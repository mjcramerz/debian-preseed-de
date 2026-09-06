#!/bin/sh
set -eu

ARCH_RAW_CACHE=
ARCH_RAW_READY=false
CPU_MODEL_CACHE=
CPU_MODEL_READY=false
CPU_VENDOR_CACHE=
CPU_VENDOR_READY=false
CPU_HYPERVISOR_CACHE=
CPU_HYPERVISOR_READY=false
DMI_TEXT_CACHE=
DMI_TEXT_READY=false
DEVICE_TREE_TEXT_CACHE=
DEVICE_TREE_TEXT_READY=false
PCI_DEVICE_TABLE=
PCI_SCAN_READY=false
STORAGE_PROBE_READY=false
VM_TYPE_CACHE=
VM_TYPE_READY=false
MMC_BASE_CACHE=
MMC_BASE_READY=false
NVME_BASE_CACHE=
NVME_BASE_READY=false

block_sys_root() {
  printf '%s\n' "${CLASS_AUTO_SYS_BLOCK_ROOT:-/sys/block}"
}

pci_devices_root() {
  printf '%s\n' "${CLASS_AUTO_SYS_PCI_DEVICES_ROOT:-/sys/bus/pci/devices}"
}

read_first_line() {
  [ -r "$1" ] || return 1
  IFS= read -r value <"$1" || return 1
  printf '%s' "$value"
}

line() {
  printf '%-24s %s\n' "$1:" "$2"
}

yn() {
  if "$@"; then
    printf yes
  else
    printf no
  fi
}

arch_raw() {
  if [ "$ARCH_RAW_READY" = true ]; then
    printf '%s' "$ARCH_RAW_CACHE"
    return 0
  fi
  ARCH_RAW_CACHE=$(uname -m 2>/dev/null || printf unknown)
  ARCH_RAW_READY=true
  printf '%s' "$ARCH_RAW_CACHE"
}

arch_class() {
  case "$(arch_raw)" in
    x86_64) printf amd64 ;;
    aarch64|arm64) printf arm64 ;;
    *) return 1 ;;
  esac
}

cpu_vendor() {
  if [ "$CPU_VENDOR_READY" = true ]; then
    [ -n "$CPU_VENDOR_CACHE" ] || return 1
    printf '%s' "$CPU_VENDOR_CACHE"
    return 0
  fi

  CPU_VENDOR_CACHE=
  if [ -r /proc/cpuinfo ]; then
    while IFS= read -r line_value; do
      case "$line_value" in
        "vendor_id"*:*|"CPU implementer"*:*)
          vendor_value=${line_value#*:}
          while :; do
            case "$vendor_value" in
              " "*) vendor_value=${vendor_value# } ;;
              *) break ;;
            esac
          done
          CPU_VENDOR_CACHE=$vendor_value
          break
          ;;
      esac
    done </proc/cpuinfo
  fi
  CPU_VENDOR_READY=true
  [ -n "$CPU_VENDOR_CACHE" ] || return 1
  printf '%s' "$CPU_VENDOR_CACHE"
}

cpu_intel() {
  [ "$(cpu_vendor 2>/dev/null || true)" = GenuineIntel ]
}

cpu_amd() {
  [ "$(cpu_vendor 2>/dev/null || true)" = AuthenticAMD ]
}

cpu_class() {
  if cpu_intel; then
    printf intel
  elif cpu_amd; then
    printf amd
  else
    return 1
  fi
}

cpu_model() {
  if [ "$CPU_MODEL_READY" = true ]; then
    printf '%s' "$CPU_MODEL_CACHE"
    return 0
  fi

  CPU_MODEL_CACHE=unknown
  [ -r /proc/cpuinfo ] || {
    CPU_MODEL_READY=true
    printf '%s' "$CPU_MODEL_CACHE"
    return
  }

  while IFS= read -r line_value; do
    case "$line_value" in
      "model name"*:*|"Processor"*:*|"Hardware"*:*)
        model_value=${line_value#*:}
        while :; do
          case "$model_value" in
            " "*) model_value=${model_value# } ;;
            *) break ;;
          esac
        done
        [ -n "$model_value" ] && {
          CPU_MODEL_CACHE=$model_value
          CPU_MODEL_READY=true
          printf '%s' "$CPU_MODEL_CACHE"
          return
        }
        ;;
    esac
  done </proc/cpuinfo

  CPU_MODEL_READY=true
  printf '%s' "$CPU_MODEL_CACHE"
}

