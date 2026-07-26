export class MadisCarrier {
  static controlResources = new Set([
    "gateways", "routes", "dispatch-sets", "dispatch-members", "dids",
    "header-rules", "access-control", "security-bans", "ani-groups",
    "ani-ranges", "registrations", "registration-bindings", "cluster-nodes",
    "security-events",
  ]);

  constructor(baseUrl, token, timeoutMs = 2000) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.token = token;
    this.timeoutMs = timeoutMs;
  }

  async request(method, path, body) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    const payload = body === undefined ? undefined : JSON.stringify(body);
    if (payload !== undefined && new TextEncoder().encode(payload).length > 65536) throw new Error("event body exceeds Madis 64 KiB limit");
    try {
      const response = await fetch(this.baseUrl + path, {
        method,
        signal: controller.signal,
        headers: { Authorization: `Bearer ${this.token}`, Accept: "application/json", ...(body ? {"Content-Type": "application/json"} : {}) },
        body: payload,
      });
      if (!response.ok) throw new Error(`Madis API ${response.status}`);
      return await response.json();
    } finally { clearTimeout(timer); }
  }

  capabilities() { return this.request("GET", "/api/v1/capabilities"); }
  pendingEvents(limit = 100) { return this.request("GET", `/api/v1/billing/events?limit=${Math.min(Math.max(limit, 1), 100)}`); }
  publish(event) { return this.request("POST", "/api/v1/billing/events", event); }
  ack(eventId) { return this.request("POST", `/api/v1/billing/events/ack?event_id=${encodeURIComponent(eventId)}`); }
  cdr(limit = 100, callId = "") {
    const query = new URLSearchParams({ limit: String(Math.min(Math.max(limit, 1), 100)) });
    if (callId) query.set("call_id", callId);
    return this.request("GET", `/api/v1/billing/cdr?${query}`);
  }
  controlStatus() { return this.request("GET", "/api/v1/control/status"); }
  routingRules(limit = 100) { return this.request("GET", `/api/v1/control/routing-rules?limit=${Math.min(Math.max(limit, 1), 100)}`); }
  createRoutingRule(rule) { return this.request("POST", "/api/v1/control/routing-rules", rule); }
  setRoutingRuleEnabled(ruleId, enabled) {
    return this.request("POST", `/api/v1/control/routing-rules/${Number(ruleId)}/${enabled ? "enable" : "disable"}`);
  }
  dialplans(limit = 100) { return this.request("GET", `/api/v1/control/dialplans?limit=${Math.min(Math.max(limit, 1), 100)}`); }
  createDialplan(rule) { return this.request("POST", "/api/v1/control/dialplans", rule); }
  setDialplanEnabled(ruleId, enabled) {
    return this.request("POST", `/api/v1/control/dialplans/${Number(ruleId)}/${enabled ? "enable" : "disable"}`);
  }
  updateDialplan(ruleId, rule) { return this.request("PUT", `/api/v1/control/dialplans/${Number(ruleId)}`, rule); }
  deleteDialplan(ruleId) { return this.request("DELETE", `/api/v1/control/dialplans/${Number(ruleId)}`); }

  resourcePath(resource) {
    if (!MadisCarrier.controlResources.has(resource)) throw new Error("resource is not in the Madis control allowlist");
    return `/api/v1/control/resources/${resource}`;
  }
  controlResources(resource, limit = 100) {
    const n = Math.min(Math.max(limit, 1), 100);
    return this.request("GET", `${this.resourcePath(resource)}?limit=${n}`);
  }
  createControlResource(resource, document) { return this.request("POST", this.resourcePath(resource), document); }
  updateControlResource(resource, resourceId, document) {
    return this.request("PUT", `${this.resourcePath(resource)}/${Number(resourceId)}`, document);
  }
  deleteControlResource(resource, resourceId, expectedRevision = "") {
    const query = expectedRevision ? `?expected_revision=${encodeURIComponent(expectedRevision)}` : "";
    return this.request("DELETE", `${this.resourcePath(resource)}/${Number(resourceId)}${query}`);
  }
  setControlResourceEnabled(resource, resourceId, enabled) {
    return this.request("POST", `${this.resourcePath(resource)}/${Number(resourceId)}/${enabled ? "enable" : "disable"}`);
  }
  validateRoutingRule(rule) { return this.request("POST", "/api/v1/control/validate/routing-rule", rule); }
  validateDialplan(rule) { return this.request("POST", "/api/v1/control/validate/dialplan", rule); }
}
