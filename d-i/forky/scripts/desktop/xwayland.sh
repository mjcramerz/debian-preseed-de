#!/bin/sh
# Private Xwayland package payloads. This file is sourced, not executed.
#
# Debian ships Xwayland's common data in xserver-common. There is no separate
# xwayland-common binary package.
#
# Xwayland, xserver-common, libxcb-cursor0, and x11-xkb-utils remain
# byte-pinned Debian Snapshot payloads. Xwayland-only X11/XCB libraries are
# downloaded through authenticated APT metadata and extracted into
# /opt/xwayland without host installation. The private xkbcomp executable uses
# explicitly installed target libraries while remaining unavailable outside
# the managed Zoom/Discord Bubblewrap namespace.

XWAYLAND_PRIVATE_DEPENDENCY_RELEASE=forky
XWAYLAND_PRIVATE_DEPENDENCY_MAX_BYTES=16777216
XWAYLAND_PRIVATE_DEPENDENCY_SPECS='
libfontenc1:libfontenc.so.1
libxau6:libXau.so.6
libxcb-image0:libxcb-image.so.0
libxcb-render-util0:libxcb-render-util.so.0
libxcb-render0:libxcb-render.so.0
libxcb-shm0:libxcb-shm.so.0
libxcb-util1:libxcb-util.so.1
libxcb1:libxcb.so.1
libxcvt0:libxcvt.so.0
libxdmcp6:libXdmcp.so.6
libxfont2:libXfont2.so.2
libxshmfence1:libxshmfence.so.1
'
readonly \
  XWAYLAND_PRIVATE_DEPENDENCY_RELEASE \
  XWAYLAND_PRIVATE_DEPENDENCY_MAX_BYTES \
  XWAYLAND_PRIVATE_DEPENDENCY_SPECS

desktop_xwayland_fail() {
  rm -rf -- "/target${xwayland_work_dir:-/tmp/invalid-xwayland-work-dir}" 2>/dev/null || true
  installer_fatal "$*"
}

desktop_xwayland_validate_unsigned_integer() {
  xwayland_value_name=$1
  xwayland_value=$2

  case "$xwayland_value" in
    ''|*[!0-9]*)
      installer_fatal "${xwayland_value_name} must be an unsigned integer"
      ;;
  esac
}

desktop_xwayland_validate_sha256() {
  xwayland_sha_name=$1
  xwayland_sha_value=$2

  case "$xwayland_sha_value" in
    *[!0123456789abcdef]*|'')
      installer_fatal "${xwayland_sha_name} must contain lowercase hexadecimal characters"
      ;;
  esac
  [ "${#xwayland_sha_value}" -eq 64 ] ||
    installer_fatal "${xwayland_sha_name} must contain 64 characters"
}

desktop_xwayland_find_first_path() {
  xwayland_find_description=$1
  xwayland_find_output=$2
  shift 2

  if ! find "$@" -print >"$xwayland_find_output"; then
    desktop_xwayland_fail \
      "failed to inspect private Xwayland package payload for ${xwayland_find_description}"
  fi
  if ! xwayland_find_result=$(sed -n '1p' "$xwayland_find_output"); then
    desktop_xwayland_fail \
      "failed to read private Xwayland ${xwayland_find_description} scan results"
  fi
  printf '%s\n' "$xwayland_find_result"
}

