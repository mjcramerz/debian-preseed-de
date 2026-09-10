#!/bin/sh
# Labwc desktop installer-side detection and policy rendering helpers.

desktop_fatal() {
  installer_fatal "$@"
}

desktop_policy_enabled() {
  case "${LABWC_DESKTOP_ENABLE:-true}" in
    true|yes|1|on) return 0 ;;
    false|no|0|off) return 1 ;;
    *) desktop_fatal "invalid LABWC_DESKTOP_ENABLE: ${LABWC_DESKTOP_ENABLE}" ;;
  esac
}

desktop_validate_bool() {
  var_name=$1
  var_value=$2

  case "$var_value" in
    true|false|yes|no|1|0|on|off) ;;
    *) desktop_fatal "${var_name} must be boolean-like, got: ${var_value:-unset}" ;;
  esac
}

desktop_validate_apparmor_state() {
  var_name=$1
  var_value=$2

  case "$var_value" in
    enforce|complain) ;;
    *) desktop_fatal "${var_name} must be enforce or complain, got: ${var_value:-unset}" ;;
  esac
}

desktop_validate_uint_range() {
  var_name=$1
  var_value=$2
  min_value=$3
  max_value=$4

  case "$var_value" in
    ''|*[!0-9]*) desktop_fatal "${var_name} must be numeric, got: ${var_value:-unset}" ;;
  esac
  [ "$var_value" -ge "$min_value" ] || desktop_fatal "${var_name} must be >= ${min_value}"
  [ "$var_value" -le "$max_value" ] || desktop_fatal "${var_name} must be <= ${max_value}"
}

desktop_validate_optional_uint_range() {
  var_name=$1
  var_value=$2
  min_value=$3
  max_value=$4

  [ -n "$var_value" ] || return 0
  desktop_validate_uint_range "$var_name" "$var_value" "$min_value" "$max_value"
}

desktop_validate_percent_string() {
  var_name=$1
  var_value=$2
  min_value=$3
  max_value=$4

  case "$var_value" in
    [0-9]*%)
      numeric_value=${var_value%%%}
      ;;
    *)
      desktop_fatal "${var_name} must be an integer percentage like 80%%, got: ${var_value:-unset}"
      ;;
  esac
  case "$numeric_value" in
    ''|*[!0-9]*)
      desktop_fatal "${var_name} must be an integer percentage like 80%%, got: ${var_value:-unset}"
      ;;
  esac
  [ "$numeric_value" -ge "$min_value" ] || desktop_fatal "${var_name} must be >= ${min_value}%"
  [ "$numeric_value" -le "$max_value" ] || desktop_fatal "${var_name} must be <= ${max_value}%"
}

desktop_validate_decimal_range() {
  var_name=$1
  var_value=$2
  min_value=$3
  max_value=$4

  printf '%s\n' "$var_value" | LC_ALL=C grep -Eq '^[0-9]+(\.[0-9]+)?$' || \
    desktop_fatal "${var_name} must be a decimal value, got: ${var_value:-unset}"
  awk "BEGIN { exit !($var_value >= $min_value && $var_value <= $max_value) }" || \
    desktop_fatal "${var_name} must be between ${min_value} and ${max_value}"
}

desktop_validate_output_mode_policy() {
  desktop_validate_output_mode_preference \
    LABWC_OUTPUT_INTERNAL_PREFERRED_WIDTH "${LABWC_OUTPUT_INTERNAL_PREFERRED_WIDTH:-}" \
    LABWC_OUTPUT_INTERNAL_PREFERRED_HEIGHT "${LABWC_OUTPUT_INTERNAL_PREFERRED_HEIGHT:-}" \
    LABWC_OUTPUT_INTERNAL_PREFERRED_REFRESH_HZ "${LABWC_OUTPUT_INTERNAL_PREFERRED_REFRESH_HZ:-}"
  desktop_validate_output_mode_preference \
    LABWC_OUTPUT_EXTERNAL_PREFERRED_WIDTH "${LABWC_OUTPUT_EXTERNAL_PREFERRED_WIDTH:-}" \
    LABWC_OUTPUT_EXTERNAL_PREFERRED_HEIGHT "${LABWC_OUTPUT_EXTERNAL_PREFERRED_HEIGHT:-}" \
    LABWC_OUTPUT_EXTERNAL_PREFERRED_REFRESH_HZ "${LABWC_OUTPUT_EXTERNAL_PREFERRED_REFRESH_HZ:-}"
}

desktop_validate_output_mode_preference() {
  output_width_name=$1
  output_width=$2
  output_height_name=$3
  output_height=$4
  output_refresh_name=$5
  output_refresh=$6

  case "${output_width}:${output_height}" in
    :)
      [ -z "$output_refresh" ] ||
        desktop_fatal "${output_refresh_name} requires ${output_width_name} and ${output_height_name}"
      ;;
    *:)
      desktop_fatal "${output_height_name} is required when ${output_width_name} is set"
      ;;
    :*)
      desktop_fatal "${output_width_name} is required when ${output_height_name} is set"
      ;;
  esac
}

