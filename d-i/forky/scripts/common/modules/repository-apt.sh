#!/bin/sh
# Sourced installer module; edit this file directly.

installer_seed_source_type() {
  case "${1:-}" in
    /*) printf '%s\n' file ;;
    *) printf '%s\n' url ;;
  esac
}

installer_trim_seed_base() {
  seed_base=$1

  while [ "${#seed_base}" -gt 1 ]; do
    case "$seed_base" in
      */) seed_base=${seed_base%/} ;;
      *) break ;;
    esac
  done
  printf '%s\n' "$seed_base"
}

installer_assign_normalized_seed_base() {
  output_var_name=$1
  seed_base=$2
  seed_type=$3

  seed_base=${seed_base%%\?*}
  case "$seed_base" in
    */*.cfg) seed_base=${seed_base%/*} ;;
  esac
  seed_base=$(installer_trim_seed_base "$seed_base")

  case "$seed_type" in
    file)
      case "$seed_base" in
        /*) ;;
        *) installer_fatal "installation file base must be an absolute path: ${seed_base:-unset}" ;;
      esac
      case "$seed_base" in
        *..*|*//*)
          installer_fatal "installation file base contains unsupported traversal: $seed_base"
          ;;
      esac
      ;;
    url)
      [ -n "$seed_base" ] || installer_fatal "installation URL base is empty"
      ;;
    *)
      installer_fatal "unsupported installation source type: $seed_type"
      ;;
  esac

  eval "$output_var_name=\$seed_base"
}

installer_normalize_seed_base() {
  normalized_seed_base=
  installer_assign_normalized_seed_base normalized_seed_base "$1" "$2"
  printf '%s\n' "$normalized_seed_base"
}

installer_persist_seed_source() {
  seed_base=$1
  seed_type=$(installer_seed_source_type "$seed_base")
  seed_url_path=$(installer_bootstrap_seed_url_path)
  seed_file_path=$(installer_bootstrap_seed_file_path)

  install -d -m 0700 "$(installer_runtime_bootstrap_dir)"

  case "$seed_type" in
    file)
      SEED_FILE_BASE=$(installer_normalize_seed_base "$seed_base" file)
      SEED_URL_BASE=
      printf '%s\n' "$SEED_FILE_BASE" >"$seed_file_path"
      rm -f "$seed_url_path"
      ;;
    url)
      SEED_URL_BASE=$(installer_normalize_seed_base "$seed_base" url)
      SEED_FILE_BASE=
      printf '%s\n' "$SEED_URL_BASE" >"$seed_url_path"
      rm -f "$seed_file_path"
      ;;
    *)
      installer_fatal "unsupported installation source type: $seed_type"
      ;;
  esac
}

installer_choose_seed_base_from_pair() {
  url_seed_base=$1
  file_seed_base=$2
  seed_label=$3

  if [ -n "$url_seed_base" ] && [ -n "$file_seed_base" ]; then
    installer_fatal "${seed_label} defines both URL and file seed sources"
  fi
  if [ -n "$url_seed_base" ]; then
    installer_assign_normalized_seed_base INSTALLER_RESOLVED_SEED_BASE "$url_seed_base" url
    return 0
  fi
  if [ -n "$file_seed_base" ]; then
    installer_assign_normalized_seed_base INSTALLER_RESOLVED_SEED_BASE "$file_seed_base" file
    return 0
  fi

  INSTALLER_RESOLVED_SEED_BASE=
  return 1
}

installer_persisted_seed_base() {
  persisted_seed_url_base=
  persisted_seed_file_base=
  persisted_seed_url_path=$(installer_bootstrap_seed_url_path)
  persisted_seed_file_path=$(installer_bootstrap_seed_file_path)

  if [ -f "$persisted_seed_url_path" ]; then
    persisted_seed_url_base=$(cat "$persisted_seed_url_path")
  fi
  if [ -f "$persisted_seed_file_path" ]; then
    persisted_seed_file_base=$(cat "$persisted_seed_file_path")
  fi

  installer_choose_seed_base_from_pair "$persisted_seed_url_base" "$persisted_seed_file_base" "persisted installer state"
}

installer_seed_base() {
  seed_base=${1:-}
  if [ -n "$seed_base" ]; then
    seed_type=$(installer_seed_source_type "$seed_base")
    installer_normalize_seed_base "$seed_base" "$seed_type"
    return 0
  fi
  if [ "${INSTALLER_SEED_BASE_CACHE_READY:-0}" -eq 1 ]; then
    printf '%s\n' "$INSTALLER_SEED_BASE_CACHE"
    return 0
  fi

  if installer_choose_seed_base_from_pair "${SEED_URL_BASE:-}" "${SEED_FILE_BASE:-}" "runtime seed state"; then
    INSTALLER_SEED_BASE_CACHE=$INSTALLER_RESOLVED_SEED_BASE
    INSTALLER_SEED_BASE_CACHE_READY=1
    printf '%s\n' "$INSTALLER_SEED_BASE_CACHE"
    return 0
  fi
  if installer_choose_seed_base_from_pair "${INSTALLER_SEED_URL_BASE:-}" "${INSTALLER_SEED_FILE_BASE:-}" "installer context seed state"; then
    INSTALLER_SEED_BASE_CACHE=$INSTALLER_RESOLVED_SEED_BASE
    INSTALLER_SEED_BASE_CACHE_READY=1
    printf '%s\n' "$INSTALLER_SEED_BASE_CACHE"
    return 0
  fi
  if [ -n "${INSTALLER_SEED_BASE:-}" ]; then
    INSTALLER_SEED_BASE_CACHE=$(installer_normalize_seed_base "${INSTALLER_SEED_BASE}" "$(installer_seed_source_type "${INSTALLER_SEED_BASE}")")
    INSTALLER_SEED_BASE_CACHE_READY=1
    printf '%s\n' "$INSTALLER_SEED_BASE_CACHE"
    return 0
  fi
  if installer_persisted_seed_base; then
    printf '%s\n' "$INSTALLER_RESOLVED_SEED_BASE"
    return 0
  fi
  installer_load_source_library "${INSTALLER_SOURCE_ROOT:-}" || return 1
  source_resolve_seed
  return $?

installer_fatal "installation preseed URL or file path not found in kernel cmdline, installer context, runtime state, or persisted installer state"
}

installer_seed_url_base() {
  installer_seed_base "${1:-}"
}

installer_current_seed_base() {
  installer_seed_base ""
}

installer_validate_relative_seed_path() {
  seed_relative_path=$1

  case "$seed_relative_path" in
    ''|/*|../*|*/..|*../*|*//*)
      installer_fatal "seed source path must stay relative to the seed base: ${seed_relative_path:-unset}"
      ;;
  esac
}

installer_file_safe_token() {
  printf '%s\n' "$(printf '%s' "${1:-seed}" | sed 's/[^A-Za-z0-9._-]/_/g')"
}

installer_repo_env_relpath() {
  printf '%s\n' repo.env
}

installer_repo_env_path() {
  printf '%s/bootstrap/repo.env\n' "${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}"
}

installer_repo_env_dir_vars() {
  installer_repo_env_vars_path=$1
  sed -n 's/^\(DIR_[A-Z0-9_]*\)=.*/\1/p' "$installer_repo_env_vars_path"
}

