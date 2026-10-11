; KIMDOS resident image: TTY shell, keypad entries and a jump table onto the
; library for programs that are not linked against it.

        .setcpu "6502"
        .include "kimdos.inc"

LINEMAX = 72

        .segment "CODE"

        jmp shell               ; +0  interactive shell (TTY)
        jmp kload               ; +3  keypad load, name = hex of KIM_ID
        jmp ksave               ; +6  keypad save, name = hex of KIM_ID
        jmp dos_setnam          ; +9
        jmp dos_open            ; +12
        jmp dos_close           ; +15
        jmp dos_chkin           ; +18
        jmp dos_chkout          ; +21
        jmp dos_getb            ; +24
        jmp dos_read            ; +27
        jmp dos_write           ; +30
        jmp dos_load            ; +33
        jmp dos_save            ; +36
        jmp dos_cmd             ; +39
        jmp dos_status          ; +42
        jmp iec_listen          ; +45
        jmp iec_second          ; +48
        jmp iec_talk            ; +51
        jmp iec_tksa            ; +54
        jmp iec_ciout           ; +57
        jmp iec_acptr           ; +60
        jmp iec_unlsn           ; +63
        jmp iec_untlk           ; +66
        .addr dos_dev           ; +69 variable addresses
        .addr iec_st            ; +71
        .addr dos_beg           ; +73
        .addr dos_end           ; +75
        .addr dos_errbuf        ; +77

; ----------------------------------------------------------- keypad entry

; Name the file after KIM_ID as two hex digits, with C = 1 behind "@0:".
kname:  cld
        php
        lda KIM_ID
        lsr a
        lsr a
        lsr a
        lsr a
        jsr hexasc
        sta knm+3
        lda KIM_ID
        jsr hexasc
        sta knm+4
        ldx #<knm
        ldy #>knm
        lda #5
        plp
        bcs :+
        ldx #<(knm + 3)
        ldy #>(knm + 3)
        lda #2
:       jmp dos_setnam

kload:  clc
        jsr kname
        lda #0
        clc
        jsr dos_load
        bcs kerr
        lda dos_beg
        ldx dos_beg+1
        bcc kdone

ksave:  sec
        jsr kname
        lda KIM_SAL
        sta dos_beg
        lda KIM_SAH
        sta dos_beg+1
        lda KIM_EAL
        sta dos_end
        lda KIM_EAH
        sta dos_end+1
        jsr dos_save
        bcs kerr
        jsr dos_status
        bcs kerr
        lda KIM_SAL
        ldx KIM_SAH
        bcc kdone
kerr:   lda #$FF
        tax
kdone:  sta KIM_POINTL
        stx KIM_POINTH
        jmp KIM_START

hexasc: and #$0F
        cmp #10
        bcc :+
        adc #6
:       adc #'0'
        rts

; ------------------------------------------------------------------ shell

shell:  cld
        ldx #<hello
        ldy #>hello
        jsr con_puts
loop:   jsr con_crlf
        lda #'>'
        jsr con_putc
        ldx #0
rdln:   jsr con_getc
        cmp #$0D
        beq rddone
        cmp #$08
        beq rdbs
        cmp #$7F
        beq rdbs
        cmp #' '
        bcc rdln
        cmp #'a'
        bcc :+
        cmp #'z' + 1
        bcs :+
        and #$DF
:       cpx #LINEMAX
        bcs rdln
        sta line,x
        inx
        bne rdln
rdbs:   txa
        beq rdln
        dex
        jmp rdln
rddone: lda #0
        sta line,x
        jsr con_crlf
        ldx #0
        jsr skipsp
        beq loop
        inx
        ldy #NCMDS - 1
:       cmp cmdch,y
        beq :+
        dey
        bpl :-
        jsr syntax
        jmp loop
:       jsr dispatch
        jmp loop

dispatch:
        lda cmdhi,y
        pha
        lda cmdlo,y
        pha
        rts

cmdch:  .byte "$@LVS#Q?"
NCMDS = * - cmdch
.define CMDS c_dir-1, c_dos-1, c_load-1, c_verify-1, c_save-1, c_dev-1, KIM_START-1, c_help-1
cmdlo:  .lobytes CMDS
cmdhi:  .hibytes CMDS

syntax: ldx #<m_syntax
        ldy #>m_syntax
        jmp con_puts

nodev:  ldx #<m_nodev
        ldy #>m_nodev
        jmp con_puts

; $[pattern]
c_dir:  dex
        jsr rest
        lda #0
        jsr dos_open
        bcs nodev
        lda #0
        jsr dos_chkin
        bcs nodev
        jsr dos_getb
        jsr dos_getb
dirln:  jsr dos_getb
        jsr dos_getb
        bcs dirend
        jsr dos_getb
        pha
        jsr dos_getb
        tax
        pla
        bcs dirend
        jsr con_pdec
        lda #' '
:       jsr con_pet
        jsr dos_getb
        bne :-
        jsr con_crlf
        jmp dirln
dirend: jsr iec_untlk
        lda #0
        jmp dos_close

; @[command]
c_dos:  jsr rest
        bcc status
        jsr dos_cmd
