#!/bin/sh
# Sourced installer module; edit this file directly.

desktop_unit_has_install_entry() {
  unit=$1
  scope=$2
  unit_path=$3

  for install_key in WantedBy RequiredBy Alias Also; do
    for install_value in $(target_systemd_install_values "$unit_path" "$install_key"); do
      [ -n "$install_value" ] || continue
      return 0
    done
  done
  installer_info "target ${scope} unit has no [Install] entry; leaving static unit unmanaged: ${unit}"
  return 1
}

desktop_enable_unit_if_available() {
  unit=$1
  scope=$2
  unit_path=$(target_systemd_unit_path "$unit" "$scope" 2>/dev/null || true)

  if [ -z "$unit_path" ]; then
    installer_warn "target ${scope} unit is unavailable; skipping enablement: ${unit}"
    return 0
  fi
  desktop_unit_has_install_entry "$unit" "$scope" "$unit_path" || return 0
  stage_target_systemd_unit_enabled "$unit" "$scope"
  desktop_log "staged_${scope}_unit_enabled unit=${unit} unit_path=${unit_path}"
}

desktop_disable_unit_if_available() {
  unit=$1
  scope=$2
  unit_path=$(target_systemd_unit_path "$unit" "$scope" 2>/dev/null || true)

  [ -n "$unit_path" ] || return 0
  if command -v unstage_target_systemd_unit_enabled >/dev/null 2>&1; then
    unstage_target_systemd_unit_enabled "$unit" "$scope"
  fi
  desktop_log "staged_${scope}_unit_disabled unit=${unit} unit_path=${unit_path}"
}

desktop_unit_mask_link_path() {
  unit=$1
  scope=$2
  base_dir=$(target_systemd_scope_base_dir "$scope")

  printf '/target%s/%s\n' "$base_dir" "$unit"
}

desktop_unit_is_masked() {
  unit=$1
  scope=$2
  mask_path=$(desktop_unit_mask_link_path "$unit" "$scope")

  [ -L "$mask_path" ] || return 1
  [ "$(readlink "$mask_path" 2>/dev/null || true)" = /dev/null ]
}

desktop_mask_unit_if_available() {
  unit=$1
  scope=$2

  if desktop_unit_is_masked "$unit" "$scope"; then
    desktop_log "staged_${scope}_unit_masked unit=${unit} unit_path=/dev/null already_masked=true"
    return 0
  fi

  unit_path=$(target_systemd_unit_path "$unit" "$scope" 2>/dev/null || true)

  [ -n "$unit_path" ] || return 0
  desktop_disable_unit_if_available "$unit" "$scope"
  base_dir=$(target_systemd_scope_base_dir "$scope")
  install -d -m 0755 "/target${base_dir}"
  ln -sfn /dev/null "/target${base_dir}/${unit}"
  desktop_log "staged_${scope}_unit_masked unit=${unit} unit_path=${unit_path}"
}

