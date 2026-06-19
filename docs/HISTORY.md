# tappty — project history

How tappty came to be, with dates. Timestamps are local commit/edit times (US Eastern).
tappty wasn't designed in the abstract — it was *discovered* by building a real
instrumented terminal to host 1970s PDP-10 games, then extracting the part that turned out
to be general.

---

## Origin — built as `sbterm` inside SIXBIT FORTRAN 66

tappty began as `sbterm`, the terminal layer of the *SIXBIT FORTRAN 66* project (a Python
interpreter running Walter Bright's 1978 *Empire* and the 1979 *DECWAR* unmodified). The
games needed a period-faithful glass terminal you could sit down at — and, for multiplayer
DECWAR, a way for bots and spectators to observe and drive sessions. Those two needs
produced the decoupled Source/Terminal/Session/bus design that tappty now is.

### 2026-06-17 — the instrumented terminal, built across one day

| Time | What & why |
|------|-----------|
| ~13:10 | Package stub (`__init__`) — the terminal-layer namespace. |
| **14:29** | **`Terminal`** (the fixed 80×24 VT52 grid model) and the **first pygame renderer**. The fixed-size model was the first decision: keep the program sealed in its era; make screen size a render-side concern. |
| ~17:48–17:50 | The **`Source` seam** (`source.py`) and the **curses renderer**. `EngineSource` wraps an in-process `runner(emit, readline)`; `PtySource` hosts an external program on a pseudo-terminal. Splitting "where the bytes come from" out from the Terminal is what later made tappty general. |
| 18:32 | The `sbterm` launcher (argument parsing, mode selection). |
| **19:37** | The **instrumentation bus** (`bus.py`) — observe/control over a Unix-domain socket, so an out-of-process client (an AI, a logger, a remote renderer) can attach. |
| **19:52** | The **`Session`** (`session.py`) — observe taps (`on_stream`/`on_frame`/`on_event`), control (`send_input`/`feed_key`), and the **talking-stick** arbitration so exactly one controller types at a time. This is the hub that makes "human and bot share one session" safe. |
| **22:51** (`a146711`) | Committed: *"sbterm: instrumented terminal — observe/control bus, panels, arena."* |

### 2026-06-17 23:43 → 2026-06-18 00:15 — the dashboard and the god view

| Time | Commit | What |
|------|--------|------|
| 23:43 | `e399dc6` | God view: ships **glide** to new positions (eased) with motion trails. |
| 00:15 | `54a5853` | God view: **animated weapon fire** (phaser zaps, photon-torpedo projectiles) + scrolling terminal replay; the multi-panel **compositor** (`compositor.py`) and **arena** dashboard. |

> The compositor's *panel framework* is generic and came into tappty. The **galaxy view**
> built in these commits (`draw_galaxy` / `GalaxyPanel`) is DECWAR-specific and did **not**
> — it stayed behind as a game-side consumer of the generic panel API.

---

## 2026-06-18 (midday) — extracted to `~/tappty`

With the design proven against a real, demanding host (a multiplayer game with bots and
spectators), the generic core was lifted out into a standalone, PyPI-shaped package —
following the same playbook the project used to extract its FORTRAN interpreter into
`pyf66`:

- **Copied the generic modules** — `terminal`, `source`, `session`, `bus`, `compositor`,
  `curses_ui`, `pygame_ui` — rewriting imports `sixbit.term` → `tappty`.
- **Removed the two DECWAR couplings:** `draw_galaxy` / `GalaxyPanel` from the compositor,
  and the `decwar_runner` / `bot_runner` / `decwar_script_runner` factories from the
  session. Both become consumers of tappty's seams rather than parts of it.
- **Added a generic `tapterm` program** (`cli.py`) — host any command on a pty and render
  it in `--cui` / `--gui` / `--headless`. (The package is `tappty`; the command is
  `tapterm`.)
- **Packaged it:** `pyproject.toml` (dist `tappty`, `gui`=pygame extra, `tapterm`
  console-script), MIT LICENSE © Nicholas J. Kisseberth, README, src/ layout.
- **Ported 22 tests** (the generic ones; the galaxy-panel test was dropped) — all green.
  Verified `import tappty` works with neither pygame nor a display, and `tapterm
  --headless -- echo …` round-trips a real subprocess through the pty into the grid.

### 2026-06-18 (later) — GUI verified, recordings, the full-ANSI backend, Windows

A working session in the standalone repo (under WSLg, with `pygame-ce` + `pyte` in a
`.venv`) that grew the toolkit along the seams it was built for:

- **Proved the GUI by eye, then in CI.** `pygame-ce` in a venv rendered both renderers
  correctly under WSLg; then `test_gui_smoke` drove `pygame_ui.run` + the compositor to
  completion under the SDL `dummy` driver, so the blit/draw/flip path is covered headlessly
  (skips where pygame is absent). Added `max_seconds` to `pygame_ui.run` for a bounded loop.
- **`CastSource`** — replay an asciinema `.cast` recording through the same pipeline (the
  "recorded session" Source the design always anticipated); also makes a render reproducible.
- **`PyteTerminal`** — the "b-full" full-ANSI/VT100+ backend (wraps `pyte`, `ansi` extra), a
  drop-in for the VT52 `Terminal`. `tapterm --ansi`.
- **Windows (mostly):** `PipeSource` (non-pty, cross-platform), the **TCP bus transport**,
  and platform source-selection in `cli.py` — all tested on POSIX. `ConPtySource` (ConPTY via
  pywinpty, `win` extra) written against the documented API but **not yet run on Windows**
  (finishing it on real Windows is open work — see *What's left* below).
- **39 tests green**; `import tappty` still works with no optional deps. Decoupling held — the
  three new Sources and the second Terminal backend slotted in with no change to Session or
  renderers.

---

## Where it stands

- **Standalone (`~/tappty`):** the generic toolkit + `tapterm`, **87 tests green**, with a
  full-ANSI backend (with scrollback), recording replay, non-pty/Windows sources, a TCP bus,
  and ruff lint/format. **Now a git repo** (initial commit on `main`) with a CI workflow —
  though CI hasn't run yet (no remote pushed). The pygame draw path is smoke-tested headlessly
  (and eyeballed under WSLg). The Windows ConPTY source is written but untested on real Windows.
- **In the parent (`~/pdp10-empire/sixbit/term`):** untouched — the DECWAR galaxy/arena/
  `sbterm` launcher still run on the in-tree copy. So tappty and `sixbit/term` are **two
  copies** until the parent is rewired to consume tappty (the same drift the project is
  managing with `pyf66`). **A fix in one must land in the other** until then — the top live
  hazard.

---

## What's left

Roughly in priority order — the actionable work that remained when the doc set was
consolidated (this used to live in a separate handoff doc):

1. **Push to a GitHub remote so CI runs.** `~/tappty` is a git repo (initial commit on
   `main`) with `.github/workflows/ci.yml` — ruff lint/format + the pytest matrix on Python
   3.9–3.13, with `pygame-ce` + `pyte` so the GUI-smoke and ANSI tests run headlessly under
   the SDL `dummy` driver. The workflow has **never actually run** (no remote yet): create
   it, push, and confirm green — the pygame-ce-in-CI step in particular is unverified.
2. **Rewire `~/pdp10-empire/sixbit/term` to consume `tappty`** (an editable install or a
   namespace shim) instead of its own copy, so the two stop drifting (see "two copies"
   above). The game-specific bits left behind — the DECWAR galaxy view (`draw_galaxy` /
   `GalaxyPanel`) and the `decwar_runner` / `bot_runner` / `decwar_script_runner` factories
   — become consumers that import from `tappty` (a `GalaxyPanel` is just another panel
   `kind`; a game runner is just an `EngineSource`).
3. **Publish:** build the sdist/wheel and publish to PyPI once happy.
4. **Finish Windows on a real Windows box.** Done & tested on POSIX: `PyteTerminal`
   (`--ansi`), `PipeSource` (`--no-pty`), the TCP bus, and platform source-selection
   (`cli.py` picks `ConPtySource` on `os.name=="nt"` and auto-enables `--ansi`). **Untested:**
   `ConPtySource` (`win` extra, pywinpty) has never run on Windows — it's coded from the
   documented `PtyProcess` API and flagged provisional in the source. To finish:
   - `pip install -e '.[ansi,win]'` on Windows; drive `tapterm --ansi -- cmd` / `powershell`.
   - Verify the pywinpty details coded-from-docs-but-unconfirmed: does `.read()` raise
     `EOFError` at child exit, are `dimensions` row-major `(rows, cols)`, does `.write()`
     want `str`, what does `.wait()` return for the exit status.
   - Add a `windows-latest` CI lane (the pty tests already `skipif(os.name=="nt")`; a few
     others still assume a POSIX shell `sh` and would need guarding too).
   - Broaden the `Operating System` classifiers in `pyproject.toml` (POSIX-only today) and
     flip the README/DESIGN Windows wording from "provisional" to "verified".
   - Optional: `windows-curses` makes `curses_ui` work on Windows (the stdlib ships no
     `curses` there) — as an extra or a documented manual install.
5. **Possible features:** an arcade or web renderer (same `run(session, runner, …)` shape —
   `terminado` / `pyxtermjs` are references); and the deliberate gaps in [DESIGN.md](DESIGN.md)
   §9 if they ever bite (SGR color via `styled_rows()`/`cells()`, `wcwidth`-style cell widths,
   a renderer→session key map for full TUIs).

The deeper *why* — the design-decision narrative behind the observe/control bus, the Source
seam, and the talking stick — lives in the parent SIXBIT FORTRAN 66 project's Claude memory
notes (the `sbterm-instrumentation` and `decwar-port` notes, at `~/pdp10-empire`).
