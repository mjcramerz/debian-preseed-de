#!/bin/sh
# Sourced installer module; edit this file directly.

installer_profile_shared_family() {
  profile_name=$1

  if [ -n "${INSTALLER_HOST_PROFILE:-}" ] && [ "$profile_name" = "${INSTALLER_HOST_PROFILE}" ] && [ -n "${INSTALLER_HOST_FAMILY:-}" ]; then
    printf '%s\n' "${INSTALLER_HOST_FAMILY}"
    return 0
  fi

  case "$profile_name" in
    *-*) printf '%s\n' "${profile_name%%-*}" ;;
    *) return 1 ;;
  esac
}

installer_profile_shared_families() {
  profile_name=$1
  installer_profile_shared_family "$profile_name"
}

installer_profile_variant() {
  profile_name=$1

  case "$profile_name" in
    *-*) printf '%s\n' "${profile_name#*-}" ;;
    *) return 1 ;;
  esac
}

installer_validate_profile_component() {
  component_label=$1
  component_value=$2

  case "$component_value" in
    ''|*[!A-Za-z0-9_-]*)
      installer_fatal "${component_label} contains an invalid profile path component: ${component_value:-unset}"
      ;;
  esac
}

installer_profile_layout_family() {
  profile_name=$1
  profile_family=${2:-}

  if [ -z "$profile_family" ]; then
    profile_family=$(installer_profile_shared_family "$profile_name" 2>/dev/null || true)
  fi

  if [ -n "${INSTALLER_HOST_PROFILE:-}" ] &&
    [ "$profile_name" = "${INSTALLER_HOST_PROFILE}" ] &&
    [ -n "${INSTALLER_HOOK_FAMILY:-}" ]; then
    profile_family=$INSTALLER_HOOK_FAMILY
  fi

  case "$profile_family" in
    btrfs|vm) printf 'btrfs\n' ;;
    f2fs) printf 'f2fs\n' ;;
    *) return 1 ;;
  esac
}

installer_profile_override_metadata() {
  override_seed_base=$1
  override_profile_name=$2
  INSTALLER_PROFILE_OVERRIDE_ENV_DIR=
  INSTALLER_PROFILE_OVERRIDE_ENV_NAME=
  INSTALLER_PROFILE_OVERRIDE_VARIANT=
  INSTALLER_PROFILE_OVERRIDE_HOST_FAMILY=

  case "$override_profile_name" in
    override-*)
      override_class_name=${override_profile_name#override-}
      ;;
    *)
      return 1
      ;;
  esac

  [ -n "$override_class_name" ] || installer_fatal "profile override name is empty: ${override_profile_name:-unset}"

  profile_group=$(installer_group_for_purpose host-profile-override 2>/dev/null || true)
  [ -n "$profile_group" ] || installer_fatal "profile override group is unavailable while resolving ${override_profile_name}"
  installer_class_has_manifest_record "$profile_group" "$override_class_name" ||
    installer_fatal "profile override ${override_profile_name} is missing from classes/configs/profile.cfg"

  override_env_dir=$(installer_class_meta_value "$override_seed_base" "$profile_group" "$override_class_name" host_profile_prefix)
  override_host_family=$(installer_class_meta_value "$override_seed_base" "$profile_group" "$override_class_name" host_family)
  override_required_classes=$(installer_class_meta_value "$override_seed_base" "$profile_group" "$override_class_name" requires_classes)
  override_variant=
  override_role_group=

  for required_class in $override_required_classes; do
    installer_class_token_parts "$required_class" >/dev/null
    case "${INSTALLER_CLASS_TOKEN_GROUP:-}" in
      role)
        override_role_group=${INSTALLER_CLASS_TOKEN_GROUP}
        override_variant=${INSTALLER_CLASS_TOKEN_NAME}
        break
        ;;
    esac
  done

  [ -n "$override_env_dir" ] || installer_fatal "profile override ${override_profile_name} must define HostProfilePrefix in classes/configs/profile.cfg"
  [ -n "$override_host_family" ] || installer_fatal "profile override ${override_profile_name} must define HostFamily in classes/configs/profile.cfg"
  [ -n "$override_variant" ] || installer_fatal "profile override ${override_profile_name} must require a role/<name> class"

  override_role_variant=$(installer_class_meta_value "$override_seed_base" "${override_role_group:-role}" "$override_variant" host_variant)
  [ -n "$override_role_variant" ] || override_role_variant=$override_variant

  INSTALLER_PROFILE_OVERRIDE_ENV_DIR=$override_env_dir
  INSTALLER_PROFILE_OVERRIDE_ENV_NAME=$override_class_name
  INSTALLER_PROFILE_OVERRIDE_VARIANT=$override_role_variant
  INSTALLER_PROFILE_OVERRIDE_HOST_FAMILY=$override_host_family
}

