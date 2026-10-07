#!/bin/sh
# Sourced installer module; edit this file directly.

installer_populate_selected_class_state() {
  seed_base=${1:-}
  records_path=$(installer_selected_class_records_path)
  selected_groups=
  selected_classes=
  selected_class_refs=

  installer_resolve_selected_class_records "$seed_base" "$records_path"
  installer_clear_selected_class_state "$seed_base"

  while IFS='|' read -r group_name class_name class_relpath || [ -n "$group_name" ]; do
    [ -n "$group_name" ] || continue
    context_var=$(installer_group_context_var "$group_name")
    if installer_group_is_multi "$group_name"; then
      eval "context_current=\${$context_var:-}"
      context_current="${context_current:+$context_current }$class_name"
      eval "$context_var=\$context_current"
    else
      eval "$context_var=\$class_name"
    fi
    case " ${selected_groups} " in
      *" ${group_name} "*) ;;
      *) selected_groups="${selected_groups:+$selected_groups }$group_name" ;;
    esac
    selected_classes="${selected_classes:+$selected_classes }$class_name"
    selected_class_refs="${selected_class_refs:+$selected_class_refs }${group_name}/${class_name}"
  done <"$records_path"

  INSTALLER_SELECTED_GROUPS=$selected_groups
  INSTALLER_SELECTED_CLASSES=$selected_classes
  INSTALLER_SELECTED_CLASS_REFS=$selected_class_refs

  base_role_group=$(installer_group_for_purpose host-variant)
  storage_group=$(installer_group_for_purpose storage)
  [ -n "$base_role_group" ] || installer_fatal "classes config must define a host-variant group purpose"
  [ -n "$storage_group" ] || installer_fatal "classes config must define a storage group purpose"

  base_role_class=$(installer_group_selected_class_value "$base_role_group")
  storage_class=$(installer_group_selected_class_value "$storage_group")

  host_variant=$(installer_class_meta_value "$seed_base" "$base_role_group" "$base_role_class" host_variant)
  host_profile_prefix=$(installer_class_meta_value "$seed_base" "$storage_group" "$storage_class" host_profile_prefix)
  host_family=$(installer_class_meta_value "$seed_base" "$storage_group" "$storage_class" host_family)
  hook_family=$(installer_class_meta_value "$seed_base" "$storage_group" "$storage_class" hook_family)
  install_disk_candidates_default=$(installer_class_meta_value "$seed_base" "$storage_group" "$storage_class" install_disk_candidates)
  default_install_disk=$(installer_class_meta_value "$seed_base" "$storage_group" "$storage_class" default_install_disk)
  host_profile_env_dir=$host_family
  host_profile_env_name=$host_variant
  # Use the canonical defaults directly; no duplicate desktop-profile aliases.
  case "$host_family" in
    # Virtual storage keeps its disk candidates/hooks, but uses the same
    # canonical Btrfs policy as other Btrfs storage; no separate VM profile.
    btrfs|vm) host_profile_env_dir=override; host_profile_env_name=btrfs-de ;;
    f2fs) host_profile_env_dir=override; host_profile_env_name=f2fs-de-x360 ;;
  esac

  [ -n "$host_variant" ] || installer_fatal "selected class ${base_role_group}/${base_role_class} must define HostVariant in classes/configs/system.cfg"
  [ "$host_variant" = "${REPOSITORY_ROLE:-}" ] || installer_fatal "selected role does not match this repository: ${host_variant}"
  [ -n "$host_profile_prefix" ] || installer_fatal "selected class ${storage_group}/${storage_class} must define HostProfilePrefix in classes/configs/storage.cfg"
  [ -n "$host_family" ] || installer_fatal "selected class ${storage_group}/${storage_class} must define HostFamily in classes/configs/storage.cfg"
  [ -n "$hook_family" ] || installer_fatal "selected class ${storage_group}/${storage_class} must define HookFamily in classes/configs/storage.cfg"
  [ -n "$install_disk_candidates_default" ] || installer_fatal "selected class ${storage_group}/${storage_class} must define InstallDiskCandidates in classes/configs/storage.cfg"
  [ -n "$default_install_disk" ] || installer_fatal "selected class ${storage_group}/${storage_class} must define DefaultInstallDisk in classes/configs/storage.cfg"

  profile_group=$(installer_group_for_purpose host-profile-override 2>/dev/null || true)
  profile_class=
  if [ -n "$profile_group" ]; then
    profile_class=$(installer_group_selected_class_value "$profile_group" 2>/dev/null || true)
  fi
  if [ -n "$profile_class" ]; then
    profile_env_dir=$(installer_class_meta_value "$seed_base" "$profile_group" "$profile_class" host_profile_prefix)
    profile_host_family=$(installer_class_meta_value "$seed_base" "$profile_group" "$profile_class" host_family)
    profile_hook_family=$(installer_class_meta_value "$seed_base" "$profile_group" "$profile_class" hook_family)
    [ -n "$profile_env_dir" ] || installer_fatal "selected class ${profile_group}/${profile_class} must define HostProfilePrefix in classes/configs/profile.cfg"
    [ -n "$profile_host_family" ] || installer_fatal "selected class ${profile_group}/${profile_class} must define HostFamily in classes/configs/profile.cfg"
    [ -n "$profile_hook_family" ] || installer_fatal "selected class ${profile_group}/${profile_class} must define HookFamily in classes/configs/profile.cfg"
    host_profile_env_dir=$profile_env_dir
    host_profile_env_name=$profile_class
    host_family=$profile_host_family
    hook_family=$profile_hook_family
  fi

  while IFS='|' read -r group_name class_name class_relpath || [ -n "$group_name" ]; do
    [ -n "$group_name" ] || continue
    required_classes=$(installer_class_meta_value "$seed_base" "$group_name" "$class_name" requires_classes)
    allowed_hardware_classes=$(installer_class_meta_value "$seed_base" "$group_name" "$class_name" allowed_hardware_classes)
    rejected_classes=$(installer_class_meta_value "$seed_base" "$group_name" "$class_name" rejected_classes)
    for required_class in $required_classes; do
      installer_selected_class_reference_is_selected "$required_class" || \
        installer_fatal "selected class ${group_name}/${class_name} requires class ${required_class}"
    done
    if [ -n "$allowed_hardware_classes" ]; then
      installer_selected_class_allowed_reference_matches "$allowed_hardware_classes" || \
        installer_fatal "selected class ${group_name}/${class_name} is only allowed with one of: ${allowed_hardware_classes}"
    fi
    for rejected_class in $rejected_classes; do
      installer_selected_class_reference_is_selected "$rejected_class" && \
        installer_fatal "selected class ${group_name}/${class_name} rejects class ${rejected_class}"
    done
  done <"$records_path"

  INSTALLER_HOST_VARIANT=$host_variant
  INSTALLER_STORAGE_HOST_PROFILE_PREFIX=$host_profile_prefix
  INSTALLER_INSTALL_DISK_CANDIDATES_DEFAULT=$install_disk_candidates_default
  INSTALLER_DEFAULT_INSTALL_DISK=$default_install_disk
  INSTALLER_HOST_PROFILE_ENV_DIR=$host_profile_env_dir
  INSTALLER_HOST_PROFILE_ENV_NAME=$host_profile_env_name
  INSTALLER_HOST_PROFILE="${host_profile_env_dir}-${host_profile_env_name}"
  INSTALLER_HOST_FAMILY=$host_family
  INSTALLER_HOOK_FAMILY=$hook_family
}

