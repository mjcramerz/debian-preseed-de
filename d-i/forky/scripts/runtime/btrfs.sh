#!/bin/sh
# Btrfs-family runtime layout helpers.
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
  mode=${secure_boot_mode:-${secure_boot_state_mode:-luks}}
  case "$mode" in
    luks|direct)
      printf '%s\n' "$mode"
      ;;
    *)
      runtime_fatal "SECURE_BOOT_MODE/SECURE_BOOT_STATE_MODE must be 'luks' or 'direct', got '${mode}'"
      return 1
      ;;
  esac
}

runtime_crypto_answers_required() {
  runtime_root_home_crypto_enabled || [ "$(runtime_secure_boot_state_mode)" = "luks" ]
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

runtime_compute_layout_sizing() {
  runtime_validate_partition_sizes

  disk_total_mb=$(runtime_install_disk_size_mb)
  ram_total_mib=$(runtime_total_ram_mib)
  preserved_total_mb=$(runtime_sum_preserved_partition_sizes_mb)

  runtime_require_positive_integer SIZE_LAYOUT_SAFETY_MARGIN_MB "${SIZE_LAYOUT_SAFETY_MARGIN_MB:-}"
  usable_budget_mb=$((disk_total_mb - preserved_total_mb - SIZE_LAYOUT_SAFETY_MARGIN_MB))
  if [ "$usable_budget_mb" -le 0 ]; then
    runtime_fatal "usable install budget on ${DEV_INSTALL_DISK} collapsed to ${usable_budget_mb} MiB after preserved partitions and safety margin"
  fi

  runtime_require_positive_integer SIZE_PART_ROOT_TARGET_MB "${SIZE_PART_ROOT_TARGET_MB:-}"
  runtime_require_positive_integer SIZE_PART_HOME_TARGET_MB "${SIZE_PART_HOME_TARGET_MB:-}"
  runtime_require_positive_integer SIZE_PART_OPT_TARGET_MB "${SIZE_PART_OPT_TARGET_MB:-}"
  runtime_require_positive_integer SIZE_PART_DATA_TARGET_MB "${SIZE_PART_DATA_TARGET_MB:-}"
  runtime_require_positive_integer SIZE_PART_POOL_TARGET_MB "${SIZE_PART_POOL_TARGET_MB:-$SIZE_PART_POOL_MB}"
  runtime_require_positive_integer SIZE_PART_VAR_TMP_TARGET_MB "${SIZE_PART_VAR_TMP_TARGET_MB:-}"
  raw_zram_mb=$(runtime_compute_raw_zram_partition_mb "$usable_budget_mb" "$usable_budget_mb")
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
  DEV_PART_OPT_MB=$SIZE_PART_OPT_MB
  DEV_PART_DATA_MB=$SIZE_PART_DATA_MB
  DEV_PART_POOL_MB=$SIZE_PART_POOL_MB
  DEV_PART_VAR_TMP_MB=$SIZE_PART_VAR_TMP_MB
  DEV_PART_VAR_LIB_SHSIGNED_MB=$SIZE_PART_VAR_LIB_SHSIGNED_MB
  DEV_PART_VAR_LOG_JOURNAL_MB=$SIZE_PART_VAR_LOG_JOURNAL_MB
  DEV_PART_RAW_ZRAM_MB=$raw_zram_mb

  [ "$SIZE_PART_ROOT_TARGET_MB" -ge "$DEV_PART_ROOT_MB" ] || runtime_fatal "SIZE_PART_ROOT_TARGET_MB must be >= SIZE_PART_ROOT_MB"
  [ "$SIZE_PART_HOME_TARGET_MB" -ge "$DEV_PART_HOME_MB" ] || runtime_fatal "SIZE_PART_HOME_TARGET_MB must be >= SIZE_PART_HOME_MB"
  [ "$SIZE_PART_OPT_TARGET_MB" -ge "$DEV_PART_OPT_MB" ] || runtime_fatal "SIZE_PART_OPT_TARGET_MB must be >= SIZE_PART_OPT_MB"
  [ "$SIZE_PART_DATA_TARGET_MB" -ge "$DEV_PART_DATA_MB" ] || runtime_fatal "SIZE_PART_DATA_TARGET_MB must be >= SIZE_PART_DATA_MB"
  [ "${SIZE_PART_POOL_TARGET_MB:-$SIZE_PART_POOL_MB}" -ge "$DEV_PART_POOL_MB" ] || runtime_fatal "SIZE_PART_POOL_TARGET_MB must be >= SIZE_PART_POOL_MB"
  [ "$SIZE_PART_VAR_TMP_TARGET_MB" -ge "$DEV_PART_VAR_TMP_MB" ] || runtime_fatal "SIZE_PART_VAR_TMP_TARGET_MB must be >= SIZE_PART_VAR_TMP_MB"

  base_total_mb=$((efi_recipe_mb + DEV_PART_BOOT_MB + DEV_PART_ROOT_MB + DEV_PART_HOME_MB + DEV_PART_OPT_MB + DEV_PART_DATA_MB + DEV_PART_POOL_MB + DEV_PART_VAR_TMP_MB + DEV_PART_VAR_LIB_SHSIGNED_MB + DEV_PART_VAR_LOG_JOURNAL_MB + DEV_PART_RAW_SWAP_MB + DEV_PART_RAW_ZRAM_MB))
  if [ "$base_total_mb" -gt "$usable_budget_mb" ]; then
    overflow_mb=$((base_total_mb - usable_budget_mb))

    pool_floor_mb=$(runtime_min "$DEV_PART_POOL_MB" "${SIZE_PART_POOL_MIN_MB:-1024}")
    data_floor_mb=$(runtime_min "$DEV_PART_DATA_MB" "${SIZE_PART_DATA_MIN_MB:-1024}")
    home_floor_mb=$(runtime_min "$DEV_PART_HOME_MB" "${SIZE_PART_HOME_MIN_MB:-1024}")
    opt_floor_mb=$(runtime_min "$DEV_PART_OPT_MB" "${SIZE_PART_OPT_MIN_MB:-512}")
    var_tmp_floor_mb=$(runtime_min "$DEV_PART_VAR_TMP_MB" "${SIZE_PART_VAR_TMP_MIN_MB:-512}")
    var_log_journal_floor_mb=$(runtime_min "$DEV_PART_VAR_LOG_JOURNAL_MB" "${SIZE_PART_VAR_LOG_JOURNAL_MIN_MB:-256}")
    boot_floor_mb=$(runtime_min "$DEV_PART_BOOT_MB" "${SIZE_PART_BOOT_MIN_MB:-512}")
    root_floor_mb=$(runtime_min "$DEV_PART_ROOT_MB" "${SIZE_PART_ROOT_MIN_MB:-4096}")
    if [ "${DUALBOOT_ENABLED:-false}" = true ]; then
      efi_floor_mb=$DEV_PART_EFI_MB
    else
      efi_floor_mb=$(runtime_min "$DEV_PART_EFI_MB" "${SIZE_PART_EFI_MIN_MB:-256}")
    fi

    runtime_apply_fill_result DEV_PART_POOL_MB overflow_mb \
      "$(runtime_shrink_partition_to_floor "$DEV_PART_POOL_MB" "$pool_floor_mb" "$overflow_mb")"
    runtime_apply_fill_result DEV_PART_DATA_MB overflow_mb \
      "$(runtime_shrink_partition_to_floor "$DEV_PART_DATA_MB" "$data_floor_mb" "$overflow_mb")"
    runtime_apply_fill_result DEV_PART_HOME_MB overflow_mb \
      "$(runtime_shrink_partition_to_floor "$DEV_PART_HOME_MB" "$home_floor_mb" "$overflow_mb")"
    runtime_apply_fill_result DEV_PART_OPT_MB overflow_mb \
      "$(runtime_shrink_partition_to_floor "$DEV_PART_OPT_MB" "$opt_floor_mb" "$overflow_mb")"
    runtime_apply_fill_result DEV_PART_VAR_TMP_MB overflow_mb \
      "$(runtime_shrink_partition_to_floor "$DEV_PART_VAR_TMP_MB" "$var_tmp_floor_mb" "$overflow_mb")"
    runtime_apply_fill_result DEV_PART_VAR_LOG_JOURNAL_MB overflow_mb \
      "$(runtime_shrink_partition_to_floor "$DEV_PART_VAR_LOG_JOURNAL_MB" "$var_log_journal_floor_mb" "$overflow_mb")"
    if [ "${DUALBOOT_ENABLED:-false}" != true ]; then
      runtime_apply_fill_result DEV_PART_EFI_MB overflow_mb \
        "$(runtime_shrink_partition_to_floor "$DEV_PART_EFI_MB" "$efi_floor_mb" "$overflow_mb")"
      efi_recipe_mb=$DEV_PART_EFI_MB
    fi
    runtime_apply_fill_result DEV_PART_BOOT_MB overflow_mb \
      "$(runtime_shrink_partition_to_floor "$DEV_PART_BOOT_MB" "$boot_floor_mb" "$overflow_mb")"
    runtime_apply_fill_result DEV_PART_ROOT_MB overflow_mb \
      "$(runtime_shrink_partition_to_floor "$DEV_PART_ROOT_MB" "$root_floor_mb" "$overflow_mb")"

    base_total_mb=$((efi_recipe_mb + DEV_PART_BOOT_MB + DEV_PART_ROOT_MB + DEV_PART_HOME_MB + DEV_PART_OPT_MB + DEV_PART_DATA_MB + DEV_PART_POOL_MB + DEV_PART_VAR_TMP_MB + DEV_PART_VAR_LIB_SHSIGNED_MB + DEV_PART_VAR_LOG_JOURNAL_MB + DEV_PART_RAW_SWAP_MB + DEV_PART_RAW_ZRAM_MB))
  fi
  if [ "$base_total_mb" -gt "$usable_budget_mb" ]; then
    runtime_fatal "disk budget ${usable_budget_mb} MiB is too small for the minimum Debian layout (${base_total_mb} MiB)"
  fi

  elastic_budget_mb=$((usable_budget_mb - base_total_mb))

  runtime_apply_fill_result DEV_PART_ROOT_MB elastic_budget_mb \
    "$(runtime_fill_partition_to_target "$DEV_PART_ROOT_MB" "$SIZE_PART_ROOT_TARGET_MB" "$elastic_budget_mb")"

  runtime_apply_fill_result DEV_PART_HOME_MB elastic_budget_mb \
    "$(runtime_fill_partition_to_target "$DEV_PART_HOME_MB" "$SIZE_PART_HOME_TARGET_MB" "$elastic_budget_mb")"

  runtime_apply_fill_result DEV_PART_OPT_MB elastic_budget_mb \
    "$(runtime_fill_partition_to_target "$DEV_PART_OPT_MB" "$SIZE_PART_OPT_TARGET_MB" "$elastic_budget_mb")"

  runtime_apply_fill_result DEV_PART_VAR_TMP_MB elastic_budget_mb \
    "$(runtime_fill_partition_to_target "$DEV_PART_VAR_TMP_MB" "$SIZE_PART_VAR_TMP_TARGET_MB" "$elastic_budget_mb")"

  runtime_apply_fill_result DEV_PART_DATA_MB elastic_budget_mb \
    "$(runtime_fill_partition_to_target "$DEV_PART_DATA_MB" "$SIZE_PART_DATA_TARGET_MB" "$elastic_budget_mb")"

  runtime_apply_fill_result DEV_PART_POOL_MB elastic_budget_mb \
    "$(runtime_fill_partition_to_target "$DEV_PART_POOL_MB" "${SIZE_PART_POOL_TARGET_MB:-$SIZE_PART_POOL_MB}" "$elastic_budget_mb")"

  DEV_PART_ROOT_MB=$((DEV_PART_ROOT_MB + elastic_budget_mb))

  RUNTIME_DISK_TOTAL_MB=$disk_total_mb
  RUNTIME_LAYOUT_SAFETY_MARGIN_MB=$SIZE_LAYOUT_SAFETY_MARGIN_MB
  RUNTIME_PRESERVED_TOTAL_MB=$preserved_total_mb
  RUNTIME_USABLE_BUDGET_MB=$usable_budget_mb
  RUNTIME_BASE_LAYOUT_MB=$base_total_mb
  RUNTIME_INSTALL_RAM_MIB=$ram_total_mib
}

runtime_modules_load_file_has_denied_modules() {
  denylist=$1
  src=$2
  [ -r "$src" ] || return 1
  while IFS= read -r line || [ -n "$line" ]; do
    line=$(printf '%s' "$line" | sed 's/[[:space:]]*#.*$//; s/^[[:space:]]*//; s/[[:space:]]*$//')
    [ -n "$line" ] || continue
    module_name=${line%%[[:space:]]*}
    case " $denylist " in
      *" ${module_name} "*) return 0 ;;
    esac
  done <"$src"
  return 1
}

