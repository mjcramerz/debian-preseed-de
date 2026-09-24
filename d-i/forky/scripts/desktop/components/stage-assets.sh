#!/bin/sh
# Labwc target asset staging and service enablement helpers.

desktop_normalize_system_perl_module_parents() {
  module_path=$1
  case "$module_path" in
    /usr/local/lib/perl5/site_perl/*.pm) ;;
    *) return 0 ;;
  esac

  module_parent=$(dirname "$module_path")
  while :; do
    case "$module_parent" in
      /usr/local/lib/perl5|/usr/local/lib/perl5/*) ;;
      *) installer_fatal "system Perl module parent escaped the managed tree: ${module_parent}" ;;
    esac
    ensure_target_asset_parent "${module_parent}/.installer-module-parent"
    module_parent_host=$(target_asset_host_path "$module_parent")
    [ -d "$module_parent_host" ] && [ ! -L "$module_parent_host" ] ||
      installer_fatal "system Perl module parent is unsafe: ${module_parent}"
    chown root:root "$module_parent_host"
    chmod 0755 "$module_parent_host"
    [ "$module_parent" != /usr/local/lib/perl5 ] || break
    module_parent=$(dirname "$module_parent")
  done
}

desktop_stage_role_asset() {
  role_relpath=$1
  target_path=$2
  mode=$3
  source_path=$(installer_repo_join_var DIR_HOOKS_TARGET "$role_relpath")

  desktop_normalize_system_perl_module_parents "$target_path"
  stage_target_asset "$source_path" "$target_path" "$mode"
  desktop_log "staged_asset source=${source_path} target=${target_path} mode=${mode}"
}

desktop_stage_waybar_theme_icons() {
  # Absolute paths refer to installed package artwork. Relative icon paths are
  # explicit authenticated payload assets, not a hard-coded default filename.
  for waybar_theme_icon in \
    "$WAYBAR_BUTTON_APPS_NORMAL_ICON_PATH" \
    "$WAYBAR_BUTTON_APPS_HOVER_ICON_PATH" \
    "$WAYBAR_BUTTON_WAYSCRIBER_NORMAL_ICON_PATH" \
    "$WAYBAR_BUTTON_WAYSCRIBER_HOVER_ICON_PATH"
  do
    case "$waybar_theme_icon" in
      icons/*)
        desktop_stage_role_asset "etc/skel-desktop/.config/waybar/$waybar_theme_icon" \
          "/etc/skel-desktop/.config/waybar/$waybar_theme_icon" 0644 || return $?
        ;;
      /usr/share/*) : ;;
      *) installer_fatal 'invalid validated Waybar icon path'; return 1 ;;
    esac
  done
}

desktop_normalize_public_desktop_directories() {
  # d-i uses BusyBox install: under umask 077, -d -m 0755 sets only the
  # final directory's mode. Existing/intermediate parents can remain 0700.
  # Name public asset parents explicitly; never widen private user data.
  for public_directory in \
    /usr/local/share \
    /usr/local/share/applications \
    /usr/local/share/icons \
    /usr/local/share/icons/hicolor \
    /usr/local/share/icons/hicolor/64x64 \
    /usr/local/share/icons/hicolor/64x64/apps
  do
    ensure_target_asset_parent "${public_directory}/.installer-directory"
    public_directory_host=$(target_asset_host_path "$public_directory")
    [ -d "$public_directory_host" ] && [ ! -L "$public_directory_host" ] ||
      installer_fatal "public desktop directory is unsafe: ${public_directory}"
    chown root:root "$public_directory_host"
    chmod 0755 "$public_directory_host"
  done
  unset public_directory public_directory_host
  desktop_log "normalized_public_desktop_directories owner=root:root mode=0755"
}

desktop_normalize_system_dbus_service_directories() {
  for dbus_service_directory in \
    /usr/local/share/dbus-1 \
    /usr/local/share/dbus-1/services
  do
    ensure_target_asset_parent "${dbus_service_directory}/.installer-directory"
    dbus_service_directory_host=$(target_asset_host_path "$dbus_service_directory")
    [ -d "$dbus_service_directory_host" ] && [ ! -L "$dbus_service_directory_host" ] ||
      installer_fatal "system D-Bus service directory is unsafe: ${dbus_service_directory}"
    chown root:root "$dbus_service_directory_host"
    chmod 0755 "$dbus_service_directory_host"
  done
  unset dbus_service_directory dbus_service_directory_host
  desktop_log "normalized_system_dbus_service_directories owner=root:root mode=0755"
}

desktop_normalize_background_directories() {
  for background_directory in \
    /usr/share/backgrounds \
    /usr/share/backgrounds/desktop \
    /usr/share/backgrounds/login
  do
    ensure_target_asset_parent "${background_directory}/.installer-directory"
    background_directory_host=$(target_asset_host_path "$background_directory")
    [ -d "$background_directory_host" ] && [ ! -L "$background_directory_host" ] ||
      installer_fatal "managed background directory is unsafe: ${background_directory}"
    chown root:root -- "$background_directory_host"
    chmod 0755 -- "$background_directory_host"
  done
  unset background_directory background_directory_host
  desktop_log "normalized_background_directories owner=root:root mode=0755"
}

desktop_reconcile_wtmpdb_common_session() {
  wtmpdb_target_root=${1:-/target}
  case "$wtmpdb_target_root" in
    /*) ;;
    *) installer_fatal "wtmpdb target root must be an absolute path" ;;
  esac
  [ "$wtmpdb_target_root" != / ] ||
    installer_fatal "wtmpdb target root must not be the host root"

  wtmpdb_common_session_path="${wtmpdb_target_root%/}/etc/pam.d/common-session"
  [ -f "$wtmpdb_common_session_path" ] && [ ! -L "$wtmpdb_common_session_path" ] ||
    installer_fatal "target common-session PAM policy is unavailable or unsafe"

  wtmpdb_common_session_matches=$(awk '
    $1 == "session" &&
    $2 == "optional" &&
    $3 == "pam_wtmpdb.so" &&
    $4 == "skip_if=sshd" &&
    NF == 4 {
      count++
    }
    END { print count + 0 }
  ' "$wtmpdb_common_session_path") ||
    installer_fatal "failed to inspect target common-session PAM policy"
  [ "$wtmpdb_common_session_matches" -eq 1 ] ||
    installer_fatal "target common-session must contain exactly one Debian wtmpdb entry"

  wtmpdb_rules_tmp=$(mktemp "${TMP_ENV_DIR}/pam-wtmpdb.XXXXXX") ||
    installer_fatal "cannot stage native wtmpdb policy fragment"
  if ! fetch_hook "$(installer_repo_join_var DIR_SCRIPTS_DESKTOP templates/pam-wtmpdb.fragment)" "$wtmpdb_rules_tmp"; then
    rm -f -- "$wtmpdb_rules_tmp"
    installer_fatal "cannot fetch native wtmpdb policy fragment"
  fi
  wtmpdb_common_session_tmp="${wtmpdb_common_session_path}.tmp.$$"
  rm -f "$wtmpdb_common_session_tmp"
  if ! awk '
    FILENAME == ARGV[1] { replacement = replacement $0 "\n"; next }
    $1 == "session" &&
    $2 == "optional" &&
    $3 == "pam_wtmpdb.so" &&
    $4 == "skip_if=sshd" &&
    NF == 4 {
      printf "%s", replacement
      next
    }
    { print }
  ' "$wtmpdb_rules_tmp" "$wtmpdb_common_session_path" >"$wtmpdb_common_session_tmp"; then
    rm -f -- "$wtmpdb_rules_tmp" "$wtmpdb_common_session_tmp"
    installer_fatal "failed to render native common-session wtmpdb policy"
  fi
  rm -f -- "$wtmpdb_rules_tmp"
  [ -s "$wtmpdb_common_session_tmp" ] || {
    rm -f "$wtmpdb_common_session_tmp"
    installer_fatal "managed common-session wtmpdb policy is empty"
  }
  if ! install -m 0644 "$wtmpdb_common_session_tmp" "$wtmpdb_common_session_path"; then
    rm -f "$wtmpdb_common_session_tmp"
    installer_fatal "failed to install managed common-session wtmpdb policy"
  fi
  rm -f "$wtmpdb_common_session_tmp"
  desktop_log "reconciled_wtmpdb_common_session path=/etc/pam.d/common-session matched_entries=1 pam_auth_update=false"
}

desktop_role_target_source_dir() {
  role_relpath=$1
  repo_relpath=$(installer_repo_join_var DIR_HOOKS_TARGET "$role_relpath")

  if [ -n "${INSTALLER_SOURCE_ROOT:-}" ]; then
    printf '%s\n' "${INSTALLER_SOURCE_ROOT%/}/${repo_relpath}"
    return 0
  fi

  seed_base=$(installer_current_seed_base 2>/dev/null || true)
  [ -n "$seed_base" ] || return 1
  [ "$(installer_seed_source_type "$seed_base")" = file ] || return 1
  printf '%s\n' "${seed_base%/}/${repo_relpath}"
}

desktop_stage_role_asset_tree() (
  set -eu
  role_relpath=$1
  target_path=$2
  source_dir=$(desktop_role_target_source_dir "$role_relpath" || true)
  target_host_path=$(target_asset_host_path "$target_path")

  [ -n "$source_dir" ] || installer_fatal "desktop asset tree requires local source access: ${role_relpath}"
  [ -d "$source_dir" ] && [ ! -L "$source_dir" ] || installer_fatal "desktop asset tree is missing or unsafe: ${source_dir}"
  ensure_target_asset_parent "$target_path/.installer-tree-parent"
  tree_work=$(mktemp -d "${TMP_ENV_DIR}/desktop-tree.XXXXXX") || exit 1
  trap 'rm -rf "$tree_work"' EXIT
  trap 'exit 129' HUP
  trap 'exit 130' INT
  trap 'exit 143' TERM
  mkdir "$tree_work/rendered" || exit 1
  cp -a "$source_dir/." "$tree_work/rendered/" || exit 1
  installer_theme_render_tree "$tree_work/rendered" || exit 1
  install -d -m 0755 "$target_host_path" || exit 1
  cp -a "$tree_work/rendered/." "$target_host_path/" || exit 1
  chown -R root:root "$target_host_path" || exit 1
  desktop_log "staged_asset_tree source=${source_dir} target=${target_path}"
)

desktop_digital_assets_perl_modules() {
  cat <<'EOF'
DigitalAssets/Actions.pm
DigitalAssets/Catalog.pm
DigitalAssets/CLI.pm
DigitalAssets/Context.pm
DigitalAssets/Document.pm
DigitalAssets/Image.pm
DigitalAssets/Logger.pm
DigitalAssets/Metadata.pm
DigitalAssets/PDF.pm
DigitalAssets/Policy.pm
DigitalAssets/Runtime.pm
DigitalAssets/Session.pm
EOF
}

desktop_stage_digital_assets_perl_modules() {
  desktop_digital_assets_perl_modules |
    while IFS= read -r digital_assets_module; do
      [ -n "$digital_assets_module" ] || continue
      desktop_stage_role_asset \
        "usr/local/lib/perl5/site_perl/digital-assets/${digital_assets_module}" \
        "/usr/local/lib/perl5/site_perl/digital-assets/${digital_assets_module}" \
        0644
    done
}

desktop_ai_copilots_perl_modules() {
  cat <<'EOF'
AICopilots/CLI.pm
AICopilots/ModelCatalog.pm
AICopilots/ModelInstallRoot.pm
AICopilots/ModelStore.pm
AICopilots/Runtime.pm
AICopilots/Session.pm
AICopilots/State.pm
EOF
}

desktop_stage_ai_copilots_perl_modules() {
  desktop_ai_copilots_perl_modules |
    while IFS= read -r ai_copilots_module; do
      [ -n "$ai_copilots_module" ] || continue
      desktop_stage_role_asset \
        "usr/local/lib/perl5/site_perl/ai-copilots/${ai_copilots_module}" \
        "/usr/local/lib/perl5/site_perl/ai-copilots/${ai_copilots_module}" \
        0644
    done
}

desktop_stage_ai_copilots_catalogs() {
  desktop_stage_role_asset \
    usr/local/share/labwc-ai-copilots/llama-models.tsv \
    /usr/local/share/labwc-ai-copilots/llama-models.tsv \
    0644
  desktop_stage_role_asset \
    usr/local/share/labwc-ai-copilots/whisper-models.tsv \
    /usr/local/share/labwc-ai-copilots/whisper-models.tsv \
    0644
}

desktop_ai_copilots_python_modules() {
  cat <<'EOF'
__init__.py
cli.py
gguf.py
EOF
}

desktop_stage_ai_copilots_python_modules() {
  desktop_ai_copilots_python_modules |
    while IFS= read -r ai_copilots_module; do
      [ -n "$ai_copilots_module" ] || continue
      desktop_stage_role_asset \
        "usr/local/lib/python3.14/dist-packages/labwc_ai_copilots/${ai_copilots_module}" \
        "/usr/local/lib/python3.14/dist-packages/labwc_ai_copilots/${ai_copilots_module}" \
        0644
    done
}

desktop_labwc_security_action_perl_modules() {
  cat <<'EOF'
LabwcSecurityAction/AppArmor.pm
LabwcSecurityAction/AppArmor/AuditLog.pm
LabwcSecurityAction/AppArmor/ProfileIndex.pm
LabwcSecurityAction/AppArmor/RuleGenerator.pm
LabwcSecurityAction/AppArmor/RuleRenderer.pm
LabwcSecurityAction/Client.pm
LabwcSecurityAction/Command.pm
LabwcSecurityAction/Logger.pm
LabwcSecurityAction/Root.pm
LabwcSecurityAction/ScannerLog.pm
EOF
}

desktop_stage_labwc_security_action_perl_modules() {
  desktop_labwc_security_action_perl_modules |
    while IFS= read -r labwc_security_action_module; do
      [ -n "$labwc_security_action_module" ] || continue
      desktop_stage_role_asset \
        "usr/local/lib/perl5/site_perl/labwc-security-action/${labwc_security_action_module}" \
        "/usr/local/lib/perl5/site_perl/labwc-security-action/${labwc_security_action_module}" \
        0644
    done
}

desktop_labwc_network_control_action_perl_modules() {
  cat <<'EOF'
LabwcNetworkControlAction/Client.pm
LabwcNetworkControlAction/Command.pm
LabwcNetworkControlAction/Root.pm
LabwcNetworkControlAction/Validation.pm
EOF
}

desktop_stage_labwc_network_control_action_perl_modules() {
  desktop_stage_role_asset \
    "usr/local/libexec/network-openvpn-import" \
    "/usr/local/libexec/network-openvpn-import" \
    0755
  desktop_labwc_network_control_action_perl_modules |
    while IFS= read -r labwc_network_control_action_module; do
      [ -n "$labwc_network_control_action_module" ] || continue
      desktop_stage_role_asset \
        "usr/local/lib/perl5/site_perl/labwc-network-control-action/${labwc_network_control_action_module}" \
        "/usr/local/lib/perl5/site_perl/labwc-network-control-action/${labwc_network_control_action_module}" \
        0644
    done
}

desktop_labwc_network_scan_action_perl_modules() {
  cat <<'EOF'
LabwcNetworkScanAction/Client.pm
LabwcNetworkScanAction/Command.pm
LabwcNetworkScanAction/Validation.pm
EOF
}

desktop_stage_labwc_network_scan_action_perl_modules() {
  desktop_labwc_network_scan_action_perl_modules |
    while IFS= read -r labwc_network_scan_action_module; do
      [ -n "$labwc_network_scan_action_module" ] || continue
      desktop_stage_role_asset \
        "usr/local/lib/perl5/site_perl/labwc-network-scan-action/${labwc_network_scan_action_module}" \
        "/usr/local/lib/perl5/site_perl/labwc-network-scan-action/${labwc_network_scan_action_module}" \
        0644
    done
}

desktop_render_labwc_network_scan_action_perl_root_module() {
  desktop_render_role_target_template \
    usr/local/lib/perl5/site_perl/labwc-network-scan-action/LabwcNetworkScanAction/Root.pm.tmpl \
    /usr/local/lib/perl5/site_perl/labwc-network-scan-action/LabwcNetworkScanAction/Root.pm \
    0644 \
    ACCOUNT_USERNAME "$ACCOUNT_USERNAME"
}

