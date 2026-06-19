# tappty — design document

How `tappty` is structured and why. This is the architecture companion to the
[README](../README.md) (which is the usage guide); it's for someone modifying the toolkit.

---

## 1. The one idea

A terminal program's bytes should flow through a single pipeline where **every consumer is
equal**: the screen renderer, an out-of-process logger, and an automated driver are all
just clients of the same observe/control contract. Get that right and a human and a bot
can watch — and take turns driving — the *exact same* session, with no special-casing.

So tappty is deliberately split into four decoupled parts, each ignorant of the others'
nature:

```
   a program                                          consumers (all equal)
  ┌─────────┐   bytes    ┌──────────┐  grid    ┌─────────┐  observe   ┌──────────────┐
  │ Source  │──────────▶ │ Terminal │ ───────▶ │ Session │ ─────────▶ │ curses_ui    │
  │ (pty /  │            │  (glass) │          │ (taps + │            │ pygame_ui    │
  │  engine)│ ◀──────────│          │ ◀─────── │ control)│ ◀───────── │ bus clients  │
  └─────────┘   input    └──────────┘  write   └─────────┘  control   │ compositor   │
                                                                       └──────────────┘
```

- **Source** produces bytes and accepts input — it does not know what a screen is.
- **Terminal** models the glass — it does not know where bytes come from or who draws it.
- **Session** fans output to observers and routes input back — it does not know if a
  consumer is a window, a socket, or an AI.
- **Renderers / bus clients** consume the contract — they do not know each other exist.

---

## 2. The parts

### 2.1 Source — `source.py`

A `Source` is "something that produces terminal output and consumes input." It is driven
by three callbacks supplied at `start(on_output, on_wait, on_exit)` and accepts
`send_input(text)`. Five implementations ship:

- **`PtySource`** — hosts an arbitrary external program on a real pseudo-terminal
  (`pty.openpty` + `subprocess`), forwarding the child's **raw bytes** to `on_output` (as a
  byte-transparent latin-1 str — lossless) and writing input to the master fd. This is the
  "tap a pty" core — it lets you observe and control *any* terminal program. It declares a
  wire `encoding` (default UTF-8) the Session uses to decode those bytes for the *screen*
  (see §2.3). (`on_wait` is not fired: a pty has no readline boundary, so an observer reads
  the stream/grid instead.)
- **`EngineSource`** — wraps any in-process `runner(emit, readline)` callable on a thread.
  When the runner calls `readline`, the source fires `on_wait()` ("your turn") and blocks
  until `send_input` supplies a line — giving in-process programs a clean turn boundary a
  pty can't.
- **`CastSource`** — replays a recorded asciinema `.cast` session (v2 NDJSON, or compact
  v1): it emits the recorded output events with their original timing (scaled by `speed`,
  idle gaps optionally capped; `loop` repeats) into the same `on_output`. No live program
  and no pty — just bytes plus a clock — so a recording streams through the exact same
  Terminal/Session/renderer pipeline a live program does, which also makes a render
  *reproducible*. It sizes itself from the recording header (`.width`/`.height`); input is
  ignored and `on_wait` is not fired (a recording has no input boundary, like a pty). This
  is the "recorded session" producer the seam always anticipated.
- **`PipeSource`** — hosts an external program over plain pipes (`subprocess` with
  stdin/stdout, no pty). Cross-platform (incl. Windows) and dependency-free, but the child
  sees no tty, so it suits cooperative/line-oriented programs (`--no-pty`). The "non-pty
  Source" of [WINDOWS.md](WINDOWS.md).
- **`ConPtySource`** — hosts an external program on a Windows pseudo-console (ConPTY, via
  `pywinpty`, the `win` extra) — the Windows counterpart to `PtySource`. ConPTY emits
  ANSI/VT100+, so it pairs with `PyteTerminal`, not the VT52 model. *Written but not yet
  exercised on real Windows (see [WINDOWS.md](WINDOWS.md)).*

Adding a new byte producer means implementing this one tiny interface; nothing else changes
— as `CastSource`, `PipeSource`, and `ConPtySource` (added later, no other module touched)
show.

### 2.2 Terminal — `terminal.py`

A fixed-size character grid (default 80×24) in the **VT52 spirit**: printable text
advances the cursor with wrap + scroll, the common control chars (CR/LF/BS/FF/TAB) work,
and a handful of VT52 escapes (home, erase-to-end, direct cursor address, cursor moves)
are honored. It keeps **scrollback** (lines that scrolled off the top) purely as a viewing
aid. It is thread-safe (the program thread writes while a render thread reads) and has
**zero rendering dependencies** — a renderer just reads `.grid` / `snapshot()` /
`view_rows(offset)`.

