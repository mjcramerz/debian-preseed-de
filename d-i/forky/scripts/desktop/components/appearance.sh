#!/bin/sh
# Native appearance assets; no source builds or session-policy changes.

desktop_stage_appearance() (
  set -eu
  for directory in \
    /usr/local/lib \
    /usr/local/lib/python3.14 \
    /usr/local/lib/python3.14/dist-packages \
    /usr/local/lib/python3.14/dist-packages/managed_workflows \
    /usr/local/lib/python3.14/dist-packages/labwc_appearance \
    /usr/local/libexec \
    /usr/local/share \
    /usr/local/share/labwc-appearance \
    /usr/share/polkit-1/actions
  do
    ensure_target_asset_parent "${directory}/.installer-directory"
    directory_host=$(target_asset_host_path "$directory")
    [ -d "$directory_host" ] && [ ! -L "$directory_host" ] ||
      installer_fatal "unsafe appearance asset directory: ${directory}"
    chown root:root "$directory_host"
    chmod 0755 "$directory_host"
  done
  desktop_stage_role_asset usr/local/bin/labwc-desktop-appearance /usr/local/bin/labwc-desktop-appearance 0755
  for helper in labwc-appearance-defaults labwc-appearance-greeter; do
    desktop_stage_role_asset "usr/local/libexec/$helper" "/usr/local/libexec/$helper" 0755
  done
  for module in __init__ fs process; do
    path="usr/local/lib/python3.14/dist-packages/managed_workflows/$module.py"
    desktop_stage_role_asset "$path" "/$path" 0644
  done
  for module in __init__ catalog cli defaults editors engine greeter native service transaction; do
    path="usr/local/lib/python3.14/dist-packages/labwc_appearance/$module.py"
    desktop_stage_role_asset "$path" "/$path" 0644
  done
  desktop_stage_role_asset usr/share/polkit-1/actions/org.labwc.desktop-appearance.policy \
    /usr/share/polkit-1/actions/org.labwc.desktop-appearance.policy 0644
)

desktop_capture_appearance_defaults() {
  run_in_target "capture rendered installation appearance defaults" \
    /usr/local/libexec/labwc-appearance-defaults --capture
}
