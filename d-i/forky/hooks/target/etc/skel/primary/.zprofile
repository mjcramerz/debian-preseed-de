# Zsh login profile. Debian's zsh startup does not source /etc/profile for us.

zprofile_source_sh_file() {
  emulate -L sh
  [ -r "${1:-}" ] || return 0
  # shellcheck disable=SC1090
  . "$1"
}

zprofile_has_live_ssh_agent() {
  [[ -n ${SSH_AGENT_PID:-} ]] && return 0
  [[ -n ${SSH_AUTH_SOCK:-} && -S ${SSH_AUTH_SOCK:-/dev/null} ]]
}

zprofile_maybe_start_ssh_agent() {
  [[ -o interactive ]] || return 0
  zprofile_has_live_ssh_agent && return 0
  command -v ssh-agent >/dev/null 2>&1 || return 0
  eval "$(ssh-agent -s)" >/dev/null
}

if [[ -z ${__MCR_MANAGED_SYSTEM_PROFILE_LOADED:-} ]]; then
  export __MCR_MANAGED_SYSTEM_PROFILE_LOADED=1
  zprofile_source_sh_file /etc/profile
fi

if [[ -z ${__MCR_MANAGED_PROFILE_LOADED:-} ]]; then
  zprofile_source_sh_file "$HOME/.profile"
fi

zprofile_maybe_start_ssh_agent

unfunction zprofile_source_sh_file zprofile_has_live_ssh_agent zprofile_maybe_start_ssh_agent