installer_write_runtime_install_conf() {
  runtime_conf_path=$1
  storage_group=$(installer_group_for_purpose storage 2>/dev/null || true)
  storage_class_value=
  if [ -n "$storage_group" ]; then
    storage_class_value=$(installer_group_selected_class_value "$storage_group" 2>/dev/null || true)
  fi

  {
    printf '# Generated runtime installer class config\n'
    printf '[selected]\n'
    printf 'classes_raw=%s\n' "$INSTALLER_CLASSES_RAW"
    printf 'selected_groups=%s\n' "$INSTALLER_SELECTED_GROUPS"
    printf 'selected_classes=%s\n' "$INSTALLER_SELECTED_CLASSES"
    printf 'selected_class_refs=%s\n' "$INSTALLER_SELECTED_CLASS_REFS"
    printf 'debug_logs=%s\n' "${INSTALLER_DEBUG_LOGS:-0}"
    printf 'host_variant=%s\n' "$INSTALLER_HOST_VARIANT"
    printf 'host_profile=%s\n' "$INSTALLER_HOST_PROFILE"
    printf 'host_family=%s\n' "$INSTALLER_HOST_FAMILY"
    printf 'hook_family=%s\n' "$INSTALLER_HOOK_FAMILY"
    printf 'host_profile_env_dir=%s\n' "$INSTALLER_HOST_PROFILE_ENV_DIR"
    printf 'host_profile_env_name=%s\n' "$INSTALLER_HOST_PROFILE_ENV_NAME"
    printf 'storage_host_profile_prefix=%s\n' "$INSTALLER_STORAGE_HOST_PROFILE_PREFIX"
    printf 'storage_class=%s\n' "${INSTALLER_DISK_CLASS:-$storage_class_value}"
    printf 'install_disk_candidates_default=%s\n' "$INSTALLER_INSTALL_DISK_CANDIDATES_DEFAULT"
    printf 'default_install_disk=%s\n' "$INSTALLER_DEFAULT_INSTALL_DISK"

    while IFS= read -r group_name || [ -n "$group_name" ]; do
      [ -n "$group_name" ] || continue
      class_name=$(installer_group_selected_class_value "$group_name")
      [ -n "$class_name" ] || continue
      printf '\n[group.%s]\n' "$group_name"
      printf 'class=%s\n' "$class_name"
      printf 'required=%s\n' "$(installer_group_required_status "$group_name")"
      printf 'purpose=%s\n' "$(installer_group_purpose "$group_name")"
    done <<EOF
$(installer_selected_group_names 2>/dev/null || true)
EOF
  } >"$runtime_conf_path"
  chmod 0600 "$runtime_conf_path"
}

