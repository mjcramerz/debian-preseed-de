"""Shared, bounded parsing of the administrator's application network policy."""

from __future__ import annotations

import json
import ipaddress
import os
from pathlib import PurePosixPath
import re
import stat

CONFIG_PATH = "/etc/app-veth.json"
MAX_CONFIG_BYTES = 65536
MAX_APPS = 128
APP_NAME = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
PRIVATE_IPV4_NETWORKS = tuple(ipaddress.IPv4Network(value) for value in
                              ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
NETWORK_FIELDS = frozenset((
    "ipv4_cidr", "max_leases", "host_interface_prefix", "host_interface_suffix",
    "peer_interface_suffix", "namespace_interface", "dns_address",
    "dns_host_address", "dns_host_port",
))


def parse_network(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != NETWORK_FIELDS:
        raise ValueError("invalid managed network identity fields")
    network = dict(value)
    try:
        pool = ipaddress.IPv4Network(network["ipv4_cidr"])
        dns = ipaddress.IPv4Address(network["dns_address"])
        listener = ipaddress.IPv4Address(network["dns_host_address"])
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid managed network addresses") from exc
    count = network["max_leases"]
    if (not isinstance(network["ipv4_cidr"], str) or str(pool) != network["ipv4_cidr"]
            or not 16 <= pool.prefixlen <= 30 or not any(pool.subnet_of(item) for item in PRIVATE_IPV4_NETWORKS)
            or type(count) is not int or not 1 <= count <= 128 or count * 4 > pool.num_addresses
            or not any(dns in item for item in PRIVATE_IPV4_NETWORKS) or dns in pool
            or str(dns) != network["dns_address"] or not listener.is_loopback
            or str(listener) != network["dns_host_address"]
            or type(network["dns_host_port"]) is not int or not 1024 <= network["dns_host_port"] <= 65535):
        raise ValueError("invalid managed network address range or capacity")
    for key in ("host_interface_prefix", "namespace_interface"):
        if not isinstance(network[key], str) or re.fullmatch(r"[a-z][a-z0-9]{0,14}", network[key]) is None:
            raise ValueError("invalid managed network interface name")
    for key in ("host_interface_suffix", "peer_interface_suffix"):
        if not isinstance(network[key], str) or re.fullmatch(r"-[a-z][a-z0-9]{0,8}", network[key]) is None:
            raise ValueError("invalid managed network interface suffix")
    if (network["namespace_interface"] == "lo"
            or network["host_interface_suffix"] == network["peer_interface_suffix"]
            or any(len(network["host_interface_prefix"] + str(count - 1) + network[key]) > 15
                   for key in ("host_interface_suffix", "peer_interface_suffix"))):
        raise ValueError("managed network interface names collide or exceed IFNAMSIZ")
    return network


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate application network configuration key")
        result[key] = value
    return result


def parse_configuration(raw: bytes) -> dict:
    if len(raw) > MAX_CONFIG_BYTES:
        raise ValueError("oversized managed network configuration")
    try:
        conf = json.loads(raw, object_pairs_hook=_unique_object)
    except (UnicodeError, RecursionError, json.JSONDecodeError) as exc:
        raise ValueError("invalid managed network JSON") from exc
    if (not isinstance(conf, dict) or set(conf) != {"version", "desktop_user", "apps", "network"}
            or type(conf["version"]) is not int or conf["version"] != 2
            or not isinstance(conf["desktop_user"], str)
            or re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", conf["desktop_user"]) is None
            or conf["desktop_user"] == "root"
            or not isinstance(conf["apps"], dict) or len(conf["apps"]) > MAX_APPS):
        raise ValueError("invalid managed network configuration")
    network = parse_network(conf["network"])
    pool = ipaddress.IPv4Network(network["ipv4_cidr"])
    apps = {}
    paths = set()
    assigned_slots = set()
    for name, policy in conf["apps"].items():
        if (APP_NAME.fullmatch(name) is None or not isinstance(policy, dict)
                or not set(policy) <= {"network", "block_lan", "peer_port", "pin_route", "executables", "slots", "addresses"}
                or "network" not in policy):
            raise ValueError("invalid application network policy")
        enabled = policy["network"]
        block_lan = policy.get("block_lan", False)
        port = policy.get("peer_port")
        pinned = policy.get("pin_route", port is not None)
        executables = policy.get("executables", [])
        slots = policy.get("slots")
        if (not isinstance(slots, list) or not 1 <= len(slots) <= network["max_leases"]
                or any(type(slot) is not int or not 0 <= slot < network["max_leases"] for slot in slots)
                or len(set(slots)) != len(slots) or assigned_slots.intersection(slots)
                or ((port is not None or pinned is True) and len(slots) != 1)):
            raise ValueError("invalid, duplicate or missing reserved application network slots")
        assigned_slots.update(slots)
        addresses = policy.get("addresses")
        if addresses != [str(pool.network_address + slot * 4 + 2) for slot in slots]:
            raise ValueError("missing or inconsistent reserved application IPv4 addresses")
        if (type(enabled) is not bool or type(block_lan) is not bool
                or type(pinned) is not bool
                or (port is not None and (type(port) is not int or not 1024 <= port <= 65535))
                or (not enabled and port is not None)
                or (port is not None and not pinned)
                or not isinstance(executables, list) or len(executables) > 16):
            raise ValueError("invalid application network settings")
        for executable in executables:
            if (not isinstance(executable, str) or len(executable) > 4096
                    or not executable.startswith(("/usr/bin/", "/usr/local/bin/", "/usr/lib/", "/opt/"))
                    or any(ord(character) < 32 or ord(character) == 127 for character in executable)
                    or str(PurePosixPath(executable)) != executable
                    or ".." in PurePosixPath(executable).parts or executable in paths):
                raise ValueError("invalid or duplicate application executable")
            paths.add(executable)
        apps[name] = {"network": enabled, "block_lan": block_lan, "peer_port": port,
                      "pin_route": pinned, "executables": tuple(executables),
                      "slots": tuple(slots), "addresses": tuple(addresses)}
    return {"version": conf["version"], "desktop_user": conf["desktop_user"], "network": network, "apps": apps}


def read_configuration(path: str = CONFIG_PATH, *, owner_uid: int = 0) -> dict:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(fd, "rb") as stream:
        meta = os.fstat(stream.fileno())
        if (not stat.S_ISREG(meta.st_mode) or meta.st_uid != owner_uid
                or meta.st_mode & 0o022 or meta.st_nlink != 1):
            raise ValueError("unsafe managed network configuration")
        raw = stream.read(MAX_CONFIG_BYTES + 1)
    return parse_configuration(raw)
