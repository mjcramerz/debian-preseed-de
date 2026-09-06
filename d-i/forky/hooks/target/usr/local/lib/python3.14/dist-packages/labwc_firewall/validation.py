"""Validation primitives for the Labwc firewall action."""

from __future__ import annotations

import ipaddress


class FirewallError(RuntimeError):
    """A safe, user-facing firewall action error."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise FirewallError(message)


def validate_port(value: str | int) -> int:
    text = str(value)
    require(
        text.isascii() and text.isdecimal(),
        "firewall port must be an integer from 1 through 65535",
    )
    port = int(text)
    require(
        1 <= port <= 65535,
        "firewall port must be an integer from 1 through 65535",
    )
    return port


def validate_rule_id(value: str) -> str:
    require(
        len(value) == 9 and value.startswith("rule-") and value[5:].isdigit(),
        f"invalid managed firewall rule identifier: {value or 'unset'}",
    )
    return value


def normalize_cidr(value: str) -> str:
    require(len(value) <= 64, "CIDR exceeds 64 characters")
    try:
        if "/" not in value:
            address = ipaddress.ip_address(value)
            value = f"{address}/{address.max_prefixlen}"
        return str(ipaddress.ip_network(value, strict=False))
    except ValueError as exc:
        raise FirewallError("invalid IPv4 or IPv6 firewall CIDR") from exc


def validate_rule_fields(
    direction: str,
    verdict: str,
    protocol: str,
    port: str | int,
    scope: str,
    cidr: str,
) -> tuple[str, str, str, int, str, str]:
    require(direction in {"incoming", "outgoing"}, "invalid firewall direction")
    require(verdict in {"allow", "block"}, "invalid firewall verdict")
    require(protocol in {"tcp", "udp"}, "invalid firewall protocol")
    normalized_port = validate_port(port)
    if scope in {"any", "lan"}:
        require(cidr == "-", f"{scope} firewall scope cannot include a CIDR")
        return direction, verdict, protocol, normalized_port, scope, cidr
    require(scope == "ip", "invalid firewall scope")
    return direction, verdict, protocol, normalized_port, scope, normalize_cidr(cidr)
