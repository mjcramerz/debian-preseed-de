#!/bin/sh
set -eu
umask 077

[ -r /tmp/server-install/scripts/early/dispatch.sh ] || {
  printf '%s\n' 'fatal: Trixie server early dispatcher is unavailable' >&2
  exit 1
}
/bin/sh /tmp/server-install/scripts/early/dispatch.sh /tmp/server-install