desktop_enable_target_services() {
  # Boot reconciliation handles inputs that predate path activation. The same
  # helper already runs synchronously during desktop installation.
  desktop_enable_unit_if_available labwc-system-desktop-overrides.service system
  desktop_enable_unit_if_available labwc-system-desktop-overrides.path system
  desktop_enable_unit_if_available greetd.service system
  desktop_enable_unit_if_available seatd.service system
  desktop_enable_unit_if_available bluetooth-controller-init.service system
  desktop_enable_unit_if_available bluetooth.service system
  desktop_enable_unit_if_available rtkit-daemon.service system
  desktop_enable_unit_if_available upower.service system
  desktop_enable_unit_if_available power-profiles-daemon.service system
  desktop_enable_unit_if_available udisks2.service system
  # Keep the clock synchronized after installation; do not block desktop
  # startup on external NTP reachability or add a competing custom daemon.
  desktop_enable_unit_if_available systemd-timesyncd.service system
  desktop_enable_unit_if_available NetworkManager.service system
  desktop_enable_unit_if_available NetworkManager-dispatcher.service system
  if desktop_mullvad_selected; then
    desktop_enable_unit_if_available systemd-resolved.service system
    desktop_disable_unit_if_available mullvad-daemon.service system
  fi
  desktop_enable_unit_if_available rsyslog.service system
  desktop_enable_unit_if_available logrotate.timer system
  desktop_mask_unit_if_available systemd-journald-audit.socket system
  desktop_mask_unit_if_available fwupd-refresh.service system
  desktop_mask_unit_if_available fwupd-refresh.timer system
  desktop_disable_unit_if_available mpris-proxy.service user
  desktop_disable_unit_if_available waybar.service user
  desktop_disable_unit_if_available foot-server.service user
  desktop_enable_unit_if_available clamav-signature-update.timer system
  desktop_mask_unit_if_available clamav-freshclam.service system
  desktop_mask_unit_if_available fangfrisch.timer system
  if [ "${LABWC_NVIDIA_ACCELERATION_AVAILABLE:-false}" = true ]; then
    desktop_enable_unit_if_available nvidia-char-links.service system
    desktop_mask_unit_if_available nvidia-persistenced.service system
    desktop_mask_unit_if_available nvidia-powerd.service system
  fi

  run_in_target "verify packaged SSH agent contract and desktop-only activation" /bin/sh -eu -c '
    test -r /usr/lib/systemd/user/ssh-agent.socket
    test -r /usr/lib/systemd/user/ssh-agent.service
    grep -Eq "^ListenStream=%t/openssh_agent$" /usr/lib/systemd/user/ssh-agent.socket
    grep -Eq "^SocketMode=0?600$" /usr/lib/systemd/user/ssh-agent.socket
    grep -Eq "^ExecStart=.*ssh-agent .*-[dD]" /usr/lib/systemd/user/ssh-agent.service
    systemctl --global disable ssh-agent.socket
  '

  # Unlock is explicitly requested by git-ssh unlock, not by graphical login.
  # Remove only the exact links installed by older revisions, never admin files.
  desktop_require_absolute_account_home
  for ssh_home in /etc/skel-desktop "$ACCOUNT_HOME"; do
    ssh_units="/target${ssh_home}/.config/systemd/user"
    ssh_wants="${ssh_units}/labwc-session.target.wants"
    [ ! -L "$ssh_units" ] && [ ! -L "$ssh_wants" ] ||
      installer_fatal "unsafe SSH unlock activation directory: ${ssh_wants}"
    ssh_link="${ssh_wants}/labwc-ssh-key-load.service"
    if [ -L "$ssh_link" ] && [ "$(readlink "$ssh_link")" = ../labwc-ssh-key-load.service ]; then
      rm -- "$ssh_link"
    elif [ -e "$ssh_link" ] || [ -L "$ssh_link" ]; then
      installer_fatal "unmanaged SSH unlock activation preserved: ${ssh_link}"
    fi
  done

  for unit in \
    labwc-output-watch.service \
    swaybg.service \
    swayidle.service \
    crystal-dock.service \
    labwc-mute-default-microphone.service \
    labwc-kwallet-portal.service \
    ssh-agent.socket \
    labwc-plans.service \
    foot-server.socket \
    mako.service \
    filter-chain.service \
    labwc-calendar-sync.timer \
    labwc-sync-application-launchers.service \
    labwc-sync-application-launchers.path \
    wayscriber.service \
    hyprpolkitagent.service \
    xdg-desktop-portal.service \
    xdg-desktop-portal-gtk.service \
    xdg-desktop-portal-wlr.service \
    xdg-desktop-portal-lxqt.service
  do
    desktop_stage_user_unit_wanted_by "$unit" labwc-session.target
  done

  if desktop_kanshi_enabled; then
    desktop_stage_user_unit_wanted_by kanshi.service labwc-session.target
  fi

  if desktop_whisper_persistent_memory_enabled; then
    desktop_stage_user_unit_wanted_by whisper-server.service labwc-session.target
  fi

  if [ -r "/target$(desktop_user_unit_template_dir)/apt-repo-local-software-notify.path" ]; then
    desktop_stage_user_unit_wanted_by apt-repo-local-software-notify.path labwc-session.target
  fi

  stage_target_default_systemd_unit "${LABWC_DESKTOP_DEFAULT_TARGET:-graphical.target}"
  desktop_log "staged_default_target target=${LABWC_DESKTOP_DEFAULT_TARGET:-graphical.target}"
}
