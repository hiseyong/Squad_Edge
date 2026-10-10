# 병사 단말(Soldier Node) 구현 요구사항

> 이 파일은 코딩 에이전트(Claude Code / Codex)가 작업 시작 시 항상 읽는 기준 문서다.
> 통신 형식의 유일한 기준은 `docs/squad_ble_protocol_v1.md`(이하 "프로토콜 문서")다. 이 파일과 프로토콜 문서가 충돌하면 **프로토콜 문서가 우선**이며, 충돌을 발견하면 작업을 멈추고 사용자에게 알린다.
> 보드 정보·핀맵·주의사항은 `docs/NU40_DK_Hackathon_AI_Knowledge_Guide_ko.md`(이하 "보드 가이드")를 따른다. 단, 보드 가이드 0-A의 "자동 설정 프롬프트"는 **실행하지 않는다**(환경은 이미 설치됨).

---

## 1. 프로젝트 개요

국방 해커톤(T4 Tactical Edge) 프로토타입. 분대원(병사)이 총기에 부착한 소형 단말로
- 소리 없이 조이스틱+버튼으로 적·징후·상태를 보고하고,
- 분대장의 명령(압축 음성 또는 버튼 코드)을 BLE로 받아 이어폰으로 듣고,
- 버튼으로 수신 확인을 보내며,
- 전파 방출 통제(EMCON) 모드에 따라 송신을 줄이거나 완전히 끈다.

이 저장소는 **병사 단말 펌웨어 + 노트북용 테스트 도구**만 다룬다. 분대장 단말(UNO Q)은 다른 팀원이 구현하며, 이 저장소의 `tools/mock_leader.py`가 개발 중 분대장 역할을 대신한다.

---

## 2. 작업 규칙 (항상 지킬 것)

1. **이 폴더 밖의 파일은 읽기만 하고 수정·삭제하지 않는다.** 이 폴더 안에서도 `docs/`의 기준 문서는 수정하지 않는다(진행 기록 `docs/PROGRESS.md` 제외).
2. 단계 작업이 끝날 때마다 `docs/PROGRESS.md`에 완료 항목, 남은 문제, 테스트 방법을 갱신한다.
3. 펌웨어 컴파일은 항상 `arduino-cli compile --fqbn nucode:nrf52:nu40dk firmware/SoldierNode` 실제 출력(Flash/RAM 사용량 포함)으로 확인한다. 경고 `USE_TINYUSB redefined`는 무시 가능.
4. **업로드 전에 반드시 사용자에게 묻는다.** 업로드 포트는 매번 `arduino-cli board list`로 새로 찾는다. 성공은 "Device programmed" 등 실제 메시지로 판단한다. 업로드 실패 시 보드 가이드 §10 복구 절차를 따른다.
5. LED, 소리, 진동 등 **물리적 동작은 추측하지 말고 사용자에게 확인을 요청**한다.
6. 모르는 하드웨어 정보(핀, 센서 모델, 버튼 극성 등)는 추측하지 말고 질문한다. `config.h`의 `TODO_CONFIRM` 항목이 그 목록이다.
7. 새 Arduino 라이브러리나 Python 패키지를 설치하기 전에 이름과 이유를 말하고 승인을 받는다.
8. 주 루프에서 블로킹 `delay()` 금지. `millis()` 기반 비차단 상태기계로 작성한다(음성 재생, BLE 수신이 끊기지 않게).
9. **USB `Serial` 사용 금지 — 단, `AUDIO_SINK=USB_EARPIECE`(이어폰 단말 전달, `hal/usb_earpiece`) 용도만 예외**(2026-10-10 진단으로 확인, 사용자 승인).
   - 예외 조건: `#include <Adafruit_TinyUSB.h>`(없으면 링크 오류), `while(!Serial)` 등 호스트 대기 금지, `availableForWrite()`가 프레임보다 작거나 DTR이 없으면 쓰지 않음(블로킹 금지), 프레임 형식은 `core/earpiece_frame.h`.
   - 그 외 용도(디버그 출력 등)는 여전히 금지. 디버그 로그는 BLE NUS의 로그 프레임(§6.6)이나 LED로 낸다.
   - 업로드 절차(RESET 두 번 → 부트로더 포트로 직접 전송)는 그대로.
