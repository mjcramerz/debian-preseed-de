#!/bin/sh
# Sourced installer module; edit this file directly.

devops_stage_codex_app_server() {
  environment_source_repo=$(installer_repo_join_var \
    DIR_HOOKS_TARGET \
    etc/codex/app-server.env)
  service_source_repo=$(installer_repo_join_var \
    DIR_HOOKS_TARGET \
    etc/skel-desktop/.config/systemd/user/codex-app-server.service)
  proxy_source_repo=$(installer_repo_join_var \
    DIR_HOOKS_TARGET \
    etc/skel-desktop/.config/systemd/user/codex-app-server-proxy.service)
  socket_source_repo=$(installer_repo_join_var \
    DIR_HOOKS_TARGET \
    etc/skel-desktop/.config/systemd/user/codex-app-server.socket)
  environment_tmp="${tmp_env_dir}/codex-app-server.env.$$"
  service_tmp="${tmp_env_dir}/codex-app-server.service.$$"
  proxy_tmp="${tmp_env_dir}/codex-app-server-proxy.service.$$"
  socket_tmp="${tmp_env_dir}/codex-app-server.socket.$$"
  environment_target="${target_root}/etc/codex/app-server.env"
  template_config_dir="${target_root}/etc/skel-desktop/.config"
  template_systemd_dir="${template_config_dir}/systemd"
  template_unit_dir="${template_systemd_dir}/user"
  template_wants_dir="${template_unit_dir}/sockets.target.wants"
  template_legacy_wants_dir="${template_unit_dir}/default.target.wants"
  template_link="${template_wants_dir}/codex-app-server.socket"
  template_legacy_link="${template_legacy_wants_dir}/codex-app-server.service"
  user_config_dir="${target_root}${ACCOUNT_HOME}/.config"
  user_systemd_dir="${user_config_dir}/systemd"
  user_unit_dir="${user_systemd_dir}/user"
  wants_dir="${user_unit_dir}/sockets.target.wants"
  legacy_wants_dir="${user_unit_dir}/default.target.wants"
  service_link="${wants_dir}/codex-app-server.socket"
  legacy_service_link="${legacy_wants_dir}/codex-app-server.service"

  bootstrap_fetch_seed_file \
    "$seed_base" \
    "$environment_source_repo" \
    "$environment_tmp" \
    0600 \
    "Codex app-server non-secret environment policy ${environment_source_repo}"
  installer_assert_no_unresolved_installer_placeholders \
    "$environment_tmp" \
    "Codex app-server non-secret environment policy ${environment_source_repo}"
  bootstrap_fetch_seed_file \
    "$seed_base" \
    "$service_source_repo" \
    "$service_tmp" \
    0600 \
    "Codex app-server backend unit ${service_source_repo}"
  bootstrap_fetch_seed_file \
    "$seed_base" \
    "$proxy_source_repo" \
    "$proxy_tmp" \
    0600 \
    "Codex app-server proxy unit ${proxy_source_repo}"
  bootstrap_fetch_seed_file \
    "$seed_base" \
    "$socket_source_repo" \
    "$socket_tmp" \
    0600 \
    "Codex app-server activation socket ${socket_source_repo}"
  for managed_unit_tmp in "$service_tmp" "$proxy_tmp" "$socket_tmp"; do
    installer_assert_no_unresolved_installer_placeholders \
      "$managed_unit_tmp" \
      "Codex app-server user unit ${managed_unit_tmp}"
  done
  unset managed_unit_tmp

  if grep -Eq '^[[:space:]]*(OPENAI_API_KEY|CODEX_MCP_API_KEY)=' "$environment_tmp"; then
    devops_fatal "Codex app-server non-secret environment policy contains a secret assignment"
  fi
  grep -Fqx 'CODEX_APP_SERVER_SECRET_ENV_NAMES=CODEX_MCP_API_KEY' "$environment_tmp" ||
    devops_fatal "Codex app-server environment policy does not contain the approved secret-name allowlist"
  grep -Fqx \
    'ExecStart=/data/codex/lib/codex app-server --listen unix:///data/codex/sockets/app-server-backend.sock' \
    "$service_tmp" ||
    devops_fatal "Codex app-server backend does not use the managed wrapper command"
  grep -Fqx 'StopWhenUnneeded=yes' "$service_tmp" ||
    devops_fatal "Codex app-server backend does not stop after its proxy exits"
  grep -Fqx 'ExecStartPost=/usr/local/libexec/codex-app-server-wait-ready' "$service_tmp" ||
    devops_fatal "Codex app-server backend does not wait for its private socket"
  grep -Fqx 'SuccessExitStatus=143 SIGTERM' "$service_tmp" ||
    devops_fatal "Codex app-server backend does not treat managed idle shutdown as successful"
  grep -Fqx 'EnvironmentFile=-/etc/codex/app-server.env' "$service_tmp" ||
    devops_fatal "Codex app-server unit is missing its non-secret environment policy"
  grep -Fqx 'LoadCredential=codex-mcp.env:/data/codex/credentials/mcp.env' "$service_tmp" ||
    devops_fatal "Codex app-server unit is missing its MCP credential environment"
  grep -Fqx 'EnvironmentFile=-%d/codex-mcp.env' "$service_tmp" ||
    devops_fatal "Codex app-server unit does not let systemd decode the MCP credential environment"
  grep -Fqx \
    'ExecStart=/usr/lib/systemd/systemd-socket-proxyd --exit-idle-time=10min /data/codex/sockets/app-server-backend.sock' \
    "$proxy_tmp" ||
    devops_fatal "Codex app-server proxy does not enforce the managed idle timeout"
  grep -Fqx 'Requires=codex-app-server.socket codex-app-server.service' "$proxy_tmp" ||
    devops_fatal "Codex app-server proxy does not own the backend lifecycle"
  grep -Fqx 'ListenStream=/data/codex/sockets/app-server-control.sock' "$socket_tmp" ||
    devops_fatal "Codex app-server activation socket does not own the public endpoint"
  grep -Fqx 'Service=codex-app-server-proxy.service' "$socket_tmp" ||
    devops_fatal "Codex app-server socket does not activate the managed proxy"
  grep -Fqx 'WantedBy=sockets.target' "$socket_tmp" ||
    devops_fatal "Codex app-server socket is not enabled through sockets.target"
  if grep -Eq '^[[:space:]]*[^#[:space:]].*auth\.json' "$service_tmp"; then
    devops_fatal "Codex app-server unit must not require or overmount pre-login auth.json state"
  fi
  if grep -Eq '^ExecStart=.*/data/codex/(share/bin/codex|lib/codex-app-server)([[:space:]]|$)' "$service_tmp"; then
    devops_fatal "Codex app-server unit bypasses the managed wrapper"
  fi
  if grep -Eq '^[[:space:]]*WantedBy=' "$service_tmp" "$proxy_tmp"; then
    devops_fatal "Codex app-server processes must not be enabled independently of socket activation"
  fi
  if grep -Eq '^[[:space:]]*User=' "$service_tmp" "$proxy_tmp" "$socket_tmp"; then
    devops_fatal "Codex app-server user units must inherit their account identity from the user manager"
  fi

  for managed_base_dir in "${target_root}/etc/codex" "${target_root}/etc/skel-desktop"; do
    if [ -e "$managed_base_dir" ] || [ -L "$managed_base_dir" ]; then
      [ -d "$managed_base_dir" ] && [ ! -L "$managed_base_dir" ] ||
        devops_fatal "Codex app-server base directory is indirect: $managed_base_dir"
    else
      install -d -m 0755 -- "$managed_base_dir"
    fi
    [ "$(readlink -f -- "$managed_base_dir")" = "$managed_base_dir" ] ||
      devops_fatal "Codex app-server base directory traverses a symlink: $managed_base_dir"
    chmod 0755 "$managed_base_dir"
    chown root:root "$managed_base_dir"
    devops_assert_target_metadata \
      0:0:755 \
      "$managed_base_dir" \
      "Codex app-server base directory"
  done
  unset managed_base_dir

  for managed_unit_dir in \
    "$template_config_dir" \
    "$template_systemd_dir" \
    "$template_unit_dir" \
    "$template_wants_dir" \
    "$user_config_dir" \
    "$user_systemd_dir" \
    "$user_unit_dir" \
    "$wants_dir"
  do
    case "$managed_unit_dir" in
      "$template_config_dir"|"$template_systemd_dir"|"$template_unit_dir"|"$template_wants_dir")
        managed_unit_owner=0:0
        ;;
      *)
        managed_unit_owner=$account_ids
        ;;
    esac
    if [ -e "$managed_unit_dir" ] || [ -L "$managed_unit_dir" ]; then
      [ -d "$managed_unit_dir" ] && [ ! -L "$managed_unit_dir" ] ||
        devops_fatal "Codex app-server user-unit directory is indirect: $managed_unit_dir"
      chmod 0700 "$managed_unit_dir"
    else
      install -d -m 0700 -- "$managed_unit_dir"
    fi
    [ "$(readlink -f -- "$managed_unit_dir")" = "$managed_unit_dir" ] ||
      devops_fatal "Codex app-server user-unit directory traverses a symlink: $managed_unit_dir"
    chown "$managed_unit_owner" "$managed_unit_dir"
    devops_assert_target_metadata \
      "${managed_unit_owner}:700" \
      "$managed_unit_dir" \
      "Codex app-server user-unit directory"
  done
  unset managed_unit_dir managed_unit_owner

  for legacy_unit_dir in "$template_legacy_wants_dir" "$legacy_wants_dir"; do
    if [ -e "$legacy_unit_dir" ] || [ -L "$legacy_unit_dir" ]; then
      [ -d "$legacy_unit_dir" ] && [ ! -L "$legacy_unit_dir" ] ||
        devops_fatal "Codex app-server legacy enablement directory is indirect: $legacy_unit_dir"
      [ "$(readlink -f -- "$legacy_unit_dir")" = "$legacy_unit_dir" ] ||
        devops_fatal "Codex app-server legacy enablement directory traverses a symlink: $legacy_unit_dir"
    fi
  done
  unset legacy_unit_dir

  for managed_unit_name in \
    codex-app-server.service \
    codex-app-server-proxy.service \
    codex-app-server.socket
  do
    case "$managed_unit_name" in
      codex-app-server.service) managed_unit_tmp=$service_tmp ;;
      codex-app-server-proxy.service) managed_unit_tmp=$proxy_tmp ;;
      codex-app-server.socket) managed_unit_tmp=$socket_tmp ;;
      *) devops_fatal "unsupported Codex app-server unit: $managed_unit_name" ;;
    esac
    template_unit_target="${template_unit_dir}/${managed_unit_name}"
    account_unit_target="${user_unit_dir}/${managed_unit_name}"
    for managed_unit_target in "$template_unit_target" "$account_unit_target"; do
      if [ -e "$managed_unit_target" ] || [ -L "$managed_unit_target" ]; then
        [ -f "$managed_unit_target" ] && [ ! -L "$managed_unit_target" ] ||
          devops_fatal "Codex app-server managed file is indirect: $managed_unit_target"
      fi
    done
    unset managed_unit_target

    install -m 0644 -- "$managed_unit_tmp" "$template_unit_target"
    install -m 0644 -- "$managed_unit_tmp" "$account_unit_target"
    chown root:root "$template_unit_target"
    chown "$account_ids" "$account_unit_target"
    cmp -s -- "$template_unit_target" "$account_unit_target" ||
      devops_fatal "Codex app-server account unit differs from its skeleton source: $managed_unit_name"
    devops_assert_target_metadata \
      0:0:644 \
      "$template_unit_target" \
      "Codex app-server skeleton unit"
    devops_assert_target_metadata \
      "${account_ids}:644" \
      "$account_unit_target" \
      "Codex app-server account unit"
  done
  unset managed_unit_name managed_unit_tmp template_unit_target account_unit_target

  if [ -e "$environment_target" ] || [ -L "$environment_target" ]; then
    [ -f "$environment_target" ] && [ ! -L "$environment_target" ] ||
      devops_fatal "Codex app-server environment file is indirect: $environment_target"
  fi
  install -m 0644 -- "$environment_tmp" "$environment_target"
  chown root:root "$environment_target"

  for managed_unit_link in "$template_link" "$service_link"; do
    if [ -L "$managed_unit_link" ]; then
      [ "$(readlink -- "$managed_unit_link")" = ../codex-app-server.socket ] ||
        devops_fatal "Codex app-server socket enablement link has an unexpected target: $managed_unit_link"
    elif [ -e "$managed_unit_link" ]; then
      devops_fatal "Codex app-server socket enablement path is not a symlink: $managed_unit_link"
    else
      ln -s -- ../codex-app-server.socket "$managed_unit_link"
    fi
  done
  chown -h root:root "$template_link"
  chown -h "$account_ids" "$service_link"
  unset managed_unit_link

  for legacy_service_path in "$template_legacy_link" "$legacy_service_link"; do
    if [ -L "$legacy_service_path" ]; then
      [ "$(readlink -- "$legacy_service_path")" = ../codex-app-server.service ] ||
        devops_fatal "Codex app-server legacy enablement link has an unexpected target: $legacy_service_path"
      rm -f -- "$legacy_service_path"
    elif [ -e "$legacy_service_path" ]; then
      devops_fatal "Codex app-server legacy enablement path is not a symlink: $legacy_service_path"
    fi
  done
  unset legacy_service_path

  devops_assert_target_metadata \
    0:0:644 \
    "$environment_target" \
    "Codex app-server environment file"

  rm -f -- "$environment_tmp" "$service_tmp" "$proxy_tmp" "$socket_tmp"
}
