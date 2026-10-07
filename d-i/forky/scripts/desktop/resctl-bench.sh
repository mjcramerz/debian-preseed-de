#!/bin/sh
# Pinned native resource-control tools, installed for every desktop profile.

desktop_resctl_bench_preflight_target_architecture() {
  : "${RESCTL_BENCH_VERSION:?RESCTL_BENCH_VERSION must be set}"
  : "${RESCTL_BENCH_TAG:?RESCTL_BENCH_TAG must be set}"
  : "${RESCTL_BENCH_URL:?RESCTL_BENCH_URL must be set}"
  : "${RESCTL_BENCH_SHA256:?RESCTL_BENCH_SHA256 must be set}"
  : "${RESCTL_BENCH_ARCHITECTURE:?RESCTL_BENCH_ARCHITECTURE must be set}"
  : "${RESCTL_BENCH_MAXIMUM_BYTES:?RESCTL_BENCH_MAXIMUM_BYTES must be set}"
  : "${RESCTL_BENCH_MAXIMUM_EXTRACTED_BYTES:?RESCTL_BENCH_MAXIMUM_EXTRACTED_BYTES must be set}"
  : "${RESCTL_BENCH_MAXIMUM_MEMBERS:?RESCTL_BENCH_MAXIMUM_MEMBERS must be set}"
  RESCTL_BENCH_TARGET_ARCHITECTURE=$(
    capture_in_target "detect target architecture for resctl-bench" /usr/bin/dpkg --print-architecture
  )
  [ "$RESCTL_BENCH_ARCHITECTURE" = amd64 ] &&
    [ "$RESCTL_BENCH_TARGET_ARCHITECTURE" = "$RESCTL_BENCH_ARCHITECTURE" ] ||
    installer_fatal "resctl-bench: pinned native x86-64 release requires an amd64 target"
}

desktop_install_resctl_bench() (
  set -eu
  desktop_resctl_bench_preflight_target_architecture
  # A fixed, verified repository helper, never the downloaded archive's script.
  helper=/usr/local/libexec/installer-resctl-bench
  helper_host=$(target_asset_host_path "$helper")
  trap 'rm -f -- "$helper_host"' EXIT
  trap 'exit 129' HUP
  trap 'exit 130' INT
  trap 'exit 143' TERM
  stage_target_asset \
    "$(installer_repo_join_var DIR_SCRIPTS_DESKTOP resctl-bench-install.py)" \
    "$helper" 0700
  run_in_target "install pinned resctl-bench release" \
    /usr/bin/env -i HOME=/root LC_ALL=C PATH=/usr/sbin:/usr/bin:/sbin:/bin \
    /usr/bin/timeout --signal=TERM --kill-after=5s 900s \
    /usr/bin/python3 -I "$helper" \
    --version "$RESCTL_BENCH_VERSION" --tag "$RESCTL_BENCH_TAG" \
    --url "$RESCTL_BENCH_URL" --sha256 "$RESCTL_BENCH_SHA256" \
    --architecture "$RESCTL_BENCH_ARCHITECTURE" \
    --max-archive "$RESCTL_BENCH_MAXIMUM_BYTES" \
    --max-extracted "$RESCTL_BENCH_MAXIMUM_EXTRACTED_BYTES" \
    --max-members "$RESCTL_BENCH_MAXIMUM_MEMBERS"
  desktop_log "installed_resctl_bench version=${RESCTL_BENCH_VERSION} tag=${RESCTL_BENCH_TAG} archive_sha256=${RESCTL_BENCH_SHA256}"
)
