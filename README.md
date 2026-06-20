# tappty

**Host a program on a pseudo-terminal, then observe, control, and render it** — in a
plain terminal (curses, CUI) or a green-phosphor window (GUI).

Software Architecture, Design & Engineering by Nicholas J. Kisseberth.  
Code Synthesized via Anthropic Claude Code / Opus 4.8.  
Automated Code Review via OpenAI Codex / ChatGPT 5.5.

`tappty` is a small instrumented-terminal toolkit. A program's bytes (a subprocess on a
PTY, or any in-process runner) flow into a fixed-size character `Terminal`; a `Session`
fans that output out to any number of observers and routes input back. A renderer is just
one more observer/controller — which is what lets a human *and* an automated client watch
and drive the very same session. Several sessions tile into one window via the compositor.

## Install

```sh
pip install tappty          # core (CUI works out of the box)
pip install 'tappty[sdl]'   # add the SDL/GUI window (installs pygame-ce)
pip install 'tappty[gl]' # add the OpenGL window (arcade; an alternative GUI backend)
pip install 'tappty[web]'    # add the browser renderer for --web (websockets)
pip install 'tappty[video]'  # render recordings to mp4/gif via --render (bundles ffmpeg)
pip install 'tappty[ansi]'  # add the full-ANSI/VT100+ backend (pyte) for --ansi
pip install 'tappty[win]'   # Windows: add the ConPTY source (pywinpty)
# from a checkout:
pip install -e '.[sdl,ansi,dev]'
```

`pip install tapterm` works too — it's a convenience alias that just pulls in `tappty` (which
provides the `tapterm` command). The library, the extras, and the docs all live under `tappty`.

## The `tapterm` program

```sh
tapterm                    # a regular terminal: your $SHELL, full-ANSI + raw keys
tapterm -e vim file        # run a command instead of the shell, xterm-style (or: -- vim file)
tapterm -geometry 100x30   # xterm-style size; -T/-title sets the title, -cd DIR the working dir
tapterm --cui -- bash      # force the curses character UI (takes over this terminal)
tapterm --gui -- bash      # force the SDL green-phosphor window (the 'sdl' extra)
tapterm --arcade -- bash   # same, on the arcade/OpenGL stack (the 'gl' extra)
tapterm --web -- bash      # serve it in a browser (the 'web' extra); open http://127.0.0.1:8023/
tapterm --headless -- ls   # run to completion, print the final screen (scripting/CI)
tapterm --cooked -- bash   # line-oriented instrument mode (local echo on the VT52 grid)
tapterm --play rec.cast    # replay a .cast / .ttyrec / .ans / .3a recording (--speed N, --loop)
tapterm --record out.cast -- bash       # record a session as you use it
tapterm --play rec.cast --render rec.mp4 # render a recording to a video (mp4/webm/gif)
tapterm --render rain.mp4 --seconds 5 -- cmatrix  # render a live program straight to video
tapterm --no-pty -- ls     # host over plain pipes, no pty (cross-platform, incl. Windows)
```

An interactive session behaves like a **real terminal** — full-ANSI rendering (the `ansi` extra,
pyte) plus raw keys, so colors, line-editing, arrows, and full-screen apps work, and the window
closes when the program exits, like xterm. Pass `--cooked` for the line-oriented instrument
default instead (local echo on the dependency-free VT52 grid) — what the observe taps and the bus
`CMD` capture expect. xterm-style flags are accepted where they fit: `-e`, `-T`/`-title`,
`-geometry`, `-cd`, `-hold`.

`--cui` works anywhere; `--gui` needs the `sdl` extra. With no mode flag, `tapterm` picks GUI when
the `sdl` extra is installed *and a display is available* (else CUI) — so it won't try to open a
window over SSH/cron. On Windows the pty path uses ConPTY (the `win` extra), which emits VT100+.

