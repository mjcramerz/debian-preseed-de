#!/bin/sh
# Google Android SDK Platform-Tools installation for the managed desktop role.

desktop_android_platform_tools_fail() {
  installer_fatal "Android SDK Platform-Tools: $*"
}

desktop_android_platform_tools_validate_unsigned_integer() {
  value_name=$1
  value=$2

  case "$value" in
    ''|*[!0123456789]*)
      desktop_android_platform_tools_fail "${value_name} must be an unsigned integer"
      ;;
  esac
}

desktop_android_platform_tools_validate_policy() {
  : "${ANDROID_PLATFORM_TOOLS_ARCHITECTURE:?ANDROID_PLATFORM_TOOLS_ARCHITECTURE must be set}"
  : "${ANDROID_PLATFORM_TOOLS_URL:?ANDROID_PLATFORM_TOOLS_URL must be set}"
  : "${ANDROID_PLATFORM_TOOLS_MINIMUM_BYTES:?ANDROID_PLATFORM_TOOLS_MINIMUM_BYTES must be set}"
  : "${ANDROID_PLATFORM_TOOLS_MAXIMUM_BYTES:?ANDROID_PLATFORM_TOOLS_MAXIMUM_BYTES must be set}"
  : "${ANDROID_PLATFORM_TOOLS_MAXIMUM_EXTRACTED_BYTES:?ANDROID_PLATFORM_TOOLS_MAXIMUM_EXTRACTED_BYTES must be set}"
  : "${ANDROID_PLATFORM_TOOLS_MAXIMUM_MEMBERS:?ANDROID_PLATFORM_TOOLS_MAXIMUM_MEMBERS must be set}"

  [ "$ANDROID_PLATFORM_TOOLS_ARCHITECTURE" = amd64 ] ||
    desktop_android_platform_tools_fail \
      "Google's Linux Platform-Tools archive is unsupported for ${ANDROID_PLATFORM_TOOLS_ARCHITECTURE}"
  [ "$ANDROID_PLATFORM_TOOLS_URL" = "https://dl.google.com/android/repository/platform-tools-latest-linux.zip" ] ||
    desktop_android_platform_tools_fail "download URL must remain the official Google latest Linux archive"

  desktop_android_platform_tools_validate_unsigned_integer \
    ANDROID_PLATFORM_TOOLS_MINIMUM_BYTES \
    "$ANDROID_PLATFORM_TOOLS_MINIMUM_BYTES"
  desktop_android_platform_tools_validate_unsigned_integer \
    ANDROID_PLATFORM_TOOLS_MAXIMUM_BYTES \
    "$ANDROID_PLATFORM_TOOLS_MAXIMUM_BYTES"
  desktop_android_platform_tools_validate_unsigned_integer \
    ANDROID_PLATFORM_TOOLS_MAXIMUM_EXTRACTED_BYTES \
    "$ANDROID_PLATFORM_TOOLS_MAXIMUM_EXTRACTED_BYTES"
  desktop_android_platform_tools_validate_unsigned_integer \
    ANDROID_PLATFORM_TOOLS_MAXIMUM_MEMBERS \
    "$ANDROID_PLATFORM_TOOLS_MAXIMUM_MEMBERS"

  [ "$ANDROID_PLATFORM_TOOLS_MINIMUM_BYTES" -ge 1000000 ] ||
    desktop_android_platform_tools_fail "minimum archive size is too small"
  [ "$ANDROID_PLATFORM_TOOLS_MAXIMUM_BYTES" -ge "$ANDROID_PLATFORM_TOOLS_MINIMUM_BYTES" ] ||
    desktop_android_platform_tools_fail "maximum archive size is smaller than the minimum"
  [ "$ANDROID_PLATFORM_TOOLS_MAXIMUM_EXTRACTED_BYTES" -ge "$ANDROID_PLATFORM_TOOLS_MAXIMUM_BYTES" ] ||
    desktop_android_platform_tools_fail "maximum extracted size is smaller than the archive ceiling"
  [ "$ANDROID_PLATFORM_TOOLS_MAXIMUM_MEMBERS" -ge 12 ] ||
    desktop_android_platform_tools_fail "archive member ceiling is too small"
}