installer_validate_class_set() {
  if [ -z "${INSTALLER_CLASSES_RAW_CACHE:-}" ]; then
    INSTALLER_CLASSES_RAW_CACHE=$(installer_classes_raw "${1:-}")
  fi
  installer_validate_class_manifest
  installer_resolve_selected_class_records "${1:-}" "$(installer_selected_class_records_path)"
}

installer_resolve_install_target_defaults() {
  if [ -z "${INSTALLER_INSTALL_DISK_CANDIDATES_DEFAULT:-}" ] || [ -z "${INSTALLER_DEFAULT_INSTALL_DISK:-}" ]; then
    installer_load_context_if_present || true
  fi

  [ -n "${INSTALLER_INSTALL_DISK_CANDIDATES_DEFAULT:-}" ] || installer_fatal "installer storage defaults are unavailable; context generation did not populate INSTALLER_INSTALL_DISK_CANDIDATES_DEFAULT"
  [ -n "${INSTALLER_DEFAULT_INSTALL_DISK:-}" ] || installer_fatal "installer storage defaults are unavailable; context generation did not populate INSTALLER_DEFAULT_INSTALL_DISK"

  if [ -z "${INSTALL_DISK_CANDIDATES:-}" ]; then
    INSTALL_DISK_CANDIDATES=$INSTALLER_INSTALL_DISK_CANDIDATES_DEFAULT
  fi
  if [ -z "${DEV_INSTALL_DISK:-}" ]; then
    DEV_INSTALL_DISK=$INSTALLER_DEFAULT_INSTALL_DISK
  fi
}

installer_resolve_host_profile() {
  requested_host_profile=${1:-}

  if [ -n "$requested_host_profile" ]; then
    printf '%s\n' "$requested_host_profile"
    return 0
  fi

  installer_load_context_if_present || true
  [ -n "${INSTALLER_HOST_PROFILE:-}" ] || installer_fatal "HOST_PROFILE is required for installer hook dispatch"
  printf '%s\n' "$INSTALLER_HOST_PROFILE"
}

installer_seed_class_answers() {
  classes_raw=$1

  installer_seed_debconf_value d-i auto-install/classes string "$classes_raw" || return "$?"
  installer_seed_debconf_value d-i classes string "$classes_raw" || return "$?"
}

