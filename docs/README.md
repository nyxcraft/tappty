# tappty documentation

Software Architecture, Design & Engineering by Nicholas J. Kisseberth.  
Code Synthesized via Anthropic Claude Code / Opus 4.8.  
Automated Code Review via OpenAI Codex / ChatGPT 5.5.

`tappty` is an instrumented-terminal toolkit — host a program on a pseudo-terminal, then
observe, control, and render it in a terminal (CUI), a green-phosphor window (GUI), or a
browser tab. Pick the document you need:

| If you want to… | Read |
|---|---|
| **see it in action** — screenshots + runnable demos | **[Gallery](GALLERY.md)** |
| run the **`tapterm`** command — the CUI / GUI / web / headless modes, the terminal model, recordings, snapshots, recipes | **[Command guide](TAPTERM.md)** |
| **build on the library** — `Session`, the `Source`s, both `Terminal` backends, the bus, the renderers and compositor | **[Programming reference](REFERENCE.md)** |
| understand **how it works inside, and why** — the Source → Terminal → Session → renderer/bus pipeline, concurrency, the trust model | **[Architecture & design](DESIGN.md)** |
| see **when it started and what's changed** | **[Changelog](../CHANGELOG.md)** |

New to tappty? Start with the **[command guide](TAPTERM.md)**. Writing your own tool on the
engine — a logger, an automated driver, a custom renderer — is the **[reference](REFERENCE.md)**.
The source and issue tracker are on [GitHub](https://github.com/nyxcraft/tappty).
