#!/bin/sh
set -eu

whisper_target_mode=0
case "${1:-}" in
  --target-install)
    whisper_target_mode=1
    shift
    ;;
esac

if [ "$whisper_target_mode" = 0 ]; then
  target_root=${1:-/target}
  [ -d "$target_root" ] || exit 0
fi

whisper_fatal() {
  printf 'fatal: %s\n' "$*" >&2
  exit 1
}

whisper_info() {
  if [ "$whisper_target_mode" = 1 ]; then
    printf '[whisper] %s\n' "$*" >&2
  else
    printf '[late:whisper] %s\n' "$*" >&2
  fi
}

whisper_validate_abs_path() {
  label=$1
  value=$2

  case "$value" in
    /*) ;;
    *) whisper_fatal "$label must be an absolute path: ${value:-unset}" ;;
  esac
  case "$value" in
    /|*..*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/@%:+,-]*)
      whisper_fatal "$label contains unsupported path syntax: $value"
      ;;
  esac
}

whisper_validate_bool() {
  case "$2" in
    0|1) ;;
    *) whisper_fatal "$1 must be 0 or 1" ;;
  esac
}

whisper_validate_positive_integer() {
  label=$1
  value=$2

  case "$value" in
    ''|*[!0123456789]*|0)
      whisper_fatal "$label must be a positive integer: ${value:-unset}"
      ;;
  esac
}

whisper_validate_nonnegative_integer() {
  label=$1
  value=$2

  case "$value" in
    ''|*[!0123456789]*)
      whisper_fatal "$label must be a non-negative integer: ${value:-unset}"
      ;;
  esac
}

whisper_validate_integer_range() {
  label=$1
  value=$2
  minimum=$3
  maximum=$4

  whisper_validate_nonnegative_integer "$label" "$value"
  [ "$value" -ge "$minimum" ] && [ "$value" -le "$maximum" ] ||
    whisper_fatal "$label must be between $minimum and $maximum: $value"
}

whisper_validate_sha256() {
  label=$1
  value=$2

  [ "${#value}" -eq 64 ] ||
    whisper_fatal "$label must contain 64 lowercase hexadecimal characters"
  case "$value" in
    *[!0123456789abcdef]*)
      whisper_fatal "$label must contain 64 lowercase hexadecimal characters"
      ;;
  esac
}

whisper_validate_model_source() {
  case "$WHISPER_DEFAULT_MODEL" in
    ''|.|..|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-]*)
      whisper_fatal "WHISPER_DEFAULT_MODEL must be a safe model label"
      ;;
  esac
  case "$WHISPER_DOWNLOAD_URL" in
    https://*) ;;
    *) whisper_fatal "WHISPER_DOWNLOAD_URL must use HTTPS" ;;
  esac
  case "$WHISPER_DOWNLOAD_URL" in
    *[[:space:]]*) whisper_fatal "WHISPER_DOWNLOAD_URL must not contain whitespace" ;;
  esac
  case "$WHISPER_DEFAULT_MODEL" in
    *.bin) model_filename=$WHISPER_DEFAULT_MODEL ;;
    *) model_filename="${WHISPER_DEFAULT_MODEL}.bin" ;;
  esac
  case "$WHISPER_DOWNLOAD_URL" in
    https://huggingface.co/ggerganov/whisper.cpp/resolve/*/ggml-"$model_filename") ;;
    *)
      whisper_fatal "WHISPER_DOWNLOAD_URL must pin the official ggml-${model_filename} artifact"
      ;;
  esac
  model_url_suffix="/ggml-${model_filename}"
  model_url_ref=${WHISPER_DOWNLOAD_URL#https://huggingface.co/ggerganov/whisper.cpp/resolve/}
  model_url_ref=${model_url_ref%"$model_url_suffix"}
  model_url_ref_length=$(printf '%s' "$model_url_ref" | wc -c | tr -d ' ')
  [ "$model_url_ref_length" = 40 ] ||
    whisper_fatal "WHISPER_DOWNLOAD_URL must use an immutable 40-character revision"
  case "$model_url_ref" in
    *[!0123456789abcdef]*)
      whisper_fatal "WHISPER_DOWNLOAD_URL revision must be lowercase hexadecimal"
      ;;
  esac
  whisper_validate_positive_integer WHISPER_MODEL_MIN_BYTES "$WHISPER_MODEL_MIN_BYTES"
  whisper_validate_sha256 WHISPER_MODEL_SHA256 "$WHISPER_MODEL_SHA256"
  model_min_bytes=$WHISPER_MODEL_MIN_BYTES
  model_sha256=$WHISPER_MODEL_SHA256
  unset model_url_ref model_url_ref_length model_url_suffix
}

whisper_validate_release_policy() {
  case "$WHISPER_RELEASE_URL" in
    https://*) ;;
    *) whisper_fatal "WHISPER_RELEASE_URL must use HTTPS" ;;
  esac
  case "$WHISPER_RELEASE_URL" in
    *[[:space:]]*) whisper_fatal "WHISPER_RELEASE_URL must not contain whitespace" ;;
  esac
  release_suffix="/${WHISPER_RELEASE_ARCHIVE_ROOT}.tar.gz"
  case "$WHISPER_RELEASE_URL" in
    *"$release_suffix") ;;
    *)
      whisper_fatal \
        "WHISPER_RELEASE_URL must end with the profile-owned archive ${release_suffix}"
      ;;
  esac
  unset release_suffix

  whisper_validate_sha256 WHISPER_RELEASE_SHA256 "$WHISPER_RELEASE_SHA256"
  whisper_validate_integer_range WHISPER_RELEASE_BYTES "$WHISPER_RELEASE_BYTES" 1 536870912
  whisper_validate_integer_range \
    WHISPER_RELEASE_MAXIMUM_EXTRACTED_BYTES \
    "$WHISPER_RELEASE_MAXIMUM_EXTRACTED_BYTES" \
    "$WHISPER_RELEASE_BYTES" \
    1073741824
  whisper_validate_integer_range \
    WHISPER_RELEASE_MAXIMUM_MEMBERS \
    "$WHISPER_RELEASE_MAXIMUM_MEMBERS" \
    6 \
    128

  case "${WHISPER_RELEASE_ARCHIVE_ROOT}:${WHISPER_RELEASE_REQUIRED_CLASS}" in
    whisper-cuda:addon/cuda-legacy) ;;
    whisper-ram:) ;;
    *)
      whisper_fatal \
        "unsupported Whisper release root/class contract: ${WHISPER_RELEASE_ARCHIVE_ROOT}:${WHISPER_RELEASE_REQUIRED_CLASS}"
      ;;
  esac
}

