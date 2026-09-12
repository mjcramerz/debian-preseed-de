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

  wtmpdb_common_session_tmp="${wtmpdb_common_session_path}.tmp.$$"
  rm -f "$wtmpdb_common_session_tmp"
  if ! awk '
    $1 == "session" &&
    $2 == "optional" &&
    $3 == "pam_wtmpdb.so" &&
    $4 == "skip_if=sshd" &&
    NF == 4 {
      print "session\t[success=ignore default=1]\tpam_succeed_if.so quiet service = login"
      print "session\t[success=1 default=ignore]\tpam_succeed_if.so quiet tty !~ ?*"
      print "session\toptional\tpam_wtmpdb.so skip_if=sshd"
      next
    }
    { print }
  ' "$wtmpdb_common_session_path" >"$wtmpdb_common_session_tmp"; then
    rm -f "$wtmpdb_common_session_tmp"
    installer_fatal "failed to render managed common-session wtmpdb policy"
  fi
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

desktop_stage_role_asset_tree() {
  role_relpath=$1
  target_path=$2
  source_dir=$(desktop_role_target_source_dir "$role_relpath" || true)
  target_host_path=$(target_asset_host_path "$target_path")

  [ -n "$source_dir" ] || installer_fatal "desktop asset tree requires local source access: ${role_relpath}"
  [ -d "$source_dir" ] || installer_fatal "desktop asset tree is missing: ${source_dir}"
  install -d -m 0755 "$target_host_path"
  cp -a "$source_dir/." "$target_host_path/"
  chown -R root:root "$target_host_path"
  desktop_log "staged_asset_tree source=${source_dir} target=${target_path}"
}

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

desktop_labwc_managed_app_python_modules() {
  cat <<'EOF'
__init__.py
bootstrap.py
browsers.py
bubblewrap.py
cli.py
commands.py
dbus_proxy.py
electron.py
environment.py
events.py
generic.py
identity.py
integrity.py
mounts.py
network_namespace.py
profiles.py
runtime.py
sandbox.py
session.py
user_state.py
wayland_compat.py
wayland_compat_runtime.py
EOF
}

desktop_validate_labwc_managed_app_directory() {
  managed_app_checked_directory=$1
  managed_app_expected_uid=$2
  managed_app_expected_gid=$3
  managed_app_expected_mode=${4:-}

  if [ -L "$managed_app_checked_directory" ] ||
     [ ! -d "$managed_app_checked_directory" ]; then
    printf 'managed application directory has the wrong type: %s\n' \
      "$managed_app_checked_directory" >&2
    return 1
  fi

  managed_app_directory_metadata=$(installer_metadata_value \
    "$managed_app_checked_directory" uid_gid_mode) || {
    printf 'managed application directory metadata is unavailable: %s\n' \
      "$managed_app_checked_directory" >&2
    return 1
  }
  managed_app_actual_uid=${managed_app_directory_metadata%%:*}
  managed_app_directory_metadata=${managed_app_directory_metadata#*:}
  managed_app_actual_gid=${managed_app_directory_metadata%%:*}
  managed_app_actual_mode=${managed_app_directory_metadata#*:}

  if [ "$managed_app_actual_uid" != "$managed_app_expected_uid" ] ||
     [ "$managed_app_actual_gid" != "$managed_app_expected_gid" ]; then
    printf 'managed application directory has the wrong owner: %s: expected=%s:%s actual=%s:%s\n' \
      "$managed_app_checked_directory" \
      "$managed_app_expected_uid" \
      "$managed_app_expected_gid" \
      "$managed_app_actual_uid" \
      "$managed_app_actual_gid" >&2
    return 1
  fi

  if [ -n "$managed_app_expected_mode" ]; then
    if [ "$managed_app_actual_mode" != "$managed_app_expected_mode" ]; then
      printf 'managed application directory has the wrong mode: %s: expected=%s actual=%s\n' \
        "$managed_app_checked_directory" \
        "$managed_app_expected_mode" \
        "$managed_app_actual_mode" >&2
      return 1
    fi
    return 0
  fi

  managed_app_group_mode=$(((managed_app_actual_mode / 10) % 10))
  managed_app_other_mode=$((managed_app_actual_mode % 10))
  case "$managed_app_group_mode" in
    2|3|6|7)
      printf 'managed application directory is group writable: %s: mode=%s\n' \
        "$managed_app_checked_directory" "$managed_app_actual_mode" >&2
      return 1
      ;;
  esac
  case "$managed_app_other_mode" in
    2|3|6|7)
      printf 'managed application directory is other writable: %s: mode=%s\n' \
        "$managed_app_checked_directory" "$managed_app_actual_mode" >&2
      return 1
      ;;
  esac
}

desktop_validate_labwc_managed_app_package_tree() {
  managed_app_checked_package=$1
  managed_app_expected_uid=$2
  managed_app_expected_gid=$3
  managed_app_manifest=$4

  desktop_validate_labwc_managed_app_directory \
    "$managed_app_checked_package" \
    "$managed_app_expected_uid" \
    "$managed_app_expected_gid" \
    755 || return 1
  if [ -L "$managed_app_manifest" ] || [ ! -f "$managed_app_manifest" ]; then
    printf 'managed application manifest has the wrong type: %s\n' \
      "$managed_app_manifest" >&2
    return 1
  fi

  managed_app_duplicate_module=$(LC_ALL=C sort "$managed_app_manifest" | \
    uniq -d | sed -n '1p') || {
    printf 'managed application manifest could not be checked for duplicates: %s\n' \
      "$managed_app_manifest" >&2
    return 1
  }
  if [ -n "$managed_app_duplicate_module" ]; then
    printf 'managed application manifest contains a duplicate module: %s\n' \
      "$managed_app_duplicate_module" >&2
    return 1
  fi

  managed_app_manifest_count=0
  while IFS= read -r managed_app_manifest_module ||
        [ -n "$managed_app_manifest_module" ]; do
    case "$managed_app_manifest_module" in
      ''|.*|*/*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.]*)
        printf 'managed application manifest contains an unsafe module name: %s\n' \
          "${managed_app_manifest_module:-empty}" >&2
        return 1
        ;;
      *.py) ;;
      *)
        printf 'managed application manifest contains a non-Python module: %s\n' \
          "$managed_app_manifest_module" >&2
        return 1
        ;;
    esac
    managed_app_manifest_count=$((managed_app_manifest_count + 1))

    managed_app_checked_module="${managed_app_checked_package}/${managed_app_manifest_module}"
    if [ -L "$managed_app_checked_module" ] ||
       [ ! -f "$managed_app_checked_module" ]; then
      printf 'managed application module has the wrong type: %s\n' \
        "$managed_app_checked_module" >&2
      return 1
    fi
    managed_app_module_metadata=$(installer_metadata_value \
      "$managed_app_checked_module" uid_gid_mode_links) || {
      printf 'managed application module metadata is unavailable: %s\n' \
        "$managed_app_checked_module" >&2
      return 1
    }
    managed_app_expected_metadata="${managed_app_expected_uid}:${managed_app_expected_gid}:644:1"
    if [ "$managed_app_module_metadata" != "$managed_app_expected_metadata" ]; then
      printf 'managed application module has unsafe metadata: %s: expected=%s actual=%s\n' \
        "$managed_app_checked_module" \
        "$managed_app_expected_metadata" \
        "$managed_app_module_metadata" >&2
      return 1
    fi
  done <"$managed_app_manifest"
  [ "$managed_app_manifest_count" -gt 0 ] || {
    printf 'managed application manifest is empty: %s\n' \
      "$managed_app_manifest" >&2
    return 1
  }

  managed_app_inventory_count=0
  for managed_app_inventory_entry in \
    "$managed_app_checked_package"/* \
    "$managed_app_checked_package"/.[!.]* \
    "$managed_app_checked_package"/..?*
  do
    [ -e "$managed_app_inventory_entry" ] || \
      [ -L "$managed_app_inventory_entry" ] || continue
    managed_app_inventory_count=$((managed_app_inventory_count + 1))
  done
  unset managed_app_inventory_entry
  case "$managed_app_inventory_count" in
    ''|*[!0123456789]*)
      printf 'managed application package inventory count is invalid: %s\n' \
        "$managed_app_checked_package" >&2
      return 1
      ;;
  esac
  if [ "$managed_app_inventory_count" -ne "$managed_app_manifest_count" ]; then
    printf 'managed application package inventory count does not match the manifest: %s: expected=%s actual=%s\n' \
      "$managed_app_checked_package" \
      "$managed_app_manifest_count" \
      "$managed_app_inventory_count" >&2
    return 1
  fi
}

desktop_stage_labwc_managed_app_python_modules() {
  managed_app_package_path=/usr/local/lib/python3.14/dist-packages/labwc_managed_app
  managed_app_package_dir=$(target_asset_host_path "$managed_app_package_path")
  managed_app_package_parent=$(dirname -- "$managed_app_package_dir")
  managed_app_manifest="${TMP_ENV_DIR}/labwc-managed-app.manifest.$$"

  if [ -e "$managed_app_package_dir" ] || [ -L "$managed_app_package_dir" ]; then
    installer_fatal \
      "managed application package destination already exists in fresh target: ${managed_app_package_path}"
  fi
  install -d -o root -g root -m 0755 "$managed_app_package_parent"

  for managed_app_trusted_path in \
    /usr \
    /usr/local \
    /usr/local/lib \
    /usr/local/lib/python3.14 \
    /usr/local/lib/python3.14/dist-packages; do
    managed_app_trusted_host_path=$(target_asset_host_path \
      "$managed_app_trusted_path")
    desktop_validate_labwc_managed_app_directory \
      "$managed_app_trusted_host_path" 0 0 ||
      installer_fatal \
        "managed application package parent trust failed: ${managed_app_trusted_path}"
  done

  rm -f -- "$managed_app_manifest"
  desktop_labwc_managed_app_python_modules >"$managed_app_manifest"
  if [ -L "$managed_app_manifest" ] || [ ! -s "$managed_app_manifest" ]; then
    rm -f -- "$managed_app_manifest"
    installer_fatal "managed application package manifest could not be created"
  fi

  if ! (
    set -eu
    umask 077
    managed_app_stage_dir=
    managed_app_module_tmp=

    managed_app_stage_cleanup() {
      if [ -n "$managed_app_module_tmp" ]; then
        rm -f -- "$managed_app_module_tmp"
      fi
      if [ -n "$managed_app_stage_dir" ]; then
        case "$managed_app_stage_dir" in
          "$managed_app_package_parent"/.labwc_managed_app.stage.*)
            rm -rf -- "$managed_app_stage_dir"
            ;;
          *)
            printf 'refusing unsafe managed application staging cleanup path: %s\n' \
              "$managed_app_stage_dir" >&2
            ;;
        esac
      fi
    }
    trap managed_app_stage_cleanup 0 HUP INT TERM

    managed_app_stage_dir=$(mktemp -d \
      "${managed_app_package_parent}/.labwc_managed_app.stage.XXXXXX")
    chown root:root "$managed_app_stage_dir"
    chmod 0755 "$managed_app_stage_dir"

    while IFS= read -r labwc_managed_app_module ||
          [ -n "$labwc_managed_app_module" ]; do
      [ -n "$labwc_managed_app_module" ] || continue
      managed_app_source_path=$(installer_repo_join_var \
        DIR_HOOKS_TARGET \
        "usr/local/lib/python3.14/dist-packages/labwc_managed_app/${labwc_managed_app_module}")
      managed_app_module_tmp="${TMP_ENV_DIR}/labwc-managed-app-module.$$.tmp"
      rm -f -- "$managed_app_module_tmp"
      if ! fetch_hook "$managed_app_source_path" "$managed_app_module_tmp"; then
        printf 'failed to fetch managed application module: %s\n' \
          "$labwc_managed_app_module" >&2
        exit 1
      fi
      if [ -L "$managed_app_module_tmp" ] || [ ! -f "$managed_app_module_tmp" ]; then
        printf 'fetched managed application module has the wrong type: %s\n' \
          "$labwc_managed_app_module" >&2
        exit 1
      fi
      install -o root -g root -m 0644 \
        "$managed_app_module_tmp" \
        "${managed_app_stage_dir}/${labwc_managed_app_module}"
      rm -f -- "$managed_app_module_tmp"
      managed_app_module_tmp=
      desktop_log \
        "staged_asset source=${managed_app_source_path} target=${managed_app_package_path}/${labwc_managed_app_module} mode=0644"
    done <"$managed_app_manifest"

    desktop_validate_labwc_managed_app_package_tree \
      "$managed_app_stage_dir" 0 0 "$managed_app_manifest"
    if [ -e "$managed_app_package_dir" ] || [ -L "$managed_app_package_dir" ]; then
      printf 'managed application package destination appeared during staging: %s\n' \
        "$managed_app_package_path" >&2
      exit 1
    fi
    mv -- "$managed_app_stage_dir" "$managed_app_package_dir"
    managed_app_stage_dir=
    desktop_validate_labwc_managed_app_package_tree \
      "$managed_app_package_dir" 0 0 "$managed_app_manifest"
    trap - 0 HUP INT TERM
  ); then
    rm -f -- "$managed_app_manifest"
    installer_fatal "managed application package staging failed"
  fi

  rm -f -- "$managed_app_manifest"
  desktop_log \
    "published_managed_app_package target=${managed_app_package_path} owner=root:root directory_mode=0755 module_mode=0644"
}

desktop_labwc_firewall_python_modules() {
  cat <<'EOF'
__init__.py
cli.py
files.py
nftables.py
renderer.py
state.py
validation.py
EOF
}

desktop_stage_labwc_firewall_python_modules() {
  desktop_labwc_firewall_python_modules |
    while IFS= read -r labwc_firewall_module; do
      [ -n "$labwc_firewall_module" ] || continue
      desktop_stage_role_asset \
        "usr/local/lib/python3.14/dist-packages/labwc_firewall/${labwc_firewall_module}" \
        "/usr/local/lib/python3.14/dist-packages/labwc_firewall/${labwc_firewall_module}" \
        0644
    done
}

desktop_labwc_adb_perl_modules() {
  cat <<'EOF'
AndroidADB/CLI.pm
AndroidADB/Config.pm
AndroidADB/Logger.pm
AndroidADB/Validation.pm
AndroidADB/Lock.pm
AndroidADB/Command.pm
AndroidADB/Notification.pm
AndroidADB/Runtime.pm
AndroidADB/ADB/Server.pm
AndroidADB/ADB/Device.pm
AndroidADB/ADB/Package.pm
AndroidADB/ADB/Permissions.pm
AndroidADB/ADB/Transfer.pm
AndroidADB/ADB/Backup.pm
AndroidADB/Firmware/Archive.pm
AndroidADB/Firmware/Manifest.pm
AndroidADB/Firmware/Validation.pm
AndroidADB/Firmware/Storage.pm
AndroidADB/Vendor/Samsung.pm
AndroidADB/Vendor/GooglePixel.pm
EOF
}

desktop_stage_labwc_adb_perl_modules() {
  desktop_labwc_adb_perl_modules |
    while IFS= read -r labwc_adb_module; do
      [ -n "$labwc_adb_module" ] || continue
      desktop_stage_role_asset \
        "usr/local/lib/perl5/site_perl/labwc-adb/${labwc_adb_module}" \
        "/usr/local/lib/perl5/site_perl/labwc-adb/${labwc_adb_module}" \
        0644
    done
}

desktop_extract_role_wallpaper_archive() {
  archive_relpath=usr/share/backgrounds/desktop/wallpapers.tar.gz
  archive_source=$(installer_repo_join_var DIR_HOOKS_TARGET "$archive_relpath")
  archive_host="${TMP_ENV_DIR}/desktop-wallpapers.$$.tar.gz"
  archive_target=/tmp/installer-desktop-wallpapers.tar.gz
  archive_target_host=$(target_asset_host_path "$archive_target")
  archive_max_bytes=33554432

  rm -f -- "$archive_host" "$archive_target_host"
  if ! fetch_hook "$archive_source" "$archive_host"; then
    rm -f -- "$archive_host" "$archive_target_host"
    installer_fatal "failed to fetch desktop wallpaper archive: ${archive_source}"
  fi
  [ -f "$archive_host" ] && [ ! -L "$archive_host" ] ||
    installer_fatal "desktop wallpaper archive is not a regular file: ${archive_source}"

  archive_bytes=$(wc -c <"$archive_host" 2>/dev/null || true)
  archive_bytes=${archive_bytes##* }
  case "$archive_bytes" in
    ''|*[!0123456789]*|0)
      rm -f -- "$archive_host"
      installer_fatal "desktop wallpaper archive size is invalid: ${archive_source}"
      ;;
  esac
  if [ "$archive_bytes" -gt "$archive_max_bytes" ]; then
    rm -f -- "$archive_host"
    installer_fatal \
      "desktop wallpaper archive exceeds ${archive_max_bytes} bytes: ${archive_source}"
  fi

  install -m 0600 "$archive_host" "$archive_target_host"
  rm -f -- "$archive_host"

  # shellcheck disable=SC2016
  if ! run_in_target "extract managed desktop wallpaper archive" /bin/sh -eu -c '
archive=$1
destination=$2
member_limit=$3
extracted_byte_limit=$4
member_list=/tmp/installer-desktop-wallpapers.members.$$
verbose_list=/tmp/installer-desktop-wallpapers.verbose.$$
extract_dir=/tmp/installer-desktop-wallpapers.extract.$$

cleanup() {
  rm -rf -- "$archive" "$member_list" "$verbose_list" "$extract_dir"
}
trap cleanup EXIT HUP INT TERM

fatal() {
  printf "fatal: desktop wallpaper archive: %s\n" "$*" >&2
  exit 1
}

/usr/bin/tar -tzf "$archive" >"$member_list" ||
  fatal "archive is not readable gzip-compressed tar data"
member_count=$(/usr/bin/wc -l <"$member_list" | /usr/bin/tr -d " ")
case "$member_count" in
  ""|*[!0123456789]*|0) fatal "member count is invalid" ;;
esac
[ "$member_count" -le "$member_limit" ] ||
  fatal "archive contains too many members: $member_count"

duplicate_member=$(
  LC_ALL=C /usr/bin/sort "$member_list" |
    /usr/bin/uniq -d |
    /usr/bin/sed -n "1p"
)
[ -z "$duplicate_member" ] ||
  fatal "archive contains a duplicate member: $duplicate_member"
/usr/bin/grep -Fxq "labwall0-1920x1080.png" "$member_list" ||
  fatal "archive is missing required member: labwall0-1920x1080.png"

while IFS= read -r member_name || [ -n "$member_name" ]; do
  case "$member_name" in
    ""|/*|*/*|"."|".."|.*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-]*)
      fatal "archive contains an unsafe member name: ${member_name:-empty}"
      ;;
  esac
  case "$member_name" in
    *.png|*.jpg|*.jpeg) ;;
    *) fatal "archive member is not a supported PNG or JPEG: $member_name" ;;
  esac
  [ "$member_name" != wallpaper-1920x1080.png ] ||
    fatal "archive must not replace the managed fallback wallpaper"
done <"$member_list"

/usr/bin/tar --numeric-owner -tvzf "$archive" >"$verbose_list" ||
  fatal "archive member metadata could not be inspected"
metadata_count=0
extracted_bytes=0
while IFS= read -r member_metadata || [ -n "$member_metadata" ]; do
  set -- $member_metadata
  [ "$#" -ge 6 ] ||
    fatal "archive member metadata is incomplete"
  member_mode=$1
  member_size=$3
  case "$member_mode" in
    -*) ;;
    *) fatal "archive contains a non-regular member" ;;
  esac
  case "$member_mode" in
    *x*) fatal "archive contains an executable member" ;;
  esac
  case "$member_size" in
    ""|*[!0123456789]*) fatal "archive member size is invalid" ;;
  esac
  extracted_bytes=$((extracted_bytes + member_size))
  [ "$extracted_bytes" -le "$extracted_byte_limit" ] ||
    fatal "archive expands beyond ${extracted_byte_limit} bytes"
  metadata_count=$((metadata_count + 1))
done <"$verbose_list"
[ "$metadata_count" -eq "$member_count" ] ||
  fatal "archive member metadata count does not match the member list"

/usr/bin/install -d -m 0700 "$extract_dir"
/usr/bin/tar \
  --extract \
  --gzip \
  --file "$archive" \
  --directory "$extract_dir" \
  --no-same-owner \
  --no-same-permissions ||
  fatal "archive extraction failed"

/usr/bin/install -d -m 0755 "$destination"
while IFS= read -r member_name || [ -n "$member_name" ]; do
  extracted_path="${extract_dir}/${member_name}"
  [ -f "$extracted_path" ] && [ ! -L "$extracted_path" ] ||
    fatal "extracted member is not a regular file: $member_name"
  member_mime=$(/usr/bin/file --brief --mime-type -- "$extracted_path" 2>/dev/null || true)
  case "${member_name}:${member_mime}" in
    *.png:image/png|*.jpg:image/jpeg|*.jpeg:image/jpeg) ;;
    *) fatal "extracted member content does not match its image extension: $member_name" ;;
  esac
  /usr/bin/install -m 0644 "$extracted_path" "${destination}/${member_name}"
done <"$member_list"

printf "desktop_wallpaper_archive members=%s extracted_bytes=%s destination=%s\n" \
  "$member_count" \
  "$extracted_bytes" \
  "$destination"
' sh \
    "$archive_target" \
    /usr/share/backgrounds/desktop \
    128 \
    134217728
  then
    rm -f -- "$archive_target_host"
    installer_fatal "failed to validate and extract the desktop wallpaper archive"
  fi

  [ ! -e "$archive_target_host" ] ||
    installer_fatal "desktop wallpaper archive remained in the target after extraction"
  desktop_log \
    "extracted_wallpaper_archive source=${archive_source} target=/usr/share/backgrounds/desktop archive_bytes=${archive_bytes}"
}

