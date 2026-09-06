#!/bin/sh

layout_list_has() {
  list_value=$1
  needle=$2
  case " ${list_value} " in
    *" ${needle} "*) return 0 ;;
  esac
  return 1
}

layout_debug_logs_enabled() {
  return 0
}

layout_class_selected() {
  class_ref=$1
  class_name=${class_ref#*/}

  layout_list_has "${INSTALLER_SELECTED_CLASS_REFS:-}" "$class_ref" && return 0
  layout_list_has "${INSTALLER_SELECTED_CLASS_REFS:-}" "class-${class_ref%/*}/${class_name}" && return 0
  layout_list_has "${INSTALLER_SELECTED_CLASSES:-}" "$class_name" && return 0
  layout_list_has "${INSTALLER_CLASSES_RAW:-}" "$class_name" && return 0
  return 1
}

layout_syncthing_home_enabled() {
  layout_class_selected addon/tailscale
}

log() {
  layout_level=info
  layout_message=$*
  case "$layout_message" in
    INFO:\ *) layout_level=info; layout_message=${layout_message#INFO: } ;;
    WARN:\ *) layout_level=warn; layout_message=${layout_message#WARN: } ;;
    ERROR:\ *) layout_level=error; layout_message=${layout_message#ERROR: } ;;
  esac
  if ! layout_debug_logs_enabled; then
    [ "$layout_level" = error ] || return 0
  fi
  printf '%s stage=partman_done level=%s component=partman-layout %s\n' \
    "$(date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || printf unknown-time)" \
    "$layout_level" \
    "$layout_message"
  if command -v logger >/dev/null 2>&1; then
    logger -t partman-layout -- "$layout_message" || true
  fi
}

log_info() { log "INFO: $*"; }
log_warn() { log "WARN: $*"; }
log_error() { log "ERROR: $*"; }

fatal() {
  log_error "$*"
  exit 1
}

init_logging() {
  if ! layout_debug_logs_enabled; then
    return 0
  fi
  : "${FILE_STORAGE_LAYOUT_LOG:?FILE_STORAGE_LAYOUT_LOG must be set}"
  LOG_PATH=$(resolve_runtime_log_path "$FILE_STORAGE_LAYOUT_LOG")
  log_dir=$(dirname "$LOG_PATH")
  [ -d "$log_dir" ] || install -d -m 0755 "$log_dir"
  : >>"$LOG_PATH"
  chmod 0600 "$LOG_PATH" 2>/dev/null || true
  exec >>"$LOG_PATH" 2>&1
  log_info "starting shared partman storage layout"
}

ensure_installer_command() {
  cmd=$1
  udeb=$2

  command -v "$cmd" >/dev/null 2>&1 && return 0
  command -v anna-install >/dev/null 2>&1 || fatal "${cmd} is unavailable and anna-install cannot load ${udeb}"

  log_info "Installing installer udeb ${udeb} to provide ${cmd}"
  anna-install "$udeb" >/dev/null 2>&1 || fatal "anna-install ${udeb} failed while preparing ${cmd}"
  command -v "$cmd" >/dev/null 2>&1 || fatal "${cmd} is still unavailable after anna-install ${udeb}"
}

is_mounted() {
  while IFS=' ' read -r _mount_source mount_path _mount_type _mount_options _mount_rest || [ -n "${mount_path:-}" ]; do
    [ "$mount_path" = "$1" ] && return 0
  done </proc/mounts
  return 1
}

umount_path() {
  path=$1
  if is_mounted "$path"; then
    umount "$path" 2>/dev/null || umount -l "$path" 2>/dev/null || true
  fi
}

prep_dir() {
  [ -d "$1" ] || mkdir -p "$1"
}

layout_bool_is_true() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
  esac
  return 1
}

layout_bool_is_false() {
  case "${1:-}" in
    0|false|FALSE|no|NO|off|OFF) return 0 ;;
  esac
  return 1
}

require_layout_bool() {
  label=$1
  value=$2
  if ! layout_bool_is_true "$value" && ! layout_bool_is_false "$value"; then
    fatal "${label} must be true or false, got '${value}'"
  fi
}

layout_mapper_for_raw_device() {
  raw_device=$1
  raw_real=$(readlink -f "$raw_device" 2>/dev/null || true)
  [ -n "$raw_real" ] || fatal "unable to resolve encrypted raw device ${raw_device}"

  mapper_path=
  for dm_sysfs in /sys/class/block/dm-*; do
    [ -d "$dm_sysfs" ] || continue
    [ -r "$dm_sysfs/dm/name" ] || continue
    for slave_sysfs in "$dm_sysfs"/slaves/*; do
      [ -e "$slave_sysfs" ] || continue
      slave_name=${slave_sysfs##*/}
      slave_real=$(readlink -f "/dev/${slave_name}" 2>/dev/null || true)
      [ "$slave_real" = "$raw_real" ] || continue
      dm_name=$(cat "$dm_sysfs/dm/name" 2>/dev/null || true)
      [ -n "$dm_name" ] || continue
      candidate="/dev/mapper/${dm_name}"
      [ -b "$candidate" ] || continue
      if [ -n "$mapper_path" ] && [ "$mapper_path" != "$candidate" ]; then
        fatal "multiple active dm-crypt mappings reference ${raw_device}"
      fi
      mapper_path=$candidate
    done
  done

  [ -n "$mapper_path" ] || fatal "unable to locate active dm-crypt mapping for ${raw_device}"
  printf '%s\n' "$mapper_path"
}

layout_require_luks2() {
  raw_device=$1
  ensure_installer_command cryptsetup cryptsetup-udeb
  cryptsetup isLuks "$raw_device" >/dev/null 2>&1 || fatal "${raw_device} is not a LUKS container"
  luks_version=$(cryptsetup luksDump "$raw_device" 2>/dev/null |
    awk '$1 == "Version:" { print $2; exit }')
  [ "$luks_version" = 2 ] || fatal "${raw_device} is not LUKS2"
}

layout_crypto_bootstrap_key_file() {
  bootstrap_key_file="${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}/state/crypto-bootstrap.key"
  [ -f "$bootstrap_key_file" ] && [ ! -L "$bootstrap_key_file" ] ||
    fatal "crypto bootstrap key is missing or unsafe: ${bootstrap_key_file}"
  chmod 0400 "$bootstrap_key_file" 2>/dev/null || true
  printf '%s\n' "$bootstrap_key_file"
}

layout_format_luks2_partition() {
  raw_device=$1
  mapper_name=$2
  key_file=$3

  [ -b "$raw_device" ] || fatal "encrypted partition is missing: ${raw_device}"
  ensure_installer_command cryptsetup cryptsetup-udeb

  if cryptsetup isLuks "$raw_device" >/dev/null 2>&1; then
    layout_require_luks2 "$raw_device"
    return 0
  fi

  wipe_block_device "$raw_device"
  cryptsetup luksFormat \
    --batch-mode \
    --type luks2 \
    --cipher aes-xts-plain64 \
    --key-size 512 \
    --hash sha256 \
    --label "$mapper_name" \
    --key-file "$key_file" \
    "$raw_device" ||
    fatal "failed to format ${raw_device} as LUKS2"
}

layout_open_luks2_partition() {
  raw_device=$1
  mapper_name=$2
  key_file=$3
  mapper_path="/dev/mapper/${mapper_name}"

  if [ -b "$mapper_path" ]; then
    active_mapper=$(layout_mapper_for_raw_device "$raw_device")
    [ "$active_mapper" = "$mapper_path" ] ||
      fatal "active mapper ${mapper_path} does not reference ${raw_device}"
  else
    cryptsetup open \
      --type luks2 \
      --allow-discards \
      --key-file "$key_file" \
      "$raw_device" \
      "$mapper_name" ||
      fatal "failed to open LUKS2 mapper ${mapper_name} for ${raw_device}"
  fi

  [ -b "$mapper_path" ] || fatal "LUKS2 mapper was not created: ${mapper_path}"
  printf '%s\n' "$mapper_path"
}

layout_resolve_root_home_filesystem_devices() {
  ROOT_HOME_CRYPTO_ENABLED=${ROOT_HOME_CRYPTO_ENABLED:-false}
  require_layout_bool ROOT_HOME_CRYPTO_ENABLED "$ROOT_HOME_CRYPTO_ENABLED"
  layout_bool_is_true "$ROOT_HOME_CRYPTO_ENABLED" || return 0

  bootstrap_key_file=$(layout_crypto_bootstrap_key_file)
  layout_require_luks2 "$DEV_PART_ROOT"
  DEV_PART_ROOT=$(layout_mapper_for_raw_device "$DEV_PART_ROOT")
  layout_format_luks2_partition "$DEV_PART_HOME" "$HOME_CRYPT_NAME" "$bootstrap_key_file"
  DEV_PART_HOME=$(layout_open_luks2_partition "$DEV_PART_HOME" "$HOME_CRYPT_NAME" "$bootstrap_key_file")
  log_info "Resolved native LUKS2 root and direct-managed encrypted home"
}