installer_write_context() {
  seed_base=$1
  runtime_dir=$(installer_runtime_dir)
  context_env=$(installer_context_env_path)
  runtime_install_conf=$(installer_runtime_install_conf_path)

  install -d -m 0700 \
    "$runtime_dir" \
    "$(installer_runtime_state_dir)" \
    "$(installer_runtime_cache_dir)" \
    "$(installer_runtime_bootstrap_dir)"
  installer_ensure_log_files

  seed_base=$(installer_seed_base "$seed_base")
  installer_persist_seed_source "$seed_base"
  installer_ensure_repo_env "$seed_base"
  classes_raw=$(installer_classes_raw "$seed_base")
  INSTALLER_CLASSES_RAW_CACHE=$classes_raw
  installer_validate_class_manifest
  installer_populate_selected_class_state "$seed_base"
  installer_export_logging_policy
  installer_seed_class_answers "$classes_raw"
  INSTALLER_CLASSES_RAW=$classes_raw
  installer_write_runtime_install_conf "$runtime_install_conf"
  installer_info "selected installer classes raw: ${classes_raw}"
  installer_info "selected installer class refs: ${INSTALLER_SELECTED_CLASS_REFS:-}"
  installer_info "selected installer host profile: ${INSTALLER_HOST_PROFILE:-}"
  installer_log_boot_context

  {
    printf 'INSTALLER_SEED_URL_BASE=%s\n' "$(installer_shell_quote "${SEED_URL_BASE:-}")"
    printf 'INSTALLER_SEED_FILE_BASE=%s\n' "$(installer_shell_quote "${SEED_FILE_BASE:-}")"
    printf 'INSTALLER_SEED_BASE=%s\n' "$(installer_shell_quote "$seed_base")"
    printf 'INSTALLER_SEED_SOURCE_TYPE=%s\n' "$(installer_shell_quote "$(installer_seed_source_type "$seed_base")")"
    printf 'INSTALLER_CLASSES_RAW=%s\n' "$(installer_shell_quote "$classes_raw")"
    printf 'CLASSES=%s\n' "$(installer_shell_quote "$classes_raw")"
    printf 'INSTALLER_SELECTED_GROUPS=%s\n' "$(installer_shell_quote "${INSTALLER_SELECTED_GROUPS:-}")"
    printf 'INSTALLER_SELECTED_CLASSES=%s\n' "$(installer_shell_quote "${INSTALLER_SELECTED_CLASSES:-}")"
    printf 'INSTALLER_SELECTED_CLASS_REFS=%s\n' "$(installer_shell_quote "${INSTALLER_SELECTED_CLASS_REFS:-}")"
    printf 'INSTALLER_DEBUG_LOGS=%s\n' "$(installer_shell_quote "${INSTALLER_DEBUG_LOGS:-0}")"
    printf 'INSTALLER_HOST_VARIANT=%s\n' "$(installer_shell_quote "${INSTALLER_HOST_VARIANT:-}")"
    printf 'INSTALLER_HOST_PROFILE=%s\n' "$(installer_shell_quote "${INSTALLER_HOST_PROFILE:-}")"
    printf 'INSTALLER_HOST_FAMILY=%s\n' "$(installer_shell_quote "${INSTALLER_HOST_FAMILY:-}")"
    printf 'INSTALLER_HOOK_FAMILY=%s\n' "$(installer_shell_quote "${INSTALLER_HOOK_FAMILY:-}")"
    printf 'INSTALLER_HOST_PROFILE_ENV_DIR=%s\n' "$(installer_shell_quote "${INSTALLER_HOST_PROFILE_ENV_DIR:-}")"
    printf 'INSTALLER_HOST_PROFILE_ENV_NAME=%s\n' "$(installer_shell_quote "${INSTALLER_HOST_PROFILE_ENV_NAME:-}")"
    printf 'INSTALLER_STORAGE_HOST_PROFILE_PREFIX=%s\n' "$(installer_shell_quote "${INSTALLER_STORAGE_HOST_PROFILE_PREFIX:-}")"
    printf 'INSTALLER_INSTALL_DISK_CANDIDATES_DEFAULT=%s\n' "$(installer_shell_quote "${INSTALLER_INSTALL_DISK_CANDIDATES_DEFAULT:-}")"
    printf 'INSTALLER_DEFAULT_INSTALL_DISK=%s\n' "$(installer_shell_quote "${INSTALLER_DEFAULT_INSTALL_DISK:-}")"
    while IFS= read -r group_name || [ -n "$group_name" ]; do
      [ -n "$group_name" ] || continue
      context_var=$(installer_group_context_var "$group_name")
      class_name=$(installer_group_selected_class_value "$group_name")
      [ -n "$class_name" ] || continue
      printf '%s=%s\n' "$context_var" "$(installer_shell_quote "$class_name")"
    done <<EOF
$(installer_selected_group_names 2>/dev/null || true)
EOF
  } >"$context_env"
  chmod 0600 "$context_env"
  printf '%s\n' "$INSTALLER_HOST_PROFILE"
}

