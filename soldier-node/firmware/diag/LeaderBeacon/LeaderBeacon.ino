// 분대장 비콘 — 침묵 모드(EMCON 0) 광고 송신기 (프로토콜 §3.2). 예비 보드 A용, 병사 펌웨어와 분리.
//
// 광고: Legacy, 연결·스캔 불가(ADV_NONCONN_IND), Flags + Manufacturer Specific Data(Company ID 0xFFFF + 프레임),
//       간격 100ms로 3초간 반복 후 정지. 새 명령이 오면 진행 중인 광고를 멈추고 새로 시작.
// 명령 입력
//   1) 온보드 버튼(눌림 = LOW): 1 정지(긴급) / 2 엄폐 270도(긴급) / 3 사격 중지 / 4 집결 — 전원(dst 0x1F)
//   2) USB 시리얼(UNO Q·맥 등): 프레임 hex 한 줄 + 줄바꿈. 예) "01 10 05 00 1F 06 02 0E 01 FF 00 01"
//      받아들이는 프레임: ver 01, src 00, CMD_BUTTON(0x10, len 6) 또는 EMCON_SET(0x16, len 1). seq는 보낸 쪽이 정한다.
//      응답: "OK tx type=10 seq=05 dst=1F len=12 3s" / "ERR <이유>" / 광고 끝나면 "DONE seq=05"
//      "help" → 사용법. 시리얼 속도는 아무 값(USB CDC) — 단, 1200bps로 열면 부트로더로 들어가니 피할 것.
// 분대장 위치 비콘(단계 9 보충, 프로토콜 v1.1 예정): 명령 방송이 없을 때 BEACON(0x20, src 0, dst FF, heading)을
//   500ms 간격으로 계속 광고 → 병사가 RSSI를 재서 RANGING에 peer 0으로 넣는다(위치 복원 기준점).
//   동시에 병사 비콘(0x20, src 1~5)을 수동 스캔해 USB로 "BCN <src> <rssi> <heading>" 한 줄씩 → mock_leader가
//   분대장 줄(ID 0)의 RSSI 중앙값을 만든다. 광고 세트가 하나라 명령 방송(3초) 동안은 비콘을 멈췄다가 다시 시작.
//   "beacon on" / "beacon off"(USB)로 켜고 끈다. 기본 켜짐. 침묵 모드(EMCON 0) 시연 중에는 off 권장(분대장도 방출 통제).
// LED(active-low): LED1 명령 방송 중 켜짐, LED2 USB 호스트 연결(DTR), LED3 마지막 명령이 USB에서 옴, LED4 위치 비콘 중.
#include <Adafruit_TinyUSB.h>
#include <Arduino.h>
#include <bluefruit.h>

static const uint8_t LED_ON = LOW, LED_OFF = HIGH;
static const uint16_t COMPANY_ID = 0xFFFF;
static const uint16_t ADV_INTERVAL = 160;  // 0.625ms 단위 → 100ms
static const uint16_t ADV_SECONDS = 3;
static const int8_t TX_POWER = 0;          // dBm
static const uint8_t BTN_PINS[4] = {PIN_BUTTON1, PIN_BUTTON2, PIN_BUTTON3, PIN_BUTTON4};
static const uint16_t BEACON_INTERVAL = 800;  // 0.625ms 단위 → 500ms (병사 BEACON_INTERVAL_MS와 같게)
static const uint16_t LEADER_HEADING = 0xFFFF; // 분대장 방위 센서 없음
static const uint16_t SCAN_INTERVAL = 320, SCAN_WINDOW = 240;  // 200ms 중 150ms

static uint8_t s_seq = 0;
static uint8_t s_last_seq = 0;
static volatile bool s_adv_done = false;
static char s_line[96];
static uint8_t s_line_len = 0;
static bool s_btn_state[4];
static uint32_t s_btn_t[4];
static bool s_beacon_on = true;
static bool s_cmd_adv = false;      // 명령 방송 중(3초)
static bool s_beacon_running = false;
static uint8_t s_beacon_seq = 0;
// 병사 비콘 수신 링(스캔 콜백 = BLE 태스크 → loop에서 USB로)
typedef struct { uint8_t src; int8_t rssi; uint16_t heading; } bcn_t;
static bcn_t s_bcn[16];
static volatile uint8_t s_bcn_head = 0, s_bcn_tail = 0;