validate_tmpfs_policy_config() {
  for var_name in \
    TMPFS_VAR_LOG \
    TMPFS_VAR_CACHE \
    TMPFS_VAR_LIB_APT_LISTS \
    TMPFS_DEV_SHM \
    TMPFS_DATA_RUN \
    TMPFS_SYSTEMD_COREDUMP
  do
    eval "var_value=\${$var_name-}"
    [ -n "$var_value" ] || fatal "${var_name} must be set"
    require_layout_bool "$var_name" "$var_value"
  done
}

log_path_is_numbered() {
  layout_check_log_path=$1
  layout_check_log_name=${layout_check_log_path##*/}

  case "$layout_check_log_name" in
    [0-9]*-*) return 0 ;;
  esac
  return 1
}

log_sequence_file() {
  layout_sequence_log_dir=$1
  printf '%s/.log-sequence\n' "$layout_sequence_log_dir"
}

next_log_sequence() {
  layout_sequence_log_dir=$1
  layout_sequence_path=$(log_sequence_file "$layout_sequence_log_dir")
  layout_sequence_tmp="${layout_sequence_path}.tmp.$$"
  layout_current_sequence=0

  [ -d "$layout_sequence_log_dir" ] || mkdir -p "$layout_sequence_log_dir"
  if [ -r "$layout_sequence_path" ]; then
    layout_current_sequence=$(cat "$layout_sequence_path" 2>/dev/null || printf '0\n')
  fi
  case "$layout_current_sequence" in
    ''|*[!0-9]*) layout_current_sequence=0 ;;
  esac

  layout_next_sequence=$((layout_current_sequence + 1))
  printf '%s\n' "$layout_next_sequence" >"$layout_sequence_tmp"
  mv "$layout_sequence_tmp" "$layout_sequence_path"
  chmod 0600 "$layout_sequence_path" 2>/dev/null || true
  printf '%s\n' "$layout_next_sequence"
}

runtime_log_dir() {
  printf '%s\n' /tmp
}

resolve_runtime_log_path() {
  requested_log_path=$1
  printf '%s\n' "$requested_log_path"
}

runtime_temp_log_path() {
  runtime_tmp_dir="${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}/state/tmp"
  runtime_tmp_name=${1%.log}
  mkdir -p "$runtime_tmp_dir" 2>/dev/null || true
  printf '%s/%s-%s.err\n' "$runtime_tmp_dir" "$$" "$runtime_tmp_name"
}

device_fs_type() {
  blkid -s TYPE -o value "$1" 2>/dev/null || true
}

device_fs_label() {
  blkid -s LABEL -o value "$1" 2>/dev/null || true
}

wipe_block_device() {
  dev=$1
  if command -v swapoff >/dev/null 2>&1; then
    swapoff "$dev" 2>/dev/null || true
  fi
  if command -v wipefs >/dev/null 2>&1; then
    wipefs -a -f "$dev" || true
  fi
}

wait_for_signature() {
  dev=$1
  expected_type=$2
  expected_label=$3
  attempt=1
  while [ "$attempt" -le 5 ]; do
    current_type=$(device_fs_type "$dev")
    current_label=$(device_fs_label "$dev")
    if [ "$current_type" = "$expected_type" ] && [ "$current_label" = "$expected_label" ]; then
      return 0
    fi
    if command -v udevadm >/dev/null 2>&1; then
      udevadm settle || true
    fi
    sleep 1
    attempt=$((attempt + 1))
  done
}

mount_block_device() {
  dev=$1
  mountpoint=$2
  fstype=$3
  opts=$4
  prep_dir "$mountpoint"
  mount -t "$fstype" -o "$opts" "$dev" "$mountpoint"
}

device_source() {
  dev=$1
  if [ "$dev" = "tmpfs" ]; then
    printf 'tmpfs\n'
    return 0
  fi
  uuid=$(blkid -s UUID -o value "$dev" 2>/dev/null || true)
  if [ -n "$uuid" ]; then
    printf 'UUID=%s\n' "$uuid"
  else
    printf '%s\n' "$dev"
  fi
}

fstab_entry() {
  printf '%-28s %-36s %-8s %-72s %s %s\n' "$1" "$2" "$3" "$4" "$5" "$6"
}

# Family storage layout runners. Keep these centralized so family finish hooks stay wrappers.

run_btrfs_storage_layout() {
load_conf() {
  : "${TMP_ENV_DIR:?TMP_ENV_DIR must point to env directory}"
  host_env="${TMP_ENV_DIR}/host.env"
  account_env="${TMP_ENV_DIR}/account.env"
  runtime_env="${TMP_ENV_DIR}/runtime.env"
  context_env="${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}/state/context.env"
  if [ ! -f "$runtime_env" ] && [ -f /tmp/install-runtime/state/runtime.env ]; then
    runtime_env=/tmp/install-runtime/state/runtime.env
  fi
  if [ ! -f "$host_env" ] || [ ! -f "$account_env" ]; then
    log_error "Configuration files missing in $TMP_ENV_DIR"
    exit 1
  fi
  # shellcheck disable=SC1090
  . "$host_env"
  if [ -f "$runtime_env" ]; then
    # shellcheck disable=SC1090
    . "$runtime_env"
  fi
  # shellcheck disable=SC1090
  . "$account_env"
  if [ -f "$context_env" ]; then
    # shellcheck disable=SC1090
    . "$context_env"
  fi
}

trace_logging_requested() {
  case "${INSTALLER_TRACE_LAYOUT:-}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
    0|false|FALSE|no|NO|off|OFF) return 1 ;;
  esac
  return 1
}

enable_trace_logging() {
  if ! trace_logging_requested; then
    log_info "Command trace disabled by default; enable with INSTALLER_TRACE_LAYOUT=true"
    return 0
  fi
  PS4='+[partman-layout:xtrace] '
  export PS4
  set -x
}

require_config() {
  required_vars="TARGET_ROOT ROOT_STAGE HOME_STAGE OPT_STAGE
DIR_STATE_LOG FILE_STORAGE_LAYOUT_LOG
DEV_PART_EFI DEV_PART_BOOT DEV_PART_ROOT DEV_PART_HOME DEV_PART_OPT DEV_PART_DATA DEV_PART_POOL DEV_PART_VAR_TMP DEV_PART_VAR_LOG_JOURNAL DEV_PART_RAW_SWAP DEV_PART_RAW_ZRAM
DIR_ROOT_HOME DIR_OPT DIR_SRV DIR_USR_LOCAL DIR_VAR_TMP DIR_VAR_SPOOL DIR_HOME DIR_HOME_DOCUMENTS DIR_HOME_DOWNLOADS DIR_HOME_PUBLIC DIR_HOME_PICTURES DIR_HOME_WORKSPACE DIR_HOME_SYNCTHING DIR_DEV_SHM
DIR_DATA DIR_DATA_RUN DIR_DATA_RUN_MNT DIR_POOL DIR_BOOT DIR_BOOT_EFI DIR_VAR_LOG DIR_VAR_LOG_JOURNAL DIR_VAR_CACHE DIR_VAR_LIB DIR_VAR_LIB_SHSIGNED DIR_APT_LISTS DIR_SYSTEMD DIR_SYSTEMD_COREDUMP DIR_TMP
MNT_BTRFS_BASE MNT_BTRFS_ROOT_OPTS MNT_ROOT_HOME_OPTS MNT_OPT_OPTS MNT_SRV_OPTS MNT_USR_LOCAL_OPTS MNT_VAR_SPOOL_OPTS
MNT_BTRFS_HOME_OPTS MNT_HOME_DOCUMENTS_OPTS MNT_HOME_DOWNLOADS_OPTS MNT_HOME_PUBLIC_OPTS MNT_HOME_PICTURES_OPTS MNT_HOME_WORKSPACE_OPTS MNT_HOME_SYNCTHING_OPTS
MNT_XFS_DATA_OPTS MNT_XFS_POOL_OPTS MNT_VAR_TMP_OPTS MNT_VAR_LOG_JOURNAL_OPTS MNT_BOOT_OPTS MNT_EFI_OPTS
MNT_VAR_LOG_TMPFS_OPTS MNT_VAR_CACHE_TMPFS_OPTS MNT_APT_LISTS_TMPFS_OPTS MNT_COREDUMP_TMPFS_OPTS MNT_DATA_RUN_TMPFS_OPTS MNT_TMP_OPTS MNT_DEV_SHM_OPTS
MKFS_VFAT_EFI_OPTS MKFS_EXT4_BOOT_OPTS MKFS_BTRFS_ROOT_OPTS MKFS_BTRFS_HOME_OPTS MKFS_BTRFS_OPT_OPTS MKFS_XFS_DATA_OPTS MKFS_XFS_POOL_OPTS MKFS_EXT4_VAR_TMP_OPTS MKFS_EXT4_VAR_LOG_JOURNAL_OPTS
FS_LABEL_EFI FS_LABEL_BOOT FS_LABEL_ROOT FS_LABEL_HOME FS_LABEL_OPT FS_LABEL_DATA FS_LABEL_POOL FS_LABEL_VAR_TMP FS_LABEL_VAR_LOG_JOURNAL
TMPFS_VAR_LOG TMPFS_VAR_CACHE TMPFS_VAR_LIB_APT_LISTS TMPFS_DEV_SHM TMPFS_DATA_RUN TMPFS_SYSTEMD_COREDUMP"
  missing=0

  for var in $required_vars; do
    case $var in
      ''|*[!A-Za-z0-9_]*)
        log_error "Invalid variable name '$var' in required vars list"
        missing=1
        continue
        ;;
    esac

    eval "val=\${$var-__MISSING__}"
    if [ "$val" = "__MISSING__" ]; then
      log_error "Required variable $var is not set"
      missing=1
      continue
    fi
    if [ -z "$val" ]; then
      log_error "Required variable $var is empty"
      missing=1
    fi
  done

  if [ "$missing" -ne 0 ]; then
    exit 1
  fi
}

