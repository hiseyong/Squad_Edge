// 모드별 송신 통계 구현.
#include "stats.h"

static uint16_t s_frames[3];
static uint32_t s_bytes[3];

void stats_on_tx(uint8_t mode, uint16_t bytes) {
  if (mode > 2) return;
  if (s_frames[mode] < 0xFFFF) s_frames[mode]++;
  s_bytes[mode] += bytes;
}

void stats_fill(msg_stats_t *out) {
  for (int i = 0; i < 3; i++) {
    out->tx_frames[i] = s_frames[i];
    out->tx_bytes[i] = s_bytes[i];
  }
}
