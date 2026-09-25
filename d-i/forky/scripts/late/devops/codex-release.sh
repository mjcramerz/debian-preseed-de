#!/bin/sh
# Sourced installer module; edit this file directly.

devops_install_pinned_codex() (
  # A separate, short-lived SSH agent authenticates this clone, before the
  # release publisher runs. No agent capability is passed to Codex itself.
  umask 077
  clone_parent=$(mktemp -d "${target_root}/data/codex/.home-clone.XXXXXXXX") ||
    devops_fatal "unable to allocate private Codex clone staging directory"
  trap 'rm -rf -- "$clone_parent"' 0
  trap 'exit 129' 1
  trap 'exit 130' 2
  trap 'exit 143' 15
  # /data/codex intentionally remains root:devops 3770. mktemp inherits
  # its setgid bit (2700); GNU chmod 0700 alone preserves that bit. Normalize
  # ONLY this new private stage, never the shared root or the reader's policy.
  [ -d "$clone_parent" ] && [ ! -L "$clone_parent" ] ||
    devops_fatal "private Codex clone staging path is not a direct directory"
  # This function runs in d-i, not inside the target. busybox-udeb has no
  # stat applet: use the canonical reader loaded by bootstrap_source_common_lib.
  # Distinguish an inspection failure from observed unsafe ownership/mode.
  clone_owner=$(installer_metadata_value "$clone_parent" uid) ||
    devops_fatal "unable to inspect private Codex clone staging directory ownership"
  [ "$clone_owner" = 0 ] ||
    devops_fatal "private Codex clone staging directory is not root-owned"
  chmod 0700 -- "$clone_parent" && chmod a-s -- "$clone_parent" ||
    devops_fatal "unable to secure private Codex clone staging directory"
  clone_metadata=$(installer_metadata_value "$clone_parent" uid_gid_mode) ||
    devops_fatal "unable to inspect private Codex clone staging directory mode"
  # The inherited devops GID is intentional; only the UID and exact mode are
  # fixed here. The reader validates all numeric metadata fields before use.
  case "$clone_metadata" in
    0:*:700) ;;
    *) devops_fatal "private Codex clone staging directory must be root-owned mode 0700" ;;
  esac
  INSTALLER_TARGET_DIR="$target_root" managed_git_ssh_target_action clone-codex "${clone_parent#"$target_root"}/repository" ||
    devops_fatal "failed to clone codex-home over the private installer SSH identity"
  devops_install_codex_from_clone "${clone_parent#"$target_root"}/repository"
)

devops_install_codex_from_clone() {
  devops_codex_clone_source=$1
  # Build and validate every release component in private staging first. Final
  # paths are published only after the pinned archive and branch checkout both pass.
  # shellcheck disable=SC2016
  run_in_target "download and install pinned managed Codex" /bin/sh -eu -c '
umask 022

codex_fatal() {
  printf "fatal: %s\n" "$*" >&2
  exit 1
}

codex_require_command() {
  command -v "$1" >/dev/null 2>&1 ||
    codex_fatal "required command is unavailable: $1"
}

codex_chmod_without_special_bits() {
  requested_mode=$1
  shift

  case "$requested_mode" in
    0644|0700|0750|0755) ;;
    *) codex_fatal "unsupported Codex managed mode: $requested_mode" ;;
  esac
  [ "$#" -gt 0 ] ||
    codex_fatal "Codex managed mode requires at least one path"

  chmod "$requested_mode" -- "$@" ||
    codex_fatal "unable to apply Codex managed mode $requested_mode"
  chmod a-s -- "$@" ||
    codex_fatal "unable to clear special bits from Codex managed paths"
}

codex_chmod_group_shared() {
  [ "$#" -gt 0 ] ||
    codex_fatal "Codex group-shared mode requires at least one directory"

  for shared_path in "$@"; do
    [ -d "$shared_path" ] && [ ! -L "$shared_path" ] ||
      codex_fatal "Codex group-shared path is not a direct directory: $shared_path"
  done
  unset shared_path

  chmod 0770 -- "$@" ||
    codex_fatal "unable to apply Codex group-shared permissions"
  chmod a-s -- "$@" ||
    codex_fatal "unable to clear unexpected special bits from Codex group-shared directories"
  chmod g+s -- "$@" ||
    codex_fatal "unable to preserve Codex devops-group inheritance"
}

