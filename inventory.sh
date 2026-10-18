#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P) || {
  printf '%s\n' 'inventory: cannot resolve script directory' >&2
  exit 1
}

if [ -f "$script_dir/d-i/forky/preseed.cfg" ]; then
  repo_root=$script_dir
elif [ -f "$script_dir/debian-preseed-de/d-i/forky/preseed.cfg" ]; then
  repo_root=$script_dir/debian-preseed-de
else
  printf '%s\n' 'inventory: expected d-i/forky/preseed.cfg beside the script or in ./debian-preseed-de' >&2
  exit 2
fi

if ! command -v python3 >/dev/null 2>&1; then
  printf '%s\n' 'inventory: python3 is required to scan repository text files' >&2
  exit 127
fi

exec python3 - "$repo_root" "$script_dir" "$@" <<'PYTHON_SCANNER'
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


MAX_TEXT_FILE = 16 * 1024 * 1024
MAX_SNIPPET = 360
SKIP_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", ".tox", ".venv", "venv", "node_modules",
}
SKIP_SUFFIXES = {
    ".7z", ".a", ".appimage", ".bin", ".bz2", ".class", ".deb", ".dll",
    ".docx", ".gif", ".gz", ".ico", ".img", ".iso", ".jar", ".jpeg",
    ".jpg", ".mo", ".mp3", ".mp4", ".o", ".pdf", ".png", ".pyc",
    ".so", ".svgz", ".tar", ".tgz", ".webp", ".whl", ".xz", ".zip",
    ".zst",
}
TEXT_SUFFIXES = {
    ".bash", ".cfg", ".conf", ".desktop", ".env", ".hook", ".install",
    ".json", ".list", ".lock", ".md", ".patch", ".pl", ".pm", ".pref", ".py",
    ".rules", ".service", ".sh", ".sources", ".target", ".template",
    ".timer", ".toml", ".tmpl", ".txt", ".xml", ".yaml", ".yml", ".zsh",
}
SOURCE_DIRS = {"classes", "fragments", "hooks", "hosts", "scripts", "tools"}
EXCLUDED_OPERATION_PARTS = {"doc", "docs", "fixtures", "tests"}
URL_RE = re.compile(r"https?://[^\s<>\"'`]+", re.IGNORECASE)
GIT_CLONE_RE = re.compile(
    r"""(?ix)(?:\bgit\s+clone\b|\bgit['\"]?\s*,\s*.*?['\"]clone['\"]|\bgit\s*\(\s*['\"]clone['\"]|\bmanaged_git_ssh_target_action\s+clone-[A-Za-z0-9_-]+)"""
)
PRIVATE_GITLAB_RE = re.compile(
    r"(?:git@gitlab\.com:[A-Za-z0-9_.:/-]+|ssh://git@gitlab\.com/[A-Za-z0-9_.:/-]+)",
    re.IGNORECASE,
)
VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)|\$([A-Za-z_][A-Za-z0-9_]*)")
SECRET_NAME_RE = re.compile(
    r"(?i)(?:password|passwd|token|secret|credential|api[_-]?key|access[_-]?key|private[_-]?key|passphrase)"
)
SECRET_ASSIGN_RE = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:PASSWORD|PASSWD|TOKEN|SECRET|CREDENTIALS?|API_KEY|ACCESS_KEY|PRIVATE_KEY|PASSPHRASE)[A-Z0-9_]*\s*(?:=|:)\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
BEARER_RE = re.compile(r"(?i)\b(Bearer\s+)[A-Za-z0-9._~+/-]+=*")
APT_LOCAL_RE = re.compile(
    r"^\s*(?P<comment>#\s*)?d-i\s+apt-setup/local(?P<number>\d+)/(?P<field>[a-z0-9_-]+)\s+\S+\s*(?P<value>.*?)\s*$",
    re.IGNORECASE,
)
PKGSEL_RE = re.compile(r"^\s*d-i\s+pkgsel/include\s+string\s+(.+?)\s*$", re.IGNORECASE)
SHELL_ASSIGN_RE = re.compile(
    r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*(?:\+?=|:=)\s*(.*?)\s*$"
)
URL_QUERY_SAFE = {"app", "arch", "channel", "download", "platform", "source", "variant", "version"}


def fail(message: str) -> None:
    print(f"inventory: {message}", file=sys.stderr)
    raise SystemExit(1)


def md_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def shorten(value: str, limit: int = MAX_SNIPPET) -> str:
    value = " ".join(value.split())
    if len(value) > limit:
        return value[: limit - 3] + "..."
    return value


