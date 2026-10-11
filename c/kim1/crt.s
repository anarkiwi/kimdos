; KIM-1 llvm-mos start-up and exit: decimal mode off, exit to the monitor.

        .section .init.050,"ax",@progbits
        cld

        .section .text._Exit,"ax",@progbits
        .globl _Exit
_Exit:  jmp 0x1C4F
