#!/bin/sh
set -eu

target_root=${1:-/target}

software_fatal() {
  printf 'fatal: %s\n' "$*" >&2
  exit 1
}

software_info() {
  printf '[late:software] %s\n' "$*" >&2
}

software_warn() {
  printf '[late:software] warning: %s\n' "$*" >&2
}

software_validate_abs_path() (
  label=$1
  value=$2

  case "$value" in
    /*) ;;
    *) software_fatal "$label must be an absolute path: ${value:-unset}" ;;
  esac
  case "$value" in
    /|*..*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/@%:+,-]*)
      software_fatal "$label contains unsupported path syntax: $value"
      ;;
  esac
)

software_validate_release_version() {
  label=$1
  value=$2

  printf '%s\n' "$value" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$' ||
    software_fatal "$label must contain three numeric components: ${value:-unset}"
  [ "${#value}" -le 32 ] ||
    software_fatal "$label exceeds 32 characters"
}

software_validate_sha256() {
  label=$1
  value=$2

  [ "${#value}" -eq 64 ] ||
    software_fatal "$label must contain 64 lowercase hexadecimal characters"
  case "$value" in
    *[!0123456789abcdef]*)
      software_fatal "$label must contain 64 lowercase hexadecimal characters"
      ;;
  esac
}

software_validate_bounded_bytes() {
  label=$1
  value=$2
  maximum=$3

  case "$value:$maximum" in
    *[!0123456789:]*|:|*:)
      software_fatal "$label must be a positive integer"
      ;;
  esac
  [ "$value" -gt 0 ] && [ "$value" -le "$maximum" ] ||
    software_fatal "$label is outside the approved range: $value"
}

software_validate_abs_path "target root" "$target_root"
[ -d "$target_root" ] || exit 0

runtime_dir=${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}
bootstrap_lib=${INSTALLER_BOOTSTRAP_LIB:-${runtime_dir}/bootstrap/bootstrap.sh}
tmp_env_dir=${INSTALLER_LATE_TMP_ENV_DIR:-/tmp/install-env-late/software}

[ -s "$bootstrap_lib" ] || software_fatal "installer bootstrap library is unavailable: ${bootstrap_lib}"
# shellcheck disable=SC1090,SC1091
. "$bootstrap_lib"
bootstrap_source_common_lib "" || software_fatal "failed to source installer common library"
seed_base=$(installer_current_seed_base 2>/dev/null || installer_seed_base "")
bootstrap_source_common_support_libs "$seed_base" "$tmp_env_dir" fetch hook target || {
  software_fatal "failed to source installer late support libraries"
}
installer_ensure_context_loaded "$seed_base"

installer_selected_class_reference_is_selected addon/software 2>/dev/null || exit 0
[ "${INSTALLER_HOST_VARIANT:-}" = desktop ] ||
  software_fatal "addon/software is restricted to the desktop role"
chatgpt_enabled=false
if installer_selected_class_reference_is_selected addon/devops 2>/dev/null; then
  chatgpt_enabled=true
fi

account_env=${INSTALLER_LATE_ACCOUNT_ENV:-/tmp/install-env-late/account.env}
host_env=${INSTALLER_LATE_HOST_ENV:-/tmp/install-env-late/host.env}
runtime_common=/tmp/install-env-late/runtime-common.sh
account_runtime=/tmp/install-env-late/account-runtime.sh
[ -r "$account_env" ] || installer_fetch_account_env "$seed_base" "$account_env" 0600
[ -r "$host_env" ] ||
  installer_fetch_host_env "$seed_base" "$(installer_resolve_host_profile "")" "$host_env" 0600
[ -r "$runtime_common" ] ||
  fetch_hook_file "$(installer_repo_join_var DIR_SCRIPTS_RUNTIME common.sh)" "$runtime_common"
[ -r "$account_runtime" ] ||
  fetch_hook_file "$(installer_repo_join_var DIR_SCRIPTS_RUNTIME account.sh)" "$account_runtime"
# shellcheck disable=SC1090,SC1091
. "$account_env"
# shellcheck disable=SC1090,SC1091
. "$host_env"
desktop_detect="${tmp_env_dir}/desktop-detect.sh"
[ -r "$desktop_detect" ] ||
  fetch_hook_file "$(installer_repo_join_var DIR_SCRIPTS_DESKTOP detect.sh)" "$desktop_detect"
# shellcheck disable=SC1090,SC1091
. "$desktop_detect"
desktop_resolve_acceleration_availability
desktop_resolve_managed_app_default_exec
RUNTIME_COMMON_LIB=$runtime_common
export RUNTIME_COMMON_LIB
# shellcheck disable=SC1090,SC1091
. "$account_runtime"
runtime_apply_account_from_cmdline
: "${ACCOUNT_USERNAME:?ACCOUNT_USERNAME must be set before managed software account integration}"

target_arch=$(chroot "$target_root" /usr/bin/dpkg --print-architecture 2>/dev/null || true)
case "$target_arch" in
  amd64) ;;
  arm64)
    software_info "managed Bitwarden, Obsidian, Zoom, Filen, Discord, and Tuta downloads are unavailable for arm64; keeping the architecture-compatible software bundle"
    exit 0
    ;;
  *)
    software_fatal "unsupported target architecture for managed desktop downloads: ${target_arch:-unset}"
    ;;
esac

work_dir=/tmp/installer-software
bitwarden_deb="${work_dir}/bitwarden-latest.deb"
obsidian_version=1.12.7
obsidian_url="https://github.com/obsidianmd/obsidian-releases/releases/download/v${obsidian_version}/obsidian_${obsidian_version}_amd64.deb"
obsidian_sha256=3644e3ef19bcd23db4d17f7c73311b5245429391a2a48b361da93375f59712b0
obsidian_size=85762386
obsidian_deb="${work_dir}/obsidian_${obsidian_version}_amd64.deb"
postman_url=https://dl.pstmn.io/download/latest/linux64
postman_archive="${work_dir}/postman-linux64.tar.gz"
postman_member_list="${work_dir}/postman-members.txt"
postman_verbose_list="${work_dir}/postman-members.verbose.txt"
postman_install_dir=/opt/postman
postman_desktop_file=/usr/share/applications/postman.desktop
postman_icon_file="${postman_install_dir}/app/resources/app/assets/icon.png"
sleek_version=2.0.26
sleek_url="https://github.com/ransome1/sleek/releases/download/v${sleek_version}/sleek-${sleek_version}-linux-amd64.deb"
sleek_sha256=f2531c41b70c04bbafc27af83e195aa9268845a58d3ead4b58fa58b301223fcb
sleek_size=107065664
sleek_deb="${work_dir}/sleek-${sleek_version}-linux-amd64.deb"
zoom_deb="${work_dir}/zoom-latest.deb"
filen_deb="${work_dir}/filen-latest.deb"
discord_install_dir=/opt/discord
discord_desktop_file=/usr/share/applications/discord.desktop
tuta_appimage="${work_dir}/tutanota-desktop-linux.AppImage"
tuta_signature="${work_dir}/linux-sig.bin"
tuta_public_key=/usr/local/share/software/tuta/tutao-pub.pem
tuta_install_dir=/opt/tuta-mail
tuta_desktop_file=/usr/share/applications/tuta-mail.desktop
tuta_icon_file=/usr/share/icons/hicolor/512x512/apps/tuta-mail.png
ledger_requested_latest_url=https://download.live.ledger.com/latest/linux
ledger_metadata_url=https://download.live.ledger.com/latest-linux.yml
ledger_metadata="${work_dir}/ledger-latest-linux.yml"
ledger_appimage="${work_dir}/ledger-live-linux-x86_64.AppImage"
ledger_checksums="${work_dir}/ledger-live.sha512sum"
ledger_checksums_signature="${work_dir}/ledger-live.sha512sum.sig"
ledger_public_key=/usr/local/share/software/ledger/ledgerlive.pem
ledger_install_dir=/opt/ledger-live
ledger_desktop_file=/usr/share/applications/ledger-live.desktop
ledger_icon_file=/usr/share/icons/hicolor/512x512/apps/ledger-live-desktop.png
ledger_udev_rules=/etc/udev/rules.d/53-ledger-wallet.rules
software_state_dir=/var/lib/software
software_event_dir="${software_state_dir}/events"
software_deb_archive_dir="${software_state_dir}/debs"
software_artifact_dir="${software_state_dir}/artifacts"
software_vendor_dir="${software_state_dir}/vendor"
software_postman_artifact_dir="${software_artifact_dir}/postman"
software_discord_artifact_dir="${software_artifact_dir}/discord"
software_tuta_artifact_dir="${software_artifact_dir}/tuta"
software_ledger_artifact_dir="${software_artifact_dir}/ledger"
software_metadata_dir="${software_state_dir}/state"
chatgpt_enable_file="${software_metadata_dir}/chatgpt.enabled"
chatgpt_canonical_dir=/usr/local/share/software/chatgpt
chatgpt_canonical_default="${chatgpt_canonical_dir}/default"
chatgpt_canonical_desktop="${chatgpt_canonical_dir}/chatgpt.desktop"
chatgpt_canonical_apparmor="${chatgpt_canonical_dir}/apparmor.profile"
chatgpt_canonical_icon="${chatgpt_canonical_dir}/chatgpt.png"
chatgpt_launcher=/usr/local/bin/chatgpt
chatgpt_log_runner=/usr/local/libexec/labwc-chatgpt-log-runner
chatgpt_log_socket_helper=/usr/local/libexec/rsyslog-managed-openai-socket
chatgpt_default=/etc/default/chatgpt
chatgpt_desktop=/usr/share/applications/chatgpt.desktop
chatgpt_apparmor=/etc/apparmor.d/chatgpt
chatgpt_icon=/usr/share/pixmaps/chatgpt.png
chatgpt_rsyslog_config=/etc/rsyslog.d/38-openai-chatgpt.conf
chatgpt_rsyslog_dropin=/etc/systemd/system/rsyslog.service.d/35-managed-openai-chatgpt-socket.conf
chatgpt_tmpfiles=/etc/tmpfiles.d/61-managed-openai-chatgpt.conf
chatgpt_logrotate=/etc/logrotate.d/chatgpt
chatgpt_runtime_logrotate=/etc/logrotate.d/chatgpt-runtime
chatgpt_vendor_source=/etc/apt/sources.list.d/chatgpt.sources
chatgpt_vendor_legacy_source=/etc/apt/sources.list.d/chatgpt.list
chatgpt_vendor_keyring=/usr/share/keyrings/chatgpt-archive-keyring.gpg
software_deb_repository_release="${software_deb_archive_dir}/Release"
software_deb_repository_inrelease="${software_deb_archive_dir}/InRelease"
software_deb_repository_release_gpg="${software_deb_archive_dir}/Release.gpg"
software_deb_repository_signing_home="${software_state_dir}/repository-signing"
software_deb_repository_apt_tmp="${software_state_dir}/apt-tmp"
software_deb_repository_keyring=/etc/apt/keyrings/managed-external-software.gpg
software_deb_repository_source=/etc/apt/sources.list.d/managed-external-software.list
postman_state_file="${software_metadata_dir}/postman.installed"
tuta_hash_file="${software_metadata_dir}/tuta.installed.sha256"
ledger_hash_file="${software_metadata_dir}/ledger.installed.sha512"
ledger_version_file="${software_metadata_dir}/ledger.installed.version"
software_update_helper=/usr/local/libexec/managed-external-software-update
software_discord_archive_helper=/usr/local/libexec/managed-discord-distro
software_notify_helper=/usr/local/libexec/managed-external-software-notify
software_download_service=/etc/systemd/system/managed-external-software-download.service
software_download_timer=/etc/systemd/system/managed-external-software-download.timer
software_update_service=/etc/systemd/system/managed-external-software-update.service
software_update_timer=/etc/systemd/system/managed-external-software-update.timer
software_notify_service=/etc/skel-desktop/.config/systemd/user/managed-external-software-notify.service
software_notify_path=/etc/skel-desktop/.config/systemd/user/managed-external-software-notify.path
temporary_unshare_hook=/usr/lib/pre-pkgsel.d/89temporary-unshare
temporary_unshare_path=/usr/bin/unshare
temporary_unshare_divert_path=/usr/bin/unshare.installer-real
temporary_unshare_state_path=/var/lib/installer-state/temporary-unshare-shim
temporary_unshare_marker=INSTALLER_TEMPORARY_FAKE_UNSHARE_V1
managed_application_minimum_bytes=1048576

: "${SOFTWARE_QOREDB_VERSION:?SOFTWARE_QOREDB_VERSION must be set by every desktop host profile}"
: "${SOFTWARE_QOREDB_URL:?SOFTWARE_QOREDB_URL must be set by every desktop host profile}"
: "${SOFTWARE_QOREDB_SHA256:?SOFTWARE_QOREDB_SHA256 must be set by every desktop host profile}"
: "${SOFTWARE_QOREDB_BYTES:?SOFTWARE_QOREDB_BYTES must be set by every desktop host profile}"
software_validate_release_version SOFTWARE_QOREDB_VERSION "$SOFTWARE_QOREDB_VERSION"
software_validate_sha256 SOFTWARE_QOREDB_SHA256 "$SOFTWARE_QOREDB_SHA256"
software_validate_bounded_bytes SOFTWARE_QOREDB_BYTES "$SOFTWARE_QOREDB_BYTES" 536870912
[ "$SOFTWARE_QOREDB_URL" = "https://github.com/QoreDB/QoreDB/releases/download/v${SOFTWARE_QOREDB_VERSION}/QoreDB_${SOFTWARE_QOREDB_VERSION}_amd64.deb" ] ||
  software_fatal "SOFTWARE_QOREDB_URL does not match the pinned QoreDB release"
qoredb_deb="${work_dir}/QoreDB_${SOFTWARE_QOREDB_VERSION}_amd64.deb"

software_validate_managed_app_default_exec() {
  managed_exec_value=$1

  case "$managed_exec_value" in
    ''|*'
'*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._+@%=:,/\ -]*)
      software_fatal "LABWC_MANAGED_APP_DEFAULT_EXEC contains unsupported command syntax"
      ;;
  esac
  old_ifs=$IFS
  IFS=' '
  # shellcheck disable=SC2086
  set -- $managed_exec_value
  IFS=$old_ifs
  [ "$#" -eq 2 ] ||
    software_fatal "LABWC_MANAGED_APP_DEFAULT_EXEC must contain the managed wrapper path and one mode"
  [ "$managed_exec_value" = "$1 $2" ] ||
    software_fatal "LABWC_MANAGED_APP_DEFAULT_EXEC must use one canonical space between the wrapper path and mode"
  [ "$1" = /usr/local/bin/labwc-managed-app ] ||
    software_fatal "LABWC_MANAGED_APP_DEFAULT_EXEC must use /usr/local/bin/labwc-managed-app"
  case "$2" in
    launch|intel|nvidia|pure-privacy) ;;
    *) software_fatal "LABWC_MANAGED_APP_DEFAULT_EXEC uses an unsupported managed app mode: $2" ;;
  esac
}

: "${LABWC_MANAGED_APP_DEFAULT_EXEC:?LABWC_MANAGED_APP_DEFAULT_EXEC must be set by the desktop host profile}"
software_validate_managed_app_default_exec "$LABWC_MANAGED_APP_DEFAULT_EXEC"

for managed_path in \
  "$work_dir" \
  "$bitwarden_deb" \
  "$qoredb_deb" \
  "$obsidian_deb" \
  "$postman_archive" \
  "$postman_member_list" \
  "$postman_verbose_list" \
  "$postman_install_dir" \
  "$postman_desktop_file" \
  "$postman_icon_file" \
  "$sleek_deb" \
  "$zoom_deb" \
  "$filen_deb" \
  "$discord_install_dir" \
  "$discord_desktop_file" \
  "$tuta_appimage" \
  "$tuta_signature" \
  "$tuta_public_key" \
  "$tuta_install_dir" \
  "$tuta_desktop_file" \
  "$tuta_icon_file" \
  "$ledger_metadata" \
  "$ledger_appimage" \
  "$ledger_checksums" \
  "$ledger_checksums_signature" \
  "$ledger_public_key" \
  "$ledger_install_dir" \
  "$ledger_desktop_file" \
  "$ledger_icon_file" \
  "$ledger_udev_rules" \
  "$software_state_dir" \
  "$software_event_dir" \
  "$software_deb_archive_dir" \
  "$software_artifact_dir" \
  "$software_vendor_dir" \
  "$software_postman_artifact_dir" \
  "$software_discord_artifact_dir" \
  "$software_tuta_artifact_dir" \
  "$software_ledger_artifact_dir" \
  "$software_metadata_dir" \
  "$chatgpt_enable_file" \
  "$chatgpt_canonical_dir" \
  "$chatgpt_canonical_default" \
  "$chatgpt_canonical_desktop" \
  "$chatgpt_canonical_apparmor" \
  "$chatgpt_canonical_icon" \
  "$chatgpt_launcher" \
  "$chatgpt_log_runner" \
  "$chatgpt_log_socket_helper" \
  "$chatgpt_default" \
  "$chatgpt_desktop" \
  "$chatgpt_apparmor" \
  "$chatgpt_icon" \
  "$chatgpt_rsyslog_config" \
  "$chatgpt_rsyslog_dropin" \
  "$chatgpt_tmpfiles" \
  "$chatgpt_logrotate" \
  "$chatgpt_runtime_logrotate" \
  "$chatgpt_vendor_source" \
  "$chatgpt_vendor_legacy_source" \
  "$chatgpt_vendor_keyring" \
  "$software_deb_repository_release" \
  "$software_deb_repository_inrelease" \
  "$software_deb_repository_release_gpg" \
  "$software_deb_repository_signing_home" \
  "$software_deb_repository_apt_tmp" \
  "$software_deb_repository_keyring" \
  "$software_deb_repository_source" \
  "$postman_state_file" \
  "$tuta_hash_file" \
  "$ledger_hash_file" \
  "$ledger_version_file" \
  "$software_update_helper" \
  "$software_discord_archive_helper" \
  "$software_notify_helper" \
  "$software_download_service" \
  "$software_download_timer" \
  "$software_update_service" \
  "$software_update_timer" \
  "$software_notify_service" \
  "$software_notify_path"
do
  software_validate_abs_path "managed software path" "$managed_path"
done
unset managed_path

software_stage_seed_asset() {
  repo_path=$1
  target_path=$2
  mode=$3
  tmp_asset="${tmp_env_dir}/$(basename "$target_path").$$"
  target_host_path="${target_root}${target_path}"

  software_validate_abs_path "target asset path" "$target_path"
  bootstrap_fetch_seed_file "$seed_base" "$repo_path" "$tmp_asset" 0600 "software asset ${repo_path}"
  install -d -m 0755 "${target_root}$(dirname "$target_path")"
  install -m "$mode" "$tmp_asset" "$target_host_path"
  chmod "$mode" "$target_host_path"
  rm -f "$tmp_asset"
}

software_render_seed_asset() {
  repo_path=$1
  target_path=$2
  mode=$3
  shift 3
  tmp_asset="${tmp_env_dir}/$(basename "$target_path").$$.src"
  tmp_rendered="${tmp_env_dir}/$(basename "$target_path").$$.rendered"
  target_host_path="${target_root}${target_path}"

  software_validate_abs_path "target rendered asset path" "$target_path"
  [ $(( $# % 2 )) -eq 0 ] ||
    software_fatal "rendered software asset placeholders must be name/value pairs: ${repo_path}"
  bootstrap_fetch_seed_file "$seed_base" "$repo_path" "$tmp_asset" 0600 "software template ${repo_path}"
  installer_apply_scalar_placeholders "$tmp_asset" "$tmp_rendered" "$@" || {
    rm -f "$tmp_asset" "$tmp_rendered"
    software_fatal "failed to render software template: ${repo_path}"
  }
  if installer_contains_unresolved_installer_placeholders "$tmp_rendered"; then
    rm -f "$tmp_asset" "$tmp_rendered"
    software_fatal "rendered software template has unresolved installer placeholders: ${repo_path}"
  fi
  install -d -m 0755 "${target_root}$(dirname "$target_path")"
  install -m "$mode" "$tmp_rendered" "$target_host_path"
  chmod "$mode" "$target_host_path"
  rm -f "$tmp_asset" "$tmp_rendered"
}

software_managed_external_cpu_quota() {
  managed_external_online_cpus=$(
    chroot "$target_root" /usr/bin/getconf _NPROCESSORS_ONLN
  ) || software_fatal "managed external software CPU count is unavailable"
  case "$managed_external_online_cpus" in
    ''|*[!0-9]*) software_fatal "managed external software CPU count is invalid" ;;
  esac
  [ "$managed_external_online_cpus" -ge 1 ] ||
    software_fatal "managed external software CPU count must be positive"

  managed_external_quota_cpus=$((managed_external_online_cpus / 2))
  [ "$managed_external_quota_cpus" -ge 1 ] || managed_external_quota_cpus=1
  printf '%s00%%\n' "$managed_external_quota_cpus"
}

software_normalize_system_perl_module_parents() {
  for module_parent in \
    /usr/local/lib/perl5 \
    /usr/local/lib/perl5/site_perl \
    /usr/local/lib/perl5/site_perl/external-managed-software \
    /usr/local/lib/perl5/site_perl/external-managed-software/ExternalSoftware \
    /usr/local/lib/perl5/site_perl/external-managed-software/ExternalSoftware/Servicing
  do
    module_parent_host="${target_root}${module_parent}"
    [ ! -L "$module_parent_host" ] ||
      software_fatal "system Perl module parent is a symlink: ${module_parent}"
    install -d -m 0755 "$module_parent_host"
    chown root:root "$module_parent_host"
    chmod 0755 "$module_parent_host"
  done
}

software_perl_modules() {
  cat <<'EOF'
ExternalSoftware/Servicing/Atomic.pm
ExternalSoftware/Servicing/Bitwarden.pm
ExternalSoftware/Servicing/ChatGPT.pm
ExternalSoftware/Servicing/CLI.pm
ExternalSoftware/Servicing/Deb.pm
ExternalSoftware/Servicing/Discord.pm
ExternalSoftware/Servicing/Event.pm
ExternalSoftware/Servicing/HTTP.pm
ExternalSoftware/Servicing/Ledger.pm
ExternalSoftware/Servicing/Logger.pm
ExternalSoftware/Servicing/Notifier.pm
ExternalSoftware/Servicing/Obsidian.pm
ExternalSoftware/Servicing/Postman.pm
ExternalSoftware/Servicing/Process.pm
ExternalSoftware/Servicing/Repository.pm
ExternalSoftware/Servicing/Sleek.pm
ExternalSoftware/Servicing/State.pm
ExternalSoftware/Servicing/Tuta.pm
EOF
}

software_stage_perl_modules() {
  software_normalize_system_perl_module_parents
  software_perl_modules | while IFS= read -r software_module; do
    [ -n "$software_module" ] || continue
    software_stage_seed_asset \
      "$(installer_repo_join_var DIR_HOOKS_TARGET "usr/local/lib/perl5/site_perl/external-managed-software/${software_module}")" \
      "/usr/local/lib/perl5/site_perl/external-managed-software/${software_module}" \
      0644
  done
}

software_stage_external_servicing_runtime() {
  software_stage_perl_modules
  software_stage_seed_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/libexec/managed-external-software-update)" \
    "$software_update_helper" \
    0755
  software_stage_seed_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/libexec/managed-discord-distro)" \
    "$software_discord_archive_helper" \
    0755
}

software_enable_chatgpt_integration() {
  [ "$chatgpt_enabled" = true ] || return 0

  install -d -m 0755 \
    "${target_root}${software_state_dir}" \
    "${target_root}${software_deb_archive_dir}" \
    "${target_root}${software_metadata_dir}" \
    "${target_root}${software_vendor_dir}" \
    "${target_root}${chatgpt_canonical_dir}"
  chown root:root \
    "${target_root}${software_state_dir}" \
    "${target_root}${software_deb_archive_dir}" \
    "${target_root}${software_metadata_dir}" \
    "${target_root}${software_vendor_dir}" \
    "${target_root}${chatgpt_canonical_dir}"

  software_stage_seed_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/default/chatgpt)" \
    "$chatgpt_canonical_default" \
    0644
  software_stage_seed_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET usr/share/applications/chatgpt.desktop)" \
    "$chatgpt_canonical_desktop" \
    0644
  software_stage_seed_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/apparmor.d/chatgpt)" \
    "$chatgpt_canonical_apparmor" \
    0644
  software_stage_seed_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET usr/share/pixmaps/chatgpt.png)" \
    "$chatgpt_canonical_icon" \
    0644
  software_stage_seed_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/bin/chatgpt)" \
    "$chatgpt_launcher" \
    0755
  software_stage_seed_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/libexec/labwc-chatgpt-log-runner)" \
    "$chatgpt_log_runner" \
    0755
  software_stage_seed_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/libexec/rsyslog-managed-openai-socket)" \
    "$chatgpt_log_socket_helper" \
    0755
  software_stage_seed_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/rsyslog.d/38-openai-chatgpt.conf)" \
    "$chatgpt_rsyslog_config" \
    0644
  software_stage_seed_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/system/rsyslog.service.d/35-managed-openai-chatgpt-socket.conf)" \
    "$chatgpt_rsyslog_dropin" \
    0644
  software_render_seed_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/tmpfiles.d/61-managed-openai-chatgpt.conf.tmpl)" \
    "$chatgpt_tmpfiles" \
    0644 \
    ACCOUNT_USERNAME "$ACCOUNT_USERNAME"
  software_stage_seed_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/logrotate.d/chatgpt)" \
    "$chatgpt_logrotate" \
    0644
  software_render_seed_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/logrotate.d/chatgpt-runtime.tmpl)" \
    "$chatgpt_runtime_logrotate" \
    0644 \
    ACCOUNT_USERNAME "$ACCOUNT_USERNAME"

  # shellcheck disable=SC2016
  run_in_target "configure managed ChatGPT log transport access" /bin/sh -eu -c '
account_user=$1
writer_group=openailogger

for command_name in getent groupadd id usermod; do
  command -v "$command_name" >/dev/null 2>&1 || {
    printf "fatal: required ChatGPT logging command is missing: %s\n" "$command_name" >&2
    exit 1
  }
done

getent passwd "$account_user" >/dev/null
getent group "$writer_group" >/dev/null 2>&1 ||
  groupadd --system "$writer_group"
usermod -a -G "$writer_group" "$account_user"
case " $(id -nG "$account_user") " in
  *" $writer_group "*) ;;
  *)
    printf "fatal: ChatGPT account was not added to %s: %s\n" "$writer_group" "$account_user" >&2
    exit 1
    ;;
esac
' sh "$ACCOUNT_USERNAME"

  run_in_target \
    "create protected managed ChatGPT log paths" \
    /usr/bin/systemd-tmpfiles \
    --create \
    /etc/tmpfiles.d/65-audit-syslog.conf \
    "$chatgpt_tmpfiles"
  # shellcheck disable=SC2016
  run_in_target "verify managed ChatGPT log path policy" /bin/sh -eu -c '
chatgpt_fatal() {
  printf "fatal: %s\n" "$*" >&2
  exit 1
}

chatgpt_verify_stat() {
  expected=$1
  path=$2
  actual=$(stat -c "%u:%g:%a" -- "$path")
  [ "$actual" = "$expected" ] ||
    chatgpt_fatal "unexpected ownership or mode for ${path}: expected ${expected}, found ${actual}"
}

account_user=$1
for required_command in awk getent id runuser stat; do
  command -v "$required_command" >/dev/null 2>&1 ||
    chatgpt_fatal "required ChatGPT log-policy command is unavailable: $required_command"
done

account_uid=$(id -u "$account_user")
adm_gid=$(getent group adm | awk -F: "{ print \$3; exit }")
writer_gid=$(getent group openailogger | awk -F: "{ print \$3; exit }")
case "$account_uid:$adm_gid:$writer_gid" in
  *[!0123456789:]*|:*|*:) chatgpt_fatal "unable to resolve ChatGPT log-policy ids" ;;
esac

chatgpt_verify_stat "0:${adm_gid}:751" /var/log/managed
chatgpt_verify_stat "0:${adm_gid}:751" /var/log/managed/openai
chatgpt_verify_stat "0:${adm_gid}:751" /var/log/managed/openai/chatgpt
chatgpt_verify_stat "${account_uid}:${writer_gid}:2770" /var/log/managed/openai/chatgpt/runtime
chatgpt_verify_stat "${account_uid}:${writer_gid}:660" /var/log/managed/openai/chatgpt/runtime/codex-login.log
chatgpt_verify_stat "${account_uid}:${writer_gid}:660" /var/log/managed/openai/chatgpt/runtime/codex-tui.log
chatgpt_verify_stat "0:${adm_gid}:640" /var/log/managed/openai/chatgpt/chatgpt.log
/usr/sbin/runuser -u "$account_user" -- \
  /usr/bin/test ! -w /var/log/managed/openai/chatgpt ||
  chatgpt_fatal "managed desktop account can unexpectedly modify the protected ChatGPT log directory"
/usr/sbin/runuser -u "$account_user" -- \
  /usr/bin/test -w /var/log/managed/openai/chatgpt/runtime ||
  chatgpt_fatal "managed desktop account cannot write the ChatGPT sandbox log directory"
' sh "$ACCOUNT_USERNAME"
  run_in_target \
    "validate managed ChatGPT rsyslog routing" \
    /usr/sbin/rsyslogd \
    -N1 \
    -f \
    /etc/rsyslog.conf
  run_in_target \
    "validate managed ChatGPT log rotation" \
    /usr/sbin/logrotate \
    --debug \
    /etc/logrotate.conf

  chatgpt_enable_tmp="${target_root}${chatgpt_enable_file}.tmp.$$"
  [ ! -L "${target_root}${chatgpt_enable_file}" ] ||
    software_fatal "ChatGPT enable marker must not be a symlink"
  printf '%s\n' 'addon/devops' >"$chatgpt_enable_tmp"
  chown root:root "$chatgpt_enable_tmp"
  chmod 0644 "$chatgpt_enable_tmp"
  mv -f -- "$chatgpt_enable_tmp" "${target_root}${chatgpt_enable_file}"

  run_in_target \
    "download, retain, and install the managed ChatGPT/Codex desktop package" \
    "$software_update_helper" \
    --bootstrap-chatgpt

  chatgpt_status=$(
    chroot "$target_root" /usr/bin/dpkg-query \
      -W \
      -f='${Status}' \
      chatgpt 2>/dev/null || true
  )
  [ "$chatgpt_status" = 'install ok installed' ] ||
    software_fatal "managed ChatGPT package is not fully installed"
  for chatgpt_required_path in \
    /usr/bin/chatgpt \
    /usr/bin/slirp4netns \
    /usr/lib/chatgpt/ChatGPT \
    /usr/lib/chatgpt/codex-launcher \
    /usr/lib/chatgpt/resources/codex \
    /usr/lib/chatgpt/resources/codex-code-mode-host \
    "$chatgpt_icon" \
    "$chatgpt_launcher" \
    "$chatgpt_log_runner" \
    "$chatgpt_log_socket_helper" \
    "$chatgpt_default" \
    "$chatgpt_desktop" \
    "$chatgpt_apparmor" \
    "$chatgpt_rsyslog_config" \
    "$chatgpt_rsyslog_dropin" \
    "$chatgpt_tmpfiles" \
    "$chatgpt_logrotate" \
    "$chatgpt_runtime_logrotate"
  do
    chroot "$target_root" /usr/bin/test -e "$chatgpt_required_path" ||
      software_fatal "managed ChatGPT path is missing after bootstrap: $chatgpt_required_path"
  done
  unset chatgpt_required_path
  for chatgpt_forbidden_path in \
    "$chatgpt_vendor_source" \
    "$chatgpt_vendor_legacy_source" \
    "$chatgpt_vendor_keyring"
  do
    if [ -e "${target_root}${chatgpt_forbidden_path}" ] ||
       [ -L "${target_root}${chatgpt_forbidden_path}" ]; then
      software_fatal "ChatGPT vendor repository artifact remains active: $chatgpt_forbidden_path"
    fi
  done
  unset chatgpt_forbidden_path
  chroot "$target_root" /usr/bin/desktop-file-validate "$chatgpt_desktop"
  software_info "installed managed ChatGPT/Codex desktop through the signed local repository"
}

software_restore_managed_apparmor_profiles() {
  for profile_name in \
    opt.Bitwarden.bitwarden \
    usr.bin.qoredb \
    obsidian \
    opt.postman.app.Postman \
    sleek \
    usr.bin.zoom \
    opt.Filen.Filen \
    Discord \
    opt.ledger-live.AppRun \
    opt.tuta-mail.AppRun
  do
    software_stage_seed_asset \
      "$(installer_repo_join_var DIR_HOOKS_TARGET "etc/apparmor.d/${profile_name}")" \
      "/etc/apparmor.d/${profile_name}" \
      0644
  done
  unset profile_name
}

software_https_url_host() {
  url=$1

  case "$url" in
    https://*) authority=${url#https://} ;;
    *) return 1 ;;
  esac
  authority=${authority%%/*}
  case "$authority" in
    ''|*@*|*\?*|*\#*|*\[*|*\]*) return 1 ;;
  esac

  host=${authority%%:*}
  if [ "$authority" != "$host" ]; then
    port=${authority#*:}
    [ "$port" = 443 ] || return 1
  fi
  host=$(printf '%s' "$host" | tr 'ABCDEFGHIJKLMNOPQRSTUVWXYZ' 'abcdefghijklmnopqrstuvwxyz')
  case "$host" in
    ''|.*|*.|*..*|*[!abcdefghijklmnopqrstuvwxyz0123456789.-]*) return 1 ;;
  esac
  printf '%s\n' "$host"
}

software_require_allowed_https_url() {
  label=$1
  url=$2
  allowed_hosts=$3

  url_host=$(software_https_url_host "$url" 2>/dev/null || true)
  [ -n "$url_host" ] ||
    software_fatal "$label URL is not a supported HTTPS URL: ${url:-unset}"
  case " $allowed_hosts " in
    *" $url_host "*) return 0 ;;
  esac
  software_fatal "$label URL resolved to an unapproved host: $url_host"
}

software_download() {
  label=$1
  url=$2
  destination=$3
  minimum_bytes=$4
  maximum_bytes=$5
  content_policy=${6:-artifact}
  allowed_hosts=${7:-}
  transport_policy=${8:-fatal}
  partial_destination="${destination}.part"
  destination_host_path="${target_root}${destination}"
  partial_host_path="${target_root}${partial_destination}"

  case "$content_policy" in
    artifact|metadata) ;;
    *) software_fatal "$label content policy is unsupported: $content_policy" ;;
  esac
  case "$transport_policy" in
    fatal|defer) ;;
    *) software_fatal "$label transport policy is unsupported: $transport_policy" ;;
  esac
  if [ -n "$allowed_hosts" ]; then
    software_require_allowed_https_url "$label" "$url" "$allowed_hosts"
  else
    case "$url" in
      https://*) ;;
      *) software_fatal "$label download URL must use HTTPS: $url" ;;
    esac
  fi
  software_validate_abs_path "$label destination" "$destination"
  software_validate_abs_path "$label partial destination" "$partial_destination"
  rm -f -- "$destination_host_path" "$partial_host_path"

  if ! transfer_metadata=$(
    chroot "$target_root" /usr/bin/env -i \
      HOME=/root \
      LC_ALL=C \
      PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
      /usr/bin/curl \
        --fail \
        --silent \
        --show-error \
        --location \
        --proto '=https' \
        --proto-redir '=https' \
        --connect-timeout 15 \
        --max-time 300 \
        --max-redirs 8 \
        --retry 3 \
        --retry-all-errors \
        --max-filesize "$maximum_bytes" \
        --user-agent 'unattended-installer-software/1.0' \
        --header 'Accept: application/octet-stream, application/vnd.debian.binary-package;q=0.9, */*;q=0.1' \
        --output "$partial_destination" \
        --write-out '%{http_code}\n%{url_effective}\n%{content_type}' \
        --url "$url"
  ); then
    rm -f -- "$partial_host_path"
    if [ "$transport_policy" = defer ]; then
      software_warn "$label download failed; deferring this application to the managed post-boot updater"
      return 1
    fi
    software_fatal "$label download failed"
  fi

  http_status=$(printf '%s\n' "$transfer_metadata" | sed -n '1p')
  effective_url=$(printf '%s\n' "$transfer_metadata" | sed -n '2p')
  content_type=$(printf '%s\n' "$transfer_metadata" | sed -n '3p')
  case "$http_status" in
    200|206) ;;
    *) software_fatal "$label download returned unexpected HTTP status: ${http_status:-unset}" ;;
  esac
  case "$effective_url" in
    https://*) ;;
    *) software_fatal "$label download resolved to a non-HTTPS URL: ${effective_url:-unset}" ;;
  esac
  if [ -n "$allowed_hosts" ]; then
    software_require_allowed_https_url "$label effective" "$effective_url" "$allowed_hosts"
  fi
  normalized_content_type=$(printf '%s' "$content_type" | tr 'ABCDEFGHIJKLMNOPQRSTUVWXYZ' 'abcdefghijklmnopqrstuvwxyz')
  normalized_content_type=${normalized_content_type%%;*}
  case "$content_policy:$normalized_content_type" in
    artifact:text/html|artifact:text/plain|artifact:text/xml|artifact:application/json|artifact:application/xml)
      software_fatal "$label download returned a non-artifact content type: $normalized_content_type"
      ;;
    metadata:|metadata:application/octet-stream|metadata:binary/octet-stream|metadata:text/plain|metadata:application/yaml|metadata:application/x-yaml|metadata:text/yaml|metadata:text/x-yaml)
      ;;
    metadata:*)
      software_fatal "$label download returned an unsupported metadata content type: $normalized_content_type"
      ;;
  esac

  [ -f "$partial_host_path" ] && [ ! -L "$partial_host_path" ] ||
    software_fatal "$label download is not a regular file"
  destination_size=$(wc -c <"$partial_host_path" | awk '{print $1}')
  case "$destination_size" in
    ''|*[!0-9]*) software_fatal "$label download size is invalid: ${destination_size:-unset}" ;;
  esac
  [ "$destination_size" -ge "$minimum_bytes" ] ||
    software_fatal "$label download is unexpectedly small: ${destination_size} bytes"
  [ "$destination_size" -le "$maximum_bytes" ] ||
    software_fatal "$label download is unexpectedly large: ${destination_size} bytes"
  mv -f -- "$partial_host_path" "$destination_host_path"
  software_info "resolved ${label} download effective_url=${effective_url} http_status=${http_status} content_type=${normalized_content_type:-unset} bytes=${destination_size}"
}

