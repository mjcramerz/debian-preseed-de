local stdnse = require "stdnse"

description = [[
Reports open name-resolution and discovery services whose exposure should be
limited to the intended local network segments.
]]

author = "Managed Debian desktop automation"
license = "Same as Nmap--See https://nmap.org/book/man-legal.html"
categories = {"safe", "discovery"}

local discovery_ports = {
  [53] = {name = "DNS", tcp = true, udp = true},
  [137] = {name = "NetBIOS name service", udp = true},
  [1900] = {name = "SSDP", udp = true},
  [5353] = {name = "mDNS", udp = true},
  [5355] = {name = "LLMNR", udp = true},
}

portrule = function(host, port)
  local policy = discovery_ports[port.number]
  return port.state == "open"
    and policy ~= nil
    and policy[port.protocol] == true
end

action = function(host, port)
  local service = discovery_ports[port.number].name
  local output = stdnse.output_table()
  output.status = "REVIEW"
  output.name_resolution_service = service
  output.port = port.number
  output.protocol = port.protocol
  output.recommendation =
    "Confirm the service is bound only to approved interfaces and network zones."
  return output
end