runtime_filter_modules_load_file() {
  denylist=$1
  src=$2
  dest=$3
  [ -r "$src" ] || runtime_fatal "modules-load file is not readable: ${src}"

  install -d -m 0755 "$(dirname "$dest")"
  tmp="${dest}.tmp.$$"
  : >"$tmp"
  while IFS= read -r line || [ -n "$line" ]; do
    trimmed_line=$(printf '%s' "$line" | sed 's/[[:space:]]*#.*$//; s/^[[:space:]]*//; s/[[:space:]]*$//')
    if [ -n "$trimmed_line" ]; then
      module_name=${trimmed_line%%[[:space:]]*}
      case " $denylist " in
        *" ${module_name} "*) continue ;;
      esac
    fi
    printf '%s\n' "$line" >>"$tmp" || {
      rm -f "$tmp"
      runtime_fatal "failed to filter modules-load file: ${src}"
    }
  done <"$src"

  install -m 0644 "$tmp" "$dest"
  rm -f "$tmp"
}

runtime_validate_partition_sizes() {
  runtime_require_positive_integer DEV_PART_EFI_MB "${DEV_PART_EFI_MB:-}"
  runtime_require_positive_integer DEV_PART_BOOT_MB "${DEV_PART_BOOT_MB:-}"
  runtime_require_positive_integer DEV_PART_ROOT_MB "${DEV_PART_ROOT_MB:-}"
  runtime_require_positive_integer DEV_PART_HOME_MB "${DEV_PART_HOME_MB:-}"
  runtime_require_positive_integer DEV_PART_OPT_MB "${DEV_PART_OPT_MB:-}"
  runtime_require_positive_integer DEV_PART_DATA_MB "${DEV_PART_DATA_MB:-}"
  runtime_require_positive_integer DEV_PART_POOL_MB "${DEV_PART_POOL_MB:-}"
  runtime_require_positive_integer DEV_PART_VAR_TMP_MB "${DEV_PART_VAR_TMP_MB:-}"
  runtime_require_positive_integer DEV_PART_VAR_LIB_SHSIGNED_MB "${DEV_PART_VAR_LIB_SHSIGNED_MB:-}"
  runtime_require_positive_integer DEV_PART_VAR_LOG_JOURNAL_MB "${DEV_PART_VAR_LOG_JOURNAL_MB:-}"
  runtime_require_positive_integer DEV_PART_RAW_SWAP_MB "${DEV_PART_RAW_SWAP_MB:-}"
  runtime_require_positive_integer DEV_PART_RAW_ZRAM_MB "${DEV_PART_RAW_ZRAM_MB:-}"
}

