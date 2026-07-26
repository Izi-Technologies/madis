# External SIP applications and modules

Madis owns SIP parsing, transactions, routing, dialog state, and transport.
Application code stays outside the SIP worker. A service written in Python,
Go, JavaScript, Lua, Erlang, or another language can make the live call
decision over HTTP(S); it does not need to compile Mako.

There are two related hooks:

1. The SIP application hook receives a SIP request or response and returns a
   command such as `proxy`, `b2bua`, `reply`, `redirect`, `drop`, or
   `continue`.
2. The module bus lets that application ask a configured module dispatcher to
   perform a bounded operation such as TTS `speak`, STT `transcribe`, LLM
   `complete`, media `play`, or recording `start`.

The module dispatcher can be one service or a gateway that routes to
specialist services. Madis does not load arbitrary shared libraries, execute
foreign code, or give a module a pointer to SIP state. The dispatcher returns
the same signed SIP command format, so a module can ask Madis to continue,
change an allowed header/body, route, answer, or end a transaction.

## Configuration

Set these on the SIP worker, not in browser code:

```sh
SIP_APP_URL=https://app.example.net/madis/sip
SIP_APP_TOKEN=long-random-application-secret
SIP_APP_TIMEOUT_MS=100
SIP_APP_FAIL_MODE=open          # use closed when the app is mandatory

SIP_MODULE_URL=https://modules.example.net/madis/dispatch
SIP_MODULE_TOKEN=long-random-module-secret
SIP_MODULES=tts,stt,llm,media,recording
SIP_MODULE_TIMEOUT_MS=250
SIP_MODULE_FAIL_MODE=closed
```

HTTPS is required by default. Plain HTTP requires an explicit
`SIP_APP_ALLOW_HTTP=1` or `SIP_MODULE_ALLOW_HTTP=1` and is suitable only for a
protected local network. `SIP_APP_CA` and `SIP_MODULE_CA` can point to a CA
bundle. Do not use URL userinfo or put secrets in the URL.

The application hook is disabled unless both its URL and token are present.
The module bus is disabled unless its URL, token, and module allowlist permit
the requested operation. The installer creates separate random secrets for
the application and module paths; keep them separate from the carrier and
routing-control tokens.

## Request flow

The normal flow is:

```text
SIP packet
   -> Madis parses, authenticates, and applies local policy
   -> application service makes a bounded SIP decision
   -> optional module dispatcher calls TTS/STT/LLM/etc.
   -> Madis verifies the signed command and owns the SIP transaction
```

The application hook is called for REGISTER, new INVITE, other eligible
requests, and responses. In-dialog B2BUA requests stay under Madis's leg
translator so an external service cannot break the independent transaction
identities; translated responses remain observable through the response hook.
The hook is synchronous and opt-in, so its timeout is part of call setup
latency. Use a local low-latency dispatcher for high-CPS traffic and move
long-running speech or LLM work to an asynchronous workflow.

A module is not a native plugin loaded into the SIP process. It is an
out-of-process HTTP(S) service behind the module dispatcher. This keeps a
foreign runtime, model, codec, database client, or framework outside Madis's
memory and transaction boundary. The dispatcher can be a single service or a
router that forwards the request to separate Python, Go, JavaScript, Lua, or
Erlang workers.

## Event envelope

Madis sends a bounded JSON document with schema `madis.sip.event.v1`:

```json
{
  "schema": "madis.sip.event.v1",
  "event": "request",
  "request_id": "same-for-retries-of-this-transaction",
  "method": "INVITE",
  "status": 0,
  "transport": "udp",
  "source_ip": "192.0.2.10",
  "source_port": 5060,
  "request_uri": "sip:+15551212@example.net",
  "call_id": "call-42@example.net",
  "from": "<sip:+15550001@example.net>;tag=a",
  "to": "<sip:+15551212@example.net>",
  "cseq": "1 INVITE",
  "user_agent": "Example UA",
  "body": "",
  "body_truncated": false,
  "message": "INVITE ...",
  "signature": "sha256(token|request_id|event-fields-in-contract-order)"
}
```

Responses use `madis.sip.command.v1`. The signature is calculated over the
command fields, including `action`, `target`, status, reason, header changes,
body, and module fields. This binds a response to its request ID and prevents
changing a target or header after signing.

For a command, join the decoded values in this order: `request_id`, lowercase
`action`, `target`, decimal `status`, `reason`, `set_headers`, `add_headers`,
`remove_headers`, `body`, `module`, `operation`, and `payload`. Missing fields
are empty strings (status is zero). Sign `SHA-256(token + "|" + joined-values)`.

For an event, join the decoded values with `|` in this order: `request_id`,
`event`, `method`, decimal `status`, `transport`, `source_ip`, decimal
`source_port`, `request_uri`, `call_id`, `from`, `to`, `cseq`, `user_agent`,
bounded `body`, `body_truncated` (`true`/`false`), and bounded `message`. The
signature is `SHA-256(token + "|" + joined-values)`. Do not use a URL query
parameter for the token.

