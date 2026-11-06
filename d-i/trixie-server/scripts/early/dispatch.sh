#!/bin/sh
set -eu
umask 077

source_dir=${1:-/tmp/server-install}
[ -d "$source_dir" ] && [ ! -L "$source_dir" ] || {
  printf '%s\n' 'fatal: server source staging directory is unavailable' >&2
  exit 1
}

# Keep early processing data-only. The late stage owns target mutation.
printf 'server_source_dir=%s\n' "$source_dir" >/tmp/server-install/early-state.env
chmod 0600 /tmp/server-install/early-state.env
