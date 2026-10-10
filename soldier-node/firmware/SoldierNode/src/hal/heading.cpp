// 방위 소스 구현. SENSOR 모드는 9축 센서 확보 후 단계 8에서 구현(지금은 0xFFFF).
#include "heading.h"

#include "../../config.h"

void heading_begin() {}

uint16_t heading_deg() {
#if HEADING_MODE == HEADING_MODE_FIXED
  return HEADING_FIXED_DEG;
#else
  return HEADING_NONE;
#endif
}

bool heading_available() { return heading_deg() != HEADING_NONE; }

void heading_start_calibration() {}

bool heading_calibration_done() { return true; }
