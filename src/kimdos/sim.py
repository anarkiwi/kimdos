"""KIM-1 machine: py65 6502 with monitor traps and a serial bus user port.

User port wiring: PA3/PA4/PA5 drive ATN/CLK/DATA through inverting open
collector buffers (pin high asserts the line); PA6/PA7 read CLK/DATA.
"""

from collections import deque
from typing import NamedTuple

from py65.devices.mpu6502 import MPU
from py65.memory import ObservableMemory

from .iec import ALL, Bus, Drive

GETCH, OUTCH, CRLF, PRTBYT, START = 0x1E5A, 0x1EA0, 0x1E2F, 0x1E3B, 0x1C4F
SENTINEL = 0xFFF0
IO = range(0x1700, 0x1740)
ROM = range(0x1800, 0x2000)
CHAR_CYCLES = 8300
ACCESS_CYCLE = 3
CYCLES, INPUT, MONITOR, RETURN, ROM_CALL = "cycles", "input", "monitor", "return", "rom"


class Memory(ObservableMemory):
    """ObservableMemory with a fast path for unobserved addresses."""

    def __init__(self):
        super().__init__()
        self._read_subscribers = {}
        self._write_subscribers = {}

    def __getitem__(self, address):
        cbs = self._read_subscribers.get(address)
        if cbs:
            result = None
            for cb in cbs:
                r = cb(address)
                if r is not None:
                    result = r
            if result is not None:
                return result
        return self._subject[address]

    def __setitem__(self, address, value):
        cbs = self._write_subscribers.get(address)
        if cbs:
            for cb in cbs:
                r = cb(address, value)
                if r is not None:
                    value = r
        self._subject[address] = value


class Port:
    """6530 at $1700: port A on the serial bus, port B and interval timer.

    Timer writes at offsets 4-15 select divider 1/8/64/1024 by the low two
    address bits; odd reads give the underflow flag in bit 7.
    """

    def __init__(self, bus, mpu=None):
        self.bus, self.mpu = bus, mpu
        self.reg = [0, 0, 0, 0]
        self.timer = (0, 0, 0)

    def now(self):
        """Bus time of the current memory access."""
        return self.mpu.processorCycles + ACCESS_CYCLE if self.mpu else 0

    @staticmethod
    def pins(out, ddr):
        """Pin levels of a port: output bit where DDR=1, pulled up elsewhere."""
        return (out & ddr | ~ddr) & 0xFF

    def host_mask(self):
        """Released-line mask driven onto the bus by PA3-PA5."""
        return (~self.pins(self.reg[0], self.reg[1]) >> 3) & ALL

    def read(self, address):
        """Memory read hook."""
        r = address & 0x3F
        if r == 0:
            lines = self.bus.lines(self.now())
            return self.pins(self.reg[0], self.reg[1]) & 0x3F | (lines & 6) << 5
        if r == 2:
            return self.pins(self.reg[2], self.reg[3])
        if r < 4:
            return self.reg[r]
        if r < 16:
            t0, value, shift = self.timer
            e = self.now() - t0
            if e <= value << shift:
                return 0 if r & 1 else value - (e >> shift)
            return 0x80 if r & 1 else (0xFF - (e - (value << shift) - 1)) & 0xFF
        return None

    def write(self, address, value):
        """Memory write hook."""
        r = address & 0x3F
        if r < 4:
            self.reg[r] = value
            if r < 2:
                self.bus.set_host(self.host_mask(), self.now())
        elif r < 16:
            self.timer = (self.now(), value, (0, 3, 6, 10)[r & 3])


class CallResult(NamedTuple):
    """Outcome of Kim.call."""

    reason: str
    a: int
    x: int
    y: int
    p: int
    cycles: int

    @property
    def carry(self):
        """Carry flag."""
        return bool(self.p & 1)


