#!/bin/sh
# Profile-driven native IOCost metadata. Sourced by both storage-family flows.
# No benchmark, live uevent, service or manual cgroup write is performed here.

iocost_placeholder_map() (
  # Scope exports to this subshell and its validators. Never evaluate profile
  # values as code. Read raw values through awk ENVIRON, not line-split `env`.
  case "${IOCOST_CALIBRATED_ENABLE+x}${IOCOST_CALIBRATE_ENABLED+x}${IO_COST_CALIBRATE_ENABLE+x}" in
    "") ;;
    *) printf "%s\n" "IOCost: unsupported enable-variable spelling" >&2; exit 1 ;;
  esac
  case "${IOCOST_MODEL_RBPS+x}${IOCOST_MODEL_RSEQIOPS+x}${IOCOST_MODEL_RRANDIOPS+x}${IOCOST_MODEL_WBPS+x}${IOCOST_MODEL_WSEQIOPS+x}${IOCOST_MODEL_WRANDIOPS+x}" in
    "") ;;
    *) printf "%s\n" "IOCost: shared model fields are obsolete; supply each solution model" >&2; exit 1 ;;
  esac
  export IOCOST_CALIBRATE_ENABLE IOCOST_DEVICE_MODEL_MATCH IOCOST_DEVICE_FWREV_MATCH
  export IOCOST_TARGET_SOLUTION IOCOST_SOLUTIONS
  # Reserved groups provide an explicit future-benchmark inventory in every
  # profile. Additional solution names use the identical twelve-field schema.
  # Restrict names BEFORE using them as variable names; hyphen-to-underscore is
  # injective because underscores, uppercase and all other punctuation are banned.
  iocost_keys=$(LC_ALL=C awk '
    function fail(message) { print "IOCost: " message > "/dev/stderr"; exit 1 }
    BEGIN {
      list=ENVIRON["IOCOST_SOLUTIONS"]
      count=split(list, solutions, " "); joined=""
      if (length(list)>2048 || count<1 || count>32) fail("invalid solution count or list length")
      for (i=1;i<=count;i++) {
        s=solutions[i]
        if (length(s)>48 || s !~ /^[a-z][a-z0-9]*(-[a-z0-9]+)*$/ || (s in seen)) fail("invalid or duplicate solution")
        seen[s]=1; joined=joined (i==1 ? "" : " ") s
      }
      if (joined!=list || !(ENVIRON["IOCOST_TARGET_SOLUTION"] in seen)) fail("target solution must be in the canonical solution list")
      n=split("IOCOST_CALIBRATE_ENABLE IOCOST_DEVICE_MODEL_MATCH IOCOST_DEVICE_FWREV_MATCH IOCOST_TARGET_SOLUTION IOCOST_SOLUTIONS", keys, " ")
      for (i=1;i<=n;i++) print keys[i]
      groups=split("isolation isolated-bandwidth bandwidth naive params-naive rlat-99-q1 rlat-99-q2 rlat-99-q3 rlat-99-q4", names, " ")
      for (i=1;i<=groups;i++) reserved[names[i]]=1
      for (i=1;i<=count;i++) if (!(solutions[i] in reserved)) names[++groups]=solutions[i]
      nm=split("RBPS RSEQIOPS RRANDIOPS WBPS WSEQIOPS WRANDIOPS", model_fields, " ")
      nq=split("RPCT RLAT WPCT WLAT MIN MAX", qos_fields, " ")
      for (i=1;i<=groups;i++) {
        group=toupper(names[i]); gsub(/-/, "_", group)
        for (j=1;j<=nm;j++) print "IOCOST_MODEL_" group "_" model_fields[j]
        for (j=1;j<=nq;j++) print "IOCOST_QOS_" group "_" qos_fields[j]
      }
    }') || exit 1
  # Only validator-generated identifiers are expanded as shell words. export
  # does not perform indirect evaluation of their values. No caller state leaks.
  set -f
  IFS=' 	
'
  for iocost_key in $iocost_keys; do export "$iocost_key"; done
  printf '%s\n' "$iocost_keys" | LC_ALL=C awk '
    function fail(message) { print "IOCost: " message > "/dev/stderr"; bad=1; exit 1 }
    function number(key, low, high, fraction, v) {
      v=value[key]
      if (length(v)>16 || (fraction ? v !~ /^(0|[1-9][0-9]*)([.][0-9][0-9]?)?$/ : v !~ /^(0|[1-9][0-9]*)$/) || v+0<low || v+0>high)
        fail("invalid numeric field " key)
    }
    {
      key=$0; keys[NR]=key
      if (!(key in ENVIRON)) fail("missing field " key)
      value[key]=ENVIRON[key]
      if (value[key] ~ /[[:cntrl:]]/) fail("control-containing field " key)
      if (value[key]=="" && key !~ /^IOCOST_(MODEL|QOS)_/) fail("empty field " key)
    }
    END {
      if (bad) exit 1
      if (value["IOCOST_CALIBRATE_ENABLE"]!="true" && value["IOCOST_CALIBRATE_ENABLE"]!="false") fail("boolean must be true or false")
      model=value["IOCOST_DEVICE_MODEL_MATCH"]; literal=model; sub(/[*]$/,"",literal)
      if (length(model)>128 || length(literal)<8 || model !~ /^[A-Za-z0-9][A-Za-z0-9._ -]*[*]?$/) fail("unsafe or overly broad model match")
      fw=value["IOCOST_DEVICE_FWREV_MATCH"]
      if (length(fw)>64 || (fw!="*" && fw !~ /^[A-Za-z0-9][A-Za-z0-9._-]*[*]?$/)) fail("unsafe firmware match")
      count=split(value["IOCOST_SOLUTIONS"], solutions, " ")
      for (i=1;i<=count;i++) { s=toupper(solutions[i]); gsub(/-/,"_",s); selected[s]=1 }
      for (i=1;i<=NR;i++) {
        key=keys[i]
        if (key !~ /^IOCOST_(MODEL|QOS)_/) continue
        group=key; sub(/^IOCOST_(MODEL|QOS)_/,"",group); sub(/_[A-Z]+$/,"",group)
        if (!(group in selected)) {
          if (value[key]!="") fail("parameter for unlisted solution " key)
          continue
        }
        if (key ~ /^IOCOST_MODEL_/) number(key,1,key ~ /BPS$/ ? 1000000000000 : 1000000000,0)
        if (key ~ /^IOCOST_QOS_.*_[RW]PCT$/) number(key,0,100,1)
        if (key ~ /^IOCOST_QOS_.*_[RW]LAT$/) number(key,0,60000000,0)
        if (key ~ /^IOCOST_QOS_.*_(MIN|MAX)$/) number(key,1,10000,1)
      }
      for (group in selected) {
        prefix="IOCOST_QOS_" group "_"
        if (value[prefix "MIN"]+0>value[prefix "MAX"]+0) fail("QoS minimum exceeds maximum")
        if ((value[prefix "RPCT"]+0>0 && value[prefix "RLAT"]+0==0) ||
            (value[prefix "WPCT"]+0>0 && value[prefix "WLAT"]+0==0)) fail("nonzero percentile requires positive latency")
      }
      for (i=1;i<=NR;i++) printf "%s=%s\n",keys[i],value[keys[i]]
    }'
)

