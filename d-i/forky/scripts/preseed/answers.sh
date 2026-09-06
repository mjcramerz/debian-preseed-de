#!/bin/sh
set -eu

RUNTIME_DIR=${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}
BOOTSTRAP_LIB=${INSTALLER_BOOTSTRAP_LIB:-${RUNTIME_DIR}/bootstrap/bootstrap.sh}
if [ ! -s "$BOOTSTRAP_LIB" ]; then
  SELF_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
  BOOTSTRAP_LIB="${SELF_DIR}/../common/bootstrap.sh"
fi
[ -s "$BOOTSTRAP_LIB" ] || {
  echo "fatal: installer bootstrap library is unavailable: ${BOOTSTRAP_LIB}" >&2
  exit 1
}
# shellcheck disable=SC1090,SC1091
. "$BOOTSTRAP_LIB"
bootstrap_source_common_lib "${2:-}"
installer_init_stderr_log_file "$(installer_runtime_log_file)" "" "preseed answers (${1:-unset})" preseed-answers preseed_loaded
trap 'installer_finalize_log "$?"' EXIT

preseed_parse_selection_fields() {
  selection_line=$1

  case $- in
    *f*) preseed_glob_was_disabled=true ;;
    *) preseed_glob_was_disabled=false ;;
  esac
  set -f
  # shellcheck disable=SC2086
  set -- $selection_line
  if [ "$preseed_glob_was_disabled" = false ]; then
    set +f
  fi
  [ "$#" -gt 0 ] || return 1
  case "$1" in
    '#'*)
      return 1
      ;;
  esac
  [ "$#" -ge 3 ] || return 2

  PRESEED_RECORD_OWNER=$1
  PRESEED_RECORD_QUESTION=$2
  PRESEED_RECORD_TYPE=$3
  if [ "$#" -gt 3 ]; then
    shift 3
    PRESEED_RECORD_VALUE=$*
  else
    PRESEED_RECORD_VALUE=
  fi
  return 0
}

append_debconf_communicate_commands() {
  selection_line=$1
  command_file=$2

  if preseed_parse_selection_fields "$selection_line"; then
    :
  else
    parse_status=$?
    [ "$parse_status" -eq 1 ] && return 1
    installer_fatal "malformed preseed answer record; expected owner question type [value]"
  fi

  case "$PRESEED_RECORD_TYPE" in
    seen)
      case "$PRESEED_RECORD_VALUE" in
        true|false) ;;
        *)
          installer_fatal "invalid debconf seen value for ${PRESEED_RECORD_QUESTION}: ${PRESEED_RECORD_VALUE:-empty}"
          ;;
      esac
      printf 'FSET %s seen %s\n' "$PRESEED_RECORD_QUESTION" "$PRESEED_RECORD_VALUE" >>"$command_file"
      ;;
    *)
      printf 'SET %s %s\n' "$PRESEED_RECORD_QUESTION" "$PRESEED_RECORD_VALUE" >>"$command_file"
      printf 'FSET %s seen true\n' "$PRESEED_RECORD_QUESTION" >>"$command_file"
      ;;
  esac
  return 0
}

apply_answers_file() {
  path=$1
  debconf_err_file=
  [ -r "$path" ] || installer_fatal "answer file is not readable: ${path}"
  if command -v debconf-set-selections >/dev/null 2>&1; then
    debconf_err_file="$(installer_runtime_log_dir)/debconf-set-selections.err"
    debconf-set-selections "$path" 2>"$debconf_err_file" || {
      debconf_status=$?
      installer_error "debconf-set-selections failed with status ${debconf_status} for ${path}"
      if [ -s "$debconf_err_file" ]; then
        sed 's/^/[debconf-set-selections] /' "$debconf_err_file" >&2 || true
      fi
      if debconf-set-selections -c "$path" 2>"$debconf_err_file"; then
        installer_error "debconf-set-selections --checkonly succeeded for ${path}; runtime apply failed after syntax validation"
      else
        debconf_check_status=$?
        installer_error "debconf-set-selections --checkonly failed with status ${debconf_check_status} for ${path}"
        if [ -s "$debconf_err_file" ]; then
          sed 's/^/[debconf-set-selections:checkonly] /' "$debconf_err_file" >&2 || true
        fi
      fi
      rm -f "$debconf_err_file"
      return "$debconf_status"
    }
    rm -f "$debconf_err_file"
    return 0
  fi
  command -v debconf-communicate >/dev/null 2>&1 || {
    installer_fatal "neither debconf-set-selections nor debconf-communicate is available to apply ${path}"
  }

  temp_log_dir=$(installer_runtime_temp_log_dir)
  install -d -m 0700 "$temp_log_dir"
  debconf_cmd_file="${temp_log_dir}/debconf-communicate.$$.commands"
  debconf_out_file="${temp_log_dir}/debconf-communicate.$$.out"
  rm -f "$debconf_cmd_file" "$debconf_out_file"
  : >"$debconf_cmd_file"
  chmod 0600 "$debconf_cmd_file" 2>/dev/null || true

  answer_count=0
  skipped_count=0
  logical_line=
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      *\\)
        line=${line%\\}
        logical_line="${logical_line:+$logical_line }$line"
        continue
        ;;
      *)
        logical_line="${logical_line:+$logical_line }$line"
        ;;
    esac
    if append_debconf_communicate_commands "$logical_line" "$debconf_cmd_file"; then
      answer_count=$((answer_count + 1))
    else
      skipped_count=$((skipped_count + 1))
    fi
    logical_line=
  done <"$path"

  if [ -n "$logical_line" ]; then
    if append_debconf_communicate_commands "$logical_line" "$debconf_cmd_file"; then
      answer_count=$((answer_count + 1))
    else
      skipped_count=$((skipped_count + 1))
    fi
  fi

  installer_info "applying ${answer_count} preseed answer records through debconf-communicate fallback; skipped=${skipped_count}"
  if [ "$answer_count" -eq 0 ]; then
    rm -f "$debconf_cmd_file" "$debconf_out_file"
    return 0
  fi
  if debconf-communicate <"$debconf_cmd_file" >"$debconf_out_file" 2>&1; then
    debconf_status=0
  else
    debconf_status=$?
  fi
  if [ "$debconf_status" -ne 0 ] || grep -E -q '^[1-9][0-9]*[[:space:]]' "$debconf_out_file" 2>/dev/null; then
    installer_error "debconf-communicate fallback failed while applying ${path} (status ${debconf_status})"
    if [ -s "$debconf_out_file" ]; then
      installer_redact_log_stream <"$debconf_out_file" | sed 's/^/[debconf-communicate] /' >&2 || true
    fi
    rm -f "$debconf_cmd_file" "$debconf_out_file"
    return 1
  fi
  rm -f "$debconf_cmd_file" "$debconf_out_file"
}

