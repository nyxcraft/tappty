# Concurrency and lifecycle review

## Scope

Reviewed thread ownership, renderer exit paths, source shutdown, bus start/stop,
`CMD` capture state, observer callbacks, and terminal model locking.

No high-severity findings. The recent `CMD` capture fixes look materially improved:
`_Capture.completed` and `_Capture.cancelled` now distinguish prompt completion from
shutdown cancellation (`src/tappty/bus.py:74`, `src/tappty/bus.py:170`,
`src/tappty/bus.py:262`, `src/tappty/bus.py:357`).

## Findings

### Medium: renderer exit does not stop the hosted source

Evidence:

- `pygame_ui.run()` exits by writing a final snapshot and calling `pygame.quit()`, but it
  does not stop `session.source` (`src/tappty/pygame_ui.py:121`).
- `curses_ui.run()` returns on Ctrl-] or after the done prompt without source teardown
  (`src/tappty/curses_ui.py:91`, `src/tappty/curses_ui.py:95`).
- `compositor.run()` closes panels, but `SessionBacking.close()` is a no-op
  (`src/tappty/compositor.py:108`, `src/tappty/compositor.py:366`).

Impact:

In CLI process-exit flows the process often ends soon after the renderer returns, but in
embedded/library use a hosted subprocess, pty, pipe, or runner can keep running after the
window/panel is closed. This also makes renderer shutdown behavior differ from explicit
`CastSource.stop()` and `BusServer.stop()` lifecycle tests.

Recommendation:

Introduce `Session.stop()` that delegates to `source.stop()` and optionally joins the
source thread with a short timeout. Have `pygame_ui`, `curses_ui`, and `SessionBacking`
call it from a `finally` block or document that renderers are non-owning views.

### Low: source stop methods are fire-and-forget

Evidence:

- `PtySource.stop()` terminates and closes the master fd but does not join the reader
  thread or escalate if the child ignores termination (`src/tappty/source.py:177`).
- `PipeSource.stop()` terminates but does not close stdin/stdout or join
  (`src/tappty/source.py:365`).
- `ConPtySource.stop()` calls `terminate(force=True)` but does not join
  (`src/tappty/source.py:430`).

Impact:

Most normal cases finish because the reader loop sees EOF, but callers cannot know when
teardown is complete without reaching into `src.thread`. This matters for tests, repeated
embed/unembed cycles, and tools that need deterministic cleanup.

Recommendation:

Add a common `Source.stop(timeout=None)` contract or `Source.join(timeout=None)` helper.
For subprocess sources, close input streams where appropriate, terminate, wait briefly,
then kill/escalate if still alive.

### Low: `Terminal.clear()` is not locked

Evidence:

`Terminal.write()`, `snapshot()`, `rows_text()`, and `view_rows()` use `self.lock`, but
the public `clear()` method mutates grid/cursor state without acquiring it
(`src/tappty/terminal.py:38`). `PyteTerminal.clear()` does lock
(`src/tappty/pyte_terminal.py:60`).

Impact:

The internal form-feed path currently calls `clear()` while `write()` already holds the
reentrant lock, so ordinary output is safe. A public caller invoking `clear()` concurrently
with rendering can race.

Recommendation:

Wrap `Terminal.clear()` in `with self.lock:`. Because the lock is an `RLock`, the form-feed
path remains safe.

## Positive notes

- `BusServer.stop()` now detaches session taps, closes clients, releases claimed sticks,
  wakes active captures, closes the listener, clears `_sock`, and unlinks AF_UNIX paths
  (`src/tappty/bus.py:357`).
- Observer failures are isolated and emitted as `ERROR` breadcrumbs without killing the
  source thread (`src/tappty/session.py:97`).
- `CastSource.stop()` wakes long sleeps with an event, which is the right shape for a
  replay source (`src/tappty/source.py:302`).
