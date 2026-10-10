// 수신 프레임 처리 구현. LOG 문자열은 ASCII만(프로토콜 §5.3 LOG = ASCII).
#include "commands.h"

#include <Arduino.h>

#include "../../config.h"
#include "../core/crc16.h"
#include "../core/dedup.h"
#include "../core/frame.h"
#include "../core/unack.h"
#include "../hal/audio_sink.h"
#include "../hal/heading.h"
#include "../hal/leds.h"
#include "app.h"
#include "phrases.h"
#include "reporter.h"
#include "squad_map.h"
#include "stats.h"
#include "voice_rx.h"

static dedup_t s_dedup;
static dedup_t s_peer_dedup;   // 다른 병사 보고: (보고자, 원 보고 type, payload CRC) — 중계·직접 방송 공통
static squad_map_t s_map;      // POS_TABLE

static bool s_has_last = false;
static uint8_t s_last_type = 0;
static uint8_t s_last_id = 0;
static phrase_t s_last_phrase;   // 버튼 명령일 때
static uint8_t s_last_prio = AUDIO_PRIO_NORMAL;

static unack_t s_unack;

static int8_t s_requested_mode = -1;
// 중복 재생 억제: 마지막으로 재생한 (src, seq)와 시각
static uint8_t s_play_src = 0xFF, s_play_seq = 0;
static uint32_t s_play_t = 0;

int8_t commands_requested_mode() { return s_requested_mode; }

bool commands_my_pos(int16_t *x, int16_t *y) { return squad_map_pos(&s_map, SOLDIER_ID, x, y); }

static void play(const phrase_t *p, uint8_t prio, const char *note) {
  char text[64];
  phrases_join(p, text, sizeof text);
  audio_sink_play_clips(text, prio, false);
  app_log("PLAY: %s%s", text, note);
}

static void set_unacked() {
  unack_start(&s_unack, millis());  // 시작 시각·빠른 점멸 상태 초기화(core/unack, 부호 있는 경과 시간)
  leds_blink(LED_IDX_UNACK, 2 * UNACK_BLINK_MS, UNACK_BLINK_MS);
}

void commands_begin() {
  dedup_init(&s_dedup, DEDUP_WINDOW_MS);
  dedup_init(&s_peer_dedup, PEER_DEDUP_WINDOW_MS);
  squad_map_init(&s_map);
  unack_init(&s_unack, UNACK_ESCALATE_MS);
}

void commands_loop(uint32_t now) {
  if (unack_poll(&s_unack, now)) {
    leds_blink(LED_IDX_UNACK, 2 * UNACK_FAST_BLINK_MS, UNACK_FAST_BLINK_MS);
    app_log("unacked 30s: seq=%u LED2 fast blink", s_last_id);
  }
}

bool commands_last(uint8_t *ref_type, uint8_t *ref_id) {
  if (!s_has_last) return false;
  *ref_type = s_last_type;
  *ref_id = s_last_id;
  return true;
}

void commands_acknowledged() {
  if (!s_unack.active) return;
  unack_clear(&s_unack);
  leds_set(LED_IDX_UNACK, false);
}

void commands_note_voice(uint8_t voice_id) {
  s_has_last = true;
  s_last_type = REF_TYPE_VOICE;
  s_last_id = voice_id;
  set_unacked();
}

void commands_replay() {
  if (!s_has_last) {
    app_feedback("err", "no last command");
    return;
  }
  if (s_last_type == REF_TYPE_VOICE) {
    bool ok = voice_rx_replay(s_last_id);
    app_log("PLAY: voice id=%u (replay)%s", s_last_id, ok ? "" : " - not available");
    if (!ok) app_feedback("err", "voice replay not available");
    return;
  }
  play(&s_last_phrase, s_last_prio, " (replay)");
}