software_parse_ledger_metadata() {
  metadata_host_path="${target_root}${ledger_metadata}"

  [ "$(grep -c '^version: ' "$metadata_host_path")" -eq 1 ] ||
    software_fatal "Ledger release metadata must contain exactly one version"
  [ "$(grep -c '^path: ' "$metadata_host_path")" -eq 1 ] ||
    software_fatal "Ledger release metadata must contain exactly one release path"
  [ "$(grep -c '^sha512: ' "$metadata_host_path")" -eq 1 ] ||
    software_fatal "Ledger release metadata must contain exactly one release SHA-512"
  [ "$(grep -c '^    size: ' "$metadata_host_path")" -eq 1 ] ||
    software_fatal "Ledger release metadata must contain exactly one release size"

  ledger_version=$(sed -n 's/^version: //p' "$metadata_host_path")
  ledger_filename=$(sed -n 's/^path: //p' "$metadata_host_path")
  ledger_metadata_sha512=$(sed -n 's/^sha512: //p' "$metadata_host_path")
  ledger_metadata_size=$(sed -n 's/^    size: //p' "$metadata_host_path")

  case "$ledger_version" in
    ''|.*|*.|*..*|*[!0123456789.]*)
      software_fatal "Ledger release metadata has an invalid version: ${ledger_version:-unset}"
      ;;
  esac
  [ "${#ledger_version}" -le 32 ] ||
    software_fatal "Ledger release metadata version is too long"
  [ "$ledger_filename" = "ledger-live-desktop-${ledger_version}-linux-x86_64.AppImage" ] ||
    software_fatal "Ledger release metadata has an unexpected AppImage path: ${ledger_filename:-unset}"
  case "$ledger_metadata_sha512" in
    ''|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=]*)
      software_fatal "Ledger release metadata SHA-512 is invalid"
      ;;
  esac
  [ "${#ledger_metadata_sha512}" -eq 88 ] ||
    software_fatal "Ledger release metadata SHA-512 has an unexpected length"
  ledger_metadata_digest_bytes=$(
    printf '%s' "$ledger_metadata_sha512" |
      chroot "$target_root" /usr/bin/openssl base64 -d -A 2>/dev/null |
      wc -c |
      awk '{print $1}'
  )
  [ "$ledger_metadata_digest_bytes" = 64 ] ||
    software_fatal "Ledger release metadata SHA-512 does not decode to 64 bytes"
  case "$ledger_metadata_size" in
    ''|*[!0-9]*) software_fatal "Ledger release metadata size is invalid" ;;
  esac
  [ "$ledger_metadata_size" -ge 104857600 ] &&
    [ "$ledger_metadata_size" -le 536870912 ] ||
    software_fatal "Ledger release metadata size is outside the approved range: $ledger_metadata_size"

  ledger_checksums_url="https://resources.live.ledger.app/public_resources/signatures/ledger-live-desktop-${ledger_version}.sha512sum"
  ledger_checksums_signature_url="${ledger_checksums_url}.sig"
}

