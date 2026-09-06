local stdnse = require "stdnse"

description = [[
Reports open services that commonly transmit credentials or content without
transport encryption so administrators can confirm compensating controls.
]]

author = "Managed Debian desktop automation"
license = "Same as Nmap--See https://nmap.org/book/man-legal.html"
categories = {"safe", "discovery"}

local plaintext_ports = {
  [20] = {name = "FTP data", tcp = true},
  [21] = {name = "FTP control", tcp = true},
  [23] = {name = "Telnet", tcp = true},
  [25] = {name = "SMTP", tcp = true},
  [69] = {name = "TFTP", udp = true},
  [80] = {name = "HTTP", tcp = true},
  [110] = {name = "POP3", tcp = true},
  [119] = {name = "NNTP", tcp = true},
  [143] = {name = "IMAP", tcp = true},
  [389] = {name = "LDAP", tcp = true, udp = true},
  [512] = {name = "rexec", tcp = true},
  [513] = {name = "rlogin", tcp = true},
  [514] = {name = "rsh/syslog", tcp = true, udp = true},
  [873] = {name = "rsync", tcp = true},
  [1883] = {name = "MQTT", tcp = true},
  [5672] = {name = "AMQP", tcp = true},
  [8080] = {name = "Alternate HTTP", tcp = true},
}

portrule = function(host, port)
  local policy = plaintext_ports[port.number]
  return port.state == "open"
    and policy ~= nil
    and policy[port.protocol] == true
end

action = function(host, port)
  local service = plaintext_ports[port.number].name
  local output = stdnse.output_table()
  output.status = "REVIEW"
  output.plaintext_service = service
  output.port = port.number
  output.protocol = port.protocol
  output.recommendation =
    "Confirm encryption, network isolation, or an explicit documented exception."
  return output
end