append_unique_words() {
  var_name=$1
  shift
  eval "current_words=\${$var_name:-}"
  for word in "$@"; do
    [ -n "$word" ] || continue
    case " ${current_words} " in
      *" ${word} "*) ;;
      *) current_words="${current_words:+$current_words }${word}" ;;
    esac
  done
  eval "$var_name=\$current_words"
}

append_unique_word_list() {
  var_name=$1
  list_words=$2
  for word in $list_words; do
    append_unique_words "$var_name" "$word"
  done
}

preseed_fragment_cache_token() {
  printf '%s' "$1" | tr '/.' '__'
}

preseed_fragment_cache_path() {
  rel_path=$1
  cache_token=$(preseed_fragment_cache_token "$rel_path")

  case "$rel_path" in
    classes/*) printf '%s/classes/%s\n' "$CACHE_DIR" "$cache_token" ;;
    *) printf '%s/%s\n' "$CACHE_DIR" "$cache_token" ;;
  esac
}

ensure_cached_preseed_fragment() {
  rel_path=$1
  cached_path=$(preseed_fragment_cache_path "$rel_path")

  if [ ! -s "$cached_path" ]; then
    installer_fetch_file "$seed_base" "$rel_path" "$cached_path" 0600
  fi
  printf '%s\n' "$cached_path"
}

validate_single_line_token() {
  label=$1
  value=$2
  case "$value" in
    ''|*[![:print:]]*|*[[:space:]]*)
      installer_fatal "${label} must be a single printable token"
      ;;
  esac
}

validate_hostname_component() {
  label=$1
  value=$2
  case "$value" in
    ''|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.-]*|.*|*.|*..*)
      installer_fatal "${label} must contain only hostname-safe labels"
      ;;
  esac
}

validate_word_list() {
  label=$1
  value=$2
  count=0

  for word in $value; do
    validate_single_line_token "${label} entry" "$word"
    count=$((count + 1))
  done

  [ "$count" -ge 1 ] || installer_fatal "${label} must contain at least one token"
}

answer_value() {
  for answer_key in "$@"; do
    value=$(installer_cmdline_value "$answer_key" 2>/dev/null || true)
    if [ -n "$value" ]; then
      printf '%s\n' "$value"
      return 0
    fi
  done

  for answer_key in "$@"; do
    value=$(installer_debconf_value "$answer_key" 2>/dev/null || true)
    if [ -n "$value" ]; then
      printf '%s\n' "$value"
      return 0
    fi
  done

  return 1
}

preseed_record_value_from_file() {
  path=$1
  question=$2
  type=$3
  value=

  [ -r "$path" ] || installer_fatal "preseed fragment is not readable while extracting ${question}: ${path}"

  logical=
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      *\\)
        line=${line%\\}
        logical="${logical:+$logical }$line"
        continue
        ;;
      *)
        logical="${logical:+$logical }$line"
        ;;
    esac
    if preseed_parse_selection_fields "$logical"; then
      if [ "$PRESEED_RECORD_QUESTION" = "$question" ] && [ "$PRESEED_RECORD_TYPE" = "$type" ]; then
        value=$PRESEED_RECORD_VALUE
      fi
    else
      parse_status=$?
      [ "$parse_status" -eq 1 ] || installer_fatal "malformed preseed fragment record while extracting ${question}"
    fi
    logical=
  done <"$path"

  if [ -n "$logical" ]; then
    if preseed_parse_selection_fields "$logical"; then
      if [ "$PRESEED_RECORD_QUESTION" = "$question" ] && [ "$PRESEED_RECORD_TYPE" = "$type" ]; then
        value=$PRESEED_RECORD_VALUE
      fi
    else
      parse_status=$?
      [ "$parse_status" -eq 1 ] || installer_fatal "malformed trailing preseed fragment record while extracting ${question}"
    fi
  fi

  [ -n "$value" ] || return 1
  printf '%s\n' "$value"
}

append_preseed_record_from_file() {
  output_file=$1
  source_file=$2
  question=$3
  type=$4

  value=$(preseed_record_value_from_file "$source_file" "$question" "$type" 2>/dev/null || true)
  [ -n "$value" ] || return 0
  printf 'd-i %s %s %s\n' "$question" "$type" "$value" >>"$output_file"
}

append_preseed_record_with_fallback() {
  output_file=$1
  question=$2
  type=$3
  shift 3

  for source_file in "$@"; do
    [ -n "$source_file" ] || continue
    value=$(preseed_record_value_from_file "$source_file" "$question" "$type" 2>/dev/null || true)
    [ -n "$value" ] || continue
    printf 'd-i %s %s %s\n' "$question" "$type" "$value" >>"$output_file"
    return 0
  done

  return 0
}

append_seen_true_record() {
  output_file=$1
  question=$2

  printf 'd-i %s seen true\n' "$question" >>"$output_file"
}

append_runtime_baseline_answers() {
  output_file=$1
  merged_file=$2
  common_cfg=$(ensure_cached_preseed_fragment "common.cfg")
  apt_cfg=$(ensure_cached_preseed_fragment "fragments/apt.cfg")
  finish_cfg=$(ensure_cached_preseed_fragment "fragments/finish.cfg")

  append_preseed_record_from_file "$output_file" "$apt_cfg" "debian-installer/allow_unauthenticated" boolean
  append_preseed_record_from_file "$output_file" "$apt_cfg" "debian-installer/allow_unauthenticated_ssl" boolean
  append_preseed_record_with_fallback "$output_file" "mirror/country" string "$merged_file" "$apt_cfg"
  append_preseed_record_with_fallback "$output_file" "mirror/protocol" select "$merged_file" "$apt_cfg"
  append_preseed_record_with_fallback "$output_file" "mirror/codename" string "$merged_file" "$apt_cfg"
  append_preseed_record_with_fallback "$output_file" "mirror/suite" string "$merged_file" "$apt_cfg"
  append_preseed_record_with_fallback "$output_file" "mirror/udeb/suite" string "$merged_file" "$apt_cfg"
  append_preseed_record_with_fallback "$output_file" "mirror/http/hostname" string "$merged_file" "$apt_cfg"
  append_preseed_record_with_fallback "$output_file" "mirror/http/directory" string "$merged_file" "$apt_cfg"
  append_preseed_record_with_fallback "$output_file" "mirror/http/proxy" string "$merged_file" "$apt_cfg"
  append_preseed_record_with_fallback "$output_file" "mirror/https/countries" select "$merged_file" "$apt_cfg"
  append_preseed_record_with_fallback "$output_file" "mirror/https/hostname" string "$merged_file" "$apt_cfg"
  append_preseed_record_with_fallback "$output_file" "mirror/https/mirror" select "$merged_file" "$apt_cfg"
  append_preseed_record_with_fallback "$output_file" "mirror/https/directory" string "$merged_file" "$apt_cfg"
  append_preseed_record_with_fallback "$output_file" "mirror/https/proxy" string "$merged_file" "$apt_cfg"
  append_seen_true_record "$output_file" "mirror/country"
  append_seen_true_record "$output_file" "mirror/protocol"
  append_seen_true_record "$output_file" "mirror/codename"
  append_seen_true_record "$output_file" "mirror/suite"
  append_seen_true_record "$output_file" "mirror/udeb/suite"
  append_seen_true_record "$output_file" "mirror/http/hostname"
  append_seen_true_record "$output_file" "mirror/http/directory"
  append_seen_true_record "$output_file" "mirror/http/proxy"
  append_seen_true_record "$output_file" "mirror/https/countries"
  append_seen_true_record "$output_file" "mirror/https/hostname"
  append_seen_true_record "$output_file" "mirror/https/mirror"
  append_seen_true_record "$output_file" "mirror/https/directory"
  append_seen_true_record "$output_file" "mirror/https/proxy"
  append_preseed_record_with_fallback "$output_file" "apt-setup/use_mirror" boolean "$merged_file" "$apt_cfg"
  append_preseed_record_with_fallback "$output_file" "apt-setup/cdrom/set-first" boolean "$merged_file" "$apt_cfg"
  append_preseed_record_with_fallback "$output_file" "apt-setup/disable-cdrom-entries" boolean "$merged_file" "$apt_cfg"
  append_preseed_record_with_fallback "$output_file" "apt-setup/no_mirror" boolean "$merged_file" "$apt_cfg"
  append_preseed_record_with_fallback "$output_file" "apt-setup/services-select" multiselect "$merged_file" "$apt_cfg"
  append_preseed_record_with_fallback "$output_file" "apt-setup/security_host" string "$merged_file" "$apt_cfg"
  append_preseed_record_with_fallback "$output_file" "apt-setup/security_path" string "$merged_file" "$apt_cfg"
  append_preseed_record_with_fallback "$output_file" "apt-setup/non-free" boolean "$merged_file" "$apt_cfg"
  append_preseed_record_with_fallback "$output_file" "apt-setup/contrib" boolean "$merged_file" "$apt_cfg"
  append_preseed_record_with_fallback "$output_file" "apt-setup/non-free-firmware" boolean "$merged_file" "$apt_cfg"
  append_preseed_record_with_fallback "$output_file" "apt-setup/backports" boolean "$merged_file" "$apt_cfg"
  append_preseed_record_with_fallback "$output_file" "pkgsel/upgrade" select "$merged_file" "$apt_cfg"
  append_preseed_record_with_fallback "$output_file" "pkgsel/update-policy" select "$merged_file" "$apt_cfg"
  append_preseed_record_from_file "$output_file" "$common_cfg" "debian-installer/language" string
  append_preseed_record_from_file "$output_file" "$common_cfg" "debian-installer/country" string
  append_preseed_record_from_file "$output_file" "$common_cfg" "debian-installer/locale" string
  append_preseed_record_from_file "$output_file" "$common_cfg" "debian-installer/language" seen
  append_preseed_record_from_file "$output_file" "$common_cfg" "debian-installer/country" seen
  append_preseed_record_from_file "$output_file" "$common_cfg" "debian-installer/locale" seen
  append_preseed_record_from_file "$output_file" "$common_cfg" "localechooser/languagelist" select
  append_preseed_record_from_file "$output_file" "$common_cfg" "localechooser/languagelist" seen
  append_preseed_record_from_file "$output_file" "$common_cfg" "localechooser/countrylist/Europe" select
  append_preseed_record_from_file "$output_file" "$common_cfg" "localechooser/countrylist/Europe" seen
  append_preseed_record_from_file "$output_file" "$common_cfg" "localechooser/shortlist/sv" select
  append_preseed_record_from_file "$output_file" "$common_cfg" "localechooser/shortlist/sv" seen
  append_preseed_record_from_file "$output_file" "$common_cfg" "localechooser/preferred-locale" select
  append_preseed_record_from_file "$output_file" "$common_cfg" "localechooser/preferred-locale" seen
  append_preseed_record_from_file "$output_file" "$common_cfg" "localechooser/supported-locales" multiselect
  append_preseed_record_from_file "$output_file" "$common_cfg" "localechooser/supported-locales" seen
  append_preseed_record_from_file "$output_file" "$common_cfg" "localechooser/translation/warn-light" boolean
  append_preseed_record_from_file "$output_file" "$common_cfg" "localechooser/translation/warn-light" seen
  append_preseed_record_from_file "$output_file" "$common_cfg" "localechooser/translation/warn-severe" boolean
  append_preseed_record_from_file "$output_file" "$common_cfg" "localechooser/translation/warn-severe" seen
  # Clock and timezone answers are owned by the initial preseed. Reapplying
  # them through the dynamic debconf answer set can disturb the stock
  # finish-install clock state after clock-setup has already completed.
  append_preseed_record_from_file "$output_file" "$finish_cfg" "debian-installer/exit/reboot" boolean
  append_preseed_record_from_file "$output_file" "$finish_cfg" "debian-installer/exit/reboot" seen
  append_preseed_record_from_file "$output_file" "$finish_cfg" "debian-installer/exit/halt" boolean
  append_preseed_record_from_file "$output_file" "$finish_cfg" "debian-installer/exit/halt" seen
  append_preseed_record_from_file "$output_file" "$finish_cfg" "debian-installer/exit/poweroff" boolean
  append_preseed_record_from_file "$output_file" "$finish_cfg" "debian-installer/exit/poweroff" seen
  append_preseed_record_from_file "$output_file" "$finish_cfg" "finish-install/keep-consoles" boolean
  append_preseed_record_from_file "$output_file" "$finish_cfg" "finish-install/keep-consoles" seen
  if grep -Fxq 'd-i finish-install/reboot_in_progress note' "$finish_cfg"; then
    printf 'd-i finish-install/reboot_in_progress note\n' >>"$output_file"
  fi
  append_preseed_record_from_file "$output_file" "$finish_cfg" "grub-installer/bootdev" string
  append_preseed_record_from_file "$output_file" "$finish_cfg" "grub-installer/bootdev" seen
}

validate_ipv4_address() {
  label=$1
  value=$2
  old_ifs=$IFS

  case "$value" in
    ''|*[!0123456789.]*|.*|*.|*..*)
      installer_fatal "${label} must be an IPv4 dotted-quad address"
      ;;
  esac

  IFS=.
  # shellcheck disable=SC2086
  set -- $value
  IFS=$old_ifs

  [ "$#" -eq 4 ] || installer_fatal "${label} must contain four IPv4 octets"
  for octet in "$@"; do
    case "$octet" in
      ''|*[!0123456789]*|????*)
        installer_fatal "${label} contains an invalid IPv4 octet"
        ;;
    esac
    [ "$octet" -le 255 ] || installer_fatal "${label} octet is outside 0-255"
  done
}

validate_ipv4_address_list() {
  label=$1
  value=$2
  count=0

  case "$value" in
    *','*) installer_fatal "${label} must use spaces between IPv4 addresses, not commas" ;;
  esac

  for address in $value; do
    count=$((count + 1))
    validate_ipv4_address "${label} entry" "$address"
  done

  [ "$count" -ge 1 ] || installer_fatal "${label} must contain at least one IPv4 address"
  [ "$count" -le 3 ] || installer_fatal "${label} must contain no more than three IPv4 addresses"
}

validate_wifi_essid() {
  label=$1
  value=$2

  validate_single_line_token "$label" "$value"
  [ "${#value}" -le 32 ] || installer_fatal "${label} must be 32 characters or shorter"
}

validate_wifi_security_type() {
  label=$1
  value=$2

  [ "$value" = wpa ] || installer_fatal "${label} must be 'wpa'"
}

validate_wifi_wpa() {
  label=$1
  value=$2
  length=${#value}

  validate_single_line_token "$label" "$value"
  if [ "$length" -ge 8 ] && [ "$length" -le 63 ]; then
    return 0
  fi
  case "$value" in
    *[!0123456789ABCDEFabcdef]*)
      installer_fatal "${label} must be 8-63 printable characters or a 64-character hexadecimal PSK"
      ;;
  esac
  [ "$length" -eq 64 ] || installer_fatal "${label} must be 8-63 printable characters or a 64-character hexadecimal PSK"
}

selected_wifi_addon() {
  installer_selected_class_reference_is_selected addon/wifi 2>/dev/null
}

selected_dualboot_addon() {
  installer_selected_class_reference_is_selected addon/dualboot 2>/dev/null
}

validate_positive_integer() {
  label=$1
  value=$2
  case "$value" in
    ''|*[!0123456789]*)
      installer_fatal "${label} must be a positive integer"
      ;;
    0)
      installer_fatal "${label} must be greater than zero"
      ;;
  esac
}

validate_dualboot_cmdline_contract() {
  dualboot_efi_value=$(installer_cmdline_value dualboot_efi 2>/dev/null || true)
  dualboot_debian_value=$(installer_cmdline_value dualboot_debian 2>/dev/null || true)

  if [ "$DUALBOOT_ENABLED" = true ]; then
    [ -n "$dualboot_efi_value" ] || installer_fatal "classes=...,dualboot requires dualboot_efi=<integer> on the kernel cmdline"
    [ -n "$dualboot_debian_value" ] || installer_fatal "classes=...,dualboot requires dualboot_debian=<integer> on the kernel cmdline"
    validate_positive_integer dualboot_efi "$dualboot_efi_value"
    validate_positive_integer dualboot_debian "$dualboot_debian_value"
    [ "$dualboot_efi_value" -lt "$dualboot_debian_value" ] || installer_fatal "dualboot_efi must be lower than dualboot_debian"
  elif [ -n "$dualboot_efi_value" ] || [ -n "$dualboot_debian_value" ]; then
    installer_fatal "dualboot_efi and dualboot_debian require classes=...,dualboot"
  fi
}

static_network_requested() {
  [ "$NETWORK_MODE" = static ]
}

read_network_domain_answer() {
  domain_value=$(answer_value netcfg/get_domain domain 2>/dev/null || true)
  [ -n "$domain_value" ] || return 0
  validate_hostname_component "netcfg/get_domain" "$domain_value"
  SYSTEM_DOMAIN=$domain_value
}

read_static_network_answers() {
  static_network_requested || return 0

  STATIC_IP_ADDRESS=$(answer_value netcfg/get_ipaddress ip 2>/dev/null || true)
  STATIC_NETMASK=$(answer_value netcfg/get_netmask netmask 2>/dev/null || true)
  STATIC_GATEWAY=$(answer_value netcfg/get_gateway gateway 2>/dev/null || true)
  STATIC_NAMESERVERS=$(answer_value netcfg/get_nameservers nameservers dns 2>/dev/null || true)
  if [ -z "$STATIC_NAMESERVERS" ]; then
    STATIC_NAMESERVERS=${STATIC_GATEWAY:-${STATIC_NAMESERVERS_DEFAULT:-}}
  fi
}

read_wifi_answers() {
  :
}

validate_static_network_answers() {
  static_network_requested || return 0

  validate_ipv4_address STATIC_IP_ADDRESS "$STATIC_IP_ADDRESS"
  validate_ipv4_address STATIC_NETMASK "$STATIC_NETMASK"
  validate_ipv4_address STATIC_GATEWAY "$STATIC_GATEWAY"
  if [ -n "$STATIC_NAMESERVERS" ]; then
    validate_ipv4_address_list STATIC_NAMESERVERS "$STATIC_NAMESERVERS"
  fi
}

validate_wifi_answers() {
  :
}

write_wifi_answers() {
  :
}

write_static_network_answers() {
  static_network_requested || return 0

  printf 'd-i netcfg/use_autoconfig boolean false\n'
  printf 'd-i netcfg/use_autoconfig seen true\n'
  printf 'd-i netcfg/disable_autoconfig boolean true\n'
  printf 'd-i netcfg/disable_autoconfig seen true\n'
  printf 'd-i netcfg/disable_dhcp boolean true\n'
  printf 'd-i netcfg/disable_dhcp seen true\n'
  printf 'd-i netcfg/dhcp_options select Configure network manually\n'
  printf 'd-i netcfg/dhcp_options seen true\n'
  printf 'd-i netcfg/get_ipaddress string %s\n' "$STATIC_IP_ADDRESS"
  printf 'd-i netcfg/get_ipaddress seen true\n'
  printf 'd-i netcfg/get_netmask string %s\n' "$STATIC_NETMASK"
  printf 'd-i netcfg/get_netmask seen true\n'
  printf 'd-i netcfg/get_gateway string %s\n' "$STATIC_GATEWAY"
  printf 'd-i netcfg/get_gateway seen true\n'
  if [ -n "$STATIC_NAMESERVERS" ]; then
    printf 'd-i netcfg/get_nameservers string %s\n' "$STATIC_NAMESERVERS"
    printf 'd-i netcfg/get_nameservers seen true\n'
  fi
  printf 'd-i netcfg/confirm_static boolean true\n'
  printf 'd-i netcfg/confirm_static seen true\n'
}

write_include_list() {
  include_file=$1
  install -d -m 0700 "$(dirname "$include_file")"
  installer_selected_class_paths | sed '/^[[:space:]]*$/d' | awk '!seen[$0]++' >"$include_file"
  chmod 0600 "$include_file"
}

selected_fragment_applies_to_detected_hardware() {
  rel_path=$1
  nvidia_fragment=classes/class-addon/nvidia.cfg
  cuda_fragment=classes/class-addon/cuda.cfg
  nvidia_legacy_fragment=classes/class-addon/nvidia-legacy.cfg
  cuda_legacy_fragment=classes/class-addon/cuda-legacy.cfg

  case "$rel_path" in
    "$cuda_legacy_fragment")
      # Selection explicitly requests the compiler/userspace stack, including
      # on a headless build host or when installer PCI detection is unavailable.
      return 0
      ;;
    "$nvidia_fragment"|"$cuda_fragment"|"$nvidia_legacy_fragment")
      installer_nvidia_gpu_detected
      ;;
    *)
      return 0
      ;;
  esac
}

selected_arch_class() {
  if [ -n "${PRESEED_SELECTED_ARCH_CLASS:-}" ]; then
    printf '%s\n' "$PRESEED_SELECTED_ARCH_CLASS"
    return 0
  fi

  PRESEED_SELECTED_ARCH_CLASS=${INSTALLER_ARCH_CLASS:-$(installer_selected_class_for_purpose arch 2>/dev/null || true)}
  [ -n "$PRESEED_SELECTED_ARCH_CLASS" ] ||
    installer_fatal "selected arch class is unavailable while resolving pkgsel/include"
  printf '%s\n' "$PRESEED_SELECTED_ARCH_CLASS"
}

pkgsel_include_word_supported_for_selected_arch() {
  package_word=$1
  package_name=${package_word%%/*}
  arch_class=$(selected_arch_class)

  case "$package_name" in
    microsoft-edge-stable)
      [ "$arch_class" = amd64 ]
      ;;
    *)
      return 0
      ;;
  esac
}

append_filtered_pkgsel_include_word_list() {
  list_words=$1
  skipped_words=
  skipped_arch=

  for word in $list_words; do
    [ -n "$word" ] || continue
    if pkgsel_include_word_supported_for_selected_arch "$word"; then
      append_unique_words PKGSEL_INCLUDE "$word"
    else
      skipped_words="${skipped_words:+$skipped_words }${word}"
      [ -n "$skipped_arch" ] || skipped_arch=$(selected_arch_class)
    fi
  done

  [ -z "$skipped_words" ] ||
    installer_info "skipping arch-incompatible pkgsel/include packages for ${skipped_arch}: ${skipped_words}"
}

append_debconf_word_list() {
  question=$1
  var_name=$2
  value=$(installer_debconf_value "$question" || true)

  [ -n "$value" ] || return 0
  append_unique_word_list "$var_name" "$value"
}

secure_boot_boot_chain_packages_for_selected_arch() {
  arch_class=${INSTALLER_ARCH_CLASS:-$(installer_selected_class_for_purpose arch 2>/dev/null || true)}

  case "$arch_class" in
    amd64)
      printf '%s\n' "grub-efi-amd64 grub-efi-amd64-signed shim-signed shim-helpers-amd64-signed"
      ;;
    arm64)
      printf '%s\n' "grub-efi-arm64 grub-efi-arm64-signed shim-signed shim-helpers-arm64-signed"
      ;;
    *)
      installer_fatal "unsupported arch class for Secure Boot packages: ${arch_class:-unset}"
      ;;
  esac
}

parse_preseed_record() {
  line=$1

  if preseed_parse_selection_fields "$line"; then
    owner=$PRESEED_RECORD_OWNER
    question=$PRESEED_RECORD_QUESTION
    value_type=$PRESEED_RECORD_TYPE
    value=$PRESEED_RECORD_VALUE
  else
    parse_status=$?
    [ "$parse_status" -eq 1 ] && return 0
    installer_fatal "malformed preseed fragment record; expected owner question type [value]"
  fi

  case "$owner:$question:$value_type" in
    d-i:pkgsel/include:string)
      append_filtered_pkgsel_include_word_list "$value"
      ;;
    d-i:anna/choose_modules:multiselect)
      append_unique_word_list ANNA_CHOOSE_MODULES "$value"
      ;;
    tasksel:*)
      installer_fatal "tasksel is disabled; class fragments must not define ${question}"
      ;;
  esac
}

parse_preseed_fragment() {
  path=$1
  logical_line=
  [ -r "$path" ] || installer_fatal "preseed fragment is not readable: ${path}"

  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      *\\)
        line=${line%\\}
        logical_line="${logical_line:+$logical_line }$line"
        continue
        ;;
      *)
        logical_line="${logical_line:+$logical_line }$line"
        parse_preseed_record "$logical_line"
        logical_line=
        ;;
    esac
  done <"$path"

  [ -z "$logical_line" ] || parse_preseed_record "$logical_line"
}

append_fragment_apt_setup_local_records() {
  path=$1
  records_file=$2
  source_order=$3
  logical_line=

  [ -r "$path" ] || installer_fatal "preseed fragment is not readable for apt-setup/local extraction: ${path}"

  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      *\\)
        line=${line%\\}
        logical_line="${logical_line:+$logical_line }$line"
        continue
        ;;
      *)
        logical_line="${logical_line:+$logical_line }$line"
        ;;
    esac

    if preseed_parse_selection_fields "$logical_line"; then
      case "$PRESEED_RECORD_OWNER:$PRESEED_RECORD_QUESTION" in
        d-i:apt-setup/local*/*)
          local_field=${PRESEED_RECORD_QUESTION#apt-setup/local}
          local_slot=${local_field%%/*}
          local_name=${local_field#*/}
          case "$local_slot" in
            ''|*[!0-9]*) installer_fatal "unsupported apt-setup/local slot in preseed fragment: ${PRESEED_RECORD_QUESTION}" ;;
          esac
          local_ordered_slot=$((source_order * 1000 + local_slot))
          [ -n "$local_name" ] ||
            installer_fatal "missing apt-setup/local field name in preseed fragment: ${PRESEED_RECORD_QUESTION}"
          printf '%s\t%s\t%s\t%s\n' \
            "$local_ordered_slot" \
            "$local_name" \
            "$PRESEED_RECORD_TYPE" \
            "$PRESEED_RECORD_VALUE" >>"$records_file"
          ;;
      esac
    else
      parse_status=$?
      [ "$parse_status" -eq 1 ] || installer_fatal "malformed preseed fragment record while extracting apt-setup/local answers"
    fi

    logical_line=
  done <"$path"

  if [ -n "$logical_line" ]; then
    if preseed_parse_selection_fields "$logical_line"; then
      case "$PRESEED_RECORD_OWNER:$PRESEED_RECORD_QUESTION" in
        d-i:apt-setup/local*/*)
          local_field=${PRESEED_RECORD_QUESTION#apt-setup/local}
          local_slot=${local_field%%/*}
          local_name=${local_field#*/}
          case "$local_slot" in
            ''|*[!0-9]*) installer_fatal "unsupported trailing apt-setup/local slot in preseed fragment: ${PRESEED_RECORD_QUESTION}" ;;
          esac
          local_ordered_slot=$((source_order * 1000 + local_slot))
          [ -n "$local_name" ] ||
            installer_fatal "missing trailing apt-setup/local field name in preseed fragment: ${PRESEED_RECORD_QUESTION}"
          printf '%s\t%s\t%s\t%s\n' \
            "$local_ordered_slot" \
            "$local_name" \
            "$PRESEED_RECORD_TYPE" \
            "$PRESEED_RECORD_VALUE" >>"$records_file"
          ;;
      esac
    else
      parse_status=$?
      [ "$parse_status" -eq 1 ] || installer_fatal "malformed trailing preseed fragment record while extracting apt-setup/local answers"
    fi
  fi
}