installer_load_context() {
  context_env=$(installer_context_env_path)
  [ -r "$context_env" ] || installer_fatal "context env is missing: ${context_env}"
  # shellcheck disable=SC1090
  . "$context_env"
}

installer_context_has_selected_class_state() {
  [ -n "${INSTALLER_SELECTED_GROUPS:-}" ] || return 1
  [ -n "${INSTALLER_SELECTED_CLASSES:-}" ] || return 1
  [ -n "${INSTALLER_SELECTED_CLASS_REFS:-}" ] || return 1
  [ -n "${INSTALLER_HOST_VARIANT:-}" ] || return 1
  [ -n "${INSTALLER_HOST_PROFILE:-}" ] || return 1
  [ -n "${INSTALLER_HOST_FAMILY:-}" ] || return 1
  [ -n "${INSTALLER_HOOK_FAMILY:-}" ] || return 1
  [ -n "${INSTALLER_HOST_PROFILE_ENV_DIR:-}" ] || return 1
  [ -n "${INSTALLER_HOST_PROFILE_ENV_NAME:-}" ] || return 1
  [ -n "${INSTALLER_STORAGE_HOST_PROFILE_PREFIX:-}" ] || return 1
  [ -n "${INSTALLER_INSTALL_DISK_CANDIDATES_DEFAULT:-}" ] || return 1
  [ -n "${INSTALLER_DEFAULT_INSTALL_DISK:-}" ] || return 1

  for installer_context_group in $INSTALLER_SELECTED_GROUPS; do
    installer_context_value=$(installer_group_selected_class_value "$installer_context_group" 2>/dev/null || true)
    [ -n "$installer_context_value" ] || return 1
  done

  while IFS= read -r installer_context_group || [ -n "$installer_context_group" ]; do
    [ -n "$installer_context_group" ] || continue
    case "$(installer_group_required_status "$installer_context_group")" in
      required)
        installer_context_value=$(installer_group_selected_class_value "$installer_context_group" 2>/dev/null || true)
        [ -n "$installer_context_value" ] || return 1
        ;;
    esac
  done <<EOF
$(installer_group_names)
EOF

  return 0
}

installer_ensure_context_loaded() {
  seed_base=${1:-}

  installer_load_context_if_present || true
  if installer_context_has_selected_class_state; then
    return 0
  fi

  resolved_seed_base=$(installer_seed_base "$seed_base")
  installer_warn "installer class context is missing or incomplete; regenerating from ${resolved_seed_base}"
  installer_write_context "$resolved_seed_base" >/dev/null
  installer_load_context
}

installer_prepare_context() {
  seed_base=$(installer_seed_base "${1:-}")
  installer_write_context "$seed_base" >/dev/null
  installer_load_context
}

# Flat profile storage; canonical class identifiers are validated by the resolver.
installer_profile_env_path() {
  installer_validate_profile_component "profile family" "$1"
  installer_validate_profile_component "profile name" "$2"
  case "$1" in
    override) installer_repo_join_var DIR_HOSTS_PROFILES "$2.env" ;;
    *) installer_fatal "unsupported profile family: $1" ;;
  esac
}

# Hardware selection is separate from physical payload storage. Unknown optional
# assets return a non-existent path; their existing FILE_* gate still controls
# whether staging is attempted. Required assets fail through the fetch API.
installer_hardware_asset_path() (
  group=$1; class=$2; leaf=$3
  installer_validate_profile_component "hardware group" "$group"
  installer_validate_profile_component "hardware class" "$class"
  installer_validate_relative_seed_path "$leaf"
  manifest=$(installer_class_metadata_read_path "classes/configs/target-assets.tsv")
  selected=$(awk -F '\t' -v g="$group" -v c="$class" -v p="$leaf" '$1==g && $2==c && $3==p {print $4; exit}' "$manifest")
  if [ -z "$selected" ]; then
    printf '%s\n' "hooks/target/.unavailable/$group/$class/$leaf"
  else
    installer_repo_join_var DIR_HOOKS_TARGET "$selected"
  fi
)