# Input is the already validated scalar map, never raw profile/benchmark text.
# Generate all native properties from each solution own model and QoS fields.
# No fixed solution inventory is embedded in the hwdb template or this renderer.
iocost_hwdb_properties() {
  LC_ALL=C awk '
    { eq=index($0,"="); value[substr($0,1,eq-1)]=substr($0,eq+1) }
    END {
      print "IOCOST_SOLUTIONS=" value["IOCOST_SOLUTIONS"]
      count=split(value["IOCOST_SOLUTIONS"], solutions, " ")
      nm=split("RBPS RSEQIOPS RRANDIOPS WBPS WSEQIOPS WRANDIOPS", model_fields, " ")
      nq=split("RPCT RLAT WPCT WLAT MIN MAX", qos_fields, " ")
      for (i=1;i<=count;i++) {
        group=toupper(solutions[i]); gsub(/-/,"_",group)
        prefix="IOCOST_MODEL_" group
        printf "%s=",prefix
        for (j=1;j<=nm;j++) printf "%s%s=%s",j==1 ? "" : " ",tolower(model_fields[j]),value[prefix "_" model_fields[j]]
        printf "\n"
        prefix="IOCOST_QOS_" group
        printf "%s=",prefix
        for (j=1;j<=nq;j++) printf "%s%s=%s",j==1 ? "" : " ",tolower(qos_fields[j]),value[prefix "_" qos_fields[j]]
        printf "\n"
      }
    }'
}

