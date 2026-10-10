// 최상위 상태기계 구현.
#include "app.h"

#include <Arduino.h>
#include <stdarg.h>
#include <stdio.h>

#include "../../config.h"
#include "../hal/audio_sink.h"
#include "../hal/buttons.h"
#include "../hal/heading.h"
#include "../hal/joystick.h"
#include "../hal/leds.h"
#include "../hal/radio.h"
#include "../core/ranging.h"
#include "commands.h"
#include "reporter.h"
#include "stats.h"
#include "voice_rx.h"

static uint8_t s_seq = 0;
static uint8_t s_mode = EMCON_BOOT_MODE;
static const int8_t kTxList[] = EMCON1_TX_POWER_LIST;
static int8_t s_tx_mode1 = EMCON1_TX_POWER_DBM;  // 최소 모드 송신 출력(버튼3+버튼4로 거리 시험 중 바꿀 수 있음)

// LOG 상태
static bool s_boot_logged = false;   // 부팅 로그는 첫 Notify 켜짐 때 한 번
static bool s_notify_ready = false;  // NOTIFY_ON 이벤트를 처리한 뒤에만 MTU 로그(단계 2 시험의 순서 문제 대응)
static uint16_t s_logged_mtu = 0;
static bool s_had_disconnect = false;
static uint8_t s_conn_count = 0;

// 송신 실패(연결·Notify가 있는데 notify가 실패한 경우)
static uint32_t s_tx_fail_total = 0;
static uint32_t s_tx_fail_unreported = 0;

// 단계 R: 비콘·RSSI
static ranging_t s_ranging;
static uint16_t s_beacon_heading = 0xFFFE;  // 비콘에 실은 heading(처음엔 일부러 다른 값)
static uint32_t s_beacon_check_t = 0, s_ranging_t = 0;

// 입력: 버튼별로 제스처 첫 눌림 순간의 조이스틱 방향(CLAUDE.md §6.1)
static geo_joy_t s_snap[BTN_COUNT];
static uint32_t s_joy_diag_t = 0;

uint8_t app_mode() { return s_mode; }

uint8_t app_next_seq() { return s_seq++; }

bool app_send_raw(const uint8_t *frame, uint16_t len) {
  if (!radio_can_send()) return false;
  if (!radio_send(frame, len)) {
    s_tx_fail_total++;
    s_tx_fail_unreported++;
    return false;
  }
  if (len >= 2 && frame[1] != MSG_LOG) stats_on_tx(s_mode, len);  // 무선으로 실제 나간 프로토콜 프레임(재전송 포함, 디버그 LOG 제외)
  if (len >= 2 && frame[1] != MSG_LOG) leds_pulse(LED_IDX_TX, LED_TX_PULSE_MS);
  return true;
}

bool app_send(frame_msg_t *m) {
  uint8_t buf[FRAME_MAX_LEN];
  m->src = SOLDIER_ID;
  m->seq = app_next_seq();
  int n = frame_encode(m, buf, sizeof buf);
  if (n < 0) return false;
  return app_send_raw(buf, (uint16_t)n);
}

void app_log(const char *fmt, ...) {
#if DEBUG_LOG
  char text[LOG_MAX_TEXT + 1];
  int prefix = 0;
  uint32_t reported = s_tx_fail_unreported;
  if (reported) prefix = snprintf(text, sizeof text, "[tx_fail +%lu] ", (unsigned long)reported);
  va_list ap;
  va_start(ap, fmt);
  int n = vsnprintf(text + prefix, sizeof text - prefix, fmt, ap);
  va_end(ap);
  if (n < 0) return;
  n += prefix;
  if (n > LOG_MAX_TEXT) n = LOG_MAX_TEXT;
  audio_sink_debug_text(text, (uint8_t)n);  // USB 사본: 침묵 모드(연결 없음)에서도 맥에서 보인다
  if (!radio_can_send()) return;
  frame_msg_t m;
  m.type = MSG_LOG;
  m.dst = FRAME_DST_LEADER;
  m.u.log.text = text;
  m.u.log.len = (uint8_t)n;
  if (app_send(&m) && reported) s_tx_fail_unreported -= reported;  // 표시된 만큼만 지움
#else
  (void)fmt;
#endif
}

void app_feedback(const char *clips, const char *note) {
  audio_sink_play_clips(clips, AUDIO_PRIO_FEEDBACK, true);
  if (note) app_log("FEEDBACK: %s (%s)", clips, note);
  else app_log("FEEDBACK: %s", clips);
}

