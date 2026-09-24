"""Power finalization regressions: all host commands are mocked, never executed."""
from __future__ import annotations
from payload_fixture import read_text as payload_read_text
import contextlib
import io
import json
from pathlib import Path
import tempfile
import time
import sys
import types
import unittest
from unittest import mock

TARGET = Path(__file__).resolve().parents[1] / 'hooks/target'
WORKER = TARGET / 'usr/local/libexec/labwc-admin-action-worker'


def module():
    result = types.ModuleType('runtime_power_test')
    exec(compile(payload_read_text(WORKER), str(WORKER), 'exec'), result.__dict__)
    return result


def snapshot(power, *, stopped=False, users=('1000', '109'), clear=False):
    result = {}
    for name in (*power.RUNTIME_FIXED_UNITS, *(f'user@{uid}.service' for uid in users)):
        result[name] = dict(Id=name, LoadState='loaded', ActiveState='inactive' if stopped else 'active',
                            Job='0', MainPID='0' if stopped or name.endswith('.socket') else '123',
                            ControlPID='0', ControlGroup='' if clear else power.runtime_cgroup(name))
    return result


def text_snapshot(data):
    return '\n\n'.join('\n'.join(f'{key}={value}' for key, value in props.items())
                       for props in data.values()) + '\n'


class InhibitorsTests(unittest.TestCase):
    def setUp(self):
        self.power = module()

    def check(self, records):
        raw = json.dumps({'type': 'a(ssssuu)', 'data': [records]})
        with mock.patch.object(self.power, 'run', return_value=raw) as run:
            self.power.check_shutdown_inhibitors()
        command = run.call_args.args[0]
        self.assertEqual(command[0], '/usr/bin/busctl')
        self.assertEqual(command[-1], 'ListInhibitors')
        self.assertIn('--timeout=5s', command)

    def test_empty_list_permits_shutdown(self):
        self.check([])

    def test_block_and_weak_and_unknown_shutdown_modes_veto(self):
        for mode in ('block', 'block-weak', 'future-mode', ''):
            with self.subTest(mode=mode), self.assertRaisesRegex(self.power.Error, 'inhibited'):
                self.check([['shutdown:sleep', 'application', 'unsaved', mode, 1000, 123]])

    def test_delay_is_not_misrepresented_as_blocking(self):
        self.check([['shutdown', 'application', 'flush', 'delay', 1000, 123]])
        self.assertIn('not logind', self.power.check_shutdown_inhibitors.__doc__)

    def test_unrelated_inhibitors_are_not_shutdown_vetoes(self):
        self.check([['sleep:idle', 'player', 'playing', 'block', 1000, 123]])

    def test_invalid_json_signatures_and_record_types_fail_closed(self):
        invalid = ['{', 'null', '[]', '{"type":"s","data":[[]]}',
                   '{"type":"a(ssssuu)","data":[]}',
                   '{"type":"a(ssssuu)","data":[{}]}']
        records = [['shutdown', 'a', 'b', 'block', True, 1],
                   ['shutdown', 'a', 'b', 'delay', -1, 1],
                   ['shutdown', 'a', 'b', 'delay', 1, 2**32],
                   ['shutdown', 'a', 'b', 'delay', 1],
                   ['shutdown', ['a'], 'b', 'delay', 1, 1]]
        invalid += [json.dumps({'type': 'a(ssssuu)', 'data': [[record]]}) for record in records]
        for raw in invalid:
            with self.subTest(raw=raw), mock.patch.object(self.power, 'run', return_value=raw), \
                 self.assertRaisesRegex(self.power.Error, 'cannot verify'):
                self.power.check_shutdown_inhibitors()

    def test_bounded_response_records_and_strings(self):
        invalid = [' ' * 1_048_577,
                   json.dumps({'type':'a(ssssuu)', 'data':[[[]]*1025]}),
                   json.dumps({'type':'a(ssssuu)', 'data':[[['sleep', 'a'*4097, '', 'delay', 0, 1]]]})]
        for raw in invalid:
            with mock.patch.object(self.power, 'run', return_value=raw), self.assertRaises(self.power.Error):
                self.power.check_shutdown_inhibitors()

    def test_unavailable_bus_never_silently_authorizes(self):
        with mock.patch.object(self.power, 'run', side_effect=self.power.Error('timeout')), \
             self.assertRaisesRegex(self.power.Error, 'timeout'):
            self.power.check_shutdown_inhibitors()


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.power = module()

    def parse(self, data):
        raw = text_snapshot(data) if isinstance(data, dict) else data
        with mock.patch.object(self.power, 'run', return_value=raw) as run:
            value = self.power.runtime_snapshot()
        self.assertEqual(run.call_args.args[0][-1], 'user@*.service')
        self.assertIn('--', run.call_args.args[0])
        return value

    def test_fixed_and_loaded_user_units_parse(self):
        data = snapshot(self.power)
        self.assertEqual(self.parse(data), data)

    def test_greeter_can_be_not_installed(self):
        data = snapshot(self.power)
        data['greetd.service'] = dict(Id='greetd.service', LoadState='not-found', ActiveState='inactive', Job='0')
        with self.assertRaises(self.power.Error):
            self.parse(data)

    def test_idle_services_can_clear_cgroups(self):
        self.parse(snapshot(self.power, stopped=True, clear=True))

    def test_unsafe_names_and_noncanonical_user_ids_are_rejected(self):
        for name in ('user@01.service', 'user@-1.service', 'user@4294967295.service', 'user@99999999999.service',
                     'user@1000.service;id', 'user-1000.slice', '../user@1000.service', 'sshd.service', 'dbus.service'):
            with self.subTest(name=name), self.assertRaises(self.power.Error):
                self.power.runtime_cgroup(name)
        self.assertEqual(self.power.runtime_cgroup('user@0.service'), '/user.slice/user-0.slice/user@0.service')

    def test_unexpected_unit_or_cgroup_placement_is_rejected(self):
        for key, value in (('Id', 'sshd.service'), ('ControlGroup', '/system.slice/sshd.service'),
                           ('ControlGroup', '/user.slice/user-1000.slice/user@1000.service/..')):
            data = snapshot(self.power); data['user@1000.service'][key] = value
            with self.subTest(key=key,value=value), self.assertRaises(self.power.Error):
                self.parse(data)

    def test_collected_user_manager_and_empty_snapshot_are_valid(self):
        data=snapshot(self.power,stopped=True)
        data['user@1000.service']['LoadState']='not-found'
        self.assertEqual(self.parse(data), data)
        self.assertEqual(self.parse(''), {})
        # A failed transport must not be confused with a successful empty glob.
        with mock.patch.object(self.power, 'run', side_effect=self.power.Error('bus denied')):
            with self.assertRaises(self.power.Error): self.power.runtime_snapshot()

    def test_duplicate_units_properties_unknown_states_and_partial_properties_fail(self):
        data=snapshot(self.power); raw=text_snapshot(data)
        bad=[raw+'\n'+text_snapshot({'a':data['user@1000.service']}), raw.replace('Job=0','Job=0\nJob=0',1),
             raw.replace('Job=0','Job=0\nInjected=yes',1), raw.replace('Job=0','Job=x',1),
             raw.replace('MainPID=123\n','',1), raw.replace('ActiveState=active','ActiveState=unknown',1)]
        for text in bad:
            with self.subTest(text=text[:90]), self.assertRaises(self.power.Error): self.parse(text)

    def test_empty_oversized_or_excessive_snapshots_fail(self):
        for text in ('x'*131073, text_snapshot(snapshot(self.power, users=tuple(map(str,range(129)))))):
            with self.assertRaises(self.power.Error): self.parse(text)


