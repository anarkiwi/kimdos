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
POLL = 11                       ; cycles per poll: bit, branch, dex, bne
EOI_POLLS = 308 / POLL          ; past the talker's EOI delay
FRAME_POLLS = 1100 / POLL       ; past the frame acknowledge limit
JDET_POLLS = 396 / POLL         ; past a JiffyDOS reply
JACK_POLLS = 1100 / POLL        ; past its end

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

; Exactly n cycles, n >= 2, touching nothing.
.macro  WAIT n
        .local l
        .if (n) < 2
        .error "WAIT needs 2 or more cycles"
        .endif
        .if (n) & 1
        jmp l
l:
        .repeat ((n) - 3) / 2
        nop
        .endrep
        .else
        .repeat (n) / 2
        nop
        .endrep
        .endif
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
        sec
        jsr flush
:       pla
        pha
        jsr jarm
        php
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

; Send the held-back byte, C = 1 for EOI.
flush:  lda #0
        sta bufd
        lda bufb
        bit iec_jiffy
        bpl txbyte
        jmp jtx

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
        bit jdet
        bpl txbit
        dex                     ; bits 0-6, then jdetect
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
        bit jdet
        bpl :+
        jsr jdetect
        bne txbit
:       DELAY 10
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
        bit iec_jiffy
        bpl :+
        jmp jrx
:       php
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

; JiffyDOS, as sd2iec implements it on the device side.  A device that
; speaks it answers a TALK or LISTEN whose last bit comes late by pulling
; DATA; the data bytes of that transaction then go as four bit pairs on CLK
; and DATA at fixed times after a start edge.  Every sample and change is
; timed from the host's own start write in straight-line code, so neither
; the polling before it nor branch page crossings move the windows.

; Arm detection for the command byte A: TALK and LISTEN when enabled.
jarm:   and #$1F
        cmp #$1F                ; UNTALK, UNLISTEN
        lda #0
        bcs :+
        lda iec_jiffy
        lsr a
        ror a
:       sta jdet
        lda iec_jiffy
        and #$7F
        sta iec_jiffy
        rts

; Before bit 7, with CLK held: poll for the reply, then wait out its end.
; Returns X = 1, Z = 0 for the last bit.
jdetect:
        lsr jdet
        ldx #JDET_POLLS
:       bit PORT
        bpl :+
        dex
        bne :-
        beq jdone
:       lda iec_jiffy
        ora #$80
        sta iec_jiffy
        ldx #JACK_POLLS
:       bit PORT                ; wait out the reply
        bmi jdone
        dex
        bne :-
jdone:  ldx #1
        rts

; Receive a byte as listener: as iec_acptr.  Cycle offsets from W, the
; write that releases DATA.
jrx:    php
        sei
        cld
        stx savx
        sty savy
:       bit PORT                ; talker ready: CLK released
        bvc :-
        lda PORT
        and #<~OUTS
        sta PORT                ; W: start
        WAIT 12
        lda PORT                ; W+16: bits 1, 0 on DATA, CLK
        and #$C0
        lsr a
        lsr a
        ora PORT                ; W+26: bits 3, 2
        and #$F0
        lsr a
        WAIT 3
        ldx PORT                ; W+37: bits 5, 4
        lsr a
        lsr a
        lsr a
        ldy PORT                ; W+47: bits 7, 6
        sta jtmp
        WAIT 5
        lda PORT                ; W+60: CLK held, a byte; else DATA held, EOI
        sta jst
        ora #DAT
        sta PORT                ; W+70: acknowledge
        txa
        and #$C0
        lsr a
        lsr a
        ora jtmp
        sta jtmp
        tya
        and #$C0
        ora jtmp
        bit jst
        bvc jrdone
        bpl :+
        lda #ST_EOI | ST_RTO    ; neither held: nothing was sent
        jsr setst
        lda #0
        beq jrdone
:       pha
        lda #ST_EOI
        jsr setst
        pla
jrdone: ldx savx
        ldy savy
        plp
        cmp #0
        rts

; Send A as talker, C = 1 for EOI.  Cycle offsets from W, the write that
; releases CLK.  The device samples at W+17..19, 30..32, 41..43, 54..56 and
; the EOI flag at W+67, then pulls DATA from W+73 (docs/protocol.md).
jtx:    sta txb
        ror eoi
        php
        sei
        cld
        stx savx
        sty savy
        lda PORT
        and #<~OUTS
        sta jrel
        ora #CLK
        sta jv+5
        bit eoi
        bpl :+
        lda jrel                ; EOI: CLK released
