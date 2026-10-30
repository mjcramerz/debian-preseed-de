"""Local calendar opt-ins and phone delivery. Never consumes Sleek or todo.txt.

No calendar contents or credentials are kept in the delivery ledger. Callers
hold the calendar writer lock for preference changes and delivery reservations.
Reservations are durable before HTTP dispatch: an uncertain send is not retried.
"""
from __future__ import annotations

from contextlib import contextmanager
import calendar as month_calendar
from datetime import date, datetime, time as day_time, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import stat
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from zoneinfo import ZoneInfo

FIRST_MINUTES = (15, 30, 60, 120, 180, 240, 300, 360, 720, 1440)
INTERVAL_MINUTES = (0, 5, 10, 15, 30, 45, 60)
DEFAULT = {'enabled': False, 'first_minutes': 15, 'interval_minutes': 0}
PHONE_CONTROL = 'phone-reminders-control.json'
RECURRENCE_OPTIONS = (
    ('none', 'None', None),
    ('daily', 'Daily', {'FREQ': 'DAILY'}),
    ('weekdays', 'Weekdays', {'FREQ': 'WEEKLY', 'BYDAY': ['MO', 'TU', 'WE', 'TH', 'FR']}),
    ('weekends', 'Weekends', {'FREQ': 'WEEKLY', 'BYDAY': ['SA', 'SU']}),
    ('every-2-days', 'Every 2 days', {'FREQ': 'DAILY', 'INTERVAL': 2}),
    ('every-3-days', 'Every 3 days', {'FREQ': 'DAILY', 'INTERVAL': 3}),
    ('every-4-days', 'Every 4 days', {'FREQ': 'DAILY', 'INTERVAL': 4}),
    ('every-5-days', 'Every 5 days', {'FREQ': 'DAILY', 'INTERVAL': 5}),
    ('weekly', 'Weekly', {'FREQ': 'WEEKLY'}),
    ('every-2-weeks', 'Every 2 weeks', {'FREQ': 'WEEKLY', 'INTERVAL': 2}),
    ('monthly', 'Monthly', {'FREQ': 'MONTHLY'}),
    ('every-2-months', 'Every 2 months', {'FREQ': 'MONTHLY', 'INTERVAL': 2}),
    ('quarterly', 'Quarterly', {'FREQ': 'MONTHLY', 'INTERVAL': 3}),
    ('yearly', 'Yearly', {'FREQ': 'YEARLY'}),
)
RECURRENCE_RULES = {key: rule for key, _, rule in RECURRENCE_OPTIONS}
WEEKDAYS = ('MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU')
MAX_BYTES = 1024 * 1024
MAX_ITEMS = 500
CATCHUP_SECONDS = 120


class ReminderError(Exception):
    def __init__(self, code='reminder-state'):
        self.code = code


def require(ok, code='reminder-state'):
    if not ok:
        raise ReminderError(code)


def preference(value):
    require(isinstance(value, dict) and set(value) == set(DEFAULT), 'invalid-reminder')
    require(type(value['enabled']) is bool
            and type(value['first_minutes']) is int and value['first_minutes'] in FIRST_MINUTES
            and type(value['interval_minutes']) is int and value['interval_minutes'] in INTERVAL_MINUTES,
            'invalid-reminder')
    return dict(value)


def uid_key(uid):
    require(isinstance(uid, str) and 0 < len(uid.encode('utf-8')) <= 4096
            and not any(ord(c) < 32 or ord(c) == 127 for c in uid), 'invalid-reminder')
    return hashlib.sha256(uid.encode('utf-8')).hexdigest()


