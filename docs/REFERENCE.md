# tappty — programming reference

The public API for using `tappty` as a library, with signatures, parameters, return values,
and examples. This is the *how to call it* companion to [DESIGN.md](DESIGN.md) (the *why* —
architecture, threading, the trust model) and the top-level [README](../README.md) (the
`tapterm` command). For terms like *tap*, *talking stick*, *byte source*, and *snapshot dict*,
DESIGN is the canonical explanation; this doc gives the calling details.

```python
from tappty import (
    Terminal, PyteTerminal,                                   # screen models
    Session,                                                  # the hub
    Source, PtySource, EngineSource, CastSource,              # byte/text producers
    PipeSource, ConPtySource, TtyrecSource, AnsSource, ThreeASource, replay_source,
    Recorder, export_ansi, export_3a, render_video,           # record/export/encode
    BusServer, BusClient,                                     # out-of-process observe/control
    curses_ui, pygame_ui, arcade_ui, compositor,              # renderers
)
```

`import tappty` works with no optional dependencies installed; `PyteTerminal` needs the
`ansi` extra (pyte), `pygame_ui` and the `compositor` need the `sdl` extra (pygame-ce),
`arcade_ui` needs the `gl` extra, `web_ui` needs the `web` extra (websockets) — `curses_ui`
uses only the stdlib `curses` — and `ConPtySource` needs the `win` extra
(pywinpty). Those are imported lazily, so you only pay for what you call.

---

## Contents