class CgroupTests(unittest.TestCase):
    def setUp(self):
        self.power=module();tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.power.CGROUP_ROOT=self.root
        self.group=self.power.runtime_cgroup('user@1000.service')
        self.path=self.root/self.group.lstrip('/')/'cgroup.events';self.path.parent.mkdir(parents=True)

    def test_recursive_population_is_authoritative(self):
        for value in (0,1):
            self.path.write_text(f'populated {value}\nfrozen 0\n')
            self.assertEqual(self.power.cgroup_populated(self.group),bool(value))

    def test_removed_cgroup_and_empty_socket_path_are_empty(self):
        self.assertFalse(self.power.cgroup_populated(self.group))
        self.assertFalse(self.power.cgroup_populated(''))

    def test_symlink_is_never_followed(self):
        other=self.root/'other';other.write_text('populated 0\n');self.path.symlink_to(other)
        with self.assertRaises(OSError): self.power.cgroup_populated(self.group)

    def test_malformed_or_oversized_kernel_data_fails(self):
        for text in ('','frozen 0\n','populated 2\n','populated 0\npopulated 1\n','x'*4097):
            self.path.write_text(text)
            with self.subTest(text=text[:30]), self.assertRaises(self.power.Error):
                self.power.cgroup_populated(self.group)

    def test_arbitrary_or_relative_cgroup_paths_fail(self):
        for path in ('/system.slice/sshd.service', '../user@1000.service', '/user.slice/../user@1000.service',
                     '/user.slice/user-1001.slice/user@1000.service'):
            with self.subTest(path=path), self.assertRaises(self.power.Error): self.power.cgroup_populated(path)


