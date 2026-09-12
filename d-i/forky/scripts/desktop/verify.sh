#!/bin/sh
# Labwc desktop target verification helpers.

desktop_verify_required_commands() {
  # shellcheck disable=SC2016
  run_in_target "verify Labwc desktop commands" /bin/sh -c '
set -eu
required_checked=0
optional_checked=0
optional_missing=

check_required() {
  cmd=$1
  command -v "$cmd" >/dev/null 2>&1 || {
    printf "fatal: required desktop command is missing: %s\n" "$cmd" >&2
    exit 1
  }
  required_checked=$((required_checked + 1))
}

check_optional() {
  cmd=$1
  if command -v "$cmd" >/dev/null 2>&1; then
    optional_checked=$((optional_checked + 1))
    return 0
  fi
  optional_missing="${optional_missing:+$optional_missing }$cmd"
}

check_optional_alternative() {
  primary_cmd=$1
  shift
  for cmd in "$primary_cmd" "$@"; do
    if command -v "$cmd" >/dev/null 2>&1; then
      optional_checked=$((optional_checked + 1))
      return 0
    fi
  done
  optional_missing="${optional_missing:+$optional_missing }$primary_cmd"
}

for cmd in \
  browser-devtools \
  labwc \
  cage \
  slirp4netns \
  gtkgreet \
  greetd-power-action \
  labwc-greeter-output \
  labwc-greeter-power \
  labwc-greeter-session \
  labwc-session \
  labwc-autostart \
  labwc-admin-action \
  labwc-calendar \
  labwc-ocr \
  labwc-logout \
  labwc-fuzzel \
  labwc-computer-management \
  labwc-ai-copilots \
  labwc-ai-copilots-action \
  labwc-digital-assets \
  labwc-digital-assets-action \
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
  labwc-remote-desktop \
  labwc-freerdp-askpass \
  labwc-run \
  labwc-terminal \
  labwc-bluetooth \
  labwc-brightness-control \
  labwc-power-settings \
  labwc-power-menu \
  wayland-info \
  labwc-managed-app \
  labwc-electron-app \
  labwc-wayland-app \
  labwc-qbittorrent \
  labwc-sync-application-launchers \
  labwc-keyboard-layout \
  labwc-capture \
  labwc-wayscriber-toggle \
  satty \
  wayscriber \
  systemctl \
  systemd-run \
  dbus-update-activation-environment \
  desktop-file-validate \
  grim \
  slurp \
  wf-recorder \
  wl-copy \
  khal \
  keepassxc \
  recoll \
  recollindex \
  fido2-token \
  mail \
  pkexec \
  eject \
  findmnt \
  lsblk \
  sync \
  udisksctl \
  lynis \
  rkhunter \
  chkrootkit \
  systemd-analyze \
  fwupdmgr \
  spectre-meltdown-checker \
  debsecan \
  debsums \
  ss \
  nmap \
  lua5.5 \
  luac5.5 \
  dumpcap \
  tshark \
  tcpdump \
  wireshark \
  clamscan \
  freshclam \
  fangfrisch \
  visudo \
  aa-easyprof \
  aa-enabled \
  aa-features-abi \
  aa-audit \
  aa-autodep \
  aa-genprof \
  aa-logprof \
  aa-remove-unknown \
  aa-unconfined \
  logrotate \
  rsyslogd \
  ip \
  ifup \
  ifdown \
  ifquery \
  nmcli \
  perl \
  python3 \
  flock \
  todoman \
  task \
  taskwarrior-tui \
  vdirsyncer \
  tesseract \
  notify-send \
  sendmail
do
  check_required "$cmd"
done

for cmd in \
  crystal-dock \
  zsh \
  starship \
  btop \
  brightnessctl \
  bluetoothctl \
  btmgmt \
  rfkill \
  ncdu \
  nmtui \
  fzf \
  wlr-randr \
  wlopm \
  wdisplays \
  waybar \
  kanshi \
  bwrap \
  eglinfo \
  es2_info \
  vainfo \
  xdg-dbus-proxy \
  foot \
  footclient \
  kitty \
  fuzzel \
  labwc-health-notify \
  mako \
  makoctl \
  swaylock \
  swaybg \
  swayidle \
  wpctl \
  thunar \
  nnn \
  featherpad \
  focuswriter \
  gnote \
  liferea \
  gnumeric \
  kdiff3 \
  micro \
  nvim \
  labwc-tweaks \
  qalculate-qt \
  retroarch \
  qt6ct \
  vim \
  xournalpp \
  qimgv \
  zathura \
  xarchiver \
  nwg-look \
  pavucontrol \
  pwsh \
  powerprofilesctl \
  xdg-terminal-exec \
  ikhal \
  pipewire \
  wireplumber \
  wsdd
do
  check_optional "$cmd"
done
check_optional_alternative sdl-freerdp sdl-freerdp3

printf "desktop_command_verification required_checked=%s optional_checked=%s optional_missing=%s\n" \
  "$required_checked" \
  "$optional_checked" \
  "${optional_missing:-none}"
' sh
}

