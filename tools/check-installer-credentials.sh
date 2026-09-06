#!/bin/sh
# Check trusted installer credentials without printing any values.
# Usage: sh tools/check-installer-credentials.sh [env-file [cmdline-file]]
# Does not modify accounts, debconf, disks, or browser settings. May chmod the
# credential file to 0600, exactly as the installer does. Do not run with -x.
set +x
set +v
set -eu
umask 077
if [ "$#" -gt 2 ]; then
  printf 'usage: %s [env-file [cmdline-file]]\n' "${0##*/}" >&2
  exit 2
fi
check_repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
# shellcheck disable=SC1091
. "$check_repo/d-i/forky/scripts/common/lib.sh"
INSTALLER_PRESEED_ENV_FILE=${1:-/preseed.env}
INSTALLER_CMDLINE_FILE=${2:-/proc/cmdline}
unset INSTALLER_CMDLINE INSTALLER_CMDLINE_CACHE INSTALLER_CMDLINE_CACHE_READY
if [ ! -r "$INSTALLER_CMDLINE_FILE" ]; then
  printf '[credentials] error: command-line input file is not readable\n' >&2
  exit 2
fi
check_result=0
for check_key in root_password primary_user primary_password primary_gpg_passphrase \
  netcfg/wireless_wpa fruux_username fruux_password crowdsec_token tailscale_authkey \
  telegram_chat_id telegram_api_key cf_r2_access_key cf_r2_secret_key obs_username obs_password
do
  if installer_cmdline_parameter_present "$check_key"; then
    check_source=command-line
  else
    check_source=initrd-env
  fi
  if check_value=$(installer_cmdline_value "$check_key"); then
    if [ -n "$check_value" ]; then
      check_state=present
    else
      check_state=explicit-empty
    fi
  else
    check_status=$?
    if [ "$check_status" -eq 1 ]; then
      check_state=missing-or-empty
    else
      check_state=load-error
      check_result=2
    fi
  fi
  if [ "$check_key" = root_password ]; then
    if [ "$check_state" = present ]; then
      case "$check_value" in
        *[![:print:]]*|*[[:space:]]*) check_state=invalid-format; check_result=1 ;;
      esac
    elif [ "$check_result" -eq 0 ]; then
      check_result=1
    fi
  fi
  unset check_value
  printf '%s: %s (%s)\n' "$check_key" "$check_state" "$check_source"
done
printf 'Only presence and source are shown; optional integration requirements depend on the selected profile.\n'
exit "$check_result"
