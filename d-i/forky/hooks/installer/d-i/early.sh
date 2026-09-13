#!/bin/sh
# Shared d-i early hook implementation used by storage families.

early_bool_is_true() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
  esac
  return 1
}

early_bootstrap_fatal() {
  printf '[bootstrap] fatal: %s\n' "$*" >&2
  exit 1
}

early_load_bootstrap() {
  requested_seed_base=${1:-}
  runtime_dir=${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}
  bootstrap_lib=${INSTALLER_BOOTSTRAP_LIB:-${runtime_dir}/bootstrap/bootstrap.sh}

  if [ ! -s "$bootstrap_lib" ]; then
    early_bootstrap_fatal "installer bootstrap library is unavailable: ${bootstrap_lib}"
  fi

  # shellcheck disable=SC1090,SC1091
  . "$bootstrap_lib"
  bootstrap_source_common_lib "$requested_seed_base"
}

early_ensure_crypto_dm_modules() {
  kernel_release=$(uname -r 2>/dev/null || true)
  if [ -n "$kernel_release" ]; then
    hook_anna_install_optional "crypto-dm-modules-${kernel_release}-di" || true
  fi
  hook_anna_install_optional crypto-dm-modules || true
}

early_preload_f2fs_kernel_support() {
  kernel_release=$(uname -r 2>/dev/null || true)
  if [ -n "$kernel_release" ]; then
    hook_anna_install_optional "f2fs-modules-${kernel_release}-di" || true
  fi
  hook_anna_install_optional f2fs-modules || true
  if command -v depmod >/dev/null 2>&1; then
    depmod -a >/dev/null 2>&1 || true
  fi
  if command -v modprobe >/dev/null 2>&1; then
    modprobe f2fs >/dev/null 2>&1 || true
  fi
}

early_preload_f2fs_tooling() {
  early_preload_f2fs_kernel_support
  hook_preload_installer_udeb f2fs-tools-udeb || true
  hook_preload_installer_command mkfs.f2fs f2fs-tools-udeb || true
  hook_preload_installer_command mkfs.ext4 e2fsprogs-udeb || true
  hook_preload_installer_command mkfs.fat dosfstools-udeb || true
}

