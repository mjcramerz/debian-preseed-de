"""Render the real output-class assets; stub transport/publishing, not policy."""
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
def rendered_assets(profile, count=None, theme_items=()):
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
for menu in audio calendar notifications power tomat; do
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
        if Path(dest).name == 'config':
            def unique_keys(pairs):
                values = {}
                for key, value in pairs:
                    if key in values: raise AssertionError('duplicate Waybar key: ' + key)
                    values[key] = value
                return values
            json.loads(text, object_pairs_hook=unique_keys)
        result[Path(dest).name]=text
    return result

def profiles():
    return [p for p in sorted((FORKY/'hosts/profiles').glob('*.env'))
            if 'LABWC_WAYBAR_EXTERNAL_FONT_SIZE=' in p.read_text()]

def style(profile, output_class):
    assets=rendered_assets(profile)
    return assets['style.css']
