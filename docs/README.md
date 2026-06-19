# tappty documentation

- **[DESIGN.md](DESIGN.md)** — the architecture: the decoupled Source → Terminal → Session
  → renderer/bus pipeline, the observe/control contract + talking stick, the Sources and the
  two Terminal backends (VT52 / full-ANSI), the compositor, and the extraction boundary. For
  someone modifying tappty.
- **[HISTORY.md](HISTORY.md)** — how the project got here, with dates (built as `sbterm`,
  then extracted).
- **[HANDOFF.md](HANDOFF.md)** — orientation for a new agent taking over: layout, how to
  run things, landmines, and open work.
- **[WINDOWS.md](WINDOWS.md)** — Windows support, paired with the full-ANSI / VT100
  ("b-full") backend: what runs on Windows, the gaps and how they were closed, and what's
  left. Mostly implemented; the ConPTY path is written but untested on real Windows.

Usage lives in the top-level [README](../README.md); the license is [LICENSE](../LICENSE)
(MIT © Nicholas J. Kisseberth).
