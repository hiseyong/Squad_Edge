// 문장 템플릿 구현 (프로토콜 §6.2 표 그대로).
#include "phrases.h"

#include "../core/geo.h"

static const char *const kClock[13] = {"", "c1", "c2", "c3", "c4", "c5", "c6", "c7", "c8", "c9", "c10", "c11", "c12"};

static void add(phrase_t *p, const char *clip) {
  if (p->n < PHRASE_MAX_CLIPS) p->clip[p->n++] = clip;
}

static void add_dir(phrase_t *p, uint16_t az, uint16_t heading) {
  uint8_t clock = geo_clock_from(az, heading);  // az 없음 → 0
  if (clock == 0) {
    p->flags |= PHRASE_F_NO_DIR;
    return;
  }
  add(p, kClock[clock]);
}

static void add_dist(phrase_t *p, uint8_t dist) {
  if (dist == 0) add(p, "near");
  else if (dist == 1) add(p, "mid");
  else if (dist == 2) add(p, "far");
}

static void add_count(phrase_t *p, uint8_t count) {
  static const char *const kNum[6] = {"unknown", "n1", "n2", "n3", "n4", "many"};
  add(p, kNum[count > 5 ? 5 : count]);
}

void phrases_for_cmd(const msg_cmd_button_t *c, uint16_t my_heading, uint16_t rally_az, phrase_t *out) {
  out->n = 0;
  out->flags = 0;
  switch (c->cmd_code) {
    case CMD_HALT: add(out, "halt"); break;
    case CMD_TAKE_COVER: if (c->azimuth != FRAME_NO_AZIMUTH) add_dir(out, c->azimuth, my_heading); add(out, "cover"); break;
    case CMD_ADVANCE: if (c->azimuth != FRAME_NO_AZIMUTH) add_dir(out, c->azimuth, my_heading); add(out, "advance"); break;
    case CMD_WITHDRAW: if (c->azimuth != FRAME_NO_AZIMUTH) add_dir(out, c->azimuth, my_heading); add(out, "withdraw"); break;
    case CMD_RALLY: add_dir(out, rally_az, my_heading); add(out, "rally"); break;  // 방향은 병사가 계산(§6.2)
    case CMD_OPEN_FIRE: add_dir(out, c->azimuth, my_heading); add_dist(out, c->dist_band); add(out, "open_fire"); break;
    case CMD_CEASE_FIRE: add(out, "cease_fire"); break;
    case CMD_OBSERVE: add_dir(out, c->azimuth, my_heading); add(out, "observe"); break;
    case CMD_ENEMY_INFO:  // "적 [수] [방향] [거리]"
      add(out, "enemy"); add_count(out, c->extra); add_dir(out, c->azimuth, my_heading); add_dist(out, c->dist_band);
      break;
    case CMD_REPORT_STATUS: add(out, "report_status"); break;
    case CMD_SILENCE: add(out, "silence"); break;
    case CMD_HOLD: add(out, "hold"); break;
    case CMD_CANCEL: add(out, "cancel"); break;
    default: out->flags |= PHRASE_F_UNKNOWN_CMD; break;
  }
}

void phrases_for_peer(uint8_t type, uint8_t count, uint8_t clock, uint8_t dist_band, phrase_t *out) {
  out->n = 0;
  out->flags = 0;
  switch (type) {
    case MSG_CONTACT: add(out, "enemy"); add_count(out, count); break;
    case MSG_SUSPICIOUS: add(out, "suspicious"); break;
    case MSG_HAZARD: add(out, "hazard"); break;
    case MSG_CASUALTY_FOUND: add(out, "casualty"); break;
    default: out->flags |= PHRASE_F_UNKNOWN_CMD; return;
  }
  if (clock >= 1 && clock <= 12) add(out, kClock[clock]);
  else out->flags |= PHRASE_F_NO_DIR;
  add_dist(out, dist_band);
}

size_t phrases_join(const phrase_t *p, char *buf, size_t cap) {
  size_t n = 0;
  if (cap == 0) return 0;
  for (uint8_t i = 0; i < p->n; i++) {
    for (const char *s = (i ? " " : ""); *s && n + 1 < cap; s++) buf[n++] = *s;
    for (const char *s = p->clip[i]; *s && n + 1 < cap; s++) buf[n++] = *s;
  }
  buf[n] = '\0';
  return n;
}

const char *phrases_cmd_name(uint8_t code) {
  switch (code) {
    case CMD_HALT: return "HALT";
    case CMD_TAKE_COVER: return "TAKE_COVER";
    case CMD_ADVANCE: return "ADVANCE";
    case CMD_WITHDRAW: return "WITHDRAW";
    case CMD_RALLY: return "RALLY";
    case CMD_OPEN_FIRE: return "OPEN_FIRE";
    case CMD_CEASE_FIRE: return "CEASE_FIRE";
    case CMD_OBSERVE: return "OBSERVE";
    case CMD_ENEMY_INFO: return "ENEMY_INFO";
    case CMD_REPORT_STATUS: return "REPORT_STATUS";
    case CMD_SILENCE: return "SILENCE";
    case CMD_HOLD: return "HOLD";
    case CMD_CANCEL: return "CANCEL";
    default: return "?";
  }
}
