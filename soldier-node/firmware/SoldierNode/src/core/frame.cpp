// 프로토콜 프레임 인코드/디코드 구현.
#include "frame.h"

// ---------- 바이트 쓰기/읽기 도우미 (리틀엔디언, 경계 검사) ----------
typedef struct { uint8_t *p; size_t cap; size_t n; bool ok; } wr_t;
typedef struct { const uint8_t *p; size_t len; size_t n; bool ok; } rd_t;

static void w8(wr_t *w, uint8_t v) {
  if (w->n + 1 > w->cap) { w->ok = false; return; }
  w->p[w->n++] = v;
}
static void w16(wr_t *w, uint16_t v) { w8(w, (uint8_t)(v & 0xFF)); w8(w, (uint8_t)(v >> 8)); }
static void w32(wr_t *w, uint32_t v) { w16(w, (uint16_t)(v & 0xFFFF)); w16(w, (uint16_t)(v >> 16)); }
static void wbytes(wr_t *w, const uint8_t *src, size_t len) {
  if (len > 0 && src == 0) { w->ok = false; return; }
  for (size_t i = 0; i < len; i++) w8(w, src[i]);
}

static uint8_t r8(rd_t *r) {
  if (r->n + 1 > r->len) { r->ok = false; return 0; }
  return r->p[r->n++];
}
static uint16_t r16(rd_t *r) { uint16_t lo = r8(r); uint16_t hi = r8(r); return (uint16_t)(lo | (hi << 8)); }
static uint32_t r32(rd_t *r) { uint32_t lo = r16(r); uint32_t hi = r16(r); return lo | (hi << 16); }