desktop_xwayland_validate_policy() {
  : "${LABWC_XWAYLAND_VERSION:?LABWC_XWAYLAND_VERSION must be set}"
  : "${LABWC_XWAYLAND_ARCHITECTURE:?LABWC_XWAYLAND_ARCHITECTURE must be set}"
  : "${LABWC_XWAYLAND_URL:?LABWC_XWAYLAND_URL must be set}"
  : "${LABWC_XWAYLAND_SHA256:?LABWC_XWAYLAND_SHA256 must be set}"
  : "${LABWC_XWAYLAND_BYTES:?LABWC_XWAYLAND_BYTES must be set}"
  : "${LABWC_XWAYLAND_COMMON_VERSION:?LABWC_XWAYLAND_COMMON_VERSION must be set}"
  : "${LABWC_XWAYLAND_COMMON_ARCHITECTURE:?LABWC_XWAYLAND_COMMON_ARCHITECTURE must be set}"
  : "${LABWC_XWAYLAND_COMMON_URL:?LABWC_XWAYLAND_COMMON_URL must be set}"
  : "${LABWC_XWAYLAND_COMMON_SHA256:?LABWC_XWAYLAND_COMMON_SHA256 must be set}"
  : "${LABWC_XWAYLAND_COMMON_BYTES:?LABWC_XWAYLAND_COMMON_BYTES must be set}"
  : "${LABWC_XWAYLAND_XCB_CURSOR_VERSION:?LABWC_XWAYLAND_XCB_CURSOR_VERSION must be set}"
  : "${LABWC_XWAYLAND_XCB_CURSOR_URL:?LABWC_XWAYLAND_XCB_CURSOR_URL must be set}"
  : "${LABWC_XWAYLAND_XCB_CURSOR_SHA256:?LABWC_XWAYLAND_XCB_CURSOR_SHA256 must be set}"
  : "${LABWC_XWAYLAND_XCB_CURSOR_BYTES:?LABWC_XWAYLAND_XCB_CURSOR_BYTES must be set}"
  : "${LABWC_XWAYLAND_XKBCOMP_VERSION:?LABWC_XWAYLAND_XKBCOMP_VERSION must be set}"
  : "${LABWC_XWAYLAND_XKBCOMP_ARCHITECTURE:?LABWC_XWAYLAND_XKBCOMP_ARCHITECTURE must be set}"
  : "${LABWC_XWAYLAND_XKBCOMP_URL:?LABWC_XWAYLAND_XKBCOMP_URL must be set}"
  : "${LABWC_XWAYLAND_XKBCOMP_SHA256:?LABWC_XWAYLAND_XKBCOMP_SHA256 must be set}"
  : "${LABWC_XWAYLAND_XKBCOMP_BYTES:?LABWC_XWAYLAND_XKBCOMP_BYTES must be set}"
  : "${LABWC_XWAYLAND_RUNTIME_ROOT:?LABWC_XWAYLAND_RUNTIME_ROOT must be set}"

  [ "$LABWC_XWAYLAND_VERSION" = "2:24.1.13-1" ] ||
    installer_fatal "LABWC_XWAYLAND_VERSION must remain pinned to 2:24.1.13-1"
  [ "$LABWC_XWAYLAND_ARCHITECTURE" = amd64 ] ||
    installer_fatal "LABWC_XWAYLAND_ARCHITECTURE must remain pinned to amd64"
  [ "$LABWC_XWAYLAND_URL" = "https://snapshot.debian.org/archive/debian/20260805T142647Z/pool/main/x/xwayland/xwayland_24.1.13-1_amd64.deb" ] ||
    installer_fatal "LABWC_XWAYLAND_URL must remain pinned to the Debian Snapshot package"
  [ "$LABWC_XWAYLAND_SHA256" = a0633569cf2b65d5d4902a2b6213d59c7db7973faef0233df9ace48f334ba6c2 ] ||
    installer_fatal "LABWC_XWAYLAND_SHA256 must remain pinned to the Debian 24.1.13-1 amd64 package"
  desktop_xwayland_validate_sha256 LABWC_XWAYLAND_SHA256 "$LABWC_XWAYLAND_SHA256"
  desktop_xwayland_validate_unsigned_integer LABWC_XWAYLAND_BYTES "$LABWC_XWAYLAND_BYTES"
  [ "$LABWC_XWAYLAND_BYTES" -eq 992244 ] ||
    installer_fatal "LABWC_XWAYLAND_BYTES must remain pinned to 992244"

  [ "$LABWC_XWAYLAND_COMMON_VERSION" = "2:21.1.24-1" ] ||
    installer_fatal "LABWC_XWAYLAND_COMMON_VERSION must remain pinned to 2:21.1.24-1"
  [ "$LABWC_XWAYLAND_COMMON_ARCHITECTURE" = all ] ||
    installer_fatal "LABWC_XWAYLAND_COMMON_ARCHITECTURE must remain pinned to all"
  [ "$LABWC_XWAYLAND_COMMON_URL" = "https://snapshot.debian.org/archive/debian/20260805T142647Z/pool/main/x/xorg-server/xserver-common_21.1.24-1_all.deb" ] ||
    installer_fatal "LABWC_XWAYLAND_COMMON_URL must remain pinned to the Debian Snapshot package"
  [ "$LABWC_XWAYLAND_COMMON_SHA256" = 807f2faaccada8ceac329a2c4d5b264fb794baf44bd6a2a787f9a0a75a67446b ] ||
    installer_fatal "LABWC_XWAYLAND_COMMON_SHA256 must remain pinned to the Debian 21.1.24-1 all package"
  desktop_xwayland_validate_sha256 \
    LABWC_XWAYLAND_COMMON_SHA256 \
    "$LABWC_XWAYLAND_COMMON_SHA256"
  desktop_xwayland_validate_unsigned_integer \
    LABWC_XWAYLAND_COMMON_BYTES \
    "$LABWC_XWAYLAND_COMMON_BYTES"
  [ "$LABWC_XWAYLAND_COMMON_BYTES" -eq 2455368 ] ||
    installer_fatal "LABWC_XWAYLAND_COMMON_BYTES must remain pinned to 2455368"

  [ "$LABWC_XWAYLAND_XCB_CURSOR_VERSION" = 0.1.6-1 ] ||
    installer_fatal "LABWC_XWAYLAND_XCB_CURSOR_VERSION must remain pinned to 0.1.6-1"
  [ "$LABWC_XWAYLAND_XCB_CURSOR_URL" = "https://snapshot.debian.org/archive/debian/20260206T022815Z/pool/main/x/xcb-util-cursor/libxcb-cursor0_0.1.6-1_amd64.deb" ] ||
    installer_fatal "LABWC_XWAYLAND_XCB_CURSOR_URL must remain pinned to the Debian Snapshot package"
  [ "$LABWC_XWAYLAND_XCB_CURSOR_SHA256" = f2f7730d4559769ec45aa610967d27f410b642af0c993813f50092972f8da0d4 ] ||
    installer_fatal "LABWC_XWAYLAND_XCB_CURSOR_SHA256 must remain pinned to the Debian 0.1.6-1 amd64 package"
  desktop_xwayland_validate_sha256 \
    LABWC_XWAYLAND_XCB_CURSOR_SHA256 \
    "$LABWC_XWAYLAND_XCB_CURSOR_SHA256"
  desktop_xwayland_validate_unsigned_integer \
    LABWC_XWAYLAND_XCB_CURSOR_BYTES \
    "$LABWC_XWAYLAND_XCB_CURSOR_BYTES"
  [ "$LABWC_XWAYLAND_XCB_CURSOR_BYTES" -eq 17772 ] ||
    installer_fatal "LABWC_XWAYLAND_XCB_CURSOR_BYTES must remain pinned to 17772"

  [ "$LABWC_XWAYLAND_XKBCOMP_VERSION" = "7.7+9" ] ||
    installer_fatal "LABWC_XWAYLAND_XKBCOMP_VERSION must remain pinned to 7.7+9"
  [ "$LABWC_XWAYLAND_XKBCOMP_ARCHITECTURE" = amd64 ] ||
    installer_fatal "LABWC_XWAYLAND_XKBCOMP_ARCHITECTURE must remain pinned to amd64"
  [ "$LABWC_XWAYLAND_XKBCOMP_ARCHITECTURE" = "$LABWC_XWAYLAND_ARCHITECTURE" ] ||
    installer_fatal "LABWC_XWAYLAND_XKBCOMP_ARCHITECTURE must match LABWC_XWAYLAND_ARCHITECTURE"
  [ "$LABWC_XWAYLAND_XKBCOMP_URL" = "https://snapshot.debian.org/archive/debian/20260805T142647Z/pool/main/x/x11-xkb-utils/x11-xkb-utils_7.7+9_amd64.deb" ] ||
    installer_fatal "LABWC_XWAYLAND_XKBCOMP_URL must remain pinned to the Debian Snapshot package"
  [ "$LABWC_XWAYLAND_XKBCOMP_SHA256" = 745e29c79bb435d057cdbf8bb59a35fa33e818e566cb754674f44d381ccd4317 ] ||
    installer_fatal "LABWC_XWAYLAND_XKBCOMP_SHA256 must remain pinned to the Debian 7.7+9 amd64 package"
  desktop_xwayland_validate_sha256 \
    LABWC_XWAYLAND_XKBCOMP_SHA256 \
    "$LABWC_XWAYLAND_XKBCOMP_SHA256"
  desktop_xwayland_validate_unsigned_integer \
    LABWC_XWAYLAND_XKBCOMP_BYTES \
    "$LABWC_XWAYLAND_XKBCOMP_BYTES"
  [ "$LABWC_XWAYLAND_XKBCOMP_BYTES" -eq 158552 ] ||
    installer_fatal "LABWC_XWAYLAND_XKBCOMP_BYTES must remain pinned to 158552"

  [ "$LABWC_XWAYLAND_RUNTIME_ROOT" = /opt/xwayland ] ||
    installer_fatal "LABWC_XWAYLAND_RUNTIME_ROOT must remain pinned to /opt/xwayland"

  [ "$XWAYLAND_PRIVATE_DEPENDENCY_RELEASE" = forky ] ||
    installer_fatal "private Xwayland dependency release must remain pinned to forky"
  desktop_xwayland_validate_unsigned_integer \
    XWAYLAND_PRIVATE_DEPENDENCY_MAX_BYTES \
    "$XWAYLAND_PRIVATE_DEPENDENCY_MAX_BYTES"
  [ "$XWAYLAND_PRIVATE_DEPENDENCY_MAX_BYTES" -eq 16777216 ] ||
    installer_fatal "private Xwayland dependency package limit must remain pinned to 16777216 bytes"
}

