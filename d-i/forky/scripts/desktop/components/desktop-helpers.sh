#!/bin/sh
# Sourced installer module; edit this file directly.

desktop_render_labwc_environment_assets() {
  gsk_renderer_line=$(desktop_optional_env_assignment_line GSK_RENDERER "${LABWC_GSK_RENDERER:-opengl}")

  desktop_render_role_target_template \
    "etc/skel-desktop/.config/labwc/environment.tmpl" \
    "/etc/skel-desktop/.config/labwc/environment" \
    0644 \
    LABWC_WLR_RENDERER "${LABWC_WLR_RENDERER:-gles2}" \
    LABWC_GDK_DISABLE "${LABWC_GDK_DISABLE:-vulkan}" \
    LABWC_WLR_NO_HARDWARE_CURSORS "${LABWC_WLR_NO_HARDWARE_CURSORS:-1}" \
    LABWC_WLR_SCENE_DISABLE_DIRECT_SCANOUT "${LABWC_WLR_SCENE_DISABLE_DIRECT_SCANOUT:-1}" \
    LABWC_CURSOR_THEME "${LABWC_CURSOR_THEME}" \
    LABWC_CURSOR_SIZE "${LABWC_CURSOR_SIZE:-24}" \
    LABWC_GSK_RENDERER_LINE "$gsk_renderer_line"

  desktop_render_role_target_template \
    "etc/skel-desktop/.config/labwc/environment.d/10-wayland.env.tmpl" \
    "/etc/skel-desktop/.config/labwc/environment.d/10-wayland.env" \
    0644 \
    LABWC_WLR_RENDERER "${LABWC_WLR_RENDERER:-gles2}" \
    LABWC_GDK_DISABLE "${LABWC_GDK_DISABLE:-vulkan}" \
    LABWC_WLR_NO_HARDWARE_CURSORS "${LABWC_WLR_NO_HARDWARE_CURSORS:-1}" \
    LABWC_WLR_SCENE_DISABLE_DIRECT_SCANOUT "${LABWC_WLR_SCENE_DISABLE_DIRECT_SCANOUT:-1}" \
    LABWC_QT_QPA_PLATFORM "${LABWC_QT_QPA_PLATFORM:-wayland}" \
    LABWC_DESKTOP_QT_PLATFORMTHEME "${LABWC_DESKTOP_QT_PLATFORMTHEME}" \
    LABWC_GDK_BACKEND "${LABWC_GDK_BACKEND:-wayland}" \
    LABWC_SDL_VIDEODRIVER "${LABWC_SDL_VIDEODRIVER:-wayland}" \
    LABWC_CLUTTER_BACKEND "${LABWC_CLUTTER_BACKEND:-wayland}" \
    LABWC_GSK_RENDERER_LINE "$gsk_renderer_line"

  desktop_log "rendered_labwc_environment_assets renderer=${LABWC_WLR_RENDERER:-gles2} gsk=${LABWC_GSK_RENDERER:-opengl} gdk_disable=${LABWC_GDK_DISABLE:-vulkan} hardware_cursors=${LABWC_WLR_NO_HARDWARE_CURSORS:-1}"
}

