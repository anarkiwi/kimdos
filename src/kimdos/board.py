"""Drive the KIMDOS shell on a real board over its TTY line."""

import re
import sys
import time

from kimtape import Monitor, Port, Tape

PROMPT = b"\r\n>"


class Board:
    """A KIM-1 running the KIMDOS shell, reached through the monitor."""

    def __init__(self, dev, baud=1200, trace=False):
        self.port = Port(dev, baud, trace=trace)
        self.mon = Monitor(self.port, log=sys.stderr)

    def install(self, ptp, org):
        """Load a tape image with the monitor, verify it and start the shell."""
        self.mon.sync()
        tape = Tape("kimdos", ptp)
        for _ in range(3):
            self.mon.load(tape)
            if self.mon.verify(tape):
                break
        else:
            raise RuntimeError("image did not verify")
        self.start(org)

    def start(self, org):
        """Run the shell at org and wait for its prompt."""
        self.mon.sync()
        self.port.take()
        self.mon.go(org)
        self.wait_prompt(10)

    def wait_prompt(self, timeout):
        """Collect output up to the next shell prompt."""
        deadline = time.time() + timeout
        while PROMPT not in self.port.rx and time.time() < deadline:
            self.port.poll(0.1)
        if PROMPT not in self.port.rx:
            raise TimeoutError(Port.show(bytes(self.port.rx)))
        out = bytes(self.port.rx)
        self.port.take()
        return out[: out.index(PROMPT)]

    def command(self, line, timeout=60):
        """Type a shell command and return its output without the echo."""
        self.port.take()
        self.port.write(line.encode() + b"\r")
        out = self.wait_prompt(timeout).decode("ascii", "replace")
        return re.sub(r"^.*?\r\n", "", out, count=1, flags=re.S).strip("\r\n")

    def close(self):
        """Release the serial line."""
        self.port.close()