runtime_load_default_slots_from_env() {
  if [ -n "${DEFAULT_EFI_SLOT:-}" ]; then
    runtime_require_positive_integer DEFAULT_EFI_SLOT "$DEFAULT_EFI_SLOT"
  else
    DEFAULT_EFI_SLOT=$(runtime_partition_slot_from_path DEV_PART_EFI "${DEV_PART_EFI}")
  fi
  if [ -n "${DEFAULT_BOOT_SLOT:-}" ]; then
    runtime_require_positive_integer DEFAULT_BOOT_SLOT "$DEFAULT_BOOT_SLOT"
  else
    DEFAULT_BOOT_SLOT=$(runtime_partition_slot_from_path DEV_PART_BOOT "${DEV_PART_BOOT}")
  fi
  if [ -n "${DEFAULT_ROOT_SLOT:-}" ]; then
    runtime_require_positive_integer DEFAULT_ROOT_SLOT "$DEFAULT_ROOT_SLOT"
  else
    DEFAULT_ROOT_SLOT=$(runtime_partition_slot_from_path DEV_PART_ROOT "${DEV_PART_ROOT}")
  fi
  if [ -n "${DEFAULT_HOME_SLOT:-}" ]; then
    runtime_require_positive_integer DEFAULT_HOME_SLOT "$DEFAULT_HOME_SLOT"
  else
    DEFAULT_HOME_SLOT=$(runtime_partition_slot_from_path DEV_PART_HOME "${DEV_PART_HOME}")
  fi
  if [ -n "${DEFAULT_OPT_SLOT:-}" ]; then
    runtime_require_positive_integer DEFAULT_OPT_SLOT "$DEFAULT_OPT_SLOT"
  else
    DEFAULT_OPT_SLOT=$(runtime_partition_slot_from_path DEV_PART_OPT "${DEV_PART_OPT}")
  fi
  if [ -n "${DEFAULT_DATA_SLOT:-}" ]; then
    runtime_require_positive_integer DEFAULT_DATA_SLOT "$DEFAULT_DATA_SLOT"
  else
    DEFAULT_DATA_SLOT=$(runtime_partition_slot_from_path DEV_PART_DATA "${DEV_PART_DATA}")
  fi
  if [ -n "${DEFAULT_POOL_SLOT:-}" ]; then
    runtime_require_positive_integer DEFAULT_POOL_SLOT "$DEFAULT_POOL_SLOT"
  else
    DEFAULT_POOL_SLOT=$(runtime_partition_slot_from_path DEV_PART_POOL "${DEV_PART_POOL}")
  fi
  if [ -n "${DEFAULT_VAR_TMP_SLOT:-}" ]; then
    runtime_require_positive_integer DEFAULT_VAR_TMP_SLOT "$DEFAULT_VAR_TMP_SLOT"
  else
    DEFAULT_VAR_TMP_SLOT=$(runtime_partition_slot_from_path DEV_PART_VAR_TMP "${DEV_PART_VAR_TMP}")
  fi
  if [ -n "${DEFAULT_VAR_LIB_SHSIGNED_SLOT:-}" ]; then
    runtime_require_positive_integer DEFAULT_VAR_LIB_SHSIGNED_SLOT "$DEFAULT_VAR_LIB_SHSIGNED_SLOT"
  else
    DEFAULT_VAR_LIB_SHSIGNED_SLOT=$(runtime_partition_slot_from_path DEV_PART_VAR_LIB_SHSIGNED "${DEV_PART_VAR_LIB_SHSIGNED}")
  fi
  if [ -n "${DEFAULT_VAR_LOG_JOURNAL_SLOT:-}" ]; then
    runtime_require_positive_integer DEFAULT_VAR_LOG_JOURNAL_SLOT "$DEFAULT_VAR_LOG_JOURNAL_SLOT"
  else
    DEFAULT_VAR_LOG_JOURNAL_SLOT=$(runtime_partition_slot_from_path DEV_PART_VAR_LOG_JOURNAL "${DEV_PART_VAR_LOG_JOURNAL}")
  fi
  if [ -n "${DEFAULT_RAW_SWAP_SLOT:-}" ]; then
    runtime_require_positive_integer DEFAULT_RAW_SWAP_SLOT "$DEFAULT_RAW_SWAP_SLOT"
  else
    DEFAULT_RAW_SWAP_SLOT=$(runtime_partition_slot_from_path DEV_PART_RAW_SWAP "${DEV_PART_RAW_SWAP}")
  fi
  if [ -n "${DEFAULT_RAW_ZRAM_SLOT:-}" ]; then
    runtime_require_positive_integer DEFAULT_RAW_ZRAM_SLOT "$DEFAULT_RAW_ZRAM_SLOT"
  else
    DEFAULT_RAW_ZRAM_SLOT=$(runtime_partition_slot_from_path DEV_PART_RAW_ZRAM "${DEV_PART_RAW_ZRAM}")
  fi

  if [ "$DEFAULT_EFI_SLOT" -ge "$DEFAULT_BOOT_SLOT" ] || \
     [ "$DEFAULT_BOOT_SLOT" -ge "$DEFAULT_ROOT_SLOT" ] || \
     [ "$DEFAULT_ROOT_SLOT" -ge "$DEFAULT_HOME_SLOT" ] || \
     [ "$DEFAULT_HOME_SLOT" -ge "$DEFAULT_OPT_SLOT" ] || \
     [ "$DEFAULT_OPT_SLOT" -ge "$DEFAULT_DATA_SLOT" ] || \
     [ "$DEFAULT_DATA_SLOT" -ge "$DEFAULT_POOL_SLOT" ] || \
     [ "$DEFAULT_POOL_SLOT" -ge "$DEFAULT_VAR_TMP_SLOT" ] || \
     [ "$DEFAULT_VAR_TMP_SLOT" -ge "$DEFAULT_VAR_LIB_SHSIGNED_SLOT" ] || \
     [ "$DEFAULT_VAR_LIB_SHSIGNED_SLOT" -ge "$DEFAULT_VAR_LOG_JOURNAL_SLOT" ] || \
     [ "$DEFAULT_VAR_LOG_JOURNAL_SLOT" -ge "$DEFAULT_RAW_SWAP_SLOT" ] || \
     [ "$DEFAULT_RAW_SWAP_SLOT" -ge "$DEFAULT_RAW_ZRAM_SLOT" ]
  then
    runtime_fatal "Btrfs default slot numbering must stay strictly increasing from EFI through raw zram backing"
  fi
}

