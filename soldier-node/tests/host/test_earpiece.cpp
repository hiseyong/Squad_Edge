// 이어폰 링크 프레임 테스트. 기준 벡터는 tools/earpiece.py 자체 테스트와 같다.
#include <string.h>

#include "earpiece_frame.h"
#include "test_util.h"

int main() {
  uint8_t out[300];
  // PLAY, prio 2(긴급), kind 0(명령), "c9 cover"
  const uint8_t pl[] = {2, 0, 'c', '9', ' ', 'c', 'o', 'v', 'e', 'r'};
  const uint8_t expect[] = {0xA5, 0x5A, 0x02, 0x0A, 0x00, 0x02, 0x00, 0x63, 0x39, 0x20,
                            0x63, 0x6F, 0x76, 0x65, 0x72, 0x16, 0xD9};
  CHECK_EQ(ep_encode(EP_PLAY, pl, sizeof pl, out, sizeof out), sizeof expect);
  CHECK(memcmp(out, expect, sizeof expect) == 0);
  // 빈 payload
  CHECK_EQ(ep_encode(EP_VOICE_STOP, 0, 0, out, sizeof out), EP_OVERHEAD);
  // 가장 큰 VOICE_DATA 프레임이 CDC TX 버퍼(256B) 안에 들어간다
  static uint8_t big[EP_MAX_PAYLOAD];
  CHECK_EQ(ep_encode(EP_VOICE_DATA, big, 5 + EP_VOICE_DATA_MAX, out, sizeof out), 5 + EP_VOICE_DATA_MAX + EP_OVERHEAD);
  CHECK(5 + EP_VOICE_DATA_MAX + EP_OVERHEAD <= 256);
  // 너무 긴 payload / 공간 부족
  CHECK_EQ(ep_encode(EP_PLAY, big, EP_MAX_PAYLOAD + 1, out, sizeof out), 0);
  CHECK_EQ(ep_encode(EP_PLAY, pl, sizeof pl, out, 10), 0);
  return test_summary("test_earpiece");
}
