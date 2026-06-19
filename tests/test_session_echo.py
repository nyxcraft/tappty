"""Local echo (feed_key) must fan out a FRAME so remote renderers/loggers see typed
characters immediately, not only when later program output happens to fire a frame."""

from tappty.session import Session
from tappty.terminal import Terminal


def test_feed_key_local_echo_notifies_frame_observers():
    s = Session(Terminal(80, 24))
    s.claim_control("local", "human")
    frames = []
    s.on_frame(lambda: frames.append(1))

    s.feed_key("x")
    assert "x" in s.term.rows_text()[0]  # echoed to the grid
    assert len(frames) >= 1  # and a frame fired (was 0 before the fix)

    before = len(frames)
    s.feed_key("\r")  # newline echo also fans out a frame
    assert len(frames) > before
