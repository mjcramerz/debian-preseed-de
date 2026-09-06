#!/bin/sh
# Shared late_command grub helpers. This file is sourced, not executed.

set_optional_path() {
  var_name=$1
  enabled=$2

  case "$var_name" in
    [A-Z_][A-Z0-9_]*) ;;
    *) installer_fatal "invalid optional path variable name: ${var_name}" ;;
  esac

  if [ "$enabled" = true ]; then
    quoted_value=$(shell_single_quote "$3")
    eval "$var_name=$quoted_value"
  else
    eval "$var_name="
  fi
}

grub_profile_label() {
  case "$1" in
    "${BOOTPROFILE_DEFAULT}") printf 'Balanced\n' ;;
    "${BOOTPROFILE_HARDENED}") printf 'Hardened\n' ;;
    "${BOOTPROFILE_PERFORMANCE}") printf 'Performance\n' ;;
    *) printf '%s\n' "$1" ;;
  esac
}

grub_cmdline_has_token_prefix() (
  grub_cmdline=$1
  grub_prefix=$2

  set -f
  for grub_token in $grub_cmdline; do
    case "$grub_token" in
      "${grub_prefix}"*)
        return 0
        ;;
    esac
  done
  return 1
)

grub_cmdline_replace_token_prefix() (
  grub_cmdline=$1
  grub_prefix=$2
  replacement=$3
  normalized=

  set -f
  for grub_token in $grub_cmdline; do
    case "$grub_token" in
      "${grub_prefix}"*) continue ;;
    esac
    normalized="${normalized}${normalized:+ }${grub_token}"
  done
  normalized="${normalized}${normalized:+ }${replacement}"
  printf '%s\n' "$normalized"
)

grub_root_uses_btrfs() {
  grub_cmdline_has_token_prefix "${GRUB_ROOT_FLAGS:-}" "rootfstype=btrfs"
}

grub_root_uses_f2fs() {
  grub_cmdline_has_token_prefix "${GRUB_ROOT_FLAGS:-}" "rootfstype=f2fs"
}

apply_btrfs_root_initramfs_fsck_policy() {
  grub_root_uses_btrfs || return 0
  GRUB_INITRAMFS_FLAGS=$(
    grub_cmdline_replace_token_prefix \
      "${GRUB_INITRAMFS_FLAGS:-}" \
      "fsck.mode=" \
      "fsck.mode=skip"
  )
}

apply_f2fs_root_initramfs_fsck_policy() {
  grub_root_uses_f2fs || return 0
  GRUB_INITRAMFS_FLAGS=$(
    grub_cmdline_replace_token_prefix \
      "${GRUB_INITRAMFS_FLAGS:-}" \
      "fsck.mode=" \
      "fsck.mode=skip"
  )
}

apply_root_initramfs_fsck_policy() {
  apply_btrfs_root_initramfs_fsck_policy
  apply_f2fs_root_initramfs_fsck_policy
}

grub_os_prober_placeholder_map() {
  write_shell_config_var GRUB_DISABLE_OS_PROBER "${GRUB_OS_PROBER_DISABLED:-true}"
}

grub_display_placeholder_map() {
  write_shell_config_var GRUB_TERMINAL_INPUT "${GRUB_DISPLAY_TERMINAL_INPUT}"
  write_shell_config_var GRUB_TERMINAL_OUTPUT "${GRUB_DISPLAY_TERMINAL_OUTPUT}"
  write_shell_config_var GRUB_GFXMODE "${GRUB_DISPLAY_GFXMODE}"
  write_shell_config_var GRUB_GFXPAYLOAD_LINUX "${GRUB_DISPLAY_GFXPAYLOAD_LINUX}"
  write_shell_config_var GRUB_PRELOAD_MODULES "$(managed_grub_display_preload_modules)"
}

grub_shared_target_path() {
  installer_repo_join_var DIR_HOOKS_TARGET "$1"
}

render_target_grub_dropin() {
  template_name=$1
  target_path=$2

  render_target_asset "$(grub_shared_target_path "etc/default/grub.d/${template_name}")" "$target_path" 0644
}

render_target_grub_dropin_with_placeholder_map() {
  template_name=$1
  target_path=$2
  placeholder_map=$3

  render_target_asset_with_placeholder_map \
    "$(grub_shared_target_path "etc/default/grub.d/${template_name}")" \
    "$target_path" \
    0644 \
    "$placeholder_map"
}

sync_optional_target_grub_dropin() {
  flag_value=$1
  template_name=$2
  target_path=$3

  if [ -n "$flag_value" ]; then
    render_target_grub_dropin "$template_name" "$target_path"
  else
    remove_target_asset "$target_path"
  fi
}