static void handle_cmd_button(const frame_msg_t *m) {
  const msg_cmd_button_t *c = &m->u.cmd_button;
  phrase_t p;
  // RALLY 방향 = POS_TABLE의 내 위치에서 분대장(원점) 방향(단계 9). 표가 없으면 0xFFFF → 방향 없이
  phrases_for_cmd(c, heading_deg(), squad_map_rally_az(&s_map, SOLDIER_ID), &p);

  // 중복 = 같은 (src, seq) + 같은 payload + DEDUP_WINDOW_MS 안 (core/dedup.h 설명)
  uint8_t pl[6] = {c->cmd_code, (uint8_t)c->azimuth, (uint8_t)(c->azimuth >> 8), c->dist_band, c->extra, c->priority};
  uint32_t now = millis();
  if (dedup_seen(&s_dedup, m->src, m->seq, crc16_ccitt_false(pl, sizeof pl), now)) {
    // 같은 명령의 반복. 침묵 모드 광고는 100ms마다 3초간 같은 프레임 → 5초 안의 반복은 조용히 버림.
    // 그보다 늦은 것(분대장 15초 재전송)은 다시 재생만, 새 명령으로 취급하지 않음(프로토콜 §8.1-6)
    if (m->src == s_play_src && m->seq == s_play_seq && (int32_t)(now - s_play_t) < DUP_REPLAY_HOLDOFF_MS) return;
    s_play_src = m->src;
    s_play_seq = m->seq;
    s_play_t = now;
    app_log("cmd dup seq=%u %s: replay only", m->seq, phrases_cmd_name(c->cmd_code));
    play(&p, c->priority ? AUDIO_PRIO_URGENT : AUDIO_PRIO_NORMAL, " (dup)");
    return;
  }
  s_play_src = m->src;
  s_play_seq = m->seq;
  s_play_t = now;
  if (p.flags & PHRASE_F_UNKNOWN_CMD) {
    app_log("cmd unknown code=%02X seq=%u: ignored", c->cmd_code, m->seq);
    return;
  }
  app_log("cmd %s seq=%u az=%u dist=%u extra=%u prio=%u%s", phrases_cmd_name(c->cmd_code), m->seq, c->azimuth,
          c->dist_band, c->extra, c->priority,
          (p.flags & PHRASE_F_NO_DIR) ? (c->cmd_code == CMD_RALLY ? " (no POS_TABLE: no dir)" : " (no dir)") : "");

  s_has_last = true;
  s_last_type = REF_TYPE_BUTTON;
  s_last_id = m->seq;
  s_last_phrase = p;
  s_last_prio = c->priority ? AUDIO_PRIO_URGENT : AUDIO_PRIO_NORMAL;
  set_unacked();
  play(&p, s_last_prio, c->priority ? " (urgent)" : "");

  if (c->cmd_code == CMD_SILENCE) {
    s_requested_mode = 0;
    app_set_mode(0, "SILENCE cmd");  // 재생("silence")·마지막 명령 기록 뒤 전환. ACK는 침묵 모드라 큐에 쌓임(§2)
  }
}

static void handle_pos_table(const msg_pos_table_t *t) {
  squad_map_set(&s_map, t);
  int16_t x, y;
  bool me = squad_map_pos(&s_map, SOLDIER_ID, &x, &y);
  uint16_t raz = squad_map_rally_az(&s_map, SOLDIER_ID);
  if (me) app_log("pos_table n=%u me=(%d,%d)dm rally_az=%u", t->n, x, y, raz);
  else app_log("pos_table n=%u: no entry for S%u", t->n, (unsigned)SOLDIER_ID);
}

