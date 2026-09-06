#!/bin/sh
set -eu

RUNTIME_DIR=${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}
BOOTSTRAP_LIB=${INSTALLER_BOOTSTRAP_LIB:-${RUNTIME_DIR}/bootstrap/bootstrap.sh}
FIRMWARE_CACHE_DIR=${INSTALLER_FIRMWARE_CACHE_DIR:-/var/cache/firmware}

nvidia_firmware_gate_fatal() {
  printf '[pre-pkgsel:nvidia-firmware-gate] fatal: %s\n' "$*" >&2
  exit 1
}

[ -s "$BOOTSTRAP_LIB" ] ||
  nvidia_firmware_gate_fatal "installer bootstrap library is unavailable: ${BOOTSTRAP_LIB}"
case "$FIRMWARE_CACHE_DIR" in
  /*) ;;
  *) nvidia_firmware_gate_fatal "firmware cache path must be absolute: ${FIRMWARE_CACHE_DIR:-unset}" ;;
esac
[ "$FIRMWARE_CACHE_DIR" != / ] ||
  nvidia_firmware_gate_fatal "refusing to use the installer root as the firmware cache"
# shellcheck disable=SC1090,SC1091
. "$BOOTSTRAP_LIB"
bootstrap_source_common_lib ""

SEED_BASE=$(installer_seed_base "")
installer_persist_seed_source "$SEED_BASE"
installer_ensure_context_loaded "$SEED_BASE"

if installer_nvidia_addon_selected 2>/dev/null &&
   installer_nvidia_gpu_detected 2>/dev/null
then
  installer_info "preserving Debian Installer NVIDIA firmware cache because a detected opt-in NVIDIA class is active"
  exit 0
fi

if [ ! -d "$FIRMWARE_CACHE_DIR" ]; then
  installer_info "no Debian Installer firmware cache exists; NVIDIA firmware gate has nothing to remove"
  exit 0
fi

removed_count=0
for cached_deb in \
  "$FIRMWARE_CACHE_DIR"/firmware-nvidia-*.deb \
  "$FIRMWARE_CACHE_DIR"/nvidia-firmware-*.deb
do
  [ -e "$cached_deb" ] || continue
  [ -f "$cached_deb" ] && [ ! -L "$cached_deb" ] ||
    nvidia_firmware_gate_fatal "cached NVIDIA firmware candidate is not a regular file: $cached_deb"

  cached_name=${cached_deb##*/}
  case "$cached_name" in
    firmware-nvidia-*.deb|nvidia-firmware-*.deb) ;;
    *)
      nvidia_firmware_gate_fatal "refusing to remove an unexpected firmware cache entry: $cached_name"
      ;;
  esac

  rm -f "$cached_deb"
  removed_count=$((removed_count + 1))
done

if [ "$removed_count" -gt 0 ]; then
  installer_warn "removed ${removed_count} Debian Installer NVIDIA firmware package(s) because no detected opt-in NVIDIA class is active"
else
  installer_info "Debian Installer firmware cache contains no NVIDIA firmware packages"
fi
