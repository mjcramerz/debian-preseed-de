"""Render the real output-class assets; stub transport/publishing, not policy."""

# Refuse host execution before importing runtime helpers or creating fixtures.
from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[3] / 'tools'))
# Copied checker/GUI fixtures still use the verified private checkout gate.
_isolation_sys.path.insert(0, '/workspace/repository/tools')
from isolation import require_test_isolation as _require_test_isolation
_isolation_sys.path.pop(0)
_require_test_isolation()

from functools import lru_cache
from pathlib import Path
import os
import json
import re
import subprocess
import tempfile
from payload_fixture import installed_argv, read_text
from theme_fixture import render_theme_defaults

FORKY = Path(__file__).resolve().parents[1]
TARGET = FORKY / 'hooks/target'

@lru_cache(maxsize=32)
def native_assets(profile, count=None, theme_items=()):
    """Return the rendered files at their real paths relative to waybar/."""
    profile = Path(profile)
    script = r'''
. "$1"
. "$2/detect.sh"
. "$2/components.sh"
if [ "$3" != profile ]; then LABWC_WORKSPACE_COUNT=$3; fi
DIR_SCRIPTS_DESKTOP=$2
installer_repo_join_var() { printf '%s/%s\n' "$DIR_SCRIPTS_DESKTOP" "$2"; }
fetch_hook() { cp "$1" "$2"; }
desktop_fatal() { printf '%s\n' "$*" >&2; exit 1; }
desktop_render_role_target_template() { printf '%s\0' "$@"; printf '\0'; }
desktop_render_role_target_template_deferred() { desktop_render_role_target_template "$@"; }
desktop_assert_role_target_template_resolved() { :; }
desktop_log() { :; }
installer_warn() { :; }
desktop_render_waybar_config
desktop_render_waybar_style
for menu in audio bluetooth calendar notifications power screenshot system tomat; do
    desktop_render_waybar_asset "${menu}-menu.xml"
done
'''
    with tempfile.TemporaryDirectory() as tmp:
        response = subprocess.run(installed_argv([
            '/bin/sh','-eu','-c',script,'output-class-render',str(profile),
            str(FORKY/'scripts/desktop'),'profile' if count is None else str(count)]),
            env={'PATH':'/usr/bin:/bin','TMP_ENV_DIR':tmp},
            capture_output=True,check=True,timeout=15)
    result = {}
    for record in response.stdout.decode().split('\0\0'):
        if not record: continue
        fields=record.split('\0')
        source,dest,mode,*pairs=fields
        if len(pairs)%2: raise AssertionError('incomplete renderer record')
        values=dict(zip(pairs[::2],pairs[1::2]))
        text=render_theme_defaults(read_text(TARGET/source), dict(theme_items))
        text=re.sub(r'__INSTALLER_([A-Z0-9_]+)__',lambda m:values[m[1]],text)
        if '__INSTALLER_' in text or '__THEME_' in text:
            raise AssertionError('unresolved source '+source)
        relative = Path(dest).relative_to('/etc/skel-desktop/.config/waybar').as_posix()
        if relative == 'config' or relative.startswith('modules/'):
            def unique_keys(pairs):
                values = {}
                for key, value in pairs:
                    if key in values: raise AssertionError('duplicate Waybar key: ' + key)
                    values[key] = value
                return values
            json.loads(text, object_pairs_hook=unique_keys)
        if relative in result:
            raise AssertionError('duplicate rendered Waybar destination: ' + relative)
        result[relative]=text
    return result


def resolved_config(assets):
    """Apply Waybar's first-value-wins object merge to managed includes."""
    bars = json.loads(assets['config'])

    def merge(base, fragment):
        if not isinstance(base, dict) or not isinstance(fragment, dict):
            raise AssertionError('Waybar include must contain an object')
        for key, value in fragment.items():
            if key not in base:
                base[key] = value
            elif isinstance(base[key], dict) and isinstance(value, dict):
                merge(base[key], value)

    for bar in bars:
        for include in bar.pop('include', []):
            prefix = '~/.config/waybar/'
            if not include.startswith(prefix):
                raise AssertionError('unexpected Waybar include root')
            relative = include[len(prefix):]
            if not re.fullmatch(r'modules/[a-z-]+', relative):
                raise AssertionError('unsafe Waybar include')
            merge(bar, json.loads(assets[relative]))
    return bars


def rendered_assets(profile, count=None, theme_items=()):
    """Resolved fixture view; native_assets retains the actual file boundary."""
    assets = dict(native_assets(profile, count, theme_items))
    assets['config'] = json.dumps(resolved_config(assets), ensure_ascii=False)
    expression = re.compile(r'@import url\("([^"\n]+)"\);')

    def stylesheet(relative, active=()):
        if relative in active or len(active) > 8:
            raise AssertionError('recursive Waybar stylesheet import')
        def include(match):
            name = match[1]
            if not re.fullmatch(r'(?:style-common|(?:style|gtk)/[a-z-]+)\.css', name):
                raise AssertionError('unsafe Waybar stylesheet import')
            return stylesheet(name, (*active, relative))
        return expression.sub(include, assets[relative])

    assets['style.css'] = stylesheet('style.css')
    return assets

def profiles():
    return [p for p in sorted((FORKY/'hosts/profiles').glob('*.env'))
            if 'LABWC_WAYBAR_EXTERNAL_FONT_SIZE=' in p.read_text()]

def style(profile, output_class):
    assets=rendered_assets(profile)
    return assets['style.css']