# The paths below are installer-owned constants, never profile destinations.
iocost_assets() {
  printf '%s\n' \
    etc/udev/iocost.conf \
    etc/udev/iocost.conf.d/70-unattended-installer.conf \
    etc/udev/hwdb.d/70-unattended-installer-iocost.hwdb
}

# Existing ancestors must be root-owned real directories. No link traversal is
# needed for these /etc assets (in particular, never follow /target/etc outside).
iocost_safe_parents() (
  iocost_parent=$(dirname "$(target_asset_host_path "/$1")") || exit 1
  while :; do
    [ ! -L "$iocost_parent" ] || exit 1
    if [ -e "$iocost_parent" ]; then
      [ -d "$iocost_parent" ] || exit 1
      [ "$(installer_metadata_value "$iocost_parent" uid_gid)" = 0:0 ] || exit 1
      iocost_mode=$(installer_metadata_value "$iocost_parent" mode) || exit 1
      [ "$((0$iocost_mode & 022))" -eq 0 ] || exit 1
    fi
    [ "$iocost_parent" != "$iocost_root" ] || break
    [ "$iocost_parent" != / ] || exit 1
    iocost_parent=$(dirname "$iocost_parent") || exit 1
  done
)

iocost_owned_file() (
  [ ! -L "$1" ] && [ -f "$1" ] || exit 1
  [ "$(installer_metadata_value "$1" uid_gid_mode_links)" = 0:0:644:1 ] || exit 1
  [ "$(head -n 1 "$1")" = '# Managed by unattended-installer: IOCost.' ]
)

# Debian udev installs a regular, comments-only native config. It is not an
# administrator policy conflict. Admit only inert syntax, not active settings,
# and preserve its original bytes for disable/rollback. Never follow links.
iocost_inactive_native_file() (
  [ ! -L "$1" ] && [ -f "$1" ] || exit 1
  [ "$(installer_metadata_value "$1" uid_gid_mode_links)" = 0:0:644:1 ] || exit 1
  [ "$(wc -c <"$1")" -le "${2:-65536}" ] || exit 1
  # BusyBox awk uses C strings. Make an embedded NUL visible to the control
  # character check rather than letting it truncate a line during validation.
  iocost_native_text=$(LC_ALL=C tr '\000' '\001' <"$1") || exit 1
  printf '%s\n' "$iocost_native_text" | LC_ALL=C awk '
    { line=$0; gsub(/\t/, "", line)
      if (line ~ /[[:cntrl:]]/) {bad=1; exit 1}
      line=$0; sub(/^[ \t]*/, "", line); sub(/[ \t]*$/, "", line)
      if (line=="" || line ~ /^[#;]/) next
      if (line=="[IOCost]" && ++sections==1) next
      bad=1; exit 1
    }
    END {exit bad ? 1 : 0}
  '
)

iocost_saved_native_file() (
  # The marker is in addition to the original 64 KiB maximum.
  iocost_inactive_native_file "$1" 65664 || exit 1
  [ "$(head -n 1 "$1")" = '# Managed by unattended-installer: IOCost native defaults backup.' ]
)

iocost_safe_database() (
  [ ! -L "$1" ] && [ -f "$1" ] || exit 1
  # Native systemd versions publish their binary database read-only (0444).
  # Also accept an existing administrator/root-writable 0644 database.
  case "$(installer_metadata_value "$1" uid_gid_mode_links)" in
    0:0:444:1|0:0:644:1) ;;
    *) exit 1 ;;
  esac
)

iocost_native_hwdb() {
  # Use the target executable AND libraries, not an installer-host database
  # format. The normal target executor also prepares d-i chroot mounts (proc).
  # All absolute paths below are interpreted inside this target root.
  target_exec /usr/bin/systemd-hwdb "$@"
}

iocost_validated_map() {
  printf '%s\n' "$iocost_map"
}

iocost_publish_local() (
  # Local input is already fully rendered in our private staging directory.
  # Reuse the normal same-filesystem temporary-file/atomic-rename publisher.
  fetch_hook() { cp -- "$1" "$2" && chown 0:0 "$2"; }
  stage_target_asset "$1" "$2" "${3:-0644}"
)

