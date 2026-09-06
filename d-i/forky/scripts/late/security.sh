#!/bin/sh
# Shared late_command security helpers. This file is sourced, not executed.

late_command_security_class() {
  installer_selected_class_for_purpose security 2>/dev/null || printf '%s\n' "${INSTALLER_SECURITY_CLASS:-standard}"
}

nftables_normalize_env_token() {
  nftables_ws=$(printf ' \011\015\012_')
  nftables_ws=${nftables_ws%_}

  # d-i tr implementations may treat [:upper:] and [:space:] as literal sets,
  # which corrupts "default" into "dfllt". Use explicit ASCII sets here.
  printf '%s' "$1" |
    tr 'ABCDEFGHIJKLMNOPQRSTUVWXYZ' 'abcdefghijklmnopqrstuvwxyz' |
    tr -d "$nftables_ws"
}

late_command_nftables_requested_profile() {
  nft_profile=$(nftables_normalize_env_token "${NFT_PROFILE:-default}")
  [ -n "$nft_profile" ] || installer_fatal "NFT_PROFILE must not be empty"

  case "$nft_profile" in
    none|default|baseline|desktop)
      printf '%s\n' "$nft_profile"
      ;;
    *)
      installer_fatal "unsupported NFT_PROFILE: ${nft_profile}; expected none, default, baseline, server, or desktop"
      ;;
  esac
}

late_command_nftables_host_variant() {
  host_variant=${INSTALLER_HOST_VARIANT:-}
  if [ -z "$host_variant" ]; then
    host_variant=$(installer_selected_class_for_purpose host-variant 2>/dev/null || true)
  fi

  case "$host_variant" in
    desktop|server)
      printf '%s\n' "$host_variant"
      ;;
    '')
      installer_fatal "NFT_PROFILE=default requires a selected role class (desktop or server)"
      ;;
    *)
      installer_fatal "NFT_PROFILE=default cannot resolve unsupported host variant: ${host_variant}"
      ;;
  esac
}

security_target_is_desktop() {
  [ "$(late_command_nftables_host_variant)" = desktop ]
}

late_command_nftables_profile() {
  nft_profile=${1:-$(late_command_nftables_requested_profile)}

  case "$nft_profile" in
    none|baseline|desktop)
      printf '%s\n' "$nft_profile"
      ;;
    default)
      late_command_nftables_host_variant
      ;;
    *)
      installer_fatal "unsupported normalized NFT_PROFILE: ${nft_profile}; expected none, default, baseline, server, or desktop"
      ;;
  esac
}

nftables_service_assets() {
  cat <<'EOF'
backup-restic
crowdsec
cups
dhcp-client
dns-client
docker
egress
kdeconnect
mdns
ntp-client
ollama
openvpn
podman
qemu
qbittorrent
rsync
samba
smtp-client
ssdp
ssh-client
ssh-server
syncthing
tailscale
wazuh-agent
wireguard
zerotier
EOF
}

nftables_service_asset_supported() {
  candidate=$1

  case "$candidate" in
    backup-restic|crowdsec|cups|dhcp-client|dns-client|docker|egress|kdeconnect|mdns|ntp-client|ollama|openvpn|podman|qemu|qbittorrent|rsync|samba|smtp-client|ssdp|ssh-client|ssh-server|syncthing|tailscale|wazuh-agent|wireguard|zerotier)
      return 0
      ;;
  esac

  return 1
}

late_command_nftables_services() {
  nft_services=$(nftables_normalize_env_token "${NFT_SERVICES:-none}")
  [ -n "$nft_services" ] || installer_fatal "NFT_SERVICES must not be empty when NFT_PROFILE is not none"

  case "$nft_services" in
    none)
      return 0
      ;;
    *[!abcdefghijklmnopqrstuvwxyz0123456789,-]*)
      installer_fatal "NFT_SERVICES contains unsupported characters: ${nft_services}"
      ;;
    ,*|*,|*,,*)
      installer_fatal "NFT_SERVICES must be a comma-separated list without empty entries: ${nft_services}"
      ;;
  esac

  old_ifs=$IFS
  IFS=,
  # shellcheck disable=SC2086
  set -- $nft_services
  IFS=$old_ifs

  selected_services=
  for service_asset in "$@"; do
    [ "$service_asset" != none ] || installer_fatal "NFT_SERVICES=none cannot be combined with service names"
    nftables_service_asset_supported "$service_asset" ||
      installer_fatal "unsupported NFT_SERVICES entry: ${service_asset}"
    case " $selected_services " in
      *" $service_asset "*) ;;
      *) selected_services="${selected_services:+$selected_services }$service_asset" ;;
    esac
  done

  printf '%s\n' "$selected_services"
}

nftables_merge_selected_services() {
  selected_services=$1
  shift

  merged_services=$selected_services
  for service_asset in "$@"; do
    [ -n "$service_asset" ] || continue
    case " $merged_services " in
      *" $service_asset "*) ;;
      *) merged_services="${merged_services:+$merged_services }$service_asset" ;;
    esac
  done

  printf '%s\n' "$merged_services"
}

late_command_nftables_effective_services() {
  selected_services=$(late_command_nftables_services)
  effective_services=$selected_services

  if installer_selected_class_reference_is_selected addon/crowdsec 2>/dev/null; then
    effective_services=$(nftables_merge_selected_services "$effective_services" crowdsec)
  fi

  if nftables_tailscale_selected; then
    effective_services=$(nftables_merge_selected_services "$effective_services" tailscale syncthing)
  fi

  if [ "${SSH_SERVER_ENABLED:-false}" = true ]; then
    effective_services=$(nftables_merge_selected_services "$effective_services" ssh-server)
  fi


  if nftables_qemu_selected; then
    effective_services=$(nftables_merge_selected_services "$effective_services" qemu)
  fi

  if nftables_software_selected; then
    effective_services=$(nftables_merge_selected_services "$effective_services" qbittorrent)
  fi

  if [ "$effective_services" != "$selected_services" ]; then
    installer_info "nftables service overlays adjusted from ${selected_services:-none} to $(printf '%s' "$effective_services" | tr ' ' ',')"
  fi

  printf '%s\n' "$effective_services"
}

stage_target_nftables_service_assets() {
  for service_asset in "$@"; do
    if [ "$service_asset" = ssh-server ] && [ "${SSH_SERVER_ENABLED:-false}" = true ]; then
      render_target_asset_with_placeholder_map \
        "$(installer_repo_join_var DIR_HOOKS_TARGET "etc/nftables/services/${service_asset}.yml")" \
        "/etc/nftables/services/${service_asset}.yml" \
        0644 \
        nftables_ssh_service_placeholder_map
      continue
    fi
    if [ "$service_asset" = syncthing ] && nftables_tailscale_selected; then
      render_target_asset_with_placeholder_map \
        "$(installer_repo_join_var DIR_HOOKS_TARGET "etc/nftables/services/${service_asset}.yml")" \
        "/etc/nftables/services/${service_asset}.yml" \
        0644 \
        nftables_syncthing_service_placeholder_map
      continue
    fi
    if [ "$service_asset" = tailscale ] && nftables_tailscale_selected; then
      render_target_asset_with_placeholder_map \
        "$(installer_repo_join_var DIR_HOOKS_TARGET "etc/nftables/services/${service_asset}.yml")" \
        "/etc/nftables/services/${service_asset}.yml" \
        0644 \
        nftables_tailscale_service_placeholder_map
      continue
    fi
    if [ "$service_asset" = qemu ] && nftables_qemu_selected; then
      render_target_asset_with_placeholder_map \
        "$(installer_repo_join_var DIR_HOOKS_TARGET "etc/nftables/services/${service_asset}.yml")" \
        "/etc/nftables/services/${service_asset}.yml" \
        0644 \
        nftables_qemu_service_placeholder_map
      continue
    fi
    case "$service_asset" in
      ssh-server|syncthing|tailscale|qemu)
        stage_target_asset \
          "$(installer_repo_join_var DIR_HOOKS_TARGET "etc/nftables/services/${service_asset}.yml")" \
          "/etc/nftables/services/${service_asset}.yml" \
          0644
        ;;
      *)
        render_target_asset_with_placeholder_map \
          "$(installer_repo_join_var DIR_HOOKS_TARGET "etc/nftables/services/${service_asset}.yml")" \
          "/etc/nftables/services/${service_asset}.yml" \
          0644 \
          nftables_interface_placeholder_map
        ;;
    esac
  done
}

