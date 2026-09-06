#!/bin/sh

validate_target_ssh_user() {
  : "${ACCOUNT_USERNAME:?ACCOUNT_USERNAME must be set}"
  : "${ACCOUNT_HOME:?ACCOUNT_HOME must be set}"

  case "$ACCOUNT_USERNAME" in
    [abcdefghijklmnopqrstuvwxyz_]*)
      ;;
    *)
      installer_fatal "ACCOUNT_USERNAME must start with a lowercase letter or underscore"
      ;;
  esac
  case "$ACCOUNT_USERNAME" in
    *[!abcdefghijklmnopqrstuvwxyz0123456789_-]*)
      installer_fatal "ACCOUNT_USERNAME contains unsupported characters for SSH provisioning"
      ;;
  esac
  case "$ACCOUNT_HOME" in
    /*) ;;
    *)
      installer_fatal "ACCOUNT_HOME must be an absolute path for SSH provisioning"
      ;;
  esac
  case "$ACCOUNT_HOME" in
    /|*..*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/-]*)
      installer_fatal "ACCOUNT_HOME contains unsupported path syntax for SSH provisioning"
      ;;
  esac
}

validate_ssh_public_key_file() {
  key_file=$1
  key_count=0
  key_line=

  while IFS= read -r line || [ -n "$line" ]; do
    trimmed_line=$(printf '%s' "$line" | sed 's/[[:space:]]*#.*$//; s/^[[:space:]]*//; s/[[:space:]]*$//')
    [ -n "$trimmed_line" ] || continue
    key_count=$((key_count + 1))
    [ "$key_count" -le 1 ] || break
    key_line=$trimmed_line
  done <"$key_file"

  if [ "$key_count" -ne 1 ]; then
    installer_fatal "SSH public key source must contain exactly one key"
  fi

  # shellcheck disable=SC2086
  set -- $key_line
  [ "$#" -ge 2 ] || installer_fatal "SSH public key must be a single ssh-ed25519 public key without authorized_keys options"
  [ "$1" = "ssh-ed25519" ] || installer_fatal "SSH public key must be a single ssh-ed25519 public key without authorized_keys options"
  case "$2" in
    ''|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=]*)
      installer_fatal "SSH public key must be a single ssh-ed25519 public key without authorized_keys options"
      ;;
  esac
  [ "${#2}" -le 2048 ] || installer_fatal "SSH public key must be a single ssh-ed25519 public key without authorized_keys options"
}

write_authorized_keys_from_public_key() {
  key_file=$1
  dest=$2
  key_line=

  while IFS= read -r line || [ -n "$line" ]; do
    trimmed_line=$(printf '%s' "$line" | sed 's/[[:space:]]*#.*$//; s/^[[:space:]]*//; s/[[:space:]]*$//')
    [ -n "$trimmed_line" ] || continue
    key_line=$trimmed_line
    break
  done <"$key_file"
  [ -n "$key_line" ] || installer_fatal "SSH public key source did not contain a usable key"
  # shellcheck disable=SC2086
  set -- $key_line
  printf '%s %s\n' "$1" "$2" >"$dest"
  chmod 0600 "$dest"
}

render_ssh_template() {
  src=$1
  dest=$2
  mode=$3
  fqdn="${SYSTEM_HOSTNAME}.${SYSTEM_DOMAIN}"

  installer_apply_scalar_placeholders "$src" "$dest" \
    ACCOUNT_USERNAME "$ACCOUNT_USERNAME" \
    ACCOUNT_HOME "$ACCOUNT_HOME" \
    SSH_PORT "$SSH_PORT" \
    SYSTEM_HOSTNAME "$SYSTEM_HOSTNAME" \
    SYSTEM_DOMAIN "$SYSTEM_DOMAIN" \
    SYSTEM_FQDN "$fqdn"
  installer_assert_no_unresolved_installer_placeholders "$dest" "SSH template ${src}"
  chmod "$mode" "$dest"
}

validate_ssh_template_context() {
  case "${SSH_PORT:-}" in
    ''|*[!0-9]*)
      installer_fatal "SSH_PORT is not safe for SSH template rendering"
      ;;
  esac
  [ "$SSH_PORT" -ge 1 ] && [ "$SSH_PORT" -le 65535 ] || {
    installer_fatal "SSH_PORT must be in range 1..65535"
  }
  case "$SYSTEM_HOSTNAME" in
    ''|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-]*|-*|*-)
      installer_fatal "SYSTEM_HOSTNAME is not safe for SSH template rendering"
      ;;
  esac
  case "$SYSTEM_DOMAIN" in
    ''|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.-]*|.*|*.|*..*)
      installer_fatal "SYSTEM_DOMAIN is not safe for SSH template rendering"
      ;;
  esac
}

