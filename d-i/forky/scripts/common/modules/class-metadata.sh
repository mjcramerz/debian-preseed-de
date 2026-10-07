#!/bin/sh
# Sourced installer module; edit this file directly.

installer_classes_cache_ensure() {
  if [ "${INSTALLER_CLASSES_CACHE_READY:-0}" -eq 1 ]; then
    return 0
  fi

  installer_ensure_classes_conf_path
  installer_generate_class_plan
  conf_path=$INSTALLER_CLASSES_CONF_PATH_CACHE
  plan_path=$(installer_classes_plan_path)
  tab_char=$(printf '\t')
  INSTALLER_CLASSES_SECTION_NAMES=
  INSTALLER_CLASSES_GROUP_NAMES_TEXT=
  INSTALLER_CLASSES_CLASS_RECORDS_TEXT=
  while IFS="$tab_char" read -r plan_kind plan_a plan_b plan_c plan_d plan_e plan_f plan_g plan_h plan_i plan_j plan_k plan_l plan_m plan_n plan_o plan_p plan_q || [ -n "${plan_kind:-}" ]; do
    [ -n "${plan_kind:-}" ] || continue
    case "$plan_kind" in
      manifest)
        installer_classes_cache_add_section manifest
        installer_classes_cache_maybe_set_value manifest "$plan_a" "$plan_b"
        ;;
      group)
        group_name=$plan_a
        [ -n "$group_name" ] || continue
        section_name="group.${group_name}"
        installer_classes_cache_add_section "$section_name"
        INSTALLER_CLASSES_GROUP_NAMES_TEXT="${INSTALLER_CLASSES_GROUP_NAMES_TEXT:+$INSTALLER_CLASSES_GROUP_NAMES_TEXT }${group_name}"
        installer_classes_cache_maybe_set_value "$section_name" required "$(installer_classes_plan_field_value "$plan_b")"
        installer_classes_cache_maybe_set_value "$section_name" multi "$(installer_classes_plan_field_value "$plan_c")"
        installer_classes_cache_maybe_set_value "$section_name" order "$(installer_classes_plan_field_value "$plan_d")"
        installer_classes_cache_maybe_set_value "$section_name" purpose "$(installer_classes_plan_field_value "$plan_e")"
        installer_classes_cache_maybe_set_value "$section_name" source "$(installer_classes_plan_field_value "$plan_f")"
        installer_classes_cache_maybe_set_value "$section_name" description "$(installer_classes_plan_field_value "$plan_g")"
        ;;
      class)
        group_name=$plan_a
        class_name=$plan_b
        [ -n "$group_name" ] || continue
        [ -n "$class_name" ] || continue
        section_name="class.${group_name}.${class_name}"
        installer_classes_cache_add_section "$section_name"
        INSTALLER_CLASSES_CLASS_RECORDS_TEXT="${INSTALLER_CLASSES_CLASS_RECORDS_TEXT:+$INSTALLER_CLASSES_CLASS_RECORDS_TEXT }${group_name}.${class_name}"
        installer_classes_cache_maybe_set_value "$section_name" description "$(installer_classes_plan_field_value "$plan_c")"
        installer_classes_cache_maybe_set_value "$section_name" host_variant "$(installer_classes_plan_field_value "$plan_d")"
        installer_classes_cache_maybe_set_value "$section_name" late_helper "$(installer_classes_plan_field_value "$plan_e")"
        installer_classes_cache_maybe_set_value "$section_name" late_helper_order "$(installer_classes_plan_field_value "$plan_f")"
        installer_classes_cache_maybe_set_value "$section_name" early_helper "$(installer_classes_plan_field_value "$plan_g")"
        installer_classes_cache_maybe_set_value "$section_name" partman_helper "$(installer_classes_plan_field_value "$plan_h")"
        installer_classes_cache_maybe_set_value "$section_name" host_profile_prefix "$(installer_classes_plan_field_value "$plan_i")"
        installer_classes_cache_maybe_set_value "$section_name" host_family "$(installer_classes_plan_field_value "$plan_j")"
        installer_classes_cache_maybe_set_value "$section_name" hook_family "$(installer_classes_plan_field_value "$plan_k")"
        installer_classes_cache_maybe_set_value "$section_name" install_disk_candidates "$(installer_classes_plan_field_value "$plan_l")"
        installer_classes_cache_maybe_set_value "$section_name" default_install_disk "$(installer_classes_plan_field_value "$plan_m")"
        installer_classes_cache_maybe_set_value "$section_name" allowed_hardware_classes "$(installer_classes_plan_field_value "$plan_n")"
        installer_classes_cache_maybe_set_value "$section_name" rejected_classes "$(installer_classes_plan_field_value "$plan_o")"
        installer_classes_cache_maybe_set_value "$section_name" requires_classes "$(installer_classes_plan_field_value "$plan_p")"
        installer_classes_cache_maybe_set_value "$section_name" debian_apt_preferences "$(installer_classes_plan_field_value "$plan_q")"
        ;;
    esac
  done <"$plan_path"

  INSTALLER_CLASSES_CACHE_READY=1
}

