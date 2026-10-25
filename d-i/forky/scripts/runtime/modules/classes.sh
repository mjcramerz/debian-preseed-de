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

  case "${SSH_SERVER_ENABLE:-}" in
    true|false) ;;
    *) runtime_fatal 'SSH_SERVER_ENABLE must be true or false in the host profile' ;;
  esac
  if [ -n "${INSTALLER_PROFILE_SSH_SERVER_ENABLE:-}" ] &&
     [ "$SSH_SERVER_ENABLE" != "$INSTALLER_PROFILE_SSH_SERVER_ENABLE" ]; then
    runtime_fatal 'SSH server enablement differs from the selected installer profile policy'
  fi
  if installer_selected_class_reference_is_selected addon/ssh; then
    [ "$SSH_SERVER_ENABLE" = true ] || runtime_fatal 'SSH class conflicts with disabled profile SSH server'
  else
    [ "$SSH_SERVER_ENABLE" = false ] || runtime_fatal 'profile-enabled SSH server is missing its selected addon/ssh class'
  fi
  SSH_SERVER_ENABLED=$SSH_SERVER_ENABLE
  runtime_apply_ssh_from_cmdline
}

runtime_apply_ssh_from_cmdline() {
  ssh_profile_port=${SSH_SERVER_PORT:-}
  case "$ssh_profile_port" in
    [0-9][0-9][0-9][0-9][0-9]) ;;
    *) runtime_fatal 'SSH_SERVER_PORT must be a five-digit profile port' ;;
  esac
  [ "$ssh_profile_port" -ge 30000 ] && [ "$ssh_profile_port" -le 40000 ] ||
    runtime_fatal 'SSH_SERVER_PORT must be in 30000..40000'
  if [ -n "${INSTALLER_PROFILE_SSH_SERVER_PORT:-}" ] &&
     [ "$ssh_profile_port" != "$INSTALLER_PROFILE_SSH_SERVER_PORT" ]; then
    runtime_fatal 'SSH server port differs from the selected installer profile policy'
  fi
  if [ "${RUNTIME_SSH_CMDLINE_READY:-0}" = 1 ]; then
    [ "${SSH_PORT:-}" = "$ssh_profile_port" ] || runtime_fatal 'resolved SSH port no longer matches its profile'
    return 0
  fi
  # Legacy boot arguments may repeat the profile value; they cannot silently
  # override the profile's declared server and firewall port.
  ssh_port_raw=$(runtime_cmdline_value ssh_port 2>/dev/null || true)
  [ -z "$ssh_port_raw" ] || [ "$ssh_port_raw" = "$ssh_profile_port" ] ||
    runtime_fatal 'ssh_port conflicts with SSH_SERVER_PORT in the host profile'
  SSH_PORT=$ssh_profile_port
  RUNTIME_SSH_CMDLINE_READY=1
}
