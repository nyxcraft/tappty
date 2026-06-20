"""The curses renderer's pure logic (no tty needed): the viewport math (a fixed 80x24 model
shown whole, or a cursor-following sub-rectangle when the terminal is smaller) and the SGR
color mapping (pyte color -> curses color index / attributes). See docs/DESIGN.md."""

import pytest

from tappty import style
from tappty.curses_ui import _cell_style, _continuations, _curses_color, _raw_bytes, viewport


def test_raw_bytes_translates_special_keys_to_vt_sequences():
    curses = pytest.importorskip("curses")  # stdlib, but absent on stock Windows
    from tappty import keys

    assert _raw_bytes(curses, curses.KEY_UP) == keys.KEYS["up"]
    assert _raw_bytes(curses, curses.KEY_F0 + 1) == keys.KEYS["f1"]  # KEY_F(1), pre-initscr-safe
    assert _raw_bytes(curses, curses.KEY_PPAGE) == keys.KEYS["pageup"]
    assert _raw_bytes(curses, 10) == "\r"  # Enter
    assert _raw_bytes(curses, curses.KEY_BACKSPACE) == "\x7f"
    assert _raw_bytes(curses, ord("a")) == "a"  # printable passes through
    assert _raw_bytes(curses, 3) == "\x03"  # a Ctrl-C byte passes through
    assert _raw_bytes(curses, 999999) is None  # unknown high keycode -> dropped


def test_curses_color_maps_names_bright_and_hex():
    assert _curses_color("default") is None
    assert _curses_color("red") == (1, False)  # COLOR_RED
    assert _curses_color("brown") == (3, False)  # pyte's yellow -> COLOR_YELLOW
    assert _curses_color("brightblue") == (4, True)
    assert _curses_color("fe0000") == (1, True)  # truecolor hex -> nearest ANSI-16 (bright red)


def test_cell_style_default_is_phosphor_green():
    fi, bi, bold, rev = _cell_style(style.default_cell("x"), colors=256)
    assert fi == 2 and bi is None and not bold and not rev  # green fg, terminal-default bg


def test_cell_style_bright_uses_high_index_on_16_color_else_bold():
    red_bold = style.default_cell("x")._replace(fg="red", bold=True)  # bold red
    assert _cell_style(red_bold, colors=256) == (9, None, False, False)  # red+8 = bright red
    assert _cell_style(red_bold, colors=8) == (1, None, True, False)  # 8-color -> A_BOLD instead


def test_cell_style_background_and_reverse():
    c = style.default_cell("x")._replace(bg="blue", reverse=True)  # reverse on blue bg
    assert _cell_style(c, colors=256) == (2, 4, False, True)  # green on blue, reverse flagged


def test_continuations_flag_the_cell_after_a_wide_glyph():
    # pyte lays a wide glyph as the char plus an empty continuation cell: "日" -> 日, ''
    row = [style.default_cell(c) for c in ("A", "日", "", "B", "👍", "", "C")]
    assert _continuations(row) == [False, False, True, False, False, True, False]
    # the cells flagged True are exactly the ones the CUI must not redraw
    assert all(row[i].char in ("", " ") for i, flag in enumerate(_continuations(row)) if flag)


def test_continuations_all_false_for_plain_ascii():
    row = [style.default_cell(c) for c in "hello"]
    assert _continuations(row) == [False] * 5


def test_continuations_dont_drop_a_real_char_after_a_wide_glyph():
    # The VT52 Terminal does NOT reserve a continuation cell, so a wide glyph can be followed
    # by a real character ("日本", "日X"). That character is content, not a continuation, and
    # must be drawn -- only a *blank* cell after a wide glyph is the continuation to skip.
    assert _continuations([style.default_cell(c) for c in ("日", "本")]) == [False, False]
    assert _continuations([style.default_cell(c) for c in ("日", "X")]) == [False, False]


def test_full_fit_shows_whole_model():
    # terminal comfortably >= 80x24 (status row reserved) -> show all from 0,0
    assert viewport(80, 24, 100, 30, 5, 5) == (0, 0, 80, 24)


def test_narrow_terminal_follows_cursor_horizontally():
    ox, oy, vw, vh = viewport(80, 24, 40, 30, 70, 5)
    assert vw == 40 and vh == 24
    assert ox <= 70 < ox + vw  # cursor stays visible
    assert ox == 40  # clamped to the right edge (80-40)


def test_short_terminal_follows_cursor_vertically():
    ox, oy, vw, vh = viewport(80, 24, 100, 10, 5, 20)
    assert vw == 80 and vh == 9  # 10 rows - 1 status row
    assert oy <= 20 < oy + vh
    assert oy == 15  # clamped to the bottom (24-9)


def test_tiny_terminal_clamps_but_stays_valid():
    ox, oy, vw, vh = viewport(80, 24, 10, 4, 0, 0)
    assert vw == 10 and vh == 3 and ox == 0 and oy == 0
