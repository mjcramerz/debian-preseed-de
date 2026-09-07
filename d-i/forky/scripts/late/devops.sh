#!/bin/sh
set -eu

target_root=${1:-/target}
[ -d "$target_root" ] || exit 0

devops_codex_host_log_dir=/var/log/managed/openai/codex

devops_fatal() {
  printf 'fatal: %s\n' "$*" >&2
  exit 1
}

devops_info() {
  printf '[late:devops] %s\n' "$*" >&2
}

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

devops_validate_upstream_tool_policy() {
  : "${DEVOPS_UPSTREAM_POLICY_SCHEMA:?DEVOPS_UPSTREAM_POLICY_SCHEMA must be set before DevOps provisioning}"
  : "${DEVOPS_UPSTREAM_ARCHITECTURE:?DEVOPS_UPSTREAM_ARCHITECTURE must be set before DevOps provisioning}"
  : "${DEVOPS_UPSTREAM_DOWNLOAD_TIMEOUT_SECONDS:?DEVOPS_UPSTREAM_DOWNLOAD_TIMEOUT_SECONDS must be set before DevOps provisioning}"
  : "${DEVOPS_UPSTREAM_NPM_TIMEOUT_SECONDS:?DEVOPS_UPSTREAM_NPM_TIMEOUT_SECONDS must be set before DevOps provisioning}"
  : "${DEVOPS_UPSTREAM_MAKE_TIMEOUT_SECONDS:?DEVOPS_UPSTREAM_MAKE_TIMEOUT_SECONDS must be set before DevOps provisioning}"
  : "${DEVOPS_UPSTREAM_VERIFY_TIMEOUT_SECONDS:?DEVOPS_UPSTREAM_VERIFY_TIMEOUT_SECONDS must be set before DevOps provisioning}"
  : "${DEVOPS_UPSTREAM_MAX_ARCHIVE_MEMBERS:?DEVOPS_UPSTREAM_MAX_ARCHIVE_MEMBERS must be set before DevOps provisioning}"
  : "${DEVOPS_UPSTREAM_MAX_EXTRACTED_BYTES:?DEVOPS_UPSTREAM_MAX_EXTRACTED_BYTES must be set before DevOps provisioning}"

  : "${DEVOPS_NODE_22_MAJOR:?DEVOPS_NODE_22_MAJOR must be set before DevOps provisioning}"
  : "${DEVOPS_NODE_22_VERSION:?DEVOPS_NODE_22_VERSION must be set before DevOps provisioning}"
  : "${DEVOPS_NODE_22_URL:?DEVOPS_NODE_22_URL must be set before DevOps provisioning}"
  : "${DEVOPS_NODE_22_SHA256:?DEVOPS_NODE_22_SHA256 must be set before DevOps provisioning}"
  : "${DEVOPS_NODE_22_BYTES:?DEVOPS_NODE_22_BYTES must be set before DevOps provisioning}"
  : "${DEVOPS_NODE_22_ARCHIVE_FILENAME:?DEVOPS_NODE_22_ARCHIVE_FILENAME must be set before DevOps provisioning}"
  : "${DEVOPS_NODE_22_ARCHIVE_ROOT:?DEVOPS_NODE_22_ARCHIVE_ROOT must be set before DevOps provisioning}"
  : "${DEVOPS_NODE_22_INSTALL_ROOT:?DEVOPS_NODE_22_INSTALL_ROOT must be set before DevOps provisioning}"
  : "${DEVOPS_NODE_22_BINARY_PATH:?DEVOPS_NODE_22_BINARY_PATH must be set before DevOps provisioning}"
  : "${DEVOPS_NODE_24_MAJOR:?DEVOPS_NODE_24_MAJOR must be set before DevOps provisioning}"
  : "${DEVOPS_NODE_24_VERSION:?DEVOPS_NODE_24_VERSION must be set before DevOps provisioning}"
  : "${DEVOPS_NODE_24_URL:?DEVOPS_NODE_24_URL must be set before DevOps provisioning}"
  : "${DEVOPS_NODE_24_SHA256:?DEVOPS_NODE_24_SHA256 must be set before DevOps provisioning}"
  : "${DEVOPS_NODE_24_BYTES:?DEVOPS_NODE_24_BYTES must be set before DevOps provisioning}"
  : "${DEVOPS_NODE_24_ARCHIVE_FILENAME:?DEVOPS_NODE_24_ARCHIVE_FILENAME must be set before DevOps provisioning}"
  : "${DEVOPS_NODE_24_ARCHIVE_ROOT:?DEVOPS_NODE_24_ARCHIVE_ROOT must be set before DevOps provisioning}"
  : "${DEVOPS_NODE_24_INSTALL_ROOT:?DEVOPS_NODE_24_INSTALL_ROOT must be set before DevOps provisioning}"
  : "${DEVOPS_NODE_24_BINARY_PATH:?DEVOPS_NODE_24_BINARY_PATH must be set before DevOps provisioning}"
  : "${DEVOPS_NODE_26_MAJOR:?DEVOPS_NODE_26_MAJOR must be set before DevOps provisioning}"
  : "${DEVOPS_NODE_26_VERSION:?DEVOPS_NODE_26_VERSION must be set before DevOps provisioning}"
  : "${DEVOPS_NODE_26_URL:?DEVOPS_NODE_26_URL must be set before DevOps provisioning}"
  : "${DEVOPS_NODE_26_SHA256:?DEVOPS_NODE_26_SHA256 must be set before DevOps provisioning}"
  : "${DEVOPS_NODE_26_BYTES:?DEVOPS_NODE_26_BYTES must be set before DevOps provisioning}"
  : "${DEVOPS_NODE_26_ARCHIVE_FILENAME:?DEVOPS_NODE_26_ARCHIVE_FILENAME must be set before DevOps provisioning}"
  : "${DEVOPS_NODE_26_ARCHIVE_ROOT:?DEVOPS_NODE_26_ARCHIVE_ROOT must be set before DevOps provisioning}"
  : "${DEVOPS_NODE_26_INSTALL_ROOT:?DEVOPS_NODE_26_INSTALL_ROOT must be set before DevOps provisioning}"
  : "${DEVOPS_NODE_26_BINARY_PATH:?DEVOPS_NODE_26_BINARY_PATH must be set before DevOps provisioning}"

  : "${DEVOPS_DENO_VERSION:?DEVOPS_DENO_VERSION must be set before DevOps provisioning}"
  : "${DEVOPS_DENO_URL:?DEVOPS_DENO_URL must be set before DevOps provisioning}"
  : "${DEVOPS_DENO_SHA256:?DEVOPS_DENO_SHA256 must be set before DevOps provisioning}"
  : "${DEVOPS_DENO_BYTES:?DEVOPS_DENO_BYTES must be set before DevOps provisioning}"
  : "${DEVOPS_DENO_ARCHITECTURE:?DEVOPS_DENO_ARCHITECTURE must be set before DevOps provisioning}"
  : "${DEVOPS_DENO_ARCHIVE_FILENAME:?DEVOPS_DENO_ARCHIVE_FILENAME must be set before DevOps provisioning}"
  : "${DEVOPS_DENO_ARCHIVE_FILES:?DEVOPS_DENO_ARCHIVE_FILES must be set before DevOps provisioning}"
  : "${DEVOPS_DENO_INSTALL_ROOT:?DEVOPS_DENO_INSTALL_ROOT must be set before DevOps provisioning}"
  : "${DEVOPS_DENO_BINARY_PATH:?DEVOPS_DENO_BINARY_PATH must be set before DevOps provisioning}"

  : "${DEVOPS_YT_DLP_VERSION:?DEVOPS_YT_DLP_VERSION must be set before DevOps provisioning}"
  : "${DEVOPS_YT_DLP_URL:?DEVOPS_YT_DLP_URL must be set before DevOps provisioning}"
  : "${DEVOPS_YT_DLP_SHA256:?DEVOPS_YT_DLP_SHA256 must be set before DevOps provisioning}"
  : "${DEVOPS_YT_DLP_BYTES:?DEVOPS_YT_DLP_BYTES must be set before DevOps provisioning}"
  : "${DEVOPS_YT_DLP_ARCHITECTURE:?DEVOPS_YT_DLP_ARCHITECTURE must be set before DevOps provisioning}"
  : "${DEVOPS_YT_DLP_ARCHIVE_FILENAME:?DEVOPS_YT_DLP_ARCHIVE_FILENAME must be set before DevOps provisioning}"
  : "${DEVOPS_YT_DLP_INSTALL_ROOT:?DEVOPS_YT_DLP_INSTALL_ROOT must be set before DevOps provisioning}"
  : "${DEVOPS_YT_DLP_BINARY_PATH:?DEVOPS_YT_DLP_BINARY_PATH must be set before DevOps provisioning}"
  : "${DEVOPS_YT_DLP_PAYLOAD_PATH:?DEVOPS_YT_DLP_PAYLOAD_PATH must be set before DevOps provisioning}"

  : "${DEVOPS_RUSTUP_VERSION:?DEVOPS_RUSTUP_VERSION must be set before DevOps provisioning}"
  : "${DEVOPS_RUSTUP_URL:?DEVOPS_RUSTUP_URL must be set before DevOps provisioning}"
  : "${DEVOPS_RUSTUP_SHA256:?DEVOPS_RUSTUP_SHA256 must be set before DevOps provisioning}"
  : "${DEVOPS_RUSTUP_BYTES:?DEVOPS_RUSTUP_BYTES must be set before DevOps provisioning}"
  : "${DEVOPS_RUSTUP_TARGET_TRIPLE:?DEVOPS_RUSTUP_TARGET_TRIPLE must be set before DevOps provisioning}"
  : "${DEVOPS_RUSTUP_INSTALL_ROOT:?DEVOPS_RUSTUP_INSTALL_ROOT must be set before DevOps provisioning}"
  : "${DEVOPS_RUSTUP_BINARY_PATH:?DEVOPS_RUSTUP_BINARY_PATH must be set before DevOps provisioning}"
  : "${DEVOPS_RUSTUP_TOOLCHAIN:?DEVOPS_RUSTUP_TOOLCHAIN must be set before DevOps provisioning}"
  : "${DEVOPS_DOTSLASH_SOURCE_BUILD:?DEVOPS_DOTSLASH_SOURCE_BUILD must be set before DevOps provisioning}"
  : "${DEVOPS_DOTSLASH_VERSION:?DEVOPS_DOTSLASH_VERSION must be set before DevOps provisioning}"
  : "${DEVOPS_DOTSLASH_REPOSITORY_URL:?DEVOPS_DOTSLASH_REPOSITORY_URL must be set before DevOps provisioning}"
  : "${DEVOPS_DOTSLASH_COMMIT:?DEVOPS_DOTSLASH_COMMIT must be set before DevOps provisioning}"
  : "${DEVOPS_DOTSLASH_URL:?DEVOPS_DOTSLASH_URL must be set before DevOps provisioning}"
  : "${DEVOPS_DOTSLASH_SHA256:?DEVOPS_DOTSLASH_SHA256 must be set before DevOps provisioning}"
  : "${DEVOPS_DOTSLASH_BYTES:?DEVOPS_DOTSLASH_BYTES must be set before DevOps provisioning}"
  : "${DEVOPS_DOTSLASH_ARCHITECTURE:?DEVOPS_DOTSLASH_ARCHITECTURE must be set before DevOps provisioning}"
  : "${DEVOPS_DOTSLASH_ARCHIVE_FILENAME:?DEVOPS_DOTSLASH_ARCHIVE_FILENAME must be set before DevOps provisioning}"
  : "${DEVOPS_DOTSLASH_ARCHIVE_FILES:?DEVOPS_DOTSLASH_ARCHIVE_FILES must be set before DevOps provisioning}"
  : "${DEVOPS_UV_SOURCE_BUILD:?DEVOPS_UV_SOURCE_BUILD must be set before DevOps provisioning}"
  : "${DEVOPS_UV_VERSION:?DEVOPS_UV_VERSION must be set before DevOps provisioning}"
  : "${DEVOPS_UV_URL:?DEVOPS_UV_URL must be set before DevOps provisioning}"
  : "${DEVOPS_UV_SHA256:?DEVOPS_UV_SHA256 must be set before DevOps provisioning}"
  : "${DEVOPS_UV_BYTES:?DEVOPS_UV_BYTES must be set before DevOps provisioning}"
  : "${DEVOPS_UV_ARCHITECTURE:?DEVOPS_UV_ARCHITECTURE must be set before DevOps provisioning}"
  : "${DEVOPS_UV_ARCHIVE_FILENAME:?DEVOPS_UV_ARCHIVE_FILENAME must be set before DevOps provisioning}"
  : "${DEVOPS_UV_ARCHIVE_ROOT:?DEVOPS_UV_ARCHIVE_ROOT must be set before DevOps provisioning}"
  : "${DEVOPS_UV_ARCHIVE_FILES:?DEVOPS_UV_ARCHIVE_FILES must be set before DevOps provisioning}"

  : "${DEVOPS_ANSIBLE_CORE_VERSION:?DEVOPS_ANSIBLE_CORE_VERSION must be set before DevOps provisioning}"
  : "${DEVOPS_ANSIBLE_CORE_URL:?DEVOPS_ANSIBLE_CORE_URL must be set before DevOps provisioning}"
  : "${DEVOPS_ANSIBLE_CORE_SHA256:?DEVOPS_ANSIBLE_CORE_SHA256 must be set before DevOps provisioning}"
  : "${DEVOPS_ANSIBLE_CORE_BYTES:?DEVOPS_ANSIBLE_CORE_BYTES must be set before DevOps provisioning}"
  : "${DEVOPS_ANSIBLE_CORE_ARCHITECTURE:?DEVOPS_ANSIBLE_CORE_ARCHITECTURE must be set before DevOps provisioning}"
  : "${DEVOPS_ANSIBLE_CORE_ARCHIVE_FILENAME:?DEVOPS_ANSIBLE_CORE_ARCHIVE_FILENAME must be set before DevOps provisioning}"
  : "${DEVOPS_ANSIBLE_CORE_PACKAGE_ROOTS:?DEVOPS_ANSIBLE_CORE_PACKAGE_ROOTS must be set before DevOps provisioning}"
  : "${DEVOPS_ANSIBLE_CORE_DIST_INFO_ROOT:?DEVOPS_ANSIBLE_CORE_DIST_INFO_ROOT must be set before DevOps provisioning}"
  : "${DEVOPS_ANSIBLE_CORE_MAX_ARCHIVE_MEMBERS:?DEVOPS_ANSIBLE_CORE_MAX_ARCHIVE_MEMBERS must be set before DevOps provisioning}"
  : "${DEVOPS_ANSIBLE_CORE_MAX_EXTRACTED_BYTES:?DEVOPS_ANSIBLE_CORE_MAX_EXTRACTED_BYTES must be set before DevOps provisioning}"
  : "${DEVOPS_ANSIBLE_CORE_INSTALL_ROOT:?DEVOPS_ANSIBLE_CORE_INSTALL_ROOT must be set before DevOps provisioning}"
  : "${DEVOPS_ANSIBLE_CORE_BINARY_PATH:?DEVOPS_ANSIBLE_CORE_BINARY_PATH must be set before DevOps provisioning}"

  : "${DEVOPS_OPENTOFU_VERSION:?DEVOPS_OPENTOFU_VERSION must be set before DevOps provisioning}"
  : "${DEVOPS_OPENTOFU_URL:?DEVOPS_OPENTOFU_URL must be set before DevOps provisioning}"
  : "${DEVOPS_OPENTOFU_SHA256:?DEVOPS_OPENTOFU_SHA256 must be set before DevOps provisioning}"
  : "${DEVOPS_OPENTOFU_BYTES:?DEVOPS_OPENTOFU_BYTES must be set before DevOps provisioning}"
  : "${DEVOPS_OPENTOFU_ARCHITECTURE:?DEVOPS_OPENTOFU_ARCHITECTURE must be set before DevOps provisioning}"
  : "${DEVOPS_OPENTOFU_ARCHIVE_FILENAME:?DEVOPS_OPENTOFU_ARCHIVE_FILENAME must be set before DevOps provisioning}"
  : "${DEVOPS_OPENTOFU_ARCHIVE_FILES:?DEVOPS_OPENTOFU_ARCHIVE_FILES must be set before DevOps provisioning}"
  : "${DEVOPS_OPENTOFU_INSTALL_ROOT:?DEVOPS_OPENTOFU_INSTALL_ROOT must be set before DevOps provisioning}"
  : "${DEVOPS_OPENTOFU_BINARY_PATH:?DEVOPS_OPENTOFU_BINARY_PATH must be set before DevOps provisioning}"

  : "${DEVOPS_TERRAFORM_VERSION:?DEVOPS_TERRAFORM_VERSION must be set before DevOps provisioning}"
  : "${DEVOPS_TERRAFORM_URL:?DEVOPS_TERRAFORM_URL must be set before DevOps provisioning}"
  : "${DEVOPS_TERRAFORM_SHA256:?DEVOPS_TERRAFORM_SHA256 must be set before DevOps provisioning}"
  : "${DEVOPS_TERRAFORM_BYTES:?DEVOPS_TERRAFORM_BYTES must be set before DevOps provisioning}"
  : "${DEVOPS_TERRAFORM_ARCHITECTURE:?DEVOPS_TERRAFORM_ARCHITECTURE must be set before DevOps provisioning}"
  : "${DEVOPS_TERRAFORM_ARCHIVE_FILENAME:?DEVOPS_TERRAFORM_ARCHIVE_FILENAME must be set before DevOps provisioning}"
  : "${DEVOPS_TERRAFORM_ARCHIVE_FILES:?DEVOPS_TERRAFORM_ARCHIVE_FILES must be set before DevOps provisioning}"
  : "${DEVOPS_TERRAFORM_INSTALL_ROOT:?DEVOPS_TERRAFORM_INSTALL_ROOT must be set before DevOps provisioning}"
  : "${DEVOPS_TERRAFORM_BINARY_PATH:?DEVOPS_TERRAFORM_BINARY_PATH must be set before DevOps provisioning}"

  : "${DEVOPS_PACKER_VERSION:?DEVOPS_PACKER_VERSION must be set before DevOps provisioning}"
  : "${DEVOPS_PACKER_URL:?DEVOPS_PACKER_URL must be set before DevOps provisioning}"
  : "${DEVOPS_PACKER_SHA256:?DEVOPS_PACKER_SHA256 must be set before DevOps provisioning}"
  : "${DEVOPS_PACKER_BYTES:?DEVOPS_PACKER_BYTES must be set before DevOps provisioning}"
  : "${DEVOPS_PACKER_ARCHITECTURE:?DEVOPS_PACKER_ARCHITECTURE must be set before DevOps provisioning}"
  : "${DEVOPS_PACKER_ARCHIVE_FILENAME:?DEVOPS_PACKER_ARCHIVE_FILENAME must be set before DevOps provisioning}"
  : "${DEVOPS_PACKER_ARCHIVE_FILES:?DEVOPS_PACKER_ARCHIVE_FILES must be set before DevOps provisioning}"
  : "${DEVOPS_PACKER_INSTALL_ROOT:?DEVOPS_PACKER_INSTALL_ROOT must be set before DevOps provisioning}"
  : "${DEVOPS_PACKER_BINARY_PATH:?DEVOPS_PACKER_BINARY_PATH must be set before DevOps provisioning}"
  : "${DEVOPS_PACKER_INIT_TIMEOUT_SECONDS:?DEVOPS_PACKER_INIT_TIMEOUT_SECONDS must be set before DevOps provisioning}"

  : "${DEVOPS_WRANGLER_VERSION:?DEVOPS_WRANGLER_VERSION must be set before DevOps provisioning}"
  : "${DEVOPS_WRANGLER_URL:?DEVOPS_WRANGLER_URL must be set before DevOps provisioning}"
  : "${DEVOPS_WRANGLER_SHA512:?DEVOPS_WRANGLER_SHA512 must be set before DevOps provisioning}"
  : "${DEVOPS_WRANGLER_NPM_INTEGRITY:?DEVOPS_WRANGLER_NPM_INTEGRITY must be set before DevOps provisioning}"
  : "${DEVOPS_WRANGLER_BYTES:?DEVOPS_WRANGLER_BYTES must be set before DevOps provisioning}"
  : "${DEVOPS_WRANGLER_ARCHITECTURE:?DEVOPS_WRANGLER_ARCHITECTURE must be set before DevOps provisioning}"
  : "${DEVOPS_WRANGLER_ARCHIVE_FILENAME:?DEVOPS_WRANGLER_ARCHIVE_FILENAME must be set before DevOps provisioning}"
  : "${DEVOPS_WRANGLER_ARCHIVE_ROOT:?DEVOPS_WRANGLER_ARCHIVE_ROOT must be set before DevOps provisioning}"
  : "${DEVOPS_WRANGLER_PACKAGE_NAME:?DEVOPS_WRANGLER_PACKAGE_NAME must be set before DevOps provisioning}"
  : "${DEVOPS_WRANGLER_NODE_REQUIREMENT:?DEVOPS_WRANGLER_NODE_REQUIREMENT must be set before DevOps provisioning}"
  : "${DEVOPS_WRANGLER_NODE_ROOT:?DEVOPS_WRANGLER_NODE_ROOT must be set before DevOps provisioning}"
  : "${DEVOPS_WRANGLER_NPM_REGISTRY_URL:?DEVOPS_WRANGLER_NPM_REGISTRY_URL must be set before DevOps provisioning}"
  : "${DEVOPS_WRANGLER_INSTALL_ROOT:?DEVOPS_WRANGLER_INSTALL_ROOT must be set before DevOps provisioning}"
  : "${DEVOPS_WRANGLER_BINARY_PATH:?DEVOPS_WRANGLER_BINARY_PATH must be set before DevOps provisioning}"

  : "${DEVOPS_APTLY_RELEASE_VERSION:?DEVOPS_APTLY_RELEASE_VERSION must be set before DevOps provisioning}"
  : "${DEVOPS_APTLY_RELEASE_URL:?DEVOPS_APTLY_RELEASE_URL must be set before DevOps provisioning}"
  : "${DEVOPS_APTLY_RELEASE_SHA256:?DEVOPS_APTLY_RELEASE_SHA256 must be set before DevOps provisioning}"
  : "${DEVOPS_APTLY_RELEASE_BYTES:?DEVOPS_APTLY_RELEASE_BYTES must be set before DevOps provisioning}"
  : "${DEVOPS_APTLY_RELEASE_ARCHITECTURE:?DEVOPS_APTLY_RELEASE_ARCHITECTURE must be set before DevOps provisioning}"
  : "${DEVOPS_APTLY_RELEASE_ARCHIVE_FILENAME:?DEVOPS_APTLY_RELEASE_ARCHIVE_FILENAME must be set before DevOps provisioning}"
  : "${DEVOPS_APTLY_RELEASE_ARCHIVE_ROOT:?DEVOPS_APTLY_RELEASE_ARCHIVE_ROOT must be set before DevOps provisioning}"
  : "${DEVOPS_APTLY_RELEASE_ARCHIVE_FILES:?DEVOPS_APTLY_RELEASE_ARCHIVE_FILES must be set before DevOps provisioning}"
  : "${DEVOPS_APTLY_INSTALL_ROOT:?DEVOPS_APTLY_INSTALL_ROOT must be set before DevOps provisioning}"
  : "${DEVOPS_APTLY_BINARY_PATH:?DEVOPS_APTLY_BINARY_PATH must be set before DevOps provisioning}"

  : "${DEVOPS_OSC_RELEASE_VERSION:?DEVOPS_OSC_RELEASE_VERSION must be set before DevOps provisioning}"
  : "${DEVOPS_OSC_RELEASE_URL:?DEVOPS_OSC_RELEASE_URL must be set before DevOps provisioning}"
  : "${DEVOPS_OSC_RELEASE_SHA256:?DEVOPS_OSC_RELEASE_SHA256 must be set before DevOps provisioning}"
  : "${DEVOPS_OSC_RELEASE_BYTES:?DEVOPS_OSC_RELEASE_BYTES must be set before DevOps provisioning}"
  : "${DEVOPS_OSC_RELEASE_ARCHITECTURE:?DEVOPS_OSC_RELEASE_ARCHITECTURE must be set before DevOps provisioning}"
  : "${DEVOPS_OSC_RELEASE_ARCHIVE_FILENAME:?DEVOPS_OSC_RELEASE_ARCHIVE_FILENAME must be set before DevOps provisioning}"
  : "${DEVOPS_OSC_RELEASE_PACKAGE_ROOT:?DEVOPS_OSC_RELEASE_PACKAGE_ROOT must be set before DevOps provisioning}"
  : "${DEVOPS_OSC_RELEASE_DIST_INFO_ROOT:?DEVOPS_OSC_RELEASE_DIST_INFO_ROOT must be set before DevOps provisioning}"
  : "${DEVOPS_OSC_INSTALL_ROOT:?DEVOPS_OSC_INSTALL_ROOT must be set before DevOps provisioning}"
  : "${DEVOPS_OSC_BINARY_PATH:?DEVOPS_OSC_BINARY_PATH must be set before DevOps provisioning}"

  : "${DEVOPS_OBS_BUILD_TAG:?DEVOPS_OBS_BUILD_TAG must be set before DevOps provisioning}"
  : "${DEVOPS_OBS_BUILD_COMMIT:?DEVOPS_OBS_BUILD_COMMIT must be set before DevOps provisioning}"
  : "${DEVOPS_OBS_BUILD_URL:?DEVOPS_OBS_BUILD_URL must be set before DevOps provisioning}"
  : "${DEVOPS_OBS_BUILD_SHA256:?DEVOPS_OBS_BUILD_SHA256 must be set before DevOps provisioning}"
  : "${DEVOPS_OBS_BUILD_BYTES:?DEVOPS_OBS_BUILD_BYTES must be set before DevOps provisioning}"
  : "${DEVOPS_OBS_BUILD_ARCHITECTURE:?DEVOPS_OBS_BUILD_ARCHITECTURE must be set before DevOps provisioning}"
  : "${DEVOPS_OBS_BUILD_ARCHIVE_FILENAME:?DEVOPS_OBS_BUILD_ARCHIVE_FILENAME must be set before DevOps provisioning}"
  : "${DEVOPS_OBS_BUILD_ARCHIVE_ROOT:?DEVOPS_OBS_BUILD_ARCHIVE_ROOT must be set before DevOps provisioning}"
  : "${DEVOPS_OBS_BUILD_INSTALL_ROOT:?DEVOPS_OBS_BUILD_INSTALL_ROOT must be set before DevOps provisioning}"
  : "${DEVOPS_OBS_BUILD_BINARY_PATH:?DEVOPS_OBS_BUILD_BINARY_PATH must be set before DevOps provisioning}"
  : "${DEVOPS_OBS_BUILD_ENTRYPOINTS:?DEVOPS_OBS_BUILD_ENTRYPOINTS must be set before DevOps provisioning}"

  [ "$DEVOPS_UPSTREAM_POLICY_SCHEMA" = 4 ] ||
    devops_fatal "DEVOPS_UPSTREAM_POLICY_SCHEMA must remain 4"
  [ "$DEVOPS_UPSTREAM_ARCHITECTURE" = x86_64 ] ||
    devops_fatal "DEVOPS_UPSTREAM_ARCHITECTURE must remain x86_64"
  for policy_integer in \
    "$DEVOPS_UPSTREAM_DOWNLOAD_TIMEOUT_SECONDS" \
    "$DEVOPS_UPSTREAM_NPM_TIMEOUT_SECONDS" \
    "$DEVOPS_UPSTREAM_MAKE_TIMEOUT_SECONDS" \
    "$DEVOPS_UPSTREAM_VERIFY_TIMEOUT_SECONDS" \
    "$DEVOPS_UPSTREAM_MAX_ARCHIVE_MEMBERS" \
    "$DEVOPS_UPSTREAM_MAX_EXTRACTED_BYTES" \
    "$DEVOPS_ANSIBLE_CORE_MAX_ARCHIVE_MEMBERS" \
    "$DEVOPS_ANSIBLE_CORE_MAX_EXTRACTED_BYTES" \
    "$DEVOPS_PACKER_INIT_TIMEOUT_SECONDS"
  do
    devops_validate_positive_integer "upstream DevOps policy integer" "$policy_integer"
  done
  unset policy_integer

  devops_validate_node_release 22 \
    "$DEVOPS_NODE_22_MAJOR" "$DEVOPS_NODE_22_VERSION" "$DEVOPS_NODE_22_URL" \
    "$DEVOPS_NODE_22_SHA256" "$DEVOPS_NODE_22_BYTES" \
    "$DEVOPS_NODE_22_ARCHIVE_FILENAME" "$DEVOPS_NODE_22_ARCHIVE_ROOT" \
    "$DEVOPS_NODE_22_INSTALL_ROOT" "$DEVOPS_NODE_22_BINARY_PATH"
  devops_validate_node_release 24 \
    "$DEVOPS_NODE_24_MAJOR" "$DEVOPS_NODE_24_VERSION" "$DEVOPS_NODE_24_URL" \
    "$DEVOPS_NODE_24_SHA256" "$DEVOPS_NODE_24_BYTES" \
    "$DEVOPS_NODE_24_ARCHIVE_FILENAME" "$DEVOPS_NODE_24_ARCHIVE_ROOT" \
    "$DEVOPS_NODE_24_INSTALL_ROOT" "$DEVOPS_NODE_24_BINARY_PATH"
  devops_validate_node_release 26 \
    "$DEVOPS_NODE_26_MAJOR" "$DEVOPS_NODE_26_VERSION" "$DEVOPS_NODE_26_URL" \
    "$DEVOPS_NODE_26_SHA256" "$DEVOPS_NODE_26_BYTES" \
    "$DEVOPS_NODE_26_ARCHIVE_FILENAME" "$DEVOPS_NODE_26_ARCHIVE_ROOT" \
    "$DEVOPS_NODE_26_INSTALL_ROOT" "$DEVOPS_NODE_26_BINARY_PATH"

  devops_validate_semantic_version "DEVOPS_DENO_VERSION" "$DEVOPS_DENO_VERSION"
  [ "$DEVOPS_DENO_ARCHITECTURE" = x86_64-unknown-linux-gnu ] ||
    devops_fatal "DEVOPS_DENO_ARCHITECTURE must remain x86_64-unknown-linux-gnu"
  [ "$DEVOPS_DENO_ARCHIVE_FILENAME" = deno-x86_64-unknown-linux-gnu.zip ] ||
    devops_fatal "DEVOPS_DENO_ARCHIVE_FILENAME must identify the official Linux AMD64 archive"
  [ "$DEVOPS_DENO_URL" = "https://github.com/denoland/deno/releases/download/v${DEVOPS_DENO_VERSION}/${DEVOPS_DENO_ARCHIVE_FILENAME}" ] ||
    devops_fatal "DEVOPS_DENO_URL must identify the versioned official Linux AMD64 release archive"
  devops_validate_lower_hex "DEVOPS_DENO_SHA256" "$DEVOPS_DENO_SHA256" 64
  devops_validate_positive_integer "DEVOPS_DENO_BYTES" "$DEVOPS_DENO_BYTES"
  [ "$DEVOPS_DENO_ARCHIVE_FILES" = deno ] ||
    devops_fatal "DEVOPS_DENO_ARCHIVE_FILES must contain only deno"
  [ "$DEVOPS_DENO_INSTALL_ROOT" = /usr/local/lib/deno ] ||
    devops_fatal "DEVOPS_DENO_INSTALL_ROOT must remain /usr/local/lib/deno"
  [ "$DEVOPS_DENO_BINARY_PATH" = "${DEVOPS_DENO_INSTALL_ROOT}/bin/deno" ] ||
    devops_fatal "DEVOPS_DENO_BINARY_PATH must remain ${DEVOPS_DENO_INSTALL_ROOT}/bin/deno"

  devops_validate_semantic_version "DEVOPS_YT_DLP_VERSION" "$DEVOPS_YT_DLP_VERSION"
  [ "$DEVOPS_YT_DLP_ARCHITECTURE" = linux-x86_64 ] ||
    devops_fatal "DEVOPS_YT_DLP_ARCHITECTURE must remain linux-x86_64"
  [ "$DEVOPS_YT_DLP_ARCHIVE_FILENAME" = yt-dlp_linux ] ||
    devops_fatal "DEVOPS_YT_DLP_ARCHIVE_FILENAME must identify the official Linux AMD64 standalone executable"
  [ "$DEVOPS_YT_DLP_URL" = "https://github.com/yt-dlp/yt-dlp/releases/download/${DEVOPS_YT_DLP_VERSION}/${DEVOPS_YT_DLP_ARCHIVE_FILENAME}" ] ||
    devops_fatal "DEVOPS_YT_DLP_URL must identify the versioned official Linux AMD64 standalone executable"
  devops_validate_lower_hex "DEVOPS_YT_DLP_SHA256" "$DEVOPS_YT_DLP_SHA256" 64
  devops_validate_positive_integer "DEVOPS_YT_DLP_BYTES" "$DEVOPS_YT_DLP_BYTES"
  [ "$DEVOPS_YT_DLP_INSTALL_ROOT" = /usr/local/lib/yt-dlp ] ||
    devops_fatal "DEVOPS_YT_DLP_INSTALL_ROOT must remain /usr/local/lib/yt-dlp"
  [ "$DEVOPS_YT_DLP_BINARY_PATH" = "${DEVOPS_YT_DLP_INSTALL_ROOT}/bin/yt-dlp" ] ||
    devops_fatal "DEVOPS_YT_DLP_BINARY_PATH must remain ${DEVOPS_YT_DLP_INSTALL_ROOT}/bin/yt-dlp"
  [ "$DEVOPS_YT_DLP_PAYLOAD_PATH" = "${DEVOPS_YT_DLP_INSTALL_ROOT}/libexec/yt-dlp" ] ||
    devops_fatal "DEVOPS_YT_DLP_PAYLOAD_PATH must remain ${DEVOPS_YT_DLP_INSTALL_ROOT}/libexec/yt-dlp"

  devops_validate_semantic_version "DEVOPS_RUSTUP_VERSION" "$DEVOPS_RUSTUP_VERSION"
  [ "$DEVOPS_RUSTUP_TARGET_TRIPLE" = x86_64-unknown-linux-gnu ] ||
    devops_fatal "DEVOPS_RUSTUP_TARGET_TRIPLE must remain x86_64-unknown-linux-gnu"
  [ "$DEVOPS_RUSTUP_URL" = "https://static.rust-lang.org/rustup/archive/${DEVOPS_RUSTUP_VERSION}/${DEVOPS_RUSTUP_TARGET_TRIPLE}/rustup-init" ] ||
    devops_fatal "DEVOPS_RUSTUP_URL must identify the versioned official Linux AMD64 bootstrap"
  devops_validate_lower_hex "DEVOPS_RUSTUP_SHA256" "$DEVOPS_RUSTUP_SHA256" 64
  devops_validate_positive_integer "DEVOPS_RUSTUP_BYTES" "$DEVOPS_RUSTUP_BYTES"
  [ "$DEVOPS_RUSTUP_INSTALL_ROOT" = /usr/local/lib/rustup ] ||
    devops_fatal "DEVOPS_RUSTUP_INSTALL_ROOT must remain /usr/local/lib/rustup"
  [ "$DEVOPS_RUSTUP_BINARY_PATH" = "${DEVOPS_RUSTUP_INSTALL_ROOT}/bin/rustup-init" ] ||
    devops_fatal "DEVOPS_RUSTUP_BINARY_PATH must remain ${DEVOPS_RUSTUP_INSTALL_ROOT}/bin/rustup-init"
  devops_validate_source_build_flag "DEVOPS_DOTSLASH_SOURCE_BUILD" "$DEVOPS_DOTSLASH_SOURCE_BUILD"
  devops_validate_semantic_version "DEVOPS_DOTSLASH_VERSION" "$DEVOPS_DOTSLASH_VERSION"
  [ "$DEVOPS_DOTSLASH_REPOSITORY_URL" = https://github.com/facebook/dotslash ] ||
    devops_fatal "DEVOPS_DOTSLASH_REPOSITORY_URL must identify the official repository"
  devops_validate_lower_hex "DEVOPS_DOTSLASH_COMMIT" "$DEVOPS_DOTSLASH_COMMIT" 40
  [ "$DEVOPS_DOTSLASH_ARCHIVE_FILENAME" = "dotslash-linux-musl.x86_64.v${DEVOPS_DOTSLASH_VERSION}.tar.gz" ] ||
    devops_fatal "DEVOPS_DOTSLASH_ARCHIVE_FILENAME does not match DEVOPS_DOTSLASH_VERSION"
  [ "$DEVOPS_DOTSLASH_URL" = "https://github.com/facebook/dotslash/releases/download/v${DEVOPS_DOTSLASH_VERSION}/${DEVOPS_DOTSLASH_ARCHIVE_FILENAME}" ] ||
    devops_fatal "DEVOPS_DOTSLASH_URL must identify the official Linux musl x86-64 release archive"
  devops_validate_lower_hex "DEVOPS_DOTSLASH_SHA256" "$DEVOPS_DOTSLASH_SHA256" 64
  devops_validate_positive_integer "DEVOPS_DOTSLASH_BYTES" "$DEVOPS_DOTSLASH_BYTES"
  [ "$DEVOPS_DOTSLASH_ARCHITECTURE" = linux-musl.x86_64 ] ||
    devops_fatal "DEVOPS_DOTSLASH_ARCHITECTURE must remain linux-musl.x86_64"
  [ "$DEVOPS_DOTSLASH_ARCHIVE_FILES" = dotslash ] ||
    devops_fatal "DEVOPS_DOTSLASH_ARCHIVE_FILES must contain only dotslash"
  devops_validate_source_build_flag "DEVOPS_UV_SOURCE_BUILD" "$DEVOPS_UV_SOURCE_BUILD"
  devops_validate_semantic_version "DEVOPS_UV_VERSION" "$DEVOPS_UV_VERSION"
  [ "$DEVOPS_UV_ARCHIVE_FILENAME" = uv-x86_64-unknown-linux-gnu.tar.gz ] ||
    devops_fatal "DEVOPS_UV_ARCHIVE_FILENAME must identify the official Linux GNU x86-64 release archive"
  [ "$DEVOPS_UV_ARCHIVE_ROOT" = uv-x86_64-unknown-linux-gnu ] ||
    devops_fatal "DEVOPS_UV_ARCHIVE_ROOT must identify the official Linux GNU x86-64 release root"
  [ "$DEVOPS_UV_URL" = "https://github.com/astral-sh/uv/releases/download/${DEVOPS_UV_VERSION}/${DEVOPS_UV_ARCHIVE_FILENAME}" ] ||
    devops_fatal "DEVOPS_UV_URL must identify the versioned official Linux GNU x86-64 release archive"
  devops_validate_lower_hex "DEVOPS_UV_SHA256" "$DEVOPS_UV_SHA256" 64
  devops_validate_positive_integer "DEVOPS_UV_BYTES" "$DEVOPS_UV_BYTES"
  [ "$DEVOPS_UV_ARCHITECTURE" = x86_64-unknown-linux-gnu ] ||
    devops_fatal "DEVOPS_UV_ARCHITECTURE must remain x86_64-unknown-linux-gnu"
  [ "$DEVOPS_UV_ARCHIVE_FILES" = "uv uvx" ] ||
    devops_fatal "DEVOPS_UV_ARCHIVE_FILES must contain uv and uvx"

  devops_validate_semantic_version "DEVOPS_ANSIBLE_CORE_VERSION" "$DEVOPS_ANSIBLE_CORE_VERSION"
  [ "$DEVOPS_ANSIBLE_CORE_ARCHIVE_FILENAME" = "ansible_core-${DEVOPS_ANSIBLE_CORE_VERSION}-py3-none-any.whl" ] ||
    devops_fatal "DEVOPS_ANSIBLE_CORE_ARCHIVE_FILENAME does not match DEVOPS_ANSIBLE_CORE_VERSION"
  case "$DEVOPS_ANSIBLE_CORE_URL" in
    "https://files.pythonhosted.org/packages/"*"/${DEVOPS_ANSIBLE_CORE_ARCHIVE_FILENAME}") ;;
    *) devops_fatal "DEVOPS_ANSIBLE_CORE_URL must identify the official PyPI wheel" ;;
  esac
  case "$DEVOPS_ANSIBLE_CORE_URL" in
    *..*) devops_fatal "DEVOPS_ANSIBLE_CORE_URL must be normalized" ;;
  esac
  devops_validate_lower_hex "DEVOPS_ANSIBLE_CORE_SHA256" "$DEVOPS_ANSIBLE_CORE_SHA256" 64
  devops_validate_positive_integer "DEVOPS_ANSIBLE_CORE_BYTES" "$DEVOPS_ANSIBLE_CORE_BYTES"
  [ "$DEVOPS_ANSIBLE_CORE_ARCHITECTURE" = python3-any ] ||
    devops_fatal "DEVOPS_ANSIBLE_CORE_ARCHITECTURE must remain python3-any"
  [ "$DEVOPS_ANSIBLE_CORE_PACKAGE_ROOTS" = "ansible ansible_test" ] ||
    devops_fatal "DEVOPS_ANSIBLE_CORE_PACKAGE_ROOTS must remain ansible ansible_test"
  [ "$DEVOPS_ANSIBLE_CORE_DIST_INFO_ROOT" = "ansible_core-${DEVOPS_ANSIBLE_CORE_VERSION}.dist-info" ] ||
    devops_fatal "DEVOPS_ANSIBLE_CORE_DIST_INFO_ROOT does not match DEVOPS_ANSIBLE_CORE_VERSION"
  [ "$DEVOPS_ANSIBLE_CORE_INSTALL_ROOT" = /usr/local/lib/ansible ] ||
    devops_fatal "DEVOPS_ANSIBLE_CORE_INSTALL_ROOT must remain /usr/local/lib/ansible"
  [ "$DEVOPS_ANSIBLE_CORE_BINARY_PATH" = "${DEVOPS_ANSIBLE_CORE_INSTALL_ROOT}/bin/ansible" ] ||
    devops_fatal "DEVOPS_ANSIBLE_CORE_BINARY_PATH must remain ${DEVOPS_ANSIBLE_CORE_INSTALL_ROOT}/bin/ansible"

  devops_validate_semantic_version "DEVOPS_OPENTOFU_VERSION" "$DEVOPS_OPENTOFU_VERSION"
  [ "$DEVOPS_OPENTOFU_ARCHIVE_FILENAME" = "tofu_${DEVOPS_OPENTOFU_VERSION}_linux_amd64.zip" ] ||
    devops_fatal "DEVOPS_OPENTOFU_ARCHIVE_FILENAME does not match DEVOPS_OPENTOFU_VERSION"
  [ "$DEVOPS_OPENTOFU_URL" = "https://github.com/opentofu/opentofu/releases/download/v${DEVOPS_OPENTOFU_VERSION}/${DEVOPS_OPENTOFU_ARCHIVE_FILENAME}" ] ||
    devops_fatal "DEVOPS_OPENTOFU_URL must identify the official Linux AMD64 release archive"
  devops_validate_lower_hex "DEVOPS_OPENTOFU_SHA256" "$DEVOPS_OPENTOFU_SHA256" 64
  devops_validate_positive_integer "DEVOPS_OPENTOFU_BYTES" "$DEVOPS_OPENTOFU_BYTES"
  [ "$DEVOPS_OPENTOFU_ARCHITECTURE" = linux-amd64 ] ||
    devops_fatal "DEVOPS_OPENTOFU_ARCHITECTURE must remain linux-amd64"
  devops_validate_archive_file_list "DEVOPS_OPENTOFU_ARCHIVE_FILES" "$DEVOPS_OPENTOFU_ARCHIVE_FILES"
  [ "$DEVOPS_OPENTOFU_INSTALL_ROOT" = /usr/local/lib/opentufo ] ||
    devops_fatal "DEVOPS_OPENTOFU_INSTALL_ROOT must remain /usr/local/lib/opentufo"
  [ "$DEVOPS_OPENTOFU_BINARY_PATH" = "${DEVOPS_OPENTOFU_INSTALL_ROOT}/bin/tofu" ] ||
    devops_fatal "DEVOPS_OPENTOFU_BINARY_PATH must remain ${DEVOPS_OPENTOFU_INSTALL_ROOT}/bin/tofu"

  devops_validate_semantic_version "DEVOPS_TERRAFORM_VERSION" "$DEVOPS_TERRAFORM_VERSION"
  [ "$DEVOPS_TERRAFORM_ARCHIVE_FILENAME" = "terraform_${DEVOPS_TERRAFORM_VERSION}_linux_amd64.zip" ] ||
    devops_fatal "DEVOPS_TERRAFORM_ARCHIVE_FILENAME does not match DEVOPS_TERRAFORM_VERSION"
  [ "$DEVOPS_TERRAFORM_URL" = "https://releases.hashicorp.com/terraform/${DEVOPS_TERRAFORM_VERSION}/${DEVOPS_TERRAFORM_ARCHIVE_FILENAME}" ] ||
    devops_fatal "DEVOPS_TERRAFORM_URL must identify the official Linux AMD64 release archive"
  devops_validate_lower_hex "DEVOPS_TERRAFORM_SHA256" "$DEVOPS_TERRAFORM_SHA256" 64
  devops_validate_positive_integer "DEVOPS_TERRAFORM_BYTES" "$DEVOPS_TERRAFORM_BYTES"
  [ "$DEVOPS_TERRAFORM_ARCHITECTURE" = linux-amd64 ] ||
    devops_fatal "DEVOPS_TERRAFORM_ARCHITECTURE must remain linux-amd64"
  devops_validate_archive_file_list \
    "DEVOPS_TERRAFORM_ARCHIVE_FILES" \
    "$DEVOPS_TERRAFORM_ARCHIVE_FILES"
  [ "$DEVOPS_TERRAFORM_INSTALL_ROOT" = /usr/local/lib/hashicorp/terraform ] ||
    devops_fatal "DEVOPS_TERRAFORM_INSTALL_ROOT must remain /usr/local/lib/hashicorp/terraform"
  [ "$DEVOPS_TERRAFORM_BINARY_PATH" = "${DEVOPS_TERRAFORM_INSTALL_ROOT}/bin/terraform" ] ||
    devops_fatal "DEVOPS_TERRAFORM_BINARY_PATH must remain ${DEVOPS_TERRAFORM_INSTALL_ROOT}/bin/terraform"

  devops_validate_semantic_version "DEVOPS_PACKER_VERSION" "$DEVOPS_PACKER_VERSION"
  [ "$DEVOPS_PACKER_ARCHIVE_FILENAME" = "packer_${DEVOPS_PACKER_VERSION}_linux_amd64.zip" ] ||
    devops_fatal "DEVOPS_PACKER_ARCHIVE_FILENAME does not match DEVOPS_PACKER_VERSION"
  [ "$DEVOPS_PACKER_URL" = "https://releases.hashicorp.com/packer/${DEVOPS_PACKER_VERSION}/${DEVOPS_PACKER_ARCHIVE_FILENAME}" ] ||
    devops_fatal "DEVOPS_PACKER_URL must identify the official Linux AMD64 release archive"
  devops_validate_lower_hex "DEVOPS_PACKER_SHA256" "$DEVOPS_PACKER_SHA256" 64
  devops_validate_positive_integer "DEVOPS_PACKER_BYTES" "$DEVOPS_PACKER_BYTES"
  [ "$DEVOPS_PACKER_ARCHITECTURE" = linux-amd64 ] ||
    devops_fatal "DEVOPS_PACKER_ARCHITECTURE must remain linux-amd64"
  devops_validate_archive_file_list \
    "DEVOPS_PACKER_ARCHIVE_FILES" \
    "$DEVOPS_PACKER_ARCHIVE_FILES"
  [ "$DEVOPS_PACKER_INSTALL_ROOT" = /usr/local/lib/hashicorp/packer ] ||
    devops_fatal "DEVOPS_PACKER_INSTALL_ROOT must remain /usr/local/lib/hashicorp/packer"
  [ "$DEVOPS_PACKER_BINARY_PATH" = "${DEVOPS_PACKER_INSTALL_ROOT}/bin/packer" ] ||
    devops_fatal "DEVOPS_PACKER_BINARY_PATH must remain ${DEVOPS_PACKER_INSTALL_ROOT}/bin/packer"

  devops_validate_semantic_version "DEVOPS_WRANGLER_VERSION" "$DEVOPS_WRANGLER_VERSION"
  [ "$DEVOPS_WRANGLER_ARCHIVE_FILENAME" = "wrangler-${DEVOPS_WRANGLER_VERSION}.tgz" ] ||
    devops_fatal "DEVOPS_WRANGLER_ARCHIVE_FILENAME does not match DEVOPS_WRANGLER_VERSION"
  [ "$DEVOPS_WRANGLER_URL" = "https://registry.npmjs.org/wrangler/-/${DEVOPS_WRANGLER_ARCHIVE_FILENAME}" ] ||
    devops_fatal "DEVOPS_WRANGLER_URL must identify the official npm tarball"
  devops_validate_lower_hex "DEVOPS_WRANGLER_SHA512" "$DEVOPS_WRANGLER_SHA512" 128
  if ! printf '%s\n' "$DEVOPS_WRANGLER_NPM_INTEGRITY" |
    LC_ALL=C grep -Eq '^sha512-[A-Za-z0-9+/]{86}==$'
  then
    devops_fatal "DEVOPS_WRANGLER_NPM_INTEGRITY must be an npm SHA-512 integrity value"
  fi
  devops_validate_positive_integer "DEVOPS_WRANGLER_BYTES" "$DEVOPS_WRANGLER_BYTES"
  [ "$DEVOPS_WRANGLER_ARCHITECTURE" = node-any ] ||
    devops_fatal "DEVOPS_WRANGLER_ARCHITECTURE must remain node-any"
  [ "$DEVOPS_WRANGLER_ARCHIVE_ROOT" = package ] ||
    devops_fatal "DEVOPS_WRANGLER_ARCHIVE_ROOT must remain package"
  [ "$DEVOPS_WRANGLER_PACKAGE_NAME" = wrangler ] ||
    devops_fatal "DEVOPS_WRANGLER_PACKAGE_NAME must remain wrangler"
  if ! printf '%s\n' "$DEVOPS_WRANGLER_NODE_REQUIREMENT" |
    LC_ALL=C grep -Eq '^>=[0-9]+\.[0-9]+\.[0-9]+$'
  then
    devops_fatal "DEVOPS_WRANGLER_NODE_REQUIREMENT must be a minimum semantic Node version"
  fi
  [ "$DEVOPS_WRANGLER_NODE_ROOT" = "$DEVOPS_NODE_26_INSTALL_ROOT" ] ||
    devops_fatal "DEVOPS_WRANGLER_NODE_ROOT must match DEVOPS_NODE_26_INSTALL_ROOT"
  [ "$DEVOPS_WRANGLER_NPM_REGISTRY_URL" = https://registry.npmjs.org/ ] ||
    devops_fatal "DEVOPS_WRANGLER_NPM_REGISTRY_URL must identify the official npm registry origin"
  [ "$DEVOPS_WRANGLER_INSTALL_ROOT" = /usr/local/lib/wrangler ] ||
    devops_fatal "DEVOPS_WRANGLER_INSTALL_ROOT must remain /usr/local/lib/wrangler"
  [ "$DEVOPS_WRANGLER_BINARY_PATH" = "${DEVOPS_WRANGLER_INSTALL_ROOT}/node_modules/.bin/wrangler" ] ||
    devops_fatal "DEVOPS_WRANGLER_BINARY_PATH must remain ${DEVOPS_WRANGLER_INSTALL_ROOT}/node_modules/.bin/wrangler"

  devops_validate_semantic_version "DEVOPS_APTLY_RELEASE_VERSION" "$DEVOPS_APTLY_RELEASE_VERSION"
  [ "$DEVOPS_APTLY_RELEASE_ARCHIVE_FILENAME" = "aptly_${DEVOPS_APTLY_RELEASE_VERSION}_linux_amd64.zip" ] ||
    devops_fatal "DEVOPS_APTLY_RELEASE_ARCHIVE_FILENAME does not match DEVOPS_APTLY_RELEASE_VERSION"
  [ "$DEVOPS_APTLY_RELEASE_ARCHIVE_ROOT" = "aptly_${DEVOPS_APTLY_RELEASE_VERSION}_linux_amd64" ] ||
    devops_fatal "DEVOPS_APTLY_RELEASE_ARCHIVE_ROOT does not match DEVOPS_APTLY_RELEASE_VERSION"
  [ "$DEVOPS_APTLY_RELEASE_URL" = "https://github.com/aptly-dev/aptly/releases/download/v${DEVOPS_APTLY_RELEASE_VERSION}/${DEVOPS_APTLY_RELEASE_ARCHIVE_FILENAME}" ] ||
    devops_fatal "DEVOPS_APTLY_RELEASE_URL must identify the official Linux AMD64 release archive"
  devops_validate_lower_hex "DEVOPS_APTLY_RELEASE_SHA256" "$DEVOPS_APTLY_RELEASE_SHA256" 64
  devops_validate_positive_integer "DEVOPS_APTLY_RELEASE_BYTES" "$DEVOPS_APTLY_RELEASE_BYTES"
  [ "$DEVOPS_APTLY_RELEASE_ARCHITECTURE" = linux-amd64 ] ||
    devops_fatal "DEVOPS_APTLY_RELEASE_ARCHITECTURE must remain linux-amd64"
  devops_validate_archive_file_list "DEVOPS_APTLY_RELEASE_ARCHIVE_FILES" "$DEVOPS_APTLY_RELEASE_ARCHIVE_FILES"
  [ "$DEVOPS_APTLY_INSTALL_ROOT" = /usr/local/lib/aptly ] ||
    devops_fatal "DEVOPS_APTLY_INSTALL_ROOT must remain /usr/local/lib/aptly"
  [ "$DEVOPS_APTLY_BINARY_PATH" = "${DEVOPS_APTLY_INSTALL_ROOT}/bin/aptly" ] ||
    devops_fatal "DEVOPS_APTLY_BINARY_PATH must remain ${DEVOPS_APTLY_INSTALL_ROOT}/bin/aptly"

  devops_validate_semantic_version "DEVOPS_OSC_RELEASE_VERSION" "$DEVOPS_OSC_RELEASE_VERSION"
  [ "$DEVOPS_OSC_RELEASE_ARCHIVE_FILENAME" = "osc-${DEVOPS_OSC_RELEASE_VERSION}-py3-none-any.whl" ] ||
    devops_fatal "DEVOPS_OSC_RELEASE_ARCHIVE_FILENAME does not match DEVOPS_OSC_RELEASE_VERSION"
  case "$DEVOPS_OSC_RELEASE_URL" in
    "https://files.pythonhosted.org/packages/"*"/${DEVOPS_OSC_RELEASE_ARCHIVE_FILENAME}") ;;
    *) devops_fatal "DEVOPS_OSC_RELEASE_URL must identify the official PyPI wheel" ;;
  esac
  case "$DEVOPS_OSC_RELEASE_URL" in
    *..*) devops_fatal "DEVOPS_OSC_RELEASE_URL must be normalized" ;;
  esac
  devops_validate_lower_hex "DEVOPS_OSC_RELEASE_SHA256" "$DEVOPS_OSC_RELEASE_SHA256" 64
  devops_validate_positive_integer "DEVOPS_OSC_RELEASE_BYTES" "$DEVOPS_OSC_RELEASE_BYTES"
  [ "$DEVOPS_OSC_RELEASE_ARCHITECTURE" = python3-any ] ||
    devops_fatal "DEVOPS_OSC_RELEASE_ARCHITECTURE must remain python3-any"
  [ "$DEVOPS_OSC_RELEASE_PACKAGE_ROOT" = osc ] ||
    devops_fatal "DEVOPS_OSC_RELEASE_PACKAGE_ROOT must remain osc"
  [ "$DEVOPS_OSC_RELEASE_DIST_INFO_ROOT" = "osc-${DEVOPS_OSC_RELEASE_VERSION}.dist-info" ] ||
    devops_fatal "DEVOPS_OSC_RELEASE_DIST_INFO_ROOT does not match DEVOPS_OSC_RELEASE_VERSION"
  [ "$DEVOPS_OSC_INSTALL_ROOT" = /usr/local/lib/osc ] ||
    devops_fatal "DEVOPS_OSC_INSTALL_ROOT must remain /usr/local/lib/osc"
  [ "$DEVOPS_OSC_BINARY_PATH" = "${DEVOPS_OSC_INSTALL_ROOT}/bin/osc" ] ||
    devops_fatal "DEVOPS_OSC_BINARY_PATH must remain ${DEVOPS_OSC_INSTALL_ROOT}/bin/osc"

  if ! printf '%s\n' "$DEVOPS_OBS_BUILD_TAG" | LC_ALL=C grep -Eq '^[0-9]{8}$'; then
    devops_fatal "DEVOPS_OBS_BUILD_TAG must be an eight-digit upstream tag"
  fi
  devops_validate_lower_hex "DEVOPS_OBS_BUILD_COMMIT" "$DEVOPS_OBS_BUILD_COMMIT" 40
  [ "$DEVOPS_OBS_BUILD_URL" = "https://codeload.github.com/openSUSE/obs-build/tar.gz/${DEVOPS_OBS_BUILD_COMMIT}" ] ||
    devops_fatal "DEVOPS_OBS_BUILD_URL must identify the official commit archive"
  [ "$DEVOPS_OBS_BUILD_ARCHIVE_FILENAME" = "obs-build-${DEVOPS_OBS_BUILD_COMMIT}.tar.gz" ] ||
    devops_fatal "DEVOPS_OBS_BUILD_ARCHIVE_FILENAME does not match DEVOPS_OBS_BUILD_COMMIT"
  [ "$DEVOPS_OBS_BUILD_ARCHIVE_ROOT" = "obs-build-${DEVOPS_OBS_BUILD_COMMIT}" ] ||
    devops_fatal "DEVOPS_OBS_BUILD_ARCHIVE_ROOT does not match DEVOPS_OBS_BUILD_COMMIT"
  devops_validate_lower_hex "DEVOPS_OBS_BUILD_SHA256" "$DEVOPS_OBS_BUILD_SHA256" 64
  devops_validate_positive_integer "DEVOPS_OBS_BUILD_BYTES" "$DEVOPS_OBS_BUILD_BYTES"
  [ "$DEVOPS_OBS_BUILD_ARCHITECTURE" = source-any ] ||
    devops_fatal "DEVOPS_OBS_BUILD_ARCHITECTURE must remain source-any"
  [ "$DEVOPS_OBS_BUILD_INSTALL_ROOT" = /usr/local/lib/obs-build ] ||
    devops_fatal "DEVOPS_OBS_BUILD_INSTALL_ROOT must remain /usr/local/lib/obs-build"
  [ "$DEVOPS_OBS_BUILD_BINARY_PATH" = "${DEVOPS_OBS_BUILD_INSTALL_ROOT}/bin/build" ] ||
    devops_fatal "DEVOPS_OBS_BUILD_BINARY_PATH must remain ${DEVOPS_OBS_BUILD_INSTALL_ROOT}/bin/build"
  devops_validate_archive_file_list "DEVOPS_OBS_BUILD_ENTRYPOINTS" "$DEVOPS_OBS_BUILD_ENTRYPOINTS"
}