collect_apt_setup_local_records() {
  records_file=$1
  base_fragment=$(ensure_cached_preseed_fragment "fragments/apt.cfg")
  source_order=0

  : >"$records_file"
  append_fragment_apt_setup_local_records "$base_fragment" "$records_file" "$source_order"
  while IFS= read -r rel_path || [ -n "$rel_path" ]; do
    [ -n "$rel_path" ] || continue
    selected_fragment_applies_to_detected_hardware "$rel_path" || continue
    if [ "$rel_path" = "classes/class-addon/cuda-legacy.cfg" ]; then
      installer_info "skipping apt-setup/local answers from ${rel_path}; legacy CUDA repository is managed through staged hooks"
      continue
    fi
    cached_path=$(ensure_cached_preseed_fragment "$rel_path")
    source_order=$((source_order + 1))
    append_fragment_apt_setup_local_records "$cached_path" "$records_file" "$source_order"
  done <"$INCLUDE_LIST_FILE"
  chmod 0600 "$records_file"
}

write_compacted_apt_setup_local_answers() {
  output_file=$1
  records_file="${CACHE_DIR}/preseed.apt-setup-local.tsv"
  compacted_file="${CACHE_DIR}/preseed.apt-setup-local.cfg"

  collect_apt_setup_local_records "$records_file"
  [ -s "$records_file" ] || return 0

  awk -F '\t' '
    {
      slot = $1 + 0
      if (slot > max_slot) {
        max_slot = slot
      }
      field = $2
      type = $3
      value = ""
      if (NF > 3) {
        value = $4
        for (i = 5; i <= NF; i++) {
          value = value FS $i
        }
      }
      slot_seen[slot] = 1
      key = slot SUBSEP field
      if (!(key in field_seen)) {
        fields[slot] = fields[slot] (fields[slot] == "" ? "" : "\034") field
        field_seen[key] = 1
      }
      types[key] = type
      values[key] = value
    }
    END {
      next_slot = 0
      for (slot = 0; slot <= max_slot; slot++) {
        if (!(slot in slot_seen)) {
          continue
        }
        repo_key = slot SUBSEP "repository"
        if (!(repo_key in types)) {
          printf("fatal: merged apt-setup/local%d is missing a repository field\n", slot) > "/dev/stderr"
          exit 1
        }
        field_count = split(fields[slot], ordered_fields, /\034/)
        for (field_index = 1; field_index <= field_count; field_index++) {
          field = ordered_fields[field_index]
          key = slot SUBSEP field
          printf("d-i apt-setup/local%d/%s %s", next_slot, field, types[key])
          if (length(values[key]) > 0) {
            printf(" %s", values[key])
          }
          printf("\n")
        }
        next_slot++
      }
    }
  ' "$records_file" >"$compacted_file"
  [ -s "$compacted_file" ] || return 0
  cat "$compacted_file" >>"$output_file"
  printf '\n' >>"$output_file"
}

