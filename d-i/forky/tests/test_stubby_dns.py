"""DNS trust, rendering and lifecycle tests; public Internet probes are mocked.

The loopback TLS test uses a disposable test CA and server certificate. It is
not a live check of the configured production resolvers or AppArmor enforcement.
"""
from __future__ import annotations

# Refuse host execution before importing runtime helpers or creating fixtures.
from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[3] / 'tools'))
# Copied checker/GUI fixtures still use the verified private checkout gate.
_isolation_sys.path.insert(0, '/workspace/repository/tools')
from isolation import require_test_isolation as _require_test_isolation
_isolation_sys.path.pop(0)
_require_test_isolation()

import json
import os
from pathlib import Path
import runpy
import shlex
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import unittest
from unittest import mock

import yaml
import test_kernel_veth_networking as fixtures
from test_environment import skip_unless_loopback_inet

SEED = Path(__file__).resolve().parents[1]
HELPER = runpy.run_path(str(SEED/'scripts/late/stubby-config.py'), run_name='stubby_test')
TEMPLATE = (SEED/'hooks/target/etc/stubby/stubby.yml.tmpl').read_text(encoding='utf-8')


def policy(custom=False):
    result = fixtures.SystemDNSRenderingTests().mapping()
    if result.returncode:
        raise AssertionError(result.stderr)
    values, upstreams = HELPER['parse_policy'](result.stdout.encode('ascii'))
    if custom:
        values['SYSTEM_DNS_UPSTREAM_TLS_CA_CUSTOM_ENABLE'] = 'true'
        values['SYSTEM_DNS_UPSTREAM_TLS_CA_FILE'] = HELPER['CUSTOM_CA']
        for upstream in upstreams:
            upstream['tls_auth_name'] = 'dns.lan.icramer.com'
    values['SYSTEM_NAMESERVERS_UPSTREAMS_JSON'] = json.dumps(upstreams)
    raw = ''.join(key + '=' + value + '\n' for key, value in values.items()).encode('ascii')
    return values, upstreams, raw


class StubbyPolicyTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('BUSYBOX_UDEB'), 'set BUSYBOX_UDEB to a verified Debian Installer BusyBox binary')
    def test_actual_mathless_installer_awk_renders_identity_and_dns_maps(self):
        binary = os.environ['BUSYBOX_UDEB']
        original = subprocess.run([binary, 'awk', 'BEGIN {print 2 ^ 8}'],
                                  capture_output=True, text=True, encoding='utf-8', timeout=5)
        self.assertNotEqual(original.returncode, 0, 'fixture must use the mathless installer build')
        self.assertIn('Math support is not compiled in', original.stderr)
        with tempfile.TemporaryDirectory(prefix='installer-awk-') as directory:
            wrapper = Path(directory)/'awk'
            wrapper.write_text('#!/bin/sh\nexec ' + shlex.quote(binary) + ' awk "$@"\n', encoding='ascii')
            wrapper.chmod(0o755)
            code = '. "$1/hosts/installer/identity.env"; . "$1/scripts/common/modules/app-veth-identity.sh"; . "$1/scripts/late/security.sh"; app_veth_dns_placeholder_map'
            result = subprocess.run(['/bin/sh', '-eu', '-c', code, 'installer-awk', str(SEED)], capture_output=True,
                                    text=True, encoding='utf-8', timeout=5,
                                    env={'PATH': directory + ':/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C'})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('APP_VETH_QBITTORRENT_ADDRESS=10.203.0.114\n', result.stdout)
            HELPER['parse_policy'](result.stdout.encode('ascii'))

    def test_block_yaml_uses_ordered_records_and_selected_trust_store(self):
        for custom in (False, True):
            with self.subTest(custom=custom):
                values, upstreams, _ = policy(custom)
                rendered = HELPER['render'](TEMPLATE, values, upstreams).decode()
                data = yaml.safe_load(rendered)
                self.assertEqual(data['upstream_recursive_servers'], [
                    {key: value for key, value in upstream.items() if key != 'dns_index'} for upstream in upstreams])
                self.assertEqual(data['tls_ca_file'], HELPER['CUSTOM_CA'] if custom else HELPER['PUBLIC_CA'])
                self.assertEqual(data['round_robin_upstreams'], 0)
                self.assertEqual(data['tls_authentication'], 'GETDNS_AUTHENTICATION_REQUIRED')
                self.assertEqual(data['dns_transport_list'], ['GETDNS_TRANSPORT_TLS'])
                self.assertIn('upstream_recursive_servers:\n  - address_data:', rendered)
                self.assertNotIn('__INSTALLER_', rendered)

    def test_dns3_and_custom_san_are_rendered_by_the_actual_shell_map(self):
        code = '''
. "$1/hosts/installer/identity.env"
. "$1/scripts/common/modules/app-veth-identity.sh"
. "$1/scripts/late/security.sh"
SYSTEM_NAMESERVERS_IPV4_DNS3=192.0.2.53
SYSTEM_NAMESERVERS_HOSTNAME_DNS3=three.example
SYSTEM_DNS_UPSTREAM_TLS_CA_CUSTOM_ENABLE=$2
SYSTEM_NAMESERVERS_TLS_SAN_CUSTOM=$3
app_veth_dns_placeholder_map
'''
        for custom in ('true', 'false'):
            result = subprocess.run(['/bin/sh', '-eu', '-c', code, 'dns-fixture', str(SEED), custom, 'dns.lan.icramer.com'],
                                    capture_output=True, text=True, encoding='utf-8', timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            values, upstreams = HELPER['parse_policy'](result.stdout.encode('ascii'))
            self.assertEqual(upstreams[-1]['address_data'], '192.0.2.53')
            self.assertEqual(upstreams[-1]['dns_index'], 3)
            if custom == 'true':
                self.assertEqual({entry['tls_auth_name'] for entry in upstreams}, {'dns.lan.icramer.com'})
            else:
                self.assertEqual(upstreams[-1]['tls_auth_name'], 'three.example')

    def test_invalid_switch_and_custom_name_fail_before_any_map_output(self):
        code = '''
. "$1/hosts/installer/identity.env"
. "$1/scripts/common/modules/app-veth-identity.sh"
. "$1/scripts/late/security.sh"
SYSTEM_DNS_UPSTREAM_TLS_CA_CUSTOM_ENABLE=$2
SYSTEM_NAMESERVERS_TLS_SAN_CUSTOM=$3
app_veth_dns_placeholder_map
'''
        for mode, name in (('yes', 'dns.example'), ('true', ''), ('true', '*.example'),
                           ('true', 'dns.example\nINJECT=yes'), ('true', '$(id)')):
            with self.subTest(mode=mode, name=name):
                result = subprocess.run(['/bin/sh', '-eu', '-c', code, 'dns-fixture', str(SEED), mode, name],
                                        capture_output=True, text=True, encoding='utf-8', timeout=5)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, '')

    def test_policy_rejects_duplicates_reordering_unexpected_fields_and_ca_paths(self):
        values, upstreams, _ = policy()
        variants = [list(reversed(upstreams)), [upstreams[0], upstreams[0]],
                    [{**upstreams[0], 'tls_port': 0}], [{**upstreams[0], 'tls_auth_name': '*.example'}],
                    [{**upstreams[0], 'address_data': 123}],
                    [{**upstreams[0], 'extra': 'ignored'}], []]
        for variant in variants:
            with self.subTest(upstreams=variant):
                values['SYSTEM_NAMESERVERS_UPSTREAMS_JSON'] = json.dumps(variant)
                raw = ''.join(key + '=' + value + '\n' for key, value in values.items()).encode('ascii')
                with self.assertRaises(ValueError):
                    HELPER['parse_policy'](raw)
        values['SYSTEM_NAMESERVERS_UPSTREAMS_JSON'] = json.dumps(upstreams)
        values['SYSTEM_DNS_UPSTREAM_TLS_CA_FILE'] = '/home/user/ca.pem'
        with self.assertRaises(ValueError):
            HELPER['parse_policy'](''.join(key + '=' + value + '\n' for key, value in values.items()).encode())

    def test_public_mode_queries_a_verified_san_identity_and_handles_ipv4_only_installers(self):
        _, upstreams, _ = policy()
        certificate = {'subjectAltName': (('DNS', 'validated.example'),)}
        replies = [OSError('IPv4 unavailable'), certificate, certificate]
        with mock.patch.dict(HELPER['verify_public'].__globals__, query_certificate=mock.Mock(side_effect=replies)):
            HELPER['verify_public'](upstreams)
            calls = HELPER['verify_public'].__globals__['query_certificate'].call_args_list
        self.assertEqual([call.args[1]['dns_index'] for call in calls], [1, 1, 2])
        context = calls[0].args[0]
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertFalse(context.hostname_checks_common_name)

    def test_certificate_authentication_errors_and_absent_sans_fail_closed(self):
        _, upstreams, _ = policy()
        for reply in (ssl.SSLCertVerificationError('wrong name or issuer'), {'subject': ((('commonName', 'only-cn'),),)}):
            with self.subTest(reply=reply):
                query = mock.Mock(side_effect=reply) if isinstance(reply, Exception) else mock.Mock(return_value=reply)
                with mock.patch.dict(HELPER['verify_public'].__globals__, query_certificate=query):
                    with self.assertRaises(ValueError):
                        HELPER['verify_public'](upstreams)
                self.assertEqual(query.call_count, 1)

    def test_public_failure_publishes_nothing_and_custom_mode_does_not_probe(self):
        for custom in (False, True):
            _, _, raw = policy(custom)
            published = mock.Mock()
            verify = mock.Mock(side_effect=ValueError('TLS unavailable'))
            reads = mock.Mock(side_effect=[raw, TEMPLATE.encode(), b'fixture certificate'])
            with mock.patch.dict(HELPER['main'].__globals__, read_owned=reads, publish=published,
                                 verify_public=verify, custom_ca=mock.Mock(return_value=b'validated CA')), \
                    mock.patch.object(os, 'geteuid', return_value=0):
                if custom:
                    self.assertEqual(HELPER['main'](['template', 'map', 'ca']), 0)
                    verify.assert_not_called()
                    self.assertEqual([call.args[0] for call in published.call_args_list],
                                     [Path(HELPER['CUSTOM_CA']), HELPER['OUTPUT']])
                else:
                    with self.assertRaises(ValueError):
                        HELPER['main'](['template', 'map', '-'])
                    published.assert_not_called()

    def test_installer_wiring_uses_private_initrd_reader_and_fixed_ca_path(self):
        installer = (SEED/'scripts/late/security.sh').read_text(encoding='utf-8')
        section = installer.split('configure_target_stubby() (', 1)[1].split('\nconfigure_target_app_veth()', 1)[0]
        self.assertIn('preseed_env_read_value dns_upstream_tls_ca_name_custom', section)
        self.assertIn('preseed_env_check_file "/$stubby_ca_name"', section)
        self.assertIn('stubby-config.py', section)
        self.assertIn('/usr/bin/python3 -I -B', section)
        self.assertNotIn('installer_cmdline_value', section)
        self.assertNotIn('source_transfer', section)
        profile = (SEED/'hooks/target/etc/apparmor.d/app-veth.tmpl').read_text(encoding='utf-8')
        self.assertIn('/etc/stubby/ca/upstream-custom.pem r,', profile)
        for role in ('standard', 'enhanced'):
            packages = (SEED/f'classes/class-select/security/{role}.cfg').read_text(encoding='utf-8')
            self.assertIn('python3 ca-certificates', packages)


