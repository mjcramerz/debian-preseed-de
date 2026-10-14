"""Native packaged OpenSSL PQC only; no provider downloads or compilation."""
from __future__ import annotations

from pathlib import Path

from .core import (Tree, choose, confirm, display, encrypt_pkcs8, inventory, menu, name, prompt,
                   private_file, publish, read_file, run, stage)

ALGORITHMS = ['ML-KEM-512', 'ML-KEM-768', 'ML-KEM-1024',
              'ML-DSA-44', 'ML-DSA-65', 'ML-DSA-87']


class PQC:
    def __init__(self, tree: Tree, exports: Tree):
        self.tree, self.exports = tree, exports

    def generate(self) -> None:
        algorithm = choose('PQC algorithm (KEM establishes secrets; DSA signs)', ALGORITHMS)
        if not algorithm:
            return
        supported = run(['/usr/bin/openssl', 'list',
                         '-kem-algorithms' if algorithm.startswith('ML-KEM') else '-signature-algorithms'],
                        capture=True).decode()
        if algorithm not in supported:
            raise ValueError('the installed OpenSSL does not support ' + algorithm +
                             '; use a signed package providing it')
        label = name(prompt('Key name'))
        encrypted = confirm('Encrypt the private key with a passphrase?')
        with stage(self.tree) as work:
            private, public = work / 'key.pem', work / 'public.pem'
            run(['/usr/bin/openssl', 'genpkey', '-algorithm', algorithm,
                 '-out', str(private)])
            run(['/usr/bin/openssl', 'pkey', '-in', str(private), '-pubout', '-out', str(public)])
            run(['/usr/bin/openssl', 'pkey', '-pubin', '-in', str(public), '-pubcheck'])
            if encrypted:
                encrypted_key = work / 'encrypted-key.pem'
                encrypt_pkcs8(private, encrypted_key)
                private = encrypted_key
            publish(self.tree, {label + '.key': read_file(private, private=True),
                                label + '.pub': read_file(public)})
        print('Created ' + algorithm + '. Consumer support is required; ML-KEM is not a signing key.')

    def select(self) -> str | None:
        return choose('PQC key', inventory(self.tree, '', '.pub'))

    def inspect(self) -> None:
        selected = self.select()
        if selected:
            with stage(self.tree) as work:
                path = work / 'public.pem'
                path.write_bytes(self.tree.read(selected + '.pub'))
                display(run(['/usr/bin/openssl', 'pkey', '-pubin', '-in', str(path), '-text_pub', '-noout'],
                            capture=True).decode())

    def export(self) -> None:
        selected = self.select()
        if selected:
            values = {selected + '.pub': self.tree.read(selected + '.pub')}
            if confirm('Export private key as well?'):
                values[selected + '.key'] = private_file(self.tree, selected + '.key')
            publish(self.exports, values)
            print('Private export directory: ' + str(self.exports.root))

    def delete(self) -> None:
        selected = self.select()
        if selected and prompt('Type the exact key name to delete') == selected:
            self.tree.write(selected + '.key', None)
            self.tree.write(selected + '.pub', None)

    def run(self) -> None:
        menu('Post-quantum keys', {'Generate native OpenSSL PQC key': self.generate,
                                 'Inventory / inspect public key': self.inspect,
                                 'Export key material': self.export,
                                 'Delete key files': self.delete})
