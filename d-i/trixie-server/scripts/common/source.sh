#!/bin/sh
# Trixie repository transport. The preseed fetches this helper first; this
# helper then fetches the complete publication and extracts one immutable
# installer tree for all later phases.

server_source_fatal() {
  printf '[srv-source] fatal: %s\n' "$*" >&2
  return 1
}

server_source_valid_base() {
  case "${1:-}" in
    https://?*/*) ;;
    *) server_source_fatal 'server_source must be an HTTPS repository directory'; return 1 ;;
  esac
  case "$1" in
    *[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._~:/?@%+,-]*)
      server_source_fatal 'server_source contains unsupported characters'; return 1 ;;
  esac
}

server_source_valid_relative() {
  case "${1:-}" in
    ''|/*|*..*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_./@+-]*)
      server_source_fatal 'unsafe repository-relative path'; return 1 ;;
  esac
}

server_source_fetch() {
  base=$1
  relative=$2
  destination=$3
  mode=${4:-0600}
  server_source_valid_base "$base" || return 1
  server_source_valid_relative "$relative" || return 1
  case "$mode" in
    0600|0640|0644|0700|0750|0755) ;;
    *) server_source_fatal 'unsupported fetched-file mode'; return 1 ;;
  esac
  parent=${destination%/*}
  [ -n "$parent" ] || parent=/
  install -d -m 0700 "$parent" || return 1
  temporary=$(mktemp "$parent/.source.XXXXXX") || return 1
  trap 'rm -f "$temporary"' EXIT HUP INT TERM
  /usr/bin/wget --no-config -q --timeout=30 --tries=3 --max-redirect=3 \
    -O "$temporary" "${base%/}/$relative" || return 1
  [ -f "$temporary" ] && [ ! -L "$temporary" ] || {
    server_source_fatal "fetched source is not a regular file: $relative"
    return 1
  }
  chmod "$mode" "$temporary" || return 1
  mv -f "$temporary" "$destination" || return 1
  trap - EXIT HUP INT TERM
}

server_source_validate_archive() {
  archive=$1
  work=$2
  tar -tzf "$archive" >"$work/members" || {
    server_source_fatal 'cannot list payload archive'; return 1;
  }
  tar -tvzf "$archive" >"$work/types" || {
    server_source_fatal 'cannot inspect payload archive members'; return 1;
  }
  if grep -q '^[^-]' "$work/types"; then
    server_source_fatal 'payload contains a non-regular archive member'
    return 1
  fi
  while IFS= read -r member || [ -n "$member" ]; do
    server_source_valid_relative "$member" || return 1
  done <"$work/members"
  sort "$work/members" >"$work/members.sorted" || return 1
  sort -u "$work/members" >"$work/members.unique" || return 1
  cmp -s "$work/members.sorted" "$work/members.unique" || {
    server_source_fatal 'payload contains duplicate archive members'; return 1;
  }
}

server_source_validate_manifest() {
  manifest=$1
  members=$2
  expected=$3
  awk -F '\t' '
    NR == 1 { if ($0 != "format=1") exit 1; next }
    NR == 2 { if ($0 != "format_description=size<TAB>path") exit 1; next }
    NF != 2 || $1 !~ /^[0-9]+$/ || $2 == "" { exit 1 }
    { print $1 "\t" $2 }
  ' "$manifest" >"$expected" || {
    server_source_fatal 'malformed payload manifest'; return 1;
  }
  [ -s "$expected" ] || {
    server_source_fatal 'payload manifest is empty'; return 1;
  }
  while IFS="$(printf '\t')" read -r size member || [ -n "$member" ]; do
    [ -n "$size" ] && [ -n "$member" ] || {
      server_source_fatal 'payload manifest contains an empty field'; return 1;
    }
    server_source_valid_relative "$member" || return 1
  done <"$expected"
  cut -f2 "$expected" | sort >"$expected.members" || return 1
  cmp -s "$members" "$expected.members" || {
    server_source_fatal 'payload archive and manifest member sets differ'; return 1;
  }
}

server_source_prepare_payload() {
  base=$1
  stage=${2:-/tmp/server-install}
  server_source_valid_base "$base" || return 1
  case "$stage" in
    /tmp/server-install) ;;
    *) server_source_fatal 'payload stage must be /tmp/server-install'; return 1 ;;
  esac
  [ ! -L "$stage" ] || {
    server_source_fatal 'payload stage must not be a symlink'; return 1;
  }
  work=$(mktemp -d /tmp/server-payload.XXXXXX) || return 1
  trap 'rm -rf "$work"' EXIT HUP INT TERM
  server_source_fetch "$base" preseed.cfg "$work/preseed.cfg" 0600 || return 1
  server_source_fetch "$base" scripts/common/source.sh "$work/source.sh" 0600 || return 1
  server_source_fetch "$base" payload.manifest "$work/payload.manifest" 0600 || return 1
  server_source_fetch "$base" payload.tar.gz "$work/payload.tar.gz" 0600 || return 1
  server_source_validate_archive "$work/payload.tar.gz" "$work" || return 1
  server_source_validate_manifest "$work/payload.manifest" "$work/members.sorted" \
    "$work/expected" || return 1
  tree="$work/tree"
  mkdir "$tree" || return 1
  tar -xzf "$work/payload.tar.gz" --no-same-owner --no-same-permissions -C "$tree" || {
    server_source_fatal 'cannot extract payload archive'; return 1;
  }
  while IFS="$(printf '\t')" read -r size member || [ -n "$member" ]; do
    file="$tree/$member"
    [ -f "$file" ] && [ ! -L "$file" ] || {
      server_source_fatal "payload member is not a regular file: $member"
      return 1
    }
    actual=$(wc -c <"$file") || return 1
    [ "$actual" = "$size" ] || {
      server_source_fatal "payload size differs from manifest: $member"
      return 1
    }
  done <"$work/expected"
  [ -f "$tree/repo.env" ] && [ -f "$tree/scripts/preseed/bootstrap.sh" ] &&
    [ -f "$tree/scripts/common/source.sh" ] && [ -d "$tree/forky" ] || {
      server_source_fatal 'payload lacks required installer tree'; return 1;
    }
  if [ -e "$stage" ]; then
    [ -d "$stage" ] || { server_source_fatal 'existing payload stage is not a directory'; return 1; }
    rm -rf "$stage" || return 1
  fi
  mv "$tree" "$stage" || return 1
  chmod 0700 "$stage"
  trap - EXIT HUP INT TERM
  rm -rf "$work"
}
