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
  desktop_stage_role_asset usr/local/libexec/labwc-wallpaper-control /usr/local/libexec/labwc-wallpaper-control 0755
  desktop_stage_role_asset usr/local/libexec/labwc-notification-send /usr/local/libexec/labwc-notification-send 0755
  desktop_stage_role_asset usr/local/libexec/labwc-configure-session-repairs /usr/local/libexec/labwc-configure-session-repairs 0755
  desktop_stage_role_asset etc/security/sudo-i.conf /etc/security/sudo-i.conf 0644
  desktop_stage_role_asset etc/security/cron-session.conf /etc/security/cron-session.conf 0644
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

desktop_stage_key_manager() (
  set -eu
  for directory in /usr/local/bin /usr/local/lib /usr/local/lib/python3.14 \
    /usr/local/lib/python3.14/dist-packages /usr/local/lib/python3.14/dist-packages/managed_workflows \
    /usr/local/lib/python3.14/dist-packages/key_manager /usr/local/share \
    /usr/local/share/key-manager /etc/key-manager; do
    ensure_target_asset_parent "${directory}/.installer-parent"
    host_directory=$(target_asset_host_path "$directory")
    [ ! -L "$host_directory" ] || installer_fatal "unsafe key-manager directory: $directory"
    chown root:root "$host_directory"
    chmod 0755 "$host_directory"
  done
  desktop_stage_role_asset usr/local/bin/key-manager /usr/local/bin/key-manager 0755
  desktop_stage_role_asset etc/skel-desktop/.gnupg/gpg-agent.conf \
    /usr/local/share/key-manager/gpg-agent.conf 0644
  for module in __init__ fs; do
    path="usr/local/lib/python3.14/dist-packages/managed_workflows/${module}.py"
    desktop_stage_role_asset "$path" "/$path" 0644
  done
  for module in __init__ core cli ssh gpg tls tls_profiles pqc; do
    path="usr/local/lib/python3.14/dist-packages/key_manager/${module}.py"
    desktop_stage_role_asset "$path" "/$path" 0644
  done
  desktop_render_role_target_template etc/key-manager/settings.json.tmpl \
    /etc/key-manager/settings.json 0644 \
    DIR_DATA_PKI "$DIR_DATA_PKI" ACCOUNT_USERNAME "$ACCOUNT_USERNAME"
  desktop_stage_role_asset etc/key-manager/certbot.ini /etc/key-manager/certbot.ini 0644
  desktop_stage_role_asset etc/systemd/system/key-manager-acme-renew.timer \
    /etc/systemd/system/key-manager-acme-renew.timer 0644
  desktop_render_role_target_template etc/systemd/system/key-manager-acme-renew.service.tmpl \
    /etc/systemd/system/key-manager-acme-renew.service 0644 DIR_DATA_PKI "$DIR_DATA_PKI"
)

desktop_stage_fangfrisch() (
  set -eu
  set +x
  set +v
  fangfrisch_stage=$(target_private_stage_dir fangfrisch)
  fangfrisch_stage_host=$(target_asset_host_path "$fangfrisch_stage")
  trap 'rm -rf -- "$fangfrisch_stage_host"' 0
  trap 'exit 129' HUP
  trap 'exit 130' INT
  trap 'exit 143' TERM
  stage_target_asset "$(installer_repo_join_var DIR_SCRIPTS_DESKTOP fangfrisch-configure.py)" \
    "${fangfrisch_stage}/configure.py" 0600
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/fangfrisch.conf)" \
    "${fangfrisch_stage}/fangfrisch.conf" 0600
  if fangfrisch_key=$(preseed_env_read_value urlhaus_authkey); then
    :
  else
    fangfrisch_credential_status=$?
    case "$fangfrisch_credential_status" in
      1) fangfrisch_key= ;;
      *) installer_fatal "unsafe URLhaus private credential input"; exit 1 ;;
    esac
  fi
  (umask 077; printf '%s' "$fangfrisch_key" >"${fangfrisch_stage_host}/auth-key")
  unset fangfrisch_key
  run_in_target "configure optional URLhaus authentication privately" \
    /usr/bin/env -i HOME=/root LC_ALL=C PATH=/usr/sbin:/usr/bin:/sbin:/bin \
    /usr/bin/python3 -I -S -B "${fangfrisch_stage}/configure.py" "$fangfrisch_stage"
)

