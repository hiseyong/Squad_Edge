// 보고 송신 구현.
#include "reporter.h"

#include <string.h>

#include "../../config.h"
#include "../core/frame.h"
#include "../core/report_queue.h"
#include "../hal/heading.h"
#include "../hal/radio.h"
#include "app.h"
#include "commands.h"
#include "squad_map.h"

typedef struct {
  bool used;
  uint8_t seq;
  uint8_t retries;   // 재전송 횟수(최대 RPT_MAX_RETRIES)
  uint32_t last_tx;
  uint8_t len;
  uint8_t data[REPORT_QUEUE_FRAME_MAX];
} pending_t;

static report_queue_t s_queue;
static pending_t s_pending[RPT_PENDING_MAX];
static uint8_t s_mode = 2;
static bool s_flush_all = false;     // 큐 전체를 비울 때까지 계속 보냄
static uint32_t s_batch_t = 0;       // EMCON 1 일괄 송신 기준 시각
static uint32_t s_retry_after = 0;   // 큐 송신 실패 후 재시도 시각
static uint32_t s_now = 0;

static const char *type_name(uint8_t t) {
  switch (t) {
    case MSG_CONTACT: return "CONTACT";
    case MSG_SUSPICIOUS: return "SUSPICIOUS";
    case MSG_HAZARD: return "HAZARD";
    case MSG_CASUALTY_FOUND: return "CASUALTY_FOUND";
    case MSG_OK_READY: return "OK_READY";
    case MSG_WEAPON_AMMO: return "WEAPON_AMMO";
    case MSG_CASUALTY_SELF: return "CASUALTY_SELF";
    case MSG_ACK: return "ACK";
    case MSG_CANNOT_COMPLY: return "CANNOT_COMPLY";
    case MSG_VOICE_RESULT: return "VOICE_RESULT";
    case MSG_EMCON_STATE: return "EMCON_STATE";
    case MSG_RANGING: return "RANGING";
    default: return "?";
  }
}

// 송신 후 로컬 피드백 조각(프로토콜 §9.2, 조각 ID는 CLAUDE.md §6.5)
static const char *sent_clips(uint8_t t) {
  switch (t) {
    case MSG_CONTACT: return "enemy sent";
    case MSG_SUSPICIOUS: return "suspicious sent";
    case MSG_HAZARD: return "hazard sent";
    case MSG_CASUALTY_FOUND: return "casualty sent";
    case MSG_CASUALTY_SELF: return "casualty sent";
    default: return "sent";
  }
}

static bool immediate_in_mode1(uint8_t t) {
  return frame_type_is_urgent(t) || t == MSG_ACK || t == MSG_CANNOT_COMPLY || t == MSG_VOICE_RESULT;
}

static void add_pending(const uint8_t *f, uint8_t len) {
  int slot = -1;
  for (int i = 0; i < RPT_PENDING_MAX; i++) {
    if (s_pending[i].used && s_pending[i].seq == f[2]) return;  // 이미 대기 중(재전송)
    if (!s_pending[i].used && slot < 0) slot = i;
  }
  if (slot < 0) {  // 가득 차면 가장 오래 기다린 것을 포기
    slot = 0;
    for (int i = 1; i < RPT_PENDING_MAX; i++)
      if ((int32_t)(s_pending[i].last_tx - s_pending[slot].last_tx) < 0) slot = i;
    app_log("rpt_ack wait full: drop seq=%u", s_pending[slot].seq);
  }
  pending_t *p = &s_pending[slot];
  p->used = true;
  p->seq = f[2];
  p->retries = 0;
  p->last_tx = s_now;
  p->len = len;
  memcpy(p->data, f, len);
}

// 프레임 하나를 실제로 송신. 성공하면 긴급은 RPT_ACK 대기에 등록.
static bool transmit(const uint8_t *f, uint8_t len) {
  if (!app_send_raw(f, len)) return false;
  if (frame_type_is_urgent(f[1]) && s_mode != 0) add_pending(f, len);
  return true;
}

static void enqueue(const uint8_t *f, uint8_t len) {
  rq_result_t r = report_queue_push(&s_queue, f, len);
  if (r == RQ_PUSHED_DROPPED_OLD) app_log("queue full: dropped oldest (normal first)");
  else if (r == RQ_REJECTED) app_log("queue full of urgent: rejected %s seq=%u", type_name(f[1]), f[2]);
  else if (r == RQ_INVALID) app_log("queue: invalid frame len=%u", len);
}

