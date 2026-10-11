#!/usr/bin/python3 -IB
"""Validate installer DNS trust and publish Stubby's configuration in the target.

Public certificates authenticate a preconfigured identity; SAN discovery never
selects an arbitrary identity supplied by a remote endpoint. No DNS queries or
service starts are performed. Custom trust remains local to Stubby.
"""
from __future__ import annotations

import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import ssl
import stat
import sys
import tempfile
import time

PUBLIC_CA = '/etc/ssl/certs/ca-certificates.crt'
CUSTOM_CA = '/etc/stubby/ca/upstream-custom.pem'
OUTPUT = Path('/etc/stubby/stubby.yml')


def read_owned(path: Path, limit: int) -> bytes:
    for parent in reversed(path.parents):
        info = parent.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0
                or (info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX)):
            raise ValueError('untrusted DNS configuration input directory')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1 or info.st_mode & 0o022:
            raise ValueError('DNS configuration input must be a root-owned regular file without shared writes')
        value = stream.read(limit + 1)
    if len(value) > limit:
        raise ValueError('DNS configuration input exceeds its size limit')
    return value


def hostname(value: str) -> bool:
    return (isinstance(value, str) and 1 <= len(value) <= 253
            and all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label)
                    for label in value.split('.')))


def parse_policy(raw: bytes) -> tuple[dict[str, str], list[dict]]:
    values: dict[str, str] = {}
    for line in raw.decode('ascii').splitlines():
        key, separator, value = line.partition('=')
        if not separator or not re.fullmatch(r'[A-Z][A-Z0-9_]*', key) or key in values:
            raise ValueError('invalid DNS placeholder map')
        values[key] = value
    custom = values['SYSTEM_DNS_UPSTREAM_TLS_CA_CUSTOM_ENABLE']
    if custom not in ('true', 'false'):
        raise ValueError('invalid custom CA mode')
    if values['SYSTEM_DNS_UPSTREAM_TLS_CA_FILE'] != (CUSTOM_CA if custom == 'true' else PUBLIC_CA):
        raise ValueError('unexpected Stubby CA destination')
    upstreams = json.loads(values['SYSTEM_NAMESERVERS_UPSTREAMS_JSON'])
    if not isinstance(upstreams, list) or not 1 <= len(upstreams) <= 6:
        raise ValueError('invalid DNS upstream count')
    order = []
    names = {}
    endpoints = set()
    families = set()
    for upstream in upstreams:
        if not isinstance(upstream, dict) or set(upstream) != {'dns_index', 'address_data', 'tls_port', 'tls_auth_name'}:
            raise ValueError('invalid DNS upstream record')
        index, port, name = upstream['dns_index'], upstream['tls_port'], upstream['tls_auth_name']
        if not isinstance(upstream['address_data'], str) or len(upstream['address_data']) > 45:
            raise ValueError('DNS upstream address must be a numeric IP string')
        address = ipaddress.ip_address(upstream['address_data'])
        if (type(index) is not int or not 1 <= index <= 3 or type(port) is not int or not 1 <= port <= 65535
                or not hostname(name) or address.is_unspecified or address.is_multicast):
            raise ValueError('invalid DNS endpoint or TLS identity')
        if index in names and names[index] != name:
            raise ValueError('DNS address families have different TLS identities')
        if str(address) in endpoints:
            raise ValueError('duplicate DNS upstream address')
        if (index, address.version) in families:
            raise ValueError('duplicate DNS upstream address family')
        names[index] = name
        endpoints.add(str(address))
        families.add((index, address.version))
        order.append((index, address.version))
    if order != sorted(order) or order[0][0] != 1:
        raise ValueError('DNS upstream ordering must start with DNS1, IPv4 before IPv6')
    if custom == 'true' and len(set(names.values())) != 1:
        raise ValueError('custom CA mode requires one shared TLS SAN hostname')
    return values, upstreams


def custom_ca(raw: bytes, *, now: float | None = None) -> bytes:
    """Accept a PEM CA bundle or one DER CA; reject keys and other payloads."""
    if not raw or len(raw) > 256 * 1024:
        raise ValueError('custom DNS CA must be a bounded X.509 CA certificate or bundle')
    try:
        if raw.lstrip().startswith(b'-----BEGIN'):
            pattern = rb'-----BEGIN CERTIFICATE-----\s+[A-Za-z0-9+/=\r\n]+-----END CERTIFICATE-----'
            blocks = re.findall(pattern, raw)
            if not 1 <= len(blocks) <= 16 or re.sub(pattern, b'', raw).strip():
                raise ValueError('custom DNS CA must contain certificates only, never a private key')
            pem = '\n'.join(block.decode('ascii') for block in blocks) + '\n'
            count = len(blocks)
        else:
            pem = ssl.DER_cert_to_PEM_cert(raw)
            count = 1
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.load_verify_locations(cadata=pem)
        certificates = context.get_ca_certs()
        if len(certificates) != count:
            raise ValueError('custom DNS trust file requires distinct CA certificates with CA constraints')
        current = time.time() if now is None else now
        for certificate in certificates:
            if not ssl.cert_time_to_seconds(certificate['notBefore']) <= current < ssl.cert_time_to_seconds(certificate['notAfter']):
                raise ValueError('custom DNS CA is expired or not yet valid; check the certificate and system clock')
        return pem.encode('ascii')
    except (ssl.SSLError, UnicodeError) as error:
        raise ValueError('custom DNS CA is not a valid X.509 CA certificate') from error


