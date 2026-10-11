"""kimdos: build, simulate and drive the KIMDOS shell."""

import argparse
import sys
from pathlib import Path

from . import bench
from .build import build
from .iec import Drive
from .sim import INPUT, Kim


def hexaddr(text):
    """Parse a hex address argument."""
    return int(text, 16)


def read_dir(path):
    """Files of a host directory as a drive's {PETSCII name: contents}."""
    return {
        p.stem.upper().encode(): p.read_bytes()
        for p in sorted(Path(path).glob("*.prg"))
    }


def write_dir(path, files):
    """Store a drive's files back to a host directory as .prg files."""
    for name, data in files.items():
        (Path(path) / (name.decode("latin-1").lower() + ".prg")).write_bytes(data)


def cmd_build(args):
    """Assemble and link, and print the tape image path."""
    image = build(args.org)
    print(image.ptp)


def cmd_sim(args, stdin=sys.stdin, stdout=sys.stdout):
    """Run the shell interactively on a simulated board and drive."""
    image = build(args.org)
    files = read_dir(args.dir) if args.dir else {}
    drive = Drive(files=files, jiffy=None if args.no_jiffy else bench.TIMINGS["lpc"])
    kim = Kim(image.binary, image.org, drives=drive)
    kim.mpu.pc = image.org
    shown = 0
    while True:
        reason = kim.run(1_000_000_000)
        stdout.write(kim.output[shown:])
        stdout.flush()
        shown = len(kim.output)
        line = stdin.readline() if reason == INPUT else ""
        if not line:
            break
        kim.type(line.rstrip("\n") + "\r")
    if args.dir:
        write_dir(args.dir, kim.drive.files)


def cmd_bench(args):
    """Print cycles per byte, standard and JiffyDOS, and Jiffy timing margins."""
    rows, margins = bench.report(build(args.org))
    print("| | Standard | JiffyDOS |\n| --- | --- | --- |")
    for op, std, jif in rows:
        print("| %s | %.0f | %.0f |" % (op, std, jif))
    print("\n| Device timing | Latency, us | Margin, us |\n| --- | --- | --- |")
    for timing, lat, m in margins:
        print("| %s | %d | %.2f |" % (timing, lat, m))


def cmd_board(args):  # pragma: no cover - needs a board on a serial line
    """Send shell commands to a board, installing the image first if asked."""
    from .board import Board  # pylint: disable=import-outside-toplevel

    board = Board(args.port, args.baud, trace=args.trace)
    if args.install:
        board.install(build(args.org).ptp.read_bytes(), args.org)
    for line in args.commands:
        print(">%s\n%s" % (line, board.command(line, args.timeout)))
    board.close()


def build_parser():
    """Command line parser."""
    parser = argparse.ArgumentParser(prog="kimdos", description=__doc__)
    parser.add_argument("--org", type=hexaddr, default=0x2000, help="load address")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build", help="assemble and link the image").set_defaults(
        func=cmd_build
    )
    sim = sub.add_parser("sim", help="run the shell on a simulated KIM-1")
    sim.add_argument("--dir", help="host directory of .prg files to serve")
    sim.add_argument("--no-jiffy", action="store_true", help="a drive without JiffyDOS")
    sim.set_defaults(func=cmd_sim)
    sub.add_parser(
        "bench", help="simulated throughput and JiffyDOS timing margins"
    ).set_defaults(func=cmd_bench)
    board = sub.add_parser("board", help="run shell commands on a board")
    board.add_argument("--port", required=True)
    board.add_argument("--baud", type=int, default=1200)
    board.add_argument("--install", action="store_true", help="load the image first")
    board.add_argument("--timeout", type=float, default=120)
    board.add_argument("--trace", action="store_true")
    board.add_argument("commands", nargs="*")
    board.set_defaults(func=cmd_board)
    return parser


def main(argv=None):
    """Entry point."""
    args = build_parser().parse_args(argv)
    args.func(args)
