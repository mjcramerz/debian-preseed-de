#!/bin/sh
# Sourced installer module; edit this file directly.

devops_render_osc_config() {
  config_template_repo_path=$(installer_repo_join_var \
    DIR_HOOKS_TARGET \
    usr/local/share/devops/templates/oscrc.tmpl)
  metadata_template_repo_path=$(installer_repo_join_var \
    DIR_HOOKS_TARGET \
    usr/local/share/devops/templates/oscrc.json.tmpl)
  config_template_tmp="${tmp_env_dir}/oscrc.tmpl.$$"
  metadata_template_tmp="${tmp_env_dir}/oscrc.json.tmpl.$$"
  config_rendered_tmp="${tmp_env_dir}/oscrc.rendered.$$"
  metadata_rendered_tmp="${tmp_env_dir}/oscrc.json.rendered.$$"
  target_config="${target_root}${OSC_CONFIG}"
  target_metadata="${target_root}${OSC_MANAGED_CONFIG}"

  bootstrap_fetch_seed_file \
    "$seed_base" \
    "$config_template_repo_path" \
    "$config_template_tmp" \
    0600 \
    "DevOps osc config template ${config_template_repo_path}"
  bootstrap_fetch_seed_file \
    "$seed_base" \
    "$metadata_template_repo_path" \
    "$metadata_template_tmp" \
    0600 \
    "DevOps osc metadata template ${metadata_template_repo_path}"
  installer_apply_scalar_placeholders \
    "$config_template_tmp" \
    "$config_rendered_tmp" \
    ACCOUNT_USERNAME "$ACCOUNT_USERNAME" \
    DEVOPS_OBS_API_URL "$DEVOPS_OBS_API_URL" \
    DEVOPS_OSC_PACKAGE_CACHE_DIR "$OSC_PACKAGE_CACHE_DIR" \
    DEVOPS_OSC_BUILD_ROOT "$OSC_BUILD_ROOT" \
    DEVOPS_OSC_COOKIE_JAR "$OSC_COOKIE_JAR" \
    DEVOPS_OBS_REPOSITORY "$DEVOPS_OBS_REPOSITORY"
  installer_apply_scalar_placeholders \
    "$metadata_template_tmp" \
    "$metadata_rendered_tmp" \
    ACCOUNT_USERNAME "$ACCOUNT_USERNAME" \
    DEVOPS_OBS_API_URL "$DEVOPS_OBS_API_URL" \
    DEVOPS_OSC_WORKDIR "$OSC_WORKDIR" \
    DEVOPS_OBS_PROJECT "$DEVOPS_OBS_PROJECT" \
    DEVOPS_OBS_REPOSITORY "$DEVOPS_OBS_REPOSITORY" \
    DEVOPS_OSC_CREDENTIALS_BACKEND "$DEVOPS_OSC_CREDENTIALS_BACKEND"
  installer_assert_no_unresolved_installer_placeholders \
    "$config_rendered_tmp" \
    "DevOps osc config template ${config_template_repo_path}"
  installer_assert_no_unresolved_installer_placeholders \
    "$metadata_rendered_tmp" \
    "DevOps osc metadata template ${metadata_template_repo_path}"

  [ -d "${target_root}${OSC_STATE_DIR}" ] ||
    devops_fatal "required osc state directory is missing: ${target_root}${OSC_STATE_DIR}"
  install -m 0600 "$config_rendered_tmp" "$target_config"
  install -m 0600 "$metadata_rendered_tmp" "$target_metadata"
  chown "$account_ids" "$target_config" "$target_metadata"
  run_in_target \
    "validate rendered osc config and managed metadata" \
    /usr/bin/python3 -c \
      'import configparser, json, pathlib, sys
config_path, metadata_path = map(pathlib.Path, sys.argv[1:3])
apiurl, cache_dir, build_root, cookiejar, repository, project, workspace, backend = sys.argv[3:]
parser = configparser.ConfigParser(interpolation=None)
parser.read_string(config_path.read_text(encoding="utf-8"))
assert set(parser.sections()) == {"general", apiurl}
assert parser.get("general", "apiurl") == apiurl
assert parser.get("general", "packagecachedir") == cache_dir
assert parser.get("general", "build-root") == f"{build_root}/%(project)s/%(package)s/%(repo)s-%(arch)s"
assert parser.get("general", "cookiejar") == cookiejar
assert parser.get("general", "build_repository") == repository
for option in ("use_keyring", "checkout_rooted", "checkout_no_colon", "check_filelist", "do_package_tracking", "show_download_progress", "buildlog_strip_time", "builtin_signature_check"):
    assert parser.getboolean("general", option)
for option in ("quiet", "verbose", "debug", "http_debug", "http_full_debug", "http_manual_approve", "traceback", "post_mortem", "local_service_run", "status_mtime_heuristic", "no_verify"):
    assert not parser.getboolean("general", option)
assert parser.getint("general", "http_retries") == 3
assert parser.getboolean(apiurl, "sslcertck")
assert not parser.getboolean(apiurl, "allow_http")
assert all(not parser.has_option(section, option) for section in parser.sections() for option in ("user", "pass", "passx", "password"))
metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
assert metadata == {"apiURL": apiurl, "credentialsBackend": backend, "project": project, "repository": repository, "schemaVersion": 1, "workspace": workspace}' \
      "$OSC_CONFIG" \
      "$OSC_MANAGED_CONFIG" \
      "$DEVOPS_OBS_API_URL" \
      "$OSC_PACKAGE_CACHE_DIR" \
      "$OSC_BUILD_ROOT" \
      "$OSC_COOKIE_JAR" \
      "$DEVOPS_OBS_REPOSITORY" \
      "$DEVOPS_OBS_PROJECT" \
      "$OSC_WORKDIR" \
      "$DEVOPS_OSC_CREDENTIALS_BACKEND"
  rm -f -- \
    "$config_template_tmp" \
    "$metadata_template_tmp" \
    "$config_rendered_tmp" \
    "$metadata_rendered_tmp"
}