desktop_target_tree_size_kib() {
  size_label=$1
  target_path=$2

  case "$target_path" in
    /*) ;;
    *)
      installer_fatal "desktop target size path must be absolute: ${target_path:-unset}"
      ;;
  esac
  case "$target_path" in
    /|*..*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/-]*)
      installer_fatal "desktop target size path is unsafe: ${target_path}"
      ;;
  esac

  target_size_kib=$(
    capture_in_target \
      "$size_label" \
      /usr/bin/du -sk -- "$target_path" |
      awk 'NR == 1 { print $1; exit }'
  )
  case "$target_size_kib" in
    ''|*[!0123456789]*)
      installer_fatal \
        "desktop target size measurement returned an invalid value for ${target_path}: ${target_size_kib:-unset}"
      ;;
  esac

  printf '%s\n' "$target_size_kib"
}

desktop_double_quote_escape() {
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

desktop_toml_escape() {
  desktop_double_quote_escape "$1"
}

desktop_xml_attribute_escape() {
  printf '%s' "$1" | sed 's/&/\&amp;/g; s/"/\&quot;/g; s/</\&lt;/g; s/>/\&gt;/g'
}

desktop_primary_account_ids() {
  wanted_user=${1:-${ACCOUNT_USERNAME:-}}

  [ -n "$wanted_user" ] || return 1
  awk -F: -v wanted_user="$wanted_user" '$1 == wanted_user { print $3 ":" $4; exit }' /target/etc/passwd 2>/dev/null
}

desktop_transient_pipx_build_account_prepare() {
  build_account=$1
  build_home=$2
  shift 2

  case "$build_account" in
    ''|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-]*)
      installer_fatal "transient pipx build account contains unsupported characters"
      ;;
  esac
  case "$build_home" in
    /|*..*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/-]*)
      installer_fatal "transient pipx build home contains unsupported syntax: ${build_home}"
      ;;
  esac
  [ "$#" -ge 1 ] ||
    installer_fatal "transient pipx build account requires managed writable paths"
  for build_path in "$@"; do
    case "$build_path" in
      /|*..*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/-]*)
        installer_fatal "transient pipx managed path contains unsupported syntax: ${build_path}"
        ;;
    esac
  done

  # The installer runs third-party pipx package hooks under this locked,
  # short-lived identity, with a private HOME rather than the eventual desktop
  # account's home. The installer grants managed write access only to the
  # caller-created runtime paths.
  # shellcheck disable=SC2016 # The quoted program executes inside the target.
  run_in_target "prepare transient pipx build account ${build_account}" /bin/sh -eu -c '
account=$1
build_home=$2
shift 2

case "$account" in
  ""|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-]*)
    printf "%s\n" "transient pipx build account contains unsupported characters" >&2
    exit 1
    ;;
esac
case "$build_home" in
  /|*..*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/-]*)
    printf "%s\n" "transient pipx build home contains unsupported syntax" >&2
    exit 1
    ;;
esac
[ "$#" -ge 1 ] || {
  printf "%s\n" "transient pipx build account requires managed writable paths" >&2
  exit 1
}
for build_path; do
  case "$build_path" in
    /|*..*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/-]*)
      printf "%s\n" "transient pipx managed path contains unsupported syntax" >&2
      exit 1
      ;;
  esac
  [ -d "$build_path" ] && [ ! -L "$build_path" ] || {
    printf "%s\n" "transient pipx managed path is missing or symbolic" >&2
    exit 1
  }
done
[ -d "$build_home" ] && [ ! -L "$build_home" ] || {
  printf "%s\n" "transient pipx build home is missing or symbolic" >&2
  exit 1
}
[ -x /usr/bin/awk ] &&
  [ -x /usr/sbin/useradd ] &&
  [ -x /usr/bin/chown ] &&
  [ -x /usr/bin/chmod ] &&
  [ -x /usr/bin/install ] ||
  {
    printf "%s\n" "transient pipx build account prerequisites are unavailable" >&2
    exit 1
  }

if /usr/bin/awk -F: -v account="$account" '"'"'$1 == account { found = 1; exit } END { exit !found }'"'"' /etc/passwd ||
  /usr/bin/awk -F: -v account="$account" '"'"'$1 == account { found = 1; exit } END { exit !found }'"'"' /etc/group
then
  printf "%s\n" "transient pipx build account or group already exists" >&2
  exit 1
fi

/usr/sbin/useradd \
  --system \
  --no-create-home \
  --shell /usr/sbin/nologin \
  --user-group \
  -- "$account"

for build_path; do
  /usr/bin/chown "$account:$account" "$build_path"
  /usr/bin/chmod 0755 "$build_path"
done
/usr/bin/chown "$account:$account" "$build_home"
/usr/bin/chmod 0700 "$build_home"
/usr/bin/install -d -o "$account" -g "$account" -m 0700 "$build_home/tmp"
' sh "$build_account" "$build_home" "$@"
}

desktop_transient_pipx_build_account_destroy() {
  build_account=$1
  build_home=$2

  case "$build_account" in
    ''|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-]*)
      installer_fatal "transient pipx build account contains unsupported characters"
      ;;
  esac
  case "$build_home" in
    /|*..*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/-]*)
      installer_fatal "transient pipx build home contains unsupported syntax: ${build_home}"
      ;;
  esac

  # Do not use a UID-wide kill here: in-target is chroot-based and may share
  # the installer process namespace. A non-forced userdel fails closed if the
  # transient builder cannot be removed, before root seals the runtime.
  # shellcheck disable=SC2016 # The quoted program executes inside the target.
  run_in_target "destroy transient pipx build account ${build_account}" /bin/sh -eu -c '
account=$1
build_home=$2

case "$account" in
  ""|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-]*)
    printf "%s\n" "transient pipx build account contains unsupported characters" >&2
    exit 1
    ;;
esac
case "$build_home" in
  /|*..*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/-]*)
    printf "%s\n" "transient pipx build home contains unsupported syntax" >&2
    exit 1
    ;;
esac
[ -d "$build_home" ] && [ ! -L "$build_home" ] || {
  printf "%s\n" "transient pipx build home is missing or symbolic" >&2
  exit 1
}
[ -x /usr/bin/awk ] &&
  [ -x /usr/bin/find ] &&
  [ -x /usr/bin/rmdir ] &&
  [ -x /usr/sbin/userdel ] &&
  [ -x /usr/sbin/groupdel ] ||
  {
    printf "%s\n" "transient pipx build account cleanup prerequisites are unavailable" >&2
    exit 1
  }
/usr/sbin/userdel -- "$account"
if /usr/bin/awk -F: -v account="$account" '"'"'$1 == account { found = 1; exit } END { exit !found }'"'"' /etc/group
then
  /usr/sbin/groupdel -- "$account"
fi
if /usr/bin/awk -F: -v account="$account" '"'"'$1 == account { found = 1; exit } END { exit !found }'"'"' /etc/passwd ||
  /usr/bin/awk -F: -v account="$account" '"'"'$1 == account { found = 1; exit } END { exit !found }'"'"' /etc/group
then
  printf "%s\n" "transient pipx build account cleanup left an identity behind" >&2
  exit 1
fi
/usr/bin/find "$build_home" -xdev -depth -mindepth 1 -delete
/usr/bin/rmdir -- "$build_home"
' sh "$build_account" "$build_home"
}

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
  fetch_hook "$source_path" "$tmp_source"
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
managed-admin-surface-policy.nse
managed-approved-services.nse
managed-database-exposure-policy.nse
managed-http-security-headers.nse
managed-name-resolution-policy.nse
managed-plaintext-service-policy.nse
managed-service-inventory.nse
managed-tls-service-policy.nse
EOF
}

desktop_stage_managed_nmap_scripts() {
  managed_nmap_scripts=$(desktop_managed_nmap_script_files)
  [ -n "$managed_nmap_scripts" ] || installer_fatal "desktop managed Nmap script set is empty"

  for managed_nmap_script in $managed_nmap_scripts; do
    case "$managed_nmap_script" in
      managed-*.nse) ;;
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

desktop_configure_android_debug_bridge_access() {
  : "${ACCOUNT_USERNAME:?ACCOUNT_USERNAME must be set}"

  case "$ACCOUNT_USERNAME" in
    [abcdefghijklmnopqrstuvwxyz_]*) ;;
    *)
      installer_fatal "ACCOUNT_USERNAME must start with a lowercase letter or underscore"
      ;;
  esac
  case "$ACCOUNT_USERNAME" in
    *[!abcdefghijklmnopqrstuvwxyz0123456789_-]*)
      installer_fatal "ACCOUNT_USERNAME contains unsupported characters for Android Debug Bridge policy"
      ;;
  esac

  # shellcheck disable=SC2016
  run_in_target "configure Android Debug Bridge USB access" /bin/sh -c '
set -eu
account_user=$1

for command_name in getent groupadd id usermod; do
  command -v "$command_name" >/dev/null 2>&1 || {
    printf "fatal: required Android Debug Bridge access command is missing: %s\n" "$command_name" >&2
    exit 1
  }
done

getent group plugdev >/dev/null 2>&1 || groupadd --system plugdev
usermod -a -G plugdev "$account_user"

account_groups=$(id -nG "$account_user")
case " $account_groups " in
  *" plugdev "*) ;;
  *)
    printf "fatal: desktop account was not added to the plugdev group: %s\n" "$account_user" >&2
    exit 1
    ;;
esac
' sh "$ACCOUNT_USERNAME"

  desktop_stage_role_asset \
    etc/udev/rules.d/51-android-debug-bridge.rules \
    /etc/udev/rules.d/51-android-debug-bridge.rules \
    0644
  desktop_stage_role_asset \
    etc/udev/rules.d/52-samsung-download-mode.rules \
    /etc/udev/rules.d/52-samsung-download-mode.rules \
    0644
  desktop_log "configured Android Debug Bridge and Samsung Download Mode USB access user=${ACCOUNT_USERNAME} group=plugdev"
}

desktop_configure_fido2_security_key_access() {
  desktop_stage_role_asset \
    etc/udev/rules.d/53-ledger-wallet.rules \
    /etc/udev/rules.d/53-ledger-wallet.rules \
    0644
  desktop_log "configured Ledger Stax browser FIDO2 security-key access through active-seat udev ACLs"
}

desktop_configure_packet_capture_access() {
  : "${ACCOUNT_USERNAME:?ACCOUNT_USERNAME must be set}"

  case "$ACCOUNT_USERNAME" in
    [abcdefghijklmnopqrstuvwxyz_]*) ;;
    *)
      installer_fatal "ACCOUNT_USERNAME must start with a lowercase letter or underscore"
      ;;
  esac
  case "$ACCOUNT_USERNAME" in
    *[!abcdefghijklmnopqrstuvwxyz0123456789_-]*)
      installer_fatal "ACCOUNT_USERNAME contains unsupported characters for packet capture policy"
      ;;
  esac

  # shellcheck disable=SC2016
  run_in_target "configure least-privilege Wireshark capture access" /bin/sh -c '
set -eu
account_user=$1

for command_name in \
  cut \
  debconf-set-selections \
  dpkg-reconfigure \
  dumpcap \
  getcap \
  getent \
  id \
  stat \
  tshark \
  usermod \
  wireshark
do
  command -v "$command_name" >/dev/null 2>&1 || {
    printf "fatal: required packet capture configuration command is missing: %s\n" "$command_name" >&2
    exit 1
  }
done

printf "%s\n" "wireshark-common wireshark-common/install-setuid boolean true" |
  debconf-set-selections
DEBIAN_FRONTEND=noninteractive
export DEBIAN_FRONTEND
dpkg-reconfigure wireshark-common

getent group wireshark >/dev/null 2>&1 || {
  printf "fatal: wireshark group is missing after wireshark-common reconfiguration\n" >&2
  exit 1
}
usermod -a -G wireshark "$account_user"

capture_groups=$(id -nG "$account_user")
case " $capture_groups " in
  *" wireshark "*) ;;
  *)
    printf "fatal: desktop account was not added to the wireshark group: %s\n" "$account_user" >&2
    exit 1
    ;;
esac

group_members=$(getent group wireshark | cut -d: -f4)
old_ifs=$IFS
IFS=,
for group_member in $group_members; do
  [ -n "$group_member" ] || continue
  [ "$group_member" = "$account_user" ] || {
    printf "fatal: unexpected automatically authorized wireshark group member: %s\n" "$group_member" >&2
    exit 1
  }
done
IFS=$old_ifs

dumpcap_path=$(command -v dumpcap)
dumpcap_group=$(stat -c %G "$dumpcap_path")
dumpcap_mode=$(stat -c %a "$dumpcap_path")
dumpcap_caps=$(getcap "$dumpcap_path" 2>/dev/null || true)
dumpcap_mode_value=$((0$dumpcap_mode))
dumpcap_cap_set=${dumpcap_caps#"$dumpcap_path "}

[ "$dumpcap_group" = wireshark ] || {
  printf "fatal: dumpcap is not owned by the wireshark group: %s\n" "$dumpcap_group" >&2
  exit 1
}
[ $((dumpcap_mode_value & 0010)) -ne 0 ] || {
  printf "fatal: dumpcap is not executable by the wireshark group: %s\n" "$dumpcap_mode" >&2
  exit 1
}
[ $((dumpcap_mode_value & 0001)) -eq 0 ] || {
  printf "fatal: dumpcap is executable by users outside the wireshark group: %s\n" "$dumpcap_mode" >&2
  exit 1
}
[ $((dumpcap_mode_value & 04000)) -eq 0 ] || {
  printf "fatal: dumpcap must use file capabilities instead of setuid root\n" >&2
  exit 1
}
case "$dumpcap_cap_set" in
  cap_net_admin,cap_net_raw=eip|cap_net_raw,cap_net_admin=eip|cap_net_admin,cap_net_raw=ep|cap_net_raw,cap_net_admin=ep) ;;
  *)
    printf "fatal: dumpcap has an unexpected capability set: %s\n" "${dumpcap_cap_set:-none}" >&2
    exit 1
    ;;
esac

for frontend_name in tshark wireshark; do
  frontend_path=$(command -v "$frontend_name")
  frontend_owner=$(stat -c %U "$frontend_path")
  frontend_mode=$(stat -c %a "$frontend_path")
  frontend_mode_value=$((0$frontend_mode))
  frontend_caps=$(getcap "$frontend_path" 2>/dev/null || true)

  [ "$frontend_owner" = root ] || {
    printf "fatal: %s is not owned by root: %s\n" "$frontend_name" "$frontend_owner" >&2
    exit 1
  }
  [ $((frontend_mode_value & 06000)) -eq 0 ] || {
    printf "fatal: %s must not be setuid or setgid: %s\n" "$frontend_name" "$frontend_mode" >&2
    exit 1
  }
  [ -z "$frontend_caps" ] || {
    printf "fatal: %s must not carry file capabilities: %s\n" "$frontend_name" "$frontend_caps" >&2
    exit 1
  }
done

printf "desktop_packet_capture_access user=%s group=wireshark dumpcap=%s mode=%s capabilities=%s\n" \
  "$account_user" "$dumpcap_path" "$dumpcap_mode" "$dumpcap_caps"
' sh "$ACCOUNT_USERNAME"
  desktop_log "configured packet capture access user=${ACCOUNT_USERNAME} group=wireshark"
}

desktop_assert_role_target_template_resolved() {
  role_relpath=$1
  target_path=$2
  source_path=$(installer_repo_join_var DIR_HOOKS_TARGET "$role_relpath")

  desktop_assert_no_unresolved_template_placeholders "$(target_asset_host_path "$target_path")" "desktop template ${source_path}"
}

desktop_replace_block_placeholder_in_target() {
  target_path=$1
  placeholder=$2
  replacement=$3

  replace_placeholder_line_block "$(target_asset_host_path "$target_path")" "$placeholder" "$replacement"
}

desktop_labwc_workspace_name_lines() {
  workspace_count=${LABWC_WORKSPACE_COUNT:-4}
  workspace_index=1

  while [ "$workspace_index" -le "$workspace_count" ]; do
    printf '      <name>%s</name>\n' "$workspace_index"
    workspace_index=$((workspace_index + 1))
  done
}

desktop_labwc_workspace_keybind_lines() {
  workspace_count=${LABWC_WORKSPACE_COUNT:-4}
  keybind_workspace_count=$workspace_count
  workspace_index=1

  if [ "$keybind_workspace_count" -gt 9 ]; then
    keybind_workspace_count=9
  fi

  while [ "$workspace_index" -le "$keybind_workspace_count" ]; do
    printf '    <keybind key="W-%s">\n' "$workspace_index"
    printf '      <action name="GoToDesktop" to="%s" />\n' "$workspace_index"
    printf '    </keybind>\n'
    printf '    <keybind key="W-S-%s">\n' "$workspace_index"
    printf '      <action name="SendToDesktop" to="%s" />\n' "$workspace_index"
    printf '    </keybind>\n'
    workspace_index=$((workspace_index + 1))
  done
}

desktop_whisper_addon_selected() {
  installer_selected_class_reference_is_selected addon/whisper 2>/dev/null
}

desktop_mullvad_selected() {
  installer_selected_class_reference_is_selected addon/software 2>/dev/null && return 0
  installer_selected_class_reference_is_selected apps/mullvad 2>/dev/null
}

desktop_stage_mullvad_dns_policy() {
  desktop_mullvad_selected || return 0

  run_in_target "validate Mullvad VPN resolver integration" /bin/sh -eu -c '
for package_name in mullvad-vpn systemd-resolved; do
  package_status=$(dpkg-query -W -f="\${db:Status-Abbrev}" "$package_name" 2>/dev/null || true)
  [ "$package_status" = "ii " ] || {
    printf "fatal: required Mullvad integration package is not installed: %s\n" "$package_name" >&2
    exit 1
  }
done
legacy_resolvconf_status=$(dpkg-query -W -f="\${db:Status-Abbrev}" resolvconf 2>/dev/null || true)
[ "$legacy_resolvconf_status" != "ii " ] || {
  printf "%s\n" "fatal: legacy resolvconf must not be installed with systemd-resolved" >&2
  exit 1
}
command -v resolvectl >/dev/null 2>&1 || {
  printf "%s\n" "fatal: resolvectl is unavailable for Mullvad DNS integration" >&2
  exit 1
}
[ -L /usr/sbin/resolvconf ] &&
  [ "$(readlink -f /usr/sbin/resolvconf)" = /usr/bin/resolvectl ] || {
    printf "%s\n" "fatal: systemd-resolved resolvconf compatibility link is invalid" >&2
    exit 1
  }
[ -L /etc/resolv.conf ] &&
  [ "$(readlink -m /etc/resolv.conf)" = /run/systemd/resolve/stub-resolv.conf ] || {
    printf "%s\n" "fatal: /etc/resolv.conf is not owned by systemd-resolved" >&2
    exit 1
  }
' sh

  mullvad_unit_path=$(target_systemd_unit_path mullvad-daemon.service system 2>/dev/null || true)
  [ -n "$mullvad_unit_path" ] ||
    installer_fatal "mullvad-vpn is selected but mullvad-daemon.service is unavailable in the target"

  desktop_stage_role_asset \
    etc/systemd/system/mullvad-daemon.service.d/20-managed-dns.conf \
    /etc/systemd/system/mullvad-daemon.service.d/20-managed-dns.conf \
    0644
  desktop_stage_role_asset \
    etc/systemd/system/tailscaled.service.d/30-mullvad-exclusion.conf \
    /etc/systemd/system/tailscaled.service.d/30-mullvad-exclusion.conf \
    0644
  desktop_stage_role_asset \
    etc/tmpfiles.d/51-mullvad-version-cache.conf \
    /etc/tmpfiles.d/51-mullvad-version-cache.conf \
    0644
  desktop_stage_role_asset \
    etc/tmpfiles.d/52-mullvad-tailscale-coordinator.conf \
    /etc/tmpfiles.d/52-mullvad-tailscale-coordinator.conf \
    0644
  desktop_stage_role_asset \
    usr/local/libexec/mullvad-tailscale-coordinator \
    /usr/local/libexec/mullvad-tailscale-coordinator \
    0755
  desktop_log \
    "staged_mullvad_runtime_policy backend=systemd-resolved cache_root=/var/lib/mullvad-version-cache cache_owner=root:root cache_seed=vendor-managed unit=${mullvad_unit_path}"
}

desktop_stage_mullvad_application_policy() {
  desktop_mullvad_selected || return 0

  desktop_stage_role_asset \
    usr/local/bin/mullvad-vpn \
    /usr/local/bin/mullvad-vpn \
    0755
  desktop_stage_role_asset \
    usr/local/libexec/mullvad-daemon-start \
    /usr/local/libexec/mullvad-daemon-start \
    0755
  desktop_stage_role_asset \
    usr/local/share/applications/mullvad-vpn.desktop \
    /usr/local/share/applications/mullvad-vpn.desktop \
    0644
  desktop_stage_role_asset \
    etc/skel-desktop/.config/autostart/mullvad-vpn.desktop \
    /etc/skel-desktop/.config/autostart/mullvad-vpn.desktop \
    0644
  desktop_log \
    "staged_mullvad_application_policy daemon_autostart=disabled gui_autostart=disabled launcher=/usr/local/bin/mullvad-vpn backend=wayland"
}

desktop_whisper_persistent_memory_enabled() {
  desktop_whisper_addon_selected || return 1
  [ "${WHISPER_PERSISTENT_MEM:-0}" = 1 ]
}

desktop_waybar_pulseaudio_right_click_command() {
  printf '/usr/bin/wpctl set-mute @DEFAULT_AUDIO_SOURCE@ toggle'
}

desktop_labwc_recording_keybind_lines() {
  if desktop_whisper_addon_selected; then
    cat <<'EOF'
    <keybind key="W-r">
      <action name="Execute" command="/usr/local/libexec/whisper-record-toggle toggle" />
    </keybind>
    <keybind key="C-A-r">
      <action name="Execute" command="/usr/local/libexec/whisper-record-toggle toggle" />
    </keybind>
    <keybind key="W-S-r">
      <action name="Reconfigure" />
    </keybind>
EOF
    return
  fi

  cat <<'EOF'
    <keybind key="W-r">
      <action name="Reconfigure" />
    </keybind>
EOF
}

desktop_require_absolute_account_home() {
  case "${ACCOUNT_HOME:-}" in
    /*) ;;
    *)
      installer_fatal "ACCOUNT_HOME must be an absolute path for desktop account configuration"
      ;;
  esac
  case "$ACCOUNT_HOME" in
    /|*..*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/-]*)
      installer_fatal "ACCOUNT_HOME contains unsupported path syntax for desktop account configuration: ${ACCOUNT_HOME}"
      ;;
  esac
}

desktop_validate_required_cmdline_token() {
  label=$1
  key=$2
  value=$3
  seen=$4

  if [ "$seen" != true ] || [ -z "$value" ]; then
    installer_fatal "${label} is required on the kernel cmdline (${key}=...) or in /preseed.env"
  fi
  case "$value" in
    *[![:print:]]*|*[[:space:]]*)
      installer_fatal "${label} must be a single printable token without whitespace: ${key}=..."
      ;;
  esac
}

desktop_validate_required_calendar_token() {
  label=$1
  cmdline_key=$2
  fallback_key=$3
  value=$4

  if [ -z "$value" ]; then
    installer_fatal "${label} is required on the kernel cmdline (${cmdline_key}=...), in /preseed.env, or in account.env (${fallback_key})"
  fi
  case "$value" in
    *[![:print:]]*|*[[:space:]]*)
      installer_fatal "${label} must be a single printable token without whitespace: ${cmdline_key}=... or ${fallback_key}"
      ;;
  esac
}

desktop_validate_iface_name() {
  label=$1
  value=$2

  case "$value" in
    ''|.|..|lo)
      desktop_fatal "${label} must be a non-loopback interface name"
      ;;
  esac
  case "$value" in
    *[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-]*)
      desktop_fatal "${label} contains unsupported characters: ${value}"
      ;;
  esac
  [ "${#value}" -le 15 ] || desktop_fatal "${label} must be 15 characters or fewer: ${value}"
}

desktop_target_managed_network_default_value() {
  key=$1
  defaults_path=/target/etc/default/managed-network
  value=

  [ -r "$defaults_path" ] || return 1
  value=$(sed -n "s/^${key}='\\([^']*\\)'$/\\1/p" "$defaults_path" | sed -n '1p')
  [ -n "$value" ] || return 1
  printf '%s\n' "$value"
}

desktop_waybar_modules_left_json() {
  printf '"custom/launcher", "ext/workspaces", "custom/wayscriber", "group/apps", "wlr/taskbar"'
}

desktop_waybar_modules_right_json() {
  printf '"pulseaudio", "custom/backlight", "battery", "disk", "cpu", "memory", "tray", "group/quick-controls", "custom/lock", "custom/power"'
}

desktop_waybar_modules_right_internal_json() {
  printf '"pulseaudio", "custom/backlight", "battery", "disk", "cpu", "memory", "tray", "group/quick-controls-internal", "custom/lock", "custom/power"'
}

desktop_waybar_output_selectors_json() {
  selector_mode=$1
  selector_prefixes=${LABWC_OUTPUT_INTERNAL_PREFIXES:-eDP LVDS DSI}
  selector_index_max=32
  selector_first=true

  case "$selector_mode" in
    internal|external) ;;
    *) desktop_fatal "unsupported Waybar output selector mode: ${selector_mode:-unset}" ;;
  esac
  [ -n "$selector_prefixes" ] || desktop_fatal "LABWC_OUTPUT_INTERNAL_PREFIXES must not be empty"

  for selector_prefix in $selector_prefixes; do
    case "$selector_prefix" in
      ''|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-]*)
        desktop_fatal "Waybar internal output prefix contains unsupported characters: ${selector_prefix:-unset}"
        ;;
    esac
    [ "${#selector_prefix}" -le 32 ] ||
      desktop_fatal "Waybar internal output prefix is longer than 32 characters: ${selector_prefix}"

    selector_index=1
    while [ "$selector_index" -le "$selector_index_max" ]; do
      for selector_output in "${selector_prefix}-${selector_index}" "${selector_prefix}${selector_index}"; do
        if [ "$selector_mode" = external ]; then
          selector_output="!${selector_output}"
        fi
        [ "$selector_first" = true ] || printf ', '
        printf '"%s"' "$selector_output"
        selector_first=false
      done
      selector_index=$((selector_index + 1))
    done
  done

  if [ "$selector_mode" = external ]; then
    [ "$selector_first" = true ] || printf ', '
    printf '"*"'
  fi
}

desktop_waybar_internal_outputs_json() {
  desktop_waybar_output_selectors_json internal
}

desktop_waybar_external_outputs_json() {
  desktop_waybar_output_selectors_json external
}

desktop_load_calendar_cmdline_tokens() {
  [ "${DESKTOP_CALENDAR_CMDLINE_TOKENS_READY:-0}" = 1 ] && return 0

  DESKTOP_FRUUX_USERNAME=
  DESKTOP_FRUUX_PASSWORD=
  desktop_fruux_username_seen=false
  desktop_fruux_password_seen=false

  if DESKTOP_FRUUX_USERNAME=$(installer_cmdline_value fruux_username 2>/dev/null); then
    desktop_fruux_username_seen=true
  fi
  if DESKTOP_FRUUX_PASSWORD=$(installer_cmdline_value fruux_password 2>/dev/null); then
    desktop_fruux_password_seen=true
  fi

  if [ "$desktop_fruux_username_seen" != true ] && [ -n "${FRUUX_CALENDAR_USERNAME:-}" ]; then
    DESKTOP_FRUUX_USERNAME=$FRUUX_CALENDAR_USERNAME
  fi
  if [ "$desktop_fruux_password_seen" != true ] && [ -n "${FRUUX_CALENDAR_PASSWORD:-}" ]; then
    DESKTOP_FRUUX_PASSWORD=$FRUUX_CALENDAR_PASSWORD
  fi

  desktop_validate_required_calendar_token "Fruux username" fruux_username FRUUX_CALENDAR_USERNAME "$DESKTOP_FRUUX_USERNAME"
  desktop_validate_required_calendar_token "Fruux password" fruux_password FRUUX_CALENDAR_PASSWORD "$DESKTOP_FRUUX_PASSWORD"
  DESKTOP_CALENDAR_CMDLINE_TOKENS_READY=1
}

desktop_load_plans_cmdline_tokens() {
  [ "${DESKTOP_PLANS_CMDLINE_TOKENS_READY:-0}" = 1 ] && return 0

  DESKTOP_TELEGRAM_API_KEY=$(installer_cmdline_value telegram_api_key 2>/dev/null || true)
  DESKTOP_TELEGRAM_CHAT_ID=$(installer_cmdline_value telegram_chat_id 2>/dev/null || true)

  desktop_validate_required_cmdline_token \
    "Telegram API key" \
    telegram_api_key \
    "$DESKTOP_TELEGRAM_API_KEY" \
    true
  desktop_validate_required_cmdline_token \
    "Telegram chat ID" \
    telegram_chat_id \
    "$DESKTOP_TELEGRAM_CHAT_ID" \
    true

  printf '%s\n' "$DESKTOP_TELEGRAM_API_KEY" |
    grep -Eq '^[0-9]{5,16}:[A-Za-z0-9_-]{20,128}$' ||
    installer_fatal "Telegram API key has an invalid format: telegram_api_key=..."
  printf '%s\n' "$DESKTOP_TELEGRAM_CHAT_ID" |
    grep -Eq '^-?[0-9]{1,20}$' ||
    installer_fatal "Telegram chat ID has an invalid format: telegram_chat_id=..."

  DESKTOP_PLANS_CMDLINE_TOKENS_READY=1
}

desktop_preflight_required_cmdline_tokens() {
  desktop_load_calendar_cmdline_tokens
  desktop_load_plans_cmdline_tokens
  desktop_log "validated_required_installer_tokens fruux_username=set fruux_password=set telegram_api_key=set telegram_chat_id=set"
}

desktop_write_labwc_plans_config() {
  : "${ACCOUNT_USERNAME:?ACCOUNT_USERNAME must be set}"
  : "${ACCOUNT_HOME:?ACCOUNT_HOME must be set}"

  desktop_require_absolute_account_home
  desktop_load_plans_cmdline_tokens
  primary_account_ids=$(desktop_primary_account_ids "$ACCOUNT_USERNAME" || true)
  case "$primary_account_ids" in
    [0-9]*:[0-9]*)
      primary_account_gid=${primary_account_ids#*:}
      ;;
    *)
      installer_fatal "failed to resolve target account group for labwc-plans"
      ;;
  esac

  # The replacement script and rendered temporary file contain Telegram credentials.
  (
    umask 077
    desktop_render_role_target_template \
      etc/default/labwc-plans.tmpl \
      /etc/default/labwc-plans \
      0640 \
      LABWC_PLANS_INPUT_DIR "${ACCOUNT_HOME}/Syncthing/sleek" \
      TELEGRAM_API_KEY "$DESKTOP_TELEGRAM_API_KEY" \
      TELEGRAM_CHAT_ID "$DESKTOP_TELEGRAM_CHAT_ID"
  )
  chown "root:${primary_account_gid}" /target/etc/default/labwc-plans
  chmod 0640 /target/etc/default/labwc-plans
  desktop_log "rendered_labwc_plans_config credentials=set topic=labwc_plans_notify mode=0640"
}

desktop_install_primary_account_calendar_stack() {
  : "${ACCOUNT_USERNAME:?ACCOUNT_USERNAME must be set}"
  : "${ACCOUNT_HOME:?ACCOUNT_HOME must be set}"

  desktop_require_absolute_account_home

  desktop_load_calendar_cmdline_tokens
  escaped_fruux_username=$(desktop_toml_escape "$DESKTOP_FRUUX_USERNAME")
  escaped_fruux_password=$(desktop_toml_escape "$DESKTOP_FRUUX_PASSWORD")
  account_home_path="${ACCOUNT_HOME}"
  target_account_home="/target${account_home_path}"
  config_root="${account_home_path}/.config"
  data_root="${account_home_path}/.local/share/calendars"
  state_root="${account_home_path}/.local/state"
  vdirsyncer_state_root="${state_root}/vdirsyncer"
  vdirsyncer_status_root="${vdirsyncer_state_root}/status"
  personal_dir="${data_root}/personal"
  tasks_dir="${data_root}/tasks"
  personal_displayname="${personal_dir}/displayname"
  personal_color="${personal_dir}/color"
  tasks_displayname="${tasks_dir}/displayname"
  tasks_color="${tasks_dir}/color"
  vdirsyncer_dir="${config_root}/vdirsyncer"
  khal_dir="${config_root}/khal"
  todoman_dir="${config_root}/todoman"
  vdirsyncer_config="${vdirsyncer_dir}/config"
  khal_config="${khal_dir}/config"
  todoman_config="${todoman_dir}/config.py"
  fruux_root_url="https://dav.fruux.com/calendars/a3298084101/"
  fruux_calendar_collection="05b2b2d2-6d85-43f5-bfcc-21d5903eea36"
  fruux_tasks_collection="d3e6ec9b-c656-48d8-adab-21ed7cb0f92a"
  account_ids=$(awk -F: -v wanted_user="$ACCOUNT_USERNAME" '$1 == wanted_user { print $3 ":" $4; exit }' /target/etc/passwd)
  [ -n "$account_ids" ] || installer_fatal "failed to resolve target uid/gid for ${ACCOUNT_USERNAME}"
  case "$account_ids" in
    [0-9]*:[0-9]*)
      case "$account_ids" in
        *:*:*|*[!0-9:]*)
          installer_fatal "target uid/gid for ${ACCOUNT_USERNAME} is not numeric: ${account_ids}"
          ;;
      esac
      ;;
    *)
      installer_fatal "target uid/gid for ${ACCOUNT_USERNAME} is not numeric: ${account_ids}"
      ;;
  esac
  account_uid=${account_ids%%:*}
  account_gid=${account_ids#*:}

  install -d -m 0755 \
    "${target_account_home}/.local" \
    "${target_account_home}/.local/share" \
    "${target_account_home}/.local/state"
  install -d -m 0700 \
    "/target${vdirsyncer_dir}" \
    "/target${khal_dir}" \
    "/target${todoman_dir}" \
    "/target${personal_dir}" \
    "/target${tasks_dir}" \
    "/target${vdirsyncer_status_root}"

  desktop_render_role_target_template \
    "etc/skel-desktop/.config/vdirsyncer/config.tmpl" \
    "$vdirsyncer_config" \
    0600 \
    FRUUX_ROOT_URL "$fruux_root_url" \
    FRUUX_CALENDAR_COLLECTION "$fruux_calendar_collection" \
    FRUUX_TASKS_COLLECTION "$fruux_tasks_collection" \
    FRUUX_USERNAME "$escaped_fruux_username" \
    FRUUX_PASSWORD "$escaped_fruux_password"
  desktop_stage_role_asset "etc/skel-desktop/.config/khal/config" "$khal_config" 0600
  desktop_stage_role_asset "etc/skel-desktop/.config/todoman/config.py" "$todoman_config" 0600
  desktop_stage_role_asset "etc/skel-desktop/.local/share/calendars/personal/displayname" "$personal_displayname" 0600
  desktop_stage_role_asset "etc/skel-desktop/.local/share/calendars/personal/color" "$personal_color" 0600
  desktop_stage_role_asset "etc/skel-desktop/.local/share/calendars/tasks/displayname" "$tasks_displayname" 0600
  desktop_stage_role_asset "etc/skel-desktop/.local/share/calendars/tasks/color" "$tasks_color" 0600

  chown "$account_uid:$account_gid" \
    "${target_account_home}/.local" \
    "${target_account_home}/.local/share" \
    "${target_account_home}/.local/state"
  chown -R "$account_uid:$account_gid" \
    "/target${vdirsyncer_dir}" \
    "/target${khal_dir}" \
    "/target${todoman_dir}" \
    "/target${data_root}" \
    "/target${vdirsyncer_state_root}"
  desktop_log "rendered_calendar_stack user=${ACCOUNT_USERNAME} vdirsyncer=${vdirsyncer_config} khal=${khal_config} todoman=${todoman_config}"
}

desktop_primary_account_gpg_user_id() {
  if [ -n "${SYSTEM_HOSTNAME:-}" ]; then
    printf '%s (%s@%s)\n' "$ACCOUNT_FULLNAME" "$ACCOUNT_USERNAME" "$SYSTEM_HOSTNAME"
    return 0
  fi

  printf '%s (%s)\n' "$ACCOUNT_FULLNAME" "$ACCOUNT_USERNAME"
}

desktop_primary_account_gpg_passphrase() {
  if [ "${ACCOUNT_GPG_PASSPHRASE_IS_PLAIN:-false}" = true ] &&
    [ -n "${ACCOUNT_GPG_PASSPHRASE:-}" ]
  then
    printf '%s\n' "$ACCOUNT_GPG_PASSPHRASE"
    return 0
  fi

  installer_fatal \
    "desktop GPG bootstrap requires primary_gpg_passphrase= or primary_password= on the installer kernel command line or in /preseed.env"
}

desktop_bootstrap_primary_account_gpg_key() {
  : "${ACCOUNT_USERNAME:?ACCOUNT_USERNAME must be set}"
  : "${ACCOUNT_HOME:?ACCOUNT_HOME must be set}"
  : "${ACCOUNT_FULLNAME:?ACCOUNT_FULLNAME must be set}"

  desktop_require_absolute_account_home

  gpg_user_id=$(desktop_primary_account_gpg_user_id)
  gpg_bootstrap_passphrase=$(desktop_primary_account_gpg_passphrase)
  [ -n "$gpg_bootstrap_passphrase" ] || installer_fatal "desktop GPG bootstrap requires a non-empty passphrase source"
  gpg_passphrase_file="${TMP_ENV_DIR}/desktop-gpg-passphrase"
  gpg_passphrase_target=/tmp/desktop-gpg-passphrase.$$
  umask 077
  printf '%s\n' "$gpg_bootstrap_passphrase" >"$gpg_passphrase_file"
  install -d -m 1777 /target/tmp
  install -m 0600 "$gpg_passphrase_file" "/target${gpg_passphrase_target}"

  # shellcheck disable=SC2016
  if ! attempt_in_target "bootstrap primary account GPG key for KWallet" /bin/sh -c '
set -eu
account_user=$1
account_home=$2
gpg_user_id=$3
passphrase_file=$4
gnupg_dir="${account_home}/.gnupg"
gpg_agent_conf="${gnupg_dir}/gpg-agent.conf"
gpg_agent_template=/etc/skel-desktop/.gnupg/gpg-agent.conf

fatal() {
  printf "fatal: %s\n" "$*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fatal "required command is missing: $1"
}

account_gpg() {
  runuser -u "$account_user" -- env \
    HOME="$account_home" \
    USER="$account_user" \
    LOGNAME="$account_user" \
    GNUPGHOME="$gnupg_dir" \
    PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    gpg "$@"
}

account_gpgconf() {
  runuser -u "$account_user" -- env \
    HOME="$account_home" \
    USER="$account_user" \
    LOGNAME="$account_user" \
    GNUPGHOME="$gnupg_dir" \
    PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    gpgconf "$@"
}

gpg_secret_key_fingerprints() {
  account_gpg \
    --batch \
    --no-options \
    --fixed-list-mode \
    --with-colons \
    --list-secret-keys \
    -- "$gpg_user_id" 2>/dev/null |
    awk -F: "
      \$1 == \"sec\" { want_fingerprint = 1; next }
      want_fingerprint && \$1 == \"fpr\" {
        print \$10
        want_fingerprint = 0
      }
    "
}

gpg_validate_fingerprint() {
  fingerprint=$1
  case "${#fingerprint}" in
    40|64) ;;
    *) fatal "generated GPG fingerprint has an unsupported length" ;;
  esac
  case "$fingerprint" in
    *[!0123456789ABCDEF]*) fatal "generated GPG fingerprint is malformed" ;;
  esac
}

gpg_key_can_encrypt() {
  fingerprint=$1
  account_gpg \
    --batch \
    --no-options \
    --fixed-list-mode \
    --with-colons \
    --list-keys \
    -- "$fingerprint" 2>/dev/null |
    awk -F: "
      \$1 == \"pub\" && \$12 ~ /E/ { suitable = 1 }
      END { exit suitable ? 0 : 1 }
    "
}

gpg_key_is_kwallet_suitable() {
  fingerprint=$1
  account_gpg \
    --batch \
    --no-options \
    --fixed-list-mode \
    --with-colons \
    --list-keys \
    -- "$fingerprint" 2>/dev/null |
    awk -F: "
      \$1 == \"pub\" && substr(\$9, 1, 1) == \"u\" && \$12 ~ /E/ {
        suitable = 1
      }
      END { exit suitable ? 0 : 1 }
    "
}

case "$account_home" in
  /*) ;;
  *) fatal "account home must be absolute: $account_home" ;;
esac
case "$account_home" in
  /|*..*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/-]*)
    fatal "account home contains unsupported path syntax: $account_home"
    ;;
esac

require_cmd awk
require_cmd gpg
require_cmd gpgconf
require_cmd pinentry-qt
require_cmd runuser

[ -r "$passphrase_file" ] || fatal "GPG bootstrap passphrase file is missing: $passphrase_file"
[ -r "$gpg_agent_template" ] || fatal "GPG agent configuration template is missing: $gpg_agent_template"
trap '\''rm -f "$passphrase_file"'\'' EXIT HUP INT TERM

uid=$(id -u "$account_user")
gid=$(id -g "$account_user")
install -d -m 0700 "$gnupg_dir"
install -m 0600 "$gpg_agent_template" "$gpg_agent_conf"
chown -R "$uid:$gid" "$gnupg_dir"

IFS= read -r account_password <"$passphrase_file" || fatal "failed to read the primary account GPG passphrase"
[ -n "$account_password" ] || fatal "primary account GPG passphrase is empty"

key_fingerprints=$(gpg_secret_key_fingerprints)
if [ -z "$key_fingerprints" ]; then
  if command -v timeout >/dev/null 2>&1; then
    printf "%s\n" "$account_password" | timeout 120 runuser -u "$account_user" -- env \
      HOME="$account_home" \
      USER="$account_user" \
      LOGNAME="$account_user" \
      GNUPGHOME="$gnupg_dir" \
      PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
      gpg --batch --yes --no-options --pinentry-mode loopback --passphrase-fd 0 \
        --quick-generate-key "$gpg_user_id" future-default default never || \
      fatal "GPG bootstrap key generation failed or timed out"
  else
    printf "%s\n" "$account_password" | runuser -u "$account_user" -- env \
      HOME="$account_home" \
      USER="$account_user" \
      LOGNAME="$account_user" \
      GNUPGHOME="$gnupg_dir" \
      PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
      gpg --batch --yes --no-options --pinentry-mode loopback --passphrase-fd 0 \
        --quick-generate-key "$gpg_user_id" future-default default never || \
      fatal "GPG bootstrap key generation failed"
  fi
  key_fingerprints=$(gpg_secret_key_fingerprints)
fi

set -- $key_fingerprints
[ "$#" -eq 1 ] || fatal "desktop GPG bootstrap requires exactly one managed secret key"
gpg_fingerprint=$1
gpg_validate_fingerprint "$gpg_fingerprint"
gpg_key_can_encrypt "$gpg_fingerprint" ||
  fatal "desktop GPG bootstrap key does not provide an encryption capability"

printf "%s:6:\n" "$gpg_fingerprint" |
  account_gpg --batch --no-options --import-ownertrust >/dev/null 2>&1 ||
  fatal "failed to assign ultimate owner trust to the desktop GPG key"
account_gpg --batch --no-options --check-trustdb >/dev/null 2>&1 ||
  fatal "failed to rebuild desktop GPG trust state"
gpg_key_is_kwallet_suitable "$gpg_fingerprint" ||
  fatal "desktop GPG key is not encryption-capable with ultimate owner trust"

chown -R "$uid:$gid" "$gnupg_dir"
account_gpgconf --kill gpg-agent >/dev/null 2>&1 || true
printf "desktop_gpg_bootstrap user=%s status=ready gnupg=%s fingerprint=%s\n" \
  "$account_user" "$gnupg_dir" "$gpg_fingerprint"
' sh "$ACCOUNT_USERNAME" "$ACCOUNT_HOME" "$gpg_user_id" "$gpg_passphrase_target"; then
    rm -f "$gpg_passphrase_file" "/target${gpg_passphrase_target}"
    installer_fatal "failed to bootstrap primary account GPG key for KWallet"
  fi

  rm -f "$gpg_passphrase_file" "/target${gpg_passphrase_target}"
  unset gpg_bootstrap_passphrase ACCOUNT_GPG_PASSPHRASE
  ACCOUNT_GPG_PASSPHRASE_IS_PLAIN=false
  desktop_log "bootstrapped_primary_account_gpg_key user=${ACCOUNT_USERNAME}"
}

desktop_user_unit_template_dir() {
  printf '%s\n' /etc/skel-desktop/.config/systemd/user
}

desktop_user_unit_source_path() {
  unit=$1
  template_dir=$(desktop_user_unit_template_dir)
  template_unit="${template_dir}/${unit}"
  template_unit_host="/target${template_unit}"

  validate_systemd_unit_name "$unit"
  if [ -e "$template_unit_host" ] || [ -L "$template_unit_host" ]; then
    [ -f "$template_unit_host" ] && [ ! -L "$template_unit_host" ] ||
      installer_fatal "desktop user unit template is unsafe: ${template_unit}"
    printf '%s\n' "$template_unit"
    return 0
  fi

  target_systemd_unit_path "$unit" user 2>/dev/null
}

desktop_user_unit_link_target() {
  unit=$1
  template_dir=$(desktop_user_unit_template_dir)
  unit_path=$(desktop_user_unit_source_path "$unit" || true)

  [ -n "$unit_path" ] || return 1
  if [ "$unit_path" = "${template_dir}/${unit}" ]; then
    printf '../%s\n' "$unit"
  else
    printf '%s\n' "$unit_path"
  fi
}

desktop_stage_user_unit_wanted_by() {
  unit=$1
  wanted_by=$2

  : "${ACCOUNT_USERNAME:?ACCOUNT_USERNAME must be set}"
  desktop_require_absolute_account_home
  validate_systemd_unit_name "$unit"
  validate_systemd_unit_name "$wanted_by"

  link_target=$(desktop_user_unit_link_target "$unit" || true)
  if [ -z "$link_target" ]; then
    installer_warn "target user unit is unavailable; skipping per-user enablement: ${unit}"
    return 0
  fi

  account_ids=$(desktop_primary_account_ids "$ACCOUNT_USERNAME" || true)
  case "$account_ids" in
    *:*) ;;
    *) installer_fatal "target uid/gid is unavailable for desktop user-unit enablement: ${ACCOUNT_USERNAME}" ;;
  esac
  account_uid=${account_ids%%:*}
  account_gid=${account_ids#*:}
  case "$account_uid" in
    ''|*[!0-9]*) installer_fatal "target uid is unavailable for desktop user-unit enablement: ${ACCOUNT_USERNAME}" ;;
  esac
  case "$account_gid" in
    ''|*[!0-9]*) installer_fatal "target gid is unavailable for desktop user-unit enablement: ${ACCOUNT_USERNAME}" ;;
  esac
  [ "$account_uid" -gt 0 ] ||
    installer_fatal "desktop user-unit enablement refuses the root account"
  [ "$account_gid" -gt 0 ] ||
    installer_fatal "desktop user-unit enablement refuses the root group"

  template_dir=$(desktop_user_unit_template_dir)
  template_wants="${template_dir}/${wanted_by}.wants"
  account_unit_dir="${ACCOUNT_HOME}/.config/systemd/user"
  account_wants="${account_unit_dir}/${wanted_by}.wants"
  template_link="/target${template_wants}/${unit}"
  account_link="/target${account_wants}/${unit}"

  [ -d "/target${template_dir}" ] && [ ! -L "/target${template_dir}" ] ||
    installer_fatal "desktop user-unit template directory is unsafe: ${template_dir}"
  [ -d "/target${account_unit_dir}" ] && [ ! -L "/target${account_unit_dir}" ] ||
    installer_fatal "desktop account user-unit directory is unsafe: ${account_unit_dir}"
  install -d -m 0700 "/target${template_wants}" "/target${account_wants}"
  if [ -e "$template_link" ] && [ ! -L "$template_link" ]; then
    installer_fatal "desktop user-unit template enablement path is unsafe: ${template_wants}/${unit}"
  fi
  if [ -e "$account_link" ] && [ ! -L "$account_link" ]; then
    installer_fatal "desktop account user-unit enablement path is unsafe: ${account_wants}/${unit}"
  fi
  ln -sfn "$link_target" "$template_link"
  ln -sfn "$link_target" "$account_link"
  chown "$account_uid:$account_gid" "/target${account_unit_dir}" "/target${account_wants}"
  chown -h "$account_uid:$account_gid" "$account_link"
  if command -v unstage_target_systemd_unit_enabled >/dev/null 2>&1; then
    unstage_target_systemd_unit_enabled "$unit" user
  fi
  desktop_log "staged_user_unit_session_bound unit=${unit} source=${link_target} target=${wanted_by} account=${ACCOUNT_USERNAME}"
}

desktop_stage_global_user_unit_dropin_asset() {
  unit=$1
  dropin_name=$2
  unit_path=$(desktop_user_unit_source_path "$unit" || true)

  if [ -z "$unit_path" ]; then
    installer_warn "target user unit is unavailable; skipping drop-in: ${unit}"
    return 0
  fi

  dropin_relpath="etc/systemd/user/${unit}.d/${dropin_name}"
  dropin_path="/${dropin_relpath}"
  desktop_stage_role_asset "$dropin_relpath" "$dropin_path" 0644
  desktop_log "staged_global_user_unit_dropin unit=${unit} unit_path=${unit_path} target=${dropin_path}"
}

desktop_stage_wireplumber_user_conditions() {
  : "${LABWC_GREETER_USER:?LABWC_GREETER_USER must be set}"
  unit=wireplumber.service
  unit_path=$(desktop_user_unit_source_path "$unit" || true)

  if [ -z "$unit_path" ]; then
    installer_warn "target user unit is unavailable; skipping drop-in: ${unit}"
    return 0
  fi

  desktop_render_role_target_template \
    etc/systemd/user/wireplumber.service.d/20-no-root.conf.tmpl \
    /etc/systemd/user/wireplumber.service.d/20-no-root.conf \
    0644 \
    LABWC_GREETER_USER "$LABWC_GREETER_USER"
  desktop_log "staged_wireplumber_user_conditions unit=${unit} unit_path=${unit_path} greeter=${LABWC_GREETER_USER}"
}

desktop_stage_labwc_package_user_unit_dropins() {
  for unit in \
    foot-server.service \
    foot-server.socket \
    gvfs-daemon.service \
    gvfs-udisks2-volume-monitor.service \
    mako.service \
    hyprpolkitagent.service \
    filter-chain.service \
    xdg-desktop-portal.service \
    xdg-desktop-portal-gtk.service \
    xdg-desktop-portal-wlr.service \
    xdg-desktop-portal-lxqt.service
  do
    desktop_stage_global_user_unit_dropin_asset "$unit" 10-labwc-session.conf
  done
}

desktop_stage_wayscriber_service() {
  [ -x /target/usr/bin/wayscriber ] ||
    installer_fatal "Wayscriber package executable is missing from the target"

  unit_path=$(target_systemd_unit_path wayscriber.service user 2>/dev/null || true)
  [ -n "$unit_path" ] ||
    installer_fatal "Wayscriber package user service is missing from the target"

  desktop_stage_global_user_unit_dropin_asset wayscriber.service 10-labwc-session.conf
  desktop_log "staged_wayscriber_service unit_path=${unit_path} target=labwc-session.target"
}

desktop_stage_kwallet_dbus_activation_assets() {
  [ -x /target/usr/bin/ksecretd ] ||
    installer_fatal "KWallet secret portal executable is missing from the target"
  [ -x /target/usr/bin/kwalletd6 ] ||
    installer_fatal "KWallet daemon executable is missing from the target"
  [ -x /target/usr/bin/busctl ] ||
    installer_fatal "systemd D-Bus inspection client is missing from the target"

  # Debian already owns the portal, compatibility, and kwalletd6 service names.
  # Add only the Secret Service alias that the package does not provide.
  desktop_stage_role_asset \
    etc/skel-desktop/.local/share/dbus-1/services/org.freedesktop.secrets.service \
    /etc/skel-desktop/.local/share/dbus-1/services/org.freedesktop.secrets.service \
    0644
  desktop_log "staged_account_local_kwallet_secret_service_activation path=/etc/skel-desktop/.local/share/dbus-1/services/org.freedesktop.secrets.service"
}

desktop_stage_labwc_user_session_assets() {
  desktop_stage_role_asset \
    etc/systemd/system/user@.service.d/20-labwc-seatd.conf \
    /etc/systemd/system/user@.service.d/20-labwc-seatd.conf \
    0644
  desktop_stage_role_asset \
    etc/skel-desktop/.config/systemd/user/labwc-compositor.service \
    /etc/skel-desktop/.config/systemd/user/labwc-compositor.service \
    0644
  desktop_stage_role_asset \
    etc/skel-desktop/.config/systemd/user/labwc-session.target \
    /etc/skel-desktop/.config/systemd/user/labwc-session.target \
    0644
  desktop_stage_role_asset \
    etc/skel-desktop/.config/systemd/user/labwc-health-notify.service \
    /etc/skel-desktop/.config/systemd/user/labwc-health-notify.service \
    0644
  desktop_stage_role_asset \
    etc/skel-desktop/.config/systemd/user/labwc-health-notify.path \
    /etc/skel-desktop/.config/systemd/user/labwc-health-notify.path \
    0644
  desktop_stage_role_asset \
    etc/skel-desktop/.config/systemd/user/labwc-health-notify.timer \
    /etc/skel-desktop/.config/systemd/user/labwc-health-notify.timer \
    0644
  desktop_stage_role_asset \
    etc/skel-desktop/.config/systemd/user/labwc-plans.service \
    /etc/skel-desktop/.config/systemd/user/labwc-plans.service \
    0644

  desktop_stage_labwc_package_user_unit_dropins
  desktop_stage_wireplumber_user_conditions
  desktop_stage_wayscriber_service
  desktop_stage_kwallet_dbus_activation_assets

  for global_user_systemd_dir in \
    /target/etc/systemd/user \
    /target/etc/systemd/user/*.d
  do
    [ -d "$global_user_systemd_dir" ] || continue
    chown 0:0 "$global_user_systemd_dir"
    chmod 0755 "$global_user_systemd_dir"
  done
  for user_systemd_dir in \
    /target/etc/skel-desktop/.config/systemd \
    /target/etc/skel-desktop/.config/systemd/user \
    /target/etc/skel-desktop/.config/systemd/user/*.d
  do
    [ -d "$user_systemd_dir" ] || continue
    chmod 0700 "$user_systemd_dir"
  done
}

desktop_render_labwc_default_config() {
  : "${ACCOUNT_USERNAME:?ACCOUNT_USERNAME must be set}"
  : "${LABWC_INTEL_ACCELERATION_AVAILABLE:?Labwc Intel acceleration availability must be resolved}"
  : "${LABWC_NVIDIA_ACCELERATION_AVAILABLE:?Labwc NVIDIA acceleration availability must be resolved}"
  desktop_validate_bool \
    LABWC_INTEL_ACCELERATION_AVAILABLE \
    "$LABWC_INTEL_ACCELERATION_AVAILABLE"
  desktop_validate_bool \
    LABWC_NVIDIA_ACCELERATION_AVAILABLE \
    "$LABWC_NVIDIA_ACCELERATION_AVAILABLE"
  defaults_path=${LABWC_DESKTOP_DEFAULTS_FILE:-/etc/default/labwc-desktop}
  primary_account_ids=$(desktop_primary_account_ids "${ACCOUNT_USERNAME:-}" || true)
  primary_account_uid=1000
  primary_account_gid=1000
  qbittorrent_root="/run/media/${ACCOUNT_USERNAME}/bittorrent"

  case "${primary_account_ids:-}" in
    [0-9]*:[0-9]*)
      primary_account_uid=${primary_account_ids%%:*}
      primary_account_gid=${primary_account_ids#*:}
      ;;
  esac

  desktop_render_role_target_template \
    etc/default/labwc-desktop.tmpl \
    "$defaults_path" \
    0644 \
    LABWC_PRIMARY_UID "$(desktop_shell_config_value "$primary_account_uid")" \
    LABWC_PRIMARY_GID "$(desktop_shell_config_value "$primary_account_gid")" \
    DESKTOP_APPARMOR_STATE "$(desktop_shell_config_value "${DESKTOP_APPARMOR_STATE:?DESKTOP_APPARMOR_STATE must be set by the desktop host profile}")" \
    LABWC_DESKTOP_SESSION_NAME "$(desktop_shell_config_value "${LABWC_DESKTOP_SESSION_NAME:-Labwc}")" \
    LABWC_DESKTOP_SESSION_COMMAND "$(desktop_shell_config_value "${LABWC_DESKTOP_SESSION_COMMAND:-/usr/local/bin/labwc-session}")" \
    LABWC_WLR_RENDERER "$(desktop_shell_config_value "${LABWC_WLR_RENDERER-gles2}")" \
    LABWC_GSK_RENDERER "$(desktop_shell_config_value "${LABWC_GSK_RENDERER-opengl}")" \
    LABWC_GDK_DISABLE "$(desktop_shell_config_value "${LABWC_GDK_DISABLE-vulkan}")" \
    LABWC_WLR_NO_HARDWARE_CURSORS "$(desktop_shell_config_value "${LABWC_WLR_NO_HARDWARE_CURSORS-1}")" \
    LABWC_WLR_SCENE_DISABLE_DIRECT_SCANOUT "$(desktop_shell_config_value "${LABWC_WLR_SCENE_DISABLE_DIRECT_SCANOUT-1}")" \
    LABWC_INTEL_ACCELERATION_AVAILABLE "$(desktop_shell_config_value "$LABWC_INTEL_ACCELERATION_AVAILABLE")" \
    LABWC_NVIDIA_ACCELERATION_AVAILABLE "$(desktop_shell_config_value "$LABWC_NVIDIA_ACCELERATION_AVAILABLE")" \
    LABWC_MANAGED_APP_DEFAULT_EXEC "$(desktop_shell_config_value "$LABWC_MANAGED_APP_DEFAULT_EXEC")" \
    LABWC_ELECTRON_APP_DEFAULT_EXEC "$(desktop_shell_config_value "$LABWC_ELECTRON_APP_DEFAULT_EXEC")" \
    LABWC_WAYLAND_APP_DEFAULT_EXEC "$(desktop_shell_config_value "$LABWC_WAYLAND_APP_DEFAULT_EXEC")" \
    LABWC_WORKSPACE_COUNT "$(desktop_shell_config_value "${LABWC_WORKSPACE_COUNT:-4}")" \
    LABWC_WALLPAPER_PATH "$(desktop_shell_config_value "${LABWC_WALLPAPER_PATH:-/usr/share/backgrounds/desktop/wallpaper-1920x1080.png}")" \
    LABWC_LOCK_BACKGROUND_PATH "$(desktop_shell_config_value "${LABWC_LOCK_BACKGROUND_PATH:-/usr/share/backgrounds/login/lock-1920x1080.png}")" \
    LABWC_GREETER_BACKGROUND_PATH "$(desktop_shell_config_value "${LABWC_GREETER_BACKGROUND_PATH:-/usr/share/backgrounds/login/welcome-1920x1080.png}")" \
    LABWC_OUTPUT_POLICY "$(desktop_shell_config_value "${LABWC_OUTPUT_POLICY:-auto}")" \
    LABWC_OUTPUT_INTERNAL_PREFIXES "$(desktop_shell_config_value "${LABWC_OUTPUT_INTERNAL_PREFIXES:-eDP LVDS DSI}")" \
    LABWC_OUTPUT_INTERNAL_PREFERRED_WIDTH "$(desktop_shell_config_value "${LABWC_OUTPUT_INTERNAL_PREFERRED_WIDTH:-}")" \
    LABWC_OUTPUT_INTERNAL_PREFERRED_HEIGHT "$(desktop_shell_config_value "${LABWC_OUTPUT_INTERNAL_PREFERRED_HEIGHT:-}")" \
    LABWC_OUTPUT_INTERNAL_PREFERRED_REFRESH_HZ "$(desktop_shell_config_value "${LABWC_OUTPUT_INTERNAL_PREFERRED_REFRESH_HZ:-}")" \
    LABWC_OUTPUT_EXTERNAL_PREFERRED_WIDTH "$(desktop_shell_config_value "${LABWC_OUTPUT_EXTERNAL_PREFERRED_WIDTH:-}")" \
    LABWC_OUTPUT_EXTERNAL_PREFERRED_HEIGHT "$(desktop_shell_config_value "${LABWC_OUTPUT_EXTERNAL_PREFERRED_HEIGHT:-}")" \
    LABWC_OUTPUT_EXTERNAL_PREFERRED_REFRESH_HZ "$(desktop_shell_config_value "${LABWC_OUTPUT_EXTERNAL_PREFERRED_REFRESH_HZ:-}")" \
    LABWC_OUTPUT_FALLBACK_REFRESH_HZ "$(desktop_shell_config_value "${LABWC_OUTPUT_FALLBACK_REFRESH_HZ:-60}")" \
    LABWC_OUTPUT_SCALE "$(desktop_shell_config_value "${LABWC_OUTPUT_SCALE:-1}")" \
    LABWC_OUTPUT_INTERNAL_SCALE "$(desktop_shell_config_value "${LABWC_OUTPUT_INTERNAL_SCALE:-1}")" \
    LABWC_OUTPUT_EXTERNAL_SCALE "$(desktop_shell_config_value "${LABWC_OUTPUT_EXTERNAL_SCALE:-1}")" \
    LABWC_OUTPUT_HOTPLUG_DEBOUNCE_SECONDS "$(desktop_shell_config_value "${LABWC_OUTPUT_HOTPLUG_DEBOUNCE_SECONDS:-1}")" \
    LABWC_OUTPUT_INTERNAL_REFRESH_DELAY_SECONDS "$(desktop_shell_config_value "${LABWC_OUTPUT_INTERNAL_REFRESH_DELAY_SECONDS:-0}")" \
    LABWC_KEYBOARD_REPEAT_RATE "$(desktop_shell_config_value "${LABWC_KEYBOARD_REPEAT_RATE:-40}")" \
    LABWC_KEYBOARD_REPEAT_DELAY "$(desktop_shell_config_value "${LABWC_KEYBOARD_REPEAT_DELAY:-250}")" \
    LABWC_DETECTED_OUTPUTS "$(desktop_shell_config_value "${LABWC_DETECTED_OUTPUTS:-}")" \
    LABWC_DETECTED_INTERNAL_OUTPUTS "$(desktop_shell_config_value "${LABWC_DETECTED_INTERNAL_OUTPUTS:-}")" \
    LABWC_DETECTED_EXTERNAL_OUTPUTS "$(desktop_shell_config_value "${LABWC_DETECTED_EXTERNAL_OUTPUTS:-}")" \
    LABWC_DETECTED_PRIMARY_OUTPUT "$(desktop_shell_config_value "${LABWC_DETECTED_PRIMARY_OUTPUT:-}")" \
    LABWC_GREETER_USER "$(desktop_shell_config_value "${LABWC_GREETER_USER:-greeter}")" \
    LABWC_GREETER_VT "$(desktop_shell_config_value "${LABWC_GREETER_VT:-1}")" \
    LABWC_GREETER_COMMAND "$(desktop_shell_config_value "${LABWC_GREETER_COMMAND:-/usr/local/bin/labwc-greeter-session}")" \
    LABWC_GREETER_WLR_RENDERER "$(desktop_shell_config_value "${LABWC_GREETER_WLR_RENDERER-gles2}")" \
    LABWC_GREETER_GSK_RENDERER "$(desktop_shell_config_value "${LABWC_GREETER_GSK_RENDERER-opengl}")" \
    LABWC_GREETER_GDK_DISABLE "$(desktop_shell_config_value "${LABWC_GREETER_GDK_DISABLE-vulkan}")" \
    LABWC_GREETER_WLR_NO_HARDWARE_CURSORS "$(desktop_shell_config_value "${LABWC_GREETER_WLR_NO_HARDWARE_CURSORS-1}")" \
    LABWC_GREETER_INTERNAL_SCALE "$(desktop_shell_config_value "${LABWC_GREETER_INTERNAL_SCALE:-1}")" \
    LABWC_GREETER_EXTERNAL_SCALE "$(desktop_shell_config_value "${LABWC_GREETER_EXTERNAL_SCALE:-1}")" \
    LABWC_GREETER_HOTPLUG_DEBOUNCE_SECONDS "$(desktop_shell_config_value "${LABWC_GREETER_HOTPLUG_DEBOUNCE_SECONDS:-0}")" \
    LABWC_TERMINAL_PRIMARY "$(desktop_shell_config_value "${LABWC_TERMINAL_PRIMARY:-foot}")" \
    LABWC_TERMINAL_FALLBACK "$(desktop_shell_config_value "${LABWC_TERMINAL_FALLBACK:-kitty}")" \
    LABWC_TERMINAL_FONT_FAMILY "$(desktop_shell_config_value "${LABWC_TERMINAL_FONT_FAMILY:-Noto Sans Mono}")" \
    LABWC_TERMINAL_FONT_SIZE "$(desktop_shell_config_value "${LABWC_TERMINAL_FONT_SIZE:-12}")" \
    LABWC_LAUNCHER_COMMAND "$(desktop_shell_config_value "${LABWC_LAUNCHER_COMMAND:-labwc-fuzzel launcher}")" \
    LABWC_MENU_COMMAND "$(desktop_shell_config_value "${LABWC_MENU_COMMAND:-labwc-fuzzel launcher}")" \
    LABWC_FILE_MANAGER_COMMAND "$(desktop_shell_config_value "${LABWC_FILE_MANAGER_COMMAND:-thunar}")" \
    LABWC_AUDIO_CONTROL_COMMAND "$(desktop_shell_config_value "${LABWC_AUDIO_CONTROL_COMMAND:-pavucontrol}")" \
    LABWC_DISPLAY_CONTROL_COMMAND "$(desktop_shell_config_value "${LABWC_DISPLAY_CONTROL_COMMAND:-labwc-display-configuration}")" \
    LABWC_CALENDAR_COMMAND "$(desktop_shell_config_value "${LABWC_CALENDAR_COMMAND:-labwc-calendar}")" \
    LABWC_BRIGHTNESS_CONTROL_COMMAND "$(desktop_shell_config_value "${LABWC_BRIGHTNESS_CONTROL_COMMAND:-labwc-brightness-control}")" \
    LABWC_POWER_SETTINGS_COMMAND "$(desktop_shell_config_value "${LABWC_POWER_SETTINGS_COMMAND:-labwc-power-settings}")" \
    LABWC_KEYBOARD_LAYOUTS "$(desktop_shell_config_value "${LABWC_KEYBOARD_LAYOUTS:-us se}")" \
    LABWC_KEYBOARD_DEFAULT_LAYOUT "$(desktop_shell_config_value "${LABWC_KEYBOARD_DEFAULT_LAYOUT:-us}")" \
    LABWC_FONT_WINDOW_SIZE "$(desktop_shell_config_value "${LABWC_FONT_WINDOW_SIZE:-12}")" \
    LABWC_FONT_MENU_SIZE "$(desktop_shell_config_value "${LABWC_FONT_MENU_SIZE:-13}")" \
    LABWC_FONT_OSD_SIZE "$(desktop_shell_config_value "${LABWC_FONT_OSD_SIZE:-13}")" \
    LABWC_MOUSE_POINTER_SPEED "$(desktop_shell_config_value "${LABWC_MOUSE_POINTER_SPEED:-0.55}")" \
    LABWC_MOUSE_ACCEL_PROFILE "$(desktop_shell_config_value "${LABWC_MOUSE_ACCEL_PROFILE:-flat}")" \
    LABWC_WAYBAR_HEIGHT "$(desktop_shell_config_value "${LABWC_WAYBAR_HEIGHT:-46}")" \
    LABWC_WAYBAR_TASKBAR_ICON_SIZE "$(desktop_shell_config_value "${LABWC_WAYBAR_TASKBAR_ICON_SIZE:-18}")" \
    LABWC_WAYBAR_TRAY_ICON_SIZE "$(desktop_shell_config_value "${LABWC_WAYBAR_TRAY_ICON_SIZE:-18}")" \
    LABWC_WAYBAR_FONT_SIZE "$(desktop_shell_config_value "${LABWC_WAYBAR_FONT_SIZE:-15}")" \
    LABWC_WAYBAR_MENU_BUTTON_MIN_WIDTH "$(desktop_shell_config_value "${LABWC_WAYBAR_MENU_BUTTON_MIN_WIDTH:-52}")" \
    LABWC_WAYBAR_MENU_BUTTON_PADDING_X "$(desktop_shell_config_value "${LABWC_WAYBAR_MENU_BUTTON_PADDING_X:-11}")" \
    LABWC_WAYBAR_WORKSPACE_BUTTON_MIN_WIDTH "$(desktop_shell_config_value "${LABWC_WAYBAR_WORKSPACE_BUTTON_MIN_WIDTH:-26}")" \
    LABWC_WAYBAR_WORKSPACE_BUTTON_PADDING_X "$(desktop_shell_config_value "${LABWC_WAYBAR_WORKSPACE_BUTTON_PADDING_X:-10}")" \
    LABWC_WAYBAR_TASKBAR_BUTTON_MIN_WIDTH "$(desktop_shell_config_value "${LABWC_WAYBAR_TASKBAR_BUTTON_MIN_WIDTH:-0}")" \
    LABWC_WAYBAR_TASKBAR_BUTTON_PADDING_X "$(desktop_shell_config_value "${LABWC_WAYBAR_TASKBAR_BUTTON_PADDING_X:-4}")" \
    LABWC_WAYBAR_INTERNAL_HEIGHT "$(desktop_shell_config_value "${LABWC_WAYBAR_INTERNAL_HEIGHT:-${LABWC_WAYBAR_HEIGHT:-46}}")" \
    LABWC_WAYBAR_INTERNAL_TASKBAR_ICON_SIZE "$(desktop_shell_config_value "${LABWC_WAYBAR_INTERNAL_TASKBAR_ICON_SIZE:-${LABWC_WAYBAR_TASKBAR_ICON_SIZE:-18}}")" \
    LABWC_WAYBAR_INTERNAL_TRAY_ICON_SIZE "$(desktop_shell_config_value "${LABWC_WAYBAR_INTERNAL_TRAY_ICON_SIZE:-${LABWC_WAYBAR_TRAY_ICON_SIZE:-18}}")" \
    LABWC_WAYBAR_INTERNAL_FONT_SIZE "$(desktop_shell_config_value "${LABWC_WAYBAR_INTERNAL_FONT_SIZE:-${LABWC_WAYBAR_FONT_SIZE:-15}}")" \
    LABWC_WAYBAR_INTERNAL_MENU_BUTTON_MIN_WIDTH "$(desktop_shell_config_value "${LABWC_WAYBAR_INTERNAL_MENU_BUTTON_MIN_WIDTH:-${LABWC_WAYBAR_MENU_BUTTON_MIN_WIDTH:-52}}")" \
    LABWC_WAYBAR_INTERNAL_MENU_BUTTON_PADDING_X "$(desktop_shell_config_value "${LABWC_WAYBAR_INTERNAL_MENU_BUTTON_PADDING_X:-${LABWC_WAYBAR_MENU_BUTTON_PADDING_X:-11}}")" \
    LABWC_WAYBAR_INTERNAL_WORKSPACE_BUTTON_MIN_WIDTH "$(desktop_shell_config_value "${LABWC_WAYBAR_INTERNAL_WORKSPACE_BUTTON_MIN_WIDTH:-${LABWC_WAYBAR_WORKSPACE_BUTTON_MIN_WIDTH:-26}}")" \
    LABWC_WAYBAR_INTERNAL_WORKSPACE_BUTTON_PADDING_X "$(desktop_shell_config_value "${LABWC_WAYBAR_INTERNAL_WORKSPACE_BUTTON_PADDING_X:-${LABWC_WAYBAR_WORKSPACE_BUTTON_PADDING_X:-10}}")" \
    LABWC_WAYBAR_INTERNAL_TASKBAR_BUTTON_MIN_WIDTH "$(desktop_shell_config_value "${LABWC_WAYBAR_INTERNAL_TASKBAR_BUTTON_MIN_WIDTH:-${LABWC_WAYBAR_TASKBAR_BUTTON_MIN_WIDTH:-0}}")" \
    LABWC_WAYBAR_INTERNAL_TASKBAR_BUTTON_PADDING_X "$(desktop_shell_config_value "${LABWC_WAYBAR_INTERNAL_TASKBAR_BUTTON_PADDING_X:-${LABWC_WAYBAR_TASKBAR_BUTTON_PADDING_X:-4}}")" \
    LABWC_WAYBAR_INTERNAL_APP_BUTTON_MIN_WIDTH "$(desktop_shell_config_value "${LABWC_WAYBAR_INTERNAL_APP_BUTTON_MIN_WIDTH:-28}")" \
    LABWC_WAYBAR_INTERNAL_APP_BUTTON_PADDING_X "$(desktop_shell_config_value "${LABWC_WAYBAR_INTERNAL_APP_BUTTON_PADDING_X:-7}")" \
    LABWC_WAYBAR_INTERNAL_STATUS_MODULE_MIN_WIDTH "$(desktop_shell_config_value "${LABWC_WAYBAR_INTERNAL_STATUS_MODULE_MIN_WIDTH:-46}")" \
    LABWC_WAYBAR_INTERNAL_STATUS_MODULE_PADDING_X "$(desktop_shell_config_value "${LABWC_WAYBAR_INTERNAL_STATUS_MODULE_PADDING_X:-4}")" \
    LABWC_WAYBAR_INTERNAL_QUICK_CONTROL_GROUP_PADDING_X "$(desktop_shell_config_value "${LABWC_WAYBAR_INTERNAL_QUICK_CONTROL_GROUP_PADDING_X:-1}")" \
    LABWC_WAYBAR_INTERNAL_QUICK_CONTROL_BUTTON_MIN_WIDTH "$(desktop_shell_config_value "${LABWC_WAYBAR_INTERNAL_QUICK_CONTROL_BUTTON_MIN_WIDTH:-22}")" \
    LABWC_WAYBAR_INTERNAL_QUICK_CONTROL_BUTTON_PADDING_X "$(desktop_shell_config_value "${LABWC_WAYBAR_INTERNAL_QUICK_CONTROL_BUTTON_PADDING_X:-4}")" \
    LABWC_WAYBAR_INTERNAL_SESSION_BUTTON_MIN_WIDTH "$(desktop_shell_config_value "${LABWC_WAYBAR_INTERNAL_SESSION_BUTTON_MIN_WIDTH:-24}")" \
    LABWC_WAYBAR_INTERNAL_SESSION_BUTTON_PADDING_X "$(desktop_shell_config_value "${LABWC_WAYBAR_INTERNAL_SESSION_BUTTON_PADDING_X:-6}")" \
    LABWC_GTK_FONT_SIZE "$(desktop_shell_config_value "${LABWC_GTK_FONT_SIZE:-12}")" \
    LABWC_QT_FONT_SIZE "$(desktop_shell_config_value "${LABWC_QT_FONT_SIZE:-11}")" \
    LABWC_QT_FIXED_FONT_SIZE "$(desktop_shell_config_value "${LABWC_QT_FIXED_FONT_SIZE:-12}")" \
    LABWC_GREETER_FONT_SIZE "$(desktop_shell_config_value "${LABWC_GREETER_FONT_SIZE:-14}")" \
    LABWC_GREETER_CLOCK_FONT_SIZE "$(desktop_shell_config_value "${LABWC_GREETER_CLOCK_FONT_SIZE:-104}")" \
    LABWC_GREETER_PANEL_MARGIN "$(desktop_shell_config_value "${LABWC_GREETER_PANEL_MARGIN:-}")" \
    LABWC_GREETER_PANEL_MIN_WIDTH "$(desktop_shell_config_value "${LABWC_GREETER_PANEL_MIN_WIDTH:-}")" \
    LABWC_GREETER_PANEL_PADDING_Y "$(desktop_shell_config_value "${LABWC_GREETER_PANEL_PADDING_Y:-}")" \
    LABWC_GREETER_PANEL_PADDING_X "$(desktop_shell_config_value "${LABWC_GREETER_PANEL_PADDING_X:-}")" \
    LABWC_GREETER_CONTROL_MIN_HEIGHT "$(desktop_shell_config_value "${LABWC_GREETER_CONTROL_MIN_HEIGHT:-}")" \
    LABWC_GREETER_ENTRY_MIN_WIDTH "$(desktop_shell_config_value "${LABWC_GREETER_ENTRY_MIN_WIDTH:-}")" \
    LABWC_GREETER_SHELL_MIN_WIDTH "$(desktop_shell_config_value "${LABWC_GREETER_SHELL_MIN_WIDTH:-}")" \
    LABWC_GREETER_BUTTON_MIN_WIDTH "$(desktop_shell_config_value "${LABWC_GREETER_BUTTON_MIN_WIDTH:-}")" \
    LABWC_FUZZEL_WIDTH "$(desktop_shell_config_value "${LABWC_FUZZEL_WIDTH:-36}")" \
    LABWC_FUZZEL_LINES "$(desktop_shell_config_value "${LABWC_FUZZEL_LINES:-15}")" \
    LABWC_FUZZEL_MENU_WIDTH "$(desktop_shell_config_value "${LABWC_FUZZEL_MENU_WIDTH:-22}")" \
    LABWC_FUZZEL_MENU_LINES "$(desktop_shell_config_value "${LABWC_FUZZEL_MENU_LINES:-5}")" \
    LABWC_FUZZEL_FONT_SIZE "$(desktop_shell_config_value "${LABWC_FUZZEL_FONT_SIZE:-15}")" \
    LABWC_FUZZEL_INTERNAL_WIDTH "$(desktop_shell_config_value "${LABWC_FUZZEL_INTERNAL_WIDTH:-28}")" \
    LABWC_FUZZEL_INTERNAL_LINES "$(desktop_shell_config_value "${LABWC_FUZZEL_INTERNAL_LINES:-10}")" \
    LABWC_FUZZEL_INTERNAL_MENU_WIDTH "$(desktop_shell_config_value "${LABWC_FUZZEL_INTERNAL_MENU_WIDTH:-18}")" \
    LABWC_FUZZEL_INTERNAL_MENU_LINES "$(desktop_shell_config_value "${LABWC_FUZZEL_INTERNAL_MENU_LINES:-8}")" \
    LABWC_FUZZEL_INTERNAL_FONT_SIZE "$(desktop_shell_config_value "${LABWC_FUZZEL_INTERNAL_FONT_SIZE:-9}")" \
    LABWC_FUZZEL_INTERNAL_HORIZONTAL_PAD "$(desktop_shell_config_value "${LABWC_FUZZEL_INTERNAL_HORIZONTAL_PAD:-10}")" \
    LABWC_FUZZEL_INTERNAL_VERTICAL_PAD "$(desktop_shell_config_value "${LABWC_FUZZEL_INTERNAL_VERTICAL_PAD:-6}")" \
    LABWC_FUZZEL_INTERNAL_INNER_PAD "$(desktop_shell_config_value "${LABWC_FUZZEL_INTERNAL_INNER_PAD:-4}")" \
    LABWC_FUZZEL_INTERNAL_LINE_HEIGHT "$(desktop_shell_config_value "${LABWC_FUZZEL_INTERNAL_LINE_HEIGHT:-16}")" \
    LABWC_FUZZEL_CONTAINER_MANAGEMENT_WIDTH "$(desktop_shell_config_value "${LABWC_FUZZEL_CONTAINER_MANAGEMENT_WIDTH:-${LABWC_FUZZEL_MENU_WIDTH:-22}}")" \
    LABWC_FUZZEL_CONTAINER_MANAGEMENT_LINES "$(desktop_shell_config_value "${LABWC_FUZZEL_CONTAINER_MANAGEMENT_LINES:-${LABWC_FUZZEL_MENU_LINES:-5}}")" \
    LABWC_FUZZEL_CONTAINER_MANAGEMENT_FONT_SIZE "$(desktop_shell_config_value "${LABWC_FUZZEL_CONTAINER_MANAGEMENT_FONT_SIZE:-${LABWC_FUZZEL_FONT_SIZE:-15}}")" \
    LABWC_FUZZEL_REMOTE_DESKTOP_WIDTH "$(desktop_shell_config_value "${LABWC_FUZZEL_REMOTE_DESKTOP_WIDTH:-${LABWC_FUZZEL_MENU_WIDTH:-22}}")" \
    LABWC_FUZZEL_REMOTE_DESKTOP_LINES "$(desktop_shell_config_value "${LABWC_FUZZEL_REMOTE_DESKTOP_LINES:-${LABWC_FUZZEL_MENU_LINES:-5}}")" \
    LABWC_FUZZEL_REMOTE_DESKTOP_FONT_SIZE "$(desktop_shell_config_value "${LABWC_FUZZEL_REMOTE_DESKTOP_FONT_SIZE:-${LABWC_FUZZEL_FONT_SIZE:-15}}")" \
    LABWC_FUZZEL_ENDPOINT_SECURITY_WIDTH "$(desktop_shell_config_value "${LABWC_FUZZEL_ENDPOINT_SECURITY_WIDTH:-${LABWC_FUZZEL_MENU_WIDTH:-22}}")" \
    LABWC_FUZZEL_ENDPOINT_SECURITY_LINES "$(desktop_shell_config_value "${LABWC_FUZZEL_ENDPOINT_SECURITY_LINES:-${LABWC_FUZZEL_MENU_LINES:-5}}")" \
    LABWC_FUZZEL_ENDPOINT_SECURITY_FONT_SIZE "$(desktop_shell_config_value "${LABWC_FUZZEL_ENDPOINT_SECURITY_FONT_SIZE:-${LABWC_FUZZEL_FONT_SIZE:-15}}")" \
    LABWC_FUZZEL_USERS_GROUPS_WIDTH "$(desktop_shell_config_value "${LABWC_FUZZEL_USERS_GROUPS_WIDTH:-${LABWC_FUZZEL_MENU_WIDTH:-22}}")" \
    LABWC_FUZZEL_USERS_GROUPS_LINES "$(desktop_shell_config_value "${LABWC_FUZZEL_USERS_GROUPS_LINES:-${LABWC_FUZZEL_MENU_LINES:-5}}")" \
    LABWC_FUZZEL_USERS_GROUPS_FONT_SIZE "$(desktop_shell_config_value "${LABWC_FUZZEL_USERS_GROUPS_FONT_SIZE:-${LABWC_FUZZEL_FONT_SIZE:-15}}")" \
    LABWC_FUZZEL_NETWORK_MANAGEMENT_WIDTH "$(desktop_shell_config_value "${LABWC_FUZZEL_NETWORK_MANAGEMENT_WIDTH:-${LABWC_FUZZEL_MENU_WIDTH:-22}}")" \
    LABWC_FUZZEL_NETWORK_MANAGEMENT_LINES "$(desktop_shell_config_value "${LABWC_FUZZEL_NETWORK_MANAGEMENT_LINES:-${LABWC_FUZZEL_MENU_LINES:-5}}")" \
    LABWC_FUZZEL_NETWORK_MANAGEMENT_FONT_SIZE "$(desktop_shell_config_value "${LABWC_FUZZEL_NETWORK_MANAGEMENT_FONT_SIZE:-${LABWC_FUZZEL_FONT_SIZE:-15}}")" \
    LABWC_FUZZEL_FIREWALL_SECURITY_WIDTH "$(desktop_shell_config_value "${LABWC_FUZZEL_FIREWALL_SECURITY_WIDTH:-${LABWC_FUZZEL_MENU_WIDTH:-22}}")" \
    LABWC_FUZZEL_FIREWALL_SECURITY_LINES "$(desktop_shell_config_value "${LABWC_FUZZEL_FIREWALL_SECURITY_LINES:-${LABWC_FUZZEL_MENU_LINES:-5}}")" \
    LABWC_FUZZEL_FIREWALL_SECURITY_FONT_SIZE "$(desktop_shell_config_value "${LABWC_FUZZEL_FIREWALL_SECURITY_FONT_SIZE:-${LABWC_FUZZEL_FONT_SIZE:-15}}")" \
    LABWC_FUZZEL_SYSTEM_CONFIGURATION_WIDTH "$(desktop_shell_config_value "${LABWC_FUZZEL_SYSTEM_CONFIGURATION_WIDTH:-${LABWC_FUZZEL_MENU_WIDTH:-22}}")" \
    LABWC_FUZZEL_SYSTEM_CONFIGURATION_LINES "$(desktop_shell_config_value "${LABWC_FUZZEL_SYSTEM_CONFIGURATION_LINES:-${LABWC_FUZZEL_MENU_LINES:-5}}")" \
    LABWC_FUZZEL_SYSTEM_CONFIGURATION_FONT_SIZE "$(desktop_shell_config_value "${LABWC_FUZZEL_SYSTEM_CONFIGURATION_FONT_SIZE:-${LABWC_FUZZEL_FONT_SIZE:-15}}")" \
    LABWC_FUZZEL_PHONE_MANAGEMENT_WIDTH "$(desktop_shell_config_value "${LABWC_FUZZEL_PHONE_MANAGEMENT_WIDTH:-${LABWC_FUZZEL_MENU_WIDTH:-22}}")" \
    LABWC_FUZZEL_PHONE_MANAGEMENT_LINES "$(desktop_shell_config_value "${LABWC_FUZZEL_PHONE_MANAGEMENT_LINES:-${LABWC_FUZZEL_MENU_LINES:-5}}")" \
    LABWC_FUZZEL_PHONE_MANAGEMENT_FONT_SIZE "$(desktop_shell_config_value "${LABWC_FUZZEL_PHONE_MANAGEMENT_FONT_SIZE:-${LABWC_FUZZEL_FONT_SIZE:-15}}")" \
    LABWC_FUZZEL_BACKUP_RECOVERY_WIDTH "$(desktop_shell_config_value "${LABWC_FUZZEL_BACKUP_RECOVERY_WIDTH:-${LABWC_FUZZEL_MENU_WIDTH:-22}}")" \
    LABWC_FUZZEL_BACKUP_RECOVERY_LINES "$(desktop_shell_config_value "${LABWC_FUZZEL_BACKUP_RECOVERY_LINES:-${LABWC_FUZZEL_MENU_LINES:-5}}")" \
    LABWC_FUZZEL_BACKUP_RECOVERY_FONT_SIZE "$(desktop_shell_config_value "${LABWC_FUZZEL_BACKUP_RECOVERY_FONT_SIZE:-${LABWC_FUZZEL_FONT_SIZE:-15}}")" \
    LABWC_FUZZEL_HARDWARE_PERIPHERALS_WIDTH "$(desktop_shell_config_value "${LABWC_FUZZEL_HARDWARE_PERIPHERALS_WIDTH:-${LABWC_FUZZEL_MENU_WIDTH:-22}}")" \
    LABWC_FUZZEL_HARDWARE_PERIPHERALS_LINES "$(desktop_shell_config_value "${LABWC_FUZZEL_HARDWARE_PERIPHERALS_LINES:-${LABWC_FUZZEL_MENU_LINES:-5}}")" \
    LABWC_FUZZEL_HARDWARE_PERIPHERALS_FONT_SIZE "$(desktop_shell_config_value "${LABWC_FUZZEL_HARDWARE_PERIPHERALS_FONT_SIZE:-${LABWC_FUZZEL_FONT_SIZE:-15}}")" \
    LABWC_CRYSTAL_DOCK_MINIMUM_ICON_SIZE "$(desktop_shell_config_value "${LABWC_CRYSTAL_DOCK_MINIMUM_ICON_SIZE:-50}")" \
    LABWC_CRYSTAL_DOCK_MAXIMUM_ICON_SIZE "$(desktop_shell_config_value "${LABWC_CRYSTAL_DOCK_MAXIMUM_ICON_SIZE:-80}")" \
    LABWC_CRYSTAL_DOCK_TOOLTIP_FONT_SIZE "$(desktop_shell_config_value "${LABWC_CRYSTAL_DOCK_TOOLTIP_FONT_SIZE:-13}")" \
    LABWC_CRYSTAL_DOCK_APP_MENU_ICON_SIZE "$(desktop_shell_config_value "${LABWC_CRYSTAL_DOCK_APP_MENU_ICON_SIZE:-40}")" \
    LABWC_CRYSTAL_DOCK_APP_MENU_FONT_SIZE "$(desktop_shell_config_value "${LABWC_CRYSTAL_DOCK_APP_MENU_FONT_SIZE:-15}")" \
    LABWC_CRYSTAL_DOCK_CLOCK_FONT_SCALE_FACTOR "$(desktop_shell_config_value "${LABWC_CRYSTAL_DOCK_CLOCK_FONT_SCALE_FACTOR:-1.0}")" \
    LABWC_ENABLE_WAYBAR "$(desktop_shell_config_value "${LABWC_ENABLE_WAYBAR:-true}")" \
    LABWC_ENABLE_KANSHI "$(desktop_shell_config_value "${LABWC_ENABLE_KANSHI:-true}")" \
    LABWC_ENABLE_MAKO "$(desktop_shell_config_value "${LABWC_ENABLE_MAKO:-true}")" \
    LABWC_ENABLE_SWAYIDLE "$(desktop_shell_config_value "${LABWC_ENABLE_SWAYIDLE:-true}")" \
    LABWC_ENABLE_SWAYBG "$(desktop_shell_config_value "${LABWC_ENABLE_SWAYBG:-true}")" \
    LABWC_ENABLE_POLKIT_AGENT "$(desktop_shell_config_value "${LABWC_ENABLE_POLKIT_AGENT:-true}")" \
    LABWC_ENABLE_XDG_DESKTOP_PORTAL "$(desktop_shell_config_value "${LABWC_ENABLE_XDG_DESKTOP_PORTAL:-true}")" \
    LABWC_IDLE_LOCK_SECONDS "$(desktop_shell_config_value "${LABWC_IDLE_LOCK_SECONDS:-1800}")" \
    LABWC_IDLE_DPMS_SECONDS "$(desktop_shell_config_value "${LABWC_IDLE_DPMS_SECONDS:-3600}")" \
    LABWC_IDLE_SUSPEND_SECONDS "$(desktop_shell_config_value "${LABWC_IDLE_SUSPEND_SECONDS:-0}")" \
    LABWC_CURSOR_THEME "$(desktop_shell_config_value "${LABWC_CURSOR_THEME:-Adwaita}")" \
    LABWC_CURSOR_SIZE "$(desktop_shell_config_value "${LABWC_CURSOR_SIZE:-24}")" \
    LABWC_GTK_THEME "$(desktop_shell_config_value "${LABWC_GTK_THEME:-Adwaita}")" \
    LABWC_GDK_BACKEND "$(desktop_shell_config_value "${LABWC_GDK_BACKEND:-wayland}")" \
    LABWC_QT_QPA_PLATFORM "$(desktop_shell_config_value "${LABWC_QT_QPA_PLATFORM:-wayland}")" \
    LABWC_SDL_VIDEODRIVER "$(desktop_shell_config_value "${LABWC_SDL_VIDEODRIVER:-wayland}")" \
    LABWC_CLUTTER_BACKEND "$(desktop_shell_config_value "${LABWC_CLUTTER_BACKEND:-wayland}")" \
    LABWC_ICON_THEME "$(desktop_shell_config_value "${LABWC_ICON_THEME:-Papirus-Dark}")" \
    LABWC_QT_PLATFORMTHEME "$(desktop_shell_config_value "${LABWC_QT_PLATFORMTHEME:-qt6ct}")" \
    LABWC_QT_STYLE_OVERRIDE "$(desktop_shell_config_value "${LABWC_QT_STYLE_OVERRIDE:-adwaita-dark}")" \
    LABWC_QBITTORRENT_USER "$(desktop_shell_config_value "$ACCOUNT_USERNAME")" \
    LABWC_QBITTORRENT_ROOT "$(desktop_shell_config_value "$qbittorrent_root")" \
    LABWC_QBITTORRENT_PORT "$(desktop_shell_config_value "${LABWC_QBITTORRENT_PORT:-50309}")"
  desktop_log "rendered_labwc_default_config target=${defaults_path} primary_uid=${primary_account_uid} primary_gid=${primary_account_gid}"
}

desktop_render_greetd_config() {
  desktop_render_role_target_template \
    "etc/greetd/config.toml.tmpl" \
    "/etc/greetd/config.toml" \
    0644 \
    LABWC_GREETER_VT "${LABWC_GREETER_VT:-1}" \
    LABWC_GREETER_COMMAND_ESCAPED "$(desktop_toml_escape "${LABWC_GREETER_COMMAND:-/usr/local/bin/labwc-greeter-session}")" \
    LABWC_GREETER_USER_ESCAPED "$(desktop_toml_escape "${LABWC_GREETER_USER:-greeter}")"
  desktop_log "rendered_greetd_config user=${LABWC_GREETER_USER:-greeter} vt=${LABWC_GREETER_VT:-1}"
}

desktop_validate_cargo_policy() {
  : "${DEVOPS_CARGO_RUSTC_WRAPPER:?DEVOPS_CARGO_RUSTC_WRAPPER must be set by the desktop host profile}"
  : "${DEVOPS_CARGO_TARGET_TRIPLE:?DEVOPS_CARGO_TARGET_TRIPLE must be set by the desktop host profile}"
  : "${DEVOPS_CARGO_TARGET_LINKER:?DEVOPS_CARGO_TARGET_LINKER must be set by the desktop host profile}"
  : "${DEVOPS_CARGO_TARGET_CPU:?DEVOPS_CARGO_TARGET_CPU must be set by the desktop host profile}"
  : "${DEVOPS_CARGO_LINKER_ARGUMENT:?DEVOPS_CARGO_LINKER_ARGUMENT must be set by the desktop host profile}"

  [ "$DEVOPS_CARGO_RUSTC_WRAPPER" = sccache ] ||
    desktop_fatal "DEVOPS_CARGO_RUSTC_WRAPPER must remain sccache"
  [ "$DEVOPS_CARGO_TARGET_TRIPLE" = x86_64-unknown-linux-gnu ] ||
    desktop_fatal "DEVOPS_CARGO_TARGET_TRIPLE must remain x86_64-unknown-linux-gnu"
  [ "$DEVOPS_CARGO_TARGET_LINKER" = clang-24 ] ||
    desktop_fatal "DEVOPS_CARGO_TARGET_LINKER must remain clang-24"
  [ "$DEVOPS_CARGO_LINKER_ARGUMENT" = -fuse-ld=mold ] ||
    desktop_fatal "DEVOPS_CARGO_LINKER_ARGUMENT must remain -fuse-ld=mold"
  if ! printf '%s\n' "$DEVOPS_CARGO_TARGET_CPU" |
    LC_ALL=C grep -Eq '^[a-z0-9][a-z0-9_.-]*$'
  then
    desktop_fatal "DEVOPS_CARGO_TARGET_CPU must be a lowercase rustc target CPU token"
  fi
}

desktop_render_cargo_config() {
  desktop_validate_cargo_policy
  desktop_render_role_target_template \
    "etc/skel-desktop/.config/cargo/config.toml.tmpl" \
    "/etc/skel-desktop/.config/cargo/config.toml" \
    0644 \
    DEVOPS_CARGO_RUSTC_WRAPPER "$DEVOPS_CARGO_RUSTC_WRAPPER" \
    DEVOPS_CARGO_TARGET_TRIPLE "$DEVOPS_CARGO_TARGET_TRIPLE" \
    DEVOPS_CARGO_TARGET_LINKER "$DEVOPS_CARGO_TARGET_LINKER" \
    DEVOPS_CARGO_TARGET_CPU "$DEVOPS_CARGO_TARGET_CPU" \
    DEVOPS_CARGO_LINKER_ARGUMENT "$DEVOPS_CARGO_LINKER_ARGUMENT"
  desktop_log \
    "rendered_cargo_config target_cpu=${DEVOPS_CARGO_TARGET_CPU} jobs=cargo-default"
}

desktop_render_labwc_rc_xml() {
  workspace_count=${LABWC_WORKSPACE_COUNT:-4}
  rc_path=/etc/skel-desktop/.config/labwc/rc.xml

  desktop_render_role_target_template_deferred \
    "etc/skel-desktop/.config/labwc/rc.xml.tmpl" \
    "$rc_path" \
    0644 \
    LABWC_WORKSPACE_COUNT "$workspace_count" \
    LABWC_ICON_THEME "$(desktop_xml_attribute_escape "${LABWC_ICON_THEME:-Papirus-Dark}")" \
    LABWC_FILE_MANAGER_COMMAND "$(desktop_xml_attribute_escape "${LABWC_FILE_MANAGER_COMMAND:-thunar}")" \
    LABWC_AUDIO_CONTROL_COMMAND "$(desktop_xml_attribute_escape "${LABWC_AUDIO_CONTROL_COMMAND:-pavucontrol}")" \
    LABWC_KEYBOARD_REPEAT_RATE "${LABWC_KEYBOARD_REPEAT_RATE:-40}" \
    LABWC_KEYBOARD_REPEAT_DELAY "${LABWC_KEYBOARD_REPEAT_DELAY:-250}" \
    LABWC_FONT_WINDOW_SIZE "${LABWC_FONT_WINDOW_SIZE:-12}" \
    LABWC_FONT_MENU_SIZE "${LABWC_FONT_MENU_SIZE:-13}" \
    LABWC_FONT_OSD_SIZE "${LABWC_FONT_OSD_SIZE:-13}" \
    LABWC_MOUSE_POINTER_SPEED "${LABWC_MOUSE_POINTER_SPEED:-0.55}" \
    LABWC_MOUSE_ACCEL_PROFILE "${LABWC_MOUSE_ACCEL_PROFILE:-flat}"
  desktop_replace_block_placeholder_in_target \
    "$rc_path" \
    "__INSTALLER_LABWC_WORKSPACE_NAME_LINES__" \
    "$(desktop_labwc_workspace_name_lines)"
  desktop_replace_block_placeholder_in_target \
    "$rc_path" \
    "__INSTALLER_LABWC_WORKSPACE_KEYBIND_LINES__" \
    "$(desktop_labwc_workspace_keybind_lines)"
  desktop_replace_block_placeholder_in_target \
    "$rc_path" \
    "__INSTALLER_LABWC_RECORDING_KEYBIND_LINES__" \
    "$(desktop_labwc_recording_keybind_lines)"
  desktop_assert_role_target_template_resolved "etc/skel-desktop/.config/labwc/rc.xml.tmpl" "$rc_path"
  desktop_log "rendered_labwc_rc_xml workspaces=${workspace_count}"
}

desktop_render_waybar_config() {
  waybar_path=/etc/skel-desktop/.config/waybar/config

  desktop_render_role_target_template_deferred \
    "etc/skel-desktop/.config/waybar/config.tmpl" \
    "$waybar_path" \
    0644 \
    LABWC_WAYBAR_INTERNAL_OUTPUTS "$(desktop_waybar_internal_outputs_json)" \
    LABWC_WAYBAR_EXTERNAL_OUTPUTS "$(desktop_waybar_external_outputs_json)" \
    LABWC_WAYBAR_INTERNAL_HEIGHT "${LABWC_WAYBAR_INTERNAL_HEIGHT:-${LABWC_WAYBAR_HEIGHT:-46}}" \
    LABWC_WAYBAR_INTERNAL_TASKBAR_ICON_SIZE "${LABWC_WAYBAR_INTERNAL_TASKBAR_ICON_SIZE:-${LABWC_WAYBAR_TASKBAR_ICON_SIZE:-18}}" \
    LABWC_WAYBAR_INTERNAL_TRAY_ICON_SIZE "${LABWC_WAYBAR_INTERNAL_TRAY_ICON_SIZE:-${LABWC_WAYBAR_TRAY_ICON_SIZE:-18}}" \
    LABWC_WAYBAR_HEIGHT "${LABWC_WAYBAR_HEIGHT:-46}" \
    LABWC_WAYBAR_TASKBAR_ICON_SIZE "${LABWC_WAYBAR_TASKBAR_ICON_SIZE:-18}" \
    LABWC_WAYBAR_TRAY_ICON_SIZE "${LABWC_WAYBAR_TRAY_ICON_SIZE:-18}" \
    LABWC_WAYBAR_MODULES_LEFT "$(desktop_waybar_modules_left_json)" \
    LABWC_WAYBAR_MODULES_RIGHT_INTERNAL "$(desktop_waybar_modules_right_internal_json)" \
    LABWC_WAYBAR_MODULES_RIGHT_EXTERNAL "$(desktop_waybar_modules_right_json)" \
    LABWC_MANAGED_APP_DEFAULT_EXEC "$(desktop_double_quote_escape "${LABWC_MANAGED_APP_DEFAULT_EXEC:?LABWC_MANAGED_APP_DEFAULT_EXEC must be set by the desktop host profile}")" \
    LABWC_FILE_MANAGER_COMMAND "$(desktop_double_quote_escape "${LABWC_FILE_MANAGER_COMMAND:-thunar}")" \
    LABWC_CALENDAR_COMMAND "$(desktop_double_quote_escape "${LABWC_CALENDAR_COMMAND:-labwc-calendar}")" \
    LABWC_AUDIO_CONTROL_COMMAND "$(desktop_double_quote_escape "${LABWC_AUDIO_CONTROL_COMMAND:-pavucontrol}")" \
    LABWC_WAYBAR_PULSEAUDIO_RIGHT_CLICK_COMMAND "$(desktop_waybar_pulseaudio_right_click_command)" \
    LABWC_BRIGHTNESS_CONTROL_COMMAND "$(desktop_double_quote_escape "${LABWC_BRIGHTNESS_CONTROL_COMMAND:-labwc-brightness-control}")" \
    LABWC_CAPTURE_COMMAND "$(desktop_double_quote_escape "${LABWC_CAPTURE_COMMAND:-labwc-capture}")" \
    LABWC_POWER_SETTINGS_COMMAND "$(desktop_double_quote_escape "${LABWC_POWER_SETTINGS_COMMAND:-labwc-power-settings}")"

  desktop_assert_role_target_template_resolved "etc/skel-desktop/.config/waybar/config.tmpl" "$waybar_path"
  desktop_log "rendered_waybar_config native_workspaces=true internal_drawer=true"
}

desktop_render_waybar_style() {
  desktop_render_role_target_template \
    "etc/skel-desktop/.config/waybar/style.css.tmpl" \
    "/etc/skel-desktop/.config/waybar/style.css" \
    0644 \
    LABWC_WAYBAR_FONT_SIZE "${LABWC_WAYBAR_FONT_SIZE:-15}" \
    LABWC_WAYBAR_TOOLTIP_FONT_SIZE "${LABWC_WAYBAR_TOOLTIP_FONT_SIZE:-15}" \
    LABWC_WAYBAR_TOOLTIP_PADDING_Y "${LABWC_WAYBAR_TOOLTIP_PADDING_Y:-7}" \
    LABWC_WAYBAR_TOOLTIP_PADDING_X "${LABWC_WAYBAR_TOOLTIP_PADDING_X:-10}" \
    LABWC_WAYBAR_MENU_BUTTON_MIN_WIDTH "${LABWC_WAYBAR_MENU_BUTTON_MIN_WIDTH:-52}" \
    LABWC_WAYBAR_MENU_BUTTON_PADDING_X "${LABWC_WAYBAR_MENU_BUTTON_PADDING_X:-11}" \
    LABWC_WAYBAR_WORKSPACE_BUTTON_MIN_WIDTH "${LABWC_WAYBAR_WORKSPACE_BUTTON_MIN_WIDTH:-26}" \
    LABWC_WAYBAR_WORKSPACE_BUTTON_PADDING_X "${LABWC_WAYBAR_WORKSPACE_BUTTON_PADDING_X:-10}" \
    LABWC_WAYBAR_TASKBAR_BUTTON_MIN_WIDTH "${LABWC_WAYBAR_TASKBAR_BUTTON_MIN_WIDTH:-0}" \
    LABWC_WAYBAR_TASKBAR_BUTTON_PADDING_X "${LABWC_WAYBAR_TASKBAR_BUTTON_PADDING_X:-4}" \
    LABWC_WAYBAR_INTERNAL_FONT_SIZE "${LABWC_WAYBAR_INTERNAL_FONT_SIZE:-${LABWC_WAYBAR_FONT_SIZE:-15}}" \
    LABWC_WAYBAR_INTERNAL_MENU_BUTTON_MIN_WIDTH "${LABWC_WAYBAR_INTERNAL_MENU_BUTTON_MIN_WIDTH:-${LABWC_WAYBAR_MENU_BUTTON_MIN_WIDTH:-52}}" \
    LABWC_WAYBAR_INTERNAL_MENU_BUTTON_PADDING_X "${LABWC_WAYBAR_INTERNAL_MENU_BUTTON_PADDING_X:-${LABWC_WAYBAR_MENU_BUTTON_PADDING_X:-11}}" \
    LABWC_WAYBAR_INTERNAL_WORKSPACE_BUTTON_MIN_WIDTH "${LABWC_WAYBAR_INTERNAL_WORKSPACE_BUTTON_MIN_WIDTH:-${LABWC_WAYBAR_WORKSPACE_BUTTON_MIN_WIDTH:-26}}" \
    LABWC_WAYBAR_INTERNAL_WORKSPACE_BUTTON_PADDING_X "${LABWC_WAYBAR_INTERNAL_WORKSPACE_BUTTON_PADDING_X:-${LABWC_WAYBAR_WORKSPACE_BUTTON_PADDING_X:-10}}" \
    LABWC_WAYBAR_INTERNAL_TASKBAR_BUTTON_MIN_WIDTH "${LABWC_WAYBAR_INTERNAL_TASKBAR_BUTTON_MIN_WIDTH:-${LABWC_WAYBAR_TASKBAR_BUTTON_MIN_WIDTH:-0}}" \
    LABWC_WAYBAR_INTERNAL_TASKBAR_BUTTON_PADDING_X "${LABWC_WAYBAR_INTERNAL_TASKBAR_BUTTON_PADDING_X:-${LABWC_WAYBAR_TASKBAR_BUTTON_PADDING_X:-4}}" \
    LABWC_WAYBAR_INTERNAL_APP_BUTTON_MIN_WIDTH "${LABWC_WAYBAR_INTERNAL_APP_BUTTON_MIN_WIDTH:-28}" \
    LABWC_WAYBAR_INTERNAL_APP_BUTTON_PADDING_X "${LABWC_WAYBAR_INTERNAL_APP_BUTTON_PADDING_X:-7}" \
    LABWC_WAYBAR_INTERNAL_STATUS_MODULE_MIN_WIDTH "${LABWC_WAYBAR_INTERNAL_STATUS_MODULE_MIN_WIDTH:-46}" \
    LABWC_WAYBAR_INTERNAL_STATUS_MODULE_PADDING_X "${LABWC_WAYBAR_INTERNAL_STATUS_MODULE_PADDING_X:-4}" \
    LABWC_WAYBAR_INTERNAL_QUICK_CONTROL_GROUP_PADDING_X "${LABWC_WAYBAR_INTERNAL_QUICK_CONTROL_GROUP_PADDING_X:-1}" \
    LABWC_WAYBAR_INTERNAL_QUICK_CONTROL_BUTTON_MIN_WIDTH "${LABWC_WAYBAR_INTERNAL_QUICK_CONTROL_BUTTON_MIN_WIDTH:-22}" \
    LABWC_WAYBAR_INTERNAL_QUICK_CONTROL_BUTTON_PADDING_X "${LABWC_WAYBAR_INTERNAL_QUICK_CONTROL_BUTTON_PADDING_X:-4}" \
    LABWC_WAYBAR_INTERNAL_SESSION_BUTTON_MIN_WIDTH "${LABWC_WAYBAR_INTERNAL_SESSION_BUTTON_MIN_WIDTH:-24}" \
    LABWC_WAYBAR_INTERNAL_SESSION_BUTTON_PADDING_X "${LABWC_WAYBAR_INTERNAL_SESSION_BUTTON_PADDING_X:-6}"
  desktop_log "rendered_waybar_style font_size=${LABWC_WAYBAR_FONT_SIZE:-15} internal_font_size=${LABWC_WAYBAR_INTERNAL_FONT_SIZE:-${LABWC_WAYBAR_FONT_SIZE:-15}}"
}

desktop_render_gtkgreet_css() {
  greeter_font_size=${LABWC_GREETER_FONT_SIZE:-17}
  greeter_clock_font_size=${LABWC_GREETER_CLOCK_FONT_SIZE:-104}
  greeter_background_url="file://${LABWC_GREETER_BACKGROUND_PATH:-/usr/share/backgrounds/login/welcome-1920x1080.png}"
  greeter_panel_margin=${LABWC_GREETER_PANEL_MARGIN:-$((greeter_font_size * 2))}
  greeter_panel_min_width=${LABWC_GREETER_PANEL_MIN_WIDTH:-$((greeter_font_size * 44))}
  greeter_panel_padding_y=${LABWC_GREETER_PANEL_PADDING_Y:-$((greeter_font_size * 2))}
  greeter_panel_padding_x=${LABWC_GREETER_PANEL_PADDING_X:-$((greeter_font_size * 2 + 8))}
  greeter_label_font_size=$((greeter_font_size + 2))
  greeter_control_font_size=$((greeter_font_size + 3))
  greeter_control_min_height=${LABWC_GREETER_CONTROL_MIN_HEIGHT:-$((greeter_font_size * 3 + 8))}
  greeter_entry_min_width=${LABWC_GREETER_ENTRY_MIN_WIDTH:-$((greeter_font_size * 34))}
  greeter_shell_min_width=${LABWC_GREETER_SHELL_MIN_WIDTH:-$greeter_entry_min_width}
  greeter_button_min_width=${LABWC_GREETER_BUTTON_MIN_WIDTH:-$((greeter_font_size * 13))}

  desktop_render_role_target_template \
    "etc/greetd/gtkgreet.css" \
    "/etc/greetd/gtkgreet.css" \
    0644 \
    LABWC_GREETER_BACKGROUND_URL "$(desktop_double_quote_escape "$greeter_background_url")" \
    LABWC_GREETER_CLOCK_FONT_SIZE "$greeter_clock_font_size" \
    LABWC_GREETER_PANEL_MARGIN "$greeter_panel_margin" \
    LABWC_GREETER_PANEL_MIN_WIDTH "$greeter_panel_min_width" \
    LABWC_GREETER_PANEL_PADDING_Y "$greeter_panel_padding_y" \
    LABWC_GREETER_PANEL_PADDING_X "$greeter_panel_padding_x" \
    LABWC_GREETER_LABEL_FONT_SIZE "$greeter_label_font_size" \
    LABWC_GREETER_CONTROL_FONT_SIZE "$greeter_control_font_size" \
    LABWC_GREETER_CONTROL_MIN_HEIGHT "$greeter_control_min_height" \
    LABWC_GREETER_ENTRY_MIN_WIDTH "$greeter_entry_min_width" \
    LABWC_GREETER_SHELL_MIN_WIDTH "$greeter_shell_min_width" \
    LABWC_GREETER_BUTTON_MIN_WIDTH "$greeter_button_min_width"
  desktop_log "rendered_gtkgreet_css font_size=${greeter_font_size} clock_font_size=${greeter_clock_font_size} panel_min_width=${greeter_panel_min_width} entry_min_width=${greeter_entry_min_width}"
}

desktop_render_greeter_power_rule() {
  desktop_render_role_target_template \
    "etc/polkit-1/rules.d/10-greetd-power.rules.tmpl" \
    "/etc/polkit-1/rules.d/10-greetd-power.rules" \
    0644 \
    LABWC_GREETER_USER "$(desktop_double_quote_escape "${LABWC_GREETER_USER:-greeter}")"
  desktop_log "rendered_greeter_power_rule user=${LABWC_GREETER_USER:-greeter}"
}

desktop_render_labwc_environment_assets() {
  gsk_renderer_line=$(desktop_optional_env_assignment_line GSK_RENDERER "${LABWC_GSK_RENDERER:-opengl}")

  desktop_render_role_target_template \
    "etc/skel-desktop/.config/labwc/environment.tmpl" \
    "/etc/skel-desktop/.config/labwc/environment" \
    0644 \
    LABWC_WLR_RENDERER "${LABWC_WLR_RENDERER:-gles2}" \
    LABWC_GDK_DISABLE "${LABWC_GDK_DISABLE:-vulkan}" \
    LABWC_WLR_NO_HARDWARE_CURSORS "${LABWC_WLR_NO_HARDWARE_CURSORS:-1}" \
    LABWC_WLR_SCENE_DISABLE_DIRECT_SCANOUT "${LABWC_WLR_SCENE_DISABLE_DIRECT_SCANOUT:-1}" \
    LABWC_CURSOR_THEME "${LABWC_CURSOR_THEME:-Adwaita}" \
    LABWC_CURSOR_SIZE "${LABWC_CURSOR_SIZE:-24}" \
    LABWC_GSK_RENDERER_LINE "$gsk_renderer_line"

  desktop_render_role_target_template \
    "etc/skel-desktop/.config/labwc/environment.d/10-wayland.env.tmpl" \
    "/etc/skel-desktop/.config/labwc/environment.d/10-wayland.env" \
    0644 \
    LABWC_WLR_RENDERER "${LABWC_WLR_RENDERER:-gles2}" \
    LABWC_GDK_DISABLE "${LABWC_GDK_DISABLE:-vulkan}" \
    LABWC_WLR_NO_HARDWARE_CURSORS "${LABWC_WLR_NO_HARDWARE_CURSORS:-1}" \
    LABWC_WLR_SCENE_DISABLE_DIRECT_SCANOUT "${LABWC_WLR_SCENE_DISABLE_DIRECT_SCANOUT:-1}" \
    LABWC_QT_QPA_PLATFORM "${LABWC_QT_QPA_PLATFORM:-wayland}" \
    LABWC_QT_PLATFORMTHEME "${LABWC_QT_PLATFORMTHEME:-qt6ct}" \
    LABWC_GDK_BACKEND "${LABWC_GDK_BACKEND:-wayland}" \
    LABWC_SDL_VIDEODRIVER "${LABWC_SDL_VIDEODRIVER:-wayland}" \
    LABWC_CLUTTER_BACKEND "${LABWC_CLUTTER_BACKEND:-wayland}" \
    LABWC_GTK_THEME "${LABWC_GTK_THEME:-Adwaita}" \
    LABWC_GSK_RENDERER_LINE "$gsk_renderer_line"

  desktop_log "rendered_labwc_environment_assets renderer=${LABWC_WLR_RENDERER:-gles2} gsk=${LABWC_GSK_RENDERER:-opengl} gdk_disable=${LABWC_GDK_DISABLE:-vulkan} hardware_cursors=${LABWC_WLR_NO_HARDWARE_CURSORS:-1}"
}

desktop_render_labwc_session_wrappers() {
  desktop_render_role_target_template \
    "usr/local/bin/labwc-greeter-session.tmpl" \
    "/usr/local/bin/labwc-greeter-session" \
    0755 \
    LABWC_GREETER_WLR_RENDERER "${LABWC_GREETER_WLR_RENDERER:-gles2}" \
    LABWC_GREETER_GSK_RENDERER "${LABWC_GREETER_GSK_RENDERER:-opengl}" \
    LABWC_GREETER_GDK_DISABLE "${LABWC_GREETER_GDK_DISABLE:-vulkan}" \
    LABWC_GREETER_WLR_NO_HARDWARE_CURSORS "${LABWC_GREETER_WLR_NO_HARDWARE_CURSORS:-1}" \
    LABWC_DESKTOP_SESSION_COMMAND "${LABWC_DESKTOP_SESSION_COMMAND:-/usr/local/bin/labwc-session}"

  desktop_render_role_target_template \
    "usr/local/bin/labwc-session.tmpl" \
    "/usr/local/bin/labwc-session" \
    0755 \
    LABWC_QT_QPA_PLATFORM "${LABWC_QT_QPA_PLATFORM:-wayland}" \
    LABWC_QT_PLATFORMTHEME "${LABWC_QT_PLATFORMTHEME:-qt6ct}" \
    LABWC_GDK_BACKEND "${LABWC_GDK_BACKEND:-wayland}" \
    LABWC_SDL_VIDEODRIVER "${LABWC_SDL_VIDEODRIVER:-wayland}" \
    LABWC_CLUTTER_BACKEND "${LABWC_CLUTTER_BACKEND:-wayland}" \
    LABWC_CURSOR_THEME "${LABWC_CURSOR_THEME:-Adwaita}" \
    LABWC_CURSOR_SIZE "${LABWC_CURSOR_SIZE:-24}" \
    LABWC_GTK_THEME "${LABWC_GTK_THEME:-Adwaita}" \
    LABWC_WLR_RENDERER "${LABWC_WLR_RENDERER:-gles2}" \
    LABWC_GSK_RENDERER "${LABWC_GSK_RENDERER:-opengl}" \
    LABWC_GDK_DISABLE "${LABWC_GDK_DISABLE:-vulkan}" \
    LABWC_WLR_NO_HARDWARE_CURSORS "${LABWC_WLR_NO_HARDWARE_CURSORS:-1}" \
    LABWC_WLR_SCENE_DISABLE_DIRECT_SCANOUT "${LABWC_WLR_SCENE_DISABLE_DIRECT_SCANOUT:-1}"

  desktop_log "rendered_labwc_session_wrappers session_renderer=${LABWC_WLR_RENDERER:-gles2} greeter_renderer=${LABWC_GREETER_WLR_RENDERER:-gles2}"
}

desktop_configure_local_mail_delivery() {
  : "${ACCOUNT_USERNAME:?ACCOUNT_USERNAME must be set for desktop local mail delivery}"
  mailname_value=$(desktop_mailname_value)

  desktop_render_shared_target_template "etc/mailname.tmpl" "/etc/mailname" 0644 \
    MAILNAME "$mailname_value"
  desktop_render_role_target_template "etc/aliases.tmpl" "/etc/aliases" 0644 \
    ACCOUNT_USERNAME "$ACCOUNT_USERNAME"
  desktop_stage_role_asset etc/apt/listchanges.conf /etc/apt/listchanges.conf 0644
  desktop_stage_role_asset etc/apt/apt.conf.d/60desktop-local-mail.conf /etc/apt/apt.conf.d/60desktop-local-mail.conf 0644

  desktop_log "configured_desktop_local_mail account=${ACCOUNT_USERNAME} mailname=${mailname_value}"
}

desktop_render_kanshi_config() {
  desktop_render_role_target_template \
    "etc/skel-desktop/.config/kanshi/config" \
    "/etc/skel-desktop/.config/kanshi/config" \
    0644 \
    LABWC_OUTPUT_EXTERNAL_PREFERRED_WIDTH "${LABWC_OUTPUT_EXTERNAL_PREFERRED_WIDTH:-1920}" \
    LABWC_OUTPUT_EXTERNAL_PREFERRED_HEIGHT "${LABWC_OUTPUT_EXTERNAL_PREFERRED_HEIGHT:-1080}" \
    LABWC_OUTPUT_EXTERNAL_PREFERRED_REFRESH_HZ "${LABWC_OUTPUT_EXTERNAL_PREFERRED_REFRESH_HZ:-120}" \
    LABWC_OUTPUT_EXTERNAL_SCALE "${LABWC_OUTPUT_EXTERNAL_SCALE:-1}" \
    LABWC_OUTPUT_INTERNAL_SCALE "${LABWC_OUTPUT_INTERNAL_SCALE:-1}" \
    LABWC_OUTPUT_SCALE "${LABWC_OUTPUT_SCALE:-1}"

  desktop_log "rendered_kanshi_config external_mode=${LABWC_OUTPUT_EXTERNAL_PREFERRED_WIDTH:-1920}x${LABWC_OUTPUT_EXTERNAL_PREFERRED_HEIGHT:-1080}@${LABWC_OUTPUT_EXTERNAL_PREFERRED_REFRESH_HZ:-120}Hz external_scale=${LABWC_OUTPUT_EXTERNAL_SCALE:-1}"
}

desktop_render_terminal_configs() {
  terminal_font_family=${LABWC_TERMINAL_FONT_FAMILY:-Noto Sans Mono}
  terminal_font_size=${LABWC_TERMINAL_FONT_SIZE:-12}

  desktop_render_role_target_template \
    "etc/skel-desktop/.config/foot/foot.ini" \
    "/etc/skel-desktop/.config/foot/foot.ini" \
    0644 \
    LABWC_TERMINAL_FONT_FAMILY "$terminal_font_family" \
    LABWC_TERMINAL_FONT_SIZE "$terminal_font_size" \
    LABWC_TERMINAL_BACKGROUND_OPACITY "${LABWC_TERMINAL_BACKGROUND_OPACITY:-0.985}" \
    LABWC_TERMINAL_WINDOW_COLUMNS "${LABWC_TERMINAL_WINDOW_COLUMNS:-96}" \
    LABWC_TERMINAL_WINDOW_ROWS "${LABWC_TERMINAL_WINDOW_ROWS:-26}"
  desktop_render_role_target_template \
    "etc/skel-desktop/.config/kitty/kitty.conf" \
    "/etc/skel-desktop/.config/kitty/kitty.conf" \
    0644 \
    LABWC_TERMINAL_FONT_FAMILY "$terminal_font_family" \
    LABWC_TERMINAL_FONT_SIZE "$terminal_font_size" \
    LABWC_TERMINAL_BACKGROUND_OPACITY "${LABWC_TERMINAL_BACKGROUND_OPACITY:-0.985}" \
    LABWC_TERMINAL_WINDOW_COLUMNS "${LABWC_TERMINAL_WINDOW_COLUMNS:-96}" \
    LABWC_TERMINAL_WINDOW_ROWS "${LABWC_TERMINAL_WINDOW_ROWS:-26}"

  desktop_log "rendered_terminal_configs font_family=${terminal_font_family} font_size=${terminal_font_size}"
}

desktop_render_gtk_settings() {
  gtk_font_size=${LABWC_GTK_FONT_SIZE:-12}

  for gtk_variant in 3 4; do
    template_path="etc/skel-desktop/.config/gtk-${gtk_variant}.0/settings.ini.tmpl"
    desktop_render_role_target_template \
      "$template_path" \
      "/etc/skel-desktop/.config/gtk-${gtk_variant}.0/settings.ini" \
      0644 \
      LABWC_GTK_FONT_SIZE "$gtk_font_size"
    desktop_render_role_target_template \
      "$template_path" \
      "/etc/xdg/gtk-${gtk_variant}.0/settings.ini" \
      0644 \
      LABWC_GTK_FONT_SIZE "$gtk_font_size"
  done
  desktop_log "rendered_gtk_settings font_size=${gtk_font_size}"
}

desktop_render_qt6ct_config() {
  for target_path in \
    /etc/skel-desktop/.config/qt6ct/qt6ct.conf \
    /etc/xdg/qt6ct/qt6ct.conf
  do
    desktop_render_role_target_template \
      etc/skel-desktop/.config/qt6ct/qt6ct.conf.tmpl \
      "$target_path" \
      0644 \
      LABWC_ICON_THEME "${LABWC_ICON_THEME:-Papirus-Dark}" \
      LABWC_QT_FONT_SIZE "${LABWC_QT_FONT_SIZE:-11}" \
      LABWC_QT_FIXED_FONT_SIZE "${LABWC_QT_FIXED_FONT_SIZE:-12}"
  done
  desktop_log "rendered_qt6ct_config icon_theme=${LABWC_ICON_THEME:-Papirus-Dark} font_size=${LABWC_QT_FONT_SIZE:-11}"
}

desktop_render_fuzzel_configs() {
  desktop_render_role_target_template \
    "etc/skel-desktop/.config/fuzzel/base.ini.tmpl" \
    "/etc/skel-desktop/.config/fuzzel/base.ini" \
    0644 \
    LABWC_FUZZEL_FONT_SIZE "${LABWC_FUZZEL_FONT_SIZE:-15}" \
    LABWC_FUZZEL_HORIZONTAL_PAD 12 \
    LABWC_FUZZEL_VERTICAL_PAD 10 \
    LABWC_FUZZEL_INNER_PAD 6 \
    LABWC_FUZZEL_LINE_HEIGHT 20 \
    LABWC_ICON_THEME "$(desktop_toml_escape "${LABWC_ICON_THEME:-Papirus-Dark}")"
  desktop_render_role_target_template \
    "etc/skel-desktop/.config/fuzzel/base.ini.tmpl" \
    "/etc/skel-desktop/.config/fuzzel/base-internal.ini" \
    0644 \
    LABWC_FUZZEL_FONT_SIZE "${LABWC_FUZZEL_INTERNAL_FONT_SIZE:-9}" \
    LABWC_FUZZEL_HORIZONTAL_PAD "${LABWC_FUZZEL_INTERNAL_HORIZONTAL_PAD:-10}" \
    LABWC_FUZZEL_VERTICAL_PAD "${LABWC_FUZZEL_INTERNAL_VERTICAL_PAD:-6}" \
    LABWC_FUZZEL_INNER_PAD "${LABWC_FUZZEL_INTERNAL_INNER_PAD:-4}" \
    LABWC_FUZZEL_LINE_HEIGHT "${LABWC_FUZZEL_INTERNAL_LINE_HEIGHT:-16}" \
    LABWC_ICON_THEME "$(desktop_toml_escape "${LABWC_ICON_THEME:-Papirus-Dark}")"
  desktop_render_role_target_template \
    "etc/skel-desktop/.config/fuzzel/fuzzel.ini.tmpl" \
    "/etc/skel-desktop/.config/fuzzel/fuzzel.ini" \
    0644 \
    LABWC_FUZZEL_BASE_CONFIG base.ini \
    LABWC_FUZZEL_WIDTH "${LABWC_FUZZEL_WIDTH:-54}" \
    LABWC_FUZZEL_LINES "${LABWC_FUZZEL_LINES:-10}"
  desktop_render_role_target_template \
    "etc/skel-desktop/.config/fuzzel/fuzzel.ini.tmpl" \
    "/etc/skel-desktop/.config/fuzzel/fuzzel-internal.ini" \
    0644 \
    LABWC_FUZZEL_BASE_CONFIG base-internal.ini \
    LABWC_FUZZEL_WIDTH "${LABWC_FUZZEL_INTERNAL_WIDTH:-28}" \
    LABWC_FUZZEL_LINES "${LABWC_FUZZEL_INTERNAL_LINES:-10}"
  desktop_render_role_target_template \
    "etc/skel-desktop/.config/fuzzel/menu.ini.tmpl" \
    "/etc/skel-desktop/.config/fuzzel/menu.ini" \
    0644 \
    LABWC_FUZZEL_BASE_CONFIG base.ini \
    LABWC_FUZZEL_MENU_WIDTH "${LABWC_FUZZEL_MENU_WIDTH:-28}" \
    LABWC_FUZZEL_MENU_LINES "${LABWC_FUZZEL_MENU_LINES:-8}"
  desktop_render_role_target_template \
    "etc/skel-desktop/.config/fuzzel/menu.ini.tmpl" \
    "/etc/skel-desktop/.config/fuzzel/menu-internal.ini" \
    0644 \
    LABWC_FUZZEL_BASE_CONFIG base-internal.ini \
    LABWC_FUZZEL_MENU_WIDTH "${LABWC_FUZZEL_INTERNAL_MENU_WIDTH:-18}" \
    LABWC_FUZZEL_MENU_LINES "${LABWC_FUZZEL_INTERNAL_MENU_LINES:-8}"
  desktop_log "rendered_fuzzel_configs launcher_width=${LABWC_FUZZEL_WIDTH:-54} internal_launcher_width=${LABWC_FUZZEL_INTERNAL_WIDTH:-28} menu_width=${LABWC_FUZZEL_MENU_WIDTH:-28} internal_menu_width=${LABWC_FUZZEL_INTERNAL_MENU_WIDTH:-18}"
}
desktop_render_crystal_dock_appearance() {
  for target_path in \
    /etc/skel-desktop/.config/crystal-dock/labwc/appearance.conf \
    /etc/xdg/crystal-dock/labwc/appearance.conf
  do
    desktop_render_role_target_template \
      "etc/skel-desktop/.config/crystal-dock/labwc/appearance.conf.tmpl" \
      "$target_path" \
      0644 \
      LABWC_CRYSTAL_DOCK_MINIMUM_ICON_SIZE "${LABWC_CRYSTAL_DOCK_MINIMUM_ICON_SIZE:-50}" \
      LABWC_CRYSTAL_DOCK_MAXIMUM_ICON_SIZE "${LABWC_CRYSTAL_DOCK_MAXIMUM_ICON_SIZE:-80}" \
      LABWC_CRYSTAL_DOCK_TOOLTIP_FONT_SIZE "${LABWC_CRYSTAL_DOCK_TOOLTIP_FONT_SIZE:-13}" \
      LABWC_CRYSTAL_DOCK_APP_MENU_ICON_SIZE "${LABWC_CRYSTAL_DOCK_APP_MENU_ICON_SIZE:-40}" \
      LABWC_CRYSTAL_DOCK_APP_MENU_FONT_SIZE "${LABWC_CRYSTAL_DOCK_APP_MENU_FONT_SIZE:-15}" \
      LABWC_CRYSTAL_DOCK_CLOCK_FONT_SCALE_FACTOR "${LABWC_CRYSTAL_DOCK_CLOCK_FONT_SCALE_FACTOR:-1.0}"
  done
  desktop_log "rendered_crystal_dock_appearance min_icon=${LABWC_CRYSTAL_DOCK_MINIMUM_ICON_SIZE:-50} max_icon=${LABWC_CRYSTAL_DOCK_MAXIMUM_ICON_SIZE:-80}"
}

desktop_render_chromium_flags() {
  desktop_render_role_target_template \
    "etc/chromium.d/90-performance-flags.tmpl" \
    "/etc/chromium.d/90-performance-flags" \
    0644
  desktop_log "rendered_chromium_flags gpu_wayland_defaults=managed"
}

desktop_render_note_app_defaults() {
  : "${DIR_HOME_DOCUMENTS:?DIR_HOME_DOCUMENTS must be set for desktop note apps}"
  : "${DIR_HOME_PICTURES:?DIR_HOME_PICTURES must be set for desktop note apps}"

  gtk_font_size=${LABWC_GTK_FONT_SIZE:-12}

  desktop_render_role_target_template \
    "etc/skel-desktop/.config/xournalpp/settings.xml.tmpl" \
    "/etc/skel-desktop/.config/xournalpp/settings.xml" \
    0644 \
    DIR_HOME_DOCUMENTS "$DIR_HOME_DOCUMENTS" \
    DIR_HOME_PICTURES "$DIR_HOME_PICTURES" \
    LABWC_GTK_FONT_SIZE "$gtk_font_size"
  desktop_stage_role_asset \
    etc/skel-desktop/.config/gnote/addins/global.ini \
    /etc/skel-desktop/.config/gnote/addins/global.ini \
    0644
  desktop_render_role_target_template \
    "usr/share/glib-2.0/schemas/90-desktop-gnote.gschema.override.tmpl" \
    "/usr/share/glib-2.0/schemas/90-desktop-gnote.gschema.override" \
    0644 \
    DIR_HOME_DOCUMENTS "$DIR_HOME_DOCUMENTS" \
    LABWC_GTK_FONT_SIZE "$gtk_font_size"
  desktop_stage_role_asset \
    usr/share/glib-2.0/schemas/90-desktop-window-buttons.gschema.override \
    /usr/share/glib-2.0/schemas/90-desktop-window-buttons.gschema.override \
    0644
  desktop_stage_role_asset \
    usr/share/glib-2.0/schemas/90-desktop-liferea.gschema.override \
    /usr/share/glib-2.0/schemas/90-desktop-liferea.gschema.override \
    0644
  desktop_log "rendered_note_app_defaults documents=${DIR_HOME_DOCUMENTS} pictures=${DIR_HOME_PICTURES} gtk_font_size=${gtk_font_size}"
}

desktop_stage_obsidian_default_vault() {
  vault_root=/target/etc/skel-desktop/Syncthing/obsidian-md

  install -d -m 0700 \
    /target/etc/skel-desktop/Syncthing \
    "$vault_root" \
    "$vault_root/.obsidian" \
    "$vault_root/.obsidian/snippets" \
    "$vault_root/.obsidian/themes" \
    "$vault_root/.obsidian/themes/evergreen-notes" \
    "$vault_root/.trash" \
    "$vault_root/archive" \
    "$vault_root/attachments" \
    "$vault_root/daily" \
    "$vault_root/inbox" \
    "$vault_root/templates"

  desktop_stage_role_asset etc/skel-desktop/Syncthing/obsidian-md/.obsidian/app.json /etc/skel-desktop/Syncthing/obsidian-md/.obsidian/app.json 0600
  desktop_stage_role_asset etc/skel-desktop/Syncthing/obsidian-md/.obsidian/appearance.json /etc/skel-desktop/Syncthing/obsidian-md/.obsidian/appearance.json 0600
  desktop_stage_role_asset etc/skel-desktop/Syncthing/obsidian-md/.obsidian/backlink.json /etc/skel-desktop/Syncthing/obsidian-md/.obsidian/backlink.json 0600
  desktop_stage_role_asset etc/skel-desktop/Syncthing/obsidian-md/.obsidian/bookmarks.json /etc/skel-desktop/Syncthing/obsidian-md/.obsidian/bookmarks.json 0600
  desktop_stage_role_asset etc/skel-desktop/Syncthing/obsidian-md/.obsidian/command-palette.json /etc/skel-desktop/Syncthing/obsidian-md/.obsidian/command-palette.json 0600
  desktop_stage_role_asset etc/skel-desktop/Syncthing/obsidian-md/.obsidian/community-plugins.json /etc/skel-desktop/Syncthing/obsidian-md/.obsidian/community-plugins.json 0600
  desktop_stage_role_asset etc/skel-desktop/Syncthing/obsidian-md/.obsidian/core-plugins.json /etc/skel-desktop/Syncthing/obsidian-md/.obsidian/core-plugins.json 0600
  desktop_stage_role_asset etc/skel-desktop/Syncthing/obsidian-md/.obsidian/daily-notes.json /etc/skel-desktop/Syncthing/obsidian-md/.obsidian/daily-notes.json 0600
  desktop_stage_role_asset etc/skel-desktop/Syncthing/obsidian-md/.obsidian/graph.json /etc/skel-desktop/Syncthing/obsidian-md/.obsidian/graph.json 0600
  desktop_stage_role_asset etc/skel-desktop/Syncthing/obsidian-md/.obsidian/hotkeys.json /etc/skel-desktop/Syncthing/obsidian-md/.obsidian/hotkeys.json 0600
  desktop_stage_role_asset etc/skel-desktop/Syncthing/obsidian-md/.obsidian/templates.json /etc/skel-desktop/Syncthing/obsidian-md/.obsidian/templates.json 0600
  desktop_stage_role_asset etc/skel-desktop/Syncthing/obsidian-md/.obsidian/types.json /etc/skel-desktop/Syncthing/obsidian-md/.obsidian/types.json 0600
  desktop_stage_role_asset etc/skel-desktop/Syncthing/obsidian-md/.obsidian/snippets/managed-ux.css /etc/skel-desktop/Syncthing/obsidian-md/.obsidian/snippets/managed-ux.css 0600
  desktop_stage_role_asset etc/skel-desktop/Syncthing/obsidian-md/.obsidian/themes/evergreen-notes/manifest.json /etc/skel-desktop/Syncthing/obsidian-md/.obsidian/themes/evergreen-notes/manifest.json 0600
  desktop_stage_role_asset etc/skel-desktop/Syncthing/obsidian-md/.obsidian/themes/evergreen-notes/theme.css /etc/skel-desktop/Syncthing/obsidian-md/.obsidian/themes/evergreen-notes/theme.css 0600
  desktop_stage_role_asset etc/skel-desktop/Syncthing/obsidian-md/home.md /etc/skel-desktop/Syncthing/obsidian-md/home.md 0600
  desktop_stage_role_asset etc/skel-desktop/Syncthing/obsidian-md/archive/index.md /etc/skel-desktop/Syncthing/obsidian-md/archive/index.md 0600
  desktop_stage_role_asset etc/skel-desktop/Syncthing/obsidian-md/daily/index.md /etc/skel-desktop/Syncthing/obsidian-md/daily/index.md 0600
  desktop_stage_role_asset etc/skel-desktop/Syncthing/obsidian-md/inbox/welcome.md /etc/skel-desktop/Syncthing/obsidian-md/inbox/welcome.md 0600
  desktop_stage_role_asset etc/skel-desktop/Syncthing/obsidian-md/templates/daily-note-template.md /etc/skel-desktop/Syncthing/obsidian-md/templates/daily-note-template.md 0600
  desktop_stage_role_asset etc/skel-desktop/Syncthing/obsidian-md/templates/note-template.md /etc/skel-desktop/Syncthing/obsidian-md/templates/note-template.md 0600
  desktop_stage_role_asset etc/skel-desktop/Syncthing/.stignore /etc/skel-desktop/Syncthing/.stignore 0600

  desktop_log "staged_obsidian_default_vault path=/etc/skel-desktop/Syncthing/obsidian-md theme=evergreen-notes"
}

desktop_compile_glib_schemas() {
  # shellcheck disable=SC2016
  run_in_target "compile desktop glib schemas" /bin/sh -c '
set -eu
compiler=

if command -v glib-compile-schemas >/dev/null 2>&1; then
  compiler=$(command -v glib-compile-schemas)
else
  compiler=$(find /usr/lib -path "*/glib-2.0/glib-compile-schemas" -type f | sed -n "1p")
fi

[ -n "$compiler" ] || {
  printf "fatal: glib-compile-schemas is unavailable in target\n" >&2
  exit 1
}
[ -d /usr/share/glib-2.0/schemas ] || {
  printf "fatal: target GLib schema directory is missing\n" >&2
  exit 1
}

"$compiler" /usr/share/glib-2.0/schemas
' sh
  desktop_log "compiled_glib_schemas scope=desktop"
}

