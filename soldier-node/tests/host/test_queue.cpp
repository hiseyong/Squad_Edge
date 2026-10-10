// dedup + report_queue 단위 테스트: 넘침, 긴급 보존.
#include <string.h>

#include "dedup.h"
#include "frame.h"
#include "report_queue.h"
#include "test_util.h"

static void test_dedup() {
  dedup_t d;
  const uint32_t W = 60000;
  dedup_init(&d, W);
  CHECK(!dedup_seen(&d, 0, 5, 0xAAAA, 1000));
  CHECK(dedup_seen(&d, 0, 5, 0xAAAA, 1500));       // 같은 (src, seq, 내용) → 중복
  CHECK(dedup_seen(&d, 0, 5, 0xAAAA, 16000));      // 15초 뒤 재전송(§8.1-5)도 중복
  CHECK(!dedup_seen(&d, 1, 5, 0xAAAA, 2000));      // src가 다르면 새 것
  CHECK(!dedup_seen(&d, 0, 6, 0xAAAA, 2000));      // seq가 다르면 새 것

  // 2026-10-10 장비 시험 재현: 분대장 재시작/seq 순환으로 같은 seq에 다른 명령 → 새 명령이어야 한다
  dedup_init(&d, W);
  CHECK(!dedup_seen(&d, 0, 1, 0x1111, 100000));    // 20:02 TAKE_COVER seq 1
  CHECK(!dedup_seen(&d, 0, 1, 0x2222, 900000));    // 20:15 HALT seq 1 (내용 다름) → 새 명령
  CHECK(dedup_seen(&d, 0, 1, 0x2222, 915000));     // 그 HALT의 15초 재전송 → 중복
  // 같은 내용이라도 window(60초)가 지나면 새 명령(예: 나중에 다시 내린 같은 "정지")
  CHECK(!dedup_seen(&d, 0, 1, 0x2222, 975000));
  CHECK(dedup_seen(&d, 0, 1, 0x2222, 975001));

  // 16개를 넘기면 가장 오래된 것부터 잊는다.
  dedup_init(&d, W);
  for (int s = 0; s < 16; s++) CHECK(!dedup_seen(&d, 0, (uint8_t)s, 7, 10));
  for (int s = 0; s < 16; s++) CHECK(dedup_seen(&d, 0, (uint8_t)s, 7, 20));  // 전부 기억
  CHECK(!dedup_seen(&d, 0, 16, 7, 30));            // 17번째 → seq 0이 밀려남
  CHECK(!dedup_seen(&d, 0, 0, 7, 40));             // 잊었으므로 새 것(그리고 seq 1이 밀려남)
  CHECK(!dedup_seen(&d, 0, 1, 7, 50));
  CHECK(dedup_seen(&d, 0, 15, 7, 60));
  // seq 255 → 0 순환, millis 오버플로 근처
  dedup_init(&d, W);
  CHECK(!dedup_seen(&d, 0, 255, 9, 0xFFFFF000u));
  CHECK(!dedup_seen(&d, 0, 0, 9, 0xFFFFF100u));
  CHECK(dedup_seen(&d, 0, 255, 9, 0x00001000u));   // 경과 8,192ms → 중복
}

// 보고 프레임 하나 만들기. tag는 seq에 넣어 구분.
static int make_report(uint8_t type, uint8_t tag, uint8_t *out) {
  frame_msg_t m;
  memset(&m, 0, sizeof m);
  m.type = type; m.seq = tag; m.src = 1; m.dst = FRAME_DST_LEADER;
  if (type == MSG_ACK) { m.u.ref.ref_type = REF_TYPE_BUTTON; m.u.ref.ref_id = tag; }
  return frame_encode(&m, out, 32);
}

