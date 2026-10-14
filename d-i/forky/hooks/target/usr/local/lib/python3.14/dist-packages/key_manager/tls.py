"""Purpose-specific X.509 material and isolated Certbot state under existing PKI."""
from __future__ import annotations

import base64
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import secrets
from urllib.parse import urlsplit

from .core import (Tree, choose, confirm, display, encrypt_pkcs8, inventory, menu, name, number,
                   password,
                   private_file, prompt, protected_directory, publish, read_file, run, stage)
from .tls_profiles import (ML_DSA, PLATFORM_PROFILES, PROFILES, RSA, RSA_EC, Profile, additional_extensions,
                           extensions, san_values, select as select_profile)

OPENSSL = '/usr/bin/openssl'


def common_name(value: str) -> str:
    if not re.fullmatch(r'[A-Za-z0-9*][A-Za-z0-9 ._@*-]{0,119}', value):
        raise ValueError('common name contains unsupported characters')
    return value


def certificate_name(value: str) -> str:
    value = name(value)
    if value.endswith('.fullchain'):
        raise ValueError('the .fullchain suffix is reserved for chain bundles')
    return value


def distinguished_name(label: str) -> str:
    value = 'CN=' + common_name(prompt(label)) + '\n'
    if confirm('Add organization and location fields to the subject?'):
        for field, description in (('O', 'Organization'), ('OU', 'Organizational unit'),
                                   ('C', 'Two-letter country code'), ('ST', 'State / region'), ('L', 'Locality')):
            supplied = prompt(description + ' (- skips)', '-')
            if supplied == '-':
                continue
            if (len(supplied) > 120 or any(c in supplied for c in '\\$#;\"\'[]')
                    or (field == 'C' and not re.fullmatch(r'[A-Z]{2}', supplied))):
                raise ValueError('subject field contains unsupported configuration characters or country code')
            value += field + '=' + supplied + '\n'
    return value


def key(stage_path: Path, kind: str, encrypted: bool) -> Path:
    if kind in ML_DSA:
        supported = run([OPENSSL, 'list', '-signature-algorithms'], capture=True).decode()
        if kind not in supported:
            raise ValueError('installed OpenSSL does not support ' + kind + '; a signed package is required')
        args = ['-algorithm', kind]
    else:
        args = {'ECDSA P-384': ['-algorithm', 'EC', '-pkeyopt', 'ec_paramgen_curve:P-384'],
                'ECDSA P-256': ['-algorithm', 'EC', '-pkeyopt', 'ec_paramgen_curve:P-256'],
                'ECDSA P-521': ['-algorithm', 'EC', '-pkeyopt', 'ec_paramgen_curve:P-521'],
                'RSA 4096': ['-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:4096'],
                'RSA 3072': ['-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:3072'],
                'Ed25519': ['-algorithm', 'ED25519'], 'Ed448': ['-algorithm', 'ED448']}[kind]
    output = stage_path / 'key.pem'
    run([OPENSSL, 'genpkey', *args, '-out', str(output)])
    if encrypted:
        encrypted_output = stage_path / 'encrypted-key.pem'
        encrypt_pkcs8(output, encrypted_output)
        return encrypted_output
    return output


def digest_args(kind: str, digest: str = 'sha256') -> list[str]:
    return [] if kind in ('Ed25519', 'Ed448', *ML_DSA) else ['-' + digest]


def certificate_blocks(value: bytes) -> list[bytes]:
    blocks = re.findall(rb'-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----', value, re.DOTALL)
    if not blocks or len(blocks) > 32:
        raise ValueError('certificate bundle requires 1–32 PEM certificates')
    return [block + b'\n' for block in blocks]


def public_key_type(info: str) -> str:
    for kind in ML_DSA:
        if kind in info:
            return kind
    for marker, kind in (('prime256v1', 'ECDSA P-256'), ('secp384r1', 'ECDSA P-384'),
                         ('secp521r1', 'ECDSA P-521'), ('ED25519', 'Ed25519'), ('ED448', 'Ed448')):
        if marker in info:
            return kind
    match = re.search(r'Public-Key: \((2048|3072|4096) bit\)', info)
    if match and 'Modulus:' in info:
        return 'RSA ' + match[1]
    raise ValueError('unsupported or weak certificate public key')


def certificate_key_type(path: Path) -> str:
    public = run([OPENSSL, 'x509', '-in', str(path), '-noout', '-pubkey'], capture=True)
    info = run([OPENSSL, 'pkey', '-pubin', '-text_pub', '-noout'], data=public, capture=True).decode()
    return public_key_type(info)


def compatible_key(kind: str, profile: Profile) -> bool:
    # Generation offers stronger RSA sizes; existing industry-standard RSA 2048 imports remain usable.
    return kind in profile.keys or (kind == 'RSA 2048' and any(v in RSA for v in profile.keys))


def valid_now(cert: Path) -> None:
    output = run([OPENSSL, 'x509', '-in', str(cert), '-noout', '-startdate', '-enddate',
                  '-dateopt', 'iso_8601'], capture=True).decode().splitlines()
    if len(output) != 2 or not output[0].startswith('notBefore=') or not output[1].startswith('notAfter='):
        raise ValueError('cannot read certificate validity dates')
    start, end = (datetime.fromisoformat(line.partition('=')[2]) for line in output)
    if start.tzinfo is None or end.tzinfo is None or not start <= datetime.now(UTC) < end:
        raise ValueError('certificate is not currently valid')


