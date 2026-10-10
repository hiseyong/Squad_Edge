// 입력 판정 단위 테스트: gesture(짧게/길게/두 번/연타/취소), geo_joy_direction(방향·기울기 구간·장착 보정).
#include "geo.h"
#include "gesture.h"
#include "test_util.h"

// 시뮬레이션: from~to(ms) 동안 1ms마다 down 상태로 호출하며 결과를 모은다.
typedef struct {
  int presses;
  int first_presses;
  int results[8];
  uint32_t result_t[8];
  uint8_t result_count[8];
  int nres;
  uint8_t last_press_count;
} sim_t;

static void run(gest_t *g, sim_t *s, bool down, uint32_t from, uint32_t to) {
  for (uint32_t t = from; t < to; t++) {
    gest_out_t o = gest_update(g, down, t);
    if (o.result != GEV_NONE && s->nres < 8) {
      s->results[s->nres] = o.result;
      s->result_t[s->nres] = t;
      s->result_count[s->nres] = o.count;
      s->nres++;
    }
    if (o.pressed) {
      s->presses++;
      if (o.first) s->first_presses++;
      s->last_press_count = o.count;
    }
  }
}

static sim_t fresh() {
  sim_t s = {};
  return s;
}

static void test_sdl() {
  gest_t g;
  sim_t s;

  // 짧게(200ms) → 해제 후 400ms 지나서 SHORT
  gest_init(&g, GEST_SDL, 1000); s = fresh();
  run(&g, &s, false, 0, 10); run(&g, &s, true, 10, 210); run(&g, &s, false, 210, 1000);
  CHECK_EQ(s.nres, 1); CHECK_EQ(s.results[0], GEV_SHORT); CHECK_EQ(s.result_t[0], 610);
  CHECK_EQ(s.presses, 1); CHECK_EQ(s.first_presses, 1);

  // 두 번: 150ms 누름, 200ms 뗌, 다시 누름 → 두 번째 눌림 순간 DOUBLE, SHORT 없음
  gest_init(&g, GEST_SDL, 1000); s = fresh();
  run(&g, &s, true, 0, 150); run(&g, &s, false, 150, 350); run(&g, &s, true, 350, 500); run(&g, &s, false, 500, 1500);
  CHECK_EQ(s.nres, 1); CHECK_EQ(s.results[0], GEV_DOUBLE); CHECK_EQ(s.result_t[0], 350);
  CHECK_EQ(s.presses, 2); CHECK_EQ(s.first_presses, 1);

  // 간격 400ms 이상이면 두 번이 아니라 짧게 + 짧게
  gest_init(&g, GEST_SDL, 1000); s = fresh();
  run(&g, &s, true, 0, 100); run(&g, &s, false, 100, 520); run(&g, &s, true, 520, 600); run(&g, &s, false, 600, 1500);
  CHECK_EQ(s.nres, 2); CHECK_EQ(s.results[0], GEV_SHORT); CHECK_EQ(s.results[1], GEV_SHORT);
  CHECK_EQ(s.first_presses, 2);

  // 길게(버튼2, 1000ms): 누른 채 1000ms에 LONG, 떼도 추가 결과 없음
  gest_init(&g, GEST_SDL, 1000); s = fresh();
  run(&g, &s, true, 0, 1500); run(&g, &s, false, 1500, 2500);
  CHECK_EQ(s.nres, 1); CHECK_EQ(s.results[0], GEV_LONG); CHECK_EQ(s.result_t[0], 1000);

  // 600~1000ms → IGNORED
  gest_init(&g, GEST_SDL, 1000); s = fresh();
  run(&g, &s, true, 0, 800); run(&g, &s, false, 800, 2000);
  CHECK_EQ(s.nres, 1); CHECK_EQ(s.results[0], GEV_IGNORED);

  // 버튼4(길게 2000ms): 1500ms는 IGNORED, 2000ms는 LONG
  gest_init(&g, GEST_SDL, 2000); s = fresh();
  run(&g, &s, true, 0, 1500); run(&g, &s, false, 1500, 3000);
  CHECK_EQ(s.nres, 1); CHECK_EQ(s.results[0], GEV_IGNORED);
  gest_init(&g, GEST_SDL, 2000); s = fresh();
  run(&g, &s, true, 0, 2500); run(&g, &s, false, 2500, 3000);
  CHECK_EQ(s.nres, 1); CHECK_EQ(s.results[0], GEV_LONG); CHECK_EQ(s.result_t[0], 2000);
}

