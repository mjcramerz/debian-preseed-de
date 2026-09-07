#!/bin/sh
# Shared Btrfs-family late_command implementation. This file is sourced.
# shellcheck disable=SC2034

btrfs_family_fstab_record_for_mount() {
  bffrm_fstab_file=$1
  bffrm_mount_target=$2

  [ -r "$bffrm_fstab_file" ] || return 1
  case "$bffrm_mount_target" in
    /*) ;;
    *) return 1 ;;
  esac

  awk -v target="$bffrm_mount_target" '
    /^[[:space:]]*#/ {
      next
    }
    NF >= 4 && $2 == target {
      filesystem_type = $3
      mount_options = $4
    }
    END {
      if (filesystem_type != "") {
        print filesystem_type " " mount_options
      }
    }
  ' "$bffrm_fstab_file"
}

# Select paths once; staging and initramfs rendering consume the same policy.
select_btrfs_hardware_policy() {
default_file_modprobe_snd_hda_intel=$FILE_MODPROBE_SND_HDA_INTEL
default_file_modprobe_iwlwifi=$FILE_MODPROBE_IWLWIFI
default_file_modprobe_thinkpad_acpi=$FILE_MODPROBE_THINKPAD_ACPI
default_file_modprobe_e1000e=$FILE_MODPROBE_E1000E
default_file_modprobe_vfio=$FILE_MODPROBE_VFIO
default_file_modprobe_i915=$FILE_MODPROBE_I915
default_file_modprobe_amdgpu=$FILE_MODPROBE_AMDGPU
default_file_modprobe_nvidia=$FILE_MODPROBE_NVIDIA
default_file_modprobe_thunderbolt=$FILE_MODPROBE_THUNDERBOLT
default_file_modprobe_usbcore=$FILE_MODPROBE_USBCORE
default_file_modprobe_cfg80211=$FILE_MODPROBE_CFG80211
default_file_modprobe_nvme_blacklist=$FILE_MODPROBE_NVME_BLACKLIST
default_file_modprobe_mei_blacklist=$FILE_MODPROBE_MEI_BLACKLIST
default_file_modprobe_nvme_opts=$FILE_MODPROBE_NVME_OPTS
default_file_udev_regdom_rule=$FILE_UDEV_REGDOM_RULE
default_file_modules_load_vfio=$FILE_MODULES_LOAD_VFIO
default_file_modules_load_virt_host=$FILE_MODULES_LOAD_VIRT_HOST
default_file_modules_load_kvm_guest=$FILE_MODULES_LOAD_KVM_GUEST
default_file_modules_load_bridge="${DIR_MODULES_LOAD}/20-bridge.conf"
default_file_grub_nvme_dropin="${DIR_GRUB_DEFAULT}/72-nvme-platform.cfg"
default_file_grub_pcie_power_dropin="${DIR_GRUB_DEFAULT}/73-pcie-power.cfg"
default_file_grub_mei_blacklist_dropin="${DIR_GRUB_DEFAULT}/74-intel-mei-blacklist.cfg"
default_file_grub_vfio_dropin="${DIR_GRUB_DEFAULT}/75-intel-vfio.cfg"
default_file_grub_cpu_profile_dropin="${DIR_GRUB_DEFAULT}/80-cpu-profile-flags.cfg"
default_file_grub_gpu_intel_dropin="${DIR_GRUB_DEFAULT}/85-gpu-intel.cfg"
default_file_grub_gpu_amd_dropin="${DIR_GRUB_DEFAULT}/86-gpu-amd.cfg"
default_file_grub_gpu_nvidia_dropin="${DIR_GRUB_DEFAULT}/87-gpu-nvidia.cfg"

target_enable_baremetal_intel=false
target_enable_intel_gpu=false
target_enable_amd_gpu=false
target_enable_nvidia=false
target_enable_nvme_tunables=false
target_enable_vfio=false
target_enable_virt_host=false
target_enable_kvm_guest=false
target_enable_bridge=false
INITRAMFS_PLATFORM_MODULES=
GRAPHICS_INITRAMFS_MODULES=

case "${CPU_CLASS:-}" in
  generic-arm64)
    # arm64 KVM has no vendor-specific kvm_intel/kvm_amd module.
    CPU_KVM_MODULE=""
    CPU_CRC32C_MODULE="crc32c_generic"
    ;;
  amd)
    CPU_KVM_MODULE="kvm_amd"
    CPU_CRC32C_MODULE="crc32c_generic"
    ;;
  intel)
    CPU_KVM_MODULE="kvm_intel"
    CPU_CRC32C_MODULE="crc32c_intel"
    ;;
  *)
    fatal "unsupported CPU class: ${CPU_CLASS:-unset}"
    ;;
esac

case "${HOOK_FAMILY}:${DISK_CLASS:-}" in
  btrfs:nvme)
    target_enable_nvme_tunables=true
    target_enable_virt_host=true
    target_enable_bridge=true
    if [ "${CPU_CLASS:-}" = intel ]; then
      target_enable_baremetal_intel=true
      # Restore the deployed Intel platform reservation, including early VFIO.
      target_enable_vfio=true
      INITRAMFS_PLATFORM_MODULES=$(cat <<'EOF'
intel_wmi_thunderbolt
thinkpad_acpi
EOF
)
    fi
    ;;
  btrfs:vm|vm:vm)
    target_enable_kvm_guest=true
    ;;
  vm:*)
    fatal "unsupported VM disk class: ${DISK_CLASS:-unset}"
    ;;
  *)
    fatal "unsupported Btrfs disk class: ${DISK_CLASS:-unset}"
    ;;
esac

if [ "$NVIDIA_ADDON_SELECTED" = true ] && [ "$NVIDIA_GPU_DETECTED" = true ]; then
  target_enable_nvidia=true
fi

for gpu_class in $GPU_CLASSES; do
  case "$gpu_class" in
    intel-uhd) target_enable_intel_gpu=true ;;
    amd-radeon) target_enable_amd_gpu=true ;;
    generic|'')
      ;;
    *)
      fatal "unsupported gpu class: ${gpu_class}"
      ;;
  esac
done

GRAPHICS_INITRAMFS_MODULES=$(late_command_graphics_initramfs_modules "$GPU_CLASSES" "$target_enable_nvidia")

set_optional_path FILE_MODPROBE_SND_HDA_INTEL "$target_enable_baremetal_intel" "$default_file_modprobe_snd_hda_intel"
set_optional_path FILE_MODPROBE_IWLWIFI "$target_enable_baremetal_intel" "$default_file_modprobe_iwlwifi"
set_optional_path FILE_MODPROBE_THINKPAD_ACPI "$target_enable_baremetal_intel" "$default_file_modprobe_thinkpad_acpi"
set_optional_path FILE_MODPROBE_E1000E "$target_enable_baremetal_intel" "$default_file_modprobe_e1000e"
set_optional_path FILE_MODPROBE_VFIO "$target_enable_vfio" "$default_file_modprobe_vfio"
set_optional_path FILE_MODPROBE_I915 "$target_enable_intel_gpu" "$default_file_modprobe_i915"
set_optional_path FILE_MODPROBE_AMDGPU "$target_enable_amd_gpu" "$default_file_modprobe_amdgpu"
set_optional_path FILE_MODPROBE_NVIDIA "$target_enable_nvidia" "$default_file_modprobe_nvidia"
set_optional_path FILE_MODPROBE_THUNDERBOLT "$target_enable_baremetal_intel" "$default_file_modprobe_thunderbolt"
set_optional_path FILE_MODPROBE_USBCORE "$target_enable_nvme_tunables" "$default_file_modprobe_usbcore"
set_optional_path FILE_MODPROBE_CFG80211 "$target_enable_baremetal_intel" "$default_file_modprobe_cfg80211"
set_optional_path FILE_MODPROBE_NVME_BLACKLIST "$target_enable_nvme_tunables" "$default_file_modprobe_nvme_blacklist"
set_optional_path FILE_MODPROBE_MEI_BLACKLIST "$target_enable_baremetal_intel" "$default_file_modprobe_mei_blacklist"
set_optional_path FILE_MODPROBE_NVME_OPTS "$target_enable_nvme_tunables" "$default_file_modprobe_nvme_opts"
set_optional_path FILE_UDEV_REGDOM_RULE "$target_enable_baremetal_intel" "$default_file_udev_regdom_rule"
set_optional_path FILE_MODULES_LOAD_VFIO "$target_enable_vfio" "$default_file_modules_load_vfio"
set_optional_path FILE_MODULES_LOAD_VIRT_HOST "$target_enable_virt_host" "$default_file_modules_load_virt_host"
set_optional_path FILE_MODULES_LOAD_KVM_GUEST "$target_enable_kvm_guest" "$default_file_modules_load_kvm_guest"
set_optional_path FILE_MODULES_LOAD_BRIDGE "$target_enable_bridge" "$default_file_modules_load_bridge"
set_optional_path FILE_GRUB_NVME_DROPIN "$target_enable_nvme_tunables" "$default_file_grub_nvme_dropin"
set_optional_path FILE_GRUB_PCIE_POWER_DROPIN "$target_enable_nvme_tunables" "$default_file_grub_pcie_power_dropin"
set_optional_path FILE_GRUB_MEI_BLACKLIST_DROPIN "$target_enable_baremetal_intel" "$default_file_grub_mei_blacklist_dropin"
set_optional_path FILE_GRUB_VFIO_DROPIN "$target_enable_vfio" "$default_file_grub_vfio_dropin"
set_optional_path FILE_GRUB_CPU_PROFILE_DROPIN true "$default_file_grub_cpu_profile_dropin"
set_optional_path FILE_GRUB_GPU_INTEL_DROPIN "$target_enable_intel_gpu" "$default_file_grub_gpu_intel_dropin"
set_optional_path FILE_GRUB_GPU_AMD_DROPIN "$target_enable_amd_gpu" "$default_file_grub_gpu_amd_dropin"
set_optional_path FILE_GRUB_GPU_NVIDIA_DROPIN "$target_enable_nvidia" "$default_file_grub_gpu_nvidia_dropin"

INITRAMFS_PLATFORM_MODULES=$(module_value_to_lines "${INITRAMFS_PLATFORM_MODULES:-}")
GRAPHICS_INITRAMFS_MODULES=$(module_value_to_lines "${GRAPHICS_INITRAMFS_MODULES:-}")
VFIO_INITRAMFS_MODULES=
if [ -n "${FILE_MODULES_LOAD_VFIO:-}" ]; then
  VFIO_INITRAMFS_MODULES=$(cat <<'EOF'
vfio
vfio_pci
vfio_iommu_type1
EOF
)
fi
VIRT_HOST_INITRAMFS_MODULES=
if [ -n "${FILE_MODULES_LOAD_VIRT_HOST:-}" ]; then
  VIRT_HOST_INITRAMFS_MODULES=$(cat <<EOF
kvm
${CPU_KVM_MODULE}
vhost
vhost_net
vhost_vsock
EOF
)
fi

}

run_btrfs_family_late_command() {
HOOK_FAMILY=${1:-}
requested_seed_base=${2:-}
requested_host_profile=${3:-}

case "$HOOK_FAMILY" in
  btrfs|vm) ;;
  *) fatal "unsupported Btrfs-family late_command family: ${HOOK_FAMILY:-unset}" ;;
esac

late_command_shared_init "$requested_seed_base" "$requested_host_profile" "$HOOK_FAMILY"

late_command_fetch_common_assets "$(installer_repo_join_var DIR_SCRIPTS_RUNTIME btrfs.sh)"
fetch_hook "$(installer_repo_join_var DIR_HOOKS_TARGET etc/default/grub-profiles.tmpl)" "$TMP_ENV_DIR/grub-profiles"
late_command_load_runtime_env true
late_command_load_host_env || return $?
# Architecture policy owns the required EFI placeholders and must exist before
# *any* renderer (including the unrelated runtime defaults) is called.
late_command_require_class_policy_env || return $?
install_target_runtime_defaults || return $?
install_target_wpa_supplicant_runtime_policy || return $?
installer_ensure_context_loaded "${SEED_BASE:-}"
CPU_CLASS=$(installer_selected_class_for_purpose cpu 2>/dev/null || printf '%s' "${INSTALLER_CPU_CLASS:-}")
DISK_CLASS=$(installer_selected_class_for_purpose storage 2>/dev/null || printf '%s' "${INSTALLER_DISK_CLASS:-}")
GPU_CLASSES=$(installer_selected_class_for_purpose gpu 2>/dev/null || printf '%s' "${INSTALLER_GPU_CLASS:-}")
BTRFS_SHARED_TARGET_ROOT=$(installer_repo_join_var DIR_HOOKS_TARGET)
NVIDIA_ADDON_SELECTED=false
NVIDIA_GPU_DETECTED=false
TIMESHIFT_ADDON_SELECTED=false
if installer_selected_class_reference_is_selected addon/nvidia; then
  NVIDIA_ADDON_SELECTED=true
fi
if installer_selected_class_reference_is_selected addon/nvidia-legacy; then
  NVIDIA_ADDON_SELECTED=true
fi
if installer_selected_class_reference_is_selected addon/timeshift; then
  TIMESHIFT_ADDON_SELECTED=true
fi
PODMAN_ADDON_SELECTED=$(podman_addon_selection_state)
if installer_nvidia_gpu_detected; then
  NVIDIA_GPU_DETECTED=true
fi
if [ "$NVIDIA_ADDON_SELECTED" = true ] && [ "$NVIDIA_GPU_DETECTED" != true ]; then
  warn "an NVIDIA addon was selected but no NVIDIA PCI display adapter was detected; NVIDIA target packages and modprobe config stay disabled"
fi
info "late installer context: host_profile=${INSTALLER_HOST_PROFILE:-unset} selected_groups=${INSTALLER_SELECTED_GROUPS:-unset} selected_classes=${INSTALLER_SELECTED_CLASSES:-unset} cpu=${CPU_CLASS:-unset} disk=${DISK_CLASS:-unset} gpu=${GPU_CLASSES:-none} nvidia_addon=${NVIDIA_ADDON_SELECTED} nvidia_gpu=${NVIDIA_GPU_DETECTED} timeshift_addon=${TIMESHIFT_ADDON_SELECTED} podman_addon=${PODMAN_ADDON_SELECTED}"

select_btrfs_hardware_policy

runtime_apply_ssh_from_classes

ensure_target_volatile_runtime_dirs() {
  prepare_target_volatile_dirs_for_apt
}

ensure_target_boot_mounts() {
  target_is_mounted || fatal "/target is not mounted before GRUB profile installation"

  if ! target_mount_source "/target${DIR_BOOT}" >/dev/null 2>&1 &&
    target_mount_source "/target${DIR_BOOT_EFI}" >/dev/null 2>&1; then
    info "unmounting /boot/efi before restoring /boot mount"
    if ! umount "/target${DIR_BOOT_EFI}"; then
      fatal "failed to unmount /target${DIR_BOOT_EFI} before restoring /target${DIR_BOOT}"
    fi
  fi

  ensure_target_mount "${DEV_PART_BOOT}" "/target${DIR_BOOT}" ext4 "${MNT_BOOT_OPTS}" "/boot"
  ensure_target_mount "${DEV_PART_EFI}" "/target${DIR_BOOT_EFI}" vfat "${MNT_EFI_OPTS}" "/boot/efi"
}

ensure_target_data_mounts() {
  target_is_mounted || fatal "/target is not mounted before data mount restoration"

  if ! target_mount_source "/target${DIR_DATA}" >/dev/null 2>&1 &&
    target_mount_source "/target${DIR_DATA_RUN}" >/dev/null 2>&1; then
    info "unmounting /data/run before restoring /data mount"
    if ! umount "/target${DIR_DATA_RUN}"; then
      fatal "failed to unmount /target${DIR_DATA_RUN} before restoring /target${DIR_DATA}"
    fi
  fi

  ensure_target_mount "${DEV_PART_DATA}" "/target${DIR_DATA}" xfs "${MNT_XFS_DATA_OPTS}" "/data"
}

ensure_target_volatile_backing_mounts() {
  target_is_mounted || fatal "/target is not mounted before volatile backing mount restoration"

  if tmpfs_policy_enabled TMPFS_VAR_LOG &&
    ! target_mount_source "/target${DIR_VAR_LOG}" >/dev/null 2>&1 &&
    target_mount_source "/target${DIR_VAR_LOG_JOURNAL}" >/dev/null 2>&1; then
    info "unmounting ${DIR_VAR_LOG_JOURNAL} before restoring ${DIR_VAR_LOG} backing directories"
    if ! umount "/target${DIR_VAR_LOG_JOURNAL}"; then
      fatal "failed to unmount /target${DIR_VAR_LOG_JOURNAL} before restoring /target${DIR_VAR_LOG}"
    fi
  fi

  ensure_target_data_mounts
  ensure_target_mount "${DEV_PART_VAR_LOG_JOURNAL}" "/target${DIR_VAR_LOG_JOURNAL}" ext4 "${MNT_VAR_LOG_JOURNAL_OPTS}" "${DIR_VAR_LOG_JOURNAL}"
  ensure_target_mount "${DEV_PART_VAR_TMP}" "/target${DIR_VAR_TMP}" ext4 "${MNT_VAR_TMP_OPTS}" "${DIR_VAR_TMP}"
  ensure_target_volatile_runtime_dirs
}

write_target_fstab() {
  root_src=$(device_source "${DEV_PART_ROOT}")
  home_src=$(device_source "${DEV_PART_HOME}")
  opt_src=$(device_source "${DEV_PART_OPT}")
  data_src=$(device_source "${DEV_PART_DATA}")
  pool_src=$(device_source "${DEV_PART_POOL}")
  boot_src=$(device_source "${DEV_PART_BOOT}")
  efi_src=$(device_source "${DEV_PART_EFI}")
  vtmp_src=$(device_source "${DEV_PART_VAR_TMP}")
  vjournal_src=$(device_source "${DEV_PART_VAR_LOG_JOURNAL}")

  write_target_file "/etc/fstab" 0644 <<EOF
# Generated by installer automation late_command

# Pseudo filesystems
$(fstab_entry "proc" "/proc" "proc" "defaults" 0 0)

# Boot partitions
$(fstab_entry "${boot_src}" "${DIR_BOOT}" "ext4" "${MNT_BOOT_OPTS}" 0 2)
$(fstab_entry "${efi_src}" "${DIR_BOOT_EFI}" "vfat" "${MNT_EFI_OPTS}" 0 2)

# Core system (btrfs subvolumes)
$(fstab_entry "${root_src}" "/" "btrfs" "${MNT_BTRFS_ROOT_OPTS}" 0 0)
$(fstab_entry "${root_src}" "${DIR_ROOT_HOME}" "btrfs" "${MNT_ROOT_HOME_OPTS}" 0 0)
$(fstab_entry "${root_src}" "${DIR_SRV}" "btrfs" "${MNT_SRV_OPTS}" 0 0)
$(fstab_entry "${root_src}" "${DIR_USR_LOCAL}" "btrfs" "${MNT_USR_LOCAL_OPTS}" 0 0)
$(fstab_entry "${root_src}" "${DIR_VAR_SPOOL}" "btrfs" "${MNT_VAR_SPOOL_OPTS}" 0 0)

# Home subvolumes (btrfs)
$(fstab_entry "${home_src}" "${DIR_HOME}" "btrfs" "${MNT_BTRFS_HOME_OPTS}" 0 0)
$(fstab_entry "${home_src}" "${DIR_HOME_DOCUMENTS}" "btrfs" "${MNT_HOME_DOCUMENTS_OPTS}" 0 0)
$(fstab_entry "${home_src}" "${DIR_HOME_DOWNLOADS}" "btrfs" "${MNT_HOME_DOWNLOADS_OPTS}" 0 0)
$(fstab_entry "${home_src}" "${DIR_HOME_PUBLIC}" "btrfs" "${MNT_HOME_PUBLIC_OPTS}" 0 0)
$(fstab_entry "${home_src}" "${DIR_HOME_PICTURES}" "btrfs" "${MNT_HOME_PICTURES_OPTS}" 0 0)
$(fstab_entry "${home_src}" "${DIR_HOME_WORKSPACE}" "btrfs" "${MNT_HOME_WORKSPACE_OPTS}" 0 0)
$(fstab_entry "${home_src}" "${DIR_HOME_SYNCTHING}" "btrfs" "${MNT_HOME_SYNCTHING_OPTS}" 0 0)

# Dedicated /opt
$(fstab_entry "${opt_src}" "${DIR_OPT}" "btrfs" "${MNT_OPT_OPTS}" 0 0)

# Dedicated XFS data tiers
$(fstab_entry "${data_src}" "${DIR_DATA}" "xfs" "${MNT_XFS_DATA_OPTS}" 0 0)
$(fstab_entry "${pool_src}" "${DIR_POOL}" "xfs" "${MNT_XFS_POOL_OPTS}" 0 0)

$(if tmpfs_policy_enabled TMPFS_DATA_RUN; then
    printf '%s\n' "# Data runtime tmpfs"
    fstab_entry "tmpfs" "${DIR_DATA_RUN}" "tmpfs" "${MNT_DATA_RUN_TMPFS_OPTS}" 0 0
    printf '\n'
  fi)

# Dedicated ext4 partitions
$(fstab_entry "${vtmp_src}" "${DIR_VAR_TMP}" "ext4" "${MNT_VAR_TMP_OPTS}" 0 2)

# Volatile tmpfs trees
$(if tmpfs_policy_enabled TMPFS_VAR_LOG; then
    fstab_entry "tmpfs" "${DIR_VAR_LOG}" "tmpfs" "${MNT_VAR_LOG_TMPFS_OPTS}" 0 0
  fi)
$(if tmpfs_policy_enabled TMPFS_VAR_CACHE; then
    fstab_entry "tmpfs" "${DIR_VAR_CACHE}" "tmpfs" "${MNT_VAR_CACHE_TMPFS_OPTS}" 0 0
  fi)
$(if tmpfs_policy_enabled TMPFS_VAR_LIB_APT_LISTS; then
    fstab_entry "tmpfs" "${DIR_APT_LISTS}" "tmpfs" "${MNT_APT_LISTS_TMPFS_OPTS}" 0 0
  fi)
$(if tmpfs_policy_enabled TMPFS_SYSTEMD_COREDUMP; then
    fstab_entry "tmpfs" "${DIR_SYSTEMD_COREDUMP}" "tmpfs" "${MNT_COREDUMP_TMPFS_OPTS}" 0 0
  fi)
$(fstab_entry "tmpfs" "${DIR_TMP}" "tmpfs" "${MNT_TMP_OPTS}" 0 0)
$(if tmpfs_policy_enabled TMPFS_DEV_SHM; then
    fstab_entry "tmpfs" "${DIR_DEV_SHM}" "tmpfs" "${MNT_DEV_SHM_OPTS}" 0 0
  fi)

# Persistent journal
$(fstab_entry "${vjournal_src}" "${DIR_VAR_LOG_JOURNAL}" "ext4" "${MNT_VAR_LOG_JOURNAL_OPTS}" 0 2)
EOF
  cp "/target/etc/fstab" "/target/etc/fstab.layout-cache" 2>/dev/null || true
  cp "/target/etc/fstab" "/target/etc/fstab.orig" 2>/dev/null || true
}

target_has_btrfs_filesystems() {
  if [ "${TARGET_HAS_BTRFS_FILESYSTEMS_READY:-0}" = 1 ]; then
    [ "${TARGET_HAS_BTRFS_FILESYSTEMS:-false}" = true ]
    return
  fi

  if [ -r /target/etc/fstab ]; then
    while IFS=' ' read -r fstab_source _fstab_mount fstab_type _fstab_rest || [ -n "${fstab_source:-}" ]; do
      case "$fstab_source" in
        ''|'#'*)
          continue
          ;;
      esac
      if [ "$fstab_type" = "btrfs" ]; then
        TARGET_HAS_BTRFS_FILESYSTEMS=true
        TARGET_HAS_BTRFS_FILESYSTEMS_READY=1
        return 0
      fi
    done </target/etc/fstab
  fi

  for dev in "${DEV_PART_ROOT:-}" "${DEV_PART_HOME:-}" "${DEV_PART_OPT:-}"; do
    [ -n "$dev" ] || continue
    [ -b "$dev" ] || continue
    fs_type=$(blkid -s TYPE -o value "$dev" 2>/dev/null || true)
    if [ "$fs_type" = "btrfs" ]; then
      TARGET_HAS_BTRFS_FILESYSTEMS=true
      TARGET_HAS_BTRFS_FILESYSTEMS_READY=1
      return 0
    fi
  done

  TARGET_HAS_BTRFS_FILESYSTEMS=false
  TARGET_HAS_BTRFS_FILESYSTEMS_READY=1
  return 1
}

load_target_btrfs_optional_package_state() {
  if [ "${TARGET_BTRFS_OPTIONAL_PACKAGE_STATE_LOADED:-0}" = 1 ]; then
    return 0
  fi

  require_in_target "Btrfs optional package detection"
  TARGET_HAS_BTRFSMAINTENANCE_PACKAGE=0

  target_btrfs_package_state=$(
    capture_in_target "detect target Btrfs optional packages" /bin/sh -c '
set -eu

check_payload_paths() {
  for payload_path in "$@"; do
    [ -n "$payload_path" ] || continue
    if [ -x "$payload_path" ] || [ -e "$payload_path" ]; then
      printf "1\n"
      return 0
    fi
  done

  printf "0\n"
}

printf "TARGET_HAS_BTRFSMAINTENANCE_PACKAGE=%s\n" "$(
  check_payload_paths \
    /etc/default/btrfsmaintenance \
    /usr/lib/systemd/system/btrfs-scrub.timer \
    /usr/share/btrfsmaintenance/btrfs-scrub.sh
)"
' sh
  )

  while IFS='=' read -r state_name state_value || [ -n "${state_name:-}" ]; do
    [ -n "${state_name:-}" ] || continue
    case "$state_name:$state_value" in
      TARGET_HAS_BTRFSMAINTENANCE_PACKAGE:0|TARGET_HAS_BTRFSMAINTENANCE_PACKAGE:1)
        eval "$state_name=$state_value"
        ;;
      *)
        installer_fatal "invalid target Btrfs optional package state: ${state_name}=${state_value}"
        ;;
    esac
  done <<EOF
$target_btrfs_package_state
EOF

  TARGET_BTRFS_OPTIONAL_PACKAGE_STATE_LOADED=1
}


configure_target_btrfsmaintenance() {
  if ! target_has_btrfs_filesystems; then
    info "target has no Btrfs filesystems; skipping btrfsmaintenance"
    return 0
  fi

  load_target_btrfs_optional_package_state
  if [ "${TARGET_HAS_BTRFSMAINTENANCE_PACKAGE}" != 1 ]; then
    installer_warn "btrfsmaintenance is not installed; skipping optional Btrfs maintenance timers"
    return 0
  fi
  ensure_target_volatile_runtime_dirs

  stage_target_asset "$(installer_hardware_asset_path disk "${DISK_CLASS}" "etc/default/btrfsmaintenance")" "${FILE_BTRFSMAINTENANCE_DEFAULT}" 0644
  stage_target_systemd_unit_enabled btrfs-scrub.timer system
  stage_target_systemd_unit_enabled btrfs-balance.timer system
  unstage_target_systemd_unit_enabled btrfs-trim.timer system
}

timeshift_placeholder_map() {
  timeshift_root_device=$(installer_filesystem_device "${DEV_PART_ROOT}")
  timeshift_root_uuid=$(blkid -s UUID -o value "$timeshift_root_device" 2>/dev/null || true)
  [ -n "$timeshift_root_uuid" ] || installer_fatal "unable to determine UUID for Timeshift root device ${timeshift_root_device}"
  timeshift_parent_uuid=
  if [ "${ROOT_HOME_CRYPTO_ENABLED:-false}" = true ]; then
    timeshift_parent_uuid=$(blkid -s UUID -o value "${DEV_PART_ROOT}" 2>/dev/null || true)
    [ -n "$timeshift_parent_uuid" ] ||
      installer_fatal "unable to determine UUID for encrypted Timeshift parent device ${DEV_PART_ROOT}"
  fi
  printf 'TIMESHIFT_BACKUP_DEVICE_UUID=%s\n' "$timeshift_root_uuid"
  printf 'TIMESHIFT_PARENT_DEVICE_UUID=%s\n' "$timeshift_parent_uuid"
}

configure_target_timeshift_btrfs_layout() {
  timeshift_root_device=$(installer_filesystem_device "${DEV_PART_ROOT}")
  [ -b "$timeshift_root_device" ] ||
    installer_fatal "addon/timeshift root filesystem device is unavailable: ${timeshift_root_device}"
  timeshift_root_device_fstype=$(blkid -s TYPE -o value "$timeshift_root_device" 2>/dev/null || true)
  [ "$timeshift_root_device_fstype" = btrfs ] ||
    installer_fatal "addon/timeshift requires the installed root filesystem device to be Btrfs; detected ${timeshift_root_device_fstype:-unknown} on ${timeshift_root_device}"

  timeshift_root_fstab_record=$(btrfs_family_fstab_record_for_mount /target/etc/fstab / || true)
  [ -n "$timeshift_root_fstab_record" ] ||
    installer_fatal "addon/timeshift requires a root filesystem entry in /target/etc/fstab"
  timeshift_root_fstype=${timeshift_root_fstab_record%% *}
  timeshift_root_options=${timeshift_root_fstab_record#* }
  [ "$timeshift_root_fstype" = btrfs ] ||
    installer_fatal "addon/timeshift requires the installed root fstab entry to use Btrfs; detected ${timeshift_root_fstype:-unknown}"
  case ",${timeshift_root_options}," in
    *,subvol=@,*|*,subvol=/@,*) ;;
    *)
      installer_fatal "addon/timeshift requires the target root subvolume to be @"
      ;;
  esac

  btrfs subvolume set-default 5 /target ||
    installer_fatal "failed to set the Timeshift-compatible Btrfs top-level default subvolume"
  timeshift_default_subvolume=$(btrfs subvolume get-default /target 2>/dev/null || true)
  case "$timeshift_default_subvolume" in
    "ID 5 "*) ;;
    *)
      installer_fatal "Timeshift requires Btrfs default subvolume ID 5: ${timeshift_default_subvolume:-unreadable}"
      ;;
  esac
}

btrfs_validate_shared_target_relpath() {
  shared_relpath=$1

  case "$shared_relpath" in
    ''|/*|../*|*/..|*../*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/-]*)
      installer_fatal "unsafe shared target asset path for Btrfs family staging: ${shared_relpath:-unset}"
      ;;
  esac
}

btrfs_stage_shared_target_asset() {
  shared_relpath=$1
  target_path=$2
  mode=$3

  btrfs_validate_shared_target_relpath "$shared_relpath"
  stage_target_asset "${BTRFS_SHARED_TARGET_ROOT}/${shared_relpath}" "$target_path" "$mode"
}

timeshift_managed_perl_modules() {
  cat <<'EOF'
TimeshiftManaged/CLI.pm
TimeshiftManaged/Command.pm
TimeshiftManaged/Config.pm
TimeshiftManaged/EventQueue.pm
TimeshiftManaged/GrubRefresh.pm
TimeshiftManaged/Logger.pm
TimeshiftManaged/Snapshot.pm
EOF
}

btrfs_stage_timeshift_managed_perl_modules() {
  timeshift_managed_perl_modules |
    while IFS= read -r timeshift_module; do
      [ -n "$timeshift_module" ] || continue
      btrfs_stage_shared_target_asset \
        "usr/local/lib/perl5/site_perl/timeshift-managed/${timeshift_module}" \
        "/usr/local/lib/perl5/site_perl/timeshift-managed/${timeshift_module}" \
        0644
    done
}

btrfs_render_shared_target_asset_with_placeholder_map() {
  shared_relpath=$1
  target_path=$2
  mode=$3
  map_func=$4

  btrfs_validate_shared_target_relpath "$shared_relpath"
  render_target_asset_with_placeholder_map "${BTRFS_SHARED_TARGET_ROOT}/${shared_relpath}" "$target_path" "$mode" "$map_func"
}

configure_target_timeshift() {
  if [ "$TIMESHIFT_ADDON_SELECTED" != true ]; then
    return 0
  fi
  target_has_btrfs_filesystems || fatal "addon/timeshift requires a Btrfs-root target"
  configure_target_timeshift_btrfs_layout

  btrfs_render_shared_target_asset_with_placeholder_map \
    etc/timeshift/timeshift.json.tmpl \
    "${FILE_TIMESHIFT_CONFIG}" \
    0600 \
    timeshift_placeholder_map

  btrfs_stage_shared_target_asset etc/default/grub-btrfs/config.tmpl "${FILE_GRUB_BTRFS_CONFIG}" 0644
  btrfs_stage_timeshift_managed_perl_modules
  btrfs_stage_shared_target_asset usr/local/libexec/timeshift-managed-snapshot "${FILE_TIMESHIFT_SNAPSHOT_HELPER}" 0755
  btrfs_stage_shared_target_asset usr/local/libexec/timeshift-managed/notify-send "${FILE_TIMESHIFT_NOTIFY_SHIM}" 0755
  btrfs_stage_shared_target_asset etc/timeshift/backup-hooks.d/90-grub-btrfs-refresh "${FILE_TIMESHIFT_GRUB_REFRESH_HOOK}" 0755
  btrfs_stage_shared_target_asset usr/local/libexec/grub-btrfs-refresh "${FILE_GRUB_BTRFS_REFRESH_HELPER}" 0755
  btrfs_stage_shared_target_asset etc/rsyslog.d/38-timeshift-managed.conf /etc/rsyslog.d/38-timeshift-managed.conf 0644
  btrfs_stage_shared_target_asset etc/logrotate.d/timeshift-managed /etc/logrotate.d/timeshift-managed 0644
  btrfs_stage_shared_target_asset etc/tmpfiles.d/61-timeshift-managed.conf /etc/tmpfiles.d/61-timeshift-managed.conf 0644
  btrfs_stage_shared_target_asset etc/systemd/system/timeshift-daily.service "${FILE_TIMESHIFT_DAILY_SERVICE}" 0644
  btrfs_stage_shared_target_asset etc/systemd/system/timeshift-daily.timer "${FILE_TIMESHIFT_DAILY_TIMER}" 0644
  btrfs_stage_shared_target_asset etc/systemd/system/timeshift-weekly.service "${FILE_TIMESHIFT_WEEKLY_SERVICE}" 0644
  btrfs_stage_shared_target_asset etc/systemd/system/timeshift-weekly.timer "${FILE_TIMESHIFT_WEEKLY_TIMER}" 0644
  btrfs_stage_shared_target_asset etc/systemd/system/timeshift-monthly.service "${FILE_TIMESHIFT_MONTHLY_SERVICE}" 0644
  btrfs_stage_shared_target_asset etc/systemd/system/timeshift-monthly.timer "${FILE_TIMESHIFT_MONTHLY_TIMER}" 0644
  btrfs_stage_shared_target_asset etc/systemd/system/grub-btrfs-refresh.service "${FILE_GRUB_BTRFS_REFRESH_SERVICE}" 0644
  btrfs_stage_shared_target_asset etc/systemd/system/grub-btrfs-refresh.path "${FILE_GRUB_BTRFS_REFRESH_PATH}" 0644

  for unit in \
    timeshift-daily.timer \
    timeshift-weekly.timer \
    timeshift-monthly.timer \
    grub-btrfs-refresh.path
  do
    stage_target_systemd_unit_enabled "$unit" system
  done
}

prepare_target_deferred_tmpfs_roots() {
  journal_mount="/target${DIR_VAR_LOG_JOURNAL}"

  if tmpfs_policy_enabled TMPFS_VAR_LOG &&
    target_mount_source "$journal_mount" >/dev/null 2>&1; then
    info "unmounting ${journal_mount} so the installed system remounts the persistent journal cleanly on reboot"
    umount "$journal_mount" || {
      fatal "failed to unmount ${journal_mount} while preparing deferred tmpfs roots"
    }
  fi

  rmdir "$journal_mount" 2>/dev/null || true
}

write_target_kernel_tunables() {
  stage_target_asset_if_path "$(installer_hardware_asset_path cpu "${CPU_CLASS}" "etc/modprobe.d/snd-hda-intel.conf")" "${FILE_MODPROBE_SND_HDA_INTEL:-}" "${DIR_MODPROBE_D}/snd-hda-intel.conf" 0644
  stage_target_asset_if_path "$(installer_hardware_asset_path cpu "${CPU_CLASS}" "etc/modprobe.d/iwlwifi.conf")" "${FILE_MODPROBE_IWLWIFI:-}" "${DIR_MODPROBE_D}/iwlwifi.conf" 0644
  stage_target_asset_if_path "$(installer_hardware_asset_path cpu "${CPU_CLASS}" "etc/modprobe.d/thinkpad-acpi.conf")" "${FILE_MODPROBE_THINKPAD_ACPI:-}" "${DIR_MODPROBE_D}/thinkpad-acpi.conf" 0644
  stage_target_asset_if_path "$(installer_hardware_asset_path cpu "${CPU_CLASS}" "etc/modprobe.d/e1000e.conf")" "${FILE_MODPROBE_E1000E:-}" "${DIR_MODPROBE_D}/e1000e.conf" 0644
  stage_target_asset_if_path "$(installer_hardware_asset_path cpu "${CPU_CLASS}" "etc/modprobe.d/vfio-pci.conf")" "${FILE_MODPROBE_VFIO:-}" "${DIR_MODPROBE_D}/vfio-pci.conf" 0644
  stage_target_asset_if_path "$(installer_hardware_asset_path gpu intel-uhd etc/modprobe.d/i915.conf)" "${FILE_MODPROBE_I915:-}" "${DIR_MODPROBE_D}/i915.conf" 0644
  stage_target_asset_if_path "$(installer_hardware_asset_path gpu amd-radeon etc/modprobe.d/amdgpu.conf)" "${FILE_MODPROBE_AMDGPU:-}" "${DIR_MODPROBE_D}/amdgpu.conf" 0644
  if [ "$target_enable_nvidia" = true ]; then
    stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/modprobe.d/50-nouveau-blacklist.conf)" "${DIR_MODPROBE_D}/50-nouveau-blacklist.conf" 0644
    stage_target_asset "$(installer_hardware_asset_path gpu nvidia etc/modprobe.d/nvidia.conf)" "${FILE_MODPROBE_NVIDIA}" 0644
  else
    remove_target_asset "${DIR_MODPROBE_D}/50-nouveau-blacklist.conf"
    remove_target_asset "${DIR_MODPROBE_D}/nvidia.conf"
  fi
  stage_target_asset_if_path "$(installer_hardware_asset_path cpu "${CPU_CLASS}" "etc/modprobe.d/thunderbolt.conf")" "${FILE_MODPROBE_THUNDERBOLT:-}" "${DIR_MODPROBE_D}/thunderbolt.conf" 0644
  stage_target_asset_if_path "$(installer_hardware_asset_path disk "${DISK_CLASS}" "etc/modprobe.d/usbcore.conf")" "${FILE_MODPROBE_USBCORE:-}" "${DIR_MODPROBE_D}/usbcore.conf" 0644
  stage_target_asset_if_path "$(installer_hardware_asset_path cpu "${CPU_CLASS}" "etc/modprobe.d/cfg80211.conf")" "${FILE_MODPROBE_CFG80211:-}" "${DIR_MODPROBE_D}/cfg80211.conf" 0644
  stage_target_asset_if_path "$(installer_hardware_asset_path disk "${DISK_CLASS}" "etc/modprobe.d/nvme-blacklist.conf")" "${FILE_MODPROBE_NVME_BLACKLIST:-}" "${DIR_MODPROBE_D}/nvme-blacklist.conf" 0644
  stage_target_asset_if_path "$(installer_hardware_asset_path cpu "${CPU_CLASS}" "etc/modprobe.d/05-mei-blacklist.conf")" "${FILE_MODPROBE_MEI_BLACKLIST:-}" "${DIR_MODPROBE_D}/05-mei-blacklist.conf" 0644
  stage_target_asset_if_path "$(installer_hardware_asset_path disk "${DISK_CLASS}" "etc/modprobe.d/nvme.conf")" "${FILE_MODPROBE_NVME_OPTS:-}" "${DIR_MODPROBE_D}/nvme.conf" 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/modprobe.d/20-virtualization-blacklist.conf)" "${FILE_MODPROBE_VM_BLACKLIST}" 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/modprobe.d/30-legacy-bus-blacklist.conf)" "${FILE_MODPROBE_LEGACY_BLACKLIST}" 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/modprobe.d/40-filesystem-blacklist.conf)" "${FILE_MODPROBE_FILESYSTEM_BLACKLIST}" 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/modprobe.d/60-ses-blacklist.conf)" "${FILE_MODPROBE_SES_BLACKLIST}" 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/modprobe.d/10-net-proto-blacklist.conf)" "${FILE_MODPROBE_NETPROTO_BLACKLIST}" 0644
  stage_target_asset_if_path "$(installer_hardware_asset_path cpu "${CPU_CLASS}" "etc/udev/rules.d/85-wifi-regdom.rules")" "${FILE_UDEV_REGDOM_RULE:-}" "${DIR_UDEV_RULES}/85-wifi-regdom.rules" 0644

  stage_target_asset "$(installer_hardware_asset_path disk "${DISK_CLASS}" "etc/modules-load.d/10-btrfs.conf")" "${FILE_MODULES_LOAD_BTRFS}" 0644
  stage_target_asset_if_path "$(installer_hardware_asset_path disk "${DISK_CLASS}" "etc/modules-load.d/20-bridge.conf")" "${FILE_MODULES_LOAD_BRIDGE:-}" "${DIR_MODULES_LOAD}/20-bridge.conf" 0644
  stage_target_asset_if_path "$(installer_hardware_asset_path disk "${DISK_CLASS}" "etc/modules-load.d/25-kvm-guest.conf")" "${FILE_MODULES_LOAD_KVM_GUEST:-}" "${DIR_MODULES_LOAD}/25-kvm-guest.conf" 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/modules-load.d/30-storage-memory.conf)" "${FILE_MODULES_LOAD_STORAGE_MEMORY}" 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/modules-load.d/32-tpm.conf)" "${FILE_MODULES_LOAD_TPM}" 0644
  stage_target_asset_if_path "$(installer_hardware_asset_path cpu "${CPU_CLASS}" "etc/modules-load.d/35-vfio.conf")" "${FILE_MODULES_LOAD_VFIO:-}" "${DIR_MODULES_LOAD}/35-vfio.conf" 0644
  stage_target_asset_if_path "$(installer_hardware_asset_path cpu "${CPU_CLASS}" "etc/modules-load.d/37-virt-host.conf")" "${FILE_MODULES_LOAD_VIRT_HOST:-}" "${DIR_MODULES_LOAD}/37-virt-host.conf" 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/sysctl.d/10-baseline.conf)" "${FILE_SYSCTL_BASELINE}" 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/sysctl.d/20-storage-memory.conf)" "${FILE_SYSCTL_STORAGE_MEMORY}" 0644
  render_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/sysctl.d/25-storage-static.conf.tmpl)" "${FILE_SYSCTL_FAMILY_OVERRIDE}" 0644
  render_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/sysctl.d/profiles/balanced/40-balanced.conf)" "${FILE_SYSCTL_PROFILE_DEFAULT}" 0644
  render_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/sysctl.d/profiles/hardened/40-hardened.conf)" "${FILE_SYSCTL_PROFILE_HARDENED}" 0644
  render_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/sysctl.d/profiles/performance/40-performance.conf)" "${FILE_SYSCTL_PROFILE_PERFORMANCE}" 0644

  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/initramfs-tools/conf.d/99-compress.conf)" "${FILE_INITRAMFS_CUSTOM_CONF}" 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/initramfs-tools/conf.d/resume)" "${FILE_INITRAMFS_RESUME}" 0644
  render_target_asset "$(installer_hardware_asset_path disk "${DISK_CLASS}" "etc/initramfs-tools/modules.tmpl")" "${FILE_INITRAMFS_MODULES}" 0644
  stage_target_asset_if_path "$(installer_hardware_asset_path disk "${DISK_CLASS}" "etc/default/grub.d/72-nvme-platform.cfg")" "${FILE_GRUB_NVME_DROPIN:-}" "${DIR_GRUB_DEFAULT}/72-nvme-platform.cfg" 0644
  stage_target_asset_if_path "$(installer_hardware_asset_path disk "${DISK_CLASS}" "etc/default/grub.d/73-pcie-power.cfg")" "${FILE_GRUB_PCIE_POWER_DROPIN:-}" "${DIR_GRUB_DEFAULT}/73-pcie-power.cfg" 0644
  stage_target_asset_if_path "$(installer_hardware_asset_path cpu "${CPU_CLASS}" "etc/default/grub.d/74-intel-mei-blacklist.cfg")" "${FILE_GRUB_MEI_BLACKLIST_DROPIN:-}" "${DIR_GRUB_DEFAULT}/74-intel-mei-blacklist.cfg" 0644
  stage_target_asset_if_path "$(installer_hardware_asset_path cpu "${CPU_CLASS}" "etc/default/grub.d/75-intel-vfio.cfg")" "${FILE_GRUB_VFIO_DROPIN:-}" "${DIR_GRUB_DEFAULT}/75-intel-vfio.cfg" 0644
  stage_target_asset_if_path "$(installer_hardware_asset_path cpu "${CPU_CLASS}" "etc/default/grub.d/80-cpu-profile-flags.cfg")" "${FILE_GRUB_CPU_PROFILE_DROPIN:-}" "${DIR_GRUB_DEFAULT}/80-cpu-profile-flags.cfg" 0644
  stage_target_asset_if_path "$(installer_hardware_asset_path gpu intel-uhd etc/default/grub.d/85-gpu-intel.cfg)" "${FILE_GRUB_GPU_INTEL_DROPIN:-}" "${DIR_GRUB_DEFAULT}/85-gpu-intel.cfg" 0644
  stage_target_asset_if_path "$(installer_hardware_asset_path gpu amd-radeon etc/default/grub.d/86-gpu-amd.cfg)" "${FILE_GRUB_GPU_AMD_DROPIN:-}" "${DIR_GRUB_DEFAULT}/86-gpu-amd.cfg" 0644
  stage_target_asset_if_path "$(installer_hardware_asset_path gpu nvidia etc/default/grub.d/87-gpu-nvidia.cfg)" "${FILE_GRUB_GPU_NVIDIA_DROPIN:-}" "${DIR_GRUB_DEFAULT}/87-gpu-nvidia.cfg" 0644

  configure_target_nvidia_power_management "$target_enable_nvidia"

  install_target_bootprofile_assets

  stage_target_zram_assets
  write_target_swap_fallback_config
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/libexec/swap-fallback-setup.tmpl)" "${FILE_SWAP_FALLBACK_HELPER}" 0755
  render_target_template "$TMP_ENV_DIR/swap-fallback.service.tmpl" "/target${FILE_SWAP_FALLBACK_SERVICE}" 0644

  stage_target_common_storage_maintenance_assets
}








write_target_fstab
ensure_target_boot_mounts
ensure_target_volatile_backing_mounts
ensure_target_managed_runtime_storage_roots
provision_target_identity
stage_target_docs_index
stage_target_account_shell_assets
ensure_target_account_home_ownership
install_target_account_shell_assets
install_target_account_sudoers
configure_target_shared_account_access
repair_target_pkgsel_include_packages
install_target_mullvad_vpn_if_selected
stage_target_secure_boot_runtime_assets
stage_target_xssh_helpers
provision_target_ssh_client
configure_target_rootless_podman_if_selected
sanitize_target_xfs_scrub_systemd_units
install_target_wpa_supplicant_runtime_policy
configure_target_smartmontools_defaults
ensure_target_secure_boot_packages
configure_target_btrfsmaintenance
configure_target_timeshift
provision_target_ssh_server
install_target_managed_network_handoff
configure_target_apparmor_auditd
install_target_firstboot_logger
write_target_grub_dropins
set_target_grub_default_entry
write_target_kernel_tunables
prepare_target_secure_boot_runtime
sign_target_installed_kernel_modules
dedupe_target_tmpfiles_legacy_lock
enable_target_storage_units
set_target_default_unit
disable_stock_kernel_menu

if target_exec_available; then
  # Regenerate signed kernels/initrds BEFORE discovering boot menu entries.
  repair_target_installed_kernels
  require_target_grub_installed
  install_target_grub_profiles
  if [ "$TIMESHIFT_ADDON_SELECTED" = true ]; then
    run_in_target "prime managed GRUB BTRFS snapshot menu" "${FILE_GRUB_BTRFS_REFRESH_HELPER}"
  fi
  require_target_dualboot_os_prober_package
  run_target_grub_config_update
  if reset_target_secure_boot_mok_state; then
    queue_target_grub_mok_enrollment_boot_for_reset
  fi
  sync_target_secure_boot_bundle_to_installer_usb
  close_target_secure_boot_state
fi

configure_target_dbus_broker
prepare_target_deferred_tmpfs_roots
prepare_target_volatile_mountpoints_for_first_boot
installer_archive_logs_to_target copy || true
}
