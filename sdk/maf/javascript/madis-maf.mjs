/** Small server-side fetch client for the MADIS Application Fabric (MAF). */

export class MafError extends Error {
  constructor(status, payload) {
    super(`MAF request failed with HTTP ${status}`);
    this.name = "MafError";
    this.status = status;
    this.payload = payload;
  }
}

export class MadisMaf {
  constructor(baseUrl, token, timeoutMs = 5000) {
    if (!/^https?:\/\//.test(baseUrl)) throw new TypeError("baseUrl must use HTTP or HTTPS");
    if (token.length < 16 || token.length > 512) throw new TypeError("MAF token must be 16..512 characters");
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.token = token;
    this.timeoutMs = timeoutMs;
  }

  async request(method, path, body, query, idempotencyKey) {
    const url = new URL(this.baseUrl + path);
    if (query) for (const [key, value] of Object.entries(query)) url.searchParams.set(key, String(value));
    const payload = body === undefined ? undefined : JSON.stringify(body);
    if (payload !== undefined && new TextEncoder().encode(payload).length > 65536) throw new RangeError("MAF request body exceeds 64 KiB");
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    const headers = { Authorization: `Bearer ${this.token}`, Accept: "application/json" };
    if (payload !== undefined) headers["Content-Type"] = "application/json";
    if (idempotencyKey !== undefined) headers["Idempotency-Key"] = idempotencyKey;
    try {
      const response = await fetch(url, { method, headers, body: payload, signal: controller.signal });
      const text = await response.text();
      let decoded = null;
      if (text.length > 0) {
        try { decoded = JSON.parse(text); } catch { decoded = text; }
      }
      if (!response.ok) throw new MafError(response.status, decoded);
      return decoded;
    } finally {
      clearTimeout(timer);
    }
  }

  command(path, body, idempotencyKey) {
    const key = idempotencyKey ?? globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
    return this.request("POST", path, { command_id: key, ...body }, undefined, key);
  }

  createCall(from, to, applicationData, idempotencyKey) {
    const body = { from, to };
    if (applicationData !== undefined) body.application_data = applicationData;
    return this.command("/api/v1/maf/calls", body, idempotencyKey);
  }

  callPath(callId, suffix = "") {
    return `/api/v1/maf/calls/${encodeURIComponent(callId)}${suffix}`;
  }

  getCall(callId) { return this.request("GET", this.callPath(callId)); }
  answerCall(callId, answerSdp, key) { return this.command(this.callPath(callId, "/answer"), { answer_sdp: answerSdp }, key); }
  rejectCall(callId, sipCode, reason, key) { return this.command(this.callPath(callId, "/reject"), { ...(sipCode === undefined ? {} : { sip_code: sipCode }), ...(reason === undefined ? {} : { reason }) }, key); }
  hangupCall(callId, reason, key) { return this.command(this.callPath(callId, "/hangup"), reason === undefined ? {} : { reason }, key); }
  bridgeCall(callId, channelIds, key) { return this.command(this.callPath(callId, "/bridges"), { channel_ids: channelIds }, key); }
  media(callId, operation, resource, key) { return this.command(this.callPath(callId, "/media"), { operation, ...(resource === undefined ? {} : { resource }) }, key); }
  setHeaders(callId, headers, key) { return this.command(this.callPath(callId, "/headers"), { headers }, key); }

  transferCall(callId, target, type = "blind", otherCallId, key) {
    const body = { target, type };
    if (otherCallId !== undefined) body.other_call_id = otherCallId;
    return this.command(this.callPath(callId, "/transfer"), body, key);
  }
  holdCall(callId, key) { return this.command(this.callPath(callId, "/hold"), {}, key); }
  unholdCall(callId, key) { return this.command(this.callPath(callId, "/unhold"), {}, key); }
  sendDtmf(callId, digit, duration = 250, key) { return this.command(this.callPath(callId, "/dtmf"), { digit, duration }, key); }
  rtpControl(callId, action, opts = {}, key) {
    const body = { action, ...opts };
    return this.command(this.callPath(callId, "/rtp"), body, key);
  }
  routeCall(callId, target, transport, key) {
    const body = { target };
    if (transport !== undefined) body.transport = transport;
    return this.command(this.callPath(callId, "/route"), body, key);
  }

  publishEvent(eventType, callId, payload) {
    const body = { event_type: eventType };
    if (callId !== undefined) body.call_id = callId;
    if (payload !== undefined) body.payload = typeof payload === "string" ? payload : JSON.stringify(payload);
    return this.request("POST", "/api/v1/maf/events", body);
  }

  registrations(aor, limit = 100) {
    const query = { limit: Math.min(Math.max(limit, 1), 100) };
    if (aor !== undefined) query.aor = aor;
    return this.request("GET", "/api/v1/maf/registrations", undefined, query);
  }
  cdr(callId, limit = 50) {
    const query = { limit: Math.min(Math.max(limit, 1), 100) };
    if (callId !== undefined) query.call_id = callId;
    return this.request("GET", "/api/v1/maf/cdr", undefined, query);
  }
  bans() { return this.request("GET", "/api/v1/maf/security/bans"); }
  banIP(sourceIP, reason = "", permanent = false, durationMin = 60) {
    return this.request("POST", "/api/v1/maf/security/bans", { source_ip: sourceIP, reason, permanent: permanent ? "true" : "false", duration_min: durationMin });
  }
  unbanIP(sourceIP) { return this.request("DELETE", `/api/v1/maf/security/bans/${encodeURIComponent(sourceIP)}`); }
  sipInspect(callId) { return this.request("GET", this.callPath(callId, "/sip")); }

  presence(aor, limit = 100) { const q = { limit }; if (aor) q.aor = aor; return this.request("GET", "/api/v1/maf/presence", undefined, q); }
  presenceUser(aor) { return this.request("GET", `/api/v1/maf/presence/${encodeURIComponent(aor)}`); }
  routingRules() { return this.request("GET", "/api/v1/maf/routing/rules"); }
  createRoutingRule(body) { return this.request("POST", "/api/v1/maf/routing/rules", body); }
  deleteRoutingRule(id) { return this.request("DELETE", `/api/v1/maf/routing/rules/${id}`); }
  gateways() { return this.request("GET", "/api/v1/maf/gateways"); }
  createGateway(name, address, port = 5060, transport = "UDP") { return this.request("POST", "/api/v1/maf/gateways", { name, address, port, transport }); }
  dids() { return this.request("GET", "/api/v1/maf/dids"); }
  createDID(number, destinationUser, description = "") { return this.request("POST", "/api/v1/maf/dids", { number, destination_user: destinationUser, description }); }
  dispatchSets() { return this.request("GET", "/api/v1/maf/dispatch-sets"); }
  createDispatchSet(name, algorithm = "round-robin") { return this.request("POST", "/api/v1/maf/dispatch-sets", { name, algorithm }); }
  cluster() { return this.request("GET", "/api/v1/maf/cluster"); }
  config() { return this.request("GET", "/api/v1/maf/config"); }
  setConfig(key, value, description = "") { return this.request("POST", "/api/v1/maf/config", { key, value, description }); }
  chargeAuthorize(callId) { return this.request("POST", this.callPath(callId, "/charge")); }
  chargeDeny(callId) { return this.request("POST", this.callPath(callId, "/charge-deny")); }

  events(cursor = 0, eventType, limit = 100) {
    const query = { cursor: Math.max(cursor, 0), limit: Math.min(Math.max(limit, 1), 100) };
    if (eventType !== undefined) query.event_type = eventType;
    return this.request("GET", "/api/v1/maf/events", undefined, query);
  }

  /** Subscribe to events via HTTP long-poll. Returns an async iterator. */
  async *subscribe({ cursor = 0, eventType, callId, pollMs = 200, maxPollMs = 2000, signal } = {}) {
    let cur = cursor;
    let interval = pollMs;
    while (!signal?.aborted) {
      try {
        const q = { cursor: cur, limit: 100 };
        if (eventType) q.event_type = eventType;
        if (callId) q.call_id = callId;
        const page = await this.request("GET", "/api/v1/maf/events", undefined, q);
        const events = page?.events || [];
        if (events.length > 0) {
          interval = pollMs;
          for (const evt of events) yield evt;
          const next = parseInt(page.next_cursor, 10);
          if (next > cur) cur = next;
        } else {
          interval = Math.min(interval * 2, maxPollMs);
        }
      } catch { interval = maxPollMs; }
      await new Promise(r => setTimeout(r, interval));
    }
  }

  /** Build the WebSocket URL for direct connection. */
  wsUrl({ cursor = 0, eventType, callId } = {}) {
    const base = this.baseUrl.replace(/^https:\/\//, "wss://").replace(/^http:\/\//, "ws://");
    const params = new URLSearchParams({ cursor: String(cursor) });
    if (eventType) params.set("event_type", eventType);
    if (callId) params.set("call_id", callId);
    return `${base}/api/v1/maf/events/ws?${params}`;
  }
}
