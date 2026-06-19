"""A web renderer for a Session -- view and drive a hosted program in a browser tab.

The fourth renderer on the same `run(session, runner, ...)` contract, and the maximal
demonstration of tappty's premise (every consumer is an equal client of the observe/control
contract): a browser is just another client. The screen is tappty's own grid -- the browser
is a *thin painter* (a canvas drawing the `cells()` rows in phosphor + SGR color), not a
terminal emulator, exactly as `pygame_ui`/`arcade_ui` are. The hard, standard parts are
libraries: a stdlib `http.server` serves the one page, and `websockets` (the `web` extra, its
synchronous server -- no asyncio) carries the live connection.

Per connection a single handler thread runs a poll loop: it `recv`s keystrokes (with a short
timeout) and pushes the latest frame when the grid is dirty -- so only that thread ever sends,
and the source thread merely flips a flag. Keystrokes arrive as *logical* keys (a char, or a
name like "up"/"enter"/"f1"/"ctrl-c"); the server translates them via `tappty.keys` and routes
to `send_key` (raw mode) or `feed_key` (line mode), keeping byte-mapping in one place.

Security mirrors the bus: it binds loopback by default and takes an optional `token` (a query
param, constant-time compared). It is a terminal control plane, not a public service -- no TLS.
`websockets` is imported lazily, so `import tappty` / `import tappty.web_ui` work without it.
"""

import html
import json
import logging
import sys

log = logging.getLogger(__name__)

