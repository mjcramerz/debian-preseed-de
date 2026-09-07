#!/bin/sh

# BEGIN EMBEDDED DEBCONF
#!/bin/sh
# Canonical debconf transport. Embedded in common/lib.sh and runtime/common.sh.
# d-i's shell debconf-set-selections is NOT the installed system's Perl tool:
# it requires a filename, has no --checkonly, and uses stdin + FD 3 as a live
# protocol connection. Never pipe answer data into that connection.

installer_debconf_error() {
  printf '[installer-debconf] error: %s\n' "$*" >&2
}

# Use the inherited frontend when present. Starting debconf-communicate against
# its database would introduce a second writer and can lose in-memory changes.
# The caller must preserve stdin (including inside read loops). FDs 3-6 belong
# to d-i; stdout here is solely a returned VALUE, never the protocol connection.
installer_debconf_request() (
  set +x
  set +v
  set -f
  IFS=' '
  [ "$#" -gt 0 ] || exit 125
  idb_request=$*
  case "$idb_request" in
    *'
'*|*"$(printf '\r')"*)
      installer_debconf_error 'multiline protocol requests are forbidden'
      exit 125 ;;
  esac
  if [ -n "${DEBIAN_HAS_FRONTEND:-}" ]; then
    # Lifecycle entry initializes confmodule BEFORE any logging redirection.
    # An uninitialized inherited connection must not be guessed from stdout.
    if [ -z "${DEBCONF_REDIR:-}" ]; then
      installer_debconf_error 'frontend descriptors were not initialized'
      exit 125
    fi
    if ! printf '%s\n' "$idb_request" >&3; then
      installer_debconf_error 'cannot write to inherited frontend'
      exit 125
    fi
    if ! IFS= read -r idb_reply; then
      installer_debconf_error 'frontend reply stream closed; refusing to continue'
      exit 125
    fi
  else
    command -v debconf-communicate >/dev/null 2>&1 || {
      installer_debconf_error 'debconf-communicate is unavailable outside d-i'
      exit 125
    }
    if idb_reply=$(printf '%s\n' "$idb_request" | debconf-communicate 2>/dev/null); then
      :
    else
      idb_rc=$?
      installer_debconf_error "debconf-communicate exited with status $idb_rc"
      exit "$idb_rc"
    fi
  fi
  # Never return unvalidated text as a shell exit status, and never log replies:
  # a malformed reply might contain a password rather than a protocol status.
  case "$idb_reply" in *'
'*) installer_debconf_error 'multiple frontend replies'; exit 125 ;; esac
  idb_status=${idb_reply%% *}
  case "$idb_status" in
    [0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5]) ;;
    *) installer_debconf_error 'invalid frontend reply status'; exit 125 ;;
  esac
  case "$idb_reply" in *' '*) idb_value=${idb_reply#* } ;; *) idb_value= ;; esac
  case "$idb_status" in
    0) printf '%s\n' "$idb_value" ;;
    1)
      if [ -x /usr/lib/cdebconf/debconf-escape ]; then
        printf '%s' "$idb_value" | /usr/lib/cdebconf/debconf-escape -u
      elif command -v debconf-escape >/dev/null 2>&1; then
        printf '%s' "$idb_value" | debconf-escape -u
      else
        installer_debconf_error 'escaped reply without a decoder'
        exit 125
      fi ;;
    *) exit "$idb_status" ;;
  esac
)

installer_debconf_apply_file() (
  set +x
  set +v
  umask 077
  idb_file=$1
  [ -f "$idb_file" ] && [ ! -L "$idb_file" ] && [ -r "$idb_file" ] || {
    installer_debconf_error 'answer file is not a readable regular non-symlink file'
    exit 125
  }
  command -v debconf-set-selections >/dev/null 2>&1 || {
    installer_debconf_error 'required debconf-set-selections tool is unavailable'
    exit 125
  }
  idb_work=$(mktemp -d /tmp/installer-debconf.XXXXXX) || exit 125
  # Diagnostics can contain selections. Keep them private; do not echo them.
  # Successful calls clean up. Failed calls retain diagnostics for recovery.
  if debconf-set-selections "$idb_file" 2>"$idb_work/stderr"; then
    rm -rf "$idb_work"
  else
    idb_rc=$?
    installer_debconf_error "debconf-set-selections failed with status $idb_rc; private diagnostics: $idb_work/stderr"
    exit "$idb_rc"
  fi
)

installer_debconf_seed_value() (
  set +x
  set +v
  umask 077
  [ "$#" -eq 4 ] || exit 125
  idb_owner=$1; idb_question=$2; idb_type=$3; idb_value=$4
  for idb_token in "$idb_owner" "$idb_question" "$idb_type"; do
    case "$idb_token" in ''|*[!A-Za-z0-9_./+:-]*)
      installer_debconf_error 'invalid selection identifier'; exit 125 ;; esac
  done
  case "$idb_value" in *'
'*|*"$(printf '\r')"*)
    installer_debconf_error 'multiline selection value'; exit 125 ;; esac
  idb_work=$(mktemp -d /tmp/installer-selection.XXXXXX) || exit 125
  # Cleanup must not replace an earlier failure, even under inherited errexit.
  # A cleanup failure after otherwise successful work is still an error.
  trap '
    idb_rc=$?
    trap - 0
    if rm -rf "$idb_work"; then :; else
      idb_cleanup_rc=$?
      [ "$idb_rc" -ne 0 ] || idb_rc=$idb_cleanup_rc
    fi
    exit "$idb_rc"
  ' 0
  # Empty registration avoids treating a literal terminal backslash as a
  # continuation. Send the actual value over the protocol only when needed.
  case "$idb_value" in *\\) idb_registration= ;; *) idb_registration=$idb_value ;; esac
  printf '%s %s %s %s\n' "$idb_owner" "$idb_question" "$idb_type" "$idb_registration" >"$idb_work/answers"
  installer_debconf_apply_file "$idb_work/answers" || exit "$?"
  if [ "$idb_registration" != "$idb_value" ]; then
    installer_debconf_request SET "$idb_question" "$idb_value" >/dev/null || exit "$?"
    installer_debconf_request FSET "$idb_question" seen true >/dev/null || exit "$?"
  fi
)
# END EMBEDDED DEBCONF
# Shared runtime helpers for storage-family installer scripts.
# This file is sourced before scripts/runtime/{btrfs,f2fs}.sh.

