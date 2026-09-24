#!/bin/sh
# Sourced installer module; edit this file directly.

installer_classes_install_conf_relpath() {
  printf '%s\n' "classes/install.conf"
}

installer_classes_conf_cache_path() {
  printf '%s/cache/classes.state.conf\n' "${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}"
}

installer_classes_plan_path() {
  printf '%s/state/plan.tsv\n' "${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}"
}

installer_ensure_classes_conf_path() {
  if [ -n "${INSTALLER_CLASSES_CONF_PATH_CACHE:-}" ]; then
    return 0
  fi
  INSTALLER_CLASSES_CONF_PATH_CACHE=$(installer_classes_conf_cache_path)
}

installer_classes_conf_path() {
  installer_ensure_classes_conf_path
  printf '%s\n' "$INSTALLER_CLASSES_CONF_PATH_CACHE"
}

installer_class_metadata_read_path() {
  metadata_relpath=$1
  installer_validate_relative_seed_path "$metadata_relpath"

  if [ -n "${INSTALLER_SOURCE_ROOT:-}" ]; then
    metadata_path="${INSTALLER_SOURCE_ROOT%/}/${metadata_relpath}"
    [ -r "$metadata_path" ] || installer_fatal "installer class metadata is not readable: ${metadata_path}"
    printf '%s\n' "$metadata_path"
    return 0
  fi

  metadata_path="$(installer_runtime_cache_dir)/${metadata_relpath}"
  if [ ! -s "$metadata_path" ]; then
    seed_base=$(installer_seed_base "")
    install -d -m 0700 "$(dirname "$metadata_path")"
    installer_fetch_file "$seed_base" "$metadata_relpath" "$metadata_path" 0600
  fi
  printf '%s\n' "$metadata_path"
}

installer_class_config_relpaths() {
  install_conf_path=$1
  awk '
    function trim(value) {
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
      return value
    }
    /^[[:space:]]*($|#)/ { next }
    /^Config:[[:space:]]*/ {
      line=$0
      sub(/^[^:]+:[[:space:]]*/, "", line)
      line=trim(line)
      if (line != "") {
        print line
      }
    }
  ' "$install_conf_path"
}

installer_classes_cache_name_token() {
  printf '%s' "$1" | tr -c 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789' '_'
}

installer_classes_section_var_name() {
  printf 'INSTALLER_CLASSES_SECTION__%s\n' "$(installer_classes_cache_name_token "$1")"
}

installer_classes_value_var_name() {
  printf 'INSTALLER_CLASSES_VALUE__%s__%s\n' \
    "$(installer_classes_cache_name_token "$1")" \
    "$(installer_classes_cache_name_token "$2")"
}

installer_classes_cache_add_section() {
  section_name=$1
  INSTALLER_CLASSES_SECTION_NAMES="${INSTALLER_CLASSES_SECTION_NAMES:+$INSTALLER_CLASSES_SECTION_NAMES }$section_name"
  section_var=$(installer_classes_section_var_name "$section_name")
  eval "$section_var=1"
}

installer_classes_cache_set_value() {
  section_name=$1
  key_name=$2
  key_value=$3
  value_var=$(installer_classes_value_var_name "$section_name" "$key_name")
  eval "$value_var=$(installer_shell_quote "$key_value")"
}

installer_classes_cache_maybe_set_value() {
  section_name=$1
  key_name=$2
  key_value=${3:-}
  [ -n "$key_value" ] || return 0
  installer_classes_cache_set_value "$section_name" "$key_name" "$key_value"
}

installer_classes_plan_field_value() {
  case "${1:-}" in
    __EMPTY__) printf '%s\n' "" ;;
    *) printf '%s\n' "${1:-}" ;;
  esac
}

installer_generate_class_plan() {
  install_conf_relpath=$(installer_classes_install_conf_relpath)
  install_conf_path=$(installer_class_metadata_read_path "$install_conf_relpath")
  plan_path=$(installer_classes_plan_path)
  state_path=$(installer_classes_conf_cache_path)

  if [ -s "$plan_path" ] && [ -s "$state_path" ]; then
    return 0
  fi

  config_paths=
  while IFS= read -r config_relpath || [ -n "$config_relpath" ]; do
    [ -n "$config_relpath" ] || continue
    config_path=$(installer_class_metadata_read_path "$config_relpath")
    case "$config_paths" in
      '')
        config_paths=$config_path
        ;;
      *)
        config_paths="${config_paths}|${config_path}"
        ;;
    esac
  done <<EOF
