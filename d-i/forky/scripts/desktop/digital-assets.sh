#!/bin/sh
# Pinned Digital Assets helper installation. This file is sourced, not executed.

desktop_digital_assets_fail() {
  installer_fatal "Digital Assets: $*"
}

desktop_digital_assets_validate_sha256() {
  value_name=$1
  value=$2

  case "$value" in
    ''|*[!0123456789abcdef]*)
      desktop_digital_assets_fail "${value_name} must contain lowercase hexadecimal characters"
      ;;
  esac
  [ "${#value}" -eq 64 ] ||
    desktop_digital_assets_fail "${value_name} must contain 64 characters"
}

desktop_digital_assets_validate_policy() {
  : "${DIGITAL_ASSETS_PDFCPU_URL:?DIGITAL_ASSETS_PDFCPU_URL must be set}"
  : "${DIGITAL_ASSETS_PDFCPU_SHA256:?DIGITAL_ASSETS_PDFCPU_SHA256 must be set}"
  : "${DIGITAL_ASSETS_TYPST_URL:?DIGITAL_ASSETS_TYPST_URL must be set}"
  : "${DIGITAL_ASSETS_TYPST_SHA256:?DIGITAL_ASSETS_TYPST_SHA256 must be set}"
  : "${ACCOUNT_USERNAME:?ACCOUNT_USERNAME must be set}"
  : "${ACCOUNT_HOME:?ACCOUNT_HOME must be set}"

  [ "$DIGITAL_ASSETS_PDFCPU_URL" = "https://github.com/pdfcpu/pdfcpu/releases/download/v0.13.0/pdfcpu_0.13.0_Linux_x86_64.tar.xz" ] ||
    desktop_digital_assets_fail "pdfcpu URL must remain pinned to the approved 0.13.0 Linux x86-64 release"
  [ "$DIGITAL_ASSETS_PDFCPU_SHA256" = "0f03f691c6275fa826e5d99e7aefbc8050180e4bc4a3b919b582137cd7da9bd7" ] ||
    desktop_digital_assets_fail "pdfcpu SHA-256 must match the approved release digest"
  [ "$DIGITAL_ASSETS_TYPST_URL" = "https://github.com/typst/typst/releases/download/v0.15.1/typst-x86_64-unknown-linux-musl.tar.xz" ] ||
    desktop_digital_assets_fail "Typst URL must remain pinned to the approved 0.15.1 Linux x86-64 release"
  [ "$DIGITAL_ASSETS_TYPST_SHA256" = "a6d077d0a95eed5a2eba715b2dae06be954f624ccbf85758a03f389ded33118c" ] ||
    desktop_digital_assets_fail "Typst SHA-256 must match the approved release digest"

  desktop_digital_assets_validate_sha256 \
    DIGITAL_ASSETS_PDFCPU_SHA256 \
    "$DIGITAL_ASSETS_PDFCPU_SHA256"
  desktop_digital_assets_validate_sha256 \
    DIGITAL_ASSETS_TYPST_SHA256 \
    "$DIGITAL_ASSETS_TYPST_SHA256"

  case "$ACCOUNT_USERNAME" in
    ''|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-]*)
      desktop_digital_assets_fail "ACCOUNT_USERNAME contains unsupported characters"
      ;;
  esac
  desktop_require_absolute_account_home
}

desktop_digital_assets_preflight_target_architecture() {
  desktop_digital_assets_validate_policy

  DIGITAL_ASSETS_TARGET_ARCHITECTURE=$(
    capture_in_target \
      "detect target architecture for Digital Assets tools" \
      /usr/bin/dpkg --print-architecture
  )
  [ "$DIGITAL_ASSETS_TARGET_ARCHITECTURE" = amd64 ] ||
    desktop_digital_assets_fail \
      "the pinned Linux x86-64 tools require amd64, got ${DIGITAL_ASSETS_TARGET_ARCHITECTURE:-unset}"
}

