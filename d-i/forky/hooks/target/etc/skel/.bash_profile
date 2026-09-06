# Bash login profile. Bash reads /etc/profile before this file, so keep shared
# per-user environment in ~/.profile and interactive tweaks in ~/.bashrc.

bash_profile_source_if_readable() {
  [ -r "${1:-}" ] || return 0
  # shellcheck disable=SC1090
  . "$1"
}

bash_profile_is_interactive() {
  case $- in
    *i*) return 0 ;;
  esac
  return 1
}

if [ -z "${__MCR_MANAGED_PROFILE_LOADED:-}" ]; then
  bash_profile_source_if_readable "$HOME/.profile"
fi

if bash_profile_is_interactive; then
  bash_profile_source_if_readable "$HOME/.bashrc"
fi

unset -f bash_profile_source_if_readable bash_profile_is_interactive