def safe_url(value: str) -> str:
    value = value.rstrip(".,;:)]}")
    try:
        parts = urlsplit(value)
    except ValueError:
        return "<URL omitted: malformed or credential-bearing>"
    if not parts.scheme or not parts.netloc:
        return value
    host = parts.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    try:
        if parts.port:
            host = f"{host}:{parts.port}"
    except ValueError:
        return "<URL omitted: malformed or credential-bearing>"
    query_parts = []
    for item in parts.query.split("&") if parts.query else []:
        key, separator, query_value = item.partition("=")
        if key.lower() in URL_QUERY_SAFE:
            query_parts.append(key + (separator + query_value if separator else ""))
        else:
            query_parts.append(key + ("=<redacted>" if separator else ""))
    query = "&".join(query_parts)
    fragment = "<redacted>" if parts.fragment else ""
    return urlunsplit((parts.scheme, host, parts.path, query, fragment))


def safe_text(value: str) -> str:
    if "-----BEGIN " in value and "PRIVATE KEY-----" in value:
        return "<private key material redacted>"
    value = URL_RE.sub(lambda match: safe_url(match.group(0)), value)
    value = SECRET_ASSIGN_RE.sub(r"\1<redacted>", value)
    value = BEARER_RE.sub(r"\1<redacted>", value)
    return shorten(value)


def is_candidate(path: Path) -> bool:
    name = path.name.lower()
    if name.endswith((".tar.gz", ".tar.xz", ".tar.bz2", ".payload")):
        return False
    if path.suffix.lower() in SKIP_SUFFIXES:
        return False
    if name in {"makefile", "gnumakefile", "justfile"}:
        return True
    if name.endswith(".env") or path.suffix.lower() in TEXT_SUFFIXES:
        return True
    return any(part in SOURCE_DIRS for part in path.parts)


def is_operational(path: Path) -> bool:
    if any(part.lower() in EXCLUDED_OPERATION_PARTS for part in path.parts):
        return False
    return not path.name.lower().endswith((".md", ".md.tmpl", ".rst"))


def logical_lines(lines: list[str]) -> list[tuple[int, int, str]]:
    result: list[tuple[int, int, str]] = []
    start = 0
    parts: list[str] = []
    for number, line in enumerate(lines, 1):
        piece = line.rstrip()
        continuing = piece.endswith("\\")
        if not parts:
            start = number
        parts.append(piece[:-1].rstrip() if continuing else piece)
        if not continuing:
            result.append((start, number, " ".join(part for part in parts if part)))
            parts = []
    if parts:
        result.append((start, len(lines), " ".join(part for part in parts if part)))
    return result


def path_ref(path: Path, line: int | None = None) -> str:
    rel = path.relative_to(root).as_posix()
    return f"`{rel}:{line}`" if line is not None else f"`{rel}`"


def class_context(path: Path) -> str:
    parts = path.relative_to(root).parts
    if "class-apps" in parts:
        return "optional app class"
    if "class-addon" in parts:
        return "optional add-on class"
    if "class-auto" in parts:
        return "automatic hardware class"
    if "class-profile" in parts:
        return "storage/profile class"
    if "class-select" in parts:
        return "selected role/security/network/site class"
    if "fragments" in parts:
        return "shared installer fragment"
    return "configuration context shown by path"


if len(sys.argv) < 3:
    fail("internal invocation error")
root = Path(sys.argv[1]).resolve(strict=True)
script_dir = Path(sys.argv[2]).resolve(strict=True)
parser = argparse.ArgumentParser(
    prog="inventory.sh",
    description="Create a deterministic JSON inventory of APT packages, repositories, keys, hooks, downloads, clones, kernels, and variables.",
    epilog="The scanner reads repository files as data. It does not run installer code or access the network.",
)
parser.add_argument(
    "--no-private",
    action="store_true",
    help="omit private git@gitlab.com:* SSH repositories and source lines that use their variables",
)
parser.add_argument(
    "--output",
    metavar="FILE",
    type=Path,
    default=script_dir / "inventory.json",
    help="write JSON to FILE (default: inventory.json beside this script)",
)
args = parser.parse_args(sys.argv[3:])
output_arg = args.output
if output_arg.is_symlink():
    fail("refusing to replace a symbolic-link output")
try:
    output = output_arg.parent.resolve(strict=True) / output_arg.name
except OSError as exc:
    fail(f"output directory is unavailable: {type(exc).__name__}")
if not output.name or output.name in {".", ".."}:
    fail("output must name a file")
if output == root or root in output.parents:
    if output != root / "inventory.json":
        fail("refusing to overwrite repository sources; use inventory.json at the repository root")
if not (root / "d-i/forky/preseed.cfg").is_file():
    fail("repository marker d-i/forky/preseed.cfg is missing")
if not output.parent.is_dir():
    fail("output directory does not exist")

