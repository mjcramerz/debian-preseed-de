#!/bin/sh
# Trixie repository transport. The preseed verifies this helper before it is
# sourced; this helper then verifies the complete publication before exposing
# one immutable installer tree to later phases.

set -u

SERVER_SOURCE_MAX_ARCHIVE_BYTES=${SERVER_SOURCE_MAX_ARCHIVE_BYTES:-524288000}
SERVER_SOURCE_MAX_MANIFEST_BYTES=${SERVER_SOURCE_MAX_MANIFEST_BYTES:-10485760}
SERVER_SOURCE_MAX_MEMBERS=${SERVER_SOURCE_MAX_MEMBERS:-12000}
SERVER_SOURCE_MAX_MEMBER_BYTES=${SERVER_SOURCE_MAX_MEMBER_BYTES:-16777216}
SERVER_SOURCE_MAX_EXPANDED_BYTES=${SERVER_SOURCE_MAX_EXPANDED_BYTES:-268435456}
SERVER_SOURCE_MAX_PATH_BYTES=${SERVER_SOURCE_MAX_PATH_BYTES:-240}
SERVER_SOURCE_MAX_PATH_DEPTH=${SERVER_SOURCE_MAX_PATH_DEPTH:-32}

server_source_fatal() {
  printf '[srv-source] fatal: %s\n' "$*" >&2
  return 1
}

server_source_valid_base() {
  base=${1:-}
  case "$base" in
    https://?*/*) ;;
    *) server_source_fatal 'server_source must be an HTTPS repository directory'; return 1 ;;
  esac
  rest=${base#https://}
  case "$rest" in
    *[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._~:/%+,-]*|*//*|*@*|*\?*|*#*)
      server_source_fatal 'server_source contains unsupported authority or query data'
      return 1
      ;;
  esac
  host=${base#https://}
  host=${host%%/*}
  case "$host" in
    github.com|raw.githubusercontent.com) ;;
    *) server_source_fatal 'server_source host is not approved'; return 1 ;;
  esac
  case "$host" in *:*) server_source_fatal 'server_source ports are not allowed'; return 1 ;; esac
  path=${base#https://*/}
  case "/$path" in */../*|*/./*|*//*|*/) server_source_fatal 'server_source path is not canonical'; return 1 ;; esac
}