// 다른 병사 보고(프로토콜 §9.3). via_adv: 병사 직접 방송(v1.1 예정), 아니면 분대장 중계.
static void handle_peer_report(const msg_peer_report_t *pr, bool via_adv) {
  const char *via = via_adv ? "adv" : "relay";
  uint16_t sig = crc16_ccitt_false(pr->orig_payload, pr->orig_len);
  if (dedup_seen(&s_peer_dedup, pr->reporter_id, pr->orig_type, sig, millis())) {
    app_log("peer S%u type=%02X via %s: dup (already played)", pr->reporter_id, pr->orig_type, via);
    return;
  }
  squad_peer_t o;
  int rc = squad_map_peer(&s_map, SOLDIER_ID, heading_deg(), pr, &o);
  if (rc != SQ_OK) {
    app_log("peer S%u type=%02X via %s: ignored err=%d", pr->reporter_id, pr->orig_type, via, rc);
    return;
  }
  phrase_t p;
  phrases_for_peer(o.type, o.count, o.clock, o.dist_band, &p);
  char text[64];
  phrases_join(&p, text, sizeof text);
  audio_sink_play_clips(text, AUDIO_PRIO_NORMAL, false);
  app_log("PLAY: %s (peer S%u via %s brg=%u r=%ldm%s%s%s)", text, pr->reporter_id, via, o.bearing,
          (long)(o.range_dm / 10.0f + 0.5f), (o.flags & SQ_F_NO_POS) ? " no POS_TABLE: reporter frame" : "",
          (o.flags & SQ_F_TOWARD_REPORTER) ? " no az: toward reporter" : "", (o.flags & SQ_F_NO_DIR) ? " no dir" : "");
}

void commands_handle_frame(const uint8_t *buf, uint16_t len) {
  frame_msg_t m;
  int rc = frame_receive(buf, len, SOLDIER_ID, &m);
  if (rc != FRAME_OK) {
    // 침묵 모드 광고는 같은 프레임이 3초간 반복 → 같은 (type, seq) 폐기 LOG는 5초에 한 번만
    static uint8_t last_type = 0xFF, last_seq = 0;
    static uint32_t last_t = 0;
    uint8_t t = len > 1 ? buf[1] : 0, sq = len > 2 ? buf[2] : 0;
    uint32_t now = millis();
    if (t != last_type || sq != last_seq || (int32_t)(now - last_t) >= DUP_REPLAY_HOLDOFF_MS) {
      app_log("rx drop err=%d type=%02X seq=%u len=%u", rc, t, sq, (unsigned)len);
      last_type = t;
      last_seq = sq;
      last_t = now;
    }
    return;
  }
  if (m.src != FRAME_ID_LEADER) {
    // 예외: 다른 병사의 보고 직접 방송(PEER_REPORT, src = reporter_id, 스캔으로 받음)
    if (m.type == MSG_PEER_REPORT && m.src == m.u.peer_report.reporter_id && m.src != SOLDIER_ID) {
      handle_peer_report(&m.u.peer_report, true);
      return;
    }
    app_log("rx drop src=%u (not leader) type=%02X", m.src, m.type);
    return;
  }
  // 청크마다 LOG를 보내면 무선이 넘친다. CMD_BUTTON은 handle_cmd_button이 따로 LOG(광고 반복 시 넘침 방지)
  if (m.type != MSG_VOICE_CHUNK && m.type != MSG_CMD_BUTTON) {
    app_log("rx type=%02X seq=%u src=%u dst=%02X plen=%u", m.type, m.seq, m.src, m.dst,
            (unsigned)(len - FRAME_HDR_LEN));
  }

  switch (m.type) {
    case MSG_CMD_BUTTON:
      handle_cmd_button(&m);
      break;
    case MSG_VOICE_BEGIN:
    case MSG_VOICE_CHUNK:
    case MSG_VOICE_END:
      voice_rx_handle(&m);
      break;
    case MSG_EMCON_SET:
      s_requested_mode = (int8_t)m.u.mode.mode;
      app_set_mode(m.u.mode.mode, "EMCON_SET");
      break;
    case MSG_REQ_STATS: {
      frame_msg_t reply;
      reply.type = MSG_STATS;
      reply.dst = FRAME_DST_LEADER;
      stats_fill(&reply.u.stats);
      if (!app_send(&reply)) app_log("stats send fail");
      break;
    }
    case MSG_RPT_ACK:
      reporter_on_rpt_ack(m.u.rpt_ack.ref_seq);
      break;
    case MSG_POS_TABLE:
      handle_pos_table(&m.u.pos_table);
      break;
    case MSG_PEER_REPORT:
      handle_peer_report(&m.u.peer_report, false);
      break;
    default:
      app_log("unhandled type=%02X", m.type);  // 이후 단계에서 처리
      break;
  }
}
