#!/bin/sh
# Shared late_command target asset and template helper utilities. This file is sourced, not executed.

module_value_to_lines() {
  value=${1:-}
  if [ -n "$value" ]; then
    printf '%s\n' "$value" | tr ' ' '\n'
  else
    printf '\n'
  fi
}

target_asset_host_path() (
  target_path=$1
  target_root=${INSTALLER_TARGET_DIR:-/target}
  for checked_path in "$target_root" "$target_path"; do
    case "$checked_path" in
      /*) ;;
      *) installer_fatal "target asset paths must be absolute: $checked_path"; exit 1 ;;
    esac
    case "$checked_path" in
      *//*|*/../*|*/..|*/./*|*/.)
        installer_fatal "target asset path is not normalized: $checked_path"; exit 1 ;;
    esac
  done
  target_root=${target_root%/}
  case "$target_path" in
    /|"$target_root") installer_fatal "target asset must name a file, not the target root"; exit 1 ;;
    "$target_root"/*) printf '%s\n' "$target_path" ;;
    *) printf '%s%s\n' "$target_root" "$target_path" ;;
  esac
)

ensure_target_asset_parent() (
  target_path=$1
  target_root=${INSTALLER_TARGET_DIR:-/target}
  target_host_path=$(target_asset_host_path "$target_path") || exit 1
  target_parent=$(dirname "$target_host_path")
  canonical_root=$(readlink -f "$target_root") || exit 1
  [ -d "$canonical_root" ] || exit 1
  # Check the closest existing ancestor BEFORE mkdir, so a pre-existing parent
  # symlink cannot redirect staging outside the installation root.
  ancestor=$target_parent
  while [ ! -e "$ancestor" ]; do
    [ ! -L "$ancestor" ] || exit 1
    ancestor=$(dirname "$ancestor")
  done
  canonical_ancestor=$(readlink -f "$ancestor") || exit 1
  case "$canonical_ancestor/" in
    "$canonical_root/"*) ;;
    *) installer_fatal "target asset parent escapes target root: $target_parent"; exit 1 ;;
  esac
  target_normalize_systemd_config_parent_modes "$target_path" "$target_root" || exit 1
  # BusyBox install applies umask to intermediate directories, even with -m.
  # Only newly created public parents use 022; keep existing private parents
  # and the caller's private temporary-file umask unchanged.
  [ -d "$target_parent" ] || (umask 022; install -d -m 0755 "$target_parent") || exit 1
)

target_asset_contains_installer_placeholders() {
  asset_path=$1

  installer_contains_unresolved_installer_placeholders "$asset_path"
}

target_asset_assert_no_unresolved_installer_placeholders() {
  asset_path=$1
  asset_label=${2:-$asset_path}

  installer_assert_no_unresolved_installer_placeholders "$asset_path" "$asset_label"
}

# Publish only fully fetched/rendered files. A private work directory on the
# destination filesystem makes rename atomic and contains all renderer scratch
# files; failure and signal traps never expose a half-rendered target file.
publish_target_asset() (
  set -eu
  umask 077
  asset_source=$1
  asset_target=$2
  asset_mode=$3
  asset_kind=$4
  asset_map=${5:-}
  case "$asset_mode" in [0-7][0-7][0-7]|[0-7][0-7][0-7][0-7]) ;;
    *) installer_fatal "invalid target asset mode"; exit 1 ;; esac
  asset_destination=$(target_asset_host_path "$asset_target") || exit 1
  ensure_target_asset_parent "$asset_target" || exit 1
  [ ! -d "$asset_destination" ] || { installer_fatal "asset destination is a directory"; exit 1; }
  asset_work=$(mktemp -d "$(dirname "$asset_destination")/.installer-asset.XXXXXX") || exit 1
  trap 'rm -rf -- "$asset_work"' EXIT
  trap 'exit 129' HUP
  trap 'exit 130' INT
  trap 'exit 143' TERM
  (fetch_hook "$asset_source" "$asset_work/payload") || exit 1
  case "$asset_kind" in
    plain) ;;
    template)
      (TMP_ENV_DIR=$asset_work; render_target_template "$asset_work/payload" "$asset_work/rendered" "$asset_mode") || exit 1
      mv -f "$asset_work/rendered" "$asset_work/payload" || exit 1
      ;;
    map)
      (TMP_ENV_DIR=$asset_work; apply_placeholder_map_to_target "$asset_work/payload" "$asset_map") || exit 1
      (target_asset_assert_no_unresolved_installer_placeholders "$asset_work/payload" "rendered target asset $asset_source") || exit 1
      ;;
    *) installer_fatal "invalid target asset operation"; exit 1 ;;
  esac
  chmod "$asset_mode" "$asset_work/payload" || exit 1
  mv -fT -- "$asset_work/payload" "$asset_destination" || exit 1
)

stage_target_asset() {
  publish_target_asset "$1" "$2" "$3" plain
}

remove_target_asset() (
  target_host_path=$(target_asset_host_path "$1") || exit 1
  rm -f -- "$target_host_path"
)

render_target_asset() {
  publish_target_asset "$1" "$2" "$3" template
}

render_target_asset_with_placeholder_map() {
  publish_target_asset "$1" "$2" "$3" map "$4"
}

render_target_asset_if_path() {
  repo_path=$1
  target_path=$2
  fallback_path=$3
  mode=$4

  if [ -n "$target_path" ]; then
    render_target_asset "$repo_path" "$target_path" "$mode"
  else
    remove_target_asset "$fallback_path"
  fi
}

stage_target_asset_if_path() {
  repo_path=$1
  target_path=$2
  fallback_path=$3
  mode=$4

  if [ -n "$target_path" ]; then
    stage_target_asset "$repo_path" "$target_path" "$mode"
  else
    remove_target_asset "$fallback_path"
  fi
}

stage_target_docs_index() {
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET data/docs/README.md)" "${DIR_DATA_DOCS}/README.md" 0644
  target_chown_helper_doc_path "${DIR_DATA_DOCS}/README.md"
}

target_helper_doc_owner_ids() {
  if [ -n "${TARGET_HELPER_DOC_OWNER_IDS:-}" ]; then
    printf '%s\n' "$TARGET_HELPER_DOC_OWNER_IDS"
    return 0
  fi

  : "${ACCOUNT_USERNAME:?ACCOUNT_USERNAME must be set before staging helper docs}"
  helper_doc_owner_ids=$(awk -F: -v wanted_user="$ACCOUNT_USERNAME" '$1 == wanted_user { print $3 ":" $4; exit }' /target/etc/passwd)
  [ -n "$helper_doc_owner_ids" ] || installer_fatal "target helper doc owner is missing from /target/etc/passwd: ${ACCOUNT_USERNAME}"
  TARGET_HELPER_DOC_OWNER_IDS=$helper_doc_owner_ids
  printf '%s\n' "$TARGET_HELPER_DOC_OWNER_IDS"
}

target_chown_helper_doc_path() {
  doc_target_path=$1
  helper_doc_owner_ids=$(target_helper_doc_owner_ids)
  doc_host_path=$(target_asset_host_path "$doc_target_path")

  chown "$helper_doc_owner_ids" "$doc_host_path"
}

stage_target_helper_doc() {
  repo_relpath=$1
  doc_name=$2

  [ -n "${DIR_DATA_DOCS:-}" ] || installer_fatal "DIR_DATA_DOCS must be set before staging helper docs"
  stage_target_docs_index
  doc_target_path="${DIR_DATA_DOCS}/${doc_name}"
  stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET "data/docs/${repo_relpath}")" "${doc_target_path}" 0644
  target_chown_helper_doc_path "$doc_target_path"
}

stage_target_helper_docs() {
  [ "$#" -gt 0 ] || return 0

  while [ "$#" -gt 0 ]; do
    stage_target_helper_doc "$1" "$1"
    shift
  done
}

remove_target_asset_and_empty_parent() {
  target_path=$1
  target_host_path=$(target_asset_host_path "$target_path")
  target_parent=$(dirname "$target_host_path")

  rm -f "$target_host_path"
  rmdir "$target_parent" 2>/dev/null || true
}

sysctl_profile_placeholder_map() {
  profiles="BALANCED HARDENED PERFORMANCE"
  keys="SWAPPINESS PAGE_CLUSTER VFS_CACHE_PRESSURE WATERMARK_BOOST_FACTOR WATERMARK_SCALE_FACTOR COMPACTION_PROACTIVENESS EXTFRAG_THRESHOLD DIRTY_BACKGROUND_BYTES DIRTY_BYTES DIRTY_EXPIRE_CENTISECS DIRTY_WRITEBACK_CENTISECS DIRTYTIME_EXPIRE_SECONDS STAT_INTERVAL ZONE_RECLAIM_MODE AIO_MAX_NR INOTIFY_MAX_USER_INSTANCES INOTIFY_MAX_USER_WATCHES INOTIFY_MAX_QUEUED_EVENTS SOMAXCONN NETDEV_MAX_BACKLOG TCP_MAX_SYN_BACKLOG TCP_FASTOPEN TCP_KEEPALIVE_TIME TCP_FIN_TIMEOUT"

  for profile in $profiles; do
    for key in $keys; do
      var="SYSCTL_PROFILE_${profile}_${key}"
      eval "value=\${$var-}"
      [ -n "$value" ] || installer_fatal "${var} must be set"
      case "$value" in
        *[!0123456789]*)
          installer_fatal "${var} must be a non-negative integer"
          ;;
      esac
      printf '%s=%s\n' "$var" "$value"
    done
  done
}

apply_placeholder_map_to_target() {
  target_path=$1
  map_func=$2
  rendered_tmp="${target_path}.map.$$"
  map_tmp="${TMP_ENV_DIR}/target-placeholder-map.$$.tmp"

  set --
  if ! "$map_func" >"$map_tmp"; then
    rm -f "$map_tmp"
    installer_fatal "failed to render placeholder map ${map_func} for ${target_path}"
  fi
  while IFS= read -r map_line || [ -n "$map_line" ]; do
    map_name=${map_line%%=*}
    map_value=${map_line#*=}
    [ -n "$map_name" ] || continue
    set -- "$@" "$map_name" "$map_value"
  done <"$map_tmp"
  rm -f "$map_tmp"
  installer_apply_scalar_placeholders "$target_path" "$rendered_tmp" "$@" || {
    rm -f "$map_tmp"
    rm -f "$rendered_tmp"
    installer_fatal "failed to apply placeholder map ${map_func} to ${target_path}"
  }
  mv "$rendered_tmp" "$target_path"
}

replace_placeholder_line_block() {
  target_path=$1
  placeholder=$2
  replacement=$3
  rendered_tmp="${target_path}.line.$$"

  while IFS= read -r line || [ -n "$line" ]; do
    if [ "$line" = "$placeholder" ]; then
      [ -n "$replacement" ] && printf '%s\n' "$replacement"
      continue
    fi
    printf '%s\n' "$line"
  done <"$target_path" >"$rendered_tmp"
  mv "$rendered_tmp" "$target_path"
}

apply_sysctl_profile_placeholders() {
  target_path=$1
  apply_placeholder_map_to_target "$target_path" sysctl_profile_placeholder_map
}
