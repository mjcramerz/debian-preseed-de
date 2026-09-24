#!/bin/sh
# Shared late_command target-template renderer. This file is sourced, not executed.

render_target_template_placeholder_map() {
  dir_apt_state=${DIR_APT_LISTS%/lists}
  # Runtime layout env fragments provide the zram device names for template rendering.
  # shellcheck disable=SC2153
  zram_swap_device=${ZRAM_SWAP_DEVICE}
  zram_setup_unit=${FILE_ZRAM_SETUP_SERVICE##*/}
  zram_swap_device_name=${ZRAM_SWAP_DEVICE##*/}
  zram_sysfs=${ZRAM_SYSFS:-/sys/block/${zram_swap_device_name}}
  zram_runtime_dir=${ZRAM_RUNTIME_DIR:-/run/zram}
  zram_lock_file=${ZRAM_LOCK_FILE:-${zram_runtime_dir}/zram-writeback.lock}
  zram_enable=${ZRAM_ENABLE:-1}
  zram_backing_reserve_mib=${ZRAM_BACKING_RESERVE_MIB:-128}
  zram_policy_config=${ZRAM_POLICY_CONFIG:-$FILE_ZRAM_CONFIG}
  zram_backing_raw_partuuid=${ZRAM_BACKING_RAW_PARTUUID:-}
  if [ -z "$zram_backing_raw_partuuid" ] && command -v blkid >/dev/null 2>&1; then
    zram_backing_raw_partuuid=$(blkid -s PARTUUID -o value "$ZRAM_BACKING_RAW_DEVICE" 2>/dev/null || true)
  fi
  [ -n "$zram_backing_raw_partuuid" ] || installer_fatal "unable to determine PARTUUID for zram backing device ${ZRAM_BACKING_RAW_DEVICE}"
  zram_backing_raw_device="/dev/disk/by-partuuid/${zram_backing_raw_partuuid}"
  account_username=${ACCOUNT_USERNAME:-}

  cat <<EOF
DIR_RUN_SYSCTL=$DIR_RUN_SYSCTL
DIR_SYSCTL_PROFILES=$DIR_SYSCTL_PROFILES
BOOTPROFILE_DEFAULT=$BOOTPROFILE_DEFAULT
BOOTPROFILE_HARDENED=$BOOTPROFILE_HARDENED
BOOTPROFILE_PERFORMANCE=$BOOTPROFILE_PERFORMANCE
FILE_BOOTPROFILE_APPLY=$FILE_BOOTPROFILE_APPLY
DIR_VAR_LOG=$DIR_VAR_LOG
DIR_VAR_CACHE=$DIR_VAR_CACHE
DIR_APT_LISTS=$DIR_APT_LISTS
DIR_APT_STATE=$dir_apt_state
DIR_SYSTEMD=$DIR_SYSTEMD
DIR_SYSTEMD_COREDUMP=$DIR_SYSTEMD_COREDUMP
DIR_DATA_RUN=$DIR_DATA_RUN
DIR_DATA_RUN_MNT=$DIR_DATA_RUN_MNT
DIR_RUN_MEDIA=$DIR_RUN_MEDIA
DIR_DATA=$DIR_DATA
DIR_DATA_CONFIG=$DIR_DATA_CONFIG
DIR_DATA_SERVICES=$DIR_DATA_SERVICES
DIR_DATA_SERVICES_USR=$DIR_DATA_SERVICES_USR
DIR_DATA_BIN=$DIR_DATA_BIN
DIR_DATA_DOCS=$DIR_DATA_DOCS
DIR_DATA_DOWNLOADS=$DIR_DATA_DOWNLOADS
DIR_DATA_PKI=$DIR_DATA_PKI
DIR_DATA_BACKUP=$DIR_DATA_BACKUP
DIR_POOL=$DIR_POOL
DIR_POOL_BUILD=$DIR_POOL_BUILD
DIR_POOL_BUILD_RUNNERS=$DIR_POOL_BUILD_RUNNERS
DIR_POOL_CACHE=$DIR_POOL_CACHE
DIR_POOL_CACHE_RUNNERS=$DIR_POOL_CACHE_RUNNERS
DIR_POOL_DB=$DIR_POOL_DB
DIR_POOL_PODMAN=$DIR_POOL_PODMAN
DIR_POOL_LOG=$DIR_POOL_LOG
DIR_POOL_APTLY=$DIR_POOL_APTLY
DIR_POLKIT_LOCAL_RULES_D=${DIR_POLKIT_LOCAL_RULES_D:-}
DIR_POLKIT_RUNTIME_RULES_D=${DIR_POLKIT_RUNTIME_RULES_D:-}
ACCOUNT_USERNAME=$account_username
SYSTEM_HOSTNAME=${SYSTEM_HOSTNAME:-}
SYSTEM_DOMAIN=${SYSTEM_DOMAIN:-}
INSTALLER_DEBUG_LOGS=${INSTALLER_DEBUG_LOGS:-0}
SYSTEMD_LOG_LEVEL=${SYSTEMD_LOG_LEVEL:-error}
NFTABLES_LOG_LEVEL=${NFTABLES_LOG_LEVEL:-none}
DIR_VAR_TMP=${DIR_VAR_TMP:-}
DIR_TMP=$DIR_TMP
DIR_DEV_SHM=$DIR_DEV_SHM
FILE_ZRAM_DEFAULT=$FILE_ZRAM_DEFAULT
FILE_ZRAM_CONFIG=$FILE_ZRAM_CONFIG
FILE_ZRAM_SETUP_HELPER=$FILE_ZRAM_SETUP_HELPER
FILE_ZRAM_WRITEBACK_HELPER=$FILE_ZRAM_WRITEBACK_HELPER
GRUB_DEFAULT_ENTRY=$GRUB_DEFAULT_ENTRY
GRUB_ROOT_FLAGS=$GRUB_ROOT_FLAGS
GRUB_INITRAMFS_FLAGS=$GRUB_INITRAMFS_FLAGS
GRUB_NVME_FLAGS=${GRUB_NVME_FLAGS:-}
GRUB_SYSTEMD_MASK_FLAGS=${GRUB_SYSTEMD_MASK_FLAGS:-}
GRUB_CGROUP_FLAGS=$GRUB_CGROUP_FLAGS
GRUB_SECURITY_CORE_FLAGS=$GRUB_SECURITY_CORE_FLAGS
GRUB_BLACKLIST_FLAGS=${GRUB_BLACKLIST_FLAGS:-}
GRUB_VFIO_FLAGS=${GRUB_VFIO_FLAGS:-}
GRUB_MEMORY_CORE_FLAGS=$GRUB_MEMORY_CORE_FLAGS
GRUB_HARDENING_FLAGS=$GRUB_HARDENING_FLAGS
GRUB_ASPM_FLAGS=${GRUB_ASPM_FLAGS:-}
GRUB_MOK_MANAGER_EFI_PATH=$INSTALLER_GRUB_MOK_MANAGER_EFI_PATH
GRUB_REMOVABLE_BOOT_EFI_PATH=$INSTALLER_GRUB_REMOVABLE_BOOT_EFI_PATH
FILE_SECURE_BOOT_TOOL=$FILE_SECURE_BOOT_TOOL
FILE_SECURE_BOOT_MOK_KEY=$FILE_SECURE_BOOT_MOK_KEY
FILE_SECURE_BOOT_MOK_CERT_DER=$FILE_SECURE_BOOT_MOK_CERT_DER
SECURE_BOOT_DEFER_HOOK_FAILURES=${SECURE_BOOT_DEFER_HOOK_FAILURES:-0}
FILE_SWAP_FALLBACK_CONFIG=$FILE_SWAP_FALLBACK_CONFIG
FILE_SWAP_FALLBACK_HELPER=$FILE_SWAP_FALLBACK_HELPER
ZRAM_ENABLE=$zram_enable
ZRAM_SWAP_DEVICE=$zram_swap_device
ZRAM_SETUP_UNIT=$zram_setup_unit
ZRAM_SWAP_DEVICE_NAME=$zram_swap_device_name
ZRAM_SYSFS=$zram_sysfs
ZRAM_RUNTIME_DIR=$zram_runtime_dir
ZRAM_LOCK_FILE=$zram_lock_file
ZRAM_LOG_LEVEL=${ZRAM_LOG_LEVEL:-info}
ZRAM_ALGORITHM_PARAMS=${ZRAM_ALGORITHM_PARAMS:-}
ZRAM_BACKING_RAW_PARTUUID=$zram_backing_raw_partuuid
ZRAM_BACKING_RAW_DEVICE=$zram_backing_raw_device
ZRAM_BACKING_MAPPER_NAME=$ZRAM_BACKING_MAPPER_NAME
ZRAM_BACKING_DEVICE=$ZRAM_BACKING_DEVICE
ZRAM_BACKING_RESERVE_MIB=$zram_backing_reserve_mib
DMCRYPT_EPHEMERAL_CIPHER=$DMCRYPT_EPHEMERAL_CIPHER
DMCRYPT_EPHEMERAL_KEY_SIZE=$DMCRYPT_EPHEMERAL_KEY_SIZE
DMCRYPT_EPHEMERAL_HASH=$DMCRYPT_EPHEMERAL_HASH
DMCRYPT_RANDOM_KEY_FILE=$DMCRYPT_RANDOM_KEY_FILE
ZRAM_COMPRESSION_ALGORITHM=$ZRAM_COMPRESSION_ALGORITHM
ZRAM_TIER1_ENABLE=$ZRAM_TIER1_ENABLE
ZRAM_TIER1_ALGORITHM=$ZRAM_TIER1_ALGORITHM
ZRAM_TIER1_PRIORITY=$ZRAM_TIER1_PRIORITY
ZRAM_TIER1_LEVEL=$ZRAM_TIER1_LEVEL
ZRAM_TIER1_THRESHOLD_BYTES=$ZRAM_TIER1_THRESHOLD_BYTES
ZRAM_TIER1_MAX_PAGES_NORMAL=$ZRAM_TIER1_MAX_PAGES_NORMAL
ZRAM_TIER1_MAX_PAGES_PRESSURE=$ZRAM_TIER1_MAX_PAGES_PRESSURE
ZRAM_TIER1_MAX_PAGES_EMERGENCY=$ZRAM_TIER1_MAX_PAGES_EMERGENCY
ZRAM_TIER2_ENABLE=$ZRAM_TIER2_ENABLE
ZRAM_TIER2_ALGORITHM=$ZRAM_TIER2_ALGORITHM
ZRAM_TIER2_PRIORITY=$ZRAM_TIER2_PRIORITY
ZRAM_TIER2_LEVEL=$ZRAM_TIER2_LEVEL
ZRAM_TIER2_THRESHOLD_BYTES=$ZRAM_TIER2_THRESHOLD_BYTES
ZRAM_TIER2_MAX_PAGES_NORMAL=$ZRAM_TIER2_MAX_PAGES_NORMAL
ZRAM_TIER2_MAX_PAGES_PRESSURE=$ZRAM_TIER2_MAX_PAGES_PRESSURE
ZRAM_TIER2_MAX_PAGES_EMERGENCY=$ZRAM_TIER2_MAX_PAGES_EMERGENCY
ZRAM_TIER3_ENABLE=$ZRAM_TIER3_ENABLE
ZRAM_TIER3_ALGORITHM=$ZRAM_TIER3_ALGORITHM
ZRAM_TIER3_PRIORITY=$ZRAM_TIER3_PRIORITY
ZRAM_TIER3_LEVEL=$ZRAM_TIER3_LEVEL
ZRAM_TIER3_THRESHOLD_BYTES=$ZRAM_TIER3_THRESHOLD_BYTES
ZRAM_TIER3_MAX_PAGES_NORMAL=$ZRAM_TIER3_MAX_PAGES_NORMAL
ZRAM_TIER3_MAX_PAGES_PRESSURE=$ZRAM_TIER3_MAX_PAGES_PRESSURE
ZRAM_TIER3_MAX_PAGES_EMERGENCY=$ZRAM_TIER3_MAX_PAGES_EMERGENCY
ZRAM_SWAP_PRIORITY=$ZRAM_SWAP_PRIORITY
ZRAM_MAX_COMP_STREAMS=$ZRAM_MAX_COMP_STREAMS
ZRAM_COMPRESSED_WRITEBACK=$ZRAM_COMPRESSED_WRITEBACK
ZRAM_HOT_AGE_SEC=$ZRAM_HOT_AGE_SEC
ZRAM_IDLE_AGE_SEC=$ZRAM_IDLE_AGE_SEC
ZRAM_PRESSURE_IDLE_AGE_SEC=$ZRAM_PRESSURE_IDLE_AGE_SEC
ZRAM_EMERGENCY_IDLE_AGE_SEC=$ZRAM_EMERGENCY_IDLE_AGE_SEC
ZRAM_WRITEBACK_ENABLE=$ZRAM_WRITEBACK_ENABLE
ZRAM_WRITEBACK_BATCH_SIZE=$ZRAM_WRITEBACK_BATCH_SIZE
ZRAM_WRITEBACK_BATCH_SIZE_ADAPTIVE=$ZRAM_WRITEBACK_BATCH_SIZE_ADAPTIVE
ZRAM_WRITEBACK_BATCH_SIZE_NORMAL=$ZRAM_WRITEBACK_BATCH_SIZE_NORMAL
ZRAM_WRITEBACK_BATCH_SIZE_PRESSURE=$ZRAM_WRITEBACK_BATCH_SIZE_PRESSURE
ZRAM_WRITEBACK_BATCH_SIZE_EMERGENCY=$ZRAM_WRITEBACK_BATCH_SIZE_EMERGENCY
ZRAM_WRITEBACK_BATCH_SIZE_ROTATIONAL_MAX=$ZRAM_WRITEBACK_BATCH_SIZE_ROTATIONAL_MAX
ZRAM_WRITEBACK_BATCH_SIZE_MAX=$ZRAM_WRITEBACK_BATCH_SIZE_MAX
ZRAM_WRITEBACK_MAX_PAGES_PRESSURE=$ZRAM_WRITEBACK_MAX_PAGES_PRESSURE
ZRAM_WRITEBACK_MAX_PAGES_EMERGENCY=$ZRAM_WRITEBACK_MAX_PAGES_EMERGENCY
ZRAM_IO_PSI_ENABLE=$ZRAM_IO_PSI_ENABLE
ZRAM_IO_PSI_SOME_AVG10_THRESHOLD=$ZRAM_IO_PSI_SOME_AVG10_THRESHOLD
ZRAM_IO_PSI_FULL_AVG10_THRESHOLD=$ZRAM_IO_PSI_FULL_AVG10_THRESHOLD
ZRAM_IO_PSI_BATCH_SIZE_PRESSURE=$ZRAM_IO_PSI_BATCH_SIZE_PRESSURE
ZRAM_IO_PSI_BATCH_SIZE_EMERGENCY=$ZRAM_IO_PSI_BATCH_SIZE_EMERGENCY
ZRAM_IO_PSI_MAX_PAGES_PRESSURE=$ZRAM_IO_PSI_MAX_PAGES_PRESSURE
ZRAM_IO_PSI_MAX_PAGES_EMERGENCY=$ZRAM_IO_PSI_MAX_PAGES_EMERGENCY
ZRAM_WRITEBACK_PASS_PAGES_MAX=$ZRAM_WRITEBACK_PASS_PAGES_MAX
ZRAM_BLOCK_STATE_MAX_LINES=$ZRAM_BLOCK_STATE_MAX_LINES
ZRAM_BLOCK_STATE_FALLBACK_LINES=$ZRAM_BLOCK_STATE_FALLBACK_LINES
ZRAM_LOGICAL_BLOCK_SIZE_FALLBACK=$ZRAM_LOGICAL_BLOCK_SIZE_FALLBACK
ZRAM_WRITEBACK_SPEC_MAX_BYTES=$ZRAM_WRITEBACK_SPEC_MAX_BYTES
ZRAM_WRITEBACK_CHUNKS_PER_CLASS_MAX=$ZRAM_WRITEBACK_CHUNKS_PER_CLASS_MAX
ZRAM_WRITEBACK_LIMIT_ENABLE=$ZRAM_WRITEBACK_LIMIT_ENABLE
ZRAM_DAILY_WRITEBACK_LIMIT=${ZRAM_DAILY_WRITEBACK_LIMIT:-}
ZRAM_PRESSURE_MEM_AVAILABLE_PCT=$ZRAM_PRESSURE_MEM_AVAILABLE_PCT
ZRAM_EMERGENCY_MEM_AVAILABLE_PCT=$ZRAM_EMERGENCY_MEM_AVAILABLE_PCT
ZRAM_PRESSURE_SOME_AVG10_THRESHOLD=$ZRAM_PRESSURE_SOME_AVG10_THRESHOLD
ZRAM_PRESSURE_FULL_AVG10_THRESHOLD=$ZRAM_PRESSURE_FULL_AVG10_THRESHOLD
ZRAM_EMERGENCY_SOME_AVG10_THRESHOLD=$ZRAM_EMERGENCY_SOME_AVG10_THRESHOLD
ZRAM_EMERGENCY_FULL_AVG10_THRESHOLD=$ZRAM_EMERGENCY_FULL_AVG10_THRESHOLD
ZRAM_PRESSURE_ENABLE=$ZRAM_PRESSURE_ENABLE
ZRAM_MIN_FREE_MEMORY=${ZRAM_MIN_FREE_MEMORY:-0}
ZRAM_WRITEBACK_MIN_REMAINING_PAGES=$ZRAM_WRITEBACK_MIN_REMAINING_PAGES
ZRAM_DAEMON_ENABLE=$ZRAM_DAEMON_ENABLE
ZRAM_DAEMON_PSI_WINDOW_US=$ZRAM_DAEMON_PSI_WINDOW_US
ZRAM_DAEMON_PSI_WINDOW_MIN_US=$ZRAM_DAEMON_PSI_WINDOW_MIN_US
ZRAM_DAEMON_PSI_WINDOW_MAX_US=$ZRAM_DAEMON_PSI_WINDOW_MAX_US
ZRAM_DAEMON_PSI_SOME_STALL_US=$ZRAM_DAEMON_PSI_SOME_STALL_US
ZRAM_DAEMON_PSI_FULL_STALL_US=$ZRAM_DAEMON_PSI_FULL_STALL_US
ZRAM_DAEMON_POLL_TIMEOUT_SEC=$ZRAM_DAEMON_POLL_TIMEOUT_SEC
ZRAM_DAEMON_PRESSURE_COOLDOWN_SEC=$ZRAM_DAEMON_PRESSURE_COOLDOWN_SEC
ZRAM_DAEMON_EMERGENCY_COOLDOWN_SEC=$ZRAM_DAEMON_EMERGENCY_COOLDOWN_SEC
ZRAM_DAEMON_RECOVERY_HYSTERESIS_SEC=$ZRAM_DAEMON_RECOVERY_HYSTERESIS_SEC
ZRAM_DAEMON_SECONDS_MAX=$ZRAM_DAEMON_SECONDS_MAX
ZRAM_IDLE_WRITEBACK_ENABLE=$ZRAM_IDLE_WRITEBACK_ENABLE
ZRAM_COLD_TIER_ENABLE=$ZRAM_COLD_TIER_ENABLE
ZRAM_COLD_TIER_RECOMPRESS_ENABLE=$ZRAM_COLD_TIER_RECOMPRESS_ENABLE
ZRAM_COLD_TIER_WRITEBACK_ENABLE=$ZRAM_COLD_TIER_WRITEBACK_ENABLE
ZRAM_COLD_TIER_COMPACT_ENABLE=$ZRAM_COLD_TIER_COMPACT_ENABLE
ZRAM_COLD_TIER_MIN_ZRAM_FILL_PCT=$ZRAM_COLD_TIER_MIN_ZRAM_FILL_PCT
ZRAM_COLD_TIER_MIN_COLD_PAGES=$ZRAM_COLD_TIER_MIN_COLD_PAGES
ZRAM_COLD_TIER_MIN_IDLE_PAGES=$ZRAM_COLD_TIER_MIN_IDLE_PAGES
ZRAM_COLD_TIER_MIN_HUGE_IDLE_PAGES=$ZRAM_COLD_TIER_MIN_HUGE_IDLE_PAGES
ZRAM_COLD_TIER_MIN_HUGE_PAGES=$ZRAM_COLD_TIER_MIN_HUGE_PAGES
ZRAM_COLD_TIER_MIN_INCOMPRESSIBLE_PAGES=$ZRAM_COLD_TIER_MIN_INCOMPRESSIBLE_PAGES
ZRAM_COLD_TIER_RECOMPRESS_IDLE_MAX_PAGES=$ZRAM_COLD_TIER_RECOMPRESS_IDLE_MAX_PAGES
ZRAM_COLD_TIER_RECOMPRESS_HUGE_IDLE_MAX_PAGES=$ZRAM_COLD_TIER_RECOMPRESS_HUGE_IDLE_MAX_PAGES
ZRAM_COLD_TIER_RECOMPRESS_HUGE_MAX_PAGES=$ZRAM_COLD_TIER_RECOMPRESS_HUGE_MAX_PAGES
ZRAM_COLD_TIER_WRITEBACK_INCOMPRESSIBLE_MAX_PAGES=$ZRAM_COLD_TIER_WRITEBACK_INCOMPRESSIBLE_MAX_PAGES
ZRAM_COLD_TIER_WRITEBACK_SPEC_CHUNK_PAGE_LIMIT=$ZRAM_COLD_TIER_WRITEBACK_SPEC_CHUNK_PAGE_LIMIT
ZRAM_MAINTENANCE_PAGE_INDEXES=$ZRAM_MAINTENANCE_PAGE_INDEXES
ZRAM_PCT=$ZRAM_PCT
ZRAM_MIN_MIB=$ZRAM_MIN_MIB
ZRAM_MAX_MIB=$ZRAM_MAX_MIB
ZRAM_MEM_LIMIT_PCT=$ZRAM_MEM_LIMIT_PCT
ZRAM_WRITEBACK_LIMIT_PCT=$ZRAM_WRITEBACK_LIMIT_PCT
ZRAM_POLICY_CONFIG=$zram_policy_config
CPU_CRC32C_MODULE=${CPU_CRC32C_MODULE:-}
ZRAM_MAINTENANCE_IO_WRITE_BANDWIDTH_MAX=$ZRAM_MAINTENANCE_IO_WRITE_BANDWIDTH_MAX
ZRAM_MAINTENANCE_MEMORY_HIGH=$ZRAM_MAINTENANCE_MEMORY_HIGH
ZRAM_MAINTENANCE_MEMORY_MAX=$ZRAM_MAINTENANCE_MEMORY_MAX
ZRAM_IDLE_WRITEBACK_INTERVAL=$ZRAM_IDLE_WRITEBACK_INTERVAL
ZRAM_IDLE_WRITEBACK_RANDOMIZED_DELAY=$ZRAM_IDLE_WRITEBACK_RANDOMIZED_DELAY
ZRAM_COLD_TIER_INTERVAL=$ZRAM_COLD_TIER_INTERVAL
ZRAM_COLD_TIER_RANDOMIZED_DELAY=$ZRAM_COLD_TIER_RANDOMIZED_DELAY
SYSCTL_PROFILE_BALANCED_SWAPPINESS=$SYSCTL_PROFILE_BALANCED_SWAPPINESS
SYSCTL_PROFILE_BALANCED_VFS_CACHE_PRESSURE=$SYSCTL_PROFILE_BALANCED_VFS_CACHE_PRESSURE
SYSCTL_PROFILE_BALANCED_WATERMARK_SCALE_FACTOR=$SYSCTL_PROFILE_BALANCED_WATERMARK_SCALE_FACTOR
SYSCTL_PROFILE_BALANCED_COMPACTION_PROACTIVENESS=$SYSCTL_PROFILE_BALANCED_COMPACTION_PROACTIVENESS
SYSCTL_PROFILE_BALANCED_DIRTY_BACKGROUND_BYTES=$SYSCTL_PROFILE_BALANCED_DIRTY_BACKGROUND_BYTES
SYSCTL_PROFILE_BALANCED_DIRTY_BYTES=$SYSCTL_PROFILE_BALANCED_DIRTY_BYTES
SYSCTL_PROFILE_BALANCED_DIRTY_EXPIRE_CENTISECS=$SYSCTL_PROFILE_BALANCED_DIRTY_EXPIRE_CENTISECS
SYSCTL_PROFILE_BALANCED_DIRTY_WRITEBACK_CENTISECS=$SYSCTL_PROFILE_BALANCED_DIRTY_WRITEBACK_CENTISECS
SYSCTL_PROFILE_HARDENED_SWAPPINESS=$SYSCTL_PROFILE_HARDENED_SWAPPINESS
SYSCTL_PROFILE_HARDENED_VFS_CACHE_PRESSURE=$SYSCTL_PROFILE_HARDENED_VFS_CACHE_PRESSURE
SYSCTL_PROFILE_HARDENED_WATERMARK_SCALE_FACTOR=$SYSCTL_PROFILE_HARDENED_WATERMARK_SCALE_FACTOR
SYSCTL_PROFILE_HARDENED_COMPACTION_PROACTIVENESS=$SYSCTL_PROFILE_HARDENED_COMPACTION_PROACTIVENESS
SYSCTL_PROFILE_HARDENED_DIRTY_BACKGROUND_BYTES=$SYSCTL_PROFILE_HARDENED_DIRTY_BACKGROUND_BYTES
SYSCTL_PROFILE_HARDENED_DIRTY_BYTES=$SYSCTL_PROFILE_HARDENED_DIRTY_BYTES
SYSCTL_PROFILE_HARDENED_DIRTY_EXPIRE_CENTISECS=$SYSCTL_PROFILE_HARDENED_DIRTY_EXPIRE_CENTISECS
SYSCTL_PROFILE_HARDENED_DIRTY_WRITEBACK_CENTISECS=$SYSCTL_PROFILE_HARDENED_DIRTY_WRITEBACK_CENTISECS
SYSCTL_PROFILE_PERFORMANCE_SWAPPINESS=$SYSCTL_PROFILE_PERFORMANCE_SWAPPINESS
SYSCTL_PROFILE_PERFORMANCE_VFS_CACHE_PRESSURE=$SYSCTL_PROFILE_PERFORMANCE_VFS_CACHE_PRESSURE
SYSCTL_PROFILE_PERFORMANCE_WATERMARK_SCALE_FACTOR=$SYSCTL_PROFILE_PERFORMANCE_WATERMARK_SCALE_FACTOR
SYSCTL_PROFILE_PERFORMANCE_COMPACTION_PROACTIVENESS=$SYSCTL_PROFILE_PERFORMANCE_COMPACTION_PROACTIVENESS
SYSCTL_PROFILE_PERFORMANCE_DIRTY_BACKGROUND_BYTES=$SYSCTL_PROFILE_PERFORMANCE_DIRTY_BACKGROUND_BYTES
SYSCTL_PROFILE_PERFORMANCE_DIRTY_BYTES=$SYSCTL_PROFILE_PERFORMANCE_DIRTY_BYTES
SYSCTL_PROFILE_PERFORMANCE_DIRTY_EXPIRE_CENTISECS=$SYSCTL_PROFILE_PERFORMANCE_DIRTY_EXPIRE_CENTISECS
SYSCTL_PROFILE_PERFORMANCE_DIRTY_WRITEBACK_CENTISECS=$SYSCTL_PROFILE_PERFORMANCE_DIRTY_WRITEBACK_CENTISECS
EOF
}

# Module lists are blocks, not scalar NAME=value records. Passing newline
# lists through the scalar map used to keep only the first module silently.
render_target_module_placeholders() (
  module_file=$1
  module_tmp="${module_file}.modules.$$"
  INITRAMFS_PLATFORM_MODULES=${INITRAMFS_PLATFORM_MODULES:-}
  GRAPHICS_INITRAMFS_MODULES=${GRAPHICS_INITRAMFS_MODULES:-}
  VFIO_INITRAMFS_MODULES=${VFIO_INITRAMFS_MODULES:-}
  VIRT_HOST_INITRAMFS_MODULES=${VIRT_HOST_INITRAMFS_MODULES:-}
  export INITRAMFS_PLATFORM_MODULES GRAPHICS_INITRAMFS_MODULES
  export VFIO_INITRAMFS_MODULES VIRT_HOST_INITRAMFS_MODULES
  if ! LC_ALL=C awk '
    BEGIN {
      split("INITRAMFS_PLATFORM_MODULES GRAPHICS_INITRAMFS_MODULES VFIO_INITRAMFS_MODULES VIRT_HOST_INITRAMFS_MODULES", names, " ")
      for (i in names) {
        name = names[i]
        blocks[name] = ""
        count = split(ENVIRON[name], modules, /[[:space:]]+/)
        for (j = 1; j <= count; j++) {
          module = modules[j]
          if (module == "") continue
          if (module !~ /^[A-Za-z0-9_][A-Za-z0-9_-]*$/) {
            print "fatal: invalid module name in " name > "/dev/stderr"
            exit 1
          }
          if (!seen[name SUBSEP module]++)
            blocks[name] = blocks[name] module "\n"
        }
      }
    }
    {
      token = $0
      sub(/^[[:space:]]*/, "", token)
      sub(/[[:space:]]*$/, "", token)
      for (name in blocks) {
        if (token == "__INSTALLER_" name "__" || token == "__" name "__") {
          printf "%s", blocks[name]
          next
        }
      }
      print
    }
  ' "$module_file" >"$module_tmp"; then
    rm -f "$module_tmp"
    return 1
  fi
  mv "$module_tmp" "$module_file"
)

# A single literal-substitution pass avoids hundreds of sed processes per asset.
# Values are never evaluated as shell, regular expressions, or awk replacements.
render_target_scalar_placeholders() (
  scalar_file=$1
  scalar_map=$2
  scalar_tmp="${scalar_file}.scalars.$$"
  if ! LC_ALL=C awk -v map_path="$scalar_map" '
    BEGIN {
      while ((status = getline record < map_path) > 0) {
        separator = index(record, "=")
        if (!separator) {
          print "fatal: malformed scalar placeholder record" > "/dev/stderr"
          exit 1
        }
        name = substr(record, 1, separator - 1)
        if (name !~ /^[A-Z_][A-Z0-9_]*$/) {
          print "fatal: invalid scalar placeholder name" > "/dev/stderr"
          exit 1
        }
        value = substr(record, separator + 1)
        values["__INSTALLER_" name "__"] = value
        values["__" name "__"] = value
      }
      if (status < 0) exit 1
      close(map_path)
    }
    {
      rest = $0
      output = ""
      while (match(rest, /__/)) {
        output = output substr(rest, 1, RSTART - 1)
        rest = substr(rest, RSTART)
        selected = ""
        for (token in values)
          if (index(rest, token) == 1 && length(token) > length(selected)) selected = token
        if (selected != "") {
          output = output values[selected]
          rest = substr(rest, length(selected) + 1)
        } else {
          output = output "__"
          rest = substr(rest, 3)
        }
      }
      print output rest
    }
  ' "$scalar_file" >"$scalar_tmp"; then
    rm -f "$scalar_tmp"
    return 1
  fi
  mv "$scalar_tmp" "$scalar_file"
)

_render_target_template_in_place() {
  src=$1
  dest=$2
  mode=$3
  dest_parent=$(dirname "$dest")
  map_tmp="${TMP_ENV_DIR}/template-placeholder-map.$$.tmp"
  [ -d "$dest_parent" ] || install -d -m 0755 "$dest_parent"
  cp "$src" "$dest" || return 1
  render_target_module_placeholders "$dest" || return 1
  if ! render_target_template_placeholder_map >"$map_tmp"; then
    rm -f "$map_tmp"
    installer_fatal "failed to render template placeholder map for ${dest}"
  fi
  if ! render_target_scalar_placeholders "$dest" "$map_tmp"; then
    rm -f "$map_tmp"
    installer_fatal "failed to render scalar placeholders into ${dest}"
  fi
  rm -f "$map_tmp"
  apply_tmpfs_policy_placeholders "$dest" || return 1
  apply_tmpfs_pre_clean_placeholders "$dest" || return 1
  apply_apt_refresh_placeholders "$dest" || return 1
  apply_sysctl_profile_placeholders "$dest" || return 1
  installer_assert_no_unresolved_installer_placeholders "$dest" "rendered template ${src}" || return 1
  chmod "$mode" "$dest"
}

# Direct renderer callers get the same atomic publication guarantee as assets.
render_target_template() (
  set -eu
  umask 077
  template_source=$1
  template_destination=$2
  template_mode=$3
  template_parent=$(dirname "$template_destination")
  [ -d "$template_parent" ] || install -d -m 0755 "$template_parent" || exit 1
  [ ! -d "$template_destination" ] || exit 1
  template_work=$(mktemp -d "$template_parent/.installer-render.XXXXXX") || exit 1
  trap 'rm -rf -- "$template_work"' EXIT
  trap 'exit 129' HUP
  trap 'exit 130' INT
  trap 'exit 143' TERM
  # Isolate the legacy renderer's shell variables and all of its scratch files.
  (TMP_ENV_DIR=$template_work; _render_target_template_in_place "$template_source" "$template_work/payload" "$template_mode") || exit 1
  mv -fT -- "$template_work/payload" "$template_destination" || exit 1
)


# This allowlist is intentionally limited to managed resource-policy assets.
# Existing zram/Podman policies and the generic renderer remain independent.
# Values are data: indirect variable names below are literal, never user input.
systemd_journal_policy_map() (
  set -eu
  case "${SYSTEMD_JOURNAL_VOLATILE_ENABLE-}" in
    true) journal_storage=volatile ;;
    false) journal_storage=persistent ;;
    *) installer_fatal "SYSTEMD_JOURNAL_VOLATILE_ENABLE must be true or false"; exit 1 ;;
  esac
  printf 'SYSTEMD_JOURNAL_STORAGE=%s\n' "$journal_storage"
  case "${TMPFS_VAR_LOG-}" in
    true) journal_seal=no ;;
    false) [ "$journal_storage" = persistent ] && journal_seal=yes || journal_seal=no ;;
    *) installer_fatal "TMPFS_VAR_LOG must be true or false"; exit 1 ;;
  esac
  printf 'SYSTEMD_JOURNAL_SEAL=%s\n' "$journal_seal"

)

