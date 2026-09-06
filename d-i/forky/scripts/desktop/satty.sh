#!/bin/sh
# Pinned Satty release installation helpers. This file is sourced, not executed.

desktop_satty_fail() {
  rm -rf -- "/target${satty_work_dir:-/tmp/invalid-satty-work-dir}" 2>/dev/null || true
  installer_fatal "$*"
}

desktop_satty_validate_unsigned_integer() {
  satty_value_name=$1
  satty_value=$2

  case "$satty_value" in
    ''|*[!0-9]*)
      installer_fatal "${satty_value_name} must be an unsigned integer"
      ;;
  esac
}

desktop_satty_validate_policy() {
  : "${LABWC_SATTY_VERSION:?LABWC_SATTY_VERSION must be set}"
  : "${LABWC_SATTY_ARCHITECTURE:?LABWC_SATTY_ARCHITECTURE must be set}"
  : "${LABWC_SATTY_URL:?LABWC_SATTY_URL must be set}"
  : "${LABWC_SATTY_SHA256:?LABWC_SATTY_SHA256 must be set}"
  : "${LABWC_SATTY_MINIMUM_BYTES:?LABWC_SATTY_MINIMUM_BYTES must be set}"
  : "${LABWC_SATTY_MAXIMUM_BYTES:?LABWC_SATTY_MAXIMUM_BYTES must be set}"
  : "${LABWC_SATTY_GLIBC_VERSION:?LABWC_SATTY_GLIBC_VERSION must be set}"
  : "${LABWC_SATTY_GLIBC_ARCHITECTURE:?LABWC_SATTY_GLIBC_ARCHITECTURE must be set}"
  : "${LABWC_SATTY_GLIBC_LIBC6_SHA256:?LABWC_SATTY_GLIBC_LIBC6_SHA256 must be set}"
  : "${LABWC_SATTY_GLIBC_GCONV_SHA256:?LABWC_SATTY_GLIBC_GCONV_SHA256 must be set}"
  : "${LABWC_SATTY_GLIBC_RUNTIME_ROOT:?LABWC_SATTY_GLIBC_RUNTIME_ROOT must be set}"
  : "${LABWC_SATTY_GLIBC_MINIMUM_BYTES:?LABWC_SATTY_GLIBC_MINIMUM_BYTES must be set}"
  : "${LABWC_SATTY_GLIBC_MAXIMUM_BYTES:?LABWC_SATTY_GLIBC_MAXIMUM_BYTES must be set}"
  : "${LABWC_SATTY_GLIBC_GCONV_MINIMUM_BYTES:?LABWC_SATTY_GLIBC_GCONV_MINIMUM_BYTES must be set}"
  : "${LABWC_SATTY_GLIBC_GCONV_MAXIMUM_BYTES:?LABWC_SATTY_GLIBC_GCONV_MAXIMUM_BYTES must be set}"

  case "$LABWC_SATTY_VERSION" in
    *[!0-9.]*|.*|*.|*..*)
      installer_fatal "LABWC_SATTY_VERSION is invalid: ${LABWC_SATTY_VERSION}"
      ;;
  esac
  case "$LABWC_SATTY_ARCHITECTURE" in
    amd64) ;;
    *)
      installer_fatal "LABWC_SATTY_ARCHITECTURE is unsupported: ${LABWC_SATTY_ARCHITECTURE}"
      ;;
  esac
  case "$LABWC_SATTY_URL" in
    "https://github.com/Satty-org/Satty/releases/download/v${LABWC_SATTY_VERSION}/satty-x86_64-unknown-linux-gnu.tar.gz") ;;
    *)
      installer_fatal "LABWC_SATTY_URL does not match the pinned Satty release contract"
      ;;
  esac
  case "$LABWC_SATTY_SHA256" in
    *[!0123456789abcdef]*|'')
      installer_fatal "LABWC_SATTY_SHA256 must contain lowercase hexadecimal characters"
      ;;
  esac
  [ "${#LABWC_SATTY_SHA256}" -eq 64 ] ||
    installer_fatal "LABWC_SATTY_SHA256 must contain 64 characters"

  desktop_satty_validate_unsigned_integer LABWC_SATTY_MINIMUM_BYTES "$LABWC_SATTY_MINIMUM_BYTES"
  desktop_satty_validate_unsigned_integer LABWC_SATTY_MAXIMUM_BYTES "$LABWC_SATTY_MAXIMUM_BYTES"
  [ "$LABWC_SATTY_MINIMUM_BYTES" -gt 0 ] ||
    installer_fatal "LABWC_SATTY_MINIMUM_BYTES must be greater than zero"
  [ "$LABWC_SATTY_MAXIMUM_BYTES" -ge "$LABWC_SATTY_MINIMUM_BYTES" ] ||
    installer_fatal "LABWC_SATTY_MAXIMUM_BYTES must not be smaller than LABWC_SATTY_MINIMUM_BYTES"

  [ "$LABWC_SATTY_GLIBC_VERSION" = 2.44-1 ] ||
    installer_fatal "LABWC_SATTY_GLIBC_VERSION must remain pinned to 2.44-1"
  [ "$LABWC_SATTY_GLIBC_ARCHITECTURE" = amd64 ] ||
    installer_fatal "LABWC_SATTY_GLIBC_ARCHITECTURE must remain pinned to amd64"
  case "$LABWC_SATTY_GLIBC_LIBC6_SHA256" in
    *[!0123456789abcdef]*|'')
      installer_fatal "LABWC_SATTY_GLIBC_LIBC6_SHA256 must contain lowercase hexadecimal characters"
      ;;
  esac
  [ "${#LABWC_SATTY_GLIBC_LIBC6_SHA256}" -eq 64 ] ||
    installer_fatal "LABWC_SATTY_GLIBC_LIBC6_SHA256 must contain 64 characters"
  [ "$LABWC_SATTY_GLIBC_LIBC6_SHA256" = 17d9a246ae46a457227c19a3d821c49d68b9c6f9531bfa6f52d9c064307de585 ] ||
    installer_fatal "LABWC_SATTY_GLIBC_LIBC6_SHA256 must remain pinned to the Debian 2.44-1 amd64 package"
  case "$LABWC_SATTY_GLIBC_GCONV_SHA256" in
    *[!0123456789abcdef]*|'')
      installer_fatal "LABWC_SATTY_GLIBC_GCONV_SHA256 must contain lowercase hexadecimal characters"
      ;;
  esac
  [ "${#LABWC_SATTY_GLIBC_GCONV_SHA256}" -eq 64 ] ||
    installer_fatal "LABWC_SATTY_GLIBC_GCONV_SHA256 must contain 64 characters"
  [ "$LABWC_SATTY_GLIBC_GCONV_SHA256" = 00408257a5287df51898bb5f71beca80a37f1b569c2ae6b977cb6b27de2929b2 ] ||
    installer_fatal "LABWC_SATTY_GLIBC_GCONV_SHA256 must remain pinned to the Debian 2.44-1 amd64 package"
  [ "$LABWC_SATTY_GLIBC_RUNTIME_ROOT" = /opt/glibc/2.44-1/satty ] ||
    installer_fatal "LABWC_SATTY_GLIBC_RUNTIME_ROOT must remain pinned to /opt/glibc/2.44-1/satty"
  desktop_satty_validate_unsigned_integer LABWC_SATTY_GLIBC_MINIMUM_BYTES "$LABWC_SATTY_GLIBC_MINIMUM_BYTES"
  desktop_satty_validate_unsigned_integer LABWC_SATTY_GLIBC_MAXIMUM_BYTES "$LABWC_SATTY_GLIBC_MAXIMUM_BYTES"
  [ "$LABWC_SATTY_GLIBC_MINIMUM_BYTES" -gt 0 ] ||
    installer_fatal "LABWC_SATTY_GLIBC_MINIMUM_BYTES must be greater than zero"
  [ "$LABWC_SATTY_GLIBC_MAXIMUM_BYTES" -ge "$LABWC_SATTY_GLIBC_MINIMUM_BYTES" ] ||
    installer_fatal "LABWC_SATTY_GLIBC_MAXIMUM_BYTES must not be smaller than LABWC_SATTY_GLIBC_MINIMUM_BYTES"
  desktop_satty_validate_unsigned_integer LABWC_SATTY_GLIBC_GCONV_MINIMUM_BYTES "$LABWC_SATTY_GLIBC_GCONV_MINIMUM_BYTES"
  desktop_satty_validate_unsigned_integer LABWC_SATTY_GLIBC_GCONV_MAXIMUM_BYTES "$LABWC_SATTY_GLIBC_GCONV_MAXIMUM_BYTES"
  [ "$LABWC_SATTY_GLIBC_GCONV_MINIMUM_BYTES" -gt 0 ] ||
    installer_fatal "LABWC_SATTY_GLIBC_GCONV_MINIMUM_BYTES must be greater than zero"
  [ "$LABWC_SATTY_GLIBC_GCONV_MAXIMUM_BYTES" -ge "$LABWC_SATTY_GLIBC_GCONV_MINIMUM_BYTES" ] ||
    installer_fatal "LABWC_SATTY_GLIBC_GCONV_MAXIMUM_BYTES must not be smaller than LABWC_SATTY_GLIBC_GCONV_MINIMUM_BYTES"
}