class RuntimeFlowTests(unittest.TestCase):
    def setUp(self):
        self.power=module();self.stack=contextlib.ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
        self.worker=self.power.Worker(1000,'desktop','poweroff');self.worker.quiesced=True
        self.worker.package_locks=mock.Mock()
        self.calls=[];self.stopped=False;self.kill_error=False;self.stop_error=False;self.keep_populated=False
        self.before=snapshot(self.power);self.after=snapshot(self.power,stopped=True,clear=True)
        self.stack.enter_context(mock.patch.object(self.power,'run',side_effect=self.transport))
        self.stack.enter_context(mock.patch.object(self.worker,'protect_other_sessions',side_effect=lambda:self.calls.append(['accounts'])))
        hierarchy=self.stack.enter_context(mock.patch.object(self.power,'CGROUP_ROOT'))
        (hierarchy/'cgroup.controllers').is_file.return_value=True
        self.population=self.stack.enter_context(mock.patch.object(self.power,'cgroup_populated',side_effect=self.populated))
        # Fast deterministic deadline; no real sleeps and no live power endpoints.
        self.clock=0.0
        self.stack.enter_context(mock.patch.object(self.power.time,'monotonic',side_effect=lambda:self.clock))
        self.stack.enter_context(mock.patch.object(self.power.time,'sleep',side_effect=self.advance))

    def advance(self,seconds): self.clock+=max(seconds,0.1)

    def populated(self,group): return self.keep_populated or not self.stopped

    def transport(self,argv,**kwargs):
        self.calls.append(argv)
        if argv[0]=='/usr/bin/busctl': return json.dumps({'type':'a(ssssuu)','data':[[]]})
        if 'show' in argv: return text_snapshot(self.after if self.stopped else self.before)
        if 'stop' in argv:
            if self.stop_error: raise self.power.Error('stop failed')
            if '--no-block' not in argv: self.stopped=True
            return ''
        if 'kill' in argv:
            self.stopped=True
            if self.kill_error: raise self.power.Error('kill raced stop')
            return ''
        if argv == ['/usr/bin/systemctl', '--no-ask-password', 'start', 'power-log-capture.service']: return ''
        if '--force' in argv: return ''
        raise AssertionError('unexpected host command: '+repr(argv))

    def test_desktop_and_greeter_both_actions_have_ordered_single_force(self):
        for action in ('poweroff','reboot'):
            for greeter in (False,True):
                self.calls.clear();self.stopped=False
                self.worker.action=action;self.worker.greeter=greeter;self.worker.quiesced=not greeter
                self.worker.runtime_teardown_started=self.worker.handoff_attempted=False
                self.worker.final_power_action()
                stop=next(i for i,c in enumerate(self.calls) if 'stop' in c)
                managers=next(i for i,c in enumerate(self.calls) if 'stop' in c and '--no-block' not in c)
                final=next(i for i,c in enumerate(self.calls) if '--force' in c)
                self.assertFalse(any('power-log-capture.service' in c for c in self.calls))
                self.assertLess(stop,managers);self.assertLess(managers,final)
                self.assertIn('--no-block',self.calls[stop]);self.assertIn('greetd.service',self.calls[stop])
                self.assertNotIn('--no-block',self.calls[managers])
                for name in self.before: self.assertIn(name,self.calls[managers])
                self.assertFalse(any('kill' in c for c in self.calls))
                self.assertFalse(any('dbus-broker.service' in c or 'dbus.socket' in c for c in self.calls))
                self.assertEqual(self.calls[final],['/usr/bin/systemctl','--force','--no-ask-password',action])
                self.assertEqual(sum(c.count('--force') for c in self.calls),1)
                self.assertTrue(all(c[0]=='/usr/bin/systemctl' and '--user' not in c for c in self.calls[stop:]))
                self.assertTrue(self.worker.package_locks.verify.called)

    def test_saved_user_cgroup_is_checked_when_unit_unloads(self):
        del self.after['user@1000.service']
        self.worker.final_power_action()
        self.assertGreaterEqual(sum(c.args[0].endswith('user@1000.service') for c in self.population.call_args_list),2)

    def test_nothing_is_started_after_user_managers_stop(self):
        self.worker.final_power_action()
        last_stop=max(i for i,c in enumerate(self.calls) if 'stop' in c)
        self.assertIn('user@1000.service',self.calls[last_stop])
        capture = ['/usr/bin/systemctl', '--no-ask-password', 'start', 'power-log-capture.service']
        self.assertEqual(self.calls[last_stop+1:].count(capture), 0)
        self.assertTrue(all('show' in c or '--force' in c for c in self.calls[last_stop+1:]))
        self.assertTrue(self.worker.handoff_attempted)

    def test_reservation_is_rechecked_after_native_output_before_force(self):
        import builtins
        original_print = builtins.print
        def lose_reservation(*args, **kwargs):
            result = original_print(*args, **kwargs)
            if args and str(args[0]).startswith('power handoff:'):
                self.worker.package_locks.verify.side_effect = self.power.Error('reservation lost')
            return result
        with mock.patch('builtins.print', side_effect=lose_reservation):
            with self.assertRaisesRegex(self.power.Error, 'reservation lost'):
                self.worker.final_power_action()
        self.assertFalse(any('--force' in c for c in self.calls))
        self.assertFalse(any('power-log-capture.service' in c for c in self.calls))
        self.assertTrue(self.worker.handoff_attempted)
        count = len(self.calls)
        with self.assertRaisesRegex(self.power.Error, 'only once'):
            self.worker.final_power_action()
        self.assertEqual(len(self.calls), count)

    def test_surviving_sd_pam_cgroup_blocks_force_even_when_mainpid_is_zero(self):
        self.keep_populated=True;self.kill_error=True
        with self.assertRaisesRegex(self.power.Error,'did not finish'): self.worker.final_power_action()
        self.assertFalse(any('--force' in c for c in self.calls));self.assertLessEqual(self.clock,10.2)
        with self.assertRaisesRegex(self.power.Error,'only once'): self.worker.final_power_action()

    def test_busy_stop_job_blocks_force(self):
        self.after['user@1000.service']['Job']='123'
        with self.assertRaises(self.power.Error): self.worker.final_power_action()
        self.assertFalse(any('--force' in c for c in self.calls))

    def test_live_controlpid_blocks_force(self):
        self.after['user@1000.service']['ControlPID']='456'
        with self.assertRaises(self.power.Error): self.worker.final_power_action()
        self.assertFalse(any('--force' in c for c in self.calls))

    def test_new_user_manager_during_teardown_blocks_force(self):
        self.after=snapshot(self.power,stopped=True,users=('1000','109','1001'))
        with self.assertRaisesRegex(self.power.Error,'new user manager'): self.worker.final_power_action()
        self.assertFalse(any('--force' in c for c in self.calls))

    def test_stop_submission_failure_cannot_reach_kill_or_force(self):
        self.stop_error=True
        with self.assertRaisesRegex(self.power.Error,'stop failed'): self.worker.final_power_action()
        self.assertFalse(any('kill' in c or '--force' in c for c in self.calls))
        with self.assertRaisesRegex(self.power.Error,'only once'): self.worker.final_power_action()

    def test_malformed_post_stop_snapshot_cannot_authorize_force(self):
        self.after['user@1000.service']['MainPID']='unknown'
        with self.assertRaises(self.power.Error): self.worker.final_power_action()
        self.assertFalse(any('--force' in c for c in self.calls))

    def test_unreadable_cgroup_preflight_never_commits(self):
        self.population.side_effect=PermissionError('denied')
        with self.assertRaises(PermissionError): self.worker.final_power_action()
        self.assertFalse(self.worker.runtime_teardown_started)
        self.assertFalse(any('stop' in c or '--force' in c for c in self.calls))

    def test_inhibitor_recheck_failure_keeps_brokers_alive(self):
        with mock.patch.object(self.power,'check_shutdown_inhibitors',side_effect=self.power.Error('inhibited')):
            with self.assertRaisesRegex(self.power.Error,'inhibited'): self.worker.final_power_action()
        self.assertFalse(any('stop' in c or '--force' in c for c in self.calls))

    def test_other_account_recheck_failure_keeps_brokers_alive(self):
        self.worker.protect_other_sessions.side_effect=self.power.Error('other account')
        with self.assertRaises(self.power.Error): self.worker.final_power_action()
        self.assertFalse(self.calls)

    def test_missing_cgroup_v2_fails_before_destructive_commands(self):
        (self.power.CGROUP_ROOT/'cgroup.controllers').is_file.return_value=False
        with self.assertRaisesRegex(self.power.Error,'cgroup-v2'): self.worker.final_power_action()
        self.assertFalse(any('stop' in c or '--force' in c for c in self.calls))

    def test_missing_reservation_or_unprepared_session_fails_without_commands(self):
        self.worker.package_locks=None
        with self.assertRaisesRegex(self.power.Error,'reservation'): self.worker.final_power_action()
        self.worker.package_locks=mock.Mock();self.worker.quiesced=False
        with self.assertRaisesRegex(self.power.Error,'quiesced'): self.worker.final_power_action()
        self.assertFalse(self.calls)

    def test_non_power_actions_cannot_tear_down_runtime(self):
        for action in ('logout','suspend','poweroff;id'):
            self.worker.action=action
            with self.assertRaises(self.power.Error): self.worker.stop_shutdown_runtime()
        self.assertFalse(self.calls)

    def test_final_submission_loss_is_never_automatically_retried(self):
        transport=self.transport
        def failed(argv,**kwargs):
            if '--force' in argv:
                self.calls.append(argv);raise self.power.Error('lost reply')
            return transport(argv,**kwargs)
        with mock.patch.object(self.power,'run',side_effect=failed):
            with self.assertRaisesRegex(self.power.Error,'uncertain'): self.worker.final_power_action()
            with self.assertRaisesRegex(self.power.Error,'only once'): self.worker.final_power_action()
        self.assertEqual(sum('--force' in c for c in self.calls),1)


