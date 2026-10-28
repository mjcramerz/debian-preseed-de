#!/usr/bin/env python3
"""Unexecuted phone-reminder fixtures; repository execution prohibitions apply.

All defined I/O is scoped to explicit private fixture paths. No host helpers,
services, package state, credentials, network connections or desktop are used.
The isolation guard remains mandatory and does not authorize execution.
"""
from __future__ import annotations

from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[3] / 'tools'))
_isolation_sys.path.insert(0, '/workspace/repository/tools')
from isolation import require_test_isolation as _require_test_isolation
_isolation_sys.path.pop(0)
_require_test_isolation()

from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

from icalendar import Calendar, Event, Todo

SOURCE = Path(__file__).resolve().parents[1] / 'hooks/target/usr/local/lib/python3.14/dist-packages/labwc_calendar_reminders.py'
FAKE_TOKEN = '12345:' + 'x' * 24


def load():
    module = types.ModuleType('fixture_calendar_reminders')
    exec(compile(SOURCE.read_bytes(), str(SOURCE), 'exec'), module.__dict__)
    return module


class NotificationPolicyTests(unittest.TestCase):
    def setUp(self):
        self.r = load()
        private = tempfile.TemporaryDirectory(prefix='notification-policy-')
        self.addCleanup(private.cleanup)
        self.root = Path(private.name)
        self.policy = self.root / 'plans.conf'
        self.values = {
            'LABWC_PLANS_ENABLED': 'true', 'LABWC_PLANS_TELEGRAM_ENABLED': 'true',
            'LABWC_PLANS_TELEGRAM_API_BASE': 'https://api.telegram.org',
            'LABWC_PLANS_TELEGRAM_API_KEY': FAKE_TOKEN, 'LABWC_PLANS_TELEGRAM_CHAT_ID': '12345',
            'LABWC_PLANS_NTFY_ENABLED': 'false', 'LABWC_PLANS_NTFY_BASE_URL': 'https://ntfy.sh',
            'LABWC_PLANS_NTFY_TOPIC': '', 'LABWC_PLANS_NTFY_ACCESS_TOKEN': '',
            'LABWC_PLANS_NTFY_READER_ACCESS_CONFIRMED': 'false',
        }
        self.write_policy()

    def write_policy(self, **overrides):
        self.values.update(overrides)
        self.policy.write_text(''.join(key + "='" + value + "'\n" for key, value in self.values.items()))
        self.policy.chmod(0o600)

    def read(self):
        original = self.r.os.fstat
        def metadata(fd):
            info = original(fd)
            return types.SimpleNamespace(st_mode=info.st_mode, st_uid=0, st_nlink=info.st_nlink,
                st_size=info.st_size, st_mtime_ns=info.st_mtime_ns, st_ctime_ns=info.st_ctime_ns)
        with mock.patch.object(self.r.os, 'fstat', side_effect=metadata):
            return self.r.read_policy(self.policy)

    def test_ntfy_defaults_off_and_live_disable_overrides_old_environment(self):
        self.assertIsNone(self.r.destination(self.read(), 'ntfy'))
        self.write_policy(LABWC_PLANS_TELEGRAM_ENABLED='false')
        self.assertIsNone(self.r.destination(self.read(), 'telegram'))

    def test_destinations_require_https_no_redirects_and_ntfy_reader_authentication(self):
        for base in ('http://example.invalid', 'https://user:secret@example.invalid',
                     'https://example.invalid/?token=private', 'https://example.invalid/#fragment'):
            self.write_policy(LABWC_PLANS_TELEGRAM_API_BASE=base)
            with self.subTest(base=base), self.assertRaises(self.r.ReminderError):
                self.r.destination(self.read(), 'telegram')
        self.write_policy(LABWC_PLANS_NTFY_ENABLED='true', LABWC_PLANS_NTFY_TOPIC='fixture',
                          LABWC_PLANS_NTFY_ACCESS_TOKEN='fixture-token')
        with self.assertRaises(self.r.ReminderError):
            self.r.destination(self.read(), 'ntfy')

    def test_unsafe_mode_symlink_hardlink_and_duplicate_keys_fail_closed(self):
        self.policy.chmod(0o660)
        with self.assertRaises(self.r.ReminderError):
            self.read()
        self.policy.chmod(0o600)
        alias = self.root / 'alias'
        alias.symlink_to(self.policy.name)
        original = self.policy
        self.policy = alias
        with self.assertRaises(OSError):
            self.read()
        self.policy = original
        os.link(self.policy, self.root / 'hardlink')
        with self.assertRaises(self.r.ReminderError):
            self.read()
        (self.root / 'hardlink').unlink()
        with self.policy.open('a') as stream:
            stream.write("LABWC_PLANS_ENABLED='true'\n")
        with self.assertRaises(self.r.ReminderError):
            self.read()

    def test_uncertain_post_is_not_reported_successful_or_retried(self):
        opener = mock.Mock()
        opener.open.side_effect = TimeoutError('fixture')
        with mock.patch.object(self.r.urllib.request, 'build_opener', return_value=opener):
            status, delay = self.r.dispatch(self.r.destination(self.read(), 'telegram'), 'fixture', 'telegram')
        self.assertEqual((status, delay), ('outcome-unknown', 0))
        opener.open.assert_called_once()