desktop_install_user_resource_policy() {
  user_slice_dropin=/etc/systemd/system/user-1000.slice.d/50-resource-accounting.conf
  user_manager_dropin=/etc/systemd/system/user@.service.d/50-oom-score.conf
  user_manager_config=/etc/systemd/user.conf.d/50-resource-defaults.conf

  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/system/user-1000.slice.d/50-resource-accounting.conf)" \
    "$user_slice_dropin" \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/system/user@.service.d/50-oom-score.conf)" \
    "$user_manager_dropin" \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/user.conf.d/50-resource-defaults.conf)" \
    "$user_manager_config" \
    0644

  desktop_log \
    "staged_user_resource_policy slice=user-1000 accounting=${user_slice_dropin} user_manager=${user_manager_dropin} defaults=${user_manager_config}"
}

desktop_configure_greeter_access() {
  : "${LABWC_GREETER_USER:?LABWC_GREETER_USER must be set}"

  # The greeter runs before any real user session exists, so grant the
  # compositor access paths it needs up front.
  # shellcheck disable=SC2016
  run_in_target "configure Labwc greeter seat and DRM access" /bin/sh -c '
set -eu
greeter_user=$1
requested_groups="seat render video"
existing_groups=
missing_groups=
current_groups=$(id -nG "$greeter_user")

for group_name in $requested_groups; do
  if getent group "$group_name" >/dev/null 2>&1; then
    existing_groups="${existing_groups:+$existing_groups,}$group_name"
    case " $current_groups " in
      *" $group_name "*) ;;
      *)
        missing_groups="${missing_groups:+$missing_groups,}$group_name"
        ;;
    esac
  fi