installer_fetch_composite_env_paths() (
  # Keep all assembly variables/traps private. A failed fetch must never leave
  # a nonempty partial host.env which later callers mistake for a cached one.
  umask 077
  composite_seed_base=$1
  composite_dest_path=$2
  composite_mode=$3
  shift 3
  composite_fetched_any=false
  composite_fetched_paths=

  case "$composite_mode" in
    [0-7][0-7][0-7]|0[0-7][0-7][0-7]) ;;
    *) installer_fatal 'invalid composite environment mode' ;;
  esac
  [ ! -L "$composite_dest_path" ] &&
    { [ ! -e "$composite_dest_path" ] || [ -f "$composite_dest_path" ]; } ||
    installer_fatal "host env destination is not a regular file: ${composite_dest_path}"
  install -d -m 0700 "$(dirname "$composite_dest_path")" ||
    installer_fatal "cannot prepare host env directory: ${composite_dest_path}"
  composite_work=$(mktemp -d "${composite_dest_path}.parts.XXXXXX") ||
    installer_fatal "cannot stage host env: ${composite_dest_path}"
  composite_part_dest="${composite_work}/part"
  composite_staged="${composite_work}/host.env"
  # A terminated transport may leave its own nested temporary file. Remove
  # only our private mktemp workspace, including those interrupted-copy files.
  trap 'rm -rf -- "$composite_work"' 0
  trap 'exit 129' HUP
  trap 'exit 130' INT
  trap 'exit 143' TERM
  : >"$composite_staged" || installer_fatal 'cannot initialize staged host env'
  for composite_candidate in "$@"; do
    [ -n "$composite_candidate" ] || continue
    if ! installer_fetch_seed_path "$composite_seed_base" "$composite_candidate" "$composite_part_dest" 0600; then
      installer_fatal "failed to fetch required host env ${composite_candidate} into ${composite_dest_path}"
    fi
    [ -s "$composite_part_dest" ] || installer_fatal "empty required host env: ${composite_candidate}"
    /bin/sh -n "$composite_part_dest" >/dev/null 2>&1 ||
      installer_fatal "invalid shell syntax in required host env: ${composite_candidate}"
    case "$composite_candidate" in
      hosts/logging/observability.env)
        installer_load_logging_helpers "$composite_seed_base" &&
          installer_validate_logging_data "$composite_seed_base" "$composite_part_dest" "$composite_work" ||
          installer_fatal 'invalid shared logging data; host environment was not published'
        ;;
    esac
    { cat "$composite_part_dest" && printf '\n'; } >>"$composite_staged" ||
      installer_fatal "cannot append required host env: ${composite_candidate}"
    composite_fetched_any=true
    composite_fetched_paths="${composite_fetched_paths:+$composite_fetched_paths }$composite_candidate"
  done

  [ "$composite_fetched_any" = true ] || installer_fatal "failed to fetch host env into $composite_dest_path"
  /bin/sh -n "$composite_staged" >/dev/null 2>&1 || installer_fatal 'invalid composed host environment'
  # Explicit guards also work when a caller uses this function in an if/OR
  # list, where POSIX shells suppress errexit throughout the function body.
  chmod "$composite_mode" "$composite_staged" &&
    mv -f -- "$composite_staged" "$composite_dest_path" ||
    installer_fatal "cannot publish complete host env: ${composite_dest_path}"
  installer_info "fetched host env ${composite_dest_path} from:${composite_fetched_paths:+ ${composite_fetched_paths}}"
)

