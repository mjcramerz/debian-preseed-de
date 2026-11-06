case $- in
  *i*) ;;
  *) return ;;
esac
umask 027
export HISTCONTROL=ignoreboth
export HISTSIZE=10000
export HISTFILESIZE=20000
export PATH="$HOME/.local/bin:$PATH"
export GITHUB_ACTIONS_RUNNER_TOOL_CACHE="${GITHUB_ACTIONS_RUNNER_TOOL_CACHE:-$HOME/.cache/actions}"
PS1='\u@\h:\w\$ '
