#!/bin/sh
# F2FS/ext4 runtime layout helpers.
# shellcheck disable=SC2034

if ! command -v runtime_fatal >/dev/null 2>&1; then
  if [ -n "${RUNTIME_COMMON_LIB:-}" ] && [ -r "$RUNTIME_COMMON_LIB" ]; then
    # shellcheck disable=SC1090
    . "$RUNTIME_COMMON_LIB"
  else
    echo "fatal: runtime common helper is unavailable; set RUNTIME_COMMON_LIB before sourcing ${0##*/}" >&2
    exit 1
  fi
fi

runtime_secure_boot_state_mode() {
  secure_boot_mode=${SECURE_BOOT_MODE:-}
  secure_boot_state_mode=${SECURE_BOOT_STATE_MODE:-}
  if [ -n "$secure_boot_mode" ] && [ -n "$secure_boot_state_mode" ] && [ "$secure_boot_mode" != "$secure_boot_state_mode" ]; then
    runtime_fatal "SECURE_BOOT_MODE and SECURE_BOOT_STATE_MODE disagree: '${secure_boot_mode}' != '${secure_boot_state_mode}'"
    return 1
  fi
  mode=${secure_boot_mode:-${secure_boot_state_mode:-direct}}
  case "$mode" in
    direct|luks)
      printf '%s\n' "$mode"
      ;;
    *)
      runtime_fatal "SECURE_BOOT_MODE/SECURE_BOOT_STATE_MODE must be 'direct' or 'luks' for F2FS profiles, got '${mode}'"
      return 1
      ;;
  esac
}

runtime_crypto_answers_required() {
  runtime_root_home_crypto_enabled || runtime_secure_boot_state_uses_luks
}

runtime_required_slot_from_env() {
  label=$1
  eval "value=\${$label:-}"
  runtime_require_positive_integer "$label" "$value"
  printf '%s\n' "$value"
}

runtime_optional_slot_from_env() {
  label=$1
  eval "value=\${$label:-}"
  if [ -z "$value" ]; then
    printf '\n'
    return 0
  fi
  runtime_require_positive_integer "$label" "$value"
  printf '%s\n' "$value"
}

runtime_partition_slot_from_path() {
  label=$1
  path=$2
  case "$path" in
    "${DEV_PART_PREFIX}"[0-9]*)
      slot=${path#"$DEV_PART_PREFIX"}
      ;;
    *)
      runtime_fatal "${label} path ${path} does not use prefix ${DEV_PART_PREFIX}"
      ;;
  esac

  case "$slot" in
    ''|*[!0-9]*)
      runtime_fatal "unable to parse a partition slot from ${label}=${path}"
      ;;
    0)
      runtime_fatal "${label} must not resolve to slot 0"
      ;;
  esac

  printf '%s\n' "$slot"
}

runtime_build_space_list() {
  start=$1
  end=$2
  skip=${3:-}
  result=
  current=$start

  while [ "$current" -le "$end" ]; do
    if [ -n "$skip" ] && [ "$current" -eq "$skip" ]; then
      current=$((current + 1))
      continue
    fi
    result="${result:+$result }${current}"
    current=$((current + 1))
  done

  printf '%s\n' "$result"
}

runtime_partition_size_var() {
  slot=$1
  runtime_require_positive_integer partition_slot "$slot"
  printf 'RUNTIME_PARTITION_%s_SIZE_MB\n' "$slot"
}

runtime_set_partition_size_mb() {
  slot=$1
  size_mb=$2
  runtime_require_positive_integer partition_slot "$slot"
  runtime_require_positive_integer partition_size_mb "$size_mb"

  var=$(runtime_partition_size_var "$slot")
  eval "$var=\$size_mb"
}

runtime_get_partition_size_mb() {
  slot=$1
  runtime_require_positive_integer partition_slot "$slot"

  var=$(runtime_partition_size_var "$slot")
  eval "size_mb=\${$var:-}"
  if [ -n "$size_mb" ]; then
    printf '%s\n' "$size_mb"
    return 0
  fi

  return 1
}

runtime_first_nonempty_line() {
  sed -n 's/^[[:space:]]*//; s/[[:space:]]*$//; /^$/d; p; q'
}

runtime_normalize_guid() {
  printf '%s\n' "${1:-}" | tr 'A-F' 'a-f'
}

runtime_probe_lsblk_column() {
  column=$1
  dev=$2

  command -v lsblk >/dev/null 2>&1 || return 1
  value=$(lsblk -dn -o "$column" -- "$dev" 2>/dev/null | runtime_first_nonempty_line || true)
  case "$value" in
    ''|unknown|UNKNOWN) return 1 ;;
  esac

  printf '%s\n' "$value"
}

runtime_probe_blkid_tag() {
  tag=$1
  dev=$2

  command -v blkid >/dev/null 2>&1 || return 1

  value=$(blkid -s "$tag" -o value "$dev" 2>/dev/null | runtime_first_nonempty_line || true)
  case "$value" in
    ''|unknown|UNKNOWN) ;;
    *)
      printf '%s\n' "$value"
      return 0
      ;;
  esac

  value=$(blkid -p -s "$tag" -o value "$dev" 2>/dev/null | runtime_first_nonempty_line || true)
  case "$value" in
    ''|unknown|UNKNOWN) ;;
    *)
      printf '%s\n' "$value"
      return 0
      ;;
  esac

  value=$(blkid -p -o export "$dev" 2>/dev/null | sed -n "s/^${tag}=//p" | runtime_first_nonempty_line || true)
  case "$value" in
    ''|unknown|UNKNOWN) return 1 ;;
  esac

  printf '%s\n' "$value"
}

