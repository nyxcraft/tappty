# Changelog

All notable changes to **tappty**. No tagged or PyPI release yet, so everything below is **unreleased** work
toward `0.1.0`.

## 2026-06-17 — And so it begins...

- **13:10** — Started: the fixed-size VT52 `Terminal` grid
- **14:29** — the first pygame renderer
- **22:51** — First end-to-end run: a live program hosted on a pseudo-terminal, observed and
  driven through the `Session` taps and the talking-stick arbitration over the bus. This
  observe/control core is what tappty *is* — discovered by building a real thing.

## 2026-06-18 — standalone

- **23:35** — Extracted to a standalone package (first repo commit); `tapterm --headless -- echo …`
  round-tripped a real subprocess through the pty into the grid.

## 2026-06-19 — renderers, color, bus, packaging

- **10:54** — Runtime hardening: error surfacing and exit-code contract, bus security and
  bounded untrusted input, lifecycle/validation fixes, and the `CMD` completion-vs-shutdown race.
- **11:06** — Consolidated the byte-source reader loop into `Source._pump`.
- **12:08** — The detailed docs: `DESIGN.md`, `REFERENCE.md`, the `tapterm` guide.
- **13:14** — Windows: the `win` extra bundles `windows-curses` (curses CUI on Windows).
- **13:32** — `arcade_ui` renderer — the pyglet/OpenGL twin of `pygame_ui`.
- **14:23** — SGR **color** in the GUI (`cells()` + a shared `style` module), then in the
  curses CUI too.
- **14:55** — Raw-mode full-screen TUI input (`--raw`), so vim/htop work.
- **15:30** — `web_ui` renderer — the terminal in a browser over a websocket.
- **20:33** — Bold/italic/underline as real attributes; then strikethrough and blink.
- **20:46** — Packaging: `MANIFEST.in` + a validated (non-publishing) build.
- **21:10** — SGR color over the bus (styled snapshot + colored compositor panels).
- **21:37** — Wide CJK and single-code-point emoji at their true two columns.
- **22:44** — A GitHub Pages docs site: `docs/` sources, a `gh-pages/` builder, Actions deploy.
- **23:05** — Published a `tapterm` alias distribution alongside `tappty`.
- **23:50** — Docs-site nav and hero polish.

## 2026-06-20 — recording formats, video, demos, the terminal

- **10:52** — A **gallery** of runnable demos (screenshots + source).
- **11:15** — `.ttyrec` read/write, and recording any live session to `.cast`/`.ttyrec`
  (`--record`).
- **11:47** — Host & record real ANSI programs; bundle `nyancat`/`cbonsai` recordings (zero-dep
  replay).
- **12:01** — Play and export ANSI/BBS art `.ans` (CP437 + SAUCE) and animated `.3a`
  ASCII art.
- **12:27** — **Render to video** — any recording to mp4/webm/gif via ffmpeg
  (size/zoom/font/speed/crop), and `--render` of a live command (record + render in one step).
- **13:14** — Split `demos/` (runnable showpieces) from `examples/` (API coding examples).
- **13:50** — Gallery goes visual: an embedded movie, a looping GIF, a digital-rain mp4.
- **14:06** — `tapterm` is a **regular terminal** by default (full-ANSI + raw keys, closes on
  exit like xterm; `--cooked` for the line-oriented instrument mode) with xterm-style flags
  (`-e`, `-T`/`-title`, `-geometry`, `-cd`, `-hold`).
- **14:26** — Observe-and-control demos: an autopilot driving live `vim` (open loop) and a
  reactive bot that reads the stream and decides what to type (closed loop).
- **14:55** — A web-renderer demo with a real-browser (Playwright) screenshot.
- **15:42** — Named the GUI extras by graphics layer — `sdl` (pygame-ce) and `gl` (arcade).
- **16:40** — Docs-site polish: Gallery nav link, breadcrumbs, copyright + in-site license
  footer, a "beta" stamp, and author/AI-orchestration attribution.