devops_stage_publishing_command_link() (
  publishing_label=$1
  publishing_link=$2
  publishing_target=$3
  publishing_display_path=${publishing_link#"$target_root"}

  # A resumed late stage can revisit links created before a later failure.
  # Only the exact managed target is idempotent; never replace a collision.
  if [ -L "$publishing_link" ]; then
    [ "$(readlink "$publishing_link")" = "$publishing_target" ] ||
      devops_fatal "managed ${publishing_label} publication entrypoint has an unexpected target: ${publishing_display_path}"
  elif [ -e "$publishing_link" ]; then
    devops_fatal "managed ${publishing_label} publication entrypoint already exists: ${publishing_display_path}"
  else
    ln -s "$publishing_target" "$publishing_link"
  fi
  chown -h root:root "$publishing_link"
)

devops_stage_publishing_entrypoints() {
  aptly_publishing_program=/usr/local/libexec/aptly-publishing
  aptly_publishing_bin_dir=/usr/local/libexec/aptly-publishing-bin
  obs_publishing_program=/usr/local/libexec/obs-publishing
  obs_publishing_bin_dir=/usr/local/libexec/obs-publishing-bin
  install -d -m 0755 \
    "${target_root}/usr/local/libexec" \
    "${target_root}${aptly_publishing_bin_dir}" \
    "${target_root}${obs_publishing_bin_dir}"
  chown root:root \
    "${target_root}/usr/local/libexec" \
    "${target_root}${aptly_publishing_bin_dir}" \
    "${target_root}${obs_publishing_bin_dir}"
  devops_stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/libexec/aptly-publishing)" \
    "$aptly_publishing_program" \
    0755 \
    aptly-publishing
  devops_stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/libexec/obs-publishing)" \
    "$obs_publishing_program" \
    0755 \
    obs-publishing
  chown root:root \
    "${target_root}${aptly_publishing_program}" \
    "${target_root}${obs_publishing_program}"

  for aptly_publishing_command in \
    aptly \
    aptly-publish-local \
    dpkg-buildpackage
  do
    publishing_link="${target_root}${aptly_publishing_bin_dir}/${aptly_publishing_command}"
    devops_stage_publishing_command_link \
      Aptly \
      "$publishing_link" \
      ../aptly-publishing
  done
  for obs_publishing_command in \
    obs-checkout-source \
    obs-publish-source \
    osc
  do
    publishing_link="${target_root}${obs_publishing_bin_dir}/${obs_publishing_command}"
    devops_stage_publishing_command_link \
      OBS \
      "$publishing_link" \
      ../obs-publishing
  done
  unset \
    aptly_publishing_command \
    aptly_publishing_program \
    aptly_publishing_bin_dir \
    obs_publishing_command \
    obs_publishing_program \
    obs_publishing_bin_dir \
    publishing_link
}

