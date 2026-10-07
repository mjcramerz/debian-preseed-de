#!/bin/sh
# Sourced installer module; edit this file directly.

desktop_extract_role_wallpaper_archive() {
  archive_relpath=${LABWC_WALLPAPER_ARCHIVE#hooks/target/}
  archive_source=$(installer_repo_join_var DIR_HOOKS_TARGET "$archive_relpath")
  archive_host="${TMP_ENV_DIR}/desktop-wallpapers.$$.tar.gz"
  archive_target=/tmp/installer-desktop-wallpapers.tar.gz
  archive_target_host=$(target_asset_host_path "$archive_target")
  archive_max_bytes=33554432

  rm -f -- "$archive_host" "$archive_target_host"
  if ! fetch_hook "$archive_source" "$archive_host"; then
    rm -f -- "$archive_host" "$archive_target_host"
    installer_fatal "failed to fetch desktop wallpaper archive: ${archive_source}"
  fi
  [ -f "$archive_host" ] && [ ! -L "$archive_host" ] ||
    installer_fatal "desktop wallpaper archive is not a regular file: ${archive_source}"

  archive_bytes=$(wc -c <"$archive_host" 2>/dev/null || true)
  archive_bytes=${archive_bytes##* }
  case "$archive_bytes" in
    ''|*[!0123456789]*|0)
      rm -f -- "$archive_host"
      installer_fatal "desktop wallpaper archive size is invalid: ${archive_source}"
      ;;
  esac
  if [ "$archive_bytes" -gt "$archive_max_bytes" ]; then
    rm -f -- "$archive_host"
    installer_fatal \
      "desktop wallpaper archive exceeds ${archive_max_bytes} bytes: ${archive_source}"
  fi

  install -m 0600 "$archive_host" "$archive_target_host"
  rm -f -- "$archive_host"

  # shellcheck disable=SC2016
  if ! run_in_target "extract managed desktop wallpaper archive" /bin/sh -eu -c '
archive=$1
destination=$2
member_limit=$3
extracted_byte_limit=$4
protected_default=$5
member_list=/tmp/installer-desktop-wallpapers.members.$$
verbose_list=/tmp/installer-desktop-wallpapers.verbose.$$
extract_dir=/tmp/installer-desktop-wallpapers.extract.$$

cleanup() {
  rm -rf -- "$archive" "$member_list" "$verbose_list" "$extract_dir"
}
trap cleanup EXIT HUP INT TERM

fatal() {
  printf "fatal: desktop wallpaper archive: %s\n" "$*" >&2
  exit 1
}

/usr/bin/tar -tzf "$archive" >"$member_list" ||
  fatal "archive is not readable gzip-compressed tar data"
member_count=$(/usr/bin/wc -l <"$member_list" | /usr/bin/tr -d " ")
case "$member_count" in
  ""|*[!0123456789]*|0) fatal "member count is invalid" ;;
esac
[ "$member_count" -le "$member_limit" ] ||
  fatal "archive contains too many members: $member_count"

duplicate_member=$(
  LC_ALL=C /usr/bin/sort "$member_list" |
    /usr/bin/uniq -d |
    /usr/bin/sed -n "1p"
)
[ -z "$duplicate_member" ] ||
  fatal "archive contains a duplicate member: $duplicate_member"

while IFS= read -r member_name || [ -n "$member_name" ]; do
  case "$member_name" in
    ""|/*|*/*|"."|".."|.*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-]*)
      fatal "archive contains an unsafe member name: ${member_name:-empty}"
      ;;
  esac
  case "$member_name" in
    *.png|*.jpg|*.jpeg) ;;
    *) fatal "archive member is not a supported PNG or JPEG: $member_name" ;;
  esac
  [ "$member_name" != "$protected_default" ] ||
    fatal "archive must not replace the managed fallback wallpaper"
done <"$member_list"

/usr/bin/tar --numeric-owner -tvzf "$archive" >"$verbose_list" ||
  fatal "archive member metadata could not be inspected"
metadata_count=0
extracted_bytes=0
while IFS= read -r member_metadata || [ -n "$member_metadata" ]; do
  set -- $member_metadata
  [ "$#" -ge 6 ] ||
    fatal "archive member metadata is incomplete"
  member_mode=$1
  member_size=$3
  case "$member_mode" in
    -*) ;;
    *) fatal "archive contains a non-regular member" ;;
  esac
  case "$member_mode" in
    *x*) fatal "archive contains an executable member" ;;
  esac
  case "$member_size" in
    ""|*[!0123456789]*) fatal "archive member size is invalid" ;;
  esac
  extracted_bytes=$((extracted_bytes + member_size))
  [ "$extracted_bytes" -le "$extracted_byte_limit" ] ||
    fatal "archive expands beyond ${extracted_byte_limit} bytes"
  metadata_count=$((metadata_count + 1))
done <"$verbose_list"
[ "$metadata_count" -eq "$member_count" ] ||
  fatal "archive member metadata count does not match the member list"

/usr/bin/install -d -m 0700 "$extract_dir"
/usr/bin/tar \
  --extract \
  --gzip \
  --file "$archive" \
  --directory "$extract_dir" \
  --no-same-owner \
  --no-same-permissions ||
  fatal "archive extraction failed"

/usr/bin/install -d -m 0755 "$destination"
while IFS= read -r member_name || [ -n "$member_name" ]; do
  extracted_path="${extract_dir}/${member_name}"
  [ -f "$extracted_path" ] && [ ! -L "$extracted_path" ] ||
    fatal "extracted member is not a regular file: $member_name"
  member_mime=$(/usr/bin/file --brief --mime-type -- "$extracted_path" 2>/dev/null || true)
  case "${member_name}:${member_mime}" in
    *.png:image/png|*.jpg:image/jpeg|*.jpeg:image/jpeg) ;;
    *) fatal "extracted member content does not match its image extension: $member_name" ;;
  esac
  /usr/bin/install -m 0644 "$extracted_path" "${destination}/${member_name}"
done <"$member_list"

printf "desktop_wallpaper_archive members=%s extracted_bytes=%s destination=%s\n" \
  "$member_count" \
  "$extracted_bytes" \
  "$destination"
' sh \
    "$archive_target" \
    /usr/share/backgrounds/desktop \
    128 \
    134217728 \
    "${LABWC_WALLPAPER_PATH##*/}"
  then
    rm -f -- "$archive_target_host"
    installer_fatal "failed to validate and extract the desktop wallpaper archive"
  fi

  [ ! -e "$archive_target_host" ] ||
    installer_fatal "desktop wallpaper archive remained in the target after extraction"
  desktop_log \
    "extracted_wallpaper_archive source=${archive_source} target=/usr/share/backgrounds/desktop archive_bytes=${archive_bytes}"
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

