#!/bin/sh
# Sourced installer module; edit this file directly.

installer_runtime_dir() {
  printf '%s\n' "${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}"
}

installer_runtime_state_dir() {
  printf '%s/state\n' "${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}"
}

installer_runtime_cache_dir() {
  printf '%s/cache\n' "${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}"
}

installer_runtime_seed_cache_dir() {
  printf '%s/cache/seed\n' "${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}"
}

installer_runtime_log_dir() {
  printf '%s\n' /tmp
}

installer_runtime_log_file() {
  printf '%s\n' /tmp/installer.log
}

installer_runtime_temp_log_dir() {
  printf '%s/state/tmp\n' "$(installer_runtime_dir)"
}

installer_target_log_dir() {
  printf '%s/var/lib/installer-state\n' "${INSTALLER_TARGET_DIR:-/target}"
}

installer_target_log_root_dir() {
  printf '%s/var/lib/installer-state\n' "${INSTALLER_TARGET_DIR:-/target}"
}

installer_target_log_file() {
  printf '%s/var/lib/installer-state/installer.log\n' "${INSTALLER_TARGET_DIR:-/target}"
}

installer_runtime_bootstrap_dir() {
  printf '%s/bootstrap\n' "${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}"
}

installer_bootstrap_seed_url_path() {
  printf '%s/bootstrap/seed.url\n' "${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}"
}

installer_bootstrap_seed_file_path() {
  printf '%s/bootstrap/seed.file\n' "${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}"
}

installer_bootstrap_helper_path() {
  printf '%s/bootstrap/preseed-bootstrap-entry.sh\n' "${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}"
}

installer_bootstrap_lib_path() {
  printf '%s/bootstrap/bootstrap.sh\n' "${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}"
}

installer_bootstrap_seed_meta_path() {
  printf '%s/bootstrap/seed.meta\n' "${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}"
}

installer_phase_bootstrap_log_path() {
  phase_name=$1
  case "$phase_name" in
    prepare-context|apply|early|partman|late) installer_runtime_log_file ;;
    *) return 1 ;;
  esac
}

installer_context_env_path() {
  printf '%s/state/context.env\n' "${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}"
}

installer_class_policy_env_path() {
  printf '%s/state/class-policy.env\n' "${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}"
}

installer_load_context_if_present() {
  context_env=$(installer_context_env_path)
  [ -r "$context_env" ] || return 1
  # shellcheck disable=SC1090
  . "$context_env"
}

installer_class_list_has_default() {
  installer_default_class_list=${1:-}

  for installer_default_token in $(printf '%s\n' "$installer_default_class_list" | tr ';,' '  '); do
    case "$installer_default_token" in
      default)
        return 0
        ;;
    esac
  done
  return 1
}

installer_default_classes_raw() {
  installer_default_seed_base=${1:-}

  installer_ensure_repo_env "$installer_default_seed_base"
  [ -n "${DEBIAN_DEFAULT_CLASSES:-}" ] || installer_fatal "DEBIAN_DEFAULT_CLASSES is unset in repo.env"
  printf '%s\n' "$DEBIAN_DEFAULT_CLASSES"
}

installer_expand_default_classes() {
  installer_default_seed_base=$1
  installer_default_classes_input=${2:-}

  installer_class_list_has_default "$installer_default_classes_input" || {
    printf '%s\n' "$installer_default_classes_input"
    return 0
  }

  installer_default_classes_value=$(installer_default_classes_raw "$installer_default_seed_base")
  [ -n "$installer_default_classes_value" ] || installer_fatal "DEBIAN_DEFAULT_CLASSES must not be empty when classes=default is selected"

  {
    for installer_class_token in $(printf '%s\n' "$installer_default_classes_input" | tr ';,' '  '); do
      [ -n "$installer_class_token" ] || continue
      case "$installer_class_token" in
        default)
          printf '%s\n' "$installer_default_classes_value" | tr ';,' '\n'
          ;;
        *)
          printf '%s\n' "$installer_class_token"
          ;;
      esac
    done
  } | sed '/^[[:space:]]*$/d; s/^[[:space:]]*//; s/[[:space:]]*$//' |
    awk '
      BEGIN { out = "" }
      NF {
        out = out (out == "" ? "" : ",") $0
      }
      END {
        print out
      }
    '
}

