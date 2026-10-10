// audio sink 디스패처: config.h의 AUDIO_SINK에 따라 구현 선택.
#include "audio_sink.h"

#include "../../config.h"

#if AUDIO_SINK == AUDIO_SINK_USB_EARPIECE
#include "usb_earpiece.h"
void audio_sink_begin(uint8_t id) { usb_earpiece_begin(id); }
void audio_sink_loop(uint32_t now) { usb_earpiece_loop(now); }
void audio_sink_play_clips(const char *clips, uint8_t prio, bool feedback) { usb_earpiece_play_clips(clips, prio, feedback); }
bool audio_sink_play_voice(const uint8_t *a, uint32_t nb, uint32_t ns, int16_t pred, uint8_t idx, uint8_t vid,
                           uint8_t prio, uint16_t crc) {
  return usb_earpiece_play_voice(a, nb, ns, pred, idx, vid, prio, crc);
}
void audio_sink_stop_voice() { usb_earpiece_stop_voice(); }
bool audio_sink_voice_busy() { return usb_earpiece_voice_busy(); }
uint32_t audio_sink_bytes_out() { return usb_earpiece_bytes_out(); }
uint32_t audio_sink_dropped() { return usb_earpiece_dropped(); }
const char *audio_sink_name() { return "usb_earpiece"; }
void audio_sink_debug_text(const char *t, uint8_t n) { usb_earpiece_log(t, n); }

#elif AUDIO_SINK == AUDIO_SINK_PWM
#include "audio_out.h"
void audio_sink_begin(uint8_t id) { (void)id; audio_out_begin(); }
void audio_sink_loop(uint32_t now) { audio_out_loop(now); }
void audio_sink_play_clips(const char *clips, uint8_t prio, bool feedback) { audio_out_play_clips(clips, prio, feedback); }
bool audio_sink_play_voice(const uint8_t *a, uint32_t nb, uint32_t ns, int16_t pred, uint8_t idx, uint8_t vid,
                           uint8_t prio, uint16_t crc) {
  (void)crc;
  return audio_out_play_voice(a, nb, ns, pred, idx, vid, prio);
}
void audio_sink_stop_voice() { audio_out_stop(); }
bool audio_sink_voice_busy() { return audio_out_busy(); }
uint32_t audio_sink_bytes_out() { return 0; }
uint32_t audio_sink_dropped() { return 0; }
const char *audio_sink_name() { return "pwm(stub)"; }
void audio_sink_debug_text(const char *t, uint8_t n) { (void)t; (void)n; }

#else
void audio_sink_begin(uint8_t id) { (void)id; }
void audio_sink_loop(uint32_t now) { (void)now; }
void audio_sink_play_clips(const char *c, uint8_t p, bool f) { (void)c; (void)p; (void)f; }
bool audio_sink_play_voice(const uint8_t *a, uint32_t nb, uint32_t ns, int16_t pred, uint8_t idx, uint8_t vid,
                           uint8_t prio, uint16_t crc) {
  (void)a; (void)nb; (void)ns; (void)pred; (void)idx; (void)vid; (void)prio; (void)crc;
  return false;
}
void audio_sink_stop_voice() {}
bool audio_sink_voice_busy() { return false; }
uint32_t audio_sink_bytes_out() { return 0; }
uint32_t audio_sink_dropped() { return 0; }
const char *audio_sink_name() { return "none"; }
void audio_sink_debug_text(const char *t, uint8_t n) { (void)t; (void)n; }
#endif