class ReminderStateTests(unittest.TestCase):
    def setUp(self):
        self.r = load()
        private = tempfile.TemporaryDirectory(prefix='calendar-reminder-state-')
        self.addCleanup(private.cleanup)
        self.home = Path(private.name)
        (self.home / '.config').mkdir(mode=0o700)
        self.directory = self.home / '.config/calix'
        self.directory.mkdir(mode=0o700)
        self.uid = 'fixture-uid'
        self.url = 'https://dav.fruux.com/calendars/fixture/item.ics'
        self.settings = {'enabled': True, 'first_minutes': 60, 'interval_minutes': 15}

    def opt_in(self, store):
        store.set(self.uid, self.url, 'VEVENT', 'Europe/Stockholm', self.settings)
        return store.read('phone-reminders.json')['items'][self.r.uid_key(self.uid)]

    def test_preferences_are_private_uid_bound_and_off_does_not_replay_old_state(self):
        with self.r.Store(self.home) as store, store.locked():
            self.assertEqual(store.get(self.uid, self.url, 'VEVENT'), self.r.DEFAULT)
            entry = self.opt_in(store)
            self.assertEqual((self.directory / 'phone-reminders.json').stat().st_mode & 0o777, 0o600)
            now = entry['enabled_at']
            identifier = self.r.reserve(store, entry, now + 3600, now, 'telegram', now)
            self.assertIsNotNone(identifier)
            self.assertIsNone(self.r.reserve(store, entry, now + 3600, now, 'telegram', now))
            store.set(self.uid, self.url, 'VEVENT', 'Europe/Stockholm', self.r.DEFAULT)
            self.assertIsNone(self.r.reserve(store, entry, now + 3600, now, 'telegram', now))

    def test_writer_cleanup_lock_and_replaced_opt_in_are_rechecked(self):
        with self.r.Store(self.home) as store, store.locked():
            entry = self.opt_in(store)
            with self.r.Store(self.home) as other, self.assertRaises(self.r.ReminderError) as raised:
                with other.locked():
                    self.fail('competing writer acquired the same lock')
            self.assertEqual(raised.exception.code, 'write-busy')
            self.settings['interval_minutes'] = 30
            self.opt_in(store)
            self.assertIsNone(self.r.reserve(store, entry, 2000000000, 1999996400, 'telegram', 1999996400))

    def test_failed_candidate_sync_retains_evidence_and_exact_previous_bytes(self):
        with self.r.Store(self.home) as store, store.locked():
            self.opt_in(store)
            path = self.directory / 'phone-reminders.json'
            before = path.read_bytes()
            self.settings['interval_minutes'] = 30
            with mock.patch.object(self.r.os, 'fsync', side_effect=OSError('fixture fsync failure')):
                with self.assertRaises(self.r.ReminderError) as raised:
                    self.opt_in(store)
            self.assertEqual(raised.exception.code, 'reminder-state-unknown')
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(len(list(self.directory.glob('.phone-reminders.json.*.tmp'))), 1)

    def test_corrupt_or_replaced_ledger_is_preserved_and_never_reset(self):
        with self.r.Store(self.home) as store, store.locked():
            path = self.directory / 'phone-deliveries.json'
            path.write_bytes(b'{not valid JSON')
            path.chmod(0o600)
            with self.assertRaises(self.r.ReminderError):
                store.read(path.name)
            self.assertEqual(path.read_bytes(), b'{not valid JSON')
            path.unlink()
            path.symlink_to('phone-reminders.json')
            with self.assertRaises(OSError):
                store.read(path.name)


