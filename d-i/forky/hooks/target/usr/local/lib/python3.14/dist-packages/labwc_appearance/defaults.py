"""Capture actual rendered installation defaults once, before first login."""
from __future__ import annotations
import os
import json
from pathlib import Path
import re
import subprocess
from managed_workflows.fs import Tree
from .native import FILES, GREETER_FILES, VARIANTS, OPTIONAL_FILES, user_paths
from .editors import ini_values
from .icon_catalog import ICON_NAMES, POINTER_NAMES

DIRECTORY = Path('/usr/local/share/labwc-appearance')


def validate(value):
    if not isinstance(value, dict) or value.get('schema') != 3:
        raise ValueError('unsupported installed appearance defaults')
    files, greeter = value.get('files'), value.get('greeter')
    if not isinstance(files, dict) or not isinstance(greeter, dict):
        raise ValueError('invalid installed appearance defaults')
    if set(files) - user_paths() or set(greeter) != set(GREETER_FILES):
        raise ValueError('unexpected default configuration path')
    required = {'.config/' + p for paths in FILES.values() for p in paths}
    if not required <= set(files):
        raise ValueError('installation did not capture all appearance defaults')
    for path, text in {**files, **greeter}.items():
        if text is None and path in {'.config/' + p for p in OPTIONAL_FILES}:
            continue
        if not isinstance(text, str) or len(text) > 2 * 1024**2 or re.search(r'__[A-Z0-9_]+__', text):
            raise ValueError('unrendered or invalid installed appearance default')
    if value.get('mode') not in ('dark', 'light'):
        raise ValueError('invalid installed color mode')
    for key, allowed in (('icon_theme', ICON_NAMES), ('pointer_theme', POINTER_NAMES)):
        if not isinstance(value.get(key), str) or value[key] not in allowed:
            raise ValueError('invalid installed ' + key)
    settings = value.get('settings')
    if (not isinstance(settings, dict) or set(settings) != {'color-scheme', 'gtk-theme'} or
            any(not isinstance(v, str) or not re.fullmatch(r"'[A-Za-z0-9_. +:-]{1,100}'", v)
                for v in settings.values()) or
            settings['color-scheme'] not in ("'default'", "'prefer-dark'", "'prefer-light'")):
        raise ValueError('invalid installed desktop settings defaults')
    return value


def load():
    with Tree(DIRECTORY, uid=0) as tree:
        return validate(tree.json('defaults.json'))


def main(argv):
    if argv != ['--capture'] or os.getuid() != 0:
        raise ValueError('installation-only usage: labwc-appearance-defaults --capture (root)')
    from .fields import capture_registry
    capture_registry()
    DIRECTORY.mkdir(mode=0o755, parents=True, exist_ok=True)
    with Tree(DIRECTORY, uid=0) as output:
        existing = output.json('defaults.json')
        if existing is not None:
            validate(existing)
            return 0
        files = {}
        with Tree(Path('/etc/skel-desktop'), uid=0) as skeleton:
            for paths in FILES.values():
                for path in paths:
                    for suffix in VARIANTS:
                        if path in OPTIONAL_FILES and suffix:
                            continue
                        relative = '.config/' + path + suffix
                        raw = skeleton.read(relative, missing=bool(suffix) or path in OPTIONAL_FILES)
                        if raw is not None or not suffix:
                            files[relative] = None if raw is None else raw.decode('utf-8')
        with Tree(Path('/etc/greetd'), uid=0) as greetd:
            greeter = {name: greetd.read(name).decode('utf-8') for name in GREETER_FILES}
        gtk = ini_values(files['.config/gtk-3.0/settings.ini'])
        mode = 'dark' if gtk.get(('Settings', 'gtk-application-prefer-dark-theme')) in ('1', 'true') else 'light'
        # Read the installed, compiled schema overrides, without opening root's
        # dconf or starting a session bus. This includes the installed prefer-light
        # override; hard-coding 'default' would not restore the installed system.
        settings = {}
        for key in ('color-scheme', 'gtk-theme'):
            settings[key] = subprocess.run(
                ['/usr/bin/gsettings', 'get', 'org.gnome.desktop.interface', key],
                env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8',
                     'GSETTINGS_BACKEND': 'memory'},
                text=True, capture_output=True, check=True, timeout=15).stdout.strip()
        gtk_values = ini_values(files['.config/gtk-3.0/settings.ini'])
        icon_theme = gtk_values.get(('Settings', 'gtk-icon-theme-name'))
        pointer_theme = gtk_values.get(('Settings', 'gtk-cursor-theme-name'))
        if icon_theme not in ICON_NAMES or pointer_theme not in POINTER_NAMES:
            raise ValueError('installed icon or pointer default is not in the managed catalog')
        result = {'schema': 3, 'files': files, 'greeter': greeter, 'mode': mode,
                  'icon_theme': icon_theme, 'pointer_theme': pointer_theme,
                  'settings': settings}
        validate(result)
        output.write('defaults.json', (json.dumps(result, sort_keys=True, indent=2) + '\n').encode(), mode=0o644)
    return 0