desktop_satty_preflight_target_architecture() {
  desktop_satty_validate_policy

  SATTY_TARGET_ARCHITECTURE=$(capture_in_target "detect target architecture for Satty" /usr/bin/dpkg --print-architecture)
  [ -n "$SATTY_TARGET_ARCHITECTURE" ] ||
    installer_fatal "target architecture detection returned no output before Satty installation"
  [ "$SATTY_TARGET_ARCHITECTURE" = "$LABWC_SATTY_ARCHITECTURE" ] ||
    installer_fatal "Satty ${LABWC_SATTY_VERSION} is pinned for ${LABWC_SATTY_ARCHITECTURE}, but the target architecture is ${SATTY_TARGET_ARCHITECTURE}"
}

desktop_satty_validate_private_deb() {
  satty_private_deb=$1
  satty_private_deb_host=$2
  satty_private_expected_package=$3
  satty_private_expected_version=$4
  satty_private_expected_architecture=$5
  satty_private_minimum_bytes=$6
  satty_private_maximum_bytes=$7
  satty_private_expected_sha256=$8

  [ -f "$satty_private_deb_host" ] && [ ! -L "$satty_private_deb_host" ] ||
    desktop_satty_fail "private Satty GLIBC download is missing package: ${satty_private_expected_package}"

  satty_private_deb_size=$(wc -c <"$satty_private_deb_host" | awk '{print $1}')
  desktop_satty_validate_unsigned_integer "downloaded ${satty_private_expected_package} package size" "$satty_private_deb_size"
  [ "$satty_private_deb_size" -ge "$satty_private_minimum_bytes" ] ||
    desktop_satty_fail "downloaded ${satty_private_expected_package} package is unexpectedly small: ${satty_private_deb_size} bytes"
  [ "$satty_private_deb_size" -le "$satty_private_maximum_bytes" ] ||
    desktop_satty_fail "downloaded ${satty_private_expected_package} package is unexpectedly large: ${satty_private_deb_size} bytes"

  satty_private_deb_sha256=$(
    capture_in_target "hash private ${satty_private_expected_package} package" /usr/bin/sha256sum "$satty_private_deb" |
      awk '{print $1}'
  )
  [ "$satty_private_deb_sha256" = "$satty_private_expected_sha256" ] ||
    desktop_satty_fail "downloaded ${satty_private_expected_package} package SHA-256 does not match the pinned Debian package"

  satty_private_package=$(capture_in_target "read private package name" /usr/bin/dpkg-deb -f "$satty_private_deb" Package)
  satty_private_version=$(capture_in_target "read private package version" /usr/bin/dpkg-deb -f "$satty_private_deb" Version)
  satty_private_architecture=$(capture_in_target "read private package architecture" /usr/bin/dpkg-deb -f "$satty_private_deb" Architecture)
  [ "$satty_private_package" = "$satty_private_expected_package" ] ||
    desktop_satty_fail "downloaded private package has unexpected Package: ${satty_private_package:-unset}"
  [ "$satty_private_version" = "$satty_private_expected_version" ] ||
    desktop_satty_fail "downloaded ${satty_private_expected_package} package has unexpected Version: ${satty_private_version:-unset}"
  [ "$satty_private_architecture" = "$satty_private_expected_architecture" ] ||
    desktop_satty_fail "downloaded ${satty_private_expected_package} package has unexpected Architecture: ${satty_private_architecture:-unset}"

  SATTY_PRIVATE_PACKAGE_SHA256=$satty_private_deb_sha256
}

