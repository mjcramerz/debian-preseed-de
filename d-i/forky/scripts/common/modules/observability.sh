#!/bin/sh
# Sourced installer module; edit this file directly.

installer_log_required_files() {
  printf '%s\n' installer.log
}

installer_ensure_log_files() {
  log_file=$(installer_runtime_log_file)
  log_dir=$(dirname "$log_file")
  [ -d "$log_dir" ] || install -d -m 0700 "$log_dir"
  : >>"$log_file"
  chmod 0600 "$log_file" 2>/dev/null || true
}

installer_prepare_target_log_dirs() {
  installer_target_is_mounted || return 0
  install -d -m 0700 "$(installer_target_log_root_dir)"
}

installer_missing_log_record() {
  log_name=$1
  category=${log_name#*-}
  category=${category%.log}
  case "$category" in
    packages) category=package ;;
    *) ;;
  esac
  stage=$(installer_log_stage_for_category "$category")

  installer_log_should_emit warning || return 0
  printf '%s stage=%s level=warning component=log-archive log_file=%s status=not-created message=%s\n' \
    "$(installer_log_timestamp)" \
    "$stage" \
    "$log_name" \
    "stage did not emit installer log records before final archive"
}

installer_log_redacted_cmdline() {
  redacted_cmdline=
  for cmdline_arg in $(installer_cmdline); do
    case "$cmdline_arg" in
      primary_gpg_passphrase=*|fruux_username=*|fruux_password=*|obs_username=*|telegram_chat_id=*|netcfg/wireless_wpa=*|wireless_wpa=*|wifi_wpa=*|*[Pp][Aa][Ss][Ss]*=*|*[Ss][Ee][Cc][Rr][Ee][Tt]*=*|*[Tt][Oo][Kk][Ee][Nn]*=*|*[Kk][Ee][Yy]*=*)
        cmdline_arg=${cmdline_arg%%=*}=REDACTED
        ;;
    esac
    redacted_cmdline="${redacted_cmdline:+$redacted_cmdline }$cmdline_arg"
  done
  printf '%s\n' "$redacted_cmdline"
}

installer_log_boot_context() {
  installer_ensure_log_files
  installer_append_log_category boot boot info boot "kernel_cmdline=$(installer_log_redacted_cmdline)"
  installer_append_log_category boot boot info boot "kernel_release=$(uname -r 2>/dev/null || printf unknown)"
  installer_append_log_category boot boot info boot "machine=$(uname -m 2>/dev/null || printf unknown)"
  if [ -d /sys/firmware/efi ]; then
    installer_append_log_category boot boot info boot "boot_mode=UEFI"
  else
    installer_append_log_category boot boot info boot "boot_mode=BIOS"
  fi
  if [ -r /etc/debian_version ]; then
    installer_append_log_category boot boot info boot "installer_debian_version=$(cat /etc/debian_version 2>/dev/null || printf unknown)"
  fi
  if [ -n "${INSTALLER_SELECTED_CLASS_REFS:-}" ]; then
    installer_append_log_category boot boot info classes "selected=${INSTALLER_SELECTED_CLASS_REFS}"
  fi
  if [ -n "${INSTALLER_HOST_PROFILE:-}" ]; then
    installer_append_log_category boot boot info classes "host_profile=${INSTALLER_HOST_PROFILE} host_family=${INSTALLER_HOST_FAMILY:-unset} hook_family=${INSTALLER_HOOK_FAMILY:-unset}"
  fi
}

