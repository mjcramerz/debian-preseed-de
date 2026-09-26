#!/bin/sh
# Authenticated desktop archive tooling and its pinned prebuilt FLZMA2 codec.

desktop_stage_compz() (
  set -eu
  for directory in \
    /usr/local/lib \
    /usr/local/lib/python3.14 \
    /usr/local/lib/python3.14/dist-packages \
    /usr/local/lib/python3.14/dist-packages/labwc_compz \
    /usr/local/libexec
  do
    ensure_target_asset_parent "${directory}/.installer-directory"
    directory_host=$(target_asset_host_path "$directory")
    [ -d "$directory_host" ] && [ ! -L "$directory_host" ] ||
      installer_fatal "unsafe compz module directory: ${directory}"
    chown root:root "$directory_host"
    chmod 0755 "$directory_host"
  done
  desktop_stage_role_asset usr/local/bin/compz /usr/local/bin/compz 0755
  for helper in compz-worker compz-sandbox compz-pipeline; do
    desktop_stage_role_asset "usr/local/libexec/${helper}" "/usr/local/libexec/${helper}" 0755
  done
  for module in __init__ cli formats isolation safeio volumes worker; do
    module_path="usr/local/lib/python3.14/dist-packages/labwc_compz/${module}.py"
    desktop_stage_role_asset "$module_path" "/${module_path}" 0644
  done
  desktop_stage_role_asset \
    usr/local/lib/perl5/site_perl/labwc-compz/CompzArchives/Pipeline.pm \
    /usr/local/lib/perl5/site_perl/labwc-compz/CompzArchives/Pipeline.pm 0644
  helper=/usr/local/libexec/installer-compz-codecs
  helper_host=$(target_asset_host_path "$helper")
  trap 'rm -f -- "$helper_host"' EXIT
  trap 'exit 129' HUP
  trap 'exit 130' INT
  trap 'exit 143' TERM
  stage_target_asset \
    "$(installer_repo_join_var DIR_SCRIPTS_DESKTOP compz-codecs-install.py)" \
    "$helper" 0700
  run_in_target "install pinned compz FLZMA2 codec" \
    /usr/bin/env -i HOME=/root LC_ALL=C PATH=/usr/sbin:/usr/bin:/sbin:/bin \
    /usr/bin/timeout --signal=TERM --kill-after=10s 600s \
    /usr/bin/python3 -I -B "$helper"
  run_in_target "verify compz codec and helper dependencies" /usr/local/bin/compz --check
  desktop_log "staged_compz isolated_archive_tools=yes flzma2=pinned_prebuilt"
)
