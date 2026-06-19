"""The curses renderer's viewport math (pure -- no tty needed): a fixed 80x24 model
shown whole when the terminal is big enough, or a cursor-following sub-rectangle
when it's smaller, never resizing the model. See docs/DESIGN.md."""

from tappty.curses_ui import viewport


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
