// POS_TABLE, PEER_REPORT 변환 구현 (CLAUDE.md §6.7).
#include "squad_map.h"

#include <string.h>

void squad_map_init(squad_map_t *s) { memset(s, 0, sizeof *s); }

void squad_map_set(squad_map_t *s, const msg_pos_table_t *t) {
  s->t = *t;
  s->valid = true;
}

bool squad_map_pos(const squad_map_t *s, uint8_t id, int16_t *x, int16_t *y) {
  if (!s->valid) return false;
  for (uint8_t i = 0; i < s->t.n; i++) {
    if (s->t.e[i].id == id) {
      *x = s->t.e[i].x;
      *y = s->t.e[i].y;
      return true;
    }
  }
  if (id == FRAME_ID_LEADER) {
    *x = 0;
    *y = 0;
    return true;
  }
  return false;
}

uint16_t squad_map_rally_az(const squad_map_t *s, uint8_t my_id) {
  int16_t mx, my, lx, ly;
  if (!squad_map_pos(s, my_id, &mx, &my) || !squad_map_pos(s, FRAME_ID_LEADER, &lx, &ly)) return GEO_NONE;
  uint16_t b;
  float r;
  geo_bearing_range((float)mx, (float)my, (float)lx, (float)ly, &b, &r);
  return r < 10.0f ? GEO_NONE : b;  // 1m 안 = 내가 분대장 위치 → 방향 없음
}

bool squad_map_peer_type_ok(uint8_t t) {
  return t == MSG_CONTACT || t == MSG_SUSPICIOUS || t == MSG_HAZARD || t == MSG_CASUALTY_FOUND;
}

int squad_map_peer(const squad_map_t *s, uint8_t my_id, uint16_t my_heading, const msg_peer_report_t *pr,
                   squad_peer_t *out) {
  memset(out, 0, sizeof *out);
  out->bearing = GEO_NONE;
  out->dist_band = GEO_DIST_NONE;
  if (pr->reporter_id == my_id) return SQ_ERR_SELF;
  if (!squad_map_peer_type_ok(pr->orig_type)) return SQ_ERR_TYPE;
  frame_msg_t o;
  if (frame_decode_payload(pr->orig_type, pr->orig_payload, pr->orig_len, &o) != FRAME_OK) return SQ_ERR_PAYLOAD;
  out->type = pr->orig_type;

  uint16_t az = GEO_NONE;
  uint8_t band = GEO_DIST_NONE;  // 보고자 기준 거리(SUSPICIOUS/HAZARD는 없음 → 표적 계산 시 100m)
  switch (pr->orig_type) {
    case MSG_CONTACT: az = o.u.contact.azimuth; band = o.u.contact.dist_band; out->count = o.u.contact.count; break;
    case MSG_SUSPICIOUS:
    case MSG_HAZARD: az = o.u.dir_report.azimuth; break;
    case MSG_CASUALTY_FOUND: az = o.u.casualty_found.azimuth; band = o.u.casualty_found.dist_band; break;
  }

  // 보고자 위치: PEER_REPORT의 rx/ry(분대장 중계 또는 보고자가 아는 자기 위치), 모르면 내 POS_TABLE
  int16_t rx = pr->rx, ry = pr->ry, mx, my;
  bool rep_ok = !(rx == SQUAD_POS_UNKNOWN || ry == SQUAD_POS_UNKNOWN) || squad_map_pos(s, pr->reporter_id, &rx, &ry);
  bool me_ok = squad_map_pos(s, my_id, &mx, &my);

  if (rep_ok && me_ok) {
    if (az != GEO_NONE) {
      geo_rel_t rel;
      geo_peer_to_me(rx, ry, az, band, mx, my, my_heading, &rel);
      out->bearing = rel.bearing;
      out->clock = rel.clock;
      out->dist_band = rel.dist_band;
      out->range_dm = rel.range_dm;
    } else {
      // 방향 미상 보고: 표적 위치를 모르므로 보고자 쪽 방향·거리로 알린다
      geo_bearing_range((float)mx, (float)my, (float)rx, (float)ry, &out->bearing, &out->range_dm);
      out->clock = geo_clock_from(out->bearing, my_heading);
      out->dist_band = geo_dm_to_dist_band(out->range_dm);
      out->flags |= SQ_F_TOWARD_REPORTER;
    }
  } else {
    // POS_TABLE 전: 보고자 기준 방향 그대로(CLAUDE.md §6.7)
    out->flags |= SQ_F_NO_POS;
    out->bearing = az;
    out->clock = geo_clock_from(az, my_heading);
    out->dist_band = band;
    if (az == GEO_NONE) out->flags |= SQ_F_NO_DIR;
  }
  return SQ_OK;
}
