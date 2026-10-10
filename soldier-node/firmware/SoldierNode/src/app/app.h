// 최상위 상태기계: 무선 이벤트 → LED, RX 프레임 → commands, 입력 → reporter, EMCON 모드, LOG.
#pragma once
#include <stdbool.h>
#include <stdint.h>

#include "../core/frame.h"

void app_begin();
void app_loop();

uint8_t app_next_seq();  // 송신자 순번(프로토콜 §4), 호출마다 +1

// 완성된 프레임 송신(notify 하나). 연결/Notify 없으면 false(실패로 세지 않음).
// 연결돼 있는데 송신이 실패하면 실패 수를 세고 다음 LOG에 표시한다. LOG가 아닌 프레임이 나가면 LED3 펄스.
bool app_send_raw(const uint8_t *frame, uint16_t len);

// m->seq/src를 채워 인코드 후 app_send_raw.
bool app_send(frame_msg_t *m);

// DEBUG_LOG 빌드에서만 0x7F LOG 송신(ASCII 최대 100바이트, printf 형식). 송신 불가면 버림.
void app_log(const char *fmt, ...) __attribute__((format(printf, 1, 2)));

// 로컬 피드백: 조각 ID들(공백 구분)을 audio sink로(우선순위 최저), DEBUG_LOG면 "FEEDBACK: <조각> (<설명>)" LOG.
void app_feedback(const char *clips, const char *note = nullptr);

uint8_t app_mode();  // 현재 EMCON 모드 0/1/2

// EMCON 모드 전환(조이스틱 길게 / 버튼1+버튼2 2초 / EMCON_SET / SILENCE). reason은 LOG용.
void app_set_mode(uint8_t mode, const char *reason);
