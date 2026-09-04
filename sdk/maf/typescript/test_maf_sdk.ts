import { MadisMaf, MAF_VERSION } from "./madis-maf.ts";
import type {
  Event,
  CallInvitePayload,
  CallDtmfPayload,
  CallAnsweredPayload,
  CallRoutedPayload,
} from "./madis-maf.ts";


async function testTypeScriptSdk() {
  const requests: Array<{ url: string; method: string; headers: Record<string, string>; body?: string }> = [];

  // Mock fetch
  globalThis.fetch = (async (url: string | URL, init?: RequestInit) => {
    const urlStr = url.toString();
    const method = init?.method ?? "GET";
    const headers = (init?.headers ?? {}) as Record<string, string>;
    const body = init?.body ? String(init.body) : undefined;
    requests.push({ url: urlStr, method, headers, body });

    return {
      ok: true,
      status: method === "POST" ? 202 : 200,
      text: async () => JSON.stringify({
        schema: "madis.maf.command-receipt.v1",
        status: "accepted",
        resource_id: "call-12345678",
        trace_id: "trace-test-1",
        events: [
          {
            schema: "madis.maf.event.v1",
            event_id: "evt-1",
            event_type: "call.dtmf",
            event_version: 1,
            call_id: "call-12345678",
            sequence: 1,
            occurred_at: new Date().toISOString(),
            payload: { digit: "5", duration: 250, direction: "inbound" } as CallDtmfPayload,
          },
        ],
        next_cursor: "2",
        truncated: false,
      }),
    } as unknown as Response;
  }) as typeof fetch;

  const client = new MadisMaf("https://proxy.example.net/admin", "0123456789abcdef");

  // Verify MAF_VERSION
  if (MAF_VERSION !== "0.7.0") throw new Error("MAF_VERSION mismatch");

  // Call control operations
  await client.createCall("sip:alice@example.net", "sip:bob@example.net", { app: "crm" }, "create-1", { caller_id: "+15550001" });
  await client.getCall("call-12345678");
  await client.answerCall("call-12345678", "v=0\r\nm=audio 4000 RTP/AVP 0\r\n", "ans-1");
  await client.rejectCall("call-12345678", 486, "Busy Here", "rej-1");
  await client.hangupCall("call-12345678", "Normal Clearing", "hang-1");
  await client.bridgeCall("call-12345678", ["chan-1", "chan-2"], "bridge-1");
  await client.media("call-12345678", "play", "prompt.wav", "media-1");
  await client.setHeaders("call-12345678", [{ action: "add", name: "X-Trace", value: "test" }], "hdr-1");
  await client.transferCall("call-12345678", "sip:carol@example.net", "blind", undefined, "xfer-1");
  await client.holdCall("call-12345678", "hold-1");
  await client.unholdCall("call-12345678", "unhold-1");
  await client.sendDtmf("call-12345678", "9", 200, "dtmf-1");
  await client.rtpControl("call-12345678", "offer", { sdp: "v=0\r\n" }, "rtp-1");
  await client.routeCall("call-12345678", "sip:agent@10.0.0.1:5060", "udp", "route-1", { mode: "proxy", caller_id: "+15559999" });
  await client.identity("call-12345678", "sign", undefined, "A", "id-1");

  // Advanced features
  await client.scheduledCalls();
  await client.scheduleCall("sip:alice@example.net", "sip:bob@example.net", "2026-09-05T12:00:00Z");
  await client.cancelScheduledCall(1);
  await client.queues();
  await client.createQueue("support", "round-robin", 180);
  await client.addQueueMember(1, "sip:agent@example.net", 1);
  await client.removeQueueMember(1, 10);
  await client.conferences();
  await client.createConference("room-1", "1234", 10, true);
  await client.webhooks();
  await client.createWebhook("https://app.example.net/webhook", ["call.answered", "call.dtmf"]);
  await client.deleteWebhook(1);
  await client.tagCall("call-12345678", { department: "sales" });
  await client.numberLookup("+15551234");
  await client.upsertNumber("+15551234", "Verizon", "mobile", "US", 0);
  await client.routingIntelligence();
  await client.recordRoutingOutcome("gw-1", "+1", true, 60, 450);

  // Typed events
  const page = await client.events<CallDtmfPayload>(0, "call.dtmf");
  if (page.events.length > 0) {
    const evt: Event<CallDtmfPayload> = page.events[0];
    if (evt.payload.digit !== "5") throw new Error("Typed event payload failed");
  }

  // WS url
  const ws = client.wsUrl({ eventType: "call.dtmf", callId: "call-12345678" });
  if (!ws.startsWith("wss://proxy.example.net/admin/api/v1/maf/events/ws")) {
    throw new Error("Invalid wsUrl: " + ws);
  }

  // Check headers on first request
  const firstReq = requests[0];
  if (firstReq.headers["X-MAF-Version"] !== "0.7.0") throw new Error("Missing X-MAF-Version header");
  if (firstReq.headers["Authorization"] !== "Bearer 0123456789abcdef") throw new Error("Missing Authorization header");
  if (firstReq.headers["Idempotency-Key"] !== "create-1") throw new Error("Missing Idempotency-Key");

  console.log(`TypeScript MAF SDK test passed (${requests.length} requests validated).`);
}

testTypeScriptSdk().catch((err) => {
  console.error(err);
  throw err;
});
