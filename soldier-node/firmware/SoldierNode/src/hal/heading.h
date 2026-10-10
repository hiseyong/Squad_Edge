// 방위 소스 (CLAUDE.md §6.8). HEADING_MODE: NONE(0xFFFF) / FIXED(HEADING_FIXED_DEG) / SENSOR(단계 8, 지금은 스텁).
// 다른 모듈은 heading_deg()만 쓰고 모드를 몰라야 한다.
#pragma once
#include <stdbool.h>
#include <stdint.h>

void heading_begin();
bool heading_available();          // 유효한 방위가 있는지
uint16_t heading_deg();            // 0~359 또는 0xFFFF
void heading_start_calibration();  // 버튼1+버튼4 3초 (SENSOR 모드에서만 의미)
bool heading_calibration_done();