Fixed size is a feature, not a limitation: the hosted program stays sealed in its model;
making the real window bigger or smaller is a *render-side* concern (see viewport, below),
never a resize the program sees.

**Full-ANSI backend (`pyte_terminal.py`).** VT52 is right for the 1970s programs tappty
was born hosting and wrong for anything that speaks modern ANSI/VT100+ (color, cursor
addressing, line/char edits). `PyteTerminal` wraps the `pyte` library behind the *same*
read interface (`cols`/`rows`/`cx`/`cy`/`write()`/`snapshot()`/`rows_text()`/`view_rows()`/
`max_scroll()`), so it drops in wherever a `Terminal` goes (`Session(PyteTerminal())`,
`tapterm --ansi`) with no change to Session or renderers — scrollback included (it uses
`pyte.HistoryScreen`, exposing `view_rows(offset)`/`max_scroll()` like the VT52 paper roll).
`pyte` is optional (the `ansi` extra, imported lazily; LGPLv3). This is the "b-full" backend
the design anticipated, and the prerequisite for hosting a Windows ConPTY (which emits
VT100+).

### 2.3 Session — `session.py`

The hub. It holds a Terminal and a Source, and exposes the contract:

- **Observe taps** (subscribe to taste):
  - `on_stream(cb(text))` — **raw** program output, pre-render (byte-lossless via a latin-1
    transport, temporal): the program's exact bytes
  - `on_frame(cb())` — the grid changed; call `snapshot()` to read it. The grid is the output
    **decoded** to characters
  - `on_event(cb(name, info))` — `WAIT` / `BELL` / `CLOSED` / `DRIVER` / `ERROR` (a buggy
    observer or a failed program; observer exceptions are caught so one client can't kill
    the output path for the rest)
- **Bytes vs characters.** The two output taps are deliberately different views: a stream
  observer (a logger, an AI watching the byte stream) sees the program's exact bytes, while
  the screen (the grid, `snapshot()`, a renderer, the bus `FRAME`) is those bytes **decoded**
  to characters. The Session owns that decode — an incremental decoder keyed on the source's
  `encoding` (UTF-8 by default for byte sources; absent for text sources like `EngineSource`,
  whose output is already characters). So the terminal backends stay encoding-agnostic, and
  `encoding="latin-1"` makes the screen byte-transparent too.
- **Control:** `send_input(text, by=…)` injects input; `feed_key(ch)` / `feed_text` are
  interactive keystrokes (local echo + line assembly, sent on Enter).
- **The talking stick** (control arbitration): exactly one controller "drives" (holds the
  keyboard) at a time. `claim_control(name, role)`, `take(name)`, `release(name)`. The
  rule encodes courtesy: a human/interactive controller can preempt anyone; an AI can take
  only a free stick or one held by another non-human. This is what makes shared control
  safe — the line buffer is never raced because only the driver's keys register.

### 2.4 The bus — `bus.py`

The taps and control are in-process. `BusServer` exposes the *same* contract over a
Unix-domain socket *or* TCP: it subscribes to a Session's taps and pushes `FRAME`/`OUT`/event
messages to connected clients, and accepts `KEY`/`LINE`/`TAKE`/`RELEASE`/`SNAP`/`CMD` back.
The bytes/characters split carries over the wire: `OUT` is the program's **raw bytes**,
`FRAME`/`SNAP` is the **decoded** screen — so a client watching the stream gets exact bytes
and one watching the grid gets characters.
`BusClient` is the other end. This is the externalized form of the in-process taps — so a
session running in one process can be observed and driven from another (a logger, a remote
renderer, an automated client). One server = one session. The address is a filesystem path
(Unix socket) or a `(host, port)` tuple (TCP) — the latter works on Windows, where
`AF_UNIX` is absent; the protocol is identical either way. The bus is a control plane —
treat it as **trusted-local** (see §7).

### 2.5 Renderers — `curses_ui.py` (CUI), `pygame_ui.py` (GUI)

Each is just a Session client exposing `run(session, runner, title=…)`. They start the
hosted program, then loop: read the grid, draw it, forward keystrokes.

- **`curses_ui`** draws a **viewport** into the fixed model: the whole 80×24 when the real
  terminal is big enough, a cursor-following sub-rectangle when it's smaller, with a status
  line. `viewport()` is a pure function (and unit-tested) — resize never touches the model.
- **`pygame_ui`** draws a green-phosphor grid in a monospace font, with a blinking cursor,
  mouse-wheel/PageUp scrollback, and optional per-second text/PNG snapshots.

A third renderer (arcade, web, …) is the same shape; nothing else needs to know.