whisper_validate_policy() {
  : "${WHISPER_RELEASE_URL:?missing WHISPER_RELEASE_URL}"
  : "${WHISPER_RELEASE_SHA256:?missing WHISPER_RELEASE_SHA256}"
  : "${WHISPER_RELEASE_BYTES:?missing WHISPER_RELEASE_BYTES}"
  : "${WHISPER_RELEASE_MAXIMUM_EXTRACTED_BYTES:?missing WHISPER_RELEASE_MAXIMUM_EXTRACTED_BYTES}"
  : "${WHISPER_RELEASE_MAXIMUM_MEMBERS:?missing WHISPER_RELEASE_MAXIMUM_MEMBERS}"
  : "${WHISPER_RELEASE_ARCHIVE_ROOT:?missing WHISPER_RELEASE_ARCHIVE_ROOT}"
  [ "${WHISPER_RELEASE_REQUIRED_CLASS+x}" = x ] ||
    whisper_fatal "missing WHISPER_RELEASE_REQUIRED_CLASS"
  : "${WHISPER_ROOT:?missing WHISPER_ROOT}"
  : "${WHISPER_BINARY_DIR:?missing WHISPER_BINARY_DIR}"
  : "${WHISPER_METADATA_DIR:?missing WHISPER_METADATA_DIR}"
  : "${WHISPER_MODEL_DIR:?missing WHISPER_MODEL_DIR}"
  : "${WHISPER_DOWNLOAD_RETRIES:?missing WHISPER_DOWNLOAD_RETRIES}"
  : "${WHISPER_DOWNLOAD_CONNECT_TIMEOUT_SECONDS:?missing WHISPER_DOWNLOAD_CONNECT_TIMEOUT_SECONDS}"
  : "${WHISPER_DOWNLOAD_MAX_TIME_SECONDS:?missing WHISPER_DOWNLOAD_MAX_TIME_SECONDS}"
  : "${WHISPER_RUNTIME_THREADS:?missing WHISPER_RUNTIME_THREADS}"
  : "${WHISPER_PERSISTENT_MEM:?missing WHISPER_PERSISTENT_MEM}"
  : "${WHISPER_SERVER_PORT:?missing WHISPER_SERVER_PORT}"
  : "${WHISPER_DEFAULT_MODEL:?missing WHISPER_DEFAULT_MODEL}"
  : "${WHISPER_DOWNLOAD_URL:?missing WHISPER_DOWNLOAD_URL}"
  : "${WHISPER_MODEL_MIN_BYTES:?missing WHISPER_MODEL_MIN_BYTES}"
  : "${WHISPER_MIN_MEMORY_MIB:?missing WHISPER_MIN_MEMORY_MIB}"
  : "${WHISPER_MIN_CPU_CORES:?missing WHISPER_MIN_CPU_CORES}"
  [ "${WHISPER_HF_TOKEN+x}" = x ] || whisper_fatal "missing WHISPER_HF_TOKEN"
  [ "${WHISPER_MODEL_SHA256+x}" = x ] || whisper_fatal "missing WHISPER_MODEL_SHA256"

  whisper_validate_release_policy
  whisper_validate_model_source
  whisper_validate_abs_path WHISPER_ROOT "$WHISPER_ROOT"
  whisper_validate_abs_path WHISPER_BINARY_DIR "$WHISPER_BINARY_DIR"
  whisper_validate_abs_path WHISPER_METADATA_DIR "$WHISPER_METADATA_DIR"
  whisper_validate_abs_path WHISPER_MODEL_DIR "$WHISPER_MODEL_DIR"
  [ "$WHISPER_ROOT" = /data/whisper ] ||
    whisper_fatal "WHISPER_ROOT must remain /data/whisper"
  [ "$WHISPER_BINARY_DIR" = "${WHISPER_ROOT}/bin" ] ||
    whisper_fatal "WHISPER_BINARY_DIR must remain ${WHISPER_ROOT}/bin"
  [ "$WHISPER_METADATA_DIR" = "${WHISPER_ROOT}/metadata" ] ||
    whisper_fatal "WHISPER_METADATA_DIR must remain ${WHISPER_ROOT}/metadata"
  [ "$WHISPER_MODEL_DIR" = /pool/cache/whisper/models ] ||
    whisper_fatal "WHISPER_MODEL_DIR must remain /pool/cache/whisper/models"

  whisper_validate_bool WHISPER_STRICT_RESOURCES "${WHISPER_STRICT_RESOURCES-}"
  whisper_validate_bool WHISPER_FORCE_DOWNLOAD "${WHISPER_FORCE_DOWNLOAD-}"
  whisper_validate_bool WHISPER_PERSISTENT_MEM "${WHISPER_PERSISTENT_MEM-}"
  whisper_validate_integer_range WHISPER_DOWNLOAD_RETRIES "$WHISPER_DOWNLOAD_RETRIES" 1 20
  whisper_validate_integer_range \
    WHISPER_DOWNLOAD_CONNECT_TIMEOUT_SECONDS \
    "$WHISPER_DOWNLOAD_CONNECT_TIMEOUT_SECONDS" \
    5 \
    300
  whisper_validate_integer_range \
    WHISPER_DOWNLOAD_MAX_TIME_SECONDS \
    "$WHISPER_DOWNLOAD_MAX_TIME_SECONDS" \
    60 \
    86400
  [ "$WHISPER_RUNTIME_THREADS" = auto ] ||
    whisper_validate_integer_range WHISPER_RUNTIME_THREADS "$WHISPER_RUNTIME_THREADS" 1 256
  whisper_validate_integer_range WHISPER_SERVER_PORT "$WHISPER_SERVER_PORT" 1024 65535
  whisper_validate_integer_range WHISPER_MIN_MEMORY_MIB "$WHISPER_MIN_MEMORY_MIB" 0 1048576
  whisper_validate_integer_range WHISPER_MIN_CPU_CORES "$WHISPER_MIN_CPU_CORES" 0 256
  if [ "$WHISPER_MIN_MEMORY_MIB" = 0 ] || [ "$WHISPER_MIN_CPU_CORES" = 0 ]; then
    [ "$WHISPER_MIN_MEMORY_MIB" = 0 ] && [ "$WHISPER_MIN_CPU_CORES" = 0 ] ||
      whisper_fatal "Whisper resource minima must both be 0 or both be positive integers"
  fi
  if [ "$WHISPER_STRICT_RESOURCES" = 1 ]; then
    [ "$WHISPER_MIN_MEMORY_MIB" -gt 0 ] && [ "$WHISPER_MIN_CPU_CORES" -gt 0 ] ||
      whisper_fatal "WHISPER_STRICT_RESOURCES=1 requires positive resource minima"
  fi
  case "$WHISPER_HF_TOKEN" in
    ''|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-]*)
      [ -z "$WHISPER_HF_TOKEN" ] ||
        whisper_fatal "WHISPER_HF_TOKEN contains unsupported characters"
      ;;
  esac
}

whisper_validate_release_class_selection() {
  case "$WHISPER_RELEASE_REQUIRED_CLASS" in
    '') return 0 ;;
    addon/cuda-legacy)
      installer_selected_class_reference_is_selected addon/cuda-legacy 2>/dev/null ||
        whisper_fatal \
          "${WHISPER_RELEASE_ARCHIVE_ROOT} requires the addon/cuda-legacy runtime class"
      ;;
    *)
      whisper_fatal "unsupported release class requirement: $WHISPER_RELEASE_REQUIRED_CLASS"
      ;;
  esac
}

