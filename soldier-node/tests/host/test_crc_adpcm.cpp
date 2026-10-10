// crc16 + adpcm 단위 테스트. 부록 A 기대값은 tools/test_vectors.py와 같아야 한다.
#include <math.h>
#include <stdlib.h>
#include <string.h>

#include "adpcm.h"
#include "crc16.h"
#include "test_util.h"

// tools/test_vectors.py의 EXPECTED_FIRST16 / EXPECTED_CRC16과 같은 값.
static const uint8_t kAppendixAFirst16[16] = {0x70, 0x77, 0x77, 0x77, 0xF1, 0xBB, 0x9B, 0x18,
                                              0x44, 0x53, 0x22, 0x82, 0xB8, 0xCC, 0xAC, 0x9B};
static const uint16_t kAppendixACrc16 = 0x0166;

static int16_t sine[8000];
static int16_t decoded[8000];
static uint8_t encoded[4000];

static void test_crc16() {
  const char *s = "123456789";
  CHECK_EQ(crc16_ccitt_false((const uint8_t *)s, 9), 0x29B1);
  // 나눠서 계산해도 같아야 한다.
  uint16_t c = crc16_update(CRC16_INIT, (const uint8_t *)s, 4);
  c = crc16_update(c, (const uint8_t *)s + 4, 5);
  CHECK_EQ(c, 0x29B1);
  CHECK_EQ(crc16_ccitt_false((const uint8_t *)s, 0), 0xFFFF);
}

static void make_sine() {
  for (int i = 0; i < 8000; i++) {
    sine[i] = (int16_t)lround(8000.0 * sin(2.0 * 3.14159265358979323846 * 440.0 * i / 8000.0));
  }
}

static void test_appendix_a() {
  adpcm_state_t st;
  adpcm_init(&st, 0, 0);
  CHECK_EQ(adpcm_encode(&st, sine, 8000, encoded), 4000);
  CHECK(memcmp(encoded, kAppendixAFirst16, 16) == 0);
  if (memcmp(encoded, kAppendixAFirst16, 16) != 0) {
    printf("  first16:");
    for (int i = 0; i < 16; i++) printf(" %02X", encoded[i]);
    printf("\n");
  }
  CHECK_EQ(crc16_ccitt_false(encoded, 4000), kAppendixACrc16);
  adpcm_state_t enc_end = st;

  // 디코드 → 오차 확인, 최종 상태 일치
  adpcm_init(&st, 0, 0);
  adpcm_decode(&st, encoded, 8000, decoded);
  CHECK_EQ(st.predictor, enc_end.predictor);
  CHECK_EQ(st.step_index, enc_end.step_index);
  int max_err = 0;
  for (int i = 200; i < 8000; i++) {  // 처음 스텝 수렴 구간 이후
    int e = abs(sine[i] - decoded[i]);
    if (e > max_err) max_err = e;
  }
  CHECK(max_err < 800);  // 진폭 8000 대비 10% 미만
  printf("  adpcm 안정 구간 최대 오차 %d\n", max_err);

  // 니블 하나씩 디코드(스트리밍 재생 경로)와 일괄 디코드가 같아야 한다.
  adpcm_init(&st, 0, 0);
  bool same = true;
  for (int i = 0; i < 8000; i++) {
    uint8_t b = encoded[i >> 1];
    int16_t s = adpcm_decode_nibble(&st, (i & 1) ? (uint8_t)(b >> 4) : (uint8_t)(b & 0x0F));
    if (s != decoded[i]) same = false;
  }
  CHECK(same);
}

static void test_adpcm_misc() {
  adpcm_state_t st;
  uint8_t out[2];
  int16_t one = 1000;
  adpcm_init(&st, 0, 0);
  CHECK_EQ(adpcm_encode(&st, &one, 1, out), 1);
  CHECK_EQ(out[0] >> 4, 0);       // 홀수 개 → 상위 니블 0
  CHECK_EQ(out[0] & 0x0F, 7);     // 첫 샘플은 하위 니블

  // 클램프: 큰 값/인덱스 범위
  adpcm_init(&st, 32767, 88);
  CHECK_EQ(adpcm_decode_nibble(&st, 0x7), 32767);
  CHECK_EQ(st.step_index, 88);
  adpcm_init(&st, -32768, 0);
  CHECK_EQ(adpcm_decode_nibble(&st, 0xF), -32768);
  adpcm_init(&st, 0, 200);
  CHECK_EQ(st.step_index, 88);
}

int main() {
  make_sine();
  test_crc16();
  test_appendix_a();
  test_adpcm_misc();
  return test_summary("test_crc_adpcm");
}
