#!/bin/sh
# Shared late_command core helpers. This file is sourced, not executed.

late_command_bootstrap_fatal() {
  printf '[bootstrap] fatal: %s\n' "$*" >&2
  exit 1
}

late_command_load_bootstrap() {
  if command -v bootstrap_source_common_lib >/dev/null 2>&1; then
    return 0
  fi

  runtime_dir=${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}
  bootstrap_lib=${INSTALLER_BOOTSTRAP_LIB:-${runtime_dir}/bootstrap/bootstrap.sh}

  [ -s "$bootstrap_lib" ] || {
    late_command_bootstrap_fatal "installer bootstrap library is unavailable: ${bootstrap_lib}"
  }

  # shellcheck disable=SC1090,SC1091
  . "$bootstrap_lib" || {
    late_command_bootstrap_fatal "failed to source installer bootstrap library: ${bootstrap_lib}"
  }
  command -v bootstrap_source_common_lib >/dev/null 2>&1 || {
    late_command_bootstrap_fatal "installer bootstrap library did not define bootstrap_source_common_lib: ${bootstrap_lib}"
  }
}

late_command_shared_init() {
  requested_seed_base=${1:-}
  requested_host_profile=${2:-}
  hook_family=${3:-}

  [ -n "$hook_family" ] || late_command_bootstrap_fatal "late-command hook family is required"
  late_command_load_bootstrap
  bootstrap_source_common_lib "$requested_seed_base" || {
    late_command_bootstrap_fatal "failed to source installer common library"
  }
  LOG="$(installer_runtime_log_file)"
  installer_init_log_file "$LOG" "" "${hook_family} late_command" late-command late_command
  trap 'installer_finalize_log "$?"' EXIT
  SEED_BASE=$(installer_seed_base "$requested_seed_base")
  installer_persist_seed_source "$SEED_BASE"
  installer_ensure_context_loaded "$SEED_BASE"
  HOST_PROFILE=$(installer_resolve_host_profile "$requested_host_profile")

  TMP_ENV_DIR=/tmp/install-env-late
  RUNTIME_DIR=$(installer_runtime_dir)
  LATE_COMMAND_HOST_ENV="${TMP_ENV_DIR}/host.env"
  LATE_COMMAND_ACCOUNT_ENV="${TMP_ENV_DIR}/account.env"
  mkdir -p "$TMP_ENV_DIR" "$RUNTIME_DIR"
  bootstrap_source_common_support_libs "$SEED_BASE" "$TMP_ENV_DIR" fetch hook target ssh || {
    installer_fatal "failed to source installer late support libraries"
  }
  late_command_collect_installer_logs
}

fetch_env() {
  fetch_env_file "$1" "$2"
}

fetch_hook() {
  fetch_hook_file "$1" "$2"
}

fatal() {
  installer_fatal "$@"
}

warn() {
  installer_warn "$@"
}

info() {
  installer_info "$@"
}

require_in_target() {
  phase_label=$1
  target_exec_available || fatal "target command execution is unavailable during ${phase_label}"
}

ensure_installer_command_logged() {
  cmd=$1
  udeb=$2

  if command -v "$cmd" >/dev/null 2>&1; then
    return 0
  fi
  warn "${cmd} is unavailable in the installer environment; attempting anna-install ${udeb}"
  hook_ensure_installer_command "$cmd" "$udeb"
}

late_command_collect_installer_logs() {
  runtime_log_dir=$(installer_runtime_log_dir)

  if installer_logging_enabled; then
    installer_info "live installer logs are under ${runtime_log_dir}; late hooks snapshot them into /target before finish-install runs"
  fi
}

late_command_ensure_env_paths() {
  [ -n "${TMP_ENV_DIR:-}" ] || late_command_bootstrap_fatal "late-command environment directory is not initialized"
  : "${LATE_COMMAND_HOST_ENV:=${TMP_ENV_DIR}/host.env}"
  : "${LATE_COMMAND_ACCOUNT_ENV:=${TMP_ENV_DIR}/account.env}"
}

