// 병사 단말 설정: 핀, ID, 타이밍 상수.
// "TODO_CONFIRM" 표시는 사용자 확인이 필요한 값이다(추측 금지, CLAUDE.md §2-6).
// 이 파일은 Arduino 의존(A1 등)이므로 src/core/에서 include하지 않는다.
#pragma once

// ============================================================
// TODO_CONFIRM 목록 (확인되면 해당 항목의 표시를 지우고 PROGRESS.md에 기록)
//   1. PIN_AUDIO_PWM        P1.10: 코어 소프트웨어상 충돌 없음 확인. 회로도(보드 배선) 확인은 남음
//   4. HEADING_SENSOR_MODEL 9축 센서 미확보 → 단계 8에서 지정 (지금은 HEADING_MODE_FIXED)
//   5. MAG_DECLINATION_DEG  지자기 편차(서울 약 -8도, 사용자 확인 후 설정)
// 확인 완료: PIN_JOY_SW = P0.28, EMCON_BOOT_MODE = 2, LED_ON_LEVEL = LOW, BUTTON_PRESSED_LEVEL = LOW,
//           JOY_SWAP_XY/INVERT/ROTATE, JOY_SW_PRESSED_LEVEL = LOW (조이스틱 진단 2026-10-10)
//           (모두 사용자 확인 2026-10-10, LED/버튼은 firmware/diag/LedButtonDiag로 진단)
// ============================================================

// ---------- 병사 ID / BLE ----------
// 빌드 시 지정 가능: --build-property "compiler.cpp.extra_flags=-DSOLDIER_ID=2"
#ifndef SOLDIER_ID
#define SOLDIER_ID        1          // 1~5
#endif
#define ADV_NAME_PREFIX   "SQ1-S"    // 광고 이름 = "SQ1-S" + SOLDIER_ID (프로토콜 §3.1)
#define DEBUG_LOG         1          // 1이면 0x7F LOG 프레임 송신 (CLAUDE.md §6.6)

#if SOLDIER_ID < 1 || SOLDIER_ID > 5
#error "SOLDIER_ID must be 1..5"
#endif

// ---------- 핀 배정 (CLAUDE.md §3.2) ----------
// 버튼/LED 핀은 보드 variant 정의 사용: PIN_BUTTON1~4(11,12,24,25), PIN_LED1~4(13~16)
// 사용 금지: A0/P0.02(VBAT ADC, 보드 가이드 회로도), A7/P0.31(코어 variant의 PIN_VBAT), UART 33/34, SPI 44~47, QSPI 17/19~23, NFC 9/10
#define PIN_JOY_X         A1         // P0.03 / Arduino 3 (권장값)
#define PIN_JOY_Y         A2         // P0.04 / Arduino 4 (권장값)
#define PIN_JOY_SW        28         // P0.28, INPUT_PULLUP (사용자 확인)
#define PIN_AUDIO_PWM     42         // P1.10 — TODO_CONFIRM(회로도). PWM 인스턴스는 NRF_PWM3 사용 예정
#define PIN_I2C_SDA       26         // P0.26 (Qwiic, 고정)
#define PIN_I2C_SCL       27         // P0.27 (Qwiic, 고정)

#define BUTTON_PRESSED_LEVEL LOW     // 확인됨: INPUT_PULLUP, 누르면 LOW
#define JOY_SW_PRESSED_LEVEL LOW     // 확인됨(2026-10-10 진단): INPUT_PULLUP, 누르면 LOW

// 조이스틱 연결 여부. 현재 하드웨어(2026-10-10): 조이스틱은 보드 1(ID 1)에만 연결, 보드 2(ID 2)는 없음.
// 0이면 아날로그/SW 핀을 전혀 읽지 않는다(떠 있는 핀 오동작 방지) → 방향 없는 보고(clock 0)와 버튼만 동작.
// 빌드 플래그로 덮어쓰기: -DHAS_JOYSTICK=0/1
#ifndef HAS_JOYSTICK
#if SOLDIER_ID == 1
#define HAS_JOYSTICK      1
#else
#define HAS_JOYSTICK      0
#endif
#endif

