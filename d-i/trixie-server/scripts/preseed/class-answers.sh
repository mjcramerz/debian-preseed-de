#!/bin/sh
set -eu
umask 077

source_dir=${1:-/tmp/server-install}
[ -d "$source_dir" ] || { printf '%s\n' 'fatal: server source directory is unavailable' >&2; exit 1; }
# shellcheck disable=SC1090
. "$source_dir/scripts/common/validate.sh"
# shellcheck disable=SC1090
. "$source_dir/scripts/common/credentials.sh"
# shellcheck disable=SC1090
. "$source_dir/scripts/common/forky.sh"
# shellcheck disable=SC1090
. "$source_dir/hosts/installer/identity.env"
server_forky_identity_load "$source_dir"

classes=${PRESEED_SERVER_CLASSES:-}
if [ -r /proc/cmdline ]; then
  for argument in $(cat /proc/cmdline); do
    case "$argument" in classes=*) classes=${argument#classes=} ;; esac
  done
fi
classes=$(printf '%s\n' "$classes" | tr ';' ',')
if [ -z "$classes" ]; then
  # shellcheck disable=SC1090
  . "$source_dir/repo.env"
  classes=$DEBIAN_DEFAULT_CLASSES
  classes=$(printf '%s\n' "$classes" | tr ';' ',')
fi

append_unique() {
  word=$1
  case " $pkgsel " in
    *" $word "*) ;;
    *) pkgsel="${pkgsel:+$pkgsel }$word" ;;
  esac
}

append_fragment_packages() {
  fragment=$1
  [ -f "$fragment" ] || { server_fatal "selected class fragment is missing: $fragment"; exit 1; }
  while IFS= read -r word; do
    [ -n "$word" ] || continue
    case "$word" in *[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+./:-]*) server_fatal "invalid package name in $fragment"; exit 1 ;; esac
    append_unique "$word"
  done <<EOF_PACKAGES
$(awk '$1 == "d-i" && $2 == "pkgsel/include" && $3 == "string" { for (i = 4; i <= NF; i++) print $i }' "$fragment")
EOF_PACKAGES
}

class_fragment() {
  token=$1
  case "$token" in
    */*) group=${token%%/*}; name=${token#*/} ;;
    *:*) group=${token%%:*}; name=${token#*:} ;;
    *.*) group=${token%%.*}; name=${token#*.} ;;
    *)
      group=
      name=$token
      for candidate in site role security network disk service profile; do
        [ -f "$source_dir/classes/class-select/$candidate/$name.cfg" ] && { group=$candidate; break; }
      done
      [ -n "$group" ] || [ -f "$source_dir/classes/class-addon/$name.cfg" ] || { server_fatal "unknown server class: $token"; exit 1; }
      [ -n "$group" ] || group=addon
      ;;
  esac
  case "$group" in
    site|role|security|network|disk|service) printf '%s\n' "$source_dir/classes/class-select/$group/$name.cfg" ;;
    profile) printf '%s\n' "$source_dir/classes/class-profile/$name.cfg" ;;
    addon) printf '%s\n' "$source_dir/classes/class-addon/$name.cfg" ;;
    arch|cpu) printf '%s\n' "$source_dir/classes/class-auto/$group/$name.cfg" ;;
    *) server_fatal "invalid server class group: $group"; exit 1 ;;
  esac
}

pkgsel=
append_fragment_packages "$source_dir/fragments/apt.cfg"
seen_fragments=

old_ifs=$IFS
IFS=,
# shellcheck disable=SC2086
set -- $classes
IFS=$old_ifs
for token in "$@"; do
  [ -n "$token" ] || continue
  case "$token" in *[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_./:+-]*) server_fatal 'classes contains an invalid token'; exit 1 ;; esac
  fragment=$(class_fragment "$token")
  case " $seen_fragments " in
    *" $fragment "*) server_fatal "duplicate class selection: $token"; exit 1 ;;
    *) seen_fragments="${seen_fragments:+$seen_fragments }$fragment" ;;
  esac
  append_fragment_packages "$fragment"
done

architecture=$(dpkg --print-architecture 2>/dev/null || true)
case "$architecture" in
  amd64|arm64) append_fragment_packages "$source_dir/classes/class-auto/arch/$architecture.cfg" ;;
  *) server_fatal "unsupported installer architecture: ${architecture:-unknown}"; exit 1 ;;
