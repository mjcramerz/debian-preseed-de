#!/bin/sh
# Shared late_command network handoff helpers. This file is sourced.

target_network_selected_class() {
  installer_selected_class_for_purpose network 2>/dev/null || printf '%s' "${INSTALLER_NETWORK_CLASS:-}"
}

target_wifi_essid_answer() {
  network_answer_value \
    netcfg/wireless_essid \
    wireless_essid \
    wifi_essid \
    essid
}

target_wifi_essid_again_answer() {
  network_answer_value \
    netcfg/wireless_essid_again \
    wireless_essid_again \
    wifi_essid_again \
    essid_again
}

target_wifi_security_answer() {
  network_answer_value \
    netcfg/wireless_security_type \
    wireless_security_type \
    wifi_security_type
}

target_wifi_wpa_answer() {
  network_answer_value \
    netcfg/wireless_wpa \
    wireless_wpa \
    wifi_wpa
}

target_wifi_wep_answer() {
  network_answer_value \
    netcfg/wireless_wep \
    wireless_wep \
    wifi_wep
}

target_wifi_static_config_requested() {
  wifi_essid=$(target_wifi_essid_answer 2>/dev/null || true)
  [ -n "$wifi_essid" ]
}

target_wifi_handoff_requested() {
  target_static_network_selected || return 1
  target_wifi_static_config_requested || return 1
  default_route_iface=$(installer_default_route_interface 2>/dev/null || true)
  if [ -n "$default_route_iface" ] &&
     installer_interface_matches_link_type "$default_route_iface" wifi
  then
    return 0
  fi

  chosen_iface=$(network_answer_value netcfg/choose_interface choose_interface 2>/dev/null || true)
  case "$chosen_iface" in
    auto|'') ;;
    *)
      installer_interface_matches_link_type "$chosen_iface" wifi && return 0
      ;;
  esac

  installer_global_ipv4_interface wifi >/dev/null 2>&1
}

target_static_network_selected() {
  network_class=$(target_network_selected_class)
  [ "$network_class" = static ] && return 0
  installer_selected_class_reference_is_selected network/static 2>/dev/null
}

target_managed_network_handoff_requested() {
  target_static_network_selected
}

target_managed_network_mode() {
  if target_static_network_selected; then
    printf '%s\n' static
  else
    printf '%s\n' dhcp
  fi
}

target_managed_network_link_type() {
  link_types=$(target_managed_network_link_types)
  printf '%s\n' "${link_types%% *}"
}

target_managed_network_link_types() {
  if target_static_network_selected; then
    link_types=
    if installer_network_interface_for_handoff ethernet >/dev/null 2>&1; then
      link_types=ethernet
    fi
    if target_wifi_handoff_requested &&
       installer_network_interface_for_handoff wifi >/dev/null 2>&1; then
      link_types="${link_types:+$link_types }wifi"
    fi
    [ -n "$link_types" ] ||
      installer_fatal "no Ethernet or Wi-Fi adapter detected for static target networking"
    printf '%s\n' "$link_types"
  else
    printf '%s\n' ethernet
  fi
}

network_link_types_has() {
  link_types=$1
  wanted=$2

  case " ${link_types} " in
    *" ${wanted} "*) return 0 ;;
  esac
  return 1
}

target_host_variant_class() {
  installer_selected_class_for_purpose host-variant 2>/dev/null || printf '%s\n' "${INSTALLER_HOST_VARIANT:-}"
}

network_answer_value() {
  for answer_key in "$@"; do
    value=$(installer_cmdline_value "$answer_key" 2>/dev/null || true)
    if [ -n "$value" ]; then
      printf '%s\n' "$value"
      return 0
    fi
  done

  for answer_key in "$@"; do
    value=$(installer_debconf_value "$answer_key" 2>/dev/null || true)
    if [ -n "$value" ]; then
      printf '%s\n' "$value"
      return 0
    fi
  done

  return 1
}

valid_installer_network_interface_name() {
  iface=$1

  case "$iface" in
    ''|.|..|lo|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-]*)
      return 1
      ;;
  esac
  [ "${#iface}" -le 15 ] || return 1
  return 0
}

installer_interface_is_wireless() {
  iface=$1
  valid_installer_network_interface_name "$iface" || return 1

  [ -d "/sys/class/net/${iface}/wireless" ] || [ -d "/sys/class/net/${iface}/phy80211" ]
}

installer_interface_matches_link_type() {
  iface=$1
  link_type=$2
  type_file="/sys/class/net/${iface}/type"
  device_path="/sys/class/net/${iface}/device"

  valid_installer_network_interface_name "$iface" || return 1
  [ -r "$type_file" ] || return 1
  [ -e "$device_path" ] || return 1
  IFS= read -r iface_type <"$type_file" || return 1
  [ "$iface_type" = 1 ] || return 1

  case "$link_type" in
    wifi)
      installer_interface_is_wireless "$iface"
      ;;
    ethernet)
      installer_interface_is_wireless "$iface" && return 1
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