static void say(const char *text) {  // 블로킹 없이: 호스트가 없거나 버퍼가 부족하면 버림
  size_t n = strlen(text);
  if (Serial.dtr() && Serial.availableForWrite() >= (int)n + 2) {
    Serial.write((const uint8_t *)text, n);
    Serial.write((const uint8_t *)"\r\n", 2);
  }
}

static void on_adv_stop() { s_adv_done = true; }  // 명령 방송 3초 끝(비콘은 시간 제한 없음 → 호출 안 됨)

static bool start_beacon() {
  // [ver 01, type 20, seq, src 00, dst FF, len 2, heading LE]
  uint8_t msd[2 + 8] = {(uint8_t)(COMPANY_ID & 0xFF), (uint8_t)(COMPANY_ID >> 8), 0x01, 0x20, s_beacon_seq++, 0x00, 0xFF, 2,
                        (uint8_t)(LEADER_HEADING & 0xFF), (uint8_t)(LEADER_HEADING >> 8)};
  if (Bluefruit.Advertising.isRunning()) Bluefruit.Advertising.stop();
  Bluefruit.Advertising.clearData();
  Bluefruit.Advertising.addFlags(BLE_GAP_ADV_FLAGS_LE_ONLY_GENERAL_DISC_MODE);
  if (!Bluefruit.Advertising.addManufacturerData(msd, sizeof msd)) return false;
  Bluefruit.Advertising.setInterval(BEACON_INTERVAL, BEACON_INTERVAL);
  Bluefruit.Advertising.setFastTimeout(0);
  s_beacon_running = Bluefruit.Advertising.start(0);
  digitalWrite(PIN_LED4, s_beacon_running ? LED_ON : LED_OFF);
  return s_beacon_running;
}

static void stop_beacon() {
  if (s_beacon_running && Bluefruit.Advertising.isRunning()) Bluefruit.Advertising.stop();
  s_beacon_running = false;
  digitalWrite(PIN_LED4, LED_OFF);
}

static void on_scan(ble_gap_evt_adv_report_t *report) {
  uint8_t msd[31];
  uint8_t n = Bluefruit.Scanner.parseReportByType(report, BLE_GAP_AD_TYPE_MANUFACTURER_SPECIFIC_DATA, msd, sizeof msd);
  // 병사 비콘: 0xFFFF + [01 20 seq src(1~5) FF 02 heading LE]
  if (n == 10 && msd[0] == (COMPANY_ID & 0xFF) && msd[1] == (COMPANY_ID >> 8) && msd[2] == 0x01 && msd[3] == 0x20 &&
      msd[5] >= 1 && msd[5] <= 5 && msd[7] == 2) {
    uint8_t head = s_bcn_head, next = (uint8_t)((head + 1) & 15);
    if (next != s_bcn_tail) {
      s_bcn[head] = {msd[5], report->rssi, (uint16_t)(msd[8] | (msd[9] << 8))};
      __DMB();
      s_bcn_head = next;
    }
  }
  Bluefruit.Scanner.resume();
}

