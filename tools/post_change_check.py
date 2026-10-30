#!/usr/bin/env python3
"""Run fast, non-mutating checks for every uncommitted changed file.

The checker never scans an untouched path. It parses the languages for which
the repository has local or standard-library parsers, runs shell syntax and
ShellCheck only on changed shell files, validates changed structured data, and
performs targeted theme/AppArmor checks. It never imports project modules,
executes repository scripts, starts services, contacts host sockets, or writes
validation artifacts.
"""
from __future__ import annotations

import ast
import configparser
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tomllib
import xml.etree.ElementTree as ElementTree
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - reported only for changed YAML input.
    yaml = None

YAML_ERROR = yaml.YAMLError if yaml is not None else ValueError


ROOT = Path(__file__).resolve().parents[1]
TARGET_ROOT = ROOT / 'd-i/forky/hooks/target'
SCHEMA = ROOT / 'd-i/forky/hosts/themes/theme-schema.tsv'
APPEARANCE_REGISTRY = TARGET_ROOT / 'usr/local/share/labwc-appearance/fields.json'
APPEARANCE_FIELDS = TARGET_ROOT / 'usr/local/lib/python3.14/dist-packages/labwc_appearance/fields.py'
APPEARANCE_NATIVE = TARGET_ROOT / 'usr/local/lib/python3.14/dist-packages/labwc_appearance/native.py'
THEME_FETCH_CORE = ROOT / 'd-i/forky/scripts/late/core.sh'
THEME_TOKEN = re.compile(rb'__THEME_([A-Z0-9_]+)__')
THEME_PREFIX = b'__THEME_'
REGISTRY_TOKEN = re.compile(r'__(?:THEME|INSTALLER)_[A-Z0-9_]+__')
APPEARANCE_COMPONENTS = frozenset({
    'DOCK', 'FUZZEL', 'WAYBAR', 'TASKVIEW', 'WAYCAL', 'MAKO', 'TERMINAL', 'SWAYLOCK', 'GTKGREET',
})
APPEARANCE_TYPES = frozenset({
    'hash6', 'hash8', 'hex6', 'hex8', 'swaylock-rgb', 'swaylock-rgba', 'rgba', 'alpha', 'decimal', 'text-color',
    'mako-progress',
})
APPEARANCE_GRAMMARS = frozenset({
    'gtk3-css-color', 'gtk4-css-color', 'pango-color', 'qt-color', 'mako-color',
    'mako-progress', 'fuzzel-rgba', 'foot-rgb', 'kitty-color', 'swaylock-rgb', 'swaylock-rgba', 'alpha', 'decimal',
})
APPEARANCE_PATHS = frozenset({
    'fuzzel/base.ini', 'fuzzel/fuzzel.ini', 'fuzzel/menu.ini',
    'fuzzel/computer-management.ini', 'waybar/style.css', 'waybar/style-common.css', 'waybar/config',
    'waybar/modules/app-files',
    'waybar/modules/app-notes',
    'waybar/modules/app-sleek',
    'waybar/modules/app-terminal',
    'waybar/modules/app-tuta',
    'waybar/modules/apps',
    'waybar/modules/backlight',
    'waybar/modules/battery',
    'waybar/modules/bluetooth',
    'waybar/modules/clock',
    'waybar/modules/cpu',
    'waybar/modules/disk',
    'waybar/modules/external-apps-drawer',
    'waybar/modules/external-launcher',
    'waybar/modules/external-quick-controls',
    'waybar/modules/external-taskbar',
    'waybar/modules/external-tray',
    'waybar/modules/internal-apps-drawer',
    'waybar/modules/internal-launcher',
    'waybar/modules/internal-quick-controls',
    'waybar/modules/internal-taskbar',
    'waybar/modules/internal-tray',
    'waybar/modules/keyboard',
    'waybar/modules/lock',
    'waybar/modules/memory',
    'waybar/modules/network',
    'waybar/modules/notifications',
    'waybar/modules/power',
    'waybar/modules/pulseaudio',
    'waybar/modules/screenshot',
    'waybar/modules/system',
    'waybar/modules/tomat',
    'waybar/modules/wayscriber',
    'waybar/modules/window-switcher',
    'waybar/modules/workspaces',
    'waybar/style/gtk.css',
    'waybar/style/menu.css', 'waybar/style/workspaces.css', 'waybar/style/tomat.css',
    'waybar/style/wayscriber.css', 'waybar/style/taskview.css', 'waybar/style/apps.css',
    'waybar/style/clock.css', 'waybar/style/audio.css', 'waybar/style/brightness.css',
    'waybar/style/battery.css', 'waybar/style/storage.css', 'waybar/style/cpu.css',
    'waybar/style/memory.css', 'waybar/style/tray.css', 'waybar/style/system.css',
    'waybar/style/notifications.css', 'waybar/style/lock.css', 'waybar/style/power.css',
    'waybar/icons/apps-symbolic.svg',
    'waybar/icons/wayscriber-symbolic.svg', 'waycal/style.css',
    'crystal-dock/labwc/appearance.conf',
    'foot/foot.ini', 'kitty/kitty.conf', 'mako/config', 'gtk-3.0/settings.ini',
    'gtk-4.0/settings.ini', 'gtk-4.0/gtk.css', 'swaylock/config', 'qt5ct/qt5ct.conf', 'qt6ct/qt6ct.conf',
    'qt5ct/colors/labwc-appearance.conf', 'qt6ct/colors/labwc-appearance.conf',
    'Kvantum/kvantum.kvconfig', 'labwc/themerc-override', 'labwc/environment',
    '/etc/greetd/gtkgreet.css', '/etc/greetd/gtkgreet-power.css',
})
SHELL_SUFFIXES = frozenset({'.env', '.sh'})
BINARY_SUFFIXES = frozenset({
    '.7z', '.bz2', '.deb', '.gif', '.gz', '.ico', '.jpeg', '.jpg', '.otf',
    '.png', '.tar', '.tgz', '.ttf', '.webp', '.woff', '.woff2', '.xz', '.zip',
})


