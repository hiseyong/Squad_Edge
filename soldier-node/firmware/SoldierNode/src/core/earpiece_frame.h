// 병사 단말 → 이어폰 단말(맥, tools/earpiece.py) USB 시리얼 프레임. BLE 프로토콜과 무관한 로컬 링크.
// 형식: A5 5A | type(1) | len(2, LE) | payload(len) | crc16(2, LE, CRC-16/CCITT-FALSE: type~payload)
// Arduino 비의존 → 호스트 테스트. tools/earpiece.py와 형식이 같아야 한다.
#pragma once
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define EP_SYNC0 0xA5
#define EP_SYNC1 0x5A
#define EP_OVERHEAD 7          // sync 2 + type 1 + len 2 + crc 2
#define EP_MAX_PAYLOAD 240     // USB CDC TX 버퍼 256B 안에 프레임 하나가 들어가게
#define EP_VOICE_DATA_MAX 192  // VOICE_DATA 한 프레임의 ADPCM 바이트

#define EP_HELLO       0x01  // soldier_id(1) version(1) — 2초마다(호스트가 포트를 열었을 때만)
#define EP_PLAY        0x02  // prio(1) kind(1: 0 명령 문장, 1 로컬 피드백) clips(ASCII, 공백 구분, 예 "c9 cover")
#define EP_VOICE_BEGIN 0x03  // voice_id(1) prio(1) predictor(2, int16) step_index(1) total_samples(4) total_bytes(4)
#define EP_VOICE_DATA  0x04  // voice_id(1) offset(4) data(≤192)
#define EP_VOICE_END   0x05  // voice_id(1) crc16(2) — 데이터 전체의 CRC(BLE VOICE_END와 같은 값)
#define EP_VOICE_STOP  0x06  // voice_id(1) — 전송 중단(버퍼 재사용 등)
#define EP_LOG         0x07  // ASCII — DEBUG_LOG 빌드의 LOG 사본(침묵 모드 등 BLE로 못 보낼 때도 맥에서 보이게)

#define EP_PRIO_FEEDBACK 0
#define EP_PRIO_NORMAL   1
#define EP_PRIO_URGENT   2

// 프레임 하나를 out에 쓴다. 반환: 전체 길이, 공간 부족/너무 긴 payload면 0.
size_t ep_encode(uint8_t type, const uint8_t *payload, uint16_t len, uint8_t *out, size_t cap);

#ifdef __cplusplus
}
#endif
