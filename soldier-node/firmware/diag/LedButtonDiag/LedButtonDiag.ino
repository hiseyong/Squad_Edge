// LED/온보드 버튼 극성 진단 펌웨어 (본 펌웨어와 분리).
// 0~10초: LED1=HIGH, LED2=LOW, LED3=HIGH, LED4=LOW 고정 → 어느 LED가 켜지는지로 LED 켜짐 레벨 판정.
// 10초 이후: 버튼1~4(INPUT_PULLUP) 원시값을 LED1~4에 그대로 출력(입력 HIGH → 핀 HIGH).
// Serial, Bluefruit 사용 안 함. 블로킹 delay 없음.
#include <Arduino.h>

static const uint8_t LED_PINS[4] = { PIN_LED1, PIN_LED2, PIN_LED3, PIN_LED4 };
static const uint8_t BTN_PINS[4] = { PIN_BUTTON1, PIN_BUTTON2, PIN_BUTTON3, PIN_BUTTON4 };
static const uint8_t PHASE1_LEVELS[4] = { HIGH, LOW, HIGH, LOW };
static const uint32_t PHASE1_MS = 10000;

static uint32_t bootMs = 0;

void setup() {
  for (int i = 0; i < 4; i++) {
    pinMode(LED_PINS[i], OUTPUT);
    digitalWrite(LED_PINS[i], PHASE1_LEVELS[i]);
    pinMode(BTN_PINS[i], INPUT_PULLUP);
  }
  bootMs = millis();
}

void loop() {
  if (millis() - bootMs < PHASE1_MS) return;  // 1단계: 고정 출력 유지
  for (int i = 0; i < 4; i++) {
    digitalWrite(LED_PINS[i], digitalRead(BTN_PINS[i]));
  }
}
