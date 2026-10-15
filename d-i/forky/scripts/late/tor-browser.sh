#!/bin/sh
# Sourced only by the Software installer after its class/architecture gates.

software_install_tor_browser() (
  tor_version=${SOFTWARE_TOR_BROWSER_VERSION:?SOFTWARE_TOR_BROWSER_VERSION must be set}
  tor_url=${SOFTWARE_TOR_BROWSER_URL:?SOFTWARE_TOR_BROWSER_URL must be set}
  tor_sha=${SOFTWARE_TOR_BROWSER_SHA256:?SOFTWARE_TOR_BROWSER_SHA256 must be set}
  tor_key_sha=${SOFTWARE_TOR_BROWSER_KEY_SHA256:?SOFTWARE_TOR_BROWSER_KEY_SHA256 must be set}
  software_validate_release_version SOFTWARE_TOR_BROWSER_VERSION "$tor_version"
  software_validate_sha256 SOFTWARE_TOR_BROWSER_SHA256 "$tor_sha"
  software_validate_sha256 SOFTWARE_TOR_BROWSER_KEY_SHA256 "$tor_key_sha"
  [ "$tor_url" = "https://dist.torproject.org/torbrowser/${tor_version}/tor-browser-linux-x86_64-${tor_version}.tar.xz" ] ||
    software_fatal "Tor Browser URL differs from the pinned release"
  tor_archive="${work_dir}/tor-browser.tar.xz"
  tor_signature="${work_dir}/tor-browser.tar.xz.asc"
  tor_key=/usr/local/share/software/tor-browser/developers.asc
  software_stage_seed_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/share/software/tor-browser/developers.asc)" \
    "$tor_key" 0644
  software_stage_seed_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/libexec/tor-browser-install)" \
    /usr/local/libexec/tor-browser-install 0755
  software_download "Tor Browser" "$tor_url" "$tor_archive" 100000000 167772160 artifact dist.torproject.org
  software_download "Tor Browser signature" "${tor_url}.asc" "$tor_signature" 100 16384 signature dist.torproject.org
  run_in_target "authenticate and install Tor Browser" /bin/sh -eu -c '
    umask 077
    archive=$1; signature=$2; key=$3; expected=$4; key_expected=$5
    key_actual=$(sha256sum "$key"); [ "${key_actual%% *}" = "$key_expected" ]
    actual=$(sha256sum "$archive"); [ "${actual%% *}" = "$expected" ]
    key_home=$(mktemp -d /tmp/installer-software/tor-verify.XXXXXX)
    trap '\''rm -rf -- "$key_home"'\'' 0
    trap '\''exit 129'\'' HUP
    trap '\''exit 130'\'' INT
    trap '\''exit 143'\'' TERM
    /usr/bin/gpg --batch --no-options --homedir "$key_home" --dearmor \
      --output "$key_home/developers.gpg" "$key"
    /usr/bin/gpgv --homedir "$key_home" --keyring "$key_home/developers.gpg" \
      --status-fd 1 "$signature" "$archive" >"$key_home/status"
    /usr/bin/awk '\''$1 == "[GNUPG:]" && $2 == "VALIDSIG" &&
      ($3 == "EF6E286DDA85EA2A4BA7DE684E2C6E8793298290" || $NF == "EF6E286DDA85EA2A4BA7DE684E2C6E8793298290") { valid++ }
      END { exit valid != 1 }'\'' "$key_home/status"
    /usr/bin/python3 -I -B /usr/local/libexec/tor-browser-install "$archive" "$expected"
  ' sh "$tor_archive" "$tor_signature" "$tor_key" "$tor_sha" "$tor_key_sha"
  # The root-owned immutable bundle is maintained through release pins and
  # installer publication; never permit a browser-owned binary replacement.
  software_stage_seed_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET opt/tor-browser/Browser/distribution/policies.json)" \
    /opt/tor-browser/Browser/distribution/policies.json 0644
  software_stage_seed_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/libexec/tor-browser-run)" \
    /usr/local/libexec/tor-browser-run 0755
  software_stage_seed_asset \
    "$(installer_repo_join_var DIR_HOOKS_TARGET usr/local/share/applications/tor-browser.desktop)" \
    /usr/local/share/applications/tor-browser.desktop 0644
  # Firefox uses the distribution FFmpeg library for H.264/AAC. Check the
  # actual target ABI and decoders, not merely the ffmpeg command's presence.
  # This is installer target execution with dropped privileges, never a host
  # test or a decode of untrusted media. No alternate-release libraries load.
  run_in_target "verify Tor Browser system media decoders" \
    /usr/bin/env -i PATH=/usr/bin:/bin LANG=C.UTF-8 \
    /usr/sbin/runuser -u "$ACCOUNT_USERNAME" -- /usr/bin/python3 -I -B -c '
import ctypes
library = ctypes.CDLL("/usr/lib/x86_64-linux-gnu/libavcodec.so.62")
library.avcodec_find_decoder_by_name.argtypes = [ctypes.c_char_p]
library.avcodec_find_decoder_by_name.restype = ctypes.c_void_p
required = {
    "h264": ("h264",), "aac": ("aac",), "mp3": ("mp3", "mp3float"),
    "flac": ("flac",), "opus": ("opus", "libopus"),
    "vp8": ("vp8", "libvpx"), "vp9": ("vp9", "libvpx-vp9"),
    "av1": ("libdav1d", "libaom-av1", "av1"),
}
missing = [name for name, alternatives in required.items()
           if not any(library.avcodec_find_decoder_by_name(decoder.encode("ascii"))
                      for decoder in alternatives)]
if missing:
    raise SystemExit("Tor Browser system media decoders missing: " + ", ".join(missing))
print("Tor Browser FFmpeg ABI 62 decoder availability: " + ", ".join(required))
'
  chroot "$target_root" /usr/bin/desktop-file-validate /usr/local/share/applications/tor-browser.desktop
  software_info "installed authenticated Tor Browser version=${tor_version} sha256=${tor_sha}"
)
