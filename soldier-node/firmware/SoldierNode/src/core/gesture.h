// 버튼 제스처 판정 (CLAUDE.md §6.1, 프로토콜 §9.1). 디바운스된 눌림 상태와 시간(ms)만 받는 순수 로직.
// Arduino 비의존, C 호환, 동적 할당 없음 → 호스트 테스트 대상.
//
// 종류
//   GEST_MULTI : 연타(버튼1). 누를 때마다 pressed + count, 마지막 해제 후 1200ms 입력 없으면 MULTI_DONE(count).
//   GEST_SDL   : 짧게/두 번/길게(버튼2, 버튼4). 짧게는 400ms 지연 확정(두 번 여부 확인).
//   GEST_SL    : 짧게/길게(버튼3, 조이스틱 SW). 지연 없음.
// 길게는 손을 떼기 전, 누른 시간이 long_ms에 도달한 순간 확정한다.
// 짧게(< 600ms)도 길게(≥ long_ms)도 아닌 길이는 IGNORED.
#pragma once
#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define GEST_SHORT_MAX_MS     600
#define GEST_DOUBLE_GAP_MS    400
#define GEST_MULTI_TIMEOUT_MS 1200

#define GEST_MULTI 0
#define GEST_SDL   1
#define GEST_SL    2

#define GEV_NONE       0
#define GEV_SHORT      1
#define GEV_DOUBLE     2
#define GEV_LONG       3
#define GEV_MULTI_DONE 4
#define GEV_IGNORED    5

typedef struct {
  bool pressed;    // 이번 호출에서 눌림이 시작됨
  bool first;      // 그 눌림이 제스처의 첫 눌림(조이스틱 방향을 잡는 순간)
  uint8_t count;   // GEST_MULTI: 지금까지 누른 횟수(pressed일 때), 확정 횟수(MULTI_DONE일 때)
  uint8_t result;  // GEV_*
} gest_out_t;

typedef struct {
  uint8_t kind;
  uint16_t long_ms;
  uint8_t state;
  bool down;
  uint32_t t_down;
  uint32_t t_up;
  uint8_t count;
} gest_t;

void gest_init(gest_t *g, uint8_t kind, uint16_t long_ms);

// 매 루프마다 현재(디바운스된) 상태로 호출. 결과(result)와 눌림 시작(pressed)이 함께 나올 수 있다:
// 이때 result는 이전 제스처의 것이므로 result를 먼저 처리한 뒤 pressed를 처리한다.
gest_out_t gest_update(gest_t *g, bool down, uint32_t now);

// 진행 중인 제스처 취소(버튼1+버튼4 조합용). down = 지금 눌려 있는지. 눌려 있으면 뗄 때까지 무시.
void gest_cancel(gest_t *g, bool down);

bool gest_idle(const gest_t *g);

#ifdef __cplusplus
}
#endif