installer_fetch_host_env() {
  host_seed_base=$1
  host_profile=$2
  host_dest_path=$3
  host_mode=${4:-0600}
  host_profile_env_dir=
  host_profile_env_name=

  if [ -n "${INSTALLER_HOST_PROFILE:-}" ] &&
     [ "$host_profile" = "${INSTALLER_HOST_PROFILE}" ] &&
     [ -n "${INSTALLER_HOST_PROFILE_ENV_DIR:-}" ] &&
     [ -n "${INSTALLER_HOST_PROFILE_ENV_NAME:-}" ]; then
    host_family=${INSTALLER_HOST_FAMILY:-}
    host_variant=${INSTALLER_HOST_VARIANT:-}
    host_profile_env_dir=${INSTALLER_HOST_PROFILE_ENV_DIR}
    host_profile_env_name=${INSTALLER_HOST_PROFILE_ENV_NAME}
  else
    case "$host_profile" in
      override-*)
        installer_profile_override_metadata "$host_seed_base" "$host_profile"
        host_family=${INSTALLER_PROFILE_OVERRIDE_HOST_FAMILY}
        host_variant=${INSTALLER_PROFILE_OVERRIDE_VARIANT}
        host_profile_env_dir=${INSTALLER_PROFILE_OVERRIDE_ENV_DIR}
        host_profile_env_name=${INSTALLER_PROFILE_OVERRIDE_ENV_NAME}
        ;;
      *) installer_fatal "unsupported host profile: ${host_profile:-unset}" ;;
    esac
  fi

  [ -n "$host_family" ] || installer_fatal "unable to derive host family from profile: ${host_profile:-unset}"
  [ -n "$host_variant" ] || installer_fatal "unable to derive host variant from profile: ${host_profile:-unset}"
  [ -n "$host_profile_env_dir" ] || installer_fatal "unable to derive host profile env directory from profile: ${host_profile:-unset}"
  [ -n "$host_profile_env_name" ] || installer_fatal "unable to derive host profile env name from profile: ${host_profile:-unset}"
  installer_validate_profile_component "host family" "$host_family"
  installer_validate_profile_component "host variant" "$host_variant"
  installer_validate_profile_component "host profile env directory" "$host_profile_env_dir"
  installer_validate_profile_component "host profile env name" "$host_profile_env_name"

  host_layout_family=$(installer_profile_layout_family "$host_profile" "$host_family" 2>/dev/null || true)
  [ -n "$host_layout_family" ] || installer_fatal "unable to derive layout family from profile: ${host_profile:-unset}"
  installer_validate_profile_component "host layout family" "$host_layout_family"

  set -- \
    "$(installer_profile_env_path "$host_profile_env_dir" "$host_profile_env_name")" \
    "$(installer_repo_join_var DIR_HOSTS_INSTALLER identity.env)" \
    "$(installer_repo_join_var DIR_HOSTS_INSTALLER runtime.env)" \
    "$(installer_repo_join_var DIR_HOSTS_LOGGING observability.env)"

  case "$host_variant" in
    desktop)
      ;;
    server)
      installer_fatal "this repository installs desktop systems only"
      ;;
    *)
      installer_fatal "unsupported host profile variant: ${host_variant}"
      ;;
  esac

  set -- "$@" \
    "$(installer_repo_join_var DIR_HOSTS_INSTALLER layout.env)" \
    "$(installer_repo_join_var DIR_HOSTS_INSTALLER "${host_layout_family}.env")" \
    "$(installer_repo_join_var DIR_HOSTS_INSTALLER boot.env)"

  installer_fetch_composite_env_paths \
    "$host_seed_base" \
    "$host_dest_path" \
    "$host_mode" \
    "$@"
}

installer_fetch_account_env() {
  account_seed_base=$1
  account_dest_path=$2
  account_mode=${3:-0600}

  installer_fetch_seed_path \
    "$account_seed_base" \
    "$(installer_repo_join_var DIR_HOSTS_INSTALLER account.env)" \
    "$account_dest_path" \
    "$account_mode" || installer_fatal "failed to fetch account env"
}

