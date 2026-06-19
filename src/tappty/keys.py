"""VT/xterm key sequences for driving full-screen TUIs (vim, htop, less) from a renderer.

In *raw* mode (`Session.raw_keys`, `tapterm --raw`) a renderer translates a special key to
its escape sequence and sends it straight to the program via `Session.send_key` -- no local
echo, no line buffer -- so an interactive TUI on a pty receives the keys it expects. The
program (or its tty) handles echo and editing, exactly as under a real terminal emulator.

`KEYS` maps a logical key name to its bytes (the common xterm/VT100 set, *normal* cursor-key
mode -- DECCKM application mode is a future refinement). `ctrl()` builds a control byte. No
dependencies; each renderer keeps its own native-keycode -> logical-name map and looks the
bytes up here.
"""

ESC = "\x1b"

KEYS = {
    # cursor + navigation
    "up": ESC + "[A",
    "down": ESC + "[B",
    "right": ESC + "[C",
    "left": ESC + "[D",
    "home": ESC + "[H",
    "end": ESC + "[F",
    "insert": ESC + "[2~",
    "delete": ESC + "[3~",
    "pageup": ESC + "[5~",
    "pagedown": ESC + "[6~",
    "backtab": ESC + "[Z",  # shift-Tab
    # function keys (F1-F4 are SS3, F5+ are CSI, per xterm)
    "f1": ESC + "OP",
    "f2": ESC + "OQ",
    "f3": ESC + "OR",
    "f4": ESC + "OS",
    "f5": ESC + "[15~",
    "f6": ESC + "[17~",
    "f7": ESC + "[18~",
    "f8": ESC + "[19~",
    "f9": ESC + "[20~",
    "f10": ESC + "[21~",
    "f11": ESC + "[23~",
    "f12": ESC + "[24~",
    # named single-byte keys (a renderer may also just forward these bytes directly)
    "enter": "\r",
    "tab": "\t",
    "escape": ESC,
    "backspace": "\x7f",
}


def ctrl(ch):
    """The control byte for a key, e.g. ctrl('c') -> '\\x03', ctrl('[') -> ESC. Returns None
    for anything outside the @ A-Z [ \\ ] ^ _ range that has a control code."""
    o = ord(ch.upper())
    if 64 <= o <= 95:  # @ A..Z [ \ ] ^ _  ->  0x00..0x1f
        return chr(o & 0x1F)
    return None
