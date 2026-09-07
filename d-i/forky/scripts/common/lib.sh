#!/bin/sh
# BEGIN EMBEDDED LIFECYCLE
#!/bin/sh
# Canonical d-i lifecycle. Embedded in source.sh before the first network fetch.
# Explicit delimiters also permit embedding in a single preseed command.
# Numeric ls is available in busybox-udeb; stat is deliberately not built.
# Only fixed metadata columns are parsed, never the filename or its whitespace.
installer_metadata_value() (
  set -f;
  lc_metadata=$(LC_ALL=C ls -ldn "$1" 2>/dev/null) || exit 1;
  lc_field=$2;
  set -- $lc_metadata;
  [ "$#" -ge 4 ] || exit 1;
  case "$2:$3" in *[!0-9:]*|:*) exit 1 ;; esac;
  case "$lc_field" in
    uid) printf '%s\n' "$3" ;;
    links) printf '%s\n' "$2" ;;
    mode)
      printf '%s\n' "$1" | awk '
        length($0) < 10 {exit 1}
        { special=0; value=0;
          for (i=2; i<=10; i++) {
            c=substr($0,i,1); bit=(i%3==2 ? 4 : (i%3==0 ? 2 : 1));
            if (c!="-") {
              if (c!="r" && c!="w" && c!="x" && c!="s" && c!="S" && c!="t" && c!="T") exit 1;
              if (c!="S" && c!="T") value+=bit;
              if (c=="s" || c=="S") special+=(i==4 ? 4 : 2);
              if (c=="t" || c=="T") special+=1;
            };
            if (i==4 || i==7) value*=8;
          };
          printf "%o\n", special*512+value;
        }' ;;
    *) exit 1 ;;
  esac;
);
installer_lifecycle_paths() {
  LC_ROOT=${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime};
  LC_STATE=$LC_ROOT/state;
  case "$LC_ROOT" in /*) ;; *) return 1 ;; esac;
  case "/${LC_ROOT#/}/" in *'/../'*|*'/./'*|*'//'*) return 1 ;; esac;
  [ "$LC_ROOT" != / ] || return 1;
  lc_path=$LC_STATE;
  while [ "$lc_path" != / ]; do
    [ ! -L "$lc_path" ] || return 1;
    lc_path=${lc_path%/*}; [ -n "$lc_path" ] || lc_path=/;
  done;
  (umask 077; mkdir -p "$LC_STATE") || return 1;
  [ "$(installer_metadata_value "$LC_ROOT" uid)" = "$(id -u)" ] || return 1;
  [ "$(installer_metadata_value "$LC_STATE" uid)" = "$(id -u)" ] || return 1;
  chmod 0700 "$LC_ROOT" "$LC_STATE" || return 1;
};
installer_record_failure() (
  # Atomic first-writer-wins publication, never replaced by cleanup errors.
  set +e; umask 077;
  installer_lifecycle_paths || exit 1;
  lc_status=${1:-1}; lc_component=${2:-unknown}; lc_detail=${3:-unspecified};
  case "$lc_status" in ''|*[!0-9]*|0) lc_status=1 ;; esac;
  rm -f "$LC_STATE/installation.success" "$LC_STATE/target-validated";
  [ ! -e "$LC_STATE/first-failure" ] && [ ! -L "$LC_STATE/first-failure" ] || exit 0;
  lc_tmp=$(mktemp "$LC_STATE/.failure.XXXXXX") || exit 1;
  trap 'rm -f "$lc_tmp"' 0;
  { printf 'format=1\nstate=FATAL\nstatus=%s\n' "$lc_status";
    printf 'phase=%s\ncomponent=%s\n' "${INSTALLER_PHASE:-unknown}" "$lc_component";
    printf 'timestamp=%s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')";
    printf 'detail=%s\n' "$(printf '%s' "$lc_detail" | tr '\r\n' '  ')";
  } >"$lc_tmp" || exit 1;
  chmod 0600 "$lc_tmp" || exit 1;
  ln "$lc_tmp" "$LC_STATE/first-failure" 2>/dev/null || [ -f "$LC_STATE/first-failure" ];
);
installer_preserve_failure() (
  set +e; umask 077;
  installer_lifecycle_paths || exit 1;
  lc_target=${INSTALLER_TARGET_DIR:-/target};
  # Never write into the installer's uncovered /target directory after unmount.
  awk -v p="$lc_target" '$2==p {found=1} END {exit !found}' /proc/mounts || exit 0;
  lc_path=$lc_target/var/log/installer;
  while [ "$lc_path" != / ]; do
    [ ! -L "$lc_path" ] || exit 1;
    lc_path=${lc_path%/*}; [ -n "$lc_path" ] || lc_path=/;
  done;
  mkdir -p "$lc_target/var/log/installer" || exit 1;
  chmod 0700 "$lc_target/var/log/installer" || exit 1;
  for lc_source in "$LC_STATE/first-failure" /tmp/installer.log /var/log/syslog; do
    [ -f "$lc_source" ] && [ ! -L "$lc_source" ] || continue;
    lc_tmp=$(mktemp "$lc_target/var/log/installer/.diagnostic.XXXXXX") || exit 1;
    if cp "$lc_source" "$lc_tmp" && chmod 0600 "$lc_tmp"; then
      mv -f "$lc_tmp" "$lc_target/var/log/installer/${lc_source##*/}" || exit 1;
    else rm -f "$lc_tmp"; exit 1; fi;
  done;
);
installer_terminal_hold() {
  # A nonzero late_command is NOT terminal: preseed_command may swallow it,
  # and finish-install logs most hook failures then continues toward reboot.
  # Do not return to either caller. SIGSTOP the actual main-menu ancestor too,
  # so killing this leaf cannot restart unattended installation work.
  trap '' HUP INT TERM; trap - 0;
  set +e;
  installer_preserve_failure;
  printf '\nINSTALLER TERMINAL FAILURE: no further installation or reboot is permitted.\nDiagnostics: %s/state/first-failure and /tmp/installer.log\n' "${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}" >&2;
  if [ -c /dev/console ] && [ -w /dev/console ]; then
    printf '\nINSTALLER TERMINAL FAILURE. Inspect /tmp/install-runtime/state/first-failure; manual recovery required.\n' >/dev/console;
  fi;
  lc_pid=$$; lc_depth=0;
  while [ "$lc_pid" -gt 1 ] && [ "$lc_depth" -lt 64 ]; do
    lc_name=$(cat "/proc/$lc_pid/comm" 2>/dev/null);
    if [ "$lc_name" = main-menu ]; then kill -STOP "$lc_pid"; break; fi;
    lc_pid=$(awk '/^PPid:/ {print $2}' "/proc/$lc_pid/status" 2>/dev/null);
    case "$lc_pid" in ''|*[!0-9]*) break ;; esac;
    lc_depth=$(expr "$lc_depth" + 1) || break;
  done;
  sync;
  # This is an intentional terminal wait, not a retry loop. No commands that
  # customize the target, run a phase, or reboot occur inside it.
  while :; do sleep 3600; done;
};
# Freeze the owned child before enumerating descendants. Frozen parents cannot
# reap/reuse their child PIDs or launch subsequent installer commands. No process
# group, host-wide kill, setsid, Python, or stat applet is needed in busybox-udeb.
installer_stop_tree() (
  # Callers may disable globbing while parsing URLs. The private /proc fallback
  # must still expand its trusted numeric PID pattern. Never inherit noglob here.
  set +f;
  lc_stop_pid=$1; lc_stop_depth=${2:-0};
  case "$lc_stop_depth" in ''|*[!0-9]*) exit 1 ;; esac;
  case "$lc_stop_pid" in ''|*[!0-9]*|0|1) exit 1 ;; esac;
  [ "$lc_stop_depth" -lt 128 ] || exit 1;
  [ -d "/proc/$lc_stop_pid" ] || exit 0;
  kill -STOP "$lc_stop_pid" 2>/dev/null || exit 0;
  lc_children=$(cat "/proc/$lc_stop_pid/task/$lc_stop_pid/children" 2>/dev/null) || {
    # Some kernels omit CONFIG_CHECKPOINT_RESTORE and therefore children.
    lc_children=;
    for lc_proc_status in /proc/[0-9]*/status; do
      lc_proc_parent=$(awk '/^PPid:/ {print $2}' "$lc_proc_status" 2>/dev/null) || continue;
      [ "$lc_proc_parent" = "$lc_stop_pid" ] || continue;
      lc_proc_id=${lc_proc_status%/status}; lc_proc_id=${lc_proc_id##*/};
      lc_children="$lc_children $lc_proc_id";
    done;
  };
  for lc_child in $lc_children; do
    case "$lc_child" in ''|*[!0-9]*) continue ;; esac;
    lc_parent=$(awk '/^PPid:/ {print $2}' "/proc/$lc_child/status" 2>/dev/null);
    [ "$lc_parent" = "$lc_stop_pid" ] || continue;
    lc_stop_next_depth=$(expr "$lc_stop_depth" + 1) || exit 1;
    installer_stop_tree "$lc_child" "$lc_stop_next_depth" || :;
  done;
  kill -KILL "$lc_stop_pid" 2>/dev/null || :;
);

# External commands run as a direct child, with responsive signal traps while
# waiting. Shell child statuses are retained, not replaced by diagnostic output.
installer_run_supervised() {
  "$@" <&0 &
  LC_CHILD_PID=$!;
  if wait "$LC_CHILD_PID"; then lc_child_status=0; else lc_child_status=$?; fi;
  LC_CHILD_PID=;
  return "$lc_child_status";
};

# Normalize bounded durations before numeric comparison or child creation.
# test(1) accepts leading zeroes as decimal, while shell arithmetic treats them
# as octal: 0180 passes a range check but raises a fatal ash arithmetic error.
# The bootstrap must not depend on a shell's arithmetic parser at all.
installer_bounded_seconds() (
  lc_seconds=${1-};
  case "$lc_seconds" in ''|*[!0-9]*) exit 125 ;; esac;
  while [ "${lc_seconds#0}" != "$lc_seconds" ]; do lc_seconds=${lc_seconds#0}; done;
  [ -n "$lc_seconds" ] && [ "${#lc_seconds}" -le 3 ] || exit 125;
  [ "$lc_seconds" -ge 1 ] && [ "$lc_seconds" -le 900 ] || exit 125;
  printf '%s\n' "$lc_seconds";
);

# Use only integer sleep and seq, both available in busybox-udeb. Do not rely
# on desktop BusyBox's fractional sleep or a timeout/setsid applet. The finite
# sequence is prepared BEFORE launching the child; failures cannot leak a fetch.
# Traps and counters are private to this one operation's subshell.
installer_run_bounded() (
  lc_limit=$(installer_bounded_seconds "${1-}") || exit 125;
  shift;
  [ "$#" -gt 0 ] || exit 125;
  lc_intervals=$(seq 1 "$lc_limit") || exit 125;
  [ -n "$lc_intervals" ] || exit 125;
  set -f;
  "$@" <&0 &
  lc_bounded_pid=$!;
  trap 'installer_stop_tree "$lc_bounded_pid"; exit 129' HUP;
  trap 'installer_stop_tree "$lc_bounded_pid"; exit 130' INT;
  trap 'installer_stop_tree "$lc_bounded_pid"; exit 143' TERM;
  for lc_interval in $lc_intervals; do
    kill -0 "$lc_bounded_pid" 2>/dev/null || break;
    if ! sleep 1; then
      installer_stop_tree "$lc_bounded_pid";
      wait "$lc_bounded_pid" 2>/dev/null || :;
      exit 125;
    fi;
  done;
  if kill -0 "$lc_bounded_pid" 2>/dev/null; then
    installer_stop_tree "$lc_bounded_pid";
    wait "$lc_bounded_pid" 2>/dev/null || :;
    exit 124;
  fi;
  if wait "$lc_bounded_pid"; then lc_bounded_status=0; else lc_bounded_status=$?; fi;
  exit "$lc_bounded_status";
);

installer_lifecycle_signal() {
  lc_signal_status=$1;
  trap '' HUP INT TERM;
  installer_record_failure "$lc_signal_status" "${INSTALLER_PHASE:-unknown}" 'supervisor received a termination signal' || :;
  if [ -n "${LC_CHILD_PID:-}" ]; then
    installer_stop_tree "$LC_CHILD_PID" || :;
    wait "$LC_CHILD_PID" 2>/dev/null || :;
    LC_CHILD_PID=;
  fi;
  exit "$lc_signal_status";
};

installer_lifecycle_abort() {
  installer_record_failure "${1:-1}" "${2:-${INSTALLER_PHASE:-unknown}}" "${3:-mandatory operation failed}" || :;
  installer_terminal_hold;
};
installer_lifecycle_exit() {
  lc_exit=$1; trap - 0;
  if [ "$lc_exit" -ne 0 ]; then installer_lifecycle_abort "$lc_exit" "${INSTALLER_PHASE:-unknown}" 'phase exited unsuccessfully'; fi;
  if [ -e "${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}/state/first-failure" ]; then installer_terminal_hold; fi;
  [ "${INSTALLER_LIFECYCLE_COMPLETE:-0}" = 1 ] || installer_lifecycle_abort 125 "${INSTALLER_PHASE:-unknown}" 'phase exited without explicit completion';
};
installer_lifecycle_arm() {
  INSTALLER_PHASE=$1; INSTALLER_LIFECYCLE_ACTIVE=1; INSTALLER_LIFECYCLE_COMPLETE=0;
  export INSTALLER_PHASE INSTALLER_LIFECYCLE_ACTIVE;
  case "$INSTALLER_PHASE" in ''|*[!A-Za-z0-9_.-]*) installer_lifecycle_abort 125 lifecycle 'invalid phase identifier' ;; esac;
  installer_lifecycle_paths || installer_lifecycle_abort 125 lifecycle 'unsafe or unavailable lifecycle state directory';
  trap 'installer_lifecycle_exit "$?"' 0;
  trap 'installer_lifecycle_signal 129' HUP; trap 'installer_lifecycle_signal 130' INT; trap 'installer_lifecycle_signal 143' TERM;
  [ ! -e "$LC_STATE/first-failure" ] && [ ! -L "$LC_STATE/first-failure" ] || installer_terminal_hold;
};
installer_lifecycle_begin() {
  installer_lifecycle_arm "$1";
  # A completed phase is a no-op; an interrupted phase must never be guessed
  # resumable (particularly partman). Both decisions precede target changes.
  if [ -f "$LC_STATE/$INSTALLER_PHASE.done" ] && [ ! -L "$LC_STATE/$INSTALLER_PHASE.done" ]; then
    INSTALLER_LIFECYCLE_COMPLETE=1; return 10;
  fi;
  mkdir "$LC_STATE/$INSTALLER_PHASE.running" 2>/dev/null || installer_lifecycle_abort 125 "$INSTALLER_PHASE" 'interrupted or concurrent invocation';
};
installer_lifecycle_complete() {
  installer_lifecycle_paths || installer_lifecycle_abort 125 lifecycle 'cannot publish completion';
  [ ! -e "$LC_STATE/first-failure" ] || installer_terminal_hold;
  lc_done=$(mktemp "$LC_STATE/.done.XXXXXX") || installer_lifecycle_abort 125 lifecycle 'cannot stage completion';
  printf 'phase=%s\nstate=complete\n' "$INSTALLER_PHASE" >"$lc_done" || installer_lifecycle_abort 125 lifecycle 'cannot write completion';
  chmod 0600 "$lc_done" && mv -f "$lc_done" "$LC_STATE/$INSTALLER_PHASE.done" || installer_lifecycle_abort 125 lifecycle 'cannot publish completion';
  rmdir "$LC_STATE/$INSTALLER_PHASE.running" 2>/dev/null || :;
  INSTALLER_LIFECYCLE_COMPLETE=1;
};
installer_guard_hook() (
  set -eu; umask 077;
  lc_hook=$1; lc_group=$2;
  installer_lifecycle_paths || exit 1;
  case "$LC_ROOT" in *[!A-Za-z0-9_./-]*) exit 1 ;; esac;
  lc_name=${lc_hook##*/}; lc_id=hook-$lc_group-$lc_name;
  case "$lc_id" in *[!A-Za-z0-9_.-]*) exit 1 ;; esac;
  [ -f "$lc_hook" ] && [ ! -L "$lc_hook" ] || exit 1;
  if grep -Fqx '# INSTALLER_GUARDED_HOOK_V1' "$lc_hook"; then exit 0; fi;
  lc_runner=$LC_ROOT/bootstrap/guard-hook.sh;
  [ -x "$lc_runner" ] && [ ! -L "$lc_runner" ] || exit 1;
  lc_backup_dir=$LC_ROOT/bootstrap/supervised/$lc_id;
  lc_backup=$lc_backup_dir/$lc_name;
  mkdir -p "$lc_backup_dir" || exit 1;
  chmod 0700 "$lc_backup_dir" || exit 1;
  if [ -e "$lc_backup" ] || [ -L "$lc_backup" ]; then
    [ -f "$lc_backup" ] && [ ! -L "$lc_backup" ] && cmp -s "$lc_hook" "$lc_backup" || exit 1;
  else
    lc_tmp=$(mktemp "$lc_backup_dir/.original.XXXXXX") || exit 1;
    cp "$lc_hook" "$lc_tmp" && chmod 0700 "$lc_tmp" && mv "$lc_tmp" "$lc_backup" || exit 1;
  fi;
  lc_tmp=$(mktemp "${lc_hook}.guard.XXXXXX") || exit 1;
  trap 'rm -f "$lc_tmp"' 0;
  printf '#!/bin/sh\n# INSTALLER_GUARDED_HOOK_V1\nexec "%s" "%s" "%s" "$@"\n' "$lc_runner" "$lc_id" "$lc_backup" >"$lc_tmp" || exit 1;
  chmod 0755 "$lc_tmp" && mv -f "$lc_tmp" "$lc_hook" || exit 1;
);
# END EMBEDDED LIFECYCLE
# BEGIN EMBEDDED APT SOURCES
#!/bin/sh
# APT source publication shared by early bootstrap and apt-setup. No APT update
# is safe until this has run; a Pre-Invoke hook would be too late for source parsing.
installer_apt_safe_path() (
  set -eu
  p=$1
  case "$p" in /*) ;; *) exit 1 ;; esac
  case "/${p#/}/" in *'/../'*|*'/./'*|*'//'*) exit 1 ;; esac
  while [ "$p" != / ]; do
    [ ! -L "$p" ] || exit 1
    if [ -e "$p" ]; then
      [ "$(installer_metadata_value "$p" uid)" = "$(id -u)" ] || exit 1
      mode=$(installer_metadata_value "$p" mode)
      [ "$((0$mode & 0022))" -eq 0 ] || { [ -d "$p" ] && [ "$((0$mode & 01000))" -ne 0 ]; } || exit 1
    fi
    p=${p%/*}; [ -n "$p" ] || p=/
  done
)

installer_apt_strip_cdrom() (
  set -eu
  umask 077
  target=$1
  installer_apt_safe_path "$target/etc/apt/sources.list.d"
  for src in "$target/etc/apt/sources.list" "$target/etc/apt/sources.list.d/"*; do
    [ -e "$src" ] || [ -L "$src" ] || continue
    case "$src" in *.list|*.list.*|*.sources|*.sources.*) ;; *) continue ;; esac
    installer_apt_safe_path "$src"
    [ -f "$src" ] && [ "$(installer_metadata_value "$src" links)" = 1 ] || exit 1
    tmp=$(mktemp "${src%/*}/.installer-source.XXXXXX")
    trap 'rm -f "$tmp"' 0
    case "$src" in
      *.sources|*.sources.*)
        awk 'BEGIN {RS=""; ORS="\n\n"} index($0,"cdrom:")==0 {print}' "$src" >"$tmp" ;;
      *) awk 'index($0,"cdrom:")==0 {print}' "$src" >"$tmp" ;;
    esac
    chmod "$(installer_metadata_value "$src" mode)" "$tmp"
    mv -f "$tmp" "$src"
  done
)

installer_apt_bootstrap_source() (
  set -eu
  umask 077
  target=$1; protocol=$2; host=$3; directory=$4; suite=$5
  case "$protocol" in http|https) ;; *) exit 1 ;; esac
  case "$host" in ''|*[!A-Za-z0-9.:-]*) exit 1 ;; esac
  case "$directory" in /*) ;; *) exit 1 ;; esac
  case "$directory" in *[!A-Za-z0-9/_-]*|*..*|*//*) exit 1 ;; esac
  case "$suite" in ''|*[!A-Za-z0-9_-]*) exit 1 ;; esac
  installer_apt_safe_path "$target/etc/apt/sources.list"
  installer_apt_safe_path "$target/etc/apt/apt.conf.d"
  [ -s "$target/usr/share/keyrings/debian-archive-keyring.gpg" ] || exit 1
  mkdir -p "$target/etc/apt/sources.list.d" "$target/etc/apt/apt.conf.d"
  installer_apt_strip_cdrom "$target"
  tmp=$(mktemp "$target/etc/apt/.installer-bootstrap.XXXXXX")
  trap 'rm -f "$tmp"' 0
  printf 'deb [signed-by=/usr/share/keyrings/debian-archive-keyring.gpg] %s://%s%s %s main contrib non-free non-free-firmware\n' \
    "$protocol" "$host" "$directory" "$suite" >"$tmp"
  chmod 0644 "$tmp"
  mv -f "$tmp" "$target/etc/apt/sources.list"
  tmp=$(mktemp "$target/etc/apt/apt.conf.d/.installer-network.XXXXXX")
  cat >"$tmp" <<'EOF'
Acquire::Retries "3";
Acquire::http::Timeout "45";
Acquire::https::Timeout "45";
APT::Update::Error-Mode "any";
EOF
  chmod 0644 "$tmp"
  mv -f "$tmp" "$target/etc/apt/apt.conf.d/99installer-network"
)
# END EMBEDDED APT SOURCES

installer_runtime_dir() {
  printf '%s\n' "${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}"
}

installer_runtime_state_dir() {
  printf '%s/state\n' "${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}"
}

installer_runtime_cache_dir() {
  printf '%s/cache\n' "${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}"
}

installer_runtime_seed_cache_dir() {
  printf '%s/cache/seed\n' "${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}"
}

installer_runtime_log_dir() {
  printf '%s\n' /tmp
}

installer_runtime_log_file() {
  printf '%s\n' /tmp/installer.log
}

installer_runtime_temp_log_dir() {
  printf '%s/state/tmp\n' "$(installer_runtime_dir)"
}

installer_target_log_dir() {
  printf '%s/var/lib/installer-state\n' "${INSTALLER_TARGET_DIR:-/target}"
}

installer_target_log_root_dir() {
  printf '%s/var/lib/installer-state\n' "${INSTALLER_TARGET_DIR:-/target}"
}

installer_target_log_file() {
  printf '%s/var/lib/installer-state/installer.log\n' "${INSTALLER_TARGET_DIR:-/target}"
}

installer_runtime_bootstrap_dir() {
  printf '%s/bootstrap\n' "${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}"
}

installer_bootstrap_seed_url_path() {
  printf '%s/bootstrap/seed.url\n' "${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}"
}

installer_bootstrap_seed_file_path() {
  printf '%s/bootstrap/seed.file\n' "${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}"
}

installer_bootstrap_helper_path() {
  printf '%s/bootstrap/preseed-bootstrap-entry.sh\n' "${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}"
}

installer_bootstrap_lib_path() {
  printf '%s/bootstrap/bootstrap.sh\n' "${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}"
}

installer_bootstrap_seed_meta_path() {
  printf '%s/bootstrap/seed.meta\n' "${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}"
}

installer_phase_bootstrap_log_path() {
  phase_name=$1
  case "$phase_name" in
    prepare-context|apply|early|partman|late) installer_runtime_log_file ;;
    *) return 1 ;;
  esac
}

installer_context_env_path() {
  printf '%s/state/context.env\n' "${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}"
}

installer_class_policy_env_path() {
  printf '%s/state/class-policy.env\n' "${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}"
}

installer_load_context_if_present() {
  context_env=$(installer_context_env_path)
  [ -r "$context_env" ] || return 1
  # shellcheck disable=SC1090
  . "$context_env"
}

installer_class_list_has_default() {
  installer_default_class_list=${1:-}

  for installer_default_token in $(printf '%s\n' "$installer_default_class_list" | tr ';,' '  '); do
    case "$installer_default_token" in
      default)
        return 0
        ;;
    esac
  done
  return 1
}

installer_default_classes_raw() {
  installer_default_seed_base=${1:-}

  installer_ensure_repo_env "$installer_default_seed_base"
  [ -n "${DEBIAN_DEFAULT_CLASSES:-}" ] || installer_fatal "DEBIAN_DEFAULT_CLASSES is unset in repo.env"
  printf '%s\n' "$DEBIAN_DEFAULT_CLASSES"
}

installer_expand_default_classes() {
  installer_default_seed_base=$1
  installer_default_classes_input=${2:-}

  installer_class_list_has_default "$installer_default_classes_input" || {
    printf '%s\n' "$installer_default_classes_input"
    return 0
  }

  installer_default_classes_value=$(installer_default_classes_raw "$installer_default_seed_base")
  [ -n "$installer_default_classes_value" ] || installer_fatal "DEBIAN_DEFAULT_CLASSES must not be empty when classes=default is selected"

  {
    for installer_class_token in $(printf '%s\n' "$installer_default_classes_input" | tr ';,' '  '); do
      [ -n "$installer_class_token" ] || continue
      case "$installer_class_token" in
        default)
          printf '%s\n' "$installer_default_classes_value" | tr ';,' '\n'
          ;;
        *)
          printf '%s\n' "$installer_class_token"
          ;;
      esac
    done
  } | sed '/^[[:space:]]*$/d; s/^[[:space:]]*//; s/[[:space:]]*$//' |
    awk '
      BEGIN { out = "" }
      NF {
        out = out (out == "" ? "" : ",") $0
      }
      END {
        print out
      }
    '
}

