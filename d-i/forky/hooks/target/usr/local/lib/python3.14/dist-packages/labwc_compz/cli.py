"""Interactive terminal UI. Selection IDs, never filenames, are parsed from fzf."""
from __future__ import annotations

import argparse
import getpass
import os
from pathlib import Path
import subprocess
import sys

from . import CompzError, __version__
from .formats import available_codecs, compression, missing
from .isolation import Cancelled, execute
from .safeio import display, relative
from .volumes import recognizable, resolve


def choose(title: str, values: list[str], default: int = 1) -> int:
    print('\n' + title)
    for index, value in enumerate(values, 1):
        print(f'  {index}. {value}')
    while True:
        answer = input(f'Choice [{default}] (q cancels): ').strip()
        if answer.lower() == 'q':
            raise KeyboardInterrupt
        if not answer:
            return default - 1
        if answer.isdecimal() and 1 <= int(answer) <= len(values):
            return int(answer) - 1
        print('Enter one of the displayed numbers.')


def number(title: str, default: int, low: int, high: int) -> int:
    while True:
        value = input(f'{title} [{default}]: ').strip()
        if not value:
            return default
        if value.isascii() and value.isdecimal() and low <= int(value) <= high:
            return int(value)
        print(f'Enter an integer between {low} and {high}.')


def select(current: Path, archives: bool) -> list[str]:
    entries = []
    with os.scandir(current) as items:
        for item in items:
            if item.name.startswith('.compz-') or item.is_symlink():
                continue
            if archives:
                if not item.is_file(follow_symlinks=False) or not recognizable(item.name):
                    continue
            elif not (item.is_file(follow_symlinks=False) or item.is_dir(follow_symlinks=False)):
                continue
            entries.append(item.name)
            if len(entries) > 1000000:
                raise CompzError('Current directory has more than one million entries.')
    entries.sort()
    if not entries:
        raise CompzError('No selectable archive or file/folder exists in the current directory.')
    environment = {'PATH': '/usr/bin:/bin', 'HOME': '/nonexistent', 'LC_ALL': 'C.UTF-8',
                   'TERM': os.environ.get('TERM', 'xterm-256color')}
    records = b''.join((str(i) + '\t' + display(name)).encode('ascii') + b'\0'
                       for i, name in enumerate(entries))
    command = ['/usr/bin/fzf', '--read0', '--print0', '--multi', '--delimiter=\t', '--with-nth=2..',
               '--no-sort', '--layout=reverse', '--height=80%', '--no-preview',
               '--header=Tab selects; Enter accepts; Escape cancels. No shell previews.']
    result = subprocess.run(command, input=records, stdout=subprocess.PIPE, env=environment, check=False)
    if result.returncode in (1, 130):
        raise KeyboardInterrupt
    if result.returncode:
        raise CompzError('The file selector failed.')
    selected = []
    seen = set()
    for record in result.stdout.split(b'\0'):
        if not record:
            continue
        index = record.split(b'\t', 1)[0]
        if not index.isdigit() or int(index) >= len(entries):
            raise CompzError('Invalid file-selector response.')
        name = entries[int(index)]
        if name not in seen:
            seen.add(name)
            selected.append(name)
    if not selected:
        raise KeyboardInterrupt
    return selected


