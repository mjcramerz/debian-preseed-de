#!/usr/bin/python3
"""
nft-policy-generate.py

Generate Debian nftables configuration from one profile YAML and zero or more
service overlay YAML files.

Design goals:
  - Profile-only generation must work.
  - Overlays are optional and additive.
  - YAML is declarative policy, not raw nftables text.
  - Output is deterministic and safe to validate with `nft -c` before reload.
  - No shell interpolation, no eval, no shell=True.

Requires:
  - Python 3.9+
  - python3-yaml / PyYAML
"""

from __future__ import annotations

import argparse
import copy
import datetime as _dt
import ipaddress
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

try:
    import yaml
except ImportError as exc:  # pragma: no cover - runtime dependency message
    raise SystemExit("Missing dependency: install python3-yaml / PyYAML") from exc

SUPPORTED_API_VERSION = "cybops.nftables/v1"
PROFILE_KIND = "NftablesProfile"
OVERLAY_KIND = "NftablesServiceOverlay"

PROTO_SET = {"tcp", "udp"}
DIRECTION_SET = {"inbound", "outbound", "bidirectional"}
SAFE_IDENT_RE = re.compile(r"[^A-Za-z0-9_]")
NFT_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
INTERFACE_RE = re.compile(r"^[A-Za-z0-9_.:+*-]+$")
RATE_RE = re.compile(r"^[0-9]+/(second|minute|hour|day)( burst [0-9]+ packets)?$")
PORT_RANGE_RE = re.compile(r"^(\d{1,5})-(\d{1,5})$")
UNRESOLVED_RE = re.compile(r"\$\{|<[^>]+>|YOUR_|CHANGE_ME|TODO", re.IGNORECASE)
MAX_YAML_BYTES = 1024 * 1024
DEFAULT_COMMAND_TIMEOUT_SECONDS = 30
NFT_FAMILIES = {"arp", "bridge", "inet", "ip", "ip6", "netdev"}
NFT_NAT_FAMILIES = {"inet", "ip", "ip6"}
EGRESS_MODES = {"allow_all", "allow_all_with_audit", "audit", "enforce", "strict", "deny_by_default"}
DROP_LOG_CHAINS = {"input", "forward", "output"}
DOC_IPV4_NETS = [
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
]
DOC_IPV6_NETS = [ipaddress.ip_network("2001:db8::/32")]
LOG_LEVEL_VALUES = {
    "debug": 10,
    "info": 20,
    "warning": 30,
    "error": 40,
    "none": 99,
}
ACTIVE_LOG_LEVEL = "none"


class PolicyError(Exception):
    """Policy validation or generation error."""


@dataclass
class RenderContext:
    warnings: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def skip(self, message: str) -> None:
        self.skipped.append(message)


def canonical_log_level(level: str) -> str:
    normalized = str(level or "none").strip().lower()
    if normalized == "warn":
        normalized = "warning"
    return normalized if normalized in LOG_LEVEL_VALUES else "none"


def set_log_level(level: str) -> None:
    normalized = str(level or "none").strip().lower()
    if normalized == "warn":
        normalized = "warning"
    if normalized not in LOG_LEVEL_VALUES:
        raise PolicyError("NFTABLES_LOG_LEVEL must be debug, info, warning, error, or none")
    global ACTIVE_LOG_LEVEL
    ACTIVE_LOG_LEVEL = normalized


def log_enabled(level: str) -> bool:
    requested = canonical_log_level(level)
    if requested == "error":
        return True
    active = canonical_log_level(ACTIVE_LOG_LEVEL)
    return active != "none" and LOG_LEVEL_VALUES[requested] >= LOG_LEVEL_VALUES[active]


def eprint(*args: object, level: str = "info") -> None:
    if log_enabled(level):
        print(*args, file=sys.stderr)


def load_yaml_file(path: Path) -> Dict[str, Any]:
    try:
        st = path.stat()
        if not path.is_file():
            raise PolicyError(f"YAML path is not a regular file: {path}")
        if st.st_size > MAX_YAML_BYTES:
            raise PolicyError(f"YAML file exceeds {MAX_YAML_BYTES} bytes: {path}")
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PolicyError(f"cannot read YAML file {path}: {exc}") from exc
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise PolicyError(f"invalid YAML in {path}: {exc}") from exc
    if data is None:
        raise PolicyError(f"empty YAML file: {path}")
    if not isinstance(data, dict):
        raise PolicyError(f"top-level YAML document must be a mapping: {path}")
    return data


def require_kind(doc: Mapping[str, Any], kind: str, path: Path) -> None:
    api_version = doc.get("apiVersion")
    actual_kind = doc.get("kind")
    if api_version != SUPPORTED_API_VERSION:
        raise PolicyError(f"{path}: unsupported apiVersion {api_version!r}; expected {SUPPORTED_API_VERSION!r}")
    if actual_kind != kind:
        raise PolicyError(f"{path}: invalid kind {actual_kind!r}; expected {kind!r}")


def as_dict(value: Any, label: str) -> Dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise PolicyError(f"{label} must be a mapping")
    return value


def as_list(value: Any, label: str) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    raise PolicyError(f"{label} must be a list")


def as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1", "on"}:
            return True
        if lowered in {"false", "no", "0", "off"}:
            return False
    raise PolicyError(f"expected boolean, got {value!r}")