esac
append_fragment_packages "$source_dir/classes/class-auto/cpu/generic.cfg"

network_address=$(server_answer_value netcfg/get_ipaddress ip) || { server_fatal 'static installer IP is required from the kernel command line or debconf'; exit 1; }
network_netmask=$(server_answer_value netcfg/get_netmask netmask) || { server_fatal 'static installer netmask is required from the kernel command line or debconf'; exit 1; }
network_gateway=$(server_answer_value netcfg/get_gateway gateway) || { server_fatal 'static installer gateway is required from the kernel command line or debconf'; exit 1; }
network_nameservers=$(server_answer_value netcfg/get_nameservers nameservers dns 2>/dev/null || true)
network_nameservers=${network_nameservers:-${STATIC_INSTALLER_NAMESERVER:-}}
[ -n "$network_nameservers" ] || { server_fatal 'static installer nameservers are required from the kernel command line or debconf'; exit 1; }
network_prefix=$(server_ipv4_netmask_prefix "$network_netmask") || { server_fatal 'static installer netmask is invalid'; exit 1; }
network_cidr=$network_address/$network_prefix
case "$network_address:$network_gateway" in *[!0-9.]*) server_fatal 'static network addresses contain unsupported characters'; exit 1 ;; esac
case "$network_nameservers" in *[!0-9.,]*) server_fatal 'static nameservers contain unsupported characters'; exit 1 ;; esac
case "$network_prefix" in
  0) network_netmask=0.0.0.0 ;; 1) network_netmask=128.0.0.0 ;; 2) network_netmask=192.0.0.0 ;; 3) network_netmask=224.0.0.0 ;; 4) network_netmask=240.0.0.0 ;; 5) network_netmask=248.0.0.0 ;; 6) network_netmask=252.0.0.0 ;; 7) network_netmask=254.0.0.0 ;; 8) network_netmask=255.0.0.0 ;;
  9) network_netmask=255.128.0.0 ;; 10) network_netmask=255.192.0.0 ;; 11) network_netmask=255.224.0.0 ;; 12) network_netmask=255.240.0.0 ;; 13) network_netmask=255.248.0.0 ;; 14) network_netmask=255.252.0.0 ;; 15) network_netmask=255.254.0.0 ;; 16) network_netmask=255.255.0.0 ;;
  17) network_netmask=255.255.128.0 ;; 18) network_netmask=255.255.192.0 ;; 19) network_netmask=255.255.224.0 ;; 20) network_netmask=255.255.240.0 ;; 21) network_netmask=255.255.248.0 ;; 22) network_netmask=255.255.252.0 ;; 23) network_netmask=255.255.254.0 ;; 24) network_netmask=255.255.255.0 ;;
  25) network_netmask=255.255.255.128 ;; 26) network_netmask=255.255.255.192 ;; 27) network_netmask=255.255.255.224 ;; 28) network_netmask=255.255.255.240 ;; 29) network_netmask=255.255.255.248 ;; 30) network_netmask=255.255.255.252 ;; 31) network_netmask=255.255.255.254 ;; 32) network_netmask=255.255.255.255 ;;
  *) server_fatal 'static installer netmask must use an IPv4 prefix from 0 through 32'; exit 1 ;;
esac

answers=$(mktemp /tmp/server-pkgsel.XXXXXX)
trap 'rm -f "$answers"' EXIT HUP INT TERM
printf 'd-i pkgsel/include string %s\n' "$pkgsel" >"$answers"
printf 'd-i pkgsel/include seen true\n' >>"$answers"
printf 'd-i netcfg/get_ipaddress string %s\n' "$network_address" >>"$answers"
printf 'd-i netcfg/get_netmask string %s\n' "$network_netmask" >>"$answers"
printf 'd-i netcfg/get_gateway string %s\n' "$network_gateway" >>"$answers"
printf 'd-i netcfg/get_nameservers string %s\n' "$network_nameservers" >>"$answers"
printf 'd-i netcfg/get_hostname string %s\n' "$SYSTEM_HOSTNAME" >>"$answers"
printf 'd-i netcfg/get_domain string %s\n' "$SYSTEM_DOMAIN" >>"$answers"
printf 'd-i netcfg/hostname string %s\n' "$SYSTEM_HOSTNAME" >>"$answers"
printf 'd-i netcfg/confirm_static boolean true\n' >>"$answers"
debconf-set-selections "$answers"
