// 프로토콜 프레임 인코드/디코드 (프로토콜 §4~§7). 모든 다바이트 정수는 리틀엔디언.
// Arduino 비의존, C 호환, 동적 할당 없음.
// 가변 길이 데이터(VOICE_CHUNK 데이터, PEER_REPORT 원 보고, LOG 문자열)는
// 디코드 시 입력 버퍼를 가리키는 포인터로 돌려준다(복사 없음) → 입력 버퍼가 살아 있는 동안만 유효.
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

// ---------- 헤더 (프로토콜 §4) ----------
#define FRAME_VER             0x01
#define FRAME_HDR_LEN         6
#define FRAME_MAX_PAYLOAD     238   // MTU 247 - ATT 3 - 헤더 6
#define FRAME_MAX_LEN         (FRAME_HDR_LEN + FRAME_MAX_PAYLOAD)

#define FRAME_ID_LEADER       0
#define FRAME_DST_LEADER      0x80
#define FRAME_DST_ALL_SOLDIERS 0x1F
#define FRAME_DST_ALL         0xFF

#define FRAME_NO_AZIMUTH      0xFFFF
#define FRAME_NO_HEADING      0xFFFF
#define FRAME_NO_DIST         0xFF

// ---------- msg_type (프로토콜 §5) ----------
// 병사 → 분대장 (§5.1)
#define MSG_CONTACT           0x01  // 긴급
#define MSG_SUSPICIOUS        0x02
#define MSG_HAZARD            0x03  // 긴급
#define MSG_CASUALTY_FOUND    0x04  // 긴급
#define MSG_OK_READY          0x05
#define MSG_WEAPON_AMMO       0x06  // 긴급
#define MSG_CASUALTY_SELF     0x07  // 긴급
#define MSG_ACK               0x08
#define MSG_CANNOT_COMPLY     0x09
#define MSG_VOICE_RESULT      0x0A
#define MSG_EMCON_STATE       0x0B
#define MSG_HEARTBEAT         0x0C  // v2 예약: 형식만 정의, 송신 금지(CLAUDE.md F10)
#define MSG_STATS             0x0D
#define MSG_RANGING           0x0E  // v1.1 예정 (F11): 형식만 정의, 프로토콜 v1 문서에 없음
// 분대장 → 병사 (§5.2)
#define MSG_CMD_BUTTON        0x10
#define MSG_VOICE_BEGIN       0x11
#define MSG_VOICE_CHUNK       0x12
#define MSG_VOICE_END         0x13
#define MSG_PEER_REPORT       0x14
#define MSG_POS_TABLE         0x15
#define MSG_EMCON_SET         0x16
#define MSG_RPT_ACK           0x17
#define MSG_REQ_STATS         0x1F
#define MSG_BEACON            0x20  // v1.1 예정 (F11): 광고 Manufacturer Data(0xFFFF) 안의 프레임. 형식만 정의
#define MSG_LOG               0x7F  // 디버그 전용(CLAUDE.md §6.6), DEBUG_LOG 빌드에서만 송신

// ref_type (§5.1)
#define REF_TYPE_BUTTON       0x10
#define REF_TYPE_VOICE        0x11

// VOICE_RESULT.status
#define VOICE_STATUS_OK       0
#define VOICE_STATUS_CRC      1
#define VOICE_STATUS_TIMEOUT  2
#define VOICE_STATUS_NOMEM    3

#define VOICE_CODEC_IMA_ADPCM 0x01

// cmd_code (§6.2)
#define CMD_HALT              0x01
#define CMD_TAKE_COVER        0x02
#define CMD_ADVANCE           0x03
#define CMD_WITHDRAW          0x04
#define CMD_RALLY             0x05
#define CMD_OPEN_FIRE         0x06
#define CMD_CEASE_FIRE        0x07
#define CMD_OBSERVE           0x08
#define CMD_ENEMY_INFO        0x09
#define CMD_REPORT_STATUS     0x0A
#define CMD_SILENCE           0x0B
#define CMD_HOLD              0x0C
#define CMD_CANCEL            0x0F

// ---------- 결과 코드 ----------
#define FRAME_OK              0
#define FRAME_ERR_SHORT       (-1)  // 헤더보다 짧음
#define FRAME_ERR_VER         (-2)  // ver != 0x01
#define FRAME_ERR_LEN         (-3)  // len 필드와 실제 길이 불일치
#define FRAME_ERR_TYPE        (-4)  // 알 수 없는 msg_type
#define FRAME_ERR_PAYLOAD     (-5)  // msg_type에 맞지 않는 payload 길이/값
#define FRAME_ERR_DST         (-6)  // dst_mask에 내 비트 없음
#define FRAME_ERR_CAP         (-7)  // 출력 버퍼 부족