// ---------- payload ----------
int frame_encode_payload(const frame_msg_t *m, uint8_t *out, size_t cap) {
  wr_t w = { out, cap, 0, true };
  switch (m->type) {
    case MSG_CONTACT:
      w16(&w, m->u.contact.azimuth); w8(&w, m->u.contact.clock); w8(&w, m->u.contact.dist_band);
      w8(&w, m->u.contact.count); w16(&w, m->u.contact.heading);
      break;
    case MSG_SUSPICIOUS:
    case MSG_HAZARD:
      w16(&w, m->u.dir_report.azimuth); w8(&w, m->u.dir_report.clock); w16(&w, m->u.dir_report.heading);
      break;
    case MSG_CASUALTY_FOUND:
      w16(&w, m->u.casualty_found.azimuth); w8(&w, m->u.casualty_found.clock);
      w8(&w, m->u.casualty_found.dist_band); w16(&w, m->u.casualty_found.heading);
      break;
    case MSG_OK_READY:
    case MSG_WEAPON_AMMO:
    case MSG_REQ_STATS:
      break;
    case MSG_CASUALTY_SELF:
    case MSG_BEACON:
      w16(&w, m->u.heading.heading);
      break;
    case MSG_ACK:
    case MSG_CANNOT_COMPLY:
      w8(&w, m->u.ref.ref_type); w8(&w, m->u.ref.ref_id);
      break;
    case MSG_VOICE_RESULT:
      w8(&w, m->u.voice_result.voice_id); w8(&w, m->u.voice_result.status);
      break;
    case MSG_EMCON_STATE:
    case MSG_EMCON_SET:
      w8(&w, m->u.mode.mode);
      break;
    case MSG_HEARTBEAT:
      w16(&w, m->u.heartbeat.heading); w16(&w, m->u.heartbeat.battery_mv);
      w8(&w, m->u.heartbeat.heart_rate); w8(&w, m->u.heartbeat.motion);
      break;
    case MSG_STATS:
      for (int i = 0; i < 3; i++) w16(&w, m->u.stats.tx_frames[i]);
      for (int i = 0; i < 3; i++) w32(&w, m->u.stats.tx_bytes[i]);
      break;
    case MSG_RANGING:
      if (m->u.ranging.n > RANGING_MAX_PEERS) return FRAME_ERR_PAYLOAD;
      w8(&w, m->u.ranging.n);
      for (int i = 0; i < m->u.ranging.n; i++) {
        w8(&w, m->u.ranging.e[i].peer_id); w8(&w, (uint8_t)m->u.ranging.e[i].rssi_avg);
        w8(&w, m->u.ranging.e[i].samples);
      }
      break;
    case MSG_CMD_BUTTON:
      w8(&w, m->u.cmd_button.cmd_code); w16(&w, m->u.cmd_button.azimuth); w8(&w, m->u.cmd_button.dist_band);
      w8(&w, m->u.cmd_button.extra); w8(&w, m->u.cmd_button.priority);
      break;
    case MSG_VOICE_BEGIN: {
      const msg_voice_begin_t *v = &m->u.voice_begin;
      w8(&w, v->voice_id); w8(&w, v->codec); w16(&w, v->sample_rate); w32(&w, v->total_samples);
      w16(&w, v->total_chunks); w16(&w, (uint16_t)v->predictor); w8(&w, v->step_index); w8(&w, v->priority);
      break;
    }
    case MSG_VOICE_CHUNK:
      w8(&w, m->u.voice_chunk.voice_id); w16(&w, m->u.voice_chunk.chunk_idx);
      wbytes(&w, m->u.voice_chunk.data, m->u.voice_chunk.data_len);
      break;
    case MSG_VOICE_END:
      w8(&w, m->u.voice_end.voice_id); w16(&w, m->u.voice_end.crc16);
      break;
    case MSG_PEER_REPORT:
      w8(&w, m->u.peer_report.reporter_id); w16(&w, (uint16_t)m->u.peer_report.rx);
      w16(&w, (uint16_t)m->u.peer_report.ry); w8(&w, m->u.peer_report.orig_type);
      wbytes(&w, m->u.peer_report.orig_payload, m->u.peer_report.orig_len);
      break;
    case MSG_POS_TABLE:
      if (m->u.pos_table.n > POS_TABLE_MAX) return FRAME_ERR_PAYLOAD;
      w8(&w, m->u.pos_table.n);
      for (int i = 0; i < m->u.pos_table.n; i++) {
        const pos_entry_t *e = &m->u.pos_table.e[i];
        w8(&w, e->id); w16(&w, (uint16_t)e->x); w16(&w, (uint16_t)e->y); w16(&w, e->heading);
      }
      break;
    case MSG_RPT_ACK:
      w8(&w, m->u.rpt_ack.ref_seq);
      break;
    case MSG_LOG:
      if (m->u.log.len > LOG_MAX_TEXT) return FRAME_ERR_PAYLOAD;
      wbytes(&w, (const uint8_t *)m->u.log.text, m->u.log.len);
      break;
    default:
      return FRAME_ERR_TYPE;
  }
  if (!w.ok) return FRAME_ERR_CAP;
  return (int)w.n;
}

int frame_encode(const frame_msg_t *m, uint8_t *out, size_t cap) {
  if (cap < FRAME_HDR_LEN) return FRAME_ERR_CAP;
  size_t room = cap - FRAME_HDR_LEN;
  if (room > FRAME_MAX_PAYLOAD) room = FRAME_MAX_PAYLOAD;
  int plen = frame_encode_payload(m, out + FRAME_HDR_LEN, room);
  if (plen < 0) return plen;
  out[0] = FRAME_VER;
  out[1] = m->type;
  out[2] = m->seq;
  out[3] = m->src;
  out[4] = m->dst;
  out[5] = (uint8_t)plen;
  return FRAME_HDR_LEN + plen;
}

