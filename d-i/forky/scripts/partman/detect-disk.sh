#!/bin/sh
set -eu

log() {
  printf '[detect-disk] %s\n' "$*" >&2
}

fatal() {
  log "fatal: $*"
  exit 1
}

host_profile=${1:-}

is_install_disk_name() {
  disk_name=$1

  case "$disk_name" in
    loop*|ram*|dm-*|md*) return 1 ;;
    nvme[0-9]*n[0-9]*)
      case "$disk_name" in
        *p[0-9]*) return 1 ;;
      esac
      return 0
      ;;
    mmcblk[0-9]*)
      case "$disk_name" in
        *p[0-9]*) return 1 ;;
      esac
      return 0
      ;;
    sd*|vd*|xvd*)
      case "$disk_name" in
        *[0-9]) return 1 ;;
      esac
      return 0
      ;;
  esac
  return 1
}

is_install_disk_path() {
  [ -b "$1" ] || return 1
  is_install_disk_name "${1##*/}"
}

if [ -n "${DEV_INSTALL_DISK:-}" ] && [ -b "${DEV_INSTALL_DISK}" ]; then
  is_install_disk_path "$DEV_INSTALL_DISK" || fatal "explicit DEV_INSTALL_DISK is not a whole install disk: ${DEV_INSTALL_DISK}"
  log "info: using explicit DEV_INSTALL_DISK=${DEV_INSTALL_DISK}"
  printf '%s\n' "$DEV_INSTALL_DISK"
  exit 0
fi

pattern=${INSTALL_DISK_CANDIDATES:-}
[ -n "$pattern" ] || fatal "INSTALL_DISK_CANDIDATES is required before install-disk detection"

for candidate in $pattern; do
  is_install_disk_path "$candidate" || continue
  log "info: matched install disk ${candidate}${host_profile:+ for host profile ${host_profile}}"
  printf '%s\n' "$candidate"
  exit 0
done

fatal "no install disk matched configured candidates${host_profile:+ for host profile ${host_profile}}"