is_mounted() {
  target=$1
  while IFS=' ' read -r _mount_source mount_path _mount_type _mount_options _mount_rest || [ -n "${mount_path:-}" ]; do
    [ "$mount_path" = "$target" ] && return 0
  done </proc/mounts
  return 1
}

umount_path() {
  path=$1
  if is_mounted "$path"; then
    log_info "Unmounting $path"
    umount_err=$(runtime_temp_log_path install-umount.log)
    if umount "$path" > /dev/null 2>"$umount_err"; then
      rm -f "$umount_err"
      return 0
    fi
    if ! is_mounted "$path"; then
      rm -f "$umount_err"
      return 0
    fi
    if umount -l "$path" >/dev/null 2>&1; then
      log_warn "Regular unmount failed for $path; used lazy unmount fallback"
      rm -f "$umount_err"
      return 0
    fi
    log_warn "Failed to unmount $path ($(tr '\n' ' ' <"$umount_err" | sed 's/[[:space:]]\+/ /g; s/[[:space:]]*$//')) (continuing)"
    rm -f "$umount_err"
  fi
}

cleanup_target_mounts() {
  if layout_syncthing_home_enabled; then
    umount_path "$TARGET_ROOT$DIR_HOME_SYNCTHING"
  fi

  for path in \
    "$TARGET_ROOT$DIR_BOOT_EFI" \
    "$TARGET_ROOT$DIR_BOOT" \
    "$TARGET_ROOT$DIR_HOME_WORKSPACE" \
    "$TARGET_ROOT$DIR_HOME_DOCUMENTS" \
    "$TARGET_ROOT$DIR_HOME_DOWNLOADS" \
    "$TARGET_ROOT$DIR_HOME_PUBLIC" \
    "$TARGET_ROOT$DIR_HOME_PICTURES" \
    "$TARGET_ROOT$DIR_HOME" \
    "$TARGET_ROOT$DIR_OPT" \
    "$TARGET_ROOT$DIR_DATA_RUN" \
    "$TARGET_ROOT$DIR_DATA" \
    "$TARGET_ROOT$DIR_POOL" \
    "$TARGET_ROOT$DIR_VAR_LOG_JOURNAL" \
    "$TARGET_ROOT$DIR_VAR_LOG" \
    "$TARGET_ROOT$DIR_VAR_CACHE" \
    "$TARGET_ROOT$DIR_APT_LISTS" \
    "$TARGET_ROOT$DIR_SYSTEMD_COREDUMP" \
    "$TARGET_ROOT$DIR_VAR_TMP" \
    "$TARGET_ROOT$DIR_VAR_LIB_SHSIGNED" \
    "$TARGET_ROOT$DIR_ROOT_HOME" \
    "$TARGET_ROOT$DIR_SRV" \
    "$TARGET_ROOT$DIR_USR_LOCAL" \
    "$TARGET_ROOT$DIR_VAR_SPOOL" \
    "$TARGET_ROOT$DIR_TMP" \
    "$TARGET_ROOT"
  do
    umount_path "$path"
  done
}

prep_dir() {
  [ -d "$1" ] || mkdir -p "$1"
}

device_fs_type() {
  dev=$1
  command -v blkid >/dev/null 2>&1 || return 1
  blkid -s TYPE -o value "$dev" 2>/dev/null || true
}

device_fs_label() {
  dev=$1
  command -v blkid >/dev/null 2>&1 || return 1
  blkid -s LABEL -o value "$dev" 2>/dev/null || true
}

log_block_device_geometry() {
  dev=$1
  dev_name=$(basename "$(readlink -f "$dev" 2>/dev/null || printf '%s\n' "$dev")")

  if command -v blockdev >/dev/null 2>&1; then
    logical_size=$(blockdev --getss "$dev" 2>/dev/null || true)
    physical_size=$(blockdev --getpbsz "$dev" 2>/dev/null || true)
    total_size=$(blockdev --getsize64 "$dev" 2>/dev/null || true)
  else
    logical_size=
    physical_size=
    total_size=
  fi

  if [ -z "$logical_size" ] && [ -r "/sys/class/block/${dev_name}/queue/logical_block_size" ]; then
    logical_size=$(tr -d ' \n' <"/sys/class/block/${dev_name}/queue/logical_block_size" 2>/dev/null || true)
  fi
  if [ -z "$physical_size" ] && [ -r "/sys/class/block/${dev_name}/queue/physical_block_size" ]; then
    physical_size=$(tr -d ' \n' <"/sys/class/block/${dev_name}/queue/physical_block_size" 2>/dev/null || true)
  fi
  if [ -z "$total_size" ] && [ -r "/sys/class/block/${dev_name}/size" ] && [ -n "${logical_size:-}" ]; then
    sectors=$(tr -d ' \n' <"/sys/class/block/${dev_name}/size" 2>/dev/null || true)
    case "$sectors:$logical_size" in
      :*|*:|*[!0-9:]*|*:0) ;;
      *)
        total_size=$((sectors * logical_size))
        ;;
    esac
  fi

  [ -n "${logical_size}${physical_size}${total_size}" ] || return 0
  log_info "Block geometry for ${dev}: logical_sector=${logical_size:-unknown} physical_sector=${physical_size:-unknown} size_bytes=${total_size:-unknown}"
}

wipe_block_device() {
  dev=$1
  if command -v swapoff >/dev/null 2>&1; then
    swapoff "$dev" 2>/dev/null || true
  fi
  if command -v wipefs >/dev/null 2>&1; then
    wipefs -a -f "$dev" || log_warn "wipefs failed on $dev"
  fi
}

ensure_btrfs_filesystem() {
  dev=$1
  opts=$2
  label=$3

  [ -b "$dev" ] || {
    log_error "Expected block device for btrfs provisioning: $dev"
    exit 1
  }

  current_type=$(device_fs_type "$dev")
  current_label=$(device_fs_label "$dev")
  if [ "$current_type" = "btrfs" ] && [ "$current_label" = "$label" ]; then
    log_info "Confirmed btrfs filesystem on $dev with label $label"
    return 0
  fi

  command -v mkfs.btrfs >/dev/null 2>&1 || {
    log_error "mkfs.btrfs is unavailable for $dev"
    exit 1
  }

  wipe_block_device "$dev"
  log_warn "Formatting $dev as btrfs with label $label"
  # shellcheck disable=SC2086
  mkfs.btrfs $opts "$dev"
  if command -v udevadm >/dev/null 2>&1; then
    udevadm settle || log_warn "udevadm settle failed after mkfs.btrfs on $dev"
  fi
  wait_for_device_signature "$dev" btrfs "$label"
}

ensure_xfs_filesystem() {
  dev=$1
  opts=$2
  label=$3

  [ -b "$dev" ] || {
    log_error "Expected block device for xfs provisioning: $dev"
    exit 1
  }

  command -v mkfs.xfs >/dev/null 2>&1 || {
    log_error "mkfs.xfs is unavailable for $dev"
    exit 1
  }
  # shellcheck disable=SC2086
  if ! mkfs.xfs -N $opts "$dev" >/dev/null 2>&1; then
    log_error "mkfs.xfs rejected configured options for $dev"
    exit 1
  fi

  current_type=$(device_fs_type "$dev")
  current_label=$(device_fs_label "$dev")
  if [ "$current_type" = "xfs" ] && [ "$current_label" = "$label" ]; then
    log_info "Confirmed xfs filesystem on $dev with label $label"
    return 0
  fi

  wipe_block_device "$dev"
  log_warn "Formatting $dev as xfs with label $label"
  # shellcheck disable=SC2086
  mkfs.xfs $opts "$dev"
  if command -v udevadm >/dev/null 2>&1; then
    udevadm settle || log_warn "udevadm settle failed after mkfs.xfs on $dev"
  fi
  wait_for_device_signature "$dev" xfs "$label"
}

ensure_ext4_filesystem() {
  dev=$1
  opts=$2
  label=$3

  [ -b "$dev" ] || {
    log_error "Expected block device for ext4 provisioning: $dev"
    exit 1
  }

  command -v mkfs.ext4 >/dev/null 2>&1 || {
    log_error "mkfs.ext4 is unavailable for $dev"
    exit 1
  }

  current_type=$(device_fs_type "$dev")
  current_label=$(device_fs_label "$dev")
  if [ "$current_type" = "ext4" ] && [ "$current_label" = "$label" ]; then
    log_info "Confirmed ext4 filesystem on $dev with label $label"
    return 0
  fi

  wipe_block_device "$dev"
  log_warn "Formatting $dev as ext4 with label $label"
  # shellcheck disable=SC2086
  mkfs.ext4 $opts "$dev"
  if command -v udevadm >/dev/null 2>&1; then
    udevadm settle || log_warn "udevadm settle failed after mkfs.ext4 on $dev"
  fi
  wait_for_device_signature "$dev" ext4 "$label"
}

