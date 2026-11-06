#!/bin/sh
set -eu
umask 077

kind=${1:-}
source_dir=${2:-}
target=${3:-/target}
case "$kind" in github|gitlab) ;; *) printf '%s\n' 'fatal: runner kind must be github or gitlab' >&2; exit 2 ;; esac
[ -d "$source_dir" ] && [ -d "$target" ] || { printf '%s\n' 'fatal: runner stage paths are unavailable' >&2; exit 1; }
# shellcheck disable=SC1090
. "$source_dir/hosts/profiles/shared-srv.env"
# shellcheck disable=SC1090
. "$source_dir/scripts/common/credentials.sh"
# shellcheck disable=SC1090
. "$source_dir/scripts/common/validate.sh"

case "$kind" in
  github)
    runner_user=github-runner
    runner_root=$CI_GITHUB_RUNNER_ROOT
    build_root=$CI_GITHUB_BUILD_ROOT
    cache_root=$CI_GITHUB_CACHE_ROOT
    db_root=$CI_RUNNER_DB_ROOT/github
    runner_template=hooks/target/etc/system-config/ci-runners/github/runner.env.tmpl
    token=$(server_credential_read github_runner_token) || { server_fatal 'GitHub runner token is required'; exit 1; }
    runner_url=$(server_answer_value github_runner_url) || { server_fatal 'github_runner_url installer answer is required'; exit 1; }
    runner_name=$(server_answer_value github_runner_name) || { server_fatal 'github_runner_name installer answer is required'; exit 1; }
    runner_labels=$(server_answer_value github_runner_labels 2>/dev/null || true)
    archive_url=$(server_answer_value github_runner_archive_url) || { server_fatal 'github_runner_archive_url installer answer is required'; exit 1; }
    buildbuddy_remote_cache=$BUILDBUDDY_REMOTE_CACHE_HOST
    ;;
  gitlab)
    runner_user=gitlab-runner
    runner_root=$CI_GITLAB_RUNNER_ROOT
    build_root=$CI_GITLAB_BUILD_ROOT
    cache_root=$CI_GITLAB_CACHE_ROOT
    db_root=$CI_RUNNER_DB_ROOT/gitlab
    runner_template=hooks/target/etc/system-config/ci-runners/gitlab/runner.env.tmpl
    token=$(server_credential_read gitlab_runner_token) || { server_fatal 'GitLab runner token is required'; exit 1; }
    runner_url=$(server_answer_value gitlab_runner_url) || { server_fatal 'gitlab_runner_url installer answer is required'; exit 1; }
    runner_name=$(server_answer_value gitlab_runner_name) || { server_fatal 'gitlab_runner_name installer answer is required'; exit 1; }
    runner_labels=$(server_answer_value gitlab_runner_tags 2>/dev/null || true)
    archive_url=$(server_answer_value gitlab_runner_archive_url) || { server_fatal 'gitlab_runner_archive_url installer answer is required'; exit 1; }
    buildbuddy_remote_cache=$BUILDBUDDY_REMOTE_CACHE_CONTAINER
    ;;
esac

server_valid_https_url "$runner_url" || { server_fatal 'runner URL must be HTTPS'; exit 1; }
server_valid_https_url "$archive_url" || { server_fatal 'runner archive URL must be HTTPS'; exit 1; }
case "$runner_url" in *[![:print:]]*) server_fatal 'runner URL contains control characters'; exit 1 ;; esac
case "$runner_url" in *'"'*) server_fatal 'runner URL contains an unsupported quote'; exit 1 ;; esac
server_valid_identifier "$runner_name" || { server_fatal 'runner name is invalid'; exit 1; }
[ -n "$runner_labels" ] || runner_labels=server
case "$runner_labels" in
  *[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.:,/-]*) server_fatal 'runner labels or tags contain unsupported characters'; exit 1 ;;
esac

runner_root="$target$runner_root"
config_dir="$target/etc/system-config/ci-runners"
install -d -m 0700 "$runner_root"
install -d -m 0755 "$config_dir"
archive="$runner_root/.runner.tar.gz.$$"
/usr/bin/curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 --max-time 300 --output "$archive" "$archive_url"
if tar -tzf "$archive" >/dev/null 2>&1; then
  if tar -tzf "$archive" | awk 'BEGIN {bad=0} /^\// || /(^|\/)\.\.($|\/)/ {bad=1} END {exit bad}'; then
    tar -xzf "$archive" --no-same-owner --no-same-permissions -C "$runner_root"
  else
    rm -f "$archive"
    server_fatal 'runner archive contains an unsafe member path'
    exit 1
  fi
