# kimdos

Commodore serial bus (IEC) disk access for the KIM-1, PAL-1/PAL-II and other
replicas: a 6502 library, and a shell built on it, that load and save CBM DOS
files on a 1541, an SD2IEC/uIEC or anything else that speaks the bus. Written
from the protocol, not from Commodore's code.

The library uses no zero page, preserves the user port's spare bits, and links
anywhere with ld65. The shell runs over the monitor's TTY:

```
KIMDOS
>S PROG,2000,290D
00, OK,00,00
>L PROG,4000
$4000-$490D
>$
1 "                " 32 2A
10   "PROG"             PRG
65535 BLOCKS FREE.
>S PROG,2000,2001
63,FILE EXISTS,00,00
```

## Build and install

Needs cc65 and Python 3.11+.

```sh
pip install -e .
make ORG=2000                     # build/kimdos-2000.{bin,ptp,lbl,map}, build/kimdos.lib
kimtape load --port /dev/ttyUSB0 build/kimdos-2000.ptp --go 2000
```

`ORG` is the load address; the image needs about 2.5K of RAM there.

## Shell

| Command | |
| --- | --- |
| `$[pattern]` | directory, e.g. `$`, `$0:A*` |
| `@` | drive status |
| `@command` | DOS command, e.g. `@S:OLD`, `@R:NEW=OLD`, `@CD:GAMES` |
| `L name[,addr]` | load, to the file's own address or to `addr` |
| `V name[,addr]` | verify against memory |
| `S name,start,end` | save `start`-`end` inclusive; `@0:name` replaces |
| `#[device]` | show or set the device number (decimal, default 8) |
| `Q` | return to the monitor; `G` then runs what was loaded |

Names may be quoted. From the keypad, put the KIM tape ID in $17F9 and run
`ORG+3` to load the file named by its two hex digits, or set $17F5-$17F8 as
for a tape save and run `ORG+6` to save.

## Simulator

```sh
kimdos sim --dir ./disk           # the shell against .prg files in ./disk
kimdos board --port /dev/ttyUSB0 --install '$' '@'
```

## Documentation

- [docs/hardware.md](docs/hardware.md) — the adapter and its wiring
- [docs/library.md](docs/library.md) — linking the library into a program, the API
- [docs/protocol.md](docs/protocol.md) — the bus protocol as implemented
- [docs/development.md](docs/development.md) — tests and the simulator
