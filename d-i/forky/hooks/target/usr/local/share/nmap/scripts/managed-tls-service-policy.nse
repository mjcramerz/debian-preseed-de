local shortport = require "shortport"
local stdnse = require "stdnse"

description = [[
Reports whether services on common TLS ports were identified as tunneled
through TLS. Pair this policy summary with Nmap's ssl-cert and
ssl-enum-ciphers scripts for certificate and cipher details.
]]

author = "Managed Debian desktop automation"
license = "Same as Nmap--See https://nmap.org/book/man-legal.html"
categories = {"safe", "discovery"}

local tls_ports = {
  [443] = "HTTPS",
  [465] = "SMTPS",
  [636] = "LDAPS",
  [853] = "DNS over TLS",
  [993] = "IMAPS",
  [995] = "POP3S",
  [8443] = "Alternate HTTPS",
}

portrule = function(host, port)
  return port.state == "open"
    and port.protocol == "tcp"
    and (
      tls_ports[port.number] ~= nil
      or shortport.ssl(host, port)
    )
end

action = function(host, port)
  local version = port.version or {}
  local service = string.lower(port.service or "")
  local tunnel = string.lower(version.service_tunnel or "")
  local expected_service = tls_ports[port.number]
    or string.format("TLS-enabled service on TCP/%s", port.number)
  local detected_tls = tunnel == "ssl"
    or service == "https"
    or string.find(service, "ssl", 1, true) ~= nil
    or string.find(service, "tls", 1, true) ~= nil
  local status = detected_tls and "PRESENT" or "REVIEW"
  local output = stdnse.output_table()
  output.status = status
  output.expected_tls_service = expected_service
  output.detected_service = service ~= "" and service or "unknown"
  output.detected_tunnel = tunnel ~= "" and tunnel or "none"
  return output
end
