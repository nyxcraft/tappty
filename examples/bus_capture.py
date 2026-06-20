"""Drive a session programmatically over the bus -- send a command, capture its output.

The bus carries the same observe/control contract off-process. Its `CMD` primitive sends a line
and captures everything the program prints up to its next prompt -- the building block for
automated drivers, tests, and bots. Here the server and a client run in one process for a
self-contained demo; normally they'd be separate processes (even separate machines, over TCP).

Runnable with the core install (POSIX -- it uses a Unix-domain socket):
    python examples/bus_capture.py
"""

import os
import tempfile

from tappty import BusClient, BusServer, Session, Terminal
from tappty.source import EngineSource


def shouty_repl(emit, readline):
    """A toy hosted program: print a prompt, read a line, reply with it upper-cased, repeat.
    Blocking in readline() is what tells the session (and the bus CMD) that we're at a prompt."""
    emit("say> ")
    while True:
        emit(readline().strip().upper() + "\r\nsay> ")


def main():
    sock = os.path.join(tempfile.gettempdir(), "tappty-bus-example.sock")
    sess = Session(Terminal(80, 24), source=EngineSource(shouty_repl))
    server = BusServer(sess, sock).start()
    sess.start()  # start the hosted program (non-blocking)
    try:
        client = BusClient(sock).connect()
        client.hello(role="ai", name="driver")  # claim the talking stick so we may drive
        for word in ("hello", "tappty over the bus", "neat"):
            reply = client.cmd(word)  # send the line, capture output to the next prompt
            print(f"  sent {word!r}\n    captured {reply!r}")
        client.close()
    finally:
        server.stop()
        sess.stop()


if __name__ == "__main__":
    main()