path_mounted_fat_device_uuid() {
  path_value=$1
  best_source=
  best_mount=
  best_source_fstype=

  [ -n "$path_value" ] || return 1
  [ -e "$path_value" ] || return 1
  while IFS=' ' read -r mount_source mount_point _mount_fstype _mount_options _mount_rest || [ -n "${mount_source:-}" ]; do
    mount_point=$(printf '%s' "$mount_point" | sed 's/\\040/ /g')
    case "$path_value" in
      "$mount_point"|"$mount_point"/*)
        if [ "${#mount_point}" -gt "${#best_mount}" ]; then
          best_source=$mount_source
          best_mount=$mount_point
          best_source_fstype=$(blkid -s TYPE -o value "$mount_source" 2>/dev/null || true)
        fi
        ;;
    esac
  done </proc/mounts

  case "$best_source" in
    /dev/*) ;;
    *) return 1 ;;
  esac
  case "$best_source_fstype" in
    vfat|fat|fat12|fat16|fat32)
      blkid -s UUID -o value "$best_source" 2>/dev/null
      return 0
      ;;
  esac

  first_partition_source=$(installer_usb_first_partition "$best_source" 2>/dev/null || true)
  case "$first_partition_source" in
    /dev/*)
      case "$(blkid -s TYPE -o value "$first_partition_source" 2>/dev/null || true)" in
        vfat|fat|fat12|fat16|fat32)
          best_source=$first_partition_source
          ;;
      esac
      ;;
  esac

  blkid -s UUID -o value "$best_source" 2>/dev/null
}

installer_usb_first_partition() {
  device_path=$1
  efi_partition=
  parent_disk=$(lsblk -nrpo PKNAME -- "$device_path" 2>/dev/null | sed -n '/./{p;q;}')
  case "$parent_disk" in
    '') return 1 ;;
    /dev/*) ;;
    *) parent_disk="/dev/$parent_disk" ;;
  esac
  [ -b "$parent_disk" ] || return 1

  if command -v fdisk >/dev/null 2>&1; then
    efi_partition=$(
      LC_ALL=C fdisk -l -o Device,Type -- "$parent_disk" 2>/dev/null |
        awk '
          $1 ~ /^\/dev\// && index($0, "EFI System") {
            print $1
            exit
          }
        '
    )
    case "$efi_partition" in
      /dev/*)
        printf '%s\n' "$efi_partition"
        return 0
        ;;
    esac
  fi

  first_partition=$(
    lsblk -nrpo PATH,TYPE,PARTN -- "$parent_disk" 2>/dev/null |
      awk '$2 == "part" && $3 == "1" { print $1; exit }'
  )
  case "$first_partition" in
    /dev/*)
      printf '%s\n' "$first_partition"
      return 0
      ;;
  esac
  return 1
}

managed_grub_display_preload_modules() {
  seen_modules=
  normalized_modules=

  add_module() {
    module_name=$1
    [ -n "$module_name" ] || return 0
    case "$module_name" in
      *[!A-Za-z0-9_+-]*)
        installer_fatal "unsupported GRUB preload module name: ${module_name}"
        ;;
    esac
    case " $seen_modules " in
      *" $module_name "*) return 0 ;;
    esac
    seen_modules="${seen_modules}${seen_modules:+ }${module_name}"
    normalized_modules="${normalized_modules}${normalized_modules:+ }${module_name}"
  }

  case "${INSTALLER_GRUB_EFI_TARGET:-}" in
    *efi)
      for module_name in ${GRUB_DISPLAY_PRELOAD_MODULES:-}; do
        case "$module_name" in
          all_video|efi_uga|video_bochs|video_cirrus)
            continue
            ;;
        esac
        add_module "$module_name"
      done
      add_module efi_gop
      if [ "${GRUB_DISPLAY_TERMINAL_OUTPUT:-}" = gfxterm ]; then
        add_module gfxterm
      fi
      ;;
    *)
      for module_name in ${GRUB_DISPLAY_PRELOAD_MODULES:-}; do
        add_module "$module_name"
      done
      ;;
  esac

  printf '%s\n' "$normalized_modules"
}

normalize_target_grub_video_stack() {
  case "${INSTALLER_GRUB_EFI_TARGET:-}" in
    x86_64-efi|arm64-efi) ;;
    *) return 0 ;;
  esac

  # shellcheck disable=SC2016
  run_in_target "normalize GRUB EFI video module loading for signed boot" /bin/sh -c '
set -eu
header=/etc/grub.d/00_header
[ -r "$header" ] || exit 0
[ -w "$header" ] || exit 0

tmp=$(mktemp)
trap "rm -f \"$tmp\"" EXIT HUP INT TERM

sed \
  -e "s/^\([[:space:]]*\)insmod all_video$/\1insmod efi_gop/" \
  -e "s/^\([[:space:]]*\)insmod efi_uga$/\1: # managed: skip legacy EFI UGA video module/" \
  -e "s/^\([[:space:]]*\)insmod video_bochs$/\1: # managed: skip legacy bochs video module/" \
  -e "s/^\([[:space:]]*\)insmod video_cirrus$/\1: # managed: skip legacy cirrus video module/" \
  "$header" >"$tmp"

if ! cmp -s "$header" "$tmp"; then
  install -m 0755 "$tmp" "$header"
fi

grep -F -q "insmod efi_gop" "$header"
! grep -F -q "insmod all_video" "$header"
' sh
}

installer_rescue_usb_search_uuid() {
  if [ -n "${INSTALLER_RESCUE_USB_SEARCH_UUID:-}" ]; then
    printf '%s\n' "$INSTALLER_RESCUE_USB_SEARCH_UUID"
    return 0
  fi

  for candidate_path in \
    "${INSTALLER_SEED_FILE_BASE:-}" \
    "${SEED_FILE_BASE:-}" \
    "${INSTALLER_SEED_BASE:-}" \
    "${SEED_BASE:-}" \
    /media/usb \
    /cdrom
  do
    [ -n "$candidate_path" ] || continue
    case "$candidate_path" in
      /*) ;;
      *) continue ;;
    esac
    rescue_uuid=$(path_mounted_fat_device_uuid "$candidate_path" 2>/dev/null || true)
    [ -n "$rescue_uuid" ] || continue
    INSTALLER_RESCUE_USB_SEARCH_UUID=$rescue_uuid
    printf '%s\n' "$rescue_uuid"
    return 0
  done

  INSTALLER_RESCUE_USB_SEARCH_UUID=
  printf '\n'
}

secure_boot_config_placeholder_map() {
  write_shell_config_var SECURE_BOOT_MODE "$secure_boot_state_mode"
  write_shell_config_var SECURE_BOOT_STATE_MODE "$secure_boot_state_mode"
  write_shell_config_var SECURE_BOOT_STATE_MOUNTPOINT "${DIR_VAR_LIB_SHSIGNED}"
  write_shell_config_var SECURE_BOOT_STATE_DIR "${DIR_SECURE_BOOT_STATE}"
  write_shell_config_var SECURE_BOOT_LUKS_DEVICE "$secure_boot_luks_device"
  write_shell_config_var SECURE_BOOT_LUKS_NAME "$secure_boot_luks_name"
  write_shell_config_var SECURE_BOOT_LUKS_MAPPER "$secure_boot_luks_mapper"
  write_shell_config_var SECURE_BOOT_STATE_MOUNT_OPTS "$secure_boot_state_mount_opts"
  write_shell_config_var SECURE_BOOT_MOK_KEY "${FILE_SECURE_BOOT_MOK_KEY}"
  write_shell_config_var SECURE_BOOT_MOK_CERT_PEM "${FILE_SECURE_BOOT_MOK_CERT_PEM}"
  write_shell_config_var SECURE_BOOT_MOK_CERT_DER "${FILE_SECURE_BOOT_MOK_CERT_DER}"
  write_shell_config_var SECURE_BOOT_MOK_ENROLLMENT_DIR "${DIR_SECURE_BOOT_ENROLLMENT_ESP}"
  write_shell_config_var SECURE_BOOT_MOK_ENROLLMENT_CERT "${FILE_SECURE_BOOT_MOK_CERT_DER_ESP}"
  write_shell_config_var SECURE_BOOT_OPENSSL_CONFIG "${FILE_SECURE_BOOT_OPENSSL_CONFIG}"
  write_shell_config_var SECURE_BOOT_MOK_COMMON_NAME "${SECURE_BOOT_MOK_COMMON_NAME}"
  write_shell_config_var SECURE_BOOT_MOK_COUNTRY "${SECURE_BOOT_MOK_COUNTRY}"
  write_shell_config_var SECURE_BOOT_MOK_STATE "${SECURE_BOOT_MOK_STATE}"
  write_shell_config_var SECURE_BOOT_MOK_LOCALITY "${SECURE_BOOT_MOK_LOCALITY}"
  write_shell_config_var SECURE_BOOT_MOK_ORGANIZATION "${SECURE_BOOT_MOK_ORGANIZATION}"
  write_shell_config_var SECURE_BOOT_MOK_ORG_UNIT "${SECURE_BOOT_MOK_ORG_UNIT}"
  write_shell_config_var SECURE_BOOT_MOK_EMAIL "${SECURE_BOOT_MOK_EMAIL}"
  write_shell_config_var SECURE_BOOT_MOK_RSA_BITS "${SECURE_BOOT_MOK_RSA_BITS}"
  write_shell_config_var SECURE_BOOT_MOK_VALID_DAYS "${SECURE_BOOT_MOK_VALID_DAYS}"
  write_shell_config_var ACCOUNT_USERNAME "${ACCOUNT_USERNAME}"
  write_shell_config_var SECURE_BOOT_DKMS_CONF "${FILE_DKMS_FRAMEWORK_SECURE_BOOT}"
}

write_target_grub_dropins() {
  apply_root_initramfs_fsck_policy
  render_target_grub_dropin 05-bootprofiles.cfg.tmpl "${DIR_GRUB_DEFAULT}/05-bootprofiles.cfg"
  render_target_grub_dropin_with_placeholder_map 07-display.cfg.tmpl "${FILE_GRUB_DISPLAY_CFG}" grub_display_placeholder_map
  if [ "${DUALBOOT_ENABLED:-false}" = "true" ]; then
    GRUB_OS_PROBER_DISABLED=false
  else
    GRUB_OS_PROBER_DISABLED=true
  fi
  render_target_grub_dropin_with_placeholder_map 50-os-prober.cfg.tmpl "${DIR_GRUB_DEFAULT}/50-os-prober.cfg" grub_os_prober_placeholder_map
  unset GRUB_OS_PROBER_DISABLED
  render_target_grub_dropin 10-rootfs.cfg.tmpl "${DIR_GRUB_DEFAULT}/10-rootfs.cfg"
  render_target_grub_dropin 15-initramfs.cfg.tmpl "${DIR_GRUB_DEFAULT}/15-initramfs.cfg"
  sync_optional_target_grub_dropin "${GRUB_NVME_FLAGS:-}" 20-nvme.cfg.tmpl "${DIR_GRUB_DEFAULT}/20-nvme.cfg"
  sync_optional_target_grub_dropin "${GRUB_SYSTEMD_MASK_FLAGS:-}" 25-systemd-mask.cfg.tmpl "${DIR_GRUB_DEFAULT}/25-systemd-mask.cfg"
  render_target_grub_dropin 30-cgroup.cfg.tmpl "${DIR_GRUB_DEFAULT}/30-cgroup.cfg"
  render_target_grub_dropin 35-security-core.cfg.tmpl "${DIR_GRUB_DEFAULT}/35-security-core.cfg"
  sync_optional_target_grub_dropin "${GRUB_BLACKLIST_FLAGS:-}" 40-blacklist.cfg.tmpl "${DIR_GRUB_DEFAULT}/40-blacklist.cfg"
  sync_optional_target_grub_dropin "${GRUB_VFIO_FLAGS:-}" 42-vfio.cfg.tmpl "${DIR_GRUB_DEFAULT}/42-vfio.cfg"
  render_target_grub_dropin 45-memory-core.cfg.tmpl "${DIR_GRUB_DEFAULT}/45-memory-core.cfg"
  render_target_grub_dropin 60-hardening.cfg.tmpl "${DIR_GRUB_DEFAULT}/60-hardening.cfg"
  sync_optional_target_grub_dropin "${GRUB_ASPM_FLAGS:-}" 70-aspm.cfg.tmpl "${DIR_GRUB_DEFAULT}/70-aspm.cfg"
}

install_target_bootprofile_assets() {
  render_target_template "$TMP_ENV_DIR/bootprofile-apply.tmpl" "/target${FILE_BOOTPROFILE_APPLY}" 0755
  render_target_template "$TMP_ENV_DIR/bootprofile-apply.service.tmpl" "/target${FILE_BOOTPROFILE_SERVICE}" 0644

  install -d -m 0755 "/target${DIR_SYSTEMD_SYSTEM}/sysinit.target.wants"
  ln -sf "../$(basename "${FILE_BOOTPROFILE_SERVICE}")" \
    "/target${DIR_SYSTEMD_SYSTEM}/sysinit.target.wants/$(basename "${FILE_BOOTPROFILE_SERVICE}")"
}


set_target_grub_default_entry() {
  # shellcheck disable=SC2016
  run_in_target "set GRUB defaults in /etc/default/grub" /bin/sh -c '
set -eu
file=/etc/default/grub
grub_default=$1
tmp=$(mktemp)
trap "rm -f \"$tmp\"" EXIT HUP INT TERM

if [ -f "$file" ]; then
  default_updated=0
  timeout_style_updated=0
  timeout_updated=0
  recordfail_timeout_updated=0
  disable_recovery_updated=0
  disable_submenu_updated=0
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      GRUB_DEFAULT=*)
        [ "$default_updated" -eq 0 ] && printf 'GRUB_DEFAULT="%s"\n' "$grub_default"
        default_updated=1
        continue
        ;;
      GRUB_TIMEOUT_STYLE=*)
        [ "$timeout_style_updated" -eq 0 ] && printf 'GRUB_TIMEOUT_STYLE=menu\n'
        timeout_style_updated=1
        continue
        ;;
      GRUB_TIMEOUT=*)
        [ "$timeout_updated" -eq 0 ] && printf 'GRUB_TIMEOUT=-1\n'
        timeout_updated=1
        continue
        ;;
      GRUB_RECORDFAIL_TIMEOUT=*)
        [ "$recordfail_timeout_updated" -eq 0 ] && printf 'GRUB_RECORDFAIL_TIMEOUT=-1\n'
        recordfail_timeout_updated=1
        continue
        ;;
      GRUB_DISABLE_RECOVERY=*)
        [ "$disable_recovery_updated" -eq 0 ] && printf 'GRUB_DISABLE_RECOVERY=true\n'
        disable_recovery_updated=1
        continue
        ;;
      GRUB_DISABLE_SUBMENU=*)
        [ "$disable_submenu_updated" -eq 0 ] && printf 'GRUB_DISABLE_SUBMENU=y\n'
        disable_submenu_updated=1
        continue
        ;;
    esac
    printf '%s\n' "$line"
  done <"$file" >"$tmp"
  [ "$default_updated" -eq 1 ] || printf 'GRUB_DEFAULT="%s"\n' "$grub_default" >>"$tmp"
  [ "$timeout_style_updated" -eq 1 ] || printf 'GRUB_TIMEOUT_STYLE=menu\n' >>"$tmp"
  [ "$timeout_updated" -eq 1 ] || printf 'GRUB_TIMEOUT=-1\n' >>"$tmp"
  [ "$recordfail_timeout_updated" -eq 1 ] || printf 'GRUB_RECORDFAIL_TIMEOUT=-1\n' >>"$tmp"
  [ "$disable_recovery_updated" -eq 1 ] || printf 'GRUB_DISABLE_RECOVERY=true\n' >>"$tmp"
  [ "$disable_submenu_updated" -eq 1 ] || printf 'GRUB_DISABLE_SUBMENU=y\n' >>"$tmp"
else
  {
    printf "GRUB_DEFAULT=\"%s\"\n" "$grub_default"
    printf "GRUB_TIMEOUT_STYLE=menu\n"
    printf "GRUB_TIMEOUT=-1\n"
    printf "GRUB_RECORDFAIL_TIMEOUT=-1\n"
    printf "GRUB_DISABLE_RECOVERY=true\n"
    printf "GRUB_DISABLE_SUBMENU=y\n"
  } >"$tmp"
fi

install -m 0644 "$tmp" "$file"
' sh "${GRUB_DEFAULT_ENTRY}"
}

disable_stock_kernel_menu() {
  target_grub_dir="/target${DIR_GRUB_SCRIPTS}"
  [ -d "$target_grub_dir" ] || return 0

  for path in "$target_grub_dir"/*; do
    [ -e "$path" ] || continue
    script_name=${path##*/}
    case "$script_name" in
      00_header|40_custom|README)
        continue
        ;;
      30_os-prober)
        [ "${DUALBOOT_ENABLED:-false}" = "true" ] && continue
        ;;
    esac
    if [ -f "$path" ] && [ -x "$path" ]; then
      chmod 0644 "$path"
    fi
  done

  if [ -e "${target_grub_dir}/40_custom" ] && [ ! -x "${target_grub_dir}/40_custom" ]; then
    installer_fatal "managed GRUB 40_custom generator is not executable"
  fi
  for script_name in 05_debian_theme 10_linux 20_linux_xen 25_bli 30_os-prober 30_uefi-firmware 41_custom 41_snapshots-btrfs; do
    if [ "$script_name" = 30_os-prober ] && [ "${DUALBOOT_ENABLED:-false}" = "true" ]; then
      continue
    fi
    if [ -e "${target_grub_dir}/${script_name}" ] && [ -x "${target_grub_dir}/${script_name}" ]; then
      installer_fatal "unmanaged GRUB generator is still executable: ${DIR_GRUB_SCRIPTS}/${script_name}"
    fi
  done
}

