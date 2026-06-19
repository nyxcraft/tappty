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