ensure_vfat_filesystem() {
  dev=$1
  opts=$2
  label=$3

  [ -b "$dev" ] || {
    log_error "Expected block device for vfat provisioning: $dev"
    exit 1
  }

  command -v mkfs.fat >/dev/null 2>&1 || {
    log_error "mkfs.fat is unavailable for $dev"
    exit 1
  }

  current_type=$(device_fs_type "$dev")
  current_label=$(device_fs_label "$dev")
  case "$current_type" in
    vfat|fat|fat12|fat16|fat32)
      if [ "$current_label" = "$label" ]; then
        log_info "Confirmed vfat filesystem on $dev with label $label"
        return 0
      fi
      ;;
  esac

  wipe_block_device "$dev"
  log_warn "Formatting $dev as vfat with label $label"
  # shellcheck disable=SC2086
  mkfs.fat $opts "$dev"
  if command -v udevadm >/dev/null 2>&1; then
    udevadm settle || log_warn "udevadm settle failed after mkfs.fat on $dev"
  fi
  wait_for_device_signature "$dev" vfat "$label"
}

ensure_raw_block_device() {
  dev=$1

  [ -b "$dev" ] || {
    log_error "Expected block device for raw provisioning: $dev"
    exit 1
  }

  current_type=$(device_fs_type "$dev")
  if [ -n "$current_type" ]; then
    log_warn "Clearing existing ${current_type} signature from raw device $dev"
    wipe_block_device "$dev"
    if command -v udevadm >/dev/null 2>&1; then
      udevadm settle || log_warn "udevadm settle failed after raw wipe on $dev"
    fi
  fi
}

live_mount_options() {
  printf '%s\n' "$1" | sed \
    -e 's/\(^\|,\)x-systemd[^,]*//g' \
    -e 's/,,*/,/g' \
    -e 's/^,//' \
    -e 's/,$//'
}

fs_type_matches_expected() {
  fte_expected=$1
  fte_actual=$2

  case "$fte_expected" in
    vfat)
      case "$fte_actual" in
        vfat|fat|fat12|fat16|fat32) return 0 ;;
      esac
      return 1
      ;;
  esac

  [ "$fte_actual" = "$fte_expected" ]
}

refresh_block_device_state() {
  if command -v udevadm >/dev/null 2>&1; then
    udevadm settle >/dev/null 2>&1 || log_warn "udevadm settle failed during block-device refresh"
  fi
}

wait_for_device_signature() {
  wds_dev=$1
  wds_fstype=$2
  wds_label=$3
  wds_attempt=1
  wds_max_attempts=5

  command -v blkid >/dev/null 2>&1 || return 0

  while [ "$wds_attempt" -le "$wds_max_attempts" ]; do
    wds_current_type=$(device_fs_type "$wds_dev")
    wds_current_label=$(device_fs_label "$wds_dev")
    if fs_type_matches_expected "$wds_fstype" "$wds_current_type" && [ "$wds_current_label" = "$wds_label" ]; then
      if [ "$wds_attempt" -gt 1 ]; then
        log_info "Observed expected ${wds_fstype} signature on ${wds_dev} after ${wds_attempt} attempts"
      fi
      return 0
    fi
    log_warn "Waiting for ${wds_dev} to expose ${wds_fstype} label=${wds_label}; attempt ${wds_attempt}/${wds_max_attempts} saw type='${wds_current_type:-}' label='${wds_current_label:-}'"
    refresh_block_device_state
    sleep 1
    wds_attempt=$((wds_attempt + 1))
  done

  log_warn "Continuing after signature wait timeout for ${wds_dev}; final type='${wds_current_type:-}' label='${wds_current_label:-}'"
}

log_mount_diagnostics() {
  lmd_dev=$1
  lmd_mountpoint=$2
  lmd_fstype=$3
  lmd_opts=$4

  log_info "Mount diagnostics: dev=${lmd_dev} mountpoint=${lmd_mountpoint} fstype=${lmd_fstype} opts='${lmd_opts}'"
  if [ -e "$lmd_dev" ]; then
    ls -ld "$lmd_dev" 2>/dev/null || true
  else
    log_warn "Mount diagnostic: device path does not exist: $lmd_dev"
  fi
  if [ -d "$lmd_mountpoint" ]; then
    ls -ld "$lmd_mountpoint" 2>/dev/null || true
  else
    log_warn "Mount diagnostic: mountpoint path does not exist: $lmd_mountpoint"
  fi
  log_block_device_geometry "$lmd_dev"
  if command -v blkid >/dev/null 2>&1; then
    log_info "blkid export for ${lmd_dev}:"
    blkid -p -o export "$lmd_dev" 2>&1 || true
  fi
  if [ "$lmd_fstype" = "btrfs" ]; then
    if [ -r /proc/filesystems ]; then
      log_info "/proc/filesystems entries mentioning btrfs:"
      grep 'btrfs' /proc/filesystems 2>/dev/null || true
    fi
  fi
}

mount_block_device() {
  mbd_dev=$1
  mbd_mountpoint=$2
  mbd_fstype=$3
  mbd_opts=$(live_mount_options "$4")
  mbd_attempt=1
  mbd_max_attempts=3

  [ -b "$mbd_dev" ] || {
    log_error "Expected block device for mount: $mbd_dev"
    exit 1
  }

  [ -n "$mbd_opts" ] || {
    log_error "Mount options are empty for ${mbd_dev}:${mbd_mountpoint}"
    exit 1
  }

  prep_dir "$mbd_mountpoint"
  while [ "$mbd_attempt" -le "$mbd_max_attempts" ]; do
    log_info "Mount attempt ${mbd_attempt}/${mbd_max_attempts}: ${mbd_dev} on ${mbd_mountpoint} as ${mbd_fstype} with opts '${mbd_opts}'"
    mbd_err=$(runtime_temp_log_path install-mount.log)
    if mount -t "$mbd_fstype" -o "$mbd_opts" "$mbd_dev" "$mbd_mountpoint" > /dev/null 2>"$mbd_err"; then
      rm -f "$mbd_err"
      return 0
    fi
    log_warn "Mount attempt ${mbd_attempt}/${mbd_max_attempts} failed for ${mbd_dev} on ${mbd_mountpoint}: $(tr '\n' ' ' <"$mbd_err" | sed 's/[[:space:]]\+/ /g; s/[[:space:]]*$//')"
    rm -f "$mbd_err"
    log_mount_diagnostics "$mbd_dev" "$mbd_mountpoint" "$mbd_fstype" "$mbd_opts"
    [ "$mbd_attempt" -lt "$mbd_max_attempts" ] || break
    refresh_block_device_state
    sleep 1
    mbd_attempt=$((mbd_attempt + 1))
  done

  log_error "Mount failed after ${mbd_max_attempts} attempts for ${mbd_dev} on ${mbd_mountpoint}"
  exit 1
}

prepare_install_volatile_dirs() {
  ensure_dir_mode() {
    path=$1
    mode=$2
    install -d -m "$mode" "$path"
    chmod "$mode" "$path"
  }

  ensure_optional_apt_dir_mode() {
    path=$1
    mode=$2
    apt_uid=
    install -d -m "$mode" "$path"
    if [ -r "$TARGET_ROOT/etc/passwd" ]; then
      apt_uid=$(awk -F: '$1 == "_apt" { print $3; exit }' "$TARGET_ROOT/etc/passwd")
    fi
    if [ -n "$apt_uid" ]; then
      chown "${apt_uid}:0" "$path"
    elif id -u _apt >/dev/null 2>&1; then
      chown "_apt:root" "$path"
    fi
    chmod "$mode" "$path"
  }

  if layout_bool_is_true "$TMPFS_VAR_LOG"; then
    ensure_dir_mode "$TARGET_ROOT$DIR_VAR_LOG" 0755
  fi
  if layout_bool_is_true "$TMPFS_VAR_CACHE"; then
    ensure_dir_mode "$TARGET_ROOT$DIR_VAR_CACHE" 0755
    ensure_dir_mode "$TARGET_ROOT$DIR_VAR_CACHE/apt" 0755
    ensure_dir_mode "$TARGET_ROOT$DIR_VAR_CACHE/apt/archives" 0755
    ensure_optional_apt_dir_mode "$TARGET_ROOT$DIR_VAR_CACHE/apt/archives/partial" 0700
  fi
  if layout_bool_is_true "$TMPFS_VAR_LIB_APT_LISTS"; then
    ensure_dir_mode "$TARGET_ROOT$DIR_VAR_LIB" 0755
    ensure_dir_mode "$TARGET_ROOT$DIR_VAR_LIB/apt" 0755
    ensure_dir_mode "$TARGET_ROOT$DIR_APT_LISTS" 0755
    ensure_optional_apt_dir_mode "$TARGET_ROOT$DIR_APT_LISTS/partial" 0700
  fi
  if layout_bool_is_true "$TMPFS_SYSTEMD_COREDUMP"; then
    ensure_dir_mode "$TARGET_ROOT$DIR_SYSTEMD" 0755
    ensure_dir_mode "$TARGET_ROOT$DIR_SYSTEMD_COREDUMP" 0755
  fi
  if layout_bool_is_true "$TMPFS_DATA_RUN"; then
    ensure_dir_mode "$TARGET_ROOT$DIR_DATA_RUN" 0755
    ensure_dir_mode "$TARGET_ROOT$DIR_DATA_RUN_MNT" 0755
  fi
  ensure_dir_mode "$TARGET_ROOT$DIR_VAR_TMP" 1777
  ensure_dir_mode "$TARGET_ROOT$DIR_TMP" 1777
}

