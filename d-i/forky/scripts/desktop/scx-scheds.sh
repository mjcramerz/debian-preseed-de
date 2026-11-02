#!/bin/sh
# Configure the packaged XanMod sched_ext userspace without building it.

desktop_validate_scx_scheduler_policy() {
  case "${HARDWARE_CPU_SCHEDULER_SCX_ENABLE:-false}" in
    true|false) ;;
    *) installer_fatal "HARDWARE_CPU_SCHEDULER_SCX_ENABLE must be true or false" ;;
  esac
}

desktop_require_scx_file() {
  scx_path=$1
  scx_host_path="/target${scx_path}"
  [ -f "$scx_host_path" ] && [ ! -L "$scx_host_path" ] ||
    installer_fatal "scx-scheds package asset is missing or unsafe: ${scx_path}"
}

desktop_install_scx_scheduler() (
  set -eu
  desktop_validate_scx_scheduler_policy

  # The package is selected in the desktop role. Require its service, loader,
  # D-Bus activation, and selected scheduler before publishing managed config.
  for scx_unit in scx.service scx_loader.service; do
    scx_unit_path=$(target_systemd_unit_path "$scx_unit" system 2>/dev/null || true)
    [ -n "$scx_unit_path" ] ||
      installer_fatal "scx-scheds package unit is unavailable: ${scx_unit}"
  done
  for scx_asset in \
    /usr/sbin/scx_flash \
    /usr/sbin/scx_loader \
    /usr/sbin/scxctl \
    /usr/share/dbus-1/system-services/org.scx.Loader.service \
    /usr/share/dbus-1/system.d/org.scx.Loader.conf
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
  desktop_disable_unit_if_available scx.service system
  desktop_disable_unit_if_available scx_loader.service system
  if [ "${HARDWARE_CPU_SCHEDULER_SCX_ENABLE}" = true ]; then
    desktop_enable_unit_if_available scx_loader.service system
  fi
  desktop_log "configured scx-scheds scheduler=scx_flash loader=org.scx.Loader autostart=${HARDWARE_CPU_SCHEDULER_SCX_ENABLE}"
)