def query_certificate(context: ssl.SSLContext, upstream: dict) -> dict:
    address = ipaddress.ip_address(upstream['address_data'])
    family = socket.AF_INET if address.version == 4 else socket.AF_INET6
    with socket.socket(family, socket.SOCK_STREAM) as transport:
        # Numeric addresses avoid bootstrap DNS dependencies and rebinding.
        transport.settimeout(5)
        transport.connect((str(address), upstream['tls_port']))
        with context.wrap_socket(transport, server_hostname=upstream['tls_auth_name']) as tls:
            return tls.getpeercert()


def verify_public(upstreams: list[dict], ca_file: str = PUBLIC_CA) -> None:
    context = ssl.create_default_context(cafile=ca_file)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.maximum_version = ssl.TLSVersion.TLSv1_3
    context.hostname_checks_common_name = False
    for index in dict.fromkeys(upstream['dns_index'] for upstream in upstreams):
        candidates = [upstream for upstream in upstreams if upstream['dns_index'] == index]
        for upstream in candidates:
            try:
                certificate = query_certificate(context, upstream)
                if not any(kind == 'DNS' for kind, _ in certificate.get('subjectAltName', ())):
                    raise ValueError(f'DNS{index} certificate has no DNS Subject Alternative Name')
            except ssl.SSLCertVerificationError as error:
                raise ValueError(f'DNS{index} certificate failed public CA/SAN authentication; check its configured TLS hostname and system clock') from error
            except OSError:
                # An installer with IPv4-only connectivity can authenticate
                # the resolver via IPv4. Stubby validates each family again
                # at runtime; no unauthenticated endpoint is ever trusted.
                continue
            print(f'event=stubby-upstream dns_index={index} status=ca-san-verified', flush=True)
            break
        else:
            raise ValueError(f'Cannot authenticate DNS{index}: no configured address completed a TLS handshake on the configured port')


def render(template: str, values: dict[str, str], upstreams: list[dict]) -> bytes:
    block = '\n\n'.join('\n'.join((
        '  - address_data: ' + json.dumps(upstream['address_data']),
        '    tls_port: ' + str(upstream['tls_port']),
        '    tls_auth_name: ' + json.dumps(upstream['tls_auth_name']),
    )) for upstream in upstreams)
    token = '  __INSTALLER_SYSTEM_NAMESERVERS_UPSTREAMS__'
    if template.count(token) != 1:
        raise ValueError('Stubby template requires one upstream block placeholder')
    template = template.replace(token, block)
    for key in ('SYSTEM_DNS_UPSTREAM_TLS_CA_FILE', 'APP_VETH_TLS_HOST_ADDRESS', 'APP_VETH_TLS_HOST_PORT'):
        value = values[key]
        if key == 'APP_VETH_TLS_HOST_ADDRESS' and not ipaddress.IPv4Address(value).is_loopback:
            raise ValueError('Stubby listener must be loopback')
        if key == 'APP_VETH_TLS_HOST_PORT' and (not value.isdecimal() or not 1024 <= int(value) <= 65535):
            raise ValueError('invalid Stubby listener port')
        template = template.replace('__INSTALLER_' + key + '__', value)
    if '__INSTALLER_' in template:
        raise ValueError('unresolved Stubby template placeholder')
    return template.encode('utf-8')


def directory(path: Path) -> None:
    for parent in [*reversed(path.parents), path]:
        if not parent.exists():
            parent.mkdir(mode=0o755)
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError('untrusted Stubby configuration destination directory')


def publish(path: Path, data: bytes) -> None:
    directory(path.parent)
    if path.exists() or path.is_symlink():
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1 or info.st_mode & 0o022:
            raise ValueError('untrusted Stubby configuration destination')
    fd, name = tempfile.mkstemp(prefix='.installer-stubby-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            os.fchmod(stream.fileno(), 0o644)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main(argv: list[str]) -> int:
    if os.geteuid() != 0 or len(argv) != 3:
        raise ValueError('usage (installer target chroot, root only): stubby-config.py TEMPLATE MAP CUSTOM_CA_OR_DASH')
    template, mapping, ca_input = argv
    values, upstreams = parse_policy(read_owned(Path(mapping), 128 * 1024))
    content = render(read_owned(Path(template), 64 * 1024).decode('utf-8'), values, upstreams)
    if values['SYSTEM_DNS_UPSTREAM_TLS_CA_CUSTOM_ENABLE'] == 'true':
        if ca_input == '-':
            raise ValueError('custom DNS CA input is required')
        certificate = custom_ca(read_owned(Path(ca_input), 256 * 1024))
        publish(Path(CUSTOM_CA), certificate)
    else:
        if ca_input != '-':
            raise ValueError('custom DNS CA input is forbidden in public CA mode')
        verify_public(upstreams)
    publish(OUTPUT, content)
    print('event=stubby-configuration status=published', flush=True)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main(sys.argv[1:]))
    except (OSError, ValueError, KeyError, TypeError) as error:
        message = ''.join(character if character.isprintable() else ' ' for character in str(error))[:600]
        print('Stubby configuration: ' + message, file=sys.stderr)
        raise SystemExit(2)
