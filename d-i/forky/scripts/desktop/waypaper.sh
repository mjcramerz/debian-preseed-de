#!/bin/sh
# Pinned Waypaper pipx installation helpers. This file is sourced, not executed.

desktop_waypaper_fail() {
  installer_fatal "Waypaper: $*"
}

desktop_waypaper_validate_unsigned_integer() {
  waypaper_value_name=$1
  waypaper_value=$2

  case "$waypaper_value" in
    ''|*[!0123456789]*)
      desktop_waypaper_fail "${waypaper_value_name} must be an unsigned integer"
      ;;
  esac
}

desktop_waypaper_validate_policy() {
  : "${LABWC_WAYPAPER_VERSION:?LABWC_WAYPAPER_VERSION must be set}"
  : "${LABWC_WAYPAPER_INSTALL_TIMEOUT_SECONDS:?LABWC_WAYPAPER_INSTALL_TIMEOUT_SECONDS must be set}"
  : "${ACCOUNT_USERNAME:?ACCOUNT_USERNAME must be set}"
  : "${ACCOUNT_HOME:?ACCOUNT_HOME must be set}"

  case "$LABWC_WAYPAPER_VERSION" in
    *[!0123456789.]*|.*|*.|*..*)
      desktop_waypaper_fail "LABWC_WAYPAPER_VERSION is invalid: ${LABWC_WAYPAPER_VERSION}"
      ;;
  esac
  desktop_waypaper_validate_unsigned_integer \
    LABWC_WAYPAPER_INSTALL_TIMEOUT_SECONDS \
    "$LABWC_WAYPAPER_INSTALL_TIMEOUT_SECONDS"
  [ "$LABWC_WAYPAPER_INSTALL_TIMEOUT_SECONDS" -ge 60 ] &&
    [ "$LABWC_WAYPAPER_INSTALL_TIMEOUT_SECONDS" -le 1800 ] ||
    desktop_waypaper_fail "LABWC_WAYPAPER_INSTALL_TIMEOUT_SECONDS must be between 60 and 1800"

  case "$ACCOUNT_USERNAME" in
    ''|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-]*)
      desktop_waypaper_fail "ACCOUNT_USERNAME contains unsupported characters"
      ;;
  esac
  desktop_require_absolute_account_home
}

