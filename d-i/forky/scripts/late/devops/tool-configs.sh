#!/bin/sh
# Sourced installer module; edit this file directly.

devops_install_llama_runtime() {
  llama_repo_path=$(installer_repo_join_var DIR_SCRIPTS_LATE llama.sh)
  llama_installer="${tmp_env_dir}/installer-llama-entry.$$"

  bootstrap_fetch_seed_file \
    "$seed_base" \
    "$llama_repo_path" \
    "$llama_installer" \
    0600 \
    "DevOps llama.cpp installer helper ${llama_repo_path}"
  chmod 0700 "$llama_installer"

  if ! INSTALLER_RUNTIME_DIR="$runtime_dir" \
       INSTALLER_BOOTSTRAP_LIB="$bootstrap_lib" \
       INSTALLER_LATE_HOST_ENV="$host_env" \
       INSTALLER_LLAMA_TMP_ENV_DIR="${tmp_env_dir}/llama" \
       /bin/sh "$llama_installer" "$target_root"
  then
    rm -f -- "$llama_installer"
    devops_fatal "llama.cpp provisioning failed"
  fi
  rm -f -- "$llama_installer"
}

devops_render_cargo_config() {
  template_repo_path=$(installer_repo_join_var \
    DIR_HOOKS_TARGET \
    etc/skel-desktop/.config/cargo/config.toml.tmpl)
  template_tmp="${tmp_env_dir}/cargo-config.toml.tmpl.$$"
  rendered_tmp="${tmp_env_dir}/cargo-config.toml.rendered.$$"
  target_cargo_dir="${target_root}${CARGO_HOME}"
  target_cargo_config="${target_cargo_dir}/config.toml"

  bootstrap_fetch_seed_file \
    "$seed_base" \
    "$template_repo_path" \
    "$template_tmp" \
    0600 \
    "DevOps Cargo config template ${template_repo_path}"
  installer_apply_scalar_placeholders \
    "$template_tmp" \
    "$rendered_tmp" \
    DEVOPS_CARGO_RUSTC_WRAPPER "$DEVOPS_CARGO_RUSTC_WRAPPER" \
    DEVOPS_CARGO_TARGET_TRIPLE "$DEVOPS_CARGO_TARGET_TRIPLE" \
    DEVOPS_CARGO_TARGET_LINKER "$DEVOPS_CARGO_TARGET_LINKER" \
    DEVOPS_CARGO_TARGET_CPU "$DEVOPS_CARGO_TARGET_CPU" \
    DEVOPS_CARGO_LINKER_ARGUMENT "$DEVOPS_CARGO_LINKER_ARGUMENT"
  installer_assert_no_unresolved_installer_placeholders \
    "$rendered_tmp" \
    "DevOps Cargo config template ${template_repo_path}"

  [ -d "$target_cargo_dir" ] ||
    devops_fatal "required Cargo home directory is missing: ${target_cargo_dir}"
  install -m 0644 "$rendered_tmp" "$target_cargo_config"
  chown "$account_ids" "$target_cargo_config"
  rm -f -- "$template_tmp" "$rendered_tmp"
}

devops_render_codex_sysctl() {
  template_repo_path=$(installer_repo_join_var \
    DIR_HOOKS_TARGET \
    etc/sysctl.d/90-codex-bwrap.conf.tmpl)
  template_tmp="${tmp_env_dir}/codex-bwrap-sysctl.tmpl.$$"
  rendered_tmp="${tmp_env_dir}/codex-bwrap-sysctl.rendered.$$"
  target_sysctl_dir="${target_root}/etc/sysctl.d"
  target_sysctl="${target_sysctl_dir}/90-codex-bwrap.conf"

  bootstrap_fetch_seed_file \
    "$seed_base" \
    "$template_repo_path" \
    "$template_tmp" \
    0600 \
    "DevOps Codex Bubblewrap sysctl template ${template_repo_path}"
  installer_apply_scalar_placeholders \
    "$template_tmp" \
    "$rendered_tmp" \
    DEVOPS_CODEX_BWRAP_USERNS_CLONE "$DEVOPS_CODEX_BWRAP_USERNS_CLONE" \
    DEVOPS_CODEX_BWRAP_MAX_USER_NAMESPACES "$DEVOPS_CODEX_BWRAP_MAX_USER_NAMESPACES"
  installer_assert_no_unresolved_installer_placeholders \
    "$rendered_tmp" \
    "DevOps Codex Bubblewrap sysctl template ${template_repo_path}"

  install -d -m 0755 "$target_sysctl_dir"
  install -m 0644 "$rendered_tmp" "$target_sysctl"
  chown root:root "$target_sysctl_dir" "$target_sysctl"
  rm -f -- "$template_tmp" "$rendered_tmp"
}

