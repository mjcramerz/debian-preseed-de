#!/bin/sh
# Shared late_command account helpers. This file is sourced, not executed.

provision_target_identity() {
  render_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/hostname.tmpl)" /etc/hostname 0644
  render_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/hosts.tmpl)" /etc/hosts 0644
}

stage_target_account_shell_assets() {
  install -d -m 0755 /target/etc/skel/primary
  install -d -m 0755 /target/etc/skel/primary/.profile.d
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/skel/primary/.profile.installer-base)" /etc/skel/primary/.profile 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/skel/primary/.bash_profile.installer-base)" /etc/skel/primary/.bash_profile 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/skel/primary/.bashrc.installer-base)" /etc/skel/primary/.bashrc 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/skel/primary/.dircolors)" /etc/skel/primary/.dircolors 0644
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/skel/primary/.vimrc)" /etc/skel/primary/.vimrc 0644
  chown root:root /target/etc/skel/primary/.profile /target/etc/skel/primary/.bash_profile /target/etc/skel/primary/.bashrc
  chown root:root \
    /target/etc/skel/primary/.dircolors \
    /target/etc/skel/primary/.vimrc
}

install_target_account_shell_assets() {
  : "${ACCOUNT_USERNAME:?ACCOUNT_USERNAME must be set}"
  : "${ACCOUNT_HOME:?ACCOUNT_HOME must be set}"

  case "$ACCOUNT_USERNAME" in
    [abcdefghijklmnopqrstuvwxyz_]*)
      ;;
    *)
      installer_fatal "ACCOUNT_USERNAME must start with a lowercase letter or underscore for shell assets"
      ;;
  esac
  case "$ACCOUNT_USERNAME" in
    *[!abcdefghijklmnopqrstuvwxyz0123456789_-]*)
      installer_fatal "ACCOUNT_USERNAME contains unsupported characters for shell assets"
      ;;
  esac
  case "$ACCOUNT_HOME" in
    /*) ;;
    *)
      installer_fatal "ACCOUNT_HOME must be an absolute path for shell assets"
      ;;
  esac
  case "$ACCOUNT_HOME" in
    /|*..*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/-]*)
      installer_fatal "ACCOUNT_HOME contains unsupported path syntax for shell assets"
      ;;
  esac

  # shellcheck disable=SC2016
  run_in_target "install managed shell assets for primary account" /bin/sh -c '
set -eu
account_user=$1
account_home=$2

uid=$(id -u "$account_user")
gid=$(id -g "$account_user")

install -d -m 0700 "$account_home"
for rel_file in .profile .bash_profile .bashrc; do
  src="/etc/skel/primary/${rel_file}"
  dst="${account_home}/${rel_file}"
  [ -r "$src" ] || {
    printf "fatal: missing managed shell asset: %s\n" "$src" >&2
    exit 1
  }
  [ ! -L "$dst" ] || {
    printf "fatal: managed account shell file must not be a symlink: %s\n" "$dst" >&2
    exit 1
  }
  install -m 0600 "$src" "$dst"
  chown "$uid:$gid" "$dst"
done

if [ -d /etc/skel/primary/.profile.d ] && [ ! -L /etc/skel/primary/.profile.d ]; then
  install -d -m 0700 "$account_home/.profile.d"
  chown "$uid:$gid" "$account_home/.profile.d"
  for src in /etc/skel/primary/.profile.d/[0-9][0-9]-*.sh; do
    [ -e "$src" ] || break
    [ -f "$src" ] || continue
    file_name=$(basename "$src")
    dst="$account_home/.profile.d/$file_name"
    [ ! -L "$dst" ] || {
      printf "fatal: managed account profile fragment must not be a symlink: %s\n" "$dst" >&2
      exit 1
    }
    install -m 0600 "$src" "$dst"
    chown "$uid:$gid" "$dst"
  done
fi
' sh "$ACCOUNT_USERNAME" "$ACCOUNT_HOME"
}

account_home_managed_paths() {
  printf '%s\n' "${DIR_HOME_DESKTOP:-}"
  printf '%s\n' "${DIR_HOME_DOCUMENTS:-}"
  printf '%s\n' "${DIR_HOME_DOWNLOADS:-}"
  printf '%s\n' "${DIR_HOME_MUSIC:-}"
  printf '%s\n' "${DIR_HOME_PUBLIC:-}"
  printf '%s\n' "${DIR_HOME_PICTURES:-}"
  printf '%s\n' "${DIR_HOME_TEMPLATES:-}"
  printf '%s\n' "${DIR_HOME_VIDEOS:-}"
  printf '%s\n' "${DIR_HOME_WORKSPACE:-}"
  printf '%s\n' "${DIR_HOME_LOCAL_STATE:-}"
  if command -v installer_selected_class_reference_is_selected >/dev/null 2>&1 &&
     installer_selected_class_reference_is_selected addon/tailscale 2>/dev/null; then
    printf '%s\n' "${DIR_HOME_SYNCTHING:-}"
    printf '%s\n' "${DIR_HOME_SYNCTHING_STATE:-}"
  fi
}

ensure_target_account_home_ownership() {
  : "${ACCOUNT_USERNAME:?ACCOUNT_USERNAME must be set}"
  : "${ACCOUNT_HOME:?ACCOUNT_HOME must be set}"

  case "$ACCOUNT_USERNAME" in
    [abcdefghijklmnopqrstuvwxyz_]*)
      ;;
    *)
      installer_fatal "ACCOUNT_USERNAME must start with a lowercase letter or underscore"
      ;;
  esac
  case "$ACCOUNT_USERNAME" in
    *[!abcdefghijklmnopqrstuvwxyz0123456789_-]*)
      installer_fatal "ACCOUNT_USERNAME contains unsupported characters"
      ;;
  esac
  case "$ACCOUNT_HOME" in
    /*) ;;
    *)
      installer_fatal "ACCOUNT_HOME must be an absolute path"
      ;;
  esac
  case "$ACCOUNT_HOME" in
    /|*..*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/-]*)
      installer_fatal "ACCOUNT_HOME contains unsupported path syntax"
      ;;
  esac

  managed_paths_file=$(mktemp)
  account_home_managed_paths >"$managed_paths_file"
  set --
  while IFS= read -r managed_path; do
    [ -n "$managed_path" ] || continue
    set -- "$@" "$managed_path"
  done <"$managed_paths_file"
  rm -f "$managed_paths_file"

  # shellcheck disable=SC2016
  run_in_target "fix account home and home-subvolume ownership" /bin/sh -c '
set -eu
account_user=$1
account_home=$2
shift 2

fatal() {
  printf "fatal: %s\n" "$*" >&2
  exit 1
}

case "$account_home" in
  /*) ;;
  *) fatal "account home must be absolute: $account_home" ;;
esac
case "$account_home" in
  /|*..*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/-]*)
    fatal "account home contains unsupported path syntax: $account_home"
    ;;
esac

uid=$(id -u "$account_user")
gid=$(id -g "$account_user")

install -d -m 0700 "$account_home"
chown "$uid:$gid" "$account_home"

for path in "$@"; do
  [ -n "$path" ] || continue
  case "$path" in
    "$account_home"/*) ;;
    *) fatal "managed home subvolume path is outside account home: $path" ;;
  esac
  install -d -m 0700 "$path"
  chown "$uid:$gid" "$path"
done

for path in "$account_home" "$@"; do
  [ -n "$path" ] || continue
  [ -d "$path" ] || fatal "managed home path is not a directory: $path"
  owner=$(stat -c "%u:%g" "$path")
  [ "$owner" = "$uid:$gid" ] || fatal "managed home path has owner $owner, expected $uid:$gid: $path"
done
  ' sh \
    "$ACCOUNT_USERNAME" \
    "$ACCOUNT_HOME" \
    "$@"
}

install_target_account_sudoers() {
  : "${ACCOUNT_USERNAME:?ACCOUNT_USERNAME must be set}"

  case "$ACCOUNT_USERNAME" in
    [abcdefghijklmnopqrstuvwxyz_]*)
      ;;
    *)
      installer_fatal "ACCOUNT_USERNAME must start with a lowercase letter or underscore"
      ;;
  esac
  case "$ACCOUNT_USERNAME" in
    *[!abcdefghijklmnopqrstuvwxyz0123456789_-]*)
      installer_fatal "ACCOUNT_USERNAME contains unsupported characters for sudoers"
      ;;
  esac

  sudoers_dir=/target/etc/sudoers.d
  sudoers_target="${sudoers_dir}/${ACCOUNT_USERNAME}"
  sudoers_tmp="${TMP_ENV_DIR}/account.sudoers.rendered"
  install -d -m 0750 "$sudoers_dir"
  installer_apply_scalar_placeholders \
    "$TMP_ENV_DIR/account.sudoers.tmpl" \
    "$sudoers_tmp" \
    ACCOUNT_USERNAME "$ACCOUNT_USERNAME"
  installer_assert_no_unresolved_installer_placeholders "$sudoers_tmp" "account sudoers template ${TMP_ENV_DIR}/account.sudoers.tmpl"
  install -m 0440 "$sudoers_tmp" "$sudoers_target"
  chown root:root "$sudoers_target"
}

configure_target_shared_account_access() {
  : "${ACCOUNT_USERNAME:?ACCOUNT_USERNAME must be set}"
  : "${ACCOUNT_DEFAULT_GROUPS:?ACCOUNT_DEFAULT_GROUPS must be set}"
  : "${DIR_UDEV_CONF_D:?DIR_UDEV_CONF_D must be set}"
  : "${FILE_UDEV_HARDENING_CONF:?FILE_UDEV_HARDENING_CONF must be set}"

  case "$ACCOUNT_USERNAME" in
    [abcdefghijklmnopqrstuvwxyz_]*)
      ;;
    *)
      installer_fatal "ACCOUNT_USERNAME must start with a lowercase letter or underscore"
      ;;
  esac
  case "$ACCOUNT_USERNAME" in
    *[!abcdefghijklmnopqrstuvwxyz0123456789_-]*)
      installer_fatal "ACCOUNT_USERNAME contains unsupported characters for shared account access"
      ;;
  esac

  # shellcheck disable=SC2016
  run_in_target "configure primary account access groups" /bin/sh -c '
set -eu
account_user=$1
default_groups=$2

getent passwd "$account_user" >/dev/null 2>&1 || {
  printf "fatal: primary account is missing from target passwd: %s\n" "$account_user" >&2
  exit 1
}
account_uid=$(id -u "$account_user")
account_gid=$(id -g "$account_user")
case "$account_uid:$account_gid" in
  0:*|65534:*|*:65534)
    printf "fatal: refusing unsafe primary account uid/gid mapping for %s: %s:%s\n" \
      "$account_user" "$account_uid" "$account_gid" >&2
    exit 1
    ;;
esac

getent group devops >/dev/null 2>&1 || groupadd --system devops
required_groups="${default_groups} devops"
current_groups=$(id -nG "$account_user")
missing_groups=

for group_name in $required_groups; do
  case "$group_name" in
    [abcdefghijklmnopqrstuvwxyz_]*)
      ;;
    *)
      printf "fatal: invalid primary account group name: %s\n" "$group_name" >&2
      exit 1
      ;;
  esac
  case "$group_name" in
    *[!abcdefghijklmnopqrstuvwxyz0123456789_-]*)
      printf "fatal: invalid primary account group name: %s\n" "$group_name" >&2
      exit 1
      ;;
  esac
  getent group "$group_name" >/dev/null 2>&1 || {
    printf "fatal: required primary account group is missing: %s\n" "$group_name" >&2
    exit 1
  }
  case " $current_groups " in
    *" $group_name "*) ;;
    *) missing_groups="${missing_groups:+$missing_groups,}$group_name" ;;
  esac
done

if [ -n "$missing_groups" ]; then
  usermod -a -G "$missing_groups" -- "$account_user"
  current_groups=$(id -nG "$account_user")
fi

for group_name in $required_groups; do
  case " $current_groups " in
    *" $group_name "*) ;;
    *)
      printf "fatal: primary account group assignment failed for %s: missing %s\n" \
        "$account_user" "$group_name" >&2
      exit 1
      ;;
  esac
done

for root_owned_path in / /etc /usr /usr/bin /etc/passwd /etc/group /etc/sudo.conf; do
  [ -e "$root_owned_path" ] || {
    printf "fatal: required root-owned target path is missing: %s\n" "$root_owned_path" >&2
    exit 1
  }
  root_owned_ids=$(stat -c "%u:%g" "$root_owned_path")
  [ "$root_owned_ids" = 0:0 ] || {
    printf "fatal: target path must be owned by root:root, found %s: %s\n" \
      "$root_owned_ids" "$root_owned_path" >&2
    exit 1
  }
done

sudo_metadata=$(stat -c "%u:%g:%a" /usr/bin/sudo)
case "$sudo_metadata" in
  0:0:[4567][0-7][0-7][0-7])
    ;;
  *)
    printf "fatal: /usr/bin/sudo must be root-owned with setuid enabled, found %s\n" \
      "$sudo_metadata" >&2
    exit 1
    ;;
esac

printf "account_access user=%s uid=%s gid=%s groups=%s\n" \
  "$account_user" "$account_uid" "$account_gid" "$current_groups"
' sh "$ACCOUNT_USERNAME" "$ACCOUNT_DEFAULT_GROUPS"

  install -d -m 0755 "/target${DIR_UDEV_CONF_D}" "/target${DIR_UDEV_RULES}"
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/udev/udev.conf.d/90-hardening.conf)" "${FILE_UDEV_HARDENING_CONF}" 0644
}