runtime_fatal() {
  if command -v installer_fatal >/dev/null 2>&1; then
    installer_fatal "$@"
  fi
  echo "fatal: $*" >&2
  exit 1
}

runtime_cmdline() {
  if [ -n "${INSTALLER_CMDLINE:-}" ]; then
    printf '%s\n' "$INSTALLER_CMDLINE"
    return 0
  fi

  if [ "${RUNTIME_CMDLINE_CACHE_READY:-0}" -eq 1 ]; then
    printf '%s\n' "${RUNTIME_CMDLINE_CACHE:-}"
    return 0
  fi

  if [ -n "${INSTALLER_CMDLINE_FILE:-}" ] && [ -r "${INSTALLER_CMDLINE_FILE}" ]; then
    RUNTIME_CMDLINE_CACHE=$(cat "${INSTALLER_CMDLINE_FILE}" 2>/dev/null || true)
  elif [ -r /proc/cmdline ]; then
    RUNTIME_CMDLINE_CACHE=$(cat /proc/cmdline 2>/dev/null || true)
  else
    RUNTIME_CMDLINE_CACHE=
  fi

  RUNTIME_CMDLINE_CACHE_READY=1
  printf '%s\n' "$RUNTIME_CMDLINE_CACHE"
}

# BEGIN EMBEDDED INITRD CREDENTIALS
#!/bin/sh
# Canonical initrd credential reader. tools/build.py embeds this file in both
# common libraries: no new network fetch or source-path discovery is needed.
# /preseed.env remains TRUSTED SHELL CODE, not an untrusted dotenv import.
# Return codes: 0=value, 1=unmapped/missing/empty, 2=unsafe or unreadable file.

preseed_env_variable_name() {
  case "${1:-}" in
    netcfg/wireless_wpa|wireless_wpa|wifi_wpa) printf '%s\n' PRESEED_WIFI_PASSPHRASE ;;
    fruux_username) printf '%s\n' PRESEED_FRUUX_USERNAME ;;
    fruux_password) printf '%s\n' PRESEED_FRUUX_PASSWORD ;;
    primary_user) printf '%s\n' PRESEED_PRIMARY_USERNAME ;;
    primary_password) printf '%s\n' PRESEED_PRIMARY_PASSWORD ;;
    primary_gpg_passphrase) printf '%s\n' PRESEED_PRIMARY_GPG_PASSPHRASE ;;
    root_password) printf '%s\n' PRESEED_ROOT_PASSWORD ;;
    crowdsec_token|crowdsec_enroll_token|crowdsec_attachment_key) printf '%s\n' PRESEED_CROWDSEC_TOKEN ;;
    tailscale_authkey|tailscale_auth_key) printf '%s\n' PRESEED_TAILSCALE_TOKEN ;;
    telegram_chat_id) printf '%s\n' PRESEED_TELEGRAM_CHAT_ID ;;
    telegram_api_key) printf '%s\n' PRESEED_TELEGRAM_API_KEY ;;
    cf_r2_access_key) printf '%s\n' PRESEED_CF_APTLY_ACCESS_KEY ;;
    cf_r2_secret_key) printf '%s\n' PRESEED_CF_APTLY_SECRET_KEY ;;
    obs_username) printf '%s\n' PRESEED_OBS_USERNAME ;;
    obs_password) printf '%s\n' PRESEED_OBS_PASSWORD ;;
    *) return 1 ;;
  esac
}

preseed_env_error() {
  # Never include file contents, command-line text, or a secret in diagnostics.
  printf '[credentials] error: %s\n' "$*" >&2
  return 2
}

