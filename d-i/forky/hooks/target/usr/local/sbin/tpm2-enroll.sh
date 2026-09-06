#!/bin/sh
set -eu

PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH
umask 077

CONFIG_FILE=${TPM2_ENROLL_CONFIG_FILE:-/usr/local/lib/crypto/config.env}
STATE_DIR=${TPM2_ENROLL_STATE_DIR:-/usr/local/lib/crypto}
PENDING_FILE=${TPM2_ENROLL_PENDING_FILE:-${STATE_DIR}/tpm2-enroll.pending}
COMPLETE_FILE=${TPM2_ENROLL_COMPLETE_FILE:-${STATE_DIR}/tpm2-enroll.complete}
LOCK_FILE=${TPM2_ENROLL_LOCK_FILE:-/run/lock/tpm2-enroll.lock}
TTY_STATE=
SECRET_DIR=
SECRET_VALUE=

fatal() {
  printf 'tpm2-enroll: fatal: %s\n' "$*" >&2
  exit 1
}

info() {
  printf 'tpm2-enroll: %s\n' "$*" >&2
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fatal "required command is unavailable: $1"
}

validate_uuid() {
  printf '%s\n' "$2" |
    grep -Eq '^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$' ||
    fatal "$1 is not a valid LUKS UUID"
}

device_for_uuid() {
  device_path="/dev/disk/by-uuid/$1"
  [ -b "$device_path" ] || fatal "LUKS device is unavailable: $device_path"
  readlink -f "$device_path"
}

require_luks2() {
  device=$1
  cryptsetup isLuks "$device" >/dev/null 2>&1 || fatal "$device is not a LUKS container"
  version=$(cryptsetup luksDump "$device" 2>/dev/null |
    awk '$1 == "Version:" { print $2; exit }')
  [ "$version" = 2 ] || fatal "$device is not LUKS2"
}

read_secret() {
  prompt=$1
  printf '%s' "$prompt" >/dev/tty
  TTY_STATE=$(stty -g </dev/tty) || fatal "unable to read terminal state"
  stty -echo </dev/tty
  IFS= read -r secret_value </dev/tty || {
    stty "$TTY_STATE" </dev/tty
    TTY_STATE=
    printf '\n' >/dev/tty
    fatal "secret input was interrupted"
  }
  stty "$TTY_STATE" </dev/tty
  TTY_STATE=
  printf '\n' >/dev/tty
  SECRET_VALUE=$secret_value
}

passphrase_works() {
  device=$1
  key_file=$2
  cryptsetup open --test-passphrase --type luks2 --key-file "$key_file" "$device" >/dev/null 2>&1
}

matching_passphrase_slots() {
  device=$1
  key_file=$2

  slot=0
  while [ "$slot" -le 31 ]; do
    if cryptsetup open \
      --test-passphrase \
      --type luks2 \
      --key-slot "$slot" \
      --key-file "$key_file" \
      "$device" >/dev/null 2>&1
    then
      printf '%s\n' "$slot"
    fi
    slot=$((slot + 1))
  done
}

keyslot_pbkdf() {
  device=$1
  wanted_slot=$2

  cryptsetup luksDump "$device" 2>/dev/null |
    awk -v wanted_slot="$wanted_slot" '
      $1 == "Keyslots:" {
        in_keyslots = 1
        next
      }
      in_keyslots && $1 == wanted_slot ":" {
        in_wanted_slot = 1
        next
      }
      in_wanted_slot && $1 == "PBKDF:" {
        print $2
        exit
      }
      in_wanted_slot && $1 ~ /^[0-9]+:$/ {
        exit
      }
    '
}

verify_fallback_pbkdf() {
  device=$1
  fallback_key=$2
  matching_slots=$(matching_passphrase_slots "$device" "$fallback_key")
  [ -n "$matching_slots" ] || fatal "unable to identify the recovery keyslot on $device"

  for slot in $matching_slots; do
    pbkdf=$(keyslot_pbkdf "$device" "$slot")
    [ "$pbkdf" = argon2id ] ||
      fatal "recovery keyslot ${slot} on $device does not use Argon2id"
  done
}

add_fallback_passphrase() {
  device=$1
  current_key=$2
  fallback_key=$3

  if passphrase_works "$device" "$fallback_key"; then
    info "recovery passphrase is already enrolled on $device"
    verify_fallback_pbkdf "$device" "$fallback_key"
    return 0
  fi

  if [ -z "$current_key" ] || ! passphrase_works "$device" "$current_key"; then
    fatal "recovery passphrase is not enrolled and the installer passphrase no longer unlocks $device"
  fi

  cryptsetup luksAddKey \
    --batch-mode \
    --type luks2 \
    --pbkdf argon2id \
    --iter-time 5000 \
    --key-file "$current_key" \
    "$device" \
    "$fallback_key"
  passphrase_works "$device" "$fallback_key" || fatal "recovery passphrase verification failed for $device"
  verify_fallback_pbkdf "$device" "$fallback_key"
}