codex_validate_positive_integer() {
  label=$1
  value=$2

  case "$value" in
    ""|*[!0123456789]*) codex_fatal "${label} must be a positive integer" ;;
  esac
  [ "$value" -gt 0 ] || codex_fatal "${label} must be greater than zero"
}

codex_tree_matches() {
  expected_tree=$1
  actual_tree=$2
  exclude_root_git=$3
  expected_snapshot="${staging_dir}/expected-tree.tar"
  actual_snapshot="${staging_dir}/actual-tree.tar"

  [ -d "$expected_tree" ] && [ ! -L "$expected_tree" ] || return 1
  [ -d "$actual_tree" ] && [ ! -L "$actual_tree" ] || return 1
  rm -f -- "$expected_snapshot" "$actual_snapshot"
  if [ "$exclude_root_git" = 1 ]; then
    # Runtime state is explicitly typed, scoped and permission checked. Never
    # run Git against account-writable configuration from a privileged shell.
    python3 "$state_helper_path" --expected "$expected_tree" --actual "$actual_tree" \
      --uid "$account_uid" --gid "$devops_gid" --branch "$repository_branch" \
      --url "$repository_url" --codex-root "$codex_root"
    return $?
  else
    tar --sort=name --format=gnu --mtime=@0 --numeric-owner \
      -cf "$expected_snapshot" -C "$expected_tree" . ||
      codex_fatal "unable to snapshot staged Codex managed tree"
    tar --sort=name --format=gnu --mtime=@0 --numeric-owner \
      -cf "$actual_snapshot" -C "$actual_tree" . ||
      codex_fatal "unable to snapshot existing Codex managed tree"
  fi
  if cmp -s -- "$expected_snapshot" "$actual_snapshot"; then
    rm -f -- "$expected_snapshot" "$actual_snapshot"
    return 0
  fi
  rm -f -- "$expected_snapshot" "$actual_snapshot"
  return 1
}

codex_file_matches() {
  expected_file=$1
  actual_file=$2

  [ -f "$expected_file" ] && [ ! -L "$expected_file" ] || return 1
  [ -f "$actual_file" ] && [ ! -L "$actual_file" ] || return 1
  [ "$(find -P "$actual_file" -maxdepth 0 -printf "%U:%G:%m")" = \
    "$(find -P "$expected_file" -maxdepth 0 -printf "%U:%G:%m")" ] || return 1
  cmp -s -- "$expected_file" "$actual_file"
}

codex_version=$1
shift
release_tag=$1
shift
archive_url=$1
shift
expected_sha256=$1
shift
maximum_bytes=$1
shift
maximum_extracted_bytes=$1
shift
archive_binary_dir=$1
shift
archive_schema_member=$1
shift
codex_root=$1
shift
binary_path=$1
shift
schema_path=$1
shift
wrapper_path=$1
shift
user_root=$1
shift
system_config_dir=$1
shift
log_dir=$1
shift
sqlite_home=$1
shift
runtime_root=$1
shift
repository_url=$1
shift
repository_branch=$1
shift
repository_clone_source=$1
shift
agents_path=$1
shift
home_path=$1
shift
skills_path=$1
shift
archive_helper_path=$1
shift
account_user=$1

case "$codex_version" in
  ""|*[!A-Za-z0-9._+-]*)
    codex_fatal "Codex version contains unsupported syntax: $codex_version"
    ;;
esac
case "$release_tag" in
  ""|*[!A-Za-z0-9._+-]*)
    codex_fatal "Codex release tag contains unsupported syntax: $release_tag"
    ;;
esac
case "$archive_url" in
  https://*) ;;
  *) codex_fatal "Codex release URL must use HTTPS" ;;
esac
case "$archive_url" in
  *[[:space:]]*) codex_fatal "Codex release URL must not contain whitespace" ;;
esac
case "$expected_sha256" in
  *[!0123456789abcdef]*|"") codex_fatal "expected SHA-256 is malformed" ;;
esac
[ "${#expected_sha256}" -eq 64 ] ||
  codex_fatal "expected SHA-256 must have 64 hexadecimal characters"
