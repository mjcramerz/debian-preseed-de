"""Greeter power integration regressions: never contact host PID 1 or logind.

Shell fixtures change only absolute executable paths to isolated test adapters.
Worker tests execute production flow with every host transport intercepted.
"""
from __future__ import annotations
import ast
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
TARGET = ROOT / 'd-i/forky/hooks/target'
WORKER = TARGET / 'usr/local/libexec/labwc-admin-action-worker'


def module():
    result = types.ModuleType('greeter_power_followup')
    exec(compile(WORKER.read_text(), str(WORKER), 'exec'), result.__dict__)
    return result


def session(**overrides):
    values = dict(User='109', Name='greeter', Class='greeter', Active='yes',
                  Remote='no', Service='greetd-greeter', Leader='321')
    values.update(overrides)
    return '\n'.join(f'{key}={value}' for key, value in values.items()) + '\n'


class GreeterIdentityTests(unittest.TestCase):
    def setUp(self):
        self.power = module()
        self.worker = self.power.Worker(109, 'greeter', 'reboot', greeter=True)
        self.listing = 'c1 109 greeter seat0 321 greeter tty1 no -\n'
        self.properties = session()
        self.transport = mock.patch.object(self.power, 'run', side_effect=self.run_command)
        self.run = self.transport.start()
        self.addCleanup(self.transport.stop)

    def run_command(self, argv, **kwargs):
        self.assertEqual(argv[0], '/usr/bin/loginctl')
        if 'list-sessions' in argv:
            return self.listing
        if '--property=Class' in argv:
            return 'user\n'
        self.assertIn('show-session', argv)
        return self.properties

    def test_active_local_managed_greeter_is_retained_across_checks(self):
        self.worker.protect_other_sessions()
        self.worker.protect_other_sessions()
        self.assertEqual(self.worker.greeter_identity, ('c1', '321'))
        self.assertEqual(self.run.call_count, 4)
        self.assertTrue(all(c.kwargs.get('max_output') for c in self.run.call_args_list))

    def test_no_greeter_session_fails_closed(self):
        self.listing = ''
        with self.assertRaises(self.power.Error):
            self.worker.protect_other_sessions()

    def test_remote_inactive_wrong_account_class_and_service_are_rejected(self):
        for changes in (dict(Remote='yes'), dict(Active='no'), dict(User='1000'),
                        dict(Name='desktop'), dict(Class='user'), dict(Service='sshd'),
                        dict(Leader='0'), dict(Leader='-1'), dict(Leader='1;id')):
            with self.subTest(changes=changes):
                self.properties = session(**changes)
                with self.assertRaises(self.power.Error):
                    self.worker.protect_other_sessions()

    def test_missing_duplicate_unknown_or_malformed_properties_fail_closed(self):
        for value in ('', session().replace('Remote=no\n', ''),
                      session() + 'Active=yes\n', session() + 'garbage\n',
                      session() + 'Unknown=1\n'):
            with self.subTest(value=value):
                self.properties = value
                with self.assertRaises(self.power.Error):
                    self.worker.protect_other_sessions()

    def test_replaced_session_does_not_inherit_an_old_authorization(self):
        self.worker.protect_other_sessions()
        self.listing = self.listing.replace('c1 ', 'c2 ')
        with self.assertRaisesRegex(self.power.Error, 'greeter session changed'):
            self.worker.protect_other_sessions()

    def test_replaced_leader_does_not_inherit_an_old_authorization(self):
        self.worker.protect_other_sessions()
        self.properties = session(Leader='322')
        with self.assertRaisesRegex(self.power.Error, 'greeter session changed'):
            self.worker.protect_other_sessions()

    def test_ambiguous_greeter_sessions_fail_closed(self):
        self.listing += self.listing.replace('c1 ', 'c2 ')
        with self.assertRaises(self.power.Error):
            self.worker.protect_other_sessions()

    def test_manager_session_does_not_invalidate_the_actual_greeter(self):
        self.listing += '2 109 greeter - 400 manager - no -\n'
        original = self.run_command
        def transport(argv, **kwargs):
            if 'show-session' in argv and '2' in argv:
                return session(Class='manager', Active='no', Service='systemd-user', Leader='400')
            return original(argv, **kwargs)
        self.run.side_effect = transport
        self.worker.protect_other_sessions()
        self.assertEqual(self.worker.greeter_identity, ('c1', '321'))

    def test_other_interactive_user_vetoes_greeter_power(self):
        self.listing += 'c2 1000 desktop seat0 900 user tty2 no -\n'
        with self.assertRaisesRegex(self.power.Error, 'another interactive'):
            self.worker.protect_other_sessions()

    def test_greeter_authorization_is_not_a_desktop_save_dialog_bypass(self):
        self.worker = self.power.Worker(1000, 'desktop', 'reboot', greeter=True)
        self.listing = 'c2 1000 desktop seat0 900 user tty2 no -\n'
        self.properties = session(User='1000', Name='desktop', Class='user', Service='greetd')
        with self.assertRaises(self.power.Error):
            self.worker.protect_other_sessions()

    def test_lost_logind_transport_is_not_success(self):
        self.run.side_effect = self.power.Error('bus unavailable')
        with self.assertRaisesRegex(self.power.Error, 'bus unavailable'):
            self.worker.protect_other_sessions()


