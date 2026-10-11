#!/bin/sh
# Sourced installer module; edit this file directly.

desktop_user_unit_template_dir() {
  printf '%s\n' /etc/skel-desktop/.config/systemd/user
}

desktop_user_unit_source_path() {
  unit=$1
  template_dir=$(desktop_user_unit_template_dir)
  template_unit="${template_dir}/${unit}"
  template_unit_host="/target${template_unit}"

  validate_systemd_unit_name "$unit"
  if [ -e "$template_unit_host" ] || [ -L "$template_unit_host" ]; then
    [ -f "$template_unit_host" ] && [ ! -L "$template_unit_host" ] ||
      installer_fatal "desktop user unit template is unsafe: ${template_unit}"
    printf '%s\n' "$template_unit"
    return 0
  fi

  target_systemd_unit_path "$unit" user 2>/dev/null
}

desktop_user_unit_link_target() {
  unit=$1
  template_dir=$(desktop_user_unit_template_dir)
  unit_path=$(desktop_user_unit_source_path "$unit" || true)

  [ -n "$unit_path" ] || return 1
  if [ "$unit_path" = "${template_dir}/${unit}" ]; then
    printf '../%s\n' "$unit"
  else
    printf '%s\n' "$unit_path"
  fi
}

desktop_stage_user_unit_wanted_by() {
  unit=$1
  wanted_by=$2

  : "${ACCOUNT_USERNAME:?ACCOUNT_USERNAME must be set}"
  desktop_require_absolute_account_home
  validate_systemd_unit_name "$unit"
  validate_systemd_unit_name "$wanted_by"

  link_target=$(desktop_user_unit_link_target "$unit" || true)
  if [ -z "$link_target" ]; then
    installer_warn "target user unit is unavailable; skipping per-user enablement: ${unit}"
    return 0
  fi

  account_ids=$(desktop_primary_account_ids "$ACCOUNT_USERNAME" || true)
  case "$account_ids" in
    *:*) ;;
    *) installer_fatal "target uid/gid is unavailable for desktop user-unit enablement: ${ACCOUNT_USERNAME}" ;;
  esac
  account_uid=${account_ids%%:*}
  account_gid=${account_ids#*:}
  case "$account_uid" in
    ''|*[!0-9]*) installer_fatal "target uid is unavailable for desktop user-unit enablement: ${ACCOUNT_USERNAME}" ;;
  esac
  case "$account_gid" in
    ''|*[!0-9]*) installer_fatal "target gid is unavailable for desktop user-unit enablement: ${ACCOUNT_USERNAME}" ;;
  esac
  [ "$account_uid" -gt 0 ] ||
    installer_fatal "desktop user-unit enablement refuses the root account"
  [ "$account_gid" -gt 0 ] ||
    installer_fatal "desktop user-unit enablement refuses the root group"

  template_dir=$(desktop_user_unit_template_dir)
  template_wants="${template_dir}/${wanted_by}.wants"
  account_unit_dir="${ACCOUNT_HOME}/.config/systemd/user"
  account_wants="${account_unit_dir}/${wanted_by}.wants"
  template_link="/target${template_wants}/${unit}"
  account_link="/target${account_wants}/${unit}"

  [ -d "/target${template_dir}" ] && [ ! -L "/target${template_dir}" ] ||
    installer_fatal "desktop user-unit template directory is unsafe: ${template_dir}"
  [ -d "/target${account_unit_dir}" ] && [ ! -L "/target${account_unit_dir}" ] ||
    installer_fatal "desktop account user-unit directory is unsafe: ${account_unit_dir}"
  install -d -m 0700 "/target${template_wants}" "/target${account_wants}"
  if [ -e "$template_link" ] && [ ! -L "$template_link" ]; then
    installer_fatal "desktop user-unit template enablement path is unsafe: ${template_wants}/${unit}"
  fi
  if [ -e "$account_link" ] && [ ! -L "$account_link" ]; then
    installer_fatal "desktop account user-unit enablement path is unsafe: ${account_wants}/${unit}"
  fi
  ln -sfn "$link_target" "$template_link"
  ln -sfn "$link_target" "$account_link"
  chown "$account_uid:$account_gid" "/target${account_unit_dir}" "/target${account_wants}"
  chown -h "$account_uid:$account_gid" "$account_link"
  if command -v unstage_target_systemd_unit_enabled >/dev/null 2>&1; then
    unstage_target_systemd_unit_enabled "$unit" user
  fi
  desktop_log "staged_user_unit_session_bound unit=${unit} source=${link_target} target=${wanted_by} account=${ACCOUNT_USERNAME}"
}