codex_validate_positive_integer "maximum byte limit" "$maximum_bytes"
codex_validate_positive_integer \
  "maximum extracted byte limit" \
  "$maximum_extracted_bytes"
case "$archive_binary_dir" in
  ""|*[!A-Za-z0-9._+-]*)
    codex_fatal "Codex archive binary directory is malformed: $archive_binary_dir"
    ;;
esac
case "$archive_schema_member" in
  ""|*[!A-Za-z0-9._+-]*)
    codex_fatal "Codex archive schema member is malformed: $archive_schema_member"
    ;;
esac
[ "$codex_root" = /data/codex ] ||
  codex_fatal "Codex root is not approved: $codex_root"
[ "$binary_path" = "$codex_root/share/bin/codex" ] ||
  codex_fatal "Codex binary path is not approved: $binary_path"
[ "$schema_path" = "$codex_root/$archive_schema_member" ] ||
  codex_fatal "Codex schema path does not match the profile-owned archive schema member"
[ "$wrapper_path" = "$codex_root/lib/codex" ] ||
  codex_fatal "Codex wrapper path is not approved: $wrapper_path"
[ "$user_root" = "$codex_root/usr" ] ||
  codex_fatal "Codex user root is not approved: $user_root"
[ "$system_config_dir" = /etc/codex ] ||
  codex_fatal "Codex system configuration path is not approved: $system_config_dir"
[ "$log_dir" = "$codex_root/log" ] ||
  codex_fatal "Codex log path is not approved: $log_dir"
[ "$sqlite_home" = "$codex_root/sqlite" ] ||
  codex_fatal "Codex SQLite path is not approved: $sqlite_home"
[ "$runtime_root" = "$codex_root/runtime" ] ||
  codex_fatal "Codex runtime path is not approved: $runtime_root"
[ "$repository_url" = git@gitlab.com:computes/misc/codex-home.git ] ||
  codex_fatal "Codex repository URL is not approved"
[ "$repository_branch" = mcr/main ] ||
  codex_fatal "Codex repository branch is not approved"
[ "$agents_path" = "$user_root/agents" ] ||
  codex_fatal "Codex agents path is not approved: $agents_path"
[ "$home_path" = "$user_root/home" ] ||
  codex_fatal "Codex home path is not approved: $home_path"
[ "$skills_path" = "$user_root/skills" ] ||
  codex_fatal "Codex skills path is not approved: $skills_path"
[ "$archive_helper_path" = "$codex_root/.installer-codex-archive.py" ] ||
  codex_fatal "Codex archive helper path is not approved: $archive_helper_path"

for required_command in \
  awk \
  chmod \
  chown \
  cmp \
  cp \
  curl \
  find \
  getent \
  git \
  id \
  install \
  mktemp \
  mv \
  python3 \
  rm \
  rmdir \
  sha256sum \
  find \
  tar \
  timeout \
  tr \
  wc
do
  codex_require_command "$required_command"
done
unset required_command
getent passwd "$account_user" >/dev/null 2>&1 ||
  codex_fatal "required Codex account is missing: $account_user"
devops_group_record=$(getent group devops) ||
  codex_fatal "required target group is missing: devops"
