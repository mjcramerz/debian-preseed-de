#!/bin/sh
# Shared F2FS-family partman early hook.
set -eu

LOG=/tmp/installer.log
HOOK_FAMILY=${HOOK_FAMILY:-f2fs}

fatal() {
  installer_fatal "$@"
}

ensure_partition_tooling() {
  hook_ensure_partition_tooling
}

ensure_f2fs_tooling() {
  hook_ensure_installer_udeb f2fs-tools-udeb
  hook_ensure_installer_command mkfs.f2fs f2fs-tools-udeb
  hook_ensure_installer_command mkfs.ext4 e2fsprogs-udeb
  hook_ensure_installer_command mkfs.fat dosfstools-udeb
}

f2fs_kernel_is_available() {
  [ -r /proc/filesystems ] && grep -qw f2fs /proc/filesystems
}

ensure_f2fs_kernel_support() {
  case "$(udpkg --print-os)" in
    linux) ;;
    *) fatal "F2FS installer support requires a Linux Debian Installer runtime" ;;
  esac

  mkdir -p /var/lib/partman
  rm -f /var/lib/partman/f2fs

  if f2fs_kernel_is_available; then
    : >/var/lib/partman/f2fs
    installer_info "F2FS kernel support is built into the Debian Installer kernel"
    return 0
  fi

  if command -v modprobe >/dev/null 2>&1 &&
     modprobe f2fs >/dev/null 2>&1 &&
     f2fs_kernel_is_available; then
    : >/var/lib/partman/f2fs
    installer_info "loaded preinstalled Debian Installer F2FS kernel module"
    return 0
  fi

  kernel_release=$(uname -r 2>/dev/null || true)
  module_udeb_installed=false
  if [ -n "$kernel_release" ]; then
    module_udeb="f2fs-modules-${kernel_release}-di"
    installer_info "installing Debian Installer F2FS kernel udeb ${module_udeb}"
    if hook_anna_install_optional "$module_udeb"; then
      module_udeb_installed=true
    fi
  fi

  installer_info "installing Debian Installer virtual F2FS kernel udeb f2fs-modules"
  if hook_anna_install_optional f2fs-modules; then
    module_udeb_installed=true
  fi

  [ "$module_udeb_installed" = true ] || \
    fatal "unable to install Debian Installer F2FS kernel modules for ${kernel_release:-unknown kernel}"
  command -v depmod >/dev/null 2>&1 || \
    fatal "depmod is unavailable after installing Debian Installer F2FS kernel modules"
  depmod -a >/dev/null 2>&1 || \
    fatal "depmod failed after installing Debian Installer F2FS kernel modules"
  command -v modprobe >/dev/null 2>&1 || \
    fatal "modprobe is unavailable after installing Debian Installer F2FS kernel modules"
  modprobe f2fs >/dev/null 2>&1 || \
    fatal "unable to load the Debian Installer F2FS kernel module"
  f2fs_kernel_is_available || \
    fatal "Debian Installer still does not advertise F2FS after loading its kernel module"

  : >/var/lib/partman/f2fs
  installer_info "loaded Debian Installer F2FS kernel support for ${kernel_release:-current kernel}"
}

ensure_partman_state_dir() {
  mkdir -p /var/lib/partman
  : >/var/lib/partman/lvm
  : >/var/lib/partman/md
}

append_unique_line() {
  target_file=$1
  target_line=$2

  if [ -f "$target_file" ] && grep -qxF "$target_line" "$target_file"; then
    return 0
  fi

  printf '%s\n' "$target_line" >>"$target_file"
}

