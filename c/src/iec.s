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
JDET_POLLS = 36                 ; 11-cycle polls: 400 us for a JiffyDOS reply
JACK_POLLS = 100                ; its end, about 1.1 ms

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

; Exactly n cycles, n >= 2, touching nothing.
.macro  WAIT n
.if (\n) < 2
.error "WAIT needs 2 or more cycles"
.endif
.if (\n) & 1
        jmp .Lwait\@
.Lwait\@:
.rept ((\n) - 3) / 2
        nop
.endr
.else
.rept (\n) / 2
        nop
.endr
.endif
.endm

        .globl iec_listen, iec_talk, iec_second, iec_tksa
        .globl iec_unlsn, iec_untlk, iec_ciout, iec_acptr, iec_st
        .globl iec_jiffy, iec_jload

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
1:      pla
        pha
        jsr jarm
        php
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
        bit jdet
        bpl .Ltxbit
        dex                     ; bits 0-6, then jdetect
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
        bit jdet
        bpl 1f
        jsr jdetect
        bne .Ltxbit
1:      DELAY 10
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
        bit iec_jiffy
        bpl 1f
        jmp jrx
1:      php
        sei
        cld
        stx savx
6:      bit PORT                ; talker ready to send
        bvc 6b
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

; JiffyDOS, as sd2iec implements it on the device side.  A device that
; speaks it answers a TALK or LISTEN whose last bit comes late by pulling
; DATA; the data bytes of that transaction then go as four bit pairs on CLK
; and DATA at fixed times after a start edge.  Every sample and change is
; timed from the host's own start write in straight-line code, so neither
; the polling before it nor branch page crossings move the windows.

; Arm detection for the command byte A: TALK and LISTEN when enabled.
        .section .text.iec_jarm,"ax",@progbits
jarm:   and #0x1F
        cmp #0x1F               ; UNTALK, UNLISTEN
        lda #0
        bcs 1f
        lda iec_jiffy
        lsr a
        ror a
1:      sta jdet
        lda iec_jiffy
        and #0x7F
        sta iec_jiffy
        rts

; Before bit 7, with CLK held: a reply 218 us after CLK fell lasts 101 us.
; Returns X = 1, Z = 0 for the last bit.
jdetect:
        lsr jdet
        ldx #JDET_POLLS
1:      bit PORT
        bpl 2f
        dex
        bne 1b
        beq .Ljdone
2:      lda iec_jiffy
        ora #0x80
        sta iec_jiffy
        ldx #JACK_POLLS
3:      bit PORT                ; wait out the reply
        bmi .Ljdone
        dex
        bne 3b
.Ljdone:
        ldx #1
        rts

; Receive a byte as listener: as iec_acptr.  Cycle offsets from W, the
; write that releases DATA.
        .section .text.iec_jrx,"ax",@progbits
jrx:    php
        sei
        cld
        stx savx
        sty savy
1:      bit PORT                ; talker ready: CLK released
        bvc 1b
        lda PORT
        and #(~OUTS) & 0xFF
        sta PORT                ; W: start
        WAIT 12
        lda PORT                ; W+16: bits 1, 0 on DATA, CLK
        and #0xC0
        lsr a
        lsr a
        ora PORT                ; W+26: bits 3, 2
        and #0xF0
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
        and #0xC0
        lsr a
        lsr a
        ora jtmp
        sta jtmp
        tya
        and #0xC0
        ora jtmp
        bit jst
        bvc .Ljrdone
        bpl 2f
        lda #ST_EOI | ST_RTO    ; neither held: nothing was sent
        jsr setst
        lda #0
        beq .Ljrdone
2:      pha
        lda #ST_EOI
        jsr setst
        pla
.Ljrdone:
        ldx savx
        ldy savy
        plp
        cmp #0
        rts

; Send A as talker, C = 1 for EOI.  Cycle offsets from W, the write that
; releases CLK.  The device samples at W+17..19, 30..32, 41..43, 54..56 and
; the EOI flag at W+67, then pulls DATA from W+73 for 10 us.
        .section .text.iec_jtx,"ax",@progbits