account_uid=$(id -u "$account_user")
devops_gid=${devops_group_record#*:}
devops_gid=${devops_gid#*:}
devops_gid=${devops_gid%%:*}
case "$account_uid:$devops_gid" in
  *[!0123456789:]*|:*|*:)
    codex_fatal "unable to resolve Codex account or devops group ids"
    ;;
esac

[ -d "$codex_root" ] && [ ! -L "$codex_root" ] ||
  codex_fatal "prepared Codex root is missing or indirect: $codex_root"
[ -d "$codex_root/share/bin" ] && [ ! -L "$codex_root/share/bin" ] ||
  codex_fatal "prepared Codex binary directory is missing or indirect"
[ -x "$wrapper_path" ] && [ ! -L "$wrapper_path" ] ||
  codex_fatal "staged Codex wrapper is missing or indirect: $wrapper_path"
[ -f "$archive_helper_path" ] && [ ! -L "$archive_helper_path" ] ||
  codex_fatal "staged Codex archive helper is missing or indirect: $archive_helper_path"
[ "$(find -P "$archive_helper_path" -maxdepth 0 -printf "%U:%G:%m")" = 0:0:700 ] ||
  codex_fatal "staged Codex archive helper has unexpected ownership or mode"

state_helper_path="${archive_helper_path%/*}/.installer-codex-state.py"
[ -f "$state_helper_path" ] && [ ! -L "$state_helper_path" ] ||
  codex_fatal "Codex state verifier is missing or indirect"
[ "$(find -P "$state_helper_path" -maxdepth 0 -printf "%U:%G:%m")" = 0:0:700 ] ||
  codex_fatal "Codex state verifier has unsafe ownership or mode"

staging_dir=
config_staging=
publication_committed=0
published_binary_directory=0
published_schema=0
published_repository=0
published_config=0
published_release_marker=0
removed_binary_placeholder=0
release_marker="${codex_root}/.codex-release"
cleanup() {
  if [ "$publication_committed" = 0 ]; then
    [ "$published_release_marker" = 0 ] || rm -f -- "$release_marker"
    [ "$published_config" = 0 ] || rm -rf -- "$system_config_dir"
    [ "$published_repository" = 0 ] || rm -rf -- "$user_root"
    [ "$published_schema" = 0 ] || rm -f -- "$schema_path"
    [ "$published_binary_directory" = 0 ] || rm -rf -- "$codex_root/share/bin"
    if [ "$removed_binary_placeholder" = 1 ] && \
      [ ! -e "$codex_root/share/bin" ] && [ ! -L "$codex_root/share/bin" ]; then
      install -d -m 0755 -o root -g root "$codex_root/share/bin" || true
    fi
  fi
  if [ -n "$staging_dir" ]; then
    rm -rf -- "$staging_dir"
  fi
  if [ -n "$config_staging" ]; then
    rm -rf -- "$config_staging"
  fi
  rm -f -- "$archive_helper_path" "$state_helper_path"
}
trap '"'"'cleanup_status=$?; trap - EXIT; set +e; cleanup; exit "$cleanup_status"'"'"' EXIT
trap "exit 129" HUP
trap "exit 130" INT
trap "exit 143" TERM

staging_dir=$(mktemp -d "${codex_root}/.install.XXXXXXXX") ||
  codex_fatal "unable to allocate Codex staging directory"
archive_path="${staging_dir}/codex.tar.gz"
curl \
  --fail \
  --silent \
  --show-error \
  --location \
  --proto "=https" \
  --tlsv1.2 \
  --retry 3 \
  --retry-delay 2 \
  --connect-timeout 15 \
  --max-time 900 \
  --max-filesize "$maximum_bytes" \
  --output "$archive_path" \
  "$archive_url" ||
  codex_fatal "failed to download pinned managed Codex release: $archive_url"

archive_bytes=$(wc -c <"$archive_path" | tr -d "[[:space:]]")
case "$archive_bytes" in
  ""|*[!0123456789]*) codex_fatal "downloaded Codex archive size is invalid" ;;
esac
[ "$archive_bytes" -gt 0 ] ||
  codex_fatal "downloaded Codex archive is empty"
[ "$archive_bytes" -le "$maximum_bytes" ] ||
  codex_fatal "downloaded Codex archive exceeds the configured maximum"

actual_sha256=$(sha256sum "$archive_path" | awk "{print \$1}")
[ "$actual_sha256" = "$expected_sha256" ] ||
  codex_fatal "managed Codex SHA-256 mismatch for ${archive_url}"

extract_dir="${staging_dir}/extract"
install -d -m 0700 "$extract_dir"
python3 "$archive_helper_path" \
  --archive "$archive_path" \
  --output-directory "$extract_dir" \
  --binary-directory "$archive_binary_dir" \
  --schema-member "$archive_schema_member" \
  --maximum-extracted-bytes "$maximum_extracted_bytes" ||
  codex_fatal "managed Codex archive validation or extraction failed"

extracted_binary_dir="$extract_dir/$archive_binary_dir"
[ -d "$extracted_binary_dir" ] && [ ! -L "$extracted_binary_dir" ] ||
  codex_fatal "managed Codex archive did not produce a direct binary directory"
