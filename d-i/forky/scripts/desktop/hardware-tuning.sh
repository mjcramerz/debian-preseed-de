#!/bin/sh
# Sourced by the desktop late hook. No tuning operation is performed in d-i.

desktop_hardware_intel_detected() {
  awk '$1 == "vendor_id" { seen=1; if ($3 != "GenuineIntel") bad=1 }
       END { exit !(seen && !bad) }' /proc/cpuinfo
}

desktop_install_hardware_tuning() (
  set -eu
  for hardware_flag in "${HARDWARE_INTEL_CPU_TUNING_ENABLE:-false}" "${HARDWARE_NVIDIA_GPU_TUNING_ENABLE:-false}"; do
    case "$hardware_flag" in true|false) ;; *) installer_fatal "hardware tuning enable flags must be literal true or false"; exit 1 ;; esac
  done
  hardware_vendors=
  if [ "${HARDWARE_INTEL_CPU_TUNING_ENABLE:-false}" = true ] && desktop_hardware_intel_detected; then
    hardware_vendors=intel
  fi
  if [ "${HARDWARE_NVIDIA_GPU_TUNING_ENABLE:-false}" = true ] &&
      installer_nvidia_addon_selected && installer_nvidia_gpu_detected; then
    hardware_vendors="${hardware_vendors:+${hardware_vendors} }nvidia"
  fi
  if [ -z "$hardware_vendors" ]; then
    desktop_log "hardware tuning not installed: disabled or hardware/class gates not satisfied"
    return 0
  fi

  for hardware_module in common engine broker client $hardware_vendors; do
    desktop_stage_role_asset "usr/local/lib/hardware_tuning/${hardware_module}.py" "/usr/local/lib/hardware_tuning/${hardware_module}.py" 0644
  done
  desktop_stage_role_asset usr/local/bin/labwc-hardware-tuning /usr/local/bin/labwc-hardware-tuning 0755
  desktop_stage_role_asset usr/local/libexec/hardware-tuningd /usr/local/libexec/hardware-tuningd 0755
  desktop_stage_role_asset usr/local/libexec/hardware-tuning-worker /usr/local/libexec/hardware-tuning-worker 0755
  desktop_stage_role_asset etc/apparmor.d/managed-hardware-tuning /etc/apparmor.d/managed-hardware-tuning 0644
  for hardware_bridge in desktop-parent fuzzel-parent; do
    desktop_stage_role_asset "etc/apparmor.d/abstractions/managed-hardware-tuning-${hardware_bridge}" "/etc/apparmor.d/abstractions/managed-hardware-tuning-${hardware_bridge}" 0644
  done
  for hardware_vendor in $hardware_vendors; do
    desktop_stage_role_asset "etc/apparmor.d/abstractions/managed-hardware-tuning-${hardware_vendor}" "/etc/apparmor.d/abstractions/managed-hardware-tuning-${hardware_vendor}" 0644
  done

  : "${LATE_COMMAND_HOST_ENV:?hardware tuning requires the loaded host profile}"
  : "${ACCOUNT_USERNAME:?hardware tuning requires the desktop account}"
  hardware_stage=/var/lib/unattended-installer/hardware-tuning-stage
  ensure_target_asset_parent "${hardware_stage}/config.py"
  hardware_stage_host=$(target_asset_host_path "${hardware_stage}/config.py")
  hardware_stage_host=${hardware_stage_host%/config.py}
  [ -d "$hardware_stage_host" ] && [ ! -L "$hardware_stage_host" ] || exit 1
  chmod 0700 "$hardware_stage_host"
  trap 'rm -f -- "${hardware_stage_host}/config.py" "${hardware_stage_host}/policy.env"; rmdir -- "$hardware_stage_host"' 0
  trap 'exit 129' HUP
  trap 'exit 130' INT
  trap 'exit 143' TERM
  # Never copy the account file or unrelated (potentially secret) profile data.
  # The Python installer parses these as literals; it never sources/evals them.
  (umask 077; awk '/^HARDWARE_(INTEL_CPU_TUNING|NVIDIA_GPU_TUNING|TUNING)_[A-Z0-9_]+=/ {print}' \
      "$LATE_COMMAND_HOST_ENV" >"${hardware_stage_host}/policy.env")
  fetch_hook scripts/desktop/hardware-tuning-config.py "${hardware_stage_host}/config.py"
  chmod 0700 "${hardware_stage_host}/config.py"
  # Intentional split: hardware_vendors is assembled ONLY from literal names.
  # shellcheck disable=SC2086
  run_in_target "install gated hardware tuning profiles and lifecycle units" \
    /usr/bin/python3 -I "${hardware_stage}/config.py" "${hardware_stage}/policy.env" "$ACCOUNT_USERNAME" $hardware_vendors
  run_in_target "validate hardware tuning AppArmor policy without loading into the installer kernel" \
    /usr/sbin/apparmor_parser --skip-kernel-load --skip-cache /etc/apparmor.d/managed-hardware-tuning
  desktop_log "installed hardware tuning vendors=${hardware_vendors}; automatic/autostart default remains opt-in"
)