class BoundedTransportTests(unittest.TestCase):
    """Only private Python child processes; no systemd or host services."""
    def setUp(self): self.power=module()

    def test_both_pipes_are_drained_and_success_is_decoded(self):
        output=self.power.run([sys.executable,'-c',
            'import sys;sys.stderr.write("diagnostic");print("answer")'],max_output=100,timeout=3)
        self.assertEqual(output,'answer\n')

    def test_stdout_overflow_reaps_its_child(self):
        with self.assertRaisesRegex(self.power.Error,'size limit'):
            self.power.run([sys.executable,'-c',
                'import sys,time;sys.stdout.write("x"*100000);sys.stdout.flush();time.sleep(30)'],
                max_output=1024,timeout=3)

    def test_stderr_overflow_is_also_bounded(self):
        with self.assertRaisesRegex(self.power.Error,'size limit'):
            self.power.run([sys.executable,'-c',
                'import sys,time;sys.stderr.write("x"*100000);sys.stderr.flush();time.sleep(30)'],
                max_output=1024,timeout=3)

    def test_inherited_pipe_child_is_bounded_by_deadline(self):
        start=time.monotonic()
        with self.assertRaisesRegex(self.power.Error,'timed out'):
            self.power.run([sys.executable,'-c','import os,time;os.fork();time.sleep(30)'],
                           max_output=1024,timeout=0.2)
        self.assertLess(time.monotonic()-start,4)

    def test_nonzero_result_remains_an_error(self):
        with self.assertRaisesRegex(self.power.Error,'exited 3'):
            self.power.run([sys.executable,'-c','raise SystemExit(3)'],max_output=1024,timeout=3)


