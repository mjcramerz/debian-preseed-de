"""Installer-owned layout and explicit privilege separation between menus."""
from __future__ import annotations

import argparse
import contextlib
import json
import os
from pathlib import Path
import pwd
import re
import uuid

from managed_workflows.fs import Tree
from .core import menu, protected_directory, run
from .gpg import GPG
from .pqc import PQC
from .ssh import SSH
from .tls import TLS


def privileged_tls() -> None:
    """A unique system service owns the elevated menu and every descendant."""
    unit = 'key-manager-tls-' + uuid.uuid4().hex + '.service'
    def cancel() -> None:
        # This exact owned unit is the only system-manager cancellation target.
        run(['/usr/bin/sudo', '-n', '--', '/usr/bin/systemctl', 'stop', unit],
            capture=True, timeout=30)
    command = ['/usr/bin/sudo', '--', '/usr/bin/systemd-run', '--quiet', '--wait',
               '--pty', '--collect', '--expand-environment=no', '--service-type=exec',
               '--unit=' + unit, '--property=KillMode=control-group',
               '--property=TimeoutStopSec=15s', '--property=RuntimeMaxSec=2h',
               '--property=UMask=0077', '--property=LimitCORE=0',
               '--property=NoNewPrivileges=yes', '--', '/usr/local/bin/key-manager', '--tls']
    run(command, timeout=7230, on_cancel=cancel)


def settings() -> tuple[Path, str]:
    protected_directory(Path('/etc/key-manager'))
    with Tree(Path('/etc/key-manager'), uid=0) as config:
        value = json.loads(config.read('settings.json', limit=8192))
    if (not isinstance(value, dict) or set(value) != {'root', 'account'}
            or not isinstance(value['root'], str) or not isinstance(value['account'], str)
            or not re.fullmatch(r'/[A-Za-z0-9_/+.-]+', value['root'])
            or not re.fullmatch(r'[a-z_][a-z0-9_-]{0,31}', value['account'])):
        raise ValueError('invalid installer-owned key-manager settings')
    root = Path(value['root'])
    if root == Path('/') or '..' in root.parts or str(root) != value['root']:
        raise ValueError('invalid PKI root')
    try:
        account = pwd.getpwnam(value['account'])
    except KeyError as error:
        raise ValueError('configured desktop account does not exist') from error
    if account.pw_uid == 0:
        raise ValueError('key-manager requires a non-root desktop account')
    protected_directory(root)
    return root, value['account']


def main() -> int:
    parser = argparse.ArgumentParser(description='Manage SSH, GPG, PQC and TLS identities in the existing installer PKI layout.')
    parser.add_argument('--tls', action='store_true', help='privileged TLS-only menu (normally entered from the main menu)')
    args = parser.parse_args()
    if not os.isatty(0) or not os.isatty(1):
        raise ValueError('key-manager needs an interactive terminal')
    root, account_name = settings()
    if args.tls:
        if os.geteuid() != 0:
            raise ValueError('use sudo key-manager --tls for the TLS menu')
        protected_directory(root / 'tls')
        protected_directory(root / 'exports/tls')
        with Tree(root / 'tls', uid=0, private=True) as tree, tree.lock('.key-manager.lock'), \
                Tree(root / 'exports/tls', uid=0, private=True) as exports:
            TLS(tree, exports, pwd.getpwnam(account_name).pw_uid).run()
        return 0
    account = pwd.getpwuid(os.geteuid())
    if account.pw_uid == 0 or account.pw_name != account_name:
        raise ValueError('run the main menu as the configured desktop account; root uses --tls only')
    home = Path(account.pw_dir)
    with contextlib.ExitStack() as stack:
        trees = {}
        for folder in ('config', 'ssh', 'gpg', 'pqc'):
            trees[folder] = stack.enter_context(Tree(root / folder, private=folder != 'ssh'))
        for folder in ('ssh', 'gpg', 'pqc'):
            trees['exports/' + folder] = stack.enter_context(Tree(root / 'exports' / folder, private=True))
        stack.enter_context(trees['config'].lock('.key-manager.lock'))
        ssh = SSH(trees['ssh'], home, trees['exports/ssh'])
        gpg = GPG(trees['gpg'], home, trees['config'], trees['exports/gpg'])
        pqc = PQC(trees['pqc'], trees['exports/pqc'])
        print('Key-manager — installed Debian key management\nPKI root: ' + str(root))
        menu('Main menu', {
            'SSH keys, profiles and certificates': ssh.run,
            'GPG identities, signing and encryption': gpg.run,
            'PQC keys (native packaged OpenSSL)': pqc.run,
            'TLS / X.509 / ACME (sudo authentication)':
                privileged_tls,
            'Installed paths and existing identities': lambda: print(
                'SSH keys: ' + str(root / 'ssh/.keys') + '\n'
                'Desktop Git private identity: ' + str(home / '.local/share/ssh/private/id_git_ed25519') + '\n'
                'Desktop Git public identity: ' + str(home / '.ssh/id_git_ed25519.pub') + '\n'
                'Desktop GPG: ' + str(home / '.gnupg') + '\n'
                'Named GPG stores: ' + str(root / 'gpg') + '\n'
                'TLS: ' + str(root / 'tls') + '\n'
                'OpenSSH agent: /run/user/' + str(account.pw_uid) + '/openssh_agent'),
        })
    return 0
