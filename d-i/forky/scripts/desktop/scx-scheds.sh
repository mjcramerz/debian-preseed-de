#!/bin/sh
# Configure the profile-pinned sched_ext userspace packages without building them.

desktop_validate_scx_scheduler_policy() {
  desktop_scx_enabled=${HARDWARE_CPU_SCHEDULER_SCX_ENABLE:-false}
  case "$desktop_scx_enabled" in
    true|false) ;;
    *) installer_fatal "HARDWARE_CPU_SCHEDULER_SCX_ENABLE must be true or false" ;;
  esac

  desktop_scx_mode=${HARDWARE_CPU_SCHEDULER_SCX_MODE:-on-demand}
  case "$desktop_scx_mode" in
    direct|on-demand) ;;
    *) installer_fatal "HARDWARE_CPU_SCHEDULER_SCX_MODE must be direct or on-demand" ;;
  esac
}

desktop_require_scx_file() {
  scx_path=$1
  scx_host_path=$(target_asset_host_path "$scx_path") || exit 1
  [ -f "$scx_host_path" ] && [ ! -L "$scx_host_path" ] ||
    installer_fatal "scx-scheds package asset is missing or unsafe: ${scx_path}"
}

desktop_install_scx_scheduler() (
  set -eu
  desktop_validate_scx_scheduler_policy

  if [ "$desktop_scx_enabled" = false ]; then
    desktop_log "scx-scheds disabled by host profile; package assets and units remain absent"
    return 0
  fi

  # The profile-controlled packages are imported and installed by the software
  # late helper. Require both the long-running default and the interactive
  # DevOps handoff scheduler before publishing managed config.
  for scx_unit in scx.service scx_loader.service; do
    scx_unit_path=$(target_systemd_unit_path "$scx_unit" system 2>/dev/null || true)
    [ -n "$scx_unit_path" ] ||
      installer_fatal "scx-scheds package unit is unavailable: ${scx_unit}"
  done
  for scx_asset in \
    /usr/bin/scx_rusty \
    /usr/bin/scx_flash \
    /usr/bin/scx_loader \
    /usr/bin/scxctl \
    /usr/share/dbus-1/system-services/org.scx.Loader.service \
    /usr/share/dbus-1/system.d/org.scx.Loader.conf \
    /usr/share/dbus-1/interfaces/org.scx.Loader.xml \
    /usr/share/polkit-1/actions/org.scx.Loader.policy
  do
    desktop_require_scx_file "$scx_asset"
  done

  desktop_stage_role_asset etc/default/scx /etc/default/scx 0644
  desktop_stage_role_asset etc/scx_loader/config.toml /etc/scx_loader/config.toml 0644
  desktop_stage_role_asset \
    etc/systemd/system/scx.service.d/50-sched-ext.conf \
    /etc/systemd/system/scx.service.d/50-sched-ext.conf 0644
  desktop_stage_role_asset \
    etc/systemd/system/scx_loader.service.d/50-sched-ext.conf \
    /etc/systemd/system/scx_loader.service.d/50-sched-ext.conf 0644

  # Never enable both package backends: each can load a sched_ext scheduler.
  # Keeping both installed preserves the packaged manual fallback interfaces.
  case "$desktop_scx_mode" in
    direct)
      desktop_disable_unit_if_available scx_loader.service system
      # Direct mode owns the long-running scheduler at boot. The loader remains
      # installed for diagnostics/manual recovery but cannot race this unit.
      desktop_enable_unit_if_available scx.service system
      desktop_log "configured scx-scheds scheduler=scx_rusty activation=boot mode=direct enabled=${desktop_scx_enabled}"
      ;;
    on-demand)
      # The loader is the sole boot owner. Its packaged Type=dbus service
      # starts the configured default scheduler when it registers the bus name;
      # enabling it through multi-user.target makes that startup automatic.
      desktop_disable_unit_if_available scx.service system
      desktop_enable_unit_if_available scx_loader.service system
      desktop_log "configured scx-scheds scheduler=scx_rusty loader=scx_loader.service activation=boot mode=on-demand devops_switch=scx_flash enabled=${desktop_scx_enabled}"
      ;;
  esac
)
