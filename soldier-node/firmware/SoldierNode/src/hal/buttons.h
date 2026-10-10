// 온보드 버튼 1~4 + 조이스틱 SW: 디바운스(20ms) + 제스처 판정(core/gesture) + 버튼1+버튼4 조합.
// (CLAUDE.md §6.1, 프로토콜 §9.1). loop 태스크에서 buttons_update()를 자주 호출하고 이벤트를 꺼낸다.
#pragma once
#include <stdbool.h>
#include <stdint.h>

#define BTN_1    0  // 연타: 적 발견 N명
#define BTN_2    1  // 짧게/두 번/길게(1s): 징후/부상자 발견/폭발물
#define BTN_3    2  // 짧게/길게(1s): ACK/수행 불가
#define BTN_4    3  // 짧게/두 번/길게(2s): 이상 없음/탄약·화기/본인 부상
#define BTN_JOY  4  // 조이스틱 SW 짧게/길게(1s): 다시 듣기/모드 순환 (HAS_JOYSTICK일 때만)
#define BTN_COUNT 5

#define BEV_PRESS       1  // 눌림 시작(first = 제스처의 첫 눌림 → 이때 조이스틱 방향을 잡는다)
#define BEV_SHORT       2
#define BEV_DOUBLE      3
#define BEV_LONG        4
#define BEV_MULTI_DONE  5  // 버튼1 연타 확정(count)
#define BEV_IGNORED     6  // 짧게도 길게도 아닌 길이
#define BEV_COMBO_START 7  // 조합 동시 눌림 시작(두 버튼의 진행 중 제스처 취소). count = 조합 번호(BCOMBO_*)
#define BEV_COMBO_CALIB 8  // 버튼1+버튼4 3초 → 방위 센서 보정
#define BEV_COMBO_MODE  9  // 버튼1+버튼2 2초 → EMCON 모드 순환(조이스틱 없는 보드용, 모든 보드에서 동작)
#define BEV_COMBO_TXPWR 10 // 버튼3+버튼4 2초 → 최소 모드 송신 출력 순환(거리 시험용)

#define BCOMBO_CALIB 0
#define BCOMBO_MODE  1
#define BCOMBO_TXPWR 2

typedef struct {
  uint8_t btn;
  uint8_t kind;   // BEV_*
  uint8_t count;  // BEV_PRESS(버튼1: 지금까지 횟수), BEV_MULTI_DONE(확정 횟수)
  bool first;     // BEV_PRESS
} button_event_t;

void buttons_begin();
void buttons_update(uint32_t now_ms);
bool buttons_next(button_event_t *ev);  // 쌓인 이벤트 하나. 없으면 false
