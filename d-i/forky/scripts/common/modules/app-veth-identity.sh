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
    APP_VETH_OVERRIDE "${APP_VETH_OVERRIDE:-}" \
    LABWC_QBITTORRENT_PORT "${LABWC_QBITTORRENT_PORT:-50309}" |
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
    function known_app(app, i) {
      for (i = 1; i <= app_count; i++) if (apps[i] == app) return 1
      return 0
    }
    function json_bool(value) { return value ? "true" : "false" }
    BEGIN {
      # This order is the stable address order. APP_VETH_OVERRIDE only filters
      # the set; it cannot make addresses depend on launch order.
      app_count = split("bitwarden,chatgpt,chromium,code,codex,discord,filen,freerdp,ledger-live,liferea,microsoft-edge,mullvad-browser,obsidian,postman,qbittorrent,qbittorrent-privacy,qoredb,spotify,telegram-desktop,tutanota,vivaldi,zoom,podman", apps, /,/)
      block_lan["bitwarden"] = 1
      block_lan["discord"] = 1
      block_lan["filen"] = 1
      block_lan["ledger-live"] = 1
      block_lan["qbittorrent-privacy"] = 1
      block_lan["spotify"] = 1
      block_lan["telegram-desktop"] = 1
      block_lan["tutanota"] = 1
      block_lan["zoom"] = 1
    }
    {
      position = index($0, "="); key = substr($0, 1, position - 1)
      if (!position || key !~ /^[A-Z][A-Z0-9_]+$/ || key in values || length($0) > 1024) fail(key)
      values[key] = substr($0, position + 1)
    }
    END {
      if (failed) exit 1
      cidr = values["APP_VETH_IPV4_CIDR"]
      if (split(cidr, parts, /\//) != 2 || parts[2] !~ /^(1[6-9]|2[0-9]|30)$/) fail("APP_VETH_IPV4_CIDR")
      values["pool_address"] = parts[1]; base = ipv4("pool_address")
      # busybox-udeb omits AWK math support (including exponentiation).
      # Prefix validation above bounds this to at most 16 integer doublings.
      size = 1
      for (bit = parts[2] + 0; bit < 32; bit++) size *= 2
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
      port = integer("LABWC_QBITTORRENT_PORT", 1024, 65535)

      override = values["APP_VETH_OVERRIDE"]
      if (override != "") {
        count = split(override, requested, /,/)
        for (i = 1; i <= count; i++) {
          if (requested[i] !~ /^[a-z][a-z0-9-]*$/ || !known_app(requested[i]) || requested[i] in selected) fail("APP_VETH_OVERRIDE")
          selected[requested[i]] = 1
        }
      } else {
        for (i = 1; i <= app_count; i++) selected[apps[i]] = 1
      }

      apps_json = "{"; rendered_apps = 0; slot = 0
      for (i = 1; i <= app_count; i++) {
        app = apps[i]
        if (!(app in selected)) continue
        count = (app == "qbittorrent" ? 1 : 2)
        if (slot + count > leases) fail("APP_VETH_MAX_LEASES")
        slots_json = "["; addresses_json = "["
        for (j = 0; j < count; j++) {
          current = slot + j
          slots_json = slots_json (j ? "," : "") current
          addresses_json = addresses_json (j ? "," : "") "\"" address(base + current * 4 + 2) "\""
        }
        slots_json = slots_json "]"; addresses_json = addresses_json "]"
        if (rendered_apps++) apps_json = apps_json ","
        apps_json = apps_json "\"" app "\":{"
        apps_json = apps_json "\"network\":true,\"block_lan\":" json_bool(app in block_lan)
        if (app == "qbittorrent") apps_json = apps_json ",\"pin_route\":true,\"peer_port\":" port
        apps_json = apps_json ",\"slots\":" slots_json ",\"addresses\":" addresses_json "}"
        if (app == "qbittorrent") {
          values["APP_VETH_QBITTORRENT_ADDRESS"] = address(base + slot * 4 + 2)
          values["APP_VETH_QBITTORRENT_ENABLED"] = "true"
        }
        slot += count
      }
      if (!rendered_apps) fail("APP_VETH_OVERRIDE")
      values["APP_VETH_APPS_JSON"] = apps_json "}"
      if (!("APP_VETH_QBITTORRENT_ENABLED" in values)) values["APP_VETH_QBITTORRENT_ENABLED"] = "false"
      values["APP_VETH_USED_LEASES"] = slot
      values["APP_VETH_UNMANAGED_MATCH"] = "match-device="
      host_interfaces = "["
      for (slot = 0; slot < leases; slot++) {
        values["APP_VETH_UNMANAGED_MATCH"] = values["APP_VETH_UNMANAGED_MATCH"] (slot ? ";" : "") "interface-name:=" prefix slot host_suffix ";interface-name:=" prefix slot peer_suffix
        host_interfaces = host_interfaces (slot ? "," : "") "\"" prefix slot host_suffix "\""
      }
      values["APP_VETH_HOST_INTERFACES"] = host_interfaces "]"
      for (key in values) if (key ~ /^APP_VETH_/) print key "=" values[key]
    }
  '
)
