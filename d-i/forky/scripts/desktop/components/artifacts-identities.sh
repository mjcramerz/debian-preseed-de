#!/bin/sh
# Sourced installer module; edit this file directly.

desktop_extract_role_wallpaper_archive() {
  archive_host="${TMP_ENV_DIR}/desktop-wallpapers.$$.tar.gz"
  archive_target=/tmp/installer-desktop-wallpapers.tar.gz
  archive_target_host=$(target_asset_host_path "$archive_target")
  archive_max_bytes=${LABWC_WALLPAPERS_MAXIMUM_BYTES:?LABWC_WALLPAPERS_MAXIMUM_BYTES must be set}

  rm -f -- "$archive_host" "$archive_target_host"
  if ! desktop_download_release_archive \
      'desktop wallpapers' \
      "$LABWC_WALLPAPERS_TAG" \
      "$LABWC_WALLPAPERS_URL" \
      "$LABWC_WALLPAPERS_SHA256" \
      wallpapers.tar.gz \
      "$archive_host" \
      "$archive_max_bytes"; then
    rm -f -- "$archive_host" "$archive_target_host"
    installer_fatal "failed to fetch desktop wallpaper release archive: ${LABWC_WALLPAPERS_URL}"
  fi
  [ -f "$archive_host" ] && [ ! -L "$archive_host" ] ||
    installer_fatal "desktop wallpaper release archive is not a regular file: ${LABWC_WALLPAPERS_URL}"

  archive_bytes=$(wc -c <"$archive_host" 2>/dev/null || true)
  archive_bytes=${archive_bytes##* }
  case "$archive_bytes" in
    ''|*[!0123456789]*|0)
      rm -f -- "$archive_host"
      installer_fatal "desktop wallpaper release archive size is invalid: ${LABWC_WALLPAPERS_URL}"
      ;;
  esac
  if [ "$archive_bytes" -gt "$archive_max_bytes" ]; then
    rm -f -- "$archive_host"
    installer_fatal \
      "desktop wallpaper release archive exceeds ${archive_max_bytes} bytes: ${LABWC_WALLPAPERS_URL}"
  fi

  install -m 0600 "$archive_host" "$archive_target_host"
  rm -f -- "$archive_host"

  # shellcheck disable=SC2016
  if ! run_in_target "extract managed desktop wallpaper archive" /bin/sh -eu -c '
archive=$1
destination=$2
/usr/bin/install -d -m 0755 -- "$destination"
/usr/bin/tar \
  --extract \
  --gzip \
  --file "$archive" \
  --directory "$destination" \
  --no-same-owner \
  --no-same-permissions
/usr/bin/find "$destination" -maxdepth 1 -type f -exec /usr/bin/chmod 0644 {} +
/usr/bin/rm -f -- "$archive"
' sh "$archive_target" /usr/share/backgrounds/desktop
  then
    rm -f -- "$archive_target_host"
    installer_fatal "failed to extract the verified desktop wallpaper release archive"
  fi

  [ ! -e "$archive_target_host" ] && [ ! -L "$archive_target_host" ] ||
    installer_fatal "desktop wallpaper archive remained in the target after extraction"
  desktop_log \
    "extracted_wallpaper_archive source=${LABWC_WALLPAPERS_URL} tag=${LABWC_WALLPAPERS_TAG} target=/usr/share/backgrounds/desktop archive_bytes=${archive_bytes}"
}

