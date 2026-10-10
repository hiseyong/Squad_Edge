// 분대장 → 병사 프레임 처리 (CLAUDE.md §6.3, 프로토콜 §6, §8).
// 단계 4~6 범위:
//   - 검증: ver/len/dst_mask(core/frame) + src_id = 0(분대장)
//   - CMD_BUTTON: (src, seq) 중복이면 다시 재생만(새 명령 아님), 새 명령이면 문장 조각 결정 → LOG "PLAY: ...",
//     마지막 명령 = (0x10, seq), LED2 미확인 점멸(500ms, 30초 지나면 150ms) → 버튼3 ACK/수행 불가로 해제
//   - EMCON_SET(0x16) / SILENCE(cmd 0x0B): app_set_mode로 실제 전환(단계 7). 침묵 모드에서는 광고로 받은 프레임도 같은 경로
//   - REQ_STATS → STATS, RPT_ACK → reporter, VOICE_* → voice_rx
//   - 재생은 모두 hal/audio_sink 경유(통로는 config.h AUDIO_SINK). DEBUG_LOG면 "PLAY: ..." LOG도 함께.
#pragma once
#include <stdbool.h>
#include <stdint.h>

void commands_begin();
void commands_loop(uint32_t now_ms);
void commands_handle_frame(const uint8_t *buf, uint16_t len);

// 마지막 명령. 없으면 false.
bool commands_last(uint8_t *ref_type, uint8_t *ref_id);

// voice_rx가 음성을 정상 수신·재생 시작 → 마지막 명령 = (0x11, voice_id), LED2 미확인.
void commands_note_voice(uint8_t voice_id);

// 버튼3으로 ACK/수행 불가를 보냈음 → 미확인 상태 해제(LED2 끔).
void commands_acknowledged();

// 조이스틱 짧게: 마지막 명령 다시 듣기(송신 없음).
void commands_replay();

// 분대장이 EMCON_SET/SILENCE로 요청한 모드(0~2). 없으면 -1. F6 단계에서 실제 전환에 사용.
int8_t commands_requested_mode();

// 단계 9: POS_TABLE의 내 위치(0.1m). 표가 없거나 내 항목이 없으면 false(직접 방송 rx/ry = 모름).
bool commands_my_pos(int16_t *x, int16_t *y);
