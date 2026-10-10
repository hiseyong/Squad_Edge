// 음성 명령 수신 (프로토콜 §7.4, CLAUDE.md §6.9). 버퍼 40,000B 정적 할당.
//   BEGIN: 형식 검사(codec 1, 8000Hz, 크기 ≤ 40,000B, 청크 수 ≤ VOICE_MAX_CHUNKS) → 아니면 VOICE_RESULT 3
//          수신 중 새 BEGIN: priority 1이면 이전 것 폐기 후 새로 시작, 0이면 새 것 무시(LOG). 같은 voice_id면 재전송으로 보고 새로 시작.
//   CHUNK: chunk_idx 위치에 기록(청크 크기 N은 첫 비마지막 청크 또는 마지막 청크로 계산), 받은 청크 표시
//   END  : 누락 → 2, CRC 불일치 → 1, 정상 → 0 + audio sink 재생 + 마지막 명령(0x11, voice_id) + LED2 미확인
//   시간 제한: 마지막 수신 활동(BEGIN 또는 청크) 후 3초 동안 아무것도 없으면 폐기 + 2
//     (프로토콜 v1.0.1은 "BEGIN 후 3초" → 느린 분대장·긴 발화 대비 무활동 기준으로 변경, v1.0.2 제안. PROGRESS.md 참고)
#pragma once
#include <stdbool.h>
#include <stdint.h>

#include "../core/frame.h"

void voice_rx_begin();
void voice_rx_loop(uint32_t now_ms);
void voice_rx_handle(const frame_msg_t *m);  // MSG_VOICE_BEGIN/CHUNK/END
bool voice_rx_replay(uint8_t voice_id);      // 마지막으로 정상 수신한 음성을 다시 재생(버퍼가 남아 있으면)
bool voice_rx_busy();                        // 음성 수신 중(비콘 스캔을 잠시 멈춰 처리량 확보)
void voice_rx_abort();                       // 침묵 모드 진입: 수신 중인 음성 폐기(VOICE_RESULT 없음 — 연결이 없어 의미 없음)
