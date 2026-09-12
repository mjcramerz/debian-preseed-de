#!/bin/sh
set -u

PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH
umask 077

FIRSTBOOT_LOG_DIR=${FIRSTBOOT_LOG_DIR:-/var/lib/installer-state/logs/firstboot}
FIRSTBOOT_DATA_DIR=${FIRSTBOOT_DATA_DIR:-${FIRSTBOOT_LOG_DIR}/data}
FIRSTBOOT_STATE_DIR=${FIRSTBOOT_STATE_DIR:-/var/lib/installer-state/firstboot}
FIRSTBOOT_SCRIPT_DIR=${FIRSTBOOT_SCRIPT_DIR:-/usr/local/lib/firstboot.d}
FIRSTBOOT_LOG_FILE=${FIRSTBOOT_LOG_FILE:-${FIRSTBOOT_LOG_DIR}/20-firstboot.log}
FIRSTBOOT_STATUS_FILE=${FIRSTBOOT_STATUS_FILE:-${FIRSTBOOT_LOG_DIR}/status.env}
FIRSTBOOT_COMPLETE_FILE=${FIRSTBOOT_COMPLETE_FILE:-${FIRSTBOOT_STATE_DIR}/complete}
export FIRSTBOOT_LOG_DIR FIRSTBOOT_DATA_DIR FIRSTBOOT_STATE_DIR
export FIRSTBOOT_SCRIPT_DIR FIRSTBOOT_LOG_FILE FIRSTBOOT_STATUS_FILE
export FIRSTBOOT_COMPLETE_FILE

FIRSTBOOT_STAGE_TIMEOUT=${FIRSTBOOT_STAGE_TIMEOUT:-360}
case "$FIRSTBOOT_STAGE_TIMEOUT" in
  ''|*[!0-9]*|0) printf '%s\n' 'fatal: invalid FIRSTBOOT_STAGE_TIMEOUT' >&2; exit 64 ;;
