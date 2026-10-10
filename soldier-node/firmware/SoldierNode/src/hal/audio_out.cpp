// PWM 이어폰 출력 — 빈 구현(하드웨어 미제작). AUDIO_SINK=PWM일 때만 링크된다.
#include "audio_out.h"

void audio_out_begin() {}
void audio_out_loop(uint32_t now_ms) { (void)now_ms; }
void audio_out_play_clips(const char *clips, uint8_t prio, bool feedback) {
  (void)clips; (void)prio; (void)feedback;
}
bool audio_out_play_voice(const uint8_t *adpcm, uint32_t nbytes, uint32_t nsamples, int16_t predictor,
                          uint8_t step_index, uint8_t voice_id, uint8_t prio) {
  (void)adpcm; (void)nbytes; (void)nsamples; (void)predictor; (void)step_index; (void)voice_id; (void)prio;
  return false;
}
void audio_out_stop() {}
bool audio_out_busy() { return false; }