desktop_render_labwc_session_wrappers() {
  desktop_render_role_target_template \
    "usr/local/bin/labwc-greeter-session.tmpl" \
    "/usr/local/bin/labwc-greeter-session" \
    0755 \
    LABWC_GREETER_WLR_RENDERER "${LABWC_GREETER_WLR_RENDERER:-gles2}" \
    LABWC_GREETER_GSK_RENDERER "${LABWC_GREETER_GSK_RENDERER:-opengl}" \
    LABWC_GREETER_GDK_DISABLE "${LABWC_GREETER_GDK_DISABLE:-vulkan}" \
    LABWC_GREETER_WLR_NO_HARDWARE_CURSORS "${LABWC_GREETER_WLR_NO_HARDWARE_CURSORS:-1}" \
    LABWC_DESKTOP_SESSION_COMMAND "${LABWC_DESKTOP_SESSION_COMMAND:-/usr/local/bin/labwc-session}"

  desktop_render_role_target_template \
    "usr/local/bin/labwc-session.tmpl" \
    "/usr/local/bin/labwc-session" \
    0755 \
    LABWC_QT_QPA_PLATFORM "${LABWC_QT_QPA_PLATFORM:-wayland}" \
    LABWC_DESKTOP_QT_PLATFORMTHEME "${LABWC_DESKTOP_QT_PLATFORMTHEME}" \
    LABWC_GDK_BACKEND "${LABWC_GDK_BACKEND:-wayland}" \
    LABWC_SDL_VIDEODRIVER "${LABWC_SDL_VIDEODRIVER:-wayland}" \
    LABWC_CLUTTER_BACKEND "${LABWC_CLUTTER_BACKEND:-wayland}" \
    LABWC_CURSOR_THEME "${LABWC_CURSOR_THEME}" \
    LABWC_CURSOR_SIZE "${LABWC_CURSOR_SIZE:-24}" \
    LABWC_WLR_RENDERER "${LABWC_WLR_RENDERER:-gles2}" \
    LABWC_GSK_RENDERER "${LABWC_GSK_RENDERER:-opengl}" \
    LABWC_GDK_DISABLE "${LABWC_GDK_DISABLE:-vulkan}" \
    LABWC_WLR_NO_HARDWARE_CURSORS "${LABWC_WLR_NO_HARDWARE_CURSORS:-1}" \
    LABWC_WLR_SCENE_DISABLE_DIRECT_SCANOUT "${LABWC_WLR_SCENE_DISABLE_DIRECT_SCANOUT:-1}"

  desktop_log "rendered_labwc_session_wrappers session_renderer=${LABWC_WLR_RENDERER:-gles2} greeter_renderer=${LABWC_GREETER_WLR_RENDERER:-gles2}"
}

desktop_configure_local_mail_delivery() {
  : "${ACCOUNT_USERNAME:?ACCOUNT_USERNAME must be set for desktop local mail delivery}"
  mailname_value=$(desktop_mailname_value)

  desktop_render_shared_target_template "etc/mailname.tmpl" "/etc/mailname" 0644 \
    MAILNAME "$mailname_value"
  desktop_render_role_target_template "etc/aliases.tmpl" "/etc/aliases" 0644 \
    ACCOUNT_USERNAME "$ACCOUNT_USERNAME"
  desktop_stage_role_asset etc/apt/listchanges.conf /etc/apt/listchanges.conf 0644
  desktop_stage_role_asset etc/apt/apt.conf.d/60desktop-local-mail.conf /etc/apt/apt.conf.d/60desktop-local-mail.conf 0644

  desktop_log "configured_desktop_local_mail account=${ACCOUNT_USERNAME} mailname=${mailname_value}"
}

desktop_render_kanshi_config() {
  desktop_kanshi_enabled || return 0
  desktop_render_role_target_template \
    "etc/skel-desktop/.config/kanshi/config" \
    "/etc/skel-desktop/.config/kanshi/config" \
    0644 \
    LABWC_OUTPUT_EXTERNAL_PREFERRED_WIDTH "${LABWC_OUTPUT_EXTERNAL_PREFERRED_WIDTH:-1920}" \
    LABWC_OUTPUT_EXTERNAL_PREFERRED_HEIGHT "${LABWC_OUTPUT_EXTERNAL_PREFERRED_HEIGHT:-1080}" \
    LABWC_OUTPUT_EXTERNAL_PREFERRED_REFRESH_HZ "${LABWC_OUTPUT_EXTERNAL_PREFERRED_REFRESH_HZ:-120}" \
    LABWC_OUTPUT_EXTERNAL_SCALE "${LABWC_OUTPUT_EXTERNAL_SCALE:-1}" \
    LABWC_OUTPUT_INTERNAL_SCALE "${LABWC_OUTPUT_INTERNAL_SCALE:-1}" \
    LABWC_OUTPUT_SCALE "${LABWC_OUTPUT_SCALE:-1}"

  desktop_log "rendered_kanshi_config external_mode=${LABWC_OUTPUT_EXTERNAL_PREFERRED_WIDTH:-1920}x${LABWC_OUTPUT_EXTERNAL_PREFERRED_HEIGHT:-1080}@${LABWC_OUTPUT_EXTERNAL_PREFERRED_REFRESH_HZ:-120}Hz external_scale=${LABWC_OUTPUT_EXTERNAL_SCALE:-1}"
}