// ---------- EMCON 모드 ----------
static int8_t tx_power_for(uint8_t mode) { return mode == 1 ? s_tx_mode1 : EMCON2_TX_POWER_DBM; }

static void show_mode_led() {
  if (s_mode == 0) leds_set(LED_IDX_MODE, false);
  else if (s_mode == 1) leds_blink(LED_IDX_MODE, LED_MODE1_PERIOD_MS, LED_MODE1_ON_MS);
  else leds_set(LED_IDX_MODE, true);
}

static void show_conn_led() {
  if (s_mode == 0) leds_blink(LED_IDX_CONN, LED_SILENT_PERIOD_MS, LED_SILENT_ON_MS);  // 침묵 스캔 = 3초마다 짧게
  else leds_set(LED_IDX_CONN, radio_connected());
}

void app_set_mode(uint8_t mode, const char *reason) {
  static const char *const kClip[3] = {"mode_silent", "mode_min", "mode_normal"};
  if (mode > 2) return;
  if (mode == s_mode) {
    app_log("emcon %u (unchanged, %s)", mode, reason);
    return;
  }
  uint8_t old = s_mode;
  // 침묵으로 가기 전에 LOG를 먼저(연결이 끊기면 BLE로 못 보냄, USB 사본은 계속)
  if (mode) app_log("emcon %u -> %u (%s) tx=%ddBm", old, mode, reason, (int)tx_power_for(mode));
  else app_log("emcon %u -> 0 (%s) radio: disconnect, passive scan", old, reason);
  if (mode == 0) {
    voice_rx_abort();        // 침묵 모드에서는 음성 명령을 받지 않는다(프로토콜 §2)
    s_notify_ready = false;  // 곧 끊긴다
  }
  s_mode = mode;
  reporter_set_mode(mode);
  if (!radio_set_mode(mode, tx_power_for(mode))) {
    app_log("emcon %u: radio switch failed", mode);
    app_feedback("err", "radio switch failed");
  }
  show_mode_led();
  show_conn_led();
  app_feedback(kClip[mode]);  // audio sink(USB 이어폰) — 침묵 모드에서도 동작
  if (mode != 0) reporter_send_emcon_state(mode);  // 연결되면 큐에서 나감(모드 1/2 진입 알림, §5.1 0x0B)
}

static void cycle_tx_power() {
  uint8_t n = sizeof kTxList / sizeof kTxList[0], i = 0;
  while (i < n && kTxList[i] != s_tx_mode1) i++;
  s_tx_mode1 = kTxList[(i + 1) % n];
  bool applied = (s_mode == 1) && radio_set_tx_power(s_tx_mode1);
  app_log("emcon1 tx_power=%ddBm%s", (int)s_tx_mode1, applied ? " (applied now)" : " (used when mode 1)");
}