stage_target_nftables_profile_assets() {
  for profile_asset in baseline desktop; do
    render_target_asset_with_placeholder_map \
      "$(installer_repo_join_var DIR_HOOKS_TARGET "etc/nftables/profiles/${profile_asset}.yml")" \
      "/etc/nftables/profiles/${profile_asset}.yml" \
      0644 \
      nftables_interface_placeholder_map
  done
}

stage_target_nftables_all_service_assets() {
  for service_asset in $(nftables_service_assets); do
    stage_target_nftables_service_assets "$service_asset"
  done
}

nftables_service_overlay_paths() {
  selected_paths=

  for service_asset in "$@"; do
    selected_paths="${selected_paths:+$selected_paths }/etc/nftables/services/${service_asset}.yml"
  done

  printf '%s\n' "$selected_paths"
}

nftables_runtime_cidr_pairs() {
  if [ "${MANAGED_NETWORK_IPV6_ENABLED:-false}" = true ]; then
    for cidr in ${MANAGED_NETWORK_IPV6_HOST_CIDRS:-${MANAGED_NETWORK_IPV6_HOST_CIDR:-}}; do
      printf '%s\n' "desktop_static_ipv6_host=${cidr}"
    done
    for cidr in ${MANAGED_NETWORK_IPV6_NETWORK_CIDRS:-${MANAGED_NETWORK_IPV6_NETWORK_CIDR:-}}; do
      printf '%s\n' "desktop_static_ipv6_network=${cidr}"
      printf '%s\n' "lan_ipv6=${cidr}"
    done
  fi
  if [ "${MANAGED_NETWORK_IPV4_ENABLED:-false}" = true ]; then
    for cidr in ${MANAGED_NETWORK_IPV4_NETWORK_CIDRS:-}; do
      printf '%s\n' "lan_ipv4=${cidr}"
    done
  fi
}

nftables_runtime_cidrs_env_value() {
  runtime_cidrs=
  while IFS= read -r cidr_pair || [ -n "$cidr_pair" ]; do
    [ -n "$cidr_pair" ] || continue
    runtime_cidrs="${runtime_cidrs:+$runtime_cidrs }${cidr_pair}"
  done <<EOF
$(nftables_runtime_cidr_pairs)
EOF
  printf '%s\n' "$runtime_cidrs"
}

nftables_managed_iface_value() {
  label=$1
  value=$2
  fallback=$3
  iface=${value:-$fallback}

  case "$iface" in
    ''|.|..|lo)
      installer_fatal "${label} must be a non-loopback interface name"
      ;;
  esac
  case "$iface" in
    *[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-]*)
      installer_fatal "${label} contains unsupported characters: ${iface}"
      ;;
  esac
  [ "${#iface}" -le 15 ] || installer_fatal "${label} must be 15 characters or fewer: ${iface}"
  printf '%s\n' "$iface"
}

nftables_interface_placeholder_map() {
  ethernet_iface=$(nftables_managed_iface_value MANAGED_NETWORK_ETHERNET_IFACE "${MANAGED_NETWORK_ETHERNET_IFACE:-}" managed-eth0)
  wifi_iface=$(nftables_managed_iface_value MANAGED_NETWORK_WIFI_IFACE "${MANAGED_NETWORK_WIFI_IFACE:-}" managed-wifi0)

  [ "$ethernet_iface" != "$wifi_iface" ] ||
    installer_fatal "MANAGED_NETWORK_ETHERNET_IFACE and MANAGED_NETWORK_WIFI_IFACE must differ"

  printf 'MANAGED_NETWORK_ETHERNET_IFACE=%s\n' "$ethernet_iface"
  printf 'MANAGED_NETWORK_WIFI_IFACE=%s\n' "$wifi_iface"
}

nftables_validate_port_value() {
  label=$1
  value=$2

  case "$value" in
    ''|*[!0-9]*)
      installer_fatal "${label} must be a numeric TCP/UDP port"
      ;;
  esac
  [ "$value" -ge 1 ] && [ "$value" -le 65535 ] ||
    installer_fatal "${label} must be in range 1..65535"
}

