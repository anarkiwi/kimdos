"""Throughput and JiffyDOS timing margins of the 6502 library, simulated."""

from tqdm import tqdm

from .iec import JIFFY_AVR_EARLY, JIFFY_AVR_LATE, JIFFY_LPC, Drive
from .sim import RETURN, Kim

TIMINGS = {"lpc": JIFFY_LPC, "avr-early": JIFFY_AVR_EARLY, "avr-late": JIFFY_AVR_LATE}
BUF = 0x4000
NAME = 0x3F00
SIZES = (1016, 2032)
OPS = ("read", "write", "load")


def _kim(image, files, **kw):
    kim = Kim(image.binary, image.org, drives=Drive(files=files, **kw))
    return kim, kim.drive


def _call(kim, image, name, **kw):
    r = kim.call(image[name], max_cycles=100_000_000, **kw)
    assert r.reason == RETURN, name
    return r


def _setnam(kim, image, name):
    kim.write(NAME, name)
    _call(kim, image, "dos_setnam", a=len(name), x=NAME & 0xFF, y=NAME >> 8)


def _range(kim, image, beg, end):
    kim.write(image["dos_beg"], beg.to_bytes(2, "little") + end.to_bytes(2, "little"))


def op_cycles(image, op, n, **kw):
    """CPU cycles for one library operation moving n bytes: dos_read of an
    open file, dos_write to one, or a whole dos_load (open, transfer, close)."""
    data = bytes(i * 7 & 0xFF for i in range(n))
    kim, drive = _kim(image, {b"F": b"\x00\x40" + data}, **kw)
    if op == "load":
        _setnam(kim, image, b"F")
        c = _call(kim, image, "dos_load").cycles
        assert kim.read(BUF, n) == data
    else:
        _setnam(kim, image, b"F" if op == "read" else b"G,S,W")
        _call(kim, image, "dos_open", a=2)
        if op == "write":
            kim.write(BUF, data)
        _range(kim, image, BUF, BUF + n + 2 if op == "read" else BUF + n)
        c = _call(kim, image, "dos_" + op, a=2).cycles
        _call(kim, image, "dos_close", a=2)
        got = kim.read(BUF, n + 2)[2:] if op == "read" else drive.files[b"G"]
        assert got == data, op
    assert not drive.errors, drive.errors
    return c


def per_byte(image, op, **kw):
    """Cycles per byte of op, fixed costs cancelled over two sizes."""
    lo, hi = (op_cycles(image, op, n, **kw) for n in SIZES)
    return (hi - lo) / (SIZES[1] - SIZES[0])


def margin_ok(image, margin, **kw):
    """Whether a load, a save and a status read stay margin us clear of
    every device edge and sample point."""
    data = bytes(range(256)) * 2
    kim, drive = _kim(image, {b"F": b"\x00\x40" + data}, margin=margin, **kw)
    _setnam(kim, image, b"F")
    _call(kim, image, "dos_load")
    _setnam(kim, image, b"G")
    _range(kim, image, BUF, BUF + len(data))
    _call(kim, image, "dos_save")
    _call(kim, image, "dos_status")
    return not drive.errors and drive.files.get(b"G", b"")[2:] == data


def max_margin(image, step=0.25, **kw):
    """Largest margin, in steps of step us, at which margin_ok holds."""
    m = 0
    while margin_ok(image, m + step, **kw):
        m += step
    return m


def report(image, latencies=(0, 1, 2)):
    """Throughput rows (op, standard, Jiffy) and margin rows (timing,
    latency, margin), with progress bars."""
    rows = []
    for op in tqdm(OPS, desc="throughput"):
        rows.append((op, per_byte(image, op, jiffy=None), per_byte(image, op)))
    cases = [(t, lat) for t in TIMINGS for lat in latencies]
    margins = [
        (t, lat, max_margin(image, jiffy=TIMINGS[t], latency=lat))
        for t, lat in tqdm(cases, desc="margins")
    ]
    return rows, margins