desktop_target_tree_size_kib() {
  size_label=$1
  target_path=$2

  case "$target_path" in
    /*) ;;
    *)
      installer_fatal "desktop target size path must be absolute: ${target_path:-unset}"
      ;;
  esac
  case "$target_path" in
    /|*..*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/-]*)
      installer_fatal "desktop target size path is unsafe: ${target_path}"
      ;;
  esac

  target_size_kib=$(
    capture_in_target \
      "$size_label" \
      /usr/bin/du -sk -- "$target_path" |
      awk 'NR == 1 { print $1; exit }'
  )
  case "$target_size_kib" in
    ''|*[!0123456789]*)
      installer_fatal \
        "desktop target size measurement returned an invalid value for ${target_path}: ${target_size_kib:-unset}"
      ;;
  esac

  printf '%s\n' "$target_size_kib"
}

desktop_double_quote_escape() {
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

desktop_toml_escape() {
  desktop_double_quote_escape "$1"
}

desktop_xml_attribute_escape() {
  printf '%s' "$1" | sed 's/&/\&amp;/g; s/"/\&quot;/g; s/</\&lt;/g; s/>/\&gt;/g'
}

desktop_primary_account_ids() {
  wanted_user=${1:-${ACCOUNT_USERNAME:-}}

  [ -n "$wanted_user" ] || return 1
  awk -F: -v wanted_user="$wanted_user" '$1 == wanted_user { print $3 ":" $4; exit }' /target/etc/passwd 2>/dev/null
}

desktop_transient_pipx_build_account_prepare() {
  build_account=$1
  build_home=$2
  shift 2

  case "$build_account" in
    ''|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-]*)
      installer_fatal "transient pipx build account contains unsupported characters"
      ;;
  esac
  case "$build_home" in
    /|*..*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/-]*)
      installer_fatal "transient pipx build home contains unsupported syntax: ${build_home}"
      ;;
  esac
  [ "$#" -ge 1 ] ||
    installer_fatal "transient pipx build account requires managed writable paths"
  for build_path in "$@"; do
    case "$build_path" in
      /|*..*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/-]*)
        installer_fatal "transient pipx managed path contains unsupported syntax: ${build_path}"
        ;;
    esac
  done

  # The installer runs third-party pipx package hooks under this locked,
  # short-lived identity, with a private HOME rather than the eventual desktop
  # account's home. The installer grants managed write access only to the
  # caller-created runtime paths.
  # shellcheck disable=SC2016 # The quoted program executes inside the target.
  run_in_target "prepare transient pipx build account ${build_account}" /bin/sh -eu -c '
account=$1
build_home=$2
shift 2

case "$account" in
  ""|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-]*)
    printf "%s\n" "transient pipx build account contains unsupported characters" >&2
    exit 1
    ;;
esac
case "$build_home" in
  /|*..*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/-]*)
    printf "%s\n" "transient pipx build home contains unsupported syntax" >&2
    exit 1
    ;;
esac
[ "$#" -ge 1 ] || {
  printf "%s\n" "transient pipx build account requires managed writable paths" >&2
  exit 1
}
for build_path; do
  case "$build_path" in
    /|*..*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/-]*)
      printf "%s\n" "transient pipx managed path contains unsupported syntax" >&2
      exit 1
      ;;
  esac
  [ -d "$build_path" ] && [ ! -L "$build_path" ] || {
    printf "%s\n" "transient pipx managed path is missing or symbolic" >&2
    exit 1
  }
done
[ -d "$build_home" ] && [ ! -L "$build_home" ] || {
  printf "%s\n" "transient pipx build home is missing or symbolic" >&2
  exit 1
}
[ -x /usr/bin/awk ] &&
  [ -x /usr/sbin/useradd ] &&
  [ -x /usr/bin/chown ] &&
  [ -x /usr/bin/chmod ] &&
  [ -x /usr/bin/install ] ||
  {
    printf "%s\n" "transient pipx build account prerequisites are unavailable" >&2
    exit 1
  }

if /usr/bin/awk -F: -v account="$account" '"'"'$1 == account { found = 1; exit } END { exit !found }'"'"' /etc/passwd ||
  /usr/bin/awk -F: -v account="$account" '"'"'$1 == account { found = 1; exit } END { exit !found }'"'"' /etc/group
then
  printf "%s\n" "transient pipx build account or group already exists" >&2
  exit 1
fi

/usr/sbin/useradd \
  --system \
  --no-create-home \
  --shell /usr/sbin/nologin \
  --user-group \
  -- "$account"

for build_path; do
  /usr/bin/chown "$account:$account" "$build_path"
  /usr/bin/chmod 0755 "$build_path"
done
/usr/bin/chown "$account:$account" "$build_home"
/usr/bin/chmod 0700 "$build_home"
/usr/bin/install -d -o "$account" -g "$account" -m 0700 "$build_home/tmp"
' sh "$build_account" "$build_home" "$@"
}

desktop_transient_pipx_build_account_destroy() {
  build_account=$1
  build_home=$2

  case "$build_account" in
    ''|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-]*)
      installer_fatal "transient pipx build account contains unsupported characters"
      ;;
  esac
  case "$build_home" in
    /|*..*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/-]*)
      installer_fatal "transient pipx build home contains unsupported syntax: ${build_home}"
      ;;
  esac

  # Do not use a UID-wide kill here: in-target is chroot-based and may share
  # the installer process namespace. A non-forced userdel fails closed if the
  # transient builder cannot be removed, before root seals the runtime.
  # shellcheck disable=SC2016 # The quoted program executes inside the target.
  run_in_target "destroy transient pipx build account ${build_account}" /bin/sh -eu -c '
account=$1
build_home=$2

case "$account" in
  ""|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-]*)
    printf "%s\n" "transient pipx build account contains unsupported characters" >&2
    exit 1
    ;;
esac
case "$build_home" in
  /|*..*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/-]*)
    printf "%s\n" "transient pipx build home contains unsupported syntax" >&2
    exit 1
    ;;
esac
[ -d "$build_home" ] && [ ! -L "$build_home" ] || {
  printf "%s\n" "transient pipx build home is missing or symbolic" >&2
  exit 1
}
[ -x /usr/bin/awk ] &&
  [ -x /usr/bin/find ] &&
  [ -x /usr/bin/rmdir ] &&
  [ -x /usr/sbin/userdel ] &&
  [ -x /usr/sbin/groupdel ] ||
  {
    printf "%s\n" "transient pipx build account cleanup prerequisites are unavailable" >&2
    exit 1
  }
/usr/sbin/userdel -- "$account"
if /usr/bin/awk -F: -v account="$account" '"'"'$1 == account { found = 1; exit } END { exit !found }'"'"' /etc/group
then
  /usr/sbin/groupdel -- "$account"
fi
if /usr/bin/awk -F: -v account="$account" '"'"'$1 == account { found = 1; exit } END { exit !found }'"'"' /etc/passwd ||
  /usr/bin/awk -F: -v account="$account" '"'"'$1 == account { found = 1; exit } END { exit !found }'"'"' /etc/group
then
  printf "%s\n" "transient pipx build account cleanup left an identity behind" >&2
  exit 1
fi
/usr/bin/find "$build_home" -xdev -depth -mindepth 1 -delete
/usr/bin/rmdir -- "$build_home"
' sh "$build_account" "$build_home"
}
