// 넘침 정책 (프로토콜 v1.0.1 §2):
// - 새 항목이 들어갈 자리가 없으면 가장 오래된 일반 보고를 버린다.
// - 큐가 전부 긴급인데 새 항목이 일반이면 새 항목을 버린다.
// - 큐가 전부 긴급인데 새 항목도 긴급이면 가장 오래된 긴급을 버린다(최신 상황 우선).
#include "report_queue.h"

#include "frame.h"

static bool item_urgent(const rq_item_t *it) {
  return it->len >= 2 && frame_type_is_urgent(it->data[1]);
}

static void remove_at(report_queue_t *q, uint8_t idx) {
  for (uint8_t i = idx; i + 1 < q->count; i++) q->items[i] = q->items[i + 1];
  q->count--;
}

void report_queue_init(report_queue_t *q) {
  q->count = 0;
}

rq_result_t report_queue_push(report_queue_t *q, const uint8_t *frame, size_t len) {
  if (len < FRAME_HDR_LEN || len > REPORT_QUEUE_FRAME_MAX) return RQ_INVALID;
  bool urgent = frame_type_is_urgent(frame[1]);
  rq_result_t res = RQ_PUSHED;

  if (q->count >= REPORT_QUEUE_CAP) {
    int victim = -1;
    for (uint8_t i = 0; i < q->count; i++) {
      if (!item_urgent(&q->items[i])) { victim = i; break; }
    }
    if (victim < 0) {
      if (!urgent) return RQ_REJECTED;
      victim = 0;
    }
    remove_at(q, (uint8_t)victim);
    res = RQ_PUSHED_DROPPED_OLD;
  }

  rq_item_t *it = &q->items[q->count++];
  it->len = (uint8_t)len;
  for (size_t i = 0; i < len; i++) it->data[i] = frame[i];
  return res;
}

const rq_item_t *report_queue_peek(const report_queue_t *q) {
  return q->count ? &q->items[0] : 0;
}

void report_queue_pop(report_queue_t *q) {
  if (q->count) remove_at(q, 0);
}

uint8_t report_queue_count(const report_queue_t *q) {
  return q->count;
}
