export const MAF_VERSION = "0.7.0";

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
  caller_uri?: string;
  caller_id?: string;
  caller_name?: string;
  p_asserted_identity?: string;
  privacy?: string;
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
  mode?: "bridge" | "conference";
}

export interface TransferRequest {
  command_id?: string;
  expected_version?: string;
  target: string;
  type: "blind" | "attended";
  other_call_id?: string;
}

export interface DtmfRequest {
  command_id?: string;
  expected_version?: string;
  digit: string;
  duration?: number;
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
  state: "created" | "ringing" | "answered" | "bridged" | "transferring" | "ending" | "ended" | "failed" | "canceled" | "rejected" | "timeout";
  version: string;
  from_uri?: string;
  to_uri?: string;
  application_data?: Record<string, unknown>;
  final_sip_code?: number | null;
  final_reason?: string;
  ended_by?: "" | "application" | "remote" | "timer";
  route_attempts?: RouteAttempt[];
  channels?: Channel[];
  bridges?: Bridge[];
  media?: MediaOperation[];
  created_at?: string;
  updated_at?: string;
  ended_at?: string | null;
}

export interface RouteAttempt {
  attempt_id: number;
  command_id?: string;
  target: string;
  transport: "udp" | "tcp" | "tls" | "ws" | "wss";
  mode: "proxy" | "b2bua";
  status: "attempted" | "sent" | "failed";
  sip_code?: number | null;
  error_code?: string;
  error_message?: string;
  started_at?: string;
  completed_at?: string | null;
}

export interface CallerPresentation {
  caller_uri?: string;
  caller_id?: string;
  caller_name?: string;
  p_asserted_identity?: string;
  privacy?: string;
}