valid_installer_mac_address() {
  mac=$1

  case "$mac" in
    00:00:00:00:00:00)
      return 1
      ;;
    [0123456789abcdefABCDEF][0123456789abcdefABCDEF]:[0123456789abcdefABCDEF][0123456789abcdefABCDEF]:[0123456789abcdefABCDEF][0123456789abcdefABCDEF]:[0123456789abcdefABCDEF][0123456789abcdefABCDEF]:[0123456789abcdefABCDEF][0123456789abcdefABCDEF]:[0123456789abcdefABCDEF][0123456789abcdefABCDEF])
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

installer_default_route_interface() {
  command -v ip >/dev/null 2>&1 || return 1
  ip -4 route show default 2>/dev/null | sed -n '1{s/.* dev \([^ ]*\).*/\1/p;}'
}

installer_global_ipv4_interface() {
  link_type=$1

  command -v ip >/dev/null 2>&1 || return 1
  ip -o -4 addr show scope global 2>/dev/null | while IFS= read -r line || [ -n "$line" ]; do
    iface=$(printf '%s\n' "$line" | sed -n 's/^[0-9][0-9]*: \([^ :]*\).*/\1/p')
    [ -n "$iface" ] || continue
    installer_interface_matches_link_type "$iface" "$link_type" || continue
    printf '%s\n' "$iface"
    break
  done
}

installer_first_interface_for_link_type() {
  link_type=$1

  for sys_iface in /sys/class/net/*; do
    [ -e "$sys_iface" ] || continue
    iface=${sys_iface##*/}
    installer_interface_matches_link_type "$iface" "$link_type" || continue
    printf '%s\n' "$iface"
    return 0
  done
  return 1
}

installer_network_interface_for_handoff() {
  link_type=$1
  iface=

  iface=$(installer_default_route_interface 2>/dev/null || true)
  if [ -n "$iface" ] && installer_interface_matches_link_type "$iface" "$link_type"; then
    printf '%s\n' "$iface"
    return 0
  fi

  iface=$(network_answer_value netcfg/choose_interface choose_interface 2>/dev/null || true)
  case "$iface" in
    auto|'') ;;
    *)
      if installer_interface_matches_link_type "$iface" "$link_type"; then
        printf '%s\n' "$iface"
        return 0
      fi
      ;;
  esac

  iface=$(installer_global_ipv4_interface "$link_type" 2>/dev/null || true)
  if [ -n "$iface" ]; then
    printf '%s\n' "$iface"
    return 0
  fi

  installer_first_interface_for_link_type "$link_type"
}

installer_interface_mac_address() {
  iface=$1
  address_file="/sys/class/net/${iface}/address"

  valid_installer_network_interface_name "$iface" || return 1
  [ -r "$address_file" ] || return 1
  IFS= read -r mac <"$address_file" || return 1
  valid_installer_mac_address "$mac" || return 1
  printf '%s\n' "$mac" | tr 'ABCDEFGHIJKLMNOPQRSTUVWXYZ' 'abcdefghijklmnopqrstuvwxyz'
}

validate_network_single_line_token() {
  label=$1
  value=$2

  case "$value" in
    ''|*[![:print:]]*|*[[:space:]]*)
      installer_fatal "${label} must be a single printable token"
      ;;
  esac
}

validate_network_iface_name() {
  label=$1
  value=$2

  case "$value" in
    ''|.|..|lo)
      installer_fatal "${label} must be a non-loopback interface name"
      ;;
  esac
  case "$value" in
    *[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-]*)
      installer_fatal "${label} contains unsupported characters"
      ;;
  esac
  [ "${#value}" -le 15 ] || installer_fatal "${label} must be 15 characters or fewer"
}

validate_network_hostname_component() {
  label=$1
  value=$2

  case "$value" in
    ''|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.-]*|.*|*.|*..*)
      installer_fatal "${label} must contain only hostname-safe labels"
      ;;
  esac
}

validate_network_ipv4_address() {
  label=$1
  value=$2
  old_ifs=$IFS

  case "$value" in
    ''|*[!0123456789.]*|.*|*.|*..*)
      installer_fatal "${label} must be an IPv4 dotted-quad address"
      ;;
  esac

  IFS=.
  # shellcheck disable=SC2086
  set -- $value
  IFS=$old_ifs

  [ "$#" -eq 4 ] || installer_fatal "${label} must contain four IPv4 octets"
  for octet in "$@"; do
    case "$octet" in
      ''|*[!0123456789]*|????*)
        installer_fatal "${label} contains an invalid IPv4 octet"
        ;;
    esac
    [ "$octet" -le 255 ] || installer_fatal "${label} octet is outside 0-255"
  done
}

validate_network_ipv4_address_list() {
  label=$1
  value=$2
  count=0

  case "$value" in
    *','*) installer_fatal "${label} must use spaces between IPv4 addresses, not commas" ;;
  esac

  for address in $value; do
    count=$((count + 1))
    validate_network_ipv4_address "${label} entry" "$address"
  done

  [ "$count" -ge 1 ] || installer_fatal "${label} must contain at least one IPv4 address"
  [ "$count" -le 3 ] || installer_fatal "${label} must contain no more than three IPv4 addresses"
}

