#!/bin/sh
# Sourced installer module; edit this file directly.

devops_import_aptly_signing_key() (
  signing_device=/dev/sda2
  signing_profile_path=$DEVOPS_APTLY_GPG_SIGNING_KEY
  signing_key_name=${signing_profile_path##*/}
  signing_initrd_key="/${signing_key_name}"
  signing_maximum_bytes=1048576
  signing_copy_block_bytes=4096
  signing_mountpoint=
  signing_source_key=
  staged_host_key=

  devops_cleanup_aptly_signing_key() {
    cleanup_status=$1
    trap - EXIT HUP INT TERM

    if [ -n "$staged_host_key" ]; then
      if ! rm -f -- "$staged_host_key"; then
        printf 'fatal: unable to remove the transient Aptly signing-key copy\n' >&2
        [ "$cleanup_status" -ne 0 ] || cleanup_status=1
      fi
    fi

    if [ -n "$signing_mountpoint" ] &&
       installer_mounts_has_mountpoint "$signing_mountpoint"
    then
      if ! umount "$signing_mountpoint"; then
        printf 'fatal: unable to unmount the Aptly signing-key medium\n' >&2
        [ "$cleanup_status" -ne 0 ] || cleanup_status=1
      fi
    fi

    if [ -n "$signing_mountpoint" ] && [ -d "$signing_mountpoint" ]; then
      if ! rmdir "$signing_mountpoint"; then
        printf 'fatal: unable to remove the Aptly signing-key mountpoint\n' >&2
        [ "$cleanup_status" -ne 0 ] || cleanup_status=1
      fi
    fi

    exit "$cleanup_status"
  }

  trap 'devops_cleanup_aptly_signing_key "$?"' EXIT
  trap 'devops_cleanup_aptly_signing_key 129' HUP
  trap 'devops_cleanup_aptly_signing_key 130' INT
  trap 'devops_cleanup_aptly_signing_key 143' TERM

  for required_command in chown cmp dd mktemp mount readlink tr umount wc; do
    command -v "$required_command" >/dev/null 2>&1 ||
      devops_fatal "required Aptly signing-key import command is unavailable: $required_command"
  done

  if [ -b "$signing_device" ]; then
    signing_mountpoint=$(mktemp -d "${tmp_env_dir}/aptly-signing-media.XXXXXX") ||
      devops_fatal "unable to allocate the Aptly signing-key mountpoint"
    chmod 0700 "$signing_mountpoint"
    installer_mounts_has_mountpoint "$signing_mountpoint" &&
      devops_fatal "new Aptly signing-key mountpoint is unexpectedly already mounted"

    if ! mount -o ro,nosuid,nodev,noexec "$signing_device" "$signing_mountpoint"; then
      devops_fatal "unable to mount the Aptly signing-key device read-only: $signing_device"
    fi
    installer_mounts_find_record "$signing_mountpoint" ||
      devops_fatal "Aptly signing-key mount is absent after mount completed"
    same_device_path "$INSTALLER_MOUNT_SOURCE" "$signing_device" ||
      devops_fatal "Aptly signing-key mount source does not match $signing_device"
    for required_option in ro nosuid nodev noexec; do
      case ",$INSTALLER_MOUNT_OPTIONS," in
        *",${required_option},"*) ;;
        *)
          devops_fatal "Aptly signing-key mount is missing required option: $required_option"
          ;;
      esac
    done

    signing_directory="${signing_mountpoint}/aptly-signing"
    signing_media_key="${signing_mountpoint}${signing_profile_path}"
    if [ -e "$signing_directory" ] || [ -L "$signing_directory" ]; then
      [ -d "$signing_directory" ] && [ ! -L "$signing_directory" ] ||
        devops_fatal "Aptly signing-key directory on $signing_device is not a regular directory"
    fi
    if [ -e "$signing_media_key" ] || [ -L "$signing_media_key" ]; then
      [ -d "$signing_directory" ] && [ ! -L "$signing_directory" ] ||
        devops_fatal "Aptly signing-key directory on $signing_device is missing or unsafe"
      [ -f "$signing_media_key" ] &&
        [ ! -L "$signing_media_key" ] &&
        [ -r "$signing_media_key" ] ||
        devops_fatal "Aptly signing-key source on $signing_device must be a readable regular non-symlink file"

      signing_mountpoint_real=$(readlink -f -- "$signing_mountpoint") ||
        devops_fatal "unable to resolve the Aptly signing-key mountpoint"
      signing_directory_real=$(readlink -f -- "$signing_directory") ||
        devops_fatal "unable to resolve the Aptly signing-key directory"
      signing_media_key_real=$(readlink -f -- "$signing_media_key") ||
        devops_fatal "unable to resolve the Aptly signing-key source on $signing_device"
      [ "$signing_directory_real" = "${signing_mountpoint_real}/aptly-signing" ] &&
        [ "$signing_media_key_real" = "${signing_directory_real}/${signing_key_name}" ] ||
        devops_fatal "Aptly signing-key source escaped the mounted aptly-signing directory"
      signing_source_key=$signing_media_key
    else
      if ! umount "$signing_mountpoint"; then
        devops_fatal "unable to unmount the Aptly signing-key medium before initrd fallback"
      fi
      installer_mounts_has_mountpoint "$signing_mountpoint" &&
        devops_fatal "Aptly signing-key medium remains mounted before initrd fallback"
      rmdir "$signing_mountpoint" ||
        devops_fatal "unable to remove the Aptly signing-key mountpoint before initrd fallback"
      signing_mountpoint=
    fi
  fi

  if [ -z "$signing_source_key" ]; then
    if [ ! -e "$signing_initrd_key" ] && [ ! -L "$signing_initrd_key" ]; then
      devops_fatal "Aptly signing key is absent from both ${signing_device}${signing_profile_path} and ${signing_initrd_key}"
    fi
    [ -f "$signing_initrd_key" ] &&
      [ ! -L "$signing_initrd_key" ] &&
      [ -r "$signing_initrd_key" ] ||
      devops_fatal "Aptly signing-key initrd fallback must be a readable regular non-symlink file: $signing_initrd_key"
    signing_initrd_key_real=$(readlink -f -- "$signing_initrd_key") ||
      devops_fatal "unable to resolve the Aptly signing-key initrd fallback"
    [ "$signing_initrd_key_real" = "$signing_initrd_key" ] ||
      devops_fatal "Aptly signing-key initrd fallback escaped the d-i root"
    signing_source_key=$signing_initrd_key
  fi

  umask 077
  staged_host_key=$(mktemp "${target_root}${APTLY_ROOT_DIR}/.aptly-signing-key.XXXXXX") ||
    devops_fatal "unable to allocate the transient Aptly signing-key copy"
  staged_key_name=${staged_host_key##*/}
  case "$staged_key_name" in
    .aptly-signing-key.*) ;;
    *) devops_fatal "transient Aptly signing-key name is invalid" ;;
  esac
  staged_target_key="${APTLY_ROOT_DIR}/${staged_key_name}"
  signing_copy_block_count=$((
    signing_maximum_bytes / signing_copy_block_bytes + 1
  ))
  if ! dd \
    if="$signing_source_key" \
    of="$staged_host_key" \
    bs="$signing_copy_block_bytes" \
    count="$signing_copy_block_count" \
    2>/dev/null
  then
    devops_fatal "unable to copy the bounded Aptly signing key from its selected source"
  fi
  staged_key_bytes_raw=$(wc -c <"$staged_host_key") ||
    devops_fatal "unable to count the transient Aptly signing-key bytes"
  staged_key_bytes=$(printf '%s' "$staged_key_bytes_raw" | tr -d '[:space:]') ||
    devops_fatal "unable to normalize the transient Aptly signing-key size"
  case "$staged_key_bytes" in
    ''|*[!0123456789]*)
      devops_fatal "transient Aptly signing-key size is invalid"
      ;;
  esac
  [ "$staged_key_bytes" -gt 0 ] &&
    [ "$staged_key_bytes" -le "$signing_maximum_bytes" ] ||
    devops_fatal "Aptly signing-key source must be between 1 and ${signing_maximum_bytes} bytes"
  IFS= read -r signing_source_header <"$staged_host_key" ||
    devops_fatal "unable to read the Aptly signing-key armor header"
  [ "$signing_source_header" = '-----BEGIN PGP PRIVATE KEY BLOCK-----' ] ||
    devops_fatal "Aptly signing-key source is not an armored OpenPGP private key"
  chmod 0600 "$staged_host_key"
  chown "$account_ids" "$staged_host_key"
  cmp "$signing_source_key" "$staged_host_key" >/dev/null 2>&1 ||
    devops_fatal "transient Aptly signing-key copy does not match its source"

  if [ -n "$signing_mountpoint" ]; then
    if ! umount "$signing_mountpoint"; then
      devops_fatal "unable to unmount the Aptly signing-key medium before import"
    fi
    installer_mounts_has_mountpoint "$signing_mountpoint" &&
      devops_fatal "Aptly signing-key medium remains mounted after unmount"
    rmdir "$signing_mountpoint" ||
      devops_fatal "unable to remove the Aptly signing-key mountpoint after unmount"
    signing_mountpoint=
  fi

  # BEGIN: managed Aptly signing-key target import
  # shellcheck disable=SC2016
  devops_run_as_account "inspect and import the managed Aptly signing key" /bin/sh -eu -c '
