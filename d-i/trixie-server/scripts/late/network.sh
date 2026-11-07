#!/bin/sh
set -eu
umask 077

source_dir=${1:-}
target=${2:-/target}
wifi_class=${3:-}
profile=${4:-btrfs-srv-flex}
[ -d "$source_dir" ] && [ -d "$target" ] || { printf '%s\n' 'fatal: network stage paths are unavailable' >&2; exit 1; }
. "$source_dir/repo.env"
. "$source_dir/$DIR_HOSTS_INSTALLER/runtime.env"
# shellcheck disable=SC1090
. "$source_dir/$DIR_SCRIPTS_COMMON/forky.sh"
# shellcheck disable=SC1090
. "$source_dir/scripts/common/credentials.sh"
# shellcheck disable=SC1090
. "$source_dir/scripts/common/validate.sh"
# shellcheck disable=SC1090
. "$source_dir/hosts/profiles/shared-srv.env"
# shellcheck disable=SC1090
. "$source_dir/hosts/installer/identity.env"
# shellcheck disable=SC1090
. "$source_dir/hosts/profiles/$profile.env"
server_forky_identity_load "$source_dir"

interface=$(server_answer_value netcfg/choose_interface choose_interface interface) || { server_fatal 'static installer interface is required from the kernel command line or debconf'; exit 1; }
address=$(server_answer_value netcfg/get_ipaddress ip) || { server_fatal 'static installer IP is required from the kernel command line or debconf'; exit 1; }
netmask=$(server_answer_value netcfg/get_netmask netmask) || { server_fatal 'static installer netmask is required from the kernel command line or debconf'; exit 1; }
gateway=$(server_answer_value netcfg/get_gateway gateway) || { server_fatal 'static installer gateway is required from the kernel command line or debconf'; exit 1; }
nameservers=$(server_answer_value netcfg/get_nameservers nameservers dns 2>/dev/null || true)
nameservers=${nameservers:-${STATIC_INSTALLER_NAMESERVER:-}}
[ -n "$nameservers" ] || { server_fatal 'static installer nameservers are required from the kernel command line or debconf'; exit 1; }
prefix=$(server_ipv4_netmask_prefix "$netmask") || { server_fatal 'static installer netmask is invalid'; exit 1; }
cidr=$address/$prefix
case "$interface" in ''|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-]*|????????????????*) server_fatal 'static installer interface is invalid'; exit 1 ;; esac
case "$address:$gateway" in *[!0-9.]*) server_fatal 'static network addresses contain unsupported characters'; exit 1 ;; esac
case "$nameservers" in *[!0-9.,]*) server_fatal 'static nameservers contain unsupported characters'; exit 1 ;; esac

install -d -m 0755 "$target/etc/network/interfaces.d" "$target/etc/system-config"
server_render_template "$source_dir/$DIR_HOOKS_TARGET/etc/network/interfaces.d/90-policy.tmpl" \
  "$target/etc/network/interfaces.d/90-policy" 0644 \
  NETWORK_INTERFACE "$interface" NETWORK_CIDR "$cidr" NETWORK_GATEWAY "$gateway" \
  NETWORK_NAMESERVERS "$nameservers"

if [ "$wifi_class" = wifi ]; then
  wifi_interface=$(server_credential_read wifi_interface) || { server_fatal 'PRESEED_WIFI_INTERFACE is required'; exit 1; }
  wifi_essid=$(server_credential_read wifi_essid) || { server_fatal 'PRESEED_WIFI_ESSID is required'; exit 1; }
  wifi_security=$(server_credential_read wifi_security) || { server_fatal 'PRESEED_WIFI_SECURITY is required'; exit 1; }
  wifi_cidr=$(server_credential_read wifi_cidr) || { server_fatal 'PRESEED_WIFI_CIDR is required'; exit 1; }
  wifi_passphrase=$(server_credential_read wifi_passphrase 2>/dev/null || true)
  case "$wifi_interface" in ''|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-]*|????????????????*) server_fatal 'PRESEED_WIFI_INTERFACE is invalid'; exit 1 ;; esac
  case "$wifi_security" in
    open) wifi_security_kind=open ;;
    wpa-psk|wpa2-psk) [ -n "$wifi_passphrase" ] || { server_fatal 'WPA Wi-Fi requires a passphrase'; exit 1; }; wifi_security_kind=wpa-psk ;;
    wpa3-sae) [ -n "$wifi_passphrase" ] || { server_fatal 'SAE Wi-Fi requires a passphrase'; exit 1; }; wifi_security_kind=wpa3-sae ;;
    *) server_fatal 'PRESEED_WIFI_SECURITY is invalid'; exit 1 ;;
  esac
  install -d -m 0700 "$target/etc/NetworkManager/system-connections"
  case "$wifi_security_kind" in
    open) wifi_template=managed-wifi-open.nmconnection.tmpl ;;
    wpa-psk) wifi_template=managed-wifi-wpa-psk.nmconnection.tmpl ;;
    wpa3-sae) wifi_template=managed-wifi-wpa3-sae.nmconnection.tmpl ;;
  esac
  server_render_template "$source_dir/$DIR_HOOKS_TARGET/etc/NetworkManager/system-connections/$wifi_template" \
    "$target/etc/NetworkManager/system-connections/managed-wifi.nmconnection" 0600 \
    WIFI_INTERFACE "$wifi_interface" WIFI_ESSID "$wifi_essid" WIFI_CIDR "$wifi_cidr" \
    WIFI_PASSPHRASE "$wifi_passphrase"
fi

server_render_template "$source_dir/$DIR_HOOKS_TARGET/etc/system-config/network.env.tmpl" \
  "$target/etc/system-config/network.env" 0640 \
  NETWORK_INTERFACE "$interface" NETWORK_CIDR "$cidr" NETWORK_GATEWAY "$gateway" \
  NETWORK_NAMESERVERS "$nameservers" IPV6_POLICY "${SERVER_IPV6_POLICY:-enabled}" \
  PROFILE "$profile" FILESYSTEM "${PARTMAN_RECIPE_NAME%%-*}" \
  HOSTNAME "$SYSTEM_HOSTNAME" DOMAIN "${SYSTEM_DOMAIN:-${SERVER_DOMAIN:-lan.icramer.com}}" \
  TIMEZONE "${SERVER_TIMEZONE:-Europe/Stockholm}" SSH_PORT "$SERVER_SSH_PORT" \
  SSH_CIDR_ALLOW "${SERVER_SSH_CIDR_ALLOW:-192.168.50.0/24}" \
  SSH_USER "$SSH_SERVER_USER_ALLOW"
