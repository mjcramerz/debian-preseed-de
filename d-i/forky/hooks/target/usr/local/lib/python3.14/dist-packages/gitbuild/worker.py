"""Uncredentialed worker. Never executes a command supplied by a repository."""
from __future__ import annotations
import contextlib
import hashlib
import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess
import sys
import tarfile

from managed_workflows.fs import Tree
from managed_workflows.process import CommandError, environment
from .core import (ARTIFACT, JOB, PACKAGE, VERSION, descriptor_files, record_artifacts,
                   require_subids, verified_artifacts)

SBUILD_CONFIG = '/usr/local/share/gitbuild/sbuild.conf'
KINDS = {'init', 'source', 'binary', 'local', 'bootstrap', 'lintian', 'autopkgtest', 'inspect', 'deps'}
MAX_LOG_BYTES = 64 * 1024 * 1024


def require_confinement() -> None:
    label = Path('/proc/self/attr/current').read_text().strip()
    if label != 'gitbuild-worker (enforce)':
        raise ValueError('gitbuild-worker requires its enforcing AppArmor profile; no unconfined fallback')


def validate_job(path: Path) -> None:
    home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    if (os.getuid() == 0 or not path.is_absolute() or '..' in path.parts or not JOB.fullmatch(path.name) or
            path.parent.name != 'gitbuild' or path.parent.parent.name != 'target' or
            not path.is_relative_to(home / 'Workspace')):
        raise ValueError('job must be below ~/Workspace/<repository>/target/gitbuild')
    with Tree(path, private=True):
        pass


def sandbox(job: Path, source: str, argv: list[str], epoch: str) -> list[str]:
    """No credentials, session sockets, other worktrees or network in local jobs."""
    command = ['/usr/bin/bwrap', '--unshare-all', '--die-with-parent', '--new-session', '--cap-drop', 'ALL',
               '--ro-bind', '/usr', '/usr', '--ro-bind', '/etc', '/etc',
               '--ro-bind', '/var/lib/dpkg', '/var/lib/dpkg',
               '--symlink', 'usr/bin', '/bin', '--symlink', 'usr/sbin', '/sbin',
               '--symlink', 'usr/lib', '/lib']
    if Path('/usr/lib64').exists():
        command += ['--symlink', 'usr/lib64', '/lib64']
    command += ['--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp',
                '--dir', '/home/build', '--bind', str(job / 'work'), '/build',
                '--chdir', '/build/' + source, '--', '/usr/bin/env', '-i',
                'PATH=/usr/bin:/bin', 'HOME=/home/build', 'LANG=C.UTF-8', 'LC_ALL=C.UTF-8',
                'SOURCE_DATE_EPOCH=' + epoch, *argv]
    return command


def execute(argv: list[str], job: Path, log, *, cwd: Path, env: dict, output=None) -> None:
    log.write(('\n$ ' + ' '.join(argv) + '\n').encode())
    log.flush()
    total = 0
    # The enclosing transient service owns descendants and all time limits.
    with subprocess.Popen(argv, cwd=cwd, env=env, stdout=output if output is not None else subprocess.PIPE,
                          stderr=subprocess.PIPE if output is not None else subprocess.STDOUT,
                          stdin=subprocess.DEVNULL) as child:
        while True:
            stream = child.stderr if output is not None else child.stdout
            chunk = stream.read1(65536)
            if not chunk:
                break
            total += len(chunk)
            if total <= MAX_LOG_BYTES:
                log.write(chunk)
                log.flush()
                # Bound both the private log and the forwarded terminal output.
                # Escape controls that could inject terminal commands or prompts.
                safe = ''.join(c if c in '\n\r\t' or c.isprintable() else '?'
                               for c in chunk.decode('utf-8', 'replace'))
                print(safe, end='', flush=True)
        status = child.wait()
    if total > MAX_LOG_BYTES:
        log.write(b'\n[gitbuild: log truncated at 64 MiB]\n')
        print('\n[gitbuild: output truncated at 64 MiB]', flush=True)
    if status:
        raise CommandError(f'{Path(argv[0]).name} failed (status {status})')


