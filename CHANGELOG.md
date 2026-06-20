# Changelog

All notable changes to **tappty**, newest first. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project aims to follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). Dates are local (US Eastern).

tappty has not had a tagged or PyPI release yet, so everything below is **unreleased** work
toward `0.1.0`.

## Milestones

- **Started — 2026-06-17 13:10.** First code of the terminal layer, written as `sbterm`
  inside the *SIXBIT FORTRAN 66* project (a Python interpreter hosting Walter Bright's 1978
  *Empire* and 1979 *DECWAR* unmodified). The working environment was set up at 13:02:53 and
  the package stub (`__init__.py`) written at 13:10:30; the fixed-size VT52 `Terminal` grid
  and the first pygame renderer followed at 14:29 (times from the original source-file mtimes
  in `~/pdp10-empire/sixbit/term`).
- **First useful result — 2026-06-17 22:51:34.** The instrumented terminal ran end to end: a
  live program hosted on a pseudo-terminal, observed and driven through the `Session` taps and
  the talking-stick arbitration, over the instrumentation bus (`sixbit/term` commit
  `a146711`). This observe/control core is what tappty *is* — it was discovered by building a
  real thing, not designed in the abstract.
- **Extracted to a standalone package — 2026-06-18.** The generic core was lifted out of the
  game project into `~/tappty` (the same playbook used to extract its FORTRAN interpreter into
  `pyf66`). `tapterm --headless -- echo …` round-tripped a real subprocess through the pty
  into the grid — the same bar, now standalone. First repo commit 23:35.

## [Unreleased]

The `0.1.0` line — the generic toolkit and the `tapterm` command. Built across
2026-06-17 → 2026-06-19.

### Added

- **The pipeline.** `Source → Terminal → Session → renderers/bus`, where every consumer — a
  window, a socket logger, an automated driver — is an equal client of one observe/control
  contract, so a human and a bot can watch and take turns driving the same session.
- **Terminal backends.** `Terminal` — a fixed-size VT52 character grid with scrollback and no
  dependencies; `PyteTerminal` — a drop-in full-ANSI/VT100+ backend wrapping `pyte` (the
  `ansi` extra), with scrollback via `HistoryScreen`. Both expose `cells(offset)` — the styled
  parallel to `view_rows()` — carrying per-cell SGR attributes (`style.Cell`).
- **SGR color + attributes.** All four renderers draw the cell's full style: `cells()` + the
  dependency-free `style` module (the ANSI palette, `rgb`/`resolve`/`runs`) carry
  foreground/background, **bold**, *italic*, underline, strikethrough, blink, and reverse. The GUI backends
  (`pygame_ui`/`arcade_ui`/`web_ui`) render color in RGB, bold/italic via the font, and underline/strikethrough rules + a blink phase; `curses_ui` uses color pairs + `A_BOLD`/`A_ITALIC`/`A_UNDERLINE`/`A_BLINK`/`A_REVERSE`
  (256/truecolor approximated to the nearest ANSI-16). `"default"` resolves to phosphor green so
  uncolored output stays green; bold also brightens a named color. SGR faint/rapid-blink/conceal
  aren't modelled by pyte (and curses has no strikethrough), and the bus stays text-only.
- **Sources.** `PtySource` (POSIX pty), `EngineSource` (in-process `runner(emit, readline)`),
  `CastSource` (asciinema `.cast` replay — v1/v2, original timing, `speed`/`loop`),
  `TtyrecSource` (`.ttyrec` / NetHack-format replay), `AnsSource` (`.ans` ANSI/BBS art — CP437 +
  SAUCE), `ThreeASource` (`.3a` animated ASCII art — the DomesticMoth/asciimoth format),
  `PipeSource` (plain pipes, any OS), and `ConPtySource` (Windows ConPTY via pywinpty, the `win`
  extra — provisional, see [docs/DESIGN.md](docs/DESIGN.md) §11). The byte-source reader loop is
  shared in `Source._pump`; the replay/art sources share `_ReplaySource`, and
  `replay_source(path)` picks by extension.
- **Recording & export.** A `Recorder` observe-tap writes a live session's output stream, with
  timing, to an asciinema `.cast` (v2) or a `.ttyrec` file — the formats the replay sources read,
  so record → replay round-trips (and `--play in.ttyrec --record out.cast` transcodes).
  `export_ansi()` / `export_3a()` write the current screen as an ANSI-art `.ans` (CP437 + SGR) or
  a single-frame `.3a`.
- **Render to video.** `render_video()` / `tapterm --play X --render out.mp4` renders any
  recording (`.cast`/`.ttyrec`/`.ans`/`.3a`) to a real video file (`.mp4`/`.webm`/`.gif`/…) via
  ffmpeg — deterministic and faster-than-real-time, with controls for size (`--font-size`), zoom,
  font, speed, and a crop (`--crop`, an area of interest). `--render` also takes a **live
  command** (`tapterm --render out.mp4 --seconds 5 -- cmatrix`) — hosted, recorded, and rendered
  in one step. ffmpeg is found on the system or bundled by the `video` extra (imageio-ffmpeg).
- **Session.** Observe taps (`on_stream`/`on_frame`/`on_event`), control
  (`send_input`/`feed_key`), talking-stick arbitration (one driver at a time), and the
  bytes-on-the-wire / characters-on-the-glass decode.
- **Full-screen TUI input (`--raw`).** A raw input mode (`Session.raw_keys` / `send_key`) sends
  every keystroke straight to the program — no local echo or line buffer — translating special
  keys to VT sequences via the `tappty.keys` table (arrows, Home/End, PageUp/Down, F1–F12,
  Ctrl-combos). Every renderer honors it (the CUI also switches to `curses.raw()`), so
  `tapterm --ansi --raw -- vim` drives a real TUI. The default stays line-oriented.
