"""R6: staged policy, synchronous single-force handoff, and mocked handoff.

Never run a power command. systemd checks use verify only; calls from the
production worker are mocked. Fixture units are not host units.
"""
from __future__ import annotations
import contextlib
import io
import itertools
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import types
import unittest
from unittest import mock
import test_systemd_resource_policy as base

POWER_FILES = tuple(f'etc/systemd/system/labwc-power-{action}.{kind}'
                    for action in ('reboot', 'poweroff') for kind in ('service', 'target'))
WIRE = 'etc/systemd/user/wireplumber.service.d/60-resource-class.conf'


def directives(path):
    return [line for line in path.read_text().splitlines()
            if line.strip() and not line.lstrip().startswith('#')]


def worker_module():
    path = base.TARGET / 'usr/local/libexec/labwc-admin-action-worker'
    result = types.ModuleType('r6_power_worker'); result.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), 'exec'), result.__dict__)
    return result


class IndependentIOTests(unittest.TestCase):
    def setUp(self):
        self.runner = base.ResourcePolicyTests()

    def test_all_profiles_all_four_switch_combinations_and_republication(self):
        self.assertEqual(len(base.PROFILES), 13)
        for profile in base.PROFILES:
            with self.subTest(profile=profile.name), tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / 'target'; target.mkdir()
                for unit in base.SERVICE_CLASSES:
                    relative = f'{base.USER_BASE}/{unit}.service'
                    p = target / relative; p.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(base.TARGET / relative, p)
                units = target / 'usr/lib/systemd/user'; units.mkdir(parents=True)
                (units / 'wireplumber.service').write_text('[Service]\nExecStart=/usr/bin/true\n')
                for accounting, weights in itertools.product(('true', 'false'), repeat=2):
                    with self.subTest(accounting=accounting, weights=weights):
                        self.runner.shell(self.runner.staging(tmp) + '''
stage_target_systemd_resource_policy_assets
desktop_install_user_resource_policy
''', profile=profile, override=f'SYSTEMD_DEFAULT_IOACCOUNTING_ENABLE={accounting}\nSYSTEMD_IOWEIGHT_ENABLE={weights}')
                        for scope in ('system', 'user'):
                            p = target / f'etc/systemd/{scope}.conf.d/60-resource-accounting.conf'
                            self.assertEqual(directives(p), ['[Manager]', 'DefaultMemoryAccounting=yes',
                                'DefaultTasksAccounting=yes', 'DefaultIOAccounting=' + ('yes' if accounting == 'true' else 'no')])
                        found = []
                        for p in target.rglob('*.conf'):
                            text = p.read_text()
                            self.assertFalse(base.TOKEN.search(text), str(p))
                            self.assertNotRegex(text, r'(?m)^IOWeight=\s*$')
                            found.extend(re.findall(r'(?m)^IOWeight=([0-9]+)$', text))
                            self.assertEqual(p.stat().st_mode & 0o777, 0o644)
                        self.assertEqual(sorted(found), sorted(['200', '100', '30', '300', '30', '50'])
                                         if weights == 'true' else [])
                        self.assertEqual(directives(target / WIRE), ['[Service]', 'Slice=session.slice'])
                        self.assertIn('CPUWeight=300', (target / f'{base.USER_BASE}/labwc-compositor.service.d/60-resources.conf').read_text())
                        self.assertFalse(list(target.rglob('.installer-asset.*')))
                        self.assertFalse(list(target.rglob('*.wants')))

    def test_all_profiles_declare_both_switches_once_and_default_off(self):
        for profile in base.PROFILES:
            for key in ('SYSTEMD_DEFAULT_IOACCOUNTING_ENABLE', 'SYSTEMD_IOWEIGHT_ENABLE'):
                with self.subTest(profile=profile.name, key=key):
                    self.assertEqual(re.findall(r'^' + key + r'="(true|false)"$', profile.read_text(), re.M), ['false'])

    def test_desktop_stage_alone_replaces_stale_manager_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'target'; target.mkdir()
            for scope in ('system', 'user'):
                p = target / f'etc/systemd/{scope}.conf.d/60-resource-accounting.conf'
                p.parent.mkdir(parents=True); p.write_text('[Manager]\nDefaultIOAccounting=yes\n')
            self.runner.shell(self.runner.staging(tmp) + 'desktop_install_user_resource_policy')
            for scope in ('system', 'user'):
                self.assertIn('DefaultIOAccounting=no', (target / f'etc/systemd/{scope}.conf.d/60-resource-accounting.conf').read_text())

    def test_new_flag_invalid_or_missing_is_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'target'; target.mkdir()
            sentinel = target / 'sentinel'; sentinel.write_text('untouched')
            for override in ['unset SYSTEMD_IOWEIGHT_ENABLE'] + [
                    'SYSTEMD_IOWEIGHT_ENABLE=' + shlex.quote(value)
                    for value in ('', 'yes', 'TRUE', 'false\nIOWeight=10', '$(touch /bad)', 'false ')]:
                with self.subTest(override=override):
                    result = self.runner.shell(self.runner.staging(tmp) + 'stage_target_systemd_resource_policy_assets',
                                               override=override, check=False)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('SYSTEMD_IOWEIGHT_ENABLE must be true or false', result.stderr)
                    self.assertEqual(list(target.iterdir()), [sentinel])

    def test_literal_weight_lines_are_also_omitted_without_touching_cpu(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'target'; target.mkdir()
            self.runner.shell(self.runner.staging(tmp) + '''
fetch_hook() { printf '[Service]\n IOWeight=42\nStartupIOWeight=10\nCPUWeight=200\n' >"$2"; }
render_target_resource_asset synthetic /etc/systemd/system/test.service.d/60-resources.conf 0644
''')
            p = target / 'etc/systemd/system/test.service.d/60-resources.conf'
            self.assertEqual(directives(p), ['[Service]', 'CPUWeight=200'])
            self.assertFalse(list(target.rglob('.installer-asset.*')))

    def test_both_switches_are_portable_in_all_combinations(self):
        if not shutil.which('busybox'):
            self.skipTest('BusyBox unavailable')
        for accounting, weights in itertools.product(('true', 'false'), repeat=2):
            override = f'SYSTEMD_DEFAULT_IOACCOUNTING_ENABLE={accounting}\nSYSTEMD_IOWEIGHT_ENABLE={weights}'
            self.assertEqual(self.runner.shell('systemd_resource_placeholder_map', override=override).stdout,
                             self.runner.shell('systemd_resource_placeholder_map', override=override, shell='busybox').stdout)


class FixedPowerUnitTests(unittest.TestCase):
    def test_retired_barrier_units_are_not_distributed(self):
        for rel in POWER_FILES:
            self.assertFalse((base.TARGET / rel).exists(), rel)

    def test_production_publisher_removes_only_retired_units_idempotently(self):
        runner = base.ResourcePolicyTests()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'target'; target.mkdir()
            for rel in POWER_FILES:
                p = target / rel; p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text('legacy barrier unit')
            sentinel = target / 'etc/systemd/system/retained.service'
            sentinel.write_text('retained')
            for _ in range(2):
                runner.shell(runner.staging(tmp) + 'desktop_remove_legacy_power_transactions')
                self.assertEqual([p for p in target.rglob('*') if p.is_file()], [sentinel])
            self.assertEqual(sentinel.read_text(), 'retained')
            self.assertFalse(list(target.rglob('*.wants')))

    def test_existing_application_and_wireplumber_classes_are_explicit(self):
        for leaf, section, cls in (
            ('app-.scope.d/60-resource-class.conf', 'Scope', 'app'),
            ('waybar.service.d/60-resource-class.conf', 'Service', 'app'),
            ('crystal-dock.service.d/60-resource-class.conf', 'Service', 'app')):
            self.assertEqual(directives(base.TARGET / base.USER_BASE / leaf), [f'[{section}]', f'Slice={cls}.slice'])
        self.assertEqual(directives(base.TARGET / WIRE), ['[Service]', 'Slice=session.slice'])
        verifier = (base.SEED / 'scripts/desktop/verify.sh').read_text()
        for rel in (WIRE,):
            self.assertIn('/' + rel, verifier)


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.power = worker_module()
        self.worker = self.power.Worker(1000, 'desktop', 'reboot')

    def test_both_actions_submit_exactly_one_force_after_quiescence(self):
        for action in ('reboot', 'poweroff'):
            worker = self.power.Worker(1000, 'desktop', action)
            worker.quiesced = True
            with mock.patch.object(self.power, 'run', return_value='') as run, \
                    contextlib.redirect_stderr(io.StringIO()) as output:
                worker.final_power_action()
            run.assert_called_once_with(['/usr/bin/systemctl', '--force', '--no-ask-password', action], timeout=20)
            self.assertTrue(worker.committed)
            self.assertTrue(worker.handoff_attempted)
            self.assertIn('systemctl --force ' + action, output.getvalue())

    def test_unquiesced_desktop_never_submits_power(self):
        with mock.patch.object(self.power, 'run') as run:
            with self.assertRaisesRegex(self.power.Error, 'quiesced'):
                self.worker.final_power_action()
            run.assert_not_called()
        self.assertFalse(self.worker.committed)

    def test_uncertain_submission_never_retries_or_cancels(self):
        self.worker.quiesced = True
        with mock.patch.object(self.power, 'run', side_effect=self.power.Error('lost reply')) as run, \
                contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(self.power.Error, 'status uncertain'):
                self.worker.final_power_action()
            with self.assertRaisesRegex(self.power.Error, 'only once'):
                self.worker.final_power_action()
        self.assertTrue(self.worker.committed)
        self.assertEqual(run.call_count, 1)

    def test_unaccepted_actions_cannot_form_a_unit_name(self):
        for action in ('logout', 'suspend', 'reboot;id', '../poweroff', 'reboot --force'):
            self.worker.action = action
            with mock.patch.object(self.power, 'run') as run:
                with self.assertRaises(self.power.Error):
                    self.worker.final_power_action()
                run.assert_not_called()

    def test_saving_and_other_account_recheck_precede_handoff(self):
        events = []
        with mock.patch.object(self.worker, 'userctl', side_effect=lambda *a, **k: events.append('active')), \
             mock.patch.object(self.worker, 'protect_other_sessions', side_effect=lambda: events.append('accounts')), \
             mock.patch.object(self.power, 'ready', side_effect=lambda: events.append('ready')), \
             mock.patch.object(self.worker, 'helper', side_effect=lambda a: events.append(a)), \
             mock.patch.object(self.worker, 'quiesce_desktop', side_effect=lambda: events.append('quiesce')), \
             mock.patch.object(self.worker, 'stop_optional_guests', side_effect=lambda: events.append('guests')), \
             mock.patch.object(self.worker, 'final_power_action', side_effect=lambda: events.append('handoff')):
            self.worker.execute()
        self.assertEqual(events, ['active', 'accounts', 'ready', 'prepare', 'accounts', 'quiesce', 'guests', 'handoff'])


if __name__ == '__main__':
    unittest.main()
