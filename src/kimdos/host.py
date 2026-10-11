"""Scripted host-side bus controller, standard and JiffyDOS, in simulated
time: a reference for the drive model."""

from .iec import (
    ALL,
    ATN,
    CLK,
    DATA,
    RX_BITS,
    T_EOI,
    T_EOI_ACK,
    T_FRAME,
    T_JHOST,
    T_JPOST,
    _clk_asr,
    _clk_rel,
    _data_asr,
    _data_rel,
)

# The 6502 library's Jiffy schedules, us. JRX: ready seen to start, then
# after the start the reads (4 pairs, status) and the acknowledge. JTX: ready
# seen to start, then the writes (4 pairs, EOI flag, CLK held) and the
# acknowledge read. JLOAD: ready seen to start, the start pulse's end, the
# reads (4 pairs, marker), the byte period, then the block acknowledge's
# start and end after the marker read.
JRX = (12, 16, 26, 37, 47, 60, 70)
JTX = (10, 8, 24, 36, 48, 61, 75, 79)
JLOAD = (14, 4, 16, 26, 37, 47, 60, 114, 49, 19)


class BusTimeout(Exception):
    """Raised by HostBitbang when an expected bus response does not arrive."""


class HostBitbang:  # pylint: disable=too-many-instance-attributes,too-many-public-methods
    """Scripted host-side bus controller running in simulated time.

    Polls every `poll` us; `t_setup`/`t_valid` are its bit timings, `t_ne` its
    delay before asserting CLK for a byte and `t_atn` its hold after ATN
    before the first command byte. With jiffy it offers JiffyDOS on every
    TALK/LISTEN; jrx, jtx and jload are its Jiffy schedules (us after its
    start edge), those of the 6502 library.
    """

    jrx = JRX
    jtx = JTX
    jload_at = JLOAD

    def __init__(
        self, bus, poll=2, t_setup=20, t_valid=20, t_ne=10, t_atn=T_FRAME, jiffy=False
    ):  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self.bus, self.poll, self.timeout = bus, poll, 2_000_000
        self.t_setup, self.t_valid, self.t_ne = t_setup, t_valid, t_ne
        self.t_atn = t_atn
        self.jiffy = jiffy
        self.jact = False
        self.t = 0
        self.mask = bus.host

    def set(self, release=0, assert_=0):
        """Release and assert host lines at the current time."""
        self.mask = (self.mask | release) & ~assert_ & ALL
        self.bus.set_host(self.mask, self.t)

    def delay(self, us):
        """Advance host time."""
        self.t += us

    def wait(self, pred, timeout):
        """Poll until pred(lines) holds; return the lines or None on timeout."""
        end = self.t + timeout
        while True:
            v = self.bus.lines(self.t)
            if pred(v):
                return v
            if self.t >= end:
                return None
            self.t = min(self.t + self.poll, end)

    def _must(self, pred, timeout, what):
        v = self.wait(pred, timeout)
        if v is None:
            raise BusTimeout(f"{self.t}: {what}")
        return v

    def send(self, b, eoi=False, detect=False):
        """Send one byte as talker (CLK held asserted on entry and exit); with
        detect, wait before bit 7 for a JiffyDOS reply."""
        self.set(release=CLK)
        self._must(_data_rel, self.timeout, "listener not ready")
        if eoi:
            self._must(_data_asr, T_FRAME, "EOI ack")
            self._must(_data_rel, T_FRAME, "EOI ack end")
        self.delay(self.t_ne)
        self.set(assert_=CLK)
        for i in range(8):
            if i == 7 and detect and self.wait(_data_asr, T_JHOST) is not None:
                self.jact = True
                self._must(_data_rel, T_FRAME, "Jiffy acknowledge end")
            bit = DATA if b >> i & 1 else 0
            self.set(release=bit, assert_=DATA ^ bit)
            self.delay(self.t_setup)
            self.set(release=CLK)
            self.delay(self.t_valid)
            self.set(release=DATA, assert_=CLK)
        self._must(_data_asr, T_FRAME, "frame ack")

    def recv(self, ack=True):
        """Receive one byte as listener; return (byte, eoi)."""
        if self.jact:
            return self.jrecv()
        self._must(_clk_rel, self.timeout, "talker not ready")
        self.set(release=DATA)
        eoi = self.wait(_clk_asr, T_EOI) is None
        if eoi:
            self.set(assert_=DATA)
            self.delay(T_EOI_ACK + 4)
            self.set(release=DATA)
            self._must(_clk_asr, T_FRAME, "read timeout")
        b = 0
        for i in range(8):
            v = self._must(_clk_rel, T_FRAME, f"bit {i} start")
            b |= (v >> 2 & 1) << i
            self._must(_clk_asr, T_FRAME, f"bit {i} end")
        if ack:
            self.set(assert_=DATA)
        return b, eoi

    def write(self, data):
        """Send bytes as talker, EOI on the last."""
        for i, b in enumerate(data):
            (self.jsend if self.jact else self.send)(b, i == len(data) - 1)

    def atn(self, *cmds):
        """Assert ATN and send command bytes."""
        self.set(release=DATA, assert_=ATN | CLK)
        t0 = self.t
        self._must(_data_asr, T_FRAME, "device not present")
        self.t = max(self.t, t0 + self.t_atn)
        self.jact = False
        for i, c in enumerate(cmds):
            self.send(c, detect=self.jiffy and not i and c < 0x60 and ~c & 0x1F)

    def _sample(self, t):
        self.t = t
        return self.bus.lines(t)

    def _put(self, t, assert_):
        self.t = t
        self.set(release=CLK | DATA, assert_=assert_)

    def jrecv(self):
        """Receive one byte with JiffyDOS; return (byte, eoi)."""
        self._must(_clk_rel, self.timeout, "talker not ready")
        w = self.t + self.jrx[0]
        self._put(w, 0)
        b = 0
        for k in range(4):
            v = self._sample(w + self.jrx[k + 1])
            b |= (v >> 1 & 1) << 2 * k | (v >> 2 & 1) << 2 * k + 1
        v = self._sample(w + self.jrx[5])
        self.t = w + self.jrx[6]
        self.set(assert_=DATA)
        self.delay(T_JPOST)
        if v & CLK and v & DATA:
            raise BusTimeout(f"{self.t}: read timeout")
        return b, bool(v & CLK)

    def jsend(self, b, eoi=False):
        """Send one byte with JiffyDOS (CLK held asserted on entry and exit)."""
        self._must(_data_rel, self.timeout, "listener not ready")
        w = self.t + self.jtx[0]
        self._put(w, 0)
        for k, (cb, db) in enumerate(RX_BITS):
            self._put(w + self.jtx[k + 1], (b >> cb & 1) * CLK | (b >> db & 1) * DATA)
        self._put(w + self.jtx[5], 0 if eoi else CLK)
        self._put(w + self.jtx[6], CLK)
        if self._sample(w + self.jtx[7]) & DATA:
            raise BusTimeout(f"{self.t}: Jiffy byte not acknowledged")

    def jstream(self):
        """Receive a JiffyDOS LOAD stream after TALK with secondary $61."""
        at = self.jload_at
        self.set(release=DATA)
        out = bytearray()
        while True:
            if self._must(_clk_rel, self.timeout, "block") & DATA:
                return bytes(out)
            self._must(_data_rel, self.timeout, "byte")
            w = self.t + at[0]
            while True:
                self._put(w, DATA)
                self._put(w + at[1], 0)
                b = 0
                for k in range(4):
                    v = self._sample(w + at[k + 2])
                    b |= (v >> 1 & 1) << 2 * k | (v >> 2 & 1) << 2 * k + 1
                out.append(b)
                if len(out) > 0xFFFF:
                    raise BusTimeout(f"{self.t}: LOAD stream does not end")
                if not self._sample(w + at[6]) & CLK:
                    break
                w += at[7]
            self._put(self.t + at[8], DATA)
            self._put(self.t + at[9], 0)

    def jload(self, name, dev=8):
        """LOAD the way the 6502 library does with a JiffyDOS device: the load
        address in single-byte mode, the rest in LOAD mode."""
        self.open(dev, 0, name)
        self.talk(dev, 0x60)
        head = bytes(self.jrecv()[0] for _ in range(2))
        self.untalk()
        self.talk(dev, 0x61)
        out = head + self.jstream()
        self.untalk()
        self.close(dev, 0)
        return out

    def listen(self, dev, sa):
        """LISTEN dev with secondary sa; host stays talker."""
        self.atn(0x20 + dev, sa)
        self.set(release=ATN)
        self.delay(20)

    def unlisten(self):
        """UNLISTEN and release the bus."""
        self.atn(0x3F)
        self.set(release=ATN)
        self.delay(20)
        self.set(release=ALL)

    def talk(self, dev, sa):
        """TALK dev with secondary sa and perform the turnaround."""
        self.atn(0x40 + dev, sa)
        self.set(release=ATN, assert_=DATA)
        self.delay(20)
        self.set(release=CLK)
        self._must(_clk_asr, T_FRAME, "turnaround")

    def untalk(self):
        """UNTALK and release the bus."""
        self.atn(0x5F)
        self.set(release=ATN)
        self.delay(20)
        self.set(release=ALL)

    def read(self, dev, ch, limit=None):
        """TALK and read bytes until EOI (or limit bytes), then UNTALK."""
        self.talk(dev, 0x60 | ch)
        out = bytearray()
        try:
            while limit is None or len(out) < limit:
                b, eoi = self.recv()
                out.append(b)
                if eoi:
                    break
        finally:
            self.untalk()
        return bytes(out)

    def open(self, dev, ch, name):
        """OPEN channel ch with a filename."""
        self.listen(dev, 0xF0 | ch)
        self.write(name)
        self.unlisten()

    def close(self, dev, ch):
        """CLOSE channel ch."""
        self.listen(dev, 0xE0 | ch)
        self.unlisten()

    def load(self, name, dev=8):
        """OPEN/read/CLOSE channel 0."""
        self.open(dev, 0, name)
        try:
            return self.read(dev, 0)
        finally:
            self.close(dev, 0)

    def save(self, name, data, dev=8):
        """OPEN/write/CLOSE channel 1."""
        self.open(dev, 1, name)
        self.listen(dev, 0x61)
        self.write(data)
        self.unlisten()
        self.close(dev, 1)

    def command(self, cmd, dev=8):
        """Send a DOS command on channel 15."""
        self.listen(dev, 0x6F)
        self.write(cmd)
        self.unlisten()

    def status(self, dev=8):
        """Read the status string from channel 15."""
        return self.read(dev, 15)