staged_key=$1
account_home=$2
aptly_root=$3
expected_fingerprint=$4
maximum_bytes=$5
gnupg_home="${account_home}/.gnupg"

aptly_signing_key_fatal() {
  printf "fatal: %s\n" "$*" >&2
  exit 1
}

aptly_primary_secret_summary() {
  LC_ALL=C /usr/bin/awk -F: "
    \$1 == \"pub\" || \$1 == \"sec\" {
      primary_count++
      primary_type = \$1
      expect_fingerprint = 1
      next
    }
    expect_fingerprint && \$1 == \"fpr\" {
      printf \"%d:%s:%s\\n\", primary_count, primary_type, toupper(\$10)
      expect_fingerprint = 0
    }
    END {
      if (expect_fingerprint) {
        printf \"%d:%s:\\n\", primary_count, primary_type
      }
    }
  "
}

aptly_signing_capability_count() {
  LC_ALL=C /usr/bin/awk -F: "
    (\$1 == \"sec\" || \$1 == \"ssb\") &&
    index(\$12, \"s\") != 0 {
      signing_capability_count++
    }
    END {
      print signing_capability_count + 0
    }
  "
}

aptly_available_signing_material_count() {
  LC_ALL=C /usr/bin/awk -F: "
    (\$1 == \"sec\" || \$1 == \"ssb\") &&
    index(\$12, \"s\") != 0 &&
    \$15 == \"+\" {
      available_signing_material_count++
    }
    END {
      print available_signing_material_count + 0
    }
  "
}

for required_command in \
  /usr/bin/awk \
  /usr/bin/gpg \
  /usr/bin/id \
  /usr/bin/install \
  /usr/bin/readlink \
  /usr/bin/find
do
  [ -x "$required_command" ] ||
    aptly_signing_key_fatal "required target command is unavailable: $required_command"
done

case "$maximum_bytes" in
  ""|*[!0123456789]*)
    aptly_signing_key_fatal "Aptly signing-key maximum size is invalid"
    ;;
esac
[ "$maximum_bytes" -gt 0 ] ||
  aptly_signing_key_fatal "Aptly signing-key maximum size must be positive"
case "${#expected_fingerprint}" in
  40|64) ;;
  *) aptly_signing_key_fatal "Aptly signing-key fingerprint length is invalid" ;;
