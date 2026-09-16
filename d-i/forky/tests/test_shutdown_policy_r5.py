"""R5 target-staging/stop-policy regressions; no live services are touched.

Broker fragments below are reduced fixtures for documented upstream ordering,
not a claim to have run the target's dbus-broker or systemd 261.2 binaries.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest

import test_systemd_resource_policy as base

MODULE = base.SEED / 'scripts/late/dbus-broker.sh'
DESTS = tuple(f'etc/systemd/{scope}/dbus-broker.service.d/60-stop-timeout.conf'
              for scope in ('system', 'user'))


def active(text):
    return [s for s in text.splitlines() if s and not s.startswith('#')]


class BrokerStopPolicyTests(unittest.TestCase):
    def setUp(self):
        self.runner = base.ResourcePolicyTests()

    def shell(self, command, *, tmp, override='', profile=None, check=True):
        environment = '\n'.join('. ' + shlex.quote(str(base.SEED / name)) for name in
                                 ('hosts/installer/boot.env', 'hosts/installer/runtime.env'))
        environment += '\n. ' + shlex.quote(str(profile or base.PROFILES[0])) + '\n' + override
        return self.runner.shell('. ' + shlex.quote(str(MODULE)) + '\n' +
                                 self.runner.staging(tmp) + '\n' + command,
                                 profile=profile, override=environment, check=check)

    def test_every_profile_renders_both_managers_in_both_io_modes(self):
        for profile in base.PROFILES:
            for io in ('true', 'false'):
                with self.subTest(profile=profile.name, io=io), tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp) / 'target'; target.mkdir()
                    self.shell('validate_dbus_broker_policy_env\nstage_target_dbus_broker_stop_policy',
                               tmp=tmp, profile=profile,
                               override='SYSTEMD_DEFAULT_IOACCOUNTING_ENABLE=' + io)
                    for rel in DESTS:
                        p = target / rel
                        self.assertEqual(active(p.read_text()), ['[Service]', 'TimeoutStopSec=30s'])
                        self.assertEqual(p.stat().st_mode & 0o777, 0o644)
                        self.assertEqual(p.parent.stat().st_mode & 0o777, 0o755)
                    self.assertFalse(list(target.rglob('.installer-asset.*')))
                    self.assertFalse(list(target.rglob('*.wants')))

    def test_profile_overrides_replace_both_files_without_stale_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'target'; target.mkdir()
            for seconds in ('5', '45', '120', '30'):
                self.shell('stage_target_dbus_broker_stop_policy', tmp=tmp,
                           override=f'DBUS_BROKER_TIMEOUT_STOP_SEC={seconds}')
                for rel in DESTS:
                    self.assertEqual(active((target / rel).read_text()),
                                     ['[Service]', f'TimeoutStopSec={seconds}s'])
            self.assertFalse(list(target.rglob('.installer-asset.*')))

    def test_invalid_values_preserve_both_published_files(self):
        invalid = ('', '0', '4', '121', '-1', '030', '30s', 'infinity',
                   '9'*200, '30\nKillMode=none', '30;false', ' 30', '30 ')
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'target'; target.mkdir()
            self.shell('stage_target_dbus_broker_stop_policy', tmp=tmp)
            before = {rel: (target / rel).read_bytes() for rel in DESTS}
            for value in invalid:
                with self.subTest(value=value):
                    result = self.shell('stage_target_dbus_broker_stop_policy', tmp=tmp,
                        override='DBUS_BROKER_TIMEOUT_STOP_SEC=' + shlex.quote(value), check=False)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('canonical seconds in 5..120', result.stderr)
                    self.assertEqual({rel: (target / rel).read_bytes() for rel in DESTS}, before)
                    self.assertFalse(list(target.rglob('.installer-asset.*')))

    def test_broker_publisher_uses_policy_before_offline_enablement(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'target'; target.mkdir()
            # Only unrelated package/dpkg actions are mocked; rendering and the
            # actual configure_target_dbus_broker sequence are exercised.
            self.shell('''
repair_target_dbus_broker_packages() { :; }
stage_target_dbus_session_service_aliases() { :; }
enable_target_dbus_broker_units() {
  test -s "$INSTALLER_TARGET_DIR/etc/systemd/system/dbus-broker.service.d/60-stop-timeout.conf"
  test -s "$INSTALLER_TARGET_DIR/etc/systemd/user/dbus-broker.service.d/60-stop-timeout.conf"
}
configure_target_dbus_broker
''', tmp=tmp)
            for rel in DESTS:
                self.assertEqual(active((target / rel).read_text()), ['[Service]', 'TimeoutStopSec=30s'])
            self.assertTrue((target / 'etc/dbus-1/system-local.conf').exists())
            for scope in ('system', 'user'):
                hardening = target / f'etc/systemd/{scope}/dbus-broker.service.d/10-broker-hardening.conf'
                self.assertNotIn('__INSTALLER_', hardening.read_text())

    def test_failed_fetch_does_not_overwrite_existing_broker_dropin(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'target'; target.mkdir()
            self.shell('stage_target_dbus_broker_stop_policy', tmp=tmp)
            before = {rel: (target / rel).read_bytes() for rel in DESTS}
            result = self.shell('fetch_hook() { return 1; }\nstage_target_dbus_broker_stop_policy',
                                tmp=tmp, override='DBUS_BROKER_TIMEOUT_STOP_SEC=45', check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual({rel: (target / rel).read_bytes() for rel in DESTS}, before)
            self.assertFalse(list(target.rglob('.installer-asset.*')))

    def test_no_global_watchdog_or_user_manager_timeout_overrides(self):
        # Those policies need host evidence, not process-name-based guesses.
        for directory in ('etc/systemd/system.conf.d', 'etc/systemd/user.conf.d',
                          'etc/systemd/system/user@.service.d'):
            for p in (base.TARGET / directory).glob('*.conf'):
                self.assertNotRegex('\n'.join(active(p.read_text())),
                    r'(?m)^(?:RuntimeWatchdogSec|RebootWatchdogSec|KExecWatchdogSec|'
                    r'DefaultTimeoutStopSec|TimeoutStopSec|JobTimeoutSec|JobTimeoutAction)=')
        for rel in DESTS:
            source = base.TARGET / (rel + '.tmpl')
            self.assertEqual(active(source.read_text()),
                ['[Service]', 'TimeoutStopSec=__INSTALLER_DBUS_BROKER_TIMEOUT_STOP_SEC__s'])
        self.assertFalse(list(base.TARGET.rglob('dbus-broker-lau.service*')))

    def test_offline_effective_broker_timeout_kill_mode_and_ordering(self):
        binary = Path('/usr/lib/systemd/systemd')
        if not binary.is_file() or os.geteuid() != 0:
            self.skipTest('offline manager fixture requires systemd and root to drop privileges')
        for scope in ('system', 'user'):
            with self.subTest(scope=scope), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); root.chmod(0o755)
                target = root / 'target'; target.mkdir()
                self.shell('stage_target_dbus_broker_stop_policy', tmp=tmp)
                units = root / 'units'; units.mkdir()
                drop = units / 'dbus-broker.service.d'; drop.mkdir()
                shutil.copyfile(target / f'etc/systemd/{scope}/dbus-broker.service.d/60-stop-timeout.conf',
                                drop / '60-stop-timeout.conf')
                # Upstream broker ordering + a harmless executable substitute.
                (units / 'dbus-broker.service').write_text('''[Unit]
Description=Offline broker ordering fixture
DefaultDependencies=no
After=dbus.socket
Before=basic.target shutdown.target
Conflicts=shutdown.target
Requires=dbus.socket
[Service]
Type=notify-reload
ExecStart=/usr/bin/true
''' + ('Slice=session.slice\n' if scope == 'user' else ''))
                (units / 'dbus.service').symlink_to('dbus-broker.service')
                (units / 'dbus.socket').write_text('''[Unit]
DefaultDependencies=no
[Socket]
ListenStream=%t/r5-test-bus
Service=dbus-broker.service
''')
                (units / 'session.slice').write_text('[Unit]\nDefaultDependencies=no\n[Slice]\n')
                # A client ordered after the alias must stop before the broker.
                (units / 'client.service').write_text('''[Unit]
DefaultDependencies=no
After=dbus.service
Requires=dbus.service
[Service]
ExecStart=/usr/bin/true
''')
                (units / 'r5-test.target').write_text('[Unit]\nDefaultDependencies=no\nWants=client.service\n')
                for d in ('home', 'run', 'config'):
                    p=root/d; p.mkdir(mode=0o700); os.chown(p, 65534, 65534)
                env=dict(os.environ, HOME=str(root/'home'), XDG_RUNTIME_DIR=str(root/'run'),
                    XDG_CONFIG_HOME=str(root/'config'), SYSTEMD_UNIT_PATH=str(units)+':',
                    SYSTEMD_LOG_LEVEL='warning', SYSTEMD_LOG_TARGET='console')
                def drop_privileges():
                    os.setgroups([]); os.setgid(65534); os.setuid(65534)
                result=subprocess.run([str(binary), '--user', '--test', '--unit=r5-test.target'],
                    env=env, preexec_fn=drop_privileges, text=True, capture_output=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotRegex(result.stderr, r'Unknown (key|section)|Failed to parse|ordering cycle')
                blocks={}
                for part in re.split(r'\n\s*\u2192 Unit ', result.stdout)[1:]:
                    name, body=part.split(':\n', 1); blocks[name]=body
                broker=blocks['dbus-broker.service']
                for key, value in (('TimeoutStopSec', '30s'), ('KillMode', 'control-group'), ('SendSIGKILL', 'yes')):
                    self.assertRegex(broker, r'(?m)^\s*'+key+': '+re.escape(value)+r'$')
                self.assertIn('60-stop-timeout.conf', broker)
                self.assertRegex(broker, r'(?m)^\s*Before: client.service\b')
                self.assertRegex(broker, r'(?m)^\s*Before: shutdown.target\b')
                self.assertRegex(broker, r'(?m)^\s*After: dbus.socket\b')
                if scope == 'user':
                    self.assertRegex(broker, r'(?m)^\s*Slice: session.slice$')

    def test_target_verifier_requires_new_files_in_skeleton_and_home(self):
        source=(base.SEED/'scripts/desktop/verify.sh').read_text()
        for name in ('app-.scope', 'waybar.service', 'crystal-dock.service'):
            leaf=name+'.d/60-resource-class.conf'
            self.assertIn('/etc/skel-desktop/.config/systemd/user/'+leaf, source)
            self.assertIn('$account_home/.config/systemd/user/'+leaf, source)
        for rel in DESTS:
            self.assertIn('/'+rel, source)


if __name__ == '__main__':
    unittest.main()
