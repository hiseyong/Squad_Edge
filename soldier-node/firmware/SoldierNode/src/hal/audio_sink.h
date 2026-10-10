// 오디오 출력 통로(audio sink). config.h의 AUDIO_SINK로 구현을 고른다.
// 호출 쪽(commands, voice_rx, app 피드백)은 어떤 통로인지 모른다 → PWM으로 바꿔도 호출 코드는 그대로.
// 우선순위(CLAUDE.md §6.4): 긴급 > 일반 명령 > 로컬 피드백. 높은 우선순위가 오면 현재 재생을 끊는 것은 출력 쪽 책임.
#pragma once
#include <stdbool.h>
#include <stdint.h>

#define AUDIO_PRIO_FEEDBACK 0
#define AUDIO_PRIO_NORMAL   1
#define AUDIO_PRIO_URGENT   2

void audio_sink_begin(uint8_t soldier_id);
void audio_sink_loop(uint32_t now_ms);

// 조각 ID 시퀀스(공백 구분 ASCII, 예 "c9 cover") 재생. feedback = 로컬 피드백(송신 확인음 등).
void audio_sink_play_clips(const char *clips, uint8_t prio, bool feedback);

// CRC 검증된 ADPCM 음성 재생. adpcm 버퍼는 재생(전달)이 끝나거나 audio_sink_stop_voice()까지 유지해야 한다.
bool audio_sink_play_voice(const uint8_t *adpcm, uint32_t nbytes, uint32_t nsamples, int16_t predictor,
                           uint8_t step_index, uint8_t voice_id, uint8_t prio, uint16_t crc16);
void audio_sink_stop_voice();
bool audio_sink_voice_busy();  // 버퍼를 아직 읽고 있음

uint32_t audio_sink_bytes_out();    // 통로로 내보낸 누적 바이트(USB면 무선 아님)
uint32_t audio_sink_dropped();      // 호스트 없음/공간 부족으로 버린 이벤트 수
const char *audio_sink_name();

// 디버그 텍스트 사본(USB 이어폰 링크가 있을 때만, 없으면 무시). 오디오와 무관.
void audio_sink_debug_text(const char *text, uint8_t len);