10. 이식 가능한 로직(프레임, CRC, ADPCM, 방향 계산, 큐)은 Arduino API에 의존하지 않는 C++로 `src/core/`에 두고, 호스트(노트북)에서 단위 테스트한다.
11. 한 번에 한 단계만 진행한다. 사용자가 시킨 단계 범위를 넘어서 구현하지 않는다.

---

## 3. 하드웨어

### 3.1 구성
| 장비 | 비고 |
|---|---|
| NUCODE NU-40 DK (nRF52840, CHIP 안테나) | FQBN `nucode:nrf52:nu40dk`, **3.3V 로직** |
| 온보드 버튼 4개 | `PIN_BUTTON1~4` (Arduino 11, 12, 24, 25). 눌림 극성은 테스트로 확인 |
| 온보드 LED 4개 | `PIN_LED1~4` (Arduino 13~16), 켜짐 레벨 `LED_STATE_ON` |
| 조이스틱 모듈(아두이노 키트) | X, Y 아날로그 + SW 디지털. **VCC는 3.3V에 연결(5V 금지)** |
| 9축 방위 센서 | Qwiic I2C (SDA = P0.26 / Arduino 26, SCL = P0.27 / Arduino 27). 모델 미정 |
| 이어폰 | PWM 오디오 출력 + RC 필터 + 결합 콘덴서 (§6.4) |
| 배터리 | 대여품 |

### 3.2 핀 배정 (`firmware/SoldierNode/config.h`에 정의)
| 기능 | 핀 | 상태 |
|---|---|---|
| 조이스틱 X | A1 = P0.03 (Arduino 3) | 권장값 |
| 조이스틱 Y | A2 = P0.04 (Arduino 4) | 권장값 |
| 조이스틱 SW | P0.28 (Arduino 28), INPUT_PULLUP | TODO_CONFIRM |
| 오디오 PWM 출력 | P1.10 (Arduino 42) | TODO_CONFIRM (다른 기능과 충돌 없는지 회로도·보드 가이드 확인) |
| I2C | Arduino 26 (SDA), 27 (SCL) | 고정 |

- **A0(P0.02)은 배터리 전압 측정(VBAT ADC)에 연결되어 있으므로 사용 금지.**
- UART(33, 34), SPI(44~47), QSPI(17, 19~23), NFC(9, 10) 핀은 사용하지 않는다.

### 3.3 병사 ID
- `config.h`의 `SOLDIER_ID` (`#ifndef` 기본 1, 범위 1~5). 광고 이름 `SQ1-S{ID}`.
- 이번 시연은 병사 단말 **2대(ID 1, 2)**. 소스 수정 없이 빌드 시 ID를 지정한다:
  `--build-property "compiler.cpp.extra_flags=-DSOLDIER_ID=2"` (ID별 명령은 PROGRESS.md).

---

## 4. 폴더 구조

