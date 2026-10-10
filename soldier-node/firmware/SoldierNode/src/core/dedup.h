// (src_id, seq) 중복 제거, 최근 16개 기억 (프로토콜 §3.2, §8.1-6). Arduino 비의존, C 호환.
// 중복 판정 = (src, seq)가 같고 + payload 서명(CRC16)이 같고 + window_ms 안에 다시 온 경우.
//   seq는 0~255 순환이고 RPT_ACK·음성 청크도 seq를 쓰므로 금방 한 바퀴 돈다. 분대장이 재시작해도 0부터 다시 쓴다.
//   (src, seq)만 보면 오래전 명령과 seq가 겹친 새 명령을 중복으로 버린다(2026-10-10 장비 시험에서 발생).
//   진짜 재전송은 같은 seq·같은 내용·15초 안(§8.1-5)이므로 그대로 중복으로 처리된다.
#pragma once
#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define DEDUP_SIZE 16

typedef struct {
  uint8_t src[DEDUP_SIZE];
  uint8_t seq[DEDUP_SIZE];
  uint16_t sig[DEDUP_SIZE];
  uint32_t t[DEDUP_SIZE];
  uint8_t count;  // 채워진 개수(최대 DEDUP_SIZE)
  uint8_t next;   // 다음에 덮어쓸 위치(가장 오래된 것)
  uint32_t window_ms;
} dedup_t;

void dedup_init(dedup_t *d, uint32_t window_ms);

// 중복이면 true(기록 변화 없음). 처음(또는 내용이 다르거나 window가 지난 것)이면 기록하고 false.
bool dedup_seen(dedup_t *d, uint8_t src, uint8_t seq, uint16_t sig, uint32_t now);

#ifdef __cplusplus
}
#endif
