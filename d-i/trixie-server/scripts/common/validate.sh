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
  case "${1:-}" in https://?*/*) return 0 ;; *) return 1 ;; esac
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
      *[![:print:]]*)
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
