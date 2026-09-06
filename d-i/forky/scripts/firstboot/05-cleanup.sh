#!/bin/sh
set -u

PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH
umask 077

FIRSTBOOT_LOG_DIR=${FIRSTBOOT_LOG_DIR:-/var/lib/installer-state/logs/firstboot}
FIRSTBOOT_DATA_DIR=${FIRSTBOOT_DATA_DIR:-${FIRSTBOOT_LOG_DIR}/data}
FIRSTBOOT_STATE_DIR=${FIRSTBOOT_STATE_DIR:-/var/lib/installer-state/firstboot}
FIRSTBOOT_LOG_FILE=${FIRSTBOOT_LOG_FILE:-${FIRSTBOOT_LOG_DIR}/20-firstboot.log}
FIRSTBOOT_COMPLETE_FILE=${FIRSTBOOT_COMPLETE_FILE:-${FIRSTBOOT_STATE_DIR}/complete}
CLEANUP_LOG=${FIRSTBOOT_DATA_DIR}/cleanup.txt

mkdir -p "$FIRSTBOOT_LOG_DIR" "$FIRSTBOOT_DATA_DIR" "$FIRSTBOOT_STATE_DIR" 2>/dev/null || exit 1
: >>"$FIRSTBOOT_LOG_FILE" 2>/dev/null || exit 1
: >"$CLEANUP_LOG" 2>/dev/null || exit 1
chmod 0600 "$CLEANUP_LOG" 2>/dev/null || true

timestamp() {
  date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || printf '%s\n' unknown-time
}

log_line() {
  stage=$1
  level=$2
  component=$3
  shift 3
  printf '%s stage=%s level=%s component=%s %s\n' \
    "$(timestamp)" "$stage" "$level" "$component" "$*" >>"$FIRSTBOOT_LOG_FILE"
}

if [ -r /usr/local/lib/firstboot.d/logging.sh ]; then
  # shellcheck disable=SC1091
  . /usr/local/lib/firstboot.d/logging.sh
fi

write_complete_marker() {
  # Missing status is not proof of successful provisioning.
  [ "${FIRSTBOOT_OVERALL_STATUS:-unknown}" = 0 ] || return 1
  tmp_complete=$(mktemp "${FIRSTBOOT_COMPLETE_FILE}.tmp.XXXXXX") || return 1
  {
    printf 'timestamp=%s\n' "$(timestamp)"
    printf 'status=%s\n' "${FIRSTBOOT_OVERALL_STATUS:-unknown}"
    printf 'log_dir=%s\n' "$FIRSTBOOT_LOG_DIR"
  } >"$tmp_complete" 2>/dev/null || return 1
  chmod 0600 "$tmp_complete" || return 1
  mv -fT -- "$tmp_complete" "$FIRSTBOOT_COMPLETE_FILE" 2>/dev/null || {
    rm -f "$tmp_complete" 2>/dev/null || true
    return 1
  }
}

tmp_complete=
trap '[ -z "$tmp_complete" ] || rm -f -- "$tmp_complete"' EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
log_line cleanup info cleanup "cleanup_start=true"

if ! write_complete_marker; then
  log_line cleanup error cleanup "complete_marker_write_failed=${FIRSTBOOT_COMPLETE_FILE}"
  exit 1
fi

{
  printf 'firstboot_status=%s\n' "${FIRSTBOOT_OVERALL_STATUS:-unknown}"
  printf 'complete_marker=%s\n' "$FIRSTBOOT_COMPLETE_FILE"
  printf 'automatic_cleanup_service=secondboot.service\n'
} >>"$CLEANUP_LOG"

log_line cleanup info cleanup "complete_marker=${FIRSTBOOT_COMPLETE_FILE} automatic_cleanup=secondboot.service"
exit 0