install_partman_f2fs_backend() {
  backend_tmp_dir="${TMP_ENV_DIR}/partman-f2fs-backend"

  install -d -m 0755 \
    /lib/partman/valid_filesystems \
    /lib/partman/mountoptions \
    /lib/partman/mount.d \
    /lib/partman/fstab.d \
    /lib/partman/init.d \
    /lib/partman/check.d \
    /lib/partman/commit.d \
    "$backend_tmp_dir"

  fetch_hook "hooks/installer/partman/f2fs-backend/valid_filesystems/f2fs" "$backend_tmp_dir/valid_filesystems.f2fs"
  fetch_hook "hooks/installer/partman/f2fs-backend/mountoptions/f2fs" "$backend_tmp_dir/mountoptions.f2fs"
  fetch_hook "hooks/installer/partman/f2fs-backend/mount.d/f2fs" "$backend_tmp_dir/mount.d.f2fs"
  fetch_hook "hooks/installer/partman/f2fs-backend/fstab.d/f2fs" "$backend_tmp_dir/fstab.d.f2fs"
  fetch_hook "hooks/installer/partman/f2fs-backend/init.d/kernelmodules_f2fs" "$backend_tmp_dir/init.d.kernelmodules_f2fs"
  fetch_hook "hooks/installer/partman/f2fs-backend/check.d/nomountpoint_f2fs" "$backend_tmp_dir/check.d.nomountpoint_f2fs"
  fetch_hook "hooks/installer/partman/f2fs-backend/commit.d/format_f2fs" "$backend_tmp_dir/commit.d.format_f2fs"

  install -m 0755 "$backend_tmp_dir/valid_filesystems.f2fs" /lib/partman/valid_filesystems/f2fs
  install -m 0644 "$backend_tmp_dir/mountoptions.f2fs" /lib/partman/mountoptions/f2fs
  install -m 0755 "$backend_tmp_dir/mount.d.f2fs" /lib/partman/mount.d/f2fs
  install -m 0755 "$backend_tmp_dir/fstab.d.f2fs" /lib/partman/fstab.d/f2fs
  install -m 0755 "$backend_tmp_dir/init.d.kernelmodules_f2fs" /lib/partman/init.d/kernelmodules_f2fs
  install -m 0755 "$backend_tmp_dir/check.d.nomountpoint_f2fs" /lib/partman/check.d/nomountpoint_f2fs
  install -m 0755 "$backend_tmp_dir/commit.d.format_f2fs" /lib/partman/commit.d/format_f2fs

  append_unique_line /lib/partman/valid_filesystems/_numbers '07 f2fs'
  append_unique_line /lib/partman/mount.d/_numbers '71 f2fs'
  append_unique_line /lib/partman/init.d/_numbers '03 kernelmodules_f2fs'
  append_unique_line /lib/partman/check.d/_numbers '09 nomountpoint_f2fs'
  append_unique_line /lib/partman/commit.d/_numbers '50 format_f2fs'

  installer_info "installed partman f2fs backend hooks"
}

device_has_any_type() {
  dev=$1
  shift

  [ -b "$dev" ] || return 1
  actual_type=$(runtime_probe_filesystem_type "$dev" 2>/dev/null || true)
  [ -n "$actual_type" ] || return 1

  for expected in "$@"; do
    [ "$actual_type" = "$expected" ] && return 0
  done

  return 1
}

validate_gpt_esp_type() {
  dev=$1
  esp_guid=$(runtime_gpt_esp_type_guid)

  [ -b "$dev" ] || fatal "existing EFI partition is missing: ${dev}"
  part_type=$(runtime_probe_gpt_part_type "$dev" 2>/dev/null || true)
  if [ -z "$part_type" ]; then
    installer_warn "unable to determine GPT partition type for ${dev}; continuing after vfat ESP filesystem validation"
    return 0
  fi

  runtime_gpt_part_type_is_esp "$part_type" || \
    fatal "expected ${dev} to have GPT ESP type ${esp_guid}, detected '${part_type}'"
}

install_target_free_option() {
  option_dir=/lib/partman/automatically_partition/installer_target_free
  install -d -m 0755 "$option_dir"

  cat >"$option_dir/choices" <<'EOF'
#!/bin/sh
. /lib/partman/lib/base.sh

[ -r /tmp/install-env/runtime.env ] || exit 0
# shellcheck disable=SC1091
. /tmp/install-env/runtime.env

[ -n "${DEV_INSTALL_DISK:-}" ] || exit 0
[ -n "${DEV_PART_PREFIX:-}" ] || exit 0
[ -n "${RUNTIME_DEBIAN_START_SLOT:-}" ] || exit 0

partition_slot_from_path() {
  path=$1
  case "$path" in
    "${DEV_PART_PREFIX}"[0-9]*)
      slot=${path#"$DEV_PART_PREFIX"}
      case "$slot" in
        ''|*[!0-9]*) return 1 ;;
      esac
      printf '%s\n' "$slot"
      return 0
      ;;
  esac
  return 1
}