manifest_rel = Path("d-i/forky/payload.manifest")
manifest_path = root / manifest_rel
manifest_members: list[str] = []
manifest_invalid_paths: list[dict[str, int | str]] = []
manifest_state = "missing"
if not manifest_path.is_symlink() and manifest_path.is_file():
    manifest_state = "read"
    try:
        if manifest_path.stat().st_size > MAX_TEXT_FILE:
            fail("payload manifest exceeds the configured text-file limit")
        with manifest_path.open("r", encoding="utf-8") as manifest_stream:
            for line_number, line in enumerate(manifest_stream, 1):
                fields = line.rstrip("\n").split(None, 1)
                if not fields:
                    continue
                if len(fields) != 2:
                    manifest_invalid_paths.append({"line": line_number, "path": "[missing member path]"})
                    continue
                member = fields[1].removeprefix("*")
                member_path = Path(member)
                if member_path.is_absolute() or ".." in member_path.parts or "\\" in member:
                    manifest_invalid_paths.append({"line": line_number, "path": safe_text(member)})
                    continue
                manifest_members.append(member_path.as_posix())
    except (OSError, UnicodeError) as exc:
        fail(f"cannot read payload manifest paths: {type(exc).__name__}")
manifest_members = sorted(set(manifest_members))
manifest_member_set = set(manifest_members)


def manifest_member_for_source(path: Path) -> bool:
    rel = path.relative_to(root).as_posix()
    prefix = "d-i/forky/"
    return rel.startswith(prefix) and rel[len(prefix):] in manifest_member_set

files: list[Path] = []
for current, dirs, names in os.walk(root, topdown=True, followlinks=False):
    base = Path(current)
    dirs[:] = sorted(
        name for name in dirs
        if name not in SKIP_DIRS and not (base / name).is_symlink()
    )
    for name in sorted(names):
        path = base / name
        if not is_candidate(path) or path.is_symlink() or not path.is_file():
            continue
        if path.resolve(strict=False) == output or name == "inventory.sh":
            continue
        files.append(path)
files.sort(key=lambda item: item.relative_to(root).as_posix())

contents: dict[Path, tuple[list[str], list[tuple[int, int, str]]]] = {}
skipped: list[str] = []
for path in files:
    try:
        size = path.stat().st_size
        if size > MAX_TEXT_FILE:
            skipped.append(f"{path.relative_to(root).as_posix()} (over {MAX_TEXT_FILE} bytes)")
            continue
        raw = path.read_bytes()
    except OSError as exc:
        skipped.append(f"{path.relative_to(root).as_posix()} (read error: {type(exc).__name__})")
        continue
    if b"\0" in raw:
        skipped.append(f"{path.relative_to(root).as_posix()} (binary content)")
        continue
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        skipped.append(f"{path.relative_to(root).as_posix()} (non-UTF-8 content)")
        continue
    lines = text.splitlines()
    contents[path] = (lines, logical_lines(lines))

config_paths = sorted(
    (path for path in contents if path.name.lower().endswith((".cfg", ".env"))),
    key=lambda item: item.relative_to(root).as_posix(),
)

pkg_declarations: dict[str, list[tuple[Path, int]]] = defaultdict(list)
repo_parts: dict[tuple[Path, str], dict[str, tuple[int, str, bool]]] = defaultdict(dict)
variable_definitions: dict[str, list[tuple[Path, int, str]]] = defaultdict(list)
urls: dict[str, set[tuple[Path, int]]] = defaultdict(set)
private_gitlab_urls: dict[str, set[tuple[Path, int]]] = defaultdict(set)
private_vars: set[str] = set()
private_var_values: dict[str, list[str]] = defaultdict(list)
remote_lines: dict[tuple[Path, int, int, str], set[str]] = {}
apt_commands: dict[tuple[Path, int, int, str], set[str]] = {}
kernel_lines: dict[tuple[Path, int, str], None] = {}
hook_paths: set[Path] = set()
pref_paths: set[Path] = set()

for path, (lines, _logical) in contents.items():
    if not is_operational(path):
        continue
    for line_number, line in enumerate(lines, 1):
        for private_match in PRIVATE_GITLAB_RE.finditer(line):
            private_url = private_match.group(0).rstrip(".,;:)]}")
            private_gitlab_urls[private_url].add((path, line_number))
            urls[private_url].add((path, line_number))
        assignment = SHELL_ASSIGN_RE.match(line)
        if assignment:
            variable, value = assignment.groups()
            variable_definitions[variable].append((path, line_number, value))
            private_var_values[variable].append(value)
            if PRIVATE_GITLAB_RE.search(value):
                private_vars.add(variable)

changed = True
while changed:
    changed = False
    for variable, values in private_var_values.items():
        if variable in private_vars:
            continue
        if any(
            (first or second) in private_vars
            for value in values
            for first, second in VAR_RE.findall(value)
        ):
            private_vars.add(variable)
            changed = True

private_gitlab_source_paths = {
    path
    for locations in private_gitlab_urls.values()
    for path, _line in locations
}

