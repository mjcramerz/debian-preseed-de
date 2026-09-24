local stdnse = require "stdnse"

description = [[
Formats Nmap service-version results into a compact inventory record for every
open port.
]]

author = "Managed Debian desktop automation"
license = "Same as Nmap--See https://nmap.org/book/man-legal.html"
categories = {"safe", "discovery"}

portrule = function(host, port)
  return port.state == "open"
end

action = function(host, port)
  local version = port.version or {}
  local output = stdnse.output_table()
  output.port = port.number
  output.protocol = port.protocol
  output.service = port.service or "unknown"
  output.product = version.product
  output.version = version.version
  output.extra = version.extrainfo
  output.hostname = version.hostname
  output.tunnel = version.service_tunnel
  output.state_reason = port.reason
  output.service_confidence = version.name_confidence
  if type(version.cpe) == "table" and #version.cpe > 0 then
    output.cpe = version.cpe
  end
  return output
end
