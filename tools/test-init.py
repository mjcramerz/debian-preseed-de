#!/usr/bin/python3
"""Run repository checks as PID 1 of an already prepared disposable image.

This entrypoint cannot launch a container, build an image, mount host content,
install dependencies, fetch packages, or run from an ordinary host checkout.
"""
from __future__ import annotations

import os
import sys

if os.getpid() != 1:
    raise SystemExit('TEST EXECUTION REFUSED: test-init.py must be the private image PID 1')

import argparse
import ctypes
from pathlib import Path
import shutil
import signal
import subprocess

SOURCE = Path('/opt/preseed-test-source')
if Path(__file__).resolve() != SOURCE / 'tools/test-init.py':
    raise SystemExit('TEST EXECUTION REFUSED: the source must be packaged in the disposable image')
sys.path.insert(0, str(SOURCE / 'tools'))
from isolation import fixture_environment, verify_disposable_image


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('test', 'tools-test', 'check', 'build', 'audit', 'validate'))
    parser.add_argument('--pattern', default='test_*.py')
    args = parser.parse_args()
    if '/' in args.pattern or not args.pattern.startswith('test_') or not args.pattern.endswith('.py'):
        parser.error('--pattern must be a test_*.py basename pattern')
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(15, ctypes.c_char_p(b'preseed-tests'), 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), 'cannot name the private test init')
    home = verify_disposable_image()
    os.environ.clear()
    os.environ.update(fixture_environment(home))
    destination = Path('/workspace/repository')
    # The root image is immutable and the destination is a private tmpfs. No
    # host source mount or host output mount is accepted by the boundary check.
    shutil.copytree(SOURCE, destination, symlinks=False,
                    ignore=shutil.ignore_patterns('.git', '.build', '__pycache__',
                                                  '.pytest_cache', 'preseed.env',
                                                  'git_ed25519', 'git_ed25519.pub', 'id_git_ed25519'))
    python = '/usr/bin/python3'
    stages = {
        'test': [[python, '-B', '-m', 'unittest', 'discover', '-v', '-s', 'd-i/forky/tests', '-p', args.pattern]],
        'tools-test': [[python, '-B', '-m', 'unittest', 'discover', '-v', '-s', 'tools/tests', '-p', args.pattern]],
        'check': [[python, '-I', '-B', 'tools/check_build.py'],
                  [python, '-I', '-B', 'tools/check_shells.py']],
        'build': [[python, '-I', '-B', 'tools/build.py']],
        'audit': [[python, '-I', '-B', 'd-i/forky/tests/audit_codebase.py',
                   '--output', '.build/validation/audit.json']],
        'validate': [[python, '-I', '-B', 'tools/validate.py']],
    }
    environment = fixture_environment(home)
    for command in stages[args.stage]:
        process = subprocess.Popen(command, cwd=destination, env=environment,
                                   stdin=subprocess.DEVNULL, start_new_session=True)
        def forward(signum, frame):
            try:
                os.killpg(process.pid, signum)
            except ProcessLookupError:
                pass
        previous = {signum: signal.signal(signum, forward)
                    for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM)}
        try:
            status = process.wait(timeout=3600)
        finally:
            for signum in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(process.pid, signum)
                except ProcessLookupError:
                    pass
                if process.poll() is None:
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        continue
            for signum, handler in previous.items():
                signal.signal(signum, handler)
        if status:
            return status if status > 0 else 128 - status
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
