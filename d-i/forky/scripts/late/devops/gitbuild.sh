#!/bin/sh
# Packaged Debian builders and managed gitbuild entrypoints only.

devops_stage_gitbuild() (
  set -eu
  for directory in \
    /usr/local/bin \
    /usr/local/lib \
    /usr/local/libexec \
    /usr/local/lib/python3.14 \
    /usr/local/lib/python3.14/dist-packages \
    /usr/local/lib/python3.14/dist-packages/managed_workflows \
    /usr/local/lib/python3.14/dist-packages/gitbuild \
    /usr/local/share \
    /usr/local/share/gitbuild \
    /usr/share/polkit-1/actions
  do
    target_directory="${target_root}${directory}"
    [ ! -L "$target_directory" ] || devops_fatal "symlinked gitbuild directory: $directory"
    install -d -m 0755 "$target_directory"
    chown root:root "$target_directory"
    chmod 0755 "$target_directory"
  done
  for executable in bin/gitbuild libexec/gitbuild-worker libexec/gitbuild-publish libexec/gitbuild-import-local; do
    path="usr/local/$executable"
    devops_stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET "$path")" "/$path" 0755 gitbuild-executable
    chown root:root "${target_root}/$path"
  done
  for module in __init__ fs process; do
    path="usr/local/lib/python3.14/dist-packages/managed_workflows/$module.py"
    devops_stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET "$path")" "/$path" 0644 gitbuild-shared-module
    chown root:root "${target_root}/$path"
  done
  for module in __init__ cli core import_local publish safe_rename worker; do
    path="usr/local/lib/python3.14/dist-packages/gitbuild/$module.py"
    devops_stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET "$path")" "/$path" 0644 gitbuild-module
    chown root:root "${target_root}/$path"
  done
  for path in usr/local/share/gitbuild/sbuild.conf usr/share/polkit-1/actions/org.labwc.gitbuild-import.policy; do
    devops_stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET "$path")" "/$path" 0644 gitbuild-policy
    chown root:root "${target_root}/$path"
  done
  helper=/usr/local/libexec/installer-gitbuild-policy
  trap 'rm -f -- "${target_root}${helper}"' EXIT
  trap 'exit 129' HUP
  trap 'exit 130' INT
  trap 'exit 143' TERM
  devops_stage_target_asset \
    "$(installer_repo_join_var DIR_SCRIPTS_LATE gitbuild-policy.py)" "$helper" 0700 gitbuild-installer-policy
  run_in_target "configure private gitbuild storage and subordinate IDs" \
    /usr/bin/python3 -I -B "$helper" "$ACCOUNT_USERNAME"
  run_in_target "apply selected AppArmor mode to staged gitbuild workers" \
    /usr/local/libexec/apparmor-modes-run --no-reload
)