installer_logging_enabled() {
  return 0
}

installer_export_logging_policy() {
  INSTALLER_DEBUG_LOGS=1
  INSTALLER_LOG_LEVEL=debug
  export INSTALLER_DEBUG_LOGS INSTALLER_LOG_LEVEL
}

installer_log_tag() {
  if [ -n "${INSTALLER_LOG_TAG:-}" ]; then
    printf '%s\n' "$INSTALLER_LOG_TAG"
    return 0
  fi

  script_name=${0##*/}
  [ -n "$script_name" ] || script_name=installer
  printf '%s\n' "$script_name"
}

installer_log_timestamp() {
  date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || printf '%s\n' unknown-time
}

installer_log_epoch() {
  date -u '+%s' 2>/dev/null || printf '\n'
}

installer_log_level_canonical() {
  case "${1:-info}" in
    debug|DEBUG) printf '%s\n' debug ;;
    info|INFO) printf '%s\n' info ;;
    warn|WARN|warning|WARNING) printf '%s\n' warning ;;
    error|ERROR|fatal|FATAL) printf '%s\n' error ;;
    none|NONE) printf '%s\n' none ;;
    *) printf '%s\n' info ;;
  esac
}

installer_log_level_is_valid() {
  case "${1:-info}" in
    debug|DEBUG|info|INFO|warn|WARN|warning|WARNING|error|ERROR|none|NONE)
      return 0
      ;;
  esac
  return 1
}

installer_log_level_value() {
  case "$(installer_log_level_canonical "$1")" in
    debug) printf '%s\n' 10 ;;
    info) printf '%s\n' 20 ;;
    warning) printf '%s\n' 30 ;;
    error) printf '%s\n' 40 ;;
    none) printf '%s\n' 99 ;;
  esac
}

installer_log_should_emit() {
  requested_level=$(installer_log_level_canonical "$1")
  installer_logging_enabled || return 1
  active_level=$(installer_log_level_canonical "${INSTALLER_LOG_LEVEL:-debug}")

  [ "$active_level" != none ] || return 1
  requested_value=$(installer_log_level_value "$requested_level")
  active_value=$(installer_log_level_value "$active_level")
  [ "$requested_value" -ge "$active_value" ]
}

installer_emit_console_error() {
  installer_console_level=$(installer_log_level_canonical "${1:-error}")
  shift
  printf '%s stage=%s level=%s component=%s %s\n' \
    "$(installer_log_timestamp)" \
    "$(installer_log_stage)" \
    "$installer_console_level" \
    "$(installer_log_tag)" \
    "$*" >&2
}

installer_validate_log_level() {
  installer_log_level_is_valid "${1:-info}" || installer_fatal "installer log level must be debug, info, warning, error, or none"
}

installer_debug() {
  installer_log_record debug "$*"
}

installer_stage_valid() {
  case "${1:-}" in
    boot|preseed_loaded|network_configured|disk_discovery|partman_start|partman_done|base_install_start|base_install_done|apt_config|package_install|bootloader|late_command|target_customization|first_boot|post_install_validation)
      return 0
      ;;
  esac
  return 1
}

installer_stage_from_tag() {
  case "${1:-}" in
    class-auto|early-dispatch) printf '%s\n' boot ;;
    preseed-*|d-i-early) printf '%s\n' preseed_loaded ;;
    partman-layout|partman-*) printf '%s\n' partman_start ;;
    base-installer-*) printf '%s\n' base_install_start ;;
    apt-*|apt) printf '%s\n' apt_config ;;
    bootloader|grub|secure-boot) printf '%s\n' bootloader ;;
    late-command|late-*) printf '%s\n' late_command ;;
    finish-install-*|finish-install) printf '%s\n' post_install_validation ;;
    firstboot|first-boot) printf '%s\n' first_boot ;;
    *) printf '%s\n' "${INSTALLER_LOG_STAGE:-preseed_loaded}" ;;
  esac
}

installer_log_stage() {
  if installer_stage_valid "${INSTALLER_LOG_STAGE:-}"; then
    printf '%s\n' "$INSTALLER_LOG_STAGE"
    return 0
  fi
  installer_stage_from_tag "$(installer_log_tag)"
}

installer_log_category_name() {
  category=$1

  case "$category" in
    boot|preseed|network|disk|partman|apt|package|bootloader|late|desktop|firstboot)
      printf '%s\n' installer.log
      ;;
    *) return 1 ;;
  esac
}

installer_log_stage_for_category() {
  category=$1

  case "$category" in
    boot) printf '%s\n' boot ;;
    preseed) printf '%s\n' preseed_loaded ;;
    network) printf '%s\n' network_configured ;;
    disk) printf '%s\n' disk_discovery ;;
    partman) printf '%s\n' partman_start ;;
    apt) printf '%s\n' apt_config ;;
    package) printf '%s\n' package_install ;;
    bootloader) printf '%s\n' bootloader ;;
    late) printf '%s\n' late_command ;;
    desktop) printf '%s\n' target_customization ;;
    firstboot) printf '%s\n' first_boot ;;
    *) printf '%s\n' post_install_validation ;;
  esac
}

installer_log_category_file() {
  category=$1
  installer_log_category_name "$category" >/dev/null || return 1
  installer_runtime_log_file
}

installer_append_log_category() {
  category=$1
  stage=$2
  level=$3
  component=$4
  shift 4

  level=$(installer_log_level_canonical "$level")
  installer_log_should_emit "$level" || return 0
  installer_stage_valid "$stage" || stage=preseed_loaded
  category_log_path=$(installer_log_category_file "$category") || return 1
  category_log_dir=$(dirname "$category_log_path")
  [ -d "$category_log_dir" ] || install -d -m 0700 "$category_log_dir"
  printf '%s stage=%s level=%s component=%s %s\n' \
    "$(installer_log_timestamp)" \
    "$stage" \
    "$level" \
    "$component" \
    "$*" >>"$category_log_path"
}

installer_append_log_category_file() {
  category=$1
  stage=$2
  level=$3
  component=$4
  source_file=$5

  level=$(installer_log_level_canonical "$level")
  installer_log_should_emit "$level" || return 0
  [ -s "$source_file" ] || return 0
  installer_stage_valid "$stage" || stage=preseed_loaded
  category_log_path=$(installer_log_category_file "$category") || return 1
  category_log_dir=$(dirname "$category_log_path")
  [ -d "$category_log_dir" ] || install -d -m 0700 "$category_log_dir"
  log_timestamp=$(installer_log_timestamp)
  while IFS= read -r log_line || [ -n "$log_line" ]; do
    [ -n "$log_line" ] || continue
    printf '%s stage=%s level=%s component=%s %s\n' \
      "$log_timestamp" \
      "$stage" \
      "$level" \
      "$component" \
      "$log_line"
  done <"$source_file" >>"$category_log_path"
}

installer_log_record() {
  log_level=$1
  shift
  log_level=$(installer_log_level_canonical "$log_level")
  if ! installer_log_should_emit "$log_level"; then
    [ "$log_level" = error ] || return 0
    installer_emit_console_error "$log_level" "$*"
    return 0
  fi
  printf '%s stage=%s level=%s component=%s %s\n' \
    "$(installer_log_timestamp)" \
    "$(installer_log_stage)" \
    "$log_level" \
    "$(installer_log_tag)" \
    "$*" >&2
}

installer_log() {
  installer_log_message=$*
  case "$installer_log_message" in
    "info: "*) installer_log_record info "${installer_log_message#info: }" ;;
    "warn: "*) installer_log_record warning "${installer_log_message#warn: }" ;;
    "warning: "*) installer_log_record warning "${installer_log_message#warning: }" ;;
    "error: "*) installer_log_record error "${installer_log_message#error: }" ;;
    "fatal: "*) installer_log_record error "${installer_log_message#fatal: }" ;;
    "debug: "*) installer_log_record debug "${installer_log_message#debug: }" ;;
    *) installer_log_record info "$installer_log_message" ;;
  esac
}

installer_info() {
  installer_log_record info "$*"
}

installer_warn() {
  installer_log_record warning "$*"
}

installer_error() {
  installer_log_record error "$*"
}

installer_trim_whitespace() {
  printf '%s' "$1" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//'
}

# shellcheck disable=SC2034 # Exposes INSTALLER_MOUNT_* fields for callers.
installer_mounts_find_record() {
  installer_mountpoint=$1
  installer_mounts_file=${2:-/proc/mounts}
  INSTALLER_MOUNT_SOURCE=
  INSTALLER_MOUNT_POINT=
  INSTALLER_MOUNT_FSTYPE=
  INSTALLER_MOUNT_OPTIONS=

  [ -r "$installer_mounts_file" ] || return 1
	  while IFS=' ' read -r mount_source mount_point mount_fstype mount_options _mount_rest || [ -n "${mount_source:-}" ]; do
	    [ "$mount_point" = "$installer_mountpoint" ] || continue
	    INSTALLER_MOUNT_SOURCE=$mount_source
	    INSTALLER_MOUNT_POINT=$mount_point
	    INSTALLER_MOUNT_FSTYPE=$mount_fstype
    INSTALLER_MOUNT_OPTIONS=$mount_options
    return 0
  done <"$installer_mounts_file"
  return 1
}

installer_mounts_has_mountpoint() {
  installer_mounts_find_record "$1" "${2:-/proc/mounts}" >/dev/null 2>&1
}

installer_mount_source_for_mountpoint() {
  installer_mounts_find_record "$1" "${2:-/proc/mounts}" || return 1
  printf '%s\n' "$INSTALLER_MOUNT_SOURCE"
}

installer_target_is_mounted() {
  [ -d /target ] || return 1
  installer_mounts_has_mountpoint /target /proc/mounts
}

installer_escape_sed_replacement() {
  printf '%s' "$1" | sed 's/[&|\\]/\\&/g'
}

installer_contains_unresolved_installer_placeholders() {
  installer_placeholder_path=$1

  [ -r "$installer_placeholder_path" ] || return 1
  LC_ALL=C grep -q '__INSTALLER_' "$installer_placeholder_path"
}

installer_assert_no_unresolved_installer_placeholders() {
  installer_placeholder_path=$1
  installer_placeholder_label=${2:-$installer_placeholder_path}

  installer_contains_unresolved_installer_placeholders "$installer_placeholder_path" || return 0

  installer_unresolved_tokens=$(
    LC_ALL=C grep -o '__INSTALLER_[A-Z0-9_]\+__' "$installer_placeholder_path" 2>/dev/null |
      sort -u |
      tr '\n' ' '
  )
  installer_unresolved_tokens=${installer_unresolved_tokens%" "}
  [ -n "$installer_unresolved_tokens" ] || installer_unresolved_tokens="unknown placeholder(s)"
  installer_fatal "${installer_placeholder_label} has unresolved installer placeholders: ${installer_unresolved_tokens}"
}

installer_replace_placeholder_in_file() {
  installer_placeholder_file=$1
  installer_placeholder=$2
  installer_placeholder_value=$3
  installer_placeholder_tmp="${installer_placeholder_file}.replace.$$"
  installer_escaped_placeholder_value=$(installer_escape_sed_replacement "$installer_placeholder_value")

  sed "s|${installer_placeholder}|${installer_escaped_placeholder_value}|g" \
    "$installer_placeholder_file" >"$installer_placeholder_tmp" || {
      rm -f "$installer_placeholder_tmp"
      return 1
    }
  mv "$installer_placeholder_tmp" "$installer_placeholder_file"
}

installer_apply_scalar_placeholders() {
  installer_placeholder_src=$1
  installer_placeholder_dest=$2
  installer_placeholder_script="${installer_placeholder_dest}.sed.$$"
  shift 2

  [ $(( $# % 2 )) -eq 0 ] || installer_fatal "placeholder replacement arguments must be name/value pairs"
  : >"$installer_placeholder_script" || {
    rm -f "$installer_placeholder_script"
    return 1
  }
  while [ "$#" -gt 1 ]; do
    installer_placeholder_name=$1
    installer_placeholder_value=$2
    shift 2
    installer_escaped_placeholder_value=$(installer_escape_sed_replacement "$installer_placeholder_value")
    printf 's|__INSTALLER_%s__|%s|g\n' \
      "$installer_placeholder_name" \
      "$installer_escaped_placeholder_value" >>"$installer_placeholder_script" || {
        rm -f "$installer_placeholder_script"
        return 1
      }
  done
  sed -f "$installer_placeholder_script" "$installer_placeholder_src" >"$installer_placeholder_dest" || {
    rm -f "$installer_placeholder_script" "$installer_placeholder_dest"
    return 1
  }
  rm -f "$installer_placeholder_script"
}

installer_copy_path_with_mode() {
  copy_src_path=$1
  copy_dest_path=$2
  copy_mode=$3
  copy_label=${4:-file}
  copy_parent_dir=$(dirname "$copy_dest_path")
  copy_tmp_path="${copy_dest_path}.tmp.$$"
  copy_err_path="${copy_tmp_path}.copy.err"

  if [ "$copy_src_path" = "$copy_dest_path" ]; then
    chmod "$copy_mode" "$copy_dest_path" 2>/dev/null || true
    return 0
  fi

  [ -d "$copy_parent_dir" ] || install -d -m 0700 "$copy_parent_dir"
  rm -f "$copy_tmp_path" "$copy_err_path"
  if cp "$copy_src_path" "$copy_tmp_path" >"$copy_err_path" 2>&1; then
    copy_status=0
  else
    copy_status=$?
  fi
  if [ "$copy_status" -ne 0 ]; then
    installer_error "failed to copy ${copy_label} from ${copy_src_path} to ${copy_dest_path} (status ${copy_status})"
    [ -s "$copy_err_path" ] && sed 's/^/[cp] /' "$copy_err_path" >&2
    rm -f "$copy_tmp_path" "$copy_err_path"
    return 1
  fi
  rm -f "$copy_err_path"
  [ -s "$copy_tmp_path" ] || installer_fatal "copied ${copy_label} is empty: ${copy_src_path}"
  mv "$copy_tmp_path" "$copy_dest_path"
  chmod "$copy_mode" "$copy_dest_path"
}

installer_log_path_is_numbered() {
  installer_check_log_path=$1
  installer_check_log_name=${installer_check_log_path##*/}

  case "$installer_check_log_name" in
    [0-9]*-*) return 0 ;;
  esac
  return 1
}

installer_log_sequence_file() {
  installer_sequence_log_dir=$1
  printf '%s/.log-sequence\n' "$installer_sequence_log_dir"
}

installer_next_log_sequence() {
  installer_sequence_log_dir=$1
  installer_sequence_path=$(installer_log_sequence_file "$installer_sequence_log_dir")
  installer_sequence_tmp="${installer_sequence_path}.tmp.$$"
  installer_current_sequence=0

  [ -d "$installer_sequence_log_dir" ] || install -d -m 0700 "$installer_sequence_log_dir"
  if [ -r "$installer_sequence_path" ]; then
    installer_current_sequence=$(cat "$installer_sequence_path" 2>/dev/null || printf '0\n')
  fi
  case "$installer_current_sequence" in
    ''|*[!0-9]*) installer_current_sequence=0 ;;
  esac

  installer_next_sequence=$((installer_current_sequence + 1))
  printf '%s\n' "$installer_next_sequence" >"$installer_sequence_tmp"
  mv "$installer_sequence_tmp" "$installer_sequence_path"
  chmod 0600 "$installer_sequence_path" 2>/dev/null || true
  printf '%s\n' "$installer_next_sequence"
}

installer_log_dir_for_path() {
  installer_dir_path=$1
  printf '%s\n' "$(dirname "$installer_dir_path")"
}

installer_basename_for_path() {
  installer_base_path=$1
  printf '%s\n' "${installer_base_path##*/}"
}

installer_runtime_log_path_requested() {
  requested_log_path=$1
  runtime_log_dir=$(installer_runtime_log_dir)

  case "$requested_log_path" in
    "${runtime_log_dir}/"*) return 0 ;;
  esac
  return 1
}

installer_resolve_runtime_log_path() {
  requested_log_path=$1
  printf '%s\n' "$requested_log_path"
}

installer_runtime_temp_log_path() {
  temp_log_name=$1
  temp_log_dir=$(installer_runtime_temp_log_dir)
  temp_log_name=${temp_log_name%.log}
  install -d -m 0700 "$temp_log_dir" 2>/dev/null || true
  printf '%s/%s-%s.err\n' "$temp_log_dir" "$$" "$temp_log_name"
}

installer_resolve_target_log_path() {
  requested_target_log_path=$1
  INSTALLER_RESOLVED_TARGET_LOG_PATH=

  [ -n "$requested_target_log_path" ] || return 1
  if installer_log_path_is_numbered "$requested_target_log_path"; then
    INSTALLER_RESOLVED_TARGET_LOG_PATH=$requested_target_log_path
    return 0
  fi

  if [ -n "${INSTALLER_LOG_TARGET_FILE_RESOLVED:-}" ] && \
     [ "${INSTALLER_LOG_TARGET_FILE:-}" = "$requested_target_log_path" ]
  then
    INSTALLER_RESOLVED_TARGET_LOG_PATH=$INSTALLER_LOG_TARGET_FILE_RESOLVED
    return 0
  fi

  target_log_dir=$(installer_log_dir_for_path "$requested_target_log_path")
  target_log_name=$(installer_basename_for_path "$requested_target_log_path")
  target_log_seq=$(installer_next_log_sequence "$target_log_dir")
  resolved_target_log_path="${target_log_dir}/${target_log_seq}-${target_log_name}"

  if [ "${INSTALLER_LOG_TARGET_FILE:-}" = "$requested_target_log_path" ]; then
    INSTALLER_LOG_TARGET_FILE_RESOLVED=$resolved_target_log_path
  fi

  INSTALLER_RESOLVED_TARGET_LOG_PATH=$resolved_target_log_path
  return 0
}

installer_copy_log_to_target() {
  log_path=$1
  target_log_file=$2

  installer_logging_enabled || return 0
  [ -s "$log_path" ] || return 0
  [ -n "$target_log_file" ] || return 0
  installer_target_is_mounted || return 0

  if installer_log_path_is_numbered "$log_path" && \
     ! installer_log_path_is_numbered "$target_log_file"
  then
    resolved_target_log_file="$(installer_log_dir_for_path "$target_log_file")/$(installer_basename_for_path "$log_path")"
  else
    installer_resolve_target_log_path "$target_log_file" || return 0
    resolved_target_log_file=$INSTALLER_RESOLVED_TARGET_LOG_PATH
  fi
  install -d -m 0700 "$(dirname "$resolved_target_log_file")"
  resolved_target_log_tmp="${resolved_target_log_file}.tmp.$$"
  if installer_redact_log_stream <"$log_path" >"$resolved_target_log_tmp" 2>/dev/null; then
    chmod 0600 "$resolved_target_log_tmp" 2>/dev/null || true
    mv -f "$resolved_target_log_tmp" "$resolved_target_log_file"
  else
    rm -f "$resolved_target_log_tmp" 2>/dev/null || true
    installer_warn "failed to sanitize installer log ${log_path}"
  fi
}

installer_persist_log_file() {
  log_path=$1
  target_log_file=$2

  # Runtime logs are archived once at the end of the installer flow.  Keep this
  # compatibility entrypoint as a no-op so phase hooks do not create partial
  # target-side log copies before finish-install runs.
  [ -n "$log_path" ] || return 0
  [ -n "$target_log_file" ] || return 0
  return 0
}

installer_init_log_file() {
  log_path=$1
  target_log_file=${2:-}
  log_context=${3:-${0##*/}}
  log_tag=${4:-}
  log_stage=${5:-}
  log_path=$(installer_resolve_runtime_log_path "$log_path")

  installer_export_logging_policy
  if ! installer_logging_enabled; then
    INSTALLER_LOG_PATH=
    INSTALLER_LOG_TARGET_FILE=
    INSTALLER_LOG_TARGET_FILE_RESOLVED=
    INSTALLER_LOG_CONTEXT=$log_context
    INSTALLER_LOG_FINALIZED=0
    INSTALLER_LOG_START_EPOCH=$(installer_log_epoch)
    [ -n "$log_tag" ] && INSTALLER_LOG_TAG=$log_tag
    if [ -n "$log_stage" ]; then
      INSTALLER_LOG_STAGE=$log_stage
    else
      INSTALLER_LOG_STAGE=$(installer_stage_from_tag "$(installer_log_tag)")
    fi
    return 0
  fi

  log_dir=$(dirname "$log_path")

  [ -d "$log_dir" ] || install -d -m 0700 "$log_dir" 2>/dev/null || true
  : >>"$log_path" || installer_fatal "unable to initialize log file: ${log_path}"
  chmod 0600 "$log_path" 2>/dev/null || true

  # shellcheck disable=SC2034 # Exposed for phase hooks sourced after logging setup.
  INSTALLER_LOG_PATH=$log_path
  INSTALLER_LOG_TARGET_FILE=$target_log_file
  INSTALLER_LOG_TARGET_FILE_RESOLVED=
  INSTALLER_LOG_CONTEXT=$log_context
  INSTALLER_LOG_FINALIZED=0
  INSTALLER_LOG_START_EPOCH=$(installer_log_epoch)
  if [ -n "$log_tag" ]; then
    INSTALLER_LOG_TAG=$log_tag
  fi
  if [ -n "$log_stage" ]; then
    INSTALLER_LOG_STAGE=$log_stage
  else
    INSTALLER_LOG_STAGE=$(installer_stage_from_tag "$(installer_log_tag)")
  fi

  exec >>"$log_path" 2>&1
  installer_info "starting ${INSTALLER_LOG_CONTEXT}"
  return 0
}

installer_init_stderr_log_file() {
  log_path=$1
  target_log_file=${2:-}
  log_context=${3:-${0##*/}}
  log_tag=${4:-}
  log_stage=${5:-}
  log_path=$(installer_resolve_runtime_log_path "$log_path")

  installer_export_logging_policy
  if ! installer_logging_enabled; then
    INSTALLER_LOG_PATH=
    INSTALLER_LOG_TARGET_FILE=
    INSTALLER_LOG_TARGET_FILE_RESOLVED=
    INSTALLER_LOG_CONTEXT=$log_context
    INSTALLER_LOG_FINALIZED=0
    INSTALLER_LOG_START_EPOCH=$(installer_log_epoch)
    [ -n "$log_tag" ] && INSTALLER_LOG_TAG=$log_tag
    if [ -n "$log_stage" ]; then
      INSTALLER_LOG_STAGE=$log_stage
    else
      INSTALLER_LOG_STAGE=$(installer_stage_from_tag "$(installer_log_tag)")
    fi
    return 0
  fi

  log_dir=$(dirname "$log_path")

  [ -d "$log_dir" ] || install -d -m 0700 "$log_dir" 2>/dev/null || true
  : >>"$log_path" || installer_fatal "unable to initialize log file: ${log_path}"
  chmod 0600 "$log_path" 2>/dev/null || true

  # shellcheck disable=SC2034 # Exposed for phase hooks sourced after logging setup.
  INSTALLER_LOG_PATH=$log_path
  INSTALLER_LOG_TARGET_FILE=$target_log_file
  INSTALLER_LOG_TARGET_FILE_RESOLVED=
  INSTALLER_LOG_CONTEXT=$log_context
  INSTALLER_LOG_FINALIZED=0
  INSTALLER_LOG_START_EPOCH=$(installer_log_epoch)
  if [ -n "$log_tag" ]; then
    INSTALLER_LOG_TAG=$log_tag
  fi
  if [ -n "$log_stage" ]; then
    INSTALLER_LOG_STAGE=$log_stage
  else
    INSTALLER_LOG_STAGE=$(installer_stage_from_tag "$(installer_log_tag)")
  fi

  exec 2>>"$log_path"
  installer_info "starting ${INSTALLER_LOG_CONTEXT}"
  return 0
}

installer_finalize_log() {
  exit_code=${1:-0}

  if [ "${INSTALLER_LOG_FINALIZED:-0}" -eq 1 ]; then
    return 0
  fi
  INSTALLER_LOG_FINALIZED=1

  log_context=${INSTALLER_LOG_CONTEXT:-${0##*/}}
  log_duration=
  if [ -n "${INSTALLER_LOG_START_EPOCH:-}" ]; then
    log_end_epoch=$(installer_log_epoch)
    case "$log_end_epoch:${INSTALLER_LOG_START_EPOCH:-}" in
      [0-9]*:[0-9]*)
        log_duration=" duration_seconds=$((log_end_epoch - INSTALLER_LOG_START_EPOCH))"
        ;;
    esac
  fi
  if [ "$exit_code" -eq 0 ]; then
    installer_info "completed ${log_context}${log_duration}"
  else
    installer_error "${log_context} exited with status ${exit_code}${log_duration}"
    if [ "${INSTALLER_LIFECYCLE_ACTIVE:-0}" = 1 ]; then
      installer_record_failure "$exit_code" "$log_context" 'mandatory operation failed; see preceding diagnostics' || :
    fi
  fi

  if installer_bool_is_true "${INSTALLER_ARCHIVE_LOGS_ON_FINALIZE:-false}"; then
    installer_archive_logs_to_target || true
  fi
}

installer_fatal() {
  installer_log_record error "$*"
  if [ "${INSTALLER_LIFECYCLE_ACTIVE:-0}" = 1 ]; then
    installer_record_failure 1 "${INSTALLER_LOG_CONTEXT:-unknown}" "$*" || :
  fi
  exit 1
}

installer_shell_quote() {
  printf "'%s'" "$(printf '%s' "${1-}" | sed "s/'/'\\\\''/g")"
}

installer_cmdline() {
  if [ -n "${INSTALLER_CMDLINE:-}" ]; then
    printf '%s\n' "$INSTALLER_CMDLINE"
    return 0
  fi
  if [ "${INSTALLER_CMDLINE_CACHE_READY:-0}" -eq 1 ]; then
    printf '%s\n' "$INSTALLER_CMDLINE_CACHE"
    return 0
  fi
  if [ -n "${INSTALLER_CMDLINE_FILE:-}" ] && [ -r "$INSTALLER_CMDLINE_FILE" ]; then
    INSTALLER_CMDLINE_CACHE=$(cat "$INSTALLER_CMDLINE_FILE")
    INSTALLER_CMDLINE_CACHE_READY=1
    printf '%s\n' "$INSTALLER_CMDLINE_CACHE"
    return 0
  fi
  if [ -r /proc/cmdline ]; then
    INSTALLER_CMDLINE_CACHE=$(cat /proc/cmdline)
    INSTALLER_CMDLINE_CACHE_READY=1
    printf '%s\n' "$INSTALLER_CMDLINE_CACHE"
    return 0
  fi
  INSTALLER_CMDLINE_CACHE=
  INSTALLER_CMDLINE_CACHE_READY=1
  printf '\n'
}

installer_cmdline_parameter_present() (
  set -f
  IFS=' 	
'
  installer_cmdline_presence_key=$1

  for installer_cmdline_presence_arg in $(installer_cmdline); do
    case "$installer_cmdline_presence_arg" in
      "$installer_cmdline_presence_key"|"$installer_cmdline_presence_key"=*)
        return 0
        ;;
    esac
  done
  return 1
)

installer_cmdline_fallback_blocked() {
  case "${1:-}" in
    netcfg/wireless_wpa|wireless_wpa|wifi_wpa)
      set -- netcfg/wireless_wpa wireless_wpa wifi_wpa
      ;;
    crowdsec_token|crowdsec_enroll_token|crowdsec_attachment_key)
      set -- crowdsec_token crowdsec_enroll_token crowdsec_attachment_key
      ;;
    tailscale_authkey|tailscale_auth_key)
      set -- tailscale_authkey tailscale_auth_key
      ;;
    *)
      set -- "${1:-}"
      ;;
  esac

  for installer_cmdline_fallback_key in "$@"; do
    [ -n "$installer_cmdline_fallback_key" ] || continue
    if installer_cmdline_parameter_present "$installer_cmdline_fallback_key"; then
      return 0
    fi
  done
  return 1
}

# BEGIN EMBEDDED INITRD CREDENTIALS
#!/bin/sh
# Canonical initrd credential reader. tools/build.py embeds this file in both
# common libraries: no new network fetch or source-path discovery is needed.
# /preseed.env remains TRUSTED SHELL CODE, not an untrusted dotenv import.
# Return codes: 0=value, 1=unmapped/missing/empty, 2=unsafe or unreadable file.

preseed_env_variable_name() {
  case "${1:-}" in
    netcfg/wireless_wpa|wireless_wpa|wifi_wpa) printf '%s\n' PRESEED_WIFI_PASSPHRASE ;;
    fruux_username) printf '%s\n' PRESEED_FRUUX_USERNAME ;;
    fruux_password) printf '%s\n' PRESEED_FRUUX_PASSWORD ;;
    primary_user) printf '%s\n' PRESEED_PRIMARY_USERNAME ;;
    primary_password) printf '%s\n' PRESEED_PRIMARY_PASSWORD ;;
    primary_gpg_passphrase) printf '%s\n' PRESEED_PRIMARY_GPG_PASSPHRASE ;;
    root_password) printf '%s\n' PRESEED_ROOT_PASSWORD ;;
    crowdsec_token|crowdsec_enroll_token|crowdsec_attachment_key) printf '%s\n' PRESEED_CROWDSEC_TOKEN ;;
    tailscale_authkey|tailscale_auth_key) printf '%s\n' PRESEED_TAILSCALE_TOKEN ;;
    telegram_chat_id) printf '%s\n' PRESEED_TELEGRAM_CHAT_ID ;;
    telegram_api_key) printf '%s\n' PRESEED_TELEGRAM_API_KEY ;;
    cf_r2_access_key) printf '%s\n' PRESEED_CF_APTLY_ACCESS_KEY ;;
    cf_r2_secret_key) printf '%s\n' PRESEED_CF_APTLY_SECRET_KEY ;;
    obs_username) printf '%s\n' PRESEED_OBS_USERNAME ;;
    obs_password) printf '%s\n' PRESEED_OBS_PASSWORD ;;
    *) return 1 ;;
  esac
}

