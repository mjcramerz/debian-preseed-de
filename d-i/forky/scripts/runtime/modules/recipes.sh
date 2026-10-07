#!/bin/sh
# Shared storage runtime module.

runtime_prepare_recipe_templates() {
  if [ -z "${RUNTIME_TEMPLATE_DIR:-}" ]; then
    RUNTIME_TEMPLATE_DIR="${RUNTIME_COMMON_LIB%/*}/templates"
  fi
  set -- $RUNTIME_RECIPE_TEMPLATES
  if [ -f "$RUNTIME_TEMPLATE_DIR/$1" ] && [ ! -L "$RUNTIME_TEMPLATE_DIR/$1" ]; then
    return 0
  fi
  command -v fetch_hook_file >/dev/null 2>&1 || runtime_fatal "recipe template fetcher is unavailable"
  RUNTIME_TEMPLATE_DIR=$(mktemp -d "${RUNTIME_COMMON_LIB%/*}/recipes.XXXXXX") || runtime_fatal "cannot stage partition recipe templates"
  for recipe_asset in $RUNTIME_RECIPE_TEMPLATES; do
    fetch_hook_file "scripts/runtime/templates/$recipe_asset" "$RUNTIME_TEMPLATE_DIR/$recipe_asset" ||
      runtime_fatal "cannot fetch partition recipe: $recipe_asset"
    chmod 0600 "$RUNTIME_TEMPLATE_DIR/$recipe_asset" || runtime_fatal "cannot protect partition recipe"
  done
}

runtime_render_recipe() (
  set -eu
  recipe_name=$1; shift
  case "$recipe_name" in btrfs-[0-9][0-9].recipe.tmpl|f2fs-[0-9][0-9].recipe.tmpl) ;; *) runtime_fatal "invalid recipe template" ;; esac
  recipe_path="${RUNTIME_TEMPLATE_DIR:-${RUNTIME_COMMON_LIB%/*}/templates}/$recipe_name"
  [ -f "$recipe_path" ] && [ ! -L "$recipe_path" ] || runtime_fatal "missing or unsafe recipe: $recipe_path"
  # ls -ldn is available in busybox-udeb; stat is deliberately unavailable.
  recipe_metadata=$(LC_ALL=C ls -ldn "$recipe_path") || runtime_fatal "cannot inspect partition recipe"
  # Inspect metadata in a subshell without replacing renderer arguments.
  (
    set -- $recipe_metadata
    [ "$#" -ge 4 ] && [ "$2" = 1 ] && [ "$3" = "$(id -u)" ] ||
      runtime_fatal "untrusted partition recipe ownership"
    case "$1" in
      -r--------|-rw-------|-r--r-----|-r-----r--|-r--r--r--|-rw-r-----|-rw----r--|-rw-r--r--) ;;
      *) runtime_fatal "unsafe partition recipe permissions" ;;
    esac
  ) || exit 1
  awk '
    BEGIN {
      if ((ARGC - 2) % 2) exit 1;
      for (i=2; i<ARGC; i+=2) {
        if (ARGV[i] !~ /^[A-Z][A-Z0-9_]*$/ || ARGV[i] in value) exit 1;
        if (ARGV[i+1] !~ /^[A-Za-z0-9_.-]+$/) exit 1;
        value[ARGV[i]]=ARGV[i+1]; delete ARGV[i]; delete ARGV[i+1];
      }
    }
    {
      line=$0; output="";
      while (match(line, /@@[A-Z][A-Z0-9_]*@@/)) {
        key=substr(line,RSTART+2,RLENGTH-4); if (!(key in value)) exit 1;
        output=output substr(line,1,RSTART-1) value[key]; line=substr(line,RSTART+RLENGTH);
      }
      print output line;
    }
  ' "$recipe_path" "$@" || runtime_fatal "cannot render partition recipe"
)
