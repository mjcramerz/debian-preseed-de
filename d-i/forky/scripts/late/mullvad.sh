#!/bin/sh
# Shared late_command Mullvad package helper. This file is sourced, not executed.

MULLVAD_CODE_SIGNING_FINGERPRINT=A1198702FC3E0A09A9AE5B75D5A1D4F266DE8DDF
MULLVAD_CODE_SIGNING_KEY_URL=https://mullvad.net/media/mullvad-code-signing.asc
MULLVAD_AMD64_DEB_URL=https://mullvad.net/en/download/app/deb/latest
MULLVAD_ARM64_DEB_URL=https://mullvad.net/en/download/app/arm-deb/latest
MULLVAD_KEY_MINIMUM_BYTES=1024
MULLVAD_KEY_MAXIMUM_BYTES=131072
MULLVAD_SIGNATURE_MINIMUM_BYTES=128
MULLVAD_SIGNATURE_MAXIMUM_BYTES=131072
MULLVAD_DEB_MINIMUM_BYTES=10485760
MULLVAD_DEB_MAXIMUM_BYTES=536870912
MULLVAD_RESOLVER_SOURCE=/tmp/installer-mullvad-resolv.conf
MULLVAD_RESOLVED_STUB=/run/systemd/resolve/stub-resolv.conf
MULLVAD_RESOLVER_MAXIMUM_BYTES=65536
MULLVAD_RESOLVER_HOST=mullvad.net
MULLVAD_BITWARDEN_RESOLVER_HOST=bitwarden.com
MULLVAD_GITHUB_RESOLVER_HOST=github.com
MULLVAD_DNS_ATTEMPTS=5
MULLVAD_DNS_TIMEOUT_SECONDS=15
MULLVAD_DNS_RETRY_DELAY_SECONDS=2

mullvad_vpn_selected() {
  installer_selected_class_reference_is_selected addon/software 2>/dev/null && return 0
  installer_selected_class_reference_is_selected apps/mullvad 2>/dev/null
}

