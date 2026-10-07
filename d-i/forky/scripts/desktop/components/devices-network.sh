#!/bin/sh
# Sourced installer module; edit this file directly.

desktop_configure_android_debug_bridge_access() {
  : "${ACCOUNT_USERNAME:?ACCOUNT_USERNAME must be set}"

  case "$ACCOUNT_USERNAME" in
    [abcdefghijklmnopqrstuvwxyz_]*) ;;
    *)
      installer_fatal "ACCOUNT_USERNAME must start with a lowercase letter or underscore"
      ;;
  esac
  case "$ACCOUNT_USERNAME" in
    *[!abcdefghijklmnopqrstuvwxyz0123456789_-]*)
      installer_fatal "ACCOUNT_USERNAME contains unsupported characters for Android Debug Bridge policy"
      ;;
  esac

  # shellcheck disable=SC2016
  run_in_target "configure Android Debug Bridge USB access" /bin/sh -c '
set -eu
account_user=$1

for command_name in getent groupadd id usermod; do
  command -v "$command_name" >/dev/null 2>&1 || {
    printf "fatal: required Android Debug Bridge access command is missing: %s\n" "$command_name" >&2
    exit 1
  }
done

getent group plugdev >/dev/null 2>&1 || groupadd --system plugdev
usermod -a -G plugdev "$account_user"

account_groups=$(id -nG "$account_user")
case " $account_groups " in
  *" plugdev "*) ;;
  *)
    printf "fatal: desktop account was not added to the plugdev group: %s\n" "$account_user" >&2
    exit 1
    ;;
esac
' sh "$ACCOUNT_USERNAME"

  desktop_stage_role_asset \
    etc/udev/rules.d/51-android-debug-bridge.rules \
    /etc/udev/rules.d/51-android-debug-bridge.rules \
    0644
  desktop_stage_role_asset \
    etc/udev/rules.d/52-samsung-download-mode.rules \
    /etc/udev/rules.d/52-samsung-download-mode.rules \
    0644
  desktop_log "configured Android Debug Bridge and Samsung Download Mode USB access user=${ACCOUNT_USERNAME} group=plugdev"
}

desktop_configure_fido2_security_key_access() {
  desktop_stage_role_asset \
    etc/udev/rules.d/53-ledger-wallet.rules \
    /etc/udev/rules.d/53-ledger-wallet.rules \
    0644
  desktop_log "configured Ledger Stax browser FIDO2 security-key access through active-seat udev ACLs"
}

desktop_configure_packet_capture_access() {
  : "${ACCOUNT_USERNAME:?ACCOUNT_USERNAME must be set}"

  case "$ACCOUNT_USERNAME" in
    [abcdefghijklmnopqrstuvwxyz_]*) ;;
    *)
      installer_fatal "ACCOUNT_USERNAME must start with a lowercase letter or underscore"
      ;;
  esac
  case "$ACCOUNT_USERNAME" in
    *[!abcdefghijklmnopqrstuvwxyz0123456789_-]*)
      installer_fatal "ACCOUNT_USERNAME contains unsupported characters for packet capture policy"
      ;;
  esac

  # shellcheck disable=SC2016
  run_in_target "configure least-privilege Wireshark capture access" /bin/sh -c '
set -eu
account_user=$1

for command_name in \
  cut \
  debconf-set-selections \
  dpkg-reconfigure \
  dumpcap \
  getcap \
  getent \
  id \
  find \
  tshark \
  usermod \
  wireshark
do
  command -v "$command_name" >/dev/null 2>&1 || {
    printf "fatal: required packet capture configuration command is missing: %s\n" "$command_name" >&2
    exit 1
  }
done

printf "%s\n" "wireshark-common wireshark-common/install-setuid boolean true" |
  debconf-set-selections
DEBIAN_FRONTEND=noninteractive
export DEBIAN_FRONTEND
dpkg-reconfigure wireshark-common

getent group wireshark >/dev/null 2>&1 || {
  printf "fatal: wireshark group is missing after wireshark-common reconfiguration\n" >&2
  exit 1
}
usermod -a -G wireshark "$account_user"

capture_groups=$(id -nG "$account_user")
case " $capture_groups " in
  *" wireshark "*) ;;
  *)
    printf "fatal: desktop account was not added to the wireshark group: %s\n" "$account_user" >&2
    exit 1
    ;;
esac

group_members=$(getent group wireshark | cut -d: -f4)
old_ifs=$IFS
IFS=,
for group_member in $group_members; do
  [ -n "$group_member" ] || continue
  [ "$group_member" = "$account_user" ] || {
    printf "fatal: unexpected automatically authorized wireshark group member: %s\n" "$group_member" >&2
    exit 1
  }
done
IFS=$old_ifs

