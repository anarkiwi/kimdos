"""Tests of the KIM-1 and serial bus drive oracle."""

from types import SimpleNamespace

import pytest

from kimdos.iec import (
    ALL,
    ATN,
    CLK,
    DATA,
    Bus,
    BusTimeout,
    Drive,
    HostBitbang,
    match,
    open_mode,
    parse_name,
)
from kimdos.sim import CYCLES, INPUT, MONITOR, RETURN, ROM_CALL, Kim, Port

PRG = bytes([0x00, 0x20]) + bytes(range(256)) * 3
FILES = {b"HELLO": PRG, b"HI": b"\x01\x04ab", b"WORLD": b"\x00\x30" + bytes(300)}


def rig(files=None, host_kw=None, **kw):
    """A bus with one drive and a host master."""
    d = Drive(dict(FILES if files is None else files), **kw)
    return d, HostBitbang(Bus([d]), **(host_kw or {}))


def basic_lines(img):
    """Parse a BASIC program image into (line number, text) pairs."""
    assert img[:2] == b"\x01\x04"
    addr, p, out = 0x0401, 2, []
    while link := int.from_bytes(img[p : p + 2], "little"):
        end = img.index(0, p + 4)
        assert link == addr + end + 1 - p
        out.append((int.from_bytes(img[p + 2 : p + 4], "little"), img[p + 4 : end]))
        addr, p = link, end + 1
    assert p + 2 == len(img)
    return out


@pytest.mark.parametrize(
    "kw",
    [
        {},
        {"latency": 50},
        {"latency": 150, "t_ne": 20},
        {"t_setup": 5, "t_valid": 5, "t_ready": 0},
        {"t_setup": 80, "t_valid": 90, "t_ready": 500, "sector_delay": 20000},
    ],
)
def test_load_parameters(kw):
    d, h = rig(host_kw={"t_valid": max(20, kw.get("latency", 0))}, **kw)
    assert h.load(b"0:HELLO") == PRG
    assert h.status() == b"00, OK,00,00\r"
    assert not d.errors


def test_wildcards_and_names():
    _, h = rig()
    assert h.load(b"H?") == FILES[b"HI"]
    assert h.load(b"W*") == FILES[b"WORLD"]
    assert h.load(b"HELLO,P,R") == PRG
    assert match(b"*", b"") and not match(b"HE", b"HELLO")
    assert parse_name(b"@0:X,P,W") == (True, b"X")


def test_directory():
    d, h = rig()
    lines = basic_lines(h.load(b"$"))
    assert lines[0] == (0, b'\x12"KIMDOS          " KD 2A')
    assert lines[1] == (4, b'   "HELLO"            PRG')
    assert [n for n, _ in lines[1:-1]] == [4, 1, 2]
    assert lines[-1] == (664 - 7, b"BLOCKS FREE.")
    assert [t for _, t in basic_lines(h.load(b"$0:W*"))][1:-1] == [
        b'   "WORLD"            PRG'
    ]
    assert len(basic_lines(d.directory(b"0"))) == 5
    assert not d.errors


def test_save_replace_exists():
    d, h = rig()
    h.save(b"0:NEW", b"\x00\x20abc")
    assert d.files[b"NEW"] == b"\x00\x20abc"
    with pytest.raises(BusTimeout):
        h.save(b"NEW", b"\x00\x20xyz")
    h.unlisten()
    assert h.status() == b"63,FILE EXISTS,00,00\r"
    assert d.files[b"NEW"] == b"\x00\x20abc"
    h.save(b"@0:NEW", b"\x00\x20xyz")
    assert h.status() == b"00, OK,00,00\r"
    assert h.load(b"NEW") == b"\x00\x20xyz"
    h.save(b"@:NEW", bytes(600))
    assert d.files[b"NEW"] == bytes(600)
    assert not d.errors


