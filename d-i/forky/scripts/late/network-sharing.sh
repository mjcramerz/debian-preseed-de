#!/bin/sh
# Shared, sourced late-command module. Profile data is never evaluated here.

configure_target_network_sharing() (
  set -eu
  require_in_target "configure managed network sharing"
  if [ ! -x /target/usr/bin/python3 ]; then
    run_in_target "install packaged Python for network sharing configuration" \
      /usr/bin/env DEBIAN_FRONTEND=noninteractive \
      /usr/bin/apt-get -o Acquire::Retries=3 -o DPkg::Lock::Timeout=60 \
      -o DPkg::Use-Pty=0 -y --no-install-recommends install python3-minimal
  fi
  nfs_stage=$(target_private_stage_dir network-sharing)
  trap 'rm -rf -- "/target${nfs_stage}"' EXIT
  trap 'exit 129' HUP
  trap 'exit 130' INT
  trap 'exit 143' TERM
  stage_target_asset "$(installer_repo_join_var DIR_SCRIPTS_LATE network-sharing.py)" \
    "${nfs_stage}/configure.py" 0600
  for nfs_asset in \
    etc/exports.tmpl \
    etc/idmapd.conf.tmpl \
    etc/nfs.conf.d/60-network-sharing.conf.tmpl \
    etc/sysctl.d/60-network-sharing.conf.tmpl \
    etc/systemd/system/nfs-server.service.d/60-network-sharing.conf.tmpl \
    etc/systemd/system/nfs-mountd.service.d/60-network-sharing.conf \
    etc/systemd/system/nfs-idmapd.service.d/60-network-sharing.conf \
    etc/systemd/system/network-sharing-identity.service \
    etc/systemd/system/network-sharing-report.service.tmpl \
    usr/local/libexec/network-sharing-identity \
    usr/local/libexec/network-sharing-report
  do
    stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET "$nfs_asset")" \
      "${nfs_stage}/assets/${nfs_asset}" 0600
  done
  run_in_target "validate and configure profile-controlled NFS sharing" \
    /usr/bin/env \
    "ACCOUNT_USERNAME=${ACCOUNT_USERNAME:?}" "ACCOUNT_HOME=${ACCOUNT_HOME:?}" \
    "SYSTEM_DOMAIN=${SYSTEM_DOMAIN:?}" \
    "NFT_PROFILE=${NFT_PROFILE:-default}" \
    "NETWORK_SHARING_ROOT_PATH=${NETWORK_SHARING_ROOT_PATH:?}" \
    "NFS_SERVER_ENABLE=${NFS_SERVER_ENABLE:?}" \
    "NFS_SERVER_PATH=${NFS_SERVER_PATH:?}" \
    "NFS_SERVER_BIND_ENABLE=${NFS_SERVER_BIND_ENABLE:?}" \
    "NFS_SERVER_HOME_BIND_PATH=${NFS_SERVER_HOME_BIND_PATH:?}" \
    "NFS_SERVER_DEPS=${NFS_SERVER_DEPS:?}" \
    "NFS_SERVER_THREADS=${NFS_SERVER_THREADS:?}" \
    "NFS_SERVER_EXPORTS=${NFS_SERVER_EXPORTS:?}" \
    "NFS_CLIENT_ENABLE=${NFS_CLIENT_ENABLE:?}" \
    "NFS_CLIENT_PATH=${NFS_CLIENT_PATH:?}" \
    "NFS_CLIENT_BIND_ENABLE=${NFS_CLIENT_BIND_ENABLE:?}" \
    "NFS_CLIENT_HOME_BIND_PATH=${NFS_CLIENT_HOME_BIND_PATH:?}" \
    "NFS_CLIENT_TARGET_IP=${NFS_CLIENT_TARGET_IP:?}" \
    "NFS_CLIENT_EXPORT_PATH=${NFS_CLIENT_EXPORT_PATH:?}" \
    "NFS_CLIENT_VERSION=${NFS_CLIENT_VERSION:?}" \
    "NFS_CLIENT_READ_ONLY=${NFS_CLIENT_READ_ONLY:?}" \
    "NFS_CLIENT_MOUNT_TIMEOUT=${NFS_CLIENT_MOUNT_TIMEOUT:?}" \
    "NFS_CLIENT_DEPS=${NFS_CLIENT_DEPS:?}" \
    "NFS_ACCOUNT_UID=${NFS_ACCOUNT_UID:?}" "NFS_ACCOUNT_GID=${NFS_ACCOUNT_GID:?}" \
    "NFS_SHARED_GROUP=${NFS_SHARED_GROUP:?}" "NFS_SHARED_GID=${NFS_SHARED_GID:?}" \
    "NFS_INTERFACES=${NFS_INTERFACES:?}" \
    "NFS_TCP_RMEM=${NFS_TCP_RMEM:?}" "NFS_TCP_WMEM=${NFS_TCP_WMEM:?}" \
    "NFS_SOCKET_RMEM_MAX=${NFS_SOCKET_RMEM_MAX:?}" \
    "NFS_SOCKET_WMEM_MAX=${NFS_SOCKET_WMEM_MAX:?}" \
    /usr/bin/python3 -I -B "${nfs_stage}/configure.py" "${nfs_stage}/assets"
)