static bool broadcast(const uint8_t *frame, uint8_t len, bool from_usb) {
  uint8_t msd[2 + 24];
  if (len > 24) return false;  // 31 - Flags 3 - AD 헤더 2 - Company ID 2
  msd[0] = (uint8_t)(COMPANY_ID & 0xFF);
  msd[1] = (uint8_t)(COMPANY_ID >> 8);
  memcpy(msd + 2, frame, len);
  stop_beacon();  // 광고 세트 하나: 명령 방송 동안 위치 비콘은 멈춤
  Bluefruit.Advertising.clearData();
  Bluefruit.Advertising.addFlags(BLE_GAP_ADV_FLAGS_LE_ONLY_GENERAL_DISC_MODE);
  if (!Bluefruit.Advertising.addManufacturerData(msd, (uint8_t)(2 + len))) return false;
  Bluefruit.Advertising.setInterval(ADV_INTERVAL, ADV_INTERVAL);
  Bluefruit.Advertising.setFastTimeout(ADV_SECONDS);
  s_adv_done = false;
  if (!Bluefruit.Advertising.start(ADV_SECONDS)) return false;
  s_cmd_adv = true;
  s_last_seq = frame[2];
  digitalWrite(PIN_LED1, LED_ON);
  digitalWrite(PIN_LED3, from_usb ? LED_ON : LED_OFF);
  char msg[64];
  snprintf(msg, sizeof msg, "OK tx type=%02X seq=%02X dst=%02X len=%u %us", frame[1], frame[2], frame[4], len,
           ADV_SECONDS);
  say(msg);
  return true;
}

static void send_button(uint8_t idx) {
  // cmd_code, azimuth, dist_band, extra, priority (프로토콜 §6)
  static const uint8_t kCmd[4][6] = {
    {0x01, 0xFF, 0xFF, 0xFF, 0x00, 0x01},  // HALT 정지, 긴급
    {0x02, 0x0E, 0x01, 0xFF, 0x00, 0x01},  // TAKE_COVER 엄폐, 방위 270(0x010E), 긴급
    {0x07, 0xFF, 0xFF, 0xFF, 0x00, 0x00},  // CEASE_FIRE 사격 중지
    {0x05, 0xFF, 0xFF, 0xFF, 0x00, 0x00},  // RALLY 집결(방향은 병사가 계산)
  };
  uint8_t f[12] = {0x01, 0x10, s_seq++, 0x00, 0x1F, 0x06};
  memcpy(f + 6, kCmd[idx], 6);
  if (!broadcast(f, sizeof f, false)) say("ERR adv start");
}

static int hexval(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  return -1;
}

static void handle_line(const char *line) {
  if (!strcmp(line, "beacon on") || !strcmp(line, "beacon off")) {
    s_beacon_on = line[8] == 'n';
    if (!s_cmd_adv) {
      if (s_beacon_on) start_beacon();
      else stop_beacon();
    }
    say(s_beacon_on ? "OK beacon on (BEACON 0x20 src 00, 500ms)" : "OK beacon off");
    return;
  }
  if (!strcmp(line, "help") || !strcmp(line, "?")) {
    say("send frame hex: e.g. 01 10 05 00 1F 06 02 0E 01 FF 00 01 (CMD_BUTTON) / 01 16 06 00 1F 01 01 (EMCON_SET)");
    say("rules: ver 01, src 00, type 10 (len 6) or 16 (len 1); broadcast 100ms x 3s; buttons 1-4 = HALT/COVER270/CEASE/RALLY");
    say("beacon on|off: leader position beacon (BEACON 0x20 src 00, 500ms); soldier beacons -> 'BCN <src> <rssi> <heading>'");
    return;
  }
  uint8_t f[32];
  uint8_t n = 0;
  int hi = -1;
  for (const char *p = line; *p; p++) {
    if (*p == ' ' || *p == ',' || *p == ':') continue;
    int v = hexval(*p);
    if (v < 0) { say("ERR not hex"); return; }
    if (hi < 0) hi = v;
    else {
      if (n >= sizeof f) { say("ERR too long"); return; }
      f[n++] = (uint8_t)(hi << 4 | v);
      hi = -1;
    }
  }
  if (hi >= 0) { say("ERR odd hex digits"); return; }
  if (n < 6) { say("ERR shorter than header"); return; }
  if (f[0] != 0x01) { say("ERR ver != 01"); return; }
  if (f[3] != 0x00) { say("ERR src != 00 (leader)"); return; }
  if (f[5] != n - 6) { say("ERR len field != payload length"); return; }
  if (!((f[1] == 0x10 && f[5] == 6) || (f[1] == 0x16 && f[5] == 1))) {
    say("ERR only CMD_BUTTON(10, len 6) or EMCON_SET(16, len 1) allowed in silent mode");
    return;
  }
  if (!broadcast(f, n, true)) say("ERR adv start");
}