desktop_render_terminal_configs() {
  terminal_font_family=${LABWC_TERMINAL_FONT_FAMILY}
  terminal_font_size=${LABWC_TERMINAL_FONT_SIZE:-12}

  desktop_render_role_target_template \
    "etc/skel-desktop/.config/foot/foot.ini" \
    "/etc/skel-desktop/.config/foot/foot.ini" \
    0644 \
    LABWC_TERMINAL_FONT_FAMILY "$terminal_font_family" \
    LABWC_TERMINAL_FONT_SIZE "$terminal_font_size" \
    LABWC_TERMINAL_BACKGROUND_OPACITY "${LABWC_TERMINAL_BACKGROUND_OPACITY}" \
    LABWC_TERMINAL_WINDOW_COLUMNS "${LABWC_TERMINAL_WINDOW_COLUMNS:-96}" \
    LABWC_TERMINAL_WINDOW_ROWS "${LABWC_TERMINAL_WINDOW_ROWS:-26}"
  desktop_render_role_target_template \
    "etc/skel-desktop/.config/kitty/kitty.conf" \
    "/etc/skel-desktop/.config/kitty/kitty.conf" \
    0644 \
    LABWC_TERMINAL_FONT_FAMILY "$terminal_font_family" \
    LABWC_TERMINAL_FONT_SIZE "$terminal_font_size" \
    LABWC_TERMINAL_BACKGROUND_OPACITY "${LABWC_TERMINAL_BACKGROUND_OPACITY}" \
    LABWC_TERMINAL_WINDOW_COLUMNS "${LABWC_TERMINAL_WINDOW_COLUMNS:-96}" \
    LABWC_TERMINAL_WINDOW_ROWS "${LABWC_TERMINAL_WINDOW_ROWS:-26}"

  run_in_target "validate rendered Foot configuration" \
    /usr/bin/env LC_ALL=C.UTF-8 /usr/bin/foot --check-config \
    --config /etc/skel-desktop/.config/foot/foot.ini || return $?
  desktop_log "rendered_terminal_configs font_family=${terminal_font_family} font_size=${terminal_font_size}"
}

desktop_render_gtk_settings() {
  gtk_font_size=${LABWC_GTK_FONT_SIZE:-12}

  for gtk_variant in 3 4; do
    template_path="etc/skel-desktop/.config/gtk-${gtk_variant}.0/settings.ini.tmpl"
    desktop_render_role_target_template \
      "$template_path" \
      "/etc/skel-desktop/.config/gtk-${gtk_variant}.0/settings.ini" \
      0644 \
      LABWC_GTK_FONT_SIZE "$gtk_font_size" \
      LABWC_GTK_CURSOR_SIZE "$LABWC_GTK_CURSOR_SIZE"
    desktop_render_role_target_template \
      "$template_path" \
      "/etc/xdg/gtk-${gtk_variant}.0/settings.ini" \
      0644 \
      LABWC_GTK_FONT_SIZE "$gtk_font_size" \
      LABWC_GTK_CURSOR_SIZE "$LABWC_GTK_CURSOR_SIZE"
  done
  desktop_log "rendered_gtk_settings font_size=${gtk_font_size}"
}

