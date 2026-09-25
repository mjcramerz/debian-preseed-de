#!/bin/sh
# Sourced installer module; edit this file directly.

devops_main() {
runtime_dir=${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}
bootstrap_lib=${INSTALLER_BOOTSTRAP_LIB:-${runtime_dir}/bootstrap/bootstrap.sh}
tmp_env_dir=${INSTALLER_LATE_TMP_ENV_DIR:-/tmp/install-env-late/devops}

seed_base=$(installer_current_seed_base 2>/dev/null || installer_seed_base "")
bootstrap_source_common_support_libs "$seed_base" "$tmp_env_dir" target fetch ssh ||
  devops_fatal "failed to source installer target support library"
installer_ensure_context_loaded "$seed_base"

installer_selected_class_reference_is_selected addon/devops 2>/dev/null || exit 0

case "${INSTALLER_HOST_VARIANT:-}" in
  desktop) ;;
  *) devops_fatal "addon/devops is restricted to the desktop role" ;;
esac

account_env=${INSTALLER_LATE_ACCOUNT_ENV:-/tmp/install-env-late/account.env}
host_env=${INSTALLER_LATE_HOST_ENV:-/tmp/install-env-late/host.env}
[ -r "$account_env" ] ||
  installer_fetch_account_env "$seed_base" "$account_env" 0600
[ -r "$host_env" ] ||
  installer_fetch_host_env \
    "$seed_base" \
    "$(installer_resolve_host_profile "")" \
    "$host_env" \
    0600

# shellcheck disable=SC1090,SC1091
. "$account_env"
# shellcheck disable=SC1090,SC1091
. "$host_env"

: "${ACCOUNT_USERNAME:?ACCOUNT_USERNAME must be set before DevOps provisioning}"
: "${ACCOUNT_HOME:?ACCOUNT_HOME must be set before DevOps provisioning}"
: "${DIR_POOL_BUILD:?DIR_POOL_BUILD must be set before DevOps provisioning}"
: "${DIR_POOL_CACHE:?DIR_POOL_CACHE must be set before DevOps provisioning}"
: "${DIR_POOL_DB:?DIR_POOL_DB must be set before DevOps provisioning}"

devops_validate_account_name "$ACCOUNT_USERNAME"
devops_validate_abs_path "ACCOUNT_HOME" "$ACCOUNT_HOME"
devops_validate_abs_path "DIR_POOL_BUILD" "$DIR_POOL_BUILD"
devops_validate_abs_path "DIR_POOL_CACHE" "$DIR_POOL_CACHE"
devops_validate_abs_path "DIR_POOL_DB" "$DIR_POOL_DB"
devops_validate_upstream_tool_policy
devops_validate_cargo_policy
devops_validate_bazel_policy
devops_validate_publishing_policy
devops_validate_codex_policy
devops_load_publishing_credentials

for pool_root in "$DIR_POOL_BUILD" "$DIR_POOL_CACHE" "$DIR_POOL_DB"; do
  [ -d "${target_root}${pool_root}" ] ||
    devops_fatal "shared runtime storage root is missing: ${target_root}${pool_root}"
done
unset pool_root

account_ids=$(devops_target_passwd_ids "$ACCOUNT_USERNAME")
[ -n "$account_ids" ] ||
  devops_fatal "target primary account is missing: $ACCOUNT_USERNAME"

DEVOPS_CODEX_STANDALONE_INSTALLER_HELPER=/usr/local/bin/codex-standalone-install
DEVOPS_CODEX_INSTALLER_SESSION_HELPER="${DEVOPS_CODEX_ROOT}/.installer-codex-standalone.session.py"
DEVOPS_CODEX_PACKAGES_ROOT="${DEVOPS_CODEX_ROOT}/packages"
DEVOPS_CODEX_SOCKETS_ROOT="${DEVOPS_CODEX_ROOT}/sockets"
DEVOPS_CODEX_CREDENTIALS_ROOT="${DEVOPS_CODEX_ROOT}/credentials"
DEVOPS_CODEX_APP_SERVER_SOCKET="${DEVOPS_CODEX_SOCKETS_ROOT}/app-server-control.sock"
DEVOPS_CODEX_APP_SERVER_BACKEND_SOCKET="${DEVOPS_CODEX_SOCKETS_ROOT}/app-server-backend.sock"
DEVOPS_CODEX_APP_SERVER_CONTROL_DIR="${DEVOPS_CODEX_HOME}/app-server-control"
DEVOPS_CODEX_APP_SERVER_STARTUP_LOCK="${DEVOPS_CODEX_APP_SERVER_CONTROL_DIR}/app-server-startup.lock"
DEVOPS_CODEX_APP_SERVER_DEFAULT_SOCKET="${DEVOPS_CODEX_APP_SERVER_CONTROL_DIR}/app-server-control.sock"
DEVOPS_CODEX_APP_SERVER_ENVIRONMENT=/etc/codex/app-server.env
DEVOPS_CODEX_APP_SERVER_READY_HELPER=/usr/local/libexec/codex-app-server-wait-ready
DEVOPS_CODEX_APP_SERVER_USER_UNIT="${ACCOUNT_HOME}/.config/systemd/user/codex-app-server.service"
DEVOPS_CODEX_APP_SERVER_USER_PROXY_UNIT="${ACCOUNT_HOME}/.config/systemd/user/codex-app-server-proxy.service"
DEVOPS_CODEX_APP_SERVER_USER_SOCKET_UNIT="${ACCOUNT_HOME}/.config/systemd/user/codex-app-server.socket"
DEVOPS_CODEX_APP_SERVER_USER_SOCKET_WANTS="${ACCOUNT_HOME}/.config/systemd/user/sockets.target.wants/codex-app-server.socket"
DEVOPS_CODEX_APP_SERVER_LEGACY_USER_WANTS="${ACCOUNT_HOME}/.config/systemd/user/default.target.wants/codex-app-server.service"