class GreeterFlowTests(unittest.TestCase):
    def setUp(self):
        self.power = module()
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        (self.root / 'cgroup.controllers').write_text('cpu memory io\n')
        group = self.root / 'user.slice/user-109.slice/user@109.service'
        group.mkdir(parents=True)
        self.events = group / 'cgroup.events'
        self.events.write_text('populated 1\nfrozen 0\n')
        self.stack.enter_context(mock.patch.object(self.power, 'CGROUP_ROOT', self.root))
        self.calls = []
        self.stopped = False
        self.fail_on = None
        self.greeter_properties = session()
        self.inhibitors = []
        self.transport = self.stack.enter_context(mock.patch.object(self.power, 'run', side_effect=self.run_command))
        self.reservation = self.stack.enter_context(mock.patch.object(self.power, 'PackageLocks'))
        self.stack.enter_context(mock.patch.object(self.power, 'ready'))
        self.hold = self.stack.enter_context(mock.patch.object(self.power, 'hold_reservation'))

    def run_command(self, argv, **kwargs):
        self.calls.append(argv)
        if self.fail_on and self.fail_on(argv):
            raise self.power.Error('injected transport failure')
        if argv[0] == '/usr/bin/loginctl':
            if 'list-sessions' in argv:
                return 'c1 109 greeter seat0 321 greeter tty1 no -\n'
            return self.greeter_properties
        if argv[0] == '/usr/bin/busctl':
            return json.dumps(dict(type='a(ssssuu)', data=[self.inhibitors]))
        self.assertEqual(argv[0], '/usr/bin/systemctl')
        if '--property=LoadState,ActiveState' in argv:
            return 'LoadState=not-found\nActiveState=inactive\n'
        if '--property=' + self.power.RUNTIME_PROPERTIES in argv:
            return ('Id=user@109.service\nLoadState=loaded\nActiveState=' +
                    ('inactive' if self.stopped else 'active') + '\nJob=0\nMainPID=' +
                    ('0' if self.stopped else '400') + '\nControlPID=0\nControlGroup=' +
                    self.power.runtime_cgroup('user@109.service') + '\n')
        if 'stop' in argv and 'user@109.service' in argv:
            self.stopped = True
            self.events.write_text('populated 0\nfrozen 0\n')
            return ''
        if argv[-2:] == ['stop', 'greetd.service']:
            self.assertIn('--no-block', argv)
            return ''
        if '--force' in argv:
            self.assertTrue(self.stopped)
            self.assertEqual(argv.count('--force'), 1)
            self.assertIn(argv[-1], ('reboot', 'poweroff'))
            self.assertGreater(self.reservation.return_value.__enter__.return_value.verify.call_count, 0)
            return ''
        self.fail(f'unexpected host transport: {argv}')

    def execute(self, action='reboot'):
        worker = self.power.Worker(109, 'greeter', action, greeter=True)
        with mock.patch.object(worker, 'user_run', side_effect=AssertionError('greeter must not run desktop helpers')):
            worker.execute()
        return worker

    def test_both_greeter_actions_reach_exactly_one_verified_force_handoff(self):
        for action in ('reboot', 'poweroff'):
            with self.subTest(action=action):
                self.calls.clear(); self.stopped = False
                self.events.write_text('populated 1\nfrozen 0\n')
                worker = self.execute(action)
                final = ['/usr/bin/systemctl', '--force', '--no-ask-password', action]
                self.assertEqual(self.calls[-1], final)
                self.assertEqual(sum('--force' in call for call in self.calls), 1)
                self.assertTrue(worker.committed and worker.handoff_attempted)
                self.assertGreaterEqual(sum('show-session' in call for call in self.calls), 3)
                self.assertFalse(any('--user' in call or 'kill' in call for call in self.calls))
                self.assertFalse(any('dbus.service' in call or 'dbus-broker.service' in call for call in self.calls))

    def test_block_inhibitor_never_reaches_guest_or_runtime_stop(self):
        self.inhibitors = [['shutdown', 'editor', 'unsaved', 'block', 1000, 900]]
        with self.assertRaisesRegex(self.power.Error, 'inhibited'):
            self.execute()
        self.assertFalse(any('--force' in c or 'stop' in c for c in self.calls))

    def test_identity_change_after_package_wait_never_stops_a_session(self):
        self.reservation.return_value.__enter__.side_effect = lambda: self.change_identity()
        with self.assertRaisesRegex(self.power.Error, 'greeter session changed'):
            self.execute()
        self.assertFalse(any('--force' in c or 'stop' in c for c in self.calls))

    def change_identity(self):
        self.greeter_properties = session(Leader='999')
        return mock.Mock()

    def test_runtime_stop_failure_never_escalates_force(self):
        self.fail_on = lambda argv: 'stop' in argv and 'user@109.service' in argv
        with self.assertRaises(self.power.Error):
            self.execute()
        self.assertFalse(any('--force' in c for c in self.calls))
        self.hold.assert_not_called()

    def test_uncertain_handoff_is_not_retried(self):
        self.fail_on = lambda argv: '--force' in argv
        with self.assertRaisesRegex(self.power.Error, 'do not retry automatically'):
            self.execute()
        self.assertEqual(sum('--force' in c for c in self.calls), 1)
        self.hold.assert_not_called()


class ShellDispatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.record = self.directory / 'calls.jsonl'
        adapter = '''#!/usr/bin/python3 -I
import json,os,pathlib,sys
name=pathlib.Path(sys.argv[0]).name
if name=='systemctl':
 with open(os.environ['TEST_CALLS'],'a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')
elif name=='id': print('0')
elif name=='getent': print('greeter:x:'+os.environ['PKEXEC_UID']+':109::/:/usr/sbin/nologin')
elif name=='pkexec':
 assert sys.argv[1]=='--disable-internal-agent'
 os.execve(sys.argv[2],sys.argv[2:],dict(os.environ))
else: raise AssertionError(name)
'''
        mapping = {}
        for name in ('pkexec', 'systemctl', 'id', 'getent'):
            path = self.directory / name
            path.write_text(adapter); path.chmod(0o755)
            mapping['/usr/bin/' + name] = str(path)
        sources = ['usr/local/libexec/labwc-admin-action-root',
                   'usr/local/libexec/greetd-power-action-root',
                   'usr/local/sbin/greetd-power-action']
        for relative in sources:
            mapping['/' + relative] = str(self.directory / Path(relative).name)
        for relative in sources:
            source = (TARGET / relative).read_text()
            for old, new in sorted(mapping.items(), key=lambda pair: -len(pair[0])):
                source = source.replace(old, new)
            path = Path(mapping['/' + relative])
            path.write_text(source); path.chmod(0o755)
        self.entry = self.directory / 'greetd-power-action'
        self.env = dict(os.environ, PKEXEC_UID='109', TEST_CALLS=str(self.record))

    def invoke(self, args):
        return subprocess.run([str(self.entry), *args], env=self.env,
                              capture_output=True, text=True, timeout=5)

    def test_reboot_poweroff_and_shutdown_alias_reach_waited_greeter_instance(self):
        for action, normalized in (('reboot', 'reboot'), ('poweroff', 'poweroff'), ('shutdown', 'poweroff')):
            with self.subTest(action=action):
                result = self.invoke([action])
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(self.record.read_text().splitlines()[-1]),
                                 ['--wait', 'start', f'labwc-admin-action@109-greeter-{normalized}.service'])

    def test_unsupported_or_injected_actions_never_contact_systemctl(self):
        for args in ([], ['reboot', '--force'], ['--force'], ['suspend'], ['logout'],
                     ['reboot;id'], ['../../reboot'], ['poweroff\nreboot']):
            with self.subTest(args=args):
                self.assertNotEqual(self.invoke(args).returncode, 0)
        self.assertFalse(self.record.exists())

    def test_invalid_pkexec_identity_never_reaches_systemctl(self):
        for uid in ('', '0', '0109', '109;id', '-1'):
            with self.subTest(uid=uid):
                self.env['PKEXEC_UID'] = uid
                self.assertNotEqual(self.invoke(['reboot']).returncode, 0)
        self.assertFalse(self.record.exists())


