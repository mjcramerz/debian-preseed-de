#!/usr/bin/env python3
"""Verify rendered unit syntax with isolated dependency fixtures; never activate units."""
from pathlib import Path
import re
import subprocess
import tempfile

REPO = Path(__file__).resolve().parents[2]
TARGET = REPO / 'd-i/forky/hooks/target'
TEMPLATES = TARGET / 'data/config/podman/templates/devops'
VALUES = {'UID': '999', 'DRIVER': 'overlay', 'CPU_WEIGHT': '100',
          'IO_WEIGHT': '100', 'TASKS_MAX': '8192', 'MEMORY_HIGH': '70%',
          'MEMORY_MAX': '85%'}
UNITS = ['podman.service', 'podman.socket', 'podman-restart.service',
         'podman-devops-bootstrap.service', 'incus-host-managed.service',
         'user@999.service', 'user-999.slice']


def main() -> int:
    with tempfile.TemporaryDirectory(prefix='podman-unit-verify-') as directory:
        root = Path(directory)
        unit_dir = root / 'etc/systemd/system'
        unit_dir.mkdir(parents=True)

        def write(path: Path, text: str, executable: bool = False) -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
            path.chmod(0o755 if executable else 0o644)

        def render(name: str) -> str:
            text = (TEMPLATES / name).read_text()
            for key, value in VALUES.items():
                text = text.replace('@' + key + '@', value)
            if re.search(r'@[A-Z_]+@', text):
                raise ValueError('unresolved template variable: ' + name)
            return text

        for name in ['podman.service', 'podman-restart.service']:
            write(unit_dir / name, render(name + '.tmpl'))
        write(unit_dir / 'podman.socket', render('podman.socket'))
        for name in ['podman-devops-bootstrap.service', 'incus-host-managed.service']:
            write(unit_dir / name, (TARGET / 'etc/systemd/system' / name).read_text())
        vendor = Path('/usr/lib/systemd/system/user@.service')
        if not vendor.is_file():
            raise RuntimeError('installed systemd user@.service template is required')
        write(unit_dir / 'user@.service', vendor.read_text())
        write(unit_dir / 'user@999.service.d/20-managed.conf', render('user-manager.conf.tmpl'))
        write(unit_dir / 'user-999.slice', '[Unit]\nDescription=Test user slice\n')
        write(unit_dir / 'user-999.slice.d/20-managed.conf', render('user-slice.conf.tmpl'))
        for name in ['sysinit', 'basic', 'default', 'shutdown', 'multi-user',
                     'local-fs', 'slices', 'timers', 'sockets', 'paths', 'network-online']:
            write(unit_dir / (name + '.target'), '[Unit]\nDescription=Dependency fixture\n')
        for name in ['systemd-logind', 'systemd-user-sessions', 'systemd-tmpfiles-setup',
                     'incus', 'incus-startup', 'dbus', 'systemd-oomd', 'user-runtime-dir@999']:
            write(unit_dir / (name + '.service'),
                  '[Unit]\nDescription=Dependency fixture\n[Service]\nType=oneshot\nExecStart=/usr/bin/true\n')
        for name in ['incus', 'incus-user']:
            write(unit_dir / (name + '.socket'),
                  '[Unit]\nDescription=Dependency fixture\n[Socket]\nListenStream=/run/' + name + '.sock\n')
        for name in ['usr/bin/true', 'usr/bin/install', 'usr/bin/podman',
                     'usr/lib/systemd/systemd', 'usr/local/libexec/podman-devops-host',
                     'usr/local/libexec/incus-host-managed']:
            write(root / name, '#!/bin/sh\nexit 99\n', executable=True)
        command = ['systemd-analyze', '--root=' + str(root), '--man=no', 'verify', *UNITS]
        print('Checking seven rendered units with dependency/executable fixtures. No activation.', flush=True)
        return subprocess.run(command, timeout=30, check=False).returncode


if __name__ == '__main__':
    raise SystemExit(main())
