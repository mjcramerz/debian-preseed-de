#!/bin/sh
set -eu
umask 077

source_dir=${1:-}
target=${2:-/target}
runner_kinds=${3:-}
[ -d "$source_dir" ] && [ -d "$target" ] || { printf '%s\n' 'fatal: AppArmor stage paths are unavailable' >&2; exit 1; }
if [ -n "$runner_kinds" ]; then
  source_profile="$source_dir/hooks/target/etc/apparmor.d/usr.local.libexec.runner"
  [ -f "$source_profile" ] && [ ! -L "$source_profile" ] || { printf '%s\n' 'fatal: runner AppArmor profile is unavailable' >&2; exit 1; }
  install -d -m 0755 "$target/etc/apparmor.d"
  install -m 0644 "$source_profile" "$target/etc/apparmor.d/usr.local.libexec.runner"
fi
if command -v systemctl >/dev/null 2>&1; then
  systemctl --root="$target" enable apparmor.service
fi