desktop_verify_staged_files() {
  # shellcheck disable=SC2016
  run_in_target "verify Labwc desktop staged file metadata" /bin/sh -c '
set -eu
fatal() {
  printf "fatal: %s\n" "$*" >&2
  exit 1
}

require_readable() {
  path=$1
  [ -r "$path" ] || fatal "staged desktop path is missing or unreadable: $path"
}

require_executable() {
  path=$1
  [ -x "$path" ] || fatal "staged desktop executable is missing: $path"
}

require_mode() {
  path=$1
  expected_mode=$2
  actual_mode=$(stat -c "%a" "$path")
  [ "$actual_mode" = "$expected_mode" ] ||
    fatal "staged desktop path mode mismatch: $path expected=$expected_mode actual=$actual_mode"
}

require_absent() {
  path=$1
  [ ! -e "$path" ] && [ ! -L "$path" ] ||
    fatal "retired desktop path is still present: $path"
}

desktop_skeleton=/etc/skel-desktop
[ -d "$desktop_skeleton" ] && [ ! -L "$desktop_skeleton" ] ||
  fatal "desktop skeleton root is missing or unsafe: $desktop_skeleton"
[ "$(stat -c "%u:%g" "$desktop_skeleton")" = 0:0 ] ||
  fatal "desktop skeleton root must be owned by root:root: $desktop_skeleton"
require_mode "$desktop_skeleton" 755
legacy_skeleton_parent=/etc/skel
legacy_skeleton_name=primary
require_absent "${legacy_skeleton_parent}/${legacy_skeleton_name}"
unset desktop_skeleton legacy_skeleton_name legacy_skeleton_parent

require_symlink_target() {
  path=$1
  expected_target=$2
  [ -L "$path" ] || fatal "managed desktop symlink is missing: $path"
  actual_target=$(readlink "$path")
  [ "$actual_target" = "$expected_target" ] ||
    fatal "managed desktop symlink target mismatch: $path expected=$expected_target actual=$actual_target"
}

readable_count=0
executable_count=0
for path in \
  /etc/default/labwc-desktop \
  /etc/pam.d/polkit-1 \
  /etc/pam.d/systemd-user \
  /etc/pam.d/greetd \
  /etc/pam.d/greetd-greeter \
  /etc/pam.d/swaylock \
  /usr/share/pam-configs/wtmpdb \
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
  /etc/fangfrisch.conf \
  /etc/apparmor/easyprof.conf \
  /etc/apparmor/logprof.conf \
  /etc/audit/plugins.d/syslog.conf \
  /etc/systemd/journald.conf.d/10-storage.conf \
  /etc/rsyslog.conf \
  /etc/rsyslog.d/15-audit.conf \
  /etc/rsyslog.d/20-auth.conf \
  /etc/rsyslog.d/25-usb.conf \
  /etc/rsyslog.d/30-apparmor.conf \
  /etc/rsyslog.d/31-apparmor-managed-modes.conf \
  /etc/rsyslog.d/35-storage.conf \
  /etc/rsyslog.d/37-whisper.conf \
  /etc/rsyslog.d/39-security-scanners.conf \
  /etc/rsyslog.d/40-nftables.conf \
  /etc/rsyslog.d/41-fuzzel.conf \
  /etc/rsyslog.d/42-adb.conf \
  /etc/rsyslog.d/43-managed-desktop-apps.conf \
  /etc/rsyslog.d/99-discard.conf \
  /etc/logrotate.conf \
  /etc/systemd/system/logrotate.timer.d/override.conf \
  /etc/logrotate.d/rsyslog \
  /etc/logrotate.d/audit \
  /etc/logrotate.d/auth \
  /etc/logrotate.d/usb \
  /etc/logrotate.d/apparmor \
  /etc/logrotate.d/apparmor-managed-modes \
  /etc/logrotate.d/storage \
  /etc/logrotate.d/whisper \
  /etc/logrotate.d/nftables \
  /etc/logrotate.d/security-notify \
  /etc/logrotate.d/security-scanners \
  /etc/logrotate.d/fuzzel \
  /etc/logrotate.d/adb \
  /etc/logrotate.d/managed-desktop-apps \
  /etc/tmpfiles.d/60-security-logs.conf \
  /etc/tmpfiles.d/65-audit-syslog.conf \
  /etc/systemd/system/rsyslog.service.d/30-managed-security-scanner-socket.conf \
  /usr/local/libexec/rsyslog-managed-security-socket \
  /etc/udev/rules.d/53-ledger-wallet.rules \
  /etc/tmpfiles.d/25-desktop-media-runtime.conf \
  /etc/systemd/system/managed-clamav-signature-update.service \
  /etc/systemd/system/managed-clamav-signature-update.timer \
  /etc/systemd/system/labwc-admin-action@.service \
  /usr/local/share/nmap/scripts/managed-admin-surface-policy.nse \
  /usr/local/share/nmap/scripts/managed-approved-services.nse \
  /usr/local/share/nmap/scripts/managed-database-exposure-policy.nse \
  /usr/local/share/nmap/scripts/managed-http-security-headers.nse \
  /usr/local/share/nmap/scripts/managed-name-resolution-policy.nse \
  /usr/local/share/nmap/scripts/managed-plaintext-service-policy.nse \
  /usr/local/share/nmap/scripts/managed-service-inventory.nse \
  /usr/local/share/nmap/scripts/managed-tls-service-policy.nse \
  /etc/xdg/mimeapps.list \
  /usr/share/glib-2.0/schemas/90-desktop-wsdd.gschema.override \
  /etc/mailname \
  /etc/aliases \
  /etc/apt/listchanges.conf \
  /etc/apt/apt.conf.d/60desktop-local-mail.conf \
  /etc/opt/chrome/policies/managed/telemetry.json \
  /etc/opt/chrome/policies/managed/security.json \
  /etc/opt/chrome/policies/managed/performance.json \
  /etc/opt/chrome/policies/recommended/defaults.json \
  /etc/chromium/policies/managed/telemetry.json \
  /etc/chromium/policies/managed/security.json \
  /etc/chromium/policies/managed/performance.json \
  /etc/chromium/policies/recommended/defaults.json \
  /etc/opt/edge/policies/managed/telemetry.json \
  /etc/opt/edge/policies/managed/security.json \
  /etc/opt/edge/policies/managed/performance.json \
  /etc/opt/edge/policies/recommended/defaults.json \
  /etc/vivaldi/policies/managed/telemetry.json \
  /etc/vivaldi/policies/managed/extensions.json \
  /etc/vivaldi/policies/managed/security.json \
  /etc/vivaldi/policies/managed/performance.json \
  /etc/vivaldi/policies/recommended/defaults.json \
  /opt/glibc/2.44-1/satty/.managed-release \
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
  /etc/skel-desktop/.config/systemd/user/labwc-plans.service \
  /etc/skel-desktop/.config/systemd/user/labwc-sync-application-launchers.service \
  /etc/skel-desktop/.config/systemd/user/labwc-sync-application-launchers.path \
  /etc/skel-desktop/.profile.d \
  /etc/systemd/system/greetd.service.d/20-labwc-vt.conf \
  /etc/systemd/system/bluetooth-controller-init.service \
  /etc/skel-desktop/.config/systemd/user/labwc-kwallet-portal.service \
  /etc/skel-desktop/.local/share/dbus-1/services/org.freedesktop.secrets.service \
  /etc/fonts/fonts.conf \
  /usr/local/share/labwc-greeter/rc.xml \
  /usr/local/share/labwc-greeter/autostart \
  /usr/share/wayland-sessions/labwc.desktop \
  /usr/share/applications/computer-management.desktop \
  /usr/share/applications/remote-desktop-management.desktop \
  /usr/local/share/applications/foot.desktop \
  /etc/skel-desktop/.config/labwc/rc.xml \
  /etc/skel-desktop/.config/labwc/menu.xml \
  /etc/skel-desktop/.config/labwc/autostart \
  /etc/skel-desktop/.config/labwc/shutdown \
  /etc/skel-desktop/.config/labwc/environment \
  /etc/skel-desktop/.config/labwc/environment.d/10-wayland.env \
  /etc/skel-desktop/.config/waypaper/config.ini \
  /etc/skel-desktop/.config/waypaper/keybindings.ini \
  /etc/skel-desktop/.config/waypaper/style.css \
  /etc/skel-desktop/.config/btop/btop.conf \
  /etc/skel-desktop/.config/fzf/default-opts \
  /etc/skel-desktop/.config/satty/config.toml \
  /etc/skel-desktop/.config/satty/overrides.css \
  /etc/skel-desktop/.config/labwc/themerc-override \
  /etc/skel-desktop/.config/Code/User/settings.json \
  /etc/skel-desktop/.config/chromium/Default/Preferences \
  /etc/skel-desktop/.config/keepassxc/keepassxc.ini \
  /etc/skel-desktop/.config/microsoft-edge/Default/Preferences \
  /etc/skel-desktop/.config/obsidian/obsidian.json \
  /etc/skel-desktop/.config/Recoll.org/recoll.ini \
  /etc/skel-desktop/.recoll/recoll.conf \
  /etc/skel-desktop/.config/vivaldi/Default/Preferences \
  /etc/skel-desktop/.config/systemd/user/labwc-session.target \
  /etc/skel-desktop/.config/systemd/user/labwc-health-notify.service \
  /etc/skel-desktop/.config/systemd/user/labwc-health-notify.path \
  /etc/skel-desktop/.config/systemd/user/labwc-health-notify.timer
do
  require_readable "$path"
  readable_count=$((readable_count + 1))
done

require_mode /etc/systemd/system/labwc-admin-action@.service 644
for background_directory in \
  /usr/share/backgrounds \
  /usr/share/backgrounds/desktop \
  /usr/share/backgrounds/login
do
  [ -d "$background_directory" ] && [ ! -L "$background_directory" ] ||
    fatal "managed background directory is missing or unsafe: $background_directory"
  require_mode "$background_directory" 755
  [ "$(stat -c "%u:%g" "$background_directory")" = 0:0 ] ||
    fatal "managed background directory is not root-owned: $background_directory"
done
unset background_directory
for background_file in \
  /usr/share/backgrounds/desktop/wallpaper-1920x1080.png \
  /usr/share/backgrounds/login/lock-1920x1080.png \
  /usr/share/backgrounds/login/welcome-1920x1080.png
do
  [ -f "$background_file" ] && [ ! -L "$background_file" ] ||
    fatal "managed background file is missing or unsafe: $background_file"
  require_mode "$background_file" 644
done
unset background_file
helper_package=$(dpkg-query -S /usr/sbin/unix_chkpwd 2>/dev/null) ||
  fatal "unix_chkpwd is not owned by an installed package"
printf "%s\n" "$helper_package" |
  grep -Eq "^libpam-modules-bin(:[^:[:space:]]+)?: /usr/sbin/unix_chkpwd$" ||
  fatal "unix_chkpwd has an unexpected package owner: $helper_package"
shadow_group_entry=$(getent group shadow) ||
  fatal "required shadow group is missing"
shadow_gid=$(printf "%s\n" "$shadow_group_entry" | cut -d: -f3)
case "$shadow_gid" in
  ""|*[!0-9]*) fatal "shadow group gid is invalid: $shadow_gid" ;;
esac
for authentication_path in /etc/shadow /usr/sbin/unix_chkpwd; do
  [ -f "$authentication_path" ] && [ ! -L "$authentication_path" ] ||
    fatal "authentication path is missing or unsafe: $authentication_path"
done
[ "$(stat -c "%u:%g:%a" /etc/shadow)" = "0:$shadow_gid:640" ] ||
  fatal "/etc/shadow must be root:shadow mode 0640"
