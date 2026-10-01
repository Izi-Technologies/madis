# Makori 0.6.34 validation

The compiler pin is `45c8e61a94a13dce9f01c3c913a6a5f28610ce8c` (0.6.34).
Compiler and runtime come from the same checkout; all application builds use
the C backend.

0.6.34 brings channel data-race elimination, iterator invalidation
prevention, 8MB stack safety, and the `if let` desugar fix for large pull
trees:

- Channel trylock fast path replaces spinlock with
  `pthread_mutex_trylock`/`TryAcquireSRWLockExclusive`, eliminating
  TSan-detected races. Direct benefit for crew workers, HEP actors, and
  dispatch channels.
- Iterator invalidation prevention: compile-time error when mutating an
  iterated collection inside a `for` loop body.
- Default thread stack reverted to 8MB, preventing stack smashing on deep
  SIP parsing/routing call chains.
- `accept4(SOCK_CLOEXEC)` on Linux for cleaner nonblocking accept.
- Remaining ~79 multiline `match` with empty `Err` arms rewritten to
  `if let` across 28 source files (continuing the 0.6.33 rewrite).
- One deeply nested `if let` in the shutdown drain path
  (`main.mko` line ~2212) kept as `match` due to a remaining desugar
  edge case in crew scope nesting.

All 0.6.33 features (`if let`, nonblocking accept fix, struct move safety)
and prior compiler fixes remain. See the
[0.6.33 report](makori-0.6.33-validation.md) for prior history.

## Results

| Check | Result |
| --- | --- |
| macOS arm64 `makori check` proxy and admin | Pass |
| macOS arm64 complete Mako test suite, C backend | 49 test files pass, zero failures |

## Remaining validation

ASan/UBSan, LeakSanitizer, native C builds, SIGPIPE check, Linux x86_64 C
link, and a production deploy have not yet been run on this pin. See the
[0.6.32 report](makori-0.6.32-validation.md) for the last full validation
matrix.
