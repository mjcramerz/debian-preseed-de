#!/bin/sh
# Sourced installer module; edit this file directly.

devops_target_passwd_ids() {
  awk -F: -v wanted_user="$1" '$1 == wanted_user { print $3 ":" $4; exit }' \
    "${target_root}/etc/passwd" 2>/dev/null || true
}

devops_stage_target_asset() {
  repo_path=$1
  target_path=$2
  mode=$3
  asset_name=$4
  target_host_path="${target_root}${target_path}"
  tmp_asset="${tmp_env_dir}/${asset_name}.$$"

  devops_validate_abs_path "target path" "$target_path"
  bootstrap_fetch_seed_file \
    "$seed_base" \
    "$repo_path" \
    "$tmp_asset" \
    0600 \
    "DevOps target asset ${repo_path}"
  [ -d "${target_root}$(dirname "$target_path")" ] ||
    devops_fatal "required DevOps target directory is missing: ${target_root}$(dirname "$target_path")"
  install -m "$mode" "$tmp_asset" "$target_host_path"
  rm -f -- "$tmp_asset"
}

devops_prepare_publishing_layout() {
  # shellcheck disable=SC2016
  run_in_target "create account-local Aptly and osc publication directories" /bin/sh -eu -c '
account_user=$1
build_root=$2
cache_root=$3
db_root=$4
osc_build_subdir=$5
osc_cache_subdir=$6
aptly_state_subdir=$7
osc_state_subdir=$8

for required_command in chmod getent id install; do
  command -v "$required_command" >/dev/null 2>&1 || {
    printf "fatal: required publication setup command is unavailable: %s\n" "$required_command" >&2
    exit 1
  }
done
getent group devops >/dev/null 2>&1 || {
  printf "fatal: required publication group is missing: devops\n" >&2
  exit 1
}
account_uid=$(id -u "$account_user")
account_gid=$(id -g "$account_user")

for shared_path in \
  "$build_root/$account_user/$osc_build_subdir" \
  "$build_root/$account_user/$osc_build_subdir/build-root" \
  "$cache_root/$account_user/$osc_cache_subdir" \
  "$cache_root/$account_user/$osc_cache_subdir/packages"
do
  install -d -m 2770 -o "$account_uid" -g devops -- "$shared_path"
done
for private_path in \
  "$db_root/$account_user/$aptly_state_subdir" \
  "$db_root/$account_user/$aptly_state_subdir/.credentials.pending" \
  "$db_root/$account_user/$osc_state_subdir" \
  "$db_root/$account_user/$osc_state_subdir/.credentials.pending"
do
  [ ! -L "$private_path" ] || {
    printf "fatal: private publication path is a symlink: %s\n" "$private_path" >&2
    exit 1
  }
  install -d -m 0700 -o "$account_uid" -g "$account_gid" -- "$private_path"
  [ -d "$private_path" ] && [ ! -L "$private_path" ] || {
    printf "fatal: private publication path is not a direct directory: %s\n" "$private_path" >&2
    exit 1
  }
  # The account DB root is setgid for shared DevOps state, so a newly created
  # private child inherits that special bit even when install requests 0700.
  chmod a-s -- "$private_path"
  chmod 0700 -- "$private_path"
done
' sh \
    "$ACCOUNT_USERNAME" \
    "$DIR_POOL_BUILD" \
    "$DIR_POOL_CACHE" \
    "$DIR_POOL_DB" \
    "$DEVOPS_OSC_BUILD_SUBDIR" \
    "$DEVOPS_OSC_CACHE_SUBDIR" \
    "$DEVOPS_APTLY_ROOT_SUBDIR" \
    "$DEVOPS_OSC_STATE_SUBDIR"
}

devops_render_aptly_config() {
  template_repo_path=$(installer_repo_join_var \
    DIR_HOOKS_TARGET \
    usr/local/share/devops/templates/aptly.conf.tmpl)
  template_tmp="${tmp_env_dir}/aptly.conf.tmpl.$$"
  rendered_tmp="${tmp_env_dir}/aptly.conf.rendered.$$"
  target_config="${target_root}${APTLY_CONFIG}"

  bootstrap_fetch_seed_file \
    "$seed_base" \
    "$template_repo_path" \
    "$template_tmp" \
    0600 \
    "DevOps Aptly config template ${template_repo_path}"
  installer_apply_scalar_placeholders \
    "$template_tmp" \
    "$rendered_tmp" \
    ACCOUNT_USERNAME "$ACCOUNT_USERNAME" \
    DEVOPS_APTLY_ROOT_DIR "$APTLY_ROOT_DIR" \
    DEVOPS_APTLY_R2_ENDPOINT_NAME "$DEVOPS_APTLY_R2_ENDPOINT_NAME" \
    DEVOPS_APTLY_R2_BUCKET "$DEVOPS_APTLY_R2_BUCKET" \
    DEVOPS_APTLY_R2_ENDPOINT_URL "$DEVOPS_APTLY_R2_ENDPOINT_URL" \
    DEVOPS_APTLY_R2_STORAGE_PREFIX "$APTLY_R2_STORAGE_PREFIX" \
    DEVOPS_APTLY_DISTRIBUTIONS "$DEVOPS_APTLY_DISTRIBUTIONS" \
    DEVOPS_APTLY_COMPONENT "$DEVOPS_APTLY_COMPONENT" \
    DEVOPS_APTLY_PUBLISH_TARGET "s3:${DEVOPS_APTLY_R2_ENDPOINT_NAME}:" \
    DEVOPS_APTLY_WORKER_ROUTE "$DEVOPS_APTLY_WORKER_ROUTE" \
    DEVOPS_APTLY_WORKER_ZONE "$DEVOPS_APTLY_WORKER_ZONE" \
    DEVOPS_APTLY_PUBLIC_BASE_URL "$DEVOPS_APTLY_PUBLIC_BASE_URL" \
    DEVOPS_APTLY_REPOSITORY_KEY_FINGERPRINT "$DEVOPS_APTLY_REPOSITORY_KEY_FINGERPRINT" \
    DEVOPS_APTLY_CREDENTIALS_BACKEND "$DEVOPS_OSC_CREDENTIALS_BACKEND"
  installer_assert_no_unresolved_installer_placeholders \
    "$rendered_tmp" \
    "DevOps Aptly config template ${template_repo_path}"

  [ -d "${target_root}${APTLY_ROOT_DIR}" ] ||
    devops_fatal "required Aptly root directory is missing: ${target_root}${APTLY_ROOT_DIR}"
  install -m 0600 "$rendered_tmp" "$target_config"
  chown "$account_ids" "$target_config"
  run_in_target \
    "validate rendered Aptly JSON config" \
    /usr/bin/python3 -m json.tool "$APTLY_CONFIG" >/dev/null
  rm -f -- "$template_tmp" "$rendered_tmp"
}

