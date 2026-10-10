// USB 이어폰 링크 구현. CLAUDE.md §2-9 USB Serial 금지 규칙의 예외(AUDIO_SINK=USB_EARPIECE 용도 한정).
#include "usb_earpiece.h"

#include <Adafruit_TinyUSB.h>  // Serial(SerialTinyUSB) 구현. 포함하지 않으면 링크 오류(진단 스케치로 확인)
#include <Arduino.h>
#include <string.h>

#include "../../config.h"
#include "../core/earpiece_frame.h"

#define TEXT_SLOTS 4
#define TEXT_MAX 64

typedef struct {
  uint8_t prio;
  uint8_t kind;
  uint8_t len;
  char text[TEXT_MAX];
} text_item_t;

static uint8_t s_id = 0;
static text_item_t s_text[TEXT_SLOTS];
static uint8_t s_text_head = 0, s_text_count = 0;
static uint32_t s_bytes_out = 0, s_dropped = 0;
static uint32_t s_hello_t = 0;

// 음성 전송 상태
static const uint8_t *s_v_buf = 0;
static uint32_t s_v_nbytes = 0, s_v_nsamples = 0, s_v_off = 0;
static int16_t s_v_pred = 0;
static uint8_t s_v_idx = 0, s_v_id = 0, s_v_prio = 0;
static uint16_t s_v_crc = 0;
static uint8_t s_v_state = 0;  // 0 없음, 1 BEGIN 보낼 차례, 2 DATA, 3 END 보낼 차례

static bool host_open() { return Serial.dtr(); }

// 프레임 하나를 공간이 있을 때만 쓴다.
static bool send_frame(uint8_t type, const uint8_t *payload, uint16_t len) {
  uint8_t buf[EP_MAX_PAYLOAD + EP_OVERHEAD];
  size_t n = ep_encode(type, payload, len, buf, sizeof buf);
  if (n == 0 || !host_open() || Serial.availableForWrite() < (int)n) return false;
  Serial.write(buf, n);
  s_bytes_out += n;
  return true;
}

void usb_earpiece_begin(uint8_t soldier_id) {
  s_id = soldier_id;
  Serial.begin(115200);  // 호스트를 기다리지 않는다(while(!Serial) 없음)
}

void usb_earpiece_play_clips(const char *clips, uint8_t prio, bool feedback) {
  if (!host_open()) {
    s_dropped++;
    return;
  }
  if (s_text_count == TEXT_SLOTS) {  // 가득 차면 가장 오래된 것을 버림
    s_text_head = (uint8_t)((s_text_head + 1) % TEXT_SLOTS);
    s_text_count--;
    s_dropped++;
  }
  text_item_t *t = &s_text[(s_text_head + s_text_count) % TEXT_SLOTS];
  size_t len = strlen(clips);
  if (len > TEXT_MAX) len = TEXT_MAX;
  memcpy(t->text, clips, len);
  t->len = (uint8_t)len;
  t->prio = prio;
  t->kind = feedback ? 1 : 0;
  s_text_count++;
  usb_earpiece_loop(millis());  // 가능하면 바로 보냄
}

bool usb_earpiece_play_voice(const uint8_t *adpcm, uint32_t nbytes, uint32_t nsamples, int16_t predictor,
                             uint8_t step_index, uint8_t voice_id, uint8_t prio, uint16_t crc16) {
  if (!host_open()) {
    s_dropped++;
    return false;
  }
  if (s_v_state != 0) usb_earpiece_stop_voice();
  s_v_buf = adpcm;
  s_v_nbytes = nbytes;
  s_v_nsamples = nsamples;
  s_v_pred = predictor;
  s_v_idx = step_index;
  s_v_id = voice_id;
  s_v_prio = prio;
  s_v_crc = crc16;
  s_v_off = 0;
  s_v_state = 1;
  return true;
}

void usb_earpiece_stop_voice() {
  if (s_v_state == 0) return;
  uint8_t p[1] = {s_v_id};
  send_frame(EP_VOICE_STOP, p, 1);  // 못 보내도 상태는 정리(호스트는 END가 없으면 버림)
  s_v_state = 0;
  s_v_buf = 0;
}

bool usb_earpiece_voice_busy() { return s_v_state != 0; }

void usb_earpiece_log(const char *text, uint8_t len) { send_frame(EP_LOG, (const uint8_t *)text, len); }
uint32_t usb_earpiece_bytes_out() { return s_bytes_out; }
uint32_t usb_earpiece_dropped() { return s_dropped; }

static void put32(uint8_t *p, uint32_t v) {
  p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); p[2] = (uint8_t)(v >> 16); p[3] = (uint8_t)(v >> 24);
}

static void pump_voice() {
  if (s_v_state != 0 && !host_open()) {  // 호스트가 닫힘 → 중단
    s_v_state = 0;
    s_v_buf = 0;
    s_dropped++;
    return;
  }
  for (;;) {
    if (s_v_state == 1) {
      uint8_t p[13];
      p[0] = s_v_id; p[1] = s_v_prio; p[2] = (uint8_t)s_v_pred; p[3] = (uint8_t)((uint16_t)s_v_pred >> 8);
      p[4] = s_v_idx; put32(p + 5, s_v_nsamples); put32(p + 9, s_v_nbytes);
      if (!send_frame(EP_VOICE_BEGIN, p, sizeof p)) return;
      s_v_state = 2;
    } else if (s_v_state == 2) {
      if (s_v_off >= s_v_nbytes) { s_v_state = 3; continue; }
      uint32_t n = s_v_nbytes - s_v_off;
      if (n > EP_VOICE_DATA_MAX) n = EP_VOICE_DATA_MAX;
      uint8_t p[5 + EP_VOICE_DATA_MAX];
      p[0] = s_v_id; put32(p + 1, s_v_off);
      memcpy(p + 5, s_v_buf + s_v_off, n);
      if (!send_frame(EP_VOICE_DATA, p, (uint16_t)(5 + n))) return;
      s_v_off += n;
    } else if (s_v_state == 3) {
      uint8_t p[3] = {s_v_id, (uint8_t)s_v_crc, (uint8_t)(s_v_crc >> 8)};
      if (!send_frame(EP_VOICE_END, p, 3)) return;
      s_v_state = 0;
      s_v_buf = 0;
      return;
    } else {
      return;
    }
  }
}

void usb_earpiece_loop(uint32_t now) {
  if (!host_open()) {  // 호스트가 없으면 쌓인 문장도 버림(재생 시점이 지난 것)
    s_dropped += s_text_count;
    s_text_count = 0;
  }
  // 문장(짧음)을 음성보다 먼저
  while (s_text_count) {
    text_item_t *t = &s_text[s_text_head];
    uint8_t p[2 + TEXT_MAX];
    p[0] = t->prio;
    p[1] = t->kind;
    memcpy(p + 2, t->text, t->len);
    if (!send_frame(EP_PLAY, p, (uint16_t)(2 + t->len))) break;
    s_text_head = (uint8_t)((s_text_head + 1) % TEXT_SLOTS);
    s_text_count--;
  }
  pump_voice();
  if (host_open() && (int32_t)(now - s_hello_t) >= EARPIECE_HELLO_MS) {
    uint8_t p[2] = {s_id, 1};
    if (send_frame(EP_HELLO, p, 2)) s_hello_t = now;
  }
}