first_extracted_binary=$(find "$extracted_binary_dir" \
  -mindepth 1 -maxdepth 1 -type f -links 1 -print)
[ -n "$first_extracted_binary" ] ||
  codex_fatal "managed Codex archive did not produce any binaries"
hidden_extracted_binary=$(find "$extracted_binary_dir" \
  -mindepth 1 -maxdepth 1 -name ".*" -print)
[ -z "$hidden_extracted_binary" ] ||
  codex_fatal "managed Codex archive produced an unexpected hidden binary"
unsafe_extracted_binary=$(find "$extracted_binary_dir" \
  -mindepth 1 -maxdepth 1 \( ! -type f -o -type l -o ! -links 1 \) -print)
[ -z "$unsafe_extracted_binary" ] ||
  codex_fatal "managed Codex archive produced an unsafe binary entry"
for extracted_path in "$extracted_binary_dir"/*; do
  [ -f "$extracted_path" ] && [ ! -L "$extracted_path" ] ||
    codex_fatal "extracted Codex binary is missing or indirect: $extracted_path"
  binary_name=${extracted_path##*/}
  case "$binary_name" in
    ""|*[!A-Za-z0-9._+-]*)
      codex_fatal "extracted Codex binary name is malformed: $binary_name"
      ;;
  esac
  chown root:root "$extracted_path"
  codex_chmod_without_special_bits 0755 "$extracted_path"
done
unset binary_name extracted_path
chown root:root "$extracted_binary_dir"
codex_chmod_without_special_bits 0755 "$extracted_binary_dir"

# Version commands also initialize Codex state. Keep BOTH release probes in a
# disposable private home, never in / or in the desktop account state.
codex_verify_version() (
  verify_home=$(mktemp -d "$staging_dir/verify-home.XXXXXX") || return 1
  codex_verify_cleanup() { rm -rf -- "$verify_home"; }
  trap codex_verify_cleanup EXIT
  trap "exit 129" HUP
  trap "exit 130" INT
  trap "exit 143" TERM
  /usr/bin/env -i HOME="$verify_home" USER=root LOGNAME=root \
    CODEX_HOME="$verify_home/.codex" \
    XDG_CONFIG_HOME="$verify_home/.config" XDG_CACHE_HOME="$verify_home/.cache" \
    XDG_DATA_HOME="$verify_home/.local/share" XDG_STATE_HOME="$verify_home/.local/state" \
    PATH=/usr/bin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 \
    /usr/bin/timeout --kill-after=5 30 "$1" --version
)

candidate_binary_path="$extracted_binary_dir/codex"
[ -x "$candidate_binary_path" ] && [ ! -L "$candidate_binary_path" ] ||
  codex_fatal "managed Codex archive is missing its required entrypoint"
version_output=$(codex_verify_version "$candidate_binary_path" 2>/dev/null) || codex_fatal "pinned Codex binary failed its version check"
case "$version_output" in
  *"$codex_version"*) ;;
  *) codex_fatal "Codex version verification failed for staged release" ;;
esac

extracted_schema_path="$extract_dir/$archive_schema_member"
[ -f "$extracted_schema_path" ] && [ ! -L "$extracted_schema_path" ] ||
  codex_fatal "extracted Codex configuration schema is missing or indirect"
chown root:root "$extracted_schema_path"
codex_chmod_without_special_bits 0644 "$extracted_schema_path"
unset first_extracted_binary hidden_extracted_binary unsafe_extracted_binary

repository_staging="${staging_dir}/repository"
case "$repository_clone_source" in
  /data/codex/.home-clone.*/repository) ;;
  *) codex_fatal "unapproved private Codex clone source" ;;
esac
[ -d "$repository_clone_source" ] && [ ! -L "$repository_clone_source" ] ||
  codex_fatal "private Codex branch checkout is missing"
mv -- "$repository_clone_source" "$repository_staging"
export GIT_TERMINAL_PROMPT=0 GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null
actual_repository_url=$(git -C "$repository_staging" remote get-url origin)
[ "$actual_repository_url" = "$repository_url" ] ||
  codex_fatal "cloned Codex home repository remote does not match policy"
