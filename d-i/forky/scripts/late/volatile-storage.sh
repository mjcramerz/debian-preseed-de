#!/bin/sh
# Shared late_command volatile storage helpers. This file is sourced, not executed.

purge_target_cdrom_apt_sources() {
  require_in_target "cdrom apt source cleanup"

  # shellcheck disable=SC2016
  run_in_target_quiet "remove target cdrom apt sources" /bin/sh -c '
set -eu
strip_list_file() {
  src=$1
  [ -f "$src" ] || return 0
  tmp="${src}.tmp.$$"
  awk '\''index($0, "cdrom:") == 0 { print }'\'' "$src" >"$tmp"
  mv "$tmp" "$src"
}
strip_sources_file() {
  src=$1
  [ -f "$src" ] || return 0
  tmp="${src}.tmp.$$"
  awk '\''function flush_stanza(    line_index) {
    if (stanza_line_count == 0) {
      return
    }
    if (!drop_stanza) {
      if (wrote_stanza) {
        print ""
      }
      for (line_index = 1; line_index <= stanza_line_count; line_index++) {
        print stanza_lines[line_index]
      }
      wrote_stanza = 1
    }
    for (line_index = 1; line_index <= stanza_line_count; line_index++) {
      delete stanza_lines[line_index]
    }
    stanza_line_count = 0
    drop_stanza = 0
  }
  /^[[:space:]]*$/ {
    flush_stanza()
    next
  }
  {
    stanza_lines[++stanza_line_count] = $0
    if (index($0, "cdrom:") != 0) {
      drop_stanza = 1
    }
  }
  END {
    flush_stanza()
  }'\'' "$src" >"$tmp"
  mv "$tmp" "$src"
}

strip_list_file /etc/apt/sources.list
for src in /etc/apt/sources.list.d/*; do
  [ -f "$src" ] || continue
  case "$src" in
    *.list|*.list.*) strip_list_file "$src" ;;
    *.sources|*.sources.*) strip_sources_file "$src" ;;
  esac
done
'
}

prepare_target_volatile_dirs_for_apt() {
  require_in_target "volatile target directory repair for apt"

  # Recreate the install-time backing directories with target ownership and
  # modes before any late-command apt work. This keeps tmpfs deferred until the
  # first real boot while avoiding _apt permission failures during d-i.
  # shellcheck disable=SC2016
  run_in_target "repair target volatile directories for apt work" /bin/sh -c '
set -eu
bool_is_true() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
  esac
  return 1
}
ensure_dir() {
  path=$1
  mode=$2
  owner=$3
  group=$4
  [ -n "$path" ] || return 0
  install -d -m "$mode" "$path"
  chown "$owner:$group" "$path"
  chmod "$mode" "$path"
}
ensure_optional_apt_dir() {
  path=$1
  mode=$2
  [ -n "$path" ] || return 0
  install -d -m "$mode" "$path"
  if id -u _apt >/dev/null 2>&1; then
    chown _apt:root "$path"
  fi
  chmod "$mode" "$path"
}
tmpfs_var_log=$1
tmpfs_var_cache=$2
tmpfs_var_apt_lists=$3
tmpfs_systemd_coredump=$4
tmpfs_data_run=$5
dir_var_log=$6
dir_var_cache=$7
dir_apt_state=$8
dir_apt_lists=$9
dir_systemd=${10}
dir_systemd_coredump=${11}
dir_data_run=${12}
dir_data_run_mnt=${13}
dir_var_tmp=${14}
dir_tmp=${15}

if bool_is_true "$tmpfs_var_log"; then
  ensure_dir "$dir_var_log" 0755 root root
fi
if bool_is_true "$tmpfs_var_cache"; then
  ensure_dir "$dir_var_cache" 0755 root root
  ensure_dir "$dir_var_cache/apt" 0755 root root
  ensure_dir "$dir_var_cache/apt/archives" 0755 root root
  ensure_optional_apt_dir "$dir_var_cache/apt/archives/partial" 0700
fi
if bool_is_true "$tmpfs_var_apt_lists"; then
  ensure_dir "$dir_apt_state" 0755 root root
  ensure_dir "$dir_apt_lists" 0755 root root
  ensure_optional_apt_dir "$dir_apt_lists/partial" 0700
fi
if bool_is_true "$tmpfs_systemd_coredump"; then
  ensure_dir "$dir_systemd" 0755 root root
  ensure_dir "$dir_systemd_coredump" 0755 root root
fi
if bool_is_true "$tmpfs_data_run"; then
  ensure_dir "$dir_data_run" 0755 root root
  ensure_dir "$dir_data_run_mnt" 0755 root root
fi
ensure_dir "$dir_var_tmp" 1777 root root
ensure_dir "$dir_tmp" 1777 root root
' sh \
    "${TMPFS_VAR_LOG:-false}" \
    "${TMPFS_VAR_CACHE:-false}" \
    "${TMPFS_VAR_LIB_APT_LISTS:-false}" \
    "${TMPFS_SYSTEMD_COREDUMP:-false}" \
    "${TMPFS_DATA_RUN:-false}" \
    "${DIR_VAR_LOG:-}" \
    "${DIR_VAR_CACHE:-}" \
    "${DIR_APT_STATE:-${DIR_APT_LISTS%/lists}}" \
    "${DIR_APT_LISTS:-}" \
    "${DIR_SYSTEMD:-}" \
    "${DIR_SYSTEMD_COREDUMP:-}" \
    "${DIR_DATA_RUN:-}" \
    "${DIR_DATA_RUN_MNT:-}" \
    "${DIR_VAR_TMP:-}" \
    "${DIR_TMP:-/tmp}"

  purge_target_cdrom_apt_sources
}

prepare_target_volatile_mountpoints_for_first_boot() {
  # shellcheck disable=SC2016
  run_in_target "clean volatile mountpoints before first boot" /bin/sh -c '
set -eu
bool_is_true() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
  esac
  return 1
}
ensure_empty_dir() {
  path=$1
  mode=$2
  [ -n "$path" ] || return 0
  if [ -d "$path" ]; then
    find "$path" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
  fi
  install -d -m "$mode" "$path"
  chmod "$mode" "$path"
}
normalize_tmpfs_dir() {
  enabled=$1
  path=$2
  mode=$3
  bool_is_true "$enabled" || return 0
  ensure_empty_dir "$path" "$mode"
}
tmpfs_var_log=$1
tmpfs_var_cache=$2
tmpfs_var_apt_lists=$3
tmpfs_data_run=$4
tmpfs_systemd_coredump=$5
tmpfs_dev_shm=$6
dir_var_log=$7
dir_var_cache=$8
dir_apt_lists=$9
dir_data_run=${10}
dir_systemd_coredump=${11}
dir_tmp=${12}
dir_var_tmp=${13}
dir_dev_shm=${14}

normalize_tmpfs_dir "$tmpfs_var_log" "$dir_var_log" 0755
normalize_tmpfs_dir "$tmpfs_var_cache" "$dir_var_cache" 0755
normalize_tmpfs_dir "$tmpfs_var_apt_lists" "$dir_apt_lists" 0755
normalize_tmpfs_dir "$tmpfs_data_run" "$dir_data_run" 0755
normalize_tmpfs_dir "$tmpfs_systemd_coredump" "$dir_systemd_coredump" 0755
normalize_tmpfs_dir "$tmpfs_dev_shm" "$dir_dev_shm" 1777
ensure_empty_dir "$dir_tmp" 1777
install -d -m 1777 "$dir_var_tmp"
chmod 1777 "$dir_var_tmp"
' sh \
    "${TMPFS_VAR_LOG}" \
    "${TMPFS_VAR_CACHE}" \
    "${TMPFS_VAR_LIB_APT_LISTS}" \
    "${TMPFS_DATA_RUN}" \
    "${TMPFS_SYSTEMD_COREDUMP}" \
    "${TMPFS_DEV_SHM}" \
    "${DIR_VAR_LOG}" \
    "${DIR_VAR_CACHE}" \
    "${DIR_APT_LISTS}" \
    "${DIR_DATA_RUN}" \
    "${DIR_SYSTEMD_COREDUMP}" \
    "${DIR_TMP}" \
    "${DIR_VAR_TMP}" \
    "${DIR_DEV_SHM}"
}

stage_target_tmpfs_pre_clean_mount_override_if_enabled() {
  var_name=$1
  repo_path=$2
  target_path=$3

  if tmpfs_policy_enabled "$var_name"; then
    stage_target_asset "$repo_path" "$target_path" 0644
  else
    remove_target_asset_and_empty_parent "$target_path"
  fi
}

render_target_tmpfiles_if_tmpfs_enabled() {
  var_name=$1
  repo_path=$2
  target_path=$3

  if tmpfs_policy_enabled "$var_name"; then
    render_target_asset "$repo_path" "$target_path" 0644
  else
    remove_target_asset "$target_path"
  fi
}

dedupe_target_tmpfiles_legacy_lock() {
  legacy_conf="/target/usr/lib/tmpfiles.d/legacy.conf"
  debian_conf="/target/usr/lib/tmpfiles.d/debian.conf"
  [ -f "$legacy_conf" ] || return 0

  remove_legacy_run_lock=false
  if [ -f "$debian_conf" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
      trimmed_line=$(printf '%s' "$line" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')
      case "$trimmed_line" in
        ''|'#'*) continue ;;
      esac
      # shellcheck disable=SC2086
      set -- $trimmed_line
      if [ "${2:-}" = "/run/lock" ]; then
        remove_legacy_run_lock=true
        break
      fi
    done <"$debian_conf"
  fi

  tmp_conf="/tmp/install-legacy-tmpfiles.$$"
  seen_run_lock=false
  : >"$tmp_conf"
  while IFS= read -r line || [ -n "$line" ]; do
    trimmed_line=$(printf '%s' "$line" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')
    case "$trimmed_line" in
      ''|'#'*)
        printf '%s\n' "$line" >>"$tmp_conf"
        continue
        ;;
    esac
    # shellcheck disable=SC2086
    set -- $trimmed_line
    if [ "${2:-}" = "/run/lock" ]; then
      if [ "$remove_legacy_run_lock" = true ] || [ "$seen_run_lock" = true ]; then
        continue
      fi
      seen_run_lock=true
    fi
    printf '%s\n' "$line" >>"$tmp_conf"
  done <"$legacy_conf"

  if ! cmp -s "$legacy_conf" "$tmp_conf"; then
    install -m 0644 "$tmp_conf" "$legacy_conf"
    installer_info "removed duplicate /run/lock tmpfiles entry from ${legacy_conf#/target}"
  fi
  rm -f "$tmp_conf"
}

install_target_tmpfs_pre_clean_assets() {
  tmpfs_pre_clean_before_units=$(tmpfs_pre_clean_mount_units_for_enabled_policy)
  tmpfs_pre_clean_targets=$(tmpfs_pre_clean_targets_for_enabled_policy)

  [ -n "$tmpfs_pre_clean_before_units" ] ||
    installer_fatal "tmpfs-pre-clean.service has no mount units to order before"
  [ -n "$tmpfs_pre_clean_targets" ] ||
    installer_fatal "tmpfs-pre-clean helper has no configured cleanup targets"

  render_target_template "$TMP_ENV_DIR/tmpfs-pre-clean.tmpl" "/target${FILE_TMPFS_PRE_CLEAN_HELPER}" 0755
  render_target_template "$TMP_ENV_DIR/tmpfs-pre-clean.service.tmpl" "/target${FILE_TMPFS_PRE_CLEAN_SERVICE}" 0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/system/tmp.mount.d/override.conf)" \
    "${FILE_TMPFS_PRE_CLEAN_TMP_MOUNT_OVERRIDE}" \
    0644
  stage_target_tmpfs_pre_clean_mount_override_if_enabled TMPFS_DEV_SHM \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/system/dev-shm.mount.d/override.conf)" \
    "${FILE_TMPFS_PRE_CLEAN_DEV_SHM_MOUNT_OVERRIDE}"
  stage_target_tmpfs_pre_clean_mount_override_if_enabled TMPFS_VAR_LOG \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/system/var-log.mount.d/override.conf)" \
    "${FILE_TMPFS_PRE_CLEAN_VAR_LOG_MOUNT_OVERRIDE}"
  stage_target_tmpfs_pre_clean_mount_override_if_enabled TMPFS_VAR_CACHE \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/system/var-cache.mount.d/override.conf)" \
    "${FILE_TMPFS_PRE_CLEAN_VAR_CACHE_MOUNT_OVERRIDE}"
  stage_target_tmpfs_pre_clean_mount_override_if_enabled TMPFS_VAR_LIB_APT_LISTS \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/system/var-lib-apt-lists.mount.d/override.conf)" \
    "${FILE_TMPFS_PRE_CLEAN_APT_LISTS_MOUNT_OVERRIDE}"
  stage_target_tmpfs_pre_clean_mount_override_if_enabled TMPFS_SYSTEMD_COREDUMP \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/system/var-lib-systemd-coredump.mount.d/override.conf)" \
    "${FILE_TMPFS_PRE_CLEAN_COREDUMP_MOUNT_OVERRIDE}"
  stage_target_tmpfs_pre_clean_mount_override_if_enabled TMPFS_DATA_RUN \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/system/data-run.mount.d/override.conf)" \
    "${FILE_TMPFS_PRE_CLEAN_DATA_RUN_MOUNT_OVERRIDE}"

  remove_target_asset "/usr/local/sbin/storage-tmpfiles-refresh"
  remove_target_asset "/usr/local/sbin/tmpfs-clean"
  remove_target_asset "/etc/systemd/system/storage-tmpfs-clean.service"
  remove_target_asset "/etc/systemd/system/storage-tmpfiles-watch.service"
  remove_target_asset "/etc/systemd/system/tmpfs-clean.service"
  remove_target_asset "/etc/systemd/system/local-fs-pre.target.wants/storage-tmpfs-clean.service"
  remove_target_asset "/etc/systemd/system/sysinit.target.wants/storage-tmpfs-clean.service"
  remove_target_asset "/etc/systemd/system/sysinit.target.wants/storage-tmpfiles-watch.service"
  remove_target_asset "/etc/systemd/system/local-fs-pre.target.wants/tmpfs-clean.service"
  remove_target_asset "/etc/systemd/system/sysinit.target.wants/tmpfs-clean.service"
  remove_target_asset "/etc/systemd/system/local-fs-pre.target.wants/tmpfs-pre-clean.service"
  remove_target_asset "/etc/systemd/system/sysinit.target.wants/tmpfs-pre-clean.service"
}

install_target_tmpfs_tmpfiles_assets() {
  render_target_tmpfiles_if_tmpfs_enabled TMPFS_VAR_LOG \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/tmpfiles.d/30-var-log.conf.tmpl)" \
    "${FILE_TMPFILES_VAR_LOG_GENERATED}"
  render_target_tmpfiles_if_tmpfs_enabled TMPFS_VAR_LIB_APT_LISTS \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/tmpfiles.d/40-apt-lists.conf.tmpl)" \
    "${FILE_TMPFILES_APT_LISTS_GENERATED}"
  render_target_tmpfiles_if_tmpfs_enabled TMPFS_VAR_CACHE \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/tmpfiles.d/50-var-cache.conf.tmpl)" \
    "${FILE_TMPFILES_VAR_CACHE_GENERATED}"
  render_target_tmpfiles_if_tmpfs_enabled TMPFS_DATA_RUN \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/tmpfiles.d/20-data-run.conf.tmpl)" \
    "${FILE_DATA_RUN_TMPFILES}"

  remove_target_asset "${FILE_TMPFILES_VOLATILE_BASE}"
}

policy_bool_is_true() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
  esac
  return 1
}

policy_bool_is_false() {
  case "${1:-}" in
    0|false|FALSE|no|NO|off|OFF) return 0 ;;
  esac
  return 1
}

require_policy_bool() {
  label=$1
  value=$2
  if ! policy_bool_is_true "$value" && ! policy_bool_is_false "$value"; then
    installer_fatal "${label} must be true or false, got '${value}'"
  fi
}

validate_tmpfs_policy_env() {
  for var_name in \
    TMPFS_VAR_LOG \
    TMPFS_VAR_CACHE \
    TMPFS_VAR_LIB_APT_LISTS \
    TMPFS_DEV_SHM \
    TMPFS_DATA_RUN \
    TMPFS_SYSTEMD_COREDUMP
  do
    eval "var_value=\${$var_name-}"
    [ -n "$var_value" ] || installer_fatal "${var_name} must be set"
    require_policy_bool "$var_name" "$var_value"
  done
}

tmpfs_policy_enabled() {
  var_name=$1
  eval "var_value=\${$var_name-}"
  policy_bool_is_true "$var_value"
}

tmpfs_policy_path_if_enabled() {
  var_name=$1
  path=$2
  [ -n "$path" ] || return 0
  if tmpfs_policy_enabled "$var_name"; then
    printf '%s\n' "$path"
  fi
}

tmpfs_pre_clean_mount_unit_if_enabled() {
  var_name=$1
  mount_unit=$2
  if tmpfs_policy_enabled "$var_name"; then
    printf '%s\n' "$mount_unit"
  fi
}

tmpfs_pre_clean_mount_units_for_enabled_policy() {
  join_words \
    "tmp.mount" \
    "$(tmpfs_pre_clean_mount_unit_if_enabled TMPFS_DEV_SHM dev-shm.mount)" \
    "$(tmpfs_pre_clean_mount_unit_if_enabled TMPFS_VAR_LOG var-log.mount)" \
    "$(tmpfs_pre_clean_mount_unit_if_enabled TMPFS_VAR_CACHE var-cache.mount)" \
    "$(tmpfs_pre_clean_mount_unit_if_enabled TMPFS_VAR_LIB_APT_LISTS var-lib-apt-lists.mount)" \
    "$(tmpfs_pre_clean_mount_unit_if_enabled TMPFS_SYSTEMD_COREDUMP var-lib-systemd-coredump.mount)" \
    "$(tmpfs_pre_clean_mount_unit_if_enabled TMPFS_DATA_RUN data-run.mount)"
}

tmpfs_pre_clean_condition_line_if_enabled() {
  var_name=$1
  path=$2
  if tmpfs_policy_enabled "$var_name"; then
    printf 'ConditionPathExists=%s\nConditionPathIsDirectory=%s\nConditionPathIsMountPoint=!%s\n' "$path" "$path" "$path"
  fi
}

tmpfs_pre_clean_condition_lines_for_enabled_policy() {
  printf '%s%s%s%s%s%s%s' \
    "ConditionPathExists=${DIR_TMP}
ConditionPathIsDirectory=${DIR_TMP}
ConditionPathIsMountPoint=!${DIR_TMP}
" \
    "$(tmpfs_pre_clean_condition_line_if_enabled TMPFS_DEV_SHM "$DIR_DEV_SHM")" \
    "$(tmpfs_pre_clean_condition_line_if_enabled TMPFS_VAR_LOG "$DIR_VAR_LOG")" \
    "$(tmpfs_pre_clean_condition_line_if_enabled TMPFS_VAR_CACHE "$DIR_VAR_CACHE")" \
    "$(tmpfs_pre_clean_condition_line_if_enabled TMPFS_VAR_LIB_APT_LISTS "$DIR_APT_LISTS")" \
    "$(tmpfs_pre_clean_condition_line_if_enabled TMPFS_SYSTEMD_COREDUMP "$DIR_SYSTEMD_COREDUMP")" \
    "$(tmpfs_pre_clean_condition_line_if_enabled TMPFS_DATA_RUN "$DIR_DATA_RUN")"
}

tmpfs_pre_clean_requires_mounts_for_enabled_policy() {
  if tmpfs_policy_enabled TMPFS_DATA_RUN; then
    printf 'RequiresMountsFor=%s\n' "$DIR_DATA"
  fi
}

tmpfs_pre_clean_read_write_paths_for_enabled_policy() {
  join_words \
    "$DIR_TMP" \
    "$(tmpfs_policy_path_if_enabled TMPFS_DEV_SHM "$DIR_DEV_SHM")" \
    "$(tmpfs_policy_path_if_enabled TMPFS_VAR_LOG "$DIR_VAR_LOG")" \
    "$(tmpfs_policy_path_if_enabled TMPFS_VAR_CACHE "$DIR_VAR_CACHE")" \
    "$(tmpfs_policy_path_if_enabled TMPFS_VAR_LIB_APT_LISTS "$DIR_APT_LISTS")" \
    "$(tmpfs_policy_path_if_enabled TMPFS_SYSTEMD_COREDUMP "$DIR_SYSTEMD_COREDUMP")" \
    "$(tmpfs_policy_path_if_enabled TMPFS_DATA_RUN "$DIR_DATA_RUN")"
}

tmpfs_pre_clean_target_if_enabled() {
  var_name=$1
  label=$2
  path=$3
  if tmpfs_policy_enabled "$var_name"; then
    printf '%s|%s\n' "$label" "$path"
  fi
}

tmpfs_pre_clean_targets_for_enabled_policy() {
  join_words \
    "DIR_TMP|$DIR_TMP" \
    "$(tmpfs_pre_clean_target_if_enabled TMPFS_DEV_SHM DIR_DEV_SHM "$DIR_DEV_SHM")" \
    "$(tmpfs_pre_clean_target_if_enabled TMPFS_VAR_LOG DIR_VAR_LOG "$DIR_VAR_LOG")" \
    "$(tmpfs_pre_clean_target_if_enabled TMPFS_VAR_CACHE DIR_VAR_CACHE "$DIR_VAR_CACHE")" \
    "$(tmpfs_pre_clean_target_if_enabled TMPFS_VAR_LIB_APT_LISTS DIR_APT_LISTS "$DIR_APT_LISTS")" \
    "$(tmpfs_pre_clean_target_if_enabled TMPFS_SYSTEMD_COREDUMP DIR_SYSTEMD_COREDUMP "$DIR_SYSTEMD_COREDUMP")" \
    "$(tmpfs_pre_clean_target_if_enabled TMPFS_DATA_RUN DIR_DATA_RUN "$DIR_DATA_RUN")"
}

tmpfs_pre_clean_policy_enabled() {
  tmpfs_policy_enabled TMPFS_VAR_LOG ||
    tmpfs_policy_enabled TMPFS_VAR_CACHE ||
    tmpfs_policy_enabled TMPFS_VAR_LIB_APT_LISTS ||
    tmpfs_policy_enabled TMPFS_SYSTEMD_COREDUMP ||
    tmpfs_policy_enabled TMPFS_DATA_RUN
}

join_words() {
  result=
  for word in "$@"; do
    [ -n "$word" ] || continue
    result="${result:+$result }$word"
  done
  printf '%s\n' "$result"
}

tmpfs_policy_placeholder_map() {
  for var_name in \
    TMPFS_VAR_LOG \
    TMPFS_VAR_CACHE \
    TMPFS_VAR_LIB_APT_LISTS \
    TMPFS_DEV_SHM \
    TMPFS_DATA_RUN \
    TMPFS_SYSTEMD_COREDUMP
  do
    eval "var_value=\${$var_name-}"
    [ -n "$var_value" ] || installer_fatal "${var_name} must be set"
    require_policy_bool "$var_name" "$var_value"
    printf '%s=%s\n' "$var_name" "$var_value"
  done
}

apply_tmpfs_policy_placeholders() {
  target_path=$1
  apply_placeholder_map_to_target "$target_path" tmpfs_policy_placeholder_map
}

apply_tmpfs_pre_clean_placeholders() {
  target_path=$1
  tmpfs_pre_clean_before_units=$(tmpfs_pre_clean_mount_units_for_enabled_policy)
  tmpfs_pre_clean_condition_lines=$(tmpfs_pre_clean_condition_lines_for_enabled_policy)
  tmpfs_pre_clean_requires_mounts_for=$(tmpfs_pre_clean_requires_mounts_for_enabled_policy)
  tmpfs_pre_clean_read_write_paths=$(tmpfs_pre_clean_read_write_paths_for_enabled_policy)
  tmpfs_pre_clean_targets=$(tmpfs_pre_clean_targets_for_enabled_policy)

  installer_apply_scalar_placeholders "$target_path" "$target_path.scalar.$$" \
    FILE_TMPFS_PRE_CLEAN "$FILE_TMPFS_PRE_CLEAN_HELPER" \
    TMPFS_PRE_CLEAN_BEFORE_UNITS "$tmpfs_pre_clean_before_units" \
    TMPFS_PRE_CLEAN_READ_WRITE_PATHS "$tmpfs_pre_clean_read_write_paths" \
    TMPFS_PRE_CLEAN_TARGETS "$tmpfs_pre_clean_targets"
  mv "$target_path.scalar.$$" "$target_path"
  replace_placeholder_line_block "$target_path" "__INSTALLER_TMPFS_PRE_CLEAN_CONDITION_LINES__" "$tmpfs_pre_clean_condition_lines"
  replace_placeholder_line_block "$target_path" "__INSTALLER_TMPFS_PRE_CLEAN_REQUIRES_MOUNTS_FOR__" "$tmpfs_pre_clean_requires_mounts_for"
}