device_source() {
  dev=$1
  if [ "$dev" = "tmpfs" ]; then
    printf 'tmpfs\n'
    return 0
  fi
  if command -v blkid >/dev/null 2>&1; then
    uuid=$(blkid -s UUID -o value "$dev" 2>/dev/null || true)
    if [ -n "$uuid" ]; then
      printf 'UUID=%s\n' "$uuid"
      return 0
    fi
  fi
  printf '%s\n' "$dev"
}

fstab_entry() {
  printf '%-28s %-36s %-8s %-72s %s %s\n' "$1" "$2" "$3" "$4" "$5" "$6"
}

emit_fstab_entries() {
  # shellcheck disable=SC2153
  root_src=$(device_source "$DEV_PART_ROOT")
  home_src=$(device_source "$DEV_PART_HOME")
  opt_src=$(device_source "$DEV_PART_OPT")
  data_src=$(device_source "$DEV_PART_DATA")
  pool_src=$(device_source "$DEV_PART_POOL")
  # shellcheck disable=SC2153
  boot_src=$(device_source "$DEV_PART_BOOT")
  efi_src=$(device_source "$DEV_PART_EFI")
  vtmp_src=$(device_source "$DEV_PART_VAR_TMP")
  vjournal_src=$(device_source "$DEV_PART_VAR_LOG_JOURNAL")

  printf '# Pseudo filesystems\n'
  fstab_entry "proc" "/proc" "proc" "defaults" 0 0
  printf '\n'

  printf '# Boot partitions\n'
  fstab_entry "$boot_src" "$DIR_BOOT" "ext4" "$MNT_BOOT_OPTS" 0 2
  fstab_entry "$efi_src" "$DIR_BOOT_EFI" "vfat" "$MNT_EFI_OPTS" 0 2
  printf '\n'

  printf '# Core system (btrfs subvolumes)\n'
  fstab_entry "$root_src" "/" "btrfs" "$MNT_BTRFS_ROOT_OPTS" 0 0
  fstab_entry "$root_src" "$DIR_ROOT_HOME" "btrfs" "$MNT_ROOT_HOME_OPTS" 0 0
  fstab_entry "$root_src" "$DIR_SRV" "btrfs" "$MNT_SRV_OPTS" 0 0
  fstab_entry "$root_src" "$DIR_USR_LOCAL" "btrfs" "$MNT_USR_LOCAL_OPTS" 0 0
  fstab_entry "$root_src" "$DIR_VAR_SPOOL" "btrfs" "$MNT_VAR_SPOOL_OPTS" 0 0
  printf '\n'

  printf '# Home subvolumes (btrfs)\n'
  fstab_entry "$home_src" "$DIR_HOME" "btrfs" "$MNT_BTRFS_HOME_OPTS" 0 0
  fstab_entry "$home_src" "$DIR_HOME_DOCUMENTS" "btrfs" "$MNT_HOME_DOCUMENTS_OPTS" 0 0
  fstab_entry "$home_src" "$DIR_HOME_DOWNLOADS" "btrfs" "$MNT_HOME_DOWNLOADS_OPTS" 0 0
  fstab_entry "$home_src" "$DIR_HOME_PUBLIC" "btrfs" "$MNT_HOME_PUBLIC_OPTS" 0 0
  fstab_entry "$home_src" "$DIR_HOME_PICTURES" "btrfs" "$MNT_HOME_PICTURES_OPTS" 0 0
  fstab_entry "$home_src" "$DIR_HOME_WORKSPACE" "btrfs" "$MNT_HOME_WORKSPACE_OPTS" 0 0
  if layout_syncthing_home_enabled; then
    fstab_entry "$home_src" "$DIR_HOME_SYNCTHING" "btrfs" "$MNT_HOME_SYNCTHING_OPTS" 0 0
  fi
  printf '\n'

  printf '# Dedicated /opt\n'
  fstab_entry "$opt_src" "$DIR_OPT" "btrfs" "$MNT_OPT_OPTS" 0 0
  printf '\n'

  printf '# Dedicated XFS data tiers\n'
  fstab_entry "$data_src" "$DIR_DATA" "xfs" "$MNT_XFS_DATA_OPTS" 0 0
  # shellcheck disable=SC2153
  fstab_entry "$pool_src" "$DIR_POOL" "xfs" "$MNT_XFS_POOL_OPTS" 0 0
  printf '\n'

  if layout_bool_is_true "$TMPFS_DATA_RUN"; then
    printf '# Data runtime tmpfs\n'
    fstab_entry "tmpfs" "$DIR_DATA_RUN" "tmpfs" "$MNT_DATA_RUN_TMPFS_OPTS" 0 0
    printf '\n'
  fi

  printf '# Dedicated ext4 partitions\n'
  fstab_entry "$vtmp_src" "$DIR_VAR_TMP" "ext4" "$MNT_VAR_TMP_OPTS" 0 2
  printf '\n'

  printf '# Volatile tmpfs trees\n'
  if layout_bool_is_true "$TMPFS_VAR_LOG"; then
    fstab_entry "tmpfs" "$DIR_VAR_LOG" "tmpfs" "$MNT_VAR_LOG_TMPFS_OPTS" 0 0
  fi
  if layout_bool_is_true "$TMPFS_VAR_CACHE"; then
    fstab_entry "tmpfs" "$DIR_VAR_CACHE" "tmpfs" "$MNT_VAR_CACHE_TMPFS_OPTS" 0 0
  fi
  if layout_bool_is_true "$TMPFS_VAR_LIB_APT_LISTS"; then
    fstab_entry "tmpfs" "$DIR_APT_LISTS" "tmpfs" "$MNT_APT_LISTS_TMPFS_OPTS" 0 0
  fi
  if layout_bool_is_true "$TMPFS_SYSTEMD_COREDUMP"; then
    fstab_entry "tmpfs" "$DIR_SYSTEMD_COREDUMP" "tmpfs" "$MNT_COREDUMP_TMPFS_OPTS" 0 0
  fi
  fstab_entry "tmpfs" "$DIR_TMP" "tmpfs" "$MNT_TMP_OPTS" 0 0
  if layout_bool_is_true "$TMPFS_DEV_SHM"; then
    fstab_entry "tmpfs" "$DIR_DEV_SHM" "tmpfs" "$MNT_DEV_SHM_OPTS" 0 0
  fi
  printf '\n'

  printf '# Persistent journal\n'
  fstab_entry "$vjournal_src" "$DIR_VAR_LOG_JOURNAL" "ext4" "$MNT_VAR_LOG_JOURNAL_OPTS" 0 2
}

emit_fstab_entries_without_tmpfs() {
  emit_fstab_entries | while IFS= read -r fstab_line || [ -n "$fstab_line" ]; do
    # shellcheck disable=SC2086
    set -- $fstab_line
    if [ "$#" -ge 3 ] && [ "${1:-}" != "#" ] && [ "${3:-}" = "tmpfs" ]; then
      continue
    fi
    printf '%s\n' "$fstab_line"
  done
}

write_fstab_file() {
  output_path=$1
  include_header=${2:-0}
  include_tmpfs=${3:-1}
  case "$include_tmpfs" in
    0|1) ;;
    *)
      log_error "Invalid include_tmpfs value for ${output_path}: ${include_tmpfs}"
      exit 1
      ;;
  esac

  prep_dir "$(dirname "$output_path")"
  {
    if [ "$include_header" = "1" ]; then
      printf '# Generated by installer automation partman layout hook\n'
      printf '\n'
    fi
    if [ "$include_tmpfs" = "1" ]; then
      emit_fstab_entries
    else
      emit_fstab_entries_without_tmpfs
    fi
  } >"$output_path"
  chmod 0644 "$output_path"
}

write_target_fstab() {
  fstab="${TARGET_ROOT}/etc/fstab"
  fstab_cache="${TARGET_ROOT}/etc/fstab.layout-cache"
  write_fstab_file "$fstab" 1 1
  cp "$fstab" "$fstab_cache" 2>/dev/null || true
  cp "$fstab" "${TARGET_ROOT}/etc/fstab.orig" 2>/dev/null || true
  log_info "Wrote target fstab at ${fstab}"
}

