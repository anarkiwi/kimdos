"""Commodore serial (IEC) bus, disk drive and host bus master models.

Line states are bit masks where a set bit means the line is released (high)
and a clear bit means it is asserted (pulled low). Time is in microseconds.
"""

import re
from dataclasses import dataclass
from bisect import bisect_right

ATN, CLK, DATA = 1, 2, 4
ALL = ATN | CLK | DATA
NEVER = 1 << 62
IDLE = (None, NEVER)
T_EOI = 200
T_EOI_ACK = 60
T_FRAME = 1000
T_TURN = 80
BLOCK = 254
DISK_BLOCKS = 664


def _clk_rel(v):
    return v & CLK


def _clk_asr(v):
    return not v & CLK


def _data_rel(v):
    return v & DATA


def _data_asr(v):
    return not v & DATA


def _atn_rel(v):
    return v & ATN


def _clk_asr_or_atn_rel(v):
    return v & ATN or not v & CLK


def _clk_or_atn_rel(v):
    return v & (ATN | CLK)


def status_line(code, msg, a=0, b=0):
    """Format a DOS status line as returned on channel 15."""
    return b"%02d,%s,%02d,%02d\r" % (code, msg, a, b)


OK = status_line(0, b" OK")


def match(pattern, name):
    """CBM filename match: `?` matches one char, `*` matches the rest."""
    for i, c in enumerate(pattern):
        if c == 0x2A:
            return True
        if i >= len(name) or c not in (0x3F, name[i]):
            return False
    return len(pattern) == len(name)


def parse_name(name):
    """Split a filename into (replace flag, bare name) dropping drive and type."""
    m = re.match(rb"(@)?(?:\d?:)?([^,\r]*)", name)
    return bool(m[1]), m[2]


def open_mode(name, ch):
    """(mode, type) of an OPEN name's ,type,mode suffixes as sd2iec reads them.

    Mode is R, W or A; channels 0 and 1 force read and write; the type
    defaults to PRG on those and SEQ on others.
    """
    mode, ftype = b"R", b"D"
    for f in name.split(b",")[1:3]:
        c = f[:1]
        if c in (b"R", b"W", b"A"):
            mode = c
        elif c == b"M":
            mode = b"R"
        elif c and c in b"DSPU":
            ftype = c
    if ch < 2:
        mode = b"RW"[ch : ch + 1]
    if ftype == b"D":
        ftype = b"P" if ch < 2 else b"S"
    return mode, {b"P": b"PRG", b"S": b"SEQ", b"U": b"USR"}[ftype]


class BusTimeout(Exception):
    """Raised by HostBitbang when an expected bus response does not arrive."""


class Bus:
    """Wired-AND serial bus with a timed history of host outputs."""

    def __init__(self, drives=(), host=ALL):
        self.drives = []
        self.host = host
        self.times = [-NEVER]
        self.states = [host]
        self.gen = 0
        for d in drives:
            self.attach(d)

    def attach(self, drive):
        """Connect a drive to the bus."""
        drive.bus = self
        self.drives.append(drive)
        return drive

    def sync(self, t):
        """Advance every drive to time t."""
        for d in self.drives:
            d.advance(t)

    def outputs(self, skip=None):
        """Wired-AND of all drive outputs, optionally excluding one drive."""
        m = ALL
        for d in self.drives:
            if d is not skip:
                m &= d.out
        return m

    def lines(self, t):
        """Bus line state seen by the host at time t."""
        self.sync(t)
        return self.host & self.outputs()

    def set_host(self, mask, t):
        """Change the host's released-line mask at time t."""
        self.sync(t)
        mask &= ALL
        if mask == self.host:
            return
        self.host = mask
        self.gen += 1
        if t <= self.times[-1]:
            self.states[-1] = mask
            return
        self.times.append(t)
        self.states.append(mask)
        if len(self.times) > 4096:
            lo = min((d.now - d.latency for d in self.drives if d.present), default=t)
            i = bisect_right(self.times, lo) - 1
            del self.times[:i], self.states[:i]

    def host_at(self, t):
        """Host output mask at time t."""
        return self.states[bisect_right(self.times, t) - 1]


@dataclass(slots=True)
class _Chan:
    data: bytes | bytearray
    name: bytes | None = None
    write: bool = False
    pos: int = 0
    seek: bool = True
    ftype: bytes = b"PRG"


