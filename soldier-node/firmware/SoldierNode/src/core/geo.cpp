// 방향 계산 구현.
#include "geo.h"

#include <math.h>

#define GEO_PI_F 3.14159265358979f

static int norm360(int32_t deg) {
  int32_t r = deg % 360;
  return (int)(r < 0 ? r + 360 : r);
}

uint8_t geo_clock_from(uint16_t azimuth, uint16_t my_heading) {
  if (azimuth == GEO_NONE) return 0;
  int32_t heading = (my_heading == GEO_NONE) ? 0 : my_heading;
  int rel = norm360((int32_t)azimuth - heading);
  int clock = (rel + 15) / 30;  // 프로토콜 v1.0.1 §5.1 규칙: .5는 올림 (15도 → 1시, 345도 → 12시)
  return (uint8_t)(clock == 0 ? 12 : clock);
}

uint16_t geo_azimuth_from(uint8_t clock, uint16_t my_heading) {
  if (clock == 0 || clock > 12 || my_heading == GEO_NONE) return GEO_NONE;
  return (uint16_t)norm360((int32_t)my_heading + ((int32_t)clock - 12) * 30);
}

int32_t geo_dist_band_to_dm(uint8_t dist_band) {
  switch (dist_band) {
    case GEO_DIST_NEAR: return 500;
    case GEO_DIST_FAR: return 2000;
    case GEO_DIST_MID:
    default: return 1000;
  }
}

uint8_t geo_dm_to_dist_band(float dist_dm) {
  if (dist_dm < 750.0f) return GEO_DIST_NEAR;
  if (dist_dm < 1500.0f) return GEO_DIST_MID;
  return GEO_DIST_FAR;
}

bool geo_target_pos(int16_t rep_x, int16_t rep_y, uint16_t azimuth, uint8_t dist_band,
                    float *tx, float *ty) {
  if (azimuth == GEO_NONE) return false;
  float a = (float)azimuth * GEO_PI_F / 180.0f;
  float d = (float)geo_dist_band_to_dm(dist_band);
  *tx = (float)rep_x + d * sinf(a);
  *ty = (float)rep_y + d * cosf(a);
  return true;
}

void geo_bearing_range(float px, float py, float tx, float ty, uint16_t *bearing, float *range_dm) {
  float dx = tx - px;
  float dy = ty - py;
  float deg = atan2f(dx, dy) * 180.0f / GEO_PI_F;  // 북 = 0, 동 = 90
  *bearing = (uint16_t)norm360((int32_t)lroundf(deg));
  *range_dm = sqrtf(dx * dx + dy * dy);
}

geo_joy_t geo_joy_direction(int32_t dx, int32_t dy, int32_t max_x, int32_t max_y, bool inv_x, bool inv_y,
                            int16_t rotate_deg, uint8_t deadzone_pct, uint8_t far_pct) {
  geo_joy_t out = {0, GEO_DIST_NONE, 0};
  if (max_x <= 0 || max_y <= 0) return out;
  if (inv_x) dx = -dx;
  if (inv_y) dy = -dy;
  float fx = (float)dx / (float)max_x;
  float fy = (float)dy / (float)max_y;
  float r = sqrtf(fx * fx + fy * fy);
  int32_t pct = (int32_t)lroundf(r * 100.0f);
  out.pct = (uint8_t)(pct > 100 ? 100 : pct);
  if (out.pct < deadzone_pct) return out;
  float deg = atan2f(fx, fy) * 180.0f / GEO_PI_F;  // 전방 = 0, 오른쪽 = 90
  int32_t d = norm360((int32_t)lroundf(deg) + rotate_deg);
  out.clock = geo_clock_from((uint16_t)d, 0);
  out.dist_band = (out.pct >= far_pct) ? GEO_DIST_FAR : GEO_DIST_NEAR;
  return out;
}

bool geo_peer_to_me(int16_t rep_x, int16_t rep_y, uint16_t azimuth, uint8_t dist_band,
                    int16_t my_x, int16_t my_y, uint16_t my_heading, geo_rel_t *out) {
  float tx, ty;
  if (!geo_target_pos(rep_x, rep_y, azimuth, dist_band, &tx, &ty)) return false;
  geo_bearing_range((float)my_x, (float)my_y, tx, ty, &out->bearing, &out->range_dm);
  out->clock = geo_clock_from(out->bearing, my_heading);
  out->dist_band = geo_dm_to_dist_band(out->range_dm);
  return true;
}
