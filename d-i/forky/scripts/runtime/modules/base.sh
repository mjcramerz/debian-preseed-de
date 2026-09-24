#!/bin/sh

# Shared runtime helpers for storage-family installer scripts.
# This file is sourced before scripts/runtime/{btrfs,f2fs}.sh.

runtime_fatal() {
  if command -v installer_fatal >/dev/null 2>&1; then
    installer_fatal "$@"
  fi
  echo "fatal: $*" >&2
  exit 1
}

runtime_cmdline() {
  if [ -n "${INSTALLER_CMDLINE:-}" ]; then
    printf '%s\n' "$INSTALLER_CMDLINE"
    return 0
  fi

  if [ "${RUNTIME_CMDLINE_CACHE_READY:-0}" -eq 1 ]; then
    printf '%s\n' "${RUNTIME_CMDLINE_CACHE:-}"
    return 0
  fi

  if [ -n "${INSTALLER_CMDLINE_FILE:-}" ] && [ -r "${INSTALLER_CMDLINE_FILE}" ]; then
    RUNTIME_CMDLINE_CACHE=$(cat "${INSTALLER_CMDLINE_FILE}" 2>/dev/null || true)
  elif [ -r /proc/cmdline ]; then
    RUNTIME_CMDLINE_CACHE=$(cat /proc/cmdline 2>/dev/null || true)
  else
    RUNTIME_CMDLINE_CACHE=
  fi

  RUNTIME_CMDLINE_CACHE_READY=1
  printf '%s\n' "$RUNTIME_CMDLINE_CACHE"
}


runtime_preseed_env_value() (
  preseed_env_read_value "$@"
)

runtime_cmdline_value() (
  set +x
  set +v
  # The first exact parameter wins, including an explicitly empty parameter.
  # Passwords are literal data, not pathname patterns or shell expressions.
  set -f
  IFS=' 	
'
  runtime_cmdline_key=$1
  for runtime_cmdline_arg in $(runtime_cmdline); do
    case "$runtime_cmdline_arg" in
      "$runtime_cmdline_key")
        printf '\n'
        return 0
        ;;
      "$runtime_cmdline_key"=*)
        printf '%s\n' "${runtime_cmdline_arg#*=}"
        return 0
        ;;
    esac
  done

  runtime_preseed_env_value "$runtime_cmdline_key"
)

runtime_class_list_has_addon() {
  runtime_addon_name=$1
  runtime_class_list=${2:-}

  case "$runtime_addon_name" in
    ''|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-]*) return 1 ;;
  esac

  for runtime_class_token in $(printf '%s\n' "$runtime_class_list" | tr ';,' ' '); do
    case "$runtime_class_token" in
      "$runtime_addon_name"|addon/"$runtime_addon_name"|addon:"$runtime_addon_name"|addon."$runtime_addon_name"|class-addon/"$runtime_addon_name"|class-addon:"$runtime_addon_name"|class-addon."$runtime_addon_name")
        return 0
        ;;
    esac
  done
  return 1
}

