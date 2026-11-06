# Non-interactive shells must not receive prompt or alias state.
case $- in
  *i*) ;;
  *) return ;;
esac
umask 027
export HISTCONTROL=ignoreboth
export HISTSIZE=10000
export HISTFILESIZE=20000
export LESS='-FRX'
alias ll='ls -alF'
alias la='ls -A'
alias l='ls -CF'
PS1='\u@\h:\w\$ '
