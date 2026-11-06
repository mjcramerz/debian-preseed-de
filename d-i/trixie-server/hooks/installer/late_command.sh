#!/bin/sh
set -eu
umask 077

source_dir=${1:-/tmp/server-install}
target=${2:-/target}
[ -r "$source_dir/scripts/late/dispatch.sh" ] || {
  printf '%s\n' 'fatal: Trixie server late dispatcher is unavailable' >&2
  exit 1
}
/bin/sh "$source_dir/scripts/late/dispatch.sh" "$source_dir" "$target"