installer_ini_get_generic() {
  ini_file=$1
  ini_section=$2
  ini_key=$3
  ini_cr=$(printf '\r')

  installer_in_section=false
  while IFS= read -r ini_line || [ -n "$ini_line" ]; do
    case "$ini_line" in
      *"$ini_cr") ini_line=${ini_line%"$ini_cr"} ;;
    esac
    case "$ini_line" in
      ''|'#'*|';'*) continue ;;
      \[*\])
        ini_section_name=${ini_line#\[}
        ini_section_name=${ini_section_name%\]}
        if [ "$ini_section_name" = "$ini_section" ]; then
          installer_in_section=true
        else
          installer_in_section=false
        fi
        continue
        ;;
    esac
    [ "$installer_in_section" = true ] || continue
    case "$ini_line" in
      *=*)
        current_key=${ini_line%%=*}
        [ "$current_key" = "$ini_key" ] || continue
        printf '%s\n' "${ini_line#*=}"
        return 0
        ;;
      esac
  done <"$ini_file"
}

installer_ini_get() {
  ini_file=$1
  ini_section=$2
  ini_key=$3
  installer_ensure_classes_conf_path
  conf_path=$INSTALLER_CLASSES_CONF_PATH_CACHE

  if [ "$ini_file" = "$conf_path" ]; then
    installer_classes_cache_ensure
    value_var=$(installer_classes_value_var_name "$ini_section" "$ini_key")
    value_is_set=
    eval "value_is_set=\${$value_var+x}"
    [ "$value_is_set" = x ] || return 1
    eval "printf '%s\n' \"\${$value_var}\""
    return 0
  fi

  installer_ini_get_generic "$ini_file" "$ini_section" "$ini_key"
}

installer_ini_has_section_generic() {
  ini_file=$1
  ini_section=$2
  ini_cr=$(printf '\r')

  while IFS= read -r ini_line || [ -n "$ini_line" ]; do
    case "$ini_line" in
      *"$ini_cr") ini_line=${ini_line%"$ini_cr"} ;;
    esac
    case "$ini_line" in
      ''|'#'*|';'*) continue ;;
      \[*\])
        ini_section_name=${ini_line#\[}
        ini_section_name=${ini_section_name%\]}
        [ "$ini_section_name" = "$ini_section" ] && return 0
        ;;
    esac
  done <"$ini_file"
  return 1
}

installer_ini_has_section() {
  ini_file=$1
  ini_section=$2
  installer_ensure_classes_conf_path
  conf_path=$INSTALLER_CLASSES_CONF_PATH_CACHE

  if [ "$ini_file" = "$conf_path" ]; then
    installer_classes_cache_ensure
    section_var=$(installer_classes_section_var_name "$ini_section")
    section_is_set=
    eval "section_is_set=\${$section_var+x}"
    [ "$section_is_set" = x ]
    return $?
  fi

  installer_ini_has_section_generic "$ini_file" "$ini_section"
}

installer_ini_sections_with_prefix_generic() {
  ini_file=$1
  section_prefix=$2
  ini_cr=$(printf '\r')

  while IFS= read -r ini_line || [ -n "$ini_line" ]; do
    case "$ini_line" in
      *"$ini_cr") ini_line=${ini_line%"$ini_cr"} ;;
    esac
    case "$ini_line" in
      ''|'#'*|';'*) continue ;;
      \[*\])
        ini_section_name=${ini_line#\[}
        ini_section_name=${ini_section_name%\]}
        case "$ini_section_name" in
          "${section_prefix}"*)
            printf '%s\n' "${ini_section_name#"$section_prefix"}"
            ;;
        esac
        ;;
    esac
  done <"$ini_file"
}

