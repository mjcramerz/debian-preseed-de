#!/bin/sh
# Sourced installer module; edit this file directly.

desktop_target_hostname() {
  target_hostname=

  if [ -r /target/etc/hostname ]; then
    target_hostname=$(sed -n '1{s/[[:space:]]*$//;p;q;}' /target/etc/hostname)
  fi
  if [ -z "$target_hostname" ] && [ -n "${SYSTEM_HOSTNAME:-}" ]; then
    target_hostname=$SYSTEM_HOSTNAME
  fi

  case "$target_hostname" in
    ''|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-]*)
      installer_fatal "target hostname is unavailable or invalid for desktop local mail delivery"
      ;;
  esac

  printf '%s\n' "$target_hostname"
}

desktop_mailname_value() {
  target_hostname=$(desktop_target_hostname)

  if [ -z "${SYSTEM_DOMAIN:-}" ]; then
    printf '%s\n' "$target_hostname"
    return 0
  fi

  case "$SYSTEM_DOMAIN" in
    ''|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.-]*|.*|*.|*..*)
      installer_fatal "SYSTEM_DOMAIN is invalid for desktop local mail delivery"
      ;;
  esac

  printf '%s.%s\n' "$target_hostname" "$SYSTEM_DOMAIN"
}

desktop_optional_env_assignment_line() {
  key=$1
  value=$2

  [ -n "$value" ] || return 0
  printf '%s=%s\n' "$key" "$value"
}

desktop_shell_config_value() {
  shell_single_quote "$1"
}

desktop_assert_no_unresolved_template_placeholders() {
  rendered_path=$1
  label=$2

  target_asset_assert_no_unresolved_installer_placeholders "$rendered_path" "$label"
}

desktop_render_target_template_impl() {
  source_path=$1
  target_path=$2
  mode=$3
  allow_deferred_placeholders=$4
  shift 4
  tmp_source="${TMP_ENV_DIR}/desktop-template.$$.src"
  tmp_rendered="${TMP_ENV_DIR}/desktop-template.$$.dst"

  [ $(( $# % 2 )) -eq 0 ] || installer_fatal "desktop template placeholders must be name/value pairs: ${source_path}"
  if ! fetch_hook "$source_path" "$tmp_source"; then
    rm -f "$tmp_source" "$tmp_rendered"
    return 1
  fi
  if ! installer_apply_scalar_placeholders "$tmp_source" "$tmp_rendered" "$@"; then
    rm -f "$tmp_source" "$tmp_rendered"
    installer_fatal "failed to render desktop template ${source_path}"
  fi

  if [ "$allow_deferred_placeholders" != true ]; then
    desktop_assert_no_unresolved_template_placeholders "$tmp_rendered" "desktop template ${source_path}"
  fi
  ensure_target_asset_parent "$target_path"
  install -m "$mode" "$tmp_rendered" "$(target_asset_host_path "$target_path")"
  rm -f "$tmp_source" "$tmp_rendered"
  desktop_log "rendered_template source=${source_path} target=${target_path} mode=${mode}"
}

desktop_render_target_template() {
  source_path=$1
  target_path=$2
  mode=$3
  shift 3

  desktop_render_target_template_impl "$source_path" "$target_path" "$mode" false "$@"
}

desktop_render_target_template_deferred() {
  source_path=$1
  target_path=$2
  mode=$3
  shift 3

  desktop_render_target_template_impl "$source_path" "$target_path" "$mode" true "$@"
}

desktop_render_role_target_template() {
  role_relpath=$1
  target_path=$2
  mode=$3
  shift 3
  source_path=$(installer_repo_join_var DIR_HOOKS_TARGET "$role_relpath")

  desktop_render_target_template "$source_path" "$target_path" "$mode" "$@"
}

desktop_render_role_target_template_deferred() {
  role_relpath=$1
  target_path=$2
  mode=$3
  shift 3
  source_path=$(installer_repo_join_var DIR_HOOKS_TARGET "$role_relpath")

  desktop_render_target_template_deferred "$source_path" "$target_path" "$mode" "$@"
}

desktop_render_shared_target_template() {
  shared_relpath=$1
  target_path=$2
  mode=$3
  shift 3
  source_path=$(installer_repo_join_var DIR_HOOKS_TARGET "$shared_relpath")

  desktop_render_target_template "$source_path" "$target_path" "$mode" "$@"
}

desktop_polkit_managed_rule_files() {
  cat <<'EOF'
00-admin-identities.rules
03-labwc-power.rules
05-active-local-gate.rules
10-pkexec.rules
20-login1-power.rules
40-networkmanager.rules
50-usb-policy.rules
55-software-management.rules
60-system-services-identity.rules
70-hardware-peripherals.rules
EOF
}

desktop_managed_nmap_script_files() {
  cat <<'EOF'
admin-surface-policy.nse
approved-services.nse
database-exposure-policy.nse
http-security-headers.nse
name-resolution-policy.nse
plaintext-service-policy.nse
service-inventory.nse
tls-service-policy.nse
EOF
}

desktop_stage_managed_nmap_scripts() {
  managed_nmap_scripts=$(desktop_managed_nmap_script_files)
  [ -n "$managed_nmap_scripts" ] || installer_fatal "desktop managed Nmap script set is empty"

  for managed_nmap_script in $managed_nmap_scripts; do
    case "$managed_nmap_script" in
      admin-surface-policy.nse|approved-services.nse|database-exposure-policy.nse|http-security-headers.nse|name-resolution-policy.nse|plaintext-service-policy.nse|service-inventory.nse|tls-service-policy.nse) ;;
      *)
        installer_fatal "unsafe desktop managed Nmap script name: ${managed_nmap_script:-unset}"
        ;;
    esac
    case "$managed_nmap_script" in
      *[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-]*|*..*|.*|*/*)
        installer_fatal "unsafe desktop managed Nmap script name: ${managed_nmap_script}"
        ;;
    esac
    desktop_stage_role_asset \
      "usr/local/share/nmap/scripts/${managed_nmap_script}" \
      "/usr/local/share/nmap/scripts/${managed_nmap_script}" \
      0644
  done
  unset managed_nmap_script managed_nmap_scripts
}

desktop_validate_managed_polkit_rule_name() {
  rule_name=$1

  case "$rule_name" in
    [0123456789][0123456789]-*.rules) ;;
    *)
      installer_fatal "unsafe desktop polkit rule name: ${rule_name:-unset}"
      ;;
  esac
  case "$rule_name" in
    *[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._+-]*|*..*|.*|*/*)
      installer_fatal "unsafe desktop polkit rule name: ${rule_name}"
      ;;
  esac
}

