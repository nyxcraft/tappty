# tappty — design document

How `tappty` is structured and why. This is the architecture companion to the
[README](../README.md) (the usage guide); it is for someone modifying the toolkit and
wanting the full picture — contracts, data shapes, the threading model, and the reasoning
behind each part. The open-work roadmap lives in [HISTORY.md](HISTORY.md) ("What's left").

---

## 1. The one idea

A terminal program's output should flow through a single pipeline where **every consumer is
equal**: the screen renderer, an out-of-process logger, and an automated driver are all just
clients of the same observe/control contract. Get that right and a human and a bot can
watch — and take turns driving — the *exact same* session, with no special-casing.

So tappty is split into four decoupled stages, each ignorant of the others' nature:

```
   a program                                          consumers (all equal)
  ┌─────────┐   bytes    ┌──────────┐  grid    ┌─────────┐  observe   ┌──────────────┐
  │ Source  │──────────▶ │ Terminal │ ───────▶ │ Session │ ─────────▶ │ curses_ui    │
  │ (pty /  │            │  (glass) │          │ (taps + │            │ pygame_ui    │
  │  engine)│ ◀──────────│          │ ◀─────── │ control)│ ◀───────── │ bus clients  │
  └─────────┘   input    └──────────┘  write   └─────────┘  control   │ compositor   │
                                                                       └──────────────┘
```

- **Source** produces output and accepts input — it does not know what a screen is.
- **Terminal** models the glass — it does not know where bytes come from or who draws it.
- **Session** fans output to observers and routes input back — it does not know if a
  consumer is a window, a socket, or an AI.
- **Renderers / bus clients** consume the contract — they do not know each other exist.

Two consequences run through everything below:

- **Fixed-size model.** The Terminal is a fixed grid (default 80×24). The hosted program
  stays sealed in its own dimensions; making the real window bigger/smaller is a *render-side*
  concern (a viewport), never a resize the program sees.
- **Bytes on the wire, characters on the glass.** A byte source's *raw bytes* travel
  losslessly to stream observers, while the *screen* shows those bytes decoded to characters.
  The Session owns that one decode (see §2.3); the terminal backends stay encoding-agnostic.

---

## 2. The parts

### 2.1 Source — `source.py`

A `Source` is "something that produces terminal output and consumes input." The interface is
tiny — three callbacks supplied at `start()`, plus `send_input()` and `stop()`:

```python
class Source:
    encoding = None      # wire encoding of raw output, or None if it already emits text
    returncode = None    # child exit status after on_exit (None if N/A)
    error = None         # exception that ended the program (None if clean)

    def start(self, on_output, on_wait, on_exit): ...   # begin producing on a thread
    def send_input(self, text): ...                     # feed input to the program
    def stop(self): ...                                 # ask it to end
```

- `on_output(text)` — the program emitted output (pre-render; see the bytes/text note below).
- `on_wait()` — the program is blocked waiting for input ("your turn"). Only in-process
  runners fire this; a pty/pipe has no readline boundary, so an observer reads the grid.
- `on_exit()` — the program ended (always fired exactly once, from a `finally`).

The three class attributes are the contract the Session reads: `encoding` tells it whether
to decode (a *byte source* sets it, e.g. `"utf-8"`; a *text source* leaves it `None`),
`returncode` carries the child's exit status, and `error` carries an exception so a blocking
caller can re-raise it. **Five implementations ship:**

- **`PtySource` (POSIX).** Hosts an external program on a real pseudo-terminal: `pty.openpty()`
  + `subprocess.Popen(..., start_new_session=True, close_fds=True)`, with the child's
  stdin/stdout/stderr wired to the slave fd and a `TIOCSWINSZ` ioctl for the size. The
  open→spawn section is wrapped so a failed spawn (e.g. command not found) closes both fds and
  re-raises instead of leaking the pty. Output is forwarded as a **byte-transparent latin-1
  str** (lossless: a stream observer can `.encode("latin-1")` to recover exact bytes); the
  Session decodes it for the screen by `encoding` (default UTF-8). `send_input` encodes
  keystrokes with the same encoding and writes to the master fd. `on_wait` is not fired.