late_command_host_env_path() {
  late_command_ensure_env_paths
  printf '%s\n' "$LATE_COMMAND_HOST_ENV"
}

late_command_account_env_path() {
  late_command_ensure_env_paths
  printf '%s\n' "$LATE_COMMAND_ACCOUNT_ENV"
}

late_command_ensure_host_policy_envs() {
  late_command_ensure_env_paths
  late_command_host_env=$LATE_COMMAND_HOST_ENV
  late_command_account_env=$LATE_COMMAND_ACCOUNT_ENV

  if [ ! -s "$late_command_host_env" ]; then
    installer_fetch_host_env "$SEED_BASE" "$HOST_PROFILE" "$late_command_host_env" 0600
    LATE_COMMAND_PROFILE_ENV_LOADED=0
  fi

  if [ ! -s "$late_command_account_env" ]; then
    installer_fetch_account_env "$SEED_BASE" "$late_command_account_env" 0600
    LATE_COMMAND_ACCOUNT_ENV_LOADED=0
  fi
}

late_command_load_profile_env() {
  [ "${LATE_COMMAND_PROFILE_ENV_LOADED:-0}" = 1 ] && return 0

  late_command_ensure_host_policy_envs
  late_command_host_env=$LATE_COMMAND_HOST_ENV
  [ -r "$late_command_host_env" ] || installer_fatal "host policy env is missing: ${late_command_host_env}"
  # shellcheck disable=SC1090,SC1091
  . "$late_command_host_env"
  validate_installed_log_levels
  LATE_COMMAND_PROFILE_ENV_LOADED=1
}

late_command_load_account_env() {
  [ "${LATE_COMMAND_ACCOUNT_ENV_LOADED:-0}" = 1 ] && return 0

  late_command_ensure_host_policy_envs
  late_command_account_env=$LATE_COMMAND_ACCOUNT_ENV
  [ -r "$late_command_account_env" ] || installer_fatal "account policy env is missing: ${late_command_account_env}"
  # shellcheck disable=SC1090,SC1091
  . "$late_command_account_env"
  [ -r "$TMP_ENV_DIR/runtime-common.sh" ] || installer_fatal "runtime common helper is missing: ${TMP_ENV_DIR}/runtime-common.sh"
  RUNTIME_COMMON_LIB="$TMP_ENV_DIR/runtime-common.sh"
  export RUNTIME_COMMON_LIB
  [ -r "$TMP_ENV_DIR/account-runtime.sh" ] || installer_fatal "runtime account helper is missing: ${TMP_ENV_DIR}/account-runtime.sh"
  # shellcheck disable=SC1090,SC1091
  . "$TMP_ENV_DIR/account-runtime.sh"
  runtime_apply_account_from_cmdline
  LATE_COMMAND_ACCOUNT_ENV_LOADED=1
}