desktop_digital_assets_install_release_tool() {
  tool_name=$1
  tool_version=$2
  tool_url=$3
  tool_sha256=$4
  tool_minimum_bytes=$5
  tool_maximum_bytes=$6
  tool_maximum_extracted_bytes=$7
  tool_maximum_members=$8
  shift 8

  [ "$#" -ge 1 ] ||
    desktop_digital_assets_fail "release validation command is missing for ${tool_name}"

  tool_work_dir="/tmp/digital-assets-${tool_name}-install.$$"
  tool_archive="${tool_work_dir}/release.tar.xz"
  tool_extract_dir="${tool_work_dir}/extract"
  tool_member_list="${tool_work_dir}/members"
  tool_archive_host="/target${tool_archive}"
  tool_extract_host="/target${tool_extract_dir}"
  tool_member_list_host="/target${tool_member_list}"
  tool_install_parent_host=/target/usr/local/lib
  tool_install_host="${tool_install_parent_host}/${tool_name}"
  tool_staged_host="${tool_install_parent_host}/.${tool_name}.new.$$"
  tool_member_list_maximum_bytes=$((tool_maximum_members * 8192))
  tool_member_list_maximum_blocks=$(((tool_member_list_maximum_bytes + 511) / 512))

  rm -rf -- "/target${tool_work_dir}" "$tool_staged_host"
  install -d -m 0700 "$tool_extract_host"

  if ! attempt_in_target "download pinned ${tool_name} release" \
    /usr/bin/env -i \
      HOME=/root \
      LC_ALL=C \
      PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
      /usr/bin/curl \
        --fail \
        --silent \
        --show-error \
        --location \
        --proto '=https' \
        --proto-redir '=https' \
        --connect-timeout 15 \
        --max-time 300 \
        --max-redirs 4 \
        --retry 3 \
        --retry-all-errors \
        --max-filesize "$tool_maximum_bytes" \
        --user-agent "unattended-installer-digital-assets-${tool_name}/1.0" \
        --header 'Accept: application/x-xz, application/octet-stream;q=0.9, */*;q=0.1' \
        --output "$tool_archive" \
        --url "$tool_url"
  then
    desktop_digital_assets_fail "official ${tool_name} release archive download failed"
  fi

  [ -f "$tool_archive_host" ] && [ ! -L "$tool_archive_host" ] ||
    desktop_digital_assets_fail "downloaded ${tool_name} archive is not a regular file"
  tool_archive_size=$(wc -c <"$tool_archive_host" | awk '{print $1}')
  case "$tool_archive_size" in
    ''|*[!0123456789]*)
      desktop_digital_assets_fail "downloaded ${tool_name} archive has an invalid size"
      ;;
  esac
  [ "$tool_archive_size" -ge "$tool_minimum_bytes" ] ||
    desktop_digital_assets_fail "downloaded ${tool_name} archive is unexpectedly small"
  [ "$tool_archive_size" -le "$tool_maximum_bytes" ] ||
    desktop_digital_assets_fail "downloaded ${tool_name} archive exceeds its size ceiling"

  tool_archive_sha256=$(
    capture_in_target \
      "hash downloaded ${tool_name} archive" \
      /usr/bin/sha256sum "$tool_archive" |
      awk '{print $1}'
  )
  [ "$tool_archive_sha256" = "$tool_sha256" ] ||
    desktop_digital_assets_fail "downloaded ${tool_name} archive SHA-256 does not match the pinned digest"

  # Tar member names can compress exceptionally well. Keep the private member
  # list bounded before parsing it so a malformed archive cannot consume
  # unbounded installer memory or target disk space.
  # shellcheck disable=SC2016
  if ! attempt_in_target "list downloaded ${tool_name} archive" /bin/sh -eu -c '