$(installer_class_config_relpaths "$install_conf_path")
EOF
  [ -n "$config_paths" ] || installer_fatal "classes/install.conf must define at least one Config: entry"

  install -d -m 0700 "$(dirname "$plan_path")" "$(dirname "$state_path")"
  plan_tmp="${plan_path}.tmp.$$"
  state_tmp="${state_path}.tmp.$$"
  : >"$state_tmp"

  if awk -v install_conf_path="$install_conf_path" -v config_paths="$config_paths" -v state_path="$state_tmp" '
    BEGIN {
      OFS = "\t"
      parse_install_conf(install_conf_path)
      config_count = split(config_paths, config_path_list, /\|/)
      if (config_count < 1) {
        fail("classes/install.conf resolved no readable config sources")
      }
      for (config_index = 1; config_index <= config_count; config_index++) {
        if (config_path_list[config_index] == "") {
          continue
        }
        parse_config_file(config_path_list[config_index])
      }
      finalize_record()
      emit_state()
      emit_plan()
      close(state_path)
      exit 0
    }

    function fail(message) {
      print "fatal: " message > "/dev/stderr"
      exit 1
    }

    function trim(value) {
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
      return value
    }

    function normalize_word_list(value) {
      value = trim(value)
      gsub(/,/, " ", value)
      gsub(/[[:space:]]+/, " ", value)
      return value
    }

    function state_set(section_name, key_name, key_value) {
      if (key_value != "") {
        state_values[section_name, key_name] = key_value
      }
    }

    function parse_install_conf(path,   line, field_name, field_value) {
      install_conf_line = 0
      while ((getline line < path) > 0) {
        install_conf_line++
        sub(/\r$/, "", line)
        if (line ~ /^[[:space:]]*$/ || line ~ /^[[:space:]]*#/) {
          continue
        }
        separator_index = index(line, ":")
        if (separator_index == 0) {
          fail("malformed classes/install.conf line " install_conf_line ": expected Field: value")
        }
        field_name = trim(substr(line, 1, separator_index - 1))
        field_value = trim(substr(line, separator_index + 1))
        if (field_name == "ManifestVersion") {
          if (manifest_version_seen) {
            fail("duplicate ManifestVersion in classes/install.conf")
          }
          manifest_version = field_value
          manifest_version_seen = 1
          continue
        }
        if (field_name == "ClassTokenFormats") {
          if (class_token_formats_seen) {
            fail("duplicate ClassTokenFormats in classes/install.conf")
          }
          class_token_formats = normalize_word_list(field_value)
          class_token_formats_seen = 1
          continue
        }
        if (field_name == "Config") {
          continue
        }
        fail("unsupported field in classes/install.conf line " install_conf_line ": " field_name)
      }
      close(path)
    }

    function record_reset() {
      record_active = 0
      delete record_values
      delete record_seen
      current_config_path = ""
      current_config_line = 0
    }

    function config_field_key(field_name) {
      if (field_name == "Type" || field_name == "type") return "type"
      if (field_name == "Group" || field_name == "group") return "group"
      if (field_name == "Name" || field_name == "name") return "name"
      if (field_name == "Required" || field_name == "required") return "required"
      if (field_name == "Multi" || field_name == "multi") return "multi"
      if (field_name == "Order" || field_name == "order") return "order"
      if (field_name == "Purpose" || field_name == "purpose") return "purpose"
      if (field_name == "Source" || field_name == "source") return "source"
      if (field_name == "Description" || field_name == "description") return "description"
      if (field_name == "HostVariant" || field_name == "Host-Variant" || field_name == "host_variant") return "host_variant"
      if (field_name == "LateHelper" || field_name == "Late-Helper" || field_name == "late_helper") return "late_helper"
      if (field_name == "LateHelperOrder" || field_name == "Late-Helper-Order" || field_name == "late_helper_order") return "late_helper_order"
      if (field_name == "EarlyHelper" || field_name == "Early-Helper" || field_name == "early_helper") return "early_helper"
      if (field_name == "PartmanHelper" || field_name == "Partman-Helper" || field_name == "partman_helper") return "partman_helper"
      if (field_name == "HostProfilePrefix" || field_name == "Host-Profile-Prefix" || field_name == "host_profile_prefix") return "host_profile_prefix"
      if (field_name == "HostFamily" || field_name == "Host-Family" || field_name == "host_family") return "host_family"
      if (field_name == "HookFamily" || field_name == "Hook-Family" || field_name == "hook_family") return "hook_family"
      if (field_name == "InstallDiskCandidates" || field_name == "Install-Disk-Candidates" || field_name == "install_disk_candidates") return "install_disk_candidates"
      if (field_name == "DefaultInstallDisk" || field_name == "Default-Install-Disk" || field_name == "default_install_disk") return "default_install_disk"
      if (field_name == "AllowedHardwareClasses" || field_name == "Allowed-Hardware-Classes" || field_name == "allowed_hardware_classes") return "allowed_hardware_classes"
      if (field_name == "RejectedClasses" || field_name == "Rejected-Classes" || field_name == "rejected_classes") return "rejected_classes"
      if (field_name == "RequiresClasses" || field_name == "Requires-Classes" || field_name == "requires_classes") return "requires_classes"
      if (field_name == "DebianAptPreferences" || field_name == "Debian-Apt-Preferences" || field_name == "debian_apt_preferences") return "debian_apt_preferences"
      return ""
    }

    function normalize_field_value(field_key, field_value) {
      if (field_key == "allowed_hardware_classes" ||
          field_key == "debian_apt_preferences" ||
          field_key == "install_disk_candidates" ||
          field_key == "rejected_classes" ||
          field_key == "requires_classes") {
        return normalize_word_list(field_value)
      }
      return trim(field_value)
    }

    function record_assign_field(field_name, field_value,   field_key, normalized_value) {
      field_key = config_field_key(field_name)
      if (field_key == "") {
        fail("unsupported field in " current_config_path ":" current_config_line ": " field_name)
      }
      if (record_seen[field_key]) {
        fail("duplicate field in " current_config_path ":" current_config_line ": " field_name)
      }
      normalized_value = normalize_field_value(field_key, field_value)
      record_values[field_key] = normalized_value
      record_seen[field_key] = 1
      record_active = 1
    }

    function parse_config_file(path,   line, field_name, field_value) {
      current_config_path = path
      current_config_line = 0
      while ((getline line < path) > 0) {
        current_config_line++
        sub(/\r$/, "", line)
        if (line ~ /^[[:space:]]*$/) {
          finalize_record()
          continue
        }
        if (line ~ /^[[:space:]]*#/) {
          continue
        }
        separator_index = index(line, ":")
        if (separator_index == 0) {
          fail("malformed config line in " path ":" current_config_line ": expected Field: value")
        }
        field_name = trim(substr(line, 1, separator_index - 1))
        field_value = substr(line, separator_index + 1)
        record_assign_field(field_name, field_value)
      }
      close(path)
      finalize_record()
    }

    function finalize_record(   record_type, group_name, class_name, state_section, record_key, key_index) {
      if (!record_active) {
        return
      }
      record_type = tolower(record_values["type"])
      if (record_type == "group") {
        group_name = record_values["name"]
        if (group_name == "") {
          fail("group record in " current_config_path " is missing Name")
        }
        if (record_values["group"] != "") {
          fail("group record in " current_config_path " must not define Group: " record_values["group"])
        }
        if (group_seen[group_name]) {
          fail("duplicate group record in configs/groups.cfg: " group_name)
        }
        group_seen[group_name] = 1
        group_list[++group_count] = group_name
        state_section = "group." group_name
        state_set(state_section, "required", record_values["required"])
        state_set(state_section, "multi", record_values["multi"])
        state_set(state_section, "order", record_values["order"])
        state_set(state_section, "purpose", record_values["purpose"])
        state_set(state_section, "source", record_values["source"])
        state_set(state_section, "description", record_values["description"])
      } else if (record_type == "class") {
        group_name = record_values["group"]
        class_name = record_values["name"]
        if (group_name == "") {
          fail("class record in " current_config_path " is missing Group")
        }
        if (class_name == "") {
          fail("class record in " current_config_path " is missing Name")
        }
        record_key = group_name "/" class_name
        if (class_seen[record_key]) {
          fail("duplicate class record in configs/*.cfg: " record_key)
        }
        class_seen[record_key] = 1
        class_group_list[++class_count] = group_name
        class_name_list[class_count] = class_name
        state_section = "class." group_name "." class_name
        state_set(state_section, "description", record_values["description"])
        state_set(state_section, "host_variant", record_values["host_variant"])
        state_set(state_section, "late_helper", record_values["late_helper"])
        state_set(state_section, "late_helper_order", record_values["late_helper_order"])
        state_set(state_section, "early_helper", record_values["early_helper"])
        state_set(state_section, "partman_helper", record_values["partman_helper"])
        state_set(state_section, "host_profile_prefix", record_values["host_profile_prefix"])
        state_set(state_section, "host_family", record_values["host_family"])
        state_set(state_section, "hook_family", record_values["hook_family"])
        state_set(state_section, "install_disk_candidates", record_values["install_disk_candidates"])
        state_set(state_section, "default_install_disk", record_values["default_install_disk"])
        state_set(state_section, "allowed_hardware_classes", record_values["allowed_hardware_classes"])
        state_set(state_section, "rejected_classes", record_values["rejected_classes"])
        state_set(state_section, "requires_classes", record_values["requires_classes"])
        state_set(state_section, "debian_apt_preferences", record_values["debian_apt_preferences"])
      } else {
        fail("record in " current_config_path " must define Type: group or Type: class")
      }
      record_reset()
    }

    function emit_state_section(section_name, key_list,   key_count, key_names, key_index, key_name, key_value) {
      print "[" section_name "]" >> state_path
      key_count = split(key_list, key_names, / /)
      for (key_index = 1; key_index <= key_count; key_index++) {
        key_name = key_names[key_index]
        key_value = state_values[section_name, key_name]
        if (key_value == "") {
          continue
        }
        print key_name "=" key_value >> state_path
      }
      print "" >> state_path
    }

    function emit_state(   class_section, class_index) {
      if (manifest_version != "" || class_token_formats != "") {
        state_set("manifest", "version", manifest_version)
        state_set("manifest", "class_token_formats", class_token_formats)
        emit_state_section("manifest", "version class_token_formats")
      }
      for (group_index = 1; group_index <= group_count; group_index++) {
        emit_state_section("group." group_list[group_index], "required multi order purpose source description")
      }
      for (class_index = 1; class_index <= class_count; class_index++) {
        class_section = "class." class_group_list[class_index] "." class_name_list[class_index]
        emit_state_section(class_section, "description host_variant late_helper late_helper_order early_helper partman_helper host_profile_prefix host_family hook_family install_disk_candidates default_install_disk allowed_hardware_classes rejected_classes requires_classes debian_apt_preferences")
      }
    }

    function emit_plan(   class_section, class_index, group_section) {
      if (manifest_version != "") {
        print "manifest", "version", manifest_version
      }
      if (class_token_formats != "") {
        print "manifest", "class_token_formats", class_token_formats
      }
      for (group_index = 1; group_index <= group_count; group_index++) {
        group_section = "group." group_list[group_index]
        print "group", group_list[group_index], \
          plan_cell(state_values[group_section, "required"]), \
          plan_cell(state_values[group_section, "multi"]), \
          plan_cell(state_values[group_section, "order"]), \
          plan_cell(state_values[group_section, "purpose"]), \
          plan_cell(state_values[group_section, "source"]), \
          plan_cell(state_values[group_section, "description"])
      }
      for (class_index = 1; class_index <= class_count; class_index++) {
        class_section = "class." class_group_list[class_index] "." class_name_list[class_index]
        print "class", class_group_list[class_index], class_name_list[class_index], \
          plan_cell(state_values[class_section, "description"]), \
          plan_cell(state_values[class_section, "host_variant"]), \
          plan_cell(state_values[class_section, "late_helper"]), \
          plan_cell(state_values[class_section, "late_helper_order"]), \
          plan_cell(state_values[class_section, "early_helper"]), \
          plan_cell(state_values[class_section, "partman_helper"]), \
          plan_cell(state_values[class_section, "host_profile_prefix"]), \
          plan_cell(state_values[class_section, "host_family"]), \
          plan_cell(state_values[class_section, "hook_family"]), \
          plan_cell(state_values[class_section, "install_disk_candidates"]), \
          plan_cell(state_values[class_section, "default_install_disk"]), \
          plan_cell(state_values[class_section, "allowed_hardware_classes"]), \
          plan_cell(state_values[class_section, "rejected_classes"]), \
          plan_cell(state_values[class_section, "requires_classes"]), \
          plan_cell(state_values[class_section, "debian_apt_preferences"])
      }
    }

    function plan_cell(value) {
      return value == "" ? "__EMPTY__" : value
    }
  ' >"$plan_tmp"; then
    :
  else
    plan_status=$?
    rm -f "$plan_tmp" "$state_tmp"
    return "$plan_status"
  fi

  mv "$plan_tmp" "$plan_path"
  mv "$state_tmp" "$state_path"
  chmod 0600 "$plan_path" "$state_path" 2>/dev/null || true
}

