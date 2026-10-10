// 음성 수신 구현.
#include "voice_rx.h"

#include <Arduino.h>
#include <string.h>

#include "../../config.h"
#include "../core/crc16.h"
#include "../hal/audio_sink.h"
#include "app.h"
#include "commands.h"
#include "reporter.h"

static uint8_t s_buf[VOICE_BUF_BYTES];
static uint8_t s_got[VOICE_MAX_CHUNKS / 8];

static bool s_rx = false;          // 수신 중
static msg_voice_begin_t s_hdr;    // 수신 중(또는 마지막 정상) 음성의 BEGIN
static uint32_t s_nbytes = 0;
static uint16_t s_chunk_n = 0;     // 청크 크기(마지막 제외), 0 = 아직 모름
static uint16_t s_got_count = 0;
static uint32_t s_begin_t = 0;
static uint32_t s_activity_t = 0;  // 마지막 BEGIN/청크 수신 시각(무활동 시간 제한 기준)
static bool s_last_ok = false;     // 버퍼에 정상 수신한 음성이 있음(다시 듣기용)
static uint16_t s_last_crc = 0;

static void result(uint8_t voice_id, uint8_t status) {
  reporter_send_voice_result(voice_id, status);
}

static uint8_t prio_of(const msg_voice_begin_t *h) { return h->priority ? AUDIO_PRIO_URGENT : AUDIO_PRIO_NORMAL; }

void voice_rx_begin() {}

static void start(const msg_voice_begin_t *v) {
  if (audio_sink_voice_busy()) audio_sink_stop_voice();  // 버퍼를 다시 쓰기 전에 전달 중단
  s_hdr = *v;
  s_nbytes = (v->total_samples + 1) / 2;
  s_chunk_n = 0;
  s_got_count = 0;
  memset(s_got, 0, sizeof s_got);
  s_rx = true;
  s_last_ok = false;
  s_begin_t = millis();
  s_activity_t = s_begin_t;
  app_log("voice begin id=%u samples=%lu chunks=%u prio=%u", v->voice_id, (unsigned long)v->total_samples,
          v->total_chunks, v->priority);
}

static void on_begin(const msg_voice_begin_t *v) {
  uint32_t nbytes = (v->total_samples + 1) / 2;
  if (v->codec != VOICE_CODEC_IMA_ADPCM || v->sample_rate != 8000 || v->total_samples == 0 || v->total_chunks == 0 ||
      nbytes > VOICE_BUF_BYTES || v->total_chunks > VOICE_MAX_CHUNKS || v->total_chunks > nbytes) {
    app_log("voice begin id=%u rejected (codec=%u rate=%u samples=%lu chunks=%u)", v->voice_id, v->codec,
            v->sample_rate, (unsigned long)v->total_samples, v->total_chunks);
    result(v->voice_id, VOICE_STATUS_NOMEM);
    return;
  }
  if (s_rx && v->voice_id != s_hdr.voice_id) {
    if (!v->priority) {
      app_log("voice begin id=%u ignored: receiving id=%u (prio 0)", v->voice_id, s_hdr.voice_id);
      return;
    }
    app_log("voice id=%u discarded by urgent id=%u", s_hdr.voice_id, v->voice_id);
  }
  start(v);
}

