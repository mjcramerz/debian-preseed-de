#!/bin/sh
set -eu

RUNTIME_DIR=${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}
BOOTSTRAP_LIB=${INSTALLER_BOOTSTRAP_LIB:-${RUNTIME_DIR}/bootstrap/bootstrap.sh}
TMP_ENV_DIR=${INSTALLER_CUDA_PREPKGSEL_ENV_DIR:-/tmp/install-env-pre-pkgsel/cuda-legacy}
LOG=

CUDA_FRAGMENT_REL=classes/class-addon/cuda-legacy.cfg
cuda_prepkgsel_fatal() {
  printf '[pre-pkgsel:cuda-legacy] fatal: %s\n' "$*" >&2
  exit 1
}

[ -s "$BOOTSTRAP_LIB" ] || cuda_prepkgsel_fatal "installer bootstrap library is unavailable: ${BOOTSTRAP_LIB}"
# shellcheck disable=SC1090,SC1091
. "$BOOTSTRAP_LIB"
bootstrap_source_common_lib ""

LOG="$(installer_runtime_log_file)"
INSTALLER_DEBUG_LOGS=1
INSTALLER_LOG_LEVEL=debug
export INSTALLER_DEBUG_LOGS INSTALLER_LOG_LEVEL
installer_init_log_file "$LOG" "" "cuda legacy pre-pkgsel" cuda-legacy package_install
trap 'installer_finalize_log "$?"' 0
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

SEED_BASE=$(installer_seed_base "")
installer_persist_seed_source "$SEED_BASE"
installer_ensure_context_loaded "$SEED_BASE"

if ! installer_cuda_legacy_selected 2>/dev/null; then
  installer_info "skipping legacy CUDA pre-pkgsel bootstrap because addon/cuda-legacy is not selected"
  exit 0
fi

# CUDA userspace/compiler packages are useful on build hosts without a GPU.
# Explicit class selection is authoritative; PCI detection must not skip them.

install -d -m 0700 "$TMP_ENV_DIR"
bootstrap_source_common_support_libs "$SEED_BASE" "$TMP_ENV_DIR" fetch hook target || {
  cuda_prepkgsel_fatal "failed to source shared installer helper libraries"
}

cuda_fragment_path() {
  printf '%s/cuda-legacy.fragment.cfg\n' "$TMP_ENV_DIR"
}

cuda_fetch_fragment() {
  fragment_path=$(cuda_fragment_path)
  if [ ! -s "$fragment_path" ]; then
    installer_fetch_file "$SEED_BASE" "$CUDA_FRAGMENT_REL" "$fragment_path" 0644
  fi
  [ -s "$fragment_path" ] || cuda_prepkgsel_fatal "legacy CUDA fragment is missing: ${CUDA_FRAGMENT_REL}"
  printf '%s\n' "$fragment_path"
}

cuda_fragment_field_value() {
  field_name=$1
  fragment_path=$(cuda_fetch_fragment)
  field_value=$(sed -n "s/^d-i[[:space:]]\\+apt-setup\\/local[0-9][0-9]*\\/${field_name}[[:space:]]\\+string[[:space:]]\\+//p" "$fragment_path" | sed -n '1p')
  [ -n "$field_value" ] || cuda_prepkgsel_fatal "legacy CUDA fragment is missing apt-setup/${field_name}"
  printf '%s\n' "$field_value"
}

cuda_repository_value() {
  cuda_fragment_field_value repository
}

cuda_repository_url() {
  repo_value=$(cuda_repository_value)
  set -- $repo_value
  [ "$#" -ge 1 ] || cuda_prepkgsel_fatal "legacy CUDA repository value is empty"
  printf '%s\n' "$1"
}

cuda_repository_suite() {
  repo_value=$(cuda_repository_value)
  set -- $repo_value
  [ "$#" -ge 2 ] || cuda_prepkgsel_fatal "legacy CUDA repository suite is missing"
  printf '%s\n' "$2"
}

cuda_repository_components() {
  repo_value=$(cuda_repository_value)
  set -- $repo_value
  shift 2
  printf '%s\n' "$*"
}

stage_cuda_legacy_source() {
  installer_cuda_stage_target_source \
    "$(cuda_repository_url)" "$(cuda_repository_suite)" "$(cuda_repository_components)"
}

prepare_cuda_legacy_target_apt_dirs() {
  run_in_target "repair legacy CUDA target apt directories" /bin/sh -eu -c '
install -d -m 0755 /var/lib/apt /var/lib/apt/lists /var/cache /var/cache/apt /var/cache/apt/archives
install -d -m 0700 /var/lib/apt/lists/partial /var/cache/apt/archives/partial
if id -u _apt >/dev/null 2>&1; then
  chown _apt:root /var/lib/apt/lists/partial /var/cache/apt/archives/partial
fi
install -d -m 1777 /tmp /var/tmp
' sh
}

refresh_cuda_legacy_target_apt_metadata() {
  installer_cuda_refresh_target_apt
}

stage_cuda_legacy_source
prepare_cuda_legacy_target_apt_dirs
refresh_cuda_legacy_target_apt_metadata
