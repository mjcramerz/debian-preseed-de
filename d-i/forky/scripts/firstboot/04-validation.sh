#!/bin/sh
set -u

PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH
umask 077

FIRSTBOOT_LOG_DIR=${FIRSTBOOT_LOG_DIR:-/var/lib/installer-state/logs/firstboot}
FIRSTBOOT_DATA_DIR=${FIRSTBOOT_DATA_DIR:-${FIRSTBOOT_LOG_DIR}/data}
FIRSTBOOT_LOG_FILE=${FIRSTBOOT_LOG_FILE:-${FIRSTBOOT_LOG_DIR}/20-firstboot.log}
VALIDATION_FILE=${FIRSTBOOT_DATA_DIR}/validation-results.txt

mkdir -p "$FIRSTBOOT_LOG_DIR" "$FIRSTBOOT_DATA_DIR" 2>/dev/null || exit 1
: >>"$FIRSTBOOT_LOG_FILE" 2>/dev/null || exit 1
: >"$VALIDATION_FILE" 2>/dev/null || exit 1
chmod 0600 "$VALIDATION_FILE" 2>/dev/null || true

timestamp() {
  date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || printf '%s\n' unknown-time
}

log_line() {
  stage=$1
  level=$2
  component=$3
  shift 3
  printf '%s stage=%s level=%s component=%s %s\n' \
    "$(timestamp)" "$stage" "$level" "$component" "$*" >>"$FIRSTBOOT_LOG_FILE"
}

if [ -r /usr/local/lib/firstboot.d/logging.sh ]; then
  # shellcheck disable=SC1091
  . /usr/local/lib/firstboot.d/logging.sh
fi

record() {
  printf '%s\n' "$*" >>"$VALIDATION_FILE"
}

capture() {
  output_name=$1
  shift
  output_file="${FIRSTBOOT_DATA_DIR}/${output_name}"
  {
    printf '# command:'
    for arg in "$@"; do
      printf ' %s' "$arg"
    done
    printf '\n'
    timeout --signal=TERM --kill-after=2s 20s "$@"
  } >"$output_file" 2>&1 || printf 'status=%s\n' "$?" >>"$output_file"
  chmod 0600 "$output_file" 2>/dev/null || true
}

failures=0

check_path() {
  label=$1
  path=$2
  if [ -e "$path" ]; then
    record "PASS ${label}: ${path}"
  else
    record "FAIL ${label}: missing ${path}"
    log_line validation error "$label" "missing=${path}"
    failures=$((failures + 1))
  fi
}

check_absent_path() {
  label=$1
  path=$2
  if [ ! -e "$path" ] && [ ! -L "$path" ]; then
    record "PASS ${label}: ${path}"
  else
    record "FAIL ${label}: unexpected ${path}"
    log_line validation error "$label" "unexpected=${path}"
    failures=$((failures + 1))
  fi
}

check_command() {
  label=$1
  shift
  if "$@" >>"$VALIDATION_FILE" 2>&1; then
    record "PASS ${label}"
  else
    status=$?
    record "FAIL ${label}: status=${status}"
    log_line validation error "$label" "status=${status}"
    failures=$((failures + 1))
  fi
}

bool_is_true() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
  esac
  return 1
}

desktop_renderer_policy_matches() {
  /bin/sh -eu -c '
set -eu
. /etc/default/labwc-desktop
[ "${LABWC_WLR_RENDERER:-}" = "gles2" ]
[ "${LABWC_GSK_RENDERER:-}" = "opengl" ]
[ "${LABWC_GDK_DISABLE:-}" = "vulkan" ]
[ "${LABWC_WLR_NO_HARDWARE_CURSORS:-}" = "1" ]
[ "${LABWC_WLR_SCENE_DISABLE_DIRECT_SCANOUT:-}" = "1" ]
[ "${LABWC_GREETER_WLR_RENDERER:-}" = "gles2" ]
[ "${LABWC_GREETER_GSK_RENDERER:-}" = "opengl" ]
[ "${LABWC_GREETER_GDK_DISABLE:-}" = "vulkan" ]
[ "${LABWC_GREETER_WLR_NO_HARDWARE_CURSORS:-}" = "1" ]
[ ! -e /etc/environment.d/90-labwc-session.conf ]
grep -Eq "(^|[|;&][[:space:]]*)export WLR_RENDERER=" /usr/local/bin/labwc-session
grep -Eq "(^|[|;&][[:space:]]*)export GSK_RENDERER=" /usr/local/bin/labwc-session
grep -q "^export GDK_DISABLE=" /usr/local/bin/labwc-session
grep -Eq "(^|[|;&][[:space:]]*)export WLR_NO_HARDWARE_CURSORS=" /usr/local/bin/labwc-session
grep -q "WLR_SCENE_DISABLE_DIRECT_SCANOUT=" /usr/local/bin/labwc-session
grep -q "^export QT_OPENGL=" /usr/local/bin/labwc-session
grep -q "^export QSG_RHI_BACKEND=" /usr/local/bin/labwc-session
grep -q "activation_environment_names=.*QT_OPENGL QSG_RHI_BACKEND" /usr/local/bin/labwc-autostart
grep -q "^labwc_x11_environment_names='"'"'DISPLAY XAUTHORITY WLR_XWAYLAND XWAYLAND XWAYLAND_PATH XWAYLAND_NO_GLAMOR XWAYLAND_FORCE_SCALE XWAYLAND_RESTART_DELAY _XWAYLAND_GLOBAL_OUTPUT_SCALE WINDOWID SESSION_MANAGER DESKTOP_STARTUP_ID'"'"'$" /usr/local/bin/labwc-session
grep -q "^labwc_x11_environment_names='"'"'DISPLAY XAUTHORITY WLR_XWAYLAND XWAYLAND XWAYLAND_PATH XWAYLAND_NO_GLAMOR XWAYLAND_FORCE_SCALE XWAYLAND_RESTART_DELAY _XWAYLAND_GLOBAL_OUTPUT_SCALE WINDOWID SESSION_MANAGER DESKTOP_STARTUP_ID'"'"'$" /usr/local/bin/labwc-greeter-session
grep -q "^labwc_x11_environment_names='"'"'DISPLAY XAUTHORITY WLR_XWAYLAND XWAYLAND XWAYLAND_PATH XWAYLAND_NO_GLAMOR XWAYLAND_FORCE_SCALE XWAYLAND_RESTART_DELAY _XWAYLAND_GLOBAL_OUTPUT_SCALE WINDOWID SESSION_MANAGER DESKTOP_STARTUP_ID'"'"'$" /usr/local/bin/labwc-autostart
grep -q "unset \\\$labwc_x11_environment_names" /usr/local/bin/labwc-session
grep -q "unset \\\$labwc_x11_environment_names" /usr/local/bin/labwc-greeter-session
grep -q "unset \\\$labwc_x11_environment_names" /usr/local/bin/labwc-autostart
grep -q "unset-environment \\\$cleanup_environment_names" /usr/local/bin/labwc-session
grep -q "^cleanup_environment_names=.*{labwc_x11_environment_names}" /usr/local/bin/labwc-session
grep -q "unset-environment \\\$labwc_x11_environment_names" /usr/local/bin/labwc-autostart
! grep -q "_JAVA_AWT_WM_NONREPARENTING" /etc/skel-desktop/.config/labwc/environment.d/10-wayland.env
! grep -q "_JAVA_AWT_WM_NONREPARENTING" /usr/local/bin/labwc-autostart
' sh
}

