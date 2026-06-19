# Terminal fidelity review

## Scope

Reviewed VT52 model behavior, pyte backend parity, encoding split, Unicode handling,
scrollback, and renderer treatment of terminal attributes.

No high-severity findings. The project is honest about the built-in `Terminal` being a
VT52-spirit model and about `PyteTerminal` being the modern ANSI path.

## Findings

### Medium: ANSI attributes are parsed but not rendered

Evidence:

- `PyteTerminal.rows_text()` returns only `pyte` display strings, not character attributes
  (`src/tappty/pyte_terminal.py:70`).
- `pygame_ui` renders every glyph in one fixed foreground color (`src/tappty/pygame_ui.py:82`).
- The compositor renderer also draws text with one fixed foreground color
  (`src/tappty/compositor.py:70`).

Impact:

`--ansi` gives text/cursor/erase fidelity, but SGR color, bold, inverse, and other visual
attributes are discarded. That is fine for a monochrome terminal aesthetic, but it is less
than full visual terminal fidelity for modern TUIs.

Recommendation:

Either document `PyteTerminal` as text-position fidelity only, or extend the terminal read
interface to expose attributes. A lightweight next step is a separate `cells()` or
`styled_rows()` API while preserving `rows_text()` for existing renderers.

### Medium: wide-character cell widths are not modeled

Evidence:

- `Terminal.write()` treats every printable Python character as one cell
  (`src/tappty/terminal.py:70`).
- `pygame_ui` and compositor draw by enumerating Python string code points into fixed cells
  (`src/tappty/pygame_ui.py:82`, `src/tappty/compositor.py:65`).

Impact:

CJK full-width characters, emoji, combining marks, and some symbols can drift visually or
overwrite neighboring cells. Existing tests cover accents and a checkmark, but not width
semantics.

Recommendation:

Add tests with wide and combining characters. If those are supported, use a width helper
such as `wcwidth` in the model/renderers. If not supported, document the terminal as
single-cell Unicode text.

### Low: incremental decoders are not flushed on exit

Evidence:

`Session._output()` uses an incremental decoder for byte sources (`src/tappty/session.py:89`),
but `_exit()` emits `CLOSED` without flushing the decoder (`src/tappty/session.py:111`).

Impact:

If a byte source ends with an incomplete multibyte sequence, the terminal may silently drop
or defer the replacement character instead of rendering the decoder's final state.

Recommendation:

On `_exit()`, if `_decoder` exists, call `decode(b"", final=True)`, write any returned text,
and fan out a final frame before `CLOSED`.

### Low: VT52 escape coverage is under-tested

Evidence:

`Terminal._handle_esc()` implements home, erase, direct address, and cursor motion
(`src/tappty/terminal.py:77`), but `tests/test_term.py` currently focuses on scrollback.

Impact:

The VT52 behavior is small and valuable to this project, so regressions could slip through
without a test failing.

Recommendation:

Add tests for `ESC H`, `ESC J`, `ESC K`, `ESC Yrc`, and `ESC A/B/C/D` bounds.

## Positive notes

- The byte-stream split is clear: raw bytes remain lossless on `on_stream`, while screens
  get decoded text (`src/tappty/session.py:82`).
- `PyteTerminal` presents the same read interface as `Terminal`, which keeps renderers
  backend-agnostic (`src/tappty/pyte_terminal.py:65`).