desktop_require_safe_thunar_eject_version() {
  desktop_thunar_minimum_version=4.20.9

  desktop_thunar_installed_status=$(
    capture_in_target \
      "read installed Thunar package status" \
      /usr/bin/dpkg-query \
      -W \
      -f='${Status}' \
      thunar
  ) || return 1
  [ "$desktop_thunar_installed_status" = "install ok installed" ] || {
    installer_fatal "Thunar is not fully installed for external-drive handling"
    return 1
  }

  desktop_thunar_installed_version=$(
    capture_in_target \
      "read installed Thunar package version" \
      /usr/bin/dpkg-query \
      -W \
      -f='${Version}' \
      thunar
  ) || return 1
  [ -n "$desktop_thunar_installed_version" ] &&
    [ "${#desktop_thunar_installed_version}" -le 128 ] || {
    installer_fatal "installed Thunar package has an invalid version field"
    return 1
  }
  test_in_target \
    /usr/bin/dpkg \
    --validate-version \
    "$desktop_thunar_installed_version" || {
    installer_fatal \
      "installed Thunar package version is invalid: $desktop_thunar_installed_version"
    return 1
  }
  if ! test_in_target \
    /usr/bin/dpkg \
    --compare-versions \
    "$desktop_thunar_installed_version" \
    ge \
    "$desktop_thunar_minimum_version"
  then
    # Thunar 4.19.3 fixed the ext4 eject crash (Xfce #1347). Requiring
    # 4.20.9 also includes the later asynchronous drive-operation fix (#1816).
    installer_fatal \
      "Thunar ${desktop_thunar_installed_version} is older than the safe external-drive minimum ${desktop_thunar_minimum_version}"
    return 1
  fi

  desktop_log \
    "validated Thunar external-drive runtime version=${desktop_thunar_installed_version} minimum=${desktop_thunar_minimum_version}"
  unset \
    desktop_thunar_installed_status \
    desktop_thunar_installed_version \
    desktop_thunar_minimum_version
}

