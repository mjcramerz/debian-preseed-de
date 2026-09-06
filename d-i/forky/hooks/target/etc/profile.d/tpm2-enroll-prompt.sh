#!/bin/sh

case $- in
  *i*) ;;
  *) return 0 ;;
esac

[ "$(id -u 2>/dev/null || printf '0')" -ne 0 ] || return 0
[ -t 0 ] && [ -t 1 ] || return 0
pending_file=/usr/local/lib/crypto/tpm2-enroll.pending
[ -r "$pending_file" ] || return 0
pending_user=$(cat "$pending_file")
[ -n "$pending_user" ] || return 0
[ "$(id -un 2>/dev/null)" = "$pending_user" ] || return 0
[ -x /usr/local/sbin/tpm2-enroll.sh ] || return 0
command -v sudo >/dev/null 2>&1 || return 0

printf '%s\n' 'TPM2 disk enrollment is pending; recovery passphrase and PIN setup will start now.'
sudo /usr/local/sbin/tpm2-enroll.sh