desktop_icon_theme_policy_matches() {
  /bin/sh -eu -c '
set -eu
. /etc/default/labwc-desktop
account_user=${LABWC_QBITTORRENT_USER:-}
icon_theme=${LABWC_ICON_THEME:-}
[ -n "$account_user" ]
[ -n "$icon_theme" ]
account_home=$(getent passwd "$account_user" | cut -d: -f6)
[ -n "$account_home" ]
[ -r "/usr/share/icons/${icon_theme}/index.theme" ]
grep -Fxq "icon_theme=${icon_theme}" "$account_home/.config/qt6ct/qt6ct.conf"
' sh
}

check_desktop_command_required() {
  command_name=$1
  if command -v "$command_name" >/dev/null 2>&1; then
    record "PASS desktop-command-${command_name}"
  else
    record "FAIL desktop-command-${command_name}: missing"
    log_line validation error desktop "missing_command=${command_name}"
    failures=$((failures + 1))
  fi
}

check_desktop_command_optional() {
  command_name=$1
  if command -v "$command_name" >/dev/null 2>&1; then
    record "PASS desktop-command-${command_name}"
  else
    record "WARN desktop-command-${command_name}: missing"
    log_line validation warn desktop "missing_optional_command=${command_name}"
  fi
}

check_desktop_command_optional_any() {
  primary_command=$1
  shift
  for command_name in "$primary_command" "$@"; do
    if command -v "$command_name" >/dev/null 2>&1; then
      record "PASS desktop-command-${command_name}"
      return 0
    fi
  done
  record "WARN desktop-command-${primary_command}: missing"
  log_line validation warn desktop "missing_optional_command=${primary_command}"
}