installer_log_network_context() {
  installer_ensure_log_files
  installer_append_log_category network network_configured info network "hostname=$(hostname 2>/dev/null || printf unknown)"
  if command -v ip >/dev/null 2>&1; then
    ip -o link show 2>/dev/null | while IFS= read -r line || [ -n "$line" ]; do
      [ -n "$line" ] || continue
      installer_append_log_category network network_configured info link "$line"
    done
    ip -o addr show 2>/dev/null | while IFS= read -r line || [ -n "$line" ]; do
      [ -n "$line" ] || continue
      installer_append_log_category network network_configured info address "$line"
    done
    ip route show 2>/dev/null | while IFS= read -r line || [ -n "$line" ]; do
      [ -n "$line" ] || continue
      installer_append_log_category network network_configured info route "$line"
    done
  fi
  if [ -r /etc/resolv.conf ]; then
    while IFS=' ' read -r resolver_key nameserver _resolver_rest || [ -n "${resolver_key:-}" ]; do
      [ "$resolver_key" = "nameserver" ] || continue
      [ -n "$nameserver" ] || continue
      installer_append_log_category network network_configured info dns "nameserver=${nameserver}"
    done </etc/resolv.conf
  fi
}

installer_log_disk_context() {
  installer_ensure_log_files
  for disk_sys_path in /sys/block/*; do
    [ -d "$disk_sys_path" ] || continue
    disk_name=${disk_sys_path##*/}
    case "$disk_name" in
      loop*|ram*|dm-*|md*) continue ;;
    esac
    disk_size=$(cat "$disk_sys_path/size" 2>/dev/null || printf unknown)
    disk_removable=$(cat "$disk_sys_path/removable" 2>/dev/null || printf unknown)
    disk_model=$(cat "$disk_sys_path/device/model" 2>/dev/null || printf unknown)
    disk_serial=$(cat "$disk_sys_path/device/serial" 2>/dev/null || printf unknown)
    installer_append_log_category disk disk_discovery info disk "device=/dev/${disk_name} sectors=${disk_size} removable=${disk_removable} model=${disk_model} serial=${disk_serial}"
  done
  if [ -n "${DEV_INSTALL_DISK:-}" ]; then
    installer_append_log_category disk disk_discovery info selected "install_disk=${DEV_INSTALL_DISK}"
  fi
}

installer_log_preseed_context() {
  installer_ensure_log_files
  installer_append_log_category preseed preseed_loaded info preseed "timestamp=$(installer_log_timestamp)"
  installer_append_log_category preseed preseed_loaded info preseed "seed_source=${INSTALLER_SEED_BASE:-${SEED_BASE:-unknown}}"
  installer_append_log_category preseed preseed_loaded info preseed "hostname=${SYSTEM_HOSTNAME:-$(hostname 2>/dev/null || printf unknown)}"
  if command -v ip >/dev/null 2>&1; then
    ip -o addr show scope global 2>/dev/null | while IFS= read -r line || [ -n "$line" ]; do
      [ -n "$line" ] || continue
      installer_append_log_category preseed preseed_loaded info address "$line"
    done
  fi
}

installer_log_category_for_target_command() {
  target_label=$1
  case "$target_label" in
    *apt\ metadata*|*APT\ metadata*|*apt\ preferences*|*APT\ preferences*|*apt\ work*|*APT\ work*)
      printf '%s\n' apt
      return 0
      ;;
    *package*|*Package*|*pkgsel*|*dpkg*|*DKMS*|*dkms*)
      printf '%s\n' package
      return 0
      ;;
    *apt*|*APT*)
      printf '%s\n' apt
      return 0
      ;;
    *GRUB*|*grub*|*Secure\ Boot*|*boot*|*Boot*|*EFI*|*efi*|*shim*|*MOK*|*mok*|*kernel*|*Kernel*|*initramfs*)
      printf '%s\n' bootloader
      return 0
      ;;
    *Labwc*|*labwc*|*desktop*|*Desktop*|*greetd*|*waybar*|*fuzzel*|*mako*|*kanshi*|*thunar*)
      printf '%s\n' desktop
      return 0
      ;;
  esac
  return 1
}

