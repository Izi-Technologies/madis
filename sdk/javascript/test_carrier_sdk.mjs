import assert from "node:assert/strict";
import { MadisCarrier } from "./madis-carrier.mjs";

const calls = [];
globalThis.fetch = async (url, options) => {
  calls.push({ url: String(url), options });
  return {
    ok: true,
    status: 200,
    json: async () => ({ ok: true, count: 1 }),
  };
};

const client = new MadisCarrier("https://proxy.example.net/admin", "carrier-token-1234567890");

// 1. Basic capabilities & billing
await client.capabilities();
await client.pendingEvents(50);
await client.publish({ event_type: "cdr.lifecycle" });
await client.ack("evt-1234");
await client.cdr(25, "call-1");

// 2. Control status & routing rules
await client.controlStatus();
await client.routingRules(100);
await client.createRoutingRule({ action: "gateway", prefix: "1" });
await client.setRoutingRuleEnabled(1, true);
await client.setRoutingRuleEnabled(1, false);

// 3. Dialplans
await client.dialplans(10);
await client.createDialplan({ match: "^9", strip: 1 });
await client.setDialplanEnabled(2, true);
await client.setDialplanEnabled(2, false);
await client.updateDialplan(2, { strip: 2 });
await client.deleteDialplan(2);

// 4. Generic control resources
await client.controlResources("gateways", 50);
await client.createControlResource("gateways", { name: "gw-1" });
await client.updateControlResource("gateways", 5, { port: 5080 });
await client.deleteControlResource("gateways", 5, "rev-1");
await client.setControlResourceEnabled("gateways", 5, true);

// 5. Validations
await client.validateRoutingRule({ prefix: "44" });
await client.validateDialplan({ match: "^0" });

assert.equal(calls.length, 23);
for (const call of calls) {
  assert.equal(call.options.headers.Authorization, "Bearer carrier-token-1234567890");
}

// Check allowlist rejection
assert.throws(() => client.controlResources("unknown_resource"), /allowlist/);

console.log(`JavaScript Carrier SDK tests passed (${calls.length} operations verified).`);