mullvad_validate_target_path() {
  mullvad_path_label=$1
  mullvad_path_value=$2

  case "$mullvad_path_value" in
    /*) ;;
    *) installer_fatal "${mullvad_path_label} must be an absolute target path: ${mullvad_path_value:-unset}" ;;
  esac
  case "$mullvad_path_value" in
    /|*..*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/@%:+,-]*)
      installer_fatal "${mullvad_path_label} contains unsupported path syntax: $mullvad_path_value"
      ;;
  esac
}

mullvad_https_url_host() {
  mullvad_url=$1

  case "$mullvad_url" in
    https://*) mullvad_authority=${mullvad_url#https://} ;;
    *) return 1 ;;
  esac
  mullvad_authority=${mullvad_authority%%/*}
  case "$mullvad_authority" in
    ''|*@*|*\?*|*\#*|*\[*|*\]*) return 1 ;;
  esac

  mullvad_host=${mullvad_authority%%:*}
  if [ "$mullvad_authority" != "$mullvad_host" ]; then
    mullvad_port=${mullvad_authority#*:}
    [ "$mullvad_port" = 443 ] || return 1
  fi
  mullvad_host=$(printf '%s' "$mullvad_host" | tr 'ABCDEFGHIJKLMNOPQRSTUVWXYZ' 'abcdefghijklmnopqrstuvwxyz')
  case "$mullvad_host" in
    ''|.*|*.|*..*|*[!abcdefghijklmnopqrstuvwxyz0123456789.-]*) return 1 ;;
  esac
  printf '%s\n' "$mullvad_host"
}

mullvad_require_allowed_https_url() {
  mullvad_url_label=$1
  mullvad_url_value=$2
  mullvad_url_host=$(mullvad_https_url_host "$mullvad_url_value" 2>/dev/null || true)

  [ -n "$mullvad_url_host" ] ||
    installer_fatal "${mullvad_url_label} is not a supported HTTPS URL: ${mullvad_url_value:-unset}"
  case "$mullvad_url_host" in
    mullvad.net|*.mullvad.net|github.com|*.githubusercontent.com)
      return 0
      ;;
  esac
  installer_fatal "${mullvad_url_label} resolved to an unapproved host: $mullvad_url_host"
}

mullvad_download_target_file() {
  mullvad_download_label=$1
  mullvad_download_url=$2
  mullvad_download_path=$3
  mullvad_download_minimum=$4
  mullvad_download_maximum=$5
  mullvad_download_partial="${mullvad_download_path}.part"
  mullvad_download_host_path="/target${mullvad_download_path}"
  mullvad_download_partial_host_path="/target${mullvad_download_partial}"

  mullvad_require_allowed_https_url "$mullvad_download_label URL" "$mullvad_download_url"
  mullvad_validate_target_path "$mullvad_download_label destination" "$mullvad_download_path"
  mullvad_validate_target_path "$mullvad_download_label partial destination" "$mullvad_download_partial"
  rm -f -- "$mullvad_download_host_path" "$mullvad_download_partial_host_path"

  mullvad_transfer_metadata=$(
    capture_in_target \
      "download ${mullvad_download_label}" \
      /usr/bin/env -i \
        HOME=/root \
        LC_ALL=C \
        PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
        /usr/bin/curl \
          --fail \
          --silent \
          --show-error \
          --location \
          --proto '=https' \
          --proto-redir '=https' \
          --connect-timeout 15 \
          --max-time 600 \
          --max-redirs 8 \
          --retry 5 \
          --retry-delay 2 \
          --retry-all-errors \
          --max-filesize "$mullvad_download_maximum" \
          --user-agent 'unattended-installer-mullvad/1.0' \
          --header 'Accept: application/octet-stream, application/vnd.debian.binary-package;q=0.9, application/pgp-signature;q=0.8, */*;q=0.1' \
          --output "$mullvad_download_partial" \
          --write-out '%{http_code}\n%{url_effective}' \
          --url "$mullvad_download_url"
  )

  mullvad_http_status=$(printf '%s\n' "$mullvad_transfer_metadata" | sed -n '1p')
  mullvad_effective_url=$(printf '%s\n' "$mullvad_transfer_metadata" | sed -n '2p')
  case "$mullvad_http_status" in
    200|206) ;;
    *)
      installer_fatal "${mullvad_download_label} returned unexpected HTTP status: ${mullvad_http_status:-unset}"
      ;;
  esac
  mullvad_require_allowed_https_url "$mullvad_download_label effective URL" "$mullvad_effective_url"

  [ -f "$mullvad_download_partial_host_path" ] && [ ! -L "$mullvad_download_partial_host_path" ] ||
    installer_fatal "${mullvad_download_label} download is not a regular file"
  mullvad_download_size=$(
    capture_in_target \
      "measure ${mullvad_download_label}" \
      /usr/bin/stat -c %s "$mullvad_download_partial"
  )
  case "$mullvad_download_size" in
    ''|*[!0-9]*)
      installer_fatal "${mullvad_download_label} download size is invalid: ${mullvad_download_size:-unset}"
      ;;
  esac
  [ "$mullvad_download_size" -ge "$mullvad_download_minimum" ] ||
    installer_fatal "${mullvad_download_label} download is unexpectedly small: ${mullvad_download_size} bytes"
  [ "$mullvad_download_size" -le "$mullvad_download_maximum" ] ||
    installer_fatal "${mullvad_download_label} download is unexpectedly large: ${mullvad_download_size} bytes"

  run_in_target_quiet \
    "publish ${mullvad_download_label}" \
    /bin/mv -f -- "$mullvad_download_partial" "$mullvad_download_path"
  installer_info \
    "downloaded ${mullvad_download_label} effective_url=${mullvad_effective_url} bytes=${mullvad_download_size}"
}

