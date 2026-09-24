#!/bin/sh
# Sourced installer module; edit this file directly.

devops_prepare_codex_layout() {
  # shellcheck disable=SC2016
  run_in_target "prepare OpenAI Codex installation layout" /bin/sh -eu -c '
account_user=$1
codex_root=$2
codex_log_dir=$3
codex_sqlite_home=$4
codex_runtime_root=$5

for required_command in chmod getent id install find; do
  command -v "$required_command" >/dev/null 2>&1 || {
    printf "fatal: required Codex target command is unavailable: %s\n" "$required_command" >&2
    exit 1
  }
done
getent passwd "$account_user" >/dev/null 2>&1 || {
  printf "fatal: required Codex account is missing: %s\n" "$account_user" >&2
  exit 1
}
devops_group_record=$(getent group devops) || {
  printf "fatal: required target group is missing: devops\n" >&2
  exit 1
}
account_uid=$(id -u "$account_user")
devops_gid=${devops_group_record#*:}
devops_gid=${devops_gid#*:}
devops_gid=${devops_gid%%:*}
case "$account_uid:$devops_gid" in
  *[!0123456789:]*|:*|*:)
    printf "fatal: unable to resolve Codex account or devops group ids\n" >&2
    exit 1
    ;;
esac

codex_prepare_directory() {
  directory_label=$1
  directory_path=$2
  expected_uid=$3
  expected_gid=$4
  expected_mode=$5
  expected_metadata="${expected_uid}:${expected_gid}:${expected_mode}"

  if [ -L "$directory_path" ]; then
    printf "fatal: Codex %s must not be a symlink: %s\n" \
      "$directory_label" "$directory_path" >&2
    exit 1
  fi
  if [ -e "$directory_path" ]; then
    [ -d "$directory_path" ] || {
      printf "fatal: Codex %s is not a directory: %s\n" \
        "$directory_label" "$directory_path" >&2
      exit 1
    }
    actual_metadata=$(find -P "$directory_path" -maxdepth 0 -printf "%U:%G:%m")
    [ "$actual_metadata" = "$expected_metadata" ] || {
      printf "fatal: existing Codex %s has unexpected ownership or mode: expected %s, found %s\n" \
        "$directory_label" "$expected_metadata" "$actual_metadata" >&2
      exit 1
    }
    return 0
  fi

  install -d -m "$expected_mode" -o "$expected_uid" -g "$expected_gid" \
    "$directory_path"
  chmod a-s -- "$directory_path"
  chmod "$expected_mode" -- "$directory_path"
  actual_metadata=$(find -P "$directory_path" -maxdepth 0 -printf "%U:%G:%m")
  [ "$actual_metadata" = "$expected_metadata" ] || {
    printf "fatal: prepared Codex %s has unexpected ownership or mode: expected %s, found %s\n" \
      "$directory_label" "$expected_metadata" "$actual_metadata" >&2
    exit 1
  }
}

[ -d /data ] || install -d -m 0755 -o root -g root /data
[ ! -L /data ] || {
  printf "fatal: /data must not be a symlink\n" >&2
  exit 1
}

# A resumed late stage may revisit this installer-owned skeleton. Reuse only
# directories whose type, owner, group, and mode exactly match the contract.
codex_prepare_directory root "$codex_root" 0 "$devops_gid" 3770
codex_prepare_directory share "$codex_root/share" 0 0 755
codex_prepare_directory binary "$codex_root/share/bin" 0 0 755
codex_prepare_directory library "$codex_root/lib" 0 0 755
codex_prepare_directory log "$codex_log_dir" "$account_uid" "$devops_gid" 2770
codex_prepare_directory SQLite "$codex_sqlite_home" "$account_uid" "$devops_gid" 2770
codex_prepare_directory runtime "$codex_runtime_root" "$account_uid" "$devops_gid" 2770
' sh \
    "$ACCOUNT_USERNAME" \
    "$DEVOPS_CODEX_ROOT" \
    "$DEVOPS_CODEX_LOG_DIR" \
    "$DEVOPS_CODEX_SQLITE_HOME" \
    "$DEVOPS_CODEX_RUNTIME_ROOT"
}

devops_apply_codex_tmpfiles() {
  codex_tmpfiles_policy=/etc/tmpfiles.d/80-codex-storage.conf

  [ -r "${target_root}${codex_tmpfiles_policy}" ] ||
    devops_fatal "Codex tmpfiles policy is missing before application: ${codex_tmpfiles_policy}"
  run_in_target "preflight shared logging paths before Codex tmpfiles" \
    /usr/local/libexec/log-layout --preflight || return $?
  run_in_target \
    "apply managed Codex directory policy" \
    /usr/bin/systemd-tmpfiles \
      --create \
      /etc/tmpfiles.d/59-log-layout.conf \
      "$codex_tmpfiles_policy" || return $?

  # Verify the sticky shared root, account-owned state, directly installed
  # root-owned executable assets, and writable account-owned memories marker.
  # shellcheck disable=SC2016
  run_in_target "verify persistent Codex ownership policy" /bin/sh -eu -c '
codex_fatal() {
  printf "fatal: %s\n" "$*" >&2
  exit 1
}

codex_verify_stat() {
  expected=$1
  path=$2
  actual=$(find -P "$path" -maxdepth 0 -printf "%U:%G:%m")
  [ "$actual" = "$expected" ] ||
    codex_fatal "unexpected ownership or mode for ${path}: expected ${expected}, found ${actual}"
}

account_user=$1
codex_root=$2
schema_path=$3
wrapper_path=$4
user_root=$5
system_config_dir=$6
log_dir=$7
sqlite_home=$8
runtime_root=$9
shift 9
home_path=$1
host_log_dir=$2

for required_command in awk find getent id readlink runuser; do
  command -v "$required_command" >/dev/null 2>&1 ||
    codex_fatal "required Codex policy verification command is unavailable: $required_command"
done

account_uid=$(id -u "$account_user")
devops_gid=$(getent group devops | awk -F: "{ print \$3; exit }")
case "$account_uid:$devops_gid" in
  *[!0123456789:]*|:*|*:) codex_fatal "unable to resolve Codex account or devops group ids" ;;
esac

codex_verify_stat "0:${devops_gid}:3770" "$codex_root"
codex_verify_stat "0:0:755" "$codex_root/share"
codex_verify_stat "0:0:755" "$codex_root/share/bin"
first_binary=$(find "$codex_root/share/bin" \
  -mindepth 1 -maxdepth 1 -type f -links 1 -print)
[ -n "$first_binary" ] ||
  codex_fatal "Codex binary directory does not contain a direct regular file"
hidden_binary=$(find "$codex_root/share/bin" \
  -mindepth 1 -maxdepth 1 -name ".*" -print)
[ -z "$hidden_binary" ] ||
  codex_fatal "Codex binary directory contains an unexpected hidden entry: $hidden_binary"
unsafe_binary_entry=$(find "$codex_root/share/bin" \
  -mindepth 1 -maxdepth 1 \( ! -type f -o -type l -o ! -links 1 \) -print)
[ -z "$unsafe_binary_entry" ] ||
  codex_fatal "Codex binary directory contains an unsafe entry: $unsafe_binary_entry"
for binary_path in "$codex_root/share/bin"/*; do
  [ -f "$binary_path" ] && [ ! -L "$binary_path" ] ||
    codex_fatal "Codex binary is not a direct regular file: $binary_path"
  binary_name=${binary_path##*/}
  case "$binary_name" in
    ""|*[!A-Za-z0-9._+-]*)
      codex_fatal "installed Codex binary name is malformed: $binary_name"
      ;;
  esac
  codex_verify_stat "0:0:755" "$binary_path"
  /usr/sbin/runuser -u "$account_user" -- /usr/bin/test -x "$binary_path" ||
    codex_fatal "managed desktop account cannot execute Codex binary: $binary_path"
