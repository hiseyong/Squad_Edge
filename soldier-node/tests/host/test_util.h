// 호스트 테스트용 최소 검사 매크로.
#pragma once
#include <stdio.h>

static int g_checks = 0;
static int g_fails = 0;

#define CHECK(cond)                                                     \
  do {                                                                  \
    g_checks++;                                                         \
    if (!(cond)) {                                                      \
      g_fails++;                                                        \
      printf("  FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);          \
    }                                                                   \
  } while (0)

#define CHECK_EQ(a, b)                                                  \
  do {                                                                  \
    long long _a = (long long)(a), _b = (long long)(b);                 \
    g_checks++;                                                         \
    if (_a != _b) {                                                     \
      g_fails++;                                                        \
      printf("  FAIL %s:%d: %s == %s (%lld != %lld)\n", __FILE__,       \
             __LINE__, #a, #b, _a, _b);                                 \
    }                                                                   \
  } while (0)

static inline int test_summary(const char *name) {
  printf("  %s: %d checks, %d failed\n", name, g_checks, g_fails);
  return g_fails ? 1 : 0;
}
