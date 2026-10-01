# CMap integer ownership fix verified — c2a2d38

Madis now pins Mako commit `c2a2d38212903b981f967c7023c5fe07744e1d71`
with its matching runtime in CI, release, and IMS smoke builds. README and
installer guidance reference the same revision.

Verification ran directly on `sip-test.example.invalid`. The existing compiler
executable was reused because compiler source is unchanged from `249a616`;
every check explicitly selected the candidate runtime. The application allocation
probe was recompiled against the new headers. No production service was replaced
or restarted, and no new performance comparison was run.

The earlier `5d9681a` revision fixed normal integer set/get temporaries but missed
the early return for an existing empty value. `c2a2d38` releases that allocated
value before returning the fallback. Missing keys and composite-key helpers are
also covered.

## Server results

| Check | Result |
|---|---|
| Original integer set/get reproducer, 1,000 iterations | Pass, no reported leaks |
| Missing-key fallback, 1,000 reads | Pass, no reported leaks |
| Existing empty-value fallback, 1,000 reads | Pass, no reported leaks |
| Composite empty-value fallback, 1,000 reads | Pass, no reported leaks |
| Upstream replacement and int64-limit regression, 1,000 iterations | Pass, no reported leaks |
| Functional suite | 56 test files passed |
| Linux ownership gate | Pass |
| Application allocation probe: 100 complete dialogs with transaction ticks | Pass, no reported leaks |

Allocation checks used Linux ASan/UBSan with LSan enabled and halt-on-error.
The application keeps its ownership adapters and named temporaries: this commit
does not change compiler temporary handling, and the integer adapter also
preserves strict fallback parsing. The project still has the previously reported
500 CPS completion limitation; fixing this runtime leak does not establish a
performance lead or prove every application path is leak-free.

## Evidence

- [Four direct runtime cases](../bench/results/cmap-integer-c2a2d38-linux.txt)
- [Upstream integer regression](../bench/results/cmap-upstream-c2a2d38-linux.txt)
- [Functional suite](../bench/results/functional-c2a2d38-linux.txt)
- [Linux ownership gate](../bench/results/ownership-gate-c2a2d38-linux.txt)
- [Application allocation probe](../bench/results/dialog-allocations-owned-c2a2d38-linux.txt)
- [Upstream issue #77](https://github.com/loreste/mako/issues/77)

Kluster was unavailable in this session; no Kluster review was run.
