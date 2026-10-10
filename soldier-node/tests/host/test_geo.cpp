// geo 단위 테스트: 시계 경계, HEADING_MODE FIXED 0도 기준 변환, 표적 → 다른 병사 기준 변환.
#include <math.h>

#include "geo.h"
#include "test_util.h"

// config.h 기본값(HEADING_MODE_FIXED, HEADING_FIXED_DEG 0)과 같은 방위. config.h는 Arduino 의존이라 직접 쓰지 않는다.
static const uint16_t kFixedHeading = 0;

static void test_clock_boundaries() {
  // 방위 0/359/15/345도 (내 방위 0)
  CHECK_EQ(geo_clock_from(0, 0), 12);
  CHECK_EQ(geo_clock_from(359, 0), 12);
  CHECK_EQ(geo_clock_from(15, 0), 1);     // 0.5 → 올림
  CHECK_EQ(geo_clock_from(345, 0), 12);   // 11.5 → 올림 → 12
  CHECK_EQ(geo_clock_from(14, 0), 12);
  CHECK_EQ(geo_clock_from(16, 0), 1);
  CHECK_EQ(geo_clock_from(344, 0), 11);
  CHECK_EQ(geo_clock_from(45, 0), 2);     // 프로토콜 §11.1 CMD 예시(방위 45 → 2시)

  // 내 방위 0/359/15/345도 (적 방위 0)
  CHECK_EQ(geo_clock_from(0, 359), 12);   // rel 1
  CHECK_EQ(geo_clock_from(0, 15), 12);    // rel 345
  CHECK_EQ(geo_clock_from(0, 345), 1);    // rel 15
  CHECK_EQ(geo_clock_from(270, 359), 9);  // rel 271
  CHECK_EQ(geo_clock_from(90, 345), 4);   // rel 105 → 3.5 → 4

  // 없음
  CHECK_EQ(geo_clock_from(GEO_NONE, 0), 0);
  CHECK_EQ(geo_clock_from(90, GEO_NONE), 3);  // 내 방위 없음 → 진북 기준

  // azimuth_from
  CHECK_EQ(geo_azimuth_from(12, 359), 359);
  CHECK_EQ(geo_azimuth_from(1, 15), 45);
  CHECK_EQ(geo_azimuth_from(3, 345), 75);
  CHECK_EQ(geo_azimuth_from(11, 0), 330);
  CHECK_EQ(geo_azimuth_from(0, 0), GEO_NONE);
  CHECK_EQ(geo_azimuth_from(13, 0), GEO_NONE);
  CHECK_EQ(geo_azimuth_from(3, GEO_NONE), GEO_NONE);

  // 모든 방위/시계 조합에서 azimuth_from → clock_from 왕복
  bool ok = true;
  for (int h = 0; h < 360; h++)
    for (int c = 1; c <= 12; c++)
      if (geo_clock_from(geo_azimuth_from((uint8_t)c, (uint16_t)h), (uint16_t)h) != c) ok = false;
  CHECK(ok);
}

static void test_fixed_heading_0() {
  // HEADING_MODE_FIXED, 0도(북쪽): 시계 = 절대 방위 그대로
  CHECK_EQ(geo_azimuth_from(12, kFixedHeading), 0);
  CHECK_EQ(geo_azimuth_from(3, kFixedHeading), 90);
  CHECK_EQ(geo_azimuth_from(6, kFixedHeading), 180);
  CHECK_EQ(geo_azimuth_from(9, kFixedHeading), 270);
  CHECK_EQ(geo_azimuth_from(2, kFixedHeading), 60);
  CHECK_EQ(geo_clock_from(0, kFixedHeading), 12);
  CHECK_EQ(geo_clock_from(90, kFixedHeading), 3);
  CHECK_EQ(geo_clock_from(180, kFixedHeading), 6);
  CHECK_EQ(geo_clock_from(270, kFixedHeading), 9);
}

static void test_target_and_peer() {
  float tx, ty;
  CHECK(geo_target_pos(0, 0, 90, GEO_DIST_NEAR, &tx, &ty));
  CHECK(fabsf(tx - 500.0f) < 0.5f && fabsf(ty) < 0.5f);
  CHECK(geo_target_pos(0, 0, 0, GEO_DIST_NONE, &tx, &ty));  // 거리 없음 → 100m
  CHECK(fabsf(tx) < 0.5f && fabsf(ty - 1000.0f) < 0.5f);
  CHECK(!geo_target_pos(0, 0, GEO_NONE, GEO_DIST_NEAR, &tx, &ty));
  CHECK_EQ(geo_dm_to_dist_band(749.9f), GEO_DIST_NEAR);
  CHECK_EQ(geo_dm_to_dist_band(750.0f), GEO_DIST_MID);
  CHECK_EQ(geo_dm_to_dist_band(1499.9f), GEO_DIST_MID);
  CHECK_EQ(geo_dm_to_dist_band(1500.0f), GEO_DIST_FAR);

  geo_rel_t r;
  // 예시 1 (횡대, 간격 10m): 병사1 (0,0), 병사2 (10m 동쪽 = 100,0).
  // 병사1 보고: 방위 45, 중거리(100m) → T ≈ (707.1, 707.1)
  // 병사2 기준: dx 607.1, dy 707.1 → 방위 40.65 → 41도, 거리 93.2m(중), 내 방위 0 → 1시
  CHECK(geo_peer_to_me(0, 0, 45, GEO_DIST_MID, 100, 0, kFixedHeading, &r));
  CHECK_EQ(r.bearing, 41);
  CHECK(fabsf(r.range_dm - 932.0f) < 1.0f);
  CHECK_EQ(r.dist_band, GEO_DIST_MID);
  CHECK_EQ(r.clock, 1);
  // 같은 상황에서 병사2가 동쪽(90도)을 보고 있으면 41 - 90 = -49 → 311도 → 10시
  CHECK(geo_peer_to_me(0, 0, 45, GEO_DIST_MID, 100, 0, 90, &r));
  CHECK_EQ(r.clock, 10);
  // 보고자 자신 기준이면 원래 방위·거리 그대로
  CHECK(geo_peer_to_me(0, 0, 45, GEO_DIST_MID, 0, 0, kFixedHeading, &r));
  CHECK_EQ(r.bearing, 45); CHECK_EQ(r.clock, 2); CHECK_EQ(r.dist_band, GEO_DIST_MID);

  // 예시 2 (종대, 간격 10m): 병사1 (0,0), 병사2 (10m 남쪽 = 0,-100).
  // 병사1 보고: 방위 90, 근거리(50m) → T = (500, 0)
  // 병사2 기준: dx 500, dy 100 → 방위 78.69 → 79도, 거리 51.0m(근), 내 방위 0 → 3시
  CHECK(geo_peer_to_me(0, 0, 90, GEO_DIST_NEAR, 0, -100, kFixedHeading, &r));
  CHECK_EQ(r.bearing, 79);
  CHECK(fabsf(r.range_dm - 509.9f) < 1.0f);
  CHECK_EQ(r.dist_band, GEO_DIST_NEAR);
  CHECK_EQ(r.clock, 3);

  CHECK(!geo_peer_to_me(0, 0, GEO_NONE, GEO_DIST_NEAR, 0, -100, 0, &r));
}

int main() {
  test_clock_boundaries();
  test_fixed_heading_0();
  test_target_and_peer();
  return test_summary("test_geo");
}
