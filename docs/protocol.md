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
