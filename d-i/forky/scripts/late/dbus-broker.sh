#!/bin/sh
# Shared late_command dbus-broker helpers. This file is sourced, not executed.

validate_dbus_target_path() {
  label=$1
  value=$2

  case "$value" in
    /*) ;;
    *) installer_fatal "${label} must be an absolute target path, got '${value}'" ;;
  esac
  case "$value" in
    /|*..*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/@:+%=-]*)
      installer_fatal "${label} contains unsupported path syntax: ${value}"
      ;;
  esac
}

require_uint_range() {
  label=$1
  value=$2
  min=$3
  max=$4

  case "$value" in
    ''|*[!0123456789]*)
      installer_fatal "${label} must be an integer, got '${value}'"
      ;;
  esac
  [ "$value" -ge "$min" ] || installer_fatal "${label} must be >= ${min}, got ${value}"
  [ "$value" -le "$max" ] || installer_fatal "${label} must be <= ${max}, got ${value}"
}

validate_dbus_broker_policy_env() {
  for dir_var in DIR_DBUS_SESSION_SERVICES DIR_DBUS_LOCAL_SESSION_SERVICES; do
    eval "dir_value=\${$dir_var-}"
    [ -n "$dir_value" ] || installer_fatal "${dir_var} must be set"
    validate_dbus_target_path "$dir_var" "$dir_value"
  done

  for path_var in \
    FILE_DBUS_BLOCKED_PACKAGES_APT_PREFERENCE \
    FILE_DBUS_SYSTEM_LOCAL_CONF \
    FILE_DBUS_SYSTEM_CONF \
    FILE_DBUS_SYSTEM_SERVICE_ALIAS \
    FILE_DBUS_USER_SERVICE_ALIAS \
    FILE_DBUS_SYSTEM_BROKER_SERVICE_OVERRIDE \
    FILE_DBUS_USER_BROKER_SERVICE_OVERRIDE \
    FILE_DBUS_BROKER_BINARY \
    FILE_DBUS_BROKER_LAUNCH_BINARY
  do
    eval "path_value=\${$path_var-}"
    [ -n "$path_value" ] || installer_fatal "${path_var} must be set"
    validate_dbus_target_path "$path_var" "$path_value"
  done

  require_uint_range DBUS_LIMIT_MAX_INCOMING_BYTES "${DBUS_LIMIT_MAX_INCOMING_BYTES:-}" 1048576 134217728
  require_uint_range DBUS_LIMIT_MAX_OUTGOING_BYTES "${DBUS_LIMIT_MAX_OUTGOING_BYTES:-}" 1048576 134217728
  require_uint_range DBUS_LIMIT_MAX_MESSAGE_SIZE "${DBUS_LIMIT_MAX_MESSAGE_SIZE:-}" 1024 33554432
  require_uint_range DBUS_LIMIT_MAX_MESSAGE_UNIX_FDS "${DBUS_LIMIT_MAX_MESSAGE_UNIX_FDS:-}" 0 1024
  require_uint_range DBUS_LIMIT_MAX_INCOMING_UNIX_FDS "${DBUS_LIMIT_MAX_INCOMING_UNIX_FDS:-}" 0 1024
  require_uint_range DBUS_LIMIT_MAX_OUTGOING_UNIX_FDS "${DBUS_LIMIT_MAX_OUTGOING_UNIX_FDS:-}" 0 1024
  require_uint_range DBUS_LIMIT_MAX_MATCH_RULES_PER_CONNECTION "${DBUS_LIMIT_MAX_MATCH_RULES_PER_CONNECTION:-}" 1 65536
  require_uint_range DBUS_LIMIT_MAX_NAMES_PER_CONNECTION "${DBUS_LIMIT_MAX_NAMES_PER_CONNECTION:-}" 1 1024
  require_uint_range DBUS_LIMIT_MAX_REPLIES_PER_CONNECTION "${DBUS_LIMIT_MAX_REPLIES_PER_CONNECTION:-}" 1 4096
  require_uint_range DBUS_LIMIT_MAX_INCOMPLETE_CONNECTIONS "${DBUS_LIMIT_MAX_INCOMPLETE_CONNECTIONS:-}" 1 4096
  require_uint_range DBUS_LIMIT_MAX_COMPLETED_CONNECTIONS "${DBUS_LIMIT_MAX_COMPLETED_CONNECTIONS:-}" 16 65536
  require_uint_range DBUS_LIMIT_MAX_CONNECTIONS_PER_USER "${DBUS_LIMIT_MAX_CONNECTIONS_PER_USER:-}" 1 4096
  require_uint_range DBUS_LIMIT_MAX_PENDING_SERVICE_STARTS "${DBUS_LIMIT_MAX_PENDING_SERVICE_STARTS:-}" 1 4096
  require_uint_range DBUS_LIMIT_AUTH_TIMEOUT_MS "${DBUS_LIMIT_AUTH_TIMEOUT_MS:-}" 1000 600000
  require_uint_range DBUS_LIMIT_PENDING_FD_TIMEOUT_MS "${DBUS_LIMIT_PENDING_FD_TIMEOUT_MS:-}" 1000 600000
  require_uint_range DBUS_LIMIT_SERVICE_START_TIMEOUT_MS "${DBUS_LIMIT_SERVICE_START_TIMEOUT_MS:-}" 1000 600000
  require_uint_range DBUS_LIMIT_REPLY_TIMEOUT_MS "${DBUS_LIMIT_REPLY_TIMEOUT_MS:-}" 1000 600000

  [ "$DBUS_LIMIT_MAX_MESSAGE_SIZE" -le "$DBUS_LIMIT_MAX_INCOMING_BYTES" ] || \
    installer_fatal "DBUS_LIMIT_MAX_MESSAGE_SIZE must not exceed DBUS_LIMIT_MAX_INCOMING_BYTES"
  [ "$DBUS_LIMIT_MAX_MESSAGE_SIZE" -le "$DBUS_LIMIT_MAX_OUTGOING_BYTES" ] || \
    installer_fatal "DBUS_LIMIT_MAX_MESSAGE_SIZE must not exceed DBUS_LIMIT_MAX_OUTGOING_BYTES"
  [ "$DBUS_LIMIT_MAX_MESSAGE_UNIX_FDS" -le "$DBUS_LIMIT_MAX_INCOMING_UNIX_FDS" ] || \
    installer_fatal "DBUS_LIMIT_MAX_MESSAGE_UNIX_FDS must not exceed DBUS_LIMIT_MAX_INCOMING_UNIX_FDS"
  [ "$DBUS_LIMIT_MAX_MESSAGE_UNIX_FDS" -le "$DBUS_LIMIT_MAX_OUTGOING_UNIX_FDS" ] || \
    installer_fatal "DBUS_LIMIT_MAX_MESSAGE_UNIX_FDS must not exceed DBUS_LIMIT_MAX_OUTGOING_UNIX_FDS"

  require_uint_range DBUS_BROKER_TASKS_MAX "${DBUS_BROKER_TASKS_MAX:-}" 64 8192
  require_uint_range DBUS_BROKER_LIMIT_NOFILE "${DBUS_BROKER_LIMIT_NOFILE:-}" 1024 1048576
}

dbus_broker_placeholder_map() {
  for var_name in \
    DBUS_LIMIT_MAX_INCOMING_BYTES \
    DBUS_LIMIT_MAX_OUTGOING_BYTES \
    DBUS_LIMIT_MAX_MESSAGE_SIZE \
    DBUS_LIMIT_MAX_MESSAGE_UNIX_FDS \
    DBUS_LIMIT_MAX_INCOMING_UNIX_FDS \
    DBUS_LIMIT_MAX_OUTGOING_UNIX_FDS \
    DBUS_LIMIT_MAX_MATCH_RULES_PER_CONNECTION \
    DBUS_LIMIT_MAX_NAMES_PER_CONNECTION \
    DBUS_LIMIT_MAX_REPLIES_PER_CONNECTION \
    DBUS_LIMIT_MAX_INCOMPLETE_CONNECTIONS \
    DBUS_LIMIT_MAX_COMPLETED_CONNECTIONS \
    DBUS_LIMIT_MAX_CONNECTIONS_PER_USER \
    DBUS_LIMIT_MAX_PENDING_SERVICE_STARTS \
    DBUS_LIMIT_AUTH_TIMEOUT_MS \
    DBUS_LIMIT_PENDING_FD_TIMEOUT_MS \
    DBUS_LIMIT_SERVICE_START_TIMEOUT_MS \
    DBUS_LIMIT_REPLY_TIMEOUT_MS \
    DBUS_BROKER_TASKS_MAX \
    DBUS_BROKER_LIMIT_NOFILE
  do
    eval "var_value=\${$var_name-}"
    [ -n "$var_value" ] || installer_fatal "${var_name} must be set before D-Bus template rendering"
    printf '%s=%s\n' "$var_name" "$var_value"
  done
}

render_target_asset_with_placeholders() {
  render_target_asset_with_placeholder_map "$1" "$2" "$3" "$4"
}

render_dbus_target_asset() {
  render_target_asset_with_placeholders "$1" "$2" "$3" dbus_broker_placeholder_map
}


repair_target_dbus_broker_packages() {
  require_in_target "dbus-broker package repair"

  prepare_target_volatile_dirs_for_apt
  run_in_target "install dbus-broker target packages" \
    env DEBIAN_FRONTEND=noninteractive DEBCONF_NONINTERACTIVE_SEEN=true \
    apt-get \
      -o Acquire::Retries=5 \
      -o Acquire::http::Timeout=45 \
      -o Acquire::https::Timeout=45 \
      -o Binary::apt::APT::Keep-Downloaded-Packages=false \
      -o DPkg::Use-Pty=0 \
      -y --no-remove install --no-install-recommends --no-install-suggests \
        dbus-broker \
        dbus-user-session \
        dbus-bin \
        dbus-system-bus-common \
        dbus-session-bus-common

  # dpkg removes ONLY this explicit set and enforces dependencies. Unlike
  # apt-get purge, it cannot solve a conflict by silently removing desktop apps.
  run_in_target "purge only reference D-Bus daemon packages if present" \
    env DEBIAN_FRONTEND=noninteractive DEBCONF_NONINTERACTIVE_SEEN=true \
    dpkg --purge dbus dbus-daemon dbus-x11

}

# Configuration and aliases share one upgrade-safe, locked implementation.
# Keep these entry points for callers outside configure_target_dbus_broker.
stage_target_dbus_session_service_aliases() {
  run_in_target "refresh broker compatibility files" /usr/local/libexec/dbus-broker-maintain --configure
}

sanitize_target_dbus_session_conf() {
  stage_target_dbus_session_service_aliases
}


target_user_unit_exists() {
  unit=$1

  target_systemd_unit_path "$unit" user >/dev/null 2>&1
}

validate_systemd_unit_name() {
  systemd_unit_name=$1

  case "$systemd_unit_name" in
    ''|/*|*/*|*..*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.@:-]*)
      installer_fatal "unsafe systemd unit name for staged enablement: ${systemd_unit_name}"
      ;;
  esac
}

