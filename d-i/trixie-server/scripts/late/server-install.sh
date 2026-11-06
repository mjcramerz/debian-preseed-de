#!/bin/sh
set -eu
umask 077

source_dir=${1:-}
target=${2:-/target}
[ -n "$source_dir" ] && [ -d "$source_dir" ] && [ ! -L "$source_dir" ] || {
  printf '%s\n' 'fatal: server source directory is unavailable' >&2; exit 1;
}
[ -d "$target" ] && [ ! -L "$target" ] || {
  printf '%s\n' 'fatal: installer target is unavailable' >&2; exit 1;
}
# shellcheck disable=SC1090
. "$source_dir/scripts/common/validate.sh"
# shellcheck disable=SC1090
. "$source_dir/scripts/common/credentials.sh"
# shellcheck disable=SC1090
. "$source_dir/repo.env"

classes=$(server_cmdline_value classes 2>/dev/null || true)
if [ -z "$classes" ]; then
  # shellcheck disable=SC1090
  . "$source_dir/repo.env"
  classes=$DEBIAN_DEFAULT_CLASSES
fi
profile=$(server_profile_from_classes "$classes" 2>/dev/null || true)
profile=${profile:-btrfs-srv-flex}
case "$profile" in
  btrfs-srv-flex|btrfs-srv-flex-duo|f2fs-srv-hp14) ;;
  *) server_fatal 'unknown server profile'; exit 1 ;;
esac

# shellcheck disable=SC1090
. "$source_dir/hosts/profiles/shared-srv.env"
# shellcheck disable=SC1090
. "$source_dir/hosts/installer/identity.env"
# shellcheck disable=SC1090
. "$source_dir/hosts/profiles/$profile.env"
# shellcheck disable=SC1090
. "$source_dir/hosts/installer/account.env"
# shellcheck disable=SC1090

primary_user=$(server_credential_read primary_user) || {
  server_fatal 'PRESEED_PRIMARY_USERNAME is required'; exit 1;
}
server_valid_username "$primary_user" || { server_fatal 'primary username is invalid'; exit 1; }
server_valid_username "${SSH_SERVER_USER_ALLOW:-}" || { server_fatal 'SSH_SERVER_USER_ALLOW is invalid'; exit 1; }
[ "$SSH_SERVER_USER_ALLOW" = "$primary_user" ] || { server_fatal 'SSH_SERVER_USER_ALLOW must match the provisioned account username'; exit 1; }
server_valid_port "${SERVER_SSH_PORT:-}" || { server_fatal 'server SSH port is invalid'; exit 1; }