preseed_env_check_file() (
  set +x
  set +v
  set -f
  IFS=' 	
'
  preseed_check_path=$1
  case "$preseed_check_path" in
    /*) ;;
    *) preseed_env_error 'credential file path must be absolute'; return 2 ;;
  esac
  case "$preseed_check_path" in
    *[![:print:]]*|*/../*|*/./*|*//*)
      preseed_env_error 'credential file path is not canonical'; return 2 ;;
  esac
  if [ -L "$preseed_check_path" ]; then
    preseed_env_error 'credential file must not be a symlink'; return 2
  fi
  [ -e "$preseed_check_path" ] || return 1
  if [ ! -f "$preseed_check_path" ] || [ ! -r "$preseed_check_path" ]; then
    preseed_env_error 'credential file must be a readable regular file'; return 2
  fi
  preseed_check_uid=$(id -u) || {
    preseed_env_error 'cannot determine installer UID'; return 2;
  }
  # Debian busybox-udeb deliberately has no stat applet. Numeric ls metadata
  # uses applets present in the real initrd, not just full desktop BusyBox.
  preseed_check_metadata=$(LC_ALL=C ls -ldn "$preseed_check_path" 2>/dev/null) || {
    preseed_env_error 'cannot inspect credential file with ls -ldn'; return 2;
  }
  set -- $preseed_check_metadata
  if [ "$#" -lt 4 ] || [ "$3" != "$preseed_check_uid" ] || [ "$2" != 1 ]; then
    preseed_env_error 'credential file must be owned by the installer UID (root in d-i) and have one hard link'; return 2
  fi
  preseed_check_mode=$1
  case "$preseed_check_mode" in
    -r--------|-rw-------) ;;
    -r--r-----|-r-----r--|-r--r--r--|-rw-r-----|-rw----r--|-rw-r--r--)
      # Initrd builders often preserve 0644. These files are not writable by
      # other users: reduce read access before sourcing rather than ignoring.
      ;;
    *)
      preseed_env_error 'credential file has unsafe permissions; use root ownership and mode 0400 or 0600'; return 2 ;;
  esac
  # Reject replaceable path components before sourcing root-owned shell code.
  # A root/invoking-UID-owned sticky directory (e.g. /tmp) is safe for files
  # owned by that UID. Do not follow symlinked directories.
  preseed_check_parent=${preseed_check_path%/*}
  [ -n "$preseed_check_parent" ] || preseed_check_parent=/
  while :; do
    if [ -L "$preseed_check_parent" ] || [ ! -d "$preseed_check_parent" ]; then
      preseed_env_error 'credential file has a symlinked or invalid parent directory'; return 2
    fi
    preseed_check_metadata=$(LC_ALL=C ls -ldn "$preseed_check_parent" 2>/dev/null) || {
      preseed_env_error 'cannot inspect credential parent directory'; return 2;
    }
    set -- $preseed_check_metadata
    if [ "$#" -lt 4 ] || { [ "$3" != 0 ] && [ "$3" != "$preseed_check_uid" ]; }; then
      preseed_env_error 'credential parent directory is not trusted'; return 2
    fi
    case "$1" in
      ?????w????|????????w?)
        case "$1" in
          ?????????t|?????????T) ;;
          *) preseed_env_error 'credential parent directory is writable by other users without sticky protection'; return 2 ;;
        esac ;;
    esac
    [ "$preseed_check_parent" != / ] || break
    preseed_check_parent=${preseed_check_parent%/*}
    [ -n "$preseed_check_parent" ] || preseed_check_parent=/
  done
  case "$preseed_check_mode" in
    -r--------|-rw-------) ;;
    *)
      chmod 0600 "$preseed_check_path" 2>/dev/null || {
        preseed_env_error 'cannot make initrd credentials private; rebuild the initrd with mode 0600'; return 2;
      }
      preseed_check_metadata=$(LC_ALL=C ls -ldn "$preseed_check_path" 2>/dev/null) || return 2
      set -- $preseed_check_metadata
      if [ "$1:$2:$3" != "-rw-------:1:$preseed_check_uid" ]; then
        preseed_env_error 'credential file metadata changed while hardening'; return 2
      fi
      printf '[credentials] made initrd credential file private (0600); preserve this mode when rebuilding the USB\n' >&2
      ;;
  esac
)

preseed_env_read_value() (
  set +x
  set +v
  set -f
  IFS=' 	
'
  umask 077
  preseed_read_name=$(preseed_env_variable_name "${1:-}") || return 1
  preseed_read_file=${INSTALLER_PRESEED_ENV_FILE:-/preseed.env}
  preseed_env_check_file "$preseed_read_file" || return $?

  # Normalize only line terminators and an initial UTF-8 BOM. A private copy
  # avoids modifying the initrd's contents. All source output is suppressed:
  # an accidental echo or shell error must not enter password/log streams.
  preseed_read_tmp=$(mktemp /tmp/preseed-env.XXXXXX) || {
    preseed_env_error 'cannot create private credential staging file'; return 2;
  }
  trap 'rm -f "$preseed_read_tmp"' 0
  trap 'exit 2' 1 2 3 15
  preseed_read_cr=$(printf '\r')
  preseed_read_bom=$(printf '\357\273\277')
  if ! LC_ALL=C sed "1s/^${preseed_read_bom}//;s/${preseed_read_cr}\$//" \
      "$preseed_read_file" >"$preseed_read_tmp" 2>/dev/null; then
    preseed_env_error 'cannot normalize credential file'; return 2
  fi
  if ! /bin/sh -n "$preseed_read_tmp" >/dev/null 2>&1; then
    preseed_env_error 'credential file has invalid shell syntax; check assignment quoting without displaying passwords'; return 2
  fi
  unset PRESEED_WIFI_PASSPHRASE PRESEED_FRUUX_USERNAME PRESEED_FRUUX_PASSWORD \
    PRESEED_PRIMARY_USERNAME PRESEED_PRIMARY_PASSWORD PRESEED_PRIMARY_GPG_PASSPHRASE \
    PRESEED_ROOT_PASSWORD PRESEED_CROWDSEC_TOKEN PRESEED_TAILSCALE_TOKEN \
    PRESEED_TELEGRAM_CHAT_ID PRESEED_TELEGRAM_API_KEY PRESEED_CF_APTLY_ACCESS_KEY \
    PRESEED_CF_APTLY_SECRET_KEY PRESEED_OBS_USERNAME PRESEED_OBS_PASSWORD
  # shellcheck disable=SC1090
  if ! . "$preseed_read_tmp" >/dev/null 2>&1; then
    preseed_env_error 'credential file failed while loading trusted shell assignments'; return 2
  fi
  # The only inserted text is an identifier from the fixed mapping above.
  # The value is expanded once as data, never re-evaluated as shell input.
  eval 'preseed_read_result=${'"$preseed_read_name"'-}'
  [ -n "$preseed_read_result" ] || return 1
  printf '%s\n' "$preseed_read_result"
)
# END EMBEDDED INITRD CREDENTIALS

runtime_preseed_env_value() (
  preseed_env_read_value "$@"
)

runtime_cmdline_value() (
  set +x
  set +v
  # The first exact parameter wins, including an explicitly empty parameter.
  # Passwords are literal data, not pathname patterns or shell expressions.
  set -f
  IFS=' 	
'
  runtime_cmdline_key=$1
  for runtime_cmdline_arg in $(runtime_cmdline); do
    case "$runtime_cmdline_arg" in
      "$runtime_cmdline_key")
        printf '\n'
        return 0
        ;;
      "$runtime_cmdline_key"=*)
        printf '%s\n' "${runtime_cmdline_arg#*=}"
        return 0
        ;;
    esac
  done

  runtime_preseed_env_value "$runtime_cmdline_key"
)

runtime_class_list_has_addon() {
  runtime_addon_name=$1
  runtime_class_list=${2:-}

  case "$runtime_addon_name" in
    ''|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-]*) return 1 ;;
  esac

  for runtime_class_token in $(printf '%s\n' "$runtime_class_list" | tr ';,' ' '); do
    case "$runtime_class_token" in
      "$runtime_addon_name"|addon/"$runtime_addon_name"|addon:"$runtime_addon_name"|addon."$runtime_addon_name"|class-addon/"$runtime_addon_name"|class-addon:"$runtime_addon_name"|class-addon."$runtime_addon_name")
        return 0
        ;;
    esac
  done
  return 1
}

runtime_addon_class_selected() {
  runtime_addon_name=$1

  if [ -n "${INSTALLER_SELECTED_CLASS_REFS:-}" ]; then
    runtime_class_list_has_addon "$runtime_addon_name" "$INSTALLER_SELECTED_CLASS_REFS"
    return $?
  fi

  if command -v installer_selected_class_reference_is_selected >/dev/null 2>&1 &&
    installer_selected_class_reference_is_selected "addon/$runtime_addon_name"
  then
    return 0
  fi

  runtime_classes_raw=$(runtime_cmdline_value classes 2>/dev/null || true)
  if [ -z "$runtime_classes_raw" ]; then
    runtime_classes_raw=$(runtime_cmdline_value auto-install/classes 2>/dev/null || true)
  fi
  runtime_class_list_has_addon "$runtime_addon_name" "$runtime_classes_raw"
}

runtime_dualboot_class_selected() {
  runtime_addon_class_selected dualboot
}

runtime_qemu_class_selected() {
  runtime_addon_class_selected qemu
}

runtime_crypto_class_selected() {
  runtime_addon_class_selected crypto
}

runtime_root_home_crypto_enabled() {
  runtime_crypto_class_selected
}

runtime_validate_root_home_crypto_layout() {
  runtime_root_home_crypto_enabled || return 0

  [ -n "${DEV_PART_ROOT:-}" ] || runtime_fatal "addon/crypto requires a dedicated root partition"
  [ -n "${DEV_PART_HOME:-}" ] || runtime_fatal "addon/crypto requires a dedicated /home partition"
  case "${DEV_PART_HOME_MB:-}" in
    ''|*[!0-9]*|0)
      runtime_fatal "addon/crypto requires a non-zero dedicated /home partition"
      ;;
  esac
}

runtime_bool_is_true() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
  esac
  return 1
}

runtime_bool_is_false() {
  case "${1:-}" in
    0|false|FALSE|no|NO|off|OFF) return 0 ;;
  esac
  return 1
}

runtime_apply_ssh_from_classes() {
  if ! command -v installer_selected_class_refs >/dev/null 2>&1 ||
    ! command -v installer_selected_class_reference_is_selected >/dev/null 2>&1; then
    runtime_fatal "installer class selection helpers are unavailable for SSH server provisioning"
  fi
  installer_selected_class_refs >/dev/null 2>&1 ||
    runtime_fatal "selected installer classes are unavailable for SSH server provisioning"

  if installer_selected_class_reference_is_selected addon/ssh; then
    SSH_SERVER_ENABLED=true
    runtime_apply_ssh_from_cmdline
  else
    SSH_SERVER_ENABLED=false
  fi
}

runtime_apply_ssh_from_cmdline() {
  [ "${RUNTIME_SSH_CMDLINE_READY:-0}" = 1 ] && return 0

  ssh_port_default=${SSH_PORT_DEFAULT:-}
  ssh_port_raw=$(runtime_cmdline_value ssh_port 2>/dev/null || true)
  if [ -z "$ssh_port_raw" ]; then
    ssh_port_raw=$ssh_port_default
  fi
  runtime_require_positive_integer ssh_port "$ssh_port_raw"
  [ "$ssh_port_raw" -le 65535 ] || runtime_fatal "ssh_port must be 65535 or lower"
  SSH_PORT=$ssh_port_raw
  RUNTIME_SSH_CMDLINE_READY=1
}

runtime_require_integer() {
  runtime_require_integer_label=$1
  runtime_require_integer_value=$2
  case "$runtime_require_integer_value" in
    ''|*[!0-9]*)
      runtime_fatal "${runtime_require_integer_label} must be an integer, got '${runtime_require_integer_value:-unset}'"
      ;;
  esac
}

runtime_require_positive_integer() {
  runtime_require_positive_integer_label=$1
  runtime_require_positive_integer_value=$2
  runtime_require_integer "$runtime_require_positive_integer_label" "$runtime_require_positive_integer_value"
  [ "$runtime_require_positive_integer_value" -gt 0 ] || runtime_fatal "${runtime_require_positive_integer_label} must be greater than zero"
}

runtime_require_nonnegative_integer() {
  runtime_require_nonnegative_integer_label=$1
  runtime_require_nonnegative_integer_value=$2
  runtime_require_integer "$runtime_require_nonnegative_integer_label" "$runtime_require_nonnegative_integer_value"
  [ "$runtime_require_nonnegative_integer_value" -ge 0 ] || runtime_fatal "${runtime_require_nonnegative_integer_label} must be zero or greater"
}

runtime_min() {
  runtime_min_left=$1
  runtime_min_right=$2
  runtime_require_integer runtime_min_left "$runtime_min_left"
  runtime_require_integer runtime_min_right "$runtime_min_right"
  if [ "$runtime_min_left" -le "$runtime_min_right" ]; then
    printf '%s\n' "$runtime_min_left"
  else
    printf '%s\n' "$runtime_min_right"
  fi
}

runtime_max() {
  runtime_max_left=$1
  runtime_max_right=$2
  runtime_require_integer runtime_max_left "$runtime_max_left"
  runtime_require_integer runtime_max_right "$runtime_max_right"
  if [ "$runtime_max_left" -ge "$runtime_max_right" ]; then
    printf '%s\n' "$runtime_max_left"
  else
    printf '%s\n' "$runtime_max_right"
  fi
}

runtime_clamp() {
  runtime_clamp_value=$1
  runtime_clamp_min=$2
  runtime_clamp_max=$3
  runtime_require_integer runtime_clamp_value "$runtime_clamp_value"
  runtime_require_integer runtime_clamp_min "$runtime_clamp_min"
  runtime_require_integer runtime_clamp_max "$runtime_clamp_max"
  if [ "$runtime_clamp_min" -gt "$runtime_clamp_max" ]; then
    runtime_fatal "runtime_clamp requires min <= max, got ${runtime_clamp_min} > ${runtime_clamp_max}"
  fi
  if [ "$runtime_clamp_value" -lt "$runtime_clamp_min" ]; then
    printf '%s\n' "$runtime_clamp_min"
  elif [ "$runtime_clamp_value" -gt "$runtime_clamp_max" ]; then
    printf '%s\n' "$runtime_clamp_max"
  else
    printf '%s\n' "$runtime_clamp_value"
  fi
}

runtime_total_ram_mib() {
  if [ -n "${RUNTIME_MEMTOTAL_MIB_OVERRIDE:-}" ]; then
    runtime_require_positive_integer RUNTIME_MEMTOTAL_MIB_OVERRIDE "$RUNTIME_MEMTOTAL_MIB_OVERRIDE"
    printf '%s\n' "$RUNTIME_MEMTOTAL_MIB_OVERRIDE"
    return 0
  fi

  if [ -r /proc/meminfo ]; then
    mem_kib=
    while IFS=' ' read -r key value _rest || [ -n "${key:-}" ]; do
      [ "$key" = "MemTotal:" ] || continue
      mem_kib=$value
      break
    done </proc/meminfo
    case "$mem_kib" in
      ''|*[!0-9]*|0) ;;
      *)
        printf '%s\n' "$(((mem_kib + 1023) / 1024))"
        return 0
        ;;
    esac
  fi

  runtime_fatal "unable to determine total RAM in MiB"
}

runtime_debconf_command() (
  runtime_debconf_request=$1
  runtime_debconf_question=$2
  if installer_debconf_request "$runtime_debconf_request" >/dev/null; then
    return 0
  else
    runtime_debconf_status=$?
    printf '[runtime] error: debconf command failed for %s (status %s)\n' "$runtime_debconf_question" "$runtime_debconf_status" >&2
    return "$runtime_debconf_status"
  fi
)

runtime_seed_debconf_value() {
  runtime_debconf_command "SET $1 $2" "$1" || return $?
  runtime_debconf_command "FSET $1 seen true" "$1"
}

runtime_apply_answers_file() (
  path=$1
  [ -r "$path" ] || runtime_fatal "answer fragment is not readable: ${path}"
  if LC_ALL=C grep -q '\\$' "$path" ||
     LC_ALL=C grep -Eq '^[[:space:]]*[^#[:space:]][^[:space:]]*[[:space:]]+[^[:space:]]+[[:space:]]+password([[:space:]]|$)' "$path"; then
    # The upstream d-i selector logs each record. Register password questions
    # without their values, then send those values on the live protocol.
    # Generated runtime fragments have one record per physical line. Preserve
    # terminal backslashes as data. The installer utility needs a filename;
    # piping records into it both omits that argument and destroys its replies.
    runtime_answer_work=$(mktemp -d /tmp/installer-runtime-answers.XXXXXX) || return 125
    trap '
      runtime_answer_status=$?
      trap - 0
      if rm -rf "$runtime_answer_work"; then :; else
        runtime_cleanup_status=$?
        [ "$runtime_answer_status" -ne 0 ] || runtime_answer_status=$runtime_cleanup_status
      fi
      exit "$runtime_answer_status"
    ' 0
    (umask 077
      while IFS=' 	' read -r owner question answer_type value || [ -n "${owner:-}" ]; do
        case "$owner" in ''|'#'*) continue ;; esac
        case "$value" in *\\) value= ;; esac
        [ "$answer_type" != password ] || value=
        printf '%s %s %s %s\n' "$owner" "$question" "$answer_type" "$value"
      done <"$path" >"$runtime_answer_work/answers"
    ) || return "$?"
    installer_debconf_apply_file "$runtime_answer_work/answers" || return "$?"
    runtime_seed_answers_file "$path" || return "$?"
  else
    installer_debconf_apply_file "$path" || return "$?"
  fi
)

runtime_seed_answers_file() (
  path=$1
  [ -r "$path" ] || runtime_fatal "answer fragment is not readable: ${path}"

  # Generated fragments contain one record per physical line. read -r preserves
  # password punctuation; an empty fourth field must clear a stale hash. A seen
  # record changes a flag, never the value (especially never a password).
  while IFS=' 	' read -r owner question answer_type value <&7 || [ -n "${owner:-}" ]; do
    case "$owner" in
      ''|'#'*) continue ;;
    esac
    [ -n "$question" ] || runtime_fatal "invalid generated answer record"
    case "$answer_type" in
      seen)
        case "$value" in
          true|false) ;;
          *) runtime_fatal "invalid seen flag for ${question}" ;;
        esac
        runtime_debconf_command "FSET $question seen $value" "$question" || return $?
        ;;
      boolean|string|password|select|multiselect|note|text|title)
        runtime_seed_debconf_value "$question" "$value" || return $?
        ;;
      *) runtime_fatal "unsupported generated answer type for ${question}" ;;
    esac
  done 7<"$path"
)

runtime_prepare_parent_dir() {
  path=$1
  mode=$2
  parent_dir=$(dirname "$path")
  [ -d "$parent_dir" ] || install -d -m "$mode" "$parent_dir"
}

runtime_shell_quote() {
  printf "'%s'" "$(printf '%s' "${1-}" | sed "s/'/'\\\\''/g")"
}

runtime_validate_printable_single_line() {
  label=$1
  value=$2

  [ -n "$value" ] || runtime_fatal "${label} must not be empty"
  case "$value" in
    *[![:print:]]*|*[[:space:]]*)
      runtime_fatal "${label} must be a single printable token without whitespace"
      ;;
  esac
}

runtime_validate_system_prefix() {
  value=$1

  [ -n "$value" ] || runtime_fatal "SYSTEM_PREFIX must not be empty"
  case "$value" in
    *[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789]*)
      runtime_fatal "SYSTEM_PREFIX must contain only ASCII letters and digits"
      ;;
  esac
  if [ "${#value}" -gt 59 ]; then
    runtime_fatal "SYSTEM_PREFIX must be 59 characters or shorter so SYSTEM_HOSTNAME stays within 63 characters"
  fi
}

runtime_validate_system_domain() {
  value=$1

  [ -n "$value" ] || runtime_fatal "SYSTEM_DOMAIN must not be empty"
  case "$value" in
    *[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.-]*|.*|*.|*..*)
      runtime_fatal "SYSTEM_DOMAIN must contain only hostname-safe labels"
      ;;
  esac
}

runtime_validate_system_hostname() {
  prefix=$1
  value=$2

  case "$value" in
    ''|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-]*|-*|*-)
      runtime_fatal "SYSTEM_HOSTNAME must contain only hostname-safe characters"
      ;;
    "${prefix}"-[0-9][0-9][0-9])
      ;;
    *)
      runtime_fatal "SYSTEM_HOSTNAME must match SYSTEM_PREFIX-###"
      ;;
  esac
}

runtime_apply_identity_from_cmdline() {
  cmdline_domain=$(runtime_cmdline_value netcfg/get_domain 2>/dev/null || true)
  if [ -z "$cmdline_domain" ]; then
    cmdline_domain=$(runtime_cmdline_value domain 2>/dev/null || true)
  fi
  [ -n "$cmdline_domain" ] || return 0
  SYSTEM_DOMAIN=$cmdline_domain
}

runtime_random_hostname_suffix() {
  [ -r /dev/urandom ] || runtime_fatal "unable to generate hostname suffix: /dev/urandom is unavailable"
  # Filter the kernel RNG stream down to ASCII digits so the suffix is always ###.
  raw=$(LC_ALL=C tr -dc '0-9' </dev/urandom | dd bs=3 count=1 2>/dev/null || true)
  case "$raw" in
    [0-9][0-9][0-9])
      ;;
    *)
      runtime_fatal "unable to generate hostname suffix from /dev/urandom"
      ;;
  esac

  printf '%s\n' "$raw"
}

runtime_ensure_system_identity() {
  : "${SYSTEM_PREFIX:?SYSTEM_PREFIX must be set}"
  : "${SYSTEM_DOMAIN:?SYSTEM_DOMAIN must be set}"

  runtime_apply_identity_from_cmdline
  runtime_validate_system_prefix "$SYSTEM_PREFIX"
  runtime_validate_system_domain "$SYSTEM_DOMAIN"

  if [ -n "${SYSTEM_HOSTNAME:-}" ]; then
    runtime_validate_system_hostname "$SYSTEM_PREFIX" "$SYSTEM_HOSTNAME"
    return 0
  fi

  SYSTEM_HOSTNAME="${SYSTEM_PREFIX}-$(runtime_random_hostname_suffix)"
  runtime_validate_system_hostname "$SYSTEM_PREFIX" "$SYSTEM_HOSTNAME"
}

runtime_generate_crypto_bootstrap_key() {
  crypto_bootstrap_key=

  [ -r /proc/sys/kernel/random/uuid ] ||
    runtime_fatal "kernel UUID entropy source is unavailable for the crypto bootstrap key"
  IFS= read -r crypto_bootstrap_key </proc/sys/kernel/random/uuid ||
    [ -n "$crypto_bootstrap_key" ] ||
    runtime_fatal "unable to generate the crypto bootstrap key"

  case "$crypto_bootstrap_key" in
    ????????-????-????-????-????????????) ;;
    *) runtime_fatal "generated crypto bootstrap key has an invalid UUID shape" ;;
  esac
  case "$crypto_bootstrap_key" in
    *[!0123456789abcdefABCDEF-]*)
      runtime_fatal "generated crypto bootstrap key has unsupported characters"
      ;;
  esac

  printf '%s\n' "$crypto_bootstrap_key"
}

runtime_read_or_create_crypto_bootstrap_key() {
  key_file=$1
  key_dir=$(dirname "$key_file")
  key_tmp="${key_file}.tmp.$$"
  crypto_bootstrap_key=

  if [ -e "$key_file" ]; then
    [ -f "$key_file" ] && [ ! -L "$key_file" ] ||
      runtime_fatal "crypto bootstrap key must be a regular non-symlink file: ${key_file}"
    IFS= read -r crypto_bootstrap_key <"$key_file" ||
      [ -n "$crypto_bootstrap_key" ] ||
      runtime_fatal "unable to read crypto bootstrap key: ${key_file}"
  else
    crypto_bootstrap_key=$(runtime_generate_crypto_bootstrap_key)
    (
      umask 077
      printf '%s' "$crypto_bootstrap_key" >"$key_tmp"
    ) || runtime_fatal "unable to write crypto bootstrap key"
    chmod 0400 "$key_tmp" || runtime_fatal "unable to secure crypto bootstrap key"
    mv -f "$key_tmp" "$key_file" || runtime_fatal "unable to install crypto bootstrap key"
  fi

  case "$crypto_bootstrap_key" in
    ????????-????-????-????-????????????) ;;
    *) runtime_fatal "crypto bootstrap key has an invalid UUID shape" ;;
  esac
  case "$crypto_bootstrap_key" in
    *[!0123456789abcdefABCDEF-]*)
      runtime_fatal "crypto bootstrap key has unsupported characters"
      ;;
  esac
  chmod 0400 "$key_file" || runtime_fatal "unable to secure crypto bootstrap key"
  [ -d "$key_dir" ] || runtime_fatal "crypto bootstrap key directory is missing: ${key_dir}"
  printf '%s\n' "$crypto_bootstrap_key"
}

runtime_write_crypto_answers() {
  dest=$1

  runtime_validate_account_settings
  runtime_prepare_parent_dir "$dest" 0700
  crypto_key_file="$(dirname "$dest")/crypto-bootstrap.key"
  crypto_install_passphrase=$(runtime_read_or_create_crypto_bootstrap_key "$crypto_key_file")
  {
    printf '##########  Runtime Crypto Configuration  ##########\n'
    printf '# Generated inside the installer. addon/crypto uses a random bootstrap passphrase.\n'
    printf 'd-i partman-crypto/passphrase password %s\n' "$crypto_install_passphrase"
    printf 'd-i partman-crypto/passphrase seen true\n'
    printf 'd-i partman-crypto/passphrase-again password %s\n' "$crypto_install_passphrase"
    printf 'd-i partman-crypto/passphrase-again seen true\n'
    printf 'd-i partman-crypto/weak_passphrase boolean true\n'
    printf 'd-i partman-crypto/weak_passphrase seen true\n'
    printf 'd-i partman-crypto/confirm boolean true\n'
    printf 'd-i partman-crypto/confirm seen true\n'
    printf 'd-i partman-crypto/confirm_nochanges boolean true\n'
    printf 'd-i partman-crypto/confirm_nochanges seen true\n'
    printf 'd-i partman-crypto/confirm_nooverwrite boolean true\n'
    printf 'd-i partman-crypto/confirm_nooverwrite seen true\n'
  } >"$dest"
  chmod 0600 "$dest"
}

runtime_seed_generated_answers() {
  writer=$1
  shift

  tmp_dir=$(mktemp -d) || runtime_fatal "unable to create temporary answer directory"
  tmp_file="${tmp_dir}/generated.answers"
  status=0

  "$writer" "$tmp_file" "$@" || {
    status=$?
    rm -rf "$tmp_dir"
    return "$status"
  }
  runtime_apply_answers_file "$tmp_file" || {
    status=$?
    rm -rf "$tmp_dir"
    return "$status"
  }

  rm -rf "$tmp_dir"
  return 0
}

runtime_secure_boot_state_uses_luks() {
  [ "$(runtime_secure_boot_state_mode)" = "luks" ]
}

runtime_derive_part_prefix() {
  if [ -n "${DEV_PART_PREFIX:-}" ]; then
    return 0
  fi

  DEV_PART_PREFIX=${DEV_INSTALL_DISK:-}
  case "${DEV_INSTALL_DISK:-}" in
    *[0-9]) DEV_PART_PREFIX="${DEV_INSTALL_DISK}p" ;;
  esac
}

runtime_partition_path() {
  slot=$1
  printf '%s%s\n' "$DEV_PART_PREFIX" "$slot"
}

runtime_device_size_bytes() {
  dev=$1
  if [ ! -b "$dev" ]; then
    echo "fatal: partition device is missing: ${dev}" >&2
    return 1
  fi

  if command -v blockdev >/dev/null 2>&1; then
    bytes=$(blockdev --getsize64 "$dev" 2>/dev/null || true)
    case "$bytes" in
      ''|*[!0-9]*) ;;
      *)
        printf '%s\n' "$bytes"
        return 0
        ;;
    esac
  fi

  sys_name=${dev##*/}
  sectors_file="/sys/class/block/${sys_name}/size"
  if [ -r "$sectors_file" ]; then
    sectors=$(cat "$sectors_file")
    case "$sectors" in
      ''|*[!0-9]*) ;;
      *)
        printf '%s\n' "$((sectors * 512))"
        return 0
        ;;
    esac
  fi

  echo "fatal: unable to determine partition size for ${dev}" >&2
  return 1
}