installer_load_source_library() {
  command -v source_fetch >/dev/null 2>&1 && return 0
  for source_library in "${INSTALLER_SOURCE_LIBRARY:-}" \
      "${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}/bootstrap/source.sh" \
      "${INSTALLER_SOURCE_ROOT:-/nonexistent}/scripts/common/source.sh" \
      "${1:-/nonexistent}/scripts/common/source.sh"; do
    [ -n "$source_library" ] && [ -s "$source_library" ] || continue
    # shellcheck disable=SC1090
    . "$source_library"
    return 0
  done
  installer_fatal 'repository transport is missing; start with the generated preseed.cfg'
}

# Explicit addon/cuda-legacy selection authorizes this single archive's
# authentication/freshness exception. SHA-1 signatures (including certificate
# self-signatures) can be rejected by modern APT; do not fetch or pin a key as
# an acceptance gate here. Never move these options into apt.conf or a global
# crypto policy. Normal CUDA and all other repositories keep their own policy.
installer_cuda_source_line() (
  set -eu
  repository=$1; suite=$2; components=${3:-}
  [ "$repository" = https://developer.download.nvidia.com/compute/cuda/repos/debian12/x86_64/ ] || {
    installer_fatal 'legacy CUDA is limited to the Debian 12 amd64 archive'; exit 1;
  }
  [ "$suite" = / ] && [ -z "$components" ] || {
    installer_fatal 'legacy CUDA must use the flat Debian 12 archive'; exit 1;
  }
  printf 'deb [arch=amd64 trusted=yes allow-insecure=yes allow-weak=yes allow-downgrade-to-insecure=yes check-valid-until=no check-date=no] %s /\n' "$repository"
)

installer_cuda_stage_target_source() (
  set -eu
  umask 077
  # Explicit statuses also protect callers that invoke this function in an
  # if/|| list, where shells disable errexit even inside a function's subshell.
  line=$(installer_cuda_source_line "$@") || exit "$?"
  target=${INSTALLER_TARGET_DIR:-/target}
  source_dir="$target/etc/apt/sources.list.d"
  source="$source_dir/cuda-legacy-temp.list"
  installer_apt_safe_path "$source" || exit "$?"
  install -d -m 0755 "$source_dir" || exit "$?"
  work=$(mktemp "$source_dir/.cuda-legacy.XXXXXX") || exit "$?"
  cleanup_cuda_source() {
    original=$?
    trap - 0 HUP INT TERM
    if rm -f "$work"; then
      :
    else
      cleanup=$?
      [ "$original" -ne 0 ] || original=$cleanup
    fi
    exit "$original"
  }
  trap cleanup_cuda_source 0
  trap 'exit 130' INT; trap 'exit 143' TERM; trap 'exit 129' HUP
  printf '%s\n' "$line" >"$work" || exit "$?"
  chmod 0644 "$work" || exit "$?"
  mv -f "$work" "$source" || exit "$?"
)

installer_cuda_refresh_target_apt() (
  set -eu
  installer_warn 'CUDA-legacy ONLY: archive authentication and metadata-date checks are disabled by explicit class selection; HTTPS and package checksums remain enabled'
  run_in_target 'refresh explicitly trusted legacy CUDA metadata' \
    env -u APT_SEQUOIA_CRYPTO_POLICY -u SEQUOIA_CRYPTO_POLICY \
    LC_ALL=C DEBIAN_FRONTEND=noninteractive apt-get \
    -o Dir::Etc::sourcelist=/etc/apt/sources.list.d/cuda-legacy-temp.list \
    -o Dir::Etc::sourceparts=- -o APT::Get::List-Cleanup=0 \
    -o APT::Update::Error-Mode=any \
    -o Acquire::Retries=3 -o Acquire::http::Timeout=45 \
    -o Acquire::https::Timeout=45 -o DPkg::Use-Pty=0 update
)
