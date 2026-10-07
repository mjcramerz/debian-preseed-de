#!/bin/sh
# Shared storage runtime module.

runtime_derive_part_prefix() {
  if [ -n "${DEV_PART_PREFIX:-}" ]; then
    return 0
  fi

  DEV_PART_PREFIX=${DEV_INSTALL_DISK:-}
  case "${DEV_INSTALL_DISK:-}" in
    *[0-9]) DEV_PART_PREFIX="${DEV_INSTALL_DISK}p" ;;
  esac
}

runtime_partition_path() {
  slot=$1
  printf '%s%s\n' "$DEV_PART_PREFIX" "$slot"
}

runtime_device_size_bytes() {
  dev=$1
  if [ ! -b "$dev" ]; then
    echo "fatal: partition device is missing: ${dev}" >&2
    return 1
  fi

  if command -v blockdev >/dev/null 2>&1; then
    bytes=$(blockdev --getsize64 "$dev" 2>/dev/null || true)
    case "$bytes" in
      ''|*[!0-9]*) ;;
      *)
        printf '%s\n' "$bytes"
        return 0
        ;;
    esac
  fi

  sys_name=${dev##*/}
  sectors_file="/sys/class/block/${sys_name}/size"
  if [ -r "$sectors_file" ]; then
    sectors=$(cat "$sectors_file")
    case "$sectors" in
      ''|*[!0-9]*) ;;
      *)
        printf '%s\n' "$((sectors * 512))"
        return 0
        ;;
    esac
  fi

  echo "fatal: unable to determine partition size for ${dev}" >&2
  return 1
}

runtime_device_size_mb() {
  dev=$1
  bytes=$(runtime_device_size_bytes "$dev") || return 1
  # Preserved partitions are rounded up in partman's decimal MB units.
  size_mb=$(((bytes + 999999) / 1000000))
  [ "$size_mb" -gt 0 ] || runtime_fatal "partition size for ${dev} resolved to zero MB"
  printf '%s\n' "$size_mb"
}

runtime_install_disk_size_mb() {
  if [ -n "${RUNTIME_INSTALL_DISK_MB_OVERRIDE:-}" ]; then
    runtime_require_positive_integer RUNTIME_INSTALL_DISK_MB_OVERRIDE "$RUNTIME_INSTALL_DISK_MB_OVERRIDE"
    printf '%s\n' "$RUNTIME_INSTALL_DISK_MB_OVERRIDE"
    return 0
  fi

  # Never round available disk capacity up. Preserved sizes are rounded up
  # separately, so every rounding decision remains conservative.
  bytes=$(runtime_device_size_bytes "$DEV_INSTALL_DISK") || return 1
  size_mb=$((bytes / 1000000))
  [ "$size_mb" -gt 0 ] || runtime_fatal "install disk size resolved to zero MB"
  printf '%s\n' "$size_mb"
}

runtime_fill_partition_to_target() {
  current_mb=$1
  target_mb=$2
  budget_mb=$3

  runtime_require_positive_integer runtime_fill_current_mb "$current_mb"
  runtime_require_integer runtime_fill_target_mb "$target_mb"
  runtime_require_integer runtime_fill_budget_mb "$budget_mb"

  if [ "$budget_mb" -le 0 ] || [ "$current_mb" -ge "$target_mb" ]; then
    printf '%s %s\n' "$current_mb" "$budget_mb"
    return 0
  fi

  needed_mb=$((target_mb - current_mb))
  if [ "$needed_mb" -le "$budget_mb" ]; then
    printf '%s %s\n' "$target_mb" "$((budget_mb - needed_mb))"
  else
    printf '%s %s\n' "$((current_mb + budget_mb))" "0"
  fi
}

runtime_apply_fill_result() {
  current_var=$1
  budget_var=$2
  fill_result=$3

  case "$fill_result" in
    *" "*)
      new_current=${fill_result%% *}
      new_budget=${fill_result#* }
      ;;
    *)
      runtime_fatal "runtime fill result must contain '<current> <budget>', got '${fill_result}'"
      ;;
  esac

  runtime_require_integer runtime_apply_fill_current "$new_current"
  runtime_require_integer runtime_apply_fill_budget "$new_budget"
  eval "$current_var=\$new_current"
  eval "$budget_var=\$new_budget"
}

runtime_shrink_partition_to_floor() {
  current_mb=$1
  floor_mb=$2
  overflow_mb=$3

  runtime_require_nonnegative_integer runtime_shrink_current_mb "$current_mb"
  runtime_require_nonnegative_integer runtime_shrink_floor_mb "$floor_mb"
  runtime_require_integer runtime_shrink_overflow_mb "$overflow_mb"
  [ "$floor_mb" -le "$current_mb" ] || runtime_fatal "runtime shrink floor must be <= current size"

  if [ "$overflow_mb" -le 0 ] || [ "$current_mb" -le "$floor_mb" ]; then
    printf '%s %s\n' "$current_mb" "$overflow_mb"
    return 0
  fi

  shrinkable_mb=$((current_mb - floor_mb))
  if [ "$shrinkable_mb" -ge "$overflow_mb" ]; then
    printf '%s %s\n' "$((current_mb - overflow_mb))" "0"
  else
    printf '%s %s\n' "$floor_mb" "$((overflow_mb - shrinkable_mb))"
  fi
}

