#include "kdint.h"

#define ERRMAX 47

uint8_t kd_dev = 8;

static uint8_t listen_sa(uint8_t sa) {
  iec_st = 0;
  iec_listen(kd_dev);
  if (!(iec_st & ST_DNP))
    iec_second(sa);
  return iec_st;
}

static void send(const uint8_t *p, uint8_t n) {
  while (n--)
    iec_ciout(*p++);
}

static const uint8_t *put(const uint8_t *p, const uint8_t *end) {
  while (!iec_st && p < end)
    iec_ciout(*p++);
  iec_unlsn();
  return p;
}

uint8_t kd_openp(uint8_t ch, uint8_t pre, const uint8_t *name, uint8_t len) {
  if (listen_sa(0xF0 | ch) & ST_DNP)
    return iec_st;
  if (pre)
    iec_ciout(pre);
  send(name, len);
  iec_unlsn();
  return iec_st;
}

uint8_t kd_open(uint8_t ch, const void *name, uint8_t len) {
  return kd_openp(ch, 0, name, len);
}

void kd_close(uint8_t ch) {
  listen_sa(0xE0 | ch);
  iec_unlsn();
}

uint8_t kd_chkout(uint8_t ch) { return listen_sa(0x60 | ch); }

__attribute__((noinline)) uint8_t kd_chkin(uint8_t ch) {
  iec_st = 0;
  iec_talk(kd_dev);
  iec_tksa(0x60 | ch);
  return iec_st;
}

__attribute__((noinline)) int16_t kd_getb(void) {
  if (iec_st & (ST_EOI | ST_RTO))
    return -1;
  uint8_t b = iec_acptr();
  return iec_st & ST_RTO ? -1 : b;
}

uint16_t kd_read(uint8_t ch, void *buf, uint16_t n) {
  uint8_t *p = buf;
  uint16_t i = 0;
  if (!(kd_chkin(ch) & ST_DNP)) {
    for (int16_t c; i != n && (c = kd_getb()) >= 0;)
      p[i++] = c;
    iec_untlk();
  }
  return i;
}

uint16_t kd_write(uint8_t ch, const void *buf, uint16_t n) {
  const uint8_t *p = buf;
  if (kd_chkout(ch) & ST_DNP)
    return 0;
  return put(p, p + n) - p;
}

uint8_t kd_cmd(const void *cmd, uint8_t len) {
  if (!(kd_chkout(15) & ST_DNP)) {
    send(cmd, len);
    iec_unlsn();
  }
  return iec_st;
}

uint8_t kd_status(char *buf) {
  uint8_t i = 0;
  int16_t c;
  buf[0] = buf[1] = 0;
  if (kd_chkin(15) & ST_DNP)
    return 0xFF;
  while ((c = kd_getb()) >= 0)
    if (c != '\r' && i != ERRMAX)
      buf[i++] = c;
  buf[i] = 0;
  iec_untlk();
  return (buf[0] & 15) * 10 + (buf[1] & 15);
}

uint8_t kd_seek(uint8_t ch, uint32_t offset) {
  uint8_t cmd[6] = {'P',         0x60 | ch,    offset,
                    offset >> 8, offset >> 16, offset >> 24};
  char st[ERRMAX + 1];
  kd_cmd(cmd, sizeof cmd);
  return kd_status(st);
}

uint8_t kd_load(const void *name, uint8_t len, uint8_t *addr, uint16_t *end) {
  uint8_t st;
  if (!(kd_open(0, name, len) & ST_DNP) && !(kd_chkin(0) & ST_DNP)) {
    uint8_t lo = kd_getb();
    uint16_t at = lo | (uint8_t)kd_getb() << 8;
    if (!(iec_st & ST_RTO)) {
      uint8_t *p = addr ? addr : (uint8_t *)at;
      if (iec_jiffy & 0x80 && !iec_st && *(const uint8_t *)name != '$') {
        iec_untlk();
        iec_talk(kd_dev);
        iec_tksa(0x61);
        if (!iec_st)
          p = (uint8_t *)iec_jload((uint16_t)p);
      } else {
        for (int16_t c; (c = kd_getb()) >= 0;)
          *p++ = c;
      }
      if (end)
        *end = (uint16_t)p;
    }
    iec_untlk();
  }
  st = iec_st;
  kd_close(0);
  iec_st = st;
  return st & ~ST_EOI;
}

uint8_t kd_save(const void *name, uint8_t len, const uint8_t *beg,
                const uint8_t *end) {
  uint8_t st;
  if (kd_open(1, name, len) & ST_DNP || kd_chkout(1) & ST_DNP)
    return iec_st;
  iec_ciout((uint16_t)beg);
  iec_ciout((uint16_t)beg >> 8);
  put(beg, end);
  st = iec_st;
  kd_close(1);
  iec_st = st;
  return st;
}