desktop_stage_global_user_unit_dropin_asset() {
  unit=$1
  dropin_name=$2
  unit_path=$(desktop_user_unit_source_path "$unit" || true)

  if [ -z "$unit_path" ]; then
    installer_warn "target user unit is unavailable; skipping drop-in: ${unit}"
    return 0
  fi

  dropin_relpath="etc/systemd/user/${unit}.d/${dropin_name}"
  dropin_path="/${dropin_relpath}"
  desktop_stage_role_asset "$dropin_relpath" "$dropin_path" 0644
  desktop_log "staged_global_user_unit_dropin unit=${unit} unit_path=${unit_path} target=${dropin_path}"
}

desktop_stage_wireplumber_user_conditions() {
  : "${LABWC_GREETER_USER:?LABWC_GREETER_USER must be set}"
  unit=wireplumber.service
  unit_path=$(desktop_user_unit_source_path "$unit" || true)

  if [ -z "$unit_path" ]; then
    installer_warn "target user unit is unavailable; skipping drop-in: ${unit}"
    return 0
  fi

  desktop_render_role_target_template \
    etc/systemd/user/wireplumber.service.d/20-no-root.conf.tmpl \
    /etc/systemd/user/wireplumber.service.d/20-no-root.conf \
    0644 \
    LABWC_GREETER_USER "$LABWC_GREETER_USER"
  desktop_log "staged_wireplumber_user_conditions unit=${unit} unit_path=${unit_path} greeter=${LABWC_GREETER_USER}"
}

desktop_stage_pipewire_user_conditions() {
  : "${LABWC_GREETER_USER:?LABWC_GREETER_USER must be set}"
  for unit in pipewire.socket pipewire.service pipewire-pulse.socket pipewire-pulse.service; do
    desktop_render_role_target_template \
      "etc/systemd/user/${unit}.d/20-no-greeter.conf.tmpl" \
      "/etc/systemd/user/${unit}.d/20-no-greeter.conf" \
      0644 \
      LABWC_GREETER_USER "$LABWC_GREETER_USER"
    desktop_log "staged_pipewire_user_conditions unit=${unit} greeter=${LABWC_GREETER_USER}"
  done
}

desktop_stage_labwc_package_user_unit_dropins() {
  for unit in \
    foot-server.service \
    foot-server.socket \
    gvfs-daemon.service \
    gvfs-udisks2-volume-monitor.service \
    mako.service \
    hyprpolkitagent.service \
    filter-chain.service \
    xdg-desktop-portal.service \
    xdg-desktop-portal-gtk.service \
    xdg-desktop-portal-wlr.service \
    xdg-desktop-portal-lxqt.service
  do
    desktop_stage_global_user_unit_dropin_asset "$unit" 10-labwc-session.conf
  done
}

desktop_stage_wayscriber_service() {
  [ -x /target/usr/bin/wayscriber ] ||
    installer_fatal "Wayscriber package executable is missing from the target"

  unit_path=$(target_systemd_unit_path wayscriber.service user 2>/dev/null || true)
  [ -n "$unit_path" ] ||
    installer_fatal "Wayscriber package user service is missing from the target"

  desktop_stage_global_user_unit_dropin_asset wayscriber.service 10-labwc-session.conf
  desktop_log "staged_wayscriber_service unit_path=${unit_path} target=labwc-session.target"
}

