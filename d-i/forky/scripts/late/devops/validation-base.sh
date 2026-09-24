#!/bin/sh
# Sourced installer module; edit this file directly.

devops_fatal() {
  printf 'fatal: %s\n' "$*" >&2
  exit 1
}

devops_info() {
  printf '[late:devops] %s\n' "$*" >&2
}

devops_assert_target_metadata() (
  expected_metadata=$1
  target_host_path=$2
  metadata_label=$3
  metadata_target_root=${target_root%/}

  case "$metadata_target_root" in
    ''|/)
      devops_fatal "unsafe installation target for metadata inspection: ${target_root:-unset}"
      ;;
  esac
  case "$target_host_path" in
    "$metadata_target_root"/*)
      metadata_target_path=${target_host_path#"$metadata_target_root"}
      ;;
    *)
      devops_fatal "${metadata_label} path is outside the installation target: $target_host_path"
      ;;
  esac
  devops_validate_abs_path "${metadata_label} target path" "$metadata_target_path"
  actual_metadata=$(chroot "$metadata_target_root" \
    /usr/bin/find -P "$metadata_target_path" -maxdepth 0 -printf '%U:%G:%m') ||
    devops_fatal "${metadata_label} metadata is unavailable: $target_host_path"
  [ "$actual_metadata" = "$expected_metadata" ] ||
    devops_fatal "${metadata_label} has unsafe ownership or mode: $target_host_path"
)

devops_validate_abs_path() {
  label=$1
  path_value=$2

  case "$path_value" in
    /*) ;;
    *) devops_fatal "${label} must be absolute: ${path_value:-unset}" ;;
  esac
  case "$path_value" in
    /|*..*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/-]*)
      devops_fatal "${label} contains unsupported path syntax: $path_value"
      ;;
  esac
}

devops_validate_aptly_signing_key_path() {
  label=$1
  path_value=$2

  devops_validate_abs_path "$label" "$path_value"
  case "$path_value" in
    /aptly-signing/*)
      aptly_signing_key_name=${path_value#/aptly-signing/}
      ;;
    *)
      devops_fatal "${label} must name a file directly below /aptly-signing: $path_value"
      ;;
  esac
  case "$aptly_signing_key_name" in
    ''|.|..|*/*)
      devops_fatal "${label} must name one file directly below /aptly-signing: $path_value"
      ;;
  esac
  [ "${#aptly_signing_key_name}" -le 255 ] ||
    devops_fatal "${label} filename exceeds 255 characters"
  unset aptly_signing_key_name
}

devops_validate_account_name() {
  case "${1:-}" in
    [abcdefghijklmnopqrstuvwxyz_]*)
      ;;
    *)
      devops_fatal "ACCOUNT_USERNAME must start with a lowercase letter or underscore"
      ;;
  esac
  case "$1" in
    *[!abcdefghijklmnopqrstuvwxyz0123456789_-]*)
      devops_fatal "ACCOUNT_USERNAME contains unsupported characters: $1"
      ;;
  esac
}

devops_validate_positive_integer() {
  label=$1
  value=$2

  case "$value" in
    ''|*[!0123456789]*)
      devops_fatal "${label} must be a positive integer: ${value:-unset}"
      ;;
  esac
  [ "$value" -gt 0 ] ||
    devops_fatal "${label} must be greater than zero: $value"
}

devops_validate_source_build_flag() {
  label=$1
  value=$2

  case "$value" in
    0|1) ;;
    *) devops_fatal "${label} must be 0 or 1: ${value:-unset}" ;;
  esac
}

devops_validate_cargo_token() {
  label=$1
  value=$2

  if ! printf '%s\n' "$value" | LC_ALL=C grep -Eq '^[a-z0-9][a-z0-9_.-]*$'; then
    devops_fatal "${label} must be a lowercase Cargo/rustc token: ${value:-unset}"
  fi
}

devops_validate_cargo_policy() {
  : "${DEVOPS_CARGO_RUSTC_WRAPPER:?DEVOPS_CARGO_RUSTC_WRAPPER must be set before DevOps provisioning}"
  : "${DEVOPS_CARGO_TARGET_TRIPLE:?DEVOPS_CARGO_TARGET_TRIPLE must be set before DevOps provisioning}"
  : "${DEVOPS_CARGO_TARGET_LINKER:?DEVOPS_CARGO_TARGET_LINKER must be set before DevOps provisioning}"
  : "${DEVOPS_CARGO_TARGET_CPU:?DEVOPS_CARGO_TARGET_CPU must be set before DevOps provisioning}"
  : "${DEVOPS_CARGO_LINKER_ARGUMENT:?DEVOPS_CARGO_LINKER_ARGUMENT must be set before DevOps provisioning}"

  [ "$DEVOPS_CARGO_RUSTC_WRAPPER" = sccache ] ||
    devops_fatal "DEVOPS_CARGO_RUSTC_WRAPPER must remain sccache"
  [ "$DEVOPS_CARGO_TARGET_TRIPLE" = x86_64-unknown-linux-gnu ] ||
    devops_fatal "DEVOPS_CARGO_TARGET_TRIPLE must remain x86_64-unknown-linux-gnu"
  [ "$DEVOPS_CARGO_TARGET_LINKER" = clang-24 ] ||
    devops_fatal "DEVOPS_CARGO_TARGET_LINKER must remain clang-24"
  [ "$DEVOPS_CARGO_LINKER_ARGUMENT" = -fuse-ld=mold ] ||
    devops_fatal "DEVOPS_CARGO_LINKER_ARGUMENT must remain -fuse-ld=mold"
  devops_validate_cargo_token \
    "DEVOPS_CARGO_TARGET_CPU" \
    "$DEVOPS_CARGO_TARGET_CPU"
}