preseed_env_error() {
  # Never include file contents, command-line text, or a secret in diagnostics.
  printf '[credentials] error: %s\n' "$*" >&2
  return 2
}

preseed_env_check_file() (
  set +x
  set +v
  set -f
  IFS=' 	
'
  preseed_check_path=$1
  case "$preseed_check_path" in
    /*) ;;
    *) preseed_env_error 'credential file path must be absolute'; return 2 ;;
  esac
  case "$preseed_check_path" in
    *[![:print:]]*|*/../*|*/./*|*//*)
      preseed_env_error 'credential file path is not canonical'; return 2 ;;
  esac
  if [ -L "$preseed_check_path" ]; then
    preseed_env_error 'credential file must not be a symlink'; return 2
  fi
  [ -e "$preseed_check_path" ] || return 1
  if [ ! -f "$preseed_check_path" ] || [ ! -r "$preseed_check_path" ]; then
    preseed_env_error 'credential file must be a readable regular file'; return 2
  fi
  preseed_check_uid=$(id -u) || {
    preseed_env_error 'cannot determine installer UID'; return 2;
  }
  # Debian busybox-udeb deliberately has no stat applet. Numeric ls metadata
  # uses applets present in the real initrd, not just full desktop BusyBox.
  preseed_check_metadata=$(LC_ALL=C ls -ldn "$preseed_check_path" 2>/dev/null) || {
    preseed_env_error 'cannot inspect credential file with ls -ldn'; return 2;
  }
  set -- $preseed_check_metadata
  if [ "$#" -lt 4 ] || [ "$3" != "$preseed_check_uid" ] || [ "$2" != 1 ]; then
    preseed_env_error 'credential file must be owned by the installer UID (root in d-i) and have one hard link'; return 2
  fi
  preseed_check_mode=$1
  case "$preseed_check_mode" in
    -r--------|-rw-------) ;;
    -r--r-----|-r-----r--|-r--r--r--|-rw-r-----|-rw----r--|-rw-r--r--)
      # Initrd builders often preserve 0644. These files are not writable by
      # other users: reduce read access before sourcing rather than ignoring.
      ;;
    *)
      preseed_env_error 'credential file has unsafe permissions; use root ownership and mode 0400 or 0600'; return 2 ;;
  esac
  # Reject replaceable path components before sourcing root-owned shell code.
  # A root/invoking-UID-owned sticky directory (e.g. /tmp) is safe for files
  # owned by that UID. Do not follow symlinked directories.
  preseed_check_parent=${preseed_check_path%/*}
  [ -n "$preseed_check_parent" ] || preseed_check_parent=/
  while :; do
    if [ -L "$preseed_check_parent" ] || [ ! -d "$preseed_check_parent" ]; then
      preseed_env_error 'credential file has a symlinked or invalid parent directory'; return 2
    fi
    preseed_check_metadata=$(LC_ALL=C ls -ldn "$preseed_check_parent" 2>/dev/null) || {
      preseed_env_error 'cannot inspect credential parent directory'; return 2;
    }
    set -- $preseed_check_metadata
    if [ "$#" -lt 4 ] || { [ "$3" != 0 ] && [ "$3" != "$preseed_check_uid" ]; }; then
      preseed_env_error 'credential parent directory is not trusted'; return 2
    fi
    case "$1" in
      ?????w????|????????w?)
        case "$1" in
          ?????????t|?????????T) ;;
          *) preseed_env_error 'credential parent directory is writable by other users without sticky protection'; return 2 ;;
        esac ;;
    esac
    [ "$preseed_check_parent" != / ] || break
    preseed_check_parent=${preseed_check_parent%/*}
    [ -n "$preseed_check_parent" ] || preseed_check_parent=/
  done
  case "$preseed_check_mode" in
    -r--------|-rw-------) ;;
    *)
      chmod 0600 "$preseed_check_path" 2>/dev/null || {
        preseed_env_error 'cannot make initrd credentials private; rebuild the initrd with mode 0600'; return 2;
      }
      preseed_check_metadata=$(LC_ALL=C ls -ldn "$preseed_check_path" 2>/dev/null) || return 2
      set -- $preseed_check_metadata
      if [ "$1:$2:$3" != "-rw-------:1:$preseed_check_uid" ]; then
        preseed_env_error 'credential file metadata changed while hardening'; return 2
      fi
      printf '[credentials] made initrd credential file private (0600); preserve this mode when rebuilding the USB\n' >&2
      ;;
  esac
)

preseed_env_read_value() (
  set +x
  set +v
  set -f
  IFS=' 	
'
  umask 077
  preseed_read_name=$(preseed_env_variable_name "${1:-}") || return 1
  preseed_read_file=${INSTALLER_PRESEED_ENV_FILE:-/preseed.env}
  preseed_env_check_file "$preseed_read_file" || return $?

  # Normalize only line terminators and an initial UTF-8 BOM. A private copy
  # avoids modifying the initrd's contents. All source output is suppressed:
  # an accidental echo or shell error must not enter password/log streams.
  preseed_read_tmp=$(mktemp /tmp/preseed-env.XXXXXX) || {
    preseed_env_error 'cannot create private credential staging file'; return 2;
  }
  trap 'rm -f "$preseed_read_tmp"' 0
  trap 'exit 2' 1 2 3 15
  preseed_read_cr=$(printf '\r')
  preseed_read_bom=$(printf '\357\273\277')
  if ! LC_ALL=C sed "1s/^${preseed_read_bom}//;s/${preseed_read_cr}\$//" \
      "$preseed_read_file" >"$preseed_read_tmp" 2>/dev/null; then
    preseed_env_error 'cannot normalize credential file'; return 2
  fi
  if ! /bin/sh -n "$preseed_read_tmp" >/dev/null 2>&1; then
    preseed_env_error 'credential file has invalid shell syntax; check assignment quoting without displaying passwords'; return 2
  fi
  unset PRESEED_WIFI_PASSPHRASE PRESEED_FRUUX_USERNAME PRESEED_FRUUX_PASSWORD \
    PRESEED_PRIMARY_USERNAME PRESEED_PRIMARY_PASSWORD PRESEED_PRIMARY_GPG_PASSPHRASE \
    PRESEED_ROOT_PASSWORD PRESEED_CROWDSEC_TOKEN PRESEED_TAILSCALE_TOKEN \
    PRESEED_TELEGRAM_CHAT_ID PRESEED_TELEGRAM_API_KEY PRESEED_CF_APTLY_ACCESS_KEY \
    PRESEED_CF_APTLY_SECRET_KEY PRESEED_OBS_USERNAME PRESEED_OBS_PASSWORD
  # shellcheck disable=SC1090
  if ! . "$preseed_read_tmp" >/dev/null 2>&1; then
    preseed_env_error 'credential file failed while loading trusted shell assignments'; return 2
  fi
  # The only inserted text is an identifier from the fixed mapping above.
  # The value is expanded once as data, never re-evaluated as shell input.
  eval 'preseed_read_result=${'"$preseed_read_name"'-}'
  [ -n "$preseed_read_result" ] || return 1
  printf '%s\n' "$preseed_read_result"
)
# END EMBEDDED INITRD CREDENTIALS

installer_preseed_env_value() (
  preseed_env_read_value "$@"
)

installer_cmdline_value() (
  set +x
  set +v
  # The first exact parameter wins, including an explicitly empty parameter.
  # Passwords are literal data, not pathname patterns or shell expressions.
  set -f
  IFS=' 	
'
  installer_cmdline_key=$1
  for installer_cmdline_arg in $(installer_cmdline); do
    case "$installer_cmdline_arg" in
      "$installer_cmdline_key")
        printf '\n'
        return 0
        ;;
      "$installer_cmdline_key"=*)
        printf '%s\n' "${installer_cmdline_arg#*=}"
        return 0
        ;;
    esac
  done

  installer_cmdline_fallback_blocked "$installer_cmdline_key" && return 1
  installer_preseed_env_value "$installer_cmdline_key"
)

installer_cmdline_seed_reference_pair() {
  if [ "${INSTALLER_CMDLINE_SEED_PAIR_READY:-0}" -eq 1 ]; then
    return 0
  fi

  INSTALLER_CMDLINE_SEED_URL_BASE=
  INSTALLER_CMDLINE_SEED_FILE_BASE=

  for arg in $(installer_cmdline); do
    case "$arg" in
      preseed/url=*|url=*)
        [ -n "$INSTALLER_CMDLINE_SEED_URL_BASE" ] || INSTALLER_CMDLINE_SEED_URL_BASE=${arg#*=}
        ;;
      preseed/file=*|file=*)
        [ -n "$INSTALLER_CMDLINE_SEED_FILE_BASE" ] || INSTALLER_CMDLINE_SEED_FILE_BASE=${arg#*=}
        ;;
    esac
  done
  INSTALLER_CMDLINE_SEED_PAIR_READY=1
}

installer_cmdline_seed_base() {
  installer_cmdline_seed_reference_pair
  if installer_choose_seed_base_from_pair \
    "${INSTALLER_CMDLINE_SEED_URL_BASE:-}" \
    "${INSTALLER_CMDLINE_SEED_FILE_BASE:-}" \
    "kernel cmdline"
  then
    printf '%s\n' "$INSTALLER_RESOLVED_SEED_BASE"
    return 0
  fi
  return 1
}

installer_debconf_value() {
  question=$1
  value=

  if command -v debconf-get >/dev/null 2>&1; then
    value=$(debconf-get "$question" 2>/dev/null || true)
    case "$value" in
      "$question":\ *) value=${value#"$question": } ;;
      "$question":*) value=${value#"$question":} ;;
    esac
    value=$(printf '%s\n' "$value" | sed -n '1{s/\r$//;p;q;}')
    [ -n "$value" ] || return 1
    printf '%s\n' "$value"
    return 0
  fi

  if command -v debconf-communicate >/dev/null 2>&1; then
    response=$(printf 'GET %s\n' "$question" | debconf-communicate 2>/dev/null || true)
    case "$response" in
      0\ *) value=${response#0 } ;;
      *) value= ;;
    esac
    [ -n "$value" ] || return 1
    printf '%s\n' "$value"
    return 0
  fi

  return 1
}

installer_seed_debconf_value() {
  owner=$1
  question=$2
  value_type=$3
  value=$4

  if command -v debconf-set-selections >/dev/null 2>&1; then
    {
      printf '%s %s %s %s\n' "$owner" "$question" "$value_type" "$value"
      printf '%s %s seen true\n' "$owner" "$question"
    } | debconf-set-selections >/dev/null 2>&1 || true
    return 0
  fi

  if command -v debconf-communicate >/dev/null 2>&1; then
    {
      printf 'SET %s %s\n' "$question" "$value"
      printf 'FSET %s seen true\n' "$question"
    } | debconf-communicate >/dev/null 2>&1 || true
  fi
}

installer_bool_is_true() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
  esac
  return 1
}

installer_bool_is_false() {
  case "${1:-}" in
    0|false|FALSE|no|NO|off|OFF) return 0 ;;
  esac
  return 1
}

installer_read_first_line() {
  [ -r "$1" ] || return 1
  IFS= read -r installer_line_value <"$1" || return 1
  printf '%s' "$installer_line_value"
}

installer_pci_has_display_vendor() {
  wanted_vendor=$1
  pci_devices_root=${INSTALLER_PCI_DEVICES_ROOT:-/sys/bus/pci/devices}

  case "$wanted_vendor" in
    0x[0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f]) ;;
    *) installer_fatal "PCI vendor id must be a four-digit hex value with 0x prefix: ${wanted_vendor:-unset}" ;;
  esac

  for dev_path in "$pci_devices_root"/*; do
    [ -d "$dev_path" ] || continue
    [ -r "$dev_path/vendor" ] || continue
    [ -r "$dev_path/class" ] || continue

    dev_vendor=$(installer_read_first_line "$dev_path/vendor" 2>/dev/null || true)
    dev_class=$(installer_read_first_line "$dev_path/class" 2>/dev/null || true)
    [ -n "$dev_vendor" ] || continue
    [ -n "$dev_class" ] || continue
    case "$dev_class" in
      0x03*)
        [ "$dev_vendor" = "$wanted_vendor" ] && return 0
        ;;
    esac
  done

  return 1
}

installer_nvidia_gpu_detected() {
  installer_pci_has_display_vendor 0x10de
}

installer_nvidia_addon_selected() {
  installer_selected_class_reference_is_selected addon/nvidia 2>/dev/null && return 0
  installer_selected_class_reference_is_selected addon/nvidia-legacy 2>/dev/null && return 0
  return 1
}

installer_nvidia_legacy_selected() {
  installer_selected_class_reference_is_selected addon/nvidia-legacy 2>/dev/null
}

installer_cuda_legacy_selected() {
  installer_selected_class_reference_is_selected addon/cuda-legacy 2>/dev/null
}

installer_log_required_files() {
  printf '%s\n' installer.log
}

installer_ensure_log_files() {
  log_file=$(installer_runtime_log_file)
  log_dir=$(dirname "$log_file")
  [ -d "$log_dir" ] || install -d -m 0700 "$log_dir"
  : >>"$log_file"
  chmod 0600 "$log_file" 2>/dev/null || true
}

installer_prepare_target_log_dirs() {
  installer_target_is_mounted || return 0
  install -d -m 0700 "$(installer_target_log_root_dir)"
}

installer_missing_log_record() {
  log_name=$1
  category=${log_name#*-}
  category=${category%.log}
  case "$category" in
    packages) category=package ;;
    *) ;;
  esac
  stage=$(installer_log_stage_for_category "$category")

  installer_log_should_emit warning || return 0
  printf '%s stage=%s level=warning component=log-archive log_file=%s status=not-created message=%s\n' \
    "$(installer_log_timestamp)" \
    "$stage" \
    "$log_name" \
    "stage did not emit installer log records before final archive"
}

installer_log_redacted_cmdline() {
  redacted_cmdline=
  for cmdline_arg in $(installer_cmdline); do
    case "$cmdline_arg" in
      primary_gpg_passphrase=*|fruux_username=*|fruux_password=*|obs_username=*|telegram_chat_id=*|netcfg/wireless_wpa=*|wireless_wpa=*|wifi_wpa=*|*[Pp][Aa][Ss][Ss]*=*|*[Ss][Ee][Cc][Rr][Ee][Tt]*=*|*[Tt][Oo][Kk][Ee][Nn]*=*|*[Kk][Ee][Yy]*=*)
        cmdline_arg=${cmdline_arg%%=*}=REDACTED
        ;;
    esac
    redacted_cmdline="${redacted_cmdline:+$redacted_cmdline }$cmdline_arg"
  done
  printf '%s\n' "$redacted_cmdline"
}

installer_log_boot_context() {
  installer_ensure_log_files
  installer_append_log_category boot boot info boot "kernel_cmdline=$(installer_log_redacted_cmdline)"
  installer_append_log_category boot boot info boot "kernel_release=$(uname -r 2>/dev/null || printf unknown)"
  installer_append_log_category boot boot info boot "machine=$(uname -m 2>/dev/null || printf unknown)"
  if [ -d /sys/firmware/efi ]; then
    installer_append_log_category boot boot info boot "boot_mode=UEFI"
  else
    installer_append_log_category boot boot info boot "boot_mode=BIOS"
  fi
  if [ -r /etc/debian_version ]; then
    installer_append_log_category boot boot info boot "installer_debian_version=$(cat /etc/debian_version 2>/dev/null || printf unknown)"
  fi
  if [ -n "${INSTALLER_SELECTED_CLASS_REFS:-}" ]; then
    installer_append_log_category boot boot info classes "selected=${INSTALLER_SELECTED_CLASS_REFS}"
  fi
  if [ -n "${INSTALLER_HOST_PROFILE:-}" ]; then
    installer_append_log_category boot boot info classes "host_profile=${INSTALLER_HOST_PROFILE} host_family=${INSTALLER_HOST_FAMILY:-unset} hook_family=${INSTALLER_HOOK_FAMILY:-unset}"
  fi
}

installer_log_network_context() {
  installer_ensure_log_files
  installer_append_log_category network network_configured info network "hostname=$(hostname 2>/dev/null || printf unknown)"
  if command -v ip >/dev/null 2>&1; then
    ip -o link show 2>/dev/null | while IFS= read -r line || [ -n "$line" ]; do
      [ -n "$line" ] || continue
      installer_append_log_category network network_configured info link "$line"
    done
    ip -o addr show 2>/dev/null | while IFS= read -r line || [ -n "$line" ]; do
      [ -n "$line" ] || continue
      installer_append_log_category network network_configured info address "$line"
    done
    ip route show 2>/dev/null | while IFS= read -r line || [ -n "$line" ]; do
      [ -n "$line" ] || continue
      installer_append_log_category network network_configured info route "$line"
    done
  fi
  if [ -r /etc/resolv.conf ]; then
    while IFS=' ' read -r resolver_key nameserver _resolver_rest || [ -n "${resolver_key:-}" ]; do
      [ "$resolver_key" = "nameserver" ] || continue
      [ -n "$nameserver" ] || continue
      installer_append_log_category network network_configured info dns "nameserver=${nameserver}"
    done </etc/resolv.conf
  fi
}

installer_log_disk_context() {
  installer_ensure_log_files
  for disk_sys_path in /sys/block/*; do
    [ -d "$disk_sys_path" ] || continue
    disk_name=${disk_sys_path##*/}
    case "$disk_name" in
      loop*|ram*|dm-*|md*) continue ;;
    esac
    disk_size=$(cat "$disk_sys_path/size" 2>/dev/null || printf unknown)
    disk_removable=$(cat "$disk_sys_path/removable" 2>/dev/null || printf unknown)
    disk_model=$(cat "$disk_sys_path/device/model" 2>/dev/null || printf unknown)
    disk_serial=$(cat "$disk_sys_path/device/serial" 2>/dev/null || printf unknown)
    installer_append_log_category disk disk_discovery info disk "device=/dev/${disk_name} sectors=${disk_size} removable=${disk_removable} model=${disk_model} serial=${disk_serial}"
  done
  if [ -n "${DEV_INSTALL_DISK:-}" ]; then
    installer_append_log_category disk disk_discovery info selected "install_disk=${DEV_INSTALL_DISK}"
  fi
}

installer_log_preseed_context() {
  installer_ensure_log_files
  installer_append_log_category preseed preseed_loaded info preseed "timestamp=$(installer_log_timestamp)"
  installer_append_log_category preseed preseed_loaded info preseed "seed_source=${INSTALLER_SEED_BASE:-${SEED_BASE:-unknown}}"
  installer_append_log_category preseed preseed_loaded info preseed "hostname=${SYSTEM_HOSTNAME:-$(hostname 2>/dev/null || printf unknown)}"
  if command -v ip >/dev/null 2>&1; then
    ip -o addr show scope global 2>/dev/null | while IFS= read -r line || [ -n "$line" ]; do
      [ -n "$line" ] || continue
      installer_append_log_category preseed preseed_loaded info address "$line"
    done
  fi
}

installer_log_category_for_target_command() {
  target_label=$1
  case "$target_label" in
    *apt\ metadata*|*APT\ metadata*|*apt\ preferences*|*APT\ preferences*|*apt\ work*|*APT\ work*)
      printf '%s\n' apt
      return 0
      ;;
    *package*|*Package*|*pkgsel*|*dpkg*|*DKMS*|*dkms*)
      printf '%s\n' package
      return 0
      ;;
    *apt*|*APT*)
      printf '%s\n' apt
      return 0
      ;;
    *GRUB*|*grub*|*Secure\ Boot*|*boot*|*Boot*|*EFI*|*efi*|*shim*|*MOK*|*mok*|*kernel*|*Kernel*|*initramfs*)
      printf '%s\n' bootloader
      return 0
      ;;
    *Labwc*|*labwc*|*desktop*|*Desktop*|*greetd*|*waybar*|*fuzzel*|*mako*|*kanshi*|*thunar*)
      printf '%s\n' desktop
      return 0
      ;;
  esac
  return 1
}