target_efivars_are_available() {
  test_in_target /bin/sh -c '
set -eu
[ -d /sys/firmware/efi/efivars ]
grep -qs " /sys/firmware/efi/efivars " /proc/mounts ||
  grep -qs " /target/sys/firmware/efi/efivars " /proc/mounts
' sh
}

ensure_installer_secure_boot_install_tool() {
  if [ "${INSTALLER_SECURE_BOOT_BRIDGE_READY:-0}" = 1 ]; then
    return 0
  fi

  INSTALLER_SECURE_BOOT_TARGET_ROOT=/target
  INSTALLER_SECURE_BOOT_TARGET_TOOL=${FILE_SECURE_BOOT_TOOL}
  INSTALLER_SECURE_BOOT_TARGET_CONFIG=${FILE_SECURE_BOOT_CONFIG}

  case "$INSTALLER_SECURE_BOOT_TARGET_ROOT" in
    /target) ;;
    /target/*) installer_fatal "refusing nested Secure Boot target root: $INSTALLER_SECURE_BOOT_TARGET_ROOT" ;;
    /*) ;;
    *) installer_fatal "Secure Boot target root must be absolute: ${INSTALLER_SECURE_BOOT_TARGET_ROOT:-unset}" ;;
  esac
  case "$INSTALLER_SECURE_BOOT_TARGET_TOOL" in
    /*) ;;
    *) installer_fatal "Secure Boot target tool path must be absolute: ${INSTALLER_SECURE_BOOT_TARGET_TOOL:-unset}" ;;
  esac
  case "$INSTALLER_SECURE_BOOT_TARGET_CONFIG" in
    /*) ;;
    *) installer_fatal "Secure Boot target config path must be absolute: ${INSTALLER_SECURE_BOOT_TARGET_CONFIG:-unset}" ;;
  esac

  [ -d "$INSTALLER_SECURE_BOOT_TARGET_ROOT" ] || installer_fatal "Secure Boot target root is missing: $INSTALLER_SECURE_BOOT_TARGET_ROOT"
  [ -x "${INSTALLER_SECURE_BOOT_TARGET_ROOT}${INSTALLER_SECURE_BOOT_TARGET_TOOL}" ] || \
    installer_fatal "Secure Boot target tool is not executable: ${INSTALLER_SECURE_BOOT_TARGET_ROOT}${INSTALLER_SECURE_BOOT_TARGET_TOOL}"
  [ -r "${INSTALLER_SECURE_BOOT_TARGET_ROOT}${INSTALLER_SECURE_BOOT_TARGET_CONFIG}" ] || \
    installer_fatal "Secure Boot target config is not readable: ${INSTALLER_SECURE_BOOT_TARGET_ROOT}${INSTALLER_SECURE_BOOT_TARGET_CONFIG}"
  [ -x "${INSTALLER_SECURE_BOOT_TARGET_ROOT}/bin/sh" ] || \
    installer_fatal "target POSIX shell is unavailable; base-installer must provide /bin/sh before Secure Boot preparation"
  if ! command -v in-target >/dev/null 2>&1 && ! command -v chroot >/dev/null 2>&1; then
    installer_fatal "neither in-target nor chroot is available for the Secure Boot installer bridge"
  fi

  INSTALLER_SECURE_BOOT_BRIDGE_READY=1
}

run_installer_secure_boot_install_tool() {
  secure_boot_delete_password=

  ensure_installer_secure_boot_install_tool
  if [ "${1:-}" = reset-moks ]; then
    secure_boot_delete_password=$(installer_cmdline_value primary_user 2>/dev/null || true)
    if [ -n "$secure_boot_delete_password" ]; then
      case "$secure_boot_delete_password" in
        *[![:print:]]*|*[[:space:]]*)
          installer_fatal "primary_user must be a single printable token before Secure Boot MOK deletion"
          ;;
      esac
    else
      case "${ACCOUNT_USERNAME:-}" in
        ''|*[![:print:]]*|*[[:space:]]*)
          installer_fatal "ACCOUNT_USERNAME must be a single printable token before Secure Boot MOK deletion"
          ;;
        *)
          secure_boot_delete_password=$ACCOUNT_USERNAME
          ;;
      esac
    fi
  fi

  if command -v chroot >/dev/null 2>&1; then
    if [ -n "$secure_boot_delete_password" ]; then
      env \
        SECURE_BOOT_HOST_MOUNT_PREFIX="$INSTALLER_SECURE_BOOT_TARGET_ROOT" \
        SECURE_BOOT_MOK_DELETE_PASSWORD="$secure_boot_delete_password" \
        chroot "$INSTALLER_SECURE_BOOT_TARGET_ROOT" "$INSTALLER_SECURE_BOOT_TARGET_TOOL" "$@"
      return
    fi

    env SECURE_BOOT_HOST_MOUNT_PREFIX="$INSTALLER_SECURE_BOOT_TARGET_ROOT" \
      chroot "$INSTALLER_SECURE_BOOT_TARGET_ROOT" "$INSTALLER_SECURE_BOOT_TARGET_TOOL" "$@"
    return
  fi

  if [ -n "$secure_boot_delete_password" ]; then
    in-target /usr/bin/env \
      SECURE_BOOT_HOST_MOUNT_PREFIX="$INSTALLER_SECURE_BOOT_TARGET_ROOT" \
      SECURE_BOOT_MOK_DELETE_PASSWORD="$secure_boot_delete_password" \
      "$INSTALLER_SECURE_BOOT_TARGET_TOOL" "$@"
    return
  fi

  in-target /usr/bin/env SECURE_BOOT_HOST_MOUNT_PREFIX="$INSTALLER_SECURE_BOOT_TARGET_ROOT" \
    "$INSTALLER_SECURE_BOOT_TARGET_TOOL" "$@"
}

reset_target_secure_boot_mok_state_attempt() {
  target_sys=/target/sys

  if [ ! -d /sys/firmware/efi/efivars ]; then
    installer_error "EFI variable access is unavailable in the installer; skipping Secure Boot MOK reset"
    return 1
  fi
  if [ ! -d /sys ]; then
    installer_error "installer /sys is unavailable before binding into target; skipping Secure Boot MOK reset"
    return 1
  fi

  install -d -m 0755 "$target_sys"
  if ! target_mount_source "$target_sys" >/dev/null 2>&1; then
    installer_info "binding installer /sys into ${target_sys} for Secure Boot MOK reset"
    if ! mount --rbind /sys "$target_sys"; then
      installer_error "failed to bind installer /sys into ${target_sys}; skipping Secure Boot MOK reset"
      return 1
    fi
  fi
  if ! mount --make-rslave "$target_sys"; then
    installer_error "failed to mark ${target_sys} as rslave after binding installer /sys; skipping Secure Boot MOK reset"
    return 1
  fi
  if ! target_efivars_are_available; then
    installer_error "target /sys/firmware/efi/efivars is unavailable after binding installer /sys into /target; skipping Secure Boot MOK reset"
    return 1
  fi
  if ! run_installer_secure_boot_install_tool reset-moks; then
    installer_error "failed to reset Secure Boot MOK state automatically"
    return 1
  fi

  return 0
}

installer_usb_efi_device_from_seed_context() {
  best_source=
  best_mount=
  best_source_fstype=

  for candidate_path in \
    "${INSTALLER_SEED_FILE_BASE:-}" \
    "${SEED_FILE_BASE:-}" \
    "${INSTALLER_SEED_BASE:-}" \
    "${SEED_BASE:-}" \
    /media/usb \
    /cdrom
  do
    [ -n "$candidate_path" ] || continue
    case "$candidate_path" in
      /*) ;;
      *) continue ;;
    esac
    while IFS=' ' read -r mount_source mount_point _mount_fstype _mount_options _mount_rest || [ -n "${mount_source:-}" ]; do
      mount_point=$(printf '%s' "$mount_point" | sed 's/\\040/ /g')
      case "$candidate_path" in
        "$mount_point"|"$mount_point"/*)
          case "$mount_source" in
            /dev/*) ;;
            *) continue ;;
          esac
          if [ "${#mount_point}" -gt "${#best_mount}" ]; then
            best_source=$mount_source
            best_mount=$mount_point
            best_source_fstype=$(blkid -s TYPE -o value "$mount_source" 2>/dev/null || true)
          fi
          ;;
      esac
    done </proc/mounts
  done

  case "$best_source" in
    /dev/*) ;;
    *) return 1 ;;
  esac
  case "$best_source_fstype" in
    vfat|fat|fat12|fat16|fat32)
      printf '%s\n' "$best_source"
      return 0
      ;;
  esac

  installer_usb_first_partition "$best_source"
}

installer_usb_mountpoint_for_device() {
  installer_usb_device=$1

  while IFS=' ' read -r mount_source mount_point _mount_fstype _mount_options _mount_rest || [ -n "${mount_source:-}" ]; do
    case "$mount_source" in
      /dev/*) ;;
      *) continue ;;
    esac
    if installer_same_device_path "$mount_source" "$installer_usb_device"; then
      printf '%s\n' "$(printf '%s' "$mount_point" | sed 's/\\040/ /g')"
      return 0
    fi
  done </proc/mounts

  return 1
}

installer_mountpoint_is_writable() {
  installer_mountpoint=$1
  installer_probe="${installer_mountpoint}/.sb-mok-write-test.$$"

  if : >"$installer_probe" 2>/dev/null; then
    rm -f "$installer_probe"
    return 0
  fi
  return 1
}

sync_target_secure_boot_bundle_to_installer_usb() {
  installer_usb_device=$(installer_usb_efi_device_from_seed_context 2>/dev/null || true)
  case "$installer_usb_device" in
    /dev/*) ;;
    *)
      warn "no installer USB EFI partition was detected for SB_MOK sync"
      return 0
      ;;
  esac

  installer_usb_fstype=$(blkid -s TYPE -o value "$installer_usb_device" 2>/dev/null || true)
  case "$installer_usb_fstype" in
    vfat|fat|fat12|fat16|fat32) ;;
    *)
      warn "installer USB EFI candidate is not a FAT filesystem: ${installer_usb_device} (${installer_usb_fstype:-unknown})"
      return 0
      ;;
  esac

  secure_boot_state_dir="/target${DIR_SECURE_BOOT_STATE}"
  [ -d "$secure_boot_state_dir" ] || installer_fatal "Secure Boot state directory is missing before SB_MOK sync: ${secure_boot_state_dir}"

  for required_file in MOK.priv MOK.pem MOK.der openssl.cnf; do
    [ -r "${secure_boot_state_dir}/${required_file}" ] || \
      installer_fatal "Secure Boot state file is missing before SB_MOK sync: ${secure_boot_state_dir}/${required_file}"
  done

  installer_usb_mountpoint=$(installer_usb_mountpoint_for_device "$installer_usb_device" || true)
  installer_usb_mount_ours=false
  if [ -n "$installer_usb_mountpoint" ]; then
    if ! installer_mountpoint_is_writable "$installer_usb_mountpoint"; then
      if ! mount -o remount,rw "$installer_usb_mountpoint" >/dev/null 2>&1 ||
         ! installer_mountpoint_is_writable "$installer_usb_mountpoint"
      then
        installer_fatal "installer USB EFI partition is mounted but not writable: ${installer_usb_mountpoint}"
      fi
    fi
  else
    installer_usb_mountpoint="${RUNTIME_DIR}/mnt/usb-efi"
    install -d -m 0700 "$installer_usb_mountpoint"
    if ! mount "$installer_usb_device" "$installer_usb_mountpoint" >/dev/null 2>&1 ||
       ! installer_mountpoint_is_writable "$installer_usb_mountpoint"
    then
      [ "$installer_usb_mount_ours" = false ] || umount "$installer_usb_mountpoint" >/dev/null 2>&1 || true
      installer_fatal "failed to mount writable installer USB EFI partition ${installer_usb_device} for SB_MOK sync"
    fi
    installer_usb_mount_ours=true
  fi

  installer_sb_mok_dir="${installer_usb_mountpoint}/SB_MOK"
  install -d -m 0700 "$installer_sb_mok_dir"
  cp -a "${secure_boot_state_dir}/." "$installer_sb_mok_dir/"
  chmod 0600 "${installer_sb_mok_dir}/MOK.priv" "${installer_sb_mok_dir}/openssl.cnf"
  chmod 0644 "${installer_sb_mok_dir}/MOK.pem" "${installer_sb_mok_dir}/MOK.der"

  if [ "$installer_usb_mount_ours" = true ]; then
    umount "$installer_usb_mountpoint" >/dev/null 2>&1 || installer_fatal "failed to unmount installer USB EFI partition after SB_MOK sync"
  fi
}

repair_target_secure_boot_removable_loader() {
  # shellcheck disable=SC2016
  run_in_target "ensure removable Secure Boot fallback loader uses shim" /bin/sh -c '
set -eu
esp_dir=${1%/}
shim_path=$2
removable_path=$3
shim_loader="${esp_dir}${shim_path}"
removable_loader="${esp_dir}${removable_path}"

[ -f "$shim_loader" ] || {
  printf "missing signed shim loader: %s\n" "$shim_loader" >&2
  exit 1
}
install -d -m 0755 "$(dirname "$removable_loader")"
if [ ! -f "$removable_loader" ] || ! cmp -s "$shim_loader" "$removable_loader"; then
  install -m 0644 "$shim_loader" "$removable_loader"
fi
cmp -s "$shim_loader" "$removable_loader" || {
  printf "removable Secure Boot loader does not match shim: %s\n" "$removable_loader" >&2
  exit 1
}
' sh \
    "${DIR_BOOT_EFI}" \
    "${INSTALLER_GRUB_SHIM_EFI_PATH}" \
    "${INSTALLER_GRUB_REMOVABLE_BOOT_EFI_PATH}"
}

repair_target_secure_boot_mok_manager_loader() {
  # shellcheck disable=SC2016
  run_in_target "ensure MokManager EFI loader is staged on the ESP" /bin/sh -c '
set -eu
esp_dir=${1%/}
mok_manager_path=$2
mok_manager_loader="${esp_dir}${mok_manager_path}"
mok_manager_name=$(basename "$mok_manager_path")

find_mok_manager_source() {
  for candidate in \
    "/usr/lib/shim/${mok_manager_name}.signed" \
    "/usr/lib/shim/${mok_manager_name}" \
    /usr/lib/shim/MokManager.efi.signed \
    /usr/lib/shim/MokManager.efi
  do
    [ -f "$candidate" ] || continue
    printf "%s\n" "$candidate"
    return 0
  done
  return 1
}

mok_manager_source=$(find_mok_manager_source || true)
[ -n "$mok_manager_source" ] || {
  printf "unable to locate MokManager payload for %s under /usr/lib/shim\n" "$mok_manager_name" >&2
  exit 1
}

install -d -m 0755 "$(dirname "$mok_manager_loader")"
if [ ! -f "$mok_manager_loader" ] || ! cmp -s "$mok_manager_source" "$mok_manager_loader"; then
  install -m 0644 "$mok_manager_source" "$mok_manager_loader"
fi
[ -f "$mok_manager_loader" ] || {
  printf "failed to stage MokManager EFI loader at %s\n" "$mok_manager_loader" >&2
  exit 1
}
' sh \
    "${DIR_BOOT_EFI}" \
    "${INSTALLER_GRUB_MOK_MANAGER_EFI_PATH}"
}

repair_target_secure_boot_nvram_entry() {
  # shellcheck disable=SC2016
  run_in_target "ensure firmware boot entry uses shim" /bin/sh -c '
set -eu
disk=$1
efi_part=$2
shim_path=$3
label=debian

find_shim_boot_entry() {
  loader_lower=$1
  efibootmgr -v | while IFS= read -r line; do
    lower_line=$(printf "%s\n" "$line" | tr "[:upper:]" "[:lower:]")
    case "$lower_line" in
      *"file(${loader_lower})"*)
        entry=$(printf "%s\n" "$line" | sed -n "s/^Boot\\([0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f]\\).*/\\1/p")
        [ -n "$entry" ] || continue
        printf "%s\n" "$entry"
        return 0
        ;;
    esac
  done
}

