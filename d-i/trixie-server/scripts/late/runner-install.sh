#!/bin/sh
set -eu
umask 077

kind=${1:-}
source_dir=${2:-}
target=${3:-/target}
case "$kind" in github|gitlab) ;; *) printf '%s\n' 'fatal: runner kind must be github or gitlab' >&2; exit 2 ;; esac
[ -d "$source_dir" ] && [ ! -L "$source_dir" ] && [ -d "$target" ] && [ ! -L "$target" ] || {
  printf '%s\n' 'fatal: runner stage paths are unavailable' >&2; exit 1;
}
. "$source_dir/repo.env"
. "$source_dir/$DIR_HOSTS_INSTALLER/runtime.env"
. "$source_dir/$DIR_HOSTS_PROFILES/shared-srv.env"
. "$source_dir/$DIR_SCRIPTS_COMMON/credentials.sh"
. "$source_dir/$DIR_SCRIPTS_COMMON/validate.sh"

architecture=$(chroot "$target" /usr/bin/dpkg --print-architecture 2>/dev/null || true)
case "$architecture" in amd64|arm64) ;; *) server_fatal "unsupported runner architecture: ${architecture:-unknown}"; exit 1 ;; esac

case "$kind" in
  github)
    runner_user=github-runner
    runner_root=$CI_GITHUB_RUNNER_ROOT
    build_root=$CI_GITHUB_BUILD_ROOT
    cache_root=$CI_GITHUB_CACHE_ROOT
    db_root=$CI_RUNNER_DB_ROOT/github
    runtime_root=$CI_GITHUB_RUNTIME_DIR
    allowed_hosts=github.com
    artifact_hosts=$CI_GITHUB_RUNNER_ARTIFACT_HOSTS
    endpoint=$(server_answer_value github_runner_url 2>/dev/null || true)
    name=$(server_answer_value github_runner_name 2>/dev/null || true)
    labels=$(server_answer_value github_runner_labels 2>/dev/null || true)
    token=$(server_credential_read github_runner_token) || { server_fatal 'GitHub runner token is required'; exit 1; }
    format=$CI_GITHUB_RUNNER_FORMAT
    version=$CI_GITHUB_RUNNER_VERSION
    case "$architecture" in
      amd64)
        artifact_url=$CI_GITHUB_RUNNER_URL_AMD64
        artifact_digest=$CI_GITHUB_RUNNER_SHA256_AMD64
        artifact_identity="actions-runner-linux-x64-$version.tar.gz"
        ;;
      arm64)
        artifact_url=$CI_GITHUB_RUNNER_URL_ARM64
        artifact_digest=$CI_GITHUB_RUNNER_SHA256_ARM64
        artifact_identity="actions-runner-linux-arm64-$version.tar.gz"
        ;;
    esac
    home_root=$CI_GITHUB_HOME
    artifact_min=$CI_GITHUB_RUNNER_BYTES_MIN
    artifact_max=$CI_GITHUB_RUNNER_BYTES_MAX
    artifact_root="$SERVER_CI_ARTIFACT_ROOT/ci-github-runner"
    runner_template="$DIR_HOOKS_TARGET/etc/system-config/ci-runners/github/runner.env.tmpl"
    ;;
  gitlab)
    runner_user=gitlab-runner
    runner_root=$CI_GITLAB_RUNNER_ROOT
    build_root=$CI_GITLAB_BUILD_ROOT
    cache_root=$CI_GITLAB_CACHE_ROOT
    db_root=$CI_RUNNER_DB_ROOT/gitlab
    runtime_root=$CI_GITLAB_RUNTIME_DIR
    allowed_hosts=$CI_GITLAB_ALLOWED_HOSTS
    artifact_hosts=$CI_GITLAB_RUNNER_ARTIFACT_HOSTS
    endpoint=$(server_answer_value gitlab_runner_url 2>/dev/null || true)
    name=$(server_answer_value gitlab_runner_name 2>/dev/null || true)
    labels=$(server_answer_value gitlab_runner_tags 2>/dev/null || true)
    token=$(server_credential_read gitlab_runner_token) || { server_fatal 'GitLab runner token is required'; exit 1; }
    format=$CI_GITLAB_RUNNER_FORMAT
    version=$CI_GITLAB_RUNNER_VERSION
    case "$architecture" in
      amd64)
        artifact_url=$CI_GITLAB_RUNNER_URL_AMD64
        artifact_digest=$CI_GITLAB_RUNNER_SHA256_AMD64
        artifact_identity="gitlab-runner-linux-amd64"
        ;;
      arm64)
        artifact_url=$CI_GITLAB_RUNNER_URL_ARM64
        artifact_digest=$CI_GITLAB_RUNNER_SHA256_ARM64
        artifact_identity="gitlab-runner-linux-arm64"
        ;;
    esac
    home_root=$CI_GITLAB_HOME
    artifact_min=$CI_GITLAB_RUNNER_BYTES_MIN
    artifact_max=$CI_GITLAB_RUNNER_BYTES_MAX
    artifact_root="$SERVER_CI_ARTIFACT_ROOT/ci-gitlab-runner"
    runner_template="$DIR_HOOKS_TARGET/etc/system-config/ci-runners/gitlab/runner.env.tmpl"
    ;;