static void test_report_queue() {
  static report_queue_t q;
  uint8_t f[32];
  int n;

  report_queue_init(&q);
  CHECK(report_queue_peek(&q) == 0);
  n = make_report(MSG_OK_READY, 0, f);
  CHECK_EQ(report_queue_push(&q, f, 3), RQ_INVALID);  // 헤더보다 짧음
  CHECK_EQ(report_queue_push(&q, f, 25), RQ_INVALID); // 최대 길이 초과

  // 일반 보고와 긴급 보고를 섞어 32개 채우기: 짝수 tag = 일반(OK_READY), 홀수 tag = 긴급(CONTACT)
  for (int i = 0; i < 32; i++) {
    n = make_report((i & 1) ? MSG_CONTACT : MSG_OK_READY, (uint8_t)i, f);
    CHECK_EQ(report_queue_push(&q, f, (size_t)n), RQ_PUSHED);
  }
  CHECK_EQ(report_queue_count(&q), 32);

  // 33번째(긴급) → 가장 오래된 일반(tag 0)이 버려짐
  n = make_report(MSG_CASUALTY_SELF, 100, f);
  CHECK_EQ(report_queue_push(&q, f, (size_t)n), RQ_PUSHED_DROPPED_OLD);
  CHECK_EQ(report_queue_count(&q), 32);
  CHECK_EQ(report_queue_peek(&q)->data[2], 1);  // 맨 앞은 이제 tag 1(긴급)

  // 일반 보고(ACK)를 더 넣으면 오래된 일반부터 계속 밀려남
  for (int i = 0; i < 15; i++) {
    n = make_report(MSG_ACK, (uint8_t)(200 + i), f);
    CHECK_EQ(report_queue_push(&q, f, (size_t)n), RQ_PUSHED_DROPPED_OLD);
  }
  // 이 시점: 긴급 17개(tag 1,3,...,31 + 100), 일반 15개(ACK 200~214). 원래 일반(OK_READY)은 모두 밀려남.
  int urgent = 0, normal = 0;
  for (int i = 0; i < q.count; i++) {
    if (frame_type_is_urgent(q.items[i].data[1])) urgent++; else normal++;
  }
  CHECK_EQ(urgent, 17);
  CHECK_EQ(normal, 15);

  // 긴급만 계속 넣으면 일반이 모두 밀려나고 긴급은 보존
  for (int i = 0; i < 15; i++) {
    n = make_report(MSG_HAZARD, (uint8_t)(150 + i), f);
    CHECK_EQ(report_queue_push(&q, f, (size_t)n), RQ_PUSHED_DROPPED_OLD);
  }
  urgent = 0;
  for (int i = 0; i < q.count; i++) if (frame_type_is_urgent(q.items[i].data[1])) urgent++;
  CHECK_EQ(urgent, 32);

  // 전부 긴급일 때: 일반은 거부, 긴급은 가장 오래된 긴급을 밀어냄
  n = make_report(MSG_OK_READY, 250, f);
  CHECK_EQ(report_queue_push(&q, f, (size_t)n), RQ_REJECTED);
  CHECK_EQ(report_queue_count(&q), 32);
  CHECK_EQ(report_queue_peek(&q)->data[2], 1);
  n = make_report(MSG_CONTACT, 251, f);
  CHECK_EQ(report_queue_push(&q, f, (size_t)n), RQ_PUSHED_DROPPED_OLD);
  CHECK_EQ(report_queue_peek(&q)->data[2], 3);  // tag 1이 밀려남

  // 꺼내는 순서 = 오래된 순서, 마지막은 방금 넣은 251
  uint8_t last = 0;
  int popped = 0;
  while (report_queue_peek(&q)) {
    last = report_queue_peek(&q)->data[2];
    report_queue_pop(&q);
    popped++;
  }
  CHECK_EQ(popped, 32);
  CHECK_EQ(last, 251);
  report_queue_pop(&q);  // 빈 큐 pop은 무시
  CHECK_EQ(report_queue_count(&q), 0);

  // 저장된 바이트가 원본과 같은지
  n = make_report(MSG_CONTACT, 9, f);
  report_queue_push(&q, f, (size_t)n);
  CHECK_EQ(report_queue_peek(&q)->len, n);
  CHECK(memcmp(report_queue_peek(&q)->data, f, (size_t)n) == 0);
}

int main() {
  test_dedup();
  test_report_queue();
  return test_summary("test_queue");
}
