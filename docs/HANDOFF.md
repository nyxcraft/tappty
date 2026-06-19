# Handoff — tappty

For whoever picks this up next (a fresh Claude, or a code agent in VS Code). Read this
once. The narrative of how we got here is in [HISTORY.md](HISTORY.md); the architecture is
in [DESIGN.md](DESIGN.md).

---

## What this is

`tappty` is a small instrumented-terminal toolkit: **host a program on a pseudo-terminal,
then observe, control, and render it** — in a plain terminal (curses, CUI) or a
green-phosphor pygame window (GUI). The design point is that every consumer — the screen,
a socket logger, an automated driver — is an equal client of one observe/control contract,
so a human and a bot can watch and take turns driving the same session.

It was extracted from the *SIXBIT FORTRAN 66* project's `sbterm` (a period VT52 emulator
hosting 1970s PDP-10 games) and generalized to host any command. The command-line program
is **`tapterm`** (the package is `tappty`).

---

## Layout

```
tappty/
├── pyproject.toml          dist "tappty"; extras [gui]=pygame-ce [ansi]=pyte [win]=pywinpty [dev]=pytest+ruff; ruff config (line-length 99); script: tapterm = tappty.cli:main
├── README.md, LICENSE      MIT © Nicholas J. Kisseberth
├── .github/workflows/ci.yml  ruff + pytest matrix (3.9–3.13) on push/PR; headless GUI via SDL dummy
├── src/tappty/
│   ├── terminal.py       fixed 80x24 VT52 grid model (no deps)
│   ├── pyte_terminal.py  PyteTerminal — full-ANSI/VT100+ backend, drop-in for Terminal (ansi extra)
│   ├── source.py         Source / PtySource (pty) / EngineSource (runner) / CastSource (.cast) / PipeSource (pipes) / ConPtySource (Win ConPTY)
│   ├── session.py        Session: observe taps + control + talking-stick arbitration
│   ├── bus.py            BusServer/BusClient — the same contract over a unix socket OR TCP
│   ├── compositor.py     multi-panel window + SessionBacking / BusBacking
│   ├── curses_ui.py      CUI renderer + the pure viewport() math
│   ├── pygame_ui.py      GUI renderer
│   ├── cli.py            the tapterm program (--ansi, --no-pty, --cast, platform source pick)
│   └── __init__.py       public API
├── tests/              87 tests (model, ansi+scrollback, taps, stick, bus+tcp+security, pty, pipe, cast, encoding, errors, viewport, gui-smoke)
└── docs/               DESIGN.md, HISTORY.md, HANDOFF.md, WINDOWS.md
```

---

## Running things

```sh
cd ~/tappty
python3 -m pytest                         # 77 pass + 2 skipped (system python3: no pyte/pygame)
.venv/bin/python -m pytest                # 87 pass (venv with pygame-ce + pyte: all run)
.venv/bin/ruff check src tests            # lint (E,F,W,I,B,UP); must be clean
.venv/bin/ruff format src tests           # format (line-length 99, black-style)

# the program (from a checkout, src/ on the path):
PYTHONPATH=src python3 -m tappty.cli --headless -- echo hello   # smoke test
pip install -e '.[gui,ansi,dev]'          # then `tapterm` is a real command (+ANSI backend)
tapterm --cui -- bash                     # curses, in this terminal
tapterm --gui -- bash                     # pygame window (needs the gui extra)
tapterm --headless -- ls                  # run + print final screen
tapterm --ansi -- vim                     # full-ANSI/VT100+ backend (needs the ansi extra)
tapterm --no-pty -- ls                    # host over plain pipes (no pty; cross-platform)
```

`--cui` and `--headless` need no display; `--gui` needs pygame + a display. With no mode
flag `tapterm` picks GUI when pygame is installed *and a display is available* (DISPLAY/
WAYLAND_DISPLAY on Linux; native on macOS/Windows), else CUI. With no command it hosts
`$SHELL`.

---

## Things to know / landmines

- **Optional deps are import-guarded.** `pygame`, `curses`, `pyte`, and `pywinpty` are
  imported *inside* the functions/constructors that use them, never at module top — so
  `import tappty` works with none installed (there's a test-ish check; verified by importing
  under system python3 with no extras). Keep it that way; don't hoist those imports to module
  scope. Extras: `gui`=pygame-ce, `ansi`=pyte, `win`=pywinpty, `dev`=pytest.