CARGO_HOME="${DIR_POOL_CACHE}/${ACCOUNT_USERNAME}/cargo"
CARGO_TARGET_DIR="${DIR_POOL_BUILD}/${ACCOUNT_USERNAME}/cargo/target"
CARGO_INSTALL_ROOT="${DIR_POOL_BUILD}/${ACCOUNT_USERNAME}/cargo/install"
RUSTUP_HOME="${DIR_POOL_DB}/${ACCOUNT_USERNAME}/rustup"
SCCACHE_DIR="${DIR_POOL_CACHE}/${ACCOUNT_USERNAME}/sccache"
GOPATH="${DIR_POOL_BUILD}/${ACCOUNT_USERNAME}/go"
GOMODCACHE="${DIR_POOL_CACHE}/${ACCOUNT_USERNAME}/go-mod"
MISE_DATA_DIR="${DIR_POOL_DB}/${ACCOUNT_USERNAME}/mise/data"
MISE_STATE_DIR="${DIR_POOL_DB}/${ACCOUNT_USERNAME}/mise/state"
MISE_CACHE_DIR="${DIR_POOL_CACHE}/${ACCOUNT_USERNAME}/mise"
MISE_TMP_DIR="${DIR_POOL_CACHE}/${ACCOUNT_USERNAME}/mise/tmp"
BAZEL_CACHE_HOME="${DEVOPS_BAZEL_CACHE_ROOT}/${ACCOUNT_USERNAME}/${DEVOPS_BAZEL_CACHE_SUBDIR}"
BAZEL_DISK_CACHE="${BAZEL_CACHE_HOME}/${DEVOPS_BAZEL_DISK_CACHE_SUBDIR}"
BAZEL_REPOSITORY_CACHE="${BAZEL_CACHE_HOME}/${DEVOPS_BAZEL_REPOSITORY_CACHE_SUBDIR}"
BAZEL_OUTPUT_USER_ROOT="${DEVOPS_BAZEL_BUILD_ROOT}/${ACCOUNT_USERNAME}/${DEVOPS_BAZEL_OUTPUT_USER_ROOT_SUBDIR}"
BAZELISK_HOME="${DEVOPS_BAZEL_DB_ROOT}/${ACCOUNT_USERNAME}/${DEVOPS_BAZELISK_HOME_SUBDIR}"
ANSIBLE_HOME="${DIR_POOL_DB}/${ACCOUNT_USERNAME}/ansible"
ANSIBLE_GALAXY_CACHE_DIR="${DIR_POOL_CACHE}/${ACCOUNT_USERNAME}/ansible/galaxy"
HASHICORP_CACHE_ROOT="${DIR_POOL_CACHE}/${ACCOUNT_USERNAME}/hashicorp"
PACKER_CACHE_DIR="${HASHICORP_CACHE_ROOT}/packer/cache"
PACKER_CONFIG_DIR="${HASHICORP_CACHE_ROOT}/packer.d"
PACKER_CONFIG_PATH="${PACKER_CONFIG_DIR}/config.json"
PACKER_PLUGIN_PATH="${PACKER_CONFIG_DIR}/plugins"
TF_PLUGIN_CACHE_DIR="${HASHICORP_CACHE_ROOT}/terraform/plugin-cache"
APTLY_ROOT_DIR="${DIR_POOL_DB}/${ACCOUNT_USERNAME}/${DEVOPS_APTLY_ROOT_SUBDIR}"
APTLY_CONFIG="${APTLY_ROOT_DIR}/aptly.conf"
APTLY_R2_STORAGE_PREFIX=${DEVOPS_APTLY_R2_PREFIX#/}
APTLY_R2_STORAGE_PREFIX="${APTLY_R2_STORAGE_PREFIX%/}/"
OSC_STATE_DIR="${DIR_POOL_DB}/${ACCOUNT_USERNAME}/${DEVOPS_OSC_STATE_SUBDIR}"
OSC_CONFIG="${OSC_STATE_DIR}/oscrc"
OSC_MANAGED_CONFIG="${OSC_STATE_DIR}/managed.json"
OSC_COOKIE_JAR="${OSC_STATE_DIR}/cookiejar"
OSC_WORKDIR="${DIR_POOL_BUILD}/${ACCOUNT_USERNAME}/${DEVOPS_OSC_BUILD_SUBDIR}"
OSC_BUILD_ROOT="${OSC_WORKDIR}/build-root"
OSC_PACKAGE_CACHE_DIR="${DIR_POOL_CACHE}/${ACCOUNT_USERNAME}/${DEVOPS_OSC_CACHE_SUBDIR}/packages"

for devops_path in \
  "$BAZEL_CACHE_HOME" \
  "$BAZEL_DISK_CACHE" \
  "$BAZEL_REPOSITORY_CACHE" \
  "$BAZEL_OUTPUT_USER_ROOT" \
  "$BAZELISK_HOME" \
  "$ANSIBLE_HOME" \
  "$ANSIBLE_GALAXY_CACHE_DIR" \
  "$HASHICORP_CACHE_ROOT" \
  "$PACKER_CACHE_DIR" \
  "$PACKER_CONFIG_DIR" \
  "$PACKER_CONFIG_PATH" \
  "$PACKER_PLUGIN_PATH" \
  "$TF_PLUGIN_CACHE_DIR" \
  "$GOPATH" \
  "$GOMODCACHE" \
  "$APTLY_ROOT_DIR" \
  "$APTLY_CONFIG" \
  "$OSC_STATE_DIR" \
  "$OSC_CONFIG" \
  "$OSC_MANAGED_CONFIG" \
  "$OSC_COOKIE_JAR" \
  "$OSC_WORKDIR" \
  "$OSC_BUILD_ROOT" \
  "$OSC_PACKAGE_CACHE_DIR" \
  "$DEVOPS_CODEX_STANDALONE_INSTALLER_HELPER" \
  "$DEVOPS_CODEX_INSTALLER_SESSION_HELPER" \
  "$DEVOPS_CODEX_PACKAGES_ROOT" \
  "$DEVOPS_CODEX_SOCKETS_ROOT" \
  "$DEVOPS_CODEX_CREDENTIALS_ROOT" \
  "$DEVOPS_CODEX_APP_SERVER_SOCKET" \
  "$DEVOPS_CODEX_APP_SERVER_BACKEND_SOCKET" \
  "$DEVOPS_CODEX_APP_SERVER_CONTROL_DIR" \
  "$DEVOPS_CODEX_APP_SERVER_STARTUP_LOCK" \
  "$DEVOPS_CODEX_APP_SERVER_DEFAULT_SOCKET" \
  "$DEVOPS_CODEX_APP_SERVER_ENVIRONMENT" \
  "$DEVOPS_CODEX_APP_SERVER_READY_HELPER" \
  "$DEVOPS_CODEX_APP_SERVER_USER_UNIT" \
  "$DEVOPS_CODEX_APP_SERVER_USER_PROXY_UNIT" \
  "$DEVOPS_CODEX_APP_SERVER_USER_SOCKET_UNIT" \
  "$DEVOPS_CODEX_APP_SERVER_USER_SOCKET_WANTS" \
  "$DEVOPS_CODEX_APP_SERVER_LEGACY_USER_WANTS"
do
  devops_validate_abs_path "derived DevOps path" "$devops_path"
done
unset devops_path

# shellcheck disable=SC2016
run_in_target "create desktop DevOps runtime directories" /bin/sh -eu -c '
account_user=$1
build_root=$2
cache_root=$3
db_root=$4
bazel_cache_subdir=$5
bazel_disk_cache_subdir=$6
bazel_repository_cache_subdir=$7
bazel_output_user_root_subdir=$8
bazelisk_home_subdir=$9

for required_command in getent install; do
  command -v "$required_command" >/dev/null 2>&1 || {
    printf "fatal: required DevOps target command is unavailable: %s\n" "$required_command" >&2
    exit 1
  }
done
getent group devops >/dev/null 2>&1 || {
  printf "fatal: required target group is missing: devops\n" >&2
  exit 1
}

for runtime_path in \
  "$build_root/$account_user" \
  "$build_root/$account_user/cargo" \
  "$build_root/$account_user/cargo/target" \
  "$build_root/$account_user/cargo/install" \
  "$build_root/$account_user/deno" \
  "$build_root/$account_user/deno/bin" \
  "$build_root/$account_user/go" \
  "$build_root/$account_user/go/bin" \
  "$build_root/$account_user/npm-global" \
  "$build_root/$account_user/pnpm" \
  "$build_root/$account_user/pnpm/bin" \
  "$build_root/$account_user/pnpm/global" \
  "$build_root/$account_user/python" \
  "$build_root/$account_user/python/bin" \
  "$build_root/$account_user/uv" \
  "$build_root/$account_user/uv/bin" \
  "$build_root/$account_user/yarn-global" \
  "$build_root/$account_user/$bazel_output_user_root_subdir" \
  "$cache_root/$account_user" \
  "$cache_root/$account_user/cargo" \
  "$cache_root/$account_user/deno" \
  "$cache_root/$account_user/mise" \
  "$cache_root/$account_user/mise/tmp" \
  "$cache_root/$account_user/npm" \
  "$cache_root/$account_user/corepack" \
  "$cache_root/$account_user/go-mod" \
  "$cache_root/$account_user/pnpm" \
  "$cache_root/$account_user/pnpm/cache" \
  "$cache_root/$account_user/pnpm/store" \
  "$cache_root/$account_user/pip" \
  "$cache_root/$account_user/ansible" \
  "$cache_root/$account_user/ansible/galaxy" \
  "$cache_root/$account_user/hashicorp" \
  "$cache_root/$account_user/hashicorp/packer" \
  "$cache_root/$account_user/hashicorp/packer/cache" \
  "$cache_root/$account_user/hashicorp/packer.d" \
  "$cache_root/$account_user/hashicorp/packer.d/plugins" \
  "$cache_root/$account_user/hashicorp/terraform" \
  "$cache_root/$account_user/hashicorp/terraform/plugin-cache" \
  "$cache_root/$account_user/sccache" \
  "$cache_root/$account_user/uv" \
  "$cache_root/$account_user/yarn" \
  "$cache_root/$account_user/$bazel_cache_subdir" \
  "$cache_root/$account_user/$bazel_cache_subdir/$bazel_disk_cache_subdir" \
  "$cache_root/$account_user/$bazel_cache_subdir/$bazel_repository_cache_subdir" \
  "$db_root/$account_user" \
  "$db_root/$account_user/ansible" \
  "$db_root/$account_user/deno" \
  "$db_root/$account_user/mise" \
  "$db_root/$account_user/mise/data" \
  "$db_root/$account_user/mise/state" \
  "$db_root/$account_user/node" \
  "$db_root/$account_user/pnpm" \
  "$db_root/$account_user/pnpm/state" \
  "$db_root/$account_user/python" \
  "$db_root/$account_user/rustup" \
  "$db_root/$account_user/uv" \
  "$db_root/$account_user/uv/tools" \
  "$db_root/$account_user/$bazelisk_home_subdir"
do
  install -d -m 2770 -o "$account_user" -g devops -- "$runtime_path"
done
' sh \
  "$ACCOUNT_USERNAME" \
  "$DIR_POOL_BUILD" \
  "$DIR_POOL_CACHE" \
  "$DIR_POOL_DB" \
  "$DEVOPS_BAZEL_CACHE_SUBDIR" \
  "$DEVOPS_BAZEL_DISK_CACHE_SUBDIR" \
  "$DEVOPS_BAZEL_REPOSITORY_CACHE_SUBDIR" \
  "$DEVOPS_BAZEL_OUTPUT_USER_ROOT_SUBDIR" \
  "$DEVOPS_BAZELISK_HOME_SUBDIR"

install -d -m 0700 "$tmp_env_dir"
devops_prepare_publishing_layout
devops_render_aptly_config
devops_import_aptly_signing_key
devops_render_osc_config
devops_stage_publishing_entrypoints
devops_stage_pending_credentials
unset \
  DEVOPS_CF_R2_ACCESS_KEY \
  DEVOPS_CF_R2_SECRET_KEY \
  DEVOPS_OBS_USERNAME \
  DEVOPS_OBS_PASSWORD
devops_codex_archive_helper_path="${DEVOPS_CODEX_ROOT}/.installer-codex-archive.py"
devops_render_codex_sysctl
devops_render_codex_tmpfiles
devops_render_codex_logrotate
devops_prepare_codex_layout
devops_stage_target_asset \
  "$(installer_repo_join_var DIR_HOOKS_TARGET data/codex/lib/codex)" \
  "$DEVOPS_CODEX_WRAPPER_PATH" \
  0755 \
  codex-wrapper
chown root:root "${target_root}${DEVOPS_CODEX_WRAPPER_PATH}"
devops_stage_target_asset \
  "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/libexec/codex-app-server-wait-ready)" \
  "$DEVOPS_CODEX_APP_SERVER_READY_HELPER" \
  0755 \
  codex-app-server-ready-helper
chown root:root "${target_root}${DEVOPS_CODEX_APP_SERVER_READY_HELPER}"
devops_stage_target_asset \
  "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/bin/codex-standalone-install)" \
  "$DEVOPS_CODEX_STANDALONE_INSTALLER_HELPER" \
  0755 \
  codex-standalone-installer
chown root:root "${target_root}${DEVOPS_CODEX_STANDALONE_INSTALLER_HELPER}"
devops_stage_target_asset \
  "$(installer_repo_join_var DIR_SCRIPTS_LATE codex-installer-session.py)" \
  "$DEVOPS_CODEX_INSTALLER_SESSION_HELPER" \
  0700 \
  codex-installer-session
chown root:root "${target_root}${DEVOPS_CODEX_INSTALLER_SESSION_HELPER}"
devops_stage_target_asset \
  "$(installer_repo_join_var DIR_SCRIPTS_LATE codex-archive.py)" \
  "$devops_codex_archive_helper_path" \
  0700 \
  codex-archive-helper
chown root:root "${target_root}${devops_codex_archive_helper_path}"
devops_stage_target_asset \
  "$(installer_repo_join_var DIR_SCRIPTS_LATE codex-state.py)" \
  "${DEVOPS_CODEX_ROOT}/.installer-codex-state.py" \
  0700 \
  codex-state-verifier
chown root:root "${target_root}${DEVOPS_CODEX_ROOT}/.installer-codex-state.py"
devops_install_pinned_codex
devops_apply_codex_tmpfiles
devops_stage_codex_app_server
devops_render_bazelrc
devops_render_cargo_config
devops_render_packer_template
devops_write_packer_config

devops_install_pinned_node_runtimes
devops_install_upstream_tools
devops_initialize_packer_plugins
devops_initialize_aptly_repositories
devops_install_pinned_rustup
devops_install_pinned_bazelisk
devops_install_llama_runtime
codex_binary_dir_host="${target_root}${DEVOPS_CODEX_ROOT}/share/bin"
codex_first_binary=$(find "$codex_binary_dir_host" \
  -mindepth 1 -maxdepth 1 -type f -links 1 -print)
[ -n "$codex_first_binary" ] ||
  devops_fatal "managed Codex binary directory is empty after installation"
[ -x "${target_root}${DEVOPS_CODEX_BINARY_PATH}" ] ||
  devops_fatal "managed Codex entrypoint is missing after installation"
codex_unsafe_binary=$(find "$codex_binary_dir_host" \
  -mindepth 1 -maxdepth 1 \( ! -type f -o -type l -o ! -links 1 \) -print)
[ -z "$codex_unsafe_binary" ] ||
  devops_fatal "managed Codex binary directory contains an unsafe entry"
unset codex_binary_dir_host codex_first_binary codex_unsafe_binary
[ -r "${target_root}${DEVOPS_CODEX_SCHEMA_PATH}" ] ||
  devops_fatal "pinned Codex configuration schema is missing after installation"
[ -x "${target_root}${DEVOPS_CODEX_WRAPPER_PATH}" ] ||
  devops_fatal "managed Codex wrapper is missing after installation"
[ -f "${target_root}${DEVOPS_CODEX_APP_SERVER_READY_HELPER}" ] &&
  [ ! -L "${target_root}${DEVOPS_CODEX_APP_SERVER_READY_HELPER}" ] &&
  [ -x "${target_root}${DEVOPS_CODEX_APP_SERVER_READY_HELPER}" ] ||
  devops_fatal "Codex app-server readiness helper is missing or unsafe"
[ -f "${target_root}${DEVOPS_CODEX_STANDALONE_INSTALLER_HELPER}" ] &&
  [ ! -L "${target_root}${DEVOPS_CODEX_STANDALONE_INSTALLER_HELPER}" ] &&
  [ -x "${target_root}${DEVOPS_CODEX_STANDALONE_INSTALLER_HELPER}" ] ||
  devops_fatal "target Codex standalone installer is missing or unsafe"
[ "$(chroot "$target_root" /usr/bin/find -P "${DEVOPS_CODEX_STANDALONE_INSTALLER_HELPER}" -maxdepth 0 -printf '%U:%G:%m')" = 0:0:755 ] ||
  devops_fatal "target Codex standalone installer ownership or mode is invalid"
[ -f "${target_root}${DEVOPS_CODEX_INSTALLER_SESSION_HELPER}" ] &&
  [ ! -L "${target_root}${DEVOPS_CODEX_INSTALLER_SESSION_HELPER}" ] &&
  [ -x "${target_root}${DEVOPS_CODEX_INSTALLER_SESSION_HELPER}" ] ||
  devops_fatal "temporary Codex installer supervisor is missing or unsafe"
[ "$(chroot "$target_root" /usr/bin/find -P "${DEVOPS_CODEX_INSTALLER_SESSION_HELPER}" -maxdepth 0 -printf '%U:%G:%m')" = 0:0:700 ] ||
  devops_fatal "temporary Codex installer supervisor ownership or mode is invalid"
[ -r "${target_root}${DEVOPS_CODEX_APP_SERVER_ENVIRONMENT}" ] ||
  devops_fatal "Codex app-server environment policy is missing after installation"
[ -r "${target_root}${DEVOPS_CODEX_APP_SERVER_USER_UNIT}" ] ||
  devops_fatal "Codex app-server backend unit is missing after installation"
[ -r "${target_root}${DEVOPS_CODEX_APP_SERVER_USER_PROXY_UNIT}" ] ||
  devops_fatal "Codex app-server proxy unit is missing after installation"
[ -r "${target_root}${DEVOPS_CODEX_APP_SERVER_USER_SOCKET_UNIT}" ] ||
  devops_fatal "Codex app-server activation socket is missing after installation"
[ -L "${target_root}${DEVOPS_CODEX_APP_SERVER_USER_SOCKET_WANTS}" ] &&
  [ "$(readlink -- "${target_root}${DEVOPS_CODEX_APP_SERVER_USER_SOCKET_WANTS}")" = ../codex-app-server.socket ] ||
  devops_fatal "Codex app-server socket is not enabled for the account sockets target"
[ ! -e "${target_root}${DEVOPS_CODEX_APP_SERVER_LEGACY_USER_WANTS}" ] &&
  [ ! -L "${target_root}${DEVOPS_CODEX_APP_SERVER_LEGACY_USER_WANTS}" ] ||
  devops_fatal "Codex app-server backend remains enabled for the account default target"
[ ! -e "${target_root}${devops_codex_archive_helper_path}" ] &&
  [ ! -L "${target_root}${devops_codex_archive_helper_path}" ] ||
  devops_fatal "temporary Codex archive helper remains after installation"
[ -d "${target_root}${DEVOPS_CODEX_USER_ROOT}/.git" ] ||
  devops_fatal "cloned Codex home repository metadata is missing after installation"
[ -d "${target_root}${DEVOPS_CODEX_SYSTEM_CONFIG_DIR}" ] ||
  devops_fatal "Codex system configuration directory is missing after installation"
[ -r "${target_root}/etc/sysctl.d/90-codex-bwrap.conf" ] ||
  devops_fatal "Codex Bubblewrap user-namespace sysctl policy is missing after installation"
[ -r "${target_root}/etc/tmpfiles.d/80-codex-storage.conf" ] ||
  devops_fatal "Codex ownership tmpfiles policy is missing after installation"
[ -r "${target_root}/etc/logrotate.d/codex" ] ||
  devops_fatal "Codex log rotation policy is missing after installation"
[ -x "${target_root}${DEVOPS_RUSTUP_BINARY_PATH}" ] ||
  devops_fatal "Rustup bootstrap is missing after installation"
[ -x "${target_root}${DEVOPS_BAZELISK_BINARY_PATH}" ] ||
  devops_fatal "pinned Bazelisk binary is missing after installation: ${DEVOPS_BAZELISK_BINARY_PATH}"
[ -x "${target_root}${DEVOPS_DENO_BINARY_PATH}" ] ||
  devops_fatal "Deno upstream executable is missing after installation"
[ -x "${target_root}${DEVOPS_YT_DLP_BINARY_PATH}" ] ||
  devops_fatal "managed yt-dlp wrapper is missing after installation"
[ -x "${target_root}${DEVOPS_YT_DLP_PAYLOAD_PATH}" ] ||
  devops_fatal "yt-dlp standalone payload with bundled yt-dlp-ejs is missing after installation"
[ -r "${target_root}/etc/skel-desktop/.config/bazel/bazelrc" ] ||
  devops_fatal "managed Bazel rc is missing from the desktop skeleton"
[ -x "${target_root}${DEVOPS_ANSIBLE_CORE_BINARY_PATH}" ] ||
  devops_fatal "Ansible upstream executable is missing after installation"
[ -x "${target_root}${DEVOPS_OPENTOFU_BINARY_PATH}" ] ||
  devops_fatal "OpenTofu upstream executable is missing after installation"
[ -x "${target_root}${DEVOPS_TERRAFORM_BINARY_PATH}" ] ||
  devops_fatal "Terraform upstream executable is missing after installation"
[ -x "${target_root}${DEVOPS_PACKER_BINARY_PATH}" ] ||
  devops_fatal "Packer upstream executable is missing after installation"
[ -r "${target_root}/etc/skel-desktop/.config/packer/template.pkr.hcl" ] ||
  devops_fatal "managed Packer template is missing from the desktop skeleton"
[ -r "${target_root}${ACCOUNT_HOME}/.config/packer/template.pkr.hcl" ] ||
  devops_fatal "managed Packer template is missing from the primary account"
[ -r "${target_root}${PACKER_CONFIG_PATH}" ] ||
  devops_fatal "managed Packer JSON config is missing after installation"
[ -x "${target_root}${DEVOPS_WRANGLER_BINARY_PATH}" ] ||
  devops_fatal "Wrangler upstream executable is missing after installation"
[ -x "${target_root}${DEVOPS_APTLY_BINARY_PATH}" ] ||
  devops_fatal "Aptly upstream executable is missing after installation"
[ -x "${target_root}${DEVOPS_OSC_BINARY_PATH}" ] ||
  devops_fatal "osc upstream executable is missing after installation"
# The pinned obs-build Makefile publishes bin/build as an absolute symlink
# below DEVOPS_OBS_BUILD_INSTALL_ROOT.  Validate primary-account access inside
# the target; an outer /target check resolves that link against the installer.
devops_run_as_account \
  "verify primary-account access to obs-build after installation" \
  /usr/bin/test -x "$DEVOPS_OBS_BUILD_BINARY_PATH"
[ ! -e "${target_root}/tmp/installer-devops-tools.py" ] &&
  [ ! -L "${target_root}/tmp/installer-devops-tools.py" ] ||
  devops_fatal "temporary upstream DevOps tool installer remains after installation"
[ ! -e "${target_root}/tmp/installer-devops-tools-policy.json" ] &&
  [ ! -L "${target_root}/tmp/installer-devops-tools-policy.json" ] ||
  devops_fatal "temporary upstream DevOps tool policy remains after installation"
[ -r "${target_root}${APTLY_CONFIG}" ] ||
  devops_fatal "managed Aptly config is missing after installation"
[ -r "${target_root}${OSC_CONFIG}" ] ||
  devops_fatal "managed osc config is missing after installation"
[ -r "${target_root}${OSC_MANAGED_CONFIG}" ] ||
  devops_fatal "managed osc metadata is missing after installation"
[ -x "${target_root}/usr/local/libexec/aptly-publishing" ] ||
  devops_fatal "managed Aptly publication wrapper is missing after installation"
[ -x "${target_root}/usr/local/libexec/obs-publishing" ] ||
  devops_fatal "managed OBS publication wrapper is missing after installation"
for aptly_publishing_command in \
  aptly \
  aptly-publish-local \
  dpkg-buildpackage
do
  publishing_link="${target_root}/usr/local/libexec/aptly-publishing-bin/${aptly_publishing_command}"
  [ -L "$publishing_link" ] &&
    [ "$(readlink "$publishing_link")" = ../aptly-publishing ] ||
    devops_fatal "managed Aptly publication command link is invalid: ${aptly_publishing_command}"
done
for obs_publishing_command in \
  obs-checkout-source \
  obs-publish-source \
  osc
do
  publishing_link="${target_root}/usr/local/libexec/obs-publishing-bin/${obs_publishing_command}"
  [ -L "$publishing_link" ] &&
    [ "$(readlink "$publishing_link")" = ../obs-publishing ] ||
    devops_fatal "managed OBS publication command link is invalid: ${obs_publishing_command}"
done
unset aptly_publishing_command obs_publishing_command publishing_link

devops_run_as_account \
  "initialize pinned Rustup with the profile-selected toolchain without changing shell startup files" \
  /usr/bin/timeout \
    --signal=TERM \
    --kill-after=30s \
    1200s \
    "$DEVOPS_RUSTUP_BINARY_PATH" \
      -y \
      --no-modify-path \
      --default-toolchain \
      "$DEVOPS_RUSTUP_TOOLCHAIN" \
      --profile \
      minimal
devops_install_pinned_rust_cli_binaries
# shellcheck disable=SC2016
devops_run_as_account \
  "install rustfmt and source-selected pinned Rust CLI tools" \
  /bin/sh -eu -c '
dotslash_source_build=$1
dotslash_version=$2
dotslash_commit=$3
dotslash_repository_url=$4
uv_source_build=$5
uv_version=$6

for tool_version in "$dotslash_version" "$uv_version"; do
  printf "%s\n" "$tool_version" |
    grep -Eq "^[0-9]+\.[0-9]+\.[0-9]+$" || {
    printf "fatal: Rust CLI tool version is malformed\n" >&2
    exit 1
  }
done
unset tool_version
for source_build_flag in "$dotslash_source_build" "$uv_source_build"; do
  case "$source_build_flag" in
    0|1) ;;
    *)
      printf "fatal: Rust CLI source-build flag must be 0 or 1\n" >&2
      exit 1
      ;;
  esac