def ordered_chain(work: Path, cert: Path, chain: bytes) -> list[bytes]:
    def names(path: Path) -> tuple[str, str]:
        output = run([OPENSSL, 'x509', '-in', str(path), '-noout', '-subject', '-issuer',
                      '-nameopt', 'RFC2253'], capture=True).decode().splitlines()
        if len(output) != 2 or not output[0].startswith('subject=') or not output[1].startswith('issuer='):
            raise ValueError('cannot read certificate subject and issuer')
        return output[0].partition('=')[2].strip(), output[1].partition('=')[2].strip()

    blocks = certificate_blocks(chain)
    candidates = []
    for block in blocks:
        (work / 'candidate-ca.pem').write_bytes(block)
        subject, issuer = names(work / 'candidate-ca.pem')
        candidates.append((subject, issuer, block))
    _subject, wanted = names(cert)
    ordered = []
    while candidates:
        matches = [value for value in candidates if value[0] == wanted]
        if len(matches) != 1:
            raise ValueError('issuer chain is incomplete or ambiguous; supply one complete chain including its root')
        selected = matches[0]
        candidates.remove(selected)
        ordered.append(selected[2])
        if selected[0] == selected[1]:
            if candidates:
                raise ValueError('issuer bundle contains unrelated or duplicate certificates')
            return ordered
        wanted = selected[1]
    raise ValueError('issuer chain must include its self-signed root')


def verify_chain(work: Path, cert: Path, chain: bytes) -> bytes:
    blocks = ordered_chain(work, cert, chain)
    (work / 'anchor.pem').write_bytes(blocks[-1])
    (work / 'issuers.pem').write_bytes(b''.join(blocks))
    run([OPENSSL, 'verify', '-check_ss_sig', '-no-CApath', '-no-CAstore', '-CAfile', str(work / 'anchor.pem'),
         '-untrusted', str(work / 'issuers.pem'), str(cert)])
    return b''.join(blocks)


def matching_key(work: Path, cert: Path, private: Path) -> None:
    public = run([OPENSSL, 'x509', '-in', str(cert), '-pubkey', '-noout'], capture=True)
    cert_pub = run([OPENSSL, 'pkey', '-pubin', '-outform', 'DER'], data=public, capture=True)
    derived = work / 'derived.der'
    run([OPENSSL, 'pkey', '-in', str(private), '-check', '-noout'])
    run([OPENSSL, 'pkey', '-in', str(private), '-pubout', '-outform', 'DER', '-out', str(derived)])
    if hashlib.sha256(cert_pub).digest() != hashlib.sha256(read_file(derived)).digest():
        raise ValueError('certificate and private key do not match')


def matching_leaf(work: Path, blocks: list[bytes], private: Path) -> tuple[bytes, bytes]:
    derived = work / 'derived.der'
    run([OPENSSL, 'pkey', '-in', str(private), '-pubout', '-outform', 'DER', '-out', str(derived)])
    key_public = read_file(derived)
    matched = []
    for block in blocks:
        candidate = work / 'candidate.pem'
        candidate.write_bytes(block)
        public = run([OPENSSL, 'x509', '-in', str(candidate), '-pubkey', '-noout'], capture=True)
        cert_pub = run([OPENSSL, 'pkey', '-pubin', '-outform', 'DER'], data=public, capture=True)
        if cert_pub == key_public:
            matched.append(block)
    if len(matched) != 1:
        raise ValueError('input requires exactly one certificate matching the private key')
    return matched[0], b''.join(block for block in blocks if block != matched[0])