for path, (lines, logical) in contents.items():
    rel = path.relative_to(root).as_posix()
    for line_number, line in enumerate(lines, 1):
        match = PKGSEL_RE.match(line) if path.suffix.lower() == ".cfg" else None
        if match:
            for package in match.group(1).split():
                if package not in {"\\"}:
                    pkg_declarations[package].append((path, line_number))
        match = APT_LOCAL_RE.match(line) if path.suffix.lower() == ".cfg" else None
        if match:
            number = match.group("number")
            field = match.group("field").lower()
            commented = bool(match.group("comment"))
            repo_parts[(path, number)][field] = (line_number, match.group("value"), commented)
        if is_operational(path):
            if re.search(r"pin-priority|^\s*(?:Package|Pin):", line, re.IGNORECASE):
                pref_paths.add(path)
            if any(mark in rel for mark in ("/pre-pkgsel.d/", "/base-stage.d/", "/apt-setup/", "/finish-install.d/")):
                hook_paths.add(path)
            if re.search(r"(?i)linux-(?:image|headers|xanmod)|kernel\.org|kernel.{0,30}(?:\.deb|\.tar|download)", line):
                kernel_lines[(path, line_number, safe_text(line))] = None

    if not is_operational(path):
        continue
    for start, end, statement in logical:
        sanitized = safe_text(statement)
        has_url = bool(URL_RE.search(statement))
        has_private_gitlab = bool(PRIVATE_GITLAB_RE.search(statement))
        has_git_clone = bool(GIT_CLONE_RE.search(statement))
        has_fetch = bool(re.search(
            r"(?i)\b(?:curl|wget|aria2c|git\s+(?:fetch|checkout|switch|tag)|gh\s+release\s+download|pipx?\s+download|urlopen|fetch_url|download_file)\b",
            statement,
        )) or has_git_clone
        has_url_assignment = bool(re.search(
            r"(?i)(?:^|\s)(?:[A-Za-z_][A-Za-z0-9_]*(?:_URL|_URI)|URL|URI|DOWNLOAD_URL|ARCHIVE_URL|KEY_URL|REPOSITORY_URL)\s*=",
            statement,
        ))
        has_integrity = bool(re.search(
            r"(?i)\b(?:sha(?:256|384|512)sum|checksum|gpg\s+--verify|gpgv|minisign|cosign|sigstore)\b|\.(?:asc|sig|sha256|sha512)\b",
            statement,
        ))
        variables = set(
                (first or second) for first, second in VAR_RE.findall(statement)
                if (first or second) not in {"HOME", "PWD", "OLDPWD", "IFS"}
            )
        assignment = SHELL_ASSIGN_RE.match(statement)
        if assignment and (has_url or has_private_gitlab or has_url_assignment or has_integrity):
            variables.add(assignment.group(1))
        if has_git_clone:
            if path.suffix.lower() == ".py":
                variables.update({"url", "branch"})
            clone_action = re.search(
                r"\bmanaged_git_ssh_target_action\s+clone-([A-Za-z0-9_-]+)",
                statement,
                re.IGNORECASE,
            )
            if clone_action:
                clone_slug = clone_action.group(1).replace("-", "_").lower()
                variables.update(
                    name for name in variable_definitions
                    if name.lower() in {
                        f"{clone_slug}_url", f"{clone_slug}_uri", f"{clone_slug}_branch",
                        f"{clone_slug}_tag", f"{clone_slug}_commit", f"{clone_slug}_revision",
                        f"{clone_slug}_sha", f"{clone_slug}_checksum", f"{clone_slug}_hash",
                    }
                    or re.search(
                        rf"(?:^|_){re.escape(clone_slug)}(?:_git)?_repository_(?:url|uri|branch|tag|commit|revision|sha|checksum|hash)$",
                        name,
                        re.IGNORECASE,
                    )
                )
            for name, definitions in variable_definitions.items():
                if name.lower().endswith(("_url", "_uri", "_branch", "_tag", "_commit", "_revision", "_sha", "_checksum", "_hash")) and any(
                    definition_path == path for definition_path, _line, _value in definitions
                ):
                    variables.add(name)
            if re.search(r"\bgit\s*\(\s*['\"]clone['\"]", statement, re.IGNORECASE):
                variables.add("args.arguments")
        if has_url or has_private_gitlab or has_fetch or has_url_assignment or has_integrity:
            remote_lines[(path, start, end, sanitized)] = variables
        for match in URL_RE.finditer(statement):
            urls[safe_url(match.group(0))].add((path, start))
        if re.search(r"(?i)\b(?:apt-get|apt)\b.*\binstall\b|\bpipx?\s+install\b|\bcargo\s+install\b|\bgo\s+install\b|\bdpkg\s+-i\b", statement):
            apt_commands[(path, start, end, sanitized)] = set(
                (first or second) for first, second in VAR_RE.findall(statement)
                if (first or second) not in {"HOME", "PWD", "OLDPWD", "IFS"}
            )