command -v efibootmgr >/dev/null 2>&1 || {
  printf "efibootmgr is unavailable; cannot force firmware boot through shim\n" >&2
  exit 1
}
[ -d /sys/firmware/efi/efivars ] || {
  printf "target efivars are unavailable; cannot force firmware boot through shim\n" >&2
  exit 1
}
grep -qs " /sys/firmware/efi/efivars " /proc/mounts || {
  printf "target efivars are not mounted; cannot force firmware boot through shim\n" >&2
  exit 1
}
[ -b "$disk" ] || {
  printf "install disk is missing inside target: %s\n" "$disk" >&2
  exit 1
}
[ -b "$efi_part" ] || {
  printf "EFI partition is missing inside target: %s\n" "$efi_part" >&2
  exit 1
}

part_num=$(lsblk -n -o PARTN -- "$efi_part" 2>/dev/null | sed -n '/./{p;q;}')
[ -n "$part_num" ] || {
  printf "unable to resolve EFI partition number for %s\n" "$efi_part" >&2
  exit 1
}
loader=$(printf "%s\n" "$shim_path" | sed "s#/#\\\\#g")
loader_lower=$(printf "%s\n" "$loader" | tr "[:upper:]" "[:lower:]")

entry_id=$(find_shim_boot_entry "$loader_lower" | head -n 1 || true)
if [ -z "$entry_id" ]; then
  efibootmgr --create --disk "$disk" --part "$part_num" --label "$label" --loader "$loader" >/dev/null
  entry_id=$(find_shim_boot_entry "$loader_lower" | head -n 1 || true)
