"""Fruux fixtures: no credentials, real accounts, network or desktop services.

Unexecuted fixture source. AGENTS.override.md prohibits executing these fixtures
on the host or creating a disposable environment. HTTP and Secret Service
boundaries are mocked; these definitions do not authorize their execution.
"""
from __future__ import annotations

from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[3] / 'tools'))
from isolation import require_test_isolation as _require_test_isolation
_isolation_sys.path.pop(0)
_require_test_isolation()

from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import tempfile
from threading import Event as Cancel
import types
import unittest
from unittest import mock

from icalendar import Calendar, Event, Todo

SEED = Path(__file__).resolve().parents[1]
LIBEXEC = SEED / 'hooks/target/usr/local/libexec'


def load(name):
    path = LIBEXEC / name
    module = types.ModuleType('fixture_' + name.replace('-', '_'))
    module.__file__ = str(path)
    helper_path = SEED / 'hooks/target/usr/local/lib/python3.14/dist-packages/labwc_calendar_reminders.py'
    helper = types.ModuleType('labwc_calendar_reminders')
    helper.__file__ = str(helper_path)
    exec(compile(helper_path.read_bytes(), str(helper_path), 'exec'), helper.__dict__)
    with mock.patch.dict(_isolation_sys.modules, {'labwc_calendar_reminders': helper}):
        exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


def resource(kind='VTODO', **properties):
    calendar = Calendar()
    calendar.add('VERSION', '2.0')
    component = Todo() if kind == 'VTODO' else Event()
    component.add('UID', 'fixture-uid')
    component.add('SUMMARY', 'Fixture task')
    component.add('X-FIXTURE-PRESERVE', 'must survive editing')
    for key, value in properties.items():
        component.add(key.replace('_', '-'), value)
    calendar.add_component(component)
    return calendar.to_ical()


