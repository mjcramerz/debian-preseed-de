#!/usr/bin/env python3
"""Manually edit color-only theme groups, with locked, durable backups."""
from __future__ import annotations

import argparse
from collections import OrderedDict
from contextlib import ExitStack
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import fcntl
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
MAX_SOURCE = 2 * 1024 * 1024
ASSIGNMENT = re.compile(r'([A-Z][A-Z0-9_]*)="([^"\r\n]*)"(\n|\Z)')
RGBA = re.compile(r'rgba\(\s*([0-9]{1,3})\s*,\s*([0-9]{1,3})\s*,\s*([0-9]{1,3})\s*,\s*([0-9]*\.?[0-9]+)\s*\)')
FORMATS = {
    'rgba': 'rgba(R, G, B, A), RGB 0..255 and alpha 0..1',
    'hash6': '#RRGGBB (six hexadecimal digits)',
    'hash8': '#AARRGGBB (Qt/Crystal Dock: alpha first)',
    'hex8': '#RRGGBBAA (Fuzzel: alpha last; stored without #)',
    'text': 'rgba(R, G, B, A) or #RRGGBB',
    'alpha': 'opacity from 0 to 1',
}


class ThemeError(ValueError):
    pass


@dataclass(frozen=True)
class Field:
    label: str
    keys: tuple[str, ...]
    kind: str


@dataclass(frozen=True)
class Section:
    name: str
    fields: tuple[Field, ...]


def normalize(value: str, kind: str) -> str:
    value = value.strip()
    if len(value) > 96 or not value.isascii():
        raise ThemeError('enter a literal color, not an expression')
    if kind in ('hash6', 'hash8', 'hex8'):
        digits = 6 if kind == 'hash6' else 8
        # The prompt always requests a hash-prefixed value. Accept the native
        # Fuzzel representation too when retaining an existing value.
        pattern = ('#?' if kind == 'hex8' else '#') + f'[0-9A-Fa-f]{{{digits}}}'
        if not re.fullmatch(pattern, value):
            raise ThemeError('expected ' + FORMATS[kind])
        return value.lower().removeprefix('#') if kind == 'hex8' else value.lower()
    if kind == 'alpha':
        if not re.fullmatch(r'(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)', value):
            raise ThemeError('expected opacity from 0 to 1')
        try:
            number = Decimal(value)
        except InvalidOperation as exc:
            raise ThemeError('invalid opacity') from exc
        if not 0 <= number <= 1:
            raise ThemeError('opacity must be between 0 and 1')
        return format(number.normalize(), 'f')
    if kind == 'text' and re.fullmatch(r'#[0-9A-Fa-f]{6}', value):
        return value.lower()
    if kind in ('rgba', 'text'):
        match = RGBA.fullmatch(value)
        if match and all(int(channel) <= 255 for channel in match.groups()[:3]):
            alpha = normalize(match[4], 'alpha')
            return f'rgba({int(match[1])}, {int(match[2])}, {int(match[3])}, {alpha})'
        raise ThemeError('expected ' + FORMATS[kind])
    raise ThemeError('unsupported color format: ' + kind)


def parse_base(data: bytes) -> tuple[list[str], dict[str, str]]:
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise ThemeError('base.env is not UTF-8') from exc
    lines = text.splitlines(keepends=True)
    values: dict[str, str] = {}
    for line in lines:
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        match = ASSIGNMENT.fullmatch(line)
        if not match or match[1] in values:
            raise ThemeError('invalid or duplicate base.env assignment')
        values[match[1]] = match[2]
    if not values:
        raise ThemeError('base.env is empty')
    return lines, values