devops_validate_bazel_policy() {
  : "${DEVOPS_BAZELISK_VERSION:?DEVOPS_BAZELISK_VERSION must be set before DevOps provisioning}"
  : "${DEVOPS_BAZELISK_URL:?DEVOPS_BAZELISK_URL must be set before DevOps provisioning}"
  : "${DEVOPS_BAZELISK_SHA256:?DEVOPS_BAZELISK_SHA256 must be set before DevOps provisioning}"
  : "${DEVOPS_BAZELISK_MINIMUM_BYTES:?DEVOPS_BAZELISK_MINIMUM_BYTES must be set before DevOps provisioning}"
  : "${DEVOPS_BAZELISK_MAXIMUM_BYTES:?DEVOPS_BAZELISK_MAXIMUM_BYTES must be set before DevOps provisioning}"
  : "${DEVOPS_BAZELISK_INSTALL_DIR:?DEVOPS_BAZELISK_INSTALL_DIR must be set before DevOps provisioning}"
  : "${DEVOPS_BAZELISK_BINARY_PATH:?DEVOPS_BAZELISK_BINARY_PATH must be set before DevOps provisioning}"
  : "${DEVOPS_BAZEL_CACHE_ROOT:?DEVOPS_BAZEL_CACHE_ROOT must be set before DevOps provisioning}"
  : "${DEVOPS_BAZEL_BUILD_ROOT:?DEVOPS_BAZEL_BUILD_ROOT must be set before DevOps provisioning}"
  : "${DEVOPS_BAZEL_DB_ROOT:?DEVOPS_BAZEL_DB_ROOT must be set before DevOps provisioning}"
  : "${DEVOPS_BAZEL_CACHE_SUBDIR:?DEVOPS_BAZEL_CACHE_SUBDIR must be set before DevOps provisioning}"
  : "${DEVOPS_BAZEL_DISK_CACHE_SUBDIR:?DEVOPS_BAZEL_DISK_CACHE_SUBDIR must be set before DevOps provisioning}"
  : "${DEVOPS_BAZEL_REPOSITORY_CACHE_SUBDIR:?DEVOPS_BAZEL_REPOSITORY_CACHE_SUBDIR must be set before DevOps provisioning}"
  : "${DEVOPS_BAZEL_OUTPUT_USER_ROOT_SUBDIR:?DEVOPS_BAZEL_OUTPUT_USER_ROOT_SUBDIR must be set before DevOps provisioning}"
  : "${DEVOPS_BAZELISK_HOME_SUBDIR:?DEVOPS_BAZELISK_HOME_SUBDIR must be set before DevOps provisioning}"
  : "${DEVOPS_BAZEL_DISK_CACHE_SIZE:?DEVOPS_BAZEL_DISK_CACHE_SIZE must be set before DevOps provisioning}"
  : "${DEVOPS_BAZEL_DISK_CACHE_MAX_AGE:?DEVOPS_BAZEL_DISK_CACHE_MAX_AGE must be set before DevOps provisioning}"
  : "${DEVOPS_BAZEL_DISK_CACHE_GC_IDLE_DELAY:?DEVOPS_BAZEL_DISK_CACHE_GC_IDLE_DELAY must be set before DevOps provisioning}"
  : "${DEVOPS_BAZEL_ACTION_CACHE_MAX_AGE:?DEVOPS_BAZEL_ACTION_CACHE_MAX_AGE must be set before DevOps provisioning}"
  : "${DEVOPS_BAZEL_ACTION_CACHE_GC_IDLE_DELAY:?DEVOPS_BAZEL_ACTION_CACHE_GC_IDLE_DELAY must be set before DevOps provisioning}"
  : "${DEVOPS_BAZEL_ACTION_CACHE_GC_THRESHOLD:?DEVOPS_BAZEL_ACTION_CACHE_GC_THRESHOLD must be set before DevOps provisioning}"
  : "${DEVOPS_BAZEL_INSTALL_BASE_GC_MAX_AGE:?DEVOPS_BAZEL_INSTALL_BASE_GC_MAX_AGE must be set before DevOps provisioning}"
  : "${DEVOPS_BAZEL_SERVER_IDLE_SECONDS:?DEVOPS_BAZEL_SERVER_IDLE_SECONDS must be set before DevOps provisioning}"
  : "${DEVOPS_BAZEL_REPOSITORY_DOWNLOADER_RETRIES:?DEVOPS_BAZEL_REPOSITORY_DOWNLOADER_RETRIES must be set before DevOps provisioning}"

  if ! printf '%s\n' "$DEVOPS_BAZELISK_VERSION" | LC_ALL=C grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$'; then
    devops_fatal "DEVOPS_BAZELISK_VERSION must be a semantic version: $DEVOPS_BAZELISK_VERSION"
  fi
  case "$DEVOPS_BAZELISK_URL" in
    "https://github.com/bazelbuild/bazelisk/releases/download/v${DEVOPS_BAZELISK_VERSION}/bazelisk-linux-amd64")
      ;;
    *)
      devops_fatal "DEVOPS_BAZELISK_URL must be the HTTPS Linux AMD64 release asset for DEVOPS_BAZELISK_VERSION"
      ;;
  esac
  [ "${#DEVOPS_BAZELISK_SHA256}" -eq 64 ] ||
    devops_fatal "DEVOPS_BAZELISK_SHA256 must be a lowercase SHA-256 digest"
  case "$DEVOPS_BAZELISK_SHA256" in
    *[!0123456789abcdef]*)
      devops_fatal "DEVOPS_BAZELISK_SHA256 must be a lowercase SHA-256 digest"
      ;;
  esac

  devops_validate_positive_integer \
    "DEVOPS_BAZELISK_MINIMUM_BYTES" \
    "$DEVOPS_BAZELISK_MINIMUM_BYTES"
  devops_validate_positive_integer \
    "DEVOPS_BAZELISK_MAXIMUM_BYTES" \
    "$DEVOPS_BAZELISK_MAXIMUM_BYTES"
  [ "$DEVOPS_BAZELISK_MAXIMUM_BYTES" -ge "$DEVOPS_BAZELISK_MINIMUM_BYTES" ] ||
    devops_fatal "DEVOPS_BAZELISK_MAXIMUM_BYTES must not be smaller than DEVOPS_BAZELISK_MINIMUM_BYTES"

  devops_validate_abs_path "DEVOPS_BAZELISK_INSTALL_DIR" "$DEVOPS_BAZELISK_INSTALL_DIR"
  devops_validate_abs_path "DEVOPS_BAZELISK_BINARY_PATH" "$DEVOPS_BAZELISK_BINARY_PATH"
  [ "$DEVOPS_BAZELISK_INSTALL_DIR" = "/usr/local/lib/bazelisk" ] ||
    devops_fatal "DEVOPS_BAZELISK_INSTALL_DIR must remain /usr/local/lib/bazelisk"
  [ "$DEVOPS_BAZELISK_BINARY_PATH" = "${DEVOPS_BAZELISK_INSTALL_DIR}/bazel" ] ||
    devops_fatal "DEVOPS_BAZELISK_BINARY_PATH must be ${DEVOPS_BAZELISK_INSTALL_DIR}/bazel"

  devops_validate_abs_path "DEVOPS_BAZEL_CACHE_ROOT" "$DEVOPS_BAZEL_CACHE_ROOT"
  devops_validate_abs_path "DEVOPS_BAZEL_BUILD_ROOT" "$DEVOPS_BAZEL_BUILD_ROOT"
  devops_validate_abs_path "DEVOPS_BAZEL_DB_ROOT" "$DEVOPS_BAZEL_DB_ROOT"
  [ "$DEVOPS_BAZEL_CACHE_ROOT" = "$DIR_POOL_CACHE" ] ||
    devops_fatal "DEVOPS_BAZEL_CACHE_ROOT must match DIR_POOL_CACHE"
  [ "$DEVOPS_BAZEL_BUILD_ROOT" = "$DIR_POOL_BUILD" ] ||
    devops_fatal "DEVOPS_BAZEL_BUILD_ROOT must match DIR_POOL_BUILD"
  [ "$DEVOPS_BAZEL_DB_ROOT" = "$DIR_POOL_DB" ] ||
    devops_fatal "DEVOPS_BAZEL_DB_ROOT must match DIR_POOL_DB"

  devops_validate_relative_path "DEVOPS_BAZEL_CACHE_SUBDIR" "$DEVOPS_BAZEL_CACHE_SUBDIR"
  devops_validate_relative_path \
    "DEVOPS_BAZEL_DISK_CACHE_SUBDIR" \
    "$DEVOPS_BAZEL_DISK_CACHE_SUBDIR"
  devops_validate_relative_path \
    "DEVOPS_BAZEL_REPOSITORY_CACHE_SUBDIR" \
    "$DEVOPS_BAZEL_REPOSITORY_CACHE_SUBDIR"
  devops_validate_relative_path \
    "DEVOPS_BAZEL_OUTPUT_USER_ROOT_SUBDIR" \
    "$DEVOPS_BAZEL_OUTPUT_USER_ROOT_SUBDIR"
  devops_validate_relative_path \
    "DEVOPS_BAZELISK_HOME_SUBDIR" \
    "$DEVOPS_BAZELISK_HOME_SUBDIR"

  devops_validate_bazel_size "DEVOPS_BAZEL_DISK_CACHE_SIZE" "$DEVOPS_BAZEL_DISK_CACHE_SIZE"
  devops_validate_bazel_duration \
    "DEVOPS_BAZEL_DISK_CACHE_MAX_AGE" \
    "$DEVOPS_BAZEL_DISK_CACHE_MAX_AGE"
  devops_validate_bazel_duration \
    "DEVOPS_BAZEL_DISK_CACHE_GC_IDLE_DELAY" \
    "$DEVOPS_BAZEL_DISK_CACHE_GC_IDLE_DELAY"
  devops_validate_bazel_duration \
    "DEVOPS_BAZEL_ACTION_CACHE_MAX_AGE" \
    "$DEVOPS_BAZEL_ACTION_CACHE_MAX_AGE"
  devops_validate_bazel_duration \
    "DEVOPS_BAZEL_ACTION_CACHE_GC_IDLE_DELAY" \
    "$DEVOPS_BAZEL_ACTION_CACHE_GC_IDLE_DELAY"
  devops_validate_bazel_duration \
    "DEVOPS_BAZEL_INSTALL_BASE_GC_MAX_AGE" \
    "$DEVOPS_BAZEL_INSTALL_BASE_GC_MAX_AGE"
  devops_validate_positive_integer \
    "DEVOPS_BAZEL_ACTION_CACHE_GC_THRESHOLD" \
    "$DEVOPS_BAZEL_ACTION_CACHE_GC_THRESHOLD"
  [ "$DEVOPS_BAZEL_ACTION_CACHE_GC_THRESHOLD" -le 100 ] ||
    devops_fatal "DEVOPS_BAZEL_ACTION_CACHE_GC_THRESHOLD must not exceed 100"
  devops_validate_positive_integer \
    "DEVOPS_BAZEL_SERVER_IDLE_SECONDS" \
    "$DEVOPS_BAZEL_SERVER_IDLE_SECONDS"
  devops_validate_positive_integer \
    "DEVOPS_BAZEL_REPOSITORY_DOWNLOADER_RETRIES" \
    "$DEVOPS_BAZEL_REPOSITORY_DOWNLOADER_RETRIES"
}

