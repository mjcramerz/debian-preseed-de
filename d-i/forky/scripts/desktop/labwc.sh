#!/bin/sh
# Desktop role orchestrator. This file is sourced from scripts/late/desktop.sh.

desktop_log() {
  installer_append_log_category desktop target_customization info desktop "$*" || true
  installer_append_log_category late target_customization info desktop "$*" || true
}

desktop_log_policy_context() {
  desktop_log "policy default_target=${LABWC_DESKTOP_DEFAULT_TARGET:-graphical.target} session=${LABWC_DESKTOP_SESSION_NAME:-Labwc} workspaces=${LABWC_WORKSPACE_COUNT:-4}"
  desktop_log "policy outputs=${LABWC_OUTPUT_POLICY:-auto} detected=${LABWC_DETECTED_OUTPUTS:-none} internal=${LABWC_DETECTED_INTERNAL_OUTPUTS:-none} external=${LABWC_DETECTED_EXTERNAL_OUTPUTS:-none} primary=${LABWC_DETECTED_PRIMARY_OUTPUT:-none}"
  desktop_log "policy acceleration intel=${LABWC_INTEL_ACCELERATION_AVAILABLE:-false} nvidia=${LABWC_NVIDIA_ACCELERATION_AVAILABLE:-false}"
  desktop_log "policy enables waybar=${LABWC_ENABLE_WAYBAR:-true} kanshi=${LABWC_ENABLE_KANSHI:-true} mako=${LABWC_ENABLE_MAKO:-true} swayidle=${LABWC_ENABLE_SWAYIDLE:-true} swaybg=${LABWC_ENABLE_SWAYBG:-true} polkit=${LABWC_ENABLE_POLKIT_AGENT:-true} portal=${LABWC_ENABLE_XDG_DESKTOP_PORTAL:-true}"
  desktop_log "policy commands launcher=${LABWC_LAUNCHER_COMMAND:-labwc-fuzzel launcher} menu=${LABWC_MENU_COMMAND:-labwc-fuzzel launcher} file_manager=${LABWC_FILE_MANAGER_COMMAND:-thunar} terminal=${LABWC_TERMINAL_PRIMARY:-foot}/${LABWC_TERMINAL_FALLBACK:-kitty} brightness=${LABWC_BRIGHTNESS_CONTROL_COMMAND:-labwc-brightness-control} power=${LABWC_POWER_SETTINGS_COMMAND:-labwc-power-settings}"
}