late_command_fetch_common_assets() {
  runtime_script_path=$1

  late_command_ensure_host_policy_envs
  fetch_hook "$(installer_repo_join_var DIR_SCRIPTS_RUNTIME common.sh)" "$TMP_ENV_DIR/runtime-common.sh"
  fetch_hook "$runtime_script_path" "$TMP_ENV_DIR/runtime.sh"
  fetch_hook "$(installer_repo_join_var DIR_SCRIPTS_RUNTIME account.sh)" "$TMP_ENV_DIR/account-runtime.sh"
  fetch_hook "$(installer_repo_join_var DIR_HOOKS_TARGET usr/libexec/install-tools/bootprofile-apply.tmpl)" "$TMP_ENV_DIR/bootprofile-apply.tmpl"
  fetch_hook "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/system/bootprofile-apply.service.tmpl)" "$TMP_ENV_DIR/bootprofile-apply.service.tmpl"
  fetch_hook "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/libexec/apt-refresh-lists.tmpl)" "$TMP_ENV_DIR/apt-refresh-lists.tmpl"
  fetch_hook "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/system/apt-refresh-lists.service.tmpl)" "$TMP_ENV_DIR/apt-refresh-lists.service.tmpl"
  fetch_hook "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/system/apt-daily.service.d/override.conf.tmpl)" "$TMP_ENV_DIR/apt-daily.override.conf.tmpl"
  fetch_hook "$(installer_repo_join_var DIR_HOOKS_TARGET etc/sudoers.d/account.tmpl)" "$TMP_ENV_DIR/account.sudoers.tmpl"
  fetch_hook "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/system/zram-setup.service.tmpl)" "$TMP_ENV_DIR/zram-setup.service.tmpl"
  fetch_hook "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/system/zram-writeback.service.tmpl)" "$TMP_ENV_DIR/zram-writeback.service.tmpl"
  fetch_hook "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/system/zram-writebackd.service.tmpl)" "$TMP_ENV_DIR/zram-writebackd.service.tmpl"
  fetch_hook "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/system/zram-idle-writeback.timer.tmpl)" "$TMP_ENV_DIR/zram-idle-writeback.timer.tmpl"
  fetch_hook "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/system/zram-cold-tier.timer.tmpl)" "$TMP_ENV_DIR/zram-cold-tier.timer.tmpl"
  fetch_hook "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/system/swap-fallback.service.tmpl)" "$TMP_ENV_DIR/swap-fallback.service.tmpl"
  fetch_hook "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/libexec/tmpfs-pre-clean.tmpl)" "$TMP_ENV_DIR/tmpfs-pre-clean.tmpl"
  fetch_hook "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/system/tmpfs-pre-clean.service.tmpl)" "$TMP_ENV_DIR/tmpfs-pre-clean.service.tmpl"
}

late_command_load_runtime_env() {
  capture_dualboot_layout=${1:-false}

  late_command_load_profile_env
  RUNTIME_COMMON_LIB="$TMP_ENV_DIR/runtime-common.sh"
  export RUNTIME_COMMON_LIB
  # shellcheck disable=SC1090,SC1091
  . "$TMP_ENV_DIR/runtime.sh"
  if [ -r /tmp/install-env/runtime.env ]; then
    # shellcheck disable=SC1090,SC1091
    . /tmp/install-env/runtime.env
  elif [ -r /tmp/install-runtime/state/runtime.env ]; then
    # shellcheck disable=SC1090,SC1091
    . /tmp/install-runtime/state/runtime.env
  else
    runtime_apply_layout_from_cmdline
    if [ "$capture_dualboot_layout" = true ]; then
      command -v runtime_capture_dualboot_partition_sizes >/dev/null 2>&1 || installer_fatal "runtime_capture_dualboot_partition_sizes is unavailable in ${TMP_ENV_DIR}/runtime.sh"
      runtime_capture_dualboot_partition_sizes
    fi
    runtime_write_runtime_env "$(installer_runtime_state_dir)/runtime.env"
  fi
  installer_ensure_context_loaded "${SEED_BASE:-}"
  runtime_ensure_system_identity
  validate_tmpfs_policy_env
}

runtime_log_level_canonical() {
  case "${1:-error}" in
    debug|DEBUG) printf '%s\n' debug ;;
    info|INFO) printf '%s\n' info ;;
    warn|WARN|warning|WARNING) printf '%s\n' warning ;;
    error|ERROR|fatal|FATAL) printf '%s\n' error ;;
    none|NONE) printf '%s\n' none ;;
    *) return 1 ;;
  esac
}

runtime_nftables_log_level_canonical() {
  case "${1:-none}" in
    debug|DEBUG) printf '%s\n' debug ;;
    info|INFO) printf '%s\n' info ;;
    warn|WARN|warning|WARNING) printf '%s\n' warning ;;
    error|ERROR|fatal|FATAL) printf '%s\n' error ;;
    none|NONE) printf '%s\n' none ;;
    *) return 1 ;;
  esac
}

