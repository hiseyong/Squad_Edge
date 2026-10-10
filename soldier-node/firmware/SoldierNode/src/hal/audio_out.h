// PWM 이어폰 출력 (CLAUDE.md §6.4) — 설계만, 하드웨어(RC 필터·결합 콘덴서) 미제작 → 빈 구현.
// 구현 시: NRF_PWM3(코어 Tone=PWM2, analogWrite=빈 인스턴스 동적 사용) + EasyDMA, 16MHz/250 = 64kHz,
// REFRESH 7 → 8kHz, 이중 버퍼 256샘플, 조각 이름 → audio_clips.h 조회, AUDIO_GAIN 스케일.
#pragma once
#include <stdbool.h>
#include <stdint.h>

void audio_out_begin();
void audio_out_loop(uint32_t now_ms);
void audio_out_play_clips(const char *clips, uint8_t prio, bool feedback);
bool audio_out_play_voice(const uint8_t *adpcm, uint32_t nbytes, uint32_t nsamples, int16_t predictor,
                          uint8_t step_index, uint8_t voice_id, uint8_t prio);
void audio_out_stop();
bool audio_out_busy();
