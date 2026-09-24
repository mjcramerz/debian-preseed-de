#!/bin/sh
set -eu

target_root=${1:-/target}
[ -d "$target_root" ] || { printf 'fatal: missing CrowdSec target root\n' >&2; exit 1; }

crowdsec_fatal() {
  printf 'fatal: %s\n' "$*" >&2
  exit 1
}

crowdsec_info() {
  printf '[late:crowdsec] %s\n' "$*" >&2
}

crowdsec_validate_abs_target_path() {
  case "${1:-}" in
    /*) ;;
    *) crowdsec_fatal "target path must be absolute: ${1:-unset}" ;;
  esac
  case "$1" in *'/../'*|*'/./'*|*/..|*/.) crowdsec_fatal "unsafe target path" ;; esac
  installer_apt_safe_path "${target_root}${1}" || crowdsec_fatal "unsafe target path ownership or link"
}

crowdsec_normalize_token() {
  crowdsec_token_value=$1

  case "$crowdsec_token_value" in
    \"*\")
      crowdsec_token_value=${crowdsec_token_value#\"}
      crowdsec_token_value=${crowdsec_token_value%\"}
      ;;
    \'*\')
      crowdsec_token_value=${crowdsec_token_value#\'}
      crowdsec_token_value=${crowdsec_token_value%\'}
      ;;
  esac

  [ -n "$crowdsec_token_value" ] || crowdsec_fatal "crowdsec token must not be empty"
  case "$crowdsec_token_value" in
    *[![:print:]]*|*[[:space:]]*)
      crowdsec_fatal "crowdsec token must be a single printable token without whitespace"
      ;;
  esac
  printf '%s\n' "$crowdsec_token_value"
}

crowdsec_cmdline_token() {
  crowdsec_token=
  for crowdsec_token_key in crowdsec_token crowdsec_enroll_token crowdsec_attachment_key; do
    crowdsec_token=$(installer_cmdline_value "$crowdsec_token_key" 2>/dev/null || true)
    [ -n "$crowdsec_token" ] && break
  done
  [ -n "$crowdsec_token" ] || return 1
  crowdsec_token=$(crowdsec_normalize_token "$crowdsec_token") || return 2
  [ "${#crowdsec_token}" -le 512 ] || return 2
  printf '%s\n' "$crowdsec_token"
}

crowdsec_host_variant() {
  host_variant=${INSTALLER_HOST_VARIANT:-}
  if [ -z "$host_variant" ]; then
    host_variant=$(installer_selected_class_for_purpose host-variant 2>/dev/null || true)
  fi
  case "$host_variant" in
    desktop|server)
      printf '%s\n' "$host_variant"
      ;;
    *)
      crowdsec_fatal "unsupported host variant for crowdsec helper: ${host_variant:-unset}"
      ;;
  esac
}

crowdsec_stage_target_asset() {
  repo_path=$1
  target_path=$2
  mode=$3
  shift 3
  asset_renderer=installer_apply_scalar_placeholders
  if [ "${1:-}" = --environment ]; then
    asset_renderer=installer_apply_systemd_environment_placeholders
    shift
  fi
  target_host_path="${target_root}${target_path}"
  crowdsec_validate_abs_target_path "$target_path"
  target_normalize_systemd_config_parent_modes "$target_path" "$target_root"
  [ -d "${target_host_path%/*}" ] || install -d -m 0755 "${target_host_path%/*}"
  tmp_asset=$(mktemp "${target_host_path%/*}/.crowdsec-asset.XXXXXX") || return $?
  if bootstrap_fetch_seed_file "$seed_base" "$repo_path" "$tmp_asset" 0600 "crowdsec asset ${repo_path}"; then
    if [ "$#" -gt 0 ]; then
      "$asset_renderer" "$tmp_asset" "${tmp_asset}.rendered" "$@" || return $?
      mv -f "${tmp_asset}.rendered" "$tmp_asset" || return $?
    fi
    if LC_ALL=C grep -Eq '__INSTALLER_[A-Z0-9_]+__' "$tmp_asset"; then
      rm -f "$tmp_asset"
      crowdsec_fatal "unresolved CrowdSec template: $repo_path"
    fi
    chmod "$mode" "$tmp_asset" || return $?
    mv -f "$tmp_asset" "$target_host_path" || return $?
  else
    status=$?
    rm -f "$tmp_asset"
    return "$status"
  fi
}


crowdsec_stage_logging_overlay() {
  logging_overlay_repo=$1
  logging_overlay_target=$2
  logging_overlay_kind=$3
  crowdsec_validate_abs_target_path "$logging_overlay_target"
  logging_overlay_host=${target_root}${logging_overlay_target}
  if [ -e "$logging_overlay_host" ] || [ -L "$logging_overlay_host" ]; then
    [ -f "$logging_overlay_host" ] && [ ! -L "$logging_overlay_host" ] ||
      crowdsec_fatal "unsafe CrowdSec logging overlay"
    LC_ALL=C awk -v kind="$logging_overlay_kind" '
      /^[ \t]*#/ || /^[ \t]*$/ { next }
      {
        if (kind=="engine" && $0=="common:") {
          if (section++) exit 1
          next
        }
        if (kind=="engine" && (!section || $0 !~ /^  [a-z_]+: /)) exit 1
        if (kind=="bouncer" && $0 !~ /^[a-z_]+: /) exit 1
        key=$0; sub(/^[ ]*/,"",key); sub(/:.*/,"",key)
        value=$0; sub(/^[^:]*:[ ]*/,"",value)
        if (seen[key]++ || value !~ /^[A-Za-z0-9_./:-]+$/) exit 1
        if (kind=="engine") {
          if (key !~ /^(log_media|log_dir|log_level|log_max_size|log_max_age|log_max_files|compress_logs)$/) exit 1
        } else {
          if (key=="api_url" && value=="http://127.0.0.1:8080/") next
          if (key=="mode" && value=="nftables") next
          if (key !~ /^(log_mode|log_dir|log_level|log_max_size|log_max_age|log_max_backups|log_compression)$/) exit 1
        }
      }
    ' "$logging_overlay_host" || crowdsec_fatal "preserving administrator CrowdSec overlay: $logging_overlay_target"
  fi
  crowdsec_stage_target_asset "$logging_overlay_repo" "$logging_overlay_target" 0600
}

crowdsec_remove_target_asset() {
  target_path=$1
  crowdsec_validate_abs_target_path "$target_path"
  rm -f "${target_root}${target_path}"
}

runtime_dir=${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}
bootstrap_lib=${INSTALLER_BOOTSTRAP_LIB:-${runtime_dir}/bootstrap/bootstrap.sh}
tmp_env_dir=${INSTALLER_LATE_TMP_ENV_DIR:-/tmp/install-env-late/crowdsec}

[ -s "$bootstrap_lib" ] || crowdsec_fatal "installer bootstrap library is unavailable: ${bootstrap_lib}"
# shellcheck disable=SC1090,SC1091
. "$bootstrap_lib"
bootstrap_source_common_lib ""
seed_base=$(installer_current_seed_base 2>/dev/null || installer_seed_base "")
bootstrap_source_common_support_libs "$seed_base" "$tmp_env_dir" fetch hook target
installer_ensure_context_loaded "$seed_base"

installer_selected_class_reference_is_selected addon/crowdsec 2>/dev/null || exit 0

host_profile=${INSTALLER_HOST_PROFILE:-$(installer_resolve_host_profile "" 2>/dev/null || true)}
[ -n "$host_profile" ] || crowdsec_fatal "selected host profile is unavailable for crowdsec helper"
host_env=${INSTALLER_LATE_HOST_ENV:-/tmp/install-env-late/host.env}
[ -r "$host_env" ] || installer_fetch_host_env "$seed_base" "$host_profile" "$host_env" 0600
# shellcheck disable=SC1090,SC1091
. "$host_env"

# Reject unsafe existing native output paths before any tmpfiles or daemon use.
crowdsec_stage_target_asset \
  "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/libexec/native-logging)" \
  /usr/local/libexec/native-logging 0755
run_in_target "validate existing native log paths" \
  /usr/local/libexec/native-logging --preflight

# Native logging must be in place before cscli validates the engine.
crowdsec_stage_logging_overlay \
  "$(installer_repo_join_var DIR_HOOKS_TARGET etc/crowdsec/config.yaml.local)" \
  /etc/crowdsec/config.yaml.local engine
crowdsec_stage_target_asset \
  "$(installer_repo_join_var DIR_HOOKS_TARGET etc/tmpfiles.d/57-crowdsec-logs.conf)" \
  /etc/tmpfiles.d/57-crowdsec-logs.conf 0644
run_in_target "create native CrowdSec log directory before configuration validation" \
  /usr/bin/systemd-tmpfiles --create /etc/tmpfiles.d/57-crowdsec-logs.conf
for logging_unit in crowdsec crowdsec-firewall-bouncer; do
  crowdsec_stage_target_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET "etc/systemd/system/${logging_unit}.service.d/40-logging.conf")" \
    "/etc/systemd/system/${logging_unit}.service.d/40-logging.conf" 0644