validate_installed_log_levels() {
  nft_level=$(runtime_nftables_log_level_canonical "${NFTABLES_LOG_LEVEL:-none}") ||
    installer_fatal "NFTABLES_LOG_LEVEL must be debug, info, warning, error, or none"
  zram_level=$(runtime_log_level_canonical "${ZRAM_LOG_LEVEL:-error}") ||
    installer_fatal "ZRAM_LOG_LEVEL must be debug, info, warning, error, or none"
  systemd_level=$(runtime_log_level_canonical "${SYSTEMD_LOG_LEVEL:-error}") ||
    installer_fatal "SYSTEMD_LOG_LEVEL must be debug, info, warning, error, or none"

  NFTABLES_LOG_LEVEL=$nft_level
  ZRAM_LOG_LEVEL=$zram_level
  SYSTEMD_LOG_LEVEL=$systemd_level
}

late_command_load_host_env() {
  late_command_load_profile_env
  late_command_load_account_env
}

install_target_runtime_defaults() {
  : "${FILE_LOGIND_OVERRIDE_CONF:?FILE_LOGIND_OVERRIDE_CONF must be set}"

  validate_installed_log_levels
  render_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/default/system-runtime.tmpl)" /etc/default/system-runtime 0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/logind.conf.d/override.conf)" \
    "${FILE_LOGIND_OVERRIDE_CONF}" \
    0644
}

install_target_wpa_supplicant_runtime_policy() {
  : "${FILE_WPA_SUPPLICANT_CONF:?FILE_WPA_SUPPLICANT_CONF must be set}"
  : "${FILE_WPA_SUPPLICANT_P2P_DEVICE_CONF:?FILE_WPA_SUPPLICANT_P2P_DEVICE_CONF must be set}"
  : "${FILE_WPA_SUPPLICANT_DBUS_SERVICE_OVERRIDE:?FILE_WPA_SUPPLICANT_DBUS_SERVICE_OVERRIDE must be set}"
  : "${FILE_WPA_SUPPLICANT_DBUS_SERVICE_ALIAS:?FILE_WPA_SUPPLICANT_DBUS_SERVICE_ALIAS must be set}"
  : "${FILE_NETWORKMANAGER_LINK_PRIVACY_CONF:?FILE_NETWORKMANAGER_LINK_PRIVACY_CONF must be set}"

  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/wpa_supplicant/wpa_supplicant.conf)" \
    "${FILE_WPA_SUPPLICANT_CONF}" \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/wpa_supplicant/p2p-device.conf)" \
    "${FILE_WPA_SUPPLICANT_P2P_DEVICE_CONF}" \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/system/wpa_supplicant.service.d/override.conf)" \
    "${FILE_WPA_SUPPLICANT_DBUS_SERVICE_OVERRIDE}" \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/NetworkManager/conf.d/80-managed-link-privacy.conf)" \
    "${FILE_NETWORKMANAGER_LINK_PRIVACY_CONF}" \
    0644

  [ -r "/target${FILE_WPA_SUPPLICANT_CONF}" ] ||
    installer_fatal "staged wpa_supplicant config is missing"
  [ -r "/target${FILE_WPA_SUPPLICANT_P2P_DEVICE_CONF}" ] ||
    installer_fatal "staged wpa_supplicant P2P device config is missing"
  [ -r "/target${FILE_WPA_SUPPLICANT_DBUS_SERVICE_OVERRIDE}" ] ||
    installer_fatal "staged wpa_supplicant D-Bus override is missing"
  [ -r "/target${FILE_NETWORKMANAGER_LINK_PRIVACY_CONF}" ] ||
    installer_fatal "staged NetworkManager link privacy policy is missing"
  grep -q '^p2p_disabled=1$' "/target${FILE_WPA_SUPPLICANT_CONF}" ||
    installer_fatal "wpa_supplicant config must disable P2P"
  grep -q '^p2p_disabled=1$' "/target${FILE_WPA_SUPPLICANT_P2P_DEVICE_CONF}" ||
    installer_fatal "wpa_supplicant P2P device config must disable P2P"
  grep -q 'ExecStart=/usr/sbin/wpa_supplicant .* -c /etc/wpa_supplicant/wpa_supplicant.conf ' \
    "/target${FILE_WPA_SUPPLICANT_DBUS_SERVICE_OVERRIDE}" ||
    installer_fatal "wpa_supplicant D-Bus override must load the managed config"
  if grep -q ' -m /etc/wpa_supplicant/p2p-device.conf ' \
    "/target${FILE_WPA_SUPPLICANT_DBUS_SERVICE_OVERRIDE}"; then
    installer_fatal "wpa_supplicant D-Bus override must not start a dedicated P2P device config"
  fi
  grep -q '^wifi\.scan-rand-mac-address=yes$' \
    "/target${FILE_NETWORKMANAGER_LINK_PRIVACY_CONF}" ||
    installer_fatal "NetworkManager link privacy policy must enable Wi-Fi scan MAC randomization"
  grep -q '^ethernet\.cloned-mac-address=random$' \
    "/target${FILE_NETWORKMANAGER_LINK_PRIVACY_CONF}" ||
    installer_fatal "NetworkManager link privacy policy must randomize Ethernet MAC addresses"
  grep -q '^wifi\.cloned-mac-address=random$' \
    "/target${FILE_NETWORKMANAGER_LINK_PRIVACY_CONF}" ||
    installer_fatal "NetworkManager link privacy policy must randomize Wi-Fi MAC addresses"
  if command -v target_systemd_unit_path >/dev/null 2>&1 &&
    target_systemd_unit_path wpa_supplicant.service system >/dev/null 2>&1
  then
    stage_target_systemd_unit_enabled wpa_supplicant.service system
    [ -L "/target${FILE_WPA_SUPPLICANT_DBUS_SERVICE_ALIAS}" ] ||
      installer_fatal "wpa_supplicant D-Bus systemd alias is missing: ${FILE_WPA_SUPPLICANT_DBUS_SERVICE_ALIAS}"
  fi
  installer_append_log_category late target_customization info network \
    "staged wpa_supplicant D-Bus policy config=${FILE_WPA_SUPPLICANT_CONF} p2p_config=${FILE_WPA_SUPPLICANT_P2P_DEVICE_CONF} override=${FILE_WPA_SUPPLICANT_DBUS_SERVICE_OVERRIDE}" || true
}