desktop_render_qt6ct_config() {
  for target_path in \
    /etc/skel-desktop/.config/qt6ct/qt6ct.conf \
    /etc/xdg/qt6ct/qt6ct.conf
  do
    desktop_render_role_target_template \
      etc/skel-desktop/.config/qt6ct/qt6ct.conf.tmpl \
      "$target_path" \
      0644 \
      LABWC_QT_FONT_SIZE "${LABWC_QT_FONT_SIZE:-11}" \
      LABWC_QT_FIXED_FONT_SIZE "${LABWC_QT_FIXED_FONT_SIZE:-12}"
  done
  desktop_log "rendered_qt6ct_config icon_theme=${LABWC_DESKTOP_QT_ICON_THEME} font_size=${LABWC_QT_FONT_SIZE:-11}"
}

desktop_render_fuzzel_configs() {
  desktop_validate_fuzzel_geometry
  for fuzzel_config in base fuzzel menu computer-management; do
    desktop_render_role_target_template \
      "etc/skel-desktop/.config/fuzzel/${fuzzel_config}.ini.tmpl" \
      "/etc/skel-desktop/.config/fuzzel/${fuzzel_config}.ini" 0644
  done
  desktop_log "rendered_fuzzel_configs geometry=runtime classes=internal,external,default"
}

desktop_render_crystal_dock_appearance() {
  for target_path in \
    /etc/skel-desktop/.config/crystal-dock/labwc/appearance.conf \
    /etc/xdg/crystal-dock/labwc/appearance.conf
  do
    desktop_render_role_target_template \
      "etc/skel-desktop/.config/crystal-dock/labwc/appearance.conf.tmpl" \
      "$target_path" \
      0644 \
      LABWC_CRYSTAL_DOCK_MINIMUM_ICON_SIZE "${LABWC_CRYSTAL_DOCK_MINIMUM_ICON_SIZE:-50}" \
      LABWC_CRYSTAL_DOCK_MAXIMUM_ICON_SIZE "${LABWC_CRYSTAL_DOCK_MAXIMUM_ICON_SIZE:-80}" \
      LABWC_CRYSTAL_DOCK_TOOLTIP_FONT_SIZE "${LABWC_CRYSTAL_DOCK_TOOLTIP_FONT_SIZE:-13}" \
      LABWC_CRYSTAL_DOCK_APP_MENU_ICON_SIZE "${LABWC_CRYSTAL_DOCK_APP_MENU_ICON_SIZE:-40}" \
      LABWC_CRYSTAL_DOCK_APP_MENU_FONT_SIZE "${LABWC_CRYSTAL_DOCK_APP_MENU_FONT_SIZE:-15}" \
      LABWC_CRYSTAL_DOCK_CLOCK_FONT_SCALE_FACTOR "${LABWC_CRYSTAL_DOCK_CLOCK_FONT_SCALE_FACTOR:-1.0}"
  done
  desktop_log "rendered_crystal_dock_appearance min_icon=${LABWC_CRYSTAL_DOCK_MINIMUM_ICON_SIZE:-50} max_icon=${LABWC_CRYSTAL_DOCK_MAXIMUM_ICON_SIZE:-80}"
}

desktop_render_chromium_flags() {
  desktop_render_role_target_template \
    "etc/chromium.d/90-performance-flags.tmpl" \
    "/etc/chromium.d/90-performance-flags" \
    0644
  desktop_log "rendered_chromium_flags gpu_wayland_defaults=managed"
}

