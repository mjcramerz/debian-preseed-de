#!/bin/sh
# Shared validation helpers. This file is sourced by installer-stage scripts.

server_fatal() {
  printf '[srv] fatal: %s\n' "$*" >&2
  return 1
}

server_info() {
  printf '[srv] %s\n' "$*" >&2
}

server_valid_identifier() {
  case "${1:-}" in
    ''|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-]*) return 1 ;;
  esac
}

server_valid_username() {
  value=${1:-}
  [ "${#value}" -ge 1 ] && [ "${#value}" -le 32 ] || return 1
  case "$value" in [a-z_]*) ;; *) return 1 ;; esac
  case "$value" in *[!a-z0-9_-]*) return 1 ;; *) return 0 ;; esac
}

server_valid_port() {
  case "${1:-}" in
    ''|*[!0-9]*) return 1 ;;
  esac
  [ "$1" -ge 1 ] 2>/dev/null && [ "$1" -le 65535 ] 2>/dev/null
}

server_valid_https_url() {
  value=${1:-}
  case "$value" in https://?*/*) ;; *) return 1 ;; esac
  rest=${value#https://}
  case "$rest" in
    *[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._~:/%+,-]*|*//*|*@*|*\?*|*#*) return 1 ;;
  esac
  host=${rest%%/*}
  case "$host" in ''|*:*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.-]*) return 1 ;; esac
  case "$host" in *..*|.*|*.) return 1 ;; esac
  return 0
}

# Validate an HTTPS artifact URL, including the query parameters used by
# signed release-object redirects. Redirect destinations are still restricted
# to the checked-in host allowlist by the caller.
server_valid_artifact_url() {
  value=${1:-}
  allowed=${2:-}
  case "$value" in https://?*/*) ;; *) return 1 ;; esac
  rest=${value#https://}
  case "$rest" in
    *[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._~:/%+?,=\&-]*|*//*|*@*|*#*) return 1 ;;
  esac
  host=${rest%%/*}
  case "$host" in ''|*:*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.-]*) return 1 ;; esac
  case "$host" in *..*|.*|*.) return 1 ;; esac
  [ -n "$allowed" ] || return 1
  for item in $allowed; do [ "$host" = "$item" ] && return 0; done
  return 1
}

# Download one verified artifact while validating every HTTPS redirect. The
# caller supplies the checked-in host allowlist; relative, cross-host, HTTP,
# looped, and excessive redirects fail closed. The destination is published
# only after the final response has been completely written.
server_download_artifact() (
  url=$1
  destination=$2
  maximum=$3
  allowed_hosts=$4
  server_valid_artifact_url "$url" "$allowed_hosts" || return 1
  server_safe_path "$destination" || return 1
  parent=${destination%/*}
  [ -n "$parent" ] || parent=/
  install -d -m 0700 "$parent" || return 1
  workspace=$(mktemp -d "$parent/.artifact.XXXXXX") || return 1
  body="$workspace/body"
  headers="$workspace/headers"
  cleanup_artifact_download() { rm -rf -- "$workspace"; }
  trap cleanup_artifact_download EXIT HUP INT TERM
  hop=0
  while [ "$hop" -le 4 ]; do
    rm -f "$body" "$headers"
    /usr/bin/curl --silent --show-error --proto '=https' --proto-redir '=https' \
      --max-redirs 0 --connect-timeout 15 --max-time 300 --max-filesize "$maximum" \
      --dump-header "$headers" --output "$body" "$url" || return 1
    status=$(/usr/bin/awk '$1 ~ /^HTTP\// { code=$2 } END { print code }' "$headers")
    case "$status" in
      2[0-9][0-9])
        [ -f "$body" ] && [ ! -L "$body" ] || return 1
        mv -f "$body" "$destination" || return 1
        trap - EXIT HUP INT TERM
        rm -rf -- "$workspace"
        return 0
        ;;
      3[0-9][0-9])
        location=$(/usr/bin/awk 'tolower($1) == "location:" { sub(/^[^:]*:[[:space:]]*/, ""); gsub(/\r$/, ""); print; exit }' "$headers")
        [ -n "$location" ] || return 1
        server_valid_artifact_url "$location" "$allowed_hosts" || return 1
        url=$location
        hop=$((hop + 1))
        ;;
      *) return 1 ;;
    esac
  done
  return 1
)

server_valid_runner_url() {
  value=${1:-}
  allowed=${2:-}
  server_valid_https_url "$value" || return 1
  host=${value#https://}; host=${host%%/*}
  [ -n "$allowed" ] || return 1
  for item in $allowed; do [ "$host" = "$item" ] && return 0; done
  return 1
}

server_valid_runner_name() {
  value=${1:-}
  [ "${#value}" -ge 1 ] && [ "${#value}" -le 64 ] || return 1
  case "$value" in *[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-]*) return 1 ;; esac
}

server_valid_runner_labels() {
  value=${1:-}
  [ -n "$value" ] && [ "${#value}" -le 256 ] || return 1
  case "$value" in *,*,,*|,*|*,) return 1 ;; esac
  count=0
  old_ifs=$IFS; IFS=','
  # shellcheck disable=SC2086
  set -- $value
  IFS=$old_ifs
  for item in "$@"; do
    [ "${#item}" -ge 1 ] && [ "${#item}" -le 50 ] || return 1
    case "$item" in *[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-]*) return 1 ;; esac
    count=$((count + 1))
  done
  [ "$count" -ge 1 ] && [ "$count" -le 20 ]
}