archive_path=$1
member_list_path=$2
maximum_blocks=$3
umask 077
/usr/bin/rm -f -- "$member_list_path"
ulimit -f "$maximum_blocks"
/usr/bin/tar -tJf "$archive_path" >"$member_list_path"
[ -s "$member_list_path" ]
' sh \
    "$tool_archive" \
    "$tool_member_list" \
    "$tool_member_list_maximum_blocks"
  then
    desktop_digital_assets_fail "downloaded ${tool_name} archive member list is invalid or exceeds its size ceiling"
  fi
  [ -f "$tool_member_list_host" ] && [ ! -L "$tool_member_list_host" ] ||
    desktop_digital_assets_fail "downloaded ${tool_name} archive member list is not a regular file"
  if ! awk -v maximum_members="$tool_maximum_members" '
    {
      count++
      if (count > maximum_members) {
        bad = 1
        exit
      }
      if ($0 == "" ||
          $0 ~ /^\// ||
          $0 ~ /\\/ ||
          $0 ~ /(^|\/)\.\.($|\/)/ ||
          $0 ~ /\/\// ||
          $0 !~ /^[ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._\/-]+$/ ||
          seen[$0]++) {
        bad = 1
      }
    }
    END {
      exit (bad || count == 0 || count > maximum_members) ? 1 : 0
    }
  ' "$tool_member_list_host"
  then
    desktop_digital_assets_fail "downloaded ${tool_name} archive contains unsafe or excessive member paths"
  fi

  if ! attempt_in_target "extract pinned ${tool_name} release archive" \
    /usr/bin/tar \
      --extract \
      --xz \
      --file "$tool_archive" \
      --directory "$tool_extract_dir" \
      --no-same-owner \
      --no-same-permissions
  then
    desktop_digital_assets_fail "failed to extract the downloaded ${tool_name} archive"
  fi

  unsupported_tool_node=$(
    find "$tool_extract_host" \
      -mindepth 1 \
      ! -type f \
      ! -type d \
      -print |
      sed -n '1p'
  )
  [ -z "$unsupported_tool_node" ] ||
    desktop_digital_assets_fail "downloaded ${tool_name} archive extracted an unsupported node"

  tool_binary_count=$(
    find "$tool_extract_host" -type f -name "$tool_name" -print |
      awk 'NF { count++ } END { print count + 0 }'
  )
  [ "$tool_binary_count" -eq 1 ] ||
    desktop_digital_assets_fail "downloaded ${tool_name} archive must contain exactly one ${tool_name} binary"
  tool_binary_host=$(find "$tool_extract_host" -type f -name "$tool_name" -print | sed -n '1p')
  [ -f "$tool_binary_host" ] && [ ! -L "$tool_binary_host" ] ||
    desktop_digital_assets_fail "extracted ${tool_name} binary is invalid"
  tool_binary_target=${tool_binary_host#/target}

  tool_extracted_kib=$(
    desktop_target_tree_size_kib \
      "measure extracted ${tool_name} release size" \
      "$tool_extract_dir"
  )
  case "$tool_extracted_kib" in
    ''|*[!0123456789]*)
      desktop_digital_assets_fail "extracted ${tool_name} release size is invalid"
      ;;
  esac
  tool_extracted_bytes=$((tool_extracted_kib * 1024))
  [ "$tool_extracted_bytes" -le "$tool_maximum_extracted_bytes" ] ||
    desktop_digital_assets_fail "downloaded ${tool_name} archive expands beyond its size ceiling"

  tool_file_type=$(
    capture_in_target \
      "inspect extracted ${tool_name} binary" \
      /usr/bin/file -b "$tool_binary_target"
  )
  case "$tool_file_type" in
    *"ELF 64-bit"*"x86-64"*) ;;
    *)
      desktop_digital_assets_fail "extracted ${tool_name} binary is not an x86-64 ELF executable"
      ;;
  esac

  install -d -m 0755 "$tool_install_parent_host" /target/usr/local/bin
  install -d -m 0755 "$tool_staged_host"
  install -m 0755 "$tool_binary_host" "${tool_staged_host}/${tool_name}"
  cat >"${tool_staged_host}/.managed-release" <<EOF
version=${tool_version}
url=${tool_url}
archive_sha256=${tool_sha256}
architecture=${DIGITAL_ASSETS_TARGET_ARCHITECTURE}
EOF
  chmod 0644 "${tool_staged_host}/.managed-release"
  chown -R root:root "$tool_staged_host"

  [ ! -L "$tool_install_host" ] ||
    desktop_digital_assets_fail "managed ${tool_name} installation path must not be a symbolic link"
  rm -rf -- "$tool_install_host"
  mv "$tool_staged_host" "$tool_install_host"
  ln -sfn "../lib/${tool_name}/${tool_name}" "/target/usr/local/bin/${tool_name}"

  rm -rf -- "/target${tool_work_dir}"
  desktop_log \
    "installed_digital_assets_tool tool=${tool_name} version=${tool_version} archive_sha256=${tool_sha256}"
}

