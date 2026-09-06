#!/bin/sh
set -u

PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH
umask 077

FIRSTBOOT_LOG_DIR=${FIRSTBOOT_LOG_DIR:-/var/lib/installer-state/logs/firstboot}
FIRSTBOOT_DATA_DIR=${FIRSTBOOT_DATA_DIR:-${FIRSTBOOT_LOG_DIR}/data}
FIRSTBOOT_LOG_FILE=${FIRSTBOOT_LOG_FILE:-${FIRSTBOOT_LOG_DIR}/20-firstboot.log}
FIRSTBOOT_JOURNAL_LINES=${FIRSTBOOT_JOURNAL_LINES:-300}
INITRAMFS_HEALTH_SPOOL_DIR=${INITRAMFS_HEALTH_SPOOL_DIR:-/run/installer-initramfs-health}
INITRAMFS_HEALTH_ALT_SPOOL_DIR=${INITRAMFS_HEALTH_ALT_SPOOL_DIR:-/run/initramfs/installer-initramfs-health}

mkdir -p "$FIRSTBOOT_LOG_DIR" "$FIRSTBOOT_DATA_DIR" 2>/dev/null || exit 1
: >>"$FIRSTBOOT_LOG_FILE" 2>/dev/null || exit 1

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

case "$FIRSTBOOT_JOURNAL_LINES" in
  ''|*[!0-9]*) FIRSTBOOT_JOURNAL_LINES=300 ;;
esac
if [ "$FIRSTBOOT_JOURNAL_LINES" -gt 1000 ]; then
  FIRSTBOOT_JOURNAL_LINES=1000
fi

capture() {
  output_name=$1
  shift
  output_file="${FIRSTBOOT_DATA_DIR}/${output_name}"
  {
    printf '# command:'
    for arg in "$@"; do
      printf ' %s' "$arg"
    done
    printf '\n'
    timeout --signal=TERM --kill-after=2s 20s "$@"
  } >"$output_file" 2>&1 || printf 'status=%s\n' "$?" >>"$output_file"
  chmod 0600 "$output_file" 2>/dev/null || true
}

copy_log_atomic() {
  src=$1
  dest=$2
  tmp="${dest}.tmp.$$"

  cp "$src" "$tmp" 2>/dev/null || {
    rm -f "$tmp" 2>/dev/null || true
    return 1
  }
  chmod 0600 "$tmp" 2>/dev/null || true
  mv -f "$tmp" "$dest" 2>/dev/null || {
    rm -f "$tmp" 2>/dev/null || true
    return 1
  }
}

copy_initramfs_spool_dir() {
  spool_dir=$1
  target_dir=$2
  copied=0

  [ -d "$spool_dir" ] || return 0
  mkdir -p "$target_dir" 2>/dev/null || {
    log_line log-collection warn initramfs "spool_copy_failed=${spool_dir} target=${target_dir}"
    return 0
  }

  for spooled_log in "${spool_dir}"/*.log; do
    [ -f "$spooled_log" ] || continue
    if copy_log_atomic "$spooled_log" "${target_dir}/${spooled_log##*/}"; then
      copied=$((copied + 1))
    else
      log_line log-collection warn initramfs "spool_log_copy_failed=${spooled_log}"
    fi
  done
  chmod 0700 "$target_dir" 2>/dev/null || true
  log_line log-collection info initramfs "spool=${spool_dir} copied=${copied}"
}

copy_initramfs_spool_logs() {
  target_dir=$1

  copy_initramfs_spool_dir "$INITRAMFS_HEALTH_SPOOL_DIR" "$target_dir"
  if [ "$INITRAMFS_HEALTH_ALT_SPOOL_DIR" != "$INITRAMFS_HEALTH_SPOOL_DIR" ]; then
    copy_initramfs_spool_dir "$INITRAMFS_HEALTH_ALT_SPOOL_DIR" "$target_dir"
  fi
}

# Firstboot runs after switch-root; this is the target root path, not initramfs /var.
target_initramfs_log_dir=/var/lib/installer-state/logs/initramfs
copy_initramfs_spool_logs "$target_initramfs_log_dir"
if [ -d "$target_initramfs_log_dir" ]; then
  capture initramfs-log-files.txt find "$target_initramfs_log_dir" -maxdepth 1 -type f -name '*.log' -print
  log_line log-collection info initramfs "available=${target_initramfs_log_dir}"
else
  log_line log-collection warn initramfs "missing=${target_initramfs_log_dir}"
fi

if command -v systemctl >/dev/null 2>&1; then
  capture systemctl-failed.txt systemctl --failed --no-pager --plain
  capture systemctl-jobs.txt systemctl list-jobs --no-pager --plain
fi
if command -v journalctl >/dev/null 2>&1; then
  capture journal-warnings.txt journalctl -p warning..alert -b --no-pager --no-hostname -o short-iso -n "$FIRSTBOOT_JOURNAL_LINES"
fi
if command -v dmesg >/dev/null 2>&1; then
  capture dmesg-warnings.txt dmesg --level=err,warn
fi
if command -v findmnt >/dev/null 2>&1; then
  capture findmnt-verify.txt findmnt --verify --verbose
  capture mounts.txt findmnt -R / -o TARGET,SOURCE,FSTYPE,OPTIONS
fi
if command -v lsblk >/dev/null 2>&1; then
  capture block-devices.txt lsblk -o NAME,TYPE,SIZE,FSTYPE,LABEL,UUID,MOUNTPOINTS
fi
if [ -r /etc/fstab ]; then
  cp /etc/fstab "${FIRSTBOOT_DATA_DIR}/fstab.txt" 2>/dev/null || true
  chmod 0600 "${FIRSTBOOT_DATA_DIR}/fstab.txt" 2>/dev/null || true
fi
if command -v systemd-analyze >/dev/null 2>&1; then
  capture systemd-analyze-time.txt systemd-analyze time
  systemd-analyze blame 2>&1 | sed -n '1,80p' >"${FIRSTBOOT_DATA_DIR}/systemd-analyze-blame.txt" || true
  chmod 0600 "${FIRSTBOOT_DATA_DIR}/systemd-analyze-blame.txt" 2>/dev/null || true
fi

log_line log-collection info firstboot "collection_complete=true"
exit 0
