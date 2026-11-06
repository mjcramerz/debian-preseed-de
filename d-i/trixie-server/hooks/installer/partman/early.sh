#!/bin/sh
set -eu
umask 077

[ -r /tmp/server-install/scripts/partman/choose-layout.sh ] || {
  printf '%s\n' 'fatal: Trixie server partman selector is unavailable' >&2
  exit 1
}
/bin/sh /tmp/server-install/scripts/partman/choose-layout.sh