desktop_validate_absolute_path() {
  var_name=$1
  var_value=$2

  case "$var_value" in
    /*) ;;
    *) desktop_fatal "${var_name} must be an absolute path" ;;
  esac
  case "$var_value" in
    *..*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._+@%=:,/-]*)
      desktop_fatal "${var_name} contains unsupported path characters: ${var_value}"
      ;;
  esac
}

desktop_validate_command_string() {
  var_name=$1
  var_value=$2

  [ -n "$var_value" ] || desktop_fatal "${var_name} must not be empty"
  case "$var_value" in
    *'
'*)
      desktop_fatal "${var_name} must be a single-line command"
      ;;
  esac
  case "$var_value" in
    *[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._+@%=:,/\ -]*)
      desktop_fatal "${var_name} contains unsupported command characters: ${var_value}"
      ;;
  esac
}

desktop_validate_managed_app_default_exec() {
  var_name=$1
  var_value=$2

  desktop_validate_command_string "$var_name" "$var_value"
  old_ifs=$IFS
  IFS=' '
  # shellcheck disable=SC2086
  set -- $var_value
  IFS=$old_ifs
  [ "$#" -eq 2 ] ||
    desktop_fatal "${var_name} must contain the managed wrapper path and one mode"
  [ "$var_value" = "$1 $2" ] ||
    desktop_fatal "${var_name} must use one canonical space between the wrapper path and mode"
  [ "$1" = /usr/local/bin/labwc-managed-app ] ||
    desktop_fatal "${var_name} must use /usr/local/bin/labwc-managed-app"
  case "$2" in
    launch|pure-privacy) ;;
    intel)
      [ "${LABWC_INTEL_ACCELERATION_AVAILABLE:-false}" = true ] ||
        desktop_fatal "${var_name} requests Intel acceleration without the intel-uhd GPU class"
      ;;
    nvidia)
      [ "${LABWC_NVIDIA_ACCELERATION_AVAILABLE:-false}" = true ] ||
        desktop_fatal "${var_name} requests NVIDIA acceleration without a selected NVIDIA addon and detected NVIDIA display adapter"
      ;;
    *) desktop_fatal "${var_name} uses an unsupported managed app mode: $2" ;;
  esac
}

desktop_resolve_acceleration_availability() {
  gpu_classes=$(installer_selected_class_for_purpose gpu 2>/dev/null || printf '%s' "${INSTALLER_GPU_CLASS:-}")
  nvidia_addon_selected=false

  LABWC_INTEL_ACCELERATION_AVAILABLE=false
  LABWC_NVIDIA_ACCELERATION_AVAILABLE=false

  for gpu_class in $gpu_classes; do
    case "$gpu_class" in
      intel-uhd)
        LABWC_INTEL_ACCELERATION_AVAILABLE=true
        ;;
      amd-radeon|generic|'')
        ;;
      *)
        desktop_fatal "unsupported GPU class while resolving Labwc acceleration: ${gpu_class}"
        ;;
    esac
  done

  if installer_selected_class_reference_is_selected addon/nvidia ||
     installer_selected_class_reference_is_selected addon/nvidia-legacy; then
    nvidia_addon_selected=true
  fi
  if [ "$nvidia_addon_selected" = true ] && installer_nvidia_gpu_detected; then
    LABWC_NVIDIA_ACCELERATION_AVAILABLE=true
  fi

  desktop_validate_bool \
    LABWC_INTEL_ACCELERATION_AVAILABLE \
    "$LABWC_INTEL_ACCELERATION_AVAILABLE"
  desktop_validate_bool \
    LABWC_NVIDIA_ACCELERATION_AVAILABLE \
    "$LABWC_NVIDIA_ACCELERATION_AVAILABLE"
}

desktop_resolve_managed_app_default_exec() {
  : "${LABWC_MANAGED_APP_DEFAULT_EXEC:?LABWC_MANAGED_APP_DEFAULT_EXEC must be set by the desktop host profile}"

  # Host profiles may prefer NVIDIA for systems that have it, but the installed
  # desktop must never try to use an accelerator that is not both selected and
  # present. Prefer Intel's iHD path when it is selected; otherwise fall back
  # to the neutral launch mode.
  case "$LABWC_MANAGED_APP_DEFAULT_EXEC" in
    "/usr/local/bin/labwc-managed-app nvidia")
      if [ "$LABWC_NVIDIA_ACCELERATION_AVAILABLE" = true ]; then
        return 0
      fi
      if [ "$LABWC_INTEL_ACCELERATION_AVAILABLE" = true ]; then
        LABWC_MANAGED_APP_DEFAULT_EXEC="/usr/local/bin/labwc-managed-app intel"
      else
        LABWC_MANAGED_APP_DEFAULT_EXEC="/usr/local/bin/labwc-managed-app launch"
      fi
      ;;
    "/usr/local/bin/labwc-managed-app intel")
      if [ "$LABWC_INTEL_ACCELERATION_AVAILABLE" != true ]; then
        LABWC_MANAGED_APP_DEFAULT_EXEC="/usr/local/bin/labwc-managed-app launch"
      fi
      ;;
  esac
}

desktop_validate_identifier_list() {
  var_name=$1
  var_value=$2

  case "$var_value" in
    *'
'*)
      desktop_fatal "${var_name} must be a single-line identifier list"
      ;;
  esac
  case "$var_value" in
    *[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:@%+=,\ -]*)
      desktop_fatal "${var_name} contains unsupported identifier characters: ${var_value}"
      ;;
  esac
}

desktop_validate_theme_name() {
  var_name=$1
  var_value=$2

  case "$var_value" in
    ''|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._+-]*)
      desktop_fatal "${var_name} must be a non-empty theme name without spaces"
      ;;
  esac
}

desktop_validate_font_family() {
  var_name=$1
  var_value=$2

  case "$var_value" in
    ''|*'
'*)
      desktop_fatal "${var_name} must be a non-empty single-line font family"
      ;;
  esac
  case "$var_value" in
    ' '*|*' '|*'  '*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._+\ -]*)
      desktop_fatal "${var_name} must be a single-line font family using supported characters"
      ;;
  esac
}

desktop_validate_username() {
  var_name=$1
  var_value=$2

  case "$var_value" in
    ''|root)
      desktop_fatal "${var_name} must be a non-root desktop username"
      ;;
  esac
  case "$var_value" in
    *'
'*)
      desktop_fatal "${var_name} must be a single-line username"
      ;;
  esac
  case "$var_value" in
    *[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-]*)
      desktop_fatal "${var_name} contains unsupported username characters: ${var_value}"
      ;;
  esac
}

desktop_validate_unit_name() {
  var_name=$1
  var_value=$2

  [ -n "$var_value" ] || desktop_fatal "${var_name} must not be empty"
  case "$var_value" in
    *'
'*)
      desktop_fatal "${var_name} must be a single-line unit name"
      ;;
  esac
  case "$var_value" in
    *[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.@:-]*)
      desktop_fatal "${var_name} contains unsupported unit name characters: ${var_value}"
      ;;
  esac
  case "$var_value" in
    *.target) ;;
    *) desktop_fatal "${var_name} must be a systemd target unit name, got: ${var_value}" ;;
  esac
}

desktop_validate_wayland_backend() {
  var_name=$1
  var_value=$2

  case "$var_value" in
    wayland) ;;
    *)
      desktop_fatal "${var_name} must stay native Wayland-only, got: ${var_value:-unset}"
      ;;
  esac
}

desktop_validate_mouse_accel_profile() {
  var_name=$1
  var_value=$2

  case "$var_value" in
    flat|adaptive) ;;
    *) desktop_fatal "${var_name} must be flat or adaptive, got: ${var_value:-unset}" ;;
  esac
}

desktop_validate_keyboard_layout_policy() {
  layouts=${LABWC_KEYBOARD_LAYOUTS:-us se}
  default_layout=${LABWC_KEYBOARD_DEFAULT_LAYOUT:-us}
  default_found=false

  desktop_validate_identifier_list LABWC_KEYBOARD_LAYOUTS "$layouts"
  desktop_validate_identifier_list LABWC_KEYBOARD_DEFAULT_LAYOUT "$default_layout"
  for layout in $layouts; do
    case "$layout" in
      us|se) ;;
      *) desktop_fatal "LABWC_KEYBOARD_LAYOUTS supports only us and se, got: ${layout}" ;;
    esac
    [ "$layout" != "$default_layout" ] || default_found=true
  done
  [ "$default_found" = true ] || desktop_fatal "LABWC_KEYBOARD_DEFAULT_LAYOUT must be included in LABWC_KEYBOARD_LAYOUTS"
}

desktop_validate_policy_env() {
  desktop_resolve_acceleration_availability
  desktop_resolve_managed_app_default_exec
  desktop_validate_bool LABWC_ENABLE_WAYBAR "${LABWC_ENABLE_WAYBAR:-true}"
  desktop_validate_bool LABWC_ENABLE_KANSHI "${LABWC_ENABLE_KANSHI:-true}"
  desktop_validate_bool LABWC_ENABLE_MAKO "${LABWC_ENABLE_MAKO:-true}"
  desktop_validate_bool LABWC_ENABLE_SWAYIDLE "${LABWC_ENABLE_SWAYIDLE:-true}"
  desktop_validate_bool LABWC_ENABLE_SWAYBG "${LABWC_ENABLE_SWAYBG:-true}"
  desktop_validate_bool LABWC_ENABLE_POLKIT_AGENT "${LABWC_ENABLE_POLKIT_AGENT:-true}"
  desktop_validate_bool LABWC_ENABLE_XDG_DESKTOP_PORTAL "${LABWC_ENABLE_XDG_DESKTOP_PORTAL:-true}"

  desktop_validate_uint_range LABWC_GREETER_VT "${LABWC_GREETER_VT:-1}" 1 12
  desktop_validate_optional_uint_range LABWC_OUTPUT_INTERNAL_PREFERRED_WIDTH "${LABWC_OUTPUT_INTERNAL_PREFERRED_WIDTH:-}" 640 16384
  desktop_validate_optional_uint_range LABWC_OUTPUT_INTERNAL_PREFERRED_HEIGHT "${LABWC_OUTPUT_INTERNAL_PREFERRED_HEIGHT:-}" 480 8640
  desktop_validate_optional_uint_range LABWC_OUTPUT_INTERNAL_PREFERRED_REFRESH_HZ "${LABWC_OUTPUT_INTERNAL_PREFERRED_REFRESH_HZ:-}" 24 1000
  desktop_validate_optional_uint_range LABWC_OUTPUT_EXTERNAL_PREFERRED_WIDTH "${LABWC_OUTPUT_EXTERNAL_PREFERRED_WIDTH:-}" 640 16384
  desktop_validate_optional_uint_range LABWC_OUTPUT_EXTERNAL_PREFERRED_HEIGHT "${LABWC_OUTPUT_EXTERNAL_PREFERRED_HEIGHT:-}" 480 8640
  desktop_validate_optional_uint_range LABWC_OUTPUT_EXTERNAL_PREFERRED_REFRESH_HZ "${LABWC_OUTPUT_EXTERNAL_PREFERRED_REFRESH_HZ:-}" 24 1000
  desktop_validate_output_mode_policy
  desktop_validate_decimal_range LABWC_OUTPUT_SCALE "${LABWC_OUTPUT_SCALE:-1}" 0.5 3
  desktop_validate_decimal_range LABWC_OUTPUT_INTERNAL_SCALE "${LABWC_OUTPUT_INTERNAL_SCALE:-1}" 0.5 3
  desktop_validate_decimal_range LABWC_OUTPUT_EXTERNAL_SCALE "${LABWC_OUTPUT_EXTERNAL_SCALE:-1}" 0.5 3
  desktop_validate_decimal_range LABWC_GREETER_INTERNAL_SCALE "${LABWC_GREETER_INTERNAL_SCALE:-1}" 0.5 3
  desktop_validate_decimal_range LABWC_GREETER_EXTERNAL_SCALE "${LABWC_GREETER_EXTERNAL_SCALE:-1}" 0.5 3
  desktop_validate_uint_range LABWC_OUTPUT_FALLBACK_REFRESH_HZ "${LABWC_OUTPUT_FALLBACK_REFRESH_HZ:-60}" 24 1000
  desktop_validate_uint_range LABWC_OUTPUT_HOTPLUG_DEBOUNCE_SECONDS "${LABWC_OUTPUT_HOTPLUG_DEBOUNCE_SECONDS:-1}" 0 30
  desktop_validate_uint_range LABWC_OUTPUT_INTERNAL_REFRESH_DELAY_SECONDS "${LABWC_OUTPUT_INTERNAL_REFRESH_DELAY_SECONDS:-0}" 0 30
  desktop_validate_uint_range LABWC_KEYBOARD_REPEAT_RATE "${LABWC_KEYBOARD_REPEAT_RATE:-40}" 1 80
  desktop_validate_uint_range LABWC_KEYBOARD_REPEAT_DELAY "${LABWC_KEYBOARD_REPEAT_DELAY:-250}" 100 1000
  desktop_validate_uint_range LABWC_IDLE_LOCK_SECONDS "${LABWC_IDLE_LOCK_SECONDS:-1800}" 60 86400
  desktop_validate_uint_range LABWC_IDLE_DPMS_SECONDS "${LABWC_IDLE_DPMS_SECONDS:-3600}" 60 86400
  desktop_validate_uint_range LABWC_IDLE_SUSPEND_SECONDS "${LABWC_IDLE_SUSPEND_SECONDS:-0}" 0 86400
  desktop_validate_uint_range LABWC_FONT_WINDOW_SIZE "${LABWC_FONT_WINDOW_SIZE:-12}" 8 32
  desktop_validate_uint_range LABWC_FONT_MENU_SIZE "${LABWC_FONT_MENU_SIZE:-13}" 8 32
  desktop_validate_uint_range LABWC_FONT_OSD_SIZE "${LABWC_FONT_OSD_SIZE:-13}" 8 32
  desktop_validate_font_family LABWC_TERMINAL_FONT_FAMILY "${LABWC_TERMINAL_FONT_FAMILY:-Noto Sans Mono}"
  desktop_validate_uint_range LABWC_TERMINAL_FONT_SIZE "${LABWC_TERMINAL_FONT_SIZE:-12}" 8 32
  desktop_validate_decimal_range LABWC_MOUSE_POINTER_SPEED "${LABWC_MOUSE_POINTER_SPEED:-0.55}" 0 1
  desktop_validate_mouse_accel_profile LABWC_MOUSE_ACCEL_PROFILE "${LABWC_MOUSE_ACCEL_PROFILE:-flat}"
  desktop_validate_uint_range LABWC_WAYBAR_HEIGHT "${LABWC_WAYBAR_HEIGHT:-46}" 24 128
  desktop_validate_uint_range LABWC_WAYBAR_TASKBAR_ICON_SIZE "${LABWC_WAYBAR_TASKBAR_ICON_SIZE:-18}" 8 128
  desktop_validate_uint_range LABWC_WAYBAR_TRAY_ICON_SIZE "${LABWC_WAYBAR_TRAY_ICON_SIZE:-18}" 8 128
  desktop_validate_uint_range LABWC_WAYBAR_FONT_SIZE "${LABWC_WAYBAR_FONT_SIZE:-15}" 8 32
  desktop_validate_uint_range LABWC_WAYBAR_MENU_BUTTON_MIN_WIDTH "${LABWC_WAYBAR_MENU_BUTTON_MIN_WIDTH:-52}" 24 200
  desktop_validate_uint_range LABWC_WAYBAR_MENU_BUTTON_PADDING_X "${LABWC_WAYBAR_MENU_BUTTON_PADDING_X:-11}" 0 64
  desktop_validate_uint_range LABWC_WAYBAR_WORKSPACE_BUTTON_MIN_WIDTH "${LABWC_WAYBAR_WORKSPACE_BUTTON_MIN_WIDTH:-26}" 16 128
  desktop_validate_uint_range LABWC_WAYBAR_WORKSPACE_BUTTON_PADDING_X "${LABWC_WAYBAR_WORKSPACE_BUTTON_PADDING_X:-10}" 0 64
  desktop_validate_uint_range LABWC_WAYBAR_TASKBAR_BUTTON_MIN_WIDTH "${LABWC_WAYBAR_TASKBAR_BUTTON_MIN_WIDTH:-0}" 0 128
  desktop_validate_uint_range LABWC_WAYBAR_TASKBAR_BUTTON_PADDING_X "${LABWC_WAYBAR_TASKBAR_BUTTON_PADDING_X:-4}" 0 64
  desktop_validate_uint_range LABWC_WAYBAR_INTERNAL_HEIGHT "${LABWC_WAYBAR_INTERNAL_HEIGHT:-${LABWC_WAYBAR_HEIGHT:-46}}" 24 128
  desktop_validate_uint_range LABWC_WAYBAR_INTERNAL_TASKBAR_ICON_SIZE "${LABWC_WAYBAR_INTERNAL_TASKBAR_ICON_SIZE:-${LABWC_WAYBAR_TASKBAR_ICON_SIZE:-18}}" 8 128
  desktop_validate_uint_range LABWC_WAYBAR_INTERNAL_TRAY_ICON_SIZE "${LABWC_WAYBAR_INTERNAL_TRAY_ICON_SIZE:-${LABWC_WAYBAR_TRAY_ICON_SIZE:-18}}" 8 128
  desktop_validate_uint_range LABWC_WAYBAR_INTERNAL_FONT_SIZE "${LABWC_WAYBAR_INTERNAL_FONT_SIZE:-${LABWC_WAYBAR_FONT_SIZE:-15}}" 8 32
  desktop_validate_uint_range LABWC_WAYBAR_INTERNAL_MENU_BUTTON_MIN_WIDTH "${LABWC_WAYBAR_INTERNAL_MENU_BUTTON_MIN_WIDTH:-${LABWC_WAYBAR_MENU_BUTTON_MIN_WIDTH:-52}}" 24 200
  desktop_validate_uint_range LABWC_WAYBAR_INTERNAL_MENU_BUTTON_PADDING_X "${LABWC_WAYBAR_INTERNAL_MENU_BUTTON_PADDING_X:-${LABWC_WAYBAR_MENU_BUTTON_PADDING_X:-11}}" 0 64
  desktop_validate_uint_range LABWC_WAYBAR_INTERNAL_WORKSPACE_BUTTON_MIN_WIDTH "${LABWC_WAYBAR_INTERNAL_WORKSPACE_BUTTON_MIN_WIDTH:-${LABWC_WAYBAR_WORKSPACE_BUTTON_MIN_WIDTH:-26}}" 16 128
  desktop_validate_uint_range LABWC_WAYBAR_INTERNAL_WORKSPACE_BUTTON_PADDING_X "${LABWC_WAYBAR_INTERNAL_WORKSPACE_BUTTON_PADDING_X:-${LABWC_WAYBAR_WORKSPACE_BUTTON_PADDING_X:-10}}" 0 64
  desktop_validate_uint_range LABWC_WAYBAR_INTERNAL_TASKBAR_BUTTON_MIN_WIDTH "${LABWC_WAYBAR_INTERNAL_TASKBAR_BUTTON_MIN_WIDTH:-${LABWC_WAYBAR_TASKBAR_BUTTON_MIN_WIDTH:-0}}" 0 128
  desktop_validate_uint_range LABWC_WAYBAR_INTERNAL_TASKBAR_BUTTON_PADDING_X "${LABWC_WAYBAR_INTERNAL_TASKBAR_BUTTON_PADDING_X:-${LABWC_WAYBAR_TASKBAR_BUTTON_PADDING_X:-4}}" 0 64
  desktop_validate_uint_range LABWC_WAYBAR_INTERNAL_APP_BUTTON_MIN_WIDTH "${LABWC_WAYBAR_INTERNAL_APP_BUTTON_MIN_WIDTH:-28}" 16 128
  desktop_validate_uint_range LABWC_WAYBAR_INTERNAL_APP_BUTTON_PADDING_X "${LABWC_WAYBAR_INTERNAL_APP_BUTTON_PADDING_X:-7}" 0 64
  desktop_validate_uint_range LABWC_WAYBAR_INTERNAL_STATUS_MODULE_MIN_WIDTH "${LABWC_WAYBAR_INTERNAL_STATUS_MODULE_MIN_WIDTH:-46}" 16 256
  desktop_validate_uint_range LABWC_WAYBAR_INTERNAL_STATUS_MODULE_PADDING_X "${LABWC_WAYBAR_INTERNAL_STATUS_MODULE_PADDING_X:-4}" 0 64
  desktop_validate_uint_range LABWC_WAYBAR_INTERNAL_QUICK_CONTROL_GROUP_PADDING_X "${LABWC_WAYBAR_INTERNAL_QUICK_CONTROL_GROUP_PADDING_X:-1}" 0 64
  desktop_validate_uint_range LABWC_WAYBAR_INTERNAL_QUICK_CONTROL_BUTTON_MIN_WIDTH "${LABWC_WAYBAR_INTERNAL_QUICK_CONTROL_BUTTON_MIN_WIDTH:-22}" 16 128
  desktop_validate_uint_range LABWC_WAYBAR_INTERNAL_QUICK_CONTROL_BUTTON_PADDING_X "${LABWC_WAYBAR_INTERNAL_QUICK_CONTROL_BUTTON_PADDING_X:-4}" 0 64
  desktop_validate_uint_range LABWC_WAYBAR_INTERNAL_SESSION_BUTTON_MIN_WIDTH "${LABWC_WAYBAR_INTERNAL_SESSION_BUTTON_MIN_WIDTH:-24}" 16 128
  desktop_validate_uint_range LABWC_WAYBAR_INTERNAL_SESSION_BUTTON_PADDING_X "${LABWC_WAYBAR_INTERNAL_SESSION_BUTTON_PADDING_X:-6}" 0 64
  desktop_validate_uint_range LABWC_GTK_FONT_SIZE "${LABWC_GTK_FONT_SIZE:-12}" 8 32
  desktop_validate_uint_range LABWC_QT_FONT_SIZE "${LABWC_QT_FONT_SIZE:-11}" 8 32
  desktop_validate_uint_range LABWC_QT_FIXED_FONT_SIZE "${LABWC_QT_FIXED_FONT_SIZE:-12}" 8 32
  desktop_validate_uint_range LABWC_GREETER_FONT_SIZE "${LABWC_GREETER_FONT_SIZE:-14}" 8 32
  desktop_validate_uint_range LABWC_GREETER_CLOCK_FONT_SIZE "${LABWC_GREETER_CLOCK_FONT_SIZE:-104}" 24 128
  desktop_validate_optional_uint_range LABWC_GREETER_PANEL_MARGIN "${LABWC_GREETER_PANEL_MARGIN:-}" 0 256
  desktop_validate_optional_uint_range LABWC_GREETER_PANEL_MIN_WIDTH "${LABWC_GREETER_PANEL_MIN_WIDTH:-}" 240 2048
  desktop_validate_optional_uint_range LABWC_GREETER_PANEL_PADDING_Y "${LABWC_GREETER_PANEL_PADDING_Y:-}" 0 256
  desktop_validate_optional_uint_range LABWC_GREETER_PANEL_PADDING_X "${LABWC_GREETER_PANEL_PADDING_X:-}" 0 256
  desktop_validate_optional_uint_range LABWC_GREETER_CONTROL_MIN_HEIGHT "${LABWC_GREETER_CONTROL_MIN_HEIGHT:-}" 24 256
  desktop_validate_optional_uint_range LABWC_GREETER_ENTRY_MIN_WIDTH "${LABWC_GREETER_ENTRY_MIN_WIDTH:-}" 160 2048
  desktop_validate_optional_uint_range LABWC_GREETER_SHELL_MIN_WIDTH "${LABWC_GREETER_SHELL_MIN_WIDTH:-}" 160 2048
  desktop_validate_optional_uint_range LABWC_GREETER_BUTTON_MIN_WIDTH "${LABWC_GREETER_BUTTON_MIN_WIDTH:-}" 80 1024
  desktop_validate_uint_range LABWC_FUZZEL_WIDTH "${LABWC_FUZZEL_WIDTH:-36}" 20 200
  desktop_validate_uint_range LABWC_FUZZEL_LINES "${LABWC_FUZZEL_LINES:-15}" 4 40
  desktop_validate_uint_range LABWC_FUZZEL_MENU_WIDTH "${LABWC_FUZZEL_MENU_WIDTH:-22}" 16 200
  desktop_validate_uint_range LABWC_FUZZEL_MENU_LINES "${LABWC_FUZZEL_MENU_LINES:-5}" 1 32
  desktop_validate_uint_range LABWC_FUZZEL_FONT_SIZE "${LABWC_FUZZEL_FONT_SIZE:-15}" 8 32
  desktop_validate_uint_range LABWC_FUZZEL_CONTAINER_MANAGEMENT_WIDTH "${LABWC_FUZZEL_CONTAINER_MANAGEMENT_WIDTH:-${LABWC_FUZZEL_MENU_WIDTH:-22}}" 16 200
  desktop_validate_uint_range LABWC_FUZZEL_CONTAINER_MANAGEMENT_LINES "${LABWC_FUZZEL_CONTAINER_MANAGEMENT_LINES:-${LABWC_FUZZEL_MENU_LINES:-5}}" 1 32
  desktop_validate_uint_range LABWC_FUZZEL_CONTAINER_MANAGEMENT_FONT_SIZE "${LABWC_FUZZEL_CONTAINER_MANAGEMENT_FONT_SIZE:-${LABWC_FUZZEL_FONT_SIZE:-15}}" 8 32
  desktop_validate_uint_range LABWC_FUZZEL_REMOTE_DESKTOP_WIDTH "${LABWC_FUZZEL_REMOTE_DESKTOP_WIDTH:-${LABWC_FUZZEL_MENU_WIDTH:-22}}" 16 200
  desktop_validate_uint_range LABWC_FUZZEL_REMOTE_DESKTOP_LINES "${LABWC_FUZZEL_REMOTE_DESKTOP_LINES:-${LABWC_FUZZEL_MENU_LINES:-5}}" 1 32
  desktop_validate_uint_range LABWC_FUZZEL_REMOTE_DESKTOP_FONT_SIZE "${LABWC_FUZZEL_REMOTE_DESKTOP_FONT_SIZE:-${LABWC_FUZZEL_FONT_SIZE:-15}}" 8 32
  desktop_validate_uint_range LABWC_FUZZEL_ENDPOINT_SECURITY_WIDTH "${LABWC_FUZZEL_ENDPOINT_SECURITY_WIDTH:-${LABWC_FUZZEL_MENU_WIDTH:-22}}" 16 200
  desktop_validate_uint_range LABWC_FUZZEL_ENDPOINT_SECURITY_LINES "${LABWC_FUZZEL_ENDPOINT_SECURITY_LINES:-${LABWC_FUZZEL_MENU_LINES:-5}}" 1 32
  desktop_validate_uint_range LABWC_FUZZEL_ENDPOINT_SECURITY_FONT_SIZE "${LABWC_FUZZEL_ENDPOINT_SECURITY_FONT_SIZE:-${LABWC_FUZZEL_FONT_SIZE:-15}}" 8 32
  desktop_validate_uint_range LABWC_FUZZEL_USERS_GROUPS_WIDTH "${LABWC_FUZZEL_USERS_GROUPS_WIDTH:-${LABWC_FUZZEL_MENU_WIDTH:-22}}" 16 200
  desktop_validate_uint_range LABWC_FUZZEL_USERS_GROUPS_LINES "${LABWC_FUZZEL_USERS_GROUPS_LINES:-${LABWC_FUZZEL_MENU_LINES:-5}}" 1 32
  desktop_validate_uint_range LABWC_FUZZEL_USERS_GROUPS_FONT_SIZE "${LABWC_FUZZEL_USERS_GROUPS_FONT_SIZE:-${LABWC_FUZZEL_FONT_SIZE:-15}}" 8 32
  desktop_validate_uint_range LABWC_FUZZEL_NETWORK_MANAGEMENT_WIDTH "${LABWC_FUZZEL_NETWORK_MANAGEMENT_WIDTH:-${LABWC_FUZZEL_MENU_WIDTH:-22}}" 16 200
  desktop_validate_uint_range LABWC_FUZZEL_NETWORK_MANAGEMENT_LINES "${LABWC_FUZZEL_NETWORK_MANAGEMENT_LINES:-${LABWC_FUZZEL_MENU_LINES:-5}}" 1 32
  desktop_validate_uint_range LABWC_FUZZEL_NETWORK_MANAGEMENT_FONT_SIZE "${LABWC_FUZZEL_NETWORK_MANAGEMENT_FONT_SIZE:-${LABWC_FUZZEL_FONT_SIZE:-15}}" 8 32
  desktop_validate_uint_range LABWC_FUZZEL_FIREWALL_SECURITY_WIDTH "${LABWC_FUZZEL_FIREWALL_SECURITY_WIDTH:-${LABWC_FUZZEL_MENU_WIDTH:-22}}" 16 200
  desktop_validate_uint_range LABWC_FUZZEL_FIREWALL_SECURITY_LINES "${LABWC_FUZZEL_FIREWALL_SECURITY_LINES:-${LABWC_FUZZEL_MENU_LINES:-5}}" 1 32
  desktop_validate_uint_range LABWC_FUZZEL_FIREWALL_SECURITY_FONT_SIZE "${LABWC_FUZZEL_FIREWALL_SECURITY_FONT_SIZE:-${LABWC_FUZZEL_FONT_SIZE:-15}}" 8 32
  desktop_validate_uint_range LABWC_FUZZEL_SYSTEM_CONFIGURATION_WIDTH "${LABWC_FUZZEL_SYSTEM_CONFIGURATION_WIDTH:-${LABWC_FUZZEL_MENU_WIDTH:-22}}" 16 200
  desktop_validate_uint_range LABWC_FUZZEL_SYSTEM_CONFIGURATION_LINES "${LABWC_FUZZEL_SYSTEM_CONFIGURATION_LINES:-${LABWC_FUZZEL_MENU_LINES:-5}}" 1 32
  desktop_validate_uint_range LABWC_FUZZEL_SYSTEM_CONFIGURATION_FONT_SIZE "${LABWC_FUZZEL_SYSTEM_CONFIGURATION_FONT_SIZE:-${LABWC_FUZZEL_FONT_SIZE:-15}}" 8 32
  desktop_validate_uint_range LABWC_FUZZEL_PHONE_MANAGEMENT_WIDTH "${LABWC_FUZZEL_PHONE_MANAGEMENT_WIDTH:-${LABWC_FUZZEL_MENU_WIDTH:-22}}" 16 200
  desktop_validate_uint_range LABWC_FUZZEL_PHONE_MANAGEMENT_LINES "${LABWC_FUZZEL_PHONE_MANAGEMENT_LINES:-${LABWC_FUZZEL_MENU_LINES:-5}}" 1 32
  desktop_validate_uint_range LABWC_FUZZEL_PHONE_MANAGEMENT_FONT_SIZE "${LABWC_FUZZEL_PHONE_MANAGEMENT_FONT_SIZE:-${LABWC_FUZZEL_FONT_SIZE:-15}}" 8 32
  desktop_validate_uint_range LABWC_FUZZEL_BACKUP_RECOVERY_WIDTH "${LABWC_FUZZEL_BACKUP_RECOVERY_WIDTH:-${LABWC_FUZZEL_MENU_WIDTH:-22}}" 16 200
  desktop_validate_uint_range LABWC_FUZZEL_BACKUP_RECOVERY_LINES "${LABWC_FUZZEL_BACKUP_RECOVERY_LINES:-${LABWC_FUZZEL_MENU_LINES:-5}}" 1 32
  desktop_validate_uint_range LABWC_FUZZEL_BACKUP_RECOVERY_FONT_SIZE "${LABWC_FUZZEL_BACKUP_RECOVERY_FONT_SIZE:-${LABWC_FUZZEL_FONT_SIZE:-15}}" 8 32
  desktop_validate_uint_range LABWC_FUZZEL_HARDWARE_PERIPHERALS_WIDTH "${LABWC_FUZZEL_HARDWARE_PERIPHERALS_WIDTH:-${LABWC_FUZZEL_MENU_WIDTH:-22}}" 16 200
  desktop_validate_uint_range LABWC_FUZZEL_HARDWARE_PERIPHERALS_LINES "${LABWC_FUZZEL_HARDWARE_PERIPHERALS_LINES:-${LABWC_FUZZEL_MENU_LINES:-5}}" 1 32
  desktop_validate_uint_range LABWC_FUZZEL_HARDWARE_PERIPHERALS_FONT_SIZE "${LABWC_FUZZEL_HARDWARE_PERIPHERALS_FONT_SIZE:-${LABWC_FUZZEL_FONT_SIZE:-15}}" 8 32
  desktop_validate_uint_range LABWC_CRYSTAL_DOCK_MINIMUM_ICON_SIZE "${LABWC_CRYSTAL_DOCK_MINIMUM_ICON_SIZE:-50}" 16 256
  desktop_validate_uint_range LABWC_CRYSTAL_DOCK_MAXIMUM_ICON_SIZE "${LABWC_CRYSTAL_DOCK_MAXIMUM_ICON_SIZE:-80}" 16 256
  desktop_validate_uint_range LABWC_CRYSTAL_DOCK_TOOLTIP_FONT_SIZE "${LABWC_CRYSTAL_DOCK_TOOLTIP_FONT_SIZE:-13}" 8 32
  desktop_validate_uint_range LABWC_CRYSTAL_DOCK_APP_MENU_ICON_SIZE "${LABWC_CRYSTAL_DOCK_APP_MENU_ICON_SIZE:-40}" 8 128
  desktop_validate_uint_range LABWC_CRYSTAL_DOCK_APP_MENU_FONT_SIZE "${LABWC_CRYSTAL_DOCK_APP_MENU_FONT_SIZE:-15}" 8 32
  desktop_validate_decimal_range LABWC_CRYSTAL_DOCK_CLOCK_FONT_SCALE_FACTOR "${LABWC_CRYSTAL_DOCK_CLOCK_FONT_SCALE_FACTOR:-1.0}" 0.5 2
  desktop_validate_uint_range LABWC_GREETER_HOTPLUG_DEBOUNCE_SECONDS "${LABWC_GREETER_HOTPLUG_DEBOUNCE_SECONDS:-0}" 0 10
  desktop_validate_uint_range LABWC_WORKSPACE_COUNT "${LABWC_WORKSPACE_COUNT:-4}" 1 12
  desktop_validate_uint_range LABWC_QBITTORRENT_PORT "${LABWC_QBITTORRENT_PORT:-50309}" 1 65535
  idle_lock_seconds=${LABWC_IDLE_LOCK_SECONDS:-1800}
  idle_dpms_seconds=${LABWC_IDLE_DPMS_SECONDS:-3600}
  idle_suspend_seconds=${LABWC_IDLE_SUSPEND_SECONDS:-0}
  case "${LABWC_ENABLE_SWAYIDLE:-true}" in
    true|yes|1|on)
      [ "$idle_dpms_seconds" -gt "$idle_lock_seconds" ] || \
        desktop_fatal "LABWC_IDLE_DPMS_SECONDS must be greater than LABWC_IDLE_LOCK_SECONDS so the lock screen appears before the outputs sleep"
      if [ "$idle_suspend_seconds" -gt 0 ]; then
        [ "$idle_suspend_seconds" -gt "$idle_dpms_seconds" ] || \
          desktop_fatal "LABWC_IDLE_SUSPEND_SECONDS must be greater than LABWC_IDLE_DPMS_SECONDS when suspend is enabled"
      fi
      ;;
  esac
  [ "${LABWC_QBITTORRENT_PORT:-50309}" -eq 50309 ] ||
    desktop_fatal "LABWC_QBITTORRENT_PORT must remain fixed at 50309"
  [ "${LABWC_CRYSTAL_DOCK_MAXIMUM_ICON_SIZE:-80}" -ge "${LABWC_CRYSTAL_DOCK_MINIMUM_ICON_SIZE:-50}" ] || \
    desktop_fatal "LABWC_CRYSTAL_DOCK_MAXIMUM_ICON_SIZE must be >= LABWC_CRYSTAL_DOCK_MINIMUM_ICON_SIZE"
  desktop_validate_apparmor_state \
    DESKTOP_APPARMOR_STATE \
    "${DESKTOP_APPARMOR_STATE:?DESKTOP_APPARMOR_STATE must be set by the desktop host profile}"

  desktop_validate_unit_name LABWC_DESKTOP_DEFAULT_TARGET "${LABWC_DESKTOP_DEFAULT_TARGET:-graphical.target}"
  desktop_validate_identifier_list LABWC_OUTPUT_INTERNAL_PREFIXES "${LABWC_OUTPUT_INTERNAL_PREFIXES:-eDP LVDS DSI}"
  desktop_validate_identifier_list LABWC_GREETER_USER_CANDIDATES "${LABWC_GREETER_USER_CANDIDATES:-_greetd greeter greetd}"
  desktop_validate_identifier_list LABWC_WLR_RENDERER "${LABWC_WLR_RENDERER-gles2}"
  desktop_validate_identifier_list LABWC_GSK_RENDERER "${LABWC_GSK_RENDERER-opengl}"
  desktop_validate_identifier_list LABWC_GDK_DISABLE "${LABWC_GDK_DISABLE-vulkan}"
  desktop_validate_identifier_list LABWC_WLR_NO_HARDWARE_CURSORS "${LABWC_WLR_NO_HARDWARE_CURSORS-1}"
  desktop_validate_identifier_list LABWC_WLR_SCENE_DISABLE_DIRECT_SCANOUT "${LABWC_WLR_SCENE_DISABLE_DIRECT_SCANOUT-1}"
  desktop_validate_identifier_list LABWC_GREETER_WLR_RENDERER "${LABWC_GREETER_WLR_RENDERER-gles2}"
  desktop_validate_identifier_list LABWC_GREETER_GSK_RENDERER "${LABWC_GREETER_GSK_RENDERER-opengl}"
  desktop_validate_identifier_list LABWC_GREETER_GDK_DISABLE "${LABWC_GREETER_GDK_DISABLE-vulkan}"
  desktop_validate_identifier_list LABWC_GREETER_WLR_NO_HARDWARE_CURSORS "${LABWC_GREETER_WLR_NO_HARDWARE_CURSORS-1}"
  desktop_validate_absolute_path LABWC_DESKTOP_DEFAULTS_FILE "${LABWC_DESKTOP_DEFAULTS_FILE:-/etc/default/labwc-desktop}"
  desktop_validate_absolute_path LABWC_DESKTOP_SESSION_COMMAND "${LABWC_DESKTOP_SESSION_COMMAND:-/usr/local/bin/labwc-session}"
  desktop_validate_absolute_path LABWC_WALLPAPER_PATH "${LABWC_WALLPAPER_PATH:-/usr/share/backgrounds/desktop/labwall0-1920x1080.png}"
  desktop_validate_absolute_path LABWC_LOCK_BACKGROUND_PATH "${LABWC_LOCK_BACKGROUND_PATH:-/usr/share/backgrounds/login/lock-1920x1080.png}"
  desktop_validate_absolute_path LABWC_GREETER_BACKGROUND_PATH "${LABWC_GREETER_BACKGROUND_PATH:-/usr/share/backgrounds/login/welcome-1920x1080.png}"
  desktop_validate_managed_app_default_exec \
    LABWC_MANAGED_APP_DEFAULT_EXEC \
    "${LABWC_MANAGED_APP_DEFAULT_EXEC:?LABWC_MANAGED_APP_DEFAULT_EXEC must be set by the desktop host profile}"
  desktop_validate_command_string LABWC_GREETER_COMMAND "${LABWC_GREETER_COMMAND:-/usr/local/bin/labwc-greeter-session}"
  desktop_validate_command_string LABWC_LAUNCHER_COMMAND "${LABWC_LAUNCHER_COMMAND:-labwc-fuzzel launcher}"
  desktop_validate_command_string LABWC_MENU_COMMAND "${LABWC_MENU_COMMAND:-labwc-fuzzel launcher}"
  desktop_validate_command_string LABWC_FILE_MANAGER_COMMAND "${LABWC_FILE_MANAGER_COMMAND:-thunar}"
  desktop_validate_command_string LABWC_AUDIO_CONTROL_COMMAND "${LABWC_AUDIO_CONTROL_COMMAND:-pavucontrol}"
  desktop_validate_command_string LABWC_DISPLAY_CONTROL_COMMAND "${LABWC_DISPLAY_CONTROL_COMMAND:-labwc-display-configuration}"
  desktop_validate_command_string LABWC_CALENDAR_COMMAND "${LABWC_CALENDAR_COMMAND:-labwc-calendar}"
  desktop_validate_command_string LABWC_BRIGHTNESS_CONTROL_COMMAND "${LABWC_BRIGHTNESS_CONTROL_COMMAND:-labwc-brightness-control}"
  desktop_validate_command_string LABWC_CAPTURE_COMMAND "${LABWC_CAPTURE_COMMAND:-labwc-capture}"
  desktop_validate_command_string LABWC_POWER_SETTINGS_COMMAND "${LABWC_POWER_SETTINGS_COMMAND:-labwc-power-settings}"
  desktop_validate_theme_name LABWC_ICON_THEME "${LABWC_ICON_THEME:-Papirus-Dark}"
  desktop_validate_wayland_backend LABWC_GDK_BACKEND "${LABWC_GDK_BACKEND:-wayland}"
  desktop_validate_wayland_backend LABWC_QT_QPA_PLATFORM "${LABWC_QT_QPA_PLATFORM:-wayland}"
  desktop_validate_wayland_backend LABWC_SDL_VIDEODRIVER "${LABWC_SDL_VIDEODRIVER:-wayland}"
  desktop_validate_wayland_backend LABWC_CLUTTER_BACKEND "${LABWC_CLUTTER_BACKEND:-wayland}"
  desktop_validate_keyboard_layout_policy

  case "${LABWC_OUTPUT_POLICY:-auto}" in
    auto|external-only) ;;
    *) desktop_fatal "unsupported LABWC_OUTPUT_POLICY: ${LABWC_OUTPUT_POLICY}" ;;
  esac
}

desktop_is_internal_output() {
  output_name=$1

  for output_prefix in ${LABWC_OUTPUT_INTERNAL_PREFIXES:-eDP LVDS DSI}; do
    case "$output_name" in
      "${output_prefix}"-*|"${output_prefix}"[0-9]*)
        return 0
        ;;
    esac
  done
  return 1
}

desktop_detect_connected_drm_outputs() {
  LABWC_DETECTED_OUTPUTS=
  LABWC_DETECTED_INTERNAL_OUTPUTS=
  LABWC_DETECTED_EXTERNAL_OUTPUTS=

  for status_path in /sys/class/drm/card*-*/status; do
    [ -r "$status_path" ] || continue
    status_value=$(sed -n '1p' "$status_path" 2>/dev/null || true)
    [ "$status_value" = connected ] || continue
    connector_name=${status_path%/status}
    connector_name=${connector_name##*/}
    connector_name=${connector_name#card*-}
    [ -n "$connector_name" ] || continue

    LABWC_DETECTED_OUTPUTS="${LABWC_DETECTED_OUTPUTS:+$LABWC_DETECTED_OUTPUTS }$connector_name"
    if desktop_is_internal_output "$connector_name"; then
      LABWC_DETECTED_INTERNAL_OUTPUTS="${LABWC_DETECTED_INTERNAL_OUTPUTS:+$LABWC_DETECTED_INTERNAL_OUTPUTS }$connector_name"
    else
      LABWC_DETECTED_EXTERNAL_OUTPUTS="${LABWC_DETECTED_EXTERNAL_OUTPUTS:+$LABWC_DETECTED_EXTERNAL_OUTPUTS }$connector_name"
    fi
  done

  LABWC_DETECTED_PRIMARY_OUTPUT=
  if [ "${LABWC_OUTPUT_POLICY:-auto}" = auto ] &&
     [ -n "$LABWC_DETECTED_INTERNAL_OUTPUTS" ]; then
    for output_name in $LABWC_DETECTED_INTERNAL_OUTPUTS; do
      LABWC_DETECTED_PRIMARY_OUTPUT=$output_name
      break
    done
  fi
  if [ -z "$LABWC_DETECTED_PRIMARY_OUTPUT" ]; then
    for output_name in $LABWC_DETECTED_EXTERNAL_OUTPUTS; do
      LABWC_DETECTED_PRIMARY_OUTPUT=$output_name
      break
    done
  fi
  if [ -z "$LABWC_DETECTED_PRIMARY_OUTPUT" ]; then
    for output_name in $LABWC_DETECTED_INTERNAL_OUTPUTS; do
      LABWC_DETECTED_PRIMARY_OUTPUT=$output_name
      break
    done
  fi
}

desktop_resolve_greeter_user() {
  LABWC_GREETER_USER=
  for greeter_user in ${LABWC_GREETER_USER_CANDIDATES:-_greetd greeter greetd}; do
    [ -n "$greeter_user" ] || continue
    case "$greeter_user" in
      *[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-]*)
        desktop_fatal "unsafe greeter user candidate: ${greeter_user}"
        ;;
    esac
    if grep -q "^${greeter_user}:" /target/etc/passwd 2>/dev/null; then
      LABWC_GREETER_USER=$greeter_user
      break
    fi
  done
  [ -n "$LABWC_GREETER_USER" ] || desktop_fatal "no target greetd greeter user found in candidates: ${LABWC_GREETER_USER_CANDIDATES:-_greetd greeter greetd}"
}
