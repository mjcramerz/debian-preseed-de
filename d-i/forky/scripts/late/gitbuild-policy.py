#!/usr/bin/python3 -I
"""Installation-only private storage and collision-checked subordinate-ID setup."""
from __future__ import annotations
import fcntl
import os
from pathlib import Path
import pwd
import re
import subprocess
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, '/usr/local/lib/python3.14/dist-packages')
from managed_workflows.fs import Tree
from gitbuild.core import private_child


def ranges(text: str) -> list[tuple[str, int, int]]:
    result = []
    for line in text.splitlines():
        if not line or line.startswith('#'):
            continue
        values = line.split(':')
        if len(values) != 3 or not values[1].isdecimal() or not values[2].isdecimal():
            raise ValueError('malformed subordinate ID database')
        start, count = map(int, values[1:])
        if start < 1 or count < 1 or start + count > 2**32 - 1:
            raise ValueError('invalid subordinate ID range')
        result.append((values[0], start, start + count))
    return result


def free_range(existing, low: int, high: int, count: int = 65536) -> tuple[int, int]:
    if low < 1 or high >= 2**32 - 1 or high < low:
        raise ValueError('invalid subordinate ID allocation policy')
    candidate = low
    for _, start, end in sorted(existing, key=lambda item: item[1]):
        if end <= candidate:
            continue
        if start >= candidate + count:
            break
        candidate = end
    if candidate + count - 1 > high:
        raise ValueError('no collision-free subordinate ID range available')
    return candidate, candidate + count - 1


def main(argv):
    if os.getuid() != 0 or len(argv) != 1 or not re.fullmatch(r'[a-z_][a-z0-9_-]*', argv[0]):
        raise ValueError('root and exactly one canonical account are required')
    account = pwd.getpwnam(argv[0])
    if account.pw_uid == 0:
        raise ValueError('gitbuild may not use root')
    with Tree(Path('/etc'), uid=0) as etc, etc.lock('.gitbuild-subids.lock'):
        login = etc.read('login.defs').decode()
        for name, kind in (('subuid', 'UID'), ('subgid', 'GID')):
            raw = etc.read(name, missing=True)
            entries = ranges(raw.decode() if raw is not None else '')
            owned = [entry for entry in entries if entry[0] in (account.pw_name, str(account.pw_uid))]
            if not any(end - start >= 65536 for _, start, end in owned):
                def setting(key, default):
                    values = re.findall(r'^\s*' + key + r'\s+([0-9]+)\s*(?:#.*)?$', login, re.M)
                    if len(values) > 1:
                        raise ValueError('duplicate subordinate ID policy')
                    return int(values[0]) if values else default
                low = setting('SUB_' + kind + '_MIN', 100000)
                high = setting('SUB_' + kind + '_MAX', 600100000)
                first, last = free_range(entries, low, high)
                if raw is None:
                    etc.write(name, b'', mode=0o644)
                subprocess.run(['/usr/sbin/usermod', '--add-sub' + kind.lower() + 's',
                                str(first) + '-' + str(last), '--', account.pw_name],
                               env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C.UTF-8'},
                               timeout=30, check=True)
                updated = ranges(etc.read(name).decode())
                if (account.pw_name, first, last + 1) not in updated:
                    raise ValueError('subordinate ID allocation was not retained')
    # Drop to the target account before creating private children. Existing
    # /pool parents remain mode 2770; signing/build state is never group-readable.
    os.initgroups(account.pw_name, account.pw_gid)
    os.setgid(account.pw_gid)
    os.setuid(account.pw_uid)
    os.umask(0o077)
    for root in ('/pool/cache', '/pool/db'):
        private_child(Path(root) / account.pw_name, 'gitbuild')
    with Tree(Path(account.pw_dir)) as home:
        home.mkdir('Workspace')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main(sys.argv[1:]))
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print('gitbuild installation: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