installer_logging_enabled() {
  return 0
}

installer_export_logging_policy() {
  INSTALLER_DEBUG_LOGS=1
  INSTALLER_LOG_LEVEL=debug
  export INSTALLER_DEBUG_LOGS INSTALLER_LOG_LEVEL
}

installer_log_tag() {
  if [ -n "${INSTALLER_LOG_TAG:-}" ]; then
    printf '%s\n' "$INSTALLER_LOG_TAG"
    return 0
  fi

  script_name=${0##*/}
  [ -n "$script_name" ] || script_name=installer
  printf '%s\n' "$script_name"
}

installer_log_timestamp() {
  date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || printf '%s\n' unknown-time
}

installer_log_epoch() {
  date -u '+%s' 2>/dev/null || printf '\n'
}

installer_log_level_canonical() {
  case "${1:-info}" in
    debug|DEBUG) printf '%s\n' debug ;;
    info|INFO) printf '%s\n' info ;;
    warn|WARN|warning|WARNING) printf '%s\n' warning ;;
    error|ERROR|fatal|FATAL) printf '%s\n' error ;;
    none|NONE) printf '%s\n' none ;;
    *) printf '%s\n' info ;;
  esac
}

installer_log_level_is_valid() {
  case "${1:-info}" in
    debug|DEBUG|info|INFO|warn|WARN|warning|WARNING|error|ERROR|none|NONE)
      return 0
      ;;
  esac
  return 1
}

installer_log_level_value() {
  case "$(installer_log_level_canonical "$1")" in
    debug) printf '%s\n' 10 ;;
    info) printf '%s\n' 20 ;;
    warning) printf '%s\n' 30 ;;
    error) printf '%s\n' 40 ;;
    none) printf '%s\n' 99 ;;
  esac
}

installer_log_should_emit() {
  requested_level=$(installer_log_level_canonical "$1")
  installer_logging_enabled || return 1
  active_level=$(installer_log_level_canonical "${INSTALLER_LOG_LEVEL:-debug}")

  [ "$active_level" != none ] || return 1
  requested_value=$(installer_log_level_value "$requested_level")
  active_value=$(installer_log_level_value "$active_level")
  [ "$requested_value" -ge "$active_value" ]
}

installer_emit_console_error() {
  installer_console_level=$(installer_log_level_canonical "${1:-error}")
  shift
  printf '%s stage=%s level=%s component=%s %s\n' \
    "$(installer_log_timestamp)" \
    "$(installer_log_stage)" \
    "$installer_console_level" \
    "$(installer_log_tag)" \
    "$*" >&2
}

installer_validate_log_level() {
  installer_log_level_is_valid "${1:-info}" || installer_fatal "installer log level must be debug, info, warning, error, or none"
}

installer_debug() {
  installer_log_record debug "$*"
}

installer_stage_valid() {
  case "${1:-}" in
    boot|preseed_loaded|network_configured|disk_discovery|partman_start|partman_done|base_install_start|base_install_done|apt_config|package_install|bootloader|late_command|target_customization|first_boot|post_install_validation)
      return 0
      ;;
  esac
  return 1
}

installer_stage_from_tag() {
  case "${1:-}" in
    class-auto|early-dispatch) printf '%s\n' boot ;;
    preseed-*|d-i-early) printf '%s\n' preseed_loaded ;;
    partman-layout|partman-*) printf '%s\n' partman_start ;;
    base-installer-*) printf '%s\n' base_install_start ;;
    apt-*|apt) printf '%s\n' apt_config ;;
    bootloader|grub|secure-boot) printf '%s\n' bootloader ;;
    late-command|late-*) printf '%s\n' late_command ;;
    finish-install-*|finish-install) printf '%s\n' post_install_validation ;;
    firstboot|first-boot) printf '%s\n' first_boot ;;
    *) printf '%s\n' "${INSTALLER_LOG_STAGE:-preseed_loaded}" ;;
  esac
}

installer_log_stage() {
  if installer_stage_valid "${INSTALLER_LOG_STAGE:-}"; then
    printf '%s\n' "$INSTALLER_LOG_STAGE"
    return 0
  fi
  installer_stage_from_tag "$(installer_log_tag)"
}

