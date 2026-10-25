#!/bin/sh
# Native appearance assets; no source builds or session-policy changes.

desktop_stage_appearance() (
  set -eu
  for directory in \
    /usr/local/lib \
    /usr/local/lib/python3.14 \
    /usr/local/lib/python3.14/dist-packages \
    /usr/local/lib/python3.14/dist-packages/managed_workflows \
    /usr/local/lib/python3.14/dist-packages/labwc_appearance \
    /usr/local/libexec \
    /usr/local/share \
    /usr/local/share/labwc-appearance \
    /usr/share/polkit-1/actions
  do
    ensure_target_asset_parent "${directory}/.installer-directory"
    directory_host=$(target_asset_host_path "$directory")
    [ -d "$directory_host" ] && [ ! -L "$directory_host" ] ||
      installer_fatal "unsafe appearance asset directory: ${directory}"
    chown root:root "$directory_host"
    chmod 0755 "$directory_host"
  done
  desktop_stage_role_asset usr/local/bin/labwc-desktop-appearance /usr/local/bin/labwc-desktop-appearance 0755
  for helper in labwc-appearance-defaults labwc-appearance-greeter labwc-appearance-themes; do
    desktop_stage_role_asset "usr/local/libexec/$helper" "/usr/local/libexec/$helper" 0755
  done
  for module in __init__ fs process; do
    path="usr/local/lib/python3.14/dist-packages/managed_workflows/$module.py"
    desktop_stage_role_asset "$path" "/$path" 0644
  done
  for module in __init__ catalog cli defaults editors engine greeter native service theme_archive theme_assets theme_install theme_resources themes transaction; do
    path="usr/local/lib/python3.14/dist-packages/labwc_appearance/$module.py"
    desktop_stage_role_asset "$path" "/$path" 0644
  done
  desktop_stage_role_asset usr/share/polkit-1/actions/org.labwc.desktop-appearance.policy \
    /usr/share/polkit-1/actions/org.labwc.desktop-appearance.policy 0644
)

desktop_extract_theme_release() (
  set -eu
  source_host=$1
  archive_host="${TMP_ENV_DIR}/desktop-themes.tar.gz"
  archive_max_bytes=${LABWC_DESKTOP_THEMES_MAXIMUM_BYTES:?LABWC_DESKTOP_THEMES_MAXIMUM_BYTES must be set}
  trap 'rm -f -- "$archive_host"' EXIT HUP INT TERM

  desktop_download_release_archive \
    'desktop themes' \
    "$LABWC_DESKTOP_THEMES_TAG" \
    "$LABWC_DESKTOP_THEMES_URL" \
    "$LABWC_DESKTOP_THEMES_SHA256" \
    desktop-themes.tar.gz \
    "$archive_host" \
    "$archive_max_bytes"

  /usr/bin/tar \
    --extract \
    --gzip \
    --file "$archive_host" \
    --directory "$source_host" \
    --strip-components=1 \
    --no-same-owner \
    --no-same-permissions \
    --no-overwrite-dir ||
    installer_fatal 'desktop theme release extraction failed'
  find -P "$source_host" -type d -exec chmod 0700 {} +
  find -P "$source_host" -type f -exec chmod 0600 {} +
  chown -R root:root "$source_host"
  desktop_log "extracted_verified_release label=desktop-themes tag=${LABWC_DESKTOP_THEMES_TAG}"
)

desktop_install_appearance_themes() (
  set -eu
  source_root=/usr/local/share/labwc-appearance/.installer-themes
  source_host=$(target_asset_host_path "$source_root")
  [ ! -e "$source_host" ] && [ ! -L "$source_host" ] ||
    installer_fatal "theme installation staging already exists; retained evidence: ${source_root}"
  ensure_target_asset_parent "${source_root}/.anchor"
  [ -d "$source_host" ] && [ ! -L "$source_host" ] ||
    installer_fatal 'unsafe desktop theme staging directory'
  chown root:root "$source_host"
  chmod 0700 "$source_host"
  desktop_extract_theme_release "$source_host"
  run_in_target "install pinned GTK3/GTK4 and Qt desktop theme data" \
    /usr/local/libexec/labwc-appearance-themes --install
)

desktop_capture_appearance_defaults() {
  run_in_target "capture rendered installation appearance defaults" \
    /usr/local/libexec/labwc-appearance-defaults --capture
}

desktop_verify_appearance_assets() {
  # Target installation boundary before consumer enablement. Inspect source
  # and assets as data, without importing or invoking a managed module.
  run_in_target "verify installed desktop theme providers and reset defaults" \
    /usr/bin/python3 -I -S -B -c '
import ast
import configparser
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import time

deadline = time.monotonic() + 120
def require(condition, message):
    if not condition:
        raise SystemExit("fatal: desktop appearance contract: " + message)

def read(path, mode, limit):
    require(time.monotonic() < deadline, "asset inspection deadline")
    for parent in path.parents:
        info = parent.lstat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022,
                "unsafe asset parent")
    info = path.lstat()
    modes = (mode,) if isinstance(mode, int) else mode
    require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_gid == 0
            and info.st_nlink == 1 and stat.S_IMODE(info.st_mode) in modes
            and 0 <= info.st_size <= limit, "unsafe asset metadata: " + str(path))
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    require(len(data) == info.st_size, "asset changed or exceeded read budget")
    return data

package = Path("/usr/local/lib/python3.14/dist-packages/labwc_appearance")
modules = ("__init__", "catalog", "cli", "defaults", "editors", "engine", "greeter", "native",
           "service", "theme_archive", "theme_assets", "theme_install",
           "theme_resources", "themes", "transaction")