write_partman_fstab_cache() {
  cache_dir="/var/lib/partman"
  cache_fstab="${cache_dir}/fstab"
  cache_fstab_new="${cache_dir}/fstab.new"
  prep_dir "$cache_dir"
  write_fstab_file "$cache_fstab" 0 0
  cp "$cache_fstab" "$cache_fstab_new" 2>/dev/null || true
  log_info "Wrote partman fstab cache without tmpfs mounts at ${cache_fstab}"
}

load_conf
init_logging
require_config
validate_tmpfs_policy_config
layout_resolve_root_home_filesystem_devices
enable_trace_logging
log_info "Configuration loaded from ${TMP_ENV_DIR} and validated"

LAYOUT_STATE_DIR="${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}/state"
LAYOUT_DONE_STAMP="${LAYOUT_STATE_DIR}/storage-layout.done"
prep_dir "$LAYOUT_STATE_DIR"
if [ -f "$LAYOUT_DONE_STAMP" ]; then
  log_info "Storage layout already completed for this installer session (${LAYOUT_DONE_STAMP}); skipping rerun"
  exit 0
fi

command -v btrfs >/dev/null 2>&1 || {
  log_error "Missing btrfs utility; ensure partman-btrfs and btrfs-progs-udeb are available."
  exit 1
}

cleanup_target_mounts

modprobe xxhash 2>/dev/null || true
modprobe btrfs 2>/dev/null || true
modprobe xfs 2>/dev/null || true

ensure_btrfs_filesystem "$DEV_PART_ROOT" "$MKFS_BTRFS_ROOT_OPTS" "$FS_LABEL_ROOT"
ensure_btrfs_filesystem "$DEV_PART_HOME" "$MKFS_BTRFS_HOME_OPTS" "$FS_LABEL_HOME"
ensure_btrfs_filesystem "$DEV_PART_OPT" "$MKFS_BTRFS_OPT_OPTS" "$FS_LABEL_OPT"
ensure_xfs_filesystem "$DEV_PART_DATA" "$MKFS_XFS_DATA_OPTS" "$FS_LABEL_DATA"
ensure_xfs_filesystem "$DEV_PART_POOL" "$MKFS_XFS_POOL_OPTS" "$FS_LABEL_POOL"
ensure_ext4_filesystem "$DEV_PART_BOOT" "$MKFS_EXT4_BOOT_OPTS" "$FS_LABEL_BOOT"
ensure_ext4_filesystem "$DEV_PART_VAR_TMP" "$MKFS_EXT4_VAR_TMP_OPTS" "$FS_LABEL_VAR_TMP"
ensure_ext4_filesystem "$DEV_PART_VAR_LOG_JOURNAL" "$MKFS_EXT4_VAR_LOG_JOURNAL_OPTS" "$FS_LABEL_VAR_LOG_JOURNAL"
ensure_raw_block_device "$DEV_PART_RAW_SWAP"
ensure_raw_block_device "$DEV_PART_RAW_ZRAM"
if [ "${DUALBOOT_ENABLED:-false}" = "true" ]; then
  log_info "Skipping EFI reformat for reused dual-boot ESP ${DEV_PART_EFI}"
else
  ensure_vfat_filesystem "$DEV_PART_EFI" "$MKFS_VFAT_EFI_OPTS" "$FS_LABEL_EFI"
fi

prep_dir "$ROOT_STAGE"
mount_block_device "$DEV_PART_ROOT" "$ROOT_STAGE" btrfs "$MNT_BTRFS_BASE"
for sub in @ @root @srv @usr_local @var_spool; do
  [ -d "$ROOT_STAGE/$sub" ] || btrfs subvolume create "$ROOT_STAGE/$sub"
done
umount "$ROOT_STAGE"
rmdir "$ROOT_STAGE" 2>/dev/null || true

prep_dir "$HOME_STAGE"
mount_block_device "$DEV_PART_HOME" "$HOME_STAGE" btrfs "$MNT_BTRFS_BASE"
home_subvolumes='@home @home_documents @home_downloads @home_public @home_pictures @home_workspace'
if layout_syncthing_home_enabled; then
  home_subvolumes="${home_subvolumes} @home_syncthing"
fi
for sub in $home_subvolumes; do
  [ -d "$HOME_STAGE/$sub" ] || btrfs subvolume create "$HOME_STAGE/$sub"
done
umount "$HOME_STAGE"
rmdir "$HOME_STAGE" 2>/dev/null || true

prep_dir "$OPT_STAGE"
mount_block_device "$DEV_PART_OPT" "$OPT_STAGE" btrfs "$MNT_BTRFS_BASE"
[ -d "$OPT_STAGE/@opt" ] || btrfs subvolume create "$OPT_STAGE/@opt"
umount "$OPT_STAGE"
rmdir "$OPT_STAGE" 2>/dev/null || true

prep_dir "$TARGET_ROOT"
mount_block_device "$DEV_PART_ROOT" "$TARGET_ROOT" btrfs "$MNT_BTRFS_ROOT_OPTS"

mount_block_device "$DEV_PART_ROOT" "$TARGET_ROOT$DIR_ROOT_HOME" btrfs "$MNT_ROOT_HOME_OPTS"
mount_block_device "$DEV_PART_ROOT" "$TARGET_ROOT$DIR_SRV" btrfs "$MNT_SRV_OPTS"
mount_block_device "$DEV_PART_ROOT" "$TARGET_ROOT$DIR_USR_LOCAL" btrfs "$MNT_USR_LOCAL_OPTS"
mount_block_device "$DEV_PART_ROOT" "$TARGET_ROOT$DIR_VAR_SPOOL" btrfs "$MNT_VAR_SPOOL_OPTS"

mount_block_device "$DEV_PART_HOME" "$TARGET_ROOT$DIR_HOME" btrfs "$MNT_BTRFS_HOME_OPTS"
mount_block_device "$DEV_PART_HOME" "$TARGET_ROOT$DIR_HOME_DOCUMENTS" btrfs "$MNT_HOME_DOCUMENTS_OPTS"
mount_block_device "$DEV_PART_HOME" "$TARGET_ROOT$DIR_HOME_DOWNLOADS" btrfs "$MNT_HOME_DOWNLOADS_OPTS"
mount_block_device "$DEV_PART_HOME" "$TARGET_ROOT$DIR_HOME_PUBLIC" btrfs "$MNT_HOME_PUBLIC_OPTS"
mount_block_device "$DEV_PART_HOME" "$TARGET_ROOT$DIR_HOME_PICTURES" btrfs "$MNT_HOME_PICTURES_OPTS"
mount_block_device "$DEV_PART_HOME" "$TARGET_ROOT$DIR_HOME_WORKSPACE" btrfs "$MNT_HOME_WORKSPACE_OPTS"
if layout_syncthing_home_enabled; then
  mount_block_device "$DEV_PART_HOME" "$TARGET_ROOT$DIR_HOME_SYNCTHING" btrfs "$MNT_HOME_SYNCTHING_OPTS"
fi

mount_block_device "$DEV_PART_OPT" "$TARGET_ROOT$DIR_OPT" btrfs "$MNT_OPT_OPTS"

mount_block_device "$DEV_PART_DATA" "$TARGET_ROOT$DIR_DATA" xfs "$MNT_XFS_DATA_OPTS"
mount_block_device "$DEV_PART_POOL" "$TARGET_ROOT$DIR_POOL" xfs "$MNT_XFS_POOL_OPTS"

mount_block_device "$DEV_PART_BOOT" "$TARGET_ROOT$DIR_BOOT" ext4 "$MNT_BOOT_OPTS"
mount_block_device "$DEV_PART_EFI" "$TARGET_ROOT$DIR_BOOT_EFI" vfat "$MNT_EFI_OPTS"
mount_block_device "$DEV_PART_VAR_TMP" "$TARGET_ROOT$DIR_VAR_TMP" ext4 "$MNT_VAR_TMP_OPTS"
install -d -m 0700 "$TARGET_ROOT$DIR_VAR_LIB_SHSIGNED"
mount_block_device "$DEV_PART_VAR_LOG_JOURNAL" "$TARGET_ROOT$DIR_VAR_LOG_JOURNAL" ext4 "$MNT_VAR_LOG_JOURNAL_OPTS"
prepare_install_volatile_dirs

write_target_fstab
write_partman_fstab_cache
: >"$LAYOUT_DONE_STAMP"
log_info "Wrote storage layout completion stamp at ${LAYOUT_DONE_STAMP}"

log_info "partman storage layout complete; installer log remains at /tmp/installer.log"
}