mullvad_installed_package_status() {
  mullvad_status_package=$1
  # The in-target dpkg-query expands the format token; pass it literally.
  # shellcheck disable=SC2016
  capture_in_target "inspect installed ${mullvad_status_package} package status" /bin/sh -eu -c '
package_name=$1
status_format=$2
dpkg-query -W -f="$status_format" "$package_name" 2>/dev/null || true
' sh "$mullvad_status_package" "\${Status}"
}

mullvad_capture_target_resolver() {
  run_in_target_quiet "capture installer DNS before systemd-resolved installation" /bin/sh -eu -c '
resolver_path=/etc/resolv.conf
resolver_snapshot=$1
resolver_maximum_bytes=$2

[ "$resolver_snapshot" = /tmp/installer-mullvad-resolv.conf ]
case "$resolver_maximum_bytes" in ""|*[!0-9]*) exit 1 ;; esac
[ "$resolver_maximum_bytes" -ge 1 ]
[ "$resolver_maximum_bytes" -le 1048576 ]
[ -r "$resolver_path" ]
[ -f "$resolver_path" ]
resolver_size=$(/usr/bin/stat -Lc %s -- "$resolver_path")
case "$resolver_size" in
  ""|*[!0-9]*) exit 1 ;;
esac
[ "$resolver_size" -ge 1 ]
[ "$resolver_size" -le "$resolver_maximum_bytes" ]
LC_ALL=C /usr/bin/grep -Eq \
  "^[[:space:]]*nameserver[[:space:]]+[^#[:space:]]+" \
  "$resolver_path"

resolver_snapshot_tmp="${resolver_snapshot}.tmp.$$"
cleanup_resolver_snapshot() {
  [ -z "$resolver_snapshot_tmp" ] || /bin/rm -f -- "$resolver_snapshot_tmp"
}
trap cleanup_resolver_snapshot 0 1 2 15
umask 077
/bin/cat -- "$resolver_path" >"$resolver_snapshot_tmp"
/bin/chown 0:0 "$resolver_snapshot_tmp"
/bin/chmod 0600 "$resolver_snapshot_tmp"
/bin/mv -f -- "$resolver_snapshot_tmp" "$resolver_snapshot"
resolver_snapshot_tmp=

[ -f "$resolver_snapshot" ]
[ ! -L "$resolver_snapshot" ]
[ "$(/usr/bin/stat -c %u:%g -- "$resolver_snapshot")" = 0:0 ]
[ "$(/usr/bin/stat -c %a -- "$resolver_snapshot")" = 600 ]
' sh "$MULLVAD_RESOLVER_SOURCE" "$MULLVAD_RESOLVER_MAXIMUM_BYTES"
}

mullvad_seed_target_resolved_stub() {
  mullvad_resolver_phase=$1
  case "$mullvad_resolver_phase" in
    systemd-resolved-installation|mullvad-vpn-installation) ;;
    *) installer_fatal "unsupported Mullvad resolver refresh phase: ${mullvad_resolver_phase:-unset}" ;;
  esac

  mullvad_target_root=$(target_root_dir)
  mullvad_validate_target_path "Mullvad target root" "$mullvad_target_root"
  [ -d "$mullvad_target_root" ] ||
    installer_fatal "Mullvad target root is unavailable: $mullvad_target_root"
  command -v chroot >/dev/null 2>&1 ||
    installer_fatal "chroot is unavailable for persistent target resolver refresh"

  mullvad_target_run="${mullvad_target_root%/}/run"
  if mullvad_target_run_source=$(target_mount_source "$mullvad_target_run" 2>/dev/null); then
    installer_fatal \
      "refusing to refresh the persistent target resolver while ${mullvad_target_run} is mounted from ${mullvad_target_run_source}"
  fi

  # debian-installer-utils in-target bind-mounts the installer /run over
  # /target/run. Seed systemd-resolved's target-side stub only after that bind
  # is gone, otherwise the file disappears when in-target cleans up and later
  # direct-chroot helpers see a dangling /etc/resolv.conf.
  installer_info \
    "direct-chroot: seed and verify systemd-resolved stub after ${mullvad_resolver_phase}"
  # shellcheck disable=SC2016
  if ! chroot "$mullvad_target_root" /usr/bin/env -i \
    HOME=/root \
    LC_ALL=C \
    PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    /bin/sh -eu -c '
