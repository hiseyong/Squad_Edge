// Bluefruit 무선 구현.
//
// NUS RX 경계 보존: BLEUart는 받은 write를 바이트 FIFO에 이어 붙여 프레임 경계가 사라진다.
// 프로토콜 §3.1(write 하나 = 프레임 하나, len 불일치 시 폐기)을 지키려고 BLEUart를 상속해
// RX 특성의 write 콜백만 교체한다. UUID·TX Notify·CCCD는 BLEUart 그대로(프로토콜 §3.1 UUID와 동일).
#include "radio.h"

#include <bluefruit.h>
#include <string.h>

#include "../../config.h"
#include "../core/frame.h"

#define RX_SLOTS 16  // 2의 거듭제곱. 슬롯당 244B → 약 4KB

class FrameUart : public BLEUart {
 public:
  FrameUart() : BLEUart(1) {}  // 기본 바이트 FIFO는 쓰지 않으므로 최소 크기
  err_t begin() {
    err_t err = BLEUart::begin();
    // useAdaCallback=false: BLE 태스크에서 바로 호출(지연 콜백은 write마다 malloc을 한다).
    _rxd.setWriteCallback(FrameUart::on_rx_write, false);
    return err;
  }

 private:
  static void on_rx_write(uint16_t conn_hdl, BLECharacteristic *chr, uint8_t *data, uint16_t len);
};

static FrameUart s_uart;

// ---- RX 링 버퍼 (생산자: BLE 태스크, 소비자: loop 태스크) ----
static uint8_t s_rx_buf[RX_SLOTS][FRAME_MAX_LEN];
static uint16_t s_rx_len[RX_SLOTS];
static volatile uint8_t s_rx_head = 0;  // BLE 태스크만 씀
static volatile uint8_t s_rx_tail = 0;  // loop 태스크만 씀
static volatile uint32_t s_rx_dropped = 0;

// 이벤트 카운터: BLE 태스크만 증가, loop는 마지막으로 본 값과 비교(잠금 없음).
static volatile uint8_t s_ev_count[3] = {0, 0, 0};  // [0] 연결, [1] 끊김, [2] Notify 켜짐
static uint8_t s_ev_seen[3] = {0, 0, 0};
static volatile bool s_connected = false;
static volatile uint16_t s_conn_hdl = BLE_CONN_HANDLE_INVALID;
static volatile uint8_t s_disc_reason = 0;
static volatile uint32_t s_adv_frames = 0;
static volatile bool s_disconnecting = false;  // 침묵 전환으로 끊기를 요청함(끊김 이벤트 전까지 송신 금지)
static volatile uint8_t s_mode = 2;  // 스캔 콜백(BLE 태스크)도 읽음

// RX 링 버퍼에 프레임 하나(생산자: BLE 태스크 — 연결 write 콜백 또는 스캔 콜백, 둘이 동시에 돌지 않는다)
static void rx_push(const uint8_t *data, uint16_t len) {
  uint8_t head = s_rx_head;
  uint8_t next = (uint8_t)((head + 1) & (RX_SLOTS - 1));
  if (len > FRAME_MAX_LEN || next == s_rx_tail) {
    s_rx_dropped++;
    return;
  }
  memcpy(s_rx_buf[head], data, len);
  s_rx_len[head] = len;
  __DMB();  // 데이터를 먼저 쓰고 head를 갱신
  s_rx_head = next;
}

void FrameUart::on_rx_write(uint16_t conn_hdl, BLECharacteristic *chr, uint8_t *data, uint16_t len) {
  (void)conn_hdl;
  (void)chr;
  rx_push(data, len);
}

// ---- 광고·스캔 상태(loop 태스크가 radio_loop에서 관리) ----
// S140 v6는 광고 세트가 1개뿐(BLE_GAP_ADV_SET_COUNT_MAX = 1): 연결 가능 광고와 비콘을 동시에 못 한다.
// 분대장과 연결되면 SoftDevice가 연결 가능 광고를 멈추므로 그 세트로 비연결형 비콘을 광고한다(EMCON 2만).
// Bluefruit의 끊김 후 자동 재광고는 끄고(현재 type/데이터로 재시작하므로 비콘 상태면 꼬임) 여기서 직접 관리한다.
#define ADV_NONE   0
#define ADV_CONN   1
#define ADV_BEACON 2
#define ADV_REPORT 3  // 단계 9 대안 경로: 보고 직접 방송(3초). 비콘·연결 가능 광고보다 우선
#define SCAN_OFF     0
#define SCAN_SILENT  1  // 침묵 모드: 분대장 광고(CMD_BUTTON/EMCON_SET)
#define SCAN_RANGING 2  // 모드 1/2: 다른 병사 BEACON RSSI