desktop_stage_target_assets() {
  desktop_stage_key_manager
  desktop_stage_appearance
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
  desktop_stage_role_asset etc/security/greetd-greeter.conf /etc/security/greetd-greeter.conf 0644
  desktop_render_role_target_template \
    etc/dbus-1/session.d/70-labwc-greeter-no-portals.conf.tmpl \
    /etc/dbus-1/session.d/70-labwc-greeter-no-portals.conf 0644 \
    LABWC_GREETER_USER "$LABWC_GREETER_USER"
  desktop_stage_role_asset etc/pam.d/swaylock /etc/pam.d/swaylock 0644
  desktop_stage_role_asset etc/systemd/logind.conf.d/70-labwc-lock.conf /etc/systemd/logind.conf.d/70-labwc-lock.conf 0644
  desktop_stage_role_asset usr/share/pam-configs/wtmpdb /usr/share/pam-configs/wtmpdb 0644
  desktop_reconcile_wtmpdb_common_session /target
  desktop_render_labwc_session_wrappers
  # systemd's dash-prefix drop-ins also cover future application names and
  # transient UUIDs. Keep session daemons outside these application families.
  for application_family in wayland electron native devops bitwarden qbittorrent compat; do
    desktop_stage_role_asset etc/systemd/user/labwc-native-.service.d/50-app-lifecycle.conf \
      "/etc/systemd/user/labwc-${application_family}-.service.d/50-app-lifecycle.conf" 0644
  done
  desktop_stage_role_asset etc/systemd/user/labwc-wayland-foot-.service.d/60-terminal-lifecycle.conf \
    /etc/systemd/user/labwc-wayland-foot-.service.d/60-terminal-lifecycle.conf 0644
  desktop_stage_role_asset etc/systemd/user/labwc-devops-.service.d/60-stop-budget.conf \
    /etc/systemd/user/labwc-devops-.service.d/60-stop-budget.conf 0644
  desktop_configure_local_mail_delivery
  desktop_stage_role_asset usr/local/bin/labwc-autostart /usr/local/bin/labwc-autostart 0755
  desktop_stage_role_asset usr/local/bin/labwc-wallpaper-save /usr/local/bin/labwc-wallpaper-save 0755
  desktop_stage_role_asset usr/local/bin/labwc-admin-action /usr/local/bin/labwc-admin-action 0755
  desktop_stage_role_asset usr/local/libexec/labwc-admin-action-root /usr/local/libexec/labwc-admin-action-root 0755
  desktop_stage_role_asset usr/local/libexec/labwc-admin-action-worker /usr/local/libexec/labwc-admin-action-worker 0755
  desktop_stage_role_asset usr/local/libexec/labwc-logout-root /usr/local/libexec/labwc-logout-root 0755
  desktop_stage_role_asset usr/local/libexec/labwc-session-state /usr/local/libexec/labwc-session-state 0755
  desktop_stage_role_asset etc/skel-desktop/.config/systemd/user/labwc-session-state@.service /etc/skel-desktop/.config/systemd/user/labwc-session-state@.service 0644
  desktop_stage_role_asset etc/skel-desktop/.config/systemd/user/labwc-session-state@prepare.service.d/retain-result.conf /etc/skel-desktop/.config/systemd/user/labwc-session-state@prepare.service.d/retain-result.conf 0644
  desktop_stage_role_asset etc/systemd/system/labwc-admin-action@.service.tmpl /etc/systemd/system/labwc-admin-action@.service 0644
  desktop_stage_role_asset etc/systemd/system/labwc-external-drives-shutdown.service /etc/systemd/system/labwc-external-drives-shutdown.service 0644
  desktop_stage_role_asset etc/systemd/system/labwc-package-sleep-guard.service.tmpl /etc/systemd/system/labwc-package-sleep-guard.service 0644
  desktop_stage_role_asset etc/systemd/system/sleep.target.d/50-package-lock-guard.conf /etc/systemd/system/sleep.target.d/50-package-lock-guard.conf 0644
  desktop_stage_role_asset usr/local/libexec/greetd-power-action-root /usr/local/libexec/greetd-power-action-root 0755
  desktop_stage_role_asset usr/local/libexec/calix-fruux-bootstrap /usr/local/libexec/calix-fruux-bootstrap 0755
  desktop_stage_role_asset usr/local/libexec/labwc-waycal-control /usr/local/libexec/labwc-waycal-control 0755
  desktop_stage_role_asset usr/local/libexec/labwc-waycal-popup /usr/local/libexec/labwc-waycal-popup 0755
  desktop_stage_role_asset etc/skel-desktop/.config/gtk-4.0/gtk.css /etc/skel-desktop/.config/gtk-4.0/gtk.css 0644
  desktop_stage_role_asset etc/skel-desktop/.config/waycal/style.css /etc/skel-desktop/.config/waycal/style.css 0644
  desktop_stage_role_asset usr/local/share/applications/com.ianswope.Calix.desktop /usr/local/share/applications/com.ianswope.Calix.desktop 0644
  desktop_stage_role_asset usr/local/share/applications/labwc-calendar-actions.desktop /usr/local/share/applications/labwc-calendar-actions.desktop 0644
  # Public commands share the managed launcher, including terminal launches.
  for calendar_alias in labwc-agenda labwc-calendar; do
    ensure_target_asset_parent "/usr/local/bin/$calendar_alias"
    calendar_alias_host=$(target_asset_host_path "/usr/local/bin/$calendar_alias")
    ln -sfnT labwc-app "$calendar_alias_host"
  done
  unset calendar_alias calendar_alias_host
  desktop_stage_role_asset usr/local/libexec/labwc-calendar-actions /usr/local/libexec/labwc-calendar-actions 0755
  desktop_stage_role_asset usr/local/libexec/labwc-calendar-worker /usr/local/libexec/labwc-calendar-worker 0755
  desktop_stage_role_asset usr/local/share/applications/com.github.dahenson.agenda.desktop /usr/local/share/applications/com.github.dahenson.agenda.desktop 0644
  desktop_stage_role_asset usr/local/share/agenda/schemas/90-desktop-agenda.gschema.override /usr/local/share/agenda/schemas/90-desktop-agenda.gschema.override 0644
  desktop_render_role_target_template etc/systemd/system/fruux-firstboot.service.tmpl \
    /etc/systemd/system/fruux-firstboot.service 0644 \
    ACCOUNT_USERNAME "$ACCOUNT_USERNAME" ACCOUNT_HOME "$ACCOUNT_HOME"
  desktop_render_role_target_template var/lib/firstboot/bin/fruux-cleanup.tmpl \
    /var/lib/firstboot/bin/fruux-cleanup 0755 ACCOUNT_USERNAME "$ACCOUNT_USERNAME"
  desktop_stage_role_asset etc/systemd/system/greetd.service.d/40-fruux-firstboot.conf \
    /etc/systemd/system/greetd.service.d/40-fruux-firstboot.conf 0644
  for calendar_unit in labwc-calendar-credentials; do
    desktop_stage_role_asset "etc/skel-desktop/.config/systemd/user/${calendar_unit}.service" "/etc/skel-desktop/.config/systemd/user/${calendar_unit}.service" 0644
  done
  desktop_stage_role_asset usr/local/libexec/labwc-plans.pl /usr/local/libexec/labwc-plans.pl 0755
  desktop_stage_role_asset usr/local/bin/labwc-logout /usr/local/bin/labwc-logout 0755
  desktop_stage_role_asset usr/local/bin/labwc-fuzzel /usr/local/bin/labwc-fuzzel 0755
  desktop_stage_role_asset usr/local/bin/labwc-computer-management /usr/local/bin/labwc-computer-management 0755
  desktop_stage_role_asset usr/local/bin/labwc-network-sharing /usr/local/bin/labwc-network-sharing 0755
  desktop_stage_role_asset usr/local/bin/nfsmnt /usr/local/bin/nfsmnt 0755
  desktop_stage_role_asset usr/local/bin/filenmnt /usr/local/bin/filenmnt 0755
  desktop_stage_role_asset usr/local/libexec/network-wifi-configure /usr/local/libexec/network-wifi-configure 0755
  desktop_stage_role_asset usr/local/bin/nmtui /usr/local/bin/nmtui 0755
  desktop_stage_role_asset etc/systemd/system/wifi-firstboot.service /etc/systemd/system/wifi-firstboot.service 0644
  desktop_stage_role_asset usr/local/bin/labwc-ai-copilots /usr/local/bin/labwc-ai-copilots 0755
  desktop_stage_ai_copilots_perl_modules
  desktop_stage_ai_copilots_catalogs
  desktop_stage_role_asset usr/local/bin/labwc-ai-copilots-action /usr/local/bin/labwc-ai-copilots-action 0755
  desktop_stage_role_asset usr/local/libexec/labwc-ai-llama-server /usr/local/libexec/labwc-ai-llama-server 0755
  desktop_stage_role_asset usr/local/libexec/llama-whisper-coordinate /usr/local/libexec/llama-whisper-coordinate 0755
  desktop_stage_role_asset etc/systemd/user/llama-whisper-guard.service /etc/systemd/user/llama-whisper-guard.service 0644
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
  desktop_stage_role_asset usr/local/libexec/labwc-gvfs-volume-monitor /usr/local/libexec/labwc-gvfs-volume-monitor 0755
  desktop_stage_role_asset etc/systemd/user/labwc-gvfs-volume-monitor.service /etc/systemd/user/labwc-gvfs-volume-monitor.service 0644
  desktop_stage_role_asset etc/systemd/user/thunar.service.d/50-labwc-session.conf /etc/systemd/user/thunar.service.d/50-labwc-session.conf 0644
  desktop_stage_role_asset usr/share/dbus-1/services/org.gtk.vfs.LabwcVolumeMonitor.service /usr/share/dbus-1/services/org.gtk.vfs.LabwcVolumeMonitor.service 0644
  desktop_stage_role_asset usr/share/gvfs/remote-volume-monitors/labwc.monitor /usr/share/gvfs/remote-volume-monitors/labwc.monitor 0644
  desktop_stage_labwc_security_action_perl_modules
  desktop_stage_role_asset usr/local/bin/labwc-security-action /usr/local/bin/labwc-security-action 0755
  desktop_stage_role_asset usr/local/bin/labwc-system-action /usr/local/bin/labwc-system-action 0755
  desktop_stage_role_asset usr/local/bin/labwc-recovery-action /usr/local/bin/labwc-recovery-action 0755
  desktop_stage_role_asset usr/local/bin/labwc-network-control-menu /usr/local/bin/labwc-network-control-menu 0755
  desktop_stage_labwc_network_control_action_perl_modules
  desktop_stage_role_asset usr/local/bin/labwc-network-control-action /usr/local/bin/labwc-network-control-action 0755
  desktop_stage_role_asset usr/local/bin/labwc-firewall-menu /usr/local/bin/labwc-firewall-menu 0755
  desktop_stage_labwc_firewall_python_modules
  desktop_stage_compz
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
  if [ -e /target/opt/vivaldi/vivaldi ]; then
    [ -x /target/opt/vivaldi/update-ffmpeg ] &&
      [ ! -L /target/opt/vivaldi/update-ffmpeg ] ||
      installer_fatal "installed Vivaldi is missing its packaged codec updater"
    # The signed package's postinst starts this updater asynchronously. Its
    # cleanup removes partial downloads, so wait for that process before
    # running the checked system installation. procps is a desktop dependency;
    # pidwait observes exact root-owned updater processes without signalling.
    run_in_target "install compatible Vivaldi proprietary media codecs" \
      /usr/bin/env -i PATH=/usr/bin:/bin HOME=/root USER=root LANG=C.UTF-8 \
      /usr/bin/timeout --signal=TERM --kill-after=5s 180s \
      /bin/sh -eu -c '
if /usr/bin/pidwait --exact --uid 0 -- update-ffmpeg; then
  :
else
  status=$?
  [ "$status" -eq 1 ] || exit "$status"
fi
exec /opt/vivaldi/update-ffmpeg --system
'
  fi
  desktop_stage_role_asset usr/local/libexec/labwc-proxy-session /usr/local/libexec/labwc-proxy-session 0755
  desktop_normalize_proxy3_directories
  for proxy3_app in chromium microsoft-edge vivaldi mullvad-browser qbittorrent; do
    render_target_asset_with_placeholder_map \
      "$(installer_repo_join_var DIR_HOOKS_TARGET "etc/labwc/3proxy/${proxy3_app}.conf.tmpl")" \
      "/etc/labwc/3proxy/${proxy3_app}.conf" 0644 proxy3_placeholder_map
  done
  render_target_asset_with_placeholder_map \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/labwc/3proxy/session.json.tmpl)" \
    /etc/labwc/3proxy/session.json 0644 proxy3_placeholder_map
  for proxy3_family in chromium opt/chrome opt/edge vivaldi; do
    render_target_asset_with_placeholder_map \
      "$(installer_repo_join_var DIR_HOOKS_TARGET "etc/${proxy3_family}/policies/managed/3proxy.json.tmpl")" \
      "/etc/${proxy3_family}/policies/managed/3proxy.json" 0644 proxy3_placeholder_map
  done
  render_target_asset_with_placeholder_map \
    "$(installer_repo_join_var DIR_HOOKS_TARGET usr/lib/mullvad-browser/distribution/policies.json.tmpl)" \
    /usr/lib/mullvad-browser/distribution/policies.json 0644 proxy3_placeholder_map
  desktop_stage_role_asset usr/local/bin/labwc-app /usr/local/bin/labwc-app 0755
  desktop_stage_role_asset usr/local/bin/labwc-electron-app /usr/local/bin/labwc-electron-app 0755
  desktop_stage_role_asset usr/local/bin/labwc-wayland-app /usr/local/bin/labwc-wayland-app 0755
  desktop_stage_role_asset usr/local/libexec/app-veth-run /usr/local/libexec/app-veth-run 0755
  desktop_stage_role_asset usr/local/libexec/labwc-wrap-desktop-files /usr/local/libexec/labwc-wrap-desktop-files 0755
  desktop_stage_role_asset etc/apt/apt.conf.d/71labwc-desktop-apps /etc/apt/apt.conf.d/71labwc-desktop-apps 0644
  desktop_stage_role_asset usr/local/bin/labwc-main-menu /usr/local/bin/labwc-main-menu 0755
  desktop_stage_role_asset usr/local/bin/labwc-window-switcher /usr/local/bin/labwc-window-switcher 0755
  desktop_stage_waybar_theme_icons
  desktop_stage_role_asset usr/local/bin/labwc-fzf-menu /usr/local/bin/labwc-fzf-menu 0755
  desktop_stage_role_asset etc/systemd/system/labwc-system-desktop-overrides.service /etc/systemd/system/labwc-system-desktop-overrides.service 0644
  desktop_stage_role_asset etc/systemd/system/labwc-system-desktop-overrides.path /etc/systemd/system/labwc-system-desktop-overrides.path 0644
  desktop_render_role_target_template \
    etc/skel-desktop/.local/share/applications/micro.desktop.tmpl \
    /etc/skel-desktop/.local/share/applications/micro.desktop \
    0644 \
    LABWC_WAYLAND_APP_DEFAULT_EXEC "$LABWC_WAYLAND_APP_DEFAULT_EXEC"
  desktop_render_role_target_template \
    etc/skel-desktop/.local/share/applications/waypaper.desktop.tmpl \
    /etc/skel-desktop/.local/share/applications/waypaper.desktop \
    0644 \
    LABWC_WAYLAND_APP_DEFAULT_EXEC "$LABWC_WAYLAND_APP_DEFAULT_EXEC"
  desktop_stage_role_asset etc/dpkg/dpkg.cfg.d/95-labwc-desktop-apps /etc/dpkg/dpkg.cfg.d/95-labwc-desktop-apps 0644
  desktop_stage_role_asset usr/local/libexec/labwc-chatgpt-session /usr/local/libexec/labwc-chatgpt-session 0755
  desktop_stage_role_asset usr/local/bin/labwc-wayland-compat-app /usr/local/bin/labwc-wayland-compat-app 0755
  desktop_stage_role_asset usr/local/libexec/labwc-zoom-discord-compat-runtime /usr/local/libexec/labwc-zoom-discord-compat-runtime 0755
  desktop_stage_role_asset usr/local/libexec/labwc-private-xwayland /usr/local/libexec/labwc-private-xwayland 0755
  desktop_stage_role_asset usr/local/libexec/labwc-compat-open-uri /usr/local/libexec/labwc-compat-open-uri 0755
  desktop_qbittorrent_ports=$(qbittorrent_peer_port_placeholder_map) || desktop_fatal "invalid qBittorrent peer ports"
  desktop_qbittorrent_ethernet_port=$(printf '%s\n' "$desktop_qbittorrent_ports" | awk -F= '$1 == "LABWC_QBITTORRENT_ETHERNET_PORT" {print $2}')
  desktop_veth_identity=$(app_veth_identity_placeholder_map) || desktop_fatal "invalid application network identity"
  desktop_qbittorrent_enabled=$(printf "%s\n" "$desktop_veth_identity" | awk -F= '$1 == "APP_VETH_QBITTORRENT_ENABLED" { print $2 }')
  case "$desktop_qbittorrent_enabled" in
    true)
      ;;
    false)
      # An explicit APP_VETH_OVERRIDE may omit qBittorrent. Do not publish a
      # managed binding for an application that has no broker policy.
      remove_target_asset /etc/qbittorrent/qBittorrent.conf.d/10-security.conf
      remove_target_asset /etc/qbittorrent/qBittorrent.conf.d/20-managed-privacy.conf
      remove_target_asset /etc/labwc/3proxy/qbittorrent.conf
      ;;
    *)
      desktop_fatal "invalid qBittorrent network policy selection"
      ;;
  esac
  desktop_qbittorrent_address=$(printf "%s\n" "$desktop_veth_identity" | awk -F= '$1 == "APP_VETH_QBITTORRENT_ADDRESS" { print $2 }')
  if [ "$desktop_qbittorrent_enabled" = true ]; then
    [ -n "$desktop_qbittorrent_address" ] || desktop_fatal "missing qBittorrent network identity"
    desktop_render_role_target_template \
      etc/qbittorrent/qBittorrent.conf.d/10-security.conf.tmpl \
      /etc/qbittorrent/qBittorrent.conf.d/10-security.conf \
      0644 \
      ACCOUNT_USERNAME "$ACCOUNT_USERNAME" \
      QBITTORRENT_SAVE_ROOT "/run/media/$ACCOUNT_USERNAME/bittorrent" \
      LABWC_QBITTORRENT_ETHERNET_PORT "$desktop_qbittorrent_ethernet_port" \
      PROXY3_PORT_LISTEN_QBITTORRENT "${PROXY3_PORT_LISTEN_QBITTORRENT:-3128}" \
      APP_VETH_NAMESPACE_INTERFACE "$APP_VETH_NAMESPACE_INTERFACE" \
      APP_VETH_QBITTORRENT_ADDRESS "$desktop_qbittorrent_address"
    # Same native policy, rendered at install time for the disposable HOME.
    # Its address is allocated per lease, so only the interface is fixed.
    desktop_render_role_target_template \
      etc/qbittorrent/qBittorrent.conf.d/10-security.conf.tmpl \
      /etc/qbittorrent/qBittorrent.conf.d/20-managed-privacy.conf 0644 \
      QBITTORRENT_SAVE_ROOT /home/user/Downloads \
      LABWC_QBITTORRENT_ETHERNET_PORT "$desktop_qbittorrent_ethernet_port" \
      PROXY3_PORT_LISTEN_QBITTORRENT "${PROXY3_PORT_LISTEN_QBITTORRENT:-3128}" \
      APP_VETH_NAMESPACE_INTERFACE "$APP_VETH_NAMESPACE_INTERFACE" \
      APP_VETH_QBITTORRENT_ADDRESS ""
  fi
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
  desktop_stage_role_asset usr/local/libexec/labwc-primary-gpg /usr/local/libexec/labwc-primary-gpg 0755
  desktop_stage_role_asset usr/local/libexec/labwc-waybar-exec /usr/local/libexec/labwc-waybar-exec 0755
  desktop_stage_role_asset usr/local/libexec/labwc-waybar-battery /usr/local/libexec/labwc-waybar-battery 0755
  desktop_stage_role_asset usr/local/libexec/labwc-panel-run /usr/local/libexec/labwc-panel-run 0755
  desktop_stage_role_asset usr/local/libexec/whisper-record-timed /usr/local/libexec/whisper-record-timed 0755
  desktop_stage_role_asset usr/local/libexec/labwc-swaybg /usr/local/libexec/labwc-swaybg 0755
  desktop_stage_role_asset usr/local/libexec/labwc-swayidle /usr/local/libexec/labwc-swayidle 0755
  desktop_stage_role_asset usr/local/libexec/labwc-mute-default-microphone /usr/local/libexec/labwc-mute-default-microphone 0755
  desktop_stage_role_asset usr/local/lib/perl5/site_perl/whisper/WhisperMode/Audio.pm /usr/local/lib/perl5/site_perl/whisper/WhisperMode/Audio.pm 0644
  desktop_stage_role_asset usr/local/lib/perl5/site_perl/whisper/WhisperMode/State.pm /usr/local/lib/perl5/site_perl/whisper/WhisperMode/State.pm 0644
  desktop_stage_role_asset usr/local/lib/perl5/site_perl/whisper/WhisperMode/Systemd.pm /usr/local/lib/perl5/site_perl/whisper/WhisperMode/Systemd.pm 0644
  desktop_stage_role_asset usr/local/bin/labwc-lock /usr/local/bin/labwc-lock 0755
  desktop_stage_role_asset usr/local/libexec/labwc-swaylock /usr/local/libexec/labwc-swaylock 0755
  desktop_stage_role_asset usr/local/bin/labwc-idle-toggle /usr/local/bin/labwc-idle-toggle 0755
  desktop_stage_role_asset etc/systemd/user/labwc-lock.service /etc/systemd/user/labwc-lock.service 0644
  desktop_stage_role_asset usr/local/bin/labwc-terminal /usr/local/bin/labwc-terminal 0755
  desktop_stage_role_asset usr/local/libexec/labwc-terminal-result /usr/local/libexec/labwc-terminal-result 0755
  desktop_stage_role_asset usr/local/bin/labwc-bluetooth /usr/local/bin/labwc-bluetooth 0755
  desktop_stage_role_asset usr/local/bin/labwc-brightness-control /usr/local/bin/labwc-brightness-control 0755
  desktop_stage_role_asset usr/local/libexec/labwc-thinkpad-hotkeys /usr/local/libexec/labwc-thinkpad-hotkeys 0755
  desktop_stage_role_asset etc/systemd/system/labwc-thinkpad-hotkeys.service /etc/systemd/system/labwc-thinkpad-hotkeys.service 0644
  desktop_stage_role_asset etc/udev/rules.d/81-labwc-thinkpad-backlight.rules /etc/udev/rules.d/81-labwc-thinkpad-backlight.rules 0644
  run_in_target "enable supported ThinkPad brightness events" /usr/bin/systemctl enable labwc-thinkpad-hotkeys.service
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
  desktop_stage_role_asset usr/local/libexec/labwc-storage-report /usr/local/libexec/labwc-storage-report 0755
  # Inspect code and command metadata as data before desktop service enablement.
  # Never invoke the report or query a filesystem while staging the installer.
  run_in_target "verify staged storage report contract" /usr/bin/python3 -I -S -B -c '
