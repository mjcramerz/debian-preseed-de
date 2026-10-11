#!/bin/sh
# Shared installer-only map for network identity, desktop bindings and policy.
# Values cross into awk through stdin as data; no eval or environment dump.
app_veth_identity_placeholder_map() (
  printf '%s=%s\n' \
    APP_VETH_IPV4_CIDR "${APP_VETH_IPV4_CIDR:-}" \
    APP_VETH_MAX_LEASES "${APP_VETH_MAX_LEASES:-}" \
    APP_VETH_HOST_INTERFACE_PREFIX "${APP_VETH_HOST_INTERFACE_PREFIX:-}" \
    APP_VETH_HOST_INTERFACE_SUFFIX "${APP_VETH_HOST_INTERFACE_SUFFIX:-}" \
    APP_VETH_PEER_INTERFACE_SUFFIX "${APP_VETH_PEER_INTERFACE_SUFFIX:-}" \
    APP_VETH_NAMESPACE_INTERFACE "${APP_VETH_NAMESPACE_INTERFACE:-}" \
    APP_VETH_DNS_ADDRESS "${APP_VETH_DNS_ADDRESS:-}" \
    APP_VETH_DNS_HOST_ADDRESS "${APP_VETH_DNS_HOST_ADDRESS:-}" \
    APP_VETH_DNS_HOST_PORT "${APP_VETH_DNS_HOST_PORT:-}" \
    APP_VETH_TLS_HOST_ADDRESS "${APP_VETH_TLS_HOST_ADDRESS:-}" \
    APP_VETH_TLS_HOST_PORT "${APP_VETH_TLS_HOST_PORT:-}" \
    APP_VETH_SLOTS_BITWARDEN "${APP_VETH_SLOTS_BITWARDEN:-}" \
    APP_VETH_SLOTS_CHATGPT "${APP_VETH_SLOTS_CHATGPT:-}" \
    APP_VETH_SLOTS_CHROMIUM "${APP_VETH_SLOTS_CHROMIUM:-}" \
    APP_VETH_SLOTS_CODE "${APP_VETH_SLOTS_CODE:-}" \
    APP_VETH_SLOTS_CODEX "${APP_VETH_SLOTS_CODEX:-}" \
    APP_VETH_SLOTS_DISCORD "${APP_VETH_SLOTS_DISCORD:-}" \
    APP_VETH_SLOTS_FILEN "${APP_VETH_SLOTS_FILEN:-}" \
    APP_VETH_SLOTS_FREERDP "${APP_VETH_SLOTS_FREERDP:-}" \
    APP_VETH_SLOTS_LEDGER_LIVE "${APP_VETH_SLOTS_LEDGER_LIVE:-}" \
    APP_VETH_SLOTS_LIFEREA "${APP_VETH_SLOTS_LIFEREA:-}" \
    APP_VETH_SLOTS_MICROSOFT_EDGE "${APP_VETH_SLOTS_MICROSOFT_EDGE:-}" \
    APP_VETH_SLOTS_MULLVAD_BROWSER "${APP_VETH_SLOTS_MULLVAD_BROWSER:-}" \
    APP_VETH_SLOTS_OBSIDIAN "${APP_VETH_SLOTS_OBSIDIAN:-}" \
    APP_VETH_SLOTS_POSTMAN "${APP_VETH_SLOTS_POSTMAN:-}" \
    APP_VETH_SLOTS_QBITTORRENT "${APP_VETH_SLOTS_QBITTORRENT:-}" \
    APP_VETH_SLOTS_QBITTORRENT_PRIVACY "${APP_VETH_SLOTS_QBITTORRENT_PRIVACY:-}" \
    APP_VETH_SLOTS_QOREDB "${APP_VETH_SLOTS_QOREDB:-}" \
    APP_VETH_SLOTS_SPOTIFY "${APP_VETH_SLOTS_SPOTIFY:-}" \
    APP_VETH_SLOTS_TELEGRAM_DESKTOP "${APP_VETH_SLOTS_TELEGRAM_DESKTOP:-}" \
    APP_VETH_SLOTS_TUTANOTA "${APP_VETH_SLOTS_TUTANOTA:-}" \
    APP_VETH_SLOTS_VIVALDI "${APP_VETH_SLOTS_VIVALDI:-}" \
    APP_VETH_SLOTS_ZOOM "${APP_VETH_SLOTS_ZOOM:-}" \
    APP_VETH_SLOTS_PODMAN "${APP_VETH_SLOTS_PODMAN:-}" |
  LC_ALL=C awk '
    function fail(key) { failed = 1; print "fatal: invalid " key " in app-veth identity" > "/dev/stderr"; exit 1 }
    function integer(key, low, high, value) {
      value = values[key]
      if (value !~ /^(0|[1-9][0-9]*)$/ || length(value) > 5 || value + 0 < low || value + 0 > high) fail(key)
      return value + 0
    }
    function ipv4(key, value, parts, count, i, number) {
      value = values[key]; count = split(value, parts, /\./)
      if (count != 4) fail(key)
      for (i = 1; i <= 4; i++) {
        if (parts[i] !~ /^(0|[1-9][0-9]*)$/ || length(parts[i]) > 3 || parts[i] + 0 > 255) fail(key)
        number = number * 256 + parts[i]
      }
      return number
    }
    function address(number) {
      return int(number / 16777216) "." int(number / 65536) % 256 "." int(number / 256) % 256 "." number % 256
    }
    function private_ipv4(number, first, second) {
      first = int(number / 16777216); second = int(number / 65536) % 256
      return first == 10 || (first == 172 && second >= 16 && second <= 31) || (first == 192 && second == 168)
    }
    function name(key, value) {
      value = values[key]
      if (value !~ /^[a-z][a-z0-9]*$/ || length(value) > 15) fail(key)
      return value
    }
    function suffix(key, value) {
      value = values[key]
      if (value !~ /^-[a-z][a-z0-9]*$/ || length(value) > 10) fail(key)
      return value
    }
    function loopback(key, number) {
      number = ipv4(key)
      if (int(number / 16777216) != 127) fail(key)
      return values[key]
    }
    {
      position = index($0, "="); key = substr($0, 1, position - 1)
      if (!position || key !~ /^APP_VETH_[A-Z0-9_]+$/ || key in values || length($0) > 1024) fail(key)
      values[key] = substr($0, position + 1)
    }
    END {
      if (failed) exit 1
      cidr = values["APP_VETH_IPV4_CIDR"]
      if (split(cidr, parts, /\//) != 2 || parts[2] !~ /^(1[6-9]|2[0-9]|30)$/) fail("APP_VETH_IPV4_CIDR")
      values["pool_address"] = parts[1]; base = ipv4("pool_address"); size = 2 ^ (32 - parts[2])
      if (!private_ipv4(base) || base % size) fail("APP_VETH_IPV4_CIDR")
      leases = integer("APP_VETH_MAX_LEASES", 1, 128)
      if (leases * 4 > size) fail("APP_VETH_MAX_LEASES")
      prefix = name("APP_VETH_HOST_INTERFACE_PREFIX")
      host_suffix = suffix("APP_VETH_HOST_INTERFACE_SUFFIX")
      peer_suffix = suffix("APP_VETH_PEER_INTERFACE_SUFFIX")
      guest = name("APP_VETH_NAMESPACE_INTERFACE")
      if (guest == "lo" || host_suffix == peer_suffix || length(prefix (leases - 1) host_suffix) > 15 || length(prefix (leases - 1) peer_suffix) > 15) fail("APP_VETH interface names")
      dns = ipv4("APP_VETH_DNS_ADDRESS")
      if (!private_ipv4(dns) || (dns >= base && dns < base + size)) fail("APP_VETH_DNS_ADDRESS")
      loopback("APP_VETH_DNS_HOST_ADDRESS"); loopback("APP_VETH_TLS_HOST_ADDRESS")
      integer("APP_VETH_DNS_HOST_PORT", 1024, 65535); integer("APP_VETH_TLS_HOST_PORT", 1024, 65535)
      if (values["APP_VETH_DNS_HOST_ADDRESS"] == values["APP_VETH_TLS_HOST_ADDRESS"] && values["APP_VETH_DNS_HOST_PORT"] == values["APP_VETH_TLS_HOST_PORT"]) fail("APP_VETH DNS listener collision")
      for (key in values) {
        if (key !~ /^APP_VETH_SLOTS_/) continue
        count = split(values[key], slots, /,/); rendered = "["; addresses = "["
        if (count < 1 || count > leases) fail(key)
        for (i = 1; i <= count; i++) {
          if (slots[i] !~ /^(0|[1-9][0-9]*)$/ || length(slots[i]) > 3 || slots[i] + 0 >= leases || slots[i] in used) fail(key)
          used[slots[i]] = 1
          rendered = rendered (i > 1 ? "," : "") slots[i]
          addresses = addresses (i > 1 ? "," : "") "\"" address(base + slots[i] * 4 + 2) "\""
        }
        if (key == "APP_VETH_SLOTS_QBITTORRENT" && count != 1) fail(key)
        values[key] = rendered "]"
        app = substr(key, 16)
        values["APP_VETH_" app "_ADDRESS"] = address(base + slots[1] * 4 + 2)
        values["APP_VETH_ADDRESSES_" app] = addresses "]"
      }
      matches = "match-device="
      host_interfaces = "["
      for (slot = 0; slot < leases; slot++) {
        matches = matches (slot ? ";" : "") "interface-name:=" prefix slot host_suffix ";interface-name:=" prefix slot peer_suffix
        host_interfaces = host_interfaces (slot ? "," : "") "\"" prefix slot host_suffix "\""
      }
      values["APP_VETH_UNMANAGED_MATCH"] = matches
      values["APP_VETH_HOST_INTERFACES"] = host_interfaces "]"
      for (key in values) if (key ~ /^APP_VETH_/) print key "=" values[key]
    }
  '
)