word_list_contains() {
  words=$1
  needle=$2

  case " ${words} " in
    *" ${needle} "*) return 0 ;;
  esac
  return 1
}

validate_policy_subset() {
  label=$1
  subset_words=$2
  superset_words=$3

  for word in $subset_words; do
    word_list_contains "$superset_words" "$word" || installer_fatal "${label} references package missing from d-i pkgsel/include: ${word}"
  done
}

validate_class_policy() {
  [ -n "$PKGSEL_INCLUDE" ] || installer_fatal "selected classes resolved an empty d-i pkgsel/include package set"
  validate_policy_subset secure_boot_boot_chain_packages "$SECURE_BOOT_BOOT_CHAIN_PACKAGES" "$PKGSEL_INCLUDE"
  validate_policy_subset secure_boot_support_packages "$SECURE_BOOT_SUPPORT_PACKAGES" "$PKGSEL_INCLUDE"
}

write_class_policy_env() {
  policy_file=$1
  secure_boot_target_packages=

  append_unique_word_list secure_boot_target_packages "$SECURE_BOOT_BOOT_CHAIN_PACKAGES"
  append_unique_word_list secure_boot_target_packages "$SECURE_BOOT_SUPPORT_PACKAGES"

  {
    printf '# Generated by scripts/preseed/answers.sh from selected installer class fragments\n'
    printf 'INSTALLER_PKGSEL_INCLUDE=%s\n' "$(installer_shell_quote "$PKGSEL_INCLUDE")"
    printf 'INSTALLER_SECURE_BOOT_BOOT_CHAIN_PACKAGES=%s\n' "$(installer_shell_quote "$SECURE_BOOT_BOOT_CHAIN_PACKAGES")"
    printf 'INSTALLER_SECURE_BOOT_SUPPORT_PACKAGES=%s\n' "$(installer_shell_quote "$SECURE_BOOT_SUPPORT_PACKAGES")"
    printf 'INSTALLER_SECURE_BOOT_TARGET_PACKAGES=%s\n' "$(installer_shell_quote "$secure_boot_target_packages")"
  } >"$policy_file"
  chmod 0600 "$policy_file"
}