class WiringTests(unittest.TestCase):
    def test_worker_can_reach_user_bus_without_opening_home_directories(self):
        unit = (TARGET / 'etc/systemd/system/labwc-admin-action@.service').read_text()
        self.assertIn('ProtectHome=read-only\n', unit)
        self.assertIn('InaccessiblePaths=/home /root\n', unit)
        for retained in ('NoNewPrivileges=yes', 'PrivatePIDs=no', 'PrivateUsers=no',
                         'ProtectSystem=strict', 'RestrictAddressFamilies=AF_UNIX',
                         'KillMode=control-group', 'AppArmorProfile=managed-labwc-admin-action-worker'):
            self.assertIn(retained, unit)
        self.assertNotIn('BindPaths=/home', unit)

    def test_greeter_failures_reach_the_service_journal(self):
        client = (TARGET / 'usr/local/libexec/labwc-greeter-client').read_text()
        self.assertIn('/usr/local/bin/labwc-greeter-power >/dev/null &', client)
        tree = ast.parse((TARGET / 'usr/local/bin/labwc-greeter-power').read_text())
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute) and n.func.attr == 'Popen']
        self.assertEqual(len(calls), 1)
        stderr = next((kw.value for kw in calls[0].keywords if kw.arg == 'stderr'), None)
        self.assertTrue(stderr is None or isinstance(stderr, ast.Constant) and stderr.value is None)

    def test_firstboot_checks_the_actual_greeter_handoff_contract(self):
        source = (ROOT / 'd-i/forky/scripts/firstboot/04-validation.sh').read_text()
        for expected in ('desktop-greeter-power-handoff', 'ProtectHome=read-only',
                         'InaccessiblePaths=/home /root', 'greeter_identity',
                         '--force", "--no-ask-password", self.action'):
            self.assertIn(expected, source)

    @unittest.skipUnless(shutil.which('node'), 'node is required to exercise polkit JavaScript')
    def test_polkit_grants_only_fixed_helper_to_active_local_greeter(self):
        rule = (TARGET / 'etc/polkit-1/rules.d/10-greetd-power.rules.tmpl').read_text()
        rule = rule.replace('__INSTALLER_LABWC_GREETER_USER__', 'greeter')
        script = '''let callback;
const polkit={Result:{YES:'yes',NO:'no',NOT_HANDLED:'other'},addRule:r=>callback=r};
''' + rule + '''
const subject={user:'greeter',active:true,local:true};
const helper='/usr/local/libexec/greetd-power-action-root';
function check(id,program,s,want){
 const got=callback({id:id,lookup:key=>key==='program'?program:null},s);
 if(got!==want) throw Error(JSON.stringify({id,program,s,got,want}));
}
check('org.freedesktop.policykit.exec',helper,subject,'yes');
for(const change of [{active:false},{local:false}])
 check('org.freedesktop.policykit.exec',helper,{...subject,...change},'no');
check('org.freedesktop.policykit.exec',helper,{...subject,user:'desktop'},'other');
check('org.freedesktop.policykit.exec','/usr/bin/systemctl',subject,'other');
check('org.freedesktop.policykit.exec',helper+'-evil',subject,'other');
for(const id of ['power-off','reboot','power-off-ignore-inhibit','reboot-multiple-sessions'])
 check('org.freedesktop.login1.'+id,null,subject,'no');
'''
        result = subprocess.run([shutil.which('node'), '-'], input=script,
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