resolver_source=$1
resolved_stub=$2
resolver_maximum_bytes=$3
attempts=$4
timeout_seconds=$5
retry_delay_seconds=$6
shift 6

[ "$resolver_source" = /tmp/installer-mullvad-resolv.conf ]
[ "$resolved_stub" = /run/systemd/resolve/stub-resolv.conf ]
case "$resolver_maximum_bytes" in ""|*[!0-9]*) exit 1 ;; esac
case "$attempts" in ""|*[!0-9]*) exit 1 ;; esac
case "$timeout_seconds" in ""|*[!0-9]*) exit 1 ;; esac
case "$retry_delay_seconds" in ""|*[!0-9]*) exit 1 ;; esac
[ "$resolver_maximum_bytes" -ge 1 ]
[ "$resolver_maximum_bytes" -le 1048576 ]
[ "$attempts" -ge 1 ]
[ "$attempts" -le 10 ]
[ "$timeout_seconds" -ge 1 ]
[ "$timeout_seconds" -le 60 ]
[ "$retry_delay_seconds" -le 30 ]
[ "$#" -ge 1 ]

[ -x /usr/lib/systemd/systemd-resolved ]
[ -x /usr/bin/resolvectl ]
[ -L /usr/sbin/resolvconf ]
[ "$(/usr/bin/readlink -f /usr/sbin/resolvconf)" = /usr/bin/resolvectl ]
[ -f "$resolver_source" ]
[ ! -L "$resolver_source" ]
resolver_owner_group=$(/usr/bin/stat -c %u:%g -- "$resolver_source")
[ "$resolver_owner_group" = 0:0 ]
resolver_size=$(/usr/bin/stat -c %s -- "$resolver_source")
case "$resolver_size" in
  ""|*[!0-9]*) exit 1 ;;
esac
[ "$resolver_size" -ge 1 ]
[ "$resolver_size" -le "$resolver_maximum_bytes" ]
[ -L /etc/resolv.conf ]
resolver_path=$(/usr/bin/readlink -m /etc/resolv.conf)
[ "$resolver_path" = "$resolved_stub" ]
[ ! -L "$resolved_stub" ]

/usr/bin/install -d -o 0 -g 0 -m 0755 -- "$(/usr/bin/dirname "$resolved_stub")"
resolved_stub_tmp="${resolved_stub}.tmp.$$"
cleanup_resolved_stub() {
  [ -z "$resolved_stub_tmp" ] || /bin/rm -f -- "$resolved_stub_tmp"
}
trap cleanup_resolved_stub 0 1 2 15
/bin/cat -- "$resolver_source" >"$resolved_stub_tmp"
/bin/chown 0:0 "$resolved_stub_tmp"
/bin/chmod 0644 "$resolved_stub_tmp"
/bin/mv -f -- "$resolved_stub_tmp" "$resolved_stub"
resolved_stub_tmp=

[ -f "$resolved_stub" ]
[ ! -L "$resolved_stub" ]
[ -s "$resolved_stub" ]
[ "$(/usr/bin/stat -c %u:%g -- "$resolved_stub")" = 0:0 ]
[ "$(/usr/bin/stat -c %a -- "$resolved_stub")" = 644 ]
LC_ALL=C /usr/bin/grep -Eq \
  "^[[:space:]]*nameserver[[:space:]]+[^#[:space:]]+" \
  "$resolved_stub"

for resolver_host in "$@"; do
  case "$resolver_host" in
    ""|.*|*.|*..*|*[!abcdefghijklmnopqrstuvwxyz0123456789.-]*) exit 1 ;;
  esac
done