esac

server_valid_runner_url "$endpoint" "$allowed_hosts" || { server_fatal 'runner endpoint is not an approved canonical HTTPS URL'; exit 1; }
server_valid_runner_name "$name" || { server_fatal 'runner name is invalid'; exit 1; }
[ -n "$labels" ] || labels=server
server_valid_runner_labels "$labels" || { server_fatal 'runner labels or tags are invalid'; exit 1; }
if [ "$kind" = gitlab ]; then
  [ "$CI_GITLAB_RUNNER_EXECUTOR" = docker ] || { server_fatal 'GitLab executor policy is invalid'; exit 1; }
  server_valid_runner_image "$CI_GITLAB_RUNNER_IMAGE" "$CI_GITLAB_APPROVED_REGISTRIES" || {
    server_fatal 'GitLab job image policy is not an approved immutable image'; exit 1;
  }
  server_valid_runner_pull_policy "$CI_GITLAB_RUNNER_PULL_POLICY" || {
    server_fatal 'GitLab image pull policy is invalid'; exit 1;
  }
fi
server_valid_artifact_url "$artifact_url" "$artifact_hosts" || { server_fatal 'runner artifact policy URL is invalid'; exit 1; }
case "$artifact_url" in *"$artifact_identity") ;; *) server_fatal 'runner artifact identity does not match the selected release policy'; exit 1 ;; esac
printf '%s\n' "$artifact_digest" | grep -Eq '^[0-9a-f]{64}$' || { server_fatal 'runner artifact digest policy is invalid'; exit 1; }
case "$format" in tar.gz|elf) ;; *) server_fatal 'runner artifact format is not supported'; exit 1 ;; esac

config_dir="$target$SERVER_RUNNER_CONFIG_DIR"
handoff="$config_dir/.${kind}.registration"
install -d -m 0750 "$config_dir/$kind" "$target/usr/local/libexec" "$target/usr/local/libexec/.staging"
tmp=$(mktemp "$target/usr/local/libexec/.staging/${kind}.XXXXXX")
cleanup_runner_install() { rm -f "$tmp"; }
trap cleanup_runner_install EXIT HUP INT TERM
server_download_artifact "$artifact_url" "$tmp" "$artifact_max" "$artifact_hosts" || {
  server_fatal 'runner artifact download failed'; exit 1;
}
bytes=$(wc -c <"$tmp")
[ "$bytes" -ge "$artifact_min" ] && [ "$bytes" -le "$artifact_max" ] || {
  server_fatal 'runner artifact size is outside policy'; exit 1;
}
actual_digest=$(/usr/bin/sha256sum "$tmp" | awk '{print $1}')
[ "$actual_digest" = "$artifact_digest" ] || { server_fatal 'runner artifact digest mismatch'; exit 1; }