target_systemd_scope_base_dir() {
  case "$1" in
    system) printf '%s\n' "${DIR_SYSTEMD_SYSTEM}" ;;
    user) printf '%s\n' "${DIR_SYSTEMD_USER}" ;;
    *) installer_fatal "unsupported systemd scope for staged enablement: $1" ;;
  esac
}

target_systemd_scope_unit_dirs() {
  case "$1" in
    system)
      printf '%s\n' "${DIR_SYSTEMD_SYSTEM}"
      printf '%s\n' "${DIR_SYSTEMD_SYSTEM_LEGACY}"
      printf '%s\n' "${DIR_SYSTEMD_SYSTEM_LIB}"
      ;;
    user)
      printf '%s\n' "${DIR_SYSTEMD_USER}"
      printf '%s\n' "${DIR_SYSTEMD_USER_LEGACY}"
      printf '%s\n' "${DIR_SYSTEMD_USER_LIB}"
      ;;
    *)
      installer_fatal "unsupported systemd scope for staged unit lookup: $1"
      ;;
  esac
}

target_systemd_unit_path_allowed() {
  unit_path=$1
  scope=$2

  case "$scope" in
    system)
      case "$unit_path" in
        "${DIR_SYSTEMD_SYSTEM}"/*|"${DIR_SYSTEMD_SYSTEM_LEGACY}"/*|"${DIR_SYSTEMD_SYSTEM_LIB}"/*)
          return 0
          ;;
      esac
      ;;
    user)
      case "$unit_path" in
        "${DIR_SYSTEMD_USER}"/*|"${DIR_SYSTEMD_USER_LEGACY}"/*|"${DIR_SYSTEMD_USER_LIB}"/*)
          return 0
          ;;
      esac
      ;;
  esac

  return 1
}

target_systemd_normalize_unit_path() {
  unit_path=$1
  target_systemd_normalized_unit_path=
  normalized=$(readlink -f "/target${unit_path}" 2>/dev/null || true)

  case "$normalized" in
    /target/*)
      target_systemd_normalized_unit_path=${normalized#/target}
      return 0
      ;;
  esac

  return 1
}

target_systemd_resolve_unit_path() {
  unit_path=$1
  scope=$2
  resolve_depth=0
  target_systemd_resolved_unit_path=

  target_systemd_unit_path_allowed "$unit_path" "$scope" || \
    installer_fatal "target systemd unit path escapes ${scope} scope: ${unit_path}"
  if target_systemd_normalize_unit_path "$unit_path"; then
    unit_path=$target_systemd_normalized_unit_path
    target_systemd_unit_path_allowed "$unit_path" "$scope" || \
      installer_fatal "target systemd unit path escapes ${scope} scope after normalization: ${unit_path}"
  fi

  while [ -L "/target${unit_path}" ]; do
    [ "$resolve_depth" -lt 16 ] || installer_fatal "too many target systemd unit symlink hops: ${unit_path}"
    link_target=$(readlink "/target${unit_path}") || \
      installer_fatal "unable to read target systemd unit symlink: ${unit_path}"
    case "$link_target" in
      ''|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_./@:-]*)
        installer_fatal "unsafe target systemd unit symlink target for ${unit_path}: ${link_target}"
        ;;
      /*)
        next_unit_path=$link_target
        ;;
      *)
        next_unit_path=${unit_path%/*}/${link_target}
        ;;
    esac
    case "$next_unit_path" in
      /*) ;;
      *) installer_fatal "resolved target systemd unit path is not absolute: ${next_unit_path}" ;;
    esac
    if target_systemd_normalize_unit_path "$next_unit_path"; then
      unit_path=$target_systemd_normalized_unit_path
    else
      case "$next_unit_path" in
        *..*)
          installer_fatal "unable to normalize relative target systemd unit symlink: ${next_unit_path}"
          ;;
        *)
          unit_path=$next_unit_path
          ;;
      esac
    fi
    target_systemd_unit_path_allowed "$unit_path" "$scope" || \
      installer_fatal "target systemd unit symlink escapes ${scope} scope: ${unit_path}"
    validate_systemd_unit_name "${unit_path##*/}"
    resolve_depth=$((resolve_depth + 1))
  done

  [ -e "/target${unit_path}" ] || return 1
  target_systemd_resolved_unit_path=$unit_path
  return 0
}

