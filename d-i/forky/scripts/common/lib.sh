#!/bin/sh
# Installer common entrypoint. Policy and implementation live beside this file.
# A standalone cached hook may not have sourced bootstrap.sh in this process.
if ! command -v bootstrap_source_module >/dev/null 2>&1; then
  [ -s "${INSTALLER_BOOTSTRAP_LIB:-${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}/bootstrap/bootstrap.sh}" ] || {
    printf '%s\n' 'fatal: installer bootstrap is unavailable; start with preseed.cfg' >&2
    return 1
  }
  # shellcheck disable=SC1090
  . "${INSTALLER_BOOTSTRAP_LIB:-${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}/bootstrap/bootstrap.sh}" || return "$?"
fi

bootstrap_source_module 'scripts/common/debconf.sh' || return "$?"
bootstrap_source_module 'scripts/common/lifecycle.sh' || return "$?"
bootstrap_source_module 'scripts/common/apt-sources.sh' || return "$?"
bootstrap_source_module 'scripts/common/credentials.sh' || return "$?"
bootstrap_source_module 'scripts/common/modules/runtime-console.sh' || return "$?"
bootstrap_source_module 'scripts/common/modules/files-logging.sh' || return "$?"
bootstrap_source_module 'scripts/common/modules/credentials-probes.sh' || return "$?"
bootstrap_source_module 'scripts/common/modules/observability.sh' || return "$?"
bootstrap_source_module 'scripts/common/modules/repository-apt.sh' || return "$?"
bootstrap_source_module 'scripts/common/modules/profiles.sh' || return "$?"
bootstrap_source_module 'scripts/common/modules/class-plan.sh' || return "$?"
bootstrap_source_module 'scripts/common/modules/class-metadata.sh' || return "$?"
bootstrap_source_module 'scripts/common/modules/class-selection.sh' || return "$?"
bootstrap_source_module 'scripts/common/modules/context-target.sh' || return "$?"
