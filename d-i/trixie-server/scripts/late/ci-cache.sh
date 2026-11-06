#!/bin/sh
set -eu
umask 077

source_dir=${1:-}
target=${2:-/target}
shift 2 || true
[ -d "$source_dir" ] && [ -d "$target" ] || { printf '%s\n' 'fatal: CI cache stage paths are unavailable' >&2; exit 1; }
# shellcheck disable=SC1090
. "$source_dir/hosts/profiles/shared-srv.env"
# shellcheck disable=SC1090
. "$source_dir/scripts/common/credentials.sh"
# shellcheck disable=SC1090
. "$source_dir/scripts/common/validate.sh"

podman_tls_passphrase=$(server_credential_read podman_tls_passphrase) || {
  server_fatal 'PRESEED_PODMAN_TLS_PASSPHRASE is required when a runner class is selected'; exit 1;
}
case "$podman_tls_passphrase" in *[![:print:]]*) server_fatal 'Podman TLS passphrase contains control characters'; exit 1 ;; esac

install_asset() {
  relative=$1
  destination=$2
  mode=$3
  source_path="$source_dir/$relative"
  target_path="$target/$destination"
  [ -f "$source_path" ] && [ ! -L "$source_path" ] || { server_fatal "missing CI asset: $relative"; exit 1; }
  install -d -m 0755 "${target_path%/*}"
  install -m "$mode" "$source_path" "$target_path"
}

install_asset hooks/target/etc/sysusers.d/90-ci-runners.conf etc/sysusers.d/90-ci-runners.conf 0644
install_asset hooks/target/etc/tmpfiles.d/90-ci-runners.conf etc/tmpfiles.d/90-ci-runners.conf 0644
install_asset hooks/target/etc/subuid etc/subuid 0644
install_asset hooks/target/etc/subgid etc/subgid 0644
install_asset hooks/target/usr/local/libexec/ci-runner usr/local/libexec/ci-runner 0755
install_asset hooks/target/etc/system-config/ci-runners/buildbuddy.yaml.tmpl etc/system-config/ci-runners/buildbuddy.yaml.tmpl 0640
install -d -m 0755 "$target/etc/system-config/ci-runners"
marker="$target/etc/system-config/ci-runners/enabled"
[ -f "$marker" ] || : >"$marker"
chmod 0640 "$marker"

# All persistent runner roots are created during the selected class stage.
# No systemd unit performs installation work at service start.
for kind in "$@"; do
  case "$kind" in github|gitlab) ;; *) server_fatal 'invalid CI runner class'; exit 1 ;; esac
  user=github-runner
  [ "$kind" = gitlab ] && user=gitlab-runner
  build_root="$target/pool/build/runners/$kind"
  cache_root="$target/pool/cache/runners/$kind"
  db_root="$target/pool/db/runners/$kind"
  podman_root="$target/pool/podman/runners/$kind"
  runtime_root="$target/run/ci-runners/$kind"
  install -d -m 0750 "$build_root" "$cache_root" "$db_root" "$podman_root"
  install -d -m 0710 "$runtime_root"
  install -d -m 0700 \
    "$cache_root/compiler/c" "$cache_root/compiler/cpp" "$cache_root/compiler/ccache" "$cache_root/compiler/sccache" \
    "$cache_root/rust/cargo" "$cache_root/go/build" "$cache_root/go/module" \
    "$cache_root/python/pip" "$cache_root/node/npm" "$cache_root/node/yarn" "$cache_root/node/pnpm" \
    "$cache_root/jvm/maven" "$cache_root/jvm/gradle" "$cache_root/dotnet/nuget" "$cache_root/php/composer" \
    "$cache_root/swift/spm" "$cache_root/haskell/cabal" "$cache_root/haskell/stack" \
    "$cache_root/elixir/hex" "$cache_root/elixir/mix" "$cache_root/erlang/rebar3" \
    "$cache_root/scala/coursier" "$cache_root/scala/sbt/ivy2" "$cache_root/scala/sbt/global" \
    "$cache_root/dart/pub" "$cache_root/zig/global" "$cache_root/zig/local" "$cache_root/julia/depot" \
    "$cache_root/r/library" "$cache_root/ruby/bundle" "$cache_root/perl/cpan" \
    "$cache_root/hashicorp/terraform/plugins" "$cache_root/ansible/galaxy" \
    "$cache_root/bazel/disk" "$cache_root/bazel/repository"
  install -d -m 0700 \
    "$build_root/work" "$build_root/rust/target" "$build_root/go/workspace" "$build_root/python/venv" \
    "$build_root/ansible/work" "$build_root/bazel/output" \
    "$cache_root/runner-cache" \
    "$target/pool/podman/users/$user" "$target/pool/podman/users/$user/runner" \
    "$target/pool/podman/users/$user/data" "$target/pool/podman/users/$user/cache" \
    "$db_root/rust/rustup" "$db_root/ansible" "$db_root/bazel/home" \
    "$podman_root/storage" "$podman_root/runroot" "$podman_root/tmp" "$podman_root/libpod" \
    "$podman_root/volumes" "$podman_root/networks"
