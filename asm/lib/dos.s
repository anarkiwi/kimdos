; CBM DOS file operations over the serial bus.

        .setcpu "6502"
        .include "kimdos.inc"

ERRMAX  = 47

        .segment "CODE"

dos_setnam:
        sta namelen
        stx nmop+1
        sty nmop+2
        rts

; Perform the patched access at the current address, then advance it.
memstep:
        jsr memop
        php
        inc memop+1
        bne :+
        inc memop+2
:       plp
        rts

; LISTEN the device with secondary A.  C = 1 if not present.
lsnsec: pha
        lda #0
        sta iec_st
        lda dos_dev
        jsr iec_listen
        pla
        bit iec_st
        bmi :+
        jsr iec_second
:       lda iec_st
        asl a
        rts

dos_open:
        ora #$F0
        jsr lsnsec
        bcs :+++
        ldy #0
:       cpy namelen
        beq :+
        jsr nmop
        jsr iec_ciout
        iny
        bne :-
:       jsr iec_unlsn
        lda iec_st
        asl a
:       rts

dos_close:
        ora #$E0
        jsr lsnsec
        jmp iec_unlsn

dos_cmd:
        lda #$0F
        jsr dos_chkout
        bcs :+
        ldy #0
        beq :++
:       rts
:       cpy namelen
        beq :+
        jsr nmop
        jsr iec_ciout
        iny
        bne :-
:       jmp iec_unlsn

dos_chkout:
        ora #$60
        jmp lsnsec

dos_chkin:
        ora #$60
        pha
        lda #0
        sta iec_st
        lda dos_dev
        jsr iec_talk
        pla
        jsr iec_tksa
        lda iec_st
        asl a
        rts

dos_getb:
        lda iec_st
        and #ST_EOI | ST_RTO
        cmp #1
        lda #0
        bcs :+
        jsr iec_acptr
        clc
:       rts

; Point the memory access at dos_beg using opcode A.
setop:  sta memop
        lda dos_beg
        sta memop+1
        lda dos_beg+1
        sta memop+2
        rts

; Read channel A into dos_beg up to dos_end (exclusive; 0 for no limit) or
; the end of the data.  dos_beg advances past the last byte read.
dos_read:
        jsr dos_chkin
        bcs rddone
        lda #$8D                ; STA abs
        ldx #0
rdinto: stx vfy
        jsr setop
rdloop: lda memop+1
        cmp dos_end
        bne :+
        lda memop+2
        cmp dos_end+1
        beq rdend
:       jsr dos_getb
        bcs rdend
        jsr memstep
        beq rdloop
        bit vfy
        bpl rdloop
        lda #ST_VER
        ora iec_st
        sta iec_st
        bne rdloop
rdend:  lda memop+1
        sta dos_beg
        lda memop+2
        sta dos_beg+1
        jsr iec_untlk
rddone: lda iec_st
        and #<~ST_EOI
        cmp #1
        rts

; Write dos_beg up to dos_end (exclusive) to channel A.
dos_write:
        jsr dos_chkout
        bcs wrdone
wrbody: lda #$AD                ; LDA abs
        jsr setop
:       lda iec_st
        bne :+
        lda memop+1
        cmp dos_end
        lda memop+2
        sbc dos_end+1
        bcs :+
        jsr memstep
        jsr iec_ciout
        jmp :-
:       jsr iec_unlsn
wrdone: lda iec_st
        cmp #1
        rts

; Load (A = 0) or verify (A = 1) the named file, to its own address or with
; C = 1 to dos_beg.  On return dos_beg..dos_end is the range covered.
dos_load:
        ror reloc
        tax
        lda ldop,x
        pha
        txa
        ror a
        ror a
        sta vfy
        lda #0
        jsr dos_open
        bcs ldfail
        lda #0
        jsr dos_chkin
        bcs ldfail
        jsr dos_getb
        tax
        jsr dos_getb
        tay
        lda iec_st
        and #ST_RTO
        bne ldnf
        bit reloc
        bmi :+
        stx dos_beg
        sty dos_beg+1
:       lda dos_beg
        sta start
        lda dos_beg+1
        sta start+1
        lda #0
        sta dos_end
        sta dos_end+1
        bit vfy
        bmi ldstd
        lda iec_st
        bne ldstd
        bit iec_jiffy
        bpl ldstd
        ldy #0
        jsr nmop
        cmp #'$'
        beq ldstd
        jsr ldjif
        bcs ldnf
        pla
        jmp ldend
ldstd:  pla
        ldx vfy
        jsr rdinto
ldend:  lda dos_beg
        sta dos_end
        lda dos_beg+1
        sta dos_end+1
        lda start
        sta dos_beg
        lda start+1
        sta dos_beg+1
        jmp ldclose
ldnf:   jsr iec_untlk
ldfail: pla
ldclose:
        lda iec_st
        pha
        lda #0
        jsr dos_close
        pla
        sta iec_st
        and #<~ST_EOI
        cmp #1
        rts

ldop:   .byte $8D, $CD          ; STA abs, CMP abs

; The rest of a load in JiffyDOS LOAD mode to dos_beg; C = 1 if the device
; did not take the TALK.
ldjif:  jsr iec_untlk
        lda dos_dev
        jsr iec_talk
        lda #$61
        jsr iec_tksa
        lda iec_st
        cmp #1
        bcs :+
        lda dos_beg
        ldx dos_beg+1
        jsr iec_jload
        sta dos_beg
        stx dos_beg+1
        jsr iec_untlk
        clc
:       rts

; Save dos_beg up to dos_end (exclusive) to the named file.
dos_save:
        lda #1
        jsr dos_open
        bcs svdone
        lda #1
        jsr dos_chkout
        bcs svdone
        lda dos_beg
        jsr iec_ciout
        lda dos_beg+1
        jsr iec_ciout
        jsr wrbody
        lda iec_st
        pha
        lda #1
        jsr dos_close
        pla
        sta iec_st
svdone: lda iec_st
        cmp #1
        rts

; Read the status channel into dos_errbuf.  A = the numeric code (or $FF if
; no device answered), C = 1 for codes 20 and up.
dos_status:
        lda #$0F
        ldy #0
        sty dos_errbuf
        jsr dos_chkin
        bcs stfail
:       jsr dos_getb
        bcs :+
        cmp #$0D
        beq :-
        cpy #ERRMAX
        bcs :-
        sta dos_errbuf,y
        iny
        bne :-
:       lda #0
        sta dos_errbuf,y
        jsr iec_untlk
        lda dos_errbuf
        and #$0F
        asl a
        sta start
        asl a
        asl a
        adc start
        sta start
        lda dos_errbuf+1
        and #$0F
        adc start
        cmp #20
        rts
stfail: lda #$FF
        rts

        .segment "DATA"
dos_dev:
        .byte 8
memop:  lda $FFFF
        rts
nmop:   lda $FFFF,y
        rts

        .segment "BSS"
dos_beg:
        .res 2
dos_end:
        .res 2
dos_errbuf:
        .res ERRMAX + 1
namelen:
        .res 1
reloc:  .res 1
vfy:    .res 1
start:  .res 2
