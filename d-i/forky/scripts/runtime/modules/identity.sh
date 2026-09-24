#!/bin/sh
# Shared storage runtime module.

runtime_prepare_parent_dir() {
  path=$1
  mode=$2
  parent_dir=$(dirname "$path")
  [ -d "$parent_dir" ] || install -d -m "$mode" "$parent_dir"
}

runtime_shell_quote() {
  printf "'%s'" "$(printf '%s' "${1-}" | sed "s/'/'\\\\''/g")"
}

runtime_validate_printable_single_line() {
  label=$1
  value=$2

  [ -n "$value" ] || runtime_fatal "${label} must not be empty"
  case "$value" in
    *[![:print:]]*|*[[:space:]]*)
      runtime_fatal "${label} must be a single printable token without whitespace"
      ;;
  esac
}

runtime_validate_system_prefix() {
  value=$1

  [ -n "$value" ] || runtime_fatal "SYSTEM_PREFIX must not be empty"
  case "$value" in
    *[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789]*)
      runtime_fatal "SYSTEM_PREFIX must contain only ASCII letters and digits"
      ;;
  esac
  if [ "${#value}" -gt 59 ]; then
    runtime_fatal "SYSTEM_PREFIX must be 59 characters or shorter so SYSTEM_HOSTNAME stays within 63 characters"
  fi
}

runtime_validate_system_domain() {
  value=$1

  [ -n "$value" ] || runtime_fatal "SYSTEM_DOMAIN must not be empty"
  case "$value" in
    *[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.-]*|.*|*.|*..*)
      runtime_fatal "SYSTEM_DOMAIN must contain only hostname-safe labels"
      ;;
  esac
}

runtime_validate_system_hostname() {
  prefix=$1
  value=$2

  case "$value" in
    ''|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-]*|-*|*-)
      runtime_fatal "SYSTEM_HOSTNAME must contain only hostname-safe characters"
      ;;
    "${prefix}"-[0-9][0-9][0-9])
      ;;
    *)
      runtime_fatal "SYSTEM_HOSTNAME must match SYSTEM_PREFIX-###"
      ;;
  esac
}

runtime_apply_identity_from_cmdline() {
  cmdline_domain=$(runtime_cmdline_value netcfg/get_domain 2>/dev/null || true)
  if [ -z "$cmdline_domain" ]; then
    cmdline_domain=$(runtime_cmdline_value domain 2>/dev/null || true)
  fi
  [ -n "$cmdline_domain" ] || return 0
  SYSTEM_DOMAIN=$cmdline_domain
}

runtime_random_hostname_suffix() {
  [ -r /dev/urandom ] || runtime_fatal "unable to generate hostname suffix: /dev/urandom is unavailable"
  # Filter the kernel RNG stream down to ASCII digits so the suffix is always ###.
  raw=$(LC_ALL=C tr -dc '0-9' </dev/urandom | dd bs=3 count=1 2>/dev/null || true)
  case "$raw" in
    [0-9][0-9][0-9])
      ;;
    *)
      runtime_fatal "unable to generate hostname suffix from /dev/urandom"
      ;;
  esac

  printf '%s\n' "$raw"
}

runtime_ensure_system_identity() {
  : "${SYSTEM_PREFIX:?SYSTEM_PREFIX must be set}"
  : "${SYSTEM_DOMAIN:?SYSTEM_DOMAIN must be set}"

  runtime_apply_identity_from_cmdline
  runtime_validate_system_prefix "$SYSTEM_PREFIX"
  runtime_validate_system_domain "$SYSTEM_DOMAIN"

  if [ -n "${SYSTEM_HOSTNAME:-}" ]; then
    runtime_validate_system_hostname "$SYSTEM_PREFIX" "$SYSTEM_HOSTNAME"
    return 0
  fi

  SYSTEM_HOSTNAME="${SYSTEM_PREFIX}-$(runtime_random_hostname_suffix)"
  runtime_validate_system_hostname "$SYSTEM_PREFIX" "$SYSTEM_HOSTNAME"
}

