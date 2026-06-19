# Performance and resource review

## Scope

Reviewed frame fanout, queue growth, render caches, snapshot I/O, caps on untrusted input,
and subprocess/cast resource behavior.

No high-severity findings. The largest untrusted inputs now have explicit caps:
bus frames, `CMD` captures, cast dimensions, cast lines, and v1 cast file size.

## Findings

### Medium: subscribed bus clients receive full frames on every frame event

Evidence:

- `Session._output()` fans out a frame after every output chunk (`src/tappty/session.py:93`).
- `BusServer._push_frame()` snapshots the full screen and sends it to every subscribed
  connection (`src/tappty/bus.py:342`).
- `Session.snapshot()` builds a full rows list each time (`src/tappty/session.py:71`).

Impact:

For chatty programs, larger terminal sizes, or multiple subscribers, the server can spend a
lot of time serializing and sending full frames even when clients only need the latest
state. This is acceptable for the current small terminal default, but it becomes the likely
hot path for remote dashboards.

Recommendation:

Add frame coalescing or rate limiting for subscribed clients. A simple model is one dirty
flag plus a timer/tick that sends the latest snapshot at a bounded rate. For remote
renderers, dropping stale frames is usually better than building a backlog.

### Medium: `BusClient.inbox` is unbounded

Evidence:

`BusClient` creates an unbounded `queue.Queue()` and the reader thread puts every message
into it (`src/tappty/bus.py:386`, `src/tappty/bus.py:397`). `BusBacking` has a bounded
frame deque, but that bound is after messages have already passed through the client inbox
(`src/tappty/compositor.py:128`, `src/tappty/compositor.py:133`).

Impact:

A subscribed but slow or abandoned client can accumulate unbounded `OUT`, `FRAME`, and
`EVENT` messages in memory.

Recommendation:

Give `BusClient` an optional bounded queue or add a specialized subscription client that
drops old frames/events under pressure. At minimum, document that callers who subscribe must
drain `inbox`.

### Low: glyph atlases grow without eviction

Evidence:

`pygame_ui` caches every rendered printable character (`src/tappty/pygame_ui.py:39`), and
the compositor caches glyphs per font size (`src/tappty/compositor.py:187`,
`src/tappty/compositor.py:70`).

Impact:

Normal terminal output uses a small glyph set. A hostile or accidental stream of many
Unicode code points can grow the cache for the lifetime of the renderer.

Recommendation:

Leave as-is for now, or add an LRU cap if untrusted remote output becomes common. A cap of
a few thousand glyphs per font size is likely enough.

### Low: snapshot mode writes PNGs frequently

Evidence:

`pygame_ui` writes both a text snapshot and a PNG on every snapshot tick
(`src/tappty/pygame_ui.py:106`). The compositor also saves PNG frames on its snapshot tick
(`src/tappty/compositor.py:357`).

Impact:

This is useful for review/debugging but can be heavy on slow disks or long-running sessions.

Recommendation:

Consider separate `snapshot_text_path` and `snapshot_png_path` options, or save PNG only on
F12/manual request unless explicitly enabled.

## Positive notes

- `MAX_FRAME` and `MAX_CAPTURE` bound bus protocol and synchronous command memory
  (`src/tappty/bus.py:41`).
- `CastSource` clamps dimensions and caps unstreamable v1 files (`src/tappty/source.py:29`,
  `src/tappty/source.py:233`).
- `BusBacking` already drops old queued frames with a bounded deque
  (`src/tappty/compositor.py:128`).
