#!/bin/sh
set -eu

TARGET=${INSTALLER_TARGET_DIR:-/target}
UNSHARE_PATH=/usr/bin/unshare
UNSHARE_DIVERT_PATH=/usr/bin/unshare.installer-real
UNSHARE_STATE_PATH=/var/lib/installer-state/temporary-unshare-shim
UNSHARE_MARKER=INSTALLER_TEMPORARY_FAKE_UNSHARE_V1

temporary_unshare_fatal() {
  printf '[pre-pkgsel:temporary-unshare] fatal: %s\n' "$*" >&2
  exit 1
}

case "$TARGET" in
  /*) ;;
  *) temporary_unshare_fatal "installer target must be an absolute path: ${TARGET:-unset}" ;;
esac
[ "$TARGET" != / ] || temporary_unshare_fatal "refusing to modify the installer root filesystem"

target_unshare="${TARGET}${UNSHARE_PATH}"
target_divert="${TARGET}${UNSHARE_DIVERT_PATH}"
target_state="${TARGET}${UNSHARE_STATE_PATH}"
target_dpkg_divert="${TARGET}/usr/bin/dpkg-divert"

[ -d "${TARGET}/usr/bin" ] ||
  temporary_unshare_fatal "target /usr/bin is unavailable"
[ -x "$target_dpkg_divert" ] ||
  temporary_unshare_fatal "target dpkg-divert is unavailable: /usr/bin/dpkg-divert"
command -v chroot >/dev/null 2>&1 ||
  temporary_unshare_fatal "installer chroot command is unavailable"

install -d -m 0700 "$(dirname "$target_state")"

if [ -e "$target_state" ]; then
  [ -f "$target_state" ] ||
    temporary_unshare_fatal "temporary unshare state is not a regular file"
  state_marker=$(cat "$target_state" 2>/dev/null || true)
  [ "$state_marker" = "$UNSHARE_MARKER" ] ||
    temporary_unshare_fatal "temporary unshare state marker is invalid"
fi

diversion_listing=$(
  chroot "$TARGET" /usr/bin/dpkg-divert --list "$UNSHARE_PATH" 2>/dev/null || true
)
case "$diversion_listing" in
  '')
    [ -x "$target_unshare" ] ||
      temporary_unshare_fatal "target unshare executable is unavailable: ${UNSHARE_PATH}"
    chroot "$TARGET" /usr/bin/dpkg-divert \
      --quiet \
      --local \
      --rename \
      --divert "$UNSHARE_DIVERT_PATH" \
      --add "$UNSHARE_PATH" ||
      temporary_unshare_fatal "failed to divert the target unshare executable"
    ;;
  *"$UNSHARE_DIVERT_PATH"*)
    ;;
  *)
    temporary_unshare_fatal "target unshare already has an unexpected diversion: $diversion_listing"
    ;;
esac

[ -x "$target_divert" ] ||
  temporary_unshare_fatal "diverted target unshare executable is unavailable: ${UNSHARE_DIVERT_PATH}"

if [ -e "$target_unshare" ]; then
  if [ ! -f "$target_unshare" ] ||
     ! grep -Fqx "# ${UNSHARE_MARKER}" "$target_unshare"; then
    temporary_unshare_fatal "refusing to replace an unexpected target unshare file"
  fi
fi

shim_tmp="${target_unshare}.tmp.$$"
state_tmp="${target_state}.tmp.$$"
cleanup_temporary_unshare_files() {
  rm -f "$shim_tmp" "$state_tmp"
}
trap cleanup_temporary_unshare_files EXIT HUP INT TERM

cat >"$shim_tmp" <<EOF_SHIM
#!/bin/sh
# ${UNSHARE_MARKER}
exit 0
EOF_SHIM
chmod 0755 "$shim_tmp"
mv "$shim_tmp" "$target_unshare"

printf '%s\n' "$UNSHARE_MARKER" >"$state_tmp"
chmod 0600 "$state_tmp"
mv "$state_tmp" "$target_state"

trap - EXIT HUP INT TERM
printf '[pre-pkgsel:temporary-unshare] installed temporary success-only unshare shim at %s\n' \
  "$UNSHARE_PATH" >&2
