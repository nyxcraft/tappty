"""Write your own Source: anything that produces output (and consumes input) can drive a Session.

A Source implements three things:

    start(on_output, on_wait, on_exit)   begin producing; call the callbacks as things happen
    send_input(text)                     input arrived (from a renderer / the bus)
    stop()                               shut down

Set the class attribute `encoding` if you emit raw bytes (a "byte source" -- the Session decodes
them for the screen); leave it None to emit characters directly (a "text source"), like this one.
The pty, pipe, cast, and engine sources are all just implementations of this contract.

Runnable with the core install:  python examples/custom_source.py
"""
import threading

from tappty import Session, Terminal
from tappty.source import Source


class LinesSource(Source):
    """A text source that emits each of `lines` after `delay` seconds, then ends."""

    def __init__(self, lines, delay=0.1):
        self.lines = lines
        self.delay = delay
        self.thread = None  # run_blocking() joins self.thread, so expose it
        self._stop = threading.Event()

    def start(self, on_output, on_wait, on_exit):
        def run():
            for line in self.lines:
                if self._stop.wait(self.delay):
                    break  # stop() was called
                on_output(line + "\r\n")
            on_exit()

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()

    def send_input(self, text):
        pass  # this source ignores input

    def stop(self):
        self._stop.set()


def main():
    sess = Session(Terminal(80, 24), source=LinesSource(["one", "two", "three"]))
    sess.run_blocking()
    print("final screen:")
    for row in sess.term.rows_text()[:4]:
        print("  " + row.rstrip())


if __name__ == "__main__":
    main()