devops_render_codex_tmpfiles() {
  template_repo_path=$(installer_repo_join_var \
    DIR_HOOKS_TARGET \
    etc/tmpfiles.d/80-codex-storage.conf.tmpl)
  template_tmp="${tmp_env_dir}/codex-storage-tmpfiles.tmpl.$$"
  rendered_tmp="${tmp_env_dir}/codex-storage-tmpfiles.rendered.$$"
  target_tmpfiles_dir="${target_root}/etc/tmpfiles.d"
  target_tmpfiles="${target_tmpfiles_dir}/80-codex-storage.conf"

  bootstrap_fetch_seed_file \
    "$seed_base" \
    "$template_repo_path" \
    "$template_tmp" \
    0600 \
    "DevOps Codex tmpfiles template ${template_repo_path}"
  installer_apply_scalar_placeholders \
    "$template_tmp" \
    "$rendered_tmp" \
    ACCOUNT_USERNAME "$ACCOUNT_USERNAME" \
    DEVOPS_CODEX_ROOT "$DEVOPS_CODEX_ROOT" \
    DEVOPS_CODEX_BINARY_PATH "$DEVOPS_CODEX_BINARY_PATH" \
    DEVOPS_CODEX_WRAPPER_PATH "$DEVOPS_CODEX_WRAPPER_PATH" \
    DEVOPS_CODEX_USER_ROOT "$DEVOPS_CODEX_USER_ROOT" \
    DEVOPS_CODEX_SYSTEM_CONFIG_DIR "$DEVOPS_CODEX_SYSTEM_CONFIG_DIR" \
    DEVOPS_CODEX_LOG_DIR "$DEVOPS_CODEX_LOG_DIR" \
    DEVOPS_CODEX_SQLITE_HOME "$DEVOPS_CODEX_SQLITE_HOME" \
    DEVOPS_CODEX_RUNTIME_ROOT "$DEVOPS_CODEX_RUNTIME_ROOT" \
    DEVOPS_CODEX_AGENTS "$DEVOPS_CODEX_AGENTS" \
    DEVOPS_CODEX_HOME "$DEVOPS_CODEX_HOME" \
    DEVOPS_CODEX_SKILLS "$DEVOPS_CODEX_SKILLS"
  installer_assert_no_unresolved_installer_placeholders \
    "$rendered_tmp" \
    "DevOps Codex tmpfiles template ${template_repo_path}"

  install -d -m 0755 "$target_tmpfiles_dir"
  install -m 0644 "$rendered_tmp" "$target_tmpfiles"
  chown root:root "$target_tmpfiles_dir" "$target_tmpfiles"
  rm -f -- "$template_tmp" "$rendered_tmp"
}

devops_render_codex_logrotate() {
  template_repo_path=$(installer_repo_join_var \
    DIR_HOOKS_TARGET \
    etc/logrotate.d/codex.tmpl)
  template_tmp="${tmp_env_dir}/codex-logrotate.tmpl.$$"
  rendered_tmp="${tmp_env_dir}/codex-logrotate.rendered.$$"
  target_logrotate_dir="${target_root}/etc/logrotate.d"
  target_logrotate="${target_logrotate_dir}/codex"

  bootstrap_fetch_seed_file \
    "$seed_base" \
    "$template_repo_path" \
    "$template_tmp" \
    0600 \
    "DevOps Codex logrotate template ${template_repo_path}"
  installer_apply_scalar_placeholders \
    "$template_tmp" \
    "$rendered_tmp" \
    ACCOUNT_USERNAME "$ACCOUNT_USERNAME"
  installer_assert_no_unresolved_installer_placeholders \
    "$rendered_tmp" \
    "DevOps Codex logrotate template ${template_repo_path}"

  install -d -m 0755 "$target_logrotate_dir"
  install -m 0644 "$rendered_tmp" "$target_logrotate"
  chown root:root "$target_logrotate_dir" "$target_logrotate"
  rm -f -- "$template_tmp" "$rendered_tmp"
}

