// 입력 → 보고 프레임, EMCON별 송신 규칙, 긴급 보고 RPT_ACK 대기·재전송 (CLAUDE.md §6.2, 프로토콜 §2, §8.2).
//   EMCON 0: 모두 큐(최대 32, 넘치면 일반부터 폐기)
//   EMCON 1: 긴급 + ACK/CANNOT_COMPLY/VOICE_RESULT 즉시, 나머지 큐 → 30초마다 일괄
//   EMCON 2: 즉시
//   즉시 보내려 했는데 연결이 없으면 큐에 넣고, 연결(Notify)되면 오래된 순서로 보낸다.
//   긴급(0x01/03/04/06/07)은 EMCON 1/2에서 3초 안에 RPT_ACK가 없으면 같은 seq로 최대 3회 재전송.
#pragma once
#include <stdint.h>

#include "../core/frame.h"
#include "../core/geo.h"

void reporter_begin(uint8_t mode);
void reporter_loop(uint32_t now_ms);
void reporter_set_mode(uint8_t mode);
void reporter_on_link_ready();  // Notify가 켜짐 → 큐 비우기

// 보고 생성: type = MSG_CONTACT … MSG_CASUALTY_SELF. dir = 버튼을 누른 순간의 조이스틱 방향. count = CONTACT 적 수.
void reporter_report(uint8_t type, const geo_joy_t *dir, uint8_t count);
// ACK / CANNOT_COMPLY (ref_type 0x10 버튼 명령 / 0x11 음성)
void reporter_send_ref(uint8_t type, uint8_t ref_type, uint8_t ref_id);
void reporter_send_emcon_state(uint8_t mode);
void reporter_send_voice_result(uint8_t voice_id, uint8_t status);  // 즉시 부류(EMCON 1에서도 바로)
void reporter_send_ranging(const ranging_entry_t *e, uint8_t n);  // v1.1 예정 0x0E, 비긴급(EMCON 1은 30초 묶음)

void reporter_on_rpt_ack(uint8_t ref_seq);
