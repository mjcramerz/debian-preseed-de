#!/bin/sh
# Sourced installer module; edit this file directly.

desktop_install_user_config() {
  : "${ACCOUNT_USERNAME:?ACCOUNT_USERNAME must be set}"
  : "${ACCOUNT_HOME:?ACCOUNT_HOME must be set}"

  desktop_log "installing primary account desktop config user=${ACCOUNT_USERNAME} home=${ACCOUNT_HOME}"
  # shellcheck disable=SC2016
  run_in_target "install Labwc desktop config for primary account" /bin/sh -c '
set -eu
account_user=$1
account_home=$2
kanshi_enabled=$3
copied_dirs=0
copied_files=0

case "$account_home" in
  /*) ;;
  *) printf "fatal: account home must be absolute\n" >&2; exit 1 ;;
esac
case "$account_home" in
  /|*..*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/-]*)
    printf "fatal: account home contains unsupported path syntax: %s\n" "$account_home" >&2
    exit 1
    ;;
esac

uid=$(id -u "$account_user")
gid=$(id -g "$account_user")

  install -d -m 0700 "$account_home" "$account_home/.config"
  install -d -m 0700 "$account_home/.cache"
  chown "$uid:$gid" "$account_home/.cache"
  for rel in \
    .profile.d \
    .config/labwc \
    .config/waypaper \
    .config/waybar \
    .config/tomat \
    .config/cargo \
    .config/mise \
    .config/featherpad \
    .config/foot \
    .config/git \
    .config/gitops \
    .config/gnote \
    .config/GottCode \
    .config/zathura \
    .local/share/GottCode \
    .local/share/dbus-1 \
    .cache/recoll \
    .config/Recoll.org \
    .recoll \
    .config/fontconfig \
    .config/kitty \
    .config/micro \
    .config/nano \
    .config/mpv \
    .config/nvim \
    .config/qalculate \
    .config/xarchiver \
    .config/task \
    .config/retroarch \
    .config/sleek \
    .config/tesseract \
    .config/xfce4 \
    .config/btop \
    .config/Code \
    .config/autostart \
    .config/chromium \
    .config/fzf \
    .config/fuzzel \
    .config/Thunar \
    .config/crystal-dock \
    .config/mako \
    .config/satty \
    .config/wayscriber \
    .config/swaylock \
    .config/wireplumber \
    .config/gtk-3.0 \
    .config/gtk-4.0 \
    .config/keepassxc \
    .config/microsoft-edge \
    .config/obsidian \
    .config/zoom \
    Syncthing/obsidian-md \
    .config/qt6ct \
    .config/systemd \
    .config/vim \
    .config/vivaldi \
    .config/xournalpp \
    .config/xdg-desktop-portal
  do
  src="/etc/skel-desktop/${rel}"
  dst="${account_home}/${rel}"
  [ -d "$src" ] || { printf "fatal: missing skel source: %s\n" "$src" >&2; exit 1; }
  install -d -m 0700 "$dst"
  cp -a "$src/." "$dst/"
  chown -R "$uid:$gid" "$dst"
  copied_dirs=$((copied_dirs + 1))
done
for user_systemd_dir in \
  "$account_home/.config/systemd" \
  "$account_home/.config/systemd/user" \
  "$account_home/.config/systemd/user"/*.d
do
  [ -d "$user_systemd_dir" ] || continue
  chmod 0700 "$user_systemd_dir"
  chown "$uid:$gid" "$user_systemd_dir"
done
if [ "$kanshi_enabled" = true ]; then
  src=/etc/skel-desktop/.config/kanshi
  dst="$account_home/.config/kanshi"
  [ -d "$src" ] && [ ! -L "$src" ] || exit 1
  [ ! -L "$dst" ] || exit 1
  install -d -m 0700 "$dst"
  cp -a "$src/." "$dst/"
  chown -R "$uid:$gid" "$dst"
  copied_dirs=$((copied_dirs + 1))
fi
if [ -d /etc/skel-desktop/.config/bazel ]; then
  src=/etc/skel-desktop/.config/bazel
  dst="${account_home}/.config/bazel"
  install -d -m 0700 "$dst"
  cp -a "$src/." "$dst/"
  chown -R "$uid:$gid" "$dst"
  copied_dirs=$((copied_dirs + 1))
fi
install -d -m 0700 "$account_home/.local/share/applications"
chown "$uid:$gid" "$account_home/.local/share/applications"
install -m 0600 /etc/skel-desktop/.local/share/applications/tutanota-desktop.desktop \
  "$account_home/.local/share/applications/tutanota-desktop.desktop"
chown "$uid:$gid" "$account_home/.local/share/applications/tutanota-desktop.desktop"
for private_dir in \
  "$account_home/.local/share/task" \
  "$account_home/.local/share/task/hooks" \
  "$account_home/Syncthing" \
  "$account_home/Syncthing/keepassxc" \
  "$account_home/Syncthing/keepassxc/backups" \
  "$account_home/Syncthing/obsidian-md" \
  "$account_home/Syncthing/obsidian-md/.obsidian" \
  "$account_home/Syncthing/obsidian-md/.obsidian/snippets" \
  "$account_home/Syncthing/obsidian-md/.obsidian/themes" \
  "$account_home/Syncthing/obsidian-md/.obsidian/themes/evergreen-notes" \
  "$account_home/Syncthing/obsidian-md/.trash" \
  "$account_home/Syncthing/obsidian-md/archive" \
  "$account_home/Syncthing/obsidian-md/attachments" \
  "$account_home/Syncthing/obsidian-md/daily" \
  "$account_home/Syncthing/obsidian-md/inbox" \
  "$account_home/Syncthing/obsidian-md/templates"
do
  install -d -m 0700 "$private_dir"
  chown "$uid:$gid" "$private_dir"
done
rm -f "$account_home/.config/labwc/xinitrc"
  for rel_file in .profile .bash_profile .bashrc .bash_aliases .zshenv .zprofile .zshrc .zlogout .zsh_aliases .dircolors .vimrc .config/kdiff3rc .config/kwalletrc .config/starship.toml .config/xdg-terminals.list .config/mimeapps.list .config/user-dirs.dirs Syncthing/.stignore; do
  src="/etc/skel-desktop/${rel_file}"
  dst="${account_home}/${rel_file}"
  [ -r "$src" ] || { printf "fatal: missing skel source: %s\n" "$src" >&2; exit 1; }
  file_mode=0600
  parent_mode=0700
  if [ "$rel_file" = Syncthing/.stignore ]; then
    file_mode=0600
    parent_mode=0700
  fi
  install -d -m "$parent_mode" "$(dirname "$dst")"
  install -m "$file_mode" "$src" "$dst"
  chown "$uid:$gid" "$dst"
  copied_files=$((copied_files + 1))
done
  chown "$uid:$gid" "$account_home" "$account_home/.config"
  chmod 0700 "$account_home" "$account_home/.config"
if [ -x /usr/bin/vivaldi-stable ]; then
  for vivaldi_dir in \
    "$account_home/.cache" \
    "$account_home/.cache/vivaldi" \
    "$account_home/.config/vivaldi"
  do
    install -d -m 0700 "$vivaldi_dir"
    chown "$uid:$gid" "$vivaldi_dir"
  done
fi
if command -v /usr/local/bin/labwc-sync-application-launchers >/dev/null 2>&1; then
  /usr/local/bin/labwc-sync-application-launchers "$account_user" "$account_home"
fi
find "$account_home" -xdev -type d -exec chmod 0700 {} +
find "$account_home" -xdev -type f -perm /0100 -exec chmod 0700 {} +
find "$account_home" -xdev -type f ! -perm /0100 -exec chmod 0600 {} +
# Unit files and drop-ins are data, never programs. Do not preserve execute
# bits from a copied/restored skeleton on Whisper or other user units.
find "$account_home/.config/systemd/user" -xdev -type f -exec chmod 0600 {} +
zsh_path=$(command -v zsh 2>/dev/null || true)
if [ -n "$zsh_path" ]; then
  usermod -s "$zsh_path" "$account_user"
fi
account_shell=$(getent passwd "$account_user" | cut -d: -f7)
printf "desktop_account_config user=%s home=%s copied_dirs=%s copied_files=%s shell=%s\n" "$account_user" "$account_home" "$copied_dirs" "$copied_files" "$account_shell"
' sh "$ACCOUNT_USERNAME" "$ACCOUNT_HOME" "$(if desktop_kanshi_enabled; then printf true; else printf false; fi)"
  desktop_install_primary_account_calendar_stack
  desktop_bootstrap_primary_account_gpg_key
  run_in_target "publish private browser imports in primary account Downloads" \
    /usr/local/libexec/install-browser-imports --user "$ACCOUNT_USERNAME"
  desktop_log "installed primary account desktop config user=${ACCOUNT_USERNAME}"
}