class Store:
    """Use a pinned private directory and no-follow reads/publication throughout."""
    def __init__(self, home: Path):
        self.directory = home / '.config/calix'
        self.fd = -1

    def __enter__(self):
        # No account state may redirect imports, file authority or parent paths.
        expected_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
        require(self.directory.is_absolute() and self.directory.parent.parent == expected_home
                and self.directory.resolve(strict=True) == self.directory)
        for parent in (self.directory.parent.parent, self.directory.parent, self.directory):
            info = parent.lstat()
            require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                    and not info.st_mode & 0o077)
        self.fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        info = os.fstat(self.fd)
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            os.close(self.fd)
            self.fd = -1
            raise ReminderError()
        return self

    def __exit__(self, *_):
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1

    @staticmethod
    def safe(info):
        return (stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and info.st_nlink == 1 and stat.S_IMODE(info.st_mode) == 0o600)

    @contextmanager
    def locked(self):
        fd = os.open('.fruux-actions.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                     0o600, dir_fd=self.fd)
        try:
            require(self.safe(os.fstat(fd)))
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ReminderError('write-busy') from None
            current = os.stat('.fruux-actions.lock', dir_fd=self.fd, follow_symlinks=False)
            pinned = os.fstat(fd)
            require((current.st_dev, current.st_ino) == (pinned.st_dev, pinned.st_ino))
            yield
        finally:
            os.close(fd)

    def read(self, name):
        require(name in {'phone-reminders.json', 'phone-deliveries.json', PHONE_CONTROL})
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.fd)
        except FileNotFoundError:
            return ({'version': 1, 'paused': False} if name == PHONE_CONTROL
                    else {'version': 1, 'items': {}})
        with os.fdopen(fd, 'rb') as stream:
            before = os.fstat(stream.fileno())
            require(self.safe(before) and before.st_size <= MAX_BYTES)
            raw = stream.read(MAX_BYTES + 1)
            after = os.fstat(stream.fileno())
        require(len(raw) == before.st_size and len(raw) <= MAX_BYTES
                and (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                == (after.st_size, after.st_mtime_ns, after.st_ctime_ns))
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeError):
            raise ReminderError() from None
        if name == PHONE_CONTROL:
            require(isinstance(data, dict) and set(data) == {'version', 'paused'}
                    and type(data['version']) is int and data['version'] == 1
                    and type(data['paused']) is bool)
            return data
        require(isinstance(data, dict) and set(data) == {'version', 'items'}
                and type(data['version']) is int and data['version'] == 1
                and isinstance(data['items'], dict))
        require(len(data['items']) <= (MAX_ITEMS if name == 'phone-reminders.json' else 4096))
        for key, entry in data['items'].items():
            require(isinstance(key, str) and re.fullmatch(r'[a-f0-9]{64}', key) is not None)
            if name == 'phone-reminders.json':
                require(isinstance(entry, dict) and set(entry) == {
                    'uid', 'url', 'kind', 'timezone', 'preference', 'generation', 'enabled_at'})
                require(uid_key(entry['uid']) == key and entry['kind'] in {'VEVENT', 'VTODO'}
                        and isinstance(entry['url'], str) and len(entry['url']) <= 4096
                        and isinstance(entry['timezone'], str) and len(entry['timezone']) <= 128
                        and isinstance(entry['generation'], str)
                        and re.fullmatch(r'[a-f0-9]{32}', entry['generation']) is not None
                        and type(entry['enabled_at']) is int and entry['enabled_at'] >= 0)
                preference(entry['preference'])
                require(entry['preference']['enabled'])
                try:
                    ZoneInfo(entry['timezone'])
                except (ValueError, KeyError):
                    raise ReminderError() from None
            else:
                require(isinstance(entry, dict) and set(entry) == {'expires', 'status', 'retry_at', 'slot', 'key', 'generation'}
                        and type(entry['expires']) is int and entry['expires'] >= 0
                        and type(entry['retry_at']) is int and entry['retry_at'] >= 0
                        and type(entry['slot']) is int and entry['slot'] >= 0
                        and isinstance(entry['key'], str) and re.fullmatch(r'[a-f0-9]{64}', entry['key'])
                        and isinstance(entry['generation'], str) and re.fullmatch(r'[a-f0-9]{32}', entry['generation'])
                        and entry['status'] in {'attempted', 'delivered', 'rejected', 'deferred', 'outcome-unknown'})
        return data

    def publish(self, name, data):
        require(name in {'phone-reminders.json', 'phone-deliveries.json', PHONE_CONTROL})
        if name == PHONE_CONTROL:
            require(isinstance(data, dict) and set(data) == {'version', 'paused'}
                    and data['version'] == 1 and type(data['paused']) is bool,
                    'invalid-reminder-control')
        raw = (json.dumps(data, sort_keys=True, ensure_ascii=True) + '\n').encode()
        require(len(raw) <= MAX_BYTES)
        try:
            current = os.stat(name, dir_fd=self.fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            require(self.safe(current))
        temporary = '.' + name + '.' + uuid.uuid4().hex + '.tmp'
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=self.fd)
        # Retain this exact candidate on publication/durability failure. Never
        # reset a damaged ledger or replay deliveries by inventing an empty one.
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, name, src_dir_fd=self.fd, dst_dir_fd=self.fd)
            os.fsync(self.fd)
        except OSError:
            raise ReminderError('reminder-state-unknown') from None

    def get(self, uid, url, kind):
        entry = self.read('phone-reminders.json')['items'].get(uid_key(uid))
        if entry and entry['url'] == url and entry['kind'] == kind:
            return dict(entry['preference'])
        return dict(DEFAULT)

    def prepare(self, uid, url, kind, zone, settings):
        settings = preference(settings)
        data = self.read('phone-reminders.json')
        key = uid_key(uid)
        if not settings['enabled']:
            # Duplicate remote UIDs in another collection must not revoke the
            # selected collection's opt-in through an unrelated write.
            previous = data['items'].get(key)
            if previous and previous['url'] != url:
                return None
            if previous is None:
                return None
            data['items'].pop(key, None)
        else:
            try:
                ZoneInfo(zone)
            except (ValueError, KeyError, TypeError):
                raise ReminderError('invalid-reminder') from None
            previous = data['items'].get(key)
            require(previous is None or previous['url'] == url, 'reminder-uid-conflict')
            candidate = {'uid': uid, 'url': url, 'kind': kind, 'timezone': zone, 'preference': settings}
            if previous and all(previous[k] == v for k, v in candidate.items()):
                return None
            require(previous is not None or len(data['items']) < MAX_ITEMS, 'reminder-limit')
            data['items'][key] = {**candidate, 'generation': uuid.uuid4().hex, 'enabled_at': int(time.time())}
        require(len((json.dumps(data, sort_keys=True, ensure_ascii=True) + '\n').encode()) <= MAX_BYTES,
                'reminder-limit')
        return data

    def set(self, uid, url, kind, zone, settings):
        data = self.prepare(uid, url, kind, zone, settings)
        if data is not None:
            self.publish('phone-reminders.json', data)

    def set_paused(self, paused: bool) -> None:
        require(type(paused) is bool, 'invalid-reminder-control')
        with self.locked():
            self.publish(PHONE_CONTROL, {'version': 1, 'paused': paused})

    def paused(self) -> bool:
        return bool(self.read(PHONE_CONTROL)['paused'])