software_ledger_signed_sha512() {
  checksums_host_path="${target_root}${ledger_checksums}"

  awk -v wanted="$ledger_filename" '
    $2 == wanted {
      count += 1
      hash = $1
    }
    END {
      if (count != 1 || length(hash) != 128 || hash !~ /^[0-9a-f]+$/) {
        exit 1
      }
      print hash
    }
  ' "$checksums_host_path"
}

software_deb_contains_path() {
  deb_path=$1
  expected_path=$2

  case "$expected_path" in
    /*) expected_path=${expected_path#/} ;;
    *) return 1 ;;
  esac

  # dpkg-deb preserves the data archive's member spelling.  Valid packages
  # may list either usr/bin/tool or ./usr/bin/tool, so compare one canonical
  # relative path while retaining field 6 as the source member for symlinks.
  chroot "$target_root" /usr/bin/env -i \
    LC_ALL=C \
    PATH=/usr/bin:/bin \
    /usr/bin/dpkg-deb -c "$deb_path" 2>/dev/null |
    awk -v wanted="$expected_path" '
      {
        archive_path = $6
        sub(/^[.]\//, "", archive_path)
        if (archive_path == wanted) {
          found = 1
        }
      }
      END { exit found ? 0 : 1 }
    '
}

software_validate_deb_archive_component() {
  label=$1
  value=$2

  [ "${#value}" -le 128 ] ||
    software_fatal "$label exceeds 128 characters"
  case "$value" in
    ''|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.+:~_-]*)
      software_fatal "$label contains unsupported archive-path characters: ${value:-unset}"
      ;;
  esac
}

software_managed_deb_archive_path() {
  package_name=$1
  package_version=$2
  package_architecture=$3

  software_validate_deb_archive_component "managed package name" "$package_name"
  software_validate_deb_archive_component "managed package version" "$package_version"
  [ "$package_architecture" = amd64 ] ||
    software_fatal "managed package archive has unsupported architecture: ${package_architecture:-unset}"

  printf '%s/%s_%s_%s.deb\n' \
    "$software_deb_archive_dir" \
    "$package_name" \
    "$package_version" \
    "$package_architecture"
}

software_managed_deb_repository_codename() {
  repository_codename=$(
    chroot "$target_root" /usr/bin/awk -F= \
      '$1 == "VERSION_CODENAME" { print $2; exit }' \
      /etc/os-release 2>/dev/null || true
  )
  case "$repository_codename" in
    \"*\")
      repository_codename=${repository_codename#\"}
      repository_codename=${repository_codename%\"}
      ;;
  esac
  software_validate_deb_archive_component \
    "managed package repository codename" \
    "$repository_codename"
  printf '%s\n' "$repository_codename"
}

software_managed_deb_repository_gpg() {
  chroot "$target_root" /usr/bin/env -i \
    GNUPGHOME="$software_deb_repository_signing_home" \
    HOME="$software_deb_repository_signing_home" \
    LC_ALL=C.UTF-8 \
    PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    /usr/bin/gpg \
      --batch \
      --no-options \
      --homedir "$software_deb_repository_signing_home" \
      "$@"
}

software_managed_deb_repository_fingerprint() {
  key_listing=$(software_managed_deb_repository_gpg \
    --with-colons \
    --list-secret-keys 2>/dev/null) ||
    software_fatal "managed repository signing key inventory failed"
  key_count=$(
    printf '%s\n' "$key_listing" |
      awk -F: '$1 == "sec" { count++ } END { print count + 0 }'
  )
  key_fingerprint=$(
    printf '%s\n' "$key_listing" |
      awk -F: '
        $1 == "sec" {
          want_fingerprint = 1
          next
        }
        want_fingerprint && $1 == "fpr" {
          print toupper($10)
          exit
        }
      '
  )
  [ "$key_count" -eq 1 ] ||
    software_fatal "managed repository signing home must contain exactly one secret key"
  case "$key_fingerprint" in
    ''|*[!0123456789ABCDEF]*)
      software_fatal "managed repository signing key fingerprint is invalid"
      ;;
  esac
  case "${#key_fingerprint}" in
    40|64) ;;
    *) software_fatal "managed repository signing key fingerprint has an invalid length" ;;
  esac
  printf '%s\n' "$key_fingerprint"
}

software_target_file_owner() {
  target_path=$1

  software_validate_abs_path "target file ownership path" "$target_path"
  chroot "$target_root" /usr/bin/stat -c '%u:%g' -- "$target_path" 2>/dev/null
}

software_prepare_managed_repository_generated_path() {
  generated_path=$1
  generated_host_path="${target_root}${generated_path}"

  software_validate_abs_path "managed repository generated path" "$generated_path"
  if [ -e "$generated_host_path" ] || [ -L "$generated_host_path" ]; then
    [ -f "$generated_host_path" ] && [ ! -L "$generated_host_path" ] ||
      software_fatal "managed repository generated path is unsafe: $generated_path"
    generated_owner=$(software_target_file_owner "$generated_path") ||
      software_fatal "managed repository generated path metadata is unavailable: $generated_path"
    [ "$generated_owner" = 0:0 ] ||
      software_fatal "managed repository generated path is not root-owned: $generated_path"
    rm -f -- "$generated_host_path"
  fi
}

software_publish_managed_repository_file() {
  generated_path=$1
  destination_path=$2
  destination_mode=$3
  maximum_bytes=$4
  generated_host_path="${target_root}${generated_path}"
  destination_host_path="${target_root}${destination_path}"

  software_validate_abs_path "managed repository generated file" "$generated_path"
  software_validate_abs_path "managed repository destination file" "$destination_path"
  [ -f "$generated_host_path" ] && [ ! -L "$generated_host_path" ] ||
    software_fatal "managed repository generated file is unavailable: $generated_path"
  generated_owner=$(software_target_file_owner "$generated_path") ||
    software_fatal "managed repository generated file metadata is unavailable: $generated_path"
  [ "$generated_owner" = 0:0 ] ||
    software_fatal "managed repository generated file is not root-owned: $generated_path"
  generated_size=$(wc -c <"$generated_host_path" | awk '{print $1}')
  case "$generated_size" in
    ''|*[!0123456789]*)
      software_fatal "managed repository generated file size is invalid: $generated_path"
      ;;
  esac
  [ "$generated_size" -ge 1 ] && [ "$generated_size" -le "$maximum_bytes" ] ||
    software_fatal "managed repository generated file exceeds its size bounds: $generated_path"
  if [ -e "$destination_host_path" ] || [ -L "$destination_host_path" ]; then
    [ -f "$destination_host_path" ] && [ ! -L "$destination_host_path" ] ||
      software_fatal "managed repository destination is unsafe: $destination_path"
    destination_owner=$(software_target_file_owner "$destination_path") ||
      software_fatal "managed repository destination metadata is unavailable: $destination_path"
    [ "$destination_owner" = 0:0 ] ||
      software_fatal "managed repository destination is not root-owned: $destination_path"
  fi
  chmod "$destination_mode" "$generated_host_path"
  mv -f -- "$generated_host_path" "$destination_host_path"
}

software_ensure_managed_deb_repository_signing_key() {
  signing_home_host="${target_root}${software_deb_repository_signing_home}"
  keyring_directory=$(dirname "$software_deb_repository_keyring")
  keyring_directory_host="${target_root}${keyring_directory}"

  [ ! -L "$signing_home_host" ] ||
    software_fatal "managed repository signing home must not be a symlink"
  [ ! -L "$keyring_directory_host" ] ||
    software_fatal "managed repository keyring directory must not be a symlink"
  install -d -m 0700 "$signing_home_host"
  install -d -m 0755 "$keyring_directory_host"
  chown root:root "$signing_home_host" "$keyring_directory_host"
  chmod 0700 "$signing_home_host"
  chmod 0755 "$keyring_directory_host"

  key_listing=$(software_managed_deb_repository_gpg \
    --with-colons \
    --list-secret-keys 2>/dev/null) ||
    software_fatal "managed repository signing key inventory failed"
  key_count=$(
    printf '%s\n' "$key_listing" |
      awk -F: '$1 == "sec" { count++ } END { print count + 0 }'
  )
  case "$key_count" in
    0)
      software_managed_deb_repository_gpg \
        --pinentry-mode loopback \
        --passphrase '' \
        --quick-generate-key \
        'Managed External Software Repository <managed-external-software@localhost>' \
        ed25519 \
        sign \
        0 >/dev/null 2>&1 ||
        software_fatal "managed repository signing key generation failed"
      ;;
    1) ;;
    *) software_fatal "managed repository signing home contains multiple secret keys" ;;
  esac

  key_fingerprint=$(software_managed_deb_repository_fingerprint)
  keyring_tmp="${software_deb_repository_keyring}.tmp.$$"
  software_prepare_managed_repository_generated_path "$keyring_tmp"
  software_managed_deb_repository_gpg \
    --output "$keyring_tmp" \
    --export-options export-minimal \
    --export "$key_fingerprint" >/dev/null 2>&1 ||
    software_fatal "managed repository public key export failed"
  software_publish_managed_repository_file \
    "$keyring_tmp" \
    "$software_deb_repository_keyring" \
    0644 \
    1048576
  printf '%s\n' "$key_fingerprint"
}

software_sign_managed_deb_repository() {
  [ -f "${target_root}${software_deb_repository_release}" ] &&
    [ ! -L "${target_root}${software_deb_repository_release}" ] ||
    software_fatal "managed repository Release file is unavailable for signing"
  key_fingerprint=$(software_ensure_managed_deb_repository_signing_key)
  inrelease_tmp="${software_deb_repository_inrelease}.tmp.$$"
  release_gpg_tmp="${software_deb_repository_release_gpg}.tmp.$$"
  software_prepare_managed_repository_generated_path "$inrelease_tmp"
  software_prepare_managed_repository_generated_path "$release_gpg_tmp"

  software_managed_deb_repository_gpg \
    --yes \
    --local-user "$key_fingerprint" \
    --output "$inrelease_tmp" \
    --clearsign "$software_deb_repository_release" >/dev/null 2>&1 ||
    software_fatal "managed repository InRelease signing failed"
  software_managed_deb_repository_gpg \
    --yes \
    --local-user "$key_fingerprint" \
    --armor \
    --output "$release_gpg_tmp" \
    --detach-sign "$software_deb_repository_release" >/dev/null 2>&1 ||
    software_fatal "managed repository detached signing failed"
  chroot "$target_root" /usr/bin/gpgv \
    --quiet \
    --keyring "$software_deb_repository_keyring" \
    "$inrelease_tmp" >/dev/null 2>&1 ||
    software_fatal "managed repository InRelease verification failed"
  chroot "$target_root" /usr/bin/gpgv \
    --quiet \
    --keyring "$software_deb_repository_keyring" \
    "$release_gpg_tmp" \
    "$software_deb_repository_release" >/dev/null 2>&1 ||
    software_fatal "managed repository Release signature verification failed"

  software_publish_managed_repository_file \
    "$release_gpg_tmp" \
    "$software_deb_repository_release_gpg" \
    0644 \
    1048576
  software_publish_managed_repository_file \
    "$inrelease_tmp" \
    "$software_deb_repository_inrelease" \
    0644 \
    2097152
}

software_store_managed_deb_archive() {
  label=$1
  deb_path=$2
  package_name=$3
  package_version=$4
  package_architecture=$5
  archive_path=$(software_managed_deb_archive_path \
    "$package_name" \
    "$package_version" \
    "$package_architecture")
  archive_host_path="${target_root}${archive_path}"
  archive_tmp="${archive_host_path}.tmp.$$"

  software_validate_abs_path "$label managed package archive" "$archive_path"
  [ -f "${target_root}${deb_path}" ] && [ ! -L "${target_root}${deb_path}" ] ||
    software_fatal "$label package is unavailable for managed archive retention"
  if [ -e "$archive_host_path" ] && [ ! -f "$archive_host_path" ]; then
    software_fatal "$label managed package archive path is not a regular file: $archive_path"
  fi

  install -d -m 0755 "${target_root}${software_deb_archive_dir}"
  install -m 0644 "${target_root}${deb_path}" "$archive_tmp"
  chroot "$target_root" /usr/bin/dpkg-deb --info "${archive_path}.tmp.$$" >/dev/null 2>&1 ||
    software_fatal "$label managed package archive failed validation after retention copy"
  chmod 0644 "$archive_tmp"
  mv -f -- "$archive_tmp" "$archive_host_path"
}

software_store_managed_artifact() {
  label=$1
  source_path=$2
  artifact_directory=$3
  artifact_name=$4
  artifact_path="${artifact_directory}/${artifact_name}"
  source_host_path="${target_root}${source_path}"
  artifact_host_path="${target_root}${artifact_path}"
  artifact_tmp="${artifact_host_path}.tmp.$$"

  software_validate_abs_path "$label source artifact" "$source_path"
  software_validate_abs_path "$label artifact directory" "$artifact_directory"
  case "$artifact_name" in
    ''|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:+~-]*)
      software_fatal "$label artifact filename is unsafe: ${artifact_name:-unset}"
      ;;
  esac
  software_validate_abs_path "$label retained artifact" "$artifact_path"
  [ -f "$source_host_path" ] && [ ! -L "$source_host_path" ] ||
    software_fatal "$label source artifact is unavailable for retention"

  install -d -m 0755 "${target_root}${artifact_directory}"
  if [ -e "$artifact_host_path" ] || [ -L "$artifact_host_path" ]; then
    [ -f "$artifact_host_path" ] && [ ! -L "$artifact_host_path" ] ||
      software_fatal "$label retained artifact path is not a regular file: $artifact_path"
    source_sha256=$(chroot "$target_root" /usr/bin/sha256sum "$source_path" | awk '{print $1}')
    retained_sha256=$(chroot "$target_root" /usr/bin/sha256sum "$artifact_path" | awk '{print $1}')
    [ "$source_sha256" = "$retained_sha256" ] ||
      software_fatal "$label retained artifact conflicts with the verified download: $artifact_path"
    return 0
  fi

  install -m 0644 "$source_host_path" "$artifact_tmp"
  chown root:root "$artifact_tmp"
  source_sha256=$(chroot "$target_root" /usr/bin/sha256sum "$source_path" | awk '{print $1}')
  retained_sha256=$(chroot "$target_root" /usr/bin/sha256sum "${artifact_path}.tmp.$$" | awk '{print $1}')
  [ "$source_sha256" = "$retained_sha256" ] ||
    software_fatal "$label retained artifact digest changed during copy"
  chmod 0644 "$artifact_tmp"
  mv -f -- "$artifact_tmp" "$artifact_host_path"
}

software_write_managed_deb_repository() {
  repository_host_dir="${target_root}${software_deb_archive_dir}"
  packages_tmp="${repository_host_dir}/.Packages.$$"
  packages_path="${repository_host_dir}/Packages"
  archive_count=0

  install -d -m 0755 "$repository_host_dir"
  : >"$packages_tmp"
  chmod 0644 "$packages_tmp"

  for archive_host_path in "$repository_host_dir"/*.deb; do
    [ -f "$archive_host_path" ] && [ ! -L "$archive_host_path" ] || continue
    archive_path=${archive_host_path#"$target_root"}
    archive_name=${archive_path##*/}
    case "$archive_name" in
      *[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.+:~_-]*)
        software_fatal "managed package repository contains an unsafe archive name: $archive_name"
        ;;
    esac

    archive_package=$(
      chroot "$target_root" /usr/bin/dpkg-deb -f "$archive_path" Package 2>/dev/null || true
    )
    archive_version=$(
      chroot "$target_root" /usr/bin/dpkg-deb -f "$archive_path" Version 2>/dev/null || true
    )
    archive_architecture=$(
      chroot "$target_root" /usr/bin/dpkg-deb -f "$archive_path" Architecture 2>/dev/null || true
    )
    software_validate_deb_archive_component "managed repository package name" "$archive_package"
    software_validate_deb_archive_component "managed repository package version" "$archive_version"
    [ "$archive_architecture" = amd64 ] ||
      software_fatal "managed repository package has unsupported architecture: ${archive_architecture:-unset}"
    [ "$archive_name" = "${archive_package}_${archive_version}_${archive_architecture}.deb" ] ||
      software_fatal "managed repository archive name does not match its Debian control fields: $archive_name"

    chroot "$target_root" /usr/bin/dpkg-deb -f "$archive_path" >>"$packages_tmp" ||
      software_fatal "unable to read managed package control metadata: $archive_path"
    archive_size=$(wc -c <"$archive_host_path" | awk '{print $1}')
    archive_sha256=$(
      chroot "$target_root" /usr/bin/sha256sum "$archive_path" |
        awk '{print $1}'
    )
    case "$archive_size:$archive_sha256" in
      *[!0123456789abcdef:]*|:|*:)
        software_fatal "managed package repository archive metadata is invalid: $archive_name"
        ;;
    esac
    [ "${#archive_sha256}" -eq 64 ] ||
      software_fatal "managed package repository archive SHA-256 has an unexpected length: $archive_name"
    printf 'Filename: ./%s\nSize: %s\nSHA256: %s\n\n' \
      "$archive_name" \
      "$archive_size" \
      "$archive_sha256" >>"$packages_tmp"
    archive_count=$((archive_count + 1))
  done

  [ "$archive_count" -gt 0 ] || {
    rm -f -- "$packages_tmp"
    software_fatal "managed package repository has no retained Debian archives"
  }
  mv -f -- "$packages_tmp" "$packages_path"

  repository_codename=$(software_managed_deb_repository_codename)
  repository_release_tmp="${repository_host_dir}/.Release.$$"
  repository_packages_size=$(wc -c <"$packages_path" | awk '{print $1}')
  repository_packages_sha256=$(sha256sum "$packages_path" | awk '{print $1}')
  repository_release_date=$(LC_ALL=C date -Ru)
  case "$repository_packages_size:$repository_packages_sha256" in
    *[!0123456789abcdef:]*|:|*:)
      software_fatal "managed package repository Packages metadata is invalid"
      ;;
  esac
  [ "${#repository_packages_sha256}" -eq 64 ] ||
    software_fatal "managed package repository Packages SHA-256 has an unexpected length"
  printf '%s\n' \
    'Origin: Managed External Software' \
    'Label: Managed External Software' \
    "Suite: ${repository_codename}" \
    "Codename: ${repository_codename}" \
    'Architectures: amd64' \
    "Date: ${repository_release_date}" \
    'SHA256:' \
    " ${repository_packages_sha256} ${repository_packages_size} Packages" \
    'Description: Retained validated vendor Debian packages' >"$repository_release_tmp"
  chmod 0644 "$repository_release_tmp"
  mv -f -- "$repository_release_tmp" \
    "${target_root}${software_deb_repository_release}"
  software_sign_managed_deb_repository
}

