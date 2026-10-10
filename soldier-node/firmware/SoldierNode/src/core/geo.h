// 방위/시계 변환, 표적 위치 계산, 내 기준 변환 (CLAUDE.md §6.7, 프로토콜 §9.3).
// 각도: 진북 기준 시계방향 0~359도. 좌표: 분대장 원점, x 동쪽, y 북쪽, 단위 0.1m.
// Arduino 비의존, C 호환, 동적 할당 없음.
#pragma once
#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define GEO_NONE        0xFFFF  // azimuth/heading 없음
#define GEO_DIST_NEAR   0
#define GEO_DIST_MID    1
#define GEO_DIST_FAR    2
#define GEO_DIST_NONE   0xFF

// 수신 방향 → 내 기준 시계(1~12). azimuth 없음 → 0.
// my_heading 없음(0xFFFF) → heading 0(진북 기준 시계)으로 간주(데모 단순화).
uint8_t geo_clock_from(uint16_t azimuth, uint16_t my_heading);

// 내 기준 시계 → 절대 방위. clock 0 또는 heading 없음 → 0xFFFF.
uint16_t geo_azimuth_from(uint8_t clock, uint16_t my_heading);

// 거리 구간 대표값(0.1m): 근 500, 중 1000, 원 2000, 없음 1000.
int32_t geo_dist_band_to_dm(uint8_t dist_band);

// 거리(0.1m) → 구간: < 75m 근, < 150m 중, 그 외 원.
uint8_t geo_dm_to_dist_band(float dist_dm);

// 표적 위치 T = 보고자 위치 + d·(sin az, cos az). azimuth 없음이면 false.
bool geo_target_pos(int16_t rep_x, int16_t rep_y, uint16_t azimuth, uint8_t dist_band,
                    float *tx, float *ty);

// 내 위치 P에서 T로의 방위(0~359)와 거리(0.1m).
void geo_bearing_range(float px, float py, float tx, float ty, uint16_t *bearing, float *range_dm);

typedef struct {
  uint16_t bearing;    // 절대 방위 0~359
  uint8_t clock;       // 내 기준 시계 1~12
  uint8_t dist_band;   // 근/중/원
  float range_dm;      // 거리(0.1m)
} geo_rel_t;

// 다른 병사 보고(보고자 위치, azimuth, dist_band)를 내 위치·방위 기준으로 변환. azimuth 없음이면 false.
bool geo_peer_to_me(int16_t rep_x, int16_t rep_y, uint16_t azimuth, uint8_t dist_band,
                    int16_t my_x, int16_t my_y, uint16_t my_heading, geo_rel_t *out);

// ---------- 조이스틱 방향 (CLAUDE.md §6.1, 프로토콜 §9.1) ----------
typedef struct {
  uint8_t clock;      // 1~12, 0 = 방향 없음(기울기 < deadzone)
  uint8_t dist_band;  // GEO_DIST_NEAR(35~75%) / GEO_DIST_FAR(≥75%) / GEO_DIST_NONE
  uint8_t pct;        // 기울기 비율 0~100
} geo_joy_t;

// dx, dy: 중앙값 기준 원시 편차(장착 보정 전). max_x, max_y: 축별 최대 거리(> 0).
// 보정: inv_x/inv_y로 부호 반전 → +dy = 총구 전방(12시), +dx = 오른쪽(3시) → rotate_deg만큼 시계방향 회전.
// 기울기 = sqrt((dx/max_x)^2 + (dy/max_y)^2), 100% 상한.
geo_joy_t geo_joy_direction(int32_t dx, int32_t dy, int32_t max_x, int32_t max_y, bool inv_x, bool inv_y,
                            int16_t rotate_deg, uint8_t deadzone_pct, uint8_t far_pct);

#ifdef __cplusplus
}
#endif
