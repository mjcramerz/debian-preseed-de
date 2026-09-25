#!/bin/sh
set -eu

RUNTIME_DIR=${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}
BOOTSTRAP_LIB=${INSTALLER_BOOTSTRAP_LIB:-${RUNTIME_DIR}/bootstrap/bootstrap.sh}
if [ ! -s "$BOOTSTRAP_LIB" ]; then
  SELF_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
  BOOTSTRAP_LIB="${SELF_DIR}/../common/bootstrap.sh"
fi
[ -s "$BOOTSTRAP_LIB" ] || {
  echo "fatal: installer bootstrap library is unavailable: ${BOOTSTRAP_LIB}" >&2
  exit 1
}
# shellcheck disable=SC1090,SC1091
. "$BOOTSTRAP_LIB"
bootstrap_source_common_lib "${1:-}"
installer_init_log_file "$(installer_runtime_log_file)" "" "early dispatch" early-dispatch boot
installer_ensure_log_files
trap 'installer_finalize_log "$?"' EXIT

seed_base=$(installer_seed_base "${1:-}")
installer_ensure_context_loaded "$seed_base"
host_profile=$(installer_resolve_host_profile "")
hook_family=${INSTALLER_HOOK_FAMILY:-${INSTALLER_HOST_FAMILY}}
shared_hook_path=$(installer_repo_join_var DIR_HOOKS_INSTALLER_D_I early.sh)
shared_hook_dest="${RUNTIME_DIR}/bootstrap/shared-d-i-early.sh"
helper_dir="${RUNTIME_DIR}/bootstrap/early-helpers"

installer_fetch_file "$seed_base" "$shared_hook_path" "$shared_hook_dest" 0755
install -d -m 0700 "$helper_dir"

run_helper_script() {
  helper_path=$1
  helper_dest=$2
  shift 2

  installer_fetch_file "$seed_base" "$helper_path" "$helper_dest" 0755
  "$helper_dest" "$@" </dev/null
}

run_selected_class_helpers() {
  selected_records_path=$(installer_selected_class_records_path)
  [ -r "$selected_records_path" ] || return 0
  while IFS='|' read -r group_name class_name _class_relpath || [ -n "$group_name" ]; do
    [ -n "$group_name" ] || continue
    helper_name=$(installer_class_meta_value "$seed_base" "$group_name" "$class_name" early_helper)
    [ -n "$helper_name" ] || continue
    helper_path=$(installer_repo_join_var DIR_SCRIPTS_EARLY "${helper_name}.sh")
    helper_dest="${helper_dir}/${helper_name}.sh"
    run_helper_script "$helper_path" "$helper_dest" "$host_profile" "$seed_base"
  done <"$selected_records_path"
}

run_selected_class_helpers

case "$hook_family" in
  btrfs|vm)
    runtime_script_path=$(installer_repo_join_var DIR_SCRIPTS_RUNTIME btrfs.sh)
    capture_dualboot_sizes=true
    preload_f2fs=false
    ;;
  f2fs)
    runtime_script_path=$(installer_repo_join_var DIR_SCRIPTS_RUNTIME f2fs.sh)
    capture_dualboot_sizes=false
    preload_f2fs=true
    ;;
  *)
    installer_fatal "unsupported shared d-i early storage family: ${hook_family}"
    ;;
esac

INSTALLER_BOOTSTRAP_LIB=$BOOTSTRAP_LIB \
SHARED_D_I_EARLY=$shared_hook_dest \
  /bin/sh -c '. "$SHARED_D_I_EARLY"; family_d_i_early_main "$@"' sh \
  "$seed_base" \
  "$host_profile" \
  "$hook_family" \
  "$runtime_script_path" \
  "$capture_dualboot_sizes" \
  "$preload_f2fs"
