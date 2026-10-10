// 병사 단말 펌웨어. setup()/loop()만 두고 나머지는 src/에 둔다.
// USB Serial 사용 금지, 블로킹 delay 금지(CLAUDE.md §2).
#include "config.h"
#include "src/app/app.h"

void setup() {
  app_begin();
}

void loop() {
  app_loop();
}