```json
{
  "schema": "madis.sip.command.v1",
  "request_id": "same-for-retries-of-this-transaction",
  "action": "proxy",
  "target": "sip:carrier.example.net:5060;transport=tcp",
  "status": 0,
  "reason": "",
  "set_headers": "X-Tenant: carrier-a",
  "add_headers": "P-Asserted-Identity: <sip:+15550001@example.net>",
  "remove_headers": "Privacy",
  "body": "",
  "signature": "..."
}
```

Header fields are newline-separated `Name: value` lines. Madis rejects
control characters, duplicate transaction identity changes, `Via`, `From`,
`To`, `Call-ID`, `CSeq`, `Max-Forwards`, `Route`, `Record-Route`, and
`Content-Length` mutations. Body changes are bounded and have their
`Content-Length` rebuilt by Madis. The service cannot submit SQL, Mako, shell
commands, arbitrary SIP start lines, or an unvalidated raw response.

Supported request actions:

| Action | Use |
| --- | --- |
| `continue` | Keep Madis routing, optionally applying validated headers/body changes. |
| `proxy` / `route` / `dispatch` | Send to one or more validated SIP targets. |
| `b2bua` | Start an explicit B2BUA leg; requires `SIP_B2BUA_MODE=enabled`. |
| `reply` | Return a structured SIP response with status, reason, headers, and body. |
| `redirect` | Return a 302 with a validated `Contact` target. |
| `drop` | Deliberately send no SIP response; use only with a transaction policy. |
| `module` | Invoke an allowlisted external module operation. |

Response events accept `continue`, `replace`, `reply`, and `drop`. Madis still
owns Via stripping, transaction completion, fork selection, B2BUA translation,
and non-2xx ACK generation.

## Module requests

The module dispatcher receives `madis.module.request.v1`:

```json
{
  "schema": "madis.module.request.v1",
  "event": "request",
  "request_id": "module-request-id",
  "module": "llm",
  "operation": "complete",
  "transport": "udp",
  "source_ip": "192.0.2.10",
  "source_port": 5060,
  "call_id": "call-42@example.net",
  "message": "INVITE ...",
  "payload": "{\"prompt\":\"summarize the caller request\"}",
  "signature": "sha256(module-token|request-fields-in-contract-order)"
}
```

The module returns a signed `madis.sip.command.v1` document using
`SIP_MODULE_TOKEN`. A module may return `continue` with a bounded body or
headers, or make a call decision. TTS/STT/media services should use a media
system such as RTPEngine for RTP/DTLS-SRTP; the module bus carries control and
results, not untrusted codec code inside the SIP process.

For a module request, join `request_id`, `event`, `module`, `operation`,
`transport`, `source_ip`, decimal `source_port`, `call_id`, bounded `message`,
and `payload` in that order. Sign `SHA-256(module_token + "|" + joined-values)`.
Command signatures use the decoded command-field order described above. A
client must construct that exact input before calculating SHA-256.

Built-in module operations are:

| Module | Operations |
| --- | --- |
| `tts` | `speak`, `synthesize`, `attach` |
| `stt` | `listen`, `transcribe`, `attach` |
| `llm` | `complete`, `chat`, `classify` |
| `media` | `attach`, `play`, `stop`, `record` |
| `recording` | `start`, `stop`, `pause`, `resume` |
| `fraud` | `score`, `allow`, `deny` |
| `billing` | `authorize`, `update`, `terminate` |

Set `SIP_MODULES` to a comma-separated subset in production. Custom module
names and operations require `SIP_MODULE_ALLOW_CUSTOM=1`; they still must
match the name/operation character and length limits. A module response cannot
invoke another module.

For long-running work, return a fast acknowledgement and use the application
service to correlate the `request_id` with an asynchronous event. Do not hold
a SIP transaction open while an LLM or speech service performs an unbounded
job. The synchronous timeout is intentionally capped.

## Security and failure behavior

- App and module calls happen only after SIP syntax/security checks; INVITE
  hooks run after digest authentication and online charging.
- Tokens are separate and never stored in routing rules or SQL payloads.
- HTTP(S) response bodies are capped at 64 KiB; SIP bodies and command fields
  are independently bounded.
- `SIP_APP_FAIL_MODE=open` keeps ordinary SIP local if the optional app is
  unavailable. Use `closed` when the application is the admission policy.
- Module calls default to fail-closed because a requested TTS/STT/LLM action
  is usually part of an explicit application workflow.
- A module cannot recurse into another module through a module response.
- Keep application/module endpoints on a private network or behind mTLS at
  the deployment edge. The shared digest authenticates the message; HTTPS
  provides confidentiality. If an application needs replay detection beyond
  transaction matching, retain recently seen request IDs in its own bounded
  cache.

The gateway is an extension point, not a claim that every SIP or media RFC is
implemented by every external service. Test the complete call flow, media
interworking, and failure policy with the carrier's endpoints before enabling
it in production.
