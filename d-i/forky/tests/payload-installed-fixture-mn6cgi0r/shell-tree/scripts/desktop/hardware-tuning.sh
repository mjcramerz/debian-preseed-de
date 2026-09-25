#!/bin/sh
# Sourced by the desktop late hook. No tuning operation is performed in d-i.

desktop_hardware_intel_detected() {
  awk '$1 == "vendor_id" { seen=1; if ($3 != "GenuineIntel") bad=1 }
       END { exit !(seen && !bad) }' /proc/cpuinfo
}

desktop_install_hardware_tuning() (
  set -eu
  umask 077
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

  for hardware_module in common engine broker client policy_owner system_state $hardware_vendors; do
    desktop_stage_role_asset "usr/local/lib/hardware_tuning/${hardware_module}.py" "/usr/local/lib/hardware_tuning/${hardware_module}.py" 0644 || exit 1
  done
  desktop_stage_role_asset usr/local/bin/labwc-hardware-tuning /usr/local/bin/labwc-hardware-tuning 0755 || exit 1
  desktop_stage_role_asset usr/local/libexec/hardware-tuningd /usr/local/libexec/hardware-tuningd 0755 || exit 1
  desktop_stage_role_asset usr/local/libexec/hardware-tuning-worker /usr/local/libexec/hardware-tuning-worker 0755 || exit 1
  desktop_stage_role_asset usr/local/libexec/hardware-tuning-policy /usr/local/libexec/hardware-tuning-policy 0755 || exit 1
  desktop_stage_role_asset etc/apparmor.d/hardware-tuning /etc/apparmor.d/hardware-tuning 0644 || exit 1
  for hardware_bridge in desktop-parent fuzzel-parent management-parent; do
    desktop_stage_role_asset "etc/apparmor.d/abstractions/hardware-tuning-${hardware_bridge}" "/etc/apparmor.d/abstractions/hardware-tuning-${hardware_bridge}" 0644 || exit 1
  done
  for hardware_vendor in $hardware_vendors; do
    desktop_stage_role_asset "etc/apparmor.d/abstractions/hardware-tuning-${hardware_vendor}" "/etc/apparmor.d/abstractions/hardware-tuning-${hardware_vendor}" 0644 || exit 1
  done

  : "${LATE_COMMAND_HOST_ENV:?hardware tuning requires the loaded host profile}"
  : "${ACCOUNT_USERNAME:?hardware tuning requires the desktop account}"
  hardware_stage=$(target_private_stage_dir hardware-tuning) || exit 1
  hardware_stage_host=$(target_asset_host_path "$hardware_stage") || exit 1
  trap 'rm -rf -- "$hardware_stage_host"' 0
  trap 'exit 129' HUP
  trap 'exit 130' INT
  trap 'exit 143' TERM
  # Never copy the account file or unrelated (potentially secret) profile data.
  # The Python installer parses these as literals; it never sources/evals them.
  (umask 077; awk '/^HARDWARE_(INTEL_CPU_TUNING|NVIDIA_GPU_TUNING|TUNING)_[A-Z0-9_]+=/ {print}' \
      "$LATE_COMMAND_HOST_ENV" >"${hardware_stage_host}/policy.env") || exit 1
  fetch_hook scripts/desktop/hardware-tuning-config.py "${hardware_stage_host}/config.py" || exit 1
  chmod 0700 "${hardware_stage_host}/config.py" || exit 1
  fetch_hook scripts/desktop/hardware-tuning-assets.list "${hardware_stage_host}/assets.list" || exit 1
  while IFS= read -r hardware_asset; do
    case "$hardware_asset" in etc/systemd/*|etc/hardware-tuning/*) ;; *) exit 1 ;; esac
    case "$hardware_asset" in *..*|*//*|*[!A-Za-z0-9_./-]*) exit 1 ;; esac
    install -d -m 0700 "${hardware_stage_host}/templates/${hardware_asset%/*}" || exit 1
    fetch_hook "$(installer_repo_join_var DIR_HOOKS_TARGET "$hardware_asset")" "${hardware_stage_host}/templates/${hardware_asset}" || exit 1
  done < "${hardware_stage_host}/assets.list" || exit 1
  # Intentional split: hardware_vendors is assembled ONLY from literal names.
  # shellcheck disable=SC2086
  run_in_target "install gated hardware tuning profiles and lifecycle units" \
    /usr/bin/python3 -I "${hardware_stage}/config.py" "${hardware_stage}/policy.env" "$ACCOUNT_USERNAME" "${hardware_stage}/templates" $hardware_vendors || exit 1
  run_in_target "validate hardware tuning AppArmor policy without loading into the installer kernel" \
    /usr/sbin/apparmor_parser --skip-kernel-load --skip-cache /etc/apparmor.d/hardware-tuning || exit 1
  desktop_log "installed hardware tuning vendors=${hardware_vendors}; automatic/autostart default remains opt-in"
)