done

# dpkg may configure packages in dependency order rather than pkgsel text order.
# The upstream bouncer does not depend on a fully initialized local engine.
run_in_target "verify CrowdSec engine before bouncer enrollment" /bin/sh -eu -c '
crowdsec_engine_status=$(dpkg-query -W -f="\${Status}" crowdsec 2>/dev/null || true)
[ "$crowdsec_engine_status" = "install ok installed" ] || {
  printf "CrowdSec engine package is not configured: %s\n" "${crowdsec_engine_status:-not-installed}" >&2
  exit 1
}
[ -s /etc/crowdsec/config.yaml ] && [ ! -L /etc/crowdsec/config.yaml ] || {
  printf "CrowdSec engine configuration is missing or unsafe\n" >&2
  exit 1
}
if ! cscli config show --key Config.Common.LogMedia -o raw >/dev/null; then
  printf "CrowdSec engine configuration failed cscli validation\n" >&2
  exit 1
fi
' sh
# The d-i locale may not exist inside the target yet; scope C to this package operation.
run_in_target "install CrowdSec bouncer after engine configuration" env LC_ALL=C DEBIAN_FRONTEND=noninteractive apt-get -y --no-install-recommends install crowdsec-firewall-bouncer-nftables
run_in_target "validate CrowdSec bouncer package configuration" /bin/sh -eu -c '
crowdsec_bouncer_status=$(dpkg-query -W -f="\${Status}" crowdsec-firewall-bouncer-nftables 2>/dev/null || true)
[ "$crowdsec_bouncer_status" = "install ok installed" ] || {
  printf "CrowdSec bouncer package is not configured: %s\n" "${crowdsec_bouncer_status:-not-installed}" >&2
  exit 1
}
config=/etc/crowdsec/bouncers/crowdsec-firewall-bouncer.yaml
[ -s "$config" ] && [ ! -L "$config" ] && [ "$(find -P "$config" -maxdepth 0 -printf %n)" = 1 ] || {
  printf "CrowdSec bouncer configuration is missing or unsafe\n" >&2
  exit 1
}
chown root:root "$config"
chmod 0600 "$config"
' sh