nftables_validate_cidr_token() {
  label=$1
  value=$2

  case "$value" in
    ''|*[!0123456789abcdefABCDEF:./]*)
      installer_fatal "${label} contains unsupported CIDR characters: ${value:-unset}"
      ;;
  esac
  case "$value" in
    */*)
      ;;
    *)
      installer_fatal "${label} must be CIDR-formatted"
      ;;
  esac
}

nftables_yaml_inline_list() {
  if [ "$#" -eq 0 ]; then
    printf '[]\n'
    return 0
  fi

  first=true
  printf '['
  for item in "$@"; do
    [ -n "$item" ] || continue
    if [ "$first" = true ]; then
      first=false
    else
      printf ', '
    fi
    printf '"%s"' "$item"
  done
  if [ "$first" = true ]; then
    printf '[]\n'
    return 0
  fi
  printf ']\n'
}

nftables_merge_unique_tokens() {
  merged=
  for token in "$@"; do
    [ -n "$token" ] || continue
    case " $merged " in
      *" $token "*) ;;
      *) merged="${merged:+$merged }$token" ;;
    esac
  done
  printf '%s\n' "$merged"
}

nftables_ipv4_to_int() {
  addr=$1
  old_ifs=${IFS}
  IFS=.
  set -- $addr
  IFS=${old_ifs}
  [ "$#" -eq 4 ] || installer_fatal "invalid IPv4 address: ${addr}"
  for octet in "$@"; do
    case "$octet" in
      ''|*[!0-9]*)
        installer_fatal "invalid IPv4 address: ${addr}"
        ;;
    esac
    [ "$octet" -ge 0 ] && [ "$octet" -le 255 ] ||
      installer_fatal "invalid IPv4 address: ${addr}"
  done
  printf '%s\n' "$((($1 << 24) + ($2 << 16) + ($3 << 8) + $4))"
}

nftables_ipv4_from_int() {
  value=$1
  printf '%s.%s.%s.%s\n' \
    "$(((value >> 24) & 255))" \
    "$(((value >> 16) & 255))" \
    "$(((value >> 8) & 255))" \
    "$((value & 255))"
}

nftables_ipv4_network_cidr() {
  addr=$1
  prefix=$2

  nftables_validate_port_value IPv4_prefix_length "$prefix"
  [ "$prefix" -le 32 ] || installer_fatal "IPv4 prefix length must be 32 or lower"
  addr_int=$(nftables_ipv4_to_int "$addr")
  if [ "$prefix" -eq 0 ]; then
    mask=0
  else
    mask=$(((0xffffffff << (32 - prefix)) & 0xffffffff))
  fi
  network_int=$((addr_int & mask))
  printf '%s/%s\n' "$(nftables_ipv4_from_int "$network_int")" "$prefix"
}

nftables_ipv6_expand() {
  addr=$1
  has_double_colon=false
  head=${addr}
  tail=

  case "$addr" in
    *::*)
      has_double_colon=true
      head=${addr%%::*}
      tail=${addr#*::}
      ;;
  esac

  head_count=0
  tail_count=0
  head_words=
  tail_words=

  if [ -n "$head" ]; then
    head_words=$(printf '%s\n' "$head" | tr ':' ' ')
    set -- $head_words
    head_count=$#
  fi
  if [ -n "$tail" ]; then
    tail_words=$(printf '%s\n' "$tail" | tr ':' ' ')
    set -- $tail_words
    tail_count=$#
  fi

  if [ "$has_double_colon" = true ]; then
    missing=$((8 - head_count - tail_count))
    [ "$missing" -ge 0 ] || installer_fatal "invalid IPv6 address: ${addr}"
  else
    missing=0
    [ $((head_count + tail_count)) -eq 8 ] || installer_fatal "invalid IPv6 address: ${addr}"
  fi

  expanded=
  for field in $head_words; do
    [ -n "$field" ] || continue
    expanded="${expanded:+$expanded }$field"
  done
  while [ "$missing" -gt 0 ]; do
    expanded="${expanded:+$expanded }0"
    missing=$((missing - 1))
  done
  for field in $tail_words; do
    [ -n "$field" ] || continue
    expanded="${expanded:+$expanded }$field"
  done

  set -- $expanded
  [ "$#" -eq 8 ] || installer_fatal "invalid IPv6 address: ${addr}"
  for field in "$@"; do
    case "$field" in
      ''|*[!0123456789abcdefABCDEF]*)
        installer_fatal "invalid IPv6 address: ${addr}"
        ;;
    esac
    [ "${#field}" -le 4 ] || installer_fatal "invalid IPv6 address: ${addr}"
  done
  printf '%s\n' "$expanded"
}

nftables_ipv6_network_cidr() {
  addr=$1
  prefix=$2

  nftables_validate_port_value IPv6_prefix_length "$prefix"
  [ "$prefix" -le 128 ] || installer_fatal "IPv6 prefix length must be 128 or lower"
  [ $((prefix % 16)) -eq 0 ] ||
    installer_fatal "IPv6 prefix length must align to 16-bit boundaries for SSH nftables rendering"
  keep_hextets=$((prefix / 16))
  expanded=$(nftables_ipv6_expand "$addr")
  index=0
  network=
  for field in $expanded; do
    if [ "$index" -lt "$keep_hextets" ]; then
      network="${network:+$network:}$field"
    else
      network="${network:+$network:}0"
    fi
    index=$((index + 1))
  done
  printf '%s/%s\n' "$network" "$prefix"
}

nftables_tailscale_selected() {
  installer_selected_class_reference_is_selected addon/tailscale 2>/dev/null
}

nftables_qemu_selected() {
  installer_selected_class_reference_is_selected addon/qemu 2>/dev/null || return 1
  [ "${INSTALLER_HOST_VARIANT:-}" = desktop ]
}

nftables_software_selected() {
  installer_selected_class_reference_is_selected addon/software 2>/dev/null || return 1
  [ "${INSTALLER_HOST_VARIANT:-}" = desktop ]
}

nftables_qemu_allow_interfaces() {
  incus_bridge=${INCUS_BRIDGE_NAME:-incusbr0}
  nftables_managed_iface_value INCUS_BRIDGE_NAME "$incus_bridge" incusbr0
}

nftables_qemu_service_placeholder_map() {
  qemu_allow_interfaces=$(nftables_qemu_allow_interfaces)
  printf 'NFTABLES_QEMU_ALLOW_INTERFACES=%s\n' "$(nftables_yaml_inline_list $qemu_allow_interfaces)"
}

nftables_tailscale_interface() {
  tailscale_iface=${TAILSCALE_INTERFACE:-tailscale0}
  nftables_managed_iface_value TAILSCALE_INTERFACE "$tailscale_iface" tailscale0
}

nftables_tailscale_allow_ipv4_cidrs() {
  printf '%s\n' '100.64.0.0/10'
}

nftables_tailscale_allow_ipv6_cidrs() {
  printf '%s\n' 'fd7a:115c:a1e0::/48'
}

nftables_ssh_allow_interfaces() {
  ethernet_iface=$(nftables_managed_iface_value MANAGED_NETWORK_ETHERNET_IFACE "${MANAGED_NETWORK_ETHERNET_IFACE:-}" managed-eth0)
  wifi_iface=$(nftables_managed_iface_value MANAGED_NETWORK_WIFI_IFACE "${MANAGED_NETWORK_WIFI_IFACE:-}" managed-wifi0)

  [ "$ethernet_iface" != "$wifi_iface" ] ||
    installer_fatal "MANAGED_NETWORK_ETHERNET_IFACE and MANAGED_NETWORK_WIFI_IFACE must differ"

  cat <<EOF
eth0
en*
$ethernet_iface
wlan0
wl*
$wifi_iface
wg0
EOF
}

nftables_ssh_allow_ipv4_cidrs() {
  if [ -n "${MANAGED_NETWORK_IPV4_NETWORK_CIDRS:-}" ]; then
    printf '%s\n' "$(nftables_merge_unique_tokens ${MANAGED_NETWORK_IPV4_NETWORK_CIDRS})"
    return 0
  fi
  cat <<'EOF'
10.0.0.0/8
172.16.0.0/12
192.168.0.0/16
EOF
}

nftables_ssh_allow_ipv6_cidrs() {
  if [ -n "${MANAGED_NETWORK_IPV6_NETWORK_CIDRS:-}" ]; then
    printf '%s\n' "$(nftables_merge_unique_tokens ${MANAGED_NETWORK_IPV6_NETWORK_CIDRS})"
    return 0
  fi
  cat <<'EOF'
fc00::/7
fe80::/10
EOF
}

nftables_ssh_service_placeholder_map() {
  ssh_allow_ipv4=$(nftables_ssh_allow_ipv4_cidrs)
  ssh_allow_ipv6=$(nftables_ssh_allow_ipv6_cidrs)
  ssh_allow_interfaces=$(nftables_ssh_allow_interfaces)

  runtime_apply_ssh_from_cmdline
  nftables_validate_port_value SSH_PORT "$SSH_PORT"
  while IFS= read -r cidr || [ -n "$cidr" ]; do
    [ -n "$cidr" ] || continue
    nftables_validate_cidr_token SSH_allow_ipv4 "$cidr"
  done <<EOF
$ssh_allow_ipv4
EOF
  while IFS= read -r cidr || [ -n "$cidr" ]; do
    [ -n "$cidr" ] || continue
    nftables_validate_cidr_token SSH_allow_ipv6 "$cidr"
  done <<EOF
$ssh_allow_ipv6
EOF

  nftables_interface_placeholder_map
  printf 'SSH_PORT=%s\n' "$SSH_PORT"
  printf 'NFTABLES_SSH_ALLOW_IPV4=%s\n' "$(nftables_yaml_inline_list $ssh_allow_ipv4)"
  printf 'NFTABLES_SSH_ALLOW_IPV6=%s\n' "$(nftables_yaml_inline_list $ssh_allow_ipv6)"
  printf 'NFTABLES_SSH_ALLOW_INTERFACES=%s\n' "$(nftables_yaml_inline_list $ssh_allow_interfaces)"
}

fail2ban_jail_placeholder_map() {
  runtime_apply_ssh_from_cmdline
  nftables_validate_port_value SSH_PORT "$SSH_PORT"
  printf 'SSH_PORT=%s\n' "$SSH_PORT"
}

nftables_syncthing_service_placeholder_map() {
  syncthing_tcp_port=${SYNCTHING_TCP_PORT:-35000}
  syncthing_iface=$(nftables_tailscale_interface)

  nftables_validate_port_value SYNCTHING_TCP_PORT "$syncthing_tcp_port"
  printf 'SYNCTHING_TCP_PORT=%s\n' "$syncthing_tcp_port"
  printf 'NFTABLES_SYNCTHING_ALLOW_IPV4=%s\n' "$(nftables_yaml_inline_list $(nftables_tailscale_allow_ipv4_cidrs))"
  printf 'NFTABLES_SYNCTHING_ALLOW_IPV6=%s\n' "$(nftables_yaml_inline_list $(nftables_tailscale_allow_ipv6_cidrs))"
  printf 'NFTABLES_SYNCTHING_ALLOW_INTERFACES=%s\n' "$(nftables_yaml_inline_list "$syncthing_iface")"
}

nftables_tailscale_service_placeholder_map() {
  tailscale_udp_port=${TAILSCALE_UDP_PORT:-41641}
  tailscale_ssh_enabled=${TAILSCALE_RUN_SSH_SERVER:-true}
  tailscale_iface=$(nftables_tailscale_interface)

  nftables_validate_port_value TAILSCALE_UDP_PORT "$tailscale_udp_port"
  case "$tailscale_ssh_enabled" in
    true|false) ;;
    *) installer_fatal "TAILSCALE_RUN_SSH_SERVER must be true or false for nftables rendering" ;;
  esac
  nftables_interface_placeholder_map
  printf 'TAILSCALE_UDP_PORT=%s\n' "$tailscale_udp_port"
  printf 'TAILSCALE_RUN_SSH_SERVER=%s\n' "$tailscale_ssh_enabled"
  printf 'NFTABLES_TAILSCALE_ALLOW_IPV4=%s\n' "$(nftables_yaml_inline_list $(nftables_tailscale_allow_ipv4_cidrs))"
  printf 'NFTABLES_TAILSCALE_ALLOW_IPV6=%s\n' "$(nftables_yaml_inline_list $(nftables_tailscale_allow_ipv6_cidrs))"
  printf 'NFTABLES_TAILSCALE_ALLOW_INTERFACES=%s\n' "$(nftables_yaml_inline_list "$tailscale_iface")"
}

apparmor_managed_profile_files() {
  apparmor_managed_system_profile_files
  apparmor_managed_desktop_profile_files
}

apparmor_managed_system_profile_files() {
  cat <<'EOF'
managed-system-wrappers
crun
timeshift
slirp4netns
usr.sbin.aa-status
usr.sbin.tailscaled
EOF
}

apparmor_managed_modes_perl_modules() {
  cat <<'EOF'
AppArmor/ManagedModes/CLI.pm
AppArmor/ManagedModes/Config.pm
AppArmor/ManagedModes/Logger.pm
AppArmor/ManagedModes/TrustedPath.pm
AppArmor/ManagedModes/Tool.pm
AppArmor/ManagedModes/Transition.pm
AppArmor/ManagedModes/LoadedState.pm
AppArmor/ManagedModes/Verify.pm
AppArmor/ManagedModes/Workspace.pm
EOF
}

apparmor_managed_desktop_profile_files() {
  cat <<'EOF'
managed-desktop-wrappers
managed-document-applications
managed-labwc-session
managed-desktop-utilities
whisper-local-transcription
usr.bin.totem
usr.bin.qoredb
usr.bin.spotify
usr.bin.sqlitebrowser
usr.bin.retroarch
usr.bin.qbittorrent
usr.bin.telegram-desktop
usr.bin.keepassxc
usr.bin.zoom
opt.Bitwarden.bitwarden
opt.Filen.Filen
opt.postman.app.Postman
opt.ledger-live.AppRun
opt.tuta-mail.AppRun
Discord
obsidian
sleek
usr.bin.pwsh
usr.sbin.apt-cacher-ng
usr.sbin.avahi-daemon
EOF
  if installer_selected_class_reference_is_selected addon/devops 2>/dev/null; then
    printf '%s\n' chatgpt
  fi
}

apparmor_requested_desktop_state() {
  desktop_apparmor_state=${DESKTOP_APPARMOR_STATE:-}

  case "$desktop_apparmor_state" in
    enforce|complain)
      printf '%s\n' "$desktop_apparmor_state"
      ;;
    '')
      installer_fatal "DESKTOP_APPARMOR_STATE must be set by every desktop host profile"
      return 1
      ;;
    *)
      installer_fatal "DESKTOP_APPARMOR_STATE must be enforce or complain, got: ${desktop_apparmor_state}"
      return 1
      ;;
  esac
}

apparmor_apply_desktop_state() {
  mode_config=$1

  desktop_apparmor_state=$(apparmor_requested_desktop_state) || return 1
  desktop_apparmor_tmp="${mode_config}.desktop-state.$$"

  awk \
    -v selected_state="$desktop_apparmor_state" '
      /^[[:space:]]*(#|$)/ {
        print
        next
      }
      {
        if (NF != 4) {
          exit 40
        }
        if ($1 != "__DESKTOP_APPARMOR_STATE__" ||
            $2 !~ /^(required|optional|if-executable)$/ ||
            $3 !~ /^[A-Za-z0-9._+-]+$/ ||
            ($2 == "if-executable" && $4 !~ /^\//) ||
            ($2 != "if-executable" && $4 != "-")) {
          exit 41
        }
        if (++seen[$3] != 1) {
          exit 42
        }
        rows++
        $1 = selected_state
        print
      }
      END {
        if (rows == 0) {
          exit 43
        }
      }
    ' "$mode_config" >"$desktop_apparmor_tmp" || {
      rm -f -- "$desktop_apparmor_tmp"
      installer_fatal "failed to apply DESKTOP_APPARMOR_STATE=${desktop_apparmor_state} to every declared managed AppArmor profile"
      return 1
    }

  install -m 0644 "$desktop_apparmor_tmp" "$mode_config" || {
    rm -f -- "$desktop_apparmor_tmp"
    installer_fatal "failed to publish desktop AppArmor mode policy: ${mode_config}"
    return 1
  }
  rm -f -- "$desktop_apparmor_tmp"
  installer_info "all declared managed AppArmor profile state: ${desktop_apparmor_state}"
}

security_nvidia_acceleration_enabled() {
  nvidia_addon_selected=${NVIDIA_ADDON_SELECTED:-false}
  nvidia_gpu_detected=${NVIDIA_GPU_DETECTED:-false}

  case "$nvidia_addon_selected" in
    true|false) ;;
    *)
      installer_fatal "NVIDIA_ADDON_SELECTED must be true or false, got: ${nvidia_addon_selected}"
      return 1
      ;;
  esac
  case "$nvidia_gpu_detected" in
    true|false) ;;
    *)
      installer_fatal "NVIDIA_GPU_DETECTED must be true or false, got: ${nvidia_gpu_detected}"
      return 1
      ;;
  esac

  [ "$nvidia_addon_selected" = true ] && [ "$nvidia_gpu_detected" = true ]
}

apparmor_managed_local_include_files() {
  cat <<'EOF'
code
chromium
microsoft-edge-stable
mullvad-browser
vivaldi-stable
vivaldi-bin
EOF
}

apparmor_support_local_include_files() {
  cat <<'EOF'
usr.bin.freshclam
usr.bin.pasta
slirp4netns
EOF
}

apparmor_obsolete_local_include_files() {
  cat <<'EOF'
crun
timeshift
timeshift-gtk
usr.bin.timeshift
usr.bin.timeshift-gtk
EOF
}

apparmor_compat_desktop_local_include_files() {
  cat <<'EOF'
1password
brave
chrome
element-desktop
firefox
github-desktop
keybase
opera
qutebrowser
signal-desktop
slack
steam
EOF
}

apparmor_mode_config_has_profile() {
  profile_name=$1
  mode_config=$2

  awk -v expected_profile="$profile_name" '
    /^[[:space:]]*(#|$)/ { next }
    NF == 4 && $3 == expected_profile { matches++ }
    END { exit(matches == 1 ? 0 : 1) }
  ' "$mode_config"
}

apparmor_require_disconnected_profile_flags() {
  profile_path=$1
  profile_name=$2
  unsafe_flag_policy=${3:-reject}

  case "$profile_path" in
    /target/etc/apparmor.d/*) ;;
    *) installer_fatal "refusing to rewrite AppArmor profile outside target policy: ${profile_path}" ;;
  esac
  # Package-owned profiles are direct files in this directory. Reject nested
  # and traversal-shaped inputs before any read or temporary-file creation.
  profile_basename=${profile_path#/target/etc/apparmor.d/}
  case "$profile_basename" in
    ''|*/*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._+-]*)
      installer_fatal "refusing non-direct AppArmor profile source path: ${profile_path}"
      ;;
  esac
  case "$profile_name" in
    ''|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._+-]*)
      installer_fatal "invalid AppArmor profile label for flag normalization: ${profile_name:-unset}"
      ;;
  esac
  case "$unsafe_flag_policy" in
    reject|strip-unconfined) ;;
    *) installer_fatal "invalid AppArmor unsafe-flag policy for ${profile_name}: ${unsafe_flag_policy:-unset}" ;;
  esac
  [ -f "$profile_path" ] ||
    installer_fatal "required AppArmor profile source is missing: ${profile_path}"
  [ ! -L "$profile_path" ] ||
    installer_fatal "refusing symlinked AppArmor profile source: ${profile_path}"
  profile_size=$(wc -c <"$profile_path") ||
    installer_fatal "cannot size AppArmor profile source: ${profile_path}"
  case "$profile_size" in
    ''|*[!0-9]*) installer_fatal "invalid AppArmor profile size: ${profile_path}" ;;
  esac
  [ "$profile_size" -le 1048576 ] ||
    installer_fatal "AppArmor profile source exceeds 1048576 bytes: ${profile_path}"

  profile_tmp=$(mktemp "${profile_path}.flags.XXXXXX") ||
    installer_fatal "cannot create AppArmor profile flag workspace: ${profile_path}"
  chmod 0600 "$profile_tmp" || {
    rm -f -- "$profile_tmp"
    installer_fatal "cannot secure AppArmor profile flag workspace: ${profile_path}"
  }

  if ! awk \
    -v expected_profile="$profile_name" \
    -v unsafe_flag_policy="$unsafe_flag_policy" '
    function trim(value) {
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
      return value
    }
    function add_flag(value) {
      if (!(value in seen)) {
        seen[value] = 1
        flags[++flag_count] = value
      }
    }
    $1 == "profile" && $2 == expected_profile {
      matches++
      if (matches != 1 || $0 !~ /[{][[:space:]]*$/) {
        exit 40
      }

      line = $0
      if (match(line, /flags=[(][^)]*[)]/)) {
        existing = substr(line, RSTART + 7, RLENGTH - 8)
        field_count = split(existing, fields, ",")
        for (field_index = 1; field_index <= field_count; field_index++) {
          flag = trim(fields[field_index])
          if (flag !~ /^[A-Za-z0-9_.+-]+$/) {
            exit 41
          }
          if (flag == "unconfined" || flag == "default_allow") {
            if (flag == "unconfined" &&
                unsafe_flag_policy == "strip-unconfined") {
              continue
            }
            exit 43
          }
          add_flag(flag)
        }
        add_flag("attach_disconnected")
        add_flag("mediate_deleted")
        rebuilt = flags[1]
        for (flag_index = 2; flag_index <= flag_count; flag_index++) {
          rebuilt = rebuilt ", " flags[flag_index]
        }
        line = substr(line, 1, RSTART - 1) "flags=(" rebuilt ")" \
          substr(line, RSTART + RLENGTH)
      } else {
        sub(/[[:space:]]*[{][[:space:]]*$/, \
          " flags=(attach_disconnected, mediate_deleted) {", line)
      }
      print line
      next
    }
    { print }
    END {
      if (matches != 1) {
        exit 42
      }
    }
  ' "$profile_path" >"$profile_tmp"; then
    rm -f -- "$profile_tmp"
    installer_fatal "cannot normalize disconnected-path flags for AppArmor profile: ${profile_name}"
  fi

  chmod 0644 "$profile_tmp" || {
    rm -f -- "$profile_tmp"
    installer_fatal "cannot set AppArmor profile mode before publishing: ${profile_name}"
  }
  mv -f -- "$profile_tmp" "$profile_path" || {
    rm -f -- "$profile_tmp"
    installer_fatal "cannot atomically publish disconnected-path flags for AppArmor profile: ${profile_name}"
  }
}