target_systemd_unit_path() {
  unit=$1
  scope=$2

  validate_systemd_unit_name "$unit"
  for unit_dir in $(target_systemd_scope_unit_dirs "$scope"); do
    [ -n "$unit_dir" ] || continue
    unit_path="${unit_dir}/${unit}"
    if [ -e "/target${unit_path}" ] || [ -L "/target${unit_path}" ]; then
      if target_systemd_resolve_unit_path "$unit_path" "$scope"; then
        printf '%s\n' "$target_systemd_resolved_unit_path"
        return 0
      fi
    fi
  done
  return 1
}

target_systemd_install_values() {
  unit_path=$1
  key=$2

  [ -r "/target${unit_path}" ] || installer_fatal "target systemd unit is unreadable: ${unit_path}"
  in_install=false
  while IFS= read -r unit_line || [ -n "$unit_line" ]; do
    unit_line=$(printf '%s' "$unit_line" | sed 's/\r$//')
    unit_trimmed=$(installer_trim_whitespace "$unit_line")
    case "$unit_trimmed" in
      \[*\])
        [ "$unit_trimmed" = "[Install]" ] && in_install=true || in_install=false
        continue
        ;;
    esac
    [ "$in_install" = true ] || continue
    value_line=$(printf '%s\n' "$unit_line" | sed -n "s/^[[:space:]]*${key}[[:space:]]*=[[:space:]]*//p")
    [ -n "$value_line" ] || continue
    value_line=$(printf '%s' "$value_line" | sed 's/[[:space:]]*[#;].*$//')
    for value in $value_line; do
      printf '%s\n' "$value"
    done
  done <"/target${unit_path}"
}