jtx:    sta txb
        ror eoi
        php
        sei
        cld
        stx savx
        sty savy
        lda PORT
        and #(~OUTS) & 0xFF
        sta jrel
        ora #CLK
        sta jv+5
        bit eoi
        bpl 1f
        lda jrel                ; EOI: CLK released
1:      sta jv+4
        lda txb
        and #0x30               ; bits 4, 5 on CLK, DATA
        ora jrel
        sta jv
        lda txb
        lsr a
        lsr a
        and #0x30               ; bits 6, 7
        ora jrel
        sta jv+1
        lda txb
        and #0x0F
        tax
        lda jlo2,x              ; bits 3, 1
        ora jrel
        sta jv+2
        lda jlo3,x              ; bits 2, 0
        ora jrel
        sta jv+3
2:      bit PORT                ; listener ready: DATA released
        bpl 2b
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
        bcc 3f
        lda #ST_WTO
        jmp .Ltxfail
3:      jmp .Ltxok

; Bit pairs 2 and 3 of a send by the low nibble: CLK, DATA pulled for 1.
        .section .rodata.iec_jlo,"a",@progbits
jlo2:
.irp n,0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15
        .byte ((\n >> 3) & 1) * CLK | ((\n >> 1) & 1) * DAT
.endr
jlo3:
.irp n,0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15
        .byte ((\n >> 2) & 1) * CLK | (\n & 1) * DAT
.endr

        .section .data.iec_jiffy,"aw",@progbits
iec_jiffy:
        .byte 1                 ; bit 0: use JiffyDOS; bit 7: device answered

; After TALK with secondary 0x61 to a device that answered JiffyDOS: receive
; the rest of the file in LOAD mode to A/X upwards.  Returns A/X one past
; the last byte, ST_EOI set.  Self-modifying, so in data.  Cycle offsets
; from W, the write that pulls DATA to start a byte.
        .section .data.iec_jload,"awx",@progbits
iec_jload:
        sta .Ljlst+1
        stx .Ljlst+2
        php
        sei
        cld
        sty savy
        lda PORT
        and #(~OUTS) & 0xFF
        sta jrel
        ora #DAT
        sta jast
        lda jrel
        sta PORT                ; release DATA: ready for a block
.Ljlblk:
        lda PORT
        asl a                   ; N = CLK, C = DATA
        bpl .Ljlblk             ; CLK held: busy
        bcs .Ljleof             ; both released: end of file
1:      bit PORT                ; DATA released: the device waits for a start
        bpl 1b
.Ljlbyte:
        ldx jrel
        lda jast
        sta PORT                ; W: start
        stx PORT                ; W+4
        WAIT 8
        lda PORT                ; W+16: bits 1, 0
        and #0xC0
        lsr a
        lsr a
        ora PORT                ; W+26: bits 3, 2
        and #0xF0
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
        and #0xC0
        lsr a
        lsr a
        ora jtmp
        sta jtmp
        tya
        and #0xC0
        ora jtmp
.Ljlst: sta 0xFFFF
        inc .Ljlst+1
        bne 2f
        inc .Ljlst+2
2:      txa
        asl a
        bmi .Ljlbyte            ; CLK released: the next byte is ready
        lda jast                ; acknowledge the end of the block
        sta PORT
        DELAY 10
        lda jrel
        sta PORT
        jmp .Ljlblk
.Ljleof:
        lda #ST_EOI
        jsr setst
        lda .Ljlst+1
        ldx .Ljlst+2
        ldy savy
        plp
        rts

        .section .bss.iec,"aw",@nobits
iec_st: .zero 1
bufd:   .zero 1                 ; bit 7: bufb holds a byte not yet sent
bufb:   .zero 1
txb:    .zero 1
rxb:    .zero 1
eoi:    .zero 1
savx:   .zero 1
savy:   .zero 1
jdet:   .zero 1                 ; bit 7: offer JiffyDOS on this command byte
jtmp:   .zero 1
jst:    .zero 1
jrel:   .zero 1                 ; port A with the bus released
jast:   .zero 1                 ; and DATA pulled
jv:     .zero 6                 ; send: bit pairs, EOI flag, CLK held
