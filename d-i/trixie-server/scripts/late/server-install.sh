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
. "$source_dir/scripts/common/forky.sh"
# shellcheck disable=SC1090
. "$source_dir/repo.env"
. "$source_dir/$DIR_HOSTS_INSTALLER/runtime.env"

classes=$(server_cmdline_value classes 2>/dev/null || true)
if [ -z "$classes" ]; then
  # shellcheck disable=SC1090
  . "$source_dir/repo.env"
  classes=$DEBIAN_DEFAULT_CLASSES
fi
classes=$(printf '%s\n' "$classes" | tr ';' ',')
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
server_forky_identity_load "$source_dir"

primary_user=$(server_credential_read primary_user) || {
  server_fatal 'PRESEED_PRIMARY_USERNAME is required'; exit 1;
}
server_valid_username "$primary_user" || { server_fatal 'primary username is invalid'; exit 1; }
server_valid_username "${SSH_SERVER_USER_ALLOW:-}" || { server_fatal 'SSH_SERVER_USER_ALLOW is invalid'; exit 1; }
[ "$SSH_SERVER_USER_ALLOW" = "$primary_user" ] || { server_fatal 'SSH_SERVER_USER_ALLOW must match the provisioned account username'; exit 1; }
server_valid_port "${SERVER_SSH_PORT:-}" || { server_fatal 'server SSH port is invalid'; exit 1; }
hostname=$SYSTEM_HOSTNAME

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

install_asset "$DIR_HOOKS_TARGET/etc/nftables.d/90-policy.nft" etc/nftables.d/90-policy.nft 0644
install_asset "$DIR_HOOKS_TARGET/etc/sysctl.d/90-policy.conf" etc/sysctl.d/90-policy.conf 0644
install_asset "$DIR_HOOKS_TARGET/etc/systemd/system/network-policy.service" etc/systemd/system/network-policy.service 0644
install_asset "$DIR_HOOKS_TARGET/etc/systemd/system-preset/90-policy.preset" etc/systemd/system-preset/90-policy.preset 0644
install_asset "$DIR_HOOKS_TARGET/etc/sysusers.d/90-policy.conf" etc/sysusers.d/90-policy.conf 0644
install_asset "$DIR_HOOKS_TARGET/etc/tmpfiles.d/90-policy.conf" etc/tmpfiles.d/90-policy.conf 0644
install_asset "$SSHD_CONFIG_SOURCE" etc/ssh/sshd_config 0644
install_asset "$SSH_USER_CONFIG_SOURCE" etc/skel-bare/.ssh/config 0644
install_asset "$DIR_HOOKS_TARGET/usr/local/libexec/codex" usr/local/libexec/codex-app 0755
install_asset "$DIR_HOOKS_TARGET/usr/local/libexec/network-policy" usr/local/libexec/network-policy 0755

for shell_name in .profile .bash_profile .bashrc; do
  install_asset "$DIR_HOOKS_TARGET/etc/skel-bare/$shell_name" "etc/skel-bare/$shell_name" 0644
  install_asset "$DIR_HOOKS_TARGET/etc/skel-bare/$shell_name" "etc/skel/$shell_name" 0644
done
install_asset "$DIR_HOOKS_TARGET/etc/skel-bare/.profile.d/71-devops-srv.sh" \
  etc/skel-bare/.profile.d/71-devops-srv.sh 0644
install_asset "$DIR_HOOKS_TARGET/etc/skel-bare/.profile.d/71-devops-srv.sh" \
  etc/skel/.profile.d/71-devops-srv.sh 0644
install -d -m 0755 "$target/home/$primary_user/.profile.d"
install_asset "$DIR_HOOKS_TARGET/etc/skel-bare/.profile.d/71-devops-srv.sh" \
  "home/$primary_user/.profile.d/71-devops-srv.sh" 0644

