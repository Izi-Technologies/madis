import assert from "node:assert/strict";
import { MadisMaf, MAF_VERSION } from "../javascript/madis-maf.mjs";

assert.equal(MAF_VERSION, "0.7.0");

const calls = [];
globalThis.fetch = async (url, options) => {
  calls.push({ url: String(url), options });
  return {
    ok: true,
    status: options.method === "POST" ? 202 : 200,
    text: async () => JSON.stringify({
      schema: "madis.maf.command-receipt.v1",
      status: "accepted",
      resource_id: "call-12345678",
      events: [
        {
          schema: "madis.maf.event.v1",
          event_id: "evt-1",
          event_type: "call.dtmf",
          event_version: 1,
          call_id: "call-12345678",
          sequence: 1,
          occurred_at: new Date().toISOString(),
          payload: { digit: "7", duration: 250, direction: "inbound" },
        },
      ],
      next_cursor: "2",
      truncated: false,
    }),
  };
};

const client = new MadisMaf("https://proxy.example.net/admin", "0123456789abcdef");

// 1. Call operations
await client.createCall("sip:a@example.net", "sip:b@example.net", undefined, "create-123456", { caller_id: "+15550001" });
await client.getCall("call-12345678");
await client.answerCall("call-12345678", "v=0\r\nm=audio 4000 RTP/AVP 0\r\n", "answer-123456");
await client.rejectCall("call-12345678", 486, "Busy Here", "reject-123456");
await client.hangupCall("call-12345678", "Normal Clearing", "hangup-123456");
await client.bridgeCall("call-12345678", ["chan-a", "chan-b"], "bridge-123456");
await client.media("call-12345678", "play", "prompt.wav", "media-123456");
await client.setHeaders("call-12345678", [{ action: "add", name: "X-Customer", value: "vip" }], "hdr-123456");
await client.transferCall("call-12345678", "sip:sales@example.net", "blind", undefined, "xfer-123456");
await client.holdCall("call-12345678", "hold-123456");
await client.unholdCall("call-12345678", "unhold-123456");
await client.sendDtmf("call-12345678", "9", 200, "dtmf-123456");
await client.rtpControl("call-12345678", "offer", { sdp: "v=0\r\n" }, "rtp-123456");
await client.routeCall("call-12345678", "sip:agent@10.0.0.1:5060", "udp", "route-123456", { mode: "proxy", caller_id: "+15559999" });
await client.identity("call-12345678", "sign", undefined, "A", "id-123456");

// 2. Advanced MAF services
await client.scheduledCalls();
await client.scheduleCall("sip:a@example.net", "sip:b@example.net", "2026-09-05T12:00:00Z");
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

// 3. Events
const evts = await client.events(4, "call.created", 200);
assert.equal(evts.schema, "madis.maf.command-receipt.v1");

// 4. WebSocket URL generator
const wsUrl = client.wsUrl({ eventType: "call.dtmf", callId: "call-12345678" });
assert.equal(wsUrl, "wss://proxy.example.net/admin/api/v1/maf/events/ws?cursor=0&event_type=call.dtmf&call_id=call-12345678");

// Validations
assert.equal(calls.length, 33);
assert.equal(calls[0].url, "https://proxy.example.net/admin/api/v1/maf/calls");
assert.equal(calls[0].options.headers.Authorization, "Bearer 0123456789abcdef");
assert.equal(calls[0].options.headers["X-MAF-Version"], "0.7.0");
assert.equal(calls[0].options.headers["Idempotency-Key"], "create-123456");
assert.equal(calls[1].url, "https://proxy.example.net/admin/api/v1/maf/calls/call-12345678");
assert.equal(calls[32].url, "https://proxy.example.net/admin/api/v1/maf/events?cursor=4&limit=100&event_type=call.created");

console.log(`JavaScript MAF SDK tests passed (${calls.length} operations verified).`);
