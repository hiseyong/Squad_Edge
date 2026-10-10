// frame 단위 테스트: 프로토콜 §11.1 hex 일치(양방향), 폐기 조건, dst_mask(병사 1/2), 전체 타입 왕복.
#include <string.h>

#include "frame.h"
#include "geo.h"
#include "test_util.h"

static bool bytes_eq(const uint8_t *a, const uint8_t *b, size_t n) { return memcmp(a, b, n) == 0; }

static void test_spec_11_1() {
  uint8_t out[FRAME_MAX_LEN];
  frame_msg_t m, d;

  // 1) 전원 엄폐, 방위 270, 거리 없음, 긴급
  static const uint8_t ex1[] = {0x01, 0x10, 0x05, 0x00, 0x1F, 0x06, 0x02, 0x0E, 0x01, 0xFF, 0x00, 0x01};
  memset(&m, 0, sizeof m);
  m.type = MSG_CMD_BUTTON; m.seq = 5; m.src = 0; m.dst = 0x1F;
  m.u.cmd_button.cmd_code = CMD_TAKE_COVER; m.u.cmd_button.azimuth = 270;
  m.u.cmd_button.dist_band = FRAME_NO_DIST; m.u.cmd_button.extra = 0; m.u.cmd_button.priority = 1;
  CHECK_EQ(frame_encode(&m, out, sizeof out), sizeof ex1);
  CHECK(bytes_eq(out, ex1, sizeof ex1));
  CHECK_EQ(frame_decode(ex1, sizeof ex1, &d), FRAME_OK);
  CHECK_EQ(d.type, MSG_CMD_BUTTON); CHECK_EQ(d.seq, 5); CHECK_EQ(d.src, 0); CHECK_EQ(d.dst, 0x1F);
  CHECK_EQ(d.u.cmd_button.cmd_code, 2); CHECK_EQ(d.u.cmd_button.azimuth, 270);
  CHECK_EQ(d.u.cmd_button.dist_band, 0xFF); CHECK_EQ(d.u.cmd_button.extra, 0); CHECK_EQ(d.u.cmd_button.priority, 1);

  // 2) 병사 1에게 적 위치 알림, 방위 45, 원거리, 3명
  static const uint8_t ex2[] = {0x01, 0x10, 0x06, 0x00, 0x01, 0x06, 0x09, 0x2D, 0x00, 0x02, 0x03, 0x00};
  memset(&m, 0, sizeof m);
  m.type = MSG_CMD_BUTTON; m.seq = 6; m.src = 0; m.dst = 0x01;
  m.u.cmd_button.cmd_code = CMD_ENEMY_INFO; m.u.cmd_button.azimuth = 45;
  m.u.cmd_button.dist_band = 2; m.u.cmd_button.extra = 3; m.u.cmd_button.priority = 0;
  CHECK_EQ(frame_encode(&m, out, sizeof out), sizeof ex2);
  CHECK(bytes_eq(out, ex2, sizeof ex2));
  CHECK_EQ(frame_decode(ex2, sizeof ex2, &d), FRAME_OK);
  CHECK_EQ(d.u.cmd_button.cmd_code, 9); CHECK_EQ(d.u.cmd_button.azimuth, 45);
  CHECK_EQ(d.u.cmd_button.dist_band, 2); CHECK_EQ(d.u.cmd_button.extra, 3); CHECK_EQ(d.u.cmd_button.priority, 0);

  // 3) 상태 보고 요청
  static const uint8_t ex3[] = {0x01, 0x1F, 0x07, 0x00, 0x01, 0x00};
  memset(&m, 0, sizeof m);
  m.type = MSG_REQ_STATS; m.seq = 7; m.src = 0; m.dst = 0x01;
  CHECK_EQ(frame_encode(&m, out, sizeof out), sizeof ex3);
  CHECK(bytes_eq(out, ex3, sizeof ex3));
  CHECK_EQ(frame_decode(ex3, sizeof ex3, &d), FRAME_OK);
  CHECK_EQ(d.type, MSG_REQ_STATS); CHECK_EQ(d.seq, 7);

  // 4) 병사 1 CONTACT: seq 7, 적 3, 시계 2, 원거리, 내 방위 0 → azimuth 60 (프로토콜 v1.0.1 정정)
  static const uint8_t ex4[] = {0x01, 0x01, 0x07, 0x01, 0x80, 0x07, 0x3C, 0x00, 0x02, 0x02, 0x03, 0x00, 0x00};
  memset(&m, 0, sizeof m);
  m.type = MSG_CONTACT; m.seq = 7; m.src = 1; m.dst = FRAME_DST_LEADER;
  m.u.contact.azimuth = geo_azimuth_from(2, 0); m.u.contact.clock = 2; m.u.contact.dist_band = 2;
  m.u.contact.count = 3; m.u.contact.heading = 0;
  CHECK_EQ(m.u.contact.azimuth, 60);  // §5.1 공식 = (0 + (2-12)*30) mod 360
  CHECK_EQ(frame_encode(&m, out, sizeof out), sizeof ex4);
  CHECK(bytes_eq(out, ex4, sizeof ex4));
  CHECK_EQ(frame_decode(ex4, sizeof ex4, &d), FRAME_OK);
  CHECK_EQ(d.src, 1); CHECK_EQ(d.dst, 0x80);
  CHECK_EQ(d.u.contact.azimuth, 60); CHECK_EQ(d.u.contact.clock, 2); CHECK_EQ(d.u.contact.dist_band, 2);
  CHECK_EQ(d.u.contact.count, 3); CHECK_EQ(d.u.contact.heading, 0);
}