@pytest.mark.parametrize(
    "cmd,status,names",
    [
        (b"S0:H*", b"01, FILES SCRATCHED,02,00\r", [b"WORLD"]),
        (b"S:WORLD,HI\r", b"01, FILES SCRATCHED,02,00\r", [b"HELLO"]),
        (b"S:NONE", b"01, FILES SCRATCHED,00,00\r", [b"HELLO", b"HI", b"WORLD"]),
        (b"R:BYE=HI", b"00, OK,00,00\r", [b"HELLO", b"WORLD", b"BYE"]),
        (b"R0:BYE=0:NONE", b"62,FILE NOT FOUND,00,00\r", None),
        (b"R:HELLO=HI", b"63,FILE EXISTS,00,00\r", None),
        (b"I0", b"00, OK,00,00\r", None),
        (b"I", b"00, OK,00,00\r", None),
        (b"UI", b"73,KIMDOS SIM,00,00\r", None),
        (b"X", b"31,SYNTAX ERROR,00,00\r", None),
    ],
)
def test_commands(cmd, status, names):
    d, h = rig()
    h.command(cmd)
    assert h.status() == status
    assert h.status() == b"00, OK,00,00\r"
    assert list(d.files) == (names or list(FILES))
    assert not d.errors


def test_open_15_executes():
    d, h = rig()
    assert h.status() == b"73,KIMDOS SIM,00,00\r"
    h.open(8, 15, b"S:HI")
    assert b"HI" not in d.files
    h.open(8, 15, b"")
    h.close(8, 15)
    assert h.status() == b"01, FILES SCRATCHED,01,00\r"


@pytest.mark.parametrize("name", [b"NOPE", b"EMPTY"])
def test_no_data_times_out(name):
    d, h = rig({b"EMPTY": b""})
    h.open(8, 0, name)
    with pytest.raises(BusTimeout, match="read timeout"):
        h.read(8, 0)
    assert h.status().startswith(b"62" if name == b"NOPE" else b"00")
    with pytest.raises(BusTimeout):
        h.read(8, 1)
    assert not d.errors


def test_device_not_present():
    _, h = rig(present=False)
    with pytest.raises(BusTimeout, match="device not present"):
        h.load(b"HELLO")
    _, h = rig(device=9)
    with pytest.raises(BusTimeout, match="frame ack"):
        h.listen(8, 0xF0)


def test_two_drives():
    d8, d9 = Drive(dict(FILES)), Drive({b"NINE": b"\x00\x109"}, device=9, latency=30)
    h = HostBitbang(Bus([d8, d9]), t_valid=30)
    assert h.load(b"NINE", 9) == b"\x00\x109"
    assert h.load(b"HI", 8) == FILES[b"HI"]
    assert h.status(9) == b"00, OK,00,00\r"
    assert not d8.errors and not d9.errors


def test_partial_read_resumes_after_atn():
    d, h = rig()
    h.open(8, 0, b"HELLO")
    head = h.read(8, 0, limit=3)
    assert head + h.read(8, 0) == PRG
    h.close(8, 0)
    assert not d.errors


def test_atn_aborts_talker_mid_byte():
    d, h = rig(t_setup=50, t_valid=50)
    h.open(8, 0, b"HELLO")
    h.talk(8, 0x60)
    h.recv()
    h.wait(lambda v: not v & CLK, 1000)
    h.delay(120)
    h.untalk()
    assert h.read(8, 0)[:2] == PRG[1:3]
    assert not d.errors


def test_violations():
    d, h = rig(latency=40, host_kw={"t_valid": 10})
    h.command(b"I")
    assert any("< latency" in e for e in d.errors)
    d, h = rig()
    h.atn(0x28)
    h.send(0x6F, eoi=True)
    assert any("EOI under ATN" in e for e in d.errors)
    d, h = rig()
    h.open(8, 0, b"HI")
    h.talk(8, 0x60)
    h.recv(ack=False)
    h.delay(5000)
    h.bus.sync(h.t)
    assert any("frame ack timeout" in e for e in d.errors)