repo_records: list[dict[str, str | bool]] = []
for (path, number), fields in sorted(
    repo_parts.items(), key=lambda item: (item[0][0].relative_to(root).as_posix(), int(item[0][1]))
):
    repository = fields.get("repository")
    if not repository:
        continue
    _, repository_value, commented = repository
    comment = fields.get("comment", (0, "", commented))[1]
    key = fields.get("key", (0, "", commented))[1]
    source = fields.get("source", (0, "", commented))[1]
    repo_records.append({
        "path": path,
        "number": number,
        "line": repository[0],
        "url": safe_text(repository_value),
        "comment": safe_text(comment),
        "key": safe_text(key),
        "source": safe_text(source),
        "active": not commented,
    })

def repository_matches_package(record: dict[str, str | bool], package: str) -> bool:
    """Use explicit archive identities; generic comment-word matches are unsafe."""
    raw_url = str(record["url"]).split()[0]
    try:
        parsed = urlsplit(raw_url)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    path = parsed.path.lower()
    name = package.lower()
    if host == "3proxy.org":
        return name == "3proxy"
    if host == "wayscriber.com":
        return name == "wayscriber"
    if host == "pkgs.tailscale.com":
        return name == "tailscale"
    if host == "packagecloud.io" and "/crowdsec/" in path:
        return name == "crowdsec"
    if host == "repository.mullvad.net":
        return name == "mullvad-browser"
    if host == "packages.microsoft.com" and "/repos/code" in path:
        return name == "code"
    if host == "packages.microsoft.com" and "/repos/edge" in path:
        return name == "microsoft-edge-stable"
    if host == "packages.microsoft.com" and "/debian/13/prod" in path:
        return name == "powershell"
    if host == "repo.mysql.com":
        return name == "mysql-shell"
    if host == "repository.spotify.com":
        return name == "spotify-client"
    if host == "repo.vivaldi.com":
        return name == "vivaldi-stable"
    if host == "developer.download.nvidia.com" and "/compute/cuda/" in path:
        return name.startswith(("cuda-", "libcu", "libnv", "libnpp", "libnccl"))
    if host == "pkgs.zabbly.com" and "/incus/" in path:
        return name == "incus"
    if host == "mise.jdx.dev":
        return name == "mise"
    if host == "pkg.cloudflare.com":
        return name == "cloudflared"
    if host == "deb.xanmod.org":
        return name.startswith("linux-xanmod-")
    return False


repo_map: dict[str, set[str]] = defaultdict(set)
for package, declarations in pkg_declarations.items():
    for path, _line in declarations:
        local = [record for record in repo_records if record["path"] == path and record["active"]]
        for record in local:
            rel = path.relative_to(root).as_posix()
            exact_app_class = "/class-apps/" in f"/{rel}"
            if exact_app_class or repository_matches_package(record, package):
                label = f"{record['comment'] or record['url']} ({record['url']}; {rel} apt-setup/local{record['number']})"
                repo_map[package].add(label)
    for record in repo_records:
        if record["active"] and repository_matches_package(record, package):
            rel = record["path"].relative_to(root).as_posix()
            label = f"{record['comment'] or record['url']} ({record['url']}; {rel} apt-setup/local{record['number']})"
            repo_map[package].add(label)

all_repo_urls = {str(record["url"]) for record in repo_records if record["active"]}

class_entries: list[dict[str, str]] = []
install_conf = next((path for path in contents if path.relative_to(root).as_posix().endswith("/classes/install.conf")), None)
if install_conf:
    lines, _ = contents[install_conf]
    block: dict[str, str] = {}
    for line in lines + [""]:
        if not line.strip():
            if block.get("Type") == "class":
                class_entries.append(block)
            block = {}
            continue
        if line.lstrip().startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        block[key.strip()] = value.strip()


def source_record(path: Path, line: int | None = None) -> dict[str, str | int | bool]:
    rel = path.relative_to(root).as_posix()
    result: dict[str, str | int | bool] = {"path": rel}
    if line is not None:
        result["line"] = line
    if rel.startswith("d-i/forky/"):
        result["payload_manifest_member"] = rel[len("d-i/forky/"):] in manifest_member_set
    return result


package_records = []
for package in sorted(pkg_declarations, key=str.lower):
    declarations = sorted(
        {(path.relative_to(root).as_posix(), line) for path, line in pkg_declarations[package]},
    )
    origins = sorted(repo_map.get(package, set()), key=str.lower)
    suite = package.rsplit("/", 1)[1] if "/" in package else None
    package_records.append({
        "name": package,
        "package": package.rsplit("/", 1)[0] if suite else package,
        "target_suite": suite if suite in {"bookworm", "trixie", "forky", "sid", "experimental"} else None,
        "apt_origin_candidates": origins,
        "origin_resolution": "source_declared_or_exact_vendor_mapping" if origins else "requires_installer_apt_resolution",
        "selection_contexts": sorted({class_context(path) for path, _line in pkg_declarations[package]}),
        "declarations": [
            {
                "path": path_name,
                "line": line,
                "payload_manifest_member": manifest_member_for_source(root / path_name),
            }
            for path_name, line in declarations
        ],
    })