export interface CapacityPolicy {
  policy_id?: number;
  name: string;
  selector_type?: "global" | "tenant" | "source_ip" | "target";
  selector_value?: string;
  max_active_calls?: number;
  max_cps?: number;
  reject_sip_code?: number;
  enabled?: boolean;
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
    presentation?: CallerPresentation,
  ): Promise<CommandReceipt> {
    const body: Record<string, unknown> = { from, to, ...(presentation ?? {}) };
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

  async transferCall(
    callId: string,
    target: string,
    transferType: "blind" | "attended" = "blind",
    otherCallId?: string,
    idempotencyKey?: string,
  ): Promise<CommandReceipt> {
    const body: Record<string, unknown> = { target, type: transferType };
    if (otherCallId !== undefined) body.other_call_id = otherCallId;
    return this.command(
      `${API}/calls/${encPath(callId)}/transfer`,
      body,
      idempotencyKey,
    );
  }

  async holdCall(
    callId: string,
    idempotencyKey?: string,
  ): Promise<CommandReceipt> {
    return this.command(
      `${API}/calls/${encPath(callId)}/hold`,
      {},
      idempotencyKey,
    );
  }

  async unholdCall(
    callId: string,
    idempotencyKey?: string,
  ): Promise<CommandReceipt> {
    return this.command(
      `${API}/calls/${encPath(callId)}/unhold`,
      {},
      idempotencyKey,
    );
  }

  async sendDtmf(
    callId: string,
    digit: string,
    duration = 250,
    idempotencyKey?: string,
  ): Promise<CommandReceipt> {
    return this.command(
      `${API}/calls/${encPath(callId)}/dtmf`,
      { digit, duration },
      idempotencyKey,
    );
  }

  async rtpControl(
    callId: string,
    action: "offer" | "answer" | "delete" | "query",
    opts?: { sdp?: string; from_tag?: string; to_tag?: string; flags?: string },
    idempotencyKey?: string,
  ): Promise<CommandReceipt> {
    const body: Record<string, string> = { action };
    if (opts?.sdp !== undefined) body.sdp = opts.sdp;
    if (opts?.from_tag !== undefined) body.from_tag = opts.from_tag;
    if (opts?.to_tag !== undefined) body.to_tag = opts.to_tag;
    if (opts?.flags !== undefined) body.flags = opts.flags;
    return this.command(
      `${API}/calls/${encPath(callId)}/rtp`,
      body,
      idempotencyKey,
    );
  }

  async routeCall(
    callId: string,
    target: string,
    transport?: string,
    idempotencyKey?: string,
    opts?: CallerPresentation & { mode?: "proxy" | "b2bua" },
  ): Promise<CommandReceipt> {
    const body: Record<string, string> = { target, ...(opts ?? {}) };
    if (transport !== undefined) body.transport = transport;
    return this.command(
      `${API}/calls/${encPath(callId)}/route`,
      body,
      idempotencyKey,
    );
  }

  async publishEvent(
    eventType: string,
    callId?: string,
    payload?: Record<string, unknown> | string,
  ): Promise<Record<string, unknown>> {
    const body: Record<string, unknown> = { event_type: eventType };
    if (callId !== undefined) body.call_id = callId;
    if (payload !== undefined)
      body.payload = typeof payload === "string" ? payload : JSON.stringify(payload);
    return this.request("POST", `${API}/events`, body);
  }

  async registrations(aor?: string, limit = 100): Promise<Record<string, unknown>> {
    const query: Record<string, string | number> = { limit: Math.min(Math.max(limit, 1), 100) };
    if (aor !== undefined) query.aor = aor;
    return this.request("GET", `${API}/registrations`, undefined, query);
  }

  async cdr(callId?: string, limit = 50): Promise<Record<string, unknown>> {
    const query: Record<string, string | number> = { limit: Math.min(Math.max(limit, 1), 100) };
    if (callId !== undefined) query.call_id = callId;
    return this.request("GET", `${API}/cdr`, undefined, query);
  }

  async bans(): Promise<Record<string, unknown>> {
    return this.request("GET", `${API}/security/bans`);
  }

  async banIP(sourceIP: string, opts?: { reason?: string; permanent?: boolean; duration_min?: number }): Promise<Record<string, unknown>> {
    return this.request("POST", `${API}/security/bans`, {
      source_ip: sourceIP,
      reason: opts?.reason ?? "",
      permanent: opts?.permanent ? "true" : "false",
      duration_min: opts?.duration_min ?? 60,
    });
  }

  async unbanIP(sourceIP: string): Promise<Record<string, unknown>> {
    return this.request("DELETE", `${API}/security/bans/${encPath(sourceIP)}`);
  }

  async sipInspect(callId: string): Promise<Record<string, unknown>> {
    return this.request("GET", `${API}/calls/${encPath(callId)}/sip`);
  }

  async presence(aor?: string, limit = 100): Promise<Record<string, unknown>> {
    const q: Record<string, string | number> = { limit: Math.min(Math.max(limit, 1), 500) };
    if (aor !== undefined) q.aor = aor;
    return this.request("GET", `${API}/presence`, undefined, q);
  }
  async presenceUser(aor: string): Promise<Record<string, unknown>> {
    return this.request("GET", `${API}/presence/${encPath(aor)}`);
  }
  async routingRules(): Promise<Record<string, unknown>> {
    return this.request("GET", `${API}/routing/rules`);
  }
  async createRoutingRule(body: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.request("POST", `${API}/routing/rules`, body);
  }
  async deleteRoutingRule(ruleId: number | string): Promise<Record<string, unknown>> {
    return this.request("DELETE", `${API}/routing/rules/${ruleId}`);
  }
  async gateways(): Promise<Record<string, unknown>> {
    return this.request("GET", `${API}/gateways`);
  }
  async createGateway(name: string, address: string, port = 5060, transport = "UDP"): Promise<Record<string, unknown>> {
    return this.request("POST", `${API}/gateways`, { name, address, port, transport });
  }
  async dids(): Promise<Record<string, unknown>> {
    return this.request("GET", `${API}/dids`);
  }
  async createDID(number: string, destinationUser: string, description = ""): Promise<Record<string, unknown>> {
    return this.request("POST", `${API}/dids`, { number, destination_user: destinationUser, description });
  }
  async dispatchSets(): Promise<Record<string, unknown>> {
    return this.request("GET", `${API}/dispatch-sets`);
  }
  async createDispatchSet(name: string, algorithm = "round-robin"): Promise<Record<string, unknown>> {
    return this.request("POST", `${API}/dispatch-sets`, { name, algorithm });
  }
  async cluster(): Promise<Record<string, unknown>> {
    return this.request("GET", `${API}/cluster`);
  }
  async config(): Promise<Record<string, unknown>> {
    return this.request("GET", `${API}/config`);
  }
  async setConfig(key: string, value: string, description = ""): Promise<Record<string, unknown>> {
    return this.request("POST", `${API}/config`, { key, value, description });
  }
  async chargeAuthorize(callId: string): Promise<Record<string, unknown>> {
    return this.request("POST", `${API}/calls/${encPath(callId)}/charge`);
  }
  async chargeDeny(callId: string): Promise<Record<string, unknown>> {
    return this.request("POST", `${API}/calls/${encPath(callId)}/charge-deny`);
  }
  async capacityPolicies(): Promise<Record<string, unknown>> {
    return this.request("GET", `${API}/capacity/policies`);
  }
  async upsertCapacityPolicy(policy: CapacityPolicy): Promise<Record<string, unknown>> {
    return this.request("POST", `${API}/capacity/policies`, policy);
  }

  async deleteGateway(gatewayId: number): Promise<Record<string, unknown>> {
    return this.request("DELETE", `${API}/gateways/${gatewayId}`);
  }
  async deleteDid(didId: number): Promise<Record<string, unknown>> {
    return this.request("DELETE", `${API}/dids/${didId}`);
  }
  async deleteDispatchSet(setId: number): Promise<Record<string, unknown>> {
    return this.request("DELETE", `${API}/dispatch-sets/${setId}`);
  }
  async deleteConfig(key: string): Promise<Record<string, unknown>> {
    return this.request("DELETE", `${API}/config/${encPath(key)}`);
  }
  async dialplans(): Promise<Record<string, unknown>> {
    return this.request("GET", `${API}/dialplans`);
  }
  async createDialplan(body: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.request("POST", `${API}/dialplans`, body);
  }
  async deleteDialplan(dialplanId: number): Promise<Record<string, unknown>> {
    return this.request("DELETE", `${API}/dialplans/${dialplanId}`);
  }
  async ipAuth(): Promise<Record<string, unknown>> {
    return this.request("GET", `${API}/ip-auth`);
  }
  async createIpAuth(ip: string, description = ""): Promise<Record<string, unknown>> {
    return this.request("POST", `${API}/ip-auth`, { ip, description });
  }
  async deleteIpAuth(ipAuthId: number): Promise<Record<string, unknown>> {
    return this.request("DELETE", `${API}/ip-auth/${ipAuthId}`);
  }
  async accessControl(): Promise<Record<string, unknown>> {
    return this.request("GET", `${API}/access-control`);
  }
  async createAccessControl(rule: string, source: string, description = ""): Promise<Record<string, unknown>> {
    return this.request("POST", `${API}/access-control`, { rule, source, description });
  }
  async deleteAccessControl(aclId: number): Promise<Record<string, unknown>> {
    return this.request("DELETE", `${API}/access-control/${aclId}`);
  }
  async headerRules(): Promise<Record<string, unknown>> {
    return this.request("GET", `${API}/header-rules`);
  }
  async createHeaderRule(body: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.request("POST", `${API}/header-rules`, body);
  }
  async deleteHeaderRule(ruleId: number): Promise<Record<string, unknown>> {
    return this.request("DELETE", `${API}/header-rules/${ruleId}`);
  }
  async billingEvents(): Promise<Record<string, unknown>> {
    return this.request("GET", `${API}/billing/events`);
  }
  async billingAck(eventIds: string[]): Promise<Record<string, unknown>> {
    return this.request("POST", `${API}/billing/events/ack`, { event_ids: eventIds });
  }
  async securityEvents(): Promise<Record<string, unknown>> {
    return this.request("GET", `${API}/security/events`);
  }
  async aniGroups(): Promise<Record<string, unknown>> {
    return this.request("GET", `${API}/ani-groups`);
  }
  async createAniGroup(name: string, numbers: string[]): Promise<Record<string, unknown>> {
    return this.request("POST", `${API}/ani-groups`, { name, numbers });
  }
  async deleteAniGroup(groupId: number): Promise<Record<string, unknown>> {
    return this.request("DELETE", `${API}/ani-groups/${groupId}`);
  }
  async activeCalls(): Promise<Record<string, unknown>> {
    return this.request("GET", `${API}/calls/active`);
  }
  async createDispatchMember(dispatchSetId: number, gatewayId: number, weight = 100, priority = 1): Promise<Record<string, unknown>> {
    return this.request("POST", `${API}/dispatch-members`, { dispatch_set_id: dispatchSetId, gateway_id: gatewayId, weight, priority });
  }
  async deleteDispatchMember(memberId: number): Promise<Record<string, unknown>> {
    return this.request("DELETE", `${API}/dispatch-members/${memberId}`);
  }
  async users(): Promise<Record<string, unknown>> {
    return this.request("GET", `${API}/users`);
  }
  async createUser(username: string, password: string): Promise<Record<string, unknown>> {
    return this.request("POST", `${API}/users`, { username, password });
  }
  async deleteUser(userId: number): Promise<Record<string, unknown>> {
    return this.request("DELETE", `${API}/users/${userId}`);
  }
  async setLogLevel(level: string): Promise<Record<string, unknown>> {
    return this.request("POST", `${API}/log-level`, { level });
  }
  async health(): Promise<Record<string, unknown>> {
    return this.request("GET", `${API}/health`);
  }
  async reload(): Promise<Record<string, unknown>> {
    return this.request("POST", `${API}/reload`);
  }
  // --- Call Flows ---

  async setCallFlow(
    callId: string,
    steps: Record<string, unknown>[],
    idempotencyKey?: string,
  ): Promise<CommandReceipt> {
    return this.command(`${API}/calls/${encPath(callId)}/flow`, { steps }, idempotencyKey);
  }

  // --- Scheduled Calls ---

  async scheduledCalls(): Promise<Record<string, unknown>> {
    return this.request("GET", `${API}/scheduled-calls`);
  }
  async scheduleCall(from: string, to: string, scheduledAt: string, applicationData?: Record<string, unknown>): Promise<Record<string, unknown>> {
    const body: Record<string, unknown> = { from, to, scheduled_at: scheduledAt };
    if (applicationData !== undefined) body.application_data = applicationData;
    return this.request("POST", `${API}/scheduled-calls`, body);
  }
  async cancelScheduledCall(scheduleId: number): Promise<Record<string, unknown>> {
    return this.request("DELETE", `${API}/scheduled-calls/${scheduleId}`);
  }

  // --- Queues ---

  async queues(): Promise<Record<string, unknown>> {
    return this.request("GET", `${API}/queues`);
  }
  async createQueue(name: string, strategy = "round-robin", maxWaitSec = 300): Promise<Record<string, unknown>> {
    return this.request("POST", `${API}/queues`, { name, strategy, max_wait_sec: maxWaitSec });
  }
  async addQueueMember(queueId: number, agentUri: string, priority = 1): Promise<Record<string, unknown>> {
    return this.request("POST", `${API}/queues/${queueId}/members`, { agent_uri: agentUri, priority });
  }
  async removeQueueMember(queueId: number, memberId: number): Promise<Record<string, unknown>> {
    return this.request("DELETE", `${API}/queues/${queueId}/members/${memberId}`);
  }

  // --- Conferences ---

  async conferences(): Promise<Record<string, unknown>> {
    return this.request("GET", `${API}/conferences`);
  }
  async createConference(name: string, pin = "", maxParticipants = 10, record = false): Promise<Record<string, unknown>> {
    return this.request("POST", `${API}/conferences`, { name, pin, max_participants: maxParticipants, record });
  }

  // --- Webhooks ---

  async webhooks(): Promise<Record<string, unknown>> {
    return this.request("GET", `${API}/webhooks`);
  }
  async createWebhook(url: string, events?: string[], secret = ""): Promise<Record<string, unknown>> {
    const body: Record<string, unknown> = { url };
    if (events !== undefined) body.events = events;
    if (secret) body.secret = secret;
    return this.request("POST", `${API}/webhooks`, body);
  }
  async deleteWebhook(webhookId: number): Promise<Record<string, unknown>> {
    return this.request("DELETE", `${API}/webhooks/${webhookId}`);
  }

  // --- Call Tags ---

  async tagCall(callId: string, tags: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.request("POST", `${API}/calls/${encPath(callId)}/tags`, { tags });
  }

  // --- Number Intelligence ---

  async numberLookup(number: string): Promise<Record<string, unknown>> {
    return this.request("GET", `${API}/number/${encPath(number)}`);
  }
  async upsertNumber(number: string, carrier = "", numberType = "", country = "", spamScore = 0): Promise<Record<string, unknown>> {
    return this.request("POST", `${API}/number`, { number, carrier, type: numberType, country, spam_score: spamScore });
  }

  // --- Routing Intelligence ---

  async routingIntelligence(): Promise<Record<string, unknown>> {
    return this.request("GET", `${API}/routing/intelligence`);
  }
  async recordRoutingOutcome(gateway: string, prefix: string, answered: boolean, durationSec = 0, pddMs = 0): Promise<Record<string, unknown>> {
    return this.request("POST", `${API}/routing/intelligence/record`, { gateway, prefix, answered, duration_sec: durationSec, pdd_ms: pddMs });
  }

  async identity(
    callId: string,
    action: string,
    identity?: string,
    attest?: string,
    idempotencyKey?: string,
  ): Promise<CommandReceipt> {
    const body: Record<string, unknown> = { action };
    if (identity !== undefined) body.identity = identity;
    if (attest !== undefined) body.attest = attest;
    return this.command(`${API}/calls/${encPath(callId)}/identity`, body, idempotencyKey);
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

  /**
   * Subscribe to events using HTTP long-poll with adaptive backoff.
   * Yields events as an async iterable. For native WebSocket, use wsUrl().
   */
  async *subscribe(opts?: {
    cursor?: number;
    eventType?: string;
    callId?: string;
    pollMs?: number;
    maxPollMs?: number;
    signal?: AbortSignal;
  }): AsyncGenerator<Record<string, unknown>> {
    let cur = opts?.cursor ?? 0;
    let interval = opts?.pollMs ?? 200;
    const maxInterval = opts?.maxPollMs ?? 2000;
    while (!opts?.signal?.aborted) {
      try {
        const query: Record<string, string | number> = { cursor: cur, limit: 100 };
        if (opts?.eventType !== undefined) query.event_type = opts.eventType;
        if (opts?.callId !== undefined) query.call_id = opts.callId;
        const page = await this.request("GET", `${API}/events`, undefined, query);
        const events = (page as Record<string, unknown>).events;
        if (Array.isArray(events) && events.length > 0) {
          interval = opts?.pollMs ?? 200;
          for (const evt of events) yield evt as Record<string, unknown>;
          const next = (page as Record<string, unknown>).next_cursor;
          const n = typeof next === "string" ? parseInt(next, 10) : typeof next === "number" ? next : cur;
          if (n > cur) cur = n;
        } else {
          interval = Math.min(interval * 2, maxInterval);
        }
      } catch {
        interval = maxInterval;
      }
      await new Promise((r) => setTimeout(r, interval));
    }
  }

  /**
   * Build the WebSocket URL for direct connection.
   *
   * Usage (browser/Deno):
   *   const ws = new WebSocket(client.wsUrl({ eventType: "call.answered" }));
   *   ws.onmessage = (e) => console.log(JSON.parse(e.data));
   *
   * Usage (Node with ws package):
   *   import WebSocket from "ws";
   *   const ws = new WebSocket(client.wsUrl(), {
   *     headers: { Authorization: `Bearer ${token}` }
   *   });
   */
  wsUrl(opts?: { cursor?: number; eventType?: string; callId?: string }): string {
    const base = this.baseUrl
      .replace(/^https:\/\//, "wss://")
      .replace(/^http:\/\//, "ws://");
    const params = new URLSearchParams();
    params.set("cursor", String(opts?.cursor ?? 0));
    if (opts?.eventType !== undefined) params.set("event_type", opts.eventType);
    if (opts?.callId !== undefined) params.set("call_id", opts.callId);
    return `${base}${API}/events/ws?${params.toString()}`;
  }
}