software_prepare_managed_deb_repository_apt_tmp() {
  apt_tmp_path=$software_deb_repository_apt_tmp
  apt_tmp_host_path="${target_root}${apt_tmp_path}"

  # APT drops its clear-signature verifier to _apt and creates apt.sig/apt.data
  # files under TMPDIR. Keep that work isolated from the installer-wide /tmp.
  software_validate_abs_path "managed repository APT temporary directory" "$apt_tmp_path"
  [ ! -L "$apt_tmp_host_path" ] ||
    software_fatal "managed repository APT temporary directory must not be a symlink"
  if [ -e "$apt_tmp_host_path" ]; then
    [ -d "$apt_tmp_host_path" ] ||
      software_fatal "managed repository APT temporary path is not a directory"
  fi

  apt_uid=$(chroot "$target_root" /usr/bin/id -u _apt 2>/dev/null) ||
    software_fatal "managed repository APT sandbox account is unavailable"
  root_gid=$(chroot "$target_root" /usr/bin/id -g root 2>/dev/null) ||
    software_fatal "managed repository root group is unavailable"
  case "$apt_uid" in
    ''|*[!0123456789]*)
      software_fatal "managed repository APT temporary directory ownership is invalid"
      ;;
  esac
  case "$root_gid" in
    ''|*[!0123456789]*)
      software_fatal "managed repository APT temporary directory group is invalid"
      ;;
  esac

  chroot "$target_root" /usr/bin/install \
    -d \
    -m 0700 \
    -o "$apt_uid" \
    -g "$root_gid" \
    -- "$apt_tmp_path" ||
    software_fatal "managed repository APT temporary directory preparation failed"
  apt_tmp_metadata=$(
    chroot "$target_root" /usr/bin/stat \
      -c '%u:%g:%a' \
      -- "$apt_tmp_path" 2>/dev/null
  ) ||
    software_fatal "managed repository APT temporary directory metadata is unavailable"
  [ "$apt_tmp_metadata" = "${apt_uid}:${root_gid}:700" ] ||
    software_fatal "managed repository APT temporary directory ownership or mode is unsafe"
}

