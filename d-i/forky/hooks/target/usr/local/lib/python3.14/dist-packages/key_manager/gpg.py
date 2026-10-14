"""Explicit named GPG stores with persistent policy and independent trust state."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re

from .core import (Tree, choose, confirm, display, environment, fingerprint, menu,
                   chunks, copy_input, input_file, name, prompt, publish, publish_file, read_file, run, stage, text)

POLICIES = {'general': 'Signing, encryption and authentication',
            'signing': 'Signing identities; encryption operations disabled',
            'public': 'Public keys and verification; secret imports and trust writes disabled'}
REGISTRY = 'gpg-stores.json'
AGENT_POLICY = Path('/usr/local/share/key-manager')


def agent_policy() -> bytes:
    # The installer publishes the existing desktop skeleton policy here verbatim.
    with Tree(AGENT_POLICY, uid=0) as policy:
        return policy.read('gpg-agent.conf', limit=65536)


class GPG:
    def __init__(self, tree: Tree, home: Path, config: Tree, exports: Tree):
        self.tree, self.home, self.config, self.exports = tree, home, config, exports
        self.registry = self.load_registry()
        self.store = self.registry['active']

    def load_registry(self) -> dict:
        value = self.config.json(REGISTRY, {'active': 'desktop', 'stores': {}})
        if (not isinstance(value, dict) or set(value) != {'active', 'stores'}
                or not isinstance(value['stores'], dict) or len(value['stores']) > 100
                or not isinstance(value['active'], str)):
            raise ValueError('invalid GPG store registry')
        for label, policy in value['stores'].items():
            name(label)
            if label == 'desktop' or not isinstance(policy, str) or policy not in POLICIES:
                raise ValueError('invalid GPG store policy')
        if value['active'] != 'desktop' and value['active'] not in value['stores']:
            raise ValueError('active GPG store is not registered')
        return value

    def save_registry(self) -> None:
        self.config.put_json(REGISTRY, self.registry)

    def policy(self) -> str:
        return 'general' if self.store == 'desktop' else self.registry['stores'][self.store]

    def create_store(self) -> None:
        label = name(prompt('New store name (e.g. work, personal, release-2026)'))
        if len(self.registry['stores']) >= 100:
            raise ValueError('the GPG store registry limit is 100 named stores')
        if label == 'desktop' or label in self.registry['stores']:
            raise ValueError('that store name is already registered or reserved')
        selected = choose('Store policy', [key + ': ' + value for key, value in POLICIES.items()])
        if not selected:
            return
        policy = selected.split(':', 1)[0]
        # Existing unregistered directories are never adopted or overwritten.
        os.mkdir(label, mode=0o700, dir_fd=self.tree.fd)
        old_active = self.registry['active']
        old_registry = self.config.read(REGISTRY, missing=True)
        try:
            with Tree(self.tree.root / label, private=True) as store:
                store.write('gpg.conf', b'keyid-format 0xlong\nwith-fingerprint\nno-auto-key-retrieve\n')
                store.write('gpg-agent.conf', agent_policy())
            self.registry['stores'][label] = policy
            self.registry['active'] = label
            self.save_registry()
        except BaseException as failure:
            self.registry['stores'].pop(label, None)
            self.registry['active'] = old_active
            try:
                self.config.write(REGISTRY, old_registry)
            except (OSError, ValueError) as rollback_error:
                failure.add_note('GPG registry rollback failed: ' + str(rollback_error))
                # Keep the prepared store if its registration may have reached disk.
                raise
            with Tree(self.tree.root / label, private=True) as store:
                store.write('gpg.conf', None)
                store.write('gpg-agent.conf', None)
            os.rmdir(label, dir_fd=self.tree.fd)
            raise
        self.store = label
        print('Created isolated store. Keys and ownertrust are independent from the desktop keyring.')

    def select_store(self) -> None:
        options = ['desktop: Existing desktop keyring (Git / encrypted SSH passphrase)']
        options += [key + ': ' + POLICIES[policy] for key, policy in sorted(self.registry['stores'].items())]
        selected = choose('GPG store', options)
        if selected:
            new_store = selected.split(':', 1)[0]
            self.registry['active'] = new_store
            try:
                self.save_registry()
            except BaseException:
                self.registry['active'] = self.store
                raise
            self.store = new_store

    def homedir(self) -> Path:
        if self.store == 'desktop':
            path = self.home / '.gnupg'
            with Tree(self.home) as home:
                home.mkdir('.gnupg')
            with Tree(path, private=True) as store:
                if store.read('gpg-agent.conf', missing=True) is None:
                    store.write('gpg-agent.conf', agent_policy())
            return path
        path = self.tree.root / self.store
        # A deleted/replaced registered store is an error, never silently recreated.
        with Tree(path, private=True):
            pass
        return path

    def command(self, args: list[str], *, capture: bool = False, data: bytes | None = None,
                homedir: Path | None = None) -> bytes:
        home = self.homedir() if homedir is None else homedir
        env = environment()
        env['GNUPGHOME'] = str(home)
        value = run(['/usr/bin/gpg', '--homedir', str(home), '--no-auto-key-retrieve',
                     '--no-auto-key-import', *args], env=env, capture=True, data=data,
                    interactive=True)
        if not capture and value:
            display(value.decode('utf-8', 'replace'))
        return value

    def allowed(self, *, encrypt: bool = False) -> None:
        if self.policy() == 'public' or (encrypt and self.policy() != 'general'):
            raise ValueError('operation is not permitted by the selected store role')

    def listing(self, secret: bool = False) -> bytes:
        return self.command(['--with-colons', '--with-fingerprint',
                             '--list-secret-keys' if secret else '--list-keys'], capture=True)

    def select_key(self, *, secret: bool = False) -> str | None:
        pending = False
        keys = []
        for line in self.listing(secret).decode('utf-8').splitlines():
            fields = line.split(':')
            if fields[0] in ('pub', 'sec'):
                pending = True
            elif pending and fields[0] == 'fpr' and len(fields) >= 10:
                keys.append(fingerprint(fields[9]))
                pending = False
        selected = choose('Select full primary fingerprint', keys)
        if selected:
            self.command(['--list-options', 'show-usage', '--fingerprint', selected])
        return selected

    def generate(self) -> None:
        self.allowed()
        real_name = text(prompt('Identity name'), limit=120)
        email = prompt('Email address')
        if not re.fullmatch(r'[A-Za-z0-9._+%-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}', email):
            raise ValueError('invalid email address')
        if any(c in real_name for c in '<>') or real_name.startswith('-'):
            raise ValueError('identity name cannot contain angle brackets or start with a hyphen')
        identity = real_name + ' <' + email + '>'
        expiry = prompt('Expiry (e.g. 2y, 180d; 0 means no expiry)', '2y')
        if not re.fullmatch(r'(?:0|[1-9][0-9]{0,3}[dwmy])', expiry):
            raise ValueError('invalid expiry')
        algorithm = choose('Signing algorithm', ['Ed25519', 'RSA 4096'])
        if algorithm is None:
            return
        # Do not identify a newly generated identity by UID or keyring order.
        before = self.primary_fingerprints()
        self.command(['--quick-generate-key', identity,
                      'ed25519' if algorithm == 'Ed25519' else 'rsa4096', 'cert,sign', expiry])
        created = self.primary_fingerprints() - before
        if len(created) != 1:
            raise ValueError('cannot identify exactly one generated primary key')
        primary = created.pop()
        print('Primary created: ' + primary)
        if self.policy() == 'general':
            self.command(['--quick-add-key', primary,
                          'cv25519' if algorithm == 'Ed25519' else 'rsa4096', 'encr', expiry])
            self.command(['--quick-add-key', primary,
                          'ed25519' if algorithm == 'Ed25519' else 'rsa4096', 'auth', expiry])
        print('Back up the key and its openpgp-revocs.d revocation certificate.')

    def primary_fingerprints(self) -> set[str]:
        pending = False
        result = set()
        for line in self.listing().decode().splitlines():
            fields = line.split(':')
            if fields[0] == 'pub':
                pending = True
            elif pending and fields[0] == 'fpr' and len(fields) >= 10:
                result.add(fingerprint(fields[9]))
                pending = False
        return result

    def inspect(self) -> None:
        self.command(['--list-options', 'show-usage', '--fingerprint', '--list-keys'])
        if self.policy() != 'public':
            self.command(['--with-keygrip', '--list-secret-keys'])

    def import_keys(self) -> None:
        source = Path(prompt('Key material absolute path'))
        material = read_file(source)
        with stage(self.tree) as work:
            preview = work / 'preview'
            preview.mkdir(mode=0o700)
            (preview / 'gpg-agent.conf').write_bytes(agent_policy())
            try:
                self.command(['--batch', '--import'], data=material, homedir=preview, capture=True)
                self.command(['--fingerprint', '--list-keys'], homedir=preview)
                secret = self.command(['--with-colons', '--list-secret-keys'], homedir=preview,
                                      capture=True)
                has_secret = any(line.startswith(b'sec:') for line in secret.splitlines())
                if has_secret:
                    if read_file(source, private=True) != material:
                        raise ValueError('secret import source changed after preview')
                    print('This import contains SECRET key material.')
                if self.policy() == 'public' and has_secret:
                    raise ValueError('verification store refuses secret imports')
                if confirm('Import the displayed material into ' + self.store + '?'):
                    self.command(['--import'], data=material)
            finally:
                # Only the agent for this private preview home is stopped.
                run(['/usr/bin/gpgconf', '--homedir', str(preview), '--kill', 'gpg-agent'],
                    capture=True)

    def export(self) -> None:
        primary = self.select_key()
        if not primary:
            return
        label = name(prompt('Export name', primary))
        values = {'exports/' + self.store + '/' + label + '.pub.asc':
                  self.command(['--armor', '--export', primary], capture=True)}
        if self.policy() != 'public' and confirm('Include secret key material (protect the export backup)?'):
            values['exports/' + self.store + '/' + label + '.secret.asc'] = self.command(
                ['--armor', '--export-secret-keys', primary], capture=True)
        trust = self.command(['--export-ownertrust'], capture=True)
        filtered = b'\n'.join(line for line in trust.splitlines() if line.startswith(primary.encode() + b':'))
        values['exports/' + self.store + '/' + label + '.ownertrust'] = filtered + b'\n'
        if any(not value for value in values.values()):
            raise ValueError('GPG produced an empty export')
        publish(self.exports, {path.removeprefix('exports/'): value for path, value in values.items()})
        print('Export directory: ' + str(self.exports.root / self.store))

    def delete(self) -> None:
        primary = self.select_key()
        if primary and prompt('Type full fingerprint to delete') == primary:
            if self.policy() == 'public':
                self.command(['--delete-keys', primary])
            else:
                self.command(['--delete-secret-and-public-key', primary])
            print('Removed from this store. Published keys and signatures remain elsewhere.')

    def file_operation(self, mode: str) -> None:
        if mode in ('sign', 'clear', 'encrypt', 'sign-encrypt', 'decrypt', 'symmetric'):
            self.allowed(encrypt=mode in ('encrypt', 'sign-encrypt', 'decrypt', 'symmetric'))
        input_path = Path(prompt('Input file absolute path'))
        if mode == 'digest':
            digest = hashlib.sha256()
            with input_file(input_path, limit=16 * 1024**3) as source:
                for chunk in chunks(source):
                    digest.update(chunk)
            print(digest.hexdigest())
            return
        if mode == 'verify':
            signature = read_file(Path(prompt('Signature absolute path')))
            with stage(self.tree) as work:
                copy_input(input_path, work / 'data')
                (work / 'signature').write_bytes(signature)
                status = self.command(['--status-fd', '1', '--verify', str(work / 'signature'),
                                       str(work / 'data')], capture=True).decode('utf-8')
                if any('[GNUPG:] ' + bad in status for bad in
                       ('BADSIG', 'ERRSIG', 'EXPSIG', 'EXPKEYSIG', 'REVKEYSIG')):
                    raise ValueError('signature or signing identity is invalid, expired or revoked')
                identities = [line.split()[2] for line in status.splitlines()
                              if line.startswith('[GNUPG:] VALIDSIG ')]
                if not identities:
                    raise ValueError('GPG did not report a valid signature')
                for identity in identities:
                    print('Valid cryptographic signature from ' + fingerprint(identity))
                if not any('[GNUPG:] TRUST_' + trust in status for trust in ('FULLY', 'ULTIMATE')):
                    print('Identity trust is not established in this store. Verify the fingerprint independently.')
            return
        args = []
        if mode in ('sign', 'clear', 'sign-encrypt'):
            primary = self.select_key(secret=True)
            if not primary:
                return
            args += ['--local-user', primary]
        if mode in ('encrypt', 'sign-encrypt'):
            recipients = [fingerprint(v) for v in prompt('Recipient full fingerprints (space separated)').split()]
            if not recipients or len(recipients) > 30:
                raise ValueError('select 1–30 recipients')
            for recipient in recipients:
                args += ['--recipient', recipient]
        label = name(prompt('Output name', input_path.name + ('.asc' if mode in ('sign', 'clear') else '.gpg')))
        with stage(self.tree) as work:
            source, output = work / 'input', work / 'output'
            copy_input(input_path, source)
            operations = {'sign': ['--armor', '--detach-sign'], 'clear': ['--clearsign'],
                          'encrypt': ['--encrypt'], 'sign-encrypt': ['--sign', '--encrypt'],
                          'decrypt': ['--decrypt'], 'symmetric': ['--cipher-algo', 'AES256', '--symmetric']}
            self.command(['--output', str(output), *args, *operations[mode], '--', str(source)])
            publish_file(self.exports, self.store + '/' + label, output)
        print('Output: ' + str(self.exports.root / self.store / label))

    def trust(self, action: str) -> None:
        if action != 'show':
            self.allowed()
        if action == 'show':
            display(self.command(['--export-ownertrust'], capture=True).decode())
            return
        primary = self.select_key()
        if not primary:
            return
        if action == 'sign':
            if confirm('Locally certify this fingerprint after independent identity verification?'):
                self.command(['--quick-lsign-key', primary])
            return
        level = choose('Ownertrust', ['2 Undefined', '3 Never', '4 Marginal', '5 Full', '6 Ultimate (own keys only)'])
        if level and confirm('Set ownertrust for this fingerprint?'):
            self.command(['--import-ownertrust'], data=f'{primary}:{level[0]}:\n'.encode())

    def expiry(self) -> None:
        self.allowed()
        primary = self.select_key(secret=True)
        if primary:
            value = prompt('New expiry', '2y')
            if not re.fullmatch(r'(?:0|[1-9][0-9]{0,3}[dwmy])', value):
                raise ValueError('invalid expiry')
            subkeys = []
            pending = False
            listing = self.command(['--with-colons', '--with-fingerprint', '--list-keys', primary],
                                   capture=True)
            for line in listing.decode('utf-8').splitlines():
                fields = line.split(':')
                if fields[0] in ('pub', 'sub'):
                    pending = fields[0] == 'sub' and len(fields) > 1 and fields[1] != 'r'
                elif pending and fields[0] == 'fpr' and len(fields) >= 10:
                    subkeys.append(fingerprint(fields[9]))
                    pending = False
            # The two-argument form changes the primary; subkey arguments do not.
            # Explicit fingerprints also allow renewal of expired subkeys.
            self.command(['--quick-set-expire', primary, value])
            if subkeys:
                self.command(['--quick-set-expire', primary, value, *subkeys])

    def revoke(self) -> None:
        self.allowed()
        primary = self.select_key(secret=True)
        if not primary:
            return
        with stage(self.tree) as work:
            output = work / 'revoke.asc'
            self.command(['--armor', '--output', str(output), '--gen-revoke', primary])
            publish(self.exports, {self.store + '/' + primary + '.revoke.asc':
                                read_file(output, private=True)})
        print('Revocation certificate exported. Import and distribute it to revoke this identity.')

    def run(self) -> None:
        lifecycle = {
            'Generate identity': self.generate,
            'Import with preview': self.import_keys,
            'Export public / secret identity and selected ownertrust': self.export,
            'Change expiry': self.expiry,
            'Generate revocation certificate': self.revoke,
            'Delete key material': self.delete,
        }
        signatures = {
            'Create detached signature': lambda: self.file_operation('sign'),
            'Create cleartext signature': lambda: self.file_operation('clear'),
            'Verify detached signature': lambda: self.file_operation('verify'),
            'SHA256 digest': lambda: self.file_operation('digest'),
        }
        encryption = {
            'Encrypt to recipients': lambda: self.file_operation('encrypt'),
            'Sign and encrypt': lambda: self.file_operation('sign-encrypt'),
            'Decrypt / symmetric decrypt': lambda: self.file_operation('decrypt'),
            'Symmetric AES256 encryption': lambda: self.file_operation('symmetric'),
        }
        trust = {
            'Show ownertrust': lambda: self.trust('show'),
            'Set ownertrust': lambda: self.trust('set'),
            'Locally certify public key': lambda: self.trust('sign'),
        }
        actions = {
            'Select existing store': self.select_store,
            'Create named isolated store': self.create_store,
            'Inventory / primary and subkey fingerprints': self.inspect,
            'Key lifecycle / backups / revocation': lambda: menu('Key lifecycle', lifecycle),
            'Signatures / verification / file digests': lambda: menu('Sign and verify', signatures),
            'Encryption / decryption': lambda: menu('Encrypt and decrypt', encryption),
            'Identity certification / ownertrust': lambda: menu('Trust', trust),
            'Clear passphrase cache for this store': self.clear_cache,
        }
        while (selected := choose('GPG store: ' + self.store + ' — ' + POLICIES[self.policy()], list(actions))) is not None:
            try:
                actions[selected]()
            except (OSError, ValueError, RuntimeError) as error:
                display('Operation failed: ' + str(error))

    def clear_cache(self) -> None:
        if confirm('Stop this store\'s GPG agent and discard its cached passphrases?'):
            run(['/usr/bin/gpgconf', '--homedir', str(self.homedir()), '--kill', 'gpg-agent'], capture=True)
