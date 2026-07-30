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

  events(cursor = 0, eventType, limit = 100) {
    const query = { cursor: Math.max(cursor, 0), limit: Math.min(Math.max(limit, 1), 100) };
    if (eventType !== undefined) query.event_type = eventType;
    return this.request("GET", "/api/v1/maf/events", undefined, query);
  }
}
