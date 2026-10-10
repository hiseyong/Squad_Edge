// 미확인 명령 타이머 구현.
#include "unack.h"

void unack_init(unack_t *u, uint32_t escalate_ms) {
  u->active = false;
  u->fast = false;
  u->since = 0;
  u->escalate_ms = escalate_ms;
}

void unack_start(unack_t *u, uint32_t now) {
  u->active = true;
  u->fast = false;
  u->since = now;
}

void unack_clear(unack_t *u) {
  u->active = false;
  u->fast = false;
}

bool unack_poll(unack_t *u, uint32_t now) {
  if (!u->active || u->fast) return false;
  int32_t elapsed = (int32_t)(now - u->since);  // since가 now보다 늦으면 음수 → 아직 아님
  if (elapsed < (int32_t)u->escalate_ms) return false;
  u->fast = true;
  return true;
}
