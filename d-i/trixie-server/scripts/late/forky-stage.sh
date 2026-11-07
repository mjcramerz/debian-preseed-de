#!/bin/sh
set -eu
umask 077

source_dir=${1:-}
target=${2:-/target}
[ -d "$source_dir" ] && [ ! -L "$source_dir" ] || {
  printf '%s\n' 'fatal: Forky bridge source directory is unavailable' >&2
  exit 1
}
[ -d "$target" ] && [ ! -L "$target" ] || {
  printf '%s\n' 'fatal: Forky bridge target directory is unavailable' >&2
  exit 1
}
[ "$target" = /target ] || {
  printf '%s\n' 'fatal: Forky late modules require the installer target at /target' >&2
  exit 1
}

# This bridge consumes the embedded Forky files as payload members. The payload
# manifest authenticates the complete Trixie archive before this stage runs;
# this bridge deliberately performs no second, per-file Forky hash check.
. "$source_dir/repo.env"
. "$source_dir/$DIR_HOSTS_INSTALLER/runtime.env"
. "$source_dir/$DIR_SCRIPTS_COMMON/credentials.sh"
. "$source_dir/$DIR_SCRIPTS_COMMON/validate.sh"
. "$source_dir/$DIR_SCRIPTS_COMMON/forky.sh"
. "$source_dir/$DIR_HOSTS_PROFILES/shared-srv.env"

classes=${PRESEED_SERVER_CLASSES:-}
if [ -z "$classes" ]; then
  classes=$(server_cmdline_value classes 2>/dev/null || true)
fi
if [ -z "$classes" ]; then
  . "$source_dir/repo.env"
  classes=$DEBIAN_DEFAULT_CLASSES
fi
classes=$(printf '%s\n' "$classes" | tr ';' ',')
profile=$(server_profile_from_classes "$classes" 2>/dev/null || true)
profile=${profile:-btrfs-srv-flex}
case "$profile" in
  btrfs-srv-flex|btrfs-srv-flex-duo|f2fs-srv-hp14) ;;
  *) server_fatal 'unknown server profile for Forky bridge'; exit 1 ;;
esac
. "$source_dir/$DIR_HOSTS_PROFILES/$profile.env"

forky_base=$(server_forky_source_base "$source_dir") || exit 1
INSTALLER_TARGET_DIR=$target
export INSTALLER_TARGET_DIR