devops_render_bazelrc() {
  template_repo_path=$(installer_repo_join_var \
    DIR_HOOKS_TARGET \
    etc/skel-desktop/.config/bazel/bazelrc.tmpl)
  template_tmp="${tmp_env_dir}/bazelrc.tmpl.$$"
  rendered_tmp="${tmp_env_dir}/bazelrc.rendered.$$"
  target_bazel_dir="${target_root}/etc/skel-desktop/.config/bazel"
  target_bazelrc="${target_bazel_dir}/bazelrc"

  bootstrap_fetch_seed_file \
    "$seed_base" \
    "$template_repo_path" \
    "$template_tmp" \
    0600 \
    "DevOps Bazel rc template ${template_repo_path}"
  installer_apply_scalar_placeholders \
    "$template_tmp" \
    "$rendered_tmp" \
    DEVOPS_BAZEL_OUTPUT_USER_ROOT "$BAZEL_OUTPUT_USER_ROOT" \
    DEVOPS_BAZEL_SERVER_IDLE_SECONDS "$DEVOPS_BAZEL_SERVER_IDLE_SECONDS" \
    DEVOPS_BAZEL_DISK_CACHE "$BAZEL_DISK_CACHE" \
    DEVOPS_BAZEL_REPOSITORY_CACHE "$BAZEL_REPOSITORY_CACHE" \
    DEVOPS_BAZEL_REPOSITORY_DOWNLOADER_RETRIES "$DEVOPS_BAZEL_REPOSITORY_DOWNLOADER_RETRIES" \
    DEVOPS_BAZEL_DISK_CACHE_SIZE "$DEVOPS_BAZEL_DISK_CACHE_SIZE" \
    DEVOPS_BAZEL_DISK_CACHE_MAX_AGE "$DEVOPS_BAZEL_DISK_CACHE_MAX_AGE" \
    DEVOPS_BAZEL_DISK_CACHE_GC_IDLE_DELAY "$DEVOPS_BAZEL_DISK_CACHE_GC_IDLE_DELAY" \
    DEVOPS_BAZEL_ACTION_CACHE_MAX_AGE "$DEVOPS_BAZEL_ACTION_CACHE_MAX_AGE" \
    DEVOPS_BAZEL_ACTION_CACHE_GC_IDLE_DELAY "$DEVOPS_BAZEL_ACTION_CACHE_GC_IDLE_DELAY" \
    DEVOPS_BAZEL_ACTION_CACHE_GC_THRESHOLD "$DEVOPS_BAZEL_ACTION_CACHE_GC_THRESHOLD" \
    DEVOPS_BAZEL_INSTALL_BASE_GC_MAX_AGE "$DEVOPS_BAZEL_INSTALL_BASE_GC_MAX_AGE"
  installer_assert_no_unresolved_installer_placeholders \
    "$rendered_tmp" \
    "DevOps Bazel rc template ${template_repo_path}"

  install -d -m 0755 "$target_bazel_dir"
  install -m 0644 "$rendered_tmp" "$target_bazelrc"
  chown root:root "$target_bazel_dir" "$target_bazelrc"
  rm -f -- "$template_tmp" "$rendered_tmp"
}

