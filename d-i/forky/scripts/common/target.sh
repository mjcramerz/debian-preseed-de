#!/bin/sh

target_is_mounted() {
  if command -v installer_target_is_mounted >/dev/null 2>&1; then
    installer_target_is_mounted
    return "$?"
  fi
  [ -d /target ] || return 1
  installer_mounts_has_mountpoint /target /proc/mounts
}

target_mount_source() {
  mountpoint=$1
  installer_mount_source_for_mountpoint "$mountpoint" /proc/mounts
}

target_normalize_systemd_config_parent_modes() {
  target_systemd_config_path=$1
  target_systemd_config_root=${2:-${INSTALLER_TARGET_DIR:-/target}}

  case "$target_systemd_config_path" in
    /etc/systemd/system|/etc/systemd/system/*)
      target_systemd_config_scope=system
      ;;
    /etc/systemd/user|/etc/systemd/user/*)
      target_systemd_config_scope=user
      ;;
    *)
      return 0
      ;;
  esac
  case "$target_systemd_config_root" in
    /*) target_systemd_config_root=${target_systemd_config_root%/} ;;
    *) installer_fatal "target root must be absolute before normalizing systemd config parents: ${target_systemd_config_root:-unset}" ;;
  esac

  install -d -m 0755 \
    "${target_systemd_config_root}/etc/systemd" \
    "${target_systemd_config_root}/etc/systemd/${target_systemd_config_scope}"
  chmod 0755 \
    "${target_systemd_config_root}/etc/systemd" \
    "${target_systemd_config_root}/etc/systemd/${target_systemd_config_scope}"
}

ensure_target_sys_rbind_mount() {
  target_root=${1:-/target}

  case "$target_root" in
    /*) ;;
    *)
      installer_fatal "target root must be absolute before binding /sys: ${target_root:-unset}"
      ;;
  esac

  [ -d /sys ] || installer_fatal "installer /sys is unavailable before binding into target"

  target_sys="${target_root%/}/sys"
  install -d -m 0755 "$target_sys"

  if ! target_mount_source "$target_sys" >/dev/null 2>&1; then
    installer_info "binding installer /sys into ${target_sys} for target package configuration"
    mount --rbind /sys "$target_sys" || \
      installer_fatal "failed to bind installer /sys into ${target_sys}"
  fi

  mount --make-rslave "$target_sys" || \
    installer_fatal "failed to mark ${target_sys} as rslave after binding installer /sys"
}

live_mount_options() {
  printf '%s\n' "$1" | sed \
    -e 's/\(^\|,\)x-systemd[^,]*//g' \
    -e 's/,,*/,/g' \
    -e 's/^,//' \
    -e 's/,$//'
}

canonical_device_path() {
  dev=$1
  readlink -f "$dev" 2>/dev/null || printf '%s\n' "$dev"
}

same_device_path() {
  left=$(canonical_device_path "$1")
  right=$(canonical_device_path "$2")
  [ "$left" = "$right" ]
}

ensure_target_mount() {
  dev=$1
  mountpoint=$2
  fstype=$3
  options=$4
  label=$5
  live_options=$(live_mount_options "$options")

  [ -b "$dev" ] || installer_fatal "${label} device is missing or not a block device: ${dev}"
  [ -n "$live_options" ] || installer_fatal "live mount options are empty for ${label}"

  install -d -m 0755 "$mountpoint"
  if mounted_src=$(target_mount_source "$mountpoint"); then
    if ! same_device_path "$mounted_src" "$dev"; then
      installer_fatal "${mountpoint} is mounted from ${mounted_src}, expected ${dev}"
    fi
    return 0
  fi

  installer_info "mounting ${label}: ${dev} -> ${mountpoint}"
  if ! mount -t "$fstype" -o "$live_options" "$dev" "$mountpoint"; then
    installer_fatal "failed to mount ${label} device ${dev} on ${mountpoint}"
  fi
}

write_target_file() {
  target_path=$1
  target_mode=$2
  target_normalize_systemd_config_parent_modes "$target_path" /target
  install -d -m 0755 "$(dirname "/target${target_path}")"
  chmod 0755 "$(dirname "/target${target_path}")"
  cat >"/target${target_path}"
  chmod "$target_mode" "/target${target_path}"
}

shell_single_quote() {
  printf "'"
  printf '%s' "$1" | sed "s/'/'\\\\''/g"
  printf "'"
}

write_shell_config_var() {
  key=$1
  value=$2

  case "$key" in
    [A-Z_][A-Z0-9_]*) ;;
    *)
      installer_fatal "invalid shell config key: ${key}"
      ;;
  esac

  printf '%s=' "$key"
  shell_single_quote "$value"
  printf '\n'
}

filter_in_target_noise() {
  sed '/^in-target: warning: .*\/target\/etc\/mtab .*symlink/d'
}

target_root_dir() {
  printf '%s\n' "${INSTALLER_TARGET_DIR:-/target}"
}