desktop_android_platform_tools_preflight_target_architecture() {
  desktop_android_platform_tools_validate_policy

  ANDROID_PLATFORM_TOOLS_TARGET_ARCHITECTURE=$(
    capture_in_target \
      "detect target architecture for Google Android SDK Platform-Tools" \
      /usr/bin/dpkg --print-architecture
  )
  [ -n "$ANDROID_PLATFORM_TOOLS_TARGET_ARCHITECTURE" ] ||
    desktop_android_platform_tools_fail "target architecture detection returned no output"
  [ "$ANDROID_PLATFORM_TOOLS_TARGET_ARCHITECTURE" = "$ANDROID_PLATFORM_TOOLS_ARCHITECTURE" ] ||
    desktop_android_platform_tools_fail \
      "official Google Linux Platform-Tools require ${ANDROID_PLATFORM_TOOLS_ARCHITECTURE}, but the target architecture is ${ANDROID_PLATFORM_TOOLS_TARGET_ARCHITECTURE}"
}

desktop_android_platform_tools_validate_revision() {
  revision=$1

  printf '%s\n' "$revision" |
    awk -F. '
      NF < 2 || NF > 4 { exit 1 }
      {
        for (field = 1; field <= NF; field++) {
          if ($field !~ /^[0-9]+$/) {
            exit 1
          }
        }
      }
    ' ||
    desktop_android_platform_tools_fail "downloaded archive has an invalid Pkg.Revision: ${revision:-unset}"
}

