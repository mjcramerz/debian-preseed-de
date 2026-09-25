#!/bin/sh
# The supervisor is an independent shell; `if external-command` cannot disable
# errexit inside the child. Stock d-i must never receive a fatal hook status.
set -eu
runtime=${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}
. "$runtime/bootstrap/source.sh"
id=$1
script=$2
shift 2
if installer_lifecycle_begin "$id"; then :; else
  rc=$?
  [ "$rc" -eq 10 ] || exit "$rc"
  case "$id" in
    hook-finish-99reboot|hook-component-finish-install.postinst)
      [ -f "$LC_STATE/installation.success" ] || installer_lifecycle_abort 125 "$id" 'missing final success record'
      trap - 0
      exit 11
      ;;
  esac
  exit 0
fi
[ -f "$script" ] && [ -x "$script" ] && [ ! -L "$script" ] ||
  installer_lifecycle_abort 125 "$id" 'missing or indirect supervised executable'
# The reboot sentinel must only be reached after validation and clean unmount.
if [ "$id" = hook-finish-99reboot ]; then
  for required in prepare-context apply early partman late hook-component-bootstrap-base.postinst hook-component-apt-setup-udeb.postinst hook-component-pkgsel.postinst hook-component-grub-installer.postinst; do
    [ -f "$LC_STATE/$required.done" ] || installer_lifecycle_abort 125 "$id" "missing completion: $required"
  done
  [ -f "$LC_STATE/target-validated" ] || installer_lifecycle_abort 125 "$id" 'target has not passed final validation'
  [ -s "$LC_STATE/finish-hooks.list" ] || installer_lifecycle_abort 125 "$id" 'finish hook inventory missing'
  while IFS= read -r name; do
    [ "$name" = 99reboot ] && continue
    [ -f "$LC_STATE/hook-finish-$name.done" ] || installer_lifecycle_abort 125 "$id" "finish hook not completed: $name"
  done <"$LC_STATE/finish-hooks.list"
  for hook in /usr/lib/finish-install.d/*; do
    [ -x "$hook" ] || continue
    grep -Fqx "${hook##*/}" "$LC_STATE/finish-hooks.list" || installer_lifecycle_abort 125 "$id" 'finish hook inventory changed'
  done
fi
if installer_run_supervised "$script" "$@"; then rc=0; else rc=$?; fi
case "$id:$rc" in
  hook-finish-99reboot:11)
    installer_lifecycle_complete
    tmp=$(mktemp "$LC_STATE/.success.XXXXXX")
    printf 'state=SUCCESS\nvalidated=target\nfinish_hooks=complete\nunmount=complete\n' >"$tmp"
    chmod 0600 "$tmp"
    mv "$tmp" "$LC_STATE/installation.success"
    sync
    trap - 0
    exit 11
    ;;
  hook-component-finish-install.postinst:11)
    [ -f "$LC_STATE/installation.success" ] || installer_lifecycle_abort 125 "$id" 'finish-install requested exit without validated reboot handoff'
    installer_lifecycle_complete
    trap - 0
    exit 11
    ;;
  hook-finish-99reboot:0|hook-component-finish-install.postinst:0)
    installer_lifecycle_abort 125 "$id" 'missing d-i reboot sentinel status 11' ;;
  *:0) installer_lifecycle_complete ;;
  *) installer_lifecycle_abort "$rc" "$id" 'supervised hook failed; automatic re-entry is forbidden' ;;
esac