iocost_restore_legacy_link() (
  iocost_link_path=$(target_asset_host_path /etc/udev/iocost.conf) || exit 1
  ensure_target_asset_parent /etc/udev/iocost.conf || exit 1
  iocost_link_work=$(mktemp -d "$(dirname "$iocost_link_path")/.installer-iocost-link.XXXXXX") || exit 1
  trap 'rm -rf -- "$iocost_link_work"' EXIT
  ln -s ../systemd/iocost.conf.d/70-unattended-installer.conf "$iocost_link_work/link" || exit 1
  chown -h 0:0 "$iocost_link_work/link" || exit 1
  mv -fT -- "$iocost_link_work/link" "$iocost_link_path" || exit 1
)

# Exact strings and simple globs use the shell matcher without eval. For two
# globs (or bracket/escape syntax), only disjoint literal prefixes prove safety;
# uncertainty is an overlap, never permission to overwrite administrator policy.
iocost_patterns_may_overlap() (
  case "$1:$2" in *'['*|*'\'*) ;;
    *)
      case "$1" in *'*'*|*'?'*) ;; *) case "$1" in $2) exit 0 ;; *) exit 1 ;; esac ;; esac
      case "$2" in *'*'*|*'?'*) ;; *) case "$2" in $1) exit 0 ;; *) exit 1 ;; esac ;; esac
      ;;
  esac
  iocost_prefix_a=${1%%[\*\?\[\\]*}
  iocost_prefix_b=${2%%[\*\?\[\\]*}
  case "$iocost_prefix_a" in "$iocost_prefix_b"*) exit 0 ;; esac
  case "$iocost_prefix_b" in "$iocost_prefix_a"*) exit 0 ;; esac
  exit 1
)

# A single database query cannot validate a wildcard over every firmware.
# Check effective native hwdb source records as well as querying the database.
# Lower-priority values of declared keys are legitimately replaced by our rule;
# extra keys merge, and differing later values conflict. Do not delete either.
iocost_check_hwdb_overrides() (
  : >"$iocost_work/hwdb-seen" || exit 1
  # Native hwdb directories in descending same-basename priority (hwdb(7)).
  for iocost_directory in etc/udev/hwdb.d usr/lib/udev/hwdb.d; do
    iocost_safe_parents "$iocost_directory/.iocost-check" || exit 1
    for iocost_source in "$iocost_root/$iocost_directory/"*.hwdb; do
      [ -e "$iocost_source" ] || [ -L "$iocost_source" ] || continue
      iocost_basename=${iocost_source##*/}
      case "$iocost_basename" in *[!A-Za-z0-9._-]*)
        printf '%s\n' 'IOCost: unsafe hwdb source filename; original preserved' >&2; exit 1 ;;
      esac
      if grep -Fxq -- "$iocost_basename" "$iocost_work/hwdb-seen"; then continue; fi
      printf '%s\n' "$iocost_basename" >>"$iocost_work/hwdb-seen" || exit 1
      # The current installer-owned record will be replaced as one whole file.
      [ "$iocost_basename" != 70-unattended-installer-iocost.hwdb ] || continue
      if [ -L "$iocost_source" ] && [ "$(readlink "$iocost_source")" = /dev/null ]; then continue; fi
      iocost_safe_database "$iocost_source" || { printf '%s\n' "IOCost: unsafe hwdb source preserved: $iocost_source" >&2; exit 1; }
      # Make NUL visible to BusyBox awk rather than allowing line truncation.
      LC_ALL=C tr '\000' '\001' <"$iocost_source" >"$iocost_work/hwdb-source" || exit 1
      LC_ALL=C awk -v basename="$iocost_basename" '
        function finish_record( i) {
          if (conflict) for (i=1;i<=matches;i++) print patterns[i]
          matches=0; conflict=0; properties=0
        }
        NR==FNR {
          eq=index($0,"="); key=substr($0,1,eq-1)
          expected[key]=substr($0,eq+1); next
        }
        { line=$0; gsub(/\t/,"",line); if (line ~ /[[:cntrl:]]/) {bad=1; exit 1} }
        /^[[:space:]]*#/ {next}
        /^[[:space:]]*$/ {finish_record(); next}
        /^[^[:space:]]/ {
          if (properties) finish_record()
          patterns[++matches]=$0; next
        }
        {
          properties=1; line=$0; sub(/^[[:space:]]+/,"",line)
          eq=index(line,"="); key=substr(line,1,eq-1); val=substr(line,eq+1)
          if (key ~ /^IOCOST_/ && (!(key in expected) ||
              (basename>"70-unattended-installer-iocost.hwdb" && val!=expected[key]))) conflict=1
        }
        END {if (bad) exit 1; finish_record()}
      ' "$iocost_work/expected-properties" "$iocost_work/hwdb-source" >"$iocost_work/hwdb-conflicts" || exit 1
      while IFS= read -r iocost_pattern; do
        case "$iocost_pattern" in
          block::name:*:fwrev:*:)
            iocost_other_model=${iocost_pattern#block::name:}
            iocost_other_model=${iocost_other_model%:fwrev:*}
            iocost_other_fw=${iocost_pattern##*:fwrev:}
            iocost_other_fw=${iocost_other_fw%:}
            iocost_patterns_may_overlap "$IOCOST_DEVICE_MODEL_MATCH" "$iocost_other_model" || continue
            iocost_patterns_may_overlap "$IOCOST_DEVICE_FWREV_MATCH" "$iocost_other_fw" || continue
            ;;
          *)
            iocost_patterns_may_overlap "block::name:$IOCOST_DEVICE_MODEL_MATCH:fwrev:$IOCOST_DEVICE_FWREV_MATCH:" "$iocost_pattern" || continue
            ;;
        esac
        printf '%s\n' "IOCost: conflicting or potentially overlapping hwdb record preserved: $iocost_source: $iocost_pattern" >&2
        exit 1
      done <"$iocost_work/hwdb-conflicts"
    done
  done
)

