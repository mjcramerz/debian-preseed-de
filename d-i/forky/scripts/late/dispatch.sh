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
installer_init_log_file "$(installer_runtime_log_file)" "" "late dispatch" late-dispatch late_command
trap 'installer_finalize_log "$?"' EXIT

seed_base=$(installer_seed_base "${1:-}")
installer_ensure_context_loaded "$seed_base"
host_profile=$(installer_resolve_host_profile "")
hook_family=${INSTALLER_HOOK_FAMILY:-${INSTALLER_HOST_FAMILY}}
shared_hook_path=$(installer_repo_join_var DIR_HOOKS_INSTALLER late_command.sh)
shared_hook_dest="${RUNTIME_DIR}/bootstrap/shared-late.sh"
role_hook_path=$(installer_repo_join_var DIR_SCRIPTS_LATE desktop.sh)
role_hook_dest="${RUNTIME_DIR}/bootstrap/role-late.sh"
helper_dir="${RUNTIME_DIR}/bootstrap/late-helpers"
shared_module_dir="${RUNTIME_DIR}/bootstrap/late-modules"
shared_modules="core target-assets volatile-storage storage-maintenance mullvad templates network grub security dbus-broker podman zram-swap btrfs-family f2fs-family account"
if installer_selected_class_reference_is_selected addon/cuda-legacy 2>/dev/null; then
  shared_modules="${shared_modules} cuda-legacy"
fi

installer_fetch_file "$seed_base" "$shared_hook_path" "$shared_hook_dest" 0644
install -d -m 0700 "$shared_module_dir"
for shared_module in $shared_modules; do
  installer_fetch_file \
    "$seed_base" \
    "$(installer_repo_join_var DIR_SCRIPTS_LATE "${shared_module}.sh")" \
    "${shared_module_dir}/${shared_module}.sh" \
    0644
done
install -d -m 0700 "$helper_dir"
case "$hook_family" in
  btrfs|vm)
    INSTALLER_BOOTSTRAP_LIB=$BOOTSTRAP_LIB \
    INSTALLER_LATE_MODULE_DIR=$shared_module_dir \
    SHARED_LATE_COMMAND=$shared_hook_dest \
      /bin/sh -eu -c '. "$SHARED_LATE_COMMAND"; run_btrfs_family_late_command "$@"' sh \
      "$hook_family" "$seed_base" "$host_profile"
    ;;
  f2fs)
    INSTALLER_BOOTSTRAP_LIB=$BOOTSTRAP_LIB \
    INSTALLER_LATE_MODULE_DIR=$shared_module_dir \
    SHARED_LATE_COMMAND=$shared_hook_dest \
      /bin/sh -eu -c '. "$SHARED_LATE_COMMAND"; run_f2fs_family_late_command "$@"' sh \
      "$seed_base" "$host_profile"
    ;;
  *)
    installer_fatal "unsupported shared late storage family: ${hook_family}"
    ;;
esac
run_helper_script() {
  helper_path=$1
  helper_dest=$2
  shift 2

  installer_fetch_file "$seed_base" "$helper_path" "$helper_dest" 0755
  "$helper_dest" "$@" </dev/null
}

run_selected_class_helpers() {
  selected_records_path=$(installer_selected_class_records_path)
  helper_records="${helper_dir}/selected-helpers.tsv"
  helper_sorted="${helper_dir}/selected-helpers.sorted.tsv"
  [ -r "$selected_records_path" ] || return 0
  : >"$helper_records"
  while IFS='|' read -r group_name class_name _class_relpath || [ -n "$group_name" ]; do
    [ -n "$group_name" ] || continue
    helper_name=$(installer_class_meta_value "$seed_base" "$group_name" "$class_name" late_helper)
    [ -n "$helper_name" ] || continue
    helper_order=$(installer_class_helper_order "$seed_base" "$group_name" "$class_name")
    printf '%08d\t%s\t%s\t%s\n' \
      "$helper_order" \
      "$group_name" \
      "$class_name" \
      "$helper_name" >>"$helper_records"
  done <"$selected_records_path"

  [ -s "$helper_records" ] || return 0
  sort -t "$(printf '\t')" -k1,1n -k2,2 -k3,3 "$helper_records" >"$helper_sorted"
  while IFS="$(printf '\t')" read -r _helper_order group_name class_name helper_name || [ -n "${group_name:-}" ]; do
    [ -n "${group_name:-}" ] || continue
    helper_path=$(installer_repo_join_var DIR_SCRIPTS_LATE "${helper_name}.sh")
    helper_dest="${helper_dir}/${helper_name}.sh"
    run_helper_script "$helper_path" "$helper_dest" /target
  done <"$helper_sorted"
}

run_selected_class_helpers

installer_fetch_file "$seed_base" "$role_hook_path" "$role_hook_dest" 0755
{
  INSTALLER_BOOTSTRAP_LIB=$BOOTSTRAP_LIB \
  INSTALLER_LATE_MODULE_DIR=$shared_module_dir \
    "$role_hook_dest" "$seed_base" "$host_profile"
}