// ---------- 입력 → 동작 (프로토콜 §9.1) ----------
static void on_button(const button_event_t *e) {
  // 두 버튼 조합(hal/buttons가 두 버튼의 단독 제스처를 취소해 둠)
  if (e->kind == BEV_COMBO_START) {
    static const char *const kName[3] = {"btn1+btn4 (3s -> calib)", "btn1+btn2 (2s -> mode)", "btn3+btn4 (2s -> tx power)"};
    app_log("input: %s combo start", kName[e->count < 3 ? e->count : 0]);
    return;
  }
  if (e->kind == BEV_COMBO_CALIB) {
    heading_start_calibration();
    app_feedback("calib_start", HEADING_MODE == HEADING_MODE_SENSOR ? nullptr : "HEADING_MODE!=SENSOR: no-op");
    return;
  }
  if (e->kind == BEV_COMBO_MODE) {
    app_set_mode((uint8_t)((s_mode + 1) % 3), "btn1+btn2");
    return;
  }
  if (e->kind == BEV_COMBO_TXPWR) {
    cycle_tx_power();
    return;
  }
  if (e->kind == BEV_PRESS) {
    if (e->first) s_snap[e->btn] = joystick_direction();
    if (e->btn == BTN_1) {
      static const char *const kNum[] = {"n1", "n2", "n3", "n4", "many"};
      app_feedback(kNum[e->count >= 5 ? 4 : e->count - 1]);
    }
    return;
  }
  const geo_joy_t *dir = &s_snap[e->btn];
  switch (e->btn) {
    case BTN_1:
      if (e->kind == BEV_MULTI_DONE) {
        uint8_t count = e->count >= BTN1_MULTI_MAX_COUNT ? BTN1_MULTI_MAX_COUNT : e->count;
        reporter_report(MSG_CONTACT, dir, count);
      }
      break;
    case BTN_2:
      if (e->kind == BEV_SHORT) reporter_report(MSG_SUSPICIOUS, dir, 0);
      else if (e->kind == BEV_DOUBLE) reporter_report(MSG_CASUALTY_FOUND, dir, 0);
      else if (e->kind == BEV_LONG) reporter_report(MSG_HAZARD, dir, 0);
      break;
    case BTN_3: {
      if (e->kind != BEV_SHORT && e->kind != BEV_LONG) break;
      uint8_t ref_type, ref_id;
      if (!commands_last(&ref_type, &ref_id)) {
        app_feedback("err", "no last command");
        break;
      }
      reporter_send_ref(e->kind == BEV_SHORT ? MSG_ACK : MSG_CANNOT_COMPLY, ref_type, ref_id);
      commands_acknowledged();  // LED2 미확인 점멸 해제
      break;
    }
    case BTN_4:
      if (e->kind == BEV_SHORT) reporter_report(MSG_OK_READY, dir, 0);
      else if (e->kind == BEV_DOUBLE) reporter_report(MSG_WEAPON_AMMO, dir, 0);
      else if (e->kind == BEV_LONG) reporter_report(MSG_CASUALTY_SELF, dir, 0);
      break;
    case BTN_JOY:
      if (e->kind == BEV_SHORT) commands_replay();
      else if (e->kind == BEV_LONG) app_set_mode((uint8_t)((s_mode + 1) % 3), "joystick");  // 0→1→2→0
      break;
  }
  if (e->kind == BEV_IGNORED) app_log("input: btn%u ignored (between short and long)", (unsigned)(e->btn + 1));
}

static void joy_diag(uint32_t now) {
#if HAS_JOYSTICK && JOY_DIAG_LOG
  if ((uint32_t)(now - s_joy_diag_t) < JOY_DIAG_INTERVAL_MS) return;
  s_joy_diag_t = now;
  joy_raw_t r;
  joystick_raw(&r);
  geo_joy_t d = joystick_direction();
  app_log("JOY x=%d y=%d sw=%d c=%d,%d dx=%d dy=%d mx=+%d/-%d my=+%d/-%d clk=%u pct=%u", r.x, r.y, r.sw ? 1 : 0,
          r.cx, r.cy, r.x - r.cx, r.y - r.cy, r.mx_pos, r.mx_neg, r.my_pos, r.my_neg, d.clock, d.pct);
#else
  (void)now;
#endif
}

// ---------- 단계 R: 비콘 송신(EMCON 2) · 다른 병사 비콘 RSSI · RANGING 보고 ----------
static void ranging_loop(uint32_t now) {
#if RANGING_ENABLE
  // 비콘 프레임 [ver 01, type 20, seq, src, dst FF, len 2, heading LE]. heading이 바뀌면 다시 만든다.
  if ((int32_t)(now - s_beacon_check_t) >= HEADING_BEACON_CHECK_MS) {
    s_beacon_check_t = now;
    uint16_t h = heading_deg();
    if (h != s_beacon_heading) {
      s_beacon_heading = h;
      uint8_t f[FRAME_HDR_LEN + 2] = {FRAME_VER, MSG_BEACON, app_next_seq(), SOLDIER_ID, FRAME_DST_ALL, 2,
                                      (uint8_t)(h & 0xFF), (uint8_t)(h >> 8)};
      radio_set_beacon(f, sizeof f);
    }
  }
  radio_scan_pause(voice_rx_busy());  // 음성 수신 중에는 비콘 스캔을 멈춰 연결 처리량 확보
  uint8_t src;
  int8_t rssi;
  uint16_t hd;
  while (radio_pop_beacon(&src, &rssi, &hd)) ranging_add(&s_ranging, src, rssi, now);
  if ((int32_t)(now - s_ranging_t) >= RANGING_REPORT_MS) {
    s_ranging_t = now;
    if (s_mode == 0) return;  // 침묵 모드: 보고하지 않음(쌓이면 낡은 값)
    ranging_entry_t e[RANGING_MAX_PEERS];
    uint8_t n = ranging_collect(&s_ranging, SOLDIER_ID, now, e, RANGING_MAX_PEERS);
    if (n) reporter_send_ranging(e, n);
    char t[64];
    int k = snprintf(t, sizeof t, "ranging n=%u beacon=%u", n, radio_beaconing() ? 1 : 0);
    for (uint8_t i = 0; i < n && k > 0 && k < (int)sizeof t; i++)
      k += snprintf(t + k, sizeof t - k, e[i].peer_id ? " S%u:%d/%u" : " L%u:%d/%u", e[i].peer_id, e[i].rssi_avg,
                    e[i].samples);  // L0 = 분대장 비콘
    app_log("%s", t);
  }
#else
  (void)now;
#endif
}