installer_ini_sections_with_prefix() {
  ini_file=$1
  section_prefix=$2
  installer_ensure_classes_conf_path
  conf_path=$INSTALLER_CLASSES_CONF_PATH_CACHE

  if [ "$ini_file" = "$conf_path" ]; then
    installer_classes_cache_ensure
    case "$section_prefix" in
      group.)
        for ini_section_name in $INSTALLER_CLASSES_GROUP_NAMES_TEXT; do
          printf '%s\n' "$ini_section_name"
        done
        return 0
        ;;
      class.)
        for ini_section_name in $INSTALLER_CLASSES_CLASS_RECORDS_TEXT; do
          printf '%s\n' "$ini_section_name"
        done
        return 0
        ;;
    esac
    for ini_section_name in $INSTALLER_CLASSES_SECTION_NAMES; do
      case "$ini_section_name" in
        "${section_prefix}"*)
          printf '%s\n' "${ini_section_name#"$section_prefix"}"
          ;;
      esac
    done
    return 0
  fi

  installer_ini_sections_with_prefix_generic "$ini_file" "$section_prefix"
}

installer_group_required_status() {
  group_name=$1
  installer_ensure_classes_conf_path
  conf_path=$INSTALLER_CLASSES_CONF_PATH_CACHE
  required_value=$(installer_ini_get "$conf_path" "group.${group_name}" required 2>/dev/null || true)
  case "$required_value" in
    1|true|TRUE|yes|YES|on|ON|required) printf '%s\n' required ;;
    *) printf '%s\n' optional ;;
  esac
}

installer_group_order() {
  group_name=$1
  installer_ensure_classes_conf_path
  conf_path=$INSTALLER_CLASSES_CONF_PATH_CACHE
  order=$(installer_ini_get "$conf_path" "group.${group_name}" order 2>/dev/null || true)
  case "$order" in
    ''|*[!0-9]*) printf '%s\n' 1000 ;;
    *) printf '%s\n' "$order" ;;
  esac
}

installer_group_purpose() {
  group_name=$1
  installer_ensure_classes_conf_path
  conf_path=$INSTALLER_CLASSES_CONF_PATH_CACHE
  installer_ini_get "$conf_path" "group.${group_name}" purpose 2>/dev/null || true
}

installer_group_source() {
  group_name=$1
  installer_ensure_classes_conf_path
  conf_path=$INSTALLER_CLASSES_CONF_PATH_CACHE
  source_value=$(installer_ini_get "$conf_path" "group.${group_name}" source 2>/dev/null || true)
  case "$source_value" in
    class-auto|class-select|class-profile|class-addon|class-apps) printf '%s\n' "$source_value" ;;
    '') printf '%s\n' class-select ;;
    *) installer_fatal "group ${group_name} has invalid source value: ${source_value}" ;;
  esac
}

installer_group_multi_status() {
  group_name=$1
  installer_ensure_classes_conf_path
  conf_path=$INSTALLER_CLASSES_CONF_PATH_CACHE
  multi_value=$(installer_ini_get "$conf_path" "group.${group_name}" multi 2>/dev/null || true)
  case "$multi_value" in
    1|true|TRUE|yes|YES|on|ON|multi) printf '%s\n' multi ;;
    *) printf '%s\n' single ;;
  esac
}

installer_group_is_multi() {
  [ "$(installer_group_multi_status "$1")" = multi ]
}

installer_group_context_var() {
  group_name=$1
  case "$group_name" in
    ''|*[!abcdefghijklmnopqrstuvwxyz0-9-]*)
      installer_fatal "group name contains unsupported characters: ${group_name:-unset}"
      ;;
  esac
  context_group=$(printf '%s' "$group_name" | sed 'y/abcdefghijklmnopqrstuvwxyz-/ABCDEFGHIJKLMNOPQRSTUVWXYZ_/')
  printf 'INSTALLER_%s_CLASS\n' "$context_group"
}

installer_group_names() {
  installer_classes_cache_ensure
  for group_name in $INSTALLER_CLASSES_GROUP_NAMES_TEXT; do
    printf '%s\n' "$group_name"
  done
}

installer_seed_path_exists() (
  installer_load_source_library "$1" || exit 1
  source_exists "$1" "$2"
)

