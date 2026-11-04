#!/bin/sh
# Install the profile-pinned official scrcpy release for managed ADB actions.

desktop_scrcpy_fail() {
  installer_fatal "scrcpy: $*"
}

desktop_scrcpy_validate_policy() {
  : "${SCRCPY_VERSION:?SCRCPY_VERSION must be set}"
  : "${SCRCPY_TAG:?SCRCPY_TAG must be set}"
  : "${SCRCPY_ARCHITECTURE:?SCRCPY_ARCHITECTURE must be set}"
  : "${SCRCPY_URL:?SCRCPY_URL must be set}"
  : "${SCRCPY_SHA256:?SCRCPY_SHA256 must be set}"
  : "${SCRCPY_SERVER_SHA256:?SCRCPY_SERVER_SHA256 must be set}"
  : "${SCRCPY_MAXIMUM_BYTES:?SCRCPY_MAXIMUM_BYTES must be set}"
  : "${SCRCPY_MAXIMUM_EXTRACTED_BYTES:?SCRCPY_MAXIMUM_EXTRACTED_BYTES must be set}"
  : "${SCRCPY_MAXIMUM_MEMBERS:?SCRCPY_MAXIMUM_MEMBERS must be set}"

  [ "$SCRCPY_ARCHITECTURE" = amd64 ] ||
    desktop_scrcpy_fail "the pinned Linux x86-64 release requires an amd64 target"
  [ "$SCRCPY_TAG" = "v${SCRCPY_VERSION}" ] ||
    desktop_scrcpy_fail "release tag must match the pinned version"
  [ "$SCRCPY_URL" = "https://github.com/Genymobile/scrcpy/releases/download/${SCRCPY_TAG}/scrcpy-linux-x86_64-${SCRCPY_TAG}.tar.gz" ] ||
    desktop_scrcpy_fail "download URL must remain the official GitHub release archive"
  case "$SCRCPY_SHA256" in
    ''|*[!0123456789abcdef]*)
      desktop_scrcpy_fail "archive SHA-256 must be 64 lowercase hexadecimal characters"
      ;;
  esac
  [ "${#SCRCPY_SHA256}" -eq 64 ] ||
    desktop_scrcpy_fail "archive SHA-256 must be 64 lowercase hexadecimal characters"
  case "$SCRCPY_SERVER_SHA256" in
    ''|*[!0123456789abcdef]*)
      desktop_scrcpy_fail "server SHA-256 must be lowercase hexadecimal characters"
      ;;
  esac
  [ "${#SCRCPY_SERVER_SHA256}" -eq 64 ] ||
    desktop_scrcpy_fail "server SHA-256 must be 64 lowercase hexadecimal characters"
  for scrcpy_limit in \
    "$SCRCPY_MAXIMUM_BYTES" \
    "$SCRCPY_MAXIMUM_EXTRACTED_BYTES" \
    "$SCRCPY_MAXIMUM_MEMBERS"
  do
    case "$scrcpy_limit" in
      ''|*[!0123456789]*) desktop_scrcpy_fail "archive limits must be unsigned integers" ;;
    esac
  done
  [ "$SCRCPY_MAXIMUM_BYTES" -ge 1048576 ] ||
    desktop_scrcpy_fail "archive ceiling is too small"
  [ "$SCRCPY_MAXIMUM_EXTRACTED_BYTES" -ge "$SCRCPY_MAXIMUM_BYTES" ] ||
    desktop_scrcpy_fail "extracted ceiling is smaller than the archive ceiling"
  [ "$SCRCPY_MAXIMUM_MEMBERS" -ge 4 ] ||
    desktop_scrcpy_fail "archive member ceiling is too small"
}

desktop_scrcpy_preflight_target_architecture() {
  desktop_scrcpy_validate_policy
  SCRCPY_TARGET_ARCHITECTURE=$(
    capture_in_target "detect target architecture for scrcpy" /usr/bin/dpkg --print-architecture
  )
  [ "$SCRCPY_TARGET_ARCHITECTURE" = "$SCRCPY_ARCHITECTURE" ] ||
    desktop_scrcpy_fail \
      "pinned Linux x86-64 release requires ${SCRCPY_ARCHITECTURE}, target is ${SCRCPY_TARGET_ARCHITECTURE:-unset}"
}

desktop_install_scrcpy() (
  set -eu
  desktop_scrcpy_preflight_target_architecture
  helper=/usr/local/libexec/installer-scrcpy
  helper_host=$(target_asset_host_path "$helper")
  trap 'rm -f -- "$helper_host"' EXIT
  trap 'exit 129' HUP
  trap 'exit 130' INT
  trap 'exit 143' TERM
  stage_target_asset \
    "$(installer_repo_join_var DIR_SCRIPTS_DESKTOP scrcpy-install.py)" \
    "$helper" 0700
  run_in_target "install pinned scrcpy release" \
    /usr/bin/env -i HOME=/root LC_ALL=C PATH=/usr/sbin:/usr/bin:/sbin:/bin \
    /usr/bin/timeout --signal=TERM --kill-after=5s 900s \
    /usr/bin/python3 -I "$helper" \
    --version "$SCRCPY_VERSION" --tag "$SCRCPY_TAG" \
    --url "$SCRCPY_URL" --sha256 "$SCRCPY_SHA256" \
    --server-sha256 "$SCRCPY_SERVER_SHA256" \
    --architecture "$SCRCPY_ARCHITECTURE" \
    --max-archive "$SCRCPY_MAXIMUM_BYTES" \
    --max-extracted "$SCRCPY_MAXIMUM_EXTRACTED_BYTES" \
    --max-members "$SCRCPY_MAXIMUM_MEMBERS"
  desktop_log "installed_scrcpy version=${SCRCPY_VERSION} tag=${SCRCPY_TAG} archive_sha256=${SCRCPY_SHA256} activation=adb-menu"
)
