# tapterm — user's guide

`tapterm` is the command-line program that comes with `tappty`. It **hosts a program on a
pseudo-terminal and renders it** — in a plain terminal (curses), a green-phosphor window
(pygame), or headless (run to completion and print the final screen). This guide covers every
flag and mode, with practical examples and troubleshooting.

- The package is `tappty`; the command is `tapterm`.
- This guide is the **command** reference. To build your own tools on the same engine — taps,
  the bus, multi-pane dashboards, custom sources — see [REFERENCE.md](REFERENCE.md) (the
  library API) and [DESIGN.md](DESIGN.md) (architecture).
- `tapterm` is a single local window: one program, one human at the keyboard. Observing or
  driving a session from *another process* (a logger, a bot, a remote renderer) is a library
  feature (`BusServer`/`BusClient`), not a `tapterm` flag.

---

## Contents

- [Install](#install)
- [The basics](#the-basics)
- [Modes: CUI, GUI, headless](#modes)
- [The terminal model: size, ANSI, Unicode](#the-terminal-model)
- [How the command is hosted: pty, pipes, Windows](#how-the-command-is-hosted)
- [Recording & replaying sessions (`--record` / `--play`)](#recording-and-replaying-sessions)
- [Snapshots and automation](#snapshots-and-automation)
- [Recipes](#recipes)
- [Flags at a glance](#flags-at-a-glance)
- [Platform notes](#platform-notes)
- [Troubleshooting](#troubleshooting)

---

## Install

```sh
pip install tappty            # the core + tapterm; the CUI works out of the box
pip install 'tappty[gui]'     # add the green-phosphor window (pygame-ce)
pip install 'tappty[arcade]'  # add the arcade/OpenGL window (alternative GUI backend)
pip install 'tappty[web]'     # add the browser renderer for --web (websockets)
pip install 'tappty[ansi]'    # add the full-ANSI backend (pyte) for --ansi
pip install 'tappty[win]'     # Windows-native: ConPTY host + curses CUI (pywinpty, windows-curses)
```

After install, `tapterm` is on your `PATH`. You can combine extras: `pip install 'tappty[gui,ansi]'`.

What each mode needs:

| You want… | Needs |
|-----------|-------|
| `--cui` (curses) | a terminal — no extras on POSIX; on Windows, the `win` extra (`windows-curses`) |
| `--gui` (pygame window) | the `gui` extra **and** a display |
| `--arcade` (arcade window) | the `arcade` extra **and** a display (a GL context) |
| `--web` (browser tab) | the `web` extra (no display needed — it's a server) |
| `--headless` | no terminal, no display, no extras\* |
| `--ansi` (full-ANSI render) | the `ansi` extra |

\*POSIX pty hosting, `--no-pty`, and `--record` need nothing; `--play` needs the `ansi` extra
(recordings are full-ANSI). The exception is *default*
**Windows** hosting, which uses ConPTY — that needs `tappty[ansi,win]` and is still
provisional (see [Platform notes](#platform-notes)); `--no-pty` avoids it.

---

## The basics

Run `tapterm` with no arguments and it's a **regular terminal**: it hosts your `$SHELL` with
full-ANSI rendering and raw keystrokes, so colors, line-editing, arrow keys, tab-completion and
full-screen apps (vim, htop, less) all work — and the window closes when you exit the shell.

```sh
tapterm
```

Run a specific program instead of the shell — xterm-style with `-e`, or by putting it after `--`
(everything after is the command and its arguments, untouched):

```sh
tapterm -e vim notes.txt
tapterm -- python3 -i
tapterm -- ssh user@host
```

> **`-e` and `--` both end `tapterm`'s options**, so put `tapterm`'s own flags *first*:
> `tapterm --gui -e bash` is right; `tapterm -e bash --gui` passes `--gui` to bash. With no
> command at all, `tapterm` hosts `$SHELL` (falling back to `/bin/sh`).

**xterm-style flags.** Where it makes sense, `tapterm` takes the spellings xterm users expect:
`-e CMD …` (run a command), `-T` / `-title TITLE`, `-geometry COLSxROWS` (size — a trailing
`+X+Y` offset is accepted but ignored, since tappty doesn't place windows), `-cd DIR` (working
directory), and `-hold` (keep the window open after the program exits, instead of closing).

**Regular terminal vs. instrument.** The real-terminal behavior above — full-ANSI + raw keys, the
window closing on exit — is the default for any interactive session, and needs the `ansi` extra
(pyte); without pyte, `tapterm` falls back to the instrument mode below. Pass **`--cooked`** to
choose that mode explicitly: line-buffered input with local echo and line-editing, drawn on the
dependency-free VT52 grid. That's what the observe taps and the bus `CMD` capture expect — they
key off the line/prompt boundaries that raw mode doesn't have.

**Picking a mode.** With no mode flag, `tapterm` chooses the **GUI** when pygame is installed
*and* a display is available, otherwise the always-available **CUI**. Force a mode with
`--cui`, `--gui`, or `--headless` (these are mutually exclusive).

---

## Modes

### CUI — `--cui` (curses, in your terminal)

Takes over the current terminal and draws the hosted program's fixed grid, green on your
terminal's background, with a status line at the bottom. Works anywhere a terminal does, no
extras. With `--ansi`, colored programs render in **color** where your terminal supports it
(uncolored text stays phosphor green).

```sh
tapterm --cui -- bash
```

- **The status line** shows the title and grid size, e.g. ` tapterm :: bash  80x24 `. If your
  real terminal is smaller than the model, the view follows the cursor and the line shows
  ` view@<col>,<row> [partial] ` — the program still thinks it has the full 80×24; only what
  you *see* is a sub-rectangle (resize never changes the model). When the program exits, the
  line shows ` [done -- press a key] ` and `tapterm` waits for a keypress before quitting.
- **Input:** by default keystrokes are forwarded **raw** — arrows, function keys, and Ctrl-combos
  go straight to the program, so full-screen apps work. In `--cooked` mode it's line-oriented
  (Enter, Backspace, and printable text; arrows not forwarded). Either way, **`Ctrl-]` quits**
  `tapterm` (and stops the hosted program).
- The CUI shows the **live** screen; it has no interactive scrollback (that's a GUI feature).

### GUI — `--gui` (pygame green-phosphor window)

Opens a green-on-black monospace window with a blinking block cursor — the showcase. Needs the
`gui` extra and a display.

```sh
tapterm --gui -- bash
```

- **Input:** keystrokes are forwarded **raw** by default (arrows, function keys, Ctrl-combos, and
  printable Unicode), so full-screen apps work; `--cooked` makes it line-oriented (Enter,
  Backspace, printable text).
- **Scrollback:** mouse wheel up, or **PageUp**/**PageDown**, scrolls into history; a banner
  shows your position. Typing (or Enter/Backspace) **snaps back to live**.
- **Screenshot:** press **F12** to save a PNG (to your `--snapshot` path + `.png`, or
  `/tmp/tapterm.png`).
- **Closing:** click the window's close button to quit. Add **`--exit-when-done`** to close the
  window automatically a moment after the hosted program exits (otherwise the window stays open
  showing the final screen).
- **`--snapshot PATH`** mirrors the screen to a text file (and a `.png`) about once a second —
  handy for letting a script or an AI watch what you see (see [Snapshots](#snapshots-and-automation)).

**`--arcade`** opens the *same* green-phosphor window on the arcade (pyglet/OpenGL) stack
instead of pygame — same keys, scrollback, `F12`, `--snapshot`, and `--exit-when-done`. It
needs the `arcade` extra and a real GL display (where `--gui` also runs in software). Use it if
you prefer the arcade backend or already depend on it; otherwise `--gui` is the default window.

### Headless — `--headless` (run, print, exit)

No terminal and no display — and no extras for POSIX pty hosting, `--no-pty`, or `--record`
(`--play` needs the `ansi` extra).
Runs the program to completion, prints the **final screen** to stdout, and exits with the
**program's own exit code** — the scripting/CI mode.

```sh
tapterm --headless -- ls -la
echo "exit was $?"             # tapterm forwards the child's exit status
```

- `--snapshot PATH` additionally writes the final screen to that file.
- Because it returns the child's exit code, `tapterm --headless -- sh -c 'exit 7'` exits 7 — so
  it's safe in CI (a failing command makes the step fail).
- On **Windows**, *default* hosting uses ConPTY, which needs `tappty[ansi,win]` and is still
  provisional — use `--no-pty` (no extras) for headless CI there. See
  [Platform notes](#platform-notes).

### Web — `--web` (a browser tab)

Serves the terminal over HTTP + a WebSocket so you can watch and drive it in a **browser** —
from this machine, or any device that can reach it. Needs the `web` extra; no display required
(it's a server).

```sh
pip install 'tappty[web]'
tapterm --web -- bash              # then open http://127.0.0.1:8023/
tapterm --web --port 9000 -- bash  # page on :9000, websocket on :9001
```

- The browser draws tappty's grid (green phosphor + the same SGR **color** as the other UIs);
  keystrokes go back to the program. Add **`--raw`** for full-screen TUIs (`tapterm --web --ansi --raw -- vim`).
- **Several browsers can connect at once** — all watch; the talking stick decides who drives
  (typing takes it). This is the "human and a bot share one session" idea, in a browser.
- It binds **loopback (127.0.0.1) only** and has **no TLS** — it's a local control plane, like
  the bus. To reach it from another machine, tunnel it (`ssh -L`) rather than exposing the port.
- The page is on `--port` (default 8023); the WebSocket is on `--port + 1`. `tapterm` prints the
  URL on start; it runs until the program exits or you press **Ctrl-C**.

---

## The terminal model

### Size — `--cols` / `--rows`

The hosted program lives in a **fixed grid**, default **80×24**. Change it with `--cols` and
`--rows` (positive integers):

```sh
tapterm --cols 120 --rows 40 -- bash
```

The size is what the *program* sees and never changes while it runs — resizing your real window
(CUI) or the pygame window doesn't resize the program; the renderer just shows more or less of
the fixed grid (a viewport). This keeps the hosted program sealed in a predictable size.

### ANSI vs VT52 — `--ansi`

Two terminal backends:

- **Default (VT52-spirit).** A small, dependency-free model: text, wrap/scroll, the common
  control characters, and a handful of VT52 escapes. Perfect for line-oriented and period
  programs. It does **not** understand modern ANSI (colors, cursor addressing) — feed it a
  program that emits those and you'll see escape-sequence soup.
- **`--ansi` (full ANSI/VT100+).** Backed by `pyte` (the `ansi` extra). Use it for anything
  modern — shells with colored prompts, `vim`, `htop`, `git log`, etc. It interprets cursor
  movement, erasing, and line edits correctly.

```sh
tapterm --ansi -- vim
tapterm --ansi -- bash      # colored prompts/output render cleanly
```

> Note: `--ansi` renders **color** in every interactive renderer — the GUI (`--gui` /
> `--arcade`) in full RGB, and the CUI (`--cui`) via your terminal's colors where it supports
> them — covering foreground/background, bold (as a brighter shade), and inverse, while
> uncolored text stays phosphor green. Only `--headless`/`--snapshot` output is plain text.

### Unicode and wide characters

Unicode works in both backends: a program printing `café` or `→ ✓` shows those characters
(UTF-8 is decoded for the screen; pass-through is correct end to end).

**Wide glyphs** — CJK (`日本語`, `中文`) and single-code-point emoji (`👍 🔥 ✅`) — occupy their
true **two columns**, so neighboring text lines up instead of crowding. This is most reliable
with `--ansi` (the `pyte` backend tracks the width). In the CUI it relies on your terminal being
in a UTF-8 locale (`$LANG`/`$LC_ALL`); a non-UTF-8 locale falls back to single-width but never
garbles the rest of the line. The GUI and web renderers draw the glyph in the font you have, so
how a given emoji *looks* depends on that font's coverage — but its width is always correct.

**What doesn't work: grapheme clusters.** Emoji built from several code points — ZWJ families
(`👨‍👩‍👧`), flags (`🇺🇸`), and skin-tone modifiers (`👋🏽`) — are split or collapsed by `pyte`
before tapterm sees them (the family shows as just `👨`, the flag as two letter-boxes). This is
a deliberate limit, not a bug; see [DESIGN.md](DESIGN.md) §9.

---

## How the command is hosted

By default `tapterm` runs your command on a **pseudo-terminal** so it behaves exactly as it
would in a real terminal (interactive prompts, line editing, programs that check for a tty).

- **POSIX:** a real pty. This is the default and the most faithful.
- **`--no-pty`:** host over **plain pipes** instead — no tty. Cross-platform (including
  Windows), but because there's no tty the child knows it isn't interactive: many programs
  **block-buffer** their output (you see nothing until they flush or exit) and skip prompts.
  Best for cooperative, line-oriented programs; not for full interactive ones.

  ```sh
  tapterm --no-pty -- python3 -c "print('hello from a pipe')"
  ```

- **Windows:** there's no POSIX pty, so `tapterm` hosts the command on a **Windows
  pseudo-console (ConPTY)** via the `win` extra, and automatically enables `--ansi` (ConPTY
  emits VT100+). This path is implemented but **not yet validated on real Windows** — treat it
  as provisional. `--no-pty` (pipes) is the more conservative choice on Windows today.

---

## Driving full-screen TUIs — `--raw`

By default `tapterm` is **line-oriented**: it echoes your keystrokes locally and sends a whole
line when you press Enter (good for prompts you want to *watch* being typed). Arrow keys,
function keys, and Ctrl-combos aren't sent to the program.

**`--raw`** switches to character-at-a-time input: every keystroke goes straight to the program
with no local echo or line editing, and special keys are translated to their VT escape
sequences — so full-screen programs like **`vim`**, **`htop`**, or **`less`** work. The program
handles its own echo and redraw, exactly as under a real terminal.

```sh
tapterm --ansi --raw -- vim        # the usual combo: full-ANSI render + raw keys
tapterm --ansi --raw -- htop
```

- Pair it with **`--ansi`** for anything that paints the screen with color and cursor moves —
  that's the typical combination.
- Mapped (normal cursor-key mode): arrows, Home/End, PageUp/Down, Insert/Delete, F1–F12, Tab,
  Esc, and Ctrl-letters. In the CUI, Ctrl-C/Z/\\ reach the program (raw tty).
- Still local: mouse-wheel scrollback, **Ctrl-]** to quit the CUI, the GUI close button, and
  **F12** snapshots in the GUI.

---

## Recording and replaying sessions

`tapterm` reads and writes two terminal-session recording formats —
[asciinema](https://asciinema.org) **`.cast`** (v2 NDJSON, or the older compact v1) and
**`.ttyrec`** (the ttyrec / termrec / NetHack format) — and plays two text-art formats:
**`.ans`** ANSI/BBS art (CP437 + ANSI + SAUCE) and **`.3a`** animated ASCII art. The format is
picked automatically by file extension.

**Replay** a recording (or play art) through the same renderers instead of hosting a live
command, with `--play`:

```sh
tapterm --play session.cast               # replay at the recorded speed
tapterm --play session.ttyrec             # a .ttyrec (ttyrec / NetHack format)
tapterm --play art.ans --gui              # ANSI / BBS art
tapterm --play anim.3a --gui --loop       # animated ASCII art (.3a), looping
tapterm --play session.cast --speed 4     # 4x faster
tapterm --play session.cast --gui --loop  # loop it in the window (a screensaver of your session)
```

- Recordings are VT100+, so `--play` **uses the full-ANSI backend automatically** (it needs the
  `ansi` extra: `pip install 'tappty[ansi]'`).
- A `.cast`/`.ans` carries its size, so the terminal is **sized to the recording**
  (`--cols`/`--rows` ignored); `.ttyrec` carries none, so it uses 80×24 (set `--cols`/`--rows`).
- `--speed` multiplies playback rate; long idle gaps are still replayed at that rate.
- `--loop` repeats the recording (GUI/CUI; ignored under `--headless`, which plays once and
  prints the final frame).
- `--cast` is kept as an alias for `--play`.

**Record** the session you're running with `--record FILE` — it captures the program's output
stream, with timing, as you use it:

```sh
tapterm --record session.cast -- bash         # record a shell session to asciicast v2
tapterm --record demo.ttyrec --gui -- vim      # record while you drive it in the window
tapterm --headless --record out.cast -- make   # record a non-interactive run
tapterm --play in.ttyrec --record out.cast     # transcode: replay one, record the other
```

The format follows the extension. Recordings are deterministic to replay — useful for demos,
docs, and visual regression (`--headless --snapshot` renders a recording to a known final
screen + PNG). `.cast` files also play in the `asciinema` ecosystem and its GIF/SVG tooling.

**Export a screen as art:** `--headless --snapshot screen.ans` writes the final screen as a `.ans`
file (CP437 + SGR), and `--snapshot screen.3a` writes it as a single-frame `.3a` — instead of
plain text. Both read back with `--play`.

### Render a recording to a video

`--play RECORDING --render OUT.mp4` turns a recording into a real video file (`.mp4` / `.webm` /
`.gif` / …, by extension) via ffmpeg, instead of displaying it:

```sh
tapterm --play demo.cast --render demo.mp4                 # a recording to MP4
tapterm --play demo.cast --render demo.gif --zoom 0.5      # half-size GIF
tapterm --play nyan.cast --render nyan.mp4 --speed 2 --fps 30
tapterm --play big.ttyrec --render clip.mp4 --crop 10,4,60,20   # just a region
tapterm --render cmatrix.mp4 --seconds 5 -- cmatrix        # a LIVE program, straight to video
```

- `--font-size` sets the glyph size (the main size control); `--zoom F` scales the finished
  frame (crisp, e.g. `2`); `--font TTF` picks a font; `--speed` and `--fps` control pacing.
- `--crop COL,ROW,COLS,ROWS` renders only that region of the grid (area of interest).
- Pass a command instead of `--play` to render a **live** program directly — it's hosted,
  recorded, and rendered in one step. `--seconds N` caps programs that don't exit on their own
  (cmatrix, htop, a shell); a program that exits (a build, `ls`, cbonsai) needs no cap.
- The render is deterministic and faster-than-real-time. It needs the `gui` + `ansi` extras and
  **ffmpeg** — a system binary, or `pip install 'tappty[video]'` for a bundled one.
- **No display required.** Although it uses pygame, it rasterizes *off-screen* (SDL's `dummy`
  driver) — there's no window — so `--render` runs over plain SSH, in a curses console, in cron,
  or in CI with no X11/Wayland. (Only the interactive `--gui` / `--arcade` windows need a display.)

---

## Snapshots and automation

- **`--snapshot PATH`**
  - *GUI:* mirrors the live screen to `PATH` (text) and `PATH.png` (pixels) roughly once a
    second, so a separate script or an AI can watch the same thing you see.
  - *Headless:* writes the final screen to `PATH` (in addition to printing it).
- **`--headless`** prints the final screen to stdout and exits with the child's return code —
  the building block for scripting and CI.
- **Exit code:** only `--headless` forwards the program's exit status; the interactive modes
  return 0 when you close them.

**Headless GUI render (no display).** You can drive the pygame renderer with no display by
forcing SDL's dummy driver — useful to produce a PNG in CI:

```sh
SDL_VIDEODRIVER=dummy tapterm --gui --exit-when-done --snapshot out -- bash -lc 'ls; echo done'
# -> out (text) and out.png (pixels), then exits
```

(For richer automation — observe/drive a session from another process, multi-pane dashboards —
use the library; see [REFERENCE.md](REFERENCE.md).)

---

## Recipes

| Goal | Command |
|------|---------|
| Host your shell, best available UI | `tapterm` |
| Force the in-terminal curses UI | `tapterm --cui -- bash` |
| Green-phosphor window | `tapterm --gui -- bash` |
| A full-screen TUI (color + keys) | `tapterm --ansi --raw -- htop` |
| A bigger grid | `tapterm --cols 120 --rows 40 --ansi --raw -- vim` |
| Run a command, capture the final screen | `tapterm --headless -- make 2>&1` |
| Same, save it to a file | `tapterm --headless --snapshot build.txt -- make` |
| No pty (line-oriented / cross-platform) | `tapterm --no-pty -- python3 -u script.py` |
| Record a session | `tapterm --record demo.cast -- bash` |
| Replay a recording | `tapterm --play demo.cast --speed 2` |
| Replay a .ttyrec | `tapterm --play game.ttyrec` |
| Play ANSI/BBS art | `tapterm --play art.ans --gui` |
| Export the screen as ANSI art | `tapterm --headless --snapshot screen.ans -- neofetch` |
| Render a recording to MP4 | `tapterm --play demo.cast --render demo.mp4` |
| Render a live program to MP4 | `tapterm --render rain.mp4 --seconds 5 -- cmatrix` |
| Watch/drive it in a browser | `tapterm --web -- bash` → open `http://127.0.0.1:8023/` |
| Loop a recording in a window | `tapterm --gui --loop --play demo.cast` |
| Headless PNG of a recording | `SDL_VIDEODRIVER=dummy tapterm --gui --exit-when-done --snapshot demo --play demo.cast` |

---

## Flags at a glance

```
tapterm [MODE] [OPTIONS] -- COMMAND [ARGS...]

MODE (mutually exclusive; default = GUI if pygame+display, else CUI)
  --cui                 curses character UI, in the current terminal
  --gui                 pygame green-phosphor window (needs the 'gui' extra + a display)
  --arcade              arcade/OpenGL green-phosphor window (needs the 'arcade' extra + a display)
  --web                 serve in a browser over a websocket (needs the 'web' extra)
  --headless            run to completion, print the final screen, exit with the child's code

OPTIONS
  -e, --exec CMD ...    run CMD instead of $SHELL, xterm-style (everything after -e; like `-- CMD`)
  -T, -title TITLE      window / status-line title  (--title)
  -geometry, -g WxH     terminal size COLSxROWS, xterm-style; a trailing +X+Y offset is ignored
  -cd, --cwd DIR        run the hosted program in this working directory
  -hold                 keep the window open after the program exits (a terminal session closes)
  --cooked, --line      line-oriented instrument mode (local echo on the VT52 grid) instead of the
                        regular-terminal default (full-ANSI + raw keys)
  --port N              --web: HTTP port for the page (websocket = N+1; default 8023)
  --cols N              terminal columns (default 80; positive integer; --geometry overrides)
  --rows N              terminal rows (default 24; positive integer; --geometry overrides)
  --ansi                full-ANSI/VT100+ backend (needs the 'ansi' extra); for modern programs
  --raw                 forward keystrokes raw (arrows/Fn/Ctrl, no echo) for TUIs; pair with --ansi
  --no-pty              host over plain pipes, no pty (cross-platform; line-oriented programs)
  --snapshot PATH       GUI: mirror the screen to PATH (+PATH.png) each second;
                        headless: write the final screen to PATH (.ans/.3a paths export art)
  --exit-when-done      GUI: close the window when the hosted program exits
  --play FILE           replay a .cast/.ttyrec recording or play .ans/.3a art, instead of a
                        command (--cast alias; uses the ANSI backend; sizes to a .cast/.ans)
  --record FILE         record the session's output to a .cast or .ttyrec file as it runs
  --render FILE         render to a video (.mp4/.webm/.gif/...): a --play recording, or a
                        live command (it's recorded then rendered, one step)
  --seconds N           --render of a live command: stop after N seconds (non-exiting programs)
  --fps N               --render: output frame rate (default 30)
  --font-size N         --render: glyph size in points (size/zoom control; default 18)
  --zoom F              --render: scale the finished frame (e.g. 2 for crisp 2x)
  --font TTF            --render: font file to render with (default DejaVu Sans Mono)
  --crop C,R,COLS,ROWS  --render: render only this grid region (area of interest)
  --speed F             --play: playback speed multiplier (default 1.0)
  --loop                --play: loop the recording (ignored under --headless)

COMMAND                 the program to host, after `--` or `-e` (default: $SHELL, as a terminal)
```

(`tapterm --help` lists the same flags; this table adds the default-mode rule and the
display / positive-integer notes that the bare `--help` leaves out.)

---

## Platform notes

- **Linux / BSD:** the CUI works in any terminal; the GUI needs `gui` + an X11/Wayland display.
  Over SSH or cron (no display), plain `tapterm` falls back to CUI automatically. An explicit
  `--gui` *without the `gui` extra* fails with a clear install hint; `--gui` *with no display*
  surfaces pygame/SDL's own video-initialization error instead.
- **macOS:** the GUI works (native, no `DISPLAY` needed); CUI works in Terminal/iTerm.
- **Windows:** the GUI (pygame) and `--headless` work; the CUI needs `windows-curses`, which
  the `win` extra installs (`pip install 'tappty[win]'`). Hosting a command uses ConPTY (also
  in the `win` extra) and auto-enables `--ansi`, but that path is **provisional/untested** —
  prefer `--no-pty` for now.
- **`--headless` needs neither a terminal nor a display**, so it's the safe choice in CI and
  scripts on any platform.

---

## Troubleshooting

- **Escape-sequence soup / garbled colors** (you see things like `^[[0;32m`): the program emits
  modern ANSI but you're on the VT52 model. Add **`--ansi`** (and `pip install 'tappty[ansi]'`).
- **`--gui` fails / "needs pygame"**: install the GUI extra — `pip install 'tappty[gui]'` — and
  make sure a display is available. Over SSH, use `--cui` or `--headless`, or forward X /
  set `SDL_VIDEODRIVER=dummy` for a windowless render.
- **`--no-pty` shows nothing until the program exits**: that's output buffering — without a tty
  many programs block-buffer stdout. Run the child unbuffered (e.g. `python3 -u`,
  `stdbuf -oL …`) or use the default pty instead of `--no-pty`.
- **"command not found" / it just exits**: the command after `--` must be a real executable and
  its argv; e.g. `tapterm -- bash -lc 'echo hi'`, not `tapterm -- 'bash -lc "echo hi"'`.
- **Mojibake on a pty program** (`café` shows as `cafÃ©`): the program is emitting non-UTF-8
  bytes; the screen decodes as UTF-8 by default. This is uncommon for modern programs; the raw
  bytes are always preserved on the stream side (a library concern — see REFERENCE).
- **My flags are being passed to the program**: put `tapterm`'s flags *before* `--`. Anything
  after the command name belongs to the command.