// 고정 길이 payload의 길이. 가변이면 -1, 알 수 없는 type이면 -2.
static int fixed_payload_len(uint8_t type) {
  switch (type) {
    case MSG_CONTACT: return 7;
    case MSG_SUSPICIOUS: case MSG_HAZARD: return 5;
    case MSG_CASUALTY_FOUND: return 6;
    case MSG_OK_READY: case MSG_WEAPON_AMMO: case MSG_REQ_STATS: return 0;
    case MSG_CASUALTY_SELF: case MSG_BEACON: return 2;
    case MSG_ACK: case MSG_CANNOT_COMPLY: case MSG_VOICE_RESULT: return 2;
    case MSG_EMCON_STATE: case MSG_EMCON_SET: case MSG_RPT_ACK: return 1;
    case MSG_HEARTBEAT: return 6;
    case MSG_STATS: return 18;
    case MSG_CMD_BUTTON: return 6;
    case MSG_VOICE_BEGIN: return 14;
    case MSG_VOICE_END: return 3;
    case MSG_RANGING: case MSG_VOICE_CHUNK: case MSG_PEER_REPORT: case MSG_POS_TABLE: case MSG_LOG: return -1;
    default: return -2;
  }
}

int frame_decode_payload(uint8_t type, const uint8_t *p, size_t len, frame_msg_t *out) {
  int fixed = fixed_payload_len(type);
  if (fixed == -2) return FRAME_ERR_TYPE;
  if (fixed >= 0 && (size_t)fixed != len) return FRAME_ERR_PAYLOAD;

  rd_t r = { p, len, 0, true };
  out->type = type;
  switch (type) {
    case MSG_CONTACT:
      out->u.contact.azimuth = r16(&r); out->u.contact.clock = r8(&r); out->u.contact.dist_band = r8(&r);
      out->u.contact.count = r8(&r); out->u.contact.heading = r16(&r);
      break;
    case MSG_SUSPICIOUS:
    case MSG_HAZARD:
      out->u.dir_report.azimuth = r16(&r); out->u.dir_report.clock = r8(&r); out->u.dir_report.heading = r16(&r);
      break;
    case MSG_CASUALTY_FOUND:
      out->u.casualty_found.azimuth = r16(&r); out->u.casualty_found.clock = r8(&r);
      out->u.casualty_found.dist_band = r8(&r); out->u.casualty_found.heading = r16(&r);
      break;
    case MSG_OK_READY:
    case MSG_WEAPON_AMMO:
    case MSG_REQ_STATS:
      break;
    case MSG_CASUALTY_SELF:
    case MSG_BEACON:
      out->u.heading.heading = r16(&r);
      break;
    case MSG_ACK:
    case MSG_CANNOT_COMPLY:
      out->u.ref.ref_type = r8(&r); out->u.ref.ref_id = r8(&r);
      break;
    case MSG_VOICE_RESULT:
      out->u.voice_result.voice_id = r8(&r); out->u.voice_result.status = r8(&r);
      break;
    case MSG_EMCON_STATE:
    case MSG_EMCON_SET:
      out->u.mode.mode = r8(&r);
      if (out->u.mode.mode > 2) return FRAME_ERR_PAYLOAD;
      break;
    case MSG_HEARTBEAT:
      out->u.heartbeat.heading = r16(&r); out->u.heartbeat.battery_mv = r16(&r);
      out->u.heartbeat.heart_rate = r8(&r); out->u.heartbeat.motion = r8(&r);
      break;
    case MSG_STATS:
      for (int i = 0; i < 3; i++) out->u.stats.tx_frames[i] = r16(&r);
      for (int i = 0; i < 3; i++) out->u.stats.tx_bytes[i] = r32(&r);
      break;
    case MSG_RANGING: {
      if (len < 1) return FRAME_ERR_PAYLOAD;
      uint8_t n = r8(&r);
      if (n > RANGING_MAX_PEERS || len != 1u + 3u * n) return FRAME_ERR_PAYLOAD;
      out->u.ranging.n = n;
      for (int i = 0; i < n; i++) {
        out->u.ranging.e[i].peer_id = r8(&r); out->u.ranging.e[i].rssi_avg = (int8_t)r8(&r);
        out->u.ranging.e[i].samples = r8(&r);
      }
      break;
    }
    case MSG_CMD_BUTTON:
      out->u.cmd_button.cmd_code = r8(&r); out->u.cmd_button.azimuth = r16(&r);
      out->u.cmd_button.dist_band = r8(&r); out->u.cmd_button.extra = r8(&r); out->u.cmd_button.priority = r8(&r);
      break;
    case MSG_VOICE_BEGIN: {
      msg_voice_begin_t *v = &out->u.voice_begin;
      v->voice_id = r8(&r); v->codec = r8(&r); v->sample_rate = r16(&r); v->total_samples = r32(&r);
      v->total_chunks = r16(&r); v->predictor = (int16_t)r16(&r); v->step_index = r8(&r); v->priority = r8(&r);
      if (v->step_index > 88) return FRAME_ERR_PAYLOAD;
      break;
    }
    case MSG_VOICE_CHUNK:
      if (len < 3) return FRAME_ERR_PAYLOAD;
      out->u.voice_chunk.voice_id = r8(&r); out->u.voice_chunk.chunk_idx = r16(&r);
      out->u.voice_chunk.data = p + 3; out->u.voice_chunk.data_len = (uint8_t)(len - 3);
      break;
    case MSG_VOICE_END:
      out->u.voice_end.voice_id = r8(&r); out->u.voice_end.crc16 = r16(&r);
      break;
    case MSG_PEER_REPORT:
      if (len < 6) return FRAME_ERR_PAYLOAD;
      out->u.peer_report.reporter_id = r8(&r); out->u.peer_report.rx = (int16_t)r16(&r);
      out->u.peer_report.ry = (int16_t)r16(&r); out->u.peer_report.orig_type = r8(&r);
      out->u.peer_report.orig_payload = p + 6; out->u.peer_report.orig_len = (uint8_t)(len - 6);
      break;
    case MSG_POS_TABLE: {
      if (len < 1) return FRAME_ERR_PAYLOAD;
      uint8_t n = r8(&r);
      if (n > POS_TABLE_MAX || len != 1u + 7u * n) return FRAME_ERR_PAYLOAD;
      out->u.pos_table.n = n;
      for (int i = 0; i < n; i++) {
        pos_entry_t *e = &out->u.pos_table.e[i];
        e->id = r8(&r); e->x = (int16_t)r16(&r); e->y = (int16_t)r16(&r); e->heading = r16(&r);
      }
      break;
    }
    case MSG_RPT_ACK:
      out->u.rpt_ack.ref_seq = r8(&r);
      break;
    case MSG_LOG:
      if (len > LOG_MAX_TEXT) return FRAME_ERR_PAYLOAD;
      out->u.log.text = (const char *)p; out->u.log.len = (uint8_t)len;
      break;
    default:
      return FRAME_ERR_TYPE;
  }
  return r.ok ? FRAME_OK : FRAME_ERR_PAYLOAD;
}