static void test_reject() {
  frame_msg_t d;
  static const uint8_t good[] = {0x01, 0x10, 0x05, 0x00, 0x1F, 0x06, 0x02, 0x0E, 0x01, 0xFF, 0x00, 0x01};
  uint8_t buf[32];

  memcpy(buf, good, sizeof good); buf[0] = 0x02;
  CHECK_EQ(frame_decode(buf, sizeof good, &d), FRAME_ERR_VER);
  CHECK_EQ(frame_decode(good, sizeof good - 1, &d), FRAME_ERR_LEN);       // 실제가 len보다 짧음
  memcpy(buf, good, sizeof good); buf[sizeof good] = 0;
  CHECK_EQ(frame_decode(buf, sizeof good + 1, &d), FRAME_ERR_LEN);        // 실제가 len보다 김
  CHECK_EQ(frame_decode(good, 5, &d), FRAME_ERR_SHORT);
  static const uint8_t short_cmd[] = {0x01, 0x10, 0x05, 0x00, 0x1F, 0x05, 0x02, 0x0E, 0x01, 0xFF, 0x00};
  CHECK_EQ(frame_decode(short_cmd, sizeof short_cmd, &d), FRAME_ERR_PAYLOAD);  // CMD_BUTTON은 6바이트
  static const uint8_t unk[] = {0x01, 0x55, 0x00, 0x00, 0x1F, 0x00};
  CHECK_EQ(frame_decode(unk, sizeof unk, &d), FRAME_ERR_TYPE);
  static const uint8_t bad_mode[] = {0x01, 0x16, 0x00, 0x00, 0x1F, 0x01, 0x03};
  CHECK_EQ(frame_decode(bad_mode, sizeof bad_mode, &d), FRAME_ERR_PAYLOAD);
  static const uint8_t bad_pos[] = {0x01, 0x15, 0x00, 0x00, 0x1F, 0x03, 0x01, 0x00, 0x00};  // n=1인데 2바이트
  CHECK_EQ(frame_decode(bad_pos, sizeof bad_pos, &d), FRAME_ERR_PAYLOAD);
}

