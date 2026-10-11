; Console output over the KIM-1 monitor's TTY routines.

        .setcpu "6502"
        .include "kimdos.inc"

        .segment "CODE"

con_putc:
        sta sava
        stx savx
        sty savy
        jsr KIM_OUTCH
        ldx savx
        ldy savy
        lda sava
        rts

con_getc:
        stx savx
        sty savy
        jsr KIM_GETCH
        and #$7F
        ldx savx
        ldy savy
        rts

con_crlf:
        lda #$0D
        jsr con_putc
        lda #$0A
        jmp con_putc

; CR breaks the line, shifted letters print lower case, shifted space prints
; as space, other control and graphic codes are dropped.
con_pet:
        cmp #$0D
        beq con_crlf
        cmp #$A0
        bne :+
        lda #' '
:       cmp #$C1
        bcc :+
        cmp #$DB
        bcs :+
        eor #$A0
:       cmp #$20
        bcc :+
        cmp #$7B
        bcs :+
        jmp con_putc
:       rts

con_puts:
        stx sop+1
        sty sop+2
        ldy #0
:       jsr sop
        beq :+
        jsr con_putc
        iny
        bne :-
:       rts

con_phex16:
        pha
        lda #'$'
        jsr con_putc
        txa
        jsr con_phex
        pla
con_phex:
        pha
        lsr a
        lsr a
        lsr a
        lsr a
        jsr :+
        pla
:       and #$0F
        cmp #10
        bcc :+
        adc #6
:       adc #'0'
        jmp con_putc

; Unsigned decimal of X (high) A (low), without leading zeros.
con_pdec:
        sta num
        stx num+1
        ldy #0
        sty lead
pdig:   ldx #0
:       lda num
        sec
        sbc declo,y
        sta tmp
        lda num+1
        sbc dechi,y
        bcc :+
        sta num+1
        lda tmp
        sta num
        inx
        bne :-
:       txa
        ora lead
        cpy #4
        beq :+
        cmp #0
        beq :++
:       txa
        ora #'0'
        sta lead
        jsr con_putc
:       iny
        cpy #5
        bne pdig
        rts

declo:  .lobytes 10000, 1000, 100, 10, 1
dechi:  .hibytes 10000, 1000, 100, 10, 1

        .segment "DATA"
sop:    lda $FFFF,y
        rts

        .segment "BSS"
sava:   .res 1
savx:   .res 1
savy:   .res 1
num:    .res 2
tmp:    .res 1
lead:   .res 1