runtime_probe_udev_property() {
  property=$1
  dev=$2

  command -v udevadm >/dev/null 2>&1 || return 1
  value=$(udevadm info --query=property --name="$dev" 2>/dev/null | sed -n "s/^${property}=//p" | runtime_first_nonempty_line || true)
  case "$value" in
    ''|unknown|UNKNOWN) return 1 ;;
  esac

  printf '%s\n' "$value"
}

runtime_probe_filesystem_type() {
  dev=$1

  value=$(runtime_probe_blkid_tag TYPE "$dev" 2>/dev/null || true)
  if [ -n "$value" ]; then
    printf '%s\n' "$value"
    return 0
  fi

  value=$(runtime_probe_lsblk_column FSTYPE "$dev" 2>/dev/null || true)
  if [ -n "$value" ]; then
    printf '%s\n' "$value"
    return 0
  fi

  runtime_probe_udev_property ID_FS_TYPE "$dev"
}

runtime_probe_partition_table_type() {
  dev=$1

  value=$(runtime_probe_blkid_tag PTTYPE "$dev" 2>/dev/null || true)
  if [ -n "$value" ]; then
    printf '%s\n' "$value"
    return 0
  fi

  value=$(runtime_probe_lsblk_column PTTYPE "$dev" 2>/dev/null || true)
  if [ -n "$value" ]; then
    printf '%s\n' "$value"
    return 0
  fi

  runtime_probe_udev_property ID_PART_TABLE_TYPE "$dev"
}

runtime_gpt_esp_type_guid() {
  printf '%s\n' c12a7328-f81f-11d2-ba4b-00a0c93ec93b
}

runtime_probe_gpt_part_type() {
  dev=$1

  value=$(runtime_probe_lsblk_column PARTTYPE "$dev" 2>/dev/null || true)
  if [ -n "$value" ]; then
    runtime_normalize_guid "$value"
    return 0
  fi

  value=$(runtime_probe_blkid_tag PART_ENTRY_TYPE "$dev" 2>/dev/null || true)
  if [ -n "$value" ]; then
    runtime_normalize_guid "$value"
    return 0
  fi

  value=$(runtime_probe_udev_property ID_PART_ENTRY_TYPE "$dev" 2>/dev/null || true)
  if [ -n "$value" ]; then
    runtime_normalize_guid "$value"
    return 0
  fi

  return 1
}

runtime_gpt_part_type_is_esp() {
  part_type=$(runtime_normalize_guid "${1:-}")
  [ "$part_type" = "$(runtime_gpt_esp_type_guid)" ]
}

runtime_capture_dualboot_partition_sizes() {
  [ "${DUALBOOT_ENABLED:-false}" = "true" ] || return 0

  slot=1
  while [ "$slot" -lt "$RUNTIME_DEBIAN_START_SLOT" ]; do
    part_dev=$(runtime_partition_path "$slot")
    size_mb=$(runtime_device_size_mb "$part_dev") || \
      runtime_fatal "unable to capture measured partition size for preserved slot ${slot} (${part_dev})"
    runtime_set_partition_size_mb "$slot" "$size_mb"
    slot=$((slot + 1))
  done
}

runtime_sum_preserved_partition_sizes_mb() {
  total_mb=0

  [ "${DUALBOOT_ENABLED:-false}" = "true" ] || {
    printf '0\n'
    return 0
  }

  slot=1
  while [ "$slot" -lt "$RUNTIME_DEBIAN_START_SLOT" ]; do
    size_mb=$(runtime_get_partition_size_mb "$slot") || \
      runtime_fatal "missing measured partition size for preserved slot ${slot}"
    total_mb=$((total_mb + size_mb))
    slot=$((slot + 1))
  done

  printf '%s\n' "$total_mb"
}

runtime_validate_layout_slots() {
  previous=0

  for slot in \
    "$RUNTIME_EFI_SLOT" \
    "$RUNTIME_BOOT_SLOT" \
    "$RUNTIME_ROOT_SLOT" \
    "${RUNTIME_HOME_SLOT:-}" \
    "${RUNTIME_POOL_SLOT:-}" \
    "${RUNTIME_VAR_LIB_SHSIGNED_SLOT:-}" \
    "$RUNTIME_VAR_LOG_JOURNAL_SLOT" \
    "$RUNTIME_RAW_SWAP_SLOT" \
    "$RUNTIME_RAW_ZRAM_SLOT"
  do
    [ -n "$slot" ] || continue
    runtime_require_positive_integer runtime_layout_slot "$slot"
    if [ "$slot" -le "$previous" ]; then
      runtime_fatal "F2FS slot numbering must stay strictly increasing from EFI through optional Secure Boot state and raw zram backing"
    fi
    previous=$slot
  done
}

runtime_assign_default_slots() {
  DUALBOOT_ENABLED=false
  DUALBOOT_EFI_SLOT=
  DUALBOOT_DEBIAN_SLOT=
  RUNTIME_PRESERVED_SLOTS=
  RUNTIME_EFI_SLOT=$(runtime_required_slot_from_env DEFAULT_EFI_SLOT)
  RUNTIME_BOOT_SLOT=$(runtime_required_slot_from_env DEFAULT_BOOT_SLOT)
  RUNTIME_ROOT_SLOT=$(runtime_required_slot_from_env DEFAULT_ROOT_SLOT)
  RUNTIME_HOME_SLOT=$(runtime_optional_slot_from_env DEFAULT_HOME_SLOT)
  RUNTIME_POOL_SLOT=$(runtime_optional_slot_from_env DEFAULT_POOL_SLOT)
  RUNTIME_VAR_LOG_JOURNAL_SLOT=$(runtime_required_slot_from_env DEFAULT_VAR_LOG_JOURNAL_SLOT)
  RUNTIME_RAW_SWAP_SLOT=$(runtime_required_slot_from_env DEFAULT_RAW_SWAP_SLOT)
  RUNTIME_RAW_ZRAM_SLOT=$(runtime_required_slot_from_env DEFAULT_RAW_ZRAM_SLOT)
  RUNTIME_VAR_LIB_SHSIGNED_SLOT=

  if [ "${F2FS_QEMU_POOL_ENABLED:-false}" = true ] && [ -z "$RUNTIME_POOL_SLOT" ]; then
    RUNTIME_POOL_SLOT=$RUNTIME_VAR_LOG_JOURNAL_SLOT
    RUNTIME_VAR_LOG_JOURNAL_SLOT=$((RUNTIME_VAR_LOG_JOURNAL_SLOT + 1))
    RUNTIME_RAW_SWAP_SLOT=$((RUNTIME_RAW_SWAP_SLOT + 1))
    RUNTIME_RAW_ZRAM_SLOT=$((RUNTIME_RAW_ZRAM_SLOT + 1))
  fi
}

