#!/bin/sh
# Repository transport. POSIX shell; no Python, curl or GNU-only wget required.
# The bootstrap core is embedded by tools/build.py, not maintained twice.
# BEGIN BOOTSTRAP CORE
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
  source_validate_url "$url" || exit 1;
  command -v wget >/dev/null 2>&1 || { source_error 'wget is required in the installer'; exit 1; };
  mkdir -p "$(dirname "$destination")" || exit 1;
  temp=$(mktemp "${destination}.part.XXXXXX") || exit 1; headers=${temp}.headers;
  trap 'rm -f "$temp" "$headers"' 0;
  trap 'exit 130' INT; trap 'exit 143' TERM; trap 'exit 129' HUP;
  help=$(wget --help 2>&1 || :);
  set -- wget -S -T "${INSTALLER_FETCH_TIMEOUT:-45}" -O "$temp";
  case "$help" in *--tries*) set -- "$@" --tries=1 ;; esac;
  case "$help" in *--max-redirect*) set -- "$@" --max-redirect=10 ;; esac;
  if source_insecure; then
    case "$help" in *--no-check-certificate*) set -- "$@" --no-check-certificate ;; *) source_error 'wget cannot honor explicit TLS bypass'; exit 1 ;; esac;
  else
    status=$?; [ "$status" -eq 1 ] || exit "$status";
  fi;
  success=false;
  for attempt in 1 2 3; do
    if "$@" "$url" >"$headers" 2>&1; then success=true; break; fi;
    if grep -Eq 'HTTP/[0-9.]+ (401|403|404|410)' "$headers"; then break; fi;
    [ "$attempt" -eq 3 ] || sleep 1;
  done;
  if [ "$success" != true ]; then cp "$headers" "${destination}.fetch-error" || :; source_error "repository HTTP fetch failed; response details: ${destination}.fetch-error"; exit 1; fi;
  if grep -qi 'certificate validation not implemented' "$headers"; then
    source_insecure || { source_error 'wget cannot verify TLS certificates; use a capable installer image or explicit TLS bypass'; exit 1; };
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
    source_http_get "$url" "$boot/seed.document" "$boot/seed.effective-url" || exit 1;
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
  for pair in 'scripts/common/source.sh source.sh' 'scripts/preseed/bootstrap-entry.sh preseed-bootstrap-entry.sh' 'scripts/preseed/apply.sh preseed-apply.sh'; do
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
