#!/bin/sh
set -eu
boot=${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}/bootstrap
[ -f "$boot/preflight.ok" ] && [ -x "$boot/preseed-bootstrap-entry.sh" ] || {
  printf '%s\n' 'fatal: repository preflight incomplete before applying answers' >&2
  exit 1
}
exec "$boot/preseed-bootstrap-entry.sh" apply /tmp/installer.log