done

buildbuddy_root="$target/pool/db/buildbuddy"
buildbuddy_cache="$target/pool/cache/buildbuddy"
buildbuddy_home="$target/pool/podman/users/buildbuddy"
buildbuddy_runtime="$target/run/buildbuddy"
install -d -m 0750 "$buildbuddy_root" "$buildbuddy_root/storage" "$buildbuddy_root/tmp" "$buildbuddy_cache" \
  "$buildbuddy_home" "$buildbuddy_home/data" "$buildbuddy_home/cache" "$buildbuddy_runtime"
architecture=$(chroot "$target" /usr/bin/dpkg --print-architecture 2>/dev/null || true)
case "$architecture" in
  amd64) buildbuddy_url=$BUILDBUDDY_URL_AMD64 ;;
  arm64) buildbuddy_url=$BUILDBUDDY_URL_ARM64 ;;
  *) server_fatal "unsupported architecture for BuildBuddy: ${architecture:-unknown}"; exit 1 ;;
esac
buildbuddy_tmp="$buildbuddy_root/.buildbuddy.$$"
/usr/bin/curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 --max-time 300 --output "$buildbuddy_tmp" "$buildbuddy_url"
install -m 0755 "$buildbuddy_tmp" "$target/usr/local/libexec/buildbuddy"
rm -f "$buildbuddy_tmp"
server_render_template \
  "$source_dir/hooks/target/etc/system-config/ci-runners/buildbuddy.yaml.tmpl" \
  "$target/etc/system-config/ci-runners/buildbuddy.yaml" 0640 \
  BUILDBUDDY_LISTEN "$BUILDBUDDY_LISTEN" \
  BUILDBUDDY_HTTP_PORT "$BUILDBUDDY_HTTP_PORT" \
  BUILDBUDDY_STATE_ROOT "$BUILDBUDDY_STATE_ROOT" \
  BUILDBUDDY_CACHE_ROOT "$BUILDBUDDY_CACHE_ROOT"
install_asset hooks/target/etc/systemd/system/ci-buildbuddy.service etc/systemd/system/ci-buildbuddy.service 0644
if [ -x "$target/usr/bin/systemd-sysusers" ]; then
  chroot "$target" /usr/bin/systemd-sysusers /etc/sysusers.d/90-ci-runners.conf
fi
if [ -x "$target/usr/bin/systemd-tmpfiles" ]; then
  chroot "$target" /usr/bin/systemd-tmpfiles --create /etc/tmpfiles.d/90-ci-runners.conf
fi
if [ -x "$target/usr/bin/chown" ]; then
  chroot "$target" /usr/bin/chown -R buildbuddy:buildbuddy \
    "/pool/db/buildbuddy" "/pool/cache/buildbuddy" "/pool/podman/users/buildbuddy" "/run/buildbuddy"
  chroot "$target" /usr/bin/chown buildbuddy:buildbuddy "/etc/system-config/ci-runners/buildbuddy.yaml"
fi