done

[ -n "$existing_groups" ] || {
  printf "fatal: no greeter access groups are available for %s\n" "$greeter_user" >&2
  exit 1
}

if [ -n "$missing_groups" ]; then
  usermod -a -G "$missing_groups" "$greeter_user"
  current_groups=$(id -nG "$greeter_user")
fi
printf "desktop_greeter_access user=%s requested=%s current=%s\n" \
  "$greeter_user" \
  "$existing_groups" \
  "$current_groups"
' sh "$LABWC_GREETER_USER"
  desktop_log "configured_greeter_access user=${LABWC_GREETER_USER}"
}

desktop_stage_logging_policy() {
  : "${ACCOUNT_USERNAME:?ACCOUNT_USERNAME must be set}"

  # shellcheck disable=SC2016
  run_in_target "configure Labwc security notification access" /bin/sh -c '
set -eu
account_user=$1
signal_reader_group=logreader
scanner_writer_group=securitylogger

for command_name in getent groupadd id usermod; do
  command -v "$command_name" >/dev/null 2>&1 || {
    printf "fatal: required notification access command is missing: %s\n" "$command_name" >&2
    exit 1
  }
done

getent passwd "$account_user" >/dev/null
for access_group in "$signal_reader_group" "$scanner_writer_group"; do
  getent group "$access_group" >/dev/null 2>&1 ||
    groupadd --system "$access_group"
  usermod -a -G "$access_group" "$account_user"

  case " $(id -nG "$account_user") " in
    *" $access_group "*) ;;
    *)
      printf "fatal: desktop account was not added to %s: %s\n" "$access_group" "$account_user" >&2
      exit 1
      ;;
  esac
