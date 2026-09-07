#!/bin/sh
# Canonical debconf transport. Embedded in common/lib.sh and runtime/common.sh.
# d-i's shell debconf-set-selections is NOT the installed system's Perl tool:
# it requires a filename, has no --checkonly, and uses stdin + FD 3 as a live
# protocol connection. Never pipe answer data into that connection.

installer_debconf_error() {
  printf '[installer-debconf] error: %s\n' "$*" >&2
}

# Use the inherited frontend when present. Starting debconf-communicate against
# its database would introduce a second writer and can lose in-memory changes.
# The caller must preserve stdin (including inside read loops). FDs 3-6 belong
# to d-i; stdout here is solely a returned VALUE, never the protocol connection.
installer_debconf_request() (
  set +x
  set +v
  set -f
  IFS=' '
  [ "$#" -gt 0 ] || exit 125
  idb_request=$*
  case "$idb_request" in
    *'
'*|*"$(printf '\r')"*)
      installer_debconf_error 'multiline protocol requests are forbidden'
      exit 125 ;;
  esac
  if [ -n "${DEBIAN_HAS_FRONTEND:-}" ]; then
    # Lifecycle entry initializes confmodule BEFORE any logging redirection.
    # An uninitialized inherited connection must not be guessed from stdout.
    if [ -z "${DEBCONF_REDIR:-}" ]; then
      installer_debconf_error 'frontend descriptors were not initialized'
      exit 125
    fi
    if ! printf '%s\n' "$idb_request" >&3; then
      installer_debconf_error 'cannot write to inherited frontend'
      exit 125
    fi
    if ! IFS= read -r idb_reply; then
      installer_debconf_error 'frontend reply stream closed; refusing to continue'
      exit 125
    fi
  else
    command -v debconf-communicate >/dev/null 2>&1 || {
      installer_debconf_error 'debconf-communicate is unavailable outside d-i'
      exit 125
    }
    if idb_reply=$(printf '%s\n' "$idb_request" | debconf-communicate 2>/dev/null); then
      :
    else
      idb_rc=$?
      installer_debconf_error "debconf-communicate exited with status $idb_rc"
      exit "$idb_rc"
    fi
  fi
  # Never return unvalidated text as a shell exit status, and never log replies:
  # a malformed reply might contain a password rather than a protocol status.
  case "$idb_reply" in *'
'*) installer_debconf_error 'multiple frontend replies'; exit 125 ;; esac
  idb_status=${idb_reply%% *}
  case "$idb_status" in
    [0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5]) ;;
    *) installer_debconf_error 'invalid frontend reply status'; exit 125 ;;
  esac
  case "$idb_reply" in *' '*) idb_value=${idb_reply#* } ;; *) idb_value= ;; esac
  case "$idb_status" in
    0) printf '%s\n' "$idb_value" ;;
    1)
      if [ -x /usr/lib/cdebconf/debconf-escape ]; then
        printf '%s' "$idb_value" | /usr/lib/cdebconf/debconf-escape -u
      elif command -v debconf-escape >/dev/null 2>&1; then
        printf '%s' "$idb_value" | debconf-escape -u
      else
        installer_debconf_error 'escaped reply without a decoder'
        exit 125
      fi ;;
    *) exit "$idb_status" ;;
  esac
)

installer_debconf_apply_file() (
  set +x
  set +v
  umask 077
  idb_file=$1
  [ -f "$idb_file" ] && [ ! -L "$idb_file" ] && [ -r "$idb_file" ] || {
    installer_debconf_error 'answer file is not a readable regular non-symlink file'
    exit 125
  }
  command -v debconf-set-selections >/dev/null 2>&1 || {
    installer_debconf_error 'required debconf-set-selections tool is unavailable'
    exit 125
  }
  idb_work=$(mktemp -d /tmp/installer-debconf.XXXXXX) || exit 125
  # Diagnostics can contain selections. Keep them private; do not echo them.
  # Successful calls clean up. Failed calls retain diagnostics for recovery.
  if debconf-set-selections "$idb_file" 2>"$idb_work/stderr"; then
    rm -rf "$idb_work"
  else
    idb_rc=$?
    installer_debconf_error "debconf-set-selections failed with status $idb_rc; private diagnostics: $idb_work/stderr"
    exit "$idb_rc"
  fi
)

installer_debconf_seed_value() (
  set +x
  set +v
  umask 077
  [ "$#" -eq 4 ] || exit 125
  idb_owner=$1; idb_question=$2; idb_type=$3; idb_value=$4
  for idb_token in "$idb_owner" "$idb_question" "$idb_type"; do
    case "$idb_token" in ''|*[!A-Za-z0-9_./+:-]*)
      installer_debconf_error 'invalid selection identifier'; exit 125 ;; esac
  done
  case "$idb_value" in *'
'*|*"$(printf '\r')"*)
    installer_debconf_error 'multiline selection value'; exit 125 ;; esac
  idb_work=$(mktemp -d /tmp/installer-selection.XXXXXX) || exit 125
  # Cleanup must not replace an earlier failure, even under inherited errexit.
  # A cleanup failure after otherwise successful work is still an error.
  trap '
    idb_rc=$?
    trap - 0
    if rm -rf "$idb_work"; then :; else
      idb_cleanup_rc=$?
      [ "$idb_rc" -ne 0 ] || idb_rc=$idb_cleanup_rc
    fi
    exit "$idb_rc"
  ' 0
  # Empty registration avoids treating a literal terminal backslash as a
  # continuation. Send the actual value over the protocol only when needed.
  case "$idb_value" in *\\) idb_registration= ;; *) idb_registration=$idb_value ;; esac
  printf '%s %s %s %s\n' "$idb_owner" "$idb_question" "$idb_type" "$idb_registration" >"$idb_work/answers"
  installer_debconf_apply_file "$idb_work/answers" || exit "$?"
  if [ "$idb_registration" != "$idb_value" ]; then
    installer_debconf_request SET "$idb_question" "$idb_value" >/dev/null || exit "$?"
    installer_debconf_request FSET "$idb_question" seen true >/dev/null || exit "$?"
  fi
)
