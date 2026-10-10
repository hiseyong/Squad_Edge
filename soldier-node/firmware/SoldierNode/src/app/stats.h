// 모드별 송신 통계 (CLAUDE.md §6.10, 프로토콜 §5.1 STATS). 무선(BLE notify)으로 실제 나간 프레임만 센다.
// 헤더 포함 바이트, 재전송 포함. 디버그 LOG(0x7F, 프로토콜 밖)는 제외. USB 이어폰 링크는 무선이 아니라 제외.
#pragma once
#include <stdint.h>

#include "../core/frame.h"

void stats_on_tx(uint8_t mode, uint16_t bytes);
void stats_fill(msg_stats_t *out);
