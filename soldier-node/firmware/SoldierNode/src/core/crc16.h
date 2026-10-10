// CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF, 반사 없음, xorout 0). 프로토콜 §7.3 VOICE_END.
// Arduino 비의존, C 호환.
#pragma once
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define CRC16_INIT 0xFFFFu

// 이어서 계산할 때는 앞 결과를 crc로 넘긴다. 처음에는 CRC16_INIT.
uint16_t crc16_update(uint16_t crc, const uint8_t *data, size_t len);
uint16_t crc16_ccitt_false(const uint8_t *data, size_t len);

#ifdef __cplusplus
}
#endif