configure_target_smartmontools_defaults() {
  : "${FILE_SMARTMONTOOLS_DEFAULT:?FILE_SMARTMONTOOLS_DEFAULT must be set}"

  if ! test_in_target /bin/sh -c 'dpkg-query -s smartmontools >/dev/null 2>&1'; then
    return 0
  fi

  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/default/smartmontools)" \
    "${FILE_SMARTMONTOOLS_DEFAULT}" \
    0644
}

late_command_set_grub_arch_policy() {
  arch_class=${INSTALLER_ARCH_CLASS:-$(installer_selected_class_for_purpose arch 2>/dev/null || true)}

  [ -n "$arch_class" ] || installer_fatal "selected arch class is unavailable in installer context"

  # shellcheck disable=SC2034
  # Family hooks source this shared file and consume the arch-policy variables.
  case "$arch_class" in
    amd64)
      INSTALLER_GRUB_EFI_TARGET=x86_64-efi
      INSTALLER_GRUB_SHIM_EFI_PATH=/EFI/debian/shimx64.efi
      INSTALLER_GRUB_BINARY_EFI_PATH=/EFI/debian/grubx64.efi
      INSTALLER_GRUB_MOK_MANAGER_EFI_PATH=/EFI/debian/mmx64.efi
      INSTALLER_GRUB_REMOVABLE_BOOT_EFI_PATH=/EFI/BOOT/BOOTX64.EFI
      ;;
    arm64)
      INSTALLER_GRUB_EFI_TARGET=arm64-efi
      INSTALLER_GRUB_SHIM_EFI_PATH=/EFI/debian/shimaa64.efi
      INSTALLER_GRUB_BINARY_EFI_PATH=/EFI/debian/grubaa64.efi
      INSTALLER_GRUB_MOK_MANAGER_EFI_PATH=/EFI/debian/mmaa64.efi
      INSTALLER_GRUB_REMOVABLE_BOOT_EFI_PATH=/EFI/BOOT/BOOTAA64.EFI
      ;;
    *)
      installer_fatal "unsupported arch class for GRUB EFI policy: ${arch_class}"
      ;;
  esac
}

