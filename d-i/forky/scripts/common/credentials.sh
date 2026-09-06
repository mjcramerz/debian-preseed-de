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
