# tappty documentation

`tappty` is a small instrumented-terminal toolkit: **host a program on a pseudo-terminal (or
an in-process runner, or a recording), observe and control it through one uniform contract,
and render it** — in a plain terminal (curses), a green-phosphor window (pygame), or headless.
Its premise is that every consumer — the screen, a socket logger, an automated driver — is an
equal client of the same observe/control contract, so a human and a bot can watch, and take
turns driving, the *exact same* session. The command-line program is **`tapterm`**; the
importable package is **`tappty`**.

```
   a program                                          consumers (all equal)
  ┌─────────┐   bytes    ┌──────────┐  grid    ┌─────────┐  observe   ┌──────────────┐
  │ Source  │──────────▶ │ Terminal │ ───────▶ │ Session │ ─────────▶ │ curses / GUI │
  │ (pty /  │            │  (glass) │          │ (taps + │            │ bus clients  │
  │  …)     │ ◀──────────│          │ ◀─────── │ control)│ ◀───────── │ compositor   │
  └─────────┘   input    └──────────┘  write   └─────────┘  control   └──────────────┘
```

## Start here — which doc do I want?

| If you want to… | Read |
|-----------------|------|
| install it and run the `tapterm` command | the top-level [README](../README.md), then **[TAPTERM](TAPTERM.md)** |
| use every `tapterm` flag, mode, recording, and recipe | **[TAPTERM](TAPTERM.md)** |
| build your own tool on the engine (taps, the bus, custom sources, dashboards) | **[REFERENCE](REFERENCE.md)** |
| understand how it works inside, and why | **[DESIGN](DESIGN.md)** |
| set up to develop and run the tests | the top-level [README](../README.md) |
| see when it started and what's changed | the [CHANGELOG](../CHANGELOG.md) |

## The documents

- **[TAPTERM.md](TAPTERM.md)** — the `tapterm` command in depth: every flag, the
  CUI / GUI / headless modes, the terminal model (`--cols`/`--rows`, `--ansi`), how a command
  is hosted (pty / `--no-pty` / Windows ConPTY), `--cast` replay, snapshots and automation, a
  recipes table, platform notes, and troubleshooting. *For using tapterm.*
- **[REFERENCE.md](REFERENCE.md)** — the programming/API reference: the full public surface
  with exact signatures (`Session`, the five `Source`s, the two `Terminal` backends,
  `BusServer`/`BusClient`, the renderers, the compositor), the shared contracts (the snapshot
  dict, the event names, the controller roles), how to write a custom `Source`, and worked
  examples. *For building on the library.*
- **[DESIGN.md](DESIGN.md)** — the architecture and the reasoning behind it: the decoupled
  Source → Terminal → Session → renderer/bus pipeline, the observe/control contract and the
  talking-stick arbitration, the bytes-vs-characters decode, the bus protocol, the concurrency
  and threading model, the security/trust model, the extraction boundary, the known
  limitations, and how the design was found (the provenance). *For modifying tappty.*
These four are the curated docs. One more project file lives at the repo root: the
[CHANGELOG](../CHANGELOG.md) — dated history, including when tappty started and first worked;
its footer and [DESIGN](DESIGN.md) §11 note the open work that's still ahead.

Quickstart and install live in the top-level [README](../README.md); the license is
[LICENSE](../LICENSE) (MIT © Nicholas J. Kisseberth).