def _run(command: list[str], *, timeout: int = 15) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        return subprocess.CompletedProcess(
            command, 124, stdout=error.stdout or '', stderr='static checker timed out'
        )


def _changed_paths() -> list[Path]:
    """Return only existing regular files changed or untracked in this checkout."""
    names: set[str] = set()
    commands = (
        ['git', 'diff', '--name-only', '-z', '--diff-filter=ACMRTUXB'],
        ['git', 'diff', '--cached', '--name-only', '-z', '--diff-filter=ACMRTUXB'],
        ['git', 'ls-files', '--others', '--exclude-standard', '-z'],
    )
    for command in commands:
        result = _run(command)
        if result.returncode:
            detail = (result.stderr or result.stdout).strip().replace('\n', ' ')[:300]
            raise RuntimeError(f'cannot enumerate changed files: {detail}')
        names.update(part for part in result.stdout.split('\0') if part)

    paths = []
    for name in sorted(names):
        path = ROOT / name
        if path.is_file() and not path.is_symlink() and path.is_relative_to(ROOT):
            paths.append(path)
    return paths


def _first_line(path: Path) -> str:
    with path.open('r', encoding='utf-8', errors='replace') as stream:
        return stream.readline(4096).strip()


def _logical_suffix(path: Path) -> str:
    return Path(path.name.removesuffix('.tmpl')).suffix.lower()


def _shell_kind(path: Path) -> str | None:
    first = _first_line(path)
    relative = path.relative_to(ROOT).as_posix()
    if '/etc/apparmor.d/' in '/' + relative and not first.startswith('#!'):
        return None
    if first.startswith('#!') and 'bash' in first:
        return 'bash'
    if first.startswith('#!') and re.search(r'\b(?:sh|dash|ash)\b', first):
        return 'sh'
    if _logical_suffix(path) in SHELL_SUFFIXES or path.name.endswith('.sh.tmpl'):
        return 'sh'
    return None


def _detail(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stderr or result.stdout).strip().replace('\n', ' ')[:500]


def _report_command(errors: list[str], label: str,
                    result: subprocess.CompletedProcess[str]) -> None:
    errors.append(f'{label}: command failed ({result.returncode}): {_detail(result)}')


def _read_text(path: Path) -> str:
    data = path.read_bytes()
    if b'\0' in data:
        raise ValueError('unexpected NUL byte in text source')
    return data.decode('utf-8')


def check_python(paths: list[Path], errors: list[str], counts: dict[str, int]) -> None:
    candidates = [path for path in paths if _logical_suffix(path) == '.py'
                  or re.match(r'^#!.*\bpython(?:[0-9]+(?:\.[0-9]+)*)?\b', _first_line(path))]
    for path in candidates:
        try:
            ast.parse(_read_text(path), filename=str(path.relative_to(ROOT)))
        except (OSError, UnicodeError, SyntaxError) as error:
            errors.append(f'{path.relative_to(ROOT)}: Python syntax: {error}')
    counts['python_ast'] = len(candidates)


def check_text_files(paths: list[Path], errors: list[str], counts: dict[str, int]) -> None:
    checked = 0
    for path in paths:
        suffix = _logical_suffix(path)
        if suffix in BINARY_SUFFIXES or path.name.endswith(('.tar.gz', '.tgz')):
            continue
        try:
            _read_text(path)
            checked += 1
        except (OSError, UnicodeError, ValueError) as error:
            errors.append(f'{path.relative_to(ROOT)}: text encoding/content: {error}')
    counts['text_files'] = checked


