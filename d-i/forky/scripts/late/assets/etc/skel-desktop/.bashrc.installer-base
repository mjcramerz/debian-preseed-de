# Interactive Bash configuration for the managed Debian account.

case $- in
  *i*) ;;
  *) return 0 2>/dev/null || exit 0 ;;
esac

if [ -n "${__MCR_MANAGED_BASHRC_LOADED:-}" ]; then
  return 0 2>/dev/null || exit 0
fi
__MCR_MANAGED_BASHRC_LOADED=1
export __MCR_MANAGED_BASHRC_LOADED

HISTFILE="${HISTFILE:-${XDG_STATE_HOME:-$HOME/.local/state}/bash/history}"
HISTSIZE=50000
HISTFILESIZE=100000
HISTCONTROL=ignoreboth:erasedups
shopt -s checkwinsize cmdhist histappend

mkdir -p -- "$(dirname "$HISTFILE")" 2>/dev/null || true

if command -v fdfind >/dev/null 2>&1 && ! command -v fd >/dev/null 2>&1; then
  alias fd='fdfind'
fi

alias ls='ls --color=auto'
alias ll='ls -lah --color=auto'
alias la='ls -A --color=auto'
alias l='ls -CF --color=auto'
alias grep='grep --color=auto'
alias ip='ip --color=auto'
alias btop='btop --utf-force'

if [ -r "$HOME/.bash_aliases" ]; then
  # shellcheck disable=SC1090
  . "$HOME/.bash_aliases"
fi

if [ -r /usr/share/bash-completion/bash_completion ]; then
  # shellcheck disable=SC1091
  . /usr/share/bash-completion/bash_completion
elif [ -r /etc/bash_completion ]; then
  # shellcheck disable=SC1091
  . /etc/bash_completion
fi

if [ -r /usr/share/doc/fzf/examples/key-bindings.bash ]; then
  # shellcheck disable=SC1091
  . /usr/share/doc/fzf/examples/key-bindings.bash
fi
if [ -r /usr/share/doc/fzf/examples/completion.bash ]; then
  # shellcheck disable=SC1091
  . /usr/share/doc/fzf/examples/completion.bash
fi
