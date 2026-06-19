"""The VT/xterm key sequences used for raw-mode TUI input (pure, no deps)."""

from tappty import keys


def test_key_sequences_are_the_xterm_set():
    assert keys.KEYS["up"] == "\x1b[A"
    assert keys.KEYS["left"] == "\x1b[D"
    assert keys.KEYS["home"] == "\x1b[H"
    assert keys.KEYS["pageup"] == "\x1b[5~"
    assert keys.KEYS["delete"] == "\x1b[3~"
    assert keys.KEYS["f1"] == "\x1bOP"  # F1-F4 are SS3
    assert keys.KEYS["f5"] == "\x1b[15~"  # F5+ are CSI
    assert keys.KEYS["enter"] == "\r" and keys.KEYS["backspace"] == "\x7f"
    assert all(f"f{i}" in keys.KEYS for i in range(1, 13))  # all twelve function keys


def test_ctrl_builds_control_bytes():
    assert keys.ctrl("c") == "\x03"
    assert keys.ctrl("C") == "\x03"  # case-insensitive
    assert keys.ctrl("[") == "\x1b"  # Ctrl-[ == Esc
    assert keys.ctrl("@") == "\x00"
    assert keys.ctrl("1") is None  # no control code for a digit
