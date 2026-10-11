/* Exercises the KIMDOS C library; prints KEY=VALUE lines for tests/. */
#include <string.h>

#include "kimdos.h"

extern char __kim_end[];

static uint8_t buf[640];
static char text[48];

static void hex(uint16_t v) {
  for (int8_t s = 12; s >= 0; s -= 4)
    kd_putc("0123456789ABCDEF"[(v >> s) & 15]);
}

static void key(const char *k, uint16_t v) {
  kd_puts(k);
  kd_putc('=');
  hex(v);
  kd_putc(' ');
}

static void eol(void) {
  kd_putc('\r');
  kd_putc('\n');
}

static void status(void) {
  key("ST", kd_status(text));
  kd_puts(text);
  eol();
}

static uint16_t sum(const uint8_t *p, uint16_t n) {
  uint16_t s = 0;
  while (n--)
    s = (s << 1 | s >> 15) ^ *p++;
  return s;
}

static void dir(const char *pat) {
  kd_dirent e;
  key("DIR", kd_dir_open(pat, strlen(pat)));
  eol();
  while (kd_dir_next(&e)) {
    kd_puts(e.name);
    kd_putc(',');
    kd_puts(e.type);
    kd_putc(',');
    hex(e.blocks);
    eol();
  }
  kd_dir_close();
}

int main(void) {
  uint16_t n, end;
  static const uint8_t msg[] = "HELLO,\rWORLD";

  key("END", (uint16_t)__kim_end);
  eol();
  status();

  key("OPEN", kd_open(2, "DATA,S,R", 8));
  n = kd_read(2, buf, 100);
  key("R1", n);
  n += kd_read(2, buf + n, sizeof buf - n);
  key("R2", n);
  key("R3", kd_read(2, buf, 10));
  key("SUM", sum(buf, n));
  eol();
  key("SEEK", kd_seek(2, 0x12C));
  key("R4", kd_read(2, buf, 4));
  key("B", buf[0] << 8 | buf[3]);
  key("SEEK", kd_seek(2, 0x10000));
  key("SEEK", kd_seek(9, 0));
  kd_close(2);
  eol();

  key("OPEN", kd_open(3, "@0:OUT,S,W", 10));
  key("W", kd_write(3, msg, 7));
  key("W", kd_write(3, msg + 7, sizeof msg - 7));
  kd_close(3);
  eol();
  status();
  kd_open(4, "OUT", 3);
  memset(buf, 0, sizeof buf);
  key("RB", kd_read(4, buf, sizeof buf));
  key("EQ", !memcmp(buf, msg, sizeof msg));
  kd_close(4);
  eol();

  key("CMD", kd_cmd("R:NEW=OUT", 9));
  status();
  dir("");
  dir("0:P*");

  key("LOAD", kd_load("PROG", 4, 0, &end));
  key("AT", end);
  key("SUM", sum((uint8_t *)0x6000, end - 0x6000));
  key("LOAD", kd_load("PROG", 4, buf, &end));
  key("AT", end - (uint16_t)buf);
  eol();
  key("SAVE", kd_save("COPY", 4, buf, buf + 0x10));
  key("SAVE", kd_save("COPY", 4, buf, buf + 0x10));
  status();
  key("LOAD", kd_load("NOPE", 4, buf, &end));
  status();
  key("CHKIN", kd_chkin(7));
  key("GETB", kd_getb());
  iec_untlk();
  eol();
  kd_dev = 9;
  key("DEV9", kd_status(text));
  kd_dev = 8;
  key("KEY", kd_getc());
  eol();
  kd_puts("BYE");
  eol();
  return 0;
}
