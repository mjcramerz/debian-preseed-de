#!/bin/sh
# Shared account debconf rendering for every installer storage family.
# shellcheck disable=SC2034

if ! command -v runtime_fatal >/dev/null 2>&1; then
  if [ -n "${RUNTIME_COMMON_LIB:-}" ] && [ -r "$RUNTIME_COMMON_LIB" ]; then
    # shellcheck disable=SC1090
    . "$RUNTIME_COMMON_LIB"
  else
    printf 'fatal: runtime common helper is unavailable; set RUNTIME_COMMON_LIB before sourcing %s\n' "${0##*/}" >&2
    exit 1
  fi
fi

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

runtime_validate_account_fullname() {
  value=$1

  [ -n "$value" ] || runtime_fatal "ACCOUNT_FULLNAME must not be empty"
  case "$value" in
    *[![:print:]]*)
      runtime_fatal "ACCOUNT_FULLNAME must not contain control characters"
      ;;
    [[:space:]]*|*[[:space:]])
      runtime_fatal "ACCOUNT_FULLNAME must not start or end with whitespace"
      ;;
  esac
}

runtime_validate_account_username() {
  value=$1

  printf '%s\n' "$value" | LC_ALL=C grep -Eq '^[a-z_][a-z0-9_-]*$' || \
    runtime_fatal "ACCOUNT_USERNAME must match ^[a-z_][a-z0-9_-]*$"
}

runtime_account_apply_home_paths() {
  ACCOUNT_HOME="/home/${ACCOUNT_USERNAME}"
  DIR_HOME_DESKTOP="${ACCOUNT_HOME}/Desktop"
  DIR_HOME_DOCUMENTS="${ACCOUNT_HOME}/Documents"
  DIR_HOME_DOWNLOADS="${ACCOUNT_HOME}/Downloads"
  DIR_HOME_MUSIC="${ACCOUNT_HOME}/Music"
  DIR_HOME_PUBLIC="${ACCOUNT_HOME}/Public"
  DIR_HOME_PICTURES="${ACCOUNT_HOME}/Pictures"
  DIR_HOME_TEMPLATES="${ACCOUNT_HOME}/Templates"
  DIR_HOME_VIDEOS="${ACCOUNT_HOME}/Videos"
  DIR_HOME_WORKSPACE="${ACCOUNT_HOME}/Workspace"
  DIR_HOME_SYNCTHING="${ACCOUNT_HOME}/Syncthing"
  DIR_HOME_LOCAL_STATE="${ACCOUNT_HOME}/.local/state"
  DIR_HOME_SYNCTHING_STATE="${DIR_HOME_LOCAL_STATE}/syncthing"
  SSH_AUTHORIZED_KEYS_TARGET="${ACCOUNT_HOME}/.ssh/authorized_keys"
  SSH_USER_CONFIG_TARGET="${ACCOUNT_HOME}/.ssh/config"
}

runtime_apply_account_from_cmdline() {
  [ "${RUNTIME_ACCOUNT_CMDLINE_READY:-0}" = 1 ] && return 0

  primary_user_raw=$(runtime_cmdline_value primary_user 2>/dev/null || true)
  primary_password_raw=$(runtime_cmdline_value primary_password 2>/dev/null || true)
  primary_gpg_passphrase_raw=$(runtime_cmdline_value primary_gpg_passphrase 2>/dev/null || true)
  root_password_raw=$(runtime_cmdline_value root_password 2>/dev/null || true)

  if [ -n "$primary_user_raw" ]; then
    runtime_validate_printable_single_line primary_user "$primary_user_raw"
    runtime_validate_account_username "$primary_user_raw"
    ACCOUNT_USERNAME=$primary_user_raw
  fi

  if [ -n "$primary_password_raw" ]; then
    runtime_validate_printable_single_line primary_password "$primary_password_raw"
    ACCOUNT_PASSWORD=$primary_password_raw
    ACCOUNT_PASSWORD_IS_PLAIN=true
  else
    ACCOUNT_PASSWORD=
    ACCOUNT_PASSWORD_IS_PLAIN=false
  fi

  if [ -n "$primary_gpg_passphrase_raw" ]; then
    runtime_validate_printable_single_line primary_gpg_passphrase "$primary_gpg_passphrase_raw"
    ACCOUNT_GPG_PASSPHRASE=$primary_gpg_passphrase_raw
    ACCOUNT_GPG_PASSPHRASE_IS_PLAIN=true
  elif [ -n "$primary_password_raw" ]; then
    ACCOUNT_GPG_PASSPHRASE=$primary_password_raw
    ACCOUNT_GPG_PASSPHRASE_IS_PLAIN=true
  else
    ACCOUNT_GPG_PASSPHRASE=
    ACCOUNT_GPG_PASSPHRASE_IS_PLAIN=false
  fi

  if [ -n "$root_password_raw" ]; then
    runtime_validate_printable_single_line root_password "$root_password_raw"
    ROOT_PASSWORD=$root_password_raw
    ROOT_PASSWORD_IS_PLAIN=true
  else
    ROOT_PASSWORD=
    ROOT_PASSWORD_IS_PLAIN=false
  fi

  runtime_account_apply_home_paths
  unset \
    primary_user_raw \
    primary_password_raw \
    primary_gpg_passphrase_raw \
    root_password_raw
  RUNTIME_ACCOUNT_CMDLINE_READY=1
}

