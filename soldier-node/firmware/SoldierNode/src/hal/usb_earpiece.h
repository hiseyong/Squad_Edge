// audio sink 구현: USB 시리얼(TinyUSB CDC)로 맥의 이어폰 단말(tools/earpiece.py)에 재생 이벤트·음성 전달.
// 프레임 형식은 core/earpiece_frame.h. 절대 블로킹하지 않는다:
//   - 호스트가 포트를 열지 않았으면(DTR 없음) 쓰지 않고 버린다(dropped).
//   - CDC 송신 버퍼 여유가 프레임 길이보다 작으면 이번 루프에는 쓰지 않는다(문장은 작은 큐, 음성은 이어서 전송).
#pragma once
#include <stdbool.h>
#include <stdint.h>

void usb_earpiece_begin(uint8_t soldier_id);
void usb_earpiece_loop(uint32_t now_ms);
void usb_earpiece_play_clips(const char *clips, uint8_t prio, bool feedback);
bool usb_earpiece_play_voice(const uint8_t *adpcm, uint32_t nbytes, uint32_t nsamples, int16_t predictor,
                             uint8_t step_index, uint8_t voice_id, uint8_t prio, uint16_t crc16);
void usb_earpiece_stop_voice();
bool usb_earpiece_voice_busy();
void usb_earpiece_log(const char *text, uint8_t len);  // 공간 없으면 버림
uint32_t usb_earpiece_bytes_out();
uint32_t usb_earpiece_dropped();
