#!/bin/sh
# Shared F2FS-family late_command implementation. This file is sourced.

run_f2fs_family_late_command() {
requested_seed_base=${1:-}
requested_host_profile=${2:-}
HOOK_FAMILY=f2fs

late_command_shared_init "$requested_seed_base" "$requested_host_profile" "$HOOK_FAMILY"

late_command_fetch_common_assets "$(installer_repo_join_var DIR_SCRIPTS_RUNTIME f2fs.sh)"
fetch_hook "$(installer_repo_join_var DIR_HOOKS_TARGET etc/default/grub-profiles.tmpl)" "$TMP_ENV_DIR/grub-profiles"
late_command_load_runtime_env false
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
NVIDIA_ADDON_SELECTED=false
NVIDIA_GPU_DETECTED=false
if installer_selected_class_reference_is_selected addon/nvidia; then
  NVIDIA_ADDON_SELECTED=true
fi
if installer_selected_class_reference_is_selected addon/nvidia-legacy; then
  NVIDIA_ADDON_SELECTED=true
fi
PODMAN_ADDON_SELECTED=$(podman_addon_selection_state)
if installer_nvidia_gpu_detected; then
  NVIDIA_GPU_DETECTED=true
fi
if [ "$NVIDIA_ADDON_SELECTED" = true ] && [ "$NVIDIA_GPU_DETECTED" != true ]; then
  warn "an NVIDIA addon was selected but no NVIDIA PCI display adapter was detected; NVIDIA target packages and modprobe config stay disabled"
fi
info "late installer context: host_profile=${INSTALLER_HOST_PROFILE:-unset} selected_groups=${INSTALLER_SELECTED_GROUPS:-unset} selected_classes=${INSTALLER_SELECTED_CLASSES:-unset} cpu=${CPU_CLASS:-unset} disk=${DISK_CLASS:-unset} gpu=${GPU_CLASSES:-none} nvidia_addon=${NVIDIA_ADDON_SELECTED} nvidia_gpu=${NVIDIA_GPU_DETECTED} podman_addon=${PODMAN_ADDON_SELECTED}"

default_file_modprobe_mei_blacklist=$FILE_MODPROBE_MEI_BLACKLIST
default_file_modprobe_thinkpad_acpi=$FILE_MODPROBE_THINKPAD_ACPI
default_file_modprobe_i915=$FILE_MODPROBE_I915
default_file_modprobe_amdgpu=$FILE_MODPROBE_AMDGPU
default_file_modprobe_nvidia=$FILE_MODPROBE_NVIDIA
default_file_modprobe_usbcore=$FILE_MODPROBE_USBCORE
default_file_modprobe_cfg80211=$FILE_MODPROBE_CFG80211
default_file_modprobe_nvme_blacklist=$FILE_MODPROBE_NVME_BLACKLIST
default_file_modules_load_emmc_storage=$FILE_MODULES_LOAD_EMMC_STORAGE
default_file_grub_cpu_profile_dropin="${DIR_GRUB_DEFAULT}/80-cpu-profile-flags.cfg"
default_file_grub_gpu_intel_dropin="${DIR_GRUB_DEFAULT}/85-gpu-intel.cfg"
default_file_grub_gpu_amd_dropin="${DIR_GRUB_DEFAULT}/86-gpu-amd.cfg"
default_file_grub_gpu_nvidia_dropin="${DIR_GRUB_DEFAULT}/87-gpu-nvidia.cfg"

target_enable_intel_platform=false
target_enable_intel_gpu=false
target_enable_amd_gpu=false
target_enable_nvidia=false
target_enable_nvme_tunables=false
target_enable_emmc_storage=false

case "${CPU_CLASS:-}" in
  generic-arm64|amd) ;;
  intel)
    target_enable_intel_platform=true
    ;;
  *)
    fatal "unsupported CPU class: ${CPU_CLASS:-unset}"
    ;;
esac