else
  rm -f "$archive"
  server_fatal 'runner archive is not a readable gzip tar archive'
  exit 1
fi
rm -f "$archive"

if [ -x "$target/usr/bin/chown" ]; then
  chroot "$target" /usr/bin/chown -R "$runner_user:$runner_user" "$runner_root"
fi

token_file="$config_dir/$kind.token"
printf '%s\n' "$token" >"$token_file"
chmod 0600 "$token_file"
install -d -m 0750 "$target/etc/system-config/ci-runners/$kind"
install_asset() {
  relative=$1
  destination=$2
  mode=$3
  source_path="$source_dir/$relative"
  target_path="$target/$destination"
  [ -f "$source_path" ] && [ ! -L "$source_path" ] || { server_fatal "missing runner asset: $relative"; exit 1; }
  install -d -m 0755 "${target_path%/*}"
  install -m "$mode" "$source_path" "$target_path"
}
install_asset "$runner_template" "etc/system-config/ci-runners/$kind/runner.env.tmpl" 0640
if [ "$kind" = gitlab ]; then
  install_asset hooks/target/etc/system-config/ci-runners/gitlab/config.toml.tmpl \
    etc/system-config/ci-runners/gitlab/config.toml.tmpl 0640
fi

case "$kind" in
  github)
    server_render_template "$source_dir/$runner_template" "$config_dir/$kind.env" 0600 \
      KIND "$kind" RUNNER_ROOT "${CI_GITHUB_RUNNER_ROOT}" RUNNER_URL "$runner_url" \
      RUNNER_NAME "$runner_name" RUNNER_LABELS "$runner_labels" BUILD_ROOT "$CI_GITHUB_BUILD_ROOT" \
      CACHE_ROOT "$CI_GITHUB_CACHE_ROOT" HOME_ROOT "$CI_GITHUB_HOME" \
      RUNTIME_ROOT "$CI_GITHUB_RUNTIME_DIR" DB_ROOT "$db_root" \
      BUILDBUDDY_REMOTE_CACHE "$buildbuddy_remote_cache"
    ;;
  gitlab)
    server_render_template "$source_dir/$runner_template" "$config_dir/$kind.env" 0600 \
      KIND "$kind" RUNNER_ROOT "${CI_GITLAB_RUNNER_ROOT}" RUNNER_URL "$runner_url" \
      RUNNER_NAME "$runner_name" RUNNER_LABELS "$runner_labels" BUILD_ROOT "$CI_GITLAB_BUILD_ROOT" \
      CACHE_ROOT "$CI_GITLAB_CACHE_ROOT" RUNNER_IMAGE "$CI_GITLAB_RUNNER_IMAGE" \
      RUNNER_PULL_POLICY "$CI_GITLAB_RUNNER_PULL_POLICY" RUNNER_EXECUTOR "$CI_GITLAB_RUNNER_EXECUTOR" \
      HOME_ROOT "$CI_GITLAB_HOME" RUNTIME_ROOT "$CI_GITLAB_RUNTIME_DIR" DB_ROOT "$db_root" \
      BUILDBUDDY_REMOTE_CACHE "$buildbuddy_remote_cache"
    ;;
esac

if [ -x "$target/usr/bin/chown" ]; then
  chroot "$target" /usr/bin/chown "$runner_user:$runner_user" \
    "/etc/system-config/ci-runners/$kind.token" \
    "/etc/system-config/ci-runners/$kind.env" \
    "/etc/system-config/ci-runners/$kind/runner.env.tmpl"
  if [ "$kind" = gitlab ]; then
    chroot "$target" /usr/bin/chown "$runner_user:$runner_user" \
      "/etc/system-config/ci-runners/gitlab" \
      "/etc/system-config/ci-runners/gitlab/config.toml.tmpl"
  fi
fi

if command -v systemctl >/dev/null 2>&1; then
  systemctl --root="$target" enable "ci-${kind}-runner.service"
fi
