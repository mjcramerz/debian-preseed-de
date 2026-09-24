#!/bin/sh
# Shared storage runtime module.

runtime_debconf_command() (
  runtime_debconf_request=$1
  runtime_debconf_question=$2
  if installer_debconf_request "$runtime_debconf_request" >/dev/null; then
    return 0
  else
    runtime_debconf_status=$?
    printf '[runtime] error: debconf command failed for %s (status %s)\n' "$runtime_debconf_question" "$runtime_debconf_status" >&2
    return "$runtime_debconf_status"
  fi
)

runtime_seed_debconf_value() {
  runtime_debconf_command "SET $1 $2" "$1" || return $?
  runtime_debconf_command "FSET $1 seen true" "$1"
}

runtime_apply_answers_file() (
  path=$1
  [ -r "$path" ] || runtime_fatal "answer fragment is not readable: ${path}"
  if LC_ALL=C grep -q '\\$' "$path" ||
     LC_ALL=C grep -Eq '^[[:space:]]*[^#[:space:]][^[:space:]]*[[:space:]]+[^[:space:]]+[[:space:]]+password([[:space:]]|$)' "$path"; then
    # The upstream d-i selector logs each record. Register password questions
    # without their values, then send those values on the live protocol.
    # Generated runtime fragments have one record per physical line. Preserve
    # terminal backslashes as data. The installer utility needs a filename;
    # piping records into it both omits that argument and destroys its replies.
    runtime_answer_work=$(mktemp -d /tmp/installer-runtime-answers.XXXXXX) || return 125
    trap '
      runtime_answer_status=$?
      trap - 0
      if rm -rf "$runtime_answer_work"; then :; else
        runtime_cleanup_status=$?
        [ "$runtime_answer_status" -ne 0 ] || runtime_answer_status=$runtime_cleanup_status
      fi
      exit "$runtime_answer_status"
    ' 0
    (umask 077
      while IFS=' 	' read -r owner question answer_type value || [ -n "${owner:-}" ]; do
        case "$owner" in ''|'#'*) continue ;; esac
        case "$value" in *\\) value= ;; esac
        [ "$answer_type" != password ] || value=
        printf '%s %s %s %s\n' "$owner" "$question" "$answer_type" "$value"
      done <"$path" >"$runtime_answer_work/answers"
    ) || return "$?"
    installer_debconf_apply_file "$runtime_answer_work/answers" || return "$?"
    runtime_seed_answers_file "$path" || return "$?"
  else
    installer_debconf_apply_file "$path" || return "$?"
  fi
)

runtime_seed_answers_file() (
  path=$1
  [ -r "$path" ] || runtime_fatal "answer fragment is not readable: ${path}"

  # Generated fragments contain one record per physical line. read -r preserves
  # password punctuation; an empty fourth field must clear a stale hash. A seen
  # record changes a flag, never the value (especially never a password).
  while IFS=' 	' read -r owner question answer_type value <&7 || [ -n "${owner:-}" ]; do
    case "$owner" in
      ''|'#'*) continue ;;
    esac
    [ -n "$question" ] || runtime_fatal "invalid generated answer record"
    case "$answer_type" in
      seen)
        case "$value" in
          true|false) ;;
          *) runtime_fatal "invalid seen flag for ${question}" ;;
        esac
        runtime_debconf_command "FSET $question seen $value" "$question" || return $?
        ;;
      boolean|string|password|select|multiselect|note|text|title)
        runtime_seed_debconf_value "$question" "$value" || return $?
        ;;
      *) runtime_fatal "unsupported generated answer type for ${question}" ;;
    esac
  done 7<"$path"
)