stage_target_atomic_unit_symlink() (
  set -eu
  link_source=$1
  link_destination=$2
  [ ! -d "$link_destination" ] || { installer_fatal "systemd link is a directory: $link_destination"; exit 1; }
  link_work=$(mktemp -d "$(dirname "$link_destination")/.installer-link.XXXXXX") || exit 1
  trap 'rm -rf -- "$link_work"' EXIT
  trap 'exit 129' HUP
  trap 'exit 130' INT
  trap 'exit 143' TERM
  ln -s "$link_source" "$link_work/link" || exit 1
  mv -fT -- "$link_work/link" "$link_destination"
)

stage_target_systemd_unit_enabled() (
  unit=$1
  scope=${2:-system}
  enable_chain=${3:-}
  case " $enable_chain " in *" $scope:$unit "*)
    installer_fatal "cyclic systemd Also= chain: $enable_chain $scope:$unit"; exit 1 ;; esac
  [ "${#enable_chain}" -lt 8192 ] || { installer_fatal "systemd Also= chain is too large"; exit 1; }
  enable_chain="$enable_chain $scope:$unit"
  unit_path=$(target_systemd_unit_path "$unit" "$scope" || true)
  base_dir=$(target_systemd_scope_base_dir "$scope")
  staged=false

  [ -n "$unit_path" ] || installer_fatal "expected target ${scope} unit is missing: ${unit}"

  for wanted_by in $(target_systemd_install_values "$unit_path" WantedBy); do
    validate_systemd_unit_name "$wanted_by"
    install -d -m 0755 "/target${base_dir}/${wanted_by}.wants"
    stage_target_atomic_unit_symlink "$unit_path" "/target${base_dir}/${wanted_by}.wants/${unit}" || exit 1
    staged=true
  done

  for required_by in $(target_systemd_install_values "$unit_path" RequiredBy); do
    validate_systemd_unit_name "$required_by"
    install -d -m 0755 "/target${base_dir}/${required_by}.requires"
    stage_target_atomic_unit_symlink "$unit_path" "/target${base_dir}/${required_by}.requires/${unit}" || exit 1
    staged=true
  done

  for alias_name in $(target_systemd_install_values "$unit_path" Alias); do
    validate_systemd_unit_name "$alias_name"
    install -d -m 0755 "/target${base_dir}"
    stage_target_atomic_unit_symlink "$unit_path" "/target${base_dir}/${alias_name}" || exit 1
    staged=true
  done

  for also_unit in $(target_systemd_install_values "$unit_path" Also); do
    validate_systemd_unit_name "$also_unit"
    [ "$also_unit" = "$unit" ] && continue
    if [ -z "$(target_systemd_unit_path "$also_unit" "$scope" || true)" ]; then
      continue
    fi
    stage_target_systemd_unit_enabled "$also_unit" "$scope" "$enable_chain" || exit 1
    staged=true
  done

  [ "$staged" = true ] || installer_fatal "target ${scope} unit has no supported [Install] entries: ${unit}"
)