dumpcap_path=$(command -v dumpcap)
dumpcap_group=$(find -P "$dumpcap_path" -maxdepth 0 -printf %g)
dumpcap_mode=$(find -P "$dumpcap_path" -maxdepth 0 -printf %m)
dumpcap_caps=$(getcap "$dumpcap_path" 2>/dev/null || true)
dumpcap_mode_value=$((0$dumpcap_mode))
dumpcap_cap_set=${dumpcap_caps#"$dumpcap_path "}

[ "$dumpcap_group" = wireshark ] || {
  printf "fatal: dumpcap is not owned by the wireshark group: %s\n" "$dumpcap_group" >&2
  exit 1
}
[ $((dumpcap_mode_value & 0010)) -ne 0 ] || {
  printf "fatal: dumpcap is not executable by the wireshark group: %s\n" "$dumpcap_mode" >&2
  exit 1
}
[ $((dumpcap_mode_value & 0001)) -eq 0 ] || {
  printf "fatal: dumpcap is executable by users outside the wireshark group: %s\n" "$dumpcap_mode" >&2
  exit 1
}
[ $((dumpcap_mode_value & 04000)) -eq 0 ] || {
  printf "fatal: dumpcap must use file capabilities instead of setuid root\n" >&2
  exit 1
}
case "$dumpcap_cap_set" in
  cap_net_admin,cap_net_raw=eip|cap_net_raw,cap_net_admin=eip|cap_net_admin,cap_net_raw=ep|cap_net_raw,cap_net_admin=ep) ;;
  *)
    printf "fatal: dumpcap has an unexpected capability set: %s\n" "${dumpcap_cap_set:-none}" >&2
    exit 1
    ;;
esac

for frontend_name in tshark wireshark; do
  frontend_path=$(command -v "$frontend_name")
  frontend_owner=$(find -P "$frontend_path" -maxdepth 0 -printf %u)
  frontend_mode=$(find -P "$frontend_path" -maxdepth 0 -printf %m)
  frontend_mode_value=$((0$frontend_mode))
  frontend_caps=$(getcap "$frontend_path" 2>/dev/null || true)

  [ "$frontend_owner" = root ] || {
    printf "fatal: %s is not owned by root: %s\n" "$frontend_name" "$frontend_owner" >&2
    exit 1
  }
  [ $((frontend_mode_value & 06000)) -eq 0 ] || {
    printf "fatal: %s must not be setuid or setgid: %s\n" "$frontend_name" "$frontend_mode" >&2
    exit 1
  }
  [ -z "$frontend_caps" ] || {
    printf "fatal: %s must not carry file capabilities: %s\n" "$frontend_name" "$frontend_caps" >&2
    exit 1
  }
done

printf "desktop_packet_capture_access user=%s group=wireshark dumpcap=%s mode=%s capabilities=%s\n" \
  "$account_user" "$dumpcap_path" "$dumpcap_mode" "$dumpcap_caps"
' sh "$ACCOUNT_USERNAME"
  desktop_log "configured packet capture access user=${ACCOUNT_USERNAME} group=wireshark"
}

desktop_assert_role_target_template_resolved() {
  role_relpath=$1
  target_path=$2
  source_path=$(installer_repo_join_var DIR_HOOKS_TARGET "$role_relpath")

  desktop_assert_no_unresolved_template_placeholders "$(target_asset_host_path "$target_path")" "desktop template ${source_path}"
}

desktop_replace_block_placeholder_in_target() {
  target_path=$1
  placeholder=$2
  replacement=$3

  replace_placeholder_line_block "$(target_asset_host_path "$target_path")" "$placeholder" "$replacement"
}

desktop_labwc_workspace_name_lines() {
  workspace_count=${LABWC_WORKSPACE_COUNT:-4}
  workspace_index=1

  while [ "$workspace_index" -le "$workspace_count" ]; do
    printf '      <name>%s</name>\n' "$workspace_index"
    workspace_index=$((workspace_index + 1))
  done
}

desktop_labwc_workspace_keybind_lines() {
  workspace_count=${LABWC_WORKSPACE_COUNT:-4}
  keybind_workspace_count=$workspace_count
  workspace_index=1

  if [ "$keybind_workspace_count" -gt 9 ]; then
    keybind_workspace_count=9
  fi

  while [ "$workspace_index" -le "$keybind_workspace_count" ]; do
    printf '    <keybind key="W-%s">\n' "$workspace_index"
    printf '      <action name="GoToDesktop" to="%s" />\n' "$workspace_index"
    printf '    </keybind>\n'
    printf '    <keybind key="W-S-%s">\n' "$workspace_index"
    printf '      <action name="SendToDesktop" to="%s" />\n' "$workspace_index"
    printf '    </keybind>\n'
    workspace_index=$((workspace_index + 1))
  done
}

desktop_whisper_addon_selected() {
  installer_selected_class_reference_is_selected addon/whisper 2>/dev/null
}

desktop_mullvad_selected() {
  installer_selected_class_reference_is_selected addon/software 2>/dev/null && return 0
  installer_selected_class_reference_is_selected apps/mullvad 2>/dev/null
}

