// 미확인 명령 타이머 (CLAUDE.md §6.3: 미확인 동안 LED2 점멸, 30초 경과 시 빠른 점멸).
// Arduino 비의존 → 호스트 테스트. 경과 시간은 부호 있는 차이로 계산한다:
// 시작 시각이 루프 앞에서 읽은 now보다 몇 ms 늦을 수 있어서(단계 4 버그: 부호 없는 뺄셈이 감겨 즉시 발동).
#pragma once
#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
  bool active;
  bool fast;
  uint32_t since;
  uint32_t escalate_ms;
} unack_t;

void unack_init(unack_t *u, uint32_t escalate_ms);
void unack_start(unack_t *u, uint32_t now);  // 새 명령: 시작 시각·빠른 점멸 상태 초기화
void unack_clear(unack_t *u);                // ACK/수행 불가 송신
// 빠른 점멸로 바뀌는 순간 한 번만 true.
bool unack_poll(unack_t *u, uint32_t now);

#ifdef __cplusplus
}
#endif
