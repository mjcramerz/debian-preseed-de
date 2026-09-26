#!/bin/sh
# Labwc component definitions, loaded in explicit dependency order.
# The late desktop entrypoint has already initialized the shared bootstrap.

bootstrap_source_module 'scripts/desktop/components/stage-assets.sh' || return "$?"
bootstrap_source_module 'scripts/desktop/components/managed-apps.sh' || return "$?"
bootstrap_source_module 'scripts/desktop/components/artifacts-identities.sh' || return "$?"
bootstrap_source_module 'scripts/desktop/components/rendering-access.sh' || return "$?"
bootstrap_source_module 'scripts/desktop/components/devices-network.sh' || return "$?"
bootstrap_source_module 'scripts/desktop/components/desktop-config.sh' || return "$?"
bootstrap_source_module 'scripts/desktop/components/gpg-bootstrap.sh' || return "$?"
bootstrap_source_module 'scripts/desktop/components/user-session.sh' || return "$?"
bootstrap_source_module 'scripts/desktop/components/core-renderers.sh' || return "$?"
bootstrap_source_module 'scripts/desktop/components/desktop-helpers.sh' || return "$?"
bootstrap_source_module 'scripts/desktop/components/logging.sh' || return "$?"
bootstrap_source_module 'scripts/desktop/components/compz.sh' || return "$?"
bootstrap_source_module 'scripts/desktop/components/target-assets.sh' || return "$?"
bootstrap_source_module 'scripts/desktop/components/user-config.sh' || return "$?"
bootstrap_source_module 'scripts/desktop/components/services.sh' || return "$?"