validate_network_wifi_wpa() {
  label=$1
  value=$2
  length=${#value}

  validate_network_single_line_token "$label" "$value"
  if [ "$length" -ge 8 ] && [ "$length" -le 63 ]; then
    return 0
  fi
  case "$value" in
    *[!0123456789ABCDEFabcdef]*)
      installer_fatal "${label} must be 8-63 printable characters or a 64-character hexadecimal PSK"
      ;;
  esac
  [ "$length" -eq 64 ] || installer_fatal "${label} must be 8-63 printable characters or a 64-character hexadecimal PSK"
}

validate_network_wifi_essid() {
  label=$1
  value=$2

  validate_network_single_line_token "$label" "$value"
  [ "${#value}" -le 32 ] || installer_fatal "${label} must be 32 characters or shorter"
}

# shellcheck disable=SC2034
# These MANAGED_NETWORK_* values are sourced state consumed by security.sh.
target_prepare_managed_network_handoff_state() {
  if [ "${MANAGED_NETWORK_STATE_PREPARED:-false}" = true ]; then
    return 0
  fi
  MANAGED_NETWORK_STATE_PREPARED=true
  MANAGED_NETWORK_IPV4_ENABLED=false
  MANAGED_NETWORK_IPV6_ENABLED=false
  MANAGED_NETWORK_IPV6_ADDRESS=
  MANAGED_NETWORK_IPV6_PREFIXLEN=
  MANAGED_NETWORK_IPV6_GATEWAY=
  MANAGED_NETWORK_IPV6_DNS=
  MANAGED_NETWORK_IPV6_CIDR=
  MANAGED_NETWORK_IPV6_HOST_CIDR=
  MANAGED_NETWORK_IPV6_NETWORK_CIDR=

  MANAGED_NETWORK_IPV4_HOST_CIDRS=
  MANAGED_NETWORK_IPV4_NETWORK_CIDRS=
  MANAGED_NETWORK_IPV6_HOST_CIDRS=
  MANAGED_NETWORK_IPV6_NETWORK_CIDRS=

  state_env=$(target_managed_network_state_env)
  [ -r "$state_env" ] || return 0
  # shellcheck disable=SC1090
  . "$state_env"
  [ "${MANAGED_NETWORK_IPV4_ENABLED:-false}" = true ] ||
    [ "${MANAGED_NETWORK_IPV6_ENABLED:-false}" = true ] ||
    return 0
  MANAGED_NETWORK_IPV6_HOST_CIDR=${MANAGED_NETWORK_IPV6_HOST_CIDR:-}
  MANAGED_NETWORK_IPV6_NETWORK_CIDR=${MANAGED_NETWORK_IPV6_NETWORK_CIDR:-}
  MANAGED_NETWORK_IPV6_CIDR=${MANAGED_NETWORK_IPV6_CIDR:-}
  installer_info "loaded static network CIDRs for nftables: ipv4_hosts=${MANAGED_NETWORK_IPV4_HOST_CIDRS:-none} ipv6_hosts=${MANAGED_NETWORK_IPV6_HOST_CIDRS:-none}"
}

target_prepare_managed_network_ipv6_handoff() {
  target_prepare_managed_network_handoff_state
}

normalize_network_address_list() {
  printf '%s\n' "${1:-}" |
    tr ',\015\012\011' '    ' |
    sed 's/[[:space:]][[:space:]]*/ /g; s/^ //; s/ $//'
}

target_managed_network_state_env() {
  printf '%s\n' "${TMP_ENV_DIR:-/tmp}/managed-network-state.env"
}

target_managed_network_generator_target_path() {
  printf '%s\n' /tmp/managed-network-generate.pl
}

target_managed_network_input_target_path() {
  printf '%s\n' /tmp/managed-network-input.env
}

target_managed_network_state_target_path() {
  printf '%s\n' /tmp/managed-network-state.env
}

validate_network_wifi_psk_security() {
  label=$1
  value=$2

  case "$value" in
    open|wep|open/wep|wpa|sae) ;;
    *) installer_fatal "${label} must be open, wep, open/wep, wpa, or sae" ;;
  esac
}

