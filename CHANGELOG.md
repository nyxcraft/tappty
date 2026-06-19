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
  `ansi` extra), with scrollback via `HistoryScreen`.
- **Sources.** `PtySource` (POSIX pty), `EngineSource` (in-process `runner(emit, readline)`),
  `CastSource` (asciinema `.cast` replay — v1/v2, original timing, `speed`/`loop`),
  `PipeSource` (plain pipes, any OS), and `ConPtySource` (Windows ConPTY via pywinpty, the
  `win` extra — provisional, see [ROADMAP.md](ROADMAP.md)). The byte-source reader loop is
  shared in `Source._pump`.
- **Session.** Observe taps (`on_stream`/`on_frame`/`on_event`), control
  (`send_input`/`feed_key`), talking-stick arbitration (one driver at a time), and the
  bytes-on-the-wire / characters-on-the-glass decode.
- **Bus.** `BusServer`/`BusClient` carry the same observe/control contract over a Unix-domain
  socket *or* TCP, with a synchronous `CMD` capture primitive (send a line, get its output to
  the next prompt) for automated drivers.
- **Renderers.** `curses_ui` (the CUI plus the pure, unit-tested `viewport()` math) and
  `pygame_ui` (the GUI — lazy glyph cache, scrollback, optional text+PNG snapshots); the
  `compositor` tiles local (`SessionBacking`) and remote (`BusBacking`) panels in one window
  with per-tile pan/zoom.
- **`tapterm` CLI.** `--cui` / `--gui` / `--headless`, `--ansi`, `--no-pty`, `--cast`
  (`--speed` / `--loop`), `--cols` / `--rows`, `--snapshot`, `--exit-when-done`. Headless
  prints the final screen and exits with the child's own status.
- **Packaging & tooling.** `pyproject.toml` (extras `gui` / `ansi` / `win` / `dev`), MIT
  license, `src/` layout, a pytest suite (92 tests), ruff lint + format (line length 99), and
  a GitHub Actions CI matrix on Python 3.9–3.13 (pyte + pygame-ce so the ANSI and headless-GUI
  tests run).

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

See [ROADMAP.md](ROADMAP.md) for what's next, and [docs/](docs/) for the design, the API
reference, and the `tapterm` guide.