installer_validate_repo_dir_value() {
  installer_repo_validate_var=$1
  installer_repo_validate_value=$2

  case "$installer_repo_validate_value" in
    ''|/*|../*|*/..|*../*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/-]*)
      installer_fatal "${installer_repo_validate_var} must be a safe repository-relative directory path: ${installer_repo_validate_value:-unset}"
      ;;
  esac
}

installer_repo_dir_input_is_var() {
  case "${1:-}" in
    DIR_[ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_]*)
      case "$1" in
        *[!ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_]*) return 1 ;;
      esac
      return 0
      ;;
  esac
  return 1
}

installer_loaded_repo_dir_value() {
  case "${1:-}" in
    DIR_HOSTS_THEMES) printf '%s\n' "${DIR_HOSTS_THEMES:-}" ;;
    DIR_HOSTS_PROFILES) printf '%s\n' "${DIR_HOSTS_PROFILES:-}" ;;
    DIR_HOSTS_LOGGING) printf '%s\n' "${DIR_HOSTS_LOGGING:-}" ;;
    DIR_HOSTS_INSTALLER) printf '%s\n' "${DIR_HOSTS_INSTALLER:-}" ;;
    DIR_HOOKS_INSTALLER) printf '%s\n' "${DIR_HOOKS_INSTALLER:-}" ;;
    DIR_HOOKS_TARGET) printf '%s\n' "${DIR_HOOKS_TARGET:-}" ;;
    DIR_HOOKS_INSTALLER_APT_SETUP_GENERATORS) printf '%s\n' "${DIR_HOOKS_INSTALLER_APT_SETUP_GENERATORS:-}" ;;
    DIR_HOOKS_INSTALLER_BASE_STAGE_D) printf '%s\n' "${DIR_HOOKS_INSTALLER_BASE_STAGE_D:-}" ;;
    DIR_HOOKS_INSTALLER_D_I) printf '%s\n' "${DIR_HOOKS_INSTALLER_D_I:-}" ;;
    DIR_HOOKS_INSTALLER_FINISH_INSTALL_D) printf '%s\n' "${DIR_HOOKS_INSTALLER_FINISH_INSTALL_D:-}" ;;
    DIR_HOOKS_INSTALLER_PARTMAN) printf '%s\n' "${DIR_HOOKS_INSTALLER_PARTMAN:-}" ;;
    DIR_HOOKS_INSTALLER_PARTMAN_FINISH_D) printf '%s\n' "${DIR_HOOKS_INSTALLER_PARTMAN_FINISH_D:-}" ;;
    DIR_HOOKS_INSTALLER_PRE_PKGSEL_D) printf '%s\n' "${DIR_HOOKS_INSTALLER_PRE_PKGSEL_D:-}" ;;
    DIR_SCRIPTS_COMMON) printf '%s\n' "${DIR_SCRIPTS_COMMON:-}" ;;
    DIR_SCRIPTS_EARLY) printf '%s\n' "${DIR_SCRIPTS_EARLY:-}" ;;
    DIR_SCRIPTS_FIRSTBOOT) printf '%s\n' "${DIR_SCRIPTS_FIRSTBOOT:-}" ;;
    DIR_SCRIPTS_LATE) printf '%s\n' "${DIR_SCRIPTS_LATE:-}" ;;
    DIR_SCRIPTS_PARTMAN) printf '%s\n' "${DIR_SCRIPTS_PARTMAN:-}" ;;
    DIR_SCRIPTS_PRESEED) printf '%s\n' "${DIR_SCRIPTS_PRESEED:-}" ;;
    DIR_SCRIPTS_RUNTIME) printf '%s\n' "${DIR_SCRIPTS_RUNTIME:-}" ;;
    DIR_SCRIPTS_DESKTOP) printf '%s\n' "${DIR_SCRIPTS_DESKTOP:-}" ;;
    *) return 1 ;;
  esac
}

installer_validate_repo_env() {
  installer_repo_validate_env_path=${1:-$(installer_repo_env_path)}

  [ -r "$installer_repo_validate_env_path" ] || installer_fatal "repository path environment is not readable: $installer_repo_validate_env_path"
  while IFS= read -r installer_repo_validate_dir_var || [ -n "$installer_repo_validate_dir_var" ]; do
    [ -n "$installer_repo_validate_dir_var" ] || continue
    installer_repo_validate_dir_value=$(installer_loaded_repo_dir_value "$installer_repo_validate_dir_var" 2>/dev/null || true)
    installer_validate_repo_dir_value "$installer_repo_validate_dir_var" "$installer_repo_validate_dir_value"
  done <<EOF
$(installer_repo_env_dir_vars "$installer_repo_validate_env_path")
EOF
}

installer_ensure_repo_env() {
  installer_repo_env_seed_base=${1:-}

  if [ "${INSTALLER_REPO_ENV_READY:-0}" -eq 1 ]; then
    return 0
  fi

  installer_repo_env_file=$(installer_repo_env_path)
  if [ -n "${INSTALLER_SOURCE_ROOT:-}" ]; then
    installer_repo_env_source="${INSTALLER_SOURCE_ROOT%/}/$(installer_repo_env_relpath)"
    [ -r "$installer_repo_env_source" ] || installer_fatal "repository path environment is not readable: ${installer_repo_env_source}"
    installer_repo_env_file=$installer_repo_env_source
  else
    [ -n "$installer_repo_env_seed_base" ] || installer_repo_env_seed_base=$(installer_current_seed_base)
    if [ ! -s "$installer_repo_env_file" ]; then
      installer_fetch_seed_path "$installer_repo_env_seed_base" "$(installer_repo_env_relpath)" "$installer_repo_env_file" 0600
    fi
  fi
  # shellcheck disable=SC1090
  . "$installer_repo_env_file"
  installer_validate_repo_env "$installer_repo_env_file"
  INSTALLER_REPO_ENV_READY=1
}

installer_repo_dir_value() {
  installer_repo_dir_name=$1
  installer_repo_dir_value=
  installer_repo_dir_path=

  if ! installer_repo_dir_input_is_var "$installer_repo_dir_name"; then
    installer_repo_dir_path=$installer_repo_dir_name
    installer_validate_repo_dir_value repository_path "$installer_repo_dir_path"
    printf '%s\n' "$installer_repo_dir_path"
    return 0
  fi

  if [ "${INSTALLER_REPO_ENV_READY:-0}" -ne 1 ]; then
    installer_ensure_repo_env ""
  fi
  installer_repo_dir_value=$(installer_loaded_repo_dir_value "$installer_repo_dir_name" 2>/dev/null || true)
  [ -n "$installer_repo_dir_value" ] || installer_fatal "repository directory variable is unset: $installer_repo_dir_name"
  installer_validate_repo_dir_value "$installer_repo_dir_name" "$installer_repo_dir_value"
  printf '%s\n' "$installer_repo_dir_value"
}

installer_repo_join_var() {
  installer_repo_join_dir=$1
  installer_repo_join_leaf=${2:-}
  installer_repo_join_base=$(installer_repo_dir_value "$installer_repo_join_dir")

  # Systemd template-unit paths legitimately contain "@", for example
  # etc/systemd/system/user@.service.d/50-oom-score.conf.
  case "$installer_repo_join_leaf" in
    '') printf '%s\n' "$installer_repo_join_base" ;;
    /*|../*|*/..|*../*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/@-]*)
      installer_fatal "unsafe repository path suffix for ${installer_repo_join_dir}: ${installer_repo_join_leaf:-unset}"
      ;;
    *) printf '%s/%s\n' "$installer_repo_join_base" "$installer_repo_join_leaf" ;;
  esac
}

# Legacy hierarchy mapper removed; all callers use physical repository paths.

# Legacy hierarchy mapper removed; all callers use physical repository paths.

installer_repo_resolve_path() {
  installer_validate_relative_seed_path "$1"
  printf '%s\n' "$1"
}

installer_validate_apt_preference_token() {
  pref_token=$1
  pref_label=${2:-apt preferences}

  case "$pref_token" in
    *.pref) pref_name=$pref_token ;;
    *) pref_name="${pref_token}.pref" ;;
  esac
  case "$pref_name" in
    ''|.*|*/*|*..*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._+-]*|*.tmp|*.bak|*.save|*.distUpgrade)
      installer_fatal "unsafe apt preference name in ${pref_label}: ${pref_token:-unset}"
      ;;
    *.pref) ;;
    *)
      installer_fatal "apt preference name in ${pref_label} must resolve to a .pref file: ${pref_token:-unset}"
      ;;
  esac
  [ "${#pref_name}" -le 128 ] || installer_fatal "apt preference name in ${pref_label} is too long: $pref_name"
  printf '%s\n' "$pref_name"
}