static void test_dst_mask() {
  frame_msg_t d;
  static const uint8_t all[] = {0x01, 0x10, 0x05, 0x00, 0x1F, 0x06, 0x02, 0x0E, 0x01, 0xFF, 0x00, 0x01};
  static const uint8_t to1[] = {0x01, 0x10, 0x06, 0x00, 0x01, 0x06, 0x09, 0x2D, 0x00, 0x02, 0x03, 0x00};
  static const uint8_t to2[] = {0x01, 0x10, 0x08, 0x00, 0x02, 0x06, 0x01, 0xFF, 0xFF, 0xFF, 0x00, 0x00};
  static const uint8_t to12[] = {0x01, 0x10, 0x09, 0x00, 0x03, 0x06, 0x01, 0xFF, 0xFF, 0xFF, 0x00, 0x00};
  static const uint8_t to_leader[] = {0x01, 0x05, 0x01, 0x01, 0x80, 0x00};

  CHECK_EQ(frame_dst_bit(1), 0x01); CHECK_EQ(frame_dst_bit(2), 0x02); CHECK_EQ(frame_dst_bit(5), 0x10);
  CHECK_EQ(frame_dst_bit(0), 0); CHECK_EQ(frame_dst_bit(6), 0);

  CHECK_EQ(frame_receive(all, sizeof all, 1, &d), FRAME_OK);
  CHECK_EQ(frame_receive(all, sizeof all, 2, &d), FRAME_OK);
  CHECK_EQ(frame_receive(to1, sizeof to1, 1, &d), FRAME_OK);
  CHECK_EQ(frame_receive(to1, sizeof to1, 2, &d), FRAME_ERR_DST);
  CHECK_EQ(frame_receive(to2, sizeof to2, 1, &d), FRAME_ERR_DST);
  CHECK_EQ(frame_receive(to2, sizeof to2, 2, &d), FRAME_OK);
  CHECK_EQ(frame_receive(to12, sizeof to12, 1, &d), FRAME_OK);
  CHECK_EQ(frame_receive(to12, sizeof to12, 2, &d), FRAME_OK);
  CHECK_EQ(frame_receive(to_leader, sizeof to_leader, 1, &d), FRAME_ERR_DST);
  CHECK_EQ(frame_receive(to_leader, sizeof to_leader, 2, &d), FRAME_ERR_DST);
  // 형식 오류가 dst 검사보다 먼저
  static const uint8_t bad_ver_to1[] = {0x02, 0x10, 0x06, 0x00, 0x01, 0x06, 0x09, 0x2D, 0x00, 0x02, 0x03, 0x00};
  CHECK_EQ(frame_receive(bad_ver_to1, sizeof bad_ver_to1, 1, &d), FRAME_ERR_VER);
}

// encode → decode → 다시 encode 했을 때 같은 바이트인지(전체 타입).
static void roundtrip(const frame_msg_t *m, int expect_len) {
  uint8_t a[FRAME_MAX_LEN], b[FRAME_MAX_LEN];
  frame_msg_t d;
  int na = frame_encode(m, a, sizeof a);
  CHECK_EQ(na, expect_len);
  if (na <= 0) return;
  CHECK_EQ(frame_decode(a, (size_t)na, &d), FRAME_OK);
  CHECK_EQ(d.type, m->type); CHECK_EQ(d.seq, m->seq); CHECK_EQ(d.src, m->src); CHECK_EQ(d.dst, m->dst);
  int nb = frame_encode(&d, b, sizeof b);
  CHECK_EQ(nb, na);
  CHECK(nb == na && bytes_eq(a, b, (size_t)na));
}

