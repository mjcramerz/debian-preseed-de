#!/bin/sh
# Sourced installer module; edit this file directly.

installer_mounts_find_record() {
  installer_mountpoint=$1
  installer_mounts_file=${2:-/proc/mounts}
  INSTALLER_MOUNT_SOURCE=
  INSTALLER_MOUNT_POINT=
  INSTALLER_MOUNT_FSTYPE=
  INSTALLER_MOUNT_OPTIONS=

  [ -r "$installer_mounts_file" ] || return 1
	  while IFS=' ' read -r mount_source mount_point mount_fstype mount_options _mount_rest || [ -n "${mount_source:-}" ]; do
	    [ "$mount_point" = "$installer_mountpoint" ] || continue
	    INSTALLER_MOUNT_SOURCE=$mount_source
	    INSTALLER_MOUNT_POINT=$mount_point
	    INSTALLER_MOUNT_FSTYPE=$mount_fstype
    INSTALLER_MOUNT_OPTIONS=$mount_options
    return 0
  done <"$installer_mounts_file"
  return 1
}

installer_mounts_has_mountpoint() {
  installer_mounts_find_record "$1" "${2:-/proc/mounts}" >/dev/null 2>&1
}

installer_mount_source_for_mountpoint() {
  installer_mounts_find_record "$1" "${2:-/proc/mounts}" || return 1
  printf '%s\n' "$INSTALLER_MOUNT_SOURCE"
}

installer_target_is_mounted() {
  [ -d /target ] || return 1
  installer_mounts_has_mountpoint /target /proc/mounts
}

installer_escape_sed_replacement() {
  printf '%s' "$1" | sed 's/[&|\\]/\\&/g'
}

installer_contains_unresolved_installer_placeholders() {
  installer_placeholder_path=$1

  [ -r "$installer_placeholder_path" ] || return 1
  LC_ALL=C grep -q '__INSTALLER_' "$installer_placeholder_path"
}

installer_assert_no_unresolved_installer_placeholders() {
  installer_placeholder_path=$1
  installer_placeholder_label=${2:-$installer_placeholder_path}

  installer_contains_unresolved_installer_placeholders "$installer_placeholder_path" || return 0

  installer_unresolved_tokens=$(
    LC_ALL=C grep -o '__INSTALLER_[A-Z0-9_]\+__' "$installer_placeholder_path" 2>/dev/null |
      sort -u |
      tr '\n' ' '
  )
  installer_unresolved_tokens=${installer_unresolved_tokens%" "}
  [ -n "$installer_unresolved_tokens" ] || installer_unresolved_tokens="unknown placeholder(s)"
  installer_fatal "${installer_placeholder_label} has unresolved installer placeholders: ${installer_unresolved_tokens}"
}

installer_replace_placeholder_in_file() {
  installer_placeholder_file=$1
  installer_placeholder=$2
  installer_placeholder_value=$3
  installer_placeholder_tmp="${installer_placeholder_file}.replace.$$"
  installer_escaped_placeholder_value=$(installer_escape_sed_replacement "$installer_placeholder_value")

  sed "s|${installer_placeholder}|${installer_escaped_placeholder_value}|g" \
    "$installer_placeholder_file" >"$installer_placeholder_tmp" || {
      rm -f "$installer_placeholder_tmp"
      return 1
    }
  mv "$installer_placeholder_tmp" "$installer_placeholder_file"
}