desktop_satty_download_private_deb() {
  satty_private_download_name=$1
  satty_private_download_url=$2
  satty_private_download_path=$3
  satty_private_download_maximum_bytes=$4

  if ! attempt_in_target "download private Satty ${satty_private_download_name} package from Debian Snapshot" \
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
        --max-filesize "$satty_private_download_maximum_bytes" \
        --user-agent 'unattended-installer-satty/1.0' \
        --header 'Accept: application/vnd.debian.binary-package, application/octet-stream;q=0.9, */*;q=0.1' \
        --output "$satty_private_download_path" \
        --url "$satty_private_download_url"
  then
    desktop_satty_fail "failed to download private Satty ${satty_private_download_name} package from Debian Snapshot"
  fi
}

desktop_satty_install_private_glibc() {
  satty_glibc_work_dir="${satty_work_dir}/glibc"
  satty_glibc_extract_dir="${satty_glibc_work_dir}/extract"
  satty_glibc_work_host="/target${satty_glibc_work_dir}"
  satty_glibc_extract_host="/target${satty_glibc_extract_dir}"
  satty_glibc_runtime_host="/target${LABWC_SATTY_GLIBC_RUNTIME_ROOT}"
  satty_glibc_deb="${satty_glibc_work_dir}/libc6_${LABWC_SATTY_GLIBC_VERSION}_${LABWC_SATTY_GLIBC_ARCHITECTURE}.deb"
  satty_glibc_deb_host="/target${satty_glibc_deb}"
  satty_glibc_gconv_deb="${satty_glibc_work_dir}/libc-gconv-modules-extra_${LABWC_SATTY_GLIBC_VERSION}_${LABWC_SATTY_GLIBC_ARCHITECTURE}.deb"
  satty_glibc_gconv_deb_host="/target${satty_glibc_gconv_deb}"
  satty_glibc_snapshot_base=https://snapshot.debian.org/archive/debian/20260810T202458Z/pool/main/g/glibc
  satty_glibc_deb_url="${satty_glibc_snapshot_base}/libc6_${LABWC_SATTY_GLIBC_VERSION}_${LABWC_SATTY_GLIBC_ARCHITECTURE}.deb"
  satty_glibc_gconv_deb_url="${satty_glibc_snapshot_base}/libc-gconv-modules-extra_${LABWC_SATTY_GLIBC_VERSION}_${LABWC_SATTY_GLIBC_ARCHITECTURE}.deb"

  satty_libgcc_status=$(capture_in_target "check target libgcc runtime before private GLIBC installation" /usr/bin/dpkg-query -W -f='${Status}' libgcc-s1)
  [ "$satty_libgcc_status" = "install ok installed" ] ||
    desktop_satty_fail "target libgcc-s1 runtime is not installed"

  install -d -m 0700 "$satty_glibc_work_host"
  desktop_satty_download_private_deb \
    libc6 \
    "$satty_glibc_deb_url" \
    "$satty_glibc_deb" \
    "$LABWC_SATTY_GLIBC_MAXIMUM_BYTES"
  desktop_satty_download_private_deb \
    libc-gconv-modules-extra \
    "$satty_glibc_gconv_deb_url" \
    "$satty_glibc_gconv_deb" \
    "$LABWC_SATTY_GLIBC_GCONV_MAXIMUM_BYTES"

  desktop_satty_validate_private_deb \
    "$satty_glibc_deb" \
    "$satty_glibc_deb_host" \
    libc6 \
    "$LABWC_SATTY_GLIBC_VERSION" \
    "$LABWC_SATTY_GLIBC_ARCHITECTURE" \
    "$LABWC_SATTY_GLIBC_MINIMUM_BYTES" \
    "$LABWC_SATTY_GLIBC_MAXIMUM_BYTES" \
    "$LABWC_SATTY_GLIBC_LIBC6_SHA256"
  satty_glibc_deb_sha256=$SATTY_PRIVATE_PACKAGE_SHA256

  desktop_satty_validate_private_deb \
    "$satty_glibc_gconv_deb" \
    "$satty_glibc_gconv_deb_host" \
    libc-gconv-modules-extra \
    "$LABWC_SATTY_GLIBC_VERSION" \
    "$LABWC_SATTY_GLIBC_ARCHITECTURE" \
    "$LABWC_SATTY_GLIBC_GCONV_MINIMUM_BYTES" \
    "$LABWC_SATTY_GLIBC_GCONV_MAXIMUM_BYTES" \
    "$LABWC_SATTY_GLIBC_GCONV_SHA256"
  satty_glibc_gconv_deb_sha256=$SATTY_PRIVATE_PACKAGE_SHA256

  satty_glibc_depends=$(capture_in_target "read private libc6 dependencies" /usr/bin/dpkg-deb -f "$satty_glibc_deb" Depends)
  case "$satty_glibc_depends" in
    *"libgcc-s1"*) ;;
    *) desktop_satty_fail "downloaded libc6 package no longer declares libgcc-s1" ;;
  esac
  case "$satty_glibc_depends" in
    *"libc-gconv-modules-extra (= ${LABWC_SATTY_GLIBC_VERSION})"*) ;;
    *) desktop_satty_fail "downloaded libc6 package has an unexpected gconv dependency: ${satty_glibc_depends}" ;;
  esac

  install -d -m 0700 "$satty_glibc_extract_host"
  if ! attempt_in_target "extract private Satty GLIBC runtime" \
    /usr/bin/dpkg-deb -x "$satty_glibc_deb" "$satty_glibc_extract_dir"
  then
    desktop_satty_fail "failed to extract the private Satty GLIBC runtime"
  fi
  if ! attempt_in_target "extract private Satty GLIBC gconv modules" \
    /usr/bin/dpkg-deb -x "$satty_glibc_gconv_deb" "$satty_glibc_extract_dir"
  then
    desktop_satty_fail "failed to extract the private Satty GLIBC gconv modules"
  fi

  satty_glibc_loader=
  for satty_glibc_loader_candidate in \
    "$satty_glibc_extract_host/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2" \
    "$satty_glibc_extract_host/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2" \
    "$satty_glibc_extract_host/lib64/ld-linux-x86-64.so.2"
  do
    if [ -x "$satty_glibc_loader_candidate" ]; then
      satty_glibc_loader=$satty_glibc_loader_candidate
      break
    fi
  done
  [ -n "$satty_glibc_loader" ] ||
    desktop_satty_fail "extracted private GLIBC runtime is missing the amd64 loader"

  install -d -m 0755 /target/opt/glibc/2.44-1
  rm -rf -- "$satty_glibc_runtime_host"
  mv "$satty_glibc_extract_host" "$satty_glibc_runtime_host"
  chown -R root:root "$satty_glibc_runtime_host"
  chmod -R go-w "$satty_glibc_runtime_host"
  printf 'package=libc6\nversion=%s\narchitecture=%s\nlibc6_sha256=%s\ngconv_sha256=%s\n' \
    "$LABWC_SATTY_GLIBC_VERSION" \
    "$LABWC_SATTY_GLIBC_ARCHITECTURE" \
    "$satty_glibc_deb_sha256" \
    "$satty_glibc_gconv_deb_sha256" \
    >"${satty_glibc_runtime_host}/.managed-release"
  chmod 0644 "${satty_glibc_runtime_host}/.managed-release"
  SATTY_GLIBC_PACKAGE_SHA256=$satty_glibc_deb_sha256
  SATTY_GLIBC_GCONV_PACKAGE_SHA256=$satty_glibc_gconv_deb_sha256
}

