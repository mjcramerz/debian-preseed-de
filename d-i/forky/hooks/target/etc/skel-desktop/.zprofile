# Zsh login profile. Debian's zsh startup does not source /etc/profile for us.

zprofile_source_sh_file() {
  emulate -L sh
  [ -r "${1:-}" ] || return 0
  # shellcheck disable=SC1090
  . "$1"
}

if [[ -z ${__MCR_MANAGED_SYSTEM_PROFILE_LOADED:-} ]]; then
  export __MCR_MANAGED_SYSTEM_PROFILE_LOADED=1
  zprofile_source_sh_file /etc/profile
fi

if [[ -z ${__MCR_MANAGED_PROFILE_LOADED:-} ]]; then
  zprofile_source_sh_file "$HOME/.profile"
fi


unfunction zprofile_source_sh_file
