local stdnse = require "stdnse"

description = [[
Compares each open TCP or UDP port with protocol-specific managed approved
service lists. Port specifications accept colon-separated ports and bounded
ranges such as 22:80:8000-8010.
]]

author = "Managed Debian desktop automation"
license = "Same as Nmap--See https://nmap.org/book/man-legal.html"
categories = {"safe", "discovery"}

local approved_cache
local approved_errors

local function parse_port_spec(configured, protocol, approved, errors)
  if type(configured) ~= "string" or configured == "" then
    errors[#errors + 1] = string.format(
      "Missing managed_approved_services.%s policy",
      protocol
    )
    return
  end
  if #configured > 16384 then
    errors[#errors + 1] = string.format(
      "%s policy exceeds 16384 bytes",
      protocol
    )
    return
  end

  local token_count = 0
  for value in string.gmatch(configured, "[^:]+") do
    token_count = token_count + 1
    if token_count > 512 then
      errors[#errors + 1] = string.format(
        "%s policy exceeds 512 entries",
        protocol
      )
      return
    end

    local range_start, range_end = string.match(value, "^(%d+)%-(%d+)$")
    if range_start and range_end then
      local first_port = tonumber(range_start)
      local last_port = tonumber(range_end)
      if first_port
        and last_port
        and first_port >= 1
        and last_port <= 65535
        and first_port <= last_port
        and last_port - first_port <= 1024
      then
        for port_number = first_port, last_port do
          approved[protocol][port_number] = true
        end
      else
        errors[#errors + 1] = string.format(
          "Invalid %s port range: %s",
          protocol,
          value
        )
      end
    else
      local port_number = tonumber(value)
      if port_number and port_number >= 1 and port_number <= 65535 then
        approved[protocol][port_number] = true
      else
        errors[#errors + 1] = string.format(
          "Invalid %s port: %s",
          protocol,
          value
        )
      end
    end
  end
end

local function approved_ports()
  if approved_cache then
    return approved_cache, approved_errors
  end

  local approved = {
    tcp = {},
    udp = {},
  }
  local errors = {}
  local legacy = stdnse.get_script_args("managed_approved_services.allow")

  if legacy and legacy ~= "" then
    parse_port_spec(legacy, "tcp", approved, errors)
    parse_port_spec(legacy, "udp", approved, errors)
  else
    parse_port_spec(
      stdnse.get_script_args("managed_approved_services.tcp"),
      "tcp",
      approved,
      errors
    )
    parse_port_spec(
      stdnse.get_script_args("managed_approved_services.udp"),
      "udp",
      approved,
      errors
    )
  end

  approved_cache = approved
  approved_errors = errors
  return approved_cache, approved_errors
end

portrule = function(host, port)
  return port.state == "open"
    and (port.protocol == "tcp" or port.protocol == "udp")
end

action = function(host, port)
  local approved, errors = approved_ports()
  local output = stdnse.output_table()
  if #errors > 0 then
    output.status = "ERROR"
    output.errors = errors
    return output
  end

  local service = port.service or "unknown"
  local protocol_policy = approved[port.protocol] or {}
  output.status = protocol_policy[port.number] and "APPROVED" or "REVIEW"
  output.port = port.number
  output.protocol = port.protocol
  output.detected_service = service
  return output
end