devops_validate_publishing_policy() {
  : "${DEVOPS_APTLY_ROOT_SUBDIR:?DEVOPS_APTLY_ROOT_SUBDIR must be set before DevOps provisioning}"
  : "${DEVOPS_APTLY_GPG_SIGNING_KEY:?DEVOPS_APTLY_GPG_SIGNING_KEY must be set before DevOps provisioning}"
  : "${DEVOPS_APTLY_R2_ENDPOINT_URL:?DEVOPS_APTLY_R2_ENDPOINT_URL must be set before DevOps provisioning}"
  : "${DEVOPS_APTLY_R2_ENDPOINT_NAME:?DEVOPS_APTLY_R2_ENDPOINT_NAME must be set before DevOps provisioning}"
  : "${DEVOPS_APTLY_R2_BUCKET:?DEVOPS_APTLY_R2_BUCKET must be set before DevOps provisioning}"
  : "${DEVOPS_APTLY_R2_PREFIX:?DEVOPS_APTLY_R2_PREFIX must be set before DevOps provisioning}"
  : "${DEVOPS_APTLY_DISTRIBUTIONS:?DEVOPS_APTLY_DISTRIBUTIONS must be set before DevOps provisioning}"
  : "${DEVOPS_APTLY_COMPONENT:?DEVOPS_APTLY_COMPONENT must be set before DevOps provisioning}"
  : "${DEVOPS_APTLY_WORKER_ROUTE:?DEVOPS_APTLY_WORKER_ROUTE must be set before DevOps provisioning}"
  : "${DEVOPS_APTLY_WORKER_ZONE:?DEVOPS_APTLY_WORKER_ZONE must be set before DevOps provisioning}"
  : "${DEVOPS_APTLY_PUBLIC_BASE_URL:?DEVOPS_APTLY_PUBLIC_BASE_URL must be set before DevOps provisioning}"
  : "${DEVOPS_APTLY_REPOSITORY_KEY_FINGERPRINT:?DEVOPS_APTLY_REPOSITORY_KEY_FINGERPRINT must be set before DevOps provisioning}"
  : "${DEVOPS_OSC_STATE_SUBDIR:?DEVOPS_OSC_STATE_SUBDIR must be set before DevOps provisioning}"
  : "${DEVOPS_OSC_CACHE_SUBDIR:?DEVOPS_OSC_CACHE_SUBDIR must be set before DevOps provisioning}"
  : "${DEVOPS_OSC_BUILD_SUBDIR:?DEVOPS_OSC_BUILD_SUBDIR must be set before DevOps provisioning}"
  : "${DEVOPS_OBS_API_URL:?DEVOPS_OBS_API_URL must be set before DevOps provisioning}"
  : "${DEVOPS_OBS_PROJECT:?DEVOPS_OBS_PROJECT must be set before DevOps provisioning}"
  : "${DEVOPS_OBS_REPOSITORY:?DEVOPS_OBS_REPOSITORY must be set before DevOps provisioning}"
  : "${DEVOPS_OSC_CREDENTIALS_BACKEND:?DEVOPS_OSC_CREDENTIALS_BACKEND must be set before DevOps provisioning}"

  devops_validate_relative_path "DEVOPS_APTLY_ROOT_SUBDIR" "$DEVOPS_APTLY_ROOT_SUBDIR"
  devops_validate_aptly_signing_key_path \
    "DEVOPS_APTLY_GPG_SIGNING_KEY" \
    "$DEVOPS_APTLY_GPG_SIGNING_KEY"
  devops_validate_openpgp_fingerprint \
    "DEVOPS_APTLY_REPOSITORY_KEY_FINGERPRINT" \
    "$DEVOPS_APTLY_REPOSITORY_KEY_FINGERPRINT"
  devops_validate_relative_path "DEVOPS_OSC_STATE_SUBDIR" "$DEVOPS_OSC_STATE_SUBDIR"
  devops_validate_relative_path "DEVOPS_OSC_CACHE_SUBDIR" "$DEVOPS_OSC_CACHE_SUBDIR"
  devops_validate_relative_path "DEVOPS_OSC_BUILD_SUBDIR" "$DEVOPS_OSC_BUILD_SUBDIR"

  [ "$DEVOPS_APTLY_ROOT_SUBDIR" = aptly ] ||
    devops_fatal "DEVOPS_APTLY_ROOT_SUBDIR must remain aptly"
  [ "$DEVOPS_OSC_STATE_SUBDIR" = osc ] ||
    devops_fatal "DEVOPS_OSC_STATE_SUBDIR must remain osc"
  [ "$DEVOPS_OSC_CACHE_SUBDIR" = osc ] ||
    devops_fatal "DEVOPS_OSC_CACHE_SUBDIR must remain osc"
  [ "$DEVOPS_OSC_BUILD_SUBDIR" = osc ] ||
    devops_fatal "DEVOPS_OSC_BUILD_SUBDIR must remain osc"
  [ "$DEVOPS_APTLY_R2_ENDPOINT_URL" = "https://79cc1f5f831fb7f414638c3e758e9710.r2.cloudflarestorage.com" ] ||
    devops_fatal "DEVOPS_APTLY_R2_ENDPOINT_URL must remain the managed Cloudflare R2 endpoint"
  [ "$DEVOPS_APTLY_R2_ENDPOINT_NAME" = r2 ] ||
    devops_fatal "DEVOPS_APTLY_R2_ENDPOINT_NAME must remain r2"
  [ "$DEVOPS_APTLY_R2_BUCKET" = cf-aptly-r2-prod ] ||
    devops_fatal "DEVOPS_APTLY_R2_BUCKET must remain cf-aptly-r2-prod"
  [ "$DEVOPS_APTLY_R2_PREFIX" = /debian ] ||
    devops_fatal "DEVOPS_APTLY_R2_PREFIX must remain /debian"
  [ "$DEVOPS_APTLY_DISTRIBUTIONS" = "stable testing" ] ||
    devops_fatal "DEVOPS_APTLY_DISTRIBUTIONS must remain stable testing"
  [ "$DEVOPS_APTLY_COMPONENT" = main ] ||
    devops_fatal "DEVOPS_APTLY_COMPONENT must remain main"
  [ "$DEVOPS_APTLY_WORKER_ROUTE" = apt ] ||
    devops_fatal "DEVOPS_APTLY_WORKER_ROUTE must remain apt"
  [ "$DEVOPS_APTLY_WORKER_ZONE" = jcramer.xyz ] ||
    devops_fatal "DEVOPS_APTLY_WORKER_ZONE must remain jcramer.xyz"
  [ "$DEVOPS_APTLY_PUBLIC_BASE_URL" = "https://${DEVOPS_APTLY_WORKER_ROUTE}.${DEVOPS_APTLY_WORKER_ZONE}" ] ||
    devops_fatal "DEVOPS_APTLY_PUBLIC_BASE_URL must match the Worker hostname; the Worker strips the internal R2 prefix"
  [ "$DEVOPS_OBS_API_URL" = https://api.opensuse.org ] ||
    devops_fatal "DEVOPS_OBS_API_URL must remain https://api.opensuse.org"
  [ "$DEVOPS_OBS_PROJECT" = home:cramerz:debian ] ||
    devops_fatal "DEVOPS_OBS_PROJECT must remain home:cramerz:debian"
  [ "$DEVOPS_OBS_REPOSITORY" = Debian_Unstable ] ||
    devops_fatal "DEVOPS_OBS_REPOSITORY must remain Debian_Unstable"
  [ "$DEVOPS_OSC_CREDENTIALS_BACKEND" = keyring.backends.SecretService.Keyring ] ||
    devops_fatal "DEVOPS_OSC_CREDENTIALS_BACKEND must remain the Secret Service backend"
}

devops_load_publishing_credentials() {
  DEVOPS_CF_R2_ACCESS_KEY=$(installer_cmdline_value cf_r2_access_key 2>/dev/null || true)
  DEVOPS_CF_R2_SECRET_KEY=$(installer_cmdline_value cf_r2_secret_key 2>/dev/null || true)
  DEVOPS_OBS_USERNAME=$(installer_cmdline_value obs_username 2>/dev/null || true)
  DEVOPS_OBS_PASSWORD=$(installer_cmdline_value obs_password 2>/dev/null || true)

  [ -n "$DEVOPS_CF_R2_ACCESS_KEY" ] ||
    devops_fatal "addon/devops requires cf_r2_access_key on the kernel cmdline or in /preseed.env"
  [ -n "$DEVOPS_CF_R2_SECRET_KEY" ] ||
    devops_fatal "addon/devops requires cf_r2_secret_key on the kernel cmdline or in /preseed.env"
  [ -n "$DEVOPS_OBS_USERNAME" ] ||
    devops_fatal "addon/devops requires obs_username on the kernel cmdline or in /preseed.env"
  [ -n "$DEVOPS_OBS_PASSWORD" ] ||
    devops_fatal "addon/devops requires obs_password on the kernel cmdline or in /preseed.env"

  [ "${#DEVOPS_CF_R2_ACCESS_KEY}" -eq 32 ] ||
    devops_fatal "cf_r2_access_key must be a 32-character hexadecimal R2 access key id"
  case "$DEVOPS_CF_R2_ACCESS_KEY" in
    *[!0123456789abcdefABCDEF]*)
      devops_fatal "cf_r2_access_key must be a 32-character hexadecimal R2 access key id"
      ;;
  esac
  [ "${#DEVOPS_CF_R2_SECRET_KEY}" -eq 64 ] ||
    devops_fatal "cf_r2_secret_key must be a 64-character hexadecimal R2 secret access key"
  case "$DEVOPS_CF_R2_SECRET_KEY" in
    *[!0123456789abcdefABCDEF]*)
      devops_fatal "cf_r2_secret_key must be a 64-character hexadecimal R2 secret access key"
      ;;
  esac
  if ! printf '%s\n' "$DEVOPS_OBS_USERNAME" |
    LC_ALL=C grep -Eq '^[A-Za-z0-9_.@+-]+$'
  then
    devops_fatal "obs_username contains unsupported characters"
  fi
  [ "${#DEVOPS_OBS_USERNAME}" -le 255 ] ||
    devops_fatal "obs_username exceeds 255 characters"
  [ "${#DEVOPS_OBS_PASSWORD}" -le 4096 ] ||
    devops_fatal "obs_password exceeds 4096 characters"
  if ! printf '%s\n' "$DEVOPS_OBS_PASSWORD" |
    LC_ALL=C grep -Eq '^[[:graph:]]+$'
  then
    devops_fatal "obs_password must be one printable token without whitespace"
  fi
}

devops_validate_codex_policy() {
  # These are fixed addon/devops prerequisites rather than host-specific
  # tuning. Supply the exact class defaults when an earlier installer seed
  # cache predates the profile entries, then validate them below as usual.
  : "${DEVOPS_CODEX_BWRAP_USERNS_CLONE:=1}"
  : "${DEVOPS_CODEX_BWRAP_MAX_USER_NAMESPACES:=1024}"

  : "${DEVOPS_CODEX_VERSION:?DEVOPS_CODEX_VERSION must be set before DevOps provisioning}"
  : "${DEVOPS_CODEX_STANDALONE_INSTALLER_URL:?DEVOPS_CODEX_STANDALONE_INSTALLER_URL must be set before DevOps provisioning}"
  : "${DEVOPS_CODEX_STANDALONE_INSTALLER_MAXIMUM_BYTES:?DEVOPS_CODEX_STANDALONE_INSTALLER_MAXIMUM_BYTES must be set before DevOps provisioning}"
  : "${DEVOPS_CODEX_RELEASE_TAG:?DEVOPS_CODEX_RELEASE_TAG must be set before DevOps provisioning}"
  : "${DEVOPS_CODEX_URL:?DEVOPS_CODEX_URL must be set before DevOps provisioning}"
  : "${DEVOPS_CODEX_SHA256:?DEVOPS_CODEX_SHA256 must be set before DevOps provisioning}"
  : "${DEVOPS_CODEX_MAXIMUM_BYTES:?DEVOPS_CODEX_MAXIMUM_BYTES must be set before DevOps provisioning}"
  : "${DEVOPS_CODEX_MAXIMUM_EXTRACTED_BYTES:?DEVOPS_CODEX_MAXIMUM_EXTRACTED_BYTES must be set before DevOps provisioning}"
  : "${DEVOPS_CODEX_ARCHIVE_BINARY_DIR:?DEVOPS_CODEX_ARCHIVE_BINARY_DIR must be set before DevOps provisioning}"
  : "${DEVOPS_CODEX_ARCHIVE_SCHEMA_MEMBER:?DEVOPS_CODEX_ARCHIVE_SCHEMA_MEMBER must be set before DevOps provisioning}"
  : "${DEVOPS_CODEX_ROOT:?DEVOPS_CODEX_ROOT must be set before DevOps provisioning}"
  : "${DEVOPS_CODEX_BINARY_PATH:?DEVOPS_CODEX_BINARY_PATH must be set before DevOps provisioning}"
  : "${DEVOPS_CODEX_SCHEMA_PATH:?DEVOPS_CODEX_SCHEMA_PATH must be set before DevOps provisioning}"
  : "${DEVOPS_CODEX_WRAPPER_PATH:?DEVOPS_CODEX_WRAPPER_PATH must be set before DevOps provisioning}"
  : "${DEVOPS_CODEX_USER_ROOT:?DEVOPS_CODEX_USER_ROOT must be set before DevOps provisioning}"
  : "${DEVOPS_CODEX_SYSTEM_CONFIG_DIR:?DEVOPS_CODEX_SYSTEM_CONFIG_DIR must be set before DevOps provisioning}"
  : "${DEVOPS_CODEX_LOG_DIR:?DEVOPS_CODEX_LOG_DIR must be set before DevOps provisioning}"
  : "${DEVOPS_CODEX_SQLITE_HOME:?DEVOPS_CODEX_SQLITE_HOME must be set before DevOps provisioning}"
  : "${DEVOPS_CODEX_RUNTIME_ROOT:?DEVOPS_CODEX_RUNTIME_ROOT must be set before DevOps provisioning}"
  : "${DEVOPS_CODEX_REPOSITORY_URL:?DEVOPS_CODEX_REPOSITORY_URL must be set before DevOps provisioning}"
  : "${DEVOPS_CODEX_REPOSITORY_BRANCH:?DEVOPS_CODEX_REPOSITORY_BRANCH must be set before DevOps provisioning}"
  : "${DEVOPS_CODEX_REPOSITORY_COMMIT:?DEVOPS_CODEX_REPOSITORY_COMMIT must be set before DevOps provisioning}"
  : "${DEVOPS_CODEX_AGENTS:?DEVOPS_CODEX_AGENTS must be set before DevOps provisioning}"
  : "${DEVOPS_CODEX_HOME:?DEVOPS_CODEX_HOME must be set before DevOps provisioning}"
  : "${DEVOPS_CODEX_SKILLS:?DEVOPS_CODEX_SKILLS must be set before DevOps provisioning}"

  if ! printf '%s\n' "$DEVOPS_CODEX_VERSION" |
    LC_ALL=C grep -Eq '^[A-Za-z0-9][A-Za-z0-9._+-]*$'
  then
    devops_fatal "DEVOPS_CODEX_VERSION contains unsupported syntax: $DEVOPS_CODEX_VERSION"
  fi
  [ "$DEVOPS_CODEX_STANDALONE_INSTALLER_URL" = https://chatgpt.com/codex/install.sh ] ||
    devops_fatal "DEVOPS_CODEX_STANDALONE_INSTALLER_URL must remain the approved ChatGPT HTTPS installer"
  devops_validate_positive_integer \
    "DEVOPS_CODEX_STANDALONE_INSTALLER_MAXIMUM_BYTES" \
    "$DEVOPS_CODEX_STANDALONE_INSTALLER_MAXIMUM_BYTES"
  [ "$DEVOPS_CODEX_STANDALONE_INSTALLER_MAXIMUM_BYTES" -le 1048576 ] ||
    devops_fatal "DEVOPS_CODEX_STANDALONE_INSTALLER_MAXIMUM_BYTES must not exceed 1048576"
  if ! printf '%s\n' "$DEVOPS_CODEX_RELEASE_TAG" |
    LC_ALL=C grep -Eq '^[A-Za-z0-9][A-Za-z0-9._+-]*$'
  then
    devops_fatal "DEVOPS_CODEX_RELEASE_TAG contains unsupported syntax: $DEVOPS_CODEX_RELEASE_TAG"
  fi
  if ! printf '%s\n' "$DEVOPS_CODEX_URL" |
    LC_ALL=C grep -Eq '^https://[^[:space:]]+$'
  then
    devops_fatal "DEVOPS_CODEX_URL must be a whitespace-free HTTPS URL"
  fi

  [ "${#DEVOPS_CODEX_SHA256}" -eq 64 ] ||
    devops_fatal "DEVOPS_CODEX_SHA256 must be a lowercase SHA-256 digest"
  case "$DEVOPS_CODEX_SHA256" in
    *[!0123456789abcdef]*)
      devops_fatal "DEVOPS_CODEX_SHA256 must be a lowercase SHA-256 digest"
      ;;
  esac
  devops_validate_positive_integer "DEVOPS_CODEX_MAXIMUM_BYTES" "$DEVOPS_CODEX_MAXIMUM_BYTES"
  devops_validate_positive_integer \
    "DEVOPS_CODEX_MAXIMUM_EXTRACTED_BYTES" \
    "$DEVOPS_CODEX_MAXIMUM_EXTRACTED_BYTES"

  devops_validate_relative_path \
    "DEVOPS_CODEX_ARCHIVE_BINARY_DIR" \
    "$DEVOPS_CODEX_ARCHIVE_BINARY_DIR"
  case "$DEVOPS_CODEX_ARCHIVE_BINARY_DIR" in
    */*) devops_fatal "DEVOPS_CODEX_ARCHIVE_BINARY_DIR must be one directory name" ;;
  esac
  devops_validate_relative_path \
    "DEVOPS_CODEX_ARCHIVE_SCHEMA_MEMBER" \
    "$DEVOPS_CODEX_ARCHIVE_SCHEMA_MEMBER"
  case "$DEVOPS_CODEX_ARCHIVE_SCHEMA_MEMBER" in
    */*) devops_fatal "DEVOPS_CODEX_ARCHIVE_SCHEMA_MEMBER must be a root file name" ;;
  esac

  devops_validate_abs_path "DEVOPS_CODEX_ROOT" "$DEVOPS_CODEX_ROOT"
  devops_validate_abs_path "DEVOPS_CODEX_BINARY_PATH" "$DEVOPS_CODEX_BINARY_PATH"
  devops_validate_abs_path "DEVOPS_CODEX_SCHEMA_PATH" "$DEVOPS_CODEX_SCHEMA_PATH"
  devops_validate_abs_path "DEVOPS_CODEX_WRAPPER_PATH" "$DEVOPS_CODEX_WRAPPER_PATH"
  devops_validate_abs_path "DEVOPS_CODEX_USER_ROOT" "$DEVOPS_CODEX_USER_ROOT"
  devops_validate_abs_path \
    "DEVOPS_CODEX_SYSTEM_CONFIG_DIR" \
    "$DEVOPS_CODEX_SYSTEM_CONFIG_DIR"
  devops_validate_abs_path "DEVOPS_CODEX_LOG_DIR" "$DEVOPS_CODEX_LOG_DIR"
  devops_validate_abs_path "DEVOPS_CODEX_SQLITE_HOME" "$DEVOPS_CODEX_SQLITE_HOME"
  devops_validate_abs_path "DEVOPS_CODEX_RUNTIME_ROOT" "$DEVOPS_CODEX_RUNTIME_ROOT"
  devops_validate_abs_path "DEVOPS_CODEX_AGENTS" "$DEVOPS_CODEX_AGENTS"
  devops_validate_abs_path "DEVOPS_CODEX_HOME" "$DEVOPS_CODEX_HOME"
  devops_validate_abs_path "DEVOPS_CODEX_SKILLS" "$DEVOPS_CODEX_SKILLS"
  devops_validate_abs_path \
    "managed Codex host log directory" \
    "$devops_codex_host_log_dir"

  [ "$DEVOPS_CODEX_ROOT" = /data/codex ] ||
    devops_fatal "DEVOPS_CODEX_ROOT must remain /data/codex"
  [ "$DEVOPS_CODEX_BINARY_PATH" = "${DEVOPS_CODEX_ROOT}/share/bin/codex" ] ||
    devops_fatal "DEVOPS_CODEX_BINARY_PATH must remain ${DEVOPS_CODEX_ROOT}/share/bin/codex"
  [ "$DEVOPS_CODEX_SCHEMA_PATH" = "${DEVOPS_CODEX_ROOT}/${DEVOPS_CODEX_ARCHIVE_SCHEMA_MEMBER}" ] ||
    devops_fatal "DEVOPS_CODEX_SCHEMA_PATH must match the profile-owned archive schema member"
  [ "$DEVOPS_CODEX_WRAPPER_PATH" = "${DEVOPS_CODEX_ROOT}/lib/codex" ] ||
    devops_fatal "DEVOPS_CODEX_WRAPPER_PATH must remain ${DEVOPS_CODEX_ROOT}/lib/codex"
  [ "$DEVOPS_CODEX_USER_ROOT" = "${DEVOPS_CODEX_ROOT}/usr" ] ||
    devops_fatal "DEVOPS_CODEX_USER_ROOT must remain ${DEVOPS_CODEX_ROOT}/usr"
  [ "$DEVOPS_CODEX_SYSTEM_CONFIG_DIR" = /etc/codex ] ||
    devops_fatal "DEVOPS_CODEX_SYSTEM_CONFIG_DIR must remain /etc/codex"
  [ "$DEVOPS_CODEX_LOG_DIR" = "${DEVOPS_CODEX_ROOT}/log" ] ||
    devops_fatal "DEVOPS_CODEX_LOG_DIR must remain ${DEVOPS_CODEX_ROOT}/log"
  [ "$DEVOPS_CODEX_SQLITE_HOME" = "${DEVOPS_CODEX_ROOT}/sqlite" ] ||
    devops_fatal "DEVOPS_CODEX_SQLITE_HOME must remain ${DEVOPS_CODEX_ROOT}/sqlite"
  [ "$DEVOPS_CODEX_RUNTIME_ROOT" = "${DEVOPS_CODEX_ROOT}/runtime" ] ||
    devops_fatal "DEVOPS_CODEX_RUNTIME_ROOT must remain ${DEVOPS_CODEX_ROOT}/runtime"
  [ "$DEVOPS_CODEX_AGENTS" = "${DEVOPS_CODEX_USER_ROOT}/agents" ] ||
    devops_fatal "DEVOPS_CODEX_AGENTS must remain ${DEVOPS_CODEX_USER_ROOT}/agents"
  [ "$DEVOPS_CODEX_HOME" = "${DEVOPS_CODEX_USER_ROOT}/home" ] ||
    devops_fatal "DEVOPS_CODEX_HOME must remain ${DEVOPS_CODEX_USER_ROOT}/home"
  [ "$DEVOPS_CODEX_SKILLS" = "${DEVOPS_CODEX_USER_ROOT}/skills" ] ||
    devops_fatal "DEVOPS_CODEX_SKILLS must remain ${DEVOPS_CODEX_USER_ROOT}/skills"
  [ "$devops_codex_host_log_dir" = /var/log/managed/openai/codex ] ||
    devops_fatal "managed Codex host log directory must remain /var/log/managed/openai/codex"
  [ "$DEVOPS_CODEX_BWRAP_USERNS_CLONE" = 1 ] ||
    devops_fatal "DEVOPS_CODEX_BWRAP_USERNS_CLONE must remain 1 for Bubblewrap"
  devops_validate_positive_integer \
    "DEVOPS_CODEX_BWRAP_MAX_USER_NAMESPACES" \
    "$DEVOPS_CODEX_BWRAP_MAX_USER_NAMESPACES"
  [ "$DEVOPS_CODEX_BWRAP_MAX_USER_NAMESPACES" -eq 1024 ] ||
    devops_fatal "DEVOPS_CODEX_BWRAP_MAX_USER_NAMESPACES must remain 1024"

  [ "$DEVOPS_CODEX_REPOSITORY_URL" = https://github.com/mjcramerz/codex-home ] ||
    devops_fatal "DEVOPS_CODEX_REPOSITORY_URL must remain the approved HTTPS repository"
  [ "$DEVOPS_CODEX_REPOSITORY_BRANCH" = mcr/main ] ||
    devops_fatal "DEVOPS_CODEX_REPOSITORY_BRANCH must remain mcr/main"
  [ "${#DEVOPS_CODEX_REPOSITORY_COMMIT}" -eq 40 ] ||
    devops_fatal "DEVOPS_CODEX_REPOSITORY_COMMIT must contain exactly 40 lowercase hexadecimal characters (got ${#DEVOPS_CODEX_REPOSITORY_COMMIT})"
  case "$DEVOPS_CODEX_REPOSITORY_COMMIT" in
    *[!0123456789abcdef]*)
      devops_fatal "DEVOPS_CODEX_REPOSITORY_COMMIT must contain exactly 40 lowercase hexadecimal characters"
      ;;
  esac
}

devops_target_passwd_ids() {
  awk -F: -v wanted_user="$1" '$1 == wanted_user { print $3 ":" $4; exit }' \
    "${target_root}/etc/passwd" 2>/dev/null || true
}

devops_stage_target_asset() {
  repo_path=$1
  target_path=$2
  mode=$3
  asset_name=$4
  target_host_path="${target_root}${target_path}"
  tmp_asset="${tmp_env_dir}/${asset_name}.$$"

  devops_validate_abs_path "target path" "$target_path"
  bootstrap_fetch_seed_file \
    "$seed_base" \
    "$repo_path" \
    "$tmp_asset" \
    0600 \
    "DevOps target asset ${repo_path}"
  [ -d "${target_root}$(dirname "$target_path")" ] ||
    devops_fatal "required DevOps target directory is missing: ${target_root}$(dirname "$target_path")"
  install -m "$mode" "$tmp_asset" "$target_host_path"
  rm -f -- "$tmp_asset"
}

devops_prepare_publishing_layout() {
  # shellcheck disable=SC2016
  run_in_target "create account-local Aptly and osc publication directories" /bin/sh -eu -c '
account_user=$1
build_root=$2
cache_root=$3
db_root=$4
osc_build_subdir=$5
osc_cache_subdir=$6
aptly_state_subdir=$7
osc_state_subdir=$8

for required_command in chmod getent id install; do
  command -v "$required_command" >/dev/null 2>&1 || {
    printf "fatal: required publication setup command is unavailable: %s\n" "$required_command" >&2
    exit 1
  }
done
getent group devops >/dev/null 2>&1 || {
  printf "fatal: required publication group is missing: devops\n" >&2
  exit 1
}
account_uid=$(id -u "$account_user")
account_gid=$(id -g "$account_user")

for shared_path in \
  "$build_root/$account_user/$osc_build_subdir" \
  "$build_root/$account_user/$osc_build_subdir/build-root" \
  "$cache_root/$account_user/$osc_cache_subdir" \
  "$cache_root/$account_user/$osc_cache_subdir/packages"
do
  install -d -m 2770 -o "$account_uid" -g devops -- "$shared_path"
done
for private_path in \
  "$db_root/$account_user/$aptly_state_subdir" \
  "$db_root/$account_user/$aptly_state_subdir/.credentials.pending" \
  "$db_root/$account_user/$osc_state_subdir" \
  "$db_root/$account_user/$osc_state_subdir/.credentials.pending"
do
  [ ! -L "$private_path" ] || {
    printf "fatal: private publication path is a symlink: %s\n" "$private_path" >&2
    exit 1
  }
  install -d -m 0700 -o "$account_uid" -g "$account_gid" -- "$private_path"
  [ -d "$private_path" ] && [ ! -L "$private_path" ] || {
    printf "fatal: private publication path is not a direct directory: %s\n" "$private_path" >&2
    exit 1
  }
  # The account DB root is setgid for shared DevOps state, so a newly created
  # private child inherits that special bit even when install requests 0700.
  chmod a-s -- "$private_path"
  chmod 0700 -- "$private_path"
done
' sh \
    "$ACCOUNT_USERNAME" \
    "$DIR_POOL_BUILD" \
    "$DIR_POOL_CACHE" \
    "$DIR_POOL_DB" \
    "$DEVOPS_OSC_BUILD_SUBDIR" \
    "$DEVOPS_OSC_CACHE_SUBDIR" \
    "$DEVOPS_APTLY_ROOT_SUBDIR" \
    "$DEVOPS_OSC_STATE_SUBDIR"
}

devops_render_aptly_config() {
  template_repo_path=$(installer_repo_join_var \
    DIR_SCRIPTS_LATE \
    templates/devops/aptly.conf.tmpl)
  template_tmp="${tmp_env_dir}/aptly.conf.tmpl.$$"
  rendered_tmp="${tmp_env_dir}/aptly.conf.rendered.$$"
  target_config="${target_root}${APTLY_CONFIG}"

  bootstrap_fetch_seed_file \
    "$seed_base" \
    "$template_repo_path" \
    "$template_tmp" \
    0600 \
    "DevOps Aptly config template ${template_repo_path}"
  installer_apply_scalar_placeholders \
    "$template_tmp" \
    "$rendered_tmp" \
    ACCOUNT_USERNAME "$ACCOUNT_USERNAME" \
    DEVOPS_APTLY_ROOT_DIR "$APTLY_ROOT_DIR" \
    DEVOPS_APTLY_R2_ENDPOINT_NAME "$DEVOPS_APTLY_R2_ENDPOINT_NAME" \
    DEVOPS_APTLY_R2_BUCKET "$DEVOPS_APTLY_R2_BUCKET" \
    DEVOPS_APTLY_R2_ENDPOINT_URL "$DEVOPS_APTLY_R2_ENDPOINT_URL" \
    DEVOPS_APTLY_R2_STORAGE_PREFIX "$APTLY_R2_STORAGE_PREFIX" \
    DEVOPS_APTLY_DISTRIBUTIONS "$DEVOPS_APTLY_DISTRIBUTIONS" \
    DEVOPS_APTLY_COMPONENT "$DEVOPS_APTLY_COMPONENT" \
    DEVOPS_APTLY_PUBLISH_TARGET "s3:${DEVOPS_APTLY_R2_ENDPOINT_NAME}:" \
    DEVOPS_APTLY_WORKER_ROUTE "$DEVOPS_APTLY_WORKER_ROUTE" \
    DEVOPS_APTLY_WORKER_ZONE "$DEVOPS_APTLY_WORKER_ZONE" \
    DEVOPS_APTLY_PUBLIC_BASE_URL "$DEVOPS_APTLY_PUBLIC_BASE_URL" \
    DEVOPS_APTLY_REPOSITORY_KEY_FINGERPRINT "$DEVOPS_APTLY_REPOSITORY_KEY_FINGERPRINT" \
    DEVOPS_APTLY_CREDENTIALS_BACKEND "$DEVOPS_OSC_CREDENTIALS_BACKEND"
  installer_assert_no_unresolved_installer_placeholders \
    "$rendered_tmp" \
    "DevOps Aptly config template ${template_repo_path}"

  [ -d "${target_root}${APTLY_ROOT_DIR}" ] ||
    devops_fatal "required Aptly root directory is missing: ${target_root}${APTLY_ROOT_DIR}"
  install -m 0600 "$rendered_tmp" "$target_config"
  chown "$account_ids" "$target_config"
  run_in_target \
    "validate rendered Aptly JSON config" \
    /usr/bin/python3 -m json.tool "$APTLY_CONFIG" >/dev/null
  rm -f -- "$template_tmp" "$rendered_tmp"
}

devops_import_aptly_signing_key() (
  signing_device=/dev/sda2
  signing_profile_path=$DEVOPS_APTLY_GPG_SIGNING_KEY
  signing_key_name=${signing_profile_path##*/}
  signing_initrd_key="/${signing_key_name}"
  signing_maximum_bytes=1048576
  signing_copy_block_bytes=4096
  signing_mountpoint=
  signing_source_key=
  staged_host_key=

  devops_cleanup_aptly_signing_key() {
    cleanup_status=$1
    trap - EXIT HUP INT TERM

    if [ -n "$staged_host_key" ]; then
      if ! rm -f -- "$staged_host_key"; then
        printf 'fatal: unable to remove the transient Aptly signing-key copy\n' >&2
        [ "$cleanup_status" -ne 0 ] || cleanup_status=1
      fi
    fi

    if [ -n "$signing_mountpoint" ] &&
       installer_mounts_has_mountpoint "$signing_mountpoint"
    then
      if ! umount "$signing_mountpoint"; then
        printf 'fatal: unable to unmount the Aptly signing-key medium\n' >&2
        [ "$cleanup_status" -ne 0 ] || cleanup_status=1
      fi
    fi

    if [ -n "$signing_mountpoint" ] && [ -d "$signing_mountpoint" ]; then
      if ! rmdir "$signing_mountpoint"; then
        printf 'fatal: unable to remove the Aptly signing-key mountpoint\n' >&2
        [ "$cleanup_status" -ne 0 ] || cleanup_status=1
      fi
    fi

    exit "$cleanup_status"
  }

  trap 'devops_cleanup_aptly_signing_key "$?"' EXIT
  trap 'devops_cleanup_aptly_signing_key 129' HUP
  trap 'devops_cleanup_aptly_signing_key 130' INT
  trap 'devops_cleanup_aptly_signing_key 143' TERM

  for required_command in chown cmp dd mktemp mount readlink tr umount wc; do
    command -v "$required_command" >/dev/null 2>&1 ||
      devops_fatal "required Aptly signing-key import command is unavailable: $required_command"
  done

  if [ -b "$signing_device" ]; then
    signing_mountpoint=$(mktemp -d "${tmp_env_dir}/aptly-signing-media.XXXXXX") ||
      devops_fatal "unable to allocate the Aptly signing-key mountpoint"
    chmod 0700 "$signing_mountpoint"
    installer_mounts_has_mountpoint "$signing_mountpoint" &&
      devops_fatal "new Aptly signing-key mountpoint is unexpectedly already mounted"

    if ! mount -o ro,nosuid,nodev,noexec "$signing_device" "$signing_mountpoint"; then
      devops_fatal "unable to mount the Aptly signing-key device read-only: $signing_device"
    fi
    installer_mounts_find_record "$signing_mountpoint" ||
      devops_fatal "Aptly signing-key mount is absent after mount completed"
    same_device_path "$INSTALLER_MOUNT_SOURCE" "$signing_device" ||
      devops_fatal "Aptly signing-key mount source does not match $signing_device"
    for required_option in ro nosuid nodev noexec; do
      case ",$INSTALLER_MOUNT_OPTIONS," in
        *",${required_option},"*) ;;
        *)
          devops_fatal "Aptly signing-key mount is missing required option: $required_option"
          ;;
      esac
    done

    signing_directory="${signing_mountpoint}/aptly-signing"
    signing_media_key="${signing_mountpoint}${signing_profile_path}"
    if [ -e "$signing_directory" ] || [ -L "$signing_directory" ]; then
      [ -d "$signing_directory" ] && [ ! -L "$signing_directory" ] ||
        devops_fatal "Aptly signing-key directory on $signing_device is not a regular directory"
    fi
    if [ -e "$signing_media_key" ] || [ -L "$signing_media_key" ]; then
      [ -d "$signing_directory" ] && [ ! -L "$signing_directory" ] ||
        devops_fatal "Aptly signing-key directory on $signing_device is missing or unsafe"
      [ -f "$signing_media_key" ] &&
        [ ! -L "$signing_media_key" ] &&
        [ -r "$signing_media_key" ] ||
        devops_fatal "Aptly signing-key source on $signing_device must be a readable regular non-symlink file"

      signing_mountpoint_real=$(readlink -f -- "$signing_mountpoint") ||
        devops_fatal "unable to resolve the Aptly signing-key mountpoint"
      signing_directory_real=$(readlink -f -- "$signing_directory") ||
        devops_fatal "unable to resolve the Aptly signing-key directory"
      signing_media_key_real=$(readlink -f -- "$signing_media_key") ||
        devops_fatal "unable to resolve the Aptly signing-key source on $signing_device"
      [ "$signing_directory_real" = "${signing_mountpoint_real}/aptly-signing" ] &&
        [ "$signing_media_key_real" = "${signing_directory_real}/${signing_key_name}" ] ||
        devops_fatal "Aptly signing-key source escaped the mounted aptly-signing directory"
      signing_source_key=$signing_media_key
    else
      if ! umount "$signing_mountpoint"; then
        devops_fatal "unable to unmount the Aptly signing-key medium before initrd fallback"
      fi
      installer_mounts_has_mountpoint "$signing_mountpoint" &&
        devops_fatal "Aptly signing-key medium remains mounted before initrd fallback"
      rmdir "$signing_mountpoint" ||
        devops_fatal "unable to remove the Aptly signing-key mountpoint before initrd fallback"
      signing_mountpoint=
    fi
  fi

  if [ -z "$signing_source_key" ]; then
    if [ ! -e "$signing_initrd_key" ] && [ ! -L "$signing_initrd_key" ]; then
      devops_fatal "Aptly signing key is absent from both ${signing_device}${signing_profile_path} and ${signing_initrd_key}"
    fi
    [ -f "$signing_initrd_key" ] &&
      [ ! -L "$signing_initrd_key" ] &&
      [ -r "$signing_initrd_key" ] ||
      devops_fatal "Aptly signing-key initrd fallback must be a readable regular non-symlink file: $signing_initrd_key"
    signing_initrd_key_real=$(readlink -f -- "$signing_initrd_key") ||
      devops_fatal "unable to resolve the Aptly signing-key initrd fallback"
    [ "$signing_initrd_key_real" = "$signing_initrd_key" ] ||
      devops_fatal "Aptly signing-key initrd fallback escaped the d-i root"
    signing_source_key=$signing_initrd_key
  fi

  umask 077
  staged_host_key=$(mktemp "${target_root}${APTLY_ROOT_DIR}/.aptly-signing-key.XXXXXX") ||
    devops_fatal "unable to allocate the transient Aptly signing-key copy"
  staged_key_name=${staged_host_key##*/}
  case "$staged_key_name" in
    .aptly-signing-key.*) ;;
    *) devops_fatal "transient Aptly signing-key name is invalid" ;;
  esac
  staged_target_key="${APTLY_ROOT_DIR}/${staged_key_name}"
  signing_copy_block_count=$((
    signing_maximum_bytes / signing_copy_block_bytes + 1
  ))
  if ! dd \
    if="$signing_source_key" \
    of="$staged_host_key" \
    bs="$signing_copy_block_bytes" \
    count="$signing_copy_block_count" \
    2>/dev/null
  then
    devops_fatal "unable to copy the bounded Aptly signing key from its selected source"
  fi
  staged_key_bytes_raw=$(wc -c <"$staged_host_key") ||
    devops_fatal "unable to count the transient Aptly signing-key bytes"
  staged_key_bytes=$(printf '%s' "$staged_key_bytes_raw" | tr -d '[:space:]') ||
    devops_fatal "unable to normalize the transient Aptly signing-key size"
  case "$staged_key_bytes" in
    ''|*[!0123456789]*)
      devops_fatal "transient Aptly signing-key size is invalid"
      ;;
  esac
  [ "$staged_key_bytes" -gt 0 ] &&
    [ "$staged_key_bytes" -le "$signing_maximum_bytes" ] ||
    devops_fatal "Aptly signing-key source must be between 1 and ${signing_maximum_bytes} bytes"
  IFS= read -r signing_source_header <"$staged_host_key" ||
    devops_fatal "unable to read the Aptly signing-key armor header"
  [ "$signing_source_header" = '-----BEGIN PGP PRIVATE KEY BLOCK-----' ] ||
    devops_fatal "Aptly signing-key source is not an armored OpenPGP private key"
  chmod 0600 "$staged_host_key"
  chown "$account_ids" "$staged_host_key"
  cmp "$signing_source_key" "$staged_host_key" >/dev/null 2>&1 ||
    devops_fatal "transient Aptly signing-key copy does not match its source"

  if [ -n "$signing_mountpoint" ]; then
    if ! umount "$signing_mountpoint"; then
      devops_fatal "unable to unmount the Aptly signing-key medium before import"
    fi
    installer_mounts_has_mountpoint "$signing_mountpoint" &&
      devops_fatal "Aptly signing-key medium remains mounted after unmount"
    rmdir "$signing_mountpoint" ||
      devops_fatal "unable to remove the Aptly signing-key mountpoint after unmount"
    signing_mountpoint=
  fi

  # BEGIN: managed Aptly signing-key target import
  # shellcheck disable=SC2016
  devops_run_as_account "inspect and import the managed Aptly signing key" /bin/sh -eu -c '