runtime_validate_account_groups() {
  value=$1

  printf '%s\n' "$value" | LC_ALL=C grep -Eq '^[A-Za-z0-9_-]+( [A-Za-z0-9_-]+)*$' || \
    runtime_fatal "ACCOUNT_DEFAULT_GROUPS must be a space-separated group list"
}

runtime_validate_account_settings() {
  runtime_apply_account_from_cmdline

  : "${ROOT_LOGIN:?ROOT_LOGIN must be set}"
  : "${ACCOUNT_USERNAME:?ACCOUNT_USERNAME must be set}"
  : "${ACCOUNT_FULLNAME:?ACCOUNT_FULLNAME must be set}"
  : "${ACCOUNT_DEFAULT_GROUPS:?ACCOUNT_DEFAULT_GROUPS must be set}"

  if ! runtime_bool_is_true "$ROOT_LOGIN"; then
    runtime_fatal "ROOT_LOGIN must be true; local root login is required (SSH root login stays disabled)"
  fi
  ROOT_LOGIN=true

  runtime_validate_account_username "$ACCOUNT_USERNAME"
  runtime_validate_account_fullname "$ACCOUNT_FULLNAME"
  runtime_validate_account_groups "$ACCOUNT_DEFAULT_GROUPS"

  if [ "${ROOT_PASSWORD_IS_PLAIN:-false}" != true ]; then
    runtime_fatal "root password is required: use root_password= on the installer command line, or PRESEED_ROOT_PASSWORD in /preseed.env when root_password is absent; an empty or bare root_password blocks fallback"
  fi
  runtime_validate_printable_single_line ROOT_PASSWORD "${ROOT_PASSWORD:-}"

  if [ "${ACCOUNT_PASSWORD_IS_PLAIN:-false}" = true ]; then
    runtime_validate_printable_single_line ACCOUNT_PASSWORD "$ACCOUNT_PASSWORD"
  else
    : "${ACCOUNT_PASSWORD_CRYPTED:?ACCOUNT_PASSWORD_CRYPTED must be set}"
    runtime_validate_printable_single_line ACCOUNT_PASSWORD_CRYPTED "$ACCOUNT_PASSWORD_CRYPTED"
  fi

  if [ "${ACCOUNT_GPG_PASSPHRASE_IS_PLAIN:-false}" = true ]; then
    runtime_validate_printable_single_line \
      ACCOUNT_GPG_PASSPHRASE \
      "$ACCOUNT_GPG_PASSPHRASE"
  fi
}

runtime_write_account_answers() {
  dest=$1

  runtime_validate_account_settings
  runtime_prepare_parent_dir "$dest" 0700
  {
    printf '##########  Runtime Account Configuration  ##########\n'
    printf '# Generated inside the installer from hosts/installer/account.env.\n'
    printf 'd-i passwd/root-login boolean %s\n' "$ROOT_LOGIN"
    printf 'd-i passwd/root-login seen true\n'
    # Clear any stale hash/lock answer before supplying the selected plaintext
    # password. In particular, an earlier "!" must not keep root locked.
    printf 'd-i passwd/root-password-crypted password\n'
    printf 'd-i passwd/root-password-crypted seen true\n'
    printf 'd-i passwd/root-password password %s\n' "$ROOT_PASSWORD"
    printf 'd-i passwd/root-password seen true\n'
    printf 'd-i passwd/root-password-again password %s\n' "$ROOT_PASSWORD"
    printf 'd-i passwd/root-password-again seen true\n'
    printf 'd-i passwd/make-user boolean true\n'
    printf 'd-i passwd/make-user seen true\n'
    printf 'd-i passwd/user-fullname string %s\n' "$ACCOUNT_FULLNAME"
    printf 'd-i passwd/user-fullname seen true\n'
    printf 'd-i passwd/username string %s\n' "$ACCOUNT_USERNAME"
    printf 'd-i passwd/username seen true\n'
    if [ "${ACCOUNT_PASSWORD_IS_PLAIN:-false}" = true ]; then
      printf 'd-i passwd/user-password password %s\n' "$ACCOUNT_PASSWORD"
      printf 'd-i passwd/user-password seen true\n'
      printf 'd-i passwd/user-password-again password %s\n' "$ACCOUNT_PASSWORD"
      printf 'd-i passwd/user-password-again seen true\n'
    else
      printf 'd-i passwd/user-password-crypted password %s\n' "$ACCOUNT_PASSWORD_CRYPTED"
      printf 'd-i passwd/user-password-crypted seen true\n'
    fi
    printf 'd-i passwd/user-default-groups string %s\n' "$ACCOUNT_DEFAULT_GROUPS"
    printf 'd-i passwd/user-default-groups seen true\n'
    printf 'd-i user-setup/allow-password-weak boolean false\n'
    printf 'd-i user-setup/allow-password-weak seen true\n'
  } >"$dest"
  chmod 0600 "$dest"
}

