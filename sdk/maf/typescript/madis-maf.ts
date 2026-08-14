export const MAF_VERSION = "0.5.0";

const MAX_BODY = 65_536;
const API = "/api/v1/maf";

// --- Interfaces ---

export interface CreateCallRequest {
  command_id?: string;
  expected_version?: string;
  reason?: string;
  tenant_id?: string;
  from: string;
  to: string;
  application_data?: Record<string, unknown>;
}

export interface AnswerRequest {
  command_id?: string;
  expected_version?: string;
  answer_sdp: string;
}

export interface RejectCallRequest {
  command_id?: string;
  expected_version?: string;
  reason?: string;
  sip_code?: number;
}

export interface BridgeRequest {
  command_id?: string;
  expected_version?: string;
  reason?: string;
  channel_ids: string[];
}

export interface MediaRequest {
  command_id?: string;
  expected_version?: string;
  reason?: string;
  operation: "play" | "record" | "stop" | "pause" | "resume";
  resource?: string;
}

export interface HeaderPolicy {
  method?: string;
  direction?: "inbound" | "outbound" | "both";
  action: "add" | "set" | "remove" | "rename" | "copy" | "move";
  name: string;
  value?: string;
  target?: string;
}

export interface HeaderPolicyRequest {
  command_id?: string;
  expected_version?: string;
  reason?: string;
  headers: HeaderPolicy[];
}

export interface CommandReceipt {
  schema: "madis.maf.command-receipt.v1";
  command_id: string;
  status: "accepted" | "completed" | "failed";
  resource_id?: string;
  trace_id: string;
  error_code?: string;
  error_message?: string;
}

export interface Channel {
  channel_id: string;
  state: "created" | "ringing" | "answered" | "held" | "ended";
  direction?: "inbound" | "outbound";
  endpoint?: string;
}

export interface Bridge {
  bridge_id: string;
  channel_ids: string[];
  state: "active" | "ended" | "failed";
  created_at?: string;
  updated_at?: string;
}

export interface MediaOperation {
  media_id: string;
  operation: "play" | "record" | "stop" | "pause" | "resume";
  resource?: string;
  state: "accepted" | "processing" | "completed" | "failed";
  error_code?: string;
  error_message?: string;
}

export interface Call {
  schema: "madis.maf.call.v1";
  call_id: string;
  tenant_id?: string;
  state: "created" | "ringing" | "answered" | "bridged" | "ending" | "ended" | "failed";
  version: string;
  channels?: Channel[];
  bridges?: Bridge[];
  media?: MediaOperation[];
  created_at?: string;
  updated_at?: string;
}

export interface Event {
  schema: "madis.maf.event.v1";
  event_id: string;
  event_type: string;
  event_version: number;
  tenant_id?: string;
  call_id?: string;
  channel_id?: string;
  sequence: number;
  occurred_at: string;
  trace_id?: string;
  payload: Record<string, unknown>;
}

export interface EventPage {
  schema: "madis.maf.event-page.v1";
  events: Event[];
  next_cursor: string;
  truncated: boolean;
}

// --- Error ---

export class MafError extends Error {
  constructor(
    public readonly status: number,
    public readonly payload: unknown,
  ) {
    super(`MAF request failed with HTTP ${status}: ${JSON.stringify(payload)}`);
    this.name = "MafError";
  }
}

// --- Client ---

function genKey(): string {
  const buf = new Uint8Array(16);
  crypto.getRandomValues(buf);
  return Array.from(buf, (b) => b.toString(16).padStart(2, "0")).join("");
}

function encPath(segment: string): string {
  return encodeURIComponent(segment);
}

export class MadisMaf {
  private readonly baseUrl: string;
  private readonly token: string;
  private readonly timeout: number;

  constructor(baseUrl: string, token: string, timeout = 5000) {
    if (!/^https?:\/\//.test(baseUrl)) {
      throw new Error("base_url must use HTTP or HTTPS");
    }
    if (token.length < 16 || token.length > 512) {
      throw new Error("MAF token must be 16..512 characters");
    }
    this.baseUrl = baseUrl.replace(/\/+$/, "");
    this.token = token;
    this.timeout = timeout;
  }

