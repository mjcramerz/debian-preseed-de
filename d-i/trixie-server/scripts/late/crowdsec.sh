#!/bin/sh
set -eu
umask 077

source_dir=${1:-}
target=${2:-/target}
[ -d "$source_dir" ] && [ -d "$target" ] || { printf '%s\n' 'fatal: CrowdSec stage paths are unavailable' >&2; exit 1; }
. "$source_dir/repo.env"
. "$source_dir/$DIR_HOSTS_INSTALLER/runtime.env"
# shellcheck disable=SC1090
. "$source_dir/scripts/common/credentials.sh"

install -d -m 0750 "$target/etc/crowdsec"
token=$(server_credential_read crowdsec_token 2>/dev/null || true)
if [ -n "$token" ]; then
  printf '%s\n' "$token" >"$target/etc/crowdsec/enrollment.token"
  chmod 0600 "$target/etc/crowdsec/enrollment.token"
fi
policy="$source_dir/$DIR_HOOKS_TARGET/etc/crowdsec/server-policy.env"
[ -f "$policy" ] && [ ! -L "$policy" ] || { printf '%s\n' 'fatal: CrowdSec policy asset is unavailable' >&2; exit 1; }
install -m 0640 "$policy" "$target/etc/crowdsec/server-policy.env"
if command -v systemctl >/dev/null 2>&1; then
  systemctl --root="$target" enable crowdsec.service
  systemctl --root="$target" enable crowdsec-firewall-bouncer.service
fi