// 조이스틱 진단: 1이면 0.5초마다 원시 X/Y/SW를 LOG로 송신(장착 방향 확인용). 확인 후 0으로.
#ifndef JOY_DIAG_LOG
#define JOY_DIAG_LOG      0      // 2026-10-10 장착 방향 확인 완료 → 끔
#endif
#define JOY_DIAG_INTERVAL_MS      500
// LED 켜짐 레벨. 이 보드는 active-low(LOW = 켜짐)로 확인됨.
// 주의: 코어 variant의 LED_STATE_ON(=1)은 이 보드와 반대이므로 사용하지 않는다.
#define LED_ON_LEVEL      LOW
#define LED_OFF_LEVEL     HIGH

// ---------- 입력 판정 (CLAUDE.md §6.1) ----------
#define DEBOUNCE_MS               20
#define PRESS_SHORT_MAX_MS        600    // 짧게 < 600
#define PRESS_LONG_MIN_MS         1000   // 길게 >= 1000
#define PRESS_SELF_CASUALTY_MS    2000   // 버튼4 본인 부상 >= 2000
#define DOUBLE_PRESS_GAP_MS       400    // 첫 해제 후 400ms 안에 재입력
#define BTN1_MULTI_TIMEOUT_MS     1200   // 버튼1 연타 확정
#define BTN1_MULTI_MAX_COUNT      5      // 5 이상 = 다수
#define CALIB_COMBO_HOLD_MS       3000   // 버튼1+버튼4 → 방위 보정
#define MODE_COMBO_HOLD_MS        2000   // 버튼1+버튼2 → EMCON 모드 순환(조이스틱 없는 ID 2용, 모든 보드)
#define TXPWR_COMBO_HOLD_MS       2000   // 버튼3+버튼4 → 최소 모드 송신 출력 순환(거리 시험)

// ---------- 조이스틱 ----------
#define JOY_CENTER_CAL_MS         200    // 부팅 시 중앙값 평균
// 방향별 최대 거리 기본값 = 중앙값에서 ADC 끝(0 / 1023)까지 거리(중앙이 치우쳐 +/− 거리가 다름). 더 멀리 가면 학습으로 늘어남.
#define JOY_ADC_MAX               1023   // 10bit
#define JOY_DEADZONE_PCT          35     // < 35%: 방향 없음
#define JOY_FAR_PCT               75     // >= 75%: 원거리(2), 그 사이 근거리(0)
// 장착 방향 (2026-10-10 ID 1 보드 진단, 사용자가 정한 장착 기준):
//   중앙 x≈537 y≈534 / 앞(총구) x=1021 / 오른쪽 y=1022 / 뒤 x=0 / 왼쪽 y=0
//   → 원시 +X = 앞(12시), 원시 +Y = 오른쪽(3시). 회전이 아니라 거울 관계라 X/Y 교환만 하면 된다.
// 적용 순서: 교환 → 반전 → 회전. (교환 후 기준: 앞 성분 → 12시, 오른쪽 성분 → 3시)
#define JOY_SWAP_XY               1      // 확인됨
#define JOY_INVERT_X              0      // 확인됨
#define JOY_INVERT_Y              0      // 확인됨
#define JOY_ROTATE_DEG            0      // 확인됨
#define JOY_SAMPLE_INTERVAL_MS    10     // ADC 읽기 주기 (10bit, 기준 VDD)

// ---------- 보고 / EMCON (CLAUDE.md §6.2) ----------
#define EMCON_BOOT_MODE           2      // 0/1/2, 부팅 시 모드 (사용자 확인: 2)
#define RPT_ACK_TIMEOUT_MS        3000
#define RPT_MAX_RETRIES           3
#define REPORT_QUEUE_MAX          32
#define EMCON1_BATCH_INTERVAL_MS  30000
#define RPT_PENDING_MAX           8      // RPT_ACK 대기 중인 긴급 보고 수
#define TX_RETRY_BACKOFF_MS       50     // 큐 송신 실패 후 다시 시도까지