pci_scan_ensure() {
  [ "$PCI_SCAN_READY" = true ] && return 0

  PCI_DEVICE_TABLE=
  for dev_path in "$(pci_devices_root)"/*; do
    [ -d "$dev_path" ] || continue
    [ -r "$dev_path/vendor" ] || continue
    [ -r "$dev_path/class" ] || continue
    vendor=$(read_first_line "$dev_path/vendor" 2>/dev/null || true)
    class=$(read_first_line "$dev_path/class" 2>/dev/null || true)
    [ -n "$vendor" ] || continue
    [ -n "$class" ] || continue
    PCI_DEVICE_TABLE="${PCI_DEVICE_TABLE:+$PCI_DEVICE_TABLE
}${dev_path##*/}|${vendor}|${class}"
  done
  PCI_SCAN_READY=true
}

pci_has_class_prefix() {
  wanted_prefix=$1

  pci_scan_ensure
  while IFS='|' read -r pci_name _vendor class || [ -n "$pci_name" ]; do
    [ -n "$pci_name" ] || continue
    case "$class" in
      "$wanted_prefix"*) return 0 ;;
    esac
  done <<EOF
$PCI_DEVICE_TABLE
EOF

  return 1
}

pci_has_display_vendor() {
  wanted_vendor=$1

  pci_scan_ensure
  while IFS='|' read -r pci_name vendor class || [ -n "$pci_name" ]; do
    [ -n "$pci_name" ] || continue
    case "$class" in
      0x03*)
        [ "$vendor" = "$wanted_vendor" ] && return 0
        ;;
    esac
  done <<EOF
$PCI_DEVICE_TABLE
EOF

  return 1
}

storage_probe_prepare() {
  [ "$STORAGE_PROBE_READY" = true ] && return 0

  if [ "${CLASS_AUTO_SKIP_MODULE_PROBE:-0}" != 1 ] && [ "$(block_sys_root)" = /sys/block ]; then
    if command -v modprobe >/dev/null 2>&1; then
      for module_name in \
        nvme nvme_core \
        ahci libahci sd_mod scsi_mod \
        virtio_blk virtio_pci virtio_scsi \
        xen-blkfront \
        mmc_block
      do
        modprobe "$module_name" >/dev/null 2>&1 || true
      done
    fi
    if command -v udevadm >/dev/null 2>&1; then
      udevadm settle --timeout=5 >/dev/null 2>&1 || true
    fi
  fi

  STORAGE_PROBE_READY=true
}

gpu_name() {
  case "$1" in
    0x8086) printf Intel ;;
    0x1002) printf AMD_Radeon ;;
    0x10de) printf NVIDIA ;;
    *) printf unknown ;;
  esac
}

emit_gpu_classes() {
  emitted=false

  if pci_has_display_vendor 0x8086; then
    printf '%s\n' gpu/intel-uhd
    emitted=true
  fi
  if pci_has_display_vendor 0x1002; then
    printf '%s\n' gpu/amd-radeon
    emitted=true
  fi
  if [ "$emitted" != true ]; then
    printf '%s\n' gpu/generic
  fi
}

is_mmc_base() {
  case "$1" in
    mmcblk[0-9]|mmcblk[0-9][0-9]|mmcblk[0-9][0-9][0-9]) return 0 ;;
  esac
  return 1
}

is_nvme_base() {
  case "$1" in
    nvme[0-9]*n[0-9]*)
      case "$1" in
        *p[0-9]*) return 1 ;;
      esac
      return 0
      ;;
  esac
  return 1
}

