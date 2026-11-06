#!/bin/sh
# Safe reader for protected installer credentials. Non-secret installer answers
# are resolved from the kernel command line/debconf by server_answer_value and
# never come from /preseed.env.
# Return codes: 0=value, 1=missing/empty, 2=unsafe/unreadable input.

server_credential_variable() {
  case "${1:-}" in
    primary_user) printf '%s\n' PRESEED_PRIMARY_USERNAME ;;
    primary_fullname) printf '%s\n' PRESEED_PRIMARY_FULLNAME ;;
    primary_password) printf '%s\n' PRESEED_PRIMARY_PASSWORD ;;
    root_password) printf '%s\n' PRESEED_ROOT_PASSWORD ;;
    crowdsec_token) printf '%s\n' PRESEED_CROWDSEC_TOKEN ;;
    shim_signed_passphrase) printf '%s\n' PRESEED_SHIM_SIGNED_PASSPHRASE ;;
    github_runner_token) printf '%s\n' PRESEED_GITHUB_RUNNER_TOKEN ;;
    gitlab_runner_token) printf '%s\n' PRESEED_GITLAB_RUNNER_TOKEN ;;
    wifi_interface) printf '%s\n' PRESEED_WIFI_INTERFACE ;;
    wifi_essid) printf '%s\n' PRESEED_WIFI_ESSID ;;
    wifi_security) printf '%s\n' PRESEED_WIFI_SECURITY ;;
    wifi_cidr) printf '%s\n' PRESEED_WIFI_CIDR ;;
    wifi_passphrase) printf '%s\n' PRESEED_WIFI_PASSPHRASE ;;
    podman_tls_passphrase) printf '%s\n' PRESEED_PODMAN_TLS_PASSPHRASE ;;
    *) return 1 ;;
  esac
}

server_cmdline_value() (
  set +x
  set +v
  set -f
  key=${1:-}
  [ -n "$key" ] || exit 1
  [ -r /proc/cmdline ] || exit 1
  for argument in $(cat /proc/cmdline); do
    case "$argument" in
      "$key") printf '\n'; exit 0 ;;
      "$key"=*) printf '%s\n' "${argument#*=}"; exit 0 ;;
    esac
  done
  exit 1
)

server_debconf_value() {
  question=${1:-}
  [ -n "$question" ] || return 1
  value=
  if command -v debconf-get >/dev/null 2>&1; then
    value=$(debconf-get "$question" 2>/dev/null || true)
    case "$value" in
      "$question":\ *) value=${value#"$question": } ;;
      "$question":*) value=${value#"$question":} ;;
    esac
    value=$(printf '%s\n' "$value" | sed -n '1{s/\r$//;p;q;}')
    [ -n "$value" ] || return 1
    printf '%s\n' "$value"
    return 0
  fi
  if command -v debconf-communicate >/dev/null 2>&1; then
    response=$(printf 'GET %s\n' "$question" | debconf-communicate 2>/dev/null || true)
    case "$response" in
      0\ *) value=${response#0 } ;;
      *) value= ;;
    esac
    [ -n "$value" ] || return 1
    printf '%s\n' "$value"
    return 0
  fi
  return 1
}

server_answer_value() {
  for answer_key in "$@"; do
    value=$(server_cmdline_value "$answer_key" 2>/dev/null || true)
    if [ -n "$value" ]; then
      printf '%s\n' "$value"
      return 0
    fi
  done
  for answer_key in "$@"; do
    value=$(server_debconf_value "$answer_key" 2>/dev/null || true)
    if [ -n "$value" ]; then
      printf '%s\n' "$value"
      return 0
    fi
  done
  return 1
}

server_ipv4_netmask_prefix() {
  case "${1:-}" in
    0) printf '0\n' ;; 128.0.0.0) printf '1\n' ;;
    192.0.0.0) printf '2\n' ;; 224.0.0.0) printf '3\n' ;;
    240.0.0.0) printf '4\n' ;; 248.0.0.0) printf '5\n' ;;
    252.0.0.0) printf '6\n' ;; 254.0.0.0) printf '7\n' ;;
    255.0.0.0) printf '8\n' ;; 255.128.0.0) printf '9\n' ;;
    255.192.0.0) printf '10\n' ;; 255.224.0.0) printf '11\n' ;;
    255.240.0.0) printf '12\n' ;; 255.248.0.0) printf '13\n' ;;
    255.252.0.0) printf '14\n' ;; 255.254.0.0) printf '15\n' ;;
    255.255.0.0) printf '16\n' ;; 255.255.128.0) printf '17\n' ;;
    255.255.192.0) printf '18\n' ;; 255.255.224.0) printf '19\n' ;;
    255.255.240.0) printf '20\n' ;; 255.255.248.0) printf '21\n' ;;
    255.255.252.0) printf '22\n' ;; 255.255.254.0) printf '23\n' ;;
    255.255.255.0) printf '24\n' ;; 255.255.255.128) printf '25\n' ;;
    255.255.255.192) printf '26\n' ;; 255.255.255.224) printf '27\n' ;;
    255.255.255.240) printf '28\n' ;; 255.255.255.248) printf '29\n' ;;
    255.255.255.252) printf '30\n' ;; 255.255.255.254) printf '31\n' ;;
    255.255.255.255) printf '32\n' ;;
    0|[0-9]|[12][0-9]|3[0-2]) printf '%s\n' "$1" ;;
    *) return 1 ;;
  esac
}