static void test_all_types() {
  frame_msg_t m;
#define NEW(t) memset(&m, 0, sizeof m); m.type = (t); m.seq = 0x42; m.src = 1; m.dst = FRAME_DST_LEADER
  NEW(MSG_CONTACT); m.u.contact.azimuth = 300; m.u.contact.clock = 10; m.u.contact.count = 5; roundtrip(&m, 6 + 7);
  NEW(MSG_SUSPICIOUS); m.u.dir_report.azimuth = 0xFFFF; m.u.dir_report.heading = 0xFFFF; roundtrip(&m, 6 + 5);
  NEW(MSG_HAZARD); m.u.dir_report.azimuth = 15; m.u.dir_report.clock = 1; roundtrip(&m, 6 + 5);
  NEW(MSG_CASUALTY_FOUND); m.u.casualty_found.azimuth = 90; m.u.casualty_found.dist_band = 0; roundtrip(&m, 6 + 6);
  NEW(MSG_OK_READY); roundtrip(&m, 6);
  NEW(MSG_WEAPON_AMMO); roundtrip(&m, 6);
  NEW(MSG_CASUALTY_SELF); m.u.heading.heading = 359; roundtrip(&m, 6 + 2);
  NEW(MSG_ACK); m.u.ref.ref_type = REF_TYPE_BUTTON; m.u.ref.ref_id = 5; roundtrip(&m, 6 + 2);
  NEW(MSG_CANNOT_COMPLY); m.u.ref.ref_type = REF_TYPE_VOICE; m.u.ref.ref_id = 9; roundtrip(&m, 6 + 2);
  NEW(MSG_VOICE_RESULT); m.u.voice_result.voice_id = 9; m.u.voice_result.status = VOICE_STATUS_CRC; roundtrip(&m, 6 + 2);
  NEW(MSG_EMCON_STATE); m.u.mode.mode = 1; roundtrip(&m, 6 + 1);
  NEW(MSG_HEARTBEAT); m.u.heartbeat.battery_mv = 3900; roundtrip(&m, 6 + 6);
  NEW(MSG_STATS); m.u.stats.tx_frames[2] = 300; m.u.stats.tx_bytes[2] = 70000; roundtrip(&m, 6 + 18);
  NEW(MSG_RANGING); m.u.ranging.n = 2;
  m.u.ranging.e[0].peer_id = 2; m.u.ranging.e[0].rssi_avg = -67; m.u.ranging.e[0].samples = 10;
  m.u.ranging.e[1].peer_id = 3; m.u.ranging.e[1].rssi_avg = -90; m.u.ranging.e[1].samples = 4;
  roundtrip(&m, 6 + 7);
  NEW(MSG_LOG); m.u.log.text = "mtu=247"; m.u.log.len = 7; roundtrip(&m, 6 + 7);

  NEW(MSG_CMD_BUTTON); m.src = 0; m.dst = 0x03; m.u.cmd_button.cmd_code = CMD_RALLY; m.u.cmd_button.azimuth = 0xFFFF;
  roundtrip(&m, 6 + 6);
  NEW(MSG_VOICE_BEGIN); m.src = 0; m.dst = 0x03;
  m.u.voice_begin.voice_id = 1; m.u.voice_begin.codec = VOICE_CODEC_IMA_ADPCM; m.u.voice_begin.sample_rate = 8000;
  m.u.voice_begin.total_samples = 16000; m.u.voice_begin.total_chunks = 35; m.u.voice_begin.predictor = -12;
  m.u.voice_begin.step_index = 7;
  roundtrip(&m, 6 + 14);
  static uint8_t chunk[235];
  for (int i = 0; i < 235; i++) chunk[i] = (uint8_t)i;
  NEW(MSG_VOICE_CHUNK); m.src = 0; m.dst = 0x03;
  m.u.voice_chunk.voice_id = 1; m.u.voice_chunk.chunk_idx = 300; m.u.voice_chunk.data = chunk; m.u.voice_chunk.data_len = 235;
  roundtrip(&m, 244);  // MTU 247 - 3 = 244 (프로토콜 §7.3 N=235)
  NEW(MSG_VOICE_END); m.src = 0; m.dst = 0x03; m.u.voice_end.voice_id = 1; m.u.voice_end.crc16 = 0xBEEF; roundtrip(&m, 6 + 3);
  NEW(MSG_POS_TABLE); m.src = 0; m.dst = 0x1F; m.u.pos_table.n = 3;
  m.u.pos_table.e[1].id = 1; m.u.pos_table.e[1].x = -100; m.u.pos_table.e[1].y = -100;
  m.u.pos_table.e[2].id = 2; m.u.pos_table.e[2].x = 100; m.u.pos_table.e[2].y = -100; m.u.pos_table.e[2].heading = 90;
  roundtrip(&m, 6 + 1 + 21);
  NEW(MSG_EMCON_SET); m.src = 0; m.dst = 0x1F; m.u.mode.mode = 0; roundtrip(&m, 6 + 1);
  NEW(MSG_RPT_ACK); m.src = 0; m.dst = 0x01; m.u.rpt_ack.ref_seq = 7; roundtrip(&m, 6 + 1);
  NEW(MSG_REQ_STATS); m.src = 0; m.dst = 0x01; roundtrip(&m, 6);
  NEW(MSG_BEACON); m.dst = FRAME_DST_ALL; m.u.heading.heading = 270; roundtrip(&m, 6 + 2);

  // PEER_REPORT: 원 보고(CONTACT) payload를 넣고 다시 해석
  uint8_t orig[16];
  frame_msg_t c;
  memset(&c, 0, sizeof c);
  c.type = MSG_CONTACT; c.u.contact.azimuth = 45; c.u.contact.clock = 2; c.u.contact.dist_band = 2; c.u.contact.count = 3;
  int olen = frame_encode_payload(&c, orig, sizeof orig);
  CHECK_EQ(olen, 7);
  NEW(MSG_PEER_REPORT); m.src = 0; m.dst = 0x02;
  m.u.peer_report.reporter_id = 1; m.u.peer_report.rx = -100; m.u.peer_report.ry = 0;
  m.u.peer_report.orig_type = MSG_CONTACT; m.u.peer_report.orig_payload = orig; m.u.peer_report.orig_len = (uint8_t)olen;
  roundtrip(&m, 6 + 6 + 7);
  uint8_t buf[64];
  frame_msg_t d, inner;
  int n = frame_encode(&m, buf, sizeof buf);
  CHECK_EQ(frame_decode(buf, (size_t)n, &d), FRAME_OK);
  CHECK_EQ(d.u.peer_report.rx, -100);
  CHECK_EQ(frame_decode_payload(d.u.peer_report.orig_type, d.u.peer_report.orig_payload, d.u.peer_report.orig_len, &inner),
           FRAME_OK);
  CHECK_EQ(inner.u.contact.azimuth, 45); CHECK_EQ(inner.u.contact.count, 3);

  // 출력 버퍼 부족, LOG 길이 초과
  NEW(MSG_CONTACT);
  CHECK_EQ(frame_encode(&m, buf, 8), FRAME_ERR_CAP);
  NEW(MSG_LOG); m.u.log.text = (const char *)chunk; m.u.log.len = 101;
  CHECK_EQ(frame_encode(&m, buf, sizeof buf), FRAME_ERR_PAYLOAD);
#undef NEW

  CHECK(frame_type_is_urgent(MSG_CONTACT) && frame_type_is_urgent(MSG_HAZARD) && frame_type_is_urgent(MSG_CASUALTY_FOUND) &&
        frame_type_is_urgent(MSG_WEAPON_AMMO) && frame_type_is_urgent(MSG_CASUALTY_SELF));
  CHECK(!frame_type_is_urgent(MSG_SUSPICIOUS) && !frame_type_is_urgent(MSG_OK_READY) && !frame_type_is_urgent(MSG_ACK));
}

int main() {
  test_spec_11_1();
  test_reject();
  test_dst_mask();
  test_all_types();
  return test_summary("test_frame");
}