class CalendarMutationTests(unittest.TestCase):
    def setUp(self):
        self.w = load('labwc-calendar-worker')
        store_patch = mock.patch.object(self.w, 'reminder_store')
        store = store_patch.start().return_value.__enter__.return_value
        store.get.return_value = dict(self.w.reminders.DEFAULT)
        self.addCleanup(store_patch.stop)
        self.collection = 'https://dav.fruux.com/calendars/fixture/list/'
        self.url = self.collection + 'item.ics'
        self.raw = resource()
        self.client = mock.Mock()
        self.client.request_id = '123456abcdef'
        self.client.request.return_value = (200, {'ETag': '"v1"'}, self.raw)
        self.client.write.return_value = (204, {}, b'')
        patch = mock.patch.object(self.w, 'discovery', return_value=[
            {'url': self.collection, 'name': 'Fixture', 'create': True, 'update': True, 'delete': True}])
        patch.start()
        self.addCleanup(patch.stop)
        self.common = {'kind': 'VTODO', 'calendar': self.collection}
        self.token = {'url': self.url, 'etag': '"v1"', 'uid': 'fixture-uid'}
        self.fields = dict(summary='Updated title', description='Private notes', location='',
                           start='', end='', due='', timezone='Europe/Stockholm')

    def test_create_is_remote_vtodo_and_never_overwrites_an_existing_resource(self):
        self.fields['summary'] = '$(touch not-a-command); <b>plain text</b>'
        result = self.w.execute({**self.common, 'op': 'create', 'fields': self.fields}, self.client)
        self.assertEqual(result['result'], 'created')
        self.assertEqual(result['write_request_id'], self.client.request_id)
        args = self.client.write.call_args.args
        self.assertEqual(args[0], 'PUT')
        self.assertTrue(args[1].startswith(self.collection))
        self.assertEqual(args[2], 'VTODO')
        parsed = Calendar.from_ical(args[3]).walk('VTODO')[0]
        self.assertEqual(str(parsed['SUMMARY']), self.fields['summary'])
        self.assertEqual(str(parsed['STATUS']), 'NEEDS-ACTION')
        self.assertEqual(args[4]['If-None-Match'], '*')

    def test_edit_preserves_unknown_properties_and_conditions_the_remote_write(self):
        result = self.w.execute({**self.common, **self.token, 'op': 'update', 'fields': self.fields}, self.client)
        self.assertEqual(result['result'], 'updated')
        args = self.client.write.call_args.args
        parsed = Calendar.from_ical(args[3]).walk('VTODO')[0]
        self.assertEqual(str(parsed['X-FIXTURE-PRESERVE']), 'must survive editing')
        self.assertEqual(str(parsed['SUMMARY']), 'Updated title')
        self.assertEqual(args[4]['If-Match'], '"v1"')

    def test_replaced_uid_or_etag_aborts_before_mutation(self):
        for raw, tag in [(self.raw, '"v2"'), (self.raw.replace(b'fixture-uid', b'other-uid'), '"v1"')]:
            self.client.request.return_value = (200, {'ETag': tag}, raw)
            with self.subTest(tag=tag), self.assertRaises(self.w.Error) as raised:
                self.w.execute({**self.common, **self.token, 'op': 'delete'}, self.client)
            self.assertEqual(raised.exception.code, 'conflict')
            self.client.write.assert_not_called()

    def test_complete_and_delete_update_the_same_selected_remote_object(self):
        self.w.execute({**self.common, **self.token, 'op': 'complete'}, self.client)
        args = self.client.write.call_args.args
        parsed = Calendar.from_ical(args[3]).walk('VTODO')[0]
        self.assertEqual(str(parsed['STATUS']), 'COMPLETED')
        self.assertEqual(int(parsed['PERCENT-COMPLETE']), 100)
        self.assertIn('COMPLETED', parsed)
        self.assertEqual(args[1], self.url)
        self.assertEqual(args[4]['If-Match'], '"v1"')
        self.client.write.reset_mock()
        self.w.execute({**self.common, **self.token, 'op': 'delete'}, self.client)
        self.client.write.assert_called_once_with('DELETE', self.url, 'VTODO', headers={'If-Match': '"v1"'},
                                                   reminder=mock.ANY)

    def test_scheduling_and_unconfirmed_recurrence_do_not_mutate(self):
        for props, expected in [({'ORGANIZER': 'mailto:fixture@example.invalid'}, 'scheduled-object'),
                                ({'RRULE': {'freq': 'weekly'}}, 'series-confirmation')]:
            self.client.request.return_value = (200, {'etag': '"v1"'}, resource(**props))
            with self.subTest(expected=expected), self.assertRaises(self.w.Error) as raised:
                self.w.execute({**self.common, **self.token, 'op': 'delete'}, self.client)
            self.assertEqual(raised.exception.code, expected)
            self.client.write.assert_not_called()

    def test_collection_substitution_and_path_escape_are_rejected(self):
        for url in ['https://evil.invalid/item.ics', self.collection + '../other/item.ics',
                    self.collection + '%2e%2e/other.ics', self.collection + '%252e%252e/other.ics',
                    self.collection + 'subdirectory/item.ics']:
            with self.subTest(url=url), self.assertRaises(self.w.Error):
                self.w.execute({**self.common, **self.token, 'url': url, 'op': 'delete'}, self.client)
        self.client.write.assert_not_called()

    def test_dst_gap_and_fold_are_rejected_but_an_explicit_offset_is_accepted(self):
        for value in ('2026-03-29 02:30', '2026-10-25 02:30'):
            with self.subTest(value=value), self.assertRaises(self.w.Error) as raised:
                self.w.temporal(value, 'Europe/Stockholm')
            self.assertEqual(raised.exception.code, 'ambiguous-date')
        self.assertEqual(self.w.temporal('2026-10-25 02:30+02:00', 'Europe/Stockholm'),
                         datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc))

    def test_all_day_event_and_bad_end_date(self):
        fields = {**self.fields, 'start': '2026-11-01', 'end': '2026-11-02'}
        self.w.execute({**self.common, 'kind': 'VEVENT', 'op': 'create', 'fields': fields}, self.client)
        component = Calendar.from_ical(self.client.write.call_args.args[3]).walk('VEVENT')[0]
        self.assertEqual(component['DTEND'].dt.isoformat(), '2026-11-02')
        self.client.write.reset_mock()
        fields['end'] = fields['start']
        with self.assertRaises(self.w.Error) as raised:
            self.w.execute({**self.common, 'kind': 'VEVENT', 'op': 'create', 'fields': fields}, self.client)
        self.assertEqual(raised.exception.code, 'invalid-date')
        self.client.write.assert_not_called()

    def test_xml_entities_and_aggregate_node_limit_are_rejected(self):
        for raw in [b'<!DOCTYPE x [<!ENTITY a "expanded">]><x>&a;</x>',
                    b'<multistatus xmlns="DAV:">' + b'<x/>' * 20001 + b'</multistatus>']:
            with self.subTest(size=len(raw)), self.assertRaises(Exception):
                self.w.multistatus(raw, self.collection)

    def test_all_popup_recurrences_round_trip_and_phone_settings_never_enter_ics(self):
        settings = {'enabled': True, 'first_minutes': 60, 'interval_minutes': 15}
        for key, _, rule in self.w.reminders.RECURRENCE_OPTIONS:
            for kind in ('VEVENT', 'VTODO'):
                with self.subTest(recurrence=key, kind=kind):
                    day = '2026-10-31' if key == 'weekends' else '2026-11-02'
                    fields = {**self.fields, 'start': day + ' 09:00', 'recurrence': key}
                    fields['end' if kind == 'VEVENT' else 'due'] = day + ' 10:00'
                    self.w.execute({**self.common, 'kind': kind, 'op': 'create',
                                    'fields': fields, 'reminder': settings}, self.client)
                    body = self.client.write.call_args.args[3]
                    parsed = Calendar.from_ical(body).walk(kind)[0]
                    self.assertEqual(self.w.reminders.recurrence_name(parsed), key)
                    self.assertEqual('RRULE' in parsed, rule is not None)
                    self.assertNotIn(b'VALARM', body)
                    self.assertNotIn(b'first_minutes', body)
                    self.assertNotIn(b'interval_minutes', body)
                    self.assertNotIn(b'Send Reminder to Phone', body)
                    self.assertEqual(self.client.write.call_args.kwargs['reminder']['preference'], settings)

    def test_weekday_weekend_start_mismatch_and_recurring_undated_task_fail_before_put(self):
        for fields, expected in [
            ({**self.fields, 'start': '2026-11-01 09:00', 'due': '2026-11-01 10:00',
              'recurrence': 'weekdays'}, 'recurrence-start-day'),
            ({**self.fields, 'start': '2026-11-02 09:00', 'due': '2026-11-02 10:00',
              'recurrence': 'weekends'}, 'recurrence-start-day'),
            ({**self.fields, 'recurrence': 'daily'}, 'reminder-needs-date')]:
            with self.subTest(fields=fields), self.assertRaises(self.w.Error) as raised:
                self.w.execute({**self.common, 'op': 'create', 'fields': fields}, self.client)
            self.assertEqual(raised.exception.code, expected)
            self.client.write.assert_not_called()


class CalendarRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.w = load('labwc-calendar-worker')
        temp = tempfile.TemporaryDirectory(prefix='fruux-recovery-')
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        self.config = self.home / '.config/calix'
        self.config.mkdir(parents=True, mode=0o700)
        (self.home / '.config').chmod(0o700)
        patch = mock.patch.object(self.w.pwd, 'getpwuid', return_value=types.SimpleNamespace(pw_dir=str(self.home)))
        patch.start()
        self.addCleanup(patch.stop)
        self.client = self.w.Client('fixture-user', 'fixture-password')
        self.url = 'https://dav.fruux.com/calendars/fixture/list/item.ics'
        self.client.request = mock.Mock(return_value=(201, {}, b''))

    def write(self, **kwargs):
        return self.client.write('PUT', self.url, 'VTODO', resource(), {'If-None-Match': '*'}, **kwargs)

    def phone(self):
        return {'uid': 'fixture-uid', 'url': self.url, 'kind': 'VTODO', 'timezone': 'Europe/Stockholm',
                'preference': {'enabled': True, 'first_minutes': 15, 'interval_minutes': 0}}

    def test_acknowledged_write_commits_local_opt_in_without_changing_the_remote_body(self):
        candidate = self.phone()
        self.write(reminder=candidate)
        self.assertEqual(self.client.request.call_args.args[2], resource())
        self.assertEqual(self.w.pending_change()['reminder'], candidate)
        with self.w.reminder_store() as store:
            self.assertEqual(store.get(candidate['uid'], self.url, 'VTODO'), candidate['preference'])

    def test_unknown_remote_outcome_defers_opt_in_until_matching_read_only_review(self):
        candidate = self.phone()
        self.client.request.side_effect = self.w.Error('outcome-unknown')
        with self.assertRaises(self.w.Error):
            self.write(reminder=candidate)
        with self.w.reminder_store() as store:
            self.assertEqual(store.get(candidate['uid'], self.url, 'VTODO'), self.w.reminders.DEFAULT)
        self.client.request.side_effect = None
        self.client.request.return_value = (200, {'etag': '"remote"'}, resource())
        result = self.w.execute({'op': 'review', 'kind': 'VTODO',
                                 'request_id': self.w.pending_change()['request_id']}, self.client)
        self.assertEqual(result['remote'], 'matches')
        with self.w.reminder_store() as store:
            self.assertEqual(store.get(candidate['uid'], self.url, 'VTODO'), candidate['preference'])

    def test_unresolved_delete_suppresses_notifications_before_any_secret_or_network_lookup(self):
        candidate = self.phone()
        self.write(reminder=candidate)
        self.w.remove_intent(self.w.pending_change())
        self.client.request.side_effect = self.w.Error('outcome-unknown')
        off = {**candidate, 'preference': dict(self.w.reminders.DEFAULT)}
        with self.assertRaises(self.w.Error):
            self.client.write('DELETE', self.url, 'VTODO', headers={'If-Match': '"old"'}, reminder=off)
        with mock.patch.object(self.w, 'credentials') as secret:
            self.assertEqual(self.w.reminder_cycle({}, 0), 0)
        secret.assert_not_called()

    def test_local_commit_failure_after_ack_retains_remote_intent_and_never_retries_put(self):
        with mock.patch.object(self.w, 'apply_reminder', side_effect=self.w.reminders.ReminderError('reminder-state-unknown')):
            with self.assertRaises(self.w.Error) as raised:
                self.write(reminder=self.phone())
        self.assertEqual(raised.exception.code, 'outcome-unknown')
        self.assertIsNotNone(self.w.pending_change())
        self.client.request.assert_called_once()

    def test_intent_survives_until_the_controller_receives_and_acknowledges_the_reply(self):
        def reply(*args):
            self.assertEqual(self.w.pending_change()['url'], self.url)
            return (201, {}, b'')
        self.client.request.side_effect = reply
        self.write()
        pending = self.w.pending_change()
        self.assertIsNotNone(pending)
        self.client.request.assert_called_once()
        self.w.execute({'op': 'acknowledge', 'kind': 'VTODO', 'request_id': pending['request_id']}, self.client)
        self.assertIsNone(self.w.pending_change())

    def test_uncertain_write_retains_private_evidence_and_blocks_a_retry(self):
        self.client.request.side_effect = self.w.Error('outcome-unknown')
        with self.assertRaises(self.w.Error):
            self.write()
        pending = self.w.pending_change()
        self.assertEqual(pending['url'], self.url)
        path = self.config / 'fruux-pending.json'
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn('fixture-password', path.read_text())
        with self.assertRaises(self.w.Error) as raised:
            self.write()
        self.assertEqual(raised.exception.code, 'pending-change')
        self.client.request.assert_called_once()

    def test_server_conflict_releases_intent_without_retry(self):
        self.client.request.side_effect = self.w.Error('conflict')
        with self.assertRaises(self.w.Error):
            self.write()
        self.assertIsNone(self.w.pending_change())
        self.client.request.assert_called_once()

    def test_durable_intent_failure_does_not_send_and_retains_evidence(self):
        with mock.patch.object(self.w, 'sync_state_directory', side_effect=OSError('fixture fsync failure')):
            with self.assertRaises(self.w.Error) as raised:
                self.write()
        self.assertEqual(raised.exception.code, 'outcome-unknown')
        self.client.request.assert_not_called()
        self.assertIsNotNone(self.w.pending_change())

    def test_review_is_read_only_and_acknowledgement_is_bound_to_the_record(self):
        self.client.request.side_effect = self.w.Error('outcome-unknown')
        with self.assertRaises(self.w.Error):
            self.write()
        pending = self.w.pending_change()
        self.client.request.side_effect = None
        self.client.request.return_value = (200, {'ETag': '"remote"'}, resource())
        review = self.w.execute({'op': 'review', 'kind': 'VTODO', 'request_id': pending['request_id']}, self.client)
        self.assertIn(review['remote'], {'matches', 'present'})
        self.assertIsNotNone(self.w.pending_change())
        with self.assertRaises(self.w.Error):
            self.w.execute({'op': 'acknowledge', 'kind': 'VTODO', 'request_id': '000000000000'}, self.client)
        self.w.execute({'op': 'acknowledge', 'kind': 'VTODO', 'request_id': pending['request_id']}, self.client)
        self.assertIsNone(self.w.pending_change())
        self.assertEqual(self.client.request.call_args.args[0], 'GET')

    def test_concurrent_writer_uses_the_same_lock_as_acknowledgement(self):
        lock = self.w.writer_lock()
        try:
            with self.assertRaises(self.w.Error) as raised:
                self.write()
            self.assertEqual(raised.exception.code, 'write-busy')
            self.client.request.assert_not_called()
        finally:
            os.close(lock)