iocost_verify_database() (
  iocost_query_root=$1
  iocost_query_output=$2
  if [ "$iocost_query_root" = / ]; then iocost_check_hwdb_overrides || exit 1; fi
  iocost_model_probe=${IOCOST_DEVICE_MODEL_MATCH%\*}
  iocost_firmware_probe=${IOCOST_DEVICE_FWREV_MATCH%\*}
  [ -n "$iocost_firmware_probe" ] || iocost_firmware_probe=installer-probe
  iocost_native_hwdb --root="$iocost_query_root" query \
    "block::name:${iocost_model_probe}:fwrev:${iocost_firmware_probe}:" >"$iocost_query_output" || exit 1
  LC_ALL=C awk '/^IOCOST_/ { print }' "$iocost_query_output" | LC_ALL=C sort >"$iocost_query_output.sorted" || exit 1
  cmp -s "$iocost_work/expected-properties" "$iocost_query_output.sorted"
)

iocost_restore() {
  iocost_restore_failed=0
  while IFS= read -r iocost_rel; do
    iocost_safe_parents "$iocost_rel" || { iocost_restore_failed=1; continue; }
    if [ -L "$iocost_work/old/$iocost_rel" ]; then
      iocost_restore_legacy_link || iocost_restore_failed=1
    elif [ -f "$iocost_work/old/$iocost_rel" ]; then
      iocost_old_mode=$(installer_metadata_value "$iocost_work/old/$iocost_rel" mode) || { iocost_restore_failed=1; continue; }
      iocost_publish_local "$iocost_work/old/$iocost_rel" "/$iocost_rel" "$iocost_old_mode" || iocost_restore_failed=1
    else
      rm -f -- "$iocost_root/$iocost_rel" || iocost_restore_failed=1
    fi
  done <"$iocost_work/actions"
  [ "$iocost_restore_failed" -eq 0 ]
}

iocost_finish() {
  iocost_status=$?
  trap - EXIT HUP INT TERM
  if [ "$iocost_status" -ne 0 ] && [ "$iocost_publishing" = true ]; then
    if ! iocost_restore; then
      printf '%s\n' "IOCost: rollback failed; private recovery copies retained at $iocost_work" >&2
      rmdir "$iocost_lock" || :
      exit 1
    fi
  fi
  rm -rf -- "$iocost_work"
  rmdir "$iocost_lock" || exit 1
  exit "$iocost_status"
}

