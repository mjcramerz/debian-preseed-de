#!/bin/sh
# Repository transport. POSIX shell; no Python, curl or GNU-only wget required.
# The bootstrap core is embedded by tools/build.py, not maintained twice.
# BEGIN BOOTSTRAP CORE
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
  case "$2:$3:$4" in *[!0-9:]*|:*|*:|*::*) exit 1 ;; esac;
  case "$lc_field" in
    uid) printf '%s\n' "$3" ;;
    gid) printf '%s\n' "$4" ;;
    links) printf '%s\n' "$2" ;;
    mode|uid_gid_mode|uid_gid_mode_links)
      lc_mode=$(printf '%s\n' "$1" | awk '
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
        }') || exit 1;
      case "$lc_field" in
        mode) printf '%s\n' "$lc_mode" ;;
        uid_gid_mode) printf '%s:%s:%s\n' "$3" "$4" "$lc_mode" ;;
        uid_gid_mode_links) printf '%s:%s:%s:%s\n' "$3" "$4" "$lc_mode" "$2" ;;
      esac ;;
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
    printf 'detail=%s\n' "$(printf '%s' "$lc_detail" | tr '\r\n' ' ')";
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
# Snapshot stdin in the PARENT before starting an asynchronous list. In ash and
# dash, <&0 on an async command duplicates the /dev/null the shell has already
# installed, not the caller's stdin. d-i uses stdin for cdebconf replies; losing
# it makes confmodule return an empty (illegal) status. FD 9 is launch-local:
# preserve d-i's FDs 3-6, close the extra copy in the child, and let the function
# redirection restore the caller's previous FD 9 on return.
installer_run_supervised() {
  "$@" <&9 9<&- &
  LC_CHILD_PID=$!;
  if wait "$LC_CHILD_PID"; then lc_child_status=0; else lc_child_status=$?; fi;
  LC_CHILD_PID=;
  return "$lc_child_status";
} 9<&0;

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
  "$@" <&9 9<&- &
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
) 9<&0;

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
  # main-menu may launch a component before the shell confmodule has redirected
  # protocol stdout onto FD 3. Do this before any repository logger captures it.
  # Never unset DEBIAN_HAS_FRONTEND or start a competing database writer.
  if [ -n "${DEBIAN_HAS_FRONTEND:-}" ] && [ -z "${DEBCONF_REDIR:-}" ]; then
    [ -r /usr/share/debconf/confmodule ] || installer_lifecycle_abort 125 debconf 'shell confmodule is unavailable';
    . /usr/share/debconf/confmodule;
  fi;
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
source_error() {
  printf '[repository] fatal: %s\n' "$*" >&2;
  if [ -w /dev/tty4 ] && [ -c /dev/tty4 ]; then printf '[repository] fatal: %s\n' "$*" >/dev/tty4; fi;
  if command -v logger >/dev/null 2>&1; then logger -t preseed-repository "fatal: $*" 2>/dev/null || :; fi;
  return 1;
};
source_cmdline() {
  if [ "${INSTALLER_CMDLINE+x}" = x ]; then printf '%s\n' "$INSTALLER_CMDLINE"; else cat /proc/cmdline 2>/dev/null || :; fi;
};
source_insecure() (
  set -f;
  answer=;
  for item in $(source_cmdline); do
    case "$item" in
      allow_unauthenticated_ssl|debian-installer/allow_unauthenticated_ssl) answer=true ;;
      allow_unauthenticated_ssl=*|debian-installer/allow_unauthenticated_ssl=*) answer=${item#*=} ;;
    esac;
  done;
  if [ -z "$answer" ] && command -v debconf-get >/dev/null 2>&1; then answer=$(debconf-get debian-installer/allow_unauthenticated_ssl 2>/dev/null || :); fi;
  case "$answer" in true|yes|1|on) exit 0 ;; ''|false|no|0|off) exit 1 ;; *) source_error 'allow_unauthenticated_ssl must be true or false'; exit 2 ;; esac;
);
source_hash() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum; elif command -v busybox >/dev/null 2>&1; then busybox sha256sum; else source_error 'sha256sum is required in the installer'; return 1; fi;
};
source_validate_url() {
  case "$1" in http://?*/*|https://?*/*) ;; *) source_error 'repository URLs must be absolute HTTP or HTTPS URLs with a path'; return 1 ;; esac;
  case "$1" in *[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._~:/?#@\!\$\&\(\)\*+,\;=%-]*) source_error 'repository URL contains unsupported characters'; return 1 ;; esac;
  source_authority=${1#*://}; source_authority=${source_authority%%/*};
  case "$source_authority" in ''|*@*) source_error 'empty URL authority or embedded credentials are not allowed'; return 1 ;; esac;
};
source_effective_url() {
  awk -v initial="$1" 'function join(b,l, a,n,i,out,scheme,host,path,q) { if(l ~ /^https?:\/\//) return l; if(l ~ /^[A-Za-z][A-Za-z0-9+.-]*:/) {bad=1; return l}; scheme=b; sub(/:.*/,"",scheme); host=b; sub(/^https?:\/\//,"",host); sub(/\/.*/,"",host); if(l ~ /^\/\//) return scheme ":" l; sub(/[?#].*/,"",b); if(l ~ /^\//) path=l; else if(l ~ /^\?/) return b l; else {path=b; sub(/^https?:\/\/[^\/]+/,"",path); sub(/[^\/]*$/,"",path); path=path l}; q=path; sub(/^[^?#]*/,"",q); sub(/[?#].*/,"",path); n=split(path,a,"/"); out=""; for(i=1;i<=n;i++){if(a[i]=="" || a[i]==".") continue; if(a[i]=="..") sub(/\/[^\/]*$/,"",out); else out=out "/" a[i]}; return scheme "://" host out q } BEGIN {url=initial; bad=0; count=0} {line=$0; sub(/^[ \t]+/,"",line); if(tolower(line) ~ /^location:/) {sub(/^[^:]*:[ \t]*/,"",line); sub(/\r$/,"",line); sub(/[ \t]+\[following\].*$/,"",line); sub(/[ \t]+$/,"",line); nexturl=join(url,line); if(url ~ /^https:/ && nexturl !~ /^https:/) bad=1; url=nexturl; count++}} END {if(bad || count>10) exit 1; print url}' "$2";
};
source_http_get() (
  set -eu;
  umask 077;
  url=$1; destination=$2; effective=${3:-};
  read_timeout=$(installer_bounded_seconds "${INSTALLER_FETCH_TIMEOUT:-45}") || {
    source_error 'INSTALLER_FETCH_TIMEOUT must be 1 through 900 integer seconds' || :; exit 125;
  };
  wall_timeout=$(installer_bounded_seconds "${INSTALLER_FETCH_WALL_TIMEOUT:-180}") || {
    source_error 'INSTALLER_FETCH_WALL_TIMEOUT must be 1 through 900 integer seconds' || :; exit 125;
  };
  source_validate_url "$url" || exit 1;
  command -v wget >/dev/null 2>&1 || { source_error 'wget is required in the installer'; exit 1; };
  mkdir -p "$(dirname "$destination")" || exit 1;
  temp=$(mktemp "${destination}.part.XXXXXX") || exit 1; headers=${temp}.headers;
  trap 'rm -f "$temp" "$headers"' 0;
  trap 'exit 130' INT; trap 'exit 143' TERM; trap 'exit 129' HUP;
  help=$(wget --help 2>&1 || :);
  set -- wget -S -T "$read_timeout" -O "$temp";
  case "$help" in *--tries*) set -- "$@" --tries=1 ;; esac;
  case "$help" in *--max-redirect*) set -- "$@" --max-redirect=10 ;; esac;
  if source_insecure; then
    source_error 'TLS authentication bypass is forbidden for executable repository content'; exit 1;
  else
    status=$?; [ "$status" -eq 1 ] || exit "$status";
  fi;
  # wget -T is an inactivity timeout; a slow trickle must not extend a fetch
  # forever. The independent wall-clock bound also covers BusyBox retries.
  success=false; fetch_status=1;
  for attempt in 1 2 3; do
    if installer_run_bounded "$wall_timeout" "$@" "$url" >"$headers" 2>&1; then
      success=true; break;
    else fetch_status=$?; fi;
    # Invalid options, local I/O, TLS/authentication and supervisor errors do
    # not become valid by retrying. Retry only potentially transient failures.
    case "$fetch_status" in 2|3|5|6|125|126|127|129|130|143) break ;; esac;
    if grep -Eq 'HTTP/[0-9.]+ (401|403|404|410)' "$headers"; then break; fi;
    [ "$attempt" -eq 3 ] || sleep 1;
  done;
  if [ "$success" != true ]; then
    # Never follow an existing diagnostic symlink or lose the downloader's
    # status behind a generic fetch error. The first failure owns the record.
    { printf 'status=%s\nattempts=%s\n' "$fetch_status" "$attempt"; cat "$headers"; } >"$temp";
    chmod 0600 "$temp" && mv -f "$temp" "${destination}.fetch-error" || :;
    source_error "repository HTTP fetch failed status=$fetch_status attempts=$attempt; response details: ${destination}.fetch-error" || :;
    exit "$fetch_status";
  fi;
  if grep -qi 'certificate validation not implemented' "$headers"; then
    source_error 'wget cannot verify TLS certificates; use a TLS-capable installer image'; exit 1;
  fi;
  resolved=$(source_effective_url "$url" "$headers") || { source_error 'unsafe redirect scheme, HTTPS downgrade, or redirect loop'; exit 1; };
  source_validate_url "$resolved" || exit 1;
  chmod 0600 "$temp" && mv -f "$temp" "$destination" || exit 1;
  if [ -n "$effective" ]; then printf '%s\n' "$resolved" >"$effective"; chmod 0600 "$effective"; fi;
);
source_validate_relative() {
  case "${1:-}" in ''|/*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/@+-]*) source_error 'unsafe repository-relative path'; return 1 ;; esac;
  case "/$1/" in */../*|*/./*|*//*) source_error 'repository path contains traversal or empty components'; return 1 ;; esac;
};
source_transfer() (
  set -eu;
  base=$1; rel=$2; destination=$3;
  source_validate_relative "$rel" || exit 1;
  case "$base" in
    /*)
      candidate=${base%/}/$rel;
      [ -f "$candidate" ] && [ ! -L "$candidate" ] || { source_error "missing or non-regular repository file: $rel"; exit 1; };
      canonical=$(readlink -f "$candidate") || exit 1; root=$(readlink -f "$base") || exit 1;
      case "$canonical" in "${root%/}/"*) ;; *) source_error 'repository file escapes source root'; exit 1 ;; esac;
      mkdir -p "$(dirname "$destination")" || exit 1; temp=$(mktemp "${destination}.part.XXXXXX") || exit 1;
      trap 'rm -f "$temp"' 0; cp "$candidate" "$temp" && chmod 0600 "$temp" && mv -f "$temp" "$destination" || exit 1 ;;
    http://*|https://*) source_http_get "${base%/}/$rel" "$destination" ;;
    *) source_error 'unsupported repository source'; exit 1 ;;
  esac;
);
source_resolve_seed() (
  set -eu;
  set -f;
  runtime=${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}; boot=$runtime/bootstrap;
  umask 077; mkdir -p "$boot" && chmod 0700 "$runtime" "$boot" || exit 1;
  if [ -s "$boot/seed.file" ] && [ -s "$boot/seed.url" ]; then source_error 'ambiguous persisted repository source'; exit 1; fi;
  for kind in file url; do if [ -s "$boot/seed.$kind" ]; then cat "$boot/seed.$kind"; exit 0; fi; done;
  url=; file=;
  for item in $(source_cmdline); do
    case "$item" in
      url=*|preseed/url=*) value=${item#*=}; [ -z "$url" ] || [ "$url" = "$value" ] || { source_error 'conflicting url= parameters'; exit 1; }; url=$value ;;
      file=*|preseed/file=*) value=${item#*=}; [ -z "$file" ] || [ "$file" = "$value" ] || { source_error 'conflicting file= parameters'; exit 1; }; file=$value ;;
    esac;
  done;
  if [ -z "$url$file" ] && command -v debconf-get >/dev/null 2>&1; then url=$(debconf-get preseed/url 2>/dev/null || :); file=$(debconf-get preseed/file 2>/dev/null || :); fi;
  if [ -z "$url$file" ] && [ -r /var/run/preseed.last_location ]; then url=$(cat /var/run/preseed.last_location); fi;
  [ -z "$url" ] || [ -z "$file" ] || { source_error 'specify either file= or url=, not both'; exit 1; };
  case "$url" in /*) file=$url; url= ;; file://localhost/*) file=/${url#file://localhost/}; url= ;; file:///*) file=${url#file://}; url= ;; esac;
  if [ -n "$file" ]; then
    case "$file" in /*) ;; *) source_error 'file= must name an absolute preseed file'; exit 1 ;; esac;
    [ -f "$file" ] || { source_error 'file= does not name a readable preseed file'; exit 1; };
    file=$(readlink -f "$file"); base=${file%/*}; [ -n "$base" ] || base=/;
    case "$base" in *[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/-]*) source_error 'unsupported local repository path'; exit 1 ;; esac;
    printf '%s\n' "$base" >"$boot/seed.file";
  elif [ -n "$url" ]; then
    source_http_get "$url" "$boot/seed.document" "$boot/seed.effective-url" || exit "$?";
    resolved=$(cat "$boot/seed.effective-url"); resolved=${resolved%%\#*}; resolved=${resolved%%\?*};
    base=${resolved%/*}; source_validate_url "$base/" || exit 1;
    printf '%s\n' "$base" >"$boot/seed.url";
  else source_error 'no repository source: pass file=, preseed/file=, url=, or preseed/url='; exit 1;
  fi;
  for state in "$boot/seed.file" "$boot/seed.url" "$boot/seed.effective-url"; do [ ! -f "$state" ] || chmod 0600 "$state"; done; printf '%s\n' "$base";
);
# END BOOTSTRAP CORE

source_normalize_base() (
  value=$1
  case "$value" in file://localhost/*) value=/${value#file://localhost/} ;; file:///*) value=${value#file://} ;; esac
  value=${value%%\#*}; value=${value%%\?*}
  case "$value" in */*.cfg) value=${value%/*} ;; esac
  while [ "$value" != / ] && [ "${value%/}" != "$value" ]; do value=${value%/}; done
  case "$value" in /*) ;; http://*|https://*) source_validate_url "$value/" || exit 1 ;; *) source_error 'unsupported repository base'; exit 1 ;; esac
  printf '%s\n' "$value"
)

source_verify_manifest() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum -c "$1"
  else
    busybox sha256sum -c "$1"
  fi
}

source_cache_root() (
  base=$(source_normalize_base "$1") || exit 1
  key=$(printf '%s' "$base" | source_hash) || exit 1
  printf '%s/cache/seed/%s\n' "${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}" "${key%% *}"
)

# One content snapshot per install. A release is built before it is served;
# modifying profiles/assets requires tools/build.py, which updates preseed pins.
source_prepare_payload() (
  set -eu
  umask 077
  base=$1; expected_archive=$2; expected_manifest=$3
  case "$expected_archive$expected_manifest" in *[!a-f0-9]*) source_error 'invalid payload digest'; exit 1 ;; esac
  [ "${#expected_archive}" -eq 64 ] && [ "${#expected_manifest}" -eq 64 ] || exit 1
  runtime=${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}
  root=$(source_cache_root "$base")
  marker=$runtime/bootstrap/payload.ready
  if [ -r "$marker" ] && [ "$(cat "$marker")" = "$expected_archive $expected_manifest $base" ]; then exit 0; fi
  mkdir -p "$runtime/bootstrap" || exit 1
  work=$(mktemp -d "$runtime/bootstrap/payload.XXXXXX") || exit 1
  trap 'rm -rf "$work"' 0
  trap 'exit 130' INT; trap 'exit 143' TERM
  source_transfer "$base" payload.manifest "$work/payload.manifest" || exit 1
  actual=$(source_hash <"$work/payload.manifest"); [ "${actual%% *}" = "$expected_manifest" ] || { source_error 'payload manifest differs from preseed pin; rebuild and publish atomically'; exit 1; }
  source_transfer "$base" payload.tar.gz "$work/payload.tar.gz" || exit 1
  actual=$(source_hash <"$work/payload.tar.gz"); [ "${actual%% *}" = "$expected_archive" ] || { source_error 'payload archive differs from preseed pin; rebuild and publish atomically'; exit 1; }
  # A bundle must contain regular files only; reject links, devices, directories,
  # duplicate entries and escaping paths BEFORE extraction into a private tree.
  tar -tzf "$work/payload.tar.gz" >"$work/members" || { source_error 'cannot list payload archive'; exit 1; }
  tar -tvzf "$work/payload.tar.gz" >"$work/types" || exit 1
  if grep -q '^[^-]' "$work/types"; then source_error 'payload contains a non-regular archive member'; exit 1; fi
  while IFS= read -r path; do source_validate_relative "$path" || exit 1; done <"$work/members"
  sort "$work/members" >"$work/members.sorted"
  sort -u "$work/members" >"$work/members.unique"
  cmp -s "$work/members.sorted" "$work/members.unique" || { source_error 'duplicate payload archive member'; exit 1; }
  awk 'length($1)!=64 || $1 ~ /[^a-f0-9]/ || NF!=2 {exit 1} {print $2}' "$work/payload.manifest" >"$work/expected" || { source_error 'malformed payload manifest'; exit 1; }
  while IFS= read -r path; do source_validate_relative "$path" || exit 1; done <"$work/expected"
  sort "$work/expected" >"$work/expected.sorted"
  cmp -s "$work/expected.sorted" "$work/members.sorted" || { source_error 'payload member set differs from manifest'; exit 1; }
  mkdir "$work/tree" || exit 1
  tar -xzf "$work/payload.tar.gz" -C "$work/tree" || { source_error 'cannot extract payload archive'; exit 1; }
  (cd "$work/tree"; source_verify_manifest ../payload.manifest >../verification.log 2>&1) || { source_error 'payload file verification failed'; exit 1; }
  # Local media must not silently use a stale built snapshot after editing.
  case "$base" in /*) (cd "$base"; source_verify_manifest "$work/payload.manifest" >"$work/local-verification.log" 2>&1) || { source_error 'local repository changed after build; run tools/build.py'; exit 1; } ;; esac
  [ -s "$work/tree/repo.env" ] && [ -s "$work/tree/scripts/common/lib.sh" ] || { source_error 'payload lacks installer entry files'; exit 1; }
  for file in "$work/tree"/scripts/*/*.sh "$work/tree"/hosts/installer/*.env "$work/tree"/hosts/profiles/*.env; do
    [ -f "$file" ] || continue
    /bin/sh -n "$file" || { source_error "invalid shell syntax: ${file#"$work/tree/"}"; exit 1; }
  done
  mkdir -p "$(dirname "$root")" || exit 1
  if [ -e "$root" ]; then rm -rf "$root" || exit 1; fi
  mv "$work/tree" "$root" || exit 1
  cp "$work/payload.manifest" "$runtime/bootstrap/payload.manifest" || exit 1
  printf '%s\n' "$expected_archive $expected_manifest $base" >"$marker"
  chmod 0600 "$marker"
)

source_fetch() (
  set -eu
  umask 077
  base=$(source_normalize_base "$1") || exit 1
  rel=$2; destination=$3; mode=${4:-0600}
  source_validate_relative "$rel" || exit 1
  case "$mode" in [0-7][0-7][0-7]|0[0-7][0-7][0-7]) ;; *) source_error 'invalid fetched file mode'; exit 1 ;; esac
  root=$(source_cache_root "$base") || exit 1
  cache=$root/$rel
  if [ ! -f "$cache" ]; then
    # Once a snapshot is validated, never mix it with a moving remote branch.
    if [ -f "${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}/bootstrap/payload.ready" ]; then source_error "file absent from validated payload: $rel"; exit 1; fi
    source_transfer "$base" "$rel" "$cache" || exit 1
  fi
  if [ ! -s "$cache" ]; then
    case "$rel" in classes/class-profile/*.cfg) ;; *) source_error "unexpected empty repository file: $rel"; exit 1 ;; esac
  fi
  [ "$cache" != "$destination" ] || { chmod "$mode" "$destination"; exit 0; }
  mkdir -p "$(dirname "$destination")" || exit 1
  temporary=$(mktemp "${destination}.part.XXXXXX") || exit 1
  trap 'rm -f "$temporary"' 0
  cp "$cache" "$temporary" && chmod "$mode" "$temporary" && mv -f "$temporary" "$destination" || exit 1
)

source_exists() (
  set -eu
  source_validate_relative "$2" || exit 1
  root=$(source_cache_root "$1") || exit 1
  [ ! -f "$root/$2" ] || exit 0
  [ ! -f "${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}/bootstrap/payload.ready" ] || exit 1
  source_fetch "$1" "$2" "$root/$2" 0600
)

source_bootstrap() (
  set -eu
  base=$1; archive_digest=$2; manifest_digest=$3
  runtime=${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}
  boot=$runtime/bootstrap
  source_prepare_payload "$base" "$archive_digest" "$manifest_digest" || exit 1
  for pair in 'scripts/common/source.sh source.sh' 'scripts/preseed/bootstrap-entry.sh preseed-bootstrap-entry.sh' 'scripts/preseed/apply.sh preseed-apply.sh' 'scripts/preseed/guard-hook.sh guard-hook.sh'; do
    set -- $pair
    source_fetch "$base" "$1" "$boot/$2" 0700 || exit 1
  done
  "$boot/preseed-bootstrap-entry.sh" prepare-context /tmp/installer.log "$base" || { source_error 'class/profile preflight failed; see /tmp/installer.log (console 4)'; exit 1; }
  # All includes are local, absolute URIs: preseed.last_location can no longer
  # accidentally anchor them to a shortener, CDN host root or previous include.
  for rel in common.cfg fragments/network.cfg fragments/partman.cfg fragments/apt.cfg fragments/finish.cfg; do
    destination=$boot/includes/$rel
    source_fetch "$base" "$rel" "$destination" 0600 || exit 1
    printf 'file://%s\n' "$destination"
  done
  : >"$boot/preflight.ok"
)

# External vendor data is NOT part of the immutable repository snapshot. Keep
# this deliberately separate from source_fetch: a missing snapshot member must
# still fail closed. TLS bypass is never inherited by this transport.
source_fetch_external() (
  set -eu
  umask 077
  base=$1; rel=$2; destination=$3; mode=${4:-0600}
  case "$base" in https://*) ;; *) source_error 'external downloads require HTTPS'; exit 1 ;; esac
  source_validate_relative "$rel" || exit 1
  case "$mode" in 0600|0644) ;; *) source_error 'external data must not be executable'; exit 1 ;; esac
  source_insecure() { return 1; }
  mkdir -p "$(dirname "$destination")"
  scratch=$(mktemp -d "${destination}.external.XXXXXX") || exit 1
  trap 'rm -rf "$scratch"' 0
  trap 'exit 130' INT; trap 'exit 143' TERM; trap 'exit 129' HUP
  source_http_get "${base%/}/$rel" "$scratch/data" || exit 1
  [ -s "$scratch/data" ] || { source_error 'empty external download'; exit 1; }
  chmod "$mode" "$scratch/data"
  mv -f "$scratch/data" "$destination"
)
