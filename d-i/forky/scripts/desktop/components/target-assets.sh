#!/bin/sh
# Sourced installer module; edit this file directly.

desktop_stage_session_repairs() {
  for public_directory in /etc/udev /etc/udev/hwdb.d; do
    ensure_target_asset_parent "${public_directory}/.installer-parent"
    public_host=$(target_asset_host_path "$public_directory")
    [ ! -L "$public_host" ] || installer_fatal "unsafe system configuration directory: $public_directory"
    chown root:root "$public_host"
    chmod 0755 "$public_host"
  done
  # Retire the old key remap, including reruns on an existing target. The strict
  # hwdb rebuild below also removes its entries from the compiled database.
  remove_target_asset /etc/udev/hwdb.d/90-thinkpad-extra-buttons.hwdb
  desktop_stage_role_asset usr/local/libexec/labwc-wallpaper-control /usr/local/libexec/labwc-wallpaper-control 0755
  desktop_stage_role_asset usr/local/libexec/labwc-notification-send /usr/local/libexec/labwc-notification-send 0755
  desktop_stage_role_asset usr/local/libexec/labwc-configure-session-repairs /usr/local/libexec/labwc-configure-session-repairs 0755
  desktop_stage_role_asset etc/security/sudo-i.conf /etc/security/sudo-i.conf 0644
  desktop_stage_role_asset etc/skel-desktop/.config/xfce4/xfconf/xfce-perchannel-xml/xsettings.xml /etc/skel-desktop/.config/xfce4/xfconf/xfce-perchannel-xml/xsettings.xml 0644
  run_in_target "build target keyboard hardware database" /usr/bin/systemd-hwdb --strict update
  run_in_target "configure managed session repairs" /usr/local/libexec/labwc-configure-session-repairs \
    "$ACCOUNT_USERNAME"
}

desktop_stage_wlsunset() {
  desktop_stage_role_asset etc/skel-desktop/.config/systemd/user/labwc-wlsunset-start.service /etc/skel-desktop/.config/systemd/user/labwc-wlsunset-start.service 0644
  desktop_stage_role_asset usr/local/bin/labwc-wlsunset /usr/local/bin/labwc-wlsunset 0755
  desktop_render_role_target_template \
    etc/labwc/wlsunset.conf.tmpl /etc/labwc/wlsunset.conf 0644 \
    WLSUNSET_ENABLED "$(desktop_shell_config_value "${WLSUNSET_ENABLED-true}")" \
    WLSUNSET_LATITUDE "$(desktop_shell_config_value "${WLSUNSET_LATITUDE-55.60587}")" \
    WLSUNSET_LONGITUDE "$(desktop_shell_config_value "${WLSUNSET_LONGITUDE-13.00073}")" \
    WLSUNSET_TEMPERATURE_DAY "$(desktop_shell_config_value "${WLSUNSET_TEMPERATURE_DAY-6500}")" \
    WLSUNSET_TEMPERATURE_NIGHT "$(desktop_shell_config_value "${WLSUNSET_TEMPERATURE_NIGHT-4500}")" \
    WLSUNSET_GAMMA "$(desktop_shell_config_value "${WLSUNSET_GAMMA-1.0}")" \
    WLSUNSET_SUNRISE "$(desktop_shell_config_value "${WLSUNSET_SUNRISE-}")" \
    WLSUNSET_SUNSET "$(desktop_shell_config_value "${WLSUNSET_SUNSET-}")" \
    WLSUNSET_TRANSITION_SECONDS "$(desktop_shell_config_value "${WLSUNSET_TRANSITION_SECONDS-1800}")" \
    WLSUNSET_OUTPUTS "$(desktop_shell_config_value "${WLSUNSET_OUTPUTS-}")"

  run_in_target "validate managed wlsunset configuration" /usr/local/bin/labwc-wlsunset check
}

desktop_stage_waybar_native_menus() {
  for menu_name in tomat audio notifications power calendar; do
    desktop_render_waybar_asset "${menu_name}-menu.xml"
  done
  # Keep optional voice actions visible but disabled when their services are
  # not selected. IDs stay stable, so both Waybar layouts use the same mapping.
  native_menu_whisper=0
  if desktop_whisper_addon_selected; then native_menu_whisper=1; fi
  run_in_target "configure optional native audio menu" /usr/bin/python3 -I -c '
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
path = Path("/etc/skel-desktop/.config/waybar/audio-menu.xml")
tree = ET.parse(path)
items = [item for item in tree.iter("object") if item.get("class") == "GtkMenuItem"
         and item.find(".//object[@id=\"whisper_record\"]") is not None]
if len(items) != 1:
    raise SystemExit("native audio menu has no unique Whisper submenu")
item = items[0]
prop = item.find("./property[@name=\"sensitive\"]")
if prop is None:
    prop = ET.Element("property", {"name": "sensitive"})
    # GtkBuilder constructs the parent when it encounters its first child.
    # Properties added after that child are not reliably applied by GTK3.
    item.insert(0, prop)
prop.text = "True" if sys.argv[1] == "1" else "False"
item.find("./child/object[@class=\"GtkBox\"]/child/object[@class=\"GtkLabel\"]/property[@name=\"label\"]").text = "Whisper" if sys.argv[1] == "1" else "Whisper (not installed)"
ET.indent(tree, space="  ")
tree.write(path, encoding="utf-8", xml_declaration=True)
' "$native_menu_whisper"
  desktop_stage_role_asset etc/skel-desktop/.config/tomat/config.toml \
    /etc/skel-desktop/.config/tomat/config.toml 0600
  for menu_helper in labwc-tomat labwc-tomat-hook labwc-notifications; do
    desktop_stage_role_asset "usr/local/libexec/$menu_helper" "/usr/local/libexec/$menu_helper" 0755
  done
}

