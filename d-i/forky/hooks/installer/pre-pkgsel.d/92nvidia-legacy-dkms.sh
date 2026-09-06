#!/bin/sh
set -eu

RUNTIME_DIR=${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}
BOOTSTRAP_LIB=${INSTALLER_BOOTSTRAP_LIB:-${RUNTIME_DIR}/bootstrap/bootstrap.sh}
TMP_ENV_DIR=/tmp/install-env-pre-pkgsel/nvidia-legacy
LOG=

nvidia_legacy_prepkgsel_fatal() {
  printf '[pre-pkgsel:nvidia-legacy] fatal: %s\n' "$*" >&2
  exit 1
}

[ -s "$BOOTSTRAP_LIB" ] || nvidia_legacy_prepkgsel_fatal "installer bootstrap library is unavailable: ${BOOTSTRAP_LIB}"
# shellcheck disable=SC1090,SC1091
. "$BOOTSTRAP_LIB"
bootstrap_source_common_lib ""

LOG="$(installer_runtime_log_file)"
INSTALLER_DEBUG_LOGS=1
INSTALLER_LOG_LEVEL=debug
export INSTALLER_DEBUG_LOGS INSTALLER_LOG_LEVEL
installer_init_log_file "$LOG" "" "nvidia legacy pre-pkgsel" nvidia-legacy package_install
trap 'installer_finalize_log "$?"' 0
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

SEED_BASE=$(installer_seed_base "")
installer_persist_seed_source "$SEED_BASE"
installer_ensure_context_loaded "$SEED_BASE"

if ! installer_nvidia_legacy_selected 2>/dev/null; then
  installer_info "skipping legacy NVIDIA DKMS bootstrap because addon/nvidia-legacy is not selected"
  exit 0
fi

if ! installer_nvidia_gpu_detected 2>/dev/null; then
  installer_info "skipping legacy NVIDIA DKMS bootstrap because no NVIDIA PCI display adapter was detected"
  exit 0
fi

install -d -m 0700 "$TMP_ENV_DIR"
bootstrap_source_common_support_libs "$SEED_BASE" "$TMP_ENV_DIR" fetch hook target || {
  nvidia_legacy_prepkgsel_fatal "failed to source shared installer helper libraries"
}

wrapper_path=/target/usr/sbin/dkms

cat >"$TMP_ENV_DIR/dkms-wrapper" <<'EOF'
#!/bin/sh
set -eu

patch_nv_linux_header() {
  header_path=$1
  temp_path="${header_path}.tmp.$$"

  [ -r "$header_path" ] || return 1
  grep -Fq '#include <linux/of_gpio.h>' "$header_path" || return 0
  grep -Fq 'NV_INSTALLER_NVIDIA_LEGACY_OF_GPIO_COMPAT' "$header_path" && return 0

  awk '
    {
      if ($0 == "#include <linux/of_gpio.h>") {
        print "#if defined(NV_LINUX_OF_GPIO_H_PRESENT)"
        print "#include <linux/of_gpio.h>"
        print "#else"
        print "#include <linux/gpio/consumer.h>"
        print "/* NV_INSTALLER_NVIDIA_LEGACY_OF_GPIO_COMPAT */"
        print "#define of_get_named_gpio(np, name, index) of_get_named_gpio_flags(np, name, index, NULL)"
        print "#endif"
        next
      }
      print
    }
  ' "$header_path" >"$temp_path"
  mv "$temp_path" "$header_path"
}

patch_legacy_nvidia_source_tree() {
  for source_root in \
    /usr/src/nvidia-580.* \
    /usr/src/nvidia-current-580.* \
    /var/lib/dkms/nvidia/580.*/source \
    /var/lib/dkms/nvidia/580.*/build
  do
    [ -e "$source_root" ] || continue
    patch_nv_linux_header "$source_root/common/inc/nv-linux.h" || true
    patch_nv_linux_header "$source_root/kernel-open/common/inc/nv-linux.h" || true
  done
}

real_dkms=/usr/sbin/dkms.distrib
[ -x "$real_dkms" ] || {
  printf '%s\n' 'fatal: diverted DKMS executable missing: /usr/sbin/dkms.distrib' >&2
  exit 127
}

patch_legacy_nvidia_source_tree
exec "$real_dkms" "$@"
EOF
chmod 0755 "$TMP_ENV_DIR/dkms-wrapper"

run_in_target "reserve dkms diversion for legacy NVIDIA wrapper" /bin/sh -eu -c '
if dpkg-divert --list /usr/sbin/dkms 2>/dev/null | grep -Fq "/usr/sbin/dkms.distrib"; then
  exit 0
fi
dpkg-divert --quiet --local --divert /usr/sbin/dkms.distrib --rename --add /usr/sbin/dkms
' sh

install -d -m 0755 /target/usr/sbin
installer_copy_path_with_mode "$TMP_ENV_DIR/dkms-wrapper" "$wrapper_path" 0755 "legacy NVIDIA dkms wrapper"

run_in_target "verify legacy NVIDIA dkms wrapper" /bin/sh -eu -c '
test -x /usr/sbin/dkms
dpkg-divert --list /usr/sbin/dkms 2>/dev/null | grep -Fq "/usr/sbin/dkms.distrib"
' sh