- [Quick recipes](#quick-recipes)
- [Shared contracts](#shared-contracts) — the snapshot dict, events, controller roles
- [Terminal backends](#terminal-backends) — `Terminal`, `PyteTerminal`
- [Sources](#sources) — `Source` and the built-in producers; writing your own
- [Session](#session) — taps, control, the talking stick, lifecycle
- [The bus](#the-bus) — `BusServer`, `BusClient`
- [Renderers](#renderers) — `curses_ui`, `pygame_ui`, `arcade_ui`, `web_ui`
- [Compositor](#compositor) — `TerminalPanel`, backings, `run`
- [Worked examples](#worked-examples)
- [Quick reference](#quick-reference)

---

## Quick recipes

**Host a shell in a terminal (curses):**

```python
from tappty import Session, Terminal, PtySource, curses_ui

sess = Session(Terminal())
sess.source = PtySource(["bash"])
sess.claim_control("local", "human")      # a human is at the keyboard
curses_ui.run(sess, None, title="bash")    # blocks until you quit (Ctrl-])
```

**Run a command to completion and read the final screen (no renderer):**

```python
from tappty import Session, Terminal, PtySource

sess = Session(Terminal(), source=PtySource(["ls", "-la"]))
sess.run_blocking()                        # runs until the child exits
print(sess.term.snapshot())                # the final 80x24 grid as text
```

**Observe and drive a session from another process (the bus):**

```python
# host process:
from tappty import Session, Terminal, PtySource, BusServer
sess = Session(Terminal(), source=PtySource(["python3", "-i"]))
BusServer(sess, "/run/user/1000/tappty.sock").start()
sess.start()

# driver process:
from tappty import BusClient
c = BusClient("/run/user/1000/tappty.sock").connect()
c.hello(role="ai", name="bot")
print(c.snap()["rows"])                    # observe the screen
print(c.cmd("print(6 * 7)"))               # drive: send a line, get its output
```

More in [Worked examples](#worked-examples).

---

## Shared contracts

A few shapes recur across the API.

### The snapshot dict

`Session.snapshot()` (and the bus `FRAME`/`SNAP`/`INFO` replies, and a backing's `grid()`)
return a plain dict describing the screen:

```python
{
    "rows":   ["...", ...],   # list[str], one per row, each `cols` wide (text consumers)
    "cells":  [[run, ...], ...],  # styled runs per row (color+attrs); the renderers draw these
    "cx":     int,            # cursor column (0-based)
    "cy":     int,            # cursor row (0-based)
    "cols":   int,            # grid width
    "rows_n": int,            # grid height
}
```

`INFO` adds `done` (bool), `driver` (str|None), and `waiting` (bool). It is a dict, not a
typed object, because it crosses the bus's JSON boundary.

### Events (`on_event` / bus `EVENT`)

A callback `cb(name, info)` receives:

| `name` | when | `info` |
|--------|------|--------|
| `WAIT` | the program is blocked waiting for input | `{}` |
| `BELL` | the program emitted `\a` | `{}` |
| `CLOSED` | the program ended | `{}` |
| `DRIVER` | the talking stick changed hands | `{"who": str \| None}` |
| `ERROR` | a program/runner failure, or an observer callback raised | `{"where": str, "error": str}` |

### Controller roles (the talking stick)

A controller registers a `name` with a `role`. Roles: `"human"` / `"interactive"` (can
preempt anyone) and `"ai"` (can take only a free stick or one held by a non-human). Exactly
one controller "drives" at a time; only the driver's input registers. See [Session control](#control--the-talking-stick).

---

## Terminal backends

The screen model. Two implementations share one read interface, so a Session and the
renderers work with either:

| attribute / method | type | meaning |
|--------------------|------|---------|
| `cols`, `rows` | `int` | fixed grid dimensions |
| `cx`, `cy` | `int` | cursor column / row |
| `write(text)` | — | feed the program's output in (the Session calls this) |
| `snapshot()` | `str` | whole screen as one `"\n"`-joined string |
| `rows_text()` | `list[str]` | one string per row |
| `view_rows(offset=0)` | `list[str]` | `rows` lines scrolled back `offset` into history (0 = live) |
| `cells(offset=0)` | `list[list[style.Cell]]` | same window, styled — `Cell(char, fg, bg, bold, italic, underline, strike, blink, reverse)` |
| `max_scroll()` | `int` | how many scrolled-off lines are available |
| `clear()` | — | blank the grid, home the cursor |

Both are thread-safe (an `RLock`): the program thread writes while a render thread reads.

### `Terminal(cols=80, rows=24, scrollback=5000)`

The built-in **VT52-spirit** model, zero dependencies. Honors wrap+scroll, `CR/LF/BS/FF/TAB`,
and the VT52 escapes `ESC H/J/K`, `ESC Y row col`, `ESC A/B/C/D`. Keeps `scrollback` lines of
history (the "paper roll"). Raises `ValueError` if `cols` or `rows` < 1.

### `PyteTerminal(cols=80, rows=24, scrollback=5000)`

The **full-ANSI/VT100+** backend (the `ansi` extra). A drop-in for `Terminal` with the same
read interface, backed by `pyte.HistoryScreen` — so it handles color/cursor-addressing/line
edits and keeps scrollback. Use it for programs that emit modern ANSI (`tapterm --ansi`).
Importing `pyte` is deferred to the constructor, so this raises `ModuleNotFoundError` if the
`ansi` extra isn't installed. Same `ValueError` on bad dimensions.

> Note: SGR attributes — color, **bold**, *italic*, underline, strikethrough, blink, inverse — are exposed via
> `cells()` and drawn by **all four renderers** (the GUI backends via the font + bg fills,
> `curses_ui` via `A_*` attributes + color pairs); the `cells()` cell carries pyte's
> `fg`/`bg`/`bold`/`italic`/`underline`/`strike`/`blink`/`reverse`. The bus carries color too —
> `snapshot()`/`FRAME` includes styled `cells` (`style.encode_row`), so a remote `BusBacking`
> panel renders in color. SGR faint/rapid-blink/conceal aren't modelled by pyte (curses also
> lacks strikethrough). See DESIGN §9.

### `style` — cell color helpers

`style.Cell(char, fg, bg, bold, italic, underline, strike, blink, reverse)` is what `cells()` returns; `fg`/`bg` are pyte color
strings (`"default"`, `"red"`, `"brightred"`, `"brown"` = yellow, or a 6-hex string from
256-color/truecolor). Helpers (no dependencies):

- **`rgb(color, bold=False)`** → an `(r, g, b)`, or `None` for `"default"` (the renderer
  substitutes its own phosphor color). `bold` brightens a *named* color.
- **`resolve(cell, fg_default=FG, bg_default=BG)`** → a cell's concrete `(fg, bg)` with
  `"default"` filled in and `reverse` (inverse video) applied.
- **`runs(row, …)`** → maximal same-style runs `(x, text, fg, bg, bold, italic, underline,
  strike, blink)`, for a renderer that draws a whole run at once.
- **`encode_row(row, …)`** → the same runs as JSON-able lists
  `[col, text, fg_hex, bg_hex, bold, italic, underline, strike, blink]` — the single wire
  encoding shared by `snapshot()`, the web renderer, and the bus `FRAME`.
- **`hex_rgb(rgb)`** → an `(r, g, b)` as a 6-digit hex string (no `#`).
- **`char_width(char)`** → display columns a character occupies: **2** for East-Asian
  wide/fullwidth (CJK and single-code-point emoji), **0** for a combining/format mark, else
  **1**. Used to skip the empty continuation cell `pyte` leaves to the right of a wide glyph
  (see [DESIGN.md](DESIGN.md) §9). Grapheme clusters are out of scope — `pyte` splits them upstream.

`style.FG` / `style.BG` are the phosphor defaults. Use these to write your own renderer.

---

## Sources

A `Source` produces terminal output and consumes input. Eight ship; you can write your own.

### The `Source` contract

```python
class Source:
    encoding = None      # wire encoding of raw output, or None if it already emits text
    returncode = None    # child exit status after on_exit (None if N/A)
    error = None         # exception that ended the program (None if clean)

    def start(self, on_output, on_wait, on_exit): ...
    def send_input(self, text): ...
    def stop(self): ...
```

`start()` begins producing on a background (daemon) thread and is handed three callbacks:

- `on_output(text)` — the program emitted output. For a *byte source* this is a
  byte-transparent latin-1 `str` (the Session decodes it for the screen by `encoding`); for a
  *text source* it's characters.
- `on_wait()` — the program is blocked waiting for input (fired by in-process runners only).
- `on_exit()` — the program ended (fired exactly once).

`send_input(text)` feeds input; `stop()` asks the program to end. The Session reads the three
class attributes: set `encoding` (e.g. `"utf-8"`) to mark a *byte source* whose output the
Session should decode for the screen; leave it `None` for a *text source*.

### `PtySource(argv, cwd=None, env=None, size=(24, 80), encoding="utf-8")`  *(POSIX)*

Hosts an external program on a real pseudo-terminal. `argv` is a list (`["bash", "-l"]`);
`size` is `(rows, cols)`. A byte source. `send_input` encodes keystrokes with `encoding`. A
failed spawn (e.g. command not found) raises (`FileNotFoundError`/`OSError`) after cleaning up
the pty fds. After exit, `.returncode` holds the child's status. POSIX only (`pty`/`termios`).

### `EngineSource(runner)`  *(any OS)*

Wraps an in-process `runner(emit, readline)` callable on a thread. `emit(text)` writes output;
`readline()` fires `on_wait()` and blocks until input arrives, returning one line — a clean
turn boundary. A text source. A runner exception is captured into `.error`. `stop()` unblocks
a runner waiting in `readline()` (it raises an internal exception that unwinds the runner).
Usually you don't construct this directly — `Session.run_in_thread(runner)` /
`run_blocking(runner)` wrap a bare runner for you.

```python
def runner(emit, readline):
    emit("Name? ")
    emit(f"Hello, {readline().strip()}!\r\n")
```

### `CastSource(path, speed=1.0, idle_time_limit=None, loop=False)`  *(any OS)*

Replays a recorded asciinema `.cast` file (v2 NDJSON or compact v1) through the pipeline. A
text source. `speed` multiplies playback rate; `idle_time_limit` caps long pauses (seconds);
`loop=True` repeats until `stop()`. After construction, `.width` / `.height` hold the
recording's dimensions, so you can size the Terminal to match. Input is ignored. Raises
`ValueError` for an oversized v1 file (the unstreamable whole-file path).

```python
src = CastSource("demo.cast", speed=2.0)
sess = Session(PyteTerminal(src.width, src.height), source=src)
```

### `TtyrecSource(path, speed=1.0, idle_time_limit=None, loop=False, encoding="utf-8")`  *(any OS)*

Replays a `.ttyrec` recording (ttyrec / termrec / NetHack format) — a flat sequence of records,
each a header of three little-endian uint32 (seconds, microseconds, payload length) then that
many raw output bytes. A **byte** source; bytes are decoded to the screen by `encoding` (pass
`"cp437"` for old DOS recordings). `speed`/`idle_time_limit`/`loop` as for `CastSource`. ttyrec
carries no dimensions, so `.width`/`.height` stay 80×24 — size the Terminal yourself.

### `AnsSource(path, speed=1.0, idle_time_limit=None, loop=False, baud=None, charset="cp437")`  *(any OS)*

Plays an ANSI / BBS art file (`.ans`): CP437 bytes + ANSI escapes, optional SAUCE trailer. A
**text** source — it strips the SAUCE record / comment block / DOS `0x1A` marker, decodes CP437
(high-byte glyphs → Unicode box/block characters; escapes pass through), and emits the art (use
`--ansi` / `PyteTerminal` to render it). `baud` (characters/second) draws it progressively for the
retro effect; the default shows it at once. SAUCE's width/height land on `.width`/`.height`.

### `ThreeASource(path, speed=1.0, idle_time_limit=None, loop=False)`  *(any OS)*

Plays a `.3a` animated-ASCII-art file (the DomesticMoth/asciimoth format): UTF-8 text with an
`@3a` header (`delay <ms>`, `loop yes|no`, `colors yes|no`, custom `col <name> fg:.. bg:..`;
`;;` comments) and an `@body` of frames separated by blank lines. With `colors yes`, each frame
interleaves text rows with equal-length color-name rows (`0`-`7`/`8`-`f`/`_` = ANSI
30-37/90-97/default). A **text** source — it renders each frame as positioned SGR output and
steps at the `delay`; `loop yes` (or `--loop`) repeats. Channel "pinning" isn't supported.

### `replay_source(path, speed=1.0, idle_time_limit=None, loop=False)`

Returns the right replay Source for a recording/art file by extension: `.ttyrec` → `TtyrecSource`,
`.ans` → `AnsSource`, `.3a` → `ThreeASource`, anything else (`.cast`, …) → `CastSource`. What
`tapterm --play` uses.

### `PipeSource(argv, cwd=None, env=None, encoding="utf-8")`  *(any OS)*

Hosts an external program over plain pipes — no pty (`tapterm --no-pty`). A byte source,
cross-platform, zero extra deps. Caveat: with no tty the child detects it isn't interactive,
so many programs block-buffer output and skip prompts; best for cooperative, line-oriented
programs.

### `ConPtySource(argv, cwd=None, env=None, size=(24, 80))`  *(Windows)*

Hosts a program on a Windows pseudo-console (ConPTY) via `pywinpty` (the `win` extra). The
Windows counterpart to `PtySource`; pairs with `PyteTerminal` (ConPTY emits VT100+). A text
source (pywinpty returns decoded `str`). **Provisional — written but not yet exercised on real
Windows** (DESIGN §9). `start()` raises `ModuleNotFoundError` where pywinpty isn't installed.

### Writing a custom Source

Implement the three callbacks; nothing else in the toolkit changes. A byte source sets
`encoding` and emits raw bytes as a latin-1 `str`; a text source leaves `encoding = None`.

```python
class TelnetSource(Source):
    encoding = "utf-8"                      # byte source: Session decodes for the screen

    def __init__(self, host, port):
        self.host, self.port, self.thread, self._running = host, port, None, False

    def start(self, on_output, on_wait, on_exit):
        self._sock = socket.create_connection((self.host, self.port))
        self._running = True

        def reader():
            try:
                while self._running:
                    data = self._sock.recv(4096)
                    if not data:
                        break
                    on_output(data.decode("latin-1"))    # raw bytes, lossless
            finally:
                on_exit()

        self.thread = threading.Thread(target=reader, daemon=True)
        self.thread.start()

    def send_input(self, text):
        self._sock.sendall(text.encode("utf-8"))

    def stop(self):
        self._running = False
        self._sock.close()
```

---

## Recording

### `Recorder(session, path, fmt=None)`

An observe-tap that writes a session's output stream, with timing, to a recording file as it
runs — the inverse of a replay source. `fmt` is `"cast"` (asciinema v2) or `"ttyrec"`, defaulting
from the path extension. `start()` opens the file (writing the asciicast header) and attaches the
tap; `close()` detaches and closes. Works as a context manager. Records any source — including a
replay source, so it doubles as a format converter.

```python
sess = Session(PyteTerminal(80, 24), source=PtySource(["bash"]))
with Recorder(sess, "session.cast"):
    curses_ui.run(sess, None)        # everything bash prints is recorded
# replay it: tapterm --play session.cast   (or CastSource("session.cast"))
```

### `export_ansi(session, path)`

Writes the session's **current screen** as an ANSI-art `.ans` file — each cell's color/attributes
as an SGR escape, each glyph encoded back to CP437 (non-CP437 glyphs → `?`), ending with a DOS EOF
marker. A snapshot, not a recording (no timing); readable by `AnsSource` and ANSI-art tools, and
what `tapterm --headless --snapshot screen.ans` calls.

### `export_3a(session, path)`

Writes the current screen as a **single-frame** `.3a` file (a text row + an equal-length
color-name row per screen row, under a minimal `@3a`/`@body` header). Foreground color only;
readable by `ThreeASource`; what `tapterm --headless --snapshot screen.3a` calls. (Recording a
multi-frame `.3a` animation is future work.)

### `render_video(recording, out_path, fps=30, font_size=18, font_path=None, zoom=1.0, speed=1.0, tail=1.0, max_seconds=None, crop=None, terminal=None)`

Renders a `.cast` / `.ttyrec` / `.ans` / `.3a` recording to a **video file** (`.mp4` / `.webm` /
`.gif` / …, by extension): it replays the recording into a terminal, rasterizes each moment with
the compositor's grid renderer, and pipes frames to ffmpeg. Deterministic and
faster-than-real-time (it feeds events up to each frame's time rather than waiting). `font_size`
is the main size control; `zoom` scales the finished frame (crisp nearest-neighbor);
`font_path` picks a `.ttf`; `speed` scales playback; `crop=(col, row, cols, rows)` renders only
that region (area of interest); `max_seconds` caps a never-ending source; `terminal` is the
backend factory `(cols, rows) -> backend` and defaults to `PyteTerminal` — pass `Terminal` to
render a VT52 recording (e.g. one from the dependency-free digital-rain demo). `.gif` output is
an animated, infinitely-looping GIF. Needs the `sdl` + `ansi` extras and ffmpeg — a system
binary, or the bundled one from the `video` extra (`imageio-ffmpeg`). What
`tapterm --play X --render out.mp4` calls.

---

## Session

`Session(terminal=None, source=None)` — the hub. `terminal` defaults to `Terminal()`; set or
pass a `source` before starting. Attributes you can read: `term`, `source`, `driver` (the
current controller name or `None`), `done` (bool), `waiting` (bool).

### Observe taps

```python
on_stream(cb)   # cb(text)        -- raw program output, pre-render (byte-lossless)
on_frame(cb)    # cb()            -- the grid changed; call snapshot() to read it
on_event(cb)    # cb(name, info)  -- WAIT / BELL / CLOSED / DRIVER / ERROR (see Events)
off_stream(cb) / off_frame(cb) / off_event(cb)    # unsubscribe
```

Each `on_*` returns the callback (handy for `off_*` or decorator use). A misbehaving stream/
frame callback is isolated (caught, emitted as an `ERROR` event) so it can't kill output for
other observers.

```python
sess.on_frame(lambda: print(sess.snapshot()["rows"][0]))   # print the top row on each change
sess.on_event(lambda name, info: print("event:", name, info))
```

`snapshot()` → the [snapshot dict](#the-snapshot-dict).

### Control & the talking stick

```python
send_input(text, by=None)              -> bool   # inject input; applied if by is None or driver
feed_key(ch, by="local", auto_take=True)         # one interactive keystroke (local echo + line buffer)
feed_text(s, **kw)                               # feed_key for each char of s
send_key(data, by="local", auto_take=True) -> bool  # raw keystroke bytes, no echo/buffer (raw_keys mode)
echo(text)                                       # show injected text on screen + to observers

claim_control(name, role="ai", unique_suffix=None) -> name  # register a controller (first
                                                 #   claim drives); unique_suffix de-dups a taken
                                                 #   name (the bus uses it, atomically)
take(name)                              -> bool  # grab the stick (courtesy-gated by role)
release(name)                                    # give it up
drop_controller(name)                            # deregister (auto-releases)
has_control(name)                       -> bool  # is `name` the driver?
has_controller(name)                    -> bool  # is `name` registered?
```

`send_input(text, by=None)`: `by=None` is trusted/internal and always applied; a named
controller's input applies only while it holds the stick; returns whether it was applied.
`feed_key` assembles a line (echoing locally, sending on Enter); `auto_take=True` means typing
implicitly grabs the stick (the local human preempts). Only the driver's keys register, so the
line buffer is never raced. See DESIGN §2.3 for the courtesy rules.

Set `session.raw_keys = True` (or `tapterm --raw`) for **full-screen TUIs**: a renderer then
forwards every keystroke via `send_key` — no echo, no line buffer — translating special keys to
VT sequences from the `tappty.keys` module (`KEYS["up"]` → `"\x1b[A"`, …; `ctrl("c")` → `"\x03"`).
The program (a pty TUI like vim) handles its own echo and redraw.

### Lifecycle

```python
start()                  # build the decoder, start the source (non-blocking)
run_in_thread(runner=None)   # if runner given, wrap it as EngineSource; then start()
run_blocking(runner=None)    # start + join the source thread; re-raises source.error if it failed
stop()                   # stop the source and briefly join its thread (idempotent)
```

`run_blocking` is the scripting entry (host → run to completion → read `term.snapshot()`).
`stop()` is the *owning* teardown — the renderers call it on exit; a non-owning view (a
compositor panel over a session it didn't start) should not.

---

## The bus

The same observe/control contract, out of process, over a Unix-domain socket or TCP. One
server = one session, N clients. The full wire protocol is in DESIGN §2.4; here is the Python
API. Trust model: **trusted-local** — see DESIGN §8.

### `BusServer(session, path, cmd_timeout=8.0, token=None, allow_remote=False)`

- `path` — a filesystem path (Unix socket) **or** a `(host, port)` tuple (TCP).
- `cmd_timeout` — seconds a `CMD` waits for the next prompt before reporting a timeout.
- `token` — optional non-empty shared secret a client must present in `HELLO` (a casual gate,
  not transport security). Passing `""` raises `ValueError`.
- `allow_remote` — required to bind a non-loopback TCP host; otherwise binding one raises
  `ValueError`.

```python
start()  -> self    # register the session taps, bind/listen, start accepting (idempotent)
stop()              # detach taps, drop clients, close + unlink; restart-safe
addr                # the resolved bound address after start() (e.g. ("127.0.0.1", 54321))
```

A Unix socket is created `0600` (owner-only). For TCP, bind port `0` and read `srv.addr` for
the OS-assigned port:

```python
srv = BusServer(sess, ("127.0.0.1", 0), token="s3cret").start()
host, port = srv.addr
```

### `BusClient(path, token=None)`

`path`/`token` mirror the server. A background thread reads every message onto `inbox` (a
`queue.Queue` of `(verb, payload)` tuples).

```python
connect()                 -> self        # open the socket, start the reader thread
hello(role="observer", name="client")    # identify; send token if one was set
sub()                                    # subscribe to pushed OUT/FRAME/EVENT
take() / release()                       # grab / drop the talking stick
line(text)                               # inject a line (needs the stick)
key(text)                                # inject raw keystrokes (a string of chars)
send(verb, payload="")                   # low-level frame (str only, no newlines)
wait_for(verb, timeout=3.0)  -> payload | None   # drain inbox until this verb (or timeout)
snap(timeout=3.0)            -> dict | None       # request + return the current grid
cmd(line, timeout=9.0)       -> str | None        # send a line, return output to next prompt
close()
```

`cmd()` is the synchronous driving primitive: it sends the line and returns exactly the output
up to the program's next prompt. It raises `TimeoutError` if the command didn't reach a prompt
(so partial output isn't mistaken for a result) and returns `None` if no reply arrived.

> `BusClient` is **single-consumer**: `wait_for()` drains and discards intervening messages,
> so it's for one request/reply at a time before subscribing — not concurrent callers. A
> subscriber must drain `inbox` (it is unbounded). DESIGN §9.

---

## Renderers

Each renderer is a Session client exposing `run(session, runner, …)`. It starts the program
(`session.run_in_thread(runner)`), loops drawing the grid and forwarding keys, and calls
`session.stop()` on exit (so closing the window stops the program). `run()` **blocks** until
the user quits. Pass `runner=None` when the session already has a `source`.

### `curses_ui.run(session, runner, title="tapterm", refresh_ms=50)`  *(POSIX terminal)*

Draws a cursor-following viewport into the fixed grid with a status line; takes over the
current terminal. Renders SGR color via curses color pairs where the terminal supports it
(else the default foreground). Maps Enter/Backspace/printable ASCII to the session; `Ctrl-]`
quits.

Also exported: **`viewport(model_w, model_h, screen_w, screen_h, cx, cy, status=1)`** →
`(ox, oy, vw, vh)` — the pure, unit-tested function that computes the visible sub-rectangle
(the top-left offset and view size) keeping the cursor in view. Useful if you write your own
renderer.

### `pygame_ui.run(session, runner, title="tapterm", snapshot_path=None, font_size=18, exit_when_done=False, fps=30, max_seconds=None)`  *(GUI)*

A green-phosphor window (the `sdl` extra; needs a display). `snapshot_path` mirrors the screen
to a text file + PNG each second (and `F12` on demand) so an automated observer can watch;
`exit_when_done` closes when the program ends; `max_seconds` is a hard loop cap (scripting/
tests). Scrollback is mouse-wheel / PageUp-PageDown. `fps` must be `>= 1` (else `ValueError`).

### `arcade_ui.run(session, runner, title="tapterm", snapshot_path=None, font_size=18, exit_when_done=False, fps=30, max_seconds=None)`  *(GUI)*

The same renderer on the arcade (pyglet/OpenGL) stack — identical signature and behavior to
`pygame_ui.run` (green phosphor, scrollback, `snapshot_path` text+PNG, `F12`, `exit_when_done`,
`max_seconds`, `fps >= 1`), so the two are interchangeable. The `gl` extra; needs a real GL
context (a display), where the pygame path runs purely in software. `arcade` is imported lazily,
so `import tappty` works without it.

### `web_ui.run(session, runner, title="tapterm", host="127.0.0.1", port=8023, token=None, exit_when_done=False, max_seconds=None, fps=30, allow_remote=False)`  *(browser)*

Serves the session in a **browser tab** (the `web` extra). A stdlib `http.server` serves one
page on `port`; a `websockets` server carries the live connection on `port + 1`. The browser
draws the `cells()` grid (phosphor + SGR color) on a canvas and sends keystrokes back, honoring
`session.raw_keys` for full TUIs. Several browsers can connect at once — the talking stick
arbitrates who drives. `run()` blocks until the program ends (`exit_when_done`), `max_seconds`,
or `KeyboardInterrupt`.

Security: binds **loopback** unless `allow_remote=True`; rejects WebSocket connections whose
`Origin` isn't the page's own (anti-CSWSH — a site the user merely visits can't drive the
terminal); and a non-empty `token` gates **both** the page and the socket (constant-time
compared) and is never embedded in the served HTML. No TLS — tunnel it for untrusted networks
(see DESIGN §8).

---

## Compositor

Tiles several panels in one pygame window (the `sdl` extra).

### `compositor.run(panels, title="tappty dashboard", size=(1280, 720), fps=10, snapshot_path=None, max_seconds=None)`

`panels` is a list of `TerminalPanel`. Blocks. Mouse: wheel zooms a tile, left-drag pans,
right-click resets to fit. Keys: `Tab` cycles focus, `F2` takes/gives the focused tile's
stick, `Esc` quits; other keys route to the focused tile. `fps >= 1`.

### `TerminalPanel(backing, rect, title="")`

A draw-into-rect tile over a pluggable backing. `rect` is `(x, y, w, h)` in pixels. `.kind` is
`"term"` (the compositor dispatches panels by kind). Mouse pan/zoom is built in.

### Backings

Both present the same interface (`grid()`, `feed_key(ch)`, `has_stick()`, `toggle_stick()`,
`focus()`, `close()`), so a panel doesn't care whether its session is local or remote:

- **`SessionBacking(session, op="local")`** — an in-process Session. A *non-owning view*:
  `close()` is a no-op (the session may outlive the panel). The operator types only while it
  holds the stick (`toggle_stick()`, bound to F2); `focus()` never grabs control.
- **`BusBacking(socket_path, name="panel", role="human", token=None)`** — a *remote* session
  over the bus. Subscribes for frames, forwards keystrokes, paces queued frames into a smooth
  scroll. `token` authenticates if the server requires one.

```python
from tappty import compositor, Session, PyteTerminal, PtySource

def local_panel(cmd, rect):
    s = Session(PyteTerminal(), source=PtySource(cmd))
    s.claim_control("local", "human")
    s.start()
    return compositor.TerminalPanel(compositor.SessionBacking(s), rect, cmd[0])

panels = [
    local_panel(["bash"], (10, 24, 620, 680)),
    compositor.TerminalPanel(compositor.BusBacking("/tmp/remote.sock"), (650, 24, 620, 680), "remote"),
]
compositor.run(panels)
```

---

## Worked examples

Runnable versions of these (and more) live in [`examples/`](https://github.com/nyxbitco/tappty/tree/main/examples)
— `observe_tap.py`, `custom_source.py`, `bus_capture.py`. For visual showpieces, see
[`demos/`](https://github.com/nyxbitco/tappty/tree/main/demos) and the [gallery](GALLERY.md).

### Drive an interactive program over the bus

```python
# --- host process ---
from tappty import Session, Terminal, PtySource, BusServer
sess = Session(Terminal(), source=PtySource(["python3", "-i", "-u"]))
srv = BusServer(sess, "/tmp/tappty-demo.sock").start()
sess.start()
# ... keep the process alive (e.g. join the source thread, or run a renderer) ...

# --- driver process ---
from tappty import BusClient
c = BusClient("/tmp/tappty-demo.sock").connect()
c.hello(role="ai", name="bot")            # claim the stick (first controller drives)
print(c.cmd("import math; math.pi"))      # -> the REPL's output up to the next ">>> "
print(c.cmd("2 ** 10"))                   # -> "1024\n..."
c.line("exit()")                          # fire-and-forget input
c.close()
```

### Watch a live session headlessly (subscribe to the stream)

```python
from tappty import BusClient
c = BusClient("/tmp/tappty-demo.sock").connect()
c.hello(role="observer", name="logger")
c.sub()                                   # subscribe to pushed OUT/FRAME/EVENT
while True:
    verb, payload = c.inbox.get()         # MUST drain — the inbox is unbounded
    if verb == "OUT":
        log.write(payload)                # raw program bytes (lossless)
    elif verb == "EVENT" and payload["name"] == "CLOSED":
        break
```

### Replay a recording to a PNG (headless, deterministic)

```python
from tappty import Session, PyteTerminal, CastSource, pygame_ui
import os
os.environ["SDL_VIDEODRIVER"] = "dummy"   # no display needed
src = CastSource("session.cast", speed=4.0)
sess = Session(PyteTerminal(src.width, src.height), source=src)
pygame_ui.run(sess, None, snapshot_path="out", exit_when_done=True, max_seconds=10)
# -> out (final screen text) and out.png (pixels)
```

---

## Quick reference

| Name | Signature | Notes |
|------|-----------|-------|
| `Terminal` | `(cols=80, rows=24, scrollback=5000)` | VT52 model, no deps |
| `PyteTerminal` | `(cols=80, rows=24, scrollback=5000)` | full-ANSI; `ansi` extra |
| `Session` | `(terminal=None, source=None)` | the hub |
| `Source` | base class | subclass for a custom producer |
| `PtySource` | `(argv, cwd=None, env=None, size=(24,80), encoding="utf-8")` | POSIX pty; byte source |
| `EngineSource` | `(runner)` | in-process `runner(emit, readline)`; text source |
| `CastSource` | `(path, speed=1.0, idle_time_limit=None, loop=False)` | `.cast` replay; `.width`/`.height` |
| `TtyrecSource` | `(path, speed=1.0, idle_time_limit=None, loop=False, encoding="utf-8")` | `.ttyrec` replay; byte source |
| `AnsSource` | `(path, speed=1.0, idle_time_limit=None, loop=False, baud=None, charset="cp437")` | `.ans` ANSI art; CP437 + SAUCE |
| `ThreeASource` | `(path, speed=1.0, idle_time_limit=None, loop=False)` | `.3a` animated ASCII art |
| `replay_source` | `(path, speed=1.0, idle_time_limit=None, loop=False)` | picks Cast/Ttyrec/Ans/3a by extension |
| `PipeSource` | `(argv, cwd=None, env=None, encoding="utf-8")` | plain pipes, any OS; byte source |
| `ConPtySource` | `(argv, cwd=None, env=None, size=(24,80))` | Windows ConPTY; `win` extra (provisional) |
| `Recorder` | `(session, path, fmt=None)` | record output → `.cast`/`.ttyrec`; `start()`/`close()` |
| `export_ansi` | `(session, path)` | write the screen as ANSI-art `.ans` (CP437 + SGR) |
| `export_3a` | `(session, path)` | write the screen as a single-frame `.3a` |
| `render_video` | `(recording, out_path, fps=30, font_size=18, font_path=None, zoom=1.0, speed=1.0, tail=1.0, max_seconds=None, crop=None, terminal=None)` | recording → `.mp4`/`.webm`/`.gif`/… via ffmpeg |
| `BusServer` | `(session, path, cmd_timeout=8.0, token=None, allow_remote=False)` | `.start()`/`.stop()`/`.addr` |
| `BusClient` | `(path, token=None)` | `.connect()`, `snap`, `cmd`, `line`, `key`, `sub`, `inbox` |
| `curses_ui.run` | `(session, runner, title="tapterm", refresh_ms=50)` | blocks; POSIX |
| `curses_ui.viewport` | `(model_w, model_h, screen_w, screen_h, cx, cy, status=1)` | pure → `(ox, oy, vw, vh)` |
| `pygame_ui.run` | `(session, runner, title="tapterm", snapshot_path=None, font_size=18, exit_when_done=False, fps=30, max_seconds=None)` | blocks; `sdl` extra |
| `compositor.run` | `(panels, title="tappty dashboard", size=(1280,720), fps=10, snapshot_path=None, max_seconds=None)` | blocks; `sdl` extra |
| `compositor.TerminalPanel` | `(backing, rect, title="")` | `rect=(x,y,w,h)` |
| `compositor.SessionBacking` | `(session, op="local")` | in-process, non-owning |
| `compositor.BusBacking` | `(socket_path, name="panel", role="human", token=None)` | remote over the bus |