family_d_i_early_main() {
  requested_seed_base=${1:-}
  requested_host_profile=${2:-}
  hook_family=${3:-}
  runtime_script_path=${4:-}
  capture_dualboot_sizes=${5:-false}
  preload_f2fs=${6:-false}

  [ -n "$hook_family" ] || early_bootstrap_fatal "d-i early hook family is required"
  [ -n "$runtime_script_path" ] || early_bootstrap_fatal "runtime script path is required"

  early_load_bootstrap "$requested_seed_base"

  LOG="$(installer_runtime_log_file)"
  installer_init_log_file "$LOG" "" "${hook_family} d-i early hook" d-i-early preseed_loaded
  trap 'installer_finalize_log "$?"' EXIT
  installer_load_context_if_present || true

  SEED_BASE=$(installer_seed_base "$requested_seed_base")
  installer_persist_seed_source "$SEED_BASE"
  HOST_PROFILE=$(installer_resolve_host_profile "$requested_host_profile")
  installer_log_boot_context
  installer_log_network_context

  install -d -m 0755 \
    /usr/lib/apt-setup/generators \
    /usr/lib/base-installer.d \
    /usr/lib/pre-pkgsel.d \
    /usr/lib/finish-install.d \
    /lib/partman/finish.d

  TMP_ENV_DIR="/tmp/install-env"
  RUNTIME_DIR=$(installer_runtime_dir)
  STATE_DIR=$(installer_runtime_state_dir)
  CACHE_DIR=$(installer_runtime_cache_dir)
  RUNTIME_ACCOUNT_FILE="${STATE_DIR}/account.answers.cfg"
  RUNTIME_CRYPTO_FILE="${STATE_DIR}/crypto.answers.cfg"
  RUNTIME_PARTMAN_FILE="${STATE_DIR}/partman.answers.cfg"
  RUNTIME_ENV_FILE="${STATE_DIR}/runtime.env"
  RUNTIME_RECIPE_FILE="${CACHE_DIR}/expert_recipe"

  install -d -m 0700 "$TMP_ENV_DIR" "$RUNTIME_DIR"
  bootstrap_source_common_support_libs "$SEED_BASE" "$TMP_ENV_DIR" fetch hook
  fetch_hook_file \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/apt/apt.conf.d/99noinstall-recommends)" \
    "$TMP_ENV_DIR/99noinstall-recommends"
  chmod 0644 "$TMP_ENV_DIR/99noinstall-recommends"

  fetch_hook_file "$(installer_repo_join_var DIR_HOOKS_INSTALLER_APT_SETUP_GENERATORS 99-apt-preferences)" "/usr/lib/apt-setup/generators/99-apt-preferences"
  fetch_hook_file "$(installer_repo_join_var DIR_HOOKS_INSTALLER_APT_SETUP_GENERATORS 98-cuda-legacy-source)" "/usr/lib/apt-setup/generators/98-cuda-legacy-source"
  chmod 0755 /usr/lib/apt-setup/generators/98-cuda-legacy-source
  chmod 0755 /usr/lib/apt-setup/generators/99-apt-preferences
  fetch_hook_file "$(installer_repo_join_var DIR_HOOKS_INSTALLER_BASE_STAGE_D 10-apt-install-policy)" "/usr/lib/base-installer.d/10-apt-install-policy"
  fetch_hook_file "$(installer_repo_join_var DIR_HOOKS_INSTALLER_BASE_STAGE_D 20-fstab-guard)" "/usr/lib/base-installer.d/20-fstab-guard"
  chmod 0755 /usr/lib/base-installer.d/10-apt-install-policy
  fetch_hook_file "$(installer_repo_join_var DIR_HOOKS_INSTALLER_PRE_PKGSEL_D 49nvidia-opt-in-firmware.sh)" "/usr/lib/pre-pkgsel.d/49nvidia-opt-in-firmware"
  fetch_hook_file "$(installer_repo_join_var DIR_HOOKS_INSTALLER_PRE_PKGSEL_D 88temporary-os-prober.sh)" "/usr/lib/pre-pkgsel.d/88temporary-os-prober"
  fetch_hook_file "$(installer_repo_join_var DIR_HOOKS_INSTALLER_PRE_PKGSEL_D 89temporary-unshare.sh)" "/usr/lib/pre-pkgsel.d/89temporary-unshare"
  fetch_hook_file "$(installer_repo_join_var DIR_HOOKS_INSTALLER_PRE_PKGSEL_D 90secure-boot-dkms.sh)" "/usr/lib/pre-pkgsel.d/90secure-boot-dkms"
  fetch_hook_file "$(installer_repo_join_var DIR_HOOKS_INSTALLER_PRE_PKGSEL_D 91cuda-legacy-apt.sh)" "/usr/lib/pre-pkgsel.d/91cuda-legacy-apt"
  fetch_hook_file "$(installer_repo_join_var DIR_HOOKS_INSTALLER_PRE_PKGSEL_D 92nvidia-legacy-dkms.sh)" "/usr/lib/pre-pkgsel.d/92nvidia-legacy-dkms"
  chmod 0755 /usr/lib/pre-pkgsel.d/49nvidia-opt-in-firmware
  # Finalize volatile backing directories before any target-side APT command,
  # then repair/modernize sources; both still precede validation and 95umount.
  fetch_hook_file "$(installer_repo_join_var DIR_HOOKS_INSTALLER_FINISH_INSTALL_D 99-normalize-finish)" "/usr/lib/finish-install.d/94zz-10-normalize-finish"
  fetch_hook_file "$(installer_repo_join_var DIR_HOOKS_INSTALLER_FINISH_INSTALL_D 95-normalize-apt)" "/usr/lib/finish-install.d/94zz-20-normalize-apt"
  chmod 0755 /usr/lib/finish-install.d/94zz-10-normalize-finish /usr/lib/finish-install.d/94zz-20-normalize-apt
  fetch_hook_file "$(installer_repo_join_var DIR_HOOKS_INSTALLER_FINISH_INSTALL_D 00-installer-guard)" /usr/lib/finish-install.d/00-installer-guard
  fetch_hook_file "$(installer_repo_join_var DIR_HOOKS_INSTALLER_FINISH_INSTALL_D 94zz-99-validate-target)" /usr/lib/finish-install.d/94zz-99-validate-target
  # Interpose on the first base-installer APT update, not on the later
  # apt-setup generator. The adapter rejects unknown d-i waypoint layouts.
  fetch_hook_file scripts/common/apt-sources.sh "$RUNTIME_DIR/bootstrap/apt-sources.sh"
  fetch_hook_file scripts/preseed/network-apt.sh "$RUNTIME_DIR/bootstrap/network-apt.sh"
  fetch_hook_file scripts/preseed/base-apt-adapter.sh "$RUNTIME_DIR/bootstrap/base-apt-adapter.sh"
  /bin/sh -eu "$RUNTIME_DIR/bootstrap/base-apt-adapter.sh" \
    /var/lib/dpkg/info/bootstrap-base.postinst "$RUNTIME_DIR/bootstrap/network-apt.sh"
  # anna has loaded these mandatory components before preseed/early_command.
  # Refuse an installer image missing them rather than run an unguarded phase.
  for component in bootstrap-base apt-setup-udeb pkgsel grub-installer finish-install partman-base; do
    installer_guard_hook "/var/lib/dpkg/info/$component.postinst" component ||
      installer_fatal "cannot supervise mandatory d-i component: $component"
  done
  # base-installer itself treats post-base hook failures as warnings.
  for base_hook in /usr/lib/post-base-installer.d/*; do
    [ -x "$base_hook" ] || continue
    installer_guard_hook "$base_hook" post-base || installer_fatal 'cannot supervise post-base hook'
  done
  fetch_hook_file "scripts/runtime/common.sh" "$TMP_ENV_DIR/runtime-common.sh"
  fetch_hook_file "$runtime_script_path" "$TMP_ENV_DIR/runtime.sh"
  fetch_hook_file "scripts/runtime/account.sh" "$TMP_ENV_DIR/account.sh"
  fetch_hook_file "scripts/partman/detect-disk.sh" "$TMP_ENV_DIR/detect-disk.sh"
  installer_fetch_host_env "$SEED_BASE" "$HOST_PROFILE" "$TMP_ENV_DIR/host.env" 0600
  installer_fetch_account_env "$SEED_BASE" "$TMP_ENV_DIR/account.env" 0600

  # shellcheck disable=SC1090,SC1091
  . "$TMP_ENV_DIR/host.env"
  RUNTIME_COMMON_LIB="$TMP_ENV_DIR/runtime-common.sh"
  export RUNTIME_COMMON_LIB
  # shellcheck disable=SC1090,SC1091
  . "$TMP_ENV_DIR/runtime.sh"
  # shellcheck disable=SC1090,SC1091
  . "$TMP_ENV_DIR/account.sh"
  # shellcheck disable=SC1090,SC1091
  . "$TMP_ENV_DIR/account.env"

  # Validate credentials before disk discovery, partition tooling or storage
  # planning. /preseed.env belongs to the running initrd, never the target.
  runtime_validate_account_settings

  write_crypto_answers=false
  if command -v runtime_crypto_answers_required >/dev/null 2>&1; then
    if runtime_crypto_answers_required; then
      write_crypto_answers=true
    fi
  fi

  hook_resolve_install_disk "$TMP_ENV_DIR/detect-disk.sh" "$HOST_PROFILE"
  installer_log_disk_context

  runtime_apply_ssh_from_classes
  runtime_apply_layout_from_cmdline
  runtime_apply_account_from_cmdline
  runtime_seed_identity_answers
  installer_log_preseed_context
  installer_info "seeded runtime identity fragment from generated hostname"

  # Partman crypto and later Secure Boot helpers need cryptsetup in d-i.
  hook_ensure_installer_command cryptsetup cryptsetup-udeb
  if runtime_dualboot_class_selected; then
    # grub-installer invokes the installer udeb directly before it evaluates
    # the preseeded GRUB policy. Ensure the real command exists before the
    # pre-pkgsel hook preserves it and installs the temporary no-output shim.
    hook_ensure_installer_command os-prober os-prober-udeb
  fi
  if early_bool_is_true "$write_crypto_answers"; then
    early_ensure_crypto_dm_modules
  fi
  hook_preload_partition_tooling
  if early_bool_is_true "$preload_f2fs"; then
    early_preload_f2fs_tooling
  fi

  runtime_write_account_answers "$RUNTIME_ACCOUNT_FILE"
  runtime_apply_answers_file "$RUNTIME_ACCOUNT_FILE"
  installer_info "seeded runtime account fragment from ${RUNTIME_ACCOUNT_FILE}"

  if early_bool_is_true "$write_crypto_answers"; then
    runtime_write_crypto_answers "$RUNTIME_CRYPTO_FILE"
    runtime_apply_answers_file "$RUNTIME_CRYPTO_FILE"
    installer_info "seeded runtime crypto fragment from ${RUNTIME_CRYPTO_FILE}"
  fi
  runtime_write_effective_account_env "$TMP_ENV_DIR/account.env"

  if early_bool_is_true "$capture_dualboot_sizes"; then
    runtime_capture_dualboot_partition_sizes
  fi
  runtime_write_runtime_env "$RUNTIME_ENV_FILE"
  cp "$RUNTIME_ENV_FILE" "${TMP_ENV_DIR}/runtime.env"
  runtime_write_expert_recipe "$RUNTIME_RECIPE_FILE"
  runtime_write_partman_fragment "$RUNTIME_PARTMAN_FILE" "$RUNTIME_RECIPE_FILE"
  runtime_apply_answers_file "$RUNTIME_PARTMAN_FILE"
  installer_info "seeded runtime partman fragment from ${RUNTIME_PARTMAN_FILE}"
  installer_info "hooks installed from $(installer_seed_source_type "$SEED_BASE") seed source $SEED_BASE"
}