```
soldier-node/
├─ CLAUDE.md                     ← 이 파일 (Codex는 같은 내용을 AGENTS.md로)
├─ docs/
│  ├─ squad_ble_protocol_v1.md   ← 통신 기준 문서 (수정 금지)
│  ├─ NU40_DK_Hackathon_AI_Knowledge_Guide_ko.md  ← 보드 가이드 (수정 금지)
│  └─ PROGRESS.md                ← 에이전트가 단계마다 갱신
├─ firmware/
│  └─ SoldierNode/
│     ├─ SoldierNode.ino         ← setup()/loop()만, 나머지는 src/
│     ├─ config.h                ← 핀, ID, 타이밍 상수, TODO_CONFIRM 목록
│     └─ src/
│        ├─ core/                ← Arduino 비의존, 호스트 테스트 대상
│        │  ├─ frame.h/.cpp      ← 프로토콜 프레임 인코드/디코드
│        │  ├─ crc16.h/.cpp      ← CRC-16/CCITT-FALSE
│        │  ├─ adpcm.h/.cpp      ← IMA ADPCM 디코더(+테스트용 인코더)
│        │  ├─ geo.h/.cpp        ← 방위/시계 변환, 표적 위치 변환
│        │  ├─ dedup.h/.cpp      ← (src_id, seq) 중복 제거
│        │  └─ report_queue.h/.cpp ← EMCON용 보고 큐
│        ├─ hal/                 ← 하드웨어 접근
│        │  ├─ leds.h/.cpp
│        │  ├─ buttons.h/.cpp    ← 디바운스 + 짧게/길게/두 번/연타 판정
│        │  ├─ joystick.h/.cpp   ← 보정, 방향, 기울기 비율
│        │  ├─ heading.h/.cpp    ← 방위 센서 추상화(센서 없으면 0xFFFF)
│        │  ├─ audio_out.h/.cpp  ← PWM EasyDMA 오디오 출력
│        │  └─ radio.h/.cpp      ← Bluefruit: NUS 주변기기, 수동 스캔, 송신 출력
│        ├─ app/                 ← 동작 로직
│        │  ├─ app.h/.cpp        ← 최상위 상태기계, EMCON 모드
│        │  ├─ reporter.h/.cpp   ← 입력 → 보고 프레임, RPT_ACK 재전송
│        │  ├─ commands.h/.cpp   ← CMD_BUTTON 처리, 미확인 상태, ACK
│        │  ├─ voice_rx.h/.cpp   ← VOICE_BEGIN/CHUNK/END 수신·검증
│        │  ├─ phrases.h/.cpp    ← 문장 템플릿 → 음성 조각 시퀀스
│        │  ├─ squad_map.h/.cpp  ← POS_TABLE, PEER_REPORT 변환
│        │  └─ stats.h/.cpp      ← 모드별 송신 통계
│        └─ assets/
│           └─ audio_clips.h     ← tools/gen_clips.py가 생성 (직접 편집 금지)
├─ tests/
│  └─ host/                      ← g++로 빌드하는 core/ 단위 테스트
│     ├─ Makefile
│     ├─ test_frame.cpp
│     ├─ test_crc_adpcm.cpp
│     └─ test_geo.cpp
├─ tools/                        ← 노트북용 Python (3.10+)
│  ├─ requirements.txt           ← bleak 등
│  ├─ frame_codec.py             ← 프로토콜 프레임 Python 구현 (분대장 팀원과 공유 가능)
│  ├─ adpcm.py                   ← IMA ADPCM 인코더/디코더 (audioop 미사용)
│  ├─ mock_leader.py             ← 분대장 대역: BLE Central CLI
│  ├─ gen_clips.py               ← 녹음 WAV → 8kHz ADPCM → audio_clips.h
│  └─ test_vectors.py            ← 프로토콜 부록 A 테스트 벡터 생성
└─ assets/
   └─ clips_wav/                 ← 음성 조각 원본 WAV (파일명 = 조각 ID)
```

- Arduino 빌드는 스케치 폴더의 `src/` 하위를 재귀적으로 컴파일한다. `src/` 밖에 소스를 두지 않는다.

---

## 5. 기능 요구사항

기능 번호는 PROGRESS.md와 단계 프롬프트에서 그대로 사용한다.

| ID | 기능 | 우선순위 |
|---|---|---|
| F1 | BLE NUS 주변기기, 프로토콜 프레임 송수신 | 필수 |
| F2 | 조이스틱+버튼 입력 → 보고 송신(프로토콜 §9.1) | 필수 |
| F3 | 버튼 명령 수신 → 음성 조각 재생 + LED 미확인 → ACK/수행 불가 | 필수 |
| F4 | 음성 명령 수신(ADPCM) → 검증 → 재생 → VOICE_RESULT | 필수 |
| F5 | 오디오 출력(PWM) + 내장 음성 조각 + 로컬 피드백 음성 | 필수 |
| F6 | EMCON 0/1/2 (침묵 = 연결 끊고 수동 스캔으로 광고 명령 수신) | 필수 |
| F7 | 방위 센서 + 보정 → heading, azimuth 계산 | 높음 (센서 확보 후) |
| F8 | POS_TABLE / PEER_REPORT → 내 기준 방향 변환 재생 | 높음 |
| F9 | 송신 통계(STATS), 로그 프레임 | 보통 |
| F10 | HEARTBEAT(심박, 무동작) | 나중(v2), 이번엔 구현 금지 |
| F11 | 병사 간 RSSI 거리 측정 | 나중(단계 R), 지금 구현 금지 |

---

## 6. 상세 설계

