# Live SIP applications and external modules

Madis can call external HTTP(S) services for bounded SIP decisions and for selected application work. These integrations are network contracts, not an in-process plugin ABI. The external service may be written in Python, Go, Node.js, Lua, Erlang, or another language that can implement the JSON contract.

## Configuration

```sh
SIP_APP_URL=https://app.example.net/madis/sip
SIP_APP_TOKEN=long-random-application-secret
SIP_APP_TIMEOUT_MS=100
SIP_APP_FAIL_MODE=open

SIP_MODULE_URL=https://modules.example.net/madis/dispatch
SIP_MODULE_TOKEN=long-random-module-secret
SIP_MODULES=tts,stt,llm,media,recording
SIP_MODULE_TIMEOUT_MS=250
SIP_MODULE_FAIL_MODE=closed
```

`SIP_APP_URL` and `SIP_APP_TOKEN` enable the live SIP application gateway together. `SIP_MODULE_URL` and `SIP_MODULE_TOKEN` enable the module dispatcher together. `SIP_APP_CA` and `SIP_MODULE_CA` select CA bundles; HTTPS verification is the normal mode. `SIP_APP_ALLOW_HTTP=1` and `SIP_MODULE_ALLOW_HTTP=1` are explicit protected-lab exceptions.

Timeouts are clamped by the implementation. Application timeouts are bounded to 10–1000 ms and module timeouts to 10–2000 ms. `SIP_APP_FAIL_MODE=open` preserves local SIP behavior when an optional application is unavailable; `closed` rejects the request instead. Modules fail closed by default because an explicitly requested module operation usually forms part of the application workflow.

## Live application contract

The application request is a signed, bounded `madis.sip.event.v1` document. The response is a signed, bounded `madis.sip.command.v1` document. The request can contain the validated SIP method, direction, caller/callee information, headers, bounded body data, transaction identifiers, and the configured application context.

The application may return only validated commands, including:

- `continue` to keep local processing;
- `route`, `dispatch`, `failover`, or `b2bua` policy values;
- `reply`, `reject`, or `redirect` responses;
- constrained header/body changes;
- a module request with the configured module allowlist.

Madis retains transaction and dialog ownership. The application cannot inject raw SIP bytes, execute Mako, run SQL, invoke shell commands, or install code. A `b2bua` decision still requires `SIP_B2BUA_MODE=enabled`.

Application calls occur only after the applicable SIP syntax/security checks. Keep the endpoint private or protected by mTLS at the deployment edge, and do not place the shared token in routing data or browser code.

## Module contract

The dispatcher uses signed `madis.module.request.v1` requests. Built-in module names are:

`tts`, `stt`, `llm`, `media`, `recording`, `fraud`, and `billing`.

The request includes a bounded `request_id`, operation, session/call context, and application data. A module response can return a bounded result or a fast acknowledgement for work that the external service continues asynchronously. A module response cannot recursively invoke another module.

Set `SIP_MODULES` to the smallest production allowlist. Custom module names or operations require `SIP_MODULE_ALLOW_CUSTOM=1` and remain subject to the same size and character bounds.

## Long-running work

Do not hold a SIP transaction open while an LLM, speech, media, or fraud system performs an unbounded job. Return a fast acknowledgement, persist the correlation ID in the external service, and use the application’s own queue or callback/event path for completion. Madis does not provide a general job scheduler or application database.

## Security and failure behavior

- Calls are made only after local SIP validation and security checks.
- Shared-secret signing authenticates the message; HTTPS/mTLS provides transport confidentiality and peer authentication.
- HTTP response bodies and SIP command fields are independently bounded.
- Tokens are separate from carrier/control API tokens.
- Commands are allowlisted and cannot recurse through the module dispatcher.
- Keep bounded replay detection for request IDs in the external service if transaction matching alone is insufficient.
- Test timeout, signature failure, malformed response, unavailable endpoint, and configured open/closed behavior before enabling production traffic.

The live gateway is an extension point, not a claim that every external application or media service implements all SIP, WebRTC, or media standards. See [`../api/README.md`](../api/README.md) for the separate carrier/control API.