apparmor_obsolete_profile_files() {
  cat <<'EOF'
opt.microsoft.msedge.msedge
timeshift-gtk
usr.bin.code
usr.bin.microsoft-edge-stable
usr.bin.mullvad-browser
usr.bin.timeshift
usr.bin.timeshift-gtk
EOF
}

stage_target_system_apparmor_profiles() {
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/apparmor.d/abstractions/managed-wrapper-base)" \
    "/etc/apparmor.d/abstractions/managed-wrapper-base" \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/apparmor.d/abstractions/managed-wrapper-perl)" \
    "/etc/apparmor.d/abstractions/managed-wrapper-perl" \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/apparmor.d/abstractions/managed-crun-runtime)" \
    "/etc/apparmor.d/abstractions/managed-crun-runtime" \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/apparmor.d/abstractions/managed-timeshift-runtime)" \
    "/etc/apparmor.d/abstractions/managed-timeshift-runtime" \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/apparmor.d/abstractions/managed-wrapper-python)" \
    "/etc/apparmor.d/abstractions/managed-wrapper-python" \
    0644

  for apparmor_profile in $(apparmor_managed_system_profile_files); do
    stage_target_asset \
      "$(installer_repo_join_var DIR_HOOKS_TARGET "etc/apparmor.d/${apparmor_profile}")" \
      "/etc/apparmor.d/${apparmor_profile}" \
      0644
  done
}