server_valid_runner_image() {
  value=${1:-}
  approved=${2:-}
  case "$value" in
    */*@sha256:????????????????????????????????????????????????????????????????) ;;
    *) return 1 ;;
  esac
  case "$value" in *[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/@:-]*) return 1 ;; esac
  image=${value%@sha256:*}
  registry=${image%%/*}
  [ "$registry" != "$image" ] || return 1
  for item in $approved; do
    case "$image" in "$item"|"$item"/*) return 0 ;; esac
  done
  return 1
}

server_valid_runner_pull_policy() {
  case "${1:-}" in always|if-not-present|never) return 0 ;; *) return 1 ;; esac
}

server_valid_policy_value() {
  case "${1:-}" in
    ''|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_./:@%+,-]*) return 1 ;;
    *) return 0 ;;
  esac
}

server_safe_path() {
  case "${1:-}" in
    ''|*..*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_./@:+%=-]*) return 1 ;;
    *) return 0 ;;
  esac
}

server_atomic_write() {
  destination=$1
  mode=$2
  content_file=$3
  server_safe_path "$destination" || server_fatal 'unsafe destination path'
  [ -f "$content_file" ] && [ ! -L "$content_file" ] || server_fatal 'staged content is not a regular file'
  parent=${destination%/*}
  [ -n "$parent" ] || parent=/
  mkdir -p "$parent" || server_fatal 'cannot create destination parent'
  temporary=$(mktemp "$parent/.stage.XXXXXX") || server_fatal 'cannot stage destination'
  trap 'rm -f "$temporary"' EXIT HUP INT TERM
  cat "$content_file" >"$temporary" || server_fatal 'cannot write destination'
  chmod "$mode" "$temporary" || server_fatal 'cannot set destination mode'
  mv -f "$temporary" "$destination" || server_fatal 'cannot publish destination'
  trap - EXIT HUP INT TERM
}

# Render a checked-in target template without evaluating its contents. Template
# values are deliberately single-line data. Replacement uses literal string
# operations rather than awk regular-expression replacement so URLs,
# credentials, and shell paths cannot change the generated syntax.
server_render_template() {
  template=$1
  destination=$2
  mode=$3
  shift 3
  [ -f "$template" ] && [ ! -L "$template" ] || {
    server_fatal "template is not a regular file: $template"
    return 1
  }
  [ $(( $# % 2 )) -eq 0 ] || {
    server_fatal 'template substitutions must be key/value pairs'
    return 1
  }
  server_safe_path "$destination" || {
    server_fatal 'unsafe rendered destination path'
    return 1
  }
  parent=${destination%/*}
  [ -n "$parent" ] || parent=/
  mkdir -p "$parent" || {
    server_fatal 'cannot create rendered destination parent'
    return 1
  }
  temporary=$(mktemp "$parent/.render.XXXXXX") || {
    server_fatal 'cannot create rendered temporary file'
    return 1
  }
  next=
  cleanup_rendered() { rm -f "$temporary" "${next:-}"; }
  cp "$template" "$temporary" || {
    cleanup_rendered
    server_fatal 'cannot stage template'
    return 1
  }
  while [ "$#" -gt 0 ]; do
    key=$1
    value=$2
    shift 2
    case "$key" in
      ''|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_]*)
        cleanup_rendered
        server_fatal 'invalid template key'
        return 1
        ;;
      esac
    case "$value" in
      *[![:print:]]*|*'\\'*|*'"'*|*'$'*|*'`'*|*';'*|*'>'*|*'<'*|*'&'*|*'|'*|*'#'*)
        cleanup_rendered
        server_fatal "unsafe template value for $key"
        return 1
        ;;
      esac
    next=$(mktemp "$parent/.render.XXXXXX") || {
      cleanup_rendered
      server_fatal 'cannot create rendered intermediate file'
      return 1
    }
    if ! awk -v placeholder="@$key@" -v replacement="$value" '
      function replace_literal(text, needle, value, position, result) {
        result = ""
        while ((position = index(text, needle)) != 0) {
          result = result substr(text, 1, position - 1) value
          text = substr(text, position + length(needle))
        }
        return result text
      }
      { print replace_literal($0, placeholder, replacement) }
    ' "$temporary" >"$next"; then
      cleanup_rendered
      server_fatal 'template rendering failed'
      return 1
    fi
    mv -f "$next" "$temporary" || {
      cleanup_rendered
      server_fatal 'cannot update rendered template'
      return 1
    }
  done
  if grep -Eq '@[A-Z][A-Z0-9_]*@' "$temporary"; then
    cleanup_rendered
    server_fatal 'template contains an unresolved placeholder'
    return 1
  fi
  if case "$destination" in *.env) true ;; *) false ;; esac; then
    /bin/sh -n "$temporary" >/dev/null 2>&1 || {
      cleanup_rendered
      server_fatal 'rendered environment is not valid shell syntax'
      return 1
    }
  fi
  chmod "$mode" "$temporary" || {
    cleanup_rendered
    server_fatal 'cannot set rendered file mode'
    return 1
  }
  mv -f "$temporary" "$destination" || {
    cleanup_rendered
    server_fatal 'cannot publish rendered file'
    return 1
  }
}