devops_render_packer_template() {
  template_repo_path=$(installer_repo_join_var \
    DIR_HOOKS_TARGET \
    etc/skel-desktop/.config/packer/template.pkr.hcl.tmpl)
  template_tmp="${tmp_env_dir}/packer-template.pkr.hcl.tmpl.$$"
  rendered_tmp="${tmp_env_dir}/packer-template.pkr.hcl.rendered.$$"
  target_skel_dir="${target_root}/etc/skel-desktop/.config/packer"
  target_skel_template="${target_skel_dir}/template.pkr.hcl"

  bootstrap_fetch_seed_file \
    "$seed_base" \
    "$template_repo_path" \
    "$template_tmp" \
    0600 \
    "DevOps Packer template ${template_repo_path}"
  installer_apply_scalar_placeholders \
    "$template_tmp" \
    "$rendered_tmp" \
    DEVOPS_PACKER_VERSION "$DEVOPS_PACKER_VERSION"
  installer_assert_no_unresolved_installer_placeholders \
    "$rendered_tmp" \
    "DevOps Packer template ${template_repo_path}"

  install -d -m 0755 "$target_skel_dir"
  [ ! -e "$target_skel_template" ] && [ ! -L "$target_skel_template" ] ||
    devops_fatal "fresh-install Packer template path already exists: ${target_skel_template}"
  install -m 0644 "$rendered_tmp" "$target_skel_template"
  chown root:root "$target_skel_dir" "$target_skel_template"
  rm -f -- "$template_tmp" "$rendered_tmp"

  # Stage the account copy from inside the target namespace. This guarantees
  # that the path validated below is the same path later seen by runuser.
  # shellcheck disable=SC2016
  run_in_target "stage managed Packer template for primary account" /bin/sh -eu -c '
packer_fatal() {
  printf "fatal: %s\n" "$*" >&2
  exit 1
}

account_user=$1
account_home=$2
source_template=/etc/skel-desktop/.config/packer/template.pkr.hcl
config_dir="${account_home}/.config"
template_dir="${config_dir}/packer"
target_template="${template_dir}/template.pkr.hcl"
mise_config_dir="${config_dir}/mise"

for required_command in awk chmod chown getent id install runuser find; do
  command -v "$required_command" >/dev/null 2>&1 ||
    packer_fatal "required Packer template staging command is unavailable: $required_command"
done
[ -x /usr/bin/test ] ||
  packer_fatal "required Packer template access test is unavailable: /usr/bin/test"

account_record=$(getent passwd "$account_user") ||
  packer_fatal "primary account is unavailable while staging Packer policy: $account_user"
resolved_home=$(printf "%s\n" "$account_record" | awk -F: "{ print \$6; exit }")
[ "$resolved_home" = "$account_home" ] ||
  packer_fatal "primary account home does not match Packer policy: expected $account_home, found ${resolved_home:-unset}"
account_uid=$(id -u "$account_user")
account_gid=$(id -g "$account_user")
case "$account_uid:$account_gid" in
  0:*|65534:*|*:65534|*[!0123456789:]*)
    packer_fatal "unsafe primary account identity for Packer policy: $account_uid:$account_gid"
    ;;
esac

[ -d "$account_home" ] && [ ! -L "$account_home" ] ||
  packer_fatal "primary account home is unavailable or unsafe: $account_home"
[ -f "$source_template" ] && [ ! -L "$source_template" ] ||
  packer_fatal "managed Packer skeleton template is unavailable or unsafe: $source_template"
for managed_path in \
  "$config_dir" \
  "$template_dir" \
  "$target_template" \
  "$mise_config_dir"
do
  [ ! -L "$managed_path" ] ||
    packer_fatal "managed Packer account path must not be a symlink: $managed_path"
done

install -d -m 0755 "$config_dir"
install -d -m 0700 "$template_dir"
install -d -m 0755 "$mise_config_dir"
[ ! -e "$target_template" ] ||
  packer_fatal "fresh-install Packer account template already exists: $target_template"
install -m 0644 "$source_template" "$target_template"
chown "$account_uid:$account_gid" \
  "$config_dir" \
  "$template_dir" \
  "$target_template" \
  "$mise_config_dir"
chmod 0755 "$config_dir"
chmod 0700 "$template_dir"
chmod 0644 "$target_template"
chmod 0755 "$mise_config_dir"

[ "$(find -P "$config_dir" -maxdepth 0 -printf "%U:%G:%m")" = "$account_uid:$account_gid:755" ] ||
  packer_fatal "Packer account config directory ownership or mode is invalid: $config_dir"
[ "$(find -P "$template_dir" -maxdepth 0 -printf "%U:%G:%m")" = "$account_uid:$account_gid:700" ] ||
  packer_fatal "Packer template directory ownership or mode is invalid: $template_dir"
