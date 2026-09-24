#!/bin/sh
# Sourced installer module; edit this file directly.

desktop_primary_account_gpg_user_id() {
  if [ -n "${SYSTEM_HOSTNAME:-}" ]; then
    printf '%s (%s@%s)\n' "$ACCOUNT_FULLNAME" "$ACCOUNT_USERNAME" "$SYSTEM_HOSTNAME"
    return 0
  fi

  printf '%s (%s)\n' "$ACCOUNT_FULLNAME" "$ACCOUNT_USERNAME"
}

desktop_primary_account_gpg_passphrase() {
  if [ "${ACCOUNT_GPG_PASSPHRASE_IS_PLAIN:-false}" = true ] &&
    [ -n "${ACCOUNT_GPG_PASSPHRASE:-}" ]
  then
    printf '%s\n' "$ACCOUNT_GPG_PASSPHRASE"
    return 0
  fi

  installer_fatal \
    "desktop GPG bootstrap requires primary_gpg_passphrase= or primary_password= on the installer kernel command line or in /preseed.env"
}

desktop_bootstrap_primary_account_gpg_key() {
  : "${ACCOUNT_USERNAME:?ACCOUNT_USERNAME must be set}"
  : "${ACCOUNT_HOME:?ACCOUNT_HOME must be set}"
  : "${ACCOUNT_FULLNAME:?ACCOUNT_FULLNAME must be set}"

  desktop_require_absolute_account_home

  (
  set +x
  set +v
  umask 077
  gpg_user_id=$(desktop_primary_account_gpg_user_id)
  gpg_bootstrap_passphrase=$(desktop_primary_account_gpg_passphrase)
  [ -n "$gpg_bootstrap_passphrase" ] || installer_fatal "desktop GPG bootstrap requires a non-empty passphrase source"
  [ ! -L /target/tmp ] || installer_fatal "unsafe target temporary directory for GPG bootstrap"
  install -d -m 1777 /target/tmp || installer_fatal "cannot prepare target temporary directory"
  gpg_stage=$(mktemp -d /target/tmp/desktop-gpg.XXXXXX) ||
    installer_fatal "cannot allocate private GPG bootstrap staging"
  gpg_bootstrap_cleanup() {
    gpg_status=$?
    trap - 0
    rm -rf -- "$gpg_stage" || {
      [ "$gpg_status" -ne 0 ] || gpg_status=1
    }
    unset gpg_bootstrap_passphrase
    exit "$gpg_status"
  }
  trap gpg_bootstrap_cleanup 0
  trap 'exit 129' 1
  trap 'exit 130' 2
  trap 'exit 143' 15
  chmod 0700 "$gpg_stage" && chmod u-s,g-s "$gpg_stage" ||
    installer_fatal "cannot secure private GPG bootstrap staging"
  gpg_passphrase_target="${gpg_stage#/target}/passphrase"
  gpg_fingerprint_target="${gpg_stage#/target}/fingerprint"
  printf '%s\n' "$gpg_bootstrap_passphrase" >"$gpg_stage/passphrase" ||
    installer_fatal "cannot stage GPG bootstrap passphrase"

  # shellcheck disable=SC2016
  if ! attempt_in_target "bootstrap primary account GPG key for KWallet" /bin/sh -c '
set -eu
umask 077
account_user=$1
account_home=$2
gpg_user_id=$3
passphrase_file=$4
fingerprint_file=$5
gnupg_dir="${account_home}/.gnupg"
gpg_agent_conf="${gnupg_dir}/gpg-agent.conf"
gpg_agent_template=/etc/skel-desktop/.gnupg/gpg-agent.conf

fatal() {
  printf "fatal: %s\n" "$*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fatal "required command is missing: $1"
}

account_gpg() {
  runuser -u "$account_user" -- env \
    HOME="$account_home" \
    USER="$account_user" \
    LOGNAME="$account_user" \
    GNUPGHOME="$gnupg_dir" \
    PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    gpg "$@"
}

account_gpgconf() {
  runuser -u "$account_user" -- env \
    HOME="$account_home" \
    USER="$account_user" \
    LOGNAME="$account_user" \
    GNUPGHOME="$gnupg_dir" \
    PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    gpgconf "$@"
}

gpg_secret_key_fingerprints() {
  account_gpg \
    --batch \
    --no-options \
    --fixed-list-mode \
    --with-colons \
    --list-secret-keys \
    -- "$gpg_user_id" 2>/dev/null |
    awk -F: "
      \$1 == \"sec\" { want_fingerprint = 1; next }
      want_fingerprint && \$1 == \"fpr\" {
        print \$10
        want_fingerprint = 0
      }
    "
}

gpg_validate_fingerprint() {
  fingerprint=$1
  case "${#fingerprint}" in
    40|64) ;;
    *) fatal "generated GPG fingerprint has an unsupported length" ;;
  esac
  case "$fingerprint" in
    *[!0123456789ABCDEF]*) fatal "generated GPG fingerprint is malformed" ;;
  esac
}

gpg_key_can_encrypt() {
  fingerprint=$1
  account_gpg \
    --batch \
    --no-options \
    --fixed-list-mode \
    --with-colons \
    --list-keys \
    -- "$fingerprint" 2>/dev/null |
    awk -F: "
      \$1 == \"pub\" && \$12 ~ /E/ { suitable = 1 }
      END { exit suitable ? 0 : 1 }
    "
}

gpg_key_is_kwallet_suitable() {
  fingerprint=$1
  account_gpg \
    --batch \
    --no-options \
    --fixed-list-mode \
    --with-colons \
    --list-keys \
    -- "$fingerprint" 2>/dev/null |
    awk -F: "
      \$1 == \"pub\" && substr(\$9, 1, 1) == \"u\" && \$12 ~ /E/ {
        suitable = 1
      }
      END { exit suitable ? 0 : 1 }
    "
}