:       sta jv+4
        lda txb
        and #$30                ; bits 4, 5 on CLK, DATA
        ora jrel
        sta jv
        lda txb
        lsr a
        lsr a
        and #$30                ; bits 6, 7
        ora jrel
        sta jv+1
        lda txb
        and #$0F
        tax
        lda jlo2,x              ; bits 3, 1
        ora jrel
        sta jv+2
        lda jlo3,x              ; bits 2, 0
        ora jrel
        sta jv+3
:       bit PORT                ; listener ready: DATA released
        bpl :-
        lda jrel
        sta PORT                ; W: start
        lda jv
        sta PORT                ; W+8
        lda jv+1
        WAIT 8
        sta PORT                ; W+24
        lda jv+2
        WAIT 4
        sta PORT                ; W+36
        lda jv+3
        WAIT 4
        sta PORT                ; W+48
        lda jv+4
        WAIT 5
        sta PORT                ; W+61: EOI flag
        lda jv+5
        WAIT 6
        sta PORT                ; W+75: CLK held
        lda PORT                ; W+79: DATA held, acknowledged
        ldy savy
        asl a
        bcc :+
        lda #ST_WTO
        jmp txfail
:       jmp txok

; Bit pairs 2 and 3 of a send by the low nibble: CLK, DATA pulled for 1.
jlo2:   .repeat 16, n
        .byte (n >> 3 & 1) * CLK | (n >> 1 & 1) * DAT
        .endrep
jlo3:   .repeat 16, n
        .byte (n >> 2 & 1) * CLK | (n & 1) * DAT
        .endrep

        .segment "DATA"
bufd:   .byte 0                 ; bit 7: bufb holds a byte not yet sent
iec_jiffy:
        .byte 1                 ; bit 0: use JiffyDOS; bit 7: device answered

; After TALK with secondary $61 to a device that answered JiffyDOS: receive
; the rest of the file in LOAD mode to A/X upwards.  Returns A/X one past
; the last byte, ST_EOI set.  Self-modifying, so in DATA.  Cycle offsets
; from W, the write that pulls DATA to start a byte.
iec_jload:
        sta jlst+1
        stx jlst+2
        php
        sei
        cld
        sty savy
        lda PORT
        and #<~OUTS
        sta jrel
        ora #DAT
        sta jast
        lda jrel
        sta PORT                ; release DATA: ready for a block
jlblk:  lda PORT
        asl a                   ; N = CLK, C = DATA
        bpl jlblk               ; CLK held: busy
        bcs jleof               ; both released: end of file
:       bit PORT                ; DATA released: the device waits for a start
        bpl :-
jlbyte: ldx jrel
        lda jast
        sta PORT                ; W: start
        stx PORT                ; W+4
        WAIT 8
        lda PORT                ; W+16: bits 1, 0
        and #$C0
        lsr a
        lsr a
        ora PORT                ; W+26: bits 3, 2
        and #$F0
        lsr a
        WAIT 3
        ldx PORT                ; W+37: bits 5, 4
        lsr a
        lsr a
        lsr a
        ldy PORT                ; W+47: bits 7, 6
        sta jtmp
        txa
        WAIT 3
        ldx PORT                ; W+60: CLK held, end of block
        and #$C0
        lsr a
        lsr a
        ora jtmp
        sta jtmp
        tya
        and #$C0
        ora jtmp
jlst:   sta $FFFF
        inc jlst+1
        bne :+
        inc jlst+2
:       txa
        asl a
        bmi jlbyte              ; CLK released: the next byte is ready
        lda jast                ; acknowledge the end of the block
        sta PORT
        DELAY 10
        lda jrel
        sta PORT
        jmp jlblk
jleof:  lda #ST_EOI
        jsr setst
        lda jlst+1
        ldx jlst+2
        ldy savy
        plp
        rts

        .segment "BSS"
iec_st: .res 1
bufb:   .res 1
txb:    .res 1
rxb:    .res 1
eoi:    .res 1
savx:   .res 1
savy:   .res 1
jdet:   .res 1                  ; bit 7: offer JiffyDOS on this command byte
jtmp:   .res 1
jst:    .res 1
jrel:   .res 1                  ; port A with the bus released
jast:   .res 1                  ; and DATA pulled
jv:     .res 6                  ; send: bit pairs, EOI flag, CLK held