def _shellcheck_batch(errors: list[str], executable: str, kind: str,
                      paths: list[Path], *, unbound: bool) -> None:
    if not paths:
        return
    command = [executable, '--shell=' + kind, '--format=json']
    command.extend(['--severity=warning', '--include=SC2154'] if unbound else ['--severity=error'])
    command.extend(str(path) for path in paths)
    result = _run(command, timeout=60)
    if result.returncode not in (0, 1):
        _report_command(errors, f'ShellCheck {kind}', result)
        return
    if not result.stdout.strip():
        return
    try:
        messages = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        errors.append(f'ShellCheck {kind} returned malformed JSON: {error}')
        return
    for message in messages:
        errors.append(
            f"{message.get('file', '<unknown>')}:{message.get('line', '?')}: "
            f"ShellCheck SC{message.get('code', '?')}: {message.get('message', 'error')}"
        )


def check_shell(paths: list[Path], errors: list[str], counts: dict[str, int]) -> None:
    sources = [(path, _shell_kind(path)) for path in paths]
    sources = [(path, kind) for path, kind in sources if kind]
    counts['shell_sources'] = len(sources)
    if not sources:
        counts['shell_unbound_sources'] = 0
        return
    dash = shutil.which('dash')
    bash = shutil.which('bash')
    busybox = shutil.which('busybox')
    shellcheck = shutil.which('shellcheck')
    missing = [name for name, value in (
        ('dash', dash), ('bash', bash), ('busybox', busybox), ('shellcheck', shellcheck)
    ) if not value]
    if missing:
        errors.append('required static shell checker is unavailable: ' + ', '.join(missing))
        return

    for path, kind in sources:
        commands = [[bash, '-n', str(path)]] if kind == 'bash' else [
            [dash, '-n', str(path)], [busybox, 'sh', '-n', str(path)]
        ]
        for command in commands:
            result = _run(command)
            if result.returncode:
                _report_command(errors, f'{path.relative_to(ROOT)}: shell syntax', result)

    for kind in ('sh', 'bash'):
        _shellcheck_batch(
            errors, shellcheck, kind,
            [path for path, source_kind in sources if source_kind == kind],
            unbound=False,
        )
    counts['shell_unbound_sources'] = len(sources)
    for kind in ('sh', 'bash'):
        _shellcheck_batch(
            errors, shellcheck, kind,
            [path for path, source_kind in sources if source_kind == kind],
            unbound=True,
        )


def _schema_keys() -> set[str]:
    keys = set()
    for number, line in enumerate(SCHEMA.read_text(encoding='utf-8').splitlines(), 1):
        if not line or line.startswith('#'):
            continue
        fields = line.split('\t')
        if len(fields) != 3:
            raise ValueError(f'{SCHEMA}:{number}: malformed schema row')
        keys.add(fields[1])
    return keys


def _scan_markers(name: str, data: bytes, errors: list[str],
                  schema_keys: set[str] | None, counts: dict[str, int]) -> set[str] | None:
    if THEME_PREFIX not in data:
        return schema_keys
    counts['marker_files'] = counts.get('marker_files', 0) + 1
    for line_number, line in enumerate(data.splitlines(), 1):
        offset = 0
        while True:
            start = line.find(THEME_PREFIX, offset)
            if start < 0:
                break
            match = THEME_TOKEN.match(line, start)
            if not match:
                errors.append(f'{name}:{line_number}: malformed/partial __THEME_ marker')
            else:
                counts['theme_markers'] = counts.get('theme_markers', 0) + 1
                if schema_keys is None:
                    schema_keys = _schema_keys()
                key = match.group(1).decode('ascii')
                if key.removeprefix('TARGET_PATH_') not in schema_keys:
                    errors.append(f'{name}:{line_number}: unknown theme token {key}')
            offset = start + len(THEME_PREFIX)
    return schema_keys


def check_markers(paths: list[Path], errors: list[str], counts: dict[str, int]) -> None:
    schema_keys: set[str] | None = None
    # The installer theme renderer processes the staged target tree. Installer
    # source code has its own marker grammar and may construct marker strings
    # dynamically, so it is not mistaken for a staged asset here.
    for path in (path for path in paths if path.is_relative_to(TARGET_ROOT)):
        schema_keys = _scan_markers(str(path.relative_to(ROOT)), path.read_bytes(), errors,
                                    schema_keys, counts)
    counts.setdefault('marker_files', 0)
    counts.setdefault('theme_markers', 0)