server_profile_from_classes() {
  classes=${1:-}
  old_ifs=$IFS
  IFS=',; '
  # shellcheck disable=SC2086
  set -- $classes
  IFS=$old_ifs
  for token in "$@"; do
    case "$token" in
      profile/*|profile:*|profile.*) token=${token#*/}; token=${token#*:}; token=${token#*.} ;;
    esac
    case "$token" in
      btrfs-srv-flex|btrfs-srv-flex-duo|f2fs-srv-hp14) printf '%s\n' "$token"; return 0 ;;
    esac
  done
  return 1
}

server_credential_error() {
  printf '[credentials] error: %s\n' "$*" >&2
  return 2
}

server_credential_check_file() (
  set +x
  set +v
  set -f
  credential_file=$1
  case "$credential_file" in
    /*) ;;
    *) server_credential_error 'credential path must be absolute'; exit 2 ;;
  esac
  case "$credential_file" in
    *[![:print:]]*|*/../*|*/./*|*//*)
      server_credential_error 'credential path is not canonical'; exit 2 ;;
  esac
  [ -f "$credential_file" ] && [ ! -L "$credential_file" ] || {
    server_credential_error 'credential file must be a regular non-symlink'; exit 2;
  }
  metadata=$(LC_ALL=C ls -ldn "$credential_file" 2>/dev/null) || {
    server_credential_error 'credential metadata is unavailable'; exit 2;
  }
  set -- $metadata
  [ "$#" -ge 4 ] && [ "$2" = 1 ] && [ "$3" = "$(id -u)" ] || {
    server_credential_error 'credential file must be owned by the installer and have one hard link'; exit 2;
  }
  case "$1" in
    -r--------|-rw-------|-r--r-----|-rw-r-----) ;;
    *) server_credential_error 'credential file permissions are too broad'; exit 2 ;;
  esac
)

server_credential_read() (
  set +x
  set +v
  set -f
  umask 077
  name=$(server_credential_variable "${1:-}") || exit 1
  file=${INSTALLER_PRESEED_ENV_FILE:-/preseed.env}
  server_credential_check_file "$file" || exit $?
  temp=$(mktemp /tmp/server-install-env.XXXXXX) || {
    server_credential_error 'cannot create private credential staging'; exit 2;
  }
  trap 'rm -f "$temp"' EXIT HUP INT TERM
  sed '1s/^\357\273\277//;s/\r$//' "$file" >"$temp" 2>/dev/null || {
    server_credential_error 'cannot normalize credential file'; exit 2;
  }
  /bin/sh -n "$temp" >/dev/null 2>&1 || {
    server_credential_error 'credential file has invalid shell syntax'; exit 2;
  }
  unset PRESEED_PRIMARY_USERNAME PRESEED_PRIMARY_FULLNAME PRESEED_PRIMARY_PASSWORD PRESEED_ROOT_PASSWORD
  unset PRESEED_CROWDSEC_TOKEN PRESEED_SHIM_SIGNED_PASSPHRASE
  unset PRESEED_GITHUB_RUNNER_TOKEN PRESEED_GITLAB_RUNNER_TOKEN
  unset PRESEED_WIFI_INTERFACE PRESEED_WIFI_ESSID PRESEED_WIFI_SECURITY PRESEED_WIFI_CIDR PRESEED_WIFI_PASSPHRASE
  unset PRESEED_PODMAN_TLS_PASSPHRASE
  . "$temp" >/dev/null 2>&1 || {
    server_credential_error 'credential assignments could not be loaded'; exit 2;
  }
  # The identifier is selected from a fixed mapping above; the value remains
  # quoted data even when it contains shell metacharacters.
  eval "value=\${${name}:-}"
  [ -n "${value:-}" ] || exit 1
  case "$value" in
    *[![:print:]]*) server_credential_error 'credential values must be printable single-line data'; exit 2 ;;
  esac
  printf '%s\n' "$value"
)