status: jsr dos_status
        cmp #$FF
        beq nodev
        ldx #<dos_errbuf
        ldy #>dos_errbuf
        jmp con_puts

; L name[,addr]  V name[,addr]
c_verify:
        lda #1
        .byte $2C
c_load: lda #0
        sta verify
        jsr getname
        bcc serr
        jsr hexarg
        lda num
        sta dos_beg
        lda num+1
        sta dos_beg+1
        lda verify
        bcc :+
        clc
        bcc :++
:       sec
:       jsr dos_load
        bcc :+
        tay
        bmi fnodev
        and #ST_RTO
        bne status
:       lda dos_beg
        ldx dos_beg+1
        sta KIM_POINTL
        stx KIM_POINTH
        jsr con_phex16
        lda #'-'
        jsr con_putc
        lda dos_end
        sec
        sbc #1
        tay
        lda dos_end+1
        sbc #0
        tax
        tya
        jsr con_phex16
        lda iec_st
        and #ST_VER
        beq :+
        ldx #<m_verr
        ldy #>m_verr
        jmp con_puts
:       rts

serr:   jmp syntax
fnodev: jmp nodev

; S name,start,end
c_save: jsr getname
        bcc serr
        jsr hexarg
        bcs serr
        lda num
        sta dos_beg
        lda num+1
        sta dos_beg+1
        jsr hexarg
        bcs serr
        lda num
        clc
        adc #1
        sta dos_end
        lda num+1
        adc #0
        sta dos_end+1
        jsr dos_save
        lda iec_st
        bmi fnodev
        jmp status

; #[device], decimal
c_dev:  jsr skipsp
        beq :++
        jsr decval
        bcs serr
        sta num
        inx
        lda line,x
        jsr decval
        bcs :+
        sta num+1
        lda num
        asl a
        sta num
        asl a
        asl a
        adc num
        adc num+1
        sta num
        inx
:       lda line,x
        bne serr
        lda num
        cmp #4
        bcc serr
        cmp #31
        bcs serr
        sta dos_dev
:       lda dos_dev
        ldx #0
        jmp con_pdec

c_help: ldx #<m_help
        ldy #>m_help
        jmp con_puts

; ---------------------------------------------------------------- parsing

; Name argument at X, quoted or up to a comma, set with dos_setnam.
; C = 0 if empty.
getname:
        jsr skipsp
        ldy #','
        cmp #'"'
        bne :+
        inx
        tay
:       stx tmp
        sty tmp+1
:       lda line,x
        beq gnset
        cmp tmp+1
        beq :+
        inx
        bne :-
:       jsr gnset
        php
        lda line,x
        cmp #'"'
        bne :+
        inx
:       plp
        rts

; Rest of the line from X as the name; C = 0 if empty.
rest:   stx tmp
:       lda line,x
        beq gnset
        inx
        bne :-

; Name from line+tmp up to X; C = 0 if empty.
gnset:  stx tmp+1
        txa
        sec
        sbc tmp
        pha
        lda tmp
        clc
        adc #<line
        tax
        lda #>line
        adc #0
        tay
        pla
        jsr dos_setnam
        ldx tmp+1
        cmp #1
        rts

; ,hex argument at X into num.  C = 1 if absent; a malformed one ends the
; command with a syntax error.
hexarg: jsr skipsp
        cmp #','
        bne hxnone
        inx
        jsr skipsp
        lda #0
        sta num
        sta num+1
        tay
:       lda line,x
        jsr hexval
        bcs :+
        asl num
        rol num+1
        asl num
        rol num+1
        asl num
        rol num+1
        asl num
        rol num+1
        ora num
        sta num
        inx
        iny
        bne :-
:       tya
        beq :+
        clc
        rts
:       pla
        pla
        jmp syntax
hxnone: sec
        rts

hexval: cmp #'A'
        bcc decval
        cmp #'F' + 1
        bcs :+
        sbc #'A' - 11
        clc
        rts
decval: cmp #'0'
        bcc :+
        cmp #'9' + 1
        bcs :+
        and #$0F
        rts
:       sec
        rts

skipsp: lda line,x
        cmp #' '
        bne :+
        inx
        bne skipsp
:       cmp #0
        rts

hello:  .byte $0D, $0A, "KIMDOS", 0
m_syntax:
        .byte "?SYNTAX", 0
m_nodev:
        .byte "?DEVICE NOT PRESENT", 0
m_verr: .byte " ?VERIFY", 0
m_help: .byte "$[PAT]       DIRECTORY", $0D, $0A
        .byte "@[CMD]       STATUS/COMMAND", $0D, $0A
        .byte "L F[,ADDR]   LOAD", $0D, $0A
        .byte "V F[,ADDR]   VERIFY", $0D, $0A
        .byte "S F,BEG,END  SAVE", $0D, $0A
        .byte "#[DEV]       DEVICE", $0D, $0A
        .byte "Q            MONITOR", 0

        .segment "DATA"
knm:    .byte "@0:00"

        .segment "BSS"
verify: .res 1
num:    .res 2
tmp:    .res 2
line:   .res LINEMAX + 1