def active(component, kind):
    if str(component.get('STATUS', '')).upper() in {'COMPLETED', 'CANCELLED'}:
        return False
    if kind == 'VTODO' and str(component.get('PERCENT-COMPLETE', '0')) == '100':
        return False
    return True


def localized(value, zone):
    require(isinstance(value, date), 'invalid-calendar')
    if not isinstance(value, datetime):
        value = datetime.combine(value, day_time())
    if value.tzinfo is not None:
        require(value.astimezone(timezone.utc).astimezone(value.tzinfo).replace(tzinfo=None)
                == value.replace(tzinfo=None), 'ambiguous-date')
        return value
    # RFC recurrence gaps are omitted; folds use the first local occurrence.
    candidate = value.replace(tzinfo=zone, fold=0)
    require(candidate.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) == value,
            'ambiguous-date')
    return candidate


def component_anchor(component, kind):
    # A task with DTSTART and DUE is anchored to DTSTART. DUE is used only
    # when no start exists, so one task cannot create a second due-date series.
    value = component.get('DTSTART')
    if value is None and kind == 'VTODO':
        value = component.get('DUE')
    require(value is not None, 'reminder-needs-date')
    return value.dt


def schedule_slot(epoch, entry, now):
    first = epoch - entry['preference']['first_minutes'] * 60
    interval = entry['preference']['interval_minutes'] * 60
    if now < first or now > epoch + CATCHUP_SECONDS:
        return None
    slot = first + ((min(now, epoch) - first) // interval) * interval if interval else first
    if slot < entry['enabled_at'] or now - slot > CATCHUP_SECONDS:
        return None
    return epoch, slot


def recurrence_name(component):
    rule = component.get('RRULE')
    if not rule and not any(key in component for key in ('RDATE', 'EXDATE')):
        return 'none'
    if isinstance(rule, dict):
        normalized = {key: [str(value).upper() for value in values] for key, values in rule.items()}
        if normalized.get('INTERVAL') == ['1']:
            normalized.pop('INTERVAL')
        if normalized.get('WKST') == ['MO']:
            normalized.pop('WKST')
        if 'BYDAY' in normalized:
            normalized['BYDAY'] = sorted(normalized['BYDAY'])
        for key, preset in RECURRENCE_RULES.items():
            if preset is None:
                continue
            expected = {name: [str(v).upper() for v in (value if isinstance(value, list) else [value])]
                        for name, value in preset.items()}
            if 'BYDAY' in expected:
                expected['BYDAY'] = sorted(expected['BYDAY'])
            if normalized == expected:
                return key
    return 'custom'


def recurrence_dates(component, zone, now):
    """Jump to a bounded occurrence window; never iterate from an old DTSTART.

    The popup writes the fixed recurrence presets above. Common external
    INTERVAL/UNTIL and RDATE/EXDATE values are supported. More complex rules
    fail closed instead of approximating their occurrences.
    """
    require('DTSTART' in component, 'reminder-needs-date')
    raw_start = component['DTSTART'].dt
    start = localized(raw_start, zone)
    rule = component.get('RRULE')
    candidates = {start}
    if rule:
        require(isinstance(rule, dict) and set(rule) <= {'FREQ', 'INTERVAL', 'UNTIL', 'BYDAY', 'WKST'}
                and all(isinstance(value, list) and 1 <= len(value) <= (7 if key == 'BYDAY' else 1)
                        for key, value in rule.items()),
                'unsupported-reminder-recurrence')
        freq = str(rule.get('FREQ', [''])[0]).upper()
        require(freq in {'DAILY', 'WEEKLY', 'MONTHLY', 'YEARLY'}, 'unsupported-reminder-recurrence')
        interval = int(rule.get('INTERVAL', [1])[0])
        require(1 <= interval <= 366, 'unsupported-reminder-recurrence')
        days = [str(value).upper() for value in rule.get('BYDAY', [])]
        week_start = str(rule.get('WKST', ['MO'])[0]).upper()
        require(week_start in WEEKDAYS and (not days or (freq == 'WEEKLY'
                and len(set(days)) == len(days) and all(value in WEEKDAYS for value in days))),
                'unsupported-reminder-recurrence')
        until = getattr(rule.get('UNTIL', [None])[0], 'dt', rule.get('UNTIL', [None])[0])
        if until is not None:
            until = localized(until, start.tzinfo)
            require(until >= start, 'invalid-calendar')
        # A task's DUE may be later than its DTSTART. Estimate in the same
        # recurrence frame and retain wall-clock distance across DST changes.
        raw_anchor = component_anchor(component, component.name)
        base_anchor = localized(raw_anchor, zone).astimezone(start.tzinfo)
        shift = base_anchor.replace(tzinfo=None) - start.replace(tzinfo=None)
        near = datetime.fromtimestamp(now, start.tzinfo) - shift
        week_origin = start.date() - timedelta(days=(start.weekday() - WEEKDAYS.index(week_start)) % 7)
        if freq in {'DAILY', 'WEEKLY'}:
            step = interval * (7 if freq == 'WEEKLY' else 1)
            approximate = (near.date() - (week_origin if days else start.date())).days // step
        elif freq == 'MONTHLY':
            approximate = ((near.year - start.year) * 12 + near.month - start.month) // interval
        else:
            approximate = (near.year - start.year) // interval

        def occurrence(index):
            if freq in {'DAILY', 'WEEKLY'}:
                return start.replace(tzinfo=None) + timedelta(days=index * step)
            months = index * interval * (12 if freq == 'YEARLY' else 1)
            year, month0 = divmod(start.year * 12 + start.month - 1 + months, 12)
            if not 1 <= year <= 9999 or start.day > month_calendar.monthrange(year, month0 + 1)[1]:
                return None
            return start.replace(year=year, month=month0 + 1, tzinfo=None)

        for index in range(max(0, approximate - 2), max(0, approximate) + 5):
            offsets = [(WEEKDAYS.index(day) - WEEKDAYS.index(week_start)) % 7 for day in days] if days else [None]
            for offset in offsets:
                try:
                    if offset is None:
                        local = occurrence(index)
                    else:
                        local_date = week_origin + timedelta(days=index * interval * 7 + offset)
                        local = datetime.combine(local_date, start.replace(tzinfo=None).time())
                    if local is None:
                        continue
                    value = localized(local, start.tzinfo)
                except (ValueError, OverflowError):
                    continue
                except ReminderError as error:
                    if error.code != 'ambiguous-date':
                        raise
                    continue
                if value >= start and (until is None or value <= until):
                    candidates.add(value)
    for prop in ('RDATE', 'EXDATE'):
        values = component.get(prop, [])
        values = values if isinstance(values, list) else [values]
        require(sum(len(value.dts) for value in values) <= 128, 'response-limit')
        for value in values:
            for entry in value.dts:
                require(isinstance(entry.dt, date), 'unsupported-reminder-recurrence')
                localized_date = localized(entry.dt, start.tzinfo)
                if prop == 'RDATE':
                    candidates.add(localized_date)
                else:
                    candidates.discard(localized_date)
    return start, candidates


def due_slots(calendar, component, kind, entry, now):
    if not active(component, kind):
        return []
    zone = ZoneInfo(entry['timezone'])
    recurring = (any(key in component for key in ('RRULE', 'RDATE', 'EXDATE'))
                 or any(other.name == kind and 'RECURRENCE-ID' in other for other in calendar.subcomponents))
    if not recurring:
        slot = schedule_slot(int(localized(component_anchor(component, kind), zone).timestamp()), entry, now)
        return [slot] if slot else []
    start, dates = recurrence_dates(component, zone, now)
    anchor = localized(component_anchor(component, kind), zone).astimezone(start.tzinfo)
    shift = anchor.replace(tzinfo=None) - start.replace(tzinfo=None)
    exceptions = {}
    for other in calendar.subcomponents:
        if other.name == kind and 'RECURRENCE-ID' in other:
            identity = localized(other['RECURRENCE-ID'].dt, start.tzinfo)
            require(identity not in exceptions and 'RANGE' not in other['RECURRENCE-ID'].params,
                    'unsupported-reminder-recurrence')
            exceptions[identity] = other
    anchors = []
    for value in dates:
        if value in exceptions:
            continue
        try:
            anchors.append(localized(value.replace(tzinfo=None) + shift, start.tzinfo))
        except ReminderError as error:
            if error.code != 'ambiguous-date':
                raise
    for other in exceptions.values():
        if active(other, kind):
            anchors.append(localized(component_anchor(other, kind), zone))
    return sorted({slot for value in anchors
                   if (slot := schedule_slot(int(value.timestamp()), entry, now)) is not None})


def read_policy(path=Path('/etc/labwc/plans.conf')):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_uid == 0
                and before.st_nlink == 1 and not before.st_mode & 0o027 and before.st_size <= 65536,
                'reminder-policy')
        raw = stream.read(65537)
        after = os.fstat(stream.fileno())
    require(len(raw) == before.st_size and len(raw) <= 65536
            and (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            == (after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'reminder-policy')
    result = {}
    for line in raw.decode('utf-8').splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        match = re.fullmatch(r"(LABWC_PLANS_[A-Z_]+)='([^'\r\n]*)'", line)
        require(match is not None and match[1] not in result, 'reminder-policy')
        result[match[1]] = match[2]
    return result


def boolean(policy, name):
    value = policy.get('LABWC_PLANS_' + name, '').lower()
    require(value in {'true', 'false'}, 'reminder-policy')
    return value == 'true'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def destination(policy, channel):
    if not boolean(policy, 'ENABLED') or not boolean(policy, channel.upper() + '_ENABLED'):
        return None
    if channel == 'telegram':
        token = policy.get('LABWC_PLANS_TELEGRAM_API_KEY', '')
        chat = policy.get('LABWC_PLANS_TELEGRAM_CHAT_ID', '')
        require(re.fullmatch(r'[0-9]{5,16}:[A-Za-z0-9_-]{20,128}', token) is not None
                and re.fullmatch(r'-?[0-9]{1,20}', chat) is not None, 'reminder-policy')
        base = policy.get('LABWC_PLANS_TELEGRAM_API_BASE', '')
        suffix = '/bot' + token + '/sendMessage'
        headers = {'Content-Type': 'application/json'}
        extra = {'chat_id': chat, 'disable_web_page_preview': True}
    else:
        require(channel == 'ntfy' and boolean(policy, 'NTFY_READER_ACCESS_CONFIRMED'), 'reminder-policy')
        base = policy.get('LABWC_PLANS_NTFY_BASE_URL', '')
        topic = policy.get('LABWC_PLANS_NTFY_TOPIC', '')
        token = policy.get('LABWC_PLANS_NTFY_ACCESS_TOKEN', '')
        require(re.fullmatch(r'[A-Za-z0-9_-]{1,64}', topic) is not None
                and re.fullmatch(r'[\x21-\x7e]{1,512}', token) is not None, 'reminder-policy')
        suffix = '/' + topic
        headers = {'Content-Type': 'text/plain; charset=utf-8', 'Authorization': 'Bearer ' + token}
        extra = {}
    parsed = urllib.parse.urlsplit(base)
    require(parsed.scheme == 'https' and parsed.hostname and parsed.username is None
            and parsed.password is None and not parsed.query and not parsed.fragment
            and re.fullmatch(r'https://[A-Za-z0-9.-]+(?::[0-9]{1,5})?(?:/[A-Za-z0-9._~/-]+)*', base)
            and (parsed.port is None or 1 <= parsed.port <= 65535), 'reminder-policy')
    return base.rstrip('/') + suffix, headers, extra


def dispatch(target, message, channel, timeout=10):
    url, headers, extra = target
    body = (json.dumps({**extra, 'text': message}, ensure_ascii=True).encode()
            if channel == 'telegram' else message.encode('utf-8'))
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    request = urllib.request.Request(url, data=body, headers=headers, method='POST')
    deadline = time.monotonic() + timeout
    try:
        try:
            response = opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            if response.code == 429:
                # This explicit rejection did not accept the message. It may
                # be retried only while the same current slot remains useful.
                delay = response.headers.get('Retry-After', '')
                return 'deferred', min(120, max(5, int(delay))) if delay.isdecimal() else 30
            if response.code in {400, 401, 403, 404, 405, 410, 413, 415}:
                return 'rejected', 0
            if response.code != 200:
                return 'outcome-unknown', 0
            raw = bytearray()
            while True:
                require(time.monotonic() < deadline, 'deadline')
                block = response.read1(16385 - len(raw))
                require(time.monotonic() < deadline, 'deadline')
                if not block:
                    break
                raw.extend(block)
                require(len(raw) <= 16384, 'invalid-response')
            data = json.loads(raw)
            accepted = (isinstance(data, dict) and (data.get('ok') is True if channel == 'telegram'
                        else data.get('event') == 'message' and isinstance(data.get('id'), str)))
            return ('delivered' if accepted else 'outcome-unknown'), 0
    except Exception:
        # URLs contain credentials. Never stringify transport exceptions or
        # retry a POST that may have reached its destination.
        return 'outcome-unknown', 0


def reserve(store, entry, epoch, slot, channel, now):
    """Called with the shared writer lock, after fresh remote/UID validation."""
    preferences = store.read('phone-reminders.json')['items']
    key = uid_key(entry['uid'])
    current = preferences.get(key)
    if current != entry:
        return None
    identifier = hashlib.sha256(json.dumps([entry['uid'], entry['url'], entry['generation'],
                                           epoch, channel]).encode()).hexdigest()
    data = store.read('phone-deliveries.json')
    data['items'] = {identifier: value for identifier, value in data['items'].items()
                     if value['expires'] >= now and value['key'] in preferences
                     and preferences[value['key']]['generation'] == value['generation']}
    previous = data['items'].get(identifier)
    if previous:
        if previous['slot'] > slot:
            return None
        if previous['slot'] == slot and (previous['status'] != 'deferred' or previous['retry_at'] > now):
            return None
    require(previous is not None or len(data['items']) < 4096, 'reminder-limit')
    # One watermark per occurrence/channel, not one growing record per repeat.
    data['items'][identifier] = {'expires': epoch + 86400, 'status': 'attempted', 'retry_at': 0,
                                 'slot': slot, 'key': key, 'generation': entry['generation']}
    store.publish('phone-deliveries.json', data)
    return identifier


def record_result(store, identifier, status, retry_at):
    data = store.read('phone-deliveries.json')
    require(identifier in data['items'])
    data['items'][identifier].update(status=status, retry_at=retry_at)
    store.publish('phone-deliveries.json', data)
