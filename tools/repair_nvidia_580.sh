#!/bin/sh
# Repair an already-failed install using THIS snapshot's production wrapper.
# Does not download packages, change repositories, load modules, or reboot.
set -eu

fatal() { printf 'fatal: %s\n' "$*" >&2; exit 1; }
usage() {
  printf 'Usage: sh %s TARGET_ROOT KERNEL_RELEASE\n' "$0" >&2
  printf 'Example from the installer: sh %s /target 7.2.4-x64v3-xanmod1\n' "$0" >&2
  exit 2
}
[ "$#" -eq 2 ] || usage
[ "$(id -u)" -eq 0 ] || fatal 'run as root in the installer or installed system'
case $1 in /*) ;; *) fatal 'TARGET_ROOT must be an absolute mounted path (or /)' ;; esac
TARGET=$(CDPATH= cd -- "$1" && pwd -P) || fatal 'target root is unavailable'
KERNEL=$2
case "$KERNEL" in ''|*[!A-Za-z0-9._+-]*) fatal 'invalid kernel release' ;; esac
REPO=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
HOOK=$REPO/d-i/forky/hooks/installer/pre-pkgsel.d/92nvidia-legacy-dkms.sh
[ -r "$HOOK" ] || fatal 'production hook not found; keep this script inside the extracted repository'
[ -f "$TARGET/etc/debian_version" ] || fatal 'target is not an installed Debian root'
[ -s "$TARGET/lib/modules/$KERNEL/build/Module.symvers" ] || fatal "prepared $KERNEL headers/Module.symvers missing"
[ -c "$TARGET/dev/null" ] || fatal 'target /dev is not mounted'
[ -r "$TARGET/proc/self/status" ] || fatal 'target /proc is not mounted'
[ -d "$TARGET/sys/class" ] || fatal 'target /sys is not mounted'
[ -x "$TARGET/usr/sbin/dkms.distrib" ] || fatal 'existing diverted DKMS executable is missing'
chroot "$TARGET" /bin/sh -eu -c '
  command -v perl >/dev/null
  dpkg-divert --list /usr/sbin/dkms | grep -Fq /usr/sbin/dkms.distrib
' || fatal 'expected installer DKMS diversion or perl-base is missing'
PACKAGE_VERSION=$(chroot "$TARGET" dpkg-query -W '-f=${Version}' nvidia-kernel-source-580)
VERSION=${PACKAGE_VERSION#*:}
VERSION=${VERSION%%-*}
case "$VERSION" in 580.*) ;; *) fatal "unexpected source package version: $PACKAGE_VERSION" ;; esac
case "$VERSION" in *[!0-9.]*|'580.') fatal 'invalid NVIDIA DKMS version' ;; esac
chroot "$TARGET" dpkg-query -W nvidia-dkms-580 >/dev/null

# Stage alongside the destination: replacement cannot expose a partial wrapper.
STAGED=$(mktemp "$TARGET/usr/sbin/dkms.r2.XXXXXX")
trap 'rm -f "$STAGED"' 0
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
awk '
  /^cat >.*dkms-wrapper.*<<.*EOF/ { if (inside || complete) exit 41; inside=1; next }
  inside && $0 == "EOF" { inside=0; complete=1; next }
  inside { print; lines++ }
  END { if (inside || !complete || lines < 10) exit 42 }
' "$HOOK" > "$STAGED" || fatal 'cannot extract production wrapper'
/bin/sh -n "$STAGED"
grep -Fq NV_INSTALLER_NVIDIA_LEGACY_BOUNDED_COPY "$STAGED" || fatal 'revision-2 copy repair missing'
grep -Fq NV_INSTALLER_NVIDIA_LEGACY_DRM_PROBE "$STAGED" || fatal 'revision-2 DRM probe missing'
chmod 0755 "$STAGED"
chown 0:0 "$STAGED"
BACKUP=$(mktemp "$TARGET/usr/sbin/dkms.before-r2.XXXXXX")
cp -p "$TARGET/usr/sbin/dkms" "$BACKUP"
mv -f "$STAGED" "$TARGET/usr/sbin/dkms"
printf 'Previous wrapper saved as %s\n' "$BACKUP"
printf 'Building the FULL NVIDIA %s module set for %s (not the installer uname).\n' "$VERSION" "$KERNEL"
# Force the compile even when DKMS has a previous built-state record. Every
# failure propagates. Retain the fixed wrapper for a subsequent repair attempt.
chroot "$TARGET" /usr/sbin/dkms build -m nvidia -v "$VERSION" -k "$KERNEL" --force
chroot "$TARGET" /usr/sbin/dkms install -m nvidia -v "$VERSION" -k "$KERNEL" --force
chroot "$TARGET" depmod -a "$KERNEL"
for module in nvidia nvidia-modeset nvidia-drm nvidia-uvm; do
  actual=$(chroot "$TARGET" modinfo -k "$KERNEL" -F version "$module")
  [ "$actual" = "$VERSION" ] || fatal "$module version is '$actual', expected '$VERSION'"
  vermagic=$(chroot "$TARGET" modinfo -k "$KERNEL" -F vermagic "$module")
  [ "${vermagic%% *}" = "$KERNEL" ] || fatal "$module kernel identity does not match $KERNEL: $vermagic"
done
# Finish pending package configuration only AFTER the explicit target build.
# This is not a replacement for the installer's remaining pkgsel/late phases.
chroot "$TARGET" /usr/bin/env DEBIAN_FRONTEND=noninteractive dpkg --configure -a
chroot "$TARGET" update-initramfs -u -k "$KERNEL"
STATUS=$(chroot "$TARGET" dpkg-query -W '-f=${Status}' nvidia-dkms-580)
[ "$STATUS" = 'install ok installed' ] || fatal "nvidia-dkms-580 status: $STATUS"
chroot "$TARGET" /usr/sbin/dkms status -m nvidia -v "$VERSION" -k "$KERNEL"
printf '%s\n' 'NVIDIA package/module repair completed. No GPU runtime test has been performed.'
printf '%s\n' 'For a failed Debian installer: return to its menu and retry package installation.'
printf '%s\n' 'Let the remaining installer/late hooks finish; do not treat this script as installation completion.'