installer_log_target_command_output() {
  category=$1
  stage=$2
  component=$3
  output_file=$4
  output_level=$(installer_log_level_canonical "${5:-info}")

  [ -s "$output_file" ] || return 0

  max_lines=${INSTALLER_COMMAND_LOG_MAX_LINES:-80}
  case "$max_lines" in
    ''|*[!0-9]*) max_lines=80 ;;
  esac
  [ "$max_lines" -gt 0 ] || return 0

  output_lines=$(wc -l <"$output_file" 2>/dev/null || printf '0')
  output_lines=${output_lines##* }
  case "$output_lines" in
    ''|*[!0-9]*) output_lines=0 ;;
  esac

  source_stream=$output_file
  temp_stream=
  if [ "$output_lines" -gt "$max_lines" ] && command -v tail >/dev/null 2>&1; then
    installer_append_log_category "$category" "$stage" "$output_level" "$component" "output_truncated=true original_lines=${output_lines} kept_tail_lines=${max_lines}" || true
    temp_stream=$(installer_runtime_temp_log_path target-command-tail.log)
    tail -n "$max_lines" "$output_file" >"$temp_stream" 2>/dev/null || {
      rm -f "$temp_stream"
      temp_stream=
    }
    [ -n "$temp_stream" ] && source_stream=$temp_stream
  fi

  installer_redact_log_stream <"$source_stream" | while IFS= read -r output_line || [ -n "$output_line" ]; do
    installer_append_log_category "$category" "$stage" "$output_level" "$component" "$output_line" || true
  done

  if [ -n "$temp_stream" ]; then
    rm -f "$temp_stream"
  fi
}

installer_live_log_max_bytes() {
  live_log_max_bytes=${INSTALLER_LIVE_LOG_MAX_BYTES:-4194304}
  case "$live_log_max_bytes" in
    ''|*[!0-9]*) live_log_max_bytes=4194304 ;;
  esac
  printf '%s\n' "$live_log_max_bytes"
}

installer_live_installer_log_files() {
  printf '%s\n' \
    /var/log/syslog \
    /var/log/messages \
    /var/log/partman \
    /var/log/debootstrap.log \
    /var/log/installer/syslog \
    /var/log/installer/partman \
    /var/log/installer/status \
    /var/log/installer/hardware-summary
}

installer_safe_log_filename() {
  printf '%s\n' "$1" | sed 's|^/||; s|/|_|g; s|[^A-Za-z0-9._-]|_|g'
}

installer_redact_log_stream() {
  sed \
    -e 's/\([Pp][Aa][Ss][Ss][^=[:space:]]*[= ][= ]*\)[^[:space:]]*/\1REDACTED/g' \
    -e 's/\([Ss][Ee][Cc][Rr][Ee][Tt][^=[:space:]]*[= ][= ]*\)[^[:space:]]*/\1REDACTED/g' \
    -e 's/\([Tt][Oo][Kk][Ee][Nn][^=[:space:]]*[= ][= ]*\)[^[:space:]]*/\1REDACTED/g' \
    -e 's/\([Tt][Ee][Ll][Ee][Gg][Rr][Aa][Mm]_[Aa][Pp][Ii]_[Kk][Ee][Yy][= ][= ]*\)[^[:space:]]*/\1REDACTED/g' \
    -e 's/\([Tt][Ee][Ll][Ee][Gg][Rr][Aa][Mm]_[Cc][Hh][Aa][Tt]_[Ii][Dd][= ][= ]*\)[^[:space:]]*/\1REDACTED/g' \
    -e 's/\([Ww][Pp][Aa][^=[:space:]]*[= ][= ]*\)[^[:space:]]*/\1REDACTED/g' \
    -e 's/[Pp][Rr][Ee][Ss][Ee][Ee][Dd]/installer/g'
}

installer_archive_live_installer_logs_to_target() {
  installer_logging_enabled || return 0
  target_log_dir=$(installer_target_log_dir)
  live_log_dir="${target_log_dir}/debian-installer"
  max_bytes=$(installer_live_log_max_bytes)

  installer_target_is_mounted || return 0
  install -d -m 0700 "$live_log_dir"

  while IFS= read -r live_log || [ -n "$live_log" ]; do
    [ -n "$live_log" ] || continue
    [ -s "$live_log" ] || continue
    safe_name=$(installer_safe_log_filename "$live_log")
    tmp_log="${live_log_dir}/${safe_name}.tmp.$$"
    dst_log="${live_log_dir}/${safe_name}"
    live_log_size=$(wc -c <"$live_log" 2>/dev/null | tr -d ' ' || printf '0')
    case "$live_log_size" in
      ''|*[!0-9]*) live_log_size=0 ;;
    esac

    if [ "$live_log_size" -gt "$max_bytes" ] && command -v tail >/dev/null 2>&1; then
      {
        printf '# truncated_to_last_bytes=%s original_bytes=%s source=%s\n' "$max_bytes" "$live_log_size" "$live_log"
        tail -c "$max_bytes" "$live_log"
      } | installer_redact_log_stream >"$tmp_log" 2>/dev/null || {
        rm -f "$tmp_log"
        installer_warn "failed to archive live installer log ${live_log}"
        continue
      }
    else
      installer_redact_log_stream <"$live_log" >"$tmp_log" 2>/dev/null || {
        rm -f "$tmp_log"
        installer_warn "failed to archive live installer log ${live_log}"
        continue
      }
    fi
    chmod 0600 "$tmp_log" 2>/dev/null || true
    mv "$tmp_log" "$dst_log"
  done <<EOF
$(installer_live_installer_log_files)
EOF
}

installer_archive_logs_to_target() {
  archive_mode=${1:-copy}
  runtime_log_file=$(installer_runtime_log_file)
  target_log_file=$(installer_target_log_file)

  case "$archive_mode" in
    copy|move) ;;
    *) archive_mode=copy ;;
  esac

  installer_target_is_mounted || return 0
  installer_ensure_log_files
  installer_prepare_target_log_dirs
  tmp_log="${target_log_file}.tmp.$$"

  if installer_redact_log_stream <"$runtime_log_file" >"$tmp_log" 2>/dev/null; then
    chmod 0600 "$tmp_log" 2>/dev/null || true
    mv "$tmp_log" "$target_log_file"
    [ "$archive_mode" = copy ] || rm -f "$runtime_log_file"
  else
    rm -f "$tmp_log"
    installer_warn "failed to archive ${runtime_log_file} to ${target_log_file}"
  fi
}

installer_random_hostname_suffix() {
  raw=$(LC_ALL=C tr -dc '0-9' </dev/urandom | dd bs=3 count=1 2>/dev/null || true)
  case "$raw" in
    [0-9][0-9][0-9]) printf '%s\n' "$raw" ;;
    *) installer_fatal "unable to generate hostname suffix" ;;
  esac
}

installer_ensure_system_identity() {
  : "${SYSTEM_PREFIX:?SYSTEM_PREFIX must be set}"
  : "${SYSTEM_DOMAIN:?SYSTEM_DOMAIN must be set}"
  case "$SYSTEM_PREFIX" in
    ''|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789]*)
      installer_fatal "SYSTEM_PREFIX must contain only ASCII letters and digits"
      ;;
  esac
  case "$SYSTEM_DOMAIN" in
    ''|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.-]*|.*|*.|*..*)
      installer_fatal "SYSTEM_DOMAIN must contain only hostname-safe labels"
      ;;
  esac
  if [ -z "${SYSTEM_HOSTNAME:-}" ]; then
    SYSTEM_HOSTNAME="${SYSTEM_PREFIX}-$(installer_random_hostname_suffix)"
  fi
  case "$SYSTEM_HOSTNAME" in
    "${SYSTEM_PREFIX}"-[0-9][0-9][0-9]) ;;
    *) installer_fatal "SYSTEM_HOSTNAME must match SYSTEM_PREFIX-###" ;;
  esac
}

installer_seed_source_type() {
  case "${1:-}" in
    /*) printf '%s\n' file ;;
    *) printf '%s\n' url ;;
  esac
}

installer_trim_seed_base() {
  seed_base=$1

  while [ "${#seed_base}" -gt 1 ]; do
    case "$seed_base" in
      */) seed_base=${seed_base%/} ;;
      *) break ;;
    esac
  done
  printf '%s\n' "$seed_base"
}

installer_assign_normalized_seed_base() {
  output_var_name=$1
  seed_base=$2
  seed_type=$3

  seed_base=${seed_base%%\?*}
  case "$seed_base" in
    */*.cfg) seed_base=${seed_base%/*} ;;
  esac
  seed_base=$(installer_trim_seed_base "$seed_base")

  case "$seed_type" in
    file)
      case "$seed_base" in
        /*) ;;
        *) installer_fatal "installation file base must be an absolute path: ${seed_base:-unset}" ;;
      esac
      case "$seed_base" in
        *..*|*//*)
          installer_fatal "installation file base contains unsupported traversal: $seed_base"
          ;;
      esac
      ;;
    url)
      [ -n "$seed_base" ] || installer_fatal "installation URL base is empty"
      ;;
    *)
      installer_fatal "unsupported installation source type: $seed_type"
      ;;
  esac

  eval "$output_var_name=\$seed_base"
}

installer_normalize_seed_base() {
  normalized_seed_base=
  installer_assign_normalized_seed_base normalized_seed_base "$1" "$2"
  printf '%s\n' "$normalized_seed_base"
}

installer_persist_seed_source() {
  seed_base=$1
  seed_type=$(installer_seed_source_type "$seed_base")
  seed_url_path=$(installer_bootstrap_seed_url_path)
  seed_file_path=$(installer_bootstrap_seed_file_path)

  install -d -m 0700 "$(installer_runtime_bootstrap_dir)"

  case "$seed_type" in
    file)
      SEED_FILE_BASE=$(installer_normalize_seed_base "$seed_base" file)
      SEED_URL_BASE=
      printf '%s\n' "$SEED_FILE_BASE" >"$seed_file_path"
      rm -f "$seed_url_path"
      ;;
    url)
      SEED_URL_BASE=$(installer_normalize_seed_base "$seed_base" url)
      SEED_FILE_BASE=
      printf '%s\n' "$SEED_URL_BASE" >"$seed_url_path"
      rm -f "$seed_file_path"
      ;;
    *)
      installer_fatal "unsupported installation source type: $seed_type"
      ;;
  esac
}

installer_choose_seed_base_from_pair() {
  url_seed_base=$1
  file_seed_base=$2
  seed_label=$3

  if [ -n "$url_seed_base" ] && [ -n "$file_seed_base" ]; then
    installer_fatal "${seed_label} defines both URL and file seed sources"
  fi
  if [ -n "$url_seed_base" ]; then
    installer_assign_normalized_seed_base INSTALLER_RESOLVED_SEED_BASE "$url_seed_base" url
    return 0
  fi
  if [ -n "$file_seed_base" ]; then
    installer_assign_normalized_seed_base INSTALLER_RESOLVED_SEED_BASE "$file_seed_base" file
    return 0
  fi

  INSTALLER_RESOLVED_SEED_BASE=
  return 1
}

installer_persisted_seed_base() {
  persisted_seed_url_base=
  persisted_seed_file_base=
  persisted_seed_url_path=$(installer_bootstrap_seed_url_path)
  persisted_seed_file_path=$(installer_bootstrap_seed_file_path)

  if [ -f "$persisted_seed_url_path" ]; then
    persisted_seed_url_base=$(cat "$persisted_seed_url_path")
  fi
  if [ -f "$persisted_seed_file_path" ]; then
    persisted_seed_file_base=$(cat "$persisted_seed_file_path")
  fi

  installer_choose_seed_base_from_pair "$persisted_seed_url_base" "$persisted_seed_file_base" "persisted installer state"
}

installer_seed_base() {
  seed_base=${1:-}
  if [ -n "$seed_base" ]; then
    seed_type=$(installer_seed_source_type "$seed_base")
    installer_normalize_seed_base "$seed_base" "$seed_type"
    return 0
  fi
  if [ "${INSTALLER_SEED_BASE_CACHE_READY:-0}" -eq 1 ]; then
    printf '%s\n' "$INSTALLER_SEED_BASE_CACHE"
    return 0
  fi

  if installer_choose_seed_base_from_pair "${SEED_URL_BASE:-}" "${SEED_FILE_BASE:-}" "runtime seed state"; then
    INSTALLER_SEED_BASE_CACHE=$INSTALLER_RESOLVED_SEED_BASE
    INSTALLER_SEED_BASE_CACHE_READY=1
    printf '%s\n' "$INSTALLER_SEED_BASE_CACHE"
    return 0
  fi
  if installer_choose_seed_base_from_pair "${INSTALLER_SEED_URL_BASE:-}" "${INSTALLER_SEED_FILE_BASE:-}" "installer context seed state"; then
    INSTALLER_SEED_BASE_CACHE=$INSTALLER_RESOLVED_SEED_BASE
    INSTALLER_SEED_BASE_CACHE_READY=1
    printf '%s\n' "$INSTALLER_SEED_BASE_CACHE"
    return 0
  fi
  if [ -n "${INSTALLER_SEED_BASE:-}" ]; then
    INSTALLER_SEED_BASE_CACHE=$(installer_normalize_seed_base "${INSTALLER_SEED_BASE}" "$(installer_seed_source_type "${INSTALLER_SEED_BASE}")")
    INSTALLER_SEED_BASE_CACHE_READY=1
    printf '%s\n' "$INSTALLER_SEED_BASE_CACHE"
    return 0
  fi
  if installer_persisted_seed_base; then
    printf '%s\n' "$INSTALLER_RESOLVED_SEED_BASE"
    return 0
  fi
  installer_load_source_library "${INSTALLER_SOURCE_ROOT:-}" || return 1
  source_resolve_seed
  return $?

installer_fatal "installation preseed URL or file path not found in kernel cmdline, installer context, runtime state, or persisted installer state"
}

installer_seed_url_base() {
  installer_seed_base "${1:-}"
}

installer_current_seed_base() {
  installer_seed_base ""
}

installer_validate_relative_seed_path() {
  seed_relative_path=$1

  case "$seed_relative_path" in
    ''|/*|../*|*/..|*../*|*//*)
      installer_fatal "seed source path must stay relative to the seed base: ${seed_relative_path:-unset}"
      ;;
  esac
}

installer_file_safe_token() {
  printf '%s\n' "$(printf '%s' "${1:-seed}" | sed 's/[^A-Za-z0-9._-]/_/g')"
}

installer_repo_env_relpath() {
  printf '%s\n' repo.env
}

installer_repo_env_path() {
  printf '%s/bootstrap/repo.env\n' "${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}"
}

installer_repo_env_dir_vars() {
  installer_repo_env_vars_path=$1
  sed -n 's/^\(DIR_[A-Z0-9_]*\)=.*/\1/p' "$installer_repo_env_vars_path"
}

installer_validate_repo_dir_value() {
  installer_repo_validate_var=$1
  installer_repo_validate_value=$2

  case "$installer_repo_validate_value" in
    ''|/*|../*|*/..|*../*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/-]*)
      installer_fatal "${installer_repo_validate_var} must be a safe repository-relative directory path: ${installer_repo_validate_value:-unset}"
      ;;
  esac
}

installer_repo_dir_input_is_var() {
  case "${1:-}" in
    DIR_[ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_]*)
      case "$1" in
        *[!ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_]*) return 1 ;;
      esac
      return 0
      ;;
  esac
  return 1
}

installer_loaded_repo_dir_value() {
  case "${1:-}" in
    DIR_HOSTS_PROFILES) printf '%s\n' "${DIR_HOSTS_PROFILES:-}" ;;
    DIR_HOSTS_INSTALLER) printf '%s\n' "${DIR_HOSTS_INSTALLER:-}" ;;
    DIR_HOOKS_INSTALLER) printf '%s\n' "${DIR_HOOKS_INSTALLER:-}" ;;
    DIR_HOOKS_TARGET) printf '%s\n' "${DIR_HOOKS_TARGET:-}" ;;
    DIR_HOOKS_INSTALLER_APT_SETUP_GENERATORS) printf '%s\n' "${DIR_HOOKS_INSTALLER_APT_SETUP_GENERATORS:-}" ;;
    DIR_HOOKS_INSTALLER_BASE_STAGE_D) printf '%s\n' "${DIR_HOOKS_INSTALLER_BASE_STAGE_D:-}" ;;
    DIR_HOOKS_INSTALLER_D_I) printf '%s\n' "${DIR_HOOKS_INSTALLER_D_I:-}" ;;
    DIR_HOOKS_INSTALLER_FINISH_INSTALL_D) printf '%s\n' "${DIR_HOOKS_INSTALLER_FINISH_INSTALL_D:-}" ;;
    DIR_HOOKS_INSTALLER_PARTMAN) printf '%s\n' "${DIR_HOOKS_INSTALLER_PARTMAN:-}" ;;
    DIR_HOOKS_INSTALLER_PARTMAN_FINISH_D) printf '%s\n' "${DIR_HOOKS_INSTALLER_PARTMAN_FINISH_D:-}" ;;
    DIR_HOOKS_INSTALLER_PRE_PKGSEL_D) printf '%s\n' "${DIR_HOOKS_INSTALLER_PRE_PKGSEL_D:-}" ;;
    DIR_SCRIPTS_COMMON) printf '%s\n' "${DIR_SCRIPTS_COMMON:-}" ;;
    DIR_SCRIPTS_EARLY) printf '%s\n' "${DIR_SCRIPTS_EARLY:-}" ;;
    DIR_SCRIPTS_FIRSTBOOT) printf '%s\n' "${DIR_SCRIPTS_FIRSTBOOT:-}" ;;
    DIR_SCRIPTS_LATE) printf '%s\n' "${DIR_SCRIPTS_LATE:-}" ;;
    DIR_SCRIPTS_PARTMAN) printf '%s\n' "${DIR_SCRIPTS_PARTMAN:-}" ;;
    DIR_SCRIPTS_PRESEED) printf '%s\n' "${DIR_SCRIPTS_PRESEED:-}" ;;
    DIR_SCRIPTS_RUNTIME) printf '%s\n' "${DIR_SCRIPTS_RUNTIME:-}" ;;
    DIR_SCRIPTS_DESKTOP) printf '%s\n' "${DIR_SCRIPTS_DESKTOP:-}" ;;
    *) return 1 ;;
  esac
}

installer_validate_repo_env() {
  installer_repo_validate_env_path=${1:-$(installer_repo_env_path)}

  [ -r "$installer_repo_validate_env_path" ] || installer_fatal "repository path environment is not readable: $installer_repo_validate_env_path"
  while IFS= read -r installer_repo_validate_dir_var || [ -n "$installer_repo_validate_dir_var" ]; do
    [ -n "$installer_repo_validate_dir_var" ] || continue
    installer_repo_validate_dir_value=$(installer_loaded_repo_dir_value "$installer_repo_validate_dir_var" 2>/dev/null || true)
    installer_validate_repo_dir_value "$installer_repo_validate_dir_var" "$installer_repo_validate_dir_value"
  done <<EOF
$(installer_repo_env_dir_vars "$installer_repo_validate_env_path")
EOF
}

installer_ensure_repo_env() {
  installer_repo_env_seed_base=${1:-}

  if [ "${INSTALLER_REPO_ENV_READY:-0}" -eq 1 ]; then
    return 0
  fi

  installer_repo_env_file=$(installer_repo_env_path)
  if [ -n "${INSTALLER_SOURCE_ROOT:-}" ]; then
    installer_repo_env_source="${INSTALLER_SOURCE_ROOT%/}/$(installer_repo_env_relpath)"
    [ -r "$installer_repo_env_source" ] || installer_fatal "repository path environment is not readable: ${installer_repo_env_source}"
    installer_repo_env_file=$installer_repo_env_source
  else
    [ -n "$installer_repo_env_seed_base" ] || installer_repo_env_seed_base=$(installer_current_seed_base)
    if [ ! -s "$installer_repo_env_file" ]; then
      installer_fetch_seed_path "$installer_repo_env_seed_base" "$(installer_repo_env_relpath)" "$installer_repo_env_file" 0600
    fi
  fi
  # shellcheck disable=SC1090
  . "$installer_repo_env_file"
  installer_validate_repo_env "$installer_repo_env_file"
  INSTALLER_REPO_ENV_READY=1
}

installer_repo_dir_value() {
  installer_repo_dir_name=$1
  installer_repo_dir_value=
  installer_repo_dir_path=

  if ! installer_repo_dir_input_is_var "$installer_repo_dir_name"; then
    installer_repo_dir_path=$installer_repo_dir_name
    installer_validate_repo_dir_value repository_path "$installer_repo_dir_path"
    printf '%s\n' "$installer_repo_dir_path"
    return 0
  fi

  if [ "${INSTALLER_REPO_ENV_READY:-0}" -ne 1 ]; then
    installer_ensure_repo_env ""
  fi
  installer_repo_dir_value=$(installer_loaded_repo_dir_value "$installer_repo_dir_name" 2>/dev/null || true)
  [ -n "$installer_repo_dir_value" ] || installer_fatal "repository directory variable is unset: $installer_repo_dir_name"
  installer_validate_repo_dir_value "$installer_repo_dir_name" "$installer_repo_dir_value"
  printf '%s\n' "$installer_repo_dir_value"
}

installer_repo_join_var() {
  installer_repo_join_dir=$1
  installer_repo_join_leaf=${2:-}
  installer_repo_join_base=$(installer_repo_dir_value "$installer_repo_join_dir")

  # Systemd template-unit paths legitimately contain "@", for example
  # etc/systemd/system/user@.service.d/50-oom-score.conf.
  case "$installer_repo_join_leaf" in
    '') printf '%s\n' "$installer_repo_join_base" ;;
    /*|../*|*/..|*../*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/@-]*)
      installer_fatal "unsafe repository path suffix for ${installer_repo_join_dir}: ${installer_repo_join_leaf:-unset}"
      ;;
    *) printf '%s/%s\n' "$installer_repo_join_base" "$installer_repo_join_leaf" ;;
  esac
}

# Legacy hierarchy mapper removed; all callers use physical repository paths.

# Legacy hierarchy mapper removed; all callers use physical repository paths.

installer_repo_resolve_path() {
  installer_validate_relative_seed_path "$1"
  printf '%s\n' "$1"
}

installer_validate_apt_preference_token() {
  pref_token=$1
  pref_label=${2:-apt preferences}

  case "$pref_token" in
    *.pref) pref_name=$pref_token ;;
    *) pref_name="${pref_token}.pref" ;;
  esac
  case "$pref_name" in
    ''|.*|*/*|*..*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._+-]*|*.tmp|*.bak|*.save|*.distUpgrade)
      installer_fatal "unsafe apt preference name in ${pref_label}: ${pref_token:-unset}"
      ;;
    *.pref) ;;
    *)
      installer_fatal "apt preference name in ${pref_label} must resolve to a .pref file: ${pref_token:-unset}"
      ;;
  esac
  [ "${#pref_name}" -le 128 ] || installer_fatal "apt preference name in ${pref_label} is too long: $pref_name"
  printf '%s\n' "$pref_name"
}

installer_emit_apt_preference_names() {
  pref_config=$1
  pref_label=${2:-apt preferences}
  pref_line_breaks=$(printf '%s' "$pref_config" | wc -l | tr -d '[:space:]')
  case "$pref_line_breaks" in
    0) ;;
    ''|*[!0-9]*)
      installer_fatal "unable to validate ${pref_label} line count"
      ;;
    *)
      installer_fatal "${pref_label} must be a single comma- or space-separated line"
      ;;
  esac
  pref_seen=' '

  while IFS= read -r pref_token || [ -n "$pref_token" ]; do
    [ -n "$pref_token" ] || continue
    pref_name=$(installer_validate_apt_preference_token "$pref_token" "$pref_label")
    case "$pref_seen" in
      *" $pref_name "*) continue ;;
    esac
    pref_seen="${pref_seen}${pref_name} "
    printf '%s\n' "$pref_name"
  done <<EOF
$(printf '%s' "$pref_config" | tr ',	 ' '\n\n\n')
EOF
}

installer_normalize_apt_preferences_config() {
  pref_config=$1
  pref_label=${2:-apt preferences}
  pref_normalized=

  while IFS= read -r pref_name || [ -n "$pref_name" ]; do
    [ -n "$pref_name" ] || continue
    pref_token=${pref_name%.pref}
    pref_normalized="${pref_normalized:+$pref_normalized,}$pref_token"
  done <<EOF
$(installer_emit_apt_preference_names "$pref_config" "$pref_label")
EOF
  printf '%s\n' "$pref_normalized"
}

installer_selected_apt_preferences_config() {
  pref_override=
  pref_seen=' '
  while IFS= read -r class_ref || [ -n "$class_ref" ]; do
    [ -n "$class_ref" ] || continue
    installer_class_token_parts "$class_ref" >/dev/null
    group_name=${INSTALLER_CLASS_TOKEN_GROUP:-}
    class_name=$INSTALLER_CLASS_TOKEN_NAME
    [ -n "$group_name" ] || continue
    if [ "$group_name" = addon ]; then
      case "$class_name" in
        nvidia|cuda|nvidia-legacy|cuda-legacy)
          installer_nvidia_gpu_detected || continue
          ;;
      esac
    fi
    pref_value=$(installer_class_meta_value "" "$group_name" "$class_name" debian_apt_preferences)
    [ -n "$pref_value" ] || continue
    pref_label="class ${group_name}/${class_name} debian_apt_preferences"
    while IFS= read -r pref_name || [ -n "$pref_name" ]; do
      [ -n "$pref_name" ] || continue
      case "$pref_seen" in
        *" $pref_name "*) continue ;;
      esac
      pref_seen="${pref_seen}${pref_name} "
      pref_token=${pref_name%.pref}
      pref_override="${pref_override:+$pref_override,}$pref_token"
    done <<EOF