runtime_assign_default_slots() {
  DUALBOOT_ENABLED=false
  DUALBOOT_EFI_SLOT=
  DUALBOOT_DEBIAN_SLOT=
  RUNTIME_PRESERVED_SLOTS=
  RUNTIME_EFI_SLOT=$DEFAULT_EFI_SLOT
  RUNTIME_BOOT_SLOT=$DEFAULT_BOOT_SLOT
  RUNTIME_ROOT_SLOT=$DEFAULT_ROOT_SLOT
  RUNTIME_HOME_SLOT=$DEFAULT_HOME_SLOT
  RUNTIME_OPT_SLOT=$DEFAULT_OPT_SLOT
  RUNTIME_DATA_SLOT=$DEFAULT_DATA_SLOT
  RUNTIME_POOL_SLOT=$DEFAULT_POOL_SLOT
  RUNTIME_VAR_TMP_SLOT=$DEFAULT_VAR_TMP_SLOT
  RUNTIME_VAR_LIB_SHSIGNED_SLOT=$DEFAULT_VAR_LIB_SHSIGNED_SLOT
  RUNTIME_VAR_LOG_JOURNAL_SLOT=$DEFAULT_VAR_LOG_JOURNAL_SLOT
  RUNTIME_RAW_SWAP_SLOT=$DEFAULT_RAW_SWAP_SLOT
  RUNTIME_RAW_ZRAM_SLOT=$DEFAULT_RAW_ZRAM_SLOT
}

