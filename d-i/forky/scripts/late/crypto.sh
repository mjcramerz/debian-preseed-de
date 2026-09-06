#!/bin/sh
set -eu

target_root=${1:-/target}
[ -d "$target_root" ] || exit 0

crypto_fatal() {
  printf 'fatal: %s\n' "$*" >&2
  exit 1
}

crypto_info() {
  printf '[late:crypto] %s\n' "$*" >&2
}

crypto_validate_abs_path() {
  case "${2:-}" in
    /*) ;;
    *) crypto_fatal "$1 must be an absolute path: ${2:-unset}" ;;
  esac
  case "$2" in
    /|*..*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/@%:+,-]*)
      crypto_fatal "$1 contains unsupported path syntax: $2"
      ;;
  esac
}

crypto_stage_target_asset() {
  repo_path=$1
  target_path=$2
  mode=$3
  tmp_asset="${tmp_env_dir}/$(basename "$target_path").$$"
  target_host_path="${target_root}${target_path}"

  crypto_validate_abs_path "target path" "$target_path"
  bootstrap_fetch_seed_file "$seed_base" "$repo_path" "$tmp_asset" 0600 "crypto asset ${repo_path}"
  install -d -m 0755 "${target_root}$(dirname "$target_path")"
  install -m "$mode" "$tmp_asset" "$target_host_path"
  chmod "$mode" "$target_host_path"
  rm -f "$tmp_asset"
}

crypto_render_target_template() {
  repo_path=$1
  target_path=$2
  mode=$3
  shift 3
  tmp_template="${tmp_env_dir}/$(basename "$target_path").$$.tmpl"
  tmp_rendered="${tmp_env_dir}/$(basename "$target_path").$$.rendered"
  target_host_path="${target_root}${target_path}"

  crypto_validate_abs_path "rendered target path" "$target_path"
  [ $(( $# % 2 )) -eq 0 ] ||
    crypto_fatal "crypto template placeholders must be name/value pairs: ${repo_path}"
  bootstrap_fetch_seed_file "$seed_base" "$repo_path" "$tmp_template" 0600 "crypto template ${repo_path}"
  installer_apply_scalar_placeholders "$tmp_template" "$tmp_rendered" "$@" || {
    rm -f "$tmp_template" "$tmp_rendered"
    crypto_fatal "failed to render crypto template: ${repo_path}"
  }
  installer_assert_no_unresolved_installer_placeholders \
    "$tmp_rendered" \
    "crypto template ${repo_path}"
  install -d -m 0755 "${target_root}$(dirname "$target_path")"
  install -m "$mode" "$tmp_rendered" "$target_host_path"
  chmod "$mode" "$target_host_path"
  rm -f "$tmp_template" "$tmp_rendered"
}

runtime_env_path() {
  for candidate in /tmp/install-env/runtime.env /tmp/install-runtime/state/runtime.env; do
    [ -r "$candidate" ] || continue
    printf '%s\n' "$candidate"
    return 0
  done
  return 1
}

crypto_require_luks2() {
  device=$1
  cryptsetup isLuks "$device" >/dev/null 2>&1 || crypto_fatal "$device is not a LUKS container"
  luks_version=$(cryptsetup luksDump "$device" 2>/dev/null |
    awk '$1 == "Version:" { print $2; exit }')
  [ "$luks_version" = 2 ] || crypto_fatal "$device is not LUKS2"
}

crypto_passphrase_works() {
  device=$1
  key_file=$2
  cryptsetup open --test-passphrase --type luks2 --key-file "$key_file" "$device" >/dev/null 2>&1
}

crypto_validate_install_passphrase_file() {
  key_file=$1
  expected_key=$2
  [ -f "$key_file" ] && [ ! -L "$key_file" ] ||
    crypto_fatal "installer passphrase file must be a regular non-symlink file: ${key_file}"
  key_value=$(cat "$key_file") ||
    crypto_fatal "unable to read installer passphrase file: ${key_file}"
  [ "$key_value" = "$expected_key" ] ||
    crypto_fatal "installer passphrase file does not match the installer bootstrap key"
}

crypto_stage_install_passphrase_file() {
  bootstrap_key_file=$1
  target_key_file=$2
  bootstrap_key=

  [ -f "$bootstrap_key_file" ] && [ ! -L "$bootstrap_key_file" ] ||
    crypto_fatal "crypto bootstrap key is unsafe: ${bootstrap_key_file}"
  bootstrap_key=$(cat "$bootstrap_key_file") ||
    crypto_fatal "unable to read crypto bootstrap key: ${bootstrap_key_file}"
  case "$bootstrap_key" in
    ????????-????-????-????-????????????) ;;
    *) crypto_fatal "crypto bootstrap key has an invalid UUID shape" ;;
  esac
  case "$bootstrap_key" in
    *[!0123456789abcdefABCDEF-]*)
      crypto_fatal "crypto bootstrap key has unsupported characters"
      ;;
  esac

  install -d -m 0755 "$(dirname "$target_key_file")"
  install -m 0400 "$bootstrap_key_file" "$target_key_file" ||
    crypto_fatal "unable to stage the installer passphrase file"
  crypto_validate_install_passphrase_file "$target_key_file" "$bootstrap_key"
}

crypto_write_config() {
  : "${FILE_CRYPTO_STATE_CONFIG:?FILE_CRYPTO_STATE_CONFIG must be set}"
  crypto_render_target_template \
    "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/lib/crypto/config.env.tmpl)" \
    "$FILE_CRYPTO_STATE_CONFIG" \
    0600 \
    CRYPTO_PRIMARY_USER_VALUE "$(shell_single_quote "$ACCOUNT_USERNAME")" \
    CRYPTO_ROOT_LUKS_UUID_VALUE "$(shell_single_quote "$root_luks_uuid")" \
    CRYPTO_HOME_LUKS_UUID_VALUE "$(shell_single_quote "$home_luks_uuid")" \
    CRYPTO_ROOT_CRYPT_NAME_VALUE "$(shell_single_quote "$ROOT_CRYPT_NAME")" \
    CRYPTO_HOME_CRYPT_NAME_VALUE "$(shell_single_quote "$HOME_CRYPT_NAME")" \
    CRYPTO_HOME_KEY_FILE_VALUE "$(shell_single_quote "$home_key_target")" \
    CRYPTO_INSTALL_PASSPHRASE_FILE_VALUE "$(shell_single_quote "$install_passphrase_target")" \
    CRYPTO_TPM2_FINAL_PCRS_VALUE "$(shell_single_quote 7+14)"
}

crypto_write_crypttab() {
  # /etc/crypttab is deliberately rendered here rather than staged as a
  # static target asset: d-i may already have emitted entries, and the managed
  # root/home records depend on the fresh installation's LUKS UUIDs.
  crypttab_path="${target_root}/etc/crypttab"
  crypttab_tmp="${tmp_env_dir}/crypttab.$$"
  if [ -r "$crypttab_path" ]; then
    awk \
      -v root_name="$ROOT_CRYPT_NAME" \
      -v home_name="$HOME_CRYPT_NAME" \
      -v root_source="UUID=$root_luks_uuid" \
      -v home_source="UUID=$home_luks_uuid" \
      -v root_by_uuid="/dev/disk/by-uuid/$root_luks_uuid" \
      -v home_by_uuid="/dev/disk/by-uuid/$home_luks_uuid" \
      -v root_device="$DEV_PART_ROOT" \
      -v home_device="$DEV_PART_HOME" '
        $0 == "# Generated by installer automation for addon/crypto." ||
        $0 == "# Root is TPM2-token aware through the initramfs-tools local-top hook." {
          next
        }
        /^[[:space:]]*#/ || NF == 0 {
          print
          next
        }
        $1 == root_name || $1 == home_name ||
        $2 == root_source || $2 == home_source ||
        $2 == root_by_uuid || $2 == home_by_uuid ||
        $2 == root_device || $2 == home_device {
          next
        }
        {
          print
        }
      ' "$crypttab_path" >"$crypttab_tmp"
  else
    : >"$crypttab_tmp"
  fi
  {
    cat "$crypttab_tmp"
    printf '# Generated by installer automation for addon/crypto.\n'
    printf '# Root is TPM2-token aware through the initramfs-tools local-top hook.\n'
    printf '%s UUID=%s none luks,discard,initramfs\n' "$ROOT_CRYPT_NAME" "$root_luks_uuid"
    printf '%s UUID=%s %s luks,discard\n' "$HOME_CRYPT_NAME" "$home_luks_uuid" "$home_key_target"
  } >"$crypttab_path"
  chmod 0600 "$crypttab_path"
  rm -f "$crypttab_tmp"
}

crypto_write_initramfs_config() {
  crypto_render_target_template \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/tpm2-cryptroot.conf.tmpl)" \
    /etc/tpm2-cryptroot.conf \
    0600 \
    TPM2_CRYPTROOT_NAME_VALUE "$(shell_single_quote "$ROOT_CRYPT_NAME")" \
    TPM2_CRYPTROOT_UUID_VALUE "$(shell_single_quote "$root_luks_uuid")"
  crypto_stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/cryptsetup-initramfs/conf-hook)" \
    /etc/cryptsetup-initramfs/conf-hook \
    0644
}

crypto_verify_initramfs() {
  found_initrd=false
  for initrd in "${target_root}"/boot/initrd.img-*; do
    [ -f "$initrd" ] || continue
    found_initrd=true
    relative_initrd=${initrd#"$target_root"}
    listing="${tmp_env_dir}/lsinitramfs.$$.txt"
    if ! run_in_target \
      "inspect TPM2 initramfs payload" \
      /usr/bin/lsinitramfs \
      "$relative_initrd" >"$listing"
    then
      rm -f "$listing"
      crypto_fatal "unable to inspect ${relative_initrd}"
    fi
    grep -q 'scripts/local-top/00-tpm2-cryptroot$' "$listing" ||
      crypto_fatal "early TPM2 local-top script is missing from ${relative_initrd}"
    grep -q 'scripts/local-top/cryptroot$' "$listing" ||
      crypto_fatal "stock cryptroot fallback is missing from ${relative_initrd}"
    grep -q 'libcryptsetup-token-systemd-tpm2.so$' "$listing" ||
      crypto_fatal "systemd TPM2 token plugin is missing from ${relative_initrd}"
    grep -q 'etc/tpm2-cryptroot.conf$' "$listing" ||
      crypto_fatal "TPM2 root config is missing from ${relative_initrd}"
    if grep -q 'etc/cryptsetup-keys.d/crypthome.key$' "$listing"; then
      crypto_fatal "root-contained /home key leaked into ${relative_initrd}"
    fi
    if grep -q 'usr/local/lib/crypto/install-passphrase$' "$listing"; then
      crypto_fatal "installer passphrase file leaked into ${relative_initrd}"
    fi
    rm -f "$listing"
  done
  [ "$found_initrd" = true ] || crypto_fatal "no target initramfs image was found"
}

crypto_require_secure_boot_tpm2() {
  secure_boot_state=$(capture_in_target "read Secure Boot state for TPM2 policy" /usr/bin/mokutil --sb-state)
  printf '%s\n' "$secure_boot_state" | grep -q '^SecureBoot enabled' ||
    crypto_fatal "addon/crypto requires UEFI Secure Boot to be enabled"

  tpm2_devices=$(capture_in_target "discover target TPM2 devices" /usr/bin/systemd-cryptenroll --tpm2-device=list)
  printf '%s\n' "$tpm2_devices" | grep -Eq '/dev/tpm(rm)?[0-9]+' ||
    crypto_fatal "addon/crypto requires a usable TPM2 device"
}

crypto_enroll_installer_tpm2() {
  run_in_target "enroll TPM2 installer token for encrypted root" \
    /usr/bin/systemd-cryptenroll \
      --wipe-slot=tpm2 \
      --unlock-key-file="$install_passphrase_target" \
      --tpm2-device=auto \
      --tpm2-pcrs=7 \
      "$DEV_PART_ROOT"
}

runtime_dir=${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}
bootstrap_lib=${INSTALLER_BOOTSTRAP_LIB:-${runtime_dir}/bootstrap/bootstrap.sh}
tmp_env_dir=${INSTALLER_LATE_TMP_ENV_DIR:-/tmp/install-env-late/crypto}

[ -s "$bootstrap_lib" ] || crypto_fatal "installer bootstrap library is unavailable: ${bootstrap_lib}"
# shellcheck disable=SC1090,SC1091
. "$bootstrap_lib"
bootstrap_source_common_lib "" || crypto_fatal "failed to source installer common library"
seed_base=$(installer_current_seed_base 2>/dev/null || installer_seed_base "")
bootstrap_source_common_support_libs "$seed_base" "$tmp_env_dir" fetch hook target || {
  crypto_fatal "failed to source installer late support libraries"
}
installer_ensure_context_loaded "$seed_base"

installer_selected_class_reference_is_selected addon/crypto 2>/dev/null || exit 0

account_env=${INSTALLER_LATE_ACCOUNT_ENV:-/tmp/install-env-late/account.env}
[ -r "$account_env" ] || installer_fetch_account_env "$seed_base" "$account_env" 0600
# shellcheck disable=SC1090,SC1091
. "$account_env"

runtime_env=$(runtime_env_path) || crypto_fatal "installer runtime env is unavailable"
# shellcheck disable=SC1090,SC1091
. "$runtime_env"

: "${ACCOUNT_USERNAME:?ACCOUNT_USERNAME must be set before crypto staging}"
: "${ROOT_HOME_CRYPTO_ENABLED:?ROOT_HOME_CRYPTO_ENABLED must be set}"
: "${DEV_PART_ROOT:?DEV_PART_ROOT must be set}"
: "${DEV_PART_HOME:?DEV_PART_HOME must be set}"
: "${ROOT_CRYPT_NAME:?ROOT_CRYPT_NAME must be set}"
: "${HOME_CRYPT_NAME:?HOME_CRYPT_NAME must be set}"
: "${FILE_CRYPTO_PENDING:?FILE_CRYPTO_PENDING must be set}"
: "${FILE_CRYPTO_COMPLETE:?FILE_CRYPTO_COMPLETE must be set}"
[ "$ROOT_HOME_CRYPTO_ENABLED" = true ] || crypto_fatal "addon/crypto selected without root/home crypto runtime state"
[ -b "$DEV_PART_ROOT" ] || crypto_fatal "encrypted root partition is missing: $DEV_PART_ROOT"
[ -b "$DEV_PART_HOME" ] || crypto_fatal "encrypted home partition is missing: $DEV_PART_HOME"

run_in_target "verify crypto package baseline" /bin/sh -eu -c '
dpkg-query -s cryptsetup-initramfs systemd-cryptsetup systemd-tpm tpm2-tools tpm-udev mokutil >/dev/null
command -v cryptsetup >/dev/null
command -v mokutil >/dev/null
command -v systemd-cryptenroll >/dev/null
command -v update-initramfs >/dev/null
command -v lsinitramfs >/dev/null
' sh || crypto_fatal "target crypto package baseline is incomplete"

crypto_require_secure_boot_tpm2
crypto_require_luks2 "$DEV_PART_ROOT"
crypto_require_luks2 "$DEV_PART_HOME"
root_luks_uuid=$(cryptsetup luksUUID "$DEV_PART_ROOT")
home_luks_uuid=$(cryptsetup luksUUID "$DEV_PART_HOME")
[ -n "$root_luks_uuid" ] || crypto_fatal "unable to read root LUKS UUID"
[ -n "$home_luks_uuid" ] || crypto_fatal "unable to read home LUKS UUID"

home_key_target=/etc/cryptsetup-keys.d/crypthome.key
home_key_host="${target_root}${home_key_target}"
install_passphrase_target=/usr/local/lib/crypto/install-passphrase
install_passphrase_host="${target_root}${install_passphrase_target}"
bootstrap_key_file="${runtime_dir}/state/crypto-bootstrap.key"
install -d -m 0700 "$tmp_env_dir" "${target_root}/etc/cryptsetup-keys.d"
crypto_stage_install_passphrase_file "$bootstrap_key_file" "$install_passphrase_host"
crypto_passphrase_works "$DEV_PART_ROOT" "$install_passphrase_host" ||
  crypto_fatal "installer bootstrap key does not unlock encrypted root"
crypto_passphrase_works "$DEV_PART_HOME" "$install_passphrase_host" ||
  crypto_fatal "installer bootstrap key does not unlock encrypted home"

if [ ! -s "$home_key_host" ]; then
  dd if=/dev/urandom of="$home_key_host" bs=64 count=1 2>/dev/null
  chmod 0400 "$home_key_host"
fi
crypto_passphrase_works "$DEV_PART_HOME" "$home_key_host" || {
  cryptsetup luksAddKey \
    --batch-mode \
    --type luks2 \
    --key-file "$install_passphrase_host" \
    "$DEV_PART_HOME" \
    "$home_key_host"
}
crypto_passphrase_works "$DEV_PART_HOME" "$home_key_host" ||
  crypto_fatal "root-contained home key does not unlock ${DEV_PART_HOME}"

crypto_write_crypttab
crypto_write_config
crypto_write_initramfs_config

crypto_stage_target_asset \
  "$(installer_repo_join_var DIR_HOOKS_TARGET etc/initramfs-tools/hooks/tpm2-cryptroot)" \
  /etc/initramfs-tools/hooks/tpm2-cryptroot \
  0755
crypto_stage_target_asset \
  "$(installer_repo_join_var DIR_HOOKS_TARGET etc/initramfs-tools/scripts/local-top/tpm2-cryptroot)" \
  /etc/initramfs-tools/scripts/local-top/00-tpm2-cryptroot \
  0755
crypto_stage_target_asset \
  "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/sbin/tpm2-enroll.sh)" \
  /usr/local/sbin/tpm2-enroll.sh \
  0755
crypto_stage_target_asset \
  "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/bin/tpm2-enroll-launch)" \
  /usr/local/bin/tpm2-enroll-launch \
  0755
crypto_stage_target_asset \
  "$(installer_repo_join_var DIR_HOOKS_TARGET etc/profile.d/tpm2-enroll-prompt.sh)" \
  /etc/profile.d/tpm2-enroll-prompt.sh \
  0644
crypto_stage_target_asset \
  "$(installer_repo_join_var DIR_HOOKS_TARGET etc/xdg/autostart/tpm2-enroll.desktop)" \
  /etc/xdg/autostart/tpm2-enroll.desktop \
  0644

install -d -m 0755 "${target_root}$(dirname "$FILE_CRYPTO_PENDING")" "${target_root}$(dirname "$FILE_CRYPTO_COMPLETE")"
printf '%s\n' "$ACCOUNT_USERNAME" >"${target_root}${FILE_CRYPTO_PENDING}"
chmod 0644 "${target_root}${FILE_CRYPTO_PENDING}"
rm -f "${target_root}${FILE_CRYPTO_COMPLETE}"

crypto_enroll_installer_tpm2
run_in_target "refresh initramfs-tools images for TPM2 root unlock" /usr/sbin/update-initramfs -u -k all
crypto_verify_initramfs
rm -f "${runtime_dir}/state/crypto.answers.cfg" "$bootstrap_key_file"

crypto_info "staged LUKS2 root/home policy using a random installer bootstrap key with deferred TPM2+PIN enrollment"