$(installer_emit_apt_preference_names "$pref_value" "$pref_label")
EOF
  done <<EOF
$(installer_selected_class_refs 2>/dev/null || true)
EOF

  [ -n "$pref_override" ] || return 1
  printf '%s\n' "$pref_override"
}

installer_apt_preferences_config() {
  installer_ensure_repo_env ""
  installer_load_context_if_present || true
  pref_base=$(installer_normalize_apt_preferences_config "${DEBIAN_APT_PREFERENCES:-}" DEBIAN_APT_PREFERENCES)

  if pref_override=$(installer_selected_apt_preferences_config 2>/dev/null); then
    if [ -n "$pref_base" ]; then
      printf '%s\n' "$(installer_normalize_apt_preferences_config "${pref_base},${pref_override}" "merged apt preferences")"
    else
      printf '%s\n' "$pref_override"
    fi
    return 0
  fi

  printf '%s\n' "$pref_base"
}

installer_configured_apt_preferences() {
  installer_emit_apt_preference_names "$(installer_apt_preferences_config)" "effective apt preferences"
}

installer_target_apt_preferences_source_variant() {
  printf '%s\n' default
}

installer_target_apt_preference_source_path() {
  pref_name=$1
  pref_variant=$(installer_target_apt_preferences_source_variant)
  printf '%s\n' "$(installer_repo_join_var DIR_HOOKS_TARGET "etc/apt/preferences.d/${pref_variant}/${pref_name}")"
}

installer_seed_cache_key() (
  installer_load_source_library "$1" || exit 1
  normalized=$(source_normalize_base "$1") || exit 1
  key=$(printf '%s' "$normalized" | source_hash) || exit 1
  printf '%s\n' "${key%% *}"
)

installer_seed_cache_path() (
  installer_load_source_library "$1" || exit 1
  source_validate_relative "$2" || exit 1
  printf '%s/%s\n' "$(source_cache_root "$1")" "$2"
)

# External vendor data; never resolve repository code from the vendor URL.
installer_fetch_url() (
  installer_load_source_library "${INSTALLER_SOURCE_ROOT:-}" || exit 1
  source_fetch_external "$1" "$2" "$3" "${4:-0600}"
)

installer_copy_seed_file() (
  installer_load_source_library "$1" || exit 1
  source_fetch "$1" "$2" "$3" "${4:-0600}"
)

installer_fetch_seed_path() (
  installer_load_source_library "$1" || exit 1
  source_fetch "$1" "$2" "$3" "${4:-0600}"
)

installer_fetch_file() {
  fetch_file_seed_base=$1
  fetch_file_source_path=$2
  fetch_file_dest_path=$3
  fetch_file_mode=${4:-0600}

  installer_fetch_seed_path "$fetch_file_seed_base" "$fetch_file_source_path" "$fetch_file_dest_path" "$fetch_file_mode" || installer_fatal "failed to fetch $fetch_file_source_path"
}

installer_profile_shared_family() {
  profile_name=$1

  if [ -n "${INSTALLER_HOST_PROFILE:-}" ] && [ "$profile_name" = "${INSTALLER_HOST_PROFILE}" ] && [ -n "${INSTALLER_HOST_FAMILY:-}" ]; then
    printf '%s\n' "${INSTALLER_HOST_FAMILY}"
    return 0
  fi

  case "$profile_name" in
    *-*) printf '%s\n' "${profile_name%%-*}" ;;
    *) return 1 ;;
  esac
}

installer_profile_shared_families() {
  profile_name=$1
  installer_profile_shared_family "$profile_name"
}

installer_profile_variant() {
  profile_name=$1

  case "$profile_name" in
    *-*) printf '%s\n' "${profile_name#*-}" ;;
    *) return 1 ;;
  esac
}

installer_validate_profile_component() {
  component_label=$1
  component_value=$2

  case "$component_value" in
    ''|*[!A-Za-z0-9_-]*)
      installer_fatal "${component_label} contains an invalid profile path component: ${component_value:-unset}"
      ;;
  esac
}

installer_profile_layout_family() {
  profile_name=$1
  profile_family=${2:-}

  if [ -z "$profile_family" ]; then
    profile_family=$(installer_profile_shared_family "$profile_name" 2>/dev/null || true)
  fi

  if [ -n "${INSTALLER_HOST_PROFILE:-}" ] &&
    [ "$profile_name" = "${INSTALLER_HOST_PROFILE}" ] &&
    [ -n "${INSTALLER_HOOK_FAMILY:-}" ]; then
    profile_family=$INSTALLER_HOOK_FAMILY
  fi

  case "$profile_family" in
    btrfs|vm) printf 'btrfs\n' ;;
    f2fs) printf 'f2fs\n' ;;
    *) return 1 ;;
  esac
}

installer_profile_override_metadata() {
  override_seed_base=$1
  override_profile_name=$2
  INSTALLER_PROFILE_OVERRIDE_ENV_DIR=
  INSTALLER_PROFILE_OVERRIDE_ENV_NAME=
  INSTALLER_PROFILE_OVERRIDE_VARIANT=
  INSTALLER_PROFILE_OVERRIDE_HOST_FAMILY=

  case "$override_profile_name" in
    override-*)
      override_class_name=${override_profile_name#override-}
      ;;
    *)
      return 1
      ;;
  esac

  [ -n "$override_class_name" ] || installer_fatal "profile override name is empty: ${override_profile_name:-unset}"

  profile_group=$(installer_group_for_purpose host-profile-override 2>/dev/null || true)
  [ -n "$profile_group" ] || installer_fatal "profile override group is unavailable while resolving ${override_profile_name}"
  installer_class_has_manifest_record "$profile_group" "$override_class_name" ||
    installer_fatal "profile override ${override_profile_name} is missing from classes/configs/profile.cfg"

  override_env_dir=$(installer_class_meta_value "$override_seed_base" "$profile_group" "$override_class_name" host_profile_prefix)
  override_host_family=$(installer_class_meta_value "$override_seed_base" "$profile_group" "$override_class_name" host_family)
  override_required_classes=$(installer_class_meta_value "$override_seed_base" "$profile_group" "$override_class_name" requires_classes)
  override_variant=
  override_role_group=

  for required_class in $override_required_classes; do
    installer_class_token_parts "$required_class" >/dev/null
    case "${INSTALLER_CLASS_TOKEN_GROUP:-}" in
      role)
        override_role_group=${INSTALLER_CLASS_TOKEN_GROUP}
        override_variant=${INSTALLER_CLASS_TOKEN_NAME}
        break
        ;;
    esac
  done

  [ -n "$override_env_dir" ] || installer_fatal "profile override ${override_profile_name} must define HostProfilePrefix in classes/configs/profile.cfg"
  [ -n "$override_host_family" ] || installer_fatal "profile override ${override_profile_name} must define HostFamily in classes/configs/profile.cfg"
  [ -n "$override_variant" ] || installer_fatal "profile override ${override_profile_name} must require a role/<name> class"

  override_role_variant=$(installer_class_meta_value "$override_seed_base" "${override_role_group:-role}" "$override_variant" host_variant)
  [ -n "$override_role_variant" ] || override_role_variant=$override_variant

  INSTALLER_PROFILE_OVERRIDE_ENV_DIR=$override_env_dir
  INSTALLER_PROFILE_OVERRIDE_ENV_NAME=$override_class_name
  INSTALLER_PROFILE_OVERRIDE_VARIANT=$override_role_variant
  INSTALLER_PROFILE_OVERRIDE_HOST_FAMILY=$override_host_family
}

installer_fetch_composite_env_paths() {
  composite_seed_base=$1
  composite_dest_path=$2
  composite_mode=$3
  shift 3
  composite_fetched_any=false
  composite_fetched_paths=

  install -d -m 0700 "$(dirname "$composite_dest_path")"
  : >"$composite_dest_path"
  for composite_candidate in "$@"; do
    [ -n "$composite_candidate" ] || continue
    composite_part_dest="${composite_dest_path}.part.$$"
    if ! installer_fetch_seed_path "$composite_seed_base" "$composite_candidate" "$composite_part_dest" "$composite_mode"; then
      rm -f "$composite_part_dest"
      installer_fatal "failed to fetch required host env ${composite_candidate} into ${composite_dest_path}"
    fi
    cat "$composite_part_dest" >>"$composite_dest_path"
    printf '\n' >>"$composite_dest_path"
    rm -f "$composite_part_dest"
    composite_fetched_any=true
    composite_fetched_paths="${composite_fetched_paths:+$composite_fetched_paths }$composite_candidate"
  done

  [ "$composite_fetched_any" = true ] || installer_fatal "failed to fetch host env into $composite_dest_path"
  chmod "$composite_mode" "$composite_dest_path"
  installer_info "fetched host env ${composite_dest_path} from:${composite_fetched_paths:+ ${composite_fetched_paths}}"
}

installer_fetch_host_env() {
  host_seed_base=$1
  host_profile=$2
  host_dest_path=$3
  host_mode=${4:-0600}
  host_profile_env_dir=
  host_profile_env_name=

  if [ -n "${INSTALLER_HOST_PROFILE:-}" ] &&
     [ "$host_profile" = "${INSTALLER_HOST_PROFILE}" ] &&
     [ -n "${INSTALLER_HOST_PROFILE_ENV_DIR:-}" ] &&
     [ -n "${INSTALLER_HOST_PROFILE_ENV_NAME:-}" ]; then
    host_family=${INSTALLER_HOST_FAMILY:-}
    host_variant=${INSTALLER_HOST_VARIANT:-}
    host_profile_env_dir=${INSTALLER_HOST_PROFILE_ENV_DIR}
    host_profile_env_name=${INSTALLER_HOST_PROFILE_ENV_NAME}
  else
    case "$host_profile" in
      override-*)
        installer_profile_override_metadata "$host_seed_base" "$host_profile"
        host_family=${INSTALLER_PROFILE_OVERRIDE_HOST_FAMILY}
        host_variant=${INSTALLER_PROFILE_OVERRIDE_VARIANT}
        host_profile_env_dir=${INSTALLER_PROFILE_OVERRIDE_ENV_DIR}
        host_profile_env_name=${INSTALLER_PROFILE_OVERRIDE_ENV_NAME}
        ;;
      *)
        host_family=$(installer_profile_shared_family "$host_profile" 2>/dev/null || true)
        host_variant=$(installer_profile_variant "$host_profile" 2>/dev/null || true)
        host_profile_env_dir=$host_family
        host_profile_env_name=$host_variant
        ;;
    esac
  fi

  [ -n "$host_family" ] || installer_fatal "unable to derive host family from profile: ${host_profile:-unset}"
  [ -n "$host_variant" ] || installer_fatal "unable to derive host variant from profile: ${host_profile:-unset}"
  [ -n "$host_profile_env_dir" ] || installer_fatal "unable to derive host profile env directory from profile: ${host_profile:-unset}"
  [ -n "$host_profile_env_name" ] || installer_fatal "unable to derive host profile env name from profile: ${host_profile:-unset}"
  installer_validate_profile_component "host family" "$host_family"
  installer_validate_profile_component "host variant" "$host_variant"
  installer_validate_profile_component "host profile env directory" "$host_profile_env_dir"
  installer_validate_profile_component "host profile env name" "$host_profile_env_name"

  host_layout_family=$(installer_profile_layout_family "$host_profile" "$host_family" 2>/dev/null || true)
  [ -n "$host_layout_family" ] || installer_fatal "unable to derive layout family from profile: ${host_profile:-unset}"
  installer_validate_profile_component "host layout family" "$host_layout_family"

  set -- \
    "$(installer_profile_env_path "$host_profile_env_dir" "$host_profile_env_name")" \
    "$(installer_repo_join_var DIR_HOSTS_INSTALLER identity.env)" \
    "$(installer_repo_join_var DIR_HOSTS_INSTALLER runtime.env)"

  case "$host_variant" in
    desktop)
      ;;
    server)
      installer_fatal "this repository installs desktop systems only"
      ;;
    *)
      installer_fatal "unsupported host profile variant: ${host_variant}"
      ;;
  esac

  set -- "$@" \
    "$(installer_repo_join_var DIR_HOSTS_INSTALLER layout.env)" \
    "$(installer_repo_join_var DIR_HOSTS_INSTALLER "layout-${host_layout_family}.env")" \
    "$(installer_repo_join_var DIR_HOSTS_INSTALLER boot.env)"

  installer_fetch_composite_env_paths \
    "$host_seed_base" \
    "$host_dest_path" \
    "$host_mode" \
    "$@"
}

installer_fetch_account_env() {
  account_seed_base=$1
  account_dest_path=$2
  account_mode=${3:-0600}

  installer_fetch_seed_path \
    "$account_seed_base" \
    "$(installer_repo_join_var DIR_HOSTS_INSTALLER account.env)" \
    "$account_dest_path" \
    "$account_mode" || installer_fatal "failed to fetch account env"
}

installer_classes_install_conf_relpath() {
  printf '%s\n' "classes/install.conf"
}

installer_classes_conf_cache_path() {
  printf '%s/cache/classes.state.conf\n' "${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}"
}

installer_classes_plan_path() {
  printf '%s/state/plan.tsv\n' "${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}"
}

installer_ensure_classes_conf_path() {
  if [ -n "${INSTALLER_CLASSES_CONF_PATH_CACHE:-}" ]; then
    return 0
  fi
  INSTALLER_CLASSES_CONF_PATH_CACHE=$(installer_classes_conf_cache_path)
}

installer_classes_conf_path() {
  installer_ensure_classes_conf_path
  printf '%s\n' "$INSTALLER_CLASSES_CONF_PATH_CACHE"
}

installer_class_metadata_read_path() {
  metadata_relpath=$1
  installer_validate_relative_seed_path "$metadata_relpath"

  if [ -n "${INSTALLER_SOURCE_ROOT:-}" ]; then
    metadata_path="${INSTALLER_SOURCE_ROOT%/}/${metadata_relpath}"
    [ -r "$metadata_path" ] || installer_fatal "installer class metadata is not readable: ${metadata_path}"
    printf '%s\n' "$metadata_path"
    return 0
  fi

  metadata_path="$(installer_runtime_cache_dir)/${metadata_relpath}"
  if [ ! -s "$metadata_path" ]; then
    seed_base=$(installer_seed_base "")
    install -d -m 0700 "$(dirname "$metadata_path")"
    installer_fetch_file "$seed_base" "$metadata_relpath" "$metadata_path" 0600
  fi
  printf '%s\n' "$metadata_path"
}

installer_class_config_relpaths() {
  install_conf_path=$1
  awk '
    function trim(value) {
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
      return value
    }
    /^[[:space:]]*($|#)/ { next }
    /^Config:[[:space:]]*/ {
      line=$0
      sub(/^[^:]+:[[:space:]]*/, "", line)
      line=trim(line)
      if (line != "") {
        print line
      }
    }
  ' "$install_conf_path"
}

installer_classes_cache_name_token() {
  printf '%s' "$1" | tr -c 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789' '_'
}

installer_classes_section_var_name() {
  printf 'INSTALLER_CLASSES_SECTION__%s\n' "$(installer_classes_cache_name_token "$1")"
}

installer_classes_value_var_name() {
  printf 'INSTALLER_CLASSES_VALUE__%s__%s\n' \
    "$(installer_classes_cache_name_token "$1")" \
    "$(installer_classes_cache_name_token "$2")"
}

installer_classes_cache_add_section() {
  section_name=$1
  INSTALLER_CLASSES_SECTION_NAMES="${INSTALLER_CLASSES_SECTION_NAMES:+$INSTALLER_CLASSES_SECTION_NAMES }$section_name"
  section_var=$(installer_classes_section_var_name "$section_name")
  eval "$section_var=1"
}

installer_classes_cache_set_value() {
  section_name=$1
  key_name=$2
  key_value=$3
  value_var=$(installer_classes_value_var_name "$section_name" "$key_name")
  eval "$value_var=$(installer_shell_quote "$key_value")"
}

installer_classes_cache_maybe_set_value() {
  section_name=$1
  key_name=$2
  key_value=${3:-}
  [ -n "$key_value" ] || return 0
  installer_classes_cache_set_value "$section_name" "$key_name" "$key_value"
}

installer_classes_plan_field_value() {
  case "${1:-}" in
    __EMPTY__) printf '%s\n' "" ;;
    *) printf '%s\n' "${1:-}" ;;
  esac
}

installer_generate_class_plan() {
  install_conf_relpath=$(installer_classes_install_conf_relpath)
  install_conf_path=$(installer_class_metadata_read_path "$install_conf_relpath")
  plan_path=$(installer_classes_plan_path)
  state_path=$(installer_classes_conf_cache_path)

  if [ -s "$plan_path" ] && [ -s "$state_path" ]; then
    return 0
  fi

  config_paths=
  while IFS= read -r config_relpath || [ -n "$config_relpath" ]; do
    [ -n "$config_relpath" ] || continue
    config_path=$(installer_class_metadata_read_path "$config_relpath")
    case "$config_paths" in
      '')
        config_paths=$config_path
        ;;
      *)
        config_paths="${config_paths}|${config_path}"
        ;;
    esac
  done <<EOF
$(installer_class_config_relpaths "$install_conf_path")
EOF
  [ -n "$config_paths" ] || installer_fatal "classes/install.conf must define at least one Config: entry"

  install -d -m 0700 "$(dirname "$plan_path")" "$(dirname "$state_path")"
  plan_tmp="${plan_path}.tmp.$$"
  state_tmp="${state_path}.tmp.$$"
  : >"$state_tmp"

  if awk -v install_conf_path="$install_conf_path" -v config_paths="$config_paths" -v state_path="$state_tmp" '
    BEGIN {
      OFS = "\t"
      parse_install_conf(install_conf_path)
      config_count = split(config_paths, config_path_list, /\|/)
      if (config_count < 1) {
        fail("classes/install.conf resolved no readable config sources")
      }
      for (config_index = 1; config_index <= config_count; config_index++) {
        if (config_path_list[config_index] == "") {
          continue
        }
        parse_config_file(config_path_list[config_index])
      }
      finalize_record()
      emit_state()
      emit_plan()
      close(state_path)
      exit 0
    }

    function fail(message) {
      print "fatal: " message > "/dev/stderr"
      exit 1
    }

    function trim(value) {
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
      return value
    }

    function normalize_word_list(value) {
      value = trim(value)
      gsub(/,/, " ", value)
      gsub(/[[:space:]]+/, " ", value)
      return value
    }

    function state_set(section_name, key_name, key_value) {
      if (key_value != "") {
        state_values[section_name, key_name] = key_value
      }
    }

    function parse_install_conf(path,   line, field_name, field_value) {
      install_conf_line = 0
      while ((getline line < path) > 0) {
        install_conf_line++
        sub(/\r$/, "", line)
        if (line ~ /^[[:space:]]*$/ || line ~ /^[[:space:]]*#/) {
          continue
        }
        separator_index = index(line, ":")
        if (separator_index == 0) {
          fail("malformed classes/install.conf line " install_conf_line ": expected Field: value")
        }
        field_name = trim(substr(line, 1, separator_index - 1))
        field_value = trim(substr(line, separator_index + 1))
        if (field_name == "ManifestVersion") {
          if (manifest_version_seen) {
            fail("duplicate ManifestVersion in classes/install.conf")
          }
          manifest_version = field_value
          manifest_version_seen = 1
          continue
        }
        if (field_name == "ClassTokenFormats") {
          if (class_token_formats_seen) {
            fail("duplicate ClassTokenFormats in classes/install.conf")
          }
          class_token_formats = normalize_word_list(field_value)
          class_token_formats_seen = 1
          continue
        }
        if (field_name == "Config") {
          continue
        }
        fail("unsupported field in classes/install.conf line " install_conf_line ": " field_name)
      }
      close(path)
    }

    function record_reset() {
      record_active = 0
      delete record_values
      delete record_seen
      current_config_path = ""
      current_config_line = 0
    }

    function config_field_key(field_name) {
      if (field_name == "Type" || field_name == "type") return "type"
      if (field_name == "Group" || field_name == "group") return "group"
      if (field_name == "Name" || field_name == "name") return "name"
      if (field_name == "Required" || field_name == "required") return "required"
      if (field_name == "Multi" || field_name == "multi") return "multi"
      if (field_name == "Order" || field_name == "order") return "order"
      if (field_name == "Purpose" || field_name == "purpose") return "purpose"
      if (field_name == "Source" || field_name == "source") return "source"
      if (field_name == "Description" || field_name == "description") return "description"
      if (field_name == "HostVariant" || field_name == "Host-Variant" || field_name == "host_variant") return "host_variant"
      if (field_name == "LateHelper" || field_name == "Late-Helper" || field_name == "late_helper") return "late_helper"
      if (field_name == "LateHelperOrder" || field_name == "Late-Helper-Order" || field_name == "late_helper_order") return "late_helper_order"
      if (field_name == "EarlyHelper" || field_name == "Early-Helper" || field_name == "early_helper") return "early_helper"
      if (field_name == "PartmanHelper" || field_name == "Partman-Helper" || field_name == "partman_helper") return "partman_helper"
      if (field_name == "HostProfilePrefix" || field_name == "Host-Profile-Prefix" || field_name == "host_profile_prefix") return "host_profile_prefix"
      if (field_name == "HostFamily" || field_name == "Host-Family" || field_name == "host_family") return "host_family"
      if (field_name == "HookFamily" || field_name == "Hook-Family" || field_name == "hook_family") return "hook_family"
      if (field_name == "InstallDiskCandidates" || field_name == "Install-Disk-Candidates" || field_name == "install_disk_candidates") return "install_disk_candidates"
      if (field_name == "DefaultInstallDisk" || field_name == "Default-Install-Disk" || field_name == "default_install_disk") return "default_install_disk"
      if (field_name == "AllowedHardwareClasses" || field_name == "Allowed-Hardware-Classes" || field_name == "allowed_hardware_classes") return "allowed_hardware_classes"
      if (field_name == "RejectedClasses" || field_name == "Rejected-Classes" || field_name == "rejected_classes") return "rejected_classes"
      if (field_name == "RequiresClasses" || field_name == "Requires-Classes" || field_name == "requires_classes") return "requires_classes"
      if (field_name == "DebianAptPreferences" || field_name == "Debian-Apt-Preferences" || field_name == "debian_apt_preferences") return "debian_apt_preferences"
      return ""
    }

    function normalize_field_value(field_key, field_value) {
      if (field_key == "allowed_hardware_classes" ||
          field_key == "debian_apt_preferences" ||
          field_key == "install_disk_candidates" ||
          field_key == "rejected_classes" ||
          field_key == "requires_classes") {
        return normalize_word_list(field_value)
      }
      return trim(field_value)
    }

    function record_assign_field(field_name, field_value,   field_key, normalized_value) {
      field_key = config_field_key(field_name)
      if (field_key == "") {
        fail("unsupported field in " current_config_path ":" current_config_line ": " field_name)
      }
      if (record_seen[field_key]) {
        fail("duplicate field in " current_config_path ":" current_config_line ": " field_name)
      }
      normalized_value = normalize_field_value(field_key, field_value)
      record_values[field_key] = normalized_value
      record_seen[field_key] = 1
      record_active = 1
    }

    function parse_config_file(path,   line, field_name, field_value) {
      current_config_path = path
      current_config_line = 0
      while ((getline line < path) > 0) {
        current_config_line++
        sub(/\r$/, "", line)
        if (line ~ /^[[:space:]]*$/) {
          finalize_record()
          continue
        }
        if (line ~ /^[[:space:]]*#/) {
          continue
        }
        separator_index = index(line, ":")
        if (separator_index == 0) {
          fail("malformed config line in " path ":" current_config_line ": expected Field: value")
        }
        field_name = trim(substr(line, 1, separator_index - 1))
        field_value = substr(line, separator_index + 1)
        record_assign_field(field_name, field_value)
      }
      close(path)
      finalize_record()
    }

    function finalize_record(   record_type, group_name, class_name, state_section, record_key, key_index) {
      if (!record_active) {
        return
      }
      record_type = tolower(record_values["type"])
      if (record_type == "group") {
        group_name = record_values["name"]
        if (group_name == "") {
          fail("group record in " current_config_path " is missing Name")
        }
        if (record_values["group"] != "") {
          fail("group record in " current_config_path " must not define Group: " record_values["group"])
        }
        if (group_seen[group_name]) {
          fail("duplicate group record in configs/groups.cfg: " group_name)
        }
        group_seen[group_name] = 1
        group_list[++group_count] = group_name
        state_section = "group." group_name
        state_set(state_section, "required", record_values["required"])
        state_set(state_section, "multi", record_values["multi"])
        state_set(state_section, "order", record_values["order"])
        state_set(state_section, "purpose", record_values["purpose"])
        state_set(state_section, "source", record_values["source"])
        state_set(state_section, "description", record_values["description"])
      } else if (record_type == "class") {
        group_name = record_values["group"]
        class_name = record_values["name"]
        if (group_name == "") {
          fail("class record in " current_config_path " is missing Group")
        }
        if (class_name == "") {
          fail("class record in " current_config_path " is missing Name")
        }
        record_key = group_name "/" class_name
        if (class_seen[record_key]) {
          fail("duplicate class record in configs/*.cfg: " record_key)
        }
        class_seen[record_key] = 1
        class_group_list[++class_count] = group_name
        class_name_list[class_count] = class_name
        state_section = "class." group_name "." class_name
        state_set(state_section, "description", record_values["description"])
        state_set(state_section, "host_variant", record_values["host_variant"])
        state_set(state_section, "late_helper", record_values["late_helper"])
        state_set(state_section, "late_helper_order", record_values["late_helper_order"])
        state_set(state_section, "early_helper", record_values["early_helper"])
        state_set(state_section, "partman_helper", record_values["partman_helper"])
        state_set(state_section, "host_profile_prefix", record_values["host_profile_prefix"])
        state_set(state_section, "host_family", record_values["host_family"])
        state_set(state_section, "hook_family", record_values["hook_family"])
        state_set(state_section, "install_disk_candidates", record_values["install_disk_candidates"])
        state_set(state_section, "default_install_disk", record_values["default_install_disk"])
        state_set(state_section, "allowed_hardware_classes", record_values["allowed_hardware_classes"])
        state_set(state_section, "rejected_classes", record_values["rejected_classes"])
        state_set(state_section, "requires_classes", record_values["requires_classes"])
        state_set(state_section, "debian_apt_preferences", record_values["debian_apt_preferences"])
      } else {
        fail("record in " current_config_path " must define Type: group or Type: class")
      }
      record_reset()
    }

    function emit_state_section(section_name, key_list,   key_count, key_names, key_index, key_name, key_value) {
      print "[" section_name "]" >> state_path
      key_count = split(key_list, key_names, / /)
      for (key_index = 1; key_index <= key_count; key_index++) {
        key_name = key_names[key_index]
        key_value = state_values[section_name, key_name]
        if (key_value == "") {
          continue
        }
        print key_name "=" key_value >> state_path
      }
      print "" >> state_path
    }

    function emit_state(   class_section, class_index) {
      if (manifest_version != "" || class_token_formats != "") {
        state_set("manifest", "version", manifest_version)
        state_set("manifest", "class_token_formats", class_token_formats)
        emit_state_section("manifest", "version class_token_formats")
      }
      for (group_index = 1; group_index <= group_count; group_index++) {
        emit_state_section("group." group_list[group_index], "required multi order purpose source description")
      }
      for (class_index = 1; class_index <= class_count; class_index++) {
        class_section = "class." class_group_list[class_index] "." class_name_list[class_index]
        emit_state_section(class_section, "description host_variant late_helper late_helper_order early_helper partman_helper host_profile_prefix host_family hook_family install_disk_candidates default_install_disk allowed_hardware_classes rejected_classes requires_classes debian_apt_preferences")
      }
    }

    function emit_plan(   class_section, class_index, group_section) {
      if (manifest_version != "") {
        print "manifest", "version", manifest_version
      }
      if (class_token_formats != "") {
        print "manifest", "class_token_formats", class_token_formats
      }
      for (group_index = 1; group_index <= group_count; group_index++) {
        group_section = "group." group_list[group_index]
        print "group", group_list[group_index], \
          plan_cell(state_values[group_section, "required"]), \
          plan_cell(state_values[group_section, "multi"]), \
          plan_cell(state_values[group_section, "order"]), \
          plan_cell(state_values[group_section, "purpose"]), \
          plan_cell(state_values[group_section, "source"]), \
          plan_cell(state_values[group_section, "description"])
      }
      for (class_index = 1; class_index <= class_count; class_index++) {
        class_section = "class." class_group_list[class_index] "." class_name_list[class_index]
        print "class", class_group_list[class_index], class_name_list[class_index], \
          plan_cell(state_values[class_section, "description"]), \
          plan_cell(state_values[class_section, "host_variant"]), \
          plan_cell(state_values[class_section, "late_helper"]), \
          plan_cell(state_values[class_section, "late_helper_order"]), \
          plan_cell(state_values[class_section, "early_helper"]), \
          plan_cell(state_values[class_section, "partman_helper"]), \
          plan_cell(state_values[class_section, "host_profile_prefix"]), \
          plan_cell(state_values[class_section, "host_family"]), \
          plan_cell(state_values[class_section, "hook_family"]), \
          plan_cell(state_values[class_section, "install_disk_candidates"]), \
          plan_cell(state_values[class_section, "default_install_disk"]), \
          plan_cell(state_values[class_section, "allowed_hardware_classes"]), \
          plan_cell(state_values[class_section, "rejected_classes"]), \
          plan_cell(state_values[class_section, "requires_classes"]), \
          plan_cell(state_values[class_section, "debian_apt_preferences"])
      }
    }

    function plan_cell(value) {
      return value == "" ? "__EMPTY__" : value
    }
  ' >"$plan_tmp"; then
    :
  else
    plan_status=$?
    rm -f "$plan_tmp" "$state_tmp"
    return "$plan_status"
  fi

  mv "$plan_tmp" "$plan_path"
  mv "$state_tmp" "$state_path"
  chmod 0600 "$plan_path" "$state_path" 2>/dev/null || true
}