desktop_install_android_platform_tools() {
  [ -n "${ANDROID_PLATFORM_TOOLS_TARGET_ARCHITECTURE:-}" ] ||
    desktop_android_platform_tools_preflight_target_architecture

  platform_tools_work_dir="/tmp/android-platform-tools-install.$$"
  platform_tools_archive="${platform_tools_work_dir}/platform-tools.zip"
  platform_tools_extract_dir="${platform_tools_work_dir}/extract"
  platform_tools_archive_host="/target${platform_tools_archive}"
  platform_tools_extract_host="/target${platform_tools_extract_dir}"
  platform_tools_source_host="${platform_tools_extract_host}/platform-tools/source.properties"
  platform_tools_install_root_host="/target/usr/local/lib/android-sdk"
  platform_tools_install_host="${platform_tools_install_root_host}/platform-tools"
  platform_tools_staged_host="${platform_tools_install_root_host}/.platform-tools.new.$$"

  rm -rf -- "/target${platform_tools_work_dir}" "$platform_tools_staged_host"
  install -d -m 0700 "$platform_tools_extract_host"

  if ! attempt_in_target "download latest Google Android SDK Platform-Tools" \
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
        --max-time 300 \
        --max-redirs 4 \
        --retry 3 \
        --retry-all-errors \
        --max-filesize "$ANDROID_PLATFORM_TOOLS_MAXIMUM_BYTES" \
        --user-agent 'unattended-installer-android-platform-tools/1.0' \
        --header 'Accept: application/zip, application/octet-stream;q=0.9, */*;q=0.1' \
        --output "$platform_tools_archive" \
        --url "$ANDROID_PLATFORM_TOOLS_URL"
  then
    desktop_android_platform_tools_fail "latest Google archive download failed"
  fi

  [ -f "$platform_tools_archive_host" ] && [ ! -L "$platform_tools_archive_host" ] ||
    desktop_android_platform_tools_fail "downloaded archive is not a regular file"
  platform_tools_archive_size=$(wc -c <"$platform_tools_archive_host" | awk '{print $1}')
  desktop_android_platform_tools_validate_unsigned_integer \
    "downloaded archive size" \
    "$platform_tools_archive_size"
  [ "$platform_tools_archive_size" -ge "$ANDROID_PLATFORM_TOOLS_MINIMUM_BYTES" ] ||
    desktop_android_platform_tools_fail \
      "downloaded archive is unexpectedly small: ${platform_tools_archive_size} bytes"
  [ "$platform_tools_archive_size" -le "$ANDROID_PLATFORM_TOOLS_MAXIMUM_BYTES" ] ||
    desktop_android_platform_tools_fail \
      "downloaded archive is unexpectedly large: ${platform_tools_archive_size} bytes"

  platform_tools_archive_sha256=$(
    capture_in_target \
      "hash downloaded Google Android SDK Platform-Tools archive" \
      /usr/bin/sha256sum "$platform_tools_archive" |
      awk '{print $1}'
  )
  case "$platform_tools_archive_sha256" in
    *[!0123456789abcdef]*|'')
      desktop_android_platform_tools_fail "downloaded archive SHA-256 is invalid"
      ;;
  esac
  [ "${#platform_tools_archive_sha256}" -eq 64 ] ||
    desktop_android_platform_tools_fail "downloaded archive SHA-256 has an invalid length"

  platform_tools_member_list=$(
    capture_in_target \
      "list downloaded Google Android SDK Platform-Tools archive" \
      /usr/bin/unzip -Z1 "$platform_tools_archive"
  )
  if ! printf '%s\n' "$platform_tools_member_list" |
    awk '
      !NF { bad = 1 }
      /^\// { bad = 1 }
      /\\/ { bad = 1 }
      /(^|\/)\.\.($|\/)/ { bad = 1 }
      $0 !~ /^platform-tools\// { bad = 1 }
      seen[$0]++ { bad = 1 }
      END { exit bad ? 1 : 0 }
    '
  then
    desktop_android_platform_tools_fail "downloaded archive contains an unsafe member path"
  fi

  platform_tools_member_count=$(printf '%s\n' "$platform_tools_member_list" | awk 'NF { count++ } END { print count + 0 }')
  desktop_android_platform_tools_validate_unsigned_integer \
    "downloaded archive member count" \
    "$platform_tools_member_count"
  [ "$platform_tools_member_count" -le "$ANDROID_PLATFORM_TOOLS_MAXIMUM_MEMBERS" ] ||
    desktop_android_platform_tools_fail \
      "downloaded archive contains too many members: ${platform_tools_member_count}"

  for platform_tools_required_member in \
    platform-tools/NOTICE.txt \
    platform-tools/adb \
    platform-tools/fastboot \
    platform-tools/lib64/libc++.so \
    platform-tools/source.properties
  do
    printf '%s\n' "$platform_tools_member_list" |
      grep -Fqx "$platform_tools_required_member" ||
      desktop_android_platform_tools_fail \
        "downloaded archive is missing ${platform_tools_required_member}"
  done

  if ! attempt_in_target "extract latest Google Android SDK Platform-Tools archive" \
    /usr/bin/unzip \
      -q \
      "$platform_tools_archive" \
      -d "$platform_tools_extract_dir"
  then
    desktop_android_platform_tools_fail "failed to extract the downloaded archive"
  fi

  [ -d "${platform_tools_extract_host}/platform-tools" ] &&
    [ ! -L "${platform_tools_extract_host}/platform-tools" ] ||
    desktop_android_platform_tools_fail "extracted platform-tools directory is invalid"
  unsupported_platform_tools_node=$(
    find "${platform_tools_extract_host}/platform-tools" \
      -mindepth 1 \
      ! -type f \
      ! -type d \
      -print |
      sed -n '1p'
  )
  [ -z "$unsupported_platform_tools_node" ] ||
    desktop_android_platform_tools_fail \
      "downloaded archive extracted an unsupported node: ${unsupported_platform_tools_node}"

  platform_tools_extracted_kib=$(
    desktop_target_tree_size_kib \
      "measure extracted Google Android SDK Platform-Tools size" \
      "${platform_tools_extract_dir}/platform-tools"
  )
  desktop_android_platform_tools_validate_unsigned_integer \
    "extracted archive size" \
    "$platform_tools_extracted_kib"
  platform_tools_extracted_bytes=$((platform_tools_extracted_kib * 1024))
  [ "$platform_tools_extracted_bytes" -le "$ANDROID_PLATFORM_TOOLS_MAXIMUM_EXTRACTED_BYTES" ] ||
    desktop_android_platform_tools_fail \
      "downloaded archive expands beyond the managed size ceiling: ${platform_tools_extracted_bytes} bytes"

  [ -r "$platform_tools_source_host" ] && [ ! -L "$platform_tools_source_host" ] ||
    desktop_android_platform_tools_fail "extracted source.properties is invalid"
  platform_tools_revision=$(
    sed -n 's/^Pkg\.Revision=//p' "$platform_tools_source_host"
  )
  [ "$(printf '%s\n' "$platform_tools_revision" | awk 'NF { count++ } END { print count + 0 }')" -eq 1 ] ||
    desktop_android_platform_tools_fail "extracted source.properties must contain one Pkg.Revision"
  desktop_android_platform_tools_validate_revision "$platform_tools_revision"

  for platform_tools_binary in adb fastboot; do
    platform_tools_binary_host="${platform_tools_extract_host}/platform-tools/${platform_tools_binary}"
    [ -f "$platform_tools_binary_host" ] &&
      [ ! -L "$platform_tools_binary_host" ] &&
      [ -x "$platform_tools_binary_host" ] ||
      desktop_android_platform_tools_fail \
        "extracted ${platform_tools_binary} binary is invalid"
    platform_tools_file_type=$(
      capture_in_target \
        "inspect extracted Google ${platform_tools_binary} binary" \
        /usr/bin/file -b "${platform_tools_extract_dir}/platform-tools/${platform_tools_binary}"
    )
    case "$platform_tools_file_type" in
      *"ELF 64-bit"*"x86-64"*) ;;
      *)
        desktop_android_platform_tools_fail \
          "extracted ${platform_tools_binary} has an unexpected file type: ${platform_tools_file_type:-unset}"
        ;;
    esac
  done

  install -d -m 0755 "$platform_tools_install_root_host" /target/usr/local/bin
  cp -a "${platform_tools_extract_host}/platform-tools" "$platform_tools_staged_host"
  chown -R root:root "$platform_tools_staged_host"
  find "$platform_tools_staged_host" -type d -exec chmod 0755 {} \;
  find "$platform_tools_staged_host" -type f -exec chmod 0644 {} \;
  for platform_tools_binary in \
    adb \
    etc1tool \
    fastboot \
    hprof-conv \
    make_f2fs \
    make_f2fs_casefold \
    mke2fs \
    sqlite3
  do
    if [ -f "${platform_tools_staged_host}/${platform_tools_binary}" ]; then
      chmod 0755 "${platform_tools_staged_host}/${platform_tools_binary}"
    fi
  done

  cat >"${platform_tools_staged_host}/.managed-release" <<EOF
version=${platform_tools_revision}
url=${ANDROID_PLATFORM_TOOLS_URL}
archive_sha256=${platform_tools_archive_sha256}
architecture=${ANDROID_PLATFORM_TOOLS_TARGET_ARCHITECTURE}
EOF
  chmod 0644 "${platform_tools_staged_host}/.managed-release"

  [ ! -L "$platform_tools_install_host" ] ||
    desktop_android_platform_tools_fail "managed installation path must not be a symlink"
  rm -rf -- "$platform_tools_install_host"
  mv "$platform_tools_staged_host" "$platform_tools_install_host"
  ln -sfn ../lib/android-sdk/platform-tools/adb /target/usr/local/bin/adb
  ln -sfn ../lib/android-sdk/platform-tools/fastboot /target/usr/local/bin/fastboot

  rm -rf -- "/target${platform_tools_work_dir}"
  desktop_log \
    "installed_android_platform_tools version=${platform_tools_revision} architecture=${ANDROID_PLATFORM_TOOLS_TARGET_ARCHITECTURE} archive_sha256=${platform_tools_archive_sha256}"
}