desktop_xwayland_preflight_target_architecture() {
  desktop_xwayland_validate_policy

  XWAYLAND_TARGET_ARCHITECTURE=$(capture_in_target "detect target architecture for private Xwayland" /usr/bin/dpkg --print-architecture)
  [ -n "$XWAYLAND_TARGET_ARCHITECTURE" ] ||
    installer_fatal "target architecture detection returned no output before private Xwayland installation"
  [ "$XWAYLAND_TARGET_ARCHITECTURE" = "$LABWC_XWAYLAND_ARCHITECTURE" ] ||
    installer_fatal "private Xwayland is pinned for ${LABWC_XWAYLAND_ARCHITECTURE}, but the target architecture is ${XWAYLAND_TARGET_ARCHITECTURE}"
}

desktop_xwayland_download_private_deb() {
  xwayland_download_label=$1
  xwayland_download_url=$2
  xwayland_download_path=$3
  xwayland_download_bytes=$4

  if ! attempt_in_target "download private ${xwayland_download_label} package from Debian Snapshot" \
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
        --max-time 180 \
        --max-redirs 4 \
        --retry 3 \
        --retry-all-errors \
        --max-filesize "$xwayland_download_bytes" \
        --user-agent 'unattended-installer-xwayland/1.0' \
        --header 'Accept: application/vnd.debian.binary-package, application/octet-stream;q=0.9, */*;q=0.1' \
        --output "$xwayland_download_path" \
        --url "$xwayland_download_url"
  then
    desktop_xwayland_fail "failed to download private ${xwayland_download_label} package from Debian Snapshot"
  fi
}

desktop_xwayland_download_repository_deb() {
  xwayland_repository_package=$1
  xwayland_repository_architecture=$2
  xwayland_repository_directory=$3

  case "$xwayland_repository_package" in
    ''|*[!a-z0-9+.-]*)
      desktop_xwayland_fail \
        "private Xwayland repository package name is invalid: ${xwayland_repository_package:-unset}"
      ;;
  esac
  case "$xwayland_repository_architecture" in
    ''|*[!a-z0-9-]*)
      desktop_xwayland_fail \
        "private Xwayland repository architecture is invalid: ${xwayland_repository_architecture:-unset}"
      ;;
  esac
  case "$xwayland_repository_directory" in
    "${xwayland_work_dir}"/packages/"$xwayland_repository_package") ;;
    *)
      desktop_xwayland_fail \
        "private Xwayland repository download directory is outside the managed work tree"
      ;;
  esac

  if ! attempt_in_target \
    "download private ${xwayland_repository_package} package from authenticated ${XWAYLAND_PRIVATE_DEPENDENCY_RELEASE} APT metadata" \
    /usr/bin/env -i \
      DEBIAN_FRONTEND=noninteractive \
      HOME=/root \
      LC_ALL=C \
      PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
      /bin/sh -eu -c '
        umask 077
        cd "$1"
        exec /usr/bin/apt-get \
          -q \
          -o Acquire::Retries=2 \
          -o Acquire::http::Timeout=30 \
          -o Acquire::https::Timeout=30 \
          -o Acquire::AllowInsecureRepositories=false \
          -o Acquire::AllowDowngradeToInsecureRepositories=false \
          -o APT::Get::AllowUnauthenticated=false \
          -o APT::Install-Recommends=false \
          -o APT::Install-Suggests=false \
          -o APT::Sandbox::User=root \
          -t "$2" \
          download \
          "$3:$4"
      ' \
      xwayland-private-apt-download \
      "$xwayland_repository_directory" \
      "$XWAYLAND_PRIVATE_DEPENDENCY_RELEASE" \
      "$xwayland_repository_package" \
      "$xwayland_repository_architecture"
  then
    desktop_xwayland_fail \
      "failed to download private ${xwayland_repository_package} package from authenticated ${XWAYLAND_PRIVATE_DEPENDENCY_RELEASE} APT metadata"
  fi
}