desktop_render_note_app_defaults() {
  : "${DIR_HOME_DOCUMENTS:?DIR_HOME_DOCUMENTS must be set for desktop note apps}"
  : "${DIR_HOME_PICTURES:?DIR_HOME_PICTURES must be set for desktop note apps}"

  gtk_font_size=${LABWC_GTK_FONT_SIZE:-12}

  desktop_render_role_target_template \
    "etc/skel-desktop/.config/xournalpp/settings.xml.tmpl" \
    "/etc/skel-desktop/.config/xournalpp/settings.xml" \
    0644 \
    DIR_HOME_DOCUMENTS "$DIR_HOME_DOCUMENTS" \
    DIR_HOME_PICTURES "$DIR_HOME_PICTURES" \
    LABWC_GTK_FONT_SIZE "$gtk_font_size"
  desktop_stage_role_asset \
    etc/skel-desktop/.config/gnote/addins/global.ini \
    /etc/skel-desktop/.config/gnote/addins/global.ini \
    0644
  desktop_render_role_target_template \
    "usr/share/glib-2.0/schemas/90-desktop-gnote.gschema.override.tmpl" \
    "/usr/share/glib-2.0/schemas/90-desktop-gnote.gschema.override" \
    0644 \
    DIR_HOME_DOCUMENTS "$DIR_HOME_DOCUMENTS" \
    LABWC_GTK_FONT_SIZE "$gtk_font_size"
  desktop_stage_role_asset \
    usr/share/glib-2.0/schemas/90-desktop-window-buttons.gschema.override \
    /usr/share/glib-2.0/schemas/90-desktop-window-buttons.gschema.override \
    0644
  desktop_stage_role_asset \
    usr/share/glib-2.0/schemas/90-desktop-liferea.gschema.override \
    /usr/share/glib-2.0/schemas/90-desktop-liferea.gschema.override \
    0644
  desktop_log "rendered_note_app_defaults documents=${DIR_HOME_DOCUMENTS} pictures=${DIR_HOME_PICTURES} gtk_font_size=${gtk_font_size}"
}

