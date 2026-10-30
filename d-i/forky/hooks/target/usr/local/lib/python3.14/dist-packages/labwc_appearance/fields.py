"""Safe access to the installed native appearance color fields."""
from __future__ import annotations

import json
import os
from pathlib import Path
import pwd
import re
import secrets
import stat
import subprocess
from typing import Iterable

from managed_workflows.fs import Tree
from . import service, transaction
from .native import FILES, GREETER_FILES, user_paths

REGISTRY = Path('/usr/local/share/labwc-appearance/fields.json')
USER_LOCK = '.local/state/labwc-appearance/appearance.lock'
USER_JOURNAL = '.config/labwc/appearance-fields.pending.json'
ROOT_HELPER = '/usr/local/libexec/labwc-appearance-greeter'
MAX_REGISTRY_BYTES = 8 * 1024 * 1024
MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_FIELDS = 1024
MAX_VALUE_BYTES = 2048
MAX_LINE_PART_CANDIDATES = 4096
VARIANTS = ('', '.internal', '.external')
COMPONENTS = frozenset(('DOCK', 'FUZZEL', 'WAYBAR', 'TASKVIEW', 'WAYCAL', 'MAKO', 'TERMINAL', 'SWAYLOCK', 'GTKGREET'))
COLOR_TYPES = frozenset(('hash6', 'hash8', 'hex6', 'hex8', 'swaylock-rgb', 'swaylock-rgba', 'rgba', 'alpha', 'decimal',
                         'text-color', 'mako-progress'))
# These identifiers mirror the parsers used by the installed consumers:
# GTK3/GdkRGBA, GTK4/GdkRGBA, Pango markup, Qt QColor, Mako, Fuzzel, Foot,
# and Kitty.  Installer theme types are intentionally absent from this set.
NATIVE_GRAMMARS = frozenset(('gtk3-css-color', 'gtk4-css-color', 'pango-color', 'qt-color',
                             'mako-color', 'mako-progress', 'fuzzel-rgba', 'foot-rgb',
                             'kitty-color', 'swaylock-rgb', 'swaylock-rgba', 'alpha', 'decimal'))

_HEX = {
    'hash6': re.compile(r'#[0-9A-Fa-f]{6}\Z'),
    'hash8': re.compile(r'#[0-9A-Fa-f]{8}\Z'),
    'hex6': re.compile(r'[0-9A-Fa-f]{6}\Z'),
    'hex8': re.compile(r'[0-9A-Fa-f]{8}\Z'),
}
_GTK3_HEX = re.compile(r'#(?:[0-9A-Fa-f]{3}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{9}|'
                        r'[0-9A-Fa-f]{12})\Z')
_GTK4_HEX = re.compile(r'#(?:[0-9A-Fa-f]{3}|[0-9A-Fa-f]{4}|[0-9A-Fa-f]{6}|'
                        r'[0-9A-Fa-f]{8}|[0-9A-Fa-f]{9}|[0-9A-Fa-f]{12}|'
                        r'[0-9A-Fa-f]{16})\Z')
_PANGO_HEX = re.compile(r'#(?:[0-9A-Fa-f]{3}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{9}|'
                        r'[0-9A-Fa-f]{12})\Z')
_QT_HEX = re.compile(r'#(?:[0-9A-Fa-f]{3}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8}|'
                     r'[0-9A-Fa-f]{9}|[0-9A-Fa-f]{12})\Z')
_FUZZEL_RGBA = re.compile(r'[0-9A-Fa-f]{8}\Z')
_FOOT_RGB = re.compile(r'[0-9A-Fa-f]{6}\Z')
_SWAYLOCK_RGB = re.compile(r'[0-9A-Fa-f]{6}\Z')
_SWAYLOCK_RGBA = re.compile(r'[0-9A-Fa-f]{8}\Z')
_KITTY_HEX = re.compile(r'#(?:[0-9A-Fa-f]{3}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{9}|'
                        r'[0-9A-Fa-f]{12})(?:@(?:0|1|0\.[0-9]+|1\.0+))?\Z')
