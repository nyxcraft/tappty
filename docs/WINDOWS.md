# Windows support

> **Status: MOSTLY IMPLEMENTED — the cross-platform half is built and tested; the Windows
> ConPTY path is written but UNTESTED on real Windows.** The coupled full-ANSI / VT100
> backend (`PyteTerminal`, the `ansi` extra) is **done and tested**. Built and tested on
> POSIX: `PipeSource` (non-pty, `--no-pty`), the **TCP bus transport**, and platform source
> selection in `tapterm`. Written but **not yet exercised on Windows** (no Windows in the
> dev env, and `pywinpty` doesn't install off-Windows): `ConPtySource` (the `win` extra).
> The one remaining task is to **run it on a real Windows box** and fix what breaks. See §5
> for the per-stage state.

This is the architecture companion's Windows chapter: what runs on Windows, the gaps and
how they were closed, and what's left. Originally a deferred plan; updated as the work
landed.

---

## 1. The one insight

The project's whole point — every consumer is an equal client of one observe/control
contract, and only the **Source** knows where the bytes come from ([DESIGN.md](DESIGN.md)
§1, §2.1) — is exactly what makes Windows a *small, contained* job rather than a port. The
platform-bound surface is four spots, and three of them are leaves:

| Spot | File | What's POSIX |
|------|------|--------------|
| Hosting an external command | `source.py` — `PtySource.start()` | `pty` / `termios` / `fcntl`, `os.read`/`os.write` on a master fd, `start_new_session` |
| The cross-process bus | `bus.py` | `socket.AF_UNIX` (server bind + client connect) |
| The CUI renderer | `curses_ui.py` | `import curses` (no stdlib curses on Windows) |
| Source selection | `cli.py` | hardcodes `PtySource` |

Everything else — `terminal.py`, `session.py`, the talking stick, `EngineSource`,
`pygame_ui.py`, `compositor.py` (`SessionBacking`) — is pure stdlib `threading`/`queue` +
pygame, and is already cross-platform. Windows is the first real test of the Source-seam
claim; the surface above is the proof the claim holds.

---

## 2. What already runs on Windows today

The *contract* is portable now, unmodified:

- Hosting an **in-process** runner via `EngineSource`, driven through a `Session`.
- Rendering it in the **pygame** window (`pygame_ui`) — pygame is cross-platform.
- Tiling in-process sessions in the **compositor** via `SessionBacking`.

So an in-process program (a REPL, a game engine, a bot) can be hosted and rendered on
Windows right now. What does *not* work on Windows is everything that touches the four
spots in §1: hosting an external subprocess, the bus, and the curses CUI.

A cheap first deliverable (§5, stage 1) is simply to **prove and pin this** — a Windows CI
job (or a documented manual check) that exercises `EngineSource` + pygame — so the story is
"the core is portable; only process-hosting is POSIX," backed by a test rather than a
claim.

---

## 3. The three gaps and their fixes

### 3.1 Hosting an external command — a new Windows `Source`

This is the substantive gap and the reason for the VT100 pairing. Two options, with a sharp
tradeoff:

**(a) `PipeSource` — `subprocess.Popen` with plain pipes, no pty.** This is the "non-pty
Source" HANDOFF.md gestures at. Zero new dependencies, works on **both** POSIX and Windows,
slots straight into the `Source` interface (`start(on_output, on_wait, on_exit)` +
`send_input`). It is the cheapest path to "host an external command on Windows."

> Limitation: with no tty the child detects it is not interactive — many programs
> block-buffer stdout (you see nothing until they flush/exit) and skip prompts/raw mode.
> Fine for cooperative, line-oriented children (tappty's PDP-10-game heritage); not for
> programs that demand a terminal. `on_wait` can't fire (no readline boundary), same as
> `PtySource`.

**(b) `ConPtySource` — the Windows pseudoconsole.** The proper answer for interactive
programs (`cmd`, PowerShell, anything that wants a console). Built on the Win32
pseudoconsole API (`CreatePseudoConsole` / `ResizePseudoConsole` / `ClosePseudoConsole`,
Windows 10 v1809 / Server 2019 and later): create pipes, attach them via `STARTUPINFOEX`
with `PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE`, then `CreateProcess`. Access it either through
**`pywinpty`** (the maintained, de-facto package — what Jupyter/terminado use; wraps
winpty/ConPTY) or via raw `ctypes` for a zero-dependency implementation.

**The gotcha that couples this to the VT100 work:** a ConPTY emits **ANSI / VT100+ CSI**
sequences, but the current `Terminal` is "VT52 spirit" — it honors only `ESC H/J/K/Y` and
`ESC A`–`D` (`terminal.py`, `_handle_esc`). Feed ConPTY output into it and you get escape
soup. So a *genuinely useful* `ConPtySource` requires the full-ANSI Terminal backend. See
§4.

### 3.2 The bus — a non-AF_UNIX transport

`bus.py` opens `socket.AF_UNIX`. CPython does not expose `AF_UNIX` on Windows (the kernel
has had it since Windows 10 1803, but the Python `socket` module doesn't surface it
portably). The protocol itself is **transport-agnostic** — newline-delimited messages,
JSON payloads — so only the listen/connect plumbing changes. Add a **TCP-on-localhost**
transport (bind `127.0.0.1` on an ephemeral port, write the port where the socket path goes
today) as the Windows form, selected by platform. Named pipes are an alternative but
heavier; TCP-localhost is the smallest contained change. One server still = one session.

### 3.3 The CUI renderer — `windows-curses`

`curses_ui.py` needs the `_curses` C extension, absent from the Windows stdlib. The
`windows-curses` package supplies it and the renderer works mostly unchanged. **Low
priority** — the pygame GUI is the showcase and is already cross-platform; the CUI on
Windows is a nicety, not a blocker. Could ship as a documented `pip install windows-curses`
extra rather than a code change.

---

## 4. Why this is paired with the VT100 / "b-full" backend

The deferred full-ANSI Terminal backend (a `pyte`-backed grid model, "b-full" in the
original notes) and Windows support are **one project, not two**:

- Today's `Terminal` is VT52-only by design (the games it was born for are VT52-era).
- The only Windows way to host a *real interactive* program faithfully is ConPTY, and
  ConPTY speaks ANSI/VT100+.
- Therefore `ConPtySource` without a full-ANSI Terminal renders garbage. The backend is a
  hard prerequisite for the high-value half of Windows support.

The clean shape: introduce a pluggable Terminal backend behind the same read interface the
renderers already use (`.grid` / `snapshot()` / `view_rows()` / `rows_text()` + `cx`/`cy`),
ship a `pyte`-backed implementation as the `b-full` option, then build `ConPtySource`
against it. `PipeSource` (§3.1a) and the bus transport (§3.2) do **not** need b-full and can
land independently — they're the parts of Windows support that are cheap and decoupled.

---

## 5. Staged plan — state

The b-full / full-ANSI backend (§4) landed first as **`PyteTerminal`** (`pyte_terminal.py`,
the `ansi` extra, `tapterm --ansi`) — done and tested (`test_pyte_terminal`). Then:

1. **Claim what's free.** ☐ Not done — needs a real Windows runner. The portability is in
   place (core + `EngineSource` + pygame are pure/cross-platform); what's missing is a
   Windows CI job that proves it. No repo/CI yet, so this is pending the same setup work.
2. **`PipeSource`** (no pty). ✅ **Done & tested on POSIX** (`test_pipe_source`). Cross-
   platform, zero deps; gives POSIX a no-pty option too. `tapterm --no-pty`.
3. **Bus over TCP.** ✅ **Done & tested** (`test_bus_tcp`). `BusServer`/`BusClient` take a
   `(host, port)` tuple → TCP behind the unchanged protocol; `AF_UNIX` is now behind a
   `getattr`, so `bus.py` imports cleanly on Windows.
4. **`cli.py` source selection.** ✅ **Done.** `_make_source` picks `PtySource` on POSIX,
   `ConPtySource` on `os.name == "nt"`, or `PipeSource` when `--no-pty`. `--ansi` selects the
   terminal backend.
5. **`ConPtySource` + the full-ANSI backend.** ◑ **Written, UNTESTED on Windows.**
   `ConPtySource` (the `win` extra, pywinpty) is implemented against the `PtyProcess` API and
   structurally mirrors `PtySource`; the backend it needs (`PyteTerminal`) is done. It cannot
   be run here (no ConPTY; pywinpty is Windows-only). **This is the remaining work.**
6. **(Optional) `windows-curses`** for the CUI. ☐ Not done — documented as a `pip install`
   the user adds; `curses_ui` is otherwise unchanged.

---

## 6. What's left

Just one thing of substance: **run it on real Windows.** Bring up a Windows box (or CI
runner), `pip install -e '.[ansi,win]'`, and try `tapterm --ansi -- cmd` /
`tapterm --ansi -- powershell`. Expect to fix details in `ConPtySource` — the pywinpty
`PtyProcess` read/spawn/exit semantics (does `.read()` raise `EOFError` at exit, are
`dimensions` row-major, does `.write()` want str) are coded from the documented API but
unverified. Then add the Windows CI job (stage 1) so it doesn't regress, and consider
broadening the `Operating System` classifiers in `pyproject.toml` (currently POSIX-only)
once it actually works there.
