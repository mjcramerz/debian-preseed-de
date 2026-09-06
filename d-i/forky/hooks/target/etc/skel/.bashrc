# Interactive Bash configuration for the managed desktop account.

case $- in
  *i*) ;;
  *) return 0 2>/dev/null || exit 0 ;;
esac

if [ -n "${__MCR_MANAGED_BASHRC_LOADED:-}" ]; then
  return 0 2>/dev/null || exit 0
fi
__MCR_MANAGED_BASHRC_LOADED=1

bashrc_source_if_readable() {
  local source_file=${1:-}

  [ -r "$source_file" ] || return 0
  # shellcheck disable=SC1090
  . "$source_file"
}

bashrc_ensure_parent_dir() {
  local parent_dir

  parent_dir=$(dirname -- "$1")
  [ -d "$parent_dir" ] || mkdir -p -- "$parent_dir" 2>/dev/null || true
}

bashrc_load_profile_fragments() {
  local profile_fragment profile_fragment_dir

  [ -z "${__MCR_MANAGED_PROFILE_FRAGMENTS_LOADED:-}" ] || return 0

  profile_fragment_dir="${HOME}/.profile.d"
  if [ -d "$profile_fragment_dir" ] && [ ! -L "$profile_fragment_dir" ]; then
    for profile_fragment in "$profile_fragment_dir"/[0-9][0-9]-*.sh; do
      [ -e "$profile_fragment" ] || break
      [ -f "$profile_fragment" ] || continue
      [ ! -L "$profile_fragment" ] || continue
      bashrc_source_if_readable "$profile_fragment"
    done
  fi

  __MCR_MANAGED_PROFILE_FRAGMENTS_LOADED=1
}

bashrc_init_history() {
  HISTFILE="${HISTFILE:-${XDG_STATE_HOME:-$HOME/.local/state}/bash/history}"
  HISTSIZE=50000
  HISTFILESIZE=100000
  HISTCONTROL=ignoreboth:erasedups
  shopt -s checkwinsize cmdhist histappend
  bashrc_ensure_parent_dir "$HISTFILE"
}

bashrc_init_system_rc() {
  bashrc_source_if_readable /etc/bash.bashrc
}

bashrc_load_aliases() {
  bashrc_source_if_readable "$HOME/.bash_aliases"
}

bashrc_init_completion() {
  if [ -n "${BASH_COMPLETION_VERSINFO:-}" ]; then
    return 0
  fi

  if [ -r /usr/share/bash-completion/bash_completion ]; then
    # shellcheck disable=SC1091
    . /usr/share/bash-completion/bash_completion
  elif [ -r /etc/bash_completion ]; then
    # shellcheck disable=SC1091
    . /etc/bash_completion
  fi
}

bashrc_init_devops_completions() {
  declare -F devops_de_enable_shell_completions >/dev/null || return 0

  if ! devops_de_enable_shell_completions; then
    printf '%s\n' 'warning: DevOps shell completions could not be enabled' >&2
  fi
}

bashrc_init_fzf() {
  bashrc_source_if_readable /usr/share/doc/fzf/examples/key-bindings.bash
  bashrc_source_if_readable /usr/share/doc/fzf/examples/completion.bash
}

bashrc_init_prompt() {
  if command -v starship >/dev/null 2>&1; then
    eval "$(starship init bash)"
  elif [ -z "${PS1:-}" ]; then
    PS1='\u@\h:\w\$ '
  fi
}

# Load generic completion providers first, then register class-gated DevOps
# completions last so later providers cannot replace them.
bashrc_load_profile_fragments
bashrc_init_history
bashrc_init_system_rc
bashrc_load_aliases
bashrc_init_completion
bashrc_init_fzf
bashrc_init_devops_completions
bashrc_init_prompt

unset -f \
  bashrc_source_if_readable \
  bashrc_ensure_parent_dir \
  bashrc_load_profile_fragments \
  bashrc_init_history \
  bashrc_init_system_rc \
  bashrc_load_aliases \
  bashrc_init_completion \
  bashrc_init_devops_completions \
  bashrc_init_fzf \
  bashrc_init_prompt