devops_validate_bazel_size() {
  label=$1
  value=$2

  if ! printf '%s\n' "$value" | LC_ALL=C grep -Eq '^[1-9][0-9]*[KMGT]?$'; then
    devops_fatal "${label} must be a positive Bazel size with an optional K/M/G/T suffix: ${value:-unset}"
  fi
}

devops_validate_bazel_duration() {
  label=$1
  value=$2

  if ! printf '%s\n' "$value" | LC_ALL=C grep -Eq '^[1-9][0-9]*[smhd]$'; then
    devops_fatal "${label} must be a positive Bazel duration ending in s/m/h/d: ${value:-unset}"
  fi
}

devops_validate_relative_path() {
  label=$1
  path_value=$2

  case "$path_value" in
    ''|/*|.|*/.|*..*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/-]*)
      devops_fatal "${label} contains unsupported relative path syntax: ${path_value:-unset}"
      ;;
  esac
}

devops_validate_semantic_version() {
  label=$1
  value=$2

  if ! printf '%s\n' "$value" | LC_ALL=C grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$'; then
    devops_fatal "${label} must be a semantic version: ${value:-unset}"
  fi
}

devops_validate_lower_hex() {
  label=$1
  value=$2
  expected_length=$3

  [ "${#value}" -eq "$expected_length" ] ||
    devops_fatal "${label} must contain exactly ${expected_length} lowercase hexadecimal characters"
  case "$value" in
    *[!0123456789abcdef]*)
      devops_fatal "${label} must contain exactly ${expected_length} lowercase hexadecimal characters"
      ;;
  esac
}

devops_validate_openpgp_fingerprint() {
  label=$1
  value=$2

  case "${#value}" in
    40|64) ;;
    *)
      devops_fatal "${label} must contain 40 or 64 uppercase hexadecimal characters"
      ;;
  esac
  case "$value" in
    *[!0123456789ABCDEF]*)
      devops_fatal "${label} must contain 40 or 64 uppercase hexadecimal characters"
      ;;
  esac
}

devops_validate_archive_file_list() {
  label=$1
  file_list=$2
  seen_files=

  [ -n "$file_list" ] || devops_fatal "${label} must not be empty"
  for archive_file in $file_list; do
    devops_validate_relative_path "$label" "$archive_file"
    case " $seen_files " in
      *" $archive_file "*)
        devops_fatal "${label} contains a duplicate archive path: $archive_file"
        ;;
    esac
    seen_files="${seen_files}${seen_files:+ }${archive_file}"
  done
  unset archive_file seen_files
}

devops_validate_node_release() {
  expected_major=$1
  major=$2
  version=$3
  url=$4
  sha256=$5
  expected_bytes=$6
  archive_filename=$7
  archive_root=$8
  install_root=$9
  binary_path=${10}

  [ "$major" = "$expected_major" ] ||
    devops_fatal "Node ${expected_major} policy has an unexpected major version: $major"
  if ! printf '%s\n' "$version" |
    LC_ALL=C grep -Eq "^v${expected_major}\.[0-9]+\.[0-9]+$"
  then
    devops_fatal "Node ${expected_major} release must be a matching v-prefixed semantic version: $version"
  fi
  [ "$archive_filename" = "node-${version}-linux-x64.tar.xz" ] ||
    devops_fatal "Node ${expected_major} archive filename does not match its version"
  [ "$archive_root" = "node-${version}-linux-x64" ] ||
    devops_fatal "Node ${expected_major} archive root does not match its version"
  [ "$url" = "https://nodejs.org/dist/${version}/${archive_filename}" ] ||
    devops_fatal "Node ${expected_major} URL must identify its official Linux x64 release archive"
  devops_validate_lower_hex "Node ${expected_major} SHA-256" "$sha256" 64
  devops_validate_positive_integer "Node ${expected_major} exact bytes" "$expected_bytes"
  devops_validate_abs_path "Node ${expected_major} install root" "$install_root"
  devops_validate_abs_path "Node ${expected_major} binary path" "$binary_path"
  [ "$install_root" = "/usr/local/lib/node-${expected_major}" ] ||
    devops_fatal "Node ${expected_major} install root must remain /usr/local/lib/node-${expected_major}"
  [ "$binary_path" = "${install_root}/bin/node" ] ||
    devops_fatal "Node ${expected_major} binary path must remain ${install_root}/bin/node"
}

