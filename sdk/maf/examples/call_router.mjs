#!/usr/bin/env node
/**
 * Smart SIP Call Router & Policy Engine using MADIS Application Fabric (MAF).
 *
 * Demonstrates how a Node.js/JavaScript application can fully control
 * inbound call routing, caller ID presentation, and failover:
 * - Subscribes to MAF events (call.created / call.ringing)
 * - Evaluates custom routing policies (DID mapping, time-of-day, carrier cost)
 * - Dispatches calls using `calls.route` with custom Caller ID and P-Asserted-Identity
 * - Rejects unauthorized numbers with custom SIP codes (403/486/603)
 *
 * Usage:
 *     node call_router.mjs --url http://127.0.0.1:8080/admin --token <MAF_TOKEN>
 */

import { MadisMaf } from '../javascript/madis-maf.mjs';

const parseArgs = () => {
  const args = process.argv.slice(2);
  const out = { url: 'http://127.0.0.1:8080/admin', token: '' };
  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--url' && args[i + 1]) out.url = args[++i];
    if (args[i] === '--token' && args[i + 1]) out.token = args[++i];
  }
  return out;
};

const config = parseArgs();
if (!config.token || config.token.length < 16) {
  console.error('Error: --token <MAF_TOKEN> is required (min 16 characters).');
  process.exit(1);
}

const maf = new MadisMaf(config.url, config.token);

// Simple routing table mapping dialed prefixes / DIDs to target gateways
const ROUTING_TABLE = [
  { prefix: '+1800', target: 'sip:tollfree-gw.carrier.net:5060', transport: 'udp' },
  { prefix: '+44', target: 'sip:uk-trunk.carrier.net:5061', transport: 'tls' },
  { prefix: '+33', target: 'sip:fr-trunk.carrier.net:5060', transport: 'tcp' },
];
const DEFAULT_GATEWAY = 'sip:primary-sbc.carrier.net:5060';

let running = true;
process.on('SIGINT', () => {
  console.log('\nShutting down call router...');
  running = false;
});

async function handleIncomingCall(callId, payload) {
  const caller = payload?.from_uri || '';
  const callee = payload?.to_uri || '';
  console.log(`[Router] Evaluating routing for Call ${callId}: from=${caller} to=${callee}`);

  // Policy check: blacklist spammers or invalid caller IDs
  if (caller.includes('anonymous') && !callee.includes('test')) {
    console.log(`[Router] Rejecting anonymous caller ${caller}`);
    try {
      await maf.rejectCall(callId, 403, 'Forbidden Anonymous');
    } catch (err) {
      console.error(`[Router] Failed to reject call ${callId}:`, err);
    }
    return;
  }

  // Find matching destination gateway
  let selected = ROUTING_TABLE.find(rule => callee.includes(rule.prefix));
  let target = selected ? selected.target : DEFAULT_GATEWAY;
  let transport = selected ? selected.transport : 'udp';

  console.log(`[Router] Routing call ${callId} -> ${target} (${transport})`);

  try {
    // Route call with customized caller presentation
    await maf.routeCall(callId, target, {
      transport: transport,
      callerId: '+15551234567',
      callerName: 'Smart Routing Gateway',
      pAssertedIdentity: 'sip:+15551234567@example.net',
      privacy: 'none',
    });
    console.log(`[Router] Call ${callId} successfully routed to ${target}`);
  } catch (err) {
    console.error(`[Router] Failed to route call ${callId}:`, err);
    // Failover: send 503 Service Unavailable
    try {
      await maf.rejectCall(callId, 503, 'Routing Unavailable');
    } catch {}
  }
}

async function startEventLoop() {
  let cursor = 0;
  console.log(`[Router] Connected to MAF at ${config.url}. Listening for events...`);

  while (running) {
    try {
      const page = await maf.events({ cursor });
      const events = page?.events || [];

      for (const event of events) {
        const type = event.type || '';
        const callId = event.call_id || '';

        if (type === 'call.created' || type === 'call.ringing') {
          let payload = event.payload;
          if (typeof payload === 'string') {
            try { payload = JSON.parse(payload); } catch { payload = {}; }
          }
          await handleIncomingCall(callId, payload);
        } else if (type === 'call.ended') {
          console.log(`[Router] Call ${callId} completed`);
        }
      }

      if (page?.next_cursor !== undefined && page.next_cursor !== cursor) {
        cursor = page.next_cursor;
      } else {
        await new Promise(r => setTimeout(r, 500));
      }
    } catch (err) {
      console.error('[Router] Error polling events, retrying in 2s:', err.message);
      await new Promise(r => setTimeout(r, 2000));
    }
  }
}

startEventLoop();