desktop_configure_usb_media_access() {
  : "${ACCOUNT_USERNAME:?ACCOUNT_USERNAME must be set}"
  : "${ACCOUNT_DEFAULT_GROUPS:?ACCOUNT_DEFAULT_GROUPS must be set}"
  : "${DIR_UDISKS2:?DIR_UDISKS2 must be set}"
  : "${DIR_UDEV_RULES:?DIR_UDEV_RULES must be set}"
  : "${DIR_POLKIT_RULES_D:?DIR_POLKIT_RULES_D must be set}"
  : "${DIR_POLKIT_LOCAL_RULES_D:?DIR_POLKIT_LOCAL_RULES_D must be set}"
  : "${DIR_POLKIT_RUNTIME_RULES_D:?DIR_POLKIT_RUNTIME_RULES_D must be set}"
  : "${DIR_RUN_MEDIA:?DIR_RUN_MEDIA must be set}"
  : "${DIR_DATA_RUN_MNT:?DIR_DATA_RUN_MNT must be set}"
  : "${FILE_UDISKS2_CONF:?FILE_UDISKS2_CONF must be set}"
  : "${FILE_UDISKS2_MOUNT_OPTIONS_CONF:?FILE_UDISKS2_MOUNT_OPTIONS_CONF must be set}"
  : "${FILE_UDEV_UDISKS_BEHAVIOR_RULES:?FILE_UDEV_UDISKS_BEHAVIOR_RULES must be set}"
  : "${FILE_POLKIT_RUNTIME_TMPFILES:?FILE_POLKIT_RUNTIME_TMPFILES must be set}"

  desktop_require_safe_thunar_eject_version

  case "$ACCOUNT_USERNAME" in
    [abcdefghijklmnopqrstuvwxyz_]*) ;;
    *)
      installer_fatal "ACCOUNT_USERNAME must start with a lowercase letter or underscore"
      ;;
  esac
  case "$ACCOUNT_USERNAME" in
    *[!abcdefghijklmnopqrstuvwxyz0123456789_-]*)
      installer_fatal "ACCOUNT_USERNAME contains unsupported characters for desktop USB media policy"
      ;;
  esac
  case " $ACCOUNT_DEFAULT_GROUPS " in
    *" usbadmin "*)
      installer_fatal "ACCOUNT_DEFAULT_GROUPS must not include usbadmin; add users to usbadmin through an explicit hardware addon"
      ;;
  esac

  # shellcheck disable=SC2016
  run_in_target "configure desktop USB media authorization groups" /bin/sh -c '
set -eu
account_user=$1

for group_name in usbmedia usbadmin; do
  getent group "$group_name" >/dev/null 2>&1 || groupadd --system "$group_name"
done
usermod -a -G usbmedia "$account_user"
' sh "$ACCOUNT_USERNAME"

  install -d -m 0755 \
    "/target${DIR_UDISKS2}" \
    "/target${DIR_UDEV_RULES}" \
    "/target${DIR_POLKIT_RULES_D}" \
    "/target${DIR_POLKIT_LOCAL_RULES_D}"

  desktop_stage_role_asset etc/udisks2/udisks2.conf "$FILE_UDISKS2_CONF" 0644
  desktop_stage_role_asset etc/udisks2/mount_options.conf "$FILE_UDISKS2_MOUNT_OPTIONS_CONF" 0644
  desktop_stage_role_asset etc/udev/rules.d/90-udisks-behavior.rules "$FILE_UDEV_UDISKS_BEHAVIOR_RULES" 0644
  desktop_render_role_target_template \
    etc/tmpfiles.d/70-polkit-runtime.conf \
    "$FILE_POLKIT_RUNTIME_TMPFILES" \
    0644 \
    DIR_POLKIT_RUNTIME_RULES_D "$DIR_POLKIT_RUNTIME_RULES_D" \
    DIR_POLKIT_LOCAL_RULES_D "$DIR_POLKIT_LOCAL_RULES_D"
  desktop_render_role_target_template \
    etc/tmpfiles.d/25-desktop-media-runtime.conf \
    /etc/tmpfiles.d/25-desktop-media-runtime.conf \
    0644 \
    DIR_RUN_MEDIA "$DIR_RUN_MEDIA" \
    DIR_DATA_RUN_MNT "$DIR_DATA_RUN_MNT" \
    ACCOUNT_USERNAME "$ACCOUNT_USERNAME"
  polkit_managed_rule_files=$(desktop_polkit_managed_rule_files)
  [ -n "$polkit_managed_rule_files" ] || installer_fatal "desktop managed polkit rule set is empty"
  for polkit_rule in $polkit_managed_rule_files; do
    desktop_validate_managed_polkit_rule_name "$polkit_rule"
    desktop_stage_role_asset \
      "etc/polkit-1/rules.d/${polkit_rule}" \
      "${DIR_POLKIT_RULES_D}/${polkit_rule}" \
      0644
  done
  unset polkit_rule polkit_managed_rule_files
  desktop_log "configured desktop USB media and polkit policy user=${ACCOUNT_USERNAME}"
}

