# POSIX-compatible shared login environment for managed Debian accounts.

if [ -n "${__MCR_MANAGED_PROFILE_LOADED:-}" ]; then
  return 0 2>/dev/null || exit 0
fi
__MCR_MANAGED_PROFILE_LOADED=1
export __MCR_MANAGED_PROFILE_LOADED
umask 077

path_append_if_dir() {
  [ -n "${1:-}" ] || return 0
  [ -d "$1" ] || return 0
  case ":${PATH:-}:" in
    *":$1:"*) ;;
    *) PATH="${PATH:+$PATH:}$1" ;;
  esac
}

export XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-$HOME/.cache}"
export XDG_DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
export XDG_STATE_HOME="${XDG_STATE_HOME:-$HOME/.local/state}"
export XDG_CONFIG_DIRS="${XDG_CONFIG_DIRS:-/etc/xdg}"
export XDG_DATA_DIRS="${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"

if [ -n "${USER:-}" ]; then
  export MAIL="${MAIL:-/var/mail/${USER}}"
fi

profile_fragment_dir="${HOME}/.profile.d"
if [ -d "$profile_fragment_dir" ] && [ ! -L "$profile_fragment_dir" ]; then
  for profile_fragment in "$profile_fragment_dir"/[0-9][0-9]-*.sh; do
    [ -e "$profile_fragment" ] || break
    [ -f "$profile_fragment" ] || continue
    [ -r "$profile_fragment" ] || continue
    [ ! -L "$profile_fragment" ] || continue
    # shellcheck disable=SC1090
    . "$profile_fragment"
  done
fi
unset profile_fragment profile_fragment_dir

path_append_if_dir "$HOME/bin"
path_append_if_dir "$HOME/.local/bin"
path_append_if_dir /usr/local/sbin
path_append_if_dir /usr/sbin
path_append_if_dir /data/bin
export PATH

export EDITOR="${EDITOR:-nano}"
export VISUAL="${VISUAL:-$EDITOR}"
export PAGER="${PAGER:-less}"
export LESS="${LESS:--FRSX}"
export LESSHISTFILE="${LESSHISTFILE:--}"
export CLICOLOR="${CLICOLOR:-1}"

if command -v dircolors >/dev/null 2>&1; then
  if [ -r "$HOME/.dircolors" ]; then
    eval "$(dircolors -b "$HOME/.dircolors")"
  else
    eval "$(dircolors -b)"
  fi
  export LS_COLORS
fi

export FZF_DEFAULT_OPTS_FILE="${FZF_DEFAULT_OPTS_FILE:-$XDG_CONFIG_HOME/fzf/default-opts}"
if [ -r "$FZF_DEFAULT_OPTS_FILE" ]; then
  FZF_DEFAULT_OPTS=$(
    sed '/^[[:space:]]*#/d; /^[[:space:]]*$/d' "$FZF_DEFAULT_OPTS_FILE" 2>/dev/null |
      tr '\n' ' '
  )
  export FZF_DEFAULT_OPTS
fi

__fzf_fd=
if command -v fd >/dev/null 2>&1; then
  __fzf_fd=fd
elif command -v fdfind >/dev/null 2>&1; then
  __fzf_fd=fdfind
fi
if [ -n "$__fzf_fd" ]; then
  export FZF_CTRL_T_COMMAND="${FZF_CTRL_T_COMMAND:-$__fzf_fd --hidden --follow --exclude .git .}"
  export FZF_ALT_C_COMMAND="${FZF_ALT_C_COMMAND:-$__fzf_fd --type d --hidden --follow --exclude .git .}"
else
  export FZF_CTRL_T_COMMAND="${FZF_CTRL_T_COMMAND:-find . -type f}"
  export FZF_ALT_C_COMMAND="${FZF_ALT_C_COMMAND:-find . -type d}"
fi

unset __fzf_fd
unset -f path_append_if_dir
