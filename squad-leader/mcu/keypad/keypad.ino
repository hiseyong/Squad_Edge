// 분대장 4×4 키패드 스캐너 (UNO Q MCU, STM32U585 Zephyr) → Linux 앱으로 키 눌림/뗌 알림.
//
// 배선: 키패드 핀 1~4(행1~4) → D2~D5, 핀 5~8(열1~4) → D6~D9. 외부 저항·전원 없음.
// 스캔: 열은 INPUT_PULLUP, 행은 평소 고임피던스(INPUT) → 한 행씩 OUTPUT LOW로 내리고 열을 읽는다(LOW = 눌림).
//       여러 키를 동시에 눌러도 행끼리 단락되지 않게 쓰지 않는 행은 INPUT으로 둔다.
// 알림: Bridge.notify("keypad", key, down) — key는 "1"~"9","0","*","#","A"~"D", down 1 = 눌림 / 0 = 뗌.
//       짧게·길게·누르고 있기 판정은 Linux 쪽(squad/input/keypad.py)이 한다(시간 기준을 한 곳에서 조정).
// 디바운스 20 ms(병사 단말과 같음), 스캔 주기 약 5 ms.
#include <Arduino_RouterBridge.h>

static const uint8_t ROWS[4] = {2, 3, 4, 5};
static const uint8_t COLS[4] = {6, 7, 8, 9};
static const char *KEYS[4][4] = {
  {"1", "2", "3", "A"},
  {"4", "5", "6", "B"},
  {"7", "8", "9", "C"},
  {"*", "0", "#", "D"},
};
static const uint32_t DEBOUNCE_MS = 20;

static bool stable[4][4];       // 확정된 상태
static bool raw_prev[4][4];     // 직전 읽은 값
static uint32_t changed_at[4][4];

void setup() {
  Bridge.begin();
  for (uint8_t r = 0; r < 4; r++) pinMode(ROWS[r], INPUT);
  for (uint8_t c = 0; c < 4; c++) pinMode(COLS[c], INPUT_PULLUP);
}

void loop() {
  uint32_t now = millis();
  for (uint8_t r = 0; r < 4; r++) {
    pinMode(ROWS[r], OUTPUT);
    digitalWrite(ROWS[r], LOW);
    delayMicroseconds(30);                       // 선 정착
    for (uint8_t c = 0; c < 4; c++) {
      bool pressed = digitalRead(COLS[c]) == LOW;
      if (pressed != raw_prev[r][c]) {
        raw_prev[r][c] = pressed;
        changed_at[r][c] = now;
      } else if (pressed != stable[r][c] && (uint32_t)(now - changed_at[r][c]) >= DEBOUNCE_MS) {
        stable[r][c] = pressed;
        Bridge.notify("keypad", KEYS[r][c], pressed ? 1 : 0);
      }
    }
    pinMode(ROWS[r], INPUT);
  }
  delay(5);
}
