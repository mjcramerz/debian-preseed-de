#!/usr/bin/python3 -ISB
"""Verify a raw Linux module's detached CMS signature against one managed MOK.

Only the bounded trailer is interpreted here. Packaged OpenSSL performs the
cryptography, with embedded signer certificates disabled and an explicit private
copy of the configured public certificate. No firmware or kernel state is read.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import resource
import shutil
import signal
import stat
import struct
import subprocess
import sys
import tempfile
import time

MAGIC = b'~Module signature appended~\n'
TRAILER_BYTES = 12
MAX_MODULE_BYTES = 512 * 1024 * 1024
MAX_SIGNATURE_BYTES = 1024 * 1024
MAX_CERTIFICATE_BYTES = 1024 * 1024


class InvalidSignature(ValueError):
    pass


class VerificationUnavailable(RuntimeError):
    pass

class DecompressionUnknown(VerificationUnavailable):
    pass


def identity(info):
    return (info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def open_regular(path: Path, maximum: int):
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o022 or info.st_nlink != 1
                or not 0 < info.st_size <= maximum):
            raise VerificationUnavailable('signature input is not a safe bounded regular file')
        return fd, info
    except BaseException:
        os.close(fd)
        raise


def copy_range(fd: int, offset: int, length: int, destination: Path):
    with destination.open('xb') as output:
        while length:
            data = os.pread(fd, min(length, 65536), offset)
            if not data:
                raise VerificationUnavailable('signature input changed during snapshot')
            output.write(data)
            offset += len(data)
            length -= len(data)


def snapshot_inputs(module: Path, certificate: Path, workspace: Path):
    fd, before = open_regular(module, MAX_MODULE_BYTES)
    try:
        trailer_offset = before.st_size - len(MAGIC) - TRAILER_BYTES
        if trailer_offset <= 0:
            raise InvalidSignature('module has no supported signature trailer')
        tail = os.pread(fd, len(MAGIC) + TRAILER_BYTES, trailer_offset)
        if len(tail) != len(MAGIC) + TRAILER_BYTES or not tail.endswith(MAGIC):
            raise InvalidSignature('module has no supported signature trailer')
        # sign-file emits detached PKCS#7/CMS (id_type 2), with all legacy
        # algorithm, signer-name, key-id and padding bytes zero.
        if tail[:8] != b'\x00\x00\x02\x00\x00\x00\x00\x00':
            raise InvalidSignature('module uses an unsupported signature trailer')
        signature_length = struct.unpack('>I', tail[8:12])[0]
        if not 0 < signature_length <= min(MAX_SIGNATURE_BYTES, trailer_offset - 1):
            raise InvalidSignature('module signature length is invalid')
        unsigned_length = trailer_offset - signature_length
        copy_range(fd, 0, unsigned_length, workspace / 'module')
        copy_range(fd, unsigned_length, signature_length, workspace / 'signature.der')
        if identity(os.fstat(fd)) != identity(before):
            raise VerificationUnavailable('module changed during signature snapshot')
    finally:
        os.close(fd)
    fd, before = open_regular(certificate, MAX_CERTIFICATE_BYTES)
    try:
        data = os.pread(fd, before.st_size + 1, 0)
        if len(data) != before.st_size or identity(os.fstat(fd)) != identity(before):
            raise VerificationUnavailable('managed certificate changed during signature snapshot')
        if re.fullmatch(
            rb'\s*-----BEGIN CERTIFICATE-----\r?\n[A-Za-z0-9+/=\r\n]+-----END CERTIFICATE-----\s*',
            data,
        ) is None:
            raise VerificationUnavailable('managed certificate must contain exactly one public certificate')
        (workspace / 'certificate.pem').write_bytes(data)
    finally:
        os.close(fd)


def verify(module: Path, certificate: Path):
    workspace = Path(tempfile.mkdtemp(prefix='secure-boot.module-verify.', dir='/tmp'))
    child = None
    cleanup = True
    try:
        snapshot_inputs(module, certificate, workspace)
        # -noverify skips CA-chain discovery for our explicitly trusted MOK;
        # it does not disable content/signature verification. -nointern forbids
        # substitution by certificates embedded in the hostile CMS envelope.
        child = subprocess.Popen(
            ['/usr/bin/openssl', 'cms', '-verify', '-binary', '-inform', 'DER',
             '-in', str(workspace / 'signature.der'), '-content', str(workspace / 'module'),
             '-nointern', '-certfile', str(workspace / 'certificate.pem'), '-noverify',
             '-out', '/dev/null'],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'},
        )
        try:
            status = child.wait(timeout=30)
        except subprocess.TimeoutExpired as exc:
            raise VerificationUnavailable('module signature verification timed out') from exc
        if status != 0:
            raise InvalidSignature('module is not signed by the managed MOK')
    finally:
        if child is not None and child.returncode is None:
            try:
                child.kill()
                child.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                cleanup = False
        if cleanup:
            shutil.rmtree(workspace)
        else:
            raise VerificationUnavailable(
                f'module verifier termination is unknown; retained {workspace}'
            )


def decompress(module: Path, destination: Path):
    """Pin compressed input and enforce the expansion limit before disk writes."""
    commands = {'.gz': ['/usr/bin/gzip', '-d', '-c'],
                '.xz': ['/usr/bin/xz', '-d', '-c'],
                '.zst': ['/usr/bin/zstd', '-d', '-q', '-c']}
    command = commands.get(module.suffix)
    if command is None and module.suffix != '.ko':
        raise VerificationUnavailable('unsupported module compression')
    directory = destination.parent
    info = directory.lstat()
    if (directory.resolve(strict=True) != directory or not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.getuid() or info.st_mode & 0o077 or destination.name != 'module.ko'):
        raise VerificationUnavailable('decompression requires the private module workspace')
    if command is not None and (not hasattr(os, 'pidfd_open') or not hasattr(signal, 'pidfd_send_signal')):
        raise VerificationUnavailable('pinned decompressor supervision is unavailable')
    source_fd, before = open_regular(module, MAX_MODULE_BYTES)
    child = None
    pidfd = None
    try:
        with destination.open('xb') as output:
            if command is None:
                end = time.monotonic() + 60
                offset = 0
                while offset < before.st_size:
                    if time.monotonic() >= end:
                        raise VerificationUnavailable('module copy deadline exceeded')
                    chunk = os.pread(source_fd, min(65536, before.st_size - offset), offset)
                    if not chunk:
                        raise VerificationUnavailable('module changed during bounded copy')
                    output.write(chunk)
                    offset += len(chunk)
            else:
                # This helper is a dedicated process. Limit inherited native
                # decompressor writes before it receives any compressed bytes.
                _, hard_limit = resource.getrlimit(resource.RLIMIT_FSIZE)
                write_limit = (MAX_MODULE_BYTES if hard_limit == resource.RLIM_INFINITY
                               else min(MAX_MODULE_BYTES, hard_limit))
                resource.setrlimit(resource.RLIMIT_FSIZE, (write_limit, write_limit))
                child = subprocess.Popen(command, stdin=source_fd, stdout=output,
                    stderr=subprocess.DEVNULL, env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
                try:
                    pidfd = os.pidfd_open(child.pid)
                except OSError as exc:
                    # No unverified numeric-PID signaling fallback.
                    raise DecompressionUnknown(f'cannot pin module decompressor; retain {directory}') from exc
                try:
                    status = child.wait(timeout=60)
                except subprocess.TimeoutExpired as exc:
                    raise VerificationUnavailable('module decompression deadline exceeded') from exc
                if status != 0:
                    raise VerificationUnavailable('module decompression failed or exceeded its size limit')
            if identity(os.fstat(source_fd)) != identity(before):
                raise VerificationUnavailable('module changed during decompression')
            output.flush()
            size = os.fstat(output.fileno()).st_size
            if not 0 < size <= MAX_MODULE_BYTES:
                raise VerificationUnavailable('decompressed module exceeds its byte limit')
    finally:
        os.close(source_fd)
        try:
            if child is not None and child.returncode is None:
                if pidfd is None:
                    raise DecompressionUnknown(f'module decompressor ownership is unknown; retain {directory}')
                try:
                    signal.pidfd_send_signal(pidfd, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except OSError as exc:
                    raise DecompressionUnknown(f'module decompressor termination could not be requested; retain {directory}') from exc
                try:
                    child.wait(timeout=5)
                except (OSError, subprocess.TimeoutExpired) as exc:
                    raise DecompressionUnknown(f'module decompressor termination is unknown; retain {directory}') from exc
        finally:
            if pidfd is not None:
                os.close(pidfd)


def main(argv):
    expanding = len(argv) == 3 and argv[0] == '--decompress'
    if not expanding and len(argv) != 2:
        print('usage: verify-module-signature.py MODULE CERTIFICATE | --decompress MODULE DESTINATION', file=sys.stderr)
        return 2
    os.umask(0o077)
    try:
        if expanding:
            decompress(Path(argv[1]), Path(argv[2]))
        else:
            verify(Path(argv[0]), Path(argv[1]))
    except DecompressionUnknown as exc:
        print(f'module decompression outcome unknown: {exc}', file=sys.stderr)
        return 3
    except InvalidSignature:
        return 1
    except (OSError, VerificationUnavailable) as exc:
        print(f'module signature verification unavailable: {exc}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
