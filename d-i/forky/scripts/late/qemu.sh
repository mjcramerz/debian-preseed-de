#!/bin/sh
set -eu

target_root=${1:-/target}
[ -d "$target_root" ] || exit 0

qemu_fatal() {
  printf 'fatal: %s\n' "$*" >&2
  exit 1
}

qemu_info() {
  printf '[late:qemu] %s\n' "$*" >&2
}

qemu_validate_abs_path() {
  case "${2:-}" in
    /*) ;;
    *) qemu_fatal "$1 must be an absolute path: ${2:-unset}" ;;
  esac
  case "$2" in
    /|*..*|*//*|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/@%:+,-]*)
      qemu_fatal "$1 contains unsupported path syntax: $2"
      ;;
  esac
}

qemu_stage_target_asset() {
  repo_path=$1
  target_path=$2
  mode=$3
  tmp_asset="${tmp_env_dir}/$(basename "$target_path").$$"
  qemu_validate_abs_path "target path" "$target_path"
  bootstrap_fetch_seed_file "$seed_base" "$repo_path" "$tmp_asset" 0600 "qemu asset ${repo_path}"
  install -d -o root -g root -m 0755 "${target_root}$(dirname "$target_path")"
  install -o root -g root -m "$mode" "$tmp_asset" "${target_root}${target_path}"
  rm -f "$tmp_asset"
}

qemu_render_target_asset() {
  repo_path=$1
  target_path=$2
  mode=$3
  shift 3
  tmp_asset="${tmp_env_dir}/$(basename "$target_path").$$"
  tmp_rendered="${tmp_asset}.rendered"
  qemu_validate_abs_path "target path" "$target_path"
  bootstrap_fetch_seed_file "$seed_base" "$repo_path" "$tmp_asset" 0600 "qemu template ${repo_path}"
  installer_apply_scalar_placeholders "$tmp_asset" "$tmp_rendered" "$@"
  if grep -Eq '__INSTALLER_[A-Z0-9_]+__' "$tmp_rendered"; then
    rm -f "$tmp_asset" "$tmp_rendered"
    qemu_fatal "qemu template rendered with unresolved placeholders: ${repo_path}"
  fi
  install -d -o root -g root -m 0755 "${target_root}$(dirname "$target_path")"
  install -o root -g root -m "$mode" "$tmp_rendered" "${target_root}${target_path}"
  rm -f "$tmp_asset" "$tmp_rendered"
}

target_passwd_ids() {
  awk -F: -v wanted_user="$1" \
    '$1 == wanted_user { print $3 ":" $4; exit }' \
    "${target_root}/etc/passwd" 2>/dev/null || true
}

runtime_env_path() {
  for candidate in /tmp/install-env/runtime.env /tmp/install-runtime/state/runtime.env; do
    [ -r "$candidate" ] || continue
    printf '%s\n' "$candidate"
    return 0
  done
  return 1
}

qemu_enable_unit() {
  unit_name=$1
  unit_source=$2
  wants_dir=$3
  [ -r "${target_root}${unit_source}" ] ||
    qemu_fatal "unit source is unavailable: ${unit_source}"
  install -d -m 0755 "${target_root}/etc/systemd/system/${wants_dir}"
  ln -sfn "$unit_source" "${target_root}/etc/systemd/system/${wants_dir}/${unit_name}"
}

qemu_disable_target_unit() {
  unit_name=$1
  case "$unit_name" in
    ''|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789@_.:-]*)
      qemu_fatal "unit name contains unsupported characters: ${unit_name:-unset}"
      ;;
  esac
  for wants_dir in \
    default.target.wants graphical.target.wants multi-user.target.wants
  do
    rm -f -- "${target_root}/etc/systemd/system/${wants_dir}/${unit_name}"
  done
}

runtime_dir=${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}
bootstrap_lib=${INSTALLER_BOOTSTRAP_LIB:-${runtime_dir}/bootstrap/bootstrap.sh}
tmp_env_dir=${INSTALLER_LATE_TMP_ENV_DIR:-/tmp/install-env-late/qemu}

[ -s "$bootstrap_lib" ] || qemu_fatal "installer bootstrap library is unavailable: ${bootstrap_lib}"
# shellcheck disable=SC1090,SC1091
. "$bootstrap_lib"
bootstrap_source_common_lib "" || qemu_fatal "failed to source installer common library"
seed_base=$(installer_current_seed_base 2>/dev/null || installer_seed_base "")
bootstrap_source_common_support_libs "$seed_base" "$tmp_env_dir" fetch hook target ||
  qemu_fatal "failed to source installer late support libraries"
installer_ensure_context_loaded "$seed_base"

installer_selected_class_reference_is_selected addon/qemu 2>/dev/null || exit 0
[ "${INSTALLER_HOST_VARIANT:-}" = desktop ] || qemu_fatal "addon/qemu is restricted to the desktop role"

account_env=${INSTALLER_LATE_ACCOUNT_ENV:-/tmp/install-env-late/account.env}
host_env=${INSTALLER_LATE_HOST_ENV:-/tmp/install-env-late/host.env}
[ -r "$account_env" ] || installer_fetch_account_env "$seed_base" "$account_env" 0600
[ -r "$host_env" ] || installer_fetch_host_env "$seed_base" "$(installer_resolve_host_profile "")" "$host_env" 0600
# shellcheck disable=SC1090,SC1091
. "$account_env"
# shellcheck disable=SC1090,SC1091
. "$host_env"
if runtime_env=$(runtime_env_path); then
  # shellcheck disable=SC1090,SC1091
  . "$runtime_env"
fi

: "${ACCOUNT_USERNAME:?ACCOUNT_USERNAME must be set before staging qemu assets}"
: "${ACCOUNT_HOME:?ACCOUNT_HOME must be set before staging qemu assets}"
: "${DIR_POOL_CACHE:=/pool/cache}"
: "${DIR_POOL_DB:=/pool/db}"
: "${DIR_POOL_QEMU:=/pool/qemu}"
: "${DIR_POOL_INCUS:=/pool/incus}"
: "${INCUS_BRIDGE_NAME:=incusbr0}"
qemu_validate_abs_path ACCOUNT_HOME "$ACCOUNT_HOME"
qemu_validate_abs_path DIR_POOL_CACHE "$DIR_POOL_CACHE"
qemu_validate_abs_path DIR_POOL_DB "$DIR_POOL_DB"
qemu_validate_abs_path DIR_POOL_QEMU "$DIR_POOL_QEMU"
qemu_validate_abs_path DIR_POOL_INCUS "$DIR_POOL_INCUS"
case "$INCUS_BRIDGE_NAME" in
  ''|*[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-]*)
    qemu_fatal "INCUS_BRIDGE_NAME contains unsupported characters"
    ;;
esac

# shellcheck disable=SC2016
run_in_target "verify direct QEMU and Incus package contract" /bin/sh -eu -c '
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH
for package_name in \
  qemu-system-x86 qemu-system-modules-opengl qemu-utils qemu-block-extra \
  ovmf swtpm swtpm-tools virtiofsd passt incus incus-client \
  incus-ui-canonical uidmap libosinfo-bin genisoimage python3
do
  package_status=$(dpkg-query -W -f="\${db:Status-Abbrev}" "$package_name" 2>/dev/null || true)
  [ "$package_status" = "ii " ] || {
    printf "fatal: required QEMU/Incus package is not installed: %s\n" "$package_name" >&2
    exit 1
  }
done
for executable in \
  /usr/bin/qemu-system-x86_64 /usr/bin/qemu-img /usr/bin/incus /usr/bin/curl \
  /opt/incus/lib/systemd/incusd
do
  [ -x "$executable" ] || {
    printf "fatal: required QEMU/Incus executable is missing: %s\n" "$executable" >&2
    exit 1
  }
done
[ -r /opt/incus/ui/index.html ] || {
  printf "%s\n" "fatal: incus-ui-canonical Web UI payload is missing" >&2
  exit 1
}
grep -Fq "INCUS_UI=/opt/incus/ui/" /opt/incus/lib/systemd/incusd || {
  printf "%s\n" "fatal: Incus wrapper does not export its Web UI path" >&2
  exit 1
}
for unit in \
  incus.service incus.socket incus-user.service incus-user.socket \
  incus-startup.service
do
  [ -r "/usr/lib/systemd/system/${unit}" ] || {
    printf "fatal: required Incus unit is missing: %s\n" "$unit" >&2
    exit 1
  }
done
'

qemu_render_target_asset \
  "$(installer_repo_join_var DIR_HOOKS_TARGET etc/default/incus-host-managed.tmpl)" \
  /etc/default/incus-host-managed \
  0644 \
  DIR_POOL_INCUS "$DIR_POOL_INCUS" \
  INCUS_BRIDGE_NAME "$INCUS_BRIDGE_NAME"
qemu_render_target_asset \
  "$(installer_repo_join_var DIR_HOOKS_TARGET etc/tmpfiles.d/85-qemu-incus-storage.conf.tmpl)" \
  /etc/tmpfiles.d/85-qemu-incus-storage.conf \
  0644 \
  DIR_POOL_QEMU "$DIR_POOL_QEMU" \
  DIR_POOL_INCUS "$DIR_POOL_INCUS"
qemu_render_target_asset \
  "$(installer_repo_join_var DIR_HOOKS_TARGET etc/skel/.profile.d/72-incus.sh.tmpl)" \
  /etc/skel/.profile.d/72-incus.sh \
  0644 \
  DIR_POOL_CACHE "$DIR_POOL_CACHE" \
  DIR_POOL_DB "$DIR_POOL_DB"
qemu_render_target_asset \
  "$(installer_repo_join_var DIR_HOOKS_TARGET etc/qemu/bridge.conf.tmpl)" \
  /etc/qemu/bridge.conf \
  0644 \
  INCUS_BRIDGE_NAME "$INCUS_BRIDGE_NAME"
qemu_stage_target_asset \
  "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/libexec/incus-host-managed)" \
  /usr/local/libexec/incus-host-managed \
  0755
qemu_stage_target_asset \
  "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/system/incus-host-managed.service)" \
  /etc/systemd/system/incus-host-managed.service \
  0644
qemu_stage_target_asset \
  "$(installer_repo_join_var DIR_HOOKS_TARGET etc/systemd/system/incus-user.service.d/20-managed-bootstrap.conf)" \
  /etc/systemd/system/incus-user.service.d/20-managed-bootstrap.conf \
  0644
qemu_stage_target_asset \
  "$(installer_repo_join_var DIR_HOOKS_TARGET etc/sysusers.d/swtpm-sysusers.conf)" \
  /etc/sysusers.d/swtpm-sysusers.conf \
  0644

run_in_target "prepare direct QEMU and Incus storage roots" \
  /usr/local/libexec/incus-host-managed --prepare-install

# shellcheck disable=SC2016
run_in_target "grant confined virtualization groups to primary account" /bin/sh -eu -c '
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH
account_user=$1
for group_name in kvm incus; do
  getent group "$group_name" >/dev/null 2>&1 || {
    printf "fatal: required virtualization group is missing: %s\n" "$group_name" >&2
    exit 1
  }
  usermod -a -G "$group_name" -- "$account_user"
done
current_groups=$(id -nG "$account_user")
for group_name in kvm incus; do
  case " $current_groups " in
    *" $group_name "*) ;;
    *)
      printf "fatal: primary account is missing required virtualization group %s: %s\n" \
        "$group_name" "$account_user" >&2
      exit 1
      ;;
  esac
done
case " $current_groups " in
  *" incus-admin "*)
    printf "fatal: primary account must not belong to root-equivalent incus-admin: %s\n" \
      "$account_user" >&2
    exit 1
    ;;
esac
' sh "$ACCOUNT_USERNAME"

account_ids=$(target_passwd_ids "$ACCOUNT_USERNAME")
[ -n "$account_ids" ] || qemu_fatal "primary account is missing from target passwd: ${ACCOUNT_USERNAME}"
account_uid=${account_ids%:*}
account_gid=${account_ids#*:}
install -d -o "$account_uid" -g "$account_gid" -m 0700 "${target_root}${ACCOUNT_HOME}/.profile.d"
install -o "$account_uid" -g "$account_gid" -m 0600 \
  "${target_root}/etc/skel/.profile.d/72-incus.sh" \
  "${target_root}${ACCOUNT_HOME}/.profile.d/72-incus.sh"

for service_unit in \
  incus.service incus-lxcfs.service incus-startup.service incus-user.service \
  incus-host-managed.service
do
  qemu_disable_target_unit "$service_unit"
done
qemu_enable_unit incus.socket /usr/lib/systemd/system/incus.socket sockets.target.wants
qemu_enable_unit incus-user.socket /usr/lib/systemd/system/incus-user.socket sockets.target.wants

qemu_info "staged direct QEMU/KVM and socket-activated confined Incus assets for account=${ACCOUNT_USERNAME}"
