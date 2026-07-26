export class MadisCarrier {
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
}
