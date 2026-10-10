// LED1~4 제어 (프로토콜 §9.4). LED 켜짐 레벨은 config.h의 LED_ON_LEVEL(이 보드는 active-low).
// 점멸·펄스는 leds_update()에서 millis 기준으로 처리(비차단). loop 태스크에서만 호출한다.
#pragma once
#include <stdbool.h>
#include <stdint.h>

#define LED_IDX_CONN   0  // LED1: 연결 상태
#define LED_IDX_UNACK  1  // LED2: 미확인 명령
#define LED_IDX_TX     2  // LED3: 송신 순간
#define LED_IDX_MODE   3  // LED4: EMCON 모드

void leds_begin();                                           // 4개 모두 출력 + 끔
void leds_set(uint8_t idx, bool on);                         // 고정 켬/끔(점멸 해제)
void leds_blink(uint8_t idx, uint16_t period_ms, uint16_t on_ms);  // 주기 점멸
void leds_pulse(uint8_t idx, uint16_t on_ms);                // 잠깐 켰다가 원래 상태(고정/점멸)로
void leds_update(uint32_t now_ms);
