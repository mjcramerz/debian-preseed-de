#!/bin/sh
set -eu
umask 077

source_dir=${1:-}
target=${2:-/target}
profile=${3:-btrfs-srv-flex}
[ -d "$source_dir" ] && [ ! -L "$source_dir" ] && [ -d "$target" ] && [ ! -L "$target" ] || {
  printf '%s\n' 'fatal: Filen stage paths are unavailable' >&2; exit 1;
}
case "$profile" in
  btrfs-srv-flex|btrfs-srv-flex-duo|f2fs-srv-hp14) ;;
  *) printf '%s\n' 'fatal: unknown server profile for Filen' >&2; exit 1 ;;
esac

. "$source_dir/repo.env"
. "$source_dir/$DIR_HOSTS_INSTALLER/runtime.env"
. "$source_dir/$DIR_SCRIPTS_COMMON/credentials.sh"
. "$source_dir/$DIR_SCRIPTS_COMMON/validate.sh"
. "$source_dir/$DIR_HOSTS_PROFILES/shared-srv.env"
. "$source_dir/$DIR_HOSTS_PROFILES/$profile.env"

filen_priv_enable=${FILEN_CLI_PRIV_ENABLE:-false}
filen_offsec_enable=${FILEN_CLI_OFFSEC_ENABLE:-false}
case "$filen_priv_enable:$filen_offsec_enable" in
  false:false) exit 0 ;;
  true:true|true:false|false:true) ;;
  *) server_fatal 'Filen enable flags must be true or false'; exit 1 ;;
esac

primary_user=$(server_credential_read primary_user) || {
  server_fatal 'PRESEED_PRIMARY_USERNAME is required for Filen'; exit 1;
}
server_valid_username "$primary_user" || {
  server_fatal 'primary username is invalid for Filen'; exit 1;
}
account_home=$(chroot "$target" /usr/bin/getent passwd "$primary_user" 2>/dev/null | awk -F: 'NR == 1 { print $6; exit }')
[ -n "$account_home" ] || { server_fatal 'primary account home is unavailable for Filen'; exit 1; }

[ -d "$target/tmp" ] && [ ! -L "$target/tmp" ] || {
  server_fatal 'target /tmp is unavailable for Filen staging'; exit 1;
}
filen_stage=$(mktemp -d "$target/tmp/installer-filen.XXXXXX") || {
  server_fatal 'cannot create private Filen staging directory'; exit 1;
}
chmod 0700 "$filen_stage"
filen_stage_name=${filen_stage##*/}
filen_stage_target="/tmp/$filen_stage_name"
filen_skel="$target/etc/skel-desktop"
filen_skel_created=false

cleanup_filen() {
  status=$?
  trap - EXIT HUP INT TERM
  rm -rf -- "$filen_stage"
  if [ "$filen_skel_created" = true ]; then
    rm -rf -- "$filen_skel"
  fi
  exit "$status"
}
trap cleanup_filen EXIT HUP INT TERM

stage_filen_asset() {
  relative=$1
  source_path="$source_dir/forky/$relative"
  destination="$filen_stage/assets/$relative"
  [ -f "$source_path" ] && [ ! -L "$source_path" ] || {
    server_fatal "missing embedded Forky Filen asset: $relative"; exit 1;
  }
  install -d -m 0700 "${destination%/*}"
  install -m 0600 "$source_path" "$destination"
}

install -m 0600 "$source_dir/forky/scripts/desktop/filen-install.py" "$filen_stage/install.py"
stage_filen_asset hooks/target/etc/apparmor.d/filen-sync.tmpl
stage_filen_asset hooks/target/etc/systemd/system/filen-sync@.service.tmpl
stage_filen_asset hooks/target/usr/local/libexec/filen-sync
stage_filen_asset hooks/target/usr/local/lib/perl5/site_perl/filen/FilenSync/Config.pm
stage_filen_asset hooks/target/usr/local/lib/perl5/site_perl/filen/FilenSync/Daemon.pm
stage_filen_asset hooks/target/usr/local/lib/perl5/site_perl/runtime/Managed/Process.pm

stage_filen_credential() {
  identifier=$1
  destination=$2
  value=$(server_credential_read "$identifier") || {
    server_fatal "missing protected Filen credential: $identifier"; exit 1;
  }
  [ -n "$value" ] || { server_fatal "empty protected Filen credential: $identifier"; exit 1; }
  printf '%s' "$value" >"$filen_stage/$destination"
  chmod 0600 "$filen_stage/$destination"
  unset value
}

if [ "$filen_priv_enable" = true ]; then
  stage_filen_credential filen_priv_email priv-email
  stage_filen_credential filen_priv_password priv-password
  stage_filen_credential filen_priv_2fa_seed priv-2fa_seed
fi
if [ "$filen_offsec_enable" = true ]; then
  stage_filen_credential filen_offsec_email offsec-email
  stage_filen_credential filen_offsec_password offsec-password
  stage_filen_credential filen_offsec_2fa_seed offsec-2fa_seed
fi

# Forky's installer expects the desktop bookmark seed as an input. Trixie has
# no desktop profile, so provide a private empty seed and remove it after the
# existing installer publishes the server services and policies.
[ ! -e "$filen_skel" ] && [ ! -L "$filen_skel" ] || {
  server_fatal 'unexpected desktop skeleton in a server target'; exit 1;
}
install -d -m 0755 "$filen_skel/.config/gtk-3.0"
install -m 0644 /dev/null "$filen_skel/.config/gtk-3.0/bookmarks"
filen_skel_created=true

chroot "$target" /usr/bin/env -i \
  HOME=/root LC_ALL=C.UTF-8 SYSTEMD_OFFLINE=1 PATH=/usr/sbin:/usr/bin:/sbin:/bin \
  FILEN_CLI_VERSION="$FILEN_CLI_VERSION" FILEN_CLI_URL="$FILEN_CLI_URL" \
  FILEN_CLI_SHA256="$FILEN_CLI_SHA256" FILEN_CLI_ARCHITECTURE="$FILEN_CLI_ARCHITECTURE" \
  FILEN_CLI_MINIMUM_BYTES="$FILEN_CLI_MINIMUM_BYTES" FILEN_CLI_MAXIMUM_BYTES="$FILEN_CLI_MAXIMUM_BYTES" \
  FILEN_CLI_PRIV_ENABLE="$filen_priv_enable" FILEN_CLI_OFFSEC_ENABLE="$filen_offsec_enable" \
  FILEN_CLI_PRIV_SYNC_MODE="${FILEN_CLI_PRIV_SYNC_MODE:-}" \
  FILEN_CLI_OFFSEC_SYNC_MODE="${FILEN_CLI_OFFSEC_SYNC_MODE:-}" \
  FILEN_CLI_PRIV_REMOTE_PATH="$FILEN_CLI_PRIV_REMOTE_PATH" \
  FILEN_CLI_OFFSEC_REMOTE_PATH="$FILEN_CLI_OFFSEC_REMOTE_PATH" \
  NETWORK_SHARING_ROOT_PATH="$NETWORK_SHARING_ROOT_PATH" \
  NETWORK_SHARING_HOME_BIND_PATH="$NETWORK_SHARING_HOME_BIND_PATH" \
  ACCOUNT_USERNAME="$primary_user" ACCOUNT_HOME="$account_home" \
  /usr/bin/python3 -I -B "$filen_stage_target/install.py" "$filen_stage_target"

server_info "configured Forky Filen sync installer for profile $profile"
