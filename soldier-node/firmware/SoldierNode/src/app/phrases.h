// 문장 템플릿 → 음성 조각 ID 시퀀스 (CLAUDE.md §6.5, 프로토콜 §6.2).
// 조각 ID는 tools/gen_clips.py 표(CLAUDE.md §6.5)와 같은 문자열. 오디오 단계 전까지는 LOG "PLAY: ..."로 출력.
// Arduino 비의존(core만 사용) → 호스트 테스트 대상.
#pragma once
#include <stddef.h>
#include <stdint.h>

#include "../core/frame.h"

#define PHRASE_MAX_CLIPS 6

typedef struct {
  const char *clip[PHRASE_MAX_CLIPS];
  uint8_t n;
  uint8_t flags;  // PHRASE_F_*
} phrase_t;

#define PHRASE_F_NO_DIR      0x01  // 방향이 필수/선택인데 azimuth 없음(또는 RALLY인데 분대장 방향 모름) → 방향 없이 재생
#define PHRASE_F_UNKNOWN_CMD 0x02  // 알 수 없는 cmd_code

// CMD_BUTTON → 조각 시퀀스. my_heading: 내 방위(0xFFFF면 진북 기준). rally_az: 분대장(원점) 방향, 모르면 0xFFFF.
void phrases_for_cmd(const msg_cmd_button_t *c, uint16_t my_heading, uint16_t rally_az, phrase_t *out);

// 다른 병사 보고(PEER_REPORT, 프로토콜 §9.3) → "적 3, 2시, 근거리" = "enemy n3 c2 near".
// type: CONTACT/SUSPICIOUS/HAZARD/CASUALTY_FOUND. count는 CONTACT만. clock 0 = 방향 없음, dist_band 0xFF = 거리 없음.
void phrases_for_peer(uint8_t type, uint8_t count, uint8_t clock, uint8_t dist_band, phrase_t *out);

// "c9 cover"처럼 공백으로 이어 붙인다. 반환: 쓴 길이.
size_t phrases_join(const phrase_t *p, char *buf, size_t cap);

const char *phrases_cmd_name(uint8_t cmd_code);  // "TAKE_COVER" 등, 모르면 "?"
