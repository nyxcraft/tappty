# Changelog

## 2026-06-17 — And so it begins...

- **13:10** — Started: the fixed-size VT52 `Terminal` grid
- **14:29** — the first pygame renderer
- **22:51** — First end-to-end run of observe/control core
- **22:51** — a multi-pane **compositor** and an **arena** that tiles many sessions
- **22:51** — a **curses** renderer beside the pygame one, and a `python -m` entry to host any program on a pty
- **23:43** — Compositor: eased inter-frame motion (glide) with motion trails.

## 2026-06-18 — standalone

- **00:15** — Compositor: scrolling terminal-replay in a pane.
- **23:30** — Extracted to a standalone package
- **23:35** — round-tripped a real subprocess through the pty into the grid.

## 2026-06-19 — renderers, color, bus, packaging

- **10:54** — Runtime hardening
- **11:06** — Consolidated the byte-source reader loop into `Source._pump`.
- **12:08** — The detailed docs: `DESIGN.md`, `REFERENCE.md`, the `tapterm` guide.
- **13:14** — Windows: the `win` extra bundles `windows-curses` (curses CUI on Windows).
- **13:32** — `arcade_ui` renderer — the pyglet/OpenGL twin of `pygame_ui`.
- **14:23** — SGR **color** in the GUI, then in the curses CUI too.
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
- **11:47** — Host & record real ANSI programs; bundle `nyancat`/`cbonsai` recordings
- **12:01** — Play and export ANSI/BBS art `.ans` (CP437 + SAUCE) and animated `.3a`
- **12:27** — **Render to video** — any recording to mp4/webm/gif via ffmpeg
- **12:41** — render of a live command (record + render in one step).
- **13:14** — Split `demos/` (runnable showpieces) from `examples/` (API coding examples).
- **13:50** — Gallery goes visual: an embedded movie, a looping GIF, a digital-rain mp4.
- **14:06** — `tapterm` is a **regular terminal** by default 
- **14:12** — `tapterm` takes xterm like arguments where useful
- **14:26** — Observe-and-control demos: an autopilot driving live `vim` (open loop)
- **14:35** — reactive bot demo that reads the stream and decides what to type (closed loop).
- **14:55** — A web-renderer demo with a real-browser (Playwright) screenshot.
- **15:42** — Named the GUI extras by graphics layer — `sdl` (pygame-ce) and `gl` (arcade).
- **16:40** — Docs-site polish
- **17:28** — Runtime hardening
- **17:33** — Fixed race conditions
- **17:40** — pypy packaging prep
- **18:11** — Bus/control hardening
- **18:16** — Improve replay/render robustness
- **18:19** — The CUI honors `--exit-when-done` / `-hold`
- **18:28** — Applied `ruff format`
- **18:29** — Across the tree; CI installs the `web` extra so the WebSocket/CSWSH tests run.