server_source_valid_relative() {
  relative=${1:-}
  case "$relative" in
    ''|/*|*..*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_./@+\-]*)
      server_source_fatal 'unsafe repository-relative path'; return 1 ;;
  esac
  [ "${#relative}" -le "$SERVER_SOURCE_MAX_PATH_BYTES" ] || {
    server_source_fatal 'repository-relative path is too long'; return 1;
  }
  depth=$(printf '%s' "$relative" | awk -F/ '{print NF}')
  [ "$depth" -le "$SERVER_SOURCE_MAX_PATH_DEPTH" ] || {
    server_source_fatal 'repository-relative path is too deep'; return 1;
  }
}

server_source_fetch() {
  base=$1
  relative=$2
  destination=$3
  mode=${4:-0600}
  maximum=${5:-$SERVER_SOURCE_MAX_MANIFEST_BYTES}
  server_source_valid_base "$base" || return 1
  server_source_valid_relative "$relative" || return 1
  case "$mode" in 0600|0640|0644|0700|0750|0755) ;; *) server_source_fatal 'unsupported fetched-file mode'; return 1 ;; esac
  case "$maximum" in ''|*[!0-9]*) server_source_fatal 'invalid fetched-file size limit'; return 1 ;; esac
  parent=${destination%/*}
  [ -n "$parent" ] || parent=/
  install -d -m 0700 "$parent" || return 1
  temporary=$(mktemp "$parent/.source.XXXXXX") || return 1
  cleanup_source_fetch() { rm -f "$temporary"; }
  trap cleanup_source_fetch EXIT HUP INT TERM
  /usr/bin/wget --no-config -q --timeout=30 --tries=2 --max-redirect=0 \
    --max-filesize="$maximum" -O "$temporary" "${base%/}/$relative" || return 1
  [ -f "$temporary" ] && [ ! -L "$temporary" ] || {
    server_source_fatal "fetched source is not a regular file: $relative"; return 1;
  }
  bytes=$(wc -c <"$temporary") || return 1
  [ "$bytes" -le "$maximum" ] || { server_source_fatal 'fetched source exceeds its size limit'; return 1; }
  chmod "$mode" "$temporary" || return 1
  mv -f "$temporary" "$destination" || return 1
  trap - EXIT HUP INT TERM
}

server_source_validate_archive() {
  archive=$1
  work=$2
  [ -f "$archive" ] && [ ! -L "$archive" ] || { server_source_fatal 'payload archive is unavailable'; return 1; }
  archive_bytes=$(wc -c <"$archive") || return 1
  [ "$archive_bytes" -le "$SERVER_SOURCE_MAX_ARCHIVE_BYTES" ] || {
    server_source_fatal 'payload archive exceeds its compressed-byte limit'; return 1;
  }
  tar -tzf "$archive" >"$work/members" || { server_source_fatal 'cannot list payload archive'; return 1; }
  member_count=$(wc -l <"$work/members") || return 1
  [ "$member_count" -gt 0 ] && [ "$member_count" -le "$SERVER_SOURCE_MAX_MEMBERS" ] || {
    server_source_fatal 'payload member count is outside its limit'; return 1;
  }
  sort "$work/members" >"$work/members.sorted" || return 1
  sort -u "$work/members" >"$work/members.unique" || return 1
  cmp -s "$work/members.sorted" "$work/members.unique" || {
    server_source_fatal 'payload contains duplicate archive members'; return 1;
  }
  while IFS= read -r member || [ -n "$member" ]; do
    server_source_valid_relative "$member" || return 1
  done <"$work/members"
  tar -tvzf "$archive" >"$work/types" || { server_source_fatal 'cannot inspect payload archive members'; return 1; }
  awk -v max_member="$SERVER_SOURCE_MAX_MEMBER_BYTES" -v max_total="$SERVER_SOURCE_MAX_EXPANDED_BYTES" '
    BEGIN { total = 0 }
    { type = substr($1, 1, 1); if (type != "-") exit 2; size = $3 + 0;
      if (size < 0 || size > max_member) exit 3; total += size; if (total > max_total) exit 4 }
    END { if (NR == 0) exit 5 }
  ' "$work/types" || {
    server_source_fatal 'payload contains an unsafe member type or exceeds expansion limits'; return 1;
  }
}

server_source_validate_manifest() {
  manifest=$1
  members=$2
  expected=$3
  [ -f "$manifest" ] && [ ! -L "$manifest" ] || { server_source_fatal 'payload manifest is unavailable'; return 1; }
  bytes=$(wc -c <"$manifest") || return 1
  [ "$bytes" -le "$SERVER_SOURCE_MAX_MANIFEST_BYTES" ] || { server_source_fatal 'payload manifest is too large'; return 1; }
  awk -F '\t' '
    NR == 1 { if ($0 != "format=2") exit 1; next }
    NR == 2 { if ($1 !~ /^archive_sha256=[0-9a-f]{64}$/) exit 1; next }
    NR == 3 { if ($0 != "format_description=size<TAB>sha256<TAB>path") exit 1; next }
    NF != 3 || $1 !~ /^[0-9]+$/ || $2 !~ /^[0-9a-f]{64}$/ || $3 == "" { exit 1 }
    { print $1 "\t" $2 "\t" $3 }
  ' "$manifest" >"$expected" || { server_source_fatal 'malformed payload manifest'; return 1; }
  [ -s "$expected" ] || { server_source_fatal 'payload manifest is empty'; return 1; }
  manifest_count=$(wc -l <"$expected") || return 1
  [ "$manifest_count" -le "$SERVER_SOURCE_MAX_MEMBERS" ] || { server_source_fatal 'manifest member count is too large'; return 1; }
  while IFS="$(printf '\t')" read -r size digest member || [ -n "$member" ]; do
    [ -n "$size" ] && [ -n "$digest" ] && [ -n "$member" ] || { server_source_fatal 'payload manifest contains an empty field'; return 1; }
    server_source_valid_relative "$member" || return 1
  done <"$expected"
  cut -f3 "$expected" | sort >"$expected.members" || return 1
  cmp -s "$members" "$expected.members" || { server_source_fatal 'payload archive and manifest member sets differ'; return 1; }
}

server_source_prepare_payload() {
  base=$1
  stage=${2:-/tmp/server-install}
  server_source_valid_base "$base" || return 1
  [ "$stage" = /tmp/server-install ] || { server_source_fatal 'payload stage must be /tmp/server-install'; return 1; }
  [ ! -L "$stage" ] || { server_source_fatal 'payload stage must not be a symlink'; return 1; }
  work=$(mktemp -d /tmp/server-payload.XXXXXX) || return 1
  cleanup_payload() { rm -rf "$work"; }
  trap cleanup_payload EXIT HUP INT TERM
  server_source_fetch "$base" payload.manifest "$work/payload.manifest" 0600 "$SERVER_SOURCE_MAX_MANIFEST_BYTES" || return 1
  server_source_fetch "$base" payload.tar.gz "$work/payload.tar.gz" 0600 "$SERVER_SOURCE_MAX_ARCHIVE_BYTES" || return 1
  expected_archive=$(awk -F= 'NR == 2 { print $2 }' "$work/payload.manifest")
  actual_archive=$(/usr/bin/sha256sum "$work/payload.tar.gz" | awk '{print $1}')
  [ "$expected_archive" = "$actual_archive" ] || { server_source_fatal 'payload archive digest mismatch'; return 1; }
  server_source_validate_archive "$work/payload.tar.gz" "$work" || return 1
  server_source_validate_manifest "$work/payload.manifest" "$work/members.sorted" "$work/expected" || return 1
  tree="$work/tree"
  mkdir "$tree" || return 1
  tar -xzf "$work/payload.tar.gz" --no-same-owner --no-same-permissions --no-acls --no-xattrs -C "$tree" || {
    server_source_fatal 'cannot extract payload archive'; return 1;
  }
  while IFS="$(printf '\t')" read -r size digest member || [ -n "$member" ]; do
    file="$tree/$member"
    [ -f "$file" ] && [ ! -L "$file" ] || { server_source_fatal "payload member is not a regular file: $member"; return 1; }
    actual_size=$(wc -c <"$file") || return 1
    actual_digest=$(/usr/bin/sha256sum "$file" | awk '{print $1}')
    [ "$actual_size" = "$size" ] && [ "$actual_digest" = "$digest" ] || {
      server_source_fatal "payload identity differs from manifest: $member"; return 1;
    }
  done <"$work/expected"
  [ -f "$tree/repo.env" ] && [ -f "$tree/scripts/preseed/bootstrap.sh" ] && [ -f "$tree/scripts/common/source.sh" ] && [ -d "$tree/forky" ] || {
    server_source_fatal 'payload lacks required installer tree'; return 1;
  }
  if [ -e "$stage" ]; then
    [ -d "$stage" ] || { server_source_fatal 'existing payload stage is not a directory'; return 1; }
    recovery="$stage.recovery.$$"
    mv "$stage" "$recovery" || { server_source_fatal 'cannot retain the previous payload stage'; return 1; }
    if mv "$tree" "$stage"; then
      rm -rf "$recovery"
    else
      mv "$recovery" "$stage" || server_source_fatal 'payload replacement outcome is unknown'
      return 1
    fi
  else
    mv "$tree" "$stage" || return 1
  fi
  chmod 0700 "$stage"
  trap - EXIT HUP INT TERM
  rm -rf "$work"
}
