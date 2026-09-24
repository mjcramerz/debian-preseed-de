#!/bin/sh
# Sourced installer module; edit this file directly.

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

