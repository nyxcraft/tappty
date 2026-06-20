# Roadmap

What's next for **tappty** — current status and the open work in priority order. Dated,
completed work is in [CHANGELOG.md](CHANGELOG.md); the architecture is in
[docs/DESIGN.md](docs/DESIGN.md).

## Status

The generic toolkit and the `tapterm` command exist and are green: **124 tests**, a full-ANSI
backend (with scrollback, SGR color, and raw-key input for full TUIs), `.cast` replay, non-pty
and Windows sources, a Unix + TCP bus, and four renderers — the curses CUI, two GUI backends
(pygame and arcade/OpenGL), and a browser renderer over a WebSocket — plus ruff lint/format.
`~/tappty` is a git repo on `main` with a CI workflow. **Not yet shipped:** no tagged or PyPI
release; CI has never actually run (no remote pushed); and the Windows ConPTY source is written
but unverified on real Windows.

## What's left (roughly in priority order)

1. **Publish to PyPI.** Packaging is ready and validated: `MANIFEST.in` ships the
   docs/CHANGELOG/ROADMAP/tests in the sdist, `python -m build` produces a clean sdist + wheel,
   `twine check dist/*` passes (README renders), and the wheel installs into a bare venv (no
   optional deps) with `import tappty` and the `tapterm` entry point both working. Remaining: a
   PyPI account + token, then `python -m build && twine upload dist/*` (after confirming the
   version). Optionally test-publish to TestPyPI first.
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
   - CUI on Windows: `windows-curses` is now bundled in the `win` extra (the stdlib ships no
     `curses` there), and `curses_ui` is already portable — but, like `ConPtySource`, it's
     unverified on real Windows; confirm `tapterm --cui` renders there.
3. **Possible features:** the remaining deliberate gaps in [docs/DESIGN.md](docs/DESIGN.md) §9
   if they ever bite. *Out of reach:* SGR faint/rapid-blink/conceal — pyte doesn't model them;
   and **grapheme clusters** (ZWJ emoji families, flags, skin-tone modifiers) — pyte splits or
   collapses them upstream, so faithful rendering would need a grapheme-segmenting text path that
   overrides pyte. *Done:* SGR color **and** the bold/italic/underline/strikethrough/blink/reverse
   attributes across all four renderers (`cells()` + the `style` palette); raw-mode TUI input
   (`--raw` / `send_key` + the `keys` table) so vim/htop work; the **web renderer** (`web_ui`,
   `--web`, the `web` extra — a browser over a WebSocket, built on `websockets`); **color over the
   bus** (styled `cells` in `snapshot()`/`FRAME`) so remote `BusBacking` panels render in full
   color; and **wide-glyph width** for CJK and single-code-point emoji (`style.char_width` —
   pyte's continuation cell, the CUI dropping it so ncurses' two-column advance lines up).