collect_selected_fragments() {
  merged_file=$1
  : >"$merged_file"
  while IFS= read -r rel_path || [ -n "$rel_path" ]; do
    [ -n "$rel_path" ] || continue
    if ! selected_fragment_applies_to_detected_hardware "$rel_path"; then
      installer_warn "skipping ${rel_path}: selected NVIDIA-dependent class requires a detected NVIDIA PCI display adapter"
      continue
    fi
    cached_path=$(ensure_cached_preseed_fragment "$rel_path")
    parse_preseed_fragment "$cached_path"
    grep -E -v '^d-i[[:space:]]+(anna/choose_modules|pkgsel/include|apt-setup/local[0-9]+/[^[:space:]]+)[[:space:]]+' "$cached_path" >>"$merged_file" || true
    printf '\n' >>"$merged_file"
  done <"$INCLUDE_LIST_FILE"
  chmod 0600 "$merged_file"
}

parse_base_answer_fragment() {
  rel_path=$1
  cached_path=$(ensure_cached_preseed_fragment "$rel_path")
  parse_preseed_fragment "$cached_path"
}

fragment_pkgsel_include_words() {
  path=$1
  [ -r "$path" ] || installer_fatal "preseed fragment is not readable for pkgsel extraction: ${path}"

  logical=
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      *\\)
        line=${line%\\}
        logical="${logical:+$logical }$line"
        continue
        ;;
      *)
        logical="${logical:+$logical }$line"
        ;;
    esac
    if preseed_parse_selection_fields "$logical"; then
      case "$PRESEED_RECORD_OWNER:$PRESEED_RECORD_QUESTION:$PRESEED_RECORD_TYPE" in
        d-i:pkgsel/include:string)
          for word in $PRESEED_RECORD_VALUE; do
            [ -n "$word" ] || continue
            pkgsel_include_word_supported_for_selected_arch "$word" || continue
            printf '%s\n' "$word"
          done
          ;;
      esac
    else
      parse_status=$?
      [ "$parse_status" -eq 1 ] || installer_fatal "malformed preseed fragment record while extracting pkgsel/include"
    fi
    logical=
  done <"$path"

  if [ -n "$logical" ]; then
    if preseed_parse_selection_fields "$logical"; then
      case "$PRESEED_RECORD_OWNER:$PRESEED_RECORD_QUESTION:$PRESEED_RECORD_TYPE" in
        d-i:pkgsel/include:string)
          for word in $PRESEED_RECORD_VALUE; do
            [ -n "$word" ] || continue
            pkgsel_include_word_supported_for_selected_arch "$word" || continue
            printf '%s\n' "$word"
          done
          ;;
      esac
    else
      parse_status=$?
      [ "$parse_status" -eq 1 ] || installer_fatal "malformed trailing preseed fragment record while extracting pkgsel/include"
    fi
  fi
}