runtime_write_effective_account_env() {
  dest=$1

  runtime_apply_account_from_cmdline
  runtime_validate_account_username "$ACCOUNT_USERNAME"
  runtime_validate_account_fullname "$ACCOUNT_FULLNAME"
  runtime_validate_account_groups "$ACCOUNT_DEFAULT_GROUPS"
  runtime_prepare_parent_dir "$dest" 0700
  {
    printf '# Generated inside the installer from hosts/installer/account.env plus resolved installer identity overrides.\n'
    printf 'ROOT_LOGIN=%s\n' "$(runtime_shell_quote "$ROOT_LOGIN")"
    printf 'ACCOUNT_USERNAME=%s\n' "$(runtime_shell_quote "$ACCOUNT_USERNAME")"
    printf 'ACCOUNT_FULLNAME=%s\n' "$(runtime_shell_quote "$ACCOUNT_FULLNAME")"
    printf 'ACCOUNT_DEFAULT_GROUPS=%s\n' "$(runtime_shell_quote "$ACCOUNT_DEFAULT_GROUPS")"
    printf 'ACCOUNT_HOME=%s\n' "$(runtime_shell_quote "$ACCOUNT_HOME")"
    printf 'DIR_HOME_DESKTOP=%s\n' "$(runtime_shell_quote "$DIR_HOME_DESKTOP")"
    printf 'DIR_HOME_DOCUMENTS=%s\n' "$(runtime_shell_quote "$DIR_HOME_DOCUMENTS")"
    printf 'DIR_HOME_DOWNLOADS=%s\n' "$(runtime_shell_quote "$DIR_HOME_DOWNLOADS")"
    printf 'DIR_HOME_MUSIC=%s\n' "$(runtime_shell_quote "$DIR_HOME_MUSIC")"
    printf 'DIR_HOME_PUBLIC=%s\n' "$(runtime_shell_quote "$DIR_HOME_PUBLIC")"
    printf 'DIR_HOME_PICTURES=%s\n' "$(runtime_shell_quote "$DIR_HOME_PICTURES")"
    printf 'DIR_HOME_TEMPLATES=%s\n' "$(runtime_shell_quote "$DIR_HOME_TEMPLATES")"
    printf 'DIR_HOME_VIDEOS=%s\n' "$(runtime_shell_quote "$DIR_HOME_VIDEOS")"
    printf 'DIR_HOME_WORKSPACE=%s\n' "$(runtime_shell_quote "$DIR_HOME_WORKSPACE")"
    printf 'DIR_HOME_SYNCTHING=%s\n' "$(runtime_shell_quote "$DIR_HOME_SYNCTHING")"
    printf 'DIR_HOME_LOCAL_STATE=%s\n' "$(runtime_shell_quote "$DIR_HOME_LOCAL_STATE")"
    printf 'DIR_HOME_SYNCTHING_STATE=%s\n' "$(runtime_shell_quote "$DIR_HOME_SYNCTHING_STATE")"
    printf 'SSH_PUBLIC_KEY_SOURCE=%s\n' "$(runtime_shell_quote "$SSH_PUBLIC_KEY_SOURCE")"
    printf 'SSHD_CONFIG_SOURCE=%s\n' "$(runtime_shell_quote "$SSHD_CONFIG_SOURCE")"
    printf 'SSH_USER_CONFIG_SOURCE=%s\n' "$(runtime_shell_quote "$SSH_USER_CONFIG_SOURCE")"
    printf 'SSH_PUBLIC_KEY_MAX_BYTES=%s\n' "$(runtime_shell_quote "$SSH_PUBLIC_KEY_MAX_BYTES")"
    printf 'SSH_CONFIG_MAX_BYTES=%s\n' "$(runtime_shell_quote "$SSH_CONFIG_MAX_BYTES")"
    printf 'SSH_AUTHORIZED_KEYS_TARGET=%s\n' "$(runtime_shell_quote "$SSH_AUTHORIZED_KEYS_TARGET")"
    printf 'SSH_USER_CONFIG_TARGET=%s\n' "$(runtime_shell_quote "$SSH_USER_CONFIG_TARGET")"
    printf 'FRUUX_CALENDAR_USERNAME=%s\n' "$(runtime_shell_quote "${FRUUX_CALENDAR_USERNAME:-}")"
    printf 'FRUUX_CALENDAR_PASSWORD=%s\n' "$(runtime_shell_quote "${FRUUX_CALENDAR_PASSWORD:-}")"
  } >"$dest"
  chmod 0600 "$dest"
}
