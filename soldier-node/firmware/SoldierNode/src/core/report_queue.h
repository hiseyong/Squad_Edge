// EMCON용 보고 큐 (프로토콜 §2, CLAUDE.md §6.2). 완성된 프레임을 그대로 보관, 오래된 순서로 꺼낸다.
// 최대 32건. 넘치면 일반 보고부터 버리고 긴급 보고(0x01, 0x03, 0x04, 0x06, 0x07)는 유지.
// Arduino 비의존, C 호환, 정적 배열.
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define REPORT_QUEUE_CAP        32
#define REPORT_QUEUE_FRAME_MAX  24   // 가장 긴 보고 = STATS(헤더 6 + 18)

typedef struct {
  uint8_t len;
  uint8_t data[REPORT_QUEUE_FRAME_MAX];
} rq_item_t;

typedef struct {
  rq_item_t items[REPORT_QUEUE_CAP];  // [0] = 가장 오래된 것
  uint8_t count;
} report_queue_t;

typedef enum {
  RQ_PUSHED = 0,         // 그냥 들어감
  RQ_PUSHED_DROPPED_OLD, // 들어가면서 기존 항목 하나를 버림(일반 우선, 없으면 가장 오래된 긴급)
  RQ_REJECTED,           // 새 항목을 버림(새 것이 일반이고 큐가 전부 긴급)
  RQ_INVALID             // 길이 오류
} rq_result_t;

void report_queue_init(report_queue_t *q);

// 프레임(헤더 포함)을 넣는다. 긴급 여부는 frame[1](msg_type)로 판단.
rq_result_t report_queue_push(report_queue_t *q, const uint8_t *frame, size_t len);

// 가장 오래된 항목. 비었으면 NULL.
const rq_item_t *report_queue_peek(const report_queue_t *q);
void report_queue_pop(report_queue_t *q);
uint8_t report_queue_count(const report_queue_t *q);

#ifdef __cplusplus
}
#endif