fi
[ -n "$entry_id" ] || {
  printf "failed to create or find shim firmware boot entry for %s\n" "$loader" >&2
  exit 1
}

boot_order=$(efibootmgr | sed -n "s/^BootOrder:[[:space:]]*//p" | head -n 1)
entry_lower=$(printf "%s\n" "$entry_id" | tr "[:upper:]" "[:lower:]")
new_order=$entry_id
old_ifs=$IFS
IFS=,
for existing_entry in $boot_order; do
  existing_entry=$(printf "%s\n" "$existing_entry" | tr -d "[:space:]")
  [ -n "$existing_entry" ] || continue
  existing_lower=$(printf "%s\n" "$existing_entry" | tr "[:upper:]" "[:lower:]")
  [ "$existing_lower" = "$entry_lower" ] && continue
  new_order="${new_order},${existing_entry}"
done
IFS=$old_ifs
efibootmgr --bootorder "$new_order" >/dev/null
efibootmgr --bootnext "$entry_id" >/dev/null
efibootmgr | grep -E -i -q "^BootNext:[[:space:]]*${entry_id}$"
' sh \
    "${DEV_INSTALL_DISK}" \
    "${DEV_PART_EFI}" \
    "${INSTALLER_GRUB_SHIM_EFI_PATH}"
}

queue_target_grub_mok_enrollment_boot() {
  # shellcheck disable=SC2016
  run_in_target "queue one-shot GRUB boot into MokManager" /bin/sh -c '
set -eu
mok_entry_id=$1
mokmanager_path=$2
mok_enrollment_cert=$3
grub_cfg=/boot/grub/grub.cfg

command -v grub-editenv >/dev/null 2>&1 || {
  printf "grub-editenv is unavailable; cannot force first boot into MokManager\n" >&2
  exit 1
}
[ -r "$grub_cfg" ] || {
  printf "GRUB configuration is missing before MOK enrollment queue: %s\n" "$grub_cfg" >&2
  exit 1
}
grep -F -q -- "--id '${mok_entry_id}'" "$grub_cfg" || {
  printf "MOK enrollment GRUB entry is missing: %s\n" "$mok_entry_id" >&2
  exit 1
}
case "$mokmanager_path" in
  /EFI/*) ;;
  *)
    printf "MokManager EFI path is invalid: %s\n" "$mokmanager_path" >&2
    exit 1
    ;;
esac
[ -f "/boot/efi${mokmanager_path}" ] || {
  printf "MokManager EFI loader is missing: /boot/efi%s\n" "$mokmanager_path" >&2
  exit 1
}
[ -r "$mok_enrollment_cert" ] || {
  printf "MOK enrollment certificate is missing: %s\n" "$mok_enrollment_cert" >&2
  exit 1
}
[ -s /boot/grub/grubenv ] || {
  grub-editenv /boot/grub/grubenv create
}
grub-editenv /boot/grub/grubenv set "next_entry=${mok_entry_id}"
grub-editenv /boot/grub/grubenv list | grep -F -q "next_entry=${mok_entry_id}"
' sh \
    installer-mok-enrollment \
    "${INSTALLER_GRUB_MOK_MANAGER_EFI_PATH}" \
    "${FILE_SECURE_BOOT_MOK_CERT_DER_ESP}"
}

queue_target_grub_mok_enrollment_boot_for_reset() {
  ensure_target_grub_profile_mounts
  require_target_grub_installed
  queue_target_grub_mok_enrollment_boot
}

require_target_grub_installed() {
  # shellcheck disable=SC2016
  if ! test_in_target /bin/sh -c '
set -eu
packages=$1
test -x /usr/sbin/grub-install
[ -x /usr/sbin/update-grub ] || [ -x /usr/sbin/grub-mkconfig ]
test -x /usr/bin/grub-editenv
for pkg in $packages; do
  dpkg-query -W "$pkg" >/dev/null 2>&1
done
' sh "${INSTALLER_SECURE_BOOT_BOOT_CHAIN_PACKAGES}"; then
    installer_fatal "target Secure Boot GRUB and shim packages are not fully installed before profile installation"
  fi
}

ensure_target_grub_profile_mounts() {
  target_is_mounted || installer_fatal "/target is not mounted before GRUB profile installation"
  [ -n "${DEV_PART_BOOT:-}" ] || installer_fatal "DEV_PART_BOOT is unset before GRUB profile installation"
  [ -n "${DEV_PART_EFI:-}" ] || installer_fatal "DEV_PART_EFI is unset before GRUB profile installation"

  if ! target_mount_source "/target${DIR_BOOT}" >/dev/null 2>&1 &&
    target_mount_source "/target${DIR_BOOT_EFI}" >/dev/null 2>&1; then
    info "unmounting /boot/efi before restoring /boot for GRUB profile installation"
    if ! umount "/target${DIR_BOOT_EFI}"; then
      installer_fatal "failed to unmount /target${DIR_BOOT_EFI} before restoring /target${DIR_BOOT}"
    fi
  fi

  ensure_target_mount "${DEV_PART_BOOT}" "/target${DIR_BOOT}" ext4 "${MNT_BOOT_OPTS}" "/boot"
  ensure_target_mount "${DEV_PART_EFI}" "/target${DIR_BOOT_EFI}" vfat "${MNT_EFI_OPTS}" "/boot/efi"

  # shellcheck disable=SC2016
  test_in_target /bin/sh -c '
set -eu
grep -qs " /boot " /proc/mounts
grep -qs " /boot/efi " /proc/mounts
' || installer_fatal "target /boot and /boot/efi must be mounted before GRUB profile installation"
}

ensure_target_grubenv_ready() {
  require_target_grub_installed
  # shellcheck disable=SC2016
  run_in_target "ensure target grubenv exists for GRUB profile state" /bin/sh -c '
set -eu
command -v grub-editenv >/dev/null 2>&1 || {
  printf "grub-editenv is unavailable in target\n" >&2
  exit 1
}
install -d -m 0755 /boot/grub
[ -s /boot/grub/grubenv ] || grub-editenv /boot/grub/grubenv create
[ -s /boot/grub/grubenv ] || {
  printf "grubenv is missing after creation\n" >&2
  exit 1
}
' sh
}

ensure_target_bootable_kernel_pairs() {
  # shellcheck disable=SC2016
  run_in_target "ensure target bootable kernel and initrd pairs exist" /bin/sh -c '
set -eu
have_pairs() {
  for img in /boot/vmlinuz-*; do
    [ -e "$img" ] || continue
    ver=${img#/boot/vmlinuz-}
    [ -e "/boot/initrd.img-$ver" ] || continue
    return 0
  done
  return 1
}

have_pairs || {
  printf "no bootable kernel/initrd pairs exist under /boot\n" >&2
  exit 1
}
' sh
}

prepare_target_secure_boot_runtime() {
  if [ "${TARGET_SECURE_BOOT_RUNTIME_PREPARED:-0}" = 1 ]; then
    return 0
  fi
  run_installer_secure_boot_install_tool prepare
  TARGET_SECURE_BOOT_RUNTIME_PREPARED=1
}

secure_boot_packages_stage_stamp() {
  runtime_state_dir=$(installer_runtime_state_dir)
  printf '%s/secure-boot-packages.done\n' "$runtime_state_dir"
}

secure_boot_packages_stage_is_complete() {
  [ -f "$(secure_boot_packages_stage_stamp)" ]
}

mark_secure_boot_packages_stage_complete() {
  stamp_path=$(secure_boot_packages_stage_stamp)
  install -d -m 0700 "$(dirname "$stamp_path")"
  : >"$stamp_path"
  chmod 0600 "$stamp_path"
}

stage_target_secure_boot_runtime_assets() {
  ensure_target_secure_boot_state_mount
  write_target_secure_boot_payloads
  remove_target_secure_boot_crypttab_entry
  install_target_secure_boot_kernel_hooks
}

ensure_target_dualboot_os_prober_package() {
  [ "${DUALBOOT_ENABLED:-false}" = "true" ] || return 0

  if ! installer_word_list_contains "${INSTALLER_PKGSEL_INCLUDE:-}" os-prober; then
    INSTALLER_PKGSEL_INCLUDE="${INSTALLER_PKGSEL_INCLUDE:+${INSTALLER_PKGSEL_INCLUDE} }os-prober"
  fi

  if test_in_target test -x /usr/bin/os-prober; then
    return 0
  fi

  installer_warn "addon/dualboot selected but /usr/bin/os-prober is missing in target; repairing package state"
  prepare_target_volatile_dirs_for_apt
  run_in_target "refresh apt metadata before dualboot os-prober repair" \
    env DEBIAN_FRONTEND=noninteractive DEBCONF_NONINTERACTIVE_SEEN=true \
    apt-get \
      -o Acquire::Retries=5 \
      -o Acquire::http::Timeout=45 \
      -o Acquire::https::Timeout=45 \
      -o Binary::apt::APT::Keep-Downloaded-Packages=false \
      -o DPkg::Use-Pty=0 \
      update
  run_in_target "install dualboot os-prober package" \
    env DEBIAN_FRONTEND=noninteractive DEBCONF_NONINTERACTIVE_SEEN=true \
    apt-get \
      -o Acquire::Retries=5 \
      -o Acquire::http::Timeout=45 \
      -o Acquire::https::Timeout=45 \
      -o Binary::apt::APT::Keep-Downloaded-Packages=false \
      -o DPkg::Use-Pty=0 \
      -y install --no-install-recommends --no-install-suggests os-prober

  TARGET_BOOT_TOOL_STATE_LOADED=0
}

require_target_dualboot_os_prober_package() {
  [ "${DUALBOOT_ENABLED:-false}" = "true" ] || return 0
  ensure_target_dualboot_os_prober_package
  test_in_target test -x /usr/bin/os-prober || \
    installer_fatal "/usr/bin/os-prober is missing in target after repair; GRUB cannot probe other operating systems automatically"
}

resolve_target_grub_config_command() {
  if test_in_target test -x /usr/sbin/update-grub; then
    printf '%s\n' update-grub
    return 0
  fi
  if test_in_target test -x /usr/sbin/grub-mkconfig; then
    printf '%s\n' grub-mkconfig
    return 0
  fi
  return 1
}

run_target_grub_config_update() {
  grub_config_command=$(resolve_target_grub_config_command) || \
    installer_fatal "neither /usr/sbin/update-grub nor /usr/sbin/grub-mkconfig is available in target"

  if [ "${DUALBOOT_ENABLED:-false}" = "true" ]; then
    install_disk_path=$(readlink -f "$DEV_INSTALL_DISK" 2>/dev/null || true)
    [ -n "$install_disk_path" ] || \
      installer_fatal "unable to resolve the selected install disk before scoped dualboot os-prober: ${DEV_INSTALL_DISK:-unset}"
    install_disk_name=${install_disk_path##*/}
    case "$install_disk_name" in
      ''|*[!A-Za-z0-9._-]*)
        installer_fatal "invalid install disk basename for scoped dualboot os-prober run: ${install_disk_name:-unset}"
        ;;
    esac
    test_in_target test -x /usr/bin/unshare.installer-real || \
      installer_fatal "preserved real target unshare is unavailable for the scoped dualboot os-prober run"

    # os-prober scans every partition exposed below /sys/block. Run the final
    # dual-boot discovery in a private mount namespace and mask USB-backed
    # disks other than the selected install disk so removable installer or
    # utility media cannot stall the unattended installation.
    # shellcheck disable=SC2016
    run_in_target "update GRUB configuration with unrelated USB storage hidden from os-prober" \
      /usr/bin/unshare.installer-real --mount /bin/sh -eu -c '
