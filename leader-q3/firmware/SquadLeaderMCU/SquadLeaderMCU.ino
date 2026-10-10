/*
 * Squad Edge — 분대장1 (1-1) MCU 스케치 (Arduino UNO Q)
 *
 * Wi-Fi SoftAP / COP TCP 브리지는 Linux(MPU) 쪽 `host/bridge_server.py` 가 담당한다.
 * 이 스케치는 Bridge RPC 로 텔레메트리·하향 알림을 제공한다.
 *
 * App Lab / Arduino IDE 에서 UNO Q 보드로 업로드한 뒤,
 * 보드 Linux 에서 host/bridge_server.py 를 실행한다.
 *
 * Bridge 미탑재 보드(시리얼 시험): USB CDC 로 NDJSON 한 줄을 주기 송신한다.
 *   {"type":"unit.position","data":{...},"bytes":18}
 */

#include <Arduino.h>
#include <math.h>
#include "config.h"

#if __has_include(<Arduino_RouterBridge.h>)
#include <Arduino_RouterBridge.h>
#define HAS_BRIDGE 1
#else
#define HAS_BRIDGE 0
#endif

static uint32_t g_boot_ms = 0;
static uint32_t g_seq = 0;
static float g_lat = DEMO_LAT;
static float g_lon = DEMO_LON;
static float g_heading = 45.0f;
static uint8_t g_battery = 92;
static volatile uint32_t g_last_order_ms = 0;
static char g_last_order[160] = "";  // code|text (SoftAP 하향 명령 문구)

// 분대원 상대좌표 프리셋 (쐐기, m) — host 가 덮어쓸 수 있음
static const float REL_DX[3] = {-9.0f, 9.0f, -18.0f};
static const float REL_DY[3] = {-8.0f, -8.0f, -16.0f};
static const char *REL_IDS[3] = {"1-2", "1-3", "1-4"};

static void update_demo_pose() {
  float t = (millis() - g_boot_ms) / 1000.0f;
  float dist = t * 1.2f;
  const float deg2rad = 0.01745329252f;
  const float rad2deg = 57.29577951f;
  float rad = g_heading * deg2rad;
  const float R = 6371000.0f;
  g_lat = DEMO_LAT + (dist * cosf(rad) / R) * rad2deg;
  g_lon = DEMO_LON + (dist * sinf(rad) / (R * cosf(DEMO_LAT * deg2rad))) * rad2deg;
  g_heading = fmodf(45.0f + 10.0f * sinf(t / 20.0f) + 360.0f, 360.0f);
  if (g_battery > 40 && ((uint32_t)t % 60) == 0) {
    // 느린 방전 시뮬
  }
}

// Bridge / Serial 공용 JSON (단일 객체, 개행 없음)
static size_t build_telemetry(char *buf, size_t n) {
  update_demo_pose();
  g_seq++;
  int wrote = snprintf(
      buf, n,
      "{\"node\":\"%s\",\"squad\":\"%s\",\"seq\":%lu,"
      "\"lat\":%.6f,\"lon\":%.6f,\"heading\":%.1f,\"battery\":%u,\"err\":3.0,"
      "\"members\":["
      "{\"id\":\"%s\",\"dx\":%.1f,\"dy\":%.1f,\"err\":4.5},"
      "{\"id\":\"%s\",\"dx\":%.1f,\"dy\":%.1f,\"err\":4.5},"
      "{\"id\":\"%s\",\"dx\":%.1f,\"dy\":%.1f,\"err\":5.0}"
      "]}",
      NODE_ID, SQUAD_ID, (unsigned long)g_seq, g_lat, g_lon, g_heading, (unsigned)g_battery,
      REL_IDS[0], REL_DX[0], REL_DY[0], REL_IDS[1], REL_DX[1], REL_DY[1], REL_IDS[2], REL_DX[2],
      REL_DY[2]);
  if (wrote < 0) return 0;
  return (size_t)wrote < n ? (size_t)wrote : n - 1;
}

#if HAS_BRIDGE
static String rpc_ping() { return String("pong"); }

static String rpc_telemetry_json() {
  char buf[512];
  build_telemetry(buf, sizeof buf);
  return String(buf);
}

// host → MCU: SoftAP 하향 명령 알림 (LED 점멸 + Serial에 code|text)
static String rpc_order_notify(String notice) {
  notice.toCharArray(g_last_order, sizeof g_last_order);
  g_last_order[sizeof g_last_order - 1] = '\0';
  g_last_order_ms = millis();
  Serial.print(F("[order] "));
  Serial.println(g_last_order);
  return String("ok");
}
#endif

void setup() {
  g_boot_ms = millis();
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, LOW);
  Serial.begin(115200);
  delay(200);
  Serial.println(F("[SquadLeaderMCU] 분대장1 MCU ready"));

#if HAS_BRIDGE
  Bridge.begin();
  Bridge.provide(RPC_PING, rpc_ping);
  Bridge.provide(RPC_TELEMETRY, rpc_telemetry_json);
  Bridge.provide(RPC_ORDER, rpc_order_notify);
  Serial.println(F("[SquadLeaderMCU] Bridge RPC: ping / telemetry_json / order_notify"));
#else
  Serial.println(F("[SquadLeaderMCU] Bridge 없음 — USB NDJSON demo 모드"));
#endif
}

void loop() {
  // 하향 알림 후 2초간 LED 깜빡임
  if (g_last_order_ms && (millis() - g_last_order_ms) < 2000) {
    digitalWrite(LED_BUILTIN, ((millis() / 100) % 2) ? HIGH : LOW);
  } else {
    digitalWrite(LED_BUILTIN, LOW);
  }

#if !HAS_BRIDGE
  // 시리얼 전용 시험: 1초마다 unit.position + relpos NDJSON
  static uint32_t last = 0;
  if (millis() - last >= 1000) {
    last = millis();
    char tel[512];
    build_telemetry(tel, sizeof tel);
    // host/bridge_server 가 파싱하기 쉬운 telemetry 래퍼
    Serial.print(F("TEL "));
    Serial.println(tel);
  }
#endif

  delay(10);
}
