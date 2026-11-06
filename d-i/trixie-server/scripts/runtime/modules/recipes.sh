#!/bin/sh
# Server partition recipe renderer follows the Forky runtime template contract.

runtime_prepare_recipe_templates() {
  RUNTIME_TEMPLATE_DIR=${RUNTIME_TEMPLATE_DIR:-${RUNTIME_COMMON_LIB%/*}/templates}
  [ -d "$RUNTIME_TEMPLATE_DIR" ] || runtime_fatal 'partition recipe template directory is unavailable'
}

runtime_render_recipe() (
  set -eu
  recipe_name=$1
  shift
  case "$recipe_name" in
    btrfs-[0-9][0-9].recipe.tmpl|f2fs-[0-9][0-9].recipe.tmpl) ;;
    *) runtime_fatal 'invalid partition recipe template' ;;
  esac
  recipe_path="${RUNTIME_TEMPLATE_DIR:-${RUNTIME_COMMON_LIB%/*}/templates}/$recipe_name"
  [ -f "$recipe_path" ] && [ ! -L "$recipe_path" ] || runtime_fatal "missing partition recipe: $recipe_path"
  awk '
    BEGIN {
      if ((ARGC - 2) % 2) exit 1
      for (i = 2; i < ARGC; i += 2) {
        if (ARGV[i] !~ /^[A-Z][A-Z0-9_]*$/ || ARGV[i] in value) exit 1
        if (ARGV[i + 1] !~ /^[A-Za-z0-9_.-]+$/) exit 1
        value[ARGV[i]] = ARGV[i + 1]
        delete ARGV[i]
        delete ARGV[i + 1]
      }
    }
    {
      line = $0
      output = ""
      while (match(line, /@@[A-Z][A-Z0-9_]*@@/)) {
        key = substr(line, RSTART + 2, RLENGTH - 4)
        if (!(key in value)) exit 1
        output = output substr(line, 1, RSTART - 1) value[key]
        line = substr(line, RSTART + RLENGTH)
      }
      print output line
    }
  ' "$recipe_path" "$@" || runtime_fatal 'cannot render partition recipe'
)