static void on_chunk(const msg_voice_chunk_t *c) {
  if (!s_rx || c->voice_id != s_hdr.voice_id) return;  // 모르는 음성의 청크는 무시
  uint16_t last = (uint16_t)(s_hdr.total_chunks - 1);
  if (c->chunk_idx > last || c->data_len == 0) return;
  // 청크 크기 N: 마지막이 아닌 청크는 모두 N, 마지막은 나머지
  if (s_chunk_n == 0) {
    if (c->chunk_idx < last) s_chunk_n = c->data_len;
    else if (last == 0) s_chunk_n = c->data_len;
    else if (s_nbytes > c->data_len) s_chunk_n = (uint16_t)((s_nbytes - c->data_len) / last);
  }
  if (s_chunk_n == 0) return;
  if (c->chunk_idx < last && c->data_len != s_chunk_n) return;  // 크기가 다르면 버림 → END에서 누락
  uint32_t off = (uint32_t)c->chunk_idx * s_chunk_n;
  if (off + c->data_len > s_nbytes) return;
  memcpy(s_buf + off, c->data, c->data_len);
  s_activity_t = millis();
  uint8_t bit = (uint8_t)(1u << (c->chunk_idx & 7));
  if (!(s_got[c->chunk_idx >> 3] & bit)) {
    s_got[c->chunk_idx >> 3] |= bit;
    s_got_count++;
  }
}

static void on_end(const msg_voice_end_t *e) {
  if (!s_rx || e->voice_id != s_hdr.voice_id) {
    app_log("voice end id=%u: no matching begin", e->voice_id);
    return;
  }
  s_rx = false;
  if (s_got_count != s_hdr.total_chunks) {
    app_log("voice end id=%u: missing %u/%u chunks", e->voice_id, s_hdr.total_chunks - s_got_count,
            s_hdr.total_chunks);
    result(e->voice_id, VOICE_STATUS_TIMEOUT);
    return;
  }
  uint16_t crc = crc16_ccitt_false(s_buf, s_nbytes);
  if (crc != e->crc16) {
    app_log("voice end id=%u: crc %04X != %04X", e->voice_id, crc, e->crc16);
    result(e->voice_id, VOICE_STATUS_CRC);
    return;
  }
  uint32_t ms = (uint32_t)(millis() - s_begin_t);
  app_log("voice ok id=%u bytes=%lu %lums", e->voice_id, (unsigned long)s_nbytes, (unsigned long)ms);
  result(e->voice_id, VOICE_STATUS_OK);
  s_last_ok = true;
  s_last_crc = crc;
  bool sent = audio_sink_play_voice(s_buf, s_nbytes, s_hdr.total_samples, s_hdr.predictor, s_hdr.step_index,
                                    s_hdr.voice_id, prio_of(&s_hdr), crc);
  if (!sent) app_log("voice id=%u: audio sink not ready (%s)", e->voice_id, audio_sink_name());
  commands_note_voice(e->voice_id);  // 마지막 명령 = (0x11, voice_id), LED2 미확인
}

void voice_rx_handle(const frame_msg_t *m) {
  if (m->type == MSG_VOICE_BEGIN) on_begin(&m->u.voice_begin);
  else if (m->type == MSG_VOICE_CHUNK) on_chunk(&m->u.voice_chunk);
  else if (m->type == MSG_VOICE_END) on_end(&m->u.voice_end);
}

void voice_rx_loop(uint32_t now) {
  if (s_rx && (int32_t)(now - s_activity_t) >= VOICE_RX_TIMEOUT_MS) {  // 부호 있는 경과(루프 앞 now 대비)
    s_rx = false;
    app_log("voice id=%u timeout: no data for 3s (%u/%u chunks, %lums since begin)", s_hdr.voice_id, s_got_count,
            s_hdr.total_chunks, (unsigned long)(now - s_begin_t));
    result(s_hdr.voice_id, VOICE_STATUS_TIMEOUT);
  }
}

bool voice_rx_busy() { return s_rx; }

void voice_rx_abort() {
  if (!s_rx) return;
  s_rx = false;
  app_log("voice id=%u aborted: entering silent mode (%u/%u chunks)", s_hdr.voice_id, s_got_count, s_hdr.total_chunks);
}

bool voice_rx_replay(uint8_t voice_id) {
  if (!s_last_ok || s_rx || s_hdr.voice_id != voice_id) return false;
  return audio_sink_play_voice(s_buf, s_nbytes, s_hdr.total_samples, s_hdr.predictor, s_hdr.step_index,
                               s_hdr.voice_id, prio_of(&s_hdr), s_last_crc);
}
