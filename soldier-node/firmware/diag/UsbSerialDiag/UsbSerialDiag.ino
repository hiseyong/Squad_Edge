// USB Serial(TinyUSB CDC) 진단 스케치 — 본 펌웨어와 분리.
// 확인: (1) NUCODE 코어에서 Serial이 컴파일·링크되는지 (2) 맥에 /dev/cu.usbmodem*가 보이는지
//       (3) 호스트가 포트를 열지 않아도 loop가 멈추지 않는지 (4) 데이터가 오는지.
// 동작: LED1 0.5초 점멸(loop가 돈다는 표시). 0.5초마다 "diag n=<번호> up=<ms> dtr=<0|1> afw=<쓰기 여유>" 한 줄 송신.
//       쓰기 여유가 줄보다 작거나 호스트가 안 열었으면 쓰지 않고 건너뜀(블로킹 없음). 받은 바이트는 그대로 되돌려 보냄.
#include <Arduino.h>
#include <Adafruit_TinyUSB.h>  // Serial(SerialTinyUSB) 구현이 이 라이브러리에 있다. 포함하지 않으면 링크 오류

static const uint8_t LED_ON = LOW, LED_OFF = HIGH;  // 이 보드 LED는 active-low
static uint32_t t_led = 0, t_tx = 0, n = 0, skipped = 0;
static bool led = false;

void setup() {
  const uint8_t leds[4] = {PIN_LED1, PIN_LED2, PIN_LED3, PIN_LED4};
  for (uint8_t i = 0; i < 4; i++) {
    pinMode(leds[i], OUTPUT);
    digitalWrite(leds[i], LED_OFF);
  }
  Serial.begin(115200);  // while(!Serial) 대기 없음
}

void loop() {
  uint32_t now = millis();
  if (now - t_led >= 500) {
    t_led = now;
    led = !led;
    digitalWrite(PIN_LED1, led ? LED_ON : LED_OFF);
  }
  if (now - t_tx >= 500) {
    t_tx = now;
    char line[96];
    int len = snprintf(line, sizeof line, "diag n=%lu up=%lu dtr=%d afw=%d skipped=%lu\r\n", (unsigned long)n,
                       (unsigned long)now, Serial.dtr() ? 1 : 0, Serial.availableForWrite(), (unsigned long)skipped);
    if (Serial.dtr() && Serial.availableForWrite() >= len) {
      Serial.write((const uint8_t *)line, len);
      n++;
    } else {
      skipped++;
    }
    digitalWrite(PIN_LED2, Serial.dtr() ? LED_ON : LED_OFF);  // LED2 = 호스트가 포트를 열었음
  }
  while (Serial.available() > 0) {
    int c = Serial.read();
    if (Serial.availableForWrite() > 0) Serial.write((uint8_t)c);
  }
}