late_command_require_class_policy_env() {
  INSTALL_POLICY_ENV=$(installer_class_policy_env_path)
  [ -r "$INSTALL_POLICY_ENV" ] || installer_fatal "installer install policy env is missing: ${INSTALL_POLICY_ENV}"
  # shellcheck disable=SC1090,SC1091
  . "$INSTALL_POLICY_ENV"
  [ -n "${INSTALLER_PKGSEL_INCLUDE:-}" ] || installer_fatal "INSTALLER_PKGSEL_INCLUDE is missing from ${INSTALL_POLICY_ENV}"
  [ -n "${INSTALLER_SECURE_BOOT_BOOT_CHAIN_PACKAGES:-}" ] || installer_fatal "INSTALLER_SECURE_BOOT_BOOT_CHAIN_PACKAGES is missing from ${INSTALL_POLICY_ENV}"
  [ -n "${INSTALLER_SECURE_BOOT_TARGET_PACKAGES:-}" ] || installer_fatal "INSTALLER_SECURE_BOOT_TARGET_PACKAGES is missing from ${INSTALL_POLICY_ENV}"
  late_command_set_grub_arch_policy
}

late_command_graphics_initramfs_modules() (
  gpu_classes=${1:-}
  include_nvidia=${2:-false}
  emitted_modules=' '

  emit_unique_module() {
    module_name=$1
    case " $emitted_modules " in
      *" $module_name "*) return 0 ;;
    esac
    emitted_modules="${emitted_modules}${module_name} "
    printf '%s\n' "$module_name"
  }

  for gpu_class in $gpu_classes; do
    case "$gpu_class" in
      intel-uhd)
        emit_unique_module i915
        ;;
      amd-radeon)
        # AMD display drivers are not required for root discovery. Loading them
        # from initramfs can trip PSP TA firmware paths before the full target
        # firmware stack is available, so let udev load them after switch-root.
        ;;
      generic)
        ;;
      *)
        installer_fatal "unsupported gpu class: ${gpu_class}"
        ;;
    esac
  done

  case "$include_nvidia" in
    true)
      emit_unique_module nvidia
      emit_unique_module nvidia_modeset
      emit_unique_module nvidia_uvm
      emit_unique_module nvidia_drm
      ;;
  esac
)