void setup() {
  const uint8_t leds[4] = {PIN_LED1, PIN_LED2, PIN_LED3, PIN_LED4};
  for (uint8_t i = 0; i < 4; i++) {
    pinMode(leds[i], OUTPUT);
    digitalWrite(leds[i], LED_OFF);
    pinMode(BTN_PINS[i], INPUT_PULLUP);
  }
  Serial.begin(115200);  // 호스트 대기 없음
  Bluefruit.autoConnLed(false);
  Bluefruit.begin(1, 0);
  Bluefruit.setName("SQ1-LEADER-BEACON");
  Bluefruit.setTxPower(TX_POWER);
  Bluefruit.Advertising.setType(BLE_GAP_ADV_TYPE_NONCONNECTABLE_NONSCANNABLE_UNDIRECTED);
  Bluefruit.Advertising.setInterval(ADV_INTERVAL, ADV_INTERVAL);
  Bluefruit.Advertising.setFastTimeout(ADV_SECONDS);
  Bluefruit.Advertising.restartOnDisconnect(false);
  Bluefruit.Advertising.setStopCallback(on_adv_stop);
  uint8_t r = 0;
  sd_rand_application_vector_get(&r, 1);  // 재부팅마다 seq 시작값을 바꿔 병사 중복 제거와 겹칠 확률을 낮춤
  s_seq = r;
  // 병사 비콘 수동 스캔(scan request 없음)
  Bluefruit.Scanner.setRxCallback(on_scan);
  Bluefruit.Scanner.restartOnDisconnect(false);
  Bluefruit.Scanner.useActiveScan(false);
  Bluefruit.Scanner.filterMSD(COMPANY_ID);
  Bluefruit.Scanner.setInterval(SCAN_INTERVAL, SCAN_WINDOW);
  Bluefruit.Scanner.start(0);
  if (s_beacon_on) start_beacon();
}

void loop() {
  uint32_t now = millis();
  for (uint8_t i = 0; i < 4; i++) {  // 버튼: 20ms 디바운스, 눌리는 순간 1회
    bool pressed = digitalRead(BTN_PINS[i]) == LOW;
    if (pressed != s_btn_state[i] && (uint32_t)(now - s_btn_t[i]) >= 20) {
      s_btn_state[i] = pressed;
      s_btn_t[i] = now;
      if (pressed) send_button(i);
    }
  }
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\r' || c == '\n') {
      if (s_line_len) {
        s_line[s_line_len] = '\0';
        handle_line(s_line);
        s_line_len = 0;
      }
    } else if (s_line_len < sizeof s_line - 1) {
      s_line[s_line_len++] = c;
    }
  }
  if (s_adv_done) {
    s_adv_done = false;
    // 끝남 알림(지연 콜백)이 오기 전에 새 명령 방송이 이미 시작됐으면 그것을 끊지 않는다
    if (!Bluefruit.Advertising.isRunning()) {
      s_cmd_adv = false;
      digitalWrite(PIN_LED1, LED_OFF);
      char msg[24];
      snprintf(msg, sizeof msg, "DONE seq=%02X", s_last_seq);
      say(msg);
      if (s_beacon_on) start_beacon();  // 명령 방송이 끝나면 위치 비콘 재개
    }
  }
  while (s_bcn_tail != s_bcn_head) {  // 병사 비콘 RSSI → USB(호스트 없으면 버림)
    uint8_t t = s_bcn_tail;
    __DMB();
    char msg[32];
    snprintf(msg, sizeof msg, "BCN %u %d %u", s_bcn[t].src, s_bcn[t].rssi, s_bcn[t].heading);
    s_bcn_tail = (uint8_t)((t + 1) & 15);
    say(msg);
  }
  digitalWrite(PIN_LED2, Serial.dtr() ? LED_ON : LED_OFF);
}