def test_data_change_during_valid_and_short_eoi_ack():
    d, h = rig()
    h.listen(8, 0x6F)
    h.set(release=CLK)
    h.wait(lambda v: v & DATA, 1000)
    h.delay(10)
    h.set(assert_=CLK)
    h.set(release=CLK)
    h.delay(10)
    h.set(assert_=DATA)
    h.delay(10)
    h.set(assert_=CLK)
    assert any("DATA changed" in e for e in d.errors)
    d, h = rig()
    h.open(8, 0, b"HI")
    h.talk(8, 0x60)
    for _ in range(3):
        h.recv()
    h.wait(lambda v: v & CLK, 1000)
    h.set(release=DATA)
    h.delay(210)
    h.set(assert_=DATA)
    h.delay(10)
    h.set(release=DATA)
    h.delay(300)
    h.bus.sync(h.t)
    assert any("too short" in e for e in d.errors)


def test_eoi_ack_timeout():
    d, h = rig()
    h.open(8, 0, b"HI")
    h.talk(8, 0x60)
    for _ in range(3):
        h.recv()
    h.wait(lambda v: v & CLK, 1000)
    h.set(release=DATA)
    h.delay(3000)
    h.bus.sync(h.t)
    assert any("EOI ack timeout" in e for e in d.errors)


def test_bus_history():
    bus = Bus(host=ALL)
    bus.set_host(ALL & ~ATN, 10)
    bus.set_host(ALL & ~ATN, 11)
    bus.set_host(ALL & ~CLK, 10)
    assert bus.host_at(5) == ALL and bus.host_at(10) == ALL & ~CLK
    assert bus.lines(20) == ALL & ~CLK


def test_port_levels():
    k = Kim(drives=[])
    assert k.bus.host == 0
    assert k.mem[0x1700] == 0x3F
    k.mem[0x1701] = 0x3F
    k.mem[0x1700] = 0x00
    assert k.bus.host == ALL and k.mem[0x1700] == 0xC0
    k.mem[0x1700] = 0x15
    assert k.bus.host == ATN | DATA and k.mem[0x1700] == 0x95
    k.mem[0x1701] = 0x08
    assert k.bus.host == ATN and k.mem[0x1700] == 0x37
    k.mem[0x1703] = 0xF0
    k.mem[0x1702] = 0x5A
    assert k.mem[0x1702] == 0x5F and k.mem[0x1703] == 0xF0
    assert k.mem[0x1710] == 0


def test_port_timer():
    cpu = SimpleNamespace(processorCycles=100)
    p = Port(Bus(), cpu)
    p.write(0x1705, 10)
    cpu.processorCycles = 100 + 3 * 8
    assert (p.read(0x1706), p.read(0x1707)) == (7, 0)
    cpu.processorCycles = 100 + 80 + 5
    assert (p.read(0x170E), p.read(0x170F)) == (0xFB, 0x80)
    assert Port(Bus()).now() == 0


ATN_POLL = bytes.fromhex("a9388d0117a9008d0017a200cad0fda9188d0017ad001730fb4c4f1c")


@pytest.mark.parametrize("latency", [0, 200])
def test_cpu_sees_atn_response(latency):
    k = Kim(ATN_POLL, drives=Drive(latency=latency))
    assert k.run(100_000) == MONITOR
    elapsed = k.cycles - k.bus.times[-1]
    assert latency <= elapsed <= latency + 15
    assert not k.drive.errors
    k = Kim(ATN_POLL, drives=Drive(present=False))
    assert k.run(5000) == CYCLES


TRAPS = bytes.fromhex("a94120a01e205a1e85108611202f1ea95c203b1e4c4f1c")


def test_traps():
    k = Kim(TRAPS)
    assert k.run() == INPUT and k.output == "A"
    k.type("Z")
    assert k.run() == MONITOR
    assert k.output == "AZ\r\n5C"
    assert k.read(0x10, 2) == b"Z\xa5"
    assert k.cycles > 6 * 8300
    k.write(0x300, bytes.fromhex("6901e8c860"))
    r = k.call(0x300, a=1, x=2, y=3, carry=True)
    assert (r.reason, r.a, r.x, r.y, r.carry) == (RETURN, 3, 3, 4, False)
    assert k.call(0x1800).reason == ROM_CALL
    assert k.drive is k.drives[0]