runtime_assign_dualboot_slots() {
  dualboot_efi_slot=$1
  dualboot_debian_slot=$2

  runtime_require_positive_integer dualboot_efi "$dualboot_efi_slot"
  runtime_require_positive_integer dualboot_debian "$dualboot_debian_slot"
  if [ "$dualboot_efi_slot" -ge "$dualboot_debian_slot" ]; then
    runtime_fatal "dualboot_efi must be lower than dualboot_debian"
  fi

  DUALBOOT_ENABLED=true
  DUALBOOT_EFI_SLOT=$dualboot_efi_slot
  DUALBOOT_DEBIAN_SLOT=$dualboot_debian_slot
  RUNTIME_EFI_SLOT=$dualboot_efi_slot
  RUNTIME_BOOT_SLOT=$dualboot_debian_slot
  RUNTIME_ROOT_SLOT=$((dualboot_debian_slot + 1))
  RUNTIME_HOME_SLOT=$((dualboot_debian_slot + 2))
  RUNTIME_OPT_SLOT=$((dualboot_debian_slot + 3))
  RUNTIME_DATA_SLOT=$((dualboot_debian_slot + 4))
  RUNTIME_POOL_SLOT=$((dualboot_debian_slot + 5))
  RUNTIME_VAR_TMP_SLOT=$((dualboot_debian_slot + 6))
  RUNTIME_VAR_LIB_SHSIGNED_SLOT=$((dualboot_debian_slot + 7))
  RUNTIME_VAR_LOG_JOURNAL_SLOT=$((dualboot_debian_slot + 8))
  RUNTIME_RAW_SWAP_SLOT=$((dualboot_debian_slot + 9))
  RUNTIME_RAW_ZRAM_SLOT=$((dualboot_debian_slot + 10))
  RUNTIME_PRESERVED_SLOTS=$(runtime_build_space_list 1 $((dualboot_debian_slot - 1)) "$dualboot_efi_slot")
}

