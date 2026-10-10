// 버튼 구현: 디바운스 → 조합 검사 → 제스처 판정 → 이벤트 링 버퍼.
#include "buttons.h"

#include <Arduino.h>

#include "../../config.h"
#include "../core/gesture.h"

#define EV_SLOTS 16  // 2의 거듭제곱

static const uint8_t kPins[BTN_COUNT] = {PIN_BUTTON1, PIN_BUTTON2, PIN_BUTTON3, PIN_BUTTON4, PIN_JOY_SW};
static const uint8_t kPressedLevel[BTN_COUNT] = {BUTTON_PRESSED_LEVEL, BUTTON_PRESSED_LEVEL, BUTTON_PRESSED_LEVEL,
                                                 BUTTON_PRESSED_LEVEL, JOY_SW_PRESSED_LEVEL};

typedef struct {
  bool stable;      // 디바운스된 눌림 상태
  bool raw_last;
  uint32_t t_raw;   // raw가 마지막으로 바뀐 시각
} debounce_t;

static debounce_t s_db[BTN_COUNT];
static gest_t s_gest[BTN_COUNT];
// 두 버튼 조합: 동시에 눌린 순간 두 제스처를 취소(단독 길게 판정 오발 방지), hold_ms 유지 시 이벤트 1회
typedef struct {
  uint8_t a, b;
  uint16_t hold_ms;
  uint8_t event;
  bool active, fired;
  uint32_t t;
} combo_t;

static combo_t s_combo[3] = {
  {BTN_1, BTN_4, CALIB_COMBO_HOLD_MS, BEV_COMBO_CALIB, false, false, 0},
  {BTN_1, BTN_2, MODE_COMBO_HOLD_MS, BEV_COMBO_MODE, false, false, 0},
  {BTN_3, BTN_4, TXPWR_COMBO_HOLD_MS, BEV_COMBO_TXPWR, false, false, 0},
};

static button_event_t s_ev[EV_SLOTS];
static uint8_t s_ev_head = 0, s_ev_tail = 0;

static void push(uint8_t btn, uint8_t kind, uint8_t count, bool first) {
  uint8_t next = (uint8_t)((s_ev_head + 1) & (EV_SLOTS - 1));
  if (next == s_ev_tail) return;  // 가득 차면 버림(루프가 매번 비우므로 정상 동작에서는 없음)
  s_ev[s_ev_head] = {btn, kind, count, first};
  s_ev_head = next;
}

static uint8_t used_count() { return HAS_JOYSTICK ? BTN_COUNT : BTN_JOY; }

void buttons_begin() {
  for (uint8_t i = 0; i < used_count(); i++) {
    pinMode(kPins[i], INPUT_PULLUP);
    s_db[i] = {false, false, 0};
  }
  gest_init(&s_gest[BTN_1], GEST_MULTI, 0);
  gest_init(&s_gest[BTN_2], GEST_SDL, PRESS_LONG_MIN_MS);
  gest_init(&s_gest[BTN_3], GEST_SL, PRESS_LONG_MIN_MS);
  gest_init(&s_gest[BTN_4], GEST_SDL, PRESS_SELF_CASUALTY_MS);
  gest_init(&s_gest[BTN_JOY], GEST_SL, PRESS_LONG_MIN_MS);
}

static void debounce(uint8_t i, uint32_t now) {
  bool raw = digitalRead(kPins[i]) == kPressedLevel[i];
  if (raw != s_db[i].raw_last) {
    s_db[i].raw_last = raw;
    s_db[i].t_raw = now;
  } else if (raw != s_db[i].stable && (uint32_t)(now - s_db[i].t_raw) >= DEBOUNCE_MS) {
    s_db[i].stable = raw;
  }
}

static void check_combo(uint32_t now) {
  for (uint8_t i = 0; i < 3; i++) {
    combo_t *c = &s_combo[i];
    bool a = s_db[c->a].stable, b = s_db[c->b].stable;
    if (a && b) {
      if (!c->active) {
        c->active = true;
        c->fired = false;
        c->t = now;
        gest_cancel(&s_gest[c->a], true);
        gest_cancel(&s_gest[c->b], true);
        push(c->a, BEV_COMBO_START, i, false);
      } else if (!c->fired && (int32_t)(now - c->t) >= (int32_t)c->hold_ms) {
        c->fired = true;
        push(c->a, c->event, i, false);
      }
    } else if (!a && !b) {
      c->active = false;
    }
  }
}

void buttons_update(uint32_t now) {
  uint8_t n = used_count();
  for (uint8_t i = 0; i < n; i++) debounce(i, now);
  check_combo(now);
  for (uint8_t i = 0; i < n; i++) {
    gest_out_t o = gest_update(&s_gest[i], s_db[i].stable, now);
    // result가 먼저(이전 제스처), 그다음 눌림 시작
    switch (o.result) {
      case GEV_SHORT: push(i, BEV_SHORT, 0, false); break;
      case GEV_DOUBLE: push(i, BEV_DOUBLE, 0, false); break;
      case GEV_LONG: push(i, BEV_LONG, 0, false); break;
      case GEV_MULTI_DONE: push(i, BEV_MULTI_DONE, o.count, false); break;
      case GEV_IGNORED: push(i, BEV_IGNORED, 0, false); break;
      default: break;
    }
    if (o.pressed) push(i, BEV_PRESS, o.count, o.first);
  }
}

bool buttons_next(button_event_t *ev) {
  if (s_ev_tail == s_ev_head) return false;
  *ev = s_ev[s_ev_tail];
  s_ev_tail = (uint8_t)((s_ev_tail + 1) & (EV_SLOTS - 1));
  return true;
}
