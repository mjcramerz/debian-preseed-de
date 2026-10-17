#!/bin/sh

partman_early_require_command() {
  command -v "$1" >/dev/null 2>&1 || installer_fatal "required command is unavailable: $1"
}

PARTMAN_EARLY_WIPEFS_WARNED=${PARTMAN_EARLY_WIPEFS_WARNED:-false}

partman_early_assert_selected_disk() (
  "${TMP_ENV_DIR:?TMP_ENV_DIR must be set}/detect-disk.sh" --verify-identity \
    "${DEV_INSTALL_DISK:?DEV_INSTALL_DISK must be set}" \
    "${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}/state/selected-disk.identity" \
    "${1:-$DEV_INSTALL_DISK}" || {
      installer_fatal 'selected physical disk identity changed before storage mutation'
      return 1
    }
)

partman_early_clear_signatures() {
  dev=$1

  if command -v wipefs >/dev/null 2>&1; then
    partman_early_assert_selected_disk "$dev" || return 1
    wipefs -a -f "$dev" || {
      installer_fatal "failed to clear storage signatures from ${dev}"
      return 1
    }
    return 0
  fi

  if [ "$PARTMAN_EARLY_WIPEFS_WARNED" != true ]; then
    installer_warn "wipefs is not shipped in the Debian Installer udebs; continuing with validated partition deletion and GPT reinitialization"
    PARTMAN_EARLY_WIPEFS_WARNED=true
  fi
}

partman_early_settle_block_devices() {
  disk=${1:-${DEV_DISK_BLOCK:-}}

  [ -n "$disk" ] || installer_fatal "partman_early_settle_block_devices requires a disk path"
  if command -v partprobe >/dev/null 2>&1; then
    partprobe "$disk" || installer_warn "partprobe failed for ${disk}"
  fi
  if command -v udevadm >/dev/null 2>&1; then
    udevadm settle || installer_warn "udevadm settle failed for ${disk}"
  fi
}

partman_early_log_partition_state() {
  label=$1
  disk=${2:-${DEV_DISK_BLOCK:-}}

  [ -n "$disk" ] || installer_fatal "partman_early_log_partition_state requires a disk path"
  installer_info "${label}: sfdisk --json ${disk}"
  sfdisk --json "$disk" 2>/dev/null || installer_warn "sfdisk --json failed during ${label} for ${disk}"
  installer_info "${label}: parted -sm ${disk} unit MiB print free"
  parted -sm "$disk" unit MiB print free 2>/dev/null || installer_warn "parted print free failed during ${label} for ${disk}"
}

partman_early_reinitialize_gpt_disk() {
  disk=${1:-${DEV_DISK_BLOCK:-}}

  [ -n "$disk" ] || installer_fatal "partman_early_reinitialize_gpt_disk requires a disk path"
  installer_info "reinitializing GPT label on ${disk} using sfdisk + parted"
  partman_early_assert_selected_disk "$disk" || return 1
  sfdisk --delete "$disk" >/dev/null 2>&1 || true
  partman_early_assert_selected_disk "$disk" || return 1
  parted -s "$disk" mklabel gpt || installer_fatal "failed to create GPT label on ${disk} with parted"
  partman_early_settle_block_devices "$disk"
  partman_early_log_partition_state "after-gpt-label" "$disk"
}

partman_early_sanitize_install_disk() {
  disk=${1:-${DEV_DISK_BLOCK:-}}

  [ -n "$disk" ] || installer_fatal "partman_early_sanitize_install_disk requires a disk path"
  case "$disk" in
    /dev/*) ;;
    *) installer_fatal "install disk must be an absolute /dev path: ${disk}" ;;
  esac
  [ -b "$disk" ] || installer_fatal "install disk is not a block device: ${disk}"

  disk_discarded=false
  if command -v blkdiscard >/dev/null 2>&1; then
    partman_early_assert_selected_disk "$disk" || return 1
    if blkdiscard -f "$disk" >/dev/null 2>&1; then
      disk_discarded=true
    else
      installer_warn "blkdiscard failed for ${disk}; continuing with partition metadata cleanup"
    fi
  fi

  if [ "$disk_discarded" != true ]; then
    # Enumerate only actual children of this disk. A /dev/sda* glob can also
    # match an unrelated /dev/sdaa disk and its partitions.
    for partition_sys in "/sys/class/block/${disk##*/}/"*; do
      [ -f "$partition_sys/partition" ] || continue
      dev="/dev/${partition_sys##*/}"
      [ -b "$dev" ] || continue
      partman_early_clear_signatures "$dev"
    done
    partman_early_clear_signatures "$disk"
  fi

  partman_early_reinitialize_gpt_disk "$disk"
}