installer_emit_apt_preference_names() {
  pref_config=$1
  pref_label=${2:-apt preferences}
  pref_line_breaks=$(printf '%s' "$pref_config" | wc -l | tr -d '[:space:]')
  case "$pref_line_breaks" in
    0) ;;
    ''|*[!0-9]*)
      installer_fatal "unable to validate ${pref_label} line count"
      ;;
    *)
      installer_fatal "${pref_label} must be a single comma- or space-separated line"
      ;;
  esac
  pref_seen=' '

  while IFS= read -r pref_token || [ -n "$pref_token" ]; do
    [ -n "$pref_token" ] || continue
    pref_name=$(installer_validate_apt_preference_token "$pref_token" "$pref_label")
    case "$pref_seen" in
      *" $pref_name "*) continue ;;
    esac
    pref_seen="${pref_seen}${pref_name} "
    printf '%s\n' "$pref_name"
  done <<EOF
$(printf '%s' "$pref_config" | tr ',	 ' '\n\n\n')
EOF
}

installer_normalize_apt_preferences_config() {
  pref_config=$1
  pref_label=${2:-apt preferences}
  pref_normalized=

  while IFS= read -r pref_name || [ -n "$pref_name" ]; do
    [ -n "$pref_name" ] || continue
    pref_token=${pref_name%.pref}
    pref_normalized="${pref_normalized:+$pref_normalized,}$pref_token"
  done <<EOF
$(installer_emit_apt_preference_names "$pref_config" "$pref_label")
EOF
  printf '%s\n' "$pref_normalized"
}

