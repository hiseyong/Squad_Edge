// 조이스틱 X/Y (CLAUDE.md §6.1): 부팅 200ms 중앙값 보정, 축별 최대 거리 학습, 방향(시계)·기울기 구간.
// HAS_JOYSTICK = 0이면 아날로그 핀을 전혀 읽지 않고 항상 "방향 없음"을 돌려준다.
// SW(누름)는 hal/buttons가 BTN_JOY로 처리한다.
#pragma once
#include <stdbool.h>
#include <stdint.h>

#include "../core/geo.h"

typedef struct {
  int16_t x, y;    // 최근 원시값(10bit, 0~1023)
  int16_t cx, cy;  // 중앙값(보정 전이면 0)
  int16_t mx_pos, mx_neg, my_pos, my_neg;  // 방향별 최대 거리(원시 축 기준)
  bool sw;         // SW 원시 레벨이 눌림 레벨인지(디바운스 전)
} joy_raw_t;

void joystick_begin();
void joystick_update(uint32_t now_ms);
bool joystick_ready();          // 중앙값 보정 완료
geo_joy_t joystick_direction(); // 현재 방향. 없음/미보정/미연결이면 clock 0, dist GEO_DIST_NONE
void joystick_raw(joy_raw_t *out);