esac
case "$expected_fingerprint" in
  *[!0123456789ABCDEF]*)
    aptly_signing_key_fatal "Aptly signing-key fingerprint is not uppercase hexadecimal"
    ;;
esac

account_uid=$(/usr/bin/id -u)
account_gid=$(/usr/bin/id -g)
[ -d "$account_home" ] && [ ! -L "$account_home" ] ||
  aptly_signing_key_fatal "account home is missing or is a symlink"
[ "$(/usr/bin/find -P "$account_home" -maxdepth 0 -printf "%U:%G")" = "${account_uid}:${account_gid}" ] ||
  aptly_signing_key_fatal "account home is not owned by the target account"
[ -d "$aptly_root" ] && [ ! -L "$aptly_root" ] ||
  aptly_signing_key_fatal "Aptly state root is missing or is a symlink"
[ "$(/usr/bin/find -P "$aptly_root" -maxdepth 0 -printf "%U:%G:%m")" = "${account_uid}:${account_gid}:700" ] ||
  aptly_signing_key_fatal "Aptly state root is not a private account directory"

[ -f "$staged_key" ] && [ ! -L "$staged_key" ] && [ -r "$staged_key" ] ||
  aptly_signing_key_fatal "transient Aptly signing key is not a readable regular file"
aptly_root_real=$(/usr/bin/readlink -f -- "$aptly_root") ||
  aptly_signing_key_fatal "unable to resolve the Aptly state root"
