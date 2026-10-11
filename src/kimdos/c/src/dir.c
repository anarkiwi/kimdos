#include "kdint.h"

/* Next listing byte; 0 past the end, which also ends a line or the listing. */
__attribute__((noinline)) static uint8_t next(void) {
  int16_t c = kd_getb();
  return c < 0 ? 0 : c;
}

uint8_t kd_dir_open(const void *pattern, uint8_t len) {
  if (kd_openp(0, '$', pattern, len) & ST_DNP || kd_chkin(0) & ST_DNP)
    return iec_st;
  for (uint8_t n = 6; n; --n)
    next();
  while (next())
    ;
  iec_untlk();
  return iec_st & ~ST_EOI;
}

uint8_t kd_dir_next(kd_dirent *e) {
  uint8_t q = 0, n = 0, t = 0, c;
  if (kd_chkin(0) & ST_DNP)
    return 0;
  if (next() | next()) {
    c = next();
    e->blocks = c | next() << 8;
    while ((c = next())) {
      if (c == '"')
        ++q;
      else if (q == 1) {
        if (n < 16)
          e->name[n++] = c;
      } else if (q == 2 && c != ' ' && c != '*' && t < 3)
        e->type[t++] = c;
    }
    e->name[n] = 0;
    e->type[t] = 0;
  }
  iec_untlk();
  return q > 1;
}

void kd_dir_close(void) { kd_close(0); }