_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>__TITLE__</title>
<style>html,body{margin:0;background:#__BG__;height:100%}
#c{display:block;margin:0 auto}
#s{color:#__FG__;font:12px monospace;text-align:center;padding:4px}</style>
</head><body>
<canvas id="c"></canvas><div id="s">connecting…</div>
<script>
const COLS=__COLS__, ROWS=__ROWS__, WS_PORT=__WS_PORT__, TOKEN=__TOKEN__;
const FG="__FG__", BG="__BG__", FONT="16px monospace";
const cv=document.getElementById("c"), ctx=cv.getContext("2d"), st=document.getElementById("s");
ctx.font=FONT;
const CW=Math.max(1,Math.ceil(ctx.measureText("M").width)), CH=19;
cv.width=COLS*CW; cv.height=ROWS*CH;
let rows=null, cx=0, cy=0, blink=true;
function draw(){
  ctx.fillStyle="#"+BG; ctx.fillRect(0,0,cv.width,cv.height);
  ctx.font=FONT; ctx.textBaseline="top";
  if(rows){ for(let r=0;r<rows.length;r++){ for(const run of rows[r]){
    const x=run[0], text=run[1], fg=run[2], bg=run[3];
    if(bg!==BG){ ctx.fillStyle="#"+bg; ctx.fillRect(x*CW, r*CH, text.length*CW, CH); }
    ctx.fillStyle="#"+fg;
    for(let i=0;i<text.length;i++){ ctx.fillText(text[i], (x+i)*CW, r*CH+2); }
  }}}
  if(blink){ ctx.strokeStyle="#"+FG; ctx.strokeRect(cx*CW+0.5, cy*CH+0.5, CW-1, CH-1); }
}
setInterval(()=>{blink=!blink; draw();}, 500);
const proto = location.protocol==="https:"?"wss":"ws";
const url = proto+"://"+location.hostname+":"+WS_PORT+"/"+(TOKEN?("?token="+encodeURIComponent(TOKEN)):"");
const ws = new WebSocket(url);
ws.onopen = ()=>{ st.textContent=""; };
ws.onclose = ()=>{ st.textContent="— disconnected —"; };
ws.onmessage = ev=>{ const m=JSON.parse(ev.data);
  if(m.t==="frame"){ rows=m.rows; cx=m.cx; cy=m.cy; draw(); } };
const NAMED={ArrowUp:"up",ArrowDown:"down",ArrowLeft:"left",ArrowRight:"right",Home:"home",
  End:"end",PageUp:"pageup",PageDown:"pagedown",Insert:"insert",Delete:"delete",
  Enter:"enter",Tab:"tab",Escape:"escape",Backspace:"backspace"};
function classify(e){
  const k=e.key;
  if(k in NAMED) return NAMED[k];
  if(/^F([1-9]|1[0-2])$/.test(k)) return k.toLowerCase();
  if(e.ctrlKey && k.length===1 && /[a-zA-Z]/.test(k)) return "ctrl-"+k.toLowerCase();
  if(k.length===1) return k;
  return null;
}
document.addEventListener("keydown", e=>{
  if(ws.readyState!==1) return;
  const k=classify(e);
  if(k===null) return;
  e.preventDefault();
  ws.send(JSON.stringify({t:"key", k:k}));
});
</script></body></html>
"""


def _hex(rgb):
    """An (r, g, b) tuple as a 6-digit hex string (no leading '#')."""
    return f"{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


def _render_page(title, ws_port, cols, rows, token):
    from tappty import style

    repl = {
        "__TITLE__": html.escape(title),
        "__WS_PORT__": str(ws_port),
        "__COLS__": str(cols),
        "__ROWS__": str(rows),
        "__TOKEN__": json.dumps(token or ""),  # a JS string literal (safely encoded)
        "__FG__": _hex(style.FG),
        "__BG__": _hex(style.BG),
    }
    page = _PAGE
    for k, v in repl.items():
        page = page.replace(k, v)
    return page


def _frame_json(session):
    """The current grid as a compact run-length-encoded frame: each row is a list of
    [col, text, fg_hex, bg_hex] runs (sharing one resolved color), with the cursor."""
    from tappty import style

    rows = []
    for row in session.term.cells():
        rows.append(
            [
                [x, text, _hex(fg), _hex(bg)]
                for x, text, fg, bg in style.runs(row, style.FG, style.BG)
            ]
        )
    return json.dumps({"t": "frame", "rows": rows, "cx": session.term.cx, "cy": session.term.cy})


def _handle_key(session, by, msg):
    """Apply one logical key from the browser: a printable char, a named key
    (`tappty.keys.KEYS`), or `ctrl-<letter>`. Raw mode sends bytes straight through; line
    mode keeps only printable + Enter/Backspace (specials are ignored, as the other UIs do)."""
    from tappty import keys

    try:
        m = json.loads(msg)
    except (ValueError, TypeError):
        return
    if not isinstance(m, dict) or m.get("t") != "key":
        return
    k = m.get("k")
    if not isinstance(k, str) or not k:
        return
    if session.raw_keys:
        if len(k) == 1 and k.isprintable():
            data = k
        elif k.startswith("ctrl-") and len(k) == 6:
            data = keys.ctrl(k[5])
        else:
            data = keys.KEYS.get(k)
        if data:
            session.send_key(data, by=by)
    elif len(k) == 1 and k.isprintable():
        session.feed_key(k, by=by)
    elif k == "enter":
        session.feed_key("\r", by=by)
    elif k == "backspace":
        session.feed_key("\b", by=by)


def run(
    session,
    runner,
    title="tapterm",
    host="127.0.0.1",
    port=8023,
    token=None,
    exit_when_done=False,
    max_seconds=None,
    fps=30,
):
    if fps < 1:
        raise ValueError("fps must be >= 1")
    if token is not None and not (isinstance(token, str) and token):
        raise ValueError("token must be a non-empty string or None")
    import hmac
    import http.server
    import threading
    import time
    from urllib.parse import parse_qs, urlsplit

    from websockets.exceptions import ConnectionClosed
    from websockets.sync.server import serve as ws_serve

    cols, rows = session.term.cols, session.term.rows
    ws_port = port + 1
    page = _render_page(title, ws_port, cols, rows, token).encode("utf-8")

    class _Page(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)

        def log_message(self, *a):  # quiet -- no request logging to stderr
            pass

    httpd = http.server.ThreadingHTTPServer((host, port), _Page)
    counter = {"n": 0}
    clock = threading.Lock()

    def ws_handler(conn):
        if token is not None:  # optional shared-secret gate (query param)
            got = (parse_qs(urlsplit(conn.request.path).query).get("token") or [""])[0]
            if not hmac.compare_digest(got, token):
                conn.close()
                return
        with clock:
            counter["n"] += 1
            name = f"web-{counter['n']}"
        session.claim_control(name, "human")
        dirty = threading.Event()
        dirty.set()  # send an initial frame on connect
        session.on_frame(dirty.set)
        try:
            while True:
                try:
                    msg = conn.recv(timeout=1.0 / fps)
                except TimeoutError:
                    msg = None
                if msg:
                    _handle_key(session, name, msg)
                if dirty.is_set():
                    dirty.clear()
                    conn.send(_frame_json(session))  # only this thread ever sends
        except ConnectionClosed:
            pass
        finally:
            session.off_frame(dirty.set)
            session.drop_controller(name)

    wsd = ws_serve(ws_handler, host, ws_port)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    threading.Thread(target=wsd.serve_forever, daemon=True).start()
    sys.stderr.write(f"tapterm web UI on http://{host}:{port}/  (websocket :{ws_port})\n")

    session.run_in_thread(runner)  # start the hosted program
    elapsed = 0.0
    try:
        while True:
            time.sleep(0.1)
            elapsed += 0.1
            if max_seconds is not None and elapsed >= max_seconds:
                break
            if session.done and exit_when_done:
                break
    except KeyboardInterrupt:
        pass
    finally:
        try:
            wsd.shutdown()
        except Exception as e:
            log.debug("ws shutdown: %s", e)
        try:
            httpd.shutdown()
        except Exception as e:
            log.debug("http shutdown: %s", e)
        session.stop()  # owning renderer
