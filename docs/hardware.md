# Hardware

The adapter is the KIM-1 user port on one side and an IEC socket on the other:
a 7406 open-collector inverter drives the bus, two port pins read it back, and
1K pull-ups hold each line high.

| Port A | Direction | Bus line | IEC pin |
| --- | --- | --- | --- |
| PA3 | out, through 7406 | ATN | 3 |
| PA4 | out, through 7406 | CLK | 4 |
| PA5 | out, through 7406 | DATA | 5 |
| PA6 | in | CLK | 4 |
| PA7 | in | DATA | 5 |
| GND | | GND | 2 |
| RS | | RESET | 6 |

Writing 1 to an output pin pulls its line low. Port A is the 6530/6532 at
$1700 on the application connector. PA0-PA2 stay free: the library sets only
bits 3-5 of the direction register and writes back the others unchanged.

Until KIMDOS first runs, the port is all inputs, its pull-ups turn the 7406 on,
and all three lines are held low. Drives tolerate this; the first command
releases them.

Wiring the KIM-1 RS line to the bus RESET means RS also resets the drive.

## Memory

The image needs about 2.5K of RAM for code and variables, at an address chosen
at link time, and nothing in zero page. On a PAL-II, any 8K block switched to
RAM by `SW5` works; the $0400-$13FF K1-K4 RAM does too if a program does not
need it.

## Speed

Transfers run at the drive's pace, about 1K a second with a 1541 and somewhat
faster with an SD2IEC. Saves take longer, as the host clocks each bit.