### 6.1 입력 판정 (hal/buttons, hal/joystick)
- 디바운스 20ms.
- 판정 시간: 짧게 < 600ms, 길게 ≥ 1000ms, 본인 부상(버튼4)은 ≥ 2000ms, 두 번 = 첫 해제 후 400ms 안에 재입력.
- "두 번" 판정이 있는 버튼(2, 4)은 짧게 판정을 400ms 지연 확정한다.
- 버튼1 연타: 1200ms 동안 추가 입력이 없으면 확정. 횟수 1~4 그대로, 5 이상 = 5(다수).
- 조이스틱
  - 부팅 시 200ms 동안 평균으로 중앙값 보정(사용자는 부팅 시 조이스틱을 건드리지 않는다).
  - 기울기 비율 = 중앙으로부터 거리 / 최대 거리(축별 최대값 학습, 기본 512).
  - < 35%: 방향 없음. 35~75%: 근거리(0). ≥ 75%: 원거리(2).
  - 방향: atan2 → 12시 = 총구 전방(조이스틱 장착 방향에 맞춰 `config.h`에서 축 반전/회전 오프셋 설정 가능) → 시계 1~12로 반올림.
  - **보고 시점의 방향/거리는 해당 버튼이 눌린 순간의 조이스틱 값**으로 고정한다.
- 입력 → 메시지 매핑은 프로토콜 §9.1 표를 그대로 따른다.

### 6.2 보고 송신 (app/reporter)
- 프레임 헤더: ver 0x01, src_id = SOLDIER_ID, dst_mask = 0x80, seq는 송신자 순번(재전송 시 유지).
- azimuth = (heading + (clock − 12) × 30) mod 360, heading 없으면 0xFFFF. clock = 0이면 azimuth = 0xFFFF.
- 긴급 보고(0x01, 0x03, 0x04, 0x06, 0x07): EMCON 1/2에서 3초 내 RPT_ACK 없으면 같은 seq로 최대 3회 재전송.
- EMCON 0: 연결이 없으므로 report_queue에 저장(최대 32, 넘치면 일반 보고부터 폐기).
- EMCON 1: 긴급 + ACK/CANNOT_COMPLY + VOICE_RESULT는 즉시, 나머지는 큐에 넣고 30초마다 일괄.
- EMCON 2: 즉시.
- 송신 시 LED3 짧게 점등 + 로컬 피드백 음성(§6.5).

### 6.3 명령 수신 (app/commands)
- RX에서 받은 프레임 검증: ver, len, dst_mask에 내 비트(bit(ID−1)) 포함 여부. 실패 시 폐기.
- dedup: 최근 16개 (src_id, seq). 중복 CMD_BUTTON은 **다시 재생만** 하고 새 명령으로 취급하지 않는다.
- CMD_BUTTON: cmd_code → 문장 템플릿(프로토콜 §6.2) → 방향은 azimuth를 내 heading 기준 시계로 변환(§6.7). RALLY는 POS_TABLE 원점(분대장) 방향으로 계산.
- "마지막 명령" 상태 = {ref_type(0x10/0x11), ref_id, 재생 시퀀스}. 버튼3 짧게 → ACK, 길게 → CANNOT_COMPLY(마지막 명령 기준). 마지막 명령이 없으면 송신하지 않고 짧은 오류음.
- 미확인 동안 LED2 점멸(500ms), 30초 경과 시 빠른 점멸(150ms).
- EMCON_SET(0x16) 또는 SILENCE(0x0B) 수신 → 해당 모드로 전환.
- REQ_STATS(0x1F) → STATS(0x0D) 응답.
- RPT_ACK(0x17) → reporter의 재전송 대기 해제.
- POS_TABLE(0x15), PEER_REPORT(0x14) → squad_map(F8).

### 6.4 오디오 출력 (hal/audio_out) — F5
- **nRF52840 PWM 주변기기 + EasyDMA 시퀀스**로 구현한다(Arduino `analogWrite`/`tone`으로 하지 않는다).
  - PWM 클럭 16MHz, COUNTERTOP = 250 → 반송파 64kHz.
  - SEQ[n].REFRESH = 7 → 샘플 하나당 8주기 = **정확히 8kHz 샘플레이트**.
  - DECODER: Common, 값 범위 0~250(무음 = 125). 극성 비트 주의.
  - 이중 버퍼(SEQ0/SEQ1 교대, EVENTS_SEQEND 인터럽트에서 다음 블록 채움), 블록 크기 256샘플.
  - Arduino 코어의 `HardwarePWM`/`tone`이 사용하는 PWM 인스턴스를 코어 소스에서 확인하고 **사용되지 않는 인스턴스**를 쓴다. 확인 결과를 PROGRESS.md에 기록.