class_records = []
for entry in sorted(class_entries, key=lambda item: (item.get("Group", ""), item.get("Name", ""))):
    class_records.append({
        "id": f"{entry.get('Group', '?')}/{entry.get('Name', '?')}",
        "description": entry.get("Description", ""),
        "requires_classes": entry.get("RequiresClasses", "").split(),
        "rejected_classes": entry.get("RejectedClasses", "").split(),
        "apt_preferences": entry.get("DebianAptPreferences", "").split(),
        "late_helper": entry.get("LateHelper") or None,
        "metadata_source": source_record(install_conf) if install_conf else None,
    })

apt_archives = []
for record in repo_records:
    apt_archives.append({
        "state": "active_declaration" if record["active"] else "commented_inactive",
        "comment": str(record["comment"]),
        "repository": str(record["url"]),
        "key_url": str(record["key"]),
        "source_packages_enabled": str(record["source"]).lower() == "true",
        "definition": {
            **source_record(record["path"], int(record["line"])),
            "local_id": f"local{record['number']}",
        },
        "selection_context": class_context(record["path"]),
    })

base_setting_re = re.compile(
    r"(?i)(?:mirror/(?:https|http)/(?:hostname|mirror|directory)|"
    r"apt-setup/(?:services-select|security_host|security_path|use_mirror|backports|non-free|contrib|non-free-firmware)|"
    r"base-installer/install-recommends|pkgsel/(?:include|install-recommends|upgrade)|"
    r"APT::(?:Default-Release|Install-Recommends|Install-Suggests))"
)
base_settings = []
for path, (lines, _logical) in contents.items():
    if not is_operational(path) or path.relative_to(root).as_posix() == "d-i/forky/preseed.cfg":
        continue
    for number, line in enumerate(lines, 1):
        if base_setting_re.search(line) and not line.lstrip().startswith("#"):
            base_settings.append({"source": source_record(path, number), "text": safe_text(line)})

installed_sources = []
for path, (lines, _logical) in contents.items():
    if not is_operational(path) or not (path.name.endswith(".sources") or path.name.endswith(".list")):
        continue
    if path.name.endswith(".sources"):
        paragraph: dict[str, str] = {}
        start_line = 1
        for number, line in enumerate(lines + [""], 1):
            if not line.strip():
                if paragraph:
                    installed_sources.append({"source": source_record(path, start_line), "fields": paragraph})
                    paragraph = {}
                start_line = number + 1
                continue
            if line.lstrip().startswith("#") or ":" not in line:
                continue
            key, value = line.split(":", 1)
            paragraph[key.strip()] = safe_text(value.strip())
    else:
        for number, line in enumerate(lines, 1):
            if line.strip() and not line.lstrip().startswith("#"):
                installed_sources.append({"source": source_record(path, number), "line": safe_text(line)})

preference_re = re.compile(r"(?i)^\s*(?:Package|Pin|Pin-Priority):")
preference_records = []
for path in sorted(pref_paths, key=lambda item: item.relative_to(root).as_posix()):
    lines = contents[path][0]
    rules = [
        {"line": number, "text": safe_text(line)}
        for number, line in enumerate(lines, 1)
        if preference_re.search(line)
    ]
    if rules:
        preference_records.append({"source": source_record(path), "rules": rules})

apt_policy_re = re.compile(
    r"(?i)(?:APT::Default-Release|APT::Install-Recommends|APT::Install-Suggests|"
    r"pkgsel/install-recommends|pkgsel/upgrade|base-installer/install-recommends|"
    r"apt-setup/(?:services-select|use_mirror|backports|non-free|contrib|non-free-firmware)|"
    r"allow_unauthenticated)"
)
apt_policy = []
for path, (lines, _logical) in contents.items():
    if not is_operational(path):
        continue
    for number, line in enumerate(lines, 1):
        if apt_policy_re.search(line) and not line.lstrip().startswith("#"):
            apt_policy.append({"source": source_record(path, number), "text": safe_text(line)})