runtime_device_size_mb() {
  dev=$1
  bytes=$(runtime_device_size_bytes "$dev") || return 1
  size_mb=$(((bytes + 1048575) / 1048576))
  [ "$size_mb" -gt 0 ] || runtime_fatal "partition size for ${dev} resolved to zero MB"
  printf '%s\n' "$size_mb"
}

runtime_install_disk_size_mb() {
  if [ -n "${RUNTIME_INSTALL_DISK_MB_OVERRIDE:-}" ]; then
    runtime_require_positive_integer RUNTIME_INSTALL_DISK_MB_OVERRIDE "$RUNTIME_INSTALL_DISK_MB_OVERRIDE"
    printf '%s\n' "$RUNTIME_INSTALL_DISK_MB_OVERRIDE"
    return 0
  fi

  runtime_device_size_mb "$DEV_INSTALL_DISK"
}

runtime_fill_partition_to_target() {
  current_mb=$1
  target_mb=$2
  budget_mb=$3

  runtime_require_positive_integer runtime_fill_current_mb "$current_mb"
  runtime_require_integer runtime_fill_target_mb "$target_mb"
  runtime_require_integer runtime_fill_budget_mb "$budget_mb"

  if [ "$budget_mb" -le 0 ] || [ "$current_mb" -ge "$target_mb" ]; then
    printf '%s %s\n' "$current_mb" "$budget_mb"
    return 0
  fi

  needed_mb=$((target_mb - current_mb))
  if [ "$needed_mb" -le "$budget_mb" ]; then
    printf '%s %s\n' "$target_mb" "$((budget_mb - needed_mb))"
  else
    printf '%s %s\n' "$((current_mb + budget_mb))" "0"
  fi
}

