"""The 6502 library and shell, run on the simulated KIM-1 against a drive."""

import random

import pytest

from kimdos.iec import Drive
from kimdos.sim import MONITOR, RETURN, Kim

PRG = b"\x00\x03" + bytes(range(256)) * 3
TIMINGS = [
    {},
    {"latency": 40, "t_ready": 150},
    {"latency": 50, "t_setup": 70, "t_valid": 70, "sector_delay": 20000},
    {"t_ne": 5, "t_ack": 5, "t_ready": 0},
]


def machine(image, files=None, **kw):
    """A simulated KIM-1 running the image, with one drive."""
    drive = Drive(files=dict(files or {}), **kw)
    kim = Kim(image.binary, image.org, drives=drive)
    bss = random.Random(image.org).randbytes(image["__BSS_SIZE__"])
    kim.write(image["__BSS_RUN__"], bss)
    return kim, drive


def shell(image, *lines, files=None, **kw):
    """Type lines into the shell; return each reply and the drive."""
    kim, drive = machine(image, files, **kw)
    kim.mpu.pc = image.org
    kim.type("".join(line + "\r" for line in lines) + "Q\r")
    assert kim.run(200_000_000) == MONITOR
    assert not drive.errors
    replies = kim.output.split("\r\n>")[1:]
    return [r.split("\r\n", 1)[1] if "\r\n" in r else "" for r in replies[:-1]], drive


def setnam(kim, image, name):
    """Name a file through dos_setnam."""
    kim.write(0x0F00, name)
    kim.call(image["dos_setnam"], a=len(name), x=0x00, y=0x0F)


def word(kim, addr):
    """Little-endian word at addr."""
    lo, hi = kim.read(addr, 2)
    return lo | hi << 8


@pytest.mark.parametrize("timing", TIMINGS)
def test_shell_round_trip(image, timing):
    out, drive = shell(
        image,
        "L HELLO",
        "V HELLO",
        'S "NEW 1",0300,04FF',
        'V "NEW 1"',
        "$",
        "@",
        files={b"HELLO": PRG},
        **timing,
    )
    assert out[0] == "$0300-$05FF"
    assert out[1] == "$0300-$05FF"
    assert out[2] == "00, OK,00,00"
    assert out[3] == "$0300-$04FF"
    assert drive.files[b"NEW 1"] == PRG[:0x202]
    assert '"HELLO"' in out[4] and "BLOCKS FREE." in out[4]
    assert out[5].startswith("00,")


def test_load_relocates_and_points_monitor(image):
    out, _ = shell(image, "l hello,4000", files={b"HELLO": PRG})
    assert out[0] == "$4000-$42FF"


def test_verify_mismatch_and_missing(image):
    out, _ = shell(
        image,
        "L HELLO",
        "V OTHER",
        "V NOPE",
        files={b"HELLO": PRG, b"OTHER": PRG[:10] + b"\xff" + PRG[11:]},
    )
    assert out[1] == "$0300-$05FF ?VERIFY"
    assert out[2] == "62,FILE NOT FOUND,00,00"


def test_save_existing_reports_drive_error(image):
    out, drive = shell(
        image, "S HELLO,0300,0301", "S @0:HELLO,0300,0301", files={b"HELLO": PRG}
    )
    assert out[0].startswith("63,")
    assert out[1].startswith("00,")
    assert len(drive.files[b"HELLO"]) == 4


def test_dos_commands_and_device(image):
    out, drive = shell(
        image,
        "@S:HELLO",
        "@BOGUS",
        "#",
        "#9",
        "@",
        "#30",
        "#3",
        "#X",
        "#123",
        files={b"HELLO": PRG},
    )
    assert out[0].startswith("01,")
    assert out[1].startswith("31,")
    assert out[2] == "8"
    assert out[3] == "9"
    assert out[4] == "?DEVICE NOT PRESENT"
    assert out[5] == "30"
    assert out[6:9] == ["?SYNTAX"] * 3
    assert b"HELLO" not in drive.files


def test_syntax_and_help(image):
    out, _ = shell(image, "", "X", "L", "S A", "S A,1", "S A,1,G", "?", "L A,")
    assert out[0] == ""
    assert out[1:7] == ["?SYNTAX"] * 5 + [out[6]]
    assert "DIRECTORY" in out[6]
    assert out[7] == "?SYNTAX"


def test_line_editing(image):
    out, _ = shell(image, "#XX\x08\x7f9\x01", "$", files={})
    assert out[0] == "9"
    assert out[1] == "?DEVICE NOT PRESENT"


def test_no_device(image):
    out, _ = shell(image, "$", "L A", "S A,0,1", present=False)
    assert out == ["?DEVICE NOT PRESENT"] * 3


def test_dir_pattern_and_lowercase(image):
    out, _ = shell(image, "$0:B*", files={b"ALPHA": PRG, b"BETA\xc1": PRG})
    assert '"BETAa"' in out[0] and "ALPHA" not in out[0]