_COLOR_NAME = re.compile(r'(?:transparent|currentColor|[A-Za-z][A-Za-z0-9_-]{0,63})\Z')
_PANGO_NAME = re.compile(r'(?!transparent\Z|currentColor\Z)[A-Za-z][A-Za-z0-9_-]{0,63}\Z')
_QT_NAME = re.compile(r'(?:transparent|(?!currentColor\Z)[A-Za-z][A-Za-z0-9_-]{0,63})\Z')
_KITTY_NAME = re.compile(r'(?:transparent|(?!currentColor\Z)[A-Za-z][A-Za-z0-9_-]{0,63})\Z')
_KITTY_RGB = re.compile(r'(?:rgb:[0-9A-Fa-f]{1,4}/[0-9A-Fa-f]{1,4}/[0-9A-Fa-f]{1,4}|'
                        r'rgbi:[0-9]+(?:\.[0-9]+)?/[0-9]+(?:\.[0-9]+)?/'
                        r'[0-9]+(?:\.[0-9]+)?)(?:@(?:0|1|0\.[0-9]+|1\.0+))?\Z')
_GTK_FUNCTION = re.compile(r'(?i)(?:rgb|rgba|hsl|hsla)\([A-Za-z0-9.,%+\-/ ]+\)\Z')
_GTK_EXPRESSION = re.compile(r'(?i)(?:alpha|mix|shade|lighter|darker)\([A-Za-z0-9#@(),.%+\-/ ]+\)\Z')
_GTK_SYMBOLIC = re.compile(r'@[A-Za-z][A-Za-z0-9_-]{0,63}\Z')
_MAKO_COLOR = re.compile(r'#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?\Z')
_RGB_CHANNEL = r'(?:0|[1-9]?[0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])'
_RGBA = re.compile(
    rf'rgba\(\s*{_RGB_CHANNEL}\s*,\s*'
    rf'{_RGB_CHANNEL}\s*,\s*'
    rf'{_RGB_CHANNEL}\s*,\s*'
    r'(?:0|1|0\.[0-9]+|1\.0+)\s*\)\Z', re.IGNORECASE)
_NUMBER = re.compile(r'(?:0|1|0\.[0-9]+)\Z')
_TEXT_COLOR = re.compile(r'(?:transparent|#[0-9A-Fa-f]{6,8}|[A-Za-z]{1,32})\Z')
_MAKO_PROGRESS = re.compile(r'over #[0-9A-Fa-f]{8}\Z')
_RELATIVE = re.compile(r'[A-Za-z0-9_.+-]+(?:/[A-Za-z0-9_.+-]+)+\Z')


def _regular_owned(path: Path, *, uid: int | None = None, mode: int | tuple[int, ...] = 0o644,
                   limit: int = MAX_REGISTRY_BYTES) -> bytes:
    """Read one regular, single-link file without following a symlink."""
    with Tree(path.parent, uid=0 if uid is None else uid) as tree:
        with tree.open_read(path.name, limit=limit) as (stream, info):
            modes = (mode,) if isinstance(mode, int) else mode
            if stat.S_IMODE(info.st_mode) not in modes or (uid is None and info.st_gid != 0):
                raise ValueError('unsafe appearance file: ' + str(path))
            data = stream.read(limit + 1)
            if len(data) != info.st_size or len(data) > limit:
                raise ValueError('appearance file changed during read: ' + str(path))
            return data