- **`EngineSource` (any OS).** Wraps an in-process `runner(emit, readline)` callable on a
  thread. `emit` is `on_output`; the first time the runner calls `readline`, the source fires
  `on_wait()` and blocks on an input queue until `send_input` supplies a line — giving
  in-process programs a clean turn boundary a pty can't. It is a *text source* (`encoding`
  None). A runner exception is captured into `error`. `stop()` pushes a sentinel that makes a
  blocked `readline()` raise an internal `_StopRunner` (a `BaseException`, so a runner's
  `except Exception` can't swallow it) and unwind cleanly — so `Session.stop()` can stop a
  runner that is waiting for input. (A runner busy *elsewhere* — compute/sleep — can't be
  force-stopped; its thread is a daemon and won't block process exit.)
- **`CastSource` (any OS).** Replays a recorded asciinema `.cast` session — the "recorded
  session" producer. A *text source*. It emits the recorded output events with their original
  timing (`speed` multiplier; `idle_time_limit` caps long pauses; `loop` repeats), so a
  recording streams through the exact same pipeline a live program would — which also makes a
  render *reproducible*. `stop()` is prompt even mid-pause: the inter-event wait is on a
  `threading.Event` that `stop()` sets. It sizes itself from the recording header
  (`.width`/`.height`) so the caller can size the Terminal first. Input is ignored. Formats:
  **v2** (newline-delimited JSON — a header `{"version":2,"width":..,"height":..}` then
  `[time, code, data]` events, replaying only `"o"` output events) and compact **v1**
  (`{"version":1,"width","height","stdout":[[delay,data],...]}`). Untrusted-input bounds:
  dimensions clamped to `MAX_CAST_DIM` (1000), v2 line reads capped at `MAX_CAST_LINE` (1 MiB),
  and the unstreamable v1 whole-file `json.load` refused above `MAX_CAST_FILE` (16 MiB).
- **`PipeSource` (any OS).** Hosts an external program over plain pipes (`subprocess` with
  `stdin/stdout`, `stderr`→stdout, `bufsize=0`) — no pty. The "non-pty Source" (`--no-pty`),
  byte-transparent like `PtySource`. Caveat: with no tty the child detects it isn't
  interactive, so many programs block-buffer output and skip prompts/raw mode; it suits
  cooperative, line-oriented programs. Cross-platform and dependency-free.
- **`ConPtySource` (Windows).** Hosts a program on a Windows pseudo-console (ConPTY) via
  `pywinpty` (the `win` extra). The Windows counterpart to `PtySource`. ConPTY emits ANSI/
  VT100+ and `pywinpty` returns already-decoded `str`, so it is a *text source* and pairs with
  `PyteTerminal` (not the VT52 model). **Written against the documented `PtyProcess` API but
  not yet exercised on real Windows — provisional** (finishing it is open work — see
  [HISTORY.md](HISTORY.md)).

**Shared reader loop.** The three subprocess/pty sources (`PtySource`, `PipeSource`,
`ConPtySource`) all run the same daemon-thread loop, so it lives once in `Source._pump`:
pull chunks from a `read_one()` closure until it returns `""` (EOF), forward each to
`on_output`, then in a `finally` reap the child's exit status (into `returncode`) and fire
`on_exit`. Each source supplies only a small `read_one()` (its read call, EOF handling, and
whether to decode) and the `wait()` form. `EngineSource` and `CastSource` have genuinely
different loops (turn-based queue; timed replay) and keep their own.

Adding a new byte producer (a telnet stream, a SSH channel) means implementing this one tiny
interface; nothing else changes — as `CastSource`, `PipeSource`, and `ConPtySource` (each
added later with no other module touched) show.

### 2.2 Terminal backends — `terminal.py`, `pyte_terminal.py`

The Terminal models the glass. Two backends ship behind **one duck-typed read interface** that
a Session and the renderers rely on:

```
cols, rows           # fixed dimensions (ints)
cx, cy               # cursor column/row
write(text)          # the hosted program's output goes here
snapshot()           # whole screen as one "\n"-joined string
rows_text()          # list of row strings
view_rows(offset=0)  # `rows` lines scrolled back `offset` into history (0 = live)
max_scroll()         # how many scrolled-off lines are available
clear()              # blank the grid, home the cursor
```

Both are thread-safe (an `RLock`): the program thread writes while a render thread reads.
There is no shared base class or `Protocol` — with only two implementations the implicit
contract above (documented here) is lighter than an ABC, and the codebase is otherwise
annotation-free.

- **`Terminal` (VT52 spirit, zero deps).** A fixed grid. Printable text advances the cursor
  with wrap + scroll. Control chars: `CR`, `LF` (scroll at the bottom), `BS`, `FF` (`clear`),
  `TAB` (8-column stops). VT52 escapes honored: `ESC H` (home), `ESC J` (erase to end of
  screen), `ESC K` (erase to end of line), `ESC Y row col` (direct cursor address, bytes
  offset by 32), and `ESC A/B/C/D` (cursor up/down/right/left, bounds-clamped). It keeps
  **scrollback** — lines that scrolled off the top, the hardcopy "paper roll" — purely as a
  viewing aid (`max_scroll`/`view_rows`); the program never sees it. Right for the 1970s
  PDP-10 programs tappty was born hosting; wrong for anything that speaks modern ANSI.
- **`PyteTerminal` (full ANSI/VT100+, the `ansi` extra).** Wraps the `pyte` library behind the
  *same* read interface, so it drops in wherever a `Terminal` goes (`Session(PyteTerminal())`,
  `tapterm --ansi`) with no change to Session or renderers. It uses `pyte.HistoryScreen` +
  `pyte.Stream`, so it gets color/cursor-addressing/line-and-char edits *and* scrollback
  (read non-mutatingly from `history.top`, so the program keeps writing to the live screen
  while a renderer views older lines). It is **encoding-agnostic** — it renders whatever
  characters the Session hands it (Unicode included). `pyte` is imported lazily (LGPLv3, fine
  as a separately-installed optional backend). This is the "b-full" backend the design always
  anticipated and the prerequisite for hosting a Windows ConPTY (which emits VT100+).

Backend selection is the caller's (`Session(PyteTerminal(...))`) or the CLI's (`--ansi`); on
Windows the CLI auto-enables ANSI for the ConPTY path (§4). Both validate `cols/rows >= 1` at
construction, so a 0-sized grid can't be built and crash on the first write.

### 2.3 Session — `session.py`

The hub. It holds a Terminal and a Source, wires the source's three callbacks to the Terminal
and the taps, and exposes the observe/control contract every client speaks.

**Observe taps** (subscribe to taste; each returns the callback so it can be removed with the
matching `off_*`):

- `on_stream(cb(text))` — **tap 1: raw program output**, pre-render, temporal. For a byte
  source this is byte-lossless (a latin-1 transport); it is the program's exact bytes.
- `on_frame(cb())` — **tap 2: the grid changed.** Call `snapshot()` to read it. The grid is
  the output **decoded** to characters.
- `on_event(cb(name, info))` — **tap 3: events.** `WAIT` (blocked on input), `BELL`, `CLOSED`,
  `DRIVER {who}` (the stick changed hands), `ERROR {where, error}` (a program/runner failure,
  or an observer callback that raised).

**Bytes vs characters (the decode).** The two output taps are deliberately different views:
a stream observer sees the program's exact bytes; the screen (the grid, `snapshot()`, a
renderer, the bus `FRAME`) is those bytes decoded to characters. The Session owns the one
decode — an *incremental* decoder (so a multibyte char split across reads is handled),
created in `start()` from `self.source.encoding` (UTF-8 by default for byte sources; `None`
for text sources, which are passed through). On `_exit` the decoder is flushed
(`decode(b"", final=True)`) so a stream ending on a partial multibyte sequence still renders
its final `�`. `encoding="latin-1"` makes the screen byte-transparent too.

**`snapshot()` shape** — the tap-2 / bus-`FRAME` payload, a plain dict:

```python
{"rows": [str, ...], "cx": int, "cy": int, "cols": int, "rows_n": int}
```

(It is a dict rather than a typed object because it crosses the bus's JSON boundary, where a
type wouldn't survive.)

**Observer isolation.** Output and frame observers are dispatched through `_fanout`, which
catches a misbehaving callback, emits an `ERROR` event as a breadcrumb, and keeps going — one
bad client can't kill the output path for everyone. Event observers are dispatched
defensively too (and never via `_fanout`, so an `ERROR` for a failing observer can't recurse).

**Control.**

- `send_input(text, by=None)` — inject input. `by=None` is trusted/internal; a named
  controller's input is applied only while it holds the stick. Returns whether it was applied.
- `feed_key(ch, by="local", auto_take=True)` / `feed_text` — interactive keystrokes: local
  echo + line assembly, sent on Enter; backspace edits the buffer. `auto_take` means typing
  implicitly grabs the stick (the local human preempts). Local echo goes through `_echo_local`,
  which writes to the grid **and fans out a frame** (so a remote renderer sees typed characters
  immediately) but not to the stream tap (local echo isn't program output).
- `echo(text)` — show injected text on the screen and to observers (so a watcher sees what a
  remote controller "typed"); routed through the same protected fan-out.

**The talking stick (control arbitration).** Exactly one controller "drives" (holds the
keyboard) at a time:

- `claim_control(name, role="ai")` — register a controller; the first to claim becomes the
  driver. `has_controller(name)` reports registration; `has_control(name)` reports driving.
- `take(name)` — grab the stick, courtesy-gated: a `human`/`interactive` controller can
  preempt anyone; an `ai` can take only a free stick or one held by another non-human.
- `release(name)` / `drop_controller(name)` — give it up / deregister (auto-releases if held).

This is what makes shared control safe — the line buffer is never raced because only the
driver's keys register.

**Lifecycle.** `start()` builds the decoder and starts the source. `run_in_thread(runner)`
wraps a bare runner as an `EngineSource` and starts (non-blocking). `run_blocking(runner)`
starts and joins the source thread, then re-raises `source.error` if the program failed.
`stop()` stops the source and briefly joins its thread — the *owning* teardown path (a
renderer that started the program calls it on exit; a non-owning view does not).

### 2.4 The bus — `bus.py`

The taps and control are in-process. `BusServer` exposes the **same** contract over a
Unix-domain socket *or* TCP, and `BusClient` is the other end — so a session running in one
process can be observed and driven from another (a logger, a remote renderer, an automated
client). One server = one session, N clients.

**Wire format.** Newline-delimited text frames: `VERB[ payload]\n`. The payload is JSON for
most verbs, or rest-of-line literal text for `LINE`/`CMD`. Frames are read with a size cap
(`MAX_FRAME`, 64 KiB) on **both** ends; an oversized frame drops the connection.

**Protocol.**

| client → server | meaning | reply |
|---|---|---|
| `HELLO <json>` | identify `{role, name, token?}` | `OK {name, driver}` \| `DENIED` |
| `SNAP` | request the current grid | `FRAME <snapshot>` |
| `INFO` | session info | `INFO <snapshot + done, driver, waiting>` |
| `SUB` | subscribe to pushed `OUT`/`FRAME`/`EVENT` | `OK` |
| `LINE <text>` | inject a line (needs the stick) | — \| `DENIED` |
| `CMD <text>` | send a line, capture output to the next prompt | `RESP <json>` \| `DENIED` |
| `KEY <json-string>` | inject raw keystrokes (JSON-encoded so ctrl chars survive) | — \| `DENIED` |
| `TAKE` / `RELEASE` | grab / drop the talking stick | `OK`/`DENIED {driver}` |

| server → client (pushed, if subscribed) | meaning |
|---|---|
| `OUT <json-string>` | a raw output chunk (tap 1 — exact bytes) |
| `FRAME <snapshot>` | the grid changed (tap 2 — decoded screen) |
| `EVENT <json>` | `{name: WAIT\|BELL\|CLOSED\|DRIVER\|ERROR, ...}` (tap 3) |

So the bytes/characters split carries over the wire: `OUT` is raw bytes, `FRAME`/`SNAP` is the
decoded screen. The protocol is identical over either transport.

**Server internals.** A daemon accept thread spawns one daemon serve thread per connection.
Per-connection state is a small `@dataclass _Conn(name, lock, sub, role, claimed, authed)`;
verbs dispatch through a `{verb: handler}` table (`HELLO` is handled specially, before the
auth gate; unknown verbs are ignored — forward-compatible). The send lock per connection
serializes concurrent pushes.

**`CMD` is the synchronous primitive** an automated driver needs: send a line and get back
exactly its output up to the program's next prompt. Each in-flight `CMD` is a
`@dataclass _Capture(buf, ev, size, truncated, completed, cancelled)`. Output is accumulated
into `buf` (byte-bounded by `MAX_CAPTURE`, 1 MiB; `truncated` flags drops). The capture's
event is set when a `WAIT`/`CLOSED` arrives (`completed=True`) or when `stop()` shuts the
server down (`cancelled=True`, but only on a capture that hasn't completed). The reply's
`timeout` is `not (completed and not cancelled)` — so a client can distinguish *reached the
prompt* (clean) from *timed out mid-command* from *interrupted by shutdown*. `BusClient.cmd`
raises `TimeoutError` rather than return partial output as if complete.

**Transports & addressing.** `_resolve(addr)`: a `(host, port)` tuple → TCP (works anywhere,
incl. Windows where `AF_UNIX` is absent); anything else → a Unix-socket path (and a clear
error if the platform has no `AF_UNIX`). See §8 for the security posture (owner-only socket,
loopback-only TCP, optional token).

**Lifecycle.** `start()` registers the three session taps, binds/listens, and starts
accepting. `stop()` is the mirror and is restart-safe: it detaches the taps, wakes any pending
`CMD` captures, drops all client connections (closing sockets and releasing any stick they
held), closes and clears the listener, and unlinks the Unix socket path. A second `start()`
while running is a no-op; `start()`/`stop()` cycles are clean.

**`BusClient`.** A background reader thread puts every `(verb, payload)` on `inbox`. It is
**single-consumer**: `wait_for(verb)` drains the inbox until a match, discarding intervening
messages — for one request/reply at a time before subscribing, not concurrent callers. A
subscriber must drain `inbox` (it is unbounded). `send()` is a low-level string-frame API that
rejects non-`str` payloads and embedded newlines (which would inject frames).

### 2.5 Renderers — `curses_ui.py` (CUI), `pygame_ui.py` (GUI)

Each is a Session client exposing `run(session, runner, title=…)`: start the hosted program,
then loop — read the grid, draw it, forward keystrokes. Both are *owning* renderers: they call
`session.stop()` on exit (in a `finally`), so closing the window stops the hosted program.

- **`curses_ui`** draws a **viewport** into the fixed model: the whole 80×24 when the real
  terminal is big enough, a cursor-following sub-rectangle when it's smaller, plus a status
  line. The geometry is a pure, unit-tested function — `viewport(model_w, model_h, screen_w,
  screen_h, cx, cy, status=1) → (ox, oy, vw, vh)` — so resize never touches the model. Input
  maps Enter/Backspace/printable ASCII to the Session; arrows/function keys are ignored;
  `Ctrl-]` force-quits.
- **`pygame_ui`** draws a green-phosphor grid in a monospace font with a blinking block cursor.
  Glyphs are rendered lazily and cached (any Unicode the font has, not a fixed ASCII range).
  Scrollback is mouse-wheel / PageUp-PageDown; typing snaps back to live. Optional per-second
  text + PNG snapshots (and `F12` on demand) let an automated observer watch the same session;
  `max_seconds` is a hard loop cap for scripting/tests, `exit_when_done` closes when the
  program ends. `fps` is validated `>= 1`.

A third renderer (arcade, web, …) is the same shape; nothing else needs to know.

### 2.6 The compositor — `compositor.py`

Tiles several panels in one pygame window. A `TerminalPanel` draws over a **pluggable
backing**, and both backings present the same tiny interface — `grid()` (returns the snapshot
dict), `feed_key`, `has_stick`, `toggle_stick`, `focus`, `close` — so a panel doesn't care
where its bytes come from; local and remote sessions tile together:

- **`SessionBacking`** — an in-process Session. A *non-owning view*: `close()` is a no-op (the
  session may outlive the panel or be driven elsewhere). The local operator types only while it
  explicitly holds the stick (`toggle_stick`, bound to **F2**); `focus()` never grabs control.
- **`BusBacking`** — a *remote* session over the bus socket. Subscribes for `FRAME` snapshots
  and forwards keystrokes as `KEY`; tracks the remote driver and adopts the server-assigned
  (possibly uniquified) name from the `HELLO` `OK`; takes an optional `token`. It paces queued
  frames a few per tick instead of jumping to the newest, so a remote program's output scrolls
  in like a live terminal.

Rendering: a shared `DrawCtx` caches a per-size glyph atlas and the fit font size, keyed on
*(tile size, grid size)* so a non-80×24 cast/terminal fits correctly. Each tile supports mouse
**pan + zoom** (wheel zooms the font, left-drag pans, right-click resets to fit); the default
is the largest font at which the whole grid fits the tile. Keys route to the focused tile (the
talking stick, per tile); `Tab` cycles focus, `Esc` quits, `fps` is validated `>= 1`.

---

## 3. Concurrency & threading model

tappty is multithreaded but the rules are small and deliberate:

- **One source thread runs the program.** `_pump`'s reader (pty/pipe/ConPTY), `EngineSource`'s
  runner, or `CastSource`'s replay each run on a single daemon thread and call
  `Session._output` / `_wait` / `_exit`. Because `_output` is called only from that one
  thread, the incremental decoder is accessed single-threaded — no lock needed there.
- **Terminal writes are serialized.** `_output`, `_echo_local`, and `echo` take `Session._lock`
  around `term.write`, and the Terminal additionally locks itself (an `RLock`). Reads
  (`rows_text`/`snapshot`/`view_rows`) take the Terminal lock. So the grid is always read and
  written consistently across the source thread, a renderer's main thread, and bus serve
  threads.
- **The bus has its own lock.** `BusServer._lock` guards `_conns` and `_captures`; each
  connection has a per-send lock. Serve threads call session methods (`snapshot`, `send_input`,
  `take`/`release`, `feed_key`, `echo`).
- **The talking-stick state is not separately locked.** `_controllers`/`driver` mutations
  (`claim`/`take`/`release`) are plain dict/attribute writes. This is acceptable under the
  trusted-local, low-contention assumption (one driver at a time, few controllers); it is a
  conscious simplicity choice, not a hardened concurrent structure.
- **All worker threads are daemons.** A renderer/`run_blocking` joins with a short timeout, but
  a stuck source thread never blocks process exit.

---

## 4. The `tapterm` program — `cli.py`

A thin front-end: build a Source, host it in a `Session` with a Terminal backend, hand the
Session to a renderer. The pieces it wires:

- **Mode** (mutually exclusive): `--cui` (curses, anywhere), `--gui` (pygame, needs a display),
  `--headless` (run to completion, print the final screen — for scripting/CI). With no flag it
  picks GUI only when pygame is importable **and a display is available** (`_display_available`:
  native on Windows/macOS; `DISPLAY`/`WAYLAND_DISPLAY`/`SDL_VIDEODRIVER` on other POSIX), else
  CUI — so plain `tapterm` over SSH/cron falls back to CUI instead of failing in pygame.
- **Terminal backend** (`_make_terminal`): the VT52 `Terminal`, or `PyteTerminal` for `--ansi`
  (errors clearly if `pyte` is missing). ANSI is auto-enabled on the Windows ConPTY path, since
  ConPTY emits VT100+ the VT52 grid would mangle.
- **Source** (`_make_source`): `PipeSource` for `--no-pty`, `ConPtySource` on `os.name == "nt"`,
  else `PtySource`; or `CastSource` for `--cast` (with `--speed`/`--loop`).
- **Other flags:** `--cols`/`--rows` (validated positive), `--snapshot`, `--exit-when-done`,
  `--title`. With no command it hosts `$SHELL`.
- **Exit code:** `--headless` returns the child's exit status (`source.returncode or 0`), so it
  is honest in CI rather than always 0.

---

## 5. Module map

| Module | Role | Deps |
|--------|------|------|
| `terminal.py` | the fixed-size VT52 character grid model | none |
| `pyte_terminal.py` | `PyteTerminal` — full-ANSI/VT100+ backend, drop-in for `Terminal` | `pyte` (deferred; `ansi` extra) |
| `source.py` | `Source` base (+ `_pump`) and the 5 sources (pty / engine / cast / pipe / ConPTY) | stdlib `pty`/`subprocess`/`json`; `pywinpty` (deferred; `win` extra) |
| `session.py` | Session: observe taps, control, talking stick, the bytes↔chars decode | terminal, source |
| `bus.py` | `BusServer` / `BusClient` — the contract over a unix socket or TCP | stdlib `socket`/`hmac` |
| `compositor.py` | multi-panel window + `SessionBacking`/`BusBacking` | pygame (deferred), curses_ui, bus |
| `curses_ui.py` | CUI renderer + the pure `viewport()` | stdlib `curses` (deferred) |
| `pygame_ui.py` | GUI renderer | pygame (deferred) |
| `cli.py` | the `tapterm` program | session, terminal, source |
| `__init__.py` | public API | — |

**Optional deps are deferred** — `pygame`, `curses`, `pyte`, and `pywinpty` are imported
*inside* the functions/constructors that need them, never at module top. So `import tappty`
works with none of them installed (verified under a bare interpreter), and `tapterm --cui` /
`--headless` need no display. The extras: `gui` = pygame-ce, `ansi` = pyte (`PyteTerminal`),
`win` = pywinpty (`ConPtySource`, Windows only), `dev` = pytest + ruff.

---

## 6. What is *not* here (extraction boundary)

tappty was carved out of the *SIXBIT FORTRAN 66* project's `sbterm`. Two things were
deliberately left behind because they are game-specific, not terminal-generic:

- **The DECWAR galaxy view** (`draw_galaxy` / `GalaxyPanel` in the original compositor) — a
  star-map renderer tied to the game's universe snapshot and symbol table.
- **The DECWAR runners** (`decwar_runner` / `bot_runner` / `decwar_script_runner` in the
  original session) — factories that build an `EngineSource` around the game engine/bot.

Both are now consumers that *use* tappty's seams (a `GalaxyPanel` is just another panel `kind`;
a game runner is just an `EngineSource`), so the parent project can layer them back on top
without tappty depending on the game. The compositor's `run()` dispatches panels by their
`.kind`, so dropping `GalaxyPanel` left it fully generic.

---

## 7. Testing

The suite (87 in the full environment; the GUI and ANSI tests skip cleanly without their
optional deps) exercises the model and the contract through real paths, not mocks:

- **Model:** `test_term` (VT52 cursor/scroll, the escapes, scrollback bounds), `test_pyte_terminal`
  (SGR/cursor-address/erase/Unicode/scrollback; skips without pyte).
- **Session:** `test_session_bus`, `test_talking_stick`, `test_session_echo` (taps, control,
  the stick, local-echo frames).
- **Bus:** `test_bus_socket` (round-trip over a real socket + lifecycle: tap-unsubscribe,
  client drop, restart, capture-wake), `test_bus_tcp` (TCP transport), `test_bus_cmd`
  (synchronous CMD), `test_bus_security` (token auth, loopback-only bind, newline injection,
  safe socket unlink, capture cap, malformed/non-string `HELLO`).
- **Sources:** `test_pty_source` (a real subprocess on a pty; POSIX-skip on Windows),
  `test_pipe_source` (plain pipes + that `ConPtySource` is import-guarded), `test_source_encoding`
  (the bytes/characters split, the `latin-1` knob, partial-multibyte flush at EOF),
  `test_cast_source` (v1/v2 replay, timing, clamps, `stop()`).
- **Error paths:** `test_error_handling` (child exit-code propagation, observer-failure
  isolation, runner-error re-raise, CMD timeout, pty spawn cleanup, fps/dimension validation,
  headless display default, stopping a blocked engine runner).
- **Pure math:** `test_curses_viewport`, `test_compositor_view`.
- **Renderers:** `test_compositor_backings` (the panel-backing data contract);
  `test_gui_smoke` drives the real `pygame_ui.run` and the compositor to completion under the
  SDL `dummy` driver (no display), so every blit/draw/flip executes — deterministically, via a
  `CastSource` replay. It runs wherever `pygame` is installed and *skips cleanly* where it
  isn't, so it never breaks the pygame-free path. (Caveat: that clean skip cuts both ways —
  dropping `pygame-ce` from CI would silently turn this test green-by-skipping, not red.)

What is still by-eye only is pixel-level *fidelity* (does it look right) — the smoke test proves
the draw path runs and the right grid data reaches it, not that the phosphor is pretty. For the
by-eye pass: under WSLg (`DISPLAY`/`WAYLAND_DISPLAY` set, SDL auto-picks x11) both renderers
draw correctly, `tapterm --cast rec.cast --gui` is the easiest reproducible visual check, and
`--snapshot` writes a reviewable PNG (harmless EGL/MESA warnings on stderr are failed
hardware-GL probing — SDL falls back to software). The Windows `ConPtySource` path is unverified
(no Windows runner; finishing it is open work — see [HISTORY.md](HISTORY.md)).

---

## 8. Security / trust model

The bus is a **terminal control plane**: a connected client can read the screen and, holding
the talking stick, inject input — i.e. terminal read/write as the tappty user. It is
**trusted-local**, not a boundary against a hostile network. The defenses:

- **Unix socket (default-safe):** the socket *file* is `0600`, so only the owner UID can
  connect — that file mode is the actual connect gate, the auth. When tappty creates the parent
  directory it also makes it `0700` (defense-in-depth); if you point the path at an existing
  shared directory its permissions are left untouched, so the `0600` socket file is what
  protects you there.
- **TCP:** bound to **loopback only**; binding a non-loopback host raises unless
  `allow_remote=True` is passed explicitly. Loopback isn't user-isolated, so on a shared box set
  a `token`.
- **`token` (optional):** a non-empty string shared secret presented in `HELLO` (constant-time
  compared via `hmac`; an empty token is rejected at construction, and a non-string token can't
  match); a client without it is denied and dropped. It's a *casual gate sent in the clear* —
  **not** transport security; tunnel over SSH/TLS for an untrusted network.
- **Input validation:** `HELLO` must be a JSON object (invalid JSON or a non-object is denied,
  not silently accepted as an anonymous observer); `KEY` must decode to a JSON string;
  `BusClient.send` rejects newline-injected frames.
- **DoS bounds:** protocol frames are read with a size cap (`MAX_FRAME`) on **both** ends;
  `CMD` captures are byte-bounded (`MAX_CAPTURE`, with a `truncated` flag).
- **Untrusted `.cast` files:** width/height are clamped, v2 line reads are byte-bounded, and the
  unstreamable v1 whole-file load is refused above `MAX_CAST_FILE` — so a malicious recording
  can't drive a huge grid allocation or load an unbounded file.

Not in scope as bugs: the subprocess path launches `argv` with `shell=False` (no shell
injection), and `--snapshot` writes exactly where the user asked (user-directed output, not a
privilege boundary). Full transport auth (TLS/mTLS) is intentionally out of scope for this
toolkit; the recommendation is a private Unix socket, or loopback+token behind an SSH tunnel.

---

## 9. Known limitations (deliberate, not bugs)

Conscious scope choices, recorded so they aren't mistaken for defects:

- **Monochrome render — no SGR attributes.** `PyteTerminal` parses ANSI position/erase/edit
  correctly, but the read interface exposes only text; the renderers draw one phosphor color.
  So `--ansi` gives text/cursor fidelity, not color/bold/inverse. A future `styled_rows()` /
  `cells()` API could expose attributes without changing `rows_text()`.
- **Single-cell Unicode.** Both Terminal models treat each Python code point as one cell, and
  renderers blit one glyph per cell. CJK full-width, emoji, and combining marks can drift or
  overwrite neighbors. Faithful width would need a `wcwidth`-style helper in the model and
  renderers.
- **Line-oriented input.** Renderers forward Enter/Backspace/printable text (and pygame's
  scrollback keys); arrows, function keys, Esc, and Ctrl-combos are not yet mapped to VT
  sequences for the hosted program. Right for the toolkit's line-oriented heritage; hosting full
  interactive TUIs would need a renderer→session key map (pairs naturally with the full-ANSI
  backend).
- **Frame fan-out is per-chunk.** A subscribed bus client gets a full screen snapshot on every
  output chunk. Fine at the default 80×24; a busy remote dashboard would want frame coalescing /
  rate-limiting (send the latest at a bounded tick, drop stale frames).
- **`BusClient` is single-consumer.** `wait_for()` drains the inbox until a matching verb,
  discarding others; it's for one request/reply at a time before subscribing, not concurrent
  callers or overlapping requests. A subscriber must drain `inbox` (it is unbounded).
- **`EngineSource.stop()` can't interrupt a busy runner.** It unblocks a runner waiting in
  `readline()`, but a runner in a compute/sleep loop can't be force-stopped (you can't safely
  interrupt arbitrary in-process Python). Its thread is a daemon, so it never blocks exit.
- **Windows is provisional.** The platform-bound surface is small and isolated to the Source
  seam — proof of the §1 claim. Only `PtySource` (POSIX `pty`/`termios`/`fcntl`) and the
  Unix-socket bus transport are POSIX-specific; the core (Terminal/Session/talking-stick),
  `EngineSource`, `CastSource`, `PipeSource`, the renderers, and the TCP bus are already
  cross-platform. So Windows hosting needs only a Windows Source: `ConPtySource` (ConPTY via
  pywinpty, the `win` extra) exists and `cli.py` selects it — but it has **never run on real
  Windows**, so it's provisional until exercised. (The stdlib also lacks `curses` on Windows;
  the CUI would need `windows-curses`.) Finishing Windows — validate `ConPtySource`, add a
  Windows CI lane, broaden the `pyproject` classifiers — is open work (see [HISTORY.md](HISTORY.md)).