mypart=
mysize=0
reinstall_part=
for dev in $DEVICES/*; do
  [ -d "$dev" ] || continue
  [ -r "$dev/device" ] || continue
  device_path=$(cat "$dev/device" 2>/dev/null || true)
  [ "$device_path" = "$DEV_INSTALL_DISK" ] || continue

  cd "$dev" || exit 0
  open_dialog PARTITIONS
  while { read_line num id size type fs path name; [ "$id" ]; }; do
    if [ "$fs" = free ] && [ "$type" != unusable ] && ! longint_le "$size" "$mysize"; then
      mysize=$size
      mypart=$dev//$id
    fi
    slot=$(partition_slot_from_path "$path" 2>/dev/null || true)
    if [ -n "$slot" ] && [ "$slot" -ge "$RUNTIME_DEBIAN_START_SLOT" ]; then
      reinstall_part=$dev//$id
    fi
  done
  close_dialog
done

if [ "$reinstall_part" ]; then
  printf '%s\tRecreate Debian-owned partition range on %s\n' "$reinstall_part" "$DEV_INSTALL_DISK"
elif [ "$mypart" ]; then
  printf '%s\tUse largest free space on %s\n' "$mypart" "$DEV_INSTALL_DISK"
fi
EOF

  cat >"$option_dir/do_option" <<'EOF'
#!/bin/sh
. /lib/partman/lib/base.sh

dev=${1%//*}
id=${1#*//}

[ -r /tmp/install-env/runtime.env ] || exit 1
# shellcheck disable=SC1091
. /tmp/install-env/runtime.env

partition_slot_from_path() {
  path=$1
  case "$path" in
    "${DEV_PART_PREFIX}"[0-9]*)
      slot=${path#"$DEV_PART_PREFIX"}
      case "$slot" in
        ''|*[!0-9]*) return 1 ;;
      esac
      printf '%s\n' "$slot"
      return 0
      ;;
  esac
  return 1
}

partition_id_is_debian_owned() {
  cd "$dev" || return 1
  open_dialog PARTITIONS
  while { read_line num part_id size type fs path name; [ "$part_id" ]; }; do
    [ "$part_id" = "$id" ] || continue
    slot=$(partition_slot_from_path "$path" 2>/dev/null || true)
    if [ -n "$slot" ] && [ "$slot" -ge "$RUNTIME_DEBIAN_START_SLOT" ]; then
      close_dialog
      return 0
    fi
  done
  close_dialog
  return 1
}

largest_free_partition_id() {
  myid=
  mysize=0

  cd "$dev" || return 1
  open_dialog PARTITIONS
  while { read_line num part_id size type fs path name; [ "$part_id" ]; }; do
    if [ "$fs" = free ] && [ "$type" != unusable ] && ! longint_le "$size" "$mysize"; then
      mysize=$size
      myid=$part_id
    fi
  done
  close_dialog

  [ -n "$myid" ] || return 1
  printf '%s\n' "$myid"
}

delete_debian_owned_partitions() {
  delete_list=/tmp/install-delete-partitions.$$

  cd "$dev" || return 1
  : >"$delete_list"
  open_dialog PARTITIONS
  while { read_line num part_id size type fs path name; [ "$part_id" ]; }; do
    slot=$(partition_slot_from_path "$path" 2>/dev/null || true)
    [ -n "$slot" ] || continue
    [ "$slot" -ge "$RUNTIME_DEBIAN_START_SLOT" ] || continue
    printf '%s %s %s\n' "$slot" "$part_id" "$path" >>"$delete_list"
  done
  close_dialog

  if [ -s "$delete_list" ]; then
    if ! sort -rn "$delete_list" | while read -r slot part_id part_path; do
      [ -n "$part_id" ] || continue
      [ -n "$part_path" ] || exit 1
      if awk -v wanted_path="$part_path" '$1 == wanted_path { found = 1 } END { exit !found }' /proc/mounts; then
        umount "$part_path" || {
          echo "[install-target-free] unable to unmount Debian-owned slot ${slot} at ${part_path}" >&2
          exit 1
        }
      fi
      part_discarded=false
      if command -v blkdiscard >/dev/null 2>&1 &&
         blkdiscard -f "$part_path" >/dev/null 2>&1; then
        part_discarded=true
      fi
      if [ "$part_discarded" != true ]; then
        if command -v wipefs >/dev/null 2>&1; then
          wipefs -a -f "$part_path" >/dev/null || {
            echo "[install-target-free] unable to clear Debian-owned slot ${slot} at ${part_path}" >&2
            exit 1
          }
        elif [ "${wipefs_unavailable_warned:-false}" != true ]; then
          echo "[install-target-free] wipefs is unavailable in Debian Installer; continuing with validated partman deletion" >&2
          wipefs_unavailable_warned=true
        fi
      fi
      open_dialog DELETE_PARTITION "$part_id"
      close_dialog
      echo "[install-target-free] cleared and removed Debian-owned slot ${slot} on ${DEV_INSTALL_DISK}" >&2
    done; then
      rm -f "$delete_list"
      return 1
    fi
    if command -v update_all >/dev/null 2>&1; then
      update_all
    fi
  fi

  rm -f "$delete_list"
}

