#!/bin/sh
# Rootless Podman target staging. This file is sourced by shared late_command.
# shellcheck disable=SC2016

podman_fatal() {
  installer_fatal "$@"
}

podman_bool_value() {
  label=$1
  value=$2
  case "$value" in
    1|true|TRUE|yes|YES|on|ON) printf '1\n' ;;
    0|false|FALSE|no|NO|off|OFF) printf '0\n' ;;
    *) podman_fatal "$label must be boolean, got: ${value:-unset}" ;;
  esac
}

podman_require_uint() {
  label=$1
  value=$2
  case "$value" in
    ''|*[!0-9]*) podman_fatal "$label must be a non-negative integer, got: ${value:-unset}" ;;
  esac
}

podman_require_positive_uint() {
  label=$1
  value=$2
  podman_require_uint "$label" "$value"
  [ "$value" -gt 0 ] || podman_fatal "$label must be greater than zero"
}

podman_require_abs_path() {
  label=$1
  value=$2
  case "$value" in
    /*) ;;
    *) podman_fatal "$label must be an absolute path: ${value:-unset}" ;;
  esac
  case "$value" in
    /|*..*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/@%:+,-]*)
      podman_fatal "$label contains unsupported path syntax: $value"
      ;;
  esac
}

podman_resolve_native_storage_driver() {
  requested_driver=$1
  storage_path=$2
  [ -d "$storage_path" ] || podman_fatal "Podman storage path is missing: $storage_path"
  # This function runs in busybox-udeb, which has no stat applet. Query the
  # installed target's coreutils using a path relative to its chroot instead.
  storage_target_root=${INSTALLER_TARGET_DIR:-/target}
  storage_target_root=${storage_target_root%/}
  [ -n "$storage_target_root" ] || podman_fatal "Podman target root must not be /"
  case "$storage_path" in
    "$storage_target_root"/*) storage_target_path=${storage_path#"$storage_target_root"} ;;
    *) podman_fatal "Podman storage path is outside the installation target" ;;
  esac
  podman_require_abs_path "Podman storage path" "$storage_target_path"
  storage_fstype=$(chroot "$storage_target_root" /usr/bin/stat -f -c '%T' -- \
    "$storage_target_path" 2>/dev/null) ||
    podman_fatal "target coreutils could not inspect the Podman storage filesystem"
  [ -n "$storage_fstype" ] || podman_fatal "failed to detect filesystem for Podman storage: $storage_path"
  case "$requested_driver" in
    auto)
      case "$storage_fstype" in
        btrfs) printf '%s\n' btrfs ;;
        ext2/ext3|f2fs|xfs) printf '%s\n' overlay ;;
        *) podman_fatal "no approved native rootless Podman storage driver for filesystem $storage_fstype at $storage_path" ;;
      esac
      ;;
    btrfs)
      [ "$storage_fstype" = btrfs ] ||
        podman_fatal "Podman btrfs storage requires a btrfs backing filesystem, found $storage_fstype"
      printf '%s\n' btrfs
      ;;
    overlay)
      case "$storage_fstype" in
        btrfs|ecryptfs|overlayfs|zfs)
          podman_fatal "native rootless OverlayFS is not approved on $storage_fstype backing storage"
          ;;
        ext2/ext3|f2fs|xfs) printf '%s\n' overlay ;;
        *) podman_fatal "unsupported backing filesystem for native rootless OverlayFS: $storage_fstype" ;;
      esac
      ;;
    *)
      podman_fatal "unsupported PODMAN_STORAGE_DRIVER: $requested_driver"
      ;;
  esac
}

podman_validate_username() {
  label=$1
  value=$2
  case "$value" in
    [abcdefghijklmnopqrstuvwxyz_]*)
      ;;
    *)
      podman_fatal "$label must start with a lowercase letter or underscore"
      ;;
  esac
  case "$value" in
    *[!abcdefghijklmnopqrstuvwxyz0123456789_-]*)
      podman_fatal "$label contains unsupported characters: $value"
      ;;
  esac
}

podman_validate_unit_name() {
  label=$1
  value=$2
  case "$value" in
    *.service) ;;
    *) podman_fatal "$label must resolve to a .service unit name: ${value:-unset}" ;;
  esac
  case "$value" in
    ''|.*|*/*|*..*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789@%:_.-]*)
      podman_fatal "$label contains unsupported unit syntax: ${value:-unset}"
      ;;
  esac
}

podman_addon_is_selected() {
  case "${PODMAN_ADDON_SELECTED:-}" in
    true) return 0 ;;
    false) return 1 ;;
  esac
  installer_selected_class_reference_is_selected addon/podman 2>/dev/null
}

podman_addon_selection_state() {
  if podman_addon_is_selected; then
    printf '%s\n' true
  else
    printf '%s\n' false
  fi
}

podman_runtime_stage_stamp() {
  runtime_state_dir=$(installer_runtime_state_dir)
  printf '%s/podman-rootless.%s.done\n' "$runtime_state_dir" "$1"
}

podman_runtime_stage_is_complete() {
  [ -f "$(podman_runtime_stage_stamp "$1")" ]
}

podman_mark_runtime_stage_complete() {
  stamp_path=$(podman_runtime_stage_stamp "$1")
  install -d -m 0700 "$(dirname "$stamp_path")"
  : >"$stamp_path"
  chmod 0600 "$stamp_path"
}

configure_target_rootless_podman_if_selected() {
  podman_addon_is_selected || return 0
  configure_target_rootless_podman
}

podman_validate_csv_endpoints() {
  label=$1
  csv=$2
  case $- in
    *f*) restore_glob=false ;;
    *)
      restore_glob=true
      set -f
      ;;
  esac
  old_ifs=$IFS
  IFS=,
  # shellcheck disable=SC2086
  set -- $csv
  IFS=$old_ifs
  if [ "$restore_glob" = true ]; then
    set +f
  fi
  for endpoint in "$@"; do
    [ -n "$endpoint" ] || continue
    case "$endpoint" in
      *[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:-]*|.*|*..*)
        podman_fatal "$label contains invalid registry endpoint: $endpoint"
        ;;
    esac
    host=${endpoint%%:*}
    [ -n "$host" ] || podman_fatal "$label contains empty registry host"
    case "$endpoint" in
      *:*)
        port=${endpoint##*:}
        podman_require_positive_uint "$label registry port" "$port"
        [ "$port" -le 65535 ] || podman_fatal "$label registry port must be 65535 or lower: $endpoint"
        ;;
    esac
  done
}

podman_toml_string() {
  case "$1" in
    *[\\\"]*) podman_fatal "unsupported TOML string content: $1" ;;
  esac
  printf '"%s"' "$1"
}

podman_toml_array_from_csv() {
  csv=$1
  case $- in
    *f*) restore_glob=false ;;
    *)
      restore_glob=true
      set -f
      ;;
  esac
  old_ifs=$IFS
  IFS=,
  # shellcheck disable=SC2086
  set -- $csv
  IFS=$old_ifs
  if [ "$restore_glob" = true ]; then
    set +f
  fi
  first=1
  for item in "$@"; do
    [ -n "$item" ] || continue
    if [ "$first" -eq 0 ]; then
      printf ', '
    fi
    podman_toml_string "$item"
    first=0
  done
}

podman_registry_blocks() {
  block_mode=$1
  registries=$2
  case $- in
    *f*) restore_glob=false ;;
    *)
      restore_glob=true
      set -f
      ;;
  esac
  old_ifs=$IFS
  IFS=,
  # shellcheck disable=SC2086
  set -- $registries
  IFS=$old_ifs
  if [ "$restore_glob" = true ]; then
    set +f
  fi
  for registry in "$@"; do
    [ -n "$registry" ] || continue
    printf '\n'
    printf '[[registry]]\n'
    printf 'location = %s\n' "$(podman_toml_string "$registry")"
    case "$block_mode" in
      blocked) printf 'blocked = true\n' ;;
      tls) printf 'blocked = false\n' ;;
      *) podman_fatal "unsupported registry block mode: $block_mode" ;;
    esac
    printf 'insecure = false\n'
  done
}

podman_target_passwd_record() {
  awk -F: -v wanted_user="$PODMAN_SERVICE_USER" '$1 == wanted_user { print $3 ":" $4 ":" $6; exit }' /target/etc/passwd
}

podman_subid_entry() {
  file=$1
  [ -r "$file" ] || return 0
  awk -F: -v user="$PODMAN_SERVICE_USER" '$1 == user { print; exit }' "$file"
}

podman_target_user_unit_path() {
  unit_name=$1
  unit_path=$(target_systemd_unit_path "$unit_name" user 2>/dev/null || true)
  if [ -n "$unit_path" ]; then
    printf '%s\n' "$unit_path"
    return 0
  fi
  for unit_path in /usr/lib/systemd/user "/lib/systemd/user" /etc/systemd/user; do
    [ -r "/target${unit_path}/${unit_name}" ] || continue
    printf '%s\n' "${unit_path}/${unit_name}"
    return 0
  done
  return 1
}

podman_install_symlink_with_backup() {
  link_path=$1
  target_path=$2
  backup_root=$3

  install -d -m 0755 "$(dirname "$link_path")"
  install -d -m 0700 "$backup_root"
  if [ -L "$link_path" ] && [ "$(readlink "$link_path")" = "$target_path" ]; then
    return 0
  fi
  if [ -e "$link_path" ] || [ -L "$link_path" ]; then
    backup_path="${backup_root}/$(basename "$link_path").$(date -u +%Y%m%dT%H%M%SZ)"
    if [ -e "$backup_path" ] || [ -L "$backup_path" ]; then
      backup_path="${backup_path}.$$"
    fi
    mv "$link_path" "$backup_path"
  fi
  ln -s "$target_path" "$link_path"
}

podman_chown_target_paths() {
  chown_flag=$1
  shift
  for target_path in "$@"; do
    [ -n "$target_path" ] || continue
    target_abs_path="/target${target_path}"
    [ -e "$target_abs_path" ] || [ -L "$target_abs_path" ] || continue
    case "$chown_flag" in
      -h)
        chown -h "$PODMAN_SERVICE_UID:$PODMAN_SERVICE_GID" "$target_abs_path"
        ;;
      '')
        chown "$PODMAN_SERVICE_UID:$PODMAN_SERVICE_GID" "$target_abs_path"
        ;;
      *)
        podman_fatal "unsupported chown flag for managed Podman target paths: ${chown_flag}"
        ;;
    esac
  done
}

podman_reject_target_symlink() {
  target_path=$1
  [ ! -L "/target${target_path}" ] || podman_fatal "managed Podman path must not be a symlink: ${target_path}"
}