write_target_managed_network_input() {
  network_mode=$1
  link_types=$2
  installer_mac=
  ethernet_mac=
  wifi_mac=
  static_domain=${SYSTEM_DOMAIN:-}
  static_ip=
  static_netmask=
  static_gateway=
  static_nameservers=
  ipv6_address=
  ipv6_gateway=
  ipv6_dns_raw=
  ipv6_enabled=false
  ipv4_dns=
  ipv6_dns=
  wifi_essid=
  wifi_essid_again=
  wifi_security=
  wifi_wpa=
  wifi_wep=

  [ "$network_mode" = static ] ||
    installer_fatal "managed network generator only supports static target networking"
  static_ip=$(network_answer_value netcfg/get_ipaddress ip 2>/dev/null || true)
  static_netmask=$(network_answer_value netcfg/get_netmask netmask 2>/dev/null || true)
  static_gateway=$(network_answer_value netcfg/get_gateway gateway 2>/dev/null || true)
  static_nameservers=$(network_answer_value netcfg/get_nameservers nameservers dns 2>/dev/null || true)
  [ -n "$static_ip" ] || installer_fatal "netcfg/get_ipaddress is required for static target networking"
  [ -n "$static_netmask" ] || installer_fatal "netcfg/get_netmask is required for static target networking"
  [ -n "$static_gateway" ] || installer_fatal "netcfg/get_gateway is required for static target networking"

  validate_network_ipv4_address MANAGED_NETWORK_IPV4_ADDRESS "$static_ip"
  validate_network_ipv4_address MANAGED_NETWORK_IPV4_NETMASK "$static_netmask"
  validate_network_ipv4_address MANAGED_NETWORK_IPV4_GATEWAY "$static_gateway"
  validate_network_hostname_component SYSTEM_DOMAIN "$static_domain"
  ipv4_dns=$(normalize_network_address_list "$static_nameservers")
  [ -n "$ipv4_dns" ] || ipv4_dns=${static_gateway:-${STATIC_NAMESERVERS_DEFAULT:-}}
  validate_network_ipv4_address_list MANAGED_NETWORK_IPV4_DNS "$ipv4_dns"

  ipv6_address=$(installer_cmdline_value ipv6_address 2>/dev/null || true)
  ipv6_gateway=$(installer_cmdline_value ipv6_gateway 2>/dev/null || true)
  ipv6_dns_raw=$(installer_cmdline_value ipv6_nameservers 2>/dev/null || true)
  if [ -n "$ipv6_address" ] || [ -n "$ipv6_gateway" ] || [ -n "$ipv6_dns_raw" ]; then
    [ -n "$ipv6_address" ] || installer_fatal "ipv6_gateway and ipv6_nameservers require ipv6_address=<address/prefix> on the kernel cmdline"
    [ -n "$ipv6_gateway" ] || installer_fatal "ipv6_address and ipv6_nameservers require ipv6_gateway=<address> on the kernel cmdline"
    [ -n "$ipv6_dns_raw" ] || installer_fatal "ipv6_address and ipv6_gateway require ipv6_nameservers=<address[,address]> on the kernel cmdline"
    validate_network_single_line_token MANAGED_NETWORK_IPV6_ADDRESS "$ipv6_address"
    case "$ipv6_address" in
      */*) ;;
      *) installer_fatal "ipv6_address must use CIDR notation, for example 2001:db8::82/64" ;;
    esac
    validate_network_single_line_token MANAGED_NETWORK_IPV6_GATEWAY "$ipv6_gateway"
    ipv6_dns=$(normalize_network_address_list "$ipv6_dns_raw")
    [ -n "$ipv6_dns" ] || installer_fatal "ipv6_nameservers must contain at least one IPv6 address"
    ipv6_enabled=true
  fi

  case " $link_types " in
    *" wifi "*)
      wifi_essid=$(target_wifi_essid_answer 2>/dev/null || true)
      if [ -n "$wifi_essid" ]; then
        validate_network_wifi_essid MANAGED_NETWORK_WIFI_ESSID "$wifi_essid"
        wifi_essid_again=$(target_wifi_essid_again_answer 2>/dev/null || true)
        if [ -n "$wifi_essid_again" ]; then
          validate_network_wifi_essid MANAGED_NETWORK_WIFI_ESSID_AGAIN "$wifi_essid_again"
          [ "$wifi_essid_again" = "$wifi_essid" ] ||
            installer_fatal "MANAGED_NETWORK_WIFI_ESSID_AGAIN must match MANAGED_NETWORK_WIFI_ESSID"
        fi

        wifi_security=$(target_wifi_security_answer 2>/dev/null || true)
        wifi_wpa=$(target_wifi_wpa_answer 2>/dev/null || true)
        wifi_wep=$(target_wifi_wep_answer 2>/dev/null || true)
        if [ -z "$wifi_security" ]; then
          if [ -n "$wifi_wpa" ]; then
            wifi_security=wpa
          elif [ -n "$wifi_wep" ]; then
            wifi_security=wep
          else
            wifi_security=open
          fi
        fi
        validate_network_wifi_psk_security MANAGED_NETWORK_WIFI_PSK_SECURITY "$wifi_security"
        case "$wifi_security" in
          wpa|sae)
            [ -n "$wifi_wpa" ] || installer_fatal "MANAGED_NETWORK_WIFI_WPA is required for ${wifi_security} Wi-Fi"
            validate_network_wifi_wpa MANAGED_NETWORK_WIFI_WPA "$wifi_wpa"
            ;;
          wep)
            [ -n "$wifi_wep" ] || installer_fatal "MANAGED_NETWORK_WIFI_WEP is required when Wi-Fi security is set to wep"
            validate_network_single_line_token MANAGED_NETWORK_WIFI_WEP "$wifi_wep"
            ;;
          open/wep)
            if [ -n "$wifi_wep" ]; then
              validate_network_single_line_token MANAGED_NETWORK_WIFI_WEP "$wifi_wep"
            fi
            ;;
        esac
      else
        link_types=$(printf '%s\n' "$link_types" | sed 's/\<wifi\>//g; s/[[:space:]][[:space:]]*/ /g; s/^ //; s/ $//')
        installer_info "skipping Wi-Fi static handoff because no Wi-Fi ESSID was supplied"
        [ -n "$link_types" ] ||
          installer_fatal "no managed network interface remains after skipping unconfigured Wi-Fi handoff"
      fi
      ;;
  esac

  for handoff_link_type in $link_types; do
    installer_iface=$(installer_network_interface_for_handoff "$handoff_link_type" 2>/dev/null || true)
    installer_mac_for_type=
    if [ -n "$installer_iface" ]; then
      installer_mac_for_type=$(installer_interface_mac_address "$installer_iface" 2>/dev/null || true)
    fi
    case "$handoff_link_type" in
      ethernet) ethernet_mac=$installer_mac_for_type ;;
      wifi) wifi_mac=$installer_mac_for_type ;;
    esac
    [ -n "$installer_mac" ] || installer_mac=$installer_mac_for_type
  done

  if [ -z "$wifi_mac" ]; then
    detected_wifi_iface=$(installer_network_interface_for_handoff wifi 2>/dev/null || true)
    if [ -n "$detected_wifi_iface" ]; then
      wifi_mac=$(installer_interface_mac_address "$detected_wifi_iface" 2>/dev/null || true)
    fi
  fi

  target_ethernet_iface=${MANAGED_NETWORK_ETHERNET_IFACE:-managed-eth0}
  target_wifi_iface=${MANAGED_NETWORK_WIFI_IFACE:-managed-wifi0}
  validate_network_iface_name MANAGED_NETWORK_ETHERNET_IFACE "$target_ethernet_iface"
  validate_network_iface_name MANAGED_NETWORK_WIFI_IFACE "$target_wifi_iface"
  [ "$target_ethernet_iface" != "$target_wifi_iface" ] ||
    installer_fatal "MANAGED_NETWORK_ETHERNET_IFACE and MANAGED_NETWORK_WIFI_IFACE must differ"

  {
    printf '# Managed by unattended-installer.\n'
    printf '# Temporary input for late-command static target network generation.\n'
    write_shell_config_var MANAGED_NETWORK_WAIT_SECONDS 8
    write_shell_config_var MANAGED_NETWORK_MODE "$network_mode"
    write_shell_config_var MANAGED_NETWORK_LINK_TYPES "$link_types"
    write_shell_config_var MANAGED_NETWORK_TARGET_ROOT /
    write_shell_config_var MANAGED_NETWORK_SYS_CLASS_NET /sys/class/net
    write_shell_config_var MANAGED_NETWORK_STATE_ENV "$(target_managed_network_state_target_path)"
    write_shell_config_var MANAGED_NETWORK_HOSTNAME "${SYSTEM_HOSTNAME:-managed-host}"
    write_shell_config_var MANAGED_NETWORK_DOMAIN "$static_domain"
    write_shell_config_var MANAGED_NETWORK_HOST_VARIANT "${MANAGED_NETWORK_HOST_VARIANT:-$(target_host_variant_class)}"
    write_shell_config_var MANAGED_NETWORK_CLASSES_RAW "${INSTALLER_CLASSES_RAW:-}"
    write_shell_config_var MANAGED_NETWORK_SELECTED_CLASS_REFS "${INSTALLER_SELECTED_CLASS_REFS:-}"
    if [ -n "$installer_mac" ]; then
      write_shell_config_var MANAGED_NETWORK_INSTALLER_MAC "$installer_mac"
    fi
    if [ -n "$ethernet_mac" ]; then
      write_shell_config_var MANAGED_NETWORK_ETHERNET_MAC "$ethernet_mac"
    fi
    write_shell_config_var MANAGED_NETWORK_ETHERNET_IFACE "$target_ethernet_iface"
    if [ -n "$wifi_mac" ]; then
      write_shell_config_var MANAGED_NETWORK_WIFI_MAC "$wifi_mac"
    fi
    write_shell_config_var MANAGED_NETWORK_WIFI_IFACE "$target_wifi_iface"
    if [ -n "$wifi_essid" ]; then
      write_shell_config_var MANAGED_NETWORK_WIFI_ESSID "$wifi_essid"
    fi
    if [ -n "$wifi_essid_again" ]; then
      write_shell_config_var MANAGED_NETWORK_WIFI_ESSID_AGAIN "$wifi_essid_again"
    fi
    if [ -n "$wifi_security" ]; then
      write_shell_config_var MANAGED_NETWORK_WIFI_PSK_SECURITY "$wifi_security"
    fi
    if [ -n "$wifi_wpa" ]; then
      write_shell_config_var MANAGED_NETWORK_WIFI_WPA "$wifi_wpa"
    fi
    if [ -n "$wifi_wep" ]; then
      write_shell_config_var MANAGED_NETWORK_WIFI_WEP "$wifi_wep"
    fi
    write_shell_config_var MANAGED_NETWORK_IPV4_ADDRESS "$static_ip"
    write_shell_config_var MANAGED_NETWORK_IPV4_NETMASK "$static_netmask"
    write_shell_config_var MANAGED_NETWORK_IPV4_GATEWAY "$static_gateway"
    write_shell_config_var MANAGED_NETWORK_IPV4_DNS "$ipv4_dns"
    write_shell_config_var MANAGED_NETWORK_IPV6_ENABLED "$ipv6_enabled"
    write_shell_config_var MANAGED_NETWORK_IPV6_ADDRESS "$ipv6_address"
    write_shell_config_var MANAGED_NETWORK_IPV6_GATEWAY "$ipv6_gateway"
    write_shell_config_var MANAGED_NETWORK_IPV6_DNS "$ipv6_dns"
  } | write_target_file "$(target_managed_network_input_target_path)" 0600
}

