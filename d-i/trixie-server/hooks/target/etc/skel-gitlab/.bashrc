case $- in
  *i*) ;;
  *) return ;;
esac
umask 027
export HISTCONTROL=ignoreboth
export HISTSIZE=10000
export HISTFILESIZE=20000
export PATH="$HOME/.local/bin:$PATH"
export GITLAB_RUNNER_CACHE_DIR="${GITLAB_RUNNER_CACHE_DIR:-$HOME/.cache/gitlab-runner}"
PS1='\u@\h:\w\$ '
