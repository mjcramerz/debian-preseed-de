#!/usr/bin/env python3
"""Native syntax checks in disposable roots; no units are started."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

REPO = Path(sys.argv[1]).resolve()
TARGET = REPO / 'd-i/forky/hooks/target'
results = []

def write(root, relative, text, mode=0o644):
    path = root / relative.lstrip('/')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(mode)

with tempfile.TemporaryDirectory(prefix='boot-native-verify-') as temporary:
    root = Path(temporary)
    base = 'etc/systemd/system/'
    write(root, 'etc/os-release', 'ID=debian\n')
    write(root, 'etc/default/system-runtime', '')
    for executable in ('bin/true', 'usr/local/libexec/managed-nvidia-char-links',
                       'usr/local/libexec/managed-network-run', 'usr/local/libexec/apparmor-managed-modes-run',
                       'usr/libexec/install-tools/bootprofile-apply', 'usr/bin/pipewire', 'usr/bin/pipewire-pulse'):
        write(root, executable, '#!/bin/sh\nexit 0\n', 0o755)
    for target in ('sysinit', 'basic', 'multi-user', 'local-fs', 'network-pre', 'sockets', 'shutdown'):
        write(root, base + target + '.target', '[Unit]\nDescription=Syntax-check dependency fixture\nDefaultDependencies=no\n')
    for service in ('systemd-modules-load', 'systemd-udev-trigger', 'greetd', 'firstboot', 'apparmor',
                    'mullvad-apparmor', 'systemd-user-sessions', 'display-manager',
                    'systemd-remount-fs', 'systemd-sysctl', 'networking', 'NetworkManager', 'systemd-networkd'):
        write(root, base + service + '.service', '[Unit]\nDescription=Syntax-check dependency fixture\nDefaultDependencies=no\n[Service]\nType=oneshot\nExecStart=/bin/true\n')
    units = ['managed-nvidia-char-links.service', 'managed-network.service', 'apparmor-managed-modes.service',
             'bootprofile-apply.service']
    for unit in units:
        source = TARGET / base / unit
        if not source.exists():
            source = source.with_name(source.name + '.tmpl')
        text = source.read_text().replace('__INSTALLER_FILE_BOOTPROFILE_APPLY__', '/usr/libexec/install-tools/bootprofile-apply')
        write(root, base + unit, text)
    command = ['systemd-analyze', 'verify', '--man=no', '--root=' + str(root), *units]
    completed = subprocess.run(command, text=True, capture_output=True, timeout=20)
    results.append({'scope': 'four actual system units with isolated dependency/executable fixtures',
                    'units': units, 'returncode': completed.returncode,
                    'output': completed.stdout + completed.stderr})
    audio = []
    for application in ('pipewire', 'pipewire-pulse'):
        for kind in ('socket', 'service'):
            unit = application + '.' + kind
            audio.append(unit)
            text = '[Unit]\nDescription=Vendor base fixture for greeter drop-in syntax\nDefaultDependencies=no\n'
            if kind == 'service':
                text += '[Service]\nExecStart=/usr/bin/' + application + '\n'
            else:
                text += '[Socket]\nListenStream=%t/' + application + '\n'
            write(root, base + unit, text)
            dropins = list((TARGET / 'etc/systemd/user' / (unit + '.d')).glob('*.tmpl'))
            assert len(dropins) == 1, (unit, dropins)
            text = dropins[0].read_text().replace('__INSTALLER_LABWC_GREETER_USER__', '_custom_greeter')
            write(root, base + unit + '.d/' + dropins[0].name.removesuffix('.tmpl'), text)
    completed = subprocess.run(['systemd-analyze', 'verify', '--man=no', '--root=' + str(root), *audio],
                               text=True, capture_output=True, timeout=20)
    results.append({'scope': 'four actual rendered greeter drop-ins with fixture vendor bases',
                    'units': audio, 'returncode': completed.returncode,
                    'output': completed.stdout + completed.stderr})
rule = TARGET / 'etc/udev/rules.d/71-managed-nvidia-char-links.rules'
completed = subprocess.run(['udevadm', 'verify', str(rule)], text=True, capture_output=True, timeout=10)
results.append({'scope': 'actual NVIDIA udev rules', 'returncode': completed.returncode,
                'output': completed.stdout + completed.stderr})
print(json.dumps(results, indent=2))
sys.exit(0 if all(item['returncode'] == 0 for item in results) else 1)