mount --make-rprivate /
install_disk_name=$1
grub_config_command=$2
empty_sys_block=$(mktemp -d /tmp/os-prober-empty-sys-block.XXXXXX)
cleanup_scoped_os_prober() {
  rmdir "$empty_sys_block" 2>/dev/null || true
}
trap cleanup_scoped_os_prober EXIT HUP INT TERM

for sys_block in /sys/block/*; do
  [ -d "$sys_block" ] || continue
  block_name=${sys_block##*/}
  [ "$block_name" = "$install_disk_name" ] && continue
  device_path=$(readlink -f "$sys_block/device" 2>/dev/null || true)
  case "$device_path" in
    */usb*)
      mount --bind "$empty_sys_block" "$sys_block"
      printf "[late:grub] hidden USB-backed block device from os-prober: %s\n" \
        "$block_name" >&2
      ;;
  esac
done

case "$grub_config_command" in
  update-grub)
    /usr/sbin/update-grub
    ;;
  grub-mkconfig)
    /usr/sbin/grub-mkconfig -o /boot/grub/grub.cfg
    ;;
  *)
    printf "unsupported target GRUB config command: %s\n" "$grub_config_command" >&2
    exit 1
    ;;
esac
' sh "$install_disk_name" "$grub_config_command"
    return 0
  fi

  case "$grub_config_command" in
    update-grub)
      run_in_target "update GRUB configuration" /usr/sbin/update-grub
      ;;
    grub-mkconfig)
      run_in_target "generate GRUB configuration" /usr/sbin/grub-mkconfig -o /boot/grub/grub.cfg
      ;;
    *)
      installer_fatal "unsupported target GRUB config command: ${grub_config_command}"
      ;;
  esac
}

install_target_secure_boot_target_packages() {
  # shellcheck disable=SC2086
  set -- $INSTALLER_SECURE_BOOT_TARGET_PACKAGES
  [ "$#" -ge 1 ] || installer_fatal "selected Secure Boot target package set is empty"
  prepare_target_volatile_dirs_for_apt
  run_in_target "install selected Secure Boot target packages" \
    env DEBIAN_FRONTEND=noninteractive DEBCONF_NONINTERACTIVE_SEEN=true \
    apt-get \
      -o Acquire::Retries=5 \
      -o Acquire::http::Timeout=45 \
      -o Acquire::https::Timeout=45 \
      -o Binary::apt::APT::Keep-Downloaded-Packages=false \
      -o DPkg::Use-Pty=0 \
      -y install --no-install-recommends --no-install-suggests "$@"
}


reinstall_target_grub_boot_chain_packages() {
  # shellcheck disable=SC2086
  set -- $INSTALLER_SECURE_BOOT_BOOT_CHAIN_PACKAGES
  [ "$#" -ge 1 ] || installer_fatal "selected GRUB EFI boot chain package set is empty"
  prepare_target_volatile_dirs_for_apt
  run_in_target "reinstall selected GRUB EFI boot chain packages on the restored ESP" \
    env DEBIAN_FRONTEND=noninteractive DEBCONF_NONINTERACTIVE_SEEN=true \
    apt-get \
      -o Acquire::Retries=5 \
      -o Acquire::http::Timeout=45 \
      -o Acquire::https::Timeout=45 \
      -o Binary::apt::APT::Keep-Downloaded-Packages=false \
      -o DPkg::Use-Pty=0 \
      -y install --reinstall --no-install-recommends --no-install-suggests "$@"
}

installer_canonical_device_path() {
  readlink -f "$1" 2>/dev/null || printf '%s\n' "$1"
}

installer_same_device_path() {
  installer_left=$(installer_canonical_device_path "$1")
  installer_right=$(installer_canonical_device_path "$2")
  [ "$installer_left" = "$installer_right" ]
}

installer_device_fs_type() {
  command -v blkid >/dev/null 2>&1 || return 1
  blkid -s TYPE -o value "$1" 2>/dev/null || true
}

installer_device_fs_label() {
  command -v blkid >/dev/null 2>&1 || return 1
  blkid -s LABEL -o value "$1" 2>/dev/null || true
}

installer_udev_settle() {
  if command -v udevadm >/dev/null 2>&1; then
    udevadm settle || warn "udevadm settle failed while refreshing device state"
  fi
}

installer_wipe_block_device() {
  if command -v swapoff >/dev/null 2>&1; then
    swapoff "$1" >/dev/null 2>&1 || true
  fi
  if command -v wipefs >/dev/null 2>&1; then
    wipefs -a -f "$1" >/dev/null 2>&1 || true
  fi
}

installer_log_command_failure() {
  failure_prefix=$1
  failure_file=$2

  [ -s "$failure_file" ] || return 0
  sed "s/^/[${failure_prefix}] /" "$failure_file" >&2 || true
}

installer_ensure_ext4_filesystem() {
  dev=$1
  opts=$2
  label=$3

  ensure_installer_command_logged blkid util-linux-udeb
  ensure_installer_command_logged mkfs.ext4 e2fsprogs-udeb

  current_type=$(installer_device_fs_type "$dev")
  current_label=$(installer_device_fs_label "$dev")
  if [ "$current_type" = "ext4" ] && [ "$current_label" = "$label" ]; then
    return 0
  fi

  installer_wipe_block_device "$dev"
  mkfs_err=$(installer_runtime_temp_log_path secure-boot-mkfs-ext4.log)
  info "formatting Secure Boot state mapper ${dev} as ext4"
  # shellcheck disable=SC2086
  if ! mkfs.ext4 $opts "$dev" >"$mkfs_err" 2>&1; then
    installer_log_command_failure "mkfs.ext4" "$mkfs_err"
    rm -f "$mkfs_err"
    fatal "failed to format Secure Boot state mapper ${dev} as ext4"
  fi
  rm -f "$mkfs_err"
  installer_udev_settle
}

