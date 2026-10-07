#!/bin/sh
# Sourced by late/core.sh. All inputs use the authenticated installer fetcher.
# Theme files are literal data, validated in full before shell consumption.

installer_load_themes() {
  [ "${INSTALLER_THEMES_LOADED:-0}" = 1 ] && return 0
  : "${TMP_ENV_DIR:?installer theme staging directory is not initialized}"
  INSTALLER_THEME_DIR="${TMP_ENV_DIR}/themes"
  install -d -m 0700 "$INSTALLER_THEME_DIR" || return $?
  fetch_hook_file "$(installer_repo_join_var DIR_SCRIPTS_LATE theme-validate.awk)" "$INSTALLER_THEME_DIR/validate.awk" || return $?
  fetch_hook_file "$(installer_repo_join_var DIR_SCRIPTS_LATE theme-render.awk)" "$INSTALLER_THEME_DIR/render.awk" || return $?
  fetch_hook_file "$(installer_repo_join_var DIR_HOSTS_THEMES theme-schema.tsv)" "$INSTALLER_THEME_DIR/schema.tsv" || return $?
  for theme_group in base apps office; do
    fetch_hook_file "$(installer_repo_join_var DIR_HOSTS_THEMES "${theme_group}.env")" "$INSTALLER_THEME_DIR/${theme_group}.env" || return $?
  done
  if ! LC_ALL=C awk -f "$INSTALLER_THEME_DIR/validate.awk" \
      "$INSTALLER_THEME_DIR/schema.tsv" "$INSTALLER_THEME_DIR/base.env" \
      "$INSTALLER_THEME_DIR/apps.env" "$INSTALLER_THEME_DIR/office.env" \
      > "$INSTALLER_THEME_DIR/values.map"; then
    installer_fatal 'theme inputs failed validation; no theme assets were published'
    return 1
  fi
  # Schema allowlist plus literal grammar make sourcing safe: no expansion,
  # commands, quotes, backslashes or variable names outside the theme catalog.
  for theme_group in base apps office; do
    # shellcheck disable=SC1090,SC1091
    . "$INSTALLER_THEME_DIR/${theme_group}.env" || return $?
  done
  INSTALLER_THEME_MAP="$INSTALLER_THEME_DIR/values.map"
  LABWC_WALLPAPER_PATH="/${LABWC_WALLPAPER_DESKTOP_SWAYBG#hooks/target/}"
  LABWC_LOCK_BACKGROUND_PATH="/${LABWC_WALLPAPER_LOCKSCREEN_SWAYLOCK#hooks/target/}"
  LABWC_GREETER_BACKGROUND_PATH="/${LABWC_WALLPAPER_LOGIN_GTKGREET#hooks/target/}"
  INSTALLER_THEMES_LOADED=1
}

installer_theme_render_file() (
  theme_path=$1
  [ -f "$theme_path" ] && [ ! -L "$theme_path" ] || {
    installer_fatal "theme asset is not a regular file: $theme_path"
    exit 1
  }
  # Binary artwork and files with no appearance inputs remain byte-identical.
  # Use the source name when the destination is a temporary file named payload.
  case "${2:-$theme_path}" in
    *.png|*.jpg|*.jpeg|*.webp|*.gif|*.ico|*.ttf|*.otf|*.woff|*.woff2|*.gz|*.xz|*.bz2|*.zip|*.deb)
      exit 0 ;;
  esac
  if LC_ALL=C grep -q '__THEME_' "$theme_path"; then
    :
  else
    theme_probe_status=$?
    [ "$theme_probe_status" = 1 ] && exit 0
    installer_fatal "could not read theme asset: $theme_path"
    exit 1
  fi
  installer_load_themes || exit $?
  theme_parent=${theme_path%/*}
  [ "$theme_parent" != "$theme_path" ] || theme_parent=.
  theme_work=$(mktemp -d "${theme_parent}/.theme-render.XXXXXX") || exit $?
  trap 'rm -rf "$theme_work"' EXIT
  trap 'exit 129' HUP
  trap 'exit 130' INT
  trap 'exit 143' TERM
  cp -p "$theme_path" "$theme_work/rendered" || exit $?
  LC_ALL=C awk -f "$INSTALLER_THEME_DIR/render.awk" "$INSTALLER_THEME_MAP" "$theme_path" > "$theme_work/rendered" || exit $?
  mv -f "$theme_work/rendered" "$theme_path" || exit $?
)

installer_theme_render_tree() (
  theme_tree=$1
  installer_load_themes || exit $?
  theme_list=$(mktemp "${INSTALLER_THEME_DIR}/tree.XXXXXX") || exit $?
  trap 'rm -f "$theme_list"' EXIT
  trap 'exit 129' HUP
  trap 'exit 130' INT
  trap 'exit 143' TERM
  # Repository payload paths already reject whitespace and symbolic links.
  # Do not follow symlinks or interpret filenames as shell/awk code.
  find "$theme_tree" -type f -print > "$theme_list" || exit $?
  while IFS= read -r theme_file; do
    installer_render_logging_asset "$SEED_BASE" hooks/target/tree "$theme_file" || exit $?
    installer_theme_render_file "$theme_file" || exit $?
    case "$theme_file" in
      *.tmpl)
        if LC_ALL=C grep -Eq '__(INSTALLER|SYSTEMD|THEME)_[A-Z0-9_]+__' "$theme_file"; then
          installer_fatal "unrendered asset in template tree: $theme_file"; exit 1
        fi
        [ ! -e "${theme_file%.tmpl}" ] && [ ! -L "${theme_file%.tmpl}" ] || exit 1
        mv -- "$theme_file" "${theme_file%.tmpl}" || exit 1
        ;;
    esac
  done < "$theme_list"
)
