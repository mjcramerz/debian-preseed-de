#!/bin/sh
set -eu
umask 077

target_root=${1:-/target}
[ -d "$target_root" ] || exit 0

tailscale_fatal() {
  printf 'fatal: %s\n' "$*" >&2
  exit 1
}

tailscale_info() {
  printf '[late:tailscale] %s\n' "$*" >&2
}

tailscale_validate_abs_target_path() {
  case "${1:-}" in
    /*) ;;
    *) tailscale_fatal "target path must be absolute: ${1:-unset}" ;;
  esac
}

tailscale_validate_port() {
  label=$1
  value=$2
  case "$value" in
    ''|*[!0-9]*)
      tailscale_fatal "${label} must be a numeric TCP/UDP port"
      ;;
  esac
  [ "$value" -ge 1 ] && [ "$value" -le 65535 ] || tailscale_fatal "${label} must be in range 1..65535"
}

tailscale_validate_bool() {
  label=$1
  value=$2
  case "$value" in
    true|false) ;;
    *) tailscale_fatal "${label} must be true or false" ;;
  esac
}

tailscale_validate_iface_name() {
  label=$1
  value=$2
  case "$value" in
    ''|.|..|lo|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-]*)
      tailscale_fatal "${label} must be a non-loopback interface name"
      ;;
  esac
  [ "${#value}" -le 15 ] || tailscale_fatal "${label} must be 15 characters or fewer"
}

tailscale_normalize_token() {
  token_value=$1

  case "$token_value" in
    \"*\")
      token_value=${token_value#\"}
      token_value=${token_value%\"}
      ;;
    \'*\')
      token_value=${token_value#\'}
      token_value=${token_value%\'}
      ;;
  esac

  [ -n "$token_value" ] || tailscale_fatal "tailscale auth key must not be empty"
  case "$token_value" in
    *[![:print:]]*|*[[:space:]]*)
      tailscale_fatal "tailscale auth key must be a single printable token without whitespace"
      ;;
  esac
  printf '%s\n' "$token_value"
}

tailscale_cmdline_token() {
  token=
  for tailscale_token_key in tailscale_authkey tailscale_auth_key; do
    token=$(installer_cmdline_value "$tailscale_token_key" 2>/dev/null || true)
    [ -n "$token" ] && break
  done
  [ -n "$token" ] || return 1
  token=$(tailscale_normalize_token "$token")
  [ "${#token}" -le 512 ] || tailscale_fatal "tailscale_authkey must be 512 characters or fewer"
  printf '%s\n' "$token"
}

tailscale_stage_target_asset() {
  repo_path=$1
  target_path=$2
  mode=$3
  tmp_asset="${tmp_env_dir}/$(basename "$target_path").$$"
  target_host_path="${target_root}${target_path}"

  tailscale_validate_abs_target_path "$target_path"
  bootstrap_fetch_seed_file "$seed_base" "$repo_path" "$tmp_asset" 0600 "tailscale asset ${repo_path}"
  target_normalize_systemd_config_parent_modes "$target_path" "$target_root"
  install -d -m 0755 "${target_root}$(dirname "$target_path")"
  chmod 0755 "${target_root}$(dirname "$target_path")"
  install -m "$mode" "$tmp_asset" "$target_host_path"
  chmod "$mode" "$target_host_path"
  rm -f "$tmp_asset"
}

tailscale_render_target_asset() {
  repo_path=$1
  target_path=$2
  mode=$3
  shift 3
  tmp_asset="${tmp_env_dir}/$(basename "$target_path").src.$$"
  tmp_rendered="${tmp_env_dir}/$(basename "$target_path").out.$$"
  target_host_path="${target_root}${target_path}"

  tailscale_validate_abs_target_path "$target_path"
  bootstrap_fetch_seed_file "$seed_base" "$repo_path" "$tmp_asset" 0600 "tailscale template ${repo_path}"
  installer_apply_scalar_placeholders "$tmp_asset" "$tmp_rendered" "$@"
  if grep -Eq '__INSTALLER_[A-Z0-9_]+__' "$tmp_rendered"; then
    rm -f "$tmp_asset" "$tmp_rendered"
    tailscale_fatal "tailscale template rendered with unresolved placeholders: ${repo_path}"
  fi
  target_normalize_systemd_config_parent_modes "$target_path" "$target_root"
  install -d -m 0755 "${target_root}$(dirname "$target_path")"
  chmod 0755 "${target_root}$(dirname "$target_path")"
  install -m "$mode" "$tmp_rendered" "$target_host_path"
  chmod "$mode" "$target_host_path"
  rm -f "$tmp_asset" "$tmp_rendered"
}

tailscale_unstage_vendor_syncthing_unit() {
  account_user=$1
  for link_dir in "${target_root}/etc/systemd/system"/*.wants "${target_root}/etc/systemd/system"/*.requires; do
    [ -d "$link_dir" ] || continue
    rm -f "${link_dir}/syncthing@${account_user}.service"
  done
}

tailscale_stage_target_unit() {
  unit=$1
  if ! target_systemd_unit_path "$unit" system >/dev/null 2>&1; then
    tailscale_fatal "expected target systemd unit is missing: ${unit}"
  fi
  stage_target_systemd_unit_enabled "$unit" system
}

tailscale_run_target_chroot() {
  label=$1
  shift
  output="${tmp_env_dir}/chroot.$$.log"

  [ -x /usr/sbin/chroot ] || tailscale_fatal "installer chroot helper is unavailable"
  tailscale_info "target chroot: ${label}"
  if /usr/sbin/chroot "$target_root" "$@" >"$output" 2>&1; then
    rm -f "$output"
    return 0
  else
    code=$?
  fi

  cat "$output" >&2 || true
  rm -f "$output"
  tailscale_fatal "target chroot failed during ${label} (status ${code})"
}

runtime_dir=${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}
bootstrap_lib=${INSTALLER_BOOTSTRAP_LIB:-${runtime_dir}/bootstrap/bootstrap.sh}
tmp_env_dir=${INSTALLER_LATE_TMP_ENV_DIR:-/tmp/install-env-late/tailscale}

[ -s "$bootstrap_lib" ] || tailscale_fatal "installer bootstrap library is unavailable: ${bootstrap_lib}"
# shellcheck disable=SC1090,SC1091
. "$bootstrap_lib"
bootstrap_source_common_lib ""
seed_base=$(installer_current_seed_base 2>/dev/null || installer_seed_base "")
bootstrap_source_common_support_libs "$seed_base" "$tmp_env_dir" fetch hook target || {
  tailscale_fatal "failed to source installer late support libraries"
}
installer_ensure_context_loaded "$seed_base"

installer_selected_class_reference_is_selected addon/tailscale 2>/dev/null || exit 0

host_profile=${INSTALLER_HOST_PROFILE:-$(installer_resolve_host_profile "" 2>/dev/null || true)}
[ -n "$host_profile" ] || tailscale_fatal "selected host profile is unavailable for tailscale helper"

host_env=/tmp/install-env-late/host.env
account_env=/tmp/install-env-late/account.env
runtime_common=/tmp/install-env-late/runtime-common.sh
account_runtime=/tmp/install-env-late/account-runtime.sh
[ -r "$host_env" ] || installer_fetch_host_env "$seed_base" "$host_profile" "$host_env" 0600
[ -r "$account_env" ] || installer_fetch_account_env "$seed_base" "$account_env" 0600
[ -r "$runtime_common" ] || fetch_hook_file "$(installer_repo_join_var DIR_SCRIPTS_RUNTIME common.sh)" "$runtime_common"
[ -r "$account_runtime" ] || fetch_hook_file "$(installer_repo_join_var DIR_SCRIPTS_RUNTIME account.sh)" "$account_runtime"
runtime_env_file=${INSTALLER_RUNTIME_ENV_FILE:-/tmp/install-env/runtime.env}
if [ ! -r "$runtime_env_file" ]; then
  runtime_env_file="${INSTALLER_RUNTIME_STATE_DIR:-$(installer_runtime_state_dir)}/runtime.env"
fi
[ -r "$runtime_env_file" ] || tailscale_fatal "runtime env is unavailable for tailscale helper: ${runtime_env_file}"
dbus_helper="${tmp_env_dir}/dbus-broker.sh"
[ -r "$dbus_helper" ] || fetch_hook_file "$(installer_repo_join_var DIR_SCRIPTS_LATE dbus-broker.sh)" "$dbus_helper"

# shellcheck disable=SC1090,SC1091
. "$host_env"
# shellcheck disable=SC1090,SC1091
. "$account_env"
# shellcheck disable=SC1090,SC1091
. "$runtime_env_file"
RUNTIME_COMMON_LIB=$runtime_common
export RUNTIME_COMMON_LIB
# shellcheck disable=SC1090,SC1091
. "$account_runtime"
# shellcheck disable=SC1090,SC1091
. "$dbus_helper"
runtime_apply_account_from_cmdline

tailscale_validate_port TAILSCALE_UDP_PORT "${TAILSCALE_UDP_PORT:-41641}"
tailscale_validate_port SYNCTHING_TCP_PORT "${SYNCTHING_TCP_PORT:-35000}"
tailscale_validate_bool TAILSCALE_RUN_SSH_SERVER "${TAILSCALE_RUN_SSH_SERVER:-true}"
tailscale_validate_bool TAILSCALE_AUTH_KEY_REQUIRED "${TAILSCALE_AUTH_KEY_REQUIRED:-true}"
tailscale_interface=${TAILSCALE_INTERFACE:-tailscale0}
tailscale_validate_iface_name TAILSCALE_INTERFACE "$tailscale_interface"
tailscale_interface_log_regex=$(printf '%s\n' "$tailscale_interface" | sed 's/[.]/[.]/g')

: "${FILE_TAILSCALED_DEFAULT:?FILE_TAILSCALED_DEFAULT must be set}"
: "${FILE_TAILSCALE_MANAGED_DEFAULT:?FILE_TAILSCALE_MANAGED_DEFAULT must be set}"
: "${FILE_TAILSCALE_MANAGED_HELPER:?FILE_TAILSCALE_MANAGED_HELPER must be set}"
: "${FILE_TAILSCALE_BOOTSTRAP_SERVICE:?FILE_TAILSCALE_BOOTSTRAP_SERVICE must be set}"
: "${FILE_TAILSCALED_SERVICE_OVERRIDE:?FILE_TAILSCALED_SERVICE_OVERRIDE must be set}"
: "${FILE_TAILSCALE_TUN_MODULES_LOAD:?FILE_TAILSCALE_TUN_MODULES_LOAD must be set}"
: "${FILE_TAILSCALE_AUTH_KEY:?FILE_TAILSCALE_AUTH_KEY must be set}"
: "${FILE_TAILSCALE_COMPLETE:?FILE_TAILSCALE_COMPLETE must be set}"
: "${FILE_TAILSCALE_STATUS:?FILE_TAILSCALE_STATUS must be set}"
: "${FILE_TAILSCALE_LOG:?FILE_TAILSCALE_LOG must be set}"
: "${FILE_MANAGED_SYNCTHING_DEFAULT:?FILE_MANAGED_SYNCTHING_DEFAULT must be set}"
: "${FILE_MANAGED_SYNCTHING_HELPER:?FILE_MANAGED_SYNCTHING_HELPER must be set}"
: "${FILE_MANAGED_SYNCTHING_SERVICE:?FILE_MANAGED_SYNCTHING_SERVICE must be set}"

auth_key_file=$FILE_TAILSCALE_AUTH_KEY
complete_file=$FILE_TAILSCALE_COMPLETE
status_file=$FILE_TAILSCALE_STATUS
log_file=$FILE_TAILSCALE_LOG

install -d -m 0700 \
  "${target_root}$(dirname "$auth_key_file")" \
  "${target_root}$(dirname "$complete_file")" \
  "${target_root}$(dirname "$status_file")" \
  "${target_root}$(dirname "$log_file")"

if auth_key=$(tailscale_cmdline_token 2>/dev/null); then
  printf '%s\n' "$auth_key" >"${target_root}${auth_key_file}"
  chmod 0600 "${target_root}${auth_key_file}" 2>/dev/null || true
  tailscale_info "staged optional Tailscale auth key for deferred post-boot bootstrap"
else
  rm -f "${target_root}${auth_key_file}"
  if [ "${TAILSCALE_AUTH_KEY_REQUIRED:-true}" = true ]; then
    tailscale_fatal "tailscale_authkey is required when addon/tailscale is selected for unattended provisioning"
  fi
  tailscale_info "tailscale_authkey not provided on kernel cmdline or in /preseed.env; deferred join stays manual"
fi
unset auth_key 2>/dev/null || true

{
  write_shell_config_var PORT "${TAILSCALE_UDP_PORT:-41641}"
  # This is Tailscale's supported upload opt-out. It intentionally disables
  # Tailscale technical support and is incompatible with tailnets that require
  # data-plane audit logging, but it does not replace or disable local journal
  # diagnostics, control connectivity, DERP, or direct peer transport.
  write_shell_config_var FLAGS "--tun=${tailscale_interface} --no-logs-no-support"
} >"${target_root}${FILE_TAILSCALED_DEFAULT}"
chmod 0644 "${target_root}${FILE_TAILSCALED_DEFAULT}" 2>/dev/null || true

tailscale_stage_target_asset \
  "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/libexec/tailscale-managed-up)" \
  "${FILE_TAILSCALE_MANAGED_HELPER}" \
  0755
tailscale_stage_target_asset \
  "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/system/tailscale-managed-bootstrap.service)" \
  "${FILE_TAILSCALE_BOOTSTRAP_SERVICE}" \
  0644
tailscale_render_target_asset \
  "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/system/tailscaled.service.d/override.conf.tmpl)" \
  "${FILE_TAILSCALED_SERVICE_OVERRIDE}" \
  0644 \
  TAILSCALE_INTERFACE_REGEX "$tailscale_interface_log_regex"
tailscale_stage_target_asset \
  "$(installer_repo_join_var DIR_HOOKS_TARGET etc/modules-load.d/50-tailscale.conf)" \
  "${FILE_TAILSCALE_TUN_MODULES_LOAD}" \
  0644
tailscale_stage_target_asset \
  "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/libexec/managed-syncthing-configure)" \
  "${FILE_MANAGED_SYNCTHING_HELPER}" \
  0755
tailscale_render_target_asset \
  "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/system/managed-syncthing.service.tmpl)" \
  "${FILE_MANAGED_SYNCTHING_SERVICE}" \
  0644 \
  ACCOUNT_USERNAME "$ACCOUNT_USERNAME" \
  ACCOUNT_HOME "$ACCOUNT_HOME" \
  DIR_HOME_SYNCTHING "$DIR_HOME_SYNCTHING" \
  DIR_HOME_SYNCTHING_STATE "$DIR_HOME_SYNCTHING_STATE"

{
  write_shell_config_var TAILSCALE_AUTH_KEY_FILE "$auth_key_file"
  write_shell_config_var TAILSCALE_COMPLETE_FILE "$complete_file"
  write_shell_config_var TAILSCALE_STATUS_FILE "$status_file"
  write_shell_config_var TAILSCALE_LOG_FILE "$log_file"
  write_shell_config_var TAILSCALE_HOSTNAME "$SYSTEM_HOSTNAME"
  write_shell_config_var TAILSCALE_INTERFACE "$tailscale_interface"
  write_shell_config_var TAILSCALE_UDP_PORT "${TAILSCALE_UDP_PORT:-41641}"
  write_shell_config_var TAILSCALE_ACCEPT_DNS "${TAILSCALE_ACCEPT_DNS:-false}"
  write_shell_config_var TAILSCALE_ACCEPT_ROUTES "${TAILSCALE_ACCEPT_ROUTES:-false}"
  write_shell_config_var TAILSCALE_RUN_SSH_SERVER "${TAILSCALE_RUN_SSH_SERVER:-true}"
  write_shell_config_var TAILSCALE_NETFILTER_MODE "${TAILSCALE_NETFILTER_MODE:-off}"
  write_shell_config_var TAILSCALE_OPERATOR_USER "${TAILSCALE_OPERATOR_USER:-$ACCOUNT_USERNAME}"
  write_shell_config_var TAILSCALE_ACCEPT_RISK "${TAILSCALE_ACCEPT_RISK:-}"
  write_shell_config_var TAILSCALE_ADVERTISE_TAGS "${TAILSCALE_ADVERTISE_TAGS:-}"
  write_shell_config_var TAILSCALE_ADVERTISE_ROUTES "${TAILSCALE_ADVERTISE_ROUTES:-}"
  write_shell_config_var TAILSCALE_ADVERTISE_EXIT_NODE "${TAILSCALE_ADVERTISE_EXIT_NODE:-false}"
  write_shell_config_var TAILSCALE_EXIT_NODE "${TAILSCALE_EXIT_NODE:-}"
  write_shell_config_var TAILSCALE_EXIT_NODE_ALLOW_LAN_ACCESS "${TAILSCALE_EXIT_NODE_ALLOW_LAN_ACCESS:-false}"
  write_shell_config_var TAILSCALE_SHIELDS_UP "${TAILSCALE_SHIELDS_UP:-false}"
  write_shell_config_var TAILSCALE_REPORT_POSTURE "${TAILSCALE_REPORT_POSTURE:-false}"
  write_shell_config_var TAILSCALE_SNAT_SUBNET_ROUTES "${TAILSCALE_SNAT_SUBNET_ROUTES:-true}"
  write_shell_config_var TAILSCALE_STATEFUL_FILTERING "${TAILSCALE_STATEFUL_FILTERING:-false}"
  write_shell_config_var TAILSCALE_AUTH_KEY_REQUIRED "${TAILSCALE_AUTH_KEY_REQUIRED:-true}"
  write_shell_config_var TAILSCALE_FORCE_REAUTH "${TAILSCALE_FORCE_REAUTH:-false}"
  write_shell_config_var TAILSCALE_TIMEOUT "${TAILSCALE_TIMEOUT:-2m}"
  write_shell_config_var TAILSCALE_DAEMON_WAIT_SECONDS "${TAILSCALE_DAEMON_WAIT_SECONDS:-60}"
} >"${target_root}${FILE_TAILSCALE_MANAGED_DEFAULT}"
chmod 0644 "${target_root}${FILE_TAILSCALE_MANAGED_DEFAULT}" 2>/dev/null || true

{
  write_shell_config_var SYNCTHING_TCP_PORT "${SYNCTHING_TCP_PORT:-35000}"
  write_shell_config_var SYNCTHING_USER "$ACCOUNT_USERNAME"
  write_shell_config_var SYNCTHING_DATA_DIR "$DIR_HOME_SYNCTHING"
  write_shell_config_var SYNCTHING_STATE_DIR "$DIR_HOME_SYNCTHING_STATE"
  write_shell_config_var SYNCTHING_GUI_ENABLED false
} >"${target_root}${FILE_MANAGED_SYNCTHING_DEFAULT}"
chmod 0644 "${target_root}${FILE_MANAGED_SYNCTHING_DEFAULT}" 2>/dev/null || true

tailscale_run_target_chroot "prepare managed syncthing state during install" /bin/sh -eu -c '
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH
test -r /usr/local/libexec/managed-syncthing-configure
/usr/sbin/runuser -u "$1" -- /usr/local/libexec/managed-syncthing-configure --prepare
' sh "$ACCOUNT_USERNAME"

tailscale_unstage_vendor_syncthing_unit "$ACCOUNT_USERNAME"
tailscale_stage_target_unit tailscaled.service
tailscale_stage_target_unit tailscale-managed-bootstrap.service
tailscale_stage_target_unit managed-syncthing.service

tailscale_info "staged Tailscale + Syncthing target assets for account=${ACCOUNT_USERNAME}"