done
unset binary_name binary_path first_binary hidden_binary unsafe_binary_entry
[ -f "$schema_path" ] && [ ! -L "$schema_path" ] ||
  codex_fatal "Codex configuration schema is not a direct regular file"
codex_verify_stat "0:0:644" "$schema_path"
codex_verify_stat "0:0:644" "$codex_root/.codex-release"
codex_verify_stat "0:0:755" "$codex_root/lib"
codex_verify_stat "0:0:755" "$wrapper_path"
codex_verify_stat "${account_uid}:${devops_gid}:750" "$user_root"
repository_git_path="$user_root/.git"
codex_verify_stat "${account_uid}:${devops_gid}:750" "$repository_git_path"
unsafe_repository_git_entry=$(find "$repository_git_path" -xdev \
  \( -type l -o \( ! -type d ! -type f \) -o \( -type f ! -links 1 \) \) \
  -print -quit)
[ -z "$unsafe_repository_git_entry" ] ||
  codex_fatal "Codex repository metadata contains an unsafe installed entry: $unsafe_repository_git_entry"
unset unsafe_repository_git_entry
misowned_repository_git_entry=$(find "$repository_git_path" -xdev \
  \( ! -uid "$account_uid" -o ! -gid "$devops_gid" \) -print -quit)
[ -z "$misowned_repository_git_entry" ] ||
  codex_fatal "Codex repository metadata is not fully account-owned: $misowned_repository_git_entry"
unset misowned_repository_git_entry
misconfigured_repository_git_entry=$(find "$repository_git_path" -xdev \
  \( \( -type d ! -perm 0750 \) -o \( -type f ! -perm 0640 \) \) \
  -print -quit)
[ -z "$misconfigured_repository_git_entry" ] ||
  codex_fatal "Codex repository metadata has an unexpected installed mode: $misconfigured_repository_git_entry"
unset misconfigured_repository_git_entry
codex_verify_stat "0:0:755" "$user_root/etc"
codex_verify_stat "${account_uid}:${devops_gid}:2770" "$home_path"
codex_verify_stat "${account_uid}:${devops_gid}:2770" "$home_path/memories"
codex_verify_stat "${account_uid}:${devops_gid}:660" "$home_path/memories/.git"
for shared_home_path in sessions shell_snapshots archived_sessions; do
  codex_verify_stat \
    "${account_uid}:${devops_gid}:2770" \
    "$home_path/$shared_home_path"