### 2.6 The compositor — `compositor.py`

Tiles several panels in one pygame window. A `TerminalPanel` draws over a **pluggable
backing**: `SessionBacking` (an in-process Session) or `BusBacking` (a *remote* session
over the bus socket). Both present the same tiny interface (`grid()`, `feed_key`, `focus`,
`close`), so a panel doesn't care where its bytes come from — local and remote sessions
tile together. Per-tile mouse pan/zoom; keys route to the focused tile (the talking stick
per tile). `BusBacking` paces queued frames into a smooth scroll instead of jumping to the
newest, so a remote program's output streams in like a live terminal.

---

## 3. The `tapterm` program — `cli.py`

A thin front-end: wrap a command in a Source, host it in a `Session`, hand the Session to a
renderer. Modes: `--cui` (curses, anywhere), `--gui` (pygame, needs the optional extra),
`--headless` (run to completion, print the final screen — for scripting/CI). With no flag it
picks GUI when pygame is importable *and a display is available*, else CUI. With no command
it hosts `$SHELL`. Two
backend/transport switches: `--ansi` selects `PyteTerminal` over the VT52 `Terminal`;
`--no-pty` hosts over `PipeSource` instead of a pty. The Source is chosen by platform —
`PtySource` on POSIX, `ConPtySource` on Windows — and `--cast` replays a recording instead.

---

## 4. Module map

| Module | Role | Deps |
|--------|------|------|
| `terminal.py` | the fixed-size VT52 character grid model | none |
| `pyte_terminal.py` | `PyteTerminal` — full-ANSI/VT100+ backend, drop-in for `Terminal` | `pyte` (deferred; `ansi` extra) |
| `source.py` | `Source` / `PtySource` (pty) / `EngineSource` (runner) / `CastSource` (.cast) / `PipeSource` (pipes) / `ConPtySource` (Windows ConPTY) | stdlib `pty`/`subprocess`/`json`; `pywinpty` (deferred; `win` extra) |
| `session.py` | Session: observe taps, control, talking stick | terminal, source |
| `bus.py` | `BusServer` / `BusClient` — contract over a unix socket or TCP | stdlib `socket` |
| `compositor.py` | multi-panel window + `SessionBacking`/`BusBacking` | pygame (deferred), curses_ui, bus |
| `curses_ui.py` | CUI renderer + the pure `viewport()` | stdlib `curses` (deferred) |
| `pygame_ui.py` | GUI renderer | pygame (deferred) |
| `cli.py` | the `tapterm` program | session, terminal, source |
| `__init__.py` | public API | — |

**Optional deps are deferred:** `pygame`, `curses`, `pyte`, and `pywinpty` are imported
*inside* the functions/constructors that need them, never at module top. So `import tappty`
works with none of them installed (verified), and `tapterm --cui` / `--headless` need no
display. The extras: `gui` = pygame-ce, `ansi` = pyte (`PyteTerminal`), `win` = pywinpty
(`ConPtySource`, Windows only).

---

## 5. What is *not* here (extraction boundary)

tappty was carved out of the *SIXBIT FORTRAN 66* project's `sbterm`. Two things were
deliberately left behind because they are game-specific, not terminal-generic:

- **The DECWAR galaxy view** (`draw_galaxy` / `GalaxyPanel` in the original compositor) — a
  star-map renderer tied to the game's universe snapshot and symbol table.
- **The DECWAR runners** (`decwar_runner` / `bot_runner` / `decwar_script_runner` in the
  original session) — factories that build an `EngineSource` around the game engine/bot.

Both are now consumers that *use* tappty's seams (a `GalaxyPanel` is just another panel
`kind`; a game runner is just an `EngineSource`), so the parent project can layer them back
on top without tappty depending on the game. The compositor's `run()` dispatches panels by
their `.kind`, so dropping `GalaxyPanel` left it fully generic.

---

## 6. Testing

87 tests exercise the model and contract through real paths: the Terminal model
(`test_term`), the full-ANSI backend (`test_pyte_terminal` — SGR/cursor-address/erase/
Unicode/scrollback, skips without pyte), Session taps + control + talking stick + local-echo
frames (`test_session_bus`, `test_talking_stick`, `test_session_echo`), the bus round-trip
over an actual socket and over TCP, plus duplicate-name handling (`test_bus_socket`,
`test_bus_cmd`, `test_bus_tcp`), a real subprocess on a pty (`test_pty_source`) and over
plain pipes (`test_pipe_source`, which also checks `ConPtySource` is import-guarded), the
bytes/characters encoding split (`test_source_encoding`), recording replay through the
pipeline (`test_cast_source`), error paths (`test_error_handling` — child exit-code
propagation, observer-failure isolation, runner-error re-raise, CMD timeout signaling, pty
spawn cleanup), bus hardening (`test_bus_security` — token auth, loopback-only TCP, newline
injection, safe socket unlink), the pure viewport/pan/zoom math (`test_curses_viewport`,
`test_compositor_view`), and the panel backings (`test_compositor_backings`).