def resource_policy() -> dict:
    try:
        ram_mib = os.sysconf('SC_PHYS_PAGES') * os.sysconf('SC_PAGE_SIZE') // 1024**2
    except (ValueError, OSError):
        ram_mib = 4096
    memory = max(256, min(16384, ram_mib // 2))
    result = {'max_bytes': 20 * 1024**3, 'max_files': 100000,
              'memory_mib': memory, 'threads': min(8, os.cpu_count() or 1), 'hours': 12, 'depth': 8}
    print(f"\nLimits: 20 GiB workspace / expansion, 100000 entries, {memory} MiB RAM, 12 hours.")
    if choose('Resource limits', ['Use these limits', 'Customize limits']) == 1:
        result['max_bytes'] = number('Maximum workspace / expanded GiB', 20, 1, 1048576) * 1024**3
        result['max_files'] = number('Maximum expanded entries', 100000, 1, 1000000)
        result['memory_mib'] = number('Maximum RAM MiB', memory, 256, 1048576)
        result['threads'] = number('Maximum codec threads', result['threads'], 1, 64)
        result['hours'] = number('Maximum running hours', 12, 1, 168)
        result['depth'] = number('Maximum nested archive depth', 8, 0, 16)
    return result


def passphrase(confirm: bool) -> str:
    secret = getpass.getpass('Passphrase (never passed in process arguments): ')
    if not secret or len(secret.encode('utf-8')) > 4096 or any(c in secret for c in '\r\n\0'):
        raise CompzError('Passphrase must be nonempty, at most 4096 bytes, without line breaks or NUL.')
    if confirm and getpass.getpass('Repeat passphrase: ') != secret:
        raise CompzError('Passphrases did not match.')
    return secret


def interactive() -> None:
    if os.geteuid() == 0:
        raise CompzError('Run compz as the desktop user, not root or sudo.')
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise CompzError('The interactive menu requires a terminal.')
    absent = missing()
    if absent:
        raise CompzError('Missing managed prerequisites: ' + ', '.join(absent))
    current = Path.cwd()
    print('compz ' + __version__ + ' - ' + display(str(current)))
    print('Sources are never removed. Existing destinations are never overwritten.')
    print('Links and special files are rejected. Nested archive originals are retained.')
    action = ('compress', 'extract', 'test', 'list')[choose('Action', [
        'Compress files / folders', 'Extract archives (including split volumes)',
        'Test archives by fully decoding them', 'List verified files (fully decodes the archive)'])]
    selected = select(current, action != 'compress')
    plan = {'action': action, 'selected': selected, 'codec': 'zstd', 'tier': 1,
            'encrypted': False, 'nested': False, 'output': 'archive'}
    secret = ''
    if action == 'compress':
        codecs = available_codecs()
        codec = codecs[choose('Algorithm', [item.label for item in codecs])]
        plan['codec'] = codec.key
        plan['tier'] = choose('Compression ratio', ['Fast', 'Balanced', 'Maximum'], 2)
        print('Selected entries use a tar container, preserving filenames without argv/list-file limits.')
        print('compz automatically unwraps this container on extraction.')
        plan['encrypted'] = choose('Encryption', ['None', 'GPG AES-256 envelope (.gpg)']) == 1
        if plan['encrypted']:
            secret = passphrase(True)
        default = (selected[0] if len(selected) == 1 else 'archive') + codec.suffix
        if plan['encrypted']:
            default += '.gpg'
        output = input('Output filename [' + display(default) + ']: ') or default
        if len(relative(output)) != 1 or not output.endswith(codec.suffix + ('.gpg' if plan['encrypted'] else '')):
            raise CompzError('Output must be one filename with the displayed format suffix.')
        plan['output'] = output
    else:
        plan['nested'] = choose('Nested archives', ['Extract recursively to final files', 'Only the selected archive']) == 0
        print('GPG envelopes and native encrypted 7z/ZIP/RAR accept a private passphrase.')
        print('Native ZPAQ encryption is not used because its CLI exposes keys in argv.')
        if choose('Password-protected input?', ['No', 'Yes']) == 1:
            secret = passphrase(False)
    plan.update(resource_policy())
    if action == 'compress':
        # Catch, for example, an impossible bzip3 maximum memory budget before
        # a potentially long tar producer starts. TAR has no codec invocation.
        if codec.key != 'tar':
            compression(codec, plan['tier'], plan['threads'], plan['memory_mib'], Path('/work/archive'))
        print('Creating ' + display(plan['output']))
        result = execute(current, plan, secret)
        print('Created ' + display(str(result)))
    else:
        groups = []
        covered = set()
        for item in selected:
            if item in covered:
                continue
            group = resolve(current / item)
            covered.update(member.name for member in group.members)
            groups.append(group)
        # Each selected group is a separate atomic transaction. An error never
        # invalidates a previously completed independent archive extraction.
        for group in groups:
            operation = dict(plan, selected=[group.head.name], output=group.name)
            print('Processing ' + display(group.head.name))
            result = execute(current, operation, secret)
            print('Extracted ' + display(str(result)) if result else 'Archive verified successfully.')


def main() -> int:
    parser = argparse.ArgumentParser(description='Interactive, isolated archive operations in the current directory.')
    parser.add_argument('--version', action='version', version=__version__)
    parser.add_argument('--check', action='store_true', help='check installed executables without performing an archive operation')
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.check:
            absent = missing()
            print('\n'.join('Missing: ' + item for item in absent) if absent else 'All managed compz executables are installed.')
            return 1 if absent else 0
        interactive()
        return 0
    except (KeyboardInterrupt, EOFError, Cancelled):
        print('\nCancelled.', file=sys.stderr)
        return 130
    except (CompzError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print('compz: ' + display(str(exc)), file=sys.stderr)
        return 1
