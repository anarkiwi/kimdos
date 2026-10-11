/* KIM-1 llvm-mos platform: a RAM image at $2000, the monitor's zero page
 * ($EF-$FF) left alone, a 1K soft stack after the image. Programs may use
 * __kim_end up to $FEFF as free RAM. */

__rc0 = 0x00;
INCLUDE imag-regs.ld
ASSERT(__rc31 == 0x1f, "Inconsistent zero page map.")

MEMORY {
  zp : ORIGIN = __rc31 + 1, LENGTH = 0xEF - (__rc31 + 1)
  ram (rw) : ORIGIN = 0x2000, LENGTH = 0xDF00
}

REGION_ALIAS("c_readonly", ram)
REGION_ALIAS("c_writeable", ram)

SECTIONS { INCLUDE c.ld }

__stack = ALIGN(__heap_start + 0x400, 0x100);
__kim_end = __stack;
ASSERT(__kim_end <= 0xFF00, "Image and stack do not fit below $FF00.")

INPUT(-lexit-custom -linit-stack -lzero-bss)

OUTPUT_FORMAT { TRIM(ram) }