runtime_apply_fill_result() {
  current_var=$1
  budget_var=$2
  fill_result=$3

  case "$fill_result" in
    *" "*)
      new_current=${fill_result%% *}
      new_budget=${fill_result#* }
      ;;
    *)
      runtime_fatal "runtime fill result must contain '<current> <budget>', got '${fill_result}'"
      ;;
  esac

  runtime_require_integer runtime_apply_fill_current "$new_current"
  runtime_require_integer runtime_apply_fill_budget "$new_budget"
  eval "$current_var=\$new_current"
  eval "$budget_var=\$new_budget"
}

runtime_shrink_partition_to_floor() {
  current_mb=$1
  floor_mb=$2
  overflow_mb=$3

  runtime_require_nonnegative_integer runtime_shrink_current_mb "$current_mb"
  runtime_require_nonnegative_integer runtime_shrink_floor_mb "$floor_mb"
  runtime_require_integer runtime_shrink_overflow_mb "$overflow_mb"
  [ "$floor_mb" -le "$current_mb" ] || runtime_fatal "runtime shrink floor must be <= current size"

  if [ "$overflow_mb" -le 0 ] || [ "$current_mb" -le "$floor_mb" ]; then
    printf '%s %s\n' "$current_mb" "$overflow_mb"
    return 0
  fi

  shrinkable_mb=$((current_mb - floor_mb))
  if [ "$shrinkable_mb" -ge "$overflow_mb" ]; then
    printf '%s %s\n' "$((current_mb - overflow_mb))" "0"
  else
    printf '%s %s\n' "$floor_mb" "$((overflow_mb - shrinkable_mb))"
  fi
}