case "${DISK_CLASS:-emmc}" in
  emmc)
    target_enable_emmc_storage=true
    ;;
  *)
    fatal "unsupported F2FS disk class: ${DISK_CLASS:-unset}"
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

set_optional_path FILE_MODPROBE_MEI_BLACKLIST false "$default_file_modprobe_mei_blacklist"
set_optional_path FILE_MODPROBE_THINKPAD_ACPI "$target_enable_intel_platform" "$default_file_modprobe_thinkpad_acpi"
set_optional_path FILE_MODPROBE_I915 "$target_enable_intel_gpu" "$default_file_modprobe_i915"
set_optional_path FILE_MODPROBE_AMDGPU "$target_enable_amd_gpu" "$default_file_modprobe_amdgpu"
set_optional_path FILE_MODPROBE_NVIDIA "$target_enable_nvidia" "$default_file_modprobe_nvidia"
set_optional_path FILE_MODPROBE_USBCORE "$target_enable_nvme_tunables" "$default_file_modprobe_usbcore"
set_optional_path FILE_MODPROBE_CFG80211 false "$default_file_modprobe_cfg80211"
set_optional_path FILE_MODPROBE_NVME_BLACKLIST "$target_enable_nvme_tunables" "$default_file_modprobe_nvme_blacklist"
set_optional_path FILE_MODULES_LOAD_EMMC_STORAGE "$target_enable_emmc_storage" "$default_file_modules_load_emmc_storage"
set_optional_path FILE_GRUB_CPU_PROFILE_DROPIN true "$default_file_grub_cpu_profile_dropin"
set_optional_path FILE_GRUB_GPU_INTEL_DROPIN "$target_enable_intel_gpu" "$default_file_grub_gpu_intel_dropin"
set_optional_path FILE_GRUB_GPU_AMD_DROPIN "$target_enable_amd_gpu" "$default_file_grub_gpu_amd_dropin"
set_optional_path FILE_GRUB_GPU_NVIDIA_DROPIN "$target_enable_nvidia" "$default_file_grub_gpu_nvidia_dropin"

GRAPHICS_INITRAMFS_MODULES=$(module_value_to_lines "${GRAPHICS_INITRAMFS_MODULES:-}")

runtime_apply_ssh_from_classes