def check_appearance_registry(paths: list[Path], errors: list[str], counts: dict[str, int]) -> None:
    """Validate the raw registry contract without importing installed code."""
    theme_inputs = {
        SCHEMA,
        *(ROOT / 'd-i/forky/hosts/themes' / (group + '.env') for group in ('base', 'apps', 'office')),
    }
    appearance_source_changed = any(
        path in {APPEARANCE_REGISTRY, APPEARANCE_FIELDS, APPEARANCE_NATIVE}
        or path in theme_inputs
        or (path.is_relative_to(TARGET_ROOT)
            and path.relative_to(TARGET_ROOT).parts[:2] in {('etc', 'greetd'), ('etc', 'skel-desktop')})
        for path in paths
    )
    if not appearance_source_changed:
        counts['appearance_registry_fields'] = 0
        counts['appearance_registry_mappings'] = 0
        counts['appearance_source_checks'] = 0
        counts['appearance_capture_line_checks'] = 0
        counts['appearance_native_token_checks'] = 0
        return
    field_count = 0
    mapping_count = 0
    multitoken_count = 0
    source_checks = 0
    capture_line_checks = 0
    native_token_checks = 0
    source_cache: dict[Path, list[str]] = {}
    try:
        value = json.loads(_read_text(APPEARANCE_REGISTRY))
        if (not isinstance(value, dict) or value.get('schema') != 3
                or value.get('captured') is not False
                or not isinstance(value.get('components'), list)
                or not isinstance(value.get('fields'), list)
                or not value['fields'] or len(value['fields']) > 1024):
            raise ValueError('registry must be schema 3 with captured=false and bounded fields')
        components = value['components']
        component_ids: list[str] = []
        for component in components:
            if (not isinstance(component, dict)
                    or component.get('id') not in APPEARANCE_COMPONENTS
                    or not isinstance(component.get('label'), str)
                    or not component['label']
                    or type(component.get('field_count')) is not int
                    or component['field_count'] < 1):
                raise ValueError('invalid component descriptor')
            component_ids.append(component['id'])
        if len(component_ids) != len(set(component_ids)):
            raise ValueError('duplicate component descriptor')
        seen: set[str] = set()
        theme_values: dict[str, str] = {}
        theme_types: dict[str, str] = {}
        for schema_line_number, schema_line in enumerate(_read_text(SCHEMA).splitlines(), 1):
            if not schema_line or schema_line.startswith('#'):
                continue
            schema_parts = schema_line.split('\t')
            if len(schema_parts) != 3:
                raise ValueError(f'{SCHEMA}:{schema_line_number}: malformed schema row')
            theme_types[schema_parts[1]] = schema_parts[2]
        for group in ('base', 'apps', 'office'):
            env_path = ROOT / 'd-i/forky/hosts/themes' / (group + '.env')
            for env_line_number, env_line in enumerate(_read_text(env_path).splitlines(), 1):
                if not env_line or env_line.startswith('#'):
                    continue
                match = re.fullmatch(r'([A-Z][A-Z0-9_]*)="([^"\r\n]*)"', env_line)
                if match:
                    theme_values[match[1]] = match[2]
        for field_number, field in enumerate(value['fields'], 1):
            if not isinstance(field, dict):
                raise ValueError(f'field {field_number} is not an object')
            key = field.get('key')
            if (not isinstance(key, str) or re.fullmatch(r'[A-Z][A-Z0-9_]{2,127}', key) is None
                    or key in seen or field.get('component') not in APPEARANCE_COMPONENTS
                    or field.get('component') not in component_ids
                    or field.get('type') not in APPEARANCE_TYPES
                    or not isinstance(field.get('default'), str)
                    or not isinstance(field.get('label'), str)
                    or not isinstance(field.get('category'), str)
                    or not isinstance(field.get('mappings'), list)
                    or not field['mappings']):
                raise ValueError(f'invalid field descriptor at index {field_number}')
            seen.add(key)
            field_count += 1
            for mapping_number, mapping in enumerate(field['mappings'], 1):
                if not isinstance(mapping, dict):
                    raise ValueError(f'{key} mapping {mapping_number} is not an object')
                path = mapping.get('path')
                source_name = mapping.get('source')
                template = mapping.get('template')
                tokens = mapping.get('tokens')
                target_index = mapping.get('target_index')
                if (not isinstance(path, str) or path not in APPEARANCE_PATHS
                        or type(mapping.get('line')) is not int
                        or not 1 <= mapping['line'] <= 100000
                        or not isinstance(template, str) or len(template) > 32768
                        or not isinstance(source_name, str)
                        or not isinstance(tokens, list) or not tokens or len(tokens) > 32
                        or not all(isinstance(token, str) and REGISTRY_TOKEN.fullmatch(token)
                                   for token in tokens)
                        or tokens != REGISTRY_TOKEN.findall(template)
                        or type(target_index) is not int
                        or not 0 <= target_index < len(tokens)
                        or tokens[target_index] != '__THEME_' + key + '__'
                        or mapping.get('grammar') not in APPEARANCE_GRAMMARS):
                    raise ValueError(f'invalid mapping for {key}')
                source = ROOT / source_name
                if (Path(source_name).is_absolute() or
                        source_name != source.relative_to(ROOT).as_posix() or
                        not source.is_relative_to(TARGET_ROOT) or
                        not source.is_file() or source.is_symlink()):
                    raise ValueError(f'{key} mapping {mapping_number} has an unsafe source path')
                source_lines = source_cache.get(source)
                if source_lines is None:
                    source_lines = _read_text(source).splitlines()
                    source_cache[source] = source_lines
                if mapping['line'] > len(source_lines):
                    raise ValueError(f'{key} mapping {mapping_number} source line is unavailable')
                source_line = source_lines[mapping['line'] - 1]
                if source_line != template:
                    raise ValueError(f'{key} mapping {mapping_number} template differs from source line')
                # Reproduce the data substitution boundary for this one source
                # line without importing or executing installer renderers. Use
                # actual checked-in theme literals and distinct safe sentinels
                # for installer-owned placeholders; then ensure the target
                # field remains uniquely extractable from the rendered line.
                rendered_line = source_line
                marker_matches = list(REGISTRY_TOKEN.finditer(rendered_line))
                for marker_index, marker in reversed(list(enumerate(marker_matches))):
                    token = marker.group(0)
                    if token.startswith('__THEME_'):
                        theme_key = token[len('__THEME_'):-2]
                        if theme_key not in theme_values:
                            raise ValueError(f'{key} mapping {mapping_number} references missing theme input {theme_key}')
                        replacement = theme_values[theme_key]
                    else:
                        replacement = f'INSTALLER_STATIC_VALUE_{marker_index}'
                    rendered_line = (rendered_line[:marker.start()] + replacement
                                     + rendered_line[marker.end():])
                pieces: list[str] = []
                cursor = 0
                for token in tokens:
                    start = template.find(token, cursor)
                    pieces.append(template[cursor:start])
                    cursor = start + len(token)
                pieces.append(template[cursor:])
                candidates: list[list[str]] = []

                def collect(index: int, position: int, extracted: list[str]) -> None:
                    if len(candidates) > 4096:
                        return
                    literal = pieces[index]
                    if not rendered_line.startswith(literal, position):
                        return
                    start = position + len(literal)
                    if index == len(tokens):
                        if start == len(rendered_line):
                            candidates.append(extracted)
                        return
                    delimiter = pieces[index + 1]
                    if delimiter:
                        ends = []
                        probe = start
                        while True:
                            probe = rendered_line.find(delimiter, probe)
                            if probe < 0:
                                break
                            ends.append(probe)
                            probe += 1
                    else:
                        ends = range(start, len(rendered_line) + 1)
                    for end in ends:
                        token_value = rendered_line[start:end]
                        theme_token = tokens[index]
                        if theme_token.startswith('__THEME_'):
                            theme_key = theme_token[len('__THEME_'):-2]
                            expected_value = theme_values.get(theme_key)
                            if expected_value is not None and token_value != expected_value:
                                continue
                        collect(index + 1, end, extracted + [token_value])

                collect(0, 0, [])
                if len(candidates) != 1:
                    raise ValueError(
                        f'{key} mapping {mapping_number} does not have one rendered-line tokenization '
                        f'(found {len(candidates)})'
                    )
                capture_line_checks += 1
                relative = source.relative_to(TARGET_ROOT)
                if relative.parts[:3] == ('etc', 'skel-desktop', '.config'):
                    expected_path = relative.relative_to('etc/skel-desktop/.config')
                    if expected_path.name.endswith('.tmpl'):
                        expected_path = expected_path.with_suffix('')
                    expected_path = expected_path.as_posix()
                elif relative.parts[:2] == ('etc', 'greetd'):
                    expected_path = relative
                    if expected_path.name.endswith('.tmpl'):
                        expected_path = expected_path.with_suffix('')
                    expected_path = '/' + expected_path.as_posix()
                else:
                    raise ValueError(f'{key} mapping {mapping_number} source is not a native template')
                if path != expected_path:
                    raise ValueError(f'{key} mapping {mapping_number} target path differs from source')
                source_checks += 1
                mapping_count += 1
                multitoken_count += len(tokens) > 1
        # Discover native color tokens from every checked-in appearance source
        # corresponding to an allowlisted installed path. This catches a new
        # color token that was added to a native file but omitted from the
        # registry entirely, including a whole source file with no mappings.
        native_sources: set[Path] = set()
        for target_path in APPEARANCE_PATHS:
            if target_path.startswith('/'):
                relative = Path(target_path[1:])
                source_base = TARGET_ROOT / relative
            else:
                source_base = TARGET_ROOT / 'etc/skel-desktop/.config' / target_path
            for candidate in (source_base.with_name(source_base.name + '.tmpl'), source_base):
                if candidate.is_file() and not candidate.is_symlink():
                    native_sources.add(candidate)
                    break
        for source in sorted(native_sources):
            for token_match in REGISTRY_TOKEN.finditer(_read_text(source)):
                token = token_match.group(0)
                if not token.startswith('__THEME_'):
                    continue
                theme_key = token[len('__THEME_'):-2]
                if theme_types.get(theme_key) not in APPEARANCE_GRAMMARS:
                    continue
                native_token_checks += 1
                if theme_key not in seen:
                    raise ValueError(
                        f'{theme_key} is a native color token without an appearance mapping '
                        f'in {source.relative_to(ROOT)}'
                    )
        for component in components:
            expected = sum(1 for field in value['fields'] if field['component'] == component['id'])
            if component['field_count'] != expected:
                raise ValueError(f"field count mismatch for {component['id']}")
    except (OSError, UnicodeError, TypeError, ValueError, json.JSONDecodeError) as error:
        errors.append(f'{APPEARANCE_REGISTRY.relative_to(ROOT)}: registry contract: {error}')
    counts['appearance_registry_fields'] = field_count
    counts['appearance_registry_mappings'] = mapping_count
    counts['appearance_multitoken_mappings'] = multitoken_count
    counts['appearance_source_checks'] = source_checks
    counts['appearance_capture_line_checks'] = capture_line_checks
    counts['appearance_native_token_checks'] = native_token_checks