installer_selected_apt_preferences_config() {
  pref_override=
  pref_seen=' '
  while IFS= read -r class_ref || [ -n "$class_ref" ]; do
    [ -n "$class_ref" ] || continue
    installer_class_token_parts "$class_ref" >/dev/null
    group_name=${INSTALLER_CLASS_TOKEN_GROUP:-}
    class_name=$INSTALLER_CLASS_TOKEN_NAME
    [ -n "$group_name" ] || continue
    if [ "$group_name" = addon ]; then
      case "$class_name" in
        nvidia|cuda|nvidia-legacy|cuda-legacy)
          installer_nvidia_gpu_detected || continue
          ;;
      esac
    fi
    pref_value=$(installer_class_meta_value "" "$group_name" "$class_name" debian_apt_preferences)
    [ -n "$pref_value" ] || continue
    pref_label="class ${group_name}/${class_name} debian_apt_preferences"
    while IFS= read -r pref_name || [ -n "$pref_name" ]; do
      [ -n "$pref_name" ] || continue
      case "$pref_seen" in
        *" $pref_name "*) continue ;;
      esac
      pref_seen="${pref_seen}${pref_name} "
      pref_token=${pref_name%.pref}
      pref_override="${pref_override:+$pref_override,}$pref_token"
    done <<EOF