brands = set()
for module in modules:
    path = package / (module + ".py")
    text = read(path, 0o644, 256 * 1024).decode("utf-8")
    require(re.search(r"__[A-Z][A-Z0-9_]{2,}__", text) is None, "unresolved appearance token")
    tree = ast.parse(text, filename=str(path))
    if module == "themes":
        brands = {node.args[0].value for node in ast.walk(tree)
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                  and node.func.id == "_family" and node.args and isinstance(node.args[0], ast.Constant)}
require(len(brands) == 20, "invalid desktop theme family catalog")
for helper in ("labwc-appearance-defaults", "labwc-appearance-greeter", "labwc-appearance-themes"):
    path = Path("/usr/local/libexec") / helper
    ast.parse(read(path, 0o755, 16384).decode("utf-8"), filename=str(path))

registry = Path("/usr/local/share/labwc-appearance")
pending = registry / "themes-install-pending.json"
require(not pending.exists() and not pending.is_symlink(), "theme publication needs recovery")
manifest = json.loads(read(registry / "themes.json", 0o644, 6 * 1024**2))
require(isinstance(manifest, dict) and manifest.get("schema") == 1
        and isinstance(manifest.get("variants"), dict) and len(manifest["variants"]) == 50
        and isinstance(manifest.get("files"), dict) and 0 < len(manifest["files"]) <= 24000,
        "incomplete theme inventory")
families = set()
for identity, directories in manifest["variants"].items():
    require(isinstance(identity, str) and re.fullmatch(r"[a-z][a-z0-9-]{0,79}", identity) is not None
            and isinstance(directories, list), "invalid theme identifier")
    family = next((name for name in brands if identity.startswith(name + "-")), None)
    require(family is not None, "unknown theme family")
    families.add(family)
    gtk = "themes/Labwc-" + identity
    kvantum = "Kvantum/Labwc-" + identity
    expected = ([] if family == "adwaita" else [gtk])
    if family not in ("adwaita", "breeze"):
        expected.append(kvantum)
    require(directories == expected, "incorrect GTK/Qt provider pairing")
    if family != "adwaita":
        for version in ("3.0", "4.0"):
            require(gtk + "/gtk-" + version + "/gtk.css" in manifest["files"], "missing GTK provider")
    if family not in ("adwaita", "breeze"):
        for extension in (".kvconfig", ".svg"):
            require(kvantum + "/Labwc-" + identity + extension in manifest["files"], "missing Qt provider")
require(families == brands, "desktop theme brands were counted as variants")
total = 0
for relative, metadata in manifest["files"].items():
    path = PurePosixPath(relative)
    require(not path.is_absolute() and str(path) == relative and len(path.parts) <= 32
            and all(part not in ("", ".", "..", "gtk-2.0") for part in path.parts)
            and path.parts[0] in ("themes", "Kvantum", "doc"), "unsafe installed asset path")
    require(isinstance(metadata, dict) and type(metadata.get("bytes")) is int
            and 0 <= metadata["bytes"] <= 16 * 1024**2
            and isinstance(metadata.get("sha256"), str)
            and re.fullmatch(r"[0-9a-f]{64}", metadata["sha256"]) is not None, "invalid asset descriptor")
    total += metadata["bytes"]
    require(total <= 512 * 1024**2, "aggregate theme asset budget")
    blob = read(Path("/usr/share") / relative, 0o644, metadata["bytes"])
    require(hashlib.sha256(blob).hexdigest() == metadata["sha256"], "installed asset hash differs")
packages = manifest.get("packages", {})
require(isinstance(packages, dict) and isinstance(packages.get("plugins"), dict)
        and len(packages["plugins"]) == 7, "missing Qt5/Qt6 style and frontend plugins")
for relative, digest in packages["plugins"].items():
    require(re.fullmatch(r"lib/[A-Za-z0-9_+-]+/qt[56]/plugins/(?:styles/[A-Za-z0-9_.]+|platformthemes/libqt[56]ct.so)",
                        relative) is not None, "invalid Qt plugin path")
    require(hashlib.sha256(read(Path("/usr") / relative, (0o644, 0o755), 16 * 1024**2)).hexdigest() == digest,
            "installed Qt plugin hash differs")
defaults = json.loads(read(registry / "defaults.json", 0o644, 8 * 1024**2))
require(defaults.get("schema") in (1, 2) and isinstance(defaults.get("files"), dict),
        "missing captured installation defaults")
session_environment = read(Path("/etc/skel-desktop/.config/labwc/environment.d/10-wayland.env"),
                           0o644, 65536).decode("utf-8").splitlines()
require(session_environment.count("QT_QPA_PLATFORMTHEME=qt6ct") == 1,
        "the desktop platform theme must remain qt6ct")
for config in (Path("/etc/xdg/qt6ct/qt6ct.conf"),
               Path("/etc/skel-desktop/.config/qt6ct/qt6ct.conf")):
    text = read(config, 0o644, 65536).decode("utf-8")
    require(re.search(r"__[A-Z][A-Z0-9_]{2,}__", text) is None, "unresolved qt6ct token")
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.read_string(text)
    require(parser.get("Appearance", "style") in ("Adwaita", "Adwaita-Dark", "Breeze", "kvantum"),
            "invalid default Qt6 style")
print("Verified 20 theme families, 50 GTK3/GTK4 and Qt variants, and captured reset defaults.")
'
}
