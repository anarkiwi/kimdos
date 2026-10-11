; Commodore serial bus controller, bit-banged on the KIM-1 user port.
; llvm-mos port of asm/lib/iec.s: the same instructions and timing.
;
; Adapter on the 6530/6532 port A, outputs through a 7406 inverter:
;   PA3 -> ATN, PA4 -> CLK, PA5 -> DATA   (write 1 to assert/pull low)
;   PA6 <- CLK, PA7 <- DATA               (read 1 when released)
; PA0-PA2 are left as found.  Arguments and results in A; X and Y preserved.

PORT    = 0x1700
DDR     = 0x1701
ATN     = 0x08
CLK     = 0x10
DAT     = 0x20
INS     = 0xC0
OUTS    = ATN | CLK | DAT

ST_WTO  = 0x01
ST_RTO  = 0x02
ST_EOI  = 0x40
ST_DNP  = 0x80

T_SETUP = 40                    ; talker bit setup and valid times, us
T_VALID = 40
EOI_POLLS = 28                  ; 11-cycle polls: just over 300 us
FRAME_POLLS = 100               ; about 1.1 ms

; Busy-wait about us microseconds at 1 MHz; clobbers A and C.
.macro  DELAY us
        sec
        lda #((\us) / 5)
.Ldelay\@:
        sbc #1
        bne .Ldelay\@
.endm

.macro  ASSERT bits
        lda PORT
        ora #(\bits)
        sta PORT
.endm

.macro  RELEASE bits
        lda PORT
        and #(~(\bits)) & 0xFF
        sta PORT
.endm

        .globl iec_listen, iec_talk, iec_second, iec_tksa
        .globl iec_unlsn, iec_untlk, iec_ciout, iec_acptr, iec_st

        .section .text.iec_listen,"ax",@progbits
iec_listen:
        ora #0x20
        bne atncmd
iec_talk:
        ora #0x40
atncmd: pha
        bit bufd
        bpl 1f
        sec
        jsr flush
1:      php
        sei
        lda PORT
        and #(~DAT) & 0xFF
        ora #ATN | CLK
        sta PORT
        lda DDR
        and #(~INS) & 0xFF
        ora #OUTS
        sta DDR
        DELAY 1000
        plp
        pla
        clc
        jmp txbyte

        .section .text.iec_second,"ax",@progbits
iec_second:
        clc
        jsr txbyte
atnoff: RELEASE ATN
        rts

        .section .text.iec_tksa,"ax",@progbits
iec_tksa:
        clc
        jsr txbyte
        bit iec_st
        bmi .Ltkdone
        php
        sei
        lda PORT
        ora #DAT
        and #(~ATN) & 0xFF
        sta PORT
        DELAY 20
        RELEASE CLK
        DELAY 20
        stx savx
        ldx #0
        lda #0
.Ltkpoll:
        bit PORT                ; device takes CLK to become talker
        bvc .Ltkok
        dex
        bne .Ltkpoll
        sec
        sbc #1
        bne .Ltkpoll
        lda #ST_RTO
        jsr setst
.Ltkok: ldx savx
        plp
.Ltkdone:
        rts

        .section .text.iec_unlsn,"ax",@progbits
iec_unlsn:
        lda #0x3F
        bne 1f
iec_untlk:
        lda #0x5F
1:      jsr atncmd
        jsr atnoff
        DELAY 20
        RELEASE CLK | DAT
        rts

        .section .text.iec_ciout,"ax",@progbits
iec_ciout:
        bit bufd
        bpl 1f
        pha
        clc
        jsr flush
        pla
1:      sta bufb
        sec
        ror bufd
        rts

; Send the held-back byte, C = 1 for EOI.
        .section .text.iec_txbyte,"ax",@progbits
flush:  lda #0
        sta bufd
        lda bufb

; Send A as talker, C = 1 for EOI.  CLK is held by us, DATA by a listener.
txbyte: sta txb
        ror eoi
        php
        sei
        cld
        stx savx
        bit PORT
        bpl 1f
        lda #ST_DNP
        bne .Ltxfail
1:      RELEASE CLK
2:      bit PORT                ; listener ready for data
        bpl 2b
        bit eoi
        bpl .Ltxbyte
3:      bit PORT                ; listener acknowledges EOI
        bmi 3b
4:      bit PORT
        bpl 4b
.Ltxbyte:
        ldx #8
.Ltxbit:
        lda PORT
        ora #CLK
        and #(~DAT) & 0xFF
        lsr txb
        bcs 1f
        ora #DAT
1:      sta PORT
        DELAY T_SETUP
        RELEASE CLK
        DELAY T_VALID
        lda PORT
        ora #CLK
        and #(~DAT) & 0xFF
        sta PORT
        dex
        bne .Ltxbit
        DELAY 10
        ldx #FRAME_POLLS
2:      bit PORT                ; listener acknowledges the frame
        bpl .Ltxok
        dex
        bne 2b
        lda #ST_WTO
.Ltxfail:
        jsr setst
        RELEASE OUTS
.Ltxok: ldx savx
        plp
        rts

; Receive a byte as listener.  Sets ST_EOI on the last byte, and ST_RTO
; (returning 0) if the talker never sends.  Z reflects A.
        .section .text.iec_acptr,"ax",@progbits
iec_acptr:
        php
        sei
        cld
        stx savx
1:      bit PORT                ; talker ready to send
        bvc 1b
        RELEASE DAT
        ldx #EOI_POLLS
2:      bit PORT
        bvc .Lrxbits
        dex
        bne 2b
        lda #ST_EOI
        jsr setst
        ASSERT DAT
        DELAY 80
        RELEASE DAT
        ldx #FRAME_POLLS
3:      bit PORT
        bvc .Lrxbits
        dex
        bne 3b
        lda #ST_RTO
        jsr setst
        lda #0
        beq .Lrxdone
.Lrxbits:
        ldx #8
4:      lda PORT                ; C = DATA, N = CLK
        asl a
        bpl 4b
        ror rxb
5:      bit PORT
        bvs 5b
        dex
        bne 4b
        ASSERT DAT
        lda rxb
.Lrxdone:
        ldx savx
        plp
        cmp #0
        rts

        .section .text.iec_setst,"ax",@progbits
setst:  ora iec_st
        sta iec_st
        rts

        .section .bss.iec,"aw",@nobits
iec_st: .zero 1
bufd:   .zero 1                 ; bit 7: bufb holds a byte not yet sent
bufb:   .zero 1
txb:    .zero 1
rxb:    .zero 1
eoi:    .zero 1
savx:   .zero 1
