// 분대장 MCU 입출력 (UNO Q, STM32U585 Zephyr): 4×4 키패드 스캔 + SSD1306 128×64 OLED 표시.
//
// 키패드: 핀 1~4(행) → D2~D5, 핀 5~8(열) → D6~D9. Bridge.notify("keypad", key, down) — 판정은 Linux(squad/input/keypad.py).
// OLED(I2C 4핀): GND, VCC → 3.3V, SCL → SCL(D21), SDA → SDA(D20). 주소 0x3C(안 되면 0x3D). Qwiic(Wire1)도 찾는다.
//   한글은 Linux가 나눔고딕으로 그린 1비트 화면을 페이지(8줄 = 128바이트) 단위로 보낸다(RPC 버퍼 256B).
//   Bridge.provide_safe("oled_page", page 0~7, 128바이트) / ("oled_clear") / ("oled_ok") → 주 루프 스레드에서 Wire 사용.
#include <Arduino_RouterBridge.h>
#include <Wire.h>

static const uint8_t ROWS[4] = {2, 3, 4, 5};
static const uint8_t COLS[4] = {6, 7, 8, 9};
static const char *KEYS[4][4] = {
  {"1", "2", "3", "A"}, {"4", "5", "6", "B"}, {"7", "8", "9", "C"}, {"*", "0", "#", "D"},
};
static const uint32_t DEBOUNCE_MS = 20;
static bool stable[4][4], raw_prev[4][4];
static uint32_t changed_at[4][4];

static uint8_t oled_addr = 0;          // 0 = 못 찾음
static TwoWire *bus = &Wire;           // 헤더 SDA/SCL(Wire). 못 찾으면 Qwiic(Wire1)도 본다
static int bus_no = 0;

static bool oled_cmds(const uint8_t *c, size_t n) {
  bus->beginTransmission(oled_addr);
  bus->write(0x00);                    // 명령 스트림
  for (size_t i = 0; i < n; i++) bus->write(c[i]);
  return bus->endTransmission() == 0;
}

static bool oled_find() {
  TwoWire *buses[2] = {&Wire, &Wire1};
  for (int b = 0; b < 2; b++) {
    for (uint8_t a : {0x3C, 0x3D}) {
      buses[b]->beginTransmission(a);
      if (buses[b]->endTransmission() == 0) { bus = buses[b]; bus_no = b; oled_addr = a; return true; }
    }
  }
  return false;
}

static bool oled_init() {
  if (!oled_find()) return false;
  static const uint8_t init[] = {
    0xAE, 0xD5, 0x80, 0xA8, 0x3F, 0xD3, 0x00, 0x40, 0x8D, 0x14, 0x20, 0x02,   // 페이지 주소 모드
    0xA1, 0xC8, 0xDA, 0x12, 0x81, 0xCF, 0xD9, 0xF1, 0xDB, 0x40, 0xA4, 0xA6, 0xAF};
  return oled_cmds(init, sizeof init);
}

static bool oled_write_page(int page, const uint8_t *data, size_t n) {
  if (!oled_addr || page < 0 || page > 7) return false;
  const uint8_t pos[] = {(uint8_t)(0xB0 | page), 0x00, 0x10};
  if (!oled_cmds(pos, sizeof pos)) return false;
  for (size_t i = 0; i < n && i < 128; i += 16) {          // Wire 버퍼(32B) 안에서 16바이트씩
    bus->beginTransmission(oled_addr);
    bus->write(0x40);                                     // 데이터 스트림
    for (size_t j = i; j < i + 16 && j < n; j++) bus->write(data[j]);
    if (bus->endTransmission() != 0) return false;
  }
  return true;
}

bool oled_page(int page, MsgPack::bin_t<uint8_t> data) {
  return oled_write_page(page, data.data(), data.size());
}

bool oled_clear() {
  static const uint8_t zero[128] = {0};
  bool ok = true;
  for (int p = 0; p < 8; p++) ok &= oled_write_page(p, zero, 128);
  return ok;
}

int oled_ok() {                                           // Linux가 연결 확인용: 주소(+256 = Qwiic 버스), 0 = 없음
  if (!oled_addr && oled_init()) oled_clear();            // 나중에 꽂아도 찾는다
  return oled_addr ? oled_addr + (bus_no ? 256 : 0) : 0;
}

void setup() {
  Bridge.begin();
  Wire.begin();
  Wire.setClock(400000);
  Wire1.begin();
  Wire1.setClock(400000);
  for (uint8_t r = 0; r < 4; r++) pinMode(ROWS[r], INPUT);
  for (uint8_t c = 0; c < 4; c++) pinMode(COLS[c], INPUT_PULLUP);
  if (oled_init()) oled_clear();
  Bridge.provide_safe("oled_page", oled_page);
  Bridge.provide_safe("oled_clear", oled_clear);
  Bridge.provide_safe("oled_ok", oled_ok);
}

void loop() {
  uint32_t now = millis();
  for (uint8_t r = 0; r < 4; r++) {
    pinMode(ROWS[r], OUTPUT);
    digitalWrite(ROWS[r], LOW);
    delayMicroseconds(30);
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
