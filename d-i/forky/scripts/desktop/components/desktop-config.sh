#!/bin/sh
# Sourced installer module; edit this file directly.

desktop_require_absolute_account_home() {
  case "${ACCOUNT_HOME:-}" in
    /*) ;;
    *)
      installer_fatal "ACCOUNT_HOME must be an absolute path for desktop account configuration"
      ;;
  esac
  case "$ACCOUNT_HOME" in
    /|*..*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/-]*)
      installer_fatal "ACCOUNT_HOME contains unsupported path syntax for desktop account configuration: ${ACCOUNT_HOME}"
      ;;
  esac
}

desktop_validate_required_cmdline_token() {
  label=$1
  key=$2
  value=$3
  seen=$4

  if [ "$seen" != true ] || [ -z "$value" ]; then
    installer_fatal "${label} is required on the kernel cmdline (${key}=...) or in /preseed.env"
  fi
  case "$value" in
    *[![:print:]]*|*[[:space:]]*)
      installer_fatal "${label} must be a single printable token without whitespace: ${key}=..."
      ;;
  esac
}

desktop_validate_required_calendar_token() {
  label=$1
  cmdline_key=$2
  fallback_key=$3
  value=$4

  if [ -z "$value" ]; then
    installer_fatal "${label} is required on the kernel cmdline (${cmdline_key}=...), in /preseed.env, or in account.env (${fallback_key})"
  fi
  case "$value" in
    *[![:print:]]*|*[[:space:]]*)
      installer_fatal "${label} must be a single printable token without whitespace: ${cmdline_key}=... or ${fallback_key}"
      ;;
  esac
}

desktop_validate_iface_name() {
  label=$1
  value=$2

  case "$value" in
    ''|.|..|lo)
      desktop_fatal "${label} must be a non-loopback interface name"
      ;;
  esac
  case "$value" in
    *[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-]*)
      desktop_fatal "${label} contains unsupported characters: ${value}"
      ;;
  esac
  [ "${#value}" -le 15 ] || desktop_fatal "${label} must be 15 characters or fewer: ${value}"
}

desktop_target_managed_network_default_value() {
  key=$1
  defaults_path=/target/etc/network/host.conf
  value=

  [ -r "$defaults_path" ] || return 1
  value=$(sed -n "s/^${key}='\\([^']*\\)'$/\\1/p" "$defaults_path" | sed -n '1p')
  [ -n "$value" ] || return 1
  printf '%s\n' "$value"
}

desktop_waybar_modules_left_json() {
  # Stock wlr/taskbar has output filtering, NOT workspace filtering. Never
  # expose a global window list as a supposedly workspace-local taskbar.
  # With one configured workspace its native per-window buttons are safe.
  desktop_validate_uint_range LABWC_WORKSPACE_COUNT "${LABWC_WORKSPACE_COUNT:-4}" 1 12
  printf '"custom/launcher", "ext/workspaces", "custom/tomat", "custom/wayscriber", "custom/window-switcher", "group/apps"'
  if [ "${LABWC_WORKSPACE_COUNT:-4}" -eq 1 ]; then
    printf ', "wlr/taskbar"'
  fi
}

desktop_waybar_modules_right_json() {
  printf '"pulseaudio", "custom/backlight", "custom/battery", "disk", "cpu", "memory", "tray", "group/quick-controls", "custom/notifications", "custom/lock", "custom/power"'
}

desktop_waybar_output_selectors_json() {
  selector_mode=$1
  desktop_validate_internal_output_prefixes || return 1
  selector_prefixes=$LABWC_OUTPUT_INTERNAL_PREFIXES
  selector_index_max=32
  selector_first=true
  selector_seen="|"

  case "$selector_mode" in
    internal|external) ;;
    *) desktop_fatal "unsupported Waybar output selector mode: ${selector_mode:-unset}" ;;
  esac
  [ -n "$selector_prefixes" ] || desktop_fatal "LABWC_OUTPUT_INTERNAL_PREFIXES must not be empty"

  for selector_prefix in $selector_prefixes; do
    case "$selector_prefix" in
      ''|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-]*)
        desktop_fatal "Waybar internal output prefix contains unsupported characters: ${selector_prefix:-unset}"
        ;;
    esac
    [ "${#selector_prefix}" -le 32 ] ||
      desktop_fatal "Waybar internal output prefix is longer than 32 characters: ${selector_prefix}"

    selector_index=1
    while [ "$selector_index" -le "$selector_index_max" ]; do
      for selector_output in "${selector_prefix}-${selector_index}" "${selector_prefix}${selector_index}"; do
        case "$selector_seen" in *"|${selector_output}|"*) continue ;; esac
        selector_seen="${selector_seen}${selector_output}|"
        if [ "$selector_mode" = external ]; then
          selector_output="!${selector_output}"
        fi
        [ "$selector_first" = true ] || printf ', '
        printf '"%s"' "$selector_output"
        selector_first=false
      done
      selector_index=$((selector_index + 1))
    done
  done

  # Native Waybar matches exact connector names, not prefix globs. Include
  # detected/nonstandard internal names and disabled DRM connectors as well.
  selector_known=${LABWC_DETECTED_INTERNAL_OUTPUTS:-}
  for selector_path in /sys/class/drm/card*-*/status; do
    [ -r "$selector_path" ] || continue
    selector_output=${selector_path%/status}
    selector_output=${selector_output##*/}
    selector_output=${selector_output#card*-}
    selector_known="$selector_known $selector_output"
  done
  for selector_output in $selector_known; do
    case "$selector_output" in
      ''|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-]*)
        desktop_fatal "invalid detected Waybar connector name" ;;
    esac
    [ "${#selector_output}" -le 128 ] || desktop_fatal "detected Waybar connector name too long"
    desktop_is_internal_output "$selector_output" || continue
    case "$selector_seen" in *"|${selector_output}|"*) continue ;; esac
    selector_seen="${selector_seen}${selector_output}|"
    [ "$selector_mode" != external ] || selector_output="!${selector_output}"
    [ "$selector_first" = true ] || printf ', '
    printf '"%s"' "$selector_output"
    selector_first=false
  done

  if [ "$selector_mode" = external ]; then
    [ "$selector_first" = true ] || printf ', '
    printf '"*"'
  fi
}

