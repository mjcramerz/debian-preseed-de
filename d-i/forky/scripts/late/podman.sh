#!/bin/sh
# Rootless Podman target staging; sourced by the shared late-command loader.
# All privileged account/storage work runs under the target Python interpreter,
# not missing BusyBox applets. Ordinary desktop commands never call this helper.

podman_fatal() {
  installer_fatal "$@"
}

podman_addon_is_selected() {
  case "${PODMAN_ADDON_SELECTED:-}" in
    true) return 0 ;;
    false) return 1 ;;
  esac
  installer_selected_class_reference_is_selected addon/podman 2>/dev/null
}

podman_addon_selection_state() {
  if podman_addon_is_selected; then printf '%s\n' true; else printf '%s\n' false; fi
}

# Kept as a small target-boundary helper for callers/tests. The target
# provisioner independently enforces the same approved-filesystem policy.
podman_resolve_native_storage_driver() (
  requested=$1
  storage=$2
  target=${INSTALLER_TARGET_DIR:-/target}
  target=${target%/}
  case "$storage" in
    "$target"/*) relative=${storage#"$target"} ;;
    *) podman_fatal 'Podman storage path is outside the installation target' ;;
  esac
  case "$relative" in
    *..*|*//*|*[!A-Za-z0-9_./-]*) podman_fatal 'unsafe Podman storage path' ;;
  esac
  filesystem=$(chroot "$target" /usr/bin/stat -f -c '%T' -- "$relative") ||
    podman_fatal 'target coreutils could not inspect the Podman storage filesystem'
  case "$filesystem" in
    btrfs|ext2/ext3|xfs|f2fs) ;;
    *) podman_fatal "unsupported Podman storage filesystem: $filesystem" ;;
  esac
  case "$requested" in
    auto|overlay) printf '%s\n' overlay ;;
    btrfs)
      [ "$filesystem" = btrfs ] || podman_fatal 'btrfs storage requires Btrfs'
      printf '%s\n' btrfs
      ;;
    *) podman_fatal "unsupported Podman storage driver: $requested" ;;
  esac
)

configure_target_rootless_podman_if_selected() {
  podman_addon_is_selected || return 0
  configure_target_rootless_podman
}

configure_target_rootless_podman() (
  : "${ACCOUNT_USERNAME:?ACCOUNT_USERNAME must be set}"
  # Fixed identities/paths are security invariants, not install-time aliases.
  [ "${PODMAN_USER:-devops}" = devops ] || podman_fatal 'PODMAN_USER must be devops'
  [ "${PODMAN_USER_HOME:-/nonexistent}" = /nonexistent ] ||
    podman_fatal 'PODMAN_USER_HOME must be /nonexistent for the no-home service account'
  [ "${PODMAN_ROOTLESS_STATE_BASE:-/pool/podman}" = /pool/podman ] ||
    podman_fatal 'PODMAN_ROOTLESS_STATE_BASE must be /pool/podman'

  for asset in \
    containers.conf.tmpl storage.conf.tmpl registries.conf client.conf \
    podman-devops.service.tmpl podman-devops.socket \
    podman-devops-restart.service.tmpl
  do
    stage_target_asset \
      "$(installer_repo_join_var DIR_HOOKS_TARGET "data/config/podman/templates/devops/$asset")" \
      "/usr/local/share/podman-devops/$asset" 0644
  done
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/libexec/podman-devops-host)" /usr/local/libexec/podman-devops-host 0755
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/libexec/podman-devops-client)" /usr/local/libexec/podman-devops-client 0755
  for client in podman docker docker-compose; do
    stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET "usr/local/bin/$client")" "/usr/local/bin/$client" 0755
  done
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/system/podman-devops-bootstrap.service)" /etc/systemd/system/podman-devops-bootstrap.service 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/tmpfiles.d/55-podman-devops.conf)" /etc/tmpfiles.d/55-podman-devops.conf 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/ssh/sshd_config.d/00-devops-nologin.conf)" /etc/ssh/sshd_config.d/00-devops-nologin.conf 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/sysctl.d/90-podman-rootless.conf)" /etc/sysctl.d/90-podman-rootless.conf 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/skel-desktop/.profile.d/71-devops-de.sh)" /etc/skel-desktop/.profile.d/71-devops-de.sh 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/bin/labwc-podman-menu)" /usr/local/bin/labwc-podman-menu 0755
  stage_target_helper_docs podman-devops.md podbin.md podbin-service-bridge.md

  run_in_target 'provision locked devops rootless engine' \
    /usr/local/libexec/podman-devops-host setup \
      --desktop-user "$ACCOUNT_USERNAME" \
      --storage-driver "${PODMAN_STORAGE_DRIVER:-auto}" \
      --cpu-weight "${PODMAN_SERVICE_SLICE_CPU_WEIGHT:-100}" \
      --io-weight "${PODMAN_SERVICE_SLICE_IO_WEIGHT:-100}" \
      --tasks-max "${PODMAN_SERVICE_SLICE_TASKS_MAX:-8192}" \
      --memory-high "${PODMAN_SERVICE_SLICE_MEMORY_HIGH:-70%}" \
      --memory-max "${PODMAN_SERVICE_SLICE_MEMORY_MAX:-85%}"
  # Account shell assets were initially copied before this addon. Refresh them
  # from the same source so addon/podman does not require addon/devops.
  install_target_account_shell_assets
  installer_info 'staged devops rootless Podman/Docker clients; socket activation and readiness validation run on every boot'
)