xssh_helpers_role_selected() {
  if ! command -v installer_selected_class_reference_is_selected >/dev/null 2>&1; then
    installer_fatal "installer class selection helpers are unavailable for xssh helper staging"
  fi

  installer_selected_class_reference_is_selected role/desktop
}

render_ssh_user_config_template() {
  src=$1
  dest=$2
  mode=$3

  installer_apply_scalar_placeholders "$src" "$dest" \
    ACCOUNT_USERNAME "$ACCOUNT_USERNAME" \
    ACCOUNT_HOME "$ACCOUNT_HOME"
  installer_assert_no_unresolved_installer_placeholders "$dest" "SSH user template ${src}"
  chmod "$mode" "$dest"
}

stage_target_xssh_helpers() {
  xssh_helpers_role_selected || return 0

  if ! test_in_target dpkg-query -s openssh-client; then
    installer_fatal "openssh-client must be preinstalled by pkgsel when xssh helper staging is enabled"
  fi

  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/bin/xssh-send)" "${FILE_XSSH_SEND}" 0755
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/bin/xssh-retrieve)" "${FILE_XSSH_RETRIEVE}" 0755
}

provision_target_ssh_client() {
  xssh_helpers_role_selected || return 0

  : "${SSH_USER_CONFIG_SOURCE:?SSH_USER_CONFIG_SOURCE must be set}"
  : "${SSH_USER_CONFIG_TARGET:?SSH_USER_CONFIG_TARGET must be set}"

  validate_target_ssh_user

  if ! test_in_target dpkg-query -s openssh-client; then
    installer_fatal "openssh-client must be preinstalled by pkgsel when SSH client provisioning is enabled"
  fi

  case "$SSH_USER_CONFIG_TARGET" in
    "${ACCOUNT_HOME}/.ssh/config") ;;
    *)
      installer_fatal "SSH_USER_CONFIG_TARGET must be ${ACCOUNT_HOME}/.ssh/config"
      ;;
  esac

  ssh_tmp="${TMP_ENV_DIR}/ssh-client"
  ssh_stage="/tmp/install-ssh-client.$$"
  target_ssh_stage="/target${ssh_stage}"
  install -d -m 0700 "$ssh_tmp" "$target_ssh_stage"
  fetch_ssh_asset "$SSH_USER_CONFIG_SOURCE" "$ssh_tmp/user_config" "${SSH_CONFIG_MAX_BYTES:-65536}"
  render_ssh_user_config_template "$ssh_tmp/user_config" "$target_ssh_stage/user_config.rendered" 0600

  # shellcheck disable=SC2016
  run_in_target "install managed SSH client config" /bin/sh -c '
set -eu
account_user=$1
account_home=$2
user_config_target=$3
stage=$4

uid=$(id -u "$account_user")
gid=$(id -g "$account_user")

install -d -m 0700 "$account_home"
install -d -m 0700 "$account_home/.ssh"
install -m 0600 "$stage/user_config.rendered" "$user_config_target"
chown "$uid:$gid" "$account_home" "$account_home/.ssh" "$user_config_target"
rm -rf "$stage"
' sh "$ACCOUNT_USERNAME" "$ACCOUNT_HOME" "$SSH_USER_CONFIG_TARGET" "$ssh_stage"
}

