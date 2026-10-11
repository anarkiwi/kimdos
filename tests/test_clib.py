"""The llvm-mos C library, through c/test/kdtest.c on the simulated KIM-1."""

import random
import re

import pytest

from kimdos.iec import Drive
from kimdos.sim import MONITOR, Kim

ORG = 0x2000
DATA = bytes((i * 7 + 3) & 0xFF for i in range(600))
PROG = b"\x00\x60" + bytes((i * 5 + 1) & 0xFF for i in range(300))
MSG = b"HELLO,\rWORLD\0"
MONITOR_ZP = range(0xEF, 0x100)

EXPECTED = """\
ST=0049 73,KIMDOS SIM,00,00
OPEN=0000 R1=0064 R2=0258 R3=0000 SUM={sum_data:04X}
SEEK=0000 R4=0004 B=374C SEEK=0032 SEEK=0046
OPEN=0000 W=0007 W=0006
ST=0000 00, OK,00,00
RB=000D EQ=0001
CMD=0000 ST=0000 00, OK,00,00
DIR=0000
DATA,SEQ,0003
PROG,PRG,0002
NEW,SEQ,0001
DIR=0000
PROG,PRG,0002
LOAD=0000 AT=612C SUM={sum_prog:04X} LOAD=0000 AT=012C
SAVE=0000 SAVE=0080 ST=003F 63,FILE EXISTS,00,00
LOAD=0002 ST=003E 62,FILE NOT FOUND,00,00
CHKIN=0000 GETB=FFFF
DEV9=00FF \xe1KEY=0061
BYE
"""

TIMINGS = [
    {},
    {"latency": 40, "t_ready": 150},
    {"latency": 50, "t_setup": 70, "t_valid": 70, "sector_delay": 20000},
    {"t_ne": 5, "t_ack": 5, "t_ready": 0},
]


def checksum(data):
    """The rotate-and-xor sum kdtest prints."""
    s = 0
    for b in data:
        s = ((s << 1 | s >> 15) & 0xFFFF) ^ b
    return s


def run(image, **kw):
    """Run kdtest against a drive holding DATA and PROG, with garbage in RAM."""
    drive = Drive({b"DATA": DATA, b"PROG": PROG}, **kw)
    drive.types[b"DATA"] = b"SEQ"
    kim = Kim(drives=drive)
    rng = random.Random(len(image))
    kim.write(0, rng.randbytes(0xFF00))
    kim.write(ORG, image)
    kim.mpu.pc = ORG
    kim.type(b"\xe1")
    zp = kim.read(MONITOR_ZP.start, len(MONITOR_ZP))
    assert kim.run(500_000_000) == MONITOR
    assert kim.read(MONITOR_ZP.start, len(MONITOR_ZP)) == zp
    head, out = re.sub(r" *\r\n", "\n", kim.output).split("\n", 1)
    end = int(re.fullmatch(r"END=([0-9A-F]{4})", head)[1], 16)
    return out, end, drive


@pytest.mark.parametrize("timing", TIMINGS)
def test_kdtest(kdtest, timing):
    out, _, drive = run(kdtest, **timing)
    assert not drive.errors
    assert out == EXPECTED.format(sum_data=checksum(DATA), sum_prog=checksum(PROG[2:]))
    assert drive.files[b"NEW"] == MSG
    assert drive.files[b"COPY"][2:] == PROG[2:18]
    assert b"OUT" not in drive.files


def test_kim_end(kdtest):
    _, end, _ = run(kdtest)
    assert end & 0xFF == 0
    assert 0x400 <= end - (ORG + len(kdtest)) < 0x800


def test_no_device(kdtest):
    out, _, drive = run(kdtest, present=False)
    assert not drive.errors
    fields = dict(re.findall(r"(\w+)=([0-9A-F]{4})", out))
    assert fields["ST"] == "00FF"
    assert fields["OPEN"] == fields["CMD"] == fields["DIR"] == "0080"
    assert fields["R1"] == fields["W"] == fields["RB"] == "0000"
    assert fields["LOAD"] == fields["SAVE"] == fields["CHKIN"] == "0080"
    assert fields["GETB"] == "FFFF"
    assert out.endswith("BYE\n")