runtime_compute_raw_zram_partition_mb() {
  runtime_zram_budget_mb=$1
  runtime_zram_relevant_span_mb=$2

  runtime_require_positive_integer runtime_zram_budget_mb "$runtime_zram_budget_mb"
  runtime_require_positive_integer runtime_zram_relevant_span_mb "$runtime_zram_relevant_span_mb"
  runtime_require_positive_integer SIZE_PART_RAW_ZRAM_MB "${SIZE_PART_RAW_ZRAM_MB:-}"
  runtime_require_positive_integer SIZE_PART_RAW_ZRAM_DISK_DIVISOR "${SIZE_PART_RAW_ZRAM_DISK_DIVISOR:-}"
  runtime_require_positive_integer SIZE_PART_RAW_ZRAM_BUDGET_DIVISOR "${SIZE_PART_RAW_ZRAM_BUDGET_DIVISOR:-}"
  runtime_require_positive_integer SIZE_PART_RAW_ZRAM_MAX_MB "${SIZE_PART_RAW_ZRAM_MAX_MB:-}"
  runtime_require_positive_integer SIZE_PART_RAW_ZRAM_MIN_MB "${SIZE_PART_RAW_ZRAM_MIN_MB:-2048}"

  runtime_zram_floor_mb=$(runtime_min "$SIZE_PART_RAW_ZRAM_MB" "${SIZE_PART_RAW_ZRAM_MIN_MB:-2048}")
  runtime_zram_target_mb=$((runtime_zram_relevant_span_mb / SIZE_PART_RAW_ZRAM_DISK_DIVISOR))
  runtime_zram_target_mb=$(runtime_clamp "$runtime_zram_target_mb" "$runtime_zram_floor_mb" "$SIZE_PART_RAW_ZRAM_MAX_MB")
  runtime_zram_budget_cap_mb=$((runtime_zram_budget_mb / SIZE_PART_RAW_ZRAM_BUDGET_DIVISOR))
  if [ "$runtime_zram_budget_cap_mb" -lt "$runtime_zram_floor_mb" ]; then
    runtime_zram_budget_cap_mb=$runtime_zram_floor_mb
  fi

  runtime_min "$runtime_zram_target_mb" "$runtime_zram_budget_cap_mb"
}