fragment_pkgsel_include_word_list() {
  output=
  while IFS= read -r word || [ -n "$word" ]; do
    [ -n "$word" ] || continue
    output="${output:+$output }$word"
  done <<EOF
$(fragment_pkgsel_include_words "$1")
EOF
  printf '%s\n' "$output"
}

validate_fragment_pkgsel_subset() {
  label=$1
  rel_path=$2
  superset_words=$3
  cached_path=$(ensure_cached_preseed_fragment "$rel_path")

  subset_words=$(fragment_pkgsel_include_word_list "$cached_path")
  [ -n "$subset_words" ] || return 0
  validate_policy_subset "$label" "$subset_words" "$superset_words"
}

validate_selected_fragment_pkgsel_subsets() {
  validate_fragment_pkgsel_subset "base apt pkgsel/include" "fragments/apt.cfg" "$PKGSEL_INCLUDE"
  while IFS= read -r rel_path || [ -n "$rel_path" ]; do
    [ -n "$rel_path" ] || continue
    selected_fragment_applies_to_detected_hardware "$rel_path" || continue
    validate_fragment_pkgsel_subset "selected fragment pkgsel/include (${rel_path})" "$rel_path" "$PKGSEL_INCLUDE"
  done <"$INCLUDE_LIST_FILE"
}