stage_target_desktop_apparmor_profiles() {
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/apparmor.d/abstractions/managed-devops-toolchain-data)" \
    "/etc/apparmor.d/abstractions/managed-devops-toolchain-data" \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/apparmor.d/abstractions/managed-user-documents)" \
    "/etc/apparmor.d/abstractions/managed-user-documents" \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/apparmor.d/abstractions/managed-document-runtime)" \
    "/etc/apparmor.d/abstractions/managed-document-runtime" \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/apparmor.d/abstractions/managed-session-client)" \
    "/etc/apparmor.d/abstractions/managed-session-client" \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/apparmor.d/abstractions/managed-wrapper-desktop)" \
    "/etc/apparmor.d/abstractions/managed-wrapper-desktop" \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/apparmor.d/abstractions/managed-wrapper-gui)" \
    "/etc/apparmor.d/abstractions/managed-wrapper-gui" \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/apparmor.d/abstractions/managed-wrapper-wayland)" \
    "/etc/apparmor.d/abstractions/managed-wrapper-wayland" \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/apparmor.d/abstractions/audio.d/managed-no-raw-audio)" \
    "/etc/apparmor.d/abstractions/audio.d/managed-no-raw-audio" \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/apparmor.d/abstractions/managed-pipewire-audio)" \
    "/etc/apparmor.d/abstractions/managed-pipewire-audio" \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/apparmor.d/abstractions/managed-bwrap-common)" \
    "/etc/apparmor.d/abstractions/managed-bwrap-common" \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/apparmor.d/abstractions/managed-bwrap-desktop-runtime)" \
    "/etc/apparmor.d/abstractions/managed-bwrap-desktop-runtime" \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/apparmor.d/abstractions/managed-devops-toolchain-runtime)" \
    "/etc/apparmor.d/abstractions/managed-devops-toolchain-runtime" \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/apparmor.d/abstractions/managed-codex-runtime)" \
    "/etc/apparmor.d/abstractions/managed-codex-runtime" \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/apparmor.d/abstractions/managed-electron-runtime)" \
    "/etc/apparmor.d/abstractions/managed-electron-runtime" \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/apparmor.d/abstractions/managed-electron-application)" \
    "/etc/apparmor.d/abstractions/managed-electron-application" \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/apparmor.d/abstractions/managed-webkit-runtime)" \
    "/etc/apparmor.d/abstractions/managed-webkit-runtime" \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/apparmor.d/abstractions/managed-desktop-graphics)" \
    "/etc/apparmor.d/abstractions/managed-desktop-graphics" \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/apparmor.d/abstractions/managed-desktop-runtime)" \
    "/etc/apparmor.d/abstractions/managed-desktop-runtime" \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/apparmor.d/abstractions/managed-desktop-application)" \
    "/etc/apparmor.d/abstractions/managed-desktop-application" \
    0644

  for apparmor_profile in $(apparmor_managed_desktop_profile_files); do
    stage_target_asset \
      "$(installer_repo_join_var DIR_HOOKS_TARGET "etc/apparmor.d/${apparmor_profile}")" \
      "/etc/apparmor.d/${apparmor_profile}" \
      0644
  done

  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/apparmor.d/local/managed-desktop-application)" \
    "/etc/apparmor.d/local/managed-desktop-application" \
    0644
  if security_nvidia_acceleration_enabled; then
    stage_target_asset \
      "$(installer_hardware_asset_path gpu nvidia etc/apparmor.d/local/managed-desktop-graphics)" \
      "/etc/apparmor.d/local/managed-desktop-graphics" \
      0644
    stage_target_asset \
      "$(installer_hardware_asset_path gpu nvidia etc/apparmor.d/local/managed-desktop-wrappers-nvidia)" \
      "/etc/apparmor.d/local/managed-desktop-wrappers-nvidia" \
      0644
  else
    rm -f \
      /target/etc/apparmor.d/local/managed-desktop-graphics \
      /target/etc/apparmor.d/local/managed-desktop-wrappers-nvidia
  fi
  for apparmor_local_include in $(apparmor_managed_local_include_files); do
    stage_target_asset \
      "$(installer_repo_join_var DIR_HOOKS_TARGET "etc/apparmor.d/local/${apparmor_local_include}")" \
      "/etc/apparmor.d/local/${apparmor_local_include}" \
      0644
  done
	for apparmor_local_include in $(apparmor_support_local_include_files); do
	  stage_target_asset \
	    "$(installer_repo_join_var DIR_HOOKS_TARGET "etc/apparmor.d/local/${apparmor_local_include}")" \
	    "/etc/apparmor.d/local/${apparmor_local_include}" \
	    0644
	done
	# Edge's package-owned outer profile ships unconfined. Strip only that known
	# vendor flag, then attach nameless renderer paths and keep deleted objects
	# mediated by policy.
	if [ -e /target/etc/apparmor.d/microsoft-edge-stable ] || [ -L /target/etc/apparmor.d/microsoft-edge-stable ]; then
	  apparmor_require_disconnected_profile_flags \
	    "/target/etc/apparmor.d/microsoft-edge-stable" \
	    microsoft-edge-stable \
	    strip-unconfined
	fi
	# Mullvad Browser's package-owned outer profile ships unconfined while the
	# tracked local include provides the managed policy. Strip only that known
	# vendor flag, then attach and mediate nameless disconnected VA-API paths.
	if [ -e /target/etc/apparmor.d/mullvad-browser ] || [ -L /target/etc/apparmor.d/mullvad-browser ]; then
	  apparmor_require_disconnected_profile_flags \
	    "/target/etc/apparmor.d/mullvad-browser" \
	    mullvad-browser \
	    strip-unconfined
	fi
	# The package's /usr/bin/vivaldi-stable entry is an absolute symlink to this
  # wrapper. Test the direct target-root path so the installer never resolves
  # the symlink against its own root and silently skips the confined profiles.
  if [ -x /target/opt/vivaldi/vivaldi ]; then
    for apparmor_profile in vivaldi-stable vivaldi-bin; do
      stage_target_asset \
        "$(installer_repo_join_var DIR_HOOKS_TARGET "etc/apparmor.d/${apparmor_profile}")" \
        "/etc/apparmor.d/${apparmor_profile}" \
        0644
      apparmor_require_disconnected_profile_flags \
        "/target/etc/apparmor.d/${apparmor_profile}" \
        "$apparmor_profile"
    done
  fi
  for apparmor_local_include in $(apparmor_obsolete_local_include_files); do
    rm -f "/target/etc/apparmor.d/local/${apparmor_local_include}"
  done
  rm -f \
    /target/etc/apparmor.d/disable/crun \
    /target/etc/apparmor.d/disable/timeshift \
    /target/etc/apparmor.d/force-complain/crun \
    /target/etc/apparmor.d/force-complain/timeshift
  for apparmor_local_include in $(apparmor_compat_desktop_local_include_files); do
    stage_target_asset \
      "$(installer_repo_join_var DIR_HOOKS_TARGET etc/apparmor.d/local/managed-desktop-application)" \
      "/etc/apparmor.d/local/${apparmor_local_include}" \
      0644
  done

  for apparmor_obsolete_profile in $(apparmor_obsolete_profile_files); do
    rm -f \
      "/target/etc/apparmor.d/${apparmor_obsolete_profile}" \
      "/target/etc/apparmor.d/disable/${apparmor_obsolete_profile}" \
      "/target/etc/apparmor.d/force-complain/${apparmor_obsolete_profile}"
  done
}