class RecurringReminderTests(unittest.TestCase):
    def setUp(self):
        self.r = load()
        self.zone = ZoneInfo('Europe/Stockholm')
        self.entry = {'timezone': 'Europe/Stockholm', 'enabled_at': 0,
                      'preference': {'enabled': True, 'first_minutes': 15, 'interval_minutes': 0}}

    def schedule(self, preset, start, target, kind='VEVENT'):
        calendar = Calendar()
        component = Event() if kind == 'VEVENT' else Todo()
        component.add('UID', 'fixture')
        component.add('DTSTART', start)
        if kind == 'VTODO':
            component.add('DUE', start + timedelta(hours=1))
            target += timedelta(hours=1)
        component.add('RRULE', self.r.RECURRENCE_RULES[preset])
        calendar.add_component(component)
        epoch = int(target.timestamp())
        now = epoch - 900
        return self.r.due_slots(calendar, component, kind, self.entry, now), (epoch, now)

    def test_every_popup_preset_uses_its_actual_interval_for_events_and_tasks(self):
        first = datetime(2026, 11, 2, 9, tzinfo=self.zone)
        cases = [('daily', first + timedelta(days=1)), ('weekdays', first + timedelta(days=4)),
                 ('every-2-days', first + timedelta(days=2)), ('every-3-days', first + timedelta(days=3)),
                 ('every-4-days', first + timedelta(days=4)), ('every-5-days', first + timedelta(days=5)),
                 ('weekly', first + timedelta(days=7)), ('every-2-weeks', first + timedelta(days=14)),
                 ('monthly', first.replace(month=12)), ('every-2-months', first.replace(year=2027, month=1)),
                 ('quarterly', first.replace(year=2027, month=2)), ('yearly', first.replace(year=2027))]
        for preset, target in cases:
            for kind in ('VEVENT', 'VTODO'):
                with self.subTest(preset=preset, kind=kind):
                    slots, expected = self.schedule(preset, first, target, kind)
                    self.assertIn(expected, slots)
        saturday = datetime(2026, 10, 31, 9, tzinfo=self.zone)
        slots, expected = self.schedule('weekends', saturday, saturday + timedelta(days=1))
        self.assertIn(expected, slots)

    def test_weekday_weekend_filters_and_missing_month_days_do_not_invent_occurrences(self):
        monday = datetime(2026, 11, 2, 9, tzinfo=self.zone)
        self.assertEqual(self.schedule('weekdays', monday, monday + timedelta(days=5))[0], [])
        saturday = datetime(2026, 10, 31, 9, tzinfo=self.zone)
        self.assertEqual(self.schedule('weekends', saturday, saturday + timedelta(days=2))[0], [])
        january = datetime(2027, 1, 31, 9, tzinfo=self.zone)
        self.assertEqual(self.schedule('monthly', january, january.replace(month=2, day=28))[0], [])
        slots, expected = self.schedule('monthly', january, january.replace(month=3))
        self.assertIn(expected, slots)

    def test_daily_local_time_survives_dst_and_the_current_final_interval_can_be_late(self):
        before = datetime(2026, 10, 24, 9, tzinfo=self.zone)
        after = datetime(2026, 10, 25, 9, tzinfo=self.zone)
        slots, expected = self.schedule('daily', before, after)
        self.assertIn(expected, slots)
        self.assertEqual(int((after.timestamp() - before.timestamp()) / 3600), 25)
        self.entry['preference'] = {'enabled': True, 'first_minutes': 60, 'interval_minutes': 15}
        epoch = int(after.timestamp())
        self.assertEqual(self.r.schedule_slot(epoch, self.entry, epoch + 30), (epoch, epoch))
        self.assertIsNone(self.r.schedule_slot(epoch, self.entry, epoch + 121))


if __name__ == '__main__':
    unittest.main()