runtime_configure_qemu_pool() {
  F2FS_QEMU_POOL_ENABLED=false
  runtime_qemu_class_selected || return 0

  [ "$F2FS_LAYOUT_VARIANT" = desktop ] ||
    runtime_fatal "addon/qemu requires an F2FS desktop layout"

  qemu_pool_mb=${SIZE_PART_QEMU_POOL_MB:-}
  qemu_pool_min_mb=${SIZE_PART_QEMU_POOL_MIN_MB:-$qemu_pool_mb}
  runtime_require_positive_integer SIZE_PART_QEMU_POOL_MB "$qemu_pool_mb"
  runtime_require_positive_integer SIZE_PART_QEMU_POOL_MIN_MB "$qemu_pool_min_mb"
  [ "$qemu_pool_min_mb" -le "$qemu_pool_mb" ] ||
    runtime_fatal "SIZE_PART_QEMU_POOL_MIN_MB must not exceed SIZE_PART_QEMU_POOL_MB"

  F2FS_QEMU_POOL_ENABLED=true
  SIZE_PART_POOL_MB=$qemu_pool_mb
  SIZE_PART_POOL_MIN_MB=$qemu_pool_min_mb
}

runtime_assign_dualboot_slots() {
  dualboot_efi_slot=$1
  dualboot_debian_slot=$2
  secure_boot_state_mode=$3

  runtime_require_positive_integer dualboot_efi "$dualboot_efi_slot"
  runtime_require_positive_integer dualboot_debian "$dualboot_debian_slot"
  if [ "$dualboot_efi_slot" -ge "$dualboot_debian_slot" ]; then
    runtime_fatal "dualboot_efi must be lower than dualboot_debian"
  fi

  DUALBOOT_ENABLED=true
  DUALBOOT_EFI_SLOT=$dualboot_efi_slot
  DUALBOOT_DEBIAN_SLOT=$dualboot_debian_slot
  RUNTIME_EFI_SLOT=$dualboot_efi_slot

  next_slot=$dualboot_debian_slot
  RUNTIME_BOOT_SLOT=$next_slot
  next_slot=$((next_slot + 1))
  RUNTIME_ROOT_SLOT=$next_slot
  next_slot=$((next_slot + 1))

  if [ -n "${DEFAULT_HOME_SLOT:-}" ]; then
    RUNTIME_HOME_SLOT=$next_slot
    next_slot=$((next_slot + 1))
  else
    RUNTIME_HOME_SLOT=
  fi

  if [ -n "${DEFAULT_POOL_SLOT:-}" ]; then
    RUNTIME_POOL_SLOT=$next_slot
    next_slot=$((next_slot + 1))
  else
    RUNTIME_POOL_SLOT=
  fi

  RUNTIME_VAR_LOG_JOURNAL_SLOT=$next_slot
  next_slot=$((next_slot + 1))
  RUNTIME_RAW_SWAP_SLOT=$next_slot
  next_slot=$((next_slot + 1))
  RUNTIME_RAW_ZRAM_SLOT=$next_slot
  RUNTIME_VAR_LIB_SHSIGNED_SLOT=

  if [ "$secure_boot_state_mode" = "luks" ]; then
    RUNTIME_VAR_LIB_SHSIGNED_SLOT=$RUNTIME_VAR_LOG_JOURNAL_SLOT
    RUNTIME_VAR_LOG_JOURNAL_SLOT=$((RUNTIME_VAR_LOG_JOURNAL_SLOT + 1))
    RUNTIME_RAW_SWAP_SLOT=$((RUNTIME_RAW_SWAP_SLOT + 1))
    RUNTIME_RAW_ZRAM_SLOT=$((RUNTIME_RAW_ZRAM_SLOT + 1))
  fi

  RUNTIME_PRESERVED_SLOTS=$(runtime_build_space_list 1 $((dualboot_debian_slot - 1)) "$dualboot_efi_slot")
}