def catalog(schema: Path, values: dict[str, str]) -> OrderedDict[str, Section]:
    kinds: dict[str, str] = {}
    for line in schema.read_text(encoding='utf-8').splitlines():
        if not line or line.startswith('#'):
            continue
        group, name, kind = line.split('\t')
        if group == 'base' and (name.endswith('_COLOR') or name == 'DOCK_APPLICATION_MENU_BACKGROUND_ALPHA'):
            if name.startswith(('WAYBAR_', 'FUZZEL_', 'DOCK_')):
                if kind not in FORMATS or name not in values or name in kinds:
                    raise ThemeError('unsupported or missing color contract: ' + name)
                kinds[name] = kind
    result: OrderedDict[str, Section] = OrderedDict()
    used: set[str] = set()

    def section(identifier: str, title: str, prefixes: tuple[str, ...], *, shared: bool = False) -> None:
        groups: OrderedDict[tuple[str, str], list[str]] = OrderedDict()
        for name, kind in kinds.items():
            prefix = next((prefix for prefix in prefixes if name.startswith(prefix)), None)
            if prefix is None:
                continue
            if name in used:
                raise ThemeError('overlapping color sections: ' + name)
            role = name[len(prefix):] if shared else name.removeprefix(prefixes[0])
            if shared and name.startswith('WAYBAR_BUTTON_') and role.endswith(('_ICON_COLOR', '_TEXT_COLOR')):
                # Shared semantic foreground roles keep warning/critical states
                # meaningful while asking only once per color across a unit.
                if 'HOVER' in role:
                    role = 'HOVER_FOREGROUND_COLOR'
                elif any(word in role for word in ('CRITICAL', 'ERROR')):
                    role = 'CRITICAL_FOREGROUND_COLOR'
                elif any(word in role for word in ('WARNING', 'MUTED', 'UNAVAILABLE', 'PAUSED', 'PAUSE_')):
                    role = 'WARNING_FOREGROUND_COLOR'
                elif any(word in role for word in ('CHARGING', 'FULL', 'BREAK')) and 'NOT_CHARGING' not in role:
                    role = 'POSITIVE_FOREGROUND_COLOR'
                else:
                    role = 'NORMAL_FOREGROUND_COLOR'
            groups.setdefault((role, kind), []).append(name)
            used.add(name)
        if not groups:
            raise ThemeError('empty color section: ' + identifier)
        fields = tuple(Field(role.removesuffix('_COLOR').replace('_', ' ').title(), tuple(keys), kind)
                       for (role, kind), keys in groups.items())
        result[identifier] = Section(title, fields)

    section('waybar-panel', 'Waybar Panel', ('WAYBAR_PANEL_',))
    section('waybar-menu', 'Waybar Menu Button', ('WAYBAR_BUTTON_MENU_',))
    section('waybar-workspaces', 'Waybar Workspaces Buttons', ('WAYBAR_BUTTON_WORKSPACES_', 'WAYBAR_WORKSPACES_CONTAINER_'))
    section('waybar-extras', 'Waybar Extras Buttons (Tomat, Wayscriber, Taskview, Apps)',
            tuple('WAYBAR_BUTTON_'+name+'_' for name in ('TOMAT', 'WAYSCRIBER', 'TASKVIEW', 'APPS')), shared=True)
    section('waybar-apps', 'Waybar Apps Buttons (Terminal, Files, Tuta, Notes, Sleek)',
            tuple('WAYBAR_BUTTON_'+name+'_' for name in ('TERMINAL', 'FILES', 'TUTANOTA', 'NOTES', 'SLEEK')), shared=True)
    section('waybar-clock', 'Waybar Clock Button and Calendar', ('WAYBAR_BUTTON_CLOCK_', 'WAYBAR_CLOCK_CALENDAR_'))
    section('waybar-hardware', 'Waybar Hardware Buttons (Audio, Backlight, Battery, Disk, CPU, Memory)',
            tuple('WAYBAR_BUTTON_'+name+'_' for name in ('AUDIO', 'BACKLIGHT', 'BATTERY', 'DISK', 'CPU', 'MEMORY')), shared=True)
    section('waybar-dropdown', 'Waybar Dropdown Menu', ('WAYBAR_DROPDOWN_MENU_',))
    section('waybar-submenu', 'Waybar Dropdown Submenu', ('WAYBAR_DROPDOWN_SUBMENU_',))
    section('waybar-taskbar', 'Waybar Taskbar', ('WAYBAR_BUTTON_TASKBAR_',))
    section('waybar-controls', 'Waybar Quick Controls', ('WAYBAR_QUICK_CONTROLS_',
            *(f'WAYBAR_BUTTON_{name}_' for name in ('BLUETOOTH', 'KEYBOARD', 'NETWORK', 'NOTIFICATIONS', 'SCREENSHOT', 'SYSTEM', 'TRAY'))))
    section('waybar-power', 'Waybar Power and Lock Buttons', ('WAYBAR_BUTTON_POWER_', 'WAYBAR_BUTTON_LOCK_'))
    section('waybar-tooltip', 'Waybar Tooltip', ('WAYBAR_TOOLTIP_',))
    section('waybar-app-surfaces', 'Waybar App Container and Symbolic Fill Colors',
            ('WAYBAR_APPS_CONTAINER_', 'WAYBAR_APPS_SYMBOLIC_', 'WAYBAR_WAYSCRIBER_SYMBOLIC_'))
    section('fuzzel', 'Fuzzel (one palette for all menus)',
            ('FUZZEL_MENU_', 'FUZZEL_COMPUTER_MANAGEMENT_MENU_'), shared=True)
    # Crystal Dock has three native style variants, with Qt ARGB backgrounds.
    dock_roles = OrderedDict()
    for name, kind in kinds.items():
        if name.startswith('DOCK_'):
            role = name.removeprefix('DOCK_').replace('_METAL_2D', '').replace('_2D', '')
            dock_roles.setdefault((role, kind), []).append(name)
            used.add(name)
    result['crystal-dock'] = Section('Crystal Dock (all native styles)', tuple(
        Field(role.removesuffix('_COLOR').replace('_', ' ').title(), tuple(keys), kind)
        for (role, kind), keys in dock_roles.items()))
    if used != kinds.keys():
        raise ThemeError('unmapped color keys: ' + ', '.join(sorted(kinds.keys()-used)))
    return result


