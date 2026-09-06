#!/bin/sh
# Shared first-boot logging filter. This file is sourced.

if [ -r /etc/default/system-runtime ]; then
  # shellcheck disable=SC1091
  . /etc/default/system-runtime
fi

firstboot_log_level_canonical() {
  case "${1:-info}" in
    debug|DEBUG) printf '%s\n' debug ;;
    info|INFO) printf '%s\n' info ;;
    warn|WARN|warning|WARNING) printf '%s\n' warning ;;
    error|ERROR|fatal|FATAL) printf '%s\n' error ;;
    none|NONE) printf '%s\n' none ;;
    *) printf '%s\n' info ;;
  esac
}

firstboot_log_level_value() {
  case "$(firstboot_log_level_canonical "$1")" in
    debug) printf '%s\n' 10 ;;
    info) printf '%s\n' 20 ;;
    warning) printf '%s\n' 30 ;;
    error) printf '%s\n' 40 ;;
    none) printf '%s\n' 99 ;;
  esac
}

firstboot_log_should_emit() {
  requested_level=$(firstboot_log_level_canonical "$1")
  active_level=$(firstboot_log_level_canonical "${SYSTEMD_LOG_LEVEL:-error}")

  [ "$requested_level" = error ] && return 0
  [ "$active_level" != none ] || return 1
  requested_value=$(firstboot_log_level_value "$requested_level")
  active_value=$(firstboot_log_level_value "$active_level")
  [ "$requested_value" -ge "$active_value" ]
}

log_line() {
  stage=$1
  level=$2
  component=$3
  shift 3
  level=$(firstboot_log_level_canonical "$level")
  firstboot_log_should_emit "$level" || return 0
  printf '%s stage=%s level=%s component=%s %s\n' \
    "$(timestamp)" "$stage" "$level" "$component" "$*" >>"$FIRSTBOOT_LOG_FILE"
}