// ---------- EMCON 무선 (CLAUDE.md §6.6, 프로토콜 §2, §3.2) ----------
// 송신 출력(dBm). nRF52840 + Bluefruit 지원값: -40 -20 -16 -12 -8 -4 0 2 3 4 5 6 7 8
#define EMCON1_TX_POWER_DBM       (-20)  // 최소 모드 기본값 — TODO_CONFIRM: 10m 거리 시험으로 연결 유지되는 최저값 확정
#define EMCON2_TX_POWER_DBM       0      // 정상 모드
// 거리 시험용 순환 목록(버튼3+버튼4 2초마다 다음 값, 재부팅하면 EMCON1_TX_POWER_DBM으로 돌아감)
#define EMCON1_TX_POWER_LIST      {-40, -20, -12, -8, -4}
// 침묵 모드 수동 스캔: 간격·창(0.625ms 단위). 160/160 = 100ms 연속 스캔(분대장 광고 100ms × 3초를 최대한 받기)
#define SILENT_SCAN_INTERVAL      160
#define SILENT_SCAN_WINDOW        160
#define SILENT_COMPANY_ID         0xFFFF // 프로토콜 §3.2 Manufacturer Specific Data Company ID
#define LED_SILENT_PERIOD_MS      3000   // LED1: 침묵 스캔 = 3초마다 짧게(프로토콜 §9.4)
#define LED_SILENT_ON_MS          100

// ---------- 병사 간 RSSI 거리 측정 (F11, 단계 R, 프로토콜 v1.1 예정 0x20 BEACON / 0x0E RANGING) ----------
#ifndef RANGING_ENABLE
#define RANGING_ENABLE            1      // 1이면 EMCON 2에서 비콘 송신 + EMCON 1/2에서 다른 병사 비콘 수신·RANGING 보고
#endif
#define BEACON_INTERVAL_MS        500    // 비콘 광고 간격(20ms~10.24s)
#define RANGING_SCAN_INTERVAL     320    // 비콘 스캔 간격(0.625ms 단위) = 200ms
#define RANGING_SCAN_WINDOW       160    // 창 100ms(50%) — 나머지는 연결 이벤트에
#define RANGING_REPORT_MS         10000  // RANGING(0x0E) 보고 주기
#define RANGING_STALE_MS          30000  // 이 시간 동안 못 들은 피어는 RANGING에서 뺌
#define HEADING_BEACON_CHECK_MS   1000   // 비콘 heading 갱신 확인 주기

// ---------- 분대 위치·다른 병사 보고 (단계 9, CLAUDE.md §6.7) ----------
#ifndef PEER_ADV_ENABLE
#define PEER_ADV_ENABLE           1      // 1이면 대안 경로: EMCON 2에서 CONTACT/SUSPICIOUS/HAZARD/CASUALTY_FOUND를 광고로도 방송,
#endif                                   //   다른 병사의 방송을 스캔으로 받아 내 기준으로 재생(프로토콜 v1.1 예정)
#define PEER_ADV_MS               3000   // 보고 직접 방송 시간(분대장 침묵 방송과 같은 3초)
#define PEER_ADV_INTERVAL_MS      100    // 방송 광고 간격
#define PEER_ADV_REPEAT_MS        5000   // 받는 쪽: 같은 (src, seq) 방송 반복을 이 시간 동안 버림(스캔 콜백)
#define PEER_DEDUP_WINDOW_MS      10000  // 분대장 중계(PEER_REPORT)와 직접 방송이 같은 보고면 한 번만 재생

// ---------- BLE 송신 ----------
#define BLE_HVN_QUEUE_SIZE        8      // Notify 송신 큐(Bluefruit BANDWIDTH_MAX 기본 3 → 8)

