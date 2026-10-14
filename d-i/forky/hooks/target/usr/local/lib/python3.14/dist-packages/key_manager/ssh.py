"""SSH keys, profiles, certificates and the existing desktop OpenSSH agent."""
from __future__ import annotations

import ipaddress
from pathlib import Path
import re

from .core import (Tree, choose, confirm, display, dns, environment, inventory, menu,
                   name, number, private_file, prompt, publish, read_file, run, stage, text)

KEYGEN = '/usr/bin/ssh-keygen'
ALGORITHMS = ['Ed25519', 'RSA 4096', 'ECDSA P-384', 'FIDO2 Ed25519', 'FIDO2 ECDSA']


class SSH:
    def __init__(self, tree: Tree, home: Path, exports: Tree):
        self.tree, self.home, self.exports = tree, home, exports
        if tree.read('known_hosts', missing=True) is None:
            tree.write('known_hosts', b'')

    def select(self) -> str | None:
        return choose('Select SSH key', [item for item in inventory(self.tree, '.keys', '.pub')
                                          if not item.endswith('-cert')])

    def generate(self, *, ca: bool = False) -> None:
        label = name(prompt('CA name' if ca else 'Key name', 'ssh-ca' if ca else 'id_ed25519'))
        if label.endswith('-cert'):
            raise ValueError('the -cert suffix is reserved for SSH certificates')
        algorithm = choose('SSH algorithm', ALGORITHMS[:3] if ca else ALGORITHMS)
        if algorithm is None:
            return
        args = {'Ed25519': ['-t', 'ed25519'], 'RSA 4096': ['-t', 'rsa', '-b', '4096'],
                'ECDSA P-384': ['-t', 'ecdsa', '-b', '384'],
                'FIDO2 Ed25519': ['-t', 'ed25519-sk'], 'FIDO2 ECDSA': ['-t', 'ecdsa-sk']}[algorithm]
        rounds = number(prompt('Private-key KDF rounds', '100'), 64, 1000000)
        comment = text(prompt('Public comment', label))
        print('ssh-keygen will prompt for a private-key passphrase. Use a strong passphrase.')
        with stage(self.tree) as work:
            private = work / 'key'
            run([KEYGEN, *args, '-a', str(rounds), '-C', comment, '-f', str(private)])
            public = read_file(work / 'key.pub')
            run([KEYGEN, '-lf', str(work / 'key.pub')])
            folder = 'ca' if ca else '.keys'
            publish(self.tree, {folder + '/' + label: read_file(private, private=True),
                                folder + '/' + label + '.pub': public})
        print('Key created.')

    def import_key(self) -> None:
        label = name(prompt('Managed key name'))
        if label.endswith('-cert'):
            raise ValueError('the -cert suffix is reserved for SSH certificates')
        supplied = read_file(Path(prompt('Mode-0600 private key absolute path')), private=True)
        with stage(self.tree) as work:
            private = work / 'key'
            private.write_bytes(supplied)
            # ssh-keygen validates/decrypts using its controlling terminal.
            public = work / 'key.pub'
            # -y output is public, but it may need a passphrase on /dev/tty.
            # Use native conversion to a checked output rather than a shell redirect.
            from .core import public_command
            public.write_bytes(public_command([KEYGEN, '-y', '-f', str(private)]))
            run([KEYGEN, '-lf', str(public)])
            if confirm('Import this identity?'):
                publish(self.tree, {'.keys/' + label: supplied, '.keys/' + label + '.pub': read_file(public)})

    def show(self) -> None:
        label = self.select()
        if label:
            public = self.tree.read('.keys/' + label + '.pub')
            display(public.decode())
            with stage(self.tree) as work:
                path = work / 'key.pub'
                path.write_bytes(public)
                run([KEYGEN, '-lf', str(path)])

    def passphrase(self) -> None:
        label = self.select()
        if label:
            with stage(self.tree) as work:
                path = work / 'key'
                path.write_bytes(private_file(self.tree, '.keys/' + label))
                run([KEYGEN, '-p', '-a', '100', '-f', str(path)])
                self.tree.write('.keys/' + label, read_file(path, private=True))

    def profile(self) -> None:
        label = self.select()
        if not label:
            return
        profile = name(prompt('Profile name'))
        order = number(prompt('Profile order', '20'), 10, 80)
        hosts = prompt('Host aliases / patterns (space separated)').split()
        if not hosts or len(hosts) > 20 or any(not re.fullmatch(r'[A-Za-z0-9*?!_.-]{1,253}', h) for h in hosts):
            raise ValueError('invalid SSH host patterns')
        destination = prompt('HostName (DNS or IP)')
        try:
            destination = str(ipaddress.ip_address(destination))
        except ValueError:
            destination = dns(destination)
        user = name(prompt('Remote username'))
        port = number(prompt('Remote port', '22'), 1, 65535)
        preset = choose('Connection policy', ['Balanced', 'Performance', 'Hardened'])
        if preset is None:
            return
        persist = number(prompt('Reuse authenticated transport for seconds', '30'), 0, 3600)
        identity = self.tree.root / '.keys' / label
        # Earlier Host blocks win in OpenSSH; use this file ahead of Host * defaults.
        value = (f'Host {" ".join(hosts)}\n  HostName {destination}\n  User {user}\n  Port {port}\n'
                 f'  IdentityFile "{identity}"\n  IdentitiesOnly yes\n'
                 f'  IdentityAgent /run/user/{self.tree.uid}/openssh_agent\n'
                 f'  UserKnownHostsFile "{self.tree.root}/known_hosts"\n'
                 '  StrictHostKeyChecking yes\n  ForwardAgent no\n  ForwardX11 no\n'
                 '  PubkeyAcceptedAlgorithms ssh-ed25519,ssh-ed25519-cert-v01@openssh.com,'
                 'rsa-sha2-512,rsa-sha2-256,rsa-sha2-512-cert-v01@openssh.com,'
                 'rsa-sha2-256-cert-v01@openssh.com,ecdsa-sha2-nistp384,'
                 'ecdsa-sha2-nistp384-cert-v01@openssh.com,sk-ssh-ed25519@openssh.com,'
                 'sk-ssh-ed25519-cert-v01@openssh.com,sk-ecdsa-sha2-nistp256@openssh.com,'
                 'sk-ecdsa-sha2-nistp256-cert-v01@openssh.com\n'
                 '  HostKeyAlgorithms ssh-ed25519,ssh-ed25519-cert-v01@openssh.com,'
                 'rsa-sha2-512,rsa-sha2-256,rsa-sha2-512-cert-v01@openssh.com,'
                 'rsa-sha2-256-cert-v01@openssh.com,ecdsa-sha2-nistp384,'
                 'ecdsa-sha2-nistp384-cert-v01@openssh.com\n'
                 '  KexAlgorithms sntrup761x25519-sha512,sntrup761x25519-sha512@openssh.com,'
                 'mlkem768x25519-sha256,curve25519-sha256,curve25519-sha256@libssh.org\n'
                 '  Ciphers chacha20-poly1305@openssh.com,aes256-gcm@openssh.com\n'
                 '  MACs hmac-sha2-512-etm@openssh.com,hmac-sha2-256-etm@openssh.com\n'
                 '  PasswordAuthentication no\n  KbdInteractiveAuthentication no\n')
        if preset == 'Hardened':
            value += '  AddKeysToAgent no\n  ControlMaster no\n  ControlPersist no\n'
        else:
            value += (f'  AddKeysToAgent 1h\n  ControlMaster auto\n  ControlPersist {persist}s\n'
                      f'  ControlPath "{self.tree.root}/control/%C"\n')
            if preset == 'Performance':
                value += '  Compression no\n  IPQoS throughput\n'
        display(value)
        with stage(self.tree) as work:
            path = work / 'config'
            path.write_text(value, encoding='utf-8')
            run(['/usr/bin/ssh', '-G', '-F', str(path), 'key-manager-config-check'], capture=True)
        if confirm('Save this profile?'):
            publish(self.tree, {f'config.d/{order:02}-{profile}.conf': value.encode()})
            print('Existing ~/.ssh/config includes the PKI profiles for non-Git hosts.')

    def inspect_profile(self) -> None:
        label = choose('Profile', inventory(self.tree, 'config.d', '.conf'))
        if label:
            display(self.tree.read('config.d/' + label + '.conf').decode())

    def pin_host(self) -> None:
        host = prompt('Host DNS name / IP address')
        try:
            host = str(ipaddress.ip_address(host))
        except ValueError:
            host = dns(host)
        port = number(prompt('SSH port', '22'), 1, 65535)
        scan = run(['/usr/bin/ssh-keyscan', '-T', '10', '-p', str(port), host], capture=True, timeout=30)
        if not scan.strip():
            raise ValueError('host returned no key')
        with stage(self.tree) as work:
            path = work / 'known_hosts'
            path.write_bytes(scan)
            run([KEYGEN, '-lf', str(path)])
            if not confirm('Have you verified these fingerprints through an independent trusted channel?'):
                return
            run([KEYGEN, '-H', '-f', str(path)])
            old = self.tree.read('known_hosts', missing=True) or b''
            self.tree.write('known_hosts', old + read_file(path))

    def agent(self, action: str) -> None:
        if action in ('start', 'stop', 'status'):
            if action == 'stop' and not confirm('Stop the session SSH agent and discard all cached keys?'):
                return
            units = ['ssh-agent.socket'] if action == 'start' else ['ssh-agent.socket', 'ssh-agent.service']
            run(['/usr/bin/systemctl', '--user', '--no-pager', action, *units])
            return
        env = environment()
        if 'SSH_AUTH_SOCK' not in env:
            raise ValueError('the existing desktop SSH agent socket is unavailable; start the session agent')
        if action == 'list':
            run(['/usr/bin/ssh-add', '-l'], env=env)
            return
        label = self.select()
        if label:
            path = self.tree.root / '.keys' / label
            private_file(self.tree, '.keys/' + label)
            args = ['-t', '1h'] if action == 'add' else ['-d']
            run(['/usr/bin/ssh-add', *args, str(path)], env=env)

    def sign(self) -> None:
        label = self.select()
        issuer = choose('SSH CA', inventory(self.tree, 'ca', '.pub'))
        if not label or not issuer:
            return
        identity = name(prompt('Certificate identity'))
        principals = prompt('Principals (comma separated)').split(',')
        if not principals or len(principals) > 30 or any(not re.fullmatch(r'[A-Za-z0-9_.@-]{1,253}', p) for p in principals):
            raise ValueError('invalid principals')
        kind = choose('SSH certificate type', ['User', 'Host'])
        if not kind:
            return
        hours = number(prompt('Certificate lifetime in hours', '24'), 1, 8760)
        args = ['-h'] if kind == 'Host' else ['-O', 'clear', '-O', 'permit-pty']
        if kind == 'User':
            if confirm('Permit local / remote port forwarding?'):
                args += ['-O', 'permit-port-forwarding']
            if confirm('Restrict to source IP networks?'):
                networks = [str(ipaddress.ip_network(p, strict=False)) for p in prompt('Networks (comma separated)').split(',')]
                args += ['-O', 'source-address=' + ','.join(networks)]
            if confirm('Force a specific command?'):
                args += ['-O', 'force-command=' + text(prompt('Forced command'))]
        with stage(self.tree) as work:
            ca, public = work / 'ca', work / 'key.pub'
            ca.write_bytes(private_file(self.tree, 'ca/' + issuer))
            public.write_bytes(self.tree.read('.keys/' + label + '.pub'))
            import secrets
            run([KEYGEN, '-s', str(ca), '-I', identity, '-z', str(secrets.randbits(63)),
                 '-n', ','.join(principals), '-V', '-5m:+' + str(hours) + 'h', *args, str(public)])
            cert = work / 'key-cert.pub'
            run([KEYGEN, '-L', '-f', str(cert)])
            publish(self.tree, {'.keys/' + label + '-cert.pub': read_file(cert)})

    def inspect_certificate(self) -> None:
        label = choose('SSH certificate', inventory(self.tree, '.keys', '-cert.pub'))
        if label:
            with stage(self.tree) as work:
                path = work / 'certificate.pub'
                path.write_bytes(self.tree.read('.keys/' + label + '-cert.pub'))
                run([KEYGEN, '-L', '-f', str(path)])

    def export_ca(self) -> None:
        label = choose('SSH CA backup', inventory(self.tree, 'ca', '.pub'))
        if not label:
            return
        values = {'ca/' + label + '.pub': self.tree.read('ca/' + label + '.pub')}
        if confirm('Include the CA private signing key in this private backup?'):
            values['ca/' + label] = private_file(self.tree, 'ca/' + label)
        publish(self.exports, values)
        print('CA backup: ' + str(self.exports.root / 'ca'))

    def export(self) -> None:
        label = self.select()
        if label:
            secret = confirm('Export private key as well as public material?')
            values = {label + '.pub': self.tree.read('.keys/' + label + '.pub')}
            if secret:
                values[label] = private_file(self.tree, '.keys/' + label)
            cert = self.tree.read('.keys/' + label + '-cert.pub', missing=True)
            if cert is not None:
                values[label + '-cert.pub'] = cert
            publish(self.exports, values)
            print('Exported to ' + str(self.exports.root))

    def delete(self) -> None:
        label = self.select()
        if label and prompt('Type the exact key name to delete') == label:
            for path in ('.keys/' + label, '.keys/' + label + '.pub', '.keys/' + label + '-cert.pub'):
                self.tree.write(path, None)
            print('Key files deleted. Agent caches and remote authorized keys must be removed separately.')

    def run(self) -> None:
        keys = {
            'Generate SSH key': self.generate,
            'Import existing SSH private key': self.import_key,
            'Inventory / public key / fingerprint': self.show,
            'Change private-key passphrase': self.passphrase,
            'Export key': self.export,
            'Delete key files': self.delete,
        }
        connections = {
            'Create connection profile': self.profile,
            'Inspect connection profile': self.inspect_profile,
            'Validate existing ~/.ssh/config': lambda: display(run(
                ['/usr/bin/ssh', '-G', '-F', str(self.home / '.ssh/config'),
                 '--', prompt('Host alias to validate')], capture=True).decode()),
            'Scan and pin host key after fingerprint verification': self.pin_host,
        }
        agent = {
            'Agent: status': lambda: self.agent('status'),
            'Agent: start existing session socket': lambda: self.agent('start'),
            'Agent: list cached keys': lambda: self.agent('list'),
            'Agent: cache key for one hour': lambda: self.agent('add'),
            'Agent: remove cached key': lambda: self.agent('remove'),
            'Agent: stop and discard cached keys': lambda: self.agent('stop'),
        }
        certificates = {
            'Generate SSH CA': lambda: self.generate(ca=True),
            'Sign user / host SSH certificate': self.sign,
            'Inspect SSH certificate': self.inspect_certificate,
            'Back up SSH CA public / private signing material': self.export_ca,
        }
        menu('SSH keys and certificates', {
            'Key lifecycle / fingerprints / backups': lambda: menu('SSH keys', keys),
            'Connection profiles and host trust': lambda: menu('SSH connection profiles', connections),
            'Existing desktop SSH agent': lambda: menu('SSH agent', agent),
            'SSH CA / user and host certificates': lambda: menu('SSH certificates', certificates),
            'Inspect existing installer Git public identity': self.desktop_identity,
        })

    def desktop_identity(self) -> None:
        with stage(self.tree) as work:
            public = work / 'git.pub'
            public.write_bytes(read_file(self.home / '.ssh/id_git_ed25519.pub'))
            run([KEYGEN, '-lf', str(public)])
        print('The installer Git private key and encrypted passphrase remain in ~/.local/share/ssh.')
