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

patch_nv_os_interface() {
  os_interface_path=$1
  os_interface_temp=

  [ -r "$os_interface_path" ] || {
    printf 'fatal: recognized NVIDIA 580 OS interface is not readable: %s\n' "$os_interface_path" >&2
    return 1
  }

  # Linux 7.2 removed strncpy; adding linux/string.h cannot restore it.
  # Replace only the complete, known process-name function, never every
  # strncpy call. strscpy_pad uses the FULL buffer size and preserves the old
  # NUL padding and task lock, without the len == 0 underflow of buf[len - 1].
  # Accept our exact result (with or without its marker) on subsequent runs.
  # Reject unknown/partial functions before publishing any source changes.
  os_interface_transform='
    BEGIN {
      signature = "voidNV_API_CALLos_get_current_process_name(char*buf,NvU32len)"
      old_body = signature "{task_lock(current);strncpy(buf,current->comm,len-1);" \
        "buf[len-1]=" sprintf("%c", 39) "\\0" sprintf("%c", 39) ";task_unlock(current);}"
      new_body = signature "{task_lock(current);strscpy_pad(buf,current->comm,len);task_unlock(current);}"
    }
    /^[[:space:]]*void[[:space:]]+NV_API_CALL[[:space:]]+os_get_current_process_name[[:space:]]*\(/ {
      functions++
      inside = 1
      body = ""
    }
    inside {
      body = body $0 "\n"
      if ($0 ~ /^[[:space:]]*}[[:space:]]*$/) {
        inside = 0
        normalized = body
        gsub(/[[:space:]]/, "", normalized)
        markers = gsub(/\/\*NV_INSTALLER_NVIDIA_LEGACY_STRNCPY_COMPAT\*\//, "", normalized)
        if (normalized == old_body && markers == 0) {
          rewrites++
          print "void NV_API_CALL os_get_current_process_name(char *buf, NvU32 len)"
          print "{"
          print "    task_lock(current);"
          print "    /* NV_INSTALLER_NVIDIA_LEGACY_STRNCPY_COMPAT */"
          print "    strscpy_pad(buf, current->comm, len);"
          print "    task_unlock(current);"
          print "}"
        } else if (normalized == new_body && markers <= 1) {
          printf "%s", body
        } else {
          exit 41
        }
        validated++
      }
      next
    }
    { print }
    END {
      if (inside || functions != 1 || validated != 1) exit 42
      if (check_only && rewrites) exit 10
    }
  '
  # Read-only DKMS operations must still work on an already-patched tree.
  # Validate the whole function, not just the marker, before skipping writes.
  if LC_ALL=C awk -v check_only=1 "$os_interface_transform" "$os_interface_path" >/dev/null; then
    return 0
  else
    case $? in
      10) ;; # Validated legacy body: perform the atomic rewrite below.
      *)
        printf 'fatal: unrecognized NVIDIA 580 os_get_current_process_name; source left unchanged: %s\n' "$os_interface_path" >&2
        return 1
        ;;
    esac
  fi

  os_interface_temp=$(mktemp "${os_interface_path}.tmp.XXXXXX") || {
    printf 'fatal: cannot allocate NVIDIA 580 OS interface rewrite: %s\n' "$os_interface_path" >&2
    return 1
  }
  if ! cp -p "$os_interface_path" "$os_interface_temp"; then
    rm -f "$os_interface_temp"
    printf 'fatal: cannot preserve NVIDIA 580 OS interface metadata: %s\n' "$os_interface_path" >&2
    return 1
  fi

  if ! LC_ALL=C awk "$os_interface_transform" "$os_interface_path" >"$os_interface_temp"; then
    rm -f "$os_interface_temp"
    printf 'fatal: unrecognized NVIDIA 580 os_get_current_process_name; source left unchanged: %s\n' "$os_interface_path" >&2
    return 1
  fi

  if cmp -s "$os_interface_path" "$os_interface_temp"; then
    rm -f "$os_interface_temp"
    return 0
  fi
  if ! mv -f "$os_interface_temp" "$os_interface_path"; then
    rm -f "$os_interface_temp"
    printf 'fatal: cannot publish NVIDIA 580 OS interface rewrite atomically: %s\n' "$os_interface_path" >&2
    return 1
  fi
  printf 'Applied NVIDIA 580 Linux 7.2 process-name compatibility: %s\n' "$os_interface_path" >&2
}

