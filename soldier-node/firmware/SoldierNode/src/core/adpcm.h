// IMA ADPCM 4bit (프로토콜 §7.1). 한 바이트에 샘플 2개, 하위 니블이 먼저.
// 디코더(펌웨어용) + 인코더(테스트용). Arduino 비의존, C 호환, 동적 할당 없음.
#pragma once
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
  int16_t predictor;   // 현재 예측값
  uint8_t step_index;  // 0~88
} adpcm_state_t;

void adpcm_init(adpcm_state_t *st, int16_t predictor, uint8_t step_index);

// 니블(하위 4비트) 하나를 디코드해 샘플 하나를 돌려준다. 스트리밍 재생용.
int16_t adpcm_decode_nibble(adpcm_state_t *st, uint8_t nibble);

// 샘플 하나를 인코드해 니블을 돌려준다.
uint8_t adpcm_encode_sample(adpcm_state_t *st, int16_t sample);

// in에서 nsamples개를 디코드(첫 샘플 = in[0]의 하위 니블). out은 nsamples개 공간.
void adpcm_decode(adpcm_state_t *st, const uint8_t *in, size_t nsamples, int16_t *out);

// nsamples개를 인코드. out은 (nsamples+1)/2 바이트 공간. 홀수면 마지막 상위 니블 = 0.
// 반환: 쓴 바이트 수.
size_t adpcm_encode(adpcm_state_t *st, const int16_t *in, size_t nsamples, uint8_t *out);

#ifdef __cplusplus
}
#endif