installer_log_target_command_output() {
  category=$1
  stage=$2
  component=$3
  output_file=$4
  output_level=$(installer_log_level_canonical "${5:-info}")

  [ -s "$output_file" ] || return 0

  max_lines=${INSTALLER_COMMAND_LOG_MAX_LINES:-80}
  case "$max_lines" in
    ''|*[!0-9]*) max_lines=80 ;;
  esac
  [ "$max_lines" -gt 0 ] || return 0

  output_lines=$(wc -l <"$output_file" 2>/dev/null || printf '0')
  output_lines=${output_lines##* }
  case "$output_lines" in
    ''|*[!0-9]*) output_lines=0 ;;
  esac

  source_stream=$output_file
  temp_stream=
  if [ "$output_lines" -gt "$max_lines" ] && command -v tail >/dev/null 2>&1; then
    installer_append_log_category "$category" "$stage" "$output_level" "$component" "output_truncated=true original_lines=${output_lines} kept_tail_lines=${max_lines}" || true
    temp_stream=$(installer_runtime_temp_log_path target-command-tail.log)
    tail -n "$max_lines" "$output_file" >"$temp_stream" 2>/dev/null || {
      rm -f "$temp_stream"
      temp_stream=
    }
    [ -n "$temp_stream" ] && source_stream=$temp_stream
  fi

  installer_redact_log_stream <"$source_stream" | while IFS= read -r output_line || [ -n "$output_line" ]; do
    installer_append_log_category "$category" "$stage" "$output_level" "$component" "$output_line" || true
  done

  if [ -n "$temp_stream" ]; then
    rm -f "$temp_stream"
  fi
}

installer_live_log_max_bytes() {
  live_log_max_bytes=${INSTALLER_LIVE_LOG_MAX_BYTES:-4194304}
  case "$live_log_max_bytes" in
    ''|*[!0-9]*) live_log_max_bytes=4194304 ;;
  esac
  printf '%s\n' "$live_log_max_bytes"
}

installer_live_installer_log_files() {
  printf '%s\n' \
    /var/log/syslog \
    /var/log/messages \
    /var/log/partman \
    /var/log/debootstrap.log \
    /var/log/installer/syslog \
    /var/log/installer/partman \
    /var/log/installer/status \
    /var/log/installer/hardware-summary
}

installer_safe_log_filename() {
  printf '%s\n' "$1" | sed 's|^/||; s|/|_|g; s|[^A-Za-z0-9._-]|_|g'
}

installer_redact_log_stream() {
  sed \
    -e 's/\([Pp][Aa][Ss][Ss][^=[:space:]]*[= ][= ]*\)[^[:space:]]*/\1REDACTED/g' \
    -e 's/\([Ss][Ee][Cc][Rr][Ee][Tt][^=[:space:]]*[= ][= ]*\)[^[:space:]]*/\1REDACTED/g' \
    -e 's/\([Tt][Oo][Kk][Ee][Nn][^=[:space:]]*[= ][= ]*\)[^[:space:]]*/\1REDACTED/g' \
    -e 's/\([Tt][Ee][Ll][Ee][Gg][Rr][Aa][Mm]_[Aa][Pp][Ii]_[Kk][Ee][Yy][= ][= ]*\)[^[:space:]]*/\1REDACTED/g' \
    -e 's/\([Tt][Ee][Ll][Ee][Gg][Rr][Aa][Mm]_[Cc][Hh][Aa][Tt]_[Ii][Dd][= ][= ]*\)[^[:space:]]*/\1REDACTED/g' \
    -e 's/\([Ww][Pp][Aa][^=[:space:]]*[= ][= ]*\)[^[:space:]]*/\1REDACTED/g' \
    -e 's/[Pp][Rr][Ee][Ss][Ee][Ee][Dd]/installer/g'
}