mark_existing_esp_for_partman() {
  cd "$dev" || return 1
  open_dialog PARTITIONS
  while { read_line num part_id size type fs path name; [ "$part_id" ]; }; do
    [ "$path" = "$DEV_PART_EFI" ] || continue
    close_dialog
    mkdir -p "$part_id"
    printf '%s\n' efi >"$part_id/method"
    rm -f "$part_id/format"
    echo "[install-target-free] marked existing ESP ${DEV_PART_EFI} as method efi" >&2
    return 0
  done
  close_dialog

  echo "[install-target-free] unable to find existing ESP ${DEV_PART_EFI} in partman state" >&2
  return 1
}

if partition_id_is_debian_owned; then
  delete_debian_owned_partitions || exit 1
  id=$(largest_free_partition_id) || {
    echo "[install-target-free] no usable free space after deleting Debian-owned partitions on ${DEV_INSTALL_DISK}" >&2
    exit 1
  }
fi

autopartition "$dev" "$id"
code=$?
if [ "$code" -eq 0 ]; then
  mark_existing_esp_for_partman || code=1
fi
if [ "$code" -eq 255 ]; then
  code=99
fi

exit "$code"
EOF

  chmod 0755 "$option_dir/choices" "$option_dir/do_option"
  installer_info "installed target-disk free-space partman option for ${DEV_INSTALL_DISK}"
}

RUNTIME_DIR=${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}
BOOTSTRAP_LIB=${INSTALLER_BOOTSTRAP_LIB:-${RUNTIME_DIR}/bootstrap/bootstrap.sh}
if [ ! -s "$BOOTSTRAP_LIB" ]; then
  SELF_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
  BOOTSTRAP_LIB="${SELF_DIR}/../../../../scripts/common/bootstrap.sh"
fi
[ -s "$BOOTSTRAP_LIB" ] || fatal "installer bootstrap library is unavailable: ${BOOTSTRAP_LIB}"
# shellcheck disable=SC1090,SC1091
. "$BOOTSTRAP_LIB"
bootstrap_source_common_lib "${1:-}"
installer_init_log_file "$LOG" "" "${HOOK_FAMILY} partman early hook" partman-early partman_start
trap 'installer_finalize_log "$?"' EXIT
installer_load_context_if_present || true

SEED_BASE=$(installer_seed_base "${1:-}")
installer_persist_seed_source "$SEED_BASE"
HOST_PROFILE=$(installer_resolve_host_profile "${2:-}")

LAYOUT_HOOK=/lib/partman/finish.d/99-storage-layout
TMP_ENV_DIR=/tmp/install-env
RUNTIME_DIR=$(installer_runtime_dir)
STATE_DIR=$(installer_runtime_state_dir)
CACHE_DIR=$(installer_runtime_cache_dir)
RUNTIME_ENV_FILE="${STATE_DIR}/runtime.env"
RUNTIME_RECIPE_FILE="${CACHE_DIR}/expert_recipe"
RUNTIME_FRAGMENT_FILE="${STATE_DIR}/partman.answers.cfg"
install -d -m 0700 "$TMP_ENV_DIR" "$RUNTIME_DIR"
bootstrap_source_common_support_libs "$SEED_BASE" "$TMP_ENV_DIR" fetch hook
fetch_hook_file "$(installer_repo_join_var DIR_HOOKS_INSTALLER_PARTMAN early.sh)" "$TMP_ENV_DIR/partman-early-common.sh"
fetch_hook_file "$(installer_repo_join_var DIR_HOOKS_INSTALLER_PARTMAN_FINISH_D 99-storage-layout.sh)" "$TMP_ENV_DIR/partman-layout-common.sh"
# shellcheck disable=SC1090,SC1091
. "$TMP_ENV_DIR/partman-early-common.sh"

