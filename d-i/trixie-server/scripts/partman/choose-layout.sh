#!/bin/sh
set -eu
umask 077

source_dir=${SERVER_SOURCE_DIR:-/tmp/server-install}
. "$source_dir/repo.env"
. "$source_dir/$DIR_HOSTS_INSTALLER/runtime.env"
credentials="$source_dir/scripts/common/credentials.sh"
recipes="$source_dir/scripts/runtime/modules/recipes.sh"
[ -r "$credentials" ] || { printf '%s\n' 'fatal: server credential reader is unavailable' >&2; exit 1; }
[ -r "$recipes" ] || { printf '%s\n' 'fatal: server partition recipe module is unavailable' >&2; exit 1; }
# shellcheck disable=SC1090
. "$credentials"
runtime_fatal() { printf '[partman] fatal: %s\n' "$*" >&2; exit 1; }
RUNTIME_TEMPLATE_DIR="$source_dir/scripts/runtime/templates"
export RUNTIME_TEMPLATE_DIR
# shellcheck disable=SC1090
. "$recipes"

classes=$(server_cmdline_value classes 2>/dev/null || true)
if [ -z "$classes" ]; then
  # shellcheck disable=SC1090
  . "$source_dir/repo.env"
  classes=$DEBIAN_DEFAULT_CLASSES
fi
profile=$(server_profile_from_classes "$classes" 2>/dev/null || true)
profile=${profile:-btrfs-srv-flex}
case "$profile" in
  btrfs-srv-flex|btrfs-srv-flex-duo|f2fs-srv-hp14) ;;
  *) runtime_fatal 'selected server profile is invalid' ;;
esac
# shellcheck disable=SC1090
. "$source_dir/hosts/profiles/$profile.env"
. "$source_dir/hosts/installer/layout.env"
case "$profile" in
  f2fs-srv-hp14) . "$source_dir/hosts/installer/f2fs.env" ;;
  *) . "$source_dir/hosts/installer/btrfs.env" ;;
esac
recipe=${PARTMAN_RECIPE_NAME:-}
case "$recipe" in
  btrfs-layout-server) template=btrfs-01.recipe.tmpl ;;
  f2fs-layout-server) template=f2fs-01.recipe.tmpl ;;
  *) runtime_fatal 'selected profile has no supported partman recipe' ;;
esac
runtime_prepare_recipe_templates
recipe_file="$source_dir/runtime-partman.recipe"
case "$recipe" in
  btrfs-layout-server)
    runtime_render_recipe "$template" \
      RECIPE "$recipe" SIZE_PART_EFI_MB "$SIZE_PART_EFI_MB" SIZE_PART_BOOT_MB "$SIZE_PART_BOOT_MB" \
      SIZE_PART_ROOT_MB "$SIZE_PART_ROOT_MB" SIZE_PART_HOME_MB "$SIZE_PART_HOME_MB" \
      SIZE_PART_OPT_MB "$SIZE_PART_OPT_MB" SIZE_PART_DATA_MB "$SIZE_PART_DATA_MB" \
      SIZE_PART_POOL_MB "$SIZE_PART_POOL_MB" SIZE_PART_VAR_TMP_MB "$SIZE_PART_VAR_TMP_MB" \
      SIZE_PART_VAR_LIB_SHSIGNED_MB "$SIZE_PART_VAR_LIB_SHSIGNED_MB" \
      SIZE_PART_VAR_LOG_JOURNAL_MB "$SIZE_PART_VAR_LOG_JOURNAL_MB" \
      SIZE_PART_RAW_SWAP_MB "$SIZE_PART_RAW_SWAP_MB" SIZE_PART_RAW_ZRAM_MB "$SIZE_PART_RAW_ZRAM_MB" \
      >"$recipe_file"
    ;;
  f2fs-layout-server)
    runtime_render_recipe "$template" \
      RECIPE "$recipe" SIZE_PART_EFI_MB "$SIZE_PART_EFI_MB" SIZE_PART_BOOT_MB "$SIZE_PART_BOOT_MB" \
      SIZE_PART_ROOT_MB "$SIZE_PART_ROOT_MB" SIZE_PART_HOME_MB "$SIZE_PART_HOME_MB" \
      SIZE_PART_VAR_LIB_SHSIGNED_MB "$SIZE_PART_VAR_LIB_SHSIGNED_MB" \
      SIZE_PART_VAR_LOG_JOURNAL_MB "$SIZE_PART_VAR_LOG_JOURNAL_MB" \
      SIZE_PART_RAW_SWAP_MB "$SIZE_PART_RAW_SWAP_MB" SIZE_PART_RAW_ZRAM_MB "$SIZE_PART_RAW_ZRAM_MB" \
      >"$recipe_file"
    ;;
esac
chmod 0600 "$recipe_file"
answers=$(mktemp /tmp/server-partman.XXXXXX)
trap 'rm -f "$answers"' EXIT HUP INT TERM
printf 'd-i partman-auto/choose_recipe select %s\n' "$recipe" >"$answers"
printf 'd-i partman-auto/choose_recipe seen true\n' >>"$answers"
printf 'd-i partman-auto/expert_recipe_file string %s\n' "$recipe_file" >>"$answers"
printf 'd-i partman-auto/expert_recipe_file seen true\n' >>"$answers"
command -v debconf-set-selections >/dev/null 2>&1 || runtime_fatal 'debconf-set-selections is unavailable during partman early processing'
debconf-set-selections "$answers"