install_target_firstboot_logger() {
  : "${FILE_FIRSTBOOT_HELPER:?FILE_FIRSTBOOT_HELPER must be set}"
  : "${FILE_FIRSTBOOT_SERVICE:?FILE_FIRSTBOOT_SERVICE must be set}"
  : "${FILE_SECONDBOOT_HELPER:?FILE_SECONDBOOT_HELPER must be set}"
  : "${FILE_SECONDBOOT_SERVICE:?FILE_SECONDBOOT_SERVICE must be set}"
  : "${FILE_INITRAMFS_HEALTH_COMMON:?FILE_INITRAMFS_HEALTH_COMMON must be set}"
  : "${FILE_INITRAMFS_HEALTH_INIT_TOP:?FILE_INITRAMFS_HEALTH_INIT_TOP must be set}"
  : "${FILE_INITRAMFS_HEALTH_INIT_PREMOUNT:?FILE_INITRAMFS_HEALTH_INIT_PREMOUNT must be set}"
  : "${FILE_INITRAMFS_HEALTH_LOCAL_TOP:?FILE_INITRAMFS_HEALTH_LOCAL_TOP must be set}"
  : "${FILE_INITRAMFS_HEALTH_LOCAL_BLOCK:?FILE_INITRAMFS_HEALTH_LOCAL_BLOCK must be set}"
  : "${FILE_INITRAMFS_HEALTH_LOCAL_PREMOUNT:?FILE_INITRAMFS_HEALTH_LOCAL_PREMOUNT must be set}"
  : "${FILE_INITRAMFS_HEALTH_LOCAL_BOTTOM:?FILE_INITRAMFS_HEALTH_LOCAL_BOTTOM must be set}"
  : "${FILE_INITRAMFS_HEALTH_INIT_BOTTOM:?FILE_INITRAMFS_HEALTH_INIT_BOTTOM must be set}"
  : "${DIR_INITRAMFS_SCRIPTS:?DIR_INITRAMFS_SCRIPTS must be set}"
  : "${DIR_FIRSTBOOT_LIB:?DIR_FIRSTBOOT_LIB must be set}"
  : "${DIR_FIRSTBOOT_LOG:?DIR_FIRSTBOOT_LOG must be set}"
  : "${DIR_FIRSTBOOT_STATE:?DIR_FIRSTBOOT_STATE must be set}"
  : "${DIR_INSTALL_LOG:?DIR_INSTALL_LOG must be set}"
  : "${DIR_INITRAMFS_LOG:?DIR_INITRAMFS_LOG must be set}"

  # Shared by system and desktop command wrappers on every storage family.
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/lib/perl5/site_perl/managed-runtime/Managed/Process.pm)" \
    /usr/local/lib/perl5/site_perl/managed-runtime/Managed/Process.pm 0644
  stage_target_asset "$(installer_repo_join_var DIR_SCRIPTS_FIRSTBOOT firstboot.sh)" "${FILE_FIRSTBOOT_HELPER}" 0755
  install -d -m 0755 "/target${DIR_FIRSTBOOT_LIB}"
  stage_target_asset "$(installer_repo_join_var DIR_SCRIPTS_FIRSTBOOT logging.sh)" "${DIR_FIRSTBOOT_LIB}/logging.sh" 0644
  for firstboot_stage in \
    01-early.sh \
    02-collect.sh \
    03-network.sh \
    04-validation.sh \
    05-cleanup.sh
  do
    stage_target_asset "$(installer_repo_join_var DIR_SCRIPTS_FIRSTBOOT "${firstboot_stage}")" "${DIR_FIRSTBOOT_LIB}/${firstboot_stage}" 0755
  done
  unset firstboot_stage

  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/initramfs-tools/scripts/installer-health-common)" "${FILE_INITRAMFS_HEALTH_COMMON}" 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/initramfs-tools/scripts/init-top/90-installer-health)" "${FILE_INITRAMFS_HEALTH_INIT_TOP}" 0755
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/initramfs-tools/scripts/init-premount/90-installer-health)" "${FILE_INITRAMFS_HEALTH_INIT_PREMOUNT}" 0755
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/initramfs-tools/scripts/local-top/90-installer-health)" "${FILE_INITRAMFS_HEALTH_LOCAL_TOP}" 0755
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/initramfs-tools/scripts/local-block/90-installer-health)" "${FILE_INITRAMFS_HEALTH_LOCAL_BLOCK}" 0755
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/initramfs-tools/scripts/local-premount/90-installer-health)" "${FILE_INITRAMFS_HEALTH_LOCAL_PREMOUNT}" 0755
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/initramfs-tools/scripts/local-bottom/90-installer-health)" "${FILE_INITRAMFS_HEALTH_LOCAL_BOTTOM}" 0755
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/initramfs-tools/scripts/init-bottom/90-installer-health)" "${FILE_INITRAMFS_HEALTH_INIT_BOTTOM}" 0755
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/system/firstboot.service)" "${FILE_FIRSTBOOT_SERVICE}" 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/libexec/secondboot-cleanup)" "${FILE_SECONDBOOT_HELPER}" 0755
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/system/secondboot.service)" "${FILE_SECONDBOOT_SERVICE}" 0644

  install -d -m 0700 \
    "/target${DIR_INITRAMFS_LOG}" \
    "/target${DIR_FIRSTBOOT_LOG}" \
    "/target${DIR_FIRSTBOOT_STATE}"
  if installer_logging_enabled; then
    install -d -m 0700 "/target${DIR_INSTALL_LOG}"
  fi

  stage_target_systemd_unit_enabled firstboot.service system
  stage_target_systemd_unit_enabled secondboot.service system
  installer_append_log_category late target_customization info firstboot "staged target first-boot wrapper ${FILE_FIRSTBOOT_HELPER}" || true
  installer_append_log_category late target_customization info secondboot "staged target cleanup service ${FILE_SECONDBOOT_SERVICE} automatic_after_completed_enrollment=true" || true
  installer_append_log_category bootloader bootloader info initramfs "staged initramfs health hooks under ${DIR_INITRAMFS_SCRIPTS}" || true
}