class HardeningTests(unittest.TestCase):
    def test_broker_free_transport_and_no_privilege_expansion(self):
        power=module()
        self.assertEqual(power.ENV['SYSTEMCTL_FORCE_BUS'],'0')
        self.assertFalse(any(key.startswith('DBUS_') for key in power.ENV))
        unit=payload_read_text(TARGET/'etc/systemd/system/labwc-admin-action@.service')
        self.assertIn('\nCapabilityBoundingSet=CAP_SETUID CAP_SETGID CAP_KILL\n',unit)
        self.assertIn('\nAmbientCapabilities=\n',unit)
        self.assertIn('NoNewPrivileges=yes',unit)
        self.assertIn('ProtectControlGroups=yes',unit)
        source=payload_read_text(WORKER)
        self.assertNotIn('/usr/bin/pkill',source);self.assertNotIn('/usr/bin/pgrep',source)
        profile=payload_read_text(TARGET/'etc/apparmor.d/desktop-wrappers').split('profile labwc-admin-action-worker ',1)[1].split('\n}',1)[0]
        self.assertIn('capability kill,',profile)
        self.assertNotIn('capability sys_admin',profile)
        self.assertIn('set=(kill chld) peer=labwc-admin-action-worker',profile)
        self.assertIn('/sys/fs/cgroup/cgroup.controllers r,',profile)
        self.assertIn('cgroup.events r,',profile)
        self.assertNotIn('cgroup.kill',profile)


if __name__=='__main__': unittest.main()