case "$account_home" in
  /*) ;;
  *) fatal "account home must be absolute: $account_home" ;;
esac
case "$account_home" in
  /|*..*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/-]*)
    fatal "account home contains unsupported path syntax: $account_home"
    ;;
esac

require_cmd awk
require_cmd gpg
require_cmd gpgconf
require_cmd pinentry-qt
require_cmd runuser

[ -r "$passphrase_file" ] || fatal "GPG bootstrap passphrase file is missing: $passphrase_file"
[ -r "$gpg_agent_template" ] || fatal "GPG agent configuration template is missing: $gpg_agent_template"
gpg_target_cleanup() {
  gpg_cleanup_status=$?
  trap - 0
  account_gpgconf --kill gpg-agent >/dev/null 2>&1 || {
    [ "$gpg_cleanup_status" -ne 0 ] || gpg_cleanup_status=1
  }
  rm -f "$passphrase_file" || {
    [ "$gpg_cleanup_status" -ne 0 ] || gpg_cleanup_status=1
  }
  unset account_password
  exit "$gpg_cleanup_status"
}
trap gpg_target_cleanup 0
trap '\''exit 129'\'' 1
trap '\''exit 130'\'' 2
trap '\''exit 143'\'' 15

uid=$(id -u "$account_user")
gid=$(id -g "$account_user")
install -d -m 0700 "$gnupg_dir"
install -m 0600 "$gpg_agent_template" "$gpg_agent_conf"
chown -R "$uid:$gid" "$gnupg_dir"

IFS= read -r account_password <"$passphrase_file" || fatal "failed to read the primary account GPG passphrase"
[ -n "$account_password" ] || fatal "primary account GPG passphrase is empty"

key_fingerprints=$(gpg_secret_key_fingerprints)
if [ -z "$key_fingerprints" ]; then
  if command -v timeout >/dev/null 2>&1; then
    printf "%s\n" "$account_password" | timeout 120 runuser -u "$account_user" -- env \
      HOME="$account_home" \
      USER="$account_user" \
      LOGNAME="$account_user" \
      GNUPGHOME="$gnupg_dir" \
      PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
      gpg --batch --yes --no-options --pinentry-mode loopback --passphrase-fd 0 \
        --quick-generate-key "$gpg_user_id" future-default default never || \
      fatal "GPG bootstrap key generation failed or timed out"
  else
    printf "%s\n" "$account_password" | runuser -u "$account_user" -- env \
      HOME="$account_home" \
      USER="$account_user" \
      LOGNAME="$account_user" \
      GNUPGHOME="$gnupg_dir" \
      PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
      gpg --batch --yes --no-options --pinentry-mode loopback --passphrase-fd 0 \
        --quick-generate-key "$gpg_user_id" future-default default never || \
      fatal "GPG bootstrap key generation failed"
  fi
  key_fingerprints=$(gpg_secret_key_fingerprints)
fi

set -- $key_fingerprints
[ "$#" -eq 1 ] || fatal "desktop GPG bootstrap requires exactly one managed secret key"
gpg_fingerprint=$1
gpg_validate_fingerprint "$gpg_fingerprint"
gpg_key_can_encrypt "$gpg_fingerprint" ||
  fatal "desktop GPG bootstrap key does not provide an encryption capability"

printf "%s:6:\n" "$gpg_fingerprint" |
  account_gpg --batch --no-options --import-ownertrust >/dev/null 2>&1 ||
  fatal "failed to assign ultimate owner trust to the desktop GPG key"
account_gpg --batch --no-options --check-trustdb >/dev/null 2>&1 ||
  fatal "failed to rebuild desktop GPG trust state"
gpg_key_is_kwallet_suitable "$gpg_fingerprint" ||
  fatal "desktop GPG key is not encryption-capable with ultimate owner trust"

chown -R "$uid:$gid" "$gnupg_dir"
printf "%s\n" "$gpg_fingerprint" >"$fingerprint_file" ||
  fatal "failed to return the managed desktop GPG fingerprint"
printf "desktop_gpg_bootstrap user=%s status=ready gnupg=%s fingerprint=%s\n" \
  "$account_user" "$gnupg_dir" "$gpg_fingerprint"
' sh "$ACCOUNT_USERNAME" "$ACCOUNT_HOME" "$gpg_user_id" "$gpg_passphrase_target" "$gpg_fingerprint_target"; then
    installer_fatal "failed to bootstrap primary account GPG key for KWallet"
  fi

  gpg_fingerprint=$(cat "$gpg_stage/fingerprint") ||
    installer_fatal "managed desktop GPG fingerprint was not returned"
  case "${#gpg_fingerprint}" in
    40|64) ;;
    *) installer_fatal "managed desktop GPG fingerprint has an unsupported length" ;;
  esac
  case "$gpg_fingerprint" in
    *[!0123456789ABCDEF]*) installer_fatal "managed desktop GPG fingerprint is malformed" ;;
  esac
  rm -f "$gpg_stage/passphrase"
  unset gpg_bootstrap_passphrase
  managed_git_ssh_target_action seal --gpg-fingerprint "$gpg_fingerprint" ||
    installer_fatal "failed to GPG-seal the Git SSH passphrase to the managed desktop identity"
  ) || installer_fatal "desktop GPG bootstrap and Git SSH sealing failed"
  unset ACCOUNT_GPG_PASSPHRASE
  ACCOUNT_GPG_PASSPHRASE_IS_PLAIN=false
  desktop_log "bootstrapped_primary_account_gpg_key user=${ACCOUNT_USERNAME}"
}