generate_target_managed_network_config() {
  network_mode=$1
  link_types=$2
  generator_target=$(target_managed_network_generator_target_path)
  input_target=$(target_managed_network_input_target_path)
  state_target=$(target_managed_network_state_target_path)
  state_env=$(target_managed_network_state_env)

  stage_target_asset "$(installer_repo_join_var DIR_SCRIPTS_LATE managed-network-generate.pl)" "$generator_target" 0700
  write_target_managed_network_input "$network_mode" "$link_types"
  if ! attempt_in_target "generate managed static target network config" \
    /usr/bin/env "SYSTEMD_LOG_LEVEL=${SYSTEMD_LOG_LEVEL:-error}" \
    /usr/bin/perl "$generator_target" --input "$input_target" --state-env "$state_target"; then
    remove_target_asset "$generator_target"
    remove_target_asset "$input_target"
    remove_target_asset "$state_target"
    installer_fatal "failed to generate managed static target network config"
  fi
  if [ ! -r "/target${state_target}" ]; then
    remove_target_asset "$generator_target"
    remove_target_asset "$input_target"
    remove_target_asset "$state_target"
    installer_fatal "managed-network generator did not produce ${state_target}"
  fi
  if ! cp "/target${state_target}" "$state_env"; then
    remove_target_asset "$generator_target"
    remove_target_asset "$input_target"
    remove_target_asset "$state_target"
    installer_fatal "failed to copy managed-network generator state"
  fi
  if ! chmod 0600 "$state_env"; then
    remove_target_asset "$generator_target"
    remove_target_asset "$input_target"
    remove_target_asset "$state_target"
    installer_fatal "failed to protect managed-network generator state"
  fi
  remove_target_asset "$generator_target"
  remove_target_asset "$input_target"
  remove_target_asset "$state_target"
  # shellcheck disable=SC1090
  . "$state_env"
}

