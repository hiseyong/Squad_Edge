// squad_map 단위 테스트(단계 9): POS_TABLE 프리셋 대형 → PEER_REPORT를 내 기준으로 변환, RALLY 방향.
// 시연 시나리오 3개: 같은 표적(S2 보고)이 대형에 따라 S1에게 다른 시계 방향으로 들린다.
// 기대값은 tools/squad_localize.py peer_to_me()와 같은 계산(프리셋 간격 10m, heading 0).
#include <string.h>

#include "phrases.h"
#include "squad_map.h"
#include "test_util.h"

enum { WEDGE, LINE, COLUMN };

// tools/squad_localize.py preset_positions()와 같은 좌표(0.1m, 반올림). 0 = 분대장(원점)
static void preset(int f, msg_pos_table_t *t) {
  static const int16_t kXY[3][5][2] = {
    {{-71, -71}, {71, -71}, {-141, -141}, {141, -141}, {-212, -212}},  // wedge 쐐기
    {{-100, 0}, {100, 0}, {-200, 0}, {200, 0}, {-300, 0}},             // line 횡대
    {{0, 100}, {0, -100}, {0, 200}, {0, -200}, {0, -300}},             // column 종대
  };
  t->n = 6;
  t->e[0] = {0, 0, 0, 0};
  for (int i = 0; i < 5; i++) t->e[i + 1] = {(uint8_t)(i + 1), kXY[f][i][0], kXY[f][i][1], 0};
}

static uint8_t s_payload[16];

static msg_peer_report_t make_peer(uint8_t reporter, int16_t rx, int16_t ry, uint8_t type, uint16_t az,
                                   uint8_t dist, uint8_t count) {
  frame_msg_t o = {};
  o.type = type;
  switch (type) {
    case MSG_CONTACT: o.u.contact = {az, 0, dist, count, 0}; break;
    case MSG_SUSPICIOUS:
    case MSG_HAZARD: o.u.dir_report = {az, 0, 0}; break;
    case MSG_CASUALTY_FOUND: o.u.casualty_found = {az, 0, dist, 0}; break;
    case MSG_OK_READY: break;
  }
  int n = frame_encode_payload(&o, s_payload, sizeof s_payload);
  msg_peer_report_t pr = {reporter, rx, ry, type, s_payload, (uint8_t)(n < 0 ? 0 : n)};
  return pr;
}

// S2가 보고 → S1(heading h) 기준. 보고자 위치는 분대장 중계처럼 POS_TABLE에서 넣는다.
static const char *hear(int formation, uint8_t type, uint16_t az, uint8_t dist, uint8_t count, uint16_t h,
                        squad_peer_t *out) {
  static char buf[64];
  squad_map_t s;
  squad_map_init(&s);
  msg_pos_table_t t;
  preset(formation, &t);
  squad_map_set(&s, &t);
  int16_t rx, ry;
  squad_map_pos(&s, 2, &rx, &ry);
  msg_peer_report_t pr = make_peer(2, rx, ry, type, az, dist, count);
  CHECK_EQ(squad_map_peer(&s, 1, h, &pr, out), SQ_OK);
  phrase_t p;
  phrases_for_peer(out->type, out->count, out->clock, out->dist_band, &p);
  phrases_join(&p, buf, sizeof buf);
  return buf;
}

#define HEAR_EQ(expect, ...) CHECK(strcmp(hear(__VA_ARGS__), expect) == 0)

