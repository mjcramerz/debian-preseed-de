#!/bin/sh
# Shared late_command storage maintenance helpers. This file is sourced, not executed.


repair_target_pkgsel_include_packages() {
  stage_target_apt_login_policy_assets
  require_in_target "pkgsel/include package repair"

  # shellcheck disable=SC2016
  missing_packages=$(capture_in_target "detect missing pkgsel/include packages" /bin/sh -c '
set -eu
packages=$1
[ -n "$packages" ] || exit 0
# One checked database read also accounts for virtual packages (for example
# mesa-utils-extra provided by mesa-utils). Do not call apt for an installed
# provider merely because the virtual name has no standalone dpkg record.
installed=$(dpkg-query -W -f="\${Status}\t\${binary:Package}\t\${Provides}\t\${Version}\n")
printf "%s\n" "$installed" | awk -F "\t" -v requested="$packages" '\''
$1 == "install ok installed" {
  present[$2] = 1; versions[$2] = $4
  name = $2; sub(/:.*/, "", name); present[name] = 1; versions[name] = $4
  n = split($3, providers, ",")
  for (i = 1; i <= n; i++) {
    name = providers[i]; sub(/^[ \t]+/, "", name); sub(/[ \t:(].*$/, "", name)
    if (name != "") present[name] = 1
  }
}
END {
  n = split(requested, pkgs, /[ \t\n]+/)
  for (i = 1; i <= n; i++) {
    name = pkgs[i]; sub(/\/.*/, "", name)
    count = split(name, wanted, "="); name = wanted[1]
    if (name != "" && (!(name in present) || (count == 2 && versions[name] != wanted[2]))) print pkgs[i]
  }
}'\''

' sh "${INSTALLER_PKGSEL_INCLUDE}")

  legacy_cuda_repair_active=false
  if command -v cuda_legacy_target_apt_required >/dev/null 2>&1 && cuda_legacy_target_apt_required; then
    legacy_cuda_repair_active=true
  fi

  repair_status=0
  cleanup_status=0
  if [ -n "$missing_packages" ]; then
    installer_warn "repairing missing pkgsel/include packages in target:${missing_packages:+ ${missing_packages}}"
    if [ "$legacy_cuda_repair_active" = true ]; then
      cuda_legacy_prepare_target_apt_state
    fi
    prepare_target_volatile_dirs_for_apt
    if refresh_non_cuda_target_metadata \
      env DEBIAN_FRONTEND=noninteractive DEBCONF_NONINTERACTIVE_SEEN=true \
      apt-get \
        -o APT::Get::List-Cleanup=0 \
        -o APT::Update::Error-Mode=any \
        -o Acquire::Retries=5 \
        -o Acquire::http::Timeout=45 \
        -o Acquire::https::Timeout=45 \
        -o Binary::apt::APT::Keep-Downloaded-Packages=false \
        -o DPkg::Use-Pty=0 \
        update
    then
      # shellcheck disable=SC2086
      set -- $missing_packages
      if ( run_in_target "install missing pkgsel/include packages" \
          env DEBIAN_FRONTEND=noninteractive DEBCONF_NONINTERACTIVE_SEEN=true \
          apt-get \
            -o Acquire::Retries=5 \
            -o Acquire::http::Timeout=45 \
            -o Acquire::https::Timeout=45 \
            -o Binary::apt::APT::Keep-Downloaded-Packages=false \
            -o DPkg::Use-Pty=0 \
            -y install --no-install-recommends --no-install-suggests "$@" )
      then
        :
      else
        repair_status=$?
      fi
    else
      repair_status=$?
    fi
  fi

  if [ "$legacy_cuda_repair_active" = true ]; then
    if cuda_legacy_cleanup_target_apt_state; then
      :
    else
      cleanup_status=$?
    fi
  fi

  [ "$repair_status" -eq 0 ] || return "$repair_status"
  [ "$cleanup_status" -eq 0 ] || return "$cleanup_status"
  [ -n "$missing_packages" ] || return 0
}

managed_target_policy_assets() {
  cat <<'EOF'
etc/apt/apt.conf.d/20auto-upgrades|/etc/apt/apt.conf.d/20auto-upgrades|0644
etc/apt/apt.conf.d/25no-pdiffs|/etc/apt/apt.conf.d/25no-pdiffs|0644
etc/apt/apt.conf.d/52unattended-upgrades|/etc/apt/apt.conf.d/52unattended-upgrades|0644
etc/apt/apt.conf.d/99noinstall-recommends|/etc/apt/apt.conf.d/99noinstall-recommends|0644
etc/login.defs|/etc/login.defs|0644
etc/pam.d/polkit-1|/etc/pam.d/polkit-1|0644
etc/pam.d/systemd-user|/etc/pam.d/systemd-user|0644
etc/systemd/system/apt-daily-upgrade.service.d/50-unattended-upgrades-notify.conf|/etc/systemd/system/apt-daily-upgrade.service.d/50-unattended-upgrades-notify.conf|0644
etc/systemd/system/fwupd.service.d/20-managed-upower-ordering.conf|/etc/systemd/system/fwupd.service.d/20-managed-upower-ordering.conf|0644
etc/systemd/system/unattended-upgrades.service.d/override.conf|/etc/systemd/system/unattended-upgrades.service.d/override.conf|0644
usr/local/libexec/unattended-upgrades-notify|/usr/local/libexec/unattended-upgrades-notify|0755
EOF
}

stage_target_apt_login_policy_assets() {
  while IFS='|' read -r repo_relpath target_path mode || [ -n "$repo_relpath" ]; do
    [ -n "$repo_relpath" ] || continue
    stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET "$repo_relpath")" "$target_path" "$mode"
  done <<EOF
$(managed_target_policy_assets)
EOF
}

stage_target_conditional_apt_refresh_assets() {
  if tmpfs_policy_enabled TMPFS_VAR_LIB_APT_LISTS; then
    render_target_template "$TMP_ENV_DIR/apt-refresh-lists.tmpl" "/target${FILE_APT_REFRESH_LISTS_HELPER}" 0755
    render_target_template "$TMP_ENV_DIR/apt-refresh-lists.service.tmpl" "/target${FILE_APT_REFRESH_LISTS_SERVICE}" 0644
  else
    remove_target_asset "${FILE_APT_REFRESH_LISTS_HELPER}"
    remove_target_asset "${FILE_APT_REFRESH_LISTS_SERVICE}"
    remove_target_asset "/etc/systemd/system/multi-user.target.wants/apt-refresh-lists.service"
  fi
}

validate_target_tmpfiles_policy_path() {
  case "${1:-}" in
    /*) ;;
    *) installer_fatal "managed tmpfiles policy path must be absolute: ${1:-unset}" ;;
  esac
  case "$1" in
    /|*..*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/-]*)
      installer_fatal "managed tmpfiles policy path contains unsupported syntax: ${1}"
      ;;
  esac
}

normalize_target_tmpfiles_directory_policy() {
  tmpfiles_policy_path=$1
  tmpfiles_policy_label=${2:-managed tmpfiles directory policy}

  validate_target_tmpfiles_policy_path "$tmpfiles_policy_path"
  [ -r "/target${tmpfiles_policy_path}" ] ||
    installer_fatal "managed tmpfiles policy is missing before normalization: ${tmpfiles_policy_path}"

  # Apply only directory entries from the rendered tmpfiles policy so the target
  # file remains the single source of truth for shared storage permissions.
  # shellcheck disable=SC2016
  run_in_target_quiet "normalize ${tmpfiles_policy_label}" /bin/sh -eu -c '
conf_path=$1
conf_label=$2

while IFS= read -r raw_line || [ -n "$raw_line" ]; do
  line=$(printf "%s" "$raw_line" | sed "s/^[[:space:]]*//; s/[[:space:]]*$//")
  case "$line" in
    ""|"#"*) continue ;;
  esac

  # shellcheck disable=SC2086
  set -- $line
  entry_type=${1:-}
  entry_path=${2:-}
  entry_mode=${3:-}
  entry_owner=${4:--}
  entry_group=${5:--}

  case "$entry_type" in
    d) ;;
    *) continue ;;
  esac
  case "$entry_path" in
    /*) ;;
    *)
      printf "fatal: %s has a non-absolute directory path: %s\n" "$conf_label" "${entry_path:-unset}" >&2
      exit 1
      ;;
  esac
  case "$entry_path" in
    /|*..*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/-]*)
      printf "fatal: %s has unsupported directory path syntax: %s\n" "$conf_label" "$entry_path" >&2
      exit 1
      ;;
  esac
  case "$entry_mode" in
    0[0-7][0-7][0-7][0-7])
      entry_mode=${entry_mode#0}
      ;;
    [0-7][0-7][0-7][0-7]|[0-7][0-7][0-7]) ;;
    *)
      printf "fatal: %s has invalid directory mode %s for %s\n" "$conf_label" "${entry_mode:-unset}" "$entry_path" >&2
      exit 1
      ;;
  esac

  install -d -m "$entry_mode" -- "$entry_path"

  if [ "$entry_owner" = "-" ]; then
    resolved_owner=$(stat -c "%u" -- "$entry_path")
  else
    resolved_owner=$entry_owner
  fi
  if [ "$entry_group" = "-" ]; then
    resolved_group=$(stat -c "%g" -- "$entry_path")
  else
    resolved_group=$entry_group
  fi

  chown "${resolved_owner}:${resolved_group}" -- "$entry_path"
  chmod "$entry_mode" -- "$entry_path"
done < "$conf_path"
' sh "$tmpfiles_policy_path" "$tmpfiles_policy_label"
}

stage_target_runtime_storage_root_policy() {
  render_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/tmpfiles.d/10-runtime-storage-roots.conf)" "/etc/tmpfiles.d/10-runtime-storage-roots.conf" 0644
}

ensure_target_managed_runtime_storage_roots() {
  run_in_target_quiet "ensure shared devops group" /bin/sh -eu -c '
getent group devops >/dev/null 2>&1 || groupadd --system devops
' sh
  stage_target_runtime_storage_root_policy
  normalize_target_tmpfiles_directory_policy "/etc/tmpfiles.d/10-runtime-storage-roots.conf" "shared runtime storage roots"
}

stage_target_common_storage_maintenance_assets() {
  stage_target_runtime_storage_root_policy
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/tmpfiles.d/tmp.conf)" "/etc/tmpfiles.d/tmp.conf" 0644
  grep -Fxq 'D! /tmp 1777 root root 0' /target/etc/tmpfiles.d/tmp.conf &&
    grep -Fxq 'e /tmp 1777 root root 7d' /target/etc/tmpfiles.d/tmp.conf &&
    grep -Fxq 'd /var/tmp 1777 root root 30d' /target/etc/tmpfiles.d/tmp.conf ||
    installer_fatal "managed temporary-directory tmpfiles policy is incomplete"
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET usr/libexec/install-tools/system-log.sh)" "/usr/libexec/install-tools/system-log.sh" 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/journald.conf.d/10-storage.conf)" "${FILE_JOURNALD_STORAGE_CONF}" 0644
  grep -Fxq 'Storage=persistent' "/target${FILE_JOURNALD_STORAGE_CONF}" &&
    grep -Fxq 'SystemMaxUse=1G' "/target${FILE_JOURNALD_STORAGE_CONF}" &&
    grep -Fxq 'RuntimeMaxUse=128M' "/target${FILE_JOURNALD_STORAGE_CONF}" &&
    grep -Fxq 'MaxRetentionSec=1month' "/target${FILE_JOURNALD_STORAGE_CONF}" &&
    grep -Fxq 'ForwardToSyslog=yes' "/target${FILE_JOURNALD_STORAGE_CONF}" &&
    grep -Fxq 'ForwardToKMsg=no' "/target${FILE_JOURNALD_STORAGE_CONF}" &&
    grep -Fxq 'ReadKMsg=no' "/target${FILE_JOURNALD_STORAGE_CONF}" ||
    installer_fatal "managed journald policy must retain userspace logs, forward them to rsyslog, and leave kernel logging to imklog"
  install_target_tmpfs_pre_clean_assets
  install_target_tmpfs_tmpfiles_assets
  stage_target_conditional_apt_refresh_assets
  stage_target_apt_login_policy_assets
  render_target_template "$TMP_ENV_DIR/apt-daily.override.conf.tmpl" "/target${FILE_APT_DAILY_SERVICE_OVERRIDE}" 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/apt/listchanges.conf.installer-base)" "${FILE_APT_LISTCHANGES_CONF}" 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/system/systemd-creds.socket.d/10-encrypted-only.conf)" "/etc/systemd/system/systemd-creds.socket.d/10-encrypted-only.conf" 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/system/fstrim.service.d/override.conf)" "${FILE_FSTRIM_SERVICE_OVERRIDE}" 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/system/fstrim.timer.d/override.conf)" "${FILE_FSTRIM_TIMER_OVERRIDE}" 0644
}

target_xfs_scrub_cpuaccounting_units() {
  printf '%s\n' \
    xfs_scrub@.service \
    xfs_scrub_all.service \
    xfs_scrub_media@.service \
    system-xfs_scrub.slice
}

sanitize_target_xfs_scrub_systemd_units() {
  sanitized_count=0

  for xfs_unit in $(target_xfs_scrub_cpuaccounting_units); do
    xfs_unit_path=$(target_systemd_unit_path "$xfs_unit" system 2>/dev/null || true)
    [ -n "$xfs_unit_path" ] || continue
    [ -r "/target${xfs_unit_path}" ] || continue
    grep -q '^[[:space:]]*CPUAccounting[[:space:]]*=' "/target${xfs_unit_path}" || continue

    xfs_unit_dest="/target${DIR_SYSTEMD_SYSTEM}/${xfs_unit}"
    xfs_unit_tmp="${xfs_unit_dest}.tmp.$$"
    install -d -m 0755 "/target${DIR_SYSTEMD_SYSTEM}"
    if ! sed '/^[[:space:]]*CPUAccounting[[:space:]]*=/d' "/target${xfs_unit_path}" >"$xfs_unit_tmp"; then
      rm -f "$xfs_unit_tmp"
      installer_fatal "failed to sanitize xfs scrub unit: ${xfs_unit_path}"
    fi
    [ -s "$xfs_unit_tmp" ] || {
      rm -f "$xfs_unit_tmp"
      installer_fatal "sanitized xfs scrub unit is empty: ${xfs_unit_path}"
    }
    install -m 0644 "$xfs_unit_tmp" "$xfs_unit_dest"
    rm -f "$xfs_unit_tmp"
    grep -q '^[[:space:]]*CPUAccounting[[:space:]]*=' "$xfs_unit_dest" &&
      installer_fatal "sanitized xfs scrub unit still contains CPUAccounting=: ${xfs_unit_dest#/target}"

    for xfs_unit_link in "/target${DIR_SYSTEMD_SYSTEM}"/*.wants/"$xfs_unit" "/target${DIR_SYSTEMD_SYSTEM}"/*.requires/"$xfs_unit"; do
      [ -L "$xfs_unit_link" ] || continue
      ln -sf "${DIR_SYSTEMD_SYSTEM}/${xfs_unit}" "$xfs_unit_link"
    done
    sanitized_count=$((sanitized_count + 1))
  done

  [ "$sanitized_count" -eq 0 ] ||
    installer_info "sanitized xfs scrub systemd units with removed CPUAccounting directives: ${sanitized_count}"
}




apply_apt_refresh_placeholders() {
  target_path=$1
  installer_apply_scalar_placeholders "$target_path" "$target_path.apt-refresh.$$" \
    APT_REFRESH_LISTS_TIMEOUT "$APT_REFRESH_LISTS_TIMEOUT" \
    APT_REFRESH_LISTS_CONNECTIVITY_URL "$APT_REFRESH_LISTS_CONNECTIVITY_URL"
  mv "$target_path.apt-refresh.$$" "$target_path"
}

# A subshell guarantees restoration even if the general update fails or is
# interrupted. Preserve the selected CUDA lists without extending its explicit
# authentication exception to the ordinary Debian/vendor metadata refresh.
refresh_non_cuda_target_metadata() (
  set -eu
  source="${INSTALLER_TARGET_DIR:-/target}/etc/apt/sources.list.d/cuda-legacy-temp.list"
  held="${source}.installer-disabled"
  restore_cuda_source() { [ ! -f "$held" ] || mv -f "$held" "$source"; }
  [ ! -e "$held" ] || { installer_fatal 'stale CUDA source suspension; restore it before retrying'; exit 1; }
  if [ -f "$source" ]; then
    trap restore_cuda_source 0
    trap 'exit 130' INT; trap 'exit 143' TERM; trap 'exit 129' HUP
    mv "$source" "$held"
  fi
  run_in_target 'refresh non-CUDA apt metadata with the default crypto policy' "$@"
)
