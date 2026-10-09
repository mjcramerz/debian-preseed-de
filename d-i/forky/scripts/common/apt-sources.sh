#!/bin/sh
# APT source publication shared by early bootstrap and apt-setup. No APT update
# is safe until this has run; a Pre-Invoke hook would be too late for source parsing.
installer_apt_safe_path() (
  set -eu
  p=$1
  case "$p" in /*) ;; *) exit 1 ;; esac
  case "/${p#/}/" in *'/../'*|*'/./'*|*'//'*) exit 1 ;; esac
  while [ "$p" != / ]; do
    [ ! -L "$p" ] || exit 1
    if [ -e "$p" ]; then
      [ "$(installer_metadata_value "$p" uid)" = "$(id -u)" ] || exit 1
      mode=$(installer_metadata_value "$p" mode) || exit 1
      [ "$((0$mode & 0022))" -eq 0 ] || { [ -d "$p" ] && [ "$((0$mode & 01000))" -ne 0 ]; } || exit 1
    fi
    p=${p%/*}; [ -n "$p" ] || p=/
  done
)

installer_apt_strip_cdrom() (
  set -eu
  umask 077
  target=$1
  installer_apt_safe_path "$target/etc/apt/sources.list.d" || exit 1
  for src in "$target/etc/apt/sources.list" "$target/etc/apt/sources.list.d/"*; do
    [ -e "$src" ] || [ -L "$src" ] || continue
    case "$src" in *.list|*.list.*|*.sources|*.sources.*) ;; *) continue ;; esac
    installer_apt_safe_path "$src" || exit 1
    [ -f "$src" ] && [ "$(installer_metadata_value "$src" links)" = 1 ] || exit 1
    if grep -Fq 'cdrom:' "$src"; then
      :
    else
      source_status=$?
      [ "$source_status" -eq 1 ] && continue
      exit 1
    fi
    tmp=$(mktemp "${src%/*}/.installer-source.XXXXXX") || exit 1
    trap 'rm -f "$tmp"' 0
    case "$src" in
      *.sources|*.sources.*)
        awk 'BEGIN {RS=""; ORS="\n\n"} index($0,"cdrom:")==0 {print}' "$src" >"$tmp" || exit 1 ;;
      *) awk 'index($0,"cdrom:")==0 {print}' "$src" >"$tmp" || exit 1 ;;
    esac
    source_mode=$(installer_metadata_value "$src" mode) || exit 1
    chmod "$source_mode" "$tmp" || exit 1
    mv -fT -- "$tmp" "$src" || exit 1
  done
)

installer_apt_bootstrap_source() (
  set -eu
  umask 077
  target=$1; protocol=$2; host=$3; directory=$4; suite=$5
  case "$protocol" in http|https) ;; *) exit 1 ;; esac
  case "$host" in ''|*[!A-Za-z0-9.:-]*) exit 1 ;; esac
  case "$directory" in /*) ;; *) exit 1 ;; esac
  case "$directory" in *[!A-Za-z0-9/_-]*|*..*|*//*) exit 1 ;; esac
  case "$suite" in ''|*[!A-Za-z0-9_-]*) exit 1 ;; esac
  installer_apt_safe_path "$target/etc/apt/sources.list" || exit 1
  installer_apt_safe_path "$target/etc/apt/apt.conf.d" || exit 1
  [ -s "$target/usr/share/keyrings/debian-archive-keyring.gpg" ] || exit 1
  mkdir -p "$target/etc/apt/sources.list.d" "$target/etc/apt/apt.conf.d" || exit 1
  installer_apt_strip_cdrom "$target" || exit 1
  tmp=$(mktemp "$target/etc/apt/.installer-bootstrap.XXXXXX") || exit 1
  trap 'rm -f "$tmp"' 0
  printf 'deb [signed-by=/usr/share/keyrings/debian-archive-keyring.gpg] %s://%s%s %s main contrib non-free non-free-firmware\n' \
    "$protocol" "$host" "$directory" "$suite" >"$tmp" || exit 1
  if [ -f "$target/etc/apt/sources.list" ]; then
    if cmp -s "$tmp" "$target/etc/apt/sources.list"; then
      source_mode=$(installer_metadata_value "$target/etc/apt/sources.list" mode) || exit 1
      [ "$source_mode" != 644 ] || exit 0
    else
      source_status=$?
      [ "$source_status" -eq 1 ] || exit 1
    fi
  fi
  chmod 0644 "$tmp" || exit 1
  mv -fT -- "$tmp" "$target/etc/apt/sources.list" || exit 1
  # Bootstrap retries/timeouts are command options, never permanent target policy.
)
