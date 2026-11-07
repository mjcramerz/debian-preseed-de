#!/bin/sh
set -eu
umask 077

source_dir=${1:-/tmp/server-install}
target=${2:-/target}
[ -d "$target" ] && [ ! -L "$target" ] || { printf '%s\n' 'fatal: target root is unavailable' >&2; exit 1; }
. "$source_dir/repo.env"
. "$source_dir/$DIR_HOSTS_INSTALLER/runtime.env"
fstab="$target/etc/fstab"
[ -f "$fstab" ] && [ ! -L "$fstab" ] || { printf '%s\n' 'fatal: partman did not produce fstab' >&2; exit 1; }

temporary=$(mktemp "${fstab}.srv.XXXXXX")
trap 'rm -f "$temporary"' EXIT HUP INT TERM
awk 'BEGIN { print "# BEGIN debian-preseed-de srv mounts" }
     { print }
     END { print "# END debian-preseed-de srv mounts" }' "$fstab" >"$temporary"

append_btrfs_subvolume() {
  label=$1
  mountpoint=$2
  subvolume=$3
  grep -Fq " $mountpoint " "$temporary" && return 0
  uuid=$(blkid -L "$label" 2>/dev/null || true)
  [ -n "$uuid" ] || return 0
  case "$uuid" in UUID=*) source=$uuid ;; *) source="UUID=$uuid" ;; esac
  printf '%s %s btrfs rw,relatime,lazytime,compress=zstd:1,space_cache=v2,nodiscard,subvol=%s 0 2\n' \
    "$source" "$mountpoint" "$subvolume" >>"$temporary"
}

filesystem=btrfs
if [ -r "$target/etc/system-config/profile.env" ]; then
  recipe=$(awk -F= '$1 == "PARTMAN_RECIPE_NAME" {print $2; found=1} END {if (!found) exit 1}' "$target/etc/system-config/profile.env") || recipe=
  case "$recipe" in
    f2fs-*) filesystem=f2fs ;;
    btrfs-*) filesystem=btrfs ;;
  esac
fi
if [ "$filesystem" = btrfs ]; then
  append_btrfs_subvolume ROOT /home @home
  append_btrfs_subvolume ROOT /srv @srv
  append_btrfs_subvolume ROOT /var/lib @var_lib
  append_btrfs_subvolume ROOT /var/log @var_log
fi

chmod 0644 "$temporary"
mv -f "$temporary" "$fstab"
trap - EXIT HUP INT TERM
