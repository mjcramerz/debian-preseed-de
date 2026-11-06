#!/bin/sh
set -eu
umask 077

source_dir=${1:-}
target=${2:-/target}
profile=${3:-btrfs-srv-flex}
[ -d "$source_dir" ] && [ -d "$target" ] || { printf '%s\n' 'fatal: boot stage paths are unavailable' >&2; exit 1; }
# shellcheck disable=SC1090
. "$source_dir/scripts/common/forky.sh"
# shellcheck disable=SC1090
. "$source_dir/scripts/common/validate.sh"
# shellcheck disable=SC1090
. "$source_dir/hosts/profiles/shared-srv.env"
# shellcheck disable=SC1090
. "$source_dir/hosts/profiles/$profile.env"

forky_base=$(server_forky_source_base "$source_dir") || exit 1
stage=$(mktemp -d /tmp/server-grub.XXXXXX)
trap 'rm -rf "$stage"' EXIT HUP INT TERM
fetch() {
  relative=$1
  destination="$stage/${relative##*/}"
  server_forky_fetch "$forky_base" "hooks/target/$relative" "$destination" 0600
  printf '%s\n' "$destination"
}
grub_profiles=$(fetch etc/default/grub-profiles.tmpl)
bootprofiles=$(fetch etc/default/grub.d/05-bootprofiles.cfg.tmpl)
rootfs=$(fetch etc/default/grub.d/10-rootfs.cfg.tmpl)
initramfs=$(fetch etc/default/grub.d/15-initramfs.cfg.tmpl)
systemd_mask=$(fetch etc/default/grub.d/25-systemd-mask.cfg.tmpl)
cgroup=$(fetch etc/default/grub.d/30-cgroup.cfg.tmpl)
security=$(fetch etc/default/grub.d/35-security-core.cfg.tmpl)
memory=$(fetch etc/default/grub.d/45-memory-core.cfg.tmpl)
hardening=$(fetch etc/default/grub.d/60-hardening.cfg.tmpl)

render() {
  template=$1
  destination=$2
  shift 2
  server_forky_render "$template" "$destination" 0644 "$@"
}

install -d -m 0755 "$target/etc/default/grub.d" "$target/etc/default"
render "$bootprofiles" "$target/etc/default/grub.d/05-bootprofiles.cfg" \
  GRUB_DEFAULT_ENTRY "$GRUB_DEFAULT_ENTRY"
render "$rootfs" "$target/etc/default/grub.d/10-rootfs.cfg" \
  GRUB_ROOT_FLAGS "rootfstype=${SERVER_FILESYSTEM:-btrfs}"
render "$initramfs" "$target/etc/default/grub.d/15-initramfs.cfg" \
  GRUB_INITRAMFS_FLAGS "$GRUB_INITRAMFS_FLAGS"
render "$systemd_mask" "$target/etc/default/grub.d/25-systemd-mask.cfg" \
  GRUB_SYSTEMD_MASK_FLAGS "$GRUB_SYSTEMD_MASK_FLAGS"
render "$cgroup" "$target/etc/default/grub.d/30-cgroup.cfg" GRUB_CGROUP_FLAGS "$GRUB_CGROUP_FLAGS"
render "$security" "$target/etc/default/grub.d/35-security-core.cfg" \
  GRUB_SECURITY_CORE_FLAGS "$GRUB_SECURITY_CORE_FLAGS"
render "$memory" "$target/etc/default/grub.d/45-memory-core.cfg" \
  GRUB_MEMORY_CORE_FLAGS "$GRUB_MEMORY_CORE_FLAGS"
render "$hardening" "$target/etc/default/grub.d/60-hardening.cfg" \
  GRUB_HARDENING_FLAGS "$GRUB_HARDENING_FLAGS"
render "$grub_profiles" "$target/etc/default/grub-profiles" \
  GRUB_CONFIG_DEV_PART_BOOT "" GRUB_CONFIG_DEV_PART_ROOT "" GRUB_CONFIG_DEV_PART_EFI "" \
  GRUB_CONFIG_BOOTPROFILE_DEFAULT "$BOOTPROFILE_DEFAULT" \
  GRUB_CONFIG_BOOTPROFILE_PERFORMANCE "$BOOTPROFILE_PERFORMANCE" \
  GRUB_CONFIG_BOOTPROFILE_HARDENED "$BOOTPROFILE_HARDENED" \
  GRUB_CONFIG_GRUB_ROOT_FLAGS "rootfstype=${SERVER_FILESYSTEM:-btrfs}" \
  GRUB_CONFIG_GRUB_INITRAMFS_FLAGS "$GRUB_INITRAMFS_FLAGS" \
  GRUB_CONFIG_GRUB_CGROUP_FLAGS "$GRUB_CGROUP_FLAGS" \
  GRUB_CONFIG_GRUB_SECURITY_CORE_FLAGS "$GRUB_SECURITY_CORE_FLAGS" \
  GRUB_CONFIG_GRUB_MEMORY_CORE_FLAGS "$GRUB_MEMORY_CORE_FLAGS" \
  GRUB_CONFIG_GRUB_HARDENING_FLAGS "$GRUB_HARDENING_FLAGS" \
  GRUB_CONFIG_GRUB_SYSTEMD_MASK_FLAGS "$GRUB_SYSTEMD_MASK_FLAGS" \
  GRUB_CONFIG_GRUB_DEFAULT_ENTRY "$GRUB_DEFAULT_ENTRY" \
  GRUB_CONFIG_GRUB_PROFILE_DEFAULT_FLAGS "$GRUB_PROFILE_DEFAULT_FLAGS" \
  GRUB_CONFIG_GRUB_PROFILE_PERFORMANCE_FLAGS "$GRUB_PROFILE_PERFORMANCE_FLAGS" \
  GRUB_CONFIG_GRUB_PROFILE_HARDENED_FLAGS "$GRUB_PROFILE_HARDENED_FLAGS" \
  GRUB_CONFIG_GRUB_GFXPAYLOAD_LINUX "${GRUB_DISPLAY_GFXPAYLOAD_LINUX:-text}" \
  GRUB_CONFIG_GRUB_NVME_FLAGS "" GRUB_CONFIG_GRUB_BLACKLIST_FLAGS "" \
  GRUB_CONFIG_GRUB_VFIO_FLAGS "" GRUB_CONFIG_GRUB_ASPM_FLAGS "" \
  GRUB_CONFIG_MOK_DER_PATH "" GRUB_CONFIG_RESCUE_USB_UUID "" \
  GRUB_CONFIG_DUALBOOT_ENABLED "false"
