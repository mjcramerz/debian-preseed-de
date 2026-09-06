#!/bin/sh
set -eu

fatal() {
  printf '[select-recipe] fatal: %s\n' "$*" >&2
  exit 1
}

host_profile=${1:-}
case "$host_profile" in
  *-*)
    family=${host_profile%%-*}
    variant=${host_profile#*-}
    ;;
  *)
    fatal "unsupported host profile: ${host_profile}"
    ;;
esac

[ -n "$family" ] || fatal "host profile must include both family and variant: ${host_profile}"
[ -n "$variant" ] || fatal "host profile must include both family and variant: ${host_profile}"

case "$family" in
  *[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-]*)
    fatal "host profile family contains unsupported characters: ${family}"
    ;;
esac
case "$variant" in
  *[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-]*)
    fatal "host profile variant contains unsupported characters: ${variant}"
    ;;
esac

printf '%s-layout-%s\n' "$family" "$variant"