podman_require_managed_service_home() {
  case "$PODMAN_SERVICE_HOME" in
    /home|/home/*)
      podman_fatal "PODMAN_USER_HOME must not be a login home path for hardened service user ${PODMAN_SERVICE_USER}: ${PODMAN_SERVICE_HOME}"
      ;;
  esac
}

podman_chown_target_tree() {
  seen_paths=" "
  for target_path in "$@"; do
    [ -n "$target_path" ] || continue
    case "$seen_paths" in
      *" $target_path "*) continue ;;
    esac
    seen_paths="${seen_paths}${target_path} "
    podman_reject_target_symlink "$target_path"
    chown -R "$PODMAN_SERVICE_UID:$PODMAN_SERVICE_GID" "/target${target_path}"
  done
}

podman_chmod_target_paths() {
  target_mode=$1
  shift
  for target_path in "$@"; do
    [ -n "$target_path" ] || continue
    [ -e "/target${target_path}" ] || continue
    chmod "$target_mode" "/target${target_path}"
  done
}

podman_clear_target_dir_setgid_bits() {
  seen_paths=" "
  for target_path in "$@"; do
    [ -n "$target_path" ] || continue
    case "$seen_paths" in
      *" $target_path "*) continue ;;
    esac
    seen_paths="${seen_paths}${target_path} "
    podman_reject_target_symlink "$target_path"
    [ -d "/target${target_path}" ] || continue
    find "/target${target_path}" -type d -exec chmod g-s {} +
  done
}

podman_placeholder_map() {
  cat <<EOF
PODMAN_CONTAINERS_CGROUPNS=$PODMAN_CONTAINERS_CGROUPNS
PODMAN_CONTAINERS_LOG_DRIVER=$PODMAN_CONTAINERS_LOG_DRIVER
PODMAN_CONTAINERS_UTSNS=$PODMAN_CONTAINERS_UTSNS
PODMAN_CGROUP_MANAGER=$PODMAN_CGROUP_MANAGER
PODMAN_EVENTS_LOGGER=$PODMAN_EVENTS_LOGGER
PODMAN_RUNTIME=$PODMAN_RUNTIME
PODMAN_NETWORK_BACKEND=$PODMAN_NETWORK_BACKEND
PODMAN_FIREWALL_DRIVER=$PODMAN_FIREWALL_DRIVER
PODMAN_ROOTLESS_NETWORK_CMD=$PODMAN_ROOTLESS_NETWORK_CMD
PODMAN_ROOTLESS_CONTAINERS_CONFIG_DIR=$PODMAN_ROOTLESS_CONTAINERS_CONFIG_DIR
PODMAN_ROOTLESS_TMPDIR=$PODMAN_ROOTLESS_TMPDIR
PODMAN_ROOTLESS_IMAGE_TMPDIR=$PODMAN_ROOTLESS_IMAGE_TMPDIR
PODMAN_ROOTLESS_VOLUME_PATH=$PODMAN_ROOTLESS_VOLUME_PATH
PODMAN_ROOTLESS_STATIC_DIR=$PODMAN_ROOTLESS_STATIC_DIR
PODMAN_ROOTLESS_NETWORK_CONFIG_DIR=$PODMAN_ROOTLESS_NETWORK_CONFIG_DIR
PODMAN_STORAGE_DRIVER=$PODMAN_STORAGE_DRIVER
PODMAN_ROOTLESS_GRAPHROOT=$PODMAN_ROOTLESS_GRAPHROOT
PODMAN_ROOTLESS_IMAGESTORE=$PODMAN_ROOTLESS_IMAGESTORE
PODMAN_ROOTLESS_RUNROOT=$PODMAN_ROOTLESS_RUNROOT
PODMAN_ROOTLESS_BUILDAH_ISOLATION=$PODMAN_ROOTLESS_BUILDAH_ISOLATION
PODMAN_ROOTLESS_BUILDAH_TMPDIR=$PODMAN_ROOTLESS_BUILDAH_TMPDIR
PODMAN_ROOTLESS_SOCKET_URI=$PODMAN_ROOTLESS_SOCKET_URI
PODMAN_API_SET_ENV_ARGS=$PODMAN_API_SET_ENV_ARGS
PODMAN_API_UNSET_ENV_NAMES=$PODMAN_API_UNSET_ENV_NAMES
PODMAN_API_START_UNITS=$PODMAN_API_START_UNITS
PODMAN_ROOTLESS_USERNS_CLONE=$PODMAN_ROOTLESS_USERNS_CLONE
PODMAN_ROOTLESS_MAX_USER_NAMESPACES=$PODMAN_ROOTLESS_MAX_USER_NAMESPACES
PODMAN_SERVICE_SLICE_CPU_WEIGHT=$PODMAN_SERVICE_SLICE_CPU_WEIGHT
PODMAN_SERVICE_SLICE_IO_WEIGHT=$PODMAN_SERVICE_SLICE_IO_WEIGHT
PODMAN_SERVICE_SLICE_TASKS_MAX=$PODMAN_SERVICE_SLICE_TASKS_MAX
PODMAN_SERVICE_SLICE_LINE=$PODMAN_SERVICE_SLICE_LINE
PODMAN_SERVICE_USER=$PODMAN_SERVICE_USER
PODMAN_SERVICE_HOME=$PODMAN_SERVICE_HOME
PODMAN_SERVICE_UID=$PODMAN_SERVICE_UID
PODMAN_LINGER_MARKER=$PODMAN_LINGER_MARKER
PODBIN_USER_HOME_BASE=$PODBIN_USER_HOME_BASE
PODBIN_CONFIG_BASE=$PODBIN_CONFIG_BASE
PODBIN_USER_CONFIG_BASE=$PODBIN_USER_CONFIG_BASE
PODBIN_SYSTEMD_USER_BASE=$PODBIN_SYSTEMD_USER_BASE
PODBIN_ADMIN_META_BASE=$PODBIN_ADMIN_META_BASE
PODBIN_TEMPLATE_DIR=$PODBIN_TEMPLATE_DIR
PODBIN_STATE_BASE=$PODBIN_STATE_BASE
PODBIN_STORAGE_DRIVER=$PODBIN_STORAGE_DRIVER
PODBIN_KEY_DIR=$PODBIN_KEY_DIR
PODBIN_KEY_NAME=$PODBIN_KEY_NAME
PODBIN_HIGH_PORT_MIN=$PODBIN_HIGH_PORT_MIN
PODBIN_PORT_SCAN_START=$PODBIN_PORT_SCAN_START
PODBIN_PORT_SCAN_END=$PODBIN_PORT_SCAN_END
PODBIN_DEFAULT_BIND_IP=$PODBIN_DEFAULT_BIND_IP
PODBIN_DEFAULT_CONTAINER_SSH_PORT=$PODBIN_DEFAULT_CONTAINER_SSH_PORT
PODBIN_DEFAULT_CONTAINER_SSH_USER=$PODBIN_DEFAULT_CONTAINER_SSH_USER
PODBIN_DEFAULT_CONTAINER_SHELL=$PODBIN_DEFAULT_CONTAINER_SHELL
PODBIN_SERVICE_USER=$PODBIN_SERVICE_USER
PODBIN_DEFAULT_IMAGE=$PODBIN_DEFAULT_IMAGE
PODBIN_RUNTIME_USER_NAME=$PODBIN_RUNTIME_USER_NAME
PODBIN_RUNTIME_USER_UID=$PODBIN_RUNTIME_USER_UID
PODBIN_RUNTIME_USER_GID=$PODBIN_RUNTIME_USER_GID
PODBIN_RUNTIME_USER_HOME=$PODBIN_RUNTIME_USER_HOME
PODBIN_RUNTIME_USER_SHELL=$PODBIN_RUNTIME_USER_SHELL
PODBIN_RUNTIME_AUTH_KEYS_DIR=$PODBIN_RUNTIME_AUTH_KEYS_DIR
PODBIN_RUNTIME_WORKDIR=$PODBIN_RUNTIME_WORKDIR
PODBIN_KNOWN_HOSTS_FILE=$PODBIN_KNOWN_HOSTS_FILE
EOF
}

podman_user_api_env_file_lines() {
  if [ "$PODMAN_USER_CONTAINER_HOST" = 1 ]; then
    printf '%s\n' "CONTAINER_HOST=$PODMAN_ROOTLESS_SOCKET_URI"
  fi
  if [ "$PODMAN_USER_DOCKER_HOST" = 1 ]; then
    printf '%s\n' "DOCKER_HOST=$PODMAN_ROOTLESS_SOCKET_URI"
  fi
}

podman_user_api_service_environment_lines() {
  if [ "$PODMAN_USER_CONTAINER_HOST" = 1 ]; then
    printf '%s\n' "Environment=CONTAINER_HOST=$PODMAN_ROOTLESS_SOCKET_URI"
  fi
  if [ "$PODMAN_USER_DOCKER_HOST" = 1 ]; then
    printf '%s\n' "Environment=DOCKER_HOST=$PODMAN_ROOTLESS_SOCKET_URI"
  fi
}

podman_user_api_set_env_args() {
  set_args=
  if [ "$PODMAN_USER_CONTAINER_HOST" = 1 ]; then
    set_args="CONTAINER_HOST=$PODMAN_ROOTLESS_SOCKET_URI"
  fi
  if [ "$PODMAN_USER_DOCKER_HOST" = 1 ]; then
    if [ -n "$set_args" ]; then
      set_args="${set_args} "
    fi
    set_args="${set_args}DOCKER_HOST=$PODMAN_ROOTLESS_SOCKET_URI"
  fi
  printf '%s\n' "$set_args"
}

podman_user_api_unset_env_names() {
  unset_names=
  if [ "$PODMAN_USER_CONTAINER_HOST" = 1 ]; then
    unset_names="CONTAINER_HOST"
  fi
  if [ "$PODMAN_USER_DOCKER_HOST" = 1 ]; then
    if [ -n "$unset_names" ]; then
      unset_names="${unset_names} "
    fi
    unset_names="${unset_names}DOCKER_HOST"
  fi
  printf '%s\n' "$unset_names"
}

podman_render_api_env_assets() {
  service_target="${PODMAN_ROOTLESS_SYSTEMD_DIR}/podman-api-env.service"
  env_target="${PODMAN_ROOTLESS_ENVIRONMENT_DIR}/90-podman-api.conf"

  podman_render_managed_template data/config/podman/templates/rootless/systemd/user/podman-api-env.service.tmpl "$service_target" 0640
  replace_placeholder_line_block "/target${service_target}" "__INSTALLER_PODMAN_API_SERVICE_ENVIRONMENT_LINES__" "$(podman_user_api_service_environment_lines)"

  podman_render_managed_template data/config/podman/templates/rootless/environment.d/90-podman-api.conf.tmpl "$env_target" 0640
  replace_placeholder_line_block "/target${env_target}" "__INSTALLER_PODMAN_API_ENV_FILE_LINES__" "$(podman_user_api_env_file_lines)"
}

podman_render_managed_template() {
  source_relpath=$1
  target_path=$2
  mode=$3
  render_target_asset_with_placeholder_map \
    "$(installer_repo_join_var DIR_HOOKS_TARGET "$source_relpath")" \
    "$target_path" \
    "$mode" \
    podman_placeholder_map
}

podman_render_registries_conf_file() {
  dest_path=$1
  podman_require_abs_path "Podman registries config path" "$dest_path"
  rendered_tmp="${dest_path}.tmp.$$"
  unqualified_toml=$(podman_toml_array_from_csv "$PODMAN_UNQUALIFIED_SEARCH_REGISTRIES")
  blocked_lines=$(podman_registry_blocks blocked "$PODMAN_BLOCKED_REGISTRIES")
  tls_lines=
  if [ "$PODMAN_TLS_ENABLE" = 1 ]; then
    tls_lines=$(podman_registry_blocks tls "$PODMAN_TLS_REGISTRIES")
  fi
  install -d -m 0755 "$(dirname "$dest_path")"
  {
    printf 'short-name-mode = %s\n' "$(podman_toml_string "$PODMAN_SHORT_NAME_MODE")"
    printf 'unqualified-search-registries = [%s]\n' "$unqualified_toml"
    [ -n "$blocked_lines" ] && printf '%s\n' "$blocked_lines"
    [ -n "$tls_lines" ] && printf '%s\n' "$tls_lines"
  } >"$rendered_tmp"
  mv "$rendered_tmp" "$dest_path"
}

podman_ensure_service_account() {
  run_in_target "ensure rootless Podman service account" /bin/sh -c '
set -eu
service_user=$1
service_home=$2
service_shell=$3
service_comment=$4
strip_groups=$5
allowed_groups=$6
service_home_mode=$7

case "$service_home_mode" in
  0700|0711) ;;
  *)
    printf "fatal: invalid Podman service home mode: %s\n" "$service_home_mode" >&2
    exit 1
    ;;
esac

uid_min=$(awk '"'"'$1 == "UID_MIN" && $2 ~ /^[0-9]+$/ { print $2; exit }'"'"' /etc/login.defs 2>/dev/null || true)
[ -n "$uid_min" ] || uid_min=1000

if getent passwd "$service_user" >/dev/null 2>&1; then
  passwd_entry=$(getent passwd "$service_user")
  current_uid=$(printf "%s\n" "$passwd_entry" | cut -d: -f3)
  current_gid=$(printf "%s\n" "$passwd_entry" | cut -d: -f4)
  current_home=$(printf "%s\n" "$passwd_entry" | cut -d: -f6)
  current_shell=$(printf "%s\n" "$passwd_entry" | cut -d: -f7)
  current_group=$(getent group "$current_gid" | cut -d: -f1)
  [ "$current_uid" -lt "$uid_min" ] || {
    printf "fatal: refusing to reuse login-class account for Podman service user: %s\n" "$service_user" >&2
    exit 1
  }
  [ "$current_group" = "$service_user" ] || {
    printf "fatal: Podman service user primary group must be %s, found %s\n" "$service_user" "$current_group" >&2
    exit 1
  }
  [ "$current_home" = "$service_home" ] || usermod -d "$service_home" -- "$service_user"
  [ "$current_shell" = "$service_shell" ] || usermod -s "$service_shell" -- "$service_user"
  gecos=$(printf "%s\n" "$passwd_entry" | cut -d: -f5)
  [ "$gecos" = "$service_comment" ] || usermod -c "$service_comment" -- "$service_user"
else
  groupadd --force --system -- "$service_user"
  useradd --system -g "$service_user" -M -d "$service_home" -s "$service_shell" -c "$service_comment" -- "$service_user"
fi

getent group devops >/dev/null 2>&1 || {
  printf "fatal: required target group is missing: devops\n" >&2
  exit 1
}
usermod -a -G devops -- "$service_user"

install -d -m "$service_home_mode" -o "$service_user" -g "$service_user" "$service_home"

shadow_hash=$(awk -F: -v wanted_user="$service_user" '"'"'$1 == wanted_user { print $2; found=1; exit } END { if (!found) exit 1 }'"'"' /etc/shadow 2>/dev/null || true)
[ -n "$shadow_hash" ] || {
  printf "fatal: Podman service user shadow entry is missing: %s\n" "$service_user" >&2
  exit 1
}

case "$shadow_hash" in
  '!'*|'*')
    ;;
  *)
    usermod -p "!" -- "$service_user"
    ;;
esac

if [ "$strip_groups" = 1 ]; then
  primary_group=$(id -gn -- "$service_user")
  preserved_groups=" ${allowed_groups} devops "
  while IFS= read -r group_name || [ -n "$group_name" ]; do
    [ -n "$group_name" ] || continue
    [ "$group_name" = "$primary_group" ] && continue
    case "$preserved_groups" in
      *" $group_name "*) continue ;;
    esac
    gpasswd -d "$service_user" "$group_name" >/dev/null 2>&1 || true
  done <<EOF
$(id -Gn -- "$service_user" | tr " " "\n")
EOF
fi

shadow_hash=$(awk -F: -v wanted_user="$service_user" '"'"'$1 == wanted_user { print $2; found=1; exit } END { if (!found) exit 1 }'"'"' /etc/shadow 2>/dev/null || true)
case "$shadow_hash" in
  '!'*|'*')
    ;;
  *)
    printf "fatal: Podman service user must remain password-locked: %s\n" "$service_user" >&2
    exit 1
    ;;
esac
' sh \
    "$PODMAN_SERVICE_USER" \
    "$PODMAN_SERVICE_HOME" \
    "$PODMAN_USER_SHELL" \
    "$PODMAN_USER_COMMENT" \
    "$PODMAN_USER_STRIP_GROUPS" \
    "$PODMAN_USER_ALLOWED_GROUPS" \
    "$PODMAN_SERVICE_HOME_MODE"
}

podman_next_subid_start() {
  block_size=$1
  min_start=$2
  max_end=$(awk -F: '
    $2 ~ /^[0-9]+$/ && $3 ~ /^[0-9]+$/ {
      end = $2 + $3 - 1
      if (end > max) {
        max = end
      }
    }
    END {
      if (max == 0) {
        print 99999
      } else {
        print max
      }
    }
  ' /target/etc/subuid /target/etc/subgid 2>/dev/null || printf '99999')
  next=$((max_end + 1))
  next=$((((next + block_size - 1) / block_size) * block_size))
  if [ "$next" -lt "$min_start" ]; then
    next=$min_start
  fi
  printf '%s\n' "$next"
}

podman_subid_range_available() {
  start=$1
  count=$2
  end=$((start + count - 1))
  conflict=$(awk -F: -v user="$PODMAN_SERVICE_USER" -v start="$start" -v end="$end" '
    $1 == user {
      next
    }
    $2 ~ /^[0-9]+$/ && $3 ~ /^[0-9]+$/ {
      entry_start = $2
      entry_end = $2 + $3 - 1
      if (!(end < entry_start || start > entry_end)) {
        printf "%s:%s:%s:%s", FILENAME, $1, $2, $3
        exit
      }
    }
  ' /target/etc/subuid /target/etc/subgid 2>/dev/null || true)
  [ -z "$conflict" ] || podman_fatal "subordinate ID range ${start}:${count} for ${PODMAN_SERVICE_USER} overlaps existing allocation ${conflict}"
}

podman_write_subid_entry() {
  file=$1
  start=$2
  count=$3
  tmp_file="${file}.tmp.$$"
  replacement="${PODMAN_SERVICE_USER}:${start}:${count}"
  awk -F: -v user="$PODMAN_SERVICE_USER" -v replacement="$replacement" '
    BEGIN { done = 0 }
    $1 == user {
      if (!done) {
        print replacement
        done = 1
      }
      next
    }
    { print }
    END {
      if (!done) {
        print replacement
      }
    }
  ' "$file" >"$tmp_file"
  chmod 0644 "$tmp_file"
  mv "$tmp_file" "$file"
}

podman_target_relative_path() {
  target_path=$1
  case "$target_path" in
    /target) printf '/\n' ;;
    /target/*) printf '/%s\n' "${target_path#/target/}" ;;
    *)
      podman_fatal "Podman target path must live below /target: ${target_path:-unset}"
      ;;
  esac
}

podman_prepare_openssl_backend() {
  if command -v openssl >/dev/null 2>&1; then
    PODMAN_OPENSSL_BACKEND=installer
    return 0
  fi

  require_in_target "Podman TLS material"
  if test_in_target test -x /usr/bin/openssl; then
    PODMAN_OPENSSL_BACKEND=target
    return 0
  fi

  podman_fatal "openssl is required to stage Podman TLS material in either the installer or target environment"
}

podman_openssl_path() {
  if [ "${PODMAN_OPENSSL_BACKEND:-installer}" = target ]; then
    podman_target_relative_path "$1"
    return 0
  fi
  printf '%s\n' "$1"
}

podman_run_openssl_quiet() {
  label=$1
  shift

  if [ "${PODMAN_OPENSSL_BACKEND:-installer}" = target ]; then
    run_in_target_quiet "$label" openssl "$@"
    return 0
  fi

  if openssl "$@" >/dev/null 2>&1; then
    return 0
  fi
  podman_fatal "${label} failed"
}

podman_write_rand_hex_file() {
  label=$1
  bytes=$2
  output_path=$3
  output_dir=$(dirname "$output_path")
  tmp_output_path="${output_dir}/.$(basename "$output_path").tmp.$$"

  podman_require_positive_uint "${label} byte count" "$bytes"
  rm -f "$tmp_output_path"

  if [ "${PODMAN_OPENSSL_BACKEND:-installer}" = target ]; then
    target_tmp_output_path=$(podman_target_relative_path "$tmp_output_path")
    if ! attempt_in_target "$label" /bin/sh -c '
set -eu
bytes=$1
output_path=$2
hex=
if command -v openssl >/dev/null 2>&1; then
  hex=$(openssl rand -hex "$bytes" 2>/dev/null || true)
fi
if [ -z "$hex" ] && [ -r /dev/urandom ] && command -v od >/dev/null 2>&1; then
  hex=$(od -An -N "$bytes" -tx1 /dev/urandom 2>/dev/null | tr -d " \n" || true)
fi
[ -n "$hex" ] || exit 1
umask 077
printf "%s\n" "$hex" >"$output_path"
' sh "$bytes" "$target_tmp_output_path"; then
      rm -f "$tmp_output_path"
      podman_fatal "${label} failed"
    fi
  else
    if ! /bin/sh -c '
set -eu
bytes=$1
output_path=$2
hex=
if command -v openssl >/dev/null 2>&1; then
  hex=$(openssl rand -hex "$bytes" 2>/dev/null || true)
fi
if [ -z "$hex" ] && [ -r /dev/urandom ] && command -v od >/dev/null 2>&1; then
  hex=$(od -An -N "$bytes" -tx1 /dev/urandom 2>/dev/null | tr -d " \n" || true)
fi
[ -n "$hex" ] || exit 1
umask 077
printf "%s\n" "$hex" >"$output_path"
' sh "$bytes" "$tmp_output_path"; then
      rm -f "$tmp_output_path"
      podman_fatal "${label} failed"
    fi
  fi

  [ -s "$tmp_output_path" ] || {
    rm -f "$tmp_output_path"
    podman_fatal "${label} produced an empty file"
  }

  chmod 0600 "$tmp_output_path"
  mv -f "$tmp_output_path" "$output_path"
}

podman_ensure_service_subids() {
  subid_count=65536
  subid_min_start=100000
  if [ -r /target/etc/login.defs ]; then
    login_sub_uid_count=$(awk '$1 == "SUB_UID_COUNT" && $2 ~ /^[0-9]+$/ { print $2; exit }' /target/etc/login.defs || true)
    login_sub_gid_count=$(awk '$1 == "SUB_GID_COUNT" && $2 ~ /^[0-9]+$/ { print $2; exit }' /target/etc/login.defs || true)
    login_sub_uid_min=$(awk '$1 == "SUB_UID_MIN" && $2 ~ /^[0-9]+$/ { print $2; exit }' /target/etc/login.defs || true)
    login_sub_gid_min=$(awk '$1 == "SUB_GID_MIN" && $2 ~ /^[0-9]+$/ { print $2; exit }' /target/etc/login.defs || true)
    [ -z "$login_sub_uid_count" ] || subid_count=$login_sub_uid_count
    if [ -n "$login_sub_gid_count" ] && [ "$login_sub_gid_count" -gt "$subid_count" ]; then
      subid_count=$login_sub_gid_count
    fi
    [ -z "$login_sub_uid_min" ] || subid_min_start=$login_sub_uid_min
    if [ -n "$login_sub_gid_min" ] && [ "$login_sub_gid_min" -gt "$subid_min_start" ]; then
      subid_min_start=$login_sub_gid_min
    fi
  fi

  install -d -m 0755 /target/etc
  [ -e /target/etc/subuid ] || : >/target/etc/subuid
  [ -e /target/etc/subgid ] || : >/target/etc/subgid
  [ ! -L /target/etc/subuid ] || podman_fatal "/etc/subuid must not be a symlink"
  [ ! -L /target/etc/subgid ] || podman_fatal "/etc/subgid must not be a symlink"

  subuid_entry=$(podman_subid_entry /target/etc/subuid)
  subgid_entry=$(podman_subid_entry /target/etc/subgid)
  if [ -n "$subuid_entry" ] && [ -n "$subgid_entry" ]; then
    subuid_rest=${subuid_entry#*:}
    subuid_start=${subuid_rest%%:*}
    subuid_existing_count=${subuid_rest#*:}
    subgid_rest=${subgid_entry#*:}
    subgid_start=${subgid_rest%%:*}
    subgid_existing_count=${subgid_rest#*:}
    podman_require_positive_uint subuid_start "$subuid_start"
    podman_require_positive_uint subuid_count "$subuid_existing_count"
    podman_require_positive_uint subgid_start "$subgid_start"
    podman_require_positive_uint subgid_count "$subgid_existing_count"
    [ "$subuid_start" = "$subgid_start" ] || podman_fatal "existing subuid/subgid starts differ for ${PODMAN_SERVICE_USER}"
    [ "$subuid_existing_count" = "$subgid_existing_count" ] || podman_fatal "existing subuid/subgid counts differ for ${PODMAN_SERVICE_USER}"
    subid_start=$subuid_start
  elif [ -n "$subuid_entry" ]; then
    subuid_rest=${subuid_entry#*:}
    subid_start=${subuid_rest%%:*}
    subid_count=${subuid_rest#*:}
    podman_require_positive_uint subuid_start "$subid_start"
    podman_require_positive_uint subuid_count "$subid_count"
  elif [ -n "$subgid_entry" ]; then
    subgid_rest=${subgid_entry#*:}
    subid_start=${subgid_rest%%:*}
    subid_count=${subgid_rest#*:}
    podman_require_positive_uint subgid_start "$subid_start"
    podman_require_positive_uint subgid_count "$subid_count"
  else
    subid_start=$(podman_next_subid_start "$subid_count" "$subid_min_start")
  fi

  podman_subid_range_available "$subid_start" "$subid_count"
  podman_write_subid_entry /target/etc/subuid "$subid_start" "$subid_count"
  podman_write_subid_entry /target/etc/subgid "$subid_start" "$subid_count"
}

podman_install_registry_pki() {
  [ "$PODMAN_TLS_ENABLE" = 1 ] || return 0
  [ -n "$PODMAN_TLS_REGISTRIES" ] || return 0
  podman_prepare_openssl_backend

  pki_root="/target${PODMAN_TLS_PKI_BASE}"
  passphrase_path="/target${PODMAN_TLS_KEY_PASSPHRASE_FILE}"
  ca_key="${pki_root}/private/ca.key.pem"
  ca_cert="${pki_root}/ca/ca.crt"
  passphrase_openssl_path=$(podman_openssl_path "$passphrase_path")
  ca_key_openssl_path=$(podman_openssl_path "$ca_key")
  ca_cert_openssl_path=$(podman_openssl_path "$ca_cert")

  install -d -m 0700 "${pki_root}" "${pki_root}/private" "${pki_root}/ca" "${pki_root}/registries"
  install -d -m 0700 "$(dirname "$passphrase_path")"
  [ ! -L "$passphrase_path" ] || podman_fatal "Podman TLS passphrase path must not be a symlink"
  if [ ! -s "$passphrase_path" ]; then
    podman_write_rand_hex_file "generate Podman TLS passphrase" 32 "$passphrase_path"
  fi
  [ -s "$passphrase_path" ] || podman_fatal "Podman TLS passphrase is empty"
  chmod 0600 "$passphrase_path"

  if [ ! -f "$ca_key" ]; then
    podman_run_openssl_quiet "generate Podman TLS CA key" genpkey \
      -algorithm RSA \
      -aes-256-cbc \
      -pass "file:$passphrase_openssl_path" \
      -pkeyopt "rsa_keygen_bits:$PODMAN_TLS_RSA_BITS" \
      -out "$ca_key_openssl_path"
    chmod 0600 "$ca_key"
  fi
  if [ ! -f "$ca_cert" ]; then
    podman_run_openssl_quiet "generate Podman TLS CA certificate" req -new -x509 \
      -days "$PODMAN_TLS_CA_DAYS" \
      -sha256 \
      -key "$ca_key_openssl_path" \
      -passin "file:$passphrase_openssl_path" \
      -subj "/CN=$PODMAN_TLS_CA_COMMON_NAME" \
      -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
      -addext "keyUsage=critical,keyCertSign,cRLSign" \
      -addext "subjectKeyIdentifier=hash" \
      -out "$ca_cert_openssl_path"
    chmod 0644 "$ca_cert"
  fi

  case $- in
    *f*) restore_glob=false ;;
    *)
      restore_glob=true
      set -f
      ;;
  esac
  old_ifs=$IFS
  IFS=,
  # shellcheck disable=SC2086
  set -- $PODMAN_TLS_REGISTRIES
  IFS=$old_ifs
  if [ "$restore_glob" = true ]; then
    set +f
  fi
  for registry in "$@"; do
    [ -n "$registry" ] || continue
    registry_id=$(printf '%s' "$registry" | tr ':/' '_')
    registry_host=${registry%%:*}
    registry_dir="${pki_root}/registries/${registry_id}"
    key_path="${registry_dir}/server.key.pem"
    csr_path="${registry_dir}/server.csr.pem"
    cert_path="${registry_dir}/server.crt"
    extfile="${registry_dir}/server.ext"
    trust_dir="/target${PODMAN_ROOTLESS_CERTS_DIR}/${registry}"
    key_openssl_path=$(podman_openssl_path "$key_path")
    csr_openssl_path=$(podman_openssl_path "$csr_path")
    cert_openssl_path=$(podman_openssl_path "$cert_path")
    extfile_openssl_path=$(podman_openssl_path "$extfile")
    install -d -m 0700 "$registry_dir"
    install -d -m 0750 "$trust_dir"
    if [ ! -f "$key_path" ]; then
      podman_run_openssl_quiet "generate Podman TLS server key for ${registry}" genpkey \
        -algorithm RSA \
        -aes-256-cbc \
        -pass "file:$passphrase_openssl_path" \
        -pkeyopt "rsa_keygen_bits:$PODMAN_TLS_RSA_BITS" \
        -out "$key_openssl_path"
      chmod 0600 "$key_path"
    fi
    if [ ! -f "$csr_path" ]; then
      podman_run_openssl_quiet "generate Podman TLS CSR for ${registry}" req -new \
        -key "$key_openssl_path" \
        -passin "file:$passphrase_openssl_path" \
        -subj "/CN=$registry" \
        -out "$csr_openssl_path"
      chmod 0640 "$csr_path"
    fi
    if [ ! -f "$extfile" ]; then
      if printf '%s\n' "$registry_host" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$'; then
        printf 'subjectAltName=IP:%s\n' "$registry_host" >"$extfile"
      else
        printf 'subjectAltName=DNS:%s\n' "$registry_host" >"$extfile"
      fi
      {
        printf 'basicConstraints=CA:FALSE\n'
        printf 'keyUsage=digitalSignature,keyEncipherment\n'
        printf 'extendedKeyUsage=serverAuth\n'
      } >>"$extfile"
      chmod 0600 "$extfile"
    fi
    if [ ! -f "$cert_path" ]; then
      podman_run_openssl_quiet "generate Podman TLS server certificate for ${registry}" x509 -req \
        -in "$csr_openssl_path" \
        -CA "$ca_cert_openssl_path" \
        -CAkey "$ca_key_openssl_path" \
        -passin "file:$passphrase_openssl_path" \
        -CAcreateserial \
        -days "$PODMAN_TLS_CERT_DAYS" \
        -sha256 \
        -extfile "$extfile_openssl_path" \
        -out "$cert_openssl_path"
      chmod 0644 "$cert_path"
    fi
    cp "$ca_cert" "$trust_dir/ca.crt"
    chmod 0640 "$trust_dir/ca.crt"
    chown "$PODMAN_SERVICE_UID:$PODMAN_SERVICE_GID" "$trust_dir" "$trust_dir/ca.crt"
  done
}

podman_stage_podbin_assets() {
  podman_render_managed_template etc/default/podbin.tmpl /etc/default/podbin 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/sbin/podbin.tmpl)" /usr/local/sbin/podbin 0755
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET data/config/podman/templates/podbin/containers.conf.tmpl)" "${PODBIN_TEMPLATE_DIR}/containers.conf.tmpl" 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET data/config/podman/templates/podbin/storage.conf.tmpl)" "${PODBIN_TEMPLATE_DIR}/storage.conf.tmpl" 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET data/config/podman/templates/podbin/registries.conf)" "${PODBIN_TEMPLATE_DIR}/registries.conf" 0644
  podman_render_managed_template data/config/podman/templates/podbin/images/runtime/Containerfile.tmpl "${PODBIN_TEMPLATE_DIR}/images/runtime/Containerfile" 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET data/config/podman/templates/podbin/images/runtime/entrypoint.sh.tmpl)" "${PODBIN_TEMPLATE_DIR}/images/runtime/entrypoint.sh" 0644
  podman_render_managed_template data/config/podman/templates/podbin/images/runtime/sshd_config.tmpl "${PODBIN_TEMPLATE_DIR}/images/runtime/sshd_config" 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET data/config/podman/templates/podbin/systemd/user/podbin-rootless.slice)" "${PODBIN_TEMPLATE_DIR}/systemd/user/podbin-rootless.slice" 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET data/config/podman/templates/podbin/systemd/users/container.d/10-podbin-managed.conf)" "${PODBIN_TEMPLATE_DIR}/systemd/users/container.d/10-podbin-managed.conf" 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET data/config/podman/templates/podbin/systemd/users/container.container.tmpl)" "${PODBIN_TEMPLATE_DIR}/systemd/users/container.container.tmpl" 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET data/config/podman/templates/podbin/metadata.env.tmpl)" "${PODBIN_TEMPLATE_DIR}/metadata.env.tmpl" 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET data/config/podman/templates/podbin/user.env.tmpl)" "${PODBIN_TEMPLATE_DIR}/user.env.tmpl" 0644
  install -d -m 0755 \
    "/target${PODBIN_CONFIG_BASE}" \
    "/target${PODBIN_USER_CONFIG_BASE}" \
    "/target${PODBIN_SYSTEMD_USER_BASE}" \
    "/target${PODBIN_ADMIN_META_BASE}" \
    "/target${PODBIN_TEMPLATE_DIR}"
  install -d -m 0711 "/target${PODBIN_USER_HOME_BASE}"
  chown root:root \
    "/target${PODBIN_CONFIG_BASE}" \
    "/target${PODBIN_USER_CONFIG_BASE}" \
    "/target${PODBIN_SYSTEMD_USER_BASE}" \
    "/target${PODBIN_ADMIN_META_BASE}" \
    "/target${PODBIN_TEMPLATE_DIR}" \
    "/target${PODBIN_USER_HOME_BASE}"
}

configure_target_rootless_podman() {
  : "${PODMAN_USER:=podsvc}"
  : "${PODMAN_USER_COMMENT:=Managed Podman service account}"
  : "${PODMAN_USER_HOME:=/data/accounts/podman}"
  : "${PODMAN_USER_SHELL:=/usr/sbin/nologin}"
  : "${PODMAN_USER_LOCK:=1}"
  : "${PODMAN_USER_LINGER:=1}"
  : "${PODMAN_USER_DAEMON:=0}"
  : "${PODMAN_USER_DOCKER_HOST:=1}"
  : "${PODMAN_USER_CONTAINER_HOST:=1}"
  : "${PODMAN_USER_STRIP_GROUPS:=1}"
  : "${PODMAN_USER_ALLOWED_GROUPS:=}"
  : "${PODMAN_SERVICE_SLICE_ENABLE:=1}"
  : "${PODMAN_SERVICE_SLICE_CPU_WEIGHT:=200}"
  : "${PODMAN_SERVICE_SLICE_IO_WEIGHT:=200}"
  : "${PODMAN_SERVICE_SLICE_TASKS_MAX:=8192}"
  : "${PODMAN_ENABLE_ROOTLESS_SYSCTL:=1}"
  : "${PODMAN_ROOTLESS_USERNS_CLONE:=1}"
  : "${PODMAN_ROOTLESS_MAX_USER_NAMESPACES:=28633}"
  : "${PODMAN_USER_CONFIG_BASE:=/data/config/podman}"
  : "${PODMAN_ROOTLESS_STATE_BASE:=/pool/podman}"
  : "${PODMAN_ROOTLESS_TMP_BASE:=$PODMAN_ROOTLESS_STATE_BASE}"
  : "${PODMAN_TLS_PKI_BASE:=/data/pki/tls/podman}"
  : "${PODMAN_TLS_KEY_PASSPHRASE_FILE:=$PODMAN_TLS_PKI_BASE/private/passphrase.txt}"
  : "${PODMAN_STORAGE_DRIVER:=auto}"
  : "${PODMAN_RUNTIME:=crun}"
  : "${PODMAN_EVENTS_LOGGER:=journald}"
  : "${PODMAN_CGROUP_MANAGER:=systemd}"
  : "${PODMAN_NETWORK_BACKEND:=netavark}"
  : "${PODMAN_FIREWALL_DRIVER:=nftables}"
  : "${PODMAN_ROOTLESS_NETWORK_CMD:=pasta}"
  : "${PODMAN_CONTAINERS_LOG_DRIVER:=journald}"
  : "${PODMAN_CONTAINERS_CGROUPNS:=private}"
  : "${PODMAN_CONTAINERS_UTSNS:=private}"
  : "${PODMAN_SHORT_NAME_MODE:=disabled}"
  : "${PODMAN_UNQUALIFIED_SEARCH_REGISTRIES:=}"
  : "${PODMAN_BLOCKED_REGISTRIES:=}"
  : "${PODMAN_ROOTLESS_BUILDAH_ISOLATION:=rootless}"
  : "${PODMAN_TLS_ENABLE:=1}"
  : "${PODMAN_TLS_REGISTRIES:=127.0.0.1:5000,localhost:5000}"
  : "${PODMAN_TLS_CA_COMMON_NAME:=Podman Local Registry CA}"
  : "${PODMAN_TLS_CA_DAYS:=3650}"
  : "${PODMAN_TLS_CERT_DAYS:=825}"
  : "${PODMAN_TLS_RSA_BITS:=4096}"
  : "${PODMAN_PODBIN_ENABLE:=1}"
  : "${PODMAN_LINGER_UNIT_NAME:=podman-rootless-linger.service}"
  : "${PODMAN_LINGER_MARKER:=/usr/local/lib/podman/podman-rootless-linger.done}"

  PODMAN_SERVICE_USER=$PODMAN_USER
  PODMAN_SERVICE_HOME=$PODMAN_USER_HOME
  : "${PODBIN_USER_HOME_BASE:=${PODMAN_SERVICE_HOME}/users}"
  : "${PODBIN_CONFIG_BASE:=$PODMAN_USER_CONFIG_BASE}"
  : "${PODBIN_USER_CONFIG_BASE:=${PODBIN_CONFIG_BASE}/users}"
  : "${PODBIN_SYSTEMD_USER_BASE:=${PODBIN_CONFIG_BASE}/systemd/users}"
  : "${PODBIN_ADMIN_META_BASE:=${PODBIN_CONFIG_BASE}/podbin/users}"
  : "${PODBIN_TEMPLATE_DIR:=${PODBIN_CONFIG_BASE}/templates/podbin}"
  : "${PODBIN_STATE_BASE:=$PODMAN_ROOTLESS_STATE_BASE}"
  : "${PODBIN_STORAGE_DRIVER:=$PODMAN_STORAGE_DRIVER}"
  : "${PODBIN_KEY_DIR:=/data/pki/ssh/podbin}"
  : "${PODBIN_KEY_NAME:=podbin_ed25519}"
  : "${PODBIN_HIGH_PORT_MIN:=1024}"
  : "${PODBIN_PORT_SCAN_START:=22000}"
  : "${PODBIN_PORT_SCAN_END:=60999}"
  : "${PODBIN_DEFAULT_BIND_IP:=127.0.0.1}"
  : "${PODBIN_DEFAULT_CONTAINER_SSH_PORT:=2222}"
  : "${PODBIN_SERVICE_USER:=$PODMAN_SERVICE_USER}"
  : "${PODBIN_DEFAULT_IMAGE:=localhost/podbin-runtime:trixie}"
  : "${PODBIN_RUNTIME_USER_NAME:=poduser}"
  : "${PODBIN_RUNTIME_USER_UID:=2000}"
  : "${PODBIN_RUNTIME_USER_GID:=2000}"
  : "${PODBIN_RUNTIME_USER_HOME:=/home/poduser}"
  : "${PODBIN_RUNTIME_USER_SHELL:=/bin/sh}"
  : "${PODBIN_RUNTIME_AUTH_KEYS_DIR:=${PODBIN_RUNTIME_USER_HOME}/.ssh}"
  : "${PODBIN_RUNTIME_WORKDIR:=/workspace}"
  : "${PODBIN_KNOWN_HOSTS_FILE:=${PODBIN_CONFIG_BASE}/podbin/known_hosts}"
  : "${PODBIN_DEFAULT_CONTAINER_SSH_USER:=$PODBIN_RUNTIME_USER_NAME}"
  : "${PODBIN_DEFAULT_CONTAINER_SHELL:=$PODBIN_RUNTIME_USER_SHELL}"
  PODMAN_USER_LOCK=$(podman_bool_value PODMAN_USER_LOCK "$PODMAN_USER_LOCK")
  PODMAN_USER_LINGER=$(podman_bool_value PODMAN_USER_LINGER "$PODMAN_USER_LINGER")
  PODMAN_USER_DAEMON=$(podman_bool_value PODMAN_USER_DAEMON "$PODMAN_USER_DAEMON")
  PODMAN_USER_DOCKER_HOST=$(podman_bool_value PODMAN_USER_DOCKER_HOST "$PODMAN_USER_DOCKER_HOST")
  PODMAN_USER_CONTAINER_HOST=$(podman_bool_value PODMAN_USER_CONTAINER_HOST "$PODMAN_USER_CONTAINER_HOST")
  PODMAN_USER_STRIP_GROUPS=$(podman_bool_value PODMAN_USER_STRIP_GROUPS "$PODMAN_USER_STRIP_GROUPS")
  PODMAN_SERVICE_SLICE_ENABLE=$(podman_bool_value PODMAN_SERVICE_SLICE_ENABLE "$PODMAN_SERVICE_SLICE_ENABLE")
  PODMAN_ENABLE_ROOTLESS_SYSCTL=$(podman_bool_value PODMAN_ENABLE_ROOTLESS_SYSCTL "$PODMAN_ENABLE_ROOTLESS_SYSCTL")
  PODMAN_ROOTLESS_USERNS_CLONE=$(podman_bool_value PODMAN_ROOTLESS_USERNS_CLONE "$PODMAN_ROOTLESS_USERNS_CLONE")
  PODMAN_TLS_ENABLE=$(podman_bool_value PODMAN_TLS_ENABLE "$PODMAN_TLS_ENABLE")
  PODMAN_PODBIN_ENABLE=$(podman_bool_value PODMAN_PODBIN_ENABLE "$PODMAN_PODBIN_ENABLE")

  podman_validate_username PODMAN_USER "$PODMAN_SERVICE_USER"
  podman_require_abs_path PODMAN_USER_HOME "$PODMAN_SERVICE_HOME"
  podman_require_abs_path PODMAN_USER_SHELL "$PODMAN_USER_SHELL"
  podman_validate_unit_name PODMAN_LINGER_UNIT_NAME "$PODMAN_LINGER_UNIT_NAME"
  for path_var in PODMAN_USER_CONFIG_BASE PODMAN_ROOTLESS_STATE_BASE PODMAN_ROOTLESS_TMP_BASE PODMAN_TLS_PKI_BASE PODMAN_TLS_KEY_PASSPHRASE_FILE; do
    path_value=$(eval "printf '%s\n' \"\${$path_var}\"")
    podman_require_abs_path "$path_var" "$path_value"
  done
  if [ "$PODMAN_PODBIN_ENABLE" = 1 ]; then
    for path_var in PODBIN_USER_HOME_BASE PODBIN_CONFIG_BASE PODBIN_USER_CONFIG_BASE PODBIN_SYSTEMD_USER_BASE PODBIN_ADMIN_META_BASE PODBIN_TEMPLATE_DIR PODBIN_STATE_BASE PODBIN_KEY_DIR PODBIN_DEFAULT_CONTAINER_SHELL PODBIN_RUNTIME_USER_HOME PODBIN_RUNTIME_USER_SHELL PODBIN_RUNTIME_AUTH_KEYS_DIR PODBIN_RUNTIME_WORKDIR PODBIN_KNOWN_HOSTS_FILE; do
      path_value=$(eval "printf '%s\n' \"\${$path_var}\"")
      podman_require_abs_path "$path_var" "$path_value"
    done
  fi
  PODMAN_SERVICE_HOME_MODE=0700
  if [ "$PODMAN_PODBIN_ENABLE" = 1 ]; then
    case "$PODBIN_USER_HOME_BASE" in
      "$PODMAN_SERVICE_HOME")
        podman_fatal "PODBIN_USER_HOME_BASE must not equal PODMAN_USER_HOME"
        ;;
      "$PODMAN_SERVICE_HOME"/*)
        PODMAN_SERVICE_HOME_MODE=0711
        ;;
    esac
  fi
  [ "$PODMAN_USER_LOCK" = 1 ] || podman_fatal "PODMAN_USER_LOCK must remain 1 for hardened Podman service user ${PODMAN_SERVICE_USER}"
  [ "$PODMAN_USER_STRIP_GROUPS" = 1 ] || podman_fatal "PODMAN_USER_STRIP_GROUPS must remain 1 for hardened Podman service user ${PODMAN_SERVICE_USER}"
  [ -z "$PODMAN_USER_ALLOWED_GROUPS" ] || podman_fatal "PODMAN_USER_ALLOWED_GROUPS must remain empty for hardened Podman service user ${PODMAN_SERVICE_USER}"
  case "$PODMAN_STORAGE_DRIVER" in
    auto|btrfs|overlay) ;;
    *) podman_fatal "unsupported PODMAN_STORAGE_DRIVER: $PODMAN_STORAGE_DRIVER" ;;
  esac
  case "$PODMAN_RUNTIME" in crun) ;; *) podman_fatal "unsupported PODMAN_RUNTIME: $PODMAN_RUNTIME" ;; esac
  case "$PODMAN_EVENTS_LOGGER" in journald|file|none) ;; *) podman_fatal "unsupported PODMAN_EVENTS_LOGGER: $PODMAN_EVENTS_LOGGER" ;; esac
  case "$PODMAN_CGROUP_MANAGER" in systemd|cgroupfs) ;; *) podman_fatal "unsupported PODMAN_CGROUP_MANAGER: $PODMAN_CGROUP_MANAGER" ;; esac
  case "$PODMAN_NETWORK_BACKEND" in netavark) ;; *) podman_fatal "PODMAN_NETWORK_BACKEND must be netavark for the nftables-managed rootless policy" ;; esac
  case "$PODMAN_FIREWALL_DRIVER" in nftables) ;; *) podman_fatal "PODMAN_FIREWALL_DRIVER must be nftables; firewalld is not supported" ;; esac
  case "$PODMAN_ROOTLESS_NETWORK_CMD" in pasta|slirp4netns) ;; *) podman_fatal "unsupported PODMAN_ROOTLESS_NETWORK_CMD: $PODMAN_ROOTLESS_NETWORK_CMD" ;; esac
  case "$PODMAN_CONTAINERS_LOG_DRIVER" in journald|k8s-file|json-file|passthrough|none) ;; *) podman_fatal "unsupported PODMAN_CONTAINERS_LOG_DRIVER: $PODMAN_CONTAINERS_LOG_DRIVER" ;; esac
  case "$PODMAN_CONTAINERS_CGROUPNS" in private|host) ;; *) podman_fatal "unsupported PODMAN_CONTAINERS_CGROUPNS: $PODMAN_CONTAINERS_CGROUPNS" ;; esac
  case "$PODMAN_CONTAINERS_UTSNS" in private|host) ;; *) podman_fatal "unsupported PODMAN_CONTAINERS_UTSNS: $PODMAN_CONTAINERS_UTSNS" ;; esac
  case "$PODMAN_SHORT_NAME_MODE" in disabled|enforcing|permissive) ;; *) podman_fatal "unsupported PODMAN_SHORT_NAME_MODE: $PODMAN_SHORT_NAME_MODE" ;; esac
  case "$PODMAN_ROOTLESS_BUILDAH_ISOLATION" in oci|rootless|chroot) ;; *) podman_fatal "unsupported PODMAN_ROOTLESS_BUILDAH_ISOLATION: $PODMAN_ROOTLESS_BUILDAH_ISOLATION" ;; esac
  podman_require_positive_uint PODMAN_SERVICE_SLICE_CPU_WEIGHT "$PODMAN_SERVICE_SLICE_CPU_WEIGHT"
  podman_require_positive_uint PODMAN_SERVICE_SLICE_IO_WEIGHT "$PODMAN_SERVICE_SLICE_IO_WEIGHT"
  podman_require_positive_uint PODMAN_SERVICE_SLICE_TASKS_MAX "$PODMAN_SERVICE_SLICE_TASKS_MAX"
  podman_require_positive_uint PODMAN_ROOTLESS_MAX_USER_NAMESPACES "$PODMAN_ROOTLESS_MAX_USER_NAMESPACES"
  podman_require_positive_uint PODMAN_TLS_CA_DAYS "$PODMAN_TLS_CA_DAYS"
  podman_require_positive_uint PODMAN_TLS_CERT_DAYS "$PODMAN_TLS_CERT_DAYS"
  podman_require_positive_uint PODMAN_TLS_RSA_BITS "$PODMAN_TLS_RSA_BITS"
  [ "$PODMAN_TLS_RSA_BITS" -ge 2048 ] || podman_fatal "PODMAN_TLS_RSA_BITS must be at least 2048"
  if [ "$PODMAN_PODBIN_ENABLE" = 1 ]; then
    podman_require_positive_uint PODBIN_HIGH_PORT_MIN "$PODBIN_HIGH_PORT_MIN"
    podman_require_positive_uint PODBIN_PORT_SCAN_START "$PODBIN_PORT_SCAN_START"
    podman_require_positive_uint PODBIN_PORT_SCAN_END "$PODBIN_PORT_SCAN_END"
    podman_require_positive_uint PODBIN_DEFAULT_CONTAINER_SSH_PORT "$PODBIN_DEFAULT_CONTAINER_SSH_PORT"
    podman_require_positive_uint PODBIN_RUNTIME_USER_UID "$PODBIN_RUNTIME_USER_UID"
    podman_require_positive_uint PODBIN_RUNTIME_USER_GID "$PODBIN_RUNTIME_USER_GID"
    [ "$PODBIN_HIGH_PORT_MIN" -ge 1024 ] || podman_fatal "PODBIN_HIGH_PORT_MIN must be at least 1024"
    [ "$PODBIN_PORT_SCAN_START" -ge "$PODBIN_HIGH_PORT_MIN" ] || podman_fatal "PODBIN_PORT_SCAN_START must be at least PODBIN_HIGH_PORT_MIN"
    [ "$PODBIN_PORT_SCAN_END" -le 65535 ] || podman_fatal "PODBIN_PORT_SCAN_END must be 65535 or lower"
    [ "$PODBIN_PORT_SCAN_START" -le "$PODBIN_PORT_SCAN_END" ] || podman_fatal "PODBIN_PORT_SCAN_START must be <= PODBIN_PORT_SCAN_END"
    [ "$PODBIN_DEFAULT_CONTAINER_SSH_PORT" -ge "$PODBIN_HIGH_PORT_MIN" ] || podman_fatal "PODBIN_DEFAULT_CONTAINER_SSH_PORT must be at least PODBIN_HIGH_PORT_MIN"
    [ "$PODBIN_DEFAULT_CONTAINER_SSH_PORT" -le 65535 ] || podman_fatal "PODBIN_DEFAULT_CONTAINER_SSH_PORT must be 65535 or lower"
    case "$PODBIN_STORAGE_DRIVER" in
      auto|btrfs|overlay) ;;
      *) podman_fatal "unsupported PODBIN_STORAGE_DRIVER: $PODBIN_STORAGE_DRIVER" ;;
    esac
    [ "$PODBIN_STORAGE_DRIVER" = "$PODMAN_STORAGE_DRIVER" ] || podman_fatal "PODBIN_STORAGE_DRIVER must match PODMAN_STORAGE_DRIVER"
    case "$PODBIN_KEY_NAME" in
      podbin_ed25519) ;;
      *) podman_fatal "PODBIN_KEY_NAME must remain podbin_ed25519" ;;
    esac
    [ "$PODBIN_KEY_DIR" = "/data/pki/ssh/podbin" ] || podman_fatal "PODBIN_KEY_DIR must remain /data/pki/ssh/podbin so Podbin cannot read the shared desktop SSH key pool"
    case "$PODBIN_DEFAULT_BIND_IP" in
      127.0.0.1|0.0.0.0) ;;
      *) podman_fatal "PODBIN_DEFAULT_BIND_IP must be 127.0.0.1 or 0.0.0.0" ;;
    esac
    podman_validate_username PODBIN_SERVICE_USER "$PODBIN_SERVICE_USER"
    [ "$PODBIN_SERVICE_USER" = "$PODMAN_SERVICE_USER" ] || podman_fatal "PODBIN_SERVICE_USER must match PODMAN_USER for the reserved Podman service account"
    podman_validate_username PODBIN_RUNTIME_USER_NAME "$PODBIN_RUNTIME_USER_NAME"
    [ "$PODBIN_RUNTIME_USER_NAME" != root ] || podman_fatal "PODBIN_RUNTIME_USER_NAME must not be root"
    [ "$PODBIN_RUNTIME_USER_NAME" != "$PODBIN_SERVICE_USER" ] || podman_fatal "PODBIN_RUNTIME_USER_NAME must not reuse the reserved Podman service account"
    [ "$PODBIN_RUNTIME_AUTH_KEYS_DIR" = "${PODBIN_RUNTIME_USER_HOME}/.ssh" ] || podman_fatal "PODBIN_RUNTIME_AUTH_KEYS_DIR must remain ${PODBIN_RUNTIME_USER_HOME}/.ssh"
    [ "$PODBIN_DEFAULT_CONTAINER_SSH_USER" = "$PODBIN_RUNTIME_USER_NAME" ] || podman_fatal "PODBIN_DEFAULT_CONTAINER_SSH_USER must match PODBIN_RUNTIME_USER_NAME"
    [ "$PODBIN_DEFAULT_CONTAINER_SSH_USER" != root ] || podman_fatal "PODBIN_DEFAULT_CONTAINER_SSH_USER must not be root"
  [ "$PODBIN_DEFAULT_CONTAINER_SHELL" = "$PODBIN_RUNTIME_USER_SHELL" ] || podman_fatal "PODBIN_DEFAULT_CONTAINER_SHELL must match PODBIN_RUNTIME_USER_SHELL"
  podman_validate_username PODBIN_DEFAULT_CONTAINER_SSH_USER "$PODBIN_DEFAULT_CONTAINER_SSH_USER"
  fi
  podman_validate_csv_endpoints PODMAN_UNQUALIFIED_SEARCH_REGISTRIES "$PODMAN_UNQUALIFIED_SEARCH_REGISTRIES"
  podman_validate_csv_endpoints PODMAN_BLOCKED_REGISTRIES "$PODMAN_BLOCKED_REGISTRIES"
  podman_validate_csv_endpoints PODMAN_TLS_REGISTRIES "$PODMAN_TLS_REGISTRIES"
  if podman_runtime_stage_is_complete "$PODMAN_SERVICE_USER"; then
    installer_info "managed rootless Podman already staged earlier in this install for service user=${PODMAN_SERVICE_USER}; skipping duplicate late_command run"
    return 0
  fi

  podman_role=${INSTALLER_HOST_VARIANT:-$(installer_selected_class_for_purpose host-variant 2>/dev/null || true)}
  case "$podman_role" in
    desktop|server) ;;
    *) podman_fatal "unsupported host variant for Podman policy: ${podman_role:-unset}" ;;
  esac
  PODMAN_EFFECTIVE_USER_DAEMON=$PODMAN_USER_DAEMON
  PODMAN_EFFECTIVE_USER_API_ENV=0
  if [ "$podman_role" = server ]; then
    PODMAN_EFFECTIVE_USER_DAEMON=1
  fi
  if [ "$PODMAN_EFFECTIVE_USER_DAEMON" = 1 ] && [ "$PODMAN_USER_LINGER" != 1 ]; then
    podman_fatal "managed Podman user daemon requires PODMAN_USER_LINGER=1 so the rootless Podman socket survives outside interactive logins"
  fi
  PODMAN_ROOTLESS_SOCKET_URI=
  podman_require_managed_service_home

  podman_ensure_service_account
  service_record=$(podman_target_passwd_record)
  [ -n "$service_record" ] || podman_fatal "managed Podman service user is missing from target passwd: ${PODMAN_SERVICE_USER}"
  PODMAN_SERVICE_UID=${service_record%%:*}
  service_record_rest=${service_record#*:}
  PODMAN_SERVICE_GID=${service_record_rest%%:*}
  service_home=${service_record_rest#*:}
  podman_require_positive_uint PODMAN_SERVICE_UID "$PODMAN_SERVICE_UID"
  podman_require_positive_uint PODMAN_SERVICE_GID "$PODMAN_SERVICE_GID"
  [ "$service_home" = "$PODMAN_SERVICE_HOME" ] || podman_fatal "managed Podman service user home drifted from ${PODMAN_SERVICE_HOME}: ${service_home}"

  podman_ensure_service_subids

  PODMAN_ROOTLESS_CONFIG_ROOT="${PODMAN_USER_CONFIG_BASE}"
  PODMAN_ROOTLESS_CONTAINERS_CONFIG_DIR="${PODMAN_ROOTLESS_CONFIG_ROOT}/containers"
  PODMAN_ROOTLESS_QUADLET_DIR="${PODMAN_ROOTLESS_CONTAINERS_CONFIG_DIR}/systemd"
  PODMAN_ROOTLESS_CERTS_DIR="${PODMAN_ROOTLESS_CONTAINERS_CONFIG_DIR}/certs.d"
  PODMAN_ROOTLESS_SYSTEMD_DIR="${PODMAN_ROOTLESS_CONFIG_ROOT}/systemd/user"
  PODMAN_ROOTLESS_ENVIRONMENT_DIR="${PODMAN_ROOTLESS_CONFIG_ROOT}/environment.d"
  PODMAN_ROOTLESS_BACKUP_ROOT="${PODMAN_ROOTLESS_CONFIG_ROOT}/backups"
  PODMAN_ROOTLESS_GRAPHROOT="${PODMAN_ROOTLESS_STATE_BASE}/storage"
  PODMAN_ROOTLESS_IMAGESTORE="${PODMAN_ROOTLESS_STATE_BASE}/imagestore"
  PODMAN_ROOTLESS_RUNTIME_DIR="/run/user/${PODMAN_SERVICE_UID}"
  PODMAN_ROOTLESS_RUNTIME_LIBPOD_DIR="${PODMAN_ROOTLESS_RUNTIME_DIR}/libpod"
  PODMAN_ROOTLESS_RUNROOT="${PODMAN_ROOTLESS_RUNTIME_DIR}/run"
  PODMAN_ROOTLESS_VOLUME_PATH="${PODMAN_ROOTLESS_STATE_BASE}/volumes"
  PODMAN_ROOTLESS_NETWORK_CONFIG_DIR="${PODMAN_ROOTLESS_STATE_BASE}/networks"
  PODMAN_ROOTLESS_STATIC_DIR="${PODMAN_ROOTLESS_STATE_BASE}/libpod"
  PODMAN_ROOTLESS_TMPDIR="${PODMAN_ROOTLESS_RUNTIME_LIBPOD_DIR}/tmp"
  PODMAN_ROOTLESS_IMAGE_TMPDIR="${PODMAN_ROOTLESS_TMP_BASE}/tmp"
  PODMAN_ROOTLESS_BUILDAH_TMPDIR="${PODMAN_ROOTLESS_TMP_BASE}/tmp"
  PODMAN_ROOTLESS_SOCKET_URI="unix:///run/user/${PODMAN_SERVICE_UID}/podman/podman.sock"
  if [ "$PODMAN_USER_DOCKER_HOST" = 1 ] || [ "$PODMAN_USER_CONTAINER_HOST" = 1 ]; then
    PODMAN_EFFECTIVE_USER_API_ENV=1
  fi
  if [ "$PODMAN_EFFECTIVE_USER_API_ENV" = 1 ] && [ "$PODMAN_EFFECTIVE_USER_DAEMON" != 1 ]; then
    podman_fatal "PODMAN_USER_DOCKER_HOST and PODMAN_USER_CONTAINER_HOST require the managed Podman user daemon"
  fi
  PODMAN_API_SET_ENV_ARGS=$(podman_user_api_set_env_args)
  PODMAN_API_UNSET_ENV_NAMES=$(podman_user_api_unset_env_names)
  PODMAN_API_START_UNITS=podman.socket
  if [ "$PODMAN_EFFECTIVE_USER_API_ENV" = 1 ]; then
    PODMAN_API_START_UNITS="podman.socket podman-api-env.service"
  fi
  PODMAN_SERVICE_SLICE_LINE=
  if [ "$PODMAN_SERVICE_SLICE_ENABLE" = 1 ]; then
    PODMAN_SERVICE_SLICE_LINE='Slice=podman-rootless.slice'
  fi

  for managed_root in \
    "$PODMAN_SERVICE_HOME" \
    "$PODMAN_ROOTLESS_CONFIG_ROOT" \
    "$PODMAN_ROOTLESS_STATE_BASE" \
    "$PODMAN_ROOTLESS_TMP_BASE"
  do
    podman_reject_target_symlink "$managed_root"
  done
  if [ "$PODMAN_PODBIN_ENABLE" = 1 ]; then
    for managed_root in \
      "$PODBIN_USER_HOME_BASE" \
      "$PODBIN_CONFIG_BASE" \
      "$PODBIN_USER_CONFIG_BASE" \
      "$PODBIN_SYSTEMD_USER_BASE" \
      "$PODBIN_ADMIN_META_BASE" \
      "$PODBIN_TEMPLATE_DIR" \
      "$PODBIN_STATE_BASE" \
      "$PODBIN_KEY_DIR"
    do
      podman_reject_target_symlink "$managed_root"
    done
  fi
  if [ "$PODMAN_TLS_ENABLE" = 1 ]; then
    podman_reject_target_symlink "$PODMAN_TLS_PKI_BASE"
  fi

  install -d -m 0755 "/target${PODMAN_ROOTLESS_CONFIG_ROOT}"
  chown root:root "/target${PODMAN_ROOTLESS_CONFIG_ROOT}"
  install -d -m 0700 \
    "/target${PODMAN_ROOTLESS_CONTAINERS_CONFIG_DIR}" \
    "/target${PODMAN_ROOTLESS_QUADLET_DIR}/container.d" \
    "/target${PODMAN_ROOTLESS_CERTS_DIR}" \
    "/target${PODMAN_ROOTLESS_SYSTEMD_DIR}" \
    "/target${PODMAN_ROOTLESS_ENVIRONMENT_DIR}" \
    "/target${PODMAN_ROOTLESS_BACKUP_ROOT}" \
    "/target${PODMAN_ROOTLESS_GRAPHROOT}" \
    "/target${PODMAN_ROOTLESS_IMAGESTORE}" \
    "/target${PODMAN_ROOTLESS_VOLUME_PATH}" \
    "/target${PODMAN_ROOTLESS_NETWORK_CONFIG_DIR}" \
    "/target${PODMAN_ROOTLESS_STATIC_DIR}" \
    "/target${PODMAN_ROOTLESS_IMAGE_TMPDIR}"
  PODMAN_STORAGE_DRIVER=$(podman_resolve_native_storage_driver \
    "$PODMAN_STORAGE_DRIVER" "/target${PODMAN_ROOTLESS_STATE_BASE}")
  if [ "$PODMAN_PODBIN_ENABLE" = 1 ]; then
    PODBIN_STORAGE_DRIVER=$PODMAN_STORAGE_DRIVER
  fi
  podman_chown_target_tree \
    "$PODMAN_ROOTLESS_STATE_BASE" \
    "$PODMAN_ROOTLESS_TMP_BASE"
  podman_clear_target_dir_setgid_bits \
    "$PODMAN_ROOTLESS_STATE_BASE" \
    "$PODMAN_ROOTLESS_TMP_BASE" \
    "$PODMAN_ROOTLESS_RUNTIME_DIR" \
    "$PODMAN_ROOTLESS_RUNTIME_LIBPOD_DIR"
  podman_chmod_target_paths 0700 \
    "$PODMAN_ROOTLESS_STATE_BASE" \
    "$PODMAN_ROOTLESS_TMP_BASE" \
    "$PODMAN_ROOTLESS_GRAPHROOT" \
    "$PODMAN_ROOTLESS_IMAGESTORE" \
    "$PODMAN_ROOTLESS_VOLUME_PATH" \
    "$PODMAN_ROOTLESS_NETWORK_CONFIG_DIR" \
    "$PODMAN_ROOTLESS_STATIC_DIR" \
    "$PODMAN_ROOTLESS_IMAGE_TMPDIR" \
    "$PODMAN_ROOTLESS_RUNTIME_DIR" \
    "$PODMAN_ROOTLESS_RUNTIME_LIBPOD_DIR" \
    "$PODMAN_ROOTLESS_RUNROOT" \
    "$PODMAN_ROOTLESS_TMPDIR"

  podman_render_managed_template data/config/podman/templates/rootless/containers.conf.tmpl "${PODMAN_ROOTLESS_CONTAINERS_CONFIG_DIR}/containers.conf" 0640
  podman_render_managed_template data/config/podman/templates/rootless/storage.conf.tmpl "${PODMAN_ROOTLESS_CONTAINERS_CONFIG_DIR}/storage.conf" 0640
  podman_render_registries_conf_file "/target${PODMAN_ROOTLESS_CONTAINERS_CONFIG_DIR}/registries.conf"
  podman_render_managed_template data/config/podman/templates/rootless/containers/systemd/container.d/10-podman-managed.conf.tmpl "${PODMAN_ROOTLESS_QUADLET_DIR}/container.d/10-podman-managed.conf" 0640
  podman_render_managed_template data/config/podman/templates/rootless/systemd/user/buildah-env.service.tmpl "${PODMAN_ROOTLESS_SYSTEMD_DIR}/buildah-env.service" 0640
  if [ "$PODMAN_SERVICE_SLICE_ENABLE" = 1 ]; then
    podman_render_managed_template data/config/podman/templates/rootless/systemd/user/podman-rootless.slice.tmpl "${PODMAN_ROOTLESS_SYSTEMD_DIR}/podman-rootless.slice" 0640
  fi
  if [ "$PODMAN_EFFECTIVE_USER_DAEMON" = 1 ]; then
    podman_render_managed_template data/config/podman/templates/rootless/systemd/user/podman.service.d/10-podman-service-managed.conf "${PODMAN_ROOTLESS_SYSTEMD_DIR}/podman.service.d/10-podman-service-managed.conf" 0640
    stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET data/config/podman/templates/rootless/systemd/user/podman.socket.d/10-podman-socket-managed.conf)" "${PODMAN_ROOTLESS_SYSTEMD_DIR}/podman.socket.d/10-podman-socket-managed.conf" 0640
    if [ "$PODMAN_EFFECTIVE_USER_API_ENV" = 1 ]; then
      podman_render_api_env_assets
    fi
  fi
  if [ "$PODMAN_ENABLE_ROOTLESS_SYSCTL" = 1 ]; then
    podman_render_managed_template etc/sysctl.d/90-podman-rootless.conf.tmpl /etc/sysctl.d/90-podman-rootless.conf 0644
  fi
  podman_chown_target_tree \
    "$PODMAN_ROOTLESS_CONTAINERS_CONFIG_DIR" \
    "$PODMAN_ROOTLESS_SYSTEMD_DIR" \
    "$PODMAN_ROOTLESS_ENVIRONMENT_DIR" \
    "$PODMAN_ROOTLESS_BACKUP_ROOT"

  install -d -m "$PODMAN_SERVICE_HOME_MODE" "/target${PODMAN_SERVICE_HOME}"
  install -d -m 0700 \
    "/target${PODMAN_SERVICE_HOME}/.config" \
    "/target${PODMAN_SERVICE_HOME}/.config/systemd/user" \
    "/target${PODMAN_SERVICE_HOME}/.config/environment.d"
  podman_chown_target_tree "$PODMAN_SERVICE_HOME"
  podman_install_symlink_with_backup "/target${PODMAN_SERVICE_HOME}/.config/containers" "$PODMAN_ROOTLESS_CONTAINERS_CONFIG_DIR" "/target${PODMAN_ROOTLESS_BACKUP_ROOT}"
  podman_install_symlink_with_backup "/target${PODMAN_SERVICE_HOME}/.config/systemd/user/buildah-env.service" "${PODMAN_ROOTLESS_SYSTEMD_DIR}/buildah-env.service" "/target${PODMAN_ROOTLESS_BACKUP_ROOT}"
  if [ "$PODMAN_SERVICE_SLICE_ENABLE" = 1 ]; then
    podman_install_symlink_with_backup "/target${PODMAN_SERVICE_HOME}/.config/systemd/user/podman-rootless.slice" "${PODMAN_ROOTLESS_SYSTEMD_DIR}/podman-rootless.slice" "/target${PODMAN_ROOTLESS_BACKUP_ROOT}"
  fi
  install -d -m 0700 "/target${PODMAN_SERVICE_HOME}/.config/systemd/user/default.target.wants"
  ln -sf ../buildah-env.service "/target${PODMAN_SERVICE_HOME}/.config/systemd/user/default.target.wants/buildah-env.service"
  podman_chown_target_paths '' \
    "${PODMAN_SERVICE_HOME}/.config/systemd/user/default.target.wants"
  podman_chown_target_paths -h \
    "${PODMAN_SERVICE_HOME}/.config/containers" \
    "${PODMAN_SERVICE_HOME}/.config/systemd/user/buildah-env.service" \
    "${PODMAN_SERVICE_HOME}/.config/systemd/user/default.target.wants/buildah-env.service"
  if [ "$PODMAN_SERVICE_SLICE_ENABLE" = 1 ]; then
    podman_chown_target_paths -h \
      "${PODMAN_SERVICE_HOME}/.config/systemd/user/podman-rootless.slice"
  fi

  if [ "$PODMAN_EFFECTIVE_USER_DAEMON" = 1 ]; then
    install -d -m 0700 \
      "/target${PODMAN_SERVICE_HOME}/.config/systemd/user/podman.service.d" \
      "/target${PODMAN_SERVICE_HOME}/.config/systemd/user/podman.socket.d" \
      "/target${PODMAN_SERVICE_HOME}/.config/systemd/user/sockets.target.wants"
    podman_install_symlink_with_backup "/target${PODMAN_SERVICE_HOME}/.config/systemd/user/podman.service.d/10-podman-service-managed.conf" "${PODMAN_ROOTLESS_SYSTEMD_DIR}/podman.service.d/10-podman-service-managed.conf" "/target${PODMAN_ROOTLESS_BACKUP_ROOT}"
    podman_install_symlink_with_backup "/target${PODMAN_SERVICE_HOME}/.config/systemd/user/podman.socket.d/10-podman-socket-managed.conf" "${PODMAN_ROOTLESS_SYSTEMD_DIR}/podman.socket.d/10-podman-socket-managed.conf" "/target${PODMAN_ROOTLESS_BACKUP_ROOT}"
    if [ "$PODMAN_EFFECTIVE_USER_API_ENV" = 1 ]; then
      podman_install_symlink_with_backup "/target${PODMAN_SERVICE_HOME}/.config/systemd/user/podman-api-env.service" "${PODMAN_ROOTLESS_SYSTEMD_DIR}/podman-api-env.service" "/target${PODMAN_ROOTLESS_BACKUP_ROOT}"
      podman_install_symlink_with_backup "/target${PODMAN_SERVICE_HOME}/.config/environment.d/90-podman-api.conf" "${PODMAN_ROOTLESS_ENVIRONMENT_DIR}/90-podman-api.conf" "/target${PODMAN_ROOTLESS_BACKUP_ROOT}"
      ln -sf ../podman-api-env.service "/target${PODMAN_SERVICE_HOME}/.config/systemd/user/default.target.wants/podman-api-env.service"
    fi
    podman_socket_unit=$(podman_target_user_unit_path podman.socket)
    [ -n "$podman_socket_unit" ] || podman_fatal "target podman.socket user unit is missing"
    ln -sf "$podman_socket_unit" "/target${PODMAN_SERVICE_HOME}/.config/systemd/user/sockets.target.wants/podman.socket"
    podman_chown_target_paths '' \
      "${PODMAN_SERVICE_HOME}/.config/systemd/user/podman.service.d" \
      "${PODMAN_SERVICE_HOME}/.config/systemd/user/podman.socket.d" \
      "${PODMAN_SERVICE_HOME}/.config/environment.d" \
      "${PODMAN_SERVICE_HOME}/.config/systemd/user/sockets.target.wants"
    podman_chown_target_paths -h \
      "${PODMAN_SERVICE_HOME}/.config/systemd/user/podman.service.d/10-podman-service-managed.conf" \
      "${PODMAN_SERVICE_HOME}/.config/systemd/user/podman.socket.d/10-podman-socket-managed.conf" \
      "${PODMAN_SERVICE_HOME}/.config/systemd/user/sockets.target.wants/podman.socket"
    if [ "$PODMAN_EFFECTIVE_USER_API_ENV" = 1 ]; then
      podman_chown_target_paths -h \
        "${PODMAN_SERVICE_HOME}/.config/systemd/user/podman-api-env.service" \
        "${PODMAN_SERVICE_HOME}/.config/systemd/user/default.target.wants/podman-api-env.service" \
        "${PODMAN_SERVICE_HOME}/.config/environment.d/90-podman-api.conf"
    fi
  fi
  if [ "$PODMAN_PODBIN_ENABLE" = 1 ]; then
    podman_stage_podbin_assets
    stage_target_helper_docs podbin.md podbin-service-bridge.md
    run_in_target "generate podbin SSH keypair" /usr/local/sbin/podbin --ensure-keypair _
  fi
  podman_install_registry_pki

  if [ "$PODMAN_EFFECTIVE_USER_DAEMON" = 1 ] && [ "$PODMAN_USER_LINGER" = 1 ]; then
    podman_render_managed_template etc/systemd/system/podman-rootless-linger.service.tmpl "/etc/systemd/system/${PODMAN_LINGER_UNIT_NAME}" 0644
    stage_target_systemd_unit_enabled "$PODMAN_LINGER_UNIT_NAME" system
  fi

  [ -r "/target${PODMAN_ROOTLESS_CONTAINERS_CONFIG_DIR}/containers.conf" ] || podman_fatal "missing rootless Podman containers.conf"
  grep -q '^network_backend = "netavark"$' "/target${PODMAN_ROOTLESS_CONTAINERS_CONFIG_DIR}/containers.conf" || podman_fatal "rootless Podman containers.conf must use netavark"
  grep -q '^firewall_driver = "nftables"$' "/target${PODMAN_ROOTLESS_CONTAINERS_CONFIG_DIR}/containers.conf" || podman_fatal "rootless Podman containers.conf must force nftables"
  grep -q "^driver = \"${PODMAN_STORAGE_DRIVER}\"$" "/target${PODMAN_ROOTLESS_CONTAINERS_CONFIG_DIR}/storage.conf" ||
    podman_fatal "rootless Podman storage.conf must use resolved native driver ${PODMAN_STORAGE_DRIVER}"
  if grep -Rqs 'fuse-overlayfs\|mount_program' "/target${PODMAN_ROOTLESS_CONFIG_ROOT}"; then
    podman_fatal "managed rootless Podman configuration must use native storage without a FUSE mount helper"
  fi
  if grep -Rqs 'firewalld' "/target${PODMAN_ROOTLESS_CONFIG_ROOT}"; then
    podman_fatal "managed rootless Podman configuration must not reference firewalld"
  fi
  [ ! -e /target/etc/containers/containers.conf ] || podman_fatal "Podman addon must not stage rootful /etc/containers/containers.conf"
  [ ! -e /target/var/lib/systemd/linger/"${PODMAN_SERVICE_USER}" ] || podman_fatal "Podman addon must not write systemd linger state directly"
  podman_mark_runtime_stage_complete "$PODMAN_SERVICE_USER"

  installer_info "staged managed rootless Podman service user=${PODMAN_SERVICE_USER} home=${PODMAN_SERVICE_HOME} config=${PODMAN_ROOTLESS_CONFIG_ROOT} state=${PODMAN_ROOTLESS_STATE_BASE} storage_driver=${PODMAN_STORAGE_DRIVER} socket_enabled=${PODMAN_EFFECTIVE_USER_DAEMON} role=${podman_role}"
}

configure_target_rootless_podman_without_podbin() {
  PODMAN_PODBIN_ENABLE=0
  export PODMAN_PODBIN_ENABLE
  configure_target_rootless_podman
}
