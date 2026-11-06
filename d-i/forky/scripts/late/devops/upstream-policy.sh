#!/bin/sh
# Sourced installer module; edit this file directly.

devops_validate_configured_release_url() {
  label=$1
  url=$2
  filename=$3
  case "$filename" in
    ''|*/*|*..*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-]*)
      devops_fatal "${label} release filename is malformed"
      ;;
  esac
  case "$url" in
    https://*/"$filename") ;;
    *) devops_fatal "${label} URL does not end at its configured release filename" ;;
  esac
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
  : "${DEVOPS_NODE_22_MINIMUM_BYTES:?DEVOPS_NODE_22_MINIMUM_BYTES must be set before DevOps provisioning}"
  : "${DEVOPS_NODE_22_MAXIMUM_BYTES:?DEVOPS_NODE_22_MAXIMUM_BYTES must be set before DevOps provisioning}"
  : "${DEVOPS_NODE_22_ARCHIVE_FILENAME:?DEVOPS_NODE_22_ARCHIVE_FILENAME must be set before DevOps provisioning}"
  : "${DEVOPS_NODE_22_ARCHIVE_ROOT:?DEVOPS_NODE_22_ARCHIVE_ROOT must be set before DevOps provisioning}"
  : "${DEVOPS_NODE_22_INSTALL_ROOT:?DEVOPS_NODE_22_INSTALL_ROOT must be set before DevOps provisioning}"
  : "${DEVOPS_NODE_22_BINARY_PATH:?DEVOPS_NODE_22_BINARY_PATH must be set before DevOps provisioning}"
  : "${DEVOPS_NODE_24_MAJOR:?DEVOPS_NODE_24_MAJOR must be set before DevOps provisioning}"
  : "${DEVOPS_NODE_24_VERSION:?DEVOPS_NODE_24_VERSION must be set before DevOps provisioning}"
  : "${DEVOPS_NODE_24_URL:?DEVOPS_NODE_24_URL must be set before DevOps provisioning}"
  : "${DEVOPS_NODE_24_SHA256:?DEVOPS_NODE_24_SHA256 must be set before DevOps provisioning}"
  : "${DEVOPS_NODE_24_MINIMUM_BYTES:?DEVOPS_NODE_24_MINIMUM_BYTES must be set before DevOps provisioning}"
  : "${DEVOPS_NODE_24_MAXIMUM_BYTES:?DEVOPS_NODE_24_MAXIMUM_BYTES must be set before DevOps provisioning}"
  : "${DEVOPS_NODE_24_ARCHIVE_FILENAME:?DEVOPS_NODE_24_ARCHIVE_FILENAME must be set before DevOps provisioning}"
  : "${DEVOPS_NODE_24_ARCHIVE_ROOT:?DEVOPS_NODE_24_ARCHIVE_ROOT must be set before DevOps provisioning}"
  : "${DEVOPS_NODE_24_INSTALL_ROOT:?DEVOPS_NODE_24_INSTALL_ROOT must be set before DevOps provisioning}"
  : "${DEVOPS_NODE_24_BINARY_PATH:?DEVOPS_NODE_24_BINARY_PATH must be set before DevOps provisioning}"
  : "${DEVOPS_NODE_26_MAJOR:?DEVOPS_NODE_26_MAJOR must be set before DevOps provisioning}"
  : "${DEVOPS_NODE_26_VERSION:?DEVOPS_NODE_26_VERSION must be set before DevOps provisioning}"
  : "${DEVOPS_NODE_26_URL:?DEVOPS_NODE_26_URL must be set before DevOps provisioning}"
  : "${DEVOPS_NODE_26_SHA256:?DEVOPS_NODE_26_SHA256 must be set before DevOps provisioning}"
  : "${DEVOPS_NODE_26_MINIMUM_BYTES:?DEVOPS_NODE_26_MINIMUM_BYTES must be set before DevOps provisioning}"
  : "${DEVOPS_NODE_26_MAXIMUM_BYTES:?DEVOPS_NODE_26_MAXIMUM_BYTES must be set before DevOps provisioning}"
  : "${DEVOPS_NODE_26_ARCHIVE_FILENAME:?DEVOPS_NODE_26_ARCHIVE_FILENAME must be set before DevOps provisioning}"
  : "${DEVOPS_NODE_26_ARCHIVE_ROOT:?DEVOPS_NODE_26_ARCHIVE_ROOT must be set before DevOps provisioning}"
  : "${DEVOPS_NODE_26_INSTALL_ROOT:?DEVOPS_NODE_26_INSTALL_ROOT must be set before DevOps provisioning}"
  : "${DEVOPS_NODE_26_BINARY_PATH:?DEVOPS_NODE_26_BINARY_PATH must be set before DevOps provisioning}"

  : "${DEVOPS_DENO_VERSION:?DEVOPS_DENO_VERSION must be set before DevOps provisioning}"
  : "${DEVOPS_DENO_URL:?DEVOPS_DENO_URL must be set before DevOps provisioning}"
  : "${DEVOPS_DENO_SHA256:?DEVOPS_DENO_SHA256 must be set before DevOps provisioning}"
  : "${DEVOPS_DENO_MINIMUM_BYTES:?DEVOPS_DENO_MINIMUM_BYTES must be set before DevOps provisioning}"
  : "${DEVOPS_DENO_ARCHITECTURE:?DEVOPS_DENO_ARCHITECTURE must be set before DevOps provisioning}"
  : "${DEVOPS_DENO_ARCHIVE_FILENAME:?DEVOPS_DENO_ARCHIVE_FILENAME must be set before DevOps provisioning}"
  : "${DEVOPS_DENO_ARCHIVE_FILES:?DEVOPS_DENO_ARCHIVE_FILES must be set before DevOps provisioning}"
  : "${DEVOPS_DENO_INSTALL_ROOT:?DEVOPS_DENO_INSTALL_ROOT must be set before DevOps provisioning}"
  : "${DEVOPS_DENO_BINARY_PATH:?DEVOPS_DENO_BINARY_PATH must be set before DevOps provisioning}"

  : "${DEVOPS_YT_DLP_VERSION:?DEVOPS_YT_DLP_VERSION must be set before DevOps provisioning}"
  : "${DEVOPS_YT_DLP_URL:?DEVOPS_YT_DLP_URL must be set before DevOps provisioning}"
  : "${DEVOPS_YT_DLP_SHA256:?DEVOPS_YT_DLP_SHA256 must be set before DevOps provisioning}"
  : "${DEVOPS_YT_DLP_MINIMUM_BYTES:?DEVOPS_YT_DLP_MINIMUM_BYTES must be set before DevOps provisioning}"
  : "${DEVOPS_YT_DLP_ARCHITECTURE:?DEVOPS_YT_DLP_ARCHITECTURE must be set before DevOps provisioning}"
  : "${DEVOPS_YT_DLP_ARCHIVE_FILENAME:?DEVOPS_YT_DLP_ARCHIVE_FILENAME must be set before DevOps provisioning}"
  : "${DEVOPS_YT_DLP_INSTALL_ROOT:?DEVOPS_YT_DLP_INSTALL_ROOT must be set before DevOps provisioning}"
  : "${DEVOPS_YT_DLP_BINARY_PATH:?DEVOPS_YT_DLP_BINARY_PATH must be set before DevOps provisioning}"
  : "${DEVOPS_YT_DLP_PAYLOAD_PATH:?DEVOPS_YT_DLP_PAYLOAD_PATH must be set before DevOps provisioning}"
  : "${DEVOPS_YT_DLP_EJS_VERSION:?DEVOPS_YT_DLP_EJS_VERSION must be set before DevOps provisioning}"

  : "${DEVOPS_RUSTUP_VERSION:?DEVOPS_RUSTUP_VERSION must be set before DevOps provisioning}"
  : "${DEVOPS_RUSTUP_URL:?DEVOPS_RUSTUP_URL must be set before DevOps provisioning}"
  : "${DEVOPS_RUSTUP_SHA256:?DEVOPS_RUSTUP_SHA256 must be set before DevOps provisioning}"
  : "${DEVOPS_RUSTUP_MINIMUM_BYTES:?DEVOPS_RUSTUP_MINIMUM_BYTES must be set before DevOps provisioning}"
  : "${DEVOPS_RUSTUP_MAXIMUM_BYTES:?DEVOPS_RUSTUP_MAXIMUM_BYTES must be set before DevOps provisioning}"
  : "${DEVOPS_RUSTUP_TARGET_TRIPLE:?DEVOPS_RUSTUP_TARGET_TRIPLE must be set before DevOps provisioning}"
  : "${DEVOPS_RUSTUP_INSTALL_ROOT:?DEVOPS_RUSTUP_INSTALL_ROOT must be set before DevOps provisioning}"
  : "${DEVOPS_RUSTUP_BINARY_PATH:?DEVOPS_RUSTUP_BINARY_PATH must be set before DevOps provisioning}"
  : "${DEVOPS_RUSTUP_TOOLCHAIN:?DEVOPS_RUSTUP_TOOLCHAIN must be set before DevOps provisioning}"
  : "${DEVOPS_CARGO_BINSTALL_VERSION:?DEVOPS_CARGO_BINSTALL_VERSION must be set before DevOps provisioning}"
  : "${DEVOPS_CARGO_BINSTALL_URL:?DEVOPS_CARGO_BINSTALL_URL must be set before DevOps provisioning}"
  : "${DEVOPS_CARGO_BINSTALL_SHA256:?DEVOPS_CARGO_BINSTALL_SHA256 must be set before DevOps provisioning}"
  : "${DEVOPS_CARGO_BINSTALL_MINIMUM_BYTES:?DEVOPS_CARGO_BINSTALL_MINIMUM_BYTES must be set before DevOps provisioning}"
  : "${DEVOPS_CARGO_BINSTALL_ARCHITECTURE:?DEVOPS_CARGO_BINSTALL_ARCHITECTURE must be set before DevOps provisioning}"
  : "${DEVOPS_CARGO_BINSTALL_ARCHIVE_FILENAME:?DEVOPS_CARGO_BINSTALL_ARCHIVE_FILENAME must be set before DevOps provisioning}"
  : "${DEVOPS_CARGO_BINSTALL_ARCHIVE_FILES:?DEVOPS_CARGO_BINSTALL_ARCHIVE_FILES must be set before DevOps provisioning}"
  : "${DEVOPS_DOTSLASH_SOURCE_BUILD:?DEVOPS_DOTSLASH_SOURCE_BUILD must be set before DevOps provisioning}"
  : "${DEVOPS_DOTSLASH_VERSION:?DEVOPS_DOTSLASH_VERSION must be set before DevOps provisioning}"
  : "${DEVOPS_DOTSLASH_REPOSITORY_URL:?DEVOPS_DOTSLASH_REPOSITORY_URL must be set before DevOps provisioning}"
  : "${DEVOPS_DOTSLASH_COMMIT:?DEVOPS_DOTSLASH_COMMIT must be set before DevOps provisioning}"
  : "${DEVOPS_DOTSLASH_URL:?DEVOPS_DOTSLASH_URL must be set before DevOps provisioning}"
  : "${DEVOPS_DOTSLASH_SHA256:?DEVOPS_DOTSLASH_SHA256 must be set before DevOps provisioning}"
  : "${DEVOPS_DOTSLASH_MINIMUM_BYTES:?DEVOPS_DOTSLASH_MINIMUM_BYTES must be set before DevOps provisioning}"
  : "${DEVOPS_DOTSLASH_ARCHITECTURE:?DEVOPS_DOTSLASH_ARCHITECTURE must be set before DevOps provisioning}"
  : "${DEVOPS_DOTSLASH_ARCHIVE_FILENAME:?DEVOPS_DOTSLASH_ARCHIVE_FILENAME must be set before DevOps provisioning}"
  : "${DEVOPS_DOTSLASH_ARCHIVE_FILES:?DEVOPS_DOTSLASH_ARCHIVE_FILES must be set before DevOps provisioning}"
  : "${DEVOPS_UV_SOURCE_BUILD:?DEVOPS_UV_SOURCE_BUILD must be set before DevOps provisioning}"
  : "${DEVOPS_UV_VERSION:?DEVOPS_UV_VERSION must be set before DevOps provisioning}"
  : "${DEVOPS_UV_URL:?DEVOPS_UV_URL must be set before DevOps provisioning}"
  : "${DEVOPS_UV_SHA256:?DEVOPS_UV_SHA256 must be set before DevOps provisioning}"
  : "${DEVOPS_UV_MINIMUM_BYTES:?DEVOPS_UV_MINIMUM_BYTES must be set before DevOps provisioning}"
  : "${DEVOPS_UV_ARCHITECTURE:?DEVOPS_UV_ARCHITECTURE must be set before DevOps provisioning}"
  : "${DEVOPS_UV_ARCHIVE_FILENAME:?DEVOPS_UV_ARCHIVE_FILENAME must be set before DevOps provisioning}"
  : "${DEVOPS_UV_ARCHIVE_ROOT:?DEVOPS_UV_ARCHIVE_ROOT must be set before DevOps provisioning}"
  : "${DEVOPS_UV_ARCHIVE_FILES:?DEVOPS_UV_ARCHIVE_FILES must be set before DevOps provisioning}"

  : "${DEVOPS_ANSIBLE_CORE_VERSION:?DEVOPS_ANSIBLE_CORE_VERSION must be set before DevOps provisioning}"
  : "${DEVOPS_ANSIBLE_CORE_URL:?DEVOPS_ANSIBLE_CORE_URL must be set before DevOps provisioning}"
  : "${DEVOPS_ANSIBLE_CORE_SHA256:?DEVOPS_ANSIBLE_CORE_SHA256 must be set before DevOps provisioning}"
  : "${DEVOPS_ANSIBLE_CORE_MINIMUM_BYTES:?DEVOPS_ANSIBLE_CORE_MINIMUM_BYTES must be set before DevOps provisioning}"
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
  : "${DEVOPS_OPENTOFU_MINIMUM_BYTES:?DEVOPS_OPENTOFU_MINIMUM_BYTES must be set before DevOps provisioning}"
  : "${DEVOPS_OPENTOFU_ARCHITECTURE:?DEVOPS_OPENTOFU_ARCHITECTURE must be set before DevOps provisioning}"
  : "${DEVOPS_OPENTOFU_ARCHIVE_FILENAME:?DEVOPS_OPENTOFU_ARCHIVE_FILENAME must be set before DevOps provisioning}"
  : "${DEVOPS_OPENTOFU_ARCHIVE_FILES:?DEVOPS_OPENTOFU_ARCHIVE_FILES must be set before DevOps provisioning}"
  : "${DEVOPS_OPENTOFU_INSTALL_ROOT:?DEVOPS_OPENTOFU_INSTALL_ROOT must be set before DevOps provisioning}"
  : "${DEVOPS_OPENTOFU_BINARY_PATH:?DEVOPS_OPENTOFU_BINARY_PATH must be set before DevOps provisioning}"

  : "${DEVOPS_TERRAFORM_VERSION:?DEVOPS_TERRAFORM_VERSION must be set before DevOps provisioning}"
  : "${DEVOPS_TERRAFORM_URL:?DEVOPS_TERRAFORM_URL must be set before DevOps provisioning}"
  : "${DEVOPS_TERRAFORM_SHA256:?DEVOPS_TERRAFORM_SHA256 must be set before DevOps provisioning}"
  : "${DEVOPS_TERRAFORM_MINIMUM_BYTES:?DEVOPS_TERRAFORM_MINIMUM_BYTES must be set before DevOps provisioning}"
  : "${DEVOPS_TERRAFORM_ARCHITECTURE:?DEVOPS_TERRAFORM_ARCHITECTURE must be set before DevOps provisioning}"
  : "${DEVOPS_TERRAFORM_ARCHIVE_FILENAME:?DEVOPS_TERRAFORM_ARCHIVE_FILENAME must be set before DevOps provisioning}"
  : "${DEVOPS_TERRAFORM_ARCHIVE_FILES:?DEVOPS_TERRAFORM_ARCHIVE_FILES must be set before DevOps provisioning}"
  : "${DEVOPS_TERRAFORM_INSTALL_ROOT:?DEVOPS_TERRAFORM_INSTALL_ROOT must be set before DevOps provisioning}"
  : "${DEVOPS_TERRAFORM_BINARY_PATH:?DEVOPS_TERRAFORM_BINARY_PATH must be set before DevOps provisioning}"

  : "${DEVOPS_PACKER_VERSION:?DEVOPS_PACKER_VERSION must be set before DevOps provisioning}"
  : "${DEVOPS_PACKER_URL:?DEVOPS_PACKER_URL must be set before DevOps provisioning}"
  : "${DEVOPS_PACKER_SHA256:?DEVOPS_PACKER_SHA256 must be set before DevOps provisioning}"
  : "${DEVOPS_PACKER_MINIMUM_BYTES:?DEVOPS_PACKER_MINIMUM_BYTES must be set before DevOps provisioning}"
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
  : "${DEVOPS_WRANGLER_MINIMUM_BYTES:?DEVOPS_WRANGLER_MINIMUM_BYTES must be set before DevOps provisioning}"
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
  : "${DEVOPS_APTLY_RELEASE_MINIMUM_BYTES:?DEVOPS_APTLY_RELEASE_MINIMUM_BYTES must be set before DevOps provisioning}"
  : "${DEVOPS_APTLY_RELEASE_ARCHITECTURE:?DEVOPS_APTLY_RELEASE_ARCHITECTURE must be set before DevOps provisioning}"
  : "${DEVOPS_APTLY_RELEASE_ARCHIVE_FILENAME:?DEVOPS_APTLY_RELEASE_ARCHIVE_FILENAME must be set before DevOps provisioning}"
  : "${DEVOPS_APTLY_RELEASE_ARCHIVE_ROOT:?DEVOPS_APTLY_RELEASE_ARCHIVE_ROOT must be set before DevOps provisioning}"
  : "${DEVOPS_APTLY_RELEASE_ARCHIVE_FILES:?DEVOPS_APTLY_RELEASE_ARCHIVE_FILES must be set before DevOps provisioning}"
  : "${DEVOPS_APTLY_INSTALL_ROOT:?DEVOPS_APTLY_INSTALL_ROOT must be set before DevOps provisioning}"
  : "${DEVOPS_APTLY_BINARY_PATH:?DEVOPS_APTLY_BINARY_PATH must be set before DevOps provisioning}"

  : "${DEVOPS_OSC_RELEASE_VERSION:?DEVOPS_OSC_RELEASE_VERSION must be set before DevOps provisioning}"
  : "${DEVOPS_OSC_RELEASE_URL:?DEVOPS_OSC_RELEASE_URL must be set before DevOps provisioning}"
  : "${DEVOPS_OSC_RELEASE_SHA256:?DEVOPS_OSC_RELEASE_SHA256 must be set before DevOps provisioning}"
  : "${DEVOPS_OSC_RELEASE_MINIMUM_BYTES:?DEVOPS_OSC_RELEASE_MINIMUM_BYTES must be set before DevOps provisioning}"
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
  : "${DEVOPS_OBS_BUILD_MINIMUM_BYTES:?DEVOPS_OBS_BUILD_MINIMUM_BYTES must be set before DevOps provisioning}"
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
    "$DEVOPS_NODE_22_SHA256" "$DEVOPS_NODE_22_MINIMUM_BYTES" \
    "$DEVOPS_NODE_22_ARCHIVE_FILENAME" "$DEVOPS_NODE_22_ARCHIVE_ROOT" \
    "$DEVOPS_NODE_22_INSTALL_ROOT" "$DEVOPS_NODE_22_BINARY_PATH"
  devops_validate_node_release 24 \
    "$DEVOPS_NODE_24_MAJOR" "$DEVOPS_NODE_24_VERSION" "$DEVOPS_NODE_24_URL" \
    "$DEVOPS_NODE_24_SHA256" "$DEVOPS_NODE_24_MINIMUM_BYTES" \
    "$DEVOPS_NODE_24_ARCHIVE_FILENAME" "$DEVOPS_NODE_24_ARCHIVE_ROOT" \
    "$DEVOPS_NODE_24_INSTALL_ROOT" "$DEVOPS_NODE_24_BINARY_PATH"
  devops_validate_node_release 26 \
    "$DEVOPS_NODE_26_MAJOR" "$DEVOPS_NODE_26_VERSION" "$DEVOPS_NODE_26_URL" \
    "$DEVOPS_NODE_26_SHA256" "$DEVOPS_NODE_26_MINIMUM_BYTES" \
    "$DEVOPS_NODE_26_ARCHIVE_FILENAME" "$DEVOPS_NODE_26_ARCHIVE_ROOT" \
    "$DEVOPS_NODE_26_INSTALL_ROOT" "$DEVOPS_NODE_26_BINARY_PATH"
  for node_limit in \
    "$DEVOPS_NODE_22_MINIMUM_BYTES" "$DEVOPS_NODE_22_MAXIMUM_BYTES" \
    "$DEVOPS_NODE_24_MINIMUM_BYTES" "$DEVOPS_NODE_24_MAXIMUM_BYTES" \
    "$DEVOPS_NODE_26_MINIMUM_BYTES" "$DEVOPS_NODE_26_MAXIMUM_BYTES"
  do
    devops_validate_positive_integer "Node release byte limit" "$node_limit"
  done
  [ "$DEVOPS_NODE_22_MAXIMUM_BYTES" -ge "$DEVOPS_NODE_22_MINIMUM_BYTES" ] ||
    devops_fatal "DEVOPS_NODE_22_MAXIMUM_BYTES must not be smaller than its minimum"
  [ "$DEVOPS_NODE_24_MAXIMUM_BYTES" -ge "$DEVOPS_NODE_24_MINIMUM_BYTES" ] ||
    devops_fatal "DEVOPS_NODE_24_MAXIMUM_BYTES must not be smaller than its minimum"
  [ "$DEVOPS_NODE_26_MAXIMUM_BYTES" -ge "$DEVOPS_NODE_26_MINIMUM_BYTES" ] ||
    devops_fatal "DEVOPS_NODE_26_MAXIMUM_BYTES must not be smaller than its minimum"

  devops_validate_semantic_version "DEVOPS_DENO_VERSION" "$DEVOPS_DENO_VERSION"
  [ "$DEVOPS_DENO_ARCHITECTURE" = x86_64-unknown-linux-gnu ] ||
    devops_fatal "DEVOPS_DENO_ARCHITECTURE must remain x86_64-unknown-linux-gnu"
  devops_validate_configured_release_url DEVOPS_DENO_URL "$DEVOPS_DENO_URL" "$DEVOPS_DENO_ARCHIVE_FILENAME"
  devops_validate_lower_hex "DEVOPS_DENO_SHA256" "$DEVOPS_DENO_SHA256" 64
  devops_validate_positive_integer "DEVOPS_DENO_MINIMUM_BYTES" "$DEVOPS_DENO_MINIMUM_BYTES"
  [ "$DEVOPS_DENO_ARCHIVE_FILES" = deno ] ||
    devops_fatal "DEVOPS_DENO_ARCHIVE_FILES must contain only deno"
  devops_validate_install_layout \
    "DEVOPS_DENO" \
    "$DEVOPS_DENO_INSTALL_ROOT" \
    "$DEVOPS_DENO_BINARY_PATH"

  devops_validate_semantic_version "DEVOPS_YT_DLP_VERSION" "$DEVOPS_YT_DLP_VERSION"
  [ "$DEVOPS_YT_DLP_ARCHITECTURE" = linux-x86_64 ] ||
    devops_fatal "DEVOPS_YT_DLP_ARCHITECTURE must remain linux-x86_64"
  devops_validate_configured_release_url DEVOPS_YT_DLP_URL "$DEVOPS_YT_DLP_URL" "$DEVOPS_YT_DLP_ARCHIVE_FILENAME"
  devops_validate_lower_hex "DEVOPS_YT_DLP_SHA256" "$DEVOPS_YT_DLP_SHA256" 64
  devops_validate_positive_integer "DEVOPS_YT_DLP_MINIMUM_BYTES" "$DEVOPS_YT_DLP_MINIMUM_BYTES"
  devops_validate_install_layout \
    "DEVOPS_YT_DLP" \
    "$DEVOPS_YT_DLP_INSTALL_ROOT" \
    "$DEVOPS_YT_DLP_BINARY_PATH"
  devops_validate_abs_path "DEVOPS_YT_DLP_PAYLOAD_PATH" "$DEVOPS_YT_DLP_PAYLOAD_PATH"
  case "$DEVOPS_YT_DLP_PAYLOAD_PATH" in
    "$DEVOPS_YT_DLP_INSTALL_ROOT"/*) ;;
    *) devops_fatal "DEVOPS_YT_DLP_PAYLOAD_PATH must be below DEVOPS_YT_DLP_INSTALL_ROOT" ;;
  esac

  devops_validate_semantic_version "DEVOPS_RUSTUP_VERSION" "$DEVOPS_RUSTUP_VERSION"
  [ "$DEVOPS_RUSTUP_TARGET_TRIPLE" = x86_64-unknown-linux-gnu ] ||
    devops_fatal "DEVOPS_RUSTUP_TARGET_TRIPLE must remain x86_64-unknown-linux-gnu"
  rustup_archive_filename=${DEVOPS_RUSTUP_URL##*/}
  devops_validate_configured_release_url \
    DEVOPS_RUSTUP_URL \
    "$DEVOPS_RUSTUP_URL" \
    "$rustup_archive_filename"
  devops_validate_lower_hex "DEVOPS_RUSTUP_SHA256" "$DEVOPS_RUSTUP_SHA256" 64
  devops_validate_positive_integer "DEVOPS_RUSTUP_MINIMUM_BYTES" "$DEVOPS_RUSTUP_MINIMUM_BYTES"
  devops_validate_positive_integer "DEVOPS_RUSTUP_MAXIMUM_BYTES" "$DEVOPS_RUSTUP_MAXIMUM_BYTES"
  [ "$DEVOPS_RUSTUP_MAXIMUM_BYTES" -ge "$DEVOPS_RUSTUP_MINIMUM_BYTES" ] ||
    devops_fatal "DEVOPS_RUSTUP_MAXIMUM_BYTES must not be smaller than its minimum"
  devops_validate_install_layout \
    "DEVOPS_RUSTUP" \
    "$DEVOPS_RUSTUP_INSTALL_ROOT" \
    "$DEVOPS_RUSTUP_BINARY_PATH"
  devops_validate_semantic_version "DEVOPS_CARGO_BINSTALL_VERSION" "$DEVOPS_CARGO_BINSTALL_VERSION"
  [ "$DEVOPS_CARGO_BINSTALL_ARCHITECTURE" = x86_64-unknown-linux-musl ] ||
    devops_fatal "DEVOPS_CARGO_BINSTALL_ARCHITECTURE must remain x86_64-unknown-linux-musl"
  devops_validate_configured_release_url DEVOPS_CARGO_BINSTALL_URL "$DEVOPS_CARGO_BINSTALL_URL" "$DEVOPS_CARGO_BINSTALL_ARCHIVE_FILENAME"
  devops_validate_lower_hex "DEVOPS_CARGO_BINSTALL_SHA256" "$DEVOPS_CARGO_BINSTALL_SHA256" 64
  devops_validate_positive_integer "DEVOPS_CARGO_BINSTALL_MINIMUM_BYTES" "$DEVOPS_CARGO_BINSTALL_MINIMUM_BYTES"
  [ "$DEVOPS_CARGO_BINSTALL_ARCHIVE_FILES" = cargo-binstall ] ||
    devops_fatal "DEVOPS_CARGO_BINSTALL_ARCHIVE_FILES must contain only cargo-binstall"
  devops_validate_source_build_flag "DEVOPS_DOTSLASH_SOURCE_BUILD" "$DEVOPS_DOTSLASH_SOURCE_BUILD"
  devops_validate_semantic_version "DEVOPS_DOTSLASH_VERSION" "$DEVOPS_DOTSLASH_VERSION"
  case "$DEVOPS_DOTSLASH_REPOSITORY_URL" in https://*) ;; *) devops_fatal "DEVOPS_DOTSLASH_REPOSITORY_URL must be HTTPS" ;; esac
  devops_validate_lower_hex "DEVOPS_DOTSLASH_COMMIT" "$DEVOPS_DOTSLASH_COMMIT" 40
  devops_validate_configured_release_url DEVOPS_DOTSLASH_URL "$DEVOPS_DOTSLASH_URL" "$DEVOPS_DOTSLASH_ARCHIVE_FILENAME"
  devops_validate_lower_hex "DEVOPS_DOTSLASH_SHA256" "$DEVOPS_DOTSLASH_SHA256" 64
  devops_validate_positive_integer "DEVOPS_DOTSLASH_MINIMUM_BYTES" "$DEVOPS_DOTSLASH_MINIMUM_BYTES"
  [ "$DEVOPS_DOTSLASH_ARCHITECTURE" = linux-musl.x86_64 ] ||
    devops_fatal "DEVOPS_DOTSLASH_ARCHITECTURE must remain linux-musl.x86_64"
  [ "$DEVOPS_DOTSLASH_ARCHIVE_FILES" = dotslash ] ||
    devops_fatal "DEVOPS_DOTSLASH_ARCHIVE_FILES must contain only dotslash"
  devops_validate_source_build_flag "DEVOPS_UV_SOURCE_BUILD" "$DEVOPS_UV_SOURCE_BUILD"
  devops_validate_semantic_version "DEVOPS_UV_VERSION" "$DEVOPS_UV_VERSION"
  devops_validate_configured_release_url DEVOPS_UV_URL "$DEVOPS_UV_URL" "$DEVOPS_UV_ARCHIVE_FILENAME"
  devops_validate_lower_hex "DEVOPS_UV_SHA256" "$DEVOPS_UV_SHA256" 64
  devops_validate_positive_integer "DEVOPS_UV_MINIMUM_BYTES" "$DEVOPS_UV_MINIMUM_BYTES"
  [ "$DEVOPS_UV_ARCHITECTURE" = x86_64-unknown-linux-gnu ] ||
    devops_fatal "DEVOPS_UV_ARCHITECTURE must remain x86_64-unknown-linux-gnu"
  [ "$DEVOPS_UV_ARCHIVE_FILES" = "uv uvx" ] ||
    devops_fatal "DEVOPS_UV_ARCHIVE_FILES must contain uv and uvx"

  devops_validate_semantic_version "DEVOPS_ANSIBLE_CORE_VERSION" "$DEVOPS_ANSIBLE_CORE_VERSION"
  case "$DEVOPS_ANSIBLE_CORE_URL" in
    https://*/"${DEVOPS_ANSIBLE_CORE_ARCHIVE_FILENAME}") ;;
    *) devops_fatal "DEVOPS_ANSIBLE_CORE_URL must identify an HTTPS wheel" ;;
  esac
  case "$DEVOPS_ANSIBLE_CORE_URL" in
    *..*) devops_fatal "DEVOPS_ANSIBLE_CORE_URL must be normalized" ;;
  esac
  devops_validate_lower_hex "DEVOPS_ANSIBLE_CORE_SHA256" "$DEVOPS_ANSIBLE_CORE_SHA256" 64
  devops_validate_positive_integer "DEVOPS_ANSIBLE_CORE_MINIMUM_BYTES" "$DEVOPS_ANSIBLE_CORE_MINIMUM_BYTES"
  [ "$DEVOPS_ANSIBLE_CORE_ARCHITECTURE" = python3-any ] ||
    devops_fatal "DEVOPS_ANSIBLE_CORE_ARCHITECTURE must remain python3-any"
  [ "$DEVOPS_ANSIBLE_CORE_PACKAGE_ROOTS" = "ansible ansible_test" ] ||
    devops_fatal "DEVOPS_ANSIBLE_CORE_PACKAGE_ROOTS must remain ansible ansible_test"
  [ "$DEVOPS_ANSIBLE_CORE_DIST_INFO_ROOT" = "ansible_core-${DEVOPS_ANSIBLE_CORE_VERSION}.dist-info" ] ||
    devops_fatal "DEVOPS_ANSIBLE_CORE_DIST_INFO_ROOT does not match DEVOPS_ANSIBLE_CORE_VERSION"
  devops_validate_install_layout \
    "DEVOPS_ANSIBLE_CORE" \
    "$DEVOPS_ANSIBLE_CORE_INSTALL_ROOT" \
    "$DEVOPS_ANSIBLE_CORE_BINARY_PATH"

  devops_validate_semantic_version "DEVOPS_OPENTOFU_VERSION" "$DEVOPS_OPENTOFU_VERSION"
  devops_validate_configured_release_url DEVOPS_OPENTOFU_URL "$DEVOPS_OPENTOFU_URL" "$DEVOPS_OPENTOFU_ARCHIVE_FILENAME"
  devops_validate_lower_hex "DEVOPS_OPENTOFU_SHA256" "$DEVOPS_OPENTOFU_SHA256" 64
  devops_validate_positive_integer "DEVOPS_OPENTOFU_MINIMUM_BYTES" "$DEVOPS_OPENTOFU_MINIMUM_BYTES"
  [ "$DEVOPS_OPENTOFU_ARCHITECTURE" = linux-amd64 ] ||
    devops_fatal "DEVOPS_OPENTOFU_ARCHITECTURE must remain linux-amd64"
  devops_validate_archive_file_list "DEVOPS_OPENTOFU_ARCHIVE_FILES" "$DEVOPS_OPENTOFU_ARCHIVE_FILES"
  devops_validate_install_layout \
    "DEVOPS_OPENTOFU" \
    "$DEVOPS_OPENTOFU_INSTALL_ROOT" \
    "$DEVOPS_OPENTOFU_BINARY_PATH"

  devops_validate_semantic_version "DEVOPS_TERRAFORM_VERSION" "$DEVOPS_TERRAFORM_VERSION"
  devops_validate_configured_release_url DEVOPS_TERRAFORM_URL "$DEVOPS_TERRAFORM_URL" "$DEVOPS_TERRAFORM_ARCHIVE_FILENAME"
  devops_validate_lower_hex "DEVOPS_TERRAFORM_SHA256" "$DEVOPS_TERRAFORM_SHA256" 64
  devops_validate_positive_integer "DEVOPS_TERRAFORM_MINIMUM_BYTES" "$DEVOPS_TERRAFORM_MINIMUM_BYTES"
  [ "$DEVOPS_TERRAFORM_ARCHITECTURE" = linux-amd64 ] ||
    devops_fatal "DEVOPS_TERRAFORM_ARCHITECTURE must remain linux-amd64"
  devops_validate_archive_file_list \
    "DEVOPS_TERRAFORM_ARCHIVE_FILES" \
    "$DEVOPS_TERRAFORM_ARCHIVE_FILES"
  devops_validate_install_layout \
    "DEVOPS_TERRAFORM" \
    "$DEVOPS_TERRAFORM_INSTALL_ROOT" \
    "$DEVOPS_TERRAFORM_BINARY_PATH"

  devops_validate_semantic_version "DEVOPS_PACKER_VERSION" "$DEVOPS_PACKER_VERSION"
  devops_validate_configured_release_url DEVOPS_PACKER_URL "$DEVOPS_PACKER_URL" "$DEVOPS_PACKER_ARCHIVE_FILENAME"
  devops_validate_lower_hex "DEVOPS_PACKER_SHA256" "$DEVOPS_PACKER_SHA256" 64
  devops_validate_positive_integer "DEVOPS_PACKER_MINIMUM_BYTES" "$DEVOPS_PACKER_MINIMUM_BYTES"
  [ "$DEVOPS_PACKER_ARCHITECTURE" = linux-amd64 ] ||
    devops_fatal "DEVOPS_PACKER_ARCHITECTURE must remain linux-amd64"
  devops_validate_archive_file_list \
    "DEVOPS_PACKER_ARCHIVE_FILES" \
    "$DEVOPS_PACKER_ARCHIVE_FILES"
  devops_validate_install_layout \
    "DEVOPS_PACKER" \
    "$DEVOPS_PACKER_INSTALL_ROOT" \
    "$DEVOPS_PACKER_BINARY_PATH"

  devops_validate_semantic_version "DEVOPS_WRANGLER_VERSION" "$DEVOPS_WRANGLER_VERSION"
  devops_validate_configured_release_url DEVOPS_WRANGLER_URL "$DEVOPS_WRANGLER_URL" "$DEVOPS_WRANGLER_ARCHIVE_FILENAME"
  devops_validate_lower_hex "DEVOPS_WRANGLER_SHA512" "$DEVOPS_WRANGLER_SHA512" 128
  if ! printf '%s\n' "$DEVOPS_WRANGLER_NPM_INTEGRITY" |
    LC_ALL=C grep -Eq '^sha512-[A-Za-z0-9+/]{86}==$'
  then
    devops_fatal "DEVOPS_WRANGLER_NPM_INTEGRITY must be an npm SHA-512 integrity value"
  fi
  devops_validate_positive_integer "DEVOPS_WRANGLER_MINIMUM_BYTES" "$DEVOPS_WRANGLER_MINIMUM_BYTES"
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
  case "$DEVOPS_WRANGLER_NPM_REGISTRY_URL" in https://*/) ;; *) devops_fatal "DEVOPS_WRANGLER_NPM_REGISTRY_URL must be HTTPS" ;; esac
  devops_validate_install_layout \
    "DEVOPS_WRANGLER" \
    "$DEVOPS_WRANGLER_INSTALL_ROOT" \
    "$DEVOPS_WRANGLER_BINARY_PATH"

  devops_validate_semantic_version "DEVOPS_APTLY_RELEASE_VERSION" "$DEVOPS_APTLY_RELEASE_VERSION"
  devops_validate_configured_release_url DEVOPS_APTLY_RELEASE_URL "$DEVOPS_APTLY_RELEASE_URL" "$DEVOPS_APTLY_RELEASE_ARCHIVE_FILENAME"
  devops_validate_lower_hex "DEVOPS_APTLY_RELEASE_SHA256" "$DEVOPS_APTLY_RELEASE_SHA256" 64
  devops_validate_positive_integer "DEVOPS_APTLY_RELEASE_MINIMUM_BYTES" "$DEVOPS_APTLY_RELEASE_MINIMUM_BYTES"
  [ "$DEVOPS_APTLY_RELEASE_ARCHITECTURE" = linux-amd64 ] ||
    devops_fatal "DEVOPS_APTLY_RELEASE_ARCHITECTURE must remain linux-amd64"
  devops_validate_archive_file_list "DEVOPS_APTLY_RELEASE_ARCHIVE_FILES" "$DEVOPS_APTLY_RELEASE_ARCHIVE_FILES"
  devops_validate_install_layout \
    "DEVOPS_APTLY" \
    "$DEVOPS_APTLY_INSTALL_ROOT" \
    "$DEVOPS_APTLY_BINARY_PATH"

  devops_validate_semantic_version "DEVOPS_OSC_RELEASE_VERSION" "$DEVOPS_OSC_RELEASE_VERSION"
  case "$DEVOPS_OSC_RELEASE_URL" in
    https://*/"${DEVOPS_OSC_RELEASE_ARCHIVE_FILENAME}") ;;
    *) devops_fatal "DEVOPS_OSC_RELEASE_URL must identify an HTTPS wheel" ;;
  esac
  case "$DEVOPS_OSC_RELEASE_URL" in
    *..*) devops_fatal "DEVOPS_OSC_RELEASE_URL must be normalized" ;;
  esac
  devops_validate_lower_hex "DEVOPS_OSC_RELEASE_SHA256" "$DEVOPS_OSC_RELEASE_SHA256" 64
  devops_validate_positive_integer "DEVOPS_OSC_RELEASE_MINIMUM_BYTES" "$DEVOPS_OSC_RELEASE_MINIMUM_BYTES"
  [ "$DEVOPS_OSC_RELEASE_ARCHITECTURE" = python3-any ] ||
    devops_fatal "DEVOPS_OSC_RELEASE_ARCHITECTURE must remain python3-any"
  [ "$DEVOPS_OSC_RELEASE_PACKAGE_ROOT" = osc ] ||
    devops_fatal "DEVOPS_OSC_RELEASE_PACKAGE_ROOT must remain osc"
  [ "$DEVOPS_OSC_RELEASE_DIST_INFO_ROOT" = "osc-${DEVOPS_OSC_RELEASE_VERSION}.dist-info" ] ||
    devops_fatal "DEVOPS_OSC_RELEASE_DIST_INFO_ROOT does not match DEVOPS_OSC_RELEASE_VERSION"
  devops_validate_install_layout \
    "DEVOPS_OSC" \
    "$DEVOPS_OSC_INSTALL_ROOT" \
    "$DEVOPS_OSC_BINARY_PATH"

  if ! printf '%s\n' "$DEVOPS_OBS_BUILD_TAG" | LC_ALL=C grep -Eq '^[0-9]{8}$'; then
    devops_fatal "DEVOPS_OBS_BUILD_TAG must be an eight-digit upstream tag"
  fi
  devops_validate_lower_hex "DEVOPS_OBS_BUILD_COMMIT" "$DEVOPS_OBS_BUILD_COMMIT" 40
  case "$DEVOPS_OBS_BUILD_URL" in https://*/"${DEVOPS_OBS_BUILD_COMMIT}") ;; *) devops_fatal "DEVOPS_OBS_BUILD_URL must end at the configured commit" ;; esac
  devops_validate_lower_hex "DEVOPS_OBS_BUILD_SHA256" "$DEVOPS_OBS_BUILD_SHA256" 64
  devops_validate_positive_integer "DEVOPS_OBS_BUILD_MINIMUM_BYTES" "$DEVOPS_OBS_BUILD_MINIMUM_BYTES"
  [ "$DEVOPS_OBS_BUILD_ARCHITECTURE" = source-any ] ||
    devops_fatal "DEVOPS_OBS_BUILD_ARCHITECTURE must remain source-any"
  devops_validate_install_layout \
    "DEVOPS_OBS_BUILD" \
    "$DEVOPS_OBS_BUILD_INSTALL_ROOT" \
    "$DEVOPS_OBS_BUILD_BINARY_PATH"
  devops_validate_archive_file_list "DEVOPS_OBS_BUILD_ENTRYPOINTS" "$DEVOPS_OBS_BUILD_ENTRYPOINTS"
}