disk_mmcblk() {
  if [ "$MMC_BASE_READY" = true ]; then
    [ "$MMC_BASE_CACHE" = true ]
    return "$?"
  fi

  storage_probe_prepare
  MMC_BASE_CACHE=false
  for dev_path in "$(block_sys_root)"/mmcblk*; do
    [ -d "$dev_path" ] || continue
    if is_mmc_base "${dev_path##*/}"; then
      MMC_BASE_CACHE=true
      break
    fi
  done
  MMC_BASE_READY=true
  [ "$MMC_BASE_CACHE" = true ]
}

disk_nvme() {
  if [ "$NVME_BASE_READY" = true ]; then
    [ "$NVME_BASE_CACHE" = true ]
    return "$?"
  fi

  storage_probe_prepare
  NVME_BASE_CACHE=false
  for dev_path in "$(block_sys_root)"/nvme*n*; do
    [ -d "$dev_path" ] || continue
    if is_nvme_base "${dev_path##*/}"; then
      NVME_BASE_CACHE=true
      break
    fi
  done
  NVME_BASE_READY=true
  [ "$NVME_BASE_CACHE" = true ]
}

disk_nvme_controller() {
  pci_has_class_prefix 0x010802
}

disk_virtual_block() {
  storage_probe_prepare
  for dev_path in "$(block_sys_root)"/vd* "$(block_sys_root)"/xvd*; do
    [ -d "$dev_path" ] || continue
    return 0
  done
  return 1
}

disk_fixed_baremetal() {
  storage_probe_prepare
  for dev_path in "$(block_sys_root)"/*; do
    [ -d "$dev_path" ] || continue
    disk_name=${dev_path##*/}
    case "$disk_name" in
      sd*) ;;
      *) continue ;;
    esac
    removable=$(read_first_line "$dev_path/removable" 2>/dev/null || printf unknown)
    case "$removable" in
      1) continue ;;
    esac
    return 0
  done
  return 1
}

match_file() {
  file=$1
  pattern=$2

  [ -r "$file" ] || return 1
  grep -qi "$pattern" "$file" 2>/dev/null
}

match_dmi() {
  pattern=$1

  if [ "$DMI_TEXT_READY" != true ]; then
    DMI_TEXT_CACHE=
    for file in \
      /sys/class/dmi/id/sys_vendor \
      /sys/class/dmi/id/product_name \
      /sys/class/dmi/id/product_version \
      /sys/class/dmi/id/board_vendor \
      /sys/class/dmi/id/board_name \
      /sys/class/dmi/id/bios_vendor \
      /sys/class/dmi/id/bios_version
    do
      [ -r "$file" ] || continue
      dmi_value=$(read_first_line "$file" 2>/dev/null || true)
      [ -n "$dmi_value" ] || continue
      DMI_TEXT_CACHE="${DMI_TEXT_CACHE:+$DMI_TEXT_CACHE
}$dmi_value"
    done
    DMI_TEXT_READY=true
  fi

  [ -n "$DMI_TEXT_CACHE" ] || return 1
  printf '%s\n' "$DMI_TEXT_CACHE" | grep -qi "$pattern" 2>/dev/null
}

cpu_has_hypervisor_flag() {
  if [ "$CPU_HYPERVISOR_READY" = true ]; then
    [ "$CPU_HYPERVISOR_CACHE" = true ]
    return "$?"
  fi

  if grep -q hypervisor /proc/cpuinfo 2>/dev/null; then
    CPU_HYPERVISOR_CACHE=true
  else
    CPU_HYPERVISOR_CACHE=false
  fi
  CPU_HYPERVISOR_READY=true
  [ "$CPU_HYPERVISOR_CACHE" = true ]
}

pci_has_vendor() {
  wanted_vendor=$1

  pci_scan_ensure
  while IFS='|' read -r pci_name vendor _class || [ -n "$pci_name" ]; do
    [ -n "$pci_name" ] || continue
    [ "$vendor" = "$wanted_vendor" ] && return 0
  done <<EOF
$PCI_DEVICE_TABLE
EOF

  return 1
}