software_refresh_managed_deb_repository() {
  software_write_managed_deb_repository
  software_prepare_managed_deb_repository_apt_tmp
  [ -r "${target_root}${software_deb_repository_source}" ] &&
    [ ! -L "${target_root}${software_deb_repository_source}" ] ||
    software_fatal "managed package repository source is missing or unsafe: $software_deb_repository_source"

  if ! chroot "$target_root" /usr/bin/env -i \
    DEBIAN_FRONTEND=noninteractive \
    HOME=/root \
    LC_ALL=C.UTF-8 \
    TMPDIR="$software_deb_repository_apt_tmp" \
    PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    /usr/bin/apt-get \
      -o Dir::Etc::sourcelist="sources.list.d/managed-external-software.list" \
      -o Dir::Etc::sourceparts="-" \
      -o APT::Get::List-Cleanup=false \
      update
  then
    software_fatal "managed package repository APT index refresh failed"
  fi
}

software_ensure_temporary_unshare() {
  target_unshare="${target_root}${temporary_unshare_path}"
  target_unshare_divert="${target_root}${temporary_unshare_divert_path}"
  target_unshare_state="${target_root}${temporary_unshare_state_path}"

  [ -x "$temporary_unshare_hook" ] ||
    software_fatal "temporary unshare installer hook is unavailable: $temporary_unshare_hook"
  INSTALLER_TARGET_DIR="$target_root" "$temporary_unshare_hook" ||
    software_fatal "failed to activate the temporary unshare installer shim"

  [ -f "$target_unshare" ] &&
    grep -Fqx "# ${temporary_unshare_marker}" "$target_unshare" ||
    software_fatal "temporary unshare installer shim is not active"
  [ -x "$target_unshare_divert" ] ||
    software_fatal "diverted real unshare executable is unavailable"
  [ -f "$target_unshare_state" ] &&
    [ "$(cat "$target_unshare_state" 2>/dev/null || true)" = "$temporary_unshare_marker" ] ||
    software_fatal "temporary unshare installer state marker is unavailable"

  software_info "verified temporary unshare installer shim before vendor package installation"
}

software_install_deb() {
  label=$1
  deb_path=$2
  expected_packages=$3
  expected_architecture=$4
  expected_executable=$5
  expected_desktop_file=$6
  expected_runtime_library=${7:-}

  software_validate_abs_path "$label package path" "$deb_path"
  software_validate_abs_path "$label executable path" "$expected_executable"
  software_validate_abs_path "$label desktop file path" "$expected_desktop_file"
  if [ -n "$expected_runtime_library" ]; then
    software_validate_abs_path "$label runtime library path" "$expected_runtime_library"
  fi
  [ -n "$expected_packages" ] ||
    software_fatal "$label expected package names are empty"
  case "$expected_architecture" in
    amd64|arm64) ;;
    *) software_fatal "$label expected architecture is unsupported: $expected_architecture" ;;
  esac
  deb_magic=$(head -c 8 "${target_root}${deb_path}" 2>/dev/null || true)
  [ "$deb_magic" = '!<arch>' ] ||
    software_fatal "$label download does not have Debian archive framing"
  chroot "$target_root" /usr/bin/dpkg-deb --info "$deb_path" >/dev/null 2>&1 ||
    software_fatal "$label download is not a valid Debian binary package"
  software_deb_contains_path "$deb_path" "$expected_executable" ||
    software_fatal "$label package payload is missing executable: $expected_executable"
  software_deb_contains_path "$deb_path" "$expected_desktop_file" ||
    software_fatal "$label package payload is missing desktop entry: $expected_desktop_file"
  if [ -n "$expected_runtime_library" ]; then
    software_deb_contains_path "$deb_path" "$expected_runtime_library" ||
      software_fatal "$label package payload is missing runtime library: $expected_runtime_library"
  fi

  package_name=$(chroot "$target_root" /usr/bin/dpkg-deb -f "$deb_path" Package 2>/dev/null || true)
  package_version=$(chroot "$target_root" /usr/bin/dpkg-deb -f "$deb_path" Version 2>/dev/null || true)
  package_architecture=$(chroot "$target_root" /usr/bin/dpkg-deb -f "$deb_path" Architecture 2>/dev/null || true)
  case "$package_name" in
    ''|*[!abcdefghijklmnopqrstuvwxyz0123456789+.-]*)
      software_fatal "$label package has an invalid Package field: ${package_name:-unset}"
      ;;
  esac
  package_name_is_expected=false
  for expected_package in $expected_packages; do
    case "$expected_package" in
      ''|*[!abcdefghijklmnopqrstuvwxyz0123456789+.-]*)
        software_fatal "$label expected package name is invalid: ${expected_package:-unset}"
        ;;
    esac
    if [ "$package_name" = "$expected_package" ]; then
      package_name_is_expected=true
    fi
  done
  [ "$package_name_is_expected" = true ] ||
    software_fatal "$label package has unexpected Package field: $package_name"
  unset expected_package package_name_is_expected
  [ -n "$package_version" ] ||
    software_fatal "$label package has no Version field"
  chroot "$target_root" /usr/bin/dpkg --validate-version "$package_version" >/dev/null 2>&1 ||
    software_fatal "$label package has an invalid Version field: $package_version"
  [ "${#package_version}" -le 128 ] ||
    software_fatal "$label package Version field exceeds 128 characters"
  [ "$package_architecture" = "$expected_architecture" ] ||
    software_fatal "$label package has unexpected architecture: ${package_architecture:-unset}"

  software_store_managed_deb_archive \
    "$label" \
    "$deb_path" \
    "$package_name" \
    "$package_version" \
    "$package_architecture"
  managed_archive_path=$(software_managed_deb_archive_path \
    "$package_name" \
    "$package_version" \
    "$package_architecture")
  software_refresh_managed_deb_repository

  if command -v purge_target_cdrom_apt_sources >/dev/null 2>&1; then
    purge_target_cdrom_apt_sources
  fi
  # The d-i target is a chroot, not the running system. There are no target
  # services or user sessions to inspect or restart, and current needrestart
  # scanners may invoke unshare(1), which the installer environment can deny.
  # Suppress restart handling for this automatic installer-time package
  # transaction. The scheduled external-software updater uses the same policy;
  # administrator-initiated target operations remain outside it.
  if ! chroot "$target_root" /usr/bin/env -i \
    DEBIAN_FRONTEND=noninteractive \
    DEBCONF_NONINTERACTIVE_SEEN=true \
    NEEDRESTART_SUSPEND=1 \
    HOME=/root \
    PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    /usr/bin/apt-get \
      -y \
      -o DPkg::Lock::Timeout=60 \
      -o DPkg::Use-Pty=0 \
      --no-install-recommends \
      --no-install-suggests \
      install "$managed_archive_path"
  then
    software_fatal "$label package installation failed inside the d-i target"
  fi

  installed_package_status=$(
    chroot "$target_root" /usr/bin/dpkg-query \
      -W \
      -f='${Status}' \
      "$package_name" 2>/dev/null || true
  )
  [ "$installed_package_status" = "install ok installed" ] ||
    software_fatal "$label package is not fully installed and configured: ${installed_package_status:-missing}"
  chroot "$target_root" /usr/bin/test -x "$expected_executable" ||
    software_fatal "$label executable is missing after package installation: $expected_executable"
  chroot "$target_root" /usr/bin/test -r "$expected_desktop_file" ||
    software_fatal "$label desktop entry is missing after package installation: $expected_desktop_file"
  if [ -n "$expected_runtime_library" ]; then
    chroot "$target_root" /usr/bin/test -r "$expected_runtime_library" ||
      software_fatal "$label runtime library is missing after package installation: $expected_runtime_library"
  fi
  package_sha256=$(chroot "$target_root" /usr/bin/sha256sum "$deb_path" | awk '{print $1}')
  [ -n "$package_sha256" ] || software_fatal "$label package SHA-256 could not be recorded"
  software_info "installed ${label} package=${package_name} version=${package_version} architecture=${package_architecture} sha256=${package_sha256}"
}