int main() {
  squad_peer_t o;
  // ---- 시나리오 1: S2 "적 3, 12시(방위 0), 근거리" ----
  HEAR_EQ("enemy n3 c1 near", WEDGE, MSG_CONTACT, 0, 0, 3, 0, &o);  // 방위 16, 52m
  CHECK(o.bearing >= 15 && o.bearing <= 17);
  HEAR_EQ("enemy n3 c1 near", LINE, MSG_CONTACT, 0, 0, 3, 0, &o);   // 방위 22, 54m
  CHECK_EQ(o.bearing, 22);
  HEAR_EQ("enemy n3 c12 near", COLUMN, MSG_CONTACT, 0, 0, 3, 0, &o);  // S1이 S2 앞 20m: 바로 앞 30m
  CHECK_EQ(o.bearing, 0);
  CHECK(o.range_dm > 299.0f && o.range_dm < 301.0f);
  // 내 방위가 90(동쪽)이면 같은 표적이 10시
  HEAR_EQ("enemy n3 c10 near", LINE, MSG_CONTACT, 0, 0, 3, 90, &o);

  // ---- 시나리오 2: S2 "적 2, 3시(방위 90), 근거리" ----
  HEAR_EQ("enemy n2 c3 near", WEDGE, MSG_CONTACT, 90, 0, 2, 0, &o);
  HEAR_EQ("enemy n2 c3 near", LINE, MSG_CONTACT, 90, 0, 2, 0, &o);   // 방위 90, 70m
  HEAR_EQ("enemy n2 c4 near", COLUMN, MSG_CONTACT, 90, 0, 2, 0, &o);  // 방위 112, 54m
  CHECK_EQ(o.bearing, 112);

  // ---- 시나리오 3: S2 "부상자, 10시(방위 300), 근거리" → 대형마다 다른 시계 ----
  HEAR_EQ("casualty c10 near", WEDGE, MSG_CASUALTY_FOUND, 300, 0, 0, 0, &o);  // 방위 311
  HEAR_EQ("casualty c11 near", LINE, MSG_CASUALTY_FOUND, 300, 0, 0, 0, &o);   // 방위 317
  HEAR_EQ("casualty c9 near", COLUMN, MSG_CASUALTY_FOUND, 300, 0, 0, 0, &o);  // 방위 277

  // 폭발물 의심(거리 없음 → 표적 100m 가정, §6.7): 내 기준 중거리
  HEAR_EQ("hazard c10 mid", LINE, MSG_HAZARD, 285, 0xFF, 0, 0, &o);
  HEAR_EQ("hazard c9 mid", COLUMN, MSG_HAZARD, 285, 0xFF, 0, 0, &o);
  HEAR_EQ("suspicious c12 mid", COLUMN, MSG_SUSPICIOUS, 0, 0xFF, 0, 0, &o);  // 앞 80m

  // 방향 미상 보고 → 보고자 쪽(횡대 S2는 S1 동쪽 20m = 3시 근거리)
  HEAR_EQ("enemy unknown c3 near", LINE, MSG_CONTACT, 0xFFFF, 0xFF, 0, 0, &o);
  CHECK(o.flags & SQ_F_TOWARD_REPORTER);

  // ---- RALLY: 분대장(원점) 방향 ----
  squad_map_t s;
  msg_pos_table_t t;
  squad_map_init(&s);
  CHECK_EQ(squad_map_rally_az(&s, 1), 0xFFFF);  // POS_TABLE 전
  preset(WEDGE, &t); squad_map_set(&s, &t);
  CHECK_EQ(geo_clock_from(squad_map_rally_az(&s, 1), 0), 2);   // 쐐기 S1(좌후방) → 45도 = 2시
  CHECK_EQ(geo_clock_from(squad_map_rally_az(&s, 2), 0), 11);  // S2(우후방) → 315도 = 11시
  preset(LINE, &t); squad_map_set(&s, &t);
  CHECK_EQ(geo_clock_from(squad_map_rally_az(&s, 1), 0), 3);
  preset(COLUMN, &t); squad_map_set(&s, &t);
  CHECK_EQ(geo_clock_from(squad_map_rally_az(&s, 1), 0), 6);
  CHECK_EQ(squad_map_rally_az(&s, 0), 0xFFFF);  // 분대장 자신 = 원점(방향 없음)
  CHECK_EQ(squad_map_rally_az(&s, 5), 0);       // S5(맨 뒤) → 북쪽
  CHECK_EQ(geo_clock_from(squad_map_rally_az(&s, 5), 0), 12);
  // 표에 분대장 항목이 없어도 원점
  msg_pos_table_t t2 = {};
  t2.n = 1; t2.e[0] = {1, -100, 0, 0};
  squad_map_set(&s, &t2);
  CHECK_EQ(squad_map_rally_az(&s, 1), 90);
  CHECK_EQ(squad_map_rally_az(&s, 2), 0xFFFF);  // 내 항목 없음

  // ---- 병사 직접 방송: rx/ry 모름(0x8000) → 받는 쪽 POS_TABLE의 보고자 위치 ----
  preset(LINE, &t); squad_map_set(&s, &t);
  msg_peer_report_t pr = make_peer(2, SQUAD_POS_UNKNOWN, SQUAD_POS_UNKNOWN, MSG_CONTACT, 0, 0, 3);
  CHECK_EQ(squad_map_peer(&s, 1, 0, &pr, &o), SQ_OK);
  CHECK_EQ(o.clock, 1); CHECK_EQ(o.bearing, 22); CHECK_EQ(o.flags, 0);
  // 방송에 실린 위치가 있으면 그것을 쓴다(보고자가 아는 자기 위치)
  pr = make_peer(2, 0, -100, MSG_CONTACT, 0, 0, 3);
  CHECK_EQ(squad_map_peer(&s, 1, 0, &pr, &o), SQ_OK);
  CHECK_EQ(o.bearing, 14); CHECK_EQ(o.clock, 12);  // S2가 (0,-10m)라고 알림 → 표적 (0,40m), S1(-10,0)에서 14도

  // ---- POS_TABLE 전: 보고자 기준 방향 그대로 ----
  squad_map_init(&s);
  pr = make_peer(2, 100, 0, MSG_CONTACT, 45, 2, 3);
  CHECK_EQ(squad_map_peer(&s, 1, 0, &pr, &o), SQ_OK);
  CHECK_EQ(o.flags, SQ_F_NO_POS); CHECK_EQ(o.clock, 2); CHECK_EQ(o.dist_band, 2);
  pr = make_peer(2, 100, 0, MSG_SUSPICIOUS, 0xFFFF, 0xFF, 0);
  CHECK_EQ(squad_map_peer(&s, 1, 0, &pr, &o), SQ_OK);
  CHECK_EQ(o.flags, SQ_F_NO_POS | SQ_F_NO_DIR); CHECK_EQ(o.clock, 0);
  phrase_t p;
  char buf[64];
  phrases_for_peer(o.type, o.count, o.clock, o.dist_band, &p);
  phrases_join(&p, buf, sizeof buf);
  CHECK(strcmp(buf, "suspicious") == 0);
  CHECK(p.flags & PHRASE_F_NO_DIR);

  // ---- 거부 ----
  pr = make_peer(1, 0, 0, MSG_CONTACT, 0, 0, 3);
  CHECK_EQ(squad_map_peer(&s, 1, 0, &pr, &o), SQ_ERR_SELF);
  pr = make_peer(2, 0, 0, MSG_OK_READY, 0, 0, 0);
  CHECK_EQ(squad_map_peer(&s, 1, 0, &pr, &o), SQ_ERR_TYPE);
  pr = make_peer(2, 0, 0, MSG_CONTACT, 0, 0, 3);
  pr.orig_len = 6;  // CONTACT는 7바이트
  CHECK_EQ(squad_map_peer(&s, 1, 0, &pr, &o), SQ_ERR_PAYLOAD);

  // ---- 직접 방송 프레임 크기: PEER_REPORT(CONTACT) = 6 + 6 + 7 = 19B ≤ 광고 24B ----
  frame_msg_t m = {};
  m.type = MSG_PEER_REPORT; m.src = 2; m.dst = FRAME_DST_ALL_SOLDIERS;
  pr = make_peer(2, 100, 0, MSG_CONTACT, 0, 0, 3);
  m.u.peer_report = pr;
  uint8_t f[32];
  CHECK_EQ(frame_encode(&m, f, sizeof f), 19);
  frame_msg_t d;
  CHECK_EQ(frame_receive(f, 19, 1, &d), FRAME_OK);
  CHECK_EQ(d.u.peer_report.reporter_id, 2);
  CHECK_EQ(d.u.peer_report.orig_len, 7);
  return test_summary("squad");
}
