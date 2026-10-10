// POS_TABLE, PEER_REPORT 변환 (CLAUDE.md §6.7, 프로토콜 §5.2, §9.3) — 단계 9.
// Arduino 비의존(core만 사용) → 호스트 테스트 대상(tests/host/test_squad.cpp).
//
// PEER_REPORT 경로 두 가지(같은 payload 형식):
//   1) 분대장 중계: 연결 RX, src = 0, rx/ry = 분대장이 아는 보고자 위치.
//   2) 병사 직접 방송(v1.1 예정): 보고자가 EMCON 2에서 같은 보고를 광고로 3초 방송, src = reporter_id,
//      rx/ry = 보고자가 받은 POS_TABLE의 자기 위치(모르면 SQUAD_POS_UNKNOWN → 받는 쪽 POS_TABLE로 찾음).
#pragma once
#include <stdbool.h>
#include <stdint.h>

#include "../core/frame.h"
#include "../core/geo.h"

#define SQUAD_POS_UNKNOWN ((int16_t)-32768)  // 0x8000: 직접 방송에서 보고자가 자기 위치를 모를 때

typedef struct {
  bool valid;
  msg_pos_table_t t;
} squad_map_t;

void squad_map_init(squad_map_t *s);
void squad_map_set(squad_map_t *s, const msg_pos_table_t *t);

// id의 위치(0.1m). 표에 없으면 false. id 0(분대장)이 표에 없으면 원점(프로토콜 §5.2: 분대장 = 원점).
bool squad_map_pos(const squad_map_t *s, uint8_t id, int16_t *x, int16_t *y);

// RALLY 방향 = 내 위치에서 분대장(원점)으로의 절대 방위. POS_TABLE 없음/내 항목 없음/1m 안이면 0xFFFF.
uint16_t squad_map_rally_az(const squad_map_t *s, uint8_t my_id);

#define SQ_F_NO_POS          0x01  // 위치 모름 → 보고자 기준 방향 그대로(CLAUDE.md §6.7 마지막 줄)
#define SQ_F_NO_DIR          0x02  // 방향 없음(보고 azimuth 없음 + 위치도 모름)
#define SQ_F_TOWARD_REPORTER 0x04  // 보고 azimuth 없음 → 보고자 쪽 방향으로 대신 재생

typedef struct {
  uint8_t type;       // 원 보고 msg_type
  uint8_t count;      // CONTACT 적 수(그 외 0)
  uint8_t clock;      // 내 기준 시계 1~12, 0 = 없음
  uint8_t dist_band;  // 내 기준 거리 구간, GEO_DIST_NONE = 없음
  uint16_t bearing;   // 절대 방위(0~359), 없음 0xFFFF
  float range_dm;     // 거리(0.1m), 모르면 0
  uint8_t flags;      // SQ_F_*
} squad_peer_t;

#define SQ_OK          0
#define SQ_ERR_TYPE    (-1)  // 재생 대상이 아닌 원 보고 종류
#define SQ_ERR_PAYLOAD (-2)  // 원 보고 payload 길이 오류
#define SQ_ERR_SELF    (-3)  // 내 보고

// 재생 대상 원 보고: CONTACT, SUSPICIOUS, HAZARD, CASUALTY_FOUND
bool squad_map_peer_type_ok(uint8_t orig_type);

// PEER_REPORT → 내 위치·방위 기준(프로토콜 §9.3). 반환 SQ_OK 또는 SQ_ERR_*.
int squad_map_peer(const squad_map_t *s, uint8_t my_id, uint16_t my_heading, const msg_peer_report_t *pr,
                   squad_peer_t *out);