write_answers_file() {
  answers_file=$1
  merged_file=$2
  [ -r "$merged_file" ] || installer_fatal "merged preseed fragment file is not readable: ${merged_file}"
  install -d -m 0700 "$(dirname "$answers_file")"
  cat "$merged_file" >"$answers_file"
  write_compacted_apt_setup_local_answers "$answers_file"

  {
    printf '# Generated by scripts/preseed/answers.sh from selected preseed cfg fragments\n'
    printf '# Runtime overrides are appended after the class fragments so host- and cmdline-derived values win.\n'
    printf 'd-i anna/choose_modules multiselect %s\n' "$ANNA_CHOOSE_MODULES"
    printf 'd-i anna/choose_modules seen true\n'
    printf 'd-i pkgsel/include string %s\n' "$PKGSEL_INCLUDE"
    printf 'd-i pkgsel/include seen true\n'
    append_runtime_baseline_answers "$answers_file" "$merged_file"
    printf 'd-i netcfg/get_hostname string %s\n' "$SYSTEM_HOSTNAME"
    printf 'd-i netcfg/get_hostname seen true\n'
    printf 'd-i netcfg/hostname string %s\n' "$SYSTEM_HOSTNAME"
    printf 'd-i netcfg/hostname seen true\n'
    printf 'd-i netcfg/get_domain string %s\n' "$SYSTEM_DOMAIN"
    printf 'd-i netcfg/get_domain seen true\n'
    write_wifi_answers
    if [ "$DUALBOOT_ENABLED" != true ]; then
      printf 'd-i grub-installer/only_debian boolean true\n'
      printf 'd-i grub-installer/only_debian seen true\n'
      printf 'd-i grub-installer/with_other_os boolean false\n'
      printf 'd-i grub-installer/with_other_os seen true\n'
      printf 'd-i grub-installer/enable_os_prober_otheros_yes boolean false\n'
      printf 'd-i grub-installer/enable_os_prober_otheros_yes seen true\n'
      printf 'd-i grub-installer/enable_os_prober_otheros_no boolean false\n'
      printf 'd-i grub-installer/enable_os_prober_otheros_no seen true\n'
      printf 'grub2 grub2/enable_os_prober boolean false\n'
      printf 'grub2 grub2/enable_os_prober seen true\n'
    fi
    printf 'd-i grub-installer/force-efi-extra-removable boolean false\n'
    printf 'd-i grub-installer/force-efi-extra-removable seen true\n'
    printf 'd-i grub-installer/update-nvram boolean true\n'
    printf 'd-i grub-installer/update-nvram seen true\n'
    printf 'd-i grub-installer/skip boolean false\n'
    printf 'd-i grub-installer/skip seen true\n'
    write_static_network_answers
  } >>"$answers_file"
  chmod 0600 "$answers_file"
}

usage() {
  echo "usage: ${0##*/} {apply|prepare-context|render|show-host} [seed-base]" >&2
  exit 1
}