desktop_stage_primary_account_pool_storage_policy() {
  : "${ACCOUNT_USERNAME:?ACCOUNT_USERNAME must be set}"
  : "${DIR_POOL_BUILD:?DIR_POOL_BUILD must be set}"
  : "${DIR_POOL_CACHE:?DIR_POOL_CACHE must be set}"
  : "${DIR_POOL_DB:?DIR_POOL_DB must be set}"

  command -v normalize_target_tmpfiles_directory_policy >/dev/null 2>&1 ||
    installer_fatal "desktop account pool storage requires the shared tmpfiles normalizer"

  desktop_render_role_target_template \
    etc/tmpfiles.d/75-desktop-pool-storage.conf.tmpl \
    /etc/tmpfiles.d/75-desktop-pool-storage.conf \
    0644 \
    ACCOUNT_USERNAME "$ACCOUNT_USERNAME" \
    DIR_POOL_BUILD "$DIR_POOL_BUILD" \
    DIR_POOL_CACHE "$DIR_POOL_CACHE" \
    DIR_POOL_DB "$DIR_POOL_DB"
  normalize_target_tmpfiles_directory_policy \
    /etc/tmpfiles.d/75-desktop-pool-storage.conf \
    "desktop primary-account pool storage"
  desktop_log \
    "staged_desktop_pool_storage policy=/etc/tmpfiles.d/75-desktop-pool-storage.conf account=${ACCOUNT_USERNAME} group=devops shared_mode=2770 private_tmp=${DIR_POOL_CACHE}/${ACCOUNT_USERNAME}/tmp private_tmp_mode=0700"
}

desktop_stage_network_profile_storage_policy() {
  command -v normalize_target_tmpfiles_directory_policy >/dev/null 2>&1 ||
    installer_fatal "desktop network profile storage requires the shared tmpfiles normalizer"

  desktop_stage_role_asset \
    etc/tmpfiles.d/40-network-profiles.conf \
    /etc/tmpfiles.d/40-network-profiles.conf \
    0644
  normalize_target_tmpfiles_directory_policy \
    /etc/tmpfiles.d/40-network-profiles.conf \
    "desktop network profile storage"
  desktop_log \
    "staged_network_profile_storage wireguard_root=/data/config/network/wireguard owner=root group=devops mode=0750"
}

desktop_stage_var_cache_policy() {
  command -v normalize_target_tmpfiles_directory_policy >/dev/null 2>&1 ||
    installer_fatal "desktop var-cache policy requires the shared tmpfiles normalizer"

  # Package installation must create these accounts before the desktop role
  # applies the cache policy. Fail closed rather than leaving named tmpfiles
  # ownership unresolved on the fresh target.
  # shellcheck disable=SC2016
  run_in_target_quiet "validate desktop var-cache owners" /bin/sh -eu -c '
for account_name in man fwupd-refresh; do
  getent passwd "$account_name" >/dev/null 2>&1 || {
    printf "fatal: desktop var-cache owner account is missing: %s\n" "$account_name" >&2
    exit 1
  }
  getent group "$account_name" >/dev/null 2>&1 || {
    printf "fatal: desktop var-cache owner group is missing: %s\n" "$account_name" >&2
    exit 1
  }
done
' sh

  desktop_stage_role_asset \
    etc/tmpfiles.d/50-desktop-var-cache.conf \
    /etc/tmpfiles.d/50-desktop-var-cache.conf \
    0644
  desktop_stage_role_asset \
    etc/tmpfiles.d/man-db.conf \
    /etc/tmpfiles.d/man-db.conf \
    0644
  normalize_target_tmpfiles_directory_policy \
    /etc/tmpfiles.d/50-desktop-var-cache.conf \
    "desktop var-cache directories"
  normalize_target_tmpfiles_directory_policy \
    /etc/tmpfiles.d/man-db.conf \
    "desktop man-db cache directory"
  desktop_log "staged_desktop_var_cache policy=/etc/tmpfiles.d/50-desktop-var-cache.conf man_policy=/etc/tmpfiles.d/man-db.conf"
}