crowdsec_validate_abs_target_path /var/lib/firstboot/bin
install -d -m 0700 "${target_root}/var/lib/firstboot" "${target_root}/var/lib/firstboot/bin"

host_variant=$(crowdsec_host_variant)
: "${FILE_CROWDSEC_ENROLL_TOKEN:?FILE_CROWDSEC_ENROLL_TOKEN must be set}"
: "${FILE_CROWDSEC_COMPLETE:?FILE_CROWDSEC_COMPLETE must be set}"
: "${FILE_CROWDSEC_STATUS:?FILE_CROWDSEC_STATUS must be set}"
: "${LOG_SYSTEM_SERVICES_FILE:?LOG_SYSTEM_SERVICES_FILE must be set}"
token_file=$FILE_CROWDSEC_ENROLL_TOKEN
complete_file=$FILE_CROWDSEC_COMPLETE
status_file=$FILE_CROWDSEC_STATUS
log_file=$LOG_SYSTEM_SERVICES_FILE

crowdsec_validate_abs_target_path "$token_file"
crowdsec_validate_abs_target_path "$complete_file"
crowdsec_validate_abs_target_path "$status_file"
crowdsec_validate_abs_target_path "$log_file"

install -d -m 0700 \
  "${target_root}$(dirname "$token_file")" \
  "${target_root}$(dirname "$complete_file")" \
  "${target_root}$(dirname "$status_file")"

