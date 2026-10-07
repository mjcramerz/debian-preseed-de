# POSIX-compatible shared login environment for managed Debian accounts.

if [ -n "${__MCR_MANAGED_PROFILE_LOADED:-}" ]; then
  return 0 2>/dev/null || exit 0
fi
__MCR_MANAGED_PROFILE_LOADED=1
export __MCR_MANAGED_PROFILE_LOADED

profile_source_if_readable() {
  [ -r "${1:-}" ] || return 0
  # shellcheck disable=SC1090
  . "$1"
}

profile_append_path_if_dir() {
  [ -n "${1:-}" ] || return 0
  [ -d "$1" ] || return 0
  case ":${PATH:-}:" in
    *":$1:"*) ;;
    *) PATH="${PATH:+$PATH:}$1" ;;
  esac
}

profile_init_xdg_env() {
  export XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
  export XDG_CACHE_HOME="${XDG_CACHE_HOME:-$HOME/.cache}"
  export XDG_DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
  export XDG_STATE_HOME="${XDG_STATE_HOME:-$HOME/.local/state}"
  export XDG_CONFIG_DIRS="${XDG_CONFIG_DIRS:-/etc/xdg}"
  export XDG_DATA_DIRS="${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"
}

profile_init_mail_env() {
  if [ -n "${USER:-}" ]; then
    export MAIL="${MAIL:-/var/mail/${USER}}"
  fi
}

profile_source_fragments() {
  profile_fragment_dir="${HOME}/.profile.d"
  if [ -d "$profile_fragment_dir" ] && [ ! -L "$profile_fragment_dir" ]; then
    for profile_fragment in "$profile_fragment_dir"/[0-9][0-9]-*.sh; do
      [ -e "$profile_fragment" ] || break
      [ -f "$profile_fragment" ] || continue
      [ ! -L "$profile_fragment" ] || continue
      profile_source_if_readable "$profile_fragment"
    done
  fi
  # Keep this marker local to the current shell.  Interactive child shells
  # must source the fragments again so newly opened terminals get current
  # managed environment values.
  __MCR_MANAGED_PROFILE_FRAGMENTS_LOADED=1
  unset profile_fragment profile_fragment_dir
}

profile_init_path() {
  profile_append_path_if_dir "$HOME/bin"
  profile_append_path_if_dir "$HOME/.local/bin"
  profile_append_path_if_dir /usr/local/cuda-12-8/bin
  profile_append_path_if_dir /usr/local/sbin
  profile_append_path_if_dir /usr/sbin
  profile_append_path_if_dir /data/bin
  export PATH
}

profile_init_tool_defaults() {
  export EDITOR="${EDITOR:-nano}"
  export VISUAL="${VISUAL:-$EDITOR}"
  export PAGER="${PAGER:-less}"
  export LESS="${LESS:--FRSX}"
  export LESSHISTFILE="${LESSHISTFILE:--}"
  export CLICOLOR="${CLICOLOR:-1}"

  if [ -r "$XDG_CONFIG_HOME/starship.toml" ]; then
    export STARSHIP_CONFIG="$XDG_CONFIG_HOME/starship.toml"
  fi
  export STARSHIP_CACHE="${STARSHIP_CACHE:-$XDG_CACHE_HOME/starship}"
  export TASKRC="${TASKRC:-$XDG_CONFIG_HOME/task/taskrc}"
  export TASKDATA="${TASKDATA:-$XDG_DATA_HOME/task}"
}

profile_init_dircolors() {
  command -v dircolors >/dev/null 2>&1 || return 0

  if [ -r "$HOME/.dircolors" ]; then
    eval "$(dircolors -b "$HOME/.dircolors")"
  else
    eval "$(dircolors -b)"
  fi
  export LS_COLORS
}

profile_init_fzf_env() {
  export FZF_DEFAULT_OPTS_FILE="${FZF_DEFAULT_OPTS_FILE:-$XDG_CONFIG_HOME/fzf/default-opts}"
  if [ -r "$FZF_DEFAULT_OPTS_FILE" ]; then
    FZF_DEFAULT_OPTS=$(
      sed '/^[[:space:]]*#/d; /^[[:space:]]*$/d' "$FZF_DEFAULT_OPTS_FILE" 2>/dev/null |
        tr '\n' ' '
    )
    export FZF_DEFAULT_OPTS
  fi

  profile_fzf_fd=
  if command -v fd >/dev/null 2>&1; then
    profile_fzf_fd=fd
  elif command -v fdfind >/dev/null 2>&1; then
    profile_fzf_fd=fdfind
  fi

  if [ -n "$profile_fzf_fd" ]; then
    export FZF_CTRL_T_COMMAND="${FZF_CTRL_T_COMMAND:-$profile_fzf_fd --hidden --follow --exclude .git .}"
    export FZF_ALT_C_COMMAND="${FZF_ALT_C_COMMAND:-$profile_fzf_fd --type d --hidden --follow --exclude .git .}"
  else
    export FZF_CTRL_T_COMMAND="${FZF_CTRL_T_COMMAND:-find . -type f}"
    export FZF_ALT_C_COMMAND="${FZF_ALT_C_COMMAND:-find . -type d}"
  fi

  unset profile_fzf_fd
}

profile_init_xdg_env
profile_init_mail_env
profile_source_fragments
profile_init_path
profile_init_tool_defaults
profile_init_dircolors
profile_init_fzf_env

unset -f \
  profile_source_if_readable \
  profile_append_path_if_dir \
  profile_init_xdg_env \
  profile_init_mail_env \
  profile_source_fragments \
  profile_init_path \
  profile_init_tool_defaults \
  profile_init_dircolors \
  profile_init_fzf_env
