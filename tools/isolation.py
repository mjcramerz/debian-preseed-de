"""Fail closed before tests import runtime code or execute fixture commands.

The checkout must be a private copy in a prepared rootless disposable image.
An environment variable, chroot, temporary directory or host-root bind is not
an isolation boundary. This module never provisions or contacts a host daemon.
"""
from __future__ import annotations

import fcntl
import os
from pathlib import Path
import stat
import socket

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = Path('/workspace')
_verified_pid: int | None = None
NS_GET_USERNS = 0xB701


def _refuse(reason: str) -> None:
    raise SystemExit('TEST EXECUTION REFUSED: ' + reason +
                     '. Use the prepared disposable environment described in '
                     'docs/test-isolation.md; host execution has no override.')


def _mounts() -> dict[str, tuple[str, str, set[str]]]:
    mounts = {}
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        fields = line.split()
        separator = fields.index('-')
        root, target, options = fields[3:6]
        filesystem = fields[separator + 1]
        # Escape sequences and repeated mounts make the boundary ambiguous.
        if '\\' in root or '\\' in target or target in mounts:
            _refuse('ambiguous mount inventory')
        mounts[target] = (root, filesystem, set(options.split(',')))
    return mounts


def verify_disposable_image() -> Path:
    """Inspect only the prepared image's own kernel and mount boundaries."""
    try:
        mappings = [tuple(map(int, line.split())) for line in
                    Path('/proc/self/uid_map').read_text().splitlines()]
        if not mappings or any(len(row) != 3 for row in mappings):
            _refuse('invalid user namespace mapping')
        if not any(inside == 0 and outside != 0 and count > 0
                   for inside, outside, count in mappings):
            _refuse('a rootless user namespace is required')
        if any(outside == 0 for inside, outside, count in mappings):
            _refuse('the outer root UID must not be mapped')
        status = dict(line.split(':', 1) for line in
                      Path('/proc/self/status').read_text().splitlines())
        if int(status['Pid']) != os.getpid():
            _refuse('procfs must belong to the private PID namespace')
        user_namespace = os.stat('/proc/self/ns/user')
        for name in ('net', 'pid', 'mnt', 'ipc', 'uts', 'cgroup'):
            descriptor = os.open('/proc/self/ns/' + name, os.O_RDONLY | os.O_CLOEXEC)
            try:
                owner = fcntl.ioctl(descriptor, NS_GET_USERNS)
                try:
                    info = os.fstat(owner)
                    if (info.st_dev, info.st_ino) != (user_namespace.st_dev, user_namespace.st_ino):
                        _refuse(name + ' namespace is not owned by the private user namespace')
                finally:
                    os.close(owner)
            finally:
                os.close(descriptor)
        if {name for index, name in socket.if_nameindex()} != {'lo'}:
            _refuse('the private network must contain loopback only')
        if status.get('NoNewPrivs', '').strip() != '1' or any(
                int(status[name].strip(), 16) for name in ('CapInh', 'CapPrm', 'CapEff', 'CapBnd')):
            _refuse('no-new-privileges and dropped process capabilities are required')
        mounts = _mounts()
        root, filesystem, options = mounts.get('/', ('', '', set()))
        if root != '/' or filesystem not in {'overlay', 'fuse.overlayfs'} or 'ro' not in options:
            _refuse('the disposable image root must be read-only')
        for target in ('/workspace', '/run', '/tmp', '/sys', '/dev'):
            root, filesystem, options = mounts.get(target, ('', '', set()))
            if root != '/' or filesystem != 'tmpfs' or 'nosuid' not in options:
                _refuse(target + ' must be a private tmpfs')
        workspace_info = WORKSPACE.lstat()
        if not stat.S_ISDIR(workspace_info.st_mode) or workspace_info.st_uid != 0 or workspace_info.st_mode & 0o022:
            _refuse('/workspace must be a root-owned non-writable fixture parent')
        if mounts.get('/proc', ('', '', set()))[:2] != ('/', 'proc'):
            _refuse('private procfs is required')
        for target, (root, filesystem, options) in mounts.items():
            if target == '/':
                continue
            # Reject host files, host sockets, devices, sysfs, cgroups, and all
            # persistent/bind-mounted filesystems, including /etc/hosts binds.
            if root != '/' or filesystem not in {'tmpfs', 'proc', 'devpts', 'mqueue'}:
                _refuse('non-private mount at ' + target)
            if filesystem == 'proc' and target != '/proc':
                _refuse('additional procfs mount at ' + target)
        if Path('/usr/local').exists() and any(Path('/usr/local').iterdir()):
            # Packaged images may contain empty prefix directories only.
            for path in Path('/usr/local').rglob('*'):
                if not path.is_dir() or path.is_symlink():
                    _refuse('installed /usr/local content is forbidden in the test image')
        if Path('/proc/1/comm').read_text().strip() != 'preseed-tests':
            _refuse('the dedicated test init must own the private PID namespace')
        home = WORKSPACE / 'home' / str(os.geteuid())
        home.mkdir(parents=True, mode=0o700, exist_ok=True)
        info = home.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            _refuse('unsafe fixture HOME')
    except (OSError, ValueError, KeyError) as error:
        _refuse('cannot verify the isolation boundary (' + type(error).__name__ + ')')
    return home


def fixture_environment(home: Path) -> dict[str, str]:
    return {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'HOME': str(home),
            'TMPDIR': '/tmp', 'LC_ALL': 'C.UTF-8', 'LANG': 'C.UTF-8',
            'PYTHONDONTWRITEBYTECODE': '1'}


def require_test_isolation() -> None:
    """Check the boundary before any test discovery/import side effects."""
    global _verified_pid
    if _verified_pid == os.getpid():
        return
    # Refuse an ordinary checkout before reading any operating-system state.
    if ROOT != WORKSPACE / 'repository':
        _refuse('the checkout is outside the private /workspace/repository copy')
    verify_disposable_image()
    # test-init supplies the minimal initial environment. Explicit private
    # fixture buses/displays must survive checks in child fixture processes.
    _verified_pid = os.getpid()


if __name__ == '__main__':
    if ROOT == WORKSPACE / 'repository':
        require_test_isolation()
    else:
        # A copied Makefile fixture uses the original verified image gate.
        # An ordinary host checkout has no private canonical gate to load.
        canonical = WORKSPACE / 'repository/tools/isolation.py'
        if not canonical.is_file():
            _refuse('the checkout is outside the private /workspace/repository copy')
        import sys
        sys.path.insert(0, str(canonical.parent))
        from isolation import require_test_isolation as verify_canonical
        verify_canonical()