runtime_apply_layout_from_cmdline() {
  installer_resolve_install_target_defaults
  : "${DEV_INSTALL_DISK:?DEV_INSTALL_DISK must be set}"
  runtime_derive_part_prefix
  runtime_validate_partition_sizes
  runtime_load_default_slots_from_env

  PARTMAN_RECIPE_NAME=${PARTMAN_RECIPE_NAME:-btrfs-ext4-xfs-layout}
  dualboot_efi_raw=$(runtime_cmdline_value dualboot_efi 2>/dev/null || true)
  dualboot_debian_raw=$(runtime_cmdline_value dualboot_debian 2>/dev/null || true)

  if runtime_dualboot_class_selected; then
    [ -n "$dualboot_efi_raw" ] || runtime_fatal "classes=...,dualboot requires dualboot_efi=<integer> on the kernel cmdline"
    [ -n "$dualboot_debian_raw" ] || runtime_fatal "classes=...,dualboot requires dualboot_debian=<integer> on the kernel cmdline"
    runtime_assign_dualboot_slots "$dualboot_efi_raw" "$dualboot_debian_raw"
  else
    if [ -n "$dualboot_efi_raw" ] || [ -n "$dualboot_debian_raw" ]; then
      runtime_fatal "dualboot_efi and dualboot_debian require classes=...,dualboot"
    fi
    runtime_assign_default_slots
  fi

  RUNTIME_DEBIAN_START_SLOT=$RUNTIME_BOOT_SLOT
  RUNTIME_DEBIAN_END_SLOT=$RUNTIME_RAW_ZRAM_SLOT
  DEV_PART_EFI=$(runtime_partition_path "$RUNTIME_EFI_SLOT")
  DEV_PART_BOOT=$(runtime_partition_path "$RUNTIME_BOOT_SLOT")
  DEV_PART_ROOT=$(runtime_partition_path "$RUNTIME_ROOT_SLOT")
  DEV_PART_HOME=$(runtime_partition_path "$RUNTIME_HOME_SLOT")
  DEV_PART_OPT=$(runtime_partition_path "$RUNTIME_OPT_SLOT")
  DEV_PART_DATA=$(runtime_partition_path "$RUNTIME_DATA_SLOT")
  DEV_PART_POOL=$(runtime_partition_path "$RUNTIME_POOL_SLOT")
  DEV_PART_VAR_TMP=$(runtime_partition_path "$RUNTIME_VAR_TMP_SLOT")
  DEV_PART_VAR_LIB_SHSIGNED=$(runtime_partition_path "$RUNTIME_VAR_LIB_SHSIGNED_SLOT")
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

runtime_write_runtime_env() {
  dest=$1
  runtime_ensure_system_identity
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
    printf 'DUALBOOT_ENABLED=%s\n' "$(runtime_shell_quote "$DUALBOOT_ENABLED")"
    printf 'ROOT_HOME_CRYPTO_ENABLED=%s\n' "$(runtime_shell_quote "$root_home_crypto_enabled")"
    printf 'ROOT_CRYPT_NAME=%s\n' "$(runtime_shell_quote cryptroot)"
    printf 'HOME_CRYPT_NAME=%s\n' "$(runtime_shell_quote crypthome)"
    printf 'DUALBOOT_EFI_SLOT=%s\n' "$(runtime_shell_quote "${DUALBOOT_EFI_SLOT:-}")"
    printf 'DUALBOOT_DEBIAN_SLOT=%s\n' "$(runtime_shell_quote "${DUALBOOT_DEBIAN_SLOT:-}")"
    printf 'RUNTIME_PRESERVED_SLOTS=%s\n' "$(runtime_shell_quote "${RUNTIME_PRESERVED_SLOTS:-}")"
    printf 'PARTMAN_RECIPE_NAME=%s\n' "$(runtime_shell_quote "$PARTMAN_RECIPE_NAME")"
    printf 'DEV_INSTALL_DISK=%s\n' "$(runtime_shell_quote "$DEV_INSTALL_DISK")"
    printf 'DEV_PART_PREFIX=%s\n' "$(runtime_shell_quote "$DEV_PART_PREFIX")"
    printf 'RUNTIME_DISK_TOTAL_MB=%s\n' "$(runtime_shell_quote "$RUNTIME_DISK_TOTAL_MB")"
    printf 'RUNTIME_LAYOUT_SAFETY_MARGIN_MB=%s\n' "$(runtime_shell_quote "$RUNTIME_LAYOUT_SAFETY_MARGIN_MB")"
    printf 'RUNTIME_PRESERVED_TOTAL_MB=%s\n' "$(runtime_shell_quote "$RUNTIME_PRESERVED_TOTAL_MB")"
    printf 'RUNTIME_USABLE_BUDGET_MB=%s\n' "$(runtime_shell_quote "$RUNTIME_USABLE_BUDGET_MB")"
    printf 'RUNTIME_BASE_LAYOUT_MB=%s\n' "$(runtime_shell_quote "$RUNTIME_BASE_LAYOUT_MB")"
    printf 'RUNTIME_INSTALL_RAM_MIB=%s\n' "$(runtime_shell_quote "$RUNTIME_INSTALL_RAM_MIB")"
    printf 'RUNTIME_EFI_SLOT=%s\n' "$(runtime_shell_quote "$RUNTIME_EFI_SLOT")"
    printf 'RUNTIME_BOOT_SLOT=%s\n' "$(runtime_shell_quote "$RUNTIME_BOOT_SLOT")"
    printf 'RUNTIME_ROOT_SLOT=%s\n' "$(runtime_shell_quote "$RUNTIME_ROOT_SLOT")"
    printf 'RUNTIME_HOME_SLOT=%s\n' "$(runtime_shell_quote "$RUNTIME_HOME_SLOT")"
    printf 'RUNTIME_OPT_SLOT=%s\n' "$(runtime_shell_quote "$RUNTIME_OPT_SLOT")"
    printf 'RUNTIME_DATA_SLOT=%s\n' "$(runtime_shell_quote "$RUNTIME_DATA_SLOT")"
    printf 'RUNTIME_POOL_SLOT=%s\n' "$(runtime_shell_quote "$RUNTIME_POOL_SLOT")"
    printf 'RUNTIME_VAR_TMP_SLOT=%s\n' "$(runtime_shell_quote "$RUNTIME_VAR_TMP_SLOT")"
    printf 'RUNTIME_VAR_LIB_SHSIGNED_SLOT=%s\n' "$(runtime_shell_quote "$RUNTIME_VAR_LIB_SHSIGNED_SLOT")"
    printf 'RUNTIME_VAR_LOG_JOURNAL_SLOT=%s\n' "$(runtime_shell_quote "$RUNTIME_VAR_LOG_JOURNAL_SLOT")"
    printf 'RUNTIME_RAW_SWAP_SLOT=%s\n' "$(runtime_shell_quote "$RUNTIME_RAW_SWAP_SLOT")"
    printf 'RUNTIME_RAW_ZRAM_SLOT=%s\n' "$(runtime_shell_quote "$RUNTIME_RAW_ZRAM_SLOT")"
    printf 'RUNTIME_DEBIAN_START_SLOT=%s\n' "$(runtime_shell_quote "$RUNTIME_DEBIAN_START_SLOT")"
    printf 'RUNTIME_DEBIAN_END_SLOT=%s\n' "$(runtime_shell_quote "$RUNTIME_DEBIAN_END_SLOT")"
    printf 'DEV_PART_EFI=%s\n' "$(runtime_shell_quote "$DEV_PART_EFI")"
    printf 'DEV_PART_BOOT=%s\n' "$(runtime_shell_quote "$DEV_PART_BOOT")"
    printf 'DEV_PART_ROOT=%s\n' "$(runtime_shell_quote "$DEV_PART_ROOT")"
    printf 'DEV_PART_HOME=%s\n' "$(runtime_shell_quote "$DEV_PART_HOME")"
    printf 'DEV_PART_OPT=%s\n' "$(runtime_shell_quote "$DEV_PART_OPT")"
    printf 'DEV_PART_DATA=%s\n' "$(runtime_shell_quote "$DEV_PART_DATA")"
    printf 'DEV_PART_POOL=%s\n' "$(runtime_shell_quote "$DEV_PART_POOL")"
    printf 'DEV_PART_VAR_TMP=%s\n' "$(runtime_shell_quote "$DEV_PART_VAR_TMP")"
    printf 'DEV_PART_VAR_LIB_SHSIGNED=%s\n' "$(runtime_shell_quote "$DEV_PART_VAR_LIB_SHSIGNED")"
    printf 'DEV_PART_VAR_LOG_JOURNAL=%s\n' "$(runtime_shell_quote "$DEV_PART_VAR_LOG_JOURNAL")"
    printf 'DEV_PART_RAW_SWAP=%s\n' "$(runtime_shell_quote "$DEV_PART_RAW_SWAP")"
    printf 'DEV_PART_RAW_ZRAM=%s\n' "$(runtime_shell_quote "$DEV_PART_RAW_ZRAM")"
    printf 'ZRAM_BACKING_RAW_DEVICE=%s\n' "$(runtime_shell_quote "$ZRAM_BACKING_RAW_DEVICE")"
    printf 'ZRAM_BACKING_MAPPER_NAME=%s\n' "$(runtime_shell_quote "$ZRAM_BACKING_MAPPER_NAME")"
    printf 'ZRAM_BACKING_DEVICE=%s\n' "$(runtime_shell_quote "$ZRAM_BACKING_DEVICE")"
    printf 'SWAP_FALLBACK_RAW_DEVICE=%s\n' "$(runtime_shell_quote "$SWAP_FALLBACK_RAW_DEVICE")"
    printf 'SWAP_FALLBACK_MAPPER_NAME=%s\n' "$(runtime_shell_quote "$SWAP_FALLBACK_MAPPER_NAME")"
    printf 'SWAP_FALLBACK_MAPPER=%s\n' "$(runtime_shell_quote "$SWAP_FALLBACK_MAPPER")"
    printf 'DEV_PART_EFI_MB=%s\n' "$(runtime_shell_quote "$DEV_PART_EFI_MB")"
    printf 'DEV_PART_BOOT_MB=%s\n' "$(runtime_shell_quote "$DEV_PART_BOOT_MB")"
    printf 'DEV_PART_ROOT_MB=%s\n' "$(runtime_shell_quote "$DEV_PART_ROOT_MB")"
    printf 'DEV_PART_HOME_MB=%s\n' "$(runtime_shell_quote "$DEV_PART_HOME_MB")"
    printf 'DEV_PART_OPT_MB=%s\n' "$(runtime_shell_quote "$DEV_PART_OPT_MB")"
    printf 'DEV_PART_DATA_MB=%s\n' "$(runtime_shell_quote "$DEV_PART_DATA_MB")"
    printf 'DEV_PART_POOL_MB=%s\n' "$(runtime_shell_quote "$DEV_PART_POOL_MB")"
    printf 'DEV_PART_VAR_TMP_MB=%s\n' "$(runtime_shell_quote "$DEV_PART_VAR_TMP_MB")"
    printf 'DEV_PART_VAR_LIB_SHSIGNED_MB=%s\n' "$(runtime_shell_quote "$DEV_PART_VAR_LIB_SHSIGNED_MB")"
    printf 'DEV_PART_VAR_LOG_JOURNAL_MB=%s\n' "$(runtime_shell_quote "$DEV_PART_VAR_LOG_JOURNAL_MB")"
    printf 'DEV_PART_RAW_SWAP_MB=%s\n' "$(runtime_shell_quote "$DEV_PART_RAW_SWAP_MB")"
    printf 'DEV_PART_RAW_ZRAM_MB=%s\n' "$(runtime_shell_quote "$DEV_PART_RAW_ZRAM_MB")"
    printf 'SWAP_SIZE_MIB=%s\n' "$(runtime_shell_quote "$SWAP_SIZE_MIB")"
    if [ "$DUALBOOT_ENABLED" = "true" ]; then
      slot=1
      while [ "$slot" -lt "$RUNTIME_DEBIAN_START_SLOT" ]; do
        size_mb=$(runtime_get_partition_size_mb "$slot") || \
          runtime_fatal "missing measured partition size for preserved slot ${slot}"
        printf 'RUNTIME_PARTITION_%s_SIZE_MB=%s\n' "$slot" "$(runtime_shell_quote "$size_mb")"
        slot=$((slot + 1))
      done
    fi
  } >"$dest"
  chmod 0600 "$dest"
}