def fingerprint(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns,
            info.st_mode, info.st_uid, info.st_gid, info.st_nlink)


class Editor:
    """Serialize editors on a pinned directory inode, not a replaceable file."""
    def __init__(self, root: Path = ROOT):
        self.root = root
        self.seed = root/'d-i/forky'
        self.themes = self.seed/'hosts/themes'
        self.backups = self.seed/'hosts/backup'
        self.stack = ExitStack()

    def directory(self, path: str | Path, parent: int | None = None) -> int:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
        self.stack.callback(os.close, fd)
        info = os.fstat(fd)
        if info.st_uid != os.geteuid() or info.st_mode & 0o022:
            raise ThemeError('theme directories must be owned by this account and not group/world writable')
        return fd

    def __enter__(self):
        try:
            # Resolve the trusted script location once, then open each repository
            # component without following links. No sudo or privilege changes.
            parent = self.directory(self.root)
            for component in ('d-i', 'forky', 'hosts'):
                parent = self.directory(component, parent)
            self.hosts_fd = parent
            self.themes_fd = self.directory('themes', parent)
            try:
                os.mkdir('backup', mode=0o700, dir_fd=parent)
                os.fsync(parent)
            except FileExistsError:
                pass
            self.backups_fd = self.directory('backup', parent)
            try:
                fcntl.flock(self.backups_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ThemeError('another theme editor is active') from exc
            self.original, self.info = self.read_base()
            self.lines, self.values = parse_base(self.original)
            self.validate(self.themes/'base.env')
            self.sections = catalog(self.themes/'theme-schema.tsv', self.values)
            return self
        except BaseException:
            self.stack.close()
            raise

    def __exit__(self, *exception):
        self.stack.close()

    def read_base(self) -> tuple[bytes, os.stat_result]:
        fd = os.open('base.env', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=self.themes_fd)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid()
                    or info.st_mode & 0o022 or info.st_size > MAX_SOURCE):
                raise ThemeError('unsafe base.env type, owner, permissions, hardlink count or size')
            data = stream.read(MAX_SOURCE+1)
            if len(data) > MAX_SOURCE or fingerprint(info) != fingerprint(os.fstat(stream.fileno())):
                raise ThemeError('base.env changed while reading')
            return data, info

    def unchanged(self) -> None:
        for name, fd in (('themes', self.themes_fd), ('backup', self.backups_fd)):
            current = os.stat(name, dir_fd=self.hosts_fd, follow_symlinks=False)
            pinned = os.fstat(fd)
            if not stat.S_ISDIR(current.st_mode) or (current.st_dev, current.st_ino) != (pinned.st_dev, pinned.st_ino):
                raise ThemeError('theme directory was replaced; refusing publication')
        data, info = self.read_base()
        if data != self.original or fingerprint(info) != fingerprint(self.info):
            raise ThemeError('base.env changed outside this editor; restart with the new values')

    def validate(self, base: Path) -> None:
        awk = shutil.which('awk', path='/usr/bin:/bin')
        if not awk:
            raise ThemeError('POSIX awk is required by the installer theme validator')
        result = subprocess.run([awk, '-f', str(self.seed/'scripts/late/theme-validate.awk'),
            str(self.themes/'theme-schema.tsv'), str(base), str(self.themes/'apps.env'), str(self.themes/'office.env')],
            env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'}, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=15, check=False)
        if result.returncode:
            raise ThemeError('installer theme validation failed: ' + result.stderr.strip()[:4000])

    def backup(self) -> Path:
        maximum = 0
        with os.scandir(self.backups_fd) as entries:
            for entry in entries:
                match = re.fullmatch(r'base\.env-([0-9]+)\.env', entry.name)
                if match:
                    if len(match[1]) > 18:
                        raise ThemeError('backup sequence is too large')
                    maximum = max(maximum, int(match[1]))
        name = f'base.env-{maximum+1}.env'
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600, dir_fd=self.backups_fd)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(self.original)
                stream.flush()
                os.fsync(stream.fileno())
            os.fsync(self.backups_fd)
        except BaseException:
            # A failed copy must not look like a complete recoverable backup.
            os.unlink(name, dir_fd=self.backups_fd)
            raise
        return self.backups/name

    def publish(self, changes: dict[str, str]) -> Path | None:
        allowed = {key: field.kind for section in self.sections.values() for field in section.fields for key in field.keys}
        normalized: dict[str, str] = {}
        for name, value in changes.items():
            if name not in allowed:
                raise ThemeError('not an editable color: ' + name)
            if value != self.values[name]:
                normalized[name] = normalize(value, allowed[name])
        changes = {name: value for name, value in normalized.items() if value != self.values[name]}
        if not changes:
            return None
        self.unchanged()
        backup = self.backup()  # Durable original exists BEFORE any rendering.
        rendered = ''.join(f'{match[1]}="{changes[match[1]]}"{match[3]}'
            if (match := ASSIGNMENT.fullmatch(line)) and match[1] in changes else line for line in self.lines).encode('utf-8')
        with tempfile.TemporaryDirectory(prefix='.themes-', dir=self.themes) as directory:
            candidate = Path(directory)/'base.env'  # Validator uses the basename.
            fd = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(rendered)
                stream.flush()
                os.fchown(stream.fileno(), self.info.st_uid, self.info.st_gid)
                os.fchmod(stream.fileno(), stat.S_IMODE(self.info.st_mode))
                os.fsync(stream.fileno())
            self.validate(candidate)
            self.unchanged()
            os.replace(candidate, 'base.env', dst_dir_fd=self.themes_fd)
            try:
                os.fsync(self.themes_fd)
            except OSError as exc:
                raise ThemeError(f'base.env was replaced but directory sync failed; original backup: {backup}') from exc
        self.original, self.info = self.read_base()
        self.lines, self.values = parse_base(self.original)
        return backup