// 새 프레임을 모드 규칙에 따라 즉시 송신 또는 큐에 넣는다. 반환: 즉시 송신 여부.
static bool submit(const uint8_t *f, uint8_t len) {
  bool now = (s_mode == 2) || (s_mode == 1 && immediate_in_mode1(f[1]));
  // 큐에 먼저 들어간 것이 있으면 순서를 지키기 위해 뒤에 줄을 세운다(긴급은 예외: 바로 보낸다)
  if (now && report_queue_count(&s_queue) > 0 && !frame_type_is_urgent(f[1])) now = false;
  if (now && transmit(f, len)) return true;
  enqueue(f, len);
  if (s_mode == 2) s_flush_all = true;
  return false;
}

static void build_and_submit(frame_msg_t *m) {
  uint8_t buf[REPORT_QUEUE_FRAME_MAX];
  m->src = SOLDIER_ID;
  m->dst = FRAME_DST_LEADER;
  m->seq = app_next_seq();
  int n = frame_encode(m, buf, sizeof buf);
  if (n < 0) {
    app_log("encode fail type=%02X err=%d", m->type, n);
    return;
  }
  bool sent = submit(buf, (uint8_t)n);
  app_log("tx %s seq=%u %s", type_name(m->type), m->seq, sent ? "sent" : (s_mode == 0 ? "queued(emcon0)" : "queued"));
}

// 단계 9 대안 경로(v1.1 예정): 같은 보고를 PEER_REPORT 형식으로 광고 직접 방송(EMCON 2에서만, 3초).
// src = reporter_id = 나, rx/ry = POS_TABLE의 내 위치(모르면 0x8000), dst = 병사 전원.
static void broadcast_peer(const frame_msg_t *rep) {
#if PEER_ADV_ENABLE
  if (s_mode != 2 || !squad_map_peer_type_ok(rep->type)) return;
  uint8_t pl[16];
  int pn = frame_encode_payload(rep, pl, sizeof pl);
  if (pn < 0) return;
  frame_msg_t m;
  memset(&m, 0, sizeof m);
  m.type = MSG_PEER_REPORT;
  m.src = SOLDIER_ID;
  m.dst = FRAME_DST_ALL_SOLDIERS;
  m.seq = app_next_seq();
  m.u.peer_report.reporter_id = SOLDIER_ID;
  if (!commands_my_pos(&m.u.peer_report.rx, &m.u.peer_report.ry)) {
    m.u.peer_report.rx = SQUAD_POS_UNKNOWN;
    m.u.peer_report.ry = SQUAD_POS_UNKNOWN;
  }
  m.u.peer_report.orig_type = rep->type;
  m.u.peer_report.orig_payload = pl;
  m.u.peer_report.orig_len = (uint8_t)pn;
  uint8_t f[32];
  int n = frame_encode(&m, f, sizeof f);
  bool ok = n > 0 && radio_broadcast(f, (uint8_t)n, PEER_ADV_MS);
  app_log("peer adv %s seq=%u len=%d %s", type_name(rep->type), m.seq, n, ok ? "3s" : "fail");
#else
  (void)rep;
#endif
}

void reporter_report(uint8_t type, const geo_joy_t *dir, uint8_t count) {
  frame_msg_t m;
  memset(&m, 0, sizeof m);
  m.type = type;
  uint16_t heading = heading_deg();
  uint8_t clock = dir ? dir->clock : 0;
  uint16_t az = geo_azimuth_from(clock, heading);  // clock 0 또는 heading 없음 → 0xFFFF
  uint8_t dist = (dir && clock) ? dir->dist_band : FRAME_NO_DIST;
  switch (type) {
    case MSG_CONTACT:
      m.u.contact.azimuth = az; m.u.contact.clock = clock; m.u.contact.dist_band = dist;
      m.u.contact.count = count; m.u.contact.heading = heading;
      break;
    case MSG_SUSPICIOUS:
    case MSG_HAZARD:
      m.u.dir_report.azimuth = az; m.u.dir_report.clock = clock; m.u.dir_report.heading = heading;
      break;
    case MSG_CASUALTY_FOUND:
      m.u.casualty_found.azimuth = az; m.u.casualty_found.clock = clock;
      m.u.casualty_found.dist_band = dist; m.u.casualty_found.heading = heading;
      break;
    case MSG_CASUALTY_SELF:
      m.u.heading.heading = heading;
      break;
    case MSG_OK_READY:
    case MSG_WEAPON_AMMO:
      break;
    default:
      return;
  }
  build_and_submit(&m);
  broadcast_peer(&m);
  app_feedback(sent_clips(type));
}