desktop_install_codex_standalone() (
  if ! installer_selected_class_reference_is_selected addon/devops 2>/dev/null; then
    return 0
  fi

  : "${ACCOUNT_USERNAME:?ACCOUNT_USERNAME must be set before Codex standalone installation}"
  : "${ACCOUNT_HOME:?ACCOUNT_HOME must be set before Codex standalone installation}"
  : "${DEVOPS_CODEX_ROOT:?DEVOPS_CODEX_ROOT must be set before Codex standalone installation}"
  : "${DEVOPS_CODEX_BINARY_PATH:?DEVOPS_CODEX_BINARY_PATH must be set before Codex standalone installation}"
  : "${DEVOPS_CODEX_USER_ROOT:?DEVOPS_CODEX_USER_ROOT must be set before Codex standalone installation}"
  : "${DEVOPS_CODEX_HOME:?DEVOPS_CODEX_HOME must be set before Codex standalone installation}"
  : "${DEVOPS_CODEX_STANDALONE_INSTALLER_URL:?DEVOPS_CODEX_STANDALONE_INSTALLER_URL must be set before Codex standalone installation}"
  : "${DEVOPS_CODEX_STANDALONE_INSTALLER_MAXIMUM_BYTES:?DEVOPS_CODEX_STANDALONE_INSTALLER_MAXIMUM_BYTES must be set before Codex standalone installation}"

  [ "$DEVOPS_CODEX_ROOT" = /data/codex ] ||
    fatal "Codex root is not approved for standalone installation: $DEVOPS_CODEX_ROOT"
  [ "$DEVOPS_CODEX_HOME" = /data/codex/usr/home ] ||
    fatal "Codex home is not approved for standalone installation: $DEVOPS_CODEX_HOME"

  installer_helper=/usr/local/bin/codex-standalone-install
  session_helper="${DEVOPS_CODEX_ROOT}/.installer-codex-standalone.session.py"
  packages_root="${DEVOPS_CODEX_ROOT}/packages"
  installer_host_path=$(target_asset_host_path "$installer_helper")
  session_host_path=$(target_asset_host_path "$session_helper")
  account_home_host_path=$(target_asset_host_path "$ACCOUNT_HOME")
  profile_host_path=$(target_asset_host_path "${ACCOUNT_HOME}/.profile.d/71-devops-de.sh")
  codex_binary_host_path=$(target_asset_host_path "$DEVOPS_CODEX_BINARY_PATH")
  codex_home_host_path=$(target_asset_host_path "$DEVOPS_CODEX_HOME")
  codex_repository_host_path=$(target_asset_host_path "${DEVOPS_CODEX_USER_ROOT}/.git")

  [ -d "$account_home_host_path" ] && [ ! -L "$account_home_host_path" ] ||
    fatal "desktop account home is missing or unsafe before Codex standalone installation: $ACCOUNT_HOME"
  [ -f "$profile_host_path" ] && [ ! -L "$profile_host_path" ] ||
    fatal "managed DevOps profile is missing or unsafe before Codex standalone installation"
  [ -f "$codex_binary_host_path" ] && [ ! -L "$codex_binary_host_path" ] &&
    [ -x "$codex_binary_host_path" ] ||
    fatal "pinned Codex binary is missing or unsafe before standalone installation"
  [ -d "$codex_home_host_path" ] && [ ! -L "$codex_home_host_path" ] ||
    fatal "Codex home is missing or unsafe before standalone installation"
  [ -d "$codex_repository_host_path" ] && [ ! -L "$codex_repository_host_path" ] ||
    fatal "cloned Codex-home repository is missing or unsafe before standalone installation"
  [ -f "$installer_host_path" ] && [ ! -L "$installer_host_path" ] &&
    [ -x "$installer_host_path" ] ||
    fatal "target Codex standalone installer is missing or unsafe: $installer_helper"
  [ "$(chroot "${INSTALLER_TARGET_DIR:-/target}" /usr/bin/stat -c '%u:%g:%a' -- "$installer_helper")" = 0:0:755 ] ||
    fatal "target Codex standalone installer ownership or mode is invalid: $installer_helper"
  [ -f "$session_host_path" ] && [ ! -L "$session_host_path" ] &&
    [ -x "$session_host_path" ] ||
    fatal "temporary Codex installer supervisor is missing or unsafe: $session_helper"
  [ "$(chroot "${INSTALLER_TARGET_DIR:-/target}" /usr/bin/stat -c '%u:%g:%a' -- "$session_helper")" = 0:0:700 ] ||
    fatal "temporary Codex installer supervisor ownership or mode is invalid: $session_helper"

  cleanup_codex_installer_supervisor() {
    cleanup_status=$?
    trap - EXIT HUP INT TERM
    if [ -f "$session_host_path" ] && [ ! -L "$session_host_path" ]; then
      rm -f -- "$session_host_path" || cleanup_status=1
    elif [ -e "$session_host_path" ] || [ -L "$session_host_path" ]; then
      printf 'fatal: staged Codex installer supervisor became unsafe: %s\n' "$session_helper" >&2
      cleanup_status=1
    fi
    exit "$cleanup_status"
  }
  trap cleanup_codex_installer_supervisor EXIT
  trap 'exit 129' HUP
  trap 'exit 130' INT
  trap 'exit 143' TERM

  # d-i may bind its /run over /target/run while entering in-target. Allocate
  # and dispose of the private runtime inside that namespace, in the same
  # invocation as the unprivileged installer. Never fabricate a logind session.
  run_in_target \
    "install the official Codex standalone package after desktop account configuration" \
    /usr/bin/python3 "$session_helper" \
      "$ACCOUNT_USERNAME" "$ACCOUNT_HOME" \
      "$installer_helper" \
      "$DEVOPS_CODEX_STANDALONE_INSTALLER_URL" \
      "$DEVOPS_CODEX_STANDALONE_INSTALLER_MAXIMUM_BYTES" \
      "$DEVOPS_CODEX_HOME" "$packages_root"

  packages_host_path=$(target_asset_host_path "$packages_root")
  home_packages_host_path=$(target_asset_host_path "${DEVOPS_CODEX_HOME}/packages")
  [ -d "$packages_host_path" ] && [ ! -L "$packages_host_path" ] ||
    fatal "official Codex standalone package root is missing after installation"
  [ -L "$home_packages_host_path" ] &&
    [ "$(readlink -- "$home_packages_host_path")" = "$packages_root" ] ||
    fatal "CODEX_HOME package link does not target the managed standalone package root"
  [ -f "$installer_host_path" ] && [ ! -L "$installer_host_path" ] &&
    [ -x "$installer_host_path" ] ||
    fatal "target Codex standalone installer was not retained after installation"
  desktop_log "installed off-PATH official Codex standalone package for app-server daemon discovery"
)