# Compatibility adapters provide the installer contracts consumed by the
# existing Forky modules. They do not contain IOCost or scheduler policy.
installer_fatal() { server_fatal "$*"; exit 1; }
installer_error() { installer_fatal "$*"; }
installer_warn() { server_info "$*"; }
installer_info() { server_info "$*"; }
installer_log_record() { :; }
installer_repo_join_var() {
  [ "$1" = DIR_HOOKS_TARGET ] || installer_fatal "unsupported Forky repository variable: $1"
  leaf=${2:-}
  case "$leaf" in
    ''|/*|*..*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_./@+-]*)
      installer_fatal 'unsafe Forky target asset suffix' ;;
  esac
  printf '%s/%s/%s\n' "$forky_base" "$FORKY_HOOKS_TARGET" "$leaf"
}
fetch_hook() {
  source_path=$1
  destination=$2
  [ -f "$source_path" ] && [ ! -L "$source_path" ] || installer_fatal "Forky source file is unavailable: $source_path"
  cp -- "$source_path" "$destination"
}

# Reuse the existing Forky lifecycle, metadata, target execution, asset
# publication, and placeholder implementations. These files are embedded in
# the Trixie payload through forky-payload.list.
. "$forky_base/scripts/common/source.sh"
. "$forky_base/scripts/common/modules/files-logging.sh"
. "$forky_base/scripts/common/target.sh"
. "$forky_base/scripts/late/target-assets.sh"
. "$forky_base/scripts/late/templates.sh"
. "$forky_base/scripts/late/storage-maintenance.sh"
. "$forky_base/scripts/late/volatile-storage.sh"

# Forky’s resource policy functions name their rendered destinations while the
# immutable source tree stores the parameterized inputs with a .tmpl suffix.
# Resolve that source naming convention at the bridge boundary and keep the
# existing resource renderer and placeholder validation as the single policy
# implementation.
render_target_resource_asset() {
  resource_source=$1
  resource_target=$2
  resource_mode=$3
  if [ ! -f "$resource_source" ] || [ -L "$resource_source" ]; then
    case "$resource_source" in
      *.tmpl) installer_fatal "Forky resource source is unavailable: $resource_source" ;;
      *) resource_source="$resource_source.tmpl" ;;
    esac
  fi
  [ -f "$resource_source" ] && [ ! -L "$resource_source" ] ||
    installer_fatal "Forky resource source is unavailable: $resource_source"
  publish_target_asset "$resource_source" "$resource_target" "$resource_mode" resources
}

TMP_ENV_DIR=$(mktemp -d /tmp/server-forky-stage.XXXXXX)
cleanup_forky_stage() { rm -rf -- "$TMP_ENV_DIR"; }
trap cleanup_forky_stage EXIT HUP INT TERM
server_forky_fetch "$forky_base" hooks/target/usr/local/libexec/tmpfs-pre-clean.tmpl \
  "$TMP_ENV_DIR/tmpfs-pre-clean.tmpl" 0600
server_forky_fetch "$forky_base" hooks/target/etc/systemd/system/tmpfs-pre-clean.service.tmpl \
  "$TMP_ENV_DIR/tmpfs-pre-clean.service.tmpl" 0600

target_systemd_unit_path() {
  unit=$1
  scope=$2
  [ "$scope" = system ] || installer_fatal "Forky SCX bridge only supports system units"
  case "$unit" in
    scx.service|scx_loader.service) ;;
    *) installer_fatal "unexpected SCX unit: $unit" ;;
  esac
  for unit_dir in \
    "$target/etc/systemd/system" \
    "$target/usr/lib/systemd/system" \
    "$target/lib/systemd/system"
  do
    if [ -e "$unit_dir/$unit" ] || [ -L "$unit_dir/$unit" ]; then
      printf '%s\n' "$unit_dir/$unit"
      return 0
    fi
  done
  return 1
}

desktop_log() { server_info "$*"; }
desktop_stage_role_asset() {
  role_relpath=$1
  target_path=$2
  mode=$3
  source_path=$(installer_repo_join_var DIR_HOOKS_TARGET "$role_relpath")
  stage_target_asset "$source_path" "$target_path" "$mode"
}
desktop_enable_unit_if_available() {
  unit=$1
  scope=$2
  [ "$scope" = system ] || installer_fatal "Forky SCX bridge only supports system units"
  unit_path=$(target_systemd_unit_path "$unit" "$scope" 2>/dev/null || true)
  [ -n "$unit_path" ] || return 0
  /usr/bin/systemctl --root="$target" enable "$unit"
}
desktop_disable_unit_if_available() {
  unit=$1
  scope=$2
  [ "$scope" = system ] || installer_fatal "Forky SCX bridge only supports system units"
  unit_path=$(target_systemd_unit_path "$unit" "$scope" 2>/dev/null || true)
  [ -n "$unit_path" ] || return 0
  /usr/bin/systemctl --root="$target" disable "$unit"
}

# The existing Forky transaction handles both enabled calibration and a
# disabled policy, including restoration of native defaults when applicable.
stage_target_iocost

# Reuse Forky’s profile-driven resource accounting, journald, and tmpfs
# renderers. These consume the Trixie profile variables loaded above and keep
# resource behavior dynamic without adding desktop or Waybar components.
stage_target_systemd_resource_policy_assets
render_target_resource_asset \
  "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/journald.conf.d/10-storage.conf.tmpl)" \
  "$FILE_JOURNALD_STORAGE_CONF" 0644
validate_target_journal_storage_policy
install_target_tmpfs_pre_clean_assets
install_target_tmpfs_tmpfiles_assets

# The scheduler function is sourced from Forky and applies its existing
# profile validation, package-asset checks, mode selection, and enablement.
. "$forky_base/scripts/desktop/scx-scheds.sh"
desktop_install_scx_scheduler