staged_key_real=$(/usr/bin/readlink -f -- "$staged_key") ||
  aptly_signing_key_fatal "unable to resolve the transient Aptly signing key"
case "$staged_key_real" in
  "${aptly_root_real}"/.aptly-signing-key.*) ;;
  *) aptly_signing_key_fatal "transient Aptly signing key escaped its state root" ;;
esac
[ "$(/usr/bin/find -P "$staged_key" -maxdepth 0 -printf "%U:%G:%m")" = "${account_uid}:${account_gid}:600" ] ||
  aptly_signing_key_fatal "transient Aptly signing key is not account-owned mode 0600"
staged_key_bytes=$(/usr/bin/find -P "$staged_key" -maxdepth 0 -printf "%s") ||
  aptly_signing_key_fatal "unable to determine the transient Aptly signing-key size"
case "$staged_key_bytes" in
  ""|*[!0123456789]*)
    aptly_signing_key_fatal "transient Aptly signing-key size is invalid"
    ;;
esac
[ "$staged_key_bytes" -gt 0 ] && [ "$staged_key_bytes" -le "$maximum_bytes" ] ||
  aptly_signing_key_fatal "transient Aptly signing-key size is outside the managed bound"

[ ! -L "$gnupg_home" ] ||
  aptly_signing_key_fatal "target GnuPG home must not be a symlink"
if [ ! -e "$gnupg_home" ]; then
  /usr/bin/install -d -m 0700 -- "$gnupg_home"
fi
[ -d "$gnupg_home" ] && [ ! -L "$gnupg_home" ] ||
  aptly_signing_key_fatal "target GnuPG home is not a directory"
[ "$(/usr/bin/find -P "$gnupg_home" -maxdepth 0 -printf "%U:%G:%m")" = "${account_uid}:${account_gid}:700" ] ||
  aptly_signing_key_fatal "target GnuPG home is not account-owned mode 0700"

key_listing=$(
  /usr/bin/gpg \
    --batch \
    --no-options \
    --quiet \
    --homedir "$gnupg_home" \
    --fixed-list-mode \
    --with-colons \
    --import-options show-only \
    --import "$staged_key"
)
key_summary=$(printf "%s\n" "$key_listing" | aptly_primary_secret_summary)
expected_summary="1:sec:${expected_fingerprint}"
[ "$key_summary" = "$expected_summary" ] ||
  aptly_signing_key_fatal "source must contain exactly one matching primary OpenPGP secret key"
key_signing_capability_count=$(
  printf "%s\n" "$key_listing" | aptly_signing_capability_count
)
[ "$key_signing_capability_count" -gt 0 ] ||
  aptly_signing_key_fatal "source does not contain signing-capable secret-key material"

/usr/bin/gpg \
  --batch \
  --no-options \
  --quiet \
  --homedir "$gnupg_home" \
  --import "$staged_key" >/dev/null

imported_listing=$(
  /usr/bin/gpg \
    --batch \
    --no-options \
    --quiet \
    --homedir "$gnupg_home" \
    --fixed-list-mode \
    --with-secret \
    --with-colons \
    --list-secret-keys "$expected_fingerprint"
)
imported_summary=$(printf "%s\n" "$imported_listing" | aptly_primary_secret_summary)
[ "$imported_summary" = "$expected_summary" ] ||
  aptly_signing_key_fatal "matching Aptly secret key is unavailable after import"
imported_signing_material_count=$(
  printf "%s\n" "$imported_listing" | aptly_available_signing_material_count
)
[ "$imported_signing_material_count" -gt 0 ] ||
  aptly_signing_key_fatal "matching Aptly key has no local signing-capable secret material after import"
' sh \
    "$staged_target_key" \
    "$ACCOUNT_HOME" \
    "$APTLY_ROOT_DIR" \
    "$DEVOPS_APTLY_REPOSITORY_KEY_FINGERPRINT" \
    "$signing_maximum_bytes"
  # END: managed Aptly signing-key target import

  if ! rm -f -- "$staged_host_key"; then
    devops_fatal "unable to remove the transient Aptly signing-key copy after import"
  fi
  [ ! -e "$staged_host_key" ] && [ ! -L "$staged_host_key" ] ||
    devops_fatal "transient Aptly signing-key copy remains after import"
  staged_host_key=
)

