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
T_JDET = 218
T_JACK = 101
T_JTALK = 360
T_JREADY = 50
T_JEOF = 100
T_JREFILL = 120
T_JHOST = 400
T_JPOST = 30
RX_BITS = ((4, 5), (6, 7), (3, 1), (2, 0))
SINGLE, MID, FINAL = range(3)


@dataclass(frozen=True)
class JiffyTiming:  # pylint: disable=too-many-instance-attributes
    """Device-side JiffyDOS timing, us after the host's start edge.

    tx: the drive talking, when each of the four bit pairs (CLK = bit 2k,
    DATA = bit 2k+1, released = 1) and then the EOI/status mark go out.
    rx: the drive listening, when it samples the four bit pairs (bits
    RX_BITS, pulled = 1) and then CLK for EOI; ack: when it pulls DATA, for
    pulse. hold: after the host acknowledges a sent byte, before returning.
    gap: LOAD mode, last pair to the release for the next byte. arm_tx,
    arm_rx: from releasing the bus to watching for the host's start edge.
    """

    tx: tuple
    rx: tuple
    ack: float
    pulse: float
    hold: float
    gap: float
    arm_tx: float
    arm_rx: float


def _avr(phase_tx, phase_rx):
    """sd2iec on an 8 MHz AVR (fastloader-ll.S as built by avr-gcc 7.3): cycle
    offsets of each port access after the polling loop saw the start edge
    phase cycles late."""
    return JiffyTiming(
        tx=tuple((79 + phase_tx + c) / 8 for c in (0, 80, 168, 248, 336)),
        rx=tuple((136 + phase_rx + c) / 8 for c in (0, 104, 192, 296, 400)),
        ack=(136 + phase_rx + 450) / 8,
        pulse=10,
        hold=0,
        gap=83 / 8,
        arm_tx=10 / 8,
        arm_rx=2 / 8,
    )


JIFFY_LPC = JiffyTiming(
    tx=(10, 20, 31, 41, 52),
    rx=(18.5, 31.5, 42.5, 55.5, 67),
    ack=73,
    pulse=10,
    hold=10,
    gap=10,
    arm_tx=3,
    arm_rx=1,
)
JIFFY_AVR_EARLY = _avr(0.5, 0.5)
JIFFY_AVR_LATE = _avr(6.5, 5.5)