static void test_sl() {
  gest_t g;
  sim_t s;
  // 짧게는 지연 없이 해제 순간
  gest_init(&g, GEST_SL, 1000); s = fresh();
  run(&g, &s, true, 0, 300); run(&g, &s, false, 300, 1000);
  CHECK_EQ(s.nres, 1); CHECK_EQ(s.results[0], GEV_SHORT); CHECK_EQ(s.result_t[0], 300);
  // 길게
  gest_init(&g, GEST_SL, 1000); s = fresh();
  run(&g, &s, true, 0, 1200); run(&g, &s, false, 1200, 1500);
  CHECK_EQ(s.nres, 1); CHECK_EQ(s.results[0], GEV_LONG); CHECK_EQ(s.result_t[0], 1000);
  // 빠른 두 번은 짧게 두 번(SL에는 두 번 판정 없음)
  gest_init(&g, GEST_SL, 1000); s = fresh();
  run(&g, &s, true, 0, 100); run(&g, &s, false, 100, 200); run(&g, &s, true, 200, 300); run(&g, &s, false, 300, 500);
  CHECK_EQ(s.nres, 2); CHECK_EQ(s.results[0], GEV_SHORT); CHECK_EQ(s.results[1], GEV_SHORT);
}

static void test_multi() {
  gest_t g;
  sim_t s;
  // 3번 연타 → 마지막 해제 후 1200ms에 MULTI_DONE(3)
  gest_init(&g, GEST_MULTI, 0); s = fresh();
  uint32_t t = 0;
  for (int i = 0; i < 3; i++) { run(&g, &s, true, t, t + 100); run(&g, &s, false, t + 100, t + 300); t += 300; }
  run(&g, &s, false, t, t + 2000);
  CHECK_EQ(s.presses, 3); CHECK_EQ(s.first_presses, 1); CHECK_EQ(s.last_press_count, 3);
  CHECK_EQ(s.nres, 1); CHECK_EQ(s.results[0], GEV_MULTI_DONE); CHECK_EQ(s.result_count[0], 3);
  CHECK_EQ(s.result_t[0], 700 + 1200);  // 마지막 해제(700ms) + 1200
  CHECK(gest_idle(&g));

  // 7번 → 횟수 7 그대로(5 이상 = 다수 처리는 앱에서)
  gest_init(&g, GEST_MULTI, 0); s = fresh(); t = 0;
  for (int i = 0; i < 7; i++) { run(&g, &s, true, t, t + 80); run(&g, &s, false, t + 80, t + 200); t += 200; }
  run(&g, &s, false, t, t + 1500);
  CHECK_EQ(s.nres, 1); CHECK_EQ(s.result_count[0], 7);

  // 누르고 있는 동안에는 확정하지 않는다
  gest_init(&g, GEST_MULTI, 0); s = fresh();
  run(&g, &s, true, 0, 3000);
  CHECK_EQ(s.nres, 0);
  run(&g, &s, false, 3000, 4300);
  CHECK_EQ(s.nres, 1); CHECK_EQ(s.result_count[0], 1);
}

static void test_cancel() {
  gest_t g;
  sim_t s;
  // 버튼4(SDL 2000) 누른 채 취소 → 2000ms가 지나도 LONG 없음, 뗀 뒤 정상 동작
  gest_init(&g, GEST_SDL, 2000); s = fresh();
  run(&g, &s, true, 0, 100);
  gest_cancel(&g, true);
  run(&g, &s, true, 100, 3500); run(&g, &s, false, 3500, 4000);
  CHECK_EQ(s.nres, 0);
  run(&g, &s, true, 4000, 4100); run(&g, &s, false, 4100, 5000);
  CHECK_EQ(s.nres, 1); CHECK_EQ(s.results[0], GEV_SHORT);

  // 버튼1 연타 중 취소 → 횟수 버림
  gest_init(&g, GEST_MULTI, 0); s = fresh();
  run(&g, &s, true, 0, 100); run(&g, &s, false, 100, 200); run(&g, &s, true, 200, 300);
  gest_cancel(&g, true);
  run(&g, &s, true, 300, 3300); run(&g, &s, false, 3300, 6000);
  CHECK_EQ(s.nres, 0);

  // 같은 틱에 눌림과 취소: 취소가 먼저면 눌림으로 보지 않는다
  gest_init(&g, GEST_SDL, 1000); s = fresh();
  gest_cancel(&g, true);
  run(&g, &s, true, 0, 2000); run(&g, &s, false, 2000, 3000);
  CHECK_EQ(s.presses, 0); CHECK_EQ(s.nres, 0);
}

