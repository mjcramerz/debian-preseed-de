#!/bin/sh
# Test-only transport fixture; renderer and replacement functions are production.
set -eu
repo=$1
destination=$2
LABWC_WORKSPACE_COUNT=${3:-4}
LABWC_WINDOW_SWITCHER_STYLE=${4:-thumbnail}
. "$repo/d-i/forky/scripts/common/lib.sh"
. "$repo/d-i/forky/scripts/common/target.sh"
. "$repo/d-i/forky/scripts/late/target-assets.sh"
. "$repo/d-i/forky/scripts/desktop/detect.sh.tmpl"
. "$repo/d-i/forky/scripts/desktop/components.sh.tmpl"
INSTALLER_TARGET_DIR=$destination
TMP_ENV_DIR=$destination/tmp
mkdir -p "$TMP_ENV_DIR"
installer_repo_join_var() {
  case "$1" in
    DIR_HOOKS_TARGET) printf '%s/d-i/forky/hooks/target/%s\n' "$repo" "$2" ;;
    DIR_SCRIPTS_DESKTOP) printf '%s/d-i/forky/scripts/desktop/%s\n' "$repo" "$2" ;;
    *) return 1 ;;
  esac
}
fetch_hook() { cp "$1" "$2"; }
desktop_log() { :; }
installer_log() { :; }
installer_warn() { printf "%s\n" "$*" >&2; }
installer_fatal() { printf '%s\n' "$*" >&2; exit 1; }
# Load only output-class geometry from a real profile; unrelated fixture
# overrides for the workspace switcher remain explicit test inputs.
while IFS= read -r assignment; do
  case "$assignment" in LABWC_OUTPUT_INTERNAL_PREFIXES=*|LABWC_WAYBAR_INTERNAL_*=*|LABWC_WAYBAR_EXTERNAL_*=*) eval "$assignment" ;; esac
done < "$repo/d-i/forky/hosts/profiles/btrfs-de.env"
LABWC_DESKTOP_GTK_ICON_THEME=Papirus-Dark
LABWC_MANAGED_APP_DEFAULT_EXEC=foot
# A feature selector is transport context, not part of rendering itself.
installer_selected_class_reference_is_selected() { return 1; }
desktop_render_labwc_rc_xml
desktop_render_waybar_config
desktop_render_waybar_style