def orig_archive(source: Path, target: Path, epoch: int) -> None:
    """Deterministic working-tree orig tarball; never silently replace a release."""
    if target.exists() or target.is_symlink():
        raise ValueError('orig archive already exists')
    with tarfile.open(target, 'x:xz', format=tarfile.PAX_FORMAT) as archive:
        def metadata(info):
            info.uid = info.gid = 0
            info.uname = info.gname = 'root'
            info.mtime = epoch
            info.pax_headers = {}
            if info.isdir():
                info.mode = 0o755
            elif info.isfile():
                info.mode = 0o755 if info.mode & 0o111 else 0o644
            return info
        archive.add(source, arcname=source.name, recursive=False, filter=metadata)
        for path in sorted(source.rglob('*')):
            rel = path.relative_to(source)
            if rel.parts[0] == 'debian':
                continue
            archive.add(path, arcname=source.name + '/' + str(rel), recursive=False, filter=metadata)
    os.chmod(target, 0o600)


def build_commands(request: dict, job: Path, cache: Path, arch: str) -> list[list[str]]:
    kind = request['kind']
    source = request.get('source', '')
    epoch = str(request.get('epoch', 0))
    if not epoch.isdecimal() or len(epoch) > 12:
        raise ValueError('invalid source timestamp')
    tarball = cache / f'forky-{arch}.tar'
    if kind == 'bootstrap':
        return [['/usr/bin/mmdebstrap', '--mode=unshare', '--variant=buildd', '--format=tar',
                 '--architectures=' + arch, '--components=main', '--include=ca-certificates',
                 'forky', '-', 'https://deb.debian.org/debian']]
    if kind in {'init', 'source', 'binary', 'local', 'deps'}:
        if not re.fullmatch(r'[a-z0-9][A-Za-z0-9.+~\-]+', source):
            raise ValueError('invalid source directory')
        with Tree(job / 'work' / source):
            pass
    if kind == 'init':
        package, version = request.get('package', ''), request.get('version', '')
        name, email = request.get('name', ''), request.get('email', '')
        if not PACKAGE.fullmatch(package) or not VERSION.fullmatch(version) or ':' in version:
            raise ValueError('invalid initial source name or upstream version')
        if (not re.fullmatch(r'[^\x00-\x1f\x7f<>]{1,100}', name) or
                not re.fullmatch(r'[A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+', email)):
            raise ValueError('invalid maintainer identity')
        if request.get('format') not in {'native', 'quilt'}:
            raise ValueError('invalid source format')
        command = ['/usr/bin/debmake', '-p', package, '-u', version, '-f', name,
                   '-e', email, '-x', '2', '-y']
        command += ['-n'] if request['format'] == 'native' else ['-r', '1']
        return [sandbox(job, source, command, epoch)]
    if kind in {'source', 'binary'}:
        return [sandbox(job, source, ['/usr/bin/dpkg-buildpackage', '-S', '-sa', '-us', '-uc', '-nc', '-d'], epoch)]
    if kind == 'local':
        return [sandbox(job, source, ['/usr/bin/dpkg-buildpackage', '-b', '-us', '-uc',
                                     '-j' + str(request['jobs'])], epoch)]
    if kind == 'deps':
        return [sandbox(job, source, ['/usr/bin/dpkg-checkbuilddeps'], epoch)]
    bundle = Path(request.get('bundle', ''))
    validate_job(bundle)
    paths = verified_artifacts(bundle)
    if kind == 'lintian':
        changes = [str(p) for p in paths if p.suffix == '.changes']
        if not changes:
            raise ValueError('bundle contains no .changes file')
        return [['/usr/bin/lintian', '--fail-on', 'error', *changes]]
    if kind == 'inspect':
        commands = [['/usr/bin/dpkg-deb', '--info', str(p)] for p in paths if p.suffix == '.deb']
        if not commands:
            raise ValueError('bundle contains no .deb packages')
        return commands
    if kind == 'autopkgtest':
        dsc = [p for p in paths if p.suffix == '.dsc']
        debs = [p for p in paths if p.suffix == '.deb']
        if len(dsc) != 1 or not debs:
            raise ValueError('autopkgtest needs one source descriptor and built binary packages')
        descriptor_files(dsc[0])
        return [['/usr/bin/autopkgtest', '--output-dir=' + str(job / 'autopkgtest'),
                 *map(str, debs), str(dsc[0]), '--', 'unshare', '--release=forky',
                 '--arch=' + arch, '--prefix=gitbuild-autopkgtest-', '--tarball=' + str(tarball)]]
    raise ValueError('unsupported worker operation')


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        raise ValueError('worker requires exactly one job path')
    require_confinement()
    job = Path(argv[0])
    validate_job(job)
    account = pwd.getpwuid(os.getuid())
    cache = Path('/pool/cache') / account.pw_name / 'gitbuild'
    with Tree(cache, private=True):
        pass
    env = environment()
    # No inherited GIT_*, Python/Perl hooks, compiler variables, keyrings or bus.
    env.update(HOME=str(job / 'home'), XDG_CONFIG_HOME=str(job / 'home/.config'),
               XDG_CACHE_HOME=str(job / 'home/.cache'), TMPDIR='/var/tmp',
               SBUILD_CONFIG=SBUILD_CONFIG)
    # Rootless tools create mode-0700 temporary roots themselves. Their mapped
    # subordinate UID must traverse the parent: never use private HOME/Workspace
    # for TMPDIR, or relax those directories' permissions to make it work.
    os.environ.clear()
    os.environ.update(env)
    arch = subprocess.check_output(['/usr/bin/dpkg', '--print-architecture'], env=env, text=True).strip()
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]*', arch):
        raise ValueError('invalid architecture')
    with Tree(job, private=True) as tree, tree.lock('worker.lock'), contextlib.ExitStack() as resources:
        request = tree.json('request.json')
        if not isinstance(request, dict) or request.get('kind') not in KINDS:
            raise ValueError('invalid worker request')
        if type(request.get('jobs')) is not int or request['jobs'] not in range(1, 65):
            raise ValueError('invalid job count')
        kind = request['kind']
        if kind in {'bootstrap', 'binary', 'autopkgtest'}:
            # Hold this descriptor for the service lifetime, not the menu lifetime.
            image = resources.enter_context(Tree(cache, private=True))
            resources.enter_context(image.lock('image.lock'))
            require_subids()
        if kind in {'binary', 'autopkgtest'}:
            with Tree(cache, private=True) as caches, caches.open_read(f'forky-{arch}.tar'):
                pass
        commands = build_commands(request, job, cache, arch)
        source = job / 'work' / request.get('source', 'unused')
        if kind == 'init' and request.get('format') == 'quilt':
            orig_archive(source, job / 'work' / (request['package'] + '_' + request['version'] + '.orig.tar.xz'),
                         int(request['epoch']))
        with tree.parent('build.log') as (parent, name):
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=parent)
        try:
            with os.fdopen(fd, 'wb') as log:
                for command in commands:
                    if kind == 'bootstrap':
                        # Open the output before entering subordinate-UID namespaces.
                        # The mapped root need not traverse the private workspace.
                        with tree.parent('rootfs.tar') as (parent, leaf):
                            output_fd = os.open(leaf, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                                                os.O_NOFOLLOW, 0o600, dir_fd=parent)
                        with os.fdopen(output_fd, 'wb') as output:
                            execute(command, job, log, cwd=job, env=env, output=output)
                            output.flush()
                            os.fsync(output.fileno())
                    else:
                        execute(command, job, log, cwd=job, env=env)
                if kind in {'source', 'binary', 'local'}:
                    for path in sorted((job / 'work').iterdir()):
                        if ARTIFACT.fullmatch(path.name):
                            with Tree(job / 'artifacts') as output, Tree(job / 'work') as work:
                                output.copy(path.name, work, path.name)
                    if kind == 'binary':
                        dsc = list((job / 'artifacts').glob('*.dsc'))
                        if len(dsc) != 1:
                            raise ValueError('source build did not produce exactly one .dsc')
                        descriptor_files(dsc[0])
                        execute(['/usr/bin/sbuild', '--chroot-mode=unshare', '--dist=forky',
                                 '--arch=' + arch, '--chroot=' + str(cache / f'forky-{arch}.tar'),
                                 '--build-dir=' + str(job / 'artifacts'), '--no-enable-network',
                                 '--purge-build=always', '--nolog', '--run-lintian', '--no-run-autopkgtest',
                                 '--no-run-piuparts', '-j' + str(request['jobs']), str(dsc[0])],
                                job, log, cwd=job / 'artifacts', env=env)
                if kind == 'bootstrap':
                    with Tree(cache, private=True) as caches:
                        caches.copy(f'forky-{arch}.tar', tree, 'rootfs.tar')
            record_artifacts(job)
        except BaseException:
            record = tree.json('job.json')
            record['status'] = 'failed'
            tree.put_json('job.json', record)
            raise
    return 0
