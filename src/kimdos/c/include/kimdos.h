/* KIMDOS: Commodore serial bus disk access for the KIM-1, llvm-mos C API. */
#ifndef KIMDOS_H
#define KIMDOS_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* assembly routines: they never call back into C */
#define KD_ASM __attribute__((leaf))

#define ST_WTO 0x01 /* a listener did not acknowledge a byte */
#define ST_RTO 0x02 /* the talker sent nothing */
#define ST_VER 0x10 /* verify mismatch */
#define ST_EOI 0x40 /* the last byte read was the end of the data */
#define ST_DNP 0x80 /* no device answered */

extern uint8_t iec_st; /* status bits collected by the bus primitives */
/* bit 0: offer JiffyDOS (default 1); 0 forces the standard protocol.
 * bit 7: set by iec_listen/iec_talk when the device answered */
extern uint8_t iec_jiffy;
extern uint8_t kd_dev; /* device number, default 8 */

/* bus primitives (asm, same semantics as asm/lib/iec.s) */
KD_ASM void iec_listen(uint8_t dev);
KD_ASM void iec_second(uint8_t sa);
KD_ASM void iec_talk(uint8_t dev);
KD_ASM void iec_tksa(uint8_t sa);
KD_ASM void iec_ciout(uint8_t b);
KD_ASM uint8_t iec_acptr(void);
KD_ASM void iec_unlsn(void);
KD_ASM void iec_untlk(void);
/* after TALK and secondary 0x61 to a device in iec_jiffy bit 7: the rest of
 * the file in JiffyDOS LOAD mode to addr up; returns one past the end */
KD_ASM uint16_t iec_jload(uint16_t addr);

/* DOS layer: functions returning uint8_t return 0 on success, else nonzero
 * (iec_st bits or a DOS error code as documented) */
uint8_t kd_open(uint8_t ch, const void *name, uint8_t len);
void kd_close(uint8_t ch);
uint8_t kd_chkin(uint8_t ch);  /* TALK ch */
uint8_t kd_chkout(uint8_t ch); /* LISTEN ch */
int16_t kd_getb(void); /* next byte, -1 once past the end (EOI seen or RTO) */
/* TALK, read up to n bytes or to EOI, UNTALK; returns count; can be called
 * again to continue */
uint16_t kd_read(uint8_t ch, void *buf, uint16_t n);
/* LISTEN, write, UNLISTEN; returns count */
uint16_t kd_write(uint8_t ch, const void *buf, uint16_t n);
/* command on channel 15 (binary safe) */
uint8_t kd_cmd(const void *cmd, uint8_t len);
/* reads channel 15 into buf (48 bytes, zero terminated, CR stripped); returns
 * the numeric code, 0xFF if no device */
uint8_t kd_status(char *buf);
/* sd2iec "P" + chr(0x60|ch) + 4-byte little-endian offset, then kd_status;
 * returns its code */
uint8_t kd_seek(uint8_t ch, uint32_t offset);

/* name raw PETSCII, zero terminated, quotes stripped; type e.g. "PRG" */
typedef struct {
  char name[17];
  char type[4];
  uint16_t blocks;
} kd_dirent;
/* opens "$"+pattern on channel 0 and skips the load address and header line;
 * 0 ok */
uint8_t kd_dir_open(const void *pattern, uint8_t len);
/* 1 with the next file entry, 0 at the end (BLOCKS FREE line or end) */
uint8_t kd_dir_next(kd_dirent *e);
void kd_dir_close(void);
/* addr NULL: to the file's own address; *end = one past last byte; 0 ok */
uint8_t kd_load(const void *name, uint8_t len, uint8_t *addr, uint16_t *end);
uint8_t kd_save(const void *name, uint8_t len, const uint8_t *beg,
                const uint8_t *end);

/* console via the KIM-1 monitor TTY */
KD_ASM void kd_putc(uint8_t c); /* OUTCH */
KD_ASM uint8_t kd_getc(void);   /* GETCH, 7-bit */
KD_ASM void kd_puts(const char *s);

#ifdef __cplusplus
}
#endif

#endif
