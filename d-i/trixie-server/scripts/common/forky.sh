#!/bin/sh
# Source bridge for server features whose canonical implementation belongs to
# the Forky tree embedded in the immutable Trixie payload. This file contains
# local staging helpers only; it does not duplicate the Forky implementation.

server_forky_source_base() {
  source_dir=${1:-}
  [ -d "$source_dir/forky" ] && [ ! -L "$source_dir/forky" ] || {
    printf '%s\n' 'fatal: embedded Forky payload tree is unavailable' >&2
    return 1
  }
  printf '%s\n' "$source_dir/forky"
}

server_forky_fetch() {
  fork_base=$1
  relative=$2
  destination=$3
  mode=$4
  case "$relative" in
    ''|/*|*..*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_./@+-]*)
      printf '%s\n' 'fatal: unsafe Forky source path' >&2; return 1 ;;
  esac
  parent=${destination%/*}
  [ -n "$parent" ] || parent=/
  install -d -m 0700 "$parent"
  temporary=$(mktemp "$parent/.forky.XXXXXX")
  trap 'rm -f "$temporary"' EXIT HUP INT TERM
  case "$fork_base" in /*) ;; *)
    printf '%s\n' 'fatal: Forky source must be an extracted payload directory' >&2
    return 1 ;;
  esac
  source_path="$fork_base/$relative"
  [ -f "$source_path" ] && [ ! -L "$source_path" ] || {
    printf '%s\n' 'fatal: embedded Forky source file is unavailable' >&2
    return 1
  }
  cp "$source_path" "$temporary"
  install -m "$mode" "$temporary" "$destination"
  rm -f "$temporary"
  trap - EXIT HUP INT TERM
}

server_forky_env_value() {
  env_file=$1
  key=$2
  [ -r "$env_file" ] && [ ! -L "$env_file" ] || return 1
  case "$key" in
    DEVOPS_CODEX_URL|DEVOPS_CODEX_VERSION|DEVOPS_CODEX_RELEASE_TAG|DEVOPS_CODEX_MAXIMUM_BYTES|DEVOPS_CODEX_MAXIMUM_EXTRACTED_BYTES|DEVOPS_CODEX_ARCHIVE_BINARY_DIR|DEVOPS_CODEX_ARCHIVE_SCHEMA_MEMBER|DEVOPS_CODEX_ROOT|DEVOPS_CODEX_BINARY_PATH|DEVOPS_CODEX_SCHEMA_PATH|DEVOPS_CODEX_WRAPPER_PATH|DEVOPS_CODEX_USER_ROOT|DEVOPS_CODEX_PACKAGES_ROOT|DEVOPS_CODEX_SYSTEM_CONFIG_DIR|DEVOPS_CODEX_LOG_DIR|DEVOPS_CODEX_SQLITE_HOME|DEVOPS_CODEX_RUNTIME_ROOT|DEVOPS_CODEX_REPOSITORY_URL|DEVOPS_CODEX_REPOSITORY_BRANCH|DEVOPS_CODEX_AGENTS|DEVOPS_CODEX_HOME|DEVOPS_CODEX_SKILLS) ;;
    *) return 1 ;;
  esac
  line=$(awk -v wanted="$key" 'index($0, wanted "=") == 1 { print; exit }' "$env_file")
  case "$line" in
    "$key"=\"*\") value=${line#"$key"=\"}; value=${value%\"} ;;
    "$key"=*) value=${line#"$key"=} ;;
    *) return 1 ;;
  esac
  case "$value" in *[![:print:]]*) return 1 ;; esac
  printf '%s\n' "$value"
}

server_forky_render() {
  template=$1
  destination=$2
  mode=$3
  shift 3
  [ $(( $# % 2 )) -eq 0 ] || return 1
  parent=${destination%/*}
  [ -n "$parent" ] || parent=/
  install -d -m 0755 "$parent"
  temporary=$(mktemp "$parent/.forky-render.XXXXXX")
  trap 'rm -f "$temporary"' EXIT HUP INT TERM
  cp "$template" "$temporary"
  while [ "$#" -gt 0 ]; do
    key=$1
    value=$2
    shift 2
    next=$(mktemp "$parent/.forky-render.XXXXXX")
    awk -v placeholder="__INSTALLER_${key}__" -v replacement="$value" '
      function replace_literal(text, needle, value, position, result) {
        result = ""
        while ((position = index(text, needle)) != 0) {
          result = result substr(text, 1, position - 1) value
          text = substr(text, position + length(needle))
        }
        return result text
      }
      { print replace_literal($0, placeholder, replacement) }
    ' "$temporary" >"$next"
    mv -f "$next" "$temporary"
  done
  grep -Eq '__INSTALLER_[A-Z0-9_]+__' "$temporary" && return 1
  chmod "$mode" "$temporary"
  mv -f "$temporary" "$destination"
  trap - EXIT HUP INT TERM
}