import re
import stat
from pathlib import Path

report = Path("/usr/local/libexec/labwc-storage-report")
for path in (report, Path("/usr/bin/df"), Path("/usr/bin/findmnt"),
             Path("/usr/bin/lsblk"), Path("/usr/bin/timeout")):
    for parent in reversed(path.parents):
        meta = parent.lstat()
        if not stat.S_ISDIR(meta.st_mode) or meta.st_uid != 0 or meta.st_mode & 0o022:
            raise SystemExit("fatal: untrusted storage command parent: " + str(parent))
    meta = path.lstat()
    if (not stat.S_ISREG(meta.st_mode) or meta.st_uid != 0 or meta.st_gid != 0
            or meta.st_mode & 0o022 or not meta.st_mode & 0o111):
        raise SystemExit("fatal: unsafe or unavailable storage command: " + str(path))
    if path == report and (meta.st_nlink != 1 or stat.S_IMODE(meta.st_mode) != 0o755
                           or not 0 < meta.st_size <= 16384):
        raise SystemExit("fatal: invalid storage report metadata")
with report.open("rb") as stream:
    source = stream.read(16385)
if len(source) > 16384 or re.search(rb"__[A-Z][A-Z0-9_]{2,}__", source):
    raise SystemExit("fatal: oversized or unresolved storage report")