installer_find_open_luks_mapping_for_device() {
  installer_dev=$1

  command -v cryptsetup >/dev/null 2>&1 || return 1

  for installer_mapper_path in /dev/mapper/*; do
    [ -b "$installer_mapper_path" ] || continue
    installer_mapper_name=${installer_mapper_path##*/}
    installer_real_dev=$(cryptsetup status "$installer_mapper_name" 2>/dev/null |
      sed -n 's/^[[:space:]]*device:[[:space:]]*//p' | sed -n '1p')
    [ -n "$installer_real_dev" ] || continue
    if installer_same_device_path "$installer_dev" "$installer_real_dev"; then
      printf '%s\n' "$installer_mapper_path"
      return 0
    fi
  done

  return 1
}

installer_active_secure_boot_luks_mapper() {
  if [ -b "$LUKS_MAPPER_VAR_LIB_SHSIGNED" ]; then
    printf '%s\n' "$LUKS_MAPPER_VAR_LIB_SHSIGNED"
    return 0
  fi

  installer_find_open_luks_mapping_for_device "$DEV_PART_VAR_LIB_SHSIGNED"
}

open_luks_mapping_with_passphrase() {
  dev=$1
  mapper_name=$2
  passphrase=$3

  ensure_installer_command_logged cryptsetup cryptsetup-udeb
  if command -v modprobe >/dev/null 2>&1; then
    modprobe dm_mod >/dev/null 2>&1 || true
    modprobe dm_crypt >/dev/null 2>&1 || true
  fi

  ACTIVE_TARGET_SECURE_BOOT_MAPPER=$(installer_active_secure_boot_luks_mapper || true)
  if [ -n "$ACTIVE_TARGET_SECURE_BOOT_MAPPER" ]; then
    installer_ensure_ext4_filesystem "$ACTIVE_TARGET_SECURE_BOOT_MAPPER" "$MKFS_EXT4_VAR_LIB_SHSIGNED_OPTS" "$FS_LABEL_VAR_LIB_SHSIGNED"
    return 0
  fi

  if ! cryptsetup isLuks "$dev" >/dev/null 2>&1; then
    installer_wipe_block_device "$dev"
    luks_format_err=$(installer_runtime_temp_log_path secure-boot-luks-format.log)
    info "formatting Secure Boot state partition ${dev} as LUKS2"
    # shellcheck disable=SC2086
    if ! printf '%s' "$passphrase" | cryptsetup luksFormat --batch-mode --key-file - $CRYPTSETUP_LUKS_VAR_LIB_SHSIGNED_OPTS "$dev" >"$luks_format_err" 2>&1; then
      installer_log_command_failure "cryptsetup:luksFormat" "$luks_format_err"
      rm -f "$luks_format_err"
      fatal "failed to format Secure Boot state partition ${dev} as LUKS2"
    fi
    rm -f "$luks_format_err"
    installer_udev_settle
  fi

  luks_open_err=$(installer_runtime_temp_log_path secure-boot-luks-open.log)
  info "opening Secure Boot LUKS mapper ${mapper_name}"
  if ! printf '%s' "$passphrase" | cryptsetup luksOpen --batch-mode --key-file - "$dev" "$mapper_name" >"$luks_open_err" 2>&1; then
    installer_log_command_failure "cryptsetup:luksOpen" "$luks_open_err"
    rm -f "$luks_open_err"
    fatal "failed to open Secure Boot LUKS mapper ${mapper_name}"
  fi
  rm -f "$luks_open_err"
  installer_udev_settle
  ACTIVE_TARGET_SECURE_BOOT_MAPPER="$LUKS_MAPPER_VAR_LIB_SHSIGNED"
  installer_ensure_ext4_filesystem "$ACTIVE_TARGET_SECURE_BOOT_MAPPER" "$MKFS_EXT4_VAR_LIB_SHSIGNED_OPTS" "$FS_LABEL_VAR_LIB_SHSIGNED"
}

ensure_target_secure_boot_state_mount() {
  secure_boot_state_mode=$(target_secure_boot_state_mode)
  mountpoint="/target${DIR_VAR_LIB_SHSIGNED}"
  mapper_path=

  target_is_mounted || fatal "/target is not mounted before Secure Boot state activation"

  case "$secure_boot_state_mode" in
    direct)
      install -d -m 0700 "$mountpoint"
      install -d -m 0700 "/target${DIR_SECURE_BOOT_STATE}"
      return 0
      ;;
    luks)
      validate_target_secure_boot_luks_contract
      ;;
    *)
      fatal "unsupported Secure Boot state mode: ${secure_boot_state_mode}"
      ;;
  esac

  [ -b "${DEV_PART_VAR_LIB_SHSIGNED}" ] || fatal "Secure Boot state partition is missing: ${DEV_PART_VAR_LIB_SHSIGNED}"

  install -d -m 0700 "$mountpoint"
  open_luks_mapping_with_passphrase "${DEV_PART_VAR_LIB_SHSIGNED}" "${LUKS_NAME_VAR_LIB_SHSIGNED}" "${ACCOUNT_USERNAME}"
  mapper_path=${ACTIVE_TARGET_SECURE_BOOT_MAPPER:-$LUKS_MAPPER_VAR_LIB_SHSIGNED}
  ensure_target_mount "$mapper_path" "$mountpoint" ext4 "${MNT_VAR_LIB_SHSIGNED_OPTS}" "/var/lib/shim-signed"
  chmod 0700 "$mountpoint"
}

close_target_secure_boot_state() {
  secure_boot_state_mode=$(target_secure_boot_state_mode)
  mountpoint="/target${DIR_VAR_LIB_SHSIGNED}"
  active_mapper=

  case "$secure_boot_state_mode" in
    direct)
      install -d -m 0700 "$mountpoint"
      return 0
      ;;
    luks)
      validate_target_secure_boot_luks_contract
      ;;
    *)
      fatal "unsupported Secure Boot state mode: ${secure_boot_state_mode}"
      ;;
  esac

  active_mapper=$(installer_active_secure_boot_luks_mapper || true)
  if mounted_src=$(target_mount_source "$mountpoint"); then
    if [ -n "$active_mapper" ] && ! installer_same_device_path "$mounted_src" "$active_mapper"; then
      fatal "${mountpoint} is mounted from ${mounted_src}, expected ${active_mapper}"
    fi
    info "unmounting Secure Boot state partition"
    if ! umount "$mountpoint"; then
      fatal "failed to unmount ${mountpoint}"
    fi
    install -d -m 0700 "$mountpoint"
  fi

  active_mapper=${active_mapper:-$(installer_active_secure_boot_luks_mapper || true)}
  if [ -n "$active_mapper" ]; then
    active_mapper_name=${active_mapper##*/}
    ensure_installer_command_logged cryptsetup cryptsetup-udeb
    info "closing Secure Boot LUKS mapper ${active_mapper_name}"
    if ! cryptsetup close "$active_mapper_name"; then
      fatal "failed to close Secure Boot LUKS mapper ${active_mapper_name}"
    fi
  fi
}

remove_target_secure_boot_crypttab_entry() {
  secure_boot_state_mode=$(target_secure_boot_state_mode)
  crypttab="/target/etc/crypttab"

  [ "$secure_boot_state_mode" = "luks" ] || return 0
  validate_target_secure_boot_luks_contract

  outer_uuid=$(blkid -s UUID -o value "${DEV_PART_VAR_LIB_SHSIGNED}" 2>/dev/null || true)

  [ -f "$crypttab" ] || return 0

  tmp=$(mktemp) || fatal "unable to create temporary crypttab file"

  uuid_ref=
  [ -n "$outer_uuid" ] && uuid_ref="UUID=${outer_uuid}"
  : >"$tmp"
  while IFS= read -r line || [ -n "$line" ]; do
    trimmed_line=$(printf '%s' "$line" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')
    case "$trimmed_line" in
      ''|'#'*)
        printf '%s\n' "$line" >>"$tmp"
        continue
        ;;
    esac
    # shellcheck disable=SC2086
    set -- $trimmed_line
    [ "${1:-}" = "$LUKS_NAME_VAR_LIB_SHSIGNED" ] && continue
    [ "${2:-}" = "${DEV_PART_VAR_LIB_SHSIGNED}" ] && continue
    [ -n "$uuid_ref" ] && [ "${2:-}" = "$uuid_ref" ] && continue
    printf '%s\n' "$line" >>"$tmp"
  done <"$crypttab" || {
    rm -f "$tmp"
    fatal "failed to rewrite ${crypttab} while pruning Secure Boot auto-open entries"
  }

  if ! cmp -s "$tmp" "$crypttab"; then
    info "removing Secure Boot state crypttab auto-open entry"
    mv "$tmp" "$crypttab" || {
      rm -f "$tmp"
      fatal "failed to replace ${crypttab} after pruning Secure Boot auto-open entries"
    }
    chmod 0644 "$crypttab"
  else
    rm -f "$tmp"
  fi
}

target_secure_boot_state_mode() {
  secure_boot_mode=${SECURE_BOOT_MODE:-}
  secure_boot_state_mode=${SECURE_BOOT_STATE_MODE:-}
  if [ -n "$secure_boot_mode" ] && [ -n "$secure_boot_state_mode" ] && [ "$secure_boot_mode" != "$secure_boot_state_mode" ]; then
    installer_fatal "SECURE_BOOT_MODE and SECURE_BOOT_STATE_MODE disagree: '${secure_boot_mode}' != '${secure_boot_state_mode}'"
    return 1
  fi
  mode=${secure_boot_mode:-$secure_boot_state_mode}
  if [ -z "$mode" ]; then
    case "${HOOK_FAMILY:-}" in
      btrfs|vm) mode=luks ;;
      *) mode=direct ;;
    esac
  fi

  case "$mode" in
    luks|direct) printf '%s\n' "$mode" ;;
    *)
      installer_fatal "SECURE_BOOT_MODE/SECURE_BOOT_STATE_MODE must be 'luks' or 'direct', got '${mode}'"
      return 1
      ;;
  esac
}