install_asset() {
  relative=$1
  destination=$2
  mode=$3
  source_path="$source_dir/$relative"
  target_path="$target/$destination"
  [ -f "$source_path" ] && [ ! -L "$source_path" ] || {
    server_fatal "missing target asset: $relative"; return 1;
  }
  parent=${target_path%/*}
  [ -n "$parent" ] || parent=/
  mkdir -p "$parent"
  temporary=$(mktemp "$parent/.stage.XXXXXX")
  trap 'rm -f "$temporary"' EXIT HUP INT TERM
  cp "$source_path" "$temporary"
  chmod "$mode" "$temporary"
  mv -f "$temporary" "$target_path"
  trap - EXIT HUP INT TERM
}

install_asset hooks/target/etc/nftables.d/90-policy.nft etc/nftables.d/90-policy.nft 0644
install_asset hooks/target/etc/sysctl.d/90-policy.conf etc/sysctl.d/90-policy.conf 0644
install_asset hooks/target/etc/systemd/system/network-policy.service etc/systemd/system/network-policy.service 0644
install_asset hooks/target/etc/systemd/system/scx.service.d/50-sched-ext.conf etc/systemd/system/scx.service.d/50-sched-ext.conf 0644
install_asset hooks/target/etc/systemd/system/scx_loader.service.d/50-sched-ext.conf etc/systemd/system/scx_loader.service.d/50-sched-ext.conf 0644
install_asset hooks/target/etc/systemd/system-preset/90-policy.preset etc/systemd/system-preset/90-policy.preset 0644
install_asset hooks/target/etc/sysusers.d/90-policy.conf etc/sysusers.d/90-policy.conf 0644
install_asset hooks/target/etc/tmpfiles.d/90-policy.conf etc/tmpfiles.d/90-policy.conf 0644
install_asset "$SSHD_CONFIG_SOURCE" etc/ssh/sshd_config 0644
install_asset "$SSH_USER_CONFIG_SOURCE" etc/skel-bare/.ssh/config 0644
install_asset hooks/target/usr/local/libexec/codex usr/local/libexec/codex-app 0755
install_asset hooks/target/usr/local/libexec/network-policy usr/local/libexec/network-policy 0755

for shell_name in .profile .bash_profile .bashrc; do
  install_asset "hooks/target/etc/skel-bare/$shell_name" "etc/skel-bare/$shell_name" 0644
  install_asset "hooks/target/etc/skel-bare/$shell_name" "etc/skel/$shell_name" 0644
done
install_asset hooks/target/etc/skel-bare/.profile.d/71-devops-srv.sh \
  etc/skel-bare/.profile.d/71-devops-srv.sh 0644
install_asset hooks/target/etc/skel-bare/.profile.d/71-devops-srv.sh \
  etc/skel/.profile.d/71-devops-srv.sh 0644
install -d -m 0755 "$target/home/$primary_user/.profile.d"
install_asset hooks/target/etc/skel-bare/.profile.d/71-devops-srv.sh \
  "home/$primary_user/.profile.d/71-devops-srv.sh" 0644

install -d -m 0750 "$target/etc/system-config"
server_render_template "$source_dir/hooks/target/etc/system-config/profile.env.tmpl" \
  "$target/etc/system-config/profile.env" 0640 \
  PROFILE "$profile" FILESYSTEM "${SERVER_FILESYSTEM:-btrfs}" HOSTNAME "${SERVER_HOSTNAME:-srv}" \
  DOMAIN "${SYSTEM_DOMAIN:-${SERVER_DOMAIN:-lan.icramer.com}}" TIMEZONE "${SERVER_TIMEZONE:-Europe/Stockholm}" \
  SSH_PORT "$SERVER_SSH_PORT" SSH_CIDR_ALLOW "${SERVER_SSH_CIDR_ALLOW:-192.168.50.0/24}" \
  SSH_USER "$SSH_SERVER_USER_ALLOW"

ssh_source="$source_dir/hooks/target/etc/ssh/sshd_config.d/90-policy.conf"
server_render_template "$ssh_source" "$target/etc/ssh/sshd_config.d/90-policy.conf" 0644 \
  SSH_PORT "$SERVER_SSH_PORT" SSH_USER "$SSH_SERVER_USER_ALLOW"

authorized_key_file="$source_dir/$SSH_PUBLIC_KEY_SOURCE"
[ -f "$authorized_key_file" ] && [ ! -L "$authorized_key_file" ] || {
  server_fatal 'the managed LAN SSH public key is unavailable'; exit 1;
}
[ "$(wc -c <"$authorized_key_file")" -le "$SSH_PUBLIC_KEY_MAX_BYTES" ] || {
  server_fatal 'the managed LAN SSH public key exceeds its configured size limit'; exit 1;
}
[ "$(wc -c <"$source_dir/$SSH_USER_CONFIG_SOURCE")" -le "$SSH_CONFIG_MAX_BYTES" ] || {
  server_fatal 'the managed SSH client configuration exceeds its configured size limit'; exit 1;
}
authorized_key=$(sed -n '1{s/[[:space:]]*$//;p;q;}' "$authorized_key_file")
set -- $authorized_key
[ "$#" -ge 2 ] && [ "$1" = ssh-ed25519 ] || {
  server_fatal 'the managed LAN SSH public key is not an ssh-ed25519 key'; exit 1;
}
case "$2" in
  *[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=]*)
    server_fatal 'the managed LAN SSH public key is malformed'; exit 1 ;;
esac
home="$target/home/$primary_user"
install -d -m 0700 "$home/.ssh"
printf '%s\n' "$authorized_key" >"$home/.ssh/authorized_keys"
chmod 0600 "$home/.ssh/authorized_keys"
if command -v chroot >/dev/null 2>&1 && [ -x "$target/usr/bin/id" ]; then
  chroot "$target" /usr/bin/chown -R "$primary_user:$primary_user" "/home/$primary_user/.ssh"
fi

install_asset hooks/target/etc/nftables.conf etc/nftables.conf 0644
install_asset hooks/target/etc/apt/preferences.d/99-policy etc/apt/preferences.d/99-policy 0644

if command -v systemctl >/dev/null 2>&1; then
  systemctl --root="$target" daemon-reload
  systemctl --root="$target" enable network-policy.service
  systemctl --root="$target" enable ssh.socket
fi

server_info "staged server profile ${profile} for ${primary_user}"
