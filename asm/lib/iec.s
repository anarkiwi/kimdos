; Commodore serial bus controller, bit-banged on the KIM-1 user port.
;
; Adapter on the 6530/6532 port A, outputs through a 7406 inverter:
;   PA3 -> ATN, PA4 -> CLK, PA5 -> DATA   (write 1 to assert/pull low)
;   PA6 <- CLK, PA7 <- DATA               (read 1 when released)
; PA0-PA2 are left as found.

        .setcpu "6502"
        .include "kimdos.inc"

PORT    = $1700
DDR     = $1701
ATN     = $08
CLK     = $10
DAT     = $20
INS     = $C0
OUTS    = ATN | CLK | DAT

T_SETUP = 40                    ; talker bit setup and valid times, us
T_VALID = 40
EOI_POLLS = 28                  ; 11-cycle polls: just over 300 us
FRAME_POLLS = 100               ; about 1.1 ms

; Busy-wait about us microseconds at 1 MHz; clobbers A and C.
.macro  DELAY us
        .local l
        sec
        lda #<((us) / 5)
l:      sbc #1
        bne l
.endmacro

.macro  ASSERT bits
        lda PORT
        ora #bits
        sta PORT
.endmacro

.macro  RELEASE bits
        lda PORT
        and #<~(bits)
        sta PORT
.endmacro

        .segment "CODE"

iec_listen:
        ora #$20
        bne atncmd
iec_talk:
        ora #$40
atncmd: pha
        bit bufd
        bpl :+
        jsr flush
:       php
        sei
        lda PORT
        and #<~DAT
        ora #ATN | CLK
        sta PORT
        lda DDR
        and #<~INS
        ora #OUTS
        sta DDR
        DELAY 1000
        plp
        pla
        clc
        jmp txbyte

iec_second:
        clc
        jsr txbyte
atnoff: RELEASE ATN
        rts

iec_tksa:
        clc
        jsr txbyte
        bit iec_st
        bmi tkdone
        php
        sei
        lda PORT
        ora #DAT
        and #<~ATN
        sta PORT
        DELAY 20
        RELEASE CLK
        DELAY 20
        stx savx
        ldx #0
        lda #0
:       bit PORT                ; device takes CLK to become talker
        bvc :+
        dex
        bne :-
        sec
        sbc #1
        bne :-
        lda #ST_RTO
        jsr setst
:       ldx savx
        plp
tkdone: rts

iec_unlsn:
        lda #$3F
        bne :+
iec_untlk:
        lda #$5F
:       jsr atncmd
        jsr atnoff
        DELAY 20
        RELEASE CLK | DAT
        rts

iec_ciout:
        bit bufd
        bpl :+
        pha
        clc
        jsr flush
        pla
:       sta bufb
        sec
        ror bufd
        rts

flush:  lda bufb
        lsr bufd
        ; fall through, C = EOI

; Send A as talker, C = 1 for EOI.  CLK is held by us, DATA by a listener.
txbyte: sta txb
        ror eoi
        php
        sei
        cld
        stx savx
        bit PORT
        bpl :+
        lda #ST_DNP
        bne txfail
:       RELEASE CLK
:       bit PORT                ; listener ready for data
        bpl :-
        bit eoi
        bpl :+++
:       bit PORT                ; listener acknowledges EOI
        bmi :-
:       bit PORT
        bpl :-
:       ldx #8
txbit:  lda PORT
        ora #CLK
        and #<~DAT
        lsr txb
        bcs :+
        ora #DAT
:       sta PORT
        DELAY T_SETUP
        RELEASE CLK
        DELAY T_VALID
        lda PORT
        ora #CLK
        and #<~DAT
        sta PORT
        dex
        bne txbit
        DELAY 10
        ldx #FRAME_POLLS
:       bit PORT                ; listener acknowledges the frame
        bpl txok
        dex
        bne :-
        lda #ST_WTO
txfail: jsr setst
        RELEASE OUTS
txok:   ldx savx
        plp
        rts

; Receive a byte as listener.  Sets ST_EOI on the last byte, and ST_RTO
; (returning 0) if the talker never sends.  Z reflects A.
iec_acptr:
        php
        sei
        cld
        stx savx
:       bit PORT                ; talker ready to send
        bvc :-
        RELEASE DAT
        ldx #EOI_POLLS
:       bit PORT
        bvc rxbits
        dex
        bne :-
        lda #ST_EOI
        jsr setst
        ASSERT DAT
        DELAY 80
        RELEASE DAT
        ldx #FRAME_POLLS
:       bit PORT
        bvc rxbits
        dex
        bne :-
        lda #ST_RTO
        jsr setst
        lda #0
        beq rxdone
rxbits: ldx #8
:       lda PORT                ; C = DATA, N = CLK
        asl a
        bpl :-
        ror rxb
:       bit PORT
        bvs :-
        dex
        bne :--
        ASSERT DAT
        lda rxb
rxdone: ldx savx
        plp
        cmp #0
        rts

setst:  ora iec_st
        sta iec_st
        rts

        .segment "BSS"
iec_st: .res 1
bufd:   .res 1
bufb:   .res 1
txb:    .res 1
rxb:    .res 1
eoi:    .res 1
savx:   .res 1