static uint8_t s_self_id = 0;
static uint8_t s_adv_kind = ADV_NONE;
static uint8_t s_scan_kind = SCAN_OFF;
static volatile bool s_adv_reset = false;  // 연결됨 → SoftDevice가 연결 가능 광고를 멈춤
static uint32_t s_retry_t = 0;
static bool s_beacon_en = false, s_ranging_en = false, s_scan_pause = false;
static uint8_t s_beacon[2 + FRAME_HDR_LEN + 2];
static uint8_t s_beacon_len = 0;
static bool s_beacon_dirty = false;
// 보고 직접 방송(PEER_REPORT 형식, src = 나). 광고 세트가 하나라 방송 중에는 비콘/연결 가능 광고를 잠시 멈춘다.
static uint8_t s_bc[2 + 24];
static uint8_t s_bc_len = 0;
static uint32_t s_bc_until = 0;
static bool s_bc_dirty = false;
// 다른 병사의 직접 방송 수신: 같은 (src, seq) 반복(100ms 간격 3초)은 스캔 콜백에서 바로 버린다
static uint8_t s_peer_seq[6];
static uint32_t s_peer_t[6];
static volatile uint32_t s_peer_adv_frames = 0;

// ---- 비콘 수신 링 버퍼 (생산자: BLE 태스크 스캔 콜백, 소비자: loop) ----
#define BCN_SLOTS 16
typedef struct { uint8_t src; int8_t rssi; uint16_t heading; } bcn_t;
static bcn_t s_bcn[BCN_SLOTS];
static volatile uint8_t s_bcn_head = 0, s_bcn_tail = 0;

// 스캔 보고(지연 콜백, BLE 태스크). 데이터 버퍼는 resume() 전까지만 유효 → 먼저 복사.
static void on_scan(ble_gap_evt_adv_report_t *report) {
  uint8_t msd[31];
  uint8_t n = Bluefruit.Scanner.parseReportByType(report, BLE_GAP_AD_TYPE_MANUFACTURER_SPECIFIC_DATA, msd, sizeof msd);
  // msd = Company ID(2, LE) + 프레임[ver type seq src dst len payload]
  if (n >= 2 + FRAME_HDR_LEN && msd[0] == (SILENT_COMPANY_ID & 0xFF) && msd[1] == (SILENT_COMPANY_ID >> 8) &&
      msd[2] == FRAME_VER) {
    uint8_t type = msd[3], src = msd[5];
    if (type == MSG_BEACON && n == 2 + FRAME_HDR_LEN + 2 && msd[7] == 2 && src <= 5 && src != s_self_id) {
      // 다른 병사·분대장(src 0) 비콘(v1.1 예정 0x20): RSSI만 모은다
      uint8_t head = s_bcn_head, next = (uint8_t)((head + 1) & (BCN_SLOTS - 1));
      if (next != s_bcn_tail) {
        s_bcn[head].src = src;
        s_bcn[head].rssi = report->rssi;
        s_bcn[head].heading = (uint16_t)(msd[8] | (msd[9] << 8));
        __DMB();
        s_bcn_head = next;
      }
    } else if (type == MSG_PEER_REPORT && src >= 1 && src <= 5 && src != s_self_id && n == 2 + FRAME_HDR_LEN + msd[7]) {
      // 다른 병사의 보고 직접 방송(v1.1 예정): 모든 모드에서 수신만(전파 방출 없음). 반복분은 여기서 버림
      uint32_t now = millis();
      if (s_peer_t[src] == 0 || s_peer_seq[src] != msd[4] || (int32_t)(now - s_peer_t[src]) >= PEER_ADV_REPEAT_MS) {
        s_peer_seq[src] = msd[4];
        s_peer_t[src] = now ? now : 1;
        s_peer_adv_frames++;
        rx_push(msd + 2, (uint16_t)(n - 2));
      }
    } else if (s_mode == 0 && src == FRAME_ID_LEADER && (type == MSG_CMD_BUTTON || type == MSG_EMCON_SET)) {
      // 침묵 모드 분대장 방송(프로토콜 §3.2): 연결 RX와 같은 경로
      s_adv_frames++;
      rx_push(msd + 2, (uint16_t)(n - 2));
    }
  }
  Bluefruit.Scanner.resume();  // SoftDevice v6: 보고 하나마다 스캔이 멈춘다
}