staged_key=$1
account_home=$2
aptly_root=$3
expected_fingerprint=$4
maximum_bytes=$5
gnupg_home="${account_home}/.gnupg"

aptly_signing_key_fatal() {
  printf "fatal: %s\n" "$*" >&2
  exit 1
}

aptly_primary_secret_summary() {
  LC_ALL=C /usr/bin/awk -F: "
    \$1 == \"pub\" || \$1 == \"sec\" {
      primary_count++
      primary_type = \$1
      expect_fingerprint = 1
      next
    }
    expect_fingerprint && \$1 == \"fpr\" {
      printf \"%d:%s:%s\\n\", primary_count, primary_type, toupper(\$10)
      expect_fingerprint = 0
    }
    END {
      if (expect_fingerprint) {
        printf \"%d:%s:\\n\", primary_count, primary_type
      }
    }
  "
}

aptly_signing_capability_count() {
  LC_ALL=C /usr/bin/awk -F: "
    (\$1 == \"sec\" || \$1 == \"ssb\") &&
    index(\$12, \"s\") != 0 {
      signing_capability_count++
    }
    END {
      print signing_capability_count + 0
    }
  "
}

aptly_available_signing_material_count() {
  LC_ALL=C /usr/bin/awk -F: "
    (\$1 == \"sec\" || \$1 == \"ssb\") &&
    index(\$12, \"s\") != 0 &&
    \$15 == \"+\" {
      available_signing_material_count++
    }
    END {
      print available_signing_material_count + 0
    }
  "
}

for required_command in \
  /usr/bin/awk \
  /usr/bin/gpg \
  /usr/bin/id \
  /usr/bin/install \
  /usr/bin/readlink \
  /usr/bin/stat
do
  [ -x "$required_command" ] ||
    aptly_signing_key_fatal "required target command is unavailable: $required_command"
done

case "$maximum_bytes" in
  ""|*[!0123456789]*)
    aptly_signing_key_fatal "Aptly signing-key maximum size is invalid"
    ;;
esac
[ "$maximum_bytes" -gt 0 ] ||
  aptly_signing_key_fatal "Aptly signing-key maximum size must be positive"
case "${#expected_fingerprint}" in
  40|64) ;;
  *) aptly_signing_key_fatal "Aptly signing-key fingerprint length is invalid" ;;
esac
case "$expected_fingerprint" in
  *[!0123456789ABCDEF]*)
    aptly_signing_key_fatal "Aptly signing-key fingerprint is not uppercase hexadecimal"
    ;;
esac

account_uid=$(/usr/bin/id -u)
account_gid=$(/usr/bin/id -g)
[ -d "$account_home" ] && [ ! -L "$account_home" ] ||
  aptly_signing_key_fatal "account home is missing or is a symlink"
[ "$(/usr/bin/stat -c "%u:%g" -- "$account_home")" = "${account_uid}:${account_gid}" ] ||
  aptly_signing_key_fatal "account home is not owned by the target account"
[ -d "$aptly_root" ] && [ ! -L "$aptly_root" ] ||
  aptly_signing_key_fatal "Aptly state root is missing or is a symlink"
[ "$(/usr/bin/stat -c "%u:%g:%a" -- "$aptly_root")" = "${account_uid}:${account_gid}:700" ] ||
  aptly_signing_key_fatal "Aptly state root is not a private account directory"

[ -f "$staged_key" ] && [ ! -L "$staged_key" ] && [ -r "$staged_key" ] ||
  aptly_signing_key_fatal "transient Aptly signing key is not a readable regular file"
aptly_root_real=$(/usr/bin/readlink -f -- "$aptly_root") ||
  aptly_signing_key_fatal "unable to resolve the Aptly state root"
staged_key_real=$(/usr/bin/readlink -f -- "$staged_key") ||
  aptly_signing_key_fatal "unable to resolve the transient Aptly signing key"
case "$staged_key_real" in
  "${aptly_root_real}"/.aptly-signing-key.*) ;;
  *) aptly_signing_key_fatal "transient Aptly signing key escaped its state root" ;;
esac
[ "$(/usr/bin/stat -c "%u:%g:%a" -- "$staged_key")" = "${account_uid}:${account_gid}:600" ] ||
  aptly_signing_key_fatal "transient Aptly signing key is not account-owned mode 0600"
staged_key_bytes=$(/usr/bin/stat -c "%s" -- "$staged_key") ||
  aptly_signing_key_fatal "unable to determine the transient Aptly signing-key size"
case "$staged_key_bytes" in
  ""|*[!0123456789]*)
    aptly_signing_key_fatal "transient Aptly signing-key size is invalid"
    ;;
esac
[ "$staged_key_bytes" -gt 0 ] && [ "$staged_key_bytes" -le "$maximum_bytes" ] ||
  aptly_signing_key_fatal "transient Aptly signing-key size is outside the managed bound"

[ ! -L "$gnupg_home" ] ||
  aptly_signing_key_fatal "target GnuPG home must not be a symlink"
if [ ! -e "$gnupg_home" ]; then
  /usr/bin/install -d -m 0700 -- "$gnupg_home"
fi
[ -d "$gnupg_home" ] && [ ! -L "$gnupg_home" ] ||
  aptly_signing_key_fatal "target GnuPG home is not a directory"
[ "$(/usr/bin/stat -c "%u:%g:%a" -- "$gnupg_home")" = "${account_uid}:${account_gid}:700" ] ||
  aptly_signing_key_fatal "target GnuPG home is not account-owned mode 0700"

key_listing=$(
  /usr/bin/gpg \
    --batch \
    --no-options \
    --quiet \
    --homedir "$gnupg_home" \
    --fixed-list-mode \
    --with-colons \
    --import-options show-only \
    --import "$staged_key"
)
key_summary=$(printf "%s\n" "$key_listing" | aptly_primary_secret_summary)
expected_summary="1:sec:${expected_fingerprint}"
[ "$key_summary" = "$expected_summary" ] ||
  aptly_signing_key_fatal "source must contain exactly one matching primary OpenPGP secret key"
key_signing_capability_count=$(
  printf "%s\n" "$key_listing" | aptly_signing_capability_count
)
[ "$key_signing_capability_count" -gt 0 ] ||
  aptly_signing_key_fatal "source does not contain signing-capable secret-key material"

/usr/bin/gpg \
  --batch \
  --no-options \
  --quiet \
  --homedir "$gnupg_home" \
  --import "$staged_key" >/dev/null

imported_listing=$(
  /usr/bin/gpg \
    --batch \
    --no-options \
    --quiet \
    --homedir "$gnupg_home" \
    --fixed-list-mode \
    --with-secret \
    --with-colons \
    --list-secret-keys "$expected_fingerprint"
)
imported_summary=$(printf "%s\n" "$imported_listing" | aptly_primary_secret_summary)
[ "$imported_summary" = "$expected_summary" ] ||
  aptly_signing_key_fatal "matching Aptly secret key is unavailable after import"
imported_signing_material_count=$(
  printf "%s\n" "$imported_listing" | aptly_available_signing_material_count
)
[ "$imported_signing_material_count" -gt 0 ] ||
  aptly_signing_key_fatal "matching Aptly key has no local signing-capable secret material after import"
' sh \
    "$staged_target_key" \
    "$ACCOUNT_HOME" \
    "$APTLY_ROOT_DIR" \
    "$DEVOPS_APTLY_REPOSITORY_KEY_FINGERPRINT" \
    "$signing_maximum_bytes"
  # END: managed Aptly signing-key target import

  if ! rm -f -- "$staged_host_key"; then
    devops_fatal "unable to remove the transient Aptly signing-key copy after import"
  fi
  [ ! -e "$staged_host_key" ] && [ ! -L "$staged_host_key" ] ||
    devops_fatal "transient Aptly signing-key copy remains after import"
  staged_host_key=
)

devops_render_osc_config() {
  config_template_repo_path=$(installer_repo_join_var \
    DIR_SCRIPTS_LATE \
    templates/devops/oscrc.tmpl)
  metadata_template_repo_path=$(installer_repo_join_var \
    DIR_SCRIPTS_LATE \
    templates/devops/oscrc-managed.json.tmpl)
  config_template_tmp="${tmp_env_dir}/oscrc.tmpl.$$"
  metadata_template_tmp="${tmp_env_dir}/oscrc-managed.json.tmpl.$$"
  config_rendered_tmp="${tmp_env_dir}/oscrc.rendered.$$"
  metadata_rendered_tmp="${tmp_env_dir}/oscrc-managed.json.rendered.$$"
  target_config="${target_root}${OSC_CONFIG}"
  target_metadata="${target_root}${OSC_MANAGED_CONFIG}"

  bootstrap_fetch_seed_file \
    "$seed_base" \
    "$config_template_repo_path" \
    "$config_template_tmp" \
    0600 \
    "DevOps osc config template ${config_template_repo_path}"
  bootstrap_fetch_seed_file \
    "$seed_base" \
    "$metadata_template_repo_path" \
    "$metadata_template_tmp" \
    0600 \
    "DevOps osc metadata template ${metadata_template_repo_path}"
  installer_apply_scalar_placeholders \
    "$config_template_tmp" \
    "$config_rendered_tmp" \
    ACCOUNT_USERNAME "$ACCOUNT_USERNAME" \
    DEVOPS_OBS_API_URL "$DEVOPS_OBS_API_URL" \
    DEVOPS_OSC_PACKAGE_CACHE_DIR "$OSC_PACKAGE_CACHE_DIR" \
    DEVOPS_OSC_BUILD_ROOT "$OSC_BUILD_ROOT" \
    DEVOPS_OSC_COOKIE_JAR "$OSC_COOKIE_JAR" \
    DEVOPS_OBS_REPOSITORY "$DEVOPS_OBS_REPOSITORY"
  installer_apply_scalar_placeholders \
    "$metadata_template_tmp" \
    "$metadata_rendered_tmp" \
    ACCOUNT_USERNAME "$ACCOUNT_USERNAME" \
    DEVOPS_OBS_API_URL "$DEVOPS_OBS_API_URL" \
    DEVOPS_OSC_WORKDIR "$OSC_WORKDIR" \
    DEVOPS_OBS_PROJECT "$DEVOPS_OBS_PROJECT" \
    DEVOPS_OBS_REPOSITORY "$DEVOPS_OBS_REPOSITORY" \
    DEVOPS_OSC_CREDENTIALS_BACKEND "$DEVOPS_OSC_CREDENTIALS_BACKEND"
  installer_assert_no_unresolved_installer_placeholders \
    "$config_rendered_tmp" \
    "DevOps osc config template ${config_template_repo_path}"
  installer_assert_no_unresolved_installer_placeholders \
    "$metadata_rendered_tmp" \
    "DevOps osc metadata template ${metadata_template_repo_path}"

  [ -d "${target_root}${OSC_STATE_DIR}" ] ||
    devops_fatal "required osc state directory is missing: ${target_root}${OSC_STATE_DIR}"
  install -m 0600 "$config_rendered_tmp" "$target_config"
  install -m 0600 "$metadata_rendered_tmp" "$target_metadata"
  chown "$account_ids" "$target_config" "$target_metadata"
  run_in_target \
    "validate rendered osc config and managed metadata" \
    /usr/bin/python3 -c \
      'import configparser, json, pathlib, sys
config_path, metadata_path = map(pathlib.Path, sys.argv[1:3])
apiurl, cache_dir, build_root, cookiejar, repository, project, workspace, backend = sys.argv[3:]
parser = configparser.ConfigParser(interpolation=None)
parser.read_string(config_path.read_text(encoding="utf-8"))
assert set(parser.sections()) == {"general", apiurl}
assert parser.get("general", "apiurl") == apiurl
assert parser.get("general", "packagecachedir") == cache_dir
assert parser.get("general", "build-root") == f"{build_root}/%(project)s/%(package)s/%(repo)s-%(arch)s"
assert parser.get("general", "cookiejar") == cookiejar
assert parser.get("general", "build_repository") == repository
for option in ("use_keyring", "checkout_rooted", "checkout_no_colon", "check_filelist", "do_package_tracking", "show_download_progress", "buildlog_strip_time", "builtin_signature_check"):
    assert parser.getboolean("general", option)
for option in ("quiet", "verbose", "debug", "http_debug", "http_full_debug", "http_manual_approve", "traceback", "post_mortem", "local_service_run", "status_mtime_heuristic", "no_verify"):
    assert not parser.getboolean("general", option)
assert parser.getint("general", "http_retries") == 3
assert parser.getboolean(apiurl, "sslcertck")
assert not parser.getboolean(apiurl, "allow_http")
assert all(not parser.has_option(section, option) for section in parser.sections() for option in ("user", "pass", "passx", "password"))
metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
assert metadata == {"apiURL": apiurl, "credentialsBackend": backend, "project": project, "repository": repository, "schemaVersion": 1, "workspace": workspace}' \
      "$OSC_CONFIG" \
      "$OSC_MANAGED_CONFIG" \
      "$DEVOPS_OBS_API_URL" \
      "$OSC_PACKAGE_CACHE_DIR" \
      "$OSC_BUILD_ROOT" \
      "$OSC_COOKIE_JAR" \
      "$DEVOPS_OBS_REPOSITORY" \
      "$DEVOPS_OBS_PROJECT" \
      "$OSC_WORKDIR" \
      "$DEVOPS_OSC_CREDENTIALS_BACKEND"
  rm -f -- \
    "$config_template_tmp" \
    "$metadata_template_tmp" \
    "$config_rendered_tmp" \
    "$metadata_rendered_tmp"
}

devops_stage_publishing_command_link() (
  publishing_label=$1
  publishing_link=$2
  publishing_target=$3
  publishing_display_path=${publishing_link#"$target_root"}

  # A resumed late stage can revisit links created before a later failure.
  # Only the exact managed target is idempotent; never replace a collision.
  if [ -L "$publishing_link" ]; then
    [ "$(readlink "$publishing_link")" = "$publishing_target" ] ||
      devops_fatal "managed ${publishing_label} publication entrypoint has an unexpected target: ${publishing_display_path}"
  elif [ -e "$publishing_link" ]; then
    devops_fatal "managed ${publishing_label} publication entrypoint already exists: ${publishing_display_path}"
  else
    ln -s "$publishing_target" "$publishing_link"
  fi
  chown -h root:root "$publishing_link"
)

devops_stage_publishing_entrypoints() {
  aptly_publishing_program=/usr/local/libexec/aptly-publishing
  aptly_publishing_bin_dir=/usr/local/libexec/aptly-publishing-bin
  obs_publishing_program=/usr/local/libexec/obs-publishing
  obs_publishing_bin_dir=/usr/local/libexec/obs-publishing-bin
  install -d -m 0755 \
    "${target_root}/usr/local/libexec" \
    "${target_root}${aptly_publishing_bin_dir}" \
    "${target_root}${obs_publishing_bin_dir}"
  chown root:root \
    "${target_root}/usr/local/libexec" \
    "${target_root}${aptly_publishing_bin_dir}" \
    "${target_root}${obs_publishing_bin_dir}"
  devops_stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/libexec/aptly-publishing)" \
    "$aptly_publishing_program" \
    0755 \
    aptly-publishing
  devops_stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/libexec/obs-publishing)" \
    "$obs_publishing_program" \
    0755 \
    obs-publishing
  chown root:root \
    "${target_root}${aptly_publishing_program}" \
    "${target_root}${obs_publishing_program}"

  for aptly_publishing_command in \
    aptly \
    aptly-publish-local \
    dpkg-buildpackage
  do
    publishing_link="${target_root}${aptly_publishing_bin_dir}/${aptly_publishing_command}"
    devops_stage_publishing_command_link \
      Aptly \
      "$publishing_link" \
      ../aptly-publishing
  done
  for obs_publishing_command in \
    obs-checkout-source \
    obs-publish-source \
    osc
  do
    publishing_link="${target_root}${obs_publishing_bin_dir}/${obs_publishing_command}"
    devops_stage_publishing_command_link \
      OBS \
      "$publishing_link" \
      ../obs-publishing
  done
  unset \
    aptly_publishing_command \
    aptly_publishing_program \
    aptly_publishing_bin_dir \
    obs_publishing_command \
    obs_publishing_program \
    obs_publishing_bin_dir \
    publishing_link
}

devops_install_pending_credential() {
  credential_value=$1
  credential_target=$2
  credential_label=$3
  credential_tmp="${tmp_env_dir}/${credential_label}.pending.$$"

  umask 077
  if ! printf '%s' "$credential_value" >"$credential_tmp"; then
    rm -f -- "$credential_tmp"
    devops_fatal "failed to stage pending ${credential_label} credential"
  fi
  if ! install -m 0600 "$credential_tmp" "${target_root}${credential_target}"; then
    rm -f -- "$credential_tmp" "${target_root}${credential_target}"
    devops_fatal "failed to install pending ${credential_label} credential"
  fi
  if ! chown "$account_ids" "${target_root}${credential_target}"; then
    rm -f -- "$credential_tmp" "${target_root}${credential_target}"
    devops_fatal "failed to assign pending ${credential_label} credential"
  fi
  rm -f -- "$credential_tmp"
}

devops_stage_pending_credentials() {
  devops_install_pending_credential \
    "$DEVOPS_CF_R2_ACCESS_KEY" \
    "${APTLY_ROOT_DIR}/.credentials.pending/cf-r2-access-key" \
    cf-r2-access-key
  devops_install_pending_credential \
    "$DEVOPS_CF_R2_SECRET_KEY" \
    "${APTLY_ROOT_DIR}/.credentials.pending/cf-r2-secret-key" \
    cf-r2-secret-key
  devops_install_pending_credential \
    "$DEVOPS_OBS_USERNAME" \
    "${OSC_STATE_DIR}/.credentials.pending/obs-username" \
    obs-username
  devops_install_pending_credential \
    "$DEVOPS_OBS_PASSWORD" \
    "${OSC_STATE_DIR}/.credentials.pending/obs-password" \
    obs-password
}

devops_initialize_aptly_repositories() {
  # shellcheck disable=SC2016
  devops_run_as_account "initialize stable and testing Aptly repositories" /bin/sh -eu -c '
aptly_config=$1
distributions=$2
component=$3
aptly_binary=$4

[ -r "$aptly_config" ] || {
  printf "fatal: managed Aptly config is missing: %s\n" "$aptly_config" >&2
  exit 1
}
[ -x "$aptly_binary" ] || {
  printf "fatal: managed Aptly binary is missing: %s\n" "$aptly_binary" >&2
  exit 1
}
for distribution in $distributions; do
  repository="local-${distribution}"
  if "$aptly_binary" -config="$aptly_config" repo show "$repository" >/dev/null 2>&1; then
    continue
  fi
  "$aptly_binary" \
    -config="$aptly_config" \
    repo create \
    -distribution="$distribution" \
    -component="$component" \
    "$repository"
done
' sh \
    "$APTLY_CONFIG" \
    "$DEVOPS_APTLY_DISTRIBUTIONS" \
    "$DEVOPS_APTLY_COMPONENT" \
    "$DEVOPS_APTLY_BINARY_PATH"
}

devops_install_llama_runtime() {
  llama_repo_path=$(installer_repo_join_var DIR_SCRIPTS_LATE llama.sh)
  llama_installer="${tmp_env_dir}/installer-llama-entry.$$"

  bootstrap_fetch_seed_file \
    "$seed_base" \
    "$llama_repo_path" \
    "$llama_installer" \
    0600 \
    "DevOps llama.cpp installer helper ${llama_repo_path}"
  chmod 0700 "$llama_installer"

  if ! INSTALLER_RUNTIME_DIR="$runtime_dir" \
       INSTALLER_BOOTSTRAP_LIB="$bootstrap_lib" \
       INSTALLER_LATE_HOST_ENV="$host_env" \
       INSTALLER_LLAMA_TMP_ENV_DIR="${tmp_env_dir}/llama" \
       /bin/sh "$llama_installer" "$target_root"
  then
    rm -f -- "$llama_installer"
    devops_fatal "llama.cpp provisioning failed"
  fi
  rm -f -- "$llama_installer"
}

devops_render_cargo_config() {
  template_repo_path=$(installer_repo_join_var \
    DIR_HOOKS_TARGET \
    etc/skel/.config/cargo/config.toml.tmpl)
  template_tmp="${tmp_env_dir}/cargo-config.toml.tmpl.$$"
  rendered_tmp="${tmp_env_dir}/cargo-config.toml.rendered.$$"
  target_cargo_dir="${target_root}${CARGO_HOME}"
  target_cargo_config="${target_cargo_dir}/config.toml"

  bootstrap_fetch_seed_file \
    "$seed_base" \
    "$template_repo_path" \
    "$template_tmp" \
    0600 \
    "DevOps Cargo config template ${template_repo_path}"
  installer_apply_scalar_placeholders \
    "$template_tmp" \
    "$rendered_tmp" \
    DEVOPS_CARGO_RUSTC_WRAPPER "$DEVOPS_CARGO_RUSTC_WRAPPER" \
    DEVOPS_CARGO_TARGET_TRIPLE "$DEVOPS_CARGO_TARGET_TRIPLE" \
    DEVOPS_CARGO_TARGET_LINKER "$DEVOPS_CARGO_TARGET_LINKER" \
    DEVOPS_CARGO_TARGET_CPU "$DEVOPS_CARGO_TARGET_CPU" \
    DEVOPS_CARGO_LINKER_ARGUMENT "$DEVOPS_CARGO_LINKER_ARGUMENT"
  installer_assert_no_unresolved_installer_placeholders \
    "$rendered_tmp" \
    "DevOps Cargo config template ${template_repo_path}"

  [ -d "$target_cargo_dir" ] ||
    devops_fatal "required Cargo home directory is missing: ${target_cargo_dir}"
  install -m 0644 "$rendered_tmp" "$target_cargo_config"
  chown "$account_ids" "$target_cargo_config"
  rm -f -- "$template_tmp" "$rendered_tmp"
}

devops_render_codex_sysctl() {
  template_repo_path=$(installer_repo_join_var \
    DIR_HOOKS_TARGET \
    etc/sysctl.d/90-codex-bwrap.conf.tmpl)
  template_tmp="${tmp_env_dir}/codex-bwrap-sysctl.tmpl.$$"
  rendered_tmp="${tmp_env_dir}/codex-bwrap-sysctl.rendered.$$"
  target_sysctl_dir="${target_root}/etc/sysctl.d"
  target_sysctl="${target_sysctl_dir}/90-codex-bwrap.conf"

  bootstrap_fetch_seed_file \
    "$seed_base" \
    "$template_repo_path" \
    "$template_tmp" \
    0600 \
    "DevOps Codex Bubblewrap sysctl template ${template_repo_path}"
  installer_apply_scalar_placeholders \
    "$template_tmp" \
    "$rendered_tmp" \
    DEVOPS_CODEX_BWRAP_USERNS_CLONE "$DEVOPS_CODEX_BWRAP_USERNS_CLONE" \
    DEVOPS_CODEX_BWRAP_MAX_USER_NAMESPACES "$DEVOPS_CODEX_BWRAP_MAX_USER_NAMESPACES"
  installer_assert_no_unresolved_installer_placeholders \
    "$rendered_tmp" \
    "DevOps Codex Bubblewrap sysctl template ${template_repo_path}"

  install -d -m 0755 "$target_sysctl_dir"
  install -m 0644 "$rendered_tmp" "$target_sysctl"
  chown root:root "$target_sysctl_dir" "$target_sysctl"
  rm -f -- "$template_tmp" "$rendered_tmp"
}

devops_render_codex_tmpfiles() {
  template_repo_path=$(installer_repo_join_var \
    DIR_HOOKS_TARGET \
    etc/tmpfiles.d/80-codex-storage.conf.tmpl)
  template_tmp="${tmp_env_dir}/codex-storage-tmpfiles.tmpl.$$"
  rendered_tmp="${tmp_env_dir}/codex-storage-tmpfiles.rendered.$$"
  target_tmpfiles_dir="${target_root}/etc/tmpfiles.d"
  target_tmpfiles="${target_tmpfiles_dir}/80-codex-storage.conf"

  bootstrap_fetch_seed_file \
    "$seed_base" \
    "$template_repo_path" \
    "$template_tmp" \
    0600 \
    "DevOps Codex tmpfiles template ${template_repo_path}"
  installer_apply_scalar_placeholders \
    "$template_tmp" \
    "$rendered_tmp" \
    ACCOUNT_USERNAME "$ACCOUNT_USERNAME" \
    DEVOPS_CODEX_ROOT "$DEVOPS_CODEX_ROOT" \
    DEVOPS_CODEX_BINARY_PATH "$DEVOPS_CODEX_BINARY_PATH" \
    DEVOPS_CODEX_WRAPPER_PATH "$DEVOPS_CODEX_WRAPPER_PATH" \
    DEVOPS_CODEX_USER_ROOT "$DEVOPS_CODEX_USER_ROOT" \
    DEVOPS_CODEX_SYSTEM_CONFIG_DIR "$DEVOPS_CODEX_SYSTEM_CONFIG_DIR" \
    DEVOPS_CODEX_LOG_DIR "$DEVOPS_CODEX_LOG_DIR" \
    DEVOPS_CODEX_SQLITE_HOME "$DEVOPS_CODEX_SQLITE_HOME" \
    DEVOPS_CODEX_RUNTIME_ROOT "$DEVOPS_CODEX_RUNTIME_ROOT" \
    DEVOPS_CODEX_AGENTS "$DEVOPS_CODEX_AGENTS" \
    DEVOPS_CODEX_HOME "$DEVOPS_CODEX_HOME" \
    DEVOPS_CODEX_SKILLS "$DEVOPS_CODEX_SKILLS"
  installer_assert_no_unresolved_installer_placeholders \
    "$rendered_tmp" \
    "DevOps Codex tmpfiles template ${template_repo_path}"

  install -d -m 0755 "$target_tmpfiles_dir"
  install -m 0644 "$rendered_tmp" "$target_tmpfiles"
  chown root:root "$target_tmpfiles_dir" "$target_tmpfiles"
  rm -f -- "$template_tmp" "$rendered_tmp"
}

devops_render_codex_logrotate() {
  template_repo_path=$(installer_repo_join_var \
    DIR_HOOKS_TARGET \
    etc/logrotate.d/managed-codex.tmpl)
  template_tmp="${tmp_env_dir}/managed-codex-logrotate.tmpl.$$"
  rendered_tmp="${tmp_env_dir}/managed-codex-logrotate.rendered.$$"
  target_logrotate_dir="${target_root}/etc/logrotate.d"
  target_logrotate="${target_logrotate_dir}/managed-codex"

  bootstrap_fetch_seed_file \
    "$seed_base" \
    "$template_repo_path" \
    "$template_tmp" \
    0600 \
    "DevOps Codex logrotate template ${template_repo_path}"
  installer_apply_scalar_placeholders \
    "$template_tmp" \
    "$rendered_tmp" \
    ACCOUNT_USERNAME "$ACCOUNT_USERNAME"
  installer_assert_no_unresolved_installer_placeholders \
    "$rendered_tmp" \
    "DevOps Codex logrotate template ${template_repo_path}"

  install -d -m 0755 "$target_logrotate_dir"
  install -m 0644 "$rendered_tmp" "$target_logrotate"
  chown root:root "$target_logrotate_dir" "$target_logrotate"
  rm -f -- "$template_tmp" "$rendered_tmp"
}

devops_render_bazelrc() {
  template_repo_path=$(installer_repo_join_var \
    DIR_HOOKS_TARGET \
    etc/skel/.config/bazel/bazelrc.tmpl)
  template_tmp="${tmp_env_dir}/bazelrc.tmpl.$$"
  rendered_tmp="${tmp_env_dir}/bazelrc.rendered.$$"
  target_bazel_dir="${target_root}/etc/skel/.config/bazel"
  target_bazelrc="${target_bazel_dir}/bazelrc"

  bootstrap_fetch_seed_file \
    "$seed_base" \
    "$template_repo_path" \
    "$template_tmp" \
    0600 \
    "DevOps Bazel rc template ${template_repo_path}"
  installer_apply_scalar_placeholders \
    "$template_tmp" \
    "$rendered_tmp" \
    DEVOPS_BAZEL_OUTPUT_USER_ROOT "$BAZEL_OUTPUT_USER_ROOT" \
    DEVOPS_BAZEL_SERVER_IDLE_SECONDS "$DEVOPS_BAZEL_SERVER_IDLE_SECONDS" \
    DEVOPS_BAZEL_DISK_CACHE "$BAZEL_DISK_CACHE" \
    DEVOPS_BAZEL_REPOSITORY_CACHE "$BAZEL_REPOSITORY_CACHE" \
    DEVOPS_BAZEL_REPOSITORY_DOWNLOADER_RETRIES "$DEVOPS_BAZEL_REPOSITORY_DOWNLOADER_RETRIES" \
    DEVOPS_BAZEL_DISK_CACHE_SIZE "$DEVOPS_BAZEL_DISK_CACHE_SIZE" \
    DEVOPS_BAZEL_DISK_CACHE_MAX_AGE "$DEVOPS_BAZEL_DISK_CACHE_MAX_AGE" \
    DEVOPS_BAZEL_DISK_CACHE_GC_IDLE_DELAY "$DEVOPS_BAZEL_DISK_CACHE_GC_IDLE_DELAY" \
    DEVOPS_BAZEL_ACTION_CACHE_MAX_AGE "$DEVOPS_BAZEL_ACTION_CACHE_MAX_AGE" \
    DEVOPS_BAZEL_ACTION_CACHE_GC_IDLE_DELAY "$DEVOPS_BAZEL_ACTION_CACHE_GC_IDLE_DELAY" \
    DEVOPS_BAZEL_ACTION_CACHE_GC_THRESHOLD "$DEVOPS_BAZEL_ACTION_CACHE_GC_THRESHOLD" \
    DEVOPS_BAZEL_INSTALL_BASE_GC_MAX_AGE "$DEVOPS_BAZEL_INSTALL_BASE_GC_MAX_AGE"
  installer_assert_no_unresolved_installer_placeholders \
    "$rendered_tmp" \
    "DevOps Bazel rc template ${template_repo_path}"

  install -d -m 0755 "$target_bazel_dir"
  install -m 0644 "$rendered_tmp" "$target_bazelrc"
  chown root:root "$target_bazel_dir" "$target_bazelrc"
  rm -f -- "$template_tmp" "$rendered_tmp"
}

devops_render_packer_template() {
  template_repo_path=$(installer_repo_join_var \
    DIR_HOOKS_TARGET \
    etc/skel/.config/packer/template.pkr.hcl.tmpl)
  template_tmp="${tmp_env_dir}/packer-template.pkr.hcl.tmpl.$$"
  rendered_tmp="${tmp_env_dir}/packer-template.pkr.hcl.rendered.$$"
  target_skel_dir="${target_root}/etc/skel/.config/packer"
  target_skel_template="${target_skel_dir}/template.pkr.hcl"

  bootstrap_fetch_seed_file \
    "$seed_base" \
    "$template_repo_path" \
    "$template_tmp" \
    0600 \
    "DevOps Packer template ${template_repo_path}"
  installer_apply_scalar_placeholders \
    "$template_tmp" \
    "$rendered_tmp" \
    DEVOPS_PACKER_VERSION "$DEVOPS_PACKER_VERSION"
  installer_assert_no_unresolved_installer_placeholders \
    "$rendered_tmp" \
    "DevOps Packer template ${template_repo_path}"

  install -d -m 0755 "$target_skel_dir"
  [ ! -e "$target_skel_template" ] && [ ! -L "$target_skel_template" ] ||
    devops_fatal "fresh-install Packer template path already exists: ${target_skel_template}"
  install -m 0644 "$rendered_tmp" "$target_skel_template"
  chown root:root "$target_skel_dir" "$target_skel_template"
  rm -f -- "$template_tmp" "$rendered_tmp"

  # Stage the account copy from inside the target namespace. This guarantees
  # that the path validated below is the same path later seen by runuser.
  # shellcheck disable=SC2016
  run_in_target "stage managed Packer template for primary account" /bin/sh -eu -c '
packer_fatal() {
  printf "fatal: %s\n" "$*" >&2
  exit 1
}

account_user=$1
account_home=$2
source_template=/etc/skel/.config/packer/template.pkr.hcl
config_dir="${account_home}/.config"
template_dir="${config_dir}/packer"
target_template="${template_dir}/template.pkr.hcl"
mise_config_dir="${config_dir}/mise"

for required_command in awk chmod chown getent id install runuser stat; do
  command -v "$required_command" >/dev/null 2>&1 ||
    packer_fatal "required Packer template staging command is unavailable: $required_command"
done
[ -x /usr/bin/test ] ||
  packer_fatal "required Packer template access test is unavailable: /usr/bin/test"

account_record=$(getent passwd "$account_user") ||
  packer_fatal "primary account is unavailable while staging Packer policy: $account_user"
resolved_home=$(printf "%s\n" "$account_record" | awk -F: "{ print \$6; exit }")
[ "$resolved_home" = "$account_home" ] ||
  packer_fatal "primary account home does not match Packer policy: expected $account_home, found ${resolved_home:-unset}"
account_uid=$(id -u "$account_user")
account_gid=$(id -g "$account_user")
case "$account_uid:$account_gid" in
  0:*|65534:*|*:65534|*[!0123456789:]*)
    packer_fatal "unsafe primary account identity for Packer policy: $account_uid:$account_gid"
    ;;