The pygame **draw path** is now smoke-tested too (`test_gui_smoke`): it drives the real
`pygame_ui.run` and the compositor to completion under the SDL `dummy` video driver (no
display), so every blit/draw/flip executes — deterministically, via a `CastSource` replay
rather than a live subprocess. That test runs wherever `pygame` is installed and *skips
cleanly* where it isn't, so it never breaks the pygame-free path. What's still by-eye only
is pixel-level *fidelity* (does it look right) — the smoke test proves the path runs and
the right grid data reaches it, not that the phosphor is pretty.

---

## 7. Security / trust model

The bus is a **terminal control plane**: a connected client can read the screen and, holding
the talking stick, inject input — i.e. terminal read/write as the tappty user. It is
**trusted-local**, not a boundary against a hostile network. The defenses:

- **Unix socket (default-safe):** the socket *file* is `0600`, so only the owner UID can
  connect — that file mode is the actual connect gate, the auth. When tappty creates the
  parent directory it also makes it `0700` (defense-in-depth); if you point the path at an
  existing shared directory its permissions are left untouched, so the `0600` socket file is
  what protects you there.
- **TCP:** bound to **loopback only**; binding a non-loopback host raises unless
  `allow_remote=True` is passed explicitly. Loopback isn't user-isolated, so on a shared box
  set a `token`.
- **`token` (optional):** a non-empty shared secret presented in `HELLO` (constant-time
  compared; an empty token is rejected at construction); a client without it is denied. It's
  a *casual gate sent in the clear*, **not** transport security — tunnel over SSH/TLS for an
  untrusted network.
- **DoS bounds:** protocol frames are read with a size cap (`MAX_FRAME`) on **both** ends —
  server *and* client — (the server's own outbound messages are naturally small, bounded by
  per-read chunk sizes); `CMD` captures are byte-bounded (`MAX_CAPTURE`, with a `truncated`
  flag); and `BusClient.send` rejects newlines so a `LINE`/`CMD` payload can't inject frames.
- **Untrusted `.cast` files:** width/height are clamped and v2 line reads are byte-bounded;
  the unstreamable v1 path (whole-file `json.load`) is refused above `MAX_CAST_FILE`. So a
  malicious recording can't drive a huge grid allocation or load an unbounded file.

Not in scope as bugs: the subprocess path launches `argv` with `shell=False` (no shell
injection), and `--snapshot` writes exactly where the user asked (user-directed output, not
a privilege boundary). Full transport auth (TLS/mTLS) is intentionally out of scope for this
toolkit; the recommendation is a private Unix socket, or loopback+token behind an SSH tunnel.

---

## 8. Known limitations (deliberate, not bugs)

These are conscious scope choices, recorded so they aren't mistaken for defects:

- **Monochrome render — no SGR attributes.** `PyteTerminal` parses ANSI position/erase/edit
  correctly, but the read interface exposes only text (`rows_text`/`display`); the renderers
  draw one phosphor color. So `--ansi` gives text/cursor fidelity, not color/bold/inverse.
  A future `styled_rows()`/`cells()` API could expose attributes without changing
  `rows_text()`.
- **Single-cell Unicode.** Both Terminal models treat each Python code point as one cell, and
  renderers blit one glyph per cell. CJK full-width, emoji, and combining marks can drift or
  overwrite neighbors. Faithful width would need a `wcwidth`-style helper in the model and
  renderers.
- **Line-oriented input.** Renderers forward Enter/Backspace/printable text (and pygame's
  scrollback keys); arrows, function keys, Esc, and Ctrl-combos are not yet mapped to VT
  sequences for the hosted program. Right for the toolkit's line-oriented heritage; hosting
  full interactive TUIs would need a renderer→session key map (pairs naturally with the
  full-ANSI backend).
- **Frame fan-out is per-chunk.** A subscribed bus client gets a full screen snapshot on
  every output chunk. Fine at the default 80×24; a busy remote dashboard would want frame
  coalescing / rate-limiting (send the latest at a bounded tick, drop stale frames).
- **`BusClient` is single-consumer.** `wait_for()` drains the inbox until a matching verb,
  discarding others; it's for one request/reply at a time before subscribing, not concurrent
  callers or overlapping requests. A subscriber must drain `inbox` (it is unbounded).