def edit_section(editor: Editor, section: Section, read: Callable[[str], str] = input) -> None:
    print('\n'+section.name)
    print('Only colors change. Enter keeps the displayed value; :cancel abandons this section.')
    changes: dict[str, str] = {}
    for field in section.fields:
        current = editor.values[field.keys[0]]
        mixed = len({editor.values[key] for key in field.keys}) > 1
        shown = '#'+current if field.kind == 'hex8' else current
        print(f'\n{field.label} | {FORMATS[field.kind]} | {len(field.keys)} setting(s)')
        if mixed:
            print('Existing colors differ. Enter applies the displayed color to this entire group.')
        while True:
            value = read(f'[{shown}] > ').strip()
            if value == ':cancel':
                print('Cancelled; no files changed.')
                return
            try:
                normalized = current if not value else normalize(value, field.kind)
                break
            except ThemeError as exc:
                print(str(exc))
        changes.update(dict.fromkeys(field.keys, normalized))
    modified = {name: value for name, value in changes.items() if value != editor.values[name]}
    if not modified:
        print('No color changes.')
        return
    print(f'\n{len(modified)} color settings will change:')
    for name, value in modified.items():
        print(f'  {name}: {editor.values[name]} -> {value}')
    if read('Type APPLY to back up and save this section (anything else cancels): ').strip() != 'APPLY':
        print('Cancelled; no files changed.')
        return
    backup = editor.publish(modified)
    print(f'Saved {editor.themes / "base.env"}\nOriginal backup: {backup}')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--list', action='store_true', help='list color sections without editing')
    args = parser.parse_args(argv)
    if args.list:
        themes = ROOT/'d-i/forky/hosts/themes'
        _, values = parse_base((themes/'base.env').read_bytes())
        for identifier, section in catalog(themes/'theme-schema.tsv', values).items():
            print(f'{identifier}: {section.name}')
        return 0
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ThemeError('make themes is interactive; run it in a terminal')
    with Editor() as editor:
        while True:
            print('\nTHEMES | Manual color editor')
            sections = list(editor.sections.values())
            for index, section in enumerate(sections, 1):
                print(f' {index:2d}. {section.name}')
            print('  0. Exit')
            choice = input('Theme section: ').strip()
            if choice in ('0', 'q', 'Q', ''):
                return 0
            if len(choice) > 3 or not choice.isascii() or not choice.isdigit() or not 1 <= int(choice) <= len(sections):
                print('Choose a displayed section number.')
                continue
            edit_section(editor, sections[int(choice)-1])


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (KeyboardInterrupt, EOFError):
        print('\nCancelled. Any already saved sections and their backups are retained.', file=sys.stderr)
        raise SystemExit(130)
    except (OSError, ThemeError, subprocess.SubprocessError) as error:
        print('themes: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
