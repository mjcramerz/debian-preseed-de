#!/bin/sh
set -eu
umask 077

source_dir=${1:-}
target=${2:-/target}
profile=${3:-btrfs-srv-flex}
[ -d "$source_dir" ] && [ -d "$target" ] || { printf '%s\n' 'fatal: Codex stage paths are unavailable' >&2; exit 1; }
# shellcheck disable=SC1090
. "$source_dir/scripts/common/credentials.sh"
# shellcheck disable=SC1090
. "$source_dir/scripts/common/forky.sh"
# shellcheck disable=SC1090
. "$source_dir/scripts/common/validate.sh"
# shellcheck disable=SC1090
. "$source_dir/hosts/profiles/shared-srv.env"
# shellcheck disable=SC1090
. "$source_dir/hosts/profiles/$profile.env"

install_asset() {
  relative=$1
  destination=$2
  mode=$3
  source_path="$source_dir/$relative"
  target_path="$target/$destination"
  [ -f "$source_path" ] && [ ! -L "$source_path" ] || { server_fatal "missing Codex asset: $relative"; exit 1; }
  install -d -m 0750 "${target_path%/*}"
  install -m "$mode" "$source_path" "$target_path"
}

install_asset hooks/target/etc/apparmor.d/usr.local.libexec.codex etc/apparmor.d/usr.local.libexec.codex 0644
install_asset hooks/target/etc/systemd/system/codex-app.service etc/systemd/system/codex-app.service 0644
install_asset hooks/target/usr/local/libexec/codex usr/local/libexec/codex-app 0755
install_asset hooks/target/etc/sysusers.d/90-codex.conf etc/sysusers.d/90-codex.conf 0644
install_asset hooks/target/etc/tmpfiles.d/90-codex.conf etc/tmpfiles.d/90-codex.conf 0644
if [ -x "$target/usr/bin/systemd-sysusers" ]; then
  chroot "$target" /usr/bin/systemd-sysusers /etc/sysusers.d/90-codex.conf
fi
if [ -x "$target/usr/bin/systemd-tmpfiles" ]; then
  chroot "$target" /usr/bin/systemd-tmpfiles --create /etc/tmpfiles.d/90-codex.conf
fi

install -d -m 0750 "$target/etc/codex" "$target$SERVER_CODEX_STATE_DIR"
forky_base=$(server_forky_source_base "$source_dir") || exit 1
metadata_dir=$(mktemp -d /tmp/server-codex-metadata.XXXXXX)
trap 'rm -rf "$metadata_dir"' EXIT HUP INT TERM
server_forky_fetch "$forky_base" hosts/profiles/shared-de.env "$metadata_dir/shared-de.env" 0600
archive_url=$(server_forky_env_value "$metadata_dir/shared-de.env" DEVOPS_CODEX_URL) || {
  server_fatal 'Forky Codex release URL is unavailable'; exit 1;
}
case "$archive_url" in https://*) ;; *) server_fatal 'Forky Codex release URL must be HTTPS'; exit 1 ;; esac
archive="$target$SERVER_CODEX_STATE_DIR/codex.tar.gz"
/usr/bin/curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 --max-time 300 --output "$archive" "$archive_url"
tar -tzf "$archive" | awk 'BEGIN {bad=0} /^\// || /(^|\/)\.\.($|\/)/ {bad=1} END {exit bad}'
tar -xzf "$archive" --no-same-owner --no-same-permissions -C "$target$SERVER_CODEX_STATE_DIR"
rm -f "$archive"
codex_enabled=true

server_render_template "$source_dir/hooks/target/etc/codex/server.env.tmpl" \
  "$target/etc/codex/server.env" 0640 CODEX_ENABLED "$codex_enabled" \
  CODEX_HOME "$SERVER_CODEX_STATE_DIR" \
  DEVOPS_CODEX_TOOLS_ENABLE "${DEVOPS_CODEX_TOOLS_ENABLE:-false}"

if [ "$codex_enabled" = true ] && command -v systemctl >/dev/null 2>&1; then
  systemctl --root="$target" enable codex-app.service
fi