runtime_apply_layout_from_cmdline() {
  installer_resolve_install_target_defaults
  : "${DEV_INSTALL_DISK:?DEV_INSTALL_DISK must be set}"
  F2FS_LAYOUT_VARIANT=${F2FS_LAYOUT_VARIANT:-custom}
  PARTMAN_RECIPE_NAME=${PARTMAN_RECIPE_NAME:-f2fs-layout}
  secure_boot_state_mode=$(runtime_secure_boot_state_mode)
  runtime_derive_part_prefix
  runtime_configure_qemu_pool

  dualboot_efi_raw=$(runtime_cmdline_value dualboot_efi 2>/dev/null || true)
  dualboot_debian_raw=$(runtime_cmdline_value dualboot_debian 2>/dev/null || true)
  if runtime_dualboot_class_selected; then
    [ "${F2FS_LAYOUT_VARIANT:-custom}" = desktop ] ||
      runtime_fatal "dualboot is not supported for F2FS layouts"
    [ -n "$dualboot_efi_raw" ] || runtime_fatal "classes=...,dualboot requires dualboot_efi=<integer> on the kernel cmdline"
    [ -n "$dualboot_debian_raw" ] || runtime_fatal "classes=...,dualboot requires dualboot_debian=<integer> on the kernel cmdline"
    runtime_assign_dualboot_slots "$dualboot_efi_raw" "$dualboot_debian_raw" "$secure_boot_state_mode"
  else
    if [ -n "$dualboot_efi_raw" ] || [ -n "$dualboot_debian_raw" ]; then
      runtime_fatal "dualboot_efi and dualboot_debian require classes=...,dualboot"
    fi
    runtime_assign_default_slots
  fi

  if [ "$secure_boot_state_mode" = "luks" ] && [ -z "${RUNTIME_VAR_LIB_SHSIGNED_SLOT:-}" ]; then
    RUNTIME_VAR_LIB_SHSIGNED_SLOT=$RUNTIME_VAR_LOG_JOURNAL_SLOT
    RUNTIME_VAR_LOG_JOURNAL_SLOT=$((RUNTIME_VAR_LOG_JOURNAL_SLOT + 1))
    RUNTIME_RAW_SWAP_SLOT=$((RUNTIME_RAW_SWAP_SLOT + 1))
    RUNTIME_RAW_ZRAM_SLOT=$((RUNTIME_RAW_ZRAM_SLOT + 1))
  fi
  runtime_validate_layout_slots
  RUNTIME_DEBIAN_START_SLOT=$RUNTIME_BOOT_SLOT

  DEV_PART_EFI=$(runtime_partition_path "$RUNTIME_EFI_SLOT")
  DEV_PART_BOOT=$(runtime_partition_path "$RUNTIME_BOOT_SLOT")
  DEV_PART_ROOT=$(runtime_partition_path "$RUNTIME_ROOT_SLOT")
  if [ -n "${RUNTIME_HOME_SLOT:-}" ]; then
    DEV_PART_HOME=$(runtime_partition_path "$RUNTIME_HOME_SLOT")
  else
    DEV_PART_HOME=
  fi
  if [ -n "${RUNTIME_POOL_SLOT:-}" ]; then
    DEV_PART_POOL=$(runtime_partition_path "$RUNTIME_POOL_SLOT")
  else
    DEV_PART_POOL=
  fi
  if [ -n "${RUNTIME_VAR_LIB_SHSIGNED_SLOT:-}" ]; then
    DEV_PART_VAR_LIB_SHSIGNED=$(runtime_partition_path "$RUNTIME_VAR_LIB_SHSIGNED_SLOT")
  else
    DEV_PART_VAR_LIB_SHSIGNED=
  fi
  DEV_PART_VAR_LOG_JOURNAL=$(runtime_partition_path "$RUNTIME_VAR_LOG_JOURNAL_SLOT")
  DEV_PART_RAW_SWAP=$(runtime_partition_path "$RUNTIME_RAW_SWAP_SLOT")
  DEV_PART_RAW_ZRAM=$(runtime_partition_path "$RUNTIME_RAW_ZRAM_SLOT")
  ZRAM_BACKING_RAW_DEVICE=$DEV_PART_RAW_ZRAM
  ZRAM_BACKING_MAPPER_NAME=${ZRAM_BACKING_MAPPER_NAME:-zram-writeback}
  ZRAM_BACKING_DEVICE="/dev/mapper/${ZRAM_BACKING_MAPPER_NAME}"
  SWAP_FALLBACK_RAW_DEVICE=$DEV_PART_RAW_SWAP
  SWAP_FALLBACK_MAPPER_NAME=${SWAP_FALLBACK_MAPPER_NAME:-swap-fallback}
  SWAP_FALLBACK_MAPPER="/dev/mapper/${SWAP_FALLBACK_MAPPER_NAME}"
}