def check_appearance_render_preservation(paths: list[Path], errors: list[str],
                                         counts: dict[str, int]) -> None:
    """Require code and registry assets to bypass theme substitution."""
    if THEME_FETCH_CORE not in paths:
        counts['appearance_render_contract'] = 0
        return
    try:
        text = _read_text(THEME_FETCH_CORE)
        markers = {
            '*/usr/local/share/labwc-appearance/fields.json) return 0 ;;':
                'missing raw fields.json theme-render exemption',
            '*/usr/local/lib/python3.14/dist-packages/labwc_appearance/*.py) return 0 ;;':
                'missing appearance Python code theme-render exemption',
        }
        for marker, description in markers.items():
            if marker not in text:
                errors.append(f'{THEME_FETCH_CORE.relative_to(ROOT)}: {description}')
    except (OSError, UnicodeError) as error:
        errors.append(f'{THEME_FETCH_CORE.relative_to(ROOT)}: render contract: {error}')
    counts['appearance_render_contract'] = 1


def check_waybar_render_contract(paths: list[Path], errors: list[str],
                                 counts: dict[str, int]) -> None:
    """Check that Waybar config assets always use their placeholder map."""
    renderer = ROOT / 'd-i/forky/scripts/desktop/components/core-renderers.sh.tmpl'
    waybar_root = TARGET_ROOT / 'etc/skel-desktop/.config/waybar'
    changed_waybar = [path for path in paths if path.is_relative_to(waybar_root)
                      and path.name.endswith('.tmpl')]
    if renderer not in paths and not changed_waybar:
        counts['waybar_render_contract'] = 0
        return
    try:
        renderer_text = _read_text(renderer)
        if re.search(r'(?m)^\s*desktop_render_waybar_asset\s+config\s*$', renderer_text):
            errors.append(f'{renderer.relative_to(ROOT)}: config.tmpl is rendered once without its placeholder map')
        if 'desktop_render_waybar_config_asset "$wb_config_asset"' not in renderer_text:
            errors.append(f'{renderer.relative_to(ROOT)}: Waybar config asset loop is missing')
        module_root = waybar_root / 'modules'
        module_assets = {path.name.removesuffix('.tmpl') for path in changed_waybar
                         if path.parent == module_root}
        for asset in sorted(module_assets):
            if asset not in renderer_text:
                errors.append(f'{renderer.relative_to(ROOT)}: module template {asset} is not in the config renderer loop')
        counts['waybar_module_templates'] = len(module_assets)
        style_root = waybar_root / 'style'
        style_assets = {path.name.removesuffix('.tmpl') for path in changed_waybar
                        if path.parent == style_root}
        for asset in sorted(style_assets):
            loop_name = asset
            if loop_name not in renderer_text:
                errors.append(f'{renderer.relative_to(ROOT)}: style template {asset} is not in the style renderer loop')
        counts['waybar_style_templates'] = len(style_assets)
        map_match = re.search(
            r'desktop_render_waybar_config_asset\(\) \{(.*?)\n  \}\n  desktop_render_waybar_config_asset config',
            renderer_text, re.DOTALL,
        )
        if map_match is None:
            errors.append(f'{renderer.relative_to(ROOT)}: config placeholder map body is missing')
            explicit = set()
        else:
            explicit = set(re.findall(r'^\s+(LABWC_[A-Z0-9_]+)\s+"', map_match.group(1), re.MULTILINE))
        geometry = ROOT / 'd-i/forky/scripts/desktop/waybar-geometry.tsv'
        geometry_keys = set()
        for line in _read_text(geometry).splitlines():
            if not line or line.startswith('#'):
                continue
            fields = line.split('\t')
            if len(fields) == 4:
                geometry_keys.add(fields[0])
        accepted = set(explicit)
        for key in geometry_keys:
            accepted.update({f'LABWC_WAYBAR_INTERNAL_{key}', f'LABWC_WAYBAR_EXTERNAL_{key}'})
            if key.startswith(('MENU_', 'POPUP_', 'TOOLTIP_')):
                accepted.add(f'LABWC_WAYBAR_SHARED_{key}')
        tokens = set()
        for path in changed_waybar:
            tokens.update(re.findall(r'__INSTALLER_([A-Z0-9_]+)__', _read_text(path)))
        unknown = sorted(token for token in tokens if token not in accepted)
        for token in unknown:
            errors.append(f'{waybar_root.relative_to(ROOT)}: no Waybar renderer map entry for {token}')
        counts['waybar_installer_tokens'] = len(tokens)
    except (OSError, UnicodeError) as error:
        errors.append(f'{renderer.relative_to(ROOT)}: Waybar render contract: {error}')
    counts['waybar_render_contract'] = 1