for kind in "$@"; do
  case "$kind" in github|gitlab) ;; *) server_fatal 'invalid CI runner class'; exit 1 ;; esac
  user=github-runner
  [ "$kind" = gitlab ] && user=gitlab-runner
  buildbuddy_remote_cache=$BUILDBUDDY_REMOTE_CACHE_HOST
  [ "$kind" = gitlab ] && buildbuddy_remote_cache=$BUILDBUDDY_REMOTE_CACHE_CONTAINER
  install_asset "hooks/target/etc/systemd/system/ci-$kind-runner.service" "etc/systemd/system/ci-$kind-runner.service" 0644
  install_asset "hooks/target/etc/systemd/system/ci-$kind-podman.service" "etc/systemd/system/ci-$kind-podman.service" 0644
  install_asset "hooks/target/etc/systemd/system/ci-$kind-podman.socket" "etc/systemd/system/ci-$kind-podman.socket" 0644
  install_asset "hooks/target/etc/system-config/ci-runners/podman/$kind/containers.conf" "etc/system-config/ci-runners/podman/$kind/containers.conf" 0644
  install_asset "hooks/target/etc/system-config/ci-runners/podman/$kind/storage.conf" "etc/system-config/ci-runners/podman/$kind/storage.conf" 0644
  install_asset "hooks/target/etc/system-config/ci-runners/podman/$kind/registries.conf" "etc/system-config/ci-runners/podman/$kind/registries.conf" 0644
  install_asset hooks/target/etc/system-config/ci-runners/podman/registry-tls.env.tmpl \
    "etc/system-config/ci-runners/podman/$kind/registry-tls.env.tmpl" 0640
  install_asset "hooks/target/etc/nftables.d/92-ci-$kind.nft" "etc/nftables.d/92-ci-$kind.nft" 0644
  for shell_name in .profile .bash_profile .bashrc; do
    install_asset "hooks/target/etc/skel-$kind/$shell_name" "etc/skel-$kind/$shell_name" 0644
  done
  install_asset hooks/target/etc/system-config/ci-runners/toolchain.env.tmpl etc/system-config/ci-runners/toolchain.env.tmpl 0640
  install_asset hooks/target/etc/system-config/ci-runners/bazelrc.tmpl etc/system-config/ci-runners/bazelrc.tmpl 0640
  if [ "$kind" = gitlab ]; then
    install_asset hooks/target/etc/system-config/ci-runners/gitlab/config.toml.tmpl etc/system-config/ci-runners/gitlab/config.toml.tmpl 0640
  fi
  grep -Fxq "$kind" "$marker" || printf '%s\n' "$kind" >>"$marker"

  build_root=/pool/build/runners/$kind
  cache_root=/pool/cache/runners/$kind
  db_root=/pool/db/runners/$kind
  home_root=/pool/podman/users/$user
  runtime_root=/run/ci-runners/$kind
  install -d -m 0700 "$target/etc/system-config/ci-runners/podman/$kind"
  printf '%s\n' "$podman_tls_passphrase" >"$target/etc/system-config/ci-runners/podman/$kind/tls-passphrase"
  chmod 0600 "$target/etc/system-config/ci-runners/podman/$kind/tls-passphrase"
  server_render_template \
    "$source_dir/hooks/target/etc/system-config/ci-runners/podman/registry-tls.env.tmpl" \
    "$target/etc/system-config/ci-runners/podman/$kind/registry-tls.env" 0640 \
    KIND "$kind" HOME_ROOT "$home_root"
  server_render_template \
    "$source_dir/hooks/target/etc/system-config/ci-runners/toolchain.env.tmpl" \
    "$target/etc/system-config/ci-runners/$kind.toolchain.env" 0640 \
    KIND "$kind" BUILD_ROOT "$build_root" CACHE_ROOT "$cache_root" DB_ROOT "$db_root" \
    PODMAN_ROOT "/pool/podman/runners/$kind" HOME_ROOT "$home_root" RUNTIME_ROOT "$runtime_root" \
    BUILDBUDDY_REMOTE_CACHE "$buildbuddy_remote_cache"
  server_render_template \
    "$source_dir/hooks/target/etc/system-config/ci-runners/bazelrc.tmpl" \
    "$target/etc/system-config/ci-runners/$kind.bazelrc" 0640 \
    BUILD_ROOT "$build_root" CACHE_ROOT "$cache_root" \
    BAZEL_REPOSITORY_DOWNLOADER_RETRIES "$BAZEL_REPOSITORY_DOWNLOADER_RETRIES" \
    BAZEL_SERVER_IDLE_SECONDS "$BAZEL_SERVER_IDLE_SECONDS" \
    BUILDBUDDY_REMOTE_CACHE "$buildbuddy_remote_cache"
  if [ "$kind" = github ]; then
    server_render_template \
      "$source_dir/hooks/target/etc/system-config/ci-runners/bazelrc.tmpl" \
      "$target/etc/system-config/ci-runners/github-container.bazelrc" 0640 \
      BUILD_ROOT "$build_root" CACHE_ROOT "$cache_root" \
      BAZEL_REPOSITORY_DOWNLOADER_RETRIES "$BAZEL_REPOSITORY_DOWNLOADER_RETRIES" \
      BAZEL_SERVER_IDLE_SECONDS "$BAZEL_SERVER_IDLE_SECONDS" \
      BUILDBUDDY_REMOTE_CACHE "$BUILDBUDDY_REMOTE_CACHE_CONTAINER"
  fi
  if [ -x "$target/usr/bin/chown" ]; then
    chroot "$target" /usr/bin/chown -R "$user:$user" \
      "/pool/build/runners/$kind" "/pool/cache/runners/$kind" "/pool/db/runners/$kind" \
      "/pool/podman/runners/$kind" "/pool/podman/users/$user"
    chroot "$target" /usr/bin/chown "$user:$user" "/run/ci-runners/$kind"
    chroot "$target" /usr/bin/chown "$user:$user" \
      "/etc/system-config/ci-runners/$kind.toolchain.env" "/etc/system-config/ci-runners/$kind.bazelrc"
    if [ "$kind" = github ]; then
      chroot "$target" /usr/bin/chown "$user:$user" \
        "/etc/system-config/ci-runners/github-container.bazelrc"
    fi
    chroot "$target" /usr/bin/chown "$user:$user" \
      "/etc/system-config/ci-runners/podman/$kind/tls-passphrase" \
      "/etc/system-config/ci-runners/podman/$kind/registry-tls.env"
  fi
done

if command -v systemctl >/dev/null 2>&1; then
  systemctl --root="$target" enable ci-buildbuddy.service
  for kind in "$@"; do
    systemctl --root="$target" enable "ci-$kind-podman.socket"
  done
fi
