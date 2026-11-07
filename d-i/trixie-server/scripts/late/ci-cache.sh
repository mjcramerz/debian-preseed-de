#!/bin/sh
set -eu
umask 077

source_dir=${1:-}
target=${2:-/target}
shift 2 || true
[ -d "$source_dir" ] && [ ! -L "$source_dir" ] && [ -d "$target" ] && [ ! -L "$target" ] || {
  printf '%s\n' 'fatal: CI cache stage paths are unavailable' >&2; exit 1;
}
. "$source_dir/repo.env"
. "$source_dir/$DIR_HOSTS_INSTALLER/runtime.env"
. "$source_dir/$DIR_HOSTS_PROFILES/shared-srv.env"
. "$source_dir/$DIR_SCRIPTS_COMMON/validate.sh"

selected=
for kind in "$@"; do
  case "$kind" in github|gitlab) ;; *) server_fatal 'invalid CI runner class'; exit 1 ;; esac
  case " $selected " in *" $kind "*) server_fatal 'duplicate CI runner class'; exit 1 ;; esac
  selected="${selected:+$selected }$kind"
done
[ -n "$selected" ] || { server_fatal 'no CI runner class selected'; exit 1; }

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

append_mapping() {
  file=$1
  line=$2
  install -d -m 0755 "${file%/*}"
  if [ -e "$file" ]; then
    [ -f "$file" ] && [ ! -L "$file" ] || { server_fatal "mapping path is not a regular file: $file"; exit 1; }
    grep -Fqx "$line" "$file" || {
      temporary=$(mktemp "${file}.XXXXXX")
      cat "$file" >"$temporary"
      printf '%s\n' "$line" >>"$temporary"
      chmod 0644 "$temporary"
      mv -f "$temporary" "$file"
    }
  else
    temporary=$(mktemp "${file}.XXXXXX")
    printf '%s\n' "$line" >"$temporary"
    chmod 0644 "$temporary"
    mv -f "$temporary" "$file"
  fi
}

install_asset "$DIR_HOOKS_TARGET/usr/local/libexec/ci-runner" usr/local/libexec/ci-runner 0755
install_asset "$DIR_HOOKS_TARGET/usr/local/libexec/ci-register" usr/local/libexec/ci-register 0755
install -d -m 0750 "$target$SERVER_RUNNER_CONFIG_DIR" "$target$SERVER_CI_REGISTRATION_STATE_DIR"
marker="$target$SERVER_RUNNER_CONFIG_DIR/enabled"
if [ ! -e "$marker" ]; then
  install -m 0640 /dev/null "$marker"
fi

for kind in "$@"; do
  user=github-runner
  [ "$kind" = gitlab ] && user=gitlab-runner
  install_asset "$DIR_HOOKS_TARGET/etc/sysusers.d/90-ci-$kind.conf" "etc/sysusers.d/90-ci-$kind.conf" 0644
  install_asset "$DIR_HOOKS_TARGET/etc/tmpfiles.d/90-ci-$kind.conf" "etc/tmpfiles.d/90-ci-$kind.conf" 0644
  install_asset "$DIR_HOOKS_TARGET/etc/systemd/system/ci-$kind-register.service" "etc/systemd/system/ci-$kind-register.service" 0644
  install_asset "$DIR_HOOKS_TARGET/etc/systemd/system/ci-$kind-runner.service" "etc/systemd/system/ci-$kind-runner.service" 0644
  install_asset "$DIR_HOOKS_TARGET/etc/systemd/system/ci-$kind-podman.service" "etc/systemd/system/ci-$kind-podman.service" 0644
  install_asset "$DIR_HOOKS_TARGET/etc/systemd/system/ci-$kind-podman.socket" "etc/systemd/system/ci-$kind-podman.socket" 0644
  install_asset "$DIR_HOOKS_TARGET/etc/system-config/ci-runners/podman/$kind/containers.conf" "etc/system-config/ci-runners/podman/$kind/containers.conf" 0644
  install_asset "$DIR_HOOKS_TARGET/etc/system-config/ci-runners/podman/$kind/storage.conf" "etc/system-config/ci-runners/podman/$kind/storage.conf" 0644
  install_asset "$DIR_HOOKS_TARGET/etc/system-config/ci-runners/podman/$kind/registries.conf" "etc/system-config/ci-runners/podman/$kind/registries.conf" 0644
  install_asset "$DIR_HOOKS_TARGET/etc/nftables.d/92-ci-$kind.nft" "etc/nftables.d/92-ci-$kind.nft" 0644
  install_asset "$DIR_HOOKS_TARGET/etc/apparmor.d/ci-$kind-runner" "etc/apparmor.d/ci-$kind-runner" 0644
  install_asset "$DIR_HOOKS_TARGET/etc/apparmor.d/ci-$kind-podman" "etc/apparmor.d/ci-$kind-podman" 0644
  install_asset "$DIR_HOOKS_TARGET/etc/skel-$kind/.profile" "etc/skel-$kind/.profile" 0644
  install_asset "$DIR_HOOKS_TARGET/etc/skel-$kind/.bash_profile" "etc/skel-$kind/.bash_profile" 0644
  install_asset "$DIR_HOOKS_TARGET/etc/skel-$kind/.bashrc" "etc/skel-$kind/.bashrc" 0644
  install_asset "$DIR_HOOKS_TARGET/etc/system-config/ci-runners/toolchain.env.tmpl" etc/system-config/ci-runners/toolchain.env.tmpl 0640
  install_asset "$DIR_HOOKS_TARGET/etc/system-config/ci-runners/bazelrc.tmpl" etc/system-config/ci-runners/bazelrc.tmpl 0640
  if [ "$kind" = gitlab ]; then
    install_asset "$DIR_HOOKS_TARGET/etc/system-config/ci-runners/gitlab/config.toml.tmpl" etc/system-config/ci-runners/gitlab/config.toml.tmpl 0640
  fi
  subid_range=$CI_RUNNER_GITLAB_SUBUID
  [ "$kind" = github ] && subid_range=$CI_RUNNER_GITHUB_SUBUID
  append_mapping "$target/etc/subuid" "${user}:$subid_range"
  append_mapping "$target/etc/subgid" "${user}:$subid_range"
  install -d -m 0750 "$target$SERVER_CI_REGISTRATION_STATE_DIR/$kind"
  grep -Fqx "$kind" "$marker" 2>/dev/null || printf '%s\n' "$kind" >>"$marker"