match_device_tree() {
  pattern=$1

  if [ "$DEVICE_TREE_TEXT_READY" != true ]; then
    DEVICE_TREE_TEXT_CACHE=
  for file in \
      /proc/device-tree/model \
      /proc/device-tree/compatible \
      /sys/firmware/devicetree/base/model \
      /sys/firmware/devicetree/base/compatible
  do
      [ -r "$file" ] || continue
      device_tree_value=$(tr '\000' '\n' <"$file" 2>/dev/null || true)
      [ -n "$device_tree_value" ] || continue
      DEVICE_TREE_TEXT_CACHE="${DEVICE_TREE_TEXT_CACHE:+$DEVICE_TREE_TEXT_CACHE
}$device_tree_value"
  done
    DEVICE_TREE_TEXT_READY=true
  fi

  [ -n "$DEVICE_TREE_TEXT_CACHE" ] || return 1
  printf '%s\n' "$DEVICE_TREE_TEXT_CACHE" | grep -qi "$pattern" 2>/dev/null
}

vm_type_detect() {
  if match_dmi 'KVM'; then printf kvm; return; fi
  if match_dmi 'QEMU'; then printf qemu; return; fi
  if match_dmi 'VMware'; then printf vmware; return; fi
  if match_dmi 'VirtualBox'; then printf virtualbox; return; fi
  if match_dmi 'Hyper-V'; then printf hyperv; return; fi
  if match_dmi 'Microsoft Corporation' && match_dmi 'Virtual Machine'; then printf hyperv; return; fi
  if match_dmi 'Xen'; then printf xen; return; fi
  if match_dmi 'Parallels'; then printf parallels; return; fi
  if match_dmi 'BHYVE'; then printf bhyve; return; fi
  if match_dmi 'Amazon EC2'; then printf amazon_ec2; return; fi
  if match_dmi 'Google Compute Engine'; then printf gce; return; fi
  if match_dmi 'OpenStack'; then printf openstack; return; fi

  if pci_has_vendor 0x1af4; then printf virtio; return; fi
  if pci_has_vendor 0x15ad; then printf vmware; return; fi
  if pci_has_vendor 0x80ee; then printf virtualbox; return; fi
  if pci_has_vendor 0x1414; then printf hyperv; return; fi
  if pci_has_vendor 0x5853; then printf xen; return; fi
  if pci_has_vendor 0x1ab8; then printf parallels; return; fi

  if match_device_tree 'linux,dummy-virt'; then printf qemu_arm_virt; return; fi
  if match_device_tree qemu; then printf qemu; return; fi
  if match_device_tree virtio; then printf virtio; return; fi
  if match_device_tree xen; then printf xen; return; fi

  if cpu_has_hypervisor_flag; then printf generic_hypervisor; return; fi

  printf none
}

vm_type() {
  if [ -n "${CLASS_AUTO_VM_TYPE_OVERRIDE:-}" ]; then
    printf '%s' "$CLASS_AUTO_VM_TYPE_OVERRIDE"
    return 0
  fi
  if [ "$VM_TYPE_READY" = true ]; then
    printf '%s' "$VM_TYPE_CACHE"
    return 0
  fi

  VM_TYPE_CACHE=$(vm_type_detect)
  VM_TYPE_READY=true
  printf '%s' "$VM_TYPE_CACHE"
}

is_vm() {
  [ "$(vm_type)" != none ]
}

disk_class() {
  if disk_nvme || disk_nvme_controller; then
    printf nvme
  elif disk_mmcblk; then
    printf emmc
  elif is_vm || disk_virtual_block; then
    printf vm
  elif disk_fixed_baremetal; then
    printf nvme
  else
    return 1
  fi
}

boot_mode() {
  if [ -d /sys/firmware/efi ]; then
    printf UEFI
  else
    printf BIOS
  fi
}

list_gpus() {
  found=false

  pci_scan_ensure
  while IFS='|' read -r pci_name vendor class || [ -n "$pci_name" ]; do
    [ -n "$pci_name" ] || continue
    case "$class" in
      0x03*)
        found=true
        printf '  /sys/bus/pci/devices/%s vendor=%s name=%s class=%s\n' \
          "$pci_name" "$vendor" "$(gpu_name "$vendor")" "$class"
        ;;
    esac
  done <<EOF