- 재생 소스 인터페이스: "다음 샘플 블록을 채워 달라" 콜백. 소스는 (a) 내장 조각 시퀀스, (b) 수신 음성 버퍼. 둘 다 ADPCM → int16 → 0~250으로 변환.
- 우선순위: 긴급 음성/명령 > 일반 명령 > 로컬 피드백. 높은 우선순위가 오면 현재 재생을 끊는다.
- 음량: `config.h`의 `AUDIO_GAIN`(0.0~1.0, 기본 0.3)로 스케일.
- **외부 회로(사용자 제작)**: PWM 핀 → 1kΩ → 노드A → 47nF → GND (저역통과, 약 3.4kHz) → 노드A → 10µF(결합) → 470Ω → 이어폰 팁(좌/우 함께), 이어폰 슬리브 → GND.
  - 첫 시험은 이어폰을 **귀에 꽂지 말고** 가까이 두고 들은 뒤 음량을 조절하라고 사용자에게 안내한다.

### 6.5 음성 조각과 문장 (app/phrases, assets/audio_clips.h) — F5
- 조각 목록과 ID는 `tools/gen_clips.py` 안의 표 하나로 관리(이 표가 기준). 프로토콜 §9.3 목록 + 로컬 피드백:
  - 숫자: n1, n2, n3, n4, many(다수), unknown(미상)
  - 방향: c1 ~ c12 ("1시" ~ "12시")
  - 거리: near(근거리), mid(중거리), far(원거리)
  - 명령: halt, cover, advance, withdraw, rally, open_fire, cease_fire, observe, report_status, silence, hold, cancel
  - 명사: enemy(적), suspicious(징후), hazard(폭발물 의심), casualty(부상자), friendly(아군)
  - 시스템: sent(송신), received(수신), mode_silent(침묵), mode_min(최소), mode_normal(정상), calib_start(보정 시작), calib_done(보정 완료), err(짧은 오류음, 합성음)
- 원본: `assets/clips_wav/{id}.wav` (사용자가 직접 녹음하거나 노트북 TTS로 생성). gen_clips.py가 모노 8kHz 리샘플 → 앞뒤 무음 제거 → 정규화 → IMA ADPCM 인코딩 → `audio_clips.h`(const 배열, 플래시 배치, 조각별 초기 predictor/step_index 포함) 생성.
- 플래시 예산: 조각 합계 약 150KB 이하 목표(조각 평균 0.6초 × 약 60개 × 4KB/s). 생성 시 총 바이트를 출력하고, 컴파일 출력으로 여유를 확인.
- 문장 템플릿은 프로토콜 §6.2(명령), §9.2(로컬 피드백), §9.3(PEER_REPORT) 그대로. 조각 사이 무음 80ms.

### 6.6 BLE (hal/radio) — F1, F6
- `<bluefruit.h>`(Adafruit nRF52 코어 계열) 사용. 1단계에서 실제 컴파일로 사용 가능 여부를 검증하고, 불가하면 즉시 보고.
- 역할: Peripheral 1 + Central 0, 단 침묵 모드 수동 스캔을 위해 Scanner 사용(`useActiveScan(false)`).
- NUS: `BLEUart`. 프로토콜 §3.1 UUID와 일치하는지 확인.
- MTU 최대 허용(대역폭 최대 설정). 연결 후 협상된 MTU를 로그로 남긴다.
- 광고: 이름 `SQ1-S{ID}`, NUS 서비스 UUID 포함, 연결 가능 광고.
- 모드 전환
  - → EMCON 0: 연결 끊기 → 광고 중지 → 수동 스캔 시작(Company ID 0xFFFF 필터는 콜백에서 직접 확인). 받은 프레임은 일반 RX 경로(commands)로 넘긴다.
  - → EMCON 1: 스캔 중지 → 광고 재개, 송신 출력 최저값(`Bluefruit.setTxPower`의 지원 최소값, 코어 문서에서 확인), 연결되면 큐 송신 시작.
  - → EMCON 2: 송신 출력 기본값(0dBm 또는 코어 기본), 즉시 송신.
