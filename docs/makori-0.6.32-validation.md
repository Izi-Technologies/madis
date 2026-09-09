# Makori 0.6.32 validation

The compiler pin is `1a75d53f15e59bf1a5f58eb3e14d75180c7d82d7` (0.6.32).
Compiler and runtime come from the same checkout; all application builds use
the C backend.

0.6.32 is the first pin that uses structured crew policies, arenas, and
actors in the SIP worker:

- Process and admin WebSocket nurseries are `crew:all`.
- After listeners are on dedicated pthreads, `sched_set_workers(4)` starts a
  request pool (`SIP_REQUEST_WORKERS`) so per-INVITE `crew:all` fork/CANCEL
  and quality scoring reuse four workers instead of one pthread per branch.
- Dispatch algorithm `first`/`race` uses `crew:race` plus `chan_new(4)`
  (`sip_inline_chan`) so the first healthy member publishes an index on the
  inline ring and the slower probe is cancelled. Cap ≤ 4 int channels do not
  heap-allocate a payload buffer.
- `HepCapture` and `SipWorkers` are mailbox actors (cap 4, same inline ring).
- IPv4 bind/HEP checks parse octets in an arena and only the 0/1 result
  escapes.

String HEP outboxes still heap-allocate their ring (`MakoChanStr` has no
inline buffer). Zero-allocation applies to `chan[int]` with cap 0..4.

`crew:race` is not used for the listener nursery: the first worker
returning would cancel the remaining sockets. Release builds keep
`-DNDEBUG`, so the new trace hooks are no-ops.

The 0.6.31 ownership and JSON-escaping fixes remain in this compiler. See
the [0.6.31 report](makori-0.6.31-validation.md) for the leak-gate history.

## Results

| Check | Result |
| --- | --- |
| macOS arm64 `makori check` proxy and admin | Pass |
| macOS arm64 complete Mako test suite, including crew-policy contract | 49 test files pass, zero failures |
| macOS arm64 ownership sanitizer (ASan/UBSan; no LeakSanitizer) | Pass |
| macOS arm64 proxy/admin C builds and SIGPIPE check | Pass; both remain healthy |
| Linux x86_64 C link of 0.6.32 emit-c output | Pass |
| Linux x86_64 deploy on medis.lancethedev.com | Pass: `madis` and `madis-admin` active |
| Authenticated `/healthz` and `/readyz` | `{"ok":true,"version":"0.7.4"}` and `{"ready":true}` |
| SIP OPTIONS UDP and TCP to bound IPv4 | Both return `200 OK` with To-tag |
| Admin `/admin/login` | HTTP 200 HTML |
| SIGPIPE to both processes | Both remain active and responsive |

`chan[int]` with cap 0..4 uses `inline_buf[4]` and does not heap-allocate a
payload ring. First-healthy dispatch and actor mailboxes use that path.
`chan[string]` (HEP outbox, ownership fixture) still heap-allocates
`MakoString` slots. The production HEP queue default remains 8192.

The Linux deploy used 0.6.32 C emission from macOS arm64, linked with gcc on
the host against the matching runtime headers. The host PostgreSQL instance
listens on 5433; FayDB occupies 5432.

## Remaining validation

Linux LeakSanitizer was not re-run on this pin; the macOS ownership gate
covers ASan/UBSan only. These results do not establish stable RSS under
sustained SIP traffic. A repeat traffic soak with post-load idle sampling
remains necessary. See the historical
[0.6.29 report](makori-0.6.29-validation.md) and the
[0.6.31 report](makori-0.6.31-validation.md).