install -d -m 0750 "$target/etc/system-config"
server_render_template "$source_dir/$DIR_HOOKS_TARGET/etc/system-config/profile.env.tmpl" \
  "$target/etc/system-config/profile.env" 0640 \
  HOST_PROFILE "$profile" RECIPE "$PARTMAN_RECIPE_NAME" HOSTNAME "$hostname" \
  DOMAIN "${SYSTEM_DOMAIN:-${SERVER_DOMAIN:-lan.icramer.com}}" TIMEZONE "${SERVER_TIMEZONE:-Europe/Stockholm}" \
  SSH_PORT "$SERVER_SSH_PORT" SSH_CIDR_ALLOW "${SERVER_SSH_CIDR_ALLOW:-192.168.50.0/24}" \
  SSH_USER "$SSH_SERVER_USER_ALLOW" \
  FILEN_PRIV_ENABLE "${FILEN_CLI_PRIV_ENABLE:-false}" \
  FILEN_OFFSEC_ENABLE "${FILEN_CLI_OFFSEC_ENABLE:-false}" \
  FILEN_PRIV_SYNC_MODE "${FILEN_CLI_PRIV_SYNC_MODE:-}" \
  FILEN_OFFSEC_SYNC_MODE "${FILEN_CLI_OFFSEC_SYNC_MODE:-}"

ssh_source="$source_dir/$DIR_HOOKS_TARGET/etc/ssh/sshd_config.d/90-policy.conf"
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

install_asset "$DIR_HOOKS_TARGET/etc/nftables.conf" etc/nftables.conf 0644
install_asset "$DIR_HOOKS_TARGET/etc/apt/preferences.d/99-policy" etc/apt/preferences.d/99-policy 0644

class_selected() {
  class_name=$1
  case ",$classes," in
    *,"$class_name",*|*,"disk/$class_name",*|*,"disk:$class_name",*|*,"disk.$class_name",*) return 0 ;;
  esac
  return 1
}

install_device_asset() {
  relative=$1
  destination=$2
  mode=$3
  install_asset "$DIR_HOOKS_TARGET/$relative" "$destination" "$mode"
}

# Forky’s device policy is copied into the Trixie target tree and staged by
# this server installer. The Forky bridge remains reserved for shared logic.
for relative in \
  etc/modprobe.d/05-mei-blacklist.conf \
  etc/modprobe.d/10-net-proto-blacklist.conf \
  etc/modprobe.d/20-virtualization-blacklist.conf \
  etc/modprobe.d/30-legacy-bus-blacklist.conf \
  etc/modprobe.d/40-filesystem-blacklist.conf \
  etc/modprobe.d/50-nouveau-blacklist.conf \
  etc/modprobe.d/60-ses-blacklist.conf \
  etc/modprobe.d/70-vfio-pci.conf \
  etc/modprobe.d/71-thunderbolt.conf \
  etc/modprobe.d/72-nvme-blacklist.conf \
  etc/modprobe.d/73-nvme.conf \
  etc/modprobe.d/74-usbcore.conf \
  etc/modprobe.d/75-cfg80211.conf \
  etc/modprobe.d/76-iwlwifi.conf \
  etc/modprobe.d/77-e1000e.conf \
  etc/modprobe.d/78-snd-hda-intel.conf \
  etc/modprobe.d/80-i915.conf \
  etc/modprobe.d/81-amdgpu.conf \
  etc/modprobe.d/82-nvidia.conf \
  etc/modprobe.d/90-zram.conf; do
  install_device_asset "$relative" "$relative" 0644
