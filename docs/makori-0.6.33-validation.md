# Makori 0.6.33 validation

The compiler pin is `81ef8c594c4fe5bb1a7a58f5a116f818faaf7a9e` (0.6.33).
Compiler and runtime come from the same checkout; all application builds use
the C backend.

0.6.33 adopts `if let` for concise single-arm pattern matching, the
nonblocking accept fix, and struct move safety improvements:

- ~110 `match parse_int(...) { Ok(v) => { ... } Err(_) => {} }` patterns
  rewritten to `if let Ok(v) = parse_int(...) { ... }` across 25 source files.
- Removed manual `io_set_nonblocking(c, 0)` workaround after `tcp_accept_nb`
  in `workers.mko` and `ims_cx_push.mko` — the 0.6.33 runtime clears
  `O_NONBLOCK` on accepted sockets automatically and adds `EINTR` retry loops
  to `tcp_read`/`tcp_write`.
- Struct move safety: multi-mention identifiers in single statements prevent
  premature move zeroing; struct/tuple stack padding bytes are unconditionally
  zero-initialized.

All 0.6.32 features (structured crew policies, inline small channels, memset
elision, channel-drop safety) and 0.6.31 ownership/JSON-escaping fixes remain
in this compiler. See the [0.6.32 report](makori-0.6.32-validation.md) and the
[0.6.31 report](makori-0.6.31-validation.md) for prior history.

## Results

| Check | Result |
| --- | --- |
| macOS arm64 `makori check` proxy and admin | Pass |
| macOS arm64 complete Mako test suite, C backend | 49 test files pass, zero failures |

## Remaining validation

ASan/UBSan, LeakSanitizer, native C builds, SIGPIPE check, Linux x86_64 C
link, and a production deploy have not yet been run on this pin. These results
do not establish stable RSS under sustained SIP traffic. See the
[0.6.32 report](makori-0.6.32-validation.md) for the last full validation
matrix.
