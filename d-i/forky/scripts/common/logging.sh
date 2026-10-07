#!/bin/sh
# Sourced only from the authenticated payload by common/lib.sh.
installer_validate_logging_data() (
  set -eu
  log_base=$1; log_env=$2; log_work=$3
  source_fetch "$log_base" scripts/common/logging-validate.awk "$log_work/validate.awk" 0600 || exit 1
  source_fetch "$log_base" hosts/logging/observability-schema.tsv "$log_work/schema.tsv" 0600 || exit 1
  LC_ALL=C awk -f "$log_work/validate.awk" "$log_work/schema.tsv" "$log_env" > "$log_work/values.map" || exit 1
)

installer_render_logging_file() (
  set -eu
  log_base=$1; log_file=$2
  [ -f "$log_file" ] && [ ! -L "$log_file" ] || exit 1
  log_work=$(mktemp -d "${log_file}.logging.XXXXXX") || exit 1
  trap 'rm -rf -- "$log_work"' 0
  trap 'exit 129' HUP; trap 'exit 130' INT; trap 'exit 143' TERM
  chmod 0700 "$log_work" || exit 1
  source_fetch "$log_base" hosts/logging/observability.env "$log_work/logging.env" 0600 || exit 1
  installer_validate_logging_data "$log_base" "$log_work/logging.env" "$log_work" || exit 1
  source_fetch "$log_base" scripts/common/logging-render.awk "$log_work/render.awk" 0600 || exit 1
  cp -p -- "$log_file" "$log_work/rendered" || exit 1
  LC_ALL=C awk -f "$log_work/render.awk" "$log_work/values.map" "$log_file" > "$log_work/rendered" || exit 1
  mv -f -- "$log_work/rendered" "$log_file" || exit 1
)