desktop_stage_obsidian_default_vault() {
  vault_root=/target/etc/skel-desktop/Syncthing/obsidian-md

  install -d -m 0700 \
    /target/etc/skel-desktop/Syncthing \
    "$vault_root" \
    "$vault_root/.obsidian" \
    "$vault_root/.obsidian/snippets" \
    "$vault_root/.obsidian/themes" \
    "$vault_root/.obsidian/themes/evergreen-notes" \
    "$vault_root/.trash" \
    "$vault_root/archive" \
    "$vault_root/attachments" \
    "$vault_root/daily" \
    "$vault_root/inbox" \
    "$vault_root/templates"

  desktop_stage_role_asset etc/skel-desktop/Syncthing/obsidian-md/.obsidian/app.json /etc/skel-desktop/Syncthing/obsidian-md/.obsidian/app.json 0600
  desktop_stage_role_asset etc/skel-desktop/Syncthing/obsidian-md/.obsidian/appearance.json /etc/skel-desktop/Syncthing/obsidian-md/.obsidian/appearance.json 0600
  desktop_stage_role_asset etc/skel-desktop/Syncthing/obsidian-md/.obsidian/backlink.json /etc/skel-desktop/Syncthing/obsidian-md/.obsidian/backlink.json 0600
  desktop_stage_role_asset etc/skel-desktop/Syncthing/obsidian-md/.obsidian/bookmarks.json /etc/skel-desktop/Syncthing/obsidian-md/.obsidian/bookmarks.json 0600
  desktop_stage_role_asset etc/skel-desktop/Syncthing/obsidian-md/.obsidian/command-palette.json /etc/skel-desktop/Syncthing/obsidian-md/.obsidian/command-palette.json 0600
  desktop_stage_role_asset etc/skel-desktop/Syncthing/obsidian-md/.obsidian/community-plugins.json /etc/skel-desktop/Syncthing/obsidian-md/.obsidian/community-plugins.json 0600
  desktop_stage_role_asset etc/skel-desktop/Syncthing/obsidian-md/.obsidian/core-plugins.json /etc/skel-desktop/Syncthing/obsidian-md/.obsidian/core-plugins.json 0600
  desktop_stage_role_asset etc/skel-desktop/Syncthing/obsidian-md/.obsidian/daily-notes.json /etc/skel-desktop/Syncthing/obsidian-md/.obsidian/daily-notes.json 0600
  desktop_stage_role_asset etc/skel-desktop/Syncthing/obsidian-md/.obsidian/graph.json /etc/skel-desktop/Syncthing/obsidian-md/.obsidian/graph.json 0600
  desktop_stage_role_asset etc/skel-desktop/Syncthing/obsidian-md/.obsidian/hotkeys.json /etc/skel-desktop/Syncthing/obsidian-md/.obsidian/hotkeys.json 0600
  desktop_stage_role_asset etc/skel-desktop/Syncthing/obsidian-md/.obsidian/templates.json /etc/skel-desktop/Syncthing/obsidian-md/.obsidian/templates.json 0600
  desktop_stage_role_asset etc/skel-desktop/Syncthing/obsidian-md/.obsidian/types.json /etc/skel-desktop/Syncthing/obsidian-md/.obsidian/types.json 0600
  desktop_stage_role_asset etc/skel-desktop/Syncthing/obsidian-md/.obsidian/snippets/ux.css /etc/skel-desktop/Syncthing/obsidian-md/.obsidian/snippets/ux.css 0600
  desktop_stage_role_asset etc/skel-desktop/Syncthing/obsidian-md/.obsidian/themes/evergreen-notes/manifest.json /etc/skel-desktop/Syncthing/obsidian-md/.obsidian/themes/evergreen-notes/manifest.json 0600
  desktop_stage_role_asset etc/skel-desktop/Syncthing/obsidian-md/.obsidian/themes/evergreen-notes/theme.css /etc/skel-desktop/Syncthing/obsidian-md/.obsidian/themes/evergreen-notes/theme.css 0600
  desktop_stage_role_asset etc/skel-desktop/Syncthing/obsidian-md/home.md /etc/skel-desktop/Syncthing/obsidian-md/home.md 0600
  desktop_stage_role_asset etc/skel-desktop/Syncthing/obsidian-md/archive/index.md /etc/skel-desktop/Syncthing/obsidian-md/archive/index.md 0600
  desktop_stage_role_asset etc/skel-desktop/Syncthing/obsidian-md/daily/index.md /etc/skel-desktop/Syncthing/obsidian-md/daily/index.md 0600
  desktop_stage_role_asset etc/skel-desktop/Syncthing/obsidian-md/inbox/welcome.md /etc/skel-desktop/Syncthing/obsidian-md/inbox/welcome.md 0600
  desktop_stage_role_asset etc/skel-desktop/Syncthing/obsidian-md/templates/daily-note-template.md /etc/skel-desktop/Syncthing/obsidian-md/templates/daily-note-template.md 0600
  desktop_stage_role_asset etc/skel-desktop/Syncthing/obsidian-md/templates/note-template.md /etc/skel-desktop/Syncthing/obsidian-md/templates/note-template.md 0600
  desktop_stage_role_asset etc/skel-desktop/Syncthing/.stignore /etc/skel-desktop/Syncthing/.stignore 0600

  desktop_log "staged_obsidian_default_vault path=/etc/skel-desktop/Syncthing/obsidian-md theme=evergreen-notes"
}

desktop_compile_glib_schemas() {
  # shellcheck disable=SC2016
  run_in_target "compile desktop glib schemas" /bin/sh -c '
set -eu
compiler=

if command -v glib-compile-schemas >/dev/null 2>&1; then
  compiler=$(command -v glib-compile-schemas)
else
  compiler=$(find /usr/lib -path "*/glib-2.0/glib-compile-schemas" -type f | sed -n "1p")
fi

[ -n "$compiler" ] || {
  printf "fatal: glib-compile-schemas is unavailable in target\n" >&2
  exit 1
}
[ -d /usr/share/glib-2.0/schemas ] || {
  printf "fatal: target GLib schema directory is missing\n" >&2
  exit 1
}

"$compiler" /usr/share/glib-2.0/schemas
' sh
  desktop_log "compiled_glib_schemas scope=desktop"
}