def check_payload_archive(paths: list[Path], errors: list[str], counts: dict[str, int]) -> None:
    archive_path = ROOT / 'd-i/forky/payload.tar.gz'
    if archive_path not in paths:
        return
    schema_keys: set[str] | None = None
    member_count = 0
    with tarfile.open(archive_path, 'r:*') as archive:
        for member in archive.getmembers():
            member_count += 1
            if member_count > 100000:
                raise ValueError('payload archive member limit exceeded')
            if not member.isfile() or not member.name.startswith('hooks/target/'):
                continue
            if Path(member.name).suffix.lower() in BINARY_SUFFIXES:
                continue
            stream = archive.extractfile(member)
            if stream is None:
                continue
            data = stream.read(8 * 1024 * 1024 + 1)
            if len(data) > 8 * 1024 * 1024:
                continue
            schema_keys = _scan_markers(member.name, data, errors, schema_keys, counts)
    counts['payload_members'] = member_count
    sources = (
        ('hooks/target/usr/local/lib/python3.14/dist-packages/labwc_appearance/fields.py',
         APPEARANCE_FIELDS),
        ('hooks/target/usr/local/lib/python3.14/dist-packages/labwc_appearance/native.py',
         APPEARANCE_NATIVE),
        ('hooks/target/usr/local/share/labwc-appearance/fields.json', APPEARANCE_REGISTRY),
        ('scripts/late/core.sh', ROOT / 'd-i/forky/scripts/late/core.sh'),
    )
    with tarfile.open(archive_path, 'r:*') as archive:
        for member_name, source in sources:
            if source not in paths:
                continue
            member = archive.extractfile(member_name)
            if member is None or member.read() != source.read_bytes():
                errors.append(f'payload {Path(member_name).name} does not match the source file')


