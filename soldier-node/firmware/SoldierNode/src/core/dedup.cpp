// 고정 크기 링 버퍼. 꽉 차면 가장 오래된 항목을 덮어쓴다.
#include "dedup.h"

void dedup_init(dedup_t *d, uint32_t window_ms) {
  d->count = 0;
  d->next = 0;
  d->window_ms = window_ms;
}

bool dedup_seen(dedup_t *d, uint8_t src, uint8_t seq, uint16_t sig, uint32_t now) {
  for (uint8_t i = 0; i < d->count; i++) {
    if (d->src[i] != src || d->seq[i] != seq) continue;
    if (d->sig[i] == sig && (int32_t)(now - d->t[i]) < (int32_t)d->window_ms) return true;
    // 같은 (src, seq)지만 내용이 다르거나 오래됨 → 새 프레임. 그 자리를 갱신
    d->sig[i] = sig;
    d->t[i] = now;
    return false;
  }
  d->src[d->next] = src;
  d->seq[d->next] = seq;
  d->sig[d->next] = sig;
  d->t[d->next] = now;
  d->next = (uint8_t)((d->next + 1) % DEDUP_SIZE);
  if (d->count < DEDUP_SIZE) d->count++;
  return false;
}