- 로그 프레임: 디버그용으로 msg_type **0x7F LOG**(병사 → 분대장, payload = ASCII 최대 100바이트)를 정의해 사용한다. 이 타입은 프로토콜 문서에는 없으므로 **디버그 빌드 플래그(`DEBUG_LOG`)가 켜져 있을 때만** 송신하고, mock_leader는 이를 화면에 출력한다. 분대장 팀원에게는 "0x7F는 무시하라"고 사용자가 전달한다.

### 6.7 방향 계산 (core/geo) — F7, F8
- clock_from(azimuth, my_heading): rel = (azimuth − my_heading + 360) mod 360, clock = round(rel / 30), 0 → 12. heading이 0xFFFF면 azimuth를 진북 기준 시계로 간주하고 문장 앞에 아무것도 붙이지 않는다(데모 단순화, PROGRESS에 기록).
- azimuth_from(clock, my_heading): (my_heading + (clock − 12) × 30 + 360) mod 360.
- 표적 위치: T = 보고자 위치 + d·(sin az, cos az), d = {0: 50m, 1: 100m, 2: 200m, 없음: 100m}. 좌표는 분대장 원점, x 동쪽, y 북쪽, 단위 0.1m(프로토콜).
- 내 기준: P = POS_TABLE의 내 위치, b = atan2(Tx − Px, Ty − Py)의 방위(0~359), r = |T − P| → clock, 거리 구간(< 75m 근, < 150m 중, 그 외 원).
- POS_TABLE을 받기 전에는 PEER_REPORT를 보고자 기준 방향 그대로 재생하고 "위치 정보 없음" 플래그를 로그로 남긴다.

### 6.8 방위 센서 (hal/heading) — F7
- 인터페이스: `begin()`, `available()`, `headingDeg()`(0~359 또는 0xFFFF), `startCalibration()`, `calibrationDone()`.
- 기울기 보정 방위(가속도 + 자력계). 하드아이언 보정: 버튼1+버튼4 3초 → 20초간 min/max 수집 → 오프셋 저장(InternalFileSystem 사용 가능하면 사용, 아니면 RAM만).
- 지자기 편차(진북 보정)는 `config.h` 상수(서울 약 −8도, 사용자가 확인 후 설정)로 둔다.
- 센서 모델이 정해지기 전에는 스텁(항상 0xFFFF) 구현으로 나머지 기능이 동작해야 한다.
- 방위 소스는 `config.h`의 `HEADING_MODE`로 고른다:
  - `HEADING_MODE_NONE`: 항상 0xFFFF(센서 없음).
  - `HEADING_MODE_FIXED`: 항상 `HEADING_FIXED_DEG`(0~359, 기본 0 = 북쪽). 센서 없이 시연할 때 "모두 북쪽을 보고 있다"고 가정.
  - `HEADING_MODE_SENSOR`: 9축 센서 사용(단계 8에서 구현).
  - **기본값은 `HEADING_MODE_FIXED`, 0도.** 다른 모듈은 `headingDeg()`만 쓰고 모드를 몰라야 한다.

### 6.9 음성 수신 (app/voice_rx) — F4
- 프로토콜 §7.4를 그대로 구현. 버퍼 40,000바이트 정적 할당(동적 할당 금지).
- BEGIN 후 3초 내 END 없으면 폐기 + VOICE_RESULT status 2.
- 수신 중 새 BEGIN이 오면: priority 1이면 이전 것을 폐기하고 새로 시작, 0이면 새 것을 거부(status 3이 아니라 무시하고 로그).
- 재생 완료 후 "마지막 명령" = (0x11, voice_id)로 설정, LED2 미확인 점멸.

### 6.10 통계 (app/stats) — F9
- EMCON 모드별 송신 프레임 수와 바이트 수(헤더 포함) 집계. 재전송도 집계에 포함.
- REQ_STATS 응답 형식은 프로토콜 §5.1 0x0D.

### 6.11 LED (프로토콜 §9.4 그대로)
LED1 연결 상태, LED2 미확인 명령, LED3 송신 순간, LED4 EMCON 모드.