- **`PyteTerminal` (the `ansi` extra, `--ansi`) is the full-ANSI backend.** Drop-in for the
  VT52 `Terminal` (same read interface), wraps `pyte` (LGPLv3 — fine as a *separate* optional
  install; don't vendor/modify it). Use it for programs that emit modern ANSI; the VT52
  `Terminal` stays the default. Scrollback works (it uses `pyte.HistoryScreen`, reading
  `.history.top` non-mutatingly for `view_rows`).
- **Bytes vs characters split.** `on_stream` (and the bus `OUT`) carries the program's **raw
  bytes** (byte-transparent latin-1 str, lossless); the **screen** (grid / `snapshot` /
  `FRAME`) carries those bytes **decoded** to characters. The Session does the decode
  (incremental, keyed on the source's `encoding` attr — UTF-8 by default for `PtySource`/
  `PipeSource`; absent for text sources). So the terminal backends are encoding-agnostic, and
  UTF-8 renders right on *both* `Terminal` and `PyteTerminal`. `encoding="latin-1"` makes the
  screen byte-transparent too. Don't move the decode back into a source — it would make the
  stream tap lossy.
- **The bus is a trusted-local control plane (auth is opt-in).** A connected client gets
  terminal read/write as the tappty user. Defenses: the Unix socket *file* is `0600`
  (owner-only connect — the actual gate; a parent dir tappty creates is also `0700`, but an
  existing dir is left as-is); TCP is loopback-only unless `allow_remote=True`; an optional
  non-empty `token` (a string in `HELLO`, constant-time compared) gates connections but is
  cleartext, not transport security; frames are size-capped on both ends and captures byte-
  bounded; `BusClient.send` rejects newlines. Full design + the reasoning is
  [DESIGN.md](DESIGN.md) §7. Don't expose the bus to an untrusted network without a tunnel —
  there is no TLS.
- **The GUI draw path is smoke-tested, but only where pygame is installed.**
  `test_gui_smoke` drives `pygame_ui.run` + the compositor to completion under the SDL
  `dummy` driver (no display), so the blit/draw/flip paths execute — but it `importorskip`s
  pygame, so without it the test *skips* (the 2 skips in the system-python run). The CI
  workflow installs `pygame-ce`, so it runs there; if you ever drop that, the smoke test goes
  silently green-by-skipping. Pixel *fidelity* is still by-eye: under WSLg
  (`DISPLAY`/`WAYLAND_DISPLAY` set, SDL auto-picks x11) both renderers draw correctly and
  `--snapshot` writes a reviewable PNG; `tapterm --cast rec.cast --gui` is the easiest
  reproducible visual check. Harmless EGL/MESA warnings on stderr are failed hardware-GL
  probing; SDL falls back to software.
- **Cross-platform now, except the pty + a still-untested Windows source.** `PtySource`
  uses `pty`/`termios`/`fcntl` (POSIX only). For Windows: `PipeSource` (`--no-pty`, plain
  pipes, tested on POSIX) and `ConPtySource` (the `win` extra, ConPTY via pywinpty) exist,
  and `cli.py` auto-picks `ConPtySource` on `os.name=="nt"`. The bus now does TCP (a
  `(host,port)` tuple) as well as `AF_UNIX`. **But `ConPtySource` has never run on Windows**
  (no Windows here; pywinpty won't install off-Windows) — it's coded to the documented
  pywinpty `PtyProcess` API and flagged provisional in the source. **Next agent on a Windows
  box: this is the thing to actually exercise.** See [WINDOWS.md](WINDOWS.md).
- **Two copies of this code exist.** `~/tappty` and `~/pdp10-empire/sixbit/term` are
  independent copies until the parent is rewired (see below). **A fix here must also land
  in `sixbit/term`** (and vice-versa) until then. This is the top live hazard — the same
  drift the project is already managing with `pyf66`.

---

## Open work (roughly in priority order)

1. **Push to a GitHub remote so CI runs.** `~/tappty` is now a git repo (initial commit on
   `main`, author Nicholas J. Kisseberth / nkissebe@purdue.edu) with a CI workflow
   (`.github/workflows/ci.yml`: ruff lint/format + the full pytest matrix on 3.9–3.13, with
   pygame-ce + pyte so the GUI-smoke and ANSI tests run headlessly under SDL `dummy`).
   **The workflow has never actually run** (no remote yet) — create `github.com/nkissebe/tappty`,
   `git push`, and confirm it's green; the pygame-ce-in-CI step in particular is unverified.
2. **Rewire `~/pdp10-empire/sixbit/term` to consume `tappty`** (pip editable install or a
   namespace shim) instead of its own copy, so the two stop drifting. The game-specific
   bits left behind — the DECWAR galaxy view (`draw_galaxy` / `GalaxyPanel`) and the
   `decwar_runner` / `bot_runner` / `decwar_script_runner` factories — become consumers
   that import from `tappty` (a `GalaxyPanel` is just another panel `kind`; a game runner is
   just an `EngineSource`). `arena.py` and the `sbterm` launcher come along as consumers.
3. **Publish:** build sdist/wheel and publish to PyPI once happy.
4. **Finish Windows on a real Windows box.** The full-ANSI "b-full" backend (`PyteTerminal`,
   `ansi` extra) is **done**; `PipeSource`, the TCP bus, and platform source-selection are
   **done and tested on POSIX**; `ConPtySource` (`win` extra) is **written but never run on
   Windows**. Remaining: `pip install -e '.[ansi,win]'` on Windows, drive
   `tapterm --ansi -- cmd` / `powershell`, fix the pywinpty details, then add a Windows CI
   job. Full state per stage in [WINDOWS.md](WINDOWS.md) §5–6.
5. **Possible features:** an arcade or web renderer (same `run(session, runner, …)` shape —
   `terminado` / `pyxtermjs` are references); `windows-curses` so the CUI runs on Windows too.

---

## Design-decision archive (parent project)

tappty's *why* is recorded in the SIXBIT FORTRAN 66 project's memory notes (one fact per
file). The most relevant are the `sbterm-instrumentation` design note (the observe/control
bus + Source seam + talking-stick arbitration that became this package) and `decwar-port`
(the multiplayer host that drove the requirements). They live with the parent project at
`~/pdp10-empire` and in the project's Claude memory directory.
