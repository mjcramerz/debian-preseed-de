#!/bin/sh
# Shared late-command module loader for installer storage families.

late_command_source_module() {
  module_name=$1
  runtime_dir=${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}
  module_dir=${INSTALLER_LATE_MODULE_DIR:-${runtime_dir}/bootstrap/late-modules}
  module_path="${module_dir}/${module_name}.sh"

  [ -r "$module_path" ] || {
    printf '[late-command] fatal: shared late module is missing: %s\n' "$module_path" >&2
    exit 1
  }

  # shellcheck disable=SC1090
  . "$module_path"
}

for late_module in \
  core \
  target-assets \
  volatile-storage \
  storage-maintenance \
  mullvad \
  templates \
  network \
  grub \
  security \
  dbus-broker \
  podman \
  zram-swap \
  btrfs-family \
  f2fs-family \
  account
do
  late_command_source_module "$late_module"
done

if installer_selected_class_reference_is_selected addon/cuda-legacy 2>/dev/null; then
  late_command_source_module cuda-legacy
fi

unset late_module