actual_repository_branch=$(git -C "$repository_staging" symbolic-ref --short HEAD)
[ "$actual_repository_branch" = "$repository_branch" ] ||
  codex_fatal "Codex home is not a named mcr/main branch checkout"
[ "$(git -C "$repository_staging" rev-parse --abbrev-ref "@{upstream}")" = "origin/$repository_branch" ] ||
  codex_fatal "Codex home does not track origin/mcr/main"

for required_repository_dir in agents etc home skills; do
  [ -d "$repository_staging/$required_repository_dir" ] &&
    [ ! -L "$repository_staging/$required_repository_dir" ] ||
    codex_fatal "Codex home repository is missing required directory: $required_repository_dir"
done
for forbidden_repository_state in \
  home/auth.json \
  home/app-server-control \
  home/packages
do
  [ ! -e "$repository_staging/$forbidden_repository_state" ] &&
    [ ! -L "$repository_staging/$forbidden_repository_state" ] ||
    codex_fatal "Codex home repository must not contain runtime credential or package state: $forbidden_repository_state"
done
unset forbidden_repository_state
unsafe_etc_entry=$(find "$repository_staging/etc" -xdev \
  \( -type l -o \( ! -type f ! -type d \) \) -print)
[ -z "$unsafe_etc_entry" ] ||
  codex_fatal "Codex repository etc tree contains an unsafe entry: $unsafe_etc_entry"

repository_git_path="$repository_staging/.git"
[ -d "$repository_git_path" ] && [ ! -L "$repository_git_path" ] ||
  codex_fatal "staged Codex repository metadata is missing or indirect"
unsafe_repository_git_entry=$(find "$repository_git_path" -xdev \
  \( -type l -o \( ! -type d ! -type f \) -o \( -type f ! -links 1 \) \) \
  -print -quit)
[ -z "$unsafe_repository_git_entry" ] ||
  codex_fatal "Codex repository metadata contains an unsafe entry: $unsafe_repository_git_entry"
unset unsafe_repository_git_entry

candidate_home_path="$repository_staging/home"
candidate_memories_path="${candidate_home_path}/memories"
chown -R "$account_user:devops" "$repository_staging"
find "$repository_staging" -xdev -type d -exec chmod a-s,go-w -- {} +
find "$repository_staging" -xdev -type f -exec chmod a-s,go-w -- {} +
chown -R "$account_user:devops" "$repository_git_path"
find "$repository_git_path" -xdev -type d -exec chmod 0750 -- {} +
find "$repository_git_path" -xdev -type f -exec chmod 0640 -- {} +
chown -R root:root "$repository_staging/etc"
codex_chmod_without_special_bits 0755 "$repository_staging/etc"

install -d -m 2770 -o "$account_user" -g devops \
  "$candidate_home_path/sessions" \
  "$candidate_home_path/shell_snapshots" \
  "$candidate_home_path/archived_sessions"
for state_file in history.jsonl session_index.jsonl external_agent_session_imports.json; do
  install -m 0660 -o "$account_user" -g devops /dev/null \
    "$candidate_home_path/$state_file"
done

if [ ! -e "$candidate_memories_path" ]; then
  install -d -m 2770 -o "$account_user" -g devops "$candidate_memories_path"
fi
[ -d "$candidate_memories_path" ] && [ ! -L "$candidate_memories_path" ] ||
  codex_fatal "staged Codex memories path is missing or indirect"
chown -R "$account_user:devops" "$candidate_memories_path"
find "$candidate_home_path" -xdev -type d -exec chmod a-s,g=u,o=,g+s -- {} +
find "$candidate_home_path" -xdev -type f -exec chmod a-s,g=u,o= -- {} +

chown "$account_user:devops" \
  "$repository_staging" "$candidate_home_path" "$candidate_memories_path"
codex_chmod_without_special_bits 0750 "$repository_staging"
codex_chmod_group_shared "$candidate_home_path" "$candidate_memories_path"

# Stage the same policy that tmpfiles applies after publication. Previously the
# publication omitted runtime links and changed modes only AFTER the commit.
chmod 0750 "$repository_staging/agents" "$repository_staging/skills"
install -d -m 0700 -o "$account_user" -g devops "$candidate_home_path/app-server-control"
install -m 0600 -o "$account_user" -g devops /dev/null \
  "$candidate_home_path/app-server-control/app-server-startup.lock"