def load_registry(*, require_captured: bool = True) -> dict:
    """Load and validate the root-owned registry produced during installation."""
    try:
        value = json.loads(_regular_owned(REGISTRY).decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError('installed appearance field registry is not valid JSON') from error
    if not isinstance(value, dict) or value.get('schema') != 3:
        raise ValueError('unsupported installed appearance field registry')
    if require_captured and value.get('captured') is not True:
        raise ValueError('installation did not capture the native appearance fields')
    fields = value.get('fields')
    components = value.get('components')
    if (not isinstance(fields, list) or not fields or len(fields) > MAX_FIELDS
            or not isinstance(components, list) or not components):
        raise ValueError('appearance field registry is incomplete')
    seen = set()
    component_ids = []
    for component in components:
        if (not isinstance(component, dict) or component.get('id') not in COMPONENTS
                or not isinstance(component.get('label'), str) or not component['label']):
            raise ValueError('invalid appearance component')
        component_ids.append(component['id'])
    if len(component_ids) != len(set(component_ids)):
        raise ValueError('duplicate appearance component')
    for field in fields:
        if not isinstance(field, dict):
            raise ValueError('invalid appearance field descriptor')
        key = field.get('key')
        component = field.get('component')
        value_type = field.get('type')
        mappings = field.get('mappings')
        if (not isinstance(key, str) or not re.fullmatch(r'[A-Z][A-Z0-9_]{2,127}', key)
                or key in seen or component not in COMPONENTS
                or value_type not in COLOR_TYPES or not isinstance(field.get('default'), str)
                or not isinstance(field.get('label'), str) or not isinstance(field.get('category'), str)
                or not isinstance(mappings, list) or not mappings):
            raise ValueError('invalid appearance field: ' + repr(key))
        seen.add(key)
        if component not in component_ids:
            raise ValueError('appearance component is not listed: ' + component)
        validate_value(field, field['default'])
        for mapping in mappings:
            _validate_mapping(mapping, key)
            validate_value(field, field['default'], mapping)
    return value


def _validate_mapping(mapping: dict, key: str) -> None:
    if not isinstance(mapping, dict):
        raise ValueError('invalid mapping for ' + key)
    path = mapping.get('path')
    line = mapping.get('line')
    template = mapping.get('template')
    tokens = mapping.get('tokens')
    target_index = mapping.get('target_index')
    grammar = mapping.get('grammar')
    allowed = {path for paths in FILES.values() for path in paths}
    allowed.update('/etc/greetd/' + name for name in GREETER_FILES)
    if (not isinstance(path, str) or path not in allowed or
            not isinstance(line, int) or not 1 <= line <= 100000
            or not isinstance(template, str) or len(template) > 32768
            or not isinstance(tokens, list) or not tokens or len(tokens) > 32
            or not all(isinstance(token, str) and re.fullmatch(
                r'__(?:THEME|INSTALLER)_[A-Z0-9_]+__', token) for token in tokens)
            or tokens != re.findall(r'__(?:THEME|INSTALLER)_[A-Z0-9_]+__', template)
            or not isinstance(target_index, int) or not 0 <= target_index < len(tokens)
            or tokens[target_index] != '__' + 'THEME_' + key + '__'
            or grammar not in NATIVE_GRAMMARS):
        raise ValueError('invalid appearance mapping for ' + key)


def field_map(registry: dict) -> dict[str, dict]:
    return {field['key']: field for field in registry['fields']}


def capture_registry() -> None:
    """Bind every field and its reset value to the fully staged native configs."""
    if os.getuid() != 0 or os.geteuid() != 0:
        raise ValueError('appearance field capture is installation-only')
    registry = load_registry(require_captured=False)
    token_validator = _registry_token_validator(registry)
    with Tree(Path('/etc/skel-desktop'), uid=0) as skeleton, \
            Tree(Path('/etc/greetd'), uid=0) as greeter:
        contents: dict[str, list[str]] = {}
        for field in registry['fields']:
            values = []
            for mapping in field['mappings']:
                path = mapping['path']
                if path not in contents:
                    raw = (greeter.read(path[len('/etc/greetd/'):]) if path.startswith('/')
                           else skeleton.read('.config/' + path))
                    text = raw.decode('utf-8')
                    if re.search(r'__[A-Z][A-Z0-9_]+__', text):
                        raise ValueError('unrendered native appearance config: ' + path)
                    contents[path] = text.splitlines()
                lines = contents[path]
                located = _locate_line_parts(lines, mapping, token_validator)
                if located is None:
                    raise ValueError('staged appearance mapping is unavailable: ' + field['key'])
                _, parsed = located
                values.append(validate_value(field, parsed[1][mapping['target_index']], mapping))
            if not values or any(value != values[0] for value in values[1:]):
                raise ValueError('staged appearance mappings disagree: ' + field['key'])
            field['default'] = values[0]
    registry['captured'] = True
    with Tree(REGISTRY.parent, uid=0) as output:
        output.write(REGISTRY.name, (json.dumps(registry, indent=2) + '\n').encode(), mode=0o644)


def validate_value(field: dict, value: str, mapping: dict | None = None) -> str:
    """Validate one value against the target native parser grammar.

    The field type remains the installed canonical/reset representation.  The
    mapping grammar is the runtime write contract and deliberately does not
    come from the installer theme schema.
    """
    if not isinstance(value, str) or len(value.encode('utf-8')) > MAX_VALUE_BYTES:
        raise ValueError('appearance value is too large')
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError('appearance value contains a control character')
    if mapping is None:
        mappings = field.get('mappings')
        if isinstance(mappings, list) and mappings:
            for target in mappings:
                validate_value(field, value, target)
            return value
    value_type = mapping.get('grammar') if mapping is not None else field.get('type')
    if value_type is None:
        raise ValueError('appearance mapping has no native grammar')
    if value_type in _HEX and _HEX[value_type].fullmatch(value):
        return value
    if value_type in ('gtk3-css-color', 'gtk4-css-color') and (
            (value_type == 'gtk3-css-color' and _GTK3_HEX.fullmatch(value))
            or (value_type == 'gtk4-css-color' and _GTK4_HEX.fullmatch(value))
            or _COLOR_NAME.fullmatch(value) or _GTK_SYMBOLIC.fullmatch(value)
            or _GTK_FUNCTION.fullmatch(value) or _GTK_EXPRESSION.fullmatch(value)):
        return value
    if value_type == 'pango-color' and (_PANGO_HEX.fullmatch(value) or _PANGO_NAME.fullmatch(value)):
        return value
    if value_type == 'qt-color' and (_QT_HEX.fullmatch(value) or _QT_NAME.fullmatch(value)):
        return value
    if value_type == 'mako-color' and _MAKO_COLOR.fullmatch(value):
        return value
    if value_type == 'fuzzel-rgba' and _FUZZEL_RGBA.fullmatch(value):
        return value
    if value_type == 'foot-rgb' and _FOOT_RGB.fullmatch(value):
        return value
    if value_type == 'swaylock-rgb' and _SWAYLOCK_RGB.fullmatch(value):
        return value
    if value_type == 'swaylock-rgba' and _SWAYLOCK_RGBA.fullmatch(value):
        return value
    if value_type == 'kitty-color' and (
            _KITTY_HEX.fullmatch(value) or _KITTY_RGB.fullmatch(value)
            or _KITTY_NAME.fullmatch(value)):
        return value
    if value_type == 'rgba' and _RGBA.fullmatch(value):
        return value
    if value_type == 'text-color' and (_TEXT_COLOR.fullmatch(value) or _RGBA.fullmatch(value)):
        return value
    if value_type == 'mako-progress' and re.fullmatch(r'over #[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?', value):
        return value
    if value_type in ('alpha', 'decimal') and _NUMBER.fullmatch(value):
        return value
    raise ValueError(f"invalid {value_type} value for {field['key']}")


def _registry_token_validator(registry: dict):
    fields = {field['key']: field for field in registry['fields']}
    theme_prefix = '__' + 'THEME_'

    def validate_token(token: str, value: str) -> bool:
        if not token.startswith(theme_prefix):
            return True
        key = token[len(theme_prefix):-2]
        field = fields.get(key)
        if field is None:
            return True
        for mapping in field['mappings']:
            try:
                validate_value(field, value, mapping)
            except ValueError:
                continue
            return True
        return False

    return validate_token


def _line_parts(line: str, mapping: dict, token_validator=None) -> tuple[list[str], list[str]] | None:
    """Return literal pieces and current token values for a rendered line.

    Native values such as CSS shadows and rgba() colors contain spaces.  A
    single non-greedy regex cannot identify token boundaries in those values.
    Enumerate bounded literal-delimiter candidates and retain only candidates
    whose known appearance tokens satisfy their native mapping grammars.
    """
    template = mapping['template']
    tokens = mapping['tokens']
    pieces = []
    cursor = 0
    for token in tokens:
        start = template.find(token, cursor)
        if start < cursor:
            return None
        pieces.append(template[cursor:start])
        cursor = start + len(token)
    pieces.append(template[cursor:])

    # Some native writers reserialize a file after the template renderer has
    # produced it.  Python's JSON writer, for example, can increase the
    # indentation of every member while preserving the actual mapping text.
    # Keep the template's structural literals strict, but accept a different
    # leading whitespace prefix and retain that prefix for later rewrites.
    if pieces and pieces[0]:
        template_prefix = pieces[0][:len(pieces[0]) - len(pieces[0].lstrip(' \t'))]
        if template_prefix:
            line_prefix = line[:len(line) - len(line.lstrip(' \t'))]
            literal = pieces[0][len(template_prefix):]
            if line.startswith(line_prefix + literal):
                pieces[0] = line_prefix + literal
    candidates: list[list[str]] = []

    def collect(index: int, cursor: int, values: list[str]) -> None:
        if len(candidates) > MAX_LINE_PART_CANDIDATES:
            return
        literal = pieces[index]
        if not line.startswith(literal, cursor):
            return
        start = cursor + len(literal)
        if index == len(tokens):
            if start == len(line):
                candidates.append(values)
            return
        delimiter = pieces[index + 1]
        if delimiter:
            positions = []
            position = start
            while True:
                found = line.find(delimiter, position)
                if found < 0:
                    break
                positions.append(found)
                position = found + 1
        else:
            positions = range(start, len(line) + 1)
        for end in positions:
            value = line[start:end]
            if token_validator is not None and not token_validator(tokens[index], value):
                continue
            collect(index + 1, end, values + [value])

    collect(0, 0, [])
    if len(candidates) != 1:
        return None
    return pieces, candidates[0]


def _locate_line_parts(
    lines: list[str], mapping: dict, token_validator=None,
) -> tuple[int, tuple[list[str], list[str]]] | None:
    """Locate a mapping in a rendered native file.

    Registry line numbers describe the source template and are the normal
    fast path. Rendering may replace placeholders, though, and a native
    template can add or remove lines before a mapped entry. In that case,
    search for the complete mapping template and choose the unique closest
    match to the declared source line. A duplicate nearest match is rejected
    so an ambiguous native entry is never edited accidentally.
    """
    def parse_line(index: int):
        line = lines[index]
        if line.endswith('\n'):
            line = line[:-1]
            if line.endswith('\r'):
                line = line[:-1]
        return _line_parts(line, mapping, token_validator)

    expected = mapping['line'] - 1
    if 0 <= expected < len(lines):
        parsed = parse_line(expected)
        if parsed is not None:
            return expected, parsed
    candidates = []
    for index, line in enumerate(lines):
        if index == expected:
            continue
        parsed = parse_line(index)
        if parsed is not None:
            candidates.append((index, parsed))
    if not candidates:
        return None
    distance = min(abs(index - expected) for index, _ in candidates)
    nearest = [(index, parsed) for index, parsed in candidates
               if abs(index - expected) == distance]
    return nearest[0] if len(nearest) == 1 else None


def _replace_line(line: str, mapping: dict, updates: dict[int, str], token_validator=None) -> str:
    newline = ''
    body = line
    if body.endswith('\n'):
        body = body[:-1]
        newline = '\n'
        if body.endswith('\r'):
            body = body[:-1]
            newline = '\r\n'
    result = _line_parts(body, mapping, token_validator)
    if result is None:
        raise RuntimeError(f"appearance file changed at line {mapping['line']}")
    pieces, values = result
    for index, value in updates.items():
        values[index] = value
    return ''.join(piece + (values[index] if index < len(values) else '')
                   for index, piece in enumerate(pieces)) + newline


def _apply_to_text(text: str, mappings: Iterable[tuple[dict, dict[int, str]]],
                   token_validator=None) -> str:
    lines = text.splitlines(keepends=True)
    grouped: dict[int, tuple[dict, dict[int, str]]] = {}
    for mapping, updates in mappings:
        located = _locate_line_parts(lines, mapping, token_validator)
        if located is None:
            raise RuntimeError(f"appearance mapping is unavailable near line {mapping['line']}")
        line_number, _ = located
        existing = grouped.get(line_number)
        if existing is None:
            grouped[line_number] = (mapping, dict(updates))
        else:
            first, values = existing
            if (first['template'] != mapping['template'] or first['tokens'] != mapping['tokens']):
                raise RuntimeError('conflicting appearance mapping templates')
            values.update(updates)
    for line_number, (mapping, updates) in grouped.items():
        lines[line_number] = _replace_line(lines[line_number], mapping, updates,
                                           token_validator)
    return ''.join(lines)


def _user_relative(path: str, variant: str = '') -> str:
    if not _RELATIVE.fullmatch(path):
        raise ValueError('appearance mapping is not a user file')
    return '.config/' + path + variant


def _candidate_user_paths(path: str) -> tuple[str, ...]:
    return tuple(_user_relative(path, variant) for variant in VARIANTS)


def _account_home() -> Path:
    account = pwd.getpwuid(os.getuid())
    home = Path(account.pw_dir)
    if not home.is_absolute() or '..' in home.parts:
        raise ValueError('desktop account has an unsafe home directory')
    return home


def _prepare_user_updates(tree: Tree, selected: dict[str, str]) -> tuple[dict[str, bytes], set[str]]:
    grouped: dict[str, list[tuple[dict, dict[int, str]]]] = {}
    components: set[str] = set()
    registry = load_registry()
    fields = field_map(registry)
    token_validator = _registry_token_validator(registry)
    for key, value in selected.items():
        field = fields.get(key)
        if field is None:
            raise ValueError('unknown installed appearance field: ' + key)
        components.add(field['component'].lower())
        for mapping in field['mappings']:
            value = validate_value(field, value, mapping)
            if mapping['path'].startswith('/'):
                continue
            for path in _candidate_user_paths(mapping['path']):
                if tree.read(path, missing=True) is not None:
                    grouped.setdefault(path, []).append((mapping, {mapping['target_index']: value}))
    if not grouped:
        return {}, components
    updates: dict[str, bytes] = {}
    for path, mappings in grouped.items():
        raw = tree.read(path)
        if raw is None:
            raise RuntimeError('appearance target disappeared: ' + path)
        text = raw.decode('utf-8')
        updates[path] = _apply_to_text(text, mappings, token_validator).encode('utf-8')
    return updates, components


def _apply_user_updates(selected: dict[str, str]) -> set[str]:
    account_home = _account_home()
    if os.getuid() == 0 or os.getuid() != os.geteuid():
        raise ValueError('run the appearance editor as the ordinary desktop account')
    with Tree(account_home) as tree:
        tree.mkdir('.config/labwc')
        tree.mkdir('.local/state/labwc-appearance')
        with tree.lock(USER_LOCK):
            if tree.json('.local/state/labwc-appearance/pending.json') is not None:
                raise RuntimeError('a theme transaction needs recovery in the appearance theme menu')
            pending = tree.json(USER_JOURNAL)
            if pending is not None:
                transaction.validate(pending, user_paths())
                if pending['phase'] == 'prepared':
                    transaction.rollback(tree, pending)
                else:
                    transaction.check_committed(tree, pending)
                tree.write(USER_JOURNAL, None)
            updates, components = _prepare_user_updates(tree, selected)
            if not updates:
                return components
            token = secrets.token_hex(16)
            journal = transaction.plan(tree, updates, token)
            transaction.validate(journal, set(updates) | {USER_JOURNAL})
            tree.put_json(USER_JOURNAL, journal)
            committed = False
            try:
                transaction.apply(tree, journal)
                journal['phase'] = 'committed'
                tree.put_json(USER_JOURNAL, journal)
                committed = True
                tree.write(USER_JOURNAL, None)
            except BaseException:
                if not committed:
                    transaction.rollback(tree, journal)
                    tree.write(USER_JOURNAL, None)
                raise
    return components


def _greeter_updates(selected: dict[str, str]) -> dict[str, str]:
    fields = field_map(load_registry())
    result = {}
    for key, value in selected.items():
        field = fields.get(key)
        if field is None:
            raise ValueError('unknown installed greeter field: ' + key)
        for mapping in field['mappings']:
            validate_value(field, value, mapping)
        if any(mapping['path'].startswith('/etc/greetd/') for mapping in field['mappings']):
            result[key] = value
    return result


def apply_greeter(selected: dict[str, str]) -> None:
    payload = json.dumps({'updates': _greeter_updates(selected)}, separators=(',', ':')).encode('utf-8')
    if len(payload) > MAX_INPUT_BYTES:
        raise ValueError('greeter appearance update is too large')
    process = subprocess.run(
        ['/usr/bin/pkexec', ROOT_HELPER, 'fields'], input=payload,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        timeout=120, env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C.UTF-8'},
    )
    if process.returncode != 0:
        message = process.stderr.decode('utf-8', 'replace').strip()
        raise RuntimeError(message[:300] or 'administrator authentication was not completed')


def apply_root_greeter(selected: dict[str, str]) -> None:
    """Apply a validated greeter-only update inside the authenticated helper."""
    updates_by_path: dict[str, list[tuple[dict, dict[int, str]]]] = {}
    registry = load_registry()
    fields = field_map(registry)
    token_validator = _registry_token_validator(registry)
    for key, value in selected.items():
        field = fields.get(key)
        if field is None:
            raise ValueError('unknown greeter appearance field: ' + key)
        mappings = [mapping for mapping in field['mappings']
                    if mapping['path'].startswith('/etc/greetd/')]
        if not mappings:
            raise ValueError('appearance field is not a greeter field: ' + key)
        for mapping in mappings:
            value = validate_value(field, value, mapping)
            relative = mapping['path'][len('/etc/greetd/'):]
            if relative not in GREETER_FILES:
                raise ValueError('unsafe greeter mapping path')
            updates_by_path.setdefault(relative, []).append(
                (mapping, {mapping['target_index']: value}))
    state_root = Path('/var/lib/labwc-appearance')
    try:
        state_info = state_root.lstat()
    except OSError as error:
        raise RuntimeError('greeter appearance state directory is unavailable') from error
    if (not stat.S_ISDIR(state_info.st_mode) or state_info.st_uid != 0
            or stat.S_IMODE(state_info.st_mode) != 0o700):
        raise RuntimeError('unsafe greeter appearance state directory')
    with Tree(state_root, uid=0, private=True) as state, state.lock('greeter.lock'), \
            Tree(Path('/etc/greetd'), uid=0) as config:
        if state.json('pending.json') is not None:
            raise RuntimeError('a greeter theme transaction needs recovery by its initiating account')
        pending = state.json('fields-pending.json')
        if pending is not None:
            transaction.validate(pending, {'gtkgreet.css', 'gtkgreet-power.css'})
            if pending.get('phase') == 'prepared':
                transaction.rollback(config, pending, mode=0o644)
            else:
                transaction.check_committed(config, pending)
            state.write('fields-pending.json', None)
        updates = {}
        for path, mappings in updates_by_path.items():
            raw = config.read(path)
            updates[path] = _apply_to_text(raw.decode('utf-8'), mappings, token_validator).encode('utf-8')
        token = secrets.token_hex(16)
        journal = transaction.plan(config, updates, token)
        transaction.validate(journal, set(updates))
        state.put_json('fields-pending.json', journal)
        committed = False
        try:
            transaction.apply(config, journal, mode=0o644)
            journal['phase'] = 'committed'
            state.put_json('fields-pending.json', journal)
            committed = True
            state.write('fields-pending.json', None)
        except BaseException:
            if not committed:
                transaction.rollback(config, journal, mode=0o644)
                state.write('fields-pending.json', None)
            raise


def apply(selected: dict[str, str]) -> list[str]:
    """Commit native user colors and authenticated greeter colors, then refresh."""
    if not selected:
        return []
    registry = load_registry()
    known = field_map(registry)
    if set(selected) - set(known):
        raise ValueError('appearance update contains an unknown field')
    for key, value in selected.items():
        for mapping in known[key]['mappings']:
            validate_value(known[key], value, mapping)
    greeter = {key: value for key, value in selected.items()
               if any(mapping['path'].startswith('/etc/greetd/') for mapping in known[key]['mappings'])}
    user = {key: value for key, value in selected.items() if key not in greeter}
    dock_running = bool(user) and any(known[key]['component'] == 'DOCK' for key in user)
    dock_running = dock_running and service.active('crystal-dock.service')
    if dock_running:
        service.dock_stop()
    try:
        components = _apply_user_updates(user) if user else set()
        if greeter:
            apply_greeter(greeter)
            components.add('gtkgreet')
    finally:
        if dock_running:
            service.dock_start()
    warnings = service.refresh(components)
    return warnings


def current_values(registry: dict | None = None) -> dict[str, str]:
    """Read values from the installed files, using registry defaults only as a guard."""
    registry = load_registry() if registry is None else registry
    result = {}
    token_validator = _registry_token_validator(registry)
    with Tree(_account_home()) as user_tree, Tree(Path('/etc/greetd'), uid=0) as greeter_tree:
        for field in registry['fields']:
            value = None
            for mapping in field['mappings']:
                paths = ((mapping['path'],) if mapping['path'].startswith('/')
                         else _candidate_user_paths(mapping['path']))
                for path in paths:
                    try:
                        raw = (greeter_tree.read(path[len('/etc/greetd/'):], missing=True)
                               if path.startswith('/etc/greetd/')
                               else user_tree.read(path, missing=True))
                        if raw is None:
                            continue
                        lines = raw.decode('utf-8').splitlines()
                        located = _locate_line_parts(lines, mapping, token_validator)
                        if located is not None:
                            _, parsed = located
                            value = validate_value(
                                field, parsed[1][mapping['target_index']], mapping)
                            break
                    except (OSError, UnicodeDecodeError, ValueError):
                        continue
                if value is not None:
                    break
            if value is None:
                raise RuntimeError('installed appearance field is not readable: ' + field['key'])
            result[field['key']] = value
    return result


def color_to_rgba(value: str, value_type: str, grammars: Iterable[str] = ()):
    """Convert a native value to a Gdk.RGBA preview using its mapping grammar."""
    from gi.repository import Gdk
    grammars = tuple(grammars)
    text = value
    if value_type == 'hex6':
        text = '#' + text
    elif value_type == 'hex8':
        text = '#' + text
    elif value_type in ('swaylock-rgb', 'swaylock-rgba'):
        text = '#' + value
    elif value_type == 'hash8' and ('qt-color' in grammars or not tuple(grammars)):
        # Qt QColor's eight-digit form is #AARRGGBB, while Gdk uses #RRGGBBAA.
        text = '#' + value[3:] + value[1:3]
    elif value_type == 'mako-progress':
        text = value.removeprefix('over ')
    rgba = Gdk.RGBA()
    if not rgba.parse(text):
        raise ValueError('value is not a previewable color')
    return rgba


def rgba_to_value(rgba, value_type: str, grammars: Iterable[str] = ()) -> str:
    """Serialize a picker value using the field's canonical/native alpha order."""
    grammars = tuple(grammars)
    red = round(rgba.red * 255)
    green = round(rgba.green * 255)
    blue = round(rgba.blue * 255)
    alpha = round(rgba.alpha * 255)
    if value_type == 'hash6':
        return f'#{red:02x}{green:02x}{blue:02x}'
    if value_type == 'hex6':
        return f'{red:02x}{green:02x}{blue:02x}'
    if value_type == 'hash8' and ('qt-color' in grammars or not tuple(grammars)):
        return f'#{alpha:02x}{red:02x}{green:02x}{blue:02x}'
    if value_type == 'hex8':
        return f'{red:02x}{green:02x}{blue:02x}{alpha:02x}'
    if value_type == 'swaylock-rgb':
        return f'{red:02x}{green:02x}{blue:02x}'
    if value_type == 'swaylock-rgba':
        return f'{red:02x}{green:02x}{blue:02x}{alpha:02x}'
    if value_type == 'rgba':
        return f'rgba({red}, {green}, {blue}, {rgba.alpha:.3f}'.rstrip('0').rstrip('.') + ')'
    if value_type == 'mako-progress':
        return 'over ' + f'#{red:02x}{green:02x}{blue:02x}{alpha:02x}'
    if value_type == 'text-color':
        return f'#{red:02x}{green:02x}{blue:02x}{alpha:02x}'
    raise ValueError('not a color field')