enroll_tpm2_pin() {
  device=$1
  credential_dir=$2
  fallback_key=$3
  pcrs=$4

  CREDENTIALS_DIRECTORY="$credential_dir" \
    systemd-cryptenroll \
      --wipe-slot=tpm2 \
      --unlock-key-file="$fallback_key" \
      --tpm2-device=auto \
      --tpm2-with-pin=yes \
      --tpm2-pcrs="$pcrs" \
      "$device"

  systemd-cryptenroll "$device" 2>/dev/null | grep -qi tpm2 ||
    fatal "TPM2 token verification failed for $device"
}

verify_tpm2_pin_unlock() {
  device=$1
  credential_dir=$2
  pcrs=$3

  CREDENTIALS_DIRECTORY="$credential_dir" \
    systemd-cryptenroll \
      --wipe-slot=tpm2 \
      --unlock-tpm2-device=auto \
      --tpm2-device=auto \
      --tpm2-with-pin=yes \
      --tpm2-pcrs="$pcrs" \
      "$device"

  systemd-cryptenroll "$device" 2>/dev/null | grep -qi tpm2 ||
    fatal "TPM2 token verification rotation failed for $device"
}

remove_install_passphrase_slots() {
  device=$1
  install_key=$2
  fallback_key=$3

  [ -n "$install_key" ] || return 0
  if ! passphrase_works "$device" "$install_key"; then
    info "temporary installer passphrase is already absent from $device"
    return 0
  fi

  matching_slots=$(matching_passphrase_slots "$device" "$install_key")

  for slot in $matching_slots; do
    cryptsetup luksKillSlot \
      --batch-mode \
      --key-file "$fallback_key" \
      "$device" \
      "$slot"
  done

  if passphrase_works "$device" "$install_key"; then
    fatal "temporary installer passphrase is still active on $device"
  fi
}

cleanup() {
  if [ -n "$TTY_STATE" ]; then
    stty "$TTY_STATE" </dev/tty 2>/dev/null || true
    TTY_STATE=
  fi
  if [ -n "$SECRET_DIR" ]; then
    rm -rf "$SECRET_DIR"
  fi
  unset SECRET_VALUE fallback_passphrase fallback_confirm tpm_pin tpm_pin_confirm 2>/dev/null || true
}

[ "$(id -u)" -eq 0 ] || fatal "run this helper through sudo"
[ -r "$CONFIG_FILE" ] || fatal "missing crypto configuration: $CONFIG_FILE"
[ -r /dev/tty ] || fatal "an interactive terminal is required"
[ -e "$PENDING_FILE" ] || {
  [ -e "$COMPLETE_FILE" ] && info "TPM2 enrollment is already complete"
  exit 0
}

require_command awk
require_command cmp
require_command cryptsetup
require_command flock
require_command grep
require_command mktemp
require_command mokutil
require_command readlink
require_command stty
require_command systemd-cryptenroll

install -d -m 0755 "$(dirname "$LOCK_FILE")"
exec 9>"$LOCK_FILE"
flock -n 9 || fatal "another TPM2 enrollment process is already running"

# shellcheck disable=SC1090
. "$CONFIG_FILE"

