// 병사 간 RSSI 거리 측정 (F11, 단계 R). 다른 병사·분대장 BEACON(0x20)의 RSSI를 피어별 최근 N개 이동 중앙값으로 정리.
// 피어 ID 0 = 분대장 비콘(위치 복원 기준점, 단계 9 보충), 1~5 = 병사.
// Arduino 비의존, C 호환, 정적 배열 → 호스트 테스트.
#pragma once
#include <stdbool.h>
#include <stdint.h>

#include "frame.h"

#ifdef __cplusplus
extern "C" {
#endif

#define RANGING_WINDOW 15   // 피어별 최근 RSSI 개수(이동 중앙값)
#define RANGING_IDS    5    // 피어 ID 0(분대장)~5

typedef struct {
  int8_t rssi[RANGING_WINDOW];
  uint8_t count;   // 채워진 개수(≤ RANGING_WINDOW)
  uint8_t next;    // 다음에 덮어쓸 위치
  uint32_t last_t; // 마지막 수신 시각
} ranging_peer_t;

typedef struct {
  ranging_peer_t p[RANGING_IDS + 1];  // [0] 분대장, [1]~[5] 병사
  uint32_t stale_ms;                  // 이 시간 동안 못 들은 피어는 버림
} ranging_t;

void ranging_init(ranging_t *r, uint32_t stale_ms);
void ranging_add(ranging_t *r, uint8_t peer_id, int8_t rssi, uint32_t now);

// RANGING(0x0E) payload용 목록: 자기 자신·오래된 피어 제외, rssi_avg = 중앙값, samples = 창 안 개수.
uint8_t ranging_collect(ranging_t *r, uint8_t self_id, uint32_t now, ranging_entry_t *out, uint8_t max);

// 중앙값(짝수 개면 가운데 두 값의 평균, 0쪽으로 버림). n = 0이면 0.
int8_t ranging_median(const int8_t *v, uint8_t n);

// 경로손실 모델 d = 10^((P1m − RSSI) / (10·n)) [m]
float ranging_distance_m(float rssi, float p1m, float n);

#ifdef __cplusplus
}
#endif