installer_classes_cache_ensure() {
  if [ "${INSTALLER_CLASSES_CACHE_READY:-0}" -eq 1 ]; then
    return 0
  fi

  installer_ensure_classes_conf_path
  installer_generate_class_plan
  conf_path=$INSTALLER_CLASSES_CONF_PATH_CACHE
  plan_path=$(installer_classes_plan_path)
  tab_char=$(printf '\t')
  INSTALLER_CLASSES_SECTION_NAMES=
  INSTALLER_CLASSES_GROUP_NAMES_TEXT=
  INSTALLER_CLASSES_CLASS_RECORDS_TEXT=
  while IFS="$tab_char" read -r plan_kind plan_a plan_b plan_c plan_d plan_e plan_f plan_g plan_h plan_i plan_j plan_k plan_l plan_m plan_n plan_o plan_p plan_q || [ -n "${plan_kind:-}" ]; do
    [ -n "${plan_kind:-}" ] || continue
    case "$plan_kind" in
      manifest)
        installer_classes_cache_add_section manifest
        installer_classes_cache_maybe_set_value manifest "$plan_a" "$plan_b"
        ;;
      group)
        group_name=$plan_a
        [ -n "$group_name" ] || continue
        section_name="group.${group_name}"
        installer_classes_cache_add_section "$section_name"
        INSTALLER_CLASSES_GROUP_NAMES_TEXT="${INSTALLER_CLASSES_GROUP_NAMES_TEXT:+$INSTALLER_CLASSES_GROUP_NAMES_TEXT }${group_name}"
        installer_classes_cache_maybe_set_value "$section_name" required "$(installer_classes_plan_field_value "$plan_b")"
        installer_classes_cache_maybe_set_value "$section_name" multi "$(installer_classes_plan_field_value "$plan_c")"
        installer_classes_cache_maybe_set_value "$section_name" order "$(installer_classes_plan_field_value "$plan_d")"
        installer_classes_cache_maybe_set_value "$section_name" purpose "$(installer_classes_plan_field_value "$plan_e")"
        installer_classes_cache_maybe_set_value "$section_name" source "$(installer_classes_plan_field_value "$plan_f")"
        installer_classes_cache_maybe_set_value "$section_name" description "$(installer_classes_plan_field_value "$plan_g")"
        ;;
      class)
        group_name=$plan_a
        class_name=$plan_b
        [ -n "$group_name" ] || continue
        [ -n "$class_name" ] || continue
        section_name="class.${group_name}.${class_name}"
        installer_classes_cache_add_section "$section_name"
        INSTALLER_CLASSES_CLASS_RECORDS_TEXT="${INSTALLER_CLASSES_CLASS_RECORDS_TEXT:+$INSTALLER_CLASSES_CLASS_RECORDS_TEXT }${group_name}.${class_name}"
        installer_classes_cache_maybe_set_value "$section_name" description "$(installer_classes_plan_field_value "$plan_c")"
        installer_classes_cache_maybe_set_value "$section_name" host_variant "$(installer_classes_plan_field_value "$plan_d")"
        installer_classes_cache_maybe_set_value "$section_name" late_helper "$(installer_classes_plan_field_value "$plan_e")"
        installer_classes_cache_maybe_set_value "$section_name" late_helper_order "$(installer_classes_plan_field_value "$plan_f")"
        installer_classes_cache_maybe_set_value "$section_name" early_helper "$(installer_classes_plan_field_value "$plan_g")"
        installer_classes_cache_maybe_set_value "$section_name" partman_helper "$(installer_classes_plan_field_value "$plan_h")"
        installer_classes_cache_maybe_set_value "$section_name" host_profile_prefix "$(installer_classes_plan_field_value "$plan_i")"
        installer_classes_cache_maybe_set_value "$section_name" host_family "$(installer_classes_plan_field_value "$plan_j")"
        installer_classes_cache_maybe_set_value "$section_name" hook_family "$(installer_classes_plan_field_value "$plan_k")"
        installer_classes_cache_maybe_set_value "$section_name" install_disk_candidates "$(installer_classes_plan_field_value "$plan_l")"
        installer_classes_cache_maybe_set_value "$section_name" default_install_disk "$(installer_classes_plan_field_value "$plan_m")"
        installer_classes_cache_maybe_set_value "$section_name" allowed_hardware_classes "$(installer_classes_plan_field_value "$plan_n")"
        installer_classes_cache_maybe_set_value "$section_name" rejected_classes "$(installer_classes_plan_field_value "$plan_o")"
        installer_classes_cache_maybe_set_value "$section_name" requires_classes "$(installer_classes_plan_field_value "$plan_p")"
        installer_classes_cache_maybe_set_value "$section_name" debian_apt_preferences "$(installer_classes_plan_field_value "$plan_q")"
        ;;
    esac
  done <"$plan_path"

  INSTALLER_CLASSES_CACHE_READY=1
}

installer_ini_get_generic() {
  ini_file=$1
  ini_section=$2
  ini_key=$3
  ini_cr=$(printf '\r')

  installer_in_section=false
  while IFS= read -r ini_line || [ -n "$ini_line" ]; do
    case "$ini_line" in
      *"$ini_cr") ini_line=${ini_line%"$ini_cr"} ;;
    esac
    case "$ini_line" in
      ''|'#'*|';'*) continue ;;
      \[*\])
        ini_section_name=${ini_line#\[}
        ini_section_name=${ini_section_name%\]}
        if [ "$ini_section_name" = "$ini_section" ]; then
          installer_in_section=true
        else
          installer_in_section=false
        fi
        continue
        ;;
    esac
    [ "$installer_in_section" = true ] || continue
    case "$ini_line" in
      *=*)
        current_key=${ini_line%%=*}
        [ "$current_key" = "$ini_key" ] || continue
        printf '%s\n' "${ini_line#*=}"
        return 0
        ;;
      esac
  done <"$ini_file"
}

installer_ini_get() {
  ini_file=$1
  ini_section=$2
  ini_key=$3
  installer_ensure_classes_conf_path
  conf_path=$INSTALLER_CLASSES_CONF_PATH_CACHE

  if [ "$ini_file" = "$conf_path" ]; then
    installer_classes_cache_ensure
    value_var=$(installer_classes_value_var_name "$ini_section" "$ini_key")
    value_is_set=
    eval "value_is_set=\${$value_var+x}"
    [ "$value_is_set" = x ] || return 1
    eval "printf '%s\n' \"\${$value_var}\""
    return 0
  fi

  installer_ini_get_generic "$ini_file" "$ini_section" "$ini_key"
}

installer_ini_has_section_generic() {
  ini_file=$1
  ini_section=$2
  ini_cr=$(printf '\r')

  while IFS= read -r ini_line || [ -n "$ini_line" ]; do
    case "$ini_line" in
      *"$ini_cr") ini_line=${ini_line%"$ini_cr"} ;;
    esac
    case "$ini_line" in
      ''|'#'*|';'*) continue ;;
      \[*\])
        ini_section_name=${ini_line#\[}
        ini_section_name=${ini_section_name%\]}
        [ "$ini_section_name" = "$ini_section" ] && return 0
        ;;
    esac
  done <"$ini_file"
  return 1
}

installer_ini_has_section() {
  ini_file=$1
  ini_section=$2
  installer_ensure_classes_conf_path
  conf_path=$INSTALLER_CLASSES_CONF_PATH_CACHE

  if [ "$ini_file" = "$conf_path" ]; then
    installer_classes_cache_ensure
    section_var=$(installer_classes_section_var_name "$ini_section")
    section_is_set=
    eval "section_is_set=\${$section_var+x}"
    [ "$section_is_set" = x ]
    return $?
  fi

  installer_ini_has_section_generic "$ini_file" "$ini_section"
}

installer_ini_sections_with_prefix_generic() {
  ini_file=$1
  section_prefix=$2
  ini_cr=$(printf '\r')

  while IFS= read -r ini_line || [ -n "$ini_line" ]; do
    case "$ini_line" in
      *"$ini_cr") ini_line=${ini_line%"$ini_cr"} ;;
    esac
    case "$ini_line" in
      ''|'#'*|';'*) continue ;;
      \[*\])
        ini_section_name=${ini_line#\[}
        ini_section_name=${ini_section_name%\]}
        case "$ini_section_name" in
          "${section_prefix}"*)
            printf '%s\n' "${ini_section_name#"$section_prefix"}"
            ;;
        esac
        ;;
    esac
  done <"$ini_file"
}

installer_ini_sections_with_prefix() {
  ini_file=$1
  section_prefix=$2
  installer_ensure_classes_conf_path
  conf_path=$INSTALLER_CLASSES_CONF_PATH_CACHE

  if [ "$ini_file" = "$conf_path" ]; then
    installer_classes_cache_ensure
    case "$section_prefix" in
      group.)
        for ini_section_name in $INSTALLER_CLASSES_GROUP_NAMES_TEXT; do
          printf '%s\n' "$ini_section_name"
        done
        return 0
        ;;
      class.)
        for ini_section_name in $INSTALLER_CLASSES_CLASS_RECORDS_TEXT; do
          printf '%s\n' "$ini_section_name"
        done
        return 0
        ;;
    esac
    for ini_section_name in $INSTALLER_CLASSES_SECTION_NAMES; do
      case "$ini_section_name" in
        "${section_prefix}"*)
          printf '%s\n' "${ini_section_name#"$section_prefix"}"
          ;;
      esac
    done
    return 0
  fi

  installer_ini_sections_with_prefix_generic "$ini_file" "$section_prefix"
}

installer_group_required_status() {
  group_name=$1
  installer_ensure_classes_conf_path
  conf_path=$INSTALLER_CLASSES_CONF_PATH_CACHE
  required_value=$(installer_ini_get "$conf_path" "group.${group_name}" required 2>/dev/null || true)
  case "$required_value" in
    1|true|TRUE|yes|YES|on|ON|required) printf '%s\n' required ;;
    *) printf '%s\n' optional ;;
  esac
}

installer_group_order() {
  group_name=$1
  installer_ensure_classes_conf_path
  conf_path=$INSTALLER_CLASSES_CONF_PATH_CACHE
  order=$(installer_ini_get "$conf_path" "group.${group_name}" order 2>/dev/null || true)
  case "$order" in
    ''|*[!0-9]*) printf '%s\n' 1000 ;;
    *) printf '%s\n' "$order" ;;
  esac
}

installer_group_purpose() {
  group_name=$1
  installer_ensure_classes_conf_path
  conf_path=$INSTALLER_CLASSES_CONF_PATH_CACHE
  installer_ini_get "$conf_path" "group.${group_name}" purpose 2>/dev/null || true
}

installer_group_source() {
  group_name=$1
  installer_ensure_classes_conf_path
  conf_path=$INSTALLER_CLASSES_CONF_PATH_CACHE
  source_value=$(installer_ini_get "$conf_path" "group.${group_name}" source 2>/dev/null || true)
  case "$source_value" in
    class-auto|class-select|class-profile|class-addon|class-apps) printf '%s\n' "$source_value" ;;
    '') printf '%s\n' class-select ;;
    *) installer_fatal "group ${group_name} has invalid source value: ${source_value}" ;;
  esac
}

installer_group_multi_status() {
  group_name=$1
  installer_ensure_classes_conf_path
  conf_path=$INSTALLER_CLASSES_CONF_PATH_CACHE
  multi_value=$(installer_ini_get "$conf_path" "group.${group_name}" multi 2>/dev/null || true)
  case "$multi_value" in
    1|true|TRUE|yes|YES|on|ON|multi) printf '%s\n' multi ;;
    *) printf '%s\n' single ;;
  esac
}

installer_group_is_multi() {
  [ "$(installer_group_multi_status "$1")" = multi ]
}

installer_group_context_var() {
  group_name=$1
  case "$group_name" in
    ''|*[!abcdefghijklmnopqrstuvwxyz0-9-]*)
      installer_fatal "group name contains unsupported characters: ${group_name:-unset}"
      ;;
  esac
  context_group=$(printf '%s' "$group_name" | sed 'y/abcdefghijklmnopqrstuvwxyz-/ABCDEFGHIJKLMNOPQRSTUVWXYZ_/')
  printf 'INSTALLER_%s_CLASS\n' "$context_group"
}

installer_group_names() {
  installer_classes_cache_ensure
  for group_name in $INSTALLER_CLASSES_GROUP_NAMES_TEXT; do
    printf '%s\n' "$group_name"
  done
}

installer_seed_path_exists() (
  installer_load_source_library "$1" || exit 1
  source_exists "$1" "$2"
)

installer_class_source_path() {
  group_name=$1
  class_name=$2
  case "$(installer_group_source "$group_name")" in
    class-auto)
      printf 'classes/class-auto/%s/%s.cfg\n' "$group_name" "$class_name"
      ;;
    class-select)
      printf 'classes/class-select/%s/%s.cfg\n' "$group_name" "$class_name"
      ;;
    class-profile)
      printf 'classes/class-profile/%s.cfg\n' "$class_name"
      ;;
    class-addon)
      printf 'classes/class-addon/%s.cfg\n' "$class_name"
      ;;
    class-apps)
      printf 'classes/class-apps/%s.cfg\n' "$class_name"
      ;;
  esac
}

installer_class_meta_value() {
  seed_base=$1
  group_name=$2
  class_name=$3
  meta_key=$4
  installer_ensure_classes_conf_path
  conf_path=$INSTALLER_CLASSES_CONF_PATH_CACHE
  installer_ini_get "$conf_path" "class.${group_name}.${class_name}" "$meta_key" 2>/dev/null || true
}

installer_configured_class_records() {
  installer_classes_cache_ensure
  for class_record in $INSTALLER_CLASSES_CLASS_RECORDS_TEXT; do
    printf '%s\n' "$class_record"
  done
}

installer_validate_class_group_name() {
  label=$1
  value=$2
  case "$value" in
    ''|*[!abcdefghijklmnopqrstuvwxyz0123456789-]*)
      installer_fatal "${label} contains unsupported characters: ${value:-unset}"
      ;;
  esac
}

installer_validate_class_name() {
  label=$1
  value=$2
  case "$value" in
    ''|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-]*)
      installer_fatal "${label} contains unsupported characters: ${value:-unset}"
      ;;
  esac
}

installer_validate_class_purpose() {
  label=$1
  value=$2
  case "$value" in
    ''|*[!abcdefghijklmnopqrstuvwxyz0123456789-]*)
      installer_fatal "${label} contains unsupported characters: ${value:-unset}"
      ;;
  esac
}

