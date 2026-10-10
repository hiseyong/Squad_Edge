// LED 구현. 코어 variant의 LED_STATE_ON은 이 보드와 반대라 쓰지 않는다(config.h 참고).
#include "leds.h"

#include <Arduino.h>

#include "../../config.h"

static const uint8_t kPins[4] = {PIN_LED1, PIN_LED2, PIN_LED3, PIN_LED4};

typedef struct {
  uint16_t period_ms;  // 0이면 고정
  uint16_t on_ms;
  bool on;             // 고정 상태
  bool level_on;       // 현재 출력 상태
  uint32_t start_ms;
  uint32_t pulse_until;
  bool pulsing;
} led_state_t;

static led_state_t s_led[4];

static void write_led(uint8_t idx, bool on) {
  if (s_led[idx].level_on == on) return;
  s_led[idx].level_on = on;
  digitalWrite(kPins[idx], on ? LED_ON_LEVEL : LED_OFF_LEVEL);
}

static bool desired(uint8_t idx, uint32_t now) {
  led_state_t *l = &s_led[idx];
  if (l->pulsing) {
    if ((int32_t)(l->pulse_until - now) > 0) return true;
    l->pulsing = false;
  }
  if (l->period_ms == 0) return l->on;
  int32_t elapsed = (int32_t)(now - l->start_ms);  // start가 루프 앞 now보다 늦을 수 있음 → 음수면 0
  if (elapsed < 0) elapsed = 0;
  return ((uint32_t)elapsed % l->period_ms) < l->on_ms;
}

void leds_begin() {
  // 코어 initVariant()가 ledOff()로 LOW(이 보드에서는 켜짐)를 걸어 두므로 명시적으로 끈다.
  for (uint8_t i = 0; i < 4; i++) {
    pinMode(kPins[i], OUTPUT);
    digitalWrite(kPins[i], LED_OFF_LEVEL);
    s_led[i] = {0, 0, false, false, 0, 0, false};
  }
}

void leds_set(uint8_t idx, bool on) {
  if (idx >= 4) return;
  s_led[idx].period_ms = 0;
  s_led[idx].on = on;
  write_led(idx, desired(idx, millis()));
}

void leds_blink(uint8_t idx, uint16_t period_ms, uint16_t on_ms) {
  if (idx >= 4 || period_ms == 0) return;
  if (s_led[idx].period_ms == period_ms && s_led[idx].on_ms == on_ms) return;  // 같은 패턴이면 위상 유지
  s_led[idx].period_ms = period_ms;
  s_led[idx].on_ms = on_ms;
  s_led[idx].start_ms = millis();
}

void leds_pulse(uint8_t idx, uint16_t on_ms) {
  if (idx >= 4) return;
  uint32_t now = millis();
  s_led[idx].pulsing = true;
  s_led[idx].pulse_until = now + on_ms;
  write_led(idx, true);
}

void leds_update(uint32_t now_ms) {
  for (uint8_t i = 0; i < 4; i++) write_led(i, desired(i, now_ms));
}