nftables_default_placeholder_map() {
  write_shell_config_var NFTABLES_LOG_LEVEL "${NFTABLES_LOG_LEVEL:-none}"
  write_shell_config_var NFT_PROFILE "${NFTABLES_DEFAULT_REQUESTED_PROFILE:-default}"
  write_shell_config_var NFT_SERVICES "${NFTABLES_DEFAULT_SELECTED_SERVICES_CSV:-none}"
  write_shell_config_var NFT_POLICY_PROFILE "/etc/nftables/profiles/${NFTABLES_DEFAULT_SELECTED_PROFILE:-default}.yml"
  write_shell_config_var NFT_POLICY_RESOLVED_PROFILE "${NFTABLES_DEFAULT_SELECTED_PROFILE:-default}"
  write_shell_config_var NFT_POLICY_DEFAULT_PROFILE /etc/nftables/profiles/default.yml
  write_shell_config_var NFT_POLICY_SERVICE_OVERLAYS "${NFTABLES_DEFAULT_SERVICE_OVERLAYS:-}"
  write_shell_config_var NFT_POLICY_RUNTIME_CIDRS "${NFTABLES_DEFAULT_RUNTIME_CIDRS:-}"
  write_shell_config_var NFT_POLICY_GENERATOR /usr/local/sbin/nft-policy-generate
}

clear_target_nftables_assets() {
  if [ -r /target/etc/nftables.conf ] &&
     grep -E -q 'Managed by (unattended-installer|nft-policy-generate[.]py)' /target/etc/nftables.conf; then
    rm -f /target/etc/nftables.conf
  fi

  rm -f \
    /target/etc/default/nft-policy-generate \
    /target/usr/local/sbin/nft-policy-generate \
    /target/etc/systemd/system/nftables.service.d/override.conf \
    /target/etc/nftables/README.md \
    /target/etc/nftables/profiles/baseline.yml \
    /target/etc/nftables/profiles/default.yml \
    /target/etc/nftables/profiles/desktop.yml \
    /target/etc/nftables/profiles/server.yml \
    /target/etc/nftables.d/00-defines.nft \
    /target/etc/nftables.d/10-base.nft \
    /target/etc/nftables.d/20-filter.nft \
    /target/etc/nftables.d/30-nat.nft \
    /target/etc/nftables.d/90-local.nft \
    /target/etc/nftables.d/95-firewall-security.nft \
    /target/etc/nftables/firewall-security.rules

  for service_asset in $(nftables_service_assets); do
    rm -f "/target/etc/nftables/services/${service_asset}.yml"
  done

  if command -v unstage_target_systemd_unit_enabled >/dev/null 2>&1; then
    unstage_target_systemd_unit_enabled nftables.service system
  fi
  rmdir /target/etc/systemd/system/nftables.service.d 2>/dev/null || true
  rmdir /target/etc/nftables/services /target/etc/nftables/profiles /target/etc/nftables /target/etc/nftables.d 2>/dev/null || true
}