@pytest.mark.parametrize("size", [0, 1, 253, 254, 255, 508, 1000])
def test_load_sizes(image, size):
    data = bytes((i * 7 + 3) & 0xFF for i in range(size))
    kim, drive = machine(image, {b"F": b"\x00\x40" + data})
    setnam(kim, image, b"F")
    res = kim.call(image["dos_load"], a=0)
    assert res.reason == RETURN and not res.carry
    assert kim.read(0x4000, size) == data
    assert (word(kim, image["dos_beg"]), word(kim, image["dos_end"])) == (
        0x4000,
        0x4000 + size,
    )
    assert not drive.errors


def test_read_in_pieces(image):
    data = bytes(range(256)) * 2
    kim, _ = machine(image, {b"F": data})
    setnam(kim, image, b"F")
    assert not kim.call(image["dos_open"], a=2).carry
    for start, end in ((0x5000, 0x5100), (0x5100, 0x5300)):
        kim.write(image["dos_beg"], bytes([start & 0xFF, start >> 8]))
        kim.write(image["dos_end"], bytes([end & 0xFF, end >> 8]))
        assert not kim.call(image["dos_read"], a=2).carry
    assert kim.read(0x5000, 512) == data
    assert word(kim, image["dos_beg"]) == 0x5200
    kim.call(image["dos_close"], a=2)


def test_write_channel_and_status(image):
    kim, drive = machine(image, {})
    kim.write(0x6000, b"payload")
    setnam(kim, image, b"OUT,P,W")
    kim.call(image["dos_open"], a=1)
    kim.write(image["dos_beg"], b"\x00\x60\x07\x60")
    assert not kim.call(image["dos_write"], a=1).carry
    kim.call(image["dos_close"], a=1)
    assert drive.files[b"OUT"] == b"payload"
    res = kim.call(image["dos_status"])
    assert (res.a, res.carry) == (0, False)
    setnam(kim, image, b"XYZZY")
    kim.call(image["dos_cmd"])
    res = kim.call(image["dos_status"])
    assert (res.a, res.carry) == (31, True)
    assert kim.read(image["dos_errbuf"], 3) == b"31,"


def test_status_without_device(image):
    kim, _ = machine(image, present=False)
    res = kim.call(image["dos_status"])
    assert (res.a, res.carry) == (0xFF, True)
    setnam(kim, image, b"X")
    assert kim.call(image["dos_save"]).carry
    assert kim.call(image["dos_read"], a=2).carry
    assert kim.call(image["dos_write"], a=2).carry
    kim.call(image["dos_cmd"])


def test_leaves_zero_page_and_spare_port_bits(image):
    kim, _ = machine(image, {b"F": PRG})
    zp = bytes((i * 13) & 0xFF for i in range(256))
    kim.write(0, zp)
    kim.mem[0x1701] = 0x07
    kim.mem[0x1700] = 0x05
    setnam(kim, image, b"F")
    kim.call(image["dos_load"], a=0)
    assert kim.read(0, 256) == zp
    assert kim.read(0x1701)[0] & 7 == 7
    assert kim.read(0x1700)[0] & 7 == 5


def test_decimal_mode_caller(image):
    kim, drive = machine(image, {b"F": PRG})
    setnam(kim, image, b"F")
    kim.mpu.p |= 0x08
    res = kim.call(image["dos_load"], a=0)
    assert not res.carry and res.p & 0x08
    assert kim.read(0x0300, 0x300) == PRG[2:]
    assert not drive.errors


def test_keypad_load_and_save(image):
    kim, drive = machine(image, {b"3A": PRG})
    kim.write(0x17F9, b"\x3a")
    kim.mpu.pc = image.org + 3
    assert kim.run(50_000_000) == MONITOR
    assert word(kim, 0xFA) == 0x0300
    kim.write(0x17F5, b"\x00\x03\x10\x03")
    kim.write(0x17F9, b"\xc5")
    kim.mpu.pc = image.org + 6
    assert kim.run(50_000_000) == MONITOR
    assert drive.files[b"C5"] == PRG[:18]
    assert word(kim, 0xFA) == 0x0300
    kim.write(0x17F9, b"\x01")
    kim.mpu.pc = image.org + 3
    assert kim.run(50_000_000) == MONITOR
    assert word(kim, 0xFA) == 0xFFFF


def test_keypad_save_without_device(image):
    kim, _ = machine(image, present=False)
    kim.mpu.pc = image.org + 6
    assert kim.run(50_000_000) == MONITOR
    assert word(kim, 0xFA) == 0xFFFF


def test_jump_table(image):
    kim, _ = machine(image)
    table = kim.read(image.org, 69)
    for i in range(0, 69, 3):
        assert table[i] == 0x4C
    names = ["dos_dev", "iec_st", "dos_beg", "dos_end", "dos_errbuf"]
    for i, name in enumerate(names):
        assert word(kim, image.org + 69 + 2 * i) == image[name]
