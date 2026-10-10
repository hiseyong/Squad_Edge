// 조이스틱 구현. 방향 계산은 core/geo의 geo_joy_direction(호스트 테스트됨).
#include "joystick.h"

#include <Arduino.h>

#include "../../config.h"

static int16_t s_x = 0, s_y = 0;
static int32_t s_sum_x = 0, s_sum_y = 0;
static uint16_t s_cal_n = 0;
static bool s_ready = false;
static int16_t s_cx = 0, s_cy = 0;
// 방향별 최대 거리(원시 축 기준). 보정 때 ADC 끝까지 거리로 초기화, 그보다 멀리 가면 늘어남.
static int16_t s_mx_pos = 512, s_mx_neg = 512, s_my_pos = 512, s_my_neg = 512;
static uint32_t s_t_start = 0, s_t_last = 0;

void joystick_begin() {
#if HAS_JOYSTICK
  analogReference(AR_VDD4);  // 0~VDD(3.3V) 전체 범위. 기본(내부 3.0V)이면 끝부분이 잘린다
  analogReadResolution(10);
  s_t_start = millis();
  s_t_last = s_t_start - JOY_SAMPLE_INTERVAL_MS;
#endif
}

void joystick_update(uint32_t now) {
#if HAS_JOYSTICK
  if ((uint32_t)(now - s_t_last) < JOY_SAMPLE_INTERVAL_MS) return;
  s_t_last = now;
  s_x = (int16_t)analogRead(PIN_JOY_X);
  s_y = (int16_t)analogRead(PIN_JOY_Y);
  if (!s_ready) {
    // 부팅 후 JOY_CENTER_CAL_MS 동안 평균 = 중앙값(사용자는 부팅 시 조이스틱을 건드리지 않는다)
    s_sum_x += s_x;
    s_sum_y += s_y;
    s_cal_n++;
    if ((uint32_t)(now - s_t_start) >= JOY_CENTER_CAL_MS && s_cal_n > 0) {
      s_cx = (int16_t)(s_sum_x / s_cal_n);
      s_cy = (int16_t)(s_sum_y / s_cal_n);
      s_mx_pos = (int16_t)(JOY_ADC_MAX - s_cx);
      s_mx_neg = s_cx;
      s_my_pos = (int16_t)(JOY_ADC_MAX - s_cy);
      s_my_neg = s_cy;
      s_ready = true;
    }
    return;
  }
  // 방향별 최대 거리 학습(늘어나기만 함)
  int16_t dx = (int16_t)(s_x - s_cx), dy = (int16_t)(s_y - s_cy);
  if (dx > s_mx_pos) s_mx_pos = dx;
  if (-dx > s_mx_neg) s_mx_neg = (int16_t)-dx;
  if (dy > s_my_pos) s_my_pos = dy;
  if (-dy > s_my_neg) s_my_neg = (int16_t)-dy;
#else
  (void)now;
#endif
}

bool joystick_ready() { return s_ready; }

geo_joy_t joystick_direction() {
  geo_joy_t none = {0, GEO_DIST_NONE, 0};
  if (!HAS_JOYSTICK || !s_ready) return none;
  int32_t dx = s_x - s_cx, dy = s_y - s_cy;
  // 방향별 정규화: 편차의 부호에 맞는 최대 거리(중앙이 치우쳐 +/− 거리가 다름)
  int32_t mx = dx >= 0 ? s_mx_pos : s_mx_neg;
  int32_t my = dy >= 0 ? s_my_pos : s_my_neg;
#if JOY_SWAP_XY
  // 원시 X = 앞(12시) 성분, 원시 Y = 오른쪽(3시) 성분 → geo_joy_direction(오른쪽, 앞) 순서로 교환
  return geo_joy_direction(dy, dx, my, mx, JOY_INVERT_X, JOY_INVERT_Y, JOY_ROTATE_DEG, JOY_DEADZONE_PCT, JOY_FAR_PCT);
#else
  return geo_joy_direction(dx, dy, mx, my, JOY_INVERT_X, JOY_INVERT_Y, JOY_ROTATE_DEG, JOY_DEADZONE_PCT, JOY_FAR_PCT);
#endif
}

void joystick_raw(joy_raw_t *out) {
  out->x = s_x;
  out->y = s_y;
  out->cx = s_cx;
  out->cy = s_cy;
  out->mx_pos = s_mx_pos;
  out->mx_neg = s_mx_neg;
  out->my_pos = s_my_pos;
  out->my_neg = s_my_neg;
#if HAS_JOYSTICK
  out->sw = digitalRead(PIN_JOY_SW) == JOY_SW_PRESSED_LEVEL;
#else
  out->sw = false;
#endif
}
