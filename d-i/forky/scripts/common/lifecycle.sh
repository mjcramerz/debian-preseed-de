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
    lc_depth=$((lc_depth + 1));
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
  lc_stop_pid=$1; lc_stop_depth=${2:-0};
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
    installer_stop_tree "$lc_child" "$((lc_stop_depth + 1))" || :;
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

# Udeb has sleep (including fractional intervals), but neither timeout nor
# setsid. Poll only our direct child and enforce a finite number of sleeps.
# This subshell confines traps and variables to this one network operation.
installer_run_bounded() (
  lc_limit=$1; shift;
  case "$lc_limit" in ''|*[!0-9]*) exit 125 ;; esac;
  [ "$lc_limit" -ge 1 ] && [ "$lc_limit" -le 900 ] || exit 125;
  "$@" <&0 &
  lc_bounded_pid=$!;
  trap 'installer_stop_tree "$lc_bounded_pid"; exit 129' HUP;
  trap 'installer_stop_tree "$lc_bounded_pid"; exit 130' INT;
  trap 'installer_stop_tree "$lc_bounded_pid"; exit 143' TERM;
  lc_ticks=0; lc_max_ticks=$((lc_limit * 5));
  while kill -0 "$lc_bounded_pid" 2>/dev/null; do
    if [ "$lc_ticks" -ge "$lc_max_ticks" ]; then
      installer_stop_tree "$lc_bounded_pid";
      wait "$lc_bounded_pid" 2>/dev/null || :;
      exit 124;
    fi;
    sleep 0.2;
    lc_ticks=$((lc_ticks + 1));
  done;
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
