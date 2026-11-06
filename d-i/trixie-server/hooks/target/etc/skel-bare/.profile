# Minimal server login environment. This profile intentionally uses bash only.
if [ -n "${BASH_VERSION:-}" ] && [ -r "$HOME/.bashrc" ]; then
  . "$HOME/.bashrc"
fi
if [ -n "${BASH_VERSION:-}" ] && [ -d "$HOME/.profile.d" ]; then
  for profile_fragment in "$HOME/.profile.d"/*.sh; do
    [ -r "$profile_fragment" ] || continue
    . "$profile_fragment"
  done
  unset profile_fragment
fi
export EDITOR=vim
export VISUAL=vim
export PAGER='less -FRX'