def check_structured(paths: list[Path], errors: list[str], counts: dict[str, int]) -> None:
    parsed = 0
    yaml_files = 0
    for path in paths:
        suffix = _logical_suffix(path)
        try:
            if suffix in BINARY_SUFFIXES:
                if path.name.endswith(('.tar.gz', '.tgz')):
                    with tarfile.open(path, 'r:*') as archive:
                        archive.getmembers()
                continue
            text = _read_text(path)
            waybar_root = TARGET_ROOT / 'etc/skel-desktop/.config/waybar'
            if path.is_relative_to(waybar_root) and (
                    path.name == 'config.tmpl' or path.parent == waybar_root / 'modules'):
                # Numeric/list installer slots are the only unquoted tokens
                # in these JSON templates. Parse as data without executing a
                # renderer, and preserve quoted strings and action arguments.
                json.loads(re.sub(r'__(?:THEME|INSTALLER)_[A-Z0-9_]+__(?=\s*[,}\]])',
                                  '0', text))
                parsed += 1
            elif path.is_relative_to(waybar_root) and suffix in {'.xml', '.svg'}:
                ElementTree.fromstring(text)
                parsed += 1
            elif suffix == '.json' and not path.name.endswith('.json.tmpl'):
                json.loads(text)
                parsed += 1
            elif suffix in {'.yaml', '.yml'} and not path.name.endswith(('.yaml.tmpl', '.yml.tmpl')):
                if yaml is None:
                    errors.append(f'{path.relative_to(ROOT)}: YAML parser unavailable')
                else:
                    list(yaml.parse(text))
                    yaml_files += 1
                    parsed += 1
            elif suffix == '.toml' and not path.name.endswith('.toml.tmpl'):
                tomllib.loads(text)
                parsed += 1
            elif suffix in {'.xml', '.svg'} and not path.name.endswith(('.xml.tmpl', '.svg.tmpl')):
                ElementTree.fromstring(text)
                parsed += 1
            elif suffix in {'.desktop', '.ini'} and not path.name.endswith('.tmpl'):
                parser = configparser.ConfigParser(interpolation=None, strict=True)
                parser.read_string(text)
                parsed += 1
            elif suffix in {'.service', '.timer'} and not path.name.endswith('.tmpl'):
                for line_number, line in enumerate(text.splitlines(), 1):
                    stripped = line.strip()
                    if not stripped or stripped.startswith(('#', ';')):
                        continue
                    if stripped.startswith('[') and stripped.endswith(']'):
                        continue
                    if '=' not in line or not re.match(r'^[A-Za-z][A-Za-z0-9]+=', line):
                        raise ValueError(f'malformed unit assignment at line {line_number}')
                parsed += 1
            elif suffix == '.tsv' and not path.name.endswith('.tsv.tmpl'):
                widths = {len(line.split('\t')) for line in text.splitlines() if line and not line.startswith('#')}
                if len(widths) > 1:
                    raise ValueError('inconsistent tabular field count')
                parsed += 1
            elif suffix == '.env' and not path.name.endswith('.env.tmpl'):
                for line_number, line in enumerate(text.splitlines(), 1):
                    if line and not line.startswith('#') and not re.fullmatch(r'[A-Z][A-Z0-9_]*=.*', line):
                        raise ValueError(f'malformed environment assignment at line {line_number}')
                parsed += 1
        except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError,
                tomllib.TOMLDecodeError, ElementTree.ParseError, configparser.Error,
                YAML_ERROR) as error:
            errors.append(f'{path.relative_to(ROOT)}: structured syntax: {error}')
    counts['structured_files'] = parsed
    counts['yaml_files'] = yaml_files


