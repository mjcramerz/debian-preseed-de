#!/bin/sh
# Sourced installer module; edit this file directly.

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
recovery.py
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
  managed_app_manifest="${TMP_ENV_DIR}/labwc-app.manifest.$$"

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
      managed_app_module_tmp="${TMP_ENV_DIR}/labwc-app-module.$$.tmp"
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

