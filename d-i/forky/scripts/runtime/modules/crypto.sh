#!/bin/sh
# Shared storage runtime module.

runtime_generate_crypto_bootstrap_key() {
  crypto_bootstrap_key=

  [ -r /proc/sys/kernel/random/uuid ] ||
    runtime_fatal "kernel UUID entropy source is unavailable for the crypto bootstrap key"
  IFS= read -r crypto_bootstrap_key </proc/sys/kernel/random/uuid ||
    [ -n "$crypto_bootstrap_key" ] ||
    runtime_fatal "unable to generate the crypto bootstrap key"

  case "$crypto_bootstrap_key" in
    ????????-????-????-????-????????????) ;;
    *) runtime_fatal "generated crypto bootstrap key has an invalid UUID shape" ;;
  esac
  case "$crypto_bootstrap_key" in
    *[!0123456789abcdefABCDEF-]*)
      runtime_fatal "generated crypto bootstrap key has unsupported characters"
      ;;
  esac

  printf '%s\n' "$crypto_bootstrap_key"
}

runtime_read_or_create_crypto_bootstrap_key() {
  key_file=$1
  key_dir=$(dirname "$key_file")
  key_tmp="${key_file}.tmp.$$"
  crypto_bootstrap_key=

  if [ -e "$key_file" ]; then
    [ -f "$key_file" ] && [ ! -L "$key_file" ] ||
      runtime_fatal "crypto bootstrap key must be a regular non-symlink file: ${key_file}"
    IFS= read -r crypto_bootstrap_key <"$key_file" ||
      [ -n "$crypto_bootstrap_key" ] ||
      runtime_fatal "unable to read crypto bootstrap key: ${key_file}"
  else
    crypto_bootstrap_key=$(runtime_generate_crypto_bootstrap_key)
    (
      umask 077
      printf '%s' "$crypto_bootstrap_key" >"$key_tmp"
    ) || runtime_fatal "unable to write crypto bootstrap key"
    chmod 0400 "$key_tmp" || runtime_fatal "unable to secure crypto bootstrap key"
    mv -f "$key_tmp" "$key_file" || runtime_fatal "unable to install crypto bootstrap key"
  fi

  case "$crypto_bootstrap_key" in
    ????????-????-????-????-????????????) ;;
    *) runtime_fatal "crypto bootstrap key has an invalid UUID shape" ;;
  esac
  case "$crypto_bootstrap_key" in
    *[!0123456789abcdefABCDEF-]*)
      runtime_fatal "crypto bootstrap key has unsupported characters"
      ;;
  esac
  chmod 0400 "$key_file" || runtime_fatal "unable to secure crypto bootstrap key"
  [ -d "$key_dir" ] || runtime_fatal "crypto bootstrap key directory is missing: ${key_dir}"
  printf '%s\n' "$crypto_bootstrap_key"
}

runtime_write_crypto_answers() {
  dest=$1

  runtime_validate_account_settings
  runtime_prepare_parent_dir "$dest" 0700
  crypto_key_file="$(dirname "$dest")/crypto-bootstrap.key"
  crypto_install_passphrase=$(runtime_read_or_create_crypto_bootstrap_key "$crypto_key_file")
  {
    printf '##########  Runtime Crypto Configuration  ##########\n'
    printf '# Generated inside the installer. addon/crypto uses a random bootstrap passphrase.\n'
    printf 'd-i partman-crypto/passphrase password %s\n' "$crypto_install_passphrase"
    printf 'd-i partman-crypto/passphrase seen true\n'
    printf 'd-i partman-crypto/passphrase-again password %s\n' "$crypto_install_passphrase"
    printf 'd-i partman-crypto/passphrase-again seen true\n'
    printf 'd-i partman-crypto/weak_passphrase boolean true\n'
    printf 'd-i partman-crypto/weak_passphrase seen true\n'
    printf 'd-i partman-crypto/confirm boolean true\n'
    printf 'd-i partman-crypto/confirm seen true\n'
    printf 'd-i partman-crypto/confirm_nochanges boolean true\n'
    printf 'd-i partman-crypto/confirm_nochanges seen true\n'
    printf 'd-i partman-crypto/confirm_nooverwrite boolean true\n'
    printf 'd-i partman-crypto/confirm_nooverwrite seen true\n'
  } >"$dest"
  chmod 0600 "$dest"
}

runtime_seed_generated_answers() {
  writer=$1
  shift

  tmp_dir=$(mktemp -d) || runtime_fatal "unable to create temporary answer directory"
  tmp_file="${tmp_dir}/generated.answers"
  status=0

  "$writer" "$tmp_file" "$@" || {
    status=$?
    rm -rf "$tmp_dir"
    return "$status"
  }
  runtime_apply_answers_file "$tmp_file" || {
    status=$?
    rm -rf "$tmp_dir"
    return "$status"
  }

  rm -rf "$tmp_dir"
  return 0
}

runtime_secure_boot_state_uses_luks() {
  [ "$(runtime_secure_boot_state_mode)" = "luks" ]
}