// ---------- 무선 이벤트 / LOG ----------
static void handle_radio_events() {
  uint8_t ev = radio_take_events();
  if (ev & RADIO_EV_DISCONNECTED) s_had_disconnect = true;
  if (ev & RADIO_EV_CONNECTED) s_conn_count++;
  if (!radio_connected()) s_notify_ready = false;
  if (ev & RADIO_EV_NOTIFY_ON) {
    // 연결 직후에는 Notify가 꺼져 있어 로그를 못 보낸다 → 분대장이 구독한 시점에 몰아서 보냄
    if (!s_boot_logged) {
      s_boot_logged = true;
      app_log("boot id=%u joy=%u heading_mode=%u emcon=%u tx1=%d sink=%s up=%lums", (unsigned)SOLDIER_ID,
              (unsigned)HAS_JOYSTICK, (unsigned)HEADING_MODE, (unsigned)s_mode, (int)s_tx_mode1, audio_sink_name(),
              (unsigned long)millis());
    }
    if (s_had_disconnect) {
      app_log("conn #%u prev_disc_reason=0x%02X rx_dropped=%lu tx_fail=%lu ear_out=%lu ear_drop=%lu",
              (unsigned)s_conn_count, (unsigned)radio_last_disconnect_reason(), (unsigned long)radio_rx_dropped(),
              (unsigned long)s_tx_fail_total, (unsigned long)audio_sink_bytes_out(),
              (unsigned long)audio_sink_dropped());
    } else {
      app_log("conn #%u", (unsigned)s_conn_count);
    }
    s_notify_ready = true;
    s_logged_mtu = 0;  // 이어서 MTU 로그
    reporter_on_link_ready();
  }
  if (ev) show_conn_led();
}

static void handle_mtu_log() {
  if (!s_notify_ready || !radio_can_send()) return;
  uint16_t mtu = radio_mtu();
  if (mtu < 23) return;  // 연결 해제 중(0) 등 비정상 값은 무시
  if (mtu != s_logged_mtu) {
    s_logged_mtu = mtu;
    app_log("mtu=%u max_write=%u", (unsigned)mtu, (unsigned)(mtu - 3));
  }
}

void app_begin() {
  leds_begin();
  buttons_begin();
  joystick_begin();
  heading_begin();
  reporter_begin(s_mode);
  commands_begin();
  voice_rx_begin();
  audio_sink_begin(SOLDIER_ID);
  ranging_init(&s_ranging, RANGING_STALE_MS);
  show_mode_led();
  show_conn_led();
  radio_set_ranging(RANGING_ENABLE, RANGING_ENABLE || PEER_ADV_ENABLE);  // 스캔 = 비콘 RSSI + 다른 병사 보고 방송
  if (!radio_begin(SOLDIER_ID, s_mode, tx_power_for(s_mode))) {
    // 무선 초기화 실패(예: SoftDevice RAM 부족): 로그를 보낼 수 없으므로 LED4 빠른 점멸로 표시
    leds_blink(LED_IDX_MODE, 200, 100);
  }
}

void app_loop() {
  uint32_t now = millis();
  handle_radio_events();
  handle_mtu_log();

  uint8_t buf[FRAME_MAX_LEN];
  uint16_t len;
  while (radio_pop_rx(buf, &len)) commands_handle_frame(buf, len);

  joystick_update(now);
  buttons_update(now);
  button_event_t e;
  while (buttons_next(&e)) on_button(&e);
  joy_diag(now);

  reporter_loop(now);
  commands_loop(now);
  voice_rx_loop(now);
  audio_sink_loop(now);
  ranging_loop(now);
  radio_loop(now);
  leds_update(now);
}