[ "$(find -P "$target_template" -maxdepth 0 -printf "%U:%G:%m")" = "$account_uid:$account_gid:644" ] ||
  packer_fatal "Packer account template ownership or mode is invalid: $target_template"
[ "$(find -P "$mise_config_dir" -maxdepth 0 -printf "%U:%G:%m")" = "$account_uid:$account_gid:755" ] ||
  packer_fatal "Mise account config directory ownership or mode is invalid: $mise_config_dir"
/usr/sbin/runuser -u "$account_user" -- /usr/bin/test -x "$template_dir" ||
  packer_fatal "primary account cannot traverse the managed Packer template directory"
/usr/sbin/runuser -u "$account_user" -- /usr/bin/test -r "$target_template" ||
  packer_fatal "primary account cannot read the managed Packer template"
/usr/sbin/runuser -u "$account_user" -- /usr/bin/test -x "$mise_config_dir" ||
  packer_fatal "primary account cannot traverse the managed Mise config directory"
' sh "$ACCOUNT_USERNAME" "$ACCOUNT_HOME"
}

devops_write_packer_config() {
  target_packer_config="${target_root}${PACKER_CONFIG_PATH}"
  packer_config_tmp="${tmp_env_dir}/packer-config.json.$$"

  [ -d "$(dirname "$target_packer_config")" ] ||
    devops_fatal "required Packer config directory is missing: $(dirname "$target_packer_config")"
  [ ! -e "$target_packer_config" ] && [ ! -L "$target_packer_config" ] ||
    devops_fatal "fresh-install Packer config path already exists: ${target_packer_config}"
  printf '{}\n' >"$packer_config_tmp"
  install -m 0640 "$packer_config_tmp" "$target_packer_config"
  chown "$account_ids" "$target_packer_config"
  rm -f -- "$packer_config_tmp"
}

devops_initialize_packer_plugins() {
  # shellcheck disable=SC2016
  devops_run_as_account \
    "initialize exact-version Packer plugins from the managed HCL template" \
    /usr/bin/timeout \
      --signal=TERM \
      --kill-after=30s \
      "${DEVOPS_PACKER_INIT_TIMEOUT_SECONDS}s" \
      /bin/sh -eu -c '
template_dir=$1
packer_binary=$2
plugin_root=$3
template_file="${template_dir}/template.pkr.hcl"

[ -d "$template_dir" ] && [ ! -L "$template_dir" ] || {
  printf "fatal: managed Packer template directory is unavailable or unsafe: %s\n" "$template_dir" >&2
  exit 1
}
[ -f "$template_file" ] && [ ! -L "$template_file" ] && [ -r "$template_file" ] || {
  printf "fatal: managed Packer template is unavailable or unsafe: %s\n" "$template_file" >&2
  exit 1
}
[ -x "$packer_binary" ] || {
  printf "fatal: managed Packer executable is unavailable: %s\n" "$packer_binary" >&2
  exit 1
}
[ -d "$plugin_root" ] && [ ! -L "$plugin_root" ] || {
  printf "fatal: managed Packer plugin root is unavailable or unsafe: %s\n" "$plugin_root" >&2
  exit 1
}
cd "$template_dir"
"$packer_binary" init .
installed_plugins=$("$packer_binary" plugins installed)
for plugin in amazon ansible azure docker googlecompute proxmox qemu; do
  printf "%s\n" "$installed_plugins" |
    grep -Fq "github.com/hashicorp/${plugin}" || {
      printf "fatal: required Packer plugin is missing after init: %s\n" "$plugin" >&2
      exit 1
    }
  plugin_dir="${plugin_root}/github.com/hashicorp/${plugin}"
  [ -d "$plugin_dir" ] && [ ! -L "$plugin_dir" ] || {
    printf "fatal: required Packer plugin directory is missing: %s\n" "$plugin_dir" >&2
    exit 1
  }
  find "$plugin_dir" -type f -name "packer-plugin-${plugin}_v*" -perm /0111 -print -quit |
    grep -q . || {
      printf "fatal: required Packer plugin executable is missing: %s\n" "$plugin" >&2
      exit 1
    }
done
' sh \
      "${ACCOUNT_HOME}/.config/packer" \
      "$DEVOPS_PACKER_BINARY_PATH" \
      "$PACKER_PLUGIN_PATH"
}