attempt=1
while [ "$attempt" -le "$attempts" ]; do
  failed_hosts=
  for resolver_host in "$@"; do
    if /usr/bin/timeout "$timeout_seconds" \
        /usr/bin/getent ahosts "$resolver_host" >/dev/null 2>&1; then
      :
    else
      failed_hosts="${failed_hosts} ${resolver_host}"
    fi
  done
  [ -z "$failed_hosts" ] && exit 0
  [ "$attempt" -lt "$attempts" ] || break
  /bin/sleep "$retry_delay_seconds"
  attempt=$((attempt + 1))
done

printf "resolver probes failed after %s attempt(s):%s\n" \
  "$attempts" "$failed_hosts" >&2
exit 1
' sh \
    "$MULLVAD_RESOLVER_SOURCE" \
    "$MULLVAD_RESOLVED_STUB" \
    "$MULLVAD_RESOLVER_MAXIMUM_BYTES" \
    "$MULLVAD_DNS_ATTEMPTS" \
    "$MULLVAD_DNS_TIMEOUT_SECONDS" \
    "$MULLVAD_DNS_RETRY_DELAY_SECONDS" \
    "$MULLVAD_RESOLVER_HOST" \
    "$MULLVAD_BITWARDEN_RESOLVER_HOST" \
    "$MULLVAD_GITHUB_RESOLVER_HOST"
  then
    installer_fatal \
      "persistent target resolver refresh failed after ${mullvad_resolver_phase}"
  fi

  installer_info \
    "seeded persistent target systemd-resolved stub phase=${mullvad_resolver_phase} source=${MULLVAD_RESOLVER_SOURCE} stub=${MULLVAD_RESOLVED_STUB} dns_hosts=${MULLVAD_RESOLVER_HOST},${MULLVAD_BITWARDEN_RESOLVER_HOST},${MULLVAD_GITHUB_RESOLVER_HOST}"
}

install_target_systemd_resolved_for_mullvad() {
  mullvad_capture_target_resolver

  mullvad_resolved_status=$(mullvad_installed_package_status systemd-resolved)
  if [ "$mullvad_resolved_status" != "install ok installed" ]; then
    run_in_target \
      "install systemd-resolved for Mullvad DNS integration" \
      /usr/bin/env \
        DEBIAN_FRONTEND=noninteractive \
        DEBCONF_NONINTERACTIVE_SEEN=true \
        NEEDRESTART_SUSPEND=1 \
        /usr/bin/apt-get \
          -o Acquire::Retries=5 \
          -o Acquire::http::Timeout=45 \
          -o Acquire::https::Timeout=45 \
          -o Binary::apt::APT::Keep-Downloaded-Packages=false \
          -o DPkg::Lock::Timeout=60 \
          -o DPkg::Use-Pty=0 \
          -y \
          --no-install-recommends \
          --no-install-suggests \
          install systemd-resolved
  fi

  mullvad_resolved_status=$(mullvad_installed_package_status systemd-resolved)
  [ "$mullvad_resolved_status" = "install ok installed" ] ||
    installer_fatal "systemd-resolved is not fully installed: ${mullvad_resolved_status:-missing}"
  mullvad_legacy_resolvconf_status=$(mullvad_installed_package_status resolvconf)
  [ "$mullvad_legacy_resolvconf_status" != "install ok installed" ] ||
    installer_fatal "legacy resolvconf must not remain installed with systemd-resolved"

  mullvad_seed_target_resolved_stub systemd-resolved-installation
}

