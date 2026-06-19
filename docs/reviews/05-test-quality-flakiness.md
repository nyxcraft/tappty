# Test quality and flakiness review

## Scope

Reviewed synchronization style, platform coverage, optional dependency coverage, private
state assertions, and behavioral gaps.

No high-severity findings. The suite covers real sockets, real subprocesses, pty, pipes,
cast replay, the session contract, talking-stick behavior, and headless GUI smoke paths
when optional deps are installed.

## Findings

### Medium: several bus tests rely on fixed sleeps

Evidence:

- `tests/test_bus_socket.py` uses sleeps to wait for prompt/capture/subscription/disconnect
  state (`tests/test_bus_socket.py:72`, `tests/test_bus_socket.py:112`,
  `tests/test_bus_socket.py:199`, `tests/test_bus_socket.py:237`).
- `tests/test_bus_security.py` sleeps before issuing `CMD` or checking ignored keys
  (`tests/test_bus_security.py:108`, `tests/test_bus_security.py:132`,
  `tests/test_bus_security.py:151`).
- `tests/test_compositor_backings.py` has a polling helper plus an additional fixed sleep
  before typing over the bus (`tests/test_compositor_backings.py:16`,
  `tests/test_compositor_backings.py:65`).

Impact:

These tests pass locally, but fixed sleeps tend to fail under loaded CI, slow Windows
runners, or alternate Python versions. They can also mask real ordering regressions.

Recommendation:

Prefer `threading.Event`, bus `EVENT WAIT`, or a bounded `wait_until(predicate)` helper for
every state transition. Keep sleeps only where the behavior is intentionally time based.

### Medium: Windows is not represented in CI yet

Evidence:

The workflow is Ubuntu-only and documents that a Windows job would currently need skips and
ConPTY validation (`.github/workflows/ci.yml:19`, `.github/workflows/ci.yml:39`). POSIX-only
tests use `PtySource` directly (`tests/test_pty_source.py:11`,
`tests/test_source_encoding.py:12`).

Impact:

The suite cannot yet protect the Windows code path or catch accidental POSIX assumptions in
the core API.

Recommendation:

Add `pytest.mark.skipif(os.name == "nt", reason="POSIX pty")` to pty-specific tests, then
add a Windows CI lane for import, EngineSource, PipeSource, TCP bus, PyteTerminal, and
eventually ConPtySource.

### Low: some tests assert private implementation details

Evidence:

Lifecycle tests inspect `_stream_obs`, `_frame_obs`, `_event_obs`, `_captures`, and import
`_Capture` directly (`tests/test_bus_socket.py:21`, `tests/test_bus_socket.py:75`,
`tests/test_bus_socket.py:126`).

Impact:

These tests are valuable because they pin recent lifecycle fixes, but they make internal
refactors harder and can pass while a black-box client behavior regresses.

Recommendation:

Keep the private-state tests for the race-prone paths, but pair them with black-box tests
where possible: client socket closes, command returns/raises, observer no longer receives
frames, and driver release is visible through `INFO`.

### Low: README's local test command runs a reduced suite

Evidence:

README suggests `pip install -e '.[dev]'` and `pytest` (`README.md:92`). That skips pyte and
pygame tests unless the optional packages are already installed.

Impact:

New contributors can think they ran the full suite while actually skipping the ANSI and GUI
smoke paths.

Recommendation:

Document two commands: quick core tests with `.[dev]`, and full local tests with
`.[dev,ansi,gui]` or whatever GUI dependency the project chooses.

## Positive notes

- Headless pygame smoke tests exist and exercise real draw loops under SDL dummy when pygame
  is installed (`tests/test_gui_smoke.py:1`).
- Error-path tests cover exit codes, observer isolation, runner exceptions, CMD timeouts,
  and pty spawn cleanup (`tests/test_error_handling.py:1`).
