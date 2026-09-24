#!/bin/sh
# Sourced installer module; edit this file directly.

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
} >"${install_dir}/.rustup-bootstrap"
chmod 0644 "${install_dir}/.rustup-bootstrap"
chown root:root "${install_dir}/.rustup-bootstrap"

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