done
unset shared_home_path
for shared_state_file in history.jsonl session_index.jsonl external_agent_session_imports.json; do
  codex_verify_stat \
    "${account_uid}:${devops_gid}:660" \
    "$home_path/$shared_state_file"
done
unset shared_state_file
codex_verify_stat "${account_uid}:${devops_gid}:2770" "$log_dir"
codex_verify_stat "${account_uid}:${devops_gid}:2770" "$host_log_dir"
codex_verify_stat "${account_uid}:${devops_gid}:2770" "$sqlite_home"
codex_verify_stat "${account_uid}:${devops_gid}:2770" "$runtime_root"
codex_verify_stat "${account_uid}:${devops_gid}:700" "$runtime_root/.control"
codex_verify_stat "${account_uid}:${devops_gid}:700" "$codex_root/packages"
codex_verify_stat "${account_uid}:${devops_gid}:700" "$codex_root/sockets"
codex_verify_stat "${account_uid}:${devops_gid}:700" "$codex_root/credentials"
codex_verify_stat "${account_uid}:${devops_gid}:600" "$codex_root/credentials/mcp.env"
# Codex authentication state is absent before login and private when present.
if [ -e "$home_path/auth.json" ] || [ -L "$home_path/auth.json" ]; then
  [ -f "$home_path/auth.json" ] && [ ! -L "$home_path/auth.json" ] ||
    codex_fatal "CODEX_HOME auth state is not a direct regular file"
  [ "$(find -P "$home_path/auth.json" -maxdepth 0 -printf "%n")" = 1 ] ||
    codex_fatal "CODEX_HOME auth state must not be hard linked"
  codex_verify_stat "${account_uid}:${devops_gid}:600" "$home_path/auth.json"
fi
codex_verify_stat "${account_uid}:${devops_gid}:700" "$home_path/app-server-control"
codex_verify_stat \
  "${account_uid}:${devops_gid}:600" \
  "$home_path/app-server-control/app-server-startup.lock"
[ -L "$home_path/packages" ] &&
  [ "$(readlink -- "$home_path/packages")" = "$codex_root/packages" ] ||
  codex_fatal "CODEX_HOME package link does not target the managed package root"
[ -L "$home_path/app-server-control/app-server-control.sock" ] &&
  [ "$(readlink -- "$home_path/app-server-control/app-server-control.sock")" = "$codex_root/sockets/app-server-control.sock" ] ||
  codex_fatal "default app-server socket link does not target the managed listener"
codex_verify_stat "0:0:755" "$system_config_dir"

non_root_repository_etc_entry=$(find "$user_root/etc" -xdev \
  \( ! -uid 0 -o ! -gid 0 \) -print)
[ -z "$non_root_repository_etc_entry" ] ||
  codex_fatal "Codex repository etc subtree is not fully root-owned: $non_root_repository_etc_entry"

for writable_path in \
  "$codex_root" \
  "$user_root" \
  "$repository_git_path" \
  "$home_path" \
  "$home_path/memories" \
  "$home_path/memories/.git" \
  "$log_dir" \
  "$host_log_dir" \
  "$sqlite_home" \
  "$runtime_root" \
  "$codex_root/packages" \
  "$codex_root/sockets" \
  "$codex_root/credentials" \
  "$home_path/app-server-control" \
  "$home_path/app-server-control/app-server-startup.lock"
do
  /usr/sbin/runuser -u "$account_user" -- /usr/bin/test -w "$writable_path" ||
    codex_fatal "managed desktop account cannot write required Codex path: $writable_path"
done
unset writable_path

/usr/sbin/runuser -u "$account_user" -- /usr/bin/test -x "$wrapper_path" ||
  codex_fatal "managed desktop account cannot execute the Codex wrapper"
/usr/sbin/runuser -u "$account_user" -- /usr/bin/test -r "$schema_path" ||
  codex_fatal "managed desktop account cannot read the Codex configuration schema"
if /usr/sbin/runuser -u "$account_user" -- /usr/bin/test -w "$schema_path"; then
  codex_fatal "managed desktop account can unexpectedly write the Codex configuration schema"
fi
if /usr/sbin/runuser -u "$account_user" -- \
  /usr/bin/test -w "$codex_root/.codex-release"
then
  codex_fatal "managed desktop account can unexpectedly write Codex release metadata"
fi
' sh \
    "$ACCOUNT_USERNAME" \
    "$DEVOPS_CODEX_ROOT" \
    "$DEVOPS_CODEX_SCHEMA_PATH" \
    "$DEVOPS_CODEX_WRAPPER_PATH" \
    "$DEVOPS_CODEX_USER_ROOT" \
    "$DEVOPS_CODEX_SYSTEM_CONFIG_DIR" \
    "$DEVOPS_CODEX_LOG_DIR" \
    "$DEVOPS_CODEX_SQLITE_HOME" \
    "$DEVOPS_CODEX_RUNTIME_ROOT" \
    "$DEVOPS_CODEX_HOME" \
    "$devops_codex_host_log_dir"
}

