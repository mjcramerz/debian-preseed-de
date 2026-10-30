"""Durable local reminders linked to optional Fruux calendar reminders."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import stat
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

STATE_NAME = 'local-reminders.json'
DELIVERY_NAME = 'local-reminder-deliveries.json'
LOCK_NAME = '.fruux-actions.lock'
MAX_BYTES = 2 * 1024 * 1024
MAX_ITEMS = 500
RECURRENCES = ('none', 'daily', 'weekdays', 'weekends', 'every-2-days', 'every-3-days',
               'every-4-days', 'every-5-days', 'weekly', 'every-2-weeks',
               'monthly', 'every-2-months', 'quarterly', 'yearly')
URGENCIES = ('low', 'normal', 'critical')
FIRST_MINUTES = (0, 5, 10, 15, 30, 60, 120, 180, 240, 300, 360, 720, 1440)


class ReminderError(Exception):
    pass


class OutcomeUnknown(ReminderError):
    def __init__(self, message: str, recovery_path: Path):
        super().__init__(message + '; review ' + str(recovery_path))
        self.recovery_path = recovery_path


def _require(condition: bool, message: str = 'invalid local reminder state') -> None:
    if not condition:
        raise ReminderError(message)


def _home() -> Path:
    uid = os.getuid()
    _require(uid != 0 and os.geteuid() == uid, 'local reminders require the desktop account')
    home = Path(pwd.getpwuid(uid).pw_dir)
    _require(home.is_absolute() and '..' not in home.parts, 'unsafe desktop home')
    return home


def _text(value: object, maximum: int, name: str) -> str:
    _require(isinstance(value, str) and 0 < len(value.encode('utf-8')) <= maximum,
             'invalid ' + name)
    _require(not any(ord(char) < 32 or ord(char) == 127 for char in value),
             'invalid ' + name)
    return value


def _due(value: object, zone: str) -> str:
    _text(zone, 128, 'timezone')
    try:
        ZoneInfo(zone)
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError, KeyError):
        raise ReminderError('invalid reminder date or timezone') from None
    _require(parsed.tzinfo is not None, 'reminder date needs an offset')
    return parsed.isoformat(timespec='minutes')


def localize(value: datetime, zone: str) -> datetime:
    """Interpret naive input as civil time, rejecting a nonexistent local time."""
    try:
        named_zone = ZoneInfo(zone)
    except (ValueError, KeyError, TypeError):
        raise ReminderError('invalid reminder timezone') from None
    if value.tzinfo is not None:
        return value
    candidate = value.replace(tzinfo=named_zone, fold=0)
    _require(candidate.astimezone(timezone.utc).astimezone(named_zone).replace(tzinfo=None) == value,
             'reminder time does not exist in the selected timezone')
    return candidate


def _validate_link(value: object) -> dict | None:
    if value is None:
        return None
    _require(isinstance(value, dict) and set(value) == {'uid', 'url', 'kind'})
    _text(value['uid'], 4096, 'calendar UID')
    _text(value['url'], 4096, 'calendar URL')
    _require(value['kind'] in {'VEVENT', 'VTODO'}, 'invalid calendar kind')
    return dict(value)


def _validate_item(item: object) -> dict:
    _require(isinstance(item, dict))
    required = {'id', 'title', 'body', 'due', 'timezone', 'first_minutes', 'recurrence',
                'sound', 'urgency', 'allow_dnd', 'enabled', 'link', 'created', 'updated'}
    _require(set(item) == required)
    _require(isinstance(item['id'], str) and re.fullmatch(r'[a-f0-9]{32}', item['id']))
    _text(item['title'], 512, 'reminder title')
    _require(isinstance(item['body'], str) and len(item['body'].encode('utf-8')) <= 8192
             and not any(ord(char) < 32 and char not in '\n\t' for char in item['body']))
    _due(item['due'], item['timezone'])
    _require(type(item['first_minutes']) is int and item['first_minutes'] in FIRST_MINUTES)
    _require(item['recurrence'] in RECURRENCES and type(item['sound']) is bool
             and item['urgency'] in URGENCIES and type(item['allow_dnd']) is bool
             and type(item['enabled']) is bool)
    _validate_link(item['link'])
    _require(type(item['created']) is int and item['created'] >= 0
             and type(item['updated']) is int and item['updated'] >= item['created'])
    return dict(item)


def _validate_state(value: object) -> dict:
    _require(isinstance(value, dict) and set(value) == {'version', 'items'}
             and type(value['version']) is int and value['version'] == 1
             and isinstance(value['items'], dict))
    _require(len(value['items']) <= MAX_ITEMS)
    items = {}
    for key, item in value['items'].items():
        _require(isinstance(key, str) and re.fullmatch(r'[a-f0-9]{32}', key))
        parsed = _validate_item(item)
        _require(parsed['id'] == key)
        items[key] = parsed
    return {'version': 1, 'items': items}


def _fingerprint(item: dict) -> str:
    return hashlib.sha256(json.dumps(item, sort_keys=True, ensure_ascii=True).encode('utf-8')).hexdigest()


def _validate_deliveries(value: object) -> dict:
    _require(isinstance(value, dict) and set(value) == {'version', 'items'}
             and type(value['version']) is int and value['version'] == 1
             and isinstance(value['items'], dict)
             and len(value['items']) <= 4096, 'invalid local delivery ledger')
    items = {}
    for key, record in value['items'].items():
        _require(isinstance(record, dict) and set(record) == {'item', 'status'}
                 and isinstance(record['status'], str)
                 and record['status'] in {'reserved', 'accepted', 'not-sent', 'outcome-unknown'},
                 'invalid local delivery receipt')
        item = _validate_item(record['item'])
        _require(key == _fingerprint(item), 'invalid local delivery identity')
        items[key] = {'item': item, 'status': record['status']}
    return {'version': 1, 'items': items}


class Store:
    """Private, same-UID state with one shared calendar writer lock."""
    def __init__(self, home: Path | None = None):
        self.home = _home() if home is None else home
        self.directory = self.home / '.config/calix'

    def _check_directory(self) -> None:
        for parent in (self.directory.parent.parent, self.directory.parent, self.directory):
            info = parent.lstat()
            _require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                     and not info.st_mode & 0o077, 'unsafe reminder state directory')

    @contextmanager
    def locked(self, directory_fd: int | None = None):
        owns_directory_fd = directory_fd is None
        if owns_directory_fd:
            self._check_directory()
            directory_fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        else:
            info = os.fstat(directory_fd)
            _require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                     and not info.st_mode & 0o077, 'unsafe reminder state directory')
        try:
            fd = os.open(LOCK_NAME, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                         0o600, dir_fd=directory_fd)
        except BaseException:
            if owns_directory_fd:
                os.close(directory_fd)
            raise
        try:
            info = os.fstat(fd)
            _require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                     and info.st_nlink == 1 and stat.S_IMODE(info.st_mode) == 0o600,
                     'unsafe calendar writer lock')
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ReminderError('calendar reminder state is busy') from None
            current = os.stat(LOCK_NAME, dir_fd=directory_fd, follow_symlinks=False)
            pinned = os.fstat(fd)
            _require((current.st_dev, current.st_ino) == (pinned.st_dev, pinned.st_ino),
                     'calendar writer lock changed during acquisition')
            yield
        finally:
            os.close(fd)
            if owns_directory_fd:
                os.close(directory_fd)

    def _read_unlocked(self, directory_fd: int, name: str = STATE_NAME) -> dict:
        _require(name in {STATE_NAME, DELIVERY_NAME})
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                         dir_fd=directory_fd)
        except FileNotFoundError:
            return {'version': 1, 'items': {}}
        try:
            before = os.fstat(fd)
            _require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid()
                     and before.st_nlink == 1 and stat.S_IMODE(before.st_mode) == 0o600
                     and before.st_size <= MAX_BYTES, 'unsafe local reminder state')
            chunks = []
            total = 0
            while total <= MAX_BYTES:
                chunk = os.read(fd, min(65536, MAX_BYTES + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
            raw = b''.join(chunks)
            after = os.fstat(fd)
            _require(len(raw) == before.st_size and len(raw) <= MAX_BYTES
                     and (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                     == (after.st_size, after.st_mtime_ns, after.st_ctime_ns),
                     'local reminder state changed during read')
        finally:
            os.close(fd)
        try:
            validator = _validate_state if name == STATE_NAME else _validate_deliveries
            return validator(json.loads(raw))
        except (ValueError, UnicodeError):
            raise ReminderError('local reminder state is damaged') from None

    def _publish_unlocked(self, directory_fd: int, value: dict, name: str = STATE_NAME) -> None:
        _require(name in {STATE_NAME, DELIVERY_NAME})
        value = (_validate_state if name == STATE_NAME else _validate_deliveries)(value)
        raw = (json.dumps(value, sort_keys=True, ensure_ascii=True) + '\n').encode('utf-8')
        _require(len(raw) <= MAX_BYTES, 'local reminder state is too large')
        temporary = '.' + name + '.' + secrets.token_hex(12) + '.tmp'
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600, dir_fd=directory_fd)
        retain = False
        renamed = False
        try:
            with os.fdopen(fd, 'wb', closefd=False) as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(fd)
            os.replace(temporary, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
            renamed = True
            os.fsync(directory_fd)
        except OSError as error:
            retain = True
            recovery = self.directory / (name if renamed else temporary)
            raise OutcomeUnknown('local reminder publication is uncertain', recovery) from error
        finally:
            os.close(fd)
            if not retain:
                try:
                    os.unlink(temporary, dir_fd=directory_fd)
                except FileNotFoundError:
                    pass

    @contextmanager
    def _session(self):
        self._check_directory()
        directory_fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            _require(os.fstat(directory_fd).st_uid == os.getuid(), 'unsafe reminder directory')
            with self.locked(directory_fd):
                named = self.directory.lstat()
                pinned = os.fstat(directory_fd)
                _require((named.st_dev, named.st_ino) == (pinned.st_dev, pinned.st_ino),
                         'reminder directory changed during lock acquisition')
                with os.scandir(directory_fd) as entries:
                    for count, entry in enumerate(entries, 1):
                        _require(count <= 4096, 'reminder directory entry limit reached')
                        if re.fullmatch(r'\.local-(?:reminders|reminder-deliveries)\.json\.[a-f0-9]{24}\.tmp',
                                        entry.name):
                            raise OutcomeUnknown('unresolved reminder publication candidate',
                                                 self.directory / entry.name)
                yield directory_fd
        finally:
            os.close(directory_fd)

    def list(self) -> list[dict]:
        with self._session() as fd:
            return sorted(self._read_unlocked(fd)['items'].values(),
                          key=lambda item: datetime.fromisoformat(item['due']).astimezone(timezone.utc))

    @staticmethod
    def _due_at_or_before(item: dict, now: datetime) -> bool:
        try:
            due = datetime.fromisoformat(item['due'])
        except (TypeError, ValueError):
            raise ReminderError('local reminder date is invalid') from None
        return due <= now

    def filtered(self, view: str) -> list[dict]:
        if view not in {'all', 'upcoming', 'overdue'}:
            raise ReminderError('unsupported reminder view')
        items = self.list()
        if view == 'all':
            return items
        now = datetime.now().astimezone()
        if view == 'overdue':
            return [item for item in items if item['enabled'] and self._due_at_or_before(item, now)]
        return [item for item in items if item['enabled'] and not self._due_at_or_before(item, now)]

    def clear_paused(self) -> int:
        """Remove only reminders still paused while holding the writer lock."""
        with self._session() as fd:
            state = self._read_unlocked(fd)
            remaining = {key: item for key, item in state['items'].items() if item['enabled']}
            removed = len(state['items']) - len(remaining)
            if removed:
                state['items'] = remaining
                self._publish_unlocked(fd, state)
            return removed

    def clear_expired(self) -> int:
        with self._session() as fd:
            state = self._read_unlocked(fd)
            now = datetime.now().astimezone()
            remaining = {key: item for key, item in state['items'].items()
                         if not self._due_at_or_before(item, now)}
            removed = len(state['items']) - len(remaining)
            if removed:
                state['items'] = remaining
                self._publish_unlocked(fd, state)
            return removed

    def mutate(self, operation: str, item: dict | None = None, item_id: str | None = None) -> dict | None:
        with self._session() as fd:
            state = self._read_unlocked(fd)
            if operation == 'create':
                _require(item is not None)
                now = int(time.time())
                item = {**item, 'id': secrets.token_hex(16), 'created': now, 'updated': now}
                item = _validate_item(item)
                _require(len(state['items']) < MAX_ITEMS, 'local reminder limit reached')
                state['items'][item['id']] = item
            elif operation == 'update':
                _require(item_id in state['items'] and item is not None, 'reminder not found')
                current = state['items'][item_id]
                state['items'][item_id] = _validate_item({**item, 'id': item_id,
                                                           'created': current['created'],
                                                           'updated': int(time.time())})
            elif operation == 'delete':
                state['items'].pop(item_id, None)
            elif operation == 'complete':
                _require(item_id in state['items'], 'reminder not found')
                state['items'][item_id]['enabled'] = False
                state['items'][item_id]['updated'] = int(time.time())
            elif operation == 'set-enabled':
                _require(item_id in state['items'], 'reminder not found')
                state['items'][item_id]['enabled'] = bool(item)
                state['items'][item_id]['updated'] = int(time.time())
            elif operation == 'clear':
                state['items'] = {}
            else:
                raise ReminderError('unsupported reminder operation')
            self._publish_unlocked(fd, state)
            return state['items'].get(item_id) if item_id else item

    def set_all_enabled(self, enabled: bool) -> int:
        """Atomically pause or resume every local reminder."""
        _require(type(enabled) is bool)
        with self._session() as fd:
            state = self._read_unlocked(fd)
            changed = 0
            now = int(time.time())
            for item in state['items'].values():
                if item['enabled'] != enabled:
                    item['enabled'] = enabled
                    item['updated'] = now
                    changed += 1
            if changed:
                self._publish_unlocked(fd, state)
            return changed

    def advance(self, item: dict, next_due: datetime | None) -> bool:
        """Advance only the exact item snapshot that was just delivered."""
        _validate_item(item)
        with self._session() as fd:
            state = self._read_unlocked(fd)
            current = state['items'].get(item['id'])
            if current != item:
                # A concurrent edit or delete owns the new state. Do not
                # overwrite it with the worker's older delivery snapshot.
                return False
            if next_due is None:
                current['enabled'] = False
                current['updated'] = int(time.time())
            else:
                current = {**current, 'due': next_due.isoformat(timespec='minutes'),
                           'updated': int(time.time())}
                state['items'][item['id']] = _validate_item(current)
            self._publish_unlocked(fd, state)
            return True

    def reserve_delivery(self, item: dict) -> str | None:
        """Durably claim this exact snapshot before starting an external send."""
        item = _validate_item(item)
        with self._session() as fd:
            state = self._read_unlocked(fd)
            if state['items'].get(item['id']) != item or not item['enabled']:
                return None
            ledger = self._read_unlocked(fd, DELIVERY_NAME)
            key = _fingerprint(item)
            previous = ledger['items'].get(key)
            if previous and previous['status'] != 'not-sent':
                return 'accepted' if previous['status'] == 'accepted' else None
            # Retain every uncertain attempt, even after a user edits/deletes
            # its reminder. Only proven results with superseded snapshots prune.
            current_keys = {_fingerprint(current) for current in state['items'].values()}
            ledger['items'] = {token: record for token, record in ledger['items'].items()
                               if record['status'] in {'reserved', 'outcome-unknown'}
                               or token in current_keys}
            _require(key in ledger['items'] or len(ledger['items']) < 4096,
                     'local delivery ledger needs review before more notifications')
            ledger['items'][key] = {'item': item, 'status': 'reserved'}
            self._publish_unlocked(fd, ledger, DELIVERY_NAME)
            return 'reserved'

    def record_delivery(self, item: dict, status: str) -> None:
        item = _validate_item(item)
        _require(status in {'accepted', 'not-sent', 'outcome-unknown'})
        with self._session() as fd:
            ledger = self._read_unlocked(fd, DELIVERY_NAME)
            key = _fingerprint(item)
            record = ledger['items'].get(key)
            _require(record is not None and record['item'] == item and record['status'] == 'reserved',
                     'local delivery reservation changed')
            record['status'] = status
            self._publish_unlocked(fd, ledger, DELIVERY_NAME)

    def delivery_statuses(self) -> dict[str, str]:
        with self._session() as fd:
            state = self._read_unlocked(fd)
            ledger = self._read_unlocked(fd, DELIVERY_NAME)
            return {item['id']: ledger['items'][key]['status'] for item in state['items'].values()
                    if (key := _fingerprint(item)) in ledger['items']}

    def sync_remote(self, link: dict, fields: dict, preference: dict) -> None:
        """Mirror a Fruux item into local state after a successful remote write."""
        link = _validate_link(link)
        _require(link is not None)
        _require(isinstance(fields, dict) and isinstance(preference, dict))
        enabled = preference.get('enabled', False)
        _require(type(enabled) is bool, 'invalid linked reminder preference')
        if not enabled:
            self.remove_link(link)
            return
        zone = fields.get('timezone', 'Europe/Stockholm')
        anchor = fields.get('start') or fields.get('due')
        _require(isinstance(anchor, str) and anchor, 'linked reminder needs a date')
        try:
            parsed = datetime.fromisoformat(anchor.replace('Z', '+00:00'))
            if parsed.tzinfo is None:
                parsed = localize(parsed, zone)
            lead = preference.get('first_minutes', 15)
            _require(type(lead) is int and lead in FIRST_MINUTES, 'invalid linked reminder lead time')
            due = parsed.isoformat(timespec='minutes')
        except (TypeError, ValueError, KeyError):
            raise ReminderError('linked reminder date is invalid') from None
        recurrence = fields.get('recurrence', 'none')
        _require(recurrence in RECURRENCES, 'unsupported linked reminder recurrence')
        candidate = _validate_item({
            'id': '0' * 32,
            'title': _text(fields.get('summary', 'Reminder'), 512, 'reminder title'),
            'body': str(fields.get('description', ''))[:8192],
            'due': due,
            'timezone': zone,
            'first_minutes': lead,
            'recurrence': recurrence,
            'sound': True,
            'urgency': 'normal',
            'allow_dnd': False,
            'enabled': True,
            'link': link,
            'created': 0,
            'updated': 0,
        })
        with self._session() as fd:
            state = self._read_unlocked(fd)
            matches = [item for item in state['items'].values() if item['link'] == link]
            _require(len(matches) <= 1, 'duplicate linked reminders need review in Reminder Manager')
            previous = matches[0] if matches else None
            _require(previous is not None or len(state['items']) < MAX_ITEMS,
                     'local reminder limit reached')
            now = int(time.time())
            identity = previous['id'] if previous else secrets.token_hex(16)
            created = previous['created'] if previous else now
            state['items'][identity] = _validate_item({**candidate, 'id': identity,
                                                       'created': created, 'updated': max(now, created)})
            self._publish_unlocked(fd, state)

    def remove_link(self, link: dict) -> None:
        link = _validate_link(link)
        if link is None:
            return
        with self._session() as fd:
            state = self._read_unlocked(fd)
            remaining = {key: item for key, item in state['items'].items() if item['link'] != link}
            if len(remaining) != len(state['items']):
                state['items'] = remaining
                self._publish_unlocked(fd, state)


def _next_due(current: datetime, recurrence: str, zone: str,
              *, after: datetime | None = None) -> datetime | None:
    """Retain the named zone's civil time; omit invalid RFC recurrence dates."""
    _require(recurrence in RECURRENCES and current.tzinfo is not None,
             'invalid local reminder recurrence')
    if recurrence == 'none':
        return None
    try:
        current = current.astimezone(ZoneInfo(zone))
    except (ValueError, KeyError, TypeError):
        raise ReminderError('invalid reminder timezone') from None
    days = {'daily': 1, 'weekdays': 1, 'weekends': 1, 'every-2-days': 2,
            'every-3-days': 3, 'every-4-days': 4, 'every-5-days': 5,
            'weekly': 7, 'every-2-weeks': 14}
    months = {'monthly': 1, 'every-2-months': 2, 'quarterly': 3, 'yearly': 12}
    threshold = current
    if after is not None:
        _require(isinstance(after, datetime) and after.tzinfo is not None,
                 'invalid reminder recurrence horizon')
        threshold = max(current.astimezone(timezone.utc), after.astimezone(timezone.utc))
        threshold = threshold.astimezone(current.tzinfo)
    first = 1
    if recurrence in days:
        first = max(1, (threshold.date() - current.date()).days // days[recurrence])
    else:
        elapsed = (threshold.year - current.year) * 12 + threshold.month - current.month
        first = max(1, elapsed // months[recurrence])
    for occurrence in range(first, first + 366):
        if recurrence in days:
            try:
                candidate = current + timedelta(days=days[recurrence] * occurrence)
            except OverflowError:
                break
            if recurrence == 'weekdays' and candidate.weekday() >= 5:
                continue
            if recurrence == 'weekends' and candidate.weekday() < 5:
                continue
        else:
            ordinal = current.year * 12 + current.month - 1 + months[recurrence] * occurrence
            year, month = divmod(ordinal, 12)
            if not 1 <= year <= 9999:
                break
            try:
                candidate = current.replace(year=year, month=month + 1)
            except ValueError:
                # A monthly 31st or yearly leap day omits invalid dates;
                # clamping would permanently change the series' calendar day.
                continue
        candidate = candidate.replace(fold=0)
        if (candidate.astimezone(timezone.utc).astimezone(current.tzinfo).replace(tzinfo=None)
                == candidate.replace(tzinfo=None)
                and candidate.astimezone(timezone.utc) > threshold.astimezone(timezone.utc)):
            return candidate
    raise ReminderError('next reminder date is outside the supported range')


def _dnd_active() -> bool | None:
    """Return Mako's DND state, or None when the bounded query is unavailable."""
    try:
        result = subprocess.run(
            ['/usr/bin/makoctl', 'mode'], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding='utf-8', errors='replace',
            check=False, timeout=4,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return 'do-not-disturb' in result.stdout.splitlines()


def _notify(item: dict) -> bool | None:
    """True acknowledges acceptance; False proves no exec; None is uncertain."""
    try:
        result = subprocess.run(
            ['/usr/bin/notify-send', '-a', 'Labwc Reminders', '-u', item['urgency'],
             '--', item['title'], item['body'] or 'Local reminder'],
            check=False, timeout=15, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except (FileNotFoundError, PermissionError):
        return False
    except (OSError, subprocess.SubprocessError):
        return None
    return True if result.returncode == 0 else None


def _sound() -> None:
    """Play the optional alert without withholding the notification result."""
    try:
        subprocess.run(
            ['/usr/bin/paplay', '/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga'],
            check=False, timeout=15, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def run_worker() -> int:
    while True:
        now = datetime.now(timezone.utc)
        due_items = []
        dnd_checked = False
        dnd_state: bool | None = None
        store = Store()
        for item in store.list():
            if not item['enabled']:
                continue
            due = datetime.fromisoformat(item['due']).astimezone(timezone.utc) - timedelta(minutes=item['first_minutes'])
            if due <= now:
                if not item['allow_dnd'] and not dnd_checked:
                    dnd_state = _dnd_active()
                    dnd_checked = True
                if not item['allow_dnd'] and (dnd_state is None or dnd_state):
                    continue
                due_items.append((item, due))
        for item, due in due_items:
            next_due = _next_due(datetime.fromisoformat(item['due']), item['recurrence'], item['timezone'],
                                 after=now + timedelta(minutes=item['first_minutes']))
            reservation = store.reserve_delivery(item)
            if reservation == 'accepted':
                # A durable acknowledgement survived an interrupted advance.
                store.advance(item, next_due)
                continue
            if reservation != 'reserved':
                continue
            accepted = _notify(item)
            store.record_delivery(item, 'accepted' if accepted is True else
                                  'not-sent' if accepted is False else 'outcome-unknown')
            if accepted is not True:
                if accepted is None:
                    print('local-reminder status=outcome-unknown item_id=' + item['id'], file=sys.stderr)
                continue
            store.advance(item, next_due)
            if item['sound']:
                _sound()
        time.sleep(15)