install_target_mullvad_vpn_if_selected() (
  set -eu

  mullvad_vpn_selected || exit 0
  require_in_target "Mullvad VPN package installation"
  prepare_target_volatile_dirs_for_apt
  mullvad_work_host_path=
  mullvad_resolver_host_path="/target${MULLVAD_RESOLVER_SOURCE}"
  case "$mullvad_resolver_host_path" in
    /target/tmp/installer-mullvad-resolv.conf) ;;
    *) installer_fatal "refusing unsafe Mullvad resolver snapshot path: $mullvad_resolver_host_path" ;;
  esac
  mullvad_cleanup() {
    case "${mullvad_work_host_path:-}" in
      '') ;;
      /target/tmp/installer-mullvad-vpn) rm -rf -- "$mullvad_work_host_path" ;;
    esac
    rm -f -- "$mullvad_resolver_host_path"
  }
  trap mullvad_cleanup EXIT HUP INT TERM
  install_target_systemd_resolved_for_mullvad

  mullvad_existing_status=$(mullvad_installed_package_status mullvad-vpn)
  if [ "$mullvad_existing_status" = "install ok installed" ]; then
    mullvad_existing_version=$(
      capture_in_target \
        "inspect installed Mullvad VPN package version" \
        /usr/bin/dpkg-query -W -f="\${Version}" mullvad-vpn
    )
    mullvad_existing_unit=$(target_systemd_unit_path mullvad-daemon.service system 2>/dev/null || true)
    [ -n "$mullvad_existing_unit" ] ||
      installer_fatal "installed mullvad-vpn package does not provide mullvad-daemon.service"
    installer_info \
      "Mullvad VPN is already installed version=${mullvad_existing_version} unit=${mullvad_existing_unit}"
    exit 0
  fi

  mullvad_target_arch=$(
    capture_in_target \
      "resolve Mullvad VPN target architecture" \
      /usr/bin/dpkg --print-architecture
  )
  case "$mullvad_target_arch" in
    amd64)
      mullvad_deb_url=$MULLVAD_AMD64_DEB_URL
      ;;
    arm64)
      mullvad_deb_url=$MULLVAD_ARM64_DEB_URL
      ;;
    *)
      installer_fatal "Mullvad VPN is unsupported for target architecture: ${mullvad_target_arch:-unset}"
      ;;
  esac
  mullvad_signature_url="${mullvad_deb_url}/signature"

  mullvad_work_dir=/tmp/installer-mullvad-vpn
  mullvad_key_path="${mullvad_work_dir}/mullvad-code-signing.asc"
  mullvad_signature_path="${mullvad_work_dir}/mullvad-vpn.deb.asc"
  mullvad_deb_path="${mullvad_work_dir}/mullvad-vpn.deb"
  mullvad_gnupg_home="${mullvad_work_dir}/gnupg"
  mullvad_work_host_path="/target${mullvad_work_dir}"

  case "$mullvad_work_host_path" in
    /target/tmp/installer-mullvad-vpn) ;;
    *) installer_fatal "refusing unsafe Mullvad work directory: $mullvad_work_host_path" ;;
  esac
  rm -rf -- "$mullvad_work_host_path"
  run_in_target_quiet \
    "prepare Mullvad VPN verification workspace" \
    /usr/bin/install -d -m 0700 -- "$mullvad_work_dir" "$mullvad_gnupg_home"

  mullvad_download_target_file \
    "Mullvad code signing key" \
    "$MULLVAD_CODE_SIGNING_KEY_URL" \
    "$mullvad_key_path" \
    "$MULLVAD_KEY_MINIMUM_BYTES" \
    "$MULLVAD_KEY_MAXIMUM_BYTES"
  mullvad_download_target_file \
    "Mullvad VPN Debian package" \
    "$mullvad_deb_url" \
    "$mullvad_deb_path" \
    "$MULLVAD_DEB_MINIMUM_BYTES" \
    "$MULLVAD_DEB_MAXIMUM_BYTES"
  mullvad_download_target_file \
    "Mullvad VPN detached signature" \
    "$mullvad_signature_url" \
    "$mullvad_signature_path" \
    "$MULLVAD_SIGNATURE_MINIMUM_BYTES" \
    "$MULLVAD_SIGNATURE_MAXIMUM_BYTES"

  mullvad_key_listing=$(
    capture_in_target \
      "inspect Mullvad code signing key" \
      /usr/bin/gpg \
        --batch \
        --no-options \
        --homedir "$mullvad_gnupg_home" \
        --with-colons \
        --import-options show-only \
        --import "$mullvad_key_path"
  )
  mullvad_primary_fingerprints=$(
    printf '%s\n' "$mullvad_key_listing" |
      awk -F: '
        $1 == "pub" {
          want_fingerprint = 1
          next
        }
        want_fingerprint && $1 == "fpr" {
          print $10
          want_fingerprint = 0
        }
      '
  )
  [ "$mullvad_primary_fingerprints" = "$MULLVAD_CODE_SIGNING_FINGERPRINT" ] ||
    installer_fatal "Mullvad code signing key fingerprint mismatch"

  run_in_target_quiet \
    "import pinned Mullvad code signing key" \
    /usr/bin/gpg \
      --batch \
      --no-options \
      --homedir "$mullvad_gnupg_home" \
      --import "$mullvad_key_path"

  mullvad_signature_status=$(
    capture_in_target \
      "verify Mullvad VPN detached signature" \
      /usr/bin/gpg \
        --batch \
        --no-options \
        --homedir "$mullvad_gnupg_home" \
        --status-fd 1 \
        --verify "$mullvad_signature_path" "$mullvad_deb_path"
  )
  mullvad_valid_signature_count=$(
    printf '%s\n' "$mullvad_signature_status" |
      awk -v expected="$MULLVAD_CODE_SIGNING_FINGERPRINT" '
        $1 == "[GNUPG:]" && $2 == "VALIDSIG" {
          total++
          if ($3 == expected || $NF == expected) {
            expected_total++
          }
        }
        END {
          printf "%d:%d\n", total + 0, expected_total + 0
        }
      '
  )
  [ "$mullvad_valid_signature_count" = "1:1" ] ||
    installer_fatal "Mullvad VPN package does not have exactly one valid signature from the pinned key"

  mullvad_deb_magic=$(head -c 8 "$mullvad_work_host_path/mullvad-vpn.deb" 2>/dev/null || true)
  [ "$mullvad_deb_magic" = '!<arch>' ] ||
    installer_fatal "Mullvad VPN download does not have Debian archive framing"
  run_in_target_quiet \
    "validate Mullvad VPN Debian package" \
    /usr/bin/dpkg-deb --info "$mullvad_deb_path"

  mullvad_package_name=$(
    capture_in_target \
      "read Mullvad VPN package name" \
      /usr/bin/dpkg-deb -f "$mullvad_deb_path" Package
  )
  mullvad_package_version=$(
    capture_in_target \
      "read Mullvad VPN package version" \
      /usr/bin/dpkg-deb -f "$mullvad_deb_path" Version
  )
  mullvad_package_arch=$(
    capture_in_target \
      "read Mullvad VPN package architecture" \
      /usr/bin/dpkg-deb -f "$mullvad_deb_path" Architecture
  )
  [ "$mullvad_package_name" = mullvad-vpn ] ||
    installer_fatal "Mullvad VPN artifact has unexpected Package field: ${mullvad_package_name:-unset}"
  [ "$mullvad_package_arch" = "$mullvad_target_arch" ] ||
    installer_fatal "Mullvad VPN artifact architecture mismatch: ${mullvad_package_arch:-unset}"
  [ -n "$mullvad_package_version" ] ||
    installer_fatal "Mullvad VPN artifact has no Version field"
  [ "${#mullvad_package_version}" -le 128 ] ||
    installer_fatal "Mullvad VPN artifact Version field exceeds 128 characters"
  test_in_target /usr/bin/dpkg --validate-version "$mullvad_package_version" ||
    installer_fatal "Mullvad VPN artifact Version field is invalid: $mullvad_package_version"

  mullvad_install_deb_path=$mullvad_deb_path
  if installer_selected_class_reference_is_selected addon/software 2>/dev/null; then
    case "$mullvad_package_version" in
      ''|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.+:~_-]*)
        installer_fatal "Mullvad VPN artifact Version field is unsafe for local repository retention"
        ;;
    esac
    mullvad_repository_dir=/var/lib/software/debs
    mullvad_repository_deb="${mullvad_repository_dir}/${mullvad_package_name}_${mullvad_package_version}_${mullvad_package_arch}.deb"
    mullvad_repository_tmp="${mullvad_repository_deb}.tmp.$$"
    mullvad_validate_target_path "Mullvad local repository directory" "$mullvad_repository_dir"
    mullvad_validate_target_path "Mullvad retained Debian package" "$mullvad_repository_deb"
    mullvad_validate_target_path "Mullvad retained Debian package temporary path" "$mullvad_repository_tmp"
    run_in_target_quiet \
      "retain verified Mullvad VPN package for the managed local repository" \
      /bin/sh -eu -c '