write_target_nftables_default_config() {
  selected_profile=$1
  requested_profile=$2
  selected_services=$3
  runtime_cidrs=${4:-}

  old_ifs=$IFS
  IFS=' '
  # shellcheck disable=SC2086
  set -- $selected_services
  IFS=$old_ifs
  NFTABLES_DEFAULT_SELECTED_PROFILE=$selected_profile
  NFTABLES_DEFAULT_REQUESTED_PROFILE=$requested_profile
  NFTABLES_DEFAULT_SELECTED_SERVICES_CSV=$(printf '%s' "$selected_services" | tr ' ' ',')
  NFTABLES_DEFAULT_SERVICE_OVERLAYS=$(nftables_service_overlay_paths "$@")
  NFTABLES_DEFAULT_RUNTIME_CIDRS=$runtime_cidrs

  render_target_asset_with_placeholder_map \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/default/nft-policy-generate.tmpl)" \
    /etc/default/nft-policy-generate \
    0644 \
    nftables_default_placeholder_map

  unset \
    NFTABLES_DEFAULT_SELECTED_PROFILE \
    NFTABLES_DEFAULT_REQUESTED_PROFILE \
    NFTABLES_DEFAULT_SELECTED_SERVICES_CSV \
    NFTABLES_DEFAULT_SERVICE_OVERLAYS \
    NFTABLES_DEFAULT_RUNTIME_CIDRS
}

configure_target_nftables() {
  requested_profile=$(late_command_nftables_requested_profile)
  selected_profile=$(late_command_nftables_profile "$requested_profile")
  installer_info "nftables profile selection: raw=${NFT_PROFILE:-default} normalized=${requested_profile} selected=${selected_profile}"

  if [ "$selected_profile" = none ]; then
    installer_info "NFT_PROFILE=none; skipping nftables profile, service overlay, and unit staging"
    clear_target_nftables_assets
    return 0
  fi

  if command -v target_prepare_managed_network_handoff_state >/dev/null 2>&1; then
    target_prepare_managed_network_handoff_state
  elif command -v target_prepare_managed_network_ipv6_handoff >/dev/null 2>&1; then
    target_prepare_managed_network_ipv6_handoff
  fi

  selected_services=$(late_command_nftables_effective_services)
  runtime_cidrs=$(nftables_runtime_cidrs_env_value)

  install -d -m 0755 \
    /target/etc/default \
    /target/etc/nftables \
    /target/etc/nftables/profiles \
    /target/etc/nftables/services \
    /target/etc/nftables.d \
    /target/etc/systemd/system/nftables.service.d \
    /target/usr/local/sbin

  rm -f \
    /target/etc/nftables/profiles/baseline.yml \
    /target/etc/nftables/profiles/default.yml \
    /target/etc/nftables/profiles/desktop.yml \
    /target/etc/nftables/profiles/server.yml \
    /target/etc/nftables.d/00-defines.nft \
    /target/etc/nftables.d/10-base.nft \
    /target/etc/nftables.d/20-filter.nft \
    /target/etc/nftables.d/30-nat.nft \
    /target/etc/nftables.d/90-local.nft \
    /target/etc/nftables.d/95-firewall-security.nft \
    /target/etc/nftables/firewall-security.rules
  for service_asset in $(nftables_service_assets); do
    rm -f "/target/etc/nftables/services/${service_asset}.yml"
  done

  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/sbin/nft-policy-generate.py)" "/usr/local/sbin/nft-policy-generate" 0755
  render_target_asset_with_placeholder_map "$(installer_repo_join_var DIR_HOOKS_TARGET etc/nftables/README.md)" "/etc/nftables/README.md" 0644 nftables_interface_placeholder_map
  stage_target_helper_doc nft-policy-generate.md nft-policy-generate.md
  stage_target_nftables_profile_assets
  render_target_asset_with_placeholder_map \
    "$(installer_repo_join_var DIR_HOOKS_TARGET "etc/nftables/profiles/${selected_profile}.yml")" \
    "/etc/nftables/profiles/default.yml" \
    0644 \
    nftables_interface_placeholder_map
  stage_target_nftables_all_service_assets
  write_target_nftables_default_config "$selected_profile" "${requested_profile:-default}" "$selected_services" "$runtime_cidrs"
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/nftables/firewall-security.rules)" \
    /etc/nftables/firewall-security.rules \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/nftables.d/95-firewall-security.nft)" \
    /etc/nftables.d/95-firewall-security.nft \
    0644

  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/system/nftables.service.d/override.conf)" \
    "/etc/systemd/system/nftables.service.d/override.conf" \
    0644

  require_in_target "nftables policy generation"
  set -- env "NFTABLES_LOG_LEVEL=${NFTABLES_LOG_LEVEL:-none}" /usr/local/sbin/nft-policy-generate \
    --profile "/etc/nftables/profiles/${selected_profile}.yml"
  for service_asset in $selected_services; do
    set -- "$@" --overlay "/etc/nftables/services/${service_asset}.yml"
  done
  for runtime_pair in $runtime_cidrs; do
    set -- "$@" --add-cidr "$runtime_pair"
  done
  set -- "$@" --write --summary
  run_in_target "generate ${requested_profile} nftables policy (${selected_profile} profile)" "$@"

  stage_target_systemd_unit_enabled nftables.service system

  [ -x /target/usr/local/sbin/nft-policy-generate ] || installer_fatal "staged nftables generator is missing"
  [ -r /target/etc/nftables.conf ] || installer_fatal "staged nftables entrypoint is missing"
  for fragment in 00-defines.nft 10-base.nft 20-filter.nft 30-nat.nft 90-local.nft; do
    [ -r "/target/etc/nftables.d/${fragment}" ] ||
      installer_fatal "staged nftables fragment is missing: ${fragment}"
  done
  [ -r /target/etc/nftables/firewall-security.rules ] ||
    installer_fatal "staged firewall security state is missing"
  [ -r /target/etc/nftables.d/95-firewall-security.nft ] ||
    installer_fatal "staged firewall security fragment is missing"
  grep -Fq 'include "/etc/nftables.d/95-firewall-security.nft"' \
    /target/etc/nftables.d/90-local.nft ||
    installer_fatal "generated local nftables fragment does not include Firewall Security rules"
  [ -r "/target/etc/systemd/system/nftables.service.d/override.conf" ] ||
    installer_fatal "staged nftables systemd override is missing"
  [ -r "/target/etc/nftables/profiles/${selected_profile}.yml" ] ||
    installer_fatal "staged nftables default profile is missing"
  for profile_asset in baseline desktop; do
    [ -r "/target/etc/nftables/profiles/${profile_asset}.yml" ] ||
      installer_fatal "staged nftables profile is missing: ${profile_asset}"
  done
  for service_asset in $(nftables_service_assets); do
    [ -r "/target/etc/nftables/services/${service_asset}.yml" ] ||
      installer_fatal "staged nftables service overlay is missing: ${service_asset}"
  done
  for service_asset in $selected_services; do
    [ -r "/target/etc/nftables/services/${service_asset}.yml" ] ||
      installer_fatal "selected nftables service overlay is missing: ${service_asset}"
  done
}

security_mask_target_systemd_unit_if_available() {
  unit=$1
  scope=${2:-system}

  validate_systemd_unit_name "$unit"
  base_dir=$(target_systemd_scope_base_dir "$scope")
  mask_path="/target${base_dir}/${unit}"

  if [ -L "$mask_path" ] && [ "$(readlink "$mask_path")" = /dev/null ]; then
    return 0
  fi

  unit_path=$(target_systemd_unit_path "$unit" "$scope" 2>/dev/null || true)
  if [ -z "$unit_path" ]; then
    installer_warn "target ${scope} unit is unavailable; skipping security mask: ${unit}"
    return 0
  fi

  unstage_target_systemd_unit_enabled "$unit" "$scope"
  install -d -m 0755 "/target${base_dir}"
  ln -sfn /dev/null "$mask_path"
  [ -L "$mask_path" ] &&
    [ "$(readlink "$mask_path")" = /dev/null ] ||
    installer_fatal "failed to mask target ${scope} unit: ${unit}"
}