done
unset source_build_flag
[ "${#dotslash_commit}" -eq 40 ] &&
  ! printf "%s\n" "$dotslash_commit" | grep -q "[^0-9a-f]" || {
    printf "fatal: DotSlash commit is malformed\n" >&2
    exit 1
  }
case "$dotslash_repository_url" in
  https://github.com/*) ;;
  *)
    printf "fatal: DotSlash repository URL is not HTTPS GitHub\n" >&2
    exit 1
    ;;
esac

for required_command in cargo rustup; do
  command -v "$required_command" >/dev/null 2>&1 || {
    printf "fatal: required Rust tool command is unavailable: %s\n" "$required_command" >&2
    exit 1
  }
done
[ -x /usr/bin/timeout ] || {
  printf "fatal: required Rust tool command is unavailable: /usr/bin/timeout\n" >&2
  exit 1
}

/usr/bin/timeout \
  --signal=TERM \
  --kill-after=30s \
  1200s \
  rustup component add rustfmt

if [ "$dotslash_source_build" = 1 ]; then
  CARGO_NET_RETRY=3 \
    /usr/bin/timeout \
      --signal=TERM \
      --kill-after=30s \
      3600s \
      cargo install \
        --locked \
        --root "$CARGO_INSTALL_ROOT" \
        --git "$dotslash_repository_url" \
        --rev "$dotslash_commit" \
        dotslash
