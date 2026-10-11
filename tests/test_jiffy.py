"""JiffyDOS: the drive model against the reference host, and the 6502
library's timing margins against the drive model."""

import pytest

from kimdos import bench
from kimdos.host import JLOAD, JRX, JTX, BusTimeout, HostBitbang
from kimdos.iec import (
    ATN,
    BLOCK,
    CLK,
    DATA,
    JIFFY_AVR_EARLY,
    JIFFY_AVR_LATE,
    JIFFY_LPC,
    Bus,
    Drive,
)

TIMINGS = [JIFFY_LPC, JIFFY_AVR_EARLY, JIFFY_AVR_LATE]
ALLB = bytes(range(256))
PRG = b"\x00\x20" + ALLB * 3


def rig(files=None, host_kw=None, **kw):
    """A JiffyDOS host and drive on one bus."""
    d = Drive(dict({b"P": PRG} if files is None else files), **kw)
    return d, HostBitbang(Bus([d]), jiffy=True, **(host_kw or {}))


@pytest.mark.parametrize("latency", [0, 1])
@pytest.mark.parametrize("timing", TIMINGS)
def test_transfers(timing, latency):
    d, h = rig(jiffy=timing, latency=latency)
    assert h.load(b"P") == PRG
    h.save(b"NEW", ALLB)
    assert d.files[b"NEW"] == ALLB
    assert h.jload(b"P") == PRG
    h.open(8, 2, b"P")
    h.command(b"P\x62" + (300).to_bytes(4, "little"))
    assert h.status() == b"00, OK,00,00\r"
    assert h.read(8, 2, 5) == PRG[300:305]
    assert h.read(8, 2) == PRG[305:]
    h.close(8, 2)
    assert h.load(b"$").startswith(b"\x01\x04")
    h.listen(8, 0x6F)
    assert h.jact and d.jact
    h.unlisten()
    assert not d.errors


@pytest.mark.parametrize("size", [3, 4, BLOCK, BLOCK + 2, 2 * BLOCK, 2 * BLOCK + 1])
def test_load_mode_blocks(size):
    data = bytes(i * 13 & 0xFF for i in range(size))
    d, h = rig({b"F": data}, sector_delay=3000)
    assert h.jload(b"F") == data
    assert not d.errors


def test_short_and_empty():
    d, h = rig({b"E": b"", b"ONE": b"x"})
    assert h.load(b"ONE") == b"x"
    h.open(8, 0, b"E")
    with pytest.raises(BusTimeout, match="read timeout"):
        h.read(8, 0)
    h.open(8, 0, b"NOPE")
    with pytest.raises(BusTimeout, match="read timeout"):
        h.read(8, 0)
    assert h.status().startswith(b"62")
    assert not d.errors


def test_fallback_both_ways():
    d, h = rig(jiffy=None)
    assert h.load(b"P") == PRG and not h.jact
    assert not d.errors
    d = Drive({b"P": PRG})
    h = HostBitbang(Bus([d]))
    assert h.load(b"P") == PRG and not d.jact
    assert not d.errors


def test_listener_gone():
    d, h = rig()
    h.save(b"NEW", b"a")
    h.open(8, 1, b"NEW")
    h.listen(8, 0x61)
    with pytest.raises(BusTimeout, match="not acknowledged"):
        h.write(b"b")
    assert not d.errors


def test_atn_ends_a_byte():
    d, h = rig()
    h.listen(8, 0x6F)
    h.jsend(ord("I"))
    h._must(lambda v: v & DATA, 1000, "ready")  # pylint: disable=protected-access
    h.delay(10)
    h.set(release=CLK)
    h.delay(30)
    h.set(assert_=ATN | CLK)
    h.delay(200)
    h.bus.sync(h.t)
    assert d.cmd == b"I"
    assert not d.errors


def shifted(seq, i, by):
    """seq with element i moved by `by`."""
    return seq[:i] + (seq[i] + by,) + seq[i + 1 :]


@pytest.mark.parametrize(
    "attr,seq,i,by,err",
    [
        ("jrx", JRX, 1, -5, "off the windows"),
        ("jrx", JRX, 4, 5, "off the windows"),
        ("jrx", JRX, 0, -11, "before the drive was armed"),
        ("jtx", JTX, 2, -6, "changed the bus"),
        ("jtx", JTX, 4, 7, "changed the bus"),
        ("jtx", JTX, 7, -5, "off the windows"),
        ("jtx", JTX, 0, -10, "before the drive was armed"),
        ("jtx", JTX, 6, 9, "CLK released before"),
    ],
)
def test_host_off_schedule(attr, seq, i, by, err):
    d, h = rig()
    h.timeout = 20_000
    setattr(h, attr, shifted(seq, i, by))
    try:
        h.load(b"P")
        h.save(b"NEW", ALLB)
    except BusTimeout:
        pass
    assert any(err in e for e in d.errors), d.errors


@pytest.mark.parametrize(
    "i,by,err",
    [
        (2, -5, "off the windows"),
        (5, 6, "off the windows"),
        (6, -8, "off the windows"),
        (0, -13, "pulled DATA before the drive was armed"),
    ],
)
def test_load_mode_off_schedule(i, by, err):
    d, h = rig()
    h.timeout = 20_000
    h.jload_at = shifted(JLOAD, i, by)
    try:
        h.jload(b"P")
    except BusTimeout:
        pass
    assert any(err in e for e in d.errors), d.errors


def test_bit7_during_acknowledge():
    d, h = rig()
    h.set(release=DATA, assert_=ATN | CLK)
    h._must(lambda v: not v & DATA, 1000, "present")  # pylint: disable=protected-access
    h.delay(1000)
    h.set(release=CLK)
    h._must(lambda v: v & DATA, 1000, "ready")  # pylint: disable=protected-access
    h.set(assert_=CLK)
    for i in range(7):
        h.set(
            release=DATA if 0x28 >> i & 1 else 0, assert_=0 if 0x28 >> i & 1 else DATA
        )
        h.delay(20)
        h.set(release=CLK)
        h.delay(20)
        h.set(release=DATA, assert_=CLK)
    h.delay(250)
    h.set(release=CLK)
    h.delay(20)
    h.set(assert_=CLK)
    h.delay(200)
    h.bus.sync(h.t)
    assert any("during the JiffyDOS acknowledge" in e for e in d.errors)


@pytest.mark.parametrize("latency", [0, 1])
@pytest.mark.parametrize("name", list(bench.TIMINGS))
def test_library_margins(image, name, latency):
    assert bench.margin_ok(image, 3, jiffy=bench.TIMINGS[name], latency=latency)


def test_library_margin_limit(image):
    m = bench.max_margin(image, step=1)
    assert 3 <= m < 6
    assert not bench.margin_ok(image, m + 1)


@pytest.mark.parametrize("op", bench.OPS)
def test_library_throughput(image, op):
    std, jif = (bench.per_byte(image, op, jiffy=j) for j in (None, JIFFY_LPC))
    assert jif < std / 1.8


def test_report(image):
    rows, margins = bench.report(image, latencies=(1,))
    assert [r[0] for r in rows] == list(bench.OPS)
    assert all(jif < std for _, std, jif in rows)
    assert [(t, lat) for t, lat, _ in margins] == [(t, 1) for t in bench.TIMINGS]
    assert all(m >= 3 for _, _, m in margins)
