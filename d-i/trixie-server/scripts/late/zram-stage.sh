#!/bin/sh
set -eu
umask 077

source_dir=${1:-}
target=${2:-/target}
[ -d "$source_dir" ] && [ -d "$target" ] || { printf '%s\n' 'fatal: zram stage paths are unavailable' >&2; exit 1; }
# shellcheck disable=SC1090
. "$source_dir/scripts/common/validate.sh"
# shellcheck disable=SC1090
. "$source_dir/scripts/common/credentials.sh"
# shellcheck disable=SC1090
. "$source_dir/scripts/common/forky.sh"
# shellcheck disable=SC1090
. "$source_dir/hosts/profiles/shared-srv.env"
# shellcheck disable=SC1090
. "$source_dir/hosts/installer/runtime.env"
classes=$(server_cmdline_value classes 2>/dev/null || true)
if [ -z "$classes" ]; then
  # shellcheck disable=SC1090
  . "$source_dir/repo.env"
  classes=$DEBIAN_DEFAULT_CLASSES
fi
profile=$(server_profile_from_classes "$classes" 2>/dev/null || true)
profile=${profile:-btrfs-srv-flex}
case "$profile" in
  btrfs-srv-flex|btrfs-srv-flex-duo|f2fs-srv-hp14) ;;
  *) server_fatal 'unknown server profile for zram'; exit 1 ;;
esac
# shellcheck disable=SC1090
. "$source_dir/hosts/profiles/$profile.env"

forky_base=$(server_forky_source_base "$source_dir") || exit 1

stage="$target/usr/share/zram/forky"
install -d -m 0750 "$stage"
manifest="$source_dir/zram-source.manifest"
[ -r "$manifest" ] || { server_fatal 'zram source manifest is unavailable'; exit 1; }

fetch_one() {
  relative=$1
  case "$relative" in ''|/*|*..*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_./@+-]*) server_fatal 'unsafe zram source path'; exit 1 ;; esac
  destination="$stage/$relative"
  install -d -m 0750 "${destination%/*}"
  server_forky_fetch "$forky_base" "$relative" "$destination" 0640
}

while IFS=' ' read -r marker relative remainder || [ -n "$relative" ]; do
  case "$marker:$relative" in ''*|\#*:*) continue ;; esac
  [ "$marker" = '*' ] && [ -n "$relative" ] && [ -z "$remainder" ] || {
    server_fatal 'malformed zram source manifest entry'; exit 1;
  }
  fetch_one "$relative"
done <"$manifest"

server_render_template "$source_dir/hooks/target/etc/system-config/zram-source.env.tmpl" \
  "$target/etc/system-config/zram-source.env" 0640 \
  ZRAM_SOURCE_BASE "$forky_base" ZRAM_ENABLE "${ZRAM_ENABLE:-1}" \
  ZRAM_SWAP_DEVICE "${ZRAM_SWAP_DEVICE:-/dev/zram0}" ZRAM_PCT "${ZRAM_PCT:-50}" \
  ZRAM_MIN_MIB "${ZRAM_MIN_MIB:-1024}" ZRAM_MAX_MIB "${ZRAM_MAX_MIB:-16384}" \
  ZRAM_WRITEBACK_ENABLE "${ZRAM_WRITEBACK_ENABLE:-0}"

# Keep the source separate from activation. The canonical Forky renderer owns
# placeholder materialization; this bridge records the exact source set so
# server profile variables can be passed to that renderer later.