fi

if [ "$uv_source_build" = 1 ]; then
  CARGO_NET_RETRY=3 \
    /usr/bin/timeout \
      --signal=TERM \
      --kill-after=30s \
      7200s \
      cargo install \
        --locked \
        --root "$CARGO_INSTALL_ROOT" \
        --version "$uv_version" \
        uv
fi
' sh \
  "$DEVOPS_DOTSLASH_SOURCE_BUILD" \
  "$DEVOPS_DOTSLASH_VERSION" \
  "$DEVOPS_DOTSLASH_COMMIT" \
  "$DEVOPS_DOTSLASH_REPOSITORY_URL" \
  "$DEVOPS_UV_SOURCE_BUILD" \
  "$DEVOPS_UV_VERSION"
# shellcheck disable=SC2016
devops_run_as_account "verify Rustup, rustfmt, Cargo tools, and sccache" /bin/sh -eu -c '
expected_rustc_wrapper=$1
expected_target_triple=$2
expected_target_linker=$3
expected_target_cpu=$4
expected_linker_argument=$5
expected_dotslash_version=$6
expected_uv_version=$7
expected_rustup_binary=$8
expected_rustup_toolchain=$9
node_22_root=${10}
node_24_root=${11}
node_26_root=${12}

command -v rustup >/dev/null 2>&1
command -v cargo >/dev/null 2>&1
command -v rustc >/dev/null 2>&1
command -v rustfmt >/dev/null 2>&1
command -v dotslash >/dev/null 2>&1
command -v uv >/dev/null 2>&1
command -v uvx >/dev/null 2>&1
command -v sccache >/dev/null 2>&1
command -v mold >/dev/null 2>&1
test -x /usr/bin/clang-24
for llvm_binary in \
  /usr/lib/llvm-24/bin/clang \
  /usr/lib/llvm-24/bin/clang++ \
  /usr/lib/llvm-24/bin/llvm-config \
  /usr/lib/llvm-24/bin/lld \
  /usr/lib/llvm-24/bin/ld.lld \
  /usr/lib/llvm-24/bin/lldb