runtime_mib_to_recipe_mb() {
  # Only logical RAM/swap sizing uses MiB. Recipes and disk budgets use MB.
  label=$1
  size_mb=$2
  runtime_require_positive_integer "$label" "$size_mb"
  case "$size_mb" in
    0*) runtime_fatal "${label} must not contain leading zeroes" ;;
  esac
  [ "$size_mb" -le 2147483647 ] || runtime_fatal "${label} is too large"
  printf '%s\n' "$(((size_mb * 1048576 + 999999) / 1000000))"
}

runtime_compute_raw_zram_partition_mb() {
  runtime_zram_budget_mb=$1
  runtime_zram_relevant_span_mb=$2

  runtime_require_positive_integer runtime_zram_budget_mb "$runtime_zram_budget_mb"
  runtime_require_positive_integer runtime_zram_relevant_span_mb "$runtime_zram_relevant_span_mb"
  runtime_require_positive_integer SIZE_PART_RAW_ZRAM_MB "${SIZE_PART_RAW_ZRAM_MB:-}"
  runtime_require_positive_integer SIZE_PART_RAW_ZRAM_DISK_DIVISOR "${SIZE_PART_RAW_ZRAM_DISK_DIVISOR:-}"
  runtime_require_positive_integer SIZE_PART_RAW_ZRAM_BUDGET_DIVISOR "${SIZE_PART_RAW_ZRAM_BUDGET_DIVISOR:-}"
  runtime_require_positive_integer SIZE_PART_RAW_ZRAM_MAX_MB "${SIZE_PART_RAW_ZRAM_MAX_MB:-}"
  runtime_require_positive_integer SIZE_PART_RAW_ZRAM_MIN_MB "${SIZE_PART_RAW_ZRAM_MIN_MB:-2048}"

  runtime_zram_floor_mb=$(runtime_min "$SIZE_PART_RAW_ZRAM_MB" "${SIZE_PART_RAW_ZRAM_MIN_MB:-2048}")
  [ "$runtime_zram_floor_mb" -le "$SIZE_PART_RAW_ZRAM_MAX_MB" ] ||
    runtime_fatal "raw zram backing minimum exceeds its maximum"
  runtime_zram_target_mb=$((runtime_zram_relevant_span_mb / SIZE_PART_RAW_ZRAM_DISK_DIVISOR))
  runtime_zram_target_mb=$(runtime_clamp "$runtime_zram_target_mb" "$runtime_zram_floor_mb" "$SIZE_PART_RAW_ZRAM_MAX_MB")
  runtime_zram_budget_cap_mb=$((runtime_zram_budget_mb / SIZE_PART_RAW_ZRAM_BUDGET_DIVISOR))
  if [ "$runtime_zram_budget_cap_mb" -lt "$runtime_zram_floor_mb" ]; then
    runtime_zram_budget_cap_mb=$runtime_zram_floor_mb
  fi

  runtime_min "$runtime_zram_target_mb" "$runtime_zram_budget_cap_mb"
}

runtime_compute_swap_partition_mib() {
  runtime_swap_budget_mb=$1
  runtime_swap_ram_mib=$2

  runtime_require_positive_integer runtime_swap_budget_mb "$runtime_swap_budget_mb"
  runtime_require_positive_integer runtime_swap_ram_mib "$runtime_swap_ram_mib"
  runtime_require_positive_integer SIZE_PART_RAW_SWAP_MB "${SIZE_PART_RAW_SWAP_MB:-}"
  runtime_require_positive_integer SIZE_PART_SWAP_MIN_MIB "${SIZE_PART_SWAP_MIN_MIB:-}"
  runtime_require_positive_integer SIZE_PART_SWAP_MAX_MIB "${SIZE_PART_SWAP_MAX_MIB:-}"
  runtime_require_positive_integer SIZE_PART_SWAP_RAM_DIVISOR "${SIZE_PART_SWAP_RAM_DIVISOR:-}"
  runtime_require_positive_integer SIZE_PART_SWAP_LAYOUT_DIVISOR "${SIZE_PART_SWAP_LAYOUT_DIVISOR:-}"

  [ "$SIZE_PART_SWAP_MIN_MIB" -le "$SIZE_PART_SWAP_MAX_MIB" ] ||
    runtime_fatal "fallback swap minimum exceeds its maximum"
  runtime_swap_target_mib=$((runtime_swap_ram_mib / SIZE_PART_SWAP_RAM_DIVISOR))
  runtime_swap_target_mib=$(runtime_clamp "$runtime_swap_target_mib" "$SIZE_PART_SWAP_MIN_MIB" "$SIZE_PART_SWAP_MAX_MIB")
  runtime_swap_budget_cap_mib=$((runtime_swap_budget_mb * 1000000 / 1048576 / SIZE_PART_SWAP_LAYOUT_DIVISOR))
  if [ "$runtime_swap_budget_cap_mib" -lt "$SIZE_PART_SWAP_MIN_MIB" ]; then
    runtime_swap_budget_cap_mib=$SIZE_PART_SWAP_MIN_MIB
  fi

  runtime_min "$runtime_swap_target_mib" "$runtime_swap_budget_cap_mib"
}

# Recipe text is installer-only data. Stage authenticated sources in the running
# installer's private temporary directory, never in the installed target tree.