# Remove only the obsolete project-owned shutdown graph on republication.
# Never start/stop/enable those units while staging an unattended installation.
desktop_remove_legacy_power_transactions() (
  set -eu
  for power_action in reboot poweroff; do
    for power_kind in service target; do
      ensure_target_asset_parent "/etc/systemd/system/labwc-power-${power_action}.${power_kind}"
      power_path=$(target_asset_host_path "/etc/systemd/system/labwc-power-${power_action}.${power_kind}")
      [ ! -d "$power_path" ] || installer_fatal "obsolete power unit is a directory: $power_path"
      rm -f -- "$power_path"
    done
  done
)

desktop_install_user_resource_policy() {
  stage_target_systemd_manager_accounting || return 1
  user_slice_dropin=/etc/systemd/system/user-1000.slice.d/50-resource-accounting.conf
  user_manager_dropin=/etc/systemd/system/user@.service.d/50-oom-score.conf
  user_manager_config=/etc/systemd/user.conf.d/50-resource-defaults.conf

  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/system/user-1000.slice.d/50-resource-accounting.conf)" \
    "$user_slice_dropin" \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/system/user@.service.d/50-oom-score.conf)" \
    "$user_manager_dropin" \
    0644
  stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/user.conf.d/50-resource-defaults.conf)" \
    "$user_manager_config" \
    0644

  # Render before desktop_install_user_config copies .config/systemd into
  # ACCOUNT_HOME. Only existing repository-owned units get class assignments.
  systemd_resource_placeholder_map >/dev/null || return 1
  for resource_asset in \
    etc/skel-desktop/.config/systemd/user/session.slice.d/60-resources.conf \
    etc/skel-desktop/.config/systemd/user/app.slice.d/60-resources.conf \
    etc/skel-desktop/.config/systemd/user/background.slice.d/60-resources.conf
  do
    render_target_resource_asset \
      "$(installer_repo_join_var DIR_HOOKS_TARGET "$resource_asset")" \
      "/$resource_asset" 0644 || return 1
  done
  for resource_unit in \
    labwc-compositor kanshi labwc-output-watch swayidle labwc-calendar-sync \
    labwc-kwallet-portal labwc-ssh-key-load waybar crystal-dock
  do
    # Optional services (notably kanshi) may be deliberately omitted by a
    # profile. Never create orphaned drop-ins or enable a disabled service.
    resource_base="/etc/skel-desktop/.config/systemd/user/${resource_unit}.service"
    [ -f "$(target_asset_host_path "$resource_base")" ] || continue
    resource_asset="etc/skel-desktop/.config/systemd/user/${resource_unit}.service.d/60-resource-class.conf"
    stage_target_asset \
      "$(installer_repo_join_var DIR_HOOKS_TARGET "$resource_asset")" \
      "/$resource_asset" 0644 || return 1
  done

  # These narrowly scoped overrides add no dependencies or lifecycle changes.
  for resource_pair in \
    labwc-compositor:60-resources.conf \
    labwc-kwallet-portal:70-no-core.conf
  do
    resource_unit=${resource_pair%%:*}
    resource_name=${resource_pair#*:}
    resource_base="/etc/skel-desktop/.config/systemd/user/${resource_unit}.service"
    [ -f "$(target_asset_host_path "$resource_base")" ] || continue
    resource_asset="etc/skel-desktop/.config/systemd/user/${resource_unit}.service.d/${resource_name}"
    render_target_resource_asset \
      "$(installer_repo_join_var DIR_HOOKS_TARGET "$resource_asset")" \
      "/$resource_asset" 0644 || return 1
  done
  # Runtime-created services and app-* scopes have no base files to probe.
  # The scope class is explicit; its original lifecycle drop-in is unchanged.
  for resource_leaf in \
    app-.scope.d/60-resource-class.conf \
    labwc-bitwarden-.service.d/70-no-core.conf \
    labwc-power-lock-.service.d/60-resource-class.conf \
    labwc-power-lock-.service.d/70-no-core.conf
  do
    resource_asset="etc/skel-desktop/.config/systemd/user/$resource_leaf"
    render_target_resource_asset \
      "$(installer_repo_join_var DIR_HOOKS_TARGET "$resource_asset")" \
      "/$resource_asset" 0644 || return 1
  done
  desktop_install_vendor_resource_policy || return 1

  desktop_log \
    "staged_user_resource_policy slice=user-1000 accounting=${user_slice_dropin} user_manager=${user_manager_dropin} defaults=${user_manager_config}"
}