---

## 7. 노트북 도구 (tools/)

### 7.1 frame_codec.py
- 프로토콜 §4~§7 전체 메시지의 encode/decode. 바이트 단위로 프로토콜 §11.1의 hex 예시와 일치해야 한다(자체 테스트 함수 포함).
- 분대장 팀원도 그대로 가져다 쓸 수 있도록 외부 의존성 없이 작성.

### 7.2 adpcm.py
- 표준 IMA ADPCM, 하위 니블 먼저, `audioop` 미사용(Python 3.13에서 제거됨).
- encode(int16 list, predictor, step_index) → (bytes, 최종 상태), decode 대칭.

### 7.3 test_vectors.py
- 프로토콜 부록 A 조건(440Hz, 진폭 8000, 8kHz 1초, 초기 상태 0/0)으로 처음 16바이트 hex와 CRC16 출력.
- 같은 값을 펌웨어 core 호스트 테스트(test_crc_adpcm.cpp)에서도 검증한다.

### 7.4 mock_leader.py (분대장 대역)
- bleak로 `SQ1-S*` 스캔·연결, TX Notify 구독, MTU 출력.
- **`SQ1-S1`~`S5` 여러 대 동시 연결**(병사별 MTU 따로 출력, 끊기면 재연결).
- **명령 대상 지정**: 각 송신 명령에 대상(`all` 또는 ID 목록)을 줄 수 있다. 대상은 프레임 `dst_mask`로 넣고, 그 병사들 연결로만 write한다(기본 `all`).
- **수신 프레임 출력에 병사 ID 표시**(어느 연결에서 왔는지 + 프레임 src_id, 둘이 다르면 경고).
- 대화형 CLI 명령:
  - `cmd <code|name> [az] [dist] [extra] [prio] [targets]` → CMD_BUTTON
  - `voice <wav경로> [prio]` → 8kHz 변환 → ADPCM → BEGIN/CHUNK/END (청크 간격 옵션 `--gap-ms`, 기본 15)
  - `pos <preset이름>` → POS_TABLE (프리셋: wedge(쐐기), line(횡대), column(종대), 간격 10m, 분대장 원점, 각자 heading 0)
  - `peer <reporter_id> <az> <dist> <count>` → PEER_REPORT(CONTACT)
  - `emcon <0|1|2>`, `stats`, `raw <hex>`
- 수신한 모든 프레임을 사람이 읽는 형태로 출력(보고 종류, 방향, 시계, 거리, 적 수, ACK 대상 등). 보고 수신 시 RPT_ACK 자동 송신(옵션으로 끌 수 있게: 재전송 시험용).
- `--log-csv` 옵션: 수신/송신 프레임을 CSV로 저장(발표용 송신량 비교).

### 7.5 gen_clips.py
- §6.5 조각 표 관리, WAV → `firmware/SoldierNode/src/assets/audio_clips.h` 생성, 누락 WAV 목록 출력.
- 옵션 `--tts-mac`: macOS의 `say` 명령(한국어 음성)으로 누락 조각 WAV를 생성할 수 있으면 생성(사용자 승인 후 실행). 그 외 OS는 사용자가 녹음.

---

## 8. 테스트

- 호스트 단위 테스트: `make -C tests/host` → frame(프로토콜 §11.1 hex 일치), crc16(알려진 "123456789" → 0x29B1), adpcm(인코드→디코드 오차, 부록 A 벡터), geo(시계 변환 경계: 0/359/15/345도, 표적 변환 예).
- 장비 테스트는 각 단계 프롬프트의 "완료 조건"을 따른다.
- 모든 장비 테스트 결과(사용자 확인 포함)는 PROGRESS.md에 기록.

---

## 9. 하지 말 것

- 프로토콜 문서에 없는 메시지를 분대장 쪽으로 보내기(디버그 0x7F LOG 예외).
- HEARTBEAT·심박 기능 구현(v2).
- 보드 가이드 0-A 자동 설정 실행, Arduino IDE·코어 재설치, 다른 보드 URL 삭제.
- USB Serial 사용(§2-9의 USB_EARPIECE 예외 제외), 블로킹 delay, 동적 메모리 할당(음성 버퍼 포함).
- 사용자 확인 없이 업로드·라이브러리 설치.