desktop_xwayland_find_single_repository_deb() {
  xwayland_repository_directory_host=$1
  xwayland_repository_expected_package=$2
  xwayland_repository_scan_output=$3

  if ! find \
    "$xwayland_repository_directory_host" \
    -mindepth 1 \
    -maxdepth 1 \
    -print >"$xwayland_repository_scan_output"
  then
    desktop_xwayland_fail \
      "failed to inspect the private ${xwayland_repository_expected_package} APT download"
  fi
  xwayland_repository_entry_count=$(
    wc -l <"$xwayland_repository_scan_output" | awk '{print $1}'
  )
  desktop_xwayland_validate_unsigned_integer \
    "private ${xwayland_repository_expected_package} APT download entry count" \
    "$xwayland_repository_entry_count"
  [ "$xwayland_repository_entry_count" -eq 1 ] ||
    desktop_xwayland_fail \
      "private ${xwayland_repository_expected_package} APT download produced ${xwayland_repository_entry_count} entries instead of one"

  if ! xwayland_repository_deb_host=$(sed -n '1p' "$xwayland_repository_scan_output"); then
    desktop_xwayland_fail \
      "failed to read the private ${xwayland_repository_expected_package} APT download path"
  fi
  case "$xwayland_repository_deb_host" in
    "$xwayland_repository_directory_host"/*.deb) ;;
    *)
      desktop_xwayland_fail \
        "private ${xwayland_repository_expected_package} APT download is not a single .deb file"
      ;;
  esac
  [ -f "$xwayland_repository_deb_host" ] &&
    [ ! -L "$xwayland_repository_deb_host" ] ||
    desktop_xwayland_fail \
      "private ${xwayland_repository_expected_package} APT download is not a regular file"

  printf '%s\n' "$xwayland_repository_deb_host"
}

desktop_xwayland_validate_repository_deb() {
  xwayland_repository_deb=$1
  xwayland_repository_deb_host=$2
  xwayland_repository_expected_package=$3
  xwayland_repository_expected_architecture=$4

  xwayland_repository_deb_size=$(
    wc -c <"$xwayland_repository_deb_host" | awk '{print $1}'
  )
  desktop_xwayland_validate_unsigned_integer \
    "downloaded ${xwayland_repository_expected_package} package size" \
    "$xwayland_repository_deb_size"
  [ "$xwayland_repository_deb_size" -gt 0 ] &&
    [ "$xwayland_repository_deb_size" -le "$XWAYLAND_PRIVATE_DEPENDENCY_MAX_BYTES" ] ||
    desktop_xwayland_fail \
      "downloaded ${xwayland_repository_expected_package} package exceeds the managed ${XWAYLAND_PRIVATE_DEPENDENCY_MAX_BYTES}-byte limit"

  xwayland_repository_package=$(
    capture_in_target \
      "read private repository package name" \
      /usr/bin/dpkg-deb \
      -f \
      "$xwayland_repository_deb" \
      Package
  )
  xwayland_repository_version=$(
    capture_in_target \
      "read private ${xwayland_repository_expected_package} package version" \
      /usr/bin/dpkg-deb \
      -f \
      "$xwayland_repository_deb" \
      Version
  )
  xwayland_repository_architecture=$(
    capture_in_target \
      "read private ${xwayland_repository_expected_package} package architecture" \
      /usr/bin/dpkg-deb \
      -f \
      "$xwayland_repository_deb" \
      Architecture
  )
  [ "$xwayland_repository_package" = "$xwayland_repository_expected_package" ] ||
    desktop_xwayland_fail \
      "downloaded private repository package has unexpected Package: ${xwayland_repository_package:-unset}"
  [ -n "$xwayland_repository_version" ] ||
    desktop_xwayland_fail \
      "downloaded ${xwayland_repository_expected_package} package has no Version"
  [ "$xwayland_repository_architecture" = "$xwayland_repository_expected_architecture" ] ||
    desktop_xwayland_fail \
      "downloaded ${xwayland_repository_expected_package} package has unexpected Architecture: ${xwayland_repository_architecture:-unset}"
}

desktop_xwayland_extract_private_deb() {
  xwayland_extract_label=$1
  xwayland_extract_deb=$2
  xwayland_extract_directory=$3

  if ! attempt_in_target \
    "extract private ${xwayland_extract_label} package" \
    /usr/bin/dpkg-deb \
    -x \
    "$xwayland_extract_deb" \
    "$xwayland_extract_directory"
  then
    desktop_xwayland_fail \
      "failed to extract the private ${xwayland_extract_label} package"
  fi
}

desktop_xwayland_validate_extracted_library() {
  xwayland_private_library_directory=$1
  xwayland_private_library_name=$2
  xwayland_private_library_path="${xwayland_private_library_directory}/${xwayland_private_library_name}"

  case "$xwayland_private_library_name" in
    ''|*/*|*[!A-Za-z0-9._-]*)
      desktop_xwayland_fail \
        "private Xwayland library name is invalid: ${xwayland_private_library_name:-unset}"
      ;;
  esac

  if [ -L "$xwayland_private_library_path" ]; then
    if ! xwayland_private_library_target=$(readlink -f -- "$xwayland_private_library_path"); then
      desktop_xwayland_fail \
        "private Xwayland library has an unreadable target: ${xwayland_private_library_name}"
    fi
    case "$xwayland_private_library_target" in
      "$xwayland_private_library_directory"/*) ;;
      *)
        desktop_xwayland_fail \
          "private Xwayland library target escapes its managed directory: ${xwayland_private_library_name}"
        ;;
    esac
    [ -f "$xwayland_private_library_target" ] &&
      [ ! -L "$xwayland_private_library_target" ] &&
      [ -r "$xwayland_private_library_target" ] ||
      desktop_xwayland_fail \
        "private Xwayland library target is not a readable regular file: ${xwayland_private_library_name}"
  elif [ -f "$xwayland_private_library_path" ] &&
    [ -r "$xwayland_private_library_path" ]
  then
    :
  else
    desktop_xwayland_fail \
      "private Xwayland runtime is missing ${xwayland_private_library_name}"
  fi
}

desktop_xwayland_validate_private_deb() {
  xwayland_private_deb=$1
  xwayland_private_deb_host=$2
  xwayland_private_expected_package=$3
  xwayland_private_expected_version=$4
  xwayland_private_expected_architecture=$5
  xwayland_private_expected_bytes=$6
  xwayland_private_expected_sha256=$7

  [ -f "$xwayland_private_deb_host" ] && [ ! -L "$xwayland_private_deb_host" ] ||
    desktop_xwayland_fail "private Xwayland download is missing package: ${xwayland_private_expected_package}"

  xwayland_private_deb_size=$(wc -c <"$xwayland_private_deb_host" | awk '{print $1}')
  desktop_xwayland_validate_unsigned_integer \
    "downloaded ${xwayland_private_expected_package} package size" \
    "$xwayland_private_deb_size"
  [ "$xwayland_private_deb_size" -eq "$xwayland_private_expected_bytes" ] ||
    desktop_xwayland_fail "downloaded ${xwayland_private_expected_package} package has unexpected size: ${xwayland_private_deb_size} bytes"

  xwayland_private_deb_sha256=$(
    capture_in_target "hash private ${xwayland_private_expected_package} package" /usr/bin/sha256sum "$xwayland_private_deb" |
      awk '{print $1}'
  )
  [ "$xwayland_private_deb_sha256" = "$xwayland_private_expected_sha256" ] ||
    desktop_xwayland_fail "downloaded ${xwayland_private_expected_package} package SHA-256 does not match the pinned Debian package"

  xwayland_private_package=$(capture_in_target "read private package name" /usr/bin/dpkg-deb -f "$xwayland_private_deb" Package)
  xwayland_private_version=$(capture_in_target "read private package version" /usr/bin/dpkg-deb -f "$xwayland_private_deb" Version)
  xwayland_private_architecture=$(capture_in_target "read private package architecture" /usr/bin/dpkg-deb -f "$xwayland_private_deb" Architecture)
  [ "$xwayland_private_package" = "$xwayland_private_expected_package" ] ||
    desktop_xwayland_fail "downloaded private package has unexpected Package: ${xwayland_private_package:-unset}"
  [ "$xwayland_private_version" = "$xwayland_private_expected_version" ] ||
    desktop_xwayland_fail "downloaded ${xwayland_private_expected_package} package has unexpected Version: ${xwayland_private_version:-unset}"
  [ "$xwayland_private_architecture" = "$xwayland_private_expected_architecture" ] ||
    desktop_xwayland_fail "downloaded ${xwayland_private_expected_package} package has unexpected Architecture: ${xwayland_private_architecture:-unset}"

  XWAYLAND_PRIVATE_PACKAGE_SHA256=$xwayland_private_deb_sha256
}

desktop_xwayland_require_target_package() {
  xwayland_required_package=$1
  xwayland_required_status=$(
    capture_in_target \
      "check target ${xwayland_required_package} runtime for private Xwayland" \
      /usr/bin/dpkg-query \
      -W \
      -f='${Status}' \
      "$xwayland_required_package"
  )
  [ "$xwayland_required_status" = "install ok installed" ] ||
    desktop_xwayland_fail "target package is not installed for private Xwayland: ${xwayland_required_package}"
}

desktop_xwayland_prepare_xkbcomp_overlay() {
  xwayland_system_xkbcomp_host=/target/usr/bin/xkbcomp
  xwayland_xkbcomp_source="${xwayland_extract_host}/usr/bin/xkbcomp"
  xwayland_xkbcomp_overlay_directory="${xwayland_extract_host}/usr/lib/xkbcomp-overlay"
  xwayland_xkbcomp_overlay_entry="${xwayland_xkbcomp_overlay_directory}/xkbcomp"

  [ -d /target/usr/bin ] && [ ! -L /target/usr/bin ] ||
    desktop_xwayland_fail "target /usr/bin is unavailable or unsafe for private Xwayland"
  if [ -e "$xwayland_system_xkbcomp_host" ] ||
    [ -L "$xwayland_system_xkbcomp_host" ]
  then
    desktop_xwayland_fail \
      "target /usr/bin/xkbcomp must remain absent; x11-xkb-utils must not be installed system-wide"
  fi
  if [ -e "$xwayland_xkbcomp_overlay_directory" ] ||
    [ -L "$xwayland_xkbcomp_overlay_directory" ]
  then
    desktop_xwayland_fail "private xkbcomp overlay directory already exists"
  fi

  install -d -m 0700 "$xwayland_xkbcomp_overlay_directory" ||
    desktop_xwayland_fail "failed to create the private xkbcomp overlay directory"
  ln "$xwayland_xkbcomp_source" "$xwayland_xkbcomp_overlay_entry" ||
    desktop_xwayland_fail "failed to link the private xkbcomp overlay entry"
  chown root:root "$xwayland_xkbcomp_overlay_directory" ||
    desktop_xwayland_fail "failed to normalize private xkbcomp overlay ownership"
  chmod 0555 "$xwayland_xkbcomp_overlay_directory" ||
    desktop_xwayland_fail "failed to lock the private xkbcomp overlay directory"

  [ -f "$xwayland_xkbcomp_overlay_entry" ] &&
    [ ! -L "$xwayland_xkbcomp_overlay_entry" ] &&
    [ -x "$xwayland_xkbcomp_overlay_entry" ] &&
    [ "$xwayland_xkbcomp_source" -ef "$xwayland_xkbcomp_overlay_entry" ] ||
    desktop_xwayland_fail "private xkbcomp overlay entry is not the prepared private executable"

  unset \
    xwayland_system_xkbcomp_host \
    xwayland_xkbcomp_overlay_directory \
    xwayland_xkbcomp_overlay_entry \
    xwayland_xkbcomp_source
}

desktop_xwayland_assert_public_runtime_absent() {
  # The in-target dpkg-query expands the format token; pass it literally.
  # shellcheck disable=SC2016
  xwayland_public_status=$(
    capture_in_target \
      "inspect public Xwayland package status" \
      /bin/sh -eu -c '
dpkg-query -W -f="\${Status}" xwayland 2>/dev/null || true
'
  )
  [ "$xwayland_public_status" != "install ok installed" ] ||
    desktop_xwayland_fail "public xwayland package must not remain installed"
  if [ -e /target/usr/bin/Xwayland ] || [ -L /target/usr/bin/Xwayland ]; then
    desktop_xwayland_fail "public /usr/bin/Xwayland must not exist"
  fi
  unset xwayland_public_status
}

desktop_xwayland_remove_public_runtime() {
  run_in_target_quiet \
    "purge public Xwayland package" \
    /usr/bin/env \
      DEBIAN_FRONTEND=noninteractive \
      DEBCONF_NONINTERACTIVE_SEEN=true \
      NEEDRESTART_SUSPEND=1 \
      /usr/bin/apt-get \
        -o DPkg::Lock::Timeout=60 \
        -o DPkg::Use-Pty=0 \
        -y \
        purge xwayland
  desktop_xwayland_assert_public_runtime_absent
}

desktop_install_xwayland() {
  [ -n "${XWAYLAND_TARGET_ARCHITECTURE:-}" ] || desktop_xwayland_preflight_target_architecture

  desktop_xwayland_remove_public_runtime

  xwayland_work_dir="/tmp/xwayland-install.$$"
  xwayland_extract_dir="${xwayland_work_dir}/extract"
  xwayland_work_host="/target${xwayland_work_dir}"
  xwayland_extract_host="/target${xwayland_extract_dir}"
  xwayland_runtime_host="/target${LABWC_XWAYLAND_RUNTIME_ROOT}"
  xwayland_deb="${xwayland_work_dir}/xwayland.deb"
  xwayland_deb_host="/target${xwayland_deb}"
  xwayland_common_deb="${xwayland_work_dir}/xserver-common.deb"
  xwayland_common_deb_host="/target${xwayland_common_deb}"
  xwayland_xcb_cursor_deb="${xwayland_work_dir}/libxcb-cursor0.deb"
  xwayland_xcb_cursor_deb_host="/target${xwayland_xcb_cursor_deb}"
  xwayland_xkbcomp_deb="${xwayland_work_dir}/x11-xkb-utils.deb"
  xwayland_xkbcomp_deb_host="/target${xwayland_xkbcomp_deb}"
  xwayland_repository_root="${xwayland_work_dir}/packages"
  xwayland_repository_root_host="/target${xwayland_repository_root}"
  xwayland_find_output="${xwayland_work_host}/find-output"

  rm -rf -- "$xwayland_work_host"
  install -d -m 0700 "$xwayland_extract_host" "$xwayland_repository_root_host"

  desktop_xwayland_download_private_deb \
    xwayland \
    "$LABWC_XWAYLAND_URL" \
    "$xwayland_deb" \
    "$LABWC_XWAYLAND_BYTES"
  desktop_xwayland_download_private_deb \
    xserver-common \
    "$LABWC_XWAYLAND_COMMON_URL" \
    "$xwayland_common_deb" \
    "$LABWC_XWAYLAND_COMMON_BYTES"
  desktop_xwayland_download_private_deb \
    libxcb-cursor0 \
    "$LABWC_XWAYLAND_XCB_CURSOR_URL" \
    "$xwayland_xcb_cursor_deb" \
    "$LABWC_XWAYLAND_XCB_CURSOR_BYTES"
  desktop_xwayland_download_private_deb \
    x11-xkb-utils \
    "$LABWC_XWAYLAND_XKBCOMP_URL" \
    "$xwayland_xkbcomp_deb" \
    "$LABWC_XWAYLAND_XKBCOMP_BYTES"

  desktop_xwayland_validate_private_deb \
    "$xwayland_deb" \
    "$xwayland_deb_host" \
    xwayland \
    "$LABWC_XWAYLAND_VERSION" \
    "$LABWC_XWAYLAND_ARCHITECTURE" \
    "$LABWC_XWAYLAND_BYTES" \
    "$LABWC_XWAYLAND_SHA256"

  desktop_xwayland_validate_private_deb \
    "$xwayland_common_deb" \
    "$xwayland_common_deb_host" \
    xserver-common \
    "$LABWC_XWAYLAND_COMMON_VERSION" \
    "$LABWC_XWAYLAND_COMMON_ARCHITECTURE" \
    "$LABWC_XWAYLAND_COMMON_BYTES" \
    "$LABWC_XWAYLAND_COMMON_SHA256"

  desktop_xwayland_validate_private_deb \
    "$xwayland_xcb_cursor_deb" \
    "$xwayland_xcb_cursor_deb_host" \
    libxcb-cursor0 \
    "$LABWC_XWAYLAND_XCB_CURSOR_VERSION" \
    "$LABWC_XWAYLAND_ARCHITECTURE" \
    "$LABWC_XWAYLAND_XCB_CURSOR_BYTES" \
    "$LABWC_XWAYLAND_XCB_CURSOR_SHA256"

  desktop_xwayland_validate_private_deb \
    "$xwayland_xkbcomp_deb" \
    "$xwayland_xkbcomp_deb_host" \
    x11-xkb-utils \
    "$LABWC_XWAYLAND_XKBCOMP_VERSION" \
    "$LABWC_XWAYLAND_XKBCOMP_ARCHITECTURE" \
    "$LABWC_XWAYLAND_XKBCOMP_BYTES" \
    "$LABWC_XWAYLAND_XKBCOMP_SHA256"

  xwayland_depends=$(capture_in_target "read private Xwayland dependencies" /usr/bin/dpkg-deb -f "$xwayland_deb" Depends)
  for xwayland_required_dependency in \
    libc6 \
    libdecor-0-0 \
    libdrm2 \
    libei1 \
    libepoxy0 \
    libgbm1 \
    libgcrypt20 \
    libgl1 \
    liboeffis1 \
    libpixman-1-0 \
    libtirpc3t64 \
    libwayland-client0 \
    libxau6 \
    libxcvt0 \
    libxdmcp6 \
    libxfont2 \
    libxshmfence1 \
    xserver-common
  do
    case "$xwayland_depends" in
      *"$xwayland_required_dependency"*) ;;
      *)
        desktop_xwayland_fail "downloaded xwayland package no longer declares ${xwayland_required_dependency}: ${xwayland_depends}"
        ;;
    esac
  done
  unset xwayland_required_dependency

  xwayland_xcb_cursor_depends=$(capture_in_target "read private libxcb-cursor0 dependencies" /usr/bin/dpkg-deb -f "$xwayland_xcb_cursor_deb" Depends)
  for xwayland_required_dependency in libc6 libxcb-image0 libxcb-render-util0 libxcb-render0 libxcb1; do
    case "$xwayland_xcb_cursor_depends" in
      *"$xwayland_required_dependency"*) ;;
      *)
        desktop_xwayland_fail "downloaded libxcb-cursor0 package no longer declares ${xwayland_required_dependency}: ${xwayland_xcb_cursor_depends}"
        ;;
    esac
  done
  unset xwayland_required_dependency

  xwayland_xkbcomp_depends=$(capture_in_target "read private x11-xkb-utils dependencies" /usr/bin/dpkg-deb -f "$xwayland_xkbcomp_deb" Depends)
  for xwayland_required_dependency in \
    libc6 \
    libx11-6 \
    libxaw7 \
    libxkbfile1 \
    libxrandr2 \
    libxt6t64
  do
    case "$xwayland_xkbcomp_depends" in
      *"$xwayland_required_dependency"*) ;;
      *)
        desktop_xwayland_fail "downloaded x11-xkb-utils package no longer declares ${xwayland_required_dependency}: ${xwayland_xkbcomp_depends}"
        ;;
    esac
  done
  unset xwayland_required_dependency xwayland_xkbcomp_depends

  for xwayland_required_package in \
    libc6 \
    libdecor-0-0 \
    libdecor-0-plugin-1-gtk \
    libdrm2 \
    libei1 \
    libepoxy0 \
    libgbm1 \
    libgcrypt20 \
    libgl1 \
    liboeffis1 \
    libpixman-1-0 \
    libtirpc3t64 \
    libwayland-client0 \
    libx11-6 \
    libxaw7 \
    libxkbfile1 \
    libxrandr2 \
    libxt6t64 \
    xkb-data
  do
    desktop_xwayland_require_target_package "$xwayland_required_package"
  done
  unset xwayland_required_package xwayland_required_status

  for xwayland_extract_spec in \
    "xwayland:${xwayland_deb}" \
    "xserver-common:${xwayland_common_deb}" \
    "libxcb-cursor0:${xwayland_xcb_cursor_deb}" \
    "x11-xkb-utils:${xwayland_xkbcomp_deb}"
  do
    xwayland_extract_label=${xwayland_extract_spec%%:*}
    xwayland_extract_deb=${xwayland_extract_spec#*:}
    desktop_xwayland_extract_private_deb \
      "$xwayland_extract_label" \
      "$xwayland_extract_deb" \
      "$xwayland_extract_dir"
  done
  unset xwayland_extract_deb xwayland_extract_label xwayland_extract_spec

  for xwayland_private_dependency_spec in $XWAYLAND_PRIVATE_DEPENDENCY_SPECS; do
    xwayland_private_dependency_package=${xwayland_private_dependency_spec%%:*}
    xwayland_private_dependency_library=${xwayland_private_dependency_spec#*:}
    [ "$xwayland_private_dependency_package" != "$xwayland_private_dependency_spec" ] ||
      desktop_xwayland_fail \
        "private Xwayland dependency specification is malformed: ${xwayland_private_dependency_spec}"

    xwayland_repository_directory="${xwayland_repository_root}/${xwayland_private_dependency_package}"
    xwayland_repository_directory_host="/target${xwayland_repository_directory}"
    install -d -m 0700 "$xwayland_repository_directory_host"
    desktop_xwayland_download_repository_deb \
      "$xwayland_private_dependency_package" \
      "$XWAYLAND_TARGET_ARCHITECTURE" \
      "$xwayland_repository_directory"
    xwayland_repository_deb_host=$(
      desktop_xwayland_find_single_repository_deb \
        "$xwayland_repository_directory_host" \
        "$xwayland_private_dependency_package" \
        "$xwayland_find_output"
    )
    case "$xwayland_repository_deb_host" in
      /target"$xwayland_repository_directory"/*.deb) ;;
      *)
        desktop_xwayland_fail \
          "private ${xwayland_private_dependency_package} package escaped its managed download directory"
        ;;
    esac
    xwayland_repository_deb=${xwayland_repository_deb_host#/target}
    desktop_xwayland_validate_repository_deb \
      "$xwayland_repository_deb" \
      "$xwayland_repository_deb_host" \
      "$xwayland_private_dependency_package" \
      "$XWAYLAND_TARGET_ARCHITECTURE"
    desktop_xwayland_extract_private_deb \
      "$xwayland_private_dependency_package" \
      "$xwayland_repository_deb" \
      "$xwayland_extract_dir"
  done
  unset \
    xwayland_private_dependency_library \
    xwayland_private_dependency_package \
    xwayland_private_dependency_spec \
    xwayland_repository_architecture \
    xwayland_repository_deb \
    xwayland_repository_deb_host \
    xwayland_repository_deb_size \
    xwayland_repository_directory \
    xwayland_repository_directory_host \
    xwayland_repository_entry_count \
    xwayland_repository_expected_architecture \
    xwayland_repository_expected_package \
    xwayland_repository_package \
    xwayland_repository_scan_output \
    xwayland_repository_version

  [ -f "$xwayland_extract_host/usr/bin/Xwayland" ] &&
    [ ! -L "$xwayland_extract_host/usr/bin/Xwayland" ] &&
    [ -x "$xwayland_extract_host/usr/bin/Xwayland" ] ||
    desktop_xwayland_fail "extracted private Xwayland runtime is missing usr/bin/Xwayland"
  [ -f "$xwayland_extract_host/usr/lib/xorg/protocol.txt" ] &&
    [ ! -L "$xwayland_extract_host/usr/lib/xorg/protocol.txt" ] &&
    [ -r "$xwayland_extract_host/usr/lib/xorg/protocol.txt" ] ||
    desktop_xwayland_fail "extracted private Xwayland runtime is missing usr/lib/xorg/protocol.txt"
  [ -f "$xwayland_extract_host/usr/bin/xkbcomp" ] &&
    [ ! -L "$xwayland_extract_host/usr/bin/xkbcomp" ] &&
    [ -x "$xwayland_extract_host/usr/bin/xkbcomp" ] ||
    desktop_xwayland_fail "extracted private Xwayland runtime is missing executable usr/bin/xkbcomp"

  xwayland_private_library_directory="${xwayland_extract_host}/usr/lib/x86_64-linux-gnu"
  desktop_xwayland_validate_extracted_library \
    "$xwayland_private_library_directory" \
    libxcb-cursor.so.0
  for xwayland_private_dependency_spec in $XWAYLAND_PRIVATE_DEPENDENCY_SPECS; do
    xwayland_private_dependency_library=${xwayland_private_dependency_spec#*:}
    desktop_xwayland_validate_extracted_library \
      "$xwayland_private_library_directory" \
      "$xwayland_private_dependency_library"
  done
  unset \
    xwayland_private_dependency_library \
    xwayland_private_dependency_spec \
    xwayland_private_library_directory \
    xwayland_private_library_name \
    xwayland_private_library_path \
    xwayland_private_library_target

  xwayland_special_member=$(
    desktop_xwayland_find_first_path \
      "unsupported special files" \
      "$xwayland_find_output" \
      "$xwayland_extract_host" -xdev \
      \( -type b -o -type c -o -type p -o -type s \) \
  )
  [ -z "$xwayland_special_member" ] ||
    desktop_xwayland_fail "private Xwayland packages contain an unsupported special file: ${xwayland_special_member}"
  xwayland_setid_member=$(
    desktop_xwayland_find_first_path \
      "set-ID files" \
      "$xwayland_find_output" \
      "$xwayland_extract_host" -xdev -type f -perm /6000
  )
  [ -z "$xwayland_setid_member" ] ||
    desktop_xwayland_fail "private Xwayland packages contain a set-ID file: ${xwayland_setid_member}"

  xwayland_unexpected_top_level=$(
    desktop_xwayland_find_first_path \
      "top-level entries" \
      "$xwayland_find_output" \
      "$xwayland_extract_host" -mindepth 1 -maxdepth 1 \
      ! -name usr \
      ! -name var
  )
  [ -z "$xwayland_unexpected_top_level" ] ||
    desktop_xwayland_fail "private Xwayland root contains a non-package top-level entry: ${xwayland_unexpected_top_level}"

  chown -R root:root "$xwayland_extract_host"
  chmod -R go-w "$xwayland_extract_host"
  xwayland_unsafe_xkbcomp=$(
    desktop_xwayland_find_first_path \
      "prepared xkbcomp ownership and mode" \
      "$xwayland_find_output" \
      "$xwayland_extract_host/usr/bin/xkbcomp" \
      \( ! -type f -o ! -user 0 -o ! -group 0 -o -perm /022 \)
  )
  [ -z "$xwayland_unsafe_xkbcomp" ] ||
    desktop_xwayland_fail "prepared private xkbcomp is not a root-owned regular file with a safe mode"

  desktop_xwayland_prepare_xkbcomp_overlay

  install -d -m 0755 /target/opt
  rm -rf -- "$xwayland_runtime_host"
  mv "$xwayland_extract_host" "$xwayland_runtime_host"

  rm -rf -- "$xwayland_work_host"
  desktop_xwayland_assert_public_runtime_absent
  unset \
    xwayland_find_output \
    xwayland_setid_member \
    xwayland_special_member \
    xwayland_unexpected_top_level \
    xwayland_unsafe_xkbcomp \
    xwayland_work_dir
}
