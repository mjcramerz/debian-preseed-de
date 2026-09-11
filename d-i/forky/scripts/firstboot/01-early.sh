#!/bin/sh
set -u

PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH
umask 077

FIRSTBOOT_LOG_DIR=${FIRSTBOOT_LOG_DIR:-/var/lib/installer-state/logs/firstboot}
FIRSTBOOT_DATA_DIR=${FIRSTBOOT_DATA_DIR:-${FIRSTBOOT_LOG_DIR}/data}
FIRSTBOOT_LOG_FILE=${FIRSTBOOT_LOG_FILE:-${FIRSTBOOT_LOG_DIR}/20-firstboot.log}

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

desktop_defaults=/etc/default/labwc-desktop
if [ -e "$desktop_defaults" ] || [ -L "$desktop_defaults" ]; then
  if [ ! -f "$desktop_defaults" ] || [ -L "$desktop_defaults" ]; then
    log_line early error desktop-defaults "unsafe_path=${desktop_defaults}"
    exit 1
  fi
  chown root:root "$desktop_defaults" || {
    log_line early error desktop-defaults "owner_normalization_failed=${desktop_defaults}"
    exit 1
  }
  chmod 0644 "$desktop_defaults" || {
    log_line early error desktop-defaults "mode_normalization_failed=${desktop_defaults}"
    exit 1
  }
  log_line early info desktop-defaults "normalized=${desktop_defaults} owner=root:root mode=0644"
fi
unset desktop_defaults

redacted_cmdline() {
  redacted=
  if [ -r /proc/cmdline ]; then
    for arg in $(cat /proc/cmdline 2>/dev/null || true); do
      case "$arg" in
        primary_gpg_passphrase=*|fruux_username=*|fruux_password=*|obs_username=*|netcfg/wireless_wpa=*|wireless_wpa=*|wifi_wpa=*|*[Pp][Aa][Ss][Ss]*=*|*[Ss][Ee][Cc][Rr][Ee][Tt]*=*|*[Tt][Oo][Kk][Ee][Nn]*=*|*[Kk][Ee][Yy]*=*)
          arg=${arg%%=*}=REDACTED
          ;;
      esac
      redacted="${redacted:+$redacted }$arg"
    done
  fi
  printf '%s\n' "$redacted"
}

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

{
  printf 'timestamp=%s\n' "$(timestamp)"
  printf 'hostname=%s\n' "$(hostname 2>/dev/null || printf unknown)"
  printf 'kernel_release=%s\n' "$(uname -r 2>/dev/null || printf unknown)"
  printf 'machine=%s\n' "$(uname -m 2>/dev/null || printf unknown)"
  printf 'boot_id=%s\n' "$(cat /proc/sys/kernel/random/boot_id 2>/dev/null || printf unknown)"
  if [ -r /etc/os-release ]; then
    grep -E '^(ID|VERSION_ID|PRETTY_NAME)=' /etc/os-release || true
  fi
} >"${FIRSTBOOT_DATA_DIR}/boot.env" 2>&1 || true
chmod 0600 "${FIRSTBOOT_DATA_DIR}/boot.env" 2>/dev/null || true

redacted_cmdline >"${FIRSTBOOT_DATA_DIR}/cmdline.txt" 2>/dev/null || true
chmod 0600 "${FIRSTBOOT_DATA_DIR}/cmdline.txt" 2>/dev/null || true

if command -v systemctl >/dev/null 2>&1; then
  capture systemd-version.txt systemctl --version
  capture systemd-targets.txt systemctl list-units --type=target --all --no-pager --plain
  capture systemd-failed.txt systemctl --failed --no-pager --plain
  capture systemd-boot-state.txt systemctl status local-fs.target sysinit.target basic.target multi-user.target network-online.target --no-pager --lines=30
  for target_name in local-fs sysinit basic multi-user; do
    target_state=$(systemctl is-active "${target_name}.target" 2>/dev/null || true)
    case "$target_name" in
      local-fs) log_stage=local-filesystems ;;
      *) log_stage=$target_name ;;
    esac
    log_line "$log_stage" info systemd "${target_name}.target=${target_state:-unknown}"
  done
fi

if command -v journalctl >/dev/null 2>&1; then
  capture journal-warnings.txt journalctl -b -p warning --no-pager -n 200
fi

log_line early info firstboot "early_collection_complete=true"
exit 0
