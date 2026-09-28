"""Atomic no-clobber directory installation on the supported Linux target."""
import ctypes
import os


def rename_new_directory(parent: int, source: str, destination: str) -> None:
    for name in (source, destination):
        if '/' in name or name in ('', '.', '..'):
            raise ValueError('rename requires direct children')
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = libc.renameat2
    renameat2.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    renameat2.restype = ctypes.c_int
    if renameat2(parent, os.fsencode(source), parent, os.fsencode(destination), 1) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), destination)
    os.fsync(parent)
