// 버튼 제스처 판정 구현.
#include "gesture.h"

#define S_IDLE      0
#define S_DOWN      1  // 첫 눌림 유지 중
#define S_WAIT2     2  // SDL: 짧게 뗀 뒤 두 번째 눌림 대기
#define S_DONE_HELD 3  // 결과 확정(또는 취소) 후 뗄 때까지 무시
#define S_MULTI     4  // MULTI: 연타 진행 중

void gest_init(gest_t *g, uint8_t kind, uint16_t long_ms) {
  g->kind = kind;
  g->long_ms = long_ms;
  g->state = S_IDLE;
  g->down = false;
  g->t_down = 0;
  g->t_up = 0;
  g->count = 0;
}

static gest_out_t update_multi(gest_t *g, bool press, bool release, uint32_t now) {
  gest_out_t o = {false, false, 0, GEV_NONE};
  if (g->state == S_DONE_HELD) {  // 취소됨: 뗄 때까지 무시
    if (release) g->state = S_IDLE;
    return o;
  }
  if (press) {
    o.pressed = true;
    o.first = (g->count == 0);
    if (g->count < 255) g->count++;
    o.count = g->count;
    g->state = S_MULTI;
    g->t_down = now;
  }
  if (release) g->t_up = now;
  if (g->state == S_MULTI && !g->down && (uint32_t)(now - g->t_up) >= GEST_MULTI_TIMEOUT_MS) {
    o.result = GEV_MULTI_DONE;
    o.count = g->count;
    g->count = 0;
    g->state = S_IDLE;
  }
  return o;
}

static gest_out_t update_sdl_sl(gest_t *g, bool press, uint32_t now) {
  gest_out_t o = {false, false, 0, GEV_NONE};
  switch (g->state) {
    case S_IDLE:
      if (press) {
        o.pressed = true;
        o.first = true;
        g->t_down = now;
        g->state = S_DOWN;
      }
      break;
    case S_DOWN:
      if (g->down) {
        if ((uint32_t)(now - g->t_down) >= g->long_ms) {
          o.result = GEV_LONG;
          g->state = S_DONE_HELD;
        }
      } else {
        uint32_t dur = now - g->t_down;
        if (dur >= GEST_SHORT_MAX_MS) {
          o.result = GEV_IGNORED;
          g->state = S_IDLE;
        } else if (g->kind == GEST_SDL) {
          g->t_up = now;
          g->state = S_WAIT2;
        } else {
          o.result = GEV_SHORT;
          g->state = S_IDLE;
        }
      }
      break;
    case S_WAIT2:
      if ((uint32_t)(now - g->t_up) < GEST_DOUBLE_GAP_MS) {
        if (press) {
          o.pressed = true;
          o.first = false;
          o.result = GEV_DOUBLE;
          g->state = S_DONE_HELD;
        }
      } else {
        o.result = GEV_SHORT;  // 400ms 지연 확정
        g->state = S_IDLE;
        if (press) {           // 같은 호출에 새 제스처 시작
          o.pressed = true;
          o.first = true;
          g->t_down = now;
          g->state = S_DOWN;
        }
      }
      break;
    case S_DONE_HELD:
    default:
      if (!g->down) g->state = S_IDLE;
      break;
  }
  return o;
}

gest_out_t gest_update(gest_t *g, bool down, uint32_t now) {
  bool press = down && !g->down;
  bool release = !down && g->down;
  g->down = down;
  if (g->kind == GEST_MULTI) return update_multi(g, press, release, now);
  return update_sdl_sl(g, press, now);
}

void gest_cancel(gest_t *g, bool down) {
  g->down = down;
  g->count = 0;
  g->state = down ? S_DONE_HELD : S_IDLE;
}

bool gest_idle(const gest_t *g) {
  return g->state == S_IDLE && g->count == 0;
}