fetch_env() {
  fetch_env_file "$1" "$2"
}

fetch_hook() {
  fetch_hook_file "$1" "$2"
}

install_storage_layout_hook() {
  layout_hook_tmp_env_dir=$(installer_shell_quote "$TMP_ENV_DIR")
  layout_hook_family=$(installer_shell_quote "$HOOK_FAMILY")

  fetch_hook_file "$(installer_repo_join_var DIR_HOOKS_INSTALLER_PARTMAN_FINISH_D 99-storage-layout.sh)" "$TMP_ENV_DIR/partman-layout-common.sh"
  {
    printf '%s\n' '#!/bin/sh'
    printf '%s\n' 'set -eu'
    printf '%s\n' "IFS=\$(printf ' \t\nX'); IFS=\${IFS%X}"
    printf '%s\n' 'umask 022'
    printf 'TMP_ENV_DIR=%s\n' "$layout_hook_tmp_env_dir"
    printf 'HOOK_FAMILY=%s\n' "$layout_hook_family"
    printf '%s\n' 'LAYOUT_COMMON="${TMP_ENV_DIR}/partman-layout-common.sh"'
    printf '%s\n' '[ -r "$LAYOUT_COMMON" ] || {'
    printf '%s\n' "  printf '[partman-layout] ERROR: missing shared finish helper %s\n' \"\$LAYOUT_COMMON\" >&2"
    printf '%s\n' '  exit 1'
    printf '%s\n' '}'
    printf '%s\n' '# shellcheck disable=SC1090'
    printf '%s\n' '. "$LAYOUT_COMMON"'
    printf '%s\n' 'run_f2fs_storage_layout'
  } >"$LAYOUT_HOOK"
  chmod 0755 "$LAYOUT_HOOK"
}

install_crypto_skip_erase_hook() {
  skip_hook=/lib/partman/init.d/51crypto-skip-erase

  cat >"$skip_hook" <<'EOF'
#!/bin/sh
set -eu

[ -d /var/lib/partman/devices ] || exit 0

find /var/lib/partman/devices -mindepth 2 -maxdepth 2 -type d | while IFS= read -r part_dir; do
  [ -r "$part_dir/method" ] || continue
  method=$(cat "$part_dir/method" 2>/dev/null || true)
  [ "$method" = crypto ] || continue
  : >"$part_dir/skip_erase"
done
EOF
  chmod 0755 "$skip_hook"
  installer_info "installed partman crypto skip-erase hook"
}

installer_fetch_host_env "$SEED_BASE" "$HOST_PROFILE" "$TMP_ENV_DIR/host.env" 0600
installer_fetch_account_env "$SEED_BASE" "$TMP_ENV_DIR/account.env" 0600
fetch_hook "scripts/runtime/common.sh" "$TMP_ENV_DIR/runtime-common.sh"
fetch_hook "scripts/runtime/f2fs.sh" "$TMP_ENV_DIR/runtime.sh"
fetch_hook "scripts/runtime/account.sh" "$TMP_ENV_DIR/account.sh"
fetch_hook "scripts/partman/detect-disk.sh" "$TMP_ENV_DIR/detect-disk.sh"

# shellcheck disable=SC1090,SC1091
. "$TMP_ENV_DIR/host.env"
RUNTIME_COMMON_LIB="$TMP_ENV_DIR/runtime-common.sh"
export RUNTIME_COMMON_LIB
# shellcheck disable=SC1090,SC1091
. "$TMP_ENV_DIR/runtime.sh"
# shellcheck disable=SC1090,SC1091
. "$TMP_ENV_DIR/account.sh"
# shellcheck disable=SC1090,SC1091
. "$TMP_ENV_DIR/account.env"
runtime_apply_account_from_cmdline
runtime_write_effective_account_env "$TMP_ENV_DIR/account.env"

hook_resolve_install_disk "$TMP_ENV_DIR/detect-disk.sh" "$HOST_PROFILE"

ensure_partition_tooling
ensure_f2fs_tooling
ensure_f2fs_kernel_support
install_partman_f2fs_backend