$(installer_emit_apt_preference_names "$pref_value" "$pref_label")
EOF
  done <<EOF
$(installer_selected_class_refs 2>/dev/null || true)
EOF

  [ -n "$pref_override" ] || return 1
  printf '%s\n' "$pref_override"
}

installer_apt_preferences_config() {
  installer_ensure_repo_env ""
  installer_load_context_if_present || true
  pref_base=$(installer_normalize_apt_preferences_config "${DEBIAN_APT_PREFERENCES:-}" DEBIAN_APT_PREFERENCES)

  if pref_override=$(installer_selected_apt_preferences_config 2>/dev/null); then
    if [ -n "$pref_base" ]; then
      printf '%s\n' "$(installer_normalize_apt_preferences_config "${pref_base},${pref_override}" "merged apt preferences")"
    else
      printf '%s\n' "$pref_override"
    fi
    return 0
  fi

  printf '%s\n' "$pref_base"
}

installer_configured_apt_preferences() {
  installer_emit_apt_preference_names "$(installer_apt_preferences_config)" "effective apt preferences"
}

installer_target_apt_preferences_source_variant() {
  printf '%s\n' default
}

installer_target_apt_preference_source_path() {
  pref_name=$1
  pref_variant=$(installer_target_apt_preferences_source_variant)
  printf '%s\n' "$(installer_repo_join_var DIR_HOOKS_TARGET "etc/apt/preferences.d/${pref_variant}/${pref_name}")"
}

installer_seed_cache_key() (
  installer_load_source_library "$1" || exit 1
  normalized=$(source_normalize_base "$1") || exit 1
  key=$(printf '%s' "$normalized" | source_hash) || exit 1
  printf '%s\n' "${key%% *}"
)

