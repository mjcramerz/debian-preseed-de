#!/bin/sh
set -eu
umask 077

source_dir=${1:-}
target=${2:-/target}
mode=${3:-}
profile=${4:-btrfs-srv-flex}
[ -d "$source_dir" ] && [ -d "$target" ] || { printf '%s\n' 'fatal: NFS stage paths are unavailable' >&2; exit 1; }
case "$mode" in client|server|both) ;; '') exit 0 ;; *) printf '%s\n' 'fatal: NFS mode must be client, server, or both' >&2; exit 1 ;; esac
case "$profile" in
  btrfs-srv-flex|btrfs-srv-flex-duo|f2fs-srv-hp14) ;;
  *) printf '%s\n' 'fatal: unknown server profile for NFS policy' >&2; exit 1 ;;
esac
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
# shellcheck disable=SC1090
. "$source_dir/hosts/installer/identity.env"

interface=$(server_answer_value netcfg/choose_interface choose_interface interface) || {
  server_fatal 'static installer interface is required for NFS policy'; exit 1;
}
case "$interface" in
  ''|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-]*|????????????????*)
    server_fatal 'NFS interface is invalid'; exit 1 ;;
esac

server_enable=${NFS_SERVER_ENABLE:-false}
client_enable=${NFS_CLIENT_ENABLE:-false}
case "$mode" in
  server) client_enable=false ;;
  client) server_enable=false ;;
esac
client_read_only=${NFS_CLIENT_READ_ONLY:-false}
account_user=$(server_credential_read primary_user) || { server_fatal 'primary account is required for NFS policy'; exit 1; }
account_home=$(chroot "$target" /usr/bin/getent passwd "$account_user" 2>/dev/null | awk -F: 'NR == 1 { print $6; exit }')
[ -n "$account_home" ] || { server_fatal 'primary account home is unavailable in target'; exit 1; }
account_uid=$(chroot "$target" /usr/bin/id -u "$account_user")
account_gid=$(chroot "$target" /usr/bin/id -g "$account_user")

forky_base=$(server_forky_source_base "$source_dir") || exit 1
stage="$target/tmp/server-network-sharing"
rm -rf -- "$stage"
install -d -m 0700 "$stage/assets"
trap 'rm -rf -- "$stage"' EXIT HUP INT TERM
server_forky_fetch "$forky_base" scripts/late/network-sharing.py "$stage/network-sharing.py" 0600

fetch_asset() {
  relative=$1
  destination="$stage/assets/$relative"
  install -d -m 0700 "${destination%/*}"
  server_forky_fetch "$forky_base" "hooks/target/$relative" "$destination" 0600
}

fetch_asset etc/exports.tmpl
fetch_asset etc/idmapd.conf.tmpl
fetch_asset etc/nfs.conf.d/60-network-sharing.conf.tmpl
fetch_asset etc/sysctl.d/60-network-sharing.conf.tmpl
fetch_asset etc/systemd/system/nfs-server.service.d/60-network-sharing.conf.tmpl
fetch_asset etc/systemd/system/nfs-mountd.service.d/60-network-sharing.conf
fetch_asset etc/systemd/system/nfs-idmapd.service.d/60-network-sharing.conf
fetch_asset etc/systemd/system/network-sharing-identity.service
fetch_asset etc/systemd/system/network-sharing-report.service.tmpl
fetch_asset usr/local/libexec/network-sharing-identity
fetch_asset usr/local/libexec/network-sharing-report

if [ -x "$target/usr/bin/chroot" ] && [ -x "$target/usr/bin/python3" ]; then
  if [ "$server_enable" = true ]; then
    server_render_template "$source_dir/hooks/target/etc/nftables.d/91-nfs.tmpl" \
      "$target/etc/nftables.d/91-nfs.nft" 0644 \
      NFS_SERVER_PORT "$NFS_SERVER_PORT" NFS_SERVER_EXPORT_CIDR "$NFS_SERVER_EXPORT_CIDR"
  fi
  chroot "$target" /usr/bin/env \
    PATH=/usr/sbin:/usr/bin:/sbin:/bin \
    LANG=C LC_ALL=C DEBIAN_FRONTEND=noninteractive DEBCONF_NONINTERACTIVE_SEEN=true \
    SYSTEMD_OFFLINE=1 \
    ACCOUNT_USERNAME="$account_user" ACCOUNT_HOME="$account_home" \
    SYSTEM_DOMAIN="${SYSTEM_DOMAIN:-${SERVER_DOMAIN:-lan.icramer.com}}" NFT_PROFILE="${NFT_PROFILE:-default}" \
    NETWORK_SHARING_ROOT_PATH="$NETWORK_SHARING_ROOT_PATH" \
    NETWORK_SHARING_HOME_BIND_PATH="$NETWORK_SHARING_HOME_BIND_PATH" \
    NFS_SERVER_ENABLE="$server_enable" NFS_SERVER_PATH="$NFS_SERVER_PATH" \
    NFS_SERVER_APT_DEPS="$NFS_SERVER_APT_DEPS" NFS_SERVER_PORT="$NFS_SERVER_PORT" \
    NFS_SERVER_THREADS="$NFS_SERVER_THREADS" NFS_SERVER_RW_OPTIONS="$NFS_SERVER_RW_OPTIONS" \
    NFS_SERVER_RO_OPTIONS="$NFS_SERVER_RO_OPTIONS" NFS_SERVER_EXPORTS="$NFS_SERVER_EXPORTS" \
    NFS_CLIENT_ENABLE="$client_enable" NFS_CLIENT_PATH="$NFS_CLIENT_MOUNT_PATH" \
    NFS_CLIENT_TARGET_IP="$NFS_CLIENT_TARGET_IP" NFS_CLIENT_EXPORT_PATH="$NFS_CLIENT_EXPORT_PATH" \
    NFS_CLIENT_VERSION="$NFS_CLIENT_VERSION" NFS_CLIENT_READ_ONLY="$client_read_only" \
    NFS_CLIENT_MOUNT_TIMEOUT="$NFS_CLIENT_MOUNT_TIMEOUT" NFS_CLIENT_APT_DEPS="$NFS_CLIENT_APT_DEPS" \
    NFS_MNT_CLIENT_TARGET_SHARE_OPTS="$NFS_MNT_CLIENT_TARGET_SHARE_OPTS" \
    NFS_ACCOUNT_UID="$account_uid" NFS_ACCOUNT_GID="$account_gid" \
    NFS_SHARED_GROUP="$NFS_SHARED_GROUP" NFS_SHARED_GID="$NFS_SHARED_GID" \
    NFS_INTERFACES="$interface" NFS_TCP_RMEM="$NFS_TCP_RMEM" NFS_TCP_WMEM="$NFS_TCP_WMEM" \
    NFS_SOCKET_RMEM_MAX="$NFS_SOCKET_RMEM_MAX" NFS_SOCKET_WMEM_MAX="$NFS_SOCKET_WMEM_MAX" \
    /usr/bin/python3 -I -B /tmp/server-network-sharing/network-sharing.py /tmp/server-network-sharing/assets
else
  server_fatal 'target Python runtime is unavailable for the canonical Forky NFS implementation'
  exit 1
fi
