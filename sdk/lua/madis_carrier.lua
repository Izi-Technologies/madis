-- LuaSocket client. Pass decoded/encoded JSON through the caller's JSON
-- library so carriers can choose cjson, dkjson, or their own schema.
local http = require("socket.http")
local ltn12 = require("ltn12")

local M = {}
function M.new(base_url, token)
  local client = { base_url = base_url:gsub("/$", ""), token = token }
  function client:request(method, path, body)
    assert(not body or #body <= 65536, "event body exceeds 64 KiB limit")
    local out = {}
    local headers = { authorization = "Bearer " .. self.token, accept = "application/json" }
    if body then headers["content-type"] = "application/json"; headers["content-length"] = #body end
    local _, code = http.request{url=self.base_url .. path, method=method, headers=headers, source=body and ltn12.source.string(body) or nil, sink=ltn12.sink.table(out)}
    assert(code and code >= 200 and code < 300, "Madis API HTTP error")
    return table.concat(out)
  end
  function client:capabilities() return self:request("GET", "/api/v1/capabilities") end
  function client:pending_events(limit) limit=math.min(math.max(limit or 100,1),100); return self:request("GET", "/api/v1/billing/events?limit=" .. limit) end
  function client:publish(json) return self:request("POST", "/api/v1/billing/events", json) end
  function client:ack(event_id) return self:request("POST", "/api/v1/billing/events/ack?event_id=" .. event_id) end
  function client:control_status() return self:request("GET", "/api/v1/control/status") end
  function client:routing_rules(limit) limit=math.min(math.max(limit or 100,1),100); return self:request("GET", "/api/v1/control/routing-rules?limit=" .. limit) end
  function client:create_routing_rule(json) return self:request("POST", "/api/v1/control/routing-rules", json) end
  function client:set_routing_rule_enabled(rule_id, enabled)
    return self:request("POST", "/api/v1/control/routing-rules/" .. tostring(rule_id) .. "/" .. (enabled and "enable" or "disable"))
  end
  return client
end
return M