installer_apply_scalar_placeholders() {
  installer_placeholder_src=$1
  installer_placeholder_dest=$2
  installer_placeholder_script="${installer_placeholder_dest}.sed.$$"
  shift 2

  [ $(( $# % 2 )) -eq 0 ] || installer_fatal "placeholder replacement arguments must be name/value pairs"
  : >"$installer_placeholder_script" || {
    rm -f "$installer_placeholder_script"
    return 1
  }
  while [ "$#" -gt 1 ]; do
    installer_placeholder_name=$1
    installer_placeholder_value=$2
    shift 2
    installer_escaped_placeholder_value=$(installer_escape_sed_replacement "$installer_placeholder_value")
    printf 's|__INSTALLER_%s__|%s|g\n' \
      "$installer_placeholder_name" \
      "$installer_escaped_placeholder_value" >>"$installer_placeholder_script" || {
        rm -f "$installer_placeholder_script"
        return 1
      }
  done
  sed -f "$installer_placeholder_script" "$installer_placeholder_src" >"$installer_placeholder_dest" || {
    rm -f "$installer_placeholder_script" "$installer_placeholder_dest"
    return 1
  }
  rm -f "$installer_placeholder_script"
}

installer_copy_path_with_mode() {
  copy_src_path=$1
  copy_dest_path=$2
  copy_mode=$3
  copy_label=${4:-file}
  copy_parent_dir=$(dirname "$copy_dest_path")
  copy_tmp_path="${copy_dest_path}.tmp.$$"
  copy_err_path="${copy_tmp_path}.copy.err"

  if [ "$copy_src_path" = "$copy_dest_path" ]; then
    chmod "$copy_mode" "$copy_dest_path" 2>/dev/null || true
    return 0
  fi

  [ -d "$copy_parent_dir" ] || install -d -m 0700 "$copy_parent_dir"
  rm -f "$copy_tmp_path" "$copy_err_path"
  if cp "$copy_src_path" "$copy_tmp_path" >"$copy_err_path" 2>&1; then
    copy_status=0
  else
    copy_status=$?
  fi
  if [ "$copy_status" -ne 0 ]; then
    installer_error "failed to copy ${copy_label} from ${copy_src_path} to ${copy_dest_path} (status ${copy_status})"
    [ -s "$copy_err_path" ] && sed 's/^/[cp] /' "$copy_err_path" >&2
    rm -f "$copy_tmp_path" "$copy_err_path"
    return 1
  fi
  rm -f "$copy_err_path"
  [ -s "$copy_tmp_path" ] || installer_fatal "copied ${copy_label} is empty: ${copy_src_path}"
  mv "$copy_tmp_path" "$copy_dest_path"
  chmod "$copy_mode" "$copy_dest_path"
}

installer_log_path_is_numbered() {
  installer_check_log_path=$1
  installer_check_log_name=${installer_check_log_path##*/}

  case "$installer_check_log_name" in
    [0-9]*-*) return 0 ;;
  esac
  return 1
}

installer_log_sequence_file() {
  installer_sequence_log_dir=$1
  printf '%s/.log-sequence\n' "$installer_sequence_log_dir"
}

installer_next_log_sequence() {
  installer_sequence_log_dir=$1
  installer_sequence_path=$(installer_log_sequence_file "$installer_sequence_log_dir")
  installer_sequence_tmp="${installer_sequence_path}.tmp.$$"
  installer_current_sequence=0

  [ -d "$installer_sequence_log_dir" ] || install -d -m 0700 "$installer_sequence_log_dir"
  if [ -r "$installer_sequence_path" ]; then
    installer_current_sequence=$(cat "$installer_sequence_path" 2>/dev/null || printf '0\n')
  fi
  case "$installer_current_sequence" in
    ''|*[!0-9]*) installer_current_sequence=0 ;;
  esac

  installer_next_sequence=$((installer_current_sequence + 1))
  printf '%s\n' "$installer_next_sequence" >"$installer_sequence_tmp"
  mv "$installer_sequence_tmp" "$installer_sequence_path"
  chmod 0600 "$installer_sequence_path" 2>/dev/null || true
  printf '%s\n' "$installer_next_sequence"
}

installer_log_dir_for_path() {
  installer_dir_path=$1
  printf '%s\n' "$(dirname "$installer_dir_path")"
}

installer_basename_for_path() {
  installer_base_path=$1
  printf '%s\n' "${installer_base_path##*/}"
}

installer_runtime_log_path_requested() {
  requested_log_path=$1
  runtime_log_dir=$(installer_runtime_log_dir)

  case "$requested_log_path" in
    "${runtime_log_dir}/"*) return 0 ;;
  esac
  return 1
}

installer_resolve_runtime_log_path() {
  requested_log_path=$1
  printf '%s\n' "$requested_log_path"
}

installer_runtime_temp_log_path() {
  temp_log_name=$1
  temp_log_dir=$(installer_runtime_temp_log_dir)
  temp_log_name=${temp_log_name%.log}
  install -d -m 0700 "$temp_log_dir" 2>/dev/null || true
  printf '%s/%s-%s.err\n' "$temp_log_dir" "$$" "$temp_log_name"
}

installer_resolve_target_log_path() {
  requested_target_log_path=$1
  INSTALLER_RESOLVED_TARGET_LOG_PATH=

  [ -n "$requested_target_log_path" ] || return 1
  if installer_log_path_is_numbered "$requested_target_log_path"; then
    INSTALLER_RESOLVED_TARGET_LOG_PATH=$requested_target_log_path
    return 0
  fi

  if [ -n "${INSTALLER_LOG_TARGET_FILE_RESOLVED:-}" ] && \
     [ "${INSTALLER_LOG_TARGET_FILE:-}" = "$requested_target_log_path" ]
  then
    INSTALLER_RESOLVED_TARGET_LOG_PATH=$INSTALLER_LOG_TARGET_FILE_RESOLVED
    return 0
  fi

  target_log_dir=$(installer_log_dir_for_path "$requested_target_log_path")
  target_log_name=$(installer_basename_for_path "$requested_target_log_path")
  target_log_seq=$(installer_next_log_sequence "$target_log_dir")
  resolved_target_log_path="${target_log_dir}/${target_log_seq}-${target_log_name}"

  if [ "${INSTALLER_LOG_TARGET_FILE:-}" = "$requested_target_log_path" ]; then
    INSTALLER_LOG_TARGET_FILE_RESOLVED=$resolved_target_log_path
  fi

  INSTALLER_RESOLVED_TARGET_LOG_PATH=$resolved_target_log_path
  return 0
}

installer_copy_log_to_target() {
  log_path=$1
  target_log_file=$2

  installer_logging_enabled || return 0
  [ -s "$log_path" ] || return 0
  [ -n "$target_log_file" ] || return 0
  installer_target_is_mounted || return 0

  if installer_log_path_is_numbered "$log_path" && \
     ! installer_log_path_is_numbered "$target_log_file"
  then
    resolved_target_log_file="$(installer_log_dir_for_path "$target_log_file")/$(installer_basename_for_path "$log_path")"
  else
    installer_resolve_target_log_path "$target_log_file" || return 0
    resolved_target_log_file=$INSTALLER_RESOLVED_TARGET_LOG_PATH
  fi
  install -d -m 0700 "$(dirname "$resolved_target_log_file")"
  resolved_target_log_tmp="${resolved_target_log_file}.tmp.$$"
  if installer_redact_log_stream <"$log_path" >"$resolved_target_log_tmp" 2>/dev/null; then
    chmod 0600 "$resolved_target_log_tmp" 2>/dev/null || true
    mv -f "$resolved_target_log_tmp" "$resolved_target_log_file"
  else
    rm -f "$resolved_target_log_tmp" 2>/dev/null || true
    installer_warn "failed to sanitize installer log ${log_path}"
  fi
}

installer_persist_log_file() {
  log_path=$1
  target_log_file=$2

  # Runtime logs are archived once at the end of the installer flow.  Keep this
  # compatibility entrypoint as a no-op so phase hooks do not create partial
  # target-side log copies before finish-install runs.
  [ -n "$log_path" ] || return 0
  [ -n "$target_log_file" ] || return 0
  return 0
}

installer_init_log_file() {
  log_path=$1
  target_log_file=${2:-}
  log_context=${3:-${0##*/}}
  log_tag=${4:-}
  log_stage=${5:-}
  log_path=$(installer_resolve_runtime_log_path "$log_path")

  installer_export_logging_policy
  if ! installer_logging_enabled; then
    INSTALLER_LOG_PATH=
    INSTALLER_LOG_TARGET_FILE=
    INSTALLER_LOG_TARGET_FILE_RESOLVED=
    INSTALLER_LOG_CONTEXT=$log_context
    INSTALLER_LOG_FINALIZED=0
    INSTALLER_LOG_START_EPOCH=$(installer_log_epoch)
    [ -n "$log_tag" ] && INSTALLER_LOG_TAG=$log_tag
    if [ -n "$log_stage" ]; then
      INSTALLER_LOG_STAGE=$log_stage
    else
      INSTALLER_LOG_STAGE=$(installer_stage_from_tag "$(installer_log_tag)")
    fi
    return 0
  fi

  log_dir=$(dirname "$log_path")

  [ -d "$log_dir" ] || install -d -m 0700 "$log_dir" 2>/dev/null || true
  : >>"$log_path" || installer_fatal "unable to initialize log file: ${log_path}"
  chmod 0600 "$log_path" 2>/dev/null || true

  # shellcheck disable=SC2034 # Exposed for phase hooks sourced after logging setup.
  INSTALLER_LOG_PATH=$log_path
  INSTALLER_LOG_TARGET_FILE=$target_log_file
  INSTALLER_LOG_TARGET_FILE_RESOLVED=
  INSTALLER_LOG_CONTEXT=$log_context
  INSTALLER_LOG_FINALIZED=0
  INSTALLER_LOG_START_EPOCH=$(installer_log_epoch)
  if [ -n "$log_tag" ]; then
    INSTALLER_LOG_TAG=$log_tag
  fi
  if [ -n "$log_stage" ]; then
    INSTALLER_LOG_STAGE=$log_stage
  else
    INSTALLER_LOG_STAGE=$(installer_stage_from_tag "$(installer_log_tag)")
  fi

  exec >>"$log_path" 2>&1
  installer_info "starting ${INSTALLER_LOG_CONTEXT}"
  return 0
}

installer_init_stderr_log_file() {
  log_path=$1
  target_log_file=${2:-}
  log_context=${3:-${0##*/}}
  log_tag=${4:-}
  log_stage=${5:-}
  log_path=$(installer_resolve_runtime_log_path "$log_path")

  installer_export_logging_policy
  if ! installer_logging_enabled; then
    INSTALLER_LOG_PATH=
    INSTALLER_LOG_TARGET_FILE=
    INSTALLER_LOG_TARGET_FILE_RESOLVED=
    INSTALLER_LOG_CONTEXT=$log_context
    INSTALLER_LOG_FINALIZED=0
    INSTALLER_LOG_START_EPOCH=$(installer_log_epoch)
    [ -n "$log_tag" ] && INSTALLER_LOG_TAG=$log_tag
    if [ -n "$log_stage" ]; then
      INSTALLER_LOG_STAGE=$log_stage
    else
      INSTALLER_LOG_STAGE=$(installer_stage_from_tag "$(installer_log_tag)")
    fi
    return 0
  fi

  log_dir=$(dirname "$log_path")

  [ -d "$log_dir" ] || install -d -m 0700 "$log_dir" 2>/dev/null || true
  : >>"$log_path" || installer_fatal "unable to initialize log file: ${log_path}"
  chmod 0600 "$log_path" 2>/dev/null || true

  # shellcheck disable=SC2034 # Exposed for phase hooks sourced after logging setup.
  INSTALLER_LOG_PATH=$log_path
  INSTALLER_LOG_TARGET_FILE=$target_log_file
  INSTALLER_LOG_TARGET_FILE_RESOLVED=
  INSTALLER_LOG_CONTEXT=$log_context
  INSTALLER_LOG_FINALIZED=0
  INSTALLER_LOG_START_EPOCH=$(installer_log_epoch)
  if [ -n "$log_tag" ]; then
    INSTALLER_LOG_TAG=$log_tag
  fi
  if [ -n "$log_stage" ]; then
    INSTALLER_LOG_STAGE=$log_stage
  else
    INSTALLER_LOG_STAGE=$(installer_stage_from_tag "$(installer_log_tag)")
  fi

  exec 2>>"$log_path"
  installer_info "starting ${INSTALLER_LOG_CONTEXT}"
  return 0
}

installer_finalize_log() {
  exit_code=${1:-0}

  if [ "${INSTALLER_LOG_FINALIZED:-0}" -eq 1 ]; then
    return 0
  fi
  INSTALLER_LOG_FINALIZED=1

  log_context=${INSTALLER_LOG_CONTEXT:-${0##*/}}
  log_duration=
  if [ -n "${INSTALLER_LOG_START_EPOCH:-}" ]; then
    log_end_epoch=$(installer_log_epoch)
    case "$log_end_epoch:${INSTALLER_LOG_START_EPOCH:-}" in
      [0-9]*:[0-9]*)
        log_duration=" duration_seconds=$((log_end_epoch - INSTALLER_LOG_START_EPOCH))"
        ;;
    esac
  fi
  if [ "$exit_code" -eq 0 ]; then
    installer_info "completed ${log_context}${log_duration}"
  else
    installer_error "${log_context} exited with status ${exit_code}${log_duration}"
    if [ "${INSTALLER_LIFECYCLE_ACTIVE:-0}" = 1 ]; then
      installer_record_failure "$exit_code" "$log_context" 'mandatory operation failed; see preceding diagnostics' || :
    fi
  fi

  if installer_bool_is_true "${INSTALLER_ARCHIVE_LOGS_ON_FINALIZE:-false}"; then
    installer_archive_logs_to_target || true
  fi
}

installer_fatal() {
  installer_log_record error "$*"
  if [ "${INSTALLER_LIFECYCLE_ACTIVE:-0}" = 1 ]; then
    installer_record_failure 1 "${INSTALLER_LOG_CONTEXT:-unknown}" "$*" || :
  fi
  exit 1
}

installer_shell_quote() {
  printf "'%s'" "$(printf '%s' "${1-}" | sed "s/'/'\\\\''/g")"
}

# Quote the VALUE inside a double-quoted Environment="KEY=value" unit entry.
# Reject controls; escape unit syntax and literal percent specifiers. Never eval.
installer_systemd_environment_value() (
  [ "$#" -eq 1 ] || exit 64
  LC_ALL=C; export LC_ALL
  # case sees embedded/trailing newlines, unlike a line-oriented grep. These
  # bootstrap values are bounded ASCII identifiers, paths and command flags.
  case "$1" in *[![:print:]]*)
    printf '%s\n' 'fatal: non-printable systemd environment value' >&2; exit 1 ;;
  esac
  [ "${#1}" -le 4096 ] || exit 1
  printf '%s' "$1" | sed 's/[\\"]/\\&/g; s/%/%%/g'
)

# Validate and escape before substitution, propagating failures instead of
# hiding them inside nested command-substitution arguments to a renderer.
installer_apply_systemd_environment_placeholders() (
  set -eu
  environment_input=$1
  environment_output=$2
  shift 2
  remaining=$#
  [ $((remaining % 2)) -eq 0 ] || exit 64
  while [ "$remaining" -gt 0 ]; do
    environment_name=$1
    environment_value=$(installer_systemd_environment_value "$2") || exit 1
    shift 2
    set -- "$@" "$environment_name" "$environment_value"
    remaining=$((remaining - 2))
  done
  installer_apply_scalar_placeholders "$environment_input" "$environment_output" "$@"
)