installer_archive_live_installer_logs_to_target() {
  installer_logging_enabled || return 0
  target_log_dir=$(installer_target_log_dir)
  live_log_dir="${target_log_dir}/debian-installer"
  max_bytes=$(installer_live_log_max_bytes)

  installer_target_is_mounted || return 0
  install -d -m 0700 "$live_log_dir"

  while IFS= read -r live_log || [ -n "$live_log" ]; do
    [ -n "$live_log" ] || continue
    [ -s "$live_log" ] || continue
    safe_name=$(installer_safe_log_filename "$live_log")
    tmp_log="${live_log_dir}/${safe_name}.tmp.$$"
    dst_log="${live_log_dir}/${safe_name}"
    live_log_size=$(wc -c <"$live_log" 2>/dev/null | tr -d ' ' || printf '0')
    case "$live_log_size" in
      ''|*[!0-9]*) live_log_size=0 ;;
    esac

    if [ "$live_log_size" -gt "$max_bytes" ] && command -v tail >/dev/null 2>&1; then
      {
        printf '# truncated_to_last_bytes=%s original_bytes=%s source=%s\n' "$max_bytes" "$live_log_size" "$live_log"
        tail -c "$max_bytes" "$live_log"
      } | installer_redact_log_stream >"$tmp_log" 2>/dev/null || {
        rm -f "$tmp_log"
        installer_warn "failed to archive live installer log ${live_log}"
        continue
      }
    else
      installer_redact_log_stream <"$live_log" >"$tmp_log" 2>/dev/null || {
        rm -f "$tmp_log"
        installer_warn "failed to archive live installer log ${live_log}"
        continue
      }
    fi
    chmod 0600 "$tmp_log" 2>/dev/null || true
    mv "$tmp_log" "$dst_log"
  done <<EOF
$(installer_live_installer_log_files)
EOF
}

installer_archive_logs_to_target() {
  archive_mode=${1:-copy}
  runtime_log_file=$(installer_runtime_log_file)
  target_log_file=$(installer_target_log_file)

  case "$archive_mode" in
    copy|move) ;;
    *) archive_mode=copy ;;
  esac

  installer_target_is_mounted || return 0
  installer_ensure_log_files
  installer_prepare_target_log_dirs
  tmp_log="${target_log_file}.tmp.$$"

  if installer_redact_log_stream <"$runtime_log_file" >"$tmp_log" 2>/dev/null; then
    chmod 0600 "$tmp_log" 2>/dev/null || true
    mv "$tmp_log" "$target_log_file"
    [ "$archive_mode" = copy ] || rm -f "$runtime_log_file"
  else
    rm -f "$tmp_log"
    installer_warn "failed to archive ${runtime_log_file} to ${target_log_file}"
  fi
}

installer_random_hostname_suffix() {
  raw=$(LC_ALL=C tr -dc '0-9' </dev/urandom | dd bs=3 count=1 2>/dev/null || true)
  case "$raw" in
    [0-9][0-9][0-9]) printf '%s\n' "$raw" ;;
    *) installer_fatal "unable to generate hostname suffix" ;;
  esac
}

installer_ensure_system_identity() {
  : "${SYSTEM_PREFIX:?SYSTEM_PREFIX must be set}"
  : "${SYSTEM_DOMAIN:?SYSTEM_DOMAIN must be set}"
  case "$SYSTEM_PREFIX" in
    ''|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789]*)
      installer_fatal "SYSTEM_PREFIX must contain only ASCII letters and digits"
      ;;
  esac
  case "$SYSTEM_DOMAIN" in
    ''|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.-]*|.*|*.|*..*)
      installer_fatal "SYSTEM_DOMAIN must contain only hostname-safe labels"
      ;;
  esac
  if [ -z "${SYSTEM_HOSTNAME:-}" ]; then
    SYSTEM_HOSTNAME="${SYSTEM_PREFIX}-$(installer_random_hostname_suffix)"
  fi
  case "$SYSTEM_HOSTNAME" in
    "${SYSTEM_PREFIX}"-[0-9][0-9][0-9]) ;;
    *) installer_fatal "SYSTEM_HOSTNAME must match SYSTEM_PREFIX-###" ;;
  esac
}