installer_seed_cache_path() (
  installer_load_source_library "$1" || exit 1
  source_validate_relative "$2" || exit 1
  printf '%s/%s\n' "$(source_cache_root "$1")" "$2"
)

# External vendor data; never resolve repository code from the vendor URL.
installer_fetch_url() (
  installer_load_source_library "${INSTALLER_SOURCE_ROOT:-}" || exit 1
  source_fetch_external "$1" "$2" "$3" "${4:-0600}"
)

installer_copy_seed_file() (
  installer_load_source_library "$1" || exit 1
  source_fetch "$1" "$2" "$3" "${4:-0600}"
)


# Logging is a separately validated shared data catalog. No values are obtained
# from log messages, application environments, or unverified remote fallbacks.
installer_load_logging_helpers() {
  if command -v installer_validate_logging_data >/dev/null 2>&1; then return 0; fi
  installer_load_source_library "$1" || return 1
  log_helper_root=$(source_cache_root "$1") || return 1
  log_helper_path=$log_helper_root/scripts/common/logging.sh
  if [ ! -f "$log_helper_path" ]; then
    source_fetch "$1" scripts/common/logging.sh "$log_helper_path" 0600 || return 1
  fi
  [ -f "$log_helper_path" ] && [ ! -L "$log_helper_path" ] || {
    installer_error 'logging helpers are absent from the authenticated source'; return 1;
  }
  # shellcheck disable=SC1090,SC1091
  . "$log_helper_path"
}

installer_render_logging_asset() (
  # Transport callers retain the original mode and the suffix-free destination.
  case "$2" in hooks/target/*|scripts/late/*|scripts/desktop/*|scripts/firstboot/*) ;; *) exit 0 ;; esac
  case "$2" in *.png|*.jpg|*.jpeg|*.webp|*.gif|*.ico|*.ttf|*.otf|*.gz|*.xz|*.zip|*.deb) exit 0 ;; esac
  if LC_ALL=C grep -q '__INSTALLER_LOG_' "$3"; then
    installer_load_logging_helpers "$1" || exit 1
    log_cache_root=$(source_cache_root "$1") || exit 1
    case "$3" in
      "$log_cache_root"|"$log_cache_root"/*)
        installer_error 'refusing to render inside the authenticated source snapshot'; exit 1 ;;
    esac
    installer_render_logging_file "$1" "$3" || exit 1
  else
    log_probe_status=$?
    [ "$log_probe_status" = 1 ] || exit "$log_probe_status"
  fi
)

installer_fetch_seed_path() (
  installer_load_source_library "$1" || exit 1
  case "$2" in
    hooks/target/*|scripts/late/*|scripts/desktop/*|scripts/firstboot/*)
      # Fetch and rendering form one transaction; invalid data cannot replace
      # a destination with an unrendered source template.
      mkdir -p "$(dirname "$3")" || exit 1
      logging_fetch_work=$(mktemp -d "${3}.fetch-render.XXXXXX") || exit 1
      trap 'rm -rf -- "$logging_fetch_work"' 0
      trap 'exit 129' HUP; trap 'exit 130' INT; trap 'exit 143' TERM
      chmod 0700 "$logging_fetch_work" || exit 1
      source_fetch "$1" "$2" "$logging_fetch_work/asset" "${4:-0600}" || exit 1
      installer_render_logging_asset "$1" "$2" "$logging_fetch_work/asset" || exit 1
      mv -f -- "$logging_fetch_work/asset" "$3" || exit 1 ;;
    *) source_fetch "$1" "$2" "$3" "${4:-0600}" || exit 1 ;;
  esac
)

installer_fetch_file() {
  fetch_file_seed_base=$1
  fetch_file_source_path=$2
  fetch_file_dest_path=$3
  fetch_file_mode=${4:-0600}

  installer_fetch_seed_path "$fetch_file_seed_base" "$fetch_file_source_path" "$fetch_file_dest_path" "$fetch_file_mode" || installer_fatal "failed to fetch $fetch_file_source_path"
}

