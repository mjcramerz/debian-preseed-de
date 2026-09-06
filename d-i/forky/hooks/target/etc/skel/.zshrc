# Interactive Zsh configuration for the managed desktop account.

[[ -o interactive ]] || return 0

if (( ${+__MCR_MANAGED_ZSHRC_LOADED} )); then
  return 0
fi
typeset -g __MCR_MANAGED_ZSHRC_LOADED=1

zshrc_source_if_readable() {
  local file_path=${1:-}
  [[ -r $file_path ]] || return 0
  . "$file_path"
}

zshrc_source_sh_file() {
  emulate -L sh
  [ -r "${1:-}" ] || return 0
  # shellcheck disable=SC1090
  . "$1"
}

zshrc_ensure_parent_dir() {
  local dir_path=${1:h}
  [[ -d $dir_path ]] || mkdir -p "$dir_path" 2>/dev/null || true
}

zshrc_load_profile_fragments() {
  (( ${+__MCR_MANAGED_PROFILE_FRAGMENTS_LOADED} )) && return 0

  local profile_fragment profile_fragment_dir
  profile_fragment_dir="${HOME}/.profile.d"
  if [[ -d $profile_fragment_dir && ! -L $profile_fragment_dir ]]; then
    for profile_fragment in "$profile_fragment_dir"/[0-9][0-9]-*.sh(N); do
      [[ -f $profile_fragment && ! -L $profile_fragment ]] || continue
      zshrc_source_sh_file "$profile_fragment"
    done
  fi

  typeset -g __MCR_MANAGED_PROFILE_FRAGMENTS_LOADED=1
}

zshrc_init_history() {
  HISTFILE="${HISTFILE:-${XDG_STATE_HOME:-$HOME/.local/state}/zsh/history}"
  HISTSIZE=50000
  SAVEHIST=50000

  setopt append_history
  setopt auto_cd
  setopt complete_in_word
  setopt extended_history
  setopt hist_expire_dups_first
  setopt hist_find_no_dups
  setopt hist_ignore_all_dups
  setopt hist_ignore_space
  setopt hist_reduce_blanks
  setopt inc_append_history
  setopt interactive_comments
  setopt no_beep
  setopt prompt_subst
  setopt share_history
  unsetopt nomatch

  zshrc_ensure_parent_dir "$HISTFILE"
}

zshrc_init_completion() {
  local cache_dir dump_file

  zmodload -i zsh/complist
  autoload -Uz compinit

  cache_dir="${ZSH_CACHE_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/zsh}"
  if mkdir -p "$cache_dir" 2>/dev/null; then
    zstyle ':completion:*' use-cache on
    zstyle ':completion:*' cache-path "$cache_dir/completion-cache"
    # Debian package candidates are kept once in memory per interactive shell.
    # Do not source persistent DEBS_* files for APT commands: a partial or
    # malformed cache must never break `sudo apt install <TAB>` completion.
    zstyle ':completion:*:*:apt:*' use-cache off
    zstyle ':completion:*:*:apt-get:*' use-cache off
    zstyle ':completion:*:*:apt-cache:*' use-cache off
    zstyle ':completion:*:*:apt-mark:*' use-cache off
    dump_file="$cache_dir/zcompdump"
    if [[ -s $dump_file ]]; then
      compinit -C -i -d "$dump_file"
    else
      compinit -i -d "$dump_file"
    fi
  else
    compinit -i
  fi
}

zshrc_init_completion_styles() {
  zstyle ':completion:*' matcher-list 'm:{a-zA-Z}={A-Za-z}'
  zstyle ':completion:*' menu select
  if [[ -n ${LS_COLORS:-} ]]; then
    zstyle ':completion:*' list-colors "${(s.:.)LS_COLORS}"
  fi
  zstyle ':completion:*:descriptions' format '%F{yellow}%d%f'
  zstyle ':completion:*:warnings' format '%F{red}no matches%f'
  zstyle ':completion:*' squeeze-slashes true
}

zshrc_init_devops_completions() {
  (( ${+functions[devops_de_enable_shell_completions]} )) || return 0

  if ! devops_de_enable_shell_completions; then
    print -u2 -- 'warning: DevOps shell completions could not be enabled'
  fi
}