write_target_fstab() {
  # Runtime layout env fragments provide the device paths and mount options used here.
  # shellcheck disable=SC2153
  root_src=$(device_source "${DEV_PART_ROOT}")
  # shellcheck disable=SC2153
  boot_src=$(device_source "${DEV_PART_BOOT}")
  efi_src=$(device_source "${DEV_PART_EFI}")
  journal_src=$(device_source "${DEV_PART_VAR_LOG_JOURNAL}")

  {
    printf '# Generated by installer automation late_command\n\n'
    printf '# Pseudo filesystems\n'
    fstab_entry proc /proc proc defaults 0 0
    printf '\n# Boot partitions\n'
    # shellcheck disable=SC2153
    fstab_entry "$boot_src" "$DIR_BOOT" ext4 "$MNT_BOOT_OPTS" 0 2
    fstab_entry "$efi_src" "$DIR_BOOT_EFI" vfat "$MNT_EFI_OPTS" 0 2
    printf '\n# Core filesystems\n'
    # shellcheck disable=SC2153
    fstab_entry "$root_src" / f2fs "$MNT_F2FS_ROOT_OPTS" 0 0
    if [ -n "${DEV_PART_HOME:-}" ] && [ "${DEV_PART_HOME_MB:-0}" -gt 0 ]; then
      home_src=$(device_source "$DEV_PART_HOME")
      fstab_entry "$home_src" "$DIR_HOME" f2fs "$MNT_F2FS_HOME_OPTS" 0 0
    fi
    if [ -n "${DEV_PART_POOL:-}" ] && [ "$DEV_PART_POOL_MB" -gt 0 ]; then
      pool_src=$(device_source "$DEV_PART_POOL")
      fstab_entry "$pool_src" "$DIR_POOL" ext4 "$MNT_EXT4_POOL_OPTS" 0 2
    fi
    if tmpfs_policy_enabled TMPFS_DATA_RUN; then
      printf '\n# Data runtime tmpfs\n'
      fstab_entry tmpfs "$DIR_DATA_RUN" tmpfs "$MNT_DATA_RUN_TMPFS_OPTS" 0 0
    fi
    printf '\n# Volatile tmpfs trees\n'
    if tmpfs_policy_enabled TMPFS_VAR_LOG; then
      fstab_entry tmpfs "$DIR_VAR_LOG" tmpfs "$MNT_VAR_LOG_TMPFS_OPTS" 0 0
    fi
    if tmpfs_policy_enabled TMPFS_VAR_CACHE; then
      fstab_entry tmpfs "$DIR_VAR_CACHE" tmpfs "$MNT_VAR_CACHE_TMPFS_OPTS" 0 0
    fi
    if tmpfs_policy_enabled TMPFS_VAR_LIB_APT_LISTS; then
      fstab_entry tmpfs "$DIR_APT_LISTS" tmpfs "$MNT_APT_LISTS_TMPFS_OPTS" 0 0
    fi
    if tmpfs_policy_enabled TMPFS_SYSTEMD_COREDUMP; then
      fstab_entry tmpfs "$DIR_SYSTEMD_COREDUMP" tmpfs "$MNT_COREDUMP_TMPFS_OPTS" 0 0
    fi
    fstab_entry tmpfs "$DIR_TMP" tmpfs "$MNT_TMP_OPTS" 0 0
    if tmpfs_policy_enabled TMPFS_DEV_SHM; then
      fstab_entry tmpfs "$DIR_DEV_SHM" tmpfs "$MNT_DEV_SHM_OPTS" 0 0
    fi
    printf '\n# Persistent journal\n'
    fstab_entry "$journal_src" "$DIR_VAR_LOG_JOURNAL" ext4 "$MNT_VAR_LOG_JOURNAL_OPTS" 0 2
  } | write_target_file /etc/fstab 0644
  cp /target/etc/fstab /target/etc/fstab.layout-cache 2>/dev/null || true
  cp /target/etc/fstab /target/etc/fstab.orig 2>/dev/null || true
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
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/modprobe.d/60-ses-blacklist.conf)" "${FILE_MODPROBE_SES_BLACKLIST}" 0644
  stage_target_asset_if_path "$(installer_hardware_asset_path disk "${DISK_CLASS}" "etc/modprobe.d/nvme-blacklist.conf")" "${FILE_MODPROBE_NVME_BLACKLIST:-}" "${DIR_MODPROBE_D}/nvme-blacklist.conf" 0644
  stage_target_asset_if_path "$(installer_hardware_asset_path cpu "${CPU_CLASS}" "etc/modprobe.d/05-mei-blacklist.conf")" "${FILE_MODPROBE_MEI_BLACKLIST:-}" "${DIR_MODPROBE_D}/05-mei-blacklist.conf" 0644
  stage_target_asset_if_path "$(installer_hardware_asset_path cpu "${CPU_CLASS}" "etc/modprobe.d/thinkpad-acpi.conf")" "${FILE_MODPROBE_THINKPAD_ACPI:-}" "${DIR_MODPROBE_D}/thinkpad-acpi.conf" 0644
  stage_target_asset_if_path "$(installer_hardware_asset_path gpu intel-uhd etc/modprobe.d/i915.conf)" "${FILE_MODPROBE_I915:-}" "${DIR_MODPROBE_D}/i915.conf" 0644
  stage_target_asset_if_path "$(installer_hardware_asset_path gpu amd-radeon etc/modprobe.d/amdgpu.conf)" "${FILE_MODPROBE_AMDGPU:-}" "${DIR_MODPROBE_D}/amdgpu.conf" 0644
  if [ "$target_enable_nvidia" = true ]; then
    stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/modprobe.d/50-nouveau-blacklist.conf)" "${DIR_MODPROBE_D}/50-nouveau-blacklist.conf" 0644
    stage_target_asset "$(installer_hardware_asset_path gpu nvidia etc/modprobe.d/nvidia.conf)" "${FILE_MODPROBE_NVIDIA}" 0644
  else
    remove_target_asset "${DIR_MODPROBE_D}/50-nouveau-blacklist.conf"
    remove_target_asset "${DIR_MODPROBE_D}/nvidia.conf"
  fi
  stage_target_asset_if_path "$(installer_hardware_asset_path disk "${DISK_CLASS}" "etc/modprobe.d/usbcore.conf")" "${FILE_MODPROBE_USBCORE:-}" "${DIR_MODPROBE_D}/usbcore.conf" 0644
  stage_target_asset_if_path "$(installer_hardware_asset_path cpu "${CPU_CLASS}" "etc/modprobe.d/cfg80211.conf")" "${FILE_MODPROBE_CFG80211:-}" "${DIR_MODPROBE_D}/cfg80211.conf" 0644
  stage_target_asset_if_path "$(installer_hardware_asset_path disk "${DISK_CLASS}" "etc/modules-load.d/20-emmc-storage.conf")" "${FILE_MODULES_LOAD_EMMC_STORAGE:-}" "${DIR_MODULES_LOAD}/20-emmc-storage.conf" 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/modules-load.d/30-storage-memory.conf)" "${FILE_MODULES_LOAD_STORAGE_MEMORY}" 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/modules-load.d/32-tpm.conf)" "${FILE_MODULES_LOAD_TPM}" 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/sysctl.d/10-baseline.conf)" "${FILE_SYSCTL_BASELINE}" 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/sysctl.d/20-storage-memory.conf)" "${FILE_SYSCTL_STORAGE_MEMORY}" 0644
  render_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/sysctl.d/25-storage-static.conf.tmpl)" "${FILE_SYSCTL_FAMILY_OVERRIDE}" 0644
  render_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/sysctl.d/profiles/balanced/40-balanced.conf)" "${FILE_SYSCTL_PROFILE_DEFAULT}" 0644
  render_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/sysctl.d/profiles/hardened/40-hardened.conf)" "${FILE_SYSCTL_PROFILE_HARDENED}" 0644
  render_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/sysctl.d/profiles/performance/40-performance.conf)" "${FILE_SYSCTL_PROFILE_PERFORMANCE}" 0644

  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/initramfs-tools/conf.d/99-compress.conf)" "${FILE_INITRAMFS_CUSTOM_CONF}" 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/initramfs-tools/conf.d/resume)" "${FILE_INITRAMFS_RESUME}" 0644
  render_target_asset "$(installer_hardware_asset_path disk "${DISK_CLASS}" "etc/initramfs-tools/modules.tmpl")" "${FILE_INITRAMFS_MODULES}" 0644
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
ensure_target_managed_runtime_storage_roots
provision_target_identity
stage_target_docs_index
stage_target_account_shell_assets
ensure_target_account_home_ownership
install_target_account_shell_assets
install_target_account_sudoers
configure_target_shared_account_access
write_target_grub_dropins
set_target_grub_default_entry
repair_target_pkgsel_include_packages
install_target_mullvad_vpn_if_selected
stage_target_secure_boot_runtime_assets
stage_target_xssh_helpers
provision_target_ssh_client
configure_target_rootless_podman_if_selected
sanitize_target_xfs_scrub_systemd_units
install_target_wpa_supplicant_runtime_policy
write_target_kernel_tunables
ensure_target_secure_boot_packages
provision_target_ssh_server
install_target_managed_network_handoff
configure_target_apparmor_auditd
dedupe_target_tmpfiles_legacy_lock
prepare_target_secure_boot_runtime
install_target_firstboot_logger
enable_target_storage_units
set_target_default_unit
disable_stock_kernel_menu

if target_exec_available; then
  sign_target_installed_kernel_modules
  # Regenerate signed kernels/initrds BEFORE discovering boot menu entries.
  repair_target_installed_kernels
  require_target_grub_installed
  install_target_grub_profiles
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
