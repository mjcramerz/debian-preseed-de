"""Real Debian shell clients connected to a private debconf protocol backend.

The client side is a BusyBox chroot with Debian preseed/confmodule source
fixtures. A duplex socket supplies the inherited d-i stdin/FD-3 connection.
The backend is the installed Perl debconf File driver, NOT compiled cdebconf.
Only log-output and local-file preseed_fetch are replaced with narrow shims.
No host database, device, mount, package installation or network is modified.
"""
from __future__ import annotations
import os
from pathlib import Path
import select
import shlex
import shutil
import socket
import stat
import subprocess
import threading
import time

from process_fixture import stop_test_tree
from test_bootstrap_portability import InstallerShellSandbox

FIXTURES = Path(__file__).parent / 'fixtures/debian-preseed'


class DebconfSandbox(InstallerShellSandbox):
    def __init__(self, root: Path):
        super().__init__(root)
        for name in ('usr/share/debconf', 'lib/preseed', 'var/lib/preseed', 'var/run'):
            (root / name).mkdir(parents=True, exist_ok=True)
        for src, dest in [('confmodule', 'usr/share/debconf/confmodule'),
                          ('preseed.sh', 'lib/preseed/preseed.sh'),
                          ('debconf-set-selections', 'bin/debconf-set-selections'),
                          ('preseed_command', 'bin/preseed_command')]:
            shutil.copyfile(FIXTURES / src, root / dest)
            (root / dest).chmod(0o755)
        (root / 'bin/logger').unlink()
        (root / 'bin/logger').write_text('#!/bin/sh\nprintf "%s\\n" "$*" >>/var/log/fixture-syslog\n')
        (root / 'bin/logger').chmod(0o755)
        # No pipe on stdin: preserve the live protocol for preseed/run children.
        (root / 'bin/log-output').write_text('#!/bin/sh\n[ "$1" != -t ] || shift 2\n"$@" >>/var/log/fixture-child.log 2>&1\n')
        (root / 'bin/log-output').chmod(0o755)
        (root / 'bin/preseed_fetch').write_text('#!/bin/sh\ncase "$1" in file:///*) cp "${1#file://}" "$2";; *) exit 1;; esac\n')
        (root / 'bin/preseed_fetch').chmod(0o755)
        try:
            os.mknod(root / 'dev/urandom', stat.S_IFCHR | 0o444, os.makedev(1, 9))
        except PermissionError:
            # Enough entropy for hostname-generation tests; no real disk nodes.
            (root / 'dev/urandom').write_bytes(os.urandom(65536))
        self.env.update(DEBIAN_HAS_FRONTEND='1', DEBCONF_REDIR='1',
                        DEBCONF_USE_CDEBCONF='1', DEBCONF_OLD_FD_BASE='4')


class PrivateDebconf:
    def __init__(self, root: Path):
        root.mkdir(parents=True)
        config = root / 'debconf.conf'
        config.write_text('Config: test_config\nTemplates: test_templates\n\n'
                          f'Name: test_config\nDriver: File\nMode: 600\nFilename: {root}/config.dat\n\n'
                          f'Name: test_templates\nDriver: File\nMode: 600\nFilename: {root}/templates.dat\n')
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(('DEBCONF_', 'DEBIAN_'))}
        self.env.update(DEBCONF_SYSTEMRC=str(config), DEBIAN_FRONTEND='noninteractive')
        questions = ('debian-installer/dummy', 'preseed/include', 'preseed/include/checksum',
                     'preseed/include_command', 'preseed/run', 'preseed/run/checksum',
                     'preseed/interactive', 'preseed/command_failed')
        data = ''.join(f'd-i {q} string \n' for q in questions)
        subprocess.run(['debconf-set-selections'], env=self.env, input=data, text=True,
                       capture_output=True, check=True, timeout=10)
        self.process = subprocess.Popen(['debconf-communicate', 'd-i'], env=self.env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.lock = threading.Lock()
        self.closed = False

    def exchange(self, request: bytes) -> bytes:
        with self.lock:
            self.process.stdin.write(request + b'\n')
            self.process.stdin.flush()
            if not select.select([self.process.stdout], [], [], 10)[0]:
                raise TimeoutError('private debconf backend did not reply')
            answer = self.process.stdout.readline()
            if not answer:
                raise RuntimeError('private debconf backend closed its pipe')
            return answer.rstrip(b'\n')

    def value(self, question: str, flag: str | None = None) -> str:
        command = f'FGET {question} {flag}' if flag else f'GET {question}'
        result = self.exchange(command.encode())
        if not result.startswith(b'0 '):
            raise AssertionError(f'GET failed for {question}: {result[:3]!r}')
        return result[2:].decode()

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.process.stdin.close()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        self.process.stdout.close()


class ProtocolSession:
    """One inherited frontend connection, with optional reply fault injection."""
    def __init__(self, box: DebconfSandbox, backend: PrivateDebconf, code: str, *,
                 env=None, raw=False, override=None):
        self.backend, self.override = backend, override
        self.requests = []
        self.errors = []
        self.server, child = socket.socketpair()
        # FD 4-6 emulate cdebconf's saved stdio. FD 0 is a live duplex socket.
        prelude = 'exec 4</dev/null 5>&1 6>&2; '
        prelude += 'exec 1>&0; unset DEBCONF_REDIR; ' if raw else 'exec 3>&0; '
        self.process = subprocess.Popen(box.command(prelude + code), stdin=child,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env={**box.env, **(env or {})},
            start_new_session=True)
        child.close()
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def serve(self):
        try:
            with self.server.makefile('rb') as reader:
                while True:
                    request = reader.readline()
                    if not request:
                        return
                    request = request.rstrip(b'\n')
                    # Retain requests only in test memory; never in release logs.
                    self.requests.append(request)
                    answer = self.override(request) if self.override else ...
                    if answer is ...:
                        answer = self.backend.exchange(request)
                    if answer is None:
                        self.server.shutdown(socket.SHUT_WR)
                        return
                    self.server.sendall(answer + b'\n')
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as error:
            self.errors.append(type(error).__name__)

    def finish(self, timeout=25, fatal_path: Path | None = None):
        deadline = time.monotonic() + timeout
        while self.process.poll() is None and time.monotonic() < deadline:
            if fatal_path and fatal_path.is_file():
                break
            time.sleep(.02)
        timed_out = self.process.poll() is None
        if timed_out:
            stop_test_tree(self.process)
        out, err = self.process.communicate(timeout=5)
        try:
            self.server.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.server.close()
        self.thread.join(timeout=5)
        return subprocess.CompletedProcess(self.process.args, self.process.returncode,
                                           out.decode(), err.decode()), timed_out

    def close(self):
        if self.process.poll() is None:
            stop_test_tree(self.process)
        self.process.communicate(timeout=5)
        try:
            self.server.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.server.close()
        self.thread.join(timeout=5)