desktop_stage_target_assets() {
  desktop_stage_waybar_native_menus
  desktop_stage_session_repairs
  desktop_stage_wlsunset
  desktop_normalize_system_dbus_service_directories
  desktop_stage_logging_policy
  desktop_stage_primary_account_pool_storage_policy
  desktop_stage_network_profile_storage_policy
  desktop_stage_var_cache_policy
  desktop_render_labwc_environment_assets
  desktop_stage_role_asset etc/pam.d/greetd /etc/pam.d/greetd 0644
  desktop_stage_role_asset etc/pam.d/greetd-greeter /etc/pam.d/greetd-greeter 0644
  desktop_stage_role_asset etc/pam.d/swaylock /etc/pam.d/swaylock 0644
  desktop_stage_role_asset usr/share/pam-configs/wtmpdb /usr/share/pam-configs/wtmpdb 0644
  desktop_reconcile_wtmpdb_common_session /target
  desktop_render_labwc_session_wrappers
  desktop_configure_local_mail_delivery
  desktop_stage_role_asset usr/local/bin/labwc-autostart /usr/local/bin/labwc-autostart 0755
  desktop_stage_role_asset usr/local/bin/labwc-wallpaper-save /usr/local/bin/labwc-wallpaper-save 0755
  desktop_stage_role_asset usr/local/bin/labwc-admin-action /usr/local/bin/labwc-admin-action 0755
  desktop_stage_role_asset usr/local/libexec/labwc-admin-action-root /usr/local/libexec/labwc-admin-action-root 0755
  desktop_stage_role_asset usr/local/libexec/labwc-admin-action-worker /usr/local/libexec/labwc-admin-action-worker 0755
  desktop_stage_role_asset usr/local/libexec/labwc-logout-root /usr/local/libexec/labwc-logout-root 0755
  desktop_stage_role_asset usr/local/libexec/labwc-session-state /usr/local/libexec/labwc-session-state 0755
  desktop_stage_role_asset etc/skel-desktop/.config/systemd/user/labwc-session-restore.service /etc/skel-desktop/.config/systemd/user/labwc-session-restore.service 0644
  desktop_stage_role_asset etc/skel-desktop/.config/systemd/user/labwc-session-state@.service /etc/skel-desktop/.config/systemd/user/labwc-session-state@.service 0644
  desktop_stage_role_asset etc/skel-desktop/.config/systemd/user/labwc-session-state@prepare.service.d/retain-result.conf /etc/skel-desktop/.config/systemd/user/labwc-session-state@prepare.service.d/retain-result.conf 0644
  desktop_stage_role_asset etc/systemd/system/labwc-admin-action@.service.tmpl /etc/systemd/system/labwc-admin-action@.service 0644
  desktop_stage_role_asset etc/systemd/system/labwc-package-sleep-guard.service.tmpl /etc/systemd/system/labwc-package-sleep-guard.service 0644
  desktop_stage_role_asset etc/systemd/system/sleep.target.d/50-package-lock-guard.conf /etc/systemd/system/sleep.target.d/50-package-lock-guard.conf 0644
  desktop_stage_role_asset usr/local/libexec/greetd-power-action-root /usr/local/libexec/greetd-power-action-root 0755
  desktop_remove_legacy_power_transactions || return 1
  desktop_stage_role_asset usr/local/bin/labwc-calendar /usr/local/bin/labwc-calendar 0755
  desktop_stage_role_asset usr/local/libexec/labwc-calendar /usr/local/libexec/labwc-calendar 0755
  desktop_stage_role_asset usr/local/libexec/labwc-plans.pl /usr/local/libexec/labwc-plans.pl 0755
  desktop_stage_role_asset usr/local/bin/labwc-logout /usr/local/bin/labwc-logout 0755
  desktop_stage_role_asset usr/local/bin/labwc-fuzzel /usr/local/bin/labwc-fuzzel 0755
  desktop_stage_role_asset usr/local/bin/labwc-computer-management /usr/local/bin/labwc-computer-management 0755
  desktop_stage_role_asset usr/local/bin/labwc-ai-copilots /usr/local/bin/labwc-ai-copilots 0755
  desktop_stage_ai_copilots_perl_modules
  desktop_stage_ai_copilots_catalogs
  desktop_stage_role_asset usr/local/bin/labwc-ai-copilots-action /usr/local/bin/labwc-ai-copilots-action 0755
  desktop_stage_role_asset usr/local/libexec/labwc-ai-llama-server /usr/local/libexec/labwc-ai-llama-server 0755
  desktop_stage_role_asset usr/local/libexec/labwc-ai-model-install-root /usr/local/libexec/labwc-ai-model-install-root 0755
  desktop_stage_ai_copilots_python_modules
  desktop_stage_role_asset usr/local/libexec/labwc-ai-model-info /usr/local/libexec/labwc-ai-model-info 0755
  desktop_stage_role_asset usr/local/bin/labwc-display-configuration /usr/local/bin/labwc-display-configuration 0755
  desktop_stage_role_asset usr/local/bin/labwc-digital-assets /usr/local/bin/labwc-digital-assets 0755
  desktop_stage_digital_assets_perl_modules
  desktop_stage_role_asset usr/local/bin/labwc-digital-assets-action /usr/local/bin/labwc-digital-assets-action 0755
  desktop_stage_role_asset usr/local/bin/labwc-users-groups-menu /usr/local/bin/labwc-users-groups-menu 0755
  desktop_stage_role_asset usr/local/bin/labwc-adb-menu /usr/local/bin/labwc-adb-menu 0755
  desktop_stage_labwc_adb_perl_modules
  desktop_stage_role_asset usr/local/bin/labwc-adb-action /usr/local/bin/labwc-adb-action 0755
  desktop_stage_role_asset etc/skel-desktop/.config/systemd/user/labwc-adb-server.service /etc/skel-desktop/.config/systemd/user/labwc-adb-server.service 0644
  desktop_stage_role_asset etc/skel-desktop/.config/systemd/user/llama-server.service /etc/skel-desktop/.config/systemd/user/llama-server.service 0644
  desktop_stage_role_asset usr/local/libexec/labwc-samsung-firmware-extract /usr/local/libexec/labwc-samsung-firmware-extract 0755
  desktop_stage_role_asset usr/local/bin/labwc-maintenance-menu /usr/local/bin/labwc-maintenance-menu 0755
  desktop_stage_role_asset usr/local/bin/labwc-podman-menu /usr/local/bin/labwc-podman-menu 0755
  desktop_stage_role_asset usr/local/bin/labwc-external-drives /usr/local/bin/labwc-external-drives 0755
  desktop_stage_labwc_security_action_perl_modules
  desktop_stage_role_asset usr/local/bin/labwc-security-action /usr/local/bin/labwc-security-action 0755
  desktop_stage_role_asset usr/local/bin/labwc-system-action /usr/local/bin/labwc-system-action 0755
  desktop_stage_role_asset usr/local/bin/labwc-recovery-action /usr/local/bin/labwc-recovery-action 0755
  desktop_stage_role_asset usr/local/bin/labwc-network-control-menu /usr/local/bin/labwc-network-control-menu 0755
  desktop_stage_labwc_network_control_action_perl_modules
  desktop_stage_role_asset usr/local/bin/labwc-network-control-action /usr/local/bin/labwc-network-control-action 0755
  desktop_stage_role_asset usr/local/bin/labwc-firewall-menu /usr/local/bin/labwc-firewall-menu 0755
  desktop_stage_labwc_firewall_python_modules
  desktop_stage_role_asset usr/local/bin/labwc-firewall-action /usr/local/bin/labwc-firewall-action 0755
  desktop_stage_role_asset usr/local/bin/labwc-network-scan-menu /usr/local/bin/labwc-network-scan-menu 0755
  desktop_stage_labwc_network_scan_action_perl_modules
  desktop_render_labwc_network_scan_action_perl_root_module
  desktop_stage_role_asset usr/local/bin/labwc-network-scan-action /usr/local/bin/labwc-network-scan-action 0755
  desktop_stage_role_asset usr/local/bin/labwc-remote-desktop /usr/local/bin/labwc-remote-desktop 0755
  desktop_stage_role_asset usr/local/bin/labwc-freerdp-askpass /usr/local/bin/labwc-freerdp-askpass 0755
  desktop_stage_role_asset usr/local/bin/labwc-ocr /usr/local/bin/labwc-ocr 0755
  desktop_stage_role_asset usr/local/bin/discord /usr/local/bin/discord 0755
  desktop_stage_role_asset usr/local/bin/telbot /usr/local/bin/telbot 0755
  desktop_render_role_target_template \
    etc/skel-desktop/.local/share/applications/tutanota-desktop.desktop \
    /etc/skel-desktop/.local/share/applications/tutanota-desktop.desktop \
    0644 \
    LABWC_MANAGED_APP_DEFAULT_EXEC "$LABWC_MANAGED_APP_DEFAULT_EXEC"
  desktop_stage_labwc_managed_app_python_modules
  desktop_stage_role_asset usr/local/bin/labwc-app /usr/local/bin/labwc-app 0755
  desktop_stage_role_asset usr/local/bin/labwc-electron-app /usr/local/bin/labwc-electron-app 0755
  desktop_stage_role_asset usr/local/bin/labwc-wayland-app /usr/local/bin/labwc-wayland-app 0755
  desktop_stage_role_asset usr/local/libexec/labwc-wrap-desktop-files /usr/local/libexec/labwc-wrap-desktop-files 0755
  desktop_stage_role_asset usr/local/bin/labwc-main-menu /usr/local/bin/labwc-main-menu 0755
  desktop_stage_role_asset usr/local/bin/labwc-window-switcher /usr/local/bin/labwc-window-switcher 0755
  desktop_stage_waybar_theme_icons
  desktop_stage_role_asset usr/local/bin/labwc-fzf-menu /usr/local/bin/labwc-fzf-menu 0755
  desktop_stage_role_asset etc/systemd/system/labwc-system-desktop-overrides.service /etc/systemd/system/labwc-system-desktop-overrides.service 0644
  desktop_stage_role_asset etc/systemd/system/labwc-system-desktop-overrides.path /etc/systemd/system/labwc-system-desktop-overrides.path 0644
  desktop_render_role_target_template \
    etc/skel-desktop/.local/share/applications/waypaper.desktop.tmpl \
    /etc/skel-desktop/.local/share/applications/waypaper.desktop \
    0644 \
    LABWC_WAYLAND_APP_DEFAULT_EXEC "$LABWC_WAYLAND_APP_DEFAULT_EXEC"
  desktop_stage_role_asset etc/dpkg/dpkg.cfg.d/95-labwc-desktop-apps /etc/dpkg/dpkg.cfg.d/95-labwc-desktop-apps 0644
  desktop_stage_role_asset usr/local/libexec/labwc-chatgpt-session /usr/local/libexec/labwc-chatgpt-session 0755
  desktop_stage_role_asset usr/local/bin/labwc-wayland-compat-app /usr/local/bin/labwc-wayland-compat-app 0755
  desktop_stage_role_asset usr/local/libexec/labwc-zoom-discord-compat-runtime /usr/local/libexec/labwc-zoom-discord-compat-runtime 0755
  desktop_stage_role_asset usr/local/bin/labwc-qbittorrent /usr/local/bin/labwc-qbittorrent 0755
  desktop_stage_role_asset usr/local/bin/zoom /usr/local/bin/zoom 0755
  desktop_render_role_target_template \
    usr/local/bin/labwc-sync-application-launchers \
    /usr/local/bin/labwc-sync-application-launchers \
    0755 \
    LABWC_MANAGED_APP_DEFAULT_EXEC "$LABWC_MANAGED_APP_DEFAULT_EXEC"
  desktop_stage_role_asset etc/skel-desktop/.config/systemd/user/labwc-sync-application-launchers.service /etc/skel-desktop/.config/systemd/user/labwc-sync-application-launchers.service 0644
  desktop_stage_role_asset etc/skel-desktop/.config/systemd/user/labwc-sync-application-launchers.path /etc/skel-desktop/.config/systemd/user/labwc-sync-application-launchers.path 0644
  desktop_stage_role_asset usr/local/bin/labwc-greeter-output /usr/local/bin/labwc-greeter-output 0755
  desktop_stage_role_asset usr/local/bin/labwc-greeter-power /usr/local/bin/labwc-greeter-power 0755
  desktop_stage_role_asset usr/local/libexec/labwc-greeter-client /usr/local/libexec/labwc-greeter-client 0755
  desktop_stage_role_asset usr/local/share/labwc-greeter/rc.xml /usr/local/share/labwc-greeter/rc.xml 0644
  desktop_stage_role_asset usr/local/share/labwc-greeter/autostart /usr/local/share/labwc-greeter/autostart 0644
  desktop_stage_role_asset usr/local/libexec/labwc-output-watch /usr/local/libexec/labwc-output-watch 0755
  if desktop_kanshi_enabled; then
    desktop_stage_role_asset usr/local/libexec/labwc-kanshi /usr/local/libexec/labwc-kanshi 0755
  fi
  desktop_stage_role_asset usr/local/libexec/labwc-session-check /usr/local/libexec/labwc-session-check 0755
  desktop_stage_role_asset usr/local/libexec/labwc-waybar-exec /usr/local/libexec/labwc-waybar-exec 0755
  desktop_stage_role_asset usr/local/libexec/labwc-panel-run /usr/local/libexec/labwc-panel-run 0755
  desktop_stage_role_asset usr/local/libexec/whisper-record-timed /usr/local/libexec/whisper-record-timed 0755
  desktop_stage_role_asset usr/local/libexec/labwc-swaybg /usr/local/libexec/labwc-swaybg 0755
  desktop_stage_role_asset usr/local/libexec/labwc-swayidle /usr/local/libexec/labwc-swayidle 0755
  desktop_stage_role_asset usr/local/libexec/labwc-mute-default-microphone /usr/local/libexec/labwc-mute-default-microphone 0755
  desktop_stage_role_asset usr/local/lib/perl5/site_perl/whisper/WhisperMode/Audio.pm /usr/local/lib/perl5/site_perl/whisper/WhisperMode/Audio.pm 0644
  desktop_stage_role_asset usr/local/lib/perl5/site_perl/whisper/WhisperMode/State.pm /usr/local/lib/perl5/site_perl/whisper/WhisperMode/State.pm 0644
  desktop_stage_role_asset usr/local/lib/perl5/site_perl/whisper/WhisperMode/Systemd.pm /usr/local/lib/perl5/site_perl/whisper/WhisperMode/Systemd.pm 0644
  desktop_stage_role_asset usr/local/bin/labwc-lock /usr/local/bin/labwc-lock 0755
  desktop_stage_role_asset usr/local/bin/labwc-terminal /usr/local/bin/labwc-terminal 0755
  desktop_stage_role_asset usr/local/libexec/labwc-terminal-result /usr/local/libexec/labwc-terminal-result 0755
  desktop_stage_role_asset usr/local/bin/labwc-bluetooth /usr/local/bin/labwc-bluetooth 0755
  desktop_stage_role_asset usr/local/bin/labwc-brightness-control /usr/local/bin/labwc-brightness-control 0755
  desktop_stage_role_asset usr/local/bin/labwc-power-settings /usr/local/bin/labwc-power-settings 0755
  desktop_stage_role_asset usr/local/bin/labwc-run /usr/local/bin/labwc-run 0755
  desktop_stage_role_asset usr/local/bin/labwc-power-menu /usr/local/bin/labwc-power-menu 0755
  desktop_stage_role_asset usr/local/bin/labwc-keyboard-layout /usr/local/bin/labwc-keyboard-layout 0755
  desktop_stage_role_asset usr/local/bin/labwc-capture /usr/local/bin/labwc-capture 0755
  desktop_stage_role_asset usr/local/bin/labwc-wayscriber-toggle /usr/local/bin/labwc-wayscriber-toggle 0755
  desktop_stage_role_asset usr/local/bin/satty /usr/local/bin/satty 0755
  desktop_stage_role_asset usr/local/libexec/apparmor-generate-rules /usr/local/libexec/apparmor-generate-rules 0755
  desktop_stage_role_asset usr/local/libexec/labwc-security-action-root /usr/local/libexec/labwc-security-action-root 0755
  desktop_stage_role_asset usr/local/libexec/labwc-apparmor-policy-worker /usr/local/libexec/labwc-apparmor-policy-worker 0755
  desktop_stage_role_asset usr/local/libexec/labwc-apparmor-boot-state /usr/local/libexec/labwc-apparmor-boot-state 0755
  desktop_stage_role_asset usr/local/libexec/labwc-system-action-root /usr/local/libexec/labwc-system-action-root 0755
  desktop_stage_role_asset usr/local/libexec/labwc-recovery-action-root /usr/local/libexec/labwc-recovery-action-root 0755
  desktop_stage_role_asset usr/local/libexec/labwc-network-control-action-root /usr/local/libexec/labwc-network-control-action-root 0755
  desktop_stage_role_asset usr/local/libexec/labwc-firewall-action-root /usr/local/libexec/labwc-firewall-action-root 0755
  desktop_render_role_target_template \
    usr/local/libexec/labwc-network-scan-action-root.tmpl \
    /usr/local/libexec/labwc-network-scan-action-root \
    0755 \
    ACCOUNT_USERNAME "$ACCOUNT_USERNAME"
  desktop_stage_managed_nmap_scripts
  desktop_stage_role_asset usr/local/sbin/greetd-power-action /usr/local/sbin/greetd-power-action 0755
  desktop_stage_role_asset usr/local/sbin/labwc-notify /usr/local/sbin/labwc-notify 0755
  desktop_stage_role_asset usr/local/libexec/clamav-signature-update /usr/local/libexec/clamav-signature-update 0755

  desktop_stage_role_asset usr/share/wayland-sessions/labwc.desktop /usr/share/wayland-sessions/labwc.desktop 0644
  desktop_stage_role_asset usr/local/share/applications/computer-management.desktop /usr/local/share/applications/computer-management.desktop 0644
  desktop_stage_role_asset usr/local/share/applications/remote-desktop-management.desktop /usr/local/share/applications/remote-desktop-management.desktop 0644
  desktop_stage_role_asset usr/local/share/applications/foot.desktop /usr/local/share/applications/foot.desktop 0644
  desktop_stage_role_asset usr/local/share/applications/labwc-notifications.desktop /usr/local/share/applications/labwc-notifications.desktop 0644
  desktop_render_gtkgreet_css
  desktop_stage_role_asset etc/greetd/gtkgreet-power.css /etc/greetd/gtkgreet-power.css 0644
  desktop_render_greeter_power_rule
  desktop_stage_role_asset etc/fangfrisch.conf /etc/fangfrisch.conf 0644
  desktop_stage_role_asset etc/systemd/system/clamav-signature-update.service /etc/systemd/system/clamav-signature-update.service 0644
  desktop_stage_role_asset etc/systemd/system/clamav-signature-update.service.d/60-resource-class.conf /etc/systemd/system/clamav-signature-update.service.d/60-resource-class.conf 0644
  desktop_stage_role_asset etc/systemd/system/clamav-signature-update.timer /etc/systemd/system/clamav-signature-update.timer 0644
  desktop_stage_role_asset etc/bluetooth/main.conf /etc/bluetooth/main.conf 0644
  desktop_stage_role_asset usr/local/libexec/bluetooth-controller-init /usr/local/libexec/bluetooth-controller-init 0755
  desktop_stage_role_asset etc/systemd/system/bluetooth-controller-init.service /etc/systemd/system/bluetooth-controller-init.service 0644
  desktop_stage_role_asset etc/systemd/system/greetd.service.d/20-labwc-vt.conf /etc/systemd/system/greetd.service.d/20-labwc-vt.conf 0644
  desktop_stage_role_asset etc/systemd/system/bluetooth.service.d/override.conf /etc/systemd/system/bluetooth.service.d/override.conf 0644
  desktop_stage_mullvad_dns_policy
  install -d -m 0700 /target/etc/skel-desktop/.config/autostart
  desktop_stage_mullvad_application_policy
  # Retire the global /dev watcher on installer reruns as well as fresh installs.
  rm -f /target/etc/systemd/system/nvidia-char-links.path \
    /target/etc/systemd/system/multi-user.target.wants/nvidia-char-links.path
  if [ "${LABWC_NVIDIA_ACCELERATION_AVAILABLE:-false}" = true ]; then
    desktop_stage_role_asset etc/systemd/system/nvidia-powerd.service.d/10-device-guard.conf /etc/systemd/system/nvidia-powerd.service.d/10-device-guard.conf 0644
    desktop_stage_role_asset etc/udev/rules.d/71-nvidia-char-links.rules /etc/udev/rules.d/71-nvidia-char-links.rules 0644
    desktop_stage_role_asset usr/local/libexec/nvidia-char-links /usr/local/libexec/nvidia-char-links 0755
    desktop_stage_role_asset etc/systemd/system/nvidia-char-links.service /etc/systemd/system/nvidia-char-links.service 0644
  else
    rm -f \
      /target/etc/systemd/system/nvidia-powerd.service.d/10-device-guard.conf \
      /target/etc/udev/rules.d/71-nvidia-char-links.rules \
      /target/usr/local/libexec/nvidia-char-links \
      /target/etc/systemd/system/nvidia-char-links.service \
      /target/etc/systemd/system/multi-user.target.wants/nvidia-char-links.service
  fi
  # KWallet belongs to the single managed Labwc account. Keep the portal unit
  # account-local so the greeter's independent user manager cannot discover or
  # activate the desktop secret-service stack. Debian's D-Bus activation owns
  # the on-demand kwalletd6 compatibility daemon.
  desktop_stage_role_asset etc/skel-desktop/.config/systemd/user/labwc-kwallet-portal.service /etc/skel-desktop/.config/systemd/user/labwc-kwallet-portal.service 0644
  desktop_stage_role_asset etc/skel-desktop/.config/systemd/user/labwc-output-watch.service /etc/skel-desktop/.config/systemd/user/labwc-output-watch.service 0644
  desktop_stage_role_asset etc/skel-desktop/.config/systemd/user/codex-app-server.service /etc/skel-desktop/.config/systemd/user/codex-app-server.service 0644
  desktop_stage_role_asset etc/skel-desktop/.config/systemd/user/codex-app-server-proxy.service /etc/skel-desktop/.config/systemd/user/codex-app-server-proxy.service 0644
  desktop_stage_role_asset etc/skel-desktop/.config/systemd/user/codex-app-server.socket /etc/skel-desktop/.config/systemd/user/codex-app-server.socket 0644
  desktop_stage_role_asset etc/codex/app-server.env /etc/codex/app-server.env 0644
  desktop_stage_role_asset usr/local/libexec/codex-app-server-wait-ready /usr/local/libexec/codex-app-server-wait-ready 0755
  desktop_stage_role_asset etc/skel-desktop/.config/systemd/user/swaybg.service /etc/skel-desktop/.config/systemd/user/swaybg.service 0644
  if desktop_kanshi_enabled; then
    desktop_stage_role_asset etc/skel-desktop/.config/systemd/user/kanshi.service /etc/skel-desktop/.config/systemd/user/kanshi.service 0644
  fi
  desktop_stage_role_asset etc/skel-desktop/.config/systemd/user/swayidle.service /etc/skel-desktop/.config/systemd/user/swayidle.service 0644
  desktop_stage_role_asset etc/skel-desktop/.config/systemd/user/crystal-dock.service /etc/skel-desktop/.config/systemd/user/crystal-dock.service 0644
  desktop_stage_role_asset etc/skel-desktop/.config/systemd/user/labwc-mute-default-microphone.service /etc/skel-desktop/.config/systemd/user/labwc-mute-default-microphone.service 0644
  if desktop_whisper_addon_selected; then
    desktop_stage_role_asset etc/tmpfiles.d/55-whisper-runtime.conf /etc/tmpfiles.d/55-whisper-runtime.conf 0644
    desktop_stage_role_asset etc/skel-desktop/.config/systemd/user/whisper-record.service /etc/skel-desktop/.config/systemd/user/whisper-record.service 0644
    desktop_stage_role_asset etc/skel-desktop/.config/systemd/user/whisper-transcribe.service /etc/skel-desktop/.config/systemd/user/whisper-transcribe.service 0644
    if desktop_whisper_persistent_memory_enabled; then
      desktop_stage_role_asset etc/skel-desktop/.config/systemd/user/whisper-server.service /etc/skel-desktop/.config/systemd/user/whisper-server.service 0644
    fi
  fi
  # systemd dependency directives cannot be removed from a vendor unit with a
  # drop-in. Install the complete managed unit so no graphical-session.target
  # dependency survives Debian's Waybar unit. Labwc autostart requests it only
  # after activating the compositor session target, so LABWC_ENABLE_WAYBAR
  # remains the authoritative policy gate.
  desktop_stage_role_asset etc/skel-desktop/.config/systemd/user/waybar.service /etc/skel-desktop/.config/systemd/user/waybar.service 0644
  desktop_stage_role_asset etc/skel-desktop/.config/systemd/user/waybar.service.d/20-tray-compat.conf /etc/skel-desktop/.config/systemd/user/waybar.service.d/20-tray-compat.conf 0644
  if [ -x /target/opt/microsoft/msedge/msedge ]; then
    install -d -m 0755 /target/opt/microsoft/msedge/extensions
  fi
  desktop_stage_role_asset etc/wireplumber/wireplumber.conf.d/10-disable-bluez-midi.conf /etc/wireplumber/wireplumber.conf.d/10-disable-bluez-midi.conf 0644
  desktop_stage_role_asset etc/wireplumber/wireplumber.conf.d/20-audio-policy.conf /etc/wireplumber/wireplumber.conf.d/20-audio-policy.conf 0644
  desktop_stage_role_asset etc/pipewire/client.conf.d/20-volume-ceiling.conf /etc/pipewire/client.conf.d/20-volume-ceiling.conf 0644
  desktop_stage_role_asset etc/pipewire/pipewire-pulse.conf.d/20-volume-ceiling.conf /etc/pipewire/pipewire-pulse.conf.d/20-volume-ceiling.conf 0644
  desktop_stage_role_asset etc/apt/listchanges.conf /etc/apt/listchanges.conf 0644
  desktop_stage_role_asset etc/apt/apt.conf.d/60desktop-local-mail.conf /etc/apt/apt.conf.d/60desktop-local-mail.conf 0644
  desktop_stage_role_asset etc/chromium/policies/managed/telemetry.json /etc/chromium/policies/managed/telemetry.json 0644
  desktop_stage_role_asset etc/chromium/policies/managed/security.json /etc/chromium/policies/managed/security.json 0644
  desktop_stage_role_asset etc/chromium/policies/managed/performance.json /etc/chromium/policies/managed/performance.json 0644
  desktop_stage_role_asset etc/chromium/policies/recommended/defaults.json /etc/chromium/policies/recommended/defaults.json 0644
  desktop_stage_role_asset etc/opt/edge/policies/managed/telemetry.json /etc/opt/edge/policies/managed/telemetry.json 0644
  desktop_stage_role_asset etc/opt/edge/policies/managed/security.json /etc/opt/edge/policies/managed/security.json 0644
  desktop_stage_role_asset etc/opt/edge/policies/managed/performance.json /etc/opt/edge/policies/managed/performance.json 0644
  desktop_stage_role_asset etc/opt/edge/policies/recommended/defaults.json /etc/opt/edge/policies/recommended/defaults.json 0644
  desktop_stage_role_asset etc/vivaldi/policies/managed/telemetry.json /etc/vivaldi/policies/managed/telemetry.json 0644
  desktop_stage_role_asset etc/vivaldi/policies/managed/extensions.json /etc/vivaldi/policies/managed/extensions.json 0644
  desktop_stage_role_asset etc/vivaldi/policies/managed/security.json /etc/vivaldi/policies/managed/security.json 0644
  desktop_stage_role_asset etc/vivaldi/policies/managed/performance.json /etc/vivaldi/policies/managed/performance.json 0644
  desktop_stage_role_asset etc/vivaldi/policies/recommended/defaults.json /etc/vivaldi/policies/recommended/defaults.json 0644
  desktop_stage_role_asset etc/opt/chrome/policies/managed/security.json /etc/opt/chrome/policies/managed/security.json 0644
  desktop_stage_role_asset etc/opt/chrome/policies/managed/telemetry.json /etc/opt/chrome/policies/managed/telemetry.json 0644
  desktop_stage_role_asset etc/opt/chrome/policies/managed/performance.json /etc/opt/chrome/policies/managed/performance.json 0644
  desktop_stage_role_asset etc/opt/chrome/policies/recommended/defaults.json /etc/opt/chrome/policies/recommended/defaults.json 0644
  desktop_stage_role_asset usr/local/bin/browser-devtools /usr/local/bin/browser-devtools 0755
  desktop_stage_role_asset usr/local/libexec/install-browser-imports /usr/local/libexec/install-browser-imports 0755
  desktop_stage_role_asset usr/local/share/browser-imports/noscript_data.txt /usr/local/share/browser-imports/noscript_data.txt 0600
  desktop_stage_role_asset usr/local/share/browser-imports/my-ubol-settings.json /usr/local/share/browser-imports/my-ubol-settings.json 0600
  desktop_stage_role_asset usr/local/share/browser-imports/PrivacyBadger_user_data-9_6_2026_1_50_43_PM.json /usr/local/share/browser-imports/PrivacyBadger_user_data-9_6_2026_1_50_43_PM.json 0600
  desktop_stage_role_asset usr/local/share/browser-imports/bookmark-coverage.json /usr/local/share/browser-imports/bookmark-coverage.json 0600
  desktop_stage_role_asset usr/local/share/browser-imports/BROWSER-IMPORTS.md /usr/local/share/browser-imports/BROWSER-IMPORTS.md 0600
  chmod 0700 /target/usr/local/share/browser-imports
  desktop_stage_role_asset \
    usr/share/glib-2.0/schemas/90-desktop-wsdd.gschema.override \
    /usr/share/glib-2.0/schemas/90-desktop-wsdd.gschema.override \
    0644
  desktop_stage_role_asset etc/xdg/xdg-desktop-portal/labwc-portals.conf /etc/xdg/xdg-desktop-portal/labwc-portals.conf 0644
  desktop_stage_role_asset etc/skel-desktop/.gnupg/gpg-agent.conf /etc/skel-desktop/.gnupg/gpg-agent.conf 0600
  chmod 0700 /target/etc/skel-desktop/.gnupg
  desktop_stage_role_asset etc/skel-desktop/.config/systemd/user/labwc-calendar-sync.service /etc/skel-desktop/.config/systemd/user/labwc-calendar-sync.service 0644
  desktop_stage_role_asset etc/skel-desktop/.config/systemd/user/labwc-calendar-sync.timer /etc/skel-desktop/.config/systemd/user/labwc-calendar-sync.timer 0644

  desktop_extract_role_wallpaper_archive
  # Publish explicit defaults after archive extraction, so an archive member
  # cannot overwrite a differently named user-selected default.
  desktop_stage_role_asset "${LABWC_WALLPAPER_DESKTOP_SWAYBG#hooks/target/}" "$LABWC_WALLPAPER_PATH" 0644
  desktop_stage_role_asset "${LABWC_WALLPAPER_LOCKSCREEN_SWAYLOCK#hooks/target/}" "$LABWC_LOCK_BACKGROUND_PATH" 0644
  desktop_stage_role_asset "${LABWC_WALLPAPER_LOGIN_GTKGREET#hooks/target/}" "$LABWC_GREETER_BACKGROUND_PATH" 0644
  desktop_normalize_background_directories
#  desktop_stage_role_asset_tree usr/share/backgrounds/other /usr/share/backgrounds/other

  desktop_stage_role_asset etc/skel-desktop/.config/labwc/autostart /etc/skel-desktop/.config/labwc/autostart 0755
  desktop_stage_role_asset etc/skel-desktop/.config/labwc/shutdown /etc/skel-desktop/.config/labwc/shutdown 0755
  desktop_stage_labwc_user_session_assets
  remove_target_asset /etc/skel-desktop/.config/labwc/xinitrc
  remove_target_asset /etc/skel-desktop/.config/gsimplecal/config
  desktop_stage_role_asset etc/skel-desktop/.config/labwc/themerc-override /etc/skel-desktop/.config/labwc/themerc-override 0644
  desktop_stage_role_asset etc/skel-desktop/.config/waypaper/config.ini /etc/skel-desktop/.config/waypaper/config.ini 0644
  desktop_stage_role_asset etc/skel-desktop/.config/waypaper/keybindings.ini /etc/skel-desktop/.config/waypaper/keybindings.ini 0644
  desktop_stage_role_asset etc/skel-desktop/.config/waypaper/style.css /etc/skel-desktop/.config/waypaper/style.css 0644
  desktop_render_labwc_rc_xml
  desktop_render_role_target_template \
    "etc/skel-desktop/.config/labwc/menu.xml" \
    "/etc/skel-desktop/.config/labwc/menu.xml" \
    0644 \
    ACCOUNT_HOME "$ACCOUNT_HOME"
  desktop_render_waybar_config
  desktop_render_waybar_style
  desktop_render_kanshi_config
  desktop_render_terminal_configs
  desktop_stage_role_asset etc/skel-desktop/.config/mpv/mpv.conf /etc/skel-desktop/.config/mpv/mpv.conf 0644
  desktop_stage_role_asset etc/skel-desktop/.config/mpv/input.conf /etc/skel-desktop/.config/mpv/input.conf 0644
  desktop_stage_role_asset etc/skel-desktop/.config/featherpad/fp.conf /etc/skel-desktop/.config/featherpad/fp.conf 0644
  desktop_stage_role_asset etc/skel-desktop/.config/GottCode/FocusWriter.conf /etc/skel-desktop/.config/GottCode/FocusWriter.conf 0644
  desktop_stage_role_asset etc/skel-desktop/.config/zathura/zathurarc /etc/skel-desktop/.config/zathura/zathurarc 0644
  desktop_stage_role_asset usr/local/bin/labwc-focuswriter-import /usr/local/bin/labwc-focuswriter-import 0755
  desktop_stage_role_asset usr/local/share/applications/labwc-focuswriter-import.desktop /usr/local/share/applications/labwc-focuswriter-import.desktop 0644
  desktop_stage_role_asset etc/skel-desktop/.local/share/GottCode/FocusWriter/Themes/word.theme /etc/skel-desktop/.local/share/GottCode/FocusWriter/Themes/word.theme 0644
  desktop_stage_role_asset etc/skel-desktop/.config/Recoll.org/recoll.ini /etc/skel-desktop/.config/Recoll.org/recoll.ini 0600
  chmod 0700 /target/etc/skel-desktop/.config/Recoll.org
  desktop_stage_role_asset etc/skel-desktop/.recoll/recoll.conf /etc/skel-desktop/.recoll/recoll.conf 0644
  chmod 0700 /target/etc/skel-desktop/.recoll
  install -d -m 0700 /target/etc/skel-desktop/.cache /target/etc/skel-desktop/.cache/recoll
  desktop_stage_role_asset etc/skel-desktop/.config/kdiff3rc /etc/skel-desktop/.config/kdiff3rc 0644
  desktop_stage_role_asset etc/skel-desktop/.config/micro/settings.json /etc/skel-desktop/.config/micro/settings.json 0644
  desktop_stage_role_asset etc/skel-desktop/.config/nano/nanorc /etc/skel-desktop/.config/nano/nanorc 0644
  desktop_stage_role_asset etc/skel-desktop/.config/nvim/init.lua /etc/skel-desktop/.config/nvim/init.lua 0644
  desktop_stage_role_asset etc/skel-desktop/.config/qalculate/qalc.cfg /etc/skel-desktop/.config/qalculate/qalc.cfg 0644
  desktop_stage_role_asset etc/skel-desktop/.config/qalculate/qalculate-qt.cfg /etc/skel-desktop/.config/qalculate/qalculate-qt.cfg 0644
  install -d -m 0700 /target/etc/skel-desktop/.config/xarchiver
  desktop_render_role_target_template \
    etc/skel-desktop/.config/xarchiver/xarchiverrc \
    /etc/skel-desktop/.config/xarchiver/xarchiverrc \
    0600 \
    ACCOUNT_USERNAME "$ACCOUNT_USERNAME" \
    ACCOUNT_HOME "$ACCOUNT_HOME"
  desktop_stage_role_asset etc/skel-desktop/.config/task/taskrc /etc/skel-desktop/.config/task/taskrc 0644
  install -d -m 0700 /target/etc/skel-desktop/.local/share/task /target/etc/skel-desktop/.local/share/task/hooks
  desktop_stage_role_asset etc/skel-desktop/.config/vim/vimrc /etc/skel-desktop/.config/vim/vimrc 0644
  desktop_render_note_app_defaults
  desktop_compile_glib_schemas
  desktop_stage_role_asset etc/skel-desktop/.config/xdg-terminals.list /etc/skel-desktop/.config/xdg-terminals.list 0644
  desktop_stage_role_asset etc/skel-desktop/.config/mimeapps.list /etc/skel-desktop/.config/mimeapps.list 0600
  desktop_stage_role_asset etc/xdg/mimeapps.list /etc/xdg/mimeapps.list 0644
  desktop_stage_role_asset usr/share/mime/packages/90-desktop-filetypes.xml /usr/share/mime/packages/90-desktop-filetypes.xml 0644
  run_in_target "update managed desktop MIME database" /bin/sh -eu -c '
test -x /usr/bin/update-mime-database
/usr/bin/update-mime-database /usr/share/mime
' sh
  desktop_stage_role_asset etc/skel-desktop/.config/xfce4/helpers.rc /etc/skel-desktop/.config/xfce4/helpers.rc 0644
  desktop_stage_role_asset etc/skel-desktop/.config/xfce4/xfconf/xfce-perchannel-xml/thunar.xml /etc/skel-desktop/.config/xfce4/xfconf/xfce-perchannel-xml/thunar.xml 0644
  desktop_stage_role_asset etc/skel-desktop/.config/retroarch/retroarch.cfg /etc/skel-desktop/.config/retroarch/retroarch.cfg 0644
  install -d -m 0700 /target/etc/skel-desktop/.config/sleek/userData
  desktop_stage_role_asset etc/skel-desktop/.config/sleek/userData/colors.json /etc/skel-desktop/.config/sleek/userData/colors.json 0600
  desktop_render_role_target_template \
    "etc/skel-desktop/.config/sleek/userData/config.json.tmpl" \
    "/etc/skel-desktop/.config/sleek/userData/config.json" \
    0600 \
    ACCOUNT_HOME "$ACCOUNT_HOME"
  desktop_stage_role_asset etc/skel-desktop/.config/sleek/userData/filters.json /etc/skel-desktop/.config/sleek/userData/filters.json 0600
  desktop_stage_role_asset usr/share/xfce4/helpers/foot.desktop /usr/share/xfce4/helpers/foot.desktop 0644
  desktop_stage_role_asset etc/skel-desktop/.config/fontconfig/conf.d/60-labwc-terminal-fonts.conf /etc/skel-desktop/.config/fontconfig/conf.d/60-labwc-terminal-fonts.conf 0644
  desktop_stage_role_asset etc/skel-desktop/.config/fontconfig/conf.d/61-microsoft-fonts.conf /etc/skel-desktop/.config/fontconfig/conf.d/61-microsoft-fonts.conf 0644
  desktop_stage_role_asset etc/skel-desktop/.profile /etc/skel-desktop/.profile 0644
  desktop_stage_role_asset etc/skel-desktop/.bash_profile /etc/skel-desktop/.bash_profile 0644
  desktop_stage_role_asset etc/skel-desktop/.bashrc /etc/skel-desktop/.bashrc 0644
  desktop_stage_role_asset etc/skel-desktop/.bash_aliases /etc/skel-desktop/.bash_aliases 0644
  install -d -m 0755 /target/etc/skel-desktop/.profile.d
  desktop_stage_role_asset etc/skel-desktop/.profile.d/71-devops-de.sh /etc/skel-desktop/.profile.d/71-devops-de.sh 0644
  install -d -m 0755 /target/etc/skel-desktop/.config/cargo
  desktop_render_cargo_config
  install -d -m 0755 /target/etc/skel-desktop/.config/mise/conf.d
  desktop_stage_role_asset etc/skel-desktop/.config/mise/config.toml /etc/skel-desktop/.config/mise/config.toml 0644
  desktop_stage_role_asset etc/skel-desktop/.config/mise/config.development.toml /etc/skel-desktop/.config/mise/config.development.toml 0644
  desktop_stage_role_asset etc/skel-desktop/.config/mise/config.local.toml /etc/skel-desktop/.config/mise/config.local.toml 0644
  desktop_stage_role_asset etc/skel-desktop/.config/mise/config.development.local.toml /etc/skel-desktop/.config/mise/config.development.local.toml 0644
  desktop_stage_role_asset etc/skel-desktop/.config/mise/conf.d/10-tools.toml /etc/skel-desktop/.config/mise/conf.d/10-tools.toml 0644
  desktop_stage_role_asset etc/skel-desktop/.zshenv /etc/skel-desktop/.zshenv 0644
  desktop_stage_role_asset etc/skel-desktop/.zprofile /etc/skel-desktop/.zprofile 0644
  desktop_stage_role_asset usr/local/bin/debugsys /usr/local/bin/debugsys 0755
  desktop_stage_role_asset usr/local/libexec/debugsys.py /usr/local/libexec/debugsys.py 0755
  desktop_stage_role_asset usr/local/libexec/debugsys-initramfs /usr/local/libexec/debugsys-initramfs 0755
  desktop_stage_role_asset usr/local/share/debugsys/initramfs/hook /usr/local/share/debugsys/initramfs/hook 0755
  desktop_stage_role_asset etc/systemd/system/debugsys-boot-report.service /etc/systemd/system/debugsys-boot-report.service 0644
  desktop_stage_role_asset usr/local/bin/gitops /usr/local/bin/gitops 0755
  desktop_stage_role_asset usr/local/share/doc/git/README.md /usr/local/share/doc/git/README.md 0644
  desktop_stage_role_asset etc/gitops/aliases.gitconfig /etc/gitops/aliases.gitconfig 0644
  desktop_stage_role_asset etc/skel-desktop/.config/gitops/gitops.env /etc/skel-desktop/.config/gitops/gitops.env 0600
  desktop_stage_role_asset etc/skel-desktop/.config/git/config /etc/skel-desktop/.config/git/config 0644
  desktop_stage_role_asset usr/local/libexec/ssh-checks /usr/local/libexec/ssh-checks 0644
  desktop_stage_role_asset usr/local/libexec/labwc-ssh-key-load /usr/local/libexec/labwc-ssh-key-load 0755
  desktop_stage_role_asset usr/local/libexec/labwc-ssh-gpg-askpass /usr/local/libexec/labwc-ssh-gpg-askpass 0755
  desktop_stage_role_asset usr/local/bin/git-ssh /usr/local/bin/git-ssh 0755
  desktop_stage_role_asset etc/skel-desktop/.config/systemd/user/labwc-ssh-key-load.service /etc/skel-desktop/.config/systemd/user/labwc-ssh-key-load.service 0644
  desktop_stage_role_asset etc/systemd/user/ssh-agent.socket.d/10-labwc-session.conf /etc/systemd/user/ssh-agent.socket.d/10-labwc-session.conf 0644
  desktop_stage_role_asset etc/systemd/user/ssh-agent.service.d/10-labwc-session.conf /etc/systemd/user/ssh-agent.service.d/10-labwc-session.conf 0644
  desktop_stage_role_asset etc/skel-desktop/.zshrc /etc/skel-desktop/.zshrc 0644
  desktop_stage_role_asset etc/skel-desktop/.zlogout /etc/skel-desktop/.zlogout 0644
  desktop_stage_role_asset etc/skel-desktop/.zsh_aliases /etc/skel-desktop/.zsh_aliases 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/skel-desktop/.dircolors)" /etc/skel-desktop/.dircolors 0644
  desktop_log "staged_asset source=$(installer_repo_join_var DIR_HOOKS_TARGET etc/skel-desktop/.dircolors) target=/etc/skel-desktop/.dircolors mode=0644"
  desktop_stage_role_asset etc/skel-desktop/.config/starship.toml /etc/skel-desktop/.config/starship.toml 0644
  desktop_stage_role_asset etc/skel-desktop/.config/btop/btop.conf /etc/skel-desktop/.config/btop/btop.conf 0644
  desktop_stage_role_asset etc/skel-desktop/.config/fzf/default-opts /etc/skel-desktop/.config/fzf/default-opts 0644
  desktop_render_fuzzel_configs
  desktop_stage_role_asset etc/skel-desktop/.config/Thunar/uca.xml /etc/skel-desktop/.config/Thunar/uca.xml 0644
  desktop_stage_role_asset etc/skel-desktop/.config/tesseract/ocr-defaults.conf /etc/skel-desktop/.config/tesseract/ocr-defaults.conf 0644
  desktop_stage_role_asset etc/skel-desktop/.config/tesseract/user-words/default.user-words /etc/skel-desktop/.config/tesseract/user-words/default.user-words 0644
  desktop_stage_role_asset etc/skel-desktop/.config/tesseract/user-words/eng.user-words /etc/skel-desktop/.config/tesseract/user-words/eng.user-words 0644
  desktop_stage_role_asset etc/skel-desktop/.config/tesseract/user-words/swe.user-words /etc/skel-desktop/.config/tesseract/user-words/swe.user-words 0644
  desktop_stage_role_asset etc/skel-desktop/.config/tesseract/user-patterns/default.user-patterns /etc/skel-desktop/.config/tesseract/user-patterns/default.user-patterns 0644
  desktop_stage_role_asset etc/skel-desktop/.config/tesseract/user-patterns/eng.user-patterns /etc/skel-desktop/.config/tesseract/user-patterns/eng.user-patterns 0644
  desktop_stage_role_asset etc/skel-desktop/.config/tesseract/user-patterns/swe.user-patterns /etc/skel-desktop/.config/tesseract/user-patterns/swe.user-patterns 0644
  desktop_render_crystal_dock_appearance
  desktop_stage_role_asset etc/skel-desktop/.config/crystal-dock/labwc/panel_1.conf /etc/skel-desktop/.config/crystal-dock/labwc/panel_1.conf 0644
  desktop_stage_role_asset etc/skel-desktop/.config/crystal-dock/labwc/panel_1.conf /etc/xdg/crystal-dock/labwc/panel_1.conf 0644
  desktop_stage_role_asset usr/local/bin/labwc-show-desktop /usr/local/bin/labwc-show-desktop 0755
  desktop_stage_role_asset usr/local/bin/labwc-health-notify /usr/local/bin/labwc-health-notify 0755
  desktop_stage_role_asset usr/local/share/applications/show-desktop.desktop /usr/local/share/applications/show-desktop.desktop 0644
  desktop_normalize_public_desktop_directories
  desktop_stage_role_asset usr/local/share/applications/labwc-tweaks.desktop /usr/local/share/applications/labwc-tweaks.desktop 0644
  desktop_stage_role_asset usr/local/share/applications/hyprpolkitagent.desktop /usr/local/share/applications/hyprpolkitagent.desktop 0644
  desktop_stage_role_asset usr/local/share/icons/hicolor/64x64/apps/show-desktop.png /usr/local/share/icons/hicolor/64x64/apps/show-desktop.png 0644
  desktop_stage_role_asset etc/skel-desktop/.config/mako/config /etc/skel-desktop/.config/mako/config 0644
  desktop_stage_role_asset etc/skel-desktop/.config/satty/config.toml /etc/skel-desktop/.config/satty/config.toml 0644
  desktop_stage_role_asset etc/skel-desktop/.config/wayscriber/config.toml /etc/skel-desktop/.config/wayscriber/config.toml 0644
  desktop_stage_role_asset etc/skel-desktop/.config/satty/overrides.css /etc/skel-desktop/.config/satty/overrides.css 0644
  desktop_stage_role_asset etc/skel-desktop/.config/swaylock/config /etc/skel-desktop/.config/swaylock/config 0644
  desktop_stage_role_asset etc/skel-desktop/.config/wireplumber/wireplumber.conf.d/10-disable-bluez-midi.conf /etc/skel-desktop/.config/wireplumber/wireplumber.conf.d/10-disable-bluez-midi.conf 0644
  desktop_stage_role_asset etc/skel-desktop/.config/wireplumber/wireplumber.conf.d/20-audio-policy.conf /etc/skel-desktop/.config/wireplumber/wireplumber.conf.d/20-audio-policy.conf 0644
  desktop_render_gtk_settings
  desktop_render_qt6ct_config
  desktop_stage_role_asset etc/skel-desktop/.config/kwalletrc /etc/skel-desktop/.config/kwalletrc 0644
  install -d -m 0700 \
    /target/etc/skel-desktop/.config/Code/User \
    /target/etc/skel-desktop/.config/chromium/Default \
    /target/etc/skel-desktop/.config/microsoft-edge/Default \
    /target/etc/skel-desktop/.config/obsidian \
    /target/etc/skel-desktop/.config/vivaldi/Default
  desktop_stage_role_asset etc/skel-desktop/.config/Code/User/settings.json /etc/skel-desktop/.config/Code/User/settings.json 0600
  desktop_stage_role_asset etc/skel-desktop/.config/chromium/Default/Preferences /etc/skel-desktop/.config/chromium/Default/Preferences 0600
  desktop_stage_role_asset etc/skel-desktop/.config/microsoft-edge/Default/Preferences /etc/skel-desktop/.config/microsoft-edge/Default/Preferences 0600
  desktop_stage_role_asset etc/skel-desktop/.config/obsidian/obsidian.json /etc/skel-desktop/.config/obsidian/obsidian.json 0600
  desktop_stage_role_asset etc/skel-desktop/.config/vivaldi/Default/Preferences /etc/skel-desktop/.config/vivaldi/Default/Preferences 0600
  desktop_stage_obsidian_default_vault
  install -d -m 0700 /target/etc/skel-desktop/.config/keepassxc
  desktop_stage_role_asset etc/skel-desktop/.config/keepassxc/keepassxc.ini /etc/skel-desktop/.config/keepassxc/keepassxc.ini 0600
  chmod 0700 /target/etc/skel-desktop/.config/keepassxc
  install -d -m 0700 /target/etc/skel-desktop/.config/zoom
  desktop_stage_role_asset etc/skel-desktop/.config/zoom/zoomus.conf /etc/skel-desktop/.config/zoom/zoomus.conf 0600
  chmod 0700 /target/etc/skel-desktop/.config/zoom
  desktop_stage_role_asset etc/skel-desktop/.config/xdg-desktop-portal/portals.conf /etc/skel-desktop/.config/xdg-desktop-portal/portals.conf 0644
  desktop_stage_role_asset etc/skel-desktop/.config/user-dirs.dirs /etc/skel-desktop/.config/user-dirs.dirs 0644
  desktop_render_chromium_flags
}