provision_target_ssh_server() {
  [ "${SSH_SERVER_ENABLED:-false}" = "true" ] || return 0

  : "${SSH_PUBLIC_KEY_SOURCE:?SSH_PUBLIC_KEY_SOURCE must be set}"
  : "${SSHD_CONFIG_SOURCE:?SSHD_CONFIG_SOURCE must be set}"
  : "${SSH_USER_CONFIG_SOURCE:?SSH_USER_CONFIG_SOURCE must be set}"
  : "${SSH_AUTHORIZED_KEYS_TARGET:?SSH_AUTHORIZED_KEYS_TARGET must be set}"
  : "${SSH_USER_CONFIG_TARGET:?SSH_USER_CONFIG_TARGET must be set}"

  if ! command -v in-target >/dev/null 2>&1; then
    installer_fatal "in-target is unavailable during SSH provisioning"
  fi

  validate_target_ssh_user
  validate_ssh_template_context

  ssh_tmp="${TMP_ENV_DIR}/ssh"
  install -d -m 0700 "$ssh_tmp"
  fetch_ssh_asset "$SSH_PUBLIC_KEY_SOURCE" "$ssh_tmp/authorized_key.pub" "${SSH_PUBLIC_KEY_MAX_BYTES:-4096}"
  fetch_ssh_asset "$SSHD_CONFIG_SOURCE" "$ssh_tmp/sshd_config" "${SSH_CONFIG_MAX_BYTES:-65536}"
  validate_ssh_public_key_file "$ssh_tmp/authorized_key.pub"

  if ! test_in_target dpkg-query -s openssh-server; then
    installer_fatal "openssh-server must be preinstalled by pkgsel when SSH server provisioning is enabled"
  fi
  run_in_target "generate SSH host keys" /usr/bin/ssh-keygen -A

  case "$SSH_AUTHORIZED_KEYS_TARGET" in
    "${ACCOUNT_HOME}/.ssh/authorized_keys") ;;
    *)
      installer_fatal "SSH_AUTHORIZED_KEYS_TARGET must be ${ACCOUNT_HOME}/.ssh/authorized_keys"
      ;;
  esac
  case "$SSH_USER_CONFIG_TARGET" in
    "${ACCOUNT_HOME}/.ssh/config") ;;
    *)
      installer_fatal "SSH_USER_CONFIG_TARGET must be ${ACCOUNT_HOME}/.ssh/config"
      ;;
  esac

  ssh_stage="/tmp/install-ssh.$$"
  target_ssh_stage="/target${ssh_stage}"
  install -d -m 0700 "$target_ssh_stage"
  render_ssh_template "$ssh_tmp/sshd_config" "$target_ssh_stage/sshd_config" 0644
  write_authorized_keys_from_public_key "$ssh_tmp/authorized_key.pub" "$target_ssh_stage/authorized_keys"

  # shellcheck disable=SC2016
  run_in_target "install SSH configuration and keys" /bin/sh -c '
set -eu
account_user=$1
account_home=$2
authorized_keys_target=$3
user_config_target=$4
stage=$5

uid=$(id -u "$account_user")
gid=$(id -g "$account_user")
usermod -d "$account_home" "$account_user"

install -d -m 0755 /etc/ssh
if [ -f /etc/ssh/sshd_config ] && [ ! -f /etc/ssh/sshd_config.install.orig ]; then
  cp -p /etc/ssh/sshd_config /etc/ssh/sshd_config.install.orig
fi
install -m 0644 "$stage/sshd_config" /etc/ssh/sshd_config

install -d -m 0700 "$account_home/.ssh"
install -m 0600 "$stage/authorized_keys" "$authorized_keys_target"
chown "$uid:$gid" "$account_home" "$account_home/.ssh" "$authorized_keys_target"
rm -rf "$stage"
' sh "$ACCOUNT_USERNAME" "$ACCOUNT_HOME" "$SSH_AUTHORIZED_KEYS_TARGET" "$ssh_stage"

  # shellcheck disable=SC2016
  run_in_target "check SSH artifacts if tools are available" /bin/sh -c '
set -eu
account_user=$1
authorized_keys_target=$2

account_uid=$(id -u "$account_user")
account_gid=$(id -g "$account_user")

[ -r /etc/ssh/sshd_config ]
[ -d "$(dirname "$authorized_keys_target")" ]
[ -r "$authorized_keys_target" ]
[ "$(stat -c %u "$authorized_keys_target")" = "$account_uid" ]
[ "$(stat -c %g "$authorized_keys_target")" = "$account_gid" ]

if [ -x /usr/bin/ssh-keygen ]; then
  /usr/bin/ssh-keygen -l -f "$authorized_keys_target" >/dev/null ||
    echo "warn: installed authorized_keys did not validate during d-i"
else
  echo "warn: ssh-keygen is unavailable in target; skipping authorized_keys validation"
fi

if [ -x /usr/sbin/sshd ]; then
  install -d -m 0755 /run/sshd
  /usr/sbin/sshd -t -f /etc/ssh/sshd_config ||
    echo "warn: sshd_config validation failed during d-i; leaving rendered config for runtime"
else
  echo "warn: sshd is unavailable in target; skipping sshd_config validation"
fi
' sh "$ACCOUNT_USERNAME" "$SSH_AUTHORIZED_KEYS_TARGET"

  if command -v stage_target_systemd_unit_enabled >/dev/null 2>&1 &&
    command -v target_unit_exists >/dev/null 2>&1; then
    if target_unit_exists ssh.service; then
      stage_target_systemd_unit_enabled ssh.service system
    else
      installer_warn "ssh.service unit is unavailable in target during d-i; skipping staged enablement"
    fi
  else
    installer_warn "systemd staging helpers are unavailable; skipping ssh.service staged enablement"
  fi
}