done
' sh "$ACCOUNT_USERNAME"

  install -d -m 0755 \
    /target/etc/rsyslog.d \
    /target/etc/logrotate.d \
    /target/etc/systemd/system/logrotate.timer.d \
    /target/etc/systemd/system/rsyslog.service.d \
    /target/usr/local/libexec

  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/rsyslog.conf)" \
    /etc/rsyslog.conf \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/rsyslog.d/15-audit.conf)" \
    /etc/rsyslog.d/15-audit.conf \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/rsyslog.d/20-auth.conf)" \
    /etc/rsyslog.d/20-auth.conf \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/rsyslog.d/25-usb.conf)" \
    /etc/rsyslog.d/25-usb.conf \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/rsyslog.d/30-apparmor.conf)" \
    /etc/rsyslog.d/30-apparmor.conf \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/rsyslog.d/31-apparmor-managed-modes.conf)" \
    /etc/rsyslog.d/31-apparmor-managed-modes.conf \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/rsyslog.d/35-storage.conf)" \
    /etc/rsyslog.d/35-storage.conf \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/rsyslog.d/37-whisper.conf)" \
    /etc/rsyslog.d/37-whisper.conf \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/rsyslog.d/39-security-scanners.conf)" \
    /etc/rsyslog.d/39-security-scanners.conf \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/rsyslog.d/40-nftables.conf)" \
    /etc/rsyslog.d/40-nftables.conf \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/rsyslog.d/41-fuzzel.conf)" \
    /etc/rsyslog.d/41-fuzzel.conf \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/rsyslog.d/42-adb.conf)" \
    /etc/rsyslog.d/42-adb.conf \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/rsyslog.d/43-managed-desktop-apps.conf)" \
    /etc/rsyslog.d/43-managed-desktop-apps.conf \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/rsyslog.d/99-discard.conf)" \
    /etc/rsyslog.d/99-discard.conf \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/logrotate.conf)" \
    /etc/logrotate.conf \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/system/logrotate.timer.d/override.conf)" \
    /etc/systemd/system/logrotate.timer.d/override.conf \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/logrotate.d/rsyslog)" \
    /etc/logrotate.d/rsyslog \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/logrotate.d/audit)" \
    /etc/logrotate.d/audit \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/logrotate.d/auth)" \
    /etc/logrotate.d/auth \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/logrotate.d/usb)" \
    /etc/logrotate.d/usb \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/logrotate.d/apparmor)" \
    /etc/logrotate.d/apparmor \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/logrotate.d/apparmor-managed-modes)" \
    /etc/logrotate.d/apparmor-managed-modes \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/logrotate.d/storage)" \
    /etc/logrotate.d/storage \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/logrotate.d/whisper)" \
    /etc/logrotate.d/whisper \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/logrotate.d/nftables)" \
    /etc/logrotate.d/nftables \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/logrotate.d/security-notify)" \
    /etc/logrotate.d/security-notify \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/logrotate.d/security-scanners)" \
    /etc/logrotate.d/security-scanners \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/logrotate.d/fuzzel)" \
    /etc/logrotate.d/fuzzel \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/logrotate.d/adb)" \
    /etc/logrotate.d/adb \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/logrotate.d/managed-desktop-apps)" \
    /etc/logrotate.d/managed-desktop-apps \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/tmpfiles.d/60-security-logs.conf)" \
    /etc/tmpfiles.d/60-security-logs.conf \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/tmpfiles.d/65-audit-syslog.conf)" \
    /etc/tmpfiles.d/65-audit-syslog.conf \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/libexec/rsyslog-managed-security-socket)" \
    /usr/local/libexec/rsyslog-managed-security-socket \
    0755
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/system/rsyslog.service.d/30-managed-security-scanner-socket.conf)" \
    /etc/systemd/system/rsyslog.service.d/30-managed-security-scanner-socket.conf \
    0644
  desktop_stage_role_asset \
    usr/local/bin/labwc-fuzzel-log \
    /usr/local/bin/labwc-fuzzel-log \
    0755

  run_in_target \
    "validate managed rsyslog configuration" \
    /usr/sbin/rsyslogd \
    -N1 \
    -f \
    /etc/rsyslog.conf
  run_in_target \
    "validate managed logrotate configuration" \
    /usr/sbin/logrotate \
    --debug \
    /etc/logrotate.conf

  desktop_log "staged_logging_policy audit=/var/log/managed/audit/kernel-audit.log auth=/var/log/managed/auth/auth.log usb=/var/log/managed/hardware/usb.log apparmor=/var/log/managed/apparmor/apparmor.log apparmor_modes=/var/log/managed/apparmor/managed-modes.log apparmor_source=/var/log/audit/audit.log storage=/var/log/managed/storage/storage.log whisper=/var/log/managed/whisper/whisper.log adb=/var/log/managed/adb/adb.log nftables=/var/log/managed/nftables/firewall.log fuzzel_menu=/var/log/managed/fuzzel/menu.log fuzzel_actions=/var/log/managed/fuzzel/actions.log managed_apps=/var/log/managed/desktop/applications.log scanner_socket=/run/rsyslog/managed-security-scanners/scanner.sock scanner_group=securitylogger retention=4 maxage_days=7 rotation_check=15m log_group=adm signal_group=logreader mako_signals=/var/lib/labwc-notifications/security"
}

