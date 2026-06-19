# UX and input review

## Scope

Reviewed CLI defaults, renderer input handling, control flow when windows close, scrollback
behavior, snapshots, and interactive terminal affordances.

No high-severity findings. The current UI is coherent for line-oriented programs and the
explicit talking-stick model is easy to reason about.

## Findings

### Medium: renderers do not forward most terminal control keys

Evidence:

- `curses_ui._feed()` handles Enter, Backspace, and printable ASCII only; arrows and
  function keys are ignored (`src/tappty/curses_ui.py:25`).
- `pygame_ui.run()` handles Return, Backspace, PageUp/PageDown, F12, and printable Unicode;
  other keys are ignored (`src/tappty/pygame_ui.py:65`).
- The compositor sends Return, Backspace, or `e.unicode`; Escape closes the dashboard
  instead of being available to the child program (`src/tappty/compositor.py:322`).

Impact:

This works for the line-oriented heritage use case. It limits real shells and TUIs that need
arrow keys, Escape, Ctrl-C, Ctrl-D, Tab, function keys, or bracketed escape sequences.

Recommendation:

Define a renderer-to-session key mapping. For `--ansi`/modern programs, send common VT
sequences for arrows/navigation/function keys. Reserve UI shortcuts behind modifiers or a
mode so Escape/Ctrl-C can reach the hosted program when desired.

### Medium: closing a renderer does not clearly terminate the hosted program

Evidence:

`pygame_ui.run()` exits without stopping the source (`src/tappty/pygame_ui.py:121`),
`curses_ui.run()` returns on Ctrl-] (`src/tappty/curses_ui.py:95`), and
`SessionBacking.close()` is a no-op (`src/tappty/compositor.py:108`).

Impact:

From a user's perspective, closing the terminal window usually means "stop the program" or
at least "detach explicitly." The current behavior is ambiguous, especially for embedded
compositor use.

Recommendation:

Pick and document one behavior per renderer: owning renderers stop the source on close;
non-owning panels detach only. The CLI renderers should probably stop the hosted source on
quit.

### Medium: automatic GUI default can surprise headless users

Evidence:

The CLI chooses GUI whenever pygame is importable (`src/tappty/cli.py:39`), not when a
display is available.

Impact:

Users on an SSH session or headless workstation may get a pygame display failure from
plain `tapterm` even though CUI would work.

Recommendation:

Default to CUI when no display environment is detected. Keep `--gui` as an explicit request
that can fail with a clear install/display message.

### Low: public renderer APIs do not validate `fps`

Evidence:

`pygame_ui.run()` uses `frame % fps` when snapshots are enabled (`src/tappty/pygame_ui.py:106`)
and `frame >= max_seconds * fps` for its hard cap (`src/tappty/pygame_ui.py:119`).
The compositor guards snapshot modulo with `max(1, fps)` but still uses `max_seconds * fps`
for exit (`src/tappty/compositor.py:357`, `src/tappty/compositor.py:364`).

Impact:

CLI callers use defaults, but library callers can pass `fps=0` or negative values and get a
crash or immediate/strange loop behavior.

Recommendation:

Validate `fps >= 1` at the start of both renderer entry points.

## Positive notes

- Scrollback UX is simple and discoverable in pygame: PageUp/PageDown or mouse wheel scroll,
  typing snaps back to live (`src/tappty/pygame_ui.py:63`).
- The compositor's F2 explicit take/release control model is visible in the panel label
  (`src/tappty/compositor.py:332`, `src/tappty/compositor.py:347`).
