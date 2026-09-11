# Minimal environment for every zsh invocation.
# Keep this file quiet, fast, and free of interactive side effects.

export XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-$HOME/.cache}"
export XDG_DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
export XDG_STATE_HOME="${XDG_STATE_HOME:-$HOME/.local/state}"
export XDG_CONFIG_DIRS="${XDG_CONFIG_DIRS:-/etc/xdg}"
export XDG_DATA_DIRS="${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"

export TASKRC="${TASKRC:-$XDG_CONFIG_HOME/task/taskrc}"
export TASKDATA="${TASKDATA:-$XDG_DATA_HOME/task}"

export EDITOR="${EDITOR:-nano}"
export VISUAL="${VISUAL:-$EDITOR}"

export ZSH_CACHE_DIR="${ZSH_CACHE_DIR:-$XDG_CACHE_HOME/zsh}"

typeset -gU path

zshenv_append_path_if_dir() {
  local dir_path=${1:-}
  [[ -n $dir_path && -d $dir_path ]] || return 0
  path+=("$dir_path")
}

zshenv_init_path() {
  zshenv_append_path_if_dir "$HOME/bin"
  zshenv_append_path_if_dir "$HOME/.local/bin"
  zshenv_append_path_if_dir "/usr/local/cuda-12-8/bin"
  zshenv_append_path_if_dir "/usr/local/sbin"
  zshenv_append_path_if_dir "/usr/sbin"
  zshenv_append_path_if_dir "/data/bin"
  export PATH
}

zshenv_init_path

unfunction zshenv_append_path_if_dir zshenv_init_path