software_configure_chromium_sandbox() {
  label=$1
  sandbox_path=$2
  presence=${3:-required}

  software_validate_abs_path "$label Chromium sandbox path" "$sandbox_path"
  sandbox_host_path="${target_root}${sandbox_path}"
  if [ ! -e "$sandbox_host_path" ]; then
    [ "$presence" = optional ] && return 0
    software_fatal "$label Chromium sandbox is missing: $sandbox_path"
  fi
  [ -f "$sandbox_host_path" ] && [ ! -L "$sandbox_host_path" ] ||
    software_fatal "$label Chromium sandbox must be a regular non-symlink file: $sandbox_path"
  chown root:root "$sandbox_host_path"
  chmod 4755 "$sandbox_host_path"
  # Debian Installer does not guarantee a GNU-compatible host-side stat(1).
  # Inspect the normalized file with the target system's coreutils instead.
  sandbox_metadata=$(
    chroot "$target_root" /usr/bin/stat -c '%u:%g:%a' -- "$sandbox_path" 2>/dev/null || true
  )
  [ "$sandbox_metadata" = 0:0:4755 ] ||
    software_fatal "$label Chromium sandbox has invalid ownership or mode: ${sandbox_metadata:-unreadable}"
}

software_install_postman() {
  postman_member_list_host="${target_root}${postman_member_list}"

  chroot "$target_root" /usr/bin/tar -tzf "$postman_archive" >"$postman_member_list_host" ||
    software_fatal "Postman download is not a readable gzip-compressed tar archive"
  if ! awk '
    !NF { bad = 1 }
    /[[:space:]]/ { bad = 1 }
    /^\// { bad = 1 }
    /\\/ { bad = 1 }
    /(^|\/)\.\.($|\/)/ { bad = 1 }
    $0 !~ /^Postman\// { bad = 1 }
    seen[$0]++ { bad = 1 }
    END { exit bad ? 1 : 0 }
  ' "$postman_member_list_host"
  then
    software_fatal "Postman archive contains an unsafe or unexpected member path"
  fi

  postman_verbose_list_host="${target_root}${postman_verbose_list}"
  chroot "$target_root" /usr/bin/env LC_ALL=C \
    /usr/bin/tar --numeric-owner -tvzf "$postman_archive" >"$postman_verbose_list_host" ||
    software_fatal "Postman archive member metadata could not be inspected"
  if ! awk '
    substr($1, 1, 1) !~ /^[-dl]$/ { bad = 1 }
    substr($1, 1, 1) == "l" {
      symlinks++
      if (NF != 8 || $6 != "Postman/Postman" || $7 != "->" || $8 != "app/Postman") {
        bad = 1
      }
      next
    }
    NF != 6 { bad = 1 }
    END {
      if (symlinks != 1) {
        bad = 1
      }
      exit bad ? 1 : 0
    }
  ' "$postman_verbose_list_host"
  then
    software_fatal "Postman archive contains an unsupported node or symlink"
  fi

  postman_member_count=$(
    awk 'NF { count++ } END { print count + 0 }' "$postman_member_list_host"
  )
  case "$postman_member_count" in
    ''|*[!0-9]*) software_fatal "Postman archive member count is invalid" ;;
  esac
  [ "$postman_member_count" -le 5000 ] ||
    software_fatal "Postman archive contains too many members: $postman_member_count"

  for postman_required_member in \
    Postman/Postman \
    Postman/app/Postman \
    Postman/app/chrome-sandbox \
    Postman/app/libffmpeg.so \
    Postman/app/resources/app/assets/icon.png \
    Postman/app/resources/app/package.json
  do
    grep -Fqx "$postman_required_member" "$postman_member_list_host" ||
      software_fatal "Postman archive is missing ${postman_required_member}"
  done
  unset postman_required_member

  postman_install_metadata=$(
    chroot "$target_root" /bin/sh -eu -s -- \
      "$postman_archive" \
      "$postman_install_dir" <<'POSTMAN_INSTALL_SH'
archive=$1
install_dir=$2
new_dir=/opt/.postman.new
backup_dir=/opt/.postman.previous

rollback() {
  rm -rf "$new_dir"
  if [ -d "$backup_dir" ]; then
    rm -rf "$install_dir"
    mv "$backup_dir" "$install_dir"
  fi
}
trap rollback EXIT HUP INT TERM

rm -rf "$new_dir" "$backup_dir"
[ ! -L "$install_dir" ]
install -d -m 0700 "$new_dir"
tar \
  --extract \
  --gzip \
  --file "$archive" \
  --directory "$new_dir" \
  --strip-components=1 \
  --no-same-owner \
  --no-same-permissions

unsupported_node=$(
  find "$new_dir" \
    -mindepth 1 \
    ! -type f \
    ! -type d \
    ! -type l \
    -print |
    sed -n "1p"
)
[ -z "$unsupported_node" ]
symlink_count=$(find "$new_dir" -xdev -type l -printf . | wc -c | awk "{print \$1}")
[ "$symlink_count" = 1 ]
[ -L "$new_dir/Postman" ]
[ "$(readlink "$new_dir/Postman")" = app/Postman ]

extracted_file_count=$(find "$new_dir" -xdev -printf . | wc -c | awk "{print \$1}")
extracted_kib=$(du -sk "$new_dir" | awk "{print \$1}")
case "$extracted_file_count:$extracted_kib" in
  *[!0-9:]*|:|*:) exit 1 ;;
esac
[ "$extracted_file_count" -le 5000 ]
[ "$extracted_kib" -le 1048576 ]

[ -f "$new_dir/app/Postman" ] && [ ! -L "$new_dir/app/Postman" ] && [ -x "$new_dir/app/Postman" ]
[ -f "$new_dir/app/postman" ] && [ ! -L "$new_dir/app/postman" ] && [ -x "$new_dir/app/postman" ]
[ -f "$new_dir/app/chrome-sandbox" ] && [ ! -L "$new_dir/app/chrome-sandbox" ]
[ -f "$new_dir/app/libffmpeg.so" ] && [ ! -L "$new_dir/app/libffmpeg.so" ] && [ -r "$new_dir/app/libffmpeg.so" ]
[ -f "$new_dir/app/resources/app/assets/icon.png" ] && [ ! -L "$new_dir/app/resources/app/assets/icon.png" ]
[ -f "$new_dir/app/resources/app/package.json" ] && [ ! -L "$new_dir/app/resources/app/package.json" ]
file -b "$new_dir/app/Postman" | grep -q "ELF 64-bit.*x86-64"

version=$(
  python3 - "$new_dir/app/resources/app/package.json" <<'PY'
import json
import os
import re
import sys

package_path = sys.argv[1]
if os.path.getsize(package_path) > 1048576:
    raise SystemExit(1)
with open(package_path, "r", encoding="utf-8") as stream:
    package = json.load(stream)
version = package.get("version")
if not isinstance(version, str):
    raise SystemExit(1)
if re.fullmatch(r"[0-9]+(?:[.][0-9]+)*", version) is None:
    raise SystemExit(1)
print(version)
PY
)
[ "$(printf "%s\n" "$version" | awk "NF { count++ } END { print count + 0 }")" -eq 1 ]
case "$version" in
  *[!0-9.]*|.*|*.|*..*) exit 1 ;;
esac

archive_sha256=$(sha256sum "$archive" | awk "{print \$1}")
case "$archive_sha256" in
  *[!0-9a-f]*|'') exit 1 ;;
esac
[ "${#archive_sha256}" -eq 64 ]

chown -R root:root "$new_dir"
find "$new_dir" -xdev -type d -exec chmod 0755 {} +
find "$new_dir" -xdev -type f -exec chmod a-s,go-w {} +
chown -h root:root "$new_dir/Postman"
chmod 0755 "$new_dir/app/Postman" "$new_dir/app/postman"
chmod 4755 "$new_dir/app/chrome-sandbox"
[ -u "$new_dir/app/chrome-sandbox" ] && [ -x "$new_dir/app/chrome-sandbox" ]

cat >"$new_dir/.managed-release" <<EOF
version=${version}
url=https://dl.pstmn.io/download/latest/linux64
archive_sha256=${archive_sha256}
architecture=amd64
EOF
chmod 0644 "$new_dir/.managed-release"

if [ -e "$install_dir" ]; then
  mv "$install_dir" "$backup_dir"
fi
mv "$new_dir" "$install_dir"
[ -x "$install_dir/app/Postman" ]
[ -u "$install_dir/app/chrome-sandbox" ]
[ -r "$install_dir/app/libffmpeg.so" ]
[ -r "$install_dir/app/resources/app/assets/icon.png" ]
rm -rf "$backup_dir"
trap - EXIT HUP INT TERM
printf "%s|%s\n" "$version" "$archive_sha256"
POSTMAN_INSTALL_SH
  ) || software_fatal "Postman archive validation or atomic publication failed"

  case "$postman_install_metadata" in
    *'|'*) ;;
    *) software_fatal "Postman installation metadata is invalid" ;;
  esac
  postman_version=${postman_install_metadata%%|*}
  postman_sha256=${postman_install_metadata#*|}
  case "$postman_version" in
    *[!0-9.]*|.*|*.|*..*|'') software_fatal "Postman version is invalid: ${postman_version:-unset}" ;;
  esac
  case "$postman_sha256" in
    *[!0-9a-f]*|'') software_fatal "Postman archive SHA-256 is invalid" ;;
  esac
  [ "${#postman_sha256}" -eq 64 ] ||
    software_fatal "Postman archive SHA-256 has an invalid length"

  software_render_seed_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET usr/share/applications/postman.desktop)" \
    "$postman_desktop_file" \
    0644 \
    LABWC_MANAGED_APP_DEFAULT_EXEC "$LABWC_MANAGED_APP_DEFAULT_EXEC"
  chroot "$target_root" /usr/bin/desktop-file-validate "$postman_desktop_file"
  chroot "$target_root" /usr/bin/update-desktop-database /usr/share/applications

  software_info "installed verified Postman archive version=${postman_version} sha256=${postman_sha256}"
}