class TLS:
    def __init__(self, tree: Tree, exports: Tree, account_uid: int):
        self.tree, self.exports, self.account_uid = tree, exports, account_uid

    def select(self, folder: str = 'certs', suffix: str = '.pem') -> str | None:
        return choose('Select certificate', [item for item in inventory(self.tree, folder, suffix)
                                              if not item.endswith('.fullchain')])

    def inspect(self, folder: str = 'certs') -> None:
        selected = self.select(folder)
        if selected:
            with stage(self.tree) as work:
                path = work / 'cert.pem'
                path.write_bytes(self.tree.read(folder + '/' + selected + '.pem'))
                display(run([OPENSSL, 'x509', '-in', str(path), '-noout', '-text',
                             '-fingerprint', '-sha256'], capture=True).decode())

    def parameters(self, *, subject: bool = True, lifetime: bool = True) -> tuple[Profile, str, str, tuple[str, ...], int] | None:
        profile = select_profile()
        if profile is None:
            return None
        label = certificate_name(prompt('Certificate name'))
        subject_value = distinguished_name('Common name') if subject else ''
        identities = ()
        if profile.san_required or confirm('Add SAN identities?'):
            identities = san_values(prompt('SANs: DNS/IP or EMAIL:/URI:/UPN: values'))
        if 'serverAuth' in profile.eku and not any(v.startswith(('DNS:', 'IP:')) for v in identities):
            raise ValueError('server authentication requires a DNS or IP SAN')
        if 'emailProtection' in profile.eku and not any(v.startswith('EMAIL:') for v in identities):
            raise ValueError('S/MIME requires an EMAIL SAN')
        if '1.3.6.1.4.1.311.20.2.2' in profile.eku and not any(v.startswith('UPN:') for v in identities):
            raise ValueError('smartcard logon requires a UPN SAN')
        days = number(prompt('Lifetime in days', str(profile.days)), 1, 3650) if lifetime else profile.days
        return profile, label, subject_value, identities, days

    def generate_ca(self, *, intermediate: bool = False) -> None:
        label = certificate_name(prompt('CA name', 'local-ca'))
        subject = distinguished_name('CA common name')
        days = number(prompt('CA lifetime in days', '3650'), 1, 7300)
        category = choose('CA compatibility', ['General-purpose CA', 'Azure P2S VPN RSA CA',
                                               'Experimental ML-DSA CA'])
        if not category:
            return
        kinds = {'General-purpose CA': RSA_EC, 'Azure P2S VPN RSA CA': RSA,
                 'Experimental ML-DSA CA': ML_DSA}[category]
        kind = choose('CA key algorithm', list(kinds))
        if not kind:
            return
        issuer = self.select('ca') if intermediate else None
        if intermediate and not issuer:
            return
        pathlen = number(prompt('Maximum subordinate CA depth', '0' if intermediate else '1'), 0, 32)
        profile = Profile(category, keys=kinds, eku=(), san_required=False,
                          ca_keys=RSA if category == 'Azure P2S VPN RSA CA' else ())
        if confirm('Configure CA name constraints / AIA / CRL extension URLs?'):
            profile = additional_extensions(profile, ca=True)
        print('CA private keys require a passphrase. Keep an offline backup and protect it.')
        with stage(self.tree) as work:
            private = key(work, kind, True)
            config = work / 'openssl.cnf'
            ext = extensions(profile, (), kind, ca=True, pathlen=pathlen)
            config.write_text('[req]\nprompt=no\nutf8=yes\ndistinguished_name=dn\nx509_extensions=ext\nreq_extensions=ext\n'
                              '[dn]\n' + subject + '[ext]\n' +
                              ext, encoding='utf-8')
            cert = work / 'cert.pem'
            if intermediate:
                csr = work / 'request.pem'
                run([OPENSSL, 'req', '-new', *digest_args(kind, profile.digest), '-key', str(private),
                     '-config', str(config), '-out', str(csr)])
                self.sign(work, csr, cert, ext, days, issuer, None, kind, profile)
                chain = read_file(cert) + read_file(work / 'ca.pem')
            else:
                run([OPENSSL, 'req', '-new', '-x509', *digest_args(kind, profile.digest), '-key', str(private),
                     '-config', str(config), '-days', str(days), '-set_serial',
                     hex(secrets.randbits(159) or 1), '-out', str(cert)])
                run([OPENSSL, 'verify', '-check_ss_sig', '-CAfile', str(cert), str(cert)])
                chain = read_file(cert)
            publish(self.tree, {'ca/' + label + '.key': read_file(private, private=True),
                                'ca/' + label + '.pem': read_file(cert),
                                'ca/' + label + '.fullchain.pem': chain})
        print('CA created. Public trust anchor: ' + str(self.tree.root / 'ca' / (label + '.pem')))

    def issue(self, *, csr_only: bool = False, self_signed: bool = False) -> None:
        parameters = self.parameters(lifetime=not csr_only)
        if parameters is None:
            return
        profile, label, subject, identities, days = parameters
        if profile.external_ca and not csr_only:
            raise ValueError('this target requires an externally trusted CA; create a CSR and import its issued chain')
        kind = choose('Key algorithm for ' + profile.label, list(profile.keys))
        if not kind:
            return
        issuer = None
        if not csr_only and not self_signed:
            issuer = self.select('ca')
            if issuer is None:
                return
        encrypted = confirm('Encrypt private key (unattended services need an unlock mechanism)?')
        with stage(self.tree) as work:
            private = key(work, kind, encrypted)
            csr = work / 'request.pem'
            config = work / 'openssl.cnf'
            ext = extensions(profile, identities, kind)
            config.write_text('[req]\nprompt=no\nutf8=yes\ndistinguished_name=dn\nreq_extensions=ext\n'
                              '[dn]\n' + subject + '[ext]\n' + ext, encoding='utf-8')
            run([OPENSSL, 'req', '-new', *digest_args(kind, profile.digest), '-key', str(private),
                 '-config', str(config), '-out', str(csr)])
            run([OPENSSL, 'req', '-in', str(csr), '-noout', '-verify'])
            values = {'private/' + label + '.key': read_file(private, private=True),
                      'csr/' + label + '.csr': read_file(csr)}
            if not csr_only:
                cert = work / 'cert.pem'
                self.sign(work, csr, cert, ext, days, issuer, private if self_signed else None,
                          kind, profile)
                values.update(self.certificate_values(work, label, issuer))
            publish(self.tree, values)
        print('Material created under ' + str(self.tree.root))

    def sign(self, work: Path, csr: Path, cert: Path, ext: str, days: int,
             issuer: str | None, private: Path | None, kind: str = '',
             profile: Profile = PROFILES[0]) -> None:
        config = work / 'extensions.cnf'
        config.write_text('[ext]\nauthorityKeyIdentifier=keyid,issuer\n' + ext, encoding='utf-8')
        args = [OPENSSL, 'x509', '-req', '-in', str(csr), '-out', str(cert),
                '-days', str(days), '-set_serial', hex(secrets.randbits(159) or 1),
                '-extfile', str(config), '-extensions', 'ext', '-copy_extensions', 'none']
        if issuer:
            ca = work / 'ca.pem'
            ca_key = work / 'ca.key'
            ca.write_bytes(self.tree.read('ca/' + name(issuer) + '.pem'))
            ca_key.write_bytes(private_file(self.tree, 'ca/' + issuer + '.key'))
            ca_kind = certificate_key_type(ca)
            if profile.ca_keys and not ca_kind.startswith('RSA '):
                raise ValueError('this certificate profile requires an RSA CA')
            run([OPENSSL, 'x509', '-in', str(ca), '-noout', '-checkend', str(days * 86400)])
            args += ['-CA', str(ca), '-CAkey', str(ca_key), *digest_args(ca_kind, profile.digest)]
        elif private is not None:
            args += ['-signkey', str(private), *digest_args(kind, profile.digest)]
        else:
            raise ValueError('a CA or self-signing key is required')
        run(args)
        if issuer:
            chain = self.tree.read('ca/' + issuer + '.fullchain.pem', missing=True) or read_file(work / 'ca.pem')
            for block in certificate_blocks(chain):
                check_ca = work / 'check-ca.pem'
                check_ca.write_bytes(block)
                run([OPENSSL, 'x509', '-in', str(check_ca), '-noout', '-checkend', str(days * 86400)])
                if profile.ca_keys and not certificate_key_type(check_ca).startswith('RSA '):
                    raise ValueError('this profile requires RSA throughout the issuing CA chain')
            chain = verify_chain(work, cert, chain)
            (work / 'ca.pem').write_bytes(chain)
        else:
            run([OPENSSL, 'verify', '-check_ss_sig', '-CAfile', str(cert), str(cert)])

    def certificate_values(self, work: Path, label: str, issuer: str | None) -> dict[str, bytes]:
        cert = read_file(work / 'cert.pem')
        chain = cert + (read_file(work / 'ca.pem') if issuer else b'')
        values = {'certs/' + label + '.pem': cert, 'certs/' + label + '.fullchain.pem': chain}
        der = work / 'cert.der'
        run([OPENSSL, 'x509', '-in', str(work / 'cert.pem'), '-outform', 'DER', '-out', str(der)])
        values['certs/' + label + '.der'] = read_file(der)
        values['certs/' + label + '.crt'] = cert
        values['certs/' + label + '.cer'] = read_file(der)
        return values

    def sign_csr(self) -> None:
        parameters = self.parameters(subject=False)
        if parameters is None:
            return
        profile, label, _subject, identities, days = parameters
        if profile.external_ca:
            raise ValueError('this profile needs a CA-issued public certificate; use external CSR/import flow')
        supplied = read_file(Path(prompt('CSR absolute path')))
        issuer = self.select('ca')
        if issuer is None:
            return
        with stage(self.tree) as work:
            csr = work / 'request.pem'
            csr.write_bytes(supplied)
            display(run([OPENSSL, 'req', '-in', str(csr), '-noout', '-verify', '-text'],
                        capture=True).decode())
            if not confirm('Sign this CSR with the selected purpose and SANs?'):
                return
            public = run([OPENSSL, 'req', '-in', str(csr), '-pubkey', '-noout'], capture=True)
            # CSR public-key type is inspected directly; no temporary signing key is created.
            info = run([OPENSSL, 'pkey', '-pubin', '-text_pub', '-noout'], data=public, capture=True).decode()
            kind = public_key_type(info)
            if not compatible_key(kind, profile):
                raise ValueError('CSR key type is incompatible with the chosen profile')
            self.sign(work, csr, work / 'cert.pem', extensions(profile, identities, kind), days,
                      issuer, None, kind, profile)
            values = self.certificate_values(work, label, issuer)
            values['csr/' + label + '.csr'] = supplied
            publish(self.tree, values)

    def import_pair(self, *, issued: bool = False, ca: bool = False) -> None:
        label = certificate_name(prompt('CA name' if ca else 'Certificate name'))
        encoding = choose('Certificate input format', ['PEM', 'DER', 'PKCS7 PEM', 'PKCS7 DER'])
        if not encoding:
            return
        cert_data = read_file(Path(prompt('Certificate absolute path')))
        if issued:
            if self.tree.read('csr/' + label + '.csr', missing=True) is None:
                raise ValueError('no managed CSR exists under that name')
            key_data = private_file(self.tree, 'private/' + label + '.key')
        else:
            input_key = Path(prompt('Root or desktop-owned mode-0600 key PEM absolute path'))
            key_data = read_file(input_key, private=True, owners=(0, self.account_uid))
        with stage(self.tree) as work:
            cert, private = work / 'cert.pem', work / 'key.pem'
            supplied = work / 'input-cert'
            supplied.write_bytes(cert_data)
            private.write_bytes(key_data)
            embedded_chain = b''
            if encoding.startswith('PKCS7'):
                parsed = run([OPENSSL, 'pkcs7', '-in', str(supplied), '-inform', encoding.split()[1],
                              '-print_certs'], capture=True)
                leaf, embedded_chain = matching_leaf(work, certificate_blocks(parsed), private)
                cert.write_bytes(leaf)
            elif encoding == 'PEM':
                leaf, embedded_chain = matching_leaf(work, certificate_blocks(cert_data), private)
                cert.write_bytes(leaf)
            else:
                run([OPENSSL, 'x509', '-in', str(supplied), '-inform', encoding, '-out', str(cert)])
            matching_key(work, cert, private)
            valid_now(cert)
            display(run([OPENSSL, 'x509', '-in', str(cert), '-noout', '-checkend', '0', '-text'],
                        capture=True).decode())
            if ca:
                policy = run([OPENSSL, 'x509', '-in', str(cert), '-noout', '-ext',
                              'basicConstraints,keyUsage'], capture=True).decode()
                if 'CA:TRUE' not in policy or 'Certificate Sign' not in policy:
                    raise ValueError('CA import requires CA:TRUE and keyCertSign extensions')
                # All managed CA keys, including backups, use an encrypted PKCS8 envelope.
                protected = work / 'protected-ca.key'
                encrypt_pkcs8(private, protected)
                key_data = read_file(protected, private=True)
            has_chain = False
            if embedded_chain or confirm('Import and validate an issuer chain too?'):
                chain_data = embedded_chain or read_file(Path(prompt('Issuer chain PEM absolute path')))
                anchor_data = read_file(Path(prompt('Trusted CA bundle absolute path',
                                                   '/etc/ssl/certs/ca-certificates.crt')))
                chain, anchor = work / 'chain.pem', work / 'anchor.pem'
                chain_data = b''.join(ordered_chain(work, cert, chain_data))
                chain.write_bytes(chain_data)
                anchor.write_bytes(anchor_data)
                run([OPENSSL, 'verify', '-no-CApath', '-no-CAstore', '-CAfile', str(anchor),
                     '-untrusted', str(chain), str(cert)])
                (work / 'ca.pem').write_bytes(chain_data)
                has_chain = True
            values = self.certificate_values(work, label, 'imported' if has_chain else None)
            if ca:
                if not has_chain:
                    run([OPENSSL, 'verify', '-check_ss_sig', '-no-CApath', '-no-CAstore',
                         '-CAfile', str(cert), str(cert)])
                values = {'ca/' + label + '.pem': read_file(cert),
                          'ca/' + label + '.key': key_data,
                          'ca/' + label + '.fullchain.pem': read_file(cert) +
                          (read_file(work / 'ca.pem') if has_chain else b'')}
            elif not issued:
                values['private/' + label + '.key'] = key_data
            if confirm('Import this matching certificate and key?'):
                publish(self.tree, values)

    def import_pkcs12(self) -> None:
        label = certificate_name(prompt('Certificate name'))
        supplied = read_file(Path(prompt('Root or desktop-owned mode-0600 PFX/P12 absolute path')),
                             private=True, owners=(0, self.account_uid))
        with stage(self.tree) as work:
            bundle, cert, private = work / 'bundle.p12', work / 'cert.pem', work / 'key.pem'
            bundle.write_bytes(supplied)
            # Verify the MAC and let native OpenSSL prompt for both import and new key passwords.
            parsed = work / 'parsed.pem'
            run([OPENSSL, 'pkcs12', '-in', str(bundle), '-out', str(parsed), '-aes256'])
            parsed_data = read_file(parsed, private=True)
            if len(re.findall(rb'-----BEGIN (?:ENCRYPTED |RSA |EC )?PRIVATE KEY-----', parsed_data)) != 1:
                raise ValueError('import requires exactly one private key')
            blocks = certificate_blocks(parsed_data)
            encrypt_pkcs8(parsed, private)
            leaf, issuers = matching_leaf(work, blocks, private)
            cert.write_bytes(leaf)
            if issuers:
                # Verify a complete chain and canonicalize issuer ordering.
                issuers = verify_chain(work, cert, issuers)
                (work / 'ca.pem').write_bytes(issuers)
            matching_key(work, cert, private)
            valid_now(cert)
            display(run([OPENSSL, 'x509', '-in', str(cert), '-noout', '-checkend', '0',
                         '-fingerprint', '-sha256', '-subject', '-issuer'], capture=True).decode())
            values = self.certificate_values(work, label, 'imported' if issuers else None)
            values['private/' + label + '.key'] = read_file(private, private=True)
            if confirm('Import this matching identity (verify the displayed CA identity separately)?'):
                publish(self.tree, values)

    def export(self) -> None:
        label = self.select()
        if not label:
            return
        include_private = confirm('Include the private key in the private export bundle?')
        values = {}
        for source in ('certs/' + label + '.pem', 'certs/' + label + '.fullchain.pem',
                       'certs/' + label + '.der', 'certs/' + label + '.crt',
                       'certs/' + label + '.cer', 'csr/' + label + '.csr'):
            data = self.tree.read(source, missing=True)
            if data is not None:
                values[label + '/' + Path(source).name] = data
        if include_private:
            values[label + '/' + label + '.key'] = private_file(self.tree, 'private/' + label + '.key')
        publish(self.exports, values)
        print('Private export directory: ' + str(self.exports.root / label))

    def export_ca(self) -> None:
        label = self.select('ca')
        if label:
            values = {'ca/' + label + '.pem': self.tree.read('ca/' + label + '.pem')}
            chain = self.tree.read('ca/' + label + '.fullchain.pem', missing=True)
            if chain:
                values['ca/' + label + '.fullchain.pem'] = chain
            with stage(self.tree) as work:
                cert, der = work / 'ca.pem', work / 'ca.der'
                cert.write_bytes(values['ca/' + label + '.pem'])
                run([OPENSSL, 'x509', '-in', str(cert), '-outform', 'DER', '-out', str(der)])
                values['ca/' + label + '.der'] = read_file(der)
                values['ca/' + label + '.cer'] = read_file(der)
                values['ca/' + label + '.base64.txt'] = base64.b64encode(read_file(der)) + b'\n'
            if confirm('Include the encrypted CA signing key in this private backup?'):
                values['ca/' + label + '.key'] = private_file(self.tree, 'ca/' + label + '.key')
            publish(self.exports, values)
            print('CA backup: ' + str(self.exports.root / 'ca'))

    def pkcs12(self) -> None:
        label = self.select()
        if not label:
            return
        with stage(self.tree) as work:
            cert, private, chain = self.export_material(work, label)
            output = self.pkcs12_file(work, label, cert, private, chain)
            publish(self.exports, {label + '.p12': read_file(output, private=True)})

    def export_material(self, work: Path, label: str, *, with_key: bool = True) -> tuple[Path, Path, list[bytes]]:
        cert, private = work / 'cert.pem', work / 'key.pem'
        cert.write_bytes(self.tree.read('certs/' + label + '.pem'))
        if with_key:
            private.write_bytes(private_file(self.tree, 'private/' + label + '.key'))
            matching_key(work, cert, private)
        valid_now(cert)
        data = self.tree.read('certs/' + label + '.fullchain.pem', missing=True) or read_file(cert)
        blocks = certificate_blocks(data)
        if blocks[0] != certificate_blocks(read_file(cert))[0]:
            raise ValueError('stored full chain does not begin with this certificate')
        if len(blocks) > 1:
            blocks = [blocks[0], *certificate_blocks(verify_chain(work, cert, b''.join(blocks[1:])))]
        return cert, private, blocks

    def pkcs12_file(self, work: Path, label: str, cert: Path, private: Path,
                    chain: list[bytes], *, azure: bool = False) -> Path:
        output = work / 'bundle.p12'
        cipher, digest = ('PBE-SHA1-3DES', 'SHA1') if azure else ('AES-256-CBC', 'SHA256')
        args = [OPENSSL, 'pkcs12', '-export', '-in', str(cert), '-inkey', str(private),
                '-name', label, '-out', str(output), '-keypbe', cipher, '-certpbe', cipher,
                '-macalg', digest, '-iter', '200000', '-passout', 'stdin']
        if len(chain) > 1:
            ca = work / 'bundle-chain.pem'
            ca.write_bytes(b''.join(chain[1:]))
            args += ['-certfile', str(ca)]
        run(args, data=password())
        return output

    def pkcs7(self) -> None:
        label = self.select()
        if not label:
            return
        encoding = choose('PKCS7 public chain format', ['PEM', 'DER'])
        if not encoding:
            return
        with stage(self.tree) as work:
            chain, output = work / 'chain.pem', work / 'chain.p7b'
            chain.write_bytes(self.tree.read('certs/' + label + '.fullchain.pem', missing=True)
                              or self.tree.read('certs/' + label + '.pem'))
            run([OPENSSL, 'crl2pkcs7', '-nocrl', '-certfile', str(chain), '-outform', encoding,
                 '-out', str(output)])
            publish(self.exports, {label + '.' + encoding.lower() + '.p7b': read_file(output)})

    def export_private(self) -> None:
        label = self.select()
        if not label:
            return
        choice = choose('Private-key export', ['Encrypted PKCS8 PEM (AES-256)',
                                             'Unencrypted PKCS8 PEM', 'Unencrypted PKCS8 DER',
                                             'Traditional RSA / EC PEM'])
        if not choice:
            return
        if choice != 'Encrypted PKCS8 PEM (AES-256)' and not confirm('Export an unencrypted private key?'):
            return
        with stage(self.tree) as work:
            private, output = work / 'key.pem', work / 'export.key'
            private.write_bytes(private_file(self.tree, 'private/' + label + '.key'))
            if choice == 'Unencrypted PKCS8 DER':
                args = [OPENSSL, 'pkcs8', '-topk8', '-nocrypt', '-in', str(private),
                        '-outform', 'DER', '-out', str(output)]
                suffix = '.pkcs8.der'
            else:
                args = [OPENSSL, 'pkey', '-in', str(private), '-out', str(output)]
                suffix = '.pkcs8.pem'
                if choice == 'Traditional RSA / EC PEM':
                    cert = work / 'cert.pem'
                    cert.write_bytes(self.tree.read('certs/' + label + '.pem'))
                    kind = certificate_key_type(cert)
                    if not kind.startswith('RSA ') and kind not in RSA_EC:
                        raise ValueError('traditional format requires RSA or EC')
                    args += ['-traditional']
                    suffix = '.traditional.pem'
            encrypted = choice == 'Encrypted PKCS8 PEM (AES-256)'
            if encrypted:
                encrypt_pkcs8(private, output)
                suffix = '.encrypted.pkcs8.pem'
            else:
                run(args)
            publish(self.exports, {label + suffix: read_file(output, private=True)})

    def export_platform(self) -> None:
        targets = PLATFORM_PROFILES
        chosen = choose('Target platform export', [p.label for p in targets])
        if not chosen:
            return
        profile = next(p for p in targets if p.label == chosen)
        label = self.select()
        if not label:
            return
        with stage(self.tree) as work:
            cert, private, chain = self.export_material(work, label,
                                                       with_key=profile.label != 'Microsoft Entra application certificate')
            kind = certificate_key_type(cert)
            if not compatible_key(kind, profile):
                raise ValueError('certificate key type is incompatible with this target profile')
            if profile.ca_keys and len(chain) < 2:
                raise ValueError('target requires a complete issuer chain including its root')
            eku = run([OPENSSL, 'x509', '-in', str(cert), '-noout', '-ext', 'extendedKeyUsage'],
                      capture=True).decode()
            for purpose, marker in (('serverAuth', 'TLS Web Server Authentication'),
                                    ('clientAuth', 'TLS Web Client Authentication')):
                if purpose in profile.eku and marker not in eku:
                    raise ValueError('certificate lacks the target-required ' + purpose + ' EKU')
            if profile.full_chain:
                last = work / 'root.pem'
                last.write_bytes(chain[-1])
                subject = run([OPENSSL, 'x509', '-in', str(last), '-noout', '-subject',
                               '-nameopt', 'RFC2253'], capture=True).decode().partition('=')[2].strip()
                issuer = run([OPENSSL, 'x509', '-in', str(last), '-noout', '-issuer',
                              '-nameopt', 'RFC2253'], capture=True).decode().partition('=')[2].strip()
                if subject != issuer:
                    raise ValueError('target requires the self-signed root at the end of the chain')
                run([OPENSSL, 'verify', '-check_ss_sig', '-no-CApath', '-no-CAstore',
                     '-CAfile', str(last), str(last)])
            if profile.external_ca:
                # Check installed trust; the target service separately decides which public CAs it accepts.
                (work / 'public-chain.pem').write_bytes(b''.join(chain[1:]))
                run([OPENSSL, 'verify', '-CAfile', '/etc/ssl/certs/ca-certificates.crt',
                     '-no-CApath', '-no-CAstore', '-purpose', 'sslserver',
                     '-untrusted', str(work / 'public-chain.pem'), str(cert)])
            if profile.ca_keys:
                for block in chain[1:]:
                    (work / 'check-ca.pem').write_bytes(block)
                    if not certificate_key_type(work / 'check-ca.pem').startswith('RSA '):
                        raise ValueError('Azure P2S requires an RSA CA chain')
            destination = label + '/' + name(profile.label.replace(' / ', '-').replace(' ', '-'))
            if profile.label == 'Microsoft Entra application certificate':
                output = work / 'public.cer'
                run([OPENSSL, 'x509', '-in', str(cert), '-outform', 'DER', '-out', str(output)])
                values = {destination + '.cer': read_file(output), destination + '.pem': read_file(cert)}
            elif profile.label == 'Azure Key Vault certificate import' or profile.container == 'pem-split':
                if not confirm('Export an unencrypted private key required by this target?'):
                    return
                output = work / 'pkcs8.pem'
                run([OPENSSL, 'pkey', '-in', str(private), '-out', str(output)])
                exported_key = read_file(output, private=True)
                if profile.label == 'Azure Key Vault certificate import':
                    values = {destination + '.pem': read_file(cert) + exported_key}
                else:
                    if profile.label.startswith('AWS') and len(exported_key) > 5120:
                        raise ValueError('AWS ACM private-key import is limited to 5120 bytes')
                    values = {destination + '.pem': read_file(cert), destination + '.key': exported_key,
                              destination + '.chain.pem': b''.join(chain[1:])}
            else:
                azure = profile.container == 'azure-app-service'
                if azure and not confirm('Use the documented App Service 3DES/SHA1 PFX envelope?'):
                    return
                output = self.pkcs12_file(work, label, cert, private, chain, azure=azure)
                values = {destination + '.pfx': read_file(output, private=True)}
            publish(self.exports, values)
            print('Prepared private platform export under ' + str(self.exports.root / label))

    def trust_instructions(self) -> None:
        label = self.select('ca')
        if label:
            print('First verify the CA SHA256 fingerprint through a trusted channel.')
            print('On each intended Debian client, an administrator installs this public CA as')
            print('/usr/local/share/ca-certificates/' + label + '.crt and runs update-ca-certificates.')
            print('Applications with independent trust stores require their own trust import.')
            print('The private CA signing key is never a client trust anchor.')

    def retire_ca(self) -> None:
        label = self.select('ca')
        if label and prompt('Type the exact CA name to remove its local signing material') == label:
            self.tree.write('ca/' + label + '.key', None)
            self.tree.write('ca/' + label + '.pem', None)
            self.tree.write('ca/' + label + '.fullchain.pem', None)
            print('Local CA material removed. Issued certificates and remote trust are not revoked.')

    def delete(self) -> None:
        label = self.select()
        if label and prompt('Type the exact certificate name to delete') == label:
            for path in ('certs/' + label + '.pem', 'certs/' + label + '.fullchain.pem',
                         'certs/' + label + '.der', 'certs/' + label + '.crt', 'certs/' + label + '.cer',
                         'private/' + label + '.key', 'csr/' + label + '.csr'):
                self.tree.write(path, None)
            print('Local files removed. Copies and issued trust remain valid until expiry or revocation.')

    def acme_args(self) -> list[str]:
        for folder in ('acme/config', 'acme/work', 'acme/logs'):
            self.tree.mkdir(folder)
        return ['/usr/bin/certbot', '--config', '/etc/key-manager/certbot.ini',
                '--config-dir', str(self.tree.root / 'acme/config'),
                '--work-dir', str(self.tree.root / 'acme/work'),
                '--logs-dir', str(self.tree.root / 'acme/logs')]

    def acme_authority(self) -> list[str] | None:
        authority = choose('ACME certificate authority', ["Let's Encrypt staging", "Let's Encrypt production",
                                                          'Internal / custom HTTPS ACME directory'])
        if not authority:
            return None
        if authority == "Let's Encrypt staging":
            return ['--staging']
        if authority == "Let's Encrypt production":
            return []
        endpoint = prompt('HTTPS ACME directory URL')
        parsed = urlsplit(endpoint)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.fragment or not parsed.path
                or parsed.query or any(c in endpoint for c in '\\ \t')):
            raise ValueError('use an HTTPS ACME directory URL without credentials or query data')
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError('invalid ACME directory port')
        print('The internal ACME server certificate must validate against the system CA trust store.')
        return ['--server', endpoint]

    def acme_request(self) -> None:
        identities = san_values(prompt('ACME DNS names or IP addresses (space separated)'))
        if any(not v.startswith(('DNS:', 'IP:')) for v in identities):
            raise ValueError('ACME accepts DNS and IP identifiers only')
        domains = [v[4:] for v in identities if v.startswith('DNS:')]
        addresses = [v[3:] for v in identities if v.startswith('IP:')]
        certificate_label = name(prompt('ACME certificate name', domains[0].removeprefix('*.') if domains else 'ip-tls'))
        email = prompt('ACME account email')
        if not re.fullmatch(r'[A-Za-z0-9._+%-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}', email):
            raise ValueError('invalid email address')
        provider = choose('ACME challenge', ['Manual DNS-01', 'Cloudflare DNS-01',
                                           'RFC2136 DNS-01', 'HTTP-01 webroot',
                                           'HTTP-01 standalone (port 80 must be free)'])
        if not provider:
            return
        if addresses and provider in ('Manual DNS-01', 'Cloudflare DNS-01', 'RFC2136 DNS-01'):
            raise ValueError('ACME IP certificates require HTTP-01; choose webroot or standalone')
        authority = self.acme_authority()
        if authority is None:
            return
        kind = choose('ACME key (RSA for RSA-only targets; CloudFront EC uses P-256)',
                      ['ECDSA P-384', 'ECDSA P-256', 'RSA 4096', 'RSA 3072'])
        if not kind:
            return
        args = self.acme_args() + ['certonly', '--email', email, '--cert-name', certificate_label, *authority]
        default_profile = 'shortlived' if addresses and '--server' not in authority else '-'
        issuance_profile = prompt('ACME certificate profile (- uses CA default)', default_profile)
        if addresses and '--server' not in authority and issuance_profile != 'shortlived':
            raise ValueError("Let's Encrypt IP certificates require the shortlived profile")
        if issuance_profile != '-':
            args += ['--required-profile', name(issuance_profile)]
        if kind.startswith('RSA'):
            args += ['--key-type', 'rsa', '--rsa-key-size', kind.split()[1]]
        else:
            args += ['--key-type', 'ecdsa', '--elliptic-curve',
                     'secp384r1' if kind == 'ECDSA P-384' else 'secp256r1']
        for domain in domains:
            args += ['-d', domain]
        for address in addresses:
            args += ['--ip-address', address]
        if provider == 'Manual DNS-01':
            print('Manual DNS requires an interactive challenge on each renewal.')
            args += ['--manual', '--preferred-challenges', 'dns']
        elif provider in ('Cloudflare DNS-01', 'RFC2136 DNS-01'):
            credential = Path(prompt('Root or desktop-owned mode-0600 DNS credentials absolute path'))
            credential_data = read_file(credential, private=True, limit=65536, owners=(0, self.account_uid))
            plugin = 'dns-cloudflare' if provider == 'Cloudflare DNS-01' else 'dns-rfc2136'
            credential_name = name(prompt('Credential profile name', plugin))
            managed_credential = 'acme/credentials/' + credential_name + '.ini'
            existing = self.tree.read(managed_credential, missing=True)
            if existing is not None and existing != credential_data:
                raise ValueError('credential profile already exists with different content; choose a new name')
            if existing is None:
                publish(self.tree, {managed_credential: credential_data})
            args += ['--' + plugin, '--' + plugin + '-credentials', str(self.tree.root / managed_credential),
                     '--' + plugin + '-propagation-seconds',
                     str(number(prompt('DNS propagation wait in seconds', '120'), 10, 3600))]
        elif provider == 'HTTP-01 webroot':
            if any(domain.startswith('*.') for domain in domains):
                raise ValueError('wildcard certificates require DNS-01')
            webroot = Path(prompt('Existing HTTP webroot absolute path'))
            protected_directory(webroot)
            if webroot != Path('/var/www') and Path('/var/www') not in webroot.parents \
                    and webroot != Path('/srv') and Path('/srv') not in webroot.parents:
                raise ValueError('automated HTTP renewal needs a root-owned webroot below /var/www or /srv')
            args += ['--webroot', '--webroot-path', str(webroot)]
        else:
            if any(domain.startswith('*.') for domain in domains):
                raise ValueError('wildcard certificates require DNS-01')
            print('Standalone validation requires public access to port 80; no web service is stopped automatically.')
            args += ['--standalone']
        eab = None
        if '--server' in authority and confirm('Register with External Account Binding credentials?'):
            eab = json.loads(read_file(Path(prompt('Mode-0600 EAB JSON absolute path (kid and hmac_key)')),
                                       private=True, limit=4096, owners=(0, self.account_uid)))
            if (not isinstance(eab, dict) or set(eab) != {'kid', 'hmac_key'}
                    or not isinstance(eab['kid'], str) or not isinstance(eab['hmac_key'], str)
                    or not re.fullmatch(r'[A-Za-z0-9._~:/+-]{1,512}', eab['kid'])
                    or not re.fullmatch(r'[A-Za-z0-9_-]{16,1024}={0,2}', eab['hmac_key'])):
                raise ValueError('invalid External Account Binding credentials')
        if confirm('Contact the selected ACME CA and request these certificates?'):
            with stage(self.tree) as work:
                if eab is not None:
                    config = work / 'certbot.ini'
                    with Tree(Path('/etc/key-manager'), uid=0) as policy:
                        base = policy.read('certbot.ini', limit=65536)
                    config.write_bytes(base + b'\n' + ('eab-kid = ' + eab['kid'] + '\n' +
                                       'eab-hmac-key = ' + eab['hmac_key'] + '\n').encode())
                    args[args.index('--config') + 1] = str(config)
                run(args, timeout=1800)
            print('Certbot live paths: ' + str(self.tree.root / 'acme/config/live'))

    def acme_renew(self, dry_run: bool) -> None:
        args = self.acme_args() + ['renew', '--non-interactive']
        if dry_run:
            args += ['--dry-run']
        if confirm('Contact ACME and run ' + ('renewal rehearsal?' if dry_run else 'renewal?')):
            run(args, timeout=1800)

    def acme_remove(self, *, revoke: bool = False) -> None:
        label = choose('Managed ACME certificate', inventory(self.tree, 'acme/config/renewal', '.conf'))
        if not label:
            return
        args = self.acme_args() + ['revoke' if revoke else 'delete', '--cert-name', label]
        if revoke:
            authority = self.acme_authority()
            if authority is None:
                return
            reason = choose('Revocation reason', ['unspecified', 'keycompromise', 'affiliationchanged',
                                                   'superseded', 'cessationofoperation'])
            if not reason:
                return
            args += [*authority, '--reason', reason]
        print('Certificate consumers must be updated before removal. Deletion alone does not revoke a certificate.')
        if prompt('Type exact certificate name to ' + ('revoke' if revoke else 'delete')) == label:
            run(args, timeout=1800)

    def run(self) -> None:
        print('TLS storage: ' + str(self.tree.root))
        authorities = {
            'Local root CA: generate': self.generate_ca,
            'Intermediate CA: issue from local CA': lambda: self.generate_ca(intermediate=True),
            'Import / restore CA certificate and signing key': lambda: self.import_pair(ca=True),
            'Local CA: inspect / trust fingerprint': lambda: self.inspect('ca'),
            'Back up local CA certificate / encrypted key': self.export_ca,
            'Client trust installation instructions': self.trust_instructions,
            'Retire local CA signing material': self.retire_ca,
        }
        issuance = {
            'Issue certificate using local CA': self.issue,
            'Create private key and CSR for an external CA': lambda: self.issue(csr_only=True),
            'Sign an existing CSR with local CA': self.sign_csr,
            'Create self-signed certificate / kernel signing identity': lambda: self.issue(self_signed=True),
        }
        inventory_actions = {
            'Inventory / inspect certificate': self.inspect,
            'Import matching certificate and key': self.import_pair,
            'Import issued certificate for a managed CSR / existing key': lambda: self.import_pair(issued=True),
            'Import password-protected PKCS12 / PFX identity': self.import_pkcs12,
            'Export PEM / full chain / DER / CRT / CER / private key': self.export,
            'Export password-protected PKCS12 bundle': self.pkcs12,
            'Export PKCS7 / P7B public chain': self.pkcs7,
            'Export PKCS8 / traditional private-key formats': self.export_private,
            'Export for Azure / Entra / AWS / Google Cloud': self.export_platform,
            'Delete local certificate files': self.delete,
        }
        acme = {
            "ACME / Let's Encrypt: request": self.acme_request,
            'ACME: list certificates and paths': lambda: run(self.acme_args() + ['certificates']),
            'ACME: renew': lambda: self.acme_renew(False),
            'ACME: dry-run renewal': lambda: self.acme_renew(True),
            'ACME: revoke at the issuing authority': lambda: self.acme_remove(revoke=True),
            'ACME: delete local renewal state': self.acme_remove,
        }
        menu('TLS and X.509 certificates', {
            'Local certificate authorities / trust / backups': lambda: menu('Certificate authorities', authorities),
            'Certificate issuance / CSR / kernel signing identities': lambda: menu('Certificate issuance', issuance),
            'Certificate inventory / import / exports': lambda: menu('Certificate lifecycle', inventory_actions),
            "ACME / Let's Encrypt / renewal": lambda: menu('ACME', acme),
        })