@unittest.skipUnless(shutil.which('openssl'), 'OpenSSL required for disposable certificate fixtures')
class CertificateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='stubby-certificate-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        commands = [
            ['req', '-new', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '2', '-subj', '/CN=Fixture CA',
             '-addext', 'basicConstraints=critical,CA:TRUE', '-addext', 'keyUsage=critical,keyCertSign,cRLSign',
             '-keyout', str(cls.root/'ca.key'), '-out', str(cls.root/'ca.pem')],
            ['req', '-new', '-newkey', 'rsa:2048', '-nodes', '-subj', '/CN=dns.fixture.invalid',
             '-keyout', str(cls.root/'server.key'), '-out', str(cls.root/'server.csr')],
        ]
        (cls.root/'extensions').write_text('subjectAltName=DNS:dns.fixture.invalid\nbasicConstraints=critical,CA:FALSE\n'
                                         'keyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n', encoding='ascii')
        commands.append(['x509', '-req', '-days', '1', '-in', str(cls.root/'server.csr'), '-CA', str(cls.root/'ca.pem'),
                         '-CAkey', str(cls.root/'ca.key'), '-CAcreateserial', '-extfile', str(cls.root/'extensions'),
                         '-out', str(cls.root/'server.pem')])
        for command in commands:
            result = subprocess.run([shutil.which('openssl'), *command], capture_output=True, timeout=15, umask=0o077)
            if result.returncode:
                raise AssertionError('certificate fixture generation failed: ' + result.stderr.decode()[:400])

    def test_real_pem_and_der_ca_are_normalized_and_keys_leaf_certs_and_expiry_are_rejected(self):
        pem = (self.root/'ca.pem').read_bytes()
        der = ssl.PEM_cert_to_DER_cert(pem.decode('ascii'))
        self.assertEqual(HELPER['custom_ca'](pem), HELPER['custom_ca'](der))
        for value in (b'', b'invalid DER', pem + (self.root/'ca.key').read_bytes(), (self.root/'server.pem').read_bytes()):
            with self.subTest(kind=value[:30]), self.assertRaises(ValueError):
                HELPER['custom_ca'](value)
        with self.assertRaisesRegex(ValueError, 'expired'):
            HELPER['custom_ca'](pem, now=time.time() + 3 * 86400)

    @skip_unless_loopback_inet
    def test_real_tls_handshake_accepts_matching_san_and_rejects_wrong_san(self):
        for name, success in (('dns.fixture.invalid', True), ('wrong.fixture.invalid', False)):
            with self.subTest(name=name), socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                listener.bind(('127.0.0.1', 0))
                listener.listen(1)
                listener.settimeout(10)
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                context.load_cert_chain(str(self.root/'server.pem'), str(self.root/'server.key'))
                def serve():
                    try:
                        with listener.accept()[0] as connection:
                            connection.settimeout(5)
                            with context.wrap_socket(connection, server_side=True):
                                pass
                    except (OSError, ssl.SSLError):
                        pass
                thread = threading.Thread(target=serve, daemon=True)
                thread.start()
                upstreams = [{'dns_index': 1, 'address_data': '127.0.0.1',
                              'tls_port': listener.getsockname()[1], 'tls_auth_name': name}]
                try:
                    if success:
                        HELPER['verify_public'](upstreams, str(self.root/'ca.pem'))
                    else:
                        with self.assertRaisesRegex(ValueError, 'CA/SAN authentication'):
                            HELPER['verify_public'](upstreams, str(self.root/'ca.pem'))
                finally:
                    thread.join(timeout=10)
                    self.assertFalse(thread.is_alive(), 'TLS fixture did not terminate')


if __name__ == '__main__':
    unittest.main()