whisper_stage_target_asset() {
  repo_path=$1
  target_path=$2
  mode=$3
  tmp_asset="${tmp_env_dir}/$(basename "$target_path").$$"
  target_host_path="${target_root}${target_path}"

  whisper_validate_abs_path "target path" "$target_path"
  bootstrap_fetch_seed_file "$seed_base" "$repo_path" "$tmp_asset" 0600 "whisper asset ${repo_path}"
  install -d -m 0755 "${target_root}$(dirname "$target_path")"
  install -m "$mode" "$tmp_asset" "$target_host_path"
  chmod "$mode" "$target_host_path"
  rm -f "$tmp_asset"
}

whisper_normalize_system_perl_module_parents() {
  for module_parent in \
    /usr/local/lib/perl5 \
    /usr/local/lib/perl5/site_perl \
    /usr/local/lib/perl5/site_perl/whisper \
    /usr/local/lib/perl5/site_perl/whisper/WhisperMode
  do
    module_parent_host="${target_root}${module_parent}"
    [ ! -L "$module_parent_host" ] ||
      whisper_fatal "system Perl module parent is a symlink: ${module_parent}"
    install -d -m 0755 "$module_parent_host"
    chown root:root "$module_parent_host"
    chmod 0755 "$module_parent_host"
  done
}

whisper_mode_perl_modules() {
  cat <<'EOF'
WhisperMode/Artifacts.pm
WhisperMode/Audio.pm
WhisperMode/CLI.pm
WhisperMode/Config.pm
WhisperMode/Logger.pm
WhisperMode/Memory.pm
WhisperMode/Recorder.pm
WhisperMode/Runtime.pm
WhisperMode/State.pm
WhisperMode/Systemd.pm
WhisperMode/Transcriber.pm
EOF
}

whisper_stage_mode_perl_modules() {
  whisper_normalize_system_perl_module_parents
  whisper_mode_perl_modules |
    while IFS= read -r whisper_module; do
      [ -n "$whisper_module" ] || continue
      whisper_stage_target_asset \
        "$(installer_repo_join_var DIR_HOOKS_TARGET "usr/local/lib/perl5/site_perl/whisper/${whisper_module}")" \
        "/usr/local/lib/perl5/site_perl/whisper/${whisper_module}" \
        0644
    done
}

target_passwd_ids() {
  awk -F: -v wanted_user="$1" '$1 == wanted_user { print $3 ":" $4; exit }' \
    "${target_root}/etc/passwd" 2>/dev/null || true
}

runtime_env_path() {
  for candidate in /tmp/install-env/runtime.env /tmp/install-runtime/state/runtime.env; do
    [ -r "$candidate" ] || continue
    printf '%s\n' "$candidate"
    return 0
  done
  return 1
}

whisper_target_fatal() {
  printf 'fatal: whisper: %s\n' "$*" >&2
  exit 1
}

whisper_target_info() {
  printf '[whisper] %s\n' "$*" >&2
}

whisper_target_require_command() {
  command -v "$1" >/dev/null 2>&1 ||
    whisper_target_fatal "required command is unavailable: $1"
}

whisper_target_validate_bool() {
  case "$2" in
    0|1) ;;
    *) whisper_target_fatal "$1 must be 0 or 1" ;;
  esac
}

whisper_target_validate_positive_integer() {
  label=$1
  value=$2

  case "$value" in
    ''|*[!0123456789]*|0)
      whisper_target_fatal "$label must be a positive integer: ${value:-unset}"
      ;;
  esac
}