# Package-owned user services retain their existing fragments and activation.
# Only resource/security drop-ins are installed, and only for available units.
desktop_install_vendor_resource_policy() (
  set -eu
  for resource_pair in \
    hyprpolkitagent.service:60-resource-class.conf \
    hyprpolkitagent.service:70-no-core.conf \
    mako.service:60-resource-class.conf \
    ssh-agent.service:60-resource-class.conf \
    wireplumber.service:60-resource-class.conf \
    pipewire.service:60-resources.conf \
    pipewire-pulse.service:60-resources.conf \
    filter-chain.service:60-resources.conf \
    xdg-desktop-portal.service:60-resource-class.conf
  do
    resource_unit=${resource_pair%%:*}
    resource_name=${resource_pair#*:}
    resource_path=$(desktop_user_unit_source_path "$resource_unit" || true)
    [ -n "$resource_path" ] || continue
    resource_asset="etc/systemd/user/${resource_unit}.d/${resource_name}"
    render_target_resource_asset \
      "$(installer_repo_join_var DIR_HOOKS_TARGET "$resource_asset")" \
      "/$resource_asset" 0644 || exit 1
  done
  # One shared class policy for the backend family, not three identical copies.
  for resource_unit in xdg-desktop-portal-gtk.service xdg-desktop-portal-wlr.service xdg-desktop-portal-lxqt.service; do
    resource_path=$(desktop_user_unit_source_path "$resource_unit" || true)
    [ -n "$resource_path" ] || continue
    resource_asset=etc/systemd/user/xdg-desktop-portal-.service.d/60-resource-class.conf
    render_target_resource_asset \
      "$(installer_repo_join_var DIR_HOOKS_TARGET "$resource_asset")" \
      "/$resource_asset" 0644 || exit 1
    break
  done
)

desktop_configure_greeter_access() {
  : "${LABWC_GREETER_USER:?LABWC_GREETER_USER must be set}"

  # The greeter runs before any real user session exists, so grant the
  # compositor access paths it needs up front.
  # shellcheck disable=SC2016
  run_in_target "configure Labwc greeter seat and DRM access" /bin/sh -c '
set -eu
greeter_user=$1
requested_groups="seat render video"
existing_groups=
missing_groups=
current_groups=$(id -nG "$greeter_user")

for group_name in $requested_groups; do
  if getent group "$group_name" >/dev/null 2>&1; then
    existing_groups="${existing_groups:+$existing_groups,}$group_name"
    case " $current_groups " in
      *" $group_name "*) ;;
      *)
        missing_groups="${missing_groups:+$missing_groups,}$group_name"
        ;;
    esac
  fi
done

[ -n "$existing_groups" ] || {
  printf "fatal: no greeter access groups are available for %s\n" "$greeter_user" >&2
  exit 1
}

if [ -n "$missing_groups" ]; then
  usermod -a -G "$missing_groups" "$greeter_user"
  current_groups=$(id -nG "$greeter_user")
fi
printf "desktop_greeter_access user=%s requested=%s current=%s\n" \
  "$greeter_user" \
  "$existing_groups" \
  "$current_groups"
' sh "$LABWC_GREETER_USER"
  desktop_log "configured_greeter_access user=${LABWC_GREETER_USER}"
}

