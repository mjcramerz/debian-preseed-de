#!/bin/sh

hook_prepend_path_dir() {
  hook_path_dir=$1

  case ":${PATH:-}:" in
    *":${hook_path_dir}:"*) ;;
    *)
      if [ -n "${PATH:-}" ]; then
        PATH="${hook_path_dir}:$PATH"
      else
        PATH=$hook_path_dir
      fi
      ;;
  esac
}

hook_prepare_installer_path() {
  for hook_path_dir in /usr/local/sbin /usr/local/bin /sbin /usr/sbin /bin /usr/bin; do
    hook_prepend_path_dir "$hook_path_dir"
  done
  export PATH
}

hook_prepare_installer_path

hook_target_is_mounted() {
  installer_mounts_has_mountpoint /target /proc/mounts
}

hook_persist_log() {
  log_path=$1
  target_log_file=$2

  installer_persist_log_file "$log_path" "$target_log_file"
}

hook_ensure_installer_command() {
  cmd=$1
  udeb=$2

  hook_prepare_installer_path
  command -v "$cmd" >/dev/null 2>&1 && return 0
  command -v anna-install >/dev/null 2>&1 || {
    installer_fatal "anna-install is unavailable while preparing installer tool ${cmd} from ${udeb}"
  }
  installer_info "installing installer udeb ${udeb} to provide ${cmd}"
  anna-install "$udeb" >/dev/null 2>&1 || {
    installer_fatal "anna-install ${udeb} failed while preparing ${cmd}"
  }
  command -v "$cmd" >/dev/null 2>&1 || {
    installer_fatal "required installer tool ${cmd} is still unavailable after anna-install ${udeb}"
  }
}

hook_ensure_installer_udeb() {
  udeb=$1

  command -v anna-install >/dev/null 2>&1 || {
    installer_fatal "anna-install is unavailable while preparing installer udeb ${udeb}"
  }
  installer_info "installing installer udeb ${udeb}"
  anna-install "$udeb" >/dev/null 2>&1 || {
    installer_fatal "anna-install ${udeb} failed while preparing installer runtime"
  }
}

hook_anna_install_optional() {
  udeb=$1

  command -v anna-install >/dev/null 2>&1 || return 1
  anna-install "$udeb" >/dev/null 2>&1
}

hook_preload_installer_udeb() {
  udeb=$1

  command -v anna-install >/dev/null 2>&1 || {
    installer_warn "anna-install is unavailable while preloading installer udeb ${udeb}"
    return 1
  }
  installer_info "preloading installer udeb ${udeb}"
  anna-install "$udeb" >/dev/null 2>&1 || {
    installer_warn "anna-install ${udeb} failed during optional preload"
    return 1
  }
}

hook_preload_installer_command() {
  cmd=$1
  udeb=$2

  hook_prepare_installer_path
  command -v "$cmd" >/dev/null 2>&1 && return 0
  command -v anna-install >/dev/null 2>&1 || {
    installer_warn "anna-install is unavailable while preloading installer tool ${cmd} from ${udeb}"
    return 1
  }
  if ! anna-install "$udeb" >/dev/null 2>&1; then
    installer_warn "anna-install ${udeb} failed while preloading ${cmd}"
    return 1
  fi
  if command -v "$cmd" >/dev/null 2>&1; then
    installer_info "preloaded installer tool ${cmd} via ${udeb}"
    return 0
  fi
  installer_warn "${cmd} is still unavailable after anna-install ${udeb}"
  return 1
}

hook_storage_probe_settle() {
  if command -v modprobe >/dev/null 2>&1; then
    for hook_storage_module in \
      nvme nvme_core \
      ahci libahci sd_mod scsi_mod \
      virtio_blk virtio_pci virtio_scsi \
      xen-blkfront \
      mmc_block
    do
      modprobe "$hook_storage_module" >/dev/null 2>&1 || true
    done
  fi
  if command -v udevadm >/dev/null 2>&1; then
    udevadm settle --timeout=5 >/dev/null 2>&1 || true
  fi
}

hook_selected_storage_class() {
  if [ -n "${INSTALLER_DISK_CLASS:-}" ]; then
    printf '%s\n' "$INSTALLER_DISK_CLASS"
    return 0
  fi
  installer_selected_class_for_purpose storage 2>/dev/null || true
}

