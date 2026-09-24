#!/bin/sh
# Shared storage runtime module.

runtime_require_integer() {
  runtime_require_integer_label=$1
  runtime_require_integer_value=$2
  case "$runtime_require_integer_value" in
    ''|*[!0-9]*)
      runtime_fatal "${runtime_require_integer_label} must be an integer, got '${runtime_require_integer_value:-unset}'"
      ;;
  esac
}

runtime_require_positive_integer() {
  runtime_require_positive_integer_label=$1
  runtime_require_positive_integer_value=$2
  runtime_require_integer "$runtime_require_positive_integer_label" "$runtime_require_positive_integer_value"
  [ "$runtime_require_positive_integer_value" -gt 0 ] || runtime_fatal "${runtime_require_positive_integer_label} must be greater than zero"
}

runtime_require_nonnegative_integer() {
  runtime_require_nonnegative_integer_label=$1
  runtime_require_nonnegative_integer_value=$2
  runtime_require_integer "$runtime_require_nonnegative_integer_label" "$runtime_require_nonnegative_integer_value"
  [ "$runtime_require_nonnegative_integer_value" -ge 0 ] || runtime_fatal "${runtime_require_nonnegative_integer_label} must be zero or greater"
}

runtime_min() {
  runtime_min_left=$1
  runtime_min_right=$2
  runtime_require_integer runtime_min_left "$runtime_min_left"
  runtime_require_integer runtime_min_right "$runtime_min_right"
  if [ "$runtime_min_left" -le "$runtime_min_right" ]; then
    printf '%s\n' "$runtime_min_left"
  else
    printf '%s\n' "$runtime_min_right"
  fi
}

runtime_max() {
  runtime_max_left=$1
  runtime_max_right=$2
  runtime_require_integer runtime_max_left "$runtime_max_left"
  runtime_require_integer runtime_max_right "$runtime_max_right"
  if [ "$runtime_max_left" -ge "$runtime_max_right" ]; then
    printf '%s\n' "$runtime_max_left"
  else
    printf '%s\n' "$runtime_max_right"
  fi
}

runtime_clamp() {
  runtime_clamp_value=$1
  runtime_clamp_min=$2
  runtime_clamp_max=$3
  runtime_require_integer runtime_clamp_value "$runtime_clamp_value"
  runtime_require_integer runtime_clamp_min "$runtime_clamp_min"
  runtime_require_integer runtime_clamp_max "$runtime_clamp_max"
  if [ "$runtime_clamp_min" -gt "$runtime_clamp_max" ]; then
    runtime_fatal "runtime_clamp requires min <= max, got ${runtime_clamp_min} > ${runtime_clamp_max}"
  fi
  if [ "$runtime_clamp_value" -lt "$runtime_clamp_min" ]; then
    printf '%s\n' "$runtime_clamp_min"
  elif [ "$runtime_clamp_value" -gt "$runtime_clamp_max" ]; then
    printf '%s\n' "$runtime_clamp_max"
  else
    printf '%s\n' "$runtime_clamp_value"
  fi
}

runtime_total_ram_mib() {
  if [ -n "${RUNTIME_MEMTOTAL_MIB_OVERRIDE:-}" ]; then
    runtime_require_positive_integer RUNTIME_MEMTOTAL_MIB_OVERRIDE "$RUNTIME_MEMTOTAL_MIB_OVERRIDE"
    printf '%s\n' "$RUNTIME_MEMTOTAL_MIB_OVERRIDE"
    return 0
  fi

  if [ -r /proc/meminfo ]; then
    mem_kib=
    while IFS=' ' read -r key value _rest || [ -n "${key:-}" ]; do
      [ "$key" = "MemTotal:" ] || continue
      mem_kib=$value
      break
    done </proc/meminfo
    case "$mem_kib" in
      ''|*[!0-9]*|0) ;;
      *)
        printf '%s\n' "$(((mem_kib + 1023) / 1024))"
        return 0
        ;;
    esac
  fi

  runtime_fatal "unable to determine total RAM in MiB"
}