class ControllerWorkerTests(unittest.TestCase):
    def test_a_stalled_mutation_is_killed_and_reported_unknown(self):
        controller = load('labwc-calendar-actions')
        with tempfile.TemporaryDirectory(prefix='calendar-worker-') as directory:
            path = Path(directory) / 'worker'
            path.write_text('#!/usr/bin/python3 -IB\nimport time\ntime.sleep(120)\n')
            path.chmod(0o700)
            cancel = Cancel()
            cancel.set()
            with mock.patch.object(controller, 'WORKER', str(path)):
                with self.assertRaises(controller.Error) as raised:
                    controller.worker({'op': 'create'}, {'PATH': '/usr/bin:/bin', 'HOME': directory}, cancel)
            self.assertEqual(raised.exception.code, 'outcome-unknown')

    def test_read_cancellation_remains_distinct_from_a_failed_or_uncertain_write(self):
        controller = load('labwc-calendar-actions')
        with tempfile.TemporaryDirectory(prefix='calendar-worker-') as directory:
            path = Path(directory) / 'worker'
            path.write_text('#!/usr/bin/python3 -IB\nimport time\ntime.sleep(120)\n')
            path.chmod(0o700)
            cancel = Cancel()
            cancel.set()
            with mock.patch.object(controller, 'WORKER', str(path)):
                with self.assertRaises(controller.Error) as raised:
                    controller.worker({'op': 'list'}, {'PATH': '/usr/bin:/bin', 'HOME': directory}, cancel)
            self.assertEqual(raised.exception.code, 'cancelled')


if __name__ == '__main__':
    unittest.main()