: "${PRIMARY_USER:?PRIMARY_USER must be configured}"
: "${ROOT_LUKS_UUID:?ROOT_LUKS_UUID must be configured}"
: "${HOME_LUKS_UUID:?HOME_LUKS_UUID must be configured}"
: "${HOME_KEY_FILE:?HOME_KEY_FILE must be configured}"
: "${INSTALL_PASSPHRASE_FILE:?INSTALL_PASSPHRASE_FILE must be configured}"
: "${TPM2_FINAL_PCRS:?TPM2_FINAL_PCRS must be configured}"
validate_uuid ROOT_LUKS_UUID "$ROOT_LUKS_UUID"
validate_uuid HOME_LUKS_UUID "$HOME_LUKS_UUID"
case "$INSTALL_PASSPHRASE_FILE:$HOME_KEY_FILE" in
  /*:/*) ;;
  *) fatal "INSTALL_PASSPHRASE_FILE and HOME_KEY_FILE must be absolute paths" ;;
esac
case "$INSTALL_PASSPHRASE_FILE:$HOME_KEY_FILE" in
  *..*|*//*)
    fatal "INSTALL_PASSPHRASE_FILE and HOME_KEY_FILE contain unsupported path syntax"
    ;;
esac
[ "$TPM2_FINAL_PCRS" = 7+14 ] || fatal "TPM2_FINAL_PCRS must be 7+14"
if [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "$PRIMARY_USER" ]; then
  fatal "TPM2 enrollment must be run by ${PRIMARY_USER}, not ${SUDO_USER}"
fi

root_device=$(device_for_uuid "$ROOT_LUKS_UUID")
home_device=$(device_for_uuid "$HOME_LUKS_UUID")
require_luks2 "$root_device"
require_luks2 "$home_device"
[ -r "$HOME_KEY_FILE" ] || fatal "root-contained home key is missing: $HOME_KEY_FILE"
passphrase_works "$home_device" "$HOME_KEY_FILE" || fatal "root-contained home key does not unlock $home_device"
install_key=
if [ -e "$INSTALL_PASSPHRASE_FILE" ]; then
  [ -f "$INSTALL_PASSPHRASE_FILE" ] && [ ! -L "$INSTALL_PASSPHRASE_FILE" ] ||
    fatal "installer passphrase file is unsafe: $INSTALL_PASSPHRASE_FILE"
  install_key=$INSTALL_PASSPHRASE_FILE
else
  info "installer passphrase file is absent; interrupted enrollment recovery requires the existing recovery passphrase"
fi

tpm2_device_list=$(systemd-cryptenroll --tpm2-device=list 2>/dev/null || true)
printf '%s\n' "$tpm2_device_list" | grep -Eq '/dev/tpm(rm)?[0-9]+' ||
  fatal "no usable TPM2 device was found"
mokutil --sb-state 2>/dev/null | grep -q '^SecureBoot enabled' ||
  fatal "UEFI Secure Boot must be enabled before final TPM2 enrollment"

trap cleanup EXIT HUP INT TERM

read_secret 'New recovery passphrase (minimum 20 characters; use 6+ random words or a password manager): '
fallback_passphrase=$SECRET_VALUE
SECRET_VALUE=
[ "${#fallback_passphrase}" -ge 20 ] || fatal "recovery passphrase must be at least 20 characters"
[ "$fallback_passphrase" != "$PRIMARY_USER" ] || fatal "recovery passphrase must differ from the primary account name"
if printf '%s' "$fallback_passphrase" | LC_ALL=C.UTF-8 grep -q '[[:cntrl:]]'; then
  fatal "recovery passphrase must not contain control characters"
fi
read_secret 'Confirm recovery passphrase: '
fallback_confirm=$SECRET_VALUE
SECRET_VALUE=
[ "$fallback_passphrase" = "$fallback_confirm" ] || fatal "recovery passphrases do not match"

read_secret 'New TPM2 PIN (6-32 digits): '
tpm_pin=$SECRET_VALUE
SECRET_VALUE=
case "$tpm_pin" in
  *[!0-9]*) fatal "TPM2 PIN must contain digits only" ;;
esac
[ "${#tpm_pin}" -ge 6 ] && [ "${#tpm_pin}" -le 32 ] ||
  fatal "TPM2 PIN must contain 6-32 digits"
read_secret 'Confirm TPM2 PIN: '
tpm_pin_confirm=$SECRET_VALUE
SECRET_VALUE=
[ "$tpm_pin" = "$tpm_pin_confirm" ] || fatal "TPM2 PIN values do not match"

SECRET_DIR=$(mktemp -d /run/tpm2-enroll.XXXXXX) || fatal "unable to create credential directory"

fallback_key="${SECRET_DIR}/fallback-passphrase"
credential_dir="${SECRET_DIR}/credentials"
install -d -m 0700 "$credential_dir"
printf '%s' "$fallback_passphrase" >"$fallback_key"
printf '%s' "$tpm_pin" >"${credential_dir}/cryptenroll.tpm2-pin"
printf '%s' "$tpm_pin" >"${credential_dir}/cryptenroll.new-tpm2-pin"
chmod 0400 "$fallback_key" "${credential_dir}/cryptenroll.tpm2-pin" "${credential_dir}/cryptenroll.new-tpm2-pin"
if [ -n "$install_key" ] && cmp -s "$install_key" "$fallback_key"; then
  fatal "recovery passphrase must differ from the temporary installer passphrase"
fi

for device in "$root_device" "$home_device"; do
  add_fallback_passphrase "$device" "$install_key" "$fallback_key"
done

for device in "$root_device" "$home_device"; do
  enroll_tpm2_pin "$device" "$credential_dir" "$fallback_key" "$TPM2_FINAL_PCRS"
done

for device in "$root_device" "$home_device"; do
  verify_tpm2_pin_unlock "$device" "$credential_dir" "$TPM2_FINAL_PCRS"
done

for device in "$root_device" "$home_device"; do
  remove_install_passphrase_slots "$device" "$install_key" "$fallback_key"
  passphrase_works "$device" "$fallback_key" || fatal "recovery passphrase stopped working for $device"
done

install -d -m 0700 "$STATE_DIR"
{
  printf 'status=complete\n'
  printf 'completed_at=%s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  printf 'root_luks_uuid=%s\n' "$ROOT_LUKS_UUID"
  printf 'home_luks_uuid=%s\n' "$HOME_LUKS_UUID"
  printf 'tpm2_pcrs=%s\n' "$TPM2_FINAL_PCRS"
  printf 'recovery_pbkdf=argon2id\n'
  printf 'recovery_iter_time_ms=5000\n'
} >"$COMPLETE_FILE"
chmod 0600 "$COMPLETE_FILE"
rm -f "$INSTALL_PASSPHRASE_FILE"
rm -f "$PENDING_FILE"

if command -v systemctl >/dev/null 2>&1; then
  systemctl start --no-block secondboot.service >/dev/null 2>&1 ||
    info "warning: could not queue completed bootstrap cleanup"
fi

info "TPM2+PIN enrollment completed for encrypted root and home"
info "Store the recovery passphrase offline; it is required after TPM/PCR policy changes"