ln -s -- "$codex_root/packages" "$candidate_home_path/packages"
ln -s -- "$codex_root/sockets/app-server-control.sock" \
  "$candidate_home_path/app-server-control/app-server-control.sock"
chown -h "$account_user:devops" "$candidate_home_path/packages" \
  "$candidate_home_path/app-server-control/app-server-control.sock"
# Validate the private candidate too, so no unsafe repository symlink or Git
# configuration is ever published. The same check defines safe resume.
python3 "$state_helper_path" --expected "$repository_staging" --actual "$repository_staging" \
  --uid "$account_uid" --gid "$devops_gid" --branch "$repository_branch" \
  --url "$repository_url" --codex-root "$codex_root" ||
  codex_fatal "staged Codex repository violates publication policy"

config_staging=$(mktemp -d "/etc/.codex.XXXXXXXX") ||
  codex_fatal "unable to allocate Codex system configuration staging directory"
cp -a -- "$repository_staging/etc/." "$config_staging/"
chown -R root:root "$config_staging"
find "$config_staging" -xdev -type d -exec chmod a-s,go-w -- {} +
find "$config_staging" -xdev -type f -exec chmod a-s,go-w -- {} +
codex_chmod_without_special_bits 0755 "$config_staging"

candidate_release_marker="${staging_dir}/codex-release"
{
  printf "version=%s\n" "$codex_version"
  printf "release_tag=%s\n" "$release_tag"
  printf "url=%s\n" "$archive_url"
  printf "sha256=%s\n" "$expected_sha256"
  printf "archive_bytes=%s\n" "$archive_bytes"
  printf "maximum_archive_bytes=%s\n" "$maximum_bytes"
  printf "maximum_extracted_bytes=%s\n" "$maximum_extracted_bytes"
  printf "archive_binary_directory=%s\n" "$archive_binary_dir"
  printf "schema=%s\n" "$schema_path"
  printf "repository=%s\n" "$repository_url"
  printf "repository_branch=%s\n" "$repository_branch"
  printf "binary=%s\n" "$binary_path"
  printf "wrapper=%s\n" "$wrapper_path"
} >"$candidate_release_marker"
chmod 0644 "$candidate_release_marker"
chown root:root "$candidate_release_marker"

# Resume verified immutable components and separately validated mutable account
# state. Conflicts remain fatal; no unrelated destination is removed or adopted.
publish_binary_directory=0
existing_binary_entry=$(find "$codex_root/share/bin" \
  -mindepth 1 -maxdepth 1 -print -quit)
if [ -z "$existing_binary_entry" ]; then
  [ "$(find -P "$codex_root/share/bin" -maxdepth 0 -printf "%U:%G:%m")" = 0:0:755 ] ||
    codex_fatal "empty Codex binary directory has unexpected ownership or mode"
  publish_binary_directory=1
elif ! codex_tree_matches "$extracted_binary_dir" "$codex_root/share/bin" 0; then
  codex_fatal "existing Codex binary directory conflicts with the pinned release"
fi
unset existing_binary_entry

publish_schema=0
if [ -e "$schema_path" ] || [ -L "$schema_path" ]; then
  codex_file_matches "$extracted_schema_path" "$schema_path" ||
    codex_fatal "existing Codex schema conflicts with the pinned release: $schema_path"
else
  publish_schema=1
fi

publish_repository=0
if [ -e "$user_root" ] || [ -L "$user_root" ]; then
  codex_tree_matches "$repository_staging" "$user_root" 1 ||
    codex_fatal "existing Codex repository tree conflicts with the pinned revision"

else
  publish_repository=1
fi

publish_config=0
if [ -e "$system_config_dir" ] || [ -L "$system_config_dir" ]; then
  codex_tree_matches "$config_staging" "$system_config_dir" 0 ||
    codex_fatal "existing Codex system configuration conflicts with the pinned revision"
else
  publish_config=1
fi

publish_release_marker=0
if [ -e "$release_marker" ] || [ -L "$release_marker" ]; then
  codex_file_matches "$candidate_release_marker" "$release_marker" ||
    codex_fatal "existing Codex release marker conflicts with the pinned release"
