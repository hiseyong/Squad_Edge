# 진행 기록 (PROGRESS)

## 단계 0 — 환경 확인 + 골격 (2026-10-10)

### 1) 개발 환경 확인 결과
| 항목 | 결과 |
|---|---|
| `arduino-cli` (PATH) | **없음** (`command not found`) |
| Arduino IDE 내장 CLI | `/Applications/Arduino IDE.app/Contents/Resources/app/lib/backend/resources/arduino-cli` — `Version: 1.5.1 Commit: 01f3d4f2b Date: 2026-06-05` |
| `core list` | `arduino:avr 1.8.8` **만 설치됨** |
| `nucode:nrf52` 코어 | **미설치**. `~/Library/Arduino15/packages/nucode` 없음 |
| Board Manager 추가 URL | 비어 있음(`~/.arduinoIDE/arduino-cli.yaml`: `additional_urls: []`). NUCODE 패키지 URL 미등록 |
| 호스트 컴파일러 | `/usr/bin/g++` (Apple clang 21.0.0), `make` 있음 |

- CLAUDE.md는 "환경은 이미 설치됨"을 전제로 하지만 실제로는 NUCODE 코어가 없다. 지시대로 **설치 작업은 하지 않았다**.

### 2) 골격 생성
- CLAUDE.md §4 구조대로 모든 폴더와 빈 파일(헤더/소스 스텁, Python 스텁, `audio_clips.h` 자리표시자, `assets/clips_wav/.gitkeep`) 생성.
- `firmware/SoldierNode/config.h`: §3.2 핀 배정, §6 타이밍 상수, TODO_CONFIRM 목록(7개) 작성.
- `tests/host/Makefile`: core/*.cpp와 각 test_*.cpp를 빌드·실행. 현재 테스트는 빈 main.
- `tools/requirements.txt`: `bleak`만 기재(**설치하지 않음**).
- AGENTS.md(Codex용 사본)는 이번 단계 범위가 아니어서 만들지 않음.

### 3) 최소 펌웨어 컴파일 / Bluefruit 판정
- `SoldierNode.ino`: LED1 1초 점멸(millis 비차단, Serial 없음) + `#include <bluefruit.h>` + `Bluefruit.begin()`.
- 실행: IDE 내장 CLI로 `arduino-cli compile --fqbn nucode:nrf52:nu40dk firmware/SoldierNode`
- 출력:
  ```
  Error during build: Platform 'nucode:nrf52' not found: platform not installed
  Platform nucode:nrf52 is not found in any known index
  Maybe you need to add a 3rd party URL?
  ```
- **판정: 보류.** 코어가 없어 컴파일 자체를 할 수 없으므로 bluefruit 사용 가능 여부는 아직 판단할 수 없다. Flash/RAM 사용량도 없음.

### 호스트 테스트
- `make -C tests/host` → 3개 빈 테스트 빌드·실행, `ALL HOST TESTS PASSED` (골격 확인용).

### 남은 문제
1. **NUCODE 코어 설치 필요**(사용자 승인 필요): 패키지 URL 등록 → `core update-index` → `core install nucode:nrf52`. 그다음 단계 0-3 컴파일을 다시 해서 bluefruit 판정.
2. `arduino-cli`가 PATH에 없다. 지금은 IDE 내장 CLI를 전체 경로로 쓴다(PATH 추가나 별칭은 사용자 결정).
3. 코어 설치 후 확인할 것: variant의 `PIN_BUTTONx`/`PIN_LEDx`/`LED_STATE_ON` 정의, P1.10 사용 여부, HardwarePWM/tone이 쓰는 PWM 인스턴스, `setTxPower` 지원 최소값.
4. 프로토콜 부록 A(ADPCM 테스트 벡터)가 비어 있다(분대장 측이 채울 예정). 그 전까지는 우리 쪽 test_vectors.py 결과로 자체 검증만 가능.
5. 보드 가이드 §1에는 제공 부품이 "6축 IMU"로 적혀 있다. 6축(가속도+자이로)에는 자력계가 없어 절대 방위를 계산할 수 없다. F7에는 9축(자력계 포함) 센서가 필요.

### 테스트 방법
- 호스트: `make -C tests/host`
- 펌웨어(코어 설치 후): `arduino-cli compile --fqbn nucode:nrf52:nu40dk firmware/SoldierNode`

---

## 단계 0 (계속) — 코어 설치 + 컴파일 (2026-10-10)

### 코어 설치 (사용자 승인: 최초 1회 설치)
- CLI: IDE 내장본 + IDE 설정 파일 `--config-file ~/.arduinoIDE/arduino-cli.yaml` (IDE와 같은 설정·데이터 폴더 공유).
  - 설정 파일 백업: 세션 scratchpad에 사본 저장 후 수정.
- `config add board_manager.additional_urls <NUCODE URL>` → 기존 URL 목록은 원래 비어 있었고, NUCODE URL 1개만 추가됨.
- `directories.data` = `/Users/nohyeonjong/Library/Arduino15` (IDE와 동일) 확인.
- `core install nucode:nrf52` → `Platform nucode:nrf52@1.0.2 installed` (툴: arm-none-eabi-gcc 9-2019q4, nrfjprog 9.4.0, CMSIS 5.7.0, openocd 0.11.0-arduino2).
- `core list`:
  ```
  arduino:avr  1.8.8 1.8.8  Arduino AVR Boards
  nucode:nrf52 1.0.2 1.0.2  NUBoards nRF52
  ```

### 컴파일 결과
- 컴파일·링크 **성공**: `SoldierNode.ino.elf`, `SoldierNode.ino.hex` 생성. 경고는 `USE_TINYUSB redefined`만.
- 사용 라이브러리: Adafruit Bluefruit nRF52 Libraries 0.21.0 (코어 내장), nRFCrypto 0.1.2, TinyUSB 3.7.0, LittleFS/InternalFileSystem 0.11.0.
- **마지막 패키징(DFU zip) 단계 실패**:
  `fork/exec .../tools/adafruit-nrfutil/macos/adafruit-nrfutil: permission denied`
  - 원인: 파일 권한이 `-rw-r--r--`(실행 권한 없음). 파일은 x86_64 Mach-O, 이 Mac은 arm64이고 Rosetta 사용 가능 확인.
  - 보드 가이드 §8 처방 = 해당 파일에 사용자 실행 권한 추가. 프로젝트 폴더 밖 파일이라 **사용자 승인 대기**.
- 실패 때문에 arduino-cli의 Flash/RAM 요약 줄은 나오지 않음. elf 기준 수치(`arm-none-eabi-size -A`):
  - Flash: `.text` 120,792 + `.data` 872 ≈ 121.7KB
  - RAM 정적: `.data` 872 + `.bss` 14,476 = 15,348B (`.heap` 220,172B는 남은 영역을 힙으로 잡은 것)
- **Bluefruit 판정: 사용 가능** (`<bluefruit.h>` + `Bluefruit.begin()` 링크 성공). 패키징 문제는 Bluefruit와 무관.

### 코어 소스 확인 결과
- variant (`variants/nu40dk_nrf52840/variant.h`):
  - `PIN_LED1~4` = 13~16, **`LED_STATE_ON` = 1 (HIGH가 켜짐)**. `PIN_BUTTON1~4` = 11, 12, 24, 25 (극성 정의 없음 → 테스트로 확인).
  - Arduino 핀 n ↔ GPIO 1:1 대응(42 = P1.10).
  - **`PIN_VBAT` = A7 (P0.31)**. 보드 가이드는 회로도 기준 VBAT ADC = P0.02라고 함 → 불일치. 둘 다 사용하지 않음(조이스틱은 A1/A2, SW는 P0.28).
- **오디오 핀 P1.10**: variant의 UART/SPI/QSPI/NFC/I2C/LED/버튼 어떤 정의에도 쓰이지 않음. 보드 가이드 핀 헤더 목록에서 오른쪽 헤더에 나와 있음. 회로도 원본(PDF)이 로컬에 없어 보드 배선 수준 확인은 못 함.
- **PWM 인스턴스**: `Tone.cpp`는 `NRF_PWM2` 고정 사용. `analogWrite()`는 `HwPWM0~3` 중 비어 있는 것을 동적으로 차지. → 오디오는 **`NRF_PWM3`** 사용, 펌웨어 전체에서 `analogWrite`/`tone`/`HwPWMx` 사용 금지로 충돌 방지.
- **Bluefruit 자동 LED**: 기본값으로 `LED_CONN`(= `PIN_LED2`)을 광고 중 점멸/연결 시 켬. 우리 LED2(미확인 명령)와 충돌 → radio 단계에서 `Bluefruit.autoConnLed(false)` 필요.
- `setTxPower` 지원값(nRF52840): -40, -20, -16, -12, -8, -4, 0, 2~8 dBm → EMCON 1 최저값 = **-40 dBm**.

### 사용자 답변 반영 (config.h)
- 방위 센서: 6축 IMU만 있음 → 단계 8까지 0xFFFF 스텁. 6축 IMU는 연결하지 않음.
- 조이스틱 SW = P0.28 확정(아직 배선 전).
- `EMCON_BOOT_MODE` = 2 (config.h 상수).
- 남은 TODO_CONFIRM: 오디오 핀 회로도 확인, 버튼 극성, 조이스틱 장착 방향, 지자기 편차.

### 패키징 문제 해결 (사용자 승인)
- `chmod u+x .../tools/adafruit-nrfutil/macos/adafruit-nrfutil` → `-rwxr--r--`, `adafruit-nrfutil version 0.5.3.post16` (보드 가이드의 정상 출력과 동일).
- 재컴파일 **성공 (exit 0)**, 실제 출력:
  ```
  스케치는 프로그램 저장 공간 121664 바이트(14%)를 사용. 최대 815104 바이트.
  전역 변수는 동적 메모리 15348바이트(6%)를 사용, 222220바이트의 지역변수가 남음.  최대는 237568 바이트.
  ```
- **단계 0 판정: Bluefruit 사용 가능, 최소 펌웨어 컴파일 완료.** 업로드는 하지 않음.
- 메모: 음성 버퍼 40,000B + 오디오 이중 버퍼 등을 추가해도 RAM 여유 충분(남은 약 222KB). 조각 150KB 추가 시 Flash 약 33%.

### 남은 문제
1. (해결됨) adafruit-nrfutil 실행 권한.
2. `arduino-cli`는 PATH에 없음. 명령: `"/Applications/Arduino IDE.app/Contents/Resources/app/lib/backend/resources/arduino-cli" --config-file ~/.arduinoIDE/arduino-cli.yaml compile --fqbn nucode:nrf52:nu40dk firmware/SoldierNode`

---

## 단계 0 (계속) — 업로드 경로 확인 (2026-10-10, 사용자 요청)

- `board list`: `/dev/cu.usbmodem101` (Serial Port (USB), Board Name Unknown). USB 정보: Vendor "Nordic", Product "PCA10056", VID 0x239A, PID 0x00DA → NU-40 DK로 판단.
- 명령: `arduino-cli --config-file ~/.arduinoIDE/arduino-cli.yaml upload -v --fqbn nucode:nrf52:nu40dk -p /dev/cu.usbmodem101 firmware/SoldierNode`
- 출력 요지:
  ```
  Performing 1200-bps touch reset on serial port /dev/cu.usbmodem101
  No upload port found, using /dev/cu.usbmodem101 as fallback
  ... dfu serial ... -b 115200 --singlebank
  Starting DFU upgrade of type 4, SoftDevice size: 0, bootloader size: 0, application size: 121672
  Activating new firmware
  DFU upgrade took 7.955564737319946s
  Device programmed.
  New upload port: /dev/cu.usbmodem101 (serial)
  ```
- **업로드 성공** (`Device programmed.`, `Failed to upgrade target` 없음, exit 0). §10 복구 절차 불필요. 리셋 후 포트 이름이 바뀌지 않아 같은 포트로 진행됨.
- 업로드 후 `board list`: `/dev/cu.usbmodem101 ... NU40DK nRF52840 nucode:nrf52:nu40dk` 로 보드가 인식됨.
- LED1 1초 점멸 육안 확인 (사용자, 2026-10-10): **LED1 반복 점멸 확인.** 단, **LED2~4가 초록색으로 계속 켜져 있음.**
  - 분석: 코어 `initVariant()`는 LED1~4를 `ledOff()` = `digitalWrite(pin, !LED_STATE_ON)` = LOW로 둔다(variant `LED_STATE_ON = 1`). 코드는 LED2~4를 건드리지 않고, Bluefruit 자동 LED(LED2)는 광고할 때만 동작하는데 지금은 광고하지 않는다.
  - → LOW를 줬는데 켜져 있으므로 **이 보드의 LED는 LOW에서 켜질(active-low) 가능성이 높다**(variant의 `LED_STATE_ON = 1`과 반대). 그렇다면 LED1도 "켜짐/꺼짐" 위상이 반대지만, 점멸만 보면 구분되지 않는다.
  - 확정은 보류(추측 금지). 단계 1에서 확인 방법을 정한다.

---

## 요구사항 변경 (2026-10-10, 사용자 지시로 이번 1회 CLAUDE.md 수정)

### 변경 내용
1. **병사 단말 2대(ID 1, 2)**: `config.h`의 `SOLDIER_ID`를 `#ifndef` 기본 1로 바꿈. CLAUDE.md §3.3에 반영.
   - 검증: `-DSOLDIER_ID=2` 컴파일 성공. `-DSOLDIER_ID=6`이면 `#error "SOLDIER_ID must be 1..5"`로 실패 → 플래그가 config.h까지 전달되는 것 확인. 기본(1) 컴파일 성공, 121,664B / 15,348B.
2. **방위 소스 선택**: `HEADING_MODE` = `HEADING_MODE_NONE`(0xFFFF) / `HEADING_MODE_FIXED`(`HEADING_FIXED_DEG`) / `HEADING_MODE_SENSOR`(단계 8). **기본 FIXED, 0도.** 둘 다 `#ifndef`라 빌드 플래그로도 바꿀 수 있음. CLAUDE.md §6.8에 반영.
3. CLAUDE.md §7.4 mock_leader: 여러 대 동시 연결, 명령 대상 지정(dst_mask + 해당 연결로만 write), 수신 프레임에 병사 ID 표시 추가.
4. CLAUDE.md §5: F11 "병사 간 RSSI 거리 측정(나중, 단계 R)" 추가만. 구현하지 않음.

### ID별 컴파일·업로드 명령 (※ 업로드는 아래 "표준 업로드 절차"(2026-10-10 갱신)를 따른다)
`CLI="/Applications/Arduino IDE.app/Contents/Resources/app/lib/backend/resources/arduino-cli"`, `CFG=~/.arduinoIDE/arduino-cli.yaml`
- 포트는 매번 `"$CLI" --config-file $CFG board list`로 새로 찾는다. **두 보드의 VID/PID가 같으므로 업로드할 보드 1대만 USB에 꽂고** 진행하는 것을 권장(둘 다 꽂혀 있으면 `ioreg -p IOUSB -l -w0 | grep "USB Serial Number"`로 구분). 지금까지 쓴 보드의 USB 시리얼 번호: `7658AE0B1C2F8327`.
- ID별 플래그로 다시 컴파일한 결과가 바로 올라가도록 `compile --upload`를 쓴다(`upload`만 쓰면 캐시에 남은 다른 ID 빌드가 올라갈 수 있음).

```bash
# 병사 1 (기본값)
"$CLI" --config-file $CFG compile --fqbn nucode:nrf52:nu40dk --build-property "compiler.cpp.extra_flags=-DSOLDIER_ID=1" --upload -p <포트> firmware/SoldierNode
# 병사 2
"$CLI" --config-file $CFG compile --fqbn nucode:nrf52:nu40dk --build-property "compiler.cpp.extra_flags=-DSOLDIER_ID=2" --upload -p <포트> firmware/SoldierNode
# 컴파일만: 위 명령에서 --upload -p <포트> 제거
```
- 주의: `compiler.cpp.extra_flags`는 .cpp/.ino에만 적용된다(.c 파일에는 안 감). 다른 플래그와 함께 쓰려면 같은 값 안에 공백으로 이어 쓴다(예: `"compiler.cpp.extra_flags=-DSOLDIER_ID=2 -DHEADING_MODE=0"`).

---

## LED/버튼 극성 진단 (2026-10-10)

- 진단 펌웨어: `firmware/diag/LedButtonDiag/` (본 펌웨어와 분리, Serial/Bluefruit 없음, millis 기반).
  - 0~10초: LED1=HIGH, LED2=LOW, LED3=HIGH, LED4=LOW 고정. 10초 후: 버튼1~4(INPUT_PULLUP) 원시값 → LED1~4.
- 컴파일: 20,556B(2%), 전역 3,100B(1%), exit 0.
- 업로드 (사용자 승인): `/dev/cu.usbmodem101` (USB Product "NU40DK nRF52840", 시리얼 `7658AE0B1C2F8327`) → `Device programmed.`, exit 0.
- 사용자 관찰 결과:
  - 0~10초: **LED2, LED4 켜짐** (LOW를 준 쪽) → **LED는 active-low, `LED_ON_LEVEL = LOW`**. variant의 `LED_STATE_ON = 1`은 이 보드와 반대.
  - 10초 후, 버튼 안 누름: 모두 꺼짐 → 입력 HIGH.
  - 버튼 누름: 해당 LED 켜짐 → 입력 LOW → **`BUTTON_PRESSED_LEVEL = LOW`** (INPUT_PULLUP 정상).
  - 버튼 n ↔ LED n 대응 1~4 모두 정상.
- 반영:
  - `config.h`: `LED_ON_LEVEL = LOW`, `LED_OFF_LEVEL = HIGH`, `BUTTON_PRESSED_LEVEL = LOW` 확정, TODO_CONFIRM에서 제거. 앞으로 `LED_STATE_ON`은 쓰지 않는다.
  - `SoldierNode.ino`의 LED1 점멸을 `LED_ON_LEVEL/LED_OFF_LEVEL` 사용으로 수정.
  - 단계 0 펌웨어에서 LED2~4가 켜져 있던 이유: 코어 `initVariant()`가 `ledOff()`로 LOW를 주는데 이 보드에서는 LOW = 켜짐. 본 펌웨어 leds 초기화에서 4개 모두 `LED_OFF_LEVEL`로 덮어써야 한다.
  - Bluefruit 자동 LED(`autoConnLed`)도 `LED_STATE_ON` 기준이라 반대로 동작한다 → radio 단계에서 `autoConnLed(false)` 필수(이미 계획됨).

---

## 단계 1 — core 로직 + 호스트 테스트 (2026-10-10) ✅ 완료

### 구현
- `src/core/` (모두 Arduino 비의존, **C 호환**: C 헤더 + `extern "C"`, 클래스/STL/동적 할당 없음. 파일 확장자는 CLAUDE.md §4대로 `.cpp`)
  - `frame`: 프로토콜 §5 전체 msg_type encode/decode + 0x7F LOG(디버그) + **0x0E RANGING / 0x20 BEACON(v1.1 예정, 형식만)**. 0x0C HEARTBEAT은 v2 예약(형식만, 송신 금지).
    - 디코드 검사: 헤더 길이, ver, len 필드 = 실제 길이, msg_type별 payload 길이(고정형은 정확히, POS_TABLE/RANGING은 1+7n/1+3n), mode ≤ 2, step_index ≤ 88, LOG ≤ 100.
    - `frame_receive(buf, n, soldier_id)` = 디코드 + dst_mask 내 비트 검사(병사 수신 경로).
    - 가변 데이터(VOICE_CHUNK 데이터, PEER_REPORT 원 보고, LOG)는 입력 버퍼 포인터로 반환(복사 없음).
    - 최대 프레임 244B(MTU 247 − 3), VOICE_CHUNK 235B 데이터로 검증.
  - `crc16`: CRC-16/CCITT-FALSE, 비트 단위(표 없음), 이어서 계산 가능(`crc16_update`).
  - `adpcm`: 표준 IMA, 하위 니블 먼저. 니블 단위 디코드(`adpcm_decode_nibble`, 스트리밍 재생용) + 일괄 decode/encode.
  - `geo`: clock↔azimuth, 거리 구간↔대표값, 표적 위치, 내 기준 변환(`geo_peer_to_me`).
    - 반올림: round(rel/30)의 .5는 **올림**(정수식 `(rel+15)/30`). 15도 → 1시, 345도 → 12시.
  - `dedup`: (src, seq) 최근 16개 링 버퍼. 중복 확인은 기록을 바꾸지 않음.
  - `report_queue`: 완성 프레임(최대 24B) 32개 정적 배열, 오래된 순서.
    - 넘침 정책(프로토콜 v1.0.1 §2에 채택됨): 꽉 차면 가장 오래된 **일반** 보고를 버림. 전부 긴급이면 새 일반 보고는 거부, 새 긴급 보고는 가장 오래된 긴급을 버림(최신 상황 우선). 긴급 판단 = msg_type 0x01/03/04/06/07.
- `tools/`: `frame_codec.py`(전체 메시지 dict encode/decode, CRC16, dst_mask 도우미), `adpcm.py`, `test_vectors.py`. 표준 라이브러리만 사용(struct, math), `audioop` 미사용.

### 테스트 결과 (실제 출력)
- `make -C tests/host`:
  ```
  core C99 syntax check OK
  test_frame: 269 checks, 0 failed
  adpcm 안정 구간 최대 오차 408
  test_crc_adpcm: 17 checks, 0 failed
  test_geo: 58 checks, 0 failed
  test_queue: 125 checks, 0 failed
  ALL HOST TESTS PASSED
  ```
  - frame: §11.1 예시 4개 인코드/디코드 바이트 일치, ver/len(짧음·김)/헤더 부족/payload 길이/알 수 없는 type/mode 범위/POS_TABLE 길이 폐기, dst_mask 0x1F·0x01·0x02·0x03·0x80을 병사 1과 2에 각각 적용, 전체 타입 왕복, PEER_REPORT 안의 원 보고 재해석.
  - crc16: "123456789" → 0x29B1 (나눠 계산해도 동일).
  - adpcm: 부록 A 처음 16바이트·CRC16, 인코더/디코더 최종 상태 일치, 안정 구간 최대 오차 408(진폭 8000), 니블 단위 = 일괄 디코드, 홀수 개/클램프.
  - geo: 방위 0/359/15/345도 및 내 방위 0/359/15/345도 경계, 360×12 전 조합 왕복, FIXED 0도 기준 변환, 표적 변환 예시 2개(아래).
  - dedup/report_queue: 16개 넘침, seq 255→0, 큐 넘침 시 일반부터 폐기·긴급 보존·전부 긴급일 때 동작, 꺼내는 순서.
- Python: `python3 tools/frame_codec.py` → `frame_codec self-test OK (§11.1 예시 4개 + 메시지 22종 왕복)`, `python3 tools/adpcm.py` → `adpcm self-test OK (안정 구간 최대 오차 408)`, `python3 tools/test_vectors.py` → `C 테스트 기대값과 일치`.
- **C++ ↔ Python 테스트 벡터 일치**: 같은 상수(처음 16바이트, CRC16)를 양쪽 테스트가 각각 계산해 통과.
- 추가 교차 검증: 이 노트북의 Python 3.12에는 아직 `audioop`이 있어 참조 구현으로 한 번 비교 → 니블 순서만 바꾸면 인코드 4000바이트·최종 상태(-2763, 62)·디코드 결과 **완전히 동일**(audioop은 상위 니블 먼저). 도구 코드는 audioop을 쓰지 않음.

### geo 표적 변환 예시 (간격 10m, 내 방위 0 = FIXED)
| 예시 | 보고 | 받는 병사 위치 | 결과 |
|---|---|---|---|
| 1 횡대 | 병사1(0,0) 방위 45, 중거리 → T≈(70.7m, 70.7m) | 병사2 10m 동쪽 | 방위 41, 93.2m 중거리, **1시** (병사2가 90도를 보면 10시) |
| 2 종대 | 병사1(0,0) 방위 90, 근거리 → T=(50m, 0) | 병사2 10m 남쪽 | 방위 79, 51.0m 근거리, **3시** |

### 펌웨어 컴파일 (ID 1, 2)
- 두 ID 모두 exit 0, `프로그램 저장 공간 121664 바이트(14%)`, `전역 변수 15348바이트(6%)`. 경고는 `USE_TINYUSB redefined`만.
- core 6개 파일이 ARM용 `.o`로 컴파일됨을 빌드 폴더에서 확인. 아직 `.ino`가 core를 호출하지 않아 링커가 제거하므로 크기는 단계 0과 같다(링크 검증은 이후 단계에서 core를 쓰기 시작할 때).

### 부록 A 값 (분대장 팀원 전달용, 프로토콜 문서는 수정하지 않음)
- 처음 16바이트: `70 77 77 77 F1 BB 9B 18 44 53 22 82 B8 CC AC 9B`
- 전체 CRC16(4000바이트): `0x0166`
- 인코더 최종 상태: predictor −2763, step_index 62

### 발견한 점 / 남은 문제 (→ 프로토콜 v1.0.1에서 모두 해결, 아래 "프로토콜 v1.0.1 반영" 참고)
1. ~~**프로토콜 §11.1 네 번째 예시의 값이 서로 맞지 않음**~~ **해결됨**: "시계 2, 내 방위 0"이면 §5.1 공식 azimuth = (0 + (2−12)×30) mod 360 = **60**인데 예시는 **45**(0x2D). 바이트 인코딩 테스트에는 영향 없음(필드 값을 그대로 넣음). 방위 45에서 시계를 구하면 2시(반올림)라 "방위 → 시계" 방향으로는 맞다. 문서 담당에게 알릴 것.
2. ~~시계 반올림~~ **해결됨**: 우리는 .5를 올림. 분대장 측이 Python `round()`(짝수 반올림)를 쓰면 rel 15도 → 12시, 75도 → 2시처럼 우리(1시, 3시)와 달라질 수 있다. 시계는 각자 화면/음성용이라 통신 호환성 문제는 아니지만, 맞추려면 `(rel + 15) // 30`을 쓰라고 전달하면 된다.
3. ~~report_queue 넘침 정책~~ **해결됨**: 넘침 정책 중 "전부 긴급일 때" 동작은 문서에 없어 위처럼 정함. 바꾸려면 알려 줄 것.

### 테스트 방법
- 호스트: `make -C tests/host`
- Python: `python3 tools/frame_codec.py && python3 tools/adpcm.py && python3 tools/test_vectors.py`
- 펌웨어: 위 "ID별 컴파일·업로드 명령"에서 `--upload -p <포트>` 제거

---

## 프로토콜 v1.0.1 반영 (2026-10-10)

사용자가 `docs/squad_ble_protocol_v1.md`를 v1.0.1로 교체(변경 이력: 부록 B). 문서는 수정하지 않음.

| v1.0.1 변경 | 반영/확인 |
|---|---|
| §11.1 네 번째 예시 azimuth 45 → **60** (`... 07 3C 00 02 02 03 00 00`) | `test_frame.cpp`, `frame_codec.py` 기대 hex 수정. C 테스트는 azimuth를 `geo_azimuth_from(2, 0)`으로 만들어 §5.1 공식과도 일치하는지 확인 → **해결됨** |
| §5.1 방위→시계 규칙 `(rel + 15) // 30`, 0 → 12 | `geo_clock_from` 구현과 동일(이미 15/345/14/16/344도 경계 + 전 조합 왕복 테스트) → **해결됨** |
| §2 긴급 보고만으로 큐가 찬 경우: 새 일반 거부, 새 긴급은 가장 오래된 긴급 폐기 | `report_queue_push` 구현과 동일(`test_queue` 검증) → **해결됨** |
| §5.3 예약 메시지 0x0E RANGING / 0x20 BEACON(dst 0xFF) / 0x7F LOG | frame.h 형식과 일치(RANGING n+n×[peer_id, rssi int8, samples], BEACON heading(2), LOG ASCII ≤ 100) |
| 부록 A 확정 `70 77 77 77 F1 BB 9B 18 44 53 22 82 B8 CC AC 9B` / `0x0166` | C/Python 기대값과 동일 |

재실행 결과:
```
core C99 syntax check OK
test_frame: 270 checks, 0 failed
test_crc_adpcm: 17 checks, 0 failed
test_geo: 58 checks, 0 failed
test_queue: 125 checks, 0 failed
ALL HOST TESTS PASSED
frame_codec self-test OK (§11.1 예시 4개 + 메시지 22종 왕복)
adpcm self-test OK (안정 구간 최대 오차 408)
test_vectors: C 테스트 기대값과 일치
```

---

## 단계 2 — BLE 연결 + mock_leader (2026-10-10) ✅ 완료 조건 충족

### 구현
- `hal/leds`: 부팅 시 LED1~4를 `LED_OFF_LEVEL`로 명시적으로 끔(코어 `initVariant()`가 켜 둔 것 덮어씀). 고정/주기 점멸, millis 기반.
- `hal/radio`: Bluefruit Peripheral 1 + Central 0, `configPrphBandwidth(BANDWIDTH_MAX)`(ATT MTU 247), **`autoConnLed(false)`**, 이름 `SQ1-S{ID}`, 광고 = Flags + NUS UUID + 이름(31B 안), 연결 끊기면 광고 자동 재개.
  - **NUS RX 경계 보존**: `BLEUart`는 write를 바이트 FIFO에 이어 붙여 프레임 경계를 잃는다. → `BLEUart`를 상속해 RX 특성의 write 콜백만 교체(UUID·TX Notify·CCCD는 BLEUart 그대로). write 하나 = 프레임 하나로 16슬롯 정적 링 버퍼에 저장(`useAdaCallback=false`: 라이브러리의 write당 malloc 회피).
  - 콜백(BLE 태스크) ↔ loop 사이는 잠금 없는 링 버퍼/이벤트 카운터(인터럽트 금지 안 씀 — SoftDevice 인터럽트 보호).
  - 송신은 notify 하나 = 프레임 하나. 프레임이 MTU−3보다 크면 쪼개지 않고 거부.
- `app/app`: 연결 상태 → LED1(hal/leds 경유), RX 프레임 → commands, 송신 seq 관리, `app_log()`(DEBUG_LOG일 때 0x7F LOG).
  - LOG 시점: Notify가 켜진 순간에 `boot …`(부팅 후 1회), `conn #n`(재연결이면 이전 끊김 이유 포함), `mtu=… max_write=…`(값이 바뀔 때마다), 수신 프레임마다 `rx …`/`rx drop err=…`.
- `app/commands`: `frame_receive(…, SOLDIER_ID)`로 ver/len/dst_mask 검증 → REQ_STATS면 STATS(0으로 채움) 응답, RPT_ACK는 로그만, 나머지는 `unhandled` 로그.
- `app/stats`: STATS 형식만(값 0). 집계는 F9 단계.
- `SoldierNode.ino`: `app_begin()` / `app_loop()`만.
- 컴파일(ID 1, 2): exit 0, **135,824B(16%) / 전역 19,608B(8%)**, 경고는 `USE_TINYUSB`만. ID 1·2 hex가 서로 다름 확인(ID 반영).
- `tools/mock_leader.py`: SQ1-S1~S5 동시 연결(NUS UUID로 스캔 필터, 모두 연결되면 스캔 중지, 끊기면 재스캔·재연결), 병사별 Notify 구독·MTU 출력, `raw <id|all> <hex>`, `stats <id|all>`(한 프레임, dst = 대상 비트 합, 대상 연결에만 write), `list`, `--only S1[,S2]`, 수신 프레임 해석 출력 + 연결 ID ≠ src_id 경고, MTU−3 초과 프레임은 보내지 않음.
  - 가짜 bleak로 오프라인 검사: `stats all` → 두 연결에 `01 1F 00 00 03 00`, `stats 2` → S2에만 dst 0x02, 끊긴 병사 건너뜀, src 불일치 경고, 잘못된 프레임 표시 확인.
- `tools/requirements.txt`: `bleak==1.1.1` (아직 설치 안 함)

### 업로드 후 시험 절차 (완료 조건: 두 보드 동시 연결, 각자 stats 응답과 LOG 표시)
1. 보드 1(ID 1)은 노트북 USB, 보드 2(ID 2)는 **USB 전원만**(노트북의 다른 포트나 충전기) 연결.
   - 펌웨어는 USB Serial을 쓰지 않고 호스트를 기다리는 코드도 없으므로, 데이터 연결 없이 전원만으로 부팅·광고한다.
2. `python3 tools/mock_leader.py --only S1,S2`
3. 기대 출력(시각·seq·MTU 값은 다를 수 있음):
   ```
   [S1] 발견 → 연결 시도 (…)
   [S1] 연결됨, Notify 구독, MTU=247 (한 번에 쓸 수 있는 최대 244B)
   [S1] ← LOG seq=0 src=1 dst=0x80 | "boot id=1 heading_mode=1 emcon_boot=2 up=…ms"
   [S1] ← LOG seq=1 src=1 dst=0x80 | "conn #1"
   [S1] ← LOG seq=2 src=1 dst=0x80 | "mtu=247 max_write=244"
   [S2] … (같은 내용, id=2, src=2)
   ```
4. `stats all` 입력 → 기대 출력:
   ```
   [S1] → REQ_STATS seq=0 src=0 dst=0x03  (01 1F 00 00 03 00)
   [S2] → REQ_STATS seq=0 src=0 dst=0x03  (01 1F 00 00 03 00)
   [S1] ← LOG seq=3 src=1 dst=0x80 | "rx type=1F seq=0 src=0 dst=03 plen=0"
   [S1] ← STATS seq=4 src=1 dst=0x80 | EMCON0 0프레임/0B, EMCON1 0프레임/0B, EMCON2 0프레임/0B
   [S2] ← LOG … "rx type=1F …",  [S2] ← STATS … src=2 …
   ```
5. 추가 확인: `stats 2` → S2만 응답, `raw 1 01 1F 07 00 02 00`(dst가 S2) → S1이 `rx drop err=-6` 로그, `quit` 후 LED1 꺼짐 → 다시 실행하면 `conn #2 prev_disc_reason=0x…`.
6. LED: 연결되면 **LED1 켜짐**, 끊기면 꺼짐. LED2~4는 꺼져 있어야 함(사용자 확인 필요).

### 주의
- MTU는 macOS가 정한다(보통 185~247). MTU 23(최대 20B)으로 잡히면 STATS(24B)와 대부분의 LOG가 MTU−3을 넘어 보내지지 않는다 → 그 경우 `mtu=` 로그도 안 보이므로 mock_leader의 MTU 출력으로 판단.
- macOS 첫 실행 시 터미널/IDE의 Bluetooth 권한 허용 필요.

### 진행 기록 (2026-10-10)
- bleak 설치(사용자 승인): `python3 -m pip install -r tools/requirements.txt` → `bleak-1.1.1`(+ pyobjc-core/Cocoa/CoreBluetooth/libdispatch 12.2.2). mock_leader가 쓰는 API 시그니처 확인.
- **보드 1 / ID 1 업로드 성공**
  - 처음엔 USB 장치가 전혀 보이지 않음 → 사용자가 RESET 두 번 → `NRF52BOOT` 볼륨 + `/dev/cu.usbmodem101`(Product "PCA10056", 시리얼 `7658AE0B1C2F8327`).
  - 이미 부트로더 상태라 1200bps 리셋 없이 직접 전송(보드 가이드 §10): `-DSOLDIER_ID=1`로 `--output-dir` 컴파일 → `adafruit-nrfutil --verbose dfu serial -pkg SoldierNode.ino.zip -p /dev/cu.usbmodem101 -b 115200 --singlebank`
  - 출력: `application size: 135832` … `Activating new firmware` … `Device programmed.`, exit 0 (`Touch disabled`).
- **BLE 시험은 이 세션에서 실행 불가**: Claude 앱 안에서 bleak를 실행하면 exit 134(SIGABRT). macOS가 Bluetooth 권한 없는 프로세스를 종료시키는 동작. 시스템 보안 설정이므로 바꾸지 않음 → **mock_leader는 사용자가 macOS 터미널(Terminal.app)에서 실행**(첫 실행 때 Bluetooth 권한 허용).
- **보드 2 / ID 2 업로드 성공**: 사용자가 RESET 두 번 → `NRF52BOOT`, `/dev/cu.usbmodem1101`(Product "PCA10056", 시리얼 `F2408DEA04B8AC33`). ID 2 이미지가 ID 1과 다름 확인 후 부트로더 포트로 직접 전송 → `application size: 135832` … `Device programmed.`, exit 0.
- 사용자 관찰: 단계 2 펌웨어 실행 중에는 USB 시리얼 포트가 보이지 않는 것 같음 → 업로드는 아래 표준 절차로 고정(사용자 지시).

### 보드 식별 (USB 시리얼 번호)
| 보드 | USB 시리얼 | 펌웨어 |
|---|---|---|
| 보드 1 | `7658AE0B1C2F8327` | 단계 2, SOLDIER_ID=1 |
| 보드 2 | `F2408DEA04B8AC33` | 단계 2, SOLDIER_ID=2 |
(※ 2026-10-10 역할 변경 → 아래 "보드 역할과 시리얼 번호" 표가 최신)

---

## 표준 업로드 절차 (2026-10-10 사용자 지시, 이후 모든 업로드의 기본)

1. 업로드 전에 사용자에게 확인을 받는다(CLAUDE.md §2-4).
2. **사용자에게 "보드를 USB에 꽂고 RESET을 빠르게 두 번 눌러 NRF52BOOT 상태로 만들어 달라"고 먼저 요청**한다(실행 중 펌웨어는 USB 시리얼 포트가 안 보일 수 있음).
   - (2026-10-10 추가) 그 전에 **`earpiece.py`·비콘 포트를 연 `mock_leader`를 종료**해 달라고 요청한다(같은 이름의 부트로더 포트를 열어 nrfutil이 `No data received on serial port`로 실패한 적 있음). earpiece.py는 NRF52BOOT가 보이면 포트를 열지 않게 고쳤지만 이전 실행분은 해당 없음.
   - 성공 판정은 반드시 출력의 `Device programmed.`로 한다(nrfutil은 실패해도 exit 0일 수 있음).
3. 부트로더 포트를 새로 찾는다(포트 이름은 매번 바뀔 수 있음: 지금까지 `usbmodem101`, `usbmodem1101`).
   ```bash
   ls /dev/cu.usbmodem*; ls -d /Volumes/NRF52BOOT
   ioreg -p IOUSB -l -w0 | grep -E '"USB Serial Number"|"USB Product Name"'   # 보드 구분(위 표)
   ```
4. 해당 ID로 컴파일해 DFU zip을 만든다(`--output-dir`로 ID별 폴더에 저장 → 다른 ID 빌드와 섞이지 않음).
   ```bash
   CLI="/Applications/Arduino IDE.app/Contents/Resources/app/lib/backend/resources/arduino-cli"
   "$CLI" --config-file ~/.arduinoIDE/arduino-cli.yaml compile --fqbn nucode:nrf52:nu40dk \
     --build-property "compiler.cpp.extra_flags=-DSOLDIER_ID=<ID>" --output-dir <출력폴더>/s<ID> firmware/SoldierNode
   ```
5. **1200bps 리셋 없이** 부트로더 포트로 직접 전송(보드 가이드 §10 DFU 설정: 115200, flow control off, single bank).
   ```bash
   NRF=~/Library/Arduino15/packages/nucode/hardware/nrf52/1.0.2/tools/adafruit-nrfutil/macos/adafruit-nrfutil
   "$NRF" --verbose dfu serial -pkg <출력폴더>/s<ID>/SoldierNode.ino.zip -p /dev/cu.usbmodem<번호> -b 115200 --singlebank
   ```
6. 성공 판정: 출력에 `Device programmed.`가 있고 `Failed to upgrade target`이 없을 것.
- `arduino-cli upload`는 1200bps 터치 리셋을 먼저 하므로 이 절차에서는 쓰지 않는다.

### 장비 시험 결과 (사용자가 Terminal.app에서 실행, 2026-10-10) — ✅ 완료 조건 충족
- `python3 tools/mock_leader.py --only S1,S2`: **S1·S2 동시 연결**, 둘 다 `MTU=247 (최대 244B)`.
  - S1: `boot id=1 heading_mode=1 emcon_boot=2 …` / `conn #1` / `mtu=247 max_write=244`
  - S2: `boot id=2 heading_mode=1 emcon_boot=2 up=6036ms` / `conn #1` / `mtu=247 max_write=244`
  - 16:49:33 S1 끊김 → 재연결: 사용자가 보드 1을 충전기로 옮긴 시점(재연결 후 `up=4634ms` = 재부팅).
  - 연결 ID와 src_id 불일치 경고 없음.
- `stats all` → 한 프레임 `01 1F 00 00 03 00`을 두 연결에 write → S1·S2 각각 `rx type=1F seq=0 src=0 dst=03 plen=0` LOG + `STATS … EMCON0 0프레임/0B, EMCON1 0프레임/0B, EMCON2 0프레임/0B`.
- `stats 2` → `01 1F 01 00 02 00`, S2만 응답(`dst=02`).
- LED(사용자 확인): 두 보드 모두 **LED1만 켜짐**(연결 상태), LED2~4 꺼짐 → leds 초기화와 autoConnLed(false) 정상.
- `raw 1 01 1F 07 00 02 00`(dst가 S2 → S1 폐기 기대 `rx drop err=-6`) 결과는 아직 받지 못함.

### 발견된 문제 (미수정)
- S1 재연결 때 LOG 순서가 `mtu → boot → conn`이고, 이어서 나가야 할 두 번째 `mtu` LOG가 빠짐(다음 LOG가 seq=3 → 그 프레임은 송신 실패해 seq를 쓰지 않음).
  - 원인(코드 분석, 추정): BLEUart의 Notify 켜짐 콜백은 지연 실행이라 `radio_can_send()`가 이벤트보다 먼저 참이 됨 → MTU LOG가 먼저 나감. 이어 4개를 연달아 보내다 HVN 큐(`BANDWIDTH_MAX`의 hvn_qsize 3)가 차서 마지막 notify가 대기 시간 초과로 실패, 조용히 버려짐.
  - 수정안: (1) NOTIFY_ON 이벤트 처리 후에만 MTU LOG, (2) `configPrphConn(247, 100, 8, …)`로 HVN 큐 8칸, (3) 송신 실패 수를 세어 다음 `conn` LOG에 표시. 두 보드 재업로드 필요 → 사용자 결정 대기.

### 단계 2 후속: LOG 누락 수정 (2026-10-10, 컴파일만 — 업로드는 단계 3과 함께)
- MTU LOG는 NOTIFY_ON 이벤트를 처리한 뒤에만(`s_notify_ready`) → 순서 `boot → conn → mtu` 고정.
- Notify 송신 큐: `configPrphConn(247, 100, BLE_HVN_QUEUE_SIZE=8, 기본)` (BANDWIDTH_MAX와 같되 hvn 3 → 8).
  - SoftDevice RAM이 부족하면 `Bluefruit.begin` 실패 → LED4 빠른 점멸(200ms)로 보인다(시험 항목).
- 송신 실패 수: 연결·Notify가 있는데 notify가 실패한 경우만 셈. 다음 LOG 앞에 `[tx_fail +N]`, 재연결 `conn` LOG에 누적 `tx_fail=`.
  - **STATS에는 넣지 않음**: 프로토콜 §5.1 STATS는 tx_frames×3 + tx_bytes×3 고정 18바이트로 실패 수 필드가 없다 → LOG로만.

---

## 단계 3 — 입력(버튼·조이스틱) + 보고 송신 (2026-10-10) ✅ 완료

### 구현
- `core/gesture` (**신규, CLAUDE.md §4 목록 밖 추가**: 타이밍 판정을 호스트에서 시험하려고 core에 둠)
  - MULTI(버튼1 연타, 마지막 해제 후 1200ms 확정), SDL(버튼2/4: 짧게 400ms 지연 확정, 두 번 = 해제 후 400ms 안에 재입력 → 두 번째 눌림 순간 확정, 길게 = 누른 채 1000/2000ms 도달 순간), SL(버튼3/조이스틱 SW: 지연 없음). 600ms~길게 사이 = IGNORED.
  - `gest_cancel`: 버튼1+버튼4 동시 눌림 시 두 제스처 취소(버튼4 2초 본인 부상 오발 방지).
- `core/geo`에 `geo_joy_direction()`: 반전(X/Y) → +dy = 12시, +dx = 3시 → 회전 → 시계, 기울기 % (축별 최대 거리로 정규화, 100% 상한), 35% 미만 없음 / 35~75% 근거리 / 75% 이상 원거리.
- 호스트 테스트 `test_input`(76 checks): 짧게/두 번/간격 초과/길게(1s·2s)/IGNORED/SL/연타 3·7회/누른 채 미확정/취소/같은 틱 취소, 조이스틱 방향·경계·모서리·반전·회전·축별 정규화. **`make -C tests/host` 전부 통과**(5개 테스트 546 checks).
- `hal/buttons`: 디바운스 20ms(raw가 20ms 안정되면 반영) → 조합 검사 → 제스처 → 이벤트 링 버퍼. `HAS_JOYSTICK=0`이면 SW 핀은 pinMode도 하지 않음.
- `hal/joystick`: `analogReference(AR_VDD4)`(0~VDD 전체), 10bit, 10ms 주기. 부팅 후 200ms 평균 = 중앙값, 축별 최대 거리는 커지기만 함(기본 512). **`HAS_JOYSTICK=0`이면 아날로그를 전혀 읽지 않음**(ID 2 빌드에 `analogRead` 심볼 자체가 없음을 확인).
- `hal/heading`: FIXED → `HEADING_FIXED_DEG`(0), NONE/SENSOR(스텁) → 0xFFFF.
- `hal/leds`: `leds_pulse()` 추가(LED3 송신 순간 100ms). LED4 = 모드(0 꺼짐, 1 느린 점멸 1s, 2 켜짐).
- `app/app`: 입력 → 동작(프로토콜 §9.1), 조이스틱 방향은 **제스처의 첫 눌림 순간** 값으로 고정(버튼1 연타면 첫 번째 누름). 조이스틱 길게 → EMCON 0→1→2→0(1/2 진입 시 EMCON_STATE). 진단 LOG `JOY x= y= sw= c= dx= dy= m= clk= pct=` 0.5초마다(`JOY_DIAG_LOG`).
  - EMCON 전환은 **보고 송신 규칙만** 바뀐다. 무선 쪽(연결 끊기·수동 스캔·송신 출력)은 F6 단계 → 지금은 EMCON 0에서도 연결과 LOG는 유지(시험용).
- `app/reporter`: 보고 프레임(azimuth = (heading + (clock−12)×30) mod 360, clock 0이면 0xFFFF, dist 없음 0xFF), EMCON 0 큐 / 1 긴급·ACK류 즉시 + 나머지 30초 일괄 / 2 즉시, 연결 없으면 큐 → Notify 켜지면 오래된 순서로 송신(한 루프에 하나씩), 긴급은 송신 후 RPT_ACK 대기(최대 8건) → 3초마다 같은 seq 재전송 최대 3회 → 포기 LOG. RPT_ACK 수신 시 `FEEDBACK: received`.
- `app/commands`: RPT_ACK → reporter. CMD_BUTTON은 **"마지막 명령"(0x10, seq)만 기록**(버튼3 ACK/CANNOT_COMPLY와 조이스틱 다시 듣기 시험용, 재생·LED2는 이후 단계).
- 로컬 피드백(오디오 전): LOG `FEEDBACK: n1`~`n4`/`many`, `enemy sent`, `suspicious sent`, `hazard sent`, `casualty sent`, `sent`, `mode_silent|mode_min|mode_normal`, `received`, `err (no last command)`, `calib_start …`.
- `config.h`: `HAS_JOYSTICK`(기본: ID 1 → 1, 그 외 0, `-DHAS_JOYSTICK=`로 덮어쓰기), `JOY_DIAG_LOG`(기본 1), `JOY_SW_PRESSED_LEVEL LOW`(TODO_CONFIRM), `BLE_HVN_QUEUE_SIZE`, `RPT_PENDING_MAX`, LED 상수.
- `tools/mock_leader.py`: 보고(0x01~0x0B) 수신 시 **RPT_ACK 자동 송신**, `ack on|off`, 같은 (병사, seq) 재수신 → `↻ 재전송(같은 seq)`, 긴급 → `★긴급`. 가짜 bleak로 오프라인 확인.
- 컴파일: ID 1 **144,584B(17%) / 21,052B(8%)**, ID 2 **142,136B / 20,996B**(조이스틱 코드 제외), 경고 `USE_TINYUSB`만.

### 조이스틱 진단 절차 (ID 1, `JOY_DIAG_LOG=1` 빌드)
1. 부팅할 때(전원/RESET 직후 0.2초) 조이스틱을 건드리지 않는다 → 중앙값 보정.
2. `python3 tools/mock_leader.py --only S1` → 0.5초마다 `LOG "JOY x=… y=… sw=… c=cx,cy dx=… dy=… m=…,… clk=… pct=…"`.
3. 총을 겨누는 자세 기준으로 다음 5가지 상태의 `x, y, sw`를 기록:
   ① 중앙(손 뗌) ② 총구 쪽(앞)으로 끝까지 ③ 오른쪽 끝 ④ 뒤쪽 끝 ⑤ 왼쪽 끝 + ⑥ SW 누름(sw 값 변화)
4. 결과로 `JOY_INVERT_X/Y`, `JOY_ROTATE_DEG`, `JOY_SW_PRESSED_LEVEL`을 정하고 `JOY_DIAG_LOG=0`으로 다시 빌드·업로드 → 아래 체크리스트.

### 프로토콜 §9.1 입력 시험 체크리스트 (업로드·방향 확정 후, mock_leader `--only S1,S2`, 시작 모드 2, heading FIXED 0)
공통 기대: 보고가 나갈 때 **LED3 짧게 깜빡임**, `LOG "tx <종류> seq=… sent"` + `FEEDBACK: …`, mock_leader가 RPT_ACK 자동 응답 → 긴급이면 `LOG "rpt_ack seq=… ok"` + `FEEDBACK: received`.
azimuth(heading 0) = 시계×30 (12시 = 0, 3시 = 90, 9시 = 270).

| # | 보드 | 입력 | 기대 결과 |
|---|---|---|---|
| 1 | S1 | 조이스틱 오른쪽 반쯤 + 버튼1 3번 | 누를 때마다 `FEEDBACK: n1/n2/n3`, 마지막 누름 1.2초 뒤 `CONTACT 적 3, 방위 90°, 3시, 근거리 ★긴급` |
| 2 | S1 | 조이스틱 앞 끝 + 버튼1 6번 | `n1…n4, many, many` → `CONTACT 적 다수, 방위 0°, 12시, 원거리` (count 5) |
| 3 | S1/S2 | 조이스틱 손 뗌 + 버튼1 1번 | `CONTACT 적 1, 방위 없음, 시계 없음, 거리없음` (S2는 항상 이 형태) |
| 4 | S1 | 왼쪽 + 버튼2 짧게 | 약 0.4초 뒤 `SUSPICIOUS 방위 270°, 9시` (긴급 아님) |
| 5 | S1 | 뒤쪽 + 버튼2 두 번 | 두 번째 누름 즉시 `CASUALTY_FOUND 방위 180°, 6시, 근/원거리 ★긴급` |
| 6 | S1 | 앞 + 버튼2 길게(1초) | 누른 채 1초에 `HAZARD 방위 0°, 12시 ★긴급` |
| 7 | 둘 다 | 버튼2를 0.6~1초 누르고 뗌 | 보고 없음, `LOG "input: btn2 ignored …"` |
| 8 | 둘 다 | 명령 받기 전 버튼3 짧게 | 송신 없음, `FEEDBACK: err (no last command)` |
| 9 | S1 | `raw 1 01 10 05 00 01 06 01 FF FF FF 00 00`(HALT) 후 버튼3 짧게 | `LOG "cmd code=01 seq=5 …"` → `ACK 대상 버튼 명령 seq 5` |
| 10 | S1 | 이어서 버튼3 길게(1초) | `CANNOT_COMPLY 대상 버튼 명령 seq 5` |
| 11 | 둘 다 | 버튼4 짧게 | 약 0.4초 뒤 `OK_READY` |
| 12 | 둘 다 | 버튼4 두 번 | `WEAPON_AMMO ★긴급` |
| 13 | 둘 다 | 버튼4 길게(2초) | 누른 채 2초에 `CASUALTY_SELF heading 0 ★긴급` (1~2초 사이에 떼면 ignored) |
| 14 | S1 | 조이스틱 SW 짧게 (#9 전/후) | 전: `FEEDBACK: err …` / 후: `FEEDBACK: replay cmd code=01 seq=5 …` (송신 없음) |
| 15 | S1 | 조이스틱 SW 길게(1초) ×3 | 2→0: `mode_silent`, LED4 꺼짐 / 0→1: `mode_min`, LED4 느린 점멸, `EMCON_STATE 모드 1` / 1→2: `mode_normal`, LED4 켜짐, `EMCON_STATE 모드 2` |
| 16 | 둘 다 | 버튼1+버튼4 3초 | `LOG "input: btn1+btn4 combo start …"` → 3초에 `FEEDBACK: calib_start (… no-op)`, **CONTACT·CASUALTY_SELF 없음** |
| 17 | S1 | EMCON 0에서 버튼4 짧게, 버튼2 길게 | `tx … queued(emcon0)`, 분대장 쪽 수신 없음 → SW 길게로 1 진입 시 오래된 순서로 OK_READY, HAZARD, EMCON_STATE 수신 |
| 18 | S1 | EMCON 1에서 버튼4 짧게 / 버튼4 두 번 | OK_READY는 `queued` → 30초 안에 일괄 송신 / WEAPON_AMMO는 즉시 |
| 19 | 둘 다 | `ack off` 후 버튼4 길게 | CASUALTY_SELF 수신 → 3초 간격으로 `↻ 재전송` 3번, 병사 `LOG "retx … #1~#3"` → `no RPT_ACK … give up`. `ack on` 후 다시 → 재전송 없음 |
| 20 | S2 | 모든 버튼 | 보고는 항상 방향 없음(clock 0, 방위 없음), JOY LOG 없음, 조이스틱 SW 기능 없음 |
| 21 | 둘 다 | mock_leader 재시작(재연결) | LOG 순서 `conn #n … tx_fail=…` → `mtu=…` (빠짐 없음), LED1 켜짐, LED4 = 현재 모드 |

### 보드 역할과 시리얼 번호 (2026-10-10 갱신, 최신)
| 보드 | USB 시리얼 | 역할 | 하드웨어 | 현재 펌웨어 |
|---|---|---|---|---|
| 새 보드(신규 구매) | `991886332446329E` | **ID 1** | 조이스틱 납땜(GND, VRx=P0.03, VRy=P0.04, SW=P0.28, +5V 핀 → 3V3) | 단계 7(ID 1) |
| 기존 보드 A | `7658AE0B1C2F8327` | **분대장 비콘**(침묵 모드 방송) | 조이스틱 없음 | LeaderBeacon (USB hex 방송 + 버튼 4개) |
| 기존 보드 B | `F2408DEA04B8AC33` | **ID 2** (사용자 동의 2026-10-10) | 조이스틱 없음 | 단계 7(ID 2, HAS_JOYSTICK=0) |
- 기존 보드 둘 다 지금 BLE 이름이 각각 `SQ1-S1`, `SQ1-S2`로 광고 중일 수 있다. 새 보드(ID 1)와 이름이 겹치지 않도록 **기존 보드 A는 전원을 끄거나 ID 2/예비 펌웨어로 바꿀 때까지 꺼 둘 것.**
- 새 보드 부트로더: `UF2 Bootloader 0.9.1`, Board-ID `nRF52840-pca10056-v1`, `SoftDevice: S140 6.1.1`(코어 링커 스크립트 `nrf52840_s140_v6.ld`와 일치).

### 업로드 기록: 새 보드 / ID 1 진단 빌드 (2026-10-10)
- 표준 절차: 사용자 RESET 두 번 → `/dev/cu.usbmodem101`(시리얼 `991886332446329E`) → `-DSOLDIER_ID=1` 컴파일(144,584B / 21,052B) → nrfutil 직접 전송 → `Device programmed.`, exit 0.
- 사용자 확인 대기: LED4 빠른 점멸 여부(BLE 초기화 실패 표시), LED 극성(LOW = 켜짐), 조이스틱 진단 값.

### 조이스틱 진단 결과와 반영 (2026-10-10, ID 1 = 새 보드 `991886332446329E`)
- 사용자 측정(앞 = 총구, 사용자가 정한 장착 기준):

  | 상태 | x | y | sw | 진단 빌드 판정 |
  |---|---|---|---|---|
  | 중앙 | 535~538 | 533~536 | 0 | 보정 중앙값 c=537,534, 흔들림 ±2 |
  | 앞 끝 | 1021 | 535 | 0 | clk=3 (틀림) |
  | 오른쪽 끝 | 536 | 1021~1022 | 0 | clk=12 (틀림) |
  | 뒤 끝 | 0 | 534 | 0 | clk=9 (틀림) |
  | 왼쪽 끝 | 537 | 0 | 0 | clk=6 (틀림) |
  | SW 누름 | 536 | 533 | **1** | — |
- 해석: 원시 +X = 앞, +Y = 오른쪽. 진단 빌드 규칙(+Y = 12시, +X = 3시)과 **거울 관계**(회전으로는 안 맞음) → **`JOY_SWAP_XY = 1`**(교환만), `JOY_INVERT_X/Y = 0`, `JOY_ROTATE_DEG = 0`. 교환 후: 앞 12시 / 오른쪽 3시 / 뒤 6시 / 왼쪽 9시.
- `JOY_SW_PRESSED_LEVEL = LOW` 확인(sw=1 = 눌림 레벨과 같음).
- **방향별 정규화**(사용자 요청): 중앙에서 +쪽 거리 ≈ 484~486, −쪽 ≈ 534~537로 비대칭 → 최대 거리를 축·방향별 4개(`+X/−X/+Y/−Y`)로 두고, 보정 때 **중앙값에서 ADC 끝(1023 / 0)까지 거리**로 초기화(그보다 멀리 가면 늘어남). CLAUDE.md §6.1의 "기본 512"를 이것으로 대체.
- 호스트 테스트 `test_joy_measured`: 위 실측값을 HAL과 같은 방식으로 계산 → 앞 12 / 오른쪽 3 / 뒤 6 / 왼쪽 9시 모두 원거리, 끝까지 = 100%, 중앙 흔들림 = 방향 없음, 앞-오른쪽 대각 = 2시. `make -C tests/host` 전부 통과(test_input 90 checks).
- `JOY_DIAG_LOG = 0`(진단 끔). 진단 LOG 형식은 `mx=+…/-… my=+…/-…`로 바뀜(다시 켤 때 참고).
- LED(사용자 관찰, 진단 빌드): LED4 빠른 점멸 없음 → HVN 큐 8에서도 BLE 초기화 정상. LED1·LED4 켜짐, LED2·LED3 꺼짐 → mock_leader 연결(LED1) + EMCON 2(LED4)로 기대와 같음 → **새 보드도 LED 극성 LOW = 켜짐**(꺼져야 할 LED2·3이 꺼져 있음).
- 최종 빌드 컴파일: ID 1 **144,396B / 21,052B**, ID 2 **142,136B / 20,996B**, 경고 `USE_TINYUSB`만. 업로드 대기(보드 1 → 보드 2).

### 업로드 기록: 단계 3 최종 빌드
- 보드 1(새 보드, `991886332446329E`) / ID 1: RESET 두 번 → `/dev/cu.usbmodem101` → nrfutil 직접 전송 → `Device programmed.`, exit 0 (144,396B, JOY_DIAG_LOG=0).
- 보드 B(`F2408DEA04B8AC33`) / ID 2: RESET 두 번 → `/dev/cu.usbmodem1101` → nrfutil 직접 전송 → `Device programmed.`, exit 0 (142,136B, HAS_JOYSTICK=0).
- 다음: §9.1 체크리스트 장비 시험(사용자, Terminal.app).

### 단계 3 장비 시험 결과 (사용자 보고, 2026-10-10) — ✅ 완료
- 터미널 출력 원문은 사용자 메시지에 자리표시만 있고 실제로 붙지 않음 → 아래는 **사용자가 보고한 판정**을 그대로 기록.
- 통과: 적 발견(12/3/6시, 근거리·원거리, 방향 없음, 다수), 징후·부상자·폭발물 방향, 버튼4 3종과 애매한 길이 무시, 명령 없을 때 오류, ACK/수행 불가/다시 듣기, 조합 입력 오발 없음, 모드 순환, 모드 0 큐 저장 → 모드 1 전환 시 오래된 순서로 일괄 송신, 긴급 보고 재전송 3회 후 포기, 보드 2(방향 없는 보고).
- 모드 1 묶음 송신: 18:42:53 모드 1 진입 → 18:43:05 OK_READY queued → 18:43:23(진입 후 정확히 30초) 일괄 송신. 통과.
- LED: LED3 송신 시 깜빡임 정상, LED4 모드 표시 정상.
- 수정 요청: LOG에 한글이 섞여 깨짐(예: `cmd code=01 seq=1 ��� last command`) → 단계 4에서 반영(아래).

---

## 단계 4 — 버튼 명령 수신 (2026-10-10) ✅ 완료(30초 타이머 버그는 수정 후 재업로드 대기)

### 구현
- **LOG ASCII 전용**: 펌웨어의 한글/기호(→) 문자열 리터럴을 모두 영문 ASCII로 교체. `tests/host/check_ascii.py`(주석은 건너뛰고 문자열 리터럴만 검사)를 `make -C tests/host`의 `ascii-check`로 추가 → 다시 섞이면 빌드 실패.
- `app/phrases`(Arduino 비의존, 호스트 테스트): 프로토콜 §6.2 템플릿 → 조각 ID 시퀀스. 방향 = `geo_clock_from(azimuth, 내 heading)` → `c1`~`c12`, 거리 `near/mid/far`, 적 수 `n1~n4/many/unknown`.
  - 방향 선택형(엄폐·전진·후퇴)은 azimuth 없으면 방향 없이, 필수형(사격 개시·경계·적 위치)은 방향 없이 재생 + `(no dir)` LOG.
  - RALLY는 명령의 azimuth를 쓰지 않고 POS_TABLE의 분대장 방향을 쓴다 → POS_TABLE은 F8 단계라 지금은 `rally`만 + `(no POS_TABLE: no dir)`.
- `app/commands`:
  - 검증 = core/frame(ver, len, dst_mask) + **src_id = 0(분대장)만 수용**.
  - CMD_BUTTON: dedup(최근 16개 (src, seq)) → 중복이면 `cmd dup seq=… : replay only` + `PLAY: … (dup)`(새 명령 아님, 마지막 명령·LED2 그대로). 새 명령이면 `cmd <이름> seq= az= dist= extra= prio=` + `PLAY: <조각들>`(긴급이면 ` (urgent)`), 마지막 명령 = (0x10, seq, 조각 시퀀스), LED2 미확인 점멸 500ms → 30초 후 150ms(`unacked 30s` LOG).
  - 버튼3 짧게/길게 → ACK/CANNOT_COMPLY(마지막 명령 기준) 송신 + LED2 끔. 조이스틱 짧게 → `PLAY: … (replay)`.
  - EMCON_SET(0x16) → `emcon_set mode=n stored; radio switch is F6`, SILENCE(cmd 0x0B) → 재생·ACK 대상 + `emcon request 0 (SILENCE) stored`. **요청 모드 값만 저장**(`commands_requested_mode()`), 보고 규칙·LED4·무선은 바꾸지 않음(F6 단계).
- 호스트 테스트 `test_phrases`(32 checks): §11.1 예시 2개(`c9 cover`, `enemy n3 c2 far`), 내 방위에 따른 변환, 선택/필수 방향, 적 수, RALLY, 방향 없는 명령, 알 수 없는 코드, join 잘림. **전체 6개 테스트 + C99 + ASCII 검사 통과.**
- 컴파일: ID 1 **147,224B(18%) / 21,128B**, ID 2 **144,964B / 21,072B**, 경고 `USE_TINYUSB`만.
- `tools/mock_leader.py`: `cmd <name|code> [az] [dist] [extra] [prio] [targets]`('-' = 기본값). targets `all`(dst 0x1F, §11.1과 같음) | `1` | `2` | `1,2`(dst = 비트 합). 대상별 ACK/수행 불가 수집 → `▶ cmd seq=… TAKE_COVER: S1 수신, S2 미수신`, 전원 응답 시 `✔`, 15초 안에 ACK 없는 대상에만 **같은 바이트(같은 seq)**로 1회 재전송(`⏱`), 그 뒤 15초에도 없으면 `✖ … 미수신`. 가짜 bleak 오프라인 확인(시간 제한 0.3초로 줄여서).

### 시험 절차 (업로드 후, `python3 tools/mock_leader.py --only S1,S2`, heading FIXED 0)
| # | 입력 | 기대 결과 |
|---|---|---|
| 1 | §11.1 예시 1: `raw all 01 10 05 00 1F 06 02 0E 01 FF 00 01` | S1·S2 모두 `cmd TAKE_COVER seq=5 az=270 dist=255 extra=0 prio=1` + `PLAY: c9 cover (urgent)`, 두 보드 LED2 500ms 점멸 |
| 2 | 같은 줄 한 번 더 | 두 보드 `cmd dup seq=5 TAKE_COVER: replay only` + `PLAY: c9 cover (dup)` |
| 3 | 각 보드 버튼3 짧게 | `ACK 대상 버튼 명령 seq 5`, 해당 보드 LED2 꺼짐 (raw는 mock이 ACK 집계를 하지 않음) |
| 4 | §11.1 예시 2: `raw all 01 10 06 00 01 06 09 2D 00 02 03 00` (dst 0x01) | S1: `cmd ENEMY_INFO …` + `PLAY: enemy n3 c2 far`. S2: `rx drop err=-6` (재생 없음) |
| 5 | §11.1 예시 3: `raw 1 01 1F 07 00 01 00` | S1 STATS 응답 |
| 6 | 1만: `cmd halt - - - - 1` | S1만 `PLAY: halt`, mock `▶ … HALT: S1 미수신` → S1 버튼3 짧게 → `S1 수신`, `✔ 전원 응답` |
| 7 | 2만: `cmd observe 90 - - - 2` | S2만 `PLAY: c3 observe` → S2 버튼3 **길게** → `S2 수행 불가` |
| 8 | 전원: `cmd take_cover 270 - - 1 all` 후 S1만 ACK | `S1 수신, S2 미수신` → 15초 뒤 `⏱ … S2` 재전송 → S2 `cmd dup … replay only`(같은 seq) → S2 ACK면 `✔`, 아니면 15초 뒤 `✖ … S2 미수신` |
| 9 | 미확인 30초: #8에서 S2를 ACK 하지 않고 기다림 | 30초 뒤 S2 `unacked 30s` + LED2 빠른 점멸(150ms) |
| 10 | 다시 듣기: S1 조이스틱 짧게 | `PLAY: <마지막 명령> (replay)`, 송신 없음 |
| 11 | 방향·거리: `cmd open_fire 330 mid - - 1`, `cmd open_fire - - - - 1`, `cmd enemy_info 180 near 7 - 1`, `cmd rally - - - - all` | `PLAY: c11 mid open_fire` / `PLAY: open_fire` + `(no dir)` / `PLAY: enemy many c6 near` / `PLAY: rally` + `(no POS_TABLE: no dir)` |
| 12 | 모드 값: `raw all 01 16 63 00 1F 01 01`(EMCON_SET 1), `cmd silence - - - - all` | `emcon_set mode=1 stored …`, `PLAY: silence` + `emcon request 0 (SILENCE) stored …`, LED4·보고 규칙은 그대로 |
| 13 | LOG ASCII | 위 모든 LOG에 깨진 문자 없음 |
- 참고: `raw`로 seq 5/6/7/0x63을 직접 넣으면 mock의 자체 seq와 겹칠 수 있다. 겹치면 병사는 중복으로 처리(#2와 같은 동작)하므로, raw 예시는 병사 재부팅 직후 먼저 시험한다.
- 사용자 확인: EMCON_SET/SILENCE "요청 모드 값만 저장", RALLY "방향 없음(POS_TABLE 전)" 해석 그대로 채택.
- 업로드: 새 보드(`991886332446329E`) / ID 1 → `/dev/cu.usbmodem101`, nrfutil 직접 전송 → `Device programmed.`, exit 0 (147,224B).
- 업로드: 보드 B(`F2408DEA04B8AC33`) / ID 2 → `/dev/cu.usbmodem1101`, nrfutil 직접 전송 → `Device programmed.`, exit 0 (144,964B). 다음: 단계 4 시험 절차(사용자, Terminal.app).

### 단계 4 장비 시험 결과 (2026-10-10, 사용자 실행 터미널 출력 확인)
- 통과: 대상 지정 전원(dst 1F)/1만(01)/2만(02), 비대상 `rx drop err=-6`, PLAY `c9 cover`·`c6 withdraw`·`c3 cover`·`enemy n3 c2 far`·`c11 mid open_fire`·`halt`·`cease_fire`, ACK/CANNOT_COMPLY, `cmd` 대상별 집계(`S1 수신, S2 수신` → `✔`), 15초 재전송(같은 seq 0A) → S2 `cmd dup seq=10 … replay only` → `✖ … S2 미수신` → 늦은 ACK(19:05:05) 반영, 다시 듣기 `PLAY: c3 cover (replay)`, EMCON_SET `emcon_set mode=1 stored`, STATS, LOG ASCII(깨짐 없음).
- 미시험(호스트 테스트로 대신): raw 중복 재전송, open_fire 방향 없음, enemy many, rally, silence.
- **버그: `unacked 30s`가 새 명령 직후 즉시 발동**(S1 seq 5/6/64/7, S2 65/66/7/10; 정상은 S2 seq 5 → 30초 뒤).
  - 원인: `app_loop()`가 맨 앞에서 `now = millis()`를 읽고, 그 뒤 프레임 처리 중 `set_unacked()`가 `millis()`(몇 ms 늦음)로 시작 시각을 기록 → 같은 루프의 `commands_loop(now)`에서 `(uint32_t)(now - since)`가 음수 → 부호 없는 값으로 감겨 30000 이상 → 즉시 발동. millis가 그 사이에 바뀐 경우만 생겨서 간헐적.
  - 수정: 타이머를 `core/unack`(Arduino 비의존)로 분리, **부호 있는 경과 시간**(`(int32_t)(now - since)`) 사용, 새 명령마다 시작 시각·빠른 점멸 상태 초기화. 같은 종류 위험이 있던 `leds` 점멸 위상 계산도 부호 있는 경과로 수정.
  - 검증: `tests/host/test_unack.cpp`(21 checks) — 수정 전 계산식으로 즉시 발동이 재현되고(start 1003, now 1000), 수정 후에는 발동 안 함, 정확히 30초에 1회, 다음 명령에서 상태 초기화, ACK 후 미발동, 30초 안에 새 명령 시 재시작, millis 오버플로 근처까지 확인.

---

## 계획 변경 (2026-10-10): 단계 5·6 — 이어폰 단말을 맥으로 대체 ✅ 완료(dedup 수정은 재업로드 대기)

### 결정 사항
- **CLAUDE.md §6.4 PWM 오디오 출력(hal/audio_out): 설계만, 하드웨어 미제작.** `hal/audio_out`은 빈 구현(AUDIO_SINK=PWM일 때만 링크). 설계 메모(NRF_PWM3, 16MHz/250, REFRESH 7 → 8kHz, 이중 버퍼 256샘플)는 `audio_out.h` 주석에 유지.
- **오디오 출력 통로(audio sink)** `hal/audio_sink`: 문장 조각 재생·로컬 피드백·수신 음성 재생이 모두 이것만 호출. `config.h`의 `AUDIO_SINK` = `USB_EARPIECE`(지금) / `PWM`(빈 구현) / `NONE`. commands·voice_rx·phrases·app은 통로를 모른다 → PWM으로 바꿀 때 호출 코드 수정 없음.
  - 사용자가 말한 "EARPIECE_RELAY"는 USB 경로로 구체화해 `AUDIO_SINK_USB_EARPIECE`로 이름 붙임. 2순위(BLE 2연결) 통로는 USB가 안 될 때만 추가 예정(`AUDIO_SINK_BLE_EARPIECE` 자리).
- **재생 내용을 노트북으로 넘기는 방법 = USB 시리얼(1순위)**: BLE 프로토콜에 새 메시지가 필요 없다 → **분대장 팀원에게 전달할 변경 없음**(0x7F LOG는 여전히 디버그 전용, 무시하면 됨). DEBUG_LOG와 무관하게 항상 USB로 나간다.
  - 2순위(BLE 2연결)로 가게 되면 그때 예약 타입(예: 0x7E EARPIECE, 병사 → 이어폰 단말 전용, 분대장 측은 무시)을 제안할 것.
- 사용자 요청의 `mock_leader --earpiece S1`(분대장 BLE 연결로 재생 이벤트 전달)은 B) 조건(시연 때 분대장은 다른 컴퓨터) 때문에 **USB 경로의 `tools/earpiece.py`로 대체**. mock_leader는 분대장 역할만 한다.
  - 단계 6의 "VOICE_RESULT 0이면 mock_leader가 원본 WAV 재생"도 같은 이유로 **병사가 CRC 검증한 ADPCM을 USB로 넘겨 earpiece.py가 디코딩·재생**하는 방식으로 대체(실제 병사가 받은 소리를 듣게 됨).
- **macOS 한국어 음성**(`say -v '?'`): `Yuna`(기본으로 사용), `Eddy`, `Flo`, `Grandma`, `Grandpa`, `Reed`, `Rocko`, `Sandy`, `Shelley`.

### USB Serial 진단 (1단계: 컴파일·링크)
- `firmware/diag/UsbSerialDiag/`: LED1 0.5초 점멸, 0.5초마다 `diag n= up= dtr= afw= skipped=` 한 줄, 호스트가 안 열었거나 송신 버퍼가 부족하면 건너뜀(블로킹 없음), 받은 바이트 되돌려 보냄, LED2 = DTR(호스트가 포트를 열었음).
- 첫 컴파일: **`undefined reference to 'Serial'`, `Adafruit_USBD_CDC::begin(...)` 등 링크 오류** = 보드 가이드가 말한 "USB Serial 링크 오류". 원인: `Serial`(SerialTinyUSB)은 Adafruit TinyUSB **라이브러리** 안에 있는데, 스케치가 그 헤더를 포함하지 않으면 arduino-cli가 라이브러리를 링크하지 않는다.
- `#include <Adafruit_TinyUSB.h>` 추가 → **컴파일·링크 성공** 54,324B(6%) / 8,772B.
- 참고: 단계 2 이후 펌웨어 실행 중 USB 포트가 안 보였던 이유도 같은 맥락으로 보임(코어 main이 TinyUSB 장치는 초기화하지만 CDC를 `begin`하지 않음). 진단 업로드로 확인 예정.
- **2단계(맥에서 포트·데이터 확인)는 업로드 대기.** 확인되면 CLAUDE.md의 USB Serial 금지 규칙을 `AUDIO_SINK=USB_EARPIECE` 용도에 한해 예외로 바꾼다(그 전에는 CLAUDE.md 수정 안 함).

### 구현 (컴파일 완료, 업로드 대기)
- `core/earpiece_frame`: USB 프레임 `A5 5A | type | len(LE16) | payload | CRC16(LE, type~payload)`. 종류 HELLO(2초마다)/PLAY(prio, kind 0 명령·1 피드백, 조각 ASCII)/VOICE_BEGIN/VOICE_DATA(≤192B, 프레임 ≤ CDC TX 버퍼 256B)/VOICE_END(CRC)/VOICE_STOP. 호스트 테스트 `test_earpiece`(기준 벡터 `A5 5A 02 0A 00 02 00 63 39 20 63 6F 76 65 72 16 D9`, earpiece.py 자체 테스트와 동일).
- `hal/usb_earpiece`: **절대 블로킹하지 않음** — DTR 없으면 버림, `availableForWrite()`가 프레임보다 작으면 이번 루프는 건너뜀(TinyUSB `write()`는 호스트가 안 읽으면 기다리므로 직접 막음). 문장 큐 4칸(가득 차면 오래된 것 버림), 음성은 버퍼에서 이어서 전송, 호스트가 닫히면 중단. `while(!Serial)` 없음 → 호스트 없이도 BLE·입력 정상.
- `app/voice_rx`(프로토콜 §7.4, CLAUDE.md §6.9): 정적 40,000B 버퍼 + 청크 비트맵(최대 4096청크). BEGIN 검사(codec 1, 8000Hz, ≤ 40,000B, 청크 수) 실패 → VOICE_RESULT 3. 수신 중 다른 voice_id의 BEGIN: prio 1이면 이전 폐기, 0이면 무시(LOG). 같은 voice_id BEGIN = 재전송으로 새로 시작. 청크 크기 N은 비마지막 청크 길이, 또는 마지막 청크로 `(총 바이트 − 마지막 길이)/(청크 수 − 1)`. END: 누락 → 2, CRC 불일치 → 1, 정상 → 0 + audio sink로 재생 + 마지막 명령(0x11, voice_id) + LED2 미확인. BEGIN 후 3초 안에 END 없으면 2. 청크마다는 LOG 안 보냄.
  - "재생 완료 후 미확인"(§6.9)은 이어폰 단말에서 재생이 끝난 시점을 알 수 없어 **END 정상 수신 시점**으로 대체.
- `app/commands`: 재생을 `audio_sink_play_clips()`로(LOG "PLAY:"는 DEBUG_LOG일 때 함께), 마지막 명령이 음성이면 조이스틱 짧게 → 음성 다시 재생, VOICE_* → voice_rx, VOICE_CHUNK는 rx LOG 생략.
- `app_feedback(clips, note)`: 피드백 조각은 audio sink(우선순위 최저)로, 설명은 LOG에만(예: `FEEDBACK: err (no last command)`).
- **STATS 집계 구현(C 요청)**: `app_send_raw` 성공 시 현재 EMCON 모드에 프레임 수·바이트(헤더 포함, 재전송·LOG 포함) 누적. USB 이어폰 링크는 무선이 아니라 STATS에 넣지 않고 재연결 LOG에 `ear_out=`(누적 바이트)·`ear_drop=`로 표시.
- 컴파일: ID 1 **151,312B(18%) / 62,020B(26%)**, ID 2 **149,052B / 61,964B**(음성 버퍼 40KB 포함), 경고 `USE_TINYUSB`만. 호스트 테스트 8개 + C99 + ASCII 전부 통과.
- `tools/earpiece.py`: 포트 자동/`--port`, 끊기면 다시 기다림, 프레임 파서(동기·CRC로 재동기), PLAY → 한국어 표(`c9`→"9시", `cover`→"엄폐", `n3`→"3명", 피드백 `n2`→"2") → `say -v Yuna`, `err` → 시스템 소리 Basso, 음성 → ADPCM 디코딩 → WAV → `afplay`. 재생 큐는 우선순위(긴급 > 일반 > 피드백) 순, 더 높은 우선순위가 오면 지금 재생을 끊음. `--self-test` 통과.
- `tools/mock_leader.py`: `voice <wav> [prio] [targets]`, `--gap-ms`(기본 15). WAV(8/16비트, 모노/스테레오, 아무 샘플레이트) → 8kHz 선형 리샘플 → 앞뒤 무음 제거 → −3dBFS 정규화 → 최대 10초 → ADPCM → BEGIN(응답 있음)/CHUNK(응답 없음, N = MTU−3−6−3)/END(응답 있음), 병사별로 차례로. VOICE_RESULT 대상별 표시, status≠0이면 그 병사에만 같은 voice_id로 1회 재전송.
- 시험용 WAV: `assets/test_voice/cover_9.wav`("9시 방향 엄폐, 대기하라", 16kHz), `urgent_withdraw.wav`("긴급, 즉시 후퇴", 22.05kHz) — `say -v Yuna`로 생성.
- 오프라인 종단 시험(가짜 bleak): cover_9 → 2.22초, ADPCM 8,900B. MTU 247 → 청크 38×235B(마지막 205B, 최대 프레임 244B), MTU 23 → 810×11B(최대 20B). BEGIN/END만 응답 있음. S2 CRC 오류 → S2만 1회 재전송, 두 번째 실패는 재전송 안 함. 펌웨어와 같은 순서의 USB 프레임을 61B씩 쪼개 earpiece에 넣음 → CRC 일치, 2.22초 WAV, 긴급 "9시 엄폐", 오류음.

### 송신량 검토 (C)
- **USB 경로에서는 이어폰 전달이 무선 송신을 늘리지 않는다**(유선). 따라서 EMCON 의미가 그대로 유지되고 STATS(무선)에도 영향 없음.
- 2순위(BLE 2연결)로 가면: 음성 10초 = 40,000B를 병사가 다시 notify → 그 병사의 무선 송신이 분대장 → 병사 수신량만큼 늘어난다(10초 음성당 약 40KB + 헤더, 청크 235B면 171프레임). EMCON 1(최소)의 "긴급·ACK만 즉시" 취지와 충돌하고, 같은 연결 이벤트를 나눠 써서 분대장 → 병사 청크 수신도 느려질 수 있음 → 2순위는 STATS로 그 증가분이 그대로 보이게 될 것(app_send_raw 경유).
- 별도 위험: 10초(40,000B) 음성은 청크 171개 × 간격 15ms ≈ 2.6초 + BLE 지연 → **수신 제한 3초(§7.4)에 가깝다.** MTU 23이면 청크 3,637개라 3초 안에 불가능(항상 status 2). 시연 발화는 5초 이하로 하거나 `--gap-ms`를 줄여 실측할 것.

### 업로드·시험 절차 (예정)
1. **진단**: 보드 1(새 보드) RESET 두 번 → `UsbSerialDiag` 업로드 → (내가 확인) `/dev/cu.usbmodem*`가 보이는지, 포트를 열면 `diag n=… dtr=1` 줄이 오는지, 안 열었을 때도 LED1이 계속 깜빡이는지.
2. 되면 CLAUDE.md USB Serial 규칙 예외 반영 → 보드 1 RESET 두 번 → ID 1 업로드 → 보드 B RESET 두 번 → ID 2 업로드.
3. 같은 맥에서 동시 실행(Terminal.app 탭 2개):
   - 탭 1(USB, 이어폰 단말): `python3 tools/earpiece.py --id 1`
   - 탭 2(BLE, 분대장 대역): `python3 tools/mock_leader.py --only S1,S2`
   - 보드 1은 USB 데이터 케이블로 맥에, 보드 2는 전원만.

### 사용자 확인 (2026-10-10)
- "요청과 다르게 정한 부분" 3가지 동의: ① `mock_leader --earpiece` 대신 USB `earpiece.py`(병사가 검증한 ADPCM 재생), ② 분대장 측 변경 없음, ③ USB 이어폰 전달량은 STATS(무선) 미포함.

### USB Serial 진단 (2단계: 장비) — ✅ 사용 가능
- 보드 1(`991886332446329E`) RESET 두 번 → `UsbSerialDiag` 업로드 → `Device programmed.`
- 내가 직접 확인(스크립트, 표준 라이브러리만):
  ```
  ports: ['/dev/cu.usbmodem101'] (after 0.0s)
  "USB Product Name" = "NU40DK nRF52840"   "USB Serial Number" = "991886332446329E"
  diag n=0 up=25000 dtr=1 afw=256 skipped=49     ← 포트를 안 연 약 24.5초 동안 49번 건너뛰며 loop 계속(블로킹 없음)
  diag n=1 up=25500 dtr=1 afw=256 skipped=49
  diag n=2 up=26000 dtr=1 afw=256 skipped=49
  PING-echo                                     ← 맥 → 보드 → 맥 되돌림
  diag n=3 … n=5 (0.5초 간격)
  ```
- 결론: CDC를 `begin`하면 펌웨어 실행 중에도 포트가 보이고(이름 "NU40DK nRF52840"), 호스트 없이도 멈추지 않고, 양방향 동작. 송신 버퍼 256B.
- **CLAUDE.md §2-9, §9 수정**(사용자 지시대로 이 용도 한정): USB Serial 금지 유지, `AUDIO_SINK=USB_EARPIECE`(`hal/usb_earpiece`)만 예외. 조건: `<Adafruit_TinyUSB.h>` 포함, 호스트 대기 금지, DTR 없음/버퍼 부족이면 쓰지 않음, 프레임은 `core/earpiece_frame.h`. 업로드 절차(RESET 두 번)는 그대로.

### 프로토콜 v1.0.2 변경 제안 — 음성 수신 시간 제한 (병사 수신 측, 2026-10-10 사용자 요청)
- 현재(v1.0.1 §7.4-4): "BEGIN 후 3초 동안 END가 없으면 폐기하고 status=2".
- 제안: **"마지막 수신 활동(VOICE_BEGIN 또는 VOICE_CHUNK) 후 3초 동안 아무것도 없으면 폐기하고 status=2"**(무활동 기준).
- 이유: 실제 분대장(UNO Q, Linux BlueZ)의 청크 송신이 맥보다 느릴 수 있어, BEGIN 기준이면 5초 이상 발화(청크 100개 이상)가 정상 전송 중에도 3초에 걸릴 위험. 10초(40,000B)는 맥에서도 청크 171개 × 15ms ≈ 2.6초 + 지연으로 한계에 가까움.
- 영향: 병사 수신 측 동작만 바뀜 → **분대장 구현 변경 없음**. 분대장은 지금처럼 status≠0이면 1회 재전송.
- 펌웨어 반영 완료: `voice_rx`가 BEGIN과 받아들인 청크마다 활동 시각 갱신, `(int32_t)(now − 활동 시각) ≥ 3000`이면 폐기 + status 2, LOG `voice id=… timeout: no data for 3s (받은/전체 chunks, BEGIN 후 경과 ms)`.
- 컴파일: ID 1 **151,384B / 62,028B**, ID 2 **149,124B / 61,972B**, 경고 `USE_TINYUSB`만. 호스트 테스트 전부 통과.
- 프로토콜 문서(`docs/squad_ble_protocol_v1.md`)는 수정하지 않음 — 문서 담당이 v1.0.2로 반영할지 결정.

### 단계 5·6 시험 절차 (업로드 후)
준비: 보드 A 꺼 둠. 보드 1은 **USB 데이터 케이블로 맥에**, 보드 B는 전원만. Terminal.app 창(또는 탭, ⌘T) 두 개:
- 탭 1 — 이어폰 단말(USB): `cd ~/Downloads/soldier-node && python3 tools/earpiece.py --id 1`
- 탭 2 — 분대장 대역(BLE): `cd ~/Downloads/soldier-node && python3 tools/mock_leader.py --only S1,S2`
  (음성 간격 시험 때는 탭 2를 `quit` 후 `--gap-ms`를 붙여 다시 실행)
- 순서는 상관없음(earpiece.py는 포트가 생길 때까지 기다리고, 펌웨어는 포트가 열릴 때부터 보냄). 맥 소리 켜기.

| # | 입력 | 기대 결과 |
|---|---|---|
| 1 | 두 탭 실행 | 탭 1 `… 열림`, `[S1] 이어폰 링크 연결(버전 1)` / 탭 2 S1·S2 연결, `boot … sink=usb_earpiece` |
| 2 | S1 조이스틱 오른쪽 + 버튼1 2번 | 맥에서 "1", "2" → "적 송신"(피드백), 탭 2 `CONTACT 적 2, 방위 90°, 3시` |
| 3 | 명령 전 S1 버튼3 짧게 | 맥에서 오류음(Basso) |
| 4 | `cmd take_cover 270 - - 1 all` | 맥에서 "9시 엄폐"(긴급), 탭 1 `PLAY(긴급): c9 cover`. S2는 이어폰 없음 |
| 5 | `cmd enemy_info 45 far 3 0 1` | "적 3명 2시 원거리" |
| 6 | 우선순위: `cmd report_status - - - 0 1` 직후 바로 `cmd halt - - - 1 1` | 탭 1 `⏹ 긴급 재생이 와서 지금 재생(일반)을 끊음` → "정지" |
| 7 | `voice assets/test_voice/cover_9.wav 0 all` | 탭 2 `음성 0 송신 완료 … 청크 38×235B`, `voice 0: S1 정상, S2 정상` / 탭 1 `음성 0 수신 완료(CRC … 일치)` → 맥에서 "9시 방향 엄폐, 대기하라"(8kHz 음질) / S1·S2 LED2 점멸 |
| 8 | S1 버튼3 짧게 | 탭 2 `ACK 대상 음성 voice_id 0`, S1 LED2 꺼짐 |
| 9 | S1 조이스틱 짧게 | 음성 다시 재생(`PLAY: voice id=0 (replay)`), 송신 없음 |
| 10 | `voice assets/test_voice/urgent_withdraw.wav 1 1` | S1만, 긴급 → 재생 중인 것이 있으면 끊고 "긴급, 즉시 후퇴" |
| 11 | 무활동 시간 제한(v1.0.2): 탭 2를 `--gap-ms 200`으로 다시 실행 → `voice assets/test_voice/cover_9.wav 0 1` | 청크 38개 × 0.2초 ≈ 7.6초(BEGIN 기준이면 실패했을 길이) → `S1 정상` |
| 12 | 탭 2를 `--gap-ms 3500`으로 → 같은 voice | 첫 청크 뒤 3초 무활동 → S1 LOG `voice id=… timeout: no data for 3s` → `S1 시간 초과` → 1회 재전송 → 또 시간 초과(정상 동작) |
| 13 | 탭 1을 Ctrl+C로 끄고 `cmd halt - - - - 1` → 탭 1 다시 실행 | 끈 동안은 소리 없음(펌웨어는 버림, BLE 정상). mock_leader 재시작 후 재연결 LOG `ear_drop=`가 늘어남 |
| 14 | `stats all` | EMCON2 프레임/바이트가 0이 아님(무선으로 실제 나간 양, LOG·재전송 포함) |

### 업로드: 단계 5·6 최종 빌드
- 보드 1(`991886332446329E`) / ID 1: RESET 두 번 → `/dev/cu.usbmodem101` → `Device programmed.`, exit 0 (151,384B).
  - 업로드 직후 USB 확인(내가 직접, earpiece.py 파서): 포트 `/dev/cu.usbmodem101`("NU40DK nRF52840"), 포트를 열자 **HELLO(id 1, 버전 1)가 2.0초·4.0초에 도착**, 깨진 프레임 0 → 펌웨어의 USB 이어폰 링크 동작.
- 보드 B(`F2408DEA04B8AC33`) / ID 2: RESET 두 번 → `/dev/cu.usbmodem1101` → `Device programmed.`, exit 0 (149,124B). 다음: 단계 5·6 시험(사용자, Terminal.app 탭 2개).

### 단계 5·6 장비 시험 결과 (2026-10-10, 두 탭 출력 확인)
| # | 결과 | 근거(출력) |
|---|---|---|
| 1 | ✅ | 탭 1 `[S1] 이어폰 링크 연결(버전 1)` / 탭 2 `boot id=1 … sink=usb_earpiece`, `boot id=2 joy=0 …` |
| 2 | ✅ | `PLAY(로컬 피드백): n1`→"1", `n2`→"2", `enemy sent`→"적 송신", `received`→"수신" / `CONTACT 적 2, 방위 90°, 3시, 원거리` |
| 3 | ✅ | `PLAY(로컬 피드백): err` → 오류음 |
| 4·5 | ✅ | "9시 엄폐"(긴급), "적 3명 2시 원거리". 15초 재전송 시 dup 재생도 이어폰으로 나옴 |
| 6 | ⚠ 미시험 | 두 명령을 한 줄에 입력 → mock_leader가 남는 인자를 조용히 버려 halt가 안 나감(아래 수정) |
| 7 | ✅ | 음성 0: S1 0.71초·S2 0.94초 전송, `S1 정상, S2 정상` / 탭 1 `음성 0 수신 완료(USB 36ms, CRC 3C84 일치)` → 재생. S2는 `audio sink not ready`(이어폰 없음, 정상) |
| 8 | ✅ | S1·S2 `ACK 대상 음성 voice_id 0` |
| 9 | ✅ | `PLAY: voice id=0 (replay)` → 탭 1 음성 0 다시 재생(USB 41ms) |
| 10 | ✅ | 음성 1(긴급, 1.45초, 25청크) → `S1 정상` → 재생 |
| 11 | ✅ **v1.0.2 확인** | `--gap-ms 200`: 7.76초 동안 38청크 → `voice ok id=0 bytes=8900 7715ms` → 정상(BEGIN 기준 3초였다면 실패했을 길이) |
| 12 | ✅ | `--gap-ms 3500`: `timeout: no data for 3s (1/38 chunks, 3061ms since begin)` → `시간 초과` → 1회 재전송 → 다시 시간 초과(재전송 없음). 늦게 온 END는 `voice end id=0: no matching begin` |
| 13 | ✅(부분) | 탭 1 재시작 후 `PLAY(일반): halt` → "정지". 끈 동안의 `ear_drop` 증가는 재연결 LOG가 없어 미확인 |
| 14 | ✅ | `STATS … EMCON2 91프레임/3336B`(S1), `35프레임/1301B`(S2) |
- 참고 수치: 재연결 LOG `ear_out=27124 → 36865`(USB로 내보낸 누적 바이트), S2 `ear_drop=5`(호스트 없음, 정상), `tx_fail=0`, `rx_dropped=0`.
- 소리 품질(사용자 청취 소감)은 아직 받지 못함.

### mock_leader 수정 (시험에서 발견, 펌웨어 변경 없음)
1. `cmd` 인자가 6개를 넘으면 조용히 버리던 것을 **오류로** 처리(`voice`도 3개 초과 시 오류). → #6이 한 줄 입력 때문에 시험되지 않았던 원인.
2. `voice` 전송을 **백그라운드 작업**으로: 긴 전송(#12에서 133초) 동안 CLI가 막히던 문제 해결.
3. 병사가 status≠0을 보내면 **진행 중인 청크 전송을 중단**하고(전송 세대 번호), 재전송은 처음부터 새로. 두 번째 실패도 중단만 하고 더 재전송하지 않음.
- 오프라인 확인: 한 줄 두 명령 → 오류, `voice`가 0.03초 만에 반환, 실패 시 `전송 중단(5/38 청크에서)` 후 재전송 1회, 두 번째 실패 후 중단.

### #6 재시험 (2026-10-10) — ✅
- `cmd report_status - - - 0 1` 후 2초 뒤 `cmd halt - - - 1 1` → 탭 1 `⏹ 긴급 재생이 와서 지금 재생(일반)을 끊음` → "정지". 15초 재전송(dup) 때도 같은 끊기 동작.
- → **단계 5·6 장비 시험 14개 항목 모두 통과**(#13의 `ear_drop` 증가만 미확인).

### 버그: 새 명령이 중복으로 처리됨 (#6 재시험 출력에서 발견) — 수정, 재업로드 대기
- 현상: `20:15:24 → CMD_BUTTON seq=1 HALT`(처음 보냄) → 병사 `cmd dup seq=1 HALT: replay only`. HALT가 마지막 명령이 되지 않고, LED2 미확인은 이전 명령(seq 0)에 남음(`unacked 30s: seq=0`).
- 원인: mock_leader 재시작으로 seq가 0부터 다시 시작 → 병사 dedup이 20:02의 TAKE_COVER(src 0, seq 1)를 아직 기억. **실전에서도 발생 가능**: seq는 0~255 순환이고 RPT_ACK·음성 청크(음성 1건 ≈ 40)도 seq를 써서 금방 한 바퀴 돌며, 분대장 재시작도 있음 → 기억한 16개가 아주 오래된 것일 수 있다.
- 수정(`core/dedup`): 중복 = **(src, seq) 같음 + payload CRC16 같음 + `DEDUP_WINDOW_MS`(60초) 안**. 진짜 재전송(같은 seq·같은 내용·15초 안)은 그대로 중복. 같은 (src, seq)라도 내용이 다르거나 60초가 지나면 새 명령으로 받고 그 자리를 갱신.
- 호스트 테스트(`test_queue` 131 checks): 재시작 시나리오 재현(seq 1에 다른 명령 → 새 명령, 그 15초 재전송 → 중복), 같은 내용도 60초 뒤 새 명령, 16개 넘침, seq 255→0, millis 오버플로. 전체 8개 테스트 통과.
- 컴파일: ID 1 151,208B, ID 2 148,948B. **업로드는 다음 단계와 함께.**

### 프로토콜 v1.0.2 변경 제안 (추가) — 중복 제거 기준 (병사 수신 측)
- 현재(v1.0.1 §3.2, §8.1-6): "(src_id, seq)로 중복을 제거한다(최근 16개 기억)".
- 제안: **"(src_id, seq)가 같고 내용(payload)이 같으며 60초 안에 다시 온 프레임만 중복으로 본다."**
- 이유: seq 8비트 순환 + 분대장 재시작 시 0부터 → (src, seq)만으로는 오래전 명령과 겹친 새 명령을 버린다(장비 시험에서 실제 발생).
- 분대장 영향: 없음(재전송은 지금처럼 같은 seq·같은 바이트). 권장 사항으로만: 분대장 재시작 시 seq를 무작위 값에서 시작하면 더 안전.

---

## 단계 7 — EMCON 0/1/2 + 침묵 모드 광고 수신 + STATS (2026-10-10) — 구현·컴파일 완료, 업로드 대기

### 사용자 추가 조건 반영
- 소리 피드백(모드 변경 "침묵/최소/정상" 등)은 audio sink → USB 이어폰(earpiece.py)으로.
- 침묵 모드에서 BLE 연결을 끊어도 USB 이어폰 경로는 그대로(무선과 무관). 광고로 받은 버튼 명령도 같은 commands 경로 → earpiece로 재생.
- 음성 명령은 침묵 모드에서 받지 않음: ① 연결이 없으니 VOICE_* 프레임이 올 수 없고 ② 스캔 필터가 CMD_BUTTON/EMCON_SET만 통과시키며 ③ 침묵 진입 시 수신 중이던 음성은 `voice_rx_abort()`로 폐기(VOICE_RESULT 없음).

### 구현
- `hal/radio`:
  - 모드 0: `restartOnDisconnect(false)` → 광고 중지 → 연결 끊기 → **수동 스캔**(`useActiveScan(false)` = scan request 없음, `filterMSD(0xFFFF)`, 100ms/100ms 연속). 스캔 콜백에서 MSD를 복사해 Company ID 0xFFFF + ver 1 + src 0 + (CMD_BUTTON | EMCON_SET)만 RX 링 버퍼로 → 연결 RX와 같은 `commands_handle_frame` 경로(dst_mask 검사 포함). 콜백마다 `Scanner.resume()`(SoftDevice v6는 보고마다 정지).
  - 모드 1/2: 스캔 중지 → 송신 출력 적용(`Bluefruit.setTxPower` = 다음 광고, `BLEConnection::setTxPower` = 현재 연결) → 연결 가능 광고 재개(자동 재광고 켬).
- `app`: `app_set_mode(mode, reason)` 하나로 모든 전환(조이스틱 길게, **버튼1+버튼2 2초**(ID 2용, 모든 보드), EMCON_SET, SILENCE). 순서: LOG → (0이면 음성 폐기) → 보고 규칙 → 무선 → LED4 → 피드백 음성 → (1/2면 EMCON_STATE를 보고 큐에 넣어 연결되면 송신).
  - LED1: 연결 모드 = 연결 시 켜짐, **침묵 = 3초마다 100ms**(§9.4). LED4: 0 꺼짐 / 1 느린 점멸 / 2 켜짐.
  - 최소 모드 송신 출력 `EMCON1_TX_POWER_DBM`(기본 −20, **TODO_CONFIRM**), 정상 `EMCON2_TX_POWER_DBM` 0. **버튼3+버튼4 2초** = 최소 모드 출력 순환 `{−40, −20, −12, −8, −4}`(거리 시험용, RAM에만, 재부팅 시 기본값).
  - 디버그 LOG 사본을 **USB 이어폰 링크(EP_LOG 0x07)**로도 보냄 → 침묵 모드에서도 `earpiece.py --log`로 병사 상태가 보인다.
- `hal/buttons`: 두 버튼 조합 일반화(버튼1+4 3초 보정, 버튼1+2 2초 모드, 버튼3+4 2초 출력). 동시 눌림 순간 두 버튼의 단독 제스처 취소(버튼2 1초 폭발물·버튼4 2초 본인 부상 오발 방지).
- `app/commands`: EMCON_SET → 실제 전환, SILENCE → 재생 후 침묵 전환. **같은 명령 반복은 마지막 재생 후 5초 안이면 조용히 버림**(`DUP_REPLAY_HOLDOFF_MS`): 침묵 광고는 100ms × 3초 반복이라 그대로 두면 이어폰에서 십수 번 재생됨. 그보다 늦은 반복(분대장 15초 재전송)은 지금처럼 "다시 재생만"(§8.1-6). CMD_BUTTON의 일반 rx LOG도 생략(광고 반복 LOG 폭주 방지).
- `app/stats`: **디버그 LOG(0x7F)는 STATS에서 제외**(프로토콜 밖 메시지, 모드 비교를 흐림). 침묵 모드 송신은 0이므로 EMCON0 칸은 항상 0이어야 한다.
- 보고 큐(최대 32, 긴급 보존)·최소 모드 30초 일괄은 단계 3 구현 그대로 사용(EMCON 0 → 1/2 진입 시 오래된 순서로 송신).
- 컴파일: ID 1 **153,960B / 62,164B**, ID 2 **151,684B / 62,108B**, 경고 `USE_TINYUSB`만. 호스트 테스트·ASCII 검사 통과.

### 진단 펌웨어 `firmware/diag/LeaderBeacon/` (보드 A `7658AE0B1C2F8327`용)
- 연결·스캔 불가 광고(ADV_NONCONN_IND), Flags + MSD(0xFFFF + 프레임), 100ms × 3초 후 정지(정지 콜백 → `DONE`). 새 명령이 오면 진행 중 방송을 멈추고 새로.
- 버튼 1~4: 정지(긴급) / 엄폐 270(긴급) / 사격 중지 / 집결 — 전원(dst 0x1F). seq 시작값은 SoftDevice 난수.
- **USB 시리얼 모드**(UNO Q·맥이 방송 위임): 프레임 hex 한 줄 → 검사(ver 01, src 00, CMD_BUTTON len 6 또는 EMCON_SET len 1, len 필드 일치) → 방송 → `OK tx type= seq= dst= len= 3s` / `ERR …` / `DONE seq=…`, `help`. 블로킹 없음(호스트 없으면 응답 버림). LED1 방송 중, LED2 DTR, LED3 마지막 명령이 USB에서 옴.
- 컴파일 124,496B / 15,464B.
- 분대장 팀원용 정리: **`docs/leader_silent_mode_notes.md`**(리눅스 직접 광고에 필요한 것 + 보드 A 비콘 사용법).

### 도구
- `mock_leader.py`: `emcon <0|1|2> [targets]`(연결로 EMCON_SET), `--beacon-port <포트>` + `bcmd …` / `bemcon <1|2> [targets]`(보드 A 경유 광고), **`--log-csv <파일>`**(모든 송수신 프레임: 시각, 방향 rx/tx/tx_adv, 병사, 종류, seq, src, dst, 길이, hex).
- `tools/tx_summary.py <csv> [<csv2>]`: 병사 → 분대장 프레임·바이트·종류별 수·**송신 묶음 수**(1초 넘게 끊기면 새 묶음), 디버그 LOG 별도, 두 파일 비교.
- `earpiece.py --log`: USB로 온 병사 LOG 사본 출력.
- 오프라인 확인(가짜 bleak/pty): CSV 기록·요약(같은 보고 5개: 모드 2 = 묶음 5회, 모드 1 = 1회), `bcmd`/`bemcon`이 보드 A에 쓰는 hex 줄, 비콘 응답 표시, `bemcon 0` 거부.

### 발견: 프로토콜 문서 안의 불일치(보고만, 문서 수정 안 함)
- §3.2 "31바이트 한도 안에 들어가야 하므로 **버튼 명령(§6) 프레임만** 허용" ↔ §5.2 표 `EMCON_SET` "침묵 모드 **O**".
- 구현: 둘 다 받음(EMCON_SET 7B도 31B 안). 분대장이 광고로 병사를 연결 모드로 되돌릴 수 있어야 하므로. 문서 담당에게 §3.2 문구를 "CMD_BUTTON·EMCON_SET"으로 맞출지 확인 요청.

### 업로드 계획 (각각 RESET 두 번 후)
1. 보드 1(`991886332446329E`) → ID 1
2. 보드 B(`F2408DEA04B8AC33`) → ID 2
3. 보드 A(`7658AE0B1C2F8327`) → LeaderBeacon

### 단계 7 시험 절차
준비: 보드 1·보드 A를 맥 USB에(포트 2개 → 업로드 후 내가 어느 포트가 어느 보드인지 확인해 알려 줌), 보드 B는 전원만. Terminal.app 탭 2개:
- 탭 1: `python3 tools/earpiece.py --id 1 --log --port <보드 1 포트>`
- 탭 2: `python3 tools/mock_leader.py --only S1,S2 --beacon-port <보드 A 포트>`

| # | 입력 | 기대 결과 |
|---|---|---|
| 1 | 두 탭 실행 | S1·S2 연결, `boot … emcon=2 tx1=-20`, 탭 2 `[비콘]` 응답 없음(정상: 아직 방송 안 함) |
| 2 | S1 조이스틱 길게(1초) | 2→0: 맥 "침묵", 탭 1 `LOG: emcon 2 -> 0 (joystick)`, 탭 2 `[S1] 연결 끊김`(재연결 안 됨), S1 LED1 3초마다 깜빡, LED4 꺼짐 |
| 3 | 침묵 중 S1 버튼4 짧게 | 맥 "송신"(피드백), 탭 1 `LOG: tx OK_READY seq=… queued(emcon0)`, 탭 2 수신 없음 |
| 4 | `bcmd take_cover 270 - - 1 all` | 탭 2 `[비콘] OK tx … 3s` → `DONE`, 맥 **"9시 엄폐" 한 번만**, 탭 1 `LOG: cmd TAKE_COVER seq=…`, S1 LED2 점멸 |
| 5 | `bcmd halt - - - - 2` | S1 무반응(탭 1 `rx drop err=-6`가 광고 수만큼 보일 수 있음), S2가 침묵이면 S2 LED2 점멸 |
| 6 | 침묵 중 S1 버튼3 짧게 | 맥 "송신", 탭 1 `tx ACK … queued(emcon0)` |
| 7 | 침묵 중 `voice assets/test_voice/cover_9.wav 0 1` | 탭 2 `[S1] 연결 안 됨 → 건너뜀`(음성은 침묵 모드에서 못 받음) |
| 8 | `bemcon 1 1` | 맥 "최소", S1 광고 재개 → 탭 2 S1 재연결 → **큐가 오래된 순서로**: OK_READY → ACK → EMCON_STATE(1). LED4 느린 점멸 |
| 9 | 모드 1에서 S1 버튼4 짧게 / 두 번 | OK_READY는 30초 안 일괄, WEAPON_AMMO는 즉시 |
| 10 | S2 버튼1+버튼2 2초 ×2 | S2 2→0(탭 2 `[S2] 연결 끊김`) → 0→1(재연결 후 EMCON_STATE 1) |
| 11 | `emcon 0 2` → `bemcon 2 2` | S2 연결 끊고 침묵 → 광고 받고 정상 모드로 재연결 |
| 12 | `cmd silence - - - - 1` | 맥 "무선 침묵" → S1 침묵 전환(연결 끊김). 이어서 `bemcon 2 1`로 복귀 |
| 13 | 정상 모드로 돌아온 뒤 `stats all` | EMCON0 칸 **0**(침묵 중 송신 없음), EMCON1·2 칸에 보고·ACK·EMCON_STATE·STATS 등(LOG 제외) |

### 최소 모드 송신 출력 거리 시험 (−40, −20, −12, −8, −4 dBm 순)
- 대상: 보드 B(ID 2, 조이스틱 없음) 또는 보드 1을 **배터리/보조배터리**로, 맥에서 약 10m(실제 분대원 간격). 맥 쪽 출력은 고정(측정 대상은 병사 → 분대장 방향).
1. 가까이에서 mock_leader 연결 → 병사를 모드 1로(버튼1+버튼2 2초, 또는 `emcon 1 <id>`). LOG `emcon … tx=-20dBm` 확인.
2. 버튼3+버튼4 2초를 눌러 **−40**으로(LOG `emcon1 tx_power=-40dBm (applied now)`; 목록 순서 −40 → −20 → −12 → −8 → −4 → −40).
3. 10m로 이동해 60초 동안: 10초마다 `stats <id>` 6번 → 응답 수, `연결 끊김` 여부 기록. 병사 버튼4 짧게 1번(30초 일괄 수신 확인).
4. 끊기거나 응답이 6/6 미만이면 병사 쪽으로 가서 버튼3+버튼4로 다음 값 → 다시 3.
5. 6/6 응답 + 끊김 없음인 **가장 낮은 값**을 `EMCON1_TX_POWER_DBM`에 반영(재빌드). 여유를 위해 한 단계 위를 권장할 수도 있음(벽·사람 몸에 따라 변동).
- 기록 표: 출력 | 연결 유지(예/아니오) | stats 응답 n/6 | 비고.

### 모드 1 vs 2 송신량 비교 (`--log-csv`)
- 같은 시나리오(약 70초): 버튼4 짧게 ×3(10초 간격), 버튼2 짧게 ×2, 조이스틱 기울여 버튼1 ×1(적 발견), `cmd halt - - - - 1` + 버튼3 ACK, 마지막 입력 후 35초 기다린 뒤 `stats 1`.
1. S1 모드 2: `python3 tools/mock_leader.py --only S1 --log-csv run_mode2.csv` → 시나리오 → `quit`
2. S1을 모드 1로(조이스틱 길게 2번: 2→0→1, 또는 `emcon 1 1`) → `python3 tools/mock_leader.py --only S1 --log-csv run_mode1.csv` → 같은 시나리오 → `quit`
3. `python3 tools/tx_summary.py run_mode2.csv run_mode1.csv`
- 기대: 보고 **프레임 수·바이트는 거의 같고**(같은 보고를 보내므로), **송신 묶음 수가 모드 1에서 줄어듦**(비긴급이 30초마다 한꺼번에), 여기에 모드 1은 **송신 출력이 낮음**(CSV엔 안 보임). 병사 `stats`의 EMCON1·EMCON2 칸으로 교차 확인. 링크 계층의 빈 패킷(연결 유지)은 CSV·STATS 어디에도 없다 → 진짜 "전파 방출 0"은 모드 0뿐.

### 대안: 폰 nRF Connect 앱으로 침묵 광고 보내기 (보드 A 없이)
- **Android** nRF Connect → ADVERTISER 탭 → `+` → Add Record → **Manufacturer Data**: Company ID `0xFFFF`, Data `011005001F06020E01FF0001`(= `01 10 05 00 1F 06 02 0E 01 FF 00 01`, 전원 엄폐 270, seq 05).
- Options: **Connectable 끔**, Interval 100ms(Advertising interval: 100ms 또는 가장 가까운 값), Timeout 3s(또는 수동으로 3초 뒤 끄기). 새 명령마다 seq 바이트(3번째)를 바꿀 것.
- iOS 앱은 Manufacturer Data 광고를 지원하지 않는다(iOS 제약) → Android 기기 필요.

### 프로토콜 v1.0.2 반영 확인 (2026-10-10)
- 사용자가 `docs/squad_ble_protocol_v1.md`를 v1.0.2로 교체: §3.2 EMCON_SET 방송 허용, §3.2 5초 안 반복 무재생, §7.4 무활동 3초 → **모두 현재 구현과 일치**(§7.4는 이미 이번 빌드에 포함).
- **불일치 1건(사용자 확인 대기)**: v1.0.2 §3.2는 "같은 (src_id, seq)"만으로 중복을 판정. 펌웨어는 우리 제안 2(같은 seq **+ 같은 내용 + 60초 안**)로 구현 → seq가 같고 내용이 다르면 새 명령으로 받는다(장비 시험에서 본 "재시작 후 새 명령이 중복 처리" 문제 대응). 문서대로 되돌릴지, 제안을 문서에 넣을지 결정 필요.
- 최소 모드 송신 출력 −20dBm은 거리 시험 후 확정(사용자).

### 업로드: 단계 7
- 보드 1(`991886332446329E`) / ID 1 → `/dev/cu.usbmodem101` → `Device programmed.`, exit 0 (153,960B).
- 보드 B(`F2408DEA04B8AC33`) / ID 2 → `/dev/cu.usbmodem1101` → `Device programmed.` (151,684B).
- 보드 A(`7658AE0B1C2F8327`) / LeaderBeacon → `/dev/cu.usbmodem1101` → `Device programmed.`, exit 0.
  - USB로 직접 확인: `help` → 사용법 2줄 / `01 10 A1 00 1F 06 02 0E 01 FF 00 01` → `OK tx type=10 seq=A1 dst=1F len=12 3s` → 약 3초 뒤 `DONE seq=A1` / len 필드 틀린 프레임·VOICE_CHUNK → `ERR only CMD_BUTTON(10, len 6) or EMCON_SET(16, len 1) …`. (광고가 실제로 병사에게 받아지는지는 단계 7 시험 #4에서 확인)

### 프로토콜 v1.0.3 반영 확인 (2026-10-10)
- 사용자가 중복 판정 (b) 확정 → 문서 v1.0.3(§3.2, §8.1-6, 부록 B): "같은 src_id·seq + 같은 payload + 60초 안"만 중복, 5초 안(마지막 재생 기준) 반복은 무재생, 5초 뒤는 재생만. → `core/dedup`(60초 창, payload CRC16) + `commands`(`DUP_REPLAY_HOLDOFF_MS` 5초, 마지막 재생 기준)과 **일치**. 펌웨어 변경 없음.
- 분대장 측 권장(재시작 시 seq 무작위 시작)은 LeaderBeacon에 이미 적용(SoftDevice 난수).

### 단계 7 시험 포트 (2026-10-10, 내가 직접 확인)
- `/dev/cu.usbmodem101` = 보드 1(ID 1, `991886332446329E`) — HELLO id 1
- `/dev/cu.usbmodem1101` = 보드 A(분대장 비콘, `7658AE0B1C2F8327`) — `help` 응답
- 포트 이름은 꽂은 USB 단자에 따라 바뀔 수 있음(다시 꽂으면 재확인).

### 단계 7 장비 시험 결과 1차 (2026-10-10, 두 탭 출력 확인)
| # | 결과 | 근거 |
|---|---|---|
| 1 | ✅ | S1·S2 연결, `boot … emcon=2 tx1=-20` |
| 2 | ✅ | `emcon 2 -> 0 (joystick)` → "침묵", `[S1] 연결 끊김`, 재연결 없음 |
| 3 | ✅ | `tx OK_READY seq=5 queued(emcon0)` |
| 4 | ✅ | 비콘 `OK … DONE`, 병사 `PLAY: c9 cover` **1회**(광고 반복 무재생 v1.0.2 확인) |
| 5 | ✅(S1만) | S1 `rx drop err=-6`(dst 02). S2는 연결 상태였음 → S2 침묵 수신은 미시험 |
| 6 | ✅ | `tx ACK seq=6 queued(emcon0)` |
| 7 | ✅ | `[S1] 연결 안 됨 → 건너뜀` |
| 8 | ✅ | `bemcon 1 1` → "최소" → 재연결 → OK_READY(5) → ACK(6) → EMCON_STATE(7) 오래된 순서 |
| 9 | ✅(절반) | 모드 1 진입 20:59:19 → OK_READY×2 queued → 20:59:49(30초) 일괄. WEAPON_AMMO 즉시는 미시험 |
| 10 | ⚠ 미시험 | S2 버튼1+버튼2 2초(대신 `emcon 0 2` 사용) |
| 11 | ✅ | `emcon 0 2` → 끊김, `bemcon 2 2` → 재연결 + EMCON_STATE 2 |
| 12 | ✅ | "무선 침묵" → "침묵" → 끊김, `bemcon 2 1` 복귀, 이후 ACK 반영 |
| 13 | ✅ | S1 `EMCON0 0프레임/0B, EMCON1 6프레임/40B, EMCON2 2프레임/14B`(계산: OK_READY 6 + ACK 8 + EMCON_STATE 7 + 7 + OK_READY 6×2 = 40, EMCON_STATE 7×2 = 14 일치), S2 `EMCON2 1프레임/7B` |
- LED(침묵 시 LED1 3초 깜빡, LED4)는 아직 보고받지 못함.

### 1차 시험에서 발견·수정 (컴파일 완료, 재업로드 필요)
1. **침묵 진입 시 `mtu=0 max_write=4294967293` + 이후 USB LOG마다 `[tx_fail +1]`**: 끊기 요청 후 끊김 이벤트 전 틈에 notify를 시도 → 실패로 집계, MTU 0 − 3이 부호 없는 값으로 넘침. 실패 수는 BLE LOG가 성공해야 지워져 침묵 중 USB 사본에 계속 붙음.
   → `radio`: 끊기 요청 시 `s_disconnecting`(연결되면 해제), `radio_can_send()`는 끊는 중·MTU ≤ 3이면 false. `app`: MTU < 23 LOG 안 함, 침묵 진입 시 `s_notify_ready = false`.
2. **비대상 광고 `rx drop err=-6` 13줄 반복** → 같은 (type, seq) 폐기 LOG는 5초에 한 번(seq도 표시).
3. 침묵 전환 LOG가 `tx=0dBm`으로 오해 소지 → `emcon 2 -> 0 (…) radio: disconnect, passive scan`.
4. **mock_leader `쓰기 실패: KeyError(19)` + `Task was destroyed but it is pending!`**(재연결 중): start_notify 직후 연결 설정이 끝나기 전에 도착한 보고에 RPT_ACK를 바로 쓰려다 실패, 작업 참조가 없어 GC 경고. → 연결 완료 전 보고의 RPT_ACK는 `pending_acks`에 모았다가 연결 직후 송신, 모든 백그라운드 작업은 `spawn()`으로 참조 유지. 오프라인 확인(연결 전 0건 쓰기 → 연결 후 `01 17 00 00 01 01 1B`).
- 컴파일: ID 1 154,392B, ID 2 152,132B, ASCII 검사 통과.
- 재업로드 시도(1차 시험 수정): 보드 1(`991886332446329E`) → **실패**: nrfutil `NordicSemiException: No data received on serial port`(exit 0이지만 실패). 업로드 직후 USB HELLO 없음.
  - 원인 확인: `lsof /dev/cu.usbmodem101` → 탭 1의 `earpiece.py`(PID 20972)가 포트를 열고 있었음. earpiece.py는 끊기면 1초마다 같은 경로를 다시 여는데, 부트로더 포트도 같은 이름(`usbmodem101`)이라 nrfutil과 포트를 다툼. 보드는 부트로더 상태 유지(NRF52BOOT) → 재시도 가능.
  - 대책: `earpiece.py`는 `/Volumes/NRF52BOOT`가 마운트돼 있으면 포트를 열지 않고 기다리도록 수정. **업로드 전에는 earpiece.py(와 비콘 포트를 연 mock_leader)를 종료**하는 것을 표준 절차에 추가.
  - 재시도(earpiece.py·mock_leader 종료 후): 보드 1 / ID 1 → **`Device programmed.`**(실패 문구 없음), 업로드 직후 USB HELLO(id 1) 확인.
  - 보드 B(`F2408DEA04B8AC33`) / ID 2 → **`Device programmed.`**(실패 문구 없음) (152,132B). 다음: 1차 시험 미완 항목 재시험 → 송신 출력 거리 시험 → 모드 1·2 송신량 비교.

### 단계 7 장비 시험 2차 (재업로드 후, 2026-10-10)
- ✅ 수정 확인: 침묵 진입 2회(21:18:13, 21:19:06)에 `mtu=0`·`[tx_fail` 없음, 재연결 LOG `tx_fail=0`.
- ✅ #5: S2를 `emcon 0 2`로 침묵 → `bcmd halt - - - - 2` → **S2 LED2 점멸**(사용자 확인). S1은 그때 연결 상태라 스캔 안 함(LOG 없음이 정상).
- ✅ LED(사용자 확인): 침묵 중 보드 1 LED1 3초마다 짧게, LED4 꺼짐.
- ✅ 침묵 → 모드 1 전환 직후(재연결 전) 누른 WEAPON_AMMO는 큐 → 재연결 1초 뒤 송신 + `rpt_ack seq=5 ok`.
- ✅ 모드 1 일괄 재확인: `bemcon 1 1`로 21:21:25 모드 1 → 21:21:35 OK_READY queued → 21:21:56 일괄(진입 후 30초).
- 참고: 21:18:41~52 비콘 `seq=AD,AE,AF,B0`(dst 1F)는 **보드 A 버튼1+버튼2 동시 누름**(비콘은 버튼마다 방송) → #10을 보드 B 대신 보드 A에서 누른 것으로 보임. 침묵 중이던 S1이 21:20대에 받은 비콘 방송(seq 179)으로 `unacked 30s: seq=179` 발생(정상 동작).
- 남은 항목: #9(연결된 모드 1에서 버튼4 **두 번** → WEAPON_AMMO 즉시), #10(**보드 B** 버튼1+버튼2 2초).
- ✅ #9: 연결된 모드 1에서 버튼4 두 번 → `tx WEAPON_AMMO seq=34 sent`(queued 없음) → 분대장 21:23:28 수신 → `rpt_ack seq=34 ok (retries=0)` → "수신".
- ✅ #10: **보드 B** 버튼1+버튼2 2초 → S2 0→1 → 21:23:48 재연결 → `EMCON_STATE 모드 1`(큐에서). `ear_drop=9`(이어폰 없음, 정상).
- **→ 단계 7 기능 시험(#1~#13) 전부 통과.** 남은 것: 최소 모드 송신 출력 거리 시험(`EMCON1_TX_POWER_DBM` 확정), 모드 1·2 송신량 비교.
- 사용자: 단계 7 완료 확인. 거리 시험(A)·송신량 비교(B)는 나중에, `EMCON1_TX_POWER_DBM`은 −20 유지.

---

## 단계 R — 병사 간 RSSI 거리 측정 (F11) (2026-10-10) — 구현·컴파일 완료, 업로드 대기

### ⚠ 프로토콜 v1.1 추가 예정 메시지 — 분대장 팀원에게 전달 필요
| msg_type | 이름 | 방향 | payload | 분대장 처리 |
|---|---|---|---|---|
| 0x20 | BEACON | 병사 → 모두, **광고**(Manufacturer Data 0xFFFF + 프레임, dst 0xFF) | heading(2) | 받을 필요 없음(병사끼리 RSSI 측정용). 분대장 스캐너에 보여도 무시 |
| 0x0E | RANGING | 병사 → 분대장, **NUS Notify** | n(1) + n×[peer_id(1), rssi_avg(int8 dBm), samples(1)] | v1.0.x에선 무시/로그(§5.3). v1.1에서 거리 추정·위치 추정에 사용 예정. 추정식 d = 10^((P1m − RSSI)/(10·n)), 보정값은 병사 팀이 측정해 전달 |
- 둘 다 프로토콜 문서 §5.3에 "v1.1 예정"으로 형식만 있음. 실제 송신은 이번이 처음 → **문서 담당·분대장 팀원에게 "병사 펌웨어가 EMCON 2에서 0x0E를 10초마다 보내기 시작함, 무시해도 됨"을 전달**할 것.
- RANGING은 RPT_ACK 대상 아님(mock_leader도 0x01~0x0B만 자동 응답).

### 1) Bluefruit 가능 여부 확인 (코어 소스·예제)
- **광고 세트는 1개뿐**: `ble_gap.h` `BLE_GAP_ADV_SET_COUNT_MAX (1)`(S140 6.1.1) → 연결 가능 광고와 비콘을 **동시에** 할 수 없다.
- **분대장과 연결된 동안에는 가능**: Peripheral 1개 설정에서 연결되면 SoftDevice가 연결 가능 광고를 멈추고(Bluefruit `BLEAdvertising::_eventHandler`의 `BLE_GAP_EVT_CONNECTED`에서 `_running = false`), 남는 광고 세트로 **비연결형(ADV_NONCONN_IND) 광고**를 할 수 있다(SoftDevice는 연결 중 비연결형 광고 허용; 연결 가능 광고만 연결 수 제한에 걸림). `BLEAdvertising::_start`는 `setType` 값으로 `sd_ble_gap_adv_set_configure/start`를 하므로 type만 바꾸면 된다.
- **Bluefruit 자동 재광고의 함정**: `BLE_GAP_EVT_DISCONNECTED`에서 `_start_if_disconnect`면 **현재 type·데이터로** 재시작 → 비콘 상태에서 끊기면 비콘으로 재광고됨 → `restartOnDisconnect(false)`로 끄고 직접 관리.
- **연결 중 수동 스캔**: Observer는 연결·광고와 동시에 동작(SoftDevice 다중 역할 스케줄링). 예제 `DualRoles/dual_bleuart`가 Peripheral 연결 중 스캔/Central을 함께 씀. 우리 침묵 모드 스캔도 `begin(1, 0)`에서 동작함을 단계 7에서 확인.
- **불가능한 경우와 대안**: EMCON 2인데 **분대장과 끊겨 있으면** 광고 세트를 연결 가능 광고가 써야 하므로 비콘 없음(연결 복구가 우선). 대안(미구현): 끊겨 있는 동안은 다른 병사가 연결 가능 광고(`SQ1-Sn`)의 RSSI를 대신 쓰게 하거나, 연결 가능 광고와 비콘을 수 초 간격으로 번갈아 내보내기. 시연에서는 병사가 늘 연결 상태라 현 방식으로 충분.
- **장비 확인 전 가정**: 위는 소스·문서 근거. 실제로 연결 중 비콘이 나가는지는 업로드 후 시험으로 확인(아래 #2).

### 2) 구현
- `hal/radio`: 광고·스캔을 **loop가 상태로 관리**(`radio_loop`). 광고 = 없음 / 연결 가능(모드 1·2, 끊김) / **비콘(모드 2, 연결됨)**. 스캔 = 끔 / 침묵(모드 0: 분대장 방송) / **비콘 스캔(모드 1·2, 200ms 중 100ms 창 — 연결 이벤트에 시간 남김)**. 실패하면 1초 뒤 재시도. 모드 1·2 진입 시 출력이 바뀌면 광고 재시작(광고 출력은 시작 시 적용).
  - 스캔 콜백: 0xFFFF MSD 중 BEACON(type 0x20, len 2, src 1~5, 자기 제외) → RSSI 링 버퍼(16), 모드 0일 때만 분대장 CMD_BUTTON/EMCON_SET → RX 경로.
- 비콘 프레임: `[01, 20, seq, ID, FF, 02, heading LE]`(heading은 FIXED 0), heading이 바뀌면(1초마다 확인) 새 seq로 다시 만들어 광고 갱신. 간격 `BEACON_INTERVAL_MS` = 500.
- `core/ranging`(호스트 테스트 27 checks): 피어별 최근 15개 RSSI 링, **이동 중앙값**(짝수면 가운데 두 값 평균), 30초 못 들으면 제외·다시 들리면 창 새로 시작, 자기 자신 제외, `ranging_distance_m()`.
- `app`: 비콘 RSSI → ranging, **10초마다 RANGING(0x0E)** 생성(피어가 있을 때) → reporter(비긴급: 모드 2 즉시, 모드 1은 30초 묶음, 모드 0은 만들지 않음). LOG `ranging n=… beacon=1 S2:-67/15`. **음성 수신 중에는 비콘 스캔 일시 중지**(연결 처리량 우선).
- 설정(`config.h`): `RANGING_ENABLE`(1), `BEACON_INTERVAL_MS`(500), `RANGING_SCAN_INTERVAL/WINDOW`(320/160 = 200ms/100ms), `RANGING_REPORT_MS`(10000), `RANGING_STALE_MS`(30000).
- STATS: RANGING은 프로토콜 프레임이라 포함. **비콘 광고는 STATS에 넣지 않음**(광고 이벤트 수는 펌웨어가 세지 않음, 500ms마다 1회 × 3채널 = 시간당 7,200 이벤트로 추정 가능 — EMCON 2에서만).
- 로컬 피드백: 필요 없어 추가 안 함(사용자 지시대로 필요하면 earpiece 경로).
- 컴파일: ID 1 **156,692B / 62,428B**, ID 2 **154,432B / 62,372B**, 경고 `USE_TINYUSB`만. 호스트 테스트 9개 전부 통과.

### 3) 도구
- `mock_leader.py`: RANGING 표시 `S2 -68dBm×15 ≈2.8m`(경로손실 추정), `--pathloss P1m,n`(기본 −59, 2.0), **`mark <m>` / `mark -`**(CSV에 실제 거리 구간 표시).
- `tools/fit_pathloss.py`: CSV의 `mark` 구간별 RANGING(표본 ≥ 5) → 최소제곱 `RSSI = P1m − 10·n·log10(d)` → P1m, n, R², 거리별 평균 RSSI·추정 거리·오차표, `--pathloss` 값 출력. 그래프 2개(RSSI–거리 로그축 + 맞춤선, 실제–추정 + y=x): **matplotlib 있으면 PNG, 없으면 SVG**(의존성 없음). `--self-test` 통과(합성 P1m −61, n 2.3 → −61.0, 2.30).
- 필요 패키지: **matplotlib(PNG용, 선택)** — 미설치. 설치 시 `python3 -m pip install matplotlib`(numpy·pillow 등 함께 설치됨). 승인 전에는 SVG로 대체.

### 4) 시험 절차 (업로드 후)
준비: 보드 1·보드 B 모두 **EMCON 2**, mock_leader로 둘 다 연결(비콘은 연결된 모드 2에서만).
| # | 확인 | 기대 결과 |
|---|---|---|
| 1 | 두 보드 연결 후 20초 | 각 병사 10초마다 `RANGING … S2 -xxdBm×n ≈x.xm`(S1 탭) / `S1 …`(S2), LOG `ranging n=1 beacon=1` |
| 2 | 비콘이 실제로 나가는지(연결 중 비연결형 광고) | 폰 nRF Connect 스캐너에서 이름 없는 광고, Manufacturer Data `0xFFFF` `01 20 …` 가 약 500ms 간격으로 보임(보드당 하나) |
| 3 | S1을 모드 1로 | S1 비콘 멈춤 → S2의 RANGING에서 S1이 30초 뒤 사라짐. S1은 S2 비콘을 계속 받아 RANGING을 30초 묶음으로 보냄 |
| 4 | S1을 모드 0으로 | S1 RANGING 없음(침묵), 스캔은 분대장 방송용 |
| 5 | 음성 전송 중 | `voice …` 동안 비콘 스캔 일시 중지 → 음성 정상(`S1 정상`) |
| 6 | `stats all` | RANGING 프레임이 EMCON2에 집계됨 |

### 5) 경로손실 보정 절차
1. `python3 tools/mock_leader.py --only S1,S2 --log-csv ranging_cal.csv`
2. 두 보드를 **1m** 떨어뜨려(같은 높이, 가능하면 실제 장착 자세) `mark 1` → **30초 이상**(권장 60초) 그대로 둔다.
3. `mark 3` → 3m로 옮겨 30초, `mark 5` → 5m, `mark 10` → 10m, 끝나면 `mark -`, `quit`.
   - 옮기는 동안의 RANGING이 섞이지 않게: 옮긴 뒤 **10초 기다렸다가** `mark`를 입력하는 편이 깨끗함(중앙값 창 15개가 새 거리로 채워질 시간).
4. `python3 tools/fit_pathloss.py ranging_cal.csv --out pathloss.png` → P1m, n, 오차표, 그래프.
5. 이후 `mock_leader.py --pathloss <P1m>,<n>`로 추정 거리 표시.

## 단계 9 + R 보충 — 분대 위치표, 다른 병사 보고의 내 기준 변환, 병사 간 직접 공유 (2026-10-10) — 구현·컴파일 완료, 업로드 보류
- 사용자 결정: matplotlib **설치 안 함**(SVG로 충분). 업로드 보류 — 지금 보드의 단계 7 펌웨어로 분대장 팀원 UNO Q와 통합 시험 먼저, 끝나면 **R+9를 한 번에** 업로드.
- 분대장 팀원 전달 문서: **`docs/leader_squad_sharing_notes.md`**(POS_TABLE 송신, PEER_REPORT 중계, 분대장 비콘 방송 + 병사 비콘 RSSI 측정, 위치 복원 코드 사용법).

### ⚠ 프로토콜 v1.1 추가 예정 (단계 R 표에 더해) — 분대장 팀원에게 전달 필요
| 항목 | 형식 | 비고 |
|---|---|---|
| BEACON 0x20 **src 0** (분대장 비콘) | 광고 MSD 0xFFFF + `[01 20 seq 00 FF 02 heading]`, 500ms | 병사가 RSSI를 재서 RANGING에 **peer_id 0**으로 넣음 |
| RANGING 0x0E peer_id 0 | 기존 형식 그대로, peer 0 = 분대장 | 최대 peers 5(분대장 + 다른 병사 4) = 22B |
| PEER_REPORT 0x14 **병사 직접 방송** | 광고 MSD 0xFFFF + PEER_REPORT 프레임(src = reporter_id 1~5, dst 0x1F), 100ms × 3초, **EMCON 2에서만** | CONTACT일 때 19B(광고 한도 24B 안) |
| PEER_REPORT rx/ry = `0x8000` | "위치 모름" | 보고자가 POS_TABLE을 못 받았을 때(직접 방송), 분대장이 위치표를 안 보냈을 때(mock_leader 중계) |

### 1) 연결 중 광고 + 스캔 동시 가능 여부 (단계 R 확인 결과 + 이번 확장)
- **가능(코어 소스 근거, 장비 미확인)**: 연결(Peripheral) + 비연결형 광고 + 수동 스캔은 SoftDevice가 동시에 스케줄링한다. 단 **광고 세트는 1개**(S140 `BLE_GAP_ADV_SET_COUNT_MAX = 1`).
- 그래서 광고 세트를 **시간으로 나눠 쓴다**: 보고 직접 방송(3초) > 비콘(연결된 EMCON 2) > 연결 가능 광고(끊김).
  - 방송 3초 동안 비콘은 멈춘다(RSSI 중앙값 창 15개·30초 유지라 영향 거의 없음).
  - **EMCON 2인데 분대장과 끊겨 있으면** 방송 3초 동안 연결 가능 광고도 멈춘다(분대장 재연결이 3초 늦어질 수 있음). 분대장이 없을 때야말로 직접 공유가 필요하므로 방송을 우선했다.
- 대안(필요 시, 미구현): 비콘 프레임에 마지막 보고를 붙여 한 광고로 보내기(8 + 19 = 27B > 24B라 CONTACT는 안 들어감 → 보고 축약 형식이 필요), 또는 Extended Advertising(BLE 5, 광고 세트 여럿 필요 — S140 6.1.1은 1개라 불가).
- 수신: 다른 병사 방송은 **모든 모드에서 스캔으로 수신만**(EMCON 0 침묵 스캔에서도 받음, 전파 방출 없음). EMCON 1/2 스캔은 `RANGING_ENABLE || PEER_ADV_ENABLE`이면 켜짐(음성 수신 중엔 일시 중지).

### 2) 펌웨어 구현
- `app/squad_map`(Arduino 비의존, 호스트 테스트): POS_TABLE 저장, `squad_map_pos`(id 0이 없으면 원점), `squad_map_rally_az`(내 위치 → 분대장 방위, 1m 안이면 없음), `squad_map_peer`(PEER_REPORT → 내 기준 시계·거리 구간).
  - 원 보고 4종(CONTACT/SUSPICIOUS/HAZARD/CASUALTY_FOUND)만 재생. 그 외·내 보고·payload 오류는 무시(LOG).
  - 보고자 위치 = PEER_REPORT rx/ry, `0x8000`이면 내 POS_TABLE의 보고자 항목.
  - **POS_TABLE 전**: 보고자 기준 방향 그대로(azimuth를 내 heading 기준 시계로, 거리 구간은 원 보고 값) + LOG `no POS_TABLE: reporter frame`(CLAUDE.md §6.7).
  - **방향 미상 보고(azimuth 0xFFFF)**: 표적 위치를 모르므로 **보고자 쪽 방향·거리**로 재생 + LOG `no az: toward reporter`(내 판단 — 다른 방식을 원하면 알려 주세요).
- `phrases_for_peer`: "적 3, 2시, 근거리" = `enemy n3 c2 near`, 징후 `suspicious c2 mid`, 폭발물 `hazard …`, 부상자 `casualty …`.
- `commands`: POS_TABLE → 저장 + LOG `pos_table n=6 me=(-100,0)dm rally_az=90`. PEER_REPORT(분대장 src 0 또는 병사 직접 방송 src = reporter_id) → **중복 제거(보고자, 원 보고 type, 원 payload CRC, 10초)** → 재생(일반 우선순위) + LOG `PLAY: enemy n3 c1 near (peer S2 via relay brg=22 r=54m)`, 두 번째는 `dup (already played)`.
  - 판정에 seq를 못 쓰는 이유: 분대장 중계 PEER_REPORT에는 원 보고 seq가 없다. 같은 내용의 보고를 10초 안에 또 하면 한 번만 들림(의도적 반복은 10초 뒤).
  - **RALLY 방향**: POS_TABLE의 내 위치 → 분대장 방위(없으면 지금처럼 방향 없이 "집결").
- `reporter`: 4종 보고를 **EMCON 2에서** NUS로 보낸 뒤 같은 보고를 PEER_REPORT 형식으로 **광고 3초 방송**(`radio_broadcast`), LOG `peer adv CONTACT seq=… len=19 3s`. EMCON 1(최소)·0(침묵)에서는 방송하지 않음.
- `hal/radio`: 광고 상태 `ADV_REPORT` 추가(최우선, 100ms 간격, 3초 뒤 자동 해제). 스캔 콜백: BEACON은 **src 0(분대장)도** 받음, PEER_REPORT(src 1~5, 자기 제외, len 검사) → RX 링(연결 RX와 같은 경로), **같은 (src, seq) 반복은 5초 동안 콜백에서 버림**(RX 링·음성 청크 보호).
- `core/ranging`: 피어 0(분대장) 허용 → RANGING에 peer 0 포함. LOG `ranging n=2 beacon=1 L0:-70/15 S2:-67/15`.
- 설정(`config.h`): `PEER_ADV_ENABLE`(1), `PEER_ADV_MS`(3000), `PEER_ADV_INTERVAL_MS`(100), `PEER_ADV_REPEAT_MS`(5000), `PEER_DEDUP_WINDOW_MS`(10000).
- STATS: 직접 방송 광고는 비콘처럼 STATS에 넣지 않음(광고 이벤트, 연결 프레임 아님). 3초 × 10회/초 × 3채널 ≈ 보고당 90 광고 패킷.

### 3) 보드 A `firmware/diag/LeaderBeacon` — "분대장 위치 비콘" 모드
- 명령 방송이 없을 때 BEACON(0x20, src 0, heading 0xFFFF)을 **500ms 간격으로 계속** 광고(기본 켜짐, LED4 = 위치 비콘 중). 명령 방송(3초) 중에는 멈췄다가 끝나면 재개.
- 병사 비콘을 수동 스캔(200ms 중 150ms) → USB `BCN <src> <rssi> <heading>`. USB `beacon on|off`로 켜고 끔.
- 맥(bleak)은 비연결형 광고를 띄울 수 없어(CoreBluetooth 제약) 보드 A가 대신 방송·측정한다. 이때 "분대장 위치" = 보드 A 위치.
- 컴파일: **125,884B / 15,544B**.

### 4) 도구
- **`tools/squad_localize.py`**(표준 라이브러리만, numpy 없음 — 승인 불필요): 프리셋 대형, RSSI → 거리, N×N 행렬(양방향 평균·한쪽·대형 값 채움), 고전 MDS(야코비), **분대장 원점 + 대형 기준 회전/반사 정렬**, POS_TABLE 변환, 표적 변환(펌웨어 core/geo와 같은 규칙). `--self-test` 통과, `--demo`.
- `mock_leader.py`:
  - `pos <wedge|line|column|auto> [targets]` — POS_TABLE(분대장 id 0 + S1~S5). `auto` = RANGING 병사 줄 + 보드 A 분대장 줄 → squad_localize(정렬 기준 = 마지막 프리셋, 없으면 wedge) → 거리 행렬(실측/한쪽/대형 표시)·잔차 출력 후 송신.
  - `peer <reporter> <az|-> <dist> <count> [targets]` — 수동 PEER_REPORT(CONTACT).
  - `relay on|off`(기본 on) — 병사의 4종 보고를 다른 연결된 병사에게 PEER_REPORT로 자동 중계(재전송은 중계 안 함), 병사별 예상 방향 `▷ S1 기준: 1시 근거리 (방위 22°, 54m)` 표시.
  - `map` — ASCII 대형 지도(북쪽 위, L = 분대장, 1~5, T = 마지막 표적, 120m 밖이면 가장자리 `t`) + 병사별 표적 방향.
  - `dist` — 쌍별 거리: 위치표 vs RSSI 실측(i→j, j→i 각각) ← 단계 9 프롬프트의 "RANGING 실측 거리로 두 병사 간 거리 표시" 옵션.
  - `lbeacon on|off` — 보드 A 위치 비콘. 보드 A의 `BCN` 줄은 화면에 찍지 않고 분대장 줄(최근 15개 중앙값, 30초)로만 씀.
  - RANGING·POS_TABLE·PEER_REPORT 표시 개선(peer 0 = "분대장").
  - 블루투스 없이 가짜 연결로 흐름 확인(pos → S2 CONTACT → S1에 PEER_REPORT 중계, 재전송 미중계, RANGING+BCN → pos auto, peer) — 정상.
- `frame_codec.py`: `POS_UNKNOWN = -32768` 추가.

### 5) 시연 시나리오 (호스트 테스트 `test_squad` 67 checks로 기대값 검증)
S2가 보고, S1이 듣는다(heading 0, 간격 10m). 같은 표적이 대형에 따라 다르게 들린다.
| # | S2 보고 | 쐐기(wedge) | 횡대(line) | 종대(column) |
|---|---|---|---|---|
| 1 | 적 3, 방위 0(12시), 근거리 | 적 3, **1시**, 근거리 | 적 3, **1시**, 근거리 | 적 3, **12시**, 근거리 |
| 2 | 적 2, 방위 90(3시), 근거리 | 적 2, **3시**, 근거리 | 적 2, **3시**, 근거리 | 적 2, **4시**, 근거리 |
| 3 | 부상자, 방위 300(10시), 근거리 | 부상자, **10시**, 근거리 | 부상자, **11시**, 근거리 | 부상자, **9시**, 근거리 |
| RALLY | 분대장 "집결" | S1 **2시** 집결 / S2 **11시** | S1 **3시** | S1 **6시** |
- 간격 10m에 근거리 표적 50m라 차이가 1~2시 정도다. 시연에서 크게 보이려면 3번 시나리오(세 대형 모두 다름)와 RALLY를 쓰는 것을 권장.
- 추가 검증: heading 90이면 시나리오 1(횡대)이 10시, 폭발물(거리 없음 = 100m) 중거리, 방향 미상 → 보고자 쪽, POS_TABLE 전 보고자 기준, 직접 방송 0x8000 → 내 위치표 사용, 거부 3종, 방송 프레임 19B.

### 6) 컴파일 (2026-10-10)
| 대상 | Flash | RAM |
|---|---|---|
| SoldierNode ID 1 | **167,436B** (20%) | **62,708B** |
| SoldierNode ID 2 | **166,112B** | **62,652B** |
| LeaderBeacon(보드 A) | 125,884B | 15,544B |
- 경고 `USE_TINYUSB`만. 호스트 테스트 10개 전부 통과(ranging 30, squad 67 checks), C99·ASCII 검사 통과.
- 단계 R 대비 Flash +10.7KB(sinf/cosf 등 표적 계산, 문자열).

### 7) 업로드 계획 (분대장 통합 시험 뒤, 승인 후)
1. earpiece.py·mock_leader 종료 → 보드 1(ID 1) RESET 두 번 → 업로드 → "Device programmed" 확인.
2. 보드 B(ID 2) 같은 절차.
3. 보드 A(LeaderBeacon) 같은 절차(위치 비콘·BCN 출력 추가).

### 8) 시험 절차 (업로드 후)
준비: `python3 tools/mock_leader.py --only S1,S2 --beacon-port <보드 A 포트> --log-csv s9.csv`, earpiece.py 두 탭(S1·S2), 두 병사 EMCON 2.
| # | 확인 | 기대 결과 |
|---|---|---|
| 1 | `pos line` | 두 병사 LOG `pos_table n=6 me=(-100,0)dm rally_az=90` / `(100,0) rally_az=270`, 지도 출력 |
| 2 | S2에서 조이스틱 12시 근거리 + 버튼1 세 번 | S2 `peer adv CONTACT … 3s`, mock_leader 중계 `▷ S1 기준: 1시 근거리`, **S1 이어폰 "적 3, 1시, 근거리" 한 번만**, S1 LOG에 relay/adv 중 하나는 `dup (already played)` |
| 3 | `pos column` 후 같은 보고 | S1 "적 3, 12시, 근거리" (대형별로 방향이 바뀜) |
| 4 | `relay off` 후 S2 보고 | S1은 직접 방송만으로 재생(`via adv`) → **분대장 없이 병사끼리 공유** 확인 |
| 5 | S2를 EMCON 1로, `relay off` 후 보고 | 방송 없음 → S1 재생 없음(EMCON 2에서만 방송) |
| 6 | `cmd rally` | S1 "3시 집결"(횡대) / "6시 집결"(종대), S2 "9시 집결"(횡대) |
| 7 | `pos line` 후 `peer 2 0 near 3`(수동 PEER_REPORT) | S1 "적 3, 1시, 근거리" |
| 8 | 20초 뒤 RANGING | S1·S2 RANGING에 `분대장 -xxdBm` 포함(보드 A 위치 비콘), `dist`에 분대장 줄 표시 |
| 9 | `pos auto` | 거리 행렬(실측 3/3쌍), 잔차, POS_TABLE 송신, 지도 |
| 10 | 폰 nRF Connect | S2 보고 순간 3초간 `0xFFFF 01 14 …` 광고(100ms), 평소엔 `01 20 …`(500ms) |

### 남은 문제
- 연결 중 광고 세트 전환(비콘 ↔ 방송)과 스캔 동시 동작은 **장비 시험 전**.
- RSSI 위치 복원은 방위를 대형에 맞춰 정하므로 실제 방위와 다를 수 있다(GPS/나침반 없음).
- 시나리오 차이가 작음(간격 10m vs 근거리 50m) — 시연 거리 설정은 사용자 판단.