class Kim:  # pylint: disable=too-many-instance-attributes
    """KIM-1 with RAM, monitor ROM traps and a serial bus on the user port.

    drives: a Drive, a list of drives, or None for one default drive.
    ram: optional (start, end) inclusive ranges accepting writes; others are ROM.
    """

    def __init__(
        self, image=b"", org=0x0200, drives=None, ram=None, char_cycles=CHAR_CYCLES
    ):  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self.mem = Memory()
        self.mpu = MPU(memory=self.mem, pc=org)
        if drives is None:
            drives = [Drive()]
        elif isinstance(drives, Drive):
            drives = [drives]
        self.port = Port(Bus(drives, host=0), self.mpu)
        self.bus = self.port.bus
        self.mem.subscribe_to_read(IO, self.port.read)
        self.mem.subscribe_to_write(IO, self.port.write)
        if ram is not None:
            ok = bytearray(0x10000)
            for lo, hi in ram:
                ok[lo : hi + 1] = b"\1" * (hi + 1 - lo)
            ok[IO.start : IO.stop] = b"\1" * len(IO)
            sub = self.mem._subject  # pylint: disable=protected-access
            self.mem.subscribe_to_write(
                [a for a in range(0x10000) if not ok[a]], lambda a, _: sub[a]
            )
        self.char_cycles = char_cycles
        self.inq = deque()
        self.out = bytearray()
        self.traps = dict.fromkeys(ROM, lambda: ROM_CALL)
        self.traps.update(
            {
                GETCH: self._getch,
                OUTCH: self._outch,
                CRLF: self._crlf,
                PRTBYT: self._prtbyt,
                START: lambda: MONITOR,
                SENTINEL: lambda: RETURN,
            }
        )
        self.write(org, image)

    @property
    def drives(self):
        """Drives on the bus."""
        return self.bus.drives

    @property
    def drive(self):
        """First drive on the bus."""
        return self.bus.drives[0]

    @property
    def output(self):
        """Text written by OUTCH and friends."""
        return self.out.decode("latin-1")

    @property
    def cycles(self):
        """Elapsed CPU cycles (microseconds)."""
        return self.mpu.processorCycles

    def type(self, text):
        """Queue input characters for GETCH."""
        self.inq.extend(text.encode("latin-1") if isinstance(text, str) else text)

    def read(self, address, n=1):
        """Read raw memory without side effects."""
        return bytes(self.mem._subject[address : address + n])  # pylint: disable=W0212

    def write(self, address, data):
        """Write raw memory without side effects."""
        self.mem._subject[address : address + len(data)] = data  # pylint: disable=W0212

    def _rts(self, chars):
        m = self.mpu
        m.x, m.y = 0xA5, 0x5A
        m.pc = (m.stPopWord() + 1) & 0xFFFF
        m.processorCycles += chars * self.char_cycles

    def _getch(self):
        if not self.inq:
            return INPUT
        self.mpu.a = self.inq.popleft()
        self.out.append(self.mpu.a)
        return self._rts(1)

    def _outch(self):
        self.out.append(self.mpu.a)
        return self._rts(1)

    def _crlf(self):
        self.out += b"\r\n"
        return self._rts(2)

    def _prtbyt(self):
        self.out += b"%02X" % self.mpu.a
        return self._rts(2)

    def run(self, max_cycles=10_000_000):
        """Execute until a trap stops the machine or max_cycles elapse."""
        mpu, traps = self.mpu, self.traps
        step, get = mpu.step, traps.get
        end = mpu.processorCycles + max_cycles
        reason = CYCLES
        while mpu.processorCycles < end:
            h = get(mpu.pc)
            if h is None:
                step()
            elif r := h():
                reason = r
                break
        self.bus.sync(mpu.processorCycles)
        return reason

    def call(
        self, address, a=0, x=0, y=0, carry=False, max_cycles=10_000_000
    ):  # pylint: disable=too-many-arguments,too-many-positional-arguments
        """JSR to address and run until it returns; return CallResult."""
        m = self.mpu
        m.stPushWord(SENTINEL - 1)
        m.pc, m.a, m.x, m.y = address, a, x, y
        m.p = m.p & 0xFE | int(carry)
        c0 = m.processorCycles
        reason = self.run(max_cycles)
        return CallResult(reason, m.a, m.x, m.y, m.p, m.processorCycles - c0)
