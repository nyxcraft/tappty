# Cross-platform review

## Scope

Reviewed POSIX pty paths, TCP/AF_UNIX bus selection, Windows ConPTY scaffolding, optional
dependencies, renderer assumptions, and CI/platform coverage.

No high-severity findings. The design is cleanly split by `Source`, and the TCP bus gives
Windows a transport that does not depend on `AF_UNIX`.

## Findings

### Medium: Windows behavior is documented but not verified

Evidence:

- CI currently runs only on Ubuntu (`.github/workflows/ci.yml:19`).
- The workflow explicitly notes no Windows job yet and says POSIX pty tests would error on
  Windows (`.github/workflows/ci.yml:39`).
- `PtySource` tests import/use the POSIX source directly (`tests/test_pty_source.py:8`,
  `tests/test_source_encoding.py:12`).
- `ConPtySource` is only tested for import guarding off-Windows, not for real operation
  (`tests/test_pipe_source.py:41`).

Impact:

The code is structured for Windows, but release claims should stay provisional until
`ConPtySource`, CLI source selection, TCP bus, and at least one renderer are exercised on
`windows-latest` or a real Windows box.

Recommendation:

Before widening release claims, add platform skips for POSIX-only tests, validate
`ConPtySource` manually on Windows, then add a Windows CI lane for `EngineSource`,
`PipeSource`, TCP bus, `PyteTerminal`, and `ConPtySource` smoke coverage.

### Medium: default mode can choose GUI in headless environments

Evidence:

`_default_mode()` picks GUI whenever `pygame` is importable (`src/tappty/cli.py:39`), while
`pygame_ui.run()` calls `pygame.display.set_mode()` unconditionally
(`src/tappty/pygame_ui.py:50`).

Impact:

On a server, SSH session, cron job, or CI image where pygame is installed but no display is
available, plain `tapterm` can choose GUI and fail instead of falling back to CUI.

Recommendation:

Make default mode consider display availability. On POSIX, treat missing `DISPLAY` and
`WAYLAND_DISPLAY` as CUI unless `SDL_VIDEODRIVER=dummy` or `--gui` is explicit. If `--gui`
is explicit, fail clearly.

### Low: Windows CUI support is documented but not packaged

Evidence:

`docs/WINDOWS.md` mentions `windows-curses` as the CUI path (`docs/WINDOWS.md:100`), but
`pyproject.toml` has no Windows curses extra (`pyproject.toml:24`).

Impact:

This is mostly documentation friction. Users on Windows may install `tappty[win]` and still
not have the CUI dependency if they want curses.

Recommendation:

Either add a `cui-win = ["windows-curses; platform_system == 'Windows'"]` extra or keep the
manual install guidance but repeat it in README install examples.

## Positive notes

- `bus.py` imports cleanly when `AF_UNIX` is absent and gives a clear error for Unix socket
  paths on such platforms (`src/tappty/bus.py:40`, `src/tappty/bus.py:49`).
- TCP bus binding is loopback-only by default (`src/tappty/bus.py:135`).
- `_make_source()` selects `PipeSource`, `ConPtySource`, or `PtySource` at the CLI boundary
  (`src/tappty/cli.py:58`).
