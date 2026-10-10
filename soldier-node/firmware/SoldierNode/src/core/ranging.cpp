// RSSI 이동 중앙값 구현.
#include "ranging.h"

#include <math.h>

void ranging_init(ranging_t *r, uint32_t stale_ms) {
  for (int i = 0; i <= RANGING_IDS; i++) {
    r->p[i].count = 0;
    r->p[i].next = 0;
    r->p[i].last_t = 0;
  }
  r->stale_ms = stale_ms;
}

void ranging_add(ranging_t *r, uint8_t peer_id, int8_t rssi, uint32_t now) {
  if (peer_id > RANGING_IDS) return;
  ranging_peer_t *p = &r->p[peer_id];
  if (p->count && (int32_t)(now - p->last_t) > (int32_t)r->stale_ms) {  // 오래 끊겼다 다시 들림 → 새로 시작
    p->count = 0;
    p->next = 0;
  }
  p->rssi[p->next] = rssi;
  p->next = (uint8_t)((p->next + 1) % RANGING_WINDOW);
  if (p->count < RANGING_WINDOW) p->count++;
  p->last_t = now;
}

int8_t ranging_median(const int8_t *v, uint8_t n) {
  if (n == 0) return 0;
  int8_t s[RANGING_WINDOW];
  if (n > RANGING_WINDOW) n = RANGING_WINDOW;
  for (uint8_t i = 0; i < n; i++) {  // 삽입 정렬(최대 15개)
    int8_t x = v[i];
    int j = i - 1;
    while (j >= 0 && s[j] > x) {
      s[j + 1] = s[j];
      j--;
    }
    s[j + 1] = x;
  }
  if (n & 1) return s[n / 2];
  return (int8_t)(((int)s[n / 2 - 1] + (int)s[n / 2]) / 2);
}

uint8_t ranging_collect(ranging_t *r, uint8_t self_id, uint32_t now, ranging_entry_t *out, uint8_t max) {
  uint8_t n = 0;
  for (uint8_t id = 0; id <= RANGING_IDS && n < max; id++) {
    ranging_peer_t *p = &r->p[id];
    if (id == self_id || p->count == 0) continue;
    if ((int32_t)(now - p->last_t) > (int32_t)r->stale_ms) {
      p->count = 0;
      p->next = 0;
      continue;
    }
    out[n].peer_id = id;
    out[n].rssi_avg = ranging_median(p->rssi, p->count);
    out[n].samples = p->count;
    n++;
  }
  return n;
}

float ranging_distance_m(float rssi, float p1m, float n) {
  if (n <= 0.0f) return 0.0f;
  return powf(10.0f, (p1m - rssi) / (10.0f * n));
}