validate_desktop_role() {
  if [ ! -r /etc/default/labwc-desktop ]; then
    log_line validation info desktop "desktop_role=not-selected"
    return 0
  fi

  record "desktop_role=selected"
  log_line validation info desktop "desktop_role=selected"
  check_command desktop-defaults-metadata \
    /bin/sh -eu -c '
      [ -f /etc/default/labwc-desktop ]
      [ ! -L /etc/default/labwc-desktop ]
      [ "$(stat -c "%u:%g:%a" /etc/default/labwc-desktop)" = "0:0:644" ]
    ' sh
  check_command desktop-skeleton-metadata \
    /bin/sh -eu -c '
      skeleton=/etc/skel-desktop
      [ -d "$skeleton" ]
      [ ! -L "$skeleton" ]
      [ "$(stat -c "%u:%g:%a" "$skeleton")" = "0:0:755" ]
      legacy_skeleton_parent=/etc/skel
      legacy_skeleton_name=primary
      legacy_skeleton="${legacy_skeleton_parent}/${legacy_skeleton_name}"
      [ ! -e "$legacy_skeleton" ]
      [ ! -L "$legacy_skeleton" ]
    ' sh
  desktop_account_user=$(
    /bin/sh -eu -c '
      . /etc/default/labwc-desktop
      printf "%s\n" "${LABWC_QBITTORRENT_USER:-}"
    ' sh 2>/dev/null || true
  )
  case "$desktop_account_user" in
    ''|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-]*)
      desktop_account_home=
      record "FAIL desktop-primary-account: invalid user ${desktop_account_user:-unset}"
      log_line validation error desktop "primary_account_invalid=${desktop_account_user:-unset}"
      failures=$((failures + 1))
      ;;
    *)
      desktop_account_home=$(getent passwd "$desktop_account_user" | cut -d: -f6)
      case "$desktop_account_home" in
        /*) ;;
        *)
          record "FAIL desktop-primary-account: missing home for ${desktop_account_user}"
          log_line validation error desktop "primary_account_home_missing=${desktop_account_user}"
          failures=$((failures + 1))
          desktop_account_home=
          ;;
      esac
      ;;
  esac
  for desktop_path in \
    /etc/default/labwc-desktop \
    /usr/local/share/dbus-1 \
    /usr/local/share/dbus-1/services \
    /etc/systemd/user/wireplumber.service.d/20-no-root.conf \
    /etc/pam.d/greetd \
    /etc/pam.d/greetd-greeter \
    /etc/pam.d/swaylock \
    /etc/greetd/config.toml \
    /etc/greetd/gtkgreet.css \
    /etc/greetd/gtkgreet-power.css \
    /etc/polkit-1/rules.d/00-admin-identities.rules \
    /etc/polkit-1/rules.d/03-labwc-power.rules \
    /etc/polkit-1/rules.d/05-active-local-gate.rules \
    /etc/polkit-1/rules.d/10-greetd-power.rules \
    /etc/polkit-1/rules.d/10-pkexec.rules \
    /etc/polkit-1/rules.d/20-login1-power.rules \
    /etc/polkit-1/rules.d/40-networkmanager.rules \
    /etc/polkit-1/rules.d/50-usb-policy.rules \
    /etc/polkit-1/rules.d/55-software-management.rules \
    /etc/polkit-1/rules.d/60-system-services-identity.rules \
    /etc/polkit-1/rules.d/70-hardware-peripherals.rules \
    /etc/fonts/fonts.conf \
    /usr/share/wayland-sessions/labwc.desktop \
    /usr/share/applications/computer-management.desktop \
    /usr/share/applications/remote-desktop-management.desktop \
    /usr/local/bin/labwc-greeter-session \
    /usr/local/bin/labwc-greeter-output \
    /usr/local/bin/labwc-greeter-power \
    /usr/local/sbin/greetd-power-action \
    /usr/local/bin/labwc-session \
    /usr/local/bin/labwc-autostart \
    /usr/local/bin/labwc-wallpaper-save \
    /usr/local/bin/labwc-admin-action \
    /usr/local/libexec/labwc-admin-action-root \
    /usr/local/libexec/labwc-admin-action-worker \
    /usr/local/libexec/labwc-logout-root \
    /usr/local/libexec/labwc-session-state \
    /etc/skel-desktop/.config/systemd/user/labwc-session-state@.service \
    /etc/skel-desktop/.config/systemd/user/labwc-session-restore.service \
    /etc/systemd/system/labwc-admin-action@.service \
    /usr/local/bin/labwc-calendar \
    /usr/local/libexec/labwc-calendar \
    /usr/local/bin/labwc-logout \
    /usr/local/bin/labwc-fuzzel \
    /usr/local/bin/labwc-computer-management \
    /usr/local/bin/labwc-ai-copilots \
    /usr/local/bin/labwc-ai-copilots-action \
    /usr/local/libexec/labwc-ai-llama-server \
    /usr/local/libexec/labwc-ai-model-install-root \
    /usr/local/libexec/labwc-ai-model-info \
    /usr/local/bin/labwc-display-configuration \
    /usr/local/bin/labwc-digital-assets \
    /usr/local/bin/labwc-digital-assets-action \
    /usr/local/bin/labwc-users-groups-menu \
    /usr/local/bin/labwc-adb-menu \
    /usr/local/bin/labwc-adb-action \
    /usr/local/bin/labwc-maintenance-menu \
    /usr/local/bin/labwc-podman-menu \
    /usr/local/bin/labwc-external-drives \
    /usr/local/bin/labwc-security-action \
    /usr/local/bin/labwc-system-action \
    /usr/local/bin/labwc-recovery-action \
    /usr/local/bin/labwc-network-control-menu \
    /usr/local/bin/labwc-network-control-action \
    /usr/local/bin/labwc-firewall-menu \
    /usr/local/bin/labwc-firewall-action \
    /usr/local/bin/labwc-network-scan-menu \
    /usr/local/bin/labwc-network-scan-action \
    /usr/local/bin/labwc-terminal \
    /usr/local/bin/telbot \
    /usr/local/bin/labwc-bluetooth \
    /usr/local/bin/labwc-brightness-control \
    /usr/local/bin/labwc-power-settings \
    /usr/local/bin/labwc-keyboard-layout \
    /usr/local/bin/labwc-remote-desktop \
    /usr/local/bin/labwc-freerdp-askpass \
    /usr/local/libexec/bluetooth-controller-init \
    /usr/local/libexec/labwc-output-watch \
    /usr/local/libexec/labwc-kanshi \
    /usr/local/libexec/labwc-swaybg \
    /usr/local/libexec/labwc-swayidle \
    /usr/local/libexec/rsyslog-managed-security-socket \
    /etc/rsyslog.d/39-security-scanners.conf \
    /etc/logrotate.d/security-scanners \
    /etc/systemd/system/rsyslog.service.d/30-managed-security-scanner-socket.conf \
    /etc/systemd/system/user-1000.slice.d/50-resource-accounting.conf \
    /etc/systemd/system/user@.service.d/50-oom-score.conf \
    /etc/systemd/user.conf.d/50-resource-defaults.conf \
    /usr/local/bin/labwc-run \
    /usr/local/bin/labwc-wayscriber-toggle \
    /usr/bin/wayscriber \
    /etc/systemd/user/dbus-broker.service.d/10-broker-hardening.conf \
    /etc/systemd/user/foot-server.service.d/10-labwc-session.conf \
    /etc/systemd/user/foot-server.socket.d/10-labwc-session.conf \
    /etc/systemd/user/mako.service.d/10-labwc-session.conf \
    /etc/systemd/user/hyprpolkitagent.service.d/10-labwc-session.conf \
    /etc/systemd/user/filter-chain.service.d/10-labwc-session.conf \
    /etc/systemd/user/wayscriber.service.d/10-labwc-session.conf \
    /etc/systemd/user/xdg-desktop-portal.service.d/10-labwc-session.conf \
    /etc/systemd/user/xdg-desktop-portal-gtk.service.d/10-labwc-session.conf \
    /etc/systemd/user/xdg-desktop-portal-wlr.service.d/10-labwc-session.conf \
    /etc/systemd/user/xdg-desktop-portal-lxqt.service.d/10-labwc-session.conf \
    /etc/skel-desktop/.gnupg/gpg-agent.conf \
    /etc/skel-desktop/.config/systemd/user/waybar.service \
    /etc/skel-desktop/.config/systemd/user/waybar.service.d/20-tray-compat.conf \
    /etc/skel-desktop/.config/systemd/user/labwc-adb-server.service \
    /etc/skel-desktop/.config/systemd/user/llama-server.service \
    /etc/skel-desktop/.config/systemd/user/labwc-output-watch.service \
    /etc/skel-desktop/.config/systemd/user/labwc-mute-default-microphone.service \
    /etc/skel-desktop/.config/systemd/user/swaybg.service \
    /etc/skel-desktop/.config/systemd/user/kanshi.service \
    /etc/skel-desktop/.config/systemd/user/swayidle.service \
    /etc/skel-desktop/.config/systemd/user/crystal-dock.service \
    /etc/mailname \
    /etc/aliases \
    /etc/apt/listchanges.conf \
    /etc/apt/apt.conf.d/60desktop-local-mail.conf \
    /etc/skel-desktop/.profile \
    /etc/skel-desktop/.bash_profile \
    /etc/skel-desktop/.bashrc \
    /etc/skel-desktop/.bash_aliases \
    /etc/skel-desktop/.config/nano/nanorc \
    /etc/skel-desktop/.zshenv \
    /etc/skel-desktop/.zprofile \
    /etc/skel-desktop/.zshrc \
    /etc/skel-desktop/.zlogout \
    /etc/skel-desktop/.zsh_aliases \
    /etc/skel-desktop/.profile.d \
    /etc/skel-desktop/.config/labwc/rc.xml \
    /etc/skel-desktop/.config/labwc/menu.xml \
    /etc/skel-desktop/.config/waypaper/config.ini \
    /etc/skel-desktop/.config/waypaper/keybindings.ini \
    /etc/skel-desktop/.config/waypaper/style.css \
    /etc/skel-desktop/.config/mako/config \
    /etc/skel-desktop/.config/satty/config.toml \
    /etc/skel-desktop/.config/satty/overrides.css \
    /etc/skel-desktop/.config/systemd/user/labwc-session.target \
    /etc/skel-desktop/.config/systemd/user/labwc-health-notify.service \
    /etc/skel-desktop/.config/systemd/user/labwc-health-notify.path \
    /etc/skel-desktop/.config/systemd/user/labwc-health-notify.timer \
    /etc/skel-desktop/.config/systemd/user/labwc-plans.service \
    /etc/default/labwc-plans \
    /etc/skel-desktop/.config/systemd/user/labwc-kwallet-portal.service \
    /etc/skel-desktop/.local/share/dbus-1/services/org.freedesktop.secrets.service \
    /usr/local/bin/labwc-health-notify \
    /usr/local/libexec/labwc-plans.pl \
    /usr/local/libexec/labwc-greeter-client \
    /usr/local/share/labwc-greeter/rc.xml \
    /usr/local/share/labwc-greeter/autostart \
    /etc/skel-desktop/.config/mpv/mpv.conf \
    /etc/skel-desktop/.config/mpv/input.conf \
    /etc/skel-desktop/.config/systemd/user/labwc-calendar-sync.service \
    /etc/skel-desktop/.config/systemd/user/labwc-calendar-sync.timer \
    /etc/skel-desktop/.config/systemd/user/labwc-sync-application-launchers.service \
    /etc/skel-desktop/.config/systemd/user/labwc-sync-application-launchers.path \
    /etc/skel-desktop/.config/Thunar/uca.xml \
    /etc/skel-desktop/.config/user-dirs.dirs \
    /etc/skel-desktop/.config/btop/btop.conf \
    /etc/skel-desktop/.config/fzf/default-opts \
    /etc/xdg/gtk-3.0/settings.ini \
    /etc/xdg/gtk-4.0/settings.ini
  do
    check_path "desktop-path-${desktop_path}" "$desktop_path"
  done

  check_command desktop-system-dbus-service-directory-metadata \
    /bin/sh -eu -c '
      for path in /usr/local/share/dbus-1 /usr/local/share/dbus-1/services; do
        [ -d "$path" ]
        [ ! -L "$path" ]
        [ "$(stat -c "%u:%g:%a" "$path")" = "0:0:755" ]
      done
    ' sh
  check_command desktop-wireplumber-user-conditions \
    /bin/sh -eu -c '
      . /etc/default/labwc-desktop
      [ -n "${LABWC_GREETER_USER:-}" ]
      dropin=/etc/systemd/user/wireplumber.service.d/20-no-root.conf
      [ -f "$dropin" ]
      [ ! -L "$dropin" ]
      grep -Fxq "ConditionUser=!root" "$dropin"
      grep -Fxq "ConditionUser=!${LABWC_GREETER_USER}" "$dropin"
    ' sh
  check_command desktop-swaylock-authentication-chain \
    /bin/sh -eu -c '
      helper_package=$(dpkg-query -S /usr/sbin/unix_chkpwd)
      printf "%s\n" "$helper_package" |
        grep -Eq "^libpam-modules-bin(:[^:[:space:]]+)?: /usr/sbin/unix_chkpwd$"
      shadow_group_entry=$(getent group shadow)
      shadow_gid=$(printf "%s\n" "$shadow_group_entry" | cut -d: -f3)
      case "$shadow_gid" in ""|*[!0-9]*) exit 1 ;; esac
      [ -f /etc/shadow ] && [ ! -L /etc/shadow ]
      [ -f /usr/sbin/unix_chkpwd ] && [ ! -L /usr/sbin/unix_chkpwd ]
      [ "$(stat -c "%u:%g:%a" /etc/shadow)" = "0:$shadow_gid:640" ]
      [ "$(stat -c "%u:%g:%a" /usr/sbin/unix_chkpwd)" = "0:$shadow_gid:2755" ]
      helper_mount_options=$(findmnt -n -o OPTIONS -T /usr/sbin/unix_chkpwd)
      case ",$helper_mount_options," in *,nosuid,*) exit 1 ;; esac
      grep -Fxq "@include common-auth" /etc/pam.d/swaylock
      grep -Fxq "@include common-account" /etc/pam.d/swaylock
      ! grep -Eq "^[[:space:]]*auth[[:space:]].*pam_permit[.]so" /etc/pam.d/swaylock
    ' sh

  desktop_wallpaper_path=$(
    /bin/sh -eu -c '
      . /etc/default/labwc-desktop
      printf "%s\n" "${LABWC_WALLPAPER_PATH:-/usr/share/backgrounds/desktop/wallpaper-1920x1080.png}"
    ' sh 2>/dev/null || true
  )
  case "$desktop_wallpaper_path" in
    /usr/share/backgrounds/desktop/*) ;;
    *)
      record "FAIL desktop-wallpaper-config: unmanaged ${desktop_wallpaper_path}"
      log_line validation error desktop "unmanaged_wallpaper=${desktop_wallpaper_path}"
      failures=$((failures + 1))
      ;;
  esac
  if [ -f "$desktop_wallpaper_path" ] && [ -r "$desktop_wallpaper_path" ]; then
    record "PASS desktop-wallpaper-config: ${desktop_wallpaper_path}"
  else
    record "FAIL desktop-wallpaper-config: unreadable ${desktop_wallpaper_path}"
    log_line validation error desktop "unreadable_wallpaper=${desktop_wallpaper_path}"
    failures=$((failures + 1))
  fi

  desktop_nvidia_acceleration_available=$(
    /bin/sh -eu -c '
      . /etc/default/labwc-desktop
      printf "%s\n" "${LABWC_NVIDIA_ACCELERATION_AVAILABLE:-false}"
    ' sh 2>/dev/null || true
  )
  if bool_is_true "$desktop_nvidia_acceleration_available"; then
    check_path desktop-nvidia-char-link-udev-rule /etc/udev/rules.d/71-managed-nvidia-char-links.rules
    check_path desktop-nvidia-char-link-helper /usr/local/libexec/managed-nvidia-char-links
    check_path desktop-nvidia-char-link-service /etc/systemd/system/managed-nvidia-char-links.service
    check_path desktop-nvidia-char-link-path /etc/systemd/system/managed-nvidia-char-links.path
    check_command desktop-nvidia-char-link-watcher systemctl is-active --quiet managed-nvidia-char-links.path
    check_command desktop-nvidia-char-device-links /usr/local/libexec/managed-nvidia-char-links --check
  else
    check_absent_path desktop-nvidia-char-link-udev-rule /etc/udev/rules.d/71-managed-nvidia-char-links.rules
  fi
  unset desktop_nvidia_acceleration_available

  check_command desktop-x11-socket-directory-metadata \
    /bin/sh -eu -c '
      [ -d /tmp/.X11-unix ]
      [ ! -L /tmp/.X11-unix ]
      [ "$(stat -c "%u:%g:%a" /tmp/.X11-unix)" = "0:0:1777" ]
    ' sh
  check_absent_path desktop-public-xwayland-binary /usr/bin/Xwayland
  check_command desktop-public-xwayland-package-absent \
    /bin/sh -eu -c '
      [ "$(dpkg-query -W -f="\${Status}" xwayland 2>/dev/null || true)" != "install ok installed" ]
    ' sh
  check_command desktop-pool-root-metadata \
    /bin/sh -eu -c '
      [ -d /pool ]
      [ ! -L /pool ]
      [ "$(stat -c "%u:%G:%a" /pool)" = "0:devops:3775" ]
    ' sh
  check_command desktop-labwc-plans-environment-source \
    /bin/sh -eu -c '
      grep -Fxq "EnvironmentFile=/etc/default/labwc-plans" /etc/skel-desktop/.config/systemd/user/labwc-plans.service
      ! grep -Eq "^(LoadCredential=|EnvironmentFile=%d/)" /etc/skel-desktop/.config/systemd/user/labwc-plans.service
    ' sh
  if [ -r /etc/podman-devops/layout.json ]; then
    check_command podman-devops-system-service-account \
      /bin/sh -eu -c '
        passwd_entry=$(getent passwd devops)
        [ "$(printf "%s\n" "$passwd_entry" | cut -d: -f1)" = devops ]
        uid=$(printf "%s\n" "$passwd_entry" | cut -d: -f3)
        [ "$uid" -gt 0 ]
        [ "$uid" -lt 1000 ]
        [ "$(printf "%s\n" "$passwd_entry" | cut -d: -f6)" = /nonexistent ]
        [ "$(printf "%s\n" "$passwd_entry" | cut -d: -f7)" = /usr/sbin/nologin ]
        [ -x /usr/sbin/nologin ]
        set -- $(passwd -S devops)
        [ "$1" = devops ]
        [ "$2" = L ]
        [ "$(id -nG devops)" = devops ]
        for forbidden_home in /nonexistent /data/accounts/devops
        do
          [ ! -e "$forbidden_home" ]
          [ ! -L "$forbidden_home" ]
        done
        [ "$(stat -c "%u:%G:%a" /etc/podman-devops)" = "0:devops:750" ]
        [ "$(stat -c "%u:%G:%a" /etc/podman-devops/server)" = "0:devops:750" ]
        [ "$(stat -c "%u:%G:%a" /etc/podman-devops/server/containers)" = "0:devops:750" ]
        for server_config in containers.conf storage.conf registries.conf
        do
          [ "$(stat -c "%u:%G:%a" "/etc/podman-devops/server/containers/$server_config")" = "0:devops:640" ]
        done
        [ ! -e /var/lib/systemd/linger/devops ]
        [ ! -L /var/lib/systemd/linger/devops ]
        [ ! -e "/etc/systemd/system/user@${uid}.service.d/50-podman-devops.conf" ]
        [ ! -L "/etc/systemd/system/user@${uid}.service.d/50-podman-devops.conf" ]
        [ ! -e "/etc/systemd/system/user-${uid}.slice.d/50-podman-devops.conf" ]
        [ ! -L "/etc/systemd/system/user-${uid}.slice.d/50-podman-devops.conf" ]
        ! systemctl is-active --quiet "user@${uid}.service"
        devops_processes=$(ps -U "$uid" -o comm=)
        ! printf "%s\n" "$devops_processes" | grep -Eq "^(pipewire|pipewire-pulse|wireplumber|mako|gpg-agent|ssh-agent|dbus-broker|dbus-daemon|hyprpolkitagen|xdg-desktop-por)$"
        for runtime_user_state in bus systemd
        do
          [ ! -e "/run/user/${uid}/${runtime_user_state}" ]
          [ ! -L "/run/user/${uid}/${runtime_user_state}" ]
        done
        [ "$(stat -c "%U:%G:%a" /run/podman-devops)" = "devops:devops:710" ]
        for unit in podman-devops.service podman-devops.socket podman-devops-restart.service
        do
          path="/etc/systemd/system/$unit"
          [ -f "$path" ]
          [ ! -L "$path" ]
          [ "$(stat -c "%u:%g:%a" "$path")" = "0:0:644" ]
        done
        grep -Fxq "User=devops" /etc/systemd/system/podman-devops.service
        grep -Fxq "Group=devops" /etc/systemd/system/podman-devops.service
        grep -Fxq "Environment=HOME=/nonexistent" /etc/systemd/system/podman-devops.service
        grep -Fxq "Environment=XDG_RUNTIME_DIR=/run/podman-devops" /etc/systemd/system/podman-devops.service
        grep -Fxq "Environment=XDG_DATA_HOME=/pool/podman/xdg-data" /etc/systemd/system/podman-devops.service
        grep -Fxq "Environment=XDG_CACHE_HOME=/pool/podman/xdg-cache" /etc/systemd/system/podman-devops.service
        grep -Fxq "ExecStartPre=+/usr/local/libexec/podman-devops-host verify-start" /etc/systemd/system/podman-devops.service
        ! grep -Eq "(/data/accounts/devops|/run/user/|^Environment=DBUS_SESSION_BUS_ADDRESS=|loginctl|systemctl --user|user@[0-9])" /etc/systemd/system/podman-devops.service
        grep -Fxq "ListenStream=/run/podman-devops/podman.sock" /etc/systemd/system/podman-devops.socket
        [ "$(readlink /etc/systemd/system/sockets.target.wants/podman-devops.socket)" = ../podman-devops.socket ]
        [ "$(readlink /etc/systemd/system/multi-user.target.wants/podman-devops-bootstrap.service)" = ../podman-devops-bootstrap.service ]
        [ "$(readlink /etc/systemd/system/multi-user.target.wants/podman-devops-restart.service)" = ../podman-devops-restart.service ]
      ' sh
  fi
  if [ -n "$desktop_account_home" ]; then
    check_command desktop-whisper-perl-module-imports \
      /usr/sbin/runuser --user "$desktop_account_user" -- \
      /usr/bin/env -i PATH=/usr/local/bin:/usr/bin:/bin HOME="$desktop_account_home" \
      /usr/bin/perl -I/usr/local/lib/perl5/site_perl/whisper \
      -MWhisperMode::Audio -MWhisperMode::State -MWhisperMode::Systemd -e 1
    if [ -x /usr/local/libexec/managed-external-software-notify ]; then
      check_command desktop-external-software-perl-module-imports \
        /usr/sbin/runuser --user "$desktop_account_user" -- \
        /usr/bin/env -i PATH=/usr/local/bin:/usr/bin:/bin HOME="$desktop_account_home" \
        /usr/bin/perl -I/usr/local/lib/perl5/site_perl/external-managed-software \
        -MExternalSoftware::Servicing::CLI -e 1
    fi
  fi

  for retired_desktop_path in \
    /etc/environment.d/90-labwc-session.conf \
    /etc/skel-desktop/.config/systemd/user/dbus-broker.service.d/10-broker-hardening.conf \
    /etc/skel-desktop/.config/systemd/user/xdg-desktop-portal-xapp.service.d/10-labwc-session.conf \
    /etc/systemd/user/labwc-kwallet-portal.service
  do
    check_absent_path "desktop-retired-path-${retired_desktop_path}" "$retired_desktop_path"
  done
  for account_local_package_dropin in \
    filter-chain.service \
    foot-server.service \
    foot-server.socket \
    hyprpolkitagent.service \
    mako.service \
    pipewire.service \
    pipewire-pulse.service \
    pipewire.socket \
    pipewire-pulse.socket \
    wayscriber.service \
    wireplumber.service \
    xdg-desktop-portal.service \
    xdg-desktop-portal-gtk.service \
    xdg-desktop-portal-wlr.service \
    xdg-desktop-portal-lxqt.service
  do
    check_absent_path \
      "desktop-account-local-package-dropin-${account_local_package_dropin}" \
      "/etc/skel-desktop/.config/systemd/user/${account_local_package_dropin}.d/10-labwc-session.conf"
  done

  if [ -n "$desktop_account_home" ]; then
    for desktop_user_unit_path in \
      .gnupg/gpg-agent.conf \
      .config/systemd/user/labwc-session.target \
      .config/systemd/user/labwc-health-notify.service \
      .config/systemd/user/labwc-health-notify.path \
      .config/systemd/user/labwc-health-notify.timer \
      .config/systemd/user/labwc-plans.service \
      .config/systemd/user/labwc-adb-server.service \
      .config/systemd/user/llama-server.service \
      .config/systemd/user/labwc-calendar-sync.service \
      .config/systemd/user/labwc-calendar-sync.timer \
      .config/systemd/user/labwc-sync-application-launchers.service \
      .config/systemd/user/labwc-sync-application-launchers.path \
      .config/systemd/user/labwc-kwallet-portal.service \
      .config/systemd/user/labwc-mute-default-microphone.service \
      .config/systemd/user/labwc-output-watch.service \
      .config/systemd/user/swaybg.service \
      .config/systemd/user/swayidle.service \
      .config/systemd/user/kanshi.service \
      .config/systemd/user/crystal-dock.service \
      .config/systemd/user/waybar.service \
      .config/systemd/user/waybar.service.d/20-tray-compat.conf \
      .local/share/dbus-1/services/org.freedesktop.secrets.service \
      .config/systemd/user/labwc-session.target.wants/labwc-output-watch.service \
      .config/systemd/user/labwc-session.target.wants/swaybg.service \
      .config/systemd/user/labwc-session.target.wants/kanshi.service \
      .config/systemd/user/labwc-session.target.wants/swayidle.service \
      .config/systemd/user/labwc-session.target.wants/crystal-dock.service \
      .config/systemd/user/labwc-session.target.wants/labwc-mute-default-microphone.service \
      .config/systemd/user/labwc-session.target.wants/labwc-kwallet-portal.service \
      .config/systemd/user/labwc-session.target.wants/labwc-plans.service \
      .config/systemd/user/labwc-session.target.wants/labwc-sync-application-launchers.service \
      .config/systemd/user/labwc-session.target.wants/labwc-sync-application-launchers.path \
      .config/systemd/user/labwc-session.target.wants/foot-server.socket \
      .config/systemd/user/labwc-session.target.wants/mako.service \
      .config/systemd/user/labwc-session.target.wants/filter-chain.service \
      .config/systemd/user/labwc-session.target.wants/labwc-calendar-sync.timer \
      .config/systemd/user/labwc-session.target.wants/wayscriber.service \
      .config/systemd/user/labwc-session.target.wants/hyprpolkitagent.service \
      .config/systemd/user/labwc-session.target.wants/xdg-desktop-portal.service \
      .config/systemd/user/labwc-session.target.wants/xdg-desktop-portal-gtk.service \
      .config/systemd/user/labwc-session.target.wants/xdg-desktop-portal-wlr.service \
      .config/systemd/user/labwc-session.target.wants/xdg-desktop-portal-lxqt.service
    do
      check_path \
        "desktop-user-unit-${desktop_user_unit_path}" \
        "${desktop_account_home}/${desktop_user_unit_path}"
    done
    for desktop_account_config_path in \
      .config/btop/btop.conf \
      .config/fzf/default-opts
    do
      check_path \
        "desktop-user-config-${desktop_account_config_path}" \
        "${desktop_account_home}/${desktop_account_config_path}"
    done
    check_absent_path \
      desktop-user-unit-dbus-broker-local-hardening-absent \
      "${desktop_account_home}/.config/systemd/user/dbus-broker.service.d/10-broker-hardening.conf"
    for independent_audio_unit in \
      pipewire.service \
      pipewire-pulse.service \
      pipewire.socket \
      pipewire-pulse.socket \
      wireplumber.service
    do
      check_absent_path \
        "desktop-audio-session-dropin-${independent_audio_unit}-absent" \
        "/etc/systemd/user/${independent_audio_unit}.d/10-labwc-session.conf"
      check_absent_path \
        "desktop-audio-session-link-${independent_audio_unit}-absent" \
        "${desktop_account_home}/.config/systemd/user/labwc-session.target.wants/${independent_audio_unit}"
    done
    unset independent_audio_unit
    check_absent_path \
      desktop-user-unit-xapp-portal-dropin-absent \
      "${desktop_account_home}/.config/systemd/user/xdg-desktop-portal-xapp.service.d/10-labwc-session.conf"
    for account_local_package_dropin in \
      filter-chain.service \
      foot-server.service \
      foot-server.socket \
      hyprpolkitagent.service \
      mako.service \
      pipewire.service \
      pipewire-pulse.service \
      pipewire.socket \
      pipewire-pulse.socket \
      wayscriber.service \
      wireplumber.service \
      xdg-desktop-portal.service \
      xdg-desktop-portal-gtk.service \
      xdg-desktop-portal-wlr.service \
      xdg-desktop-portal-lxqt.service
    do
      check_absent_path \
        "desktop-user-package-dropin-${account_local_package_dropin}-absent" \
        "${desktop_account_home}/.config/systemd/user/${account_local_package_dropin}.d/10-labwc-session.conf"
    done
    check_absent_path \
      desktop-user-unit-managed-external-software-notify.service-enable-absent \
      "${desktop_account_home}/.config/systemd/user/labwc-session.target.wants/managed-external-software-notify.service"
    check_absent_path \
      desktop-user-unit-llama-server.service-enable-absent \
      "${desktop_account_home}/.config/systemd/user/labwc-session.target.wants/llama-server.service"

    for optional_desktop_user_unit in \
      managed-external-software-notify.service \
      managed-external-software-notify.path \
      whisper-record.service \
      whisper-transcribe.service \
      whisper-server.service
    do
      [ -r "/etc/skel-desktop/.config/systemd/user/${optional_desktop_user_unit}" ] || continue
      check_path \
        "desktop-user-unit-${optional_desktop_user_unit}" \
        "${desktop_account_home}/.config/systemd/user/${optional_desktop_user_unit}"
    done
    if [ -r /etc/skel-desktop/.config/systemd/user/whisper-server.service ]; then
      check_path \
        desktop-user-unit-whisper-server-enable \
        "${desktop_account_home}/.config/systemd/user/labwc-session.target.wants/whisper-server.service"
    fi
    if [ -r /etc/skel-desktop/.config/systemd/user/managed-external-software-notify.path ]; then
      check_path \
        desktop-user-unit-managed-external-software-notify.path-enable \
        "${desktop_account_home}/.config/systemd/user/labwc-session.target.wants/managed-external-software-notify.path"
    fi
  fi

  if [ ! -e /usr/share/backgrounds/desktop/wallpapers.tar.gz ]; then
    record "PASS desktop-wallpaper-archive-not-installed"
  else
    record "FAIL desktop-wallpaper-archive-not-installed"
    log_line validation error desktop "wallpaper_archive_installed=true"
    failures=$((failures + 1))
  fi

  for desktop_command in \
    labwc \
    gtkgreet \
    greetd-power-action \
    labwc-greeter-output \
    labwc-greeter-power \
    labwc-greeter-session \
    labwc-session \
    labwc-wallpaper-save \
    labwc-admin-action \
    labwc-calendar \
    labwc-ocr \
    labwc-logout \
    labwc-fuzzel \
    labwc-computer-management \
    labwc-ai-copilots \
    labwc-ai-copilots-action \
    labwc-display-configuration \
    labwc-users-groups-menu \
    labwc-adb-menu \
    labwc-adb-action \
    labwc-maintenance-menu \
    labwc-podman-menu \
    labwc-external-drives \
    labwc-security-action \
    labwc-system-action \
    labwc-recovery-action \
    labwc-network-control-menu \
    labwc-network-control-action \
    labwc-firewall-menu \
    labwc-firewall-action \
    labwc-network-scan-menu \
    labwc-network-scan-action \
    labwc-run \
    labwc-terminal \
    labwc-bluetooth \
    labwc-remote-desktop \
    labwc-freerdp-askpass \
    labwc-brightness-control \
    labwc-power-settings \
    labwc-keyboard-layout \
    labwc-power-menu \
    labwc-health-notify \
    labwc-qbittorrent \
    labwc-wayscriber-toggle \
    wayscriber \
    notify-send \
    sendmail \
    dbus-update-activation-environment \
    desktop-file-validate \
    khal \
    qt6ct \
    tesseract \
    todoman \
    vdirsyncer
  do
    check_desktop_command_required "$desktop_command"
  done

  if desktop-file-validate \
       /usr/share/applications/computer-management.desktop \
       /usr/share/applications/remote-desktop-management.desktop >/dev/null 2>&1; then
    record "PASS desktop-management-launchers"
  else
    record "FAIL desktop-management-launchers"
    log_line validation error desktop "management_desktop_entry_invalid=true"
    failures=$((failures + 1))
  fi

  if grep -q "dbus-run-session" /usr/local/bin/labwc-greeter-session /usr/local/bin/labwc-session 2>/dev/null; then
    record "FAIL desktop-dbus-broker-wrappers: dbus-run-session present"
    log_line validation error desktop "dbus_run_session_present=true"
    failures=$((failures + 1))
  else
    record "PASS desktop-dbus-broker-wrappers"
  fi

  if desktop_renderer_policy_matches; then
    record "PASS desktop-renderer-policy"
  else
    record "FAIL desktop-renderer-policy"
    log_line validation error desktop "renderer_policy_mismatch=true"
    failures=$((failures + 1))
  fi

  if desktop_icon_theme_policy_matches; then
    record "PASS desktop-icon-theme-policy"
  else
    record "FAIL desktop-icon-theme-policy"
    log_line validation error desktop "icon_theme_policy_mismatch=true"
    failures=$((failures + 1))
  fi

  if grep -Eq '^auth[[:space:]]+required[[:space:]]+pam_permit\.so$' /etc/pam.d/greetd-greeter 2>/dev/null &&
     grep -Eq '^account[[:space:]]+required[[:space:]]+pam_permit\.so$' /etc/pam.d/greetd-greeter 2>/dev/null &&
     grep -q '^account  sufficient pam_usertype\.so issystem$' /etc/pam.d/systemd-user 2>/dev/null &&
     grep -q 'pam_systemd\.so class=greeter type=wayland desktop=labwc' /etc/pam.d/greetd-greeter 2>/dev/null &&
     ! grep -q 'pam_systemd\.so class=user-light' /etc/pam.d/greetd-greeter 2>/dev/null &&
     ! grep -Eq '^@include common-(auth|account)$|pam_nologin\.so' /etc/pam.d/greetd-greeter 2>/dev/null; then
    record "PASS desktop-greeter-pam-session"
  else
    record "FAIL desktop-greeter-pam-session"
    log_line validation error desktop "greeter_pam_session_invalid=true"
    failures=$((failures + 1))
  fi

  polkit_rules_ok=true
  for polkit_rule in \
    00-admin-identities.rules \
    05-active-local-gate.rules \
    10-greetd-power.rules \
    10-pkexec.rules \
    20-login1-power.rules \
    40-networkmanager.rules \
    50-usb-policy.rules \
    55-software-management.rules \
    60-system-services-identity.rules \
    70-hardware-peripherals.rules
  do
    polkit_rule_path="/etc/polkit-1/rules.d/${polkit_rule}"
    if [ ! -r "$polkit_rule_path" ] ||
       grep -q 'subject\.seat' "$polkit_rule_path" 2>/dev/null; then
      polkit_rules_ok=false
      break
    fi
  done
  if [ "$polkit_rules_ok" = true ] &&
     grep -q 'lookupString(action, "drive.removable") === "true"' \
       /etc/polkit-1/rules.d/50-usb-policy.rules 2>/dev/null &&
     grep -q 'lookupString(action, "drive.removable.bus") === "usb"' \
       /etc/polkit-1/rules.d/50-usb-policy.rules 2>/dev/null &&
     ! grep -q '"org.freedesktop.udisks2.filesystem-unmount": true' \
       /etc/polkit-1/rules.d/50-usb-policy.rules 2>/dev/null &&
     ! grep -q '"org.freedesktop.udisks2.drive-eject": true' \
       /etc/polkit-1/rules.d/50-usb-policy.rules 2>/dev/null; then
    record "PASS desktop-polkit-policy"
  else
    record "FAIL desktop-polkit-policy"
    log_line validation error desktop "polkit_policy_invalid=true"
    failures=$((failures + 1))
  fi

  if grep -q '^export LABWC_SESSION_OWNER=greeter$' /usr/local/bin/labwc-greeter-session 2>/dev/null &&
     grep -q '^export LABWC_UPDATE_ACTIVATION_ENV=0$' /usr/local/bin/labwc-greeter-session 2>/dev/null &&
     grep -q '^export GTK_USE_PORTAL=0$' /usr/local/bin/labwc-greeter-session 2>/dev/null &&
     grep -q '^export GIO_USE_PORTALS=0$' /usr/local/bin/labwc-greeter-session 2>/dev/null &&
     grep -q '^unset WAYLAND_DISPLAY SWAYSOCK LABWC_PID$' /usr/local/bin/labwc-greeter-session 2>/dev/null &&
     grep -q "^labwc_x11_environment_names='DISPLAY XAUTHORITY WLR_XWAYLAND XWAYLAND XWAYLAND_PATH XWAYLAND_NO_GLAMOR XWAYLAND_FORCE_SCALE XWAYLAND_RESTART_DELAY _XWAYLAND_GLOBAL_OUTPUT_SCALE WINDOWID SESSION_MANAGER DESKTOP_STARTUP_ID'$" /usr/local/bin/labwc-greeter-session 2>/dev/null &&
     grep -q 'unset \$labwc_x11_environment_names' /usr/local/bin/labwc-greeter-session 2>/dev/null &&
     ! grep -q 'systemctl --user' /usr/local/bin/labwc-greeter-session 2>/dev/null &&
     ! grep -q 'dbus-update-activation-environment' /usr/local/bin/labwc-greeter-session 2>/dev/null &&
     grep -q '^greeter_asset_dir=/usr/local/share/labwc-greeter$' /usr/local/bin/labwc-greeter-session 2>/dev/null &&
     grep -q '^greeter_client=/usr/local/libexec/labwc-greeter-client$' /usr/local/bin/labwc-greeter-session 2>/dev/null &&
     grep -q '^greeter_autostart="\${greeter_config_dir}/autostart"$' /usr/local/bin/labwc-greeter-session 2>/dev/null &&
     grep -q '^exit 0$' /usr/local/share/labwc-greeter/autostart 2>/dev/null &&
     ! grep -q 'labwc-output-watch' /usr/local/bin/labwc-greeter-session 2>/dev/null &&
     grep -q 'labwc-greeter-output --configure' /usr/local/libexec/labwc-greeter-client 2>/dev/null &&
     grep -q 'labwc-greeter-output --watch' /usr/local/libexec/labwc-greeter-client 2>/dev/null &&
     grep -q "^labwc_x11_environment_names='DISPLAY XAUTHORITY WLR_XWAYLAND XWAYLAND XWAYLAND_PATH XWAYLAND_NO_GLAMOR XWAYLAND_FORCE_SCALE XWAYLAND_RESTART_DELAY _XWAYLAND_GLOBAL_OUTPUT_SCALE WINDOWID SESSION_MANAGER DESKTOP_STARTUP_ID'$" /usr/local/libexec/labwc-greeter-client 2>/dev/null &&
     grep -q 'unset \$labwc_x11_environment_names' /usr/local/libexec/labwc-greeter-client 2>/dev/null &&
     grep -q '^trap cleanup_greeter_children EXIT$' /usr/local/libexec/labwc-greeter-client 2>/dev/null &&
     grep -q 'labwc-greeter-power' /usr/local/libexec/labwc-greeter-client 2>/dev/null &&
     grep -q 'org.freedesktop.login1.power-off' /etc/polkit-1/rules.d/10-greetd-power.rules 2>/dev/null &&
     grep -q 'org.freedesktop.login1.reboot' /etc/polkit-1/rules.d/10-greetd-power.rules 2>/dev/null &&
     grep -q '^/usr/bin/gtkgreet --layer-shell -s /etc/greetd/gtkgreet.css -c "\$LABWC_GREETER_SESSION_COMMAND"$' /usr/local/libexec/labwc-greeter-client 2>/dev/null; then
    record "PASS desktop-greeter-labwc-gtkgreet-command"
  else
    record "FAIL desktop-greeter-labwc-gtkgreet-command"
    log_line validation error desktop "greeter_command_mismatch=true"
    failures=$((failures + 1))
  fi

  if grep -q '^ConditionEnvironment=LABWC_SESSION_OWNER=desktop$' /etc/skel-desktop/.config/systemd/user/labwc-session.target 2>/dev/null &&
     ! grep -q '^BindsTo=graphical-session.target$' /etc/skel-desktop/.config/systemd/user/labwc-session.target 2>/dev/null &&
     ! grep -q '^Wants=graphical-session.target$' /etc/skel-desktop/.config/systemd/user/labwc-session.target 2>/dev/null &&
     ! grep -q '^After=graphical-session.target$' /etc/skel-desktop/.config/systemd/user/labwc-session.target 2>/dev/null &&
     grep -q '^ConditionEnvironment=LABWC_SESSION_OWNER=desktop$' /etc/systemd/user/xdg-desktop-portal.service.d/10-labwc-session.conf 2>/dev/null &&
     grep -q '^ConditionEnvironment=LABWC_SESSION_OWNER=desktop$' /etc/systemd/user/hyprpolkitagent.service.d/10-labwc-session.conf 2>/dev/null &&
     grep -Fq 'if [ "${LABWC_SESSION_OWNER:-}" != desktop ]; then' /usr/local/bin/labwc-autostart 2>/dev/null; then
    record "PASS desktop-session-owner-gating"
  else
    record "FAIL desktop-session-owner-gating"
    log_line validation error desktop "session_owner_gating_missing=true"
    failures=$((failures + 1))
  fi

  for desktop_command in \
    fuzzel \
    waybar \
    mako \
    makoctl \
    notify-send \
    labwc-health-notify \
    kanshi \
    eglinfo \
    es2_info \
    thunar \
    nnn \
    featherpad \
    focuswriter \
    gnote \
    liferea \
    gnumeric \
    kdiff3 \
    micro \
    mpv \
    nvim \
    qalculate-qt \
    qimgv \
    retroarch \
    vim \
    xournalpp \
    zathura \
    xarchiver \
    nwg-look \
    task \
    taskwarrior-tui \
    foot \
    footclient \
    kitty \
    brightnessctl \
    bluetoothctl \
    btmgmt \
    rfkill \
    powerprofilesctl \
    xdg-terminal-exec \
    crystal-dock
  do
    check_desktop_command_optional "$desktop_command"
  done
  check_desktop_command_optional_any sdl-freerdp sdl-freerdp3

  if command -v systemctl >/dev/null 2>&1; then
    capture desktop-units.txt systemctl status greetd.service seatd.service NetworkManager.service pipewire.socket pipewire-pulse.socket wireplumber.service xdg-desktop-portal.service --no-pager --lines=40
    log_line validation info desktop "desktop_unit_status_collected=true"
  fi
  if [ -n "${WAYLAND_DISPLAY:-}" ] &&
     [ -n "${XDG_RUNTIME_DIR:-}" ] &&
     [ -S "${XDG_RUNTIME_DIR}/${WAYLAND_DISPLAY}" ]; then
    if command -v eglinfo >/dev/null 2>&1; then
      capture desktop-eglinfo.txt eglinfo -B
    fi
    if command -v es2_info >/dev/null 2>&1; then
      capture desktop-es2-info.txt es2_info
    fi
    if command -v wlr-randr >/dev/null 2>&1; then
      capture desktop-wlr-randr.txt wlr-randr
    fi
  else
    record "SKIP desktop-session-graphics-capture: no active Wayland session"
    log_line validation info desktop "graphics_capture_skipped=no_active_wayland_session"
  fi
}

record "timestamp=$(timestamp)"
record "hostname=$(hostname 2>/dev/null || printf unknown)"
record "kernel=$(uname -r 2>/dev/null || printf unknown)"

check_path installer-log /var/lib/installer-state/installer.log

check_path initramfs-health-log-dir /var/lib/installer-state/logs/initramfs
check_path initramfs-health-init-top-log /var/lib/installer-state/logs/initramfs/01-init-top.log
check_path initramfs-health-init-bottom-log /var/lib/installer-state/logs/initramfs/07-init-bottom.log

if command -v findmnt >/dev/null 2>&1; then
  check_command findmnt-verify findmnt --verify
  check_command root-mounted findmnt /
  if [ -d /sys/firmware/efi ]; then
    check_command efi-vfat-mounted findmnt -n -t vfat /boot/efi
  fi
fi

if command -v coredumpctl >/dev/null 2>&1; then
  capture coredump-summary.txt coredumpctl list --no-pager
fi

if command -v systemctl >/dev/null 2>&1; then
  system_state=$(systemctl is-system-running 2>/dev/null || true)
  record "system_state=${system_state:-unknown}"
  case "$system_state" in
    degraded|failed|maintenance|emergency)
      log_line validation error systemd "system_state=${system_state}"
      failures=$((failures + 1))
      ;;
  esac
  failed_units=$(systemctl --failed --no-legend --plain 2>/dev/null | sed -n '1,20p' || true)
  if [ -n "$failed_units" ]; then
    record "FAIL failed-units-present"
    printf '%s\n' "$failed_units" >>"$VALIDATION_FILE"
    log_line validation error systemd "failed_units_present=true"
    failures=$((failures + 1))
  else
    record "PASS failed-units-absent"
  fi
fi

if [ -x /usr/local/libexec/dbus-broker-check ]; then
  check_command dbus-broker-system timeout --kill-after=2s 60s /usr/local/libexec/dbus-broker-check --system --wait
fi
validate_desktop_role

if command -v mokutil >/dev/null 2>&1; then
  capture secureboot-state.txt mokutil --sb-state
  capture mok-enrollment.txt mokutil --list-enrolled
  log_line enrollment info secureboot "mokutil_collected=true"
else
  log_line enrollment warn secureboot "mokutil=missing"
fi

if command -v systemctl >/dev/null 2>&1; then
  capture security-baseline-units.txt systemctl status apparmor.service apparmor-managed-modes.service auditd.service nftables.service ssh.service sshd.service --no-pager --lines=40
  log_line security-baseline info systemd "security_unit_status_collected=true"
fi

if [ -x /usr/local/libexec/apparmor-managed-modes-run ]; then
  # firstboot.service is ordered after the reconciliation unit, so source and
  # loaded modes must already agree rather than being deferred as a boot race.
  check_command apparmor-managed-modes /usr/local/libexec/apparmor-managed-modes-run --check
  check_command apparmor-managed-modes-loaded /usr/local/libexec/apparmor-managed-modes-run --check-loaded
fi
if command -v aa-status >/dev/null 2>&1; then
  capture apparmor-status.json aa-status --pretty-json
fi

if [ -r /boot/grub/grub.cfg ]; then
  record "PASS grub-cfg-readable"
else
  record "FAIL grub-cfg-readable: /boot/grub/grub.cfg"
  log_line validation error bootloader "missing=/boot/grub/grub.cfg"
  failures=$((failures + 1))
fi

if [ "$failures" -eq 0 ]; then
  record "validation_status=pass"
  log_line validation info validation "validation_status=pass"
  exit 0
fi

record "validation_status=fail failures=${failures}"
log_line validation error validation "validation_status=fail failures=${failures}"
exit 1
