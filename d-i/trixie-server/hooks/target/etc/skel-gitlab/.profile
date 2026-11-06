if [ -n "${BASH_VERSION:-}" ] && [ -r "$HOME/.bashrc" ]; then
  . "$HOME/.bashrc"
fi
export EDITOR=vim
export VISUAL=vim
export GITLAB_RUNNER_CACHE_DIR="${GITLAB_RUNNER_CACHE_DIR:-$HOME/.cache/gitlab-runner}"