patch_nv_72_interfaces() {
  # perl-base is Essential on Debian. No non-core modules or network access.
  # Validate every affected file before publishing any of this batch. Keep the
  # proprietary OS-interface symbols/return values, unlike the open-driver PR.
  LC_ALL=C perl - "$1" <<'NV72_PERL'
use strict;
use warnings;
use Fcntl qw(O_WRONLY O_CREAT O_EXCL);

my $root = shift @ARGV;
my (%original, %result, %metadata);
my @order;
sub load_file {
    my ($relative) = @_;
    my $path = "$root/$relative";
    return undef unless -e $path || -l $path;
    die "fatal: NVIDIA compatibility file is not a regular non-symlink: $path\n"
        if -l $path || !-f $path;
    open my $in, '<', $path or die "fatal: cannot read $path: $!\n";
    binmode $in;
    local $/;
    my $text = <$in>;
    my @st = stat $in;
    close $in or die "fatal: cannot close $path: $!\n";
    $metadata{$relative} = [@st];
    $original{$relative} = $text;
    $result{$relative} = $text;
    push @order, $relative;
    return $text;
}
sub normalized {
    my ($text) = @_;
    $text =~ s/\s+//g;
    return $text;
}
sub replace_once {
    my ($text, $old, $new, $label) = @_;
    my $count = ($$text =~ s/$old/$new/g);
    die "fatal: expected one NVIDIA 580 $label, found $count\n" unless $count == 1;
}
sub bounded_wrapper {
    my ($text, $name, $count_type, $count_name) = @_;
    my $signature = qr/\bchar\s*\*\s*\Q$name\E\s*\(\s*char\s*\*\s*dest\s*,\s*const\s+char\s*\*\s*src\s*,\s*\Q$count_type\E\s+\Q$count_name\E\s*\)/;
    my $body = <<"C_BODY";
{
    /* NV_INSTALLER_NVIDIA_LEGACY_BOUNDED_COPY: preserve the binary ABI. */
    size_t copied;

    if ($count_name == 0)
        return dest;
    copied = strnlen(src, $count_name);
    if (copied != 0)
        memcpy(dest, src, copied);
    if (copied < $count_name)
        memset(dest + copied, 0, $count_name - copied);
    return dest;
}
C_BODY
    my @matches = ($$text =~ /($signature)\s*(\{[^{}]*\})/g);
    die "fatal: missing or duplicate NVIDIA 580 $name definition\n" unless @matches == 2;
    my ($sig, $actual) = @matches;
    my $old = "{return strncpy(dest,src,$count_name);}";
    if (normalized($actual) eq normalized($body)) {
        return;
    }
    die "fatal: unrecognized NVIDIA 580 $name body; source left unchanged\n"
        unless normalized($actual) eq normalized($old);
    replace_once($text, qr/\Q$sig\E\s*\Q$actual\E/, "$sig\n$body", $name);
}

my $rel = 'nvidia/linux_nvswitch.c';
if (defined(my $text = load_file($rel))) {
    if ($text =~ /\bstrncpy\s*\(/ || $text =~ /NV_INSTALLER_NVIDIA_LEGACY_BOUNDED_COPY/) {
        if ($text =~ /\bstrncpy\s*\(\s*regkey_val\b/) {
            # This is a checked substring, not a NUL-terminated source string.
            # strscpy(..., regkey_val_len) would lose the last hex digit.
            die "fatal: NVSwitch registry bound check not recognized\n"
                unless $text =~ /regkey_val\s*\[\s*NVSWITCH_REGKEY_VALUE_LEN\s*\+\s*1\s*\]/
                && $text =~ /regkey_val_len\s*>\s*NVSWITCH_REGKEY_VALUE_LEN/;
            replace_once(\$text,
                qr/\bstrncpy\s*\(\s*regkey_val\s*,\s*regkey_val_start\s*,\s*regkey_val_len\s*\);\s*regkey_val\s*\[\s*regkey_val_len\s*\]\s*=\s*'\\0'\s*;/,
                "memcpy(regkey_val, regkey_val_start, regkey_val_len);\n    regkey_val[regkey_val_len] = '\\0';",
                'NVSwitch registry substring copy');
        }
        bounded_wrapper(\$text, 'nvswitch_os_strncpy', 'NvLength', 'length');
        $result{$rel} = $text;
    }
}
$rel = 'nvidia-modeset/nvidia-modeset-linux.c';
if (defined(my $text = load_file($rel))) {
    if ($text =~ /\bstrncpy\s*\(/ || $text =~ /NV_INSTALLER_NVIDIA_LEGACY_BOUNDED_COPY/) {
        bounded_wrapper(\$text, 'nvkms_strncpy', 'size_t', 'n');
        $result{$rel} = $text;
    }
}
$rel = 'nvidia-uvm/uvm_pmm_gpu.c';
if (defined(my $text = load_file($rel))) {
    if ($text =~ /\bstrncpy\s*\(/) {
        replace_once(\$text,
            qr/\bstrncpy\s*\(\s*chunk_split_cache\s*\[\s*level\s*\]\.name\s*,\s*"uvm_gpu_chunk_t"\s*,\s*sizeof\s*\(\s*chunk_split_cache\s*\[\s*level\s*\]\.name\s*\)\s*-\s*1\s*\);/,
            'strscpy_pad(chunk_split_cache[level].name, "uvm_gpu_chunk_t", sizeof(chunk_split_cache[level].name));',
            'UVM chunk-cache name copy');
        $result{$rel} = $text;
    }
}

# Linux 7.2 renamed the DRM transaction type and its lifetime functions.
# A real sizeof test, not an incomplete-struct pointer, detects the target API.
# Keep the original 580 full-state callbacks selected for the renamed type.
my $drm_case = <<'DRM_CASE';
        nv_installer_drm_atomic_commit_present)
            # NV_INSTALLER_NVIDIA_LEGACY_DRM_PROBE
            CODE="
            #include <drm/drm_atomic.h>
            #include <drm/drm_modeset_helper_vtables.h>
            int conftest_nv_installer_drm_atomic_commit(void) {
                return sizeof(struct drm_atomic_commit);
            }
            static const struct drm_crtc_helper_funcs *crtc_funcs;
            typeof(*crtc_funcs->atomic_check) conftest_nv_installer_crtc;
            int conftest_nv_installer_crtc(struct drm_crtc *crtc,
                                          struct drm_atomic_commit *state) {
                return 0;
            }
            static const struct drm_plane_helper_funcs *plane_funcs;
            typeof(*plane_funcs->atomic_check) conftest_nv_installer_plane;
            int conftest_nv_installer_plane(struct drm_plane *plane,
                                           struct drm_atomic_commit *state) {
                return 0;
            }"
            compile_check_conftest "$CODE" "NV_INSTALLER_DRM_ATOMIC_COMMIT_PRESENT" "" "types"
        ;;
DRM_CASE
my $drm_defines = <<'DRM_DEFINES';
/* NV_INSTALLER_NVIDIA_LEGACY_DRM_ATOMIC_COMPAT */
#if defined(NV_INSTALLER_DRM_ATOMIC_COMMIT_PRESENT)
#define drm_atomic_state drm_atomic_commit
#define drm_atomic_state_alloc drm_atomic_commit_alloc
#define drm_atomic_state_get drm_atomic_commit_get
#define drm_atomic_state_put drm_atomic_commit_put
#define drm_atomic_state_clear drm_atomic_commit_clear
#define __drm_atomic_state_free __drm_atomic_commit_free
#define drm_atomic_state_init drm_atomic_commit_init
#define drm_atomic_state_default_clear drm_atomic_commit_default_clear
#define drm_atomic_state_default_release drm_atomic_commit_default_release
/* The probe also checked BOTH full-transaction callback signatures. */
#undef NV_DRM_CRTC_ATOMIC_CHECK_HAS_ATOMIC_STATE_ARG
#define NV_DRM_CRTC_ATOMIC_CHECK_HAS_ATOMIC_STATE_ARG
#undef NV_DRM_PLANE_ATOMIC_CHECK_HAS_ATOMIC_STATE_ARG
#define NV_DRM_PLANE_ATOMIC_CHECK_HAS_ATOMIC_STATE_ARG
#endif
/* NV_INSTALLER_NVIDIA_LEGACY_DRM_ATOMIC_COMPAT_END */

DRM_DEFINES
my @drm_files = ('conftest.sh', 'nvidia-drm/nvidia-drm-sources.mk',
                 'nvidia-drm/nvidia-drm-conftest.h');
# Minimal/non-DRM source layouts are valid. A partial DRM tree is not.
if (-e "$root/nvidia-drm/nvidia-drm-conftest.h") {
    for my $file (@drm_files) {
        die "fatal: incomplete NVIDIA DRM source tree: $root/$file\n"
            unless defined load_file($file);
    }
    my $text = $result{'conftest.sh'};
    if ($text =~ /NV_INSTALLER_NVIDIA_LEGACY_DRM_PROBE/) {
        die "fatal: incomplete NVIDIA DRM probe\n"
            unless index($text, $drm_case) >= 0
            && scalar(() = $text =~ /NV_INSTALLER_NVIDIA_LEGACY_DRM_PROBE/g) == 1;
    } else {
        replace_once(\$text, qr/^([ \t]*drm_plane_atomic_check_has_atomic_state_arg\)[ \t]*\r?\n)/m,
                     $drm_case . '        drm_plane_atomic_check_has_atomic_state_arg)' . "\n",
                     'DRM conftest anchor');
    }
    $result{'conftest.sh'} = $text;
    my $mk = 'nvidia-drm/nvidia-drm-sources.mk';
    $text = $result{$mk};
    my $line = 'NV_CONFTEST_TYPE_COMPILE_TESTS += nv_installer_drm_atomic_commit_present';
    unless ($text =~ /^\Q$line\E\s*$/m) {
        die "fatal: NVIDIA DRM test list is unrecognized\n"
            unless $text =~ /^NV_CONFTEST_TYPE_COMPILE_TESTS\s*\+=\s*drm_plane_atomic_check_has_atomic_state_arg\s*$/m;
        $text .= "\n$line\n";
    }
    $result{$mk} = $text;
    my $hdr = 'nvidia-drm/nvidia-drm-conftest.h';
    $text = $result{$hdr};
    if ($text =~ /NV_INSTALLER_NVIDIA_LEGACY_DRM_ATOMIC_COMPAT/) {
        die "fatal: incomplete NVIDIA DRM compatibility block\n"
            unless index($text, $drm_defines) >= 0;
    } else {
        replace_once(\$text, qr/^#endif\s*\/\*\s*defined\(__NVIDIA_DRM_CONFTEST_H__\)\s*\*\/[ \t]*\r?$/m,
                     $drm_defines . '#endif /* defined(__NVIDIA_DRM_CONFTEST_H__) */',
                     'DRM compatibility header guard');
    }
    $result{$hdr} = $text;
}

# No more one-error-at-a-time fixes: audit ALL Linux interface C/H files before
# DKMS starts. A previously unseen raw call is an explicit actionable failure.
# Strip comments and strings so documentation and log messages do not match.
sub code_only {
    my ($s) = @_;
    $s =~ s{(/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')}{$1 =~ s/[^\n]/ /gr}gse;
    return $s;
}
sub audit_dir {
    my ($relative) = @_;
    my $dir = "$root/$relative";
    return unless -d $dir;
    opendir my $dh, $dir or die "fatal: cannot audit $dir: $!\n";
    my @names = sort grep { $_ ne '.' && $_ ne '..' } readdir $dh;
    closedir $dh;
    for my $name (@names) {
        my $file = "$relative/$name";
        my $path = "$root/$file";
        if (-d $path && !-l $path) { audit_dir($file); next; }
        next unless $name =~ /\.[ch]$/ && -f $path;
        my $text;
        if (exists $result{$file}) { $text = $result{$file}; }
        else {
            open my $in, '<', $path or die "fatal: cannot audit $path: $!\n";
            local $/; $text = <$in>; close $in;
        }
        my $code = code_only($text);
        if ($code =~ /\bstrncpy\b/) {
            my $before = substr($code, 0, $-[0]);
            my $line = 1 + ($before =~ tr/\n/\n/);
            die "fatal: unhandled removed strncpy API at $path:$line; no DKMS build attempted\n";
        }
    }
}
for my $dir (qw(common/inc nvidia nvidia-modeset nvidia-uvm nvidia-drm nvidia-peermem)) {
    audit_dir($dir);
}

my $temporary;
END { unlink $temporary if defined $temporary && -e $temporary; }
for my $file (@order) {
    next if $result{$file} eq $original{$file};
    my $path = "$root/$file";
    my @st = @{$metadata{$file}};
    my $out;
    for my $attempt (1 .. 100) {
        my $candidate = "$path.nv72.$$.$attempt";
        if (sysopen($out, $candidate, O_WRONLY | O_CREAT | O_EXCL, 0600)) {
            $temporary = $candidate; last;
        }
        die "fatal: cannot stage $path: $!\n" unless $!{EEXIST};
    }
    die "fatal: cannot allocate temporary file for $path\n" unless defined $temporary;
    binmode $out;
    print {$out} $result{$file} or die "fatal: cannot write $temporary: $!\n";
    close $out or die "fatal: cannot close $temporary: $!\n";
    my @tmp_st = stat $temporary;
    if ($tmp_st[4] != $st[4] || $tmp_st[5] != $st[5]) {
        chown($st[4], $st[5], $temporary) == 1 or die "fatal: cannot preserve owner: $!\n";
    }
    chmod($st[2] & 07777, $temporary) == 1 or die "fatal: cannot preserve mode: $!\n";
    rename($temporary, $path) or die "fatal: cannot publish $path: $!\n";
    undef $temporary;
    print STDERR "Applied NVIDIA 580 Linux 7.2 interface compatibility (r2): $path\n";
}
NV72_PERL
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
    for os_interface_path in \
      "$source_root/nvidia/os-interface.c" \
      "$source_root/kernel-open/nvidia/os-interface.c"
    do
      [ -e "$os_interface_path" ] || continue
      patch_nv_os_interface "$os_interface_path" || {
        printf 'fatal: failed to patch NVIDIA 580 OS interface before DKMS compilation: %s\n' "$os_interface_path" >&2
        return 1
      }
    done
    for interface_root in "$source_root" "$source_root/kernel-open"; do
      [ -d "$interface_root" ] || continue
      patch_nv_72_interfaces "$interface_root" || {
        printf 'fatal: NVIDIA 580 Linux 7.2 interface validation failed: %s\n' "$interface_root" >&2
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