def check_apparmor(paths: list[Path], errors: list[str], counts: dict[str, int]) -> None:
    policy_root = TARGET_ROOT / 'etc/apparmor.d'
    files = [path for path in paths if path.is_relative_to(policy_root)]
    file_rule = re.compile(
        r'\s*((?:(?:audit|deny|allow|owner)\s+)*)'
        r'(?:"[^"\n]+"|/[^\s"]*|@\{[A-Za-z0-9_]+\}[^\s]*)\s+'
        r'([A-Za-z]+)(?:\s+->\s+[^\s,]+)?\s*,\s*(?:#.*)?'
    )
    for path in files:
        text = _read_text(path)
        depth = 0
        for line_number, raw in enumerate(text.splitlines(), 1):
            stripped = raw.lstrip()
            line = '' if stripped.startswith('#') else raw
            rule = file_rule.fullmatch(line)
            if (rule and 'deny' not in rule.group(1).split()
                    and re.search(r'(?<![ipPcCuU])x', rule.group(2))):
                errors.append(f'{path.relative_to(ROOT)}:{line_number}: '
                              'AppArmor allow execute permission requires an execution qualifier')
            for column, char in enumerate(line, 1):
                if char == '{':
                    depth += 1
                elif char == '}':
                    depth -= 1
                    if depth < 0:
                        errors.append(f'{path.relative_to(ROOT)}:{line_number}:{column}: unmatched closing brace')
                        depth = 0
            if ('{' in line and '}' not in line and not stripped.startswith('profile ')
                    and ('/' in line or stripped.startswith(('owner ', 'deny owner ')))):
                errors.append(f'{path.relative_to(ROOT)}:{line_number}: multiline path/owner brace rule')
            if stripped.startswith('profile ') and not stripped.endswith('{'):
                errors.append(f'{path.relative_to(ROOT)}:{line_number}: profile declaration lacks opening brace')
        if depth:
            errors.append(f'{path.relative_to(ROOT)}:EOF: unclosed brace depth {depth}')
        if not text.endswith('\n'):
            errors.append(f'{path.relative_to(ROOT)}:EOF: missing final newline')
    counts['apparmor_files'] = len(files)


def check_diff(errors: list[str]) -> None:
    for command in (['git', 'diff', '--check'], ['git', 'diff', '--cached', '--check']):
        result = _run(command)
        if result.returncode:
            _report_command(errors, ' '.join(command), result)


def main() -> int:
    errors: list[str] = []
    counts: dict[str, int] = {}
    try:
        paths = _changed_paths()
        counts['changed_files'] = len(paths)
        check_text_files(paths, errors, counts)
        check_python(paths, errors, counts)
        check_shell(paths, errors, counts)
        check_markers(paths, errors, counts)
        check_structured(paths, errors, counts)
        check_appearance_registry(paths, errors, counts)
        check_appearance_render_preservation(paths, errors, counts)
        check_waybar_render_contract(paths, errors, counts)
        check_apparmor(paths, errors, counts)
        check_payload_archive(paths, errors, counts)
        check_diff(errors)
    except (OSError, UnicodeError, RuntimeError, ValueError) as error:
        errors.append(f'checker failure: {error}')
    print('post-change static audit: ' + ('PASS' if not errors else 'FAIL'))
    print('counts: ' + ', '.join(f'{key}={value}' for key, value in sorted(counts.items())))
    if errors:
        for error in errors:
            print('ERROR: ' + error, file=sys.stderr)
        return 1
    print('checks: changed-file Python, shell, ShellCheck, theme markers, JSON/YAML/TOML/XML/INI-like data, AppArmor structure, git diff')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
