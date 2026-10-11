#ifndef KDINT_H
#define KDINT_H

#include "kimdos.h"

/* OPEN ch with an optional leading byte pre (0 for none) before the name. */
uint8_t kd_openp(uint8_t ch, uint8_t pre, const uint8_t *name, uint8_t len);

#endif
