"""Offline worker entered only inside the compz user-service/bubblewrap boundary."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import resource
import select
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import threading

from . import CompzError
from .formats import BY_KEY, ENV, PIPELINE, SEVEN, WORKER, available_codecs, compression, decompression, identify, stem
from .safeio import Budget, CHUNK, audit, display, extract_tar, produce_tar, publish, relative
from .volumes import VolumeSet, rar_aliases, recognizable, resolve

PLAN = Path('/plan/operation.json')
WORK = Path('/work')
INPUT = Path('/input')


def read_plan(path: Path = PLAN) -> dict:
    value = path.lstat()
    if not stat.S_ISREG(value.st_mode) or value.st_size > 1024 * 1024:
        raise CompzError('Invalid operation plan.')
    plan = json.loads(path.read_bytes())
    fields = {'action', 'selected', 'codec', 'tier', 'output', 'encrypted', 'nested',
              'max_bytes', 'max_files', 'memory_mib', 'threads', 'hours', 'depth'}
    if not isinstance(plan, dict) or plan.keys() != fields:
        raise CompzError('Invalid operation-plan fields.')
    if plan['action'] not in ('compress', 'extract', 'test', 'list') or plan['codec'] not in BY_KEY:
        raise CompzError('Invalid operation or codec.')
    if plan['action'] == 'compress' and plan['codec'] not in {codec.key for codec in available_codecs()}:
        raise CompzError('Selected compressor is unavailable on this architecture.')
    for key, low, high in (('tier', 0, 2), ('max_bytes', 1024**2, 1024**5),
                           ('max_files', 1, 1000000), ('memory_mib', 256, 1048576),
                           ('threads', 1, 64), ('hours', 1, 168), ('depth', 0, 16)):
        if type(plan[key]) is not int or not low <= plan[key] <= high:
            raise CompzError('Invalid operation resource limit.')
    if type(plan['encrypted']) is not bool or type(plan['nested']) is not bool:
        raise CompzError('Invalid operation boolean.')
    selected = plan['selected']
    if (not isinstance(selected, list) or not selected or len(selected) > plan['max_files'] or
            any(not isinstance(name, str) or len(relative(name)) != 1 for name in selected) or
            len(set(selected)) != len(selected)):
        raise CompzError('Invalid current-directory selection.')
    if not isinstance(plan['output'], str) or len(relative(plan['output'])) != 1:
        raise CompzError('Invalid output filename.')
    if plan['action'] != 'compress' and len(selected) != 1:
        raise CompzError('Extract one complete volume group per transaction.')
    return plan


def run(command: list[str], *, secret: bytes | None = None, cwd: Path | None = None) -> None:
    # All output goes to the service's private log, never directly to a terminal.
    result = subprocess.run(command, input=secret, stdin=subprocess.DEVNULL if secret is None else None,
                            stdout=sys.stderr, stderr=sys.stderr, env=ENV, cwd=WORK if cwd is None else cwd, check=False)
    if result.returncode:
        raise CompzError(f'{Path(command[0]).name} failed (status {result.returncode}); no output published.')


def pipeline(commands: list[list[str]], destination: Path) -> None:
    with destination.open('xb') as output:
        completed = subprocess.run(['/usr/bin/perl', '-T', PIPELINE],
                                   input=json.dumps({'commands': commands}).encode('utf-8'),
                                   stdout=output, stderr=sys.stderr, env=ENV, cwd=WORK, check=False)
    if completed.returncode:
        raise CompzError('A streaming pipeline stage failed; partial output was discarded.')


def gpg(source: Path, destination: Path, secret: bytes, encrypt: bool) -> None:
    if not secret:
        raise CompzError('An encryption passphrase is required.')
    # Agent sockets and ephemeral state stay in the private tmpfs, not the
    # extracted output. Shut the agent down so ExitType=cgroup can complete.
    with tempfile.TemporaryDirectory(prefix='compz-gpg-', dir='/tmp') as temporary:
        home = Path(temporary)
        command = ['/usr/bin/gpg', '--no-options', '--batch', '--no-tty', '--homedir', str(home),
                   '--pinentry-mode', 'loopback', '--passphrase-fd', '0', '--no-symkey-cache',
                   '--output', str(destination)]
        if encrypt:
            command += ['--symmetric', '--cipher-algo', 'AES256', '--compress-algo', 'none',
                        '--s2k-mode', '3', '--s2k-digest-algo', 'SHA512', '--s2k-count', '65011712']
        else:
            command += ['--decrypt']
        try:
            run(command + ['--', str(source)], secret=secret + b'\n')
        finally:
            # No socket is exported to the host; kill only this fresh homedir.
            subprocess.run(['/usr/bin/gpgconf', '--homedir', str(home), '--kill', 'gpg-agent'],
                           env=ENV, stdin=subprocess.DEVNULL, stdout=sys.stderr, stderr=sys.stderr,
                           check=True, timeout=15)


def compress(plan: dict, secret: bytes) -> Path:
    codec = BY_KEY[plan['codec']]
    target = WORK / ('result' + codec.suffix)
    producer = ['/usr/bin/python3', '-I', '-B', WORKER, 'tar-produce']
    if codec.key == 'tar':
        pipeline([producer], target)
    elif codec.stream:
        pipeline([producer, compression(codec, plan['tier'], plan['threads'], plan['memory_mib'], target)], target)
    else:
        payload = WORK / 'payload.tar'
        pipeline([producer], payload)
        run(compression(codec, plan['tier'], plan['threads'], plan['memory_mib'], target))
        payload.unlink()
    if not target.is_file() or target.is_symlink() or target.stat().st_size == 0:
        raise CompzError('Compressor produced no regular archive.')
    if plan['encrypted']:
        encrypted = WORK / (target.name + '.gpg')
        gpg(target, encrypted, secret, True)
        target.unlink()
        target = encrypted
    target.chmod(0o600)
    return target


class Extractor:
    def __init__(self, plan: dict, secret: bytes):
        self.plan = plan
        self.secret = secret
        self.budget = Budget(plan['max_bytes'], plan['max_files'])
        self.groups = 0

    def check(self, directory: Path) -> None:
        size, count = audit(directory, self.plan['max_bytes'], self.plan['max_files'], sanitize=True)
        self.budget.add(size, count)

    def unpack(self, volumes: VolumeSet, destination: Path, depth: int = 0) -> None:
        if depth > self.plan['depth']:
            raise CompzError('Nested archive depth limit reached; no partial tree published.')
        self.groups += 1
        if self.groups > 256:
            raise CompzError('Nested archive count exceeds 256.')
        destination.mkdir(mode=0o700)
        with tempfile.TemporaryDirectory(prefix='scratch-', dir=WORK) as temporary:
            scratch = Path(temporary)
            source = volumes.head
            if volumes.concatenate:
                source = scratch / re.sub(r'\.[0-9]{3,}$', '', volumes.head.name)
                total = 0
                with source.open('xb') as output:
                    for part in volumes.members:
                        with part.open('rb') as input_file:
                            while block := input_file.read(CHUNK):
                                total += len(block)
                                if total > self.plan['max_bytes']:
                                    raise CompzError('Joined split archive exceeds workspace budget.')
                                output.write(block)
            # Numbered RAR headers may not have a .rar suffix. Keep original
            # sibling names available to unrar; do not concatenate RAR volumes.
            key = 'rar' if re.fullmatch(r'.+\.r[0-9]{2,}', source.name, re.I) else identify(source.name)
            logical_name = source.name
            if key == 'gpg':
                decoded = scratch / source.name[:-4]
                if not decoded.name or decoded == source:
                    raise CompzError('Encrypted archive needs its original format extension before .gpg.')
                gpg(source, decoded, self.secret, False)
                source = decoded
                key = identify(source.name)
                logical_name = source.name
            if key == 'tar':
                with source.open('rb') as data:
                    extract_tar(data, destination, self.budget)
            elif key in ('7z', 'zip', 'rar'):
                if key == 'rar' and len(volumes.members) > 1 and not volumes.concatenate:
                    source = rar_aliases(volumes, scratch / 'rar-volumes')
                if key == 'rar' and not self.secret:
                    run(['/usr/bin/unrar-nonfree', 'x', '-cfg-', '-idq', '-or', '-p-', '--', str(source),
                         str(destination) + '/'])
                else:
                    # Bare -p prompts on stdin, not in argv/environment. Supply
                    # an empty line to avoid any hanging encrypted-input prompt.
                    run([SEVEN, 'x', '-bd', '-y', '-aou', '-spd', '-p', '-o' + str(destination),
                         '--', str(source)], secret=self.secret + b'\n')
                self.check(destination)
            elif key in ('zpaq', 'zpaqfranz'):
                # Native ZPAQ -key exposes the passphrase in process arguments.
                # Use the authenticated GPG envelope for confidential ZPAQ data.
                run(['/usr/bin/zpaqfranz', 'x', str(source), '-to', str(destination) + '/',
                     '-threads', str(self.plan['threads'])])
                self.check(destination)
            else:
                decoded = scratch / 'decoded'
                if key in ('lrzip', 'rzip'):
                    command = [BY_KEY[key].binary, '-d', '-o', str(decoded), str(source)]
                    command[1:1] = ['-q', '-c'] if key == 'lrzip' else ['-k']
                    run(command)
                else:
                    pipeline([decompression(key, source, self.plan['threads'], self.plan['memory_mib'])], decoded)
                # .tar.* and conventional aliases must actually decode to tar.
                # Raw .gz/.xz/etc remain useful for single-file compression too.
                expected_tar = ('.tar.' in logical_name.lower() or
                                logical_name.lower().endswith(('.tgz', '.txz', '.tbz', '.tbz2', '.tzst')))
                is_tar = tarfile.is_tarfile(decoded)
                if expected_tar and not is_tar:
                    raise CompzError('Archive extension promised a tar container but its content is not tar.')
                if is_tar:
                    with decoded.open('rb') as data:
                        extract_tar(data, destination, self.budget)
                else:
                    leaf = stem(logical_name)
                    publish(decoded, destination / leaf)
                    self.check(destination)
            # Native compz archives explicitly carry .tar.<codec>; unwrap only
            # their unique payload.tar, not an unrelated caller's ordinary ZIP.
            if key in ('7z', 'zip', 'rar', 'zpaq', 'zpaqfranz') and '.tar.' in logical_name.lower():
                members = list(destination.iterdir())
                if len(members) != 1 or members[0].name != 'payload.tar' or not members[0].is_file():
                    raise CompzError('Tar-wrapped archive has an unexpected payload layout.')
                payload = scratch / 'payload.tar'
                members[0].rename(payload)
                with payload.open('rb') as data:
                    extract_tar(data, destination, self.budget)
            if self.plan['nested']:
                self.nested(destination, depth + 1)

    def nested(self, directory: Path, depth: int) -> None:
        # Snapshot the pre-existing tree before unpacking child archives; each
        # child's recursion is handled by unpack(), never twice by this walk.
        pending = []
        for parent, directories, files in os.walk(directory, followlinks=False):
            directories.sort()
            covered = set()
            for filename in sorted(files):
                if filename in covered or not recognizable(filename):
                    continue
                volumes = resolve(Path(parent) / filename)
                covered.update(member.name for member in volumes.members)
                pending.append(volumes)
                if len(pending) > 256:
                    raise CompzError('Too many nested archive groups.')
        for volumes in pending:
            target = volumes.head.parent / volumes.name
            if target.exists() or target.is_symlink():
                raise CompzError('Nested extraction folder already exists; refusing to merge or overwrite.')
            self.unpack(volumes, target, depth)
            # Preserve all original inner volumes as well as the final files.


def manifest(directory: Path, target: Path) -> None:
    with target.open('x', encoding='utf-8') as output:
        for parent, directories, files in os.walk(directory, followlinks=False):
            directories.sort()
            for leaf in sorted(files):
                path = Path(parent) / leaf
                output.write(json.dumps({'path': str(path.relative_to(directory)), 'bytes': path.stat().st_size},
                                        ensure_ascii=True) + '\n')


def watch_parent(descriptor: int = 0) -> tuple[threading.Event, threading.Thread]:
    """The frontend keeps its pipe open until the entire service exits.

    EOF, an unexpected second message or a broken pipe cancels the worker even
    after SIGKILL of the frontend. Exiting the initial sandbox process makes
    bubblewrap's --die-with-parent PID namespace reap/kill remaining codecs.
    No host PID or process group is signalled by this protocol.
    """
    finished = threading.Event()

    def watch() -> None:
        while not finished.is_set():
            try:
                readable, _, _ = select.select([descriptor], [], [], 0.25)
                if readable:
                    os.read(descriptor, 1)
                    if not finished.is_set():
                        os._exit(125)
            except (OSError, ValueError):
                if not finished.is_set():
                    os._exit(125)

    thread = threading.Thread(target=watch, name='compz-parent', daemon=True)
    thread.start()
    return finished, thread


def main() -> int:
    lifeline = None
    try:
        # An inherited source fd must never provide a route back to the host.
        os.closerange(3, resource.getrlimit(resource.RLIMIT_NOFILE)[0])
        label = Path('/proc/self/attr/current').read_text().strip()
        if label not in ('compz-worker (enforce)', 'compz-worker (complain)'):
            raise CompzError('Worker requires its managed AppArmor profile; no unconfined fallback.')
        if os.geteuid() == 0 or not INPUT.is_dir() or not WORK.is_dir() or not PLAN.is_file():
            raise CompzError('Worker must run as the account inside the managed sandbox.')
        os.umask(0o077)
        plan = read_plan()
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_FSIZE, (plan['max_bytes'], plan['max_bytes']))
        if sys.argv[1:] == ['tar-produce']:
            produce_tar(INPUT, plan['selected'], sys.stdout.buffer, Budget(plan['max_bytes'], plan['max_files']))
            return 0
        if sys.argv[1:]:
            raise CompzError('Invalid worker invocation.')
        secret_line = sys.stdin.buffer.readline(32769)
        envelope = json.loads(secret_line)
        if (len(secret_line) > 32768 or not isinstance(envelope, dict) or
                envelope.keys() != {'passphrase'} or not isinstance(envelope['passphrase'], str)):
            raise CompzError('Invalid secret input envelope.')
        secret = envelope['passphrase'].encode('utf-8')
        if len(secret) > 4096 or b'\n' in secret or b'\r' in secret or b'\0' in secret:
            raise CompzError('Passphrase must be at most 4096 bytes without line breaks or NUL.')
        lifeline = watch_parent()
        if plan['action'] == 'compress':
            result = compress(plan, secret)
            result.rename(WORK / 'published')
        else:
            result = WORK / 'result'
            extractor = Extractor(plan, secret)
            extractor.unpack(resolve(INPUT / plan['selected'][0]), result)
            audit(result, plan['max_bytes'], plan['max_files'], sanitize=True)
            if plan['action'] == 'list':
                manifest(result, WORK / 'listing.jsonl')
            if plan['action'] == 'extract':
                result.rename(WORK / 'published')
        # Completion is reported only after all synchronous children were reaped.
        (WORK / 'complete').write_text('ok\n', encoding='ascii')
        return 0
    except (CompzError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError,
            tarfile.TarError) as exc:
        print('compz: ' + display(str(exc)), file=sys.stderr)
        return 1
    finally:
        if lifeline is not None:
            lifeline[0].set()
            lifeline[1].join(timeout=1)


if __name__ == '__main__':
    raise SystemExit(main())
