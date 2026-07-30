import assert from "node:assert/strict";
import { MadisMaf } from "../javascript/madis-maf.mjs";

const calls = [];
globalThis.fetch = async (url, options) => {
  calls.push({ url: String(url), options });
  return {
    ok: true,
    status: options.method === "POST" ? 202 : 200,
    text: async () => JSON.stringify({ status: "accepted", resource_id: "call-12345678" }),
  };
};

const client = new MadisMaf("https://proxy.example.net/admin", "0123456789abcdef");
await client.createCall("sip:a@example.net", "sip:b@example.net", undefined, "create-123456");
await client.getCall("call-12345678");
await client.answerCall("call-12345678", "v=0\r\nm=audio 4000 RTP/AVP 0\r\n", "answer-123456");
await client.bridgeCall("call-12345678", ["chan-a", "chan-b"], "bridge-123456");
await client.events(4, "call.created", 200);

assert.equal(calls.length, 5);
assert.equal(calls[0].url, "https://proxy.example.net/admin/api/v1/maf/calls");
assert.equal(calls[0].options.headers.Authorization, "Bearer 0123456789abcdef");
assert.equal(calls[0].options.headers["Idempotency-Key"], "create-123456");
assert.equal(calls[1].url, "https://proxy.example.net/admin/api/v1/maf/calls/call-12345678");
assert.equal(calls[4].url, "https://proxy.example.net/admin/api/v1/maf/events?cursor=4&limit=100&event_type=call.created");