static void on_connect(uint16_t conn_hdl) {
  s_disconnecting = false;
  s_conn_hdl = conn_hdl;
  s_connected = true;
  s_adv_reset = true;
  s_ev_count[0]++;
}

static void on_disconnect(uint16_t conn_hdl, uint8_t reason) {
  (void)conn_hdl;
  s_connected = false;
  s_conn_hdl = BLE_CONN_HANDLE_INVALID;
  s_disc_reason = reason;
  s_ev_count[1]++;
}

static void on_notify(uint16_t conn_hdl, bool enabled) {
  (void)conn_hdl;
  if (enabled) s_ev_count[2]++;
}

static bool adv_connectable() {
  if (Bluefruit.Advertising.isRunning()) Bluefruit.Advertising.stop();
  Bluefruit.Advertising.clearData();
  Bluefruit.Advertising.setType(BLE_GAP_ADV_TYPE_CONNECTABLE_SCANNABLE_UNDIRECTED);
  // Flags + NUS UUID(128비트) + 이름. 31바이트 = 3 + 18 + (2 + 6)
  Bluefruit.Advertising.addFlags(BLE_GAP_ADV_FLAGS_LE_ONLY_GENERAL_DISC_MODE);
  Bluefruit.Advertising.addService(s_uart);
  Bluefruit.Advertising.addName();
  Bluefruit.Advertising.setInterval(32, 244);  // 단위 0.625ms: 빠른 20ms, 느린 152.5ms
  Bluefruit.Advertising.setFastTimeout(30);
  return Bluefruit.Advertising.start(0);
}

static bool adv_beacon() {
  if (Bluefruit.Advertising.isRunning()) Bluefruit.Advertising.stop();
  Bluefruit.Advertising.clearData();
  Bluefruit.Advertising.setType(BLE_GAP_ADV_TYPE_NONCONNECTABLE_NONSCANNABLE_UNDIRECTED);
  Bluefruit.Advertising.addFlags(BLE_GAP_ADV_FLAGS_LE_ONLY_GENERAL_DISC_MODE);
  if (!Bluefruit.Advertising.addManufacturerData(s_beacon, s_beacon_len)) return false;
  uint16_t iv = (uint16_t)(BEACON_INTERVAL_MS * 8 / 5);  // ms → 0.625ms 단위
  Bluefruit.Advertising.setInterval(iv, iv);
  Bluefruit.Advertising.setFastTimeout(0);  // 0 = 계속(빠른/느린 구분 없음)
  return Bluefruit.Advertising.start(0);
}

static bool adv_report() {
  if (Bluefruit.Advertising.isRunning()) Bluefruit.Advertising.stop();
  Bluefruit.Advertising.clearData();
  Bluefruit.Advertising.setType(BLE_GAP_ADV_TYPE_NONCONNECTABLE_NONSCANNABLE_UNDIRECTED);
  Bluefruit.Advertising.addFlags(BLE_GAP_ADV_FLAGS_LE_ONLY_GENERAL_DISC_MODE);
  if (!Bluefruit.Advertising.addManufacturerData(s_bc, s_bc_len)) return false;
  uint16_t iv = (uint16_t)(PEER_ADV_INTERVAL_MS * 8 / 5);
  Bluefruit.Advertising.setInterval(iv, iv);
  Bluefruit.Advertising.setFastTimeout(0);
  return Bluefruit.Advertising.start(0);  // 멈춤은 apply_state가 s_bc_until에
}

static bool apply_scan(uint8_t want) {
  if (want == s_scan_kind) return true;
  if (Bluefruit.Scanner.isRunning()) Bluefruit.Scanner.stop();
  s_scan_kind = SCAN_OFF;
  if (want == SCAN_OFF) return true;
  if (want == SCAN_SILENT) Bluefruit.Scanner.setInterval(SILENT_SCAN_INTERVAL, SILENT_SCAN_WINDOW);
  else Bluefruit.Scanner.setInterval(RANGING_SCAN_INTERVAL, RANGING_SCAN_WINDOW);  // 연결 이벤트에 시간을 남김
  if (!Bluefruit.Scanner.start(0)) return false;
  s_scan_kind = want;
  return true;
}

