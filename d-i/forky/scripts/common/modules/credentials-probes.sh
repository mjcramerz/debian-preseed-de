#!/bin/sh
# Sourced installer module; edit this file directly.

installer_cmdline() {
  if [ -n "${INSTALLER_CMDLINE:-}" ]; then
    printf '%s\n' "$INSTALLER_CMDLINE"
    return 0
  fi
  if [ "${INSTALLER_CMDLINE_CACHE_READY:-0}" -eq 1 ]; then
    printf '%s\n' "$INSTALLER_CMDLINE_CACHE"
    return 0
  fi
  if [ -n "${INSTALLER_CMDLINE_FILE:-}" ] && [ -r "$INSTALLER_CMDLINE_FILE" ]; then
    INSTALLER_CMDLINE_CACHE=$(cat "$INSTALLER_CMDLINE_FILE")
    INSTALLER_CMDLINE_CACHE_READY=1
    printf '%s\n' "$INSTALLER_CMDLINE_CACHE"
    return 0
  fi
  if [ -r /proc/cmdline ]; then
    INSTALLER_CMDLINE_CACHE=$(cat /proc/cmdline)
    INSTALLER_CMDLINE_CACHE_READY=1
    printf '%s\n' "$INSTALLER_CMDLINE_CACHE"
    return 0
  fi
  INSTALLER_CMDLINE_CACHE=
  INSTALLER_CMDLINE_CACHE_READY=1
  printf '\n'
}

installer_cmdline_parameter_present() (
  set -f
  IFS=' 	
'
  installer_cmdline_presence_key=$1

  for installer_cmdline_presence_arg in $(installer_cmdline); do
    case "$installer_cmdline_presence_arg" in
      "$installer_cmdline_presence_key"|"$installer_cmdline_presence_key"=*)
        return 0
        ;;
    esac
  done
  return 1
)

installer_cmdline_fallback_blocked() {
  case "${1:-}" in
    netcfg/wireless_wpa|wireless_wpa|wifi_wpa)
      set -- netcfg/wireless_wpa wireless_wpa wifi_wpa
      ;;
    crowdsec_token|crowdsec_enroll_token|crowdsec_attachment_key)
      set -- crowdsec_token crowdsec_enroll_token crowdsec_attachment_key
      ;;
    tailscale_authkey|tailscale_auth_key)
      set -- tailscale_authkey tailscale_auth_key
      ;;
    *)
      set -- "${1:-}"
      ;;
  esac

  for installer_cmdline_fallback_key in "$@"; do
    [ -n "$installer_cmdline_fallback_key" ] || continue
    if installer_cmdline_parameter_present "$installer_cmdline_fallback_key"; then
      return 0
    fi
  done
  return 1
}


installer_preseed_env_value() (
  preseed_env_read_value "$@"
)

installer_cmdline_value() (
  set +x
  set +v
  # The first exact parameter wins, including an explicitly empty parameter.
  # Passwords are literal data, not pathname patterns or shell expressions.
  set -f
  IFS=' 	
'
  installer_cmdline_key=$1
  for installer_cmdline_arg in $(installer_cmdline); do
    case "$installer_cmdline_arg" in
      "$installer_cmdline_key")
        printf '\n'
        return 0
        ;;
      "$installer_cmdline_key"=*)
        printf '%s\n' "${installer_cmdline_arg#*=}"
        return 0
        ;;
    esac
  done

  installer_cmdline_fallback_blocked "$installer_cmdline_key" && return 1
  installer_preseed_env_value "$installer_cmdline_key"
)

installer_cmdline_seed_reference_pair() {
  if [ "${INSTALLER_CMDLINE_SEED_PAIR_READY:-0}" -eq 1 ]; then
    return 0
  fi

  INSTALLER_CMDLINE_SEED_URL_BASE=
  INSTALLER_CMDLINE_SEED_FILE_BASE=

  for arg in $(installer_cmdline); do
    case "$arg" in
      preseed/url=*|url=*)
        [ -n "$INSTALLER_CMDLINE_SEED_URL_BASE" ] || INSTALLER_CMDLINE_SEED_URL_BASE=${arg#*=}
        ;;
      preseed/file=*|file=*)
        [ -n "$INSTALLER_CMDLINE_SEED_FILE_BASE" ] || INSTALLER_CMDLINE_SEED_FILE_BASE=${arg#*=}
        ;;
    esac
  done
  INSTALLER_CMDLINE_SEED_PAIR_READY=1
}