void reporter_send_ref(uint8_t type, uint8_t ref_type, uint8_t ref_id) {
  frame_msg_t m;
  memset(&m, 0, sizeof m);
  m.type = type;
  m.u.ref.ref_type = ref_type;
  m.u.ref.ref_id = ref_id;
  build_and_submit(&m);
  app_feedback("sent");
}

void reporter_send_emcon_state(uint8_t mode) {
  frame_msg_t m;
  memset(&m, 0, sizeof m);
  m.type = MSG_EMCON_STATE;
  m.u.mode.mode = mode;
  build_and_submit(&m);
}

void reporter_send_voice_result(uint8_t voice_id, uint8_t status) {
  frame_msg_t m;
  memset(&m, 0, sizeof m);
  m.type = MSG_VOICE_RESULT;
  m.u.voice_result.voice_id = voice_id;
  m.u.voice_result.status = status;
  build_and_submit(&m);
}

void reporter_send_ranging(const ranging_entry_t *e, uint8_t n) {
  frame_msg_t m;
  memset(&m, 0, sizeof m);
  m.type = MSG_RANGING;
  if (n > RANGING_MAX_PEERS) n = RANGING_MAX_PEERS;
  m.u.ranging.n = n;
  for (uint8_t i = 0; i < n; i++) m.u.ranging.e[i] = e[i];
  build_and_submit(&m);
}

void reporter_on_rpt_ack(uint8_t ref_seq) {
  for (int i = 0; i < RPT_PENDING_MAX; i++) {
    if (s_pending[i].used && s_pending[i].seq == ref_seq) {
      s_pending[i].used = false;
      app_log("rpt_ack seq=%u ok (retries=%u)", ref_seq, s_pending[i].retries);
      app_feedback("received");  // 긴급 보고 확인음(프로토콜 §9.2)
      return;
    }
  }
  app_log("rpt_ack seq=%u (no wait)", ref_seq);
}

void reporter_begin(uint8_t mode) {
  report_queue_init(&s_queue);
  memset(s_pending, 0, sizeof s_pending);
  s_mode = mode;
}

void reporter_set_mode(uint8_t mode) {
  uint8_t old = s_mode;
  s_mode = mode;
  if (mode != 0 && old != mode) {
    s_flush_all = true;  // 모드 1/2 진입: 쌓인 보고를 오래된 순서로 송신
    s_batch_t = s_now;
  }
}

void reporter_on_link_ready() {
  if (s_mode != 0) s_flush_all = true;
}

static void flush_queue() {
  if (s_mode == 0 || !radio_can_send() || report_queue_count(&s_queue) == 0) {
    if (report_queue_count(&s_queue) == 0) s_flush_all = false;
    return;
  }
  if (s_mode == 1 && !s_flush_all && (uint32_t)(s_now - s_batch_t) >= EMCON1_BATCH_INTERVAL_MS) {
    s_flush_all = true;
    s_batch_t = s_now;
  }
  if (!s_flush_all || (int32_t)(s_now - s_retry_after) < 0) return;
  const rq_item_t *it = report_queue_peek(&s_queue);
  if (transmit(it->data, it->len)) {
    app_log("tx %s seq=%u sent(from queue, left=%u)", type_name(it->data[1]), it->data[2],
            (unsigned)(report_queue_count(&s_queue) - 1));
    report_queue_pop(&s_queue);
  } else {
    s_retry_after = s_now + TX_RETRY_BACKOFF_MS;
  }
}

static void check_retransmit() {
  if (s_mode == 0) return;  // 재전송은 EMCON 1/2에서만
  for (int i = 0; i < RPT_PENDING_MAX; i++) {
    pending_t *p = &s_pending[i];
    if (!p->used || (uint32_t)(s_now - p->last_tx) < RPT_ACK_TIMEOUT_MS) continue;
    if (p->retries >= RPT_MAX_RETRIES) {
      app_log("no RPT_ACK seq=%u after %u retries: give up", p->seq, p->retries);
      p->used = false;
      continue;
    }
    if (!radio_can_send()) continue;  // 연결되면 다시 시도
    if (app_send_raw(p->data, p->len)) {
      p->retries++;
      p->last_tx = s_now;
      app_log("retx %s seq=%u #%u", type_name(p->data[1]), p->seq, p->retries);
    }
  }
}

void reporter_loop(uint32_t now) {
  s_now = now;
  flush_queue();
  check_retransmit();
}
