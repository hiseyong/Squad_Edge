// BLE 무선 (CLAUDE.md §6.6): Bluefruit Peripheral + NUS(BLEUart).
// EMCON(프로토콜 §2, §3.2):
//   모드 0(침묵): 연결 끊기 → 광고 중지(자동 재광고 끔) → 수동 스캔(scan request 없음). Company ID 0xFFFF
//                 Manufacturer Data 안의 프레임(ver 1, src 0, CMD_BUTTON/EMCON_SET)만 RX 링 버퍼로 → 연결 RX와 같은 경로.
//   모드 1/2    : 연결 가능 광고(끊겨 있을 때), 송신 출력 = 인자(광고·현재 연결 모두에 적용). 광고·스캔은 radio_loop가 유지.
//
// 스레드 주의: Bluefruit 콜백은 BLE 태스크에서 돈다. 콜백은 정적 링 버퍼/플래그만 갱신하고,
// 실제 처리는 loop 태스크에서 radio_pop_rx()/radio_take_events()로 가져간다.
#pragma once
#include <stdbool.h>
#include <stdint.h>

// radio_take_events() 비트
#define RADIO_EV_CONNECTED     0x01
#define RADIO_EV_DISCONNECTED  0x02
#define RADIO_EV_NOTIFY_ON     0x04  // 분대장이 TX Notify(CCCD)를 켬 → 송신 가능

bool radio_begin(uint8_t soldier_id, uint8_t mode, int8_t tx_power);  // Bluefruit 초기화 + 모드 적용
bool radio_set_mode(uint8_t mode, int8_t tx_power);  // 실패(스캔/광고 시작 오류)면 false
bool radio_set_tx_power(int8_t dbm);        // 광고·현재 연결에 바로 적용(지원값 아니면 false)
bool radio_scanning();
void radio_loop(uint32_t now_ms);           // 광고·스캔 상태 유지(연결/끊김/모드/비콘 변화 반영). 매 루프 호출

// 단계 R(F11, 프로토콜 v1.1 예정): 비콘(0x20) 송신·다른 병사 비콘 수동 스캔.
//   비콘 = 분대장과 연결된 EMCON 2에서만(광고 세트 1개를 연결 가능 광고와 나눠 씀), 연결 안 됐으면 연결 가능 광고 우선.
//   스캔 = EMCON 1/2(수신만, 전파 방출 없음). 침묵 모드에서는 분대장 방송 스캔(비콘·병사 방송도 같이 받음).
void radio_set_beacon(const uint8_t *frame, uint8_t len);  // 프레임(헤더 6 + heading 2). 바뀌면 광고 재시작
void radio_set_ranging(bool beacon, bool scan);
void radio_scan_pause(bool pause);          // 음성 수신 중 등 연결 처리량이 필요할 때 비콘 스캔 잠시 중지
bool radio_beaconing();
bool radio_pop_beacon(uint8_t *src, int8_t *rssi, uint16_t *heading);  // src 0 = 분대장 비콘(단계 9 보충)

// 단계 9 대안 경로(v1.1 예정): 보고를 광고로 직접 방송(Manufacturer Data 0xFFFF + 프레임, 최대 24B).
//   PEER_ADV_INTERVAL_MS 간격으로 duration_ms 동안. 광고 세트를 비콘·연결 가능 광고보다 우선해 쓴다(그동안 그 둘은 멈춤).
//   EMCON 0이면 false. 정책(EMCON 2에서만)은 호출 쪽(reporter)이 정한다.
//   수신: 다른 병사의 방송(type 0x14, src 1~5)은 스캔 중인 모든 모드에서 RX 링으로(연결 RX와 같은 경로).
bool radio_broadcast(const uint8_t *frame, uint8_t len, uint16_t duration_ms);
bool radio_broadcasting();
uint32_t radio_peer_adv_frames();           // 받아들인 다른 병사 직접 방송 수(반복 제외)
uint32_t radio_adv_frames();                // 침묵 모드에서 받아들인 광고 프레임 수(중복 포함)
bool radio_connected();
bool radio_can_send();                      // 연결 + Notify 켜짐
uint16_t radio_mtu();                       // 연결 없으면 0
uint8_t radio_take_events();                // 쌓인 이벤트를 읽고 지움
uint8_t radio_last_disconnect_reason();

// 프레임 하나 = notify 하나(프로토콜 §3.1). len이 MTU-3을 넘으면 쪼개지 않고 false.
bool radio_send(const uint8_t *frame, uint16_t len);

// RX로 받은 write 하나(= 프레임 하나)를 꺼낸다. 없으면 false. buf는 FRAME_MAX_LEN 이상.
bool radio_pop_rx(uint8_t *buf, uint16_t *len);
uint32_t radio_rx_dropped();                // 큐 가득/너무 긴 write로 버린 수