esac

[ -d "$account_home" ] && [ ! -L "$account_home" ] ||
  packer_fatal "primary account home is unavailable or unsafe: $account_home"
[ -f "$source_template" ] && [ ! -L "$source_template" ] ||
  packer_fatal "managed Packer skeleton template is unavailable or unsafe: $source_template"
for managed_path in \
  "$config_dir" \
  "$template_dir" \
  "$target_template" \
  "$mise_config_dir"
do
  [ ! -L "$managed_path" ] ||
    packer_fatal "managed Packer account path must not be a symlink: $managed_path"
done

install -d -m 0755 "$config_dir"
install -d -m 0700 "$template_dir"
install -d -m 0755 "$mise_config_dir"
[ ! -e "$target_template" ] ||
  packer_fatal "fresh-install Packer account template already exists: $target_template"
install -m 0644 "$source_template" "$target_template"
chown "$account_uid:$account_gid" \
  "$config_dir" \
  "$template_dir" \
  "$target_template" \
  "$mise_config_dir"
chmod 0755 "$config_dir"
chmod 0700 "$template_dir"
chmod 0644 "$target_template"
chmod 0755 "$mise_config_dir"

[ "$(stat -c "%u:%g:%a" -- "$config_dir")" = "$account_uid:$account_gid:755" ] ||
  packer_fatal "Packer account config directory ownership or mode is invalid: $config_dir"
[ "$(stat -c "%u:%g:%a" -- "$template_dir")" = "$account_uid:$account_gid:700" ] ||
  packer_fatal "Packer template directory ownership or mode is invalid: $template_dir"
[ "$(stat -c "%u:%g:%a" -- "$target_template")" = "$account_uid:$account_gid:644" ] ||
  packer_fatal "Packer account template ownership or mode is invalid: $target_template"
[ "$(stat -c "%u:%g:%a" -- "$mise_config_dir")" = "$account_uid:$account_gid:755" ] ||
  packer_fatal "Mise account config directory ownership or mode is invalid: $mise_config_dir"
/usr/sbin/runuser -u "$account_user" -- /usr/bin/test -x "$template_dir" ||
  packer_fatal "primary account cannot traverse the managed Packer template directory"
/usr/sbin/runuser -u "$account_user" -- /usr/bin/test -r "$target_template" ||
  packer_fatal "primary account cannot read the managed Packer template"
/usr/sbin/runuser -u "$account_user" -- /usr/bin/test -x "$mise_config_dir" ||
  packer_fatal "primary account cannot traverse the managed Mise config directory"
' sh "$ACCOUNT_USERNAME" "$ACCOUNT_HOME"
}

devops_write_packer_config() {
  target_packer_config="${target_root}${PACKER_CONFIG_PATH}"
  packer_config_tmp="${tmp_env_dir}/packer-config.json.$$"

  [ -d "$(dirname "$target_packer_config")" ] ||
    devops_fatal "required Packer config directory is missing: $(dirname "$target_packer_config")"
  [ ! -e "$target_packer_config" ] && [ ! -L "$target_packer_config" ] ||
    devops_fatal "fresh-install Packer config path already exists: ${target_packer_config}"
  printf '{}\n' >"$packer_config_tmp"
  install -m 0640 "$packer_config_tmp" "$target_packer_config"
  chown "$account_ids" "$target_packer_config"
  rm -f -- "$packer_config_tmp"
}

devops_initialize_packer_plugins() {
  # shellcheck disable=SC2016
  devops_run_as_account \
    "initialize exact-version Packer plugins from the managed HCL template" \
    /usr/bin/timeout \
      --signal=TERM \
      --kill-after=30s \
      "${DEVOPS_PACKER_INIT_TIMEOUT_SECONDS}s" \
      /bin/sh -eu -c '
template_dir=$1
packer_binary=$2
plugin_root=$3
template_file="${template_dir}/template.pkr.hcl"

[ -d "$template_dir" ] && [ ! -L "$template_dir" ] || {
  printf "fatal: managed Packer template directory is unavailable or unsafe: %s\n" "$template_dir" >&2
  exit 1
}
[ -f "$template_file" ] && [ ! -L "$template_file" ] && [ -r "$template_file" ] || {
  printf "fatal: managed Packer template is unavailable or unsafe: %s\n" "$template_file" >&2
  exit 1
}
[ -x "$packer_binary" ] || {
  printf "fatal: managed Packer executable is unavailable: %s\n" "$packer_binary" >&2
  exit 1
}
[ -d "$plugin_root" ] && [ ! -L "$plugin_root" ] || {
  printf "fatal: managed Packer plugin root is unavailable or unsafe: %s\n" "$plugin_root" >&2
  exit 1
}
cd "$template_dir"
"$packer_binary" init .
installed_plugins=$("$packer_binary" plugins installed)
for plugin in amazon ansible azure docker googlecompute proxmox qemu; do
  printf "%s\n" "$installed_plugins" |
    grep -Fq "github.com/hashicorp/${plugin}" || {
      printf "fatal: required Packer plugin is missing after init: %s\n" "$plugin" >&2
      exit 1
    }
  plugin_dir="${plugin_root}/github.com/hashicorp/${plugin}"
  [ -d "$plugin_dir" ] && [ ! -L "$plugin_dir" ] || {
    printf "fatal: required Packer plugin directory is missing: %s\n" "$plugin_dir" >&2
    exit 1
  }
  find "$plugin_dir" -type f -name "packer-plugin-${plugin}_v*" -perm /0111 -print -quit |
    grep -q . || {
      printf "fatal: required Packer plugin executable is missing: %s\n" "$plugin" >&2
      exit 1
    }
done
' sh \
      "${ACCOUNT_HOME}/.config/packer" \
      "$DEVOPS_PACKER_BINARY_PATH" \
      "$PACKER_PLUGIN_PATH"
}

devops_install_pinned_bazelisk() {
  # The payload runs inside /target during the installer late command. It is
  # deliberately not staged as a persistent target-side installer helper.
  # shellcheck disable=SC2016
  run_in_target "download and install pinned Bazelisk" /bin/sh -eu -c '
umask 022

bazelisk_fatal() {
  printf "fatal: %s\n" "$*" >&2
  exit 1
}

bazelisk_validate_positive_integer() {
  label=$1
  value=$2

  case "$value" in
    ""|*[!0123456789]*) bazelisk_fatal "${label} must be a positive integer" ;;
  esac
  [ "$value" -gt 0 ] || bazelisk_fatal "${label} must be greater than zero"
}

bazelisk_require_command() {
  command -v "$1" >/dev/null 2>&1 ||
    bazelisk_fatal "required command is unavailable: $1"
}

bazelisk_version=$1
bazelisk_url=$2
expected_sha256=$3
minimum_bytes=$4
maximum_bytes=$5
install_dir=$6
binary_path=$7

case "$bazelisk_url" in
  "https://github.com/bazelbuild/bazelisk/releases/download/v${bazelisk_version}/bazelisk-linux-amd64")
    ;;
  *)
    bazelisk_fatal "release URL does not match the requested Bazelisk version"
    ;;
esac
case "$expected_sha256" in
  *[!0123456789abcdef]*|"") bazelisk_fatal "expected SHA-256 is malformed" ;;
esac
[ "${#expected_sha256}" -eq 64 ] ||
  bazelisk_fatal "expected SHA-256 must have 64 hexadecimal characters"
bazelisk_validate_positive_integer "minimum byte limit" "$minimum_bytes"
bazelisk_validate_positive_integer "maximum byte limit" "$maximum_bytes"
[ "$maximum_bytes" -ge "$minimum_bytes" ] ||
  bazelisk_fatal "maximum byte limit is smaller than the minimum"
[ "$install_dir" = /usr/local/lib/bazelisk ] ||
  bazelisk_fatal "Bazelisk install directory is not approved: $install_dir"
[ "$binary_path" = "${install_dir}/bazel" ] ||
  bazelisk_fatal "Bazelisk binary path is not approved: $binary_path"

for required_command in awk chmod chown curl install mktemp rm sha256sum tr wc; do
  bazelisk_require_command "$required_command"
done
unset required_command

install_parent=/usr/local/lib
[ -d "$install_parent" ] || install -d -m 0755 "$install_parent"
[ ! -L "$install_parent" ] ||
  bazelisk_fatal "${install_parent} must not be a symlink"
[ ! -e "$install_dir" ] && [ ! -L "$install_dir" ] ||
  bazelisk_fatal "Bazelisk install path already exists; this fresh-install helper will not replace it: $install_dir"

staging_dir=$(mktemp -d "${install_parent}/.devops-bazelisk.XXXXXXXX") ||
  bazelisk_fatal "unable to allocate Bazelisk staging directory"
cleanup() {
  rm -rf -- "$staging_dir"
}
trap cleanup EXIT HUP INT TERM

payload_path="${staging_dir}/bazelisk-linux-amd64"
curl \
  --fail \
  --silent \
  --show-error \
  --location \
  --proto "=https" \
  --tlsv1.2 \
  --retry 3 \
  --retry-delay 2 \
  --connect-timeout 15 \
  --max-time 300 \
  --max-filesize "$maximum_bytes" \
  --output "$payload_path" \
  "$bazelisk_url" ||
  bazelisk_fatal "failed to download pinned Bazelisk release: $bazelisk_url"

payload_bytes=$(wc -c <"$payload_path" | tr -d "[[:space:]]")
case "$payload_bytes" in
  ""|*[!0123456789]*) bazelisk_fatal "downloaded Bazelisk size is invalid" ;;
esac
[ "$payload_bytes" -ge "$minimum_bytes" ] ||
  bazelisk_fatal "downloaded Bazelisk is smaller than the configured minimum"
[ "$payload_bytes" -le "$maximum_bytes" ] ||
  bazelisk_fatal "downloaded Bazelisk exceeds the configured maximum"

actual_sha256=$(sha256sum "$payload_path" | awk "{print \$1}")
[ "$actual_sha256" = "$expected_sha256" ] ||
  bazelisk_fatal "Bazelisk SHA-256 mismatch for ${bazelisk_url}"

install -d -m 0755 "$install_dir"
install -m 0755 "$payload_path" "$binary_path"
chown root:root "$install_dir" "$binary_path"
{
  printf "version=%s\n" "$bazelisk_version"
  printf "url=%s\n" "$bazelisk_url"
  printf "sha256=%s\n" "$expected_sha256"
  printf "minimum_bytes=%s\n" "$minimum_bytes"
  printf "maximum_bytes=%s\n" "$maximum_bytes"
  printf "architecture=linux-amd64\n"
} >"${install_dir}/.managed-bazelisk-release"
chmod 0644 "${install_dir}/.managed-bazelisk-release"
chown root:root "${install_dir}/.managed-bazelisk-release"

version_output=$("$binary_path" bazeliskVersion 2>/dev/null || true)
case "$version_output" in
  *"$bazelisk_version"*) ;;
  *) bazelisk_fatal "Bazelisk version verification failed for ${binary_path}" ;;
esac

printf "installed Bazelisk %s at %s\n" "$bazelisk_version" "$binary_path"
' sh \
    "$DEVOPS_BAZELISK_VERSION" \
    "$DEVOPS_BAZELISK_URL" \
    "$DEVOPS_BAZELISK_SHA256" \
    "$DEVOPS_BAZELISK_MINIMUM_BYTES" \
    "$DEVOPS_BAZELISK_MAXIMUM_BYTES" \
    "$DEVOPS_BAZELISK_INSTALL_DIR" \
    "$DEVOPS_BAZELISK_BINARY_PATH"
}

devops_install_pinned_node_runtimes() {
  # The payload runs inside /target during the installer late command. It is
  # deliberately not staged as a persistent target-side helper.
  # shellcheck disable=SC2016
  run_in_target "download and install pinned Node runtimes for Mise" /bin/sh -eu -c '
umask 022

node_fatal() {
  printf "fatal: %s\n" "$*" >&2
  exit 1
}

node_require_command() {
  command -v "$1" >/dev/null 2>&1 ||
    node_fatal "required command is unavailable: $1"
}

node_validate_positive_integer() {
  label=$1
  value=$2

  case "$value" in
    ""|*[!0123456789]*) node_fatal "${label} must be a positive integer" ;;
  esac
  [ "$value" -gt 0 ] || node_fatal "${label} must be greater than zero"
}

node_validate_archive() {
  archive=$1
  archive_root=$2
  archive_listing=$3

  tar -tJf "$archive" >"$archive_listing" ||
    node_fatal "unable to list Node archive: $archive"
  while IFS= read -r archive_entry || [ -n "$archive_entry" ]; do
    [ -n "$archive_entry" ] ||
      node_fatal "Node archive contains an empty path: $archive"
    case "$archive_entry" in
      "$archive_root"/*) ;;
      *) node_fatal "Node archive contains an unexpected path: $archive" ;;
    esac
    case "$archive_entry" in
      /*|../*|*/../*|*/..|..)
        node_fatal "Node archive contains an unsafe path: $archive"
        ;;
      esac
  done <"$archive_listing"
  archive_member_count=$(wc -l <"$archive_listing" | tr -d "[[:space:]]")
  node_validate_positive_integer "Node archive member count" "$archive_member_count"
  [ "$archive_member_count" -le "$max_archive_members" ] ||
    node_fatal "Node archive exceeds the configured member ceiling (${archive_member_count} > ${max_archive_members}): $archive"

  archive_expanded_bytes=$(xz --robot --list "$archive" |
    awk -F "\t" "\$1 == \"totals\" { print \$5; exit }")
  node_validate_positive_integer "Node archive expanded bytes" "$archive_expanded_bytes"
  [ "$archive_expanded_bytes" -le "$max_extracted_bytes" ] ||
    node_fatal "Node archive exceeds the configured expanded-byte ceiling: $archive"
}

node_install() {
  major_version=$1
  release_version=$2
  archive_url=$3
  expected_sha256=$4
  expected_bytes=$5
  archive_name=$6
  archive_root=$7
  install_dir=$8
  binary_path=$9

  case "$major_version" in
    22|24|26) ;;
    *) node_fatal "unsupported managed Node major version: $major_version" ;;
  esac
  printf "%s\n" "$release_version" |
    grep -Eq "^v${major_version}\.[0-9]+\.[0-9]+$" ||
    node_fatal "Node release version does not match its managed major: $release_version"
  [ "$archive_name" = "node-${release_version}-linux-x64.tar.xz" ] ||
    node_fatal "Node archive filename does not match its managed release"
  [ "$archive_root" = "node-${release_version}-linux-x64" ] ||
    node_fatal "Node archive root does not match its managed release"
  [ "$archive_url" = "https://nodejs.org/dist/${release_version}/${archive_name}" ] ||
    node_fatal "Node release URL is not the official Linux x64 archive"
  [ "$install_dir" = "/usr/local/lib/node-${major_version}" ] ||
    node_fatal "Node install root is outside the managed release root"
  [ "$binary_path" = "${install_dir}/bin/node" ] ||
    node_fatal "Node binary path does not match its managed install root"
  [ "${#expected_sha256}" -eq 64 ] ||
    node_fatal "Node SHA-256 must contain 64 lowercase hexadecimal characters"
  case "$expected_sha256" in
    *[!0123456789abcdef]*)
      node_fatal "Node SHA-256 must contain 64 lowercase hexadecimal characters"
      ;;
  esac
  node_validate_positive_integer "exact byte count" "$expected_bytes"

  [ ! -e "$install_dir" ] ||
    node_fatal "Node install path already exists; this fresh-install helper will not replace it: $install_dir"

  install -d -m 0755 /usr/local/lib
  [ ! -L /usr/local/lib ] ||
    node_fatal "/usr/local/lib must not be a symlink"

  staging_dir=$(mktemp -d /usr/local/lib/.devops-node.XXXXXXXX) ||
    node_fatal "unable to allocate Node staging directory"
  trap "rm -rf -- \"\$staging_dir\"" EXIT HUP INT TERM

  archive_path="${staging_dir}/${archive_name}"
  archive_listing="${staging_dir}/archive.list"
  curl \
    --fail \
    --silent \
    --show-error \
    --location \
    --proto "=https" \
    --tlsv1.2 \
    --retry 3 \
    --retry-delay 2 \
    --connect-timeout 15 \
    --max-time "$download_timeout" \
    --max-filesize "$expected_bytes" \
    --output "$archive_path" \
    "$archive_url" ||
    node_fatal "failed to download pinned Node archive: $archive_url"

  archive_bytes=$(wc -c <"$archive_path" | tr -d "[[:space:]]")
  case "$archive_bytes" in
    ""|*[!0123456789]*) node_fatal "downloaded Node archive size is invalid: $archive_name" ;;
  esac
  [ "$archive_bytes" = "$expected_bytes" ] ||
    node_fatal "downloaded Node archive size does not match the profile policy: $archive_name"

  actual_sha256=$(sha256sum "$archive_path" | awk "{print \$1}")
  [ "$actual_sha256" = "$expected_sha256" ] ||
    node_fatal "Node archive SHA-256 mismatch for ${archive_name}"

  node_validate_archive "$archive_path" "$archive_root" "$archive_listing"
  tar -xJf "$archive_path" \
    --no-same-owner \
    --no-same-permissions \
    -C "$staging_dir" ||
    node_fatal "failed to extract Node archive: $archive_name"

  extracted_dir="${staging_dir}/${archive_root}"
  [ -d "$extracted_dir" ] ||
    node_fatal "Node archive root is missing after extraction: $archive_root"
  [ -x "${extracted_dir}/bin/node" ] ||
    node_fatal "Node executable is missing after extraction: $archive_root"
  [ -x "${extracted_dir}/bin/npm" ] ||
    node_fatal "npm executable is missing after extraction: $archive_root"
  [ -x "${extracted_dir}/bin/npx" ] ||
    node_fatal "npx executable is missing after extraction: $archive_root"

  chown -R root:root "$extracted_dir"
  find "$extracted_dir" -xdev -type d -exec chmod 0755 {} +
  find "$extracted_dir" -xdev -type f -exec chmod a-s,go-w {} +
  printf "%s\n" \
    "version=${release_version}" \
    "url=${archive_url}" \
    "sha256=${expected_sha256}" \
    "bytes=${expected_bytes}" \
    "architecture=linux-x64" \
    >"${extracted_dir}/.managed-node-release"
  chmod 0644 "${extracted_dir}/.managed-node-release"

  mv "$extracted_dir" "$install_dir"
  installed_version=$("$binary_path" --version)
  [ "$installed_version" = "$release_version" ] ||
    node_fatal "Node version verification failed for ${install_dir}: ${installed_version:-missing}"

  rm -f -- "$archive_path" "$archive_listing"
  rmdir -- "$staging_dir" 2>/dev/null || true
  trap - EXIT HUP INT TERM
  printf "installed Node %s at %s\n" "$release_version" "$install_dir"
}

node_enable_corepack() {
  node_major_version=$1
  node_root=$2
  compatibility_root=${3:-}
  node_bin_dir="${node_root}/bin"
  corepack_binary="${node_bin_dir}/corepack"

  [ -x "${node_bin_dir}/node" ] ||
    node_fatal "Node runtime is missing before Corepack configuration: ${node_bin_dir}/node"
  if [ ! -x "$corepack_binary" ]; then
    [ "$node_major_version" = 26 ] ||
      node_fatal "bundled Corepack is missing from Node ${node_major_version}"
    [ -n "$compatibility_root" ] ||
      node_fatal "Node 26 requires a managed Corepack compatibility root"
    corepack_binary="${compatibility_root}/bin/corepack"
    [ -x "$corepack_binary" ] ||
      node_fatal "Node 24 bundled Corepack is unavailable for Node 26 compatibility"
    [ ! -e "${node_bin_dir}/corepack" ] &&
      [ ! -L "${node_bin_dir}/corepack" ] ||
      node_fatal "Node 26 Corepack compatibility path already exists"
    relative_compatibility_root=${compatibility_root#/usr/local/lib/}
    ln -s "../../${relative_compatibility_root}/bin/corepack" "${node_bin_dir}/corepack" ||
      node_fatal "failed to install the Node 26 Corepack compatibility link"
  fi

  PATH="${node_bin_dir}:${PATH:-/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin}" \
    "$corepack_binary" enable --install-directory "$node_bin_dir" ||
    node_fatal "failed to enable Corepack package-manager shims for Node ${node_major_version}"
  for corepack_command in pnpm yarn; do
    [ -x "${node_bin_dir}/${corepack_command}" ] ||
      node_fatal "Corepack did not install ${corepack_command} for Node ${node_major_version}"
  done
  unset corepack_command
}

for required_command in awk chown curl find install ln mktemp mv rmdir sha256sum tar tr wc xz; do
  node_require_command "$required_command"
done
unset required_command

download_timeout=${28}
max_archive_members=${29}
max_extracted_bytes=${30}
node_validate_positive_integer "Node download timeout" "$download_timeout"
node_validate_positive_integer "Node archive member ceiling" "$max_archive_members"
node_validate_positive_integer "Node expanded-byte ceiling" "$max_extracted_bytes"

node_install "$1" "$2" "$3" "$4" "$5" "$6" "$7" "$8" "$9"
node_install "${10}" "${11}" "${12}" "${13}" "${14}" "${15}" "${16}" "${17}" "${18}"
node_install "${19}" "${20}" "${21}" "${22}" "${23}" "${24}" "${25}" "${26}" "${27}"
node_enable_corepack "$1" "$8"
node_enable_corepack "${10}" "${17}"
# Corepack stopped shipping with Node 25.  Node 26 receives package-manager
# shims from the verified Node 24 Corepack payload while retaining Node 26 as
# the runtime selected by Mise.
node_enable_corepack "${19}" "${26}" "${17}"
' sh \
    "$DEVOPS_NODE_22_MAJOR" \
    "$DEVOPS_NODE_22_VERSION" \
    "$DEVOPS_NODE_22_URL" \
    "$DEVOPS_NODE_22_SHA256" \
    "$DEVOPS_NODE_22_BYTES" \
    "$DEVOPS_NODE_22_ARCHIVE_FILENAME" \
    "$DEVOPS_NODE_22_ARCHIVE_ROOT" \
    "$DEVOPS_NODE_22_INSTALL_ROOT" \
    "$DEVOPS_NODE_22_BINARY_PATH" \
    "$DEVOPS_NODE_24_MAJOR" \
    "$DEVOPS_NODE_24_VERSION" \
    "$DEVOPS_NODE_24_URL" \
    "$DEVOPS_NODE_24_SHA256" \
    "$DEVOPS_NODE_24_BYTES" \
    "$DEVOPS_NODE_24_ARCHIVE_FILENAME" \
    "$DEVOPS_NODE_24_ARCHIVE_ROOT" \
    "$DEVOPS_NODE_24_INSTALL_ROOT" \
    "$DEVOPS_NODE_24_BINARY_PATH" \
    "$DEVOPS_NODE_26_MAJOR" \
    "$DEVOPS_NODE_26_VERSION" \
    "$DEVOPS_NODE_26_URL" \
    "$DEVOPS_NODE_26_SHA256" \
    "$DEVOPS_NODE_26_BYTES" \
    "$DEVOPS_NODE_26_ARCHIVE_FILENAME" \
    "$DEVOPS_NODE_26_ARCHIVE_ROOT" \
    "$DEVOPS_NODE_26_INSTALL_ROOT" \
    "$DEVOPS_NODE_26_BINARY_PATH" \
    "$DEVOPS_UPSTREAM_DOWNLOAD_TIMEOUT_SECONDS" \
    "$DEVOPS_UPSTREAM_MAX_ARCHIVE_MEMBERS" \
    "$DEVOPS_UPSTREAM_MAX_EXTRACTED_BYTES"
}

devops_install_upstream_tools() {
  helper_repo_path=$(installer_repo_join_var DIR_SCRIPTS_LATE devops-tools.py)
  helper_target_path=/tmp/installer-devops-tools.py
  helper_host_path="${target_root}${helper_target_path}"
  policy_target_path=/tmp/installer-devops-tools-policy.json
  policy_host_path="${target_root}${policy_target_path}"

  [ ! -e "$helper_host_path" ] && [ ! -L "$helper_host_path" ] ||
    devops_fatal "temporary upstream DevOps tool installer path already exists"
  [ ! -e "$policy_host_path" ] && [ ! -L "$policy_host_path" ] ||
    devops_fatal "temporary upstream DevOps tool policy path already exists"

  bootstrap_fetch_seed_file \
    "$seed_base" \
    "$helper_repo_path" \
    "$helper_host_path" \
    0700 \
    "DevOps upstream-tool installer ${helper_repo_path}"
  chown root:root "$helper_host_path"

  if ! run_in_target \
    "render private upstream DevOps tool policy" \
    /usr/bin/python3 -c \
      'import json, os, pathlib, sys
path = pathlib.Path(sys.argv[1])
items = sys.argv[2:]
if len(items) % 2:
    raise SystemExit("policy key/value arguments are unbalanced")
keys = items[0::2]
if len(keys) != len(set(keys)):
    raise SystemExit("policy contains duplicate keys")
payload = dict(zip(keys, items[1::2]))
flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
if hasattr(os, "O_NOFOLLOW"):
    flags |= os.O_NOFOLLOW
descriptor = os.open(path, flags, 0o600)
try:
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
except BaseException:
    path.unlink(missing_ok=True)
    raise' \
      "$policy_target_path" \
      DEVOPS_UPSTREAM_POLICY_SCHEMA "$DEVOPS_UPSTREAM_POLICY_SCHEMA" \
      DEVOPS_UPSTREAM_ARCHITECTURE "$DEVOPS_UPSTREAM_ARCHITECTURE" \
      DEVOPS_UPSTREAM_DOWNLOAD_TIMEOUT_SECONDS "$DEVOPS_UPSTREAM_DOWNLOAD_TIMEOUT_SECONDS" \
      DEVOPS_UPSTREAM_NPM_TIMEOUT_SECONDS "$DEVOPS_UPSTREAM_NPM_TIMEOUT_SECONDS" \
      DEVOPS_UPSTREAM_MAKE_TIMEOUT_SECONDS "$DEVOPS_UPSTREAM_MAKE_TIMEOUT_SECONDS" \
      DEVOPS_UPSTREAM_VERIFY_TIMEOUT_SECONDS "$DEVOPS_UPSTREAM_VERIFY_TIMEOUT_SECONDS" \
      DEVOPS_UPSTREAM_MAX_ARCHIVE_MEMBERS "$DEVOPS_UPSTREAM_MAX_ARCHIVE_MEMBERS" \
      DEVOPS_UPSTREAM_MAX_EXTRACTED_BYTES "$DEVOPS_UPSTREAM_MAX_EXTRACTED_BYTES" \
      DEVOPS_DENO_VERSION "$DEVOPS_DENO_VERSION" \
      DEVOPS_DENO_URL "$DEVOPS_DENO_URL" \
      DEVOPS_DENO_SHA256 "$DEVOPS_DENO_SHA256" \
      DEVOPS_DENO_BYTES "$DEVOPS_DENO_BYTES" \
      DEVOPS_DENO_ARCHITECTURE "$DEVOPS_DENO_ARCHITECTURE" \
      DEVOPS_DENO_ARCHIVE_FILENAME "$DEVOPS_DENO_ARCHIVE_FILENAME" \
      DEVOPS_DENO_ARCHIVE_FILES "$DEVOPS_DENO_ARCHIVE_FILES" \
      DEVOPS_DENO_INSTALL_ROOT "$DEVOPS_DENO_INSTALL_ROOT" \
      DEVOPS_DENO_BINARY_PATH "$DEVOPS_DENO_BINARY_PATH" \
      DEVOPS_YT_DLP_VERSION "$DEVOPS_YT_DLP_VERSION" \
      DEVOPS_YT_DLP_URL "$DEVOPS_YT_DLP_URL" \
      DEVOPS_YT_DLP_SHA256 "$DEVOPS_YT_DLP_SHA256" \
      DEVOPS_YT_DLP_BYTES "$DEVOPS_YT_DLP_BYTES" \
      DEVOPS_YT_DLP_ARCHITECTURE "$DEVOPS_YT_DLP_ARCHITECTURE" \
      DEVOPS_YT_DLP_ARCHIVE_FILENAME "$DEVOPS_YT_DLP_ARCHIVE_FILENAME" \
      DEVOPS_YT_DLP_INSTALL_ROOT "$DEVOPS_YT_DLP_INSTALL_ROOT" \
      DEVOPS_YT_DLP_BINARY_PATH "$DEVOPS_YT_DLP_BINARY_PATH" \
      DEVOPS_YT_DLP_PAYLOAD_PATH "$DEVOPS_YT_DLP_PAYLOAD_PATH" \
      DEVOPS_ANSIBLE_CORE_VERSION "$DEVOPS_ANSIBLE_CORE_VERSION" \
      DEVOPS_ANSIBLE_CORE_URL "$DEVOPS_ANSIBLE_CORE_URL" \
      DEVOPS_ANSIBLE_CORE_SHA256 "$DEVOPS_ANSIBLE_CORE_SHA256" \
      DEVOPS_ANSIBLE_CORE_BYTES "$DEVOPS_ANSIBLE_CORE_BYTES" \
      DEVOPS_ANSIBLE_CORE_ARCHITECTURE "$DEVOPS_ANSIBLE_CORE_ARCHITECTURE" \
      DEVOPS_ANSIBLE_CORE_ARCHIVE_FILENAME "$DEVOPS_ANSIBLE_CORE_ARCHIVE_FILENAME" \
      DEVOPS_ANSIBLE_CORE_PACKAGE_ROOTS "$DEVOPS_ANSIBLE_CORE_PACKAGE_ROOTS" \
      DEVOPS_ANSIBLE_CORE_DIST_INFO_ROOT "$DEVOPS_ANSIBLE_CORE_DIST_INFO_ROOT" \
      DEVOPS_ANSIBLE_CORE_MAX_ARCHIVE_MEMBERS "$DEVOPS_ANSIBLE_CORE_MAX_ARCHIVE_MEMBERS" \
      DEVOPS_ANSIBLE_CORE_MAX_EXTRACTED_BYTES "$DEVOPS_ANSIBLE_CORE_MAX_EXTRACTED_BYTES" \
      DEVOPS_ANSIBLE_CORE_INSTALL_ROOT "$DEVOPS_ANSIBLE_CORE_INSTALL_ROOT" \
      DEVOPS_ANSIBLE_CORE_BINARY_PATH "$DEVOPS_ANSIBLE_CORE_BINARY_PATH" \
      DEVOPS_OPENTOFU_VERSION "$DEVOPS_OPENTOFU_VERSION" \
      DEVOPS_OPENTOFU_URL "$DEVOPS_OPENTOFU_URL" \
      DEVOPS_OPENTOFU_SHA256 "$DEVOPS_OPENTOFU_SHA256" \
      DEVOPS_OPENTOFU_BYTES "$DEVOPS_OPENTOFU_BYTES" \
      DEVOPS_OPENTOFU_ARCHITECTURE "$DEVOPS_OPENTOFU_ARCHITECTURE" \
      DEVOPS_OPENTOFU_ARCHIVE_FILENAME "$DEVOPS_OPENTOFU_ARCHIVE_FILENAME" \
      DEVOPS_OPENTOFU_ARCHIVE_FILES "$DEVOPS_OPENTOFU_ARCHIVE_FILES" \
      DEVOPS_OPENTOFU_INSTALL_ROOT "$DEVOPS_OPENTOFU_INSTALL_ROOT" \
      DEVOPS_OPENTOFU_BINARY_PATH "$DEVOPS_OPENTOFU_BINARY_PATH" \
      DEVOPS_TERRAFORM_VERSION "$DEVOPS_TERRAFORM_VERSION" \
      DEVOPS_TERRAFORM_URL "$DEVOPS_TERRAFORM_URL" \
      DEVOPS_TERRAFORM_SHA256 "$DEVOPS_TERRAFORM_SHA256" \
      DEVOPS_TERRAFORM_BYTES "$DEVOPS_TERRAFORM_BYTES" \
      DEVOPS_TERRAFORM_ARCHITECTURE "$DEVOPS_TERRAFORM_ARCHITECTURE" \
      DEVOPS_TERRAFORM_ARCHIVE_FILENAME "$DEVOPS_TERRAFORM_ARCHIVE_FILENAME" \
      DEVOPS_TERRAFORM_ARCHIVE_FILES "$DEVOPS_TERRAFORM_ARCHIVE_FILES" \
      DEVOPS_TERRAFORM_INSTALL_ROOT "$DEVOPS_TERRAFORM_INSTALL_ROOT" \
      DEVOPS_TERRAFORM_BINARY_PATH "$DEVOPS_TERRAFORM_BINARY_PATH" \
      DEVOPS_PACKER_VERSION "$DEVOPS_PACKER_VERSION" \
      DEVOPS_PACKER_URL "$DEVOPS_PACKER_URL" \
      DEVOPS_PACKER_SHA256 "$DEVOPS_PACKER_SHA256" \
      DEVOPS_PACKER_BYTES "$DEVOPS_PACKER_BYTES" \
      DEVOPS_PACKER_ARCHITECTURE "$DEVOPS_PACKER_ARCHITECTURE" \
      DEVOPS_PACKER_ARCHIVE_FILENAME "$DEVOPS_PACKER_ARCHIVE_FILENAME" \
      DEVOPS_PACKER_ARCHIVE_FILES "$DEVOPS_PACKER_ARCHIVE_FILES" \
      DEVOPS_PACKER_INSTALL_ROOT "$DEVOPS_PACKER_INSTALL_ROOT" \
      DEVOPS_PACKER_BINARY_PATH "$DEVOPS_PACKER_BINARY_PATH" \
      DEVOPS_WRANGLER_VERSION "$DEVOPS_WRANGLER_VERSION" \
      DEVOPS_WRANGLER_URL "$DEVOPS_WRANGLER_URL" \
      DEVOPS_WRANGLER_SHA512 "$DEVOPS_WRANGLER_SHA512" \
      DEVOPS_WRANGLER_NPM_INTEGRITY "$DEVOPS_WRANGLER_NPM_INTEGRITY" \
      DEVOPS_WRANGLER_BYTES "$DEVOPS_WRANGLER_BYTES" \
      DEVOPS_WRANGLER_ARCHITECTURE "$DEVOPS_WRANGLER_ARCHITECTURE" \
      DEVOPS_WRANGLER_ARCHIVE_FILENAME "$DEVOPS_WRANGLER_ARCHIVE_FILENAME" \
      DEVOPS_WRANGLER_ARCHIVE_ROOT "$DEVOPS_WRANGLER_ARCHIVE_ROOT" \
      DEVOPS_WRANGLER_PACKAGE_NAME "$DEVOPS_WRANGLER_PACKAGE_NAME" \
      DEVOPS_WRANGLER_NODE_REQUIREMENT "$DEVOPS_WRANGLER_NODE_REQUIREMENT" \
      DEVOPS_WRANGLER_NODE_ROOT "$DEVOPS_WRANGLER_NODE_ROOT" \
      DEVOPS_WRANGLER_NPM_REGISTRY_URL "$DEVOPS_WRANGLER_NPM_REGISTRY_URL" \
      DEVOPS_WRANGLER_INSTALL_ROOT "$DEVOPS_WRANGLER_INSTALL_ROOT" \
      DEVOPS_WRANGLER_BINARY_PATH "$DEVOPS_WRANGLER_BINARY_PATH" \
      DEVOPS_APTLY_RELEASE_VERSION "$DEVOPS_APTLY_RELEASE_VERSION" \
      DEVOPS_APTLY_RELEASE_URL "$DEVOPS_APTLY_RELEASE_URL" \
      DEVOPS_APTLY_RELEASE_SHA256 "$DEVOPS_APTLY_RELEASE_SHA256" \
      DEVOPS_APTLY_RELEASE_BYTES "$DEVOPS_APTLY_RELEASE_BYTES" \
      DEVOPS_APTLY_RELEASE_ARCHITECTURE "$DEVOPS_APTLY_RELEASE_ARCHITECTURE" \
      DEVOPS_APTLY_RELEASE_ARCHIVE_FILENAME "$DEVOPS_APTLY_RELEASE_ARCHIVE_FILENAME" \
      DEVOPS_APTLY_RELEASE_ARCHIVE_ROOT "$DEVOPS_APTLY_RELEASE_ARCHIVE_ROOT" \
      DEVOPS_APTLY_RELEASE_ARCHIVE_FILES "$DEVOPS_APTLY_RELEASE_ARCHIVE_FILES" \
      DEVOPS_APTLY_INSTALL_ROOT "$DEVOPS_APTLY_INSTALL_ROOT" \
      DEVOPS_APTLY_BINARY_PATH "$DEVOPS_APTLY_BINARY_PATH" \
      DEVOPS_OSC_RELEASE_VERSION "$DEVOPS_OSC_RELEASE_VERSION" \
      DEVOPS_OSC_RELEASE_URL "$DEVOPS_OSC_RELEASE_URL" \
      DEVOPS_OSC_RELEASE_SHA256 "$DEVOPS_OSC_RELEASE_SHA256" \
      DEVOPS_OSC_RELEASE_BYTES "$DEVOPS_OSC_RELEASE_BYTES" \
      DEVOPS_OSC_RELEASE_ARCHITECTURE "$DEVOPS_OSC_RELEASE_ARCHITECTURE" \
      DEVOPS_OSC_RELEASE_ARCHIVE_FILENAME "$DEVOPS_OSC_RELEASE_ARCHIVE_FILENAME" \
      DEVOPS_OSC_RELEASE_PACKAGE_ROOT "$DEVOPS_OSC_RELEASE_PACKAGE_ROOT" \
      DEVOPS_OSC_RELEASE_DIST_INFO_ROOT "$DEVOPS_OSC_RELEASE_DIST_INFO_ROOT" \
      DEVOPS_OSC_INSTALL_ROOT "$DEVOPS_OSC_INSTALL_ROOT" \
      DEVOPS_OSC_BINARY_PATH "$DEVOPS_OSC_BINARY_PATH" \
      DEVOPS_OBS_BUILD_TAG "$DEVOPS_OBS_BUILD_TAG" \
      DEVOPS_OBS_BUILD_COMMIT "$DEVOPS_OBS_BUILD_COMMIT" \
      DEVOPS_OBS_BUILD_URL "$DEVOPS_OBS_BUILD_URL" \
      DEVOPS_OBS_BUILD_SHA256 "$DEVOPS_OBS_BUILD_SHA256" \
      DEVOPS_OBS_BUILD_BYTES "$DEVOPS_OBS_BUILD_BYTES" \
      DEVOPS_OBS_BUILD_ARCHITECTURE "$DEVOPS_OBS_BUILD_ARCHITECTURE" \
      DEVOPS_OBS_BUILD_ARCHIVE_FILENAME "$DEVOPS_OBS_BUILD_ARCHIVE_FILENAME" \
      DEVOPS_OBS_BUILD_ARCHIVE_ROOT "$DEVOPS_OBS_BUILD_ARCHIVE_ROOT" \
      DEVOPS_OBS_BUILD_INSTALL_ROOT "$DEVOPS_OBS_BUILD_INSTALL_ROOT" \
      DEVOPS_OBS_BUILD_BINARY_PATH "$DEVOPS_OBS_BUILD_BINARY_PATH" \
      DEVOPS_OBS_BUILD_ENTRYPOINTS "$DEVOPS_OBS_BUILD_ENTRYPOINTS"
  then
    rm -f -- "$helper_host_path" "$policy_host_path"
    devops_fatal "failed to render upstream DevOps tool policy"
  fi
  chown root:root "$policy_host_path"
  chmod 0600 "$policy_host_path"

  if ! run_in_target \
    "download, validate, and install pinned upstream DevOps tools" \
    /usr/bin/python3 "$helper_target_path" --policy "$policy_target_path"
  then
    rm -f -- "$helper_host_path" "$policy_host_path"
    devops_fatal "upstream DevOps tool provisioning failed"
  fi
  rm -f -- "$helper_host_path" "$policy_host_path"
}

