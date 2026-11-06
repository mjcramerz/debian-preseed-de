if [ -n "${BASH_VERSION:-}" ] && [ -r "$HOME/.bashrc" ]; then
  . "$HOME/.bashrc"
fi
export GITHUB_ACTIONS_RUNNER_TOOL_CACHE="${GITHUB_ACTIONS_RUNNER_TOOL_CACHE:-$HOME/.cache/actions}"
export EDITOR=vim
export VISUAL=vim
