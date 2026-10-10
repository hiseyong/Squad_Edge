// 미확인 타이머 테스트: 단계 4 장비 시험의 "새 명령 직후 unacked 30s 즉시 발동" 재현·수정 검증.
#include "unack.h"
#include "test_util.h"

// 수정 전 코드와 같은 계산(부호 없는 뺄셈) — 버그 재현용
static bool old_poll(bool active, bool fast, uint32_t since, uint32_t now) {
  return active && !fast && (uint32_t)(now - since) >= 30000;
}

int main() {
  unack_t u;
  unack_init(&u, 30000);

  // 재현: 루프 앞에서 now=1000을 읽고, 프레임 처리 중 millis()=1003에 새 명령 시작 → 같은 루프에서 poll(1000)
  CHECK(old_poll(true, false, 1003, 1000));      // 수정 전: 즉시 발동(버그)
  unack_start(&u, 1003);
  CHECK(!unack_poll(&u, 1000));                  // 수정 후: 발동 안 함
  CHECK(!unack_poll(&u, 1003));
  CHECK(!unack_poll(&u, 31002));                 // 29,999ms
  CHECK(unack_poll(&u, 31003));                  // 정확히 30초에 한 번
  CHECK(!unack_poll(&u, 31004));                 // 한 번만
  CHECK(!unack_poll(&u, 90000));

  // 다음 새 명령: 이전 명령의 빠른 점멸 상태가 넘어오지 않고 시작 시각이 새로 잡힘
  unack_start(&u, 95007);
  CHECK(!u.fast);
  CHECK(!unack_poll(&u, 95005));                 // 같은 루프(now가 2ms 앞섬)
  CHECK(!unack_poll(&u, 125006));
  CHECK(unack_poll(&u, 125007));

  // ACK 후에는 발동 안 함, 다시 새 명령이면 다시 30초
  unack_clear(&u);
  CHECK(!unack_poll(&u, 200000));
  unack_start(&u, 200000);
  CHECK(!unack_poll(&u, 229999));
  CHECK(unack_poll(&u, 230000));

  // 30초 안에 새 명령이 오면 타이머가 새 명령 기준으로 다시 시작
  unack_start(&u, 300000);
  CHECK(!unack_poll(&u, 320000));
  unack_start(&u, 320001);
  CHECK(!unack_poll(&u, 330000));                // 첫 명령 기준 30초지만 새 명령 기준 10초
  CHECK(!unack_poll(&u, 350000));
  CHECK(unack_poll(&u, 350001));

  // millis 오버플로(49.7일) 근처
  unack_start(&u, 0xFFFFF000u);
  CHECK(!unack_poll(&u, 0xFFFFEFF0u));
  CHECK(!unack_poll(&u, 0x00005000u));           // 경과 24,576ms
  CHECK(unack_poll(&u, 0x00006530u));            // 경과 30,000ms
  return test_summary("test_unack");
}
