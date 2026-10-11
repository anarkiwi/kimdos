# Library

`build/kimdos.lib` is a ca65/ld65 object library. Link it into a program and
include `asm/include/kimdos.inc` for the symbols:

```sh
ca65 -I asm/include -o myprog.o myprog.s
ld65 -C myprog.cfg -o myprog.bin myprog.o build/kimdos.lib
```

ld65 pulls in only the modules a program references: `iec.o` (bus), `dos.o`
(files, needs `iec.o`) and `con.o` (TTY output through the KIM-1 monitor).

The library uses no zero page. It needs `CODE`, `DATA` and `BSS` segments;
`DATA` holds the device number and three small self-modified access
routines, so it must be in RAM. A ROM build puts `DATA` in RAM and copies it
there at start-up in the usual cc65 way. Nothing needs initialising when the
whole image is loaded into RAM.

Every routine clears decimal mode for its own use and masks interrupts while it
drives the bus, restoring the caller's flags afterwards.

## Status

`iec_st` collects status bits as the bus primitives run; the DOS routines clear
it at the start of each operation.

| Bit | Name | Meaning |
| --- | --- | --- |
| $01 | `ST_WTO` | a listener did not acknowledge a byte |
| $02 | `ST_RTO` | the talker sent nothing: file not found, channel not open |
| $10 | `ST_VER` | verify found a difference |
| $40 | `ST_EOI` | the last byte read was the end of the data |
| $80 | `ST_DNP` | no device answered |

## DOS layer

Routines that return C set it on any error, with `iec_st` saying which.

| Routine | In | Out |
| --- | --- | --- |
| `dos_setnam` | A = length, X/Y = address | name for the next open, command or load; the bytes are read when used, not copied |
| `dos_open` | A = channel 0-15 | OPEN with the name; C |
| `dos_close` | A = channel | CLOSE |
| `dos_chkin` | A = channel | TALK the channel; follow with `dos_getb`, end with `iec_untlk`; C |
| `dos_chkout` | A = channel | LISTEN to the channel; follow with `iec_ciout`, end with `iec_unlsn`; C |
| `dos_getb` | | A = next byte; C = 1 and A = 0 once past the end |
| `dos_read` | A = channel | reads into `dos_beg` up to `dos_end` (exclusive, 0 = no limit) or end of data; `dos_beg` advances; C |
| `dos_write` | A = channel | writes `dos_beg` up to `dos_end` (exclusive); C |
| `dos_load` | A = 0 load, 1 verify; C = 1 to load at `dos_beg` | `dos_beg`-`dos_end` = range loaded; C |
| `dos_save` | `dos_beg`, `dos_end` (exclusive) | writes a PRG file with its load address; C |
| `dos_cmd` | | sends the name as a command on channel 15 |
| `dos_status` | | `dos_errbuf` = status text; A = its number ($FF if no device); C = 1 for 20 and above |

`dos_dev` holds the device number, 8 by default.

`dos_read` stops at `dos_end` without closing anything, so a program can
fetch a file in pieces: call it again to continue where it stopped. Random
access works the CBM way: open a buffer channel with the name `#`, issue
`U1:`/`B-P:` commands with `dos_cmd`, and `dos_read` the channel.

```asm
        lda #len
        ldx #<fname
        ldy #>fname
        jsr dos_setnam
        lda #0                  ; load, not verify
        clc                     ; to the file's own address
        jsr dos_load
        bcs failed
```

## Bus primitives

The KERNAL-style serial bus calls, for anything the DOS layer does not cover.
Secondary addresses are passed whole: `$60+ch` data, `$E0+ch` close,
`$F0+ch` open.

| Routine | In | Note |
| --- | --- | --- |
| `iec_listen` | A = device | |
| `iec_second` | A = secondary | after LISTEN |
| `iec_talk` | A = device | |
| `iec_tksa` | A = secondary | after TALK; turns the bus around |
| `iec_ciout` | A = byte | holds one byte back so that UNLISTEN sends it with EOI |
| `iec_acptr` | | A = byte, Z set for 0 |
| `iec_unlsn` | | |
| `iec_untlk` | | |

All preserve X and Y.

## Console

`con.o` wraps the monitor's `OUTCH` and `GETCH` so that X and Y survive.
`con_putc`, `con_getc`, `con_crlf`, `con_puts` (X/Y = zero-terminated
string), `con_pet` (PETSCII to ASCII), `con_phex`, `con_phex16` (X high, A
low), `con_pdec` (X high, A low).

## Resident image

The shell image starts with a jump table so that programs which are not linked
against the library, a BASIC `USR` routine say, can still call it:

| Offset | Entry | Offset | Entry |
| --- | --- | --- | --- |
| +0 | shell | +39 | `dos_cmd` |
| +3 | keypad load | +42 | `dos_status` |
| +6 | keypad save | +45 | `iec_listen` |
| +9 | `dos_setnam` | +48 | `iec_second` |
| +12 | `dos_open` | +51 | `iec_talk` |
| +15 | `dos_close` | +54 | `iec_tksa` |
| +18 | `dos_chkin` | +57 | `iec_ciout` |
| +21 | `dos_chkout` | +60 | `iec_acptr` |
| +24 | `dos_getb` | +63 | `iec_unlsn` |
| +27 | `dos_read` | +66 | `iec_untlk` |
| +30 | `dos_write` | | |
| +33 | `dos_load` | | |
| +36 | `dos_save` | | |

Then the addresses of the variables: +69 `dos_dev`, +71 `iec_st`, +73
`dos_beg`, +75 `dos_end`, +77 `dos_errbuf`.