stage_target_systemd_unit_wanted_by() {
  unit=$1
  scope=$2
  wanted_by=$3
  unit_path=$(target_systemd_unit_path "$unit" "$scope" || true)
  base_dir=$(target_systemd_scope_base_dir "$scope")

  validate_systemd_unit_name "$unit"
  validate_systemd_unit_name "$wanted_by"
  [ -n "$unit_path" ] || installer_fatal "expected target ${scope} unit is missing: ${unit}"

  install -d -m 0755 "/target${base_dir}/${wanted_by}.wants"
  stage_target_atomic_unit_symlink "$unit_path" "/target${base_dir}/${wanted_by}.wants/${unit}"
}

stage_target_systemd_unit_alias_to_path() {
  alias_name=$1
  scope=$2
  unit_path=$3
  base_dir=$(target_systemd_scope_base_dir "$scope")

  validate_systemd_unit_name "$alias_name"
  [ -n "$unit_path" ] || installer_fatal "expected target ${scope} unit path for alias ${alias_name} is missing"

  install -d -m 0755 "/target${base_dir}"
  stage_target_atomic_unit_symlink "$unit_path" "/target${base_dir}/${alias_name}"
}


unstage_target_systemd_unit_enabled() {
  unit=$1
  scope=${2:-system}
  base_dir=$(target_systemd_scope_base_dir "$scope")

  validate_systemd_unit_name "$unit"
  for link_dir in "/target${base_dir}"/*.wants "/target${base_dir}"/*.requires; do
    [ -d "$link_dir" ] || continue
    rm -f "${link_dir}/${unit}"
  done
}

stage_target_default_systemd_unit() {
  unit=$1
  unit_path=$(target_systemd_unit_path "$unit" system || true)
  default_link="/target${DIR_SYSTEMD_SYSTEM}/default.target"

  [ -n "$unit_path" ] || installer_fatal "expected target default unit target is missing: ${unit}"
  install -d -m 0755 "/target${DIR_SYSTEMD_SYSTEM}"
  stage_target_atomic_unit_symlink "$unit_path" "$default_link"
  [ -L "$default_link" ] || installer_fatal "default.target staged symlink is missing"
  [ "$(readlink "$default_link")" = "$unit_path" ] || installer_fatal "default.target does not point to ${unit_path}"
}

enable_target_dbus_broker_units() {
  system_broker_unit_path=$(target_systemd_unit_path "dbus-broker.service" system || true)
  user_broker_unit_path=$(target_systemd_unit_path "dbus-broker.service" user || true)
  system_socket_unit_path=$(target_systemd_unit_path "dbus.socket" system || true)
  user_socket_unit_path=$(target_systemd_unit_path "dbus.socket" user || true)

  [ -n "$system_socket_unit_path" ] || installer_fatal "expected target dbus.socket is missing"
  [ -n "$system_broker_unit_path" ] || installer_fatal "expected target dbus-broker.service is missing"
  [ -n "$user_socket_unit_path" ] || installer_fatal "expected target user dbus.socket is missing"
  [ -n "$user_broker_unit_path" ] || installer_fatal "expected target user dbus-broker.service is missing"
  [ "$system_broker_unit_path" = "${DIR_SYSTEMD_SYSTEM_LIB}/dbus-broker.service" ] || \
    installer_fatal "system dbus-broker.service must resolve to ${DIR_SYSTEMD_SYSTEM_LIB}/dbus-broker.service, got ${system_broker_unit_path}"
  [ "$user_broker_unit_path" = "${DIR_SYSTEMD_USER_LIB}/dbus-broker.service" ] || \
    installer_fatal "user dbus-broker.service must resolve to ${DIR_SYSTEMD_USER_LIB}/dbus-broker.service, got ${user_broker_unit_path}"

  stage_target_systemd_unit_wanted_by dbus.socket system sockets.target
  stage_target_systemd_unit_wanted_by dbus.socket user sockets.target
  stage_target_systemd_unit_alias_to_path dbus.service system "$system_broker_unit_path"
  stage_target_systemd_unit_alias_to_path dbus.service user "$user_broker_unit_path"
}



configure_target_dbus_broker() {
  [ "${DIR_DBUS_SESSION_SERVICES:-/usr/share/dbus-1/services}" = /usr/share/dbus-1/services ] || \
    installer_fatal "broker maintenance requires the Debian vendor activation directory"
  [ "${DIR_DBUS_LOCAL_SESSION_SERVICES:-/usr/local/share/dbus-1/services}" = /usr/local/share/dbus-1/services ] || \
    installer_fatal "broker maintenance requires the Debian local activation directory"
  validate_dbus_broker_policy_env

  # late_command runs against a chrooted target, not a live booted system:
  # stage files and validate metadata only, without assuming services are running.
  repair_target_dbus_broker_packages
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/libexec/dbus-broker-maintain)" /usr/local/libexec/dbus-broker-maintain 0755
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/libexec/dbus-broker-check)" /usr/local/libexec/dbus-broker-check 0755
  stage_target_dbus_session_service_aliases
  # Install the hook only AFTER the initial successful configuration.
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/dpkg/dpkg.cfg.d/90-managed-dbus-broker)" /etc/dpkg/dpkg.cfg.d/90-managed-dbus-broker 0644
  render_dbus_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/dbus-1/system-local.conf.tmpl)" "${FILE_DBUS_SYSTEM_LOCAL_CONF}" 0644
  render_dbus_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/system/dbus-broker.service.d/10-broker-hardening.conf.tmpl)" "${FILE_DBUS_SYSTEM_BROKER_SERVICE_OVERRIDE}" 0644
  render_dbus_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/user/dbus-broker.service.d/10-broker-hardening.conf.tmpl)" "${FILE_DBUS_USER_BROKER_SERVICE_OVERRIDE}" 0644

  enable_target_dbus_broker_units
}
