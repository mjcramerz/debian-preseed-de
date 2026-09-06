#!/bin/sh
set -eu

llama_target_mode=0
case "${1:-}" in
  --target-install)
    llama_target_mode=1
    shift
    ;;
esac

if [ "$llama_target_mode" = 0 ]; then
  target_root=${1:-/target}
  [ -d "$target_root" ] || exit 0
fi

llama_fatal() {
  printf 'fatal: llama.cpp: %s\n' "$*" >&2
  exit 1
}

llama_info() {
  if [ "$llama_target_mode" = 1 ]; then
    printf '[llama] %s\n' "$*" >&2
  else
    printf '[late:llama] %s\n' "$*" >&2
  fi
}

llama_validate_abs_path() {
  label=$1
  value=$2

  case "$value" in
    /*) ;;
    *) llama_fatal "$label must be an absolute path: ${value:-unset}" ;;
  esac
  case "$value" in
    /|*..*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/@%:+,-]*)
      llama_fatal "$label contains unsupported path syntax: $value"
      ;;
  esac
}

llama_validate_bool() {
  case "$2" in
    0|1) ;;
    *) llama_fatal "$1 must be 0 or 1" ;;
  esac
}

llama_validate_positive_integer() {
  label=$1
  value=$2

  case "$value" in
    ''|*[!0123456789]*|0)
      llama_fatal "$label must be a positive integer: ${value:-unset}"
      ;;
  esac
}

llama_validate_nonnegative_integer() {
  label=$1
  value=$2

  case "$value" in
    ''|*[!0123456789]*)
      llama_fatal "$label must be a non-negative integer: ${value:-unset}"
      ;;
  esac
}

llama_validate_integer_range() {
  label=$1
  value=$2
  minimum=$3
  maximum=$4

  llama_validate_nonnegative_integer "$label" "$value"
  [ "$value" -ge "$minimum" ] && [ "$value" -le "$maximum" ] ||
    llama_fatal "$label must be between $minimum and $maximum: $value"
}

llama_validate_sha256() {
  label=$1
  value=$2

  [ "${#value}" -eq 64 ] ||
    llama_fatal "$label must contain 64 lowercase hexadecimal characters"
  case "$value" in
    *[!0123456789abcdef]*)
      llama_fatal "$label must contain 64 lowercase hexadecimal characters"
      ;;
  esac
}

llama_validate_release_policy() {
  case "$LLAMA_RELEASE_URL" in
    https://*) ;;
    *) llama_fatal "LLAMA_RELEASE_URL must use HTTPS" ;;
  esac
  case "$LLAMA_RELEASE_URL" in
    *[[:space:]]*) llama_fatal "LLAMA_RELEASE_URL must not contain whitespace" ;;
  esac
  release_suffix="/${LLAMA_RELEASE_ARCHIVE_ROOT}.tar.gz"
  case "$LLAMA_RELEASE_URL" in
    *"$release_suffix") ;;
    *)
      llama_fatal \
        "LLAMA_RELEASE_URL must end with the profile-owned archive ${release_suffix}"
      ;;
  esac
  unset release_suffix

  llama_validate_sha256 LLAMA_RELEASE_SHA256 "$LLAMA_RELEASE_SHA256"
  llama_validate_integer_range LLAMA_RELEASE_BYTES "$LLAMA_RELEASE_BYTES" 1 1073741824
  llama_validate_integer_range \
    LLAMA_RELEASE_MAXIMUM_EXTRACTED_BYTES \
    "$LLAMA_RELEASE_MAXIMUM_EXTRACTED_BYTES" \
    "$LLAMA_RELEASE_BYTES" \
    4294967296
  llama_validate_integer_range \
    LLAMA_RELEASE_MAXIMUM_MEMBERS \
    "$LLAMA_RELEASE_MAXIMUM_MEMBERS" \
    8 \
    256

  case "${LLAMA_RELEASE_ARCHIVE_ROOT}:${LLAMA_RELEASE_REQUIRED_CLASS}" in
    llama-cuda:addon/cuda-legacy) ;;
    llama-ram:) ;;
    *)
      llama_fatal \
        "unsupported llama release root/class contract: ${LLAMA_RELEASE_ARCHIVE_ROOT}:${LLAMA_RELEASE_REQUIRED_CLASS}"
      ;;
  esac
}

llama_validate_model_policy() {
  case "$LLAMA_DEFAULT_MODEL" in
    ''|.|..|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._+-]*)
      llama_fatal "LLAMA_DEFAULT_MODEL must be a safe GGUF filename"
      ;;
    *.gguf) ;;
    *) llama_fatal "LLAMA_DEFAULT_MODEL must end in .gguf" ;;
  esac

  case "$LLAMA_DOWNLOAD_URL" in
    https://*) ;;
    *) llama_fatal "LLAMA_DOWNLOAD_URL must use HTTPS" ;;
  esac
  case "$LLAMA_DOWNLOAD_URL" in
    *[[:space:]]*) llama_fatal "LLAMA_DOWNLOAD_URL must not contain whitespace" ;;
  esac

  llama_validate_sha256 LLAMA_MODEL_SHA256 "$LLAMA_MODEL_SHA256"
  llama_validate_positive_integer LLAMA_MODEL_BYTES "$LLAMA_MODEL_BYTES"
}

llama_validate_policy() {
  : "${LLAMA_RELEASE_URL:?missing LLAMA_RELEASE_URL}"
  : "${LLAMA_RELEASE_SHA256:?missing LLAMA_RELEASE_SHA256}"
  : "${LLAMA_RELEASE_BYTES:?missing LLAMA_RELEASE_BYTES}"
  : "${LLAMA_RELEASE_MAXIMUM_EXTRACTED_BYTES:?missing LLAMA_RELEASE_MAXIMUM_EXTRACTED_BYTES}"
  : "${LLAMA_RELEASE_MAXIMUM_MEMBERS:?missing LLAMA_RELEASE_MAXIMUM_MEMBERS}"
  : "${LLAMA_RELEASE_ARCHIVE_ROOT:?missing LLAMA_RELEASE_ARCHIVE_ROOT}"
  [ "${LLAMA_RELEASE_REQUIRED_CLASS+x}" = x ] ||
    llama_fatal "missing LLAMA_RELEASE_REQUIRED_CLASS"
  : "${LLAMA_ROOT:?missing LLAMA_ROOT}"
  : "${LLAMA_BINARY_DIR:?missing LLAMA_BINARY_DIR}"
  : "${LLAMA_METADATA_DIR:?missing LLAMA_METADATA_DIR}"
  : "${LLAMA_SHARE_DIR:?missing LLAMA_SHARE_DIR}"
  : "${LLAMA_WRAPPER_PATH:?missing LLAMA_WRAPPER_PATH}"
  : "${LLAMA_MODEL_DIR:?missing LLAMA_MODEL_DIR}"
  : "${LLAMA_DOWNLOAD_RETRIES:?missing LLAMA_DOWNLOAD_RETRIES}"
  : "${LLAMA_DOWNLOAD_CONNECT_TIMEOUT_SECONDS:?missing LLAMA_DOWNLOAD_CONNECT_TIMEOUT_SECONDS}"
  : "${LLAMA_DOWNLOAD_MAX_TIME_SECONDS:?missing LLAMA_DOWNLOAD_MAX_TIME_SECONDS}"
  : "${LLAMA_DEFAULT_MODEL:?missing LLAMA_DEFAULT_MODEL}"
  : "${LLAMA_DOWNLOAD_URL:?missing LLAMA_DOWNLOAD_URL}"
  : "${LLAMA_MODEL_SHA256:?missing LLAMA_MODEL_SHA256}"
  : "${LLAMA_MODEL_BYTES:?missing LLAMA_MODEL_BYTES}"
  : "${LLAMA_RUNTIME_CONTEXT:?missing LLAMA_RUNTIME_CONTEXT}"
  : "${LLAMA_RUNTIME_BATCH:?missing LLAMA_RUNTIME_BATCH}"
  : "${LLAMA_RUNTIME_UBATCH:?missing LLAMA_RUNTIME_UBATCH}"
  : "${LLAMA_RUNTIME_THREADS:?missing LLAMA_RUNTIME_THREADS}"
  : "${LLAMA_RUNTIME_THREADS_BATCH:?missing LLAMA_RUNTIME_THREADS_BATCH}"
  : "${LLAMA_RUNTIME_GPU_LAYERS:?missing LLAMA_RUNTIME_GPU_LAYERS}"
  : "${LLAMA_RUNTIME_KV_OFFLOAD:?missing LLAMA_RUNTIME_KV_OFFLOAD}"
  : "${LLAMA_RUNTIME_PARALLEL:?missing LLAMA_RUNTIME_PARALLEL}"
  : "${LLAMA_SERVER_HOST:?missing LLAMA_SERVER_HOST}"
  : "${LLAMA_SERVER_PORT:?missing LLAMA_SERVER_PORT}"
  : "${LLAMA_MIN_MEMORY_MIB:?missing LLAMA_MIN_MEMORY_MIB}"
  : "${LLAMA_MIN_CPU_CORES:?missing LLAMA_MIN_CPU_CORES}"

  llama_validate_release_policy
  llama_validate_model_policy

  llama_validate_abs_path LLAMA_ROOT "$LLAMA_ROOT"
  llama_validate_abs_path LLAMA_BINARY_DIR "$LLAMA_BINARY_DIR"
  llama_validate_abs_path LLAMA_METADATA_DIR "$LLAMA_METADATA_DIR"
  llama_validate_abs_path LLAMA_SHARE_DIR "$LLAMA_SHARE_DIR"
  llama_validate_abs_path LLAMA_WRAPPER_PATH "$LLAMA_WRAPPER_PATH"
  llama_validate_abs_path LLAMA_MODEL_DIR "$LLAMA_MODEL_DIR"
  [ "$LLAMA_ROOT" = /data/llama ] ||
    llama_fatal "LLAMA_ROOT must remain /data/llama"
  [ "$LLAMA_BINARY_DIR" = "${LLAMA_ROOT}/bin" ] ||
    llama_fatal "LLAMA_BINARY_DIR must remain ${LLAMA_ROOT}/bin"
  [ "$LLAMA_METADATA_DIR" = "${LLAMA_ROOT}/metadata" ] ||
    llama_fatal "LLAMA_METADATA_DIR must remain ${LLAMA_ROOT}/metadata"
  [ "$LLAMA_SHARE_DIR" = "${LLAMA_ROOT}/share" ] ||
    llama_fatal "LLAMA_SHARE_DIR must remain ${LLAMA_ROOT}/share"
  [ "$LLAMA_WRAPPER_PATH" = "${LLAMA_ROOT}/lib" ] ||
    llama_fatal "LLAMA_WRAPPER_PATH must remain ${LLAMA_ROOT}/lib"
  [ "$LLAMA_MODEL_DIR" = /pool/cache/llama/models ] ||
    llama_fatal "LLAMA_MODEL_DIR must remain /pool/cache/llama/models"

  llama_validate_bool LLAMA_FORCE_DOWNLOAD "${LLAMA_FORCE_DOWNLOAD-}"
  llama_validate_bool LLAMA_STRICT_RESOURCES "${LLAMA_STRICT_RESOURCES-}"
  llama_validate_bool LLAMA_RUNTIME_KV_OFFLOAD "${LLAMA_RUNTIME_KV_OFFLOAD-}"
  llama_validate_integer_range LLAMA_DOWNLOAD_RETRIES "$LLAMA_DOWNLOAD_RETRIES" 1 20
  llama_validate_integer_range \
    LLAMA_DOWNLOAD_CONNECT_TIMEOUT_SECONDS \
    "$LLAMA_DOWNLOAD_CONNECT_TIMEOUT_SECONDS" \
    5 \
    300
  llama_validate_integer_range \
    LLAMA_DOWNLOAD_MAX_TIME_SECONDS \
    "$LLAMA_DOWNLOAD_MAX_TIME_SECONDS" \
    60 \
    86400

  llama_validate_integer_range LLAMA_RUNTIME_CONTEXT "$LLAMA_RUNTIME_CONTEXT" 512 1048576
  llama_validate_integer_range LLAMA_RUNTIME_BATCH "$LLAMA_RUNTIME_BATCH" 1 32768
  llama_validate_integer_range LLAMA_RUNTIME_UBATCH "$LLAMA_RUNTIME_UBATCH" 1 32768
  [ "$LLAMA_RUNTIME_UBATCH" -le "$LLAMA_RUNTIME_BATCH" ] ||
    llama_fatal "LLAMA_RUNTIME_UBATCH must not exceed LLAMA_RUNTIME_BATCH"
  llama_validate_integer_range LLAMA_RUNTIME_THREADS "$LLAMA_RUNTIME_THREADS" 1 256
  llama_validate_integer_range LLAMA_RUNTIME_THREADS_BATCH "$LLAMA_RUNTIME_THREADS_BATCH" 1 256
  llama_validate_integer_range LLAMA_RUNTIME_GPU_LAYERS "$LLAMA_RUNTIME_GPU_LAYERS" 0 999
  llama_validate_integer_range LLAMA_RUNTIME_PARALLEL "$LLAMA_RUNTIME_PARALLEL" 1 128
  if [ "$LLAMA_RELEASE_ARCHIVE_ROOT" = llama-ram ]; then
    [ "$LLAMA_RUNTIME_GPU_LAYERS" = 0 ] ||
      llama_fatal "the RAM release requires LLAMA_RUNTIME_GPU_LAYERS=0"
  fi

  [ "$LLAMA_SERVER_HOST" = 127.0.0.1 ] ||
    llama_fatal "LLAMA_SERVER_HOST must remain 127.0.0.1"
  llama_validate_integer_range LLAMA_SERVER_PORT "$LLAMA_SERVER_PORT" 1 65535

  llama_validate_integer_range LLAMA_MIN_MEMORY_MIB "$LLAMA_MIN_MEMORY_MIB" 0 1048576
  llama_validate_integer_range LLAMA_MIN_CPU_CORES "$LLAMA_MIN_CPU_CORES" 0 256
  if [ "$LLAMA_MIN_MEMORY_MIB" = 0 ] || [ "$LLAMA_MIN_CPU_CORES" = 0 ]; then
    [ "$LLAMA_MIN_MEMORY_MIB" = 0 ] && [ "$LLAMA_MIN_CPU_CORES" = 0 ] ||
      llama_fatal "llama.cpp resource minima must both be 0 or both be positive integers"
  fi
  if [ "$LLAMA_STRICT_RESOURCES" = 1 ]; then
    [ "$LLAMA_MIN_MEMORY_MIB" -gt 0 ] && [ "$LLAMA_MIN_CPU_CORES" -gt 0 ] ||
      llama_fatal "LLAMA_STRICT_RESOURCES=1 requires positive resource minima"
  fi
}

llama_validate_release_class_selection() {
  case "$LLAMA_RELEASE_REQUIRED_CLASS" in
    '') return 0 ;;
    addon/cuda-legacy)
      installer_selected_class_reference_is_selected addon/cuda-legacy 2>/dev/null ||
        llama_fatal \
          "${LLAMA_RELEASE_ARCHIVE_ROOT} requires the addon/cuda-legacy runtime class"
      ;;
    *)
      llama_fatal "unsupported release class requirement: $LLAMA_RELEASE_REQUIRED_CLASS"
      ;;
  esac
}

llama_target_require_command() {
  command -v "$1" >/dev/null 2>&1 ||
    llama_fatal "required target command is unavailable: $1"
}

llama_target_managed_marker_path() {
  printf '%s/.installer-llama-managed\n' "$1"
}

llama_target_managed_dir() {
  dir_path=$1
  dir_label=$2
  marker_path=$(llama_target_managed_marker_path "$dir_path")

  [ ! -L "$dir_path" ] ||
    llama_fatal "managed ${dir_label} directory must not be a symbolic link: $dir_path"
  if [ -e "$dir_path" ] && [ ! -d "$dir_path" ]; then
    llama_fatal "managed ${dir_label} path exists but is not a directory: $dir_path"
  fi
  if [ ! -d "$dir_path" ]; then
    install -d -m 0755 "$dir_path"
  fi

  if [ -e "$marker_path" ]; then
    [ ! -L "$marker_path" ] && [ -f "$marker_path" ] ||
      llama_fatal "managed ${dir_label} marker is invalid: $marker_path"
    expected_marker="managed=llama-${dir_label}"
    [ "$(cat "$marker_path")" = "$expected_marker" ] ||
      llama_fatal "managed ${dir_label} marker does not belong to this installer: $marker_path"
    return 0
  fi

  if ! first_entry=$(find "$dir_path" -mindepth 1 -maxdepth 1 -print 2>/dev/null); then
    llama_fatal "unable to inspect managed ${dir_label} directory: $dir_path"
  fi
  [ -z "$first_entry" ] ||
    llama_fatal "refusing to adopt non-empty unmarked ${dir_label} directory: $dir_path"

  marker_tmp="${marker_path}.tmp.$$"
  printf 'managed=llama-%s\n' "$dir_label" >"$marker_tmp"
  chmod 0600 "$marker_tmp"
  mv -f "$marker_tmp" "$marker_path"
}

llama_target_secure_model_directory() {
  model_group_record=$(getent group devops 2>/dev/null || true)
  case "$model_group_record" in
    devops:*:*:*) ;;
    *) llama_fatal "cannot resolve the devops group for managed Llama models" ;;
  esac
  llama_model_gid=${model_group_record#*:}
  llama_model_gid=${llama_model_gid#*:}
  llama_model_gid=${llama_model_gid%%:*}
  case "$llama_model_gid" in
    ''|*[!0-9]*)
      llama_fatal "cannot resolve the devops group id for managed Llama models"
      ;;
  esac

  marker_path=$(llama_target_managed_marker_path "$LLAMA_MODEL_DIR")
  chown "0:${llama_model_gid}" "$LLAMA_MODEL_DIR" "$marker_path"
  chmod 2750 "$LLAMA_MODEL_DIR"
  chmod 0600 "$marker_path"
  unset marker_path model_group_record
}

llama_target_available_cores() {
  if command -v nproc >/dev/null 2>&1; then
    nproc
  else
    getconf _NPROCESSORS_ONLN 2>/dev/null || printf '1\n'
  fi
}

llama_target_validate_resource_budget() {
  [ "$LLAMA_STRICT_RESOURCES" = 1 ] || return 0

  available_memory_kib=$(awk '/^MemTotal:/ { print $2; exit }' /proc/meminfo 2>/dev/null || true)
  case "$available_memory_kib" in
    ''|*[!0-9]*)
      llama_fatal "cannot determine available system memory for strict llama.cpp resources"
      ;;
  esac
  available_memory_mib=$((available_memory_kib / 1024))
  available_core_count=$(llama_target_available_cores)
  case "$available_core_count" in
    ''|*[!0-9]*)
      llama_fatal "cannot determine available CPU cores for strict llama.cpp resources"
      ;;
  esac

  [ "$available_memory_mib" -ge "$LLAMA_MIN_MEMORY_MIB" ] ||
    llama_fatal "strict resources require at least ${LLAMA_MIN_MEMORY_MIB} MiB for ${LLAMA_DEFAULT_MODEL}"
  [ "$available_core_count" -ge "$LLAMA_MIN_CPU_CORES" ] ||
    llama_fatal "strict resources require at least ${LLAMA_MIN_CPU_CORES} CPU cores for ${LLAMA_DEFAULT_MODEL}"
}

llama_target_model_magic() {
  candidate=$1
  [ -f "$candidate" ] && [ ! -L "$candidate" ] || return 1
  LC_ALL=C dd if="$candidate" bs=4 count=1 2>/dev/null |
    od -An -tx1 |
    tr -d ' \n'
}

llama_target_model_is_valid() {
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

  model_validation_magic=$(llama_target_model_magic "$candidate" 2>/dev/null || true)
  actual_sha256=$(sha256sum "$candidate" 2>/dev/null | awk '{print $1}')
  if [ "$actual_sha256" = "$LLAMA_MODEL_SHA256" ]; then
    model_validation_sha256=match
  else
    model_validation_sha256=mismatch
  fi

  [ "$model_validation_bytes" = "$LLAMA_MODEL_BYTES" ] || {
    model_validation_failure=byte-count
    return 1
  }
  [ "$model_validation_magic" = 47475546 ] || {
    model_validation_failure=gguf-magic
    return 1
  }
  [ "$model_validation_sha256" = match ] || {
    model_validation_failure=sha256
    return 1
  }

  model_validation_failure=none
  return 0
}

llama_target_download_model() {
  final_model=$1
  model_tmp="${LLAMA_MODEL_DIR}/.${LLAMA_DEFAULT_MODEL}.tmp.$$"

  rm -f -- "$model_tmp"
  curl \
    --fail \
    --location \
    --silent \
    --show-error \
    --proto '=https' \
    --proto-redir '=https' \
    --retry "$LLAMA_DOWNLOAD_RETRIES" \
    --retry-all-errors \
    --retry-max-time "$LLAMA_DOWNLOAD_MAX_TIME_SECONDS" \
    --connect-timeout "$LLAMA_DOWNLOAD_CONNECT_TIMEOUT_SECONDS" \
    --max-time "$LLAMA_DOWNLOAD_MAX_TIME_SECONDS" \
    --max-filesize "$LLAMA_MODEL_BYTES" \
    --output "$model_tmp" \
    "$LLAMA_DOWNLOAD_URL" ||
    llama_fatal "failed to download configured GGUF model: $LLAMA_DOWNLOAD_URL"

  if ! llama_target_model_is_valid "$model_tmp"; then
    llama_fatal \
      "downloaded model failed integrity checks: ${LLAMA_DEFAULT_MODEL} (bytes=${model_validation_bytes}, magic=${model_validation_magic}, sha256=${model_validation_sha256}, reason=${model_validation_failure})"
  fi
  chown "0:${llama_model_gid}" "$model_tmp"
  chmod 0640 "$model_tmp"
  mv -f "$model_tmp" "$final_model"
  model_tmp=
}

llama_target_prepare_model() {
  final_model="${LLAMA_MODEL_DIR}/${LLAMA_DEFAULT_MODEL}"

  if [ -L "$final_model" ] || { [ -e "$final_model" ] && [ ! -f "$final_model" ]; }; then
    llama_fatal "refusing to replace an unmanaged model path: $final_model"
  fi
  if [ "$LLAMA_FORCE_DOWNLOAD" = 0 ] && llama_target_model_is_valid "$final_model"; then
    chown "0:${llama_model_gid}" "$final_model"
    chmod 0640 "$final_model"
    llama_info "reusing verified model ${LLAMA_DEFAULT_MODEL}"
    return 0
  fi
  llama_target_download_model "$final_model"
  chown "0:${llama_model_gid}" "$final_model"
  chmod 0640 "$final_model"
  llama_info "downloaded verified model ${LLAMA_DEFAULT_MODEL}"
}

llama_target_write_runtime_config() {
  llama_model="${LLAMA_MODEL_DIR}/${LLAMA_DEFAULT_MODEL}"
  runtime_conf_dir=/etc/llama
  runtime_conf="${runtime_conf_dir}/llama.conf"
  runtime_conf_template=/tmp/llama.conf.tmpl
  runtime_conf_tmp="${runtime_conf}.tmp.$$"

  [ ! -L "$runtime_conf_dir" ] ||
    llama_fatal "runtime configuration directory must not be a symbolic link"
  if [ -e "$runtime_conf_dir" ] && [ ! -d "$runtime_conf_dir" ]; then
    llama_fatal "runtime configuration path exists but is not a directory"
  fi
  [ ! -L "$runtime_conf" ] ||
    llama_fatal "runtime configuration file must not be a symbolic link"
  if [ -e "$runtime_conf" ] && [ ! -f "$runtime_conf" ]; then
    llama_fatal "runtime configuration file path is not a regular file"
  fi
  [ -f "$runtime_conf_template" ] && [ ! -L "$runtime_conf_template" ] ||
    llama_fatal "runtime configuration template is unavailable"
  [ "$(stat -c '%u:%g:%a' "$runtime_conf_template")" = 0:0:600 ] ||
    llama_fatal "runtime configuration template must be root:root mode 0600"

  install -d -o 0 -g 0 -m 0755 "$runtime_conf_dir"
  rm -f -- "$runtime_conf_tmp"
  sed \
    -e "s|__LLAMA_MODEL__|${llama_model}|g" \
    -e "s|__LLAMA_RUNTIME_CONTEXT__|${LLAMA_RUNTIME_CONTEXT}|g" \
    -e "s|__LLAMA_RUNTIME_BATCH__|${LLAMA_RUNTIME_BATCH}|g" \
    -e "s|__LLAMA_RUNTIME_UBATCH__|${LLAMA_RUNTIME_UBATCH}|g" \
    -e "s|__LLAMA_RUNTIME_THREADS__|${LLAMA_RUNTIME_THREADS}|g" \
    -e "s|__LLAMA_RUNTIME_THREADS_BATCH__|${LLAMA_RUNTIME_THREADS_BATCH}|g" \
    -e "s|__LLAMA_RUNTIME_GPU_LAYERS__|${LLAMA_RUNTIME_GPU_LAYERS}|g" \
    -e "s|__LLAMA_RUNTIME_KV_OFFLOAD__|${LLAMA_RUNTIME_KV_OFFLOAD}|g" \
    -e "s|__LLAMA_RUNTIME_PARALLEL__|${LLAMA_RUNTIME_PARALLEL}|g" \
    -e "s|__LLAMA_SERVER_HOST__|${LLAMA_SERVER_HOST}|g" \
    -e "s|__LLAMA_SERVER_PORT__|${LLAMA_SERVER_PORT}|g" \
    "$runtime_conf_template" >"$runtime_conf_tmp"
  if grep -q '__LLAMA_' "$runtime_conf_tmp"; then
    rm -f -- "$runtime_conf_tmp"
    llama_fatal "runtime configuration template contains unresolved placeholders"
  fi
  chown 0:0 "$runtime_conf_tmp"
  chmod 0644 "$runtime_conf_tmp"
  mv -f "$runtime_conf_tmp" "$runtime_conf"
  chown 0:0 "$runtime_conf_dir" "$runtime_conf"
  chmod 0755 "$runtime_conf_dir"
  chmod 0644 "$runtime_conf"

  unset \
    llama_model \
    runtime_conf \
    runtime_conf_dir \
    runtime_conf_template \
    runtime_conf_tmp
}

llama_target_rollback_release_publication() {
  [ "${llama_release_publish_in_progress:-0}" = 1 ] || return 0

  rm -rf -- "$LLAMA_BINARY_DIR" "$LLAMA_METADATA_DIR" "$LLAMA_SHARE_DIR" || true
  rm -f -- "${LLAMA_ROOT}/.installer-release" || true
  llama_release_publish_in_progress=0
}

llama_target_download_and_install_release() {
  target_archive_helper_path=/tmp/installer-ai-runtime-archive.py
  [ -f "$target_archive_helper_path" ] && [ ! -L "$target_archive_helper_path" ] ||
    llama_fatal "managed AI runtime archive helper is unavailable"
  [ "$(stat -c '%u:%g:%a' "$target_archive_helper_path")" = 0:0:700 ] ||
    llama_fatal "managed AI runtime archive helper must be root:root mode 0700"

  release_record="${LLAMA_ROOT}/.installer-release"
  for release_target in \
    "$LLAMA_BINARY_DIR" \
    "$LLAMA_METADATA_DIR" \
    "$LLAMA_SHARE_DIR" \
    "$release_record"
  do
    [ ! -e "$release_target" ] && [ ! -L "$release_target" ] ||
      llama_fatal "refusing to replace an existing llama release path: $release_target"
  done
  unset release_target

  llama_release_staging=$(mktemp -d "${LLAMA_ROOT}/.release.XXXXXXXX") ||
    llama_fatal "unable to allocate llama release staging directory"
  chmod 0700 "$llama_release_staging"
  archive_path="${llama_release_staging}/llama.tar.gz"
  extract_dir="${llama_release_staging}/extract"

  curl \
    --fail \
    --location \
    --silent \
    --show-error \
    --proto '=https' \
    --proto-redir '=https' \
    --tlsv1.2 \
    --retry "$LLAMA_DOWNLOAD_RETRIES" \
    --retry-all-errors \
    --retry-max-time "$LLAMA_DOWNLOAD_MAX_TIME_SECONDS" \
    --connect-timeout "$LLAMA_DOWNLOAD_CONNECT_TIMEOUT_SECONDS" \
    --max-time "$LLAMA_DOWNLOAD_MAX_TIME_SECONDS" \
    --max-filesize "$LLAMA_RELEASE_BYTES" \
    --output "$archive_path" \
    "$LLAMA_RELEASE_URL" ||
    llama_fatal "failed to download pinned llama runtime: $LLAMA_RELEASE_URL"

  archive_bytes=$(wc -c <"$archive_path" | tr -d ' ')
  [ "$archive_bytes" = "$LLAMA_RELEASE_BYTES" ] ||
    llama_fatal \
      "downloaded llama runtime has ${archive_bytes:-unknown} bytes; expected ${LLAMA_RELEASE_BYTES}"
  archive_sha256=$(sha256sum "$archive_path" | awk '{print $1}')
  [ "$archive_sha256" = "$LLAMA_RELEASE_SHA256" ] ||
    llama_fatal "downloaded llama runtime SHA-256 does not match profile policy"

  install -d -m 0700 "$extract_dir"
  python3 "$target_archive_helper_path" \
    --archive "$archive_path" \
    --output-directory "$extract_dir" \
    --archive-root "$LLAMA_RELEASE_ARCHIVE_ROOT" \
    --required-directory bin \
    --required-directory metadata \
    --required-directory share \
    --required-binary llama-bench \
    --required-binary llama-cli \
    --required-binary llama-gguf-split \
    --required-binary llama-quantize \
    --required-binary llama-server \
    --maximum-extracted-bytes "$LLAMA_RELEASE_MAXIMUM_EXTRACTED_BYTES" \
    --maximum-members "$LLAMA_RELEASE_MAXIMUM_MEMBERS" ||
    llama_fatal "llama runtime archive validation or extraction failed"

  release_record_staged="${extract_dir}/.installer-release"
  {
    printf 'url=%s\n' "$LLAMA_RELEASE_URL"
    printf 'sha256=%s\n' "$LLAMA_RELEASE_SHA256"
    printf 'bytes=%s\n' "$LLAMA_RELEASE_BYTES"
    printf 'archive_root=%s\n' "$LLAMA_RELEASE_ARCHIVE_ROOT"
  } >"$release_record_staged"
  chown -R 0:0 \
    "$extract_dir/bin" \
    "$extract_dir/metadata" \
    "$extract_dir/share" \
    "$release_record_staged"
  chmod 0644 "$release_record_staged"

  llama_release_publish_in_progress=1
  if mv -- "$extract_dir/bin" "$LLAMA_BINARY_DIR" &&
     mv -- "$extract_dir/metadata" "$LLAMA_METADATA_DIR" &&
     mv -- "$extract_dir/share" "$LLAMA_SHARE_DIR" &&
     mv -- "$release_record_staged" "$release_record"
  then
    llama_release_publish_in_progress=0
  else
    llama_target_rollback_release_publication
    llama_fatal "failed to publish the complete llama runtime release"
  fi

  rm -rf -- "$llama_release_staging"
  llama_release_staging=
  unset archive_bytes archive_path archive_sha256 extract_dir release_record release_record_staged
}

llama_target_install_wrapper() {
  wrapper_file="${LLAMA_WRAPPER_PATH}/llama"
  wrapper_source=/tmp/llama-launcher

  [ ! -L "$LLAMA_WRAPPER_PATH" ] ||
    llama_fatal "managed llama wrapper directory must not be a symbolic link"
  install -d -o 0 -g 0 -m 0755 "$LLAMA_WRAPPER_PATH"
  [ ! -L "$wrapper_file" ] ||
    llama_fatal "managed llama wrapper must not be a symbolic link: $wrapper_file"
  if [ -e "$wrapper_file" ] && [ ! -f "$wrapper_file" ]; then
    llama_fatal "managed llama wrapper path is not a regular file: $wrapper_file"
  fi
  [ -f "$wrapper_source" ] && [ ! -L "$wrapper_source" ] ||
    llama_fatal "managed llama launcher source is unavailable"
  [ "$(stat -c '%u:%g:%a' "$wrapper_source")" = 0:0:600 ] ||
    llama_fatal "managed llama launcher source must be root:root mode 0600"
  /bin/sh -n "$wrapper_source" ||
    llama_fatal "managed llama launcher source is not valid POSIX shell"

  wrapper_tmp="${wrapper_file}.tmp.$$"
  rm -f -- "$wrapper_tmp"
  install -o 0 -g 0 -m 0755 "$wrapper_source" "$wrapper_tmp"
  mv -f "$wrapper_tmp" "$wrapper_file"
  chown 0:0 "$LLAMA_ROOT" "$LLAMA_WRAPPER_PATH" "$wrapper_file"
  chmod 0755 "$LLAMA_ROOT" "$LLAMA_WRAPPER_PATH" "$wrapper_file"
  unset wrapper_file wrapper_source wrapper_tmp
}

llama_target_verify_metadata() {
  metadata_expected=$1
  metadata_path=$2
  metadata_label=$3

  [ ! -L "$metadata_path" ] ||
    llama_fatal "${metadata_label} must not be a symbolic link: $metadata_path"
  metadata_actual=$(stat -c '%u:%g:%a' -- "$metadata_path" 2>/dev/null) ||
    llama_fatal "cannot inspect ${metadata_label} metadata: $metadata_path"
  [ "$metadata_actual" = "$metadata_expected" ] ||
    llama_fatal \
      "${metadata_label} has unsafe ownership or mode at ${metadata_path}: expected ${metadata_expected}, found ${metadata_actual}"

  unset metadata_actual metadata_expected metadata_label metadata_path
}

llama_target_verify_runtime() {
  runtime_verify_model="${LLAMA_MODEL_DIR}/${LLAMA_DEFAULT_MODEL}"
  runtime_verify_wrapper="${LLAMA_WRAPPER_PATH}/llama"
  runtime_verify_config_dir=/etc/llama
  runtime_verify_config="${runtime_verify_config_dir}/llama.conf"
  runtime_verify_release_record="${LLAMA_ROOT}/.installer-release"

  for runtime_verify_directory in \
    "$LLAMA_ROOT" \
    "$LLAMA_BINARY_DIR" \
    "$LLAMA_METADATA_DIR" \
    "$LLAMA_SHARE_DIR" \
    "$LLAMA_WRAPPER_PATH" \
    "$runtime_verify_config_dir"
  do
    [ -d "$runtime_verify_directory" ] && [ ! -L "$runtime_verify_directory" ] ||
      llama_fatal "managed llama directory is missing or unsafe: $runtime_verify_directory"
    llama_target_verify_metadata 0:0:755 "$runtime_verify_directory" "managed llama directory"
  done

  runtime_verify_devops_group=$(getent group devops 2>/dev/null || true)
  case "$runtime_verify_devops_group" in
    devops:*:*:*) ;;
    *) llama_fatal "cannot resolve the devops group for the managed llama model directory" ;;
  esac
  runtime_verify_devops_gid=${runtime_verify_devops_group#*:}
  runtime_verify_devops_gid=${runtime_verify_devops_gid#*:}
  runtime_verify_devops_gid=${runtime_verify_devops_gid%%:*}
  case "$runtime_verify_devops_gid" in
    ''|*[!0-9]*) llama_fatal "cannot resolve the devops group id for the managed llama model directory" ;;
  esac
  [ -d "$LLAMA_MODEL_DIR" ] && [ ! -L "$LLAMA_MODEL_DIR" ] ||
    llama_fatal "managed llama model directory is missing or unsafe: $LLAMA_MODEL_DIR"
  llama_target_verify_metadata "0:${runtime_verify_devops_gid}:2750" "$LLAMA_MODEL_DIR" "managed llama model directory"

  for runtime_verify_binary_name in llama-bench llama-cli llama-gguf-split llama-quantize llama-server; do
    runtime_verify_binary="${LLAMA_BINARY_DIR}/${runtime_verify_binary_name}"
    [ -f "$runtime_verify_binary" ] && [ -x "$runtime_verify_binary" ] && [ ! -L "$runtime_verify_binary" ] ||
      llama_fatal "managed llama binary is missing or unsafe: $runtime_verify_binary"
    llama_target_verify_metadata 0:0:755 "$runtime_verify_binary" "managed ${runtime_verify_binary_name} binary"
  done

  for runtime_verify_metadata_name in LLAMA_CPP_LICENSE SHA256SUMS build-info.txt cmake-command.txt file.txt ldd.txt llama-cli-version.txt llama-server-version.txt; do
    runtime_verify_metadata="${LLAMA_METADATA_DIR}/${runtime_verify_metadata_name}"
    [ -f "$runtime_verify_metadata" ] && [ ! -L "$runtime_verify_metadata" ] ||
      llama_fatal "managed llama release metadata is missing or unsafe: $runtime_verify_metadata"
    llama_target_verify_metadata 0:0:644 "$runtime_verify_metadata" "managed llama release metadata"
  done

  runtime_verify_ui_dir="${LLAMA_SHARE_DIR}/llama-ui"
  [ -d "$runtime_verify_ui_dir" ] && [ ! -L "$runtime_verify_ui_dir" ] ||
    llama_fatal "managed llama UI directory is missing or unsafe"
  llama_target_verify_metadata 0:0:755 "$runtime_verify_ui_dir" "managed llama UI directory"
  for runtime_verify_ui_name in SHA256SUMS bundle-info.txt dist.tar.gz; do
    runtime_verify_ui_file="${runtime_verify_ui_dir}/${runtime_verify_ui_name}"
    [ -f "$runtime_verify_ui_file" ] && [ ! -L "$runtime_verify_ui_file" ] ||
      llama_fatal "managed llama UI file is missing or unsafe: $runtime_verify_ui_file"
    llama_target_verify_metadata 0:0:644 "$runtime_verify_ui_file" "managed llama UI file"
  done

  [ -f "$runtime_verify_release_record" ] && [ ! -L "$runtime_verify_release_record" ] ||
    llama_fatal "managed llama release record is missing or unsafe"
  llama_target_verify_metadata 0:0:644 "$runtime_verify_release_record" "managed llama release record"
  for runtime_verify_release_line in \
    "url=${LLAMA_RELEASE_URL}" \
    "sha256=${LLAMA_RELEASE_SHA256}" \
    "bytes=${LLAMA_RELEASE_BYTES}" \
    "archive_root=${LLAMA_RELEASE_ARCHIVE_ROOT}"
  do
    grep -Fqx "$runtime_verify_release_line" "$runtime_verify_release_record" ||
      llama_fatal "managed llama release record is missing: $runtime_verify_release_line"
  done

  [ -f "$runtime_verify_wrapper" ] && [ -x "$runtime_verify_wrapper" ] && [ ! -L "$runtime_verify_wrapper" ] ||
    llama_fatal "managed llama launcher is missing or unsafe: $runtime_verify_wrapper"
  llama_target_verify_metadata 0:0:755 "$runtime_verify_wrapper" "managed llama launcher"
  /bin/sh -n "$runtime_verify_wrapper" ||
    llama_fatal "managed llama launcher is not valid POSIX shell"

  [ -f "$runtime_verify_model" ] && [ ! -L "$runtime_verify_model" ] ||
    llama_fatal "managed GGUF model is missing or unsafe: $runtime_verify_model"
  llama_target_verify_metadata "0:${runtime_verify_devops_gid}:640" "$runtime_verify_model" "managed GGUF model"

  [ -f "$runtime_verify_config" ] && [ ! -L "$runtime_verify_config" ] ||
    llama_fatal "managed llama configuration is missing or unsafe: $runtime_verify_config"
  llama_target_verify_metadata 0:0:644 "$runtime_verify_config" "managed llama configuration"
  if grep -q '__LLAMA_' "$runtime_verify_config"; then
    llama_fatal "managed llama configuration contains unresolved placeholders"
  fi
  if grep -q '^LLAMA_BINARY_DIR=' "$runtime_verify_config"; then
    llama_fatal "managed llama configuration must not define the fixed binary directory"
  fi

  runtime_verify_record_count=$(grep -c '^LLAMA_' "$runtime_verify_config" || true)
  [ "$runtime_verify_record_count" = 11 ] ||
    llama_fatal "managed llama configuration must contain exactly 11 runtime records: found ${runtime_verify_record_count:-unreadable}"
  for runtime_verify_expected_record in \
    "LLAMA_MODEL=${runtime_verify_model}" \
    "LLAMA_CONTEXT_SIZE=${LLAMA_RUNTIME_CONTEXT}" \
    "LLAMA_BATCH_SIZE=${LLAMA_RUNTIME_BATCH}" \
    "LLAMA_UBATCH_SIZE=${LLAMA_RUNTIME_UBATCH}" \
    "LLAMA_THREADS=${LLAMA_RUNTIME_THREADS}" \
    "LLAMA_THREADS_BATCH=${LLAMA_RUNTIME_THREADS_BATCH}" \
    "LLAMA_GPU_LAYERS=${LLAMA_RUNTIME_GPU_LAYERS}" \
    "LLAMA_KV_OFFLOAD=${LLAMA_RUNTIME_KV_OFFLOAD}" \
    "LLAMA_PARALLEL=${LLAMA_RUNTIME_PARALLEL}" \
    "LLAMA_SERVER_HOST=${LLAMA_SERVER_HOST}" \
    "LLAMA_SERVER_PORT=${LLAMA_SERVER_PORT}"
  do
    grep -Fqx "$runtime_verify_expected_record" "$runtime_verify_config" ||
      llama_fatal "managed llama configuration is missing the expected record: $runtime_verify_expected_record"
  done

  unset runtime_verify_binary runtime_verify_binary_name runtime_verify_config runtime_verify_config_dir \
    runtime_verify_devops_gid runtime_verify_devops_group runtime_verify_directory \
    runtime_verify_expected_record runtime_verify_metadata runtime_verify_metadata_name \
    runtime_verify_model runtime_verify_record_count runtime_verify_release_line \
    runtime_verify_release_record runtime_verify_ui_dir runtime_verify_ui_file \
    runtime_verify_ui_name runtime_verify_wrapper
}

llama_target_install() {
  # This mode runs only after llama.sh and its archive helper have been staged
  # into /target. No source checkout or compilation is performed.
  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
  export PATH
  umask 077

  config_path=${1:-/tmp/llama-install.env}
  target_install_runtime_conf_template=/tmp/llama.conf.tmpl
  target_install_wrapper_source=/tmp/llama-launcher
  target_archive_helper_path=/tmp/installer-ai-runtime-archive.py
  case "$config_path" in
    /tmp/llama-install.env) ;;
    *) llama_fatal "unexpected configuration path: ${config_path:-unset}" ;;
  esac
  llama_target_require_command stat
  [ -f "$config_path" ] && [ ! -L "$config_path" ] ||
    llama_fatal "temporary configuration file is unavailable"
  [ "$(stat -c '%u:%g:%a' "$config_path")" = 0:0:600 ] ||
    llama_fatal "temporary configuration file must be root:root mode 0600"

  llama_release_staging=
  llama_release_publish_in_progress=0
  model_tmp=
  # shellcheck disable=SC2329
  cleanup_target_install() {
    [ -z "${model_tmp:-}" ] || rm -f -- "$model_tmp"
    llama_target_rollback_release_publication
    [ -z "${llama_release_staging:-}" ] || rm -rf -- "$llama_release_staging"
    rm -f -- "$config_path" "$target_install_runtime_conf_template" "$target_install_wrapper_source" "$target_archive_helper_path"
  }
  trap cleanup_target_install 0
  trap 'cleanup_target_install; exit 1' 1 2 15

  # shellcheck disable=SC1090
  . "$config_path"
  llama_validate_policy

  for required_command in awk cat chmod chown curl dd find getconf getent grep install mktemp mv od python3 rm sed sha256sum stat tr wc; do
    llama_target_require_command "$required_command"
  done
  unset required_command

  llama_target_validate_resource_budget
  llama_target_managed_dir "$LLAMA_ROOT" runtime
  llama_target_managed_dir "$LLAMA_MODEL_DIR" models
  llama_target_secure_model_directory
  llama_target_download_and_install_release
  llama_target_prepare_model
  llama_target_write_runtime_config
  llama_target_install_wrapper
  llama_target_verify_runtime

  llama_info "installed five llama release binaries, metadata, shared assets, configuration, launcher, and ${LLAMA_DEFAULT_MODEL}"
}

if [ "$llama_target_mode" = 1 ]; then
  llama_target_install "$@"
  exit $?
fi

runtime_dir=${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}
bootstrap_lib=${INSTALLER_BOOTSTRAP_LIB:-${runtime_dir}/bootstrap/bootstrap.sh}
tmp_env_dir=${INSTALLER_LLAMA_TMP_ENV_DIR:-/tmp/install-env-late/llama}

[ -s "$bootstrap_lib" ] ||
  llama_fatal "installer bootstrap library is unavailable: ${bootstrap_lib}"
# shellcheck disable=SC1090,SC1091
. "$bootstrap_lib"
bootstrap_source_common_lib "" ||
  llama_fatal "failed to source installer common library"
seed_base=$(installer_current_seed_base 2>/dev/null || installer_seed_base "")
bootstrap_source_common_support_libs "$seed_base" "$tmp_env_dir" fetch hook target ||
  llama_fatal "failed to source installer target support libraries"
installer_ensure_context_loaded "$seed_base"

llama_stream_target_output() {
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

run_llama_install_in_target() {
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
  ) 2>&1 | llama_stream_target_output "$output" "$stream_emit"
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

installer_selected_class_reference_is_selected addon/devops 2>/dev/null || exit 0
[ "${INSTALLER_HOST_VARIANT:-}" = desktop ] ||
  llama_fatal "addon/devops llama.cpp provisioning is restricted to the desktop role"

host_env=${INSTALLER_LATE_HOST_ENV:-/tmp/install-env-late/host.env}
[ -r "$host_env" ] ||
  installer_fetch_host_env "$seed_base" "$(installer_resolve_host_profile "")" "$host_env" 0600
# shellcheck disable=SC1090,SC1091
. "$host_env"

llama_validate_policy
llama_validate_release_class_selection

target_helper=/tmp/installer-llama
target_helper_host="${target_root}${target_helper}"
target_profile=/tmp/llama-install.env
target_profile_host="${target_root}${target_profile}"
helper_tmp="${tmp_env_dir}/installer-llama.$$"
target_archive_helper=/tmp/installer-ai-runtime-archive.py
target_archive_helper_host="${target_root}${target_archive_helper}"
archive_helper_tmp="${tmp_env_dir}/installer-ai-runtime-archive.py.$$"
target_runtime_template=/tmp/llama.conf.tmpl
target_runtime_template_host="${target_root}${target_runtime_template}"
runtime_template_tmp="${tmp_env_dir}/llama.conf.tmpl.$$"
target_wrapper_source=/tmp/llama-launcher
target_wrapper_source_host="${target_root}${target_wrapper_source}"
wrapper_source_tmp="${tmp_env_dir}/llama-launcher.$$"

install -d -m 0700 "$tmp_env_dir"
bootstrap_fetch_seed_file "$seed_base" "$(installer_repo_join_var DIR_SCRIPTS_LATE llama.sh)" "$helper_tmp" 0600 "llama.cpp late helper"
install -d -m 1777 "${target_root}/tmp"
install -m 0700 "$helper_tmp" "$target_helper_host"
chown 0:0 "$target_helper_host"
rm -f -- "$helper_tmp"
bootstrap_fetch_seed_file "$seed_base" "$(installer_repo_join_var DIR_SCRIPTS_LATE ai-runtime-archive.py)" "$archive_helper_tmp" 0600 "AI runtime archive validator"
install -m 0700 "$archive_helper_tmp" "$target_archive_helper_host"
chown 0:0 "$target_archive_helper_host"
rm -f -- "$archive_helper_tmp"
bootstrap_fetch_seed_file "$seed_base" "$(installer_repo_join_var DIR_HOOKS_TARGET etc/llama/llama.conf.tmpl)" "$runtime_template_tmp" 0600 "llama.cpp runtime configuration template"
install -m 0600 "$runtime_template_tmp" "$target_runtime_template_host"
chown 0:0 "$target_runtime_template_host"
rm -f -- "$runtime_template_tmp"
bootstrap_fetch_seed_file "$seed_base" "$(installer_repo_join_var DIR_HOOKS_TARGET data/llama/lib/llama)" "$wrapper_source_tmp" 0600 "llama.cpp launcher"
install -m 0600 "$wrapper_source_tmp" "$target_wrapper_source_host"
chown 0:0 "$target_wrapper_source_host"
rm -f -- "$wrapper_source_tmp"

cleanup_target_install_assets() {
  rm -f -- "$helper_tmp" "$archive_helper_tmp" "$runtime_template_tmp" "$wrapper_source_tmp" \
    "$target_helper_host" "$target_archive_helper_host" "$target_profile_host" \
    "$target_runtime_template_host" "$target_wrapper_source_host"
}
trap cleanup_target_install_assets 0
trap 'cleanup_target_install_assets; exit 1' 1 2 15

umask 077
{
  write_shell_config_var LLAMA_RELEASE_URL "$LLAMA_RELEASE_URL"
  write_shell_config_var LLAMA_RELEASE_SHA256 "$LLAMA_RELEASE_SHA256"
  write_shell_config_var LLAMA_RELEASE_BYTES "$LLAMA_RELEASE_BYTES"
  write_shell_config_var LLAMA_RELEASE_MAXIMUM_EXTRACTED_BYTES "$LLAMA_RELEASE_MAXIMUM_EXTRACTED_BYTES"
  write_shell_config_var LLAMA_RELEASE_MAXIMUM_MEMBERS "$LLAMA_RELEASE_MAXIMUM_MEMBERS"
  write_shell_config_var LLAMA_RELEASE_ARCHIVE_ROOT "$LLAMA_RELEASE_ARCHIVE_ROOT"
  write_shell_config_var LLAMA_RELEASE_REQUIRED_CLASS "$LLAMA_RELEASE_REQUIRED_CLASS"
  write_shell_config_var LLAMA_ROOT "$LLAMA_ROOT"
  write_shell_config_var LLAMA_BINARY_DIR "$LLAMA_BINARY_DIR"
  write_shell_config_var LLAMA_METADATA_DIR "$LLAMA_METADATA_DIR"
  write_shell_config_var LLAMA_SHARE_DIR "$LLAMA_SHARE_DIR"
  write_shell_config_var LLAMA_WRAPPER_PATH "$LLAMA_WRAPPER_PATH"
  write_shell_config_var LLAMA_MODEL_DIR "$LLAMA_MODEL_DIR"
  write_shell_config_var LLAMA_FORCE_DOWNLOAD "$LLAMA_FORCE_DOWNLOAD"
  write_shell_config_var LLAMA_DOWNLOAD_RETRIES "$LLAMA_DOWNLOAD_RETRIES"
  write_shell_config_var LLAMA_DOWNLOAD_CONNECT_TIMEOUT_SECONDS "$LLAMA_DOWNLOAD_CONNECT_TIMEOUT_SECONDS"
  write_shell_config_var LLAMA_DOWNLOAD_MAX_TIME_SECONDS "$LLAMA_DOWNLOAD_MAX_TIME_SECONDS"
  write_shell_config_var LLAMA_DEFAULT_MODEL "$LLAMA_DEFAULT_MODEL"
  write_shell_config_var LLAMA_DOWNLOAD_URL "$LLAMA_DOWNLOAD_URL"
  write_shell_config_var LLAMA_MODEL_SHA256 "$LLAMA_MODEL_SHA256"
  write_shell_config_var LLAMA_MODEL_BYTES "$LLAMA_MODEL_BYTES"
  write_shell_config_var LLAMA_RUNTIME_CONTEXT "$LLAMA_RUNTIME_CONTEXT"
  write_shell_config_var LLAMA_RUNTIME_BATCH "$LLAMA_RUNTIME_BATCH"
  write_shell_config_var LLAMA_RUNTIME_UBATCH "$LLAMA_RUNTIME_UBATCH"
  write_shell_config_var LLAMA_RUNTIME_THREADS "$LLAMA_RUNTIME_THREADS"
  write_shell_config_var LLAMA_RUNTIME_THREADS_BATCH "$LLAMA_RUNTIME_THREADS_BATCH"
  write_shell_config_var LLAMA_RUNTIME_GPU_LAYERS "$LLAMA_RUNTIME_GPU_LAYERS"
  write_shell_config_var LLAMA_RUNTIME_KV_OFFLOAD "$LLAMA_RUNTIME_KV_OFFLOAD"
  write_shell_config_var LLAMA_RUNTIME_PARALLEL "$LLAMA_RUNTIME_PARALLEL"
  write_shell_config_var LLAMA_SERVER_HOST "$LLAMA_SERVER_HOST"
  write_shell_config_var LLAMA_SERVER_PORT "$LLAMA_SERVER_PORT"
  write_shell_config_var LLAMA_STRICT_RESOURCES "$LLAMA_STRICT_RESOURCES"
  write_shell_config_var LLAMA_MIN_MEMORY_MIB "$LLAMA_MIN_MEMORY_MIB"
  write_shell_config_var LLAMA_MIN_CPU_CORES "$LLAMA_MIN_CPU_CORES"
} >"$target_profile_host"
chmod 0600 "$target_profile_host"
chown 0:0 "$target_profile_host"

run_llama_install_in_target "download and install selected llama.cpp runtime" \
  "$target_helper" --target-install "$target_profile"

# The target helper verifies every installed artifact before returning.
rm -f -- "$target_helper_host" "$target_archive_helper_host" "$target_profile_host" \
  "$target_runtime_template_host" "$target_wrapper_source_host"
llama_info "installed profile-selected llama.cpp release for addon/devops"
