// 이어폰 링크 프레임 인코더.
#include "earpiece_frame.h"

#include "crc16.h"

size_t ep_encode(uint8_t type, const uint8_t *payload, uint16_t len, uint8_t *out, size_t cap) {
  if (len > EP_MAX_PAYLOAD || cap < (size_t)len + EP_OVERHEAD) return 0;
  out[0] = EP_SYNC0;
  out[1] = EP_SYNC1;
  out[2] = type;
  out[3] = (uint8_t)(len & 0xFF);
  out[4] = (uint8_t)(len >> 8);
  for (uint16_t i = 0; i < len; i++) out[5 + i] = payload[i];
  uint16_t crc = crc16_ccitt_false(out + 2, (size_t)len + 3);
  out[5 + len] = (uint8_t)(crc & 0xFF);
  out[6 + len] = (uint8_t)(crc >> 8);
  return (size_t)len + EP_OVERHEAD;
}