crowdsec_stage_target_asset \
  "$(installer_repo_join_var DIR_HOOKS_TARGET etc/crowdsec/acquis.d/20-sshd.yaml)" \
  /etc/crowdsec/acquis.d/20-sshd.yaml \
  0644
crowdsec_stage_target_asset \
  "$(installer_repo_join_var DIR_HOOKS_TARGET etc/crowdsec/acquis.d/21-auditd.yaml)" \
  /etc/crowdsec/acquis.d/21-auditd.yaml \
  0644
crowdsec_remove_target_asset /etc/crowdsec/acquis.d/22-server-syslog.yaml
crowdsec_stage_logging_overlay \
  "$(installer_repo_join_var DIR_HOOKS_TARGET etc/crowdsec/bouncers/crowdsec-firewall-bouncer.yaml.local)" \
  /etc/crowdsec/bouncers/crowdsec-firewall-bouncer.yaml.local bouncer
crowdsec_stage_target_asset \
  "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/system/crowdsec-firewall-bouncer.service.d/override.conf)" \
  /etc/systemd/system/crowdsec-firewall-bouncer.service.d/override.conf \
  0644
crowdsec_stage_target_asset \
  "$(installer_repo_join_var DIR_HOOKS_TARGET "etc/audit/crowdsec/${host_variant}.rules")" \
  /etc/audit/rules.d/zz-crowdsec.rules \
  0640
crowdsec_stage_target_asset \
  "$(installer_repo_join_var DIR_SCRIPTS_FIRSTBOOT assets/var/lib/firstboot/bin/crowdsec-firstboot)" \
  /var/lib/firstboot/bin/crowdsec-firstboot \
  0755
crowdsec_stage_target_asset \
  "$(installer_repo_join_var DIR_SCRIPTS_FIRSTBOOT assets/etc/systemd/system/crowdsec-firstboot.service.tmpl)" \
  /etc/systemd/system/crowdsec-firstboot.service \
  0644 --environment \
  CROWDSEC_HOST_VARIANT "$host_variant" \
  CROWDSEC_ENROLL_TOKEN_FILE "$token_file" \
  CROWDSEC_COMPLETE_FILE "$complete_file" \
  CROWDSEC_STATUS_FILE "$status_file"

crowdsec_stage_target_asset \
  "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/libexec/crowdsec-bouncer-verify)" \
  /usr/local/libexec/crowdsec-bouncer-verify \
  0755
run_in_target "validate CrowdSec enrollment without activating target services" \
  /usr/local/libexec/crowdsec-bouncer-verify --offline

if crowdsec_token=$(crowdsec_cmdline_token 2>/dev/null); then
  token_tmp=$(mktemp "${target_root}${token_file}.XXXXXX")
  printf '%s\n' "$crowdsec_token" >"$token_tmp"
  chmod 0600 "$token_tmp"
  mv -f "$token_tmp" "${target_root}${token_file}"
  crowdsec_info "staged optional console enrollment token for deferred post-boot enrollment"
else
  token_status=$?
  [ "$token_status" -eq 1 ] || crowdsec_fatal "invalid supplied CrowdSec enrollment token"
  rm -f "${target_root}${token_file}"
  crowdsec_info "crowdsec_token not provided on kernel cmdline or in /preseed.env; deferred enrollment stays disabled"
fi
unset crowdsec_token 2>/dev/null || true


run_in_target "enable crowdsec target units" /bin/sh -eu -c '
systemctl --root=/ disable crowdsec.service crowdsec-firewall-bouncer.service >/dev/null
systemctl --root=/ enable crowdsec-firstboot.service >/dev/null
systemctl --root=/ is-enabled crowdsec-firstboot.service >/dev/null
! systemctl --root=/ is-enabled crowdsec.service >/dev/null 2>&1
! systemctl --root=/ is-enabled crowdsec-firewall-bouncer.service >/dev/null 2>&1
' sh

crowdsec_info "staged CrowdSec target assets for host_variant=${host_variant}"