[ "$(stat -c "%u:%g:%a" /usr/sbin/unix_chkpwd)" = "0:$shadow_gid:2755" ] ||
  fatal "/usr/sbin/unix_chkpwd must be root:shadow mode 2755"
helper_mount_options=$(findmnt -n -o OPTIONS -T /usr/sbin/unix_chkpwd) ||
  fatal "cannot resolve unix_chkpwd mount options"
case ",$helper_mount_options," in
  *,nosuid,*) fatal "unix_chkpwd resides on a nosuid mount" ;;
esac
unset authentication_path helper_mount_options helper_package shadow_gid shadow_group_entry
require_mode /etc/skel-desktop/.config/systemd 700
require_mode /etc/skel-desktop/.config/systemd/user 700
require_mode /etc/systemd/user/dbus-broker.service.d/10-broker-hardening.conf 644
for path in /etc/systemd/user/*.d; do
  [ -d "$path" ] || continue
  require_mode "$path" 755
  for dropin_path in "$path"/*.conf; do
    [ -f "$dropin_path" ] || continue
    require_mode "$dropin_path" 644
  done
done
require_mode /etc/skel-desktop/.gnupg 700
require_mode /etc/skel-desktop/.gnupg/gpg-agent.conf 600
for path in /etc/skel-desktop/.config/systemd/user/*.d; do
  [ -d "$path" ] || continue
  require_mode "$path" 700
done
require_mode /etc/skel-desktop/.local/share/dbus-1 755
require_mode /etc/skel-desktop/.local/share/dbus-1/services 755
for path in /etc/skel-desktop/.local/share/dbus-1/services/*.service; do
  require_mode "$path" 644
done

for path in \
  /etc/opt/chrome/policies/managed/telemetry.json \
  /etc/opt/chrome/policies/managed/security.json \
  /etc/opt/chrome/policies/managed/performance.json \
  /etc/opt/chrome/policies/recommended/defaults.json \
  /etc/chromium/policies/managed/telemetry.json \
  /etc/chromium/policies/managed/security.json \
  /etc/chromium/policies/managed/performance.json \
  /etc/chromium/policies/recommended/defaults.json \
  /etc/opt/edge/policies/managed/telemetry.json \
  /etc/opt/edge/policies/managed/security.json \
  /etc/opt/edge/policies/managed/performance.json \
  /etc/opt/edge/policies/recommended/defaults.json \
  /etc/vivaldi/policies/managed/telemetry.json \
  /etc/vivaldi/policies/managed/extensions.json \
  /etc/vivaldi/policies/managed/security.json \
  /etc/vivaldi/policies/managed/performance.json \
  /etc/vivaldi/policies/recommended/defaults.json
do
  require_mode "$path" 644
done

require_mode /usr/local/bin/browser-devtools 755
require_mode /usr/local/libexec/install-browser-imports 755
require_mode /usr/local/share/browser-imports 700
require_mode /usr/local/share/browser-imports/noscript_data.txt 600
require_mode /usr/local/share/browser-imports/my-ubol-settings.json 600
require_mode /usr/local/share/browser-imports/PrivacyBadger_user_data-9_6_2026_1_50_43_PM.json 600
require_mode /usr/local/share/browser-imports/bookmark-coverage.json 600
require_mode /usr/local/share/browser-imports/BROWSER-IMPORTS.md 600

require_mode /etc/skel-desktop/.config/keepassxc 700
require_mode /etc/skel-desktop/.config/keepassxc/keepassxc.ini 600
require_mode /etc/skel-desktop/.config/Code/User/settings.json 600
require_mode /etc/skel-desktop/.config/chromium/Default/Preferences 600
require_mode /etc/skel-desktop/.config/microsoft-edge/Default/Preferences 600
require_mode /etc/skel-desktop/.config/obsidian 700
require_mode /etc/skel-desktop/.config/obsidian/obsidian.json 600
require_mode /etc/skel-desktop/.config/vivaldi/Default/Preferences 600
require_mode /etc/skel-desktop/.config/Recoll.org 700
require_mode /etc/skel-desktop/.config/Recoll.org/recoll.ini 600
require_mode /etc/skel-desktop/.recoll 700
require_mode /etc/skel-desktop/.cache 700
require_mode /etc/skel-desktop/.cache/recoll 700
require_readable /etc/skel-desktop/Syncthing/.stignore
require_mode /etc/skel-desktop/Syncthing/.stignore 600
readable_count=$((readable_count + 1))

for path in \
  /etc/skel-desktop/Syncthing/obsidian-md/.obsidian/app.json \
  /etc/skel-desktop/Syncthing/obsidian-md/.obsidian/appearance.json \
  /etc/skel-desktop/Syncthing/obsidian-md/.obsidian/backlink.json \
  /etc/skel-desktop/Syncthing/obsidian-md/.obsidian/bookmarks.json \
  /etc/skel-desktop/Syncthing/obsidian-md/.obsidian/command-palette.json \
  /etc/skel-desktop/Syncthing/obsidian-md/.obsidian/community-plugins.json \
  /etc/skel-desktop/Syncthing/obsidian-md/.obsidian/core-plugins.json \
  /etc/skel-desktop/Syncthing/obsidian-md/.obsidian/daily-notes.json \
  /etc/skel-desktop/Syncthing/obsidian-md/.obsidian/graph.json \
  /etc/skel-desktop/Syncthing/obsidian-md/.obsidian/hotkeys.json \
  /etc/skel-desktop/Syncthing/obsidian-md/.obsidian/templates.json \
  /etc/skel-desktop/Syncthing/obsidian-md/.obsidian/types.json \
  /etc/skel-desktop/Syncthing/obsidian-md/.obsidian/snippets/managed-ux.css \
  /etc/skel-desktop/Syncthing/obsidian-md/.obsidian/themes/evergreen-notes/manifest.json \
  /etc/skel-desktop/Syncthing/obsidian-md/.obsidian/themes/evergreen-notes/theme.css \
  /etc/skel-desktop/Syncthing/obsidian-md/archive/index.md \
  /etc/skel-desktop/Syncthing/obsidian-md/daily/index.md \
  /etc/skel-desktop/Syncthing/obsidian-md/home.md \
  /etc/skel-desktop/Syncthing/obsidian-md/inbox/welcome.md \
  /etc/skel-desktop/Syncthing/obsidian-md/templates/daily-note-template.md \
  /etc/skel-desktop/Syncthing/obsidian-md/templates/note-template.md
do
  require_readable "$path"
  require_mode "$path" 600
  readable_count=$((readable_count + 1))
done

for path in \
  /etc/skel-desktop/Syncthing \
  /etc/skel-desktop/Syncthing/obsidian-md \
  /etc/skel-desktop/Syncthing/obsidian-md/.obsidian \
  /etc/skel-desktop/Syncthing/obsidian-md/.obsidian/snippets \
  /etc/skel-desktop/Syncthing/obsidian-md/.obsidian/themes \
  /etc/skel-desktop/Syncthing/obsidian-md/.obsidian/themes/evergreen-notes \
  /etc/skel-desktop/Syncthing/obsidian-md/.trash \
  /etc/skel-desktop/Syncthing/obsidian-md/archive \
  /etc/skel-desktop/Syncthing/obsidian-md/attachments \
  /etc/skel-desktop/Syncthing/obsidian-md/daily \
  /etc/skel-desktop/Syncthing/obsidian-md/inbox \
  /etc/skel-desktop/Syncthing/obsidian-md/templates
do
  require_mode "$path" 700
done

for path in \
  /usr/local/bin/labwc-greeter-session \
  /usr/local/bin/labwc-greeter-output \
  /usr/local/bin/labwc-greeter-power \
  /usr/local/libexec/labwc-greeter-client \
  /usr/local/sbin/greetd-power-action \
  /usr/local/bin/labwc-session \
  /usr/local/bin/labwc-autostart \
  /usr/local/bin/labwc-wallpaper-save \
  /usr/local/bin/labwc-admin-action \
  /usr/local/libexec/labwc-admin-action-root \
  /usr/local/libexec/labwc-admin-action-worker \
  /usr/local/libexec/labwc-logout-root \
  /usr/local/libexec/labwc-session-state \
  /usr/local/bin/labwc-calendar \
  /usr/local/libexec/labwc-calendar \
  /usr/local/bin/labwc-ocr \
  /usr/local/bin/labwc-logout \
  /usr/local/bin/labwc-fuzzel \
  /usr/local/bin/labwc-fuzzel-log \
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
  /usr/local/bin/labwc-remote-desktop \
  /usr/local/bin/labwc-freerdp-askpass \
  /usr/local/bin/telbot \
  /usr/local/bin/labwc-terminal \
  /usr/local/bin/labwc-bluetooth \
  /usr/local/bin/labwc-brightness-control \
  /usr/local/libexec/bluetooth-controller-init \
  /usr/local/bin/labwc-power-settings \
  /usr/local/libexec/labwc-output-watch \
  /usr/local/libexec/labwc-kanshi \
  /usr/local/libexec/labwc-swaybg \
  /usr/local/libexec/labwc-swayidle \
  /usr/local/bin/labwc-health-notify \
  /usr/local/bin/labwc-managed-app \
  /usr/local/bin/labwc-electron-app \
  /usr/local/bin/labwc-wayland-app \
  /usr/local/libexec/labwc-wrap-desktop-files \
  /usr/local/bin/labwc-qbittorrent \
  /usr/local/bin/labwc-sync-application-launchers \
  /usr/local/bin/labwc-run \
  /usr/local/bin/labwc-lock \
  /usr/local/bin/labwc-power-menu \
  /usr/local/bin/labwc-keyboard-layout \
  /usr/local/bin/labwc-capture \
  /usr/local/bin/labwc-wayscriber-toggle \
  /usr/local/bin/satty \
  /usr/bin/wayscriber \
  /usr/local/libexec/apparmor-generate-rules \
  /usr/local/libexec/labwc-security-action-root \
  /usr/local/libexec/labwc-system-action-root \
  /usr/local/libexec/labwc-recovery-action-root \
  /usr/local/libexec/labwc-network-control-action-root \
  /usr/local/libexec/labwc-firewall-action-root \
  /usr/local/libexec/labwc-network-scan-action-root \
  /usr/local/libexec/labwc-samsung-firmware-extract \
  /usr/local/libexec/managed-clamav-signature-update \
  /usr/local/libexec/satty/satty
do
  require_executable "$path"
  executable_count=$((executable_count + 1))
done

require_absent /usr/share/backgrounds/desktop/wallpapers.tar.gz
require_absent /usr/bin/Xwayland
if [ "$(dpkg-query -W -f='${Status}' xwayland 2>/dev/null || true)" = "install ok installed" ]; then
  printf '%s\n' 'fatal: public xwayland package must not be installed' >&2
  exit 1
fi
require_absent /etc/environment.d/90-labwc-session.conf
require_absent /etc/skel-desktop/.config/systemd/user/dbus-broker.service.d/10-broker-hardening.conf
require_absent /etc/systemd/user/default.target.wants/mpris-proxy.service
require_absent /etc/systemd/user/graphical-session.target.wants/foot-server.service
require_absent /etc/systemd/user/labwc-session.target.wants/waybar.service
require_absent /etc/skel-desktop/.config/systemd/user/labwc-session.target.wants/foot-server.service
require_absent /etc/skel-desktop/.config/systemd/user/xdg-desktop-portal-xapp.service.d/10-labwc-session.conf
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
  require_absent "/etc/skel-desktop/.config/systemd/user/${account_local_package_dropin}.d/10-labwc-session.conf"
done
for legacy_user_unit in \
  waybar.service \
  waybar.service.d/20-tray-compat.conf \
  labwc-adb-server.service \
  llama-server.service \
  labwc-output-watch.service \
  labwc-mute-default-microphone.service \
  swaybg.service \
  kanshi.service \
  swayidle.service \
  crystal-dock.service \
  labwc-kwallet-portal.service \
  labwc-calendar-sync.service \
  labwc-calendar-sync.timer \
  labwc-sync-application-launchers.service \
  labwc-sync-application-launchers.path \
  managed-external-software-notify.service \
  managed-external-software-notify.path \
  whisper-record.service \
  whisper-transcribe.service \
  whisper-server.service
do
  require_absent "/etc/systemd/user/${legacy_user_unit}"
done

require_executable /usr/local/lib/android-sdk/platform-tools/adb
require_executable /usr/local/lib/android-sdk/platform-tools/fastboot
require_readable /usr/local/lib/android-sdk/platform-tools/source.properties
require_readable /usr/local/lib/android-sdk/platform-tools/.managed-release
require_symlink_target /usr/local/bin/adb ../lib/android-sdk/platform-tools/adb
require_symlink_target /usr/local/bin/fastboot ../lib/android-sdk/platform-tools/fastboot

require_executable /usr/local/lib/samloader/samloader
require_readable /usr/local/lib/samloader/.managed-release
require_symlink_target /usr/local/bin/samloader ../lib/samloader/samloader

require_readable /etc/udev/rules.d/51-android-debug-bridge.rules
require_readable /etc/udev/rules.d/52-samsung-download-mode.rules
require_readable /etc/udev/rules.d/53-ledger-wallet.rules

if [ -r /usr/share/dbus-1/system-services/org.freedesktop.nm_dispatcher.service ]; then
  nm_dispatcher_alias=/etc/systemd/system/dbus-org.freedesktop.nm-dispatcher.service
  nm_dispatcher_unit=
  require_readable /etc/systemd/system/NetworkManager.service.d/20-managed-dispatcher.conf
  require_readable /etc/systemd/system/NetworkManager-dispatcher.service.d/20-managed-persistent.conf
  if [ -r /usr/lib/systemd/system/NetworkManager-dispatcher.service ]; then
    nm_dispatcher_unit=/usr/lib/systemd/system/NetworkManager-dispatcher.service
  elif [ -r /lib/systemd/system/NetworkManager-dispatcher.service ]; then
    nm_dispatcher_unit=/lib/systemd/system/NetworkManager-dispatcher.service
  fi
  [ -n "$nm_dispatcher_unit" ] || fatal "NetworkManager dispatcher unit is missing"
  [ -L "$nm_dispatcher_alias" ] || fatal "NetworkManager dispatcher D-Bus alias is missing"
  [ "$(readlink -f "$nm_dispatcher_alias" 2>/dev/null || true)" = "$(readlink -f "$nm_dispatcher_unit" 2>/dev/null || true)" ] ||
    fatal "NetworkManager dispatcher D-Bus alias does not point to the vendor unit"
fi

printf "desktop_staged_file_metadata_verification readable=%s executable=%s\n" "$readable_count" "$executable_count"
' sh
}

desktop_verify_optional_staged_files() {
  # shellcheck disable=SC2016
  run_in_target "verify optional Labwc desktop staged files" /bin/sh -c '
set -eu
checked=0
missing=

check_optional_path() {
  path=$1
  if [ -e "$path" ]; then
    checked=$((checked + 1))
    return 0
  fi
  missing="${missing:+$missing }$path"
}

for path in \
  /usr/share/backgrounds/desktop/wallpaper-1920x1080.png \
  /usr/share/backgrounds/login/lock-1920x1080.png \
  /usr/share/backgrounds/login/welcome-1920x1080.png \
  /usr/share/backgrounds/other/regreet-000-greeter-purple.svg \
  /usr/share/backgrounds/other/wp2653774-black-and-blue-wallpaper-hd.png \
  /etc/skel-desktop/.config/waybar/config \
  /etc/skel-desktop/.config/waybar/style.css \
  /etc/skel-desktop/.config/kanshi/config \
  /etc/skel-desktop/.config/featherpad/fp.conf \
  /etc/skel-desktop/.config/foot/foot.ini \
  /etc/skel-desktop/.config/gnote/addins/global.ini \
  /etc/skel-desktop/.config/GottCode/FocusWriter.conf \
  /etc/skel-desktop/.local/share/GottCode/FocusWriter/Themes/managed-word.theme \
  /etc/skel-desktop/.config/kitty/kitty.conf \
  /etc/skel-desktop/.config/kdiff3rc \
  /etc/skel-desktop/.config/micro/settings.json \
  /etc/skel-desktop/.config/nano/nanorc \
  /etc/skel-desktop/.config/xdg-terminals.list \
  /etc/skel-desktop/.config/nvim/init.lua \
  /etc/skel-desktop/.config/qalculate/qalc.cfg \
  /etc/skel-desktop/.config/qalculate/qalculate-qt.cfg \
  /etc/skel-desktop/.config/task/taskrc \
  /etc/skel-desktop/.config/retroarch/retroarch.cfg \
  /etc/skel-desktop/.config/tesseract/ocr-defaults.conf \
  /etc/skel-desktop/.config/tesseract/user-words/default.user-words \
  /etc/skel-desktop/.config/tesseract/user-patterns/default.user-patterns \
  /etc/skel-desktop/.config/vim/vimrc \
  /etc/skel-desktop/.vimrc \
  /etc/skel-desktop/.config/xfce4/helpers.rc \
  /etc/skel-desktop/.config/xfce4/xfconf/xfce-perchannel-xml/thunar.xml \
  /usr/share/xfce4/helpers/foot.desktop \
  /etc/skel-desktop/.profile \
  /etc/skel-desktop/.bash_profile \
  /etc/skel-desktop/.bashrc \
  /etc/skel-desktop/.bash_aliases \
  /etc/skel-desktop/.zshenv \
  /etc/skel-desktop/.zprofile \
  /etc/skel-desktop/.zshrc \
  /etc/skel-desktop/.zlogout \
  /etc/skel-desktop/.zsh_aliases \
  /etc/skel-desktop/.dircolors \
  /etc/skel-desktop/.config/starship.toml \
  /etc/skel-desktop/.config/fuzzel/base.ini \
  /etc/skel-desktop/.config/fuzzel/base-internal.ini \
  /etc/skel-desktop/.config/fuzzel/fuzzel.ini \
  /etc/skel-desktop/.config/fuzzel/fuzzel-internal.ini \
  /etc/skel-desktop/.config/fuzzel/menu.ini \
  /etc/skel-desktop/.config/fuzzel/menu-internal.ini \
  /etc/skel-desktop/.config/Thunar/uca.xml \
  /etc/skel-desktop/.config/crystal-dock/labwc/appearance.conf \
  /etc/skel-desktop/.config/crystal-dock/labwc/panel_1.conf \
  /etc/xdg/crystal-dock/labwc/appearance.conf \
  /etc/xdg/crystal-dock/labwc/panel_1.conf \
  /usr/local/bin/labwc-show-desktop \
  /usr/share/applications/featherpad.desktop \
  /usr/share/applications/labwc-tweaks.desktop \
  /usr/share/applications/qt6ct.desktop \
  /usr/share/applications/retroarch.desktop \
  /usr/share/applications/show-desktop.desktop \
  /usr/local/bin/labwc-health-notify \
  /etc/skel-desktop/.config/mako/config \
  /etc/systemd/user/mako.service.d/10-labwc-session.conf \
  /etc/skel-desktop/.config/systemd/user/labwc-health-notify.service \
  /etc/skel-desktop/.config/systemd/user/labwc-health-notify.path \
  /etc/skel-desktop/.config/systemd/user/labwc-health-notify.timer \
  /etc/skel-desktop/.config/swaylock/config \
  /etc/skel-desktop/.config/gtk-3.0/settings.ini \
  /etc/skel-desktop/.config/gtk-4.0/settings.ini \
  /etc/xdg/gtk-3.0/settings.ini \
  /etc/xdg/gtk-4.0/settings.ini \
  /etc/skel-desktop/.config/qt6ct/qt6ct.conf \
  /etc/xdg/qt6ct/qt6ct.conf \
  /etc/skel-desktop/.config/kwalletrc \
  /etc/skel-desktop/.config/user-dirs.dirs \
  /etc/skel-desktop/.config/xournalpp/settings.xml \
  /etc/skel-desktop/.config/xdg-desktop-portal/portals.conf \
  /etc/xdg/xdg-desktop-portal/labwc-portals.conf \
  /etc/bluetooth/main.conf \
  /etc/chromium.d/90-performance-flags \
  /etc/skel-desktop/.config/systemd/user/labwc-calendar-sync.service \
  /etc/skel-desktop/.config/systemd/user/labwc-calendar-sync.timer \
  /etc/skel-desktop/.config/systemd/user/managed-external-software-notify.service \
  /etc/skel-desktop/.config/systemd/user/managed-external-software-notify.path \
  /etc/skel-desktop/.config/systemd/user/whisper-record.service \
  /etc/skel-desktop/.config/systemd/user/whisper-transcribe.service \
  /etc/skel-desktop/.config/systemd/user/whisper-server.service \
  /etc/systemd/system/bluetooth.service.d/override.conf \
  /etc/systemd/system/bluetooth-controller-init.service \
  /usr/local/libexec/bluetooth-controller-init \
  /usr/local/bin/labwc-bluetooth \
  /usr/share/applications/com.github.xournalpp.xournalpp.desktop \
  /usr/local/bin/labwc-managed-app \
  /usr/local/bin/labwc-electron-app \
  /usr/local/bin/labwc-wayland-app \
  /usr/local/libexec/labwc-wrap-desktop-files \
  /usr/local/bin/labwc-qbittorrent \
  /usr/local/bin/labwc-sync-application-launchers \
  /usr/share/applications/org.gnome.Gnote.desktop \
  /usr/share/glib-2.0/schemas/90-desktop-gnote.gschema.override \
  /usr/share/applications/net.sourceforge.liferea.desktop \
  /usr/share/glib-2.0/schemas/90-desktop-liferea.gschema.override \
  /usr/share/mime/packages/90-desktop-filetypes.xml \
  /etc/wireplumber/wireplumber.conf.d/10-disable-bluez-midi.conf \
  /etc/skel-desktop/.config/wireplumber/wireplumber.conf.d/10-disable-bluez-midi.conf
do
  check_optional_path "$path"
done
printf "desktop_optional_staged_file_verification checked=%s missing=%s\n" "$checked" "${missing:-none}"
' sh
}

desktop_verify_primary_user_files() {
  : "${ACCOUNT_USERNAME:?ACCOUNT_USERNAME must be set}"
  : "${ACCOUNT_HOME:?ACCOUNT_HOME must be set}"

  # shellcheck disable=SC2016
  run_in_target "verify Labwc primary account config" /bin/sh -c '
set -eu
fatal() {
  printf "fatal: %s\n" "$*" >&2
  exit 1
}

account_user=$1
account_home=$2
icon_theme=$3
uid=$(id -u "$account_user")
gid=$(id -g "$account_user")
required_checked=0
optional_checked=0
optional_missing=

check_required_owned() {
  path=$1
  [ -r "$path" ] || {
    printf "fatal: missing account desktop file: %s\n" "$path" >&2
    exit 1
  }
  owner=$(stat -c "%u:%g" "$path")
  [ "$owner" = "$uid:$gid" ] || {
    printf "fatal: account desktop file owner mismatch for %s: %s\n" "$path" "$owner" >&2
    exit 1
  }
  required_checked=$((required_checked + 1))
}

check_required_owned_dir() {
  path=$1
  [ -d "$path" ] || {
    printf "fatal: missing account desktop directory: %s\n" "$path" >&2
    exit 1
  }
  owner=$(stat -c "%u:%g" "$path")
  [ "$owner" = "$uid:$gid" ] || {
    printf "fatal: account desktop directory owner mismatch for %s: %s\n" "$path" "$owner" >&2
    exit 1
  }
  required_checked=$((required_checked + 1))
}

case "$icon_theme" in
  ""|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._+-]*)
    fatal "managed icon theme contains unsupported characters: ${icon_theme:-unset}"
    ;;
esac
[ -r "/usr/share/icons/${icon_theme}/index.theme" ] ||
  fatal "managed icon theme is unavailable: ${icon_theme}"
check_optional_owned() {
  path=$1
  [ -r "$path" ] || {
    optional_missing="${optional_missing:+$optional_missing }$path"
    return 0
  }
  optional_checked=$((optional_checked + 1))
}

verify_skeleton_session_link() {
  unit=$1
  link="/etc/skel-desktop/.config/systemd/user/labwc-session.target.wants/${unit}"
  [ -L "$link" ] || fatal "skeleton user session enablement link is missing: ${unit}"
  link_target=$(readlink "$link")
  case "$link_target" in
    "../${unit}"|/usr/lib/systemd/user/*|/lib/systemd/user/*) ;;
    *) fatal "skeleton user session enablement link is unsafe for ${unit}: ${link_target}" ;;
  esac
  owner=$(stat -c "%u:%g" "$link")
  [ "$owner" = 0:0 ] ||
    fatal "skeleton user session enablement link owner mismatch for ${unit}: ${owner}"
  required_checked=$((required_checked + 1))
}

verify_account_session_link() {
  unit=$1
  link="$account_home/.config/systemd/user/labwc-session.target.wants/${unit}"
  [ -L "$link" ] || fatal "primary account user session enablement link is missing: ${unit}"
  link_target=$(readlink "$link")
  case "$link_target" in
    "../${unit}"|/usr/lib/systemd/user/*|/lib/systemd/user/*) ;;
    *) fatal "primary account user session enablement link is unsafe for ${unit}: ${link_target}" ;;
  esac
  owner=$(stat -c "%u:%g" "$link")
  [ "$owner" = "$uid:$gid" ] ||
    fatal "primary account user session enablement link owner mismatch for ${unit}: ${owner}"
  required_checked=$((required_checked + 1))
}

for path in \
  "$account_home/.config/labwc/rc.xml" \
  "$account_home/.config/labwc/menu.xml" \
  "$account_home/.config/labwc/autostart" \
  "$account_home/.config/labwc/shutdown" \
  "$account_home/.config/labwc/environment" \
  "$account_home/.config/labwc/themerc-override" \
  "$account_home/.config/waypaper/config.ini" \
  "$account_home/.config/waypaper/keybindings.ini" \
  "$account_home/.config/waypaper/style.css" \
  "$account_home/.config/btop/btop.conf" \
  "$account_home/.config/fzf/default-opts" \
  "$account_home/.config/Code/User/settings.json" \
  "$account_home/.config/chromium/Default/Preferences" \
  "$account_home/.config/keepassxc/keepassxc.ini" \
  "$account_home/.config/microsoft-edge/Default/Preferences" \
  "$account_home/.config/obsidian/obsidian.json" \
  "$account_home/Syncthing/.stignore" \
  "$account_home/Syncthing/obsidian-md/.obsidian/app.json" \
  "$account_home/Syncthing/obsidian-md/.obsidian/appearance.json" \
  "$account_home/Syncthing/obsidian-md/.obsidian/backlink.json" \
  "$account_home/Syncthing/obsidian-md/.obsidian/bookmarks.json" \
  "$account_home/Syncthing/obsidian-md/.obsidian/command-palette.json" \
  "$account_home/Syncthing/obsidian-md/.obsidian/community-plugins.json" \
  "$account_home/Syncthing/obsidian-md/.obsidian/core-plugins.json" \
  "$account_home/Syncthing/obsidian-md/.obsidian/daily-notes.json" \
  "$account_home/Syncthing/obsidian-md/.obsidian/graph.json" \
  "$account_home/Syncthing/obsidian-md/.obsidian/hotkeys.json" \
  "$account_home/Syncthing/obsidian-md/.obsidian/templates.json" \
  "$account_home/Syncthing/obsidian-md/.obsidian/types.json" \
  "$account_home/Syncthing/obsidian-md/.obsidian/snippets/managed-ux.css" \
  "$account_home/Syncthing/obsidian-md/.obsidian/themes/evergreen-notes/manifest.json" \
  "$account_home/Syncthing/obsidian-md/.obsidian/themes/evergreen-notes/theme.css" \
  "$account_home/Syncthing/obsidian-md/archive/index.md" \
  "$account_home/Syncthing/obsidian-md/daily/index.md" \
  "$account_home/Syncthing/obsidian-md/home.md" \
  "$account_home/Syncthing/obsidian-md/inbox/welcome.md" \
  "$account_home/Syncthing/obsidian-md/templates/daily-note-template.md" \
  "$account_home/Syncthing/obsidian-md/templates/note-template.md" \
  "$account_home/.config/Recoll.org/recoll.ini" \
  "$account_home/.recoll/recoll.conf" \
  "$account_home/.config/vivaldi/Default/Preferences" \
  "$account_home/.gnupg/gpg-agent.conf" \
  "$account_home/.config/systemd/user/labwc-session.target" \
  "$account_home/.config/systemd/user/labwc-health-notify.service" \
  "$account_home/.config/systemd/user/labwc-health-notify.path" \
  "$account_home/.config/systemd/user/labwc-health-notify.timer" \
  "$account_home/.config/systemd/user/labwc-plans.service" \
  "$account_home/.config/systemd/user/labwc-adb-server.service" \
  "$account_home/.config/systemd/user/llama-server.service" \
  "$account_home/.config/systemd/user/labwc-calendar-sync.service" \
  "$account_home/.config/systemd/user/labwc-calendar-sync.timer" \
  "$account_home/.config/systemd/user/labwc-sync-application-launchers.service" \
  "$account_home/.config/systemd/user/labwc-sync-application-launchers.path" \
  "$account_home/.config/systemd/user/labwc-kwallet-portal.service" \
  "$account_home/.config/systemd/user/labwc-mute-default-microphone.service" \
  "$account_home/.config/systemd/user/labwc-output-watch.service" \
  "$account_home/.config/systemd/user/swaybg.service" \
  "$account_home/.config/systemd/user/swayidle.service" \
  "$account_home/.config/systemd/user/kanshi.service" \
  "$account_home/.config/systemd/user/crystal-dock.service" \
  "$account_home/.config/systemd/user/waybar.service" \
  "$account_home/.config/systemd/user/waybar.service.d/20-tray-compat.conf" \
  "$account_home/.local/share/dbus-1/services/org.freedesktop.secrets.service" \
  "$account_home/.local/share/applications/org.keepassxc.KeePassXC.desktop" \
  "$account_home/.local/share/applications/waypaper.desktop"
do
  check_required_owned "$path"
done

[ ! -e "$account_home/.config/systemd/user/xdg-desktop-portal-xapp.service.d/10-labwc-session.conf" ] ||
  fatal "retired XApp portal user drop-in is still present"
[ ! -e "$account_home/.config/systemd/user/dbus-broker.service.d/10-broker-hardening.conf" ] ||
  fatal "system-wide D-Bus broker hardening was copied into the desktop account"

for account_local_package_dropin in \
  filter-chain.service \
  foot-server.service \
  foot-server.socket \
  mako.service \
  hyprpolkitagent.service \
  pipewire.service \
  pipewire-pulse.service \
  pipewire.socket \
  pipewire-pulse.socket \
  wireplumber.service \
  filter-chain.service \
  wayscriber.service \
  xdg-desktop-portal.service \
  xdg-desktop-portal-gtk.service \
  xdg-desktop-portal-wlr.service \
  xdg-desktop-portal-lxqt.service
do
  account_dropin="$account_home/.config/systemd/user/${account_local_package_dropin}.d/10-labwc-session.conf"
  [ ! -e "$account_dropin" ] && [ ! -L "$account_dropin" ] ||
    fatal "primary account package-unit drop-in is still present: ${account_dropin}"
done

for optional_user_unit in \
  managed-external-software-notify.service \
  managed-external-software-notify.path \
  whisper-record.service \
  whisper-transcribe.service \
  whisper-server.service
do
  [ -r "/etc/skel-desktop/.config/systemd/user/${optional_user_unit}" ] || continue
  check_required_owned "$account_home/.config/systemd/user/${optional_user_unit}"
done

for session_unit in \
  labwc-output-watch.service \
  swaybg.service \
  kanshi.service \
  swayidle.service \
  crystal-dock.service \
  labwc-mute-default-microphone.service \
  labwc-kwallet-portal.service \
  labwc-plans.service \
  labwc-sync-application-launchers.service \
  labwc-sync-application-launchers.path \
  foot-server.socket \
  mako.service \
  filter-chain.service \
  labwc-calendar-sync.timer \
  wayscriber.service \
  hyprpolkitagent.service \
  xdg-desktop-portal.service \
  xdg-desktop-portal-gtk.service \
  xdg-desktop-portal-wlr.service \
  xdg-desktop-portal-lxqt.service
do
  verify_skeleton_session_link "$session_unit"
  verify_account_session_link "$session_unit"
done
require_absent "$account_home/.config/systemd/user/labwc-session.target.wants/foot-server.service"
require_absent "$account_home/.config/systemd/user/labwc-session.target.wants/llama-server.service"
for independent_audio_unit in \
  pipewire.service \
  pipewire-pulse.service \
  pipewire.socket \
  pipewire-pulse.socket \
  wireplumber.service
do
  require_absent "/etc/systemd/user/${independent_audio_unit}.d/10-labwc-session.conf"
  require_absent "/etc/skel-desktop/.config/systemd/user/labwc-session.target.wants/${independent_audio_unit}"
  require_absent "$account_home/.config/systemd/user/labwc-session.target.wants/${independent_audio_unit}"
done
unset independent_audio_unit
if [ -r /etc/skel-desktop/.config/systemd/user/whisper-server.service ]; then
  verify_skeleton_session_link whisper-server.service
  verify_account_session_link whisper-server.service
fi
if [ -r /etc/skel-desktop/.config/systemd/user/managed-external-software-notify.path ]; then
  verify_skeleton_session_link managed-external-software-notify.path
  verify_account_session_link managed-external-software-notify.path
fi

for on_demand_or_triggered_unit in \
  codex-app-server.service \
  codex-app-server-proxy.service \
  codex-app-server.socket \
  labwc-adb-server.service \
  labwc-calendar-sync.service \
  labwc-compositor.service \
  labwc-health-notify.path \
  labwc-health-notify.service \
  labwc-health-notify.timer \
  llama-server.service \
  managed-external-software-notify.service \
  waybar.service \
  whisper-record.service \
  whisper-transcribe.service
do
  require_absent "/etc/skel-desktop/.config/systemd/user/labwc-session.target.wants/${on_demand_or_triggered_unit}"
  require_absent "$account_home/.config/systemd/user/labwc-session.target.wants/${on_demand_or_triggered_unit}"
done
unset on_demand_or_triggered_unit

for path in \
  "$account_home/Desktop" \
  "$account_home/Documents" \
  "$account_home/Downloads" \
  "$account_home/Music" \
  "$account_home/Pictures" \
  "$account_home/Public" \
  "$account_home/Templates" \
  "$account_home/Videos" \
  "$account_home/Workspace" \
  "$account_home/.cache" \
  "$account_home/.cache/recoll" \
  "$account_home/.config/Code" \
  "$account_home/.config/chromium" \
  "$account_home/.config/microsoft-edge" \
  "$account_home/.config/obsidian" \
  "$account_home/.config/vivaldi" \
  "$account_home/.gnupg" \
  "$account_home/.config/systemd" \
  "$account_home/.config/systemd/user" \
  "$account_home/.config/systemd/user/labwc-session.target.wants" \
  "$account_home/.local" \
  "$account_home/.local/share" \
  "$account_home/.local/share/applications" \
  "$account_home/.local/share/GottCode" \
  "$account_home/.local/share/GottCode/FocusWriter" \
  "$account_home/.local/share/GottCode/FocusWriter/Themes" \
  "$account_home/.local/share/dbus-1" \
  "$account_home/.local/share/dbus-1/services" \
  "$account_home/.recoll" \
  "$account_home/.local/share/task" \
  "$account_home/.local/share/task/hooks" \
  "$account_home/Syncthing" \
  "$account_home/Syncthing/keepassxc" \
  "$account_home/Syncthing/keepassxc/backups" \
  "$account_home/Syncthing/obsidian-md" \
  "$account_home/Syncthing/obsidian-md/.obsidian" \
  "$account_home/Syncthing/obsidian-md/.obsidian/snippets" \
  "$account_home/Syncthing/obsidian-md/.obsidian/themes" \
  "$account_home/Syncthing/obsidian-md/.obsidian/themes/evergreen-notes" \
  "$account_home/Syncthing/obsidian-md/.trash" \
  "$account_home/Syncthing/obsidian-md/archive" \
  "$account_home/Syncthing/obsidian-md/attachments" \
  "$account_home/Syncthing/obsidian-md/daily" \
  "$account_home/Syncthing/obsidian-md/inbox" \
  "$account_home/Syncthing/obsidian-md/templates"
do
  check_required_owned_dir "$path"
done

if command -v vivaldi-stable >/dev/null 2>&1; then
  for path in \
    "$account_home/.cache" \
    "$account_home/.cache/vivaldi" \
    "$account_home/.config/vivaldi"
  do
    check_required_owned_dir "$path"
  done
fi

[ "$(stat -c "%a" "$account_home/.config/keepassxc")" = 700 ] || {
  printf "fatal: KeePassXC config directory mode is not 0700\n" >&2
  exit 1
}
[ "$(stat -c "%a" "$account_home/.config/keepassxc/keepassxc.ini")" = 600 ] || {
  printf "fatal: KeePassXC config file mode is not 0600\n" >&2
  exit 1
}
[ "$(stat -c "%a" "$account_home/.config/Recoll.org")" = 700 ] || {
  printf "fatal: Recoll GUI configuration directory mode is not 0700\n" >&2
  exit 1
}
[ "$(stat -c "%a" "$account_home/.config/Recoll.org/recoll.ini")" = 600 ] || {
  printf "fatal: Recoll GUI configuration file mode is not 0600\n" >&2
  exit 1
}
[ "$(stat -c "%a" "$account_home/.recoll")" = 700 ] || {
  printf "fatal: Recoll index configuration directory mode is not 0700\n" >&2
  exit 1
}
[ "$(stat -c "%a" "$account_home/.cache")" = 700 ] || {
  printf "fatal: XDG cache directory mode is not 0700\n" >&2
  exit 1
}
[ "$(stat -c "%a" "$account_home/.config/systemd")" = 700 ] || {
  printf "fatal: systemd user configuration directory mode is not 0700\n" >&2
  exit 1
}
[ "$(stat -c "%a" "$account_home/.config/systemd/user")" = 700 ] || {
  printf "fatal: systemd user unit directory mode is not 0700\n" >&2
  exit 1
}
for user_dropin_dir in "$account_home/.config/systemd/user"/*.d; do
  [ -d "$user_dropin_dir" ] || continue
  [ "$(stat -c "%a" "$user_dropin_dir")" = 700 ] || {
    printf "fatal: systemd user drop-in directory mode is not 0700: %s\n" "$user_dropin_dir" >&2
    exit 1
  }
done
[ "$(stat -c "%a" "$account_home/.gnupg")" = 700 ] || {
  printf "fatal: GnuPG directory mode is not 0700\n" >&2
  exit 1
}
[ "$(stat -c "%a" "$account_home/.gnupg/gpg-agent.conf")" = 600 ] || {
  printf "fatal: GnuPG agent configuration mode is not 0600\n" >&2
  exit 1
}
[ "$(stat -c "%a" "$account_home/.local/share/dbus-1")" = 700 ] || {
  printf "fatal: D-Bus user data directory mode is not 0700\n" >&2
  exit 1
}
[ "$(stat -c "%a" "$account_home/.local/share/dbus-1/services")" = 700 ] || {
  printf "fatal: D-Bus user activation directory mode is not 0700\n" >&2
  exit 1
}
for service_file in "$account_home/.local/share/dbus-1/services"/*.service; do
  [ -f "$service_file" ] || continue
  [ "$(stat -c "%a" "$service_file")" = 600 ] || {
    printf "fatal: D-Bus user activation file mode is not 0600: %s\n" "$service_file" >&2
    exit 1
  }
done
[ "$(stat -c "%a" "$account_home/.config/systemd/user/labwc-session.target.wants")" = 700 ] || {
  printf "fatal: Labwc session user-unit enablement directory mode is not 0700\n" >&2
  exit 1
}
[ "$(stat -c "%a" "$account_home/.cache/recoll")" = 700 ] || {
  printf "fatal: Recoll cache directory mode is not 0700\n" >&2
  exit 1
}
[ "$(stat -c "%a" "$account_home/.local/share/task")" = 700 ] || {
  printf "fatal: Taskwarrior data directory mode is not 0700\n" >&2
  exit 1
}
[ "$(stat -c "%a" "$account_home/.local/share/task/hooks")" = 700 ] || {
  printf "fatal: Taskwarrior hooks directory mode is not 0700\n" >&2
  exit 1
}
[ "$(stat -c "%a" "$account_home/Syncthing/keepassxc")" = 700 ] || {
  printf "fatal: KeePassXC database directory mode is not 0700\n" >&2
  exit 1
}
[ "$(stat -c "%a" "$account_home/Syncthing/obsidian-md")" = 700 ] || {
  printf "fatal: Obsidian vault directory mode is not 0700\n" >&2
  exit 1
}
[ "$(stat -c "%a" "$account_home/Syncthing/obsidian-md/.obsidian")" = 700 ] || {
  printf "fatal: Obsidian vault configuration directory mode is not 0700\n" >&2
  exit 1
}
for private_file in \
  "$account_home/.config/obsidian/obsidian.json" \
  "$account_home/Syncthing/.stignore" \
  "$account_home/Syncthing/obsidian-md/.obsidian/app.json" \
  "$account_home/Syncthing/obsidian-md/.obsidian/appearance.json" \
  "$account_home/Syncthing/obsidian-md/.obsidian/core-plugins.json" \
  "$account_home/Syncthing/obsidian-md/.obsidian/themes/evergreen-notes/manifest.json" \
  "$account_home/Syncthing/obsidian-md/.obsidian/themes/evergreen-notes/theme.css"
do
  [ "$(stat -c "%a" "$private_file")" = 600 ] || {
    printf "fatal: managed Obsidian file mode is not 0600: %s\n" "$private_file" >&2
    exit 1
  }
done
for path in \
    "$account_home/.config/waybar/config" \
  "$account_home/.config/featherpad/fp.conf" \
  "$account_home/.config/foot/foot.ini" \
  "$account_home/.config/gnote/addins/global.ini" \
  "$account_home/.config/GottCode/FocusWriter.conf" \
  "$account_home/.local/share/GottCode/FocusWriter/Themes/managed-word.theme" \
  "$account_home/.config/kitty/kitty.conf" \
  "$account_home/.config/kdiff3rc" \
  "$account_home/.config/mimeapps.list" \
  "$account_home/.config/micro/settings.json" \
  "$account_home/.config/nano/nanorc" \
  "$account_home/.config/xdg-terminals.list" \
  "$account_home/.config/nvim/init.lua" \
  "$account_home/.config/qalculate/qalc.cfg" \
  "$account_home/.config/qalculate/qalculate-qt.cfg" \
  "$account_home/.config/task/taskrc" \
  "$account_home/.config/retroarch/retroarch.cfg" \
  "$account_home/.config/tesseract/ocr-defaults.conf" \
  "$account_home/.config/tesseract/user-words/default.user-words" \
  "$account_home/.config/tesseract/user-patterns/default.user-patterns" \
  "$account_home/.config/vim/vimrc" \
  "$account_home/.vimrc" \
  "$account_home/.config/xfce4/helpers.rc" \
  "$account_home/.config/xfce4/xfconf/xfce-perchannel-xml/thunar.xml" \
  "$account_home/.config/fuzzel/base.ini" \
  "$account_home/.config/fuzzel/base-internal.ini" \
  "$account_home/.config/fuzzel/fuzzel.ini" \
  "$account_home/.config/fuzzel/fuzzel-internal.ini" \
  "$account_home/.config/fuzzel/menu.ini" \
  "$account_home/.config/fuzzel/menu-internal.ini" \
  "$account_home/.config/Thunar/uca.xml" \
  "$account_home/.config/crystal-dock/labwc/appearance.conf" \
  "$account_home/.config/crystal-dock/labwc/panel_1.conf" \
  "$account_home/.config/mako/config" \
  "$account_home/.config/kanshi/config" \
  "$account_home/.config/swaylock/config" \
  "$account_home/.profile" \
  "$account_home/.profile.d" \
  "$account_home/.bash_profile" \
  "$account_home/.bashrc" \
  "$account_home/.bash_aliases" \
  "$account_home/.zshenv" \
  "$account_home/.zprofile" \
  "$account_home/.zshrc" \
  "$account_home/.zlogout" \
  "$account_home/.zsh_aliases" \
  "$account_home/.dircolors" \
  "$account_home/.config/starship.toml" \
  "$account_home/.config/gtk-3.0/settings.ini" \
  "$account_home/.config/gtk-4.0/settings.ini" \
  "$account_home/.config/vdirsyncer/config" \
  "$account_home/.local/share/applications/chromium.desktop" \
  "$account_home/.local/share/applications/com.microsoft.Edge.desktop" \
  "$account_home/.local/share/applications/vivaldi-stable.desktop" \
  "$account_home/.local/share/applications/code.desktop" \
  "$account_home/.local/share/applications/bitwarden.desktop" \
  "$account_home/.local/share/applications/obsidian.desktop" \
  "$account_home/.local/share/applications/postman.desktop" \
  "$account_home/.local/share/applications/sleek.desktop" \
  "$account_home/.local/share/applications/tutanota-desktop.desktop" \
  "$account_home/.local/share/applications/Zoom.desktop" \
  "$account_home/.local/share/applications/Filen.desktop" \
  "$account_home/.local/share/applications/discord.desktop" \
  "$account_home/.local/share/applications/ledger-live.desktop" \
  "$account_home/.local/share/applications/org.telegram.desktop.desktop" \
  "$account_home/.local/share/applications/mullvad-browser.desktop" \
  "$account_home/.config/khal/config" \
  "$account_home/.config/todoman/config.py" \
  "$account_home/.local/share/calendars/personal/displayname" \
  "$account_home/.local/share/calendars/tasks/displayname" \
  "$account_home/.config/qt6ct/qt6ct.conf" \
  "$account_home/.config/user-dirs.dirs" \
  "$account_home/.config/xournalpp/settings.xml" \
  "$account_home/.config/xdg-desktop-portal/portals.conf" \
  "$account_home/.config/kwalletrc"
do
  check_optional_owned "$path"
done

zsh_path=$(command -v zsh 2>/dev/null || true)
account_shell=$(getent passwd "$account_user" | cut -d: -f7)
shell_status=not-checked
if [ -n "$zsh_path" ]; then
  if [ "$account_shell" = "$zsh_path" ]; then
    shell_status=matches-zsh
  else
    shell_status=mismatch
  fi
fi

printf "desktop_primary_account_verification user=%s home=%s required_files=%s optional_files=%s optional_missing=%s shell=%s shell_status=%s\n" \
  "$account_user" \
  "$account_home" \
  "$required_checked" \
  "$optional_checked" \
  "${optional_missing:-none}" \
  "$account_shell" \
  "$shell_status"
' sh "$ACCOUNT_USERNAME" "$ACCOUNT_HOME" "${LABWC_ICON_THEME:-Papirus-Dark}"
}

desktop_verify_greeter_access() {
  : "${LABWC_GREETER_USER:?LABWC_GREETER_USER must be set}"

  # shellcheck disable=SC2016
  run_in_target "verify Labwc greeter seat and DRM access" /bin/sh -c '
set -eu
greeter_user=$1
checked=0
present=
missing=
greeter_groups=$(id -nG "$greeter_user")
wireplumber_dropin=/etc/systemd/user/wireplumber.service.d/20-no-root.conf
[ -f "$wireplumber_dropin" ] && [ ! -L "$wireplumber_dropin" ] || {
  printf "fatal: WirePlumber user-condition drop-in is missing or unsafe: %s\n" "$wireplumber_dropin" >&2
  exit 1
}
grep -Fxq 'ConditionUser=!root' "$wireplumber_dropin" &&
  grep -Fxq "ConditionUser=!${greeter_user}" "$wireplumber_dropin" || {
    printf "fatal: WirePlumber is not excluded from the greeter user manager: %s\n" "$greeter_user" >&2
    exit 1
  }

for group_name in seat render video; do
  if ! getent group "$group_name" >/dev/null 2>&1; then
    missing="${missing:+$missing }$group_name"
    continue
  fi
  case " $greeter_groups " in
    *" $group_name "*) ;;
    *)
      printf "fatal: greeter user %s is missing required group %s\n" "$greeter_user" "$group_name" >&2
      exit 1
      ;;
  esac
  checked=$((checked + 1))
  present="${present:+$present }$group_name"
done

printf "desktop_greeter_access_verification user=%s checked=%s present=%s missing=%s\n" \
  "$greeter_user" \
  "$checked" \
  "${present:-none}" \
  "${missing:-none}"
' sh "$LABWC_GREETER_USER"
}

desktop_verify_user_resource_policy() {
  # shellcheck disable=SC2016
  run_in_target "verify Labwc user resource policy files" /bin/sh -c '
set -eu

for policy_file in "$@"; do
  [ -r "$policy_file" ] || {
    printf "fatal: missing desktop user resource policy file: %s\n" "$policy_file" >&2
    exit 1
  }
done

printf "desktop_user_resource_policy_verification slice=%s files=%s\n" user-1000 "$#"
' sh \
    /etc/systemd/system/user-1000.slice.d/50-resource-accounting.conf \
    /etc/systemd/system/user@.service.d/50-oom-score.conf \
    /etc/systemd/user.conf.d/50-resource-defaults.conf
}

desktop_verify_target_staging() {
  desktop_verify_required_commands
  desktop_verify_staged_files
  desktop_verify_optional_staged_files
  desktop_verify_greeter_access
  desktop_verify_primary_user_files
  desktop_verify_user_resource_policy
}