installer_class_token_parts() {
  class_token=$1
  INSTALLER_CLASS_TOKEN_GROUP=
  INSTALLER_CLASS_TOKEN_NAME=
  token_class_group=
  token_class_name=

  case "$class_token" in
    */*)
      token_class_group=${class_token%%/*}
      token_class_name=${class_token#*/}
      case "$token_class_name" in
        */*) installer_fatal "class token contains more than one '/' separator: ${class_token}" ;;
      esac
      ;;
    *:*)
      token_class_group=${class_token%%:*}
      token_class_name=${class_token#*:}
      case "$token_class_name" in
        *:*) installer_fatal "class token contains more than one ':' separator: ${class_token}" ;;
      esac
      ;;
    *.*)
      token_class_group=${class_token%%.*}
      token_class_name=${class_token#*.}
      case "$token_class_name" in
        *.*) installer_fatal "class token contains more than one '.' separator: ${class_token}" ;;
      esac
      ;;
    *)
      token_class_group=
      token_class_name=$class_token
      ;;
  esac

  if [ -n "$token_class_group" ]; then
    installer_validate_class_group_name "class token group" "$token_class_group"
  fi
  installer_validate_class_name "class token class" "$token_class_name"
  INSTALLER_CLASS_TOKEN_GROUP=$token_class_group
  INSTALLER_CLASS_TOKEN_NAME=$token_class_name
  printf '%s\n' "$token_class_name"
}

installer_class_exists() {
  seed_base=$1
  group_name=$2
  class_name=$3
  class_relpath=$(installer_class_source_path "$group_name" "$class_name")

  if [ -n "${INSTALLER_SOURCE_ROOT:-}" ] && [ -r "${INSTALLER_SOURCE_ROOT%/}/${class_relpath}" ]; then
    return 0
  fi
  [ -n "$seed_base" ] || return 1
  installer_seed_path_exists "$seed_base" "$class_relpath"
}

installer_class_has_manifest_record() {
  group_name=$1
  class_name=$2
  installer_ensure_classes_conf_path
  conf_path=$INSTALLER_CLASSES_CONF_PATH_CACHE
  installer_ini_has_section "$conf_path" "class.${group_name}.${class_name}"
}

installer_validate_helper_name() {
  label=$1
  value=$2
  [ -n "$value" ] || return 0
  case "$value" in
    *[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-]*)
      installer_fatal "${label} contains unsupported characters: ${value}"
      ;;
  esac
}

installer_class_helper_order() {
  seed_base=$1
  group_name=$2
  class_name=$3
  helper_order=$(installer_class_meta_value "$seed_base" "$group_name" "$class_name" late_helper_order)
  case "$helper_order" in
    '')
      installer_group_order "$group_name"
      ;;
    *[!0-9]*)
      installer_fatal "class ${group_name}/${class_name} late_helper_order must be numeric: ${helper_order}"
      ;;
    *)
      printf '%s\n' "$helper_order"
      ;;
  esac
}

installer_validate_class_reference() {
  label=$1
  reference=$2
  installer_class_token_parts "$reference" >/dev/null
  [ -n "${INSTALLER_CLASS_TOKEN_NAME:-}" ] || installer_fatal "${label} is empty"
}

installer_validate_class_reference_list() {
  label=$1
  references=$2
  for class_reference in $references; do
    installer_validate_class_reference "$label" "$class_reference"
  done
}

installer_validate_word_metadata() {
  label=$1
  words=$2
  for word_value in $words; do
    case "$word_value" in
      ''|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+._:-]*)
        installer_fatal "${label} contains unsupported token: ${word_value:-unset}"
        ;;
    esac
  done
}

installer_validate_class_manifest() {
  if [ "${INSTALLER_CLASS_MANIFEST_VALIDATED:-0}" -eq 1 ]; then
    return 0
  fi
  installer_classes_cache_ensure
  installer_ensure_classes_conf_path
  conf_path=$INSTALLER_CLASSES_CONF_PATH_CACHE
  manifest_version=$(installer_ini_get "$conf_path" manifest version 2>/dev/null || true)
  seen_groups=' '
  seen_purposes=' '
  seen_classes=' '
  group_count=0

  case "$manifest_version" in
    '') ;;
    *[!0-9]*) installer_fatal "classes/install.conf ManifestVersion must be numeric: ${manifest_version}" ;;
  esac

  while IFS= read -r group_name || [ -n "$group_name" ]; do
    [ -n "$group_name" ] || continue
    installer_validate_class_group_name "class group name" "$group_name"
    case "$seen_groups" in
      *" ${group_name} "*) installer_fatal "duplicate group record in classes/configs/groups.cfg: ${group_name}" ;;
    esac
    seen_groups="${seen_groups}${group_name} "
    group_count=$((group_count + 1))

    required_value=$(installer_ini_get "$conf_path" "group.${group_name}" required 2>/dev/null || true)
    case "$required_value" in
      ''|0|1|true|TRUE|false|FALSE|yes|YES|no|NO|on|ON|off|OFF|required|optional) ;;
      *) installer_fatal "group ${group_name} has invalid required value: ${required_value}" ;;
    esac

    multi_value=$(installer_ini_get "$conf_path" "group.${group_name}" multi 2>/dev/null || true)
    case "$multi_value" in
      ''|0|1|true|TRUE|false|FALSE|yes|YES|no|NO|on|ON|off|OFF|single|multi) ;;
      *) installer_fatal "group ${group_name} has invalid multi value: ${multi_value}" ;;
    esac

    source_value=$(installer_ini_get "$conf_path" "group.${group_name}" source 2>/dev/null || true)
    case "$source_value" in
      ''|class-auto|class-select|class-profile|class-addon|class-apps) ;;
      *) installer_fatal "group ${group_name} has invalid source value: ${source_value}" ;;
    esac

    order_value=$(installer_ini_get "$conf_path" "group.${group_name}" order 2>/dev/null || true)
    case "$order_value" in
      '') ;;
      *[!0-9]*) installer_fatal "group ${group_name} has invalid order value: ${order_value}" ;;
    esac

    group_purpose=$(installer_group_purpose "$group_name")
    if [ -n "$group_purpose" ]; then
      installer_validate_class_purpose "group ${group_name} purpose" "$group_purpose"
      case "$seen_purposes" in
        *" ${group_purpose} "*)
          installer_fatal "duplicate group purpose in classes/configs/groups.cfg: ${group_purpose}"
          ;;
      esac
      seen_purposes="${seen_purposes}${group_purpose} "
    fi
  done <<EOF
$(installer_group_names)
EOF

  [ "$group_count" -gt 0 ] || installer_fatal "classes/configs/groups.cfg must define at least one group record"

  while IFS= read -r class_record || [ -n "$class_record" ]; do
    [ -n "$class_record" ] || continue
    case "$class_record" in
      *.*) ;;
      *) installer_fatal "configured class record must use group.class shape, got: ${class_record}" ;;
    esac
    record_group_name=${class_record%%.*}
    record_class_name=${class_record#*.}
    installer_validate_class_group_name "class metadata group" "$record_group_name"
    installer_validate_class_name "class metadata name" "$record_class_name"
    case "$seen_groups" in
      *" ${record_group_name} "*) ;;
      *) installer_fatal "class ${record_group_name}/${record_class_name} references undefined class group ${record_group_name}" ;;
    esac
    case "$seen_classes" in
      *" ${record_group_name}/${record_class_name} "*)
        installer_fatal "duplicate class record in classes/configs/*.cfg: ${record_group_name}/${record_class_name}"
        ;;
    esac
    seen_classes="${seen_classes}${record_group_name}/${record_class_name} "

    installer_validate_helper_name "class ${record_group_name}/${record_class_name} early_helper" \
      "$(installer_class_meta_value "" "$record_group_name" "$record_class_name" early_helper)"
    installer_validate_helper_name "class ${record_group_name}/${record_class_name} partman_helper" \
      "$(installer_class_meta_value "" "$record_group_name" "$record_class_name" partman_helper)"
    installer_validate_helper_name "class ${record_group_name}/${record_class_name} late_helper" \
      "$(installer_class_meta_value "" "$record_group_name" "$record_class_name" late_helper)"
    helper_order_value=$(installer_class_meta_value "" "$record_group_name" "$record_class_name" late_helper_order)
    case "$helper_order_value" in
      ''|*[!0-9]*) [ -z "$helper_order_value" ] || installer_fatal "class ${record_group_name}/${record_class_name} late_helper_order must be numeric: ${helper_order_value}" ;;
    esac
    installer_validate_class_reference_list "class ${record_group_name}/${record_class_name} requires_classes" \
      "$(installer_class_meta_value "" "$record_group_name" "$record_class_name" requires_classes)"
    installer_validate_class_reference_list "class ${record_group_name}/${record_class_name} allowed_hardware_classes" \
      "$(installer_class_meta_value "" "$record_group_name" "$record_class_name" allowed_hardware_classes)"
    installer_validate_class_reference_list "class ${record_group_name}/${record_class_name} rejected_classes" \
      "$(installer_class_meta_value "" "$record_group_name" "$record_class_name" rejected_classes)"
    installer_normalize_apt_preferences_config \
      "$(installer_class_meta_value "" "$record_group_name" "$record_class_name" debian_apt_preferences)" \
      "class ${record_group_name}/${record_class_name} debian_apt_preferences" >/dev/null

    class_relpath=$(installer_class_source_path "$record_group_name" "$record_class_name")
    if [ -n "${INSTALLER_SOURCE_ROOT:-}" ] && [ ! -r "${INSTALLER_SOURCE_ROOT%/}/${class_relpath}" ]; then
      installer_fatal "class ${record_group_name}/${record_class_name} metadata references missing fragment: ${class_relpath}"
    fi
  done <<EOF
$(installer_configured_class_records)
EOF
  INSTALLER_CLASS_MANIFEST_VALIDATED=1
}

installer_group_for_purpose() {
  group_purpose=$1
  while IFS= read -r group_name || [ -n "$group_name" ]; do
    [ -n "$group_name" ] || continue
    [ "$(installer_group_purpose "$group_name")" = "$group_purpose" ] || continue
    printf '%s\n' "$group_name"
    return 0
  done <<EOF
$(installer_group_names)
EOF
}

installer_auto_group_from_token() {
  token=$1
  installer_class_token_parts "$token" >/dev/null
  token_group=${INSTALLER_CLASS_TOKEN_GROUP:-}
  token_name=$INSTALLER_CLASS_TOKEN_NAME

  case "$token_group" in
    arch|cpu|gpu|disk)
      printf '%s\n' "$token_group"
      return 0
      ;;
  esac

  case "$token_name" in
    amd64|arm64) printf '%s\n' arch ;;
    amd|intel|generic-arm64) printf '%s\n' cpu ;;
    amd-radeon|generic|intel-uhd) printf '%s\n' gpu ;;
    emmc|nvme|vm) printf '%s\n' disk ;;
    *) return 1 ;;
  esac
}

installer_word_list_contains() {
  words=$1
  needle=$2
  case " ${words} " in
    *" ${needle} "*) return 0 ;;
  esac
  return 1
}

installer_auto_class_tokens() {
  seed_base=$1
  auto_script="${RUNTIME_DIR:-$(installer_runtime_dir)}/bootstrap/class-auto.sh"
  auto_classes="$(installer_runtime_temp_log_path class-auto.classes)"
  auto_err="$(installer_runtime_temp_log_path class-auto.err)"
  auto_report="$(installer_runtime_temp_log_path class-auto.report)"
  auto_tokens_found=false

  install -d -m 0700 "$(dirname "$auto_script")"
  installer_ensure_log_files
  installer_fetch_file "$seed_base" "$(installer_repo_join_var DIR_SCRIPTS_PRESEED class-auto.sh)" "$auto_script" 0755
  if "$auto_script" classes >"$auto_classes" 2>"$auto_err"; then
    :
  else
    auto_status=$?
    installer_error "automatic class detection failed with status ${auto_status}"
    if [ "${INSTALLER_LIFECYCLE_ACTIVE:-0}" = 1 ]; then
      installer_record_failure "$auto_status" class-auto "automatic class detection failed; see installer.log" || :
    fi
    [ -s "$auto_err" ] && sed 's/^/[class-auto] /' "$auto_err" >&2
    rm -f "$auto_err" "$auto_report" "$auto_classes"
    exit "$auto_status"
  fi

  if "$auto_script" report >"$auto_report" 2>>"$auto_err"; then
    :
  else
    {
      printf '\n=== d-i hardware detection ===\n\n'
      printf '[AUTO CLASSES]\n'
      sed 's/^/  /' "$auto_classes"
      printf '\n=== end ===\n\n'
    } >"$auto_report"
  fi
  [ -s "$auto_err" ] && sed 's/^/[class-auto] /' "$auto_err" >&2 || true
  rm -f "$auto_err"

  installer_append_log_category_file boot boot info class-auto "$auto_report" || true

  while IFS= read -r auto_token || [ -n "$auto_token" ]; do
    auto_token=$(installer_trim_whitespace "$auto_token")
    [ -n "$auto_token" ] || continue
    installer_validate_class_reference "auto-detected class" "$auto_token"
    auto_tokens_found=true
    printf '%s\n' "$auto_token"
  done <"$auto_classes"
  rm -f "$auto_report" "$auto_classes"

  [ "$auto_tokens_found" = true ] || installer_fatal "automatic class detection did not emit any class tokens"
}

installer_merge_auto_classes() {
  manual_raw=$1
  auto_words=$2
  merged_tokens=
  manual_auto_groups=' '

  for manual_token in $(printf '%s\n' "$manual_raw" | tr ';,' ' ' | sed '/^[[:space:]]*$/d'); do
    [ -n "$manual_token" ] || continue
    if manual_group=$(installer_auto_group_from_token "$manual_token" 2>/dev/null); then
      case "$manual_auto_groups" in
        *" ${manual_group} "*) ;;
        *) manual_auto_groups="${manual_auto_groups}${manual_group} " ;;
      esac
    fi
    case ",${merged_tokens}," in
      *",${manual_token},"*) ;;
      *) merged_tokens="${merged_tokens:+$merged_tokens,}${manual_token}" ;;
    esac
  done

  for auto_token in $auto_words; do
    [ -n "$auto_token" ] || continue
    auto_group=$(installer_auto_group_from_token "$auto_token")
    installer_word_list_contains "$manual_auto_groups" "$auto_group" && continue
    case ",${merged_tokens}," in
      *",${auto_token},"*) ;;
      *) merged_tokens="${merged_tokens:+$merged_tokens,}${auto_token}" ;;
    esac
  done

  printf '%s\n' "$merged_tokens"
}

installer_raw_class_reference_matches() {
  raw_tokens=$1
  class_reference=$2

  installer_class_token_parts "$class_reference" >/dev/null
  wanted_group=${INSTALLER_CLASS_TOKEN_GROUP:-}
  wanted_name=$INSTALLER_CLASS_TOKEN_NAME

  case "$wanted_group" in
    class-addon) wanted_group=addon ;;
  esac

  for raw_token in $(printf '%s\n' "$raw_tokens" | tr ';,' ' ' | sed '/^[[:space:]]*$/d'); do
    [ -n "$raw_token" ] || continue
    installer_class_token_parts "$raw_token" >/dev/null
    token_group=${INSTALLER_CLASS_TOKEN_GROUP:-}
    token_name=$INSTALLER_CLASS_TOKEN_NAME

    case "$token_group" in
      class-addon) token_group=addon ;;
    esac

    [ "$token_name" = "$wanted_name" ] || continue
    [ -z "$token_group" ] && return 0
    [ "$token_group" = "$wanted_group" ] && return 0
  done

  return 1
}

installer_append_implicit_class_tokens() {
  raw_tokens=$1
  printf '%s\n' "$raw_tokens"
}

installer_classes_raw() {
  seed_base=${1:-}
  if [ -n "${INSTALLER_CLASSES_RAW_CACHE:-}" ]; then
    printf '%s\n' "$INSTALLER_CLASSES_RAW_CACHE"
    return 0
  fi

  cmdline_raw=$(installer_cmdline_value classes 2>/dev/null || true)
  if [ -z "$cmdline_raw" ]; then
    cmdline_raw=$(installer_cmdline_value auto-install/classes 2>/dev/null || true)
  fi
  if [ -n "$cmdline_raw" ]; then
    raw=$cmdline_raw
  else
    debconf_raw=$(installer_debconf_value auto-install/classes 2>/dev/null || true)
    if [ -z "$debconf_raw" ]; then
      debconf_raw=$(installer_debconf_value classes 2>/dev/null || true)
    fi
    raw=$debconf_raw
  fi
  raw_cache_path=$(installer_classes_raw_cache_path)
  if [ -z "$raw" ] && [ -s "$raw_cache_path" ]; then
    # Prefer current installer inputs. A persisted cache can be stale across
    # retries or runtime reuse and must not suppress fresh auto-detected groups.
    IFS= read -r INSTALLER_CLASSES_RAW_CACHE <"$raw_cache_path" || INSTALLER_CLASSES_RAW_CACHE=
    if [ -n "$INSTALLER_CLASSES_RAW_CACHE" ]; then
      printf '%s\n' "$INSTALLER_CLASSES_RAW_CACHE"
      return 0
    fi
  fi

  normalized_raw=$(printf '%s\n' "$raw" | sed 's/\\\([;,]\)/\1/g')
  normalized_raw=$(installer_expand_default_classes "$(installer_seed_base "$seed_base")" "$normalized_raw")
  # A command substitution inside a here-document loses the detector status.
  # Capture it as a checked assignment before consuming any class output.
  auto_output=$(installer_auto_class_tokens "$(installer_seed_base "$seed_base")") || return "$?"
  auto_tokens=
  while IFS= read -r auto_token || [ -n "$auto_token" ]; do
    [ -n "$auto_token" ] || continue
    auto_tokens="${auto_tokens:+$auto_tokens }$auto_token"
  done <<EOF
$auto_output
EOF
  normalized_raw=$(installer_merge_auto_classes "$normalized_raw" "$auto_tokens")
  normalized_raw=$(installer_append_implicit_class_tokens "$normalized_raw")
  [ -n "$normalized_raw" ] || installer_fatal "kernel cmdline must include classes=<class>,<class>,... for class-select values; arch/cpu/gpu/disk are auto-detected"
  INSTALLER_CLASSES_RAW_CACHE=$normalized_raw
  install -d -m 0700 "$(dirname "$raw_cache_path")"
  raw_cache_tmp="${raw_cache_path}.tmp.$$"
  printf '%s\n' "$normalized_raw" >"$raw_cache_tmp"
  mv "$raw_cache_tmp" "$raw_cache_path"
  chmod 0600 "$raw_cache_path" 2>/dev/null || true
  printf '%s\n' "$normalized_raw"
}

installer_classes_lines() {
  class_lines_raw=$(installer_classes_raw "${1:-}") || return "$?"
  printf '%s\n' "$class_lines_raw" | tr ';,' '\n' | sed '/^[[:space:]]*$/d; s/^[[:space:]]*//; s/[[:space:]]*$//'
}

installer_selected_class_records_path() {
  printf '%s/selected-classes.tsv\n' "$(installer_runtime_state_dir)"
}

installer_runtime_install_conf_path() {
  printf '%s/state/install.conf\n' "${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}"
}

installer_classes_raw_cache_path() {
  printf '%s/state/classes.raw\n' "${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}"
}

installer_resolve_class_token() {
  seed_base=$1
  class_token=$2
  installer_class_token_parts "$class_token" >/dev/null
  class_name=$INSTALLER_CLASS_TOKEN_NAME
  requested_group=${INSTALLER_CLASS_TOKEN_GROUP:-}

  if [ -n "$requested_group" ]; then
    case "$requested_group" in
      class-addon) requested_group=addon ;;
    esac
    if installer_class_exists "$seed_base" "$requested_group" "$class_name"; then
      INSTALLER_RESOLVED_CLASS_GROUP=$requested_group
      INSTALLER_RESOLVED_CLASS_NAME=$class_name
      return 0
    fi
    if installer_class_has_manifest_record "$requested_group" "$class_name"; then
      installer_fatal "configured installer class ${requested_group}/${class_name} is missing fragment $(installer_class_source_path "$requested_group" "$class_name")"
    fi
    installer_fatal "unknown installer class: ${requested_group}/${class_name}; expected readable fragment $(installer_class_source_path "$requested_group" "$class_name")"
  fi

  match_count=0
  match_groups=
  while IFS= read -r class_record || [ -n "$class_record" ]; do
    [ -n "$class_record" ] || continue
    group_name=${class_record%%.*}
    configured_class_name=${class_record#*.}
    [ "$configured_class_name" = "$class_name" ] || continue
    match_count=$((match_count + 1))
    match_groups="${match_groups:+$match_groups }$group_name"
    matched_group=$group_name
  done <<EOF
$(installer_configured_class_records)
EOF

  case "$match_count" in
    1)
      installer_class_exists "$seed_base" "$matched_group" "$class_name" || \
        installer_fatal "configured installer class ${matched_group}/${class_name} is missing fragment $(installer_class_source_path "$matched_group" "$class_name")"
      INSTALLER_RESOLVED_CLASS_GROUP=$matched_group
      INSTALLER_RESOLVED_CLASS_NAME=$class_name
      return 0
      ;;
    0)
      if installer_class_exists "$seed_base" addon "$class_name"; then
        INSTALLER_RESOLVED_CLASS_GROUP=addon
        INSTALLER_RESOLVED_CLASS_NAME=$class_name
        return 0
      fi
      installer_fatal "unknown installer class: ${class_name}; use group/class for declared classes or add classes/class-addon/${class_name}.cfg"
      ;;
    *)
      installer_fatal "class name '${class_name}' is declared in multiple groups; use group/class. Matching groups:${match_groups:+ ${match_groups}}"
      ;;
  esac
}

installer_resolve_selected_class_records() {
  seed_base=$1
  records_path=$2
  seen_groups=' '
  classes_raw=$(installer_classes_raw "$seed_base")

  install -d -m 0700 "$(dirname "$records_path")"
  : >"$records_path"

  for class_token in $(installer_classes_lines "$seed_base"); do
    installer_resolve_class_token "$seed_base" "$class_token"
    group_name=$INSTALLER_RESOLVED_CLASS_GROUP
    class_name=$INSTALLER_RESOLVED_CLASS_NAME
    case "$seen_groups" in
      *" ${group_name} "*)
        installer_group_is_multi "$group_name" || installer_fatal "group '${group_name}' requires exactly one selected class"
        ;;
    esac
    case "$seen_groups" in
      *" ${group_name} "*) ;;
      *) seen_groups="${seen_groups}${group_name} " ;;
    esac
    printf '%s|%s|%s\n' "$group_name" "$class_name" "$(installer_class_source_path "$group_name" "$class_name")" >>"$records_path"
  done

  while IFS= read -r group_name || [ -n "$group_name" ]; do
    [ -n "$group_name" ] || continue
    case "$(installer_group_required_status "$group_name")" in
      required)
        case "$seen_groups" in
          *" ${group_name} "*) ;;
          *) installer_fatal "required class group '${group_name}' is missing from classes=${classes_raw}" ;;
        esac
        ;;
    esac
  done <<EOF
$(installer_group_names)
EOF

  sort_path="${records_path}.sort.$$"
  : >"$sort_path"
  while IFS='|' read -r group_name class_name class_relpath || [ -n "$group_name" ]; do
    [ -n "$group_name" ] || continue
    printf '%08d|%s|%s|%s\n' \
      "$(installer_group_order "$group_name")" \
      "$group_name" \
      "$class_name" \
      "$class_relpath" >>"$sort_path"
  done <"$records_path"
  sort -t'|' -k1,1n -k2,2 -k3,3 "$sort_path" | cut -d'|' -f2- >"$records_path"
  rm -f "$sort_path"
}

installer_group_selected_class_value() {
  group_name=$1
  context_var=$(installer_group_context_var "$group_name")
  eval "class_name=\${$context_var:-}"
  if [ -n "$class_name" ]; then
    printf '%s\n' "$class_name"
    return 0
  fi

  records_path=$(installer_selected_class_records_path)
  if [ -r "$records_path" ]; then
    if installer_group_is_multi "$group_name"; then
      class_name=
      while IFS='|' read -r record_group record_class _record_path || [ -n "$record_group" ]; do
        [ "$record_group" = "$group_name" ] || continue
        class_name="${class_name:+$class_name }$record_class"
      done <"$records_path"
    else
      class_name=
      while IFS='|' read -r record_group record_class _record_path || [ -n "$record_group" ]; do
        [ "$record_group" = "$group_name" ] || continue
        class_name=$record_class
        break
      done <"$records_path"
    fi
    if [ -n "$class_name" ]; then
      eval "$context_var=\$class_name"
      printf '%s\n' "$class_name"
      return 0
    fi
  fi

  return 1
}

installer_selected_group_names() {
  if [ -n "${INSTALLER_SELECTED_GROUPS:-}" ]; then
    for group_name in $INSTALLER_SELECTED_GROUPS; do
      printf '%s\n' "$group_name"
    done
    return 0
  fi

  records_path=$(installer_selected_class_records_path)
  [ -r "$records_path" ] || return 1
  while IFS='|' read -r group_name _class_name _class_path || [ -n "$group_name" ]; do
    [ -n "$group_name" ] || continue
    printf '%s\n' "$group_name"
  done <"$records_path"
}

installer_selected_class_names() {
  if [ -n "${INSTALLER_SELECTED_CLASSES:-}" ]; then
    for class_name in $INSTALLER_SELECTED_CLASSES; do
      printf '%s\n' "$class_name"
    done
    return 0
  fi

  records_path=$(installer_selected_class_records_path)
  [ -r "$records_path" ] || return 1
  while IFS='|' read -r _group_name class_name _class_path || [ -n "$class_name" ]; do
    [ -n "$class_name" ] || continue
    printf '%s\n' "$class_name"
  done <"$records_path"
}

installer_selected_class_refs() {
  if [ -n "${INSTALLER_SELECTED_CLASS_REFS:-}" ]; then
    for class_ref in $INSTALLER_SELECTED_CLASS_REFS; do
      printf '%s\n' "$class_ref"
    done
    return 0
  fi

  records_path=$(installer_selected_class_records_path)
  [ -r "$records_path" ] || return 1
  while IFS='|' read -r group_name class_name _class_path || [ -n "$group_name" ]; do
    [ -n "$group_name" ] || continue
    printf '%s/%s\n' "$group_name" "$class_name"
  done <"$records_path"
}

installer_selected_class_paths() {
  records_path=$(installer_selected_class_records_path)
  if [ -r "$records_path" ]; then
    while IFS='|' read -r record_group _class_name class_path || [ -n "$record_group" ]; do
      [ -n "$record_group" ] || continue
      [ "$record_group" = profile ] && continue
      [ -n "$class_path" ] || continue
      printf '%s\n' "$class_path"
    done <"$records_path"
    return 0
  fi

  while IFS= read -r group_name || [ -n "$group_name" ]; do
    [ -n "$group_name" ] || continue
    [ "$group_name" = profile ] && continue
    class_name=$(installer_group_selected_class_value "$group_name")
    [ -n "$class_name" ] || continue
    printf '%s\n' "$(installer_class_source_path "$group_name" "$class_name")"
  done <<EOF
$(installer_selected_group_names 2>/dev/null || true)
EOF
}

installer_class_has() {
  needle=$1

  while IFS= read -r class_name || [ -n "$class_name" ]; do
    [ -n "$class_name" ] || continue
    [ "$class_name" = "$needle" ] && return 0
  done <<EOF
$(installer_selected_class_names 2>/dev/null || {
  for raw_token in $(installer_classes_lines); do
    token_parts=$(installer_class_token_parts "$raw_token")
    printf '%s\n' "${token_parts#*|}"
  done
})
EOF
  return 1
}

installer_selected_class_list_has() {
  class_list=$1
  needle=$2
  case " ${class_list} " in
    *" ${needle} "*) return 0 ;;
  esac
  return 1
}

installer_class_reference_matches_selected() {
  class_reference=$1
  selected_group=$2
  selected_class=$3

  installer_class_token_parts "$class_reference" >/dev/null
  [ "$INSTALLER_CLASS_TOKEN_NAME" = "$selected_class" ] || return 1
  [ -z "$INSTALLER_CLASS_TOKEN_GROUP" ] || [ "$INSTALLER_CLASS_TOKEN_GROUP" = "$selected_group" ]
}

installer_class_reference_list_matches_selected() {
  reference_list=$1
  selected_group=$2
  selected_class=$3

  for class_reference in $reference_list; do
    installer_class_reference_matches_selected "$class_reference" "$selected_group" "$selected_class" && return 0
  done
  return 1
}

installer_selected_class_reference_is_selected() {
  class_reference=$1
  records_path=$(installer_selected_class_records_path)

  [ -r "$records_path" ] || return 1
  while IFS='|' read -r selected_group selected_class _selected_relpath || [ -n "$selected_group" ]; do
    [ -n "$selected_group" ] || continue
    installer_class_reference_matches_selected "$class_reference" "$selected_group" "$selected_class" && return 0
  done <"$records_path"
  return 1
}

installer_selected_class_allowed_reference_matches() {
  allowed_references=$1

  for allowed_reference in $allowed_references; do
    installer_selected_class_reference_is_selected "$allowed_reference" && return 0
  done
  return 1
}

installer_selected_class_for_purpose() {
  group_purpose=$1
  group_name=$(installer_group_for_purpose "$group_purpose" 2>/dev/null || true)
  [ -n "$group_name" ] || return 1
  class_name=$(installer_group_selected_class_value "$group_name")
  [ -n "$class_name" ] || return 1
  printf '%s\n' "$class_name"
}

installer_clear_selected_class_state() {
  seed_base=${1:-}
  records_path=$(installer_selected_class_records_path)

  clear_groups=
  while IFS= read -r group_name || [ -n "$group_name" ]; do
    [ -n "$group_name" ] || continue
    case " ${clear_groups} " in
      *" ${group_name} "*) ;;
      *) clear_groups="${clear_groups:+$clear_groups }$group_name" ;;
    esac
  done <<EOF
$(installer_group_names "$seed_base" 2>/dev/null || true)
EOF
  if [ -r "$records_path" ]; then
    while IFS='|' read -r group_name _class_name _class_path || [ -n "$group_name" ]; do
      [ -n "$group_name" ] || continue
      case " ${clear_groups} " in
        *" ${group_name} "*) ;;
        *) clear_groups="${clear_groups:+$clear_groups }$group_name" ;;
      esac
    done <"$records_path"
  fi
  for group_name in $clear_groups; do
    context_var=$(installer_group_context_var "$group_name")
    unset "$context_var" 2>/dev/null || true
  done

  unset INSTALLER_SELECTED_GROUPS INSTALLER_SELECTED_CLASSES INSTALLER_SELECTED_CLASS_REFS \
    INSTALLER_HOST_VARIANT INSTALLER_STORAGE_HOST_PROFILE_PREFIX \
    INSTALLER_INSTALL_DISK_CANDIDATES_DEFAULT INSTALLER_DEFAULT_INSTALL_DISK \
    INSTALLER_HOST_PROFILE INSTALLER_HOST_FAMILY INSTALLER_HOOK_FAMILY \
    INSTALLER_HOST_PROFILE_ENV_DIR INSTALLER_HOST_PROFILE_ENV_NAME 2>/dev/null || true
}