def test_ram_protect():
    k = Kim(bytes.fromhex("a9558d00208d00104c4f1c"), ram=[(0, 0x13FF)])
    assert k.run() == MONITOR
    assert k.read(0x2000) == b"\0" and k.read(0x1000) == b"\x55"


def test_listen_data_without_eoi_is_a_violation():
    d, h = rig()
    h.listen(8, 0x6F)
    h.send(ord("I"))
    h.unlisten()
    assert any("without EOI" in e for e in d.errors)


def seek(h, ch, off, n=4):
    """sd2iec P command: channel byte, then n bytes of little-endian offset."""
    h.command(b"P" + bytes([0x60 | ch]) + off.to_bytes(4, "little")[:n])
    return h.status()


def test_position():
    d, h = rig()
    h.open(8, 2, b"HELLO")
    assert seek(h, 2, 300) == b"00, OK,00,00\r"
    assert h.read(8, 2, 4) == PRG[300:304]
    assert seek(h, 2, 13, 1) == b"00, OK,00,00\r"
    assert h.read(8, 2) == PRG[13:]
    assert seek(h, 2, len(PRG) + 1).startswith(b"50,RECORD NOT PRESENT")
    with pytest.raises(BusTimeout):
        h.read(8, 2)
    assert seek(h, 2, len(PRG) - 1) == b"00, OK,00,00\r"
    assert h.read(8, 2) == PRG[-1:]
    assert seek(h, 3, 0).startswith(b"70,NO CHANNEL")
    h.command(b"P")
    assert h.status().startswith(b"70,")
    h.open(8, 4, b"$")
    h.open(8, 5, b"NEW,S,W")
    assert seek(h, 4, 0).startswith(b"31,")
    assert seek(h, 5, 0).startswith(b"31,")
    assert not d.errors


@pytest.mark.parametrize(
    "name,ch,mode",
    [
        (b"X", 0, (b"R", b"PRG")),
        (b"X,S,W", 0, (b"R", b"SEQ")),
        (b"X", 1, (b"W", b"PRG")),
        (b"X", 2, (b"R", b"SEQ")),
        (b"X,P,W", 2, (b"W", b"PRG")),
        (b"X,W,U", 3, (b"W", b"USR")),
        (b"X,A", 4, (b"A", b"SEQ")),
        (b"X,M,D", 4, (b"R", b"SEQ")),
        (b"X,,Z,W", 4, (b"R", b"SEQ")),
    ],
)
def test_open_mode(name, ch, mode):
    assert open_mode(name, ch) == mode


def test_write_modes():
    d, h = rig({})
    h.open(8, 3, b"A,S,W")
    h.listen(8, 0x63)
    h.write(b"abc")
    h.unlisten()
    h.open(8, 3, b"B,P,W")
    h.close(8, 3)
    assert d.files == {b"A": b"abc", b"B": b""}
    h.open(8, 3, b"A,S,W")
    assert h.status().startswith(b"63,")
    h.open(8, 4, b"A,A")
    h.listen(8, 0x64)
    h.write(b"de")
    h.unlisten()
    h.close(8, 4)
    assert d.files[b"A"] == b"abcde"
    h.open(8, 4, b"NOPE,A")
    assert h.status().startswith(b"62,")
    h.command(b"R:C=A")
    lines = basic_lines(h.load(b"$"))
    assert [t[-3:] for _, t in lines[1:-1]] == [b"PRG", b"SEQ"]
    h.open(8, 2, b"@0:C,P,W")
    h.close(8, 2)
    h.command(b"S:B")
    assert d.files == {b"C": b""} and d.types == {b"C": b"PRG"}
    assert not d.errors