software_install_ledger() {
  : "${ACCOUNT_USERNAME:?ACCOUNT_USERNAME must be set before Ledger device access is configured}"

  software_info "resolving the requested Ledger channel ${ledger_requested_latest_url} through signed release metadata"
  software_stage_seed_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/share/software/ledger/ledgerlive.pem)" \
    "$ledger_public_key" \
    0644

  chroot "$target_root" /usr/bin/openssl pkey \
    -pubin \
    -in "$ledger_public_key" \
    -noout >/dev/null 2>&1 ||
    software_fatal "staged Ledger public key is invalid"
  ledger_public_key_sha256=$(
    chroot "$target_root" /usr/bin/openssl pkey \
      -pubin \
      -in "$ledger_public_key" \
      -outform DER 2>/dev/null |
      sha256sum |
      awk '{print $1}'
  )
  [ "$ledger_public_key_sha256" = 0381bccfa5505e834f9fda30eeba257055782f30c495ba0604a0cd37b548c6fc ] ||
    software_fatal "staged Ledger public key fingerprint does not match the pinned vendor key"

  software_download \
    "Ledger release metadata" \
    "$ledger_metadata_url" \
    "$ledger_metadata" \
    128 \
    65536 \
    metadata \
    "download.live.ledger.com"
  software_parse_ledger_metadata

  software_download \
    "Ledger signed SHA-512 manifest" \
    "$ledger_checksums_url" \
    "$ledger_checksums" \
    128 \
    65536 \
    metadata \
    "resources.live.ledger.app"
  software_download \
    "Ledger SHA-512 manifest signature" \
    "$ledger_checksums_signature_url" \
    "$ledger_checksums_signature" \
    64 \
    4096 \
    artifact \
    "resources.live.ledger.app"
  software_download \
    "Ledger Live AppImage" \
    "$ledger_requested_latest_url" \
    "$ledger_appimage" \
    "$managed_application_minimum_bytes" \
    536870912 \
    artifact \
    "download.live.ledger.com"

  chroot "$target_root" /usr/bin/openssl dgst \
    -sha256 \
    -verify "$ledger_public_key" \
    -signature "$ledger_checksums_signature" \
    "$ledger_checksums" >/dev/null ||
    software_fatal "Ledger SHA-512 manifest signature verification failed"

  ledger_signed_sha512=$(software_ledger_signed_sha512) ||
    software_fatal "Ledger signed SHA-512 manifest does not contain exactly one valid Linux AppImage record"
  ledger_actual_sha512=$(
    chroot "$target_root" /usr/bin/sha512sum "$ledger_appimage" |
      awk '{print $1}'
  )
  [ "$ledger_actual_sha512" = "$ledger_signed_sha512" ] ||
    software_fatal "Ledger Live AppImage SHA-512 does not match the signed vendor manifest"
  ledger_actual_sha512_base64=$(
    chroot "$target_root" /usr/bin/openssl dgst \
      -sha512 \
      -binary "$ledger_appimage" |
      chroot "$target_root" /usr/bin/openssl base64 -A
  )
  [ "$ledger_actual_sha512_base64" = "$ledger_metadata_sha512" ] ||
    software_fatal "Ledger Live AppImage SHA-512 does not match the release metadata"
  ledger_actual_size=$(wc -c <"${target_root}${ledger_appimage}" | awk '{print $1}')
  [ "$ledger_actual_size" = "$ledger_metadata_size" ] ||
    software_fatal "Ledger Live AppImage size does not match the release metadata"

  ledger_file_type=$(chroot "$target_root" /usr/bin/file -b "$ledger_appimage" 2>/dev/null || true)
  case "$ledger_file_type" in
    *"ELF 64-bit"*"x86-64"*) ;;
    *) software_fatal "Ledger Live AppImage has an unexpected file type: ${ledger_file_type:-unset}" ;;
  esac
  software_store_managed_artifact \
    "Ledger Live AppImage" \
    "$ledger_appimage" \
    "$software_ledger_artifact_dir" \
    "$ledger_filename"

  # shellcheck disable=SC2016
  chroot "$target_root" /bin/sh -eu -c '
work_dir=$1
appimage=$2
install_dir=$3
version=$4
new_dir=/opt/.ledger-live.new
backup_dir=/opt/.ledger-live.previous

rollback() {
  rm -rf "$new_dir"
  if [ -d "$backup_dir" ]; then
    rm -rf "$install_dir"
    mv "$backup_dir" "$install_dir"
  fi
}
trap rollback EXIT HUP INT TERM

rm -rf "$work_dir/squashfs-root" "$new_dir" "$backup_dir"
chmod 0700 "$appimage"
(
  cd "$work_dir"
  "$appimage" --appimage-extract >/dev/null
)
extracted="$work_dir/squashfs-root"
vendor_desktop="$extracted/ledger-live-desktop.desktop"
[ -x "$extracted/AppRun" ]
[ -x "$extracted/ledger-live-desktop" ]
[ -f "$extracted/chrome-sandbox" ] && [ ! -L "$extracted/chrome-sandbox" ]
[ -r "$extracted/resources/app.asar" ] && [ ! -L "$extracted/resources/app.asar" ]
[ -r "$vendor_desktop" ] && [ ! -L "$vendor_desktop" ]
vendor_version=$(sed -n "s/^X-AppImage-Version=//p" "$vendor_desktop")
[ "$vendor_version" = "$version" ]
desktop-file-validate "$vendor_desktop"
extracted_file_count=$(find "$extracted" -xdev -printf . | wc -c | awk "{print \$1}")
extracted_kib=$(du -sk "$extracted" | awk "{print \$1}")
case "$extracted_file_count:$extracted_kib" in
  *[!0-9:]*|:|*:) exit 1 ;;
esac
[ "$extracted_file_count" -le 20000 ]
[ "$extracted_kib" -le 1048576 ]

cp -a "$extracted" "$new_dir"
chown -R root:root "$new_dir"
find "$new_dir" -type d -exec chmod 0755 {} +
find "$new_dir" -type f -exec chmod a-s {} +
chmod -R go-w "$new_dir"
chmod 4755 "$new_dir/chrome-sandbox"
chmod 0755 "$new_dir/AppRun" "$new_dir/ledger-live-desktop"
[ -u "$new_dir/chrome-sandbox" ] && [ -x "$new_dir/chrome-sandbox" ]
[ -x "$new_dir/AppRun" ] && [ -x "$new_dir/ledger-live-desktop" ]

if [ -e "$install_dir" ]; then
  mv "$install_dir" "$backup_dir"
fi
mv "$new_dir" "$install_dir"
chmod 0755 "$install_dir"
[ -u "$install_dir/chrome-sandbox" ] && [ -x "$install_dir/AppRun" ]
rm -rf "$backup_dir"
trap - EXIT HUP INT TERM
' sh "$work_dir" "$ledger_appimage" "$ledger_install_dir" "$ledger_version"

  ledger_icon_source="${ledger_install_dir}/usr/share/icons/hicolor/512x512/apps/ledger-live-desktop.png"
  [ -f "${target_root}${ledger_icon_source}" ] &&
    [ ! -L "${target_root}${ledger_icon_source}" ] &&
    [ -r "${target_root}${ledger_icon_source}" ] ||
    software_fatal "verified Ledger Live AppImage is missing its managed icon"
  install -D -m 0644 "${target_root}${ledger_icon_source}" "${target_root}${ledger_icon_file}"

  software_render_seed_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET usr/share/applications/ledger-live.desktop)" \
    "$ledger_desktop_file" \
    0644 \
    LABWC_MANAGED_APP_DEFAULT_EXEC "$LABWC_MANAGED_APP_DEFAULT_EXEC"
  software_stage_seed_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET etc/udev/rules.d/53-ledger-wallet.rules)" \
    "$ledger_udev_rules" \
    0644

  run_in_target "configure Ledger hardware-wallet access" /bin/sh -eu -c '
account_user=$1
udev_rule=$2

getent passwd "$account_user" >/dev/null
getent group plugdev >/dev/null 2>&1 || groupadd --system plugdev
usermod -a -G plugdev "$account_user"
case " $(id -nG "$account_user") " in
  *" plugdev "*) ;;
  *) printf "fatal: Ledger account was not added to plugdev: %s\n" "$account_user" >&2; exit 1 ;;
esac
test -r "$udev_rule"
if command -v udevadm >/dev/null 2>&1; then
  udevadm verify --resolve-names=never "$udev_rule" >/dev/null
fi
' sh "$ACCOUNT_USERNAME" "$ledger_udev_rules"

  chroot "$target_root" /usr/bin/desktop-file-validate "$ledger_desktop_file"
  chroot "$target_root" /usr/bin/update-desktop-database /usr/share/applications
  if [ -x "${target_root}/usr/bin/gtk-update-icon-cache" ]; then
    chroot "$target_root" /usr/bin/gtk-update-icon-cache -f -q /usr/share/icons/hicolor
  fi

  software_info "installed verified Ledger Live AppImage version=${ledger_version} sha512=${ledger_actual_sha512}"
}

software_cleanup_work_dir() {
  rm -rf -- "${target_root}${work_dir}"
}

install -d -m 0700 "${target_root}${work_dir}" "$tmp_env_dir"
trap software_cleanup_work_dir EXIT HUP INT TERM
software_ensure_temporary_unshare
software_stage_external_servicing_runtime
software_stage_seed_asset \
  "$(installer_repo_join_var DIR_HOOKS_TARGET etc/apt/sources.list.d/managed-external-software.list)" \
  "$software_deb_repository_source" \
  0644
software_enable_chatgpt_integration
software_stage_seed_asset \
  "$(installer_repo_join_var DIR_HOOKS_TARGET usr/share/applications/discord.desktop)" \
  "$discord_desktop_file" \
  0644
chroot "$target_root" /usr/bin/desktop-file-validate "$discord_desktop_file"

software_download \
  "Bitwarden Desktop" \
  "https://bitwarden.com/download/?app=desktop&platform=linux&variant=deb" \
  "$bitwarden_deb" \
  "$managed_application_minimum_bytes" \
  314572800 \
  artifact \
  "bitwarden.com github.com objects.githubusercontent.com release-assets.githubusercontent.com"
# Install and retain the exact vendor download; never rewrite app.asar or
# rebuild Bitwarden's Debian archive.
software_install_deb \
  "Bitwarden Desktop" \
  "$bitwarden_deb" \
  "bitwarden" \
  amd64 \
  /opt/Bitwarden/bitwarden \
  /usr/share/applications/bitwarden.desktop \
  /opt/Bitwarden/libffmpeg.so
software_configure_chromium_sandbox \
  "Bitwarden Desktop" \
  /opt/Bitwarden/chrome-sandbox

software_download \
  "QoreDB" \
  "$SOFTWARE_QOREDB_URL" \
  "$qoredb_deb" \
  "$SOFTWARE_QOREDB_BYTES" \
  "$SOFTWARE_QOREDB_BYTES" \
  artifact \
  "github.com objects.githubusercontent.com release-assets.githubusercontent.com"
qoredb_actual_sha256=$(
  chroot "$target_root" /usr/bin/sha256sum "$qoredb_deb" |
    awk '{print $1}'
)
[ "$qoredb_actual_sha256" = "$SOFTWARE_QOREDB_SHA256" ] ||
  software_fatal "QoreDB package SHA-256 does not match the pinned release asset"
software_install_deb \
  "QoreDB" \
  "$qoredb_deb" \
  "qore-db" \
  amd64 \
  /usr/bin/qoredb \
  /usr/share/applications/QoreDB.desktop
qoredb_installed_version=$(
  chroot "$target_root" /usr/bin/dpkg-query \
    -W \
    -f='${Version}' \
    qore-db 2>/dev/null || true
)
[ "$qoredb_installed_version" = "$SOFTWARE_QOREDB_VERSION" ] ||
  software_fatal "QoreDB installed version does not match the pinned release: ${qoredb_installed_version:-missing}"
chroot "$target_root" /usr/bin/desktop-file-validate \
  /usr/share/applications/QoreDB.desktop >/dev/null 2>&1

chroot "$target_root" /usr/bin/update-desktop-database /usr/share/applications

software_download \
  "Obsidian" \
  "$obsidian_url" \
  "$obsidian_deb" \
  "$obsidian_size" \
  "$obsidian_size" \
  artifact \
  "github.com objects.githubusercontent.com release-assets.githubusercontent.com"
obsidian_actual_sha256=$(
  chroot "$target_root" /usr/bin/sha256sum "$obsidian_deb" |
    awk '{print $1}'
)
[ "$obsidian_actual_sha256" = "$obsidian_sha256" ] ||
  software_fatal "Obsidian package SHA-256 does not match the pinned release asset"
software_install_deb \
  "Obsidian" \
  "$obsidian_deb" \
  "obsidian" \
  amd64 \
  /opt/Obsidian/obsidian \
  /usr/share/applications/obsidian.desktop \
  /opt/Obsidian/libffmpeg.so
obsidian_installed_version=$(
  chroot "$target_root" /usr/bin/dpkg-query \
    -W \
    -f='${Version}\n' \
    obsidian 2>/dev/null || true
)
[ "$obsidian_installed_version" = "$obsidian_version" ] ||
  software_fatal "Obsidian installed version does not match the pinned release"
chroot "$target_root" /usr/bin/desktop-file-validate \
  /usr/share/applications/obsidian.desktop >/dev/null 2>&1
chroot "$target_root" /usr/bin/update-desktop-database /usr/share/applications

software_download \
  "Postman" \
  "$postman_url" \
  "$postman_archive" \
  "$managed_application_minimum_bytes" \
  314572800 \
  artifact \
  "dl.pstmn.io"
software_install_postman
software_store_managed_artifact \
  "Postman" \
  "$postman_archive" \
  "$software_postman_artifact_dir" \
  "postman-${postman_version}-linux-amd64.tar.gz"

software_download \
  "Sleek" \
  "$sleek_url" \
  "$sleek_deb" \
  "$sleek_size" \
  "$sleek_size" \
  artifact \
  "github.com objects.githubusercontent.com release-assets.githubusercontent.com"
sleek_actual_sha256=$(
  chroot "$target_root" /usr/bin/sha256sum "$sleek_deb" |
    awk '{print $1}'
)
[ "$sleek_actual_sha256" = "$sleek_sha256" ] ||
  software_fatal "Sleek package SHA-256 does not match the pinned release asset"
