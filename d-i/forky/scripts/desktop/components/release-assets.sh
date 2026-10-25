#!/bin/sh
# Verified release archives used by the desktop role.

desktop_validate_release_pin() {
  release_label=$1
  release_tag=$2
  release_url=$3
  release_sha256=$4
  release_filename=$5

  case "$release_tag" in
    themes-v[0-9]*.[0-9]*.[0-9]*) ;;
    *) installer_fatal "${release_label} release tag is invalid: ${release_tag:-unset}" ;;
  esac
  [ "$release_url" = "https://github.com/mjcramerz/themes/releases/download/${release_tag}/${release_filename}" ] ||
    installer_fatal "${release_label} release URL does not match its pinned tag and filename"
  [ "${#release_sha256}" -eq 64 ] ||
    installer_fatal "${release_label} release SHA-256 must contain 64 hexadecimal characters"
  case "$release_sha256" in
    *[!0123456789abcdef]*)
      installer_fatal "${release_label} release SHA-256 is not lowercase hexadecimal" ;;
  esac
}

desktop_download_release_archive() (
  set -eu
  release_label=$1
  release_tag=$2
  release_url=$3
  release_sha256=$4
  release_filename=$5
  destination=$6
  maximum_bytes=$7

  desktop_validate_release_pin "$release_label" "$release_tag" "$release_url" \
    "$release_sha256" "$release_filename"
  case "$maximum_bytes" in
    ''|*[!0123456789]*|0) installer_fatal "${release_label} release byte limit is invalid" ;;
  esac
  source_fetch_external "${release_url%/*}" "${release_url##*/}" "$destination" 0600 ||
    installer_fatal "failed to download ${release_label} release archive"
  [ -f "$destination" ] && [ ! -L "$destination" ] ||
    installer_fatal "downloaded ${release_label} release archive is not a regular file"

  release_bytes=$(wc -c <"$destination" 2>/dev/null || true)
  release_bytes=${release_bytes##* }
  case "$release_bytes" in
    ''|*[!0123456789]*|0) installer_fatal "${release_label} release archive size is invalid" ;;
  esac
  [ "$release_bytes" -le "$maximum_bytes" ] ||
    installer_fatal "${release_label} release archive exceeds ${maximum_bytes} bytes"
  release_actual_sha256=$(sha256sum "$destination" | awk '{print $1}')
  [ "$release_actual_sha256" = "$release_sha256" ] ||
    installer_fatal "${release_label} release archive SHA-256 mismatch"
  desktop_log "downloaded_verified_release label=${release_label} tag=${release_tag} bytes=${release_bytes} sha256=${release_sha256}"
)
