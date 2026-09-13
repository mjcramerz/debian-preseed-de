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

capture_file() {
  output_name=$1
  src=$2
  if [ -r "$src" ]; then
    cp "$src" "${FIRSTBOOT_DATA_DIR}/${output_name}" 2>/dev/null || true
    chmod 0600 "${FIRSTBOOT_DATA_DIR}/${output_name}" 2>/dev/null || true
  fi
}

capture_redacted_file() {
  output_name=$1
  src=$2
  output_file="${FIRSTBOOT_DATA_DIR}/${output_name}"

  if [ -r "$src" ]; then
    sed \
      -e 's/^\(MANAGED_NETWORK_WIFI_PSK=\).*/\1REDACTED/' \
      -e 's/^\(MANAGED_NETWORK_WIFI_WPA=\).*/\1REDACTED/' \
      -e 's/^\(MANAGED_NETWORK_WIFI_WEP=\).*/\1REDACTED/' \
      -e 's/^\(.*[Ww][Pp][Aa].*= \{0,1\}\).*/\1REDACTED/' \
      -e 's/^\([[:space:]]*[Ww][Pp][Aa]-[Pp][Ss][Kk][[:space:]][[:space:]]*\).*/\1REDACTED/' \
      "$src" >"$output_file" 2>/dev/null || true
    chmod 0600 "$output_file" 2>/dev/null || true
  fi
}

capture_networkctl_status() {
  # Do not report an absent backend as broken networking. A failed or expected
  # enabled backend still gets its original diagnostic, including exit status.
  networkd_state=$(timeout --kill-after=1s 3s systemctl show --property=ActiveState --value systemd-networkd.service 2>/dev/null || true)
  networkd_enabled=$(timeout --kill-after=1s 3s systemctl is-enabled systemd-networkd.service 2>/dev/null || true)
  case "${networkd_state}:${networkd_enabled}" in
    inactive:disabled|inactive:masked)
      capture networkctl-status.txt /usr/bin/printf '%s\n' 'NOT_APPLICABLE: systemd-networkd is inactive and disabled/masked; see network-targets.txt for the installed network services.'
      ;;
    *) capture networkctl-status.txt networkctl status --no-pager ;;
  esac
}

if command -v hostnamectl >/dev/null 2>&1; then
  capture hostnamectl.txt hostnamectl
else
  hostname >"${FIRSTBOOT_DATA_DIR}/hostname.txt" 2>&1 || true
  chmod 0600 "${FIRSTBOOT_DATA_DIR}/hostname.txt" 2>/dev/null || true
fi

if command -v ip >/dev/null 2>&1; then
  capture ip-brief-address.txt ip -brief addr
  capture ip-address.txt ip addr
  capture ip-route.txt ip route
  capture ip-rule.txt ip rule
fi
if command -v resolvectl >/dev/null 2>&1; then
  capture resolvectl-status.txt resolvectl status
fi
if command -v networkctl >/dev/null 2>&1; then
  capture networkctl-list.txt networkctl list --no-pager
  capture_networkctl_status
fi
if command -v ss >/dev/null 2>&1; then
  capture sockets-listening.txt ss -ltnup
fi
if command -v systemctl >/dev/null 2>&1; then
  capture network-targets.txt systemctl status network-online.target networking.service managed-network.service wpa_supplicant.service systemd-networkd.service NetworkManager.service NetworkManager-dispatcher.service --no-pager --lines=40
fi
capture_file resolv.conf.txt /etc/resolv.conf
capture_file network-interfaces.txt /etc/network/interfaces
capture_redacted_file network-managed-network.txt /etc/network/interfaces.d/50-managed-network
capture_redacted_file network-managed-network-default.txt /etc/default/managed-network

log_line network-online info network "network_collection_complete=true"
exit 0
