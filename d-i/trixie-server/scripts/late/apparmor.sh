#!/bin/sh
set -eu
umask 077

source_dir=${1:-}
target=${2:-/target}
runner_kinds=${3:-}
[ -d "$source_dir" ] && [ -d "$target" ] || { printf '%s\n' 'fatal: AppArmor stage paths are unavailable' >&2; exit 1; }
. "$source_dir/repo.env"
. "$source_dir/$DIR_HOSTS_INSTALLER/runtime.env"

install_profile() {
  name=$1
  source_profile="$source_dir/$DIR_HOOKS_TARGET/etc/apparmor.d/$name"
  destination="$target/etc/apparmor.d/$name"
  [ -f "$source_profile" ] && [ ! -L "$source_profile" ] || { printf 'fatal: AppArmor profile is unavailable: %s\n' "$name" >&2; exit 1; }
  install -d -m 0755 "${destination%/*}"
  install -m 0644 "$source_profile" "$destination"
}

for kind in $runner_kinds; do
  case "$kind" in
    github) install_profile ci-github-runner; install_profile ci-github-podman ;;
    gitlab) install_profile ci-gitlab-runner; install_profile ci-gitlab-podman ;;
    *) printf '%s\n' 'fatal: invalid runner kind for AppArmor' >&2; exit 1 ;;
  esac
done
if [ -n "$runner_kinds" ]; then
  install_profile ci-buildbuddy
fi
if command -v systemctl >/dev/null 2>&1; then
  systemctl --root="$target" enable apparmor.service
fi
