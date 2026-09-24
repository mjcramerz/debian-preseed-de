#!/bin/sh
# Sourced installer module; edit this file directly.

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
} >"${install_dir}/.bazelisk-release"
chmod 0644 "${install_dir}/.bazelisk-release"
chown root:root "${install_dir}/.bazelisk-release"

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
    >"${extracted_dir}/.node-release"
  chmod 0644 "${extracted_dir}/.node-release"

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