systemd_resource_placeholder_map() (
  set -eu
  systemd_journal_policy_map || exit 1
  case "${SYSTEMD_DEFAULT_IOACCOUNTING_ENABLE-}" in
    true) io_accounting=yes ;;
    false) io_accounting=no ;;
    *) installer_fatal "SYSTEMD_DEFAULT_IOACCOUNTING_ENABLE must be true or false"; exit 1 ;;
  esac
  case "${SYSTEMD_IOWEIGHT_ENABLE-}" in
    true|false) ;;
    *) installer_fatal "SYSTEMD_IOWEIGHT_ENABLE must be true or false"; exit 1 ;;
  esac
  printf 'SYSTEMD_DEFAULT_IOACCOUNTING_ENABLE=%s\n' "$io_accounting"
  for name in \
    SYSTEMD_IOWEIGHT_HOME_USER_SESSION_SLICE_D \
    SYSTEMD_IOWEIGHT_HOME_USER_APP_SLICE_D \
    SYSTEMD_IOWEIGHT_HOME_USER_BACKGROUND_SLICE_D \
    SYSTEMD_IOWEIGHT_HOME_USER_LABWC_COMPOSITOR_SERVICE_D \
    SYSTEMD_IOWEIGHT_SYSTEM_MAINTENANCE_SLICE_D \
    SYSTEMD_IOWEIGHT_SYSTEM_BACKGROUND_SLICE_D
  do
    eval 'present=${'"$name"'+yes}'
    [ "$present" = yes ] || { installer_fatal "$name must be defined (empty is allowed)"; exit 1; }
    eval 'value=${'"$name"'-}'
    case "$value" in
      '') ;;
      IOWeight=*)
        number=${value#IOWeight=}
        case "$number" in ''|*[!0-9]*|0*)
          installer_fatal "$name must be empty or IOWeight=1..10000"; exit 1 ;;
        esac
        [ "${#number}" -le 5 ] && [ "$number" -le 10000 ] || {
          installer_fatal "$name must be empty or IOWeight=1..10000"; exit 1;
        }
        ;;
      *) installer_fatal "$name must be empty or IOWeight=1..10000"; exit 1 ;;
    esac
    [ "$SYSTEMD_IOWEIGHT_ENABLE" = true ] || value=
    printf '%s=%s\n' "$name" "$value"
  done
  # CPU preference is independent of both I/O accounting and I/O weighting.
  case "${SYSTEMD_CPUWEIGHT_ENABLE-}" in
    true|false) ;;
    *) installer_fatal "SYSTEMD_CPUWEIGHT_ENABLE must be true or false"; exit 1 ;;
  esac
  for name in \
    SYSTEMD_CPUWEIGHT_HOME_USER_SESSION_SLICE_D \
    SYSTEMD_CPUWEIGHT_HOME_USER_APP_SLICE_D \
    SYSTEMD_CPUWEIGHT_HOME_USER_BACKGROUND_SLICE_D \
    SYSTEMD_CPUWEIGHT_HOME_USER_LABWC_COMPOSITOR_SERVICE_D \
    SYSTEMD_CPUWEIGHT_USER_AUDIO_SERVICE_D \
    SYSTEMD_CPUWEIGHT_SYSTEM_MAINTENANCE_SLICE_D \
    SYSTEMD_CPUWEIGHT_SYSTEM_BACKGROUND_SLICE_D
  do
    eval 'present=${'"$name"'+yes}'
    [ "$present" = yes ] || { installer_fatal "$name must be defined (empty is allowed)"; exit 1; }
    eval 'value=${'"$name"'-}'
    case "$value" in
      '') ;;
      CPUWeight=*)
        number=${value#CPUWeight=}
        case "$number" in ''|*[!0-9]*|0*)
          installer_fatal "$name must be empty or CPUWeight=1..10000"; exit 1 ;;
        esac
        [ "${#number}" -le 5 ] && [ "$number" -le 10000 ] || {
          installer_fatal "$name must be empty or CPUWeight=1..10000"; exit 1;
        }
        ;;
      *) installer_fatal "$name must be empty or CPUWeight=1..10000"; exit 1 ;;
    esac
    [ "$SYSTEMD_CPUWEIGHT_ENABLE" = true ] || value=
    printf '%s=%s\n' "$name" "$value"
  done
  for name in \
    SYSTEMD_COREDUMP_POLL_LIMIT_INTERVAL_SEC \
    SYSTEMD_COREDUMP_POLL_LIMIT_BURST
  do
    eval 'value=${'"$name"'-}'
    # Bound integer input before numeric comparisons (also on 32-bit shells).
    case "$name" in
      SYSTEMD_COREDUMP_POLL_LIMIT_INTERVAL_SEC) minimum=2; maximum=60 ;;
      SYSTEMD_COREDUMP_POLL_LIMIT_BURST) minimum=1; maximum=1000000 ;;
    esac
    case "$value" in ''|*[!0-9]*|0*)
      installer_fatal "$name must be an integer from $minimum to $maximum"; exit 1 ;;
    esac
    [ "${#value}" -le 7 ] && [ "$value" -ge "$minimum" ] && [ "$value" -le "$maximum" ] || {
      installer_fatal "$name must be an integer from $minimum to $maximum"; exit 1;
    }
    printf '%s=%s\n' "$name" "$value"
  done
  case "${SYSTEMD_COREDUMP_STORAGE-}" in
    external|none) printf 'SYSTEMD_COREDUMP_STORAGE=%s\n' "$SYSTEMD_COREDUMP_STORAGE" ;;
    *) installer_fatal "SYSTEMD_COREDUMP_STORAGE must be external or none"; exit 1 ;;
  esac
  for name in \
    SYSTEMD_COREDUMP_PROCESS_SIZE_MAX \
    SYSTEMD_COREDUMP_EXTERNAL_SIZE_MAX \
    SYSTEMD_COREDUMP_MAX_USE \
    SYSTEMD_COREDUMP_KEEP_FREE \
    SYSTEMD_JOURNAL_SYSTEM_MAX_USE \
    SYSTEMD_JOURNAL_SYSTEM_KEEP_FREE \
    SYSTEMD_JOURNAL_SYSTEM_MAX_FILE_SIZE \
    SYSTEMD_JOURNAL_RUNTIME_MAX_USE \
    SYSTEMD_JOURNAL_RUNTIME_KEEP_FREE \
    SYSTEMD_JOURNAL_RUNTIME_MAX_FILE_SIZE
  do
    eval 'value=${'"$name"'-}'
    # Single-line bounded subset of systemd's size grammar; no signs, shell
    # expansions, whitespace, ambiguous leading zeroes or unbounded sizes.
    case "$value" in ''|*[!0-9BKMG]*)
      installer_fatal "$name must be a bounded size (bytes or B/K/M/G)"; exit 1 ;;
    esac
    printf '%s\n' "$value" | LC_ALL=C grep -Eq '^(0|[1-9][0-9]{0,8}[BKMG]?)$' || {
      installer_fatal "$name must be a bounded size (bytes or B/K/M/G)"; exit 1;
    }
    case "$name:$value" in
      SYSTEMD_COREDUMP_PROCESS_SIZE_MAX:0|SYSTEMD_COREDUMP_EXTERNAL_SIZE_MAX:0) ;;
      *:0) installer_fatal "$name must be nonzero"; exit 1 ;;
    esac
    printf '%s=%s\n' "$name" "$value"
  done
  for name in SYSTEMD_JOURNAL_SYSTEM_MAX_FILES SYSTEMD_JOURNAL_RUNTIME_MAX_FILES; do
    eval 'value=${'"$name"'-}'
    case "$value" in ''|*[!0-9]*|0*)
      installer_fatal "$name must be an integer from 1 to 1000000"; exit 1 ;;
    esac
    [ "${#value}" -le 7 ] && [ "$value" -le 1000000 ] || {
      installer_fatal "$name must be an integer from 1 to 1000000"; exit 1;
    }
    printf '%s=%s\n' "$name" "$value"
  done
)

