#!/bin/sh
set -eu

target_root=${1:-/target}
[ -d "$target_root" ] || exit 0

ch341a_fatal() {
  printf 'fatal: %s\n' "$*" >&2
  exit 1
}

ch341a_info() {
  printf '[late:ch341a] %s\n' "$*" >&2
}

target_passwd_ids() {
  awk -F: -v wanted_user="$1" '$1 == wanted_user { print $3 ":" $4; exit }' "${target_root}/etc/passwd" 2>/dev/null || true
}

ch341a_validate_abs_path() {
  case "${2:-}" in
    /*) ;;
    *) ch341a_fatal "$1 must be an absolute path: ${2:-unset}" ;;
  esac
  case "$2" in
    /|*..*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/@%:+,-]*)
      ch341a_fatal "$1 contains unsupported path syntax: $2"
      ;;
  esac
}

ch341a_stage_target_asset() {
  repo_path=$1
  target_path=$2
  mode=$3
  tmp_asset="${tmp_env_dir}/$(basename "$target_path").$$"
  target_host_path="${target_root}${target_path}"

  ch341a_validate_abs_path "target path" "$target_path"
  bootstrap_fetch_seed_file "$seed_base" "$repo_path" "$tmp_asset" 0600 "ch341a asset ${repo_path}"
  install -d -m 0755 "${target_root}$(dirname "$target_path")"
  install -m "$mode" "$tmp_asset" "$target_host_path"
  chmod "$mode" "$target_host_path"
  rm -f "$tmp_asset"
}

ch341a_render_target_asset() {
  repo_path=$1
  target_path=$2
  mode=$3
  shift 3
  tmp_asset="${tmp_env_dir}/$(basename "$target_path").$$"
  tmp_rendered="${tmp_asset}.rendered"
  target_host_path="${target_root}${target_path}"

  ch341a_validate_abs_path "target path" "$target_path"
  bootstrap_fetch_seed_file "$seed_base" "$repo_path" "$tmp_asset" 0600 "ch341a template ${repo_path}"
  installer_apply_scalar_placeholders "$tmp_asset" "$tmp_rendered" "$@"
  installer_assert_no_unresolved_installer_placeholders "$tmp_rendered" "ch341a template ${repo_path}"
  install -d -m 0755 "${target_root}$(dirname "$target_path")"
  install -m "$mode" "$tmp_rendered" "$target_host_path"
  chmod "$mode" "$target_host_path"
  rm -f "$tmp_asset" "$tmp_rendered"
}

ch341a_install_snander() {
  # The single-quoted script is expanded only inside the target; policy values
  # are passed as positional parameters below.
  # shellcheck disable=SC2016
  run_in_target "install checksum-pinned SNANDer ${SNANDER_VERSION}" /bin/sh -eu -c '
ch341a_target_fatal() {
  printf "fatal: SNANDer install: %s\n" "$*" >&2
  exit 1
}

LC_ALL=C
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export LC_ALL PATH

snander_version=$1
snander_commit=$2
snander_source_url=$3
snander_archive_sha256=$4
snander_archive_bytes=$5
snander_binary_sha256=$6

printf "%s\n" "$snander_version" |
  grep -Eq "^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$" ||
  ch341a_target_fatal "version must contain four numeric components: ${snander_version:-unset}"
case "$snander_commit" in
  *[!0-9a-f]*) ch341a_target_fatal "invalid commit: ${snander_commit:-unset}" ;;
esac
[ "${#snander_commit}" -eq 40 ] || ch341a_target_fatal "commit must contain 40 lowercase hexadecimal characters"
[ "$snander_source_url" = "https://codeload.github.com/McMCCRU/SNANDer/tar.gz/${snander_commit}" ] ||
  ch341a_target_fatal "source URL does not match the pinned upstream commit"
for snander_digest in "$snander_archive_sha256" "$snander_binary_sha256"; do
  case "$snander_digest" in
    *[!0-9a-f]*) ch341a_target_fatal "invalid SHA-256 policy" ;;
  esac
  [ "${#snander_digest}" -eq 64 ] || ch341a_target_fatal "SHA-256 policy must contain 64 characters"
done
case "$snander_archive_bytes" in
  ""|*[!0-9]*) ch341a_target_fatal "invalid archive byte count" ;;
esac
[ "$snander_archive_bytes" -ge 7000000 ] && [ "$snander_archive_bytes" -le 9000000 ] ||
  ch341a_target_fatal "archive byte count is outside the approved range"

[ "$(/usr/bin/dpkg --print-architecture)" = amd64 ] ||
  ch341a_target_fatal "the pinned upstream Linux binary supports Debian amd64 only"
for snander_command in awk chmod curl grep install ln mktemp mv readlink rm sha256sum tar tr wc; do
  command -v "$snander_command" >/dev/null 2>&1 ||
    ch341a_target_fatal "required command is unavailable: $snander_command"
done

snander_release_parent=/usr/local/lib/snander
snander_release_root="${snander_release_parent}/${snander_version}"
snander_release_binary="${snander_release_root}/bin/SNANDer"
snander_release_metadata="${snander_release_root}/metadata/installer-release"
snander_release_license="${snander_release_root}/metadata/LICENSE"
snander_release_readme="${snander_release_root}/metadata/readme.txt"
snander_release_support_list="${snander_release_root}/metadata/flash-support-list.txt"
snander_release_source="${snander_release_root}/source/SNANDer-${snander_commit}.tar.gz"
snander_stable_binary=/usr/local/bin/SNANDer
snander_archive_root="SNANDer-${snander_commit}"
snander_download_dir=
snander_publish_dir=

ch341a_target_cleanup() {
  case "${snander_download_dir:-}" in
    /var/tmp/snander-install.*) rm -rf -- "$snander_download_dir" ;;
  esac
  case "${snander_publish_dir:-}" in
    /usr/local/lib/snander/.release.*) rm -rf -- "$snander_publish_dir" ;;
  esac
}
trap ch341a_target_cleanup 0
trap "exit 1" 1 2 15

for snander_system_dir in /usr/local /usr/local/lib /usr/local/bin; do
  if [ -e "$snander_system_dir" ] || [ -L "$snander_system_dir" ]; then
    [ -d "$snander_system_dir" ] && [ ! -L "$snander_system_dir" ] ||
      ch341a_target_fatal "required installation directory is unsafe: $snander_system_dir"
  else
    install -d -m 0755 "$snander_system_dir"
  fi
done
if [ -e "$snander_release_parent" ] || [ -L "$snander_release_parent" ]; then
  [ -d "$snander_release_parent" ] && [ ! -L "$snander_release_parent" ] ||
    ch341a_target_fatal "release parent is not a direct directory: $snander_release_parent"
else
  install -d -m 0755 "$snander_release_parent"
fi
if [ -e "$snander_release_root" ] || [ -L "$snander_release_root" ]; then
  [ -d "$snander_release_root" ] && [ ! -L "$snander_release_root" ] ||
    ch341a_target_fatal "refusing to reuse a non-directory release path: $snander_release_root"
  for snander_release_file in \
    "$snander_release_binary" \
    "$snander_release_metadata" \
    "$snander_release_license" \
    "$snander_release_readme" \
    "$snander_release_support_list" \
    "$snander_release_source"
  do
    [ -f "$snander_release_file" ] && [ ! -L "$snander_release_file" ] ||
      ch341a_target_fatal "existing release member is unavailable: $snander_release_file"
  done
  snander_existing_sha256=$(sha256sum "$snander_release_binary" | awk "{print \$1}")
  [ "$snander_existing_sha256" = "$snander_binary_sha256" ] ||
    ch341a_target_fatal "existing release binary does not match the pinned SHA-256"
  snander_existing_source_bytes=$(wc -c <"$snander_release_source" | tr -d " ")
  [ "$snander_existing_source_bytes" = "$snander_archive_bytes" ] ||
    ch341a_target_fatal "existing source archive size does not match policy"
  snander_existing_source_sha256=$(sha256sum "$snander_release_source" | awk "{print \$1}")
  [ "$snander_existing_source_sha256" = "$snander_archive_sha256" ] ||
    ch341a_target_fatal "existing source archive does not match the pinned SHA-256"
  snander_expected_metadata=$(printf "%s\n" \
    "version=${snander_version}" \
    "commit=${snander_commit}" \
    "source_url=${snander_source_url}" \
    "source_sha256=${snander_archive_sha256}" \
    "source_bytes=${snander_archive_bytes}" \
    "binary_sha256=${snander_binary_sha256}")
  snander_existing_metadata=$(awk "{ print }" "$snander_release_metadata")
  [ "$snander_existing_metadata" = "$snander_expected_metadata" ] ||
    ch341a_target_fatal "existing release metadata does not match policy"
else
  snander_download_dir=$(mktemp -d /var/tmp/snander-install.XXXXXXXX) ||
    ch341a_target_fatal "unable to allocate download directory"
  chmod 0700 "$snander_download_dir"
  snander_archive="${snander_download_dir}/source.tar.gz"
  snander_listing="${snander_download_dir}/members.txt"
  snander_extract="${snander_download_dir}/extract"

  curl \
    --fail \
    --silent \
    --show-error \
    --location \
    --proto "=https" \
    --proto-redir "=https" \
    --tlsv1.2 \
    --connect-timeout 15 \
    --max-time 600 \
    --max-redirs 5 \
    --retry 5 \
    --retry-delay 2 \
    --retry-all-errors \
    --retry-max-time 600 \
    --max-filesize "$snander_archive_bytes" \
    --user-agent "unattended-installer-ch341a/1.0" \
    --output "$snander_archive" \
    --url "$snander_source_url" ||
    ch341a_target_fatal "failed to download pinned upstream source archive"

  [ -f "$snander_archive" ] && [ ! -L "$snander_archive" ] ||
    ch341a_target_fatal "downloaded source archive is not a regular file"
  snander_actual_bytes=$(wc -c <"$snander_archive" | tr -d " ")
  [ "$snander_actual_bytes" = "$snander_archive_bytes" ] ||
    ch341a_target_fatal "downloaded source archive size does not match policy"
  snander_actual_sha256=$(sha256sum "$snander_archive" | awk "{print \$1}")
  [ "$snander_actual_sha256" = "$snander_archive_sha256" ] ||
    ch341a_target_fatal "downloaded source archive SHA-256 does not match policy"

  tar -tzf "$snander_archive" >"$snander_listing" ||
    ch341a_target_fatal "source archive cannot be listed"
  if grep -Eq "(^/|(^|/)\\.\\.(/|$))" "$snander_listing"; then
    ch341a_target_fatal "source archive contains an unsafe member path"
  fi
  for snander_member in \
    "${snander_archive_root}/Linux/SNANDer" \
    "${snander_archive_root}/LICENSE" \
    "${snander_archive_root}/readme.txt" \
    "${snander_archive_root}/flash_support_list.txt"
  do
    grep -Fqx "$snander_member" "$snander_listing" ||
      ch341a_target_fatal "source archive is missing required member: $snander_member"
  done

  install -d -m 0700 "$snander_extract"
  tar \
    --extract \
    --gzip \
    --file "$snander_archive" \
    --directory "$snander_extract" \
    --no-same-owner \
    --no-same-permissions \
    "${snander_archive_root}/Linux/SNANDer" \
    "${snander_archive_root}/LICENSE" \
    "${snander_archive_root}/readme.txt" \
    "${snander_archive_root}/flash_support_list.txt" ||
    ch341a_target_fatal "source archive extraction failed"

  snander_extracted_root="${snander_extract}/${snander_archive_root}"
  for snander_file in \
    "$snander_extracted_root/Linux/SNANDer" \
    "$snander_extracted_root/LICENSE" \
    "$snander_extracted_root/readme.txt" \
    "$snander_extracted_root/flash_support_list.txt"
  do
    [ -f "$snander_file" ] && [ ! -L "$snander_file" ] ||
      ch341a_target_fatal "extracted release member is unsafe: $snander_file"
  done
  snander_extracted_binary_sha256=$(
    sha256sum "$snander_extracted_root/Linux/SNANDer" | awk "{print \$1}"
  )
  [ "$snander_extracted_binary_sha256" = "$snander_binary_sha256" ] ||
    ch341a_target_fatal "extracted Linux binary SHA-256 does not match policy"

  snander_publish_dir=$(mktemp -d "${snander_release_parent}/.release.XXXXXXXX") ||
    ch341a_target_fatal "unable to allocate release staging directory"
  chmod 0755 "$snander_publish_dir"
  install -d -m 0755 \
    "$snander_publish_dir/bin" \
    "$snander_publish_dir/metadata" \
    "$snander_publish_dir/source"
  install -m 0755 "$snander_extracted_root/Linux/SNANDer" "$snander_publish_dir/bin/SNANDer"
  install -m 0644 "$snander_extracted_root/LICENSE" "$snander_publish_dir/metadata/LICENSE"
  install -m 0644 "$snander_extracted_root/readme.txt" "$snander_publish_dir/metadata/readme.txt"
  install -m 0644 \
    "$snander_extracted_root/flash_support_list.txt" \
    "$snander_publish_dir/metadata/flash-support-list.txt"
  install -m 0644 \
    "$snander_archive" \
    "$snander_publish_dir/source/SNANDer-${snander_commit}.tar.gz"
  {
    printf "version=%s\n" "$snander_version"
    printf "commit=%s\n" "$snander_commit"
    printf "source_url=%s\n" "$snander_source_url"
    printf "source_sha256=%s\n" "$snander_archive_sha256"
    printf "source_bytes=%s\n" "$snander_archive_bytes"
    printf "binary_sha256=%s\n" "$snander_binary_sha256"
  } >"$snander_publish_dir/metadata/installer-release"
  chmod 0644 "$snander_publish_dir/metadata/installer-release"

  mv -- "$snander_publish_dir" "$snander_release_root" ||
    ch341a_target_fatal "failed to publish the complete SNANDer release"
  snander_publish_dir=
fi

if [ -e "$snander_stable_binary" ] && [ ! -L "$snander_stable_binary" ]; then
  ch341a_target_fatal "refusing to replace an unmanaged SNANDer executable"
fi
if [ -L "$snander_stable_binary" ]; then
  [ "$(readlink "$snander_stable_binary")" = "$snander_release_binary" ] ||
    ch341a_target_fatal "refusing to replace an unexpected SNANDer symlink"
else
  ln -s "$snander_release_binary" "$snander_stable_binary"
fi
[ -x "$snander_stable_binary" ] || ch341a_target_fatal "stable SNANDer entrypoint is unavailable"
[ "$(sha256sum "$snander_stable_binary" | awk "{print \$1}")" = "$snander_binary_sha256" ] ||
  ch341a_target_fatal "stable SNANDer entrypoint failed final integrity validation"

trap - 1 2 15
ch341a_target_cleanup
trap - 0
' sh \
    "$SNANDER_VERSION" \
    "$SNANDER_COMMIT" \
    "$SNANDER_SOURCE_URL" \
    "$SNANDER_ARCHIVE_SHA256" \
    "$SNANDER_ARCHIVE_BYTES" \
    "$SNANDER_BINARY_SHA256"
}

runtime_env_path() {
  for candidate in /tmp/install-env/runtime.env /tmp/install-runtime/state/runtime.env; do
    [ -r "$candidate" ] || continue
    printf '%s\n' "$candidate"
    return 0
  done
  return 1
}

runtime_dir=${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}
bootstrap_lib=${INSTALLER_BOOTSTRAP_LIB:-${runtime_dir}/bootstrap/bootstrap.sh}
tmp_env_dir=${INSTALLER_LATE_TMP_ENV_DIR:-/tmp/install-env-late/ch341a}

[ -s "$bootstrap_lib" ] || ch341a_fatal "installer bootstrap library is unavailable: ${bootstrap_lib}"
# shellcheck disable=SC1090,SC1091
. "$bootstrap_lib"
bootstrap_source_common_lib "" || ch341a_fatal "failed to source installer common library"
seed_base=$(installer_current_seed_base 2>/dev/null || installer_seed_base "")
bootstrap_source_common_support_libs "$seed_base" "$tmp_env_dir" fetch hook target || {
  ch341a_fatal "failed to source installer late support libraries"
}
installer_ensure_context_loaded "$seed_base"

installer_selected_class_reference_is_selected addon/ch341a 2>/dev/null || exit 0

account_env=${INSTALLER_LATE_ACCOUNT_ENV:-/tmp/install-env-late/account.env}
host_env=${INSTALLER_LATE_HOST_ENV:-/tmp/install-env-late/host.env}
[ -r "$account_env" ] || installer_fetch_account_env "$seed_base" "$account_env" 0600
[ -r "$host_env" ] || installer_fetch_host_env "$seed_base" "$(installer_resolve_host_profile "")" "$host_env" 0600

# shellcheck disable=SC1090,SC1091
. "$account_env"
# shellcheck disable=SC1090,SC1091
. "$host_env"

if runtime_env=$(runtime_env_path); then
  # shellcheck disable=SC1090,SC1091
  . "$runtime_env"
fi

: "${ACCOUNT_USERNAME:?ACCOUNT_USERNAME must be set before staging ch341a assets}"
: "${DIR_POOL_FIRMWARE:=/pool/firmware}"
ch341a_validate_abs_path "DIR_POOL_FIRMWARE" "$DIR_POOL_FIRMWARE"

SNANDER_VERSION=1.7.9.3
SNANDER_COMMIT=89e1fc29d01acee83f67fae95eb14a2b860fcee0
SNANDER_SOURCE_URL="https://codeload.github.com/McMCCRU/SNANDer/tar.gz/${SNANDER_COMMIT}"
SNANDER_ARCHIVE_SHA256=5fb6a93c8f2b6becbe5dcf97384b3b4842e6e20c732b484b46cc8d7717908536
SNANDER_ARCHIVE_BYTES=7941700
SNANDER_BINARY_SHA256=eeaf6ee9b046f28ffbf326591e5b77598156b14ea1c450c07b7c4a862b5475a2

run_in_target "create ch341a authorization group" /bin/sh -eu -c '
command -v getent >/dev/null 2>&1
command -v groupadd >/dev/null 2>&1
getent group usbadmin >/dev/null 2>&1 ||
  groupadd --system usbadmin
getent group usbadmin >/dev/null 2>&1
' sh

ch341a_stage_target_asset \
  "$(installer_repo_join_var DIR_HOOKS_TARGET etc/udev/rules.d/61-ch341a-programmers.rules)" \
  /etc/udev/rules.d/61-ch341a-programmers.rules \
  0644

ch341a_stage_target_asset \
  "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/sbin/fwops-mode)" \
  /usr/local/sbin/fwops-mode \
  0755

ch341a_render_target_asset \
  "$(installer_repo_join_var DIR_HOOKS_TARGET etc/tmpfiles.d/86-firmware-workspace.conf.tmpl)" \
  /etc/tmpfiles.d/86-firmware-workspace.conf \
  0644 \
  ACCOUNT_USERNAME "$ACCOUNT_USERNAME" \
  DIR_POOL_FIRMWARE "$DIR_POOL_FIRMWARE"

ch341a_render_target_asset \
  "$(installer_repo_join_var DIR_HOOKS_TARGET etc/skel-desktop/.profile.d/75-firmware-workspace.sh.tmpl)" \
  /etc/skel-desktop/.profile.d/75-firmware-workspace.sh \
  0644 \
  ACCOUNT_USERNAME "$ACCOUNT_USERNAME" \
  DIR_POOL_FIRMWARE "$DIR_POOL_FIRMWARE" \
  SNANDER_VERSION "$SNANDER_VERSION"

if [ -n "${ACCOUNT_HOME:-}" ]; then
  ch341a_validate_abs_path "ACCOUNT_HOME" "$ACCOUNT_HOME"
  install -d -m 0700 "${target_root}${ACCOUNT_HOME}/.profile.d"
  install -m 0644 \
    "${target_root}/etc/skel-desktop/.profile.d/75-firmware-workspace.sh" \
    "${target_root}${ACCOUNT_HOME}/.profile.d/75-firmware-workspace.sh"
  account_ids=$(target_passwd_ids "$ACCOUNT_USERNAME")
  if [ -n "$account_ids" ]; then
    chown "$account_ids" "${target_root}${ACCOUNT_HOME}/.profile.d"
    chown "$account_ids" "${target_root}${ACCOUNT_HOME}/.profile.d/75-firmware-workspace.sh"
  fi
fi

# shellcheck disable=SC2016
run_in_target "create firmware workspace roots" /bin/sh -eu -c '
systemd-tmpfiles --create /etc/tmpfiles.d/86-firmware-workspace.conf
test -d "$1"
test -d "$1/$2"
test -d "$1/$2/original"
test -d "$1/$2/analysis"
test -d "$1/$2/working"
test -d "$1/$2/writeback"
test -d "$1/$2/logs"
' sh "$DIR_POOL_FIRMWARE" "$ACCOUNT_USERNAME"

# shellcheck disable=SC2016
run_in_target "grant programmer USB access to primary account" /bin/sh -eu -c '
account_user=$1
getent group usbadmin >/dev/null 2>&1
usermod -a -G usbadmin -- "$account_user"
getent group dialout >/dev/null 2>&1
usermod -a -G dialout -- "$account_user"
' sh "$ACCOUNT_USERNAME"

ch341a_install_snander

# shellcheck disable=SC2016
run_in_target "validate ch341a firmware and UART toolchain" /bin/sh -eu -c '
if [ ! -x /usr/bin/binwalk ] && [ ! -x /usr/bin/pybinwalk ]; then
  printf "%s\n" "fatal: required CH341A tool is unavailable: binwalk or pybinwalk" >&2
  exit 1
fi
for required_command in \
  /usr/sbin/flashrom \
  /usr/bin/flashprog \
  /usr/bin/IMSProg \
  /usr/bin/IMSProg_editor \
  /usr/local/bin/SNANDer \
  /usr/bin/uefitool \
  /usr/bin/uefiextract \
  /usr/bin/uefifind \
  /usr/sbin/ifdtool \
  /usr/sbin/cbfstool \
  /usr/sbin/mtdinfo \
  /usr/sbin/nanddump \
  /usr/sbin/nandwrite \
  /usr/bin/spi-config \
  /usr/bin/spi-pipe \
  /usr/bin/picocom \
  /usr/bin/minicom \
  /usr/bin/screen \
  /usr/bin/lsusb \
  /usr/sbin/modprobe \
  /usr/local/sbin/fwops-mode
do
  [ -x "$required_command" ] || {
    printf "fatal: required CH341A tool is unavailable: %s\n" "$required_command" >&2
    exit 1
  }
done
' sh

ch341a_info "staged firmware workspace assets for account=${ACCOUNT_USERNAME}"