do
  test -x "$llvm_binary"
done
test -r "$CARGO_HOME/config.toml"
test -x "$expected_rustup_binary"
for node_root in "$node_22_root" "$node_24_root" "$node_26_root"; do
  test -x "${node_root}/bin/corepack"
  test -x "${node_root}/bin/pnpm"
  test -x "${node_root}/bin/yarn"
done
rustup show active-toolchain >/dev/null
rustup show active-toolchain | grep -Fq -- "$expected_rustup_toolchain"
rustup component list --installed | grep -Eq "^rustfmt-"
cargo --version >/dev/null
rustc --version >/dev/null
rustfmt --version >/dev/null
dotslash --version | grep -Fq "$expected_dotslash_version"
uv --version | grep -Fq "$expected_uv_version"
uvx --version | grep -Fq "$expected_uv_version"
sccache --version >/dev/null
rustc --print target-cpus |
  LC_ALL=C awk -v wanted="$expected_target_cpu" \
    '\''$1 == wanted { found = 1 } END { exit found ? 0 : 1 }'\''
grep -Fqx "rustc-wrapper = \"${expected_rustc_wrapper}\"" "$CARGO_HOME/config.toml"
grep -Fqx "[target.\"${expected_target_triple}\"]" "$CARGO_HOME/config.toml"
grep -Fqx "linker = \"${expected_target_linker}\"" "$CARGO_HOME/config.toml"
grep -Fqx "  \"target-cpu=${expected_target_cpu}\"," "$CARGO_HOME/config.toml"
grep -Fqx "  \"link-arg=${expected_linker_argument}\"," "$CARGO_HOME/config.toml"
' sh \
  "$DEVOPS_CARGO_RUSTC_WRAPPER" \
  "$DEVOPS_CARGO_TARGET_TRIPLE" \
  "$DEVOPS_CARGO_TARGET_LINKER" \
  "$DEVOPS_CARGO_TARGET_CPU" \
  "$DEVOPS_CARGO_LINKER_ARGUMENT" \
  "$DEVOPS_DOTSLASH_VERSION" \
  "$DEVOPS_UV_VERSION" \
  "$DEVOPS_RUSTUP_BINARY_PATH" \
  "$DEVOPS_RUSTUP_TOOLCHAIN" \
  "$DEVOPS_NODE_22_INSTALL_ROOT" \
  "$DEVOPS_NODE_24_INSTALL_ROOT" \
  "$DEVOPS_NODE_26_INSTALL_ROOT"