int frame_decode(const uint8_t *buf, size_t n, frame_msg_t *out) {
  if (n < FRAME_HDR_LEN) return FRAME_ERR_SHORT;
  if (buf[0] != FRAME_VER) return FRAME_ERR_VER;
  if ((size_t)buf[5] != n - FRAME_HDR_LEN) return FRAME_ERR_LEN;
  out->seq = buf[2];
  out->src = buf[3];
  out->dst = buf[4];
  return frame_decode_payload(buf[1], buf + FRAME_HDR_LEN, buf[5], out);
}

uint8_t frame_dst_bit(uint8_t soldier_id) {
  if (soldier_id < 1 || soldier_id > 5) return 0;
  return (uint8_t)(1u << (soldier_id - 1));
}

bool frame_dst_has_soldier(uint8_t dst_mask, uint8_t soldier_id) {
  uint8_t bit = frame_dst_bit(soldier_id);
  return bit != 0 && (dst_mask & bit) != 0;
}

int frame_receive(const uint8_t *buf, size_t n, uint8_t soldier_id, frame_msg_t *out) {
  int rc = frame_decode(buf, n, out);
  if (rc != FRAME_OK) return rc;
  if (!frame_dst_has_soldier(out->dst, soldier_id)) return FRAME_ERR_DST;
  return FRAME_OK;
}

bool frame_type_is_urgent(uint8_t type) {
  return type == MSG_CONTACT || type == MSG_HAZARD || type == MSG_CASUALTY_FOUND ||
         type == MSG_WEAPON_AMMO || type == MSG_CASUALTY_SELF;
}