installer_log_category_name() {
  category=$1

  case "$category" in
    boot|preseed|network|disk|partman|apt|package|bootloader|late|desktop|firstboot)
      printf '%s\n' installer.log
      ;;
    *) return 1 ;;
  esac
}

installer_log_stage_for_category() {
  category=$1

  case "$category" in
    boot) printf '%s\n' boot ;;
    preseed) printf '%s\n' preseed_loaded ;;
    network) printf '%s\n' network_configured ;;
    disk) printf '%s\n' disk_discovery ;;
    partman) printf '%s\n' partman_start ;;
    apt) printf '%s\n' apt_config ;;
    package) printf '%s\n' package_install ;;
    bootloader) printf '%s\n' bootloader ;;
    late) printf '%s\n' late_command ;;
    desktop) printf '%s\n' target_customization ;;
    firstboot) printf '%s\n' first_boot ;;
    *) printf '%s\n' post_install_validation ;;
  esac
}

installer_log_category_file() {
  category=$1
  installer_log_category_name "$category" >/dev/null || return 1
  installer_runtime_log_file
}

installer_append_log_category() {
  category=$1
  stage=$2
  level=$3
  component=$4
  shift 4

  level=$(installer_log_level_canonical "$level")
  installer_log_should_emit "$level" || return 0
  installer_stage_valid "$stage" || stage=preseed_loaded
  category_log_path=$(installer_log_category_file "$category") || return 1
  category_log_dir=$(dirname "$category_log_path")
  [ -d "$category_log_dir" ] || install -d -m 0700 "$category_log_dir"
  printf '%s stage=%s level=%s component=%s %s\n' \
    "$(installer_log_timestamp)" \
    "$stage" \
    "$level" \
    "$component" \
    "$*" >>"$category_log_path"
}

installer_append_log_category_file() {
  category=$1
  stage=$2
  level=$3
  component=$4
  source_file=$5

  level=$(installer_log_level_canonical "$level")
  installer_log_should_emit "$level" || return 0
  [ -s "$source_file" ] || return 0
  installer_stage_valid "$stage" || stage=preseed_loaded
  category_log_path=$(installer_log_category_file "$category") || return 1
  category_log_dir=$(dirname "$category_log_path")
  [ -d "$category_log_dir" ] || install -d -m 0700 "$category_log_dir"
  log_timestamp=$(installer_log_timestamp)
  while IFS= read -r log_line || [ -n "$log_line" ]; do
    [ -n "$log_line" ] || continue
    printf '%s stage=%s level=%s component=%s %s\n' \
      "$log_timestamp" \
      "$stage" \
      "$level" \
      "$component" \
      "$log_line"
  done <"$source_file" >>"$category_log_path"
}

installer_log_record() {
  log_level=$1
  shift
  log_level=$(installer_log_level_canonical "$log_level")
  if ! installer_log_should_emit "$log_level"; then
    [ "$log_level" = error ] || return 0
    installer_emit_console_error "$log_level" "$*"
    return 0
  fi
  printf '%s stage=%s level=%s component=%s %s\n' \
    "$(installer_log_timestamp)" \
    "$(installer_log_stage)" \
    "$log_level" \
    "$(installer_log_tag)" \
    "$*" >&2
}

installer_log() {
  installer_log_message=$*
  case "$installer_log_message" in
    "info: "*) installer_log_record info "${installer_log_message#info: }" ;;
    "warn: "*) installer_log_record warning "${installer_log_message#warn: }" ;;
    "warning: "*) installer_log_record warning "${installer_log_message#warning: }" ;;
    "error: "*) installer_log_record error "${installer_log_message#error: }" ;;
    "fatal: "*) installer_log_record error "${installer_log_message#fatal: }" ;;
    "debug: "*) installer_log_record debug "${installer_log_message#debug: }" ;;
    *) installer_log_record info "$installer_log_message" ;;
  esac
}

installer_info() {
  installer_log_record info "$*"
}

installer_warn() {
  installer_log_record warning "$*"
}

installer_error() {
  installer_log_record error "$*"
}

installer_trim_whitespace() {
  printf '%s' "$1" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//'
}

# shellcheck disable=SC2034 # Exposes INSTALLER_MOUNT_* fields for callers.