- **Bus.** `BusServer`/`BusClient` carry the same observe/control contract over a Unix-domain
  socket *or* TCP, with a synchronous `CMD` capture primitive (send a line, get its output to
  the next prompt) for automated drivers.
- **Renderers.** `curses_ui` (the CUI plus the pure, unit-tested `viewport()` math); two
  interchangeable GUI backends with the same `run(...)` signature, both drawing SGR color —
  `pygame_ui` (pygame; lazy glyph cache, scrollback, optional text+PNG snapshots) and
  `arcade_ui` (the arcade/OpenGL twin, the `arcade` extra); and `web_ui` — a **browser**
  renderer over HTTP + a WebSocket (the `web` extra, `websockets`): a stdlib `http.server`
  serves one canvas page, the browser paints the `cells()` grid (color) and sends keystrokes
  back, several clients can connect, loopback-bound + optional `token`. The `compositor` tiles
  local (`SessionBacking`) and remote (`BusBacking`) panels in one window with per-tile
  pan/zoom, **in full color** — `Session.snapshot()`/the bus `FRAME` carry styled `cells`
  (`style.encode_row`, the same encoding the web renderer uses), so a remote panel isn't
  monochrome (`MAX_FRAME` raised to 256 KiB to fit a styled frame).
- **Wide glyphs.** CJK and single-code-point emoji (👍 🔥 ✅) render at their true two columns:
  the renderers honor pyte's wide-glyph continuation cell, and the curses CUI drops it
  (`style.char_width` + `_continuations`, locale set for ncursesw) so ncurses' own two-column
  advance lines up instead of shoving the rest of the row right. Grapheme clusters (ZWJ families,
  flags, skin-tones) stay out of scope — pyte splits/collapses them upstream (DESIGN §9).
- **`tapterm` CLI.** `--cui` / `--gui` / `--arcade` / `--web` / `--headless`, `--ansi`, `--raw`,
  `--no-pty`, `--play` (`.cast`/`.ttyrec`/`.ans`/`.3a`, `--cast` alias; `--speed` / `--loop`),
  `--record FILE`, `--render FILE` (+ `--fps`/`--font-size`/`--zoom`/`--font`/`--crop`/`--seconds`),
  `--cols` / `--rows`, `--port`, `--snapshot` (a `.ans`/`.3a` path exports art),
  `--exit-when-done`. `--play` uses the full-ANSI backend automatically (recordings are VT100+).
  Headless prints the final screen and exits with the child's own status.
- **Demos & examples.** `demos/` holds runnable showpieces — single-file apps you run to *see*
  a feature (the SGR color chart, the green digital rain, the compositor "mission control"),
  plus `demos/recordings/*.cast`: short sessions of real ANSI programs (`nyancat`, `cbonsai`)
  recorded with `--record`, which replay with zero dependencies and feed the gallery's "real
  programs" shots. `examples/` holds short, commented coding examples of the API — the observe
  taps, writing a custom `Source`, and driving a session over the bus.
- **Packaging & tooling.** `pyproject.toml` (extras `gui` / `arcade` / `web` / `video` / `ansi` /
  `win` / `dev`; `win` bundles pywinpty *and* windows-curses so `tappty[win]` gives both the
  ConPTY host and the curses CUI on Windows; `video` bundles ffmpeg for `--render`), MIT license,
  `src/` layout, a pytest suite (143 tests), ruff
  lint + format (line length 99), and a GitHub Actions CI matrix on Python 3.9–3.13 (pyte +
  pygame-ce so the ANSI and headless-GUI tests run).

### Changed

- Consolidated the three subprocess/pty sources' reader loops into one `Source._pump`.
- Unified the Session observer fan-out and refactored the bus into a verb→handler dispatch
  table; trimmed duplicated prose across the docs.

### Fixed

- `BusServer.stop()` now drops client connections, releases any sticks they held, clears the
  listener, and is restart-safe.
- Resolved the `CMD` capture completion-vs-shutdown race; a reply now distinguishes *reached
  the prompt* (clean) from *timed out* from *interrupted by shutdown*.
- Validate terminal dimensions (`>= 1`) and renderer `fps` (`>= 1`); harden malformed
  `HELLO` / `KEY` frames; fix compositor fit-to-tile sizing.
- `tapterm` reports a missing optional dependency (`--ansi` → pyte, `--gui` → pygame, `--cui`
  → curses, default Windows hosting → pywinpty) with a clear `pip install` hint and an exit
  code, instead of letting a raw `ModuleNotFoundError` traceback escape.

### Security

- The bus is a trusted-local control plane: the Unix socket file is owner-only (`0600`), TCP
  binds to loopback only unless `allow_remote=True`, an optional non-empty `token` is
  constant-time compared, protocol frames are size-capped on both ends, and `CMD` captures are
  byte-bounded.
- Untrusted `.cast` inputs are bounded: width/height clamped, v2 line reads capped, and the
  unstreamable v1 whole-file load refused above a size limit — so a malicious recording can't
  drive a huge allocation.

---

The feature surface is complete; packaging is validated. This repo publishes **two**
distributions, both built and `twine check`-clean via `packaging/build-dists.sh`: **`tappty`**
(the library + the `tapterm` command) and **`tapterm`** (a thin alias that ships no code and
just depends on `tappty`, so `pip install tapterm` resolves to it). A bare-venv install of each
works. The remaining work is the PyPI upload itself (`twine upload dist/*`) and verifying Windows
on a real box ([docs/DESIGN.md](docs/DESIGN.md) §11). See [docs/](docs/) for the design, the API
reference, and the `tapterm` guide.