  private async request<T = unknown>(
    method: string,
    path: string,
    body?: unknown,
    query?: Record<string, string | number>,
    idempotencyKey?: string,
  ): Promise<T> {
    let url = this.baseUrl + path;
    if (query) {
      const params = new URLSearchParams();
      for (const [k, v] of Object.entries(query)) params.set(k, String(v));
      url += "?" + params.toString();
    }

    let payload: string | undefined;
    if (body !== undefined) {
      payload = JSON.stringify(body);
      if (new TextEncoder().encode(payload).byteLength > MAX_BODY) {
        throw new Error("MAF request body exceeds 64 KiB");
      }
    }

    const headers: Record<string, string> = {
      Authorization: `Bearer ${this.token}`,
      Accept: "application/json",
    };
    if (payload !== undefined) headers["Content-Type"] = "application/json";
    if (idempotencyKey) headers["Idempotency-Key"] = idempotencyKey;

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeout);

    let res: Response;
    try {
      res = await fetch(url, {
        method,
        headers,
        body: payload,
        signal: controller.signal,
      });
    } catch (err) {
      throw new MafError(0, String(err));
    } finally {
      clearTimeout(timer);
    }

    const raw = await res.text();
    let decoded: unknown = null;
    if (raw) {
      try {
        decoded = JSON.parse(raw);
      } catch {
        decoded = raw;
      }
    }

    if (res.status < 200 || res.status >= 300) {
      throw new MafError(res.status, decoded);
    }
    return decoded as T;
  }

  private async command<T = CommandReceipt>(
    path: string,
    body: Record<string, unknown>,
    idempotencyKey?: string,
  ): Promise<T> {
    const key = idempotencyKey || genKey();
    body = { ...body };
    if (!body.command_id) body.command_id = key;
    return this.request<T>("POST", path, body, undefined, key);
  }

  async createCall(
    from: string,
    to: string,
    applicationData?: Record<string, unknown>,
    idempotencyKey?: string,
  ): Promise<CommandReceipt> {
    const body: Record<string, unknown> = { from, to };
    if (applicationData !== undefined) body.application_data = applicationData;
    return this.command(`${API}/calls`, body, idempotencyKey);
  }

  async getCall(callId: string): Promise<Call> {
    return this.request("GET", `${API}/calls/${encPath(callId)}`);
  }

  async answerCall(
    callId: string,
    answerSdp: string,
    idempotencyKey?: string,
  ): Promise<CommandReceipt> {
    return this.command(
      `${API}/calls/${encPath(callId)}/answer`,
      { answer_sdp: answerSdp },
      idempotencyKey,
    );
  }

  async rejectCall(
    callId: string,
    sipCode?: number,
    reason?: string,
    idempotencyKey?: string,
  ): Promise<CommandReceipt> {
    const body: Record<string, unknown> = {};
    if (sipCode !== undefined) body.sip_code = sipCode;
    if (reason !== undefined) body.reason = reason;
    return this.command(
      `${API}/calls/${encPath(callId)}/reject`,
      body,
      idempotencyKey,
    );
  }

  async hangupCall(
    callId: string,
    reason?: string,
    idempotencyKey?: string,
  ): Promise<CommandReceipt> {
    const body: Record<string, unknown> = {};
    if (reason !== undefined) body.reason = reason;
    return this.command(
      `${API}/calls/${encPath(callId)}/hangup`,
      body,
      idempotencyKey,
    );
  }

  async bridgeCall(
    callId: string,
    channelIds: string[],
    idempotencyKey?: string,
  ): Promise<CommandReceipt> {
    return this.command(
      `${API}/calls/${encPath(callId)}/bridges`,
      { channel_ids: channelIds },
      idempotencyKey,
    );
  }

  async media(
    callId: string,
    operation: string,
    resource?: string,
    idempotencyKey?: string,
  ): Promise<CommandReceipt> {
    const body: Record<string, unknown> = { operation };
    if (resource !== undefined) body.resource = resource;
    return this.command(
      `${API}/calls/${encPath(callId)}/media`,
      body,
      idempotencyKey,
    );
  }

  async setHeaders(
    callId: string,
    headers: HeaderPolicy[],
    idempotencyKey?: string,
  ): Promise<CommandReceipt> {
    return this.command(
      `${API}/calls/${encPath(callId)}/headers`,
      { headers },
      idempotencyKey,
    );
  }

  async events(
    cursor = 0,
    eventType?: string,
    limit = 100,
  ): Promise<EventPage> {
    const query: Record<string, string | number> = {
      cursor: Math.max(cursor, 0),
      limit: Math.min(Math.max(limit, 1), 100),
    };
    if (eventType !== undefined) query.event_type = eventType;
    return this.request("GET", `${API}/events`, undefined, query);
  }
}
