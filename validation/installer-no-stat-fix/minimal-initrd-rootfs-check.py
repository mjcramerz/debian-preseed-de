#!/usr/bin/env python3
"""Exercise the allocator in an isolated minimal root, not a booted d-i.

Copies installed BusyBox/libraries; no download, package installation or build.
No /usr/bin/stat, /bin/stat or Python exists inside this disposable root.
An optional --before source must reproduce the reported missing-stat failure.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile


def allocator(path: Path) -> str:
    text = path.read_text()
    a = text.index('devops_install_pinned_codex() (')
    b = text.index('\n)\n\ndevops_install_codex_from_clone()', a) + 3
    return text[a:b]


def check(repository: Path, source: Path) -> dict:
    busybox = shutil.which('busybox')
    chroot = shutil.which('chroot')
    if os.geteuid() != 0 or not busybox or not chroot or not shutil.which('ldd'):
        raise RuntimeError('root, BusyBox, chroot and ldd are required; no silent skip')
    with tempfile.TemporaryDirectory(prefix='codex-minimal-initrd-') as temporary:
        root = Path(temporary)
        for name in ('bin', 'usr/bin', 'dev', 'tmp', 'target/data/codex'):
            (root/name).mkdir(parents=True, exist_ok=True)
        (root/'tmp').chmod(0o1777)
        codex = root/'target/data/codex'
        os.chown(codex, 0, 65534)
        codex.chmod(0o3770)
        dependencies = subprocess.check_output(['ldd', busybox], text=True)
        for name in set(re.findall(r'(?:=>\s+)?(/[^\s()]+)', dependencies)):
            destination = root/name.lstrip('/')
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(name, destination)
        shutil.copy2(busybox, root/'bin/busybox')
        for name in ('sh', 'ls', 'awk', 'mktemp', 'chmod', 'rm', 'mkdir', 'mv'):
            (root/'bin'/name).symlink_to('busybox')
        # Only a redirection sink is required; this is not a device/SSH fixture.
        (root/'dev/null').touch()
        shutil.copy2(repository/'d-i/forky/scripts/common/lib.sh', root/'common.sh')
        script = r'''set -eu
PATH=/bin
export PATH
[ ! -e /usr/bin/stat ] && [ ! -e /bin/stat ]
[ ! -e /usr/bin/python3 ]
if command -v stat >/dev/null 2>&1; then exit 91; fi
. /common.sh
target_root=/target
devops_fatal() { printf 'fatal: %s\n' "$*" >&2; exit 1; }
managed_git_ssh_target_action() {
  [ "$1" = clone-codex ] && [ "$#" = 2 ] || return 92
  case "$(installer_metadata_value "/target${2%/repository}" uid_gid_mode)" in
    0:*:700) ;;
    *) return 93 ;;
  esac
  mkdir "/target$2"
}
devops_install_codex_from_clone() { mv "/target$1" /target/published; }
'''
        (root/'test.sh').write_text(script + allocator(source) + '\ndevops_install_pinned_codex\n')
        result = subprocess.run([chroot, str(root), '/bin/sh', '/test.sh'],
                                env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C'},
                                text=True, capture_output=True, timeout=10)
        metadata = codex.stat()
        record = {
            'returncode': result.returncode, 'stdout': result.stdout,
            'stderr': result.stderr, 'published': (root/'target/published').is_dir(),
            'remaining_stages': [p.name for p in codex.glob('.home-clone.*')],
            'shared_root': [metadata.st_uid, metadata.st_gid, oct(stat.S_IMODE(metadata.st_mode))],
            'installer_stat_present': any((root/p).exists() for p in ('bin/stat', 'usr/bin/stat')),
        }
        assert record['remaining_stages'] == [], record
        assert record['shared_root'] == [0, 65534, '0o3770'], record
        assert not record['installer_stat_present'], record
        return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--before', type=Path)
    args = parser.parse_args()
    results = {}
    if args.before:
        before = check(args.repository, args.before)
        assert before['returncode'] != 0 and not before['published'], before
        assert 'stat: not found' in before['stderr'] and 'not root-owned' in before['stderr'], before
        results['before'] = before
    after = check(args.repository, args.repository/'d-i/forky/scripts/late/devops.sh')
    assert after['returncode'] == 0 and after['published'], after
    results['after'] = after
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