desktop_stage_kwallet_dbus_activation_assets() {
  [ -x /target/usr/bin/ksecretd ] ||
    installer_fatal "KWallet secret portal executable is missing from the target"
  [ -x /target/usr/bin/kwalletd6 ] ||
    installer_fatal "KWallet daemon executable is missing from the target"
  [ -x /target/usr/bin/busctl ] ||
    installer_fatal "systemd D-Bus inspection client is missing from the target"

  # Debian already owns the portal, compatibility, and kwalletd6 service names.
  # Add only the Secret Service alias that the package does not provide.
  desktop_stage_role_asset \
    etc/skel-desktop/.local/share/dbus-1/services/org.freedesktop.secrets.service \
    /etc/skel-desktop/.local/share/dbus-1/services/org.freedesktop.secrets.service \
    0644
  desktop_log "staged_account_local_kwallet_secret_service_activation path=/etc/skel-desktop/.local/share/dbus-1/services/org.freedesktop.secrets.service"
}

desktop_stage_labwc_user_session_assets() {
  desktop_stage_role_asset \
    etc/systemd/system/user@.service.d/20-labwc-seatd.conf \
    /etc/systemd/system/user@.service.d/20-labwc-seatd.conf \
    0644
  desktop_stage_role_asset \
    etc/skel-desktop/.config/systemd/user/labwc-compositor.service \
    /etc/skel-desktop/.config/systemd/user/labwc-compositor.service \
    0644
  desktop_stage_role_asset \
    etc/skel-desktop/.config/systemd/user/labwc-session.target \
    /etc/skel-desktop/.config/systemd/user/labwc-session.target \
    0644
  desktop_stage_role_asset \
    etc/skel-desktop/.config/systemd/user/labwc-health-notify.service \
    /etc/skel-desktop/.config/systemd/user/labwc-health-notify.service \
    0644
  desktop_stage_role_asset \
    etc/skel-desktop/.config/systemd/user/labwc-health-notify.path \
    /etc/skel-desktop/.config/systemd/user/labwc-health-notify.path \
    0644
  desktop_stage_role_asset \
    etc/skel-desktop/.config/systemd/user/labwc-health-notify.timer \
    /etc/skel-desktop/.config/systemd/user/labwc-health-notify.timer \
    0644
  desktop_stage_role_asset \
    etc/skel-desktop/.config/systemd/user/labwc-plans.service \
    /etc/skel-desktop/.config/systemd/user/labwc-plans.service \
    0644

  # All app- scopes share the Labwc session lifetime, including new vendors.
  # This prefix drop-in does not apply to unrelated scopes or services.
  desktop_stage_role_asset \
    "etc/skel-desktop/.config/systemd/user/app-.scope.d/50-session-labwc.conf" \
    "/etc/skel-desktop/.config/systemd/user/app-.scope.d/50-session-labwc.conf" \
    0644

  desktop_stage_labwc_package_user_unit_dropins
  desktop_stage_wireplumber_user_conditions
  desktop_stage_pipewire_user_conditions
  desktop_stage_wayscriber_service
  desktop_stage_kwallet_dbus_activation_assets

  for global_user_systemd_dir in \
    /target/etc/systemd/user \
    /target/etc/systemd/user/*.d
  do
    [ -d "$global_user_systemd_dir" ] || continue
    chown 0:0 "$global_user_systemd_dir"
    chmod 0755 "$global_user_systemd_dir"
  done
  for user_systemd_dir in \
    /target/etc/skel-desktop/.config/systemd \
    /target/etc/skel-desktop/.config/systemd/user \
    /target/etc/skel-desktop/.config/systemd/user/*.d
  do
    [ -d "$user_systemd_dir" ] || continue
    chmod 0700 "$user_systemd_dir"
  done
}