devops_install_pending_credential() {
  credential_value=$1
  credential_target=$2
  credential_label=$3
  credential_tmp="${tmp_env_dir}/${credential_label}.pending.$$"

  umask 077
  if ! printf '%s' "$credential_value" >"$credential_tmp"; then
    rm -f -- "$credential_tmp"
    devops_fatal "failed to stage pending ${credential_label} credential"
  fi
  if ! install -m 0600 "$credential_tmp" "${target_root}${credential_target}"; then
    rm -f -- "$credential_tmp" "${target_root}${credential_target}"
    devops_fatal "failed to install pending ${credential_label} credential"
  fi
  if ! chown "$account_ids" "${target_root}${credential_target}"; then
    rm -f -- "$credential_tmp" "${target_root}${credential_target}"
    devops_fatal "failed to assign pending ${credential_label} credential"
  fi
  rm -f -- "$credential_tmp"
}

devops_stage_pending_credentials() {
  devops_install_pending_credential \
    "$DEVOPS_CF_R2_ACCESS_KEY" \
    "${APTLY_ROOT_DIR}/.credentials.pending/cf-r2-access-key" \
    cf-r2-access-key
  devops_install_pending_credential \
    "$DEVOPS_CF_R2_SECRET_KEY" \
    "${APTLY_ROOT_DIR}/.credentials.pending/cf-r2-secret-key" \
    cf-r2-secret-key
  devops_install_pending_credential \
    "$DEVOPS_OBS_USERNAME" \
    "${OSC_STATE_DIR}/.credentials.pending/obs-username" \
    obs-username
  devops_install_pending_credential \
    "$DEVOPS_OBS_PASSWORD" \
    "${OSC_STATE_DIR}/.credentials.pending/obs-password" \
    obs-password
}

devops_initialize_aptly_repositories() {
  # shellcheck disable=SC2016
  devops_run_as_account "initialize stable and testing Aptly repositories" /bin/sh -eu -c '
aptly_config=$1
distributions=$2
component=$3
aptly_binary=$4

[ -r "$aptly_config" ] || {
  printf "fatal: managed Aptly config is missing: %s\n" "$aptly_config" >&2
  exit 1
}
[ -x "$aptly_binary" ] || {
  printf "fatal: managed Aptly binary is missing: %s\n" "$aptly_binary" >&2
  exit 1
}
for distribution in $distributions; do
  repository="local-${distribution}"
  if "$aptly_binary" -config="$aptly_config" repo show "$repository" >/dev/null 2>&1; then
    continue
  fi
  "$aptly_binary" \
    -config="$aptly_config" \
    repo create \
    -distribution="$distribution" \
    -component="$component" \
    "$repository"
done
' sh \
    "$APTLY_CONFIG" \
    "$DEVOPS_APTLY_DISTRIBUTIONS" \
    "$DEVOPS_APTLY_COMPONENT" \
    "$DEVOPS_APTLY_BINARY_PATH"
}

