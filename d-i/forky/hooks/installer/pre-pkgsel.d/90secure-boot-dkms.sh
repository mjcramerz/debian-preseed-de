#!/bin/sh
set -eu

RUNTIME_DIR=${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}
BOOTSTRAP_LIB=${INSTALLER_BOOTSTRAP_LIB:-${RUNTIME_DIR}/bootstrap/bootstrap.sh}
TMP_ENV_DIR=/tmp/install-env-pre-pkgsel
LOG=

prepkgsel_fatal() {
  printf '[pre-pkgsel] fatal: %s\n' "$*" >&2
  exit 1
}

[ -s "$BOOTSTRAP_LIB" ] || prepkgsel_fatal "installer bootstrap library is unavailable: ${BOOTSTRAP_LIB}"
# shellcheck disable=SC1090,SC1091
. "$BOOTSTRAP_LIB"
bootstrap_source_common_lib ""

LOG="$(installer_runtime_log_file)"
INSTALLER_DEBUG_LOGS=1
INSTALLER_LOG_LEVEL=debug
export INSTALLER_DEBUG_LOGS INSTALLER_LOG_LEVEL
installer_init_log_file "$LOG" "" "secure boot pre-pkgsel" secure-boot package_install
trap 'installer_finalize_log "$?"' EXIT HUP INT TERM

SEED_BASE=$(installer_seed_base "")
installer_persist_seed_source "$SEED_BASE"
installer_ensure_context_loaded "$SEED_BASE"
HOST_PROFILE=$(installer_resolve_host_profile "")
HOOK_FAMILY=${INSTALLER_HOOK_FAMILY:-${INSTALLER_HOST_FAMILY:-}}
[ -n "$HOOK_FAMILY" ] || prepkgsel_fatal "installer hook family is unavailable"

install -d -m 0700 "$TMP_ENV_DIR"
bootstrap_source_common_support_libs "$SEED_BASE" "$TMP_ENV_DIR" fetch hook target || {
  prepkgsel_fatal "failed to source shared installer helper libraries"
}

fetch_hook() {
  fetch_hook_file "$1" "$2"
}

fetch_hook "$(installer_repo_join_var DIR_SCRIPTS_LATE core.sh)" "$TMP_ENV_DIR/late-core.sh"
fetch_hook "$(installer_repo_join_var DIR_SCRIPTS_LATE target-assets.sh)" "$TMP_ENV_DIR/late-target-assets.sh"
fetch_hook "$(installer_repo_join_var DIR_SCRIPTS_LATE templates.sh)" "$TMP_ENV_DIR/late-templates.sh"
fetch_hook "$(installer_repo_join_var DIR_SCRIPTS_LATE volatile-storage.sh)" "$TMP_ENV_DIR/late-volatile-storage.sh"
fetch_hook "$(installer_repo_join_var DIR_SCRIPTS_LATE storage-maintenance.sh)" "$TMP_ENV_DIR/late-storage-maintenance.sh"
fetch_hook "$(installer_repo_join_var DIR_SCRIPTS_LATE grub.sh)" "$TMP_ENV_DIR/late-grub.sh"
fetch_hook "$(installer_repo_join_var DIR_SCRIPTS_RUNTIME common.sh)" "$TMP_ENV_DIR/runtime-common.sh"
fetch_hook "$(installer_repo_join_var DIR_SCRIPTS_RUNTIME account.sh)" "$TMP_ENV_DIR/account-runtime.sh"

case "$HOOK_FAMILY" in
  btrfs|vm)
    PREPKGSEL_RUNTIME_SCRIPT=$(installer_repo_join_var DIR_SCRIPTS_RUNTIME btrfs.sh)
    PREPKGSEL_CAPTURE_DUALBOOT=true
    ;;
  f2fs)
    PREPKGSEL_RUNTIME_SCRIPT=$(installer_repo_join_var DIR_SCRIPTS_RUNTIME f2fs.sh)
    PREPKGSEL_CAPTURE_DUALBOOT=false
    ;;
  *)
    prepkgsel_fatal "unsupported installer storage family: ${HOOK_FAMILY}"
    ;;
esac
fetch_hook "$PREPKGSEL_RUNTIME_SCRIPT" "$TMP_ENV_DIR/runtime.sh"

# shellcheck disable=SC1090,SC1091
. "$TMP_ENV_DIR/late-core.sh"
# shellcheck disable=SC1090,SC1091
. "$TMP_ENV_DIR/late-target-assets.sh"
# shellcheck disable=SC1090,SC1091
. "$TMP_ENV_DIR/late-templates.sh"
# shellcheck disable=SC1090,SC1091
. "$TMP_ENV_DIR/late-volatile-storage.sh"
# shellcheck disable=SC1090,SC1091
. "$TMP_ENV_DIR/late-storage-maintenance.sh"
# shellcheck disable=SC1090,SC1091
. "$TMP_ENV_DIR/late-grub.sh"

LATE_COMMAND_HOST_ENV="${TMP_ENV_DIR}/host.env"
LATE_COMMAND_ACCOUNT_ENV="${TMP_ENV_DIR}/account.env"

late_command_require_class_policy_env
late_command_load_runtime_env "$PREPKGSEL_CAPTURE_DUALBOOT"
late_command_load_host_env

stage_target_secure_boot_runtime_assets
run_installer_secure_boot_install_tool prepare-dkms
