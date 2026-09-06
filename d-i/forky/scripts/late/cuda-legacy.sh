#!/bin/sh
# Shared late-command helpers for temporary CUDA 12.8/12.9 target repair state.

cuda_legacy_fragment_cache_path() {
  printf '%s/cuda-legacy.fragment.cfg\n' "${TMP_ENV_DIR:-/tmp/install-env-late}"
}

cuda_legacy_target_keyring_path() {
  printf '%s\n' /etc/apt/keyrings/cuda-legacy-archive-key.asc
}

cuda_legacy_target_source_path() {
  printf '%s\n' /etc/apt/sources.list.d/cuda-legacy-temp.list
}

cuda_legacy_target_apt_required() {
  installer_cuda_legacy_selected || return 1
  installer_nvidia_gpu_detected
}

cuda_legacy_fetch_fragment() {
  installer_cuda_legacy_selected || installer_fatal "cuda-legacy fragment requested without addon/cuda-legacy selected"
  fragment_path=$(cuda_legacy_fragment_cache_path)
  if [ ! -s "$fragment_path" ]; then
    installer_fetch_file "$SEED_BASE" "classes/class-addon/cuda-legacy.cfg" "$fragment_path" 0600
  fi
  printf '%s\n' "$fragment_path"
}

cuda_legacy_fragment_field_value() {
  field_name=$1
  fragment_path=$(cuda_legacy_fetch_fragment)
  field_value=$(sed -n "s/^d-i[[:space:]]\\+apt-setup\\/local[0-9][0-9]*\\/${field_name}[[:space:]]\\+string[[:space:]]\\+//p" "$fragment_path" | sed -n '1p')
  [ -n "$field_value" ] || installer_fatal "cuda-legacy fragment is missing apt-setup/${field_name}"
  printf '%s\n' "$field_value"
}

cuda_legacy_repository_value() {
  cuda_legacy_fragment_field_value repository
}

cuda_legacy_key_url() {
  cuda_legacy_fragment_field_value key
}

cuda_legacy_repository_url() {
  repo_value=$(cuda_legacy_repository_value)
  set -- $repo_value
  [ "$#" -ge 1 ] || installer_fatal "cuda-legacy repository value is empty"
  case "$1" in
    https://developer.download.nvidia.com/*) ;;
    *) installer_fatal "cuda-legacy repository URL is unsupported: $1" ;;
  esac
  printf '%s\n' "$1"
}

cuda_legacy_repository_suite() {
  repo_value=$(cuda_legacy_repository_value)
  set -- $repo_value
  [ "$#" -ge 2 ] || installer_fatal "cuda-legacy repository value must define a suite"
  printf '%s\n' "$2"
}

cuda_legacy_repository_components() {
  repo_value=$(cuda_legacy_repository_value)
  set -- $repo_value
  [ "$#" -ge 2 ] || installer_fatal "cuda-legacy repository value must define a suite"
  shift 2
  printf '%s\n' "$*"
}

cuda_legacy_fetch_remote_url() {
  installer_fetch_cuda_key "$1" "$2" "$3"
}

cuda_legacy_target_repo_line() {
  repo_url=$(cuda_legacy_repository_url)
  repo_suite=$(cuda_legacy_repository_suite)
  repo_components=$(cuda_legacy_repository_components)
  keyring_path=$(cuda_legacy_target_keyring_path)

  installer_cuda_source_line "$keyring_path" "$repo_url" "$repo_suite" "$repo_components"
}

cuda_legacy_target_repo_present() {
  repo_url=$1
  source_path="/target$(cuda_legacy_target_source_path)"

  [ -r "$source_path" ] || return 1
  grep -F -q "$repo_url" "$source_path"
}

cuda_legacy_stage_target_keyring() {
  key_url=$(cuda_legacy_key_url)
  key_cache_path="${TMP_ENV_DIR:-/tmp/install-env-late}/cuda-legacy-archive-key.asc"
  target_keyring_path="/target$(cuda_legacy_target_keyring_path)"

  cuda_legacy_fetch_remote_url "$key_url" "$key_cache_path" 0644
  install -d -m 0755 "$(dirname "$target_keyring_path")"
  installer_copy_path_with_mode "$key_cache_path" "$target_keyring_path" 0644 "cuda-legacy apt keyring"
}

cuda_legacy_stage_target_repo_source() {
  repo_line=$(cuda_legacy_target_repo_line)
  repo_cache_path="${TMP_ENV_DIR:-/tmp/install-env-late}/cuda-legacy-temp.list"
  target_source_path="/target$(cuda_legacy_target_source_path)"

  install -d -m 0755 "$(dirname "$target_source_path")"
  printf '%s\n' "$repo_line" >"$repo_cache_path"
  chmod 0644 "$repo_cache_path"
  installer_copy_path_with_mode "$repo_cache_path" "$target_source_path" 0644 "cuda-legacy apt source"
}

cuda_legacy_prepare_target_apt_state() {
  repo_url=$(cuda_legacy_repository_url)

  cuda_legacy_stage_target_keyring
  cuda_legacy_stage_target_repo_source
  cuda_legacy_target_repo_present "$repo_url" ||
    installer_fatal "cuda-legacy failed to stage ${repo_url} in the target before pkgsel/include repair"
  installer_cuda_refresh_target_apt
  installer_info "prepared legacy CUDA target apt state for pkgsel/include repair"
}

cuda_legacy_cleanup_target_apt_state() {
  target_source_path="/target$(cuda_legacy_target_source_path)"
  target_keyring_path="/target$(cuda_legacy_target_keyring_path)"

  rm -f "$target_source_path" "$target_keyring_path"
  installer_info "removed legacy CUDA target APT source and keyring after pkgsel/include repair"
}
