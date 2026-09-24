local stdnse = require "stdnse"

description = [[
Reports open database and datastore ports that commonly require strict
interface binding, firewall allowlists, authentication, and encryption.
]]

author = "Managed Debian desktop automation"
license = "Same as Nmap--See https://nmap.org/book/man-legal.html"
categories = {"safe", "discovery"}

local database_ports = {
  [1433] = "Microsoft SQL Server",
  [1521] = "Oracle Database",
  [2181] = "Apache ZooKeeper",
  [2379] = "etcd client",
  [2380] = "etcd peer",
  [2483] = "Oracle Database",
  [2484] = "Oracle Database TLS",
  [3306] = "MySQL/MariaDB",
  [5432] = "PostgreSQL",
  [5984] = "Apache CouchDB",
  [6379] = "Redis",
  [7199] = "Cassandra JMX",
  [7474] = "Neo4j HTTP",
  [7687] = "Neo4j Bolt",
  [8086] = "InfluxDB",
  [9042] = "Cassandra",
  [9200] = "Elasticsearch HTTP",
  [9300] = "Elasticsearch transport",
  [11211] = "Memcached",
  [27017] = "MongoDB",
  [27018] = "MongoDB shard",
  [27019] = "MongoDB config server",
  [28017] = "MongoDB legacy HTTP",
}

portrule = function(host, port)
  return port.state == "open"
    and port.protocol == "tcp"
    and database_ports[port.number] ~= nil
end

action = function(host, port)
  local product = database_ports[port.number]
  local service = port.service or "unknown"
  local output = stdnse.output_table()
  output.status = "REVIEW"
  output.database_surface = product
  output.detected_service = service
  output.recommendation =
    "Confirm private binding, firewall restrictions, authentication, and transport encryption."
  return output
end
