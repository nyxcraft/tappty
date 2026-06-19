# Roadmap

What's next for **tappty** — current status and the open work in priority order. Dated,
completed work is in [CHANGELOG.md](CHANGELOG.md); the architecture is in
[docs/DESIGN.md](docs/DESIGN.md).

## Status

The generic toolkit and the `tapterm` command exist and are green: **92 tests**, a full-ANSI
backend (with scrollback), `.cast` replay, non-pty and Windows sources, a Unix + TCP bus, and
ruff lint/format. `~/tappty` is a git repo on `main` with a CI workflow. **Not yet shipped:**
no tagged or PyPI release; CI has never actually run (no remote pushed); and the Windows
ConPTY source is written but unverified on real Windows.

## What's left (roughly in priority order)

1. **Publish:** build the sdist/wheel and publish to PyPI once happy.
2. **Finish Windows on a real Windows box.** Done & tested on POSIX: `PyteTerminal`
   (`--ansi`), `PipeSource` (`--no-pty`), the TCP bus, and platform source-selection
   (`cli.py` picks `ConPtySource` on `os.name=="nt"` and auto-enables `--ansi`). **Untested:**
   `ConPtySource` (`win` extra, pywinpty) has never run on Windows — it's coded from the
   documented `PtyProcess` API and flagged provisional in the source. To finish:
   - `pip install -e '.[ansi,win]'` on Windows; drive `tapterm --ansi -- cmd` / `powershell`.
   - Verify the pywinpty details coded-from-docs-but-unconfirmed: does `.read()` raise
     `EOFError` at child exit, are `dimensions` row-major `(rows, cols)`, does `.write()`
     want `str`, what does `.wait()` return for the exit status.
   - Add a `windows-latest` CI lane (the pty tests already `skipif(os.name=="nt")`; a few
     others still assume a POSIX shell `sh` and would need guarding too).
   - Broaden the `Operating System` classifiers in `pyproject.toml` (POSIX-only today) and
     flip the README/DESIGN Windows wording from "provisional" to "verified".
   - Optional: `windows-curses` makes `curses_ui` work on Windows (the stdlib ships no
     `curses` there) — as an extra or a documented manual install.
3. **Possible features:** an arcade or web renderer (same `run(session, runner, …)` shape —
   `terminado` / `pyxtermjs` are references); and the deliberate gaps in
   [docs/DESIGN.md](docs/DESIGN.md) §9 if they ever bite (SGR color via
   `styled_rows()` / `cells()`, `wcwidth`-style cell widths, a renderer→session key map for
   full TUIs).