whisper_target_validate_pool_path() {
  label=$1
  value=$2

  case "$value" in
    /pool/*) ;;
    *) whisper_target_fatal "$label must remain below /pool: ${value:-unset}" ;;
  esac
  case "$value" in
    *..*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/@%:+,-]*)
      whisper_target_fatal "$label contains unsupported path syntax: $value"
      ;;
  esac
}

whisper_target_validate_absolute_path() {
  label=$1
  value=$2

  case "$value" in
    /*) ;;
    *) whisper_target_fatal "$label must be an absolute path: ${value:-unset}" ;;
  esac
  case "$value" in
    /|*..*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/@%:+,-]*)
      whisper_target_fatal "$label contains unsupported path syntax: $value"
      ;;
  esac
}

whisper_target_paths_overlap() {
  first=${1%/}
  second=${2%/}

  [ "$first" = "$second" ] && return 0
  case "$first" in
    "$second"/*) return 0 ;;
  esac
  case "$second" in
    "$first"/*) return 0 ;;
  esac
  return 1
}

whisper_target_managed_marker_path() {
  printf '%s/.installer-whisper-managed\n' "$1"
}

whisper_target_managed_dir() {
  dir_path=$1
  dir_label=$2
  marker_path=$(whisper_target_managed_marker_path "$dir_path")

  [ ! -L "$dir_path" ] ||
    whisper_target_fatal "managed ${dir_label} directory must not be a symbolic link: $dir_path"
  if [ -e "$dir_path" ] && [ ! -d "$dir_path" ]; then
    whisper_target_fatal "managed ${dir_label} path exists but is not a directory: $dir_path"
  fi
  if [ ! -d "$dir_path" ]; then
    install -d -m 0755 "$dir_path"
  fi

  if [ -e "$marker_path" ]; then
    [ ! -L "$marker_path" ] && [ -f "$marker_path" ] ||
      whisper_target_fatal "managed ${dir_label} marker is invalid: $marker_path"
    expected_marker="managed=whisper-${dir_label}"
    [ "$(cat "$marker_path")" = "$expected_marker" ] ||
      whisper_target_fatal "managed ${dir_label} marker does not belong to this installer: $marker_path"
    return 0
  fi

  if ! first_entry=$(find "$dir_path" -mindepth 1 -maxdepth 1 -print 2>/dev/null); then
    whisper_target_fatal "unable to inspect managed ${dir_label} directory: $dir_path"
  fi
  [ -z "$first_entry" ] ||
    whisper_target_fatal "refusing to adopt non-empty unmarked ${dir_label} directory: $dir_path"

  marker_tmp="${marker_path}.tmp.$$"
  printf 'managed=whisper-%s\n' "$dir_label" >"$marker_tmp"
  chmod 0600 "$marker_tmp"
  mv -f "$marker_tmp" "$marker_path"
}

whisper_target_secure_model_directory() {
  model_group_record=$(getent group devops 2>/dev/null || true)
  case "$model_group_record" in
    devops:*:*:*) ;;
    *) whisper_target_fatal "cannot resolve the devops group for managed Whisper models" ;;
  esac
  whisper_model_gid=${model_group_record#*:}
  whisper_model_gid=${whisper_model_gid#*:}
  whisper_model_gid=${whisper_model_gid%%:*}
  case "$whisper_model_gid" in
    ''|*[!0-9]*)
      whisper_target_fatal "cannot resolve the devops group id for managed Whisper models"
      ;;
  esac

  marker_path=$(whisper_target_managed_marker_path "$WHISPER_MODEL_DIR")
  chown "0:${whisper_model_gid}" "$WHISPER_MODEL_DIR" "$marker_path"
  chmod 2750 "$WHISPER_MODEL_DIR"
  chmod 0600 "$marker_path"
  unset marker_path model_group_record
}

whisper_target_available_cores() {
  if command -v nproc >/dev/null 2>&1; then
    nproc
  else
    getconf _NPROCESSORS_ONLN 2>/dev/null || printf '1\n'
  fi
}

whisper_target_validate_resource_budget() {
  [ "$WHISPER_STRICT_RESOURCES" = 1 ] || return 0

  whisper_target_validate_positive_integer \
    WHISPER_MIN_MEMORY_MIB \
    "$WHISPER_MIN_MEMORY_MIB"
  whisper_target_validate_positive_integer \
    WHISPER_MIN_CPU_CORES \
    "$WHISPER_MIN_CPU_CORES"

  available_memory_kib=$(awk '/^MemTotal:/ { print $2; exit }' /proc/meminfo 2>/dev/null || true)
  case "$available_memory_kib" in
    ''|*[!0-9]*) whisper_target_fatal "cannot determine available system memory for strict Whisper resources" ;;
  esac
  available_memory_mib=$((available_memory_kib / 1024))
  available_core_count=$(whisper_target_available_cores)
  case "$available_core_count" in
    ''|*[!0-9]*) whisper_target_fatal "cannot determine available CPU cores for strict Whisper resources" ;;
  esac

  [ "$available_memory_mib" -ge "$WHISPER_MIN_MEMORY_MIB" ] ||
    whisper_target_fatal "strict resources require at least ${WHISPER_MIN_MEMORY_MIB} MiB for ${WHISPER_DEFAULT_MODEL}"
  [ "$available_core_count" -ge "$WHISPER_MIN_CPU_CORES" ] ||
    whisper_target_fatal "strict resources require at least ${WHISPER_MIN_CPU_CORES} CPU cores for ${WHISPER_DEFAULT_MODEL}"
}

whisper_target_model_magic() {
  candidate=$1
  [ -f "$candidate" ] && [ ! -L "$candidate" ] || return 1
  LC_ALL=C dd if="$candidate" bs=4 count=1 2>/dev/null | od -An -tx1 | tr -d ' \n'
}

whisper_target_model_is_valid() {
  candidate=$1
  model_validation_bytes=unknown
  model_validation_magic=unavailable
  model_validation_sha256=not-checked
  model_validation_failure=unknown

  [ -f "$candidate" ] && [ ! -L "$candidate" ] || {
    model_validation_failure=not-regular-file
    return 1
  }

  model_validation_bytes=$(wc -c <"$candidate" 2>/dev/null | tr -d ' ')
  case "$model_validation_bytes" in
    ''|*[!0-9]*)
      model_validation_failure=unreadable-size
      return 1
      ;;
  esac

  model_validation_magic=$(whisper_target_model_magic "$candidate" 2>/dev/null || true)
  actual_sha256=$(sha256sum "$candidate" 2>/dev/null | awk '{print $1}')
  if [ "$actual_sha256" = "$model_sha256" ]; then
    model_validation_sha256=match
  else
    model_validation_sha256=mismatch
  fi

  [ "$model_validation_bytes" -ge "$model_min_bytes" ] || {
    model_validation_failure=byte-count
    return 1
  }
  # whisper.cpp serializes 0x67676d6c through a little-endian int32, so a
  # valid legacy GGML model begins with the raw bytes "6c6d6767".
  [ "$model_validation_magic" = 6c6d6767 ] || {
    model_validation_failure=legacy-ggml-magic
    return 1
  }
  [ "$model_validation_sha256" = match ] || {
    model_validation_failure=sha256
    return 1
  }

  model_validation_failure=none
  return 0
}

whisper_target_download_model() {
  final_model=$1
  model_tmp="${WHISPER_MODEL_DIR}/.${model_filename}.tmp.$$"
  curl_config=

  whisper_target_require_command curl
  rm -f "$model_tmp"
  if [ -n "$WHISPER_HF_TOKEN" ]; then
    curl_config=$(mktemp /tmp/whisper-curl.XXXXXX)
    chmod 0600 "$curl_config"
    printf 'header = "Authorization: Bearer %s"\n' "$WHISPER_HF_TOKEN" >"$curl_config"
    curl --fail --location --proto '=https' --proto-redir '=https' \
      --retry "$WHISPER_DOWNLOAD_RETRIES" --retry-all-errors --retry-max-time "$WHISPER_DOWNLOAD_MAX_TIME_SECONDS" --connect-timeout "$WHISPER_DOWNLOAD_CONNECT_TIMEOUT_SECONDS" --max-time "$WHISPER_DOWNLOAD_MAX_TIME_SECONDS" \
      --config "$curl_config" \
      --output "$model_tmp" \
      "$WHISPER_DOWNLOAD_URL"
  else
    curl --fail --location --proto '=https' --proto-redir '=https' \
      --retry "$WHISPER_DOWNLOAD_RETRIES" --retry-all-errors --retry-max-time "$WHISPER_DOWNLOAD_MAX_TIME_SECONDS" --connect-timeout "$WHISPER_DOWNLOAD_CONNECT_TIMEOUT_SECONDS" --max-time "$WHISPER_DOWNLOAD_MAX_TIME_SECONDS" \
      --output "$model_tmp" \
      "$WHISPER_DOWNLOAD_URL"
  fi

  if ! whisper_target_model_is_valid "$model_tmp"; then
    whisper_target_fatal \
      "downloaded model failed integrity checks: ${model_filename} (bytes=${model_validation_bytes}, magic=${model_validation_magic}, sha256=${model_validation_sha256}, reason=${model_validation_failure})"
  fi
  chown "0:${whisper_model_gid}" "$model_tmp"
  chmod 0640 "$model_tmp"
  mv -f "$model_tmp" "$final_model"
  model_tmp=
}

whisper_target_prepare_model() {
  final_model="${WHISPER_MODEL_DIR}/${model_filename}"

  if [ -L "$final_model" ] || { [ -e "$final_model" ] && [ ! -f "$final_model" ]; }; then
    whisper_target_fatal "refusing to replace an unmanaged model path: $final_model"
  fi
  if [ "$WHISPER_FORCE_DOWNLOAD" = 0 ] && whisper_target_model_is_valid "$final_model"; then
    chown "0:${whisper_model_gid}" "$final_model"
    chmod 0640 "$final_model"
    whisper_target_info "reusing verified model ${model_filename}"
    return 0
  fi
  whisper_target_download_model "$final_model"
  chown "0:${whisper_model_gid}" "$final_model"
  chmod 0640 "$final_model"
  whisper_target_info "downloaded verified model ${model_filename}"
}

whisper_target_write_runtime_config() {
  runtime_conf_dir=/etc/whisper
  runtime_conf="${runtime_conf_dir}/whisper.conf"
  runtime_conf_tmp="${runtime_conf}.tmp.$$"
  runtime_conf_template=/tmp/whisper.conf.tmpl
  runtime_model="${WHISPER_MODEL_DIR}/${model_filename}"

  [ ! -L "$runtime_conf_dir" ] ||
    whisper_target_fatal "runtime configuration directory must not be a symbolic link"
  if [ -e "$runtime_conf_dir" ] && [ ! -d "$runtime_conf_dir" ]; then
    whisper_target_fatal "runtime configuration path exists but is not a directory"
  fi
  [ -f "$runtime_conf_template" ] && [ ! -L "$runtime_conf_template" ] ||
    whisper_target_fatal "runtime configuration template is unavailable"
  [ "$(stat -c '%u' "$runtime_conf_template")" = 0 ] ||
    whisper_target_fatal "runtime configuration template must be owned by root"
  [ "$(stat -c '%a' "$runtime_conf_template")" = 600 ] ||
    whisper_target_fatal "runtime configuration template must have mode 0600"
  whisper_target_require_command grep
  whisper_target_require_command sed
  install -d -o 0 -g 0 -m 0755 "$runtime_conf_dir"
  rm -f -- "$runtime_conf_tmp"
  sed \
    -e "s|__WHISPER_CLI__|${WHISPER_BINARY_DIR}/whisper-cli|g" \
    -e "s|__WHISPER_SERVER__|${WHISPER_BINARY_DIR}/whisper-server|g" \
    -e "s|__WHISPER_SERVER_PORT__|${WHISPER_SERVER_PORT}|g" \
    -e "s|__WHISPER_MODEL__|${runtime_model}|g" \
    -e "s|__WHISPER_RUNTIME_THREADS__|${WHISPER_RUNTIME_THREADS}|g" \
    -e "s|__WHISPER_PERSISTENT_MEM__|${WHISPER_PERSISTENT_MEM}|g" \
    "$runtime_conf_template" >"$runtime_conf_tmp"
  if grep -q '__WHISPER_' "$runtime_conf_tmp"; then
    rm -f -- "$runtime_conf_tmp"
    whisper_target_fatal "runtime configuration template contains unresolved placeholders"
  fi
  chown 0:0 "$runtime_conf_tmp"
  chmod 0644 "$runtime_conf_tmp"
  mv -f "$runtime_conf_tmp" "$runtime_conf"
  chown 0:0 "$runtime_conf"
  chmod 0644 "$runtime_conf"
}

whisper_target_rollback_release_publication() {
  [ "${whisper_release_publish_in_progress:-0}" = 1 ] || return 0

  rm -rf -- "$WHISPER_BINARY_DIR" "$WHISPER_METADATA_DIR" || true
  rm -f -- "${WHISPER_ROOT}/.installer-release" || true
  whisper_release_publish_in_progress=0
}

whisper_target_download_and_install_release() {
  target_archive_helper_path=/tmp/installer-ai-runtime-archive.py
  [ -f "$target_archive_helper_path" ] && [ ! -L "$target_archive_helper_path" ] ||
    whisper_target_fatal "managed AI runtime archive helper is unavailable"
  [ "$(stat -c '%u:%g:%a' "$target_archive_helper_path")" = 0:0:700 ] ||
    whisper_target_fatal "managed AI runtime archive helper must be root:root mode 0700"

  release_record="${WHISPER_ROOT}/.installer-release"
  for release_target in \
    "$WHISPER_BINARY_DIR" \
    "$WHISPER_METADATA_DIR" \
    "$release_record"
  do
    [ ! -e "$release_target" ] && [ ! -L "$release_target" ] ||
      whisper_target_fatal "refusing to replace an existing Whisper release path: $release_target"
  done
  unset release_target

  whisper_release_staging=$(mktemp -d "${WHISPER_ROOT}/.release.XXXXXXXX") ||
    whisper_target_fatal "unable to allocate Whisper release staging directory"
  chmod 0700 "$whisper_release_staging"
  archive_path="${whisper_release_staging}/whisper.tar.gz"
  extract_dir="${whisper_release_staging}/extract"

  curl \
    --fail \
    --location \
    --silent \
    --show-error \
    --proto '=https' \
    --proto-redir '=https' \
    --tlsv1.2 \
    --retry "$WHISPER_DOWNLOAD_RETRIES" \
    --retry-all-errors \
    --retry-max-time "$WHISPER_DOWNLOAD_MAX_TIME_SECONDS" \
    --connect-timeout "$WHISPER_DOWNLOAD_CONNECT_TIMEOUT_SECONDS" \
    --max-time "$WHISPER_DOWNLOAD_MAX_TIME_SECONDS" \
    --max-filesize "$WHISPER_RELEASE_BYTES" \
    --output "$archive_path" \
    "$WHISPER_RELEASE_URL" ||
    whisper_target_fatal "failed to download pinned Whisper runtime: $WHISPER_RELEASE_URL"

  archive_bytes=$(wc -c <"$archive_path" | tr -d ' ')
  [ "$archive_bytes" = "$WHISPER_RELEASE_BYTES" ] ||
    whisper_target_fatal \
      "downloaded Whisper runtime has ${archive_bytes:-unknown} bytes; expected ${WHISPER_RELEASE_BYTES}"
  archive_sha256=$(sha256sum "$archive_path" | awk '{print $1}')
  [ "$archive_sha256" = "$WHISPER_RELEASE_SHA256" ] ||
    whisper_target_fatal "downloaded Whisper runtime SHA-256 does not match profile policy"

  install -d -m 0700 "$extract_dir"
  python3 "$target_archive_helper_path" \
    --archive "$archive_path" \
    --output-directory "$extract_dir" \
    --archive-root "$WHISPER_RELEASE_ARCHIVE_ROOT" \
    --required-directory bin \
    --required-directory metadata \
    --required-binary whisper-cli \
    --required-binary whisper-server \
    --maximum-extracted-bytes "$WHISPER_RELEASE_MAXIMUM_EXTRACTED_BYTES" \
    --maximum-members "$WHISPER_RELEASE_MAXIMUM_MEMBERS" ||
    whisper_target_fatal "Whisper runtime archive validation or extraction failed"

  release_record_staged="${extract_dir}/.installer-release"
  {
    printf 'url=%s\n' "$WHISPER_RELEASE_URL"
    printf 'sha256=%s\n' "$WHISPER_RELEASE_SHA256"
    printf 'bytes=%s\n' "$WHISPER_RELEASE_BYTES"
    printf 'archive_root=%s\n' "$WHISPER_RELEASE_ARCHIVE_ROOT"
  } >"$release_record_staged"
  chown -R 0:0 \
    "$extract_dir/bin" \
    "$extract_dir/metadata" \
    "$release_record_staged"
  chmod 0644 "$release_record_staged"

  whisper_release_publish_in_progress=1
  if mv -- "$extract_dir/bin" "$WHISPER_BINARY_DIR" &&
     mv -- "$extract_dir/metadata" "$WHISPER_METADATA_DIR" &&
     mv -- "$release_record_staged" "$release_record"
  then
    whisper_release_publish_in_progress=0
  else
    whisper_target_rollback_release_publication
    whisper_target_fatal "failed to publish the complete Whisper runtime release"
  fi

  rm -rf -- "$whisper_release_staging"
  whisper_release_staging=
  unset archive_bytes archive_path archive_sha256 extract_dir release_record release_record_staged
}

whisper_target_install_entrypoints() {
  cli_wrapper=/usr/local/libexec/whisper-cli-default-model
  stable_cli=/usr/local/bin/whisper-cli
  stable_server=/usr/local/bin/whisper-server

  [ -f "$cli_wrapper" ] && [ ! -L "$cli_wrapper" ] && [ -x "$cli_wrapper" ] ||
    whisper_target_fatal "managed default-model Whisper CLI wrapper is unavailable"
  install -d -m 0755 /usr/local/bin

  if [ -e "$stable_cli" ] && [ ! -L "$stable_cli" ]; then
    whisper_target_fatal "refusing to replace unmanaged whisper-cli path: $stable_cli"
  fi
  if [ -L "$stable_cli" ]; then
    existing_link=$(readlink "$stable_cli")
    [ "$existing_link" = "$cli_wrapper" ] ||
      whisper_target_fatal "refusing to replace unmanaged whisper-cli symlink: $stable_cli"
  fi
  ln -sfn "$cli_wrapper" "$stable_cli"

  if [ -e "$stable_server" ] && [ ! -L "$stable_server" ]; then
    whisper_target_fatal "refusing to replace unmanaged whisper-server path: $stable_server"
  fi
  if [ -L "$stable_server" ]; then
    existing_link=$(readlink "$stable_server")
    [ "$existing_link" = "${WHISPER_BINARY_DIR}/whisper-server" ] ||
      whisper_target_fatal "refusing to replace unmanaged whisper-server symlink: $stable_server"
  fi
  ln -sfn "${WHISPER_BINARY_DIR}/whisper-server" "$stable_server"
  unset cli_wrapper existing_link stable_cli stable_server
}

whisper_target_verify_metadata() {
  metadata_expected=$1
  metadata_path=$2
  metadata_label=$3

  [ ! -L "$metadata_path" ] ||
    whisper_target_fatal "${metadata_label} must not be a symbolic link: $metadata_path"
  metadata_actual=$(stat -c '%u:%g:%a' -- "$metadata_path" 2>/dev/null) ||
    whisper_target_fatal "cannot inspect ${metadata_label}: $metadata_path"
  [ "$metadata_actual" = "$metadata_expected" ] ||
    whisper_target_fatal \
      "${metadata_label} has unsafe ownership or mode: expected ${metadata_expected}, found ${metadata_actual}"
  unset metadata_actual metadata_expected metadata_label metadata_path
}

whisper_target_verify_runtime() {
  runtime_config=/etc/whisper/whisper.conf
  release_record="${WHISPER_ROOT}/.installer-release"
  cli_wrapper=/usr/local/libexec/whisper-cli-default-model
  stable_cli=/usr/local/bin/whisper-cli
  stable_server=/usr/local/bin/whisper-server
  model_path="${WHISPER_MODEL_DIR}/${model_filename}"

  for runtime_directory in "$WHISPER_ROOT" "$WHISPER_BINARY_DIR" "$WHISPER_METADATA_DIR" /etc/whisper; do
    [ -d "$runtime_directory" ] && [ ! -L "$runtime_directory" ] ||
      whisper_target_fatal "managed Whisper directory is missing or unsafe: $runtime_directory"
    whisper_target_verify_metadata 0:0:755 "$runtime_directory" "managed Whisper directory"
  done

  for binary_name in whisper-cli whisper-server; do
    binary_path="${WHISPER_BINARY_DIR}/${binary_name}"
    [ -f "$binary_path" ] && [ -x "$binary_path" ] && [ ! -L "$binary_path" ] ||
      whisper_target_fatal "managed Whisper binary is missing or unsafe: $binary_path"
    whisper_target_verify_metadata 0:0:755 "$binary_path" "managed ${binary_name} binary"
  done

  for metadata_name in SHA256SUMS WHISPER_CPP_LICENSE build-info.txt cmake-command.txt; do
    metadata_path="${WHISPER_METADATA_DIR}/${metadata_name}"
    [ -f "$metadata_path" ] && [ ! -L "$metadata_path" ] ||
      whisper_target_fatal "managed Whisper release metadata is missing or unsafe: $metadata_path"
    whisper_target_verify_metadata 0:0:644 "$metadata_path" "managed Whisper release metadata"
  done

  [ -f "$release_record" ] && [ ! -L "$release_record" ] ||
    whisper_target_fatal "managed Whisper release record is missing or unsafe"
  whisper_target_verify_metadata 0:0:644 "$release_record" "managed Whisper release record"
  for release_line in \
    "url=${WHISPER_RELEASE_URL}" \
    "sha256=${WHISPER_RELEASE_SHA256}" \
    "bytes=${WHISPER_RELEASE_BYTES}" \
    "archive_root=${WHISPER_RELEASE_ARCHIVE_ROOT}"
  do
    grep -Fqx "$release_line" "$release_record" ||
      whisper_target_fatal "managed Whisper release record is missing: $release_line"
  done

  [ -L "$stable_cli" ] && [ "$(readlink "$stable_cli")" = "$cli_wrapper" ] ||
    whisper_target_fatal "managed whisper-cli entrypoint is missing or incorrect"
  [ -L "$stable_server" ] && [ "$(readlink "$stable_server")" = "${WHISPER_BINARY_DIR}/whisper-server" ] ||
    whisper_target_fatal "managed whisper-server entrypoint is missing or incorrect"

  whisper_model_directory_metadata=$(stat -c '%u:%g:%a' "$WHISPER_MODEL_DIR")
  [ "$whisper_model_directory_metadata" = "0:${whisper_model_gid}:2750" ] ||
    whisper_target_fatal "managed Whisper model directory must be root:devops mode 2750"
  whisper_model_metadata=$(stat -c '%u:%g:%a' "$model_path")
  [ "$whisper_model_metadata" = "0:${whisper_model_gid}:640" ] ||
    whisper_target_fatal "managed Whisper model must be root:devops mode 0640"

  [ -f "$runtime_config" ] && [ ! -L "$runtime_config" ] ||
    whisper_target_fatal "managed Whisper runtime configuration is missing or unsafe"
  whisper_target_verify_metadata 0:0:644 "$runtime_config" "managed Whisper runtime configuration"
  grep -Fqx "WHISPER_CLI=${WHISPER_BINARY_DIR}/whisper-cli" "$runtime_config" ||
    whisper_target_fatal "Whisper runtime configuration does not select the managed CLI binary"
  grep -Fqx "WHISPER_SERVER=${WHISPER_BINARY_DIR}/whisper-server" "$runtime_config" ||
    whisper_target_fatal "Whisper runtime configuration does not select the managed server binary"
  grep -Fqx "WHISPER_SERVER_PORT=${WHISPER_SERVER_PORT}" "$runtime_config" ||
    whisper_target_fatal "Whisper runtime configuration does not select the managed server port"

  unset binary_name binary_path cli_wrapper metadata_name metadata_path model_path \
    release_line release_record runtime_config runtime_directory stable_cli stable_server \
    whisper_model_directory_metadata whisper_model_metadata
}

whisper_target_install() {
  # This mode runs only after whisper.sh and its archive helper have been staged
  # into /target. No source checkout or compilation is performed.
  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
  export PATH
  umask 077
  config_path=${1:-/tmp/whisper-install.env}
  runtime_conf_template=/tmp/whisper.conf.tmpl
  target_archive_helper_path=/tmp/installer-ai-runtime-archive.py
  case "$config_path" in
    /tmp/whisper-install.env) ;;
    *) whisper_target_fatal "unexpected configuration path: ${config_path:-unset}" ;;
  esac
  [ -f "$config_path" ] && [ ! -L "$config_path" ] ||
    whisper_target_fatal "temporary configuration file is unavailable"
  [ "$(stat -c '%u:%g:%a' "$config_path")" = 0:0:600 ] ||
    whisper_target_fatal "temporary configuration file must be root:root mode 0600"

  curl_config=
  model_tmp=
  whisper_release_staging=
  whisper_release_publish_in_progress=0
  # shellcheck disable=SC2329
  cleanup_target_install() {
    [ -z "${model_tmp:-}" ] || rm -f -- "$model_tmp"
    [ -z "${curl_config:-}" ] || rm -f -- "$curl_config"
    whisper_target_rollback_release_publication
    [ -z "${whisper_release_staging:-}" ] || rm -rf -- "$whisper_release_staging"
    rm -f -- "$config_path" "$runtime_conf_template" "$target_archive_helper_path"
  }
  trap cleanup_target_install 0
  trap 'cleanup_target_install; exit 1' 1 2 15

  # shellcheck disable=SC1090
  . "$config_path"
  whisper_validate_policy
  whisper_target_validate_resource_budget

  for required_command in awk cat chmod chown curl dd find getconf getent grep install mktemp mv od python3 readlink rm sed sha256sum stat tr wc; do
    whisper_target_require_command "$required_command"
  done
  unset required_command

  whisper_target_managed_dir "$WHISPER_ROOT" runtime
  whisper_target_managed_dir "$WHISPER_MODEL_DIR" models
  whisper_target_secure_model_directory
  whisper_target_download_and_install_release
  whisper_target_prepare_model
  whisper_target_write_runtime_config
  whisper_target_install_entrypoints
  whisper_target_verify_runtime

  whisper_target_info "installed whisper-cli, whisper-server, release metadata, and ${model_filename}"
}

if [ "$whisper_target_mode" = 1 ]; then
  whisper_target_install "$@"
  exit $?
fi

runtime_dir=${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}
bootstrap_lib=${INSTALLER_BOOTSTRAP_LIB:-${runtime_dir}/bootstrap/bootstrap.sh}
tmp_env_dir=${INSTALLER_LATE_TMP_ENV_DIR:-/tmp/install-env-late/whisper}

[ -s "$bootstrap_lib" ] ||
  whisper_fatal "installer bootstrap library is unavailable: ${bootstrap_lib}"
# shellcheck disable=SC1090,SC1091
. "$bootstrap_lib"
bootstrap_source_common_lib "" ||
  whisper_fatal "failed to source installer common library"
seed_base=$(installer_current_seed_base 2>/dev/null || installer_seed_base "")
bootstrap_source_common_support_libs "$seed_base" "$tmp_env_dir" fetch hook target || {
  whisper_fatal "failed to source installer late support libraries"
}
installer_ensure_context_loaded "$seed_base"

whisper_stream_target_output() {
  stream_output_file=$1
  stream_emit=$2

  : >"$stream_output_file" || return 1
  while :; do
    stream_line=
    if IFS= read -r stream_line; then
      :
    elif [ -z "$stream_line" ]; then
      break
    fi
    printf '%s\n' "$stream_line" >&3 || return 1
    if [ "$stream_emit" = 1 ]; then
      printf '%s\n' "$stream_line" || return 1
    fi
  done 3>"$stream_output_file"
}

run_whisper_install_in_target() {
  label=$1
  shift
  output=$(installer_runtime_temp_log_path install-in-target.log)
  status_file=$(installer_runtime_temp_log_path install-in-target.status)
  stream_emit=0

  rm -f "$status_file"
  target_log_should_emit info && stream_emit=1
  installer_info "in-target: ${label}"
  target_log_command_start "$label"

  if (
    set +e
    target_exec "$@" </dev/null
    target_status=$?
    printf '%s\n' "$target_status" >"$status_file" || exit 125
    exit 0
  ) 2>&1 | whisper_stream_target_output "$output" "$stream_emit"
  then
    stream_status=0
  else
    stream_status=$?
  fi

  if [ "$stream_status" -ne 0 ]; then
    code=125
    installer_error "failed to capture streamed output during ${label} (status ${stream_status})"
  elif [ ! -s "$status_file" ]; then
    code=125
    installer_error "target command status is unavailable after ${label}"
  else
    code=$(cat "$status_file")
    case "$code" in
      ''|*[!0-9]*) code=125 ;;
      *) [ "$code" -le 255 ] || code=125 ;;
    esac
  fi

  rm -f "$status_file"
  if [ "$code" -eq 0 ]; then
    target_log_command_complete "$label" "$output"
    rm -f "$output"
    return 0
  fi

  installer_error "in-target failed during ${label} (status ${code}):"
  if target_log_should_emit error; then
    print_command "$@" >&2
    [ "$stream_emit" = 1 ] || cat "$output" >&2
  fi
  target_log_command_failure "$label" "$code" error "$output"
  rm -f "$output"
  exit "$code"
}

installer_selected_class_reference_is_selected addon/whisper 2>/dev/null || exit 0
[ "${INSTALLER_HOST_VARIANT:-}" = desktop ] ||
  whisper_fatal "addon/whisper is restricted to the desktop role"

account_env=${INSTALLER_LATE_ACCOUNT_ENV:-/tmp/install-env-late/account.env}
host_env=${INSTALLER_LATE_HOST_ENV:-/tmp/install-env-late/host.env}
[ -r "$account_env" ] || installer_fetch_account_env "$seed_base" "$account_env" 0600
[ -r "$host_env" ] ||
  installer_fetch_host_env "$seed_base" "$(installer_resolve_host_profile "")" "$host_env" 0600

# shellcheck disable=SC1090,SC1091
. "$account_env"
# shellcheck disable=SC1090,SC1091
. "$host_env"
if runtime_env=$(runtime_env_path); then
  # shellcheck disable=SC1090,SC1091
  . "$runtime_env"
fi

: "${ACCOUNT_USERNAME:?ACCOUNT_USERNAME must be set before Whisper staging}"
: "${ACCOUNT_HOME:?ACCOUNT_HOME must be set before Whisper staging}"
case "$ACCOUNT_USERNAME" in
  [a-z_][a-z0-9_-]*) ;;
  *) whisper_fatal "ACCOUNT_USERNAME contains unsupported characters" ;;
esac
whisper_validate_abs_path ACCOUNT_HOME "$ACCOUNT_HOME"
whisper_validate_policy
whisper_validate_release_class_selection

target_helper=/tmp/installer-whisper
target_helper_host="${target_root}${target_helper}"
target_profile=/tmp/whisper-install.env
target_profile_host="${target_root}${target_profile}"
target_archive_helper=/tmp/installer-ai-runtime-archive.py
target_archive_helper_host="${target_root}${target_archive_helper}"
target_runtime_template=/tmp/whisper.conf.tmpl
target_runtime_template_host="${target_root}${target_runtime_template}"

whisper_stage_target_asset "$(installer_repo_join_var DIR_SCRIPTS_LATE whisper.sh)" "$target_helper" 0700
whisper_stage_target_asset "$(installer_repo_join_var DIR_SCRIPTS_LATE ai-runtime-archive.py)" "$target_archive_helper" 0700
whisper_stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET etc/whisper/whisper.conf.tmpl)" "$target_runtime_template" 0600
whisper_stage_mode_perl_modules
whisper_stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/libexec/whisper-record-toggle)" /usr/local/libexec/whisper-record-toggle 0755
whisper_stage_target_asset "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/libexec/whisper-cli-default-model)" /usr/local/libexec/whisper-cli-default-model 0755

cleanup_target_install_assets() {
  rm -f -- "$target_helper_host" "$target_profile_host" "$target_archive_helper_host" "$target_runtime_template_host"
}
trap cleanup_target_install_assets 0
trap 'cleanup_target_install_assets; exit 1' 1 2 15

umask 077
{
  write_shell_config_var WHISPER_RELEASE_URL "$WHISPER_RELEASE_URL"
  write_shell_config_var WHISPER_RELEASE_SHA256 "$WHISPER_RELEASE_SHA256"
  write_shell_config_var WHISPER_RELEASE_BYTES "$WHISPER_RELEASE_BYTES"
  write_shell_config_var WHISPER_RELEASE_MAXIMUM_EXTRACTED_BYTES "$WHISPER_RELEASE_MAXIMUM_EXTRACTED_BYTES"
  write_shell_config_var WHISPER_RELEASE_MAXIMUM_MEMBERS "$WHISPER_RELEASE_MAXIMUM_MEMBERS"
  write_shell_config_var WHISPER_RELEASE_ARCHIVE_ROOT "$WHISPER_RELEASE_ARCHIVE_ROOT"
  write_shell_config_var WHISPER_RELEASE_REQUIRED_CLASS "$WHISPER_RELEASE_REQUIRED_CLASS"
  write_shell_config_var WHISPER_ROOT "$WHISPER_ROOT"
  write_shell_config_var WHISPER_BINARY_DIR "$WHISPER_BINARY_DIR"
  write_shell_config_var WHISPER_METADATA_DIR "$WHISPER_METADATA_DIR"
  write_shell_config_var WHISPER_MODEL_DIR "$WHISPER_MODEL_DIR"
  write_shell_config_var WHISPER_DOWNLOAD_RETRIES "$WHISPER_DOWNLOAD_RETRIES"
  write_shell_config_var WHISPER_DOWNLOAD_CONNECT_TIMEOUT_SECONDS "$WHISPER_DOWNLOAD_CONNECT_TIMEOUT_SECONDS"
  write_shell_config_var WHISPER_DOWNLOAD_MAX_TIME_SECONDS "$WHISPER_DOWNLOAD_MAX_TIME_SECONDS"
  write_shell_config_var WHISPER_HF_TOKEN "$WHISPER_HF_TOKEN"
  write_shell_config_var WHISPER_MODEL_SHA256 "$WHISPER_MODEL_SHA256"
  write_shell_config_var WHISPER_MODEL_MIN_BYTES "$WHISPER_MODEL_MIN_BYTES"
  write_shell_config_var WHISPER_STRICT_RESOURCES "$WHISPER_STRICT_RESOURCES"
  write_shell_config_var WHISPER_MIN_MEMORY_MIB "$WHISPER_MIN_MEMORY_MIB"
  write_shell_config_var WHISPER_MIN_CPU_CORES "$WHISPER_MIN_CPU_CORES"
  write_shell_config_var WHISPER_FORCE_DOWNLOAD "$WHISPER_FORCE_DOWNLOAD"
  write_shell_config_var WHISPER_RUNTIME_THREADS "$WHISPER_RUNTIME_THREADS"
  write_shell_config_var WHISPER_PERSISTENT_MEM "$WHISPER_PERSISTENT_MEM"
  write_shell_config_var WHISPER_SERVER_PORT "$WHISPER_SERVER_PORT"
  write_shell_config_var WHISPER_DEFAULT_MODEL "$WHISPER_DEFAULT_MODEL"
  write_shell_config_var WHISPER_DOWNLOAD_URL "$WHISPER_DOWNLOAD_URL"
} >"$target_profile_host"
chmod 0600 "$target_profile_host"
chown 0:0 "$target_profile_host"

run_whisper_install_in_target "download and install selected whisper.cpp runtime" \
  "$target_helper" --target-install "$target_profile"

whisper_runtime_conf_dir_host="${target_root}/etc/whisper"
whisper_runtime_conf_host="${whisper_runtime_conf_dir_host}/whisper.conf"
[ -d "$whisper_runtime_conf_dir_host" ] && [ ! -L "$whisper_runtime_conf_dir_host" ] ||
  whisper_fatal "Whisper runtime configuration directory is missing or unsafe"
[ -f "$whisper_runtime_conf_host" ] && [ ! -L "$whisper_runtime_conf_host" ] ||
  whisper_fatal "Whisper runtime configuration is missing or unsafe"
grep -Fqx "WHISPER_CLI=${WHISPER_BINARY_DIR}/whisper-cli" "$whisper_runtime_conf_host" ||
  whisper_fatal "Whisper runtime configuration does not select the managed CLI binary"
grep -Fqx "WHISPER_SERVER=${WHISPER_BINARY_DIR}/whisper-server" "$whisper_runtime_conf_host" ||
  whisper_fatal "Whisper runtime configuration does not select the managed server binary"
grep -Fqx "WHISPER_SERVER_PORT=${WHISPER_SERVER_PORT}" "$whisper_runtime_conf_host" ||
  whisper_fatal "Whisper runtime configuration does not select the managed server port"
chown 0:0 "$whisper_runtime_conf_dir_host" "$whisper_runtime_conf_host"
chmod 0755 "$whisper_runtime_conf_dir_host"
chmod 0644 "$whisper_runtime_conf_host"

rm -f -- "$target_helper_host"

account_ids=$(target_passwd_ids "$ACCOUNT_USERNAME")
[ -n "$account_ids" ] ||
  whisper_fatal "primary account is missing from target passwd: $ACCOUNT_USERNAME"

whisper_audio_dir="${target_root}${ACCOUNT_HOME}/Music/Whisper/audio"
whisper_transcribed_dir="${target_root}${ACCOUNT_HOME}/Music/Whisper/transcribed"
sleek_task_dir="${target_root}${ACCOUNT_HOME}/Syncthing/sleek"
sleek_task_file="${sleek_task_dir}/whisper.txt"

install -d -m 0700 \
  "$whisper_audio_dir" \
  "$whisper_transcribed_dir" \
  "$sleek_task_dir"
if [ ! -e "$sleek_task_file" ]; then
  : >"$sleek_task_file"
fi
chmod 0600 "$sleek_task_file"

chown -R "$account_ids" \
  "${target_root}${ACCOUNT_HOME}/Music/Whisper" \
  "${target_root}${ACCOUNT_HOME}/Syncthing/sleek"

whisper_info "installed selected Whisper runtime and voice-task directories for account=${ACCOUNT_USERNAME}"