'
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
  desktop_stage_role_asset usr/local/libexec/clamav-fangfrisch /usr/local/libexec/clamav-fangfrisch 0755

  desktop_stage_role_asset usr/share/wayland-sessions/labwc.desktop /usr/share/wayland-sessions/labwc.desktop 0644
  desktop_stage_role_asset usr/local/share/applications/computer-management.desktop /usr/local/share/applications/computer-management.desktop 0644
  desktop_stage_role_asset usr/local/share/applications/remote-desktop-management.desktop /usr/local/share/applications/remote-desktop-management.desktop 0644
  desktop_stage_role_asset usr/local/share/applications/foot.desktop /usr/local/share/applications/foot.desktop 0644
  desktop_stage_role_asset usr/local/share/applications/code.desktop /usr/local/share/applications/code.desktop 0644
  desktop_stage_role_asset usr/local/share/applications/labwc-notifications.desktop /usr/local/share/applications/labwc-notifications.desktop 0644
  desktop_render_gtkgreet_css
  desktop_stage_role_asset etc/greetd/gtkgreet-power.css /etc/greetd/gtkgreet-power.css 0644
  desktop_render_greeter_power_rule
  desktop_stage_fangfrisch
  desktop_stage_role_asset etc/cron.d/debsecan /etc/cron.d/debsecan 0644
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
  desktop_stage_role_asset usr/local/libexec/labwc-hyprpolkit-agent /usr/local/libexec/labwc-hyprpolkit-agent 0755 || return 1
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
  # The package defaults to a global preload. Scope decoration conversion to
  # Agenda through its managed profile instead of changing the whole session.
  desktop_stage_role_asset etc/environment.d/50-gtk-nocsd.conf /etc/environment.d/50-gtk-nocsd.conf 0644
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
  desktop_stage_role_asset etc/chromium/policies/managed/extensions.json /etc/chromium/policies/managed/extensions.json 0644
  desktop_stage_role_asset etc/chromium/policies/managed/performance.json /etc/chromium/policies/managed/performance.json 0644
  desktop_stage_role_asset etc/chromium/policies/recommended/defaults.json /etc/chromium/policies/recommended/defaults.json 0644
  desktop_stage_role_asset etc/opt/edge/policies/managed/telemetry.json /etc/opt/edge/policies/managed/telemetry.json 0644
  desktop_stage_role_asset etc/opt/edge/policies/managed/security.json /etc/opt/edge/policies/managed/security.json 0644
  desktop_stage_role_asset etc/opt/edge/policies/managed/extensions.json /etc/opt/edge/policies/managed/extensions.json 0644
  desktop_stage_role_asset etc/opt/edge/policies/managed/performance.json /etc/opt/edge/policies/managed/performance.json 0644
  desktop_stage_role_asset etc/opt/edge/policies/recommended/defaults.json /etc/opt/edge/policies/recommended/defaults.json 0644
  desktop_stage_role_asset etc/vivaldi/policies/managed/telemetry.json /etc/vivaldi/policies/managed/telemetry.json 0644
  desktop_stage_role_asset etc/vivaldi/policies/managed/extensions.json /etc/vivaldi/policies/managed/extensions.json 0644
  desktop_stage_role_asset etc/vivaldi/policies/managed/security.json /etc/vivaldi/policies/managed/security.json 0644
  desktop_stage_role_asset etc/vivaldi/policies/managed/performance.json /etc/vivaldi/policies/managed/performance.json 0644
  desktop_stage_role_asset etc/vivaldi/policies/recommended/defaults.json /etc/vivaldi/policies/recommended/defaults.json 0644
  desktop_stage_role_asset etc/vivaldi/search-engines/search_engines.json.signed /etc/vivaldi/search-engines/search_engines.json.signed 0644
  desktop_stage_role_asset etc/vivaldi/search-engines/search_engines_prompt.json.signed /etc/vivaldi/search-engines/search_engines_prompt.json.signed 0644
  desktop_stage_role_asset etc/opt/chrome/policies/managed/security.json /etc/opt/chrome/policies/managed/security.json 0644
  desktop_stage_role_asset etc/opt/chrome/policies/managed/extensions.json /etc/opt/chrome/policies/managed/extensions.json 0644
  desktop_stage_role_asset etc/opt/chrome/policies/managed/telemetry.json /etc/opt/chrome/policies/managed/telemetry.json 0644
  desktop_stage_role_asset etc/opt/chrome/policies/managed/performance.json /etc/opt/chrome/policies/managed/performance.json 0644
  desktop_stage_role_asset etc/opt/chrome/policies/recommended/defaults.json /etc/opt/chrome/policies/recommended/defaults.json 0644
  desktop_stage_role_asset usr/local/bin/browser-devtools /usr/local/bin/browser-devtools 0755
  desktop_stage_role_asset \
    usr/share/glib-2.0/schemas/90-desktop-wsdd.gschema.override \
    /usr/share/glib-2.0/schemas/90-desktop-wsdd.gschema.override \
    0644
  desktop_stage_role_asset etc/xdg/xdg-desktop-portal/labwc-portals.conf /etc/xdg/xdg-desktop-portal/labwc-portals.conf 0644
  desktop_stage_role_asset etc/skel-desktop/.gnupg/gpg-agent.conf /etc/skel-desktop/.gnupg/gpg-agent.conf 0600
  chmod 0700 /target/etc/skel-desktop/.gnupg
  desktop_stage_role_asset etc/skel-desktop/.config/systemd/user/obsidian-git-sync.service /etc/skel-desktop/.config/systemd/user/obsidian-git-sync.service 0644
  desktop_stage_role_asset etc/skel-desktop/.config/systemd/user/obsidian-git-sync.timer /etc/skel-desktop/.config/systemd/user/obsidian-git-sync.timer 0644
  desktop_render_role_target_template \
    etc/obsidian-git-sync.conf.tmpl /etc/obsidian-git-sync.conf 0644 \
    OBSIDIAN_GIT_AUTO_ENABLE "$OBSIDIAN_GIT_AUTO_ENABLE"
  desktop_stage_role_asset usr/local/libexec/obsidian-git-sync /usr/local/libexec/obsidian-git-sync 0755
  desktop_stage_role_asset usr/local/libexec/obsidian-git-sync.py /usr/local/libexec/obsidian-git-sync.py 0755

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
  desktop_stage_role_asset etc/skel-desktop/.config/l3afpad/l3afpadrc /etc/skel-desktop/.config/l3afpad/l3afpadrc 0644
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
  case "${requested_host_profile:-${HOST_PROFILE:-}}" in
    btrfs-de-p15s|btrfs-de-p15s-duo)
      desktop_stage_role_asset usr/share/wireplumber/scripts/p15s-speaker-profile.lua /usr/share/wireplumber/scripts/p15s-speaker-profile.lua 0644
      ;;
  esac
  for audio_dir in /etc/wireplumber/wireplumber.conf.d /etc/skel-desktop/.config/wireplumber/wireplumber.conf.d; do
    case "${requested_host_profile:-${HOST_PROFILE:-}}" in
      btrfs-de-p15s|btrfs-de-p15s-duo)
        desktop_stage_role_asset etc/wireplumber/wireplumber.conf.d/30-p15s-audio.conf "$audio_dir/30-p15s-audio.conf" 0644
        ;;
      *) rm -f "/target$audio_dir/30-p15s-audio.conf" ;;
    esac
  done
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
  # The sandbox session seeds missing Vivaldi caches from signed vendor data;
  # subsequent cache updates remain owned by the browser.
  desktop_stage_syncthing_ignore
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
