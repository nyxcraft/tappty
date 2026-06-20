"""Watch the output and decide what to type -- a closed observe -> decide -> control loop.

The open-loop `demos/drive_vim.py` types a fixed script. This is the interesting case: the driver
*reacts* to what the program shows. We host a tiny "guess my number" game and attach a bot that

  1. watches the output **stream** (observe tap `on_stream`),
  2. waits for the program to ask for input (event tap `on_event` -> "WAIT"),
  3. reads the latest "higher" / "lower" hint, binary-searches, and sends its next guess over the
     **control** tap (`send_input`).

It wins in ~log2(range) moves, having typed nothing it didn't reason out. The game is an
in-process `EngineSource` so the example is self-contained, but the bot uses only the observe and
control taps -- the same contract that works over a real pty or the bus, so the identical bot
could drive an external program. (For a full-screen TUI you'd read the *screen* instead: tap
`on_frame` and inspect `session.term.snapshot()` / `rows_text()` -- noted below.)

Runnable with the core install:  python examples/watch_and_drive.py
"""

import random

from tappty import Session, Terminal
from tappty.source import EngineSource

LO, HI = 1, 100


def guessing_game(emit, readline):
    """A line-oriented program: pick a secret, then prompt and judge until the guess is right."""
    secret = random.randint(LO, HI)
    emit(f"I'm thinking of a number between {LO} and {HI}.\r\n")
    tries = 0
    while True:
        emit("Your guess? ")
        guess = int(readline().strip())
        tries += 1
        if guess == secret:
            emit(f"Correct! It was {secret}, found in {tries} guesses.\r\n")
            return
        emit("Too low -- higher.\r\n" if guess < secret else "Too high -- lower.\r\n")


class Bot:
    """Observes the game's output and drives its input by pure binary search."""

    def __init__(self, session):
        self.session = session
        self.lo, self.hi = LO, HI
        self.guess = (LO + HI) // 2
        self.seen = ""  # accumulates streamed output; we peek at the latest hint
        session.on_stream(self._on_stream)  # tap 1: raw output as the program emits it
        session.on_event(self._on_event)  # tap 3: events -- "WAIT" = it's blocked for input

    def _on_stream(self, chunk):
        self.seen += chunk

    def _on_event(self, name, info):
        if name != "WAIT":  # only act when the program is actually waiting for a line
            return
        # Decide from what we've observed: narrow the range by the last hint, then halve it.
        # (A full-screen program would have no "hint line" in the stream -- you'd read the grid:
        #  `last = self.session.term.rows_text()`; the decision logic is the same.)
        if "higher" in self.seen:
            self.lo = self.guess + 1
        elif "lower" in self.seen:
            self.hi = self.guess - 1
        self.seen = ""
        self.guess = (self.lo + self.hi) // 2
        print(f"  bot: range [{self.lo}, {self.hi}] -> guess {self.guess}")
        self.session.send_input(f"{self.guess}\n")  # control tap: type the next guess


def main():
    random.seed(7)  # deterministic for the example/test; remove for a fresh game each run
    session = Session(Terminal(80, 24), source=EngineSource(guessing_game))
    Bot(session)
    print("hosting a guess-my-number game; the bot watches the stream and binary-searches:\n")
    session.run_blocking()  # runs until the game returns (the bot guessed right)
    print("\nfinal screen:")
    for row in session.term.rows_text():
        if row.strip():
            print("  " + row.rstrip())


if __name__ == "__main__":
    main()
