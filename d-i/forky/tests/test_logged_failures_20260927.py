"""Regression tests for sealing and scoped LAN sharing.

No target services, firewall rules or real sealing keys are created. External
RPCs are mocked; generated policy and provisioning functions are real.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from payload_fixture import logging_text, read_text
import test_security_hardening_20260924 as security_fixture

module = security_fixture.module

SEED = Path(__file__).resolve().parents[1]
TARGET = SEED / 'hooks/target'
SECURITY = SEED / 'scripts/late/security.sh'


@unittest.skipUnless(os.geteuid() == 0, 'private root-owned sealing fixture')
class SealingReadOnlyTests(unittest.TestCase):
    setUp = security_fixture.JournalSealing.setUp

    def prepare(self, exported=False):
        machine = 'a' * 32
        self.m.JOURNAL = self.m.STATE.parent / 'journal'
        (self.m.JOURNAL / machine).mkdir(parents=True)
        fss = self.m.JOURNAL / machine / 'fss'
        fss.write_bytes(b'fixture-fss')
        fss.chmod(0o640)
        self.m.KEY.write_bytes(self.key)
        self.m.KEY.chmod(0o600)
        (self.m.STATE / 'lock').touch(mode=0o600)
        self.m.write_record(dict(version=1, machine_id=machine, exported=exported,
                                 rotated=True, verification_sha256=hashlib.sha256(self.key).hexdigest()))
        machine_file = self.m.STATE.parent / 'machine-id'
        machine_file.write_text(machine)
        self.stack = self.enterContext(contextlib.ExitStack())
        self.stack.enter_context(mock.patch.object(self.m, 'enabled_policy', return_value=True))
        self.stack.enter_context(mock.patch.object(self.m, 'Path', side_effect=lambda p:
            machine_file if p == '/etc/machine-id' else Path(p)))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))

    def test_status_uses_existing_read_only_shared_lock_without_mutations(self):
        self.prepare()
        before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.m.STATE.iterdir()}
        real_open, real_flock = os.open, self.m.fcntl.flock
        with mock.patch.object(self.m.os, 'open', wraps=real_open) as opened, \
             mock.patch.object(self.m.fcntl, 'flock', wraps=real_flock) as flock, \
             mock.patch.object(self.m, 'migrate_legacy_key') as migrate, \
             mock.patch.object(self.m, 'write_record') as write:
            self.assertEqual(self.m.main(['--status']), 0)
        locks = [call.args[1] for call in opened.call_args_list if call.args[0] == self.m.STATE / 'lock']
        self.assertEqual(len(locks), 1)
        self.assertEqual(locks[0] & os.O_ACCMODE, os.O_RDONLY)
        self.assertFalse(locks[0] & os.O_CREAT)
        self.assertEqual(flock.call_args.args[1], self.m.fcntl.LOCK_SH)
        migrate.assert_not_called()
        write.assert_not_called()
        self.assertEqual(before, {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.m.STATE.iterdir()})

    def test_status_does_not_delete_acknowledged_seed_but_setup_recovers(self):
        self.prepare(exported=True)
        self.assertEqual(self.m.main(['--status']), 0)
        self.assertTrue(self.m.KEY.exists())
        with self.assertRaisesRegex(ValueError, 'release gate'):
            self.m.main(['--release-check'])
        self.assertEqual(self.m.main(['--setup']), 0)
        self.assertFalse(self.m.KEY.exists())
        self.assertEqual(self.m.main(['--release-check']), 0)

    def test_missing_state_is_not_created_by_status(self):
        self.prepare()
        missing = self.m.STATE.parent / 'missing-state'
        self.m.STATE = missing
        with self.assertRaises(OSError):
            self.m.main(['--status'])
        self.assertFalse(missing.exists())

    def test_status_does_not_create_a_missing_lock(self):
        self.prepare()
        lock = self.m.STATE / 'lock'
        lock.unlink()
        with self.assertRaises(OSError):
            self.m.main(['--status'])
        self.assertFalse(lock.exists())

    def test_status_rejects_corrupted_acknowledged_seed_without_deleting_it(self):
        self.prepare(exported=True)
        self.m.KEY.write_bytes(self.key.replace(b'aaaaaa', b'bbbbbb'))
        with self.assertRaises(ValueError):
            self.m.main(['--status'])
        self.assertTrue(self.m.KEY.exists())

    def test_status_rejects_symlinked_seed(self):
        self.prepare()
        destination = self.m.STATE.parent / 'private-key'
        self.m.KEY.rename(destination)
        self.m.KEY.symlink_to(destination)
        with self.assertRaises((OSError, ValueError)):
            self.m.main(['--status'])
        self.assertEqual(destination.read_bytes(), self.key)


class LanSharingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.nft = module(TARGET / 'usr/local/sbin/nft-policy-generate.py')

    def shell(self, body, **values):
        script = 'set -eu\ninstaller_fatal() { printf "%s\\n" "$*" >&2; exit 1; }\n'
        script += '. ' + shlex.quote(str(SECURITY)) + '\n'
        script += '\n'.join(f'{key}={shlex.quote(value)}' for key, value in values.items()) + '\n' + body
        return subprocess.run(['/bin/sh', '-c', script], capture_output=True, text=True, timeout=10)

    def policy(self, ipv4='192.168.50.0/24', ipv6='2001:9b1:29fd:4e00::/64', **overrides):
        values = dict(MANAGED_NETWORK_IPV4_ENABLED='true' if ipv4 else 'false',
                      MANAGED_NETWORK_IPV6_ENABLED='true' if ipv6 else 'false',
                      MANAGED_NETWORK_IPV4_NETWORK_CIDRS=ipv4,
                      MANAGED_NETWORK_IPV6_NETWORK_CIDRS=ipv6,
                      MANAGED_NETWORK_ETHERNET_IFACE='eth0', MANAGED_NETWORK_WIFI_IFACE='wifi0')
        values.update(overrides)
        result = self.shell('nftables_lan_share_service_placeholder_map', **values)
        self.assertEqual(result.returncode, 0, result.stderr)
        tokens = dict(line.split('=', 1) for line in result.stdout.splitlines())
        overlay = (TARGET / 'etc/nftables/services/lan-share.yml.tmpl').read_text()
        for key, value in tokens.items():
            overlay = overlay.replace('__INSTALLER_' + key + '__', value)
        profile = (TARGET / 'etc/nftables/profiles/desktop.yml.tmpl').read_text()
        for key in ('MANAGED_NETWORK_ETHERNET_IFACE', 'MANAGED_NETWORK_WIFI_IFACE'):
            profile = profile.replace('__INSTALLER_' + key + '__', values[key])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'profile.yml').write_text(profile)
            (root / 'overlay.yml').write_text(overlay)
            ctx = self.nft.RenderContext()
            policy = self.nft.load_policy(root / 'profile.yml', [root / 'overlay.yml'], False, ctx)
            self.nft.validate_unresolved(policy)
            maps = self.nft.build_define_maps(policy, ctx)
            rendered = self.nft.render_filter(policy, maps, ctx, False)
        return policy, [line for line in rendered.splitlines() if 'service lan_share_http inbound' in line]

    def test_dual_stack_sharing_is_interface_and_exact_subnet_scoped(self):
        policy, rules = self.policy()
        self.assertTrue(rules)
        self.assertTrue(any('ip saddr 192.168.50.0/24' in line for line in rules))
        self.assertTrue(any('ip6 saddr 2001:9b1:29fd:4e00::/64' in line for line in rules))
        for line in rules:
            self.assertIn('iifname', line)
            self.assertIn('eth0', line)
            self.assertIn('wifi0', line)
            self.assertIn('tcp dport 8000', line)
            self.assertNotIn('tailscale0', line)
            self.assertNotIn('0.0.0.0/0', line)
        self.assertEqual(policy['policies'], dict(input='drop', forward='drop', output='accept'))

    def test_single_stack_does_not_emit_an_unrestricted_other_family(self):
        for ipv4, ipv6, forbidden in [('192.168.50.0/24', '', 'ip6 '), ('', 'fd12:3456::/64', 'ip ' )]:
            with self.subTest(ipv4=ipv4, ipv6=ipv6):
                _, rules = self.policy(ipv4, ipv6)
                self.assertTrue(rules)
                self.assertTrue(all(forbidden not in line for line in rules))
                self.assertTrue(all('saddr ' in line for line in rules))

    def test_no_subnets_fails_closed(self):
        with self.assertRaisesRegex(self.nft.PolicyError, 'non-empty IP allowlist'):
            self.policy('', '')

    def test_disabled_family_cannot_reuse_a_stale_subnet(self):
        _, rules = self.policy(MANAGED_NETWORK_IPV6_ENABLED='false')
        self.assertTrue(rules)
        self.assertFalse(any('ip6 ' in line for line in rules))

    def test_default_route_and_injected_interface_are_rejected(self):
        for values in [dict(MANAGED_NETWORK_IPV4_ENABLED='true', MANAGED_NETWORK_IPV4_NETWORK_CIDRS='0.0.0.0/0'),
                       dict(MANAGED_NETWORK_ETHERNET_IFACE='eth0;touch /tmp/pwn'),
                       dict(MANAGED_NETWORK_ETHERNET_IFACE='wifi0')]:
            with self.subTest(values=values):
                result = self.shell('nftables_lan_share_service_placeholder_map', **values)
                self.assertNotEqual(result.returncode, 0)

    def test_all_shipped_hosts_opt_in_but_none_stays_none(self):
        for path in (SEED / 'hosts/profiles').glob('*.env'):
            self.assertIn('NFT_SERVICES="lan-share"', path.read_text())
        result = self.shell('late_command_nftables_services', NFT_SERVICES='none')
        self.assertEqual((result.returncode, result.stdout), (0, ''))
        result = self.shell('late_command_nftables_services', NFT_SERVICES='LAN-SHARE,lan-share')
        self.assertEqual((result.returncode, result.stdout.strip()), (0, 'lan-share'))

    def test_firewall_status_uses_only_owned_filter_table(self):
        import ast
        source = (TARGET / 'usr/local/lib/python3.14/dist-packages/labwc_firewall/cli.py.tmpl').read_text()
        tree = ast.parse(source)
        fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == '_status')
        calls = [node for node in ast.walk(fn) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute) and node.func.attr == 'run_or_fail']
        self.assertEqual(len(calls), 2)
        self.assertEqual({tuple(arg.value for arg in call.args[2:]) for call in calls},
                         {('list', 'chain', 'inet', 'labwc_filter', 'local_input'),
                          ('list', 'chain', 'inet', 'labwc_filter', 'local_output')})

    def test_firewall_stop_preserves_other_owners(self):
        text = (TARGET / 'etc/systemd/system/nftables.service.d/override.conf').read_text()
        self.assertNotIn('flush ruleset', text)
        self.assertIn('ExecStop=/usr/sbin/nft destroy table inet labwc_filter', text)
        self.assertIn('ExecStop=/usr/sbin/nft destroy table ip labwc_nat', text)


class MullvadLanTests(unittest.TestCase):
    def invoke(self, fail_until):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            counter = root / 'calls'
            counter.write_text('0')
            rpc = root / 'mullvad'
            rpc.write_text('#!/bin/sh\n[ "$*" = "lan set allow" ] || exit 99\n'
                           'n=$(cat "$COUNTER"); n=$((n+1)); echo "$n" > "$COUNTER"\n'
                           '[ "$n" -gt "$FAIL_UNTIL" ] || { echo "RPC unavailable" >&2; exit 1; }\n')
            rpc.chmod(0o700)
            script = (TARGET / 'usr/local/libexec/mullvad-lan-allow').read_text()
            script = script.replace('/usr/bin/mullvad lan set allow', shlex.quote(str(rpc)) + ' lan set allow')
            script = script.replace('/usr/bin/sleep 1', '/usr/bin/true')
            result = subprocess.run(['/bin/sh', '-c', script], capture_output=True, text=True, timeout=10,
                                    env=dict(os.environ, COUNTER=str(counter), FAIL_UNTIL=str(fail_until)))
            return result, int(counter.read_text())

    def test_simple_daemon_startup_race_is_retried_then_succeeds(self):
        result, calls = self.invoke(2)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, 3)

    def test_permanent_failure_is_bounded_and_propagated(self):
        result, calls = self.invoke(100)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(calls, 10)
        self.assertIn('RPC unavailable', result.stderr)

    def test_conditional_staging_and_cleanup_preserve_other_dropins(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'target'
            binary = target / 'usr/bin/mullvad'
            binary.parent.mkdir(parents=True)
            binary.write_text('#!/bin/sh\nexit 0\n')
            binary.chmod(0o755)
            directory = target / 'etc/systemd/system/mullvad-daemon.service.d'
            directory.mkdir(parents=True)
            admin = directory / '90-admin.conf'
            admin.write_text('[Service]\nRestartSec=5s\n')
            script = SECURITY.read_text().replace('/target/', str(target) + '/')
            script += '\ninstaller_repo_join_var() { printf "%s/%s\\n" "$FIXTURE_SOURCE" "$2"; }\n'
            script += 'stage_target_asset() { install -D -m "$3" "$1" "$FIXTURE_TARGET$2"; }\n'
            env = dict(os.environ, FIXTURE_SOURCE=str(TARGET), FIXTURE_TARGET=str(target))
            helper = target / 'usr/local/libexec/mullvad-lan-allow'
            dropin = directory / '25-lan-sharing.conf'
            for selected, cli, expected in [('lan-share', True, True), ('none', True, False),
                                            ('crowdsec lan-share', True, True), ('lan-share', False, False)]:
                with self.subTest(selected=selected, cli=cli):
                    if not cli:
                        binary.unlink()
                    result = subprocess.run(['/bin/sh', '-eu', '-c', script +
                        'stage_target_nftables_mullvad_lan_policy ' + shlex.quote(selected)],
                        env=env, capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(helper.exists(), expected)
                    self.assertEqual(dropin.exists(), expected)
                    self.assertEqual(admin.read_text(), '[Service]\nRestartSec=5s\n')
                    if expected:
                        self.assertEqual(helper.read_bytes(), (TARGET / 'usr/local/libexec/mullvad-lan-allow').read_bytes())
                        self.assertEqual(helper.stat().st_mode & 0o777, 0o755)
                        self.assertEqual(dropin.stat().st_mode & 0o777, 0o644)

    def test_only_supported_lan_setting_is_changed(self):
        helper = (TARGET / 'usr/local/libexec/mullvad-lan-allow').read_text()
        unit = (TARGET / 'etc/systemd/system/mullvad-daemon.service.d/25-lan-sharing.conf').read_text()
        self.assertIn('--kill-after=1s 2s /usr/bin/mullvad lan set allow', helper)
        self.assertIn('--kill-after=2s 45s /usr/local/libexec/mullvad-lan-allow', unit)
        self.assertNotIn('lockdown-mode set off', helper)
        self.assertNotIn('nft ', helper)
        security = SECURITY.read_text()
        self.assertIn('stage_target_nftables_mullvad_lan_policy "$selected_services"', security)
        self.assertIn('[ -x /target/usr/bin/mullvad ]', security)


class AppArmorWiringTests(unittest.TestCase):
    def test_status_policy_is_exact_read_only_and_reloaded_before_exec(self):
        text = read_text(SEED / 'scripts/firstboot/assets/etc/apparmor.d/firstboot.tmpl')
        self.assertIn('/var/lib/journal-sealing/verification-key r,', text)
        self.assertIn('/var/lib/journal-sealing/lock rk,', text)
        self.assertNotIn('/var/lib/journal-sealing/**', text)
        unit = (SEED / 'scripts/firstboot/assets/etc/systemd/system/firstboot.service').read_text()
        self.assertIn('Requires=apparmor.service ', unit)
        self.assertIn('After=apparmor.service ', unit)
        self.assertIn('ExecStartPre=/usr/sbin/apparmor_parser --replace --skip-cache /etc/apparmor.d/firstboot', unit)

    @unittest.skipUnless(shutil.which('apparmor_parser'), 'AppArmor parser is unavailable')
    def test_firstboot_profile_parses_offline_with_shipped_abstractions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'abstractions').mkdir()
            for source in (TARGET / 'etc/apparmor.d/abstractions').iterdir():
                if source.is_file():
                    (root / 'abstractions' / source.name.removesuffix('.tmpl')).write_text(logging_text(read_text(source)))
            profile = root / 'firstboot'
            profile.write_text(logging_text(read_text(SEED / 'scripts/firstboot/assets/etc/apparmor.d/firstboot.tmpl')))
            result = subprocess.run([shutil.which('apparmor_parser'), '--skip-kernel-load', '--skip-cache',
                                     '-I', str(root), '-I', '/etc/apparmor.d', str(profile)],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