devops_install_pinned_rustup() {
  # Rustup's official archive publishes a checksum-addressed bootstrap
  # executable. Stage that profile-selected executable atomically at the
  # requested global path; account toolchains remain in /pool-backed state.
  # shellcheck disable=SC2016
  run_in_target "download and install pinned Rustup bootstrap" /bin/sh -eu -c '
umask 022

rustup_fatal() {
  printf "fatal: %s\n" "$*" >&2
  exit 1
}

rustup_require_command() {
  command -v "$1" >/dev/null 2>&1 ||
    rustup_fatal "required command is unavailable: $1"
}

rustup_validate_positive_integer() {
  label=$1
  value=$2

  case "$value" in
    ""|*[!0123456789]*) rustup_fatal "${label} must be a positive integer" ;;
  esac
  [ "$value" -gt 0 ] || rustup_fatal "${label} must be greater than zero"
}

rustup_version=$1
rustup_url=$2
expected_sha256=$3
expected_bytes=$4
target_triple=$5
install_dir=$6
rustup_init_path=$7
download_timeout=$8
install_parent=${install_dir%/*}
binary_dir=${rustup_init_path%/*}

printf "%s\n" "$rustup_version" |
  grep -Eq "^[0-9]+\.[0-9]+\.[0-9]+$" ||
  rustup_fatal "Rustup version is not semantic"
[ "$target_triple" = x86_64-unknown-linux-gnu ] ||
  rustup_fatal "Rustup target triple is not the managed Linux AMD64 target"
[ "$rustup_url" = "https://static.rust-lang.org/rustup/archive/${rustup_version}/${target_triple}/rustup-init" ] ||
  rustup_fatal "Rustup source URL is not the versioned official Linux AMD64 bootstrap"
[ "$install_dir" = /usr/local/lib/rustup ] ||
  rustup_fatal "Rustup install root is outside the managed release root"
[ "$rustup_init_path" = "${install_dir}/bin/rustup-init" ] ||
  rustup_fatal "Rustup binary path does not match the managed install root"
[ "${#expected_sha256}" -eq 64 ] ||
  rustup_fatal "Rustup SHA-256 must contain 64 lowercase hexadecimal characters"
case "$expected_sha256" in
  *[!0123456789abcdef]*)
    rustup_fatal "Rustup SHA-256 must contain 64 lowercase hexadecimal characters"
    ;;
esac
rustup_validate_positive_integer "exact byte count" "$expected_bytes"
rustup_validate_positive_integer "download timeout" "$download_timeout"

for required_command in awk chown curl grep install mktemp rm sha256sum tr wc; do
  rustup_require_command "$required_command"
done
unset required_command

[ -d "$install_parent" ] || install -d -m 0755 "$install_parent"
[ ! -L "$install_parent" ] ||
  rustup_fatal "${install_parent} must not be a symlink"
[ ! -e "$install_dir" ] && [ ! -L "$install_dir" ] ||
  rustup_fatal "Rustup install path already exists; this fresh-install helper will not replace it: $install_dir"

staging_dir=$(mktemp -d "${install_parent}/.devops-rustup.XXXXXXXX") ||
  rustup_fatal "unable to allocate Rustup staging directory"
cleanup() {
  rm -rf -- "$staging_dir"
}
trap cleanup EXIT HUP INT TERM

payload_path="${staging_dir}/rustup-init"
curl \
  --fail \
  --silent \
  --show-error \
  --location \
  --proto "=https" \
  --tlsv1.2 \
  --retry 3 \
    --retry-delay 2 \
    --connect-timeout 15 \
    --max-time "$download_timeout" \
    --max-filesize "$expected_bytes" \
  --output "$payload_path" \
  "$rustup_url" ||
    rustup_fatal "failed to download pinned Rustup bootstrap: $rustup_url"

payload_bytes=$(wc -c <"$payload_path" | tr -d "[[:space:]]")
case "$payload_bytes" in
  ""|*[!0123456789]*) rustup_fatal "downloaded Rustup bootstrap size is invalid" ;;
esac
[ "$payload_bytes" = "$expected_bytes" ] ||
  rustup_fatal "downloaded Rustup bootstrap size does not match the profile policy"

actual_sha256=$(sha256sum "$payload_path" | awk "{print \$1}")
[ "$actual_sha256" = "$expected_sha256" ] ||
  rustup_fatal "Rustup bootstrap SHA-256 mismatch"

install -d -m 0755 "$binary_dir"
install -m 0755 "$payload_path" "$rustup_init_path"
chown root:root "$install_dir" "$binary_dir" "$rustup_init_path"
{
  printf "version=%s\n" "$rustup_version"
  printf "source_url=%s\n" "$rustup_url"
  printf "sha256=%s\n" "$expected_sha256"
  printf "bytes=%s\n" "$expected_bytes"
  printf "architecture=%s\n" "$target_triple"
} >"${install_dir}/.managed-rustup-bootstrap"
chmod 0644 "${install_dir}/.managed-rustup-bootstrap"
chown root:root "${install_dir}/.managed-rustup-bootstrap"

version_output=$("$rustup_init_path" --version 2>/dev/null || true)
case "$version_output" in
  *" ${rustup_version} "*|*" ${rustup_version}"*) ;;
  *) rustup_fatal "Rustup version verification failed for ${rustup_init_path}" ;;
esac

printf "installed Rustup %s bootstrap at %s\n" "$rustup_version" "$rustup_init_path"
' sh \
    "$DEVOPS_RUSTUP_VERSION" \
    "$DEVOPS_RUSTUP_URL" \
    "$DEVOPS_RUSTUP_SHA256" \
    "$DEVOPS_RUSTUP_BYTES" \
    "$DEVOPS_RUSTUP_TARGET_TRIPLE" \
    "$DEVOPS_RUSTUP_INSTALL_ROOT" \
    "$DEVOPS_RUSTUP_BINARY_PATH" \
    "$DEVOPS_UPSTREAM_DOWNLOAD_TIMEOUT_SECONDS"
}

devops_install_pinned_rust_cli_binaries() {
  if [ "$DEVOPS_DOTSLASH_SOURCE_BUILD" = 1 ] &&
    [ "$DEVOPS_UV_SOURCE_BUILD" = 1 ]
  then
    return 0
  fi

  helper_repo_path=$(installer_repo_join_var DIR_SCRIPTS_LATE devops-rust-tools.py)
  helper_target_path=/tmp/installer-devops-rust-tools.py
  helper_host_path="${target_root}${helper_target_path}"

  [ ! -e "$helper_host_path" ] && [ ! -L "$helper_host_path" ] ||
    devops_fatal "temporary prebuilt Rust tool installer path already exists"
  bootstrap_fetch_seed_file \
    "$seed_base" \
    "$helper_repo_path" \
    "$helper_host_path" \
    0755 \
    "prebuilt Rust tool installer ${helper_repo_path}"
  chown root:root "$helper_host_path"

  if ! devops_run_as_account \
    "download, validate, and install selected pinned Rust CLI archives" \
    /usr/bin/python3 "$helper_target_path" \
      --install-root "$CARGO_INSTALL_ROOT" \
      --download-timeout-seconds "$DEVOPS_UPSTREAM_DOWNLOAD_TIMEOUT_SECONDS" \
      --max-archive-members "$DEVOPS_UPSTREAM_MAX_ARCHIVE_MEMBERS" \
      --max-extracted-bytes "$DEVOPS_UPSTREAM_MAX_EXTRACTED_BYTES" \
      --dotslash-source-build "$DEVOPS_DOTSLASH_SOURCE_BUILD" \
      --dotslash-version "$DEVOPS_DOTSLASH_VERSION" \
      --dotslash-url "$DEVOPS_DOTSLASH_URL" \
      --dotslash-sha256 "$DEVOPS_DOTSLASH_SHA256" \
      --dotslash-bytes "$DEVOPS_DOTSLASH_BYTES" \
      --dotslash-architecture "$DEVOPS_DOTSLASH_ARCHITECTURE" \
      --dotslash-archive-filename "$DEVOPS_DOTSLASH_ARCHIVE_FILENAME" \
      --dotslash-archive-files "$DEVOPS_DOTSLASH_ARCHIVE_FILES" \
      --uv-source-build "$DEVOPS_UV_SOURCE_BUILD" \
      --uv-version "$DEVOPS_UV_VERSION" \
      --uv-url "$DEVOPS_UV_URL" \
      --uv-sha256 "$DEVOPS_UV_SHA256" \
      --uv-bytes "$DEVOPS_UV_BYTES" \
      --uv-architecture "$DEVOPS_UV_ARCHITECTURE" \
      --uv-archive-filename "$DEVOPS_UV_ARCHIVE_FILENAME" \
      --uv-archive-root "$DEVOPS_UV_ARCHIVE_ROOT" \
      --uv-archive-files "$DEVOPS_UV_ARCHIVE_FILES"
  then
    rm -f -- "$helper_host_path"
    devops_fatal "prebuilt Rust CLI tool provisioning failed"
  fi

  rm -f -- "$helper_host_path"
  [ ! -e "$helper_host_path" ] && [ ! -L "$helper_host_path" ] ||
    devops_fatal "temporary prebuilt Rust tool installer remains after installation"
}

devops_prepare_codex_layout() {
  # shellcheck disable=SC2016
  run_in_target "prepare OpenAI Codex installation layout" /bin/sh -eu -c '
account_user=$1
codex_root=$2
codex_log_dir=$3
codex_sqlite_home=$4
codex_runtime_root=$5

for required_command in chmod getent id install stat; do
  command -v "$required_command" >/dev/null 2>&1 || {
    printf "fatal: required Codex target command is unavailable: %s\n" "$required_command" >&2
    exit 1
  }
done
getent passwd "$account_user" >/dev/null 2>&1 || {
  printf "fatal: required Codex account is missing: %s\n" "$account_user" >&2
  exit 1
}
devops_group_record=$(getent group devops) || {
  printf "fatal: required target group is missing: devops\n" >&2
  exit 1
}
account_uid=$(id -u "$account_user")
devops_gid=${devops_group_record#*:}
devops_gid=${devops_gid#*:}
devops_gid=${devops_gid%%:*}
case "$account_uid:$devops_gid" in
  *[!0123456789:]*|:*|*:)
    printf "fatal: unable to resolve Codex account or devops group ids\n" >&2
    exit 1
    ;;
esac

codex_prepare_directory() {
  directory_label=$1
  directory_path=$2
  expected_uid=$3
  expected_gid=$4
  expected_mode=$5
  expected_metadata="${expected_uid}:${expected_gid}:${expected_mode}"

  if [ -L "$directory_path" ]; then
    printf "fatal: Codex %s must not be a symlink: %s\n" \
      "$directory_label" "$directory_path" >&2
    exit 1
  fi
  if [ -e "$directory_path" ]; then
    [ -d "$directory_path" ] || {
      printf "fatal: Codex %s is not a directory: %s\n" \
        "$directory_label" "$directory_path" >&2
      exit 1
    }
    actual_metadata=$(stat -c "%u:%g:%a" -- "$directory_path")
    [ "$actual_metadata" = "$expected_metadata" ] || {
      printf "fatal: existing Codex %s has unexpected ownership or mode: expected %s, found %s\n" \
        "$directory_label" "$expected_metadata" "$actual_metadata" >&2
      exit 1
    }
    return 0
  fi

  install -d -m "$expected_mode" -o "$expected_uid" -g "$expected_gid" \
    "$directory_path"
  chmod a-s -- "$directory_path"
  chmod "$expected_mode" -- "$directory_path"
  actual_metadata=$(stat -c "%u:%g:%a" -- "$directory_path")
  [ "$actual_metadata" = "$expected_metadata" ] || {
    printf "fatal: prepared Codex %s has unexpected ownership or mode: expected %s, found %s\n" \
      "$directory_label" "$expected_metadata" "$actual_metadata" >&2
    exit 1
  }
}

[ -d /data ] || install -d -m 0755 -o root -g root /data
[ ! -L /data ] || {
  printf "fatal: /data must not be a symlink\n" >&2
  exit 1
}

# A resumed late stage may revisit this installer-owned skeleton. Reuse only
# directories whose type, owner, group, and mode exactly match the contract.
codex_prepare_directory root "$codex_root" 0 "$devops_gid" 3770
codex_prepare_directory share "$codex_root/share" 0 0 755
codex_prepare_directory binary "$codex_root/share/bin" 0 0 755
codex_prepare_directory library "$codex_root/lib" 0 0 755
codex_prepare_directory log "$codex_log_dir" "$account_uid" "$devops_gid" 2770
codex_prepare_directory SQLite "$codex_sqlite_home" "$account_uid" "$devops_gid" 2770
codex_prepare_directory runtime "$codex_runtime_root" "$account_uid" "$devops_gid" 2770
' sh \
    "$ACCOUNT_USERNAME" \
    "$DEVOPS_CODEX_ROOT" \
    "$DEVOPS_CODEX_LOG_DIR" \
    "$DEVOPS_CODEX_SQLITE_HOME" \
    "$DEVOPS_CODEX_RUNTIME_ROOT"
}

devops_apply_codex_tmpfiles() {
  codex_tmpfiles_policy=/etc/tmpfiles.d/80-codex-storage.conf

  [ -r "${target_root}${codex_tmpfiles_policy}" ] ||
    devops_fatal "Codex tmpfiles policy is missing before application: ${codex_tmpfiles_policy}"
  run_in_target \
    "apply managed Codex directory policy" \
    /usr/bin/systemd-tmpfiles \
      --create \
      "$codex_tmpfiles_policy"

  # Verify the sticky shared root, account-owned state, directly installed
  # root-owned executable assets, and writable account-owned memories marker.
  # shellcheck disable=SC2016
  run_in_target "verify persistent Codex ownership policy" /bin/sh -eu -c '
codex_fatal() {
  printf "fatal: %s\n" "$*" >&2
  exit 1
}

codex_verify_stat() {
  expected=$1
  path=$2
  actual=$(stat -c "%u:%g:%a" -- "$path")
  [ "$actual" = "$expected" ] ||
    codex_fatal "unexpected ownership or mode for ${path}: expected ${expected}, found ${actual}"
}

account_user=$1
codex_root=$2
schema_path=$3
wrapper_path=$4
user_root=$5
system_config_dir=$6
log_dir=$7
sqlite_home=$8
runtime_root=$9
shift 9
home_path=$1
host_log_dir=$2

for required_command in awk find getent id readlink runuser stat; do
  command -v "$required_command" >/dev/null 2>&1 ||
    codex_fatal "required Codex policy verification command is unavailable: $required_command"
done

account_uid=$(id -u "$account_user")
devops_gid=$(getent group devops | awk -F: "{ print \$3; exit }")
case "$account_uid:$devops_gid" in
  *[!0123456789:]*|:*|*:) codex_fatal "unable to resolve Codex account or devops group ids" ;;
esac

codex_verify_stat "0:${devops_gid}:3770" "$codex_root"
codex_verify_stat "0:0:755" "$codex_root/share"
codex_verify_stat "0:0:755" "$codex_root/share/bin"
first_binary=$(find "$codex_root/share/bin" \
  -mindepth 1 -maxdepth 1 -type f -links 1 -print)
[ -n "$first_binary" ] ||
  codex_fatal "Codex binary directory does not contain a direct regular file"
hidden_binary=$(find "$codex_root/share/bin" \
  -mindepth 1 -maxdepth 1 -name ".*" -print)
[ -z "$hidden_binary" ] ||
  codex_fatal "Codex binary directory contains an unexpected hidden entry: $hidden_binary"
unsafe_binary_entry=$(find "$codex_root/share/bin" \
  -mindepth 1 -maxdepth 1 \( ! -type f -o -type l -o ! -links 1 \) -print)
[ -z "$unsafe_binary_entry" ] ||
  codex_fatal "Codex binary directory contains an unsafe entry: $unsafe_binary_entry"
for binary_path in "$codex_root/share/bin"/*; do
  [ -f "$binary_path" ] && [ ! -L "$binary_path" ] ||
    codex_fatal "Codex binary is not a direct regular file: $binary_path"
  binary_name=${binary_path##*/}
  case "$binary_name" in
    ""|*[!A-Za-z0-9._+-]*)
      codex_fatal "installed Codex binary name is malformed: $binary_name"
      ;;
  esac
  codex_verify_stat "0:0:755" "$binary_path"
  /usr/sbin/runuser -u "$account_user" -- /usr/bin/test -x "$binary_path" ||
    codex_fatal "managed desktop account cannot execute Codex binary: $binary_path"
done
unset binary_name binary_path first_binary hidden_binary unsafe_binary_entry
[ -f "$schema_path" ] && [ ! -L "$schema_path" ] ||
  codex_fatal "Codex configuration schema is not a direct regular file"
codex_verify_stat "0:0:644" "$schema_path"
codex_verify_stat "0:0:644" "$codex_root/.managed-codex-release"
codex_verify_stat "0:0:755" "$codex_root/lib"
codex_verify_stat "0:0:755" "$wrapper_path"
codex_verify_stat "${account_uid}:${devops_gid}:750" "$user_root"
repository_git_path="$user_root/.git"
codex_verify_stat "${account_uid}:${devops_gid}:750" "$repository_git_path"
unsafe_repository_git_entry=$(find "$repository_git_path" -xdev \
  \( -type l -o \( ! -type d ! -type f \) -o \( -type f ! -links 1 \) \) \
  -print -quit)
[ -z "$unsafe_repository_git_entry" ] ||
  codex_fatal "Codex repository metadata contains an unsafe installed entry: $unsafe_repository_git_entry"
unset unsafe_repository_git_entry
misowned_repository_git_entry=$(find "$repository_git_path" -xdev \
  \( ! -uid "$account_uid" -o ! -gid "$devops_gid" \) -print -quit)
[ -z "$misowned_repository_git_entry" ] ||
  codex_fatal "Codex repository metadata is not fully account-owned: $misowned_repository_git_entry"
unset misowned_repository_git_entry
misconfigured_repository_git_entry=$(find "$repository_git_path" -xdev \
  \( \( -type d ! -perm 0750 \) -o \( -type f ! -perm 0640 \) \) \
  -print -quit)
[ -z "$misconfigured_repository_git_entry" ] ||
  codex_fatal "Codex repository metadata has an unexpected installed mode: $misconfigured_repository_git_entry"
unset misconfigured_repository_git_entry
codex_verify_stat "0:0:755" "$user_root/etc"
codex_verify_stat "${account_uid}:${devops_gid}:2770" "$home_path"
codex_verify_stat "${account_uid}:${devops_gid}:2770" "$home_path/memories"
codex_verify_stat "${account_uid}:${devops_gid}:660" "$home_path/memories/.git"
for shared_home_path in sessions shell_snapshots archived_sessions; do
  codex_verify_stat \
    "${account_uid}:${devops_gid}:2770" \
    "$home_path/$shared_home_path"
done
unset shared_home_path
for shared_state_file in history.jsonl session_index.jsonl external_agent_session_imports.json; do
  codex_verify_stat \
    "${account_uid}:${devops_gid}:660" \
    "$home_path/$shared_state_file"
done
unset shared_state_file
codex_verify_stat "${account_uid}:${devops_gid}:2770" "$log_dir"
codex_verify_stat "${account_uid}:${devops_gid}:2770" "$host_log_dir"
codex_verify_stat "${account_uid}:${devops_gid}:2770" "$sqlite_home"
codex_verify_stat "${account_uid}:${devops_gid}:2770" "$runtime_root"
codex_verify_stat "${account_uid}:${devops_gid}:700" "$runtime_root/.control"
codex_verify_stat "${account_uid}:${devops_gid}:700" "$codex_root/packages"
codex_verify_stat "${account_uid}:${devops_gid}:700" "$codex_root/sockets"
codex_verify_stat "${account_uid}:${devops_gid}:700" "$codex_root/credentials"
codex_verify_stat "${account_uid}:${devops_gid}:600" "$codex_root/credentials/mcp.env"
# Codex authentication state is absent before login and private when present.
if [ -e "$home_path/auth.json" ] || [ -L "$home_path/auth.json" ]; then
  [ -f "$home_path/auth.json" ] && [ ! -L "$home_path/auth.json" ] ||
    codex_fatal "CODEX_HOME auth state is not a direct regular file"
  [ "$(stat -c "%h" -- "$home_path/auth.json")" = 1 ] ||
    codex_fatal "CODEX_HOME auth state must not be hard linked"
  codex_verify_stat "${account_uid}:${devops_gid}:600" "$home_path/auth.json"
fi
codex_verify_stat "${account_uid}:${devops_gid}:700" "$home_path/app-server-control"
codex_verify_stat \
  "${account_uid}:${devops_gid}:600" \
  "$home_path/app-server-control/app-server-startup.lock"
[ -L "$home_path/packages" ] &&
  [ "$(readlink -- "$home_path/packages")" = "$codex_root/packages" ] ||
  codex_fatal "CODEX_HOME package link does not target the managed package root"
[ -L "$home_path/app-server-control/app-server-control.sock" ] &&
  [ "$(readlink -- "$home_path/app-server-control/app-server-control.sock")" = "$codex_root/sockets/app-server-control.sock" ] ||
  codex_fatal "default app-server socket link does not target the managed listener"
codex_verify_stat "0:0:755" "$system_config_dir"

non_root_repository_etc_entry=$(find "$user_root/etc" -xdev \
  \( ! -uid 0 -o ! -gid 0 \) -print)
[ -z "$non_root_repository_etc_entry" ] ||
  codex_fatal "Codex repository etc subtree is not fully root-owned: $non_root_repository_etc_entry"

for writable_path in \
  "$codex_root" \
  "$user_root" \
  "$repository_git_path" \
  "$home_path" \
  "$home_path/memories" \
  "$home_path/memories/.git" \
  "$log_dir" \
  "$host_log_dir" \
  "$sqlite_home" \
  "$runtime_root" \
  "$codex_root/packages" \
  "$codex_root/sockets" \
  "$codex_root/credentials" \
  "$home_path/app-server-control" \
  "$home_path/app-server-control/app-server-startup.lock"
do
  /usr/sbin/runuser -u "$account_user" -- /usr/bin/test -w "$writable_path" ||
    codex_fatal "managed desktop account cannot write required Codex path: $writable_path"
done
unset writable_path

/usr/sbin/runuser -u "$account_user" -- /usr/bin/test -x "$wrapper_path" ||
  codex_fatal "managed desktop account cannot execute the Codex wrapper"
/usr/sbin/runuser -u "$account_user" -- /usr/bin/test -r "$schema_path" ||
  codex_fatal "managed desktop account cannot read the Codex configuration schema"
if /usr/sbin/runuser -u "$account_user" -- /usr/bin/test -w "$schema_path"; then
  codex_fatal "managed desktop account can unexpectedly write the Codex configuration schema"
fi
if /usr/sbin/runuser -u "$account_user" -- \
  /usr/bin/test -w "$codex_root/.managed-codex-release"
then
  codex_fatal "managed desktop account can unexpectedly write Codex release metadata"
fi
' sh \
    "$ACCOUNT_USERNAME" \
    "$DEVOPS_CODEX_ROOT" \
    "$DEVOPS_CODEX_SCHEMA_PATH" \
    "$DEVOPS_CODEX_WRAPPER_PATH" \
    "$DEVOPS_CODEX_USER_ROOT" \
    "$DEVOPS_CODEX_SYSTEM_CONFIG_DIR" \
    "$DEVOPS_CODEX_LOG_DIR" \
    "$DEVOPS_CODEX_SQLITE_HOME" \
    "$DEVOPS_CODEX_RUNTIME_ROOT" \
    "$DEVOPS_CODEX_HOME" \
    "$devops_codex_host_log_dir"
}

devops_stage_codex_app_server() {
  environment_source_repo=$(installer_repo_join_var \
    DIR_HOOKS_TARGET \
    etc/default/codex-app-server)
  service_source_repo=$(installer_repo_join_var \
    DIR_HOOKS_TARGET \
    etc/skel/.config/systemd/user/codex-app-server.service)
  environment_tmp="${tmp_env_dir}/codex-app-server.env.$$"
  service_tmp="${tmp_env_dir}/codex-app-server.service.$$"
  environment_target="${target_root}/etc/default/codex-app-server"
  template_config_dir="${target_root}/etc/skel/.config"
  template_systemd_dir="${template_config_dir}/systemd"
  template_unit_dir="${template_systemd_dir}/user"
  template_wants_dir="${template_unit_dir}/default.target.wants"
  template_service="${template_unit_dir}/codex-app-server.service"
  template_link="${template_wants_dir}/codex-app-server.service"
  user_config_dir="${target_root}${ACCOUNT_HOME}/.config"
  user_systemd_dir="${user_config_dir}/systemd"
  user_unit_dir="${user_systemd_dir}/user"
  wants_dir="${user_unit_dir}/default.target.wants"
  service_target="${user_unit_dir}/codex-app-server.service"
  service_link="${wants_dir}/codex-app-server.service"

  bootstrap_fetch_seed_file \
    "$seed_base" \
    "$environment_source_repo" \
    "$environment_tmp" \
    0600 \
    "Codex app-server non-secret environment policy ${environment_source_repo}"
  installer_assert_no_unresolved_installer_placeholders \
    "$environment_tmp" \
    "Codex app-server non-secret environment policy ${environment_source_repo}"
  bootstrap_fetch_seed_file \
    "$seed_base" \
    "$service_source_repo" \
    "$service_tmp" \
    0600 \
    "Codex app-server user unit ${service_source_repo}"

  if grep -Eq '^[[:space:]]*(OPENAI_API_KEY|CODEX_MCP_API_KEY)=' "$environment_tmp"; then
    devops_fatal "Codex app-server non-secret environment policy contains a secret assignment"
  fi
  grep -Fqx 'CODEX_APP_SERVER_SECRET_ENV_NAMES=CODEX_MCP_API_KEY' "$environment_tmp" ||
    devops_fatal "Codex app-server environment policy does not contain the approved secret-name allowlist"
  grep -Fqx \
    'ExecStart=/data/codex/lib/codex app-server --listen unix:///data/codex/sockets/app-server-control.sock' \
    "$service_tmp" ||
    devops_fatal "Codex app-server unit does not use the managed wrapper command"
  grep -Fqx 'EnvironmentFile=/etc/default/codex-app-server' "$service_tmp" ||
    devops_fatal "Codex app-server unit is missing its non-secret environment policy"
  grep -Fqx 'LoadCredential=codex-mcp.env:/data/codex/credentials/mcp.env' "$service_tmp" ||
    devops_fatal "Codex app-server unit is missing its MCP credential environment"
  grep -Fqx 'EnvironmentFile=-%d/codex-mcp.env' "$service_tmp" ||
    devops_fatal "Codex app-server unit does not let systemd decode the MCP credential environment"
  if grep -Eq '^[[:space:]]*[^#[:space:]].*auth\.json' "$service_tmp"; then
    devops_fatal "Codex app-server unit must not require or overmount pre-login auth.json state"
  fi
  if grep -Eq '^ExecStart=.*/data/codex/(share/bin/codex|lib/codex-app-server)([[:space:]]|$)' "$service_tmp"; then
    devops_fatal "Codex app-server unit bypasses the managed wrapper"
  fi
  if grep -Eq '^[[:space:]]*User=' "$service_tmp"; then
    devops_fatal "Codex app-server user unit must inherit its account identity from the user manager"
  fi

  for managed_base_dir in "${target_root}/etc/default" "${target_root}/etc/skel"; do
    if [ -e "$managed_base_dir" ] || [ -L "$managed_base_dir" ]; then
      [ -d "$managed_base_dir" ] && [ ! -L "$managed_base_dir" ] ||
        devops_fatal "Codex app-server base directory is indirect: $managed_base_dir"
    else
      install -d -m 0755 -- "$managed_base_dir"
    fi
    [ "$(readlink -f -- "$managed_base_dir")" = "$managed_base_dir" ] ||
      devops_fatal "Codex app-server base directory traverses a symlink: $managed_base_dir"
    chmod 0755 "$managed_base_dir"
    chown root:root "$managed_base_dir"
    [ "$(stat -c '%u:%g:%a' -- "$managed_base_dir")" = 0:0:755 ] ||
      devops_fatal "Codex app-server base directory has unsafe ownership or mode: $managed_base_dir"
  done
  unset managed_base_dir

  for managed_unit_dir in \
    "$template_config_dir" \
    "$template_systemd_dir" \
    "$template_unit_dir" \
    "$template_wants_dir" \
    "$user_config_dir" \
    "$user_systemd_dir" \
    "$user_unit_dir" \
    "$wants_dir"
  do
    case "$managed_unit_dir" in
      "$template_config_dir"|"$template_systemd_dir"|"$template_unit_dir"|"$template_wants_dir")
        managed_unit_owner=0:0
        ;;
      *)
        managed_unit_owner=$account_ids
        ;;
    esac
    if [ -e "$managed_unit_dir" ] || [ -L "$managed_unit_dir" ]; then
      [ -d "$managed_unit_dir" ] && [ ! -L "$managed_unit_dir" ] ||
        devops_fatal "Codex app-server user-unit directory is indirect: $managed_unit_dir"
      chmod 0700 "$managed_unit_dir"
    else
      install -d -m 0700 -- "$managed_unit_dir"
    fi
    [ "$(readlink -f -- "$managed_unit_dir")" = "$managed_unit_dir" ] ||
      devops_fatal "Codex app-server user-unit directory traverses a symlink: $managed_unit_dir"
    chown "$managed_unit_owner" "$managed_unit_dir"
    [ "$(stat -c '%u:%g:%a' -- "$managed_unit_dir")" = "${managed_unit_owner}:700" ] ||
      devops_fatal "Codex app-server user-unit directory has unsafe ownership or mode: $managed_unit_dir"
  done
  unset managed_unit_dir managed_unit_owner

  for managed_unit_target in "$environment_target" "$template_service" "$service_target"; do
    if [ -e "$managed_unit_target" ] || [ -L "$managed_unit_target" ]; then
      [ -f "$managed_unit_target" ] && [ ! -L "$managed_unit_target" ] ||
        devops_fatal "Codex app-server managed file is indirect: $managed_unit_target"
    fi
  done
  unset managed_unit_target

  install -m 0644 -- "$environment_tmp" "$environment_target"
  install -m 0644 -- "$service_tmp" "$template_service"
  install -m 0644 -- "$service_tmp" "$service_target"
  chown root:root "$environment_target" "$template_service"
  chown "$account_ids" "$service_target"

  for managed_unit_link in "$template_link" "$service_link"; do
    if [ -L "$managed_unit_link" ]; then
      [ "$(readlink -- "$managed_unit_link")" = ../codex-app-server.service ] ||
        devops_fatal "Codex app-server enablement link has an unexpected target: $managed_unit_link"
    elif [ -e "$managed_unit_link" ]; then
      devops_fatal "Codex app-server enablement path is not a symlink: $managed_unit_link"
    else
      ln -s -- ../codex-app-server.service "$managed_unit_link"
    fi
  done
  chown -h root:root "$template_link"
  chown -h "$account_ids" "$service_link"
  unset managed_unit_link

  cmp -s -- "$template_service" "$service_target" ||
    devops_fatal "Codex app-server account unit differs from its skeleton source"
  [ "$(stat -c '%u:%g:%a' -- "$template_service")" = 0:0:644 ] ||
    devops_fatal "Codex app-server skeleton unit has unsafe ownership or mode"
  [ "$(stat -c '%u:%g:%a' -- "$service_target")" = "${account_ids}:644" ] ||
    devops_fatal "Codex app-server account unit has unsafe ownership or mode"
  [ "$(stat -c '%u:%g:%a' -- "$environment_target")" = 0:0:644 ] ||
    devops_fatal "Codex app-server environment file has unsafe ownership or mode"

  rm -f -- "$environment_tmp" "$service_tmp"
}

