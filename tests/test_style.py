"""SGR styling: the color palette, default->phosphor, reverse, and run-length grouping.

Pure logic shared by the terminal backends and the GUI renderers -- no deps, no display.
"""

from tappty import style


def test_default_color_is_none_so_renderer_uses_phosphor():
    assert style.rgb("default") is None
    assert style.rgb("") is None


def test_named_bright_and_bold_colors():
    assert style.rgb("red") == (205, 0, 0)
    assert style.rgb("brightred") == (255, 0, 0)
    assert style.rgb("red", bold=True) == (255, 0, 0)  # bold brightens a base color
    assert style.rgb("brown") == (205, 205, 0)  # pyte names yellow "brown"
    assert style.rgb("brightblack") == (127, 127, 127)


def test_hex_colors_from_256_and_truecolor():
    assert style.rgb("ff8700") == (255, 135, 0)
    assert style.rgb("000000") == (0, 0, 0)
    assert style.rgb("zzzzzz") is None  # not valid hex -> None (renderer uses phosphor)


def test_resolve_default_to_phosphor_then_reverse_swaps():
    plain = style.default_cell("x")
    assert style.resolve(plain) == (style.FG, style.BG)
    rev = style.Cell("x", "default", "default", False, True)
    assert style.resolve(rev) == (style.BG, style.FG)  # inverse video
    assert style.resolve(plain, (1, 2, 3), (4, 5, 6)) == ((1, 2, 3), (4, 5, 6))  # custom defaults


def test_runs_group_consecutive_same_style():
    row = [
        style.Cell("R", "red", "default", False, False),
        style.Cell("E", "red", "default", False, False),
        style.Cell("D", "red", "default", False, False),
        style.default_cell(" "),
        style.Cell("G", "green", "default", False, False),
    ]
    runs = style.runs(row)
    assert runs[0] == (0, "RED", (205, 0, 0), style.BG)
    assert runs[1] == (3, " ", style.FG, style.BG)
    assert runs[2] == (4, "G", (0, 205, 0), style.BG)