desktop_stage_mullvad_dns_policy() {
  desktop_mullvad_selected || return 0

  run_in_target "validate Mullvad VPN resolver integration" /bin/sh -eu -c '
for package_name in mullvad-vpn systemd-resolved; do
  package_status=$(dpkg-query -W -f="\${db:Status-Abbrev}" "$package_name" 2>/dev/null || true)
  [ "$package_status" = "ii " ] || {
    printf "fatal: required Mullvad integration package is not installed: %s\n" "$package_name" >&2
    exit 1
  }
done
legacy_resolvconf_status=$(dpkg-query -W -f="\${db:Status-Abbrev}" resolvconf 2>/dev/null || true)
[ "$legacy_resolvconf_status" != "ii " ] || {
  printf "%s\n" "fatal: legacy resolvconf must not be installed with systemd-resolved" >&2
  exit 1
}
command -v resolvectl >/dev/null 2>&1 || {
  printf "%s\n" "fatal: resolvectl is unavailable for Mullvad DNS integration" >&2
  exit 1
}
[ -L /usr/sbin/resolvconf ] &&
  [ "$(readlink -f /usr/sbin/resolvconf)" = /usr/bin/resolvectl ] || {
    printf "%s\n" "fatal: systemd-resolved resolvconf compatibility link is invalid" >&2
    exit 1
  }
[ -L /etc/resolv.conf ] &&
  [ "$(readlink -m /etc/resolv.conf)" = /run/systemd/resolve/stub-resolv.conf ] || {
    printf "%s\n" "fatal: /etc/resolv.conf is not owned by systemd-resolved" >&2
    exit 1
  }
' sh

  mullvad_unit_path=$(target_systemd_unit_path mullvad-daemon.service system 2>/dev/null || true)
  [ -n "$mullvad_unit_path" ] ||
    installer_fatal "mullvad-vpn is selected but mullvad-daemon.service is unavailable in the target"

  desktop_stage_role_asset \
    etc/systemd/system/mullvad-daemon.service.d/20-dns.conf \
    /etc/systemd/system/mullvad-daemon.service.d/20-dns.conf \
    0644
  desktop_stage_role_asset \
    etc/systemd/system/tailscaled.service.d/30-mullvad-exclusion.conf \
    /etc/systemd/system/tailscaled.service.d/30-mullvad-exclusion.conf \
    0644
  desktop_stage_role_asset \
    etc/tmpfiles.d/51-mullvad-version-cache.conf \
    /etc/tmpfiles.d/51-mullvad-version-cache.conf \
    0644
  desktop_stage_role_asset \
    etc/tmpfiles.d/52-mullvad-tailscale-coordinator.conf \
    /etc/tmpfiles.d/52-mullvad-tailscale-coordinator.conf \
    0644
  desktop_stage_role_asset \
    usr/local/libexec/mullvad-tailscale-coordinator \
    /usr/local/libexec/mullvad-tailscale-coordinator \
    0755
  desktop_log \
    "staged_mullvad_runtime_policy backend=systemd-resolved cache_root=/var/lib/mullvad-version-cache cache_owner=root:root cache_seed=vendor-managed unit=${mullvad_unit_path}"
}

desktop_stage_mullvad_application_policy() {
  desktop_mullvad_selected || return 0

  desktop_stage_role_asset \
    usr/local/bin/mullvad-vpn \
    /usr/local/bin/mullvad-vpn \
    0755
  desktop_stage_role_asset \
    usr/local/libexec/mullvad-daemon-start \
    /usr/local/libexec/mullvad-daemon-start \
    0755
  desktop_stage_role_asset \
    usr/local/share/applications/mullvad-vpn.desktop \
    /usr/local/share/applications/mullvad-vpn.desktop \
    0644
  desktop_stage_role_asset \
    etc/skel-desktop/.config/autostart/mullvad-vpn.desktop \
    /etc/skel-desktop/.config/autostart/mullvad-vpn.desktop \
    0644
  desktop_log \
    "staged_mullvad_application_policy daemon_autostart=disabled gui_autostart=disabled launcher=/usr/local/bin/mullvad-vpn backend=wayland"
}

desktop_whisper_persistent_memory_enabled() {
  desktop_whisper_addon_selected || return 1
  [ "${WHISPER_PERSISTENT_MEM:-0}" = 1 ]
}

desktop_waybar_pulseaudio_right_click_command() {
  printf '/usr/bin/wpctl set-mute @DEFAULT_AUDIO_SOURCE@ toggle'
}

desktop_labwc_recording_keybind_lines() (
  if desktop_whisper_addon_selected; then
    recording_fragment=recording-whisper.xml.fragment
  else
    recording_fragment=recording-reconfigure.xml.fragment
  fi
  recording_tmp=$(mktemp "${TMP_ENV_DIR}/recording-bindings.XXXXXX") || exit 1
  trap 'rm -f -- "$recording_tmp"' 0
  fetch_hook "$(installer_repo_join_var DIR_SCRIPTS_DESKTOP "templates/$recording_fragment")" "$recording_tmp" || exit 1
  cat "$recording_tmp"
)

