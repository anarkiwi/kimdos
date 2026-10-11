# Development

```sh
sudo apt-get install cc65
pip install -e ".[dev]"
make ORG=2000
make clib                       # llvm-mos, in docker
pytest                          # xdist, coverage
black src tests
pylint src/kimdos tests
```

## Layout

| Path | |
| --- | --- |
| `asm/lib/iec.s` | bus primitives |
| `asm/lib/dos.s` | file operations |
| `asm/lib/con.s` | TTY output helpers |
| `asm/app/shell.s` | the resident image: jump table, keypad entries, shell |
| `asm/include/kimdos.inc` | the library interface |
| `asm/cfg/ram.cfg` | ld65 layout for a RAM image at `__ORG__` |
| `c/include/kimdos.h` | the C library interface |
| `c/src/` | the C library: `iec.s` bus, `dos.c` files, `dir.c` directory, `con.s` TTY |
| `c/kim1/` | llvm-mos KIM-1 platform: `link.ld`, `crt.s` |
| `c/test/kdtest.c` | C library exerciser run by `tests/test_clib.py` |
| `c/Dockerfile` | pins the llvm-mos toolchain image |
| `src/kimdos/` | build helper, simulator, board driver, CLI |

## The simulator

`kimdos.sim.Kim` runs the image on py65 with the monitor's `GETCH`,
`OUTCH` and `START` trapped, and a 6530 at $1700 wired to the bus as the
adapter is. `kimdos.iec.Drive` is an independent model of a drive written from
the bus protocol: files, directory, status channel, DOS commands, and the
sd2iec behaviour the C library relies on: `,S,W`/`,P,W`/`,A` open suffixes on
any channel, `@0:` replace, and the `P` (position) command on open files.

The drive can be made slower or less forgiving: `latency` delays its view of
the host's lines, `t_ready`, `t_setup`, `t_valid`, `t_ne` and `t_ack` stretch
its own timing, and `sector_delay` stalls every 254 bytes. It records
protocol violations in `drive.errors`, which every test checks is empty.

The drive speaks JiffyDOS by default with sd2iec's LPC17xx timing; `jiffy`
takes `JIFFY_AVR_EARLY` or `JIFFY_AVR_LATE` for the AVR build at either end
of its polling phase, or `None` for a drive without it. In Jiffy transfers
it also checks that the host reads and drives the bus at least `margin` us
(default 2) away from its own edges and sample points, and it ignores ATN
where sd2iec does. `kimdos.host.HostBitbang` is a scripted host for the
model, standard or Jiffy (`jiffy=True`), with the 6502 library's schedules.

Traps clobber X and Y, as the real monitor may, so code that relies on them
surviving fails in the tests.

## Throughput and margins

`kimdos bench` (`kimdos.bench`) runs the library on the simulator and
prints cycles per byte, with fixed costs cancelled over two file sizes, for
`dos_read` of an open file, `dos_write` and `dos_load` (1 MHz: cycles are
microseconds), then the largest margin each device timing leaves at a
latency of 0-2 us:

| | Standard | JiffyDOS |
| --- | --- | --- |
| read | 508 | 259 |
| write | 1339 | 370 |
| load | 508 | 114 |

| Device timing | 0 us | 1 us | 2 us |
| --- | --- | --- | --- |
| sd2iec LPC17xx | 4.00 | 4.25 | 4.00 |
| sd2iec AVR, early phase | 3.75 | 4.50 | 3.50 |
| sd2iec AVR, late phase | 4.50 | 4.00 | 3.00 |

`tests/test_jiffy.py` requires 3 us at latencies 0 and 1 us for every
timing. A Jiffy read pays a handshake and the call path (`dos_getb`,
`iec_acptr`) per byte; load uses LOAD mode, one byte per 114 cycles with no
handshake.

## On a board

`kimdos board --port /dev/ttyUSB0 --install <commands>` loads the image with
the monitor, starts the shell and runs each command, printing the replies.
The board must be in TTY mode with RS pressed beforehand.

## Releases

`.github/workflows/release.yml` publishes to PyPI by trusted publishing (no
token): PyPI project `kimdos`, owner `anarkiwi`, repository `kimdos`, workflow
`release.yml`, environment `pypi`.

1. Bump `version` in `pyproject.toml` and merge.
2. Publish a GitHub release tagged `v<version>`.

The workflow checks the tag matches the version, publishes the wheel and
sdist to PyPI, and attaches to the release the shell images
(`kimdos-{2000,0400,C000}.{bin,ptp,lbl}`), `libkimdos.a`, `kimdos.h` and a
source tarball of the C library. Run from `workflow_dispatch` it is a dry run:
it builds everything and uploads it as workflow artifacts only.
