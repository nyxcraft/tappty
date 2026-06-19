# Focused review index

These reviews were written against runtime code at `7924e69` on `main` before adding
the review notes. They are intentionally narrow: each file covers one risk surface,
lists concrete findings with source references, and separates current blockers from
follow-up hardening.

Verification performed during the review:

- `python3 -m pytest` -> 65 passed, 2 skipped
- `python3 -m ruff check .` -> clean
- `python3 -m compileall -q src tests` -> clean
- `PYTHONPATH=src python3 -c "import tappty; print(tappty.__version__)"` -> `0.1.0`

## Review files

- [01-concurrency-lifecycle.md](01-concurrency-lifecycle.md)
- [02-cross-platform.md](02-cross-platform.md)
- [03-terminal-fidelity.md](03-terminal-fidelity.md)
- [04-protocol-api-contract.md](04-protocol-api-contract.md)
- [05-test-quality-flakiness.md](05-test-quality-flakiness.md)
- [06-performance-resource.md](06-performance-resource.md)
- [07-packaging-release.md](07-packaging-release.md)
- [08-ux-input.md](08-ux-input.md)

## Highest-value follow-ups

1. Add an explicit session/source shutdown path and have renderers call it on exit.
2. Harden `HELLO` payload validation for non-dict JSON and non-string `role`/`name`.
3. Replace timing sleeps in bus tests with event/poll based synchronization.
4. Decide whether the GUI extra should depend on `pygame` or `pygame-ce`, then test the
   same dependency in CI.
5. Add a Windows validation job once `ConPtySource` has been exercised on real Windows.