configure_target_fail2ban() {
  fail2ban_jail_count=0

  install -d -m 0755 \
    /target/etc/fail2ban \
    /target/etc/fail2ban/jail.d \
    /target/etc/fail2ban/jail.d/managed \
    /target/etc/logrotate.d \
    /target/etc/systemd/system/fail2ban.service.d \
    /target/etc/tmpfiles.d

  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/fail2ban/fail2ban.local)" \
    /etc/fail2ban/fail2ban.local \
    0644
  # Only installer-owned remote authentication or abuse logs receive jails.
  # Tailscale uses tailnet identity controls, and Syncthing's GUI is loopback-only.
  if [ "${SSH_SERVER_ENABLED:-false}" = true ]; then
    render_target_asset_with_placeholder_map \
      "$(installer_repo_join_var DIR_HOOKS_TARGET etc/fail2ban/jail.d/managed/10-sshd.local.tmpl)" \
      /etc/fail2ban/jail.d/managed/10-sshd.local \
      0644 \
      fail2ban_jail_placeholder_map
    fail2ban_jail_count=$((fail2ban_jail_count + 1))
  fi
  if installer_selected_class_reference_is_selected service/web 2>/dev/null; then
    stage_target_asset \
      "$(installer_repo_join_var DIR_HOOKS_TARGET etc/fail2ban/jail.d/managed/20-nginx-botsearch.local)" \
      /etc/fail2ban/jail.d/managed/20-nginx-botsearch.local \
      0644
    fail2ban_jail_count=$((fail2ban_jail_count + 1))
  fi
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/system/fail2ban.service.d/managed.conf)" \
    /etc/systemd/system/fail2ban.service.d/managed.conf \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/tmpfiles.d/62-fail2ban-managed.conf)" \
    /etc/tmpfiles.d/62-fail2ban-managed.conf \
    0644
  normalize_target_tmpfiles_directory_policy \
    /etc/tmpfiles.d/62-fail2ban-managed.conf \
    "Fail2ban managed state"
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/logrotate.d/fail2ban-managed)" \
    /etc/logrotate.d/fail2ban-managed \
    0644

  run_in_target \
    "create Fail2ban managed state" \
    /usr/bin/systemd-tmpfiles \
    --create \
    /etc/tmpfiles.d/62-fail2ban-managed.conf
  run_in_target \
    "validate Fail2ban configuration" \
    /usr/bin/fail2ban-client \
    -t
  run_in_target \
    "validate Fail2ban log rotation" \
    /usr/sbin/logrotate \
    --debug \
    /etc/logrotate.d/fail2ban-managed

  if [ "$fail2ban_jail_count" -gt 0 ]; then
    stage_target_systemd_unit_enabled fail2ban.service system
  else
    unstage_target_systemd_unit_enabled fail2ban.service system
  fi
}

configure_target_apparmor_auditd() {
  security_class=$(late_command_security_class)

  case "$security_class" in
    standard|enhanced) ;;
    *) installer_fatal "unsupported security class for AppArmor/auditd configuration: ${security_class:-unset}" ;;
  esac

  install -d -m 0755 \
    /target/etc/apparmor \
    /target/etc/apparmor.d \
    /target/etc/apparmor.d/abstractions \
    /target/etc/apparmor.d/local \
    /target/etc/audit \
    /target/etc/audit/rules.d \
    /target/etc/audit/plugins.d \
    /target/etc/logrotate.d \
    /target/etc/rsyslog.d \
    /target/etc/systemd/system/logrotate.timer.d \
    /target/etc/tmpfiles.d \
    /target/etc/ssh \
    /target/usr/local/bin \
    /target/usr/local/sbin
  install -d -m 0700 /target/etc/security
  [ -e /target/etc/security/opasswd ] || : > /target/etc/security/opasswd
  chmod 0600 /target/etc/security/opasswd
  # Debian's auditd package ships this base rule with "-b 8192". Remove it
  # before staging the managed profile so the boot audit_backlog_limit remains
  # authoritative when augenrules concatenates /etc/audit/rules.d/*.rules.
  rm -f \
    /target/etc/audit/rules.d/audit.rules \
    /target/etc/audit/rules.d/10-security-standard.rules \
    /target/etc/audit/rules.d/10-security-enhanced.rules \
    /target/etc/audit/rules.d/zz-security-standard.rules \
    /target/etc/audit/rules.d/zz-security-enhanced.rules

  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/tmpfiles.d/75-auditd-storage.conf)" "/etc/tmpfiles.d/75-auditd-storage.conf" 0644
  normalize_target_tmpfiles_directory_policy "/etc/tmpfiles.d/75-auditd-storage.conf" "auditd storage"
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/tmpfiles.d/65-audit-syslog.conf)" "/etc/tmpfiles.d/65-audit-syslog.conf" 0644
  normalize_target_tmpfiles_directory_policy "/etc/tmpfiles.d/65-audit-syslog.conf" "audit syslog storage"
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/apparmor/parser.conf)" "/etc/apparmor/parser.conf" 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/apparmor/easyprof.conf)" "/etc/apparmor/easyprof.conf" 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/apparmor/logprof.conf)" "/etc/apparmor/logprof.conf" 0644
  stage_target_system_apparmor_profiles
  if security_target_is_desktop; then
    install -d -m 0755 \
      /target/usr/local/lib/perl5/site_perl/apparmor-managed-modes/AppArmor/ManagedModes
    stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/apparmor/managed-modes.conf.tmpl)" "/etc/apparmor/managed-modes.conf" 0644
    apparmor_apply_desktop_state /target/etc/apparmor/managed-modes.conf
    stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/libexec/apparmor-managed-modes-run)" "/usr/local/libexec/apparmor-managed-modes-run" 0755
    apparmor_managed_modes_perl_modules | while IFS= read -r apparmor_managed_modes_module; do
      [ -n "$apparmor_managed_modes_module" ] || continue
      stage_target_asset \
        "$(installer_repo_join_var DIR_HOOKS_TARGET "usr/local/lib/perl5/site_perl/apparmor-managed-modes/${apparmor_managed_modes_module}")" \
        "/usr/local/lib/perl5/site_perl/apparmor-managed-modes/${apparmor_managed_modes_module}" \
        0644
    done
    stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/system/apparmor-managed-modes.service)" "/etc/systemd/system/apparmor-managed-modes.service" 0644
    stage_target_desktop_apparmor_profiles
    run_in_target \
      "apply managed AppArmor profile modes without touching the installer kernel" \
      /usr/local/libexec/apparmor-managed-modes-run \
      --no-reload
    stage_target_systemd_unit_enabled apparmor-managed-modes.service system
  fi
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET "etc/audit/${security_class}/auditd.conf")" "/etc/audit/auditd.conf" 0640
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET "etc/audit/${security_class}/rules.d/10-security-${security_class}.rules")" "/etc/audit/rules.d/zz-security-${security_class}.rules" 0640
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/audit/plugins.d/af_unix.conf)" "/etc/audit/plugins.d/af_unix.conf" 0640
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/audit/plugins.d/syslog.conf)" "/etc/audit/plugins.d/syslog.conf" 0640
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/rsyslog.d/15-audit.conf)" "/etc/rsyslog.d/15-audit.conf" 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/rsyslog.d/99-discard.conf)" "/etc/rsyslog.d/99-discard.conf" 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/logrotate.conf)" "/etc/logrotate.conf" 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/logrotate.d/audit)" "/etc/logrotate.d/audit" 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/system/logrotate.timer.d/override.conf)" "/etc/systemd/system/logrotate.timer.d/override.conf" 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/libexec/augenrules-quiet)" "/usr/local/libexec/augenrules-quiet" 0755
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/system/audit-rules.service.d/override.conf)" "/etc/systemd/system/audit-rules.service.d/override.conf" 0644

  stage_target_systemd_unit_enabled apparmor.service system
  security_mask_target_systemd_unit_if_available systemd-journald-audit.socket system
  stage_target_systemd_unit_enabled auditd.service system
  stage_target_systemd_unit_enabled rsyslog.service system
  stage_target_systemd_unit_enabled logrotate.timer system
  configure_target_nftables
  configure_target_fail2ban
}