run_f2fs_storage_layout() {
HOST_ENV="${TMP_ENV_DIR}/host.env"
ACCOUNT_ENV="${TMP_ENV_DIR}/account.env"
RUNTIME_ENV="${TMP_ENV_DIR}/runtime.env"
[ -r "$HOST_ENV" ] || fatal "missing ${HOST_ENV}"
[ -r "$ACCOUNT_ENV" ] || fatal "missing ${ACCOUNT_ENV}"
[ -r "$RUNTIME_ENV" ] || fatal "missing ${RUNTIME_ENV}"

# shellcheck disable=SC1090,SC1091
. "$HOST_ENV"
# shellcheck disable=SC1090,SC1091
. "$RUNTIME_ENV"
# shellcheck disable=SC1090,SC1091
. "$ACCOUNT_ENV"

init_logging
validate_tmpfs_policy_config
layout_resolve_root_home_filesystem_devices

LAYOUT_STATE_DIR="${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}/state"
LAYOUT_DONE_STAMP="${LAYOUT_STATE_DIR}/storage-layout.done"
prep_dir "$LAYOUT_STATE_DIR"
if [ -f "$LAYOUT_DONE_STAMP" ]; then
  log_info "Storage layout already completed for this installer session (${LAYOUT_DONE_STAMP}); skipping rerun"
  exit 0
fi

is_mounted() {
  while IFS=' ' read -r _mount_source mount_path _mount_type _mount_options _mount_rest || [ -n "${mount_path:-}" ]; do
    [ "$mount_path" = "$1" ] && return 0
  done </proc/mounts
  return 1
}

umount_path() {
  path=$1
  if is_mounted "$path"; then
    umount "$path" 2>/dev/null || umount -l "$path" 2>/dev/null || true
  fi
}

cleanup_target_mounts() {
  for path in \
    "$TARGET_ROOT$DIR_BOOT_EFI" \
    "$TARGET_ROOT$DIR_BOOT" \
    "$TARGET_ROOT$DIR_HOME" \
    "$TARGET_ROOT$DIR_POOL" \
    "$TARGET_ROOT$DIR_VAR_LIB_SHSIGNED" \
    "$TARGET_ROOT$DIR_DATA_RUN" \
    "$TARGET_ROOT$DIR_VAR_LOG_JOURNAL" \
    "$TARGET_ROOT$DIR_VAR_LOG" \
    "$TARGET_ROOT$DIR_VAR_CACHE" \
    "$TARGET_ROOT$DIR_APT_LISTS" \
    "$TARGET_ROOT$DIR_SYSTEMD_COREDUMP" \
    "$TARGET_ROOT$DIR_TMP" \
    "$TARGET_ROOT"
  do
    [ -n "$path" ] || continue
    umount_path "$path"
  done
}

prep_dir() {
  [ -d "$1" ] || mkdir -p "$1"
}

device_fs_type() {
  blkid -s TYPE -o value "$1" 2>/dev/null || true
}

device_fs_label() {
  blkid -s LABEL -o value "$1" 2>/dev/null || true
}

wipe_block_device() {
  dev=$1
  if command -v swapoff >/dev/null 2>&1; then
    swapoff "$dev" 2>/dev/null || true
  fi
  if command -v wipefs >/dev/null 2>&1; then
    wipefs -a -f "$dev" || true
  fi
}

wait_for_signature() {
  dev=$1
  expected_type=$2
  expected_label=$3
  attempt=1
  while [ "$attempt" -le 5 ]; do
    current_type=$(device_fs_type "$dev")
    current_label=$(device_fs_label "$dev")
    if [ "$current_type" = "$expected_type" ] && [ "$current_label" = "$expected_label" ]; then
      return 0
    fi
    if command -v udevadm >/dev/null 2>&1; then
      udevadm settle || true
    fi
    sleep 1
    attempt=$((attempt + 1))
  done
}

ensure_f2fs_filesystem() {
  dev=$1
  opts=$2
  label=$3
  current_type=$(device_fs_type "$dev")
  current_label=$(device_fs_label "$dev")
  if [ "$current_type" = "f2fs" ] && [ "$current_label" = "$label" ]; then
    return 0
  fi
  command -v mkfs.f2fs >/dev/null 2>&1 || fatal "mkfs.f2fs is unavailable"
  wipe_block_device "$dev"
  # shellcheck disable=SC2086
  mkfs.f2fs $opts "$dev"
  wait_for_signature "$dev" f2fs "$label"
}

ensure_ext4_filesystem() {
  dev=$1
  opts=$2
  label=$3
  current_type=$(device_fs_type "$dev")
  current_label=$(device_fs_label "$dev")
  if [ "$current_type" = "ext4" ] && [ "$current_label" = "$label" ]; then
    return 0
  fi
  command -v mkfs.ext4 >/dev/null 2>&1 || fatal "mkfs.ext4 is unavailable"
  wipe_block_device "$dev"
  # shellcheck disable=SC2086
  mkfs.ext4 $opts "$dev"
  wait_for_signature "$dev" ext4 "$label"
}

ensure_vfat_filesystem() {
  dev=$1
  opts=$2
  label=$3
  current_type=$(device_fs_type "$dev")
  current_label=$(device_fs_label "$dev")
  case "$current_type" in
    vfat|fat|fat12|fat16|fat32)
      [ "$current_label" = "$label" ] && return 0
      ;;
  esac
  command -v mkfs.fat >/dev/null 2>&1 || fatal "mkfs.fat is unavailable"
  wipe_block_device "$dev"
  # shellcheck disable=SC2086
  mkfs.fat $opts "$dev"
  wait_for_signature "$dev" vfat "$label"
}

ensure_raw_block_device() {
  dev=$1
  [ -b "$dev" ] || fatal "missing raw block device ${dev}"
  current_type=$(device_fs_type "$dev")
  if [ -n "$current_type" ]; then
    wipe_block_device "$dev"
  fi
}

f2fs_live_mount_options() {
  printf '%s\n' "$1" | sed \
    -e 's/\(^\|,\)x-systemd[^,]*//g' \
    -e 's/,,*/,/g' \
    -e 's/^,//' \
    -e 's/,$//'
}

mount_block_device() {
  dev=$1
  mountpoint=$2
  fstype=$3
  opts=$(f2fs_live_mount_options "$4")
  [ -b "$dev" ] || fatal "missing block device for mount: ${dev}"
  [ -n "$opts" ] || fatal "installer mount options are empty for ${dev}:${mountpoint}"
  prep_dir "$mountpoint"
  mount -t "$fstype" -o "$opts" "$dev" "$mountpoint"
}

prepare_volatile_dirs() {
  ensure_optional_apt_dir_mode() {
    path=$1
    mode=$2
    apt_uid=
    install -d -m "$mode" "$path"
    if [ -r "$TARGET_ROOT/etc/passwd" ]; then
      apt_uid=$(awk -F: '$1 == "_apt" { print $3; exit }' "$TARGET_ROOT/etc/passwd")
    fi
    if [ -n "$apt_uid" ]; then
      chown "${apt_uid}:0" "$path"
    elif id -u _apt >/dev/null 2>&1; then
      chown "_apt:root" "$path"
    fi
    chmod "$mode" "$path"
  }

  if layout_bool_is_true "$TMPFS_VAR_LOG"; then
    install -d -m 0755 "$TARGET_ROOT$DIR_VAR_LOG"
  fi
  if layout_bool_is_true "$TMPFS_VAR_CACHE"; then
    install -d -m 0755 "$TARGET_ROOT$DIR_VAR_CACHE"
    install -d -m 0755 "$TARGET_ROOT$DIR_VAR_CACHE/apt" "$TARGET_ROOT$DIR_VAR_CACHE/apt/archives"
    ensure_optional_apt_dir_mode "$TARGET_ROOT$DIR_VAR_CACHE/apt/archives/partial" 0700
  fi
  if layout_bool_is_true "$TMPFS_VAR_LIB_APT_LISTS"; then
    install -d -m 0755 "$TARGET_ROOT$DIR_VAR_LIB" "$TARGET_ROOT$DIR_VAR_LIB/apt" "$TARGET_ROOT$DIR_APT_LISTS"
    ensure_optional_apt_dir_mode "$TARGET_ROOT$DIR_APT_LISTS/partial" 0700
  fi
  if layout_bool_is_true "$TMPFS_SYSTEMD_COREDUMP"; then
    install -d -m 0755 "$TARGET_ROOT$DIR_SYSTEMD" "$TARGET_ROOT$DIR_SYSTEMD_COREDUMP"
  fi
  if layout_bool_is_true "$TMPFS_DATA_RUN"; then
    install -d -m 0755 "$TARGET_ROOT$DIR_DATA_RUN" "$TARGET_ROOT$DIR_DATA_RUN_MNT"
  fi
  install -d -m 1777 "$TARGET_ROOT$DIR_TMP"
  if layout_bool_is_true "$TMPFS_DEV_SHM"; then
    install -d -m 1777 "$TARGET_ROOT$DIR_DEV_SHM"
  fi
}

device_source() {
  dev=$1
  if [ "$dev" = "tmpfs" ]; then
    printf 'tmpfs\n'
    return 0
  fi
  uuid=$(blkid -s UUID -o value "$dev" 2>/dev/null || true)
  if [ -n "$uuid" ]; then
    printf 'UUID=%s\n' "$uuid"
  else
    printf '%s\n' "$dev"
  fi
}

fstab_entry() {
  printf '%-28s %-36s %-8s %-72s %s %s\n' "$1" "$2" "$3" "$4" "$5" "$6"
}