Every flag, the modes, recordings, snapshots, recipes, and troubleshooting are in the
[tapterm user's guide](docs/TAPTERM.md).

## Library

```python
from tappty import Session, Terminal, PtySource, curses_ui

sess = Session(Terminal(cols=80, rows=24))
sess.source = PtySource(["bash"])
sess.claim_control("local", "human")
curses_ui.run(sess, None, title="bash")
```

Full API — classes, signatures, the observe/control contract, and worked examples — is in
[docs/REFERENCE.md](docs/REFERENCE.md).

The pieces:

- **`Terminal` / `PyteTerminal`** — the screen model. `Terminal` is a fixed-size character
  grid (VT52 spirit: wrap/scroll, the common control chars, a handful of VT52 escapes), with
  scrollback and no deps. `PyteTerminal` is a drop-in full-ANSI/VT100+ backend (wraps `pyte`,
  the `ansi` extra) for programs that speak modern ANSI; same read interface (plus a `cells()`
  view of per-cell SGR color), so the GUI renderers show color while the rest is unchanged.
- **`Source` / `PtySource` / `EngineSource` / `CastSource` / `TtyrecSource` / `PipeSource` /
  `ConPtySource`** — byte producers. `PtySource` runs an external command on a real pty (POSIX);
  `EngineSource` wraps any in-process `runner(emit, readline)` callable; `CastSource` /
  `TtyrecSource` replay a recorded asciinema `.cast` / `.ttyrec` session through the same pipeline
  (original timing, `speed`/`loop`); `PipeSource` hosts a command over plain pipes (no pty, any
  OS); `ConPtySource` hosts one on a Windows pseudo-console (ConPTY, the `win` extra).
- **`Session`** — hosts a Source, drives the Terminal, and exposes **observe taps**
  (`on_stream`, `on_frame`, `on_event`) and **control** (`send_input`, `feed_key`) plus a
  talking-stick arbitration so exactly one controller types at a time.
- **`Recorder` / `render_video`** — `Recorder` writes the session's output stream to a `.cast`
  or `.ttyrec` recording as it runs (the inverse of the replay sources; `tapterm --record`);
  `render_video` encodes a recording to a real video file (mp4/webm/gif) via ffmpeg, with
  size/zoom/font/speed and an area-of-interest crop (`tapterm --play X --render out.mp4`).
- **`BusServer` / `BusClient`** — the same observe/control contract over a Unix-domain
  socket *or* TCP (a `(host, port)` tuple — works on Windows too), so an out-of-process
  client (a logger, an automated driver, a remote renderer) can attach to a session. It's a
  terminal control plane — **trusted-local**: the Unix socket is owner-only, TCP is
  loopback-only unless `allow_remote=True`, and a `token=` adds an optional shared-secret
  gate. Not a substitute for a tunnel on an untrusted network (no TLS).
- **`curses_ui` / `pygame_ui` / `arcade_ui` / `web_ui`** — renderers; each exposes
  `run(session, runner, title=…)`. `pygame_ui` and `arcade_ui` are two backends for the same
  green-phosphor window (SDL, or arcade/OpenGL); `web_ui` serves it in a browser over a
  WebSocket (the `web` extra).
- **`compositor`** — tile several panels (`SessionBacking` for in-process, `BusBacking`
  for remote) in one GUI window, with per-tile pan/zoom and focus.

## Demos & examples

`demos/` holds runnable showpieces — the SGR color chart, the green digital rain, the compositor
"mission control", `drive_vim` (a program driving a live `vim` over the control tap), and
`web_demo` (the browser renderer). `examples/` holds short, commented API examples — the observe
taps, writing a custom `Source`, driving a session over the bus, and `watch_and_drive` (a bot that
reads the output stream and types its decisions back). The [gallery](docs/GALLERY.md) has
screenshots and a clip of each.

## Platform

The core (Terminal/Session/taps/talking-stick), `EngineSource`, `CastSource`, `PipeSource`,
the renderers, and the TCP bus are cross-platform. `PtySource` uses `pty`/`termios`
(POSIX-only); on Windows, host via `ConPtySource` (the `win` extra, ConPTY — paired with
`--ansi`) or `PipeSource` (`--no-pty`), and use the TCP bus rather than a Unix socket. The
Windows ConPTY path is implemented but not yet exercised on real Windows — finishing it is
open work (see [docs/DESIGN.md](docs/DESIGN.md) §11). The GUI needs a display; the CUI needs a
terminal (and, on Windows, the `win` extra's `windows-curses`); `--headless` needs neither.

## Documentation

The rendered docs site is at **[nyxbitco.github.io/tappty](https://nyxbitco.github.io/tappty/)**
(built from `docs/` by `gh-pages/build_site.py` and published via GitHub Actions). The sources:

- **[docs/TAPTERM.md](docs/TAPTERM.md)** — the `tapterm` command in depth: every flag,
  the CUI / GUI / headless modes, the terminal model, recordings, snapshots, recipes, and
  troubleshooting. For *using* tapterm.
- **[docs/REFERENCE.md](docs/REFERENCE.md)** — the programming/API reference: every public
  class and method with signatures, the observe/control contracts (snapshot dict, events,
  roles), and worked examples. For *building on* the library.
- **[docs/DESIGN.md](docs/DESIGN.md)** — the architecture: the Source → Terminal → Session →
  renderer/bus pipeline, the concurrency and security/trust models, and the design rationale.
  For *modifying* tappty.
- **[CHANGELOG.md](CHANGELOG.md)** — dated history, newest first: when tappty started, when
  it first worked, and what's changed since. The remaining open work (publish to PyPI; verify
  Windows) is noted in its footer and in [docs/DESIGN.md](docs/DESIGN.md) §11.

## Tests & tooling

```sh
pip install -e '.[dev]'            # quick: core suite (pyte + GUI tests skip)
pytest

pip install -e '.[dev,ansi,sdl]'   # full: also the ANSI backend + headless GUI smoke
pytest

ruff check src tests               # lint (E,F,W,I,B,UP); must be clean
ruff format src tests              # format (line-length 99, black-style)

# no install needed, straight from a checkout:
PYTHONPATH=src python3 -m tappty.cli --headless -- echo hello
```

Without the `ansi`/`sdl` extras, `pytest` skips the pyte and GUI tests (so it reports
fewer passes plus a couple of skips); install `.[dev,ansi,sdl]` to run the whole suite. CI
runs ruff + the full matrix on Python 3.9–3.13.

## License

MIT © Nicholas J. Kisseberth. See [LICENSE](LICENSE).
