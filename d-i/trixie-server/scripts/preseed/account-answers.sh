#!/bin/sh
set -eu
umask 077

source_dir=${1:-/tmp/server-install}
# shellcheck disable=SC1090
. "$source_dir/scripts/common/credentials.sh"

username=$(server_credential_read primary_user) || { printf '%s\n' 'fatal: PRESEED_PRIMARY_USERNAME is required' >&2; exit 1; }
fullname=$(server_credential_read primary_fullname) || { printf '%s\n' 'fatal: PRESEED_PRIMARY_FULLNAME is required' >&2; exit 1; }
password=$(server_credential_read primary_password) || { printf '%s\n' 'fatal: PRESEED_PRIMARY_PASSWORD is required' >&2; exit 1; }
root_password=$(server_credential_read root_password 2>/dev/null || true)
{
  printf 'd-i passwd/user-fullname string %s\n' "$fullname"
  printf 'd-i passwd/user-fullname seen true\n'
  printf 'd-i passwd/username string %s\n' "$username"
  printf 'd-i passwd/username seen true\n'
  printf 'd-i passwd/user-password password %s\n' "$password"
  printf 'd-i passwd/user-password seen true\n'
  printf 'd-i passwd/user-password-again password %s\n' "$password"
  printf 'd-i passwd/user-password-again seen true\n'
  if [ -n "$root_password" ]; then
    printf 'd-i passwd/root-password password %s\n' "$root_password"
    printf 'd-i passwd/root-password seen true\n'
    printf 'd-i passwd/root-password-again password %s\n' "$root_password"
    printf 'd-i passwd/root-password-again seen true\n'
  fi
} | debconf-set-selections
