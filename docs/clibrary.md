# C library

`src/kimdos/c/` is KIMDOS for [llvm-mos](https://llvm-mos.org) C programs,
with a KIM-1 platform for the compiler. The Python package ships it:
`python -m kimdos.clib` prints the installed directory (`include/`, `src/`,
`kim1/`) and `python -m kimdos.clib --sources` the files to compile with a
program. The bus primitives in `src/kimdos/c/src/iec.s` are
`asm/lib/iec.s` instruction for instruction; the DOS layer is C with the same
bus traffic as `asm/lib/dos.s`.

```sh
make clib       # build/c/libkimdos.a, build/c/kdtest.bin and kdtest.elf
```

The toolchain runs from the image pinned in `src/kimdos/c/Dockerfile`; override
`MOS_IMAGE`, or `MOS_CC`/`MOS_AR` for a local install. The repository must be
under a path docker can bind-mount at the same place.

## Linking

Compile these with the program, or link `build/c/libkimdos.a` (paths under
the C directory):

| Source | |
| --- | --- |
| `src/iec.s` | bus primitives |
| `src/dos.c` | files, commands, status, load and save (needs `iec.s`) |
| `src/dir.c` | directory reader (needs `dos.c`) |
| `src/con.s` | console over the monitor's TTY |
| `kim1/crt.s` | start-up and `_Exit` for the KIM-1 platform |

```sh
C=$(python -m kimdos.clib)
mos-common-clang -Os -flto -I $C/include -T $C/kim1/link.ld -o prog prog.c \
    $(python -m kimdos.clib --sources)
```

This writes `prog`, the raw image to load at $2000, and `prog.elf`.
`libkimdos.a` holds LLVM bitcode from `-flto`, so link it with the same
llvm-mos release.

## KIM-1 platform

`kim1/link.ld`:

| Range | |
| --- | --- |
| $00-$1F | compiler imaginary registers `__rc0`-`__rc31` |
| $20-$EE | compiler zero page |
| $EF-$FF | KIM-1 monitor, untouched |
| $2000- | image: `_start`, code, read-only data, data, BSS |
| `__kim_end`-$400 - `__kim_end` | soft stack, growing down from `__kim_end` |
| `__kim_end` - $FEFF | free |

`__kim_end` is page aligned, at least 1K past the end of BSS. A program reaches
it as `extern char __kim_end[];`. `malloc`'s heap starts at the end of BSS,
where the stack is, so a program that uses `malloc` needs its own link
script; the rest manage `__kim_end`-$FEFF themselves.

`crt.s` clears decimal mode at start-up; `exit` and a return from `main` jump
to the monitor at $1C4F. Data is initialised by loading the image, not
copied at start-up, so a program run twice starts with the first run's
initialised variables. BSS is zeroed each run.

## ABI

The llvm-mos calling convention: the first two 8-bit arguments in A and X,
pointers and the rest in `__rc2` upwards; 8-bit results in A, 16-bit in A
(low) and X (high). A, X and Y are caller-saved. The assembly routines are
declared `leaf` (they never call back into C) so LTO can allocate the
callers' frames statically.

The bus primitives preserve X and Y, mask interrupts while they drive the
bus, clear decimal mode for themselves and restore the caller's flags. They
use no zero page. `kd_putc` and `kd_getc` call the monitor's `OUTCH` and
`GETCH`, which clobber X, Y and the monitor's own zero page. `kd_puts` walks
its string through `__rc2`/`__rc3`.

## API

`include/kimdos.h`. `iec_st` and the `ST_*` bits are as in
[library.md](library.md#status); every DOS call clears `iec_st` when it
starts the bus traffic.

| Call | Returns |
| --- | --- |
| `kd_open(ch, name, len)` | OPEN with the name; `iec_st` |
| `kd_close(ch)` | |
| `kd_chkin(ch)` | TALK the channel; follow with `kd_getb`, end with `iec_untlk`; `iec_st` |
| `kd_chkout(ch)` | LISTEN the channel; follow with `iec_ciout`, end with `iec_unlsn`; `iec_st` |
| `kd_getb()` | next byte, or -1 once the byte with EOI has been read or the talker sent nothing |
| `kd_read(ch, buf, n)` | bytes read, up to `n`; call again to continue |
| `kd_write(ch, buf, n)` | bytes written; stops at the first bus error |
| `kd_cmd(cmd, len)` | sends `len` bytes on channel 15; `iec_st` |
| `kd_status(buf)` | the code, with the text (48 bytes, CR dropped) in `buf`; $FF if no device |
| `kd_seek(ch, offset)` | sd2iec `P`: positions an open file; the status code |
| `kd_dir_open(pattern, len)` | opens `$pattern` on channel 0; `iec_st` without `ST_EOI` |
| `kd_dir_next(&e)` | 1 with the next entry, 0 at `BLOCKS FREE.` or the end |
| `kd_dir_close()` | closes channel 0 |
| `kd_load(name, len, addr, &end)` | channel 0, to `addr` or the file's own address; `iec_st` without `ST_EOI` |
| `kd_save(name, len, beg, end)` | channel 1, a PRG file with load address `beg`; `iec_st` |
| `kd_putc`, `kd_getc`, `kd_puts` | console |
| `iec_jload(addr)` | after TALK and secondary 0x61 to a JiffyDOS device: the rest of the file to `addr` up; one past the end |

`kd_read`, `kd_dir_next` and the rest end each transfer with UNTALK or
UNLISTEN, so other channels can be used between calls. Opening with a name
ending `,S,W` or `,P,W` writes a SEQ or PRG file on any channel; `@0:`
replaces an existing one. `kd_seek` is sd2iec's `P` for ordinary files
(Commodore drives position only REL files with `P`). Offsets count from the
first byte of the file, including a PRG file's load address; past the end the
code is 50, RECORD NOT PRESENT.

`iec_jiffy` switches JiffyDOS as in [library.md](library.md#jiffydos):
`iec_jiffy = 0;` forces the standard protocol. `kd_load` uses JiffyDOS LOAD
mode with a device that answers.

A load of a missing file returns `ST_RTO` and touches no memory; the status
channel then says 62, FILE NOT FOUND. `kd_dirent.name` is raw PETSCII and
`type` is `PRG`, `SEQ`, `USR`, `REL`, `DEL` or `DIR`, without the `*` and `<`
marks.

```c
#include "kimdos.h"

uint16_t end;
char st[48];
if (kd_load("GAME", 4, 0, &end))
  kd_status(st);
```

## Timing

`iec.s` keeps `asm/lib/iec.s`'s cycle counts, so its bus timing is the one
proven on hardware. As with the ca65 build, where a delay or poll loop
crosses a page boundary its branch takes one cycle more, stretching that
loop; every such time is a minimum or a timeout with margin.

## Testing

`tests/test_clib.py` builds `src/kimdos/c/test/kdtest.c` with `make clib` and runs it on
the simulated KIM-1 against the drive model, comparing its printed results.