$PCI_DEVICE_TABLE
EOF

  [ "$found" = true ] || printf '  none\n'
}

list_disks() {
  found=false

  for dev_path in "$(block_sys_root)"/*; do
    [ -d "$dev_path" ] || continue
    disk_name=${dev_path##*/}
    disk_type=

    case "$disk_name" in
      nvme0n1) disk_type=nvme ;;
      nvme*n*) disk_type=nvme-other ;;
      vd*) disk_type=virtio ;;
      xvd*) disk_type=xen-virt ;;
      sd*) disk_type=scsi-sata-usb ;;
      mmcblk*)
        is_mmc_base "$disk_name" || continue
        disk_type=mmc-emmc-sd
        ;;
      *) continue ;;
    esac

    found=true
    removable=$(read_first_line "$dev_path/removable" 2>/dev/null || printf unknown)
    sectors=$(read_first_line "$dev_path/size" 2>/dev/null || printf unknown)
    printf '  /dev/%s type=%s removable=%s sectors=%s\n' \
      "$disk_name" "$disk_type" "$removable" "$sectors"
  done

  [ "$found" = true ] || printf '  none\n'
}

emit_classes() {
  arch=$(arch_class) || {
    printf 'fatal: unsupported architecture for automatic classes: %s\n' "$(arch_raw)" >&2
    exit 1
  }
  cpu=$(cpu_class) || {
    printf 'fatal: unsupported CPU vendor for automatic classes\n' >&2
    exit 1
  }
  disk=$(disk_class) || {
    printf 'fatal: unable to auto-detect supported install disk class\n' >&2
    exit 1
  }
  gpu_classes=$(emit_gpu_classes)
  [ -n "$gpu_classes" ] || {
    printf 'fatal: unable to auto-detect a supported GPU class\n' >&2
    exit 1
  }

  printf '%s\n' "arch/${arch}"
  printf '%s\n' "cpu/${cpu}"
  printf '%s\n' "$gpu_classes"
  printf '%s\n' "disk/${disk}"
}

report() {
  auto_classes=$(emit_classes) || return "$?"

  printf '\n=== d-i hardware detection ===\n\n'
  printf '[ARCH]\n'
  line raw "$(arch_raw)"
  line debian "$(arch_class 2>/dev/null || printf unknown)"

  printf '\n[CPU]\n'
  line class "$(cpu_class 2>/dev/null || printf unknown)"
  line model "$(cpu_model)"
  line "is Intel" "$(yn cpu_intel)"
  line "is AMD" "$(yn cpu_amd)"

  printf '\n[GPU]\n'
  line "Intel GPU" "$(yn pci_has_display_vendor 0x8086)"
  line "AMD Radeon GPU" "$(yn pci_has_display_vendor 0x1002)"
  line "NVIDIA GPU" "$(yn pci_has_display_vendor 0x10de)"
  printf 'GPU devices:\n'
  list_gpus

  printf '\n[DISK]\n'
  line "VM type" "$(vm_type)"
  line "NVMe disk" "$(yn disk_nvme)"
  line "NVMe PCI controller" "$(yn disk_nvme_controller)"
  line "mmcblk" "$(yn disk_mmcblk)"
  line class "$(disk_class 2>/dev/null || printf unknown)"
  printf 'Detected disks:\n'
  list_disks

  printf '\n[VM]\n'
  line type "$(vm_type)"
  line "is VM" "$(yn is_vm)"
  line "hypervisor flag" "$(yn cpu_has_hypervisor_flag)"

  printf '\n[BOOT]\n'
  line mode "$(boot_mode)"

  printf '\n[AUTO CLASSES]\n'
  printf '%s\n' "$auto_classes" | sed 's/^/  /'
  printf '\n=== end ===\n\n'
}

case "${1:-report}" in
  classes) emit_classes ;;
  report|--report) report ;;
  *)
    printf 'usage: %s [classes|report]\n' "${0##*/}" >&2
    exit 2
    ;;
esac