installer_cmdline_seed_base() {
  installer_cmdline_seed_reference_pair
  if installer_choose_seed_base_from_pair \
    "${INSTALLER_CMDLINE_SEED_URL_BASE:-}" \
    "${INSTALLER_CMDLINE_SEED_FILE_BASE:-}" \
    "kernel cmdline"
  then
    printf '%s\n' "$INSTALLER_RESOLVED_SEED_BASE"
    return 0
  fi
  return 1
}

installer_debconf_value() {
  question=$1
  value=

  if [ -n "${DEBIAN_HAS_FRONTEND:-}" ]; then
    installer_debconf_request GET "$question"
    return "$?"
  fi

  if command -v debconf-get >/dev/null 2>&1; then
    value=$(debconf-get "$question" 2>/dev/null || true)
    case "$value" in
      "$question":\ *) value=${value#"$question": } ;;
      "$question":*) value=${value#"$question":} ;;
    esac
    value=$(printf '%s\n' "$value" | sed -n '1{s/\r$//;p;q;}')
    [ -n "$value" ] || return 1
    printf '%s\n' "$value"
    return 0
  fi

  if command -v debconf-communicate >/dev/null 2>&1; then
    response=$(printf 'GET %s\n' "$question" | debconf-communicate 2>/dev/null || true)
    case "$response" in
      0\ *) value=${response#0 } ;;
      *) value= ;;
    esac
    [ -n "$value" ] || return 1
    printf '%s\n' "$value"
    return 0
  fi

  return 1
}

installer_seed_debconf_value() {
  # Offline context rendering can run without a debconf installation. Inside
  # d-i, publishing the chosen classes is mandatory and errors must propagate.
  if [ -z "${DEBIAN_HAS_FRONTEND:-}" ] &&
     ! command -v debconf-set-selections >/dev/null 2>&1; then
    return 0
  fi
  installer_debconf_seed_value "$@" || {
    installer_debconf_status=$?
    installer_error "failed to seed debconf question $2 (status $installer_debconf_status)"
    return "$installer_debconf_status"
  }
}

installer_bool_is_true() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
  esac
  return 1
}

installer_bool_is_false() {
  case "${1:-}" in
    0|false|FALSE|no|NO|off|OFF) return 0 ;;
  esac
  return 1
}

installer_read_first_line() {
  [ -r "$1" ] || return 1
  IFS= read -r installer_line_value <"$1" || return 1
  printf '%s' "$installer_line_value"
}

installer_pci_has_display_vendor() {
  wanted_vendor=$1
  pci_devices_root=${INSTALLER_PCI_DEVICES_ROOT:-/sys/bus/pci/devices}

  case "$wanted_vendor" in
    0x[0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f]) ;;
    *) installer_fatal "PCI vendor id must be a four-digit hex value with 0x prefix: ${wanted_vendor:-unset}" ;;
  esac

  for dev_path in "$pci_devices_root"/*; do
    [ -d "$dev_path" ] || continue
    [ -r "$dev_path/vendor" ] || continue
    [ -r "$dev_path/class" ] || continue

    dev_vendor=$(installer_read_first_line "$dev_path/vendor" 2>/dev/null || true)
    dev_class=$(installer_read_first_line "$dev_path/class" 2>/dev/null || true)
    [ -n "$dev_vendor" ] || continue
    [ -n "$dev_class" ] || continue
    case "$dev_class" in
      0x03*)
        [ "$dev_vendor" = "$wanted_vendor" ] && return 0
        ;;
    esac
  done

  return 1
}

installer_nvidia_gpu_detected() {
  installer_pci_has_display_vendor 0x10de
}

installer_nvidia_addon_selected() {
  installer_selected_class_reference_is_selected addon/nvidia 2>/dev/null && return 0
  installer_selected_class_reference_is_selected addon/nvidia-legacy 2>/dev/null && return 0
  return 1
}

installer_nvidia_legacy_selected() {
  installer_selected_class_reference_is_selected addon/nvidia-legacy 2>/dev/null
}

installer_cuda_legacy_selected() {
  installer_selected_class_reference_is_selected addon/cuda-legacy 2>/dev/null
}

