#!/bin/sh
# Debian 13+ bootstrap-base registers waypoints before run_waypoints. Adapt only
# its APT-update boundary; preserve debootstrap, media handling and kernel logic.
# Unsupported upstream layouts fail BEFORE destructive partitioning starts.
set -eu
umask 077
script=$1
helper=$2
case "$script:$helper" in *[!A-Za-z0-9_./:-]*) exit 1 ;; esac
[ -f "$script" ] && [ ! -L "$script" ] && [ -f "$helper" ] && [ ! -L "$helper" ]
[ -x "$script" ]
if grep -qx '# INSTALLER_NETWORK_APT_ADAPTER_V1' "$script"; then
  grep -Fqx "  /bin/sh -eu \"$helper\" \"\$DISTRIBUTION\"" "$script"
  exit 0
fi
count=$(grep -Ec '^[[:space:]]*waypoint[[:space:]]+3[[:space:]]+apt_update[[:space:]]*$' "$script" || :)
[ "$count" = 1 ] || { echo 'fatal: unsupported bootstrap-base APT waypoint; refusing unguarded installation' >&2; exit 1; }
work=$(mktemp "${script%/*}/.installer-adapter.XXXXXX")
trap 'rm -f "$work"' 0
awk -v helper="$helper" '
/^[[:space:]]*waypoint[[:space:]]+3[[:space:]]+apt_update[[:space:]]*$/ {
  print "# INSTALLER_NETWORK_APT_ADAPTER_V1"
  print "installer_network_apt_update() {"
  print "  /bin/sh -eu \"" helper "\" \"$DISTRIBUTION\""
  print "}"
  print "waypoint 3 installer_network_apt_update"
  next
}
{print}' "$script" >"$work"
/bin/sh -n "$work"
chmod 0755 "$work"
mv -f "$work" "$script"