installer_class_source_path() {
  group_name=$1
  class_name=$2
  case "$(installer_group_source "$group_name")" in
    class-auto)
      printf 'classes/class-auto/%s/%s.cfg\n' "$group_name" "$class_name"
      ;;
    class-select)
      printf 'classes/class-select/%s/%s.cfg\n' "$group_name" "$class_name"
      ;;
    class-profile)
      printf 'classes/class-profile/%s.cfg\n' "$class_name"
      ;;
    class-addon)
      printf 'classes/class-addon/%s.cfg\n' "$class_name"
      ;;
    class-apps)
      printf 'classes/class-apps/%s.cfg\n' "$class_name"
      ;;
  esac
}

installer_class_meta_value() {
  seed_base=$1
  group_name=$2
  class_name=$3
  meta_key=$4
  installer_ensure_classes_conf_path
  conf_path=$INSTALLER_CLASSES_CONF_PATH_CACHE
  installer_ini_get "$conf_path" "class.${group_name}.${class_name}" "$meta_key" 2>/dev/null || true
}

installer_configured_class_records() {
  installer_classes_cache_ensure
  for class_record in $INSTALLER_CLASSES_CLASS_RECORDS_TEXT; do
    printf '%s\n' "$class_record"
  done
}

installer_validate_class_group_name() {
  label=$1
  value=$2
  case "$value" in
    ''|*[!abcdefghijklmnopqrstuvwxyz0123456789-]*)
      installer_fatal "${label} contains unsupported characters: ${value:-unset}"
      ;;
  esac
}

installer_validate_class_name() {
  label=$1
  value=$2
  case "$value" in
    ''|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-]*)
      installer_fatal "${label} contains unsupported characters: ${value:-unset}"
      ;;
  esac
}

installer_validate_class_purpose() {
  label=$1
  value=$2
  case "$value" in
    ''|*[!abcdefghijklmnopqrstuvwxyz0123456789-]*)
      installer_fatal "${label} contains unsupported characters: ${value:-unset}"
      ;;
  esac
}

