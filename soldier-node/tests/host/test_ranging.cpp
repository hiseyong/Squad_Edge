// 단계 R: RSSI 이동 중앙값·피어 목록·경로손실 거리.
#include <math.h>

#include "ranging.h"
#include "test_util.h"

int main() {
  // 중앙값
  int8_t a[] = {-70, -60, -65};
  CHECK_EQ(ranging_median(a, 3), -65);
  int8_t b[] = {-70, -60, -65, -61};
  CHECK_EQ(ranging_median(b, 4), -63);  // (-65 + -61)/2 = -63
  int8_t c[] = {-90};
  CHECK_EQ(ranging_median(c, 1), -90);
  CHECK_EQ(ranging_median(c, 0), 0);
  // 튀는 값에 강함: 15개 중 3개가 -100이어도 중앙값은 안정
  int8_t d[15];
  for (int i = 0; i < 15; i++) d[i] = (int8_t)(i < 3 ? -100 : -60 - (i % 3));
  CHECK_EQ(ranging_median(d, 15), -61);

  ranging_t r;
  ranging_init(&r, 30000);
  // 자기 자신(1)과 범위 밖 ID(6)는 목록에 없음, 0(분대장 비콘)은 포함(단계 9 보충)
  ranging_add(&r, 1, -40, 100);
  ranging_add(&r, 0, -40, 100);
  ranging_add(&r, 6, -40, 100);
  ranging_entry_t e[8];
  CHECK_EQ(ranging_collect(&r, 1, 200, e, 8), 1);
  CHECK_EQ(e[0].peer_id, 0); CHECK_EQ(e[0].rssi_avg, -40);
  // 피어 2: 20개 넣으면 최근 15개만
  for (int i = 0; i < 20; i++) ranging_add(&r, 2, (int8_t)(i < 5 ? -100 : -66), 1000 + i * 500);
  ranging_add(&r, 3, -80, 5000);
  uint8_t n = ranging_collect(&r, 1, 12000, e, 8);
  CHECK_EQ(n, 3);
  CHECK_EQ(e[0].peer_id, 0);
  CHECK_EQ(e[1].peer_id, 2); CHECK_EQ(e[1].rssi_avg, -66); CHECK_EQ(e[1].samples, 15);  // -100 5개는 밀려남
  CHECK_EQ(e[2].peer_id, 3); CHECK_EQ(e[2].rssi_avg, -80); CHECK_EQ(e[2].samples, 1);
  // 30초 넘게 못 들은 피어는 제외(피어 0: 마지막 100, 피어 3: 마지막 5000 → 35001에 제외), 피어 2는 마지막 10500
  n = ranging_collect(&r, 1, 35001, e, 8);
  CHECK_EQ(n, 1); CHECK_EQ(e[0].peer_id, 2);
  n = ranging_collect(&r, 1, 40501, e, 8);
  CHECK_EQ(n, 0);
  // 오래 끊겼다 다시 들리면 창을 새로 시작
  ranging_add(&r, 2, -50, 50000);
  n = ranging_collect(&r, 1, 50001, e, 8);
  CHECK_EQ(n, 1); CHECK_EQ(e[0].samples, 1); CHECK_EQ(e[0].rssi_avg, -50);
  // max 제한
  ranging_add(&r, 3, -70, 50000); ranging_add(&r, 4, -70, 50000); ranging_add(&r, 5, -70, 50000);
  CHECK_EQ(ranging_collect(&r, 1, 50001, e, 2), 2);
  ranging_add(&r, 0, -70, 50000);
  // RANGING 프레임으로 인코드 가능(최대: 분대장 + 다른 병사 4 = peers 5 → 6 + 1 + 15 = 22B, 보고 큐 24B 이하)
  frame_msg_t m = {};
  m.type = MSG_RANGING; m.src = 1; m.dst = FRAME_DST_LEADER;
  m.u.ranging.n = ranging_collect(&r, 1, 50001, m.u.ranging.e, RANGING_MAX_PEERS);
  uint8_t buf[32];
  CHECK_EQ(m.u.ranging.n, 5);
  CHECK_EQ(frame_encode(&m, buf, sizeof buf), 22);

  // 경로손실 거리: P1m −59, n 2 → RSSI −59 = 1m, −79 = 10m, −65 ≈ 2.0m
  CHECK(fabsf(ranging_distance_m(-59, -59, 2.0f) - 1.0f) < 0.01f);
  CHECK(fabsf(ranging_distance_m(-79, -59, 2.0f) - 10.0f) < 0.01f);
  CHECK(fabsf(ranging_distance_m(-65, -59, 2.0f) - 1.995f) < 0.01f);
  CHECK(fabsf(ranging_distance_m(-69, -59, 2.5f) - 2.512f) < 0.01f);
  CHECK_EQ(ranging_distance_m(-60, -59, 0.0f), 0.0f);
  return test_summary("test_ranging");
}