target_exec_available() {
  target_root=$(target_root_dir)

  case "$target_root" in
    /target|/target/)
      command -v in-target >/dev/null 2>&1 && return 0
      ;;
  esac

  command -v chroot >/dev/null 2>&1 && [ -d "$target_root" ]
}

target_exec() {
  target_root=$(target_root_dir)

  case "$target_root" in
    /target|/target/)
      if command -v in-target >/dev/null 2>&1; then
        (
          unset \
            DEBCONF_DB_REPLACE \
            DEBCONF_REDIR \
            DEBCONF_FRONTEND \
            DEBCONF_NONINTERACTIVE_SEEN \
            DEBCONF_SYSTEMRC \
            DEBCONF_PIPE \
            DEBCONF_USE_CDEBCONF \
            DEBCONF_DEBUG \
            DEBCONF_NOWARNINGS \
            DEBCONF_TERSE \
            DEBIAN_FRONTEND
          in-target --pass-stdout "$@"
        )
        return
      fi
      ;;
  esac

  if command -v chroot >/dev/null 2>&1 && [ -d "$target_root" ]; then
    chroot "$target_root" /usr/bin/env -i \
      PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
      "$@"
    return
  fi

  if command -v in-target >/dev/null 2>&1; then
    installer_fatal "in-target cannot execute non-default installer target root: ${target_root}"
  fi

  installer_fatal "neither chroot nor in-target is available for target command execution"
}

target_command_failure_state_path() {
  printf '%s/state/last-target-command.failure\n' "$(installer_runtime_dir)"
}

target_clear_command_failure_state() {
  target_failure_state_path=$(target_command_failure_state_path)
  rm -f "$target_failure_state_path"
}

target_record_command_failure() {
  target_failure_label=$1
  target_failure_status=$2
  target_failure_state_path=$(target_command_failure_state_path)
  target_failure_state_tmp="${target_failure_state_path}.tmp.$$"
  target_failure_state_dir=$(dirname "$target_failure_state_path")
  target_failure_label=$(printf '%s' "$target_failure_label" | tr '\r\n' '  ')

  case "$target_failure_status" in
    ''|*[!0-9]*) target_failure_status=1 ;;
  esac

  install -d -m 0700 "$target_failure_state_dir"
  {
    printf 'status=%s\n' "$target_failure_status"
    printf 'label=%s\n' "$target_failure_label"
  } >"$target_failure_state_tmp"
  chmod 0600 "$target_failure_state_tmp" 2>/dev/null || true
  mv "$target_failure_state_tmp" "$target_failure_state_path"
}

print_command() {
  for arg in "$@"; do
    printf ' %s' "$arg"
  done
  printf '\n'
}

target_log_should_emit() {
  if command -v installer_log_should_emit >/dev/null 2>&1; then
    installer_log_should_emit "$1"
    return "$?"
  fi
  return 0
}

target_log_route_for_label() {
  target_route_label=$1

  TARGET_LOG_CATEGORY=$(installer_log_category_for_target_command "$target_route_label" 2>/dev/null || printf '%s\n' late)
  case "$TARGET_LOG_CATEGORY" in
    apt|package) TARGET_LOG_STAGE=package_install ;;
    bootloader) TARGET_LOG_STAGE=bootloader ;;
    *) TARGET_LOG_STAGE=target_customization ;;
  esac
}

target_log_epoch() {
  if command -v installer_log_epoch >/dev/null 2>&1; then
    installer_log_epoch
  else
    date -u '+%s' 2>/dev/null || printf '\n'
  fi
}

target_log_duration_field() {
  target_log_end_epoch=$(target_log_epoch)
  case "$target_log_end_epoch:${TARGET_LOG_START_EPOCH:-}" in
    [0-9]*:[0-9]*)
      printf ' duration_seconds=%s' "$((target_log_end_epoch - TARGET_LOG_START_EPOCH))"
      ;;
  esac
}

target_output_line_count() {
  target_output_file=$1
  [ -s "$target_output_file" ] || {
    printf '%s\n' 0
    return 0
  }
  target_output_lines=$(wc -l <"$target_output_file" 2>/dev/null || printf '0')
  target_output_lines=${target_output_lines##* }
  case "$target_output_lines" in
    ''|*[!0-9]*) target_output_lines=0 ;;
  esac
  printf '%s\n' "$target_output_lines"
}

target_log_command_start() {
  target_clear_command_failure_state
  target_log_route_for_label "$1"
  TARGET_LOG_START_EPOCH=$(target_log_epoch)
  installer_append_log_category "$TARGET_LOG_CATEGORY" "$TARGET_LOG_STAGE" info in-target "start $1" || true
}

target_log_command_complete() {
  target_output_lines=$(target_output_line_count "$2")
  installer_log_target_command_output "$TARGET_LOG_CATEGORY" "$TARGET_LOG_STAGE" in-target "$2" || true
  installer_append_log_category "$TARGET_LOG_CATEGORY" "$TARGET_LOG_STAGE" info in-target "completed $1$(target_log_duration_field) output_lines=${target_output_lines}" || true
}

