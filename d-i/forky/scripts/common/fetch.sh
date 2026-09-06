#!/bin/sh

fetch_resolve_seed_base() {
  if [ -n "${SEED_BASE:-}" ]; then
    FETCH_SEED_BASE=$SEED_BASE
    return 0
  fi

  [ -n "${FETCH_SEED_BASE:-}" ] || FETCH_SEED_BASE=$(installer_current_seed_base)
}

fetch_seed_file() {
  src=$1
  dest=$2
  mode=$3
  label=$4
  fetch_resolve_seed_base
  if ! installer_fetch_seed_path "$FETCH_SEED_BASE" "$src" "$dest" "$mode"; then
    installer_error "failed to fetch ${label}: ${src}"
    return 1
  fi
}

fetch_env_file() {
  src=$1
  dest=$2
  fetch_resolve_seed_base
  installer_fetch_file "$FETCH_SEED_BASE" "$src" "$dest" 0600
}

fetch_hook_file() {
  src=$1
  dest=$2
  fetch_resolve_seed_base
  installer_fetch_file "$FETCH_SEED_BASE" "$src" "$dest" 0755
}

fetch_ssh_asset() {
  src=$1
  dest=$2
  max_bytes=${3:-}
  ssh_repo_dir=ssh

  case "$src" in
    "${ssh_repo_dir}"/*) ;;
    *)
      installer_fatal "SSH asset path must stay under ${ssh_repo_dir}: ${src}"
      ;;
  esac
  case "$src" in
    *..*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/-]*)
      installer_fatal "SSH asset path contains unsupported characters: ${src}"
      ;;
  esac
  case "$max_bytes" in
    ''|*[!0-9]*|0)
      installer_fatal "invalid SSH asset byte limit for ${src}: ${max_bytes:-unset}"
      ;;
  esac
  if [ "$max_bytes" -gt 1048576 ]; then
    installer_fatal "SSH asset byte limit is too large for ${src}: ${max_bytes}"
  fi

  fetch_resolve_seed_base
  if ! installer_fetch_seed_path "$FETCH_SEED_BASE" "$src" "$dest" 0600; then
    installer_fatal "failed to fetch $src"
  fi

  bytes=$(wc -c <"$dest" 2>/dev/null) || bytes=
  bytes=${bytes##* }
  case "$bytes" in
    ''|*[!0-9]*)
      installer_fatal "unable to measure SSH asset size: $src"
      ;;
  esac
  if [ "$bytes" -gt "$max_bytes" ]; then
    installer_fatal "SSH asset exceeds ${max_bytes} bytes: $src"
  fi

  chmod 0600 "$dest"
}
