#!/bin/sh
# Profile-pinned font data. Only the repository helper runs as root; archive
# contents are never executed. User publication/cache explicitly drops uid.
desktop_install_fonts() (
  set -eu
  : "${ACCOUNT_USERNAME:?ACCOUNT_USERNAME must be set}"
  : "${ACCOUNT_HOME:?ACCOUNT_HOME must be set}"
  : "${LABWC_FONT_FIRACODE_URL:?font URL must be set}"
  : "${LABWC_FONT_FIRACODE_SHA256:?font SHA-256 must be set}"
  : "${LABWC_FONT_SYMBOLS_URL:?font URL must be set}"
  : "${LABWC_FONT_SYMBOLS_SHA256:?font SHA-256 must be set}"
  : "${LABWC_FONT_PROFONT_URL:?font URL must be set}"
  : "${LABWC_FONT_PROFONT_SHA256:?font SHA-256 must be set}"
  : "${LABWC_FONT_APTOS_URL:?font URL must be set}"
  : "${LABWC_FONT_APTOS_SHA256:?font SHA-256 must be set}"
  : "${LABWC_FONT_MICROSOFT_URL:?font URL must be set}"
  : "${LABWC_FONT_MICROSOFT_SHA256:?font SHA-256 must be set}"
  helper=/usr/local/libexec/installer-desktop-fonts
  helper_host=$(target_asset_host_path "$helper")
  trap 'rm -f -- "$helper_host"' EXIT
  trap 'exit 129' HUP
  trap 'exit 130' INT
  trap 'exit 143' TERM
  stage_target_asset \
    "$(installer_repo_join_var DIR_SCRIPTS_DESKTOP fonts-install.py)" "$helper" 0700
  run_in_target "install pinned desktop fonts and refresh user font caches" \
    /usr/bin/env -i HOME=/root LC_ALL=C PATH=/usr/sbin:/usr/bin:/sbin:/bin \
    /usr/bin/timeout --signal=TERM --kill-after=5s 1800s \
    /usr/bin/python3 -I "$helper" \
    --account "$ACCOUNT_USERNAME" --home "$ACCOUNT_HOME" \
    --archive FiraCode "$LABWC_FONT_FIRACODE_URL" "$LABWC_FONT_FIRACODE_SHA256" \
    --archive NerdFontsSymbolsOnly "$LABWC_FONT_SYMBOLS_URL" "$LABWC_FONT_SYMBOLS_SHA256" \
    --archive ProFont "$LABWC_FONT_PROFONT_URL" "$LABWC_FONT_PROFONT_SHA256" \
    --archive MicrosoftAptosFonts "$LABWC_FONT_APTOS_URL" "$LABWC_FONT_APTOS_SHA256" \
    --archive microsoft-fonts "$LABWC_FONT_MICROSOFT_URL" "$LABWC_FONT_MICROSOFT_SHA256"
  desktop_log "installed_pinned_fonts user=${ACCOUNT_USERNAME} location=.local/share/icons/terminal-fonts"
)