def _any(_):
    return True


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
        """Bus line state seen by the host at time t; a drive in a JiffyDOS
        transfer notes the read."""
        self.sync(t)
        for d in self.drives:
            if d.reads is not None:
                d.reads.append(t)
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
            lo = min(
                (min(d.now - d.latency, d.keep) for d in self.drives if d.present),
                default=t,
            )
            i = bisect_right(self.times, lo) - 1
            del self.times[:i], self.states[:i]

    def host_at(self, t):
        """Host output mask at time t."""
        return self.states[bisect_right(self.times, t) - 1]

    def changed(self, lo, hi, bits):
        """Whether the host changed any of bits in (lo, hi]."""
        i, j = bisect_right(self.times, lo) - 1, bisect_right(self.times, hi)
        return any((s ^ self.states[i]) & bits for s in self.states[i + 1 : j])


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
    jiffy is the JiffyDOS timing (None for a drive without it); in Jiffy
    transfers the host must sample and drive the bus at least `margin` us
    away from the drive's own edges and sample points.
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
        jiffy=JIFFY_LPC,
        margin=2,
    ):  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self.files = {} if files is None else files
        self.types = {}
        self.device, self.present, self.latency = device, present, latency
        self.t_setup, self.t_valid, self.t_ready = t_setup, t_valid, t_ready
        self.sector_delay, self.t_ne, self.t_ack = sector_delay, t_ne, t_ack
        self.disk_name, self.disk_id = disk_name, disk_id
        self.jiffy, self.margin = jiffy, margin
        self.jact = self.jload = False
        self.reads = None
        self.keep = NEVER
        self.deaf = 0
        self.jpend = None
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
            if (not self.in_atn and not v & ATN and t >= self.deaf) or (
                pred is not None and pred(v)
            ):
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

    def _at(self, t, deaf=False):
        """Wait until t; deaf: ignore ATN meanwhile, as sd2iec's busy loops do."""
        if deaf:
            self.deaf = t
        if t > self.now:
            yield None, t

    def _session(self):
        self.jact = self.jload = False
        self.jpend = None
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
                b, self.tail_eoi = yield from (
                    self._jrecv() if self.jact else self._recv(False)
                )
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
            if i == 7 and atn and b < 0x60 and b & 0x1F == self.device:
                yield from self._jdetect()
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

    def _jdetect(self):
        """A host delaying the last bit of TALK/LISTEN past T_JDET speaks
        JiffyDOS: pull DATA for T_JACK in reply."""
        if self.jiffy is None or self.jact:
            return
        if (yield _clk_rel, self.now + T_JDET) is not None:
            return
        self._out(CLK)
        t1 = self.now
        self.keep = t1 - self.latency - 1
        yield None, self.now + T_JACK
        self._out(ALL)
        self.jact = True
        lat = self.latency
        if self.bus.changed(t1 - lat, self.now - lat, CLK):
            self._error("host moved CLK during the JiffyDOS acknowledge")
        self.keep = NEVER

    def _check_reads(self, start, end, allowed, required):
        """Host bus reads in [start, end) must fall in an allowed window and
        each required window needs one; windows are (lo, hi) with the margin
        already taken off."""
        reads = [t for t in self.reads if start <= t < end]
        self.reads = [t for t in self.reads if t >= end]
        for t in reads:
            if not any(lo <= t <= hi for lo, hi in allowed):
                self._error(f"Jiffy: host sampled at +{t - start:g}us, off the windows")
        for lo, hi in required:
            if not any(lo <= t <= hi for t in reads):
                self._error(f"Jiffy: no sample in +{lo - start:g}..+{hi - start:g}us")

    def _jsend(self, b, eoi, mode):
        """Send b as sd2iec's jiffy_send: SINGLE for a byte with EOI/status
        and the host's acknowledge, MID/FINAL for LOAD mode."""
        jt, m = self.jiffy, self.margin
        self._out(ALL)
        yield from self._at(self.now + jt.arm_tx)
        v = yield _any, NEVER
        if mode == SINGLE:
            if v & DATA:
                self._error("Jiffy: host released DATA before the drive was armed")
            else:
                yield _data_rel, NEVER
        else:
            if not v & DATA:
                self._error("Jiffy LOAD: host pulled DATA before the drive was armed")
                yield _data_rel, NEVER
            yield _data_asr, NEVER
        ref = self.now
        self.deaf = ref + jt.tx[3]
        if self.jpend is not None:
            self._check_reads(*self.jpend[:1], ref, *self.jpend[1:])
        elif self.reads is None:
            self.reads = []
        for k in range(4):
            yield from self._at(ref + jt.tx[k])
            self._out(
                (CLK if b >> 2 * k & 1 else 0) | (DATA if b >> 2 * k + 1 & 1 else 0)
            )
        last = ref + (jt.tx[3] + jt.gap if mode == MID else jt.tx[4])
        pairs = [(ref + jt.tx[k] + m, ref + jt.tx[k + 1] - m) for k in range(3)]
        pairs.append((ref + jt.tx[3] + m, last - m))
        if mode == MID:
            yield from self._at(last)
            self.jpend = ref, pairs + [(last + m, NEVER)], pairs
            return
        self.jpend = None
        yield from self._at(last)
        self._out(CLK if eoi else DATA)
        yield _data_asr, NEVER
        end = self.now
        yield from self._at(self.now + jt.hold, deaf=True)
        if eoi:
            yield from self._at(self.now + T_JREADY, deaf=True)
            end = self.now
            self._out(DATA)
        status = [(last + m, end - (m if eoi else 0))]
        self._check_reads(ref, self.now, pairs + [(last + m, NEVER)], pairs + status)
        self.reads = None

    def _jrecv(self):
        """Receive a byte as sd2iec's jiffy_receive; return (byte, eoi)."""
        jt, lat, m = self.jiffy, self.latency, self.margin
        self._out(ALL)
        v = yield _any, NEVER
        if v & CLK:
            self._error("Jiffy: CLK released before the drive was ready")
        else:
            yield from self._at(self.now + jt.arm_rx)
            if (yield _any, NEVER) & CLK:
                self._error("Jiffy: host released CLK before the drive was armed")
            else:
                yield _clk_rel, NEVER
        ref = self.now
        self.deaf = ref + jt.ack + jt.pulse
        self.keep = ref - lat - m - 1
        self.reads = []
        b = 0
        for k, (cb, db) in enumerate(RX_BITS):
            yield from self._at(ref + jt.rx[k])
            v = yield _any, NEVER
            b |= (not v & CLK) << cb | (not v & DATA) << db
        yield from self._at(ref + jt.rx[4])
        v = yield _any, NEVER
        if not v & ATN:
            self.deaf = self.now
            yield IDLE
        eoi = bool(v & CLK)
        yield from self._at(ref + jt.ack)
        self._out(CLK)
        t_ack = self.now
        yield from self._at(self.now + jt.pulse)
        for t in jt.rx:
            if self.bus.changed(ref + t - lat - m, ref + t - lat + m, CLK | DATA):
                self._error(f"Jiffy: host changed the bus at the +{t:g}us sample")
        self._check_reads(
            ref, self.now, [(t_ack + m, NEVER)], [(t_ack + m, self.now - m)]
        )
        self.reads = None
        self.keep = NEVER
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
        if self.jact:
            yield from self._at(self.now + T_JTALK, deaf=True)
        if self.jload:
            yield from self._jtalk_load(chan)
            return
        n = len(chan.data)
        while chan.pos < n:
            extra = self.sector_delay if ch != 15 and chan.pos % BLOCK == 0 else 0
            eoi = chan.pos == n - 1
            if self.jact:
                yield from self._at(self.now + extra, deaf=True)
                yield from self._jsend(chan.data[chan.pos], eoi, SINGLE)
            elif not (yield from self._send(chan.data[chan.pos], eoi, extra)):
                return
            chan.pos += 1
        if ch == 15:
            self.status = OK

    def _jtalk_load(self, chan):
        """JiffyDOS LOAD: blocks of bytes without handshakes, each block
        ended by a CLK-held marker the host acknowledges."""
        yield _data_rel, NEVER
        chan.pos += 2 - chan.pos % BLOCK
        n = len(chan.data)
        while True:
            self._out(CLK)
            yield from self._at(self.now + T_JREADY, deaf=True)
            end = min(n, chan.pos - chan.pos % BLOCK + BLOCK)
            while chan.pos < end:
                final = chan.pos == end - 1
                yield from self._jsend(
                    chan.data[chan.pos], False, FINAL if final else MID
                )
                chan.pos += 1
            if chan.pos >= n:
                for mask in (ALL, DATA, ALL):
                    yield from self._at(self.now + T_JEOF, deaf=True)
                    self._out(mask)
                return
            yield from self._at(self.now + self.sector_delay, deaf=True)
            self.deaf = self.now + T_JREFILL
            yield _data_rel, self.deaf

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
            if b == 0x61 and self.talk and self.jiffy is not None:
                b, self.jload = 0x60, True
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