// 원하는 광고·스캔 상태로 맞춘다. 실패하면 1초 뒤 다시 시도.
static bool apply_state(uint32_t now) {
  if (s_adv_reset) {
    s_adv_reset = false;
    s_adv_kind = ADV_NONE;  // 연결되면서 SoftDevice가 연결 가능 광고를 멈췄다
  }
  if (s_bc_len && (int32_t)(now - s_bc_until) >= 0) s_bc_len = 0;  // 직접 방송 끝
  uint8_t want_adv = ADV_NONE;
  if (s_mode != 0) {
    if (s_bc_len && !s_disconnecting) want_adv = ADV_REPORT;  // 연결 여부와 무관하게 3초 우선
    else if (!s_connected && !s_disconnecting) want_adv = ADV_CONN;
    else if (s_connected && !s_disconnecting && s_mode == 2 && s_beacon_en && s_beacon_len) want_adv = ADV_BEACON;
  }
  uint8_t want_scan = SCAN_OFF;
  if (s_mode == 0) want_scan = SCAN_SILENT;
  else if (s_ranging_en && !s_scan_pause) want_scan = SCAN_RANGING;

  bool ok = true;
  if (want_adv != s_adv_kind || (want_adv == ADV_BEACON && s_beacon_dirty) || (want_adv == ADV_REPORT && s_bc_dirty)) {
    if ((int32_t)(now - s_retry_t) < 0) return false;
    bool r = true;
    if (want_adv == ADV_NONE) {
      if (Bluefruit.Advertising.isRunning()) Bluefruit.Advertising.stop();
    } else if (want_adv == ADV_CONN) {
      r = adv_connectable();
    } else if (want_adv == ADV_REPORT) {
      r = adv_report();
      if (r) s_bc_dirty = false;
    } else {
      r = adv_beacon();
      if (r) s_beacon_dirty = false;
    }
    if (r) s_adv_kind = want_adv;
    else {
      ok = false;
      s_retry_t = now + 1000;
    }
  }
  if (!apply_scan(want_scan)) ok = false;
  return ok;
}

bool radio_begin(uint8_t soldier_id, uint8_t mode, int8_t tx_power) {
  // 자동 연결 LED 끄기: LED_STATE_ON 기준이라 이 보드(active-low)에서는 반대로 동작하고, LED2 용도와도 겹친다.
  Bluefruit.autoConnLed(false);
  // BANDWIDTH_MAX와 같되(ATT MTU 247, event_len 100) Notify 큐만 3 → BLE_HVN_QUEUE_SIZE.
  // 연달아 notify할 때 큐가 차서 송신이 실패하던 문제 대응(단계 2 시험).
  Bluefruit.configPrphConn(247, 100, BLE_HVN_QUEUE_SIZE, BLE_GATTC_WRITE_CMD_TX_QUEUE_SIZE_DEFAULT);
  if (!Bluefruit.begin(1, 0)) return false;      // Peripheral 1, Central 0
  s_self_id = soldier_id;

  char name[12];
  snprintf(name, sizeof name, "SQ1-S%u", (unsigned)soldier_id);
  Bluefruit.setName(name);
  Bluefruit.Periph.setConnectCallback(on_connect);
  Bluefruit.Periph.setDisconnectCallback(on_disconnect);

  s_uart.setNotifyCallback(on_notify);
  if (s_uart.begin() != ERROR_NONE) return false;

  Bluefruit.Advertising.restartOnDisconnect(false);  // 광고는 apply_state가 관리

  // 수동 스캔(침묵 모드 분대장 방송 + 모드 1/2 병사 비콘). scan request를 보내지 않음.
  Bluefruit.Scanner.setRxCallback(on_scan);
  Bluefruit.Scanner.restartOnDisconnect(false);
  Bluefruit.Scanner.useActiveScan(false);
  Bluefruit.Scanner.filterMSD(SILENT_COMPANY_ID);
  s_mode = 255;
  return radio_set_mode(mode, tx_power);
}

bool radio_set_tx_power(int8_t dbm) {
  if (!Bluefruit.setTxPower(dbm)) return false;  // 다음 광고부터
  if (s_connected) {
    BLEConnection *conn = Bluefruit.Connection(s_conn_hdl);
    if (conn && !conn->setTxPower(dbm)) return false;  // 현재 연결에도 바로
  }
  return true;
}