enable_target_networking_service_if_available() {
  if target_systemd_unit_path networking.service system >/dev/null 2>&1; then
    stage_target_systemd_unit_enabled networking.service system
  else
    installer_warn "target networking.service is unavailable; managed network handoff is staged but ifupdown service enablement was skipped"
  fi
}

render_target_networkmanager_unit_override() {
  networkmanager_source_unit=$1

  awk '
    function emit_before(before_line, dependency_count, dependency_index, dependency, rendered_dependencies, removed_dependencies) {
      sub(/^[[:space:]]*Before[[:space:]]*=[[:space:]]*/, "", before_line)
      dependency_count = split(before_line, dependencies, /[[:space:]]+/)
      rendered_dependencies = ""
      removed_dependencies = 0
      for (dependency_index = 1; dependency_index <= dependency_count; dependency_index++) {
        dependency = dependencies[dependency_index]
        if (dependency == "" ) {
          continue
        }
        if (dependency == "networking.service") {
          before_replacements++
          removed_dependencies++
          continue
        }
        rendered_dependencies = rendered_dependencies \
          (rendered_dependencies == "" ? "" : " ") dependency
      }
      if (rendered_dependencies != "") {
        print "Before=" rendered_dependencies
      } else if (removed_dependencies == 0) {
        # Preserve an existing empty assignment because list-valued systemd
        # directives use it to reset dependencies accumulated earlier.
        print "Before="
      }
    }

    {
      current_line = $0
    }

    collecting_before {
      sub(/^[[:space:]]*/, "", current_line)
      has_continuation = current_line ~ /\\[[:space:]]*$/
      sub(/\\[[:space:]]*$/, "", current_line)
      before_line = before_line " " current_line
      if (!has_continuation) {
        emit_before(before_line)
        before_line = ""
        collecting_before = 0
      }
      next
    }

    current_line ~ /^[[:space:]]*Before[[:space:]]*=/ {
      has_continuation = current_line ~ /\\[[:space:]]*$/
      sub(/\\[[:space:]]*$/, "", current_line)
      before_line = current_line
      if (has_continuation) {
        collecting_before = 1
      } else {
        emit_before(before_line)
        before_line = ""
      }
      next
    }

    { print current_line }

    END {
      if (collecting_before) {
        exit 42
      }
      # Status 3 means that the resolved target unit has no conflicting edge
      # and therefore does not need a full-unit override.
      if (before_replacements == 0) {
        exit 3
      }
    }
  ' "$networkmanager_source_unit"
}