if [ -r "$TMP_ENV_DIR/runtime.env" ]; then
  # shellcheck disable=SC1090,SC1091
  . "$TMP_ENV_DIR/runtime.env"
else
  runtime_apply_layout_from_cmdline
  if [ "${DUALBOOT_ENABLED:-false}" = "true" ]; then
    runtime_capture_dualboot_partition_sizes
  fi
  runtime_write_runtime_env "$RUNTIME_ENV_FILE"
  cp "$RUNTIME_ENV_FILE" "${TMP_ENV_DIR}/runtime.env"
  runtime_write_expert_recipe "$RUNTIME_RECIPE_FILE"
  runtime_write_partman_fragment "$RUNTIME_FRAGMENT_FILE" "$RUNTIME_RECIPE_FILE"
fi

[ -n "${DEV_INSTALL_DISK:-}" ] || fatal "DEV_INSTALL_DISK must be set"
[ -b "$DEV_INSTALL_DISK" ] || fatal "disk device not found: ${DEV_INSTALL_DISK}"

if [ "${DUALBOOT_ENABLED:-false}" = "true" ]; then
  PREP_STAMP="/tmp/install-partman-prepared-f2fs-$(echo "$DEV_INSTALL_DISK" | sed 's#[^A-Za-z0-9_.-]#_#g')-${RUNTIME_EFI_SLOT}-${RUNTIME_DEBIAN_START_SLOT}"

  [ "$RUNTIME_EFI_SLOT" -lt "$RUNTIME_DEBIAN_START_SLOT" ] || \
    fatal "dual-boot requires EFI slot ${RUNTIME_EFI_SLOT} to be below Debian start slot ${RUNTIME_DEBIAN_START_SLOT}"
  [ -b "$DEV_PART_EFI" ] || fatal "existing EFI partition is missing: ${DEV_PART_EFI}"
  partman_early_settle_block_devices "$DEV_INSTALL_DISK"
  disk_label=$(runtime_probe_partition_table_type "$DEV_INSTALL_DISK" 2>/dev/null || true)
  if [ -n "$disk_label" ]; then
    [ "$disk_label" = "gpt" ] || fatal "expected a GPT partition table on ${DEV_INSTALL_DISK}, got '${disk_label}'"
  fi
  esp_type=$(runtime_probe_filesystem_type "$DEV_PART_EFI" 2>/dev/null || true)
  device_has_any_type "$DEV_PART_EFI" "vfat" "fat" "fat12" "fat16" "fat32" || \
    fatal "expected ${DEV_PART_EFI} to be a reused ESP, detected filesystem '${esp_type:-unknown}'"
  validate_gpt_esp_type "$DEV_PART_EFI"
  ensure_partman_state_dir
  install_target_free_option
  if [ ! -f "$PREP_STAMP" ]; then
    if command -v umount >/dev/null 2>&1; then
      umount /media 2>/dev/null || true
      for dev in \
        "$DEV_PART_BOOT" \
        "$DEV_PART_ROOT" \
        "${DEV_PART_HOME:-}" \
        "${DEV_PART_POOL:-}" \
        "${DEV_PART_VAR_LIB_SHSIGNED:-}" \
        "$DEV_PART_VAR_LOG_JOURNAL" \
        "$DEV_PART_RAW_SWAP"
      do
        [ -n "$dev" ] || continue
        [ -b "$dev" ] || continue
        if grep -q "^$dev " /proc/mounts; then
          umount "$dev" || installer_warn "umount $dev failed"
        fi
      done
    fi
    : >"$PREP_STAMP"
    installer_info "preserved EFI plus all slots before ${RUNTIME_DEBIAN_START_SLOT}; leaving Debian-owned slot changes to partman"
  fi
else
  if command -v umount >/dev/null 2>&1; then
    for dev in "${DEV_INSTALL_DISK}" "${DEV_INSTALL_DISK}"*; do
      [ -b "$dev" ] || continue
      if grep -q "^$dev " /proc/mounts; then
        umount "$dev" || true
      fi
    done
  fi

  partman_early_sanitize_install_disk "$DEV_INSTALL_DISK"
fi

if runtime_root_home_crypto_enabled; then
  install_crypto_skip_erase_hook
fi

install_storage_layout_hook
installer_info "partman layout hook installed"