validate_target_secure_boot_luks_contract() {
  [ -n "${DEV_PART_VAR_LIB_SHSIGNED:-}" ] || installer_fatal "SECURE_BOOT_STATE_MODE=luks requires DEV_PART_VAR_LIB_SHSIGNED to be defined"
  [ -n "${LUKS_NAME_VAR_LIB_SHSIGNED:-}" ] || installer_fatal "SECURE_BOOT_STATE_MODE=luks requires LUKS_NAME_VAR_LIB_SHSIGNED to be defined"
  [ -n "${LUKS_MAPPER_VAR_LIB_SHSIGNED:-}" ] || installer_fatal "SECURE_BOOT_STATE_MODE=luks requires LUKS_MAPPER_VAR_LIB_SHSIGNED to be defined"
  [ -n "${MNT_VAR_LIB_SHSIGNED_OPTS:-}" ] || installer_fatal "SECURE_BOOT_STATE_MODE=luks requires MNT_VAR_LIB_SHSIGNED_OPTS to be defined"
}

ensure_target_secure_boot_state_dirs() {
  install -d -m 0700 "/target${DIR_VAR_LIB_SHSIGNED}"
  install -d -m 0700 "/target${DIR_SECURE_BOOT_STATE}"
}

write_target_secure_boot_payloads() {
  secure_boot_state_mode=$(target_secure_boot_state_mode)
  case "$secure_boot_state_mode" in
    luks)
      validate_target_secure_boot_luks_contract
      secure_boot_luks_device=${DEV_PART_VAR_LIB_SHSIGNED}
      secure_boot_luks_name=${LUKS_NAME_VAR_LIB_SHSIGNED}
      secure_boot_luks_mapper=${LUKS_MAPPER_VAR_LIB_SHSIGNED}
      secure_boot_state_mount_opts=${MNT_VAR_LIB_SHSIGNED_OPTS}
      ;;
    direct)
      secure_boot_luks_device=${SECURE_BOOT_LUKS_DEVICE:-}
      secure_boot_luks_name=${SECURE_BOOT_LUKS_NAME:-}
      secure_boot_luks_mapper=${SECURE_BOOT_LUKS_MAPPER:-}
      secure_boot_state_mount_opts=${SECURE_BOOT_STATE_MOUNT_OPTS:-}
      ;;
    *)
      installer_fatal "unsupported Secure Boot state mode: ${secure_boot_state_mode}"
      ;;
  esac

  ensure_target_secure_boot_state_dirs
  render_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET usr/libexec/install-tools/secure-boot-tool.tmpl)" "${FILE_SECURE_BOOT_TOOL}" 0755
  render_target_asset_with_placeholder_map \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/default/secure-boot.conf.tmpl)" \
    "${FILE_SECURE_BOOT_CONFIG}" \
    0600 \
    secure_boot_config_placeholder_map

  if [ "$secure_boot_state_mode" = luks ]; then
    render_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/sbin/luks-mok-open.tmpl)" "${FILE_LUKS_MOK_OPEN_HELPER}" 0755
    render_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/sbin/luks-mok-close.tmpl)" "${FILE_LUKS_MOK_CLOSE_HELPER}" 0755
    render_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/sbin/luks-mok-passwd.tmpl)" "${FILE_LUKS_MOK_PASSWD_HELPER}" 0755
  fi
  render_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/dkms/framework.conf.d/90-secure-boot.conf.tmpl)" "${FILE_DKMS_FRAMEWORK_SECURE_BOOT}" 0644
}

install_target_secure_boot_kernel_hooks() {
  render_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/kernel/postinst.d/zz-sign-kernel.tmpl)" "${FILE_KERNEL_POSTINST_SIGN}" 0755
  render_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/kernel/postrm.d/zz-sign-kernel-cleanup.tmpl)" "${FILE_KERNEL_POSTRM_SIGN}" 0755
  render_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/kernel/header_postinst.d/zz-sign-kernel-headers.tmpl)" "${FILE_KERNEL_HEADER_POSTINST_SIGN}" 0755
}

ensure_target_secure_boot_packages() {
  if secure_boot_packages_stage_is_complete; then
    installer_info "Secure Boot target packages already repaired earlier in this install; skipping duplicate package and GRUB EFI refresh"
    return 0
  fi
  require_in_target "Secure Boot package installation"
  ensure_target_grub_profile_mounts
  install_target_secure_boot_target_packages
  reinstall_target_grub_boot_chain_packages
  require_target_grub_installed
  efivars_bind_mounted=false
  set -- /usr/sbin/grub-install \
    "--target=${INSTALLER_GRUB_EFI_TARGET}" \
    --efi-directory=/boot/efi \
    --bootloader-id=debian \
    --uefi-secure-boot \
    --force-extra-removable
  if ! target_mount_source "/target/sys/firmware/efi/efivars" >/dev/null 2>&1; then
    if [ -d /sys/firmware/efi/efivars ]; then
      install -d -m 0755 /target/sys/firmware/efi/efivars
      info "binding installer efivars into target for grub-install"
      if ! mount --bind /sys/firmware/efi/efivars /target/sys/firmware/efi/efivars; then
        warn "failed to bind installer efivars into target for grub-install; retrying without NVRAM updates"
        set -- "$@" --no-nvram
      else
        efivars_bind_mounted=true
      fi
    else
      set -- "$@" --no-nvram
    fi
  fi
  if ! attempt_in_target "refresh signed GRUB EFI payload on the mounted ESP" "$@"; then
    case " $* " in
      *" --no-nvram "*)
        fatal "grub-install failed even after disabling NVRAM updates"
        ;;
      *)
        warn "grub-install with NVRAM updates failed; retrying with --no-nvram"
        set -- "$@" --no-nvram
        run_in_target "refresh signed GRUB EFI payload on the mounted ESP without NVRAM updates" "$@"
        ;;
    esac
  fi
  if [ "$efivars_bind_mounted" = true ]; then
    if ! umount /target/sys/firmware/efi/efivars; then
      warn "failed to unmount temporary target efivars bind after grub-install"
    fi
  fi
  repair_target_secure_boot_mok_manager_loader
  repair_target_secure_boot_removable_loader
  normalize_target_grub_video_stack
  mark_secure_boot_packages_stage_complete
}

reset_target_secure_boot_mok_state() {
  if ! reset_target_secure_boot_mok_state_attempt; then
    installer_warn "failed to reset Secure Boot MOK state automatically; continuing install without a pending MOK reset"
    return 1
  fi
  return 0
}

sign_target_installed_kernel_modules() {
  run_in_target "sign installed kernel modules before final initramfs refresh" "${FILE_SECURE_BOOT_TOOL}" sign-installed-modules
  TARGET_SECURE_BOOT_RUNTIME_PREPARED=1
}

repair_target_installed_kernels() {
  run_in_target "repair installed kernel signatures and initrds" "${FILE_SECURE_BOOT_TOOL}" repair-installed-kernels
  TARGET_SECURE_BOOT_RUNTIME_PREPARED=1
}

install_target_grub_profiles() {
  profile_script="/tmp/install-grub-profiles.$$"
  profile_script_target="/target${profile_script}"
  install -d -m 0755 "$(dirname "$profile_script_target")"
  command -v render_target_template >/dev/null 2>&1 || \
    installer_fatal "render_target_template is unavailable before GRUB profile installation"
  ensure_target_grub_profile_mounts
  ensure_target_grubenv_ready
  ensure_target_bootable_kernel_pairs
  prepare_target_secure_boot_runtime
  render_target_template "${TMP_ENV_DIR}/grub-profiles" "$profile_script_target" 0755
  grub_root_device=$(installer_filesystem_device "${DEV_PART_ROOT}")

  if ! attempt_in_target "install GRUB profile entries" /bin/sh "$profile_script" \
    "${DEV_PART_BOOT}" \
    "$grub_root_device" \
    "${DEV_PART_EFI}" \
    "${BOOTPROFILE_DEFAULT}" \
    "${BOOTPROFILE_PERFORMANCE}" \
    "${BOOTPROFILE_HARDENED}" \
    "${GRUB_ROOT_FLAGS}" \
    "${GRUB_INITRAMFS_FLAGS}" \
    "${GRUB_NVME_FLAGS:-}" \
    "${GRUB_CGROUP_FLAGS}" \
    "${GRUB_SECURITY_CORE_FLAGS}" \
    "${GRUB_BLACKLIST_FLAGS:-}" \
    "${GRUB_VFIO_FLAGS:-}" \
    "${GRUB_MEMORY_CORE_FLAGS}" \
    "${GRUB_HARDENING_FLAGS}" \
    "${GRUB_ASPM_FLAGS:-}" \
    "${GRUB_SYSTEMD_MASK_FLAGS:-}" \
    "${GRUB_PROFILE_DEFAULT_FLAGS}" \
    "${GRUB_PROFILE_PERFORMANCE_FLAGS}" \
    "${GRUB_PROFILE_HARDENED_FLAGS}" \
    "${FILE_SECURE_BOOT_MOK_CERT_DER}" \
    "${GRUB_DEFAULT_ENTRY}" \
    "$(installer_rescue_usb_search_uuid)" \
    "${GRUB_DISPLAY_GFXPAYLOAD_LINUX}" \
    "${DUALBOOT_ENABLED:-false}"; then
    rm -f "$profile_script_target"
    installer_fatal "failed to install GRUB profile entries"
  fi
  rm -f "$profile_script_target"
  disable_stock_kernel_menu
}
