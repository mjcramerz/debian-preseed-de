#!/bin/sh
set -eu

RUNTIME_DIR=${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}
BOOTSTRAP_LIB=${INSTALLER_BOOTSTRAP_LIB:-${RUNTIME_DIR}/bootstrap/bootstrap.sh}
OS_PROBER_PATH=/usr/bin/os-prober
OS_PROBER_REAL_PATH=/usr/bin/os-prober.installer-real
OS_PROBER_STATE_PATH=/var/lib/installer-state/temporary-os-prober-shim
OS_PROBER_MARKER=INSTALLER_TEMPORARY_FAKE_OS_PROBER_V1

temporary_os_prober_fatal() {
  printf '[pre-pkgsel:temporary-os-prober] fatal: %s\n' "$*" >&2
  exit 1
}

[ -s "$BOOTSTRAP_LIB" ] ||
  temporary_os_prober_fatal "installer bootstrap library is unavailable: ${BOOTSTRAP_LIB}"
# shellcheck disable=SC1090,SC1091
. "$BOOTSTRAP_LIB"
bootstrap_source_common_lib ""

SEED_BASE=$(installer_seed_base "")
installer_persist_seed_source "$SEED_BASE"
installer_ensure_context_loaded "$SEED_BASE"

if ! installer_selected_class_reference_is_selected addon/dualboot 2>/dev/null; then
  installer_info "skipping temporary installer os-prober shim because addon/dualboot is not selected"
  exit 0
fi

[ -d /usr/bin ] ||
  temporary_os_prober_fatal "installer /usr/bin is unavailable"
install -d -m 0700 "$(dirname "$OS_PROBER_STATE_PATH")"

if [ -e "$OS_PROBER_STATE_PATH" ]; then
  [ -f "$OS_PROBER_STATE_PATH" ] ||
    temporary_os_prober_fatal "temporary os-prober state is not a regular file"
  state_marker=$(cat "$OS_PROBER_STATE_PATH" 2>/dev/null || true)
  [ "$state_marker" = "$OS_PROBER_MARKER" ] ||
    temporary_os_prober_fatal "temporary os-prober state marker is invalid"
fi

if [ -e "$OS_PROBER_REAL_PATH" ]; then
  [ -f "$OS_PROBER_REAL_PATH" ] && [ -x "$OS_PROBER_REAL_PATH" ] ||
    temporary_os_prober_fatal "preserved installer os-prober is not an executable regular file"
  if grep -Fqx "# ${OS_PROBER_MARKER}" "$OS_PROBER_REAL_PATH"; then
    temporary_os_prober_fatal "preserved installer os-prober unexpectedly contains the shim marker"
  fi
else
  [ -f "$OS_PROBER_PATH" ] && [ -x "$OS_PROBER_PATH" ] ||
    temporary_os_prober_fatal "installer os-prober executable is unavailable: ${OS_PROBER_PATH}"
  if grep -Fqx "# ${OS_PROBER_MARKER}" "$OS_PROBER_PATH"; then
    temporary_os_prober_fatal "temporary os-prober shim exists without a preserved real executable"
  fi
  mv "$OS_PROBER_PATH" "$OS_PROBER_REAL_PATH"
fi

if [ -e "$OS_PROBER_PATH" ]; then
  if [ ! -f "$OS_PROBER_PATH" ] ||
     ! grep -Fqx "# ${OS_PROBER_MARKER}" "$OS_PROBER_PATH"; then
    temporary_os_prober_fatal "refusing to replace an unexpected installer os-prober file"
  fi
fi

shim_tmp="${OS_PROBER_PATH}.tmp.$$"
state_tmp="${OS_PROBER_STATE_PATH}.tmp.$$"
cleanup_temporary_os_prober_files() {
  rm -f "$shim_tmp" "$state_tmp"
}
trap cleanup_temporary_os_prober_files EXIT HUP INT TERM

cat >"$shim_tmp" <<EOF_SHIM
#!/bin/sh
# ${OS_PROBER_MARKER}
# Debian Installer probing is deferred to the controlled target-side
# dual-boot GRUB pass in preseed/late_command.
exit 0
EOF_SHIM
chmod 0755 "$shim_tmp"
mv "$shim_tmp" "$OS_PROBER_PATH"

printf '%s\n' "$OS_PROBER_MARKER" >"$state_tmp"
chmod 0600 "$state_tmp"
mv "$state_tmp" "$OS_PROBER_STATE_PATH"

trap - EXIT HUP INT TERM
installer_info "installed temporary success-only installer os-prober shim; target os-prober remains unchanged"
