#!/bin/sh
set -eu
umask 077

# The preseed transport has already extracted the immutable publication into
# this directory. Bootstrap only validates the staged tree and records its
# local root; it never downloads aliases or consults installation media.
stage=${1:-/tmp/server-install}
[ "$stage" = /tmp/server-install ] || {
  printf '%s\n' 'fatal: unexpected Trixie payload stage' >&2
  exit 1
}
[ -d "$stage" ] && [ ! -L "$stage" ] || {
  printf '%s\n' 'fatal: Trixie payload stage is unavailable' >&2
  exit 1
}

for required in \
  repo.env \
  hosts/installer/account.env \
  hosts/installer/boot.env \
  hosts/installer/btrfs.env \
  hosts/installer/f2fs.env \
  hosts/installer/identity.env \
  hosts/installer/layout.env \
  hosts/installer/runtime.env \
  hosts/profiles/shared-srv.env \
  scripts/common/credentials.sh \
  scripts/common/forky.sh \
  scripts/common/source.sh \
  scripts/common/validate.sh \
  scripts/early/dispatch.sh \
  scripts/partman/choose-layout.sh \
  scripts/late/dispatch.sh \
  ssh/sshd_config \
  ssh/config \
  ssh/lan_ed25519.pub; do
  file="$stage/$required"
  [ -f "$file" ] && [ ! -L "$file" ] || {
    printf 'fatal: Trixie payload file is missing: %s\n' "$required" >&2
    exit 1
  }
done

temporary=$(mktemp "$stage/.server-source.XXXXXX")
trap 'rm -f "$temporary"' EXIT HUP INT TERM
printf 'SERVER_SOURCE_DIR=%s\n' "$stage" >"$temporary"
chmod 0600 "$temporary"
mv -f "$temporary" "$stage/server-source.env"
trap - EXIT HUP INT TERM