runtime_compute_layout_sizing() {
  disk_total_mb=$(runtime_install_disk_size_mb)
  ram_total_mib=$(runtime_total_ram_mib)
  preserved_total_mb=$(runtime_sum_preserved_partition_sizes_mb)

  runtime_require_positive_integer SIZE_LAYOUT_SAFETY_MARGIN_MB "$SIZE_LAYOUT_SAFETY_MARGIN_MB"
  usable_budget_mb=$((disk_total_mb - preserved_total_mb - SIZE_LAYOUT_SAFETY_MARGIN_MB))
  [ "$usable_budget_mb" -gt 0 ] || runtime_fatal "usable install budget on ${DEV_INSTALL_DISK} collapsed to ${usable_budget_mb} MiB after preserved partitions and safety margin"

  runtime_require_positive_integer SIZE_PART_EFI_MB "$SIZE_PART_EFI_MB"
  runtime_require_positive_integer SIZE_PART_BOOT_MB "$SIZE_PART_BOOT_MB"
  runtime_require_positive_integer SIZE_PART_ROOT_MB "$SIZE_PART_ROOT_MB"
  runtime_require_nonnegative_integer SIZE_PART_HOME_MB "$SIZE_PART_HOME_MB"
  runtime_require_positive_integer SIZE_PART_VAR_LOG_JOURNAL_MB "$SIZE_PART_VAR_LOG_JOURNAL_MB"
  runtime_require_positive_integer SIZE_PART_RAW_SWAP_MB "$SIZE_PART_RAW_SWAP_MB"
  runtime_require_positive_integer SIZE_PART_RAW_ZRAM_MB "$SIZE_PART_RAW_ZRAM_MB"
  runtime_require_nonnegative_integer SIZE_PART_POOL_MB "$SIZE_PART_POOL_MB"
  runtime_require_nonnegative_integer SIZE_PART_VAR_LIB_SHSIGNED_MB "$SIZE_PART_VAR_LIB_SHSIGNED_MB"
  runtime_require_nonnegative_integer SIZE_PART_HOME_TARGET_MB "$SIZE_PART_HOME_TARGET_MB"

  DEV_PART_RAW_ZRAM_MB=$(runtime_compute_raw_zram_partition_mb "$usable_budget_mb" "$usable_budget_mb")
  SWAP_SIZE_MIB=$(runtime_compute_swap_partition_mib "$usable_budget_mb" "$ram_total_mib")
  DEV_PART_RAW_SWAP_MB=$SWAP_SIZE_MIB

  if [ "${DUALBOOT_ENABLED:-false}" = "true" ]; then
    DEV_PART_EFI_MB=$(runtime_get_partition_size_mb "$RUNTIME_EFI_SLOT") || \
      runtime_fatal "missing measured EFI partition size for dual-boot slot ${RUNTIME_EFI_SLOT}"
    efi_recipe_mb=0
  else
    DEV_PART_EFI_MB=$SIZE_PART_EFI_MB
    efi_recipe_mb=$DEV_PART_EFI_MB
  fi
  DEV_PART_BOOT_MB=$SIZE_PART_BOOT_MB
  DEV_PART_ROOT_MB=$SIZE_PART_ROOT_MB
  DEV_PART_HOME_MB=$SIZE_PART_HOME_MB
  DEV_PART_POOL_MB=$SIZE_PART_POOL_MB
  DEV_PART_VAR_LIB_SHSIGNED_MB=0
  if runtime_secure_boot_state_uses_luks; then
    runtime_require_positive_integer SIZE_PART_VAR_LIB_SHSIGNED_MB "$SIZE_PART_VAR_LIB_SHSIGNED_MB"
    DEV_PART_VAR_LIB_SHSIGNED_MB=$SIZE_PART_VAR_LIB_SHSIGNED_MB
  fi
  DEV_PART_VAR_LOG_JOURNAL_MB=$SIZE_PART_VAR_LOG_JOURNAL_MB

  base_total_mb=$((efi_recipe_mb + DEV_PART_BOOT_MB + DEV_PART_ROOT_MB + DEV_PART_HOME_MB + DEV_PART_POOL_MB + DEV_PART_VAR_LIB_SHSIGNED_MB + DEV_PART_VAR_LOG_JOURNAL_MB + DEV_PART_RAW_SWAP_MB + DEV_PART_RAW_ZRAM_MB))
  if [ "$base_total_mb" -gt "$usable_budget_mb" ]; then
    overflow_mb=$((base_total_mb - usable_budget_mb))

    pool_floor_mb=$(runtime_min "$DEV_PART_POOL_MB" "${SIZE_PART_POOL_MIN_MB:-0}")
    home_floor_mb=$(runtime_min "$DEV_PART_HOME_MB" "${SIZE_PART_HOME_MIN_MB:-0}")
    var_log_journal_floor_mb=$(runtime_min "$DEV_PART_VAR_LOG_JOURNAL_MB" "${SIZE_PART_VAR_LOG_JOURNAL_MIN_MB:-256}")
    efi_floor_mb=$(runtime_min "$DEV_PART_EFI_MB" "${SIZE_PART_EFI_MIN_MB:-256}")
    boot_floor_mb=$(runtime_min "$DEV_PART_BOOT_MB" "${SIZE_PART_BOOT_MIN_MB:-512}")
    root_floor_mb=$(runtime_min "$DEV_PART_ROOT_MB" "${SIZE_PART_ROOT_MIN_MB:-4096}")

    runtime_apply_fill_result DEV_PART_POOL_MB overflow_mb \
      "$(runtime_shrink_partition_to_floor "$DEV_PART_POOL_MB" "$pool_floor_mb" "$overflow_mb")"
    runtime_apply_fill_result DEV_PART_HOME_MB overflow_mb \
      "$(runtime_shrink_partition_to_floor "$DEV_PART_HOME_MB" "$home_floor_mb" "$overflow_mb")"
    runtime_apply_fill_result DEV_PART_VAR_LOG_JOURNAL_MB overflow_mb \
      "$(runtime_shrink_partition_to_floor "$DEV_PART_VAR_LOG_JOURNAL_MB" "$var_log_journal_floor_mb" "$overflow_mb")"
    runtime_apply_fill_result DEV_PART_EFI_MB overflow_mb \
      "$(runtime_shrink_partition_to_floor "$DEV_PART_EFI_MB" "$efi_floor_mb" "$overflow_mb")"
    runtime_apply_fill_result DEV_PART_BOOT_MB overflow_mb \
      "$(runtime_shrink_partition_to_floor "$DEV_PART_BOOT_MB" "$boot_floor_mb" "$overflow_mb")"
    runtime_apply_fill_result DEV_PART_ROOT_MB overflow_mb \
      "$(runtime_shrink_partition_to_floor "$DEV_PART_ROOT_MB" "$root_floor_mb" "$overflow_mb")"

    base_total_mb=$((DEV_PART_EFI_MB + DEV_PART_BOOT_MB + DEV_PART_ROOT_MB + DEV_PART_HOME_MB + DEV_PART_POOL_MB + DEV_PART_VAR_LIB_SHSIGNED_MB + DEV_PART_VAR_LOG_JOURNAL_MB + DEV_PART_RAW_SWAP_MB + DEV_PART_RAW_ZRAM_MB))
  fi
  if [ "$base_total_mb" -gt "$usable_budget_mb" ]; then
    runtime_fatal "disk budget ${usable_budget_mb} MiB is too small for the F2FS minimum layout (${base_total_mb} MiB)"
  fi

  elastic_budget_mb=$((usable_budget_mb - base_total_mb))

  if [ "$DEV_PART_HOME_MB" -gt 0 ]; then
    runtime_apply_fill_result DEV_PART_HOME_MB elastic_budget_mb \
      "$(runtime_fill_partition_to_target "$DEV_PART_HOME_MB" "$SIZE_PART_HOME_TARGET_MB" "$elastic_budget_mb")"
  fi
  DEV_PART_ROOT_MB=$((DEV_PART_ROOT_MB + elastic_budget_mb))

  RUNTIME_DISK_TOTAL_MB=$disk_total_mb
  RUNTIME_LAYOUT_SAFETY_MARGIN_MB=$SIZE_LAYOUT_SAFETY_MARGIN_MB
  RUNTIME_PRESERVED_TOTAL_MB=$preserved_total_mb
  RUNTIME_USABLE_BUDGET_MB=$usable_budget_mb
  RUNTIME_BASE_LAYOUT_MB=$base_total_mb
  RUNTIME_INSTALL_RAM_MIB=$ram_total_mib
}

