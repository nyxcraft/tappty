"""The curses renderer's pure logic (no tty needed): the viewport math (a fixed 80x24 model
shown whole, or a cursor-following sub-rectangle when the terminal is smaller) and the SGR
color mapping (pyte color -> curses color index / attributes). See docs/DESIGN.md."""

from tappty import style
from tappty.curses_ui import _cell_style, _curses_color, viewport


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
    red_bold = style.Cell("x", "red", "default", True, False)
    assert _cell_style(red_bold, colors=256) == (9, None, False, False)  # red+8 = bright red
    assert _cell_style(red_bold, colors=8) == (1, None, True, False)  # 8-color -> A_BOLD instead


def test_cell_style_background_and_reverse():
    c = style.Cell("x", "default", "blue", False, True)
    assert _cell_style(c, colors=256) == (2, 4, False, True)  # green on blue, reverse flagged


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
