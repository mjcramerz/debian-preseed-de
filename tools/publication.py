"""Atomic publication of build-owned artifacts. Never accepts environment files."""
from pathlib import Path
import hashlib
import os
import stat
import tempfile

def atomic_write(path: Path, data: bytes, mode: int) -> None:
    """Publish one builder-owned artifact and verify owner, mode and SHA-256."""
    if not path.is_absolute() or '..' in path.parts or path.parent.resolve(strict=True) != path.parent:
        raise ValueError('artifact destination must be absolute with non-symlink parents')
    if type(data) is not bytes or type(mode) is not int or not 0 <= mode <= 0o777:
        raise ValueError('artifact content must be immutable bytes with a regular permission mode')
    if path.exists() or path.is_symlink():
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid():
            raise ValueError(f'unsafe existing artifact: {path}')
    if path.name.endswith('.env'):
        raise ValueError('environment files are administrator-owned inputs, never build outputs')
    fd, temporary = tempfile.mkstemp(prefix=f'.{path.name}.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            os.fchmod(stream.fileno(), mode)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        info = path.lstat()
        if (info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != mode
                or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or hashlib.sha256(path.read_bytes()).digest() != hashlib.sha256(data).digest()):
            raise ValueError(f'publication postcondition failed: {path}')
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


SNAPSHOT_PRODUCTS = frozenset({'payload.tar.gz', 'payload.manifest', 'preseed.cfg'})

def publish_snapshot(directory: Path, products: dict[str, bytes]) -> int:
    """Publish exactly the three build products; roll back handled failures.

    This is not multi-file power-loss atomicity. Serve the complete checked
    release via an atomic deployment-directory switch, never live file copying.
    """
    if set(products) != SNAPSHOT_PRODUCTS or any(type(v) is not bytes for v in products.values()):
        raise ValueError('snapshot publication requires exactly three immutable build products')
    if not directory.is_absolute() or directory.is_symlink() or not directory.is_dir():
        raise ValueError('snapshot destination must be an existing absolute directory')
    previous = {}
    changed = []
    for name, data in products.items():
        path = directory / name
        if path.exists() or path.is_symlink():
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid():
                raise ValueError(f'unsafe snapshot output: {path}')
            old = (path.read_bytes(), stat.S_IMODE(info.st_mode))
        else:
            old = None
        previous[name] = old
        if old != (data, 0o644):
            changed.append(name)
    attempted = []
    try:
        for name in changed:
            attempted.append(name)
            atomic_write(directory / name, products[name], 0o644)
    except BaseException:
        for name in reversed(attempted):
            path = directory / name
            old = previous[name]
            if old is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write(path, *old)
        raise
    return len(changed)
