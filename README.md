# tappty

**Host a program on a pseudo-terminal, then observe, control, and render it** — in a
plain terminal (curses, CUI) or a green-phosphor window (pygame, GUI).

`tappty` is a small instrumented-terminal toolkit. A program's bytes (a subprocess on a
PTY, or any in-process runner) flow into a fixed-size character `Terminal`; a `Session`
fans that output out to any number of observers and routes input back. A renderer is just
one more observer/controller — which is what lets a human *and* an automated client watch
and drive the very same session. Several sessions tile into one window via the compositor.

It was factored out of the *SIXBIT FORTRAN 66* project's `sbterm` (a period VT52 emulator
hosting 1970s PDP-10 games), generalized to host any command.

## Install

```sh
pip install tappty          # core (CUI works out of the box)
pip install 'tappty[gui]'   # add the pygame window (pygame-ce)
pip install 'tappty[arcade]' # add the arcade/OpenGL window (an alternative GUI backend)
pip install 'tappty[ansi]'  # add the full-ANSI/VT100+ backend (pyte) for --ansi
pip install 'tappty[win]'   # Windows: add the ConPTY source (pywinpty)
# from a checkout:
pip install -e '.[gui,ansi,dev]'
```

## The `tapterm` program

```sh
tapterm                    # host your $SHELL (GUI if pygame + a display, else CUI)
tapterm -- python3 -i      # host a specific command (everything after -- is its argv)
tapterm --cui -- bash      # force the curses character UI (takes over this terminal)
tapterm --gui -- bash      # force the pygame green-phosphor window
tapterm --arcade -- bash   # same, on the arcade/OpenGL stack (the 'arcade' extra)
tapterm --headless -- ls   # run to completion, print the final screen (scripting/CI)
tapterm --cast rec.cast    # replay an asciinema recording (--speed N, --loop)
tapterm --ansi -- vim      # use the full-ANSI/VT100+ backend (pyte) instead of VT52
tapterm --no-pty -- ls     # host over plain pipes, no pty (cross-platform, incl. Windows)
```

`--cui` works anywhere; `--gui` needs the `gui` extra. With no mode flag, `tapterm` picks
GUI when pygame is installed *and a display is available* (else CUI) — so it won't try to
open a window over SSH/cron. `--ansi` swaps the built-in VT52 grid for the
`pyte` full-ANSI model (needs the `ansi` extra) — use it for programs that emit modern ANSI
(colors, cursor addressing). On Windows the pty path uses ConPTY (the `win` extra); pair it
with `--ansi`, since ConPTY emits VT100+.

Every flag, the three modes, recordings, snapshots, recipes, and troubleshooting are in the
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
  the `ansi` extra) for programs that speak modern ANSI; same read interface, so renderers
  don't change.
- **`Source` / `PtySource` / `EngineSource` / `CastSource` / `PipeSource` / `ConPtySource`**
  — byte producers. `PtySource` runs an external command on a real pty (POSIX); `EngineSource`
  wraps any in-process `runner(emit, readline)` callable; `CastSource` replays a recorded
  asciinema `.cast` session through the same pipeline (original timing, `speed`/`loop`);
  `PipeSource` hosts a command over plain pipes (no pty, any OS); `ConPtySource` hosts one on
  a Windows pseudo-console (ConPTY, the `win` extra).
- **`Session`** — hosts a Source, drives the Terminal, and exposes **observe taps**
  (`on_stream`, `on_frame`, `on_event`) and **control** (`send_input`, `feed_key`) plus a
  talking-stick arbitration so exactly one controller types at a time.
- **`BusServer` / `BusClient`** — the same observe/control contract over a Unix-domain
  socket *or* TCP (a `(host, port)` tuple — works on Windows too), so an out-of-process
  client (a logger, an automated driver, a remote renderer) can attach to a session. It's a
  terminal control plane — **trusted-local**: the Unix socket is owner-only, TCP is
  loopback-only unless `allow_remote=True`, and a `token=` adds an optional shared-secret
  gate. Not a substitute for a tunnel on an untrusted network (no TLS).
- **`curses_ui` / `pygame_ui` / `arcade_ui`** — renderers; each exposes
  `run(session, runner, title=…)`. `pygame_ui` and `arcade_ui` are two backends for the same
  green-phosphor window (pygame, or arcade/OpenGL).
- **`compositor`** — tile several panels (`SessionBacking` for in-process, `BusBacking`
  for remote) in one pygame window, with per-tile pan/zoom and focus.

## Platform

The core (Terminal/Session/taps/talking-stick), `EngineSource`, `CastSource`, `PipeSource`,
the renderers, and the TCP bus are cross-platform. `PtySource` uses `pty`/`termios`
(POSIX-only); on Windows, host via `ConPtySource` (the `win` extra, ConPTY — paired with
`--ansi`) or `PipeSource` (`--no-pty`), and use the TCP bus rather than a Unix socket. The
Windows ConPTY path is implemented but not yet exercised on real Windows — finishing it is
open work (see [ROADMAP.md](ROADMAP.md)). The GUI needs a display; the CUI needs a
terminal (and, on Windows, the `win` extra's `windows-curses`); `--headless` needs neither.

## Documentation

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
  it first worked, and what's changed since.
- **[ROADMAP.md](ROADMAP.md)** — what's next: CI, the `sixbit/term` rewire, PyPI, and
  finishing the Windows ConPTY path.

## Tests & tooling

```sh
pip install -e '.[dev]'            # quick: core suite (pyte + GUI tests skip)
pytest

pip install -e '.[dev,ansi,gui]'   # full: also the ANSI backend + headless GUI smoke
pytest

ruff check src tests               # lint (E,F,W,I,B,UP); must be clean
ruff format src tests              # format (line-length 99, black-style)

# no install needed, straight from a checkout:
PYTHONPATH=src python3 -m tappty.cli --headless -- echo hello
```

Without the `ansi`/`gui` extras, `pytest` skips the pyte and pygame tests (so it reports
fewer passes plus a couple of skips); install `.[dev,ansi,gui]` to run the whole suite. CI
runs ruff + the full matrix on Python 3.9–3.13.

## License

MIT © Nicholas J. Kisseberth. See [LICENSE](LICENSE).
