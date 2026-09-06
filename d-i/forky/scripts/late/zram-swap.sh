#!/bin/sh
# Shared late_command zram, swap, and storage-unit helpers. This file is sourced, not executed.

fstab_entry() {
  printf '%-28s %-36s %-8s %-72s %s %s\n' "$1" "$2" "$3" "$4" "$5" "$6"
}

installer_mapper_for_raw_device() {
  raw_device=$1
  raw_real=$(readlink -f "$raw_device" 2>/dev/null || true)
  [ -n "$raw_real" ] || installer_fatal "unable to resolve encrypted raw device ${raw_device}"

  mapper_path=
  for dm_sysfs in /sys/class/block/dm-*; do
    [ -d "$dm_sysfs" ] || continue
    [ -r "$dm_sysfs/dm/name" ] || continue
    for slave_sysfs in "$dm_sysfs"/slaves/*; do
      [ -e "$slave_sysfs" ] || continue
      slave_name=${slave_sysfs##*/}
      slave_real=$(readlink -f "/dev/${slave_name}" 2>/dev/null || true)
      [ "$slave_real" = "$raw_real" ] || continue
      dm_name=$(cat "$dm_sysfs/dm/name" 2>/dev/null || true)
      [ -n "$dm_name" ] || continue
      candidate="/dev/mapper/${dm_name}"
      [ -b "$candidate" ] || continue
      if [ -n "$mapper_path" ] && [ "$mapper_path" != "$candidate" ]; then
        installer_fatal "multiple active dm-crypt mappings reference ${raw_device}"
      fi
      mapper_path=$candidate
    done
  done

  [ -n "$mapper_path" ] || installer_fatal "unable to locate active dm-crypt mapping for ${raw_device}"
  printf '%s\n' "$mapper_path"
}

installer_filesystem_device() {
  requested_device=$1
  case "${ROOT_HOME_CRYPTO_ENABLED:-false}:${requested_device}" in
    true:"${DEV_PART_ROOT:-}"|true:"${DEV_PART_HOME:-}")
      installer_mapper_for_raw_device "$requested_device"
      ;;
    *)
      printf '%s\n' "$requested_device"
      ;;
  esac
}

device_source() {
  dev=$1
  if [ "$dev" = "tmpfs" ]; then
    printf 'tmpfs\n'
    return 0
  fi
  dev=$(installer_filesystem_device "$dev")
  if command -v blkid >/dev/null 2>&1; then
    uuid=$(blkid -s UUID -o value "$dev" 2>/dev/null || true)
    if [ -n "$uuid" ]; then
      printf 'UUID=%s\n' "$uuid"
      return 0
    fi
  fi
  printf '%s\n' "$dev"
}