// ---------- payload 구조체 ----------
typedef struct { uint16_t azimuth; uint8_t clock; uint8_t dist_band; uint8_t count; uint16_t heading; } msg_contact_t;
typedef struct { uint16_t azimuth; uint8_t clock; uint16_t heading; } msg_dir_report_t;          // SUSPICIOUS, HAZARD
typedef struct { uint16_t azimuth; uint8_t clock; uint8_t dist_band; uint16_t heading; } msg_casualty_found_t;
typedef struct { uint16_t heading; } msg_heading_t;                                              // CASUALTY_SELF, BEACON
typedef struct { uint8_t ref_type; uint8_t ref_id; } msg_ref_t;                                  // ACK, CANNOT_COMPLY
typedef struct { uint8_t voice_id; uint8_t status; } msg_voice_result_t;
typedef struct { uint8_t mode; } msg_mode_t;                                                     // EMCON_STATE, EMCON_SET
typedef struct { uint16_t heading; uint16_t battery_mv; uint8_t heart_rate; uint8_t motion; } msg_heartbeat_t;
typedef struct { uint16_t tx_frames[3]; uint32_t tx_bytes[3]; } msg_stats_t;                     // [0]=EMCON0 [1]=EMCON1 [2]=EMCON2

#define RANGING_MAX_PEERS 8
typedef struct { uint8_t peer_id; int8_t rssi_avg; uint8_t samples; } ranging_entry_t;
typedef struct { uint8_t n; ranging_entry_t e[RANGING_MAX_PEERS]; } msg_ranging_t;

typedef struct { uint8_t cmd_code; uint16_t azimuth; uint8_t dist_band; uint8_t extra; uint8_t priority; } msg_cmd_button_t;
typedef struct {
  uint8_t voice_id; uint8_t codec; uint16_t sample_rate; uint32_t total_samples;
  uint16_t total_chunks; int16_t predictor; uint8_t step_index; uint8_t priority;
} msg_voice_begin_t;
typedef struct { uint8_t voice_id; uint16_t chunk_idx; const uint8_t *data; uint8_t data_len; } msg_voice_chunk_t;
typedef struct { uint8_t voice_id; uint16_t crc16; } msg_voice_end_t;
typedef struct {
  uint8_t reporter_id; int16_t rx; int16_t ry;       // 보고자 위치(분대장 원점, 0.1m)
  uint8_t orig_type; const uint8_t *orig_payload; uint8_t orig_len;
} msg_peer_report_t;

#define POS_TABLE_MAX 8
typedef struct { uint8_t id; int16_t x; int16_t y; uint16_t heading; } pos_entry_t;
typedef struct { uint8_t n; pos_entry_t e[POS_TABLE_MAX]; } msg_pos_table_t;

typedef struct { uint8_t ref_seq; } msg_rpt_ack_t;

#define LOG_MAX_TEXT 100
typedef struct { const char *text; uint8_t len; } msg_log_t;   // NUL 종료 아님

typedef struct {
  uint8_t type;
  uint8_t seq;
  uint8_t src;
  uint8_t dst;
  union {
    msg_contact_t contact;
    msg_dir_report_t dir_report;
    msg_casualty_found_t casualty_found;
    msg_heading_t heading;
    msg_ref_t ref;
    msg_voice_result_t voice_result;
    msg_mode_t mode;
    msg_heartbeat_t heartbeat;
    msg_stats_t stats;
    msg_ranging_t ranging;
    msg_cmd_button_t cmd_button;
    msg_voice_begin_t voice_begin;
    msg_voice_chunk_t voice_chunk;
    msg_voice_end_t voice_end;
    msg_peer_report_t peer_report;
    msg_pos_table_t pos_table;
    msg_rpt_ack_t rpt_ack;
    msg_log_t log;
  } u;
} frame_msg_t;

// 전체 프레임 인코드. 반환: 쓴 바이트 수(>0) 또는 FRAME_ERR_*.
int frame_encode(const frame_msg_t *m, uint8_t *out, size_t cap);

// payload만 인코드(PEER_REPORT의 원 보고 만들 때 사용). 반환: 바이트 수 또는 FRAME_ERR_*.
int frame_encode_payload(const frame_msg_t *m, uint8_t *out, size_t cap);

// 전체 프레임 디코드(ver, len, msg_type별 payload 길이 검사). dst_mask는 검사하지 않는다.
int frame_decode(const uint8_t *buf, size_t n, frame_msg_t *out);

// payload만 디코드(PEER_REPORT의 원 보고 해석용). out->type은 type으로 채운다.
int frame_decode_payload(uint8_t type, const uint8_t *p, size_t len, frame_msg_t *out);

// 병사 수신 경로: frame_decode + dst_mask에 bit(soldier_id-1) 포함 여부.
int frame_receive(const uint8_t *buf, size_t n, uint8_t soldier_id, frame_msg_t *out);

// 병사 ID n(1~5) → bit(n-1). 범위 밖이면 0.
uint8_t frame_dst_bit(uint8_t soldier_id);
bool frame_dst_has_soldier(uint8_t dst_mask, uint8_t soldier_id);

// 긴급 보고(0x01, 0x03, 0x04, 0x06, 0x07) 여부 (프로토콜 §8.2).
bool frame_type_is_urgent(uint8_t type);

#ifdef __cplusplus
}
#endif