desktop_stage_target_assets() {
  desktop_normalize_system_dbus_service_directories
  desktop_stage_logging_policy
  desktop_stage_primary_account_pool_storage_policy
  desktop_stage_network_profile_storage_policy
  desktop_stage_var_cache_policy
  desktop_render_labwc_environment_assets
  desktop_stage_role_asset etc/pam.d/greetd /etc/pam.d/greetd 0644
  desktop_stage_role_asset etc/pam.d/greetd-greeter /etc/pam.d/greetd-greeter 0644
  desktop_stage_role_asset etc/pam.d/swaylock /etc/pam.d/swaylock 0644
  desktop_stage_role_asset usr/share/pam-configs/wtmpdb /usr/share/pam-configs/wtmpdb 0644
  desktop_reconcile_wtmpdb_common_session /target
  desktop_render_labwc_session_wrappers
  desktop_configure_local_mail_delivery
  desktop_stage_role_asset usr/local/bin/labwc-autostart /usr/local/bin/labwc-autostart 0755
  desktop_stage_role_asset usr/local/bin/labwc-wallpaper-save /usr/local/bin/labwc-wallpaper-save 0755
  desktop_stage_role_asset usr/local/bin/labwc-admin-action /usr/local/bin/labwc-admin-action 0755
  desktop_stage_role_asset usr/local/libexec/labwc-admin-action-root /usr/local/libexec/labwc-admin-action-root 0755
  desktop_stage_role_asset usr/local/libexec/labwc-admin-action-worker /usr/local/libexec/labwc-admin-action-worker 0755
  desktop_stage_role_asset etc/systemd/system/labwc-admin-action@.service /etc/systemd/system/labwc-admin-action@.service 0644
  desktop_stage_role_asset usr/local/bin/labwc-calendar /usr/local/bin/labwc-calendar 0755
  desktop_stage_role_asset usr/local/libexec/labwc-calendar /usr/local/libexec/labwc-calendar 0755
  desktop_stage_role_asset usr/local/libexec/labwc-plans.pl /usr/local/libexec/labwc-plans.pl 0755
  desktop_stage_role_asset usr/local/bin/labwc-logout /usr/local/bin/labwc-logout 0755
  desktop_stage_role_asset usr/local/bin/labwc-fuzzel /usr/local/bin/labwc-fuzzel 0755
  desktop_stage_role_asset usr/local/bin/labwc-computer-management /usr/local/bin/labwc-computer-management 0755
  desktop_stage_role_asset usr/local/bin/labwc-ai-copilots /usr/local/bin/labwc-ai-copilots 0755
  desktop_stage_ai_copilots_perl_modules
  desktop_stage_ai_copilots_catalogs
  desktop_stage_role_asset usr/local/bin/labwc-ai-copilots-action /usr/local/bin/labwc-ai-copilots-action 0755
  desktop_stage_role_asset usr/local/libexec/labwc-ai-llama-server /usr/local/libexec/labwc-ai-llama-server 0755
  desktop_stage_role_asset usr/local/libexec/labwc-ai-model-install-root /usr/local/libexec/labwc-ai-model-install-root 0755
  desktop_stage_ai_copilots_python_modules
  desktop_stage_role_asset usr/local/libexec/labwc-ai-model-info /usr/local/libexec/labwc-ai-model-info 0755
  desktop_stage_role_asset usr/local/bin/labwc-display-configuration /usr/local/bin/labwc-display-configuration 0755
  desktop_stage_role_asset usr/local/bin/labwc-digital-assets /usr/local/bin/labwc-digital-assets 0755
  desktop_stage_digital_assets_perl_modules
  desktop_stage_role_asset usr/local/bin/labwc-digital-assets-action /usr/local/bin/labwc-digital-assets-action 0755
  desktop_stage_role_asset usr/local/bin/labwc-users-groups-menu /usr/local/bin/labwc-users-groups-menu 0755
  desktop_stage_role_asset usr/local/bin/labwc-adb-menu /usr/local/bin/labwc-adb-menu 0755
  desktop_stage_labwc_adb_perl_modules
  desktop_stage_role_asset usr/local/bin/labwc-adb-action /usr/local/bin/labwc-adb-action 0755
  desktop_stage_role_asset etc/skel-desktop/.config/systemd/user/labwc-adb-server.service /etc/skel-desktop/.config/systemd/user/labwc-adb-server.service 0644
  desktop_stage_role_asset etc/skel-desktop/.config/systemd/user/llama-server.service /etc/skel-desktop/.config/systemd/user/llama-server.service 0644
  desktop_stage_role_asset usr/local/libexec/labwc-samsung-firmware-extract /usr/local/libexec/labwc-samsung-firmware-extract 0755
  desktop_stage_role_asset usr/local/bin/labwc-maintenance-menu /usr/local/bin/labwc-maintenance-menu 0755
  desktop_stage_role_asset usr/local/bin/labwc-podman-menu /usr/local/bin/labwc-podman-menu 0755
  desktop_stage_role_asset usr/local/bin/labwc-external-drives /usr/local/bin/labwc-external-drives 0755
  desktop_stage_labwc_security_action_perl_modules
  desktop_stage_role_asset usr/local/bin/labwc-security-action /usr/local/bin/labwc-security-action 0755
  desktop_stage_role_asset usr/local/bin/labwc-system-action /usr/local/bin/labwc-system-action 0755
  desktop_stage_role_asset usr/local/bin/labwc-recovery-action /usr/local/bin/labwc-recovery-action 0755
  desktop_stage_role_asset usr/local/bin/labwc-network-control-menu /usr/local/bin/labwc-network-control-menu 0755
  desktop_stage_labwc_network_control_action_perl_modules
  desktop_stage_role_asset usr/local/bin/labwc-network-control-action /usr/local/bin/labwc-network-control-action 0755
  desktop_stage_role_asset usr/local/bin/labwc-firewall-menu /usr/local/bin/labwc-firewall-menu 0755
  desktop_stage_labwc_firewall_python_modules
  desktop_stage_role_asset usr/local/bin/labwc-firewall-action /usr/local/bin/labwc-firewall-action 0755
  desktop_stage_role_asset usr/local/bin/labwc-network-scan-menu /usr/local/bin/labwc-network-scan-menu 0755
  desktop_stage_labwc_network_scan_action_perl_modules
  desktop_render_labwc_network_scan_action_perl_root_module
  desktop_stage_role_asset usr/local/bin/labwc-network-scan-action /usr/local/bin/labwc-network-scan-action 0755
  desktop_stage_role_asset usr/local/bin/labwc-remote-desktop /usr/local/bin/labwc-remote-desktop 0755
  desktop_stage_role_asset usr/local/bin/labwc-freerdp-askpass /usr/local/bin/labwc-freerdp-askpass 0755
  desktop_stage_role_asset usr/local/bin/labwc-ocr /usr/local/bin/labwc-ocr 0755
  desktop_stage_role_asset usr/local/bin/discord /usr/local/bin/discord 0755
  desktop_stage_role_asset usr/local/bin/telbot /usr/local/bin/telbot 0755
  desktop_render_role_target_template \
    etc/skel-desktop/.local/share/applications/tutanota-desktop.desktop \
    /etc/skel-desktop/.local/share/applications/tutanota-desktop.desktop \
    0644 \
    LABWC_MANAGED_APP_DEFAULT_EXEC "$LABWC_MANAGED_APP_DEFAULT_EXEC"
  desktop_stage_labwc_managed_app_python_modules
  desktop_stage_role_asset usr/local/bin/labwc-managed-app /usr/local/bin/labwc-managed-app 0755
  desktop_stage_role_asset usr/local/bin/labwc-electron-app /usr/local/bin/labwc-electron-app 0755
  desktop_stage_role_asset usr/local/bin/labwc-wayland-app /usr/local/bin/labwc-wayland-app 0755
  desktop_stage_role_asset usr/local/libexec/labwc-wrap-desktop-files /usr/local/libexec/labwc-wrap-desktop-files 0755
  desktop_stage_role_asset etc/dpkg/dpkg.cfg.d/95-labwc-desktop-apps /etc/dpkg/dpkg.cfg.d/95-labwc-desktop-apps 0644
  desktop_stage_role_asset usr/local/libexec/labwc-chatgpt-session /usr/local/libexec/labwc-chatgpt-session 0755
  desktop_stage_role_asset usr/local/bin/labwc-managed-wayland-compat-app /usr/local/bin/labwc-managed-wayland-compat-app 0755
  desktop_stage_role_asset usr/local/libexec/labwc-zoom-discord-compat-runtime /usr/local/libexec/labwc-zoom-discord-compat-runtime 0755
  desktop_stage_role_asset usr/local/bin/labwc-qbittorrent /usr/local/bin/labwc-qbittorrent 0755
  desktop_stage_role_asset usr/local/bin/zoom /usr/local/bin/zoom 0755
  desktop_render_role_target_template \
    usr/local/bin/labwc-sync-application-launchers \
    /usr/local/bin/labwc-sync-application-launchers \
    0755 \
    LABWC_MANAGED_APP_DEFAULT_EXEC "$LABWC_MANAGED_APP_DEFAULT_EXEC"
  desktop_stage_role_asset etc/skel-desktop/.config/systemd/user/labwc-sync-application-launchers.service /etc/skel-desktop/.config/systemd/user/labwc-sync-application-launchers.service 0644
  desktop_stage_role_asset etc/skel-desktop/.config/systemd/user/labwc-sync-application-launchers.path /etc/skel-desktop/.config/systemd/user/labwc-sync-application-launchers.path 0644
  desktop_stage_role_asset usr/local/bin/labwc-greeter-output /usr/local/bin/labwc-greeter-output 0755
  desktop_stage_role_asset usr/local/bin/labwc-greeter-power /usr/local/bin/labwc-greeter-power 0755
  desktop_stage_role_asset usr/local/libexec/labwc-greeter-client /usr/local/libexec/labwc-greeter-client 0755
  desktop_stage_role_asset usr/local/share/labwc-greeter/rc.xml /usr/local/share/labwc-greeter/rc.xml 0644
  desktop_stage_role_asset usr/local/share/labwc-greeter/autostart /usr/local/share/labwc-greeter/autostart 0644
  desktop_stage_role_asset usr/local/libexec/labwc-output-watch /usr/local/libexec/labwc-output-watch 0755
  desktop_stage_role_asset usr/local/libexec/labwc-kanshi /usr/local/libexec/labwc-kanshi 0755
  desktop_stage_role_asset usr/local/libexec/labwc-session-check /usr/local/libexec/labwc-session-check 0755
  desktop_stage_role_asset usr/local/libexec/labwc-panel-run /usr/local/libexec/labwc-panel-run 0755
  desktop_stage_role_asset usr/local/libexec/whisper-record-timed /usr/local/libexec/whisper-record-timed 0755
  desktop_stage_role_asset usr/local/libexec/labwc-swaybg /usr/local/libexec/labwc-swaybg 0755
  desktop_stage_role_asset usr/local/libexec/labwc-swayidle /usr/local/libexec/labwc-swayidle 0755
  desktop_stage_role_asset usr/local/libexec/labwc-mute-default-microphone /usr/local/libexec/labwc-mute-default-microphone 0755
  desktop_stage_role_asset usr/local/lib/perl5/site_perl/whisper/WhisperMode/Audio.pm /usr/local/lib/perl5/site_perl/whisper/WhisperMode/Audio.pm 0644
  desktop_stage_role_asset usr/local/lib/perl5/site_perl/whisper/WhisperMode/State.pm /usr/local/lib/perl5/site_perl/whisper/WhisperMode/State.pm 0644
  desktop_stage_role_asset usr/local/lib/perl5/site_perl/whisper/WhisperMode/Systemd.pm /usr/local/lib/perl5/site_perl/whisper/WhisperMode/Systemd.pm 0644
  desktop_stage_role_asset usr/local/bin/labwc-lock /usr/local/bin/labwc-lock 0755
  desktop_stage_role_asset usr/local/bin/labwc-terminal /usr/local/bin/labwc-terminal 0755
  desktop_stage_role_asset usr/local/bin/labwc-bluetooth /usr/local/bin/labwc-bluetooth 0755
  desktop_stage_role_asset usr/local/bin/labwc-brightness-control /usr/local/bin/labwc-brightness-control 0755
  desktop_stage_role_asset usr/local/bin/labwc-power-settings /usr/local/bin/labwc-power-settings 0755
  desktop_stage_role_asset usr/local/bin/labwc-run /usr/local/bin/labwc-run 0755
  desktop_stage_role_asset usr/local/bin/labwc-power-menu /usr/local/bin/labwc-power-menu 0755
  desktop_stage_role_asset usr/local/bin/labwc-keyboard-layout /usr/local/bin/labwc-keyboard-layout 0755
  desktop_stage_role_asset usr/local/bin/labwc-capture /usr/local/bin/labwc-capture 0755
  desktop_stage_role_asset usr/local/bin/labwc-wayscriber-toggle /usr/local/bin/labwc-wayscriber-toggle 0755
  desktop_stage_role_asset usr/local/bin/satty /usr/local/bin/satty 0755
  desktop_stage_role_asset usr/local/libexec/apparmor-generate-rules /usr/local/libexec/apparmor-generate-rules 0755
  desktop_stage_role_asset usr/local/libexec/labwc-security-action-root /usr/local/libexec/labwc-security-action-root 0755
  desktop_stage_role_asset usr/local/libexec/labwc-system-action-root /usr/local/libexec/labwc-system-action-root 0755
  desktop_stage_role_asset usr/local/libexec/labwc-recovery-action-root /usr/local/libexec/labwc-recovery-action-root 0755
  desktop_stage_role_asset usr/local/libexec/labwc-network-control-action-root /usr/local/libexec/labwc-network-control-action-root 0755
  desktop_stage_role_asset usr/local/libexec/labwc-firewall-action-root /usr/local/libexec/labwc-firewall-action-root 0755
  desktop_render_role_target_template \
    usr/local/libexec/labwc-network-scan-action-root.tmpl \
    /usr/local/libexec/labwc-network-scan-action-root \
    0755 \
    ACCOUNT_USERNAME "$ACCOUNT_USERNAME"
  desktop_stage_managed_nmap_scripts
  desktop_stage_role_asset usr/local/sbin/greetd-power-action /usr/local/sbin/greetd-power-action 0755
  desktop_stage_role_asset usr/local/sbin/labwc-notify /usr/local/sbin/labwc-notify 0755
  desktop_stage_role_asset usr/local/libexec/managed-clamav-signature-update /usr/local/libexec/managed-clamav-signature-update 0755

  desktop_stage_role_asset usr/share/wayland-sessions/labwc.desktop /usr/share/wayland-sessions/labwc.desktop 0644
  desktop_stage_role_asset usr/share/applications/computer-management.desktop /usr/share/applications/computer-management.desktop 0644
  desktop_stage_role_asset usr/share/applications/remote-desktop-management.desktop /usr/share/applications/remote-desktop-management.desktop 0644
  desktop_stage_role_asset usr/local/share/applications/foot.desktop /usr/local/share/applications/foot.desktop 0644
  desktop_render_gtkgreet_css
  desktop_stage_role_asset etc/greetd/gtkgreet-power.css /etc/greetd/gtkgreet-power.css 0644
  desktop_render_greeter_power_rule
  desktop_stage_role_asset etc/fangfrisch.conf /etc/fangfrisch.conf 0644
  desktop_stage_role_asset etc/systemd/system/managed-clamav-signature-update.service /etc/systemd/system/managed-clamav-signature-update.service 0644
  desktop_stage_role_asset etc/systemd/system/managed-clamav-signature-update.timer /etc/systemd/system/managed-clamav-signature-update.timer 0644
  desktop_stage_role_asset etc/bluetooth/main.conf /etc/bluetooth/main.conf 0644
  desktop_stage_role_asset usr/local/libexec/bluetooth-controller-init /usr/local/libexec/bluetooth-controller-init 0755
  desktop_stage_role_asset etc/systemd/system/bluetooth-controller-init.service /etc/systemd/system/bluetooth-controller-init.service 0644
  desktop_stage_role_asset etc/systemd/system/greetd.service.d/20-labwc-vt.conf /etc/systemd/system/greetd.service.d/20-labwc-vt.conf 0644
  desktop_stage_role_asset etc/systemd/system/bluetooth.service.d/override.conf /etc/systemd/system/bluetooth.service.d/override.conf 0644
  desktop_stage_mullvad_dns_policy
  install -d -m 0700 /target/etc/skel-desktop/.config/autostart
  desktop_stage_mullvad_application_policy
  if [ "${LABWC_NVIDIA_ACCELERATION_AVAILABLE:-false}" = true ]; then
    desktop_stage_role_asset etc/systemd/system/nvidia-powerd.service.d/10-device-guard.conf /etc/systemd/system/nvidia-powerd.service.d/10-device-guard.conf 0644
    desktop_stage_role_asset etc/udev/rules.d/71-managed-nvidia-char-links.rules /etc/udev/rules.d/71-managed-nvidia-char-links.rules 0644
  else
    rm -f \
      /target/etc/systemd/system/nvidia-powerd.service.d/10-device-guard.conf \
      /target/etc/udev/rules.d/71-managed-nvidia-char-links.rules
  fi
  # KWallet belongs to the single managed Labwc account. Keep the portal unit
  # account-local so the greeter's independent user manager cannot discover or
  # activate the desktop secret-service stack. Debian's D-Bus activation owns
  # the on-demand kwalletd6 compatibility daemon.
  desktop_stage_role_asset etc/skel-desktop/.config/systemd/user/labwc-kwallet-portal.service /etc/skel-desktop/.config/systemd/user/labwc-kwallet-portal.service 0644
  desktop_stage_role_asset etc/skel-desktop/.config/systemd/user/labwc-output-watch.service /etc/skel-desktop/.config/systemd/user/labwc-output-watch.service 0644
  desktop_stage_role_asset etc/skel-desktop/.config/systemd/user/codex-app-server.service /etc/skel-desktop/.config/systemd/user/codex-app-server.service 0644
  desktop_stage_role_asset etc/skel-desktop/.config/systemd/user/codex-app-server-proxy.service /etc/skel-desktop/.config/systemd/user/codex-app-server-proxy.service 0644
  desktop_stage_role_asset etc/skel-desktop/.config/systemd/user/codex-app-server.socket /etc/skel-desktop/.config/systemd/user/codex-app-server.socket 0644
  desktop_stage_role_asset etc/default/codex-app-server /etc/default/codex-app-server 0644
  desktop_stage_role_asset usr/local/libexec/codex-app-server-wait-ready /usr/local/libexec/codex-app-server-wait-ready 0755
  desktop_stage_role_asset etc/skel-desktop/.config/systemd/user/swaybg.service /etc/skel-desktop/.config/systemd/user/swaybg.service 0644
  desktop_stage_role_asset etc/skel-desktop/.config/systemd/user/kanshi.service /etc/skel-desktop/.config/systemd/user/kanshi.service 0644
  desktop_stage_role_asset etc/skel-desktop/.config/systemd/user/swayidle.service /etc/skel-desktop/.config/systemd/user/swayidle.service 0644
  desktop_stage_role_asset etc/skel-desktop/.config/systemd/user/crystal-dock.service /etc/skel-desktop/.config/systemd/user/crystal-dock.service 0644
  desktop_stage_role_asset etc/skel-desktop/.config/systemd/user/labwc-mute-default-microphone.service /etc/skel-desktop/.config/systemd/user/labwc-mute-default-microphone.service 0644
  if desktop_whisper_addon_selected; then
    desktop_stage_role_asset etc/tmpfiles.d/55-whisper-runtime.conf /etc/tmpfiles.d/55-whisper-runtime.conf 0644
    desktop_stage_role_asset etc/skel-desktop/.config/systemd/user/whisper-record.service /etc/skel-desktop/.config/systemd/user/whisper-record.service 0644
    desktop_stage_role_asset etc/skel-desktop/.config/systemd/user/whisper-transcribe.service /etc/skel-desktop/.config/systemd/user/whisper-transcribe.service 0644
    if desktop_whisper_persistent_memory_enabled; then
      desktop_stage_role_asset etc/skel-desktop/.config/systemd/user/whisper-server.service /etc/skel-desktop/.config/systemd/user/whisper-server.service 0644
    fi
  fi
  # systemd dependency directives cannot be removed from a vendor unit with a
  # drop-in. Install the complete managed unit so no graphical-session.target
  # dependency survives Debian's Waybar unit. Labwc autostart requests it only
  # after activating the compositor session target, so LABWC_ENABLE_WAYBAR
  # remains the authoritative policy gate.
  desktop_stage_role_asset etc/skel-desktop/.config/systemd/user/waybar.service /etc/skel-desktop/.config/systemd/user/waybar.service 0644
  desktop_stage_role_asset etc/skel-desktop/.config/systemd/user/waybar.service.d/20-tray-compat.conf /etc/skel-desktop/.config/systemd/user/waybar.service.d/20-tray-compat.conf 0644
  if [ -x /target/opt/microsoft/msedge/msedge ]; then
    install -d -m 0755 /target/opt/microsoft/msedge/extensions
  fi
  desktop_stage_role_asset etc/wireplumber/wireplumber.conf.d/10-disable-bluez-midi.conf /etc/wireplumber/wireplumber.conf.d/10-disable-bluez-midi.conf 0644
  desktop_stage_role_asset etc/wireplumber/wireplumber.conf.d/20-managed-audio-policy.conf /etc/wireplumber/wireplumber.conf.d/20-managed-audio-policy.conf 0644
  desktop_stage_role_asset etc/pipewire/client.conf.d/20-managed-volume-ceiling.conf /etc/pipewire/client.conf.d/20-managed-volume-ceiling.conf 0644
  desktop_stage_role_asset etc/pipewire/pipewire-pulse.conf.d/20-managed-volume-ceiling.conf /etc/pipewire/pipewire-pulse.conf.d/20-managed-volume-ceiling.conf 0644
  desktop_stage_role_asset etc/apt/listchanges.conf /etc/apt/listchanges.conf 0644
  desktop_stage_role_asset etc/apt/apt.conf.d/60desktop-local-mail.conf /etc/apt/apt.conf.d/60desktop-local-mail.conf 0644
  desktop_stage_role_asset etc/chromium/policies/managed/telemetry.json /etc/chromium/policies/managed/telemetry.json 0644
  desktop_stage_role_asset etc/chromium/policies/managed/security.json /etc/chromium/policies/managed/security.json 0644
  desktop_stage_role_asset etc/chromium/policies/managed/performance.json /etc/chromium/policies/managed/performance.json 0644
  desktop_stage_role_asset etc/chromium/policies/recommended/defaults.json /etc/chromium/policies/recommended/defaults.json 0644
  desktop_stage_role_asset etc/opt/edge/policies/managed/telemetry.json /etc/opt/edge/policies/managed/telemetry.json 0644
  desktop_stage_role_asset etc/opt/edge/policies/managed/security.json /etc/opt/edge/policies/managed/security.json 0644
  desktop_stage_role_asset etc/opt/edge/policies/managed/performance.json /etc/opt/edge/policies/managed/performance.json 0644
  desktop_stage_role_asset etc/opt/edge/policies/recommended/defaults.json /etc/opt/edge/policies/recommended/defaults.json 0644
  desktop_stage_role_asset etc/vivaldi/policies/managed/telemetry.json /etc/vivaldi/policies/managed/telemetry.json 0644
  desktop_stage_role_asset etc/vivaldi/policies/managed/extensions.json /etc/vivaldi/policies/managed/extensions.json 0644
  desktop_stage_role_asset etc/vivaldi/policies/managed/security.json /etc/vivaldi/policies/managed/security.json 0644
  desktop_stage_role_asset etc/vivaldi/policies/managed/performance.json /etc/vivaldi/policies/managed/performance.json 0644
  desktop_stage_role_asset etc/vivaldi/policies/recommended/defaults.json /etc/vivaldi/policies/recommended/defaults.json 0644
  desktop_stage_role_asset etc/opt/chrome/policies/managed/security.json /etc/opt/chrome/policies/managed/security.json 0644
  desktop_stage_role_asset etc/opt/chrome/policies/managed/telemetry.json /etc/opt/chrome/policies/managed/telemetry.json 0644
  desktop_stage_role_asset etc/opt/chrome/policies/managed/performance.json /etc/opt/chrome/policies/managed/performance.json 0644
  desktop_stage_role_asset etc/opt/chrome/policies/recommended/defaults.json /etc/opt/chrome/policies/recommended/defaults.json 0644
  desktop_stage_role_asset usr/local/bin/browser-devtools /usr/local/bin/browser-devtools 0755
  desktop_stage_role_asset usr/local/libexec/install-browser-imports /usr/local/libexec/install-browser-imports 0755
  desktop_stage_role_asset usr/local/share/browser-imports/noscript_data.txt /usr/local/share/browser-imports/noscript_data.txt 0600
  desktop_stage_role_asset usr/local/share/browser-imports/my-ubol-settings.json /usr/local/share/browser-imports/my-ubol-settings.json 0600
  desktop_stage_role_asset usr/local/share/browser-imports/PrivacyBadger_user_data-9_6_2026_1_50_43_PM.json /usr/local/share/browser-imports/PrivacyBadger_user_data-9_6_2026_1_50_43_PM.json 0600
  desktop_stage_role_asset usr/local/share/browser-imports/bookmark-coverage.json /usr/local/share/browser-imports/bookmark-coverage.json 0600
  desktop_stage_role_asset usr/local/share/browser-imports/BROWSER-IMPORTS.md /usr/local/share/browser-imports/BROWSER-IMPORTS.md 0600
  chmod 0700 /target/usr/local/share/browser-imports
  desktop_stage_role_asset \
    usr/share/glib-2.0/schemas/90-desktop-wsdd.gschema.override \
    /usr/share/glib-2.0/schemas/90-desktop-wsdd.gschema.override \
    0644
  desktop_stage_role_asset etc/xdg/xdg-desktop-portal/labwc-portals.conf /etc/xdg/xdg-desktop-portal/labwc-portals.conf 0644
  desktop_stage_role_asset etc/skel-desktop/.gnupg/gpg-agent.conf /etc/skel-desktop/.gnupg/gpg-agent.conf 0600
  chmod 0700 /target/etc/skel-desktop/.gnupg
  desktop_stage_role_asset etc/skel-desktop/.config/systemd/user/labwc-calendar-sync.service /etc/skel-desktop/.config/systemd/user/labwc-calendar-sync.service 0644
  desktop_stage_role_asset etc/skel-desktop/.config/systemd/user/labwc-calendar-sync.timer /etc/skel-desktop/.config/systemd/user/labwc-calendar-sync.timer 0644

  desktop_stage_role_asset usr/share/backgrounds/desktop/wallpaper-1920x1080.png /usr/share/backgrounds/desktop/wallpaper-1920x1080.png 0644
  desktop_extract_role_wallpaper_archive
  desktop_stage_role_asset usr/share/backgrounds/login/lock-1920x1080.png /usr/share/backgrounds/login/lock-1920x1080.png 0644
  desktop_stage_role_asset usr/share/backgrounds/login/welcome-1920x1080.png /usr/share/backgrounds/login/welcome-1920x1080.png 0644
  desktop_normalize_background_directories
#  desktop_stage_role_asset_tree usr/share/backgrounds/other /usr/share/backgrounds/other

  desktop_stage_role_asset etc/skel-desktop/.config/labwc/autostart /etc/skel-desktop/.config/labwc/autostart 0755
  desktop_stage_role_asset etc/skel-desktop/.config/labwc/shutdown /etc/skel-desktop/.config/labwc/shutdown 0755
  desktop_stage_labwc_user_session_assets
  remove_target_asset /etc/skel-desktop/.config/labwc/xinitrc
  remove_target_asset /etc/skel-desktop/.config/gsimplecal/config
  desktop_stage_role_asset etc/skel-desktop/.config/labwc/themerc-override /etc/skel-desktop/.config/labwc/themerc-override 0644
  desktop_stage_role_asset etc/skel-desktop/.config/waypaper/config.ini /etc/skel-desktop/.config/waypaper/config.ini 0644
  desktop_stage_role_asset etc/skel-desktop/.config/waypaper/keybindings.ini /etc/skel-desktop/.config/waypaper/keybindings.ini 0644
  desktop_stage_role_asset etc/skel-desktop/.config/waypaper/style.css /etc/skel-desktop/.config/waypaper/style.css 0644
  desktop_render_labwc_rc_xml
  desktop_render_role_target_template \
    "etc/skel-desktop/.config/labwc/menu.xml" \
    "/etc/skel-desktop/.config/labwc/menu.xml" \
    0644 \
    ACCOUNT_HOME "$ACCOUNT_HOME"
  desktop_render_waybar_config
  desktop_render_waybar_style
  desktop_render_kanshi_config
  desktop_render_terminal_configs
  desktop_stage_role_asset etc/skel-desktop/.config/mpv/mpv.conf /etc/skel-desktop/.config/mpv/mpv.conf 0644
  desktop_stage_role_asset etc/skel-desktop/.config/mpv/input.conf /etc/skel-desktop/.config/mpv/input.conf 0644
  desktop_stage_role_asset etc/skel-desktop/.config/featherpad/fp.conf /etc/skel-desktop/.config/featherpad/fp.conf 0644
  desktop_stage_role_asset etc/skel-desktop/.config/GottCode/FocusWriter.conf /etc/skel-desktop/.config/GottCode/FocusWriter.conf 0644
  desktop_stage_role_asset etc/skel-desktop/.config/zathura/zathurarc /etc/skel-desktop/.config/zathura/zathurarc 0644
  desktop_stage_role_asset usr/local/bin/labwc-focuswriter-import /usr/local/bin/labwc-focuswriter-import 0755
  desktop_stage_role_asset usr/local/share/applications/labwc-focuswriter-import.desktop /usr/local/share/applications/labwc-focuswriter-import.desktop 0644
  desktop_stage_role_asset etc/skel-desktop/.local/share/GottCode/FocusWriter/Themes/managed-word.theme /etc/skel-desktop/.local/share/GottCode/FocusWriter/Themes/managed-word.theme 0644
  desktop_stage_role_asset etc/skel-desktop/.config/Recoll.org/recoll.ini /etc/skel-desktop/.config/Recoll.org/recoll.ini 0600
  chmod 0700 /target/etc/skel-desktop/.config/Recoll.org
  desktop_stage_role_asset etc/skel-desktop/.recoll/recoll.conf /etc/skel-desktop/.recoll/recoll.conf 0644
  chmod 0700 /target/etc/skel-desktop/.recoll
  install -d -m 0700 /target/etc/skel-desktop/.cache /target/etc/skel-desktop/.cache/recoll
  desktop_stage_role_asset etc/skel-desktop/.config/kdiff3rc /etc/skel-desktop/.config/kdiff3rc 0644
  desktop_stage_role_asset etc/skel-desktop/.config/micro/settings.json /etc/skel-desktop/.config/micro/settings.json 0644
  desktop_stage_role_asset etc/skel-desktop/.config/nano/nanorc /etc/skel-desktop/.config/nano/nanorc 0644
  desktop_stage_role_asset etc/skel-desktop/.config/nvim/init.lua /etc/skel-desktop/.config/nvim/init.lua 0644
  desktop_stage_role_asset etc/skel-desktop/.config/qalculate/qalc.cfg /etc/skel-desktop/.config/qalculate/qalc.cfg 0644
  desktop_stage_role_asset etc/skel-desktop/.config/qalculate/qalculate-qt.cfg /etc/skel-desktop/.config/qalculate/qalculate-qt.cfg 0644
  install -d -m 0700 /target/etc/skel-desktop/.config/xarchiver
  desktop_render_role_target_template \
    etc/skel-desktop/.config/xarchiver/xarchiverrc \
    /etc/skel-desktop/.config/xarchiver/xarchiverrc \
    0600 \
    ACCOUNT_USERNAME "$ACCOUNT_USERNAME" \
    ACCOUNT_HOME "$ACCOUNT_HOME"
  desktop_stage_role_asset etc/skel-desktop/.config/task/taskrc /etc/skel-desktop/.config/task/taskrc 0644
  install -d -m 0700 /target/etc/skel-desktop/.local/share/task /target/etc/skel-desktop/.local/share/task/hooks
  desktop_stage_role_asset etc/skel-desktop/.config/vim/vimrc /etc/skel-desktop/.config/vim/vimrc 0644
  desktop_render_note_app_defaults
  desktop_compile_glib_schemas
  desktop_stage_role_asset etc/skel-desktop/.config/xdg-terminals.list /etc/skel-desktop/.config/xdg-terminals.list 0644
  desktop_stage_role_asset etc/skel-desktop/.config/mimeapps.list /etc/skel-desktop/.config/mimeapps.list 0600
  desktop_stage_role_asset etc/xdg/mimeapps.list /etc/xdg/mimeapps.list 0644
  desktop_stage_role_asset usr/share/mime/packages/90-desktop-filetypes.xml /usr/share/mime/packages/90-desktop-filetypes.xml 0644
  run_in_target "update managed desktop MIME database" /bin/sh -eu -c '
test -x /usr/bin/update-mime-database
/usr/bin/update-mime-database /usr/share/mime
' sh
  desktop_stage_role_asset etc/skel-desktop/.config/xfce4/helpers.rc /etc/skel-desktop/.config/xfce4/helpers.rc 0644
  desktop_stage_role_asset etc/skel-desktop/.config/xfce4/xfconf/xfce-perchannel-xml/thunar.xml /etc/skel-desktop/.config/xfce4/xfconf/xfce-perchannel-xml/thunar.xml 0644
  desktop_stage_role_asset etc/skel-desktop/.config/retroarch/retroarch.cfg /etc/skel-desktop/.config/retroarch/retroarch.cfg 0644
  install -d -m 0700 /target/etc/skel-desktop/.config/sleek/userData
  desktop_stage_role_asset etc/skel-desktop/.config/sleek/userData/colors.json /etc/skel-desktop/.config/sleek/userData/colors.json 0600
  desktop_render_role_target_template \
    "etc/skel-desktop/.config/sleek/userData/config.json.tmpl" \
    "/etc/skel-desktop/.config/sleek/userData/config.json" \
    0600 \
    ACCOUNT_HOME "$ACCOUNT_HOME"
  desktop_stage_role_asset etc/skel-desktop/.config/sleek/userData/filters.json /etc/skel-desktop/.config/sleek/userData/filters.json 0600
  desktop_stage_role_asset usr/share/xfce4/helpers/foot.desktop /usr/share/xfce4/helpers/foot.desktop 0644
  desktop_stage_role_asset etc/skel-desktop/.profile /etc/skel-desktop/.profile 0644
  desktop_stage_role_asset etc/skel-desktop/.bash_profile /etc/skel-desktop/.bash_profile 0644
  desktop_stage_role_asset etc/skel-desktop/.bashrc /etc/skel-desktop/.bashrc 0644
  desktop_stage_role_asset etc/skel-desktop/.bash_aliases /etc/skel-desktop/.bash_aliases 0644
  install -d -m 0755 /target/etc/skel-desktop/.profile.d
  desktop_stage_role_asset etc/skel-desktop/.profile.d/71-devops-de.sh /etc/skel-desktop/.profile.d/71-devops-de.sh 0644
  install -d -m 0755 /target/etc/skel-desktop/.config/cargo
  desktop_render_cargo_config
  install -d -m 0755 /target/etc/skel-desktop/.config/mise/conf.d
  desktop_stage_role_asset etc/skel-desktop/.config/mise/config.toml /etc/skel-desktop/.config/mise/config.toml 0644
  desktop_stage_role_asset etc/skel-desktop/.config/mise/config.development.toml /etc/skel-desktop/.config/mise/config.development.toml 0644
  desktop_stage_role_asset etc/skel-desktop/.config/mise/config.local.toml /etc/skel-desktop/.config/mise/config.local.toml 0644
  desktop_stage_role_asset etc/skel-desktop/.config/mise/config.development.local.toml /etc/skel-desktop/.config/mise/config.development.local.toml 0644
  desktop_stage_role_asset etc/skel-desktop/.config/mise/conf.d/10-managed-tools.toml /etc/skel-desktop/.config/mise/conf.d/10-managed-tools.toml 0644
  desktop_stage_role_asset etc/skel-desktop/.zshenv /etc/skel-desktop/.zshenv 0644
  desktop_stage_role_asset etc/skel-desktop/.zprofile /etc/skel-desktop/.zprofile 0644
  desktop_stage_role_asset etc/skel-desktop/.zshrc /etc/skel-desktop/.zshrc 0644
  desktop_stage_role_asset etc/skel-desktop/.zlogout /etc/skel-desktop/.zlogout 0644
  desktop_stage_role_asset etc/skel-desktop/.zsh_aliases /etc/skel-desktop/.zsh_aliases 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/skel-desktop/.dircolors)" /etc/skel-desktop/.dircolors 0644
  desktop_log "staged_asset source=$(installer_repo_join_var DIR_HOOKS_TARGET etc/skel-desktop/.dircolors) target=/etc/skel-desktop/.dircolors mode=0644"
  desktop_stage_role_asset etc/skel-desktop/.config/starship.toml /etc/skel-desktop/.config/starship.toml 0644
  desktop_stage_role_asset etc/skel-desktop/.config/btop/btop.conf /etc/skel-desktop/.config/btop/btop.conf 0644
  desktop_stage_role_asset etc/skel-desktop/.config/fzf/default-opts /etc/skel-desktop/.config/fzf/default-opts 0644
  desktop_render_fuzzel_configs
  desktop_stage_role_asset etc/skel-desktop/.config/Thunar/uca.xml /etc/skel-desktop/.config/Thunar/uca.xml 0644
  desktop_stage_role_asset etc/skel-desktop/.config/tesseract/ocr-defaults.conf /etc/skel-desktop/.config/tesseract/ocr-defaults.conf 0644
  desktop_stage_role_asset etc/skel-desktop/.config/tesseract/user-words/default.user-words /etc/skel-desktop/.config/tesseract/user-words/default.user-words 0644
  desktop_stage_role_asset etc/skel-desktop/.config/tesseract/user-words/eng.user-words /etc/skel-desktop/.config/tesseract/user-words/eng.user-words 0644
  desktop_stage_role_asset etc/skel-desktop/.config/tesseract/user-words/swe.user-words /etc/skel-desktop/.config/tesseract/user-words/swe.user-words 0644
  desktop_stage_role_asset etc/skel-desktop/.config/tesseract/user-patterns/default.user-patterns /etc/skel-desktop/.config/tesseract/user-patterns/default.user-patterns 0644
  desktop_stage_role_asset etc/skel-desktop/.config/tesseract/user-patterns/eng.user-patterns /etc/skel-desktop/.config/tesseract/user-patterns/eng.user-patterns 0644
  desktop_stage_role_asset etc/skel-desktop/.config/tesseract/user-patterns/swe.user-patterns /etc/skel-desktop/.config/tesseract/user-patterns/swe.user-patterns 0644
  desktop_render_crystal_dock_appearance
  desktop_stage_role_asset etc/skel-desktop/.config/crystal-dock/labwc/panel_1.conf /etc/skel-desktop/.config/crystal-dock/labwc/panel_1.conf 0644
  desktop_stage_role_asset etc/skel-desktop/.config/crystal-dock/labwc/panel_1.conf /etc/xdg/crystal-dock/labwc/panel_1.conf 0644
  desktop_stage_role_asset usr/local/bin/labwc-show-desktop /usr/local/bin/labwc-show-desktop 0755
  desktop_stage_role_asset usr/local/bin/labwc-health-notify /usr/local/bin/labwc-health-notify 0755
  desktop_stage_role_asset usr/share/applications/show-desktop.desktop /usr/share/applications/show-desktop.desktop 0644
  desktop_normalize_public_desktop_directories
  desktop_stage_role_asset usr/local/share/applications/labwc-tweaks.desktop /usr/local/share/applications/labwc-tweaks.desktop 0644
  desktop_stage_role_asset usr/local/share/applications/hyprpolkitagent.desktop /usr/local/share/applications/hyprpolkitagent.desktop 0644
  desktop_stage_role_asset usr/local/share/icons/hicolor/64x64/apps/show-desktop.png /usr/local/share/icons/hicolor/64x64/apps/show-desktop.png 0644
  desktop_stage_role_asset etc/skel-desktop/.config/mako/config /etc/skel-desktop/.config/mako/config 0644
  desktop_stage_role_asset etc/skel-desktop/.config/satty/config.toml /etc/skel-desktop/.config/satty/config.toml 0644
  desktop_stage_role_asset etc/skel-desktop/.config/satty/overrides.css /etc/skel-desktop/.config/satty/overrides.css 0644
  desktop_stage_role_asset etc/skel-desktop/.config/swaylock/config /etc/skel-desktop/.config/swaylock/config 0644
  desktop_stage_role_asset etc/skel-desktop/.config/wireplumber/wireplumber.conf.d/10-disable-bluez-midi.conf /etc/skel-desktop/.config/wireplumber/wireplumber.conf.d/10-disable-bluez-midi.conf 0644
  desktop_stage_role_asset etc/skel-desktop/.config/wireplumber/wireplumber.conf.d/20-managed-audio-policy.conf /etc/skel-desktop/.config/wireplumber/wireplumber.conf.d/20-managed-audio-policy.conf 0644
  desktop_render_gtk_settings
  desktop_render_qt6ct_config
  desktop_stage_role_asset etc/skel-desktop/.config/kwalletrc /etc/skel-desktop/.config/kwalletrc 0644
  install -d -m 0700 \
    /target/etc/skel-desktop/.config/Code/User \
    /target/etc/skel-desktop/.config/chromium/Default \
    /target/etc/skel-desktop/.config/microsoft-edge/Default \
    /target/etc/skel-desktop/.config/obsidian \
    /target/etc/skel-desktop/.config/vivaldi/Default
  desktop_stage_role_asset etc/skel-desktop/.config/Code/User/settings.json /etc/skel-desktop/.config/Code/User/settings.json 0600
  desktop_stage_role_asset etc/skel-desktop/.config/chromium/Default/Preferences /etc/skel-desktop/.config/chromium/Default/Preferences 0600
  desktop_stage_role_asset etc/skel-desktop/.config/microsoft-edge/Default/Preferences /etc/skel-desktop/.config/microsoft-edge/Default/Preferences 0600
  desktop_stage_role_asset etc/skel-desktop/.config/obsidian/obsidian.json /etc/skel-desktop/.config/obsidian/obsidian.json 0600
  desktop_stage_role_asset etc/skel-desktop/.config/vivaldi/Default/Preferences /etc/skel-desktop/.config/vivaldi/Default/Preferences 0600
  desktop_stage_obsidian_default_vault
  install -d -m 0700 /target/etc/skel-desktop/.config/keepassxc
  desktop_stage_role_asset etc/skel-desktop/.config/keepassxc/keepassxc.ini /etc/skel-desktop/.config/keepassxc/keepassxc.ini 0600
  chmod 0700 /target/etc/skel-desktop/.config/keepassxc
  install -d -m 0700 /target/etc/skel-desktop/.config/zoom
  desktop_stage_role_asset etc/skel-desktop/.config/zoom/zoomus.conf /etc/skel-desktop/.config/zoom/zoomus.conf 0600
  chmod 0700 /target/etc/skel-desktop/.config/zoom
  desktop_stage_role_asset etc/skel-desktop/.config/xdg-desktop-portal/portals.conf /etc/skel-desktop/.config/xdg-desktop-portal/portals.conf 0644
  desktop_stage_role_asset etc/skel-desktop/.config/user-dirs.dirs /etc/skel-desktop/.config/user-dirs.dirs 0644
  desktop_render_chromium_flags
}