static void test_joy() {
  geo_joy_t j;
  // 중앙 근처 → 방향 없음
  j = geo_joy_direction(50, 60, 512, 512, false, false, 0, 35, 75);
  CHECK_EQ(j.clock, 0); CHECK_EQ(j.dist_band, GEO_DIST_NONE);
  // +dy 끝까지 = 12시 원거리, +dx 절반 = 3시 근거리
  j = geo_joy_direction(0, 512, 512, 512, false, false, 0, 35, 75);
  CHECK_EQ(j.clock, 12); CHECK_EQ(j.dist_band, GEO_DIST_FAR); CHECK_EQ(j.pct, 100);
  j = geo_joy_direction(256, 0, 512, 512, false, false, 0, 35, 75);
  CHECK_EQ(j.clock, 3); CHECK_EQ(j.dist_band, GEO_DIST_NEAR); CHECK_EQ(j.pct, 50);
  j = geo_joy_direction(0, -512, 512, 512, false, false, 0, 35, 75);
  CHECK_EQ(j.clock, 6);
  j = geo_joy_direction(-512, 0, 512, 512, false, false, 0, 35, 75);
  CHECK_EQ(j.clock, 9);
  // 경계: 35% 미만/이상, 75% 미만/이상
  j = geo_joy_direction(0, 174, 512, 512, false, false, 0, 35, 75);  // 33.98% → 34
  CHECK_EQ(j.clock, 0);
  j = geo_joy_direction(0, 180, 512, 512, false, false, 0, 35, 75);  // 35.2%
  CHECK_EQ(j.clock, 12); CHECK_EQ(j.dist_band, GEO_DIST_NEAR);
  j = geo_joy_direction(0, 380, 512, 512, false, false, 0, 35, 75);  // 74.2%
  CHECK_EQ(j.dist_band, GEO_DIST_NEAR);
  j = geo_joy_direction(0, 386, 512, 512, false, false, 0, 35, 75);  // 75.4%
  CHECK_EQ(j.dist_band, GEO_DIST_FAR);
  // 대각선(모서리)은 100% 상한, 1~2시 사이 45도 → 2시(반올림 규칙)
  j = geo_joy_direction(512, 512, 512, 512, false, false, 0, 35, 75);
  CHECK_EQ(j.pct, 100); CHECK_EQ(j.clock, 2);
  // 장착 보정: Y 반전이면 -dy가 12시, X 반전이면 -dx가 3시
  j = geo_joy_direction(0, -512, 512, 512, false, true, 0, 35, 75);
  CHECK_EQ(j.clock, 12);
  j = geo_joy_direction(-512, 0, 512, 512, true, false, 0, 35, 75);
  CHECK_EQ(j.clock, 3);
  // 회전 90도: 원래 12시(전방) → 3시
  j = geo_joy_direction(0, 512, 512, 512, false, false, 90, 35, 75);
  CHECK_EQ(j.clock, 3);
  j = geo_joy_direction(0, 512, 512, 512, false, false, 270, 35, 75);
  CHECK_EQ(j.clock, 9);
  // 축별 최대값이 다르면 각 축으로 정규화
  j = geo_joy_direction(400, 0, 400, 512, false, false, 0, 35, 75);
  CHECK_EQ(j.pct, 100); CHECK_EQ(j.clock, 3);
  // 잘못된 최대값
  j = geo_joy_direction(100, 100, 0, 512, false, false, 0, 35, 75);
  CHECK_EQ(j.clock, 0);
}

// ID 1 보드 실측(2026-10-10): 중앙 c=(537,534), 앞 x=1021, 오른쪽 y=1022, 뒤 x=0, 왼쪽 y=0.
// hal/joystick과 같은 방식(방향별 최대 거리 = ADC 끝까지, X/Y 교환)으로 계산했을 때 기대 시계가 나와야 한다.
static geo_joy_t measured(int x, int y) {
  const int cx = 537, cy = 534;
  int dx = x - cx, dy = y - cy;
  int mx = dx >= 0 ? 1023 - cx : cx;
  int my = dy >= 0 ? 1023 - cy : cy;
  return geo_joy_direction(dy, dx, my, mx, false, false, 0, 35, 75);  // JOY_SWAP_XY = 1
}

static void test_joy_measured() {
  geo_joy_t j;
  j = measured(1021, 535); CHECK_EQ(j.clock, 12); CHECK_EQ(j.dist_band, GEO_DIST_FAR);  // 앞 끝
  j = measured(536, 1022); CHECK_EQ(j.clock, 3);  CHECK_EQ(j.dist_band, GEO_DIST_FAR);  // 오른쪽 끝
  j = measured(0, 534);    CHECK_EQ(j.clock, 6);  CHECK_EQ(j.dist_band, GEO_DIST_FAR);  // 뒤 끝
  j = measured(537, 0);    CHECK_EQ(j.clock, 9);  CHECK_EQ(j.dist_band, GEO_DIST_FAR);  // 왼쪽 끝
  j = measured(537, 536);  CHECK_EQ(j.clock, 0);                                        // 중앙 흔들림 ±2
  CHECK_EQ(measured(1021, 535).pct, 100);  // +X 쪽은 486까지만 가지만 방향별 정규화로 100%
  CHECK_EQ(measured(0, 534).pct, 100);
  j = measured(1021, 1022); CHECK_EQ(j.clock, 2);  // 앞-오른쪽 대각 45도 → 2시(반올림 규칙)
  j = measured(780, 534);   CHECK_EQ(j.clock, 12); CHECK_EQ(j.dist_band, GEO_DIST_NEAR);  // 243/486 = 50%
}

int main() {
  test_joy_measured();
  test_sdl();
  test_sl();
  test_multi();
  test_cancel();
  test_joy();
  return test_summary("test_input");
}
