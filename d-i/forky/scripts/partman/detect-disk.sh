#!/bin/sh
# Destructive selection is fail-closed. Defaults are candidate sets, never an
# implicit authorization to erase the first enumerated disk.
set -eu

log() { printf '[detect-disk] %s\n' "$*" >&2; }
fatal() { log "fatal: $*"; exit 1; }
disk_is_block() { [ -b "$1" ]; }

is_install_disk_name() {
  case "$1" in
    loop*|ram*|dm-*|md*|*boot*|*rpmb*) return 1 ;;
    nvme[0-9]*n[0-9]*|mmcblk[0-9]*) case "$1" in *p[0-9]*) return 1 ;; esac ;;
    sd*|vd*|xvd*) case "$1" in *[0-9]) return 1 ;; esac ;;
    *) return 1 ;;
  esac
  return 0
}

# Resolve partitions and device-mapper/RAID backing devices without depending on
# lsblk being present in the initrd. The depth bound also rejects corrupt cycles.
disk_uses() (
  name=$1; wanted=$2; depth=${3:-0}
  [ "$depth" -lt 16 ] || exit 0
  [ "$name" != "$wanted" ] || exit 0
  sys=$disk_sys_root/$name
  if [ -f "$sys/partition" ]; then
    parent=$(readlink -f "$sys") || exit 0
    parent=${parent%/*}; parent=${parent##*/}
    [ "$parent" != "$wanted" ] || exit 0
  fi
  for slave in "$sys/slaves/"*; do
    [ -e "$slave" ] || continue
    disk_uses "${slave##*/}" "$wanted" "$((depth + 1))" && exit 0
  done
  exit 1
)

disk_safe() (
  disk=$1
  disk_is_block "$disk" || exit 1
  name=${disk##*/}
  is_install_disk_name "$name" || exit 1
  sys=$disk_sys_root/$name
  [ -d "$sys" ] && [ ! -e "$sys/partition" ] || exit 1
  [ "$(cat "$sys/removable")" = 0 ] || { log "excluded removable disk $disk"; exit 1; }
  [ "$(cat "$sys/ro")" = 0 ] || { log "excluded read-only disk $disk"; exit 1; }
  sectors=$(cat "$sys/size")
  case "$sectors" in ''|*[!0-9]*) exit 1 ;; esac
  [ "$sectors" -gt 0 ] || exit 1
  # Linux sysfs size is ALWAYS measured in 512-byte units. Do not multiply by
  # logical_block_size: that would overestimate 4Kn disks by a factor of eight.
  case "$(cat "$sys/queue/logical_block_size")" in 512|4096) ;; *) log 'unsupported logical sector size'; exit 1 ;; esac
  while read -r source mountpoint rest; do
    case "$source" in "$disk_dev_root/"*)
      resolved=$(readlink -f "$source") || exit 1
      if disk_uses "${resolved##*/}" "$name"; then
        log "excluded mounted disk $disk (mountpoint $mountpoint)"; exit 1
      fi ;;
    esac
  done <"$disk_mounts"
  while read -r source rest; do
    case "$source" in "$disk_dev_root/"*)
      resolved=$(readlink -f "$source") || exit 1
      if disk_uses "${resolved##*/}" "$name"; then log "excluded active swap disk $disk"; exit 1; fi ;;
    esac
  done <"$disk_swaps"
  # Bootloader-selected hd-media remains protected even if /hd-media was
  # unmounted. This supplements, rather than replaces, the mounted-device test.
  set -f
  cmdline=$(cat "$disk_cmdline") || exit 1
  for arg in $cmdline; do
    case "$arg" in shared/enter_device=*|cdrom-detect/cdrom_device=*|iso-scan/device=*)
      source=${arg#*=}
      case "$source" in "$disk_dev_root/"*)
        resolved=$(readlink -f "$source") || exit 1
        if disk_uses "${resolved##*/}" "$name"; then log "excluded installer boot media $disk"; exit 1; fi ;;
      esac ;;
    esac
  done
  set +f
  # Refuse active holders on either the whole disk or any of its partitions.
  for member in "$disk_sys_root/"*; do
    [ -e "$member" ] || continue
    disk_uses "${member##*/}" "$name" || continue
    for holder in "$member/holders/"*; do
      [ ! -e "$holder" ] || { log "excluded disk with active holders $disk"; exit 1; }
    done
  done
  # A mounted multi-device Btrfs filesystem may list only one member in mounts.
  for member in "$disk_btrfs_root/"*/devices/*; do
    [ -e "$member" ] || continue
    if disk_uses "${member##*/}" "$name"; then log "excluded mounted Btrfs member $disk"; exit 1; fi
  done
)

disk_canonical() (
  resolved=$(readlink -f "$1") || exit 1
  case "$resolved" in "$disk_dev_root/"*) ;; *) exit 1 ;; esac
  leaf=${resolved#"$disk_dev_root/"}
  case "$leaf" in ''|*/*|*[!A-Za-z0-9_.-]*) exit 1 ;; esac
  disk_safe "$resolved" || exit 1
  printf '%s\n' "$resolved"
)

disk_identity() (
  disk=$(disk_canonical "$1") || exit 1
  sys=$disk_sys_root/${disk##*/}
  device_number=$(cat "$sys/dev") || exit 1
  case "$device_number" in *[!0-9:]*|:*|*:) exit 1 ;; *:*) ;; *) exit 1 ;; esac
  sectors=$(cat "$sys/size") || exit 1
  logical=$(cat "$sys/queue/logical_block_size") || exit 1
  identifiers=
  for field in wwid device/wwid device/serial; do
    [ -r "$sys/$field" ] || continue
    value=$(cat "$sys/$field") || exit 1
    identifiers="${identifiers}${field}=${value};"
  done
  # All fallible producers ran above, outside the pipeline. printf has only
  # validated arguments; sha256sum status is the status of this function.
  printf 'device=%s\nnumber=%s\nsectors512=%s\nlogical=%s\nids=%s\n' \
    "$disk" "$device_number" "$sectors" "$logical" "$identifiers" | sha256sum
)

detect_disk_main() {
  # These are not configurable environment overrides. Unit tests load the
  # functions without executing main and substitute private fixture roots.
  disk_sys_root=/sys/class/block
  disk_dev_root=/dev
  disk_mounts=/proc/mounts
  disk_swaps=/proc/swaps
  disk_cmdline=/proc/cmdline
  disk_btrfs_root=/sys/fs/btrfs
  detect_disk_select "$@"
}

detect_disk_select() {
  if [ "${1:-}" = --identity ]; then disk_identity "$2"; return; fi
  if [ -n "${DEV_INSTALL_DISK:-}" ]; then
    disk_canonical "$DEV_INSTALL_DISK" || fatal 'explicit install disk is unavailable, unsafe, mounted, or installation media'
    return 0
  fi
  pattern=${INSTALL_DISK_CANDIDATES:-}
  [ -n "$pattern" ] || fatal 'INSTALL_DISK_CANDIDATES is required'
  chosen=
  # Deliberate glob expansion of validated device candidates, not eval.
  for candidate in $pattern; do
    canonical=$(disk_canonical "$candidate") || continue
    [ "$canonical" != "$chosen" ] || continue
    [ -z "$chosen" ] || fatal "ambiguous install disks: $chosen and $canonical; provide an explicit safe device"
    chosen=$canonical
  done
  [ -n "$chosen" ] || fatal 'no safe install disk matches the selected class'
  log "selected $chosen"
  printf '%s\n' "$chosen"
}

detect_disk_main "$@"
