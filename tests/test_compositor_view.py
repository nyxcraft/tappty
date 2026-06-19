"""Per-tile pan/zoom view math (pure): a terminal tile shows the full 80x24 by
default (fit), zoom magnifies, pan slides the viewport (clamped). See
[[sbterm-instrumentation]]."""

from tappty.compositor import TerminalPanel, clamp_view


def test_clamp_view():
    assert clamp_view(80, 24, 100, 40, 5, 5) == (0, 0, 80, 24)  # whole model fits
    assert clamp_view(80, 24, 30, 12, 100, 100) == (50, 12, 30, 12)  # clamped to edges
    assert clamp_view(80, 24, 30, 12, -5, -5) == (0, 0, 30, 12)  # no negative pan


def test_panel_zoom_pan_reset():
    p = TerminalPanel(backing=None, rect=(0, 0, 400, 300))
    p._fit, p._cw, p._chh = 10, 8, 8  # as if last drawn at a fit size of 10
    assert p.zoom is None  # default = fit (whole 80x24 visible)
    p.zoom_by(2)
    assert p.zoom == 14  # zoomed in 2 notches (2px each)
    p.zoom_by(-10)
    assert p.zoom == 10  # can't zoom out past fit
    p.pan_px(16, -8)
    assert p.pan == [-2.0, 1.0]  # grab-drag: content moves with the mouse
    p.reset()
    assert p.zoom is None and p.pan == [0, 0]
