local stdnse = require "stdnse"

description = [[
Reports open remote-administration ports so managed hosts can review whether
each administrative surface is expected and access-controlled.
]]

author = "Managed Debian desktop automation"
license = "Same as Nmap--See https://nmap.org/book/man-legal.html"
categories = {"safe", "discovery"}

local admin_ports = {
  [22] = "SSH",
  [23] = "Telnet",
  [2375] = "Docker API (plaintext)",
  [2376] = "Docker API (TLS)",
  [3389] = "Remote Desktop",
  [5900] = "VNC",
  [5985] = "WinRM HTTP",
  [5986] = "WinRM HTTPS",
  [6443] = "Kubernetes API",
  [9090] = "Cockpit",
  [10250] = "Kubernetes kubelet API",
}

portrule = function(host, port)
  return port.state == "open"
    and port.protocol == "tcp"
    and admin_ports[port.number] ~= nil
end

action = function(host, port)
  local surface = admin_ports[port.number]
  local service = port.service or "unknown"
  local output = stdnse.output_table()
  output.status = "REVIEW"
  output.administrative_surface = surface
  output.detected_service = service
  output.recommendation =
    "Review source-address restrictions, authentication policy, and audit logging."
  return output
end
