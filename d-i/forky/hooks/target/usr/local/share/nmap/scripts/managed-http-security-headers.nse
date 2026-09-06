local http = require "http"
local shortport = require "shortport"
local stdnse = require "stdnse"

description = [[
Fetches the HTTP root resource and reports whether common browser security
headers are present. The script does not authenticate or submit data.
]]

author = "Managed Debian desktop automation"
license = "Same as Nmap--See https://nmap.org/book/man-legal.html"
categories = {"safe", "discovery"}

portrule = shortport.http

local function normalized_headers(response)
  local normalized = {}
  for key, value in pairs(response.header or {}) do
    if type(value) == "table" then
      normalized[string.lower(tostring(key))] = table.concat(value, ", ")
    else
      normalized[string.lower(tostring(key))] = tostring(value)
    end
  end
  return normalized
end

local function header_present(headers, name)
  return headers[name] ~= nil and headers[name] ~= ""
end

local function header_contains(headers, name, needle)
  local value = string.lower(headers[name] or "")
  return string.find(value, needle, 1, true) ~= nil
end

action = function(host, port)
  local response = http.get(host, port, "/", {
    redirect_ok = false,
    no_cache = true,
  })
  if not response then
    return nil
  end

  local headers = normalized_headers(response)
  local version = port.version or {}
  local service = string.lower(port.service or "")
  local tunnel = string.lower(version.service_tunnel or "")
  local tls_expected = tunnel == "ssl"
    or service == "https"
    or string.find(service, "ssl", 1, true) ~= nil
    or string.find(service, "tls", 1, true) ~= nil
    or port.number == 443
    or port.number == 8443
  local output = stdnse.output_table()
  output.http_status = tostring(response.status or "unknown")
  output.findings = {}

  if header_present(headers, "content-security-policy") then
    output.findings[#output.findings + 1] = string.format(
      "PRESENT Content-Security-Policy: %s",
      headers["content-security-policy"]
    )
  else
    output.findings[#output.findings + 1] =
      "REVIEW missing Content-Security-Policy"
  end

  if header_contains(headers, "x-content-type-options", "nosniff") then
    output.findings[#output.findings + 1] =
      "PRESENT X-Content-Type-Options: nosniff"
  else
    output.findings[#output.findings + 1] =
      "REVIEW X-Content-Type-Options should include nosniff"
  end

  if header_present(headers, "x-frame-options")
    or header_contains(headers, "content-security-policy", "frame-ancestors")
  then
    output.findings[#output.findings + 1] = "PRESENT framing policy"
  else
    output.findings[#output.findings + 1] =
      "REVIEW missing X-Frame-Options or CSP frame-ancestors"
  end

  if tls_expected then
    if header_contains(headers, "strict-transport-security", "max-age=") then
      output.findings[#output.findings + 1] = string.format(
        "PRESENT HSTS: %s",
        headers["strict-transport-security"]
      )
    else
      output.findings[#output.findings + 1] =
        "REVIEW missing or invalid HSTS max-age"
    end
  else
    output.findings[#output.findings + 1] =
      "INFO HSTS not evaluated on a cleartext HTTP service"
  end

  if header_present(headers, "referrer-policy") then
    output.findings[#output.findings + 1] = string.format(
      "PRESENT Referrer-Policy: %s",
      headers["referrer-policy"]
    )
  else
    output.findings[#output.findings + 1] =
      "REVIEW missing Referrer-Policy"
  end

  if header_present(headers, "permissions-policy") then
    output.findings[#output.findings + 1] = string.format(
      "PRESENT Permissions-Policy: %s",
      headers["permissions-policy"]
    )
  else
    output.findings[#output.findings + 1] =
      "REVIEW missing Permissions-Policy"
  end

  return output
end