stage_target_networkmanager_dispatcher_activation_if_available() {
  if ! command -v target_systemd_unit_path >/dev/null 2>&1 ||
     ! command -v stage_target_systemd_unit_alias_to_path >/dev/null 2>&1 ||
     ! command -v stage_target_asset >/dev/null 2>&1; then
    installer_warn "systemd staging helpers are unavailable; NetworkManager dispatcher lifecycle was not staged"
    return 0
  fi

  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/system/networking.service.d/20-resolved-shutdown-order.conf)" \
    /etc/systemd/system/networking.service.d/20-resolved-shutdown-order.conf \
    0644

  networkmanager_unit_path=$(target_systemd_unit_path NetworkManager.service system 2>/dev/null || true)
  dispatcher_unit_path=$(target_systemd_unit_path NetworkManager-dispatcher.service system 2>/dev/null || true)
  if [ -z "$networkmanager_unit_path" ] || [ -z "$dispatcher_unit_path" ]; then
    return 0
  fi

  dispatcher_dbus_service=/usr/share/dbus-1/system-services/org.freedesktop.nm_dispatcher.service
  target_dbus_service="/target${dispatcher_dbus_service}"
  target_networkmanager_unit="/target${networkmanager_unit_path}"
  target_dispatcher_unit="/target${dispatcher_unit_path}"

  [ -x /target/usr/libexec/nm-dispatcher ] ||
    installer_fatal "NetworkManager dispatcher executable is missing from the target: /usr/libexec/nm-dispatcher"
  [ -r "$target_networkmanager_unit" ] ||
    installer_fatal "NetworkManager unit is missing from the target: ${networkmanager_unit_path}"
  grep -Fqx 'Type=dbus' "$target_networkmanager_unit" ||
    installer_fatal "NetworkManager unit must use Type=dbus: ${networkmanager_unit_path}"
  grep -Fqx 'BusName=org.freedesktop.NetworkManager' "$target_networkmanager_unit" ||
    installer_fatal "NetworkManager unit must own org.freedesktop.NetworkManager: ${networkmanager_unit_path}"
  [ -r "$target_dbus_service" ] ||
    installer_fatal "NetworkManager dispatcher D-Bus service is missing from the target: ${dispatcher_dbus_service}"
  grep -Fqx 'Name=org.freedesktop.nm_dispatcher' "$target_dbus_service" ||
    installer_fatal "NetworkManager dispatcher D-Bus service has an unexpected bus name: ${dispatcher_dbus_service}"
  grep -Fqx 'SystemdService=dbus-org.freedesktop.nm-dispatcher.service' "$target_dbus_service" ||
    installer_fatal "NetworkManager dispatcher D-Bus service must request dbus-org.freedesktop.nm-dispatcher.service: ${dispatcher_dbus_service}"
  grep -Fqx 'Type=dbus' "$target_dispatcher_unit" ||
    installer_fatal "NetworkManager dispatcher unit must use Type=dbus: ${dispatcher_unit_path}"
  grep -Fqx 'BusName=org.freedesktop.nm_dispatcher' "$target_dispatcher_unit" ||
    installer_fatal "NetworkManager dispatcher unit must own org.freedesktop.nm_dispatcher: ${dispatcher_unit_path}"

  networkmanager_override_tmp=$(mktemp "${TMP_ENV_DIR:-/tmp}/NetworkManager.service.XXXXXX") ||
    installer_fatal "could not allocate temporary NetworkManager unit override"
  if render_target_networkmanager_unit_override \
    "$target_networkmanager_unit" >"$networkmanager_override_tmp"; then
    write_target_file /etc/systemd/system/NetworkManager.service 0644 <"$networkmanager_override_tmp"
    installer_info "removed NetworkManager Before=networking.service ordering from ${networkmanager_unit_path}"
  else
    networkmanager_render_status=$?
    case "$networkmanager_render_status" in
      3)
        installer_info "NetworkManager unit has no Before=networking.service ordering; full override is unnecessary: ${networkmanager_unit_path}"
        ;;
      *)
        rm -f -- "$networkmanager_override_tmp"
        installer_fatal "could not safely remove NetworkManager Before=networking.service ordering from ${networkmanager_unit_path}"
        ;;
    esac
  fi
  rm -f -- "$networkmanager_override_tmp"

  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/system/NetworkManager.service.d/20-managed-dispatcher.conf)" \
    /etc/systemd/system/NetworkManager.service.d/20-managed-dispatcher.conf \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/system/NetworkManager-dispatcher.service.d/20-managed-persistent.conf)" \
    /etc/systemd/system/NetworkManager-dispatcher.service.d/20-managed-persistent.conf \
    0644
  stage_target_systemd_unit_alias_to_path \
    dbus-org.freedesktop.nm-dispatcher.service \
    system \
    "$dispatcher_unit_path"
  installer_info "staged persistent NetworkManager dispatcher lifecycle unit=${dispatcher_unit_path} service=${dispatcher_dbus_service}"
}