if [ "$format" = tar.gz ]; then
  release_stage=$(mktemp -d "$target/usr/local/libexec/.staging/${kind}.release.XXXXXX")
  publish_stage=$(mktemp -d "$target/usr/local/libexec/.staging/${kind}.publish.XXXXXX")
  cleanup_runner_install() { rm -f "$tmp"; rm -rf "$release_stage" "$publish_stage"; }
  trap cleanup_runner_install EXIT HUP INT TERM
  tar -tzf "$tmp" >"$release_stage/members" || { server_fatal 'runner archive is not a readable gzip tar archive'; exit 1; }
  awk 'BEGIN { count = 0 } {
    count++
    if ($0 ~ /^\// || $0 ~ /(^|\/)\.\.($|\/)/ || $0 ~ /(^|\/)\.(\.|$)/ ||
        $0 ~ /[^ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._\/+@-]/ || length($0) > 240) exit 2
  } END { if (count == 0 || count > 4096) exit 3 }' "$release_stage/members" || {
    server_fatal 'runner archive contains unsafe or excessive members'; exit 1;
  }
  if LC_ALL=C sort "$release_stage/members" | uniq -d | grep -q .; then
    server_fatal 'runner archive contains duplicate members'; exit 1;
  fi
  tar -tvzf "$tmp" >"$release_stage/details" || { server_fatal 'runner archive details are unavailable'; exit 1; }
  awk 'BEGIN { count = 0; expanded = 0 }
    {
      type = substr($1, 1, 1)
      if (type != "-" && type != "d") exit 2
      count++
      if (type == "-") {
        if ($3 !~ /^[0-9]+$/) exit 3
        expanded += $3
        if (expanded > 268435456) exit 4
      }
    }
    END { if (count == 0 || count > 4096) exit 5 }' "$release_stage/details" || {
    server_fatal 'runner archive contains unsupported members or exceeds extraction limits'; exit 1;
  }
  tar -xzf "$tmp" --no-same-owner --no-same-permissions --no-acls --no-xattrs -C "$release_stage" || {
    server_fatal 'runner archive extraction failed'; exit 1;
  }
  [ -x "$release_stage/config.sh" ] && [ -x "$release_stage/run.sh" ] || {
    server_fatal 'GitHub runner archive layout is not the pinned contract'; exit 1;
  }
  install -m 0755 "$release_stage/config.sh" "$publish_stage/config.sh"
  install -m 0755 "$release_stage/run.sh" "$publish_stage/run.sh"
  old_ifs=$IFS
  IFS=,
  # shellcheck disable=SC2086
  set -- $CI_GITHUB_RUNNER_TOP_LEVEL
  IFS=$old_ifs
  [ "$#" -gt 0 ] || { server_fatal 'GitHub runner top-level policy is empty'; exit 1; }
  for child in "$@"; do
    case "$child" in
      ''|*/*|*..*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-]*)
        server_fatal 'GitHub runner top-level policy is invalid'; exit 1 ;;
    esac
    [ -d "$release_stage/$child" ] || { server_fatal "GitHub runner archive lacks $child"; exit 1; }
    cp -a --no-preserve=ownership "$release_stage/$child" "$publish_stage/"
  done
  [ ! -e "$target$artifact_root" ] && [ ! -L "$target$artifact_root" ] || {
    server_fatal 'verified GitHub runner release path already exists'; exit 1;
  }
  mv -f "$publish_stage" "$target$artifact_root"
  publish_stage=
else
  elf_header=$(od -An -N 6 -t x1 "$tmp" 2>/dev/null | tr -d ' \n')
  elf_machine=$(od -An -j 18 -N 2 -t x1 "$tmp" 2>/dev/null | tr -d ' \n')
  [ "$elf_header" = 7f454c460201 ] || { server_fatal 'GitLab runner artifact is not a 64-bit Linux ELF'; exit 1; }
  case "$architecture:$elf_machine" in
    amd64:3e00|arm64:b700) ;;
    *) server_fatal 'GitLab runner artifact architecture does not match the target'; exit 1 ;;
  esac
  [ ! -e "$target$artifact_root" ] && [ ! -L "$target$artifact_root" ] || {
    server_fatal 'verified GitLab runner release path already exists'; exit 1;
  }
  publish_stage=$(mktemp "$target/usr/local/libexec/.staging/${kind}.publish.XXXXXX")
  cleanup_runner_install() { rm -f "$tmp" "$publish_stage"; }
  trap cleanup_runner_install EXIT HUP INT TERM
  install -m 0755 "$tmp" "$publish_stage"
  mv -f "$publish_stage" "$target$artifact_root"
  publish_stage=
  [ -x "$target$artifact_root" ] || { server_fatal 'GitLab runner artifact is not executable'; exit 1; }
fi

rm -f "$tmp"
trap - EXIT HUP INT TERM
if [ "$kind" = gitlab ]; then
  install_asset() {
    relative=$1; destination=$2; mode=$3
    source_path="$source_dir/$relative"; target_path="$target/$destination"
    [ -f "$source_path" ] && [ ! -L "$source_path" ] || { server_fatal "missing runner asset: $relative"; exit 1; }
    install -d -m 0755 "${target_path%/*}"
    install -m "$mode" "$source_path" "$target_path"
  }
  install_asset "$DIR_HOOKS_TARGET/etc/system-config/ci-runners/gitlab/config.toml.tmpl" \
    etc/system-config/ci-runners/gitlab/config.toml.tmpl 0640
fi
install_asset() {
  relative=$1; destination=$2; mode=$3
  source_path="$source_dir/$relative"; target_path="$target/$destination"
  [ -f "$source_path" ] && [ ! -L "$source_path" ] || { server_fatal "missing runner asset: $relative"; exit 1; }
  install -d -m 0755 "${target_path%/*}"
  install -m "$mode" "$source_path" "$target_path"
}
install_asset "$runner_template" "etc/system-config/ci-runners/$kind/runner.env.tmpl" 0640

server_render_template "$source_dir/$runner_template" "$config_dir/$kind.env" 0600 \
  KIND "$kind" RUNNER_ROOT "$runner_root" RUNNER_RELEASE_ROOT "$artifact_root" \
  RUNNER_URL "$endpoint" RUNNER_NAME "$name" RUNNER_LABELS "$labels" \
  BUILD_ROOT "$build_root" CACHE_ROOT "$cache_root" HOME_ROOT "$home_root" \
  RUNTIME_ROOT "$runtime_root" DB_ROOT "$db_root" BUILDBUDDY_REMOTE_CACHE ""

# The installer token is a root-only, one-shot systemd credential handoff. It
# is never part of an EnvironmentFile and is removed by the registration unit.
install -d -m 0700 "$config_dir"
temporary_handoff=$(mktemp "$config_dir/.registration.XXXXXX")
printf '%s\n' "$token" >"$temporary_handoff"
unset token
chmod 0600 "$temporary_handoff"
mv -f "$temporary_handoff" "$handoff"
chown root:root "$handoff" 2>/dev/null || true

if [ "$kind" = gitlab ]; then
  server_render_template "$source_dir/$DIR_HOOKS_TARGET/etc/system-config/ci-runners/gitlab/config.toml.tmpl" \
    "$config_dir/gitlab/config.toml.tmpl" 0640 \
    RUNNER_NAME "$name" RUNNER_URL "$endpoint" RUNNER_EXECUTOR "$CI_GITLAB_RUNNER_EXECUTOR" \
    RUNNER_DOCKER_IMAGE "$CI_GITLAB_RUNNER_IMAGE" RUNNER_DOCKER_PULL_POLICY "$CI_GITLAB_RUNNER_PULL_POLICY" \
    RUNNER_BUILDS_DIR "$build_root/work" RUNNER_CACHE_DIR "$cache_root/runner-cache" \
    RUNNER_DOCKER_HOST "unix://$runtime_root/podman.sock" RUNNER_HOME "$CI_GITLAB_HOME" \
    RUNNER_RUNTIME_DIR "$runtime_root" RUNNER_BUILD_ROOT "$build_root" RUNNER_CACHE_ROOT "$cache_root" \
    RUNNER_DB_ROOT "$db_root" RUNNER_BAZELRC "/etc/system-config/ci-runners/gitlab.bazelrc" \
    RUNNER_BUILDBUDDY_REMOTE_CACHE ""
fi

if command -v systemctl >/dev/null 2>&1; then
  systemctl --root="$target" enable "ci-${kind}-register.service"
  systemctl --root="$target" enable "ci-${kind}-runner.service"
fi