class Drive:  # pylint: disable=too-many-instance-attributes
    """Serial bus disk drive with an in-memory filesystem.

    files maps PETSCII names to contents (PRG contents include the load
    address). The drive reacts to host line changes `latency` us late.
    """

    def __init__(
        self,
        files=None,
        device=8,
        present=True,
        latency=0,
        t_setup=20,
        t_valid=20,
        t_ready=20,
        sector_delay=0,
        t_ne=20,
        t_ack=20,
        disk_name=b"KIMDOS",
        disk_id=b"KD",
    ):  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self.files = {} if files is None else files
        self.types = {}
        self.device, self.present, self.latency = device, present, latency
        self.t_setup, self.t_valid, self.t_ready = t_setup, t_valid, t_ready
        self.sector_delay, self.t_ne, self.t_ack = sector_delay, t_ne, t_ack
        self.disk_name, self.disk_id = disk_name, disk_id
        self.errors = []
        self.status = status_line(73, b"KIMDOS SIM")
        self.bus = None
        self.out = ALL
        self.now = 0
        self.gen = None
        self.wait = IDLE
        self.in_atn = False
        self._seen = -1
        self.listen = self.talk = False
        self.sa = None
        self.chans = {}
        self.name = bytearray()
        self.cmd = bytearray()
        self.tail_eoi = None

    def advance(self, t):
        """Run the drive state machine up to time t."""
        if not self.present or t < self.now:
            return
        bus = self.bus
        while True:
            pred, deadline = self.wait
            if deadline > t and self._seen == bus.gen:
                self.now = t
                return
            hit = self._scan(pred, min(t, deadline))
            if hit is not None:
                self.now, v = hit
                if self.in_atn or v & ATN:
                    self._resume(v)
                    continue
                if self.gen is not None:
                    self.gen.close()
                self.in_atn = True
                self.gen = self._session()
                self.wait = next(self.gen)
            elif deadline <= t:
                self.now = deadline
                self._resume(None)
            else:
                self.now = t
                self._seen = bus.gen if bus.times[-1] + self.latency <= t else -1
                return

    def _scan(self, pred, end):
        bus, lat = self.bus, self.latency
        times, states = bus.times, bus.states
        mask = self.out & bus.outputs(self)
        i = bisect_right(times, self.now - lat) - 1
        t = self.now
        while t <= end:
            v = states[i] & mask
            if (not self.in_atn and not v & ATN) or (pred is not None and pred(v)):
                return t, v
            i += 1
            if i == len(times):
                return None
            t = times[i] + lat
        return None

    def _resume(self, v):
        self._seen = -1
        try:
            self.wait = self.gen.send(v)
        except StopIteration:
            self.gen, self.wait = None, IDLE

    def _out(self, mask):
        self.out = mask | ATN
        self.bus.gen += 1

    def _error(self, msg):
        self.errors.append(f"{self.now}: {msg}")

    def _session(self):
        self._out(CLK)
        while True:
            r = yield from self._recv(True)
            if r is None:
                break
            if not self._command(r[0]):
                self._out(ALL)
                yield _atn_rel, NEVER
                self.in_atn = False
                return
        self.in_atn = False
        if self.talk:
            yield _clk_rel, NEVER
            self._out(DATA)
            yield None, self.now + T_TURN
            yield from self._talk()
        elif self.listen:
            buf = self._sink()
            if buf is None:
                self._out(ALL)
                return
            while True:
                b, self.tail_eoi = yield from self._recv(False)
                buf.append(b)
        self._out(ALL)

    def _recv(self, atn):
        lat = self.latency
        v = yield (_clk_asr_or_atn_rel if atn else _clk_asr), NEVER
        if atn and v & ATN:
            return None
        v = yield (_clk_or_atn_rel if atn else _clk_rel), NEVER
        if atn and v & ATN:
            return None
        yield None, self.now + self.t_ready
        self._out(ALL)
        eoi = (yield _clk_asr, self.now + T_EOI + lat) is None
        if eoi:
            if atn:
                self._error("EOI under ATN")
            self._out(CLK)
            yield None, self.now + T_EOI_ACK
            self._out(ALL)
            yield _clk_asr, NEVER
        b = 0
        for i in range(8):
            v = yield _clk_rel, NEVER
            t1, d = self.now, v & DATA
            v = yield (lambda v, d=d: not v & CLK or v & DATA != d), NEVER
            if v & CLK:
                self._error(f"DATA changed while CLK released (bit {i})")
                yield _clk_asr, NEVER
            if self.now - t1 < lat:
                self._error(f"bit {i} valid {self.now - t1}us < latency {lat}us")
            b |= (d >> 2) << i
        yield None, self.now + self.t_ack
        self._out(CLK)
        return b, eoi

    def _send(self, b, eoi, extra):
        lat = self.latency
        yield None, self.now + self.t_ready + extra
        self._out(ALL)
        yield _data_rel, NEVER
        if eoi:
            if (yield _data_asr, self.now + T_FRAME + lat) is None:
                self._error("EOI ack timeout")
                return False
            t1 = self.now
            yield _data_rel, NEVER
            if self.now - t1 < T_EOI_ACK:
                self._error(f"EOI ack pulse {self.now - t1}us too short")
        yield None, self.now + self.t_ne
        for i in range(8):
            bit = DATA if b >> i & 1 else 0
            self._out(bit)
            yield None, self.now + self.t_setup
            self._out(bit | CLK)
            yield None, self.now + self.t_valid
        self._out(DATA)
        if (yield _data_asr, self.now + T_FRAME + lat) is None:
            self._error("frame ack timeout")
            return False
        return True

    def _talk(self):
        ch = 0 if self.sa is None else self.sa & 15
        chan = _Chan(self.status) if ch == 15 else self.chans.get(ch)
        if chan is None or chan.write or chan.pos >= len(chan.data):
            yield None, self.now + self.t_ready
            self._out(ALL)
            yield IDLE
        n = len(chan.data)
        while chan.pos < n:
            extra = self.sector_delay if ch != 15 and chan.pos % BLOCK == 0 else 0
            if not (
                yield from self._send(chan.data[chan.pos], chan.pos == n - 1, extra)
            ):
                return
            chan.pos += 1
        if ch == 15:
            self.status = OK

    def _command(self, b):
        if b == 0x3F:
            self._unlisten()
        elif b == 0x5F:
            self.talk = False
        elif 0x20 <= b < 0x60:
            if b & 0x1F != self.device:
                self._unlisten()
                self.talk = False
                return False
            if b < 0x40:
                self.listen, self.talk = True, False
            else:
                self._unlisten()
                self.talk = True
            self.sa = None
        elif self.listen or self.talk:
            hi = b & 0xF0
            if hi == 0xE0:
                self._close(b & 15)
                self.sa = None
            elif hi in (0x60, 0x70, 0xF0):
                self.sa = b
                if hi == 0xF0:
                    self.name = bytearray()
        return True

    def _sink(self):
        if self.sa is None:
            return bytearray()
        if self.sa >= 0xF0:
            return self.name
        if self.sa & 15 == 15:
            return self.cmd
        c = self.chans.get(self.sa & 15)
        return c.data if c is not None and c.write else None

    def _unlisten(self):
        if self.listen and self.tail_eoi is False:
            self._error("LISTEN data ended without EOI")
        self.tail_eoi = None
        if self.listen and self.sa is not None:
            if self.sa >= 0xF0:
                self._open(self.sa & 15, bytes(self.name))
            elif self.sa & 15 == 15 and self.cmd:
                self.execute(bytes(self.cmd))
                self.cmd = bytearray()
        self.listen, self.sa = False, None

    def _close(self, ch):
        c = self.chans.pop(ch, None)
        if c is not None and c.write:
            self.files[c.name] = bytes(c.data)
            self.types[c.name] = c.ftype

    def _open(self, ch, name):
        if ch == 15:
            if name:
                self.execute(name)
            return
        self._close(ch)
        if name[:1] == b"$":
            self.status = OK
            self.chans[ch] = _Chan(self.directory(name[1:]), seek=False)
            return
        mode, ftype = open_mode(name, ch)
        replace, pat = parse_name(name)
        key = next((k for k in self.files if match(pat, k)), None)
        if mode == b"W":
            if key is not None and not replace:
                self.status = status_line(63, b"FILE EXISTS")
                return
            self.files.pop(key, None)
            self.status = OK
            self.chans[ch] = _Chan(bytearray(), pat, True, seek=False, ftype=ftype)
            return
        if key is None:
            self.status = status_line(62, b"FILE NOT FOUND")
            return
        self.status = OK
        if mode == b"A":
            ftype = self.types.get(key, b"PRG")
            data = bytearray(self.files[key])
            self.chans[ch] = _Chan(data, key, True, seek=False, ftype=ftype)
        else:
            self.chans[ch] = _Chan(self.files[key])

    def _position(self, cmd):
        c = self.chans.get(cmd[1] & 15) if len(cmd) > 1 else None
        if c is None:
            self.status = status_line(70, b"NO CHANNEL")
        elif not c.seek:
            self.status = status_line(31, b"SYNTAX ERROR")
        else:
            off = int.from_bytes(cmd[2:6].ljust(4, b"\0"), "little")
            c.pos = min(off, len(c.data))
            self.status = (
                OK if off <= len(c.data) else status_line(50, b"RECORD NOT PRESENT")
            )

    def directory(self, pattern=b""):
        """Directory listing as a BASIC program image loaded at $0401."""
        pattern = pattern.rstrip(b"\r")
        pattern = b"*" if pattern in (b"", b"0") else parse_name(pattern)[1]
        head = b'\x12"' + self.disk_name.ljust(16)[:16] + b'" ' + self.disk_id
        lines = [(0, head + b" 2A")]
        used = 0
        for k, v in self.files.items():
            blocks = -(-len(v) // BLOCK)
            used += blocks
            if match(pattern, k):
                pad = b" " * (4 - len(str(blocks)))
                ftype = self.types.get(k, b"PRG")
                lines.append(
                    (blocks, pad + b'"' + k + b'"' + b" " * (17 - len(k)) + ftype)
                )
        lines.append((max(0, DISK_BLOCKS - used), b"BLOCKS FREE."))
        out, addr = bytearray(b"\x01\x04"), 0x0401
        for num, text in lines:
            addr += len(text) + 5
            out += addr.to_bytes(2, "little") + num.to_bytes(2, "little")
            out += text + b"\0"
        return bytes(out + b"\0\0")

    def execute(self, cmd):
        """Execute a DOS command string and set the status."""
        if cmd[:1] == b"P":
            self._position(cmd)
            return
        cmd = cmd.rstrip(b"\r")
        if re.fullmatch(rb"I0?:?", cmd):
            self.status = OK
        elif cmd[:2] == b"UI":
            self.status = status_line(73, b"KIMDOS SIM")
        elif m := re.fullmatch(rb"S\d?:(.*)", cmd, re.S):
            pats = [parse_name(p)[1] for p in m[1].split(b",")]
            gone = [k for k in self.files if any(match(p, k) for p in pats)]
            for k in gone:
                del self.files[k]
                self.types.pop(k, None)
            self.status = status_line(1, b" FILES SCRATCHED", len(gone))
        elif m := re.fullmatch(rb"R\d?:([^=]*)=(.*)", cmd, re.S):
            new, old = m[1], parse_name(m[2])[1]
            if old not in self.files:
                self.status = status_line(62, b"FILE NOT FOUND")
            elif new in self.files:
                self.status = status_line(63, b"FILE EXISTS")
            else:
                self.files[new] = self.files.pop(old)
                self.types[new] = self.types.pop(old, b"PRG")
                self.status = OK
        else:
            self.status = status_line(31, b"SYNTAX ERROR")


class HostBitbang:  # pylint: disable=too-many-instance-attributes
    """Scripted host-side bus controller running in simulated time.

    Polls every `poll` us; `t_setup`/`t_valid` are its bit timings, `t_ne` its
    delay before asserting CLK for a byte and `t_atn` its hold after ATN
    before the first command byte.
    """

    def __init__(
        self, bus, poll=2, t_setup=20, t_valid=20, t_ne=10, t_atn=T_FRAME
    ):  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self.bus, self.poll, self.timeout = bus, poll, 2_000_000
        self.t_setup, self.t_valid, self.t_ne = t_setup, t_valid, t_ne
        self.t_atn = t_atn
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

    def send(self, b, eoi=False):
        """Send one byte as talker (CLK held asserted on entry and exit)."""
        self.set(release=CLK)
        self._must(_data_rel, self.timeout, "listener not ready")
        if eoi:
            self._must(_data_asr, T_FRAME, "EOI ack")
            self._must(_data_rel, T_FRAME, "EOI ack end")
        self.delay(self.t_ne)
        self.set(assert_=CLK)
        for i in range(8):
            bit = DATA if b >> i & 1 else 0
            self.set(release=bit, assert_=DATA ^ bit)
            self.delay(self.t_setup)
            self.set(release=CLK)
            self.delay(self.t_valid)
            self.set(release=DATA, assert_=CLK)
        self._must(_data_asr, T_FRAME, "frame ack")

    def recv(self, ack=True):
        """Receive one byte as listener; return (byte, eoi)."""
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
            self.send(b, i == len(data) - 1)

    def atn(self, *cmds):
        """Assert ATN and send command bytes."""
        self.set(release=DATA, assert_=ATN | CLK)
        t0 = self.t
        self._must(_data_asr, T_FRAME, "device not present")
        self.t = max(self.t, t0 + self.t_atn)
        for c in cmds:
            self.send(c)

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
