#!/bin/sh
# Shared storage runtime module.

runtime_addon_class_selected() {
  runtime_addon_name=$1

  if [ -n "${INSTALLER_SELECTED_CLASS_REFS:-}" ]; then
    runtime_class_list_has_addon "$runtime_addon_name" "$INSTALLER_SELECTED_CLASS_REFS"
    return $?
  fi

  if command -v installer_selected_class_reference_is_selected >/dev/null 2>&1 &&
    installer_selected_class_reference_is_selected "addon/$runtime_addon_name"
  then
    return 0
  fi

  runtime_classes_raw=$(runtime_cmdline_value classes 2>/dev/null || true)
  if [ -z "$runtime_classes_raw" ]; then
    runtime_classes_raw=$(runtime_cmdline_value auto-install/classes 2>/dev/null || true)
  fi
  runtime_class_list_has_addon "$runtime_addon_name" "$runtime_classes_raw"
}

runtime_dualboot_class_selected() {
  runtime_addon_class_selected dualboot
}

runtime_qemu_class_selected() {
  runtime_addon_class_selected qemu
}

runtime_crypto_class_selected() {
  runtime_addon_class_selected crypto
}

runtime_root_home_crypto_enabled() {
  runtime_crypto_class_selected
}

runtime_validate_root_home_crypto_layout() {
  runtime_root_home_crypto_enabled || return 0

  [ -n "${DEV_PART_ROOT:-}" ] || runtime_fatal "addon/crypto requires a dedicated root partition"
  [ -n "${DEV_PART_HOME:-}" ] || runtime_fatal "addon/crypto requires a dedicated /home partition"
  case "${DEV_PART_HOME_MB:-}" in
    ''|*[!0-9]*|0)
      runtime_fatal "addon/crypto requires a non-zero dedicated /home partition"
      ;;
  esac
}

runtime_bool_is_true() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
  esac
  return 1
}

runtime_bool_is_false() {
  case "${1:-}" in
    0|false|FALSE|no|NO|off|OFF) return 0 ;;
  esac
  return 1
}

runtime_apply_ssh_from_classes() {
  if ! command -v installer_selected_class_refs >/dev/null 2>&1 ||
    ! command -v installer_selected_class_reference_is_selected >/dev/null 2>&1; then
    runtime_fatal "installer class selection helpers are unavailable for SSH server provisioning"
  fi
  installer_selected_class_refs >/dev/null 2>&1 ||
    runtime_fatal "selected installer classes are unavailable for SSH server provisioning"

  if installer_selected_class_reference_is_selected addon/ssh; then
    SSH_SERVER_ENABLED=true
    runtime_apply_ssh_from_cmdline
  else
    SSH_SERVER_ENABLED=false
  fi
}

runtime_apply_ssh_from_cmdline() {
  [ "${RUNTIME_SSH_CMDLINE_READY:-0}" = 1 ] && return 0

  ssh_port_default=${SSH_PORT_DEFAULT:-}
  ssh_port_raw=$(runtime_cmdline_value ssh_port 2>/dev/null || true)
  if [ -z "$ssh_port_raw" ]; then
    ssh_port_raw=$ssh_port_default
  fi
  runtime_require_positive_integer ssh_port "$ssh_port_raw"
  [ "$ssh_port_raw" -le 65535 ] || runtime_fatal "ssh_port must be 65535 or lower"
  SSH_PORT=$ssh_port_raw
  RUNTIME_SSH_CMDLINE_READY=1
}