software_install_deb \
  "Sleek" \
  "$sleek_deb" \
  "sleek" \
  amd64 \
  /opt/sleek/sleek \
  /usr/share/applications/sleek.desktop \
  /opt/sleek/libffmpeg.so
sleek_installed_version=$(
  chroot "$target_root" /usr/bin/dpkg-query \
    -W \
    -f='${Version}' \
    sleek 2>/dev/null || true
)
[ "$sleek_installed_version" = "$sleek_version" ] ||
  software_fatal "Sleek installed version does not match the pinned release: ${sleek_installed_version:-missing}"
software_render_seed_asset \
  "$(installer_repo_join_var DIR_HOOKS_TARGET usr/share/applications/sleek.desktop)" \
  /usr/share/applications/sleek.desktop \
  0644 \
  LABWC_MANAGED_APP_DEFAULT_EXEC "$LABWC_MANAGED_APP_DEFAULT_EXEC"
chroot "$target_root" /usr/bin/desktop-file-validate \
  /usr/share/applications/sleek.desktop >/dev/null 2>&1
chroot "$target_root" /usr/bin/update-desktop-database /usr/share/applications

software_download \
  "Zoom Workplace" \
  "https://zoom.us/client/latest/zoom_amd64.deb" \
  "$zoom_deb" \
  "$managed_application_minimum_bytes" \
  536870912
software_install_deb \
  "Zoom Workplace" \
  "$zoom_deb" \
  "zoom" \
  amd64 \
  /usr/bin/zoom \
  /usr/share/applications/Zoom.desktop

software_download \
  "Filen Desktop" \
  "https://cdn.filen.io/@filen/desktop/release/latest/Filen_linux_amd64.deb" \
  "$filen_deb" \
  "$managed_application_minimum_bytes" \
  536870912
software_install_deb \
  "Filen Desktop" \
  "$filen_deb" \
  "filen filen-desktop" \
  amd64 \
  /opt/Filen/Filen \
  /usr/share/applications/Filen.desktop \
  /opt/Filen/libffmpeg.so
software_configure_chromium_sandbox \
  "Filen Desktop" \
  /opt/Filen/chrome-sandbox \
  optional

run_in_target \
  "install complete managed Discord stable runtime" \
  "$software_update_helper" \
  --bootstrap-discord
for discord_runtime_path in \
  "${discord_install_dir}/Discord" \
  "${discord_install_dir}/chrome-sandbox" \
  "${discord_install_dir}/chrome_crashpad_handler" \
  "${discord_install_dir}/discord.png" \
  "${discord_install_dir}/libffmpeg.so" \
  "${discord_install_dir}/modules/installed.json" \
  "${discord_install_dir}/.managed-release"
do
  chroot "$target_root" /usr/bin/test -r "$discord_runtime_path" ||
    software_fatal "managed Discord runtime is incomplete after bootstrap: $discord_runtime_path"
done
unset discord_runtime_path
chroot "$target_root" /usr/bin/test -x "${discord_install_dir}/Discord" &&
  chroot "$target_root" /usr/bin/test -x "${discord_install_dir}/chrome_crashpad_handler" &&
  chroot "$target_root" /usr/bin/test -u "${discord_install_dir}/chrome-sandbox" &&
  chroot "$target_root" /usr/bin/test -x "${discord_install_dir}/chrome-sandbox" ||
  software_fatal "managed Discord runtime executables are invalid after bootstrap"

software_install_ledger

software_stage_seed_asset \
  "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/share/software/tuta/tutao-pub.pem)" \
  "$tuta_public_key" \
  0644

tuta_public_key_sha256=$(
  # shellcheck disable=SC2016
  chroot "$target_root" /bin/sh -eu -c '
openssl pkey -pubin -in "$1" -outform DER |
  sha256sum |
  awk "{print \$1}"
' sh "$tuta_public_key"
)
[ "$tuta_public_key_sha256" = 9566e054634a75f540b64db71b92b040bc77f9a3954d737cb01c4630c1225127 ] ||
  software_fatal "staged Tuta public key fingerprint does not match the pinned vendor key"

software_download \
  "Tuta Mail AppImage" \
  "https://app.tuta.com/desktop/tutanota-desktop-linux.AppImage" \
  "$tuta_appimage" \
  "$managed_application_minimum_bytes" \
  536870912
software_download \
  "Tuta Mail signature" \
  "https://app.tuta.com/desktop/linux-sig.bin" \
  "$tuta_signature" \
  128 \
  16384

chroot "$target_root" /usr/bin/openssl dgst \
  -sha512 \
  -verify "$tuta_public_key" \
  -signature "$tuta_signature" \
  "$tuta_appimage" >/dev/null ||
  software_fatal "Tuta Mail AppImage signature verification failed"

tuta_file_type=$(chroot "$target_root" /usr/bin/file -b "$tuta_appimage" 2>/dev/null || true)
case "$tuta_file_type" in
  *"ELF 64-bit"*"x86-64"*) ;;
  *) software_fatal "Tuta Mail AppImage has an unexpected file type: ${tuta_file_type:-unset}" ;;
esac

# shellcheck disable=SC2016
chroot "$target_root" /bin/sh -eu -c '
work_dir=$1
appimage=$2
install_dir=$3
new_dir=/opt/.tuta-mail.new
backup_dir=/opt/.tuta-mail.previous

rollback() {
  rm -rf "$new_dir"
  if [ -d "$backup_dir" ]; then
    rm -rf "$install_dir"
    mv "$backup_dir" "$install_dir"
  fi
}
trap rollback EXIT HUP INT TERM

rm -rf "$work_dir/squashfs-root" "$new_dir" "$backup_dir"
chmod 0700 "$appimage"
(
  cd "$work_dir"
  "$appimage" --appimage-extract >/dev/null
)
[ -x "$work_dir/squashfs-root/AppRun" ]

cp -a "$work_dir/squashfs-root" "$new_dir"
chown -R root:root "$new_dir"
/usr/bin/find "$new_dir" -xdev -type d -exec /bin/chmod 0755 {} +
/usr/bin/find "$new_dir" -xdev -type f -exec /bin/chmod a-s,go-w {} +
[ -f "$new_dir/AppRun" ] && [ ! -L "$new_dir/AppRun" ]
/bin/chmod 0755 "$new_dir/AppRun"

if [ -e "$install_dir" ]; then
  mv "$install_dir" "$backup_dir"
fi
mv "$new_dir" "$install_dir"
[ -x "$install_dir/AppRun" ]
rm -rf "$backup_dir"
trap - EXIT HUP INT TERM
' sh "$work_dir" "$tuta_appimage" "$tuta_install_dir"

tuta_icon_source=$(
  # shellcheck disable=SC2016
  chroot "$target_root" /bin/sh -eu -c '
install_dir=$1
if [ -e "$install_dir/.DirIcon" ]; then
  readlink -f "$install_dir/.DirIcon"
  exit 0
fi
find "$install_dir/usr/share/icons/hicolor" -type f -name "*.png" -exec wc -c {} \; 2>/dev/null |
  sort -n |
  tail -n 1 |
  cut -d " " -f 2-
' sh "$tuta_install_dir" 2>/dev/null || true
)
case "$tuta_icon_source" in
  "$tuta_install_dir"/*) ;;
  *) software_fatal "unable to resolve the Tuta Mail icon from the verified AppImage" ;;
esac
[ -r "${target_root}${tuta_icon_source}" ] ||
  software_fatal "resolved Tuta Mail icon is unreadable: $tuta_icon_source"

install -d -m 0755 "${target_root}$(dirname "$tuta_icon_file")"
install -m 0644 "${target_root}${tuta_icon_source}" "${target_root}${tuta_icon_file}"

software_render_seed_asset \
  "$(installer_repo_join_var DIR_HOOKS_TARGET usr/share/applications/tuta-mail.desktop)" \
  "$tuta_desktop_file" \
  0644 \
  LABWC_MANAGED_APP_DEFAULT_EXEC "$LABWC_MANAGED_APP_DEFAULT_EXEC"

chroot "$target_root" /usr/bin/desktop-file-validate "$tuta_desktop_file"
chroot "$target_root" /usr/bin/update-desktop-database /usr/share/applications
if [ -x "${target_root}/usr/bin/gtk-update-icon-cache" ]; then
  chroot "$target_root" /usr/bin/gtk-update-icon-cache -f -q /usr/share/icons/hicolor
fi

tuta_sha256=$(chroot "$target_root" /usr/bin/sha256sum "$tuta_appimage" | awk '{print $1}')
[ -n "$tuta_sha256" ] || software_fatal "failed to record Tuta Mail AppImage SHA-256"
software_store_managed_artifact \
  "Tuta Mail AppImage" \
  "$tuta_appimage" \
  "$software_tuta_artifact_dir" \
  "tuta-${tuta_sha256}.AppImage"
software_info "installed verified Tuta Mail AppImage sha256=${tuta_sha256}"

software_restore_managed_apparmor_profiles

install -d -m 0755 \
  "${target_root}${software_state_dir}" \
  "${target_root}${software_event_dir}" \
  "${target_root}${software_deb_archive_dir}" \
  "${target_root}${software_artifact_dir}" \
  "${target_root}${software_vendor_dir}" \
  "${target_root}${software_postman_artifact_dir}" \
  "${target_root}${software_discord_artifact_dir}" \
  "${target_root}${software_tuta_artifact_dir}" \
  "${target_root}${software_ledger_artifact_dir}" \
  "${target_root}${software_metadata_dir}"
chown root:root \
  "${target_root}${software_state_dir}" \
  "${target_root}${software_event_dir}" \
  "${target_root}${software_deb_archive_dir}" \
  "${target_root}${software_artifact_dir}" \
  "${target_root}${software_vendor_dir}" \
  "${target_root}${software_postman_artifact_dir}" \
  "${target_root}${software_discord_artifact_dir}" \
  "${target_root}${software_tuta_artifact_dir}" \
  "${target_root}${software_ledger_artifact_dir}" \
  "${target_root}${software_metadata_dir}"
chmod 0755 \
  "${target_root}${software_state_dir}" \
  "${target_root}${software_event_dir}" \
  "${target_root}${software_deb_archive_dir}" \
  "${target_root}${software_artifact_dir}" \
  "${target_root}${software_vendor_dir}" \
  "${target_root}${software_postman_artifact_dir}" \
  "${target_root}${software_discord_artifact_dir}" \
  "${target_root}${software_tuta_artifact_dir}" \
  "${target_root}${software_ledger_artifact_dir}" \
  "${target_root}${software_metadata_dir}"
postman_state_tmp="${target_root}${postman_state_file}.tmp.$$"
printf '%s|%s\n' "$postman_version" "$postman_sha256" >"$postman_state_tmp"
chmod 0644 "$postman_state_tmp"
mv -f -- "$postman_state_tmp" "${target_root}${postman_state_file}"
tuta_hash_tmp="${target_root}${tuta_hash_file}.tmp.$$"
printf '%s\n' "$tuta_sha256" >"$tuta_hash_tmp"
chmod 0644 "$tuta_hash_tmp"
mv -f -- "$tuta_hash_tmp" "${target_root}${tuta_hash_file}"
ledger_hash_tmp="${target_root}${ledger_hash_file}.tmp.$$"
printf '%s\n' "$ledger_actual_sha512" >"$ledger_hash_tmp"
chmod 0644 "$ledger_hash_tmp"
mv -f -- "$ledger_hash_tmp" "${target_root}${ledger_hash_file}"
ledger_version_tmp="${target_root}${ledger_version_file}.tmp.$$"
printf '%s\n' "$ledger_version" >"$ledger_version_tmp"
chmod 0644 "$ledger_version_tmp"
mv -f -- "$ledger_version_tmp" "${target_root}${ledger_version_file}"

software_refresh_managed_deb_repository

software_external_cpu_quota=$(software_managed_external_cpu_quota)

software_stage_seed_asset \
  "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/libexec/managed-external-software-notify)" \
  "$software_notify_helper" \
  0755
software_render_seed_asset \
  "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/system/managed-external-software-download.service.tmpl)" \
  "$software_download_service" \
  0644 \
  MANAGED_EXTERNAL_SOFTWARE_CPU_QUOTA "$software_external_cpu_quota"
software_stage_seed_asset \
  "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/system/managed-external-software-download.timer)" \
  "$software_download_timer" \
  0644
software_render_seed_asset \
  "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/system/managed-external-software-update.service.tmpl)" \
  "$software_update_service" \
  0644 \
  MANAGED_EXTERNAL_SOFTWARE_CPU_QUOTA "$software_external_cpu_quota"
software_stage_seed_asset \
  "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/system/managed-external-software-update.timer)" \
  "$software_update_timer" \
  0644
software_stage_seed_asset \
  "$(installer_repo_join_var DIR_HOOKS_TARGET etc/skel-desktop/.config/systemd/user/managed-external-software-notify.service)" \
  "$software_notify_service" \
  0644
software_stage_seed_asset \
  "$(installer_repo_join_var DIR_HOOKS_TARGET etc/skel-desktop/.config/systemd/user/managed-external-software-notify.path)" \
  "$software_notify_path" \
  0644

run_in_target "enable managed external software update units" /bin/sh -eu -c '
systemctl --root=/ enable managed-external-software-download.timer >/dev/null
systemctl --root=/ is-enabled managed-external-software-download.timer >/dev/null
systemctl --root=/ enable managed-external-software-update.timer >/dev/null
systemctl --root=/ is-enabled managed-external-software-update.timer >/dev/null
' sh

software_cleanup_work_dir
trap - EXIT HUP INT TERM