devops_install_pinned_codex() {
  # Build and validate every release component in private staging first. Final
  # paths are published only after the archive and repository pin both pass.
  # shellcheck disable=SC2016
  run_in_target "download and install pinned managed Codex" /bin/sh -eu -c '
umask 022

codex_fatal() {
  printf "fatal: %s\n" "$*" >&2
  exit 1
}

codex_require_command() {
  command -v "$1" >/dev/null 2>&1 ||
    codex_fatal "required command is unavailable: $1"
}

codex_chmod_without_special_bits() {
  requested_mode=$1
  shift

  case "$requested_mode" in
    0644|0700|0750|0755) ;;
    *) codex_fatal "unsupported Codex managed mode: $requested_mode" ;;
  esac
  [ "$#" -gt 0 ] ||
    codex_fatal "Codex managed mode requires at least one path"

  chmod "$requested_mode" -- "$@" ||
    codex_fatal "unable to apply Codex managed mode $requested_mode"
  chmod a-s -- "$@" ||
    codex_fatal "unable to clear special bits from Codex managed paths"
}

codex_chmod_group_shared() {
  [ "$#" -gt 0 ] ||
    codex_fatal "Codex group-shared mode requires at least one directory"

  for shared_path in "$@"; do
    [ -d "$shared_path" ] && [ ! -L "$shared_path" ] ||
      codex_fatal "Codex group-shared path is not a direct directory: $shared_path"
  done
  unset shared_path

  chmod 0770 -- "$@" ||
    codex_fatal "unable to apply Codex group-shared permissions"
  chmod a-s -- "$@" ||
    codex_fatal "unable to clear unexpected special bits from Codex group-shared directories"
  chmod g+s -- "$@" ||
    codex_fatal "unable to preserve Codex devops-group inheritance"
}

codex_validate_positive_integer() {
  label=$1
  value=$2

  case "$value" in
    ""|*[!0123456789]*) codex_fatal "${label} must be a positive integer" ;;
  esac
  [ "$value" -gt 0 ] || codex_fatal "${label} must be greater than zero"
}

codex_tree_matches() {
  expected_tree=$1
  actual_tree=$2
  exclude_root_git=$3
  expected_snapshot="${staging_dir}/expected-tree.tar"
  actual_snapshot="${staging_dir}/actual-tree.tar"

  [ -d "$expected_tree" ] && [ ! -L "$expected_tree" ] || return 1
  [ -d "$actual_tree" ] && [ ! -L "$actual_tree" ] || return 1
  rm -f -- "$expected_snapshot" "$actual_snapshot"
  if [ "$exclude_root_git" = 1 ]; then
    # Runtime state is explicitly typed, scoped and permission checked. Never
    # run Git against account-writable configuration from a privileged shell.
    python3 "$state_helper_path" --expected "$expected_tree" --actual "$actual_tree" \
      --uid "$account_uid" --gid "$devops_gid" --commit "$repository_commit" \
      --url "$repository_url" --codex-root "$codex_root"
    return $?
  else
    tar --sort=name --format=gnu --mtime=@0 --numeric-owner \
      -cf "$expected_snapshot" -C "$expected_tree" . ||
      codex_fatal "unable to snapshot staged Codex managed tree"
    tar --sort=name --format=gnu --mtime=@0 --numeric-owner \
      -cf "$actual_snapshot" -C "$actual_tree" . ||
      codex_fatal "unable to snapshot existing Codex managed tree"
  fi
  if cmp -s -- "$expected_snapshot" "$actual_snapshot"; then
    rm -f -- "$expected_snapshot" "$actual_snapshot"
    return 0
  fi
  rm -f -- "$expected_snapshot" "$actual_snapshot"
  return 1
}

codex_file_matches() {
  expected_file=$1
  actual_file=$2

  [ -f "$expected_file" ] && [ ! -L "$expected_file" ] || return 1
  [ -f "$actual_file" ] && [ ! -L "$actual_file" ] || return 1
  [ "$(stat -c "%u:%g:%a" -- "$actual_file")" = \
    "$(stat -c "%u:%g:%a" -- "$expected_file")" ] || return 1
  cmp -s -- "$expected_file" "$actual_file"
}

codex_version=$1
shift
release_tag=$1
shift
archive_url=$1
shift
expected_sha256=$1
shift
maximum_bytes=$1
shift
maximum_extracted_bytes=$1
shift
archive_binary_dir=$1
shift
archive_schema_member=$1
shift
codex_root=$1
shift
binary_path=$1
shift
schema_path=$1
shift
wrapper_path=$1
shift
user_root=$1
shift
system_config_dir=$1
shift
log_dir=$1
shift
sqlite_home=$1
shift
runtime_root=$1
shift
repository_url=$1
shift
repository_branch=$1
shift
repository_commit=$1
shift
agents_path=$1
shift
home_path=$1
shift
skills_path=$1
shift
archive_helper_path=$1
shift
account_user=$1

case "$codex_version" in
  ""|*[!A-Za-z0-9._+-]*)
    codex_fatal "Codex version contains unsupported syntax: $codex_version"
    ;;
esac
case "$release_tag" in
  ""|*[!A-Za-z0-9._+-]*)
    codex_fatal "Codex release tag contains unsupported syntax: $release_tag"
    ;;
esac
case "$archive_url" in
  https://*) ;;
  *) codex_fatal "Codex release URL must use HTTPS" ;;
esac
case "$archive_url" in
  *[[:space:]]*) codex_fatal "Codex release URL must not contain whitespace" ;;
esac
case "$expected_sha256" in
  *[!0123456789abcdef]*|"") codex_fatal "expected SHA-256 is malformed" ;;
esac
[ "${#expected_sha256}" -eq 64 ] ||
  codex_fatal "expected SHA-256 must have 64 hexadecimal characters"
codex_validate_positive_integer "maximum byte limit" "$maximum_bytes"
codex_validate_positive_integer \
  "maximum extracted byte limit" \
  "$maximum_extracted_bytes"
case "$archive_binary_dir" in
  ""|*[!A-Za-z0-9._+-]*)
    codex_fatal "Codex archive binary directory is malformed: $archive_binary_dir"
    ;;
esac
case "$archive_schema_member" in
  ""|*[!A-Za-z0-9._+-]*)
    codex_fatal "Codex archive schema member is malformed: $archive_schema_member"
    ;;
esac
[ "$codex_root" = /data/codex ] ||
  codex_fatal "Codex root is not approved: $codex_root"
[ "$binary_path" = "$codex_root/share/bin/codex" ] ||
  codex_fatal "Codex binary path is not approved: $binary_path"
[ "$schema_path" = "$codex_root/$archive_schema_member" ] ||
  codex_fatal "Codex schema path does not match the profile-owned archive schema member"
[ "$wrapper_path" = "$codex_root/lib/codex" ] ||
  codex_fatal "Codex wrapper path is not approved: $wrapper_path"
[ "$user_root" = "$codex_root/usr" ] ||
  codex_fatal "Codex user root is not approved: $user_root"
[ "$system_config_dir" = /etc/codex ] ||
  codex_fatal "Codex system configuration path is not approved: $system_config_dir"
[ "$log_dir" = "$codex_root/log" ] ||
  codex_fatal "Codex log path is not approved: $log_dir"
[ "$sqlite_home" = "$codex_root/sqlite" ] ||
  codex_fatal "Codex SQLite path is not approved: $sqlite_home"
[ "$runtime_root" = "$codex_root/runtime" ] ||
  codex_fatal "Codex runtime path is not approved: $runtime_root"
[ "$repository_url" = https://github.com/mjcramerz/codex-home ] ||
  codex_fatal "Codex repository URL is not approved"
[ "$repository_branch" = mcr/main ] ||
  codex_fatal "Codex repository branch is not approved"
case "$repository_commit" in
  *[!0123456789abcdef]*|"") codex_fatal "Codex repository commit is malformed" ;;
esac
[ "${#repository_commit}" -eq 40 ] ||
  codex_fatal "Codex repository commit must have 40 hexadecimal characters"
[ "$agents_path" = "$user_root/agents" ] ||
  codex_fatal "Codex agents path is not approved: $agents_path"
[ "$home_path" = "$user_root/home" ] ||
  codex_fatal "Codex home path is not approved: $home_path"
[ "$skills_path" = "$user_root/skills" ] ||
  codex_fatal "Codex skills path is not approved: $skills_path"
[ "$archive_helper_path" = "$codex_root/.installer-codex-archive.py" ] ||
  codex_fatal "Codex archive helper path is not approved: $archive_helper_path"

for required_command in \
  awk \
  chmod \
  chown \
  cmp \
  cp \
  curl \
  find \
  getent \
  git \
  id \
  install \
  mktemp \
  mv \
  python3 \
  rm \
  rmdir \
  sha256sum \
  stat \
  tar \
  timeout \
  tr \
  wc
do
  codex_require_command "$required_command"
done
unset required_command
getent passwd "$account_user" >/dev/null 2>&1 ||
  codex_fatal "required Codex account is missing: $account_user"
devops_group_record=$(getent group devops) ||
  codex_fatal "required target group is missing: devops"
account_uid=$(id -u "$account_user")
devops_gid=${devops_group_record#*:}
devops_gid=${devops_gid#*:}
devops_gid=${devops_gid%%:*}
case "$account_uid:$devops_gid" in
  *[!0123456789:]*|:*|*:)
    codex_fatal "unable to resolve Codex account or devops group ids"
    ;;
esac

[ -d "$codex_root" ] && [ ! -L "$codex_root" ] ||
  codex_fatal "prepared Codex root is missing or indirect: $codex_root"
[ -d "$codex_root/share/bin" ] && [ ! -L "$codex_root/share/bin" ] ||
  codex_fatal "prepared Codex binary directory is missing or indirect"
[ -x "$wrapper_path" ] && [ ! -L "$wrapper_path" ] ||
  codex_fatal "staged Codex wrapper is missing or indirect: $wrapper_path"
[ -f "$archive_helper_path" ] && [ ! -L "$archive_helper_path" ] ||
  codex_fatal "staged Codex archive helper is missing or indirect: $archive_helper_path"
[ "$(stat -c "%u:%g:%a" -- "$archive_helper_path")" = 0:0:700 ] ||
  codex_fatal "staged Codex archive helper has unexpected ownership or mode"

state_helper_path="${archive_helper_path%/*}/.installer-codex-state.py"
[ -f "$state_helper_path" ] && [ ! -L "$state_helper_path" ] ||
  codex_fatal "Codex state verifier is missing or indirect"
[ "$(stat -c "%u:%g:%a" -- "$state_helper_path")" = 0:0:700 ] ||
  codex_fatal "Codex state verifier has unsafe ownership or mode"

staging_dir=
config_staging=
publication_committed=0
published_binary_directory=0
published_schema=0
published_repository=0
published_config=0
published_release_marker=0
removed_binary_placeholder=0
release_marker="${codex_root}/.managed-codex-release"
cleanup() {
  if [ "$publication_committed" = 0 ]; then
    [ "$published_release_marker" = 0 ] || rm -f -- "$release_marker"
    [ "$published_config" = 0 ] || rm -rf -- "$system_config_dir"
    [ "$published_repository" = 0 ] || rm -rf -- "$user_root"
    [ "$published_schema" = 0 ] || rm -f -- "$schema_path"
    [ "$published_binary_directory" = 0 ] || rm -rf -- "$codex_root/share/bin"
    if [ "$removed_binary_placeholder" = 1 ] && \
      [ ! -e "$codex_root/share/bin" ] && [ ! -L "$codex_root/share/bin" ]; then
      install -d -m 0755 -o root -g root "$codex_root/share/bin" || true
    fi
  fi
  if [ -n "$staging_dir" ]; then
    rm -rf -- "$staging_dir"
  fi
  if [ -n "$config_staging" ]; then
    rm -rf -- "$config_staging"
  fi
  rm -f -- "$archive_helper_path" "$state_helper_path"
}
trap '"'"'cleanup_status=$?; trap - EXIT; set +e; cleanup; exit "$cleanup_status"'"'"' EXIT
trap "exit 129" HUP
trap "exit 130" INT
trap "exit 143" TERM

staging_dir=$(mktemp -d "${codex_root}/.install.XXXXXXXX") ||
  codex_fatal "unable to allocate Codex staging directory"
archive_path="${staging_dir}/codex.tar.gz"
curl \
  --fail \
  --silent \
  --show-error \
  --location \
  --proto "=https" \
  --tlsv1.2 \
  --retry 3 \
  --retry-delay 2 \
  --connect-timeout 15 \
  --max-time 900 \
  --max-filesize "$maximum_bytes" \
  --output "$archive_path" \
  "$archive_url" ||
  codex_fatal "failed to download pinned managed Codex release: $archive_url"

archive_bytes=$(wc -c <"$archive_path" | tr -d "[[:space:]]")
case "$archive_bytes" in
  ""|*[!0123456789]*) codex_fatal "downloaded Codex archive size is invalid" ;;
esac
[ "$archive_bytes" -gt 0 ] ||
  codex_fatal "downloaded Codex archive is empty"
[ "$archive_bytes" -le "$maximum_bytes" ] ||
  codex_fatal "downloaded Codex archive exceeds the configured maximum"

actual_sha256=$(sha256sum "$archive_path" | awk "{print \$1}")
[ "$actual_sha256" = "$expected_sha256" ] ||
  codex_fatal "managed Codex SHA-256 mismatch for ${archive_url}"

extract_dir="${staging_dir}/extract"
install -d -m 0700 "$extract_dir"
python3 "$archive_helper_path" \
  --archive "$archive_path" \
  --output-directory "$extract_dir" \
  --binary-directory "$archive_binary_dir" \
  --schema-member "$archive_schema_member" \
  --maximum-extracted-bytes "$maximum_extracted_bytes" ||
  codex_fatal "managed Codex archive validation or extraction failed"

extracted_binary_dir="$extract_dir/$archive_binary_dir"
[ -d "$extracted_binary_dir" ] && [ ! -L "$extracted_binary_dir" ] ||
  codex_fatal "managed Codex archive did not produce a direct binary directory"
first_extracted_binary=$(find "$extracted_binary_dir" \
  -mindepth 1 -maxdepth 1 -type f -links 1 -print)
[ -n "$first_extracted_binary" ] ||
  codex_fatal "managed Codex archive did not produce any binaries"
hidden_extracted_binary=$(find "$extracted_binary_dir" \
  -mindepth 1 -maxdepth 1 -name ".*" -print)
[ -z "$hidden_extracted_binary" ] ||
  codex_fatal "managed Codex archive produced an unexpected hidden binary"
unsafe_extracted_binary=$(find "$extracted_binary_dir" \
  -mindepth 1 -maxdepth 1 \( ! -type f -o -type l -o ! -links 1 \) -print)
[ -z "$unsafe_extracted_binary" ] ||
  codex_fatal "managed Codex archive produced an unsafe binary entry"
for extracted_path in "$extracted_binary_dir"/*; do
  [ -f "$extracted_path" ] && [ ! -L "$extracted_path" ] ||
    codex_fatal "extracted Codex binary is missing or indirect: $extracted_path"
  binary_name=${extracted_path##*/}
  case "$binary_name" in
    ""|*[!A-Za-z0-9._+-]*)
      codex_fatal "extracted Codex binary name is malformed: $binary_name"
      ;;
  esac
  chown root:root "$extracted_path"
  codex_chmod_without_special_bits 0755 "$extracted_path"
done
unset binary_name extracted_path
chown root:root "$extracted_binary_dir"
codex_chmod_without_special_bits 0755 "$extracted_binary_dir"

candidate_binary_path="$extracted_binary_dir/codex"
[ -x "$candidate_binary_path" ] && [ ! -L "$candidate_binary_path" ] ||
  codex_fatal "managed Codex archive is missing its required entrypoint"
version_output=$(timeout --kill-after=5 30 "$candidate_binary_path" --version 2>/dev/null) || codex_fatal "pinned Codex binary failed its version check"
case "$version_output" in
  *"$codex_version"*) ;;
  *) codex_fatal "Codex version verification failed for staged release" ;;
esac

extracted_schema_path="$extract_dir/$archive_schema_member"
[ -f "$extracted_schema_path" ] && [ ! -L "$extracted_schema_path" ] ||
  codex_fatal "extracted Codex configuration schema is missing or indirect"
chown root:root "$extracted_schema_path"
codex_chmod_without_special_bits 0644 "$extracted_schema_path"
unset first_extracted_binary hidden_extracted_binary unsafe_extracted_binary

repository_staging="${staging_dir}/repository"
export GIT_TERMINAL_PROMPT=0 GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null
timeout --signal=TERM --kill-after=10 180 git clone \
  --no-checkout \
  --depth 1 \
  --no-hardlinks \
  --single-branch \
  --branch "$repository_branch" \
  --no-tags \
  -- "$repository_url" \
  "$repository_staging" ||
  codex_fatal "failed to clone the pinned Codex home repository"
actual_repository_url=$(git -C "$repository_staging" remote get-url origin)
[ "$actual_repository_url" = "$repository_url" ] ||
  codex_fatal "cloned Codex home repository remote does not match policy"
timeout --signal=TERM --kill-after=10 180 git -C "$repository_staging" fetch \
  --quiet \
  --no-tags \
  --depth 1 \
  origin \
  "$repository_commit" ||
  codex_fatal "failed to fetch the pinned Codex home repository commit"
actual_repository_commit=$(git -C "$repository_staging" rev-parse FETCH_HEAD)
[ "$actual_repository_commit" = "$repository_commit" ] ||
  codex_fatal "fetched Codex home commit does not match policy"
git -C "$repository_staging" checkout --detach "$repository_commit" >/dev/null 2>&1 ||
  codex_fatal "failed to detach the Codex home repository at the pinned commit"
actual_repository_commit=$(git -C "$repository_staging" rev-parse HEAD)
[ "$actual_repository_commit" = "$repository_commit" ] ||
  codex_fatal "checked out Codex home commit does not match policy"

for required_repository_dir in agents etc home skills; do
  [ -d "$repository_staging/$required_repository_dir" ] &&
    [ ! -L "$repository_staging/$required_repository_dir" ] ||
    codex_fatal "Codex home repository is missing required directory: $required_repository_dir"
done
for forbidden_repository_state in \
  home/auth.json \
  home/app-server-control \
  home/packages
do
  [ ! -e "$repository_staging/$forbidden_repository_state" ] &&
    [ ! -L "$repository_staging/$forbidden_repository_state" ] ||
    codex_fatal "Codex home repository must not contain runtime credential or package state: $forbidden_repository_state"
done
unset forbidden_repository_state
unsafe_etc_entry=$(find "$repository_staging/etc" -xdev \
  \( -type l -o \( ! -type f ! -type d \) \) -print)
[ -z "$unsafe_etc_entry" ] ||
  codex_fatal "Codex repository etc tree contains an unsafe entry: $unsafe_etc_entry"

repository_git_path="$repository_staging/.git"
[ -d "$repository_git_path" ] && [ ! -L "$repository_git_path" ] ||
  codex_fatal "staged Codex repository metadata is missing or indirect"
unsafe_repository_git_entry=$(find "$repository_git_path" -xdev \
  \( -type l -o \( ! -type d ! -type f \) -o \( -type f ! -links 1 \) \) \
  -print -quit)
[ -z "$unsafe_repository_git_entry" ] ||
  codex_fatal "Codex repository metadata contains an unsafe entry: $unsafe_repository_git_entry"
unset unsafe_repository_git_entry

candidate_home_path="$repository_staging/home"
candidate_memories_path="${candidate_home_path}/memories"
chown -R "$account_user:devops" "$repository_staging"
find "$repository_staging" -xdev -type d -exec chmod a-s,go-w -- {} +
find "$repository_staging" -xdev -type f -exec chmod a-s,go-w -- {} +
chown -R "$account_user:devops" "$repository_git_path"
find "$repository_git_path" -xdev -type d -exec chmod 0750 -- {} +
find "$repository_git_path" -xdev -type f -exec chmod 0640 -- {} +
chown -R root:root "$repository_staging/etc"
codex_chmod_without_special_bits 0755 "$repository_staging/etc"

install -d -m 2770 -o "$account_user" -g devops \
  "$candidate_home_path/sessions" \
  "$candidate_home_path/shell_snapshots" \
  "$candidate_home_path/archived_sessions"
for state_file in history.jsonl session_index.jsonl external_agent_session_imports.json; do
  install -m 0660 -o "$account_user" -g devops /dev/null \
    "$candidate_home_path/$state_file"
done

if [ ! -e "$candidate_memories_path" ]; then
  install -d -m 2770 -o "$account_user" -g devops "$candidate_memories_path"
fi
[ -d "$candidate_memories_path" ] && [ ! -L "$candidate_memories_path" ] ||
  codex_fatal "staged Codex memories path is missing or indirect"
rm -rf -- "$candidate_memories_path/.git"
chown -R "$account_user:devops" "$candidate_memories_path"
find "$candidate_home_path" -xdev -type d -exec chmod a-s,g=u,o=,g+s -- {} +
find "$candidate_home_path" -xdev -type f -exec chmod a-s,g=u,o= -- {} +

chown "$account_user:devops" \
  "$repository_staging" "$candidate_home_path" "$candidate_memories_path"
codex_chmod_without_special_bits 0750 "$repository_staging"
codex_chmod_group_shared "$candidate_home_path" "$candidate_memories_path"
install -m 0660 -o "$account_user" -g devops /dev/null \
  "$candidate_memories_path/.git"
[ -f "$candidate_memories_path/.git" ] && \
  [ ! -L "$candidate_memories_path/.git" ] ||
  codex_fatal "staged Codex memories .git marker is not a direct regular file"

# Stage the same policy that tmpfiles applies after publication. Previously the
# publication omitted runtime links and changed modes only AFTER the commit.
chmod 0750 "$repository_staging/agents" "$repository_staging/skills"
install -d -m 0700 -o "$account_user" -g devops "$candidate_home_path/app-server-control"
install -m 0600 -o "$account_user" -g devops /dev/null \
  "$candidate_home_path/app-server-control/app-server-startup.lock"
ln -s -- "$codex_root/packages" "$candidate_home_path/packages"
ln -s -- "$codex_root/sockets/app-server-control.sock" \
  "$candidate_home_path/app-server-control/app-server-control.sock"
chown -h "$account_user:devops" "$candidate_home_path/packages" \
  "$candidate_home_path/app-server-control/app-server-control.sock"
# Validate the private candidate too, so no unsafe repository symlink or Git
# configuration is ever published. The same check defines safe resume.
python3 "$state_helper_path" --expected "$repository_staging" --actual "$repository_staging" \
  --uid "$account_uid" --gid "$devops_gid" --commit "$repository_commit" \
  --url "$repository_url" --codex-root "$codex_root" ||
  codex_fatal "staged Codex repository violates publication policy"

config_staging=$(mktemp -d "/etc/.codex.XXXXXXXX") ||
  codex_fatal "unable to allocate Codex system configuration staging directory"
cp -a -- "$repository_staging/etc/." "$config_staging/"
chown -R root:root "$config_staging"
find "$config_staging" -xdev -type d -exec chmod a-s,go-w -- {} +
find "$config_staging" -xdev -type f -exec chmod a-s,go-w -- {} +
codex_chmod_without_special_bits 0755 "$config_staging"

candidate_release_marker="${staging_dir}/managed-codex-release"
{
  printf "version=%s\n" "$codex_version"
  printf "release_tag=%s\n" "$release_tag"
  printf "url=%s\n" "$archive_url"
  printf "sha256=%s\n" "$expected_sha256"
  printf "archive_bytes=%s\n" "$archive_bytes"
  printf "maximum_archive_bytes=%s\n" "$maximum_bytes"
  printf "maximum_extracted_bytes=%s\n" "$maximum_extracted_bytes"
  printf "archive_binary_directory=%s\n" "$archive_binary_dir"
  printf "schema=%s\n" "$schema_path"
  printf "repository=%s\n" "$repository_url"
  printf "repository_branch=%s\n" "$repository_branch"
  printf "repository_commit=%s\n" "$repository_commit"
  printf "binary=%s\n" "$binary_path"
  printf "wrapper=%s\n" "$wrapper_path"
} >"$candidate_release_marker"
chmod 0644 "$candidate_release_marker"
chown root:root "$candidate_release_marker"

# Resume verified immutable components and separately validated mutable account
# state. Conflicts remain fatal; no unrelated destination is removed or adopted.
publish_binary_directory=0
existing_binary_entry=$(find "$codex_root/share/bin" \
  -mindepth 1 -maxdepth 1 -print -quit)
if [ -z "$existing_binary_entry" ]; then
  [ "$(stat -c "%u:%g:%a" -- "$codex_root/share/bin")" = 0:0:755 ] ||
    codex_fatal "empty Codex binary directory has unexpected ownership or mode"
  publish_binary_directory=1
elif ! codex_tree_matches "$extracted_binary_dir" "$codex_root/share/bin" 0; then
  codex_fatal "existing Codex binary directory conflicts with the pinned release"
fi
unset existing_binary_entry

publish_schema=0
if [ -e "$schema_path" ] || [ -L "$schema_path" ]; then
  codex_file_matches "$extracted_schema_path" "$schema_path" ||
    codex_fatal "existing Codex schema conflicts with the pinned release: $schema_path"
else
  publish_schema=1
fi

publish_repository=0
if [ -e "$user_root" ] || [ -L "$user_root" ]; then
  codex_tree_matches "$repository_staging" "$user_root" 1 ||
    codex_fatal "existing Codex repository tree conflicts with the pinned revision"

else
  publish_repository=1
fi

publish_config=0
if [ -e "$system_config_dir" ] || [ -L "$system_config_dir" ]; then
  codex_tree_matches "$config_staging" "$system_config_dir" 0 ||
    codex_fatal "existing Codex system configuration conflicts with the pinned revision"
else
  publish_config=1
fi

publish_release_marker=0
if [ -e "$release_marker" ] || [ -L "$release_marker" ]; then
  codex_file_matches "$candidate_release_marker" "$release_marker" ||
    codex_fatal "existing Codex release marker conflicts with the pinned release"
else
  publish_release_marker=1
fi

# All conflict checks are complete. Publish only destinations that are absent;
# rollback removes only paths moved into place by this invocation.
if [ "$publish_binary_directory" = 1 ]; then
  rmdir -- "$codex_root/share/bin" ||
    codex_fatal "unable to remove empty Codex binary directory before publication"
  removed_binary_placeholder=1
  mv -- "$extracted_binary_dir" "$codex_root/share/bin" ||
    codex_fatal "unable to publish pinned Codex binary directory"
  published_binary_directory=1
fi
if [ "$publish_schema" = 1 ]; then
  mv -- "$extracted_schema_path" "$schema_path" ||
    codex_fatal "unable to publish pinned Codex configuration schema"
  published_schema=1
fi
if [ "$publish_repository" = 1 ]; then
  mv -- "$repository_staging" "$user_root" ||
    codex_fatal "unable to publish pinned Codex home repository"
  published_repository=1
fi
if [ "$publish_config" = 1 ]; then
  mv -- "$config_staging" "$system_config_dir" ||
    codex_fatal "unable to publish pinned Codex system configuration"
  published_config=1
  config_staging=
fi
if [ "$publish_release_marker" = 1 ]; then
  mv -- "$candidate_release_marker" "$release_marker" ||
    codex_fatal "unable to publish managed Codex release marker"
  published_release_marker=1
fi

[ -x "$binary_path" ] && [ ! -L "$binary_path" ] ||
  codex_fatal "published Codex entrypoint is missing or indirect"
version_output=$(timeout --kill-after=5 30 "$binary_path" --version 2>/dev/null) || codex_fatal "published Codex binary failed its version check"
case "$version_output" in
  *"$codex_version"*) ;;
  *) codex_fatal "published Codex version verification failed" ;;
esac
[ -f "$schema_path" ] && [ ! -L "$schema_path" ] ||
  codex_fatal "published Codex schema is missing or indirect"
[ -d "$user_root/.git" ] && [ ! -L "$user_root/.git" ] ||
  codex_fatal "published Codex repository metadata is missing or indirect"
[ -d "$system_config_dir" ] && [ ! -L "$system_config_dir" ] ||
  codex_fatal "published Codex system configuration is missing or indirect"
[ -f "$release_marker" ] && [ ! -L "$release_marker" ] ||
  codex_fatal "published Codex release marker is missing or indirect"

publication_committed=1
printf "installed managed Codex %s at %s with wrapper %s\n" \
  "$codex_version" \
  "$binary_path" \
  "$wrapper_path"
' sh \
    "$DEVOPS_CODEX_VERSION" \
    "$DEVOPS_CODEX_RELEASE_TAG" \
    "$DEVOPS_CODEX_URL" \
    "$DEVOPS_CODEX_SHA256" \
    "$DEVOPS_CODEX_MAXIMUM_BYTES" \
    "$DEVOPS_CODEX_MAXIMUM_EXTRACTED_BYTES" \
    "$DEVOPS_CODEX_ARCHIVE_BINARY_DIR" \
    "$DEVOPS_CODEX_ARCHIVE_SCHEMA_MEMBER" \
    "$DEVOPS_CODEX_ROOT" \
    "$DEVOPS_CODEX_BINARY_PATH" \
    "$DEVOPS_CODEX_SCHEMA_PATH" \
    "$DEVOPS_CODEX_WRAPPER_PATH" \
    "$DEVOPS_CODEX_USER_ROOT" \
    "$DEVOPS_CODEX_SYSTEM_CONFIG_DIR" \
    "$DEVOPS_CODEX_LOG_DIR" \
    "$DEVOPS_CODEX_SQLITE_HOME" \
    "$DEVOPS_CODEX_RUNTIME_ROOT" \
    "$DEVOPS_CODEX_REPOSITORY_URL" \
    "$DEVOPS_CODEX_REPOSITORY_BRANCH" \
    "$DEVOPS_CODEX_REPOSITORY_COMMIT" \
    "$DEVOPS_CODEX_AGENTS" \
    "$DEVOPS_CODEX_HOME" \
    "$DEVOPS_CODEX_SKILLS" \
    "$devops_codex_archive_helper_path" \
    "$ACCOUNT_USERNAME"
}

devops_run_as_account() {
  run_label=$1
  shift

  run_in_target \
    "$run_label" \
    /usr/sbin/runuser \
      -u "$ACCOUNT_USERNAME" \
      -- \
      /usr/bin/env -i \
        HOME="$ACCOUNT_HOME" \
        USER="$ACCOUNT_USERNAME" \
        LOGNAME="$ACCOUNT_USERNAME" \
        PATH="${CARGO_INSTALL_ROOT}/bin:${CARGO_HOME}/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
        XDG_CONFIG_HOME="${ACCOUNT_HOME}/.config" \
        CARGO_HOME="$CARGO_HOME" \
        CARGO_TARGET_DIR="$CARGO_TARGET_DIR" \
        CARGO_INSTALL_ROOT="$CARGO_INSTALL_ROOT" \
        RUSTUP_HOME="$RUSTUP_HOME" \
        RUSTUP_TOOLCHAIN="$DEVOPS_RUSTUP_TOOLCHAIN" \
        SCCACHE_DIR="$SCCACHE_DIR" \
        MISE_CONFIG_DIR="${ACCOUNT_HOME}/.config/mise" \
        MISE_DATA_DIR="$MISE_DATA_DIR" \
        MISE_STATE_DIR="$MISE_STATE_DIR" \
        MISE_CACHE_DIR="$MISE_CACHE_DIR" \
        MISE_TMP_DIR="$MISE_TMP_DIR" \
        BAZELISK_HOME="$BAZELISK_HOME" \
        ANSIBLE_HOME="$ANSIBLE_HOME" \
        ANSIBLE_GALAXY_CACHE_DIR="$ANSIBLE_GALAXY_CACHE_DIR" \
        CHECKPOINT_DISABLE=1 \
        PACKER_CACHE_DIR="$PACKER_CACHE_DIR" \
        PACKER_CONFIG="$PACKER_CONFIG_PATH" \
        PACKER_CONFIG_DIR="$PACKER_CONFIG_DIR" \
        PACKER_CONFIG_PATH="$PACKER_CONFIG_PATH" \
        PACKER_PLUGIN_PATH="$PACKER_PLUGIN_PATH" \
        TF_PLUGIN_CACHE_DIR="$TF_PLUGIN_CACHE_DIR" \
        "$@"
}

runtime_dir=${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}
bootstrap_lib=${INSTALLER_BOOTSTRAP_LIB:-${runtime_dir}/bootstrap/bootstrap.sh}
tmp_env_dir=${INSTALLER_LATE_TMP_ENV_DIR:-/tmp/install-env-late/devops}

[ -s "$bootstrap_lib" ] ||
  devops_fatal "installer bootstrap library is unavailable: $bootstrap_lib"
# shellcheck disable=SC1090,SC1091
. "$bootstrap_lib"
bootstrap_source_common_lib "" ||
  devops_fatal "failed to source installer common library"
seed_base=$(installer_current_seed_base 2>/dev/null || installer_seed_base "")
bootstrap_source_common_support_libs "$seed_base" "$tmp_env_dir" target ||
  devops_fatal "failed to source installer target support library"
installer_ensure_context_loaded "$seed_base"

installer_selected_class_reference_is_selected addon/devops 2>/dev/null || exit 0

case "${INSTALLER_HOST_VARIANT:-}" in
  desktop) ;;
  *) devops_fatal "addon/devops is restricted to the desktop role" ;;
esac

account_env=${INSTALLER_LATE_ACCOUNT_ENV:-/tmp/install-env-late/account.env}
host_env=${INSTALLER_LATE_HOST_ENV:-/tmp/install-env-late/host.env}
[ -r "$account_env" ] ||
  installer_fetch_account_env "$seed_base" "$account_env" 0600
[ -r "$host_env" ] ||
  installer_fetch_host_env \
    "$seed_base" \
    "$(installer_resolve_host_profile "")" \
    "$host_env" \
    0600

# shellcheck disable=SC1090,SC1091
. "$account_env"
# shellcheck disable=SC1090,SC1091
. "$host_env"

: "${ACCOUNT_USERNAME:?ACCOUNT_USERNAME must be set before DevOps provisioning}"
: "${ACCOUNT_HOME:?ACCOUNT_HOME must be set before DevOps provisioning}"
: "${DIR_POOL_BUILD:?DIR_POOL_BUILD must be set before DevOps provisioning}"
: "${DIR_POOL_CACHE:?DIR_POOL_CACHE must be set before DevOps provisioning}"
: "${DIR_POOL_DB:?DIR_POOL_DB must be set before DevOps provisioning}"

devops_validate_account_name "$ACCOUNT_USERNAME"
devops_validate_abs_path "ACCOUNT_HOME" "$ACCOUNT_HOME"
devops_validate_abs_path "DIR_POOL_BUILD" "$DIR_POOL_BUILD"
devops_validate_abs_path "DIR_POOL_CACHE" "$DIR_POOL_CACHE"
devops_validate_abs_path "DIR_POOL_DB" "$DIR_POOL_DB"
devops_validate_upstream_tool_policy
devops_validate_cargo_policy
devops_validate_bazel_policy
devops_validate_publishing_policy
devops_validate_codex_policy
devops_load_publishing_credentials