desktop_digital_assets_seal_python_tools() {
  digital_assets_root=$1
  digital_assets_pipx_home=$2
  digital_assets_pipx_bin_dir=$3
  digital_assets_pipx_man_dir=$4
  digital_assets_python=$5

  # Third-party Python package installation runs under a transient unprivileged
  # builder. Seal the completed runtime before a desktop session can execute it
  # so the desktop account cannot alter its interpreter, dependencies, or pipx
  # entry points.
  # shellcheck disable=SC2016 # The quoted program executes inside the target.
  run_in_target "seal root-owned Digital Assets Python tools" /bin/sh -eu -c '
root=$1
pipx_home=$2
pipx_bin_dir=$3
pipx_man_dir=$4
python=$5

[ -d "$root" ] && [ ! -L "$root" ] ||
  { printf "%s\n" "Digital Assets Python root is missing or symbolic" >&2; exit 1; }
[ -d "$pipx_home" ] && [ ! -L "$pipx_home" ] ||
  { printf "%s\n" "Digital Assets pipx home is missing or symbolic" >&2; exit 1; }
[ -d "$pipx_bin_dir" ] && [ ! -L "$pipx_bin_dir" ] ||
  { printf "%s\n" "Digital Assets pipx bin directory is missing or symbolic" >&2; exit 1; }
[ -d "$pipx_man_dir" ] && [ ! -L "$pipx_man_dir" ] ||
  { printf "%s\n" "Digital Assets pipx man directory is missing or symbolic" >&2; exit 1; }
[ -d "${pipx_home}/venvs" ] && [ ! -L "${pipx_home}/venvs" ] ||
  { printf "%s\n" "Digital Assets pipx venv directory is missing or symbolic" >&2; exit 1; }
[ -d "${pipx_home}/venvs/pdf2docx" ] && [ ! -L "${pipx_home}/venvs/pdf2docx" ] ||
  { printf "%s\n" "Digital Assets pdf2docx environment is missing or symbolic" >&2; exit 1; }
[ -d "${pipx_home}/venvs/pdf2docx/bin" ] && [ ! -L "${pipx_home}/venvs/pdf2docx/bin" ] ||
  { printf "%s\n" "Digital Assets pdf2docx bin directory is missing or symbolic" >&2; exit 1; }
[ -x "$python" ] ||
  { printf "%s\n" "Digital Assets pdf2docx Python interpreter is missing or not executable" >&2; exit 1; }

unsafe_node=$(
  /usr/bin/find "$root" -xdev \( ! -type d -a ! -type f -a ! -type l \) -print -quit
) || {
  printf "%s\n" "Digital Assets Python node inspection failed" >&2
  exit 1
}
[ -z "$unsafe_node" ] || {
  printf "%s\n" "Digital Assets Python environment contains an unsupported filesystem node" >&2
  exit 1
}
unsafe_link=$(
  /usr/bin/find "$root" -xdev -type l \
    ! -exec /bin/sh -eu -c '"'"'
root=$1
shift
for link_path; do
  [ -L "$link_path" ] || exit 1
  resolved_path=$(/usr/bin/readlink -f -- "$link_path") || exit 1
  case "$resolved_path" in
    "$root"/*|/usr/bin/python3|/usr/bin/python3.[0-9]*) ;;
    *) exit 1 ;;
  esac
done
'"'"' sh "$root" {} \; -print -quit
) || {
  printf "%s\n" "Digital Assets Python symbolic-link inspection failed" >&2
  exit 1
}
[ -z "$unsafe_link" ] || {
  printf "%s\n" "Digital Assets Python environment has an unsafe symbolic-link target" >&2
  exit 1
}

/usr/bin/find "$root" -xdev -type d -exec /usr/bin/chown root:root {} +
/usr/bin/find "$root" -xdev -type f -exec /usr/bin/chown root:root {} +
/usr/bin/find "$root" -xdev -type l -exec /usr/bin/chown -h root:root {} +
/usr/bin/find "$root" -xdev -type d -exec /usr/bin/chmod 0755 {} +
/usr/bin/find "$root" -xdev -type f -exec /usr/bin/chmod u-s,g-s,go-w {} +

unsafe_path=$(
  /usr/bin/find "$root" -xdev \( -type d -o -type f \) \
    \( ! -user root -o ! -group root -o -perm /022 -o -perm /6000 \) -print -quit
) || {
  printf "%s\n" "Digital Assets Python ownership inspection failed" >&2
  exit 1
}
[ -z "$unsafe_path" ] || {
  printf "%s\n" "Digital Assets Python environment has unsafe ownership or permissions" >&2
  exit 1
}
unsafe_link_owner=$(
  /usr/bin/find "$root" -xdev -type l \
    \( ! -user root -o ! -group root \) -print -quit
) || {
  printf "%s\n" "Digital Assets Python symbolic-link ownership inspection failed" >&2
  exit 1
}
[ -z "$unsafe_link_owner" ] || {
  printf "%s\n" "Digital Assets Python environment has unsafe symbolic-link ownership" >&2
  exit 1
}

resolved_python=$(/usr/bin/readlink -f -- "$python") || exit 1
case "$resolved_python" in
  /usr/bin/python3|/usr/bin/python3.[0-9]*) ;;
  *)
    printf "%s\n" "Digital Assets Python interpreter does not resolve to the managed system Python" >&2
    exit 1
    ;;
esac
' sh \
    "$digital_assets_root" \
    "$digital_assets_pipx_home" \
    "$digital_assets_pipx_bin_dir" \
    "$digital_assets_pipx_man_dir" \
    "$digital_assets_python"
}

desktop_digital_assets_install_python_tools() {
  desktop_digital_assets_validate_policy

  digital_assets_root=/usr/local/lib/digital-assets
  digital_assets_pipx_home="${digital_assets_root}/pipx"
  digital_assets_pipx_bin_dir="${digital_assets_root}/bin"
  digital_assets_pipx_man_dir="${digital_assets_root}/man"
  digital_assets_build_home="${digital_assets_root}/.pipx-build-home"
  digital_assets_build_account=installer-pipx-build
  digital_assets_python="${digital_assets_pipx_home}/venvs/pdf2docx/bin/python"

  for digital_assets_path in \
    "$digital_assets_root" \
    "$digital_assets_pipx_home" \
    "$digital_assets_pipx_bin_dir" \
    "$digital_assets_pipx_man_dir" \
    "$digital_assets_build_home"
  do
    [ ! -L "/target${digital_assets_path}" ] ||
      desktop_digital_assets_fail "managed Digital Assets path must not be a symbolic link: ${digital_assets_path}"
  done

  install -d -m 0755 \
    "/target${digital_assets_root}" \
    "/target${digital_assets_pipx_home}" \
    "/target${digital_assets_pipx_bin_dir}" \
    "/target${digital_assets_pipx_man_dir}" \
    "/target${digital_assets_build_home}"
  desktop_transient_pipx_build_account_prepare \
    "$digital_assets_build_account" \
    "$digital_assets_build_home" \
    "$digital_assets_pipx_home" \
    "$digital_assets_pipx_bin_dir" \
    "$digital_assets_pipx_man_dir"

  # Build as a dedicated non-login account, not as installer root or the
  # eventual desktop account. It receives a private build home while the
  # root-owned sealing step makes the shared runtime immutable before first
  # login.
  if ! attempt_in_target "install pinned PDF conversion tools with pipx" \
    /usr/bin/timeout \
      --signal=TERM \
      --kill-after=15s \
      900s \
      /usr/sbin/runuser \
        -u "$digital_assets_build_account" \
        -- \
        /usr/bin/env -i \
          HOME="$digital_assets_build_home" \
          USER="$digital_assets_build_account" \
          LOGNAME="$digital_assets_build_account" \
          PATH=/usr/local/bin:/usr/bin:/bin \
          TMPDIR="$digital_assets_build_home/tmp" \
          XDG_CACHE_HOME="$digital_assets_build_home/cache" \
          XDG_CONFIG_HOME="$digital_assets_build_home/config" \
          XDG_DATA_HOME="$digital_assets_build_home/data" \
          XDG_STATE_HOME="$digital_assets_build_home/state" \
          PIPX_HOME="$digital_assets_pipx_home" \
          PIPX_BIN_DIR="$digital_assets_pipx_bin_dir" \
          PIPX_MAN_DIR="$digital_assets_pipx_man_dir" \
          PIPX_DEFAULT_PYTHON=/usr/bin/python3 \
          PIP_CONFIG_FILE=/dev/null \
          PIP_DISABLE_PIP_VERSION_CHECK=1 \
          PIP_NO_CACHE_DIR=1 \
          PIP_NO_INPUT=1 \
          PYTHONNOUSERSITE=1 \
          PIP_DEFAULT_TIMEOUT=30 \
          PIP_RETRIES=3 \
          /usr/bin/pipx \
            install \
            --force \
            --python /usr/bin/python3 \
            "pdf2docx==0.5.13"
  then
    desktop_digital_assets_fail "pdf2docx pipx installation failed or timed out"
  fi

  if ! attempt_in_target "inject pinned PyMuPDF4LLM into PDF conversion tools" \
    /usr/bin/timeout \
      --signal=TERM \
      --kill-after=15s \
      900s \
      /usr/sbin/runuser \
        -u "$digital_assets_build_account" \
        -- \
        /usr/bin/env -i \
          HOME="$digital_assets_build_home" \
          USER="$digital_assets_build_account" \
          LOGNAME="$digital_assets_build_account" \
          PATH=/usr/local/bin:/usr/bin:/bin \
          TMPDIR="$digital_assets_build_home/tmp" \
          XDG_CACHE_HOME="$digital_assets_build_home/cache" \
          XDG_CONFIG_HOME="$digital_assets_build_home/config" \
          XDG_DATA_HOME="$digital_assets_build_home/data" \
          XDG_STATE_HOME="$digital_assets_build_home/state" \
          PIPX_HOME="$digital_assets_pipx_home" \
          PIPX_BIN_DIR="$digital_assets_pipx_bin_dir" \
          PIPX_MAN_DIR="$digital_assets_pipx_man_dir" \
          PIPX_DEFAULT_PYTHON=/usr/bin/python3 \
          PIP_CONFIG_FILE=/dev/null \
          PIP_DISABLE_PIP_VERSION_CHECK=1 \
          PIP_NO_CACHE_DIR=1 \
          PIP_NO_INPUT=1 \
          PYTHONNOUSERSITE=1 \
          PIP_DEFAULT_TIMEOUT=30 \
          PIP_RETRIES=3 \
          /usr/bin/pipx \
            inject \
            --force \
            pdf2docx \
            "pymupdf4llm==1.28.0"
  then
    desktop_digital_assets_fail "pymupdf4llm pipx injection failed or timed out"
  fi

  desktop_transient_pipx_build_account_destroy \
    "$digital_assets_build_account" \
    "$digital_assets_build_home"
  desktop_digital_assets_seal_python_tools \
    "$digital_assets_root" \
    "$digital_assets_pipx_home" \
    "$digital_assets_pipx_bin_dir" \
    "$digital_assets_pipx_man_dir" \
    "$digital_assets_python"

  desktop_log \
    "installed_digital_assets_python_tools build_user=${digital_assets_build_account} runtime_owner=root execution_user=${ACCOUNT_USERNAME} pdf2docx=0.5.13 pymupdf4llm=1.28.0"
}

desktop_install_digital_assets() {
  [ -n "${DIGITAL_ASSETS_TARGET_ARCHITECTURE:-}" ] ||
    desktop_digital_assets_preflight_target_architecture

  desktop_digital_assets_install_release_tool \
    pdfcpu \
    0.13.0 \
    "$DIGITAL_ASSETS_PDFCPU_URL" \
    "$DIGITAL_ASSETS_PDFCPU_SHA256" \
    1000000 \
    67108864 \
    268435456 \
    128 \
    version
  desktop_digital_assets_install_release_tool \
    typst \
    0.15.1 \
    "$DIGITAL_ASSETS_TYPST_URL" \
    "$DIGITAL_ASSETS_TYPST_SHA256" \
    1000000 \
    134217728 \
    536870912 \
    256 \
    --version
  desktop_digital_assets_install_python_tools
}