runtime_write_runtime_env() {
  dest=$1
  runtime_ensure_system_identity
  runtime_apply_layout_from_cmdline
  runtime_compute_layout_sizing
  runtime_validate_root_home_crypto_layout
  root_home_crypto_enabled=false
  if runtime_root_home_crypto_enabled; then
    root_home_crypto_enabled=true
  fi
  runtime_prepare_parent_dir "$dest" 0700
  {
    printf 'SYSTEM_PREFIX=%s\n' "$(runtime_shell_quote "$SYSTEM_PREFIX")"
    printf 'SYSTEM_HOSTNAME=%s\n' "$(runtime_shell_quote "$SYSTEM_HOSTNAME")"
    printf 'SYSTEM_DOMAIN=%s\n' "$(runtime_shell_quote "$SYSTEM_DOMAIN")"
    printf 'DUALBOOT_ENABLED=%s\n' "$(runtime_shell_quote "${DUALBOOT_ENABLED:-false}")"
    printf 'ROOT_HOME_CRYPTO_ENABLED=%s\n' "$(runtime_shell_quote "$root_home_crypto_enabled")"
    printf 'ROOT_CRYPT_NAME=%s\n' "$(runtime_shell_quote cryptroot)"
    printf 'HOME_CRYPT_NAME=%s\n' "$(runtime_shell_quote crypthome)"
    printf 'DUALBOOT_EFI_SLOT=%s\n' "$(runtime_shell_quote "${DUALBOOT_EFI_SLOT:-}")"
    printf 'DUALBOOT_DEBIAN_SLOT=%s\n' "$(runtime_shell_quote "${DUALBOOT_DEBIAN_SLOT:-}")"
    printf 'RUNTIME_PRESERVED_SLOTS=%s\n' "$(runtime_shell_quote "${RUNTIME_PRESERVED_SLOTS:-}")"
    printf 'F2FS_LAYOUT_VARIANT=%s\n' "$(runtime_shell_quote "$F2FS_LAYOUT_VARIANT")"
    printf 'F2FS_QEMU_POOL_ENABLED=%s\n' "$(runtime_shell_quote "${F2FS_QEMU_POOL_ENABLED:-false}")"
    printf 'PARTMAN_RECIPE_NAME=%s\n' "$(runtime_shell_quote "$PARTMAN_RECIPE_NAME")"
    printf 'DEV_INSTALL_DISK=%s\n' "$(runtime_shell_quote "$DEV_INSTALL_DISK")"
    printf 'DEV_PART_PREFIX=%s\n' "$(runtime_shell_quote "$DEV_PART_PREFIX")"
    printf 'DEV_PART_EFI=%s\n' "$(runtime_shell_quote "$DEV_PART_EFI")"
    printf 'DEV_PART_BOOT=%s\n' "$(runtime_shell_quote "$DEV_PART_BOOT")"
    printf 'DEV_PART_ROOT=%s\n' "$(runtime_shell_quote "$DEV_PART_ROOT")"
    printf 'DEV_PART_HOME=%s\n' "$(runtime_shell_quote "${DEV_PART_HOME:-}")"
    printf 'DEV_PART_POOL=%s\n' "$(runtime_shell_quote "${DEV_PART_POOL:-}")"
    printf 'RUNTIME_VAR_LIB_SHSIGNED_SLOT=%s\n' "$(runtime_shell_quote "${RUNTIME_VAR_LIB_SHSIGNED_SLOT:-}")"
    printf 'DEV_PART_VAR_LIB_SHSIGNED=%s\n' "$(runtime_shell_quote "${DEV_PART_VAR_LIB_SHSIGNED:-}")"
    printf 'DEV_PART_VAR_LOG_JOURNAL=%s\n' "$(runtime_shell_quote "$DEV_PART_VAR_LOG_JOURNAL")"
    printf 'DEV_PART_RAW_SWAP=%s\n' "$(runtime_shell_quote "$DEV_PART_RAW_SWAP")"
    printf 'DEV_PART_RAW_ZRAM=%s\n' "$(runtime_shell_quote "$DEV_PART_RAW_ZRAM")"
    printf 'DEV_PART_EFI_MB=%s\n' "$(runtime_shell_quote "$DEV_PART_EFI_MB")"
    printf 'DEV_PART_BOOT_MB=%s\n' "$(runtime_shell_quote "$DEV_PART_BOOT_MB")"
    printf 'DEV_PART_ROOT_MB=%s\n' "$(runtime_shell_quote "$DEV_PART_ROOT_MB")"
    printf 'DEV_PART_HOME_MB=%s\n' "$(runtime_shell_quote "$DEV_PART_HOME_MB")"
    printf 'DEV_PART_POOL_MB=%s\n' "$(runtime_shell_quote "$DEV_PART_POOL_MB")"
    printf 'DEV_PART_VAR_LIB_SHSIGNED_MB=%s\n' "$(runtime_shell_quote "$DEV_PART_VAR_LIB_SHSIGNED_MB")"
    printf 'DEV_PART_VAR_LOG_JOURNAL_MB=%s\n' "$(runtime_shell_quote "$DEV_PART_VAR_LOG_JOURNAL_MB")"
    printf 'DEV_PART_RAW_SWAP_MB=%s\n' "$(runtime_shell_quote "$DEV_PART_RAW_SWAP_MB")"
    printf 'DEV_PART_RAW_ZRAM_MB=%s\n' "$(runtime_shell_quote "$DEV_PART_RAW_ZRAM_MB")"
    printf 'SWAP_SIZE_MIB=%s\n' "$(runtime_shell_quote "$SWAP_SIZE_MIB")"
    printf 'RUNTIME_DISK_TOTAL_MB=%s\n' "$(runtime_shell_quote "$RUNTIME_DISK_TOTAL_MB")"
    printf 'RUNTIME_LAYOUT_SAFETY_MARGIN_MB=%s\n' "$(runtime_shell_quote "$RUNTIME_LAYOUT_SAFETY_MARGIN_MB")"
    printf 'RUNTIME_PRESERVED_TOTAL_MB=%s\n' "$(runtime_shell_quote "${RUNTIME_PRESERVED_TOTAL_MB:-0}")"
    printf 'RUNTIME_USABLE_BUDGET_MB=%s\n' "$(runtime_shell_quote "$RUNTIME_USABLE_BUDGET_MB")"
    printf 'RUNTIME_BASE_LAYOUT_MB=%s\n' "$(runtime_shell_quote "$RUNTIME_BASE_LAYOUT_MB")"
    printf 'RUNTIME_INSTALL_RAM_MIB=%s\n' "$(runtime_shell_quote "$RUNTIME_INSTALL_RAM_MIB")"
    printf 'RUNTIME_DEBIAN_START_SLOT=%s\n' "$(runtime_shell_quote "$RUNTIME_DEBIAN_START_SLOT")"
    printf 'ZRAM_BACKING_RAW_DEVICE=%s\n' "$(runtime_shell_quote "$ZRAM_BACKING_RAW_DEVICE")"
    printf 'ZRAM_BACKING_MAPPER_NAME=%s\n' "$(runtime_shell_quote "$ZRAM_BACKING_MAPPER_NAME")"
    printf 'ZRAM_BACKING_DEVICE=%s\n' "$(runtime_shell_quote "$ZRAM_BACKING_DEVICE")"
    printf 'SWAP_FALLBACK_RAW_DEVICE=%s\n' "$(runtime_shell_quote "$SWAP_FALLBACK_RAW_DEVICE")"
    printf 'SWAP_FALLBACK_MAPPER_NAME=%s\n' "$(runtime_shell_quote "$SWAP_FALLBACK_MAPPER_NAME")"
    printf 'SWAP_FALLBACK_MAPPER=%s\n' "$(runtime_shell_quote "$SWAP_FALLBACK_MAPPER")"
  } >"$dest"
  chmod 0600 "$dest"
}