desktop_waybar_internal_outputs_json() {
  desktop_waybar_output_selectors_json internal
}

desktop_waybar_external_outputs_json() {
  desktop_waybar_output_selectors_json external
}

desktop_load_calendar_cmdline_tokens() {
  [ "${DESKTOP_CALENDAR_CMDLINE_TOKENS_READY:-0}" = 1 ] && return 0

  DESKTOP_FRUUX_USERNAME=
  DESKTOP_FRUUX_PASSWORD=
  desktop_fruux_username_seen=false
  desktop_fruux_password_seen=false

  if DESKTOP_FRUUX_USERNAME=$(installer_cmdline_value fruux_username 2>/dev/null); then
    desktop_fruux_username_seen=true
  fi
  if DESKTOP_FRUUX_PASSWORD=$(installer_cmdline_value fruux_password 2>/dev/null); then
    desktop_fruux_password_seen=true
  fi

  if [ "$desktop_fruux_username_seen" != true ] && [ -n "${FRUUX_CALENDAR_USERNAME:-}" ]; then
    DESKTOP_FRUUX_USERNAME=$FRUUX_CALENDAR_USERNAME
  fi
  if [ "$desktop_fruux_password_seen" != true ] && [ -n "${FRUUX_CALENDAR_PASSWORD:-}" ]; then
    DESKTOP_FRUUX_PASSWORD=$FRUUX_CALENDAR_PASSWORD
  fi

  desktop_validate_required_calendar_token "Fruux username" fruux_username FRUUX_CALENDAR_USERNAME "$DESKTOP_FRUUX_USERNAME"
  desktop_validate_required_calendar_token "Fruux password" fruux_password FRUUX_CALENDAR_PASSWORD "$DESKTOP_FRUUX_PASSWORD"
  DESKTOP_CALENDAR_CMDLINE_TOKENS_READY=1
}

desktop_load_plans_cmdline_tokens() {
  [ "${DESKTOP_PLANS_CMDLINE_TOKENS_READY:-0}" = 1 ] && return 0

  DESKTOP_TELEGRAM_API_KEY=$(installer_cmdline_value telegram_api_key 2>/dev/null || true)
  DESKTOP_TELEGRAM_CHAT_ID=$(installer_cmdline_value telegram_chat_id 2>/dev/null || true)

  desktop_validate_required_cmdline_token \
    "Telegram API key" \
    telegram_api_key \
    "$DESKTOP_TELEGRAM_API_KEY" \
    true
  desktop_validate_required_cmdline_token \
    "Telegram chat ID" \
    telegram_chat_id \
    "$DESKTOP_TELEGRAM_CHAT_ID" \
    true

  printf '%s\n' "$DESKTOP_TELEGRAM_API_KEY" |
    grep -Eq '^[0-9]{5,16}:[A-Za-z0-9_-]{20,128}$' ||
    installer_fatal "Telegram API key has an invalid format: telegram_api_key=..."
  printf '%s\n' "$DESKTOP_TELEGRAM_CHAT_ID" |
    grep -Eq '^-?[0-9]{1,20}$' ||
    installer_fatal "Telegram chat ID has an invalid format: telegram_chat_id=..."

  DESKTOP_PLANS_CMDLINE_TOKENS_READY=1
}

