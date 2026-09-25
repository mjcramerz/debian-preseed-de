#!/bin/sh
# First target APT update. Base media may supply debootstrap, but never an
# unauthenticated/obsolete CD-ROM APT source. Keep the BASE suite until apt-setup
# installs the selected mixed-suite policy and preferences.
set -eu
runtime=${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}
. "$runtime/bootstrap/source.sh"
if installer_lifecycle_begin base-network-apt; then :; else
  rc=$?; [ "$rc" -eq 10 ] && exit 0; exit "$rc"
fi
. "$runtime/bootstrap/apt-sources.sh"
. /usr/share/debconf/confmodule
suite=$1
db_get mirror/protocol
protocol=$RET
case "$protocol" in http|https) ;; *) installer_lifecycle_abort 125 base-network-apt 'network Debian mirror is required' ;; esac
db_get "mirror/$protocol/hostname"
host=$RET
db_get "mirror/$protocol/directory"
directory=$RET
installer_apt_bootstrap_source "${INSTALLER_TARGET_DIR:-/target}" "$protocol" "$host" "$directory" "$suite"
printf 'stage=base_install level=info component=network-apt normalized sources before first update suite=%s\n' "$suite" >&2
installer_run_supervised in-target env LC_ALL=C DEBIAN_FRONTEND=noninteractive \
  apt-get -o APT::Update::Error-Mode=any -o Acquire::Retries=3 \
  -o Acquire::http::Timeout=45 -o Acquire::https::Timeout=45 update
installer_lifecycle_complete