remove_target_managed_network_handoff() {
  remove_target_asset "${FILE_MANAGED_NETWORK_INTERFACES:-/etc/network/interfaces.d/50-managed-network}"
  remove_target_asset "${FILE_MANAGED_NETWORK_DEFAULT:-/etc/default/managed-network}"
  remove_target_asset "${FILE_MANAGED_NETWORK_HELPER:-/usr/local/libexec/managed-network-run}"
  managed_network_perl_modules |
    while IFS= read -r managed_network_module; do
      [ -n "$managed_network_module" ] || continue
      remove_target_asset "/usr/local/lib/perl5/site_perl/managed-network/${managed_network_module}"
    done
  remove_target_asset "${FILE_MANAGED_NETWORK_SERVICE:-/etc/systemd/system/managed-network.service}"
  remove_target_asset "${FILE_NETWORKMANAGER_MANAGED_UNMANAGED_CONF:-/etc/NetworkManager/conf.d/90-managed-network-unmanaged.conf}"
  remove_target_asset "/etc/systemd/system/sysinit.target.wants/managed-network.service"
  remove_target_asset "/etc/systemd/network/10-managed-ethernet.link"
  remove_target_asset "/etc/systemd/network/11-managed-wifi.link"
}

managed_network_perl_modules() {
  cat <<'EOF'
ManagedNetwork/CLI.pm
ManagedNetwork/Config.pm
ManagedNetwork/Logger.pm
ManagedNetwork/Validator.pm
EOF
}

stage_target_managed_network_perl_modules() {
  managed_network_perl_modules |
    while IFS= read -r managed_network_module; do
      [ -n "$managed_network_module" ] || continue
      stage_target_asset \
        "$(installer_repo_join_var DIR_HOOKS_TARGET "usr/local/lib/perl5/site_perl/managed-network/${managed_network_module}")" \
        "/usr/local/lib/perl5/site_perl/managed-network/${managed_network_module}" \
        0644
    done
}

install_target_managed_network_handoff() {
  : "${DIR_NETWORK:?DIR_NETWORK must be set}"
  : "${DIR_NETWORK_INTERFACES_D:?DIR_NETWORK_INTERFACES_D must be set}"
  : "${FILE_NETWORK_INTERFACES:?FILE_NETWORK_INTERFACES must be set}"
  : "${FILE_MANAGED_NETWORK_INTERFACES:?FILE_MANAGED_NETWORK_INTERFACES must be set}"
  : "${FILE_MANAGED_NETWORK_DEFAULT:?FILE_MANAGED_NETWORK_DEFAULT must be set}"
  : "${FILE_MANAGED_NETWORK_HELPER:?FILE_MANAGED_NETWORK_HELPER must be set}"
  : "${FILE_MANAGED_NETWORK_SERVICE:?FILE_MANAGED_NETWORK_SERVICE must be set}"
  : "${FILE_NETWORKMANAGER_MANAGED_UNMANAGED_CONF:?FILE_NETWORKMANAGER_MANAGED_UNMANAGED_CONF must be set}"

  stage_target_networkmanager_dispatcher_activation_if_available

  if ! target_managed_network_handoff_requested; then
    installer_info "skipping target managed network handoff; selected networking is not managed by this helper"
    remove_target_managed_network_handoff
    return 0
  fi

  network_mode=$(target_managed_network_mode)
  link_types=$(target_managed_network_link_types)

  require_in_target "managed network handoff prerequisite verification"
  if ! test_in_target /bin/sh -c 'command -v ifup >/dev/null 2>&1'; then
    installer_fatal "ifupdown is required for target networking handoff, but ifup is missing in /target"
  fi
  if network_link_types_has "$link_types" wifi && ! test_in_target /bin/sh -c 'command -v wpa_supplicant >/dev/null 2>&1'; then
    installer_fatal "wpasupplicant is required for Wi-Fi target networking, but wpa_supplicant is missing in /target"
  fi

  install -d -m 0755 "/target${DIR_NETWORK}" "/target${DIR_NETWORK_INTERFACES_D}"
  remove_target_managed_network_handoff
  install -d -m 0755 "/target${DIR_NETWORK}" "/target${DIR_NETWORK_INTERFACES_D}"
  generate_target_managed_network_config "$network_mode" "$link_types"
  stage_target_managed_network_perl_modules
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/libexec/managed-network-run)" \
    "${FILE_MANAGED_NETWORK_HELPER}" \
    0755
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/system/managed-network.service)" \
    "${FILE_MANAGED_NETWORK_SERVICE}" \
    0644
  stage_target_systemd_unit_enabled managed-network.service system
  enable_target_networking_service_if_available
  installer_append_log_category late target_customization info network \
    "staged managed network handoff mode=${network_mode} link_types=${link_types} ipv6=${MANAGED_NETWORK_IPV6_CIDR:-none} helper=${FILE_MANAGED_NETWORK_HELPER} service=${FILE_MANAGED_NETWORK_SERVICE}" || true
}