stage_target_iocost() (
  set -eu
  umask 077
  # Even disabled profiles must have a complete, valid schema. This capture is
  # data for the existing scalar renderer; it is NEVER sourced as shell code.
  iocost_map=$(iocost_placeholder_map) || exit 1
  iocost_root=${INSTALLER_TARGET_DIR:-/target}
  case "$iocost_root" in /*) ;; *) exit 1 ;; esac
  case "$iocost_root" in /|*//*|*/../*|*/..|*/./*|*/.|*/) exit 1 ;; esac
  [ -d "$iocost_root" ] && [ ! -L "$iocost_root" ] || exit 1
  [ "$(readlink -f "$iocost_root")" = "$iocost_root" ] || exit 1
  INSTALLER_TARGET_DIR=$iocost_root
  iocost_safe_parents etc/iocost-check || exit 1
  iocost_lock=$iocost_root/.installer-iocost.lock
  mkdir -m 0700 "$iocost_lock" || { printf '%s\n' 'IOCost: another staging operation holds the lock' >&2; exit 1; }
  iocost_work=$(mktemp -d "$iocost_root/.installer-iocost.XXXXXX") || { rmdir "$iocost_lock"; exit 1; }
  iocost_publishing=false
  trap iocost_finish EXIT
  trap 'exit 129' HUP
  trap 'exit 130' INT
  trap 'exit 143' TERM
  : >"$iocost_work/actions" || exit 1
  iocost_assets >"$iocost_work/assets" || exit 1
  # Check every final destination before rendering or touching target files.
  while IFS= read -r iocost_rel; do
    iocost_safe_parents "$iocost_rel" || exit 1
    # The native file has separate stock-defaults/legacy-migration handling.
    [ "$iocost_rel" != etc/udev/iocost.conf ] || continue
    if [ "$IOCOST_CALIBRATE_ENABLE" = true ]; then
      if [ -e "$iocost_root/$iocost_rel" ] || [ -L "$iocost_root/$iocost_rel" ]; then
        iocost_owned_file "$iocost_root/$iocost_rel" || { printf '%s\n' "IOCost: unmanaged target preserved: $iocost_rel" >&2; exit 1; }
      fi
      printf '%s\n' "$iocost_rel" >>"$iocost_work/actions" || exit 1
    elif iocost_owned_file "$iocost_root/$iocost_rel"; then
      printf '%s\n' "$iocost_rel" >>"$iocost_work/actions" || exit 1
    fi
  done <"$iocost_work/assets"
  # Retire only marker-owned legacy assets, transactionally. Administrator
  # files remain untouched even when another profile disables this policy.
  for iocost_rel in etc/systemd/iocost.conf etc/systemd/iocost.conf.d/70-unattended-installer.conf; do
    iocost_safe_parents "$iocost_rel" || exit 1
    if iocost_owned_file "$iocost_root/$iocost_rel"; then
      printf '%s\n' "$iocost_rel" >>"$iocost_work/actions" || exit 1
    fi
  done
  iocost_safe_parents etc/udev/iocost.conf || exit 1
  iocost_compat=$iocost_root/etc/udev/iocost.conf
  iocost_saved_rel=etc/udev/iocost.conf.unattended-installer-original
  iocost_saved=$iocost_root/$iocost_saved_rel
  iocost_safe_parents "$iocost_saved_rel" || exit 1
  iocost_have_saved=false
  iocost_save_native=false
  iocost_restore_native=false
  if [ -e "$iocost_saved" ] || [ -L "$iocost_saved" ]; then
    iocost_saved_native_file "$iocost_saved" || { printf '%s\n' 'IOCost: unsafe or unmanaged native-defaults backup preserved' >&2; exit 1; }
    iocost_have_saved=true
    tail -n +2 "$iocost_saved" >"$iocost_work/native-original" || exit 1
    chmod 0644 "$iocost_work/native-original" || exit 1
    iocost_inactive_native_file "$iocost_work/native-original" || exit 1
  fi
  if iocost_owned_file "$iocost_compat" || {
      [ -L "$iocost_compat" ] &&
      [ "$(installer_metadata_value "$iocost_compat" uid_gid)" = 0:0 ] &&
      [ "$(readlink "$iocost_compat")" = ../systemd/iocost.conf.d/70-unattended-installer.conf ] &&
      iocost_owned_file "$iocost_root/etc/systemd/iocost.conf.d/70-unattended-installer.conf"
    }; then
    printf '%s\n' etc/udev/iocost.conf >>"$iocost_work/actions" || exit 1
    if [ "$IOCOST_CALIBRATE_ENABLE" = false ] && [ "$iocost_have_saved" = true ]; then
      iocost_restore_native=true
      printf '%s\n' "$iocost_saved_rel" >>"$iocost_work/actions" || exit 1
    fi
  elif [ "$IOCOST_CALIBRATE_ENABLE" = true ]; then
    if [ -e "$iocost_compat" ] || [ -L "$iocost_compat" ]; then
      iocost_inactive_native_file "$iocost_compat" || { printf '%s\n' 'IOCost: /etc/udev/iocost.conf has active settings or unsafe metadata; original preserved' >&2; exit 1; }
      if [ "$iocost_have_saved" = false ]; then
        iocost_save_native=true
        # Preserve defaults BEFORE replacing the native config with managed data.
        printf '%s\n' "$iocost_saved_rel" >>"$iocost_work/actions" || exit 1
      fi
    fi
    printf '%s\n' etc/udev/iocost.conf >>"$iocost_work/actions" || exit 1
  elif [ "$iocost_have_saved" = true ]; then
    if [ ! -e "$iocost_compat" ] && [ ! -L "$iocost_compat" ]; then
      # Recover a removed/interrupted link without losing the saved defaults.
      iocost_restore_native=true
      printf '%s\n' etc/udev/iocost.conf "$iocost_saved_rel" >>"$iocost_work/actions" || exit 1
    elif iocost_inactive_native_file "$iocost_compat" && cmp -s "$iocost_compat" "$iocost_work/native-original"; then
      # A prior interrupted disable already restored the original file.
      printf '%s\n' "$iocost_saved_rel" >>"$iocost_work/actions" || exit 1
    else
      # An administrator replaced the link: do not restore over their policy.
      printf '%s\n' 'IOCost: native administrator config and saved defaults retained' >&2
    fi
  fi
  # No custom rules on a fresh disabled install: no target tools or hwdb update.
  [ -s "$iocost_work/actions" ] || exit 0
  if grep -Fxq etc/udev/hwdb.d/70-unattended-installer-iocost.hwdb "$iocost_work/actions"; then
    iocost_safe_parents etc/udev/hwdb.bin || exit 1
    if [ -e "$iocost_root/etc/udev/hwdb.bin" ] || [ -L "$iocost_root/etc/udev/hwdb.bin" ]; then
      [ ! -L "$iocost_root/etc/udev/hwdb.bin" ] && [ -f "$iocost_root/etc/udev/hwdb.bin" ] || exit 1
      iocost_safe_database "$iocost_root/etc/udev/hwdb.bin" || exit 1
    fi
    printf '%s\n' etc/udev/hwdb.bin >>"$iocost_work/actions" || exit 1
  fi
  if [ "$IOCOST_CALIBRATE_ENABLE" = true ]; then
    # systemd 257/261 reads the single /etc/udev/iocost.conf file; it does
    # not merge drop-ins. Materialize the same policy there and in its managed
    # drop-in so both requested paths exist and native udev applies the policy.
    # Do not silently assume the interface on an unknown future target binary.
    [ -x "$iocost_root/usr/lib/udev/iocost" ] || exit 1
    # BusyBox grep cannot search beyond embedded NULs even with text mode.
    # Match complete C strings, rather than depending on GNU binary handling.
    LC_ALL=C tr '\000' '\n' <"$iocost_root/usr/lib/udev/iocost" | grep -Fxq /etc/udev/iocost.conf || { printf '%s\n' 'IOCost: unsupported native configuration interface' >&2; exit 1; }
    mkdir -m 0700 "$iocost_work/new" || exit 1
    while IFS= read -r iocost_rel; do
      (INSTALLER_TARGET_DIR=$iocost_work/new
       render_target_asset_with_placeholder_map \
         "$(installer_repo_join_var DIR_HOOKS_TARGET "$iocost_rel.tmpl")" \
         "/$iocost_rel" 0644 iocost_validated_map) || exit 1
    done <"$iocost_work/assets"
    for iocost_name in iocost.conf iocost.conf.d/70-unattended-installer.conf; do
      iocost_needs_target=1
      LC_ALL=C awk -v expected="$IOCOST_TARGET_SOLUTION" -v needs="$iocost_needs_target" '
        /^[[:space:]]*(#|$)/ {next}
        $0=="[IOCost]" {section++;next}
        needs && $0=="TargetSolution=" expected {targets++;next}
        {bad=1;exit 1}
        END {if(bad || section!=1 || targets!=needs)exit 1}
      ' "$iocost_work/new/etc/udev/$iocost_name" || exit 1
    done
    # Compute expectations independently from the rendered template. Append
    # only validated model/QoS properties, then require the exact whole record:
    # one match, one solution list and one pair per solution. Reject additional
    # matches/properties, duplicates or changed values before any publication.
    iocost_hwdb=$iocost_work/new/etc/udev/hwdb.d/70-unattended-installer-iocost.hwdb
    printf '%s\n' "$iocost_map" | iocost_hwdb_properties >"$iocost_work/properties" || exit 1
    LC_ALL=C sort "$iocost_work/properties" >"$iocost_work/expected-properties" || exit 1
    LC_ALL=C awk 'NR>1 {print " " $0}' "$iocost_work/properties" >>"$iocost_hwdb" || exit 1
    LC_ALL=C awk -v match_line="block::name:$IOCOST_DEVICE_MODEL_MATCH:fwrev:$IOCOST_DEVICE_FWREV_MATCH:" '
      NR==FNR { expected[$0]=1; next }
      /^#/ || /^$/ {next}
      $0==match_line {matches++; next}
      /^ IOCOST_/ {
        property=substr($0,2)
        if (!(property in expected) || seen[property]++ || matches!=1) {bad=1; exit 1}
        next
      }
      {bad=1; exit 1}
      END {
        if (matches!=1) bad=1
        for (property in expected) if (seen[property]!=1) bad=1
        exit bad ? 1 : 0
      }
    ' "$iocost_work/expected-properties" "$iocost_hwdb" || exit 1
    # Compile/query the private rendered root first. No target config is live yet.
    iocost_native_hwdb --root="/${iocost_work##*/}/new" --strict update || exit 1
    iocost_verify_database "/${iocost_work##*/}/new" "$iocost_work/query-staged" || exit 1
    iocost_check_hwdb_overrides || exit 1
  fi
  # Take all recovery copies before the first target rename/unlink.
  while IFS= read -r iocost_rel; do
    mkdir -p "$iocost_work/old/$(dirname "$iocost_rel")" || exit 1
    if [ -L "$iocost_root/$iocost_rel" ]; then
      ln -s ../systemd/iocost.conf.d/70-unattended-installer.conf "$iocost_work/old/$iocost_rel" || exit 1
    elif [ -f "$iocost_root/$iocost_rel" ]; then
      cp -p -- "$iocost_root/$iocost_rel" "$iocost_work/old/$iocost_rel" || exit 1
    fi
  done <"$iocost_work/actions"
  if [ "$iocost_save_native" = true ]; then
    # Snapshot is already a checked regular file; the backup is transaction
    # managed too, with a marker that distinguishes it from administrator data.
    { printf '%s\n' '# Managed by unattended-installer: IOCost native defaults backup.'
      cat "$iocost_work/old/etc/udev/iocost.conf"
    } >"$iocost_work/new/$iocost_saved_rel" || exit 1
    chmod 0644 "$iocost_work/new/$iocost_saved_rel" || exit 1
    iocost_saved_native_file "$iocost_work/new/$iocost_saved_rel" || exit 1
  fi
  iocost_publishing=true
  while IFS= read -r iocost_rel; do
    [ "$iocost_rel" != etc/udev/hwdb.bin ] || continue
    iocost_safe_parents "$iocost_rel" || exit 1
    if [ "$IOCOST_CALIBRATE_ENABLE" = false ]; then
      if [ "$iocost_rel" = etc/udev/iocost.conf ] && [ "$iocost_restore_native" = true ]; then
        iocost_publish_local "$iocost_work/native-original" "/$iocost_rel" || exit 1
      else
        rm -f -- "$iocost_root/$iocost_rel" || exit 1
      fi
    elif [ "$iocost_rel" = etc/systemd/iocost.conf ] ||
         [ "$iocost_rel" = etc/systemd/iocost.conf.d/70-unattended-installer.conf ]; then
      rm -f -- "$iocost_root/$iocost_rel" || exit 1
    else
      iocost_publish_local "$iocost_work/new/$iocost_rel" "/$iocost_rel" || exit 1
    fi
  done <"$iocost_work/actions"
  if grep -Fxq etc/udev/hwdb.bin "$iocost_work/actions"; then
    iocost_native_hwdb --root=/ --strict update || exit 1
    [ ! -L "$iocost_root/etc/udev/hwdb.bin" ] && [ -f "$iocost_root/etc/udev/hwdb.bin" ] || exit 1
    iocost_safe_database "$iocost_root/etc/udev/hwdb.bin" || exit 1
    if [ "$IOCOST_CALIBRATE_ENABLE" = true ]; then
      iocost_verify_database / "$iocost_work/query-target" || exit 1
    fi
  fi
  iocost_publishing=false
)
