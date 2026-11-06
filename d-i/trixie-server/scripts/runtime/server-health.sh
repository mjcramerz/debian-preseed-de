#!/bin/sh
set -eu
umask 077

PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH

state_dir=/var/lib/system-state
mkdir -p "$state_dir"
chmod 0750 "$state_dir"

write_state() {
  name=$1
  value=$2
  case "$name:$value" in
    *[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.:-]*)
      printf '%s\n' 'fatal: invalid health state value' >&2; exit 1 ;;
  esac
  printf '%s=%s\n' "$name" "$value" >>"$state_dir/health.tmp"
}

tmp="$state_dir/health.tmp"
rm -f "$tmp"
write_state format 1
write_state timestamp "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
if systemctl is-system-running --quiet 2>/dev/null; then
  write_state systemd running
else
  write_state systemd degraded
fi
if command -v nft >/dev/null 2>&1 && nft list table inet policy >/dev/null 2>&1; then
  write_state nftables loaded
else
  write_state nftables unavailable
fi
chmod 0640 "$tmp"
mv -f "$tmp" "$state_dir/health"
