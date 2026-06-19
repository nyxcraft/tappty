"""The sbterm terminal core (UI-agnostic): cursor/scroll behaviour and the
hardcopy-style scrollback "paper roll". No GUI dependency -- the renderer
(pygame) is tested by eye; this pins the model a renderer reads.
"""

from tappty.terminal import Terminal


def test_scrollback_captures_lines_that_scroll_off():
    t = Terminal(cols=20, rows=4, scrollback=100)
    for i in range(10):  # 10 lines into a 4-row screen
        t.write(f"line{i}\n")
    # the live screen shows the last rows; older lines went onto the paper roll
    live = t.view_rows(0)
    assert live[0].startswith("line7")  # cursor parked on the blank 4th row
    assert t.max_scroll() >= 6  # 10 newlines - (rows-1) on screen

    # scrolling back reveals earlier output that is no longer on the live screen
    back = t.view_rows(t.max_scroll())
    assert any(r.startswith("line0") for r in back)
    assert "line0" not in "".join(live)


def test_scrollback_offset_is_clamped_and_zero_is_live():
    t = Terminal(cols=10, rows=3, scrollback=100)
    for i in range(20):
        t.write(f"L{i}\n")
    assert t.view_rows(0) == t.rows_text()  # offset 0 == the live screen
    # an over-large offset clamps to the oldest available content (no crash)
    assert t.view_rows(10_000) == t.view_rows(t.max_scroll())


def test_scrollback_is_bounded():
    t = Terminal(cols=8, rows=2, scrollback=5)
    for i in range(50):
        t.write(f"{i}\n")
    assert t.max_scroll() <= 5  # the roll is trimmed to the cap


# ---- VT52 escapes (the small set the model honors) --------------------------
def test_vt52_home_and_erase_to_end_of_screen():
    t = Terminal(cols=10, rows=3)
    t.write("ABC\r\nDEF\r\nGHI")
    t.write("\x1bH")  # ESC H: cursor home
    assert (t.cx, t.cy) == (0, 0)
    t.write("\x1bJ")  # ESC J: erase to end of screen
    assert t.snapshot().strip() == ""


def test_vt52_erase_to_end_of_line():
    t = Terminal(cols=10, rows=2)
    t.write("ABCDEF\x1bHXY\x1bK")  # home, overwrite "XY", erase to end of line
    assert t.rows_text()[0].rstrip() == "XY"


def test_vt52_direct_cursor_address():
    t = Terminal(cols=20, rows=5)
    t.write("\x1bY" + chr(2 + 32) + chr(4 + 32) + "hi")  # ESC Y row col: row 2, col 4
    assert t.rows_text()[2][4:6] == "hi"
    assert (t.cx, t.cy) == (6, 2)


def test_vt52_cursor_moves_are_bounds_clamped():
    t = Terminal(cols=5, rows=3)
    t.write("\x1bH\x1bA")  # home then up at the top -> clamped to row 0
    assert (t.cx, t.cy) == (0, 0)
    t.write("\x1bB\x1bB\x1bB\x1bB")  # down 4 in a 3-row screen -> clamped to row 2
    assert t.cy == 2
    t.write("\x1bC\x1bC\x1bD")  # right 2, left 1 -> col 1
    assert t.cx == 1