desktop_install_satty() {
  [ -n "${SATTY_TARGET_ARCHITECTURE:-}" ] || desktop_satty_preflight_target_architecture
  target_architecture=$SATTY_TARGET_ARCHITECTURE

  satty_work_dir="/tmp/satty-install.$$"
  satty_archive="${satty_work_dir}/satty.tar.gz"
  satty_extract_dir="${satty_work_dir}/extract"
  satty_archive_host="/target${satty_archive}"
  satty_extract_host="/target${satty_extract_dir}"

  rm -rf -- "/target${satty_work_dir}"
  install -d -m 0700 "$satty_extract_host"

  if ! attempt_in_target "download pinned Satty release" \
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
        --max-redirs 8 \
        --retry 3 \
        --retry-all-errors \
        --max-filesize "$LABWC_SATTY_MAXIMUM_BYTES" \
        --user-agent 'unattended-installer-satty/1.0' \
        --header 'Accept: application/gzip, application/octet-stream;q=0.9, */*;q=0.1' \
        --output "$satty_archive" \
        --url "$LABWC_SATTY_URL"
  then
    desktop_satty_fail "Satty ${LABWC_SATTY_VERSION} download failed"
  fi

  [ -f "$satty_archive_host" ] && [ ! -L "$satty_archive_host" ] ||
    desktop_satty_fail "downloaded Satty archive is not a regular file"
  satty_archive_size=$(wc -c <"$satty_archive_host" | awk '{print $1}')
  desktop_satty_validate_unsigned_integer "downloaded Satty archive size" "$satty_archive_size"
  [ "$satty_archive_size" -ge "$LABWC_SATTY_MINIMUM_BYTES" ] ||
    desktop_satty_fail "downloaded Satty archive is unexpectedly small: ${satty_archive_size} bytes"
  [ "$satty_archive_size" -le "$LABWC_SATTY_MAXIMUM_BYTES" ] ||
    desktop_satty_fail "downloaded Satty archive is unexpectedly large: ${satty_archive_size} bytes"

  satty_archive_sha256=$(
    capture_in_target "hash downloaded Satty archive" /usr/bin/sha256sum "$satty_archive" |
      awk '{print $1}'
  )
  [ "$satty_archive_sha256" = "$LABWC_SATTY_SHA256" ] ||
    desktop_satty_fail "downloaded Satty archive SHA-256 does not match the pinned release"

  satty_member_list=$(capture_in_target "list downloaded Satty archive" /bin/tar -tzf "$satty_archive")
  if ! printf '%s\n' "$satty_member_list" |
    awk '
      /^\// { bad = 1 }
      /(^|\/)\.\.($|\/)/ { bad = 1 }
      END { exit bad ? 1 : 0 }
    '
  then
    desktop_satty_fail "downloaded Satty archive contains an unsafe member path"
  fi
  satty_verbose_member_list=$(capture_in_target "inspect downloaded Satty archive types" /bin/tar -tvzf "$satty_archive")
  if ! printf '%s\n' "$satty_verbose_member_list" |
    awk '$1 !~ /^[-d]/ { bad = 1 } END { exit bad ? 1 : 0 }'
  then
    desktop_satty_fail "downloaded Satty archive contains unsupported member types"
  fi

  for satty_required_member in \
    ./LICENSE \
    ./README.md \
    ./assets/satty.svg \
    ./completions/_satty \
    ./completions/satty.bash \
    ./completions/satty.fish \
    ./man/satty.1 \
    ./satty \
    ./satty.desktop
  do
    printf '%s\n' "$satty_member_list" | grep -Fqx "$satty_required_member" ||
      desktop_satty_fail "downloaded Satty archive is missing ${satty_required_member}"
  done

  if ! attempt_in_target "extract pinned Satty archive" \
    /bin/tar \
      --no-same-owner \
      --no-same-permissions \
      -xzf "$satty_archive" \
      -C "$satty_extract_dir"
  then
    desktop_satty_fail "failed to extract the pinned Satty archive"
  fi

  [ -x "$satty_extract_host/satty" ] ||
    desktop_satty_fail "extracted Satty binary is not executable"
  satty_file_type=$(capture_in_target "inspect extracted Satty binary" /usr/bin/file -b "${satty_extract_dir}/satty")
  case "$satty_file_type" in
    *"ELF 64-bit"*"x86-64"*) ;;
    *)
      desktop_satty_fail "extracted Satty binary has an unexpected file type: ${satty_file_type:-unset}"
      ;;
  esac

  install -d -m 0755 \
    /target/usr/local/libexec/satty \
    /target/usr/local/share/applications \
    /target/usr/local/share/bash-completion/completions \
    /target/usr/local/share/doc/satty \
    /target/usr/local/share/fish/vendor_completions.d \
    /target/usr/local/share/man/man1 \
    /target/usr/local/share/satty/completions \
    /target/usr/local/share/zsh/site-functions \
    /target/usr/share/icons/hicolor/scalable/apps
  install -m 0755 "$satty_extract_host/satty" /target/usr/local/libexec/satty/satty
  install -m 0644 "$satty_extract_host/satty.desktop" /target/usr/local/share/applications/satty.desktop
  install -m 0644 "$satty_extract_host/assets/satty.svg" /target/usr/share/icons/hicolor/scalable/apps/satty.svg
  install -m 0644 "$satty_extract_host/man/satty.1" /target/usr/local/share/man/man1/satty.1
  install -m 0644 "$satty_extract_host/completions/satty.bash" /target/usr/local/share/bash-completion/completions/satty
  install -m 0644 "$satty_extract_host/completions/_satty" /target/usr/local/share/zsh/site-functions/_satty
  install -m 0644 "$satty_extract_host/completions/satty.fish" /target/usr/local/share/fish/vendor_completions.d/satty.fish
  install -m 0644 "$satty_extract_host"/completions/* /target/usr/local/share/satty/completions/
  install -m 0644 "$satty_extract_host/LICENSE" /target/usr/local/share/doc/satty/LICENSE
  install -m 0644 "$satty_extract_host/README.md" /target/usr/local/share/doc/satty/README.md

  desktop_satty_install_private_glibc
  desktop_stage_role_asset usr/local/bin/satty /usr/local/bin/satty 0755

  printf 'version=%s\nurl=%s\narchive_sha256=%s\nglibc_version=%s\nglibc_package_sha256=%s\nglibc_gconv_package_sha256=%s\n' \
    "$LABWC_SATTY_VERSION" \
    "$LABWC_SATTY_URL" \
    "$LABWC_SATTY_SHA256" \
    "$LABWC_SATTY_GLIBC_VERSION" \
    "$SATTY_GLIBC_PACKAGE_SHA256" \
    "$SATTY_GLIBC_GCONV_PACKAGE_SHA256" \
    >/target/usr/local/share/satty/release
  chmod 0644 /target/usr/local/share/satty/release

  run_in_target "refresh Satty desktop metadata" /bin/sh -eu -c '
/usr/bin/update-desktop-database /usr/local/share/applications
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f -q /usr/share/icons/hicolor
fi
' sh

  rm -rf -- "/target${satty_work_dir}"
  desktop_log "installed_satty version=${LABWC_SATTY_VERSION} architecture=${target_architecture} archive_sha256=${LABWC_SATTY_SHA256} private_glibc=${LABWC_SATTY_GLIBC_VERSION} glibc_package_sha256=${SATTY_GLIBC_PACKAGE_SHA256} glibc_gconv_package_sha256=${SATTY_GLIBC_GCONV_PACKAGE_SHA256}"
}
