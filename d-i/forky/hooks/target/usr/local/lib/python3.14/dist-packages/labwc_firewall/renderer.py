"""Render validated managed firewall state into nftables commands."""

from __future__ import annotations

from .state import Rule


LAN_IPV4 = "{ 10.0.0.0/8, 100.64.0.0/10, 169.254.0.0/16, 172.16.0.0/12, 192.168.0.0/16 }"
LAN_IPV6 = "{ fc00::/7, fe80::/10 }"


def render_fragment(rules: list[Rule]) -> str:
    lines = [
        "# Managed by labwc-firewall-action-root.",
        "# Persistent Computer Management firewall rules.",
    ]
    for rule in rules:
        chain = "local_input" if rule.direction == "incoming" else "local_output"
        address_direction = "saddr" if rule.direction == "incoming" else "daddr"
        verdict = "accept" if rule.verdict == "allow" else "drop"
        suffix = (
            f'{rule.protocol} dport {rule.port} counter {verdict} '
            f'comment "firewall-security {rule.rule_id}"'
        )
        if rule.scope == "any":
            lines.append(f"add rule inet filter {chain} {suffix}")
        elif rule.scope == "lan":
            lines.append(
                f"add rule inet filter {chain} ip {address_direction} {LAN_IPV4} {suffix}"
            )
            lines.append(
                f"add rule inet filter {chain} ip6 {address_direction} {LAN_IPV6} {suffix}"
            )
        else:
            family = "ip" if ":" not in rule.cidr else "ip6"
            lines.append(
                f"add rule inet filter {chain} {family} {address_direction} "
                f"{rule.cidr} {suffix}"
            )
    if not rules:
        lines.append("# No Computer Management firewall rules are configured.")
    return "\n".join(lines) + "\n"