done

install_asset "$DIR_HOOKS_TARGET/etc/sysusers.d/90-ci-buildbuddy.conf" etc/sysusers.d/90-ci-buildbuddy.conf 0644
install_asset "$DIR_HOOKS_TARGET/etc/tmpfiles.d/90-ci-buildbuddy.conf" etc/tmpfiles.d/90-ci-buildbuddy.conf 0644
install_asset "$DIR_HOOKS_TARGET/etc/systemd/system/ci-buildbuddy.service" etc/systemd/system/ci-buildbuddy.service 0644
install_asset "$DIR_HOOKS_TARGET/etc/system-config/ci-runners/buildbuddy.yaml.tmpl" etc/system-config/ci-runners/buildbuddy.yaml.tmpl 0640
architecture=$(chroot "$target" /usr/bin/dpkg --print-architecture 2>/dev/null || true)
case "$architecture" in
  amd64)
    buildbuddy_url=$BUILDBUDDY_URL_AMD64
    buildbuddy_digest=$BUILDBUDDY_SHA256_AMD64
    buildbuddy_identity="buildbuddy-linux-amd64"
    ;;
  arm64)
    buildbuddy_url=$BUILDBUDDY_URL_ARM64
    buildbuddy_digest=$BUILDBUDDY_SHA256_ARM64
    buildbuddy_identity="buildbuddy-linux-arm64"
    ;;
  *) server_fatal "unsupported architecture for BuildBuddy: ${architecture:-unknown}"; exit 1 ;;
esac
server_valid_artifact_url "$buildbuddy_url" "$BUILDBUDDY_ARTIFACT_HOSTS" || {
  server_fatal 'BuildBuddy artifact policy URL is invalid'; exit 1;
}
case "$buildbuddy_url" in *"$buildbuddy_identity") ;; *) server_fatal 'BuildBuddy artifact identity is invalid'; exit 1 ;; esac
buildbuddy_stage=$(mktemp "$target/usr/local/libexec/.buildbuddy.XXXXXX")
cleanup_buildbuddy() { rm -f "$buildbuddy_stage"; }
trap cleanup_buildbuddy EXIT HUP INT TERM
server_download_artifact "$buildbuddy_url" "$buildbuddy_stage" "$BUILDBUDDY_BYTES_MAX" \
  "$BUILDBUDDY_ARTIFACT_HOSTS" || { server_fatal 'BuildBuddy download failed'; exit 1; }
buildbuddy_bytes=$(wc -c <"$buildbuddy_stage")
[ "$buildbuddy_bytes" -ge "$BUILDBUDDY_BYTES_MIN" ] && [ "$buildbuddy_bytes" -le "$BUILDBUDDY_BYTES_MAX" ] || {
  server_fatal 'BuildBuddy size is outside policy'; exit 1;
}
[ "$(/usr/bin/sha256sum "$buildbuddy_stage" | awk '{print $1}')" = "$buildbuddy_digest" ] || {
  server_fatal 'BuildBuddy digest mismatch'; exit 1;
}
install -m 0755 "$buildbuddy_stage" "$target/usr/local/libexec/buildbuddy"
rm -f "$buildbuddy_stage"
trap - EXIT HUP INT TERM
server_render_template "$source_dir/$DIR_HOOKS_TARGET/etc/system-config/ci-runners/buildbuddy.yaml.tmpl" \
  "$target/etc/system-config/ci-runners/buildbuddy.yaml" 0640 \
  BUILDBUDDY_LISTEN "$BUILDBUDDY_LISTEN" BUILDBUDDY_HTTP_PORT "$BUILDBUDDY_HTTP_PORT" \
  BUILDBUDDY_STATE_ROOT "$BUILDBUDDY_STATE_ROOT" BUILDBUDDY_CACHE_ROOT "$BUILDBUDDY_CACHE_ROOT"

if command -v systemctl >/dev/null 2>&1; then
  if [ -x "$target/usr/bin/systemd-sysusers" ]; then
    for kind in "$@"; do chroot "$target" /usr/bin/systemd-sysusers "/etc/sysusers.d/90-ci-$kind.conf"; done
    chroot "$target" /usr/bin/systemd-sysusers /etc/sysusers.d/90-ci-buildbuddy.conf
  fi
  if [ -x "$target/usr/bin/systemd-tmpfiles" ]; then
    for kind in "$@"; do chroot "$target" /usr/bin/systemd-tmpfiles --create "/etc/tmpfiles.d/90-ci-$kind.conf"; done
    chroot "$target" /usr/bin/systemd-tmpfiles --create /etc/tmpfiles.d/90-ci-buildbuddy.conf
  fi
  systemctl --root="$target" enable ci-buildbuddy.service
  for kind in "$@"; do
    systemctl --root="$target" enable "ci-$kind-podman.socket"
    systemctl --root="$target" enable "ci-$kind-register.service"
  done
fi