runtime_compute_swap_partition_mib() {
  runtime_swap_budget_mb=$1
  runtime_swap_ram_mib=$2

  runtime_require_positive_integer runtime_swap_budget_mb "$runtime_swap_budget_mb"
  runtime_require_positive_integer runtime_swap_ram_mib "$runtime_swap_ram_mib"
  runtime_require_positive_integer SIZE_PART_RAW_SWAP_MB "${SIZE_PART_RAW_SWAP_MB:-}"
  runtime_require_positive_integer SIZE_PART_SWAP_MIN_MIB "${SIZE_PART_SWAP_MIN_MIB:-}"
  runtime_require_positive_integer SIZE_PART_SWAP_MAX_MIB "${SIZE_PART_SWAP_MAX_MIB:-}"
  runtime_require_positive_integer SIZE_PART_SWAP_RAM_DIVISOR "${SIZE_PART_SWAP_RAM_DIVISOR:-}"
  runtime_require_positive_integer SIZE_PART_SWAP_LAYOUT_DIVISOR "${SIZE_PART_SWAP_LAYOUT_DIVISOR:-}"

  runtime_swap_target_mib=$((runtime_swap_ram_mib / SIZE_PART_SWAP_RAM_DIVISOR))
  runtime_swap_target_mib=$(runtime_clamp "$runtime_swap_target_mib" "$SIZE_PART_SWAP_MIN_MIB" "$SIZE_PART_SWAP_MAX_MIB")
  runtime_swap_budget_cap_mib=$((runtime_swap_budget_mb / SIZE_PART_SWAP_LAYOUT_DIVISOR))
  if [ "$runtime_swap_budget_cap_mib" -lt "$SIZE_PART_SWAP_MIN_MIB" ]; then
    runtime_swap_budget_cap_mib=$SIZE_PART_SWAP_MIN_MIB
  fi

  runtime_min "$runtime_swap_target_mib" "$runtime_swap_budget_cap_mib"
}