render_answers_file() {
  MERGED_FRAGMENT_FILE="${CACHE_DIR}/preseed.fragments.cfg"
  append_debconf_word_list anna/choose_modules ANNA_CHOOSE_MODULES
  append_debconf_word_list pkgsel/include PKGSEL_INCLUDE
  parse_base_answer_fragment "fragments/apt.cfg"
  collect_selected_fragments "$MERGED_FRAGMENT_FILE"
  validate_selected_fragment_pkgsel_subsets
  validate_class_policy
  HOST_POLICY_ENV="${STATE_DIR}/selected-host.env"
  if [ ! -s "$HOST_POLICY_ENV" ]; then
    installer_fetch_host_env "$seed_base" "$HOST_PROFILE" "$HOST_POLICY_ENV" 0600
  fi
  # shellcheck disable=SC1090,SC1091
  . "$HOST_POLICY_ENV"
  read_network_domain_answer
  if selected_dualboot_addon; then
    DUALBOOT_ENABLED=true
  fi
  validate_dualboot_cmdline_contract
  case "$NETWORK_MODE" in
    static|dhcp) ;;
    *)
      installer_fatal "unsupported network mode: ${NETWORK_MODE}"
      ;;
  esac
  read_wifi_answers
  read_static_network_answers
  validate_hostname_component SYSTEM_DOMAIN "$SYSTEM_DOMAIN"
  validate_wifi_answers
  validate_static_network_answers
  validate_word_list ANNA_CHOOSE_MODULES "$ANNA_CHOOSE_MODULES"
  validate_word_list PKGSEL_INCLUDE "$PKGSEL_INCLUDE"
  installer_info "preseed answers classes raw: ${INSTALLER_CLASSES_RAW:-unset}"
  installer_info "preseed answers selected class refs: ${INSTALLER_SELECTED_CLASS_REFS:-unset}"
  installer_info "preseed answers anna modules: ${ANNA_CHOOSE_MODULES}"
  installer_info "preseed answers pkgsel/include: ${PKGSEL_INCLUDE}"
  installer_info "preseed answers secure boot boot-chain packages: ${SECURE_BOOT_BOOT_CHAIN_PACKAGES}"
  installer_info "preseed answers secure boot support packages: ${SECURE_BOOT_SUPPORT_PACKAGES}"
  planned_mirror_suite=forky
  planned_local_repos='sid,trixie,xanmod,cramerz'
  installer_append_log_category apt apt_config info apt "planned mirror=${planned_mirror_suite} security=enabled updates=enabled backports=enabled local_repos=${planned_local_repos} upgrade=safe-upgrade" || true
  installer_append_log_category package package_install info pkgsel "planned pkgsel/include=${PKGSEL_INCLUDE}" || true
  installer_append_log_category bootloader bootloader info grub "planned dualboot_class=${DUALBOOT_ENABLED} update_nvram=true force_extra_removable=false" || true
  installer_ensure_system_identity
  write_class_policy_env "$POLICY_ENV_FILE"
  answers_file="${STATE_DIR}/preseed.answers.cfg"
  write_answers_file "$answers_file" "$MERGED_FRAGMENT_FILE"
  installer_info "rendered preseed answers file: ${answers_file}"
  printf '%s\n' "$answers_file"
}

RUNTIME_DIR=$(installer_runtime_dir)
CACHE_DIR=$(installer_runtime_cache_dir)
STATE_DIR=$(installer_runtime_state_dir)
install -d -m 0700 "$CACHE_DIR/classes" "$STATE_DIR"
installer_ensure_log_files
INCLUDE_LIST_FILE="${STATE_DIR}/preseed-includes.list"
POLICY_ENV_FILE=$(installer_class_policy_env_path)

seed_base=$(installer_seed_base "${2:-}")
case "${1:-}" in
  prepare-context)
    installer_write_context "$seed_base" >/dev/null
    ;;
  *)
    installer_ensure_context_loaded "$seed_base"
    ;;
esac
installer_load_context_if_present || true

HOST_PROFILE=${INSTALLER_HOST_PROFILE:-$(installer_resolve_host_profile "" 2>/dev/null || true)}
[ -n "$HOST_PROFILE" ] || installer_fatal "selected host profile is unavailable in installer context"

write_include_list "$INCLUDE_LIST_FILE"

ANNA_CHOOSE_MODULES=
NETWORK_MODE=${INSTALLER_NETWORK_CLASS:-$(installer_selected_class_for_purpose network 2>/dev/null || true)}
[ -n "$NETWORK_MODE" ] || installer_fatal "selected network class is unavailable in installer context"
DUALBOOT_ENABLED=false
WIFI_ADDON_SELECTED=false
if selected_wifi_addon; then
  WIFI_ADDON_SELECTED=true
fi
WIFI_ESSID=
WIFI_ESSID_AGAIN=
WIFI_SECURITY_TYPE=
WIFI_WPA=
STATIC_IP_ADDRESS=
STATIC_NETMASK=
STATIC_GATEWAY=
STATIC_NAMESERVERS=
PKGSEL_INCLUDE=
SECURE_BOOT_BOOT_CHAIN_PACKAGES=$(secure_boot_boot_chain_packages_for_selected_arch)
SECURE_BOOT_SUPPORT_PACKAGES="initramfs-tools busybox cryptsetup efibootmgr mokutil sbsigntool openssl kmod util-linux util-linux-extra xz-utils zstd"

case "${1:-}" in
  apply)
    answers_file=$(render_answers_file)
    apply_answers_file "$answers_file"
    installer_log "applied dynamic preseed answers for ${HOST_PROFILE} from classes=${INSTALLER_CLASSES_RAW}"
    ;;
  prepare-context)
    MERGED_FRAGMENT_FILE="${CACHE_DIR}/preseed.fragments.cfg"
    parse_base_answer_fragment "fragments/apt.cfg"
    collect_selected_fragments "$MERGED_FRAGMENT_FILE"
    validate_selected_fragment_pkgsel_subsets
    validate_class_policy
    installer_fetch_host_env "$seed_base" "$HOST_PROFILE" "${STATE_DIR}/selected-host.env" 0600
    /bin/sh -n "${STATE_DIR}/selected-host.env" || installer_fatal 'selected host environment has invalid shell syntax'
    write_class_policy_env "$POLICY_ENV_FILE"
    ;;
  render)
    answers_file=$(render_answers_file)
    installer_log "rendered dynamic preseed answers for ${HOST_PROFILE} from classes=${INSTALLER_CLASSES_RAW}"
    printf '%s\n' "$answers_file"
    ;;
  show-host)
    printf '%s\n' "$HOST_PROFILE"
    ;;
  *)
    usage
    ;;
esac
