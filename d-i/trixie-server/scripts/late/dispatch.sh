#!/bin/sh
set -eu
umask 077

source_dir=${1:-/tmp/server-install}
target=${2:-/target}
[ -d "$source_dir" ] && [ -d "$target" ] || { printf '%s\n' 'fatal: late source or target is unavailable' >&2; exit 1; }
# shellcheck disable=SC1090
. "$source_dir/repo.env"
. "$source_dir/$DIR_HOSTS_INSTALLER/runtime.env"
. "$source_dir/$DIR_SCRIPTS_COMMON/credentials.sh"
# shellcheck disable=SC1090
. "$source_dir/$DIR_SCRIPTS_COMMON/validate.sh"
# shellcheck disable=SC1090
. "$source_dir/$DIR_HOSTS_PROFILES/shared-srv.env"
classes=${PRESEED_SERVER_CLASSES:-}
if [ -z "$classes" ]; then classes=$(server_cmdline_value classes 2>/dev/null || true); fi
if [ -z "$classes" ]; then
  # shellcheck disable=SC1090
  . "$source_dir/repo.env"
  classes=$DEBIAN_DEFAULT_CLASSES
fi
classes=$(printf '%s\n' "$classes" | tr ';' ',')
profile=$(server_profile_from_classes "$classes" 2>/dev/null || true)
profile=${profile:-btrfs-srv-flex}
# shellcheck disable=SC1090
. "$source_dir/$DIR_HOSTS_PROFILES/$profile.env"

class_selected() {
  token=$1
  old_ifs=$IFS
  IFS=',; '
  # shellcheck disable=SC2086
  set -- $classes
  IFS=$old_ifs
  for selected in "$@"; do
    case "$selected" in
      "$token"|"addon/$token"|"addon:$token"|"service/$token"|"service:$token") return 0 ;;
    esac
  done
  return 1
}

/bin/sh "$source_dir/$DIR_SCRIPTS_LATE/server-install.sh" "$source_dir" "$target"
/bin/sh "$source_dir/$DIR_SCRIPTS_LATE/forky-stage.sh" "$source_dir" "$target"
/bin/sh "$source_dir/$DIR_SCRIPTS_LATE/fstab.sh" "$source_dir" "$target"
/bin/sh "$source_dir/$DIR_SCRIPTS_LATE/boot.sh" "$source_dir" "$target" "$profile"
if class_selected wifi; then
  /bin/sh "$source_dir/$DIR_SCRIPTS_LATE/network.sh" "$source_dir" "$target" wifi "$profile"
else
  /bin/sh "$source_dir/$DIR_SCRIPTS_LATE/network.sh" "$source_dir" "$target" '' "$profile"
fi

# These are role baseline services. Their packages and policy are selected by
# the server role and the direct late flow does not consult profile booleans.
runner_kinds=
if class_selected github; then runner_kinds="$runner_kinds github"; fi
if class_selected gitlab; then runner_kinds="$runner_kinds gitlab"; fi
/bin/sh "$source_dir/$DIR_SCRIPTS_LATE/crowdsec.sh" "$source_dir" "$target"
/bin/sh "$source_dir/$DIR_SCRIPTS_LATE/apparmor.sh" "$source_dir" "$target" "$runner_kinds"
nfs_mode=
if class_selected nfs-client && [ "${NFS_CLIENT_ENABLE:-false}" = true ]; then nfs_mode=client; fi
if class_selected nfs-server && [ "${NFS_SERVER_ENABLE:-false}" = true ]; then
  [ -n "$nfs_mode" ] && nfs_mode=both || nfs_mode=server
fi
if [ -n "$nfs_mode" ]; then
  /bin/sh "$source_dir/$DIR_SCRIPTS_LATE/nfs.sh" "$source_dir" "$target" "$nfs_mode" "$profile"
fi
if [ -z "$nfs_mode" ] && { [ "${FILEN_CLI_PRIV_ENABLE:-false}" = true ] || [ "${FILEN_CLI_OFFSEC_ENABLE:-false}" = true ]; }; then
  /bin/sh "$source_dir/$DIR_SCRIPTS_LATE/nfs.sh" "$source_dir" "$target" policy "$profile"
fi
/bin/sh "$source_dir/$DIR_SCRIPTS_LATE/filen.sh" "$source_dir" "$target" "$profile"
if class_selected codex; then
  /bin/sh "$source_dir/$DIR_SCRIPTS_LATE/codex.sh" "$source_dir" "$target" "$profile"
fi

if [ -n "$runner_kinds" ]; then
  # shellcheck disable=SC2086
  /bin/sh "$source_dir/$DIR_SCRIPTS_LATE/ci-cache.sh" "$source_dir" "$target" $runner_kinds
  for kind in $runner_kinds; do
    /bin/sh "$source_dir/$DIR_SCRIPTS_LATE/runner-install.sh" "$kind" "$source_dir" "$target"
  done
fi

server_info "late staging completed for profile ${profile}"