desktop_preflight_required_cmdline_tokens() {
  desktop_load_calendar_cmdline_tokens
  desktop_load_plans_cmdline_tokens
  desktop_log "validated_required_installer_tokens fruux_username=set fruux_password=set telegram_api_key=set telegram_chat_id=set"
}

desktop_write_labwc_plans_config() {
  : "${ACCOUNT_USERNAME:?ACCOUNT_USERNAME must be set}"
  : "${ACCOUNT_HOME:?ACCOUNT_HOME must be set}"

  desktop_require_absolute_account_home
  desktop_load_plans_cmdline_tokens
  primary_account_ids=$(desktop_primary_account_ids "$ACCOUNT_USERNAME" || true)
  case "$primary_account_ids" in
    [0-9]*:[0-9]*)
      primary_account_gid=${primary_account_ids#*:}
      ;;
    *)
      installer_fatal "failed to resolve target account group for labwc-plans"
      ;;
  esac

  # The replacement script and rendered temporary file contain Telegram credentials.
  (
    umask 077
    desktop_render_role_target_template \
      etc/labwc/plans.conf.tmpl \
      /etc/labwc/plans.conf \
      0640 \
      LABWC_PLANS_INPUT_DIR "${ACCOUNT_HOME}/Syncthing/sleek" \
      TELEGRAM_API_KEY "$DESKTOP_TELEGRAM_API_KEY" \
      TELEGRAM_CHAT_ID "$DESKTOP_TELEGRAM_CHAT_ID"
  )
  chown "root:${primary_account_gid}" /target/etc/labwc/plans.conf
  chmod 0640 /target/etc/labwc/plans.conf
  desktop_log "rendered_labwc_plans_config credentials=set ntfy=disabled mode=0640"
}

desktop_install_primary_account_calendar_stack() (
  set -eu
  set +x
  set +v
  desktop_require_absolute_account_home
  desktop_load_calendar_cmdline_tokens
  calendar_stage=$(target_private_stage_dir calendar)
  calendar_stage_host=$(target_asset_host_path "$calendar_stage")
  trap 'rm -rf -- "$calendar_stage_host"' 0
  trap 'exit 129' HUP
  trap 'exit 130' INT
  trap 'exit 143' TERM
  stage_target_asset "$(installer_repo_join_var DIR_SCRIPTS_DESKTOP calendar-install.py)" \
    "${calendar_stage}/install.py" 0600
  (umask 077; printf '%s' "$DESKTOP_FRUUX_USERNAME" >"$calendar_stage_host/username")
  (umask 077; printf '%s' "$DESKTOP_FRUUX_PASSWORD" >"$calendar_stage_host/password")
  unset DESKTOP_FRUUX_USERNAME DESKTOP_FRUUX_PASSWORD
  run_in_target "install pinned Waycal, Calix and Agenda with private Fruux bootstrap" \
    /usr/bin/env -i HOME=/root LC_ALL=C.UTF-8 PATH=/usr/sbin:/usr/bin:/sbin:/bin \
    ACCOUNT_USERNAME="$ACCOUNT_USERNAME" ACCOUNT_HOME="$ACCOUNT_HOME" \
    WAYCAL_VERSION="$WAYCAL_VERSION" WAYCAL_URL="$WAYCAL_URL" WAYCAL_COMMIT="$WAYCAL_COMMIT" \
    WAYCAL_SHA256="$WAYCAL_SHA256" WAYCAL_MAXIMUM_BYTES="$WAYCAL_MAXIMUM_BYTES" \
    CALIX_VERSION="$CALIX_VERSION" CALIX_URL="$CALIX_URL" CALIX_COMMIT="$CALIX_COMMIT" \
    CALIX_SHA256="$CALIX_SHA256" CALIX_MAXIMUM_BYTES="$CALIX_MAXIMUM_BYTES" \
    AGENDA_VERSION="$AGENDA_VERSION" AGENDA_URL="$AGENDA_URL" AGENDA_COMMIT="$AGENDA_COMMIT" \
    AGENDA_SHA256="$AGENDA_SHA256" AGENDA_MAXIMUM_BYTES="$AGENDA_MAXIMUM_BYTES" \
    /usr/bin/python3 -I -B "${calendar_stage}/install.py" "$calendar_stage"
)
