# Bash login profile. Bash reads /etc/profile before this file, so keep shared
# per-user environment in ~/.profile and interactive tweaks in ~/.bashrc.

if [ -z "${__MCR_MANAGED_PROFILE_LOADED:-}" ] && [ -r "$HOME/.profile" ]; then
  # shellcheck disable=SC1091
  . "$HOME/.profile"
fi

case $- in
  *i*)
    if [ -r "$HOME/.bashrc" ]; then
      # shellcheck disable=SC1091
      . "$HOME/.bashrc"
    fi
    ;;
esac
