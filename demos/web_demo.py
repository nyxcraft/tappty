#!/usr/bin/env python3
"""tappty demo -- the web-browser renderer.

`web_ui` serves the live terminal as a single HTML page: a stdlib `http.server` hands out one
canvas, the browser paints the styled cells (color, bold/italic/underline/strike) it receives over
a websocket, and sends your keystrokes back. Several browsers can watch at once; it binds loopback.

This demo hosts the SGR color chart so you can watch the renderer paint real color in a real
browser tab:

    pip install 'tappty[web,ansi]'
    python demos/web_demo.py                 # serve at http://127.0.0.1:8023/ -- open it
    python demos/web_demo.py --shot out.png  # headless: drive a real browser to the page and
                                             # screenshot the whole window, then exit. Needs
                                             # Playwright + Chromium (pip install playwright &&
                                             # playwright install chromium)
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import time

COLS, ROWS = 80, 24


def build_session():
    """A Session hosting the SGR color chart (an EngineSource) on the full-ANSI backend."""
    from tappty import Session
    from tappty.pyte_terminal import PyteTerminal
    from tappty.source import EngineSource

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from color_chart import runner  # reuse the color-chart demo as colorful content

    return Session(PyteTerminal(COLS, ROWS), source=EngineSource(runner))


def shoot(url, out, settle=2.0):
    """Drive a real (headless) browser to the page and screenshot the whole browser window.

    A headless browser can't show the OS window chrome, so we load the live page inside a small
    window frame (traffic-lights + an address bar showing the URL) and screenshot that -- the
    terminal inside is the *real* web renderer painting over the websocket, not a mock."""
    from playwright.sync_api import sync_playwright

    dot = "width:12px;height:12px;border-radius:50%;background:#{};"
    frame = (
        '<!doctype html><html><body style="margin:0;background:#d7dae0;'
        'font-family:system-ui,Arial,sans-serif">'
        '<div style="background:#e6e8ec;padding:9px 13px;display:flex;align-items:center;gap:8px;'
        'border-bottom:1px solid #c3c7cd">'
        f'<span style="{dot.format("ff5f56")}"></span>'
        f'<span style="{dot.format("ffbd2e")}"></span>'
        f'<span style="{dot.format("27c93f")}"></span>'
        '<span style="flex:1;background:#fff;border-radius:13px;padding:6px 15px;margin-left:8px;'
        f'color:#5f6368;font-size:13px">{url}</span></div>'
        f'<iframe src="{url}" style="display:block;border:0;width:100%;height:500px"></iframe>'
        '</body></html>'
    )
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])  # --no-sandbox: headless in a container
        page = browser.new_page(viewport={"width": 900, "height": 545}, device_scale_factor=2)
        page.set_content(frame)
        time.sleep(settle)  # let the iframe load, open its websocket, and paint a frame
        page.screenshot(path=out)
        browser.close()


def main():
    ap = argparse.ArgumentParser(description="tappty demo: the web-browser renderer")
    ap.add_argument("--shot", metavar="PNG", help="screenshot the browser headless (Playwright)")
    ap.add_argument("--port", type=int, default=8023, help="HTTP port (websocket = port+1)")
    args = ap.parse_args()

    from tappty import web_ui

    sess = build_session()
    url = f"http://127.0.0.1:{args.port}/"
    # web_ui.run serves (and starts the session) but blocks; run it in a daemon thread so we can
    # drive a browser against it / sit and serve, and it dies cleanly when this process exits.
    threading.Thread(
        target=web_ui.run, args=(sess, None),
        kwargs={"title": "tappty :: web renderer", "port": args.port}, daemon=True,
    ).start()
    time.sleep(0.8)  # let the http + ws servers bind and the chart paint

    if args.shot:
        shoot(url, args.shot)
        print(f"wrote {args.shot}")
    else:
        print(f"serving the web renderer at {url}  (Ctrl-C to stop)")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
