; Console over the KIM-1 monitor's TTY routines.  OUTCH and GETCH clobber
; A, X, Y and the monitor's zero page ($EF-$FF), none of which the llvm-mos
; calling convention asks a callee to preserve.

OUTCH   = 0x1EA0
GETCH   = 0x1E5A

        .globl kd_putc, kd_getc, kd_puts

        .section .text.kd_putc,"ax",@progbits
kd_putc:
        jmp OUTCH

        .section .text.kd_getc,"ax",@progbits
kd_getc:
        jsr GETCH
        and #0x7F
        rts

; String pointer in __rc2/__rc3, advanced past 256-byte pages as it goes.
        .section .text.kd_puts,"ax",@progbits
kd_puts:
        ldy #0
1:      lda (__rc2),y
        beq 2f
        sty savy
        jsr OUTCH
        ldy savy
        iny
        bne 1b
        inc __rc3
        bne 1b
2:      rts

        .section .bss.kd_puts,"aw",@nobits
savy:   .zero 1