source_path=$1
repository_dir=$2
destination=$3
temporary=$4

install -d -m 0755 -- /var/lib/software "$repository_dir"
[ ! -L "$repository_dir" ]
if [ -e "$destination" ] || [ -L "$destination" ]; then
  [ -f "$destination" ] && [ ! -L "$destination" ]
fi
install -m 0644 -- "$source_path" "$temporary"
[ "$(sha256sum "$source_path" | awk "{print \$1}")" = "$(sha256sum "$temporary" | awk "{print \$1}")" ]
mv -f -- "$temporary" "$destination"
' sh "$mullvad_deb_path" "$mullvad_repository_dir" "$mullvad_repository_deb" "$mullvad_repository_tmp"
    mullvad_install_deb_path=$mullvad_repository_deb
  fi

  run_in_target \
    "install verified Mullvad VPN package" \
    /usr/bin/env \
      DEBIAN_FRONTEND=noninteractive \
      DEBCONF_NONINTERACTIVE_SEEN=true \
      NEEDRESTART_SUSPEND=1 \
      /usr/bin/apt-get \
        -o Acquire::Retries=5 \
        -o Acquire::http::Timeout=45 \
        -o Acquire::https::Timeout=45 \
        -o DPkg::Lock::Timeout=60 \
        -o DPkg::Use-Pty=0 \
        -y \
        --no-install-recommends \
        --no-install-suggests \
        install "$mullvad_install_deb_path"

  mullvad_seed_target_resolved_stub mullvad-vpn-installation

  mullvad_installed_status=$(mullvad_installed_package_status mullvad-vpn)
  [ "$mullvad_installed_status" = "install ok installed" ] ||
    installer_fatal "mullvad-vpn is not fully installed: ${mullvad_installed_status:-missing}"
  mullvad_installed_version=$(
    capture_in_target \
      "verify installed Mullvad VPN version" \
      /usr/bin/dpkg-query -W -f="\${Version}" mullvad-vpn
  )
  [ "$mullvad_installed_version" = "$mullvad_package_version" ] ||
    installer_fatal "installed Mullvad VPN version does not match the verified artifact"
  mullvad_daemon_unit=$(target_systemd_unit_path mullvad-daemon.service system 2>/dev/null || true)
  [ -n "$mullvad_daemon_unit" ] ||
    installer_fatal "verified mullvad-vpn package did not install mullvad-daemon.service"
  mullvad_package_sha256=$(
    capture_in_target \
      "record Mullvad VPN package SHA-256" \
      /usr/bin/sha256sum "$mullvad_deb_path" |
      awk '{print $1}'
  )
  case "$mullvad_package_sha256" in
    *[!0-9a-f]*|'') installer_fatal "Mullvad VPN package SHA-256 is invalid" ;;
  esac
  [ "${#mullvad_package_sha256}" -eq 64 ] ||
    installer_fatal "Mullvad VPN package SHA-256 has an invalid length"

  installer_info \
    "installed verified Mullvad VPN package version=${mullvad_installed_version} architecture=${mullvad_target_arch} sha256=${mullvad_package_sha256} unit=${mullvad_daemon_unit}"
)