raw_partition_partuuid() {
  raw_device=$1

  case "$raw_device" in
    /dev/*) ;;
    *) installer_fatal "raw partition device must be an absolute /dev path: ${raw_device:-unset}" ;;
  esac
  command -v blkid >/dev/null 2>&1 ||
    installer_fatal "blkid is required to determine the stable raw partition path"
  raw_partuuid=$(blkid -s PARTUUID -o value "$raw_device" 2>/dev/null || true)
  case "$raw_partuuid" in
    ''|*[!A-Fa-f0-9-]*)
      installer_fatal "unable to determine a valid PARTUUID for raw partition ${raw_device}"
      ;;
  esac
  printf '%s\n' "$raw_partuuid"
}

stable_raw_partition_path() {
  raw_partuuid=$(raw_partition_partuuid "$1")
  printf '/dev/disk/by-partuuid/%s\n' "$raw_partuuid"
}

swap_fallback_partition_alignment_tolerance_bytes() {
  printf '%s\n' 2097152
}

swap_fallback_partition_size_is_acceptable() {
  sfps_configured_size_mb=$1
  sfps_actual_size_bytes=$2
  sfps_alignment_tolerance_bytes=$(swap_fallback_partition_alignment_tolerance_bytes)

  case "$sfps_configured_size_mb" in
    ''|*[!0-9]*|0) return 1 ;;
  esac
  case "$sfps_actual_size_bytes" in
    ''|*[!0-9]*) return 1 ;;
  esac

  sfps_expected_size_bytes=$((sfps_configured_size_mb * 1000000))
  [ "$sfps_actual_size_bytes" -ge "$sfps_expected_size_bytes" ] && return 0

  sfps_shortfall_bytes=$((sfps_expected_size_bytes - sfps_actual_size_bytes))
  [ "$sfps_shortfall_bytes" -le "$sfps_alignment_tolerance_bytes" ]
}

validate_swap_fallback_partition() {
  raw_device=${SWAP_FALLBACK_RAW_DEVICE:-}
  configured_size_mb=${DEV_PART_RAW_SWAP_MB:-}

  case "$raw_device" in
    /dev/*) ;;
    *) installer_fatal "swap fallback raw device must be an absolute /dev path: ${raw_device:-unset}" ;;
  esac
  case "$configured_size_mb" in
    ''|*[!0-9]*|0) installer_fatal "configured swap fallback partition size must be a positive integer: ${configured_size_mb:-unset}" ;;
  esac
  [ -b "$raw_device" ] || installer_fatal "swap fallback partition was not created: ${raw_device}"
  command -v blockdev >/dev/null 2>&1 || installer_fatal "blockdev is required to verify swap fallback partition size"
  actual_size_bytes=$(blockdev --getsize64 "$raw_device" 2>/dev/null) ||
    installer_fatal "unable to read swap fallback partition size: ${raw_device}"
  case "$actual_size_bytes" in
    ''|*[!0-9]*) installer_fatal "invalid swap fallback partition size for ${raw_device}: ${actual_size_bytes:-unset}" ;;
  esac
  alignment_tolerance_bytes=$(swap_fallback_partition_alignment_tolerance_bytes)
  expected_size_bytes=$((configured_size_mb * 1000000))
  actual_size_mb=$((actual_size_bytes / 1000000))
  if ! swap_fallback_partition_size_is_acceptable "$configured_size_mb" "$actual_size_bytes"; then
    shortfall_bytes=$((expected_size_bytes - actual_size_bytes))
    installer_fatal "swap fallback partition ${raw_device} is ${actual_size_mb} MB (${actual_size_bytes} bytes), configured size is ${configured_size_mb} MB (${expected_size_bytes} bytes), short by ${shortfall_bytes} bytes and exceeds the ${alignment_tolerance_bytes}-byte partman alignment tolerance"
  fi
  if [ "$actual_size_bytes" -lt "$expected_size_bytes" ]; then
    shortfall_bytes=$((expected_size_bytes - actual_size_bytes))
    installer_warn "swap fallback partition ${raw_device} is ${shortfall_bytes} bytes below the nominal recipe size; accepting within the ${alignment_tolerance_bytes}-byte partman alignment tolerance"
  fi
}

write_target_swap_fallback_config() {
  validate_swap_fallback_partition
  SWAP_FALLBACK_RAW_PARTUUID=$(raw_partition_partuuid "$SWAP_FALLBACK_RAW_DEVICE")
  SWAP_FALLBACK_RAW_DEVICE=$(stable_raw_partition_path "$SWAP_FALLBACK_RAW_DEVICE")
  {
    write_shell_config_var SWAP_FALLBACK_RAW_PARTUUID "${SWAP_FALLBACK_RAW_PARTUUID}"
    write_shell_config_var SWAP_FALLBACK_RAW_DEVICE "${SWAP_FALLBACK_RAW_DEVICE}"
    write_shell_config_var SWAP_FALLBACK_MAPPER_NAME "${SWAP_FALLBACK_MAPPER_NAME}"
    write_shell_config_var SWAP_FALLBACK_MAPPER "${SWAP_FALLBACK_MAPPER}"
    write_shell_config_var SWAP_FALLBACK_PRIORITY "${SWAP_FALLBACK_PRIORITY}"
    write_shell_config_var DMCRYPT_EPHEMERAL_CIPHER "${DMCRYPT_EPHEMERAL_CIPHER}"
    write_shell_config_var DMCRYPT_EPHEMERAL_KEY_SIZE "${DMCRYPT_EPHEMERAL_KEY_SIZE}"
    write_shell_config_var DMCRYPT_EPHEMERAL_HASH "${DMCRYPT_EPHEMERAL_HASH}"
    write_shell_config_var DMCRYPT_RANDOM_KEY_FILE "${DMCRYPT_RANDOM_KEY_FILE}"
  } >"/target${FILE_SWAP_FALLBACK_CONFIG}"
  chmod 0600 "/target${FILE_SWAP_FALLBACK_CONFIG}"
}

zram_perl_modules() {
  cat <<'EOF'
Zram.pm
Zram/AtomicFile.pm
Zram/BackingDevice.pm
Zram/Budget.pm
Zram/CLI.pm
Zram/Command.pm
Zram/Command/Apply.pm
Zram/Command/Metrics.pm
Zram/Command/Reset.pm
Zram/Command/Status.pm
Zram/Command/Writeback.pm
Zram/Config.pm
Zram/Config/Parser.pm
Zram/Config/Schema.pm
Zram/Config/Validator.pm
Zram/Daemon.pm
Zram/Daemon/Controller.pm
Zram/Debugfs.pm
Zram/Device.pm
Zram/Error.pm
Zram/Lock.pm
Zram/Logger.pm
Zram/Metrics.pm
Zram/Path.pm
Zram/Policy.pm
Zram/Pressure.pm
Zram/Pressure/Evaluator.pm
Zram/Procfs.pm
Zram/Procfs/Reader.pm
Zram/Runtime.pm
Zram/Setup/BackingDevice.pm
Zram/Setup/CLI.pm
Zram/Setup/Config.pm
Zram/Setup/Device.pm
Zram/Setup/Lifecycle.pm
Zram/Setup/Lock.pm
Zram/Setup/Mapper.pm
Zram/Setup/Sysfs.pm
Zram/Sizing.pm
Zram/Swap.pm
Zram/Stats.pm
Zram/Sysfs.pm
Zram/Tuning.pm
Zram/Types.pm
EOF
}

stage_target_zram_perl_modules() {
  zram_perl_modules | while IFS= read -r zram_module; do
    [ -n "$zram_module" ] || continue
    stage_target_asset \
      "$(installer_repo_join_var DIR_HOOKS_TARGET "usr/local/lib/perl5/site_perl/zram-writeback/${zram_module}")" \
      "${DIR_ZRAM_SITE_PERL}/${zram_module}" \
      0644
  done
}

stage_target_zram_assets() {
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/modprobe.d/zram.conf)" "${FILE_MODPROBE_ZRAM}" 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/modules-load.d/40-zram.conf)" "${FILE_MODULES_LOAD_ZRAM}" 0644
  render_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/default/zram-writeback.tmpl)" "${FILE_ZRAM_DEFAULT}" 0644
  render_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/zram-writeback.conf)" "${FILE_ZRAM_CONFIG}" 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/tmpfiles.d/60-zram-writeback.conf)" "${FILE_ZRAM_TMPFILES}" 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/rsyslog.d/36-zram.conf)" "${FILE_ZRAM_RSYSLOG}" 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/logrotate.d/zram)" "${FILE_ZRAM_LOGROTATE}" 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/libexec/zram-device-setup.tmpl)" "${FILE_ZRAM_SETUP_HELPER}" 0755
  stage_target_zram_perl_modules
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/libexec/zram-writeback.tmpl)" "${FILE_ZRAM_WRITEBACK_HELPER}" 0755
  render_target_template "$TMP_ENV_DIR/zram-setup.service.tmpl" "/target${FILE_ZRAM_SETUP_SERVICE}" 0644
  render_target_template "$TMP_ENV_DIR/zram-writeback.service.tmpl" "/target${FILE_ZRAM_WRITEBACK_SERVICE}" 0644
  render_target_template "$TMP_ENV_DIR/zram-writebackd.service.tmpl" "/target${FILE_ZRAM_WRITEBACKD_SERVICE}" 0644
  render_target_template "$TMP_ENV_DIR/zram-idle-writeback.timer.tmpl" "/target${FILE_ZRAM_IDLE_WRITEBACK_TIMER}" 0644
  render_target_template "$TMP_ENV_DIR/zram-cold-tier.timer.tmpl" "/target${FILE_ZRAM_COLD_TIER_TIMER}" 0644

  verify_target_zram_staging
}

verify_target_zram_staging() {
  for zram_path in \
    "${FILE_ZRAM_TMPFILES}" \
    "${FILE_ZRAM_RSYSLOG}" \
    "${FILE_ZRAM_LOGROTATE}" \
    "${FILE_ZRAM_SETUP_HELPER}" \
    "${FILE_ZRAM_WRITEBACK_HELPER}" \
    "${FILE_ZRAM_SETUP_SERVICE}" \
    "${FILE_ZRAM_WRITEBACK_SERVICE}" \
    "${FILE_ZRAM_WRITEBACKD_SERVICE}" \
    "${FILE_ZRAM_IDLE_WRITEBACK_TIMER}" \
    "${FILE_ZRAM_COLD_TIER_TIMER}"
  do
    [ -e "/target${zram_path}" ] ||
      installer_fatal "staged zram asset is missing: ${zram_path}"
  done

  normalize_target_tmpfiles_directory_policy \
    "${FILE_ZRAM_TMPFILES}" \
    "zram runtime and managed log state"
  run_in_target \
    "create zram runtime and managed log state" \
    /usr/bin/systemd-tmpfiles \
    --create \
    "${FILE_ZRAM_TMPFILES}"
  run_in_target \
    "validate zram rsyslog configuration" \
    /usr/sbin/rsyslogd \
    -N1 \
    -f \
    /etc/rsyslog.conf
  run_in_target \
    "validate zram logrotate configuration" \
    /usr/sbin/logrotate \
    --debug \
    /etc/logrotate.conf
}


set_target_default_unit() {
  stage_target_default_systemd_unit multi-user.target
}

target_unit_exists() {
  unit=$1

  target_systemd_unit_path "$unit" system >/dev/null 2>&1
}

enable_target_required_unit() {
  unit=$1
  target_unit_exists "$unit" || installer_fatal "expected target unit is missing: ${unit}"
  stage_target_systemd_unit_enabled "$unit" system
}

enable_target_storage_units() {
  enable_target_required_unit "swap-fallback.service"
  enable_target_required_unit "zram-setup.service"
  enable_target_required_unit "zram-writebackd.service"
  enable_target_required_unit "zram-idle-writeback.timer"
  enable_target_required_unit "zram-cold-tier.timer"
  if tmpfs_policy_enabled TMPFS_VAR_LIB_APT_LISTS; then
    enable_target_required_unit "apt-refresh-lists.service"
  fi
  enable_target_required_unit "bootprofile-apply.service"
  enable_target_required_unit "fstrim.timer"
}