done
case "${SYSTEM_HARDWARE_SPEC:-}" in
  '') ;;
  *[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-]*|*/*|*..*)
    server_fatal 'unsupported SYSTEM_HARDWARE_SPEC'; exit 1 ;;
  79-*.conf)
    install_device_asset "etc/modprobe.d/$SYSTEM_HARDWARE_SPEC" \
      "etc/modprobe.d/$SYSTEM_HARDWARE_SPEC" 0644 ;;
  *) server_fatal 'unsupported SYSTEM_HARDWARE_SPEC'; exit 1 ;;
esac

for relative in \
  etc/modules-load.d/20-bridge.conf \
  etc/modules-load.d/30-storage-memory.conf \
  etc/modules-load.d/32-tpm.conf \
  etc/modules-load.d/35-vfio.conf \
  etc/modules-load.d/37-virt-host.conf \
  etc/modules-load.d/40-zram.conf \
  etc/modules-load.d/app-veth.conf; do
  install_device_asset "$relative" "$relative" 0644
done
if class_selected tailscale; then
  install_device_asset etc/modules-load.d/50-tailscale.conf etc/modules-load.d/50-tailscale.conf 0644
fi
if [ "$profile" = f2fs-srv-hp14 ] || class_selected emmc; then
  install_device_asset etc/modules-load.d/20-emmc-storage.conf etc/modules-load.d/20-emmc-storage.conf 0644
elif class_selected vm; then
  install_device_asset etc/modules-load.d/10-btrfs.vm.conf etc/modules-load.d/10-btrfs.conf 0644
  install_device_asset etc/modules-load.d/25-kvm-guest.conf etc/modules-load.d/25-kvm-guest.conf 0644
else
  install_device_asset etc/modules-load.d/10-btrfs.nvme.conf etc/modules-load.d/10-btrfs.conf 0644
fi
if [ "$(dpkg --print-architecture 2>/dev/null || true)" = arm64 ]; then
  install_device_asset etc/modules-load.d/37-virt-host.generic-arm64.conf \
    etc/modules-load.d/37-virt-host.generic-arm64.conf 0644
fi

for relative in \
  etc/udev/rules.d/51-android-debug-bridge.rules \
  etc/udev/rules.d/52-samsung-download-mode.rules \
  etc/udev/rules.d/53-ledger-wallet.rules \
  etc/udev/rules.d/61-ch341a-programmers.rules \
  etc/udev/rules.d/71-nvidia-char-links.rules \
  etc/udev/rules.d/74-nvme-link-idle.rules \
  etc/udev/rules.d/85-wifi-regdom.rules \
  etc/udev/rules.d/90-udisks-behavior.rules \
  etc/udev/udev.conf.d/90-hardening.conf \
  etc/udisks2/mount_options.conf \
  etc/udisks2/udisks2.conf; do
  install_device_asset "$relative" "$relative" 0644
done

for relative in \
  etc/systemd/system/fstrim.service.d/override.conf \
  etc/systemd/system/fstrim.timer.d/override.conf \
  etc/systemd/system/ifup@.service.d/40-device-lifecycle.conf \
  etc/systemd/system/tmp.mount.d/override.conf \
  etc/systemd/system/dev-shm.mount.d/override.conf \
  etc/systemd/system/var-log.mount.d/override.conf \
  etc/systemd/system/var-cache.mount.d/override.conf \
  etc/systemd/system/var-lib-apt-lists.mount.d/override.conf \
  etc/systemd/system/var-lib-systemd-coredump.mount.d/override.conf \
  etc/systemd/system/data-run.mount.d/override.conf \
  etc/systemd/system/var-spool-rsyslog.mount.d/override.conf \
  etc/systemd/system/systemd-creds.socket.d/10-encrypted-only.conf \
  etc/systemd/system/nftables.service.d/override.conf \
  etc/systemd/system/wpa_supplicant.service.d/override.conf \
  etc/systemd/system/networking.service.d/20-resolved-shutdown-order.conf; do
  install_device_asset "$relative" "$relative" 0644
done

if command -v systemctl >/dev/null 2>&1; then
  systemctl --root="$target" daemon-reload
  systemctl --root="$target" enable network-policy.service
  systemctl --root="$target" enable ssh.socket
fi

server_info "staged server profile ${profile} for ${primary_user}"