hook_nvme_install_disk_candidates() {
  hook_candidates=${1:-}
  hook_nvme_candidates=

  case $- in
    *f*) hook_restore_glob=false ;;
    *)
      hook_restore_glob=true
      set -f
      ;;
  esac
  for hook_candidate in $hook_candidates; do
    case "$hook_candidate" in
      /dev/nvme*)
        hook_nvme_candidates="${hook_nvme_candidates:+$hook_nvme_candidates }$hook_candidate"
        ;;
    esac
  done
  if [ "$hook_restore_glob" = true ]; then
    set +f
  fi

  if [ -n "$hook_nvme_candidates" ]; then
    printf '%s\n' "$hook_nvme_candidates"
  else
    printf '%s\n' "/dev/nvme0n1 /dev/nvme*n*"
  fi
}

hook_nvme_controller_present() {
  hook_pci_root=${INSTALLER_PCI_DEVICES_ROOT:-/sys/bus/pci/devices}

  for hook_pci_path in "$hook_pci_root"/*; do
    [ -d "$hook_pci_path" ] || continue
    [ -r "$hook_pci_path/class" ] || continue
    hook_pci_class=$(cat "$hook_pci_path/class" 2>/dev/null || true)
    case "$hook_pci_class" in
      0x010802*) return 0 ;;
    esac
  done
  return 1
}

hook_detect_install_disk() {
  hook_detect_disk_helper=$1
  hook_host_profile=$2
  hook_candidates=$3

  INSTALL_DISK_CANDIDATES="$hook_candidates" DEV_INSTALL_DISK='' "$hook_detect_disk_helper" "$hook_host_profile" 2>/dev/null || true
}

hook_resolve_nvme_install_disk() {
  hook_detect_disk_helper=$1
  hook_host_profile=$2
  hook_nvme_candidates=$(hook_nvme_install_disk_candidates "${INSTALL_DISK_CANDIDATES:-}")

  for hook_attempt in 1 2 3 4 5; do
    detected_disk=$(hook_detect_install_disk "$hook_detect_disk_helper" "$hook_host_profile" "$hook_nvme_candidates")
    if [ -n "$detected_disk" ] && [ -b "$detected_disk" ]; then
      DEV_INSTALL_DISK=$detected_disk
      installer_info "auto-detected NVMe install disk ${DEV_INSTALL_DISK} for ${hook_host_profile}"
      return 0
    fi
    [ "$hook_attempt" -eq 5 ] && break
    hook_storage_probe_settle
    sleep 2
  done

  if hook_nvme_controller_present; then
    installer_fatal "selected disk class is nvme and an NVMe PCI controller is present, but no /dev/nvme* install disk is available; refusing to fall back to non-NVMe candidates"
  fi
  return 1
}

hook_preload_partition_tooling() {
  hook_preload_installer_command parted parted-udeb || true
  hook_preload_installer_udeb fdisk-udeb || true
  hook_preload_installer_command sfdisk fdisk-udeb || true
  hook_preload_installer_command blkid util-linux-udeb || true
}

hook_ensure_partition_tooling() {
  hook_ensure_installer_command parted parted-udeb
  hook_preload_installer_udeb fdisk-udeb || true
  hook_ensure_installer_command sfdisk fdisk-udeb
  hook_preload_installer_command blkid util-linux-udeb || true
}

hook_resolve_install_disk() {
  detect_disk_helper=$1
  host_profile=$2
  explicit_install_disk=${DEV_INSTALL_DISK:-}

  installer_resolve_install_target_defaults
  if [ -n "$explicit_install_disk" ] && [ -b "$explicit_install_disk" ]; then
    DEV_INSTALL_DISK=$explicit_install_disk
  else
    hook_storage_probe_settle
    storage_class=$(hook_selected_storage_class)
    if [ "$storage_class" = nvme ]; then
      hook_resolve_nvme_install_disk "$detect_disk_helper" "$host_profile" || true
    fi
  fi

  if [ -z "${DEV_INSTALL_DISK:-}" ] || [ ! -b "${DEV_INSTALL_DISK}" ]; then
    detected_disk=$(hook_detect_install_disk "$detect_disk_helper" "$host_profile" "${INSTALL_DISK_CANDIDATES:-}")
    if [ -n "$detected_disk" ] && [ -b "$detected_disk" ]; then
      DEV_INSTALL_DISK=$detected_disk
      installer_info "auto-detected install disk ${DEV_INSTALL_DISK} for ${host_profile}"
    fi
  fi
  [ -n "${DEV_INSTALL_DISK:-}" ] || installer_fatal "DEV_INSTALL_DISK must be set by the selected host policy env"
  installer_info "using install disk ${DEV_INSTALL_DISK}"
}
