"""Managed firewall state parsing and deterministic serialization."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import stat

from .validation import FirewallError, validate_rule_fields, validate_rule_id


MAX_RULES = 128
MAX_STATE_BYTES = 65_536


@dataclass(frozen=True)
class Rule:
    rule_id: str
    direction: str
    verdict: str
    protocol: str
    port: int
    scope: str
    cidr: str


def _validate_state_file(path: Path) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise FirewallError(f"firewall state file is missing: {path}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise FirewallError(f"firewall state file must be a regular file: {path}")
    if metadata.st_size > MAX_STATE_BYTES:
        raise FirewallError(f"firewall state exceeds {MAX_STATE_BYTES} bytes")


def load_state(path: Path, *, max_rules: int = MAX_RULES) -> list[Rule]:
    _validate_state_file(path)
    rules: list[Rule] = []
    identifiers: set[str] = set()
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            for row_number, raw_line in enumerate(handle, start=1):
                line = raw_line.rstrip("\r\n")
                if not line or line.lstrip().startswith("#"):
                    continue
                fields = line.split("\t")
                if len(fields) != 7:
                    raise FirewallError(
                        f"invalid firewall state row {row_number}: expected 7 fields"
                    )
                rule_id, direction, verdict, protocol, port, scope, cidr = fields
                try:
                    rule_id = validate_rule_id(rule_id)
                    (
                        direction,
                        verdict,
                        protocol,
                        normalized_port,
                        scope,
                        cidr,
                    ) = validate_rule_fields(
                        direction,
                        verdict,
                        protocol,
                        port,
                        scope,
                        cidr,
                    )
                except FirewallError as exc:
                    raise FirewallError(
                        f"invalid firewall state row {row_number}: {exc}"
                    ) from exc
                if rule_id in identifiers:
                    raise FirewallError(
                        f"duplicate firewall rule id at row {row_number}"
                    )
                identifiers.add(rule_id)
                rules.append(
                    Rule(
                        rule_id,
                        direction,
                        verdict,
                        protocol,
                        normalized_port,
                        scope,
                        cidr,
                    )
                )
                if len(rules) > max_rules:
                    raise FirewallError(
                        f"firewall state exceeds {max_rules} managed rules"
                    )
    except OSError as exc:
        raise FirewallError(f"cannot read firewall state: {path}: {exc}") from exc
    return rules


def next_rule_id(rules: list[Rule]) -> str:
    used = {rule.rule_id for rule in rules}
    for number in range(1, 10_000):
        candidate = f"rule-{number:04d}"
        if candidate not in used:
            return candidate
    raise FirewallError("no managed firewall rule identifiers remain")


def serialize_state(rules: list[Rule]) -> str:
    lines = [
        "# Managed by labwc-firewall-action-root.",
        "# id\tdirection\tverdict\tprotocol\tport\tscope\tcidr",
    ]
    for rule in rules:
        lines.append(
            "\t".join(
                (
                    rule.rule_id,
                    rule.direction,
                    rule.verdict,
                    rule.protocol,
                    str(rule.port),
                    rule.scope,
                    rule.cidr,
                )
            )
        )
    return "\n".join(lines) + "\n"


def format_status(rules: list[Rule]) -> str:
    if not rules:
        return "No managed firewall rules are configured.\n"
    lines: list[str] = []
    for rule in rules:
        line = (
            f"{rule.rule_id}: {rule.direction} {rule.verdict} {rule.protocol} "
            f"port {rule.port} scope={rule.scope}"
        )
        if rule.cidr != "-":
            line += f" cidr={rule.cidr}"
        lines.append(line)
    return "\n".join(lines) + "\n"