else
  publish_release_marker=1
fi

# All conflict checks are complete. Publish only destinations that are absent;
# rollback removes only paths moved into place by this invocation.
if [ "$publish_binary_directory" = 1 ]; then
  rmdir -- "$codex_root/share/bin" ||
    codex_fatal "unable to remove empty Codex binary directory before publication"
  removed_binary_placeholder=1
  mv -- "$extracted_binary_dir" "$codex_root/share/bin" ||
    codex_fatal "unable to publish pinned Codex binary directory"
  published_binary_directory=1
fi
if [ "$publish_schema" = 1 ]; then
  mv -- "$extracted_schema_path" "$schema_path" ||
    codex_fatal "unable to publish pinned Codex configuration schema"
  published_schema=1
fi
if [ "$publish_repository" = 1 ]; then
  mv -- "$repository_staging" "$user_root" ||
    codex_fatal "unable to publish pinned Codex home repository"
  published_repository=1
fi
if [ "$publish_config" = 1 ]; then
  mv -- "$config_staging" "$system_config_dir" ||
    codex_fatal "unable to publish pinned Codex system configuration"
  published_config=1
  config_staging=
fi
if [ "$publish_release_marker" = 1 ]; then
  mv -- "$candidate_release_marker" "$release_marker" ||
    codex_fatal "unable to publish managed Codex release marker"
  published_release_marker=1
fi

[ -x "$binary_path" ] && [ ! -L "$binary_path" ] ||
  codex_fatal "published Codex entrypoint is missing or indirect"
version_output=$(codex_verify_version "$binary_path" 2>/dev/null) ||
  codex_fatal "published Codex binary failed its version check"
case "$version_output" in
  *"$codex_version"*) ;;
  *) codex_fatal "published Codex version verification failed" ;;
esac
[ -f "$schema_path" ] && [ ! -L "$schema_path" ] ||
  codex_fatal "published Codex schema is missing or indirect"
[ -d "$user_root/.git" ] && [ ! -L "$user_root/.git" ] ||
  codex_fatal "published Codex repository metadata is missing or indirect"
[ -d "$system_config_dir" ] && [ ! -L "$system_config_dir" ] ||
  codex_fatal "published Codex system configuration is missing or indirect"
[ -f "$release_marker" ] && [ ! -L "$release_marker" ] ||
  codex_fatal "published Codex release marker is missing or indirect"

publication_committed=1
printf "installed managed Codex %s at %s with wrapper %s\n" \
  "$codex_version" \
  "$binary_path" \
  "$wrapper_path"
' sh \
    "$DEVOPS_CODEX_VERSION" \
    "$DEVOPS_CODEX_RELEASE_TAG" \
    "$DEVOPS_CODEX_URL" \
    "$DEVOPS_CODEX_SHA256" \
    "$DEVOPS_CODEX_MAXIMUM_BYTES" \
    "$DEVOPS_CODEX_MAXIMUM_EXTRACTED_BYTES" \
    "$DEVOPS_CODEX_ARCHIVE_BINARY_DIR" \
    "$DEVOPS_CODEX_ARCHIVE_SCHEMA_MEMBER" \
    "$DEVOPS_CODEX_ROOT" \
    "$DEVOPS_CODEX_BINARY_PATH" \
    "$DEVOPS_CODEX_SCHEMA_PATH" \
    "$DEVOPS_CODEX_WRAPPER_PATH" \
    "$DEVOPS_CODEX_USER_ROOT" \
    "$DEVOPS_CODEX_SYSTEM_CONFIG_DIR" \
    "$DEVOPS_CODEX_LOG_DIR" \
    "$DEVOPS_CODEX_SQLITE_HOME" \
    "$DEVOPS_CODEX_RUNTIME_ROOT" \
    "$DEVOPS_CODEX_REPOSITORY_URL" \
    "$DEVOPS_CODEX_REPOSITORY_BRANCH" \
    "$devops_codex_clone_source" \
    "$DEVOPS_CODEX_AGENTS" \
    "$DEVOPS_CODEX_HOME" \
    "$DEVOPS_CODEX_SKILLS" \
    "$devops_codex_archive_helper_path" \
    "$ACCOUNT_USERNAME"
}