runtime_emit_debian_partition_recipe() {
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
    ${DEV_PART_ROOT_MB} ${DEV_PART_ROOT_MB} ${DEV_PART_ROOT_MB} btrfs
        method{ crypto } format{ }
        crypto_type{ luks }
        cipher{ aes }
        keysize{ 512 }
        ivalgorithm{ xts-plain64 }
        keytype{ passphrase }
        keyhash{ sha256 }
        use_filesystem{ } filesystem{ btrfs }
        mountpoint{ / }
    .
    ${DEV_PART_HOME_MB} ${DEV_PART_HOME_MB} ${DEV_PART_HOME_MB} free
        method{ keep }
    .
EOF
  else
    cat <<EOF
    ${DEV_PART_ROOT_MB} ${DEV_PART_ROOT_MB} ${DEV_PART_ROOT_MB} btrfs
        method{ format } format{ }
        use_filesystem{ } filesystem{ btrfs }
        mountpoint{ / }
    .
    ${DEV_PART_HOME_MB} ${DEV_PART_HOME_MB} ${DEV_PART_HOME_MB} btrfs
        method{ format } format{ }
        use_filesystem{ } filesystem{ btrfs }
        mountpoint{ /home }
    .
EOF
  fi
  cat <<EOF
    ${DEV_PART_OPT_MB} ${DEV_PART_OPT_MB} ${DEV_PART_OPT_MB} btrfs
        method{ format } format{ }
        use_filesystem{ } filesystem{ btrfs }
        mountpoint{ /opt }
    .
    ${DEV_PART_DATA_MB} ${DEV_PART_DATA_MB} ${DEV_PART_DATA_MB} xfs
        method{ format } format{ }
        use_filesystem{ } filesystem{ xfs }
        mountpoint{ /data }
    .
    ${DEV_PART_POOL_MB} ${DEV_PART_POOL_MB} ${DEV_PART_POOL_MB} xfs
        method{ format } format{ }
        use_filesystem{ } filesystem{ xfs }
        mountpoint{ /pool }
    .
    ${DEV_PART_VAR_TMP_MB} ${DEV_PART_VAR_TMP_MB} ${DEV_PART_VAR_TMP_MB} ext4
        method{ format } format{ }
        use_filesystem{ } filesystem{ ext4 }
        mountpoint{ /var/tmp }
    .
    ${DEV_PART_VAR_LIB_SHSIGNED_MB} ${DEV_PART_VAR_LIB_SHSIGNED_MB} ${DEV_PART_VAR_LIB_SHSIGNED_MB} free
        method{ keep }
    .
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
  runtime_compute_layout_sizing
  runtime_prepare_parent_dir "$dest" 0700
  if [ "$DUALBOOT_ENABLED" = "true" ]; then
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
    printf '##########  Runtime Partitioning  ##########\n'
    printf '# Generated inside the installer before partman runs.\n'
    if [ "$DUALBOOT_ENABLED" = "true" ]; then
      printf '# Reused EFI slot: %s\n' "$RUNTIME_EFI_SLOT"
      printf '# Debian starts at slot: %s\n' "$RUNTIME_DEBIAN_START_SLOT"
      printf '# Preserved slots: %s\n' "${RUNTIME_PRESERVED_SLOTS:-none}"
    fi
    printf 'd-i partman-efi/confirm boolean true\n'
    printf 'd-i partman-efi/confirm seen true\n'
    if [ "$DUALBOOT_ENABLED" = "true" ] || runtime_root_home_crypto_enabled; then
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
    if [ "$DUALBOOT_ENABLED" != "true" ] && ! runtime_root_home_crypto_enabled; then
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
    printf '##########  Runtime Identity Configuration  ##########\n'
    printf '# Generated inside the installer before netcfg finishes.\n'
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

runtime_seed_partman_answers() {
  recipe_file=$1
  runtime_seed_generated_answers runtime_write_partman_fragment "$recipe_file"
}