bool radio_set_mode(uint8_t mode, int8_t tx_power) {
  bool ok = true;
  s_mode = mode;
  if (mode == 0) {
    if (s_connected) {
      s_disconnecting = true;  // 끊김 이벤트가 오기 전 틈에 notify를 시도해 실패로 세던 문제 방지
      Bluefruit.disconnect(s_conn_hdl);
    }
  } else {
    ok = radio_set_tx_power(tx_power);
    if (s_adv_kind != ADV_NONE) s_adv_kind = 0xFF;  // 출력이 바뀌었으니 광고를 다시 시작(광고 출력은 시작 시 적용)
  }
  s_retry_t = millis();
  return apply_state(millis()) && ok;
}

void radio_loop(uint32_t now) { apply_state(now); }

void radio_set_beacon(const uint8_t *frame, uint8_t len) {
  if (len > FRAME_HDR_LEN + 2) return;
  s_beacon[0] = (uint8_t)(SILENT_COMPANY_ID & 0xFF);
  s_beacon[1] = (uint8_t)(SILENT_COMPANY_ID >> 8);
  memcpy(s_beacon + 2, frame, len);
  s_beacon_len = (uint8_t)(2 + len);
  s_beacon_dirty = true;
}

bool radio_broadcast(const uint8_t *frame, uint8_t len, uint16_t duration_ms) {
  if (len < FRAME_HDR_LEN || len > sizeof s_bc - 2 || s_mode == 0) return false;
  s_bc[0] = (uint8_t)(SILENT_COMPANY_ID & 0xFF);
  s_bc[1] = (uint8_t)(SILENT_COMPANY_ID >> 8);
  memcpy(s_bc + 2, frame, len);
  s_bc_len = (uint8_t)(2 + len);
  s_bc_until = millis() + duration_ms;
  s_bc_dirty = true;
  s_retry_t = millis();
  return true;
}

bool radio_broadcasting() { return s_adv_kind == ADV_REPORT; }

uint32_t radio_peer_adv_frames() { return s_peer_adv_frames; }

void radio_set_ranging(bool beacon, bool scan) {
  s_beacon_en = beacon;
  s_ranging_en = scan;
}

void radio_scan_pause(bool pause) { s_scan_pause = pause; }

bool radio_beaconing() { return s_adv_kind == ADV_BEACON; }

bool radio_pop_beacon(uint8_t *src, int8_t *rssi, uint16_t *heading) {
  uint8_t tail = s_bcn_tail;
  if (tail == s_bcn_head) return false;
  __DMB();
  *src = s_bcn[tail].src;
  *rssi = s_bcn[tail].rssi;
  *heading = s_bcn[tail].heading;
  s_bcn_tail = (uint8_t)((tail + 1) & (BCN_SLOTS - 1));
  return true;
}

bool radio_scanning() { return Bluefruit.Scanner.isRunning(); }

uint32_t radio_adv_frames() { return s_adv_frames; }

bool radio_connected() { return s_connected; }

bool radio_can_send() { return s_connected && !s_disconnecting && radio_mtu() > 3 && s_uart.notifyEnabled(s_conn_hdl); }

uint16_t radio_mtu() {
  if (!s_connected) return 0;
  BLEConnection *conn = Bluefruit.Connection(s_conn_hdl);
  return conn ? conn->getMtu() : 0;
}

uint8_t radio_take_events() {
  static const uint8_t kBits[3] = {RADIO_EV_CONNECTED, RADIO_EV_DISCONNECTED, RADIO_EV_NOTIFY_ON};
  uint8_t ev = 0;
  for (int i = 0; i < 3; i++) {
    uint8_t c = s_ev_count[i];
    if (c != s_ev_seen[i]) {
      s_ev_seen[i] = c;
      ev |= kBits[i];
    }
  }
  return ev;
}

uint8_t radio_last_disconnect_reason() { return s_disc_reason; }

bool radio_send(const uint8_t *frame, uint16_t len) {
  if (!radio_can_send()) return false;
  uint16_t mtu = radio_mtu();
  if (mtu < 3 || len > mtu - 3) return false;  // 쪼개 보내면 프로토콜 위반
  return s_uart.write(s_conn_hdl, frame, len) == len;
}

bool radio_pop_rx(uint8_t *buf, uint16_t *len) {
  uint8_t tail = s_rx_tail;
  if (tail == s_rx_head) return false;
  __DMB();
  *len = s_rx_len[tail];
  memcpy(buf, s_rx_buf[tail], *len);
  s_rx_tail = (uint8_t)((tail + 1) & (RX_SLOTS - 1));
  return true;
}

uint32_t radio_rx_dropped() { return s_rx_dropped; }
