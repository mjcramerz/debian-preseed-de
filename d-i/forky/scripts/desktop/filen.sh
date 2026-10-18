#!/bin/sh
# Desktop-only Filen installation. Secrets cross the chroot in private files.

desktop_install_filen() (
  set -eu
  set +x
  set +v
  case "${FILEN_CLI_PRIV_ENABLE:?}:${FILEN_CLI_OFFSEC_ENABLE:?}" in
    false:false) return 0 ;;
    true:true|true:false|false:true) ;;
    *) installer_fatal "Filen enable flags must be true or false" ;;
  esac
  filen_stage=$(target_private_stage_dir filen)
  trap 'rm -rf -- "/target${filen_stage}"' EXIT
  trap 'exit 129' HUP
  trap 'exit 130' INT
  trap 'exit 143' TERM
  stage_target_asset "$(installer_repo_join_var DIR_SCRIPTS_DESKTOP filen-install.py)" "${filen_stage}/install.py" 0600
  for filen_asset in \
    usr/local/libexec/filen-sync \
    usr/local/lib/perl5/site_perl/filen/FilenSync/Config.pm \
    usr/local/lib/perl5/site_perl/filen/FilenSync/Daemon.pm \
    etc/systemd/system/filen-sync@.service.tmpl \
    etc/apparmor.d/filen-sync.tmpl
  do
    stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET "$filen_asset")" \
      "${filen_stage}/assets/${filen_asset}" 0600
  done
  for filen_account in priv offsec; do
    case "$filen_account" in
      priv) filen_enabled=$FILEN_CLI_PRIV_ENABLE ;;
      offsec) filen_enabled=$FILEN_CLI_OFFSEC_ENABLE ;;
    esac
    [ "$filen_enabled" = true ] || continue
    for filen_field in email password 2fa_seed; do
      filen_value=$(preseed_env_read_value "filen_${filen_account}_${filen_field}") ||
        installer_fatal "missing Filen ${filen_account} ${filen_field} in the protected preseed credential input"
      [ -n "$filen_value" ] || installer_fatal "empty Filen credential input"
      (umask 077; printf '%s' "$filen_value" >"/target${filen_stage}/${filen_account}-${filen_field}")
      unset filen_value
    done
  done
  run_in_target "install pinned Filen CLI and isolated sync services" \
    /usr/bin/env -i HOME=/root LC_ALL=C.UTF-8 PATH=/usr/sbin:/usr/bin:/sbin:/bin \
    FILEN_CLI_VERSION="$FILEN_CLI_VERSION" FILEN_CLI_URL="$FILEN_CLI_URL" \
    FILEN_CLI_SHA256="$FILEN_CLI_SHA256" FILEN_CLI_ARCHITECTURE="$FILEN_CLI_ARCHITECTURE" \
    FILEN_CLI_MAXIMUM_BYTES="$FILEN_CLI_MAXIMUM_BYTES" \
    FILEN_CLI_PRIV_ENABLE="$FILEN_CLI_PRIV_ENABLE" FILEN_CLI_OFFSEC_ENABLE="$FILEN_CLI_OFFSEC_ENABLE" \
    FILEN_CLI_PRIV_SYNC_MODE="$FILEN_CLI_PRIV_SYNC_MODE" FILEN_CLI_OFFSEC_SYNC_MODE="$FILEN_CLI_OFFSEC_SYNC_MODE" \
    FILEN_CLI_PRIV_REMOTE_PATH="$FILEN_CLI_PRIV_REMOTE_PATH" FILEN_CLI_OFFSEC_REMOTE_PATH="$FILEN_CLI_OFFSEC_REMOTE_PATH" \
    NETWORK_SHARING_ROOT_PATH="$NETWORK_SHARING_ROOT_PATH" \
    NETWORK_SHARING_HOME_BIND_PATH="$NETWORK_SHARING_HOME_BIND_PATH" \
    ACCOUNT_USERNAME="$ACCOUNT_USERNAME" ACCOUNT_HOME="$ACCOUNT_HOME" \
    /usr/bin/timeout --signal=TERM --kill-after=5s 420s \
    /usr/bin/python3 -I -B "${filen_stage}/install.py" "$filen_stage"
)