esac
[ "$FIRSTBOOT_STAGE_TIMEOUT" -le 3600 ] || exit 64
for directory in "$FIRSTBOOT_LOG_DIR" "$FIRSTBOOT_DATA_DIR" "$FIRSTBOOT_STATE_DIR"; do
  case "$directory" in /*) ;; *) printf '%s\n' 'fatal: firstboot paths must be absolute' >&2; exit 64 ;; esac
  [ ! -L "$directory" ] || { printf '%s\n' 'fatal: symlink firstboot directory' >&2; exit 1; }
  mkdir -p "$directory" || exit 1
  chmod 0700 "$directory" || exit 1
done
[ ! -L "$FIRSTBOOT_LOG_FILE" ] && [ ! -L "$FIRSTBOOT_STATE_DIR/lock" ] || exit 1
: >>"$FIRSTBOOT_LOG_FILE" || exit 1
chmod 0600 "$FIRSTBOOT_LOG_FILE" || exit 1
# Never unlink an advisory lock: all contenders must lock the same inode.
exec 9>>"$FIRSTBOOT_STATE_DIR/lock" || exit 1
flock -n 9 || { printf '%s\n' 'firstboot: another invocation holds the lock' >&2; exit 75; }
chmod 0600 "$FIRSTBOOT_STATE_DIR/lock" || exit 1
[ ! -L "$FIRSTBOOT_COMPLETE_FILE" ] || exit 1
if [ -f "$FIRSTBOOT_COMPLETE_FILE" ] && grep -Fqx 'status=0' "$FIRSTBOOT_COMPLETE_FILE"; then
  printf '%s\n' 'firstboot: successful completion already recorded'
  exit 0
fi
child_pid=
tmp_status=
cleanup() {
  cleanup_status=$?
  trap '' HUP INT TERM
  trap - EXIT
  if [ -n "$child_pid" ]; then
    # GNU timeout forwards TERM to its process group and escalates after 5s.
    kill -TERM "$child_pid" 2>/dev/null || true
    wait "$child_pid" 2>/dev/null || true
  fi
  [ -z "$tmp_status" ] || rm -f -- "$tmp_status"
  exit "$cleanup_status"
}
interrupted() {
  signal_status=$1
  trap '' HUP INT TERM
  write_status "$signal_status" || true
  log_line interrupted error firstboot "status=${signal_status}" || true
  exit "$signal_status"
}
trap cleanup EXIT
trap 'interrupted 129' HUP
trap 'interrupted 130' INT
trap 'interrupted 143' TERM

timestamp() {
  date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || printf '%s\n' unknown-time
}

log_line() {
  stage=$1
  level=$2
  component=$3
  shift 3
  printf '%s stage=%s level=%s component=%s %s\n' \
    "$(timestamp)" \
    "$stage" \
    "$level" \
    "$component" \
    "$*" >>"$FIRSTBOOT_LOG_FILE"
}

if [ -r "${FIRSTBOOT_SCRIPT_DIR}/logging.sh" ]; then
  # shellcheck disable=SC1090
  . "${FIRSTBOOT_SCRIPT_DIR}/logging.sh"
fi

write_status() {
  status_value=$1
  tmp_status=$(mktemp "${FIRSTBOOT_STATUS_FILE}.tmp.XXXXXX") || return 1
  {
    printf 'timestamp=%s\n' "$(timestamp)"
    printf 'status=%s\n' "$status_value"
  } >"$tmp_status" || return 1
  chmod 0600 "$tmp_status" || return 1
  mv -fT -- "$tmp_status" "$FIRSTBOOT_STATUS_FILE" || return 1
  tmp_status=
}

run_step() {
  script_name=$1
  script_path="${FIRSTBOOT_SCRIPT_DIR}/${script_name}"

  if [ ! -x "$script_path" ]; then
    printf 'firstboot: missing executable stage: %s\n' "$script_path" >&2
    log_line first_boot error firstboot "missing_stage=${script_path}"
    return 127
  fi

  log_line first_boot info firstboot "start_stage=${script_name}"
  # Closing fd 9 keeps daemonized stage descendants from retaining our lock.
  timeout --signal=TERM --kill-after=5s "${FIRSTBOOT_STAGE_TIMEOUT}s" \
    "$script_path" 9>&- >>"$FIRSTBOOT_LOG_FILE" 2>&1 &
  child_pid=$!
  wait "$child_pid"
  step_status=$?
  child_pid=
  if [ "$step_status" -eq 0 ]; then
    log_line first_boot info firstboot "completed_stage=${script_name}"
  else
    printf 'firstboot: stage=%s status=%s; details=%s\n' \
      "$script_name" "$step_status" "$FIRSTBOOT_LOG_FILE" >&2
    log_line first_boot error firstboot "failed_stage=${script_name} status=${step_status}"
  fi
  return "$step_status"
}

overall_status=0
log_line systemd-start info firstboot "wrapper_start=true"
log_line systemd-start info firstboot "hostname=$(hostname 2>/dev/null || printf unknown)"
log_line systemd-start info firstboot "kernel=$(uname -r 2>/dev/null || printf unknown)"

for stage_script in 01-early.sh 02-collect.sh 03-network.sh 04-validation.sh; do
  if ! run_step "$stage_script"; then
    overall_status=1
  fi
done

FIRSTBOOT_OVERALL_STATUS=$overall_status
export FIRSTBOOT_OVERALL_STATUS
write_status "$overall_status" || exit 1

# A failed diagnostic run remains retryable and must never publish completion.
if [ "$overall_status" -eq 0 ] && ! run_step 05-cleanup.sh; then
  overall_status=1
  FIRSTBOOT_OVERALL_STATUS=$overall_status
  export FIRSTBOOT_OVERALL_STATUS
  write_status "$overall_status" || exit 1
fi

if [ "$overall_status" -eq 0 ]; then
  log_line complete info firstboot "firstboot_status=pass"
else
  printf 'firstboot: validation failed; results=%s/validation-results.txt\n' "$FIRSTBOOT_DATA_DIR" >&2
  log_line complete warn firstboot "firstboot_status=diagnostic-failures-recorded"
fi

exit "$overall_status"