desktop_install_user_config() {
  : "${ACCOUNT_USERNAME:?ACCOUNT_USERNAME must be set}"
  : "${ACCOUNT_HOME:?ACCOUNT_HOME must be set}"

  desktop_log "installing primary account desktop config user=${ACCOUNT_USERNAME} home=${ACCOUNT_HOME}"
  # shellcheck disable=SC2016
  run_in_target "install Labwc desktop config for primary account" /bin/sh -c '
set -eu
account_user=$1
account_home=$2
copied_dirs=0
copied_files=0

case "$account_home" in
  /*) ;;
  *) printf "fatal: account home must be absolute\n" >&2; exit 1 ;;
esac
case "$account_home" in
  /|*..*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/-]*)
    printf "fatal: account home contains unsupported path syntax: %s\n" "$account_home" >&2
    exit 1
    ;;
esac

uid=$(id -u "$account_user")
gid=$(id -g "$account_user")

  install -d -m 0700 "$account_home" "$account_home/.config"
  install -d -m 0700 "$account_home/.cache"
  chown "$uid:$gid" "$account_home/.cache"
  for rel in \
    .profile.d \
    .config/labwc \
    .config/waypaper \
    .config/waybar \
    .config/kanshi \
    .config/cargo \
    .config/mise \
    .config/featherpad \
    .config/foot \
    .config/gnote \
    .config/GottCode \
    .config/zathura \
    .local/share/GottCode \
    .local/share/dbus-1 \
    .cache/recoll \
    .config/Recoll.org \
    .recoll \
    .config/kitty \
    .config/micro \
    .config/nano \
    .config/mpv \
    .config/nvim \
    .config/qalculate \
    .config/xarchiver \
    .config/task \
    .config/retroarch \
    .config/sleek \
    .config/tesseract \
    .config/xfce4 \
    .config/btop \
    .config/Code \
    .config/autostart \
    .config/chromium \
    .config/fzf \
    .config/fuzzel \
    .config/Thunar \
    .config/crystal-dock \
    .config/mako \
    .config/satty \
    .config/swaylock \
    .config/wireplumber \
    .config/gtk-3.0 \
    .config/gtk-4.0 \
    .config/keepassxc \
    .config/microsoft-edge \
    .config/obsidian \
    .config/zoom \
    Syncthing/obsidian-md \
    .config/qt6ct \
    .config/systemd \
    .config/vim \
    .config/vivaldi \
    .config/xournalpp \
    .config/xdg-desktop-portal
  do
  src="/etc/skel-desktop/${rel}"
  dst="${account_home}/${rel}"
  [ -d "$src" ] || { printf "fatal: missing skel source: %s\n" "$src" >&2; exit 1; }
  install -d -m 0700 "$dst"
  cp -a "$src/." "$dst/"
  chown -R "$uid:$gid" "$dst"
  copied_dirs=$((copied_dirs + 1))
done
for user_systemd_dir in \
  "$account_home/.config/systemd" \
  "$account_home/.config/systemd/user" \
  "$account_home/.config/systemd/user"/*.d
do
  [ -d "$user_systemd_dir" ] || continue
  chmod 0700 "$user_systemd_dir"
  chown "$uid:$gid" "$user_systemd_dir"
done
if [ -d /etc/skel-desktop/.config/bazel ]; then
  src=/etc/skel-desktop/.config/bazel
  dst="${account_home}/.config/bazel"
  install -d -m 0700 "$dst"
  cp -a "$src/." "$dst/"
  chown -R "$uid:$gid" "$dst"
  copied_dirs=$((copied_dirs + 1))
fi
install -d -m 0700 "$account_home/.local/share/applications"
chown "$uid:$gid" "$account_home/.local/share/applications"
install -m 0600 /etc/skel-desktop/.local/share/applications/tutanota-desktop.desktop \
  "$account_home/.local/share/applications/tutanota-desktop.desktop"
chown "$uid:$gid" "$account_home/.local/share/applications/tutanota-desktop.desktop"
for private_dir in \
  "$account_home/.local/share/task" \
  "$account_home/.local/share/task/hooks" \
  "$account_home/Syncthing" \
  "$account_home/Syncthing/keepassxc" \
  "$account_home/Syncthing/keepassxc/backups" \
  "$account_home/Syncthing/obsidian-md" \
  "$account_home/Syncthing/obsidian-md/.obsidian" \
  "$account_home/Syncthing/obsidian-md/.obsidian/snippets" \
  "$account_home/Syncthing/obsidian-md/.obsidian/themes" \
  "$account_home/Syncthing/obsidian-md/.obsidian/themes/evergreen-notes" \
  "$account_home/Syncthing/obsidian-md/.trash" \
  "$account_home/Syncthing/obsidian-md/archive" \
  "$account_home/Syncthing/obsidian-md/attachments" \
  "$account_home/Syncthing/obsidian-md/daily" \
  "$account_home/Syncthing/obsidian-md/inbox" \
  "$account_home/Syncthing/obsidian-md/templates"
do
  install -d -m 0700 "$private_dir"
  chown "$uid:$gid" "$private_dir"
done
rm -f "$account_home/.config/labwc/xinitrc"
  for rel_file in .profile .bash_profile .bashrc .bash_aliases .zshenv .zprofile .zshrc .zlogout .zsh_aliases .dircolors .vimrc .config/kdiff3rc .config/kwalletrc .config/starship.toml .config/xdg-terminals.list .config/mimeapps.list .config/user-dirs.dirs Syncthing/.stignore; do
  src="/etc/skel-desktop/${rel_file}"
  dst="${account_home}/${rel_file}"
  [ -r "$src" ] || { printf "fatal: missing skel source: %s\n" "$src" >&2; exit 1; }
  file_mode=0600
  parent_mode=0700
  if [ "$rel_file" = Syncthing/.stignore ]; then
    file_mode=0600
    parent_mode=0700
  fi
  install -d -m "$parent_mode" "$(dirname "$dst")"
  install -m "$file_mode" "$src" "$dst"
  chown "$uid:$gid" "$dst"
  copied_files=$((copied_files + 1))
done
  chown "$uid:$gid" "$account_home" "$account_home/.config"
  chmod 0700 "$account_home" "$account_home/.config"
if [ -x /usr/bin/vivaldi-stable ]; then
  for vivaldi_dir in \
    "$account_home/.cache" \
    "$account_home/.cache/vivaldi" \
    "$account_home/.config/vivaldi"
  do
    install -d -m 0700 "$vivaldi_dir"
    chown "$uid:$gid" "$vivaldi_dir"
  done
fi
if command -v /usr/local/bin/labwc-sync-application-launchers >/dev/null 2>&1; then
  /usr/local/bin/labwc-sync-application-launchers "$account_user" "$account_home"
fi
find "$account_home" -xdev -type d -exec chmod 0700 {} +
find "$account_home" -xdev -type f -perm /0100 -exec chmod 0700 {} +
find "$account_home" -xdev -type f ! -perm /0100 -exec chmod 0600 {} +
# Unit files and drop-ins are data, never programs. Do not preserve execute
# bits from a copied/restored skeleton on Whisper or other user units.
find "$account_home/.config/systemd/user" -xdev -type f -exec chmod 0600 {} +
zsh_path=$(command -v zsh 2>/dev/null || true)
if [ -n "$zsh_path" ]; then
  usermod -s "$zsh_path" "$account_user"
fi
account_shell=$(getent passwd "$account_user" | cut -d: -f7)
printf "desktop_account_config user=%s home=%s copied_dirs=%s copied_files=%s shell=%s\n" "$account_user" "$account_home" "$copied_dirs" "$copied_files" "$account_shell"
' sh "$ACCOUNT_USERNAME" "$ACCOUNT_HOME"
  desktop_install_primary_account_calendar_stack
  desktop_bootstrap_primary_account_gpg_key
  run_in_target "publish private browser imports in primary account Downloads" \
    /usr/local/libexec/install-browser-imports --user "$ACCOUNT_USERNAME"
  desktop_log "installed primary account desktop config user=${ACCOUNT_USERNAME}"
}

desktop_unit_has_install_entry() {
  unit=$1
  scope=$2
  unit_path=$3

  for install_key in WantedBy RequiredBy Alias Also; do
    for install_value in $(target_systemd_install_values "$unit_path" "$install_key"); do
      [ -n "$install_value" ] || continue
      return 0
    done
  done
  installer_info "target ${scope} unit has no [Install] entry; leaving static unit unmanaged: ${unit}"
  return 1
}

desktop_enable_unit_if_available() {
  unit=$1
  scope=$2
  unit_path=$(target_systemd_unit_path "$unit" "$scope" 2>/dev/null || true)

  if [ -z "$unit_path" ]; then
    installer_warn "target ${scope} unit is unavailable; skipping enablement: ${unit}"
    return 0
  fi
  desktop_unit_has_install_entry "$unit" "$scope" "$unit_path" || return 0
  stage_target_systemd_unit_enabled "$unit" "$scope"
  desktop_log "staged_${scope}_unit_enabled unit=${unit} unit_path=${unit_path}"
}

desktop_disable_unit_if_available() {
  unit=$1
  scope=$2
  unit_path=$(target_systemd_unit_path "$unit" "$scope" 2>/dev/null || true)

  [ -n "$unit_path" ] || return 0
  if command -v unstage_target_systemd_unit_enabled >/dev/null 2>&1; then
    unstage_target_systemd_unit_enabled "$unit" "$scope"
  fi
  desktop_log "staged_${scope}_unit_disabled unit=${unit} unit_path=${unit_path}"
}

desktop_unit_mask_link_path() {
  unit=$1
  scope=$2
  base_dir=$(target_systemd_scope_base_dir "$scope")

  printf '/target%s/%s\n' "$base_dir" "$unit"
}

desktop_unit_is_masked() {
  unit=$1
  scope=$2
  mask_path=$(desktop_unit_mask_link_path "$unit" "$scope")

  [ -L "$mask_path" ] || return 1
  [ "$(readlink "$mask_path" 2>/dev/null || true)" = /dev/null ]
}

desktop_mask_unit_if_available() {
  unit=$1
  scope=$2

  if desktop_unit_is_masked "$unit" "$scope"; then
    desktop_log "staged_${scope}_unit_masked unit=${unit} unit_path=/dev/null already_masked=true"
    return 0
  fi

  unit_path=$(target_systemd_unit_path "$unit" "$scope" 2>/dev/null || true)

  [ -n "$unit_path" ] || return 0
  desktop_disable_unit_if_available "$unit" "$scope"
  base_dir=$(target_systemd_scope_base_dir "$scope")
  install -d -m 0755 "/target${base_dir}"
  ln -sfn /dev/null "/target${base_dir}/${unit}"
  desktop_log "staged_${scope}_unit_masked unit=${unit} unit_path=${unit_path}"
}

desktop_enable_target_services() {
  desktop_enable_unit_if_available greetd.service system
  desktop_enable_unit_if_available seatd.service system
  desktop_enable_unit_if_available bluetooth-controller-init.service system
  desktop_enable_unit_if_available bluetooth.service system
  desktop_enable_unit_if_available rtkit-daemon.service system
  desktop_enable_unit_if_available upower.service system
  desktop_enable_unit_if_available power-profiles-daemon.service system
  desktop_enable_unit_if_available udisks2.service system
  desktop_enable_unit_if_available NetworkManager.service system
  desktop_enable_unit_if_available NetworkManager-dispatcher.service system
  if desktop_mullvad_selected; then
    desktop_enable_unit_if_available systemd-resolved.service system
    desktop_disable_unit_if_available mullvad-daemon.service system
  fi
  desktop_enable_unit_if_available rsyslog.service system
  desktop_enable_unit_if_available logrotate.timer system
  desktop_mask_unit_if_available systemd-journald-audit.socket system
  desktop_mask_unit_if_available fwupd-refresh.service system
  desktop_mask_unit_if_available fwupd-refresh.timer system
  desktop_disable_unit_if_available mpris-proxy.service user
  desktop_disable_unit_if_available waybar.service user
  desktop_disable_unit_if_available foot-server.service user
  desktop_enable_unit_if_available managed-clamav-signature-update.timer system
  desktop_mask_unit_if_available clamav-freshclam.service system
  desktop_mask_unit_if_available fangfrisch.timer system
  if [ "${LABWC_NVIDIA_ACCELERATION_AVAILABLE:-false}" = true ]; then
    desktop_mask_unit_if_available nvidia-persistenced.service system
    desktop_mask_unit_if_available nvidia-powerd.service system
  fi

  for unit in \
    labwc-output-watch.service \
    swaybg.service \
    kanshi.service \
    swayidle.service \
    crystal-dock.service \
    labwc-mute-default-microphone.service \
    labwc-kwallet-portal.service \
    labwc-plans.service \
    foot-server.socket \
    mako.service \
    filter-chain.service \
    labwc-calendar-sync.timer \
    labwc-sync-application-launchers.service \
    labwc-sync-application-launchers.path \
    wayscriber.service \
    hyprpolkitagent.service \
    xdg-desktop-portal.service \
    xdg-desktop-portal-gtk.service \
    xdg-desktop-portal-wlr.service \
    xdg-desktop-portal-lxqt.service
  do
    desktop_stage_user_unit_wanted_by "$unit" labwc-session.target
  done

  if desktop_whisper_persistent_memory_enabled; then
    desktop_stage_user_unit_wanted_by whisper-server.service labwc-session.target
  fi

  if [ -r "/target$(desktop_user_unit_template_dir)/managed-external-software-notify.path" ]; then
    desktop_stage_user_unit_wanted_by managed-external-software-notify.path labwc-session.target
  fi

  stage_target_default_systemd_unit "${LABWC_DESKTOP_DEFAULT_TARGET:-graphical.target}"
  desktop_log "staged_default_target target=${LABWC_DESKTOP_DEFAULT_TARGET:-graphical.target}"
}
