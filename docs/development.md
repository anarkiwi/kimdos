# Development

```sh
sudo apt-get install cc65
pip install -e ".[dev]"
make ORG=2000
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
| `src/kimdos/` | build helper, simulator, board driver, CLI |

## The simulator

`kimdos.sim.Kim` runs the image on py65 with the monitor's `GETCH`,
`OUTCH` and `START` trapped, and a 6530 at $1700 wired to the bus as the
adapter is. `kimdos.iec.Drive` is an independent model of a drive written from
the bus protocol: files, directory, status channel, DOS commands.

The drive can be made slower or less forgiving: `latency` delays its view of
the host's lines, `t_ready`, `t_setup`, `t_valid`, `t_ne` and `t_ack` stretch
its own timing, and `sector_delay` stalls every 254 bytes. It records
protocol violations in `drive.errors`, which every test checks is empty.

Traps clobber X and Y, as the real monitor may, so code that relies on them
surviving fails in the tests.

## On a board

`kimdos board --port /dev/ttyUSB0 --install <commands>` loads the image with
the monitor, starts the shell and runs each command, printing the replies.
The board must be in TTY mode with RS pressed beforehand.
