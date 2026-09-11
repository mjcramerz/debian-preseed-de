# Zsh logout hook for the managed desktop account.

[[ -o interactive ]] || return 0

if [[ -t 1 ]] && command -v clear >/dev/null 2>&1; then
  clear
fi