desktop_waypaper_seal_runtime() {
  waypaper_root=$1
  waypaper_pipx_home=$2
  waypaper_bin_dir=$3
  waypaper_binary=$4
  waypaper_system_binary=$5

  # The pipx build runs as a transient unprivileged account with a private HOME,
  # so it cannot execute PyPI build hooks as root. Seal the completed runtime
  # before any user session starts: normal operation then resolves only
  # root-owned, non-writable interpreter code and entry points.
  # shellcheck disable=SC2016 # The quoted program executes inside the target.
  run_in_target "seal root-owned Waypaper pipx runtime" /bin/sh -eu -c '
root=$1
pipx_home=$2
pipx_bin_dir=$3
binary=$4
system_binary=$5

[ -d "$root" ] && [ ! -L "$root" ] ||
  { printf "%s\n" "Waypaper runtime root is missing or symbolic" >&2; exit 1; }
[ -d "$pipx_home" ] && [ ! -L "$pipx_home" ] ||
  { printf "%s\n" "Waypaper pipx home is missing or symbolic" >&2; exit 1; }
[ -d "$pipx_bin_dir" ] && [ ! -L "$pipx_bin_dir" ] ||
  { printf "%s\n" "Waypaper pipx bin directory is missing or symbolic" >&2; exit 1; }
[ -d "${pipx_home}/venvs" ] && [ ! -L "${pipx_home}/venvs" ] ||
  { printf "%s\n" "Waypaper pipx venv directory is missing or symbolic" >&2; exit 1; }
[ -d "${pipx_home}/venvs/waypaper" ] && [ ! -L "${pipx_home}/venvs/waypaper" ] ||
  { printf "%s\n" "Waypaper virtual environment is missing or symbolic" >&2; exit 1; }
[ -x "$binary" ] ||
  { printf "%s\n" "Waypaper pipx entry point is missing or not executable" >&2; exit 1; }

unsafe_node=$(
  /usr/bin/find "$root" -xdev \( ! -type d -a ! -type f -a ! -type l \) -print -quit
) || {
  printf "%s\n" "Waypaper runtime node inspection failed" >&2
  exit 1
}
[ -z "$unsafe_node" ] || {
  printf "%s\n" "Waypaper runtime contains an unsupported filesystem node" >&2
  exit 1
}
unsafe_link=$(
  /usr/bin/find "$root" -xdev -type l \
  ! -exec /bin/sh -eu -c '"'"'
root=$1
shift
for link_path; do
  [ -L "$link_path" ] || exit 1
  resolved_path=$(/usr/bin/readlink -f -- "$link_path") || exit 1
  case "$resolved_path" in
    "$root"/*|/usr/bin/python3|/usr/bin/python3.[0-9]*) ;;
    *) exit 1 ;;
  esac
done
'"'"' sh "$root" {} \; -print -quit
) || {
  printf "%s\n" "Waypaper runtime symbolic-link inspection failed" >&2
  exit 1
}
[ -z "$unsafe_link" ] || {
  printf "%s\n" "Waypaper runtime has an unsafe symbolic-link target" >&2
  exit 1
}

/usr/bin/find "$root" -xdev -type d -exec /usr/bin/chown root:root {} +
/usr/bin/find "$root" -xdev -type f -exec /usr/bin/chown root:root {} +
/usr/bin/find "$root" -xdev -type l -exec /usr/bin/chown -h root:root {} +
/usr/bin/find "$root" -xdev -type d -exec /usr/bin/chmod 0755 {} +
/usr/bin/find "$root" -xdev -type f -perm /111 -exec /usr/bin/chmod 0755 {} +
/usr/bin/find "$root" -xdev -type f ! -perm /111 -exec /usr/bin/chmod 0644 {} +

unsafe_path=$(
  /usr/bin/find "$root" -xdev \( -type d -o -type f \) \
    \( ! -user root -o ! -group root -o -perm /022 -o -perm /6000 \) -print -quit
) || {
  printf "%s\n" "Waypaper runtime ownership inspection failed" >&2
  exit 1
}
[ -z "$unsafe_path" ] || {
  printf "%s\n" "Waypaper runtime has unsafe ownership or permissions" >&2
  exit 1
}
unsafe_link_owner=$(
  /usr/bin/find "$root" -xdev -type l \
    \( ! -user root -o ! -group root \) -print -quit
) || {
  printf "%s\n" "Waypaper symbolic-link ownership inspection failed" >&2
  exit 1
}
[ -z "$unsafe_link_owner" ] || {
  printf "%s\n" "Waypaper runtime has unsafe symbolic-link ownership" >&2
  exit 1
}

unreadable_file=$(
  /usr/bin/find "$root" -xdev -type f ! -perm -004 -print -quit
) || {
  printf "%s\n" "Waypaper runtime readability inspection failed" >&2
  exit 1
}
[ -z "$unreadable_file" ] || {
  printf "%s\n" "Waypaper runtime has a file unreadable by the desktop user" >&2
  exit 1
}

unexecutable_file=$(
  /usr/bin/find "$root" -xdev -type f -perm /111 ! -perm -001 -print -quit
) || {
  printf "%s\n" "Waypaper runtime executability inspection failed" >&2
  exit 1
}
[ -z "$unexecutable_file" ] || {
  printf "%s\n" "Waypaper runtime has an executable file unusable by the desktop user" >&2
  exit 1
}

/usr/bin/install -d -o root -g root -m 0755 /usr/local/bin
if [ -e "$system_binary" ] && [ ! -L "$system_binary" ]; then
  printf "%s\n" "refusing to replace non-symbolic Waypaper system entry point" >&2
  exit 1
fi
/usr/bin/rm -f -- "$system_binary"
/usr/bin/ln -s -- "$binary" "$system_binary"
/usr/bin/chown -h root:root "$system_binary"
resolved_system_binary=$(/usr/bin/readlink -f -- "$system_binary") || exit 1
case "$resolved_system_binary" in
  "$root"/*) ;;
  *)
    printf "%s\n" "Waypaper system entry point resolves outside the managed runtime" >&2
    exit 1
    ;;
esac
' sh \
    "$waypaper_root" \
    "$waypaper_pipx_home" \
    "$waypaper_bin_dir" \
    "$waypaper_binary" \
    "$waypaper_system_binary"
}

desktop_install_waypaper() {
  desktop_waypaper_validate_policy

  waypaper_account_ids=$(desktop_primary_account_ids "$ACCOUNT_USERNAME" || true)
  case "$waypaper_account_ids" in
    [0123456789]*:[0123456789]*)
      case "$waypaper_account_ids" in
        *:*:*|*[!0123456789:]*)
          desktop_waypaper_fail "target uid/gid is not numeric: ${waypaper_account_ids}"
          ;;
      esac
      ;;
    *)
      desktop_waypaper_fail "target uid/gid is unavailable for ${ACCOUNT_USERNAME}"
      ;;
  esac
  waypaper_account_uid=${waypaper_account_ids%%:*}
  waypaper_account_gid=${waypaper_account_ids#*:}
  waypaper_root=/opt/waypaper
  waypaper_pipx_home="${waypaper_root}/pipx"
  waypaper_bin_dir="${waypaper_root}/bin"
  waypaper_binary="${waypaper_bin_dir}/waypaper"
  waypaper_pipx_man_dir="${waypaper_root}/man"
  waypaper_build_home="${waypaper_root}/.pipx-build-home"
  waypaper_build_account=installer-pipx-build
  waypaper_system_binary=/usr/local/bin/waypaper
  waypaper_launcher_dir="${ACCOUNT_HOME}/.local/share/applications"
  waypaper_launcher="${waypaper_launcher_dir}/waypaper.desktop"

  for waypaper_path in \
    "$waypaper_root" \
    "$waypaper_pipx_home" \
    "$waypaper_bin_dir" \
    "$waypaper_pipx_man_dir" \
    "$waypaper_build_home"
  do
    [ ! -L "/target${waypaper_path}" ] ||
      desktop_waypaper_fail \
        "managed Waypaper path must not be a symbolic link: ${waypaper_path}"
  done

  install -d -m 0755 \
    "/target${ACCOUNT_HOME}/.local" \
    "/target${ACCOUNT_HOME}/.local/share" \
    "/target${waypaper_launcher_dir}" \
    "/target${waypaper_root}" \
    "/target${waypaper_pipx_home}" \
    "/target${waypaper_bin_dir}" \
    "/target${waypaper_pipx_man_dir}" \
    "/target${waypaper_build_home}"
  desktop_transient_pipx_build_account_prepare \
    "$waypaper_build_account" \
    "$waypaper_build_home" \
    "$waypaper_pipx_home" \
    "$waypaper_bin_dir" \
    "$waypaper_pipx_man_dir"

  # Build under a dedicated non-login account, outside the desktop account
  # home, then remove that account before sealing the runtime. Exposing system
  # site packages intentionally reuses Debian's python3-gi/PyGObject instead of
  # attempting an unpinned source build from PyPI.
  if ! attempt_in_target "install pinned Waypaper with pipx" \
    /usr/bin/timeout \
      --signal=TERM \
      --kill-after=15s \
      "${LABWC_WAYPAPER_INSTALL_TIMEOUT_SECONDS}s" \
      /usr/sbin/runuser \
        -u "$waypaper_build_account" \
        -- \
        /usr/bin/env -i \
          HOME="$waypaper_build_home" \
          USER="$waypaper_build_account" \
          LOGNAME="$waypaper_build_account" \
          PATH="/usr/local/bin:/usr/bin:/bin" \
          TMPDIR="$waypaper_build_home/tmp" \
          XDG_CACHE_HOME="$waypaper_build_home/cache" \
          XDG_CONFIG_HOME="$waypaper_build_home/config" \
          XDG_DATA_HOME="$waypaper_build_home/data" \
          XDG_STATE_HOME="$waypaper_build_home/state" \
          PIPX_HOME="$waypaper_pipx_home" \
          PIPX_BIN_DIR="$waypaper_bin_dir" \
          PIPX_MAN_DIR="$waypaper_pipx_man_dir" \
          PIPX_DEFAULT_PYTHON=/usr/bin/python3 \
          PIP_CONFIG_FILE=/dev/null \
          PIP_DISABLE_PIP_VERSION_CHECK=1 \
          PIP_NO_CACHE_DIR=1 \
          PIP_NO_INPUT=1 \
          PYTHONNOUSERSITE=1 \
          PIP_DEFAULT_TIMEOUT=30 \
          PIP_RETRIES=3 \
          /usr/bin/pipx \
            install \
            --force \
            --system-site-packages \
            --python /usr/bin/python3 \
            "waypaper==${LABWC_WAYPAPER_VERSION}"
  then
    desktop_waypaper_fail "pipx installation failed or timed out"
  fi

  desktop_transient_pipx_build_account_destroy \
    "$waypaper_build_account" \
    "$waypaper_build_home"
  desktop_waypaper_seal_runtime \
    "$waypaper_root" \
    "$waypaper_pipx_home" \
    "$waypaper_bin_dir" \
    "$waypaper_binary" \
    "$waypaper_system_binary"

  desktop_render_role_target_template \
    "etc/skel/.local/share/applications/waypaper.desktop.tmpl" \
    "$waypaper_launcher" \
    0644
  chown \
    "$waypaper_account_uid:$waypaper_account_gid" \
    "/target${waypaper_launcher_dir}" \
    "/target${waypaper_launcher}"

  desktop_log \
    "installed_waypaper user=${ACCOUNT_USERNAME} version=${LABWC_WAYPAPER_VERSION} runtime_root=${waypaper_root} binary=${waypaper_system_binary} launcher=${waypaper_launcher}"
}