// ---------- LED (프로토콜 §9.4) ----------
#define LED_TX_PULSE_MS           100    // LED3: 송신 순간
#define LED_MODE1_PERIOD_MS       1000   // LED4: EMCON 1 느린 점멸
#define LED_MODE1_ON_MS           500

// ---------- 명령 수신 (CLAUDE.md §6.3) ----------
#define DEDUP_HISTORY             16
#define DEDUP_WINDOW_MS           60000  // 같은 (src, seq, 내용)이 이 시간 안에 다시 오면 중복(분대장 재전송 15초 × 여유)
#define DUP_REPLAY_HOLDOFF_MS     5000   // 중복 명령은 마지막 재생 후 이 시간이 지나야 다시 재생(침묵 모드 광고 100ms×3초 반복 대비)
#define UNACK_BLINK_MS            500
#define UNACK_FAST_BLINK_MS       150
#define UNACK_ESCALATE_MS         30000

// ---------- 음성 수신 (CLAUDE.md §6.9) ----------
#define VOICE_BUF_BYTES           40000  // 정적 할당
#define VOICE_RX_TIMEOUT_MS       3000   // 마지막 BEGIN/청크 후 무활동 시간(프로토콜 v1.0.2 제안)

// ---------- 오디오 출력 통로 (audio sink) ----------
// 문장 조각 재생·로컬 피드백·수신 음성 재생은 모두 hal/audio_sink를 거친다(commands/voice_rx/phrases는 통로를 모름).
//   USB_EARPIECE: USB 시리얼로 맥(이어폰 단말, tools/earpiece.py)에 재생 이벤트·검증된 ADPCM 전달 (지금)
//   PWM         : CLAUDE.md §6.4 PWM 이어폰 출력 — 설계만, 하드웨어 미제작 → 빈 구현
//   NONE        : 출력 없음
#define AUDIO_SINK_NONE           0
#define AUDIO_SINK_USB_EARPIECE   1
#define AUDIO_SINK_PWM            2
#ifndef AUDIO_SINK
#define AUDIO_SINK                AUDIO_SINK_USB_EARPIECE
#endif
#define EARPIECE_HELLO_MS         2000   // 호스트가 포트를 열었을 때만 HELLO 송신

// ---------- 음성 수신 추가 (CLAUDE.md §6.9, 프로토콜 §7.4) ----------
#define VOICE_MAX_CHUNKS          4096   // 수신 비트맵 크기(MTU 23일 때 청크 11B × 3637개까지)

// ---------- 오디오 출력 (CLAUDE.md §6.4, §6.5) ----------
#define AUDIO_SAMPLE_RATE         8000
#define AUDIO_PWM_COUNTERTOP      250    // 16MHz / 250 = 64kHz
#define AUDIO_PWM_REFRESH         7      // 샘플당 8주기 → 8kHz
#define AUDIO_PWM_SILENCE         125
#define AUDIO_BLOCK_SAMPLES       256
#define AUDIO_GAIN                0.3f   // 0.0~1.0
#define PHRASE_GAP_MS             80

// ---------- 방위 (CLAUDE.md §6.8) ----------
#define HEADING_MODE_NONE         0      // 항상 0xFFFF
#define HEADING_MODE_FIXED        1      // 항상 HEADING_FIXED_DEG
#define HEADING_MODE_SENSOR       2      // 9축 센서 (단계 8)
#ifndef HEADING_MODE
#define HEADING_MODE              HEADING_MODE_FIXED
#endif
#ifndef HEADING_FIXED_DEG
#define HEADING_FIXED_DEG         0      // 0~359, 0 = 북쪽
#endif
#if HEADING_FIXED_DEG < 0 || HEADING_FIXED_DEG > 359
#error "HEADING_FIXED_DEG must be 0..359"
#endif
#define HEADING_SENSOR_MODEL      0      // 0 = 미정. 9축 센서 확보 후 단계 8에서 지정
#define HEADING_NONE              0xFFFF
#define MAG_CALIB_COLLECT_MS      20000
#define MAG_DECLINATION_DEG       (-8.0f) // TODO_CONFIRM
