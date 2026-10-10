// 표준 IMA ADPCM (스텝 표 89개, 인덱스 표 16개).
#include "adpcm.h"

static const int16_t kStepTable[89] = {
  7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41, 45,
  50, 55, 60, 66, 73, 80, 88, 97, 107, 118, 130, 143, 157, 173, 190, 209, 230,
  253, 279, 307, 337, 371, 408, 449, 494, 544, 598, 658, 724, 796, 876, 963,
  1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066, 2272, 2499, 2749, 3024, 3327,
  3660, 4026, 4428, 4871, 5358, 5894, 6484, 7132, 7845, 8630, 9493, 10442, 11487,
  12635, 13899, 15289, 16818, 18500, 20350, 22385, 24623, 27086, 29794, 32767
};

static const int8_t kIndexTable[16] = {
  -1, -1, -1, -1, 2, 4, 6, 8,
  -1, -1, -1, -1, 2, 4, 6, 8
};

static int16_t clamp16(int32_t v) {
  if (v > 32767) return 32767;
  if (v < -32768) return -32768;
  return (int16_t)v;
}

static uint8_t clamp_index(int v) {
  if (v < 0) return 0;
  if (v > 88) return 88;
  return (uint8_t)v;
}

void adpcm_init(adpcm_state_t *st, int16_t predictor, uint8_t step_index) {
  st->predictor = predictor;
  st->step_index = clamp_index(step_index);
}

int16_t adpcm_decode_nibble(adpcm_state_t *st, uint8_t nibble) {
  int32_t step = kStepTable[st->step_index];
  int32_t diff = step >> 3;
  if (nibble & 4) diff += step;
  if (nibble & 2) diff += step >> 1;
  if (nibble & 1) diff += step >> 2;
  int32_t pred = st->predictor;
  pred = (nibble & 8) ? pred - diff : pred + diff;
  st->predictor = clamp16(pred);
  st->step_index = clamp_index(st->step_index + kIndexTable[nibble & 0x0F]);
  return st->predictor;
}

uint8_t adpcm_encode_sample(adpcm_state_t *st, int16_t sample) {
  int32_t step = kStepTable[st->step_index];
  int32_t diff = (int32_t)sample - st->predictor;
  uint8_t nibble = 0;
  if (diff < 0) {
    nibble = 8;
    diff = -diff;
  }
  // 디코더와 같은 재구성값을 추적해야 하므로 decode_nibble로 상태를 갱신한다.
  if (diff >= step) { nibble |= 4; diff -= step; }
  if (diff >= (step >> 1)) { nibble |= 2; diff -= step >> 1; }
  if (diff >= (step >> 2)) { nibble |= 1; }
  adpcm_decode_nibble(st, nibble);
  return nibble;
}

void adpcm_decode(adpcm_state_t *st, const uint8_t *in, size_t nsamples, int16_t *out) {
  for (size_t i = 0; i < nsamples; i++) {
    uint8_t b = in[i >> 1];
    uint8_t nibble = (i & 1) ? (uint8_t)(b >> 4) : (uint8_t)(b & 0x0F);
    out[i] = adpcm_decode_nibble(st, nibble);
  }
}

size_t adpcm_encode(adpcm_state_t *st, const int16_t *in, size_t nsamples, uint8_t *out) {
  size_t nbytes = (nsamples + 1) / 2;
  for (size_t i = 0; i < nsamples; i++) {
    uint8_t nibble = adpcm_encode_sample(st, in[i]);
    if (i & 1) {
      out[i >> 1] |= (uint8_t)(nibble << 4);
    } else {
      out[i >> 1] = nibble;
    }
  }
  return nbytes;
}