runtime_emit_debian_partition_recipe() {
  # Keep the parted-visible filesystem token on ext4 while the explicit
  # filesystem stanza drives the custom partman F2FS backend.
  cat <<EOF
    ${DEV_PART_BOOT_MB} ${DEV_PART_BOOT_MB} ${DEV_PART_BOOT_MB} ext4
        \$primary{ } \$bootable{ }
        method{ format } format{ }
        use_filesystem{ } filesystem{ ext4 }
        mountpoint{ /boot }
    .
EOF
  if runtime_root_home_crypto_enabled; then
    cat <<EOF
    ${DEV_PART_ROOT_MB} ${DEV_PART_ROOT_MB} ${DEV_PART_ROOT_MB} ext4
        method{ crypto } format{ }
        crypto_type{ luks }
        cipher{ aes }
        keysize{ 512 }
        ivalgorithm{ xts-plain64 }
        keytype{ passphrase }
        keyhash{ sha256 }
        use_filesystem{ } filesystem{ f2fs }
        mountpoint{ / }
    .
EOF
  else
    cat <<EOF
    ${DEV_PART_ROOT_MB} ${DEV_PART_ROOT_MB} ${DEV_PART_ROOT_MB} ext4
        method{ format } format{ }
        use_filesystem{ } filesystem{ f2fs }
        mountpoint{ / }
    .
EOF
  fi
  if [ "$DEV_PART_HOME_MB" -gt 0 ]; then
    if runtime_root_home_crypto_enabled; then
      cat <<EOF
    ${DEV_PART_HOME_MB} ${DEV_PART_HOME_MB} ${DEV_PART_HOME_MB} free
        method{ keep }
    .
EOF
    else
      cat <<EOF
    ${DEV_PART_HOME_MB} ${DEV_PART_HOME_MB} ${DEV_PART_HOME_MB} ext4
        method{ format } format{ }
        use_filesystem{ } filesystem{ f2fs }
        mountpoint{ /home }
    .
EOF
    fi
  fi
  if [ "$DEV_PART_POOL_MB" -gt 0 ]; then
    cat <<EOF
    ${DEV_PART_POOL_MB} ${DEV_PART_POOL_MB} ${DEV_PART_POOL_MB} ext4
        method{ format } format{ }
        use_filesystem{ } filesystem{ ext4 }
        mountpoint{ /pool }
    .
EOF
  fi
  if [ "$DEV_PART_VAR_LIB_SHSIGNED_MB" -gt 0 ]; then
    cat <<EOF
    ${DEV_PART_VAR_LIB_SHSIGNED_MB} ${DEV_PART_VAR_LIB_SHSIGNED_MB} ${DEV_PART_VAR_LIB_SHSIGNED_MB} free
        method{ keep }
    .
EOF
  fi
  cat <<EOF
    ${DEV_PART_VAR_LOG_JOURNAL_MB} ${DEV_PART_VAR_LOG_JOURNAL_MB} ${DEV_PART_VAR_LOG_JOURNAL_MB} ext4
        method{ format } format{ }
        use_filesystem{ } filesystem{ ext4 }
        mountpoint{ /var/log/journal }
    .
    ${DEV_PART_RAW_SWAP_MB} ${DEV_PART_RAW_SWAP_MB} ${DEV_PART_RAW_SWAP_MB} free
        method{ keep }
    .
    ${DEV_PART_RAW_ZRAM_MB} ${DEV_PART_RAW_ZRAM_MB} 1000000000 free
        method{ keep }
    .
EOF
}