apply_systemd_resource_placeholders() (
  set -eu
  resource_file=$1
  # Even literal resource assets obey the weight switch. This helper remains
  # opt-in: original zram/Podman assets never pass through this renderer.
  case "${SYSTEMD_IOWEIGHT_ENABLE-}" in
    true|false) ;;
    *) installer_fatal "SYSTEMD_IOWEIGHT_ENABLE must be true or false"; exit 1 ;;
  esac
  case "${SYSTEMD_CPUWEIGHT_ENABLE-}" in
    true|false) ;;
    *) installer_fatal "SYSTEMD_CPUWEIGHT_ENABLE must be true or false"; exit 1 ;;
  esac
  case "${SYSTEMD_DEFAULT_IOACCOUNTING_ENABLE-}" in
    true|false) ;;
    *) installer_fatal "SYSTEMD_DEFAULT_IOACCOUNTING_ENABLE must be true or false"; exit 1 ;;
  esac
  resource_has_tokens=false
  if grep -Eq '__(INSTALLER_)?SYSTEMD_[A-Z0-9_]+__' "$resource_file"; then
    resource_has_tokens=true
  elif { [ "$SYSTEMD_IOWEIGHT_ENABLE" = true ] ||
         ! grep -Eq '^[[:space:]]*(Startup)?IOWeight[[:space:]]*=' "$resource_file"; } &&
       { [ "$SYSTEMD_CPUWEIGHT_ENABLE" = true ] ||
         ! grep -Eq '^[[:space:]]*(Startup)?CPUWeight[[:space:]]*=' "$resource_file"; }; then
    # Class-only/security files need no map or rewrite after switch validation.
    exit 0
  fi
  resource_map=$(mktemp "${TMP_ENV_DIR}/systemd-resource-map.XXXXXX") || exit 1
  trap 'rm -f -- "$resource_map" "${resource_map}.filtered"' EXIT
  trap 'exit 129' HUP
  trap 'exit 130' INT
  trap 'exit 143' TERM
  if [ "$resource_has_tokens" = true ]; then
    systemd_resource_placeholder_map >"$resource_map" || exit 1
    render_target_scalar_placeholders "$resource_file" "$resource_map" || exit 1
  fi
  if grep -Eq '__(INSTALLER_)?SYSTEMD_[A-Z0-9_]+__' "$resource_file"; then
    installer_fatal "unresolved systemd resource placeholder in $resource_file"; exit 1
  fi
  for controller in IO CPU; do
    case "$controller" in
      IO) weight_enabled=$SYSTEMD_IOWEIGHT_ENABLE ;;
      CPU) weight_enabled=$SYSTEMD_CPUWEIGHT_ENABLE ;;
    esac
    [ "$weight_enabled" = false ] || continue
    # Omit complete directives. Never emit an empty assignment or weight zero.
    LC_ALL=C awk -v controller="$controller" '
      $0 !~ ("^[[:space:]]*(Startup)?" controller "Weight[[:space:]]*=")
    ' "$resource_file" >"${resource_map}.filtered" || exit 1
    cat "${resource_map}.filtered" >"$resource_file" || exit 1
    rm -f -- "${resource_map}.filtered"
    if grep -Eq "^[[:space:]]*(Startup)?${controller}Weight[[:space:]]*=" "$resource_file"; then
      installer_fatal "disabled $controller weight policy left a directive in $resource_file"; exit 1
    fi
  done
)
