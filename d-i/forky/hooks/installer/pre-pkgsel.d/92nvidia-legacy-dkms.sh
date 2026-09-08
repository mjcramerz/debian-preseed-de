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
  temp_path=
  add_string_include=0
  patch_of_gpio_include=0

  [ -r "$header_path" ] || {
    printf 'fatal: recognized NVIDIA 580 header is not readable: %s\n' "$header_path" >&2
    return 1
  }

  if grep -Fq 'NV_INSTALLER_NVIDIA_LEGACY_STRING_COMPAT' "$header_path" &&
     ! grep -Fq '#include <linux/string.h>' "$header_path"; then
    printf 'fatal: incomplete NVIDIA 580 string compatibility rewrite: %s\n' "$header_path" >&2
    return 1
  fi
  if ! grep -Fq '#include <linux/string.h>' "$header_path"; then
    add_string_include=1
  fi

  if ! grep -Fq 'NV_INSTALLER_NVIDIA_LEGACY_OF_GPIO_COMPAT' "$header_path" &&
     grep -Fq '#include <linux/of_gpio.h>' "$header_path"; then
    patch_of_gpio_include=1
  fi

  if [ "$add_string_include" -eq 0 ] && [ "$patch_of_gpio_include" -eq 0 ]; then
    return 0
  fi

  temp_path=$(mktemp "${header_path}.tmp.XXXXXX") || {
    printf 'fatal: cannot allocate NVIDIA 580 header rewrite next to: %s\n' "$header_path" >&2
    return 1
  }
  if ! cp -p "$header_path" "$temp_path"; then
    rm -f "$temp_path"
    printf 'fatal: cannot preserve NVIDIA 580 header metadata: %s\n' "$header_path" >&2
    return 1
  fi

  if ! LC_ALL=C awk \
    -v add_string_include="$add_string_include" \
    -v patch_of_gpio_include="$patch_of_gpio_include" '
    {
      if (patch_of_gpio_include == 1 && $0 == "#include <linux/of_gpio.h>") {
        of_gpio_rewrites++
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
      if (add_string_include == 1 && $0 == "#include \"conftest.h\"") {
        string_insertions++
        print "#include <linux/string.h>"
        print "/* NV_INSTALLER_NVIDIA_LEGACY_STRING_COMPAT */"
      }
    }
    END {
      if (add_string_include == 1 && string_insertions != 1) exit 41
      if (patch_of_gpio_include == 1 && of_gpio_rewrites != 1) exit 42
    }
  ' "$header_path" >"$temp_path"; then
    rm -f "$temp_path"
    printf '%s\n' "fatal: cannot transform recognized NVIDIA 580 header: $header_path (expected one conftest include anchor and one legacy GPIO include when required)" >&2
    return 1
  fi

  if ! mv -f "$temp_path" "$header_path"; then
    rm -f "$temp_path"
    printf 'fatal: cannot publish NVIDIA 580 header rewrite atomically: %s\n' "$header_path" >&2
    return 1
  fi
}

patch_legacy_nvidia_source_tree() {
  for source_root in \
    /usr/src/nvidia-580.* \
    /usr/src/nvidia-current-580.* \
    /var/lib/dkms/nvidia/580.*/source \
    /var/lib/dkms/nvidia/580.*/build
  do
    [ -e "$source_root" ] || continue
    for header_path in \
      "$source_root/common/inc/nv-linux.h" \
      "$source_root/kernel-open/common/inc/nv-linux.h"
    do
      [ -e "$header_path" ] || continue
      patch_nv_linux_header "$header_path" || {
        printf 'fatal: failed to patch NVIDIA 580 source header before DKMS compilation: %s\n' "$header_path" >&2
        return 1
      }
    done
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
