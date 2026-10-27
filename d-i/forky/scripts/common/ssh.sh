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
    SSH_SERVER_CIDR_ALLOW "$SSH_SERVER_CIDR_ALLOW" \
    SSH_SERVER_USER_ALLOW "$SSH_SERVER_USER_ALLOW" \
    SSH_SERVER_LISTEN_ADDRESS_ETHERNET "$SSH_SERVER_LISTEN_ADDRESS_ETHERNET" \
    SSH_SERVER_LISTEN_ADDRESS_WIFI_LINE "$SSH_SERVER_LISTEN_ADDRESS_WIFI_LINE" \
    SYSTEM_HOSTNAME "$SYSTEM_HOSTNAME" \
    SYSTEM_DOMAIN "$SYSTEM_DOMAIN" \
    SYSTEM_FQDN "$fqdn"
  installer_assert_no_unresolved_installer_placeholders "$dest" "SSH template ${src}"
  chmod "$mode" "$dest"
}

validate_ssh_server_profile_context() {
  ssh_cidr=${SSH_SERVER_CIDR_ALLOW:-}
  ssh_cidr_address=${ssh_cidr%/*}
  ssh_cidr_prefix=${ssh_cidr#*/}
  case "$ssh_cidr" in
    */*) ;;
    *) installer_fatal "SSH_SERVER_CIDR_ALLOW must be an IPv4 CIDR" ;;
  esac
  case "$ssh_cidr" in
    ''|*[!0123456789./]*) installer_fatal "SSH_SERVER_CIDR_ALLOW contains unsupported characters" ;;
  esac
  case "$ssh_cidr_prefix" in
    ''|*[!0-9]*) installer_fatal "SSH_SERVER_CIDR_ALLOW has an invalid prefix" ;;
  esac
  [ "$ssh_cidr_prefix" -le 32 ] ||
    installer_fatal "SSH_SERVER_CIDR_ALLOW prefix must be in range 0..32"
  printf '%s\n' "$ssh_cidr_address" | awk -F. '
    NF != 4 { exit 1 }
    { for (i = 1; i <= 4; i++) if ($i !~ /^[0-9]+$/ || $i > 255) exit 1 }
  ' || installer_fatal "SSH_SERVER_CIDR_ALLOW must contain a valid IPv4 address"

  case "${SSH_SERVER_USER_ALLOW:-}" in
    ''|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-]*)
      installer_fatal "SSH_SERVER_USER_ALLOW contains unsupported username characters" ;;
  esac
  [ "$SSH_SERVER_USER_ALLOW" = "$ACCOUNT_USERNAME" ] ||
    installer_fatal "SSH_SERVER_USER_ALLOW must match the provisioned account username"
}

ssh_ipv4_increment() {
  ssh_base_address=$1
  printf '%s\n' "$ssh_base_address" | awk -F. '
    NF != 4 { exit 1 }
    { for (i = 1; i <= 4; i++) if ($i !~ /^[0-9]+$/ || $i > 255) exit 1 }
    { value = (($1 * 256 + $2) * 256 + $3) * 256 + $4 + 1 }
    value > 4294967295 { exit 1 }
    { printf "%d.%d.%d.%d\n", int(value / 16777216) % 256,
        int(value / 65536) % 256, int(value / 256) % 256, value % 256 }
  '
}

resolve_ssh_server_listen_addresses() {
  ssh_server_base_address=${MANAGED_NETWORK_IPV4_ADDRESS:-}
  if [ -z "$ssh_server_base_address" ] && command -v network_answer_value >/dev/null 2>&1; then
    ssh_server_base_address=$(network_answer_value netcfg/get_ipaddress ip 2>/dev/null || true)
  fi
  [ -n "$ssh_server_base_address" ] ||
    installer_fatal "static IPv4 address is required before enabling the SSH server"
  printf '%s\n' "$ssh_server_base_address" | awk -F. '
    NF == 4 { for (i = 1; i <= 4; i++) if ($i !~ /^[0-9]+$/ || $i > 255) exit 1; next }
    { exit 1 }
  ' || installer_fatal "managed static IPv4 address is invalid for SSH ListenAddress"

  SSH_SERVER_LISTEN_ADDRESS_ETHERNET=$ssh_server_base_address
  ssh_server_wifi_address=
  SSH_SERVER_LISTEN_ADDRESS_WIFI_LINE='# Wi-Fi ListenAddress omitted: no managed Wi-Fi link'
  ssh_server_link_types=
  if command -v target_managed_network_link_types >/dev/null 2>&1; then
    ssh_server_link_types=$(target_managed_network_link_types 2>/dev/null || true)
  fi
  case " $ssh_server_link_types " in
    *" wifi "*)
      ssh_server_wifi_address=$(ssh_ipv4_increment "$ssh_server_base_address") ||
        installer_fatal "managed static IPv4 address cannot derive the Wi-Fi ListenAddress"
      SSH_SERVER_LISTEN_ADDRESS_WIFI_LINE="ListenAddress ${ssh_server_wifi_address}"
      ;;
  esac
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
  validate_ssh_server_profile_context
  resolve_ssh_server_listen_addresses
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
    ACCOUNT_HOME "$ACCOUNT_HOME" \
    DIR_DATA_PKI "$DIR_DATA_PKI"
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
stage=$4

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
  run_in_target "verify SSH artifacts before service enablement" /bin/sh -c '
set -eu
account_user=$1
authorized_keys_target=$2

account_uid=$(id -u "$account_user")
account_gid=$(id -g "$account_user")

[ -r /etc/ssh/sshd_config ]
[ -d "$(dirname "$authorized_keys_target")" ]
[ -r "$authorized_keys_target" ]
[ "$(find -P "$authorized_keys_target" -maxdepth 0 -printf %U)" = "$account_uid" ]
[ "$(find -P "$authorized_keys_target" -maxdepth 0 -printf %G)" = "$account_gid" ]

[ -x /usr/bin/ssh-keygen ] && [ -x /usr/sbin/sshd ] || {
  echo "fatal: packaged OpenSSH verification tools are missing" >&2
  exit 1
}
/usr/bin/ssh-keygen -l -f "$authorized_keys_target" >/dev/null
install -d -m 0755 /run/sshd
/usr/sbin/sshd -t -f /etc/ssh/sshd_config
' sh "$ACCOUNT_USERNAME" "$SSH_AUTHORIZED_KEYS_TARGET"

  if command -v stage_target_systemd_unit_enabled >/dev/null 2>&1 &&
    command -v target_unit_exists >/dev/null 2>&1; then
    if target_unit_exists ssh.service && target_unit_exists ssh.socket; then
      # Wi-Fi's configured address is always Ethernet +1. The interface need
      # not have that address assigned while disconnected or suppressed by
      # Ethernet preference. FreeBind keeps both explicit listeners at boot.
      # The packaged Debian sshd consumes systemd's listening descriptors.
      ssh_socket_wifi_line='# No managed Wi-Fi listener'
      if [ -n "$ssh_server_wifi_address" ]; then
        ssh_socket_wifi_line="ListenStream=${ssh_server_wifi_address}:${SSH_PORT}"
      fi
      write_target_file /etc/systemd/system/ssh.socket.d/40-managed-listeners.conf 0644 <<EOF
[Socket]
ListenStream=
ListenStream=${SSH_SERVER_LISTEN_ADDRESS_ETHERNET}:${SSH_PORT}
${ssh_socket_wifi_line}
FreeBind=yes
EOF
      stage_target_systemd_unit_enabled ssh.socket system
      # Debian's socket activation guidance requires ssh.service to be
      # disabled when ssh.socket is enabled. Otherwise sshd starts at boot
      # and attempts the same explicit binds itself, defeating FreeBind.
      command -v unstage_target_systemd_unit_enabled >/dev/null 2>&1 ||
        installer_fatal "systemd unstage helper is unavailable for SSH socket activation"
      unstage_target_systemd_unit_enabled ssh.service system
    else
      installer_fatal "packaged ssh.service and ssh.socket units are required during SSH server provisioning"
    fi
  else
    installer_fatal "systemd staging helpers are unavailable during SSH server provisioning"
  fi
}

# Subshell: tracing is disabled before reading any secret; neither the caller's
# environment nor generated account.env ever receives the passphrase. The
# normal run_in_target wrapper redirects stdin to /dev/null, so use a direct
# chroot here with a clean environment and a private pipe instead.
managed_git_ssh_target_action() (
  set +x
  set +v
  set -eu
  umask 077
  [ "$#" -ge 1 ] || exit 64
  action=$1
  shift
  case "$action" in provision|seal|clone-codex|clone-obsidian|clone-netscape) ;; *) exit 64 ;; esac
  target=${INSTALLER_TARGET_DIR:-/target}
  # This common helper also runs from standalone add-on hooks. It must not
  # depend on late/core.sh's theme-aware fetch_hook wrapper.
  command -v fetch_hook_file >/dev/null 2>&1 ||
    installer_fatal "shared SSH asset fetch helper is unavailable"
  case "$target" in
    /*) ;;
    *) installer_fatal "private SSH target must be an absolute directory" ;;
  esac
  case "$target" in
    /|*//*|*/../*|*/..|*/./*|*/.)
      installer_fatal "private SSH target must be a normalized non-root directory" ;;
  esac
  target=${target%/}
  [ -d "$target" ] && [ ! -L "$target" ] &&
    [ -d "$target/tmp" ] && [ ! -L "$target/tmp" ] ||
    installer_fatal "private SSH target and its /tmp must be real directories"
  validate_target_ssh_user || exit 1
  # Fixed source contract: do not permit a seed URL or target-side substitute.
  [ "${GIT_SSH_PRIVATE_KEY_INITRD:-/git_ed25519}" = /git_ed25519 ] &&
    [ "${GIT_SSH_PUBLIC_KEY_INITRD:-/git_ed25519.pub}" = /git_ed25519.pub ] ||
    installer_fatal "Git SSH inputs must use the fixed private initrd paths"
  preseed_env_check_file /git_ed25519 || installer_fatal "missing/unsafe private initrd Git SSH key"
  preseed_env_check_file /git_ed25519.pub || installer_fatal "missing/unsafe private initrd Git SSH public key"
  [ "$(wc -c </git_ed25519)" -le 16384 ] || installer_fatal "Git SSH private key exceeds size limit"
  [ "$(wc -c </git_ed25519.pub)" -le 4096 ] || installer_fatal "Git SSH public key exceeds size limit"
  validate_ssh_public_key_file /git_ed25519.pub || exit 1
  stage=$(mktemp -d "${target}/tmp/git-ssh.XXXXXX") ||
    installer_fatal "cannot allocate private Git SSH staging directory"
  own_proc=0
  own_dev=0
  managed_ssh_cleanup() {
    saved_status=$?
    trap - 0
    if [ "$saved_status" -eq 76 ] || [ -e "$stage/cleanup-outcome-unknown" ]; then
      unset secret
      printf '%s\n' "SSH cleanup outcome unknown; staging and owned runtime mounts retained: $stage" >&2
      exit 76
    fi
    rm -rf -- "$stage" || { [ "$saved_status" -ne 0 ] || saved_status=1; }
    unset secret
    if [ "$own_proc" -eq 1 ]; then
      umount "${target}/proc" || { [ "$saved_status" -ne 0 ] || saved_status=1; }
    fi
    if [ "$own_dev" -eq 1 ]; then
      umount "${target}/dev" || { [ "$saved_status" -ne 0 ] || saved_status=1; }
    fi
    exit "$saved_status"
  }
  trap managed_ssh_cleanup 0
  trap 'exit 129' 1
  trap 'exit 130' 2
  trap 'exit 143' 15
  # Clear inherited special bits as well as ordinary permissions. Python
  # requires an exact root-owned 0700 stage, including on a setgid /tmp.
  chmod 0700 "$stage" && chmod a-s "$stage" ||
    installer_fatal "cannot secure private Git SSH staging directory"
  stage_metadata=$(installer_metadata_value "$stage" uid_gid_mode) ||
    installer_fatal "cannot inspect private Git SSH staging directory"
  # A setgid parent may contribute a non-root group; 0700 excludes that group.
  case "$stage_metadata" in
    0:*:700) ;;
    *) installer_fatal "private Git SSH staging directory must be root-owned mode 0700" ;;
  esac
  # Fetch and verify ALL inputs before mounting or executing anything in the
  # target. Explicit guards are essential: callers use this function in ||
  # lists, where POSIX shells ignore errexit even after a local set -e.
  for ssh_install_asset in ssh-install.py ssh-install-askpass clone.conf.tmpl; do
    ssh_install_source=$(installer_repo_join_var DIR_SCRIPTS_LATE "ssh/$ssh_install_asset") ||
      installer_fatal "cannot resolve private SSH asset: $ssh_install_asset"
    (fetch_hook_file "$ssh_install_source" "$stage/$ssh_install_asset") ||
      installer_fatal "cannot fetch private SSH asset: $ssh_install_asset"
    [ -f "$stage/$ssh_install_asset" ] && [ -s "$stage/$ssh_install_asset" ] &&
      [ ! -L "$stage/$ssh_install_asset" ] ||
      installer_fatal "missing or unsafe private SSH asset: $ssh_install_asset"
    case "$ssh_install_asset" in *.tmpl) ssh_install_mode=0600 ;; *) ssh_install_mode=0700 ;; esac
    chmod "$ssh_install_mode" "$stage/$ssh_install_asset" ||
      installer_fatal "cannot secure private SSH asset: $ssh_install_asset"
  done
  install -m 0600 /git_ed25519 "$stage/private" &&
    install -m 0600 /git_ed25519.pub "$stage/public" ||
    installer_fatal "cannot stage the private initrd Git SSH identity"
  secret=$(preseed_env_read_value git_ssh_passphrase) ||
    installer_fatal "PRESEED_GIT_SSH_PASSPHRASE is required in the private initrd"
  case "$secret" in ''|*[![:print:]]*) installer_fatal "Git SSH passphrase must be nonempty printable single-line text" ;; esac
  [ "${#secret}" -le 4096 ] || installer_fatal "Git SSH passphrase exceeds size limit"
  # in-target normally manages these mounts, but its debconf/logging bridge is
  # deliberately bypassed for the private stdin pipe. Mount only missing paths
  # and remove only mounts owned by this action; preserve installer mounts.
  for mount_dir in proc dev; do
    [ ! -L "${target}/${mount_dir}" ] || installer_fatal "unsafe target runtime mountpoint"
    install -d -m 0755 "${target}/${mount_dir}" ||
      installer_fatal "cannot prepare target runtime mountpoint"
  done
  if ! installer_mounts_has_mountpoint "${target}/proc" /proc/mounts; then
    mount -t proc proc "${target}/proc" || installer_fatal "cannot mount target proc for private askpass"
    own_proc=1
  fi
  if ! installer_mounts_has_mountpoint "${target}/dev" /proc/mounts; then
    mount --bind /dev "${target}/dev" || installer_fatal "cannot bind target devices for SSH/GPG"
    own_dev=1
  fi
  # These files are encrypted key material only. The passphrase goes through
  # stdin, then a sealed Linux memfd used by SSH_ASKPASS, never a disk file.
  printf '%s' "$secret" | chroot "$target" /usr/bin/env -i \
    HOME=/root USER=root LOGNAME=root PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C.UTF-8 \
    /usr/bin/python3 -I -B "${stage#"$target"}/ssh-install.py" \
    "$action" "$ACCOUNT_USERNAME" "${stage#"$target"}" "$@"
)

provision_target_git_ssh_identity() {
  xssh_helpers_role_selected || return 0
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/ssh/git_known_hosts)" /etc/ssh/git_known_hosts 0644
  managed_git_ssh_target_action provision || installer_fatal "managed Git SSH identity provisioning failed"
}