installer_class_token_parts() {
  class_token=$1
  INSTALLER_CLASS_TOKEN_GROUP=
  INSTALLER_CLASS_TOKEN_NAME=
  token_class_group=
  token_class_name=

  case "$class_token" in
    */*)
      token_class_group=${class_token%%/*}
      token_class_name=${class_token#*/}
      case "$token_class_name" in
        */*) installer_fatal "class token contains more than one '/' separator: ${class_token}" ;;
      esac
      ;;
    *:*)
      token_class_group=${class_token%%:*}
      token_class_name=${class_token#*:}
      case "$token_class_name" in
        *:*) installer_fatal "class token contains more than one ':' separator: ${class_token}" ;;
      esac
      ;;
    *.*)
      token_class_group=${class_token%%.*}
      token_class_name=${class_token#*.}
      case "$token_class_name" in
        *.*) installer_fatal "class token contains more than one '.' separator: ${class_token}" ;;
      esac
      ;;
    *)
      token_class_group=
      token_class_name=$class_token
      ;;
  esac

  if [ -n "$token_class_group" ]; then
    installer_validate_class_group_name "class token group" "$token_class_group"
  fi
  installer_validate_class_name "class token class" "$token_class_name"
  INSTALLER_CLASS_TOKEN_GROUP=$token_class_group
  INSTALLER_CLASS_TOKEN_NAME=$token_class_name
  printf '%s\n' "$token_class_name"
}

installer_class_exists() {
  seed_base=$1
  group_name=$2
  class_name=$3
  class_relpath=$(installer_class_source_path "$group_name" "$class_name")

  if [ -n "${INSTALLER_SOURCE_ROOT:-}" ] && [ -r "${INSTALLER_SOURCE_ROOT%/}/${class_relpath}" ]; then
    return 0
  fi
  [ -n "$seed_base" ] || return 1
  installer_seed_path_exists "$seed_base" "$class_relpath"
}

installer_class_has_manifest_record() {
  group_name=$1
  class_name=$2
  installer_ensure_classes_conf_path
  conf_path=$INSTALLER_CLASSES_CONF_PATH_CACHE
  installer_ini_has_section "$conf_path" "class.${group_name}.${class_name}"
}

installer_validate_helper_name() {
  label=$1
  value=$2
  [ -n "$value" ] || return 0
  case "$value" in
    *[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-]*)
      installer_fatal "${label} contains unsupported characters: ${value}"
      ;;
  esac
}

installer_class_helper_order() {
  seed_base=$1
  group_name=$2
  class_name=$3
  helper_order=$(installer_class_meta_value "$seed_base" "$group_name" "$class_name" late_helper_order)
  case "$helper_order" in
    '')
      installer_group_order "$group_name"
      ;;
    *[!0-9]*)
      installer_fatal "class ${group_name}/${class_name} late_helper_order must be numeric: ${helper_order}"
      ;;
    *)
      printf '%s\n' "$helper_order"
      ;;
  esac
}

installer_validate_class_reference() {
  label=$1
  reference=$2
  installer_class_token_parts "$reference" >/dev/null
  [ -n "${INSTALLER_CLASS_TOKEN_NAME:-}" ] || installer_fatal "${label} is empty"
}

installer_validate_class_reference_list() {
  label=$1
  references=$2
  for class_reference in $references; do
    installer_validate_class_reference "$label" "$class_reference"
  done
}

installer_validate_word_metadata() {
  label=$1
  words=$2
  for word_value in $words; do
    case "$word_value" in
      ''|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+._:-]*)
        installer_fatal "${label} contains unsupported token: ${word_value:-unset}"
        ;;
    esac
  done
}

installer_validate_class_manifest() {
  if [ "${INSTALLER_CLASS_MANIFEST_VALIDATED:-0}" -eq 1 ]; then
    return 0
  fi
  installer_classes_cache_ensure
  installer_ensure_classes_conf_path
  conf_path=$INSTALLER_CLASSES_CONF_PATH_CACHE
  manifest_version=$(installer_ini_get "$conf_path" manifest version 2>/dev/null || true)
  seen_groups=' '
  seen_purposes=' '
  seen_classes=' '
  group_count=0

  case "$manifest_version" in
    '') ;;
    *[!0-9]*) installer_fatal "classes/install.conf ManifestVersion must be numeric: ${manifest_version}" ;;
  esac

  while IFS= read -r group_name || [ -n "$group_name" ]; do
    [ -n "$group_name" ] || continue
    installer_validate_class_group_name "class group name" "$group_name"
    case "$seen_groups" in
      *" ${group_name} "*) installer_fatal "duplicate group record in classes/configs/groups.cfg: ${group_name}" ;;
    esac
    seen_groups="${seen_groups}${group_name} "
    group_count=$((group_count + 1))

    required_value=$(installer_ini_get "$conf_path" "group.${group_name}" required 2>/dev/null || true)
    case "$required_value" in
      ''|0|1|true|TRUE|false|FALSE|yes|YES|no|NO|on|ON|off|OFF|required|optional) ;;
      *) installer_fatal "group ${group_name} has invalid required value: ${required_value}" ;;
    esac

    multi_value=$(installer_ini_get "$conf_path" "group.${group_name}" multi 2>/dev/null || true)
    case "$multi_value" in
      ''|0|1|true|TRUE|false|FALSE|yes|YES|no|NO|on|ON|off|OFF|single|multi) ;;
      *) installer_fatal "group ${group_name} has invalid multi value: ${multi_value}" ;;
    esac

    source_value=$(installer_ini_get "$conf_path" "group.${group_name}" source 2>/dev/null || true)
    case "$source_value" in
      ''|class-auto|class-select|class-profile|class-addon|class-apps) ;;
      *) installer_fatal "group ${group_name} has invalid source value: ${source_value}" ;;
    esac

    order_value=$(installer_ini_get "$conf_path" "group.${group_name}" order 2>/dev/null || true)
    case "$order_value" in
      '') ;;
      *[!0-9]*) installer_fatal "group ${group_name} has invalid order value: ${order_value}" ;;
    esac

    group_purpose=$(installer_group_purpose "$group_name")
    if [ -n "$group_purpose" ]; then
      installer_validate_class_purpose "group ${group_name} purpose" "$group_purpose"
      case "$seen_purposes" in
        *" ${group_purpose} "*)
          installer_fatal "duplicate group purpose in classes/configs/groups.cfg: ${group_purpose}"
          ;;
      esac
      seen_purposes="${seen_purposes}${group_purpose} "
    fi
  done <<EOF
$(installer_group_names)
EOF

  [ "$group_count" -gt 0 ] || installer_fatal "classes/configs/groups.cfg must define at least one group record"

  while IFS= read -r class_record || [ -n "$class_record" ]; do
    [ -n "$class_record" ] || continue
    case "$class_record" in
      *.*) ;;
      *) installer_fatal "configured class record must use group.class shape, got: ${class_record}" ;;
    esac
    record_group_name=${class_record%%.*}
    record_class_name=${class_record#*.}
    installer_validate_class_group_name "class metadata group" "$record_group_name"
    installer_validate_class_name "class metadata name" "$record_class_name"
    case "$seen_groups" in
      *" ${record_group_name} "*) ;;
      *) installer_fatal "class ${record_group_name}/${record_class_name} references undefined class group ${record_group_name}" ;;
    esac
    case "$seen_classes" in
      *" ${record_group_name}/${record_class_name} "*)
        installer_fatal "duplicate class record in classes/configs/*.cfg: ${record_group_name}/${record_class_name}"
        ;;
    esac
    seen_classes="${seen_classes}${record_group_name}/${record_class_name} "

    installer_validate_helper_name "class ${record_group_name}/${record_class_name} early_helper" \
      "$(installer_class_meta_value "" "$record_group_name" "$record_class_name" early_helper)"
    installer_validate_helper_name "class ${record_group_name}/${record_class_name} partman_helper" \
      "$(installer_class_meta_value "" "$record_group_name" "$record_class_name" partman_helper)"
    installer_validate_helper_name "class ${record_group_name}/${record_class_name} late_helper" \
      "$(installer_class_meta_value "" "$record_group_name" "$record_class_name" late_helper)"
    helper_order_value=$(installer_class_meta_value "" "$record_group_name" "$record_class_name" late_helper_order)
    case "$helper_order_value" in
      ''|*[!0-9]*) [ -z "$helper_order_value" ] || installer_fatal "class ${record_group_name}/${record_class_name} late_helper_order must be numeric: ${helper_order_value}" ;;
    esac
    installer_validate_class_reference_list "class ${record_group_name}/${record_class_name} requires_classes" \
      "$(installer_class_meta_value "" "$record_group_name" "$record_class_name" requires_classes)"
    installer_validate_class_reference_list "class ${record_group_name}/${record_class_name} allowed_hardware_classes" \
      "$(installer_class_meta_value "" "$record_group_name" "$record_class_name" allowed_hardware_classes)"
    installer_validate_class_reference_list "class ${record_group_name}/${record_class_name} rejected_classes" \
      "$(installer_class_meta_value "" "$record_group_name" "$record_class_name" rejected_classes)"
    installer_normalize_apt_preferences_config \
      "$(installer_class_meta_value "" "$record_group_name" "$record_class_name" debian_apt_preferences)" \
      "class ${record_group_name}/${record_class_name} debian_apt_preferences" >/dev/null

    class_relpath=$(installer_class_source_path "$record_group_name" "$record_class_name")
    if [ -n "${INSTALLER_SOURCE_ROOT:-}" ] && [ ! -r "${INSTALLER_SOURCE_ROOT%/}/${class_relpath}" ]; then
      installer_fatal "class ${record_group_name}/${record_class_name} metadata references missing fragment: ${class_relpath}"
    fi
  done <<EOF
$(installer_configured_class_records)
EOF
  INSTALLER_CLASS_MANIFEST_VALIDATED=1
}

installer_group_for_purpose() {
  group_purpose=$1
  while IFS= read -r group_name || [ -n "$group_name" ]; do
    [ -n "$group_name" ] || continue
    [ "$(installer_group_purpose "$group_name")" = "$group_purpose" ] || continue
    printf '%s\n' "$group_name"
    return 0
  done <<EOF
$(installer_group_names)
EOF
}

installer_auto_group_from_token() {
  token=$1
  installer_class_token_parts "$token" >/dev/null
  token_group=${INSTALLER_CLASS_TOKEN_GROUP:-}
  token_name=$INSTALLER_CLASS_TOKEN_NAME

  case "$token_group" in
    arch|cpu|gpu|disk)
      printf '%s\n' "$token_group"
      return 0
      ;;
  esac

  case "$token_name" in
    amd64|arm64) printf '%s\n' arch ;;
    amd|intel|generic-arm64) printf '%s\n' cpu ;;
    amd-radeon|generic|intel-uhd) printf '%s\n' gpu ;;
    emmc|nvme|vm) printf '%s\n' disk ;;
    *) return 1 ;;
  esac
}

installer_word_list_contains() {
  words=$1
  needle=$2
  case " ${words} " in
    *" ${needle} "*) return 0 ;;
  esac
  return 1
}

