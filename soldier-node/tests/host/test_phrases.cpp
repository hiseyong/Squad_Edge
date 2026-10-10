// phrases 단위 테스트: 프로토콜 §6.2 템플릿 → 조각 시퀀스, 방향 변환, §11.1 명령 예시.
#include <string.h>

#include "phrases.h"
#include "test_util.h"

static const char *say(uint8_t code, uint16_t az, uint8_t dist, uint8_t extra, uint16_t heading, uint16_t rally_az,
                       uint8_t *flags) {
  static char buf[64];
  msg_cmd_button_t c = {code, az, dist, extra, 0};
  phrase_t p;
  phrases_for_cmd(&c, heading, rally_az, &p);
  phrases_join(&p, buf, sizeof buf);
  if (flags) *flags = p.flags;
  return buf;
}

#define SAY_EQ(expect, ...) CHECK(strcmp(say(__VA_ARGS__), expect) == 0)

int main() {
  const uint16_t N = 0xFFFF;
  uint8_t f;
  // §11.1 예시 1: 전원 엄폐, 방위 270, 거리 없음 → 내 방위 0이면 9시 엄폐
  SAY_EQ("c9 cover", CMD_TAKE_COVER, 270, 0xFF, 0, 0, N, &f);
  CHECK_EQ(f, 0);
  // §11.1 예시 2: 적 위치 알림, 방위 45, 원거리, 3명 → "적 3 2시 원거리"
  SAY_EQ("enemy n3 c2 far", CMD_ENEMY_INFO, 45, 2, 3, 0, N, &f);
  // 프로토콜 §9.3 예: "9시 엄폐"는 내 방위에 따라 달라진다 (방위 270, 내 방위 90 → 6시)
  SAY_EQ("c6 cover", CMD_TAKE_COVER, 270, 0xFF, 0, 90, N, &f);
  // 방향 선택형: azimuth 없으면 방향 없이, 플래그 없음
  SAY_EQ("cover", CMD_TAKE_COVER, N, 0xFF, 0, 0, N, &f);
  CHECK_EQ(f, 0);
  SAY_EQ("c3 advance", CMD_ADVANCE, 90, 0xFF, 0, 0, N, &f);
  SAY_EQ("c12 withdraw", CMD_WITHDRAW, 0, 0xFF, 0, 0, N, &f);
  // 방향 필수형: azimuth 없으면 방향 없이 + 플래그
  SAY_EQ("open_fire", CMD_OPEN_FIRE, N, 0xFF, 0, 0, N, &f);
  CHECK_EQ(f, PHRASE_F_NO_DIR);
  SAY_EQ("c1 near open_fire", CMD_OPEN_FIRE, 15, 0, 0, 0, N, &f);
  SAY_EQ("c11 mid open_fire", CMD_OPEN_FIRE, 330, 1, 0, 0, N, &f);
  SAY_EQ("c4 observe", CMD_OBSERVE, 105, 0xFF, 0, 0, N, &f);
  // ENEMY_INFO 적 수: 0 미상, 5 이상 다수
  SAY_EQ("enemy unknown c6", CMD_ENEMY_INFO, 180, 0xFF, 0, 0, N, &f);
  SAY_EQ("enemy many c6 near", CMD_ENEMY_INFO, 180, 0, 5, 0, N, &f);
  SAY_EQ("enemy many c6 near", CMD_ENEMY_INFO, 180, 0, 9, 0, N, &f);
  // RALLY: 명령의 azimuth는 무시하고 분대장 방향(rally_az)을 쓴다
  SAY_EQ("rally", CMD_RALLY, 90, 0xFF, 0, 0, N, &f);
  CHECK_EQ(f, PHRASE_F_NO_DIR);
  SAY_EQ("c6 rally", CMD_RALLY, 90, 0xFF, 0, 0, 180, &f);
  // 방향 없는 명령
  SAY_EQ("halt", CMD_HALT, 90, 2, 3, 0, N, &f);
  SAY_EQ("cease_fire", CMD_CEASE_FIRE, N, 0xFF, 0, 0, N, &f);
  SAY_EQ("report_status", CMD_REPORT_STATUS, N, 0xFF, 0, 0, N, &f);
  SAY_EQ("silence", CMD_SILENCE, N, 0xFF, 0, 0, N, &f);
  SAY_EQ("hold", CMD_HOLD, N, 0xFF, 0, 0, N, &f);
  SAY_EQ("cancel", CMD_CANCEL, N, 0xFF, 0, 0, N, &f);
  // 내 방위 없음(0xFFFF) → 진북 기준
  SAY_EQ("c9 cover", CMD_TAKE_COVER, 270, 0xFF, 0, N, N, &f);
  // 알 수 없는 코드
  SAY_EQ("", 0x0D, 0, 0, 0, 0, N, &f);
  CHECK_EQ(f, PHRASE_F_UNKNOWN_CMD);
  CHECK(strcmp(phrases_cmd_name(CMD_TAKE_COVER), "TAKE_COVER") == 0);
  CHECK(strcmp(phrases_cmd_name(0x0D), "?") == 0);
  // join 버퍼가 작으면 잘리되 NUL 종료
  {
    msg_cmd_button_t c = {CMD_ENEMY_INFO, 45, 2, 3, 0};
    phrase_t p;
    char small[8];
    phrases_for_cmd(&c, 0, N, &p);
    CHECK_EQ(phrases_join(&p, small, sizeof small), 7);
    CHECK(strcmp(small, "enemy n") == 0);
  }
  return test_summary("test_phrases");
}