runtime_emit_default_recipe() {
  cat <<EOF
${PARTMAN_RECIPE_NAME} ::
    ${DEV_PART_EFI_MB} ${DEV_PART_EFI_MB} ${DEV_PART_EFI_MB} free
        \$iflabel{ gpt } \$primary{ } \$reusemethod{ } \$bootable{ }
        method{ efi } format{ }
    .
EOF
  runtime_emit_debian_partition_recipe
}

runtime_emit_dualboot_recipe() {
  cat <<EOF
${PARTMAN_RECIPE_NAME} ::
EOF
  runtime_emit_debian_partition_recipe
}

runtime_write_expert_recipe() {
  dest=$1
  runtime_apply_layout_from_cmdline
  runtime_compute_layout_sizing
  runtime_prepare_parent_dir "$dest" 0700
  if [ "${DUALBOOT_ENABLED:-false}" = "true" ]; then
    runtime_emit_dualboot_recipe >"$dest"
  else
    runtime_emit_default_recipe >"$dest"
  fi
  chmod 0600 "$dest"
}

runtime_write_partman_fragment() {
  dest=$1
  recipe_file=$2
  runtime_prepare_parent_dir "$dest" 0700
  {
    printf 'd-i partman/default_filesystem string ext4\n'
    printf 'd-i partman/default_filesystem seen true\n'
    printf 'd-i partman-efi/confirm boolean true\n'
    printf 'd-i partman-efi/confirm seen true\n'
    if [ "${DUALBOOT_ENABLED:-false}" = "true" ] || runtime_root_home_crypto_enabled; then
      printf 'd-i partman-auto/init_automatically_partition select installer_target_free\n'
      printf 'd-i partman-auto/init_automatically_partition seen true\n'
      printf 'd-i partman-basicmethods/method_only boolean false\n'
      printf 'd-i partman-basicmethods/method_only seen true\n'
    else
      printf 'd-i partman-auto/disk string %s\n' "$DEV_INSTALL_DISK"
      printf 'd-i partman-auto/disk seen true\n'
      printf 'd-i partman-partitioning/choose_label select gpt\n'
      printf 'd-i partman-partitioning/choose_label seen true\n'
      printf 'd-i partman-partitioning/default_label string gpt\n'
      printf 'd-i partman-partitioning/default_label seen true\n'
      printf 'd-i partman-partitioning/confirm_new_label boolean true\n'
      printf 'd-i partman-partitioning/confirm_new_label seen true\n'
      printf 'd-i partman-partitioning/confirm_write_new_label boolean true\n'
      printf 'd-i partman-partitioning/confirm_write_new_label seen true\n'
      printf 'd-i partman/confirm_write_new_label boolean true\n'
      printf 'd-i partman/confirm_write_new_label seen true\n'
    fi
    if [ "${DUALBOOT_ENABLED:-false}" != "true" ] && ! runtime_root_home_crypto_enabled; then
      printf 'd-i partman-auto/method string regular\n'
      printf 'd-i partman-auto/method seen true\n'
    fi
    printf 'd-i partman-auto/choose_recipe select %s\n' "$PARTMAN_RECIPE_NAME"
    printf 'd-i partman-auto/choose_recipe seen true\n'
    printf 'd-i partman-auto/expert_recipe_file string %s\n' "$recipe_file"
    printf 'd-i partman-auto/expert_recipe_file seen true\n'
    printf 'd-i partman/choose_partition select finish\n'
    printf 'd-i partman/choose_partition seen true\n'
    printf 'd-i partman/confirm boolean true\n'
    printf 'd-i partman/confirm seen true\n'
    printf 'd-i partman/confirm_nochanges boolean true\n'
    printf 'd-i partman/confirm_nochanges seen true\n'
    printf 'd-i partman/confirm_nooverwrite boolean true\n'
    printf 'd-i partman/confirm_nooverwrite seen true\n'
    printf 'd-i partman-auto/confirm boolean true\n'
    printf 'd-i partman-auto/confirm seen true\n'
  } >"$dest"
  chmod 0644 "$dest"
}

runtime_write_identity_answers() {
  dest=$1
  runtime_ensure_system_identity
  runtime_prepare_parent_dir "$dest" 0700
  {
    printf 'd-i netcfg/get_hostname string %s\n' "$SYSTEM_HOSTNAME"
    printf 'd-i netcfg/get_hostname seen true\n'
    printf 'd-i netcfg/get_domain string %s\n' "$SYSTEM_DOMAIN"
    printf 'd-i netcfg/get_domain seen true\n'
    printf 'd-i netcfg/hostname string %s\n' "$SYSTEM_HOSTNAME"
    printf 'd-i netcfg/hostname seen true\n'
  } >"$dest"
  chmod 0600 "$dest"
}

runtime_seed_identity_answers() {
  runtime_seed_generated_answers runtime_write_identity_answers
}