HOOK_SUMMARIES = {
    "10-apt-install-policy": "Stages no-Recommends/no-Suggests APT policy before target package selection.",
    "49nvidia-opt-in-firmware.sh": "Keeps the installer NVIDIA firmware cache only when the selected NVIDIA add-on is detected; otherwise removes cached NVIDIA firmware packages.",
    "88temporary-os-prober.sh": "For the dualboot add-on, installs an installer-only os-prober shim; target probing is deferred to the controlled late GRUB step.",
    "89temporary-unshare.sh": "Installs a temporary target unshare shim using dpkg-divert during the installer transaction.",
    "90secure-boot-dkms.sh": "Installs target mokutil through APT if absent, stages Secure Boot tooling, and prepares DKMS before pkgsel.",
    "91cuda-legacy-apt.sh": "For selected legacy CUDA, stages its NVIDIA Debian 12 repository and refreshes target APT metadata before pkgsel.",
    "92nvidia-legacy-dkms.sh": "For selected legacy NVIDIA with detected hardware, stages and applies the managed DKMS compatibility wrapper.",
    "98-cuda-legacy-source": "Defers legacy CUDA source publication until the selected-class pre-pkgsel refresh.",
    "99-apt-preferences": "Stages class-specific APT preference files before apt-setup configures target sources.",
    "95-normalize-apt": "Normalizes target APT policy and removes installer CD-ROM source entries before handoff.",
}
hook_match_re = re.compile(
    r"(?i)apt-get|apt-setup|apt preferences|apt_preferences|Pin-Priority|"
    r"installer_cuda_stage|apt update|apt-get update|mokutil|os-prober|unshare|"
    r"firmware|nvidia|cuda|repository|apt source|cdrom|default-release"
)
hook_records = []
for path in sorted(hook_paths, key=lambda item: item.relative_to(root).as_posix()):
    matched = [
        {"line": number, "text": safe_text(line)}
        for number, line in enumerate(contents[path][0], 1)
        if hook_match_re.search(line)
    ]
    relative_parts = path.relative_to(root).parts
    installer_index = relative_parts.index("installer") if "installer" in relative_parts else -1
    hook_stage = "/".join(relative_parts[installer_index + 1:]) if installer_index >= 0 else ""
    order_match = re.match(r"(\d+)", path.name)
    hook_records.append({
        "stage": hook_stage,
        "execution_order": int(order_match.group(1)) if order_match else None,
        "source": source_record(path),
        "summary": HOOK_SUMMARIES.get(path.name, "Inspect the cited hook for package/repository effects."),
        "relevant_source_lines": matched[:24],
    })

install_records = []
for (path, start, end, statement), variables in sorted(
    apt_commands.items(), key=lambda item: (item[0][0].relative_to(root).as_posix(), item[0][1])
):
    install_records.append({
        "source": source_record(path, start),
        "line_end": end,
        "command": statement,
        "variables": sorted(variables),
    })

external_records = []
filtered_private_source_records = 0
for (path, start, end, statement), variables in sorted(
    remote_lines.items(), key=lambda item: (item[0][0].relative_to(root).as_posix(), item[0][1])
):
    is_git_clone = bool(GIT_CLONE_RE.search(statement))
    is_private = bool(
        PRIVATE_GITLAB_RE.search(statement)
        or variables.intersection(private_vars)
        or (is_git_clone and path in private_gitlab_source_paths)
    )
    if args.no_private and is_private:
        filtered_private_source_records += 1
        continue
    if is_git_clone:
        kind = "git_clone"
    elif re.search(r"(?i)\bgit\s+(?:fetch|checkout|switch|tag)\b", statement):
        kind = "git_operation"
    elif re.search(r"(?i)\b(?:sha(?:256|384|512)sum|checksum|gpg\s+--verify|gpgv|minisign|cosign|sigstore)\b|\.(?:asc|sig|sha256|sha512)\b", statement):
        kind = "integrity_check_or_signing_key"
    elif re.search(r"(?i)\b(?:curl|wget|aria2c|urlopen|fetch_url|download_file|gh\s+release\s+download)\b", statement):
        kind = "download"
    else:
        kind = "url_reference"
    literal_urls = [safe_url(match.group(0)) for match in URL_RE.finditer(statement)]
    literal_urls.extend(match.group(0).rstrip(".,;:)]}") for match in PRIVATE_GITLAB_RE.finditer(statement))
    source_is_dynamic = is_git_clone and not literal_urls and not any(
        variable.lower() == "url" or variable.lower().endswith(("_url", "_uri"))
        for variable in variables
    )
    external_records.append({
        "kind": kind,
        "source": source_record(path, start),
        "line_end": end,
        "reference": statement,
        "urls": sorted(set(literal_urls), key=str.lower),
        "variables": sorted(variables - (private_vars if args.no_private else set())),
        "source_is_dynamic": source_is_dynamic,
        "private_gitlab_ssh": is_private,
        "requires_private_ssh_auth": is_private,
        "private_auth_requirement": "unknown" if source_is_dynamic else ("required" if is_private else "not_indicated"),
    })

url_records = []
for url in sorted(urls, key=str.lower):
    if args.no_private and url in private_gitlab_urls:
        continue
    url_records.append({
        "url": url,
        "private_gitlab_ssh": url in private_gitlab_urls,
        "locations": [
            source_record(path, line)
            for path, line in sorted(urls[url], key=lambda item: (item[0].relative_to(root).as_posix(), item[1]))
        ],
    })