# shellcheck disable=SC2016
devops_run_as_account "link preinstalled Node runtimes into Mise" /bin/sh -eu -c '
command -v mise >/dev/null 2>&1
for mise_directory in \
  "$MISE_CONFIG_DIR" \
  "$MISE_DATA_DIR" \
  "$MISE_STATE_DIR" \
  "$MISE_CACHE_DIR" \
  "$MISE_TMP_DIR"
do
  [ -d "$mise_directory" ] && [ ! -L "$mise_directory" ] || {
    printf "fatal: managed Mise directory is unavailable or unsafe: %s\n" "$mise_directory" >&2
    exit 1
  }
done
while [ "$#" -gt 0 ]; do
  node_version=$1
  node_root=$2
  shift 2
  test -x "${node_root}/bin/node"
  mise link --force "node@${node_version}" "$node_root"
done
mise reshim
' sh \
  "$DEVOPS_NODE_22_MAJOR" "$DEVOPS_NODE_22_INSTALL_ROOT" \
  "$DEVOPS_NODE_24_MAJOR" "$DEVOPS_NODE_24_INSTALL_ROOT" \
  "$DEVOPS_NODE_26_MAJOR" "$DEVOPS_NODE_26_INSTALL_ROOT"

  devops_info \
  "configured desktop toolchains account=${ACCOUNT_USERNAME} codex=${DEVOPS_CODEX_VERSION} sandbox=bubblewrap+slirp4netns llama_release=${LLAMA_RELEASE_ARCHIVE_ROOT} node=${DEVOPS_NODE_22_MAJOR},${DEVOPS_NODE_24_MAJOR},${DEVOPS_NODE_26_MAJOR} via Mise Corepack=enabled deno=${DEVOPS_DENO_VERSION} yt-dlp=${DEVOPS_YT_DLP_VERSION}+bundled-yt-dlp-ejs ffmpeg=system rustup=${DEVOPS_RUSTUP_VERSION} toolchain=${DEVOPS_RUSTUP_TOOLCHAIN} rustfmt=enabled dotslash=${DEVOPS_DOTSLASH_VERSION}@${DEVOPS_DOTSLASH_COMMIT}:source-build=${DEVOPS_DOTSLASH_SOURCE_BUILD} uv=${DEVOPS_UV_VERSION}:source-build=${DEVOPS_UV_SOURCE_BUILD} cargo_target_cpu=${DEVOPS_CARGO_TARGET_CPU} cargo_jobs=cargo-default llvm=24 direct bazelisk=${DEVOPS_BAZELISK_VERSION} ansible-core=${DEVOPS_ANSIBLE_CORE_VERSION} opentofu=${DEVOPS_OPENTOFU_VERSION} terraform=${DEVOPS_TERRAFORM_VERSION} packer=${DEVOPS_PACKER_VERSION} wrangler=${DEVOPS_WRANGLER_VERSION} aptly=${DEVOPS_APTLY_RELEASE_VERSION} osc=${DEVOPS_OSC_RELEASE_VERSION} obs-build=${DEVOPS_OBS_BUILD_TAG} publication=stable,testing:r2+home:cramerz:debian"
}