def as_int(value: Any, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise PolicyError(f"{label}: expected integer, got boolean")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise PolicyError(f"{label}: expected integer, got {value!r}") from exc
    if parsed < minimum or parsed > maximum:
        raise PolicyError(f"{label}: {parsed} outside {minimum}..{maximum}")
    return parsed


def safe_ident(name: str) -> str:
    name = SAFE_IDENT_RE.sub("_", str(name).strip())
    name = re.sub(r"_+", "_", name).strip("_")
    if not name:
        raise PolicyError("empty identifier")
    if name[0].isdigit():
        name = "n_" + name
    return name.lower()


def validate_nft_identifier(value: Any, label: str) -> str:
    text = str(value).strip()
    if not NFT_IDENT_RE.fullmatch(text):
        raise PolicyError(f"{label}: invalid nft identifier {value!r}")
    return text


def validate_nft_family(value: Any, label: str, allowed: set[str]) -> str:
    text = str(value).strip().lower()
    if text not in allowed:
        raise PolicyError(f"{label}: unsupported nft family {value!r}; expected one of {sorted(allowed)}")
    return text


def unique_preserve(seq: Iterable[Any]) -> List[Any]:
    out: List[Any] = []
    seen = set()
    for item in seq:
        key = repr(item)
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def deep_merge(base: Any, overlay: Any) -> Any:
    """Generic recursive merge used for nested settings.

    Mappings are merged recursively. Lists are de-duplicated while preserving order.
    Scalars are overwritten by the overlay.
    """
    if isinstance(base, dict) and isinstance(overlay, dict):
        result = copy.deepcopy(base)
        for key, value in overlay.items():
            if key in result:
                result[key] = deep_merge(result[key], value)
            else:
                result[key] = copy.deepcopy(value)
        return result
    if isinstance(base, list) and isinstance(overlay, list):
        return unique_preserve(copy.deepcopy(base) + copy.deepcopy(overlay))
    return copy.deepcopy(overlay)


def merge_overlay(policy: Dict[str, Any], overlay: Dict[str, Any], overlay_path: Path, force: bool, ctx: RenderContext) -> Dict[str, Any]:
    profile_name = str(as_dict(policy.get("metadata"), "metadata").get("name", ""))
    profile_class = str(as_dict(policy.get("metadata"), "metadata").get("profile_class", profile_name))
    overlay_meta = as_dict(overlay.get("metadata"), f"{overlay_path}: metadata")
    applies = overlay_meta.get("applies_to_profiles")
    if applies is not None:
        applies_list = [str(x) for x in as_list(applies, f"{overlay_path}: metadata.applies_to_profiles")]
        if profile_name not in applies_list and profile_class not in applies_list and "*" not in applies_list:
            msg = f"overlay {overlay_path} does not apply to profile {profile_name!r}/{profile_class!r}"
            if force:
                ctx.warn(msg + " (forced)")
            else:
                raise PolicyError(msg)

    for key in ("interface_groups", "cidr_groups", "port_groups", "interfaces", "cidrs", "ports"):
        if key in overlay:
            target = as_dict(policy.setdefault(key, {}), key)
            for group, values in as_dict(overlay[key], f"{overlay_path}: {key}").items():
                target[group] = unique_preserve(as_list(target.get(group), f"{key}.{group}") + as_list(values, f"{overlay_path}: {key}.{group}"))

    if "services" in overlay:
        services = as_dict(policy.setdefault("services", {}), "services")
        for name, service in as_dict(overlay["services"], f"{overlay_path}: services").items():
            services[name] = deep_merge(services.get(name, {}), service)

    if "egress" in overlay:
        policy["egress"] = deep_merge(policy.get("egress", {}), overlay["egress"])
    if "egress_mode_override" in overlay:
        policy["egress"] = deep_merge(policy.get("egress", {}), overlay["egress_mode_override"])

    if "forwarding" in overlay:
        policy["forwarding"] = deep_merge(policy.get("forwarding", {}), overlay["forwarding"])

    if "nat" in overlay:
        policy["nat"] = deep_merge(policy.get("nat", {}), overlay["nat"])

    if "containers" in overlay:
        policy["containers"] = deep_merge(policy.get("containers", {}), overlay["containers"])

    if "logging" in overlay:
        policy["logging"] = deep_merge(policy.get("logging", {}), overlay["logging"])

    return policy


def normalize_port(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise PolicyError(f"{label}: port must be integer, got boolean")
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise PolicyError(f"{label}: invalid port {value!r}") from exc
    if port < 1 or port > 65535:
        raise PolicyError(f"{label}: port {port} outside 1..65535")
    return port


def normalize_port_range(value: Any, label: str) -> str:
    text = str(value).strip()
    m = PORT_RANGE_RE.fullmatch(text)
    if not m:
        raise PolicyError(f"{label}: invalid port range {value!r}; expected START-END")
    start = normalize_port(m.group(1), label)
    end = normalize_port(m.group(2), label)
    if start > end:
        raise PolicyError(f"{label}: invalid port range {value!r}; start > end")
    return f"{start}-{end}"


def normalize_ports(service: Mapping[str, Any], label: str) -> List[str]:
    ports: List[str] = []
    for item in as_list(service.get("ports"), f"{label}.ports"):
        ports.append(str(normalize_port(item, f"{label}.ports")))
    for item in as_list(service.get("port_ranges"), f"{label}.port_ranges"):
        ports.append(normalize_port_range(item, f"{label}.port_ranges"))
    return unique_preserve(ports)


def normalize_source_ports(service: Mapping[str, Any], label: str) -> List[str]:
    ports: List[str] = []
    for item in as_list(service.get("source_ports"), f"{label}.source_ports"):
        ports.append(str(normalize_port(item, f"{label}.source_ports")))
    for item in as_list(service.get("source_port_ranges"), f"{label}.source_port_ranges"):
        ports.append(normalize_port_range(item, f"{label}.source_port_ranges"))
    return unique_preserve(ports)


def normalize_protocols(service: Mapping[str, Any], label: str) -> List[str]:
    protos = [str(p).lower() for p in as_list(service.get("protocols"), f"{label}.protocols")]
    if not protos:
        proto = service.get("proto")
        if proto is not None:
            protos = [str(proto).lower()]
    if not protos:
        raise PolicyError(f"{label}: protocols is required")
    for proto in protos:
        if proto not in PROTO_SET:
            raise PolicyError(f"{label}: unsupported protocol {proto!r}; supported: {sorted(PROTO_SET)}")
    return unique_preserve(protos)


def should_warn_for_documentation_network(label: str) -> bool:
    lowered = label.lower()
    return (
        "unsafe" not in lowered
        and "bogon" not in lowered
        and "martian" not in lowered
        and ".drop_" not in lowered
        and "anti_spoofing.drop_" not in lowered
    )


def parse_networks(values: Iterable[Any], label: str, ctx: RenderContext) -> Tuple[List[str], List[str]]:
    v4: List[str] = []
    v6: List[str] = []
    warn_docs = should_warn_for_documentation_network(label)
    for raw in values:
        text = str(raw).strip()
        if not text:
            continue
        if UNRESOLVED_RE.search(text):
            raise PolicyError(f"{label}: unresolved placeholder {text!r}")
        try:
            net = ipaddress.ip_network(text, strict=False)
        except ValueError as exc:
            raise PolicyError(f"{label}: invalid CIDR/IP {text!r}") from exc
        if isinstance(net, ipaddress.IPv4Network):
            v4.append(str(net))
            if warn_docs and any(net.subnet_of(doc) for doc in DOC_IPV4_NETS):
                ctx.warn(f"{label}: {net} is documentation/example IPv4 space; replace before production use")
        else:
            v6.append(str(net))
            if warn_docs and any(net.subnet_of(doc) for doc in DOC_IPV6_NETS):
                ctx.warn(f"{label}: {net} is documentation/example IPv6 space; replace before production use")
    return unique_preserve(v4), unique_preserve(v6)


def validate_interface(value: Any, label: str) -> str:
    iface = str(value).strip()
    if not iface:
        raise PolicyError(f"{label}: empty interface name")
    if UNRESOLVED_RE.search(iface):
        raise PolicyError(f"{label}: unresolved placeholder {iface!r}")
    if not INTERFACE_RE.fullmatch(iface):
        raise PolicyError(f"{label}: unsafe interface name {iface!r}")
    if "*" in iface and (iface == "*" or iface.count("*") != 1 or not iface.endswith("*")):
        raise PolicyError(f"{label}: interface wildcards must be non-empty prefixes ending with '*': {iface!r}")
    return iface


def split_interface_patterns(values: Sequence[str]) -> Tuple[List[str], List[str]]:
    exact: List[str] = []
    wildcards: List[str] = []
    for value in values:
        if "*" in value:
            wildcards.append(value)
        else:
            exact.append(value)
    return unique_preserve(exact), unique_preserve(wildcards)


def quote_nft_string(value: str) -> str:
    # Interface names and log prefixes are already restricted where relevant, but
    # keep this robust for generated comments/prefixes.
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def nft_set(values: Sequence[str], quote_strings: bool = False) -> str:
    if not values:
        raise PolicyError("cannot render empty nft set")
    rendered = [quote_nft_string(v) if quote_strings else str(v) for v in values]
    if len(rendered) == 1:
        return rendered[0]
    return "{ " + ", ".join(rendered) + " }"


def nft_define_set(values: Sequence[str], quote_strings: bool = False) -> str:
    if not values:
        raise PolicyError("cannot render empty define set")
    rendered = [quote_nft_string(v) if quote_strings else str(v) for v in values]
    return "{ " + ", ".join(rendered) + " }"


def rate_expr(rate: Optional[str], label: str) -> str:
    if rate is None or str(rate).strip() == "":
        return ""
    text = str(rate).strip()
    if not RATE_RE.fullmatch(text):
        raise PolicyError(f"{label}: unsafe/invalid rate expression {text!r}")
    return f" limit rate {text}"


def comment_expr(text: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_.:/@+ -]", "_", text).strip()
    if not clean:
        return ""
    return f" comment {quote_nft_string(clean[:120])}"


def log_expr(policy: Mapping[str, Any], service_name: str, verdict: str) -> str:
    logging = as_dict(policy.get("logging"), "logging")
    accept_logging = as_dict(logging.get("accept"), "logging.accept")
    if not as_bool(accept_logging.get("enabled"), False):
        return ""
    prefix = str(logging.get("prefix", "nftables"))
    prefix = re.sub(r"[^A-Za-z0-9_.:-]", "_", prefix)[:32]
    return f" log prefix {quote_nft_string(prefix + ' ' + verdict + ' ' + service_name + ' ')}"


def output_paths(policy: Mapping[str, Any], target_root: Path) -> Dict[str, Path]:
    gen = as_dict(policy.get("generator"), "generator")
    outputs = as_dict(gen.get("outputs"), "generator.outputs")
    fragments = as_dict(outputs.get("fragments"), "generator.outputs.fragments")
    paths: Dict[str, Path] = {}
    nftables_conf = str(outputs.get("nftables_conf", "/etc/nftables.conf"))
    paths["nftables_conf"] = map_to_target_root(Path(nftables_conf), target_root)
    for key in ("defines", "base", "filter", "nat", "local"):
        if key not in fragments:
            raise PolicyError(f"generator.outputs.fragments.{key} is required")
        paths[key] = map_to_target_root(Path(str(fragments[key])), target_root)
    return paths


def map_to_target_root(path: Path, target_root: Path) -> Path:
    if not path.is_absolute():
        raise PolicyError(f"output path must be absolute: {path}")
    root = target_root.resolve()
    if str(root) == "/":
        return path
    return root / str(path).lstrip("/")


def include_path_for(path: Path) -> str:
    return str(path)


def build_define_maps(policy: Mapping[str, Any], ctx: RenderContext) -> Dict[str, Dict[str, Any]]:
    maps: Dict[str, Dict[str, Any]] = {
        "interfaces": {},
        "cidr4": {},
        "cidr6": {},
        "ports": {},
    }

    interface_sources = {}
    interface_sources.update(as_dict(policy.get("interface_groups"), "interface_groups"))
    interface_sources.update(as_dict(policy.get("interfaces"), "interfaces"))
    for name, raw_values in interface_sources.items():
        values = [validate_interface(x, f"interfaces.{name}") for x in as_list(raw_values, f"interfaces.{name}")]
        values = unique_preserve(values)
        if values:
            exact, wildcards = split_interface_patterns(values)
            maps["interfaces"][name] = {"define": f"if_{safe_ident(name)}", "values": exact, "wildcards": wildcards}

    cidr_sources = {}
    cidr_sources.update(as_dict(policy.get("cidr_groups"), "cidr_groups"))
    cidr_sources.update(as_dict(policy.get("cidrs"), "cidrs"))
    for name, raw_values in cidr_sources.items():
        v4, v6 = parse_networks(as_list(raw_values, f"cidrs.{name}"), f"cidrs.{name}", ctx)
        if v4:
            maps["cidr4"][name] = {"define": f"ipv4_{safe_ident(name)}", "values": v4}
        if v6:
            maps["cidr6"][name] = {"define": f"ipv6_{safe_ident(name)}", "values": v6}

    port_sources = {}
    port_sources.update(as_dict(policy.get("port_groups"), "port_groups"))
    port_sources.update(as_dict(policy.get("ports"), "ports"))
    for name, raw_values in port_sources.items():
        ports = [str(normalize_port(x, f"ports.{name}")) for x in as_list(raw_values, f"ports.{name}")]
        ports = unique_preserve(ports)
        if ports:
            maps["ports"][name] = {"define": f"ports_{safe_ident(name)}", "values": ports}

    return maps


def define_ref(maps: Mapping[str, Dict[str, Any]], category: str, group_name: str) -> Optional[str]:
    item = maps.get(category, {}).get(group_name)
    if not item or not item.get("values"):
        return None
    return "$" + str(item["define"])


def render_nftables_conf(policy: Mapping[str, Any], paths: Mapping[str, Path]) -> str:
    gen = as_dict(policy.get("generator"), "generator")
    conf_settings = as_dict(gen.get("nftables_conf"), "generator.nftables_conf")
    shebang = str(conf_settings.get("shebang", "#!/usr/sbin/nft -f"))
    if not shebang.startswith("#!") or "\n" in shebang or "\r" in shebang:
        raise PolicyError("generator.nftables_conf.shebang must be a single line starting with #!")
    lines = [shebang, "", "# Managed by nft-policy-generate.py. Do not edit generated fragments directly."]
    if as_bool(conf_settings.get("flush_ruleset"), True):
        lines.append("flush ruleset")
    lines.append("")
    for key in ("defines", "base", "filter", "nat", "local"):
        lines.append(f"include {quote_nft_string(include_path_for(paths[key]))}")
    lines.append("")
    return "\n".join(lines)


def render_defines(policy: Mapping[str, Any], maps: Mapping[str, Dict[str, Any]]) -> str:
    meta = as_dict(policy.get("metadata"), "metadata")
    lines = [
        "# Managed by nft-policy-generate.py.",
        f"# Profile: {meta.get('name', 'unknown')}",
        "",
        "# Interface constants",
    ]
    for name in sorted(maps["interfaces"]):
        item = maps["interfaces"][name]
        if item["values"]:
            lines.append(f"define {item['define']} = {nft_define_set(item['values'], quote_strings=True)}")
    lines.append("")
    lines.append("# IPv4 CIDR constants")
    for name in sorted(maps["cidr4"]):
        item = maps["cidr4"][name]
        lines.append(f"define {item['define']} = {nft_define_set(item['values'])}")
    lines.append("")
    lines.append("# IPv6 CIDR constants")
    for name in sorted(maps["cidr6"]):
        item = maps["cidr6"][name]
        lines.append(f"define {item['define']} = {nft_define_set(item['values'])}")
    lines.append("")
    lines.append("# Port constants")
    for name in sorted(maps["ports"]):
        item = maps["ports"][name]
        lines.append(f"define {item['define']} = {nft_define_set(item['values'])}")
    lines.append("")
    return "\n".join(lines)


def egress_enforced(policy: Mapping[str, Any]) -> bool:
    egress = as_dict(policy.get("egress"), "egress")
    mode = validate_egress_mode(egress.get("mode", "allow_all"))
    return as_bool(egress.get("enforce"), False) or mode in {"enforce", "strict", "deny_by_default"}


def validate_egress_mode(value: Any) -> str:
    mode = str(value).strip().lower()
    if mode not in EGRESS_MODES:
        raise PolicyError(f"egress.mode: unsupported mode {value!r}; expected one of {sorted(EGRESS_MODES)}")
    return mode


def egress_audit_enabled(policy: Mapping[str, Any]) -> bool:
    egress = as_dict(policy.get("egress"), "egress")
    mode = validate_egress_mode(egress.get("mode", "allow_all"))
    return mode in {"audit", "allow_all_with_audit"} or as_bool(egress.get("audit_unknown_egress"), False)


def render_base(policy: Mapping[str, Any]) -> str:
    nft = as_dict(policy.get("nftables"), "nftables")
    policies = as_dict(policy.get("policies"), "policies")
    family = validate_nft_family(nft.get("family", "inet"), "nftables.family", NFT_FAMILIES)
    table = validate_nft_identifier(nft.get("filter_table", "filter"), "nftables.filter_table")
    chains = as_dict(nft.get("chain_names"), "nftables.chain_names")
    input_chain = validate_nft_identifier(chains.get("input", "input"), "nftables.chain_names.input")
    forward_chain = validate_nft_identifier(chains.get("forward", "forward"), "nftables.chain_names.forward")
    output_chain = validate_nft_identifier(chains.get("output", "output"), "nftables.chain_names.output")
    local_input = validate_nft_identifier(chains.get("local_input", "local_input"), "nftables.chain_names.local_input")
    local_forward = validate_nft_identifier(chains.get("local_forward", "local_forward"), "nftables.chain_names.local_forward")
    local_output = validate_nft_identifier(chains.get("local_output", "local_output"), "nftables.chain_names.local_output")

    input_policy = str(policies.get("input", "drop")).lower()
    forward_policy = str(policies.get("forward", "drop")).lower()
    output_policy = str(policies.get("output", "accept")).lower()
    if egress_enforced(policy):
        output_policy = str(as_dict(policy.get("egress"), "egress").get("default_policy_when_enforced", "drop")).lower()
    validate_egress_mode(as_dict(policy.get("egress"), "egress").get("mode", "allow_all"))
    for label, value in (("input", input_policy), ("forward", forward_policy), ("output", output_policy)):
        if value not in {"accept", "drop"}:
            raise PolicyError(f"policies.{label}: unsupported policy {value!r}")

    return f"""# Managed by nft-policy-generate.py.
table {family} {table} {{
    chain {input_chain} {{
        type filter hook input priority 0; policy {input_policy};
    }}

    chain {forward_chain} {{
        type filter hook forward priority 0; policy {forward_policy};
    }}

    chain {output_chain} {{
        type filter hook output priority 0; policy {output_policy};
    }}

    chain {local_input} {{
    }}

    chain {local_forward} {{
    }}

    chain {local_output} {{
    }}
}}
"""


def chain_names(policy: Mapping[str, Any]) -> Tuple[str, str, str, str, str, str]:
    nft = as_dict(policy.get("nftables"), "nftables")
    chains = as_dict(nft.get("chain_names"), "nftables.chain_names")
    return (
        validate_nft_identifier(chains.get("input", "input"), "nftables.chain_names.input"),
        validate_nft_identifier(chains.get("forward", "forward"), "nftables.chain_names.forward"),
        validate_nft_identifier(chains.get("output", "output"), "nftables.chain_names.output"),
        validate_nft_identifier(chains.get("local_input", "local_input"), "nftables.chain_names.local_input"),
        validate_nft_identifier(chains.get("local_forward", "local_forward"), "nftables.chain_names.local_forward"),
        validate_nft_identifier(chains.get("local_output", "local_output"), "nftables.chain_names.local_output"),
    )


def family_table(policy: Mapping[str, Any]) -> Tuple[str, str]:
    nft = as_dict(policy.get("nftables"), "nftables")
    return (
        validate_nft_family(nft.get("family", "inet"), "nftables.family", NFT_FAMILIES),
        validate_nft_identifier(nft.get("filter_table", "filter"), "nftables.filter_table"),
    )


def add_rule(policy: Mapping[str, Any], chain: str, expr: str) -> str:
    family, table = family_table(policy)
    return f"add rule {family} {table} {chain} {expr}"


def if_match(maps: Mapping[str, Dict[str, Any]], groups: Sequence[str], direction: str, label: str, required: bool = False) -> str:
    refs: List[str] = []
    for group in groups:
        ref = define_ref(maps, "interfaces", str(group))
        if ref:
            refs.append(ref)
    refs = unique_preserve(refs)
    if not refs:
        if required:
            raise PolicyError(f"{label}: no usable interface groups resolved")
        return ""
    keyword = "iifname" if direction == "in" else "oifname"
    if len(refs) == 1:
        return f"{keyword} {refs[0]}"
    # Multiple variable-backed sets cannot be directly unioned in nft syntax.
    # Callers should emit one rule per interface group. This helper is mainly for
    # simple cases; keep the first expression deterministic if called directly.
    return f"{keyword} {refs[0]}"


def expand_interface_group_refs(maps: Mapping[str, Dict[str, Any]], groups: Sequence[str], label: str) -> List[str]:
    refs: List[str] = []
    for group in groups:
        item = maps.get("interfaces", {}).get(str(group))
        if not item:
            raise PolicyError(f"{label}: unknown interface group {group!r}")
        ref = define_ref(maps, "interfaces", str(group))
        if ref:
            refs.append(ref)
        for wildcard in item.get("wildcards", []):
            refs.append(quote_nft_string(str(wildcard)))
    return unique_preserve(refs)


def interface_match_exprs(
    maps: Mapping[str, Dict[str, Any]],
    block: Mapping[str, Any],
    direction: str,
    label: str,
) -> List[str]:
    """Return nft interface match expressions from direct interfaces and legacy groups.

    Preferred YAML:
      interfaces: [eth0, wg0]

    Backward-compatible YAML:
      interface_groups: [wan, vpn]
    """
    keyword = "iifname" if direction == "in" else "oifname"
    exprs: List[str] = []

    direct = [validate_interface(x, f"{label}.interfaces") for x in as_list(block.get("interfaces"), f"{label}.interfaces")]
    if direct:
        exact, wildcards = split_interface_patterns(unique_preserve(direct))
        if exact:
            exprs.append(f"{keyword} {nft_set(exact, quote_strings=True)}")
        for wildcard in wildcards:
            exprs.append(f"{keyword} {quote_nft_string(wildcard)}")

    group_refs = expand_interface_group_refs(
        maps,
        [str(x) for x in as_list(block.get("interface_groups"), f"{label}.interface_groups")],
        f"{label}.interface_groups",
    )
    for ref in group_refs:
        exprs.append(f"{keyword} {ref}")

    return unique_preserve(exprs) or [""]


def direct_cidrs(values: Sequence[Any], label: str, ctx: RenderContext) -> Tuple[List[str], List[str]]:
    return parse_networks(values, label, ctx)


def direct_cidrs_for_version(values: Sequence[Any], version: int, label: str, ctx: RenderContext) -> List[str]:
    v4, v6 = parse_networks(values, label, ctx)
    if version == 4:
        if v6:
            raise PolicyError(f"{label}: IPv6 values are not valid in an IPv4 field: {', '.join(v6)}")
        return v4
    if v4:
        raise PolicyError(f"{label}: IPv4 values are not valid in an IPv6 field: {', '.join(v4)}")
    return v6


def cidr_refs(maps: Mapping[str, Dict[str, Any]], groups: Sequence[str], version: int, label: str) -> List[str]:
    cat = "cidr4" if version == 4 else "cidr6"
    refs: List[str] = []
    for group in groups:
        item = maps.get(cat, {}).get(str(group))
        if not item or not item.get("values"):
            family = "IPv4" if version == 4 else "IPv6"
            raise PolicyError(f"{label}: unknown {family} CIDR group {group!r}")
        refs.append("$" + str(item["define"]))
    return unique_preserve(refs)


def networks_are_multicast(values: Sequence[str]) -> bool:
    if not values:
        return False
    try:
        for item in values:
            net = ipaddress.ip_network(item, strict=False)
            if not net.is_multicast:
                return False
        return True
    except ValueError:
        return False


def port_match(proto: str, ports: Sequence[str], direction: str = "d") -> str:
    if not ports:
        return ""
    if direction not in {"d", "s"}:
        raise PolicyError(f"unsupported port direction: {direction!r}")
    return f"{proto} {direction}port {nft_set(list(ports))}"



def allow_has_any_ip_constraints(allow: Mapping[str, Any], label: str) -> bool:
    for key in ("ipv4", "ipv6", "ipv4_groups", "ipv6_groups"):
        if as_list(allow.get(key), f"{label}.{key}"):
            return True
    return False


def ip_match_exprs(
    maps: Mapping[str, Dict[str, Any]],
    allow: Mapping[str, Any],
    version: int,
    address_role: str,
    label: str,
    ctx: RenderContext,
) -> List[str]:
    """Return nft IP match expressions for one IP family.

    If the allow/allow_to block has constraints only for the other family, return
    []. If it has no IP constraints at all, return [""] so callers can emit a
    generic rule constrained only by interface/port/protocol.
    """
    any_ip_constraints = allow_has_any_ip_constraints(allow, label)
    groups_key = "ipv4_groups" if version == 4 else "ipv6_groups"
    direct_key = "ipv4" if version == 4 else "ipv6"
    ip_keyword = "ip" if version == 4 else "ip6"

    group_names = [str(x) for x in as_list(allow.get(groups_key), f"{label}.{groups_key}")]
    refs = cidr_refs(maps, group_names, version, f"{label}.{groups_key}")
    direct_values = direct_cidrs_for_version(
        as_list(allow.get(direct_key), f"{label}.{direct_key}"),
        version,
        f"{label}.{direct_key}",
        ctx,
    )

    if not refs and not direct_values:
        return [] if any_ip_constraints else [""]

    exprs: List[str] = []
    for ref in refs:
        exprs.append(f"{ip_keyword} {address_role} {ref}")
    if direct_values:
        field = "daddr" if networks_are_multicast(direct_values) else address_role
        exprs.append(f"{ip_keyword} {field} {nft_set(direct_values)}")
    return unique_preserve(exprs)


def build_inbound_rules_for_ip_version(
    policy: Mapping[str, Any],
    maps: Mapping[str, Dict[str, Any]],
    service_name: str,
    service: Mapping[str, Any],
    proto: str,
    ports: Sequence[str],
    version: int,
    ctx: RenderContext,
) -> List[str]:
    input_chain, _, _, _, _, _ = chain_names(policy)
    allow = as_dict(service.get("allow"), f"services.{service_name}.allow")
    ip_exprs = ip_match_exprs(maps, allow, version, "saddr", f"services.{service_name}.allow", ctx)
    if not ip_exprs:
        return []

    iface_exprs = interface_match_exprs(maps, allow, "in", f"services.{service_name}.allow")

    rules: List[str] = []
    for iface_expr in iface_exprs:
        for ip_expr in ip_exprs:
            elements = []
            if iface_expr:
                elements.append(iface_expr)
            if ip_expr:
                elements.append(ip_expr)
            pm = port_match(proto, ports)
            if pm:
                elements.append(pm)
            if proto == "tcp":
                elements.append("ct state new")
            rlim = rate_expr(service.get("rate_limit"), f"services.{service_name}.rate_limit")
            if rlim:
                elements.append(rlim.strip())
            if as_bool(service.get("log"), False):
                service_log = log_expr(policy, service_name, "accept").strip()
                if service_log:
                    elements.append(service_log)
            elements.append("counter accept")
            elements.append(comment_expr(f"service {service_name} inbound").strip())
            rules.append(add_rule(policy, input_chain, " ".join(x for x in elements if x)))
    return rules


def build_outbound_rules_for_ip_version(
    policy: Mapping[str, Any],
    maps: Mapping[str, Dict[str, Any]],
    name: str,
    spec: Mapping[str, Any],
    proto: str,
    ports: Sequence[str],
    version: int,
    ctx: RenderContext,
    source: str = "service",
) -> List[str]:
    _, _, output_chain, _, _, _ = chain_names(policy)
    allow_to = as_dict(spec.get("allow_to"), f"{source}.{name}.allow_to")
    source_ports = normalize_source_ports(spec, f"{source}.{name}")
    ip_exprs = ip_match_exprs(maps, allow_to, version, "daddr", f"{source}.{name}.allow_to", ctx)
    if not ip_exprs:
        return []

    iface_exprs = interface_match_exprs(maps, allow_to, "out", f"{source}.{name}.allow_to")

    rules: List[str] = []
    for iface_expr in iface_exprs:
        for ip_expr in ip_exprs:
            elements = []
            if iface_expr:
                elements.append(iface_expr)
            if ip_expr:
                elements.append(ip_expr)
            pm = port_match(proto, ports)
            if pm:
                elements.append(pm)
            source_pm = port_match(proto, source_ports, "s")
            if source_pm:
                elements.append(source_pm)
            if as_bool(spec.get("log"), False):
                service_log = log_expr(policy, name, "accept").strip()
                if service_log:
                    elements.append(service_log)
            elements.append("counter accept")
            elements.append(comment_expr(f"{source} {name} outbound").strip())
            rules.append(add_rule(policy, output_chain, " ".join(x for x in elements if x)))
    return rules


def build_source_filter_drop_rules(
    policy: Mapping[str, Any],
    maps: Mapping[str, Dict[str, Any]],
    ctx: RenderContext,
) -> List[str]:
    source = as_dict(policy.get("source_filtering"), "source_filtering")
    if not as_bool(source.get("enabled"), False):
        return []

    input_chain, _, _, _, _, _ = chain_names(policy)
    if_exprs = interface_match_exprs(
        maps,
        {"interfaces": source.get("apply_to_interfaces", []), "interface_groups": source.get("apply_to_interface_groups", [])},
        "in",
        "source_filtering.apply_to",
    )
    categories = [
        ("martian ipv4 source", 4, "martian_ipv4_source_groups", "martian_ipv4_sources"),
        ("bogon ipv4 source", 4, "bogon_ipv4_source_groups", "bogon_ipv4_sources"),
        ("martian ipv6 source", 6, "martian_ipv6_source_groups", "martian_ipv6_sources"),
        ("bogon ipv6 source", 6, "bogon_ipv6_source_groups", "bogon_ipv6_sources"),
    ]

    rules: List[str] = []
    for comment, version, group_key, direct_key in categories:
        ip_keyword = "ip" if version == 4 else "ip6"
        refs = cidr_refs(
            maps,
            [str(x) for x in as_list(source.get(group_key), f"source_filtering.{group_key}")],
            version,
            f"source_filtering.{group_key}",
        )
        direct = direct_cidrs_for_version(
            as_list(source.get(direct_key), f"source_filtering.{direct_key}"),
            version,
            f"source_filtering.{direct_key}",
            ctx,
        )
        if not refs and not direct:
            continue
        for if_expr in if_exprs:
            prefix = f"{if_expr} " if if_expr else ""
            for ref in refs:
                rules.append(add_rule(policy, input_chain, f"{prefix}{ip_keyword} saddr {ref} counter drop" + comment_expr(comment)))
            if direct:
                rules.append(add_rule(policy, input_chain, f"{prefix}{ip_keyword} saddr {nft_set(direct)} counter drop" + comment_expr(comment + " direct")))
    return rules


def build_drop_log_rules(policy: Mapping[str, Any], logging: Mapping[str, Any]) -> List[str]:
    drop_logging = as_dict(logging.get("drop"), "logging.drop")
    enabled = as_bool(drop_logging.get("enabled"), as_bool(logging.get("log_drops"), False))
    if not enabled:
        return []

    input_chain, forward_chain, output_chain, _, _, _ = chain_names(policy)
    chain_map = {
        "input": input_chain,
        "forward": forward_chain,
        "output": output_chain,
    }
    default_chains = ["input", "forward"]
    if egress_enforced(policy):
        default_chains.append("output")
    chains = [str(x).lower() for x in as_list(drop_logging.get("chains", default_chains), "logging.drop.chains")]
    if not chains:
        return []
    for chain in chains:
        if chain not in DROP_LOG_CHAINS:
            raise PolicyError(f"logging.drop.chains: unsupported chain {chain!r}; expected one of {sorted(DROP_LOG_CHAINS)}")
    if not egress_enforced(policy):
        chains = [chain for chain in chains if chain != "output"]

    limit = rate_expr(str(drop_logging.get("limit", logging.get("limit", "10/minute"))), "logging.drop.limit").strip()
    prefix = str(drop_logging.get("prefix", logging.get("prefix", "nftables")))
    prefix = re.sub(r"[^A-Za-z0-9_.:-]", "_", prefix)[:32]

    rules: List[str] = []
    for chain in unique_preserve(chains):
        elements = []
        if limit:
            elements.append(limit)
        elements.append("log prefix " + quote_nft_string(prefix + f" drop {chain} "))
        elements.append("counter")
        rules.append(add_rule(policy, chain_map[chain], " ".join(elements)))
    return rules


def build_output_audit_rule(policy: Mapping[str, Any], logging: Mapping[str, Any]) -> List[str]:
    if not egress_audit_enabled(policy) or egress_enforced(policy):
        return []
    audit_logging = as_dict(logging.get("egress_audit"), "logging.egress_audit")
    if not as_bool(audit_logging.get("enabled"), True):
        return []

    _, _, output_chain, _, _, _ = chain_names(policy)
    limit = rate_expr(str(audit_logging.get("limit", logging.get("limit", "10/minute"))), "logging.egress_audit.limit").strip()
    prefix = str(audit_logging.get("prefix", logging.get("prefix", "nftables")))
    prefix = re.sub(r"[^A-Za-z0-9_.:-]", "_", prefix)[:32]
    elements = []
    if limit:
        elements.append(limit)
    elements.append("log prefix " + quote_nft_string(prefix + " accept output "))
    elements.append("counter")
    return [add_rule(policy, output_chain, " ".join(elements))]


def build_link_local_noise_drop_rules(policy: Mapping[str, Any]) -> List[str]:
    input_chain, _, output_chain, _, _, _ = chain_names(policy)
    rules = [
        add_rule(policy, input_chain, "meta pkttype { broadcast, multicast } counter drop" + comment_expr("silent link-local noise input")),
        add_rule(policy, input_chain, "ip daddr 224.0.0.0/4 counter drop" + comment_expr("silent multicast input")),
        add_rule(policy, input_chain, "ip6 daddr ff00::/8 counter drop" + comment_expr("silent multicast input")),
    ]
    if egress_enforced(policy):
        rules.append(add_rule(policy, output_chain, "meta pkttype { broadcast, multicast } counter drop" + comment_expr("silent link-local noise output")))
        rules.append(add_rule(policy, output_chain, "ip daddr 224.0.0.0/4 counter drop" + comment_expr("silent multicast output")))
        rules.append(add_rule(policy, output_chain, "ip6 daddr ff00::/8 counter drop" + comment_expr("silent multicast output")))
    return rules


def build_desktop_ipv6_accounting_rules(
    policy: Mapping[str, Any],
    maps: Mapping[str, Dict[str, Any]],
    ctx: RenderContext,
) -> List[str]:
    desktop_ipv6 = as_dict(policy.get("desktop_ipv6"), "desktop_ipv6")
    if not as_bool(desktop_ipv6.get("enabled"), False):
        return []

    group_name = str(desktop_ipv6.get("host_cidr_group", "desktop_static_ipv6_host")).strip()
    if not group_name:
        raise PolicyError("desktop_ipv6.host_cidr_group must not be empty")
    ref = define_ref(maps, "cidr6", group_name)
    if not ref:
        ctx.skip(f"desktop_ipv6: CIDR group {group_name!r} is empty or absent; no desktop IPv6 accounting rules generated")
        return []

    input_chain, _, output_chain, _, _, _ = chain_names(policy)
    rules: List[str] = []
    if as_bool(desktop_ipv6.get("account_input"), True):
        rules.append(add_rule(policy, input_chain, f"ip6 daddr {ref} counter" + comment_expr("desktop generated ipv6 input")))
    if as_bool(desktop_ipv6.get("account_output"), True):
        rules.append(add_rule(policy, output_chain, f"ip6 saddr {ref} counter" + comment_expr("desktop generated ipv6 output")))
    return rules


def egress_rule_enabled(egress_rules: Mapping[str, Any], rule_name: str) -> bool:
    rule = egress_rules.get(rule_name)
    if not isinstance(rule, dict):
        return False
    return as_bool(rule.get("enabled"), False)


def service_has_ip_constraints(policy: Mapping[str, Any], maps: Mapping[str, Dict[str, Any]], service: Mapping[str, Any], service_name: str) -> bool:
    allow = as_dict(service.get("allow"), f"services.{service_name}.allow")
    for key in ("ipv4", "ipv6"):
        if as_list(allow.get(key), f"services.{service_name}.allow.{key}"):
            return True
    for group_key, version in (("ipv4_groups", 4), ("ipv6_groups", 6)):
        groups = [str(group) for group in as_list(allow.get(group_key), f"services.{service_name}.allow.{group_key}")]
        if groups and cidr_refs(maps, groups, version, f"services.{service_name}.allow.{group_key}"):
            return True
    return False


def sensitive_public_violation(maps: Mapping[str, Dict[str, Any]], service: Mapping[str, Any]) -> bool:
    allow = as_dict(service.get("allow"), "allow")
    groups4 = [str(x) for x in as_list(allow.get("ipv4_groups"), "allow.ipv4_groups")]
    groups6 = [str(x) for x in as_list(allow.get("ipv6_groups"), "allow.ipv6_groups")]
    direct4, direct6 = [], []
    dummy = RenderContext()
    if allow.get("ipv4"):
        direct4, _ = parse_networks(as_list(allow.get("ipv4"), "allow.ipv4"), "allow.ipv4", dummy)
    if allow.get("ipv6"):
        _, direct6 = parse_networks(as_list(allow.get("ipv6"), "allow.ipv6"), "allow.ipv6", dummy)
    if "any_ipv4" in groups4 or "any_ipv6" in groups6:
        return True
    if "0.0.0.0/0" in direct4 or "::/0" in direct6:
        return True
    return False


def validate_services(policy: Mapping[str, Any], maps: Mapping[str, Dict[str, Any]], ctx: RenderContext, allow_public_sensitive: bool) -> None:
    safety = as_dict(policy.get("safety"), "safety")
    services = as_dict(policy.get("services"), "services")
    require_non_empty = as_bool(safety.get("require_non_empty_allowlist_for_sensitive_services"), True)
    forbid_public_sensitive = as_bool(safety.get("forbid_public_admin_services_by_default"), True)

    for service_name, raw_service in services.items():
        service = as_dict(raw_service, f"services.{service_name}")
        if not as_bool(service.get("enabled"), False):
            continue
        direction = str(service.get("direction", "inbound")).lower()
        if direction not in DIRECTION_SET:
            raise PolicyError(f"services.{service_name}.direction: unsupported direction {direction!r}")
        normalize_protocols(service, f"services.{service_name}")
        ports = normalize_ports(service, f"services.{service_name}")
        source_ports = normalize_source_ports(service, f"services.{service_name}")
        if not ports and not source_ports:
            ctx.skip(f"services.{service_name}: enabled but has no destination or source ports; no rules generated")
        if as_bool(service.get("sensitive"), False) and direction in {"inbound", "bidirectional"}:
            if require_non_empty and not service_has_ip_constraints(policy, maps, service, str(service_name)):
                raise PolicyError(f"services.{service_name}: sensitive inbound service requires non-empty IP allowlist")
            if forbid_public_sensitive and not allow_public_sensitive and sensitive_public_violation(maps, service):
                raise PolicyError(f"services.{service_name}: sensitive service has a public allowlist; narrow it for admin/private services or pass --allow-public-sensitive")


def render_filter(policy: Mapping[str, Any], maps: Mapping[str, Dict[str, Any]], ctx: RenderContext, allow_public_sensitive: bool) -> str:
    validate_services(policy, maps, ctx, allow_public_sensitive)
    features = as_dict(policy.get("features"), "features")
    anti = as_dict(policy.get("anti_spoofing"), "anti_spoofing")
    source = as_dict(policy.get("source_filtering"), "source_filtering")
    unsafe = as_dict(policy.get("unsafe_source_filtering"), "unsafe_source_filtering")
    egress = as_dict(policy.get("egress"), "egress")
    forwarding = as_dict(policy.get("forwarding"), "forwarding")
    containers = as_dict(policy.get("containers"), "containers")
    rate_limits = as_dict(policy.get("rate_limits"), "rate_limits")
    logging = as_dict(policy.get("logging"), "logging")

    input_chain, forward_chain, output_chain, local_input, local_forward, local_output = chain_names(policy)
    lines = ["# Managed by nft-policy-generate.py.", "# Filter rules", ""]

    if as_bool(features.get("drop_invalid"), True):
        lines.append(add_rule(policy, input_chain, "ct state invalid counter drop" + comment_expr("base drop invalid")))
        lines.append(add_rule(policy, forward_chain, "ct state invalid counter drop" + comment_expr("base drop invalid forward")))
        lines.append(add_rule(policy, output_chain, "ct state invalid counter drop" + comment_expr("base drop invalid output")))

    if as_bool(features.get("allow_established_related"), True):
        lines.append(add_rule(policy, input_chain, "ct state established,related counter accept" + comment_expr("base established related")))
        lines.append(add_rule(policy, forward_chain, "ct state established,related counter accept" + comment_expr("base established related forward")))
        lines.append(add_rule(policy, output_chain, "ct state established,related counter accept" + comment_expr("base established related output")))

    if as_bool(features.get("allow_loopback"), True):
        loop_ref = define_ref(maps, "interfaces", "loopback")
        if loop_ref:
            lines.append(add_rule(policy, input_chain, f"iifname {loop_ref} counter accept" + comment_expr("base loopback input")))
            lines.append(add_rule(policy, output_chain, f"oifname {loop_ref} counter accept" + comment_expr("base loopback output")))
        else:
            lines.append(add_rule(policy, input_chain, "iifname \"lo\" counter accept" + comment_expr("base loopback input")))
            lines.append(add_rule(policy, output_chain, "oifname \"lo\" counter accept" + comment_expr("base loopback output")))

    # Loopback source on non-loopback is always suspicious.
    localhost4 = define_ref(maps, "cidr4", "localhost_ipv4")
    localhost6 = define_ref(maps, "cidr6", "localhost_ipv6")
    if as_bool(source.get("drop_loopback_on_non_loopback"), as_bool(unsafe.get("drop_loopback_on_non_loopback"), True)):
        if localhost4:
            lines.append(add_rule(policy, input_chain, f"iifname != \"lo\" ip saddr {localhost4} counter drop" + comment_expr("martian loopback source")))
        if localhost6:
            lines.append(add_rule(policy, input_chain, f"iifname != \"lo\" ip6 saddr {localhost6} counter drop" + comment_expr("martian loopback source")))

    anti_exceptions = as_dict(anti.get("exceptions"), "anti_spoofing.exceptions")
    if as_bool(anti_exceptions.get("allow_dhcp_client"), False):
        lines.append(add_rule(policy, input_chain, "udp sport 67 udp dport 68 counter accept" + comment_expr("dhcpv4 client before anti-spoof")))
        lines.append(add_rule(policy, input_chain, "udp sport 547 udp dport 546 counter accept" + comment_expr("dhcpv6 client before anti-spoof")))

    if as_bool(features.get("source_filtering"), True):
        lines.extend(build_source_filter_drop_rules(policy, maps, ctx))

    if as_bool(features.get("unsafe_source_filtering"), True) and as_bool(unsafe.get("enabled"), False):
        unsafe4 = define_ref(maps, "cidr4", "unsafe_ipv4_sources")
        unsafe6 = define_ref(maps, "cidr6", "unsafe_ipv6_sources")
        if unsafe4:
            lines.append(add_rule(policy, input_chain, f"ip saddr {unsafe4} counter drop" + comment_expr("unsafe ipv4 source")))
        if unsafe6:
            lines.append(add_rule(policy, input_chain, f"ip6 saddr {unsafe6} counter drop" + comment_expr("unsafe ipv6 source")))

    if as_bool(features.get("allow_ipv6_neighbor_discovery"), True):
        lines.append(add_rule(policy, input_chain, "ip6 nexthdr icmpv6 icmpv6 type { nd-neighbor-solicit, nd-neighbor-advert, nd-router-solicit, nd-router-advert } counter accept" + comment_expr("ipv6 neighbor discovery")))
        lines.append(add_rule(policy, output_chain, "ip6 nexthdr icmpv6 icmpv6 type { nd-neighbor-solicit, nd-neighbor-advert, nd-router-solicit, nd-router-advert } counter accept" + comment_expr("ipv6 neighbor discovery")))

    if as_bool(features.get("anti_spoofing"), True) and as_bool(anti.get("enabled"), True):
        if_exprs = interface_match_exprs(
            maps,
            {"interfaces": anti.get("apply_to_interfaces", []), "interface_groups": anti.get("apply_to_interface_groups", [])},
            "in",
            "anti_spoofing.apply_to",
        )
        drop4_refs = cidr_refs(
            maps,
            [str(x) for x in as_list(anti.get("drop_ipv4_source_groups"), "anti_spoofing.drop_ipv4_source_groups")],
            4,
            "anti_spoofing.drop_ipv4_source_groups",
        )
        drop6_refs = cidr_refs(
            maps,
            [str(x) for x in as_list(anti.get("drop_ipv6_source_groups"), "anti_spoofing.drop_ipv6_source_groups")],
            6,
            "anti_spoofing.drop_ipv6_source_groups",
        )
        drop4_direct = direct_cidrs_for_version(as_list(anti.get("drop_ipv4_sources"), "anti_spoofing.drop_ipv4_sources"), 4, "anti_spoofing.drop_ipv4_sources", ctx)
        drop6_direct = direct_cidrs_for_version(as_list(anti.get("drop_ipv6_sources"), "anti_spoofing.drop_ipv6_sources"), 6, "anti_spoofing.drop_ipv6_sources", ctx)
        for if_expr in if_exprs:
            if not if_expr:
                continue
            for src_ref in drop4_refs:
                lines.append(add_rule(policy, input_chain, f"{if_expr} ip saddr {src_ref} counter drop" + comment_expr("anti-spoof ipv4")))
            if drop4_direct:
                lines.append(add_rule(policy, input_chain, f"{if_expr} ip saddr {nft_set(drop4_direct)} counter drop" + comment_expr("anti-spoof ipv4 direct")))
            for src_ref in drop6_refs:
                lines.append(add_rule(policy, input_chain, f"{if_expr} ip6 saddr {src_ref} counter drop" + comment_expr("anti-spoof ipv6")))
            if drop6_direct:
                lines.append(add_rule(policy, input_chain, f"{if_expr} ip6 saddr {nft_set(drop6_direct)} counter drop" + comment_expr("anti-spoof ipv6 direct")))

    if as_bool(features.get("allow_icmpv4"), True):
        lim = rate_expr(str(rate_limits.get("icmpv4", "20/second burst 50 packets")), "rate_limits.icmpv4")
        lines.append(add_rule(policy, input_chain, f"ip protocol icmp icmp type {{ echo-request, destination-unreachable, time-exceeded, parameter-problem }}{lim} counter accept" + comment_expr("icmpv4")))
        lines.append(add_rule(policy, output_chain, "ip protocol icmp counter accept" + comment_expr("icmpv4 output")))

    if as_bool(features.get("allow_icmpv6"), True):
        lim = rate_expr(str(rate_limits.get("icmpv6", "20/second burst 50 packets")), "rate_limits.icmpv6")
        lines.append(add_rule(policy, input_chain, f"ip6 nexthdr icmpv6 icmpv6 type {{ echo-request, echo-reply, destination-unreachable, packet-too-big, time-exceeded, parameter-problem }}{lim} counter accept" + comment_expr("icmpv6")))
        lines.append(add_rule(policy, output_chain, "ip6 nexthdr icmpv6 counter accept" + comment_expr("icmpv6 output")))

    lines.extend(build_desktop_ipv6_accounting_rules(policy, maps, ctx))

    lines.append(add_rule(policy, input_chain, f"jump {local_input}" + comment_expr("local input hook")))
    lines.append(add_rule(policy, forward_chain, f"jump {local_forward}" + comment_expr("local forward hook")))
    lines.append(add_rule(policy, output_chain, f"jump {local_output}" + comment_expr("local output hook")))
    lines.extend(build_output_audit_rule(policy, logging))

    lines.append("")
    lines.append("# Inbound and bidirectional service rules")
    for service_name in sorted(as_dict(policy.get("services"), "services")):
        service = as_dict(as_dict(policy.get("services"), "services")[service_name], f"services.{service_name}")
        if not as_bool(service.get("enabled"), False):
            continue
        direction = str(service.get("direction", "inbound")).lower()
        if direction not in {"inbound", "bidirectional"}:
            continue
        ports = normalize_ports(service, f"services.{service_name}")
        if not ports:
            continue
        for proto in normalize_protocols(service, f"services.{service_name}"):
            for rule in build_inbound_rules_for_ip_version(policy, maps, service_name, service, proto, ports, 4, ctx):
                lines.append(rule)
            for rule in build_inbound_rules_for_ip_version(policy, maps, service_name, service, proto, ports, 6, ctx):
                lines.append(rule)

    lines.append("")
    lines.append("# Outbound service and egress rules")
    for service_name in sorted(as_dict(policy.get("services"), "services")):
        service = as_dict(as_dict(policy.get("services"), "services")[service_name], f"services.{service_name}")
        if not as_bool(service.get("enabled"), False):
            continue
        direction = str(service.get("direction", "inbound")).lower()
        if direction not in {"outbound", "bidirectional"}:
            continue
        ports = normalize_ports(service, f"services.{service_name}")
        source_ports = normalize_source_ports(service, f"services.{service_name}")
        if not ports and not source_ports:
            continue
        # Bidirectional services usually use allow, not allow_to. Mirror allow -> allow_to for outbound if absent.
        if "allow_to" not in service and "allow" in service:
            service = copy.deepcopy(service)
            service["allow_to"] = {
                "ipv4_groups": as_dict(service.get("allow"), f"services.{service_name}.allow").get("ipv4_groups", []),
                "ipv6_groups": as_dict(service.get("allow"), f"services.{service_name}.allow").get("ipv6_groups", []),
                "ipv4": as_dict(service.get("allow"), f"services.{service_name}.allow").get("ipv4", []),
                "ipv6": as_dict(service.get("allow"), f"services.{service_name}.allow").get("ipv6", []),
                "interfaces": as_dict(service.get("allow"), f"services.{service_name}.allow").get("interfaces", []),
                "interface_groups": as_dict(service.get("allow"), f"services.{service_name}.allow").get("interface_groups", []),
            }
        for proto in normalize_protocols(service, f"services.{service_name}"):
            for rule in build_outbound_rules_for_ip_version(policy, maps, service_name, service, proto, ports, 4, ctx):
                lines.append(rule)
            for rule in build_outbound_rules_for_ip_version(policy, maps, service_name, service, proto, ports, 6, ctx):
                lines.append(rule)

    egress_rules = as_dict(egress.get("rules"), "egress.rules")
    for rule_name in sorted(egress_rules):
        rule_spec = as_dict(egress_rules[rule_name], f"egress.rules.{rule_name}")
        if not as_bool(rule_spec.get("enabled"), False):
            continue
        ports = normalize_ports(rule_spec, f"egress.rules.{rule_name}")
        source_ports = normalize_source_ports(rule_spec, f"egress.rules.{rule_name}")
        if not ports and not source_ports:
            continue
        for proto in normalize_protocols(rule_spec, f"egress.rules.{rule_name}"):
            for rule in build_outbound_rules_for_ip_version(policy, maps, rule_name, rule_spec, proto, ports, 4, ctx, source="egress"):
                lines.append(rule)
            for rule in build_outbound_rules_for_ip_version(policy, maps, rule_name, rule_spec, proto, ports, 6, ctx, source="egress"):
                lines.append(rule)

    # Convenience egress rules from profile booleans, only meaningful when output is enforced.
    if egress_enforced(policy):
        any4 = define_ref(maps, "cidr4", "any_ipv4")
        any6 = define_ref(maps, "cidr6", "any_ipv6")
        if as_bool(egress.get("allow_dns"), False) and not egress_rule_enabled(egress_rules, "dns"):
            for proto in ("tcp", "udp"):
                if any4:
                    lines.append(add_rule(policy, output_chain, f"ip daddr {any4} {proto} dport 53 counter accept" + comment_expr("egress builtin dns")))
                if any6:
                    lines.append(add_rule(policy, output_chain, f"ip6 daddr {any6} {proto} dport 53 counter accept" + comment_expr("egress builtin dns")))
        if as_bool(egress.get("allow_ntp"), False) and not egress_rule_enabled(egress_rules, "ntp"):
            if any4:
                lines.append(add_rule(policy, output_chain, f"ip daddr {any4} udp dport 123 counter accept" + comment_expr("egress builtin ntp")))
            if any6:
                lines.append(add_rule(policy, output_chain, f"ip6 daddr {any6} udp dport 123 counter accept" + comment_expr("egress builtin ntp")))
        if as_bool(egress.get("allow_http_https"), False) and not egress_rule_enabled(egress_rules, "http_https"):
            if any4:
                lines.append(add_rule(policy, output_chain, f"ip daddr {any4} tcp dport {{ 80, 443 }} counter accept" + comment_expr("egress builtin http https")))
            if any6:
                lines.append(add_rule(policy, output_chain, f"ip6 daddr {any6} tcp dport {{ 80, 443 }} counter accept" + comment_expr("egress builtin http https")))

    lines.append("")
    lines.append("# Forwarding and container rules")
    if as_bool(forwarding.get("enabled"), False) or as_bool(forwarding.get("router_mode"), False):
        if as_bool(forwarding.get("allow_established_related"), True):
            lines.append(add_rule(policy, forward_chain, "ct state established,related counter accept" + comment_expr("forward established related")))
        for rule_name, raw_rule in as_dict(forwarding.get("rules"), "forwarding.rules").items():
            rule = as_dict(raw_rule, f"forwarding.rules.{rule_name}")
            if not as_bool(rule.get("enabled"), False):
                continue
            from_exprs = interface_match_exprs(maps, {"interfaces": rule.get("from_interfaces", []), "interface_groups": rule.get("from_interface_groups", [])}, "in", f"forwarding.rules.{rule_name}.from")
            to_exprs = interface_match_exprs(maps, {"interfaces": rule.get("to_interfaces", []), "interface_groups": rule.get("to_interface_groups", [])}, "out", f"forwarding.rules.{rule_name}.to")
            src4_refs = cidr_refs(
                maps,
                [str(x) for x in as_list(rule.get("source_ipv4_groups"), f"forwarding.rules.{rule_name}.source_ipv4_groups")],
                4,
                f"forwarding.rules.{rule_name}.source_ipv4_groups",
            )
            dst4_refs = cidr_refs(
                maps,
                [str(x) for x in as_list(rule.get("destination_ipv4_groups"), f"forwarding.rules.{rule_name}.destination_ipv4_groups")],
                4,
                f"forwarding.rules.{rule_name}.destination_ipv4_groups",
            )
            direct_src4 = direct_cidrs_for_version(as_list(rule.get("source_ipv4"), f"forwarding.rules.{rule_name}.source_ipv4"), 4, f"forwarding.rules.{rule_name}.source_ipv4", ctx)
            direct_dst4 = direct_cidrs_for_version(as_list(rule.get("destination_ipv4"), f"forwarding.rules.{rule_name}.destination_ipv4"), 4, f"forwarding.rules.{rule_name}.destination_ipv4", ctx)
            for fi in from_exprs:
                for ti in to_exprs:
                    elems = []
                    if fi:
                        elems.append(fi)
                    if ti:
                        elems.append(ti)
                    if src4_refs:
                        elems.append(f"ip saddr {src4_refs[0]}")
                    if direct_src4:
                        elems.append(f"ip saddr {nft_set(direct_src4)}")
                    if dst4_refs:
                        elems.append(f"ip daddr {dst4_refs[0]}")
                    if direct_dst4:
                        elems.append(f"ip daddr {nft_set(direct_dst4)}")
                    elems.append("counter accept")
                    elems.append(comment_expr(f"forward {rule_name}").strip())
                    lines.append(add_rule(policy, forward_chain, " ".join(x for x in elems if x)))

    container_forwarding_active = as_bool(forwarding.get("enabled"), False) or as_bool(forwarding.get("router_mode"), False)
    wan_direct = as_dict(policy.get("interfaces"), "interfaces").get("wan", [])
    wan_block = {"interfaces": wan_direct} if wan_direct else {"interface_groups": ["wan"]}
    wan_exprs = interface_match_exprs(maps, wan_block, "out", "interfaces.wan")
    for cname, raw_cspec in containers.items():
        cspec = as_dict(raw_cspec, f"containers.{cname}")
        if not as_bool(cspec.get("enabled"), False):
            continue
        if not as_bool(cspec.get("allow_container_outbound"), False):
            continue
        if not container_forwarding_active:
            ctx.skip(f"containers.{cname}: outbound forwarding requested but forwarding.enabled/router_mode is false")
            continue
        c_exprs = interface_match_exprs(maps, {"interfaces": cspec.get("interfaces", []), "interface_groups": cspec.get("interface_groups", [])}, "in", f"containers.{cname}")
        for c_expr in c_exprs:
            for wan_expr in wan_exprs:
                if c_expr and wan_expr:
                    lines.append(add_rule(policy, forward_chain, f"{c_expr} {wan_expr} counter accept" + comment_expr(f"container outbound {cname}")))

    lines.extend(build_link_local_noise_drop_rules(policy))
    lines.extend(build_drop_log_rules(policy, logging))

    lines.append("")
    return "\n".join(lines)


def render_nat(policy: Mapping[str, Any], maps: Mapping[str, Dict[str, Any]]) -> str:
    nft = as_dict(policy.get("nftables"), "nftables")
    nat = as_dict(policy.get("nat"), "nat")
    containers = as_dict(policy.get("containers"), "containers")
    enabled = as_bool(nat.get("enabled"), False)
    masq = as_dict(nat.get("masquerade"), "nat.masquerade")
    masq_enabled = enabled and as_bool(masq.get("enabled"), False)
    # Container outbound commonly requires masquerade on single-host workstations.
    container_wants_nat = False
    for cspec in containers.values():
        c = as_dict(cspec, "containers.*")
        if as_bool(c.get("enabled"), False) and as_bool(c.get("allow_container_outbound"), False):
            container_wants_nat = True
    nat_required = enabled or masq_enabled

    family = validate_nft_family(nft.get("nat_family", "ip"), "nftables.nat_family", NFT_NAT_FAMILIES)
    table = validate_nft_identifier(nft.get("nat_table", "nat"), "nftables.nat_table")
    lines = ["# Managed by nft-policy-generate.py.", "# NAT rules", ""]
    if not nat_required:
        if container_wants_nat:
            lines.append("# Container outbound is enabled, but nat.enabled is false; no masquerade rule generated.")
        else:
            lines.append("# NAT disabled by profile.")
        lines.append("")
        return "\n".join(lines)

    lines.extend([
        f"table {family} {table} {{",
        "    chain prerouting {",
        "        type nat hook prerouting priority -100; policy accept;",
        "    }",
        "",
        "    chain postrouting {",
        "        type nat hook postrouting priority 100; policy accept;",
        "    }",
        "}",
        "",
    ])

    if masq_enabled:
        out_exprs = interface_match_exprs(maps, {"interfaces": masq.get("out_interfaces", []), "interface_groups": [masq.get("out_interface_group", "wan")] if masq.get("out_interface_group", "wan") else []}, "out", "nat.masquerade.out")
        src4_refs = cidr_refs(
            maps,
            [str(x) for x in as_list(masq.get("source_ipv4_groups"), "nat.masquerade.source_ipv4_groups")],
            4,
            "nat.masquerade.source_ipv4_groups",
        )
        src4_direct = direct_cidrs_for_version(as_list(masq.get("source_ipv4"), "nat.masquerade.source_ipv4"), 4, "nat.masquerade.source_ipv4", RenderContext())
        if not out_exprs:
            raise PolicyError("nat.masquerade requires at least one out interface")
        for out_expr in out_exprs:
            for src_ref in src4_refs:
                lines.append(f"add rule {family} {table} postrouting {out_expr} ip saddr {src_ref} counter masquerade" + comment_expr("masquerade"))
            if src4_direct:
                lines.append(f"add rule {family} {table} postrouting {out_expr} ip saddr {nft_set(src4_direct)} counter masquerade" + comment_expr("masquerade direct"))

    dnat_rules = as_dict(nat.get("dnat_rules"), "nat.dnat_rules")
    for name, raw_rule in dnat_rules.items():
        rule = as_dict(raw_rule, f"nat.dnat_rules.{name}")
        if not as_bool(rule.get("enabled"), False):
            continue
        proto = str(rule.get("proto", rule.get("protocol", "tcp"))).lower()
        if proto not in PROTO_SET:
            raise PolicyError(f"nat.dnat_rules.{name}.proto unsupported {proto!r}")
        public_port = normalize_port(rule.get("public_port"), f"nat.dnat_rules.{name}.public_port")
        target_ip = str(ipaddress.ip_address(str(rule.get("target_ip"))))
        target_port = normalize_port(rule.get("target_port"), f"nat.dnat_rules.{name}.target_port")
        lines.append(f"add rule {family} {table} prerouting {proto} dport {public_port} counter dnat to {target_ip}:{target_port}" + comment_expr(f"dnat {name}"))

    lines.append("")
    return "\n".join(lines)


def render_local(policy: Mapping[str, Any]) -> str:
    local = as_dict(policy.get("local"), "local")
    if as_bool(local.get("allow_raw_nft"), False):
        return """# Managed by nft-policy-generate.py.
# Raw local nft is permitted by profile, but this generator does not emit raw YAML snippets.
include "/etc/nftables.d/95-firewall-security.nft"
"""
    return """# Managed by nft-policy-generate.py.
# Local override fragment.
#
# The base table exposes local_input/local_forward/local_output chains for
# controlled extension points. The Firewall Security launcher owns the included
# persistent fragment; do not add hand-written rules to this generated file.
include "/etc/nftables.d/95-firewall-security.nft"
"""


def render_all(policy: Mapping[str, Any], paths: Mapping[str, Path], ctx: RenderContext, allow_public_sensitive: bool) -> Dict[Path, str]:
    maps = build_define_maps(policy, ctx)
    return {
        paths["nftables_conf"]: render_nftables_conf(policy, paths),
        paths["defines"]: render_defines(policy, maps),
        paths["base"]: render_base(policy),
        paths["filter"]: render_filter(policy, maps, ctx, allow_public_sensitive),
        paths["nat"]: render_nat(policy, maps),
        paths["local"]: render_local(policy),
    }


def validate_unresolved(policy: Any, path: str = "policy") -> None:
    if isinstance(policy, dict):
        for k, v in policy.items():
            validate_unresolved(v, f"{path}.{k}")
    elif isinstance(policy, list):
        for i, v in enumerate(policy):
            validate_unresolved(v, f"{path}[{i}]")
    elif isinstance(policy, str):
        if UNRESOLVED_RE.search(policy):
            raise PolicyError(f"{path}: unresolved placeholder {policy!r}")


def validate_policy(policy: Mapping[str, Any], ctx: RenderContext, reject_unresolved: bool) -> None:
    require_kind(policy, PROFILE_KIND, Path("<merged-policy>"))
    if reject_unresolved:
        validate_unresolved(policy)
    # Force early validation of groups.
    build_define_maps(policy, ctx)


def atomic_write(path: Path, content: str, mode: int = 0o0644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            if not content.endswith("\n"):
                f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, path)
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass


def backup_existing(files: Sequence[Path], backup_dir: Path) -> Optional[Path]:
    existing = [p for p in files if p.exists()]
    if not existing:
        return None
    timestamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = backup_dir / f"nftables-{timestamp}"
    for attempt in range(100):
        target = base if attempt == 0 else backup_dir / f"nftables-{timestamp}-{attempt:02d}"
        try:
            target.mkdir(parents=True, exist_ok=False)
            break
        except FileExistsError:
            continue
    else:
        raise PolicyError(f"cannot allocate unique backup directory under {backup_dir}")
    for src in existing:
        rel = str(src).lstrip("/")
        dst = target / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    return target


def run_checked(argv: Sequence[str], label: str, timeout_seconds: int = DEFAULT_COMMAND_TIMEOUT_SECONDS) -> None:
    try:
        result = subprocess.run(list(argv), check=False, text=True, capture_output=True, timeout=timeout_seconds)
    except FileNotFoundError as exc:
        raise PolicyError(f"{label}: executable not found: {argv[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise PolicyError(f"{label}: timed out after {timeout_seconds} seconds") from exc
    if result.returncode != 0:
        msg = [f"{label} failed with exit code {result.returncode}", f"command: {' '.join(argv)}"]
        if result.stdout:
            msg.append("stdout:\n" + result.stdout.strip())
        if result.stderr:
            msg.append("stderr:\n" + result.stderr.strip())
        raise PolicyError("\n".join(msg))


def resolve_executable(name: str, fallback: str) -> str:
    resolved = shutil.which(name)
    if resolved:
        return resolved
    if Path(fallback).exists():
        return fallback
    return name


def load_policy(profile_path: Path, overlay_paths: Sequence[Path], force_overlay: bool, ctx: RenderContext) -> Dict[str, Any]:
    profile = load_yaml_file(profile_path)
    require_kind(profile, PROFILE_KIND, profile_path)
    policy = copy.deepcopy(profile)

    sorted_overlays: List[Tuple[int, Path, Dict[str, Any]]] = []
    for overlay_path in overlay_paths:
        overlay = load_yaml_file(overlay_path)
        require_kind(overlay, OVERLAY_KIND, overlay_path)
        meta = as_dict(overlay.get("metadata"), f"{overlay_path}: metadata")
        prio = as_int(meta.get("merge_priority", 50), f"{overlay_path}: metadata.merge_priority", 0, 1000)
        sorted_overlays.append((prio, overlay_path, overlay))
    sorted_overlays.sort(key=lambda item: (item[0], str(item[1])))

    for _, overlay_path, overlay in sorted_overlays:
        policy = merge_overlay(policy, overlay, overlay_path, force_overlay, ctx)
    return policy


def apply_runtime_cidrs(policy: Dict[str, Any], runtime_cidrs: Sequence[str], ctx: RenderContext) -> None:
    if not runtime_cidrs:
        return
    cidrs = as_dict(policy.setdefault("cidrs", {}), "cidrs")
    for item in runtime_cidrs:
        if "=" not in item:
            raise PolicyError(f"--add-cidr expects NAME=CIDR, got {item!r}")
        name, raw_value = item.split("=", 1)
        name = name.strip()
        raw_value = raw_value.strip()
        if not NFT_IDENT_RE.fullmatch(name):
            raise PolicyError(f"--add-cidr has invalid CIDR group name {name!r}")
        if not raw_value:
            raise PolicyError(f"--add-cidr {name}: CIDR value is empty")
        v4, v6 = parse_networks([raw_value], f"runtime_cidrs.{name}", ctx)
        normalized = v4 + v6
        if len(normalized) != 1:
            raise PolicyError(f"--add-cidr {name}: expected exactly one CIDR/IP value")
        existing = as_list(cidrs.get(name), f"cidrs.{name}")
        cidrs[name] = unique_preserve(existing + normalized)


def print_rendered(rendered: Mapping[Path, str]) -> None:
    for path, content in rendered.items():
        print(f"### {path}")
        print(content.rstrip())
        print()


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate nftables files from a profile YAML and optional service overlay YAML files."
    )
    parser.add_argument("--profile", required=True, type=Path, help="Path to baseline/desktop/server YAML profile.")
    parser.add_argument("--overlay", action="append", default=[], type=Path, help="Optional service overlay YAML. May be repeated.")
    parser.add_argument("--target-root", default=Path("/"), type=Path, help="Root under which absolute output paths are written. Use for staging/tests.")
    parser.add_argument("--write", action="store_true", help="Write generated files to disk. Without this, use --print to inspect output.")
    parser.add_argument("--print", dest="print_output", action="store_true", help="Print generated files to stdout.")
    parser.add_argument("--check", action="store_true", help="Run nft -c -f against generated nftables.conf after writing.")
    parser.add_argument("--reload", action="store_true", help="Reload nftables via systemctl after successful validation.")
    parser.add_argument("--backup", action="store_true", help="Backup existing target files before writing.")
    parser.add_argument("--backup-dir", default=Path("/var/backups/nftables"), type=Path, help="Backup directory.")
    parser.add_argument("--force-overlay", action="store_true", help="Allow overlays whose applies_to_profiles does not match the profile.")
    parser.add_argument("--add-cidr", action="append", default=[], metavar="NAME=CIDR", help="Append a runtime CIDR/IP value to a policy CIDR group. May be repeated.")
    parser.add_argument("--allow-public-sensitive", action="store_true", help="Allow sensitive services to use any_ipv4/any_ipv6 or 0.0.0.0/0/::/0.")
    parser.add_argument("--allow-placeholders", action="store_true", help="Do not reject placeholder strings. Not recommended.")
    parser.add_argument("--command-timeout", default=DEFAULT_COMMAND_TIMEOUT_SECONDS, type=int, help="Seconds to wait for nft/systemctl commands.")
    parser.add_argument(
        "--log-level",
        default=os.environ.get("NFTABLES_LOG_LEVEL", "none"),
        help="Generator diagnostic verbosity only: debug, info, warning, error, or none.",
    )
    parser.add_argument("--summary", action="store_true", help="Print a concise summary to stderr.")
    args = parser.parse_args(argv)
    args.command_timeout = as_int(args.command_timeout, "--command-timeout", 1, 600)
    return args


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    ctx = RenderContext()
    try:
        set_log_level(args.log_level)
        policy = load_policy(args.profile, args.overlay, args.force_overlay, ctx)
        apply_runtime_cidrs(policy, args.add_cidr, ctx)
        safety = as_dict(policy.get("safety"), "safety")
        reject_unresolved = as_bool(safety.get("reject_unresolved_placeholders"), True) and not args.allow_placeholders
        validate_policy(policy, ctx, reject_unresolved=reject_unresolved)
        paths = output_paths(policy, args.target_root)
        rendered = render_all(policy, paths, ctx, args.allow_public_sensitive)

        if args.print_output or not args.write:
            print_rendered(rendered)

        if args.write:
            if args.backup or as_bool(safety.get("backup_before_apply"), False):
                backup_dir = map_to_target_root(args.backup_dir, args.target_root) if args.backup_dir.is_absolute() else args.backup_dir
                backup_path = backup_existing(list(rendered.keys()), backup_dir)
                if backup_path:
                    eprint(f"backup: {backup_path}")
            for path, content in rendered.items():
                mode = 0o0755 if path.name == "nftables.conf" else 0o0644
                atomic_write(path, content, mode=mode)
                eprint(f"wrote: {path}")

        if args.check:
            if not args.write:
                raise PolicyError("--check requires --write so nft can read generated include files")
            conf_path = paths["nftables_conf"]
            nft_bin = resolve_executable("nft", "/usr/sbin/nft")
            run_checked([nft_bin, "-c", "-f", str(conf_path)], "nft validation", timeout_seconds=args.command_timeout)
            eprint("nft validation: ok")

        if args.reload:
            if not args.check:
                raise PolicyError("--reload requires --check")
            if str(args.target_root.resolve()) != "/":
                raise PolicyError("--reload is only allowed with --target-root /")
            systemctl_bin = resolve_executable("systemctl", "/usr/bin/systemctl")
            run_checked([systemctl_bin, "reload", "nftables"], "nftables reload", timeout_seconds=args.command_timeout)
            eprint("nftables reload: ok")

        if args.summary:
            services = as_dict(policy.get("services"), "services")
            enabled = [name for name, spec in services.items() if as_bool(as_dict(spec, f"services.{name}").get("enabled"), False)]
            eprint(f"profile: {as_dict(policy.get('metadata'), 'metadata').get('name', 'unknown')}")
            eprint(f"overlays: {len(args.overlay)}")
            eprint(f"runtime cidrs: {len(args.add_cidr)}")
            eprint(f"enabled services: {', '.join(sorted(enabled)) if enabled else 'none'}")
            eprint(f"egress enforced: {egress_enforced(policy)}")

        for warning in unique_preserve(ctx.warnings):
            eprint(f"warning: {warning}", level="warning")
        for skipped in unique_preserve(ctx.skipped):
            eprint(f"skipped: {skipped}", level="debug")
        return 0
    except PolicyError as exc:
        eprint(f"error: {exc}", level="error")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