installer_populate_selected_class_state() {
  seed_base=${1:-}
  records_path=$(installer_selected_class_records_path)
  selected_groups=
  selected_classes=
  selected_class_refs=

  installer_resolve_selected_class_records "$seed_base" "$records_path"
  installer_clear_selected_class_state "$seed_base"

  while IFS='|' read -r group_name class_name class_relpath || [ -n "$group_name" ]; do
    [ -n "$group_name" ] || continue
    context_var=$(installer_group_context_var "$group_name")
    if installer_group_is_multi "$group_name"; then
      eval "context_current=\${$context_var:-}"
      context_current="${context_current:+$context_current }$class_name"
      eval "$context_var=\$context_current"
    else
      eval "$context_var=\$class_name"
    fi
    case " ${selected_groups} " in
      *" ${group_name} "*) ;;
      *) selected_groups="${selected_groups:+$selected_groups }$group_name" ;;
    esac
    selected_classes="${selected_classes:+$selected_classes }$class_name"
    selected_class_refs="${selected_class_refs:+$selected_class_refs }${group_name}/${class_name}"
  done <"$records_path"

  INSTALLER_SELECTED_GROUPS=$selected_groups
  INSTALLER_SELECTED_CLASSES=$selected_classes
  INSTALLER_SELECTED_CLASS_REFS=$selected_class_refs

  base_role_group=$(installer_group_for_purpose host-variant)
  storage_group=$(installer_group_for_purpose storage)
  [ -n "$base_role_group" ] || installer_fatal "classes config must define a host-variant group purpose"
  [ -n "$storage_group" ] || installer_fatal "classes config must define a storage group purpose"

  base_role_class=$(installer_group_selected_class_value "$base_role_group")
  storage_class=$(installer_group_selected_class_value "$storage_group")

  host_variant=$(installer_class_meta_value "$seed_base" "$base_role_group" "$base_role_class" host_variant)
  host_profile_prefix=$(installer_class_meta_value "$seed_base" "$storage_group" "$storage_class" host_profile_prefix)
  host_family=$(installer_class_meta_value "$seed_base" "$storage_group" "$storage_class" host_family)
  hook_family=$(installer_class_meta_value "$seed_base" "$storage_group" "$storage_class" hook_family)
  install_disk_candidates_default=$(installer_class_meta_value "$seed_base" "$storage_group" "$storage_class" install_disk_candidates)
  default_install_disk=$(installer_class_meta_value "$seed_base" "$storage_group" "$storage_class" default_install_disk)
  host_profile_env_dir=$host_family
  host_profile_env_name=$host_variant

  [ -n "$host_variant" ] || installer_fatal "selected class ${base_role_group}/${base_role_class} must define HostVariant in classes/configs/system.cfg"
  [ "$host_variant" = "${REPOSITORY_ROLE:-}" ] || installer_fatal "selected role does not match this repository: ${host_variant}"
  [ -n "$host_profile_prefix" ] || installer_fatal "selected class ${storage_group}/${storage_class} must define HostProfilePrefix in classes/configs/storage.cfg"
  [ -n "$host_family" ] || installer_fatal "selected class ${storage_group}/${storage_class} must define HostFamily in classes/configs/storage.cfg"
  [ -n "$hook_family" ] || installer_fatal "selected class ${storage_group}/${storage_class} must define HookFamily in classes/configs/storage.cfg"
  [ -n "$install_disk_candidates_default" ] || installer_fatal "selected class ${storage_group}/${storage_class} must define InstallDiskCandidates in classes/configs/storage.cfg"
  [ -n "$default_install_disk" ] || installer_fatal "selected class ${storage_group}/${storage_class} must define DefaultInstallDisk in classes/configs/storage.cfg"

  profile_group=$(installer_group_for_purpose host-profile-override 2>/dev/null || true)
  profile_class=
  if [ -n "$profile_group" ]; then
    profile_class=$(installer_group_selected_class_value "$profile_group" 2>/dev/null || true)
  fi
  if [ -n "$profile_class" ]; then
    profile_env_dir=$(installer_class_meta_value "$seed_base" "$profile_group" "$profile_class" host_profile_prefix)
    profile_host_family=$(installer_class_meta_value "$seed_base" "$profile_group" "$profile_class" host_family)
    profile_hook_family=$(installer_class_meta_value "$seed_base" "$profile_group" "$profile_class" hook_family)
    [ -n "$profile_env_dir" ] || installer_fatal "selected class ${profile_group}/${profile_class} must define HostProfilePrefix in classes/configs/profile.cfg"
    [ -n "$profile_host_family" ] || installer_fatal "selected class ${profile_group}/${profile_class} must define HostFamily in classes/configs/profile.cfg"
    [ -n "$profile_hook_family" ] || installer_fatal "selected class ${profile_group}/${profile_class} must define HookFamily in classes/configs/profile.cfg"
    host_profile_env_dir=$profile_env_dir
    host_profile_env_name=$profile_class
    host_family=$profile_host_family
    hook_family=$profile_hook_family
  fi

  while IFS='|' read -r group_name class_name class_relpath || [ -n "$group_name" ]; do
    [ -n "$group_name" ] || continue
    required_classes=$(installer_class_meta_value "$seed_base" "$group_name" "$class_name" requires_classes)
    allowed_hardware_classes=$(installer_class_meta_value "$seed_base" "$group_name" "$class_name" allowed_hardware_classes)
    rejected_classes=$(installer_class_meta_value "$seed_base" "$group_name" "$class_name" rejected_classes)
    for required_class in $required_classes; do
      installer_selected_class_reference_is_selected "$required_class" || \
        installer_fatal "selected class ${group_name}/${class_name} requires class ${required_class}"
    done
    if [ -n "$allowed_hardware_classes" ]; then
      installer_selected_class_allowed_reference_matches "$allowed_hardware_classes" || \
        installer_fatal "selected class ${group_name}/${class_name} is only allowed with one of: ${allowed_hardware_classes}"
    fi
    for rejected_class in $rejected_classes; do
      installer_selected_class_reference_is_selected "$rejected_class" && \
        installer_fatal "selected class ${group_name}/${class_name} rejects class ${rejected_class}"
    done
  done <"$records_path"

  INSTALLER_HOST_VARIANT=$host_variant
  INSTALLER_STORAGE_HOST_PROFILE_PREFIX=$host_profile_prefix
  INSTALLER_INSTALL_DISK_CANDIDATES_DEFAULT=$install_disk_candidates_default
  INSTALLER_DEFAULT_INSTALL_DISK=$default_install_disk
  INSTALLER_HOST_PROFILE_ENV_DIR=$host_profile_env_dir
  INSTALLER_HOST_PROFILE_ENV_NAME=$host_profile_env_name
  if [ -n "$profile_class" ]; then
    INSTALLER_HOST_PROFILE="${host_profile_env_dir}-${host_profile_env_name}"
  else
    INSTALLER_HOST_PROFILE="${host_profile_prefix}-${host_variant}"
  fi
  INSTALLER_HOST_FAMILY=$host_family
  INSTALLER_HOOK_FAMILY=$hook_family
}

installer_write_runtime_install_conf() {
  runtime_conf_path=$1
  storage_group=$(installer_group_for_purpose storage 2>/dev/null || true)
  storage_class_value=
  if [ -n "$storage_group" ]; then
    storage_class_value=$(installer_group_selected_class_value "$storage_group" 2>/dev/null || true)
  fi

  {
    printf '# Generated runtime installer class config\n'
    printf '[selected]\n'
    printf 'classes_raw=%s\n' "$INSTALLER_CLASSES_RAW"
    printf 'selected_groups=%s\n' "$INSTALLER_SELECTED_GROUPS"
    printf 'selected_classes=%s\n' "$INSTALLER_SELECTED_CLASSES"
    printf 'selected_class_refs=%s\n' "$INSTALLER_SELECTED_CLASS_REFS"
    printf 'debug_logs=%s\n' "${INSTALLER_DEBUG_LOGS:-0}"
    printf 'host_variant=%s\n' "$INSTALLER_HOST_VARIANT"
    printf 'host_profile=%s\n' "$INSTALLER_HOST_PROFILE"
    printf 'host_family=%s\n' "$INSTALLER_HOST_FAMILY"
    printf 'hook_family=%s\n' "$INSTALLER_HOOK_FAMILY"
    printf 'host_profile_env_dir=%s\n' "$INSTALLER_HOST_PROFILE_ENV_DIR"
    printf 'host_profile_env_name=%s\n' "$INSTALLER_HOST_PROFILE_ENV_NAME"
    printf 'storage_host_profile_prefix=%s\n' "$INSTALLER_STORAGE_HOST_PROFILE_PREFIX"
    printf 'storage_class=%s\n' "${INSTALLER_DISK_CLASS:-$storage_class_value}"
    printf 'install_disk_candidates_default=%s\n' "$INSTALLER_INSTALL_DISK_CANDIDATES_DEFAULT"
    printf 'default_install_disk=%s\n' "$INSTALLER_DEFAULT_INSTALL_DISK"

    while IFS= read -r group_name || [ -n "$group_name" ]; do
      [ -n "$group_name" ] || continue
      class_name=$(installer_group_selected_class_value "$group_name")
      [ -n "$class_name" ] || continue
      printf '\n[group.%s]\n' "$group_name"
      printf 'class=%s\n' "$class_name"
      printf 'required=%s\n' "$(installer_group_required_status "$group_name")"
      printf 'purpose=%s\n' "$(installer_group_purpose "$group_name")"
    done <<EOF
$(installer_selected_group_names 2>/dev/null || true)
EOF
  } >"$runtime_conf_path"
  chmod 0600 "$runtime_conf_path"
}

installer_validate_class_set() {
  if [ -z "${INSTALLER_CLASSES_RAW_CACHE:-}" ]; then
    INSTALLER_CLASSES_RAW_CACHE=$(installer_classes_raw "${1:-}")
  fi
  installer_validate_class_manifest
  installer_resolve_selected_class_records "${1:-}" "$(installer_selected_class_records_path)"
}

installer_resolve_install_target_defaults() {
  if [ -z "${INSTALLER_INSTALL_DISK_CANDIDATES_DEFAULT:-}" ] || [ -z "${INSTALLER_DEFAULT_INSTALL_DISK:-}" ]; then
    installer_load_context_if_present || true
  fi

  [ -n "${INSTALLER_INSTALL_DISK_CANDIDATES_DEFAULT:-}" ] || installer_fatal "installer storage defaults are unavailable; context generation did not populate INSTALLER_INSTALL_DISK_CANDIDATES_DEFAULT"
  [ -n "${INSTALLER_DEFAULT_INSTALL_DISK:-}" ] || installer_fatal "installer storage defaults are unavailable; context generation did not populate INSTALLER_DEFAULT_INSTALL_DISK"

  if [ -z "${INSTALL_DISK_CANDIDATES:-}" ]; then
    INSTALL_DISK_CANDIDATES=$INSTALLER_INSTALL_DISK_CANDIDATES_DEFAULT
  fi
  if [ -z "${DEV_INSTALL_DISK:-}" ]; then
    DEV_INSTALL_DISK=$INSTALLER_DEFAULT_INSTALL_DISK
  fi
}

installer_resolve_host_profile() {
  requested_host_profile=${1:-}

  if [ -n "$requested_host_profile" ]; then
    printf '%s\n' "$requested_host_profile"
    return 0
  fi

  installer_load_context_if_present || true
  [ -n "${INSTALLER_HOST_PROFILE:-}" ] || installer_fatal "HOST_PROFILE is required for installer hook dispatch"
  printf '%s\n' "$INSTALLER_HOST_PROFILE"
}

installer_seed_class_answers() {
  classes_raw=$1

  installer_seed_debconf_value d-i auto-install/classes string "$classes_raw"
  installer_seed_debconf_value d-i classes string "$classes_raw"
}

installer_write_context() {
  seed_base=$1
  runtime_dir=$(installer_runtime_dir)
  context_env=$(installer_context_env_path)
  runtime_install_conf=$(installer_runtime_install_conf_path)

  install -d -m 0700 \
    "$runtime_dir" \
    "$(installer_runtime_state_dir)" \
    "$(installer_runtime_cache_dir)" \
    "$(installer_runtime_bootstrap_dir)"
  installer_ensure_log_files

  seed_base=$(installer_seed_base "$seed_base")
  installer_persist_seed_source "$seed_base"
  installer_ensure_repo_env "$seed_base"
  classes_raw=$(installer_classes_raw "$seed_base")
  INSTALLER_CLASSES_RAW_CACHE=$classes_raw
  installer_validate_class_manifest
  installer_populate_selected_class_state "$seed_base"
  installer_export_logging_policy
  installer_seed_class_answers "$classes_raw"
  INSTALLER_CLASSES_RAW=$classes_raw
  installer_write_runtime_install_conf "$runtime_install_conf"
  installer_info "selected installer classes raw: ${classes_raw}"
  installer_info "selected installer class refs: ${INSTALLER_SELECTED_CLASS_REFS:-}"
  installer_info "selected installer host profile: ${INSTALLER_HOST_PROFILE:-}"
  installer_log_boot_context

  {
    printf 'INSTALLER_SEED_URL_BASE=%s\n' "$(installer_shell_quote "${SEED_URL_BASE:-}")"
    printf 'INSTALLER_SEED_FILE_BASE=%s\n' "$(installer_shell_quote "${SEED_FILE_BASE:-}")"
    printf 'INSTALLER_SEED_BASE=%s\n' "$(installer_shell_quote "$seed_base")"
    printf 'INSTALLER_SEED_SOURCE_TYPE=%s\n' "$(installer_shell_quote "$(installer_seed_source_type "$seed_base")")"
    printf 'INSTALLER_CLASSES_RAW=%s\n' "$(installer_shell_quote "$classes_raw")"
    printf 'CLASSES=%s\n' "$(installer_shell_quote "$classes_raw")"
    printf 'INSTALLER_SELECTED_GROUPS=%s\n' "$(installer_shell_quote "${INSTALLER_SELECTED_GROUPS:-}")"
    printf 'INSTALLER_SELECTED_CLASSES=%s\n' "$(installer_shell_quote "${INSTALLER_SELECTED_CLASSES:-}")"
    printf 'INSTALLER_SELECTED_CLASS_REFS=%s\n' "$(installer_shell_quote "${INSTALLER_SELECTED_CLASS_REFS:-}")"
    printf 'INSTALLER_DEBUG_LOGS=%s\n' "$(installer_shell_quote "${INSTALLER_DEBUG_LOGS:-0}")"
    printf 'INSTALLER_HOST_VARIANT=%s\n' "$(installer_shell_quote "${INSTALLER_HOST_VARIANT:-}")"
    printf 'INSTALLER_HOST_PROFILE=%s\n' "$(installer_shell_quote "${INSTALLER_HOST_PROFILE:-}")"
    printf 'INSTALLER_HOST_FAMILY=%s\n' "$(installer_shell_quote "${INSTALLER_HOST_FAMILY:-}")"
    printf 'INSTALLER_HOOK_FAMILY=%s\n' "$(installer_shell_quote "${INSTALLER_HOOK_FAMILY:-}")"
    printf 'INSTALLER_HOST_PROFILE_ENV_DIR=%s\n' "$(installer_shell_quote "${INSTALLER_HOST_PROFILE_ENV_DIR:-}")"
    printf 'INSTALLER_HOST_PROFILE_ENV_NAME=%s\n' "$(installer_shell_quote "${INSTALLER_HOST_PROFILE_ENV_NAME:-}")"
    printf 'INSTALLER_STORAGE_HOST_PROFILE_PREFIX=%s\n' "$(installer_shell_quote "${INSTALLER_STORAGE_HOST_PROFILE_PREFIX:-}")"
    printf 'INSTALLER_INSTALL_DISK_CANDIDATES_DEFAULT=%s\n' "$(installer_shell_quote "${INSTALLER_INSTALL_DISK_CANDIDATES_DEFAULT:-}")"
    printf 'INSTALLER_DEFAULT_INSTALL_DISK=%s\n' "$(installer_shell_quote "${INSTALLER_DEFAULT_INSTALL_DISK:-}")"
    while IFS= read -r group_name || [ -n "$group_name" ]; do
      [ -n "$group_name" ] || continue
      context_var=$(installer_group_context_var "$group_name")
      class_name=$(installer_group_selected_class_value "$group_name")
      [ -n "$class_name" ] || continue
      printf '%s=%s\n' "$context_var" "$(installer_shell_quote "$class_name")"
    done <<EOF
$(installer_selected_group_names 2>/dev/null || true)
EOF
  } >"$context_env"
  chmod 0600 "$context_env"
  printf '%s\n' "$INSTALLER_HOST_PROFILE"
}

installer_load_context() {
  context_env=$(installer_context_env_path)
  [ -r "$context_env" ] || installer_fatal "context env is missing: ${context_env}"
  # shellcheck disable=SC1090
  . "$context_env"
}

installer_context_has_selected_class_state() {
  [ -n "${INSTALLER_SELECTED_GROUPS:-}" ] || return 1
  [ -n "${INSTALLER_SELECTED_CLASSES:-}" ] || return 1
  [ -n "${INSTALLER_SELECTED_CLASS_REFS:-}" ] || return 1
  [ -n "${INSTALLER_HOST_VARIANT:-}" ] || return 1
  [ -n "${INSTALLER_HOST_PROFILE:-}" ] || return 1
  [ -n "${INSTALLER_HOST_FAMILY:-}" ] || return 1
  [ -n "${INSTALLER_HOOK_FAMILY:-}" ] || return 1
  [ -n "${INSTALLER_HOST_PROFILE_ENV_DIR:-}" ] || return 1
  [ -n "${INSTALLER_HOST_PROFILE_ENV_NAME:-}" ] || return 1
  [ -n "${INSTALLER_STORAGE_HOST_PROFILE_PREFIX:-}" ] || return 1
  [ -n "${INSTALLER_INSTALL_DISK_CANDIDATES_DEFAULT:-}" ] || return 1
  [ -n "${INSTALLER_DEFAULT_INSTALL_DISK:-}" ] || return 1

  for installer_context_group in $INSTALLER_SELECTED_GROUPS; do
    installer_context_value=$(installer_group_selected_class_value "$installer_context_group" 2>/dev/null || true)
    [ -n "$installer_context_value" ] || return 1
  done

  while IFS= read -r installer_context_group || [ -n "$installer_context_group" ]; do
    [ -n "$installer_context_group" ] || continue
    case "$(installer_group_required_status "$installer_context_group")" in
      required)
        installer_context_value=$(installer_group_selected_class_value "$installer_context_group" 2>/dev/null || true)
        [ -n "$installer_context_value" ] || return 1
        ;;
    esac
  done <<EOF
$(installer_group_names)
EOF

  return 0
}

installer_ensure_context_loaded() {
  seed_base=${1:-}

  installer_load_context_if_present || true
  if installer_context_has_selected_class_state; then
    return 0
  fi

  resolved_seed_base=$(installer_seed_base "$seed_base")
  installer_warn "installer class context is missing or incomplete; regenerating from ${resolved_seed_base}"
  installer_write_context "$resolved_seed_base" >/dev/null
  installer_load_context
}

installer_prepare_context() {
  seed_base=$(installer_seed_base "${1:-}")
  installer_write_context "$seed_base" >/dev/null
  installer_load_context
}

# Flat profile storage. The logical 'override' identifier remains compatible.
installer_profile_env_path() {
  installer_validate_profile_component "profile family" "$1"
  installer_validate_profile_component "profile name" "$2"
  case "$1" in
    override) installer_repo_join_var DIR_HOSTS_PROFILES "$2.env" ;;
    btrfs|f2fs|vm) installer_repo_join_var DIR_HOSTS_PROFILES "$1-$2.env" ;;
    *) installer_fatal "unsupported profile family: $1" ;;
  esac
}

# Hardware selection is separate from physical payload storage. Unknown optional
# assets return a non-existent path; their existing FILE_* gate still controls
# whether staging is attempted. Required assets fail through the fetch API.
installer_hardware_asset_path() (
  group=$1; class=$2; leaf=$3
  installer_validate_profile_component "hardware group" "$group"
  installer_validate_profile_component "hardware class" "$class"
  installer_validate_relative_seed_path "$leaf"
  manifest=$(installer_class_metadata_read_path "classes/configs/target-assets.tsv")
  selected=$(awk -F '\t' -v g="$group" -v c="$class" -v p="$leaf" '$1==g && $2==c && $3==p {print $4; exit}' "$manifest")
  if [ -z "$selected" ]; then
    printf '%s\n' "hooks/target/.unavailable/$group/$class/$leaf"
  else
    installer_repo_join_var DIR_HOOKS_TARGET "$selected"
  fi
)

installer_load_source_library() {
  command -v source_fetch >/dev/null 2>&1 && return 0
  for source_library in "${INSTALLER_SOURCE_LIBRARY:-}" \
      "${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}/bootstrap/source.sh" \
      "${INSTALLER_SOURCE_ROOT:-/nonexistent}/scripts/common/source.sh" \
      "${1:-/nonexistent}/scripts/common/source.sh"; do
    [ -n "$source_library" ] && [ -s "$source_library" ] || continue
    # shellcheck disable=SC1090
    . "$source_library"
    return 0
  done
  installer_fatal 'repository transport is missing; start with the generated preseed.cfg'
}

# Legacy means package compatibility, not unauthenticated content. APT itself
# selects this full primary-key fingerprint (including its signing subkeys),
# avoiding a dependency on gpg being installed before pkgsel.
installer_cuda_source_line() (
  set -eu
  repository=$1; suite=$2; components=${3:-}
  [ "$repository" = https://developer.download.nvidia.com/compute/cuda/repos/debian12/x86_64/ ] || {
    installer_fatal 'legacy CUDA is limited to the Debian 12 amd64 archive'; exit 1;
  }
  [ "$suite" = / ] && [ -z "$components" ] || {
    installer_fatal 'legacy CUDA must use the flat Debian 12 archive'; exit 1;
  }
  printf 'deb [arch=amd64 signed-by=/etc/apt/keyrings/cuda-legacy-archive-key.asc,EB693B3035CD5710E231E123A4B469963BF863CC] %s /\n' "$repository"
)

installer_fetch_cuda_key() (
  set -eu
  umask 077
  target=${INSTALLER_TARGET_DIR:-/target}
  keydir=$target/etc/apt/keyrings
  key=$keydir/cuda-legacy-archive-key.asc
  installer_apt_safe_path "$key"
  mkdir -p "$keydir"
  chmod 0755 "$keydir"
  work=$(mktemp -d "$keydir/.cuda-key.XXXXXX")
  trap 'rm -rf "$work"' 0
  installer_load_source_library
  # Resource-limit the public-key download as well as bounding network time.
  (ulimit -f 2048; source_fetch_external \
    https://developer.download.nvidia.com/compute/cuda/repos/debian12/x86_64 \
    3bf863cc.pub "$work/key.asc" 0600)
  [ "$(wc -c <"$work/key.asc")" -le 1048576 ]
  grep -qx -- '-----BEGIN PGP PUBLIC KEY BLOCK-----' "$work/key.asc"
  grep -qx -- '-----END PGP PUBLIC KEY BLOCK-----' "$work/key.asc"
  chmod 0644 "$work/key.asc"
  mv -f "$work/key.asc" "$key"
)

installer_cuda_stage_target_source() (
  set -eu
  umask 077
  line=$(installer_cuda_source_line "$@")
  target=${INSTALLER_TARGET_DIR:-/target}
  source_dir="$target/etc/apt/sources.list.d"
  source="$source_dir/cuda-legacy-temp.list"
  installer_apt_safe_path "$source"
  install -d -m 0755 "$source_dir"
  installer_fetch_cuda_key
  work=$(mktemp "$source_dir/.cuda-legacy.XXXXXX")
  trap 'rm -f "$work"' 0
  trap 'exit 130' INT; trap 'exit 143' TERM; trap 'exit 129' HUP
  printf '%s\n' "$line" >"$work"
  chmod 0644 "$work"
  mv -f "$work" "$source"
)

installer_cuda_refresh_target_apt() (
  set -eu
  installer_info 'authenticating legacy CUDA with its source-scoped pinned NVIDIA key and the default APT crypto/date policy'
  run_in_target 'refresh authenticated legacy CUDA metadata' \
    env -u APT_SEQUOIA_CRYPTO_POLICY -u SEQUOIA_CRYPTO_POLICY \
    LC_ALL=C DEBIAN_FRONTEND=noninteractive apt-get \
    -o Dir::Etc::sourcelist=/etc/apt/sources.list.d/cuda-legacy-temp.list \
    -o Dir::Etc::sourceparts=- -o APT::Get::List-Cleanup=0 \
    -o APT::Update::Error-Mode=any \
    -o Acquire::Retries=3 -o Acquire::http::Timeout=45 \
    -o Acquire::https::Timeout=45 -o DPkg::Use-Pty=0 update
)