target_log_command_failure() {
  target_output_lines=$(target_output_line_count "$4")
  if [ "$3" = error ]; then
    target_record_command_failure "$1" "$2"
  fi
  installer_append_log_category "$TARGET_LOG_CATEGORY" "$TARGET_LOG_STAGE" "$3" in-target "failed $1 status=$2$(target_log_duration_field) output_lines=${target_output_lines}" || true
  installer_log_target_command_output "$TARGET_LOG_CATEGORY" "$TARGET_LOG_STAGE" in-target "$4" "$3" || true
}

run_in_target() {
  label=$1
  shift
  output=$(installer_runtime_temp_log_path install-in-target.log)

  installer_info "in-target: ${label}"
  target_log_command_start "$label"
  if target_exec "$@" </dev/null >"$output" 2>&1; then
    target_log_command_complete "$label" "$output"
    if target_log_should_emit info; then
      filter_in_target_noise <"$output"
    fi
    rm -f "$output"
    return 0
  else
    code=$?
  fi

  installer_error "in-target failed during ${label} (status ${code}):"
  if target_log_should_emit error; then
    print_command "$@" >&2
    cat "$output" >&2
  fi
  target_log_command_failure "$label" "$code" error "$output"
  rm -f "$output"
  exit "$code"
}

attempt_in_target() {
  label=$1
  shift
  output=$(installer_runtime_temp_log_path install-in-target.log)

  installer_info "in-target: ${label}"
  target_log_command_start "$label"
  if target_exec "$@" </dev/null >"$output" 2>&1; then
    target_log_command_complete "$label" "$output"
    if target_log_should_emit info; then
      filter_in_target_noise <"$output"
    fi
    rm -f "$output"
    return 0
  else
    code=$?
  fi

  installer_warn "in-target failed during ${label} (status ${code}):"
  if target_log_should_emit warning; then
    print_command "$@" >&2
    cat "$output" >&2
  fi
  target_log_command_failure "$label" "$code" warning "$output"
  rm -f "$output"
  return "$code"
}

run_in_target_quiet() {
  label=$1
  shift
  output=$(installer_runtime_temp_log_path install-in-target.log)

  installer_info "in-target: ${label}"
  target_log_command_start "$label"
  if target_exec "$@" </dev/null >"$output" 2>&1; then
    target_log_command_complete "$label" "$output"
    rm -f "$output"
    return 0
  else
    code=$?
  fi

  installer_error "in-target failed during ${label} (status ${code}):"
  if target_log_should_emit error; then
    print_command "$@" >&2
    cat "$output" >&2
  fi
  target_log_command_failure "$label" "$code" error "$output"
  rm -f "$output"
  exit "$code"
}

run_in_target_interactive() {
  label=$1
  shift

  [ -c /dev/tty ] || {
    installer_fatal "interactive in-target command requires /dev/tty: ${label}"
  }

  installer_info "in-target interactive: ${label}"
  target_log_command_start "$label"
  if target_exec "$@" </dev/tty >/dev/tty 2>&1; then
    target_log_command_complete "$label" /dev/null
    return 0
  else
    code=$?
  fi

  installer_error "in-target interactive command failed during ${label} (status ${code}):"
  if target_log_should_emit error; then
    print_command "$@" >&2
  fi
  target_log_command_failure "$label" "$code" error /dev/null
  exit "$code"
}

capture_in_target() {
  label=$1
  shift
  stdout_file=$(installer_runtime_temp_log_path install-in-target-stdout.log)
  stderr_file=$(installer_runtime_temp_log_path install-in-target-stderr.log)

  target_log_command_start "$label"

  if target_exec "$@" </dev/null >"$stdout_file" 2>"$stderr_file"; then
    installer_log_target_command_output "$TARGET_LOG_CATEGORY" "$TARGET_LOG_STAGE" in-target "$stdout_file" || true
    target_log_command_complete "$label" "$stderr_file"
    filter_in_target_noise <"$stderr_file" >&2
    cat "$stdout_file"
    rm -f "$stdout_file" "$stderr_file"
    return 0
  else
    code=$?
  fi

  installer_error "in-target failed during ${label} (status ${code}):"
  print_command "$@" >&2
  cat "$stderr_file" >&2
  installer_append_log_category "$TARGET_LOG_CATEGORY" "$TARGET_LOG_STAGE" error in-target "failed ${label} status=${code}" || true
  target_record_command_failure "$label" "$code"
  installer_log_target_command_output "$TARGET_LOG_CATEGORY" "$TARGET_LOG_STAGE" in-target "$stdout_file" error || true
  installer_log_target_command_output "$TARGET_LOG_CATEGORY" "$TARGET_LOG_STAGE" in-target "$stderr_file" error || true
  rm -f "$stdout_file" "$stderr_file"
  exit "$code"
}

test_in_target() {
  output=$(installer_runtime_temp_log_path install-in-target-test.log)

  if target_exec "$@" </dev/null >"$output" 2>&1; then
    filter_in_target_noise <"$output"
    rm -f "$output"
    return 0
  fi

  filter_in_target_noise <"$output" >&2
  rm -f "$output"
  return 1
}