# Preserve NVIDIA VRAM only together with the vendor's complete sleep protocol.
# Both Btrfs/VM and F2FS late paths call this after staging GPU configuration.
configure_target_nvidia_power_management() (
  enabled=${1:-false}
  case "$enabled" in
    true|false) ;;
    *) installer_fatal 'NVIDIA power-management selection must be boolean'; exit 1 ;;
  esac
  gpu_root=$(installer_repo_join_var DIR_HOOKS_TARGET)
  if [ "$enabled" != true ]; then
    # Remove only our managed target assets, never installer /etc or vendor units.
    for phase in suspend suspend-then-hibernate hibernate resume; do
      remove_target_asset "/etc/systemd/system/nvidia-${phase}.service.d/20-managed-vram.conf"
    done
    for mode in suspend suspend-then-hibernate hibernate hybrid-sleep; do
      remove_target_asset "/etc/systemd/system/systemd-${mode}.service.d/20-nvidia-preserve.conf"
    done
    remove_target_asset /etc/tmpfiles.d/70-nvidia-vram.conf
    remove_target_asset /usr/local/libexec/nvidia-vram-check
    return 0
  fi
  stage_target_asset "${gpu_root}/usr/local/libexec/nvidia-vram-check" /usr/local/libexec/nvidia-vram-check 0755
  stage_target_asset "${gpu_root}/etc/tmpfiles.d/70-nvidia-vram.conf" /etc/tmpfiles.d/70-nvidia-vram.conf 0644
  for phase in suspend suspend-then-hibernate hibernate resume; do
    stage_target_asset "${gpu_root}/etc/systemd/system/nvidia-${phase}.service.d/20-managed-vram.conf" \
      "/etc/systemd/system/nvidia-${phase}.service.d/20-managed-vram.conf" 0644
  done
  for mode in suspend suspend-then-hibernate hibernate hybrid-sleep; do
    stage_target_asset "${gpu_root}/etc/systemd/system/systemd-${mode}.service.d/20-nvidia-preserve.conf"       "/etc/systemd/system/systemd-${mode}.service.d/20-nvidia-preserve.conf" 0644
  done
  run_in_target "enable NVIDIA video-memory preservation and validate disk backing" /bin/sh -eu -c '
    for unit in nvidia-suspend.service nvidia-suspend-then-hibernate.service nvidia-hibernate.service nvidia-resume.service; do
      if [ ! -f "/usr/lib/systemd/system/$unit" ] &&
         [ ! -f "/lib/systemd/system/$unit" ] &&
         [ ! -f "/etc/systemd/system/$unit" ]; then
        printf "fatal: selected NVIDIA driver package is missing %s\n" "$unit" >&2
        exit 1
      fi
    done
    if [ ! -x /usr/bin/nvidia-sleep.sh ]; then
      printf "fatal: selected NVIDIA driver package is missing nvidia-sleep.sh\n" >&2
      exit 1
    fi
    if [ ! -x /usr/lib/systemd/system-sleep/nvidia ] &&
       [ ! -x /lib/systemd/system-sleep/nvidia ]; then
      printf "fatal: selected NVIDIA driver package is missing its sleep recovery hook\n" >&2
      exit 1
    fi
    if [ -L /var/lib/nvidia-vram ] ||
       [ "$(readlink -f /var/lib)" != /var/lib ]; then
      printf "fatal: NVIDIA backing path is indirect\n" >&2
      exit 1
    fi
    install -d -m 0700 -o root -g root /var/lib/nvidia-vram
    /usr/local/libexec/nvidia-vram-check --directory-only
    # Offline enabling is intentional: do not suspend or start a bus in d-i.
    systemctl --no-reload enable nvidia-suspend.service nvidia-suspend-then-hibernate.service nvidia-hibernate.service nvidia-resume.service
  '
)