zshrc_init_key_bindings() {
  [[ -o interactive ]] || return 0
  bindkey -e
  autoload -Uz up-line-or-beginning-search down-line-or-beginning-search
  zle -N up-line-or-beginning-search
  zle -N down-line-or-beginning-search
  bindkey '^[[A' up-line-or-beginning-search
  bindkey '^[[B' down-line-or-beginning-search
  bindkey '^[[1;5C' forward-word
  bindkey '^[[1;5D' backward-word
  bindkey '^[[3~' delete-char
}

zshrc_load_aliases() {
  zshrc_source_if_readable "$HOME/.zsh_aliases"
}

zshrc_init_fzf() {
  zshrc_source_if_readable /usr/share/doc/fzf/examples/key-bindings.zsh
  zshrc_source_if_readable /usr/share/doc/fzf/examples/completion.zsh
}

zshrc_init_autosuggestions() {
  [[ -o interactive ]] || return 0
  if [[ -r /usr/share/zsh-autosuggestions/zsh-autosuggestions.zsh ]]; then
    ZSH_AUTOSUGGEST_STRATEGY=(history completion)
    ZSH_AUTOSUGGEST_HIGHLIGHT_STYLE='fg=8'
    . /usr/share/zsh-autosuggestions/zsh-autosuggestions.zsh
  fi
}

zshrc_init_prompt() {
  if command -v starship >/dev/null 2>&1; then
    eval "$(starship init zsh)"
  else
    PROMPT='%F{yellow}[%n]%f %F{cyan}%m%f %F{green}%~%f %# '
  fi
}

zshrc_init_syntax_highlighting() {
  [[ -o interactive ]] || return 0
  if [[ -r /usr/share/zsh-syntax-highlighting/zsh-syntax-highlighting.zsh ]]; then
    (( ${+functions[_zsh_highlight_bind_widgets]} )) && return 0
    ZSH_HIGHLIGHT_MAXLENGTH="${ZSH_HIGHLIGHT_MAXLENGTH:-512}"
    typeset -gA ZSH_HIGHLIGHT_STYLES
    ZSH_HIGHLIGHT_HIGHLIGHTERS=(main brackets)
    ZSH_HIGHLIGHT_STYLES[unknown-token]='fg=red,bold'
    ZSH_HIGHLIGHT_STYLES[reserved-word]='fg=yellow'
    ZSH_HIGHLIGHT_STYLES[alias]='fg=cyan'
    ZSH_HIGHLIGHT_STYLES[builtin]='fg=cyan'
    ZSH_HIGHLIGHT_STYLES[function]='fg=cyan'
    ZSH_HIGHLIGHT_STYLES[command]='fg=green'
    ZSH_HIGHLIGHT_STYLES[path]='fg=blue,underline'
    . /usr/share/zsh-syntax-highlighting/zsh-syntax-highlighting.zsh
  fi
}

# Initialize compinit, completion styles, and FZF before registering the
# class-gated DevOps completion layer.
zshrc_load_profile_fragments
zshrc_init_history
zshrc_init_completion
zshrc_init_completion_styles
zshrc_init_key_bindings
zshrc_load_aliases
zshrc_init_fzf
zshrc_init_devops_completions
zshrc_init_autosuggestions
zshrc_init_prompt
zshrc_init_syntax_highlighting

# Profile fragments load before prompt integrations. Re-register the DevOps
# title hook last so `[devops]` remains the final title at prompts and commands.
if (( ${+functions[devops_de_enable_zsh_terminal_title]} )); then
  devops_de_enable_zsh_terminal_title
fi

unfunction \
  zshrc_source_if_readable \
  zshrc_source_sh_file \
  zshrc_ensure_parent_dir \
  zshrc_load_profile_fragments \
  zshrc_init_history \
  zshrc_init_completion \
  zshrc_init_completion_styles \
  zshrc_init_devops_completions \
  zshrc_init_key_bindings \
  zshrc_load_aliases \
  zshrc_init_fzf \
  zshrc_init_autosuggestions \
  zshrc_init_prompt \
  zshrc_init_syntax_highlighting