emit_fstab_entries() {
  # The installer-generated runtime env provides these device paths and mount options.
  # shellcheck disable=SC2153
  boot_src=$(device_source "$DEV_PART_BOOT")
  efi_src=$(device_source "$DEV_PART_EFI")
  # shellcheck disable=SC2153
  root_src=$(device_source "$DEV_PART_ROOT")
  journal_src=$(device_source "$DEV_PART_VAR_LOG_JOURNAL")

  printf '# Pseudo filesystems\n'
  fstab_entry proc /proc proc defaults 0 0
  printf '\n# Boot partitions\n'
  # shellcheck disable=SC2153
  fstab_entry "$boot_src" "$DIR_BOOT" ext4 "$MNT_BOOT_OPTS" 0 2
  fstab_entry "$efi_src" "$DIR_BOOT_EFI" vfat "$MNT_EFI_OPTS" 0 2
  printf '\n# Core filesystems\n'
  # shellcheck disable=SC2153
  fstab_entry "$root_src" / f2fs "$MNT_F2FS_ROOT_OPTS" 0 0
  if [ -n "${DEV_PART_HOME:-}" ] && [ "${DEV_PART_HOME_MB:-0}" -gt 0 ]; then
    home_src=$(device_source "$DEV_PART_HOME")
    fstab_entry "$home_src" "$DIR_HOME" f2fs "$MNT_F2FS_HOME_OPTS" 0 0
  fi
  if [ -n "${DEV_PART_POOL:-}" ] && [ -n "${MNT_EXT4_POOL_OPTS:-}" ] && [ "$DEV_PART_POOL_MB" -gt 0 ]; then
    pool_src=$(device_source "$DEV_PART_POOL")
    fstab_entry "$pool_src" "$DIR_POOL" ext4 "$MNT_EXT4_POOL_OPTS" 0 2
  fi
  if layout_bool_is_true "$TMPFS_DATA_RUN"; then
    printf '\n# Data runtime tmpfs\n'
    fstab_entry tmpfs "$DIR_DATA_RUN" tmpfs "$MNT_DATA_RUN_TMPFS_OPTS" 0 0
  fi
  printf '\n# Volatile tmpfs trees\n'
  if layout_bool_is_true "$TMPFS_VAR_LOG"; then
    fstab_entry tmpfs "$DIR_VAR_LOG" tmpfs "$MNT_VAR_LOG_TMPFS_OPTS" 0 0
  fi
  if layout_bool_is_true "$TMPFS_VAR_CACHE"; then
    fstab_entry tmpfs "$DIR_VAR_CACHE" tmpfs "$MNT_VAR_CACHE_TMPFS_OPTS" 0 0
  fi
  if layout_bool_is_true "$TMPFS_VAR_LIB_APT_LISTS"; then
    fstab_entry tmpfs "$DIR_APT_LISTS" tmpfs "$MNT_APT_LISTS_TMPFS_OPTS" 0 0
  fi
  if layout_bool_is_true "$TMPFS_SYSTEMD_COREDUMP"; then
    fstab_entry tmpfs "$DIR_SYSTEMD_COREDUMP" tmpfs "$MNT_COREDUMP_TMPFS_OPTS" 0 0
  fi
  fstab_entry tmpfs "$DIR_TMP" tmpfs "$MNT_TMP_OPTS" 0 0
  if layout_bool_is_true "$TMPFS_DEV_SHM"; then
    fstab_entry tmpfs "$DIR_DEV_SHM" tmpfs "$MNT_DEV_SHM_OPTS" 0 0
  fi
  printf '\n# Persistent journal\n'
  fstab_entry "$journal_src" "$DIR_VAR_LOG_JOURNAL" ext4 "$MNT_VAR_LOG_JOURNAL_OPTS" 0 2
}

emit_fstab_entries_without_tmpfs() {
  emit_fstab_entries | while IFS= read -r fstab_line || [ -n "$fstab_line" ]; do
    # shellcheck disable=SC2086
    set -- $fstab_line
    if [ "$#" -ge 3 ] && [ "${1:-}" != "#" ] && [ "${3:-}" = "tmpfs" ]; then
      continue
    fi
    printf '%s\n' "$fstab_line"
  done
}

write_fstab_file() {
  output_path=$1
  include_header=${2:-0}
  include_tmpfs=${3:-1}
  case "$include_tmpfs" in
    0|1) ;;
    *)
      log_error "Invalid include_tmpfs value for ${output_path}: ${include_tmpfs}"
      exit 1
      ;;
  esac

  prep_dir "$(dirname "$output_path")"
  {
    if [ "$include_header" = 1 ]; then
      printf '# Generated by installer automation partman layout hook\n\n'
    fi
    if [ "$include_tmpfs" = 1 ]; then
      emit_fstab_entries
    else
      emit_fstab_entries_without_tmpfs
    fi
  } >"$output_path"
  chmod 0644 "$output_path"
}

write_target_fstab() {
  write_fstab_file "${TARGET_ROOT}/etc/fstab" 1 1
  cp "${TARGET_ROOT}/etc/fstab" "${TARGET_ROOT}/etc/fstab.layout-cache" 2>/dev/null || true
  cp "${TARGET_ROOT}/etc/fstab" "${TARGET_ROOT}/etc/fstab.orig" 2>/dev/null || true
}

write_partman_fstab_cache() {
  prep_dir /var/lib/partman
  write_fstab_file /var/lib/partman/fstab 0 0
  cp /var/lib/partman/fstab /var/lib/partman/fstab.new 2>/dev/null || true
  log_info "Wrote partman fstab cache without tmpfs mounts at /var/lib/partman/fstab"
}

cleanup_target_mounts

ensure_installer_command mkfs.f2fs f2fs-tools-udeb
ensure_installer_command mkfs.ext4 e2fsprogs-udeb
ensure_installer_command mkfs.fat dosfstools-udeb

ensure_vfat_filesystem "$DEV_PART_EFI" "$MKFS_VFAT_EFI_OPTS" "$FS_LABEL_EFI"
ensure_ext4_filesystem "$DEV_PART_BOOT" "$MKFS_EXT4_BOOT_OPTS" "$FS_LABEL_BOOT"
ensure_f2fs_filesystem "$DEV_PART_ROOT" "$MKFS_F2FS_ROOT_OPTS" "$FS_LABEL_ROOT"
if [ -n "${DEV_PART_HOME:-}" ] && [ "${DEV_PART_HOME_MB:-0}" -gt 0 ]; then
  ensure_f2fs_filesystem "$DEV_PART_HOME" "$MKFS_F2FS_HOME_OPTS" "$FS_LABEL_HOME"
fi
if [ -n "${DEV_PART_POOL:-}" ] && [ "$DEV_PART_POOL_MB" -gt 0 ]; then
  ensure_ext4_filesystem "$DEV_PART_POOL" "$MKFS_EXT4_POOL_OPTS" "$FS_LABEL_POOL"
fi
ensure_ext4_filesystem "$DEV_PART_VAR_LOG_JOURNAL" "$MKFS_EXT4_VAR_LOG_JOURNAL_OPTS" "$FS_LABEL_VAR_LOG_JOURNAL"
ensure_raw_block_device "$DEV_PART_RAW_SWAP"
ensure_raw_block_device "$DEV_PART_RAW_ZRAM"

prep_dir "$TARGET_ROOT"
mount_block_device "$DEV_PART_ROOT" "$TARGET_ROOT" f2fs "${MNT_F2FS_INSTALLER_ROOT_OPTS:-$MNT_F2FS_ROOT_OPTS}"
if [ -n "${DEV_PART_HOME:-}" ] && [ "${DEV_PART_HOME_MB:-0}" -gt 0 ]; then
  mount_block_device "$DEV_PART_HOME" "$TARGET_ROOT$DIR_HOME" f2fs "${MNT_F2FS_INSTALLER_HOME_OPTS:-$MNT_F2FS_HOME_OPTS}"
else
  install -d -m 0755 "$TARGET_ROOT$DIR_HOME"
fi
if [ -n "${DEV_PART_POOL:-}" ] && [ "$DEV_PART_POOL_MB" -gt 0 ]; then
  mount_block_device "$DEV_PART_POOL" "$TARGET_ROOT$DIR_POOL" ext4 "$MNT_EXT4_POOL_OPTS"
else
  install -d -m 0755 "$TARGET_ROOT$DIR_POOL"
fi
mount_block_device "$DEV_PART_BOOT" "$TARGET_ROOT$DIR_BOOT" ext4 "$MNT_BOOT_OPTS"
mount_block_device "$DEV_PART_EFI" "$TARGET_ROOT$DIR_BOOT_EFI" vfat "$MNT_EFI_OPTS"
mount_block_device "$DEV_PART_VAR_LOG_JOURNAL" "$TARGET_ROOT$DIR_VAR_LOG_JOURNAL" ext4 "$MNT_VAR_LOG_JOURNAL_OPTS"
prepare_volatile_dirs

write_target_fstab
write_partman_fstab_cache
: >"$LAYOUT_DONE_STAMP"
log_info "Wrote storage layout completion stamp at ${LAYOUT_DONE_STAMP}"

log_info "partman storage layout complete; installer log remains at /tmp/installer.log"
}
