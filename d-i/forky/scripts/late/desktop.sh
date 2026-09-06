#!/bin/sh
set -eu

requested_seed_base=${1:-}
requested_host_profile=${2:-}
runtime_dir=${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}
shared_late=${SHARED_LATE_COMMAND:-${runtime_dir}/bootstrap/shared-late.sh}
desktop_late_stage_stamp="${runtime_dir}/state/desktop-late.done"

[ -s "$shared_late" ] || {
  printf '[late:role:desktop] fatal: shared late command module is unavailable: %s\n' "$shared_late" >&2
  exit 1
}

install -d -m 0700 "$(dirname "$desktop_late_stage_stamp")"
if [ -f "$desktop_late_stage_stamp" ]; then
  printf '[late:role:desktop] info: managed Labwc desktop role already completed earlier in this install; skipping duplicate late_command run\n' >&2
  exit 0
fi

# shellcheck disable=SC1090
. "$shared_late"

late_command_shared_init "$requested_seed_base" "$requested_host_profile" desktop
late_command_load_host_env

desktop_module_dir="${runtime_dir}/bootstrap/desktop-modules"
install -d -m 0700 "$desktop_module_dir"
for desktop_module in detect components satty xwayland waypaper android-platform-tools samloader digital-assets labwc; do
  fetch_hook "scripts/desktop/${desktop_module}.sh" "${desktop_module_dir}/${desktop_module}.sh"
done
unset desktop_module

# shellcheck disable=SC1090,SC1091
. "${desktop_module_dir}/detect.sh"
# shellcheck disable=SC1090,SC1091
. "${desktop_module_dir}/components.sh"
# shellcheck disable=SC1090,SC1091
. "${desktop_module_dir}/satty.sh"
# shellcheck disable=SC1090,SC1091
. "${desktop_module_dir}/xwayland.sh"
# shellcheck disable=SC1090,SC1091
. "${desktop_module_dir}/waypaper.sh"
# shellcheck disable=SC1090,SC1091
. "${desktop_module_dir}/android-platform-tools.sh"
# shellcheck disable=SC1090,SC1091
. "${desktop_module_dir}/samloader.sh"
# shellcheck disable=SC1090,SC1091
. "${desktop_module_dir}/digital-assets.sh"
# shellcheck disable=SC1090,SC1091
. "${desktop_module_dir}/labwc.sh"

run_desktop_late_command "$requested_seed_base" "$requested_host_profile"
: >"$desktop_late_stage_stamp"
chmod 0600 "$desktop_late_stage_stamp" 2>/dev/null || true
installer_info "managed Labwc desktop role completion stamp recorded: ${desktop_late_stage_stamp}"
installer_archive_logs_to_target copy || true
