#!/bin/sh
# Shared runtime for both filesystem families; loaded after installer bootstrap.
# Definitions only: sourcing does not partition disks or change configuration.
bootstrap_source_module 'scripts/common/debconf.sh' || return "$?"
bootstrap_source_module 'scripts/common/credentials.sh' || return "$?"
bootstrap_source_module 'scripts/runtime/modules/base.sh' || return "$?"
bootstrap_source_module 'scripts/runtime/modules/classes.sh' || return "$?"
bootstrap_source_module 'scripts/runtime/modules/arithmetic.sh' || return "$?"
bootstrap_source_module 'scripts/runtime/modules/answers.sh' || return "$?"
bootstrap_source_module 'scripts/runtime/modules/identity.sh' || return "$?"
bootstrap_source_module 'scripts/runtime/modules/crypto.sh' || return "$?"
bootstrap_source_module 'scripts/runtime/modules/devices.sh' || return "$?"
bootstrap_source_module 'scripts/runtime/modules/recipes.sh' || return "$?"