for pool_root in "$DIR_POOL_BUILD" "$DIR_POOL_CACHE" "$DIR_POOL_DB"; do
  [ -d "${target_root}${pool_root}" ] ||
    devops_fatal "shared runtime storage root is missing: ${target_root}${pool_root}"
done
unset pool_root

account_ids=$(devops_target_passwd_ids "$ACCOUNT_USERNAME")
[ -n "$account_ids" ] ||
  devops_fatal "target primary account is missing: $ACCOUNT_USERNAME"

DEVOPS_CODEX_STANDALONE_INSTALLER_HELPER=/usr/local/bin/codex-standalone-install
DEVOPS_CODEX_INSTALLER_SESSION_HELPER="${DEVOPS_CODEX_ROOT}/.installer-codex-standalone.session.py"
DEVOPS_CODEX_PACKAGES_ROOT="${DEVOPS_CODEX_ROOT}/packages"
DEVOPS_CODEX_SOCKETS_ROOT="${DEVOPS_CODEX_ROOT}/sockets"
DEVOPS_CODEX_CREDENTIALS_ROOT="${DEVOPS_CODEX_ROOT}/credentials"
DEVOPS_CODEX_APP_SERVER_SOCKET="${DEVOPS_CODEX_SOCKETS_ROOT}/app-server-control.sock"
DEVOPS_CODEX_APP_SERVER_CONTROL_DIR="${DEVOPS_CODEX_HOME}/app-server-control"
DEVOPS_CODEX_APP_SERVER_STARTUP_LOCK="${DEVOPS_CODEX_APP_SERVER_CONTROL_DIR}/app-server-startup.lock"
DEVOPS_CODEX_APP_SERVER_DEFAULT_SOCKET="${DEVOPS_CODEX_APP_SERVER_CONTROL_DIR}/app-server-control.sock"
DEVOPS_CODEX_APP_SERVER_ENVIRONMENT=/etc/default/codex-app-server
DEVOPS_CODEX_APP_SERVER_USER_UNIT="${ACCOUNT_HOME}/.config/systemd/user/codex-app-server.service"
DEVOPS_CODEX_APP_SERVER_USER_WANTS="${ACCOUNT_HOME}/.config/systemd/user/default.target.wants/codex-app-server.service"

CARGO_HOME="${DIR_POOL_CACHE}/${ACCOUNT_USERNAME}/cargo"
CARGO_TARGET_DIR="${DIR_POOL_BUILD}/${ACCOUNT_USERNAME}/cargo/target"
CARGO_INSTALL_ROOT="${DIR_POOL_BUILD}/${ACCOUNT_USERNAME}/cargo/install"
RUSTUP_HOME="${DIR_POOL_DB}/${ACCOUNT_USERNAME}/rustup"
SCCACHE_DIR="${DIR_POOL_CACHE}/${ACCOUNT_USERNAME}/sccache"
GOPATH="${DIR_POOL_BUILD}/${ACCOUNT_USERNAME}/go"
GOMODCACHE="${DIR_POOL_CACHE}/${ACCOUNT_USERNAME}/go-mod"
MISE_DATA_DIR="${DIR_POOL_DB}/${ACCOUNT_USERNAME}/mise/data"
MISE_STATE_DIR="${DIR_POOL_DB}/${ACCOUNT_USERNAME}/mise/state"
MISE_CACHE_DIR="${DIR_POOL_CACHE}/${ACCOUNT_USERNAME}/mise"
MISE_TMP_DIR="${DIR_POOL_CACHE}/${ACCOUNT_USERNAME}/mise/tmp"
BAZEL_CACHE_HOME="${DEVOPS_BAZEL_CACHE_ROOT}/${ACCOUNT_USERNAME}/${DEVOPS_BAZEL_CACHE_SUBDIR}"
BAZEL_DISK_CACHE="${BAZEL_CACHE_HOME}/${DEVOPS_BAZEL_DISK_CACHE_SUBDIR}"
BAZEL_REPOSITORY_CACHE="${BAZEL_CACHE_HOME}/${DEVOPS_BAZEL_REPOSITORY_CACHE_SUBDIR}"
BAZEL_OUTPUT_USER_ROOT="${DEVOPS_BAZEL_BUILD_ROOT}/${ACCOUNT_USERNAME}/${DEVOPS_BAZEL_OUTPUT_USER_ROOT_SUBDIR}"
BAZELISK_HOME="${DEVOPS_BAZEL_DB_ROOT}/${ACCOUNT_USERNAME}/${DEVOPS_BAZELISK_HOME_SUBDIR}"
ANSIBLE_HOME="${DIR_POOL_DB}/${ACCOUNT_USERNAME}/ansible"
ANSIBLE_GALAXY_CACHE_DIR="${DIR_POOL_CACHE}/${ACCOUNT_USERNAME}/ansible/galaxy"
HASHICORP_CACHE_ROOT="${DIR_POOL_CACHE}/${ACCOUNT_USERNAME}/hashicorp"
PACKER_CACHE_DIR="${HASHICORP_CACHE_ROOT}/packer/cache"
PACKER_CONFIG_DIR="${HASHICORP_CACHE_ROOT}/packer.d"
PACKER_CONFIG_PATH="${PACKER_CONFIG_DIR}/config.json"
PACKER_PLUGIN_PATH="${PACKER_CONFIG_DIR}/plugins"
TF_PLUGIN_CACHE_DIR="${HASHICORP_CACHE_ROOT}/terraform/plugin-cache"
APTLY_ROOT_DIR="${DIR_POOL_DB}/${ACCOUNT_USERNAME}/${DEVOPS_APTLY_ROOT_SUBDIR}"
APTLY_CONFIG="${APTLY_ROOT_DIR}/aptly.conf"
APTLY_R2_STORAGE_PREFIX=${DEVOPS_APTLY_R2_PREFIX#/}
APTLY_R2_STORAGE_PREFIX="${APTLY_R2_STORAGE_PREFIX%/}/"
OSC_STATE_DIR="${DIR_POOL_DB}/${ACCOUNT_USERNAME}/${DEVOPS_OSC_STATE_SUBDIR}"
OSC_CONFIG="${OSC_STATE_DIR}/oscrc"
OSC_MANAGED_CONFIG="${OSC_STATE_DIR}/managed.json"
OSC_COOKIE_JAR="${OSC_STATE_DIR}/cookiejar"
OSC_WORKDIR="${DIR_POOL_BUILD}/${ACCOUNT_USERNAME}/${DEVOPS_OSC_BUILD_SUBDIR}"
OSC_BUILD_ROOT="${OSC_WORKDIR}/build-root"
OSC_PACKAGE_CACHE_DIR="${DIR_POOL_CACHE}/${ACCOUNT_USERNAME}/${DEVOPS_OSC_CACHE_SUBDIR}/packages"

for devops_path in \
  "$BAZEL_CACHE_HOME" \
  "$BAZEL_DISK_CACHE" \
  "$BAZEL_REPOSITORY_CACHE" \
  "$BAZEL_OUTPUT_USER_ROOT" \
  "$BAZELISK_HOME" \
  "$ANSIBLE_HOME" \
  "$ANSIBLE_GALAXY_CACHE_DIR" \
  "$HASHICORP_CACHE_ROOT" \
  "$PACKER_CACHE_DIR" \
  "$PACKER_CONFIG_DIR" \
  "$PACKER_CONFIG_PATH" \
  "$PACKER_PLUGIN_PATH" \
  "$TF_PLUGIN_CACHE_DIR" \
  "$GOPATH" \
  "$GOMODCACHE" \
  "$APTLY_ROOT_DIR" \
  "$APTLY_CONFIG" \
  "$OSC_STATE_DIR" \
  "$OSC_CONFIG" \
  "$OSC_MANAGED_CONFIG" \
  "$OSC_COOKIE_JAR" \
  "$OSC_WORKDIR" \
  "$OSC_BUILD_ROOT" \
  "$OSC_PACKAGE_CACHE_DIR" \
  "$DEVOPS_CODEX_STANDALONE_INSTALLER_HELPER" \
  "$DEVOPS_CODEX_INSTALLER_SESSION_HELPER" \
  "$DEVOPS_CODEX_PACKAGES_ROOT" \
  "$DEVOPS_CODEX_SOCKETS_ROOT" \
  "$DEVOPS_CODEX_CREDENTIALS_ROOT" \
  "$DEVOPS_CODEX_APP_SERVER_SOCKET" \
  "$DEVOPS_CODEX_APP_SERVER_CONTROL_DIR" \
  "$DEVOPS_CODEX_APP_SERVER_STARTUP_LOCK" \
  "$DEVOPS_CODEX_APP_SERVER_DEFAULT_SOCKET" \
  "$DEVOPS_CODEX_APP_SERVER_ENVIRONMENT" \
  "$DEVOPS_CODEX_APP_SERVER_USER_UNIT" \
  "$DEVOPS_CODEX_APP_SERVER_USER_WANTS"
do
  devops_validate_abs_path "derived DevOps path" "$devops_path"
done
unset devops_path

# shellcheck disable=SC2016
run_in_target "create desktop DevOps runtime directories" /bin/sh -eu -c '
account_user=$1
build_root=$2
cache_root=$3
db_root=$4
bazel_cache_subdir=$5
bazel_disk_cache_subdir=$6
bazel_repository_cache_subdir=$7
bazel_output_user_root_subdir=$8
bazelisk_home_subdir=$9

for required_command in getent install; do
  command -v "$required_command" >/dev/null 2>&1 || {
    printf "fatal: required DevOps target command is unavailable: %s\n" "$required_command" >&2
    exit 1
  }
done
getent group devops >/dev/null 2>&1 || {
  printf "fatal: required target group is missing: devops\n" >&2
  exit 1
}

for runtime_path in \
  "$build_root/$account_user" \
  "$build_root/$account_user/cargo" \
  "$build_root/$account_user/cargo/target" \
  "$build_root/$account_user/cargo/install" \
  "$build_root/$account_user/deno" \
  "$build_root/$account_user/deno/bin" \
  "$build_root/$account_user/go" \
  "$build_root/$account_user/go/bin" \
  "$build_root/$account_user/npm-global" \
  "$build_root/$account_user/pnpm" \
  "$build_root/$account_user/pnpm/bin" \
  "$build_root/$account_user/pnpm/global" \
  "$build_root/$account_user/python" \
  "$build_root/$account_user/python/bin" \
  "$build_root/$account_user/uv" \
  "$build_root/$account_user/uv/bin" \
  "$build_root/$account_user/yarn-global" \
  "$build_root/$account_user/$bazel_output_user_root_subdir" \
  "$cache_root/$account_user" \
  "$cache_root/$account_user/cargo" \
  "$cache_root/$account_user/deno" \
  "$cache_root/$account_user/mise" \
  "$cache_root/$account_user/mise/tmp" \
  "$cache_root/$account_user/npm" \
  "$cache_root/$account_user/corepack" \
  "$cache_root/$account_user/go-mod" \
  "$cache_root/$account_user/pnpm" \
  "$cache_root/$account_user/pnpm/cache" \
  "$cache_root/$account_user/pnpm/store" \
  "$cache_root/$account_user/pip" \
  "$cache_root/$account_user/ansible" \
  "$cache_root/$account_user/ansible/galaxy" \
  "$cache_root/$account_user/hashicorp" \
  "$cache_root/$account_user/hashicorp/packer" \
  "$cache_root/$account_user/hashicorp/packer/cache" \
  "$cache_root/$account_user/hashicorp/packer.d" \
  "$cache_root/$account_user/hashicorp/packer.d/plugins" \
  "$cache_root/$account_user/hashicorp/terraform" \
  "$cache_root/$account_user/hashicorp/terraform/plugin-cache" \
  "$cache_root/$account_user/sccache" \
  "$cache_root/$account_user/uv" \
  "$cache_root/$account_user/yarn" \
  "$cache_root/$account_user/$bazel_cache_subdir" \
  "$cache_root/$account_user/$bazel_cache_subdir/$bazel_disk_cache_subdir" \
  "$cache_root/$account_user/$bazel_cache_subdir/$bazel_repository_cache_subdir" \
  "$db_root/$account_user" \
  "$db_root/$account_user/ansible" \
  "$db_root/$account_user/deno" \
  "$db_root/$account_user/mise" \
  "$db_root/$account_user/mise/data" \
  "$db_root/$account_user/mise/state" \
  "$db_root/$account_user/node" \
  "$db_root/$account_user/pnpm" \
  "$db_root/$account_user/pnpm/state" \
  "$db_root/$account_user/python" \
  "$db_root/$account_user/rustup" \
  "$db_root/$account_user/uv" \
  "$db_root/$account_user/uv/tools" \
  "$db_root/$account_user/$bazelisk_home_subdir"
do
  install -d -m 2770 -o "$account_user" -g devops -- "$runtime_path"
done
' sh \
  "$ACCOUNT_USERNAME" \
  "$DIR_POOL_BUILD" \
  "$DIR_POOL_CACHE" \
  "$DIR_POOL_DB" \
  "$DEVOPS_BAZEL_CACHE_SUBDIR" \
  "$DEVOPS_BAZEL_DISK_CACHE_SUBDIR" \
  "$DEVOPS_BAZEL_REPOSITORY_CACHE_SUBDIR" \
  "$DEVOPS_BAZEL_OUTPUT_USER_ROOT_SUBDIR" \
  "$DEVOPS_BAZELISK_HOME_SUBDIR"

install -d -m 0700 "$tmp_env_dir"
devops_prepare_publishing_layout
devops_render_aptly_config
devops_import_aptly_signing_key
devops_render_osc_config
devops_stage_publishing_entrypoints
devops_stage_pending_credentials
unset \
  DEVOPS_CF_R2_ACCESS_KEY \
  DEVOPS_CF_R2_SECRET_KEY \
  DEVOPS_OBS_USERNAME \
  DEVOPS_OBS_PASSWORD
devops_codex_archive_helper_path="${DEVOPS_CODEX_ROOT}/.installer-codex-archive.py"
devops_render_codex_sysctl
devops_render_codex_tmpfiles
devops_render_codex_logrotate
devops_prepare_codex_layout
devops_stage_target_asset \
  "$(installer_repo_join_var DIR_HOOKS_TARGET data/codex/lib/codex)" \
  "$DEVOPS_CODEX_WRAPPER_PATH" \
  0755 \
  codex-wrapper
chown root:root "${target_root}${DEVOPS_CODEX_WRAPPER_PATH}"
devops_stage_target_asset \
  "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/bin/codex-standalone-install)" \
  "$DEVOPS_CODEX_STANDALONE_INSTALLER_HELPER" \
  0755 \
  codex-standalone-installer
chown root:root "${target_root}${DEVOPS_CODEX_STANDALONE_INSTALLER_HELPER}"
devops_stage_target_asset \
  "$(installer_repo_join_var DIR_SCRIPTS_LATE codex-installer-session.py)" \
  "$DEVOPS_CODEX_INSTALLER_SESSION_HELPER" \
  0700 \
  codex-installer-session
chown root:root "${target_root}${DEVOPS_CODEX_INSTALLER_SESSION_HELPER}"
devops_stage_target_asset \
  "$(installer_repo_join_var DIR_SCRIPTS_LATE codex-archive.py)" \
  "$devops_codex_archive_helper_path" \
  0700 \
  codex-archive-helper
chown root:root "${target_root}${devops_codex_archive_helper_path}"
devops_stage_target_asset \
  "$(installer_repo_join_var DIR_SCRIPTS_LATE codex-state.py)" \
  "${DEVOPS_CODEX_ROOT}/.installer-codex-state.py" \
  0700 \
  codex-state-verifier
chown root:root "${target_root}${DEVOPS_CODEX_ROOT}/.installer-codex-state.py"
devops_install_pinned_codex
devops_apply_codex_tmpfiles
devops_stage_codex_app_server
devops_render_bazelrc
devops_render_cargo_config
devops_render_packer_template
devops_write_packer_config

devops_install_pinned_node_runtimes
devops_install_upstream_tools
devops_initialize_packer_plugins
devops_initialize_aptly_repositories
devops_install_pinned_rustup
devops_install_pinned_bazelisk
devops_install_llama_runtime
codex_binary_dir_host="${target_root}${DEVOPS_CODEX_ROOT}/share/bin"
codex_first_binary=$(find "$codex_binary_dir_host" \
  -mindepth 1 -maxdepth 1 -type f -links 1 -print)
[ -n "$codex_first_binary" ] ||
  devops_fatal "managed Codex binary directory is empty after installation"
[ -x "${target_root}${DEVOPS_CODEX_BINARY_PATH}" ] ||
  devops_fatal "managed Codex entrypoint is missing after installation"
codex_unsafe_binary=$(find "$codex_binary_dir_host" \
  -mindepth 1 -maxdepth 1 \( ! -type f -o -type l -o ! -links 1 \) -print)
[ -z "$codex_unsafe_binary" ] ||
  devops_fatal "managed Codex binary directory contains an unsafe entry"
unset codex_binary_dir_host codex_first_binary codex_unsafe_binary
[ -r "${target_root}${DEVOPS_CODEX_SCHEMA_PATH}" ] ||
  devops_fatal "pinned Codex configuration schema is missing after installation"
[ -x "${target_root}${DEVOPS_CODEX_WRAPPER_PATH}" ] ||
  devops_fatal "managed Codex wrapper is missing after installation"
[ -f "${target_root}${DEVOPS_CODEX_STANDALONE_INSTALLER_HELPER}" ] &&
  [ ! -L "${target_root}${DEVOPS_CODEX_STANDALONE_INSTALLER_HELPER}" ] &&
  [ -x "${target_root}${DEVOPS_CODEX_STANDALONE_INSTALLER_HELPER}" ] ||
  devops_fatal "target Codex standalone installer is missing or unsafe"
[ "$(chroot "$target_root" /usr/bin/stat -c '%u:%g:%a' -- "${DEVOPS_CODEX_STANDALONE_INSTALLER_HELPER}")" = 0:0:755 ] ||
  devops_fatal "target Codex standalone installer ownership or mode is invalid"
[ -f "${target_root}${DEVOPS_CODEX_INSTALLER_SESSION_HELPER}" ] &&
  [ ! -L "${target_root}${DEVOPS_CODEX_INSTALLER_SESSION_HELPER}" ] &&
  [ -x "${target_root}${DEVOPS_CODEX_INSTALLER_SESSION_HELPER}" ] ||
  devops_fatal "temporary Codex installer supervisor is missing or unsafe"
[ "$(chroot "$target_root" /usr/bin/stat -c '%u:%g:%a' -- "${DEVOPS_CODEX_INSTALLER_SESSION_HELPER}")" = 0:0:700 ] ||
  devops_fatal "temporary Codex installer supervisor ownership or mode is invalid"
[ -r "${target_root}${DEVOPS_CODEX_APP_SERVER_ENVIRONMENT}" ] ||
  devops_fatal "Codex app-server environment policy is missing after installation"
[ -r "${target_root}${DEVOPS_CODEX_APP_SERVER_USER_UNIT}" ] ||
  devops_fatal "Codex app-server user unit is missing after installation"
[ -L "${target_root}${DEVOPS_CODEX_APP_SERVER_USER_WANTS}" ] &&
  [ "$(readlink -- "${target_root}${DEVOPS_CODEX_APP_SERVER_USER_WANTS}")" = ../codex-app-server.service ] ||
  devops_fatal "Codex app-server user unit is not enabled for the account default target"
[ ! -e "${target_root}${devops_codex_archive_helper_path}" ] &&
  [ ! -L "${target_root}${devops_codex_archive_helper_path}" ] ||
  devops_fatal "temporary Codex archive helper remains after installation"
[ -d "${target_root}${DEVOPS_CODEX_USER_ROOT}/.git" ] ||
  devops_fatal "cloned Codex home repository metadata is missing after installation"
[ -d "${target_root}${DEVOPS_CODEX_SYSTEM_CONFIG_DIR}" ] ||
  devops_fatal "Codex system configuration directory is missing after installation"
[ -r "${target_root}/etc/sysctl.d/90-codex-bwrap.conf" ] ||
  devops_fatal "Codex Bubblewrap user-namespace sysctl policy is missing after installation"
[ -r "${target_root}/etc/tmpfiles.d/80-codex-storage.conf" ] ||
  devops_fatal "Codex ownership tmpfiles policy is missing after installation"
[ -r "${target_root}/etc/logrotate.d/managed-codex" ] ||
  devops_fatal "Codex log rotation policy is missing after installation"
[ -f "${target_root}${DEVOPS_CODEX_HOME}/memories/.git" ] &&
  [ ! -L "${target_root}${DEVOPS_CODEX_HOME}/memories/.git" ] ||
  devops_fatal "Codex memories .git guard is missing after installation"
[ -x "${target_root}${DEVOPS_RUSTUP_BINARY_PATH}" ] ||
  devops_fatal "Rustup bootstrap is missing after installation"
[ -x "${target_root}${DEVOPS_BAZELISK_BINARY_PATH}" ] ||
  devops_fatal "pinned Bazelisk binary is missing after installation: ${DEVOPS_BAZELISK_BINARY_PATH}"
[ -x "${target_root}${DEVOPS_DENO_BINARY_PATH}" ] ||
  devops_fatal "Deno upstream executable is missing after installation"
[ -x "${target_root}${DEVOPS_YT_DLP_BINARY_PATH}" ] ||
  devops_fatal "managed yt-dlp wrapper is missing after installation"
[ -x "${target_root}${DEVOPS_YT_DLP_PAYLOAD_PATH}" ] ||
  devops_fatal "yt-dlp standalone payload with bundled yt-dlp-ejs is missing after installation"
[ -r "${target_root}/etc/skel/.config/bazel/bazelrc" ] ||
  devops_fatal "managed Bazel rc is missing from the desktop skeleton"
[ -x "${target_root}${DEVOPS_ANSIBLE_CORE_BINARY_PATH}" ] ||
  devops_fatal "Ansible upstream executable is missing after installation"
[ -x "${target_root}${DEVOPS_OPENTOFU_BINARY_PATH}" ] ||
  devops_fatal "OpenTofu upstream executable is missing after installation"
[ -x "${target_root}${DEVOPS_TERRAFORM_BINARY_PATH}" ] ||
  devops_fatal "Terraform upstream executable is missing after installation"
[ -x "${target_root}${DEVOPS_PACKER_BINARY_PATH}" ] ||
  devops_fatal "Packer upstream executable is missing after installation"
[ -r "${target_root}/etc/skel/.config/packer/template.pkr.hcl" ] ||
  devops_fatal "managed Packer template is missing from the desktop skeleton"
[ -r "${target_root}${ACCOUNT_HOME}/.config/packer/template.pkr.hcl" ] ||
  devops_fatal "managed Packer template is missing from the primary account"
[ -r "${target_root}${PACKER_CONFIG_PATH}" ] ||
  devops_fatal "managed Packer JSON config is missing after installation"
[ -x "${target_root}${DEVOPS_WRANGLER_BINARY_PATH}" ] ||
  devops_fatal "Wrangler upstream executable is missing after installation"
[ -x "${target_root}${DEVOPS_APTLY_BINARY_PATH}" ] ||
  devops_fatal "Aptly upstream executable is missing after installation"
[ -x "${target_root}${DEVOPS_OSC_BINARY_PATH}" ] ||
  devops_fatal "osc upstream executable is missing after installation"
# The pinned obs-build Makefile publishes bin/build as an absolute symlink
# below DEVOPS_OBS_BUILD_INSTALL_ROOT.  Validate primary-account access inside
# the target; an outer /target check resolves that link against the installer.
devops_run_as_account \
  "verify primary-account access to obs-build after installation" \
  /usr/bin/test -x "$DEVOPS_OBS_BUILD_BINARY_PATH"
[ ! -e "${target_root}/tmp/installer-devops-tools.py" ] &&
  [ ! -L "${target_root}/tmp/installer-devops-tools.py" ] ||
  devops_fatal "temporary upstream DevOps tool installer remains after installation"
[ ! -e "${target_root}/tmp/installer-devops-tools-policy.json" ] &&
  [ ! -L "${target_root}/tmp/installer-devops-tools-policy.json" ] ||
  devops_fatal "temporary upstream DevOps tool policy remains after installation"
[ -r "${target_root}${APTLY_CONFIG}" ] ||
  devops_fatal "managed Aptly config is missing after installation"
[ -r "${target_root}${OSC_CONFIG}" ] ||
  devops_fatal "managed osc config is missing after installation"
[ -r "${target_root}${OSC_MANAGED_CONFIG}" ] ||
  devops_fatal "managed osc metadata is missing after installation"
[ -x "${target_root}/usr/local/libexec/aptly-publishing" ] ||
  devops_fatal "managed Aptly publication wrapper is missing after installation"
[ -x "${target_root}/usr/local/libexec/obs-publishing" ] ||
  devops_fatal "managed OBS publication wrapper is missing after installation"
for aptly_publishing_command in \
  aptly \
  aptly-publish-local \
  dpkg-buildpackage
do
  publishing_link="${target_root}/usr/local/libexec/aptly-publishing-bin/${aptly_publishing_command}"
  [ -L "$publishing_link" ] &&
    [ "$(readlink "$publishing_link")" = ../aptly-publishing ] ||
    devops_fatal "managed Aptly publication command link is invalid: ${aptly_publishing_command}"
done
for obs_publishing_command in \
  obs-checkout-source \
  obs-publish-source \
  osc
do
  publishing_link="${target_root}/usr/local/libexec/obs-publishing-bin/${obs_publishing_command}"
  [ -L "$publishing_link" ] &&
    [ "$(readlink "$publishing_link")" = ../obs-publishing ] ||
    devops_fatal "managed OBS publication command link is invalid: ${obs_publishing_command}"
done
unset aptly_publishing_command obs_publishing_command publishing_link

devops_run_as_account \
  "initialize pinned Rustup with the profile-selected toolchain without changing shell startup files" \
  /usr/bin/timeout \
    --signal=TERM \
    --kill-after=30s \
    1200s \
    "$DEVOPS_RUSTUP_BINARY_PATH" \
      -y \
      --no-modify-path \
      --default-toolchain \
      "$DEVOPS_RUSTUP_TOOLCHAIN" \
      --profile \
      minimal
devops_install_pinned_rust_cli_binaries
# shellcheck disable=SC2016
devops_run_as_account \
  "install rustfmt and source-selected pinned Rust CLI tools" \
  /bin/sh -eu -c '
dotslash_source_build=$1
dotslash_version=$2
dotslash_commit=$3
dotslash_repository_url=$4
uv_source_build=$5
uv_version=$6

for tool_version in "$dotslash_version" "$uv_version"; do
  printf "%s\n" "$tool_version" |
    grep -Eq "^[0-9]+\.[0-9]+\.[0-9]+$" || {
    printf "fatal: Rust CLI tool version is malformed\n" >&2
    exit 1
  }
done
unset tool_version
for source_build_flag in "$dotslash_source_build" "$uv_source_build"; do
  case "$source_build_flag" in
    0|1) ;;
    *)
      printf "fatal: Rust CLI source-build flag must be 0 or 1\n" >&2
      exit 1
      ;;
  esac
done
unset source_build_flag
[ "${#dotslash_commit}" -eq 40 ] &&
  ! printf "%s\n" "$dotslash_commit" | grep -q "[^0-9a-f]" || {
    printf "fatal: DotSlash commit is malformed\n" >&2
    exit 1
  }
case "$dotslash_repository_url" in
  https://github.com/*) ;;
  *)
    printf "fatal: DotSlash repository URL is not HTTPS GitHub\n" >&2
    exit 1
    ;;
esac

for required_command in cargo rustup; do
  command -v "$required_command" >/dev/null 2>&1 || {
    printf "fatal: required Rust tool command is unavailable: %s\n" "$required_command" >&2
    exit 1
  }
done
[ -x /usr/bin/timeout ] || {
  printf "fatal: required Rust tool command is unavailable: /usr/bin/timeout\n" >&2
  exit 1
}

/usr/bin/timeout \
  --signal=TERM \
  --kill-after=30s \
  1200s \
  rustup component add rustfmt

if [ "$dotslash_source_build" = 1 ]; then
  CARGO_NET_RETRY=3 \
    /usr/bin/timeout \
      --signal=TERM \
      --kill-after=30s \
      3600s \
      cargo install \
        --locked \
        --root "$CARGO_INSTALL_ROOT" \
        --git "$dotslash_repository_url" \
        --rev "$dotslash_commit" \
        dotslash
fi

if [ "$uv_source_build" = 1 ]; then
  CARGO_NET_RETRY=3 \
    /usr/bin/timeout \
      --signal=TERM \
      --kill-after=30s \
      7200s \
      cargo install \
        --locked \
        --root "$CARGO_INSTALL_ROOT" \
        --version "$uv_version" \
        uv
fi
' sh \
  "$DEVOPS_DOTSLASH_SOURCE_BUILD" \
  "$DEVOPS_DOTSLASH_VERSION" \
  "$DEVOPS_DOTSLASH_COMMIT" \
  "$DEVOPS_DOTSLASH_REPOSITORY_URL" \
  "$DEVOPS_UV_SOURCE_BUILD" \
  "$DEVOPS_UV_VERSION"
# shellcheck disable=SC2016
devops_run_as_account "verify Rustup, rustfmt, Cargo tools, and sccache" /bin/sh -eu -c '
expected_rustc_wrapper=$1
expected_target_triple=$2
expected_target_linker=$3
expected_target_cpu=$4
expected_linker_argument=$5
expected_dotslash_version=$6
expected_uv_version=$7
expected_rustup_binary=$8
expected_rustup_toolchain=$9
node_22_root=${10}
node_24_root=${11}
node_26_root=${12}

command -v rustup >/dev/null 2>&1
command -v cargo >/dev/null 2>&1
command -v rustc >/dev/null 2>&1
command -v rustfmt >/dev/null 2>&1
command -v dotslash >/dev/null 2>&1
command -v uv >/dev/null 2>&1
command -v uvx >/dev/null 2>&1
command -v sccache >/dev/null 2>&1
command -v mold >/dev/null 2>&1
test -x /usr/bin/clang-24
for llvm_binary in \
  /usr/lib/llvm-24/bin/clang \
  /usr/lib/llvm-24/bin/clang++ \
  /usr/lib/llvm-24/bin/llvm-config \
  /usr/lib/llvm-24/bin/lld \
  /usr/lib/llvm-24/bin/ld.lld \
  /usr/lib/llvm-24/bin/lldb
do
  test -x "$llvm_binary"
done
test -r "$CARGO_HOME/config.toml"
test -x "$expected_rustup_binary"
for node_root in "$node_22_root" "$node_24_root" "$node_26_root"; do
  test -x "${node_root}/bin/corepack"
  test -x "${node_root}/bin/pnpm"
  test -x "${node_root}/bin/yarn"
done
rustup show active-toolchain >/dev/null
rustup show active-toolchain | grep -Fq -- "$expected_rustup_toolchain"
rustup component list --installed | grep -Eq "^rustfmt-"
cargo --version >/dev/null
rustc --version >/dev/null
rustfmt --version >/dev/null
dotslash --version | grep -Fq "$expected_dotslash_version"
uv --version | grep -Fq "$expected_uv_version"
uvx --version | grep -Fq "$expected_uv_version"
sccache --version >/dev/null
rustc --print target-cpus |
  LC_ALL=C awk -v wanted="$expected_target_cpu" \
    '\''$1 == wanted { found = 1 } END { exit found ? 0 : 1 }'\''
grep -Fqx "rustc-wrapper = \"${expected_rustc_wrapper}\"" "$CARGO_HOME/config.toml"
grep -Fqx "[target.\"${expected_target_triple}\"]" "$CARGO_HOME/config.toml"
grep -Fqx "linker = \"${expected_target_linker}\"" "$CARGO_HOME/config.toml"
grep -Fqx "  \"target-cpu=${expected_target_cpu}\"," "$CARGO_HOME/config.toml"
grep -Fqx "  \"link-arg=${expected_linker_argument}\"," "$CARGO_HOME/config.toml"
' sh \
  "$DEVOPS_CARGO_RUSTC_WRAPPER" \
  "$DEVOPS_CARGO_TARGET_TRIPLE" \
  "$DEVOPS_CARGO_TARGET_LINKER" \
  "$DEVOPS_CARGO_TARGET_CPU" \
  "$DEVOPS_CARGO_LINKER_ARGUMENT" \
  "$DEVOPS_DOTSLASH_VERSION" \
  "$DEVOPS_UV_VERSION" \
  "$DEVOPS_RUSTUP_BINARY_PATH" \
  "$DEVOPS_RUSTUP_TOOLCHAIN" \
  "$DEVOPS_NODE_22_INSTALL_ROOT" \
  "$DEVOPS_NODE_24_INSTALL_ROOT" \
  "$DEVOPS_NODE_26_INSTALL_ROOT"

# shellcheck disable=SC2016
devops_run_as_account "link preinstalled Node runtimes into Mise" /bin/sh -eu -c '
command -v mise >/dev/null 2>&1
for mise_directory in \
  "$MISE_CONFIG_DIR" \
  "$MISE_DATA_DIR" \
  "$MISE_STATE_DIR" \
  "$MISE_CACHE_DIR" \
  "$MISE_TMP_DIR"
do
  [ -d "$mise_directory" ] && [ ! -L "$mise_directory" ] || {
    printf "fatal: managed Mise directory is unavailable or unsafe: %s\n" "$mise_directory" >&2
    exit 1
  }
done
while [ "$#" -gt 0 ]; do
  node_version=$1
  node_root=$2
  shift 2
  test -x "${node_root}/bin/node"
  mise link --force "node@${node_version}" "$node_root"
done
mise reshim
' sh \
  "$DEVOPS_NODE_22_MAJOR" "$DEVOPS_NODE_22_INSTALL_ROOT" \
  "$DEVOPS_NODE_24_MAJOR" "$DEVOPS_NODE_24_INSTALL_ROOT" \
  "$DEVOPS_NODE_26_MAJOR" "$DEVOPS_NODE_26_INSTALL_ROOT"

  devops_info \
  "configured desktop toolchains account=${ACCOUNT_USERNAME} codex=${DEVOPS_CODEX_VERSION} sandbox=bubblewrap+slirp4netns llama_release=${LLAMA_RELEASE_ARCHIVE_ROOT} node=${DEVOPS_NODE_22_MAJOR},${DEVOPS_NODE_24_MAJOR},${DEVOPS_NODE_26_MAJOR} via Mise Corepack=enabled deno=${DEVOPS_DENO_VERSION} yt-dlp=${DEVOPS_YT_DLP_VERSION}+bundled-yt-dlp-ejs ffmpeg=system rustup=${DEVOPS_RUSTUP_VERSION} toolchain=${DEVOPS_RUSTUP_TOOLCHAIN} rustfmt=enabled dotslash=${DEVOPS_DOTSLASH_VERSION}@${DEVOPS_DOTSLASH_COMMIT}:source-build=${DEVOPS_DOTSLASH_SOURCE_BUILD} uv=${DEVOPS_UV_VERSION}:source-build=${DEVOPS_UV_SOURCE_BUILD} cargo_target_cpu=${DEVOPS_CARGO_TARGET_CPU} cargo_jobs=cargo-default llvm=24 direct bazelisk=${DEVOPS_BAZELISK_VERSION} ansible-core=${DEVOPS_ANSIBLE_CORE_VERSION} opentofu=${DEVOPS_OPENTOFU_VERSION} terraform=${DEVOPS_TERRAFORM_VERSION} packer=${DEVOPS_PACKER_VERSION} wrangler=${DEVOPS_WRANGLER_VERSION} aptly=${DEVOPS_APTLY_RELEASE_VERSION} osc=${DEVOPS_OSC_RELEASE_VERSION} obs-build=${DEVOPS_OBS_BUILD_TAG} publication=stable,testing:r2+home:cramerz:debian"