kernel_packages = [
    record for record in package_records
    if re.search(r"(?i)(?:^linux-(?:image|headers|xanmod)|kernel|dkms|firmware-)", record["name"])
]
kernel_references = [
    {"source": source_record(path, line), "text": text}
    for path, line, text in sorted(kernel_lines, key=lambda item: (item[0].relative_to(root).as_posix(), item[1]))
]

used_variables = sorted(
    {
        name
        for (_path, _start, _end, _statement), names in remote_lines.items()
        if not args.no_private or not names.intersection(private_vars)
        for name in names
        if not (args.no_private and name in private_vars)
    },
    key=str.lower,
)
environment_variables = []
for name in used_variables:
    definitions = []
    for path, line, value in variable_definitions.get(name, []):
        if SECRET_NAME_RE.search(name):
            safe_value = "[redacted]"
        elif re.search(r"(?i)(?:url|uri|version|release|branch|tag|commit|revision|ref|pin|sha(?:256|384|512)?|hash|checksum|digest|fingerprint)", name):
            safe_value = safe_text(value)
        else:
            safe_value = "[value omitted]"
        definitions.append({"source": source_record(path, line), "value": safe_value})
    uses = []
    for (path, start, _end, _statement), names in remote_lines.items():
        if name in names and not (args.no_private and names.intersection(private_vars)):
            uses.append(source_record(path, start))
    environment_variables.append({
        "name": name,
        "definitions": definitions,
        "uses": sorted(uses, key=lambda item: (item["path"], item.get("line", 0))),
    })

private_repo_count = len(private_gitlab_urls)
inventory = {
    "schema_version": 1,
    "repository": {
        "root": ".",
        "text_files_scanned": len(contents),
    },
    "filters": {
        "no_private": bool(args.no_private),
        "private_gitlab_ssh_literals_detected": private_repo_count,
        "private_gitlab_ssh_source_records_omitted": filtered_private_source_records,
        "private_gitlab_ssh_literals_omitted": private_repo_count if args.no_private else 0,
    },
    "apt": {
        "pkgsel_packages": package_records,
        "base_and_global_settings": base_settings,
        "repositories_and_signing_keys": apt_archives,
        "installed_source_files": installed_sources,
        "preferences": preference_records,
        "policy_settings": apt_policy,
        "installer_hooks": hook_records,
        "package_install_commands_outside_pkgsel": install_records,
        "repository_interpretation": "APT source declarations and explicit archive mappings are inventory evidence; exact package version origin requires the selected class set and target APT indexes.",
    },
    "classes": class_records,
    "external_sources": external_records,
    "url_literals": url_records,
    "kernel_firmware_dkms": {
        "pkgsel_packages": kernel_packages,
        "source_references": kernel_references,
    },
    "environment": {
        "configuration_files": [
            path.relative_to(root).as_posix()
            for path in config_paths
            if path.name.lower().endswith(".env")
        ],
        "variables_used_by_external_sources": environment_variables,
    },
    "coverage": {
        "configuration_files": [path.relative_to(root).as_posix() for path in config_paths],
        "skipped_files": sorted(skipped),
        "payload_manifest": {
            "source": manifest_rel.as_posix(),
            "state": manifest_state,
            "hashes_used": False,
            "members": manifest_members,
            "configuration_members": [
                member for member in manifest_members
                if member.lower().endswith((".cfg", ".env"))
            ],
            "source_configuration_files_not_listed": [
                path.relative_to(root).as_posix()
                for path in config_paths
                if path.relative_to(root).as_posix().startswith("d-i/forky/")
                and not manifest_member_for_source(path)
            ],
            "invalid_paths": manifest_invalid_paths,
        },
        "limits": [
            "Package version and exact origin resolution depends on the selected classes, target architecture, generated APT preferences, and signed indexes available during installation.",
            "Conditional APT source definitions may reuse local IDs across mutually exclusive classes; source records retain their defining file and class path.",
            "The scanner identifies literal URLs, common transfer commands, URL variables, Git operations, and integrity references; runtime-computed network destinations require review of the cited caller/helper sources.",
        ],
    },
}

rendered = json.dumps(inventory, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
try:
    fd, temp_name = tempfile.mkstemp(prefix=".inventory.", dir=output.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(rendered)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, output)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise
except OSError as exc:
    fail(f"cannot write JSON inventory: {type(exc).__name__}")

print(
    f"inventory: JSON written; scanned {len(contents)} text files, "
    f"including {len(config_paths)} .cfg/.env files; "
    f"pkgsel packages={len(package_records)}, APT sources={len(apt_archives)}, "
    f"external references={len(external_records)}, private GitLab SSH literals={private_repo_count}"
)