run_desktop_late_command() {
  requested_seed_base=${1:-}
  requested_host_profile=${2:-}

  [ "${INSTALLER_HOST_VARIANT:-}" = desktop ] || {
    installer_info "desktop late command skipped for host variant: ${INSTALLER_HOST_VARIANT:-unset}"
    return 0
  }

  desktop_log "loaded desktop env host_profile=${requested_host_profile:-$HOST_PROFILE} account_user=${ACCOUNT_USERNAME:-unset} account_home=${ACCOUNT_HOME:-unset}"
  desktop_policy_enabled || {
    installer_info "Labwc desktop policy disabled by LABWC_DESKTOP_ENABLE"
    desktop_log "skipped Labwc desktop role because LABWC_DESKTOP_ENABLE=${LABWC_DESKTOP_ENABLE:-unset}"
    return 0
  }
  desktop_resolve_acceleration_availability
  desktop_resolve_managed_app_default_exec
  desktop_validate_managed_app_default_exec \
    LABWC_MANAGED_APP_DEFAULT_EXEC \
    "${LABWC_MANAGED_APP_DEFAULT_EXEC:?LABWC_MANAGED_APP_DEFAULT_EXEC must be set by the desktop host profile}"

  installer_info "installing Labwc desktop role very late for host profile ${requested_host_profile:-$HOST_PROFILE}"
  desktop_log "start Labwc desktop role host_profile=${requested_host_profile:-$HOST_PROFILE}"
  desktop_preflight_required_cmdline_tokens
  desktop_xwayland_preflight_target_architecture
  desktop_log "validated private Xwayland target architecture=${XWAYLAND_TARGET_ARCHITECTURE}"
  desktop_satty_preflight_target_architecture
  desktop_log "validated Satty target architecture=${SATTY_TARGET_ARCHITECTURE}"
  desktop_android_platform_tools_preflight_target_architecture
  desktop_log "validated Android SDK Platform-Tools target architecture=${ANDROID_PLATFORM_TOOLS_TARGET_ARCHITECTURE}"
  desktop_samloader_preflight_target_architecture
  desktop_log "validated samloader-rs target architecture=${SAMLOADER_TARGET_ARCHITECTURE}"
  desktop_digital_assets_preflight_target_architecture
  desktop_log "validated Digital Assets tool target architecture=${DIGITAL_ASSETS_TARGET_ARCHITECTURE}"
  desktop_detect_connected_drm_outputs
  desktop_log "detected_outputs=${LABWC_DETECTED_OUTPUTS:-none} primary=${LABWC_DETECTED_PRIMARY_OUTPUT:-none}"
  desktop_resolve_greeter_user
  desktop_log "resolved_greeter_user=${LABWC_GREETER_USER}"
  desktop_configure_greeter_access
  desktop_configure_usb_media_access
  desktop_configure_android_debug_bridge_access
  desktop_configure_fido2_security_key_access
  desktop_configure_packet_capture_access
  desktop_log_policy_context
  desktop_install_xwayland
  desktop_log "installed pinned private Xwayland compatibility runtime"
  desktop_install_satty
  desktop_log "installed pinned Satty screenshot annotation tool"
  desktop_install_android_platform_tools
  desktop_log "installed latest Google Android SDK Platform-Tools"
  desktop_install_samloader
  desktop_log "installed pinned samloader-rs Samsung firmware tool"
  desktop_install_digital_assets
  desktop_log "installed pinned Digital Assets PDF, document, and image tools"
  desktop_stage_target_assets
  desktop_log "staged Labwc desktop target assets"
  desktop_render_greetd_config
  desktop_render_labwc_default_config
  desktop_write_labwc_plans_config
  desktop_install_user_resource_policy
  desktop_log "rendered Labwc desktop defaults and greetd config"
  desktop_install_user_config
  desktop_install_waypaper
  desktop_log "installed pinned Waypaper application for ${ACCOUNT_USERNAME}"
  desktop_enable_target_services
  desktop_log "staged Labwc desktop service enablement"
  desktop_install_codex_standalone
  desktop_log "skipped Labwc desktop target staging verification during installer late-command"
  installer_info "Labwc desktop role installation completed for seed ${requested_seed_base:-$SEED_BASE}"
}
