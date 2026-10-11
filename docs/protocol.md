# Serial bus protocol

KIMDOS is the bus controller. All lines are open collector: a line is
asserted (low) if any device pulls it, released (high) only when none does.
Times assume a 1 MHz 6502.

## Sending a byte (KIMDOS or the drive as talker)

1. The talker holds CLK, the listener holds DATA.
2. The talker releases CLK: ready to send. KIMDOS first checks that DATA is
   held; if not, nobody is listening and it reports device not present.
3. The listener releases DATA when ready for data; this can take any time.
4. For the last byte the talker waits instead; the listener, after 200 us
   without CLK, acknowledges end-of-information by pulling DATA for at
   least 60 us. KIMDOS waits about 300 us before deciding, and pulls DATA for
   80 us.
5. Eight bits, least significant first: with CLK held the talker sets DATA
   (released is 1), waits 40 us, releases CLK for 40 us, pulls CLK again.
6. The talker releases DATA; the listener must pull it within 1 ms to
   acknowledge the byte.

## Commands

KIMDOS pulls ATN and CLK, waits 1 ms for devices to pull DATA, and sends the
command bytes as above: LISTEN $20+device, TALK $40+device, UNLISTEN $3F,
UNTALK $5F, then a secondary address $60+channel (data), $E0+channel (close)
or $F0+channel (open). The byte that ends a LISTEN data stream goes with EOI,
so KIMDOS holds each byte back until it knows whether another follows.

After TALK and its secondary, the roles turn around: KIMDOS pulls DATA,
releases ATN and then CLK, and waits for the drive to take CLK.

## Files

| Operation | Bus traffic |
| --- | --- |
| load | OPEN 0 with the name; TALK channel 0; two address bytes, data to EOI; CLOSE 0 |
| save | OPEN 1 with the name; LISTEN channel 1; two address bytes, data with EOI; CLOSE 1 |
| directory | load of `$`: a BASIC program, one line per file |
| status | TALK channel 15, read to EOI |
| command | LISTEN channel 15, the command with EOI |

A missing file shows on the first read: the drive signals ready to send and
then sends nothing, which KIMDOS sees as EOI followed by a read timeout.

## JiffyDOS

KIMDOS speaks JiffyDOS to devices that answer it, as sd2iec implements the
device side (`src/iec.c`, `src/avr/fastloader-ll.S`,
`src/lpc17xx/llfl-jiffydos.c`), and the standard protocol to the rest.
`iec_jiffy` = 0 forces the standard protocol.

Times below are microseconds from the host's own start write, W. sd2iec's
LPC17xx build times from hardware edge capture at fixed offsets; the AVR
build polls the bus, so its offsets move by the polling loop's phase, 0.5 to
6.5 cycles at 8 MHz. Both are given; the table's KIMDOS column is where the
6502 library acts, cycle-exact at 1 MHz from straight-line code after W, so
neither the polling before W nor a branch crossing a page moves it.

### Detection

Every TALK and LISTEN offers it. KIMDOS sends bits 0-6 of the command byte as
usual, then holds CLK with DATA released and polls DATA for 400 us. The
addressed device, after 218 us without the last bit, pulls DATA for 101 us;
KIMDOS waits for the release and sends bit 7. A device that does not answer
just sees a slow bit. The device forgets the mode at the next ATN, so the
detection runs on every TALK and LISTEN; command and secondary bytes stay
standard. A device with nothing to say costs the 400 us wait.

### Receiving (device talks)

The device releases CLK when it has a byte. KIMDOS releases DATA at W, at
least 12 us later (the device arms 1.25 us (AVR) or 3 us (LPC) after
releasing CLK). The device puts four bit pairs on CLK and DATA, released
= 1, then a status:

| | CLK | DATA | LPC | AVR | KIMDOS reads |
| --- | --- | --- | --- | --- | --- |
| pair 0 | bit 0 | bit 1 | 10 | 9.9-10.7 | 16 |
| pair 1 | bit 2 | bit 3 | 20 | 19.9-20.7 | 26 |
| pair 2 | bit 4 | bit 5 | 31 | 30.9-31.7 | 37 |
| pair 3 | bit 6 | bit 7 | 41 | 40.9-41.7 | 47 |
| status | | | 52 | 51.9-52.7 | 60 |

Status: CLK pulled, a byte with more to come; CLK released and DATA pulled,
the last byte (EOI); both released, nothing was sent (`ST_RTO`, as a missing
file). KIMDOS pulls DATA to acknowledge at W+70. An EOI status lasts until
the device releases DATA 50 (AVR) or 60 (LPC) us later. sd2iec counts a byte
as sent only if ATN stays released for 10 us after the acknowledge; KIMDOS
asserts it much later.

### Sending (device listens)

The device releases DATA when ready. KIMDOS releases CLK at W, at least
10 us later, then drives pairs, pulled = 1:

| | CLK | DATA | KIMDOS writes | LPC samples | AVR samples |
| --- | --- | --- | --- | --- | --- |
| pair 0 | bit 4 | bit 5 | 8 | 18.5 | 17.1-17.7 |
| pair 1 | bit 6 | bit 7 | 24 | 31.5 | 30.1-30.7 |
| pair 2 | bit 3 | bit 1 | 36 | 42.5 | 41.1-41.7 |
| pair 3 | bit 2 | bit 0 | 48 | 55.5 | 54.1-54.7 |
| EOI | released = last | released | 61 | 67 | 67.1-67.7 |
| | pulled | released | 75 | | |

The device pulls DATA at 73 (73.3-73.9 AVR) for at least 10 us; KIMDOS
reads it at W+79 and sets `ST_WTO` if it is not there. CLK must be pulled
again before the device returns for the next byte at 83, or it would take a
released CLK as the next start. A listener that has gone away, as after a
failed OPEN, shows as `ST_WTO` rather than `ST_DNP`: in this protocol both
leave DATA released between bytes.

### LOAD

After the load address has come through as above, `dos_load` and `kd_load`
end the TALK and send TALK with secondary $61, which sd2iec takes as channel
0 in LOAD mode (it restarts at the third byte of the file). The file comes in
blocks, the sd2iec buffer's 254 bytes:

1. KIMDOS releases DATA. The device signals a block with DATA pulled and CLK
   released, or the end of the file with both released.
2. The device releases DATA when it starts the block. For each byte KIMDOS
   pulls DATA at W and releases it at W+4; the device puts the four pairs
   out at the receive times above, with no status and no acknowledge.
3. KIMDOS reads CLK at W+60. Released: the next byte is ready and KIMDOS
   starts it (at about W+114). Pulled: the block ended, with the byte just
   read; KIMDOS pulls DATA for 10 us to acknowledge and goes to step 1.

The device releases the bus for the next byte 10.4 us (AVR) or 10 us plus
its return (LPC) after pair 3, and is ready for the next start 1.25 or 3 us
after that; the end-of-block mark comes at the status time. Reading at W+60
and starting no earlier than W+64 clears both. Verify, and names starting
with `$`, use the byte protocol.

### Margins

`Drive` in `kimdos.iec` models the device side with these timings
(`JIFFY_LPC`, `JIFFY_AVR_EARLY`, `JIFFY_AVR_LATE`) and records an error
whenever the host reads the bus within `margin` us of one of the device's
changes, changes a line within `margin` us of a device sample, misses a
window, or starts before the device is armed. `kimdos bench` finds the
largest margin each timing allows; see [development.md](development.md).
