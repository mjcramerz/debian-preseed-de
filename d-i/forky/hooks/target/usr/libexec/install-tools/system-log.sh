#!/bin/sh
# Shared installed-target logging helper. This file is sourced.

runtime_log_canonical() {
  case "${1:-error}" in
    debug|DEBUG) printf '%s\n' debug ;;
    info|INFO) printf '%s\n' info ;;
    warn|WARN|warning|WARNING) printf '%s\n' warning ;;
    error|ERROR|fatal|FATAL) printf '%s\n' error ;;
    none|NONE) printf '%s\n' none ;;
    *) return 1 ;;
  esac
}

runtime_log_level_value() {
  case "$1" in
    debug) printf '%s\n' 10 ;;
    info) printf '%s\n' 20 ;;
    warning) printf '%s\n' 30 ;;
    error) printf '%s\n' 40 ;;
    none) printf '%s\n' 99 ;;
    *) return 1 ;;
  esac
}

runtime_log_raw_error() {
  printf 'error: %s\n' "$*" >&2
}

runtime_log_init() {
  RUNTIME_LOG_TAG=$1
  RUNTIME_LOG_LEVEL_VAR=$2
  RUNTIME_LOG_DEFAULT_LEVEL=${3:-error}

  case "$RUNTIME_LOG_LEVEL_VAR" in
    ''|[!ABCDEFGHIJKLMNOPQRSTUVWXYZ_]*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_]*)
      runtime_log_raw_error "invalid log level variable name: ${RUNTIME_LOG_LEVEL_VAR:-unset}"
      exit 1
      ;;
    *)
      ;;
  esac

  # shellcheck disable=SC2086,SC2154
  eval "runtime_log_raw_level=\${$RUNTIME_LOG_LEVEL_VAR-}"
  [ -n "$runtime_log_raw_level" ] || runtime_log_raw_level=$RUNTIME_LOG_DEFAULT_LEVEL
  RUNTIME_LOG_ACTIVE_LEVEL=$(runtime_log_canonical "$runtime_log_raw_level") || {
    runtime_log_raw_error "${RUNTIME_LOG_LEVEL_VAR} must be debug, info, warning, error, or none"
    exit 1
  }
  RUNTIME_LOG_ACTIVE_VALUE=$(runtime_log_level_value "$RUNTIME_LOG_ACTIVE_LEVEL") || exit 1
  RUNTIME_LOGGER=
  RUNTIME_LOGGER_READY=0
}

runtime_log_should_emit() {
  runtime_requested_level=$(runtime_log_canonical "$1") || runtime_requested_level=error
  [ "$runtime_requested_level" = error ] && return 0
  [ "${RUNTIME_LOG_ACTIVE_LEVEL:-error}" != none ] || return 1
  runtime_requested_value=$(runtime_log_level_value "$runtime_requested_level") || return 1
  [ "$runtime_requested_value" -ge "${RUNTIME_LOG_ACTIVE_VALUE:-40}" ]
}

runtime_log_ensure_logger() {
  [ "${RUNTIME_LOGGER_READY:-0}" = 1 ] && return 0
  RUNTIME_LOGGER=$(command -v logger 2>/dev/null || true)
  RUNTIME_LOGGER_READY=1
}

log() {
  runtime_log_level=info
  runtime_log_message=$*
  case "$runtime_log_message" in
    debug:\ *) runtime_log_level=debug; runtime_log_message=${runtime_log_message#debug: } ;;
    info:\ *) runtime_log_level=info; runtime_log_message=${runtime_log_message#info: } ;;
    warn:\ *) runtime_log_level=warning; runtime_log_message=${runtime_log_message#warn: } ;;
    warning:\ *) runtime_log_level=warning; runtime_log_message=${runtime_log_message#warning: } ;;
    error:\ *) runtime_log_level=error; runtime_log_message=${runtime_log_message#error: } ;;
    fatal:\ *) runtime_log_level=error; runtime_log_message=${runtime_log_message#fatal: } ;;
  esac

  runtime_log_should_emit "$runtime_log_level" || return 0
  runtime_log_line="${runtime_log_level}: ${runtime_log_message}"
  printf '%s\n' "$runtime_log_line" >&2
  runtime_log_ensure_logger
  if [ -n "${RUNTIME_LOGGER:-}" ]; then
    "$RUNTIME_LOGGER" -t "${RUNTIME_LOG_TAG:-runtime}" -- "$runtime_log_line" 2>/dev/null || true
  fi
}

fatal() {
  log "fatal: $*"
  exit 1
}
