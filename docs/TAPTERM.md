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
- [The terminal model: size and ANSI](#the-terminal-model)
- [How the command is hosted: pty, pipes, Windows](#how-the-command-is-hosted)
- [Replaying recordings (`--cast`)](#replaying-recordings)
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
| `--headless` | no terminal, no display, no extras\* |
| `--ansi` (full-ANSI render) | the `ansi` extra |

\*POSIX pty hosting, `--no-pty`, and `--cast` need nothing. The exception is *default*
**Windows** hosting, which uses ConPTY — that needs `tappty[ansi,win]` and is still
provisional (see [Platform notes](#platform-notes)); `--no-pty` avoids it.

---

## The basics

Run `tapterm` with no arguments to host your shell:

```sh
tapterm
```

Host a specific command by putting it after `--` (everything after `--` is the command and its
arguments, untouched):

```sh
tapterm -- python3 -i
tapterm -- ssh user@host
tapterm -- bash -lc 'top -b -n1'
```

> **Put `tapterm`'s own flags *before* the `--`.** Everything after the command name is passed
> to the program, so `tapterm -- bash --gui` runs `bash --gui` (not what you want);
> `tapterm --gui -- bash` is correct. With no command at all, `tapterm` hosts `$SHELL`
> (falling back to `/bin/sh`).

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
- **Input:** Enter, Backspace, and printable ASCII are sent to the program. Arrow/function
  keys are not forwarded (the built-in model is line-oriented). **`Ctrl-]` quits** `tapterm`
  (and stops the hosted program).
- The CUI shows the **live** screen; it has no interactive scrollback (that's a GUI feature).

### GUI — `--gui` (pygame green-phosphor window)

Opens a green-on-black monospace window with a blinking block cursor — the showcase. Needs the
`gui` extra and a display.

```sh
tapterm --gui -- bash
```

- **Input:** Enter, Backspace, and printable (Unicode) characters go to the program.
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

No terminal and no display — and no extras for POSIX pty hosting, `--no-pty`, or `--cast`.
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

**Unicode** works in both backends by default: a program printing `café` or `→ ✓` shows those
characters (UTF-8 is decoded for the screen; pass-through is correct end to end).

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

## Replaying recordings

`tapterm` can replay an [asciinema](https://asciinema.org) `.cast` recording through the same
renderers instead of hosting a live command:

```sh
tapterm --cast session.cast              # replay at the recorded speed (auto-sizes to the recording)
tapterm --cast session.cast --speed 4    # 4x faster
tapterm --cast session.cast --gui --loop # loop it in the window (a screensaver of your session)
tapterm --ansi --cast session.cast       # use the full-ANSI backend if the recording is colorful
```

- The terminal is **sized to the recording** automatically (`--cols`/`--rows` are ignored).
- `--speed` multiplies playback rate; long idle gaps are still replayed at that rate.
- `--loop` repeats the recording (GUI/CUI; ignored under `--headless`, which plays once and
  prints the final frame).
- Both asciicast **v2** and the older compact **v1** formats are read.

To make a recording, use the `asciinema` tool (`asciinema rec session.cast`), then replay it
with `tapterm`. Replays are deterministic — useful for demos, docs, and visual regression
(`--headless --snapshot` renders a recording to a known final screen + PNG).

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
| A modern, colorful program | `tapterm --ansi -- htop` |
| A bigger grid | `tapterm --cols 120 --rows 40 -- vim` |
| Run a command, capture the final screen | `tapterm --headless -- make 2>&1` |
| Same, save it to a file | `tapterm --headless --snapshot build.txt -- make` |
| No pty (line-oriented / cross-platform) | `tapterm --no-pty -- python3 -u script.py` |
| Replay a recording | `tapterm --cast demo.cast --speed 2` |
| Loop a recording in a window | `tapterm --gui --loop --cast demo.cast` |
| Headless PNG of a recording | `SDL_VIDEODRIVER=dummy tapterm --gui --exit-when-done --snapshot demo --cast demo.cast` |

---

## Flags at a glance

```
tapterm [MODE] [OPTIONS] -- COMMAND [ARGS...]

MODE (mutually exclusive; default = GUI if pygame+display, else CUI)
  --cui                 curses character UI, in the current terminal
  --gui                 pygame green-phosphor window (needs the 'gui' extra + a display)
  --arcade              arcade/OpenGL green-phosphor window (needs the 'arcade' extra + a display)
  --headless            run to completion, print the final screen, exit with the child's code

OPTIONS
  --title TITLE         window / status-line title
  --cols N              terminal columns (default 80; positive integer)
  --rows N              terminal rows (default 24; positive integer)
  --ansi                full-ANSI/VT100+ backend (needs the 'ansi' extra); for modern programs
  --no-pty              host over plain pipes, no pty (cross-platform; line-oriented programs)
  --snapshot PATH       GUI: mirror the screen to PATH (+PATH.png) each second;
                        headless: write the final screen to PATH
  --exit-when-done      GUI: close the window when the hosted program exits
  --cast PATH           replay a .cast recording instead of a command (sizes to the recording)
  --speed F             --cast: playback speed multiplier (default 1.0)
  --loop                --cast: loop the recording (ignored under --headless)

COMMAND                 the program to host, after `--` (default: $SHELL)
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
