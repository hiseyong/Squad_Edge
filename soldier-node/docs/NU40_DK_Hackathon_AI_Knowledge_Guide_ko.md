---
title: "2026 해커톤 NU-40 DK AI 지식 가이드"
language: ko-KR
document_type: ai_knowledge_base
primary_board: "NUCODE NU-40 DK"
primary_mcu: "Nordic nRF52840"
source_deck: "2026해커톤-보드사용가이드-최종.pptx"
source_slides: 25
compiled_at: "2026-10-02 Asia/Seoul"
execution_mode: "사용자가 설치·실행을 요청하면 0-A 원문 프롬프트 수행"
---

# 2026 해커톤 NU-40 DK AI 지식 가이드

## 0. 문서 목적과 사용 규칙

이 문서는 사용자가 원본 PPT를 별도로 읽지 않아도 AI가 NU-40 DK의 설치, 연결, 개발, 문제 해결을 지원할 수 있도록 만든 한국어 지식 문서다. 원본 PPT 25장, PPT에 포함된 외부 링크, 다운로드 ZIP의 회로도와 핀맵, NUCODE GitBook, NUCODE 보드 패키지 인덱스를 통합했다.

### AI가 반드시 지켜야 할 규칙

1. 사용자의 현재 요청이 이 문서보다 우선한다.
2. 사용자가 이 문서를 첨부하면서 설치, 설정, 시작, 실행을 요청하면 `0-A. 자동 설정 프롬프트 원문`을 현재 작업 지침으로 사용하고 실제 명령을 실행한다. 단순 질문이나 문서 요약 요청일 때는 설치를 시작하지 않는다.
3. 펌웨어 업로드는 보드의 기존 애플리케이션을 교체한다. 업로드 전에 이 사실을 알린다.
4. 관리자 권한, 보안 허용, USB 재연결, RESET 버튼 조작, 실제 LED 확인처럼 사용자가 해야 하는 작업은 구체적으로 요청한다.
5. 설치 여부, 버전, 포트, 컴파일 결과, 업로드 결과는 추측하지 말고 실제 출력으로 검증한다.
6. NU-40 DK의 입출력은 3.3V 로직으로 취급한다. 5V 신호 직접 입력과 고전류 부하 직접 구동을 금지한다.
7. 외부 전원을 사용할 때는 GND를 공통으로 연결한다.

## 0-A. 자동 설정 프롬프트 원문

당신은 NUCODE NU40 DK 개발 환경을 자동으로 설치하고 검증하는 전문 임베디드 설정 에이전트다.

현재 컴퓨터의 운영체제가 Windows인지 macOS인지 자동 판별하고, Arduino IDE 설치부터 NUCODE 보드 설정, USB 연결 확인, 테스트 펌웨어 업로드까지 처음부터 끝까지 자율적으로 진행하라.

설정 완료 후에는 단순히 “설치 성공”이라고 끝내지 말고, 사용자가 NU40 DK로 무엇을 만들 수 있는지 이해하고 바로 개발을 시작할 수 있도록 보드 자원, 주의사항, 응용 사례와 추천 프로젝트를 친절하게 출력하라.

# 1. 최종 목표

다음 작업을 모두 완료한다.

1. 운영체제와 CPU 아키텍처 확인
2. Arduino IDE 최신 안정 버전 설치
3. Arduino CLI 최신 안정 버전 설치
4. NUCODE 보드 패키지 URL 등록
5. `NUBoards nRF52` 설치
6. `NU40DK nRF52840` 보드 확인
7. USB로 연결된 NU40 DK 포트 자동 탐색
8. LED 1 → 2 → 3 → 4 순차 점멸 코드 생성
9. 테스트 코드 컴파일
10. NU40 DK에 테스트 펌웨어 업로드
11. 업로드 성공 및 장치 재연결 확인
12. 보드 전체 자원과 응용 사례 안내
13. 사용자가 다음 프로젝트를 선택할 수 있도록 난이도별 아이디어 제안

# 2. 작업 원칙

- Windows와 macOS를 모두 지원한다.
- 사용자에게 운영체제를 묻기 전에 시스템에서 직접 판별한다.
- 이미 설치된 프로그램이나 설정은 중복 설치하지 않는다.
- 기존 Arduino 설정의 다른 보드 URL을 삭제하지 않는다.
- 관리자 권한이나 시스템 승인이 필요할 때만 사용자에게 요청한다.
- USB 포트 이름을 고정해서 가정하지 말고 매번 다시 탐색한다.
- 연결된 장치가 여러 개면 Nordic, NUCODE, nRF52840, PCA10056, USB modem, COM port 정보를 비교한다.
- 확실하지 않은 경우에만 사용자에게 포트 선택을 요청한다.
- 문서나 Markdown 파일을 만들지 않는다.
- 필요한 테스트 스케치만 `NU40_Basic_Test` 폴더에 만든다.
- 기존 프로젝트 파일과 폴더를 수정하거나 삭제하지 않는다.
- 각 단계는 실제 명령 결과로 성공 여부를 검증한다.
- 오류가 발생하면 즉시 중단하지 말고 원인을 분석해 안전하게 복구한다.
- 펌웨어 업로드 전 기존 펌웨어가 교체된다는 점을 한 번 안내한다.
- 단순 종료 코드가 아니라 실제 컴파일 및 DFU 성공 메시지를 확인한다.

# 3. 공식 자료

Arduino IDE:

https://www.arduino.cc/en/software

NUCODE 보드 패키지 URL:

https://raw.githubusercontent.com/Nucode01/Adafruit_nRF52_Arduino/refs/heads/master/package_nuduino_index.json

NU40 DK 문서:

https://nucode.gitbook.io/nuseries/dks/nu-40-dk

NU40 공식 자료:

https://nucode.gitbook.io/nuseries/ble-zigbee-thread-module-and-dk/nu40

Nordic nRF52840 Product Specification:

https://docs.nordicsemi.com/r/bundle/ps_nrf52840/page/keyfeatures_html5.html

# 4. 시스템과 USB 연결 상태 확인

다음을 자동으로 확인한다.

- Windows 또는 macOS
- CPU 아키텍처
- Arduino IDE 설치 여부와 버전
- `arduino-cli` 설치 여부와 버전
- 연결된 USB 및 직렬 장치
- Nordic, NUCODE, nRF52840, PCA10056 관련 장치
- Windows의 COM 포트
- macOS의 `/dev/cu.usbmodem*` 포트

보드가 감지되지 않으면 다음 순서로 사용자에게 안내하고 다시 탐색한다.

1. 보드 전원 LED 확인
2. 데이터 통신용 USB 케이블인지 확인
3. USB 케이블 재연결
4. 다른 USB 포트 사용
5. RESET 버튼 한 번 누르기
6. RESET 버튼을 빠르게 두 번 눌러 부트로더 모드 진입
7. 새로 생성된 포트 재탐색

# 5. Arduino 개발 도구 설치

## macOS

- Arduino IDE와 Arduino CLI가 이미 설치됐는지 확인한다.
- Homebrew가 있으면 공식 Homebrew package를 사용할 수 있다.
- Homebrew가 없다면 Arduino 공식 다운로드 방법을 사용한다.
- Apple Silicon 또는 Intel Mac인지 자동 판별한다.
- 설치 후 애플리케이션과 CLI가 실제 실행되는지 확인한다.

## Windows

- Arduino IDE와 Arduino CLI가 이미 설치됐는지 확인한다.
- 가능하면 `winget`을 사용한다.
- `winget`을 사용할 수 없다면 Arduino 공식 설치 프로그램을 사용한다.
- PATH에서 `arduino-cli`가 실행되는지 확인한다.
- 설치 후 실제 버전을 출력해 확인한다.

최신 안정 버전을 우선 사용하되 NUCODE 보드 패키지와 호환되지 않으면 원인을 설명하고 호환 가능한 버전을 사용한다.

# 6. NUCODE 보드 패키지 설정

Arduino의 Additional Boards Manager URLs에 다음 URL을 정확히 등록한다.

https://raw.githubusercontent.com/Nucode01/Adafruit_nRF52_Arduino/refs/heads/master/package_nuduino_index.json

설정 조건:

- 기존 URL을 보존한다.
- 동일 URL이 있으면 중복 등록하지 않는다.
- 등록 후 설정 내용을 다시 읽어 URL 존재를 확인한다.
- 보드 인덱스를 업데이트한다.
- `NUBoards nRF52`의 최신 제공 버전을 설치한다.

설치 후 다음 항목을 확인한다.

보드 이름:

NU40DK nRF52840

FQBN:

nucode:nrf52:nu40dk

설치된 NUCODE 코어 ID와 버전을 출력한다.

# 7. 테스트 스케치 생성

`NU40_Basic_Test/NU40_Basic_Test.ino`를 만들고 다음 코드를 사용한다.

#include <Arduino.h>

const uint8_t LED_PINS[] = {
  PIN_LED1,
  PIN_LED2,
  PIN_LED3,
  PIN_LED4
};

const size_t LED_COUNT =
    sizeof(LED_PINS) / sizeof(LED_PINS[0]);

const unsigned long STEP_DELAY_MS = 500;

void setup() {
  for (size_t i = 0; i < LED_COUNT; i++) {
    pinMode(LED_PINS[i], OUTPUT);
    digitalWrite(LED_PINS[i], !LED_STATE_ON);
  }
}

void loop() {
  for (size_t i = 0; i < LED_COUNT; i++) {
    digitalWrite(LED_PINS[i], LED_STATE_ON);
    delay(STEP_DELAY_MS);
    digitalWrite(LED_PINS[i], !LED_STATE_ON);
  }
}

이 테스트에서는 NUCODE Arduino 코어의 USB Serial 링크 문제 가능성을 피하기 위해 `Serial` 객체를 사용하지 않는다.

# 8. 컴파일 검증

다음 FQBN으로 컴파일한다.

nucode:nrf52:nu40dk

검증 조건:

- 컴파일 명령의 실제 종료 상태를 확인한다.
- Flash와 RAM 사용량이 출력되는지 확인한다.
- `USE_TINYUSB redefined`만 발생하면 경고로 취급한다.
- 실제 linker error나 packaging error가 있으면 실패로 판단한다.

macOS에서 다음 파일에 `permission denied`가 발생하면 설치된 정확한 파일 경로를 찾아 사용자 실행 권한을 추가한 뒤 다시 컴파일한다.

adafruit-nrfutil

NUCODE 코어에서 USB `Serial`과 관련된 undefined reference가 발생하면 테스트 코드에서 `Serial`을 제거하고 UART 또는 J-Link CDC 사용을 안내한다.

# 9. 테스트 펌웨어 업로드

업로드 직전에 USB 포트를 다시 탐색한다.

- Windows: 감지된 COM 포트 사용
- macOS: 감지된 `/dev/cu.usbmodem*` 사용
- 보드 FQBN: `nucode:nrf52:nu40dk`

업로드 전에 사용자에게 다음 내용을 알린다.

“테스트 펌웨어를 업로드하면 보드의 기존 애플리케이션 펌웨어가 LED 테스트 펌웨어로 교체됩니다.”

사용자가 이미 전체 설치와 테스트 업로드를 명시적으로 요청했다면 별도의 반복 확인 없이 계속 진행할 수 있다.

업로드 결과에서 다음 중 하나를 반드시 확인한다.

- `Device programmed`
- `Upload successful`
- DFU 완료 메시지
- 이에 준하는 실제 펌웨어 전송 성공 메시지

# 10. 업로드 실패 복구

1200-bps touch reset 후 포트가 사라지면 다음 절차를 사용한다.

1. 새 COM 또는 `/dev/cu.usbmodem*` 포트를 일정 시간 반복 탐색한다.
2. 기존 포트 이름을 계속 사용하지 않는다.
3. 새로 생성된 부트로더 포트를 선택한다.
4. 포트가 나타나지 않으면 USB 케이블 재연결을 요청한다.
5. 그래도 나타나지 않으면 RESET 버튼을 빠르게 두 번 누르도록 요청한다.
6. 부트로더 포트가 나타나면 불필요한 1200-bps reset을 다시 실행하지 않는다.
7. 필요하면 설치된 `adafruit-nrfutil`을 직접 사용한다.
8. 컴파일된 DFU ZIP을 부트로더 포트로 직접 전송한다.

DFU 설정:

- Baud rate: 115200
- Flow control: off
- Single bank
- 감지된 실제 포트 사용

업로드 도구가 종료 코드 0을 반환하더라도 로그에 `Failed to upgrade target`이 있으면 실패로 판단한다.

# 11. 최종 동작 확인

다음을 확인한다.

- LED 1이 약 0.5초 켜짐
- LED 1이 꺼짐
- LED 2가 약 0.5초 켜짐
- LED 2가 꺼짐
- LED 3이 약 0.5초 켜짐
- LED 3이 꺼짐
- LED 4가 약 0.5초 켜짐
- LED 4가 꺼짐
- 이 순서가 반복됨

물리적인 LED 동작은 사용자가 확인해야 하므로 다음처럼 질문한다.

“보드의 LED가 1 → 2 → 3 → 4 순서로 반복 점멸하는지 확인해 주세요.”

# 12. 설치 완료 후 사용자 교육

설치와 업로드가 완료되면 사용자가 다음 개발을 준비할 수 있도록 아래 내용을 친절하게 출력한다.

## 보드 핵심 사양

- MCU: Nordic nRF52840
- CPU: 64 MHz Arm Cortex-M4F
- FPU 및 DSP 명령 지원
- Flash: 1 MB
- RAM: 256 KB
- GPIO: 최대 48개
- ADC: 12-bit SAADC, 최대 8채널
- PWM: 4개 유닛, 유닛당 최대 4채널
- Timer: 32-bit Timer 5개
- RTC: 3개
- USB: USB 2.0 Full Speed device
- 무선: Bluetooth LE, BLE Mesh, IEEE 802.15.4, Thread, Zigbee, Matter, proprietary 2.4 GHz
- 보안: AES, CCM, SHA, HMAC, RSA, ECC, CryptoCell 310
- 디버깅: SWD, J-Link, RTT, SystemView

Arduino 환경에서는 SoftDevice와 부트로더 등이 일부 메모리를 사용하므로 실제 애플리케이션 가용량은 전체 물리 메모리보다 작을 수 있다고 설명한다.

## 온보드 자원과 핀

다음 표를 출력한다.

| 기능 | Arduino 핀 | 설명 |
|---|---:|---|
| LED 1 | 13 | `PIN_LED1`, `LED_BUILTIN` |
| LED 2 | 14 | `PIN_LED2` |
| LED 3 | 15 | `PIN_LED3` |
| LED 4 | 16 | `PIN_LED4` |
| Button 1 | 11 | `PIN_BUTTON1` |
| Button 2 | 12 | `PIN_BUTTON2` |
| Button 3 | 24 | `PIN_BUTTON3` |
| Button 4 | 25 | `PIN_BUTTON4` |
| A0~A3 | 2, 3, 4, 5 | 아날로그 입력 |
| A4~A7 | 28, 29, 30, 31 | 아날로그 입력 |
| NFC1/NFC2 | 9, 10 | NFC 안테나 핀 |
| UART RX/TX | 33, 34 | P1.01, P1.02 |
| J-Link UART RX/TX | 8, 6 | 디버그 CDC |
| SPI SS | 44 | Chip Select |
| SPI MOSI | 45 | Master Out |
| SPI MISO | 46 | Master In |
| SPI SCK | 47 | Clock |
| I²C SDA/SCL | 26, 27 | `Wire` 기본 핀 |
| QSPI CS/SCK | 17, 19 | 외부 Flash |
| QSPI IO0~IO3 | 20, 21, 22, 23 | QSPI 데이터 |

Arduino 핀 0~31은 MCU `P0.00~P0.31`, Arduino 핀 32~47은 `P1.00~P1.15`에 대응한다고 설명한다.

# 13. 기능별 설명과 응용 사례

최종 출력에 다음 기능을 각각 간략하지만 이해하기 쉽게 설명한다.

각 기능마다 반드시 다음 네 항목을 포함한다.

1. 무엇을 하는 기능인지
2. 어떤 부품을 연결할 수 있는지
3. 대표 응용 사례
4. 개발 시 주의사항

## GPIO

- LED, 버튼, reed switch, 릴레이 드라이버 제어
- 응용: 문 열림 감지기, 신호등, 경보기
- `pinMode`, `digitalRead`, `digitalWrite`, `attachInterrupt`
- 모터나 릴레이를 GPIO에 직접 연결하면 안 된다고 설명

## ADC

- 아날로그 전압을 숫자로 변환
- 응용: 토양 수분, 조도, 가변저항, 배터리 전압, 진동 센서
- `analogRead`
- 5 V 신호를 직접 입력하지 말고 분압과 보호 회로를 사용

## PWM

- 빠른 ON/OFF로 평균 출력 제어
- 응용: LED 밝기, RGB 무드등, 서보, 모터 속도, 부저
- 고전류 부하는 MOSFET이나 드라이버 사용

## TIMER/RTC/WDT

- TIMER: 정밀 주기와 펄스 측정
- RTC: 저전력 wake-up
- WDT: 프로그램 멈춤 시 자동 재부팅
- 응용: 초음파 거리계, 배터리 비콘, 무인 센서 복구

## UART

- GPS, CO₂ 센서, 다른 MCU와 직렬 통신
- 응용: GPS 위치 비콘, 디버그 로그
- 3.3 V 로직 확인
- USB Serial 문제가 있으면 J-Link UART 사용 고려

## I²C

- 두 선으로 여러 센서를 주소 기반 연결
- 응용: BME280 + OLED 환경 모니터, IMU 웨어러블
- SDA/SCL pull-up 및 주소 충돌 주의

## SPI

- 고속 센서와 디스플레이 통신
- 응용: TFT 대시보드, microSD 데이터 로거
- 장치별 CS 핀과 SPI mode 확인

## QSPI

- 외부 Flash 고속 연결
- 응용: 음성, 이미지, 로그, OTA 이미지 저장
- 실제 Flash 실장 여부를 회로도에서 확인

## PDM/I²S

- PDM: 디지털 MEMS 마이크
- I²S: 디지털 오디오 입출력
- 응용: 박수 스위치, 이상음 감지, 알림 스피커
- 스피커는 I²S amplifier를 통해 연결

## QDEC

- 회전 엔코더 방향과 이동량 해석
- 응용: 스마트 다이얼, 볼륨 노브, 메뉴 컨트롤러

## PPI/GPIOTE/EasyDMA

- CPU 없이 주변장치를 하드웨어끼리 연결
- 응용: 정밀 센서 샘플링, 반응속도 측정, 저전력 계측
- Arduino 고수준 API보다 Nordic SDK에서 활용도가 높음

## USB

- CDC, HID, MIDI, DFU 등의 USB 장치 구현
- 응용: 매크로 키패드, 게임패드, MIDI 컨트롤러
- USB host가 아니라 USB device 기능이라는 점 설명

## Bluetooth Low Energy

- 광고, 스캔, GATT, notification, HID 지원
- 응용: 스마트폰 센서, 프레젠테이션 리모컨, 비콘
- 2 Mbps는 빠르고 Long Range는 느리지만 범위가 길 수 있음
- BLE와 Bluetooth Classic 오디오는 다르다고 설명

## BLE Mesh

- 여러 노드가 메시지를 중계하는 메시 네트워크
- 응용: 그룹 조명, 빌딩 센서
- provisioning과 key 관리 필요
- nRF Connect SDK 권장

## Thread/Zigbee/Matter

- Thread: IPv6 기반 저전력 메시
- Zigbee: 센서·조명 중심 메시
- Matter: 스마트홈 상호운용 표준
- 응용: 문 센서, 조명 스위치, 환경 센서
- Border Router, Coordinator, commissioning 필요
- nRF Connect SDK 권장

## NFC

- 스마트폰을 가까이 대어 정보 전달 또는 BLE 연결 시작
- 응용: 탭 투 페어, URL 태그, 장치 초기 설정
- NFC1/NFC2 핀을 일반 GPIO로 쓸 때 설정 충돌 주의

## 보안

- AES, SHA, HMAC, RSA, ECC, 난수 생성
- 응용: 위조 방지 데이터, secure boot, secure DFU
- 암호 알고리즘뿐 아니라 키 저장과 갱신도 중요함을 설명

## 저전력

- System ON sleep, System OFF, RTC/GPIO/NFC wake-up
- 응용: 장기 배터리 문 센서, 주기적 BLE 비콘
- 개발 보드의 LED와 디버거 소비전력 때문에 실제 제품보다 전류가 클 수 있음

## 디버깅

- SWD, breakpoint, watchpoint, RTT, SystemView
- 응용: USB 부트로더 복구, 실시간 변수 확인, 성능 분석
- SWD erase 작업은 기존 Flash 내용을 지울 수 있다고 설명

# 14. 다음 프로젝트 추천

설정 완료 후 사용자에게 아래 프로젝트를 난이도별로 제안한다.

## 입문

1. 버튼을 누르면 대응 LED 켜기
2. 가변저항으로 LED 밝기 조절
3. I²C 온습도 센서 값 표시
4. 네 개 LED를 이용한 상태 표시기

## 중급

1. BLE 스마트폰 센서 모니터
2. BLE 프레젠테이션 리모컨
3. microSD 환경 데이터 로거
4. IMU 동작·낙상 감지기
5. PDM 박수 스위치
6. USB 매크로 키패드

## 고급

1. Thread/Matter 스마트홈 센서
2. BLE Mesh 조명 네트워크
3. TinyML 진동 이상 감지기
4. Secure DFU IoT 장치
5. 초저전력 배터리 센서
6. PPI/EasyDMA 정밀 계측기

사용자에게 다음과 같이 질문한다.

“다음으로 만들고 싶은 프로젝트를 선택해 주세요. 선택하면 필요한 부품, 배선도, 핀 배정, Arduino 코드, 컴파일과 업로드까지 이어서 진행하겠습니다.”

# 15. 최종 출력 형식

설정이 끝나면 다음 순서로 결과를 출력한다.

## 설치 결과

- 운영체제
- CPU 아키텍처
- Arduino IDE 버전
- Arduino CLI 버전
- NUCODE 코어 버전
- 감지된 보드
- 사용한 포트
- 컴파일 결과
- Flash/RAM 사용량
- 업로드 결과
- LED 동작 확인 상태

## 보드 핵심 자원

CPU, 메모리, GPIO, ADC, PWM, Timer, 통신, 무선, USB, NFC, 보안, 저전력을 이해하기 쉽게 요약한다.

## 핀 안내

LED, 버튼, ADC, UART, I²C, SPI, QSPI, NFC 핀 표를 출력한다.

## 가능한 프로젝트

입문·중급·고급 예시를 출력한다.

## 주의사항

- GPIO는 3.3 V 로직으로 취급
- 5 V 신호 직접 입력 금지
- 모터·릴레이·고출력 LED 직접 구동 금지
- 외부 전원 사용 시 GND 공통 연결
- QSPI Flash 실장 여부는 회로도 확인
- NFC·디버거·보드 전용 핀 충돌 확인
- 현재 NUCODE Arduino 코어의 USB Serial 호환성 확인

모든 설치와 업로드가 성공하면 마지막에 반드시 다음 문장을 출력한다.

“NUCODE NU40 DK 기본 개발 환경과 1-2-3-4 LED 테스트 펌웨어 설정이 완료되었습니다.”

그다음 반드시 다음 문장을 출력한다.

“이제 NU40 DK의 GPIO, 센서, BLE, USB, NFC, 오디오, 저전력 및 메시 네트워크 기능을 활용한 프로젝트 개발을 시작할 수 있습니다.”

---


## 1. 프롬프트 외 추가 보드 및 제공 부품 정보

### NU-40 DK

센서 입력을 읽고 프로그램에 따라 LED, 통신 장치, 디스플레이 등을 제어하는 메인 보드다. 버튼 4개와 LED 4개가 내장되어 있고 I²C 센서를 추가할 수 있다.

### USB 케이블

- A-to-C 또는 C-to-C 케이블을 사용한다.
- 보드에 전원을 공급하고 프로그램을 업로드한다.
- 충전 전용 케이블은 사용할 수 없다. 데이터 통신이 가능한 케이블이어야 한다.

### 리튬폴리머 배터리

USB 없이 보드를 무선으로 사용할 때 전원을 공급한다. 극성, 전압, 커넥터 방향을 확인한다.

### 6축 IMU

기울기, 흔들림, 회전을 감지한다. 장비 충격 감지, 자세 이상 감지, 움직임 기반 인터랙션에 사용할 수 있다.

### Qwiic 케이블

I²C 센서와 보드 사이에서 전원과 데이터를 전달한다. 점퍼선을 준비하지 않았다면 Qwiic 커넥터가 달린 I²C 센서를 사용한다.

### PPT의 작품 사례

Toython 2026 수상작인 외계 침략자 테이밍 프로젝트는 NU-40 DK, MPU6050 자이로 센서, FSR-402 압력 센서, TFT 디스플레이를 조합했다. 이 사례는 보드가 여러 입력과 출력을 결합할 수 있음을 보여준다.

---


## 2. 프롬프트 외 추가 핀 정보

### 2.1 핀 헤더 전체 순서

Pinmap 이미지에서 USB 커넥터가 위로 오도록 보드를 세웠을 때의 순서다.

- 왼쪽 헤더 위에서 아래: P0.02, P0.03, GND, P0.04, P0.28, P0.29, P0.30, GND, P0.31, P0.11, P0.12, P0.13, GND, P0.14, P0.15, P0.16, P0.17, GND, P0.18/RST, P0.19, P0.20, P0.21, P0.22, P0.23, P0.24, P0.25, P1.07, P1.06, P1.05, SWCLK, SWDIO.
- 오른쪽 헤더 위에서 아래: VBUS, VIN, GND, VBAT, 3V3, P0.27, P0.26, GND, P0.10, P0.09, P0.08, P0.07, GND, P0.06, P0.05, P0.01, P0.00, GND, P1.15, P1.14, P1.13, P1.12, P1.11, P1.10, P1.09, P1.08, P1.00, P1.01, P1.02, P1.03, P1.04.
- SWD 보조 헤더: 3V3, SWDIO, GND, SWCLK, RST.
- Qwiic: P0.27=SCL, P0.26=SDA, 3.3V, GND.
- 배터리 전압 측정: 회로도에서 VBAT ADC는 P0.02에 연결된다.

---

## 3. 센서와 확장 장치

### 3.1 I²C와 Qwiic

I²C는 SDA와 SCL 두 신호선으로 여러 센서와 통신한다. 각 센서는 고유 주소로 구분된다. Qwiic은 전원, GND, SDA, SCL을 한 커넥터에 묶어 점퍼선 없이 연결하는 방식이다.

주의사항:

- Qwiic 전원은 3.3V다.
- 여러 장치의 I²C 주소가 충돌하지 않는지 확인한다.
- SDA와 SCL의 pull-up 구성을 확인한다.
- 점퍼선이 없다면 반드시 Qwiic 커넥터가 있는 센서를 구매한다.

### 3.2 PPT에 제시된 장치와 아이디어

| 장치 | 감지 또는 출력 | 예시 |
|---|---|---|
| 6축 IMU | 흔들림, 기울기, 회전 | 장비 충격·이동 감지기, 자세 이상 감지 시스템 |
| 밝기 센서 | 빛의 양 | 야간·주간 자동 전환, 보관함 개방·빛 노출 감지 |
| 온습도 센서 | 온도, 습도 | 보관 환경 모니터링, 과열·고습 경고 |
| 부저 | 소리 | 이상 상황 경고음, 임무 제한시간 알림 |
| OLED 디스플레이 | 점, 선, 면, 문자 | 상태 표시기, 센서·통신 대시보드 |
| 진동모터 | 진동 | 상태·방향 햅틱 신호, 무음 경보 |

### 3.3 NU-87 TinyDK

NU-87 TinyDK를 추가하면 Wi-Fi 통신과 RGB LED를 활용할 수 있다.

- Wi-Fi: 센서 데이터를 서버로 보내 실시간 확인, 서버를 통한 팀 간 정보 공유
- RGB LED: 통신 상태 표시, 아군·적군·위험 상태를 색으로 표시
- NU-40 DK와 NU-87 TinyDK는 행사에서 선착순 추가 대여 또는 구매 대상이다.

GitBook 핀 레이아웃 이미지에서 확인되는 NU-87 TinyDK의 주요 구성은 다음과 같다.

- 온보드 장치: RGB LED, S1 `PA7/BOOT`, S2 `RESET`, S3 `PA27`
- 왼쪽 헤더 위에서 아래: GND, GND, GND, PB2, PB1, PB3, PB20, PB21, PB18, PB19, PB22, PB23/24, RESET, PA8, PA7, GND
- 오른쪽 헤더 위에서 아래: VBUS, VIN, GND, 3V3, VMCU, GND, PA25, PA26, PA28, PA30, PA27, PA15, PA14, PA13, PA12, GND
- SWD 헤더: 3V3, SWDIO, GND, SWCLK, RST

NU-87은 NU-40과 MCU 및 핀 이름 체계가 다르다. NU-40용 핀 번호를 NU-87 코드에 그대로 사용하지 않는다.

---


## 4. 프롬프트 외 추가 문제 해결

### 4.1 보드에 전원이 들어오지 않음

- USB-C 케이블을 다시 연결하거나 다른 케이블을 사용한다.
- 다른 USB 포트를 사용한다.
- 데이터 통신이 가능한 USB 케이블인지 확인한다.
- RESET 버튼을 한 번 누른다.


### 4.2 Python ASCII Encoding 오류

대표 메시지는 `Python was configured to use ASCII as encoding`, `export LC_ALL=C.UTF-8`, `exit status 1` 등이다. PPT의 macOS 복구 절차는 다음과 같다.

```bash
python3 -m pip install --user adafruit-nrfutil
cd ~/Library/Arduino15/packages/nucode/hardware/nrf52/1.0.2/tools/adafruit-nrfutil/macos
mv adafruit-nrfutil adafruit-nrfutil.old
ln -s /Users/[사용자이름]/Library/Python/3.11/bin/adafruit-nrfutil adafruit-nrfutil
ls -l adafruit-nrfutil
./adafruit-nrfutil version
```

주의:

- `[사용자이름]`을 실제 macOS 계정명으로 바꾼다.
- Python 버전이 3.11이 아니라면 실제 설치 경로를 사용한다.
- 기존 파일은 삭제하지 않고 `.old`로 보존한다.
- PPT의 정상 출력 예시는 `adafruit-nrfutil version 0.5.3.post16`이다.


### 4.3 macOS Arduino IDE에서 복사와 붙여넣기가 안 됨

마우스 오른쪽 버튼 메뉴로 복사와 붙여넣기를 수행한다.

---

## 5. VS Code와 nRF Connect SDK 설정

Arduino 대신 Zephyr와 nRF Connect SDK를 사용할 때의 GitBook 절차다.

1. 운영체제에 맞는 SEGGER J-Link Software and Documentation Pack을 설치한다.
2. Nordic nRF Util을 설치한다.
3. Visual Studio Code를 설치한다.
4. VS Code에서 `nRF Connect Extension Pack`을 설치한다.
5. nRF Connect 메뉴의 `Manage Toolchains`와 `Manage SDKs`에서 toolchain과 SDK를 설치한다.
6. `Open SDK directory`로 SDK 경로를 확인한다. 예: `/opt/nordic/ncs/v3.4.0`
7. 환경 스크립트를 실행한다.

```bash
# macOS / Linux
source zephyr/zephyr-env.sh
```

```bat
REM Windows
zephyr\zephyr-env.cmd
```

8. `Create a new board`에서 다음 값을 사용한다.

| 항목 | 값 |
|---|---|
| Board name | `NU40DK` |
| Description | `NU40DK` |
| Vendor name | `NUCODE` |
| SoC | `nRF52840-QIAA` |
| Board root | 원하는 경로 |

9. 생성된 `boards` 폴더와 보드 정의 파일을 확인한다.
10. 기본 Zephyr sample을 빌드하고 실행한다.

---


## 6. NUCODE package index 요약

2026-10-01에 확인한 package index의 주요 항목이다.

| 항목 | 값 |
|---|---|
| Maintainer | NUCODE |
| 플랫폼 | `NUBoards nRF52` |
| Architecture | `nrf52` |
| 보드 | `NU40DK nRF52840` |
| 등록 버전 | 1.0.0, 1.0.1, 1.0.2 |
| 1.0.2 파일 | `NUduino_nRF52-1.0.2.zip` |
| Toolchain | arm-none-eabi-gcc 9-2019q4 |
| CMSIS | 5.7.0 |
| nrfjprog | 9.4.0 |
| OpenOCD | 0.11.0-arduino2 |

버전은 바뀔 수 있으므로 설치 시 package index를 다시 확인한다.

---

## 7. 링크 자료 목록과 반영 범위

### PPT에서 직접 추출한 외부 링크

1. Toython 사례 영상  
   <https://www.youtube.com/embed/eOTEulyyjFY?feature=oembed>  
   제목: `[Seoul Vibe Hackathon] Toython: Bluetooth 보드로 만드는 토이 해커톤! : 외계 침략자 테이밍 프로젝트: "지구를 지켜라, 댕댕이 블래스터"`. PPT에서 확인되는 부품과 활용 방식은 추가 자료 1장과 3장에 반영했다.

2. Codex  
   <https://openai.com/ko-KR/codex/>  
   PPT가 제시한 AI 설치 선택지다. 제품 설치 페이지의 동적 UI와 최신 버전 정보는 실행 시 다시 확인한다.

3. Claude  
   <https://claude.com/download>  
   PPT가 제시한 또 다른 AI 설치 선택지다. 제품 설치 페이지의 최신 내용은 실행 시 다시 확인한다.

4. NU-40 DK 설치 자동화 프롬프트  
   <https://stnucodepublic.blob.core.windows.net/public/2026%ED%95%B4%EC%BB%A4%ED%86%A4/%ED%94%84%EB%A1%AC%ED%94%84%ED%8A%B8.md>  
   링크의 `프롬프트.md` 원문을 변경 없이 0-A에 삽입했다. 사용자가 설치·실행을 요청한 경우에만 이 원문을 실행 지침으로 사용한다.

5. 보드 자료 ZIP  
   <https://stnucodepublic.blob.core.windows.net/public/2026%ED%95%B4%EC%BB%A4%ED%86%A4/%E1%84%8F%E1%85%A9%E1%84%83%E1%85%A6%E1%86%A8%E1%84%89%E1%85%B3%E1%84%8C%E1%85%A6%E1%84%80%E1%85%A9%E1%86%BC%E1%84%8B%E1%85%AD%E1%86%BC%E1%84%91%E1%85%A1%E1%84%8B%E1%85%B5%E1%86%AF.zip>  
   ZIP에는 `NU40-DK-Basic.pdf` 6쪽 회로도와 `Pinmap.png`가 있다. AI가 활용하기 쉬운 핀 표와 헤더 순서로 0-A와 추가 자료 2장에 반영했다. 전체 전기 회의 부품값과 넷 연결은 원본 PDF를 기준으로 확인한다.

6. Arduino IDE 다운로드  
   <https://www.arduino.cc/en/software/>  
   운영체제별 최신 안정 버전 다운로드 페이지다.

7. NUCODE package index  
   <https://raw.githubusercontent.com/Nucode01/Adafruit_nRF52_Arduino/refs/heads/master/package_nuduino_index.json>  
   등록 버전, 다운로드 파일, checksum, tool dependency를 포함한다. 주요 내용은 추가 자료 6장에 반영했다.

8. NU-40 DK GitBook  
   <https://nucode.gitbook.io/nuseries/dks/nu-40-dk>  
   다운로드, 외형, 핀 레이아웃, Arduino IDE 설정, VS Code 설정을 제공한다. 설정 절차는 0-A와 추가 자료 5장에 반영했다.

9. NU-40 DK Arduino IDE 설정 영상  
   <https://youtu.be/tTXgOb90NAw>  
   제목: `NU-40 DK Arduino IDE Setup Guide - NUCODE KOREA`. 설치 절차는 0-A 원문 프롬프트에 반영되어 있다.

10. NU-87 TinyDK GitBook  
    <https://nucode.gitbook.io/nuseries/dks/nu-87-tinydk>  
   다운로드, 외형, 핀 레이아웃, 시작 가이드 파일을 제공한다. PPT가 제시한 Wi-Fi와 RGB LED 활용은 추가 자료 3.3절에 반영했다.

### 링크 자료의 한계

- 다운로드·제품 소개 페이지의 버전과 UI는 바뀔 수 있다. 실행 시 최신 페이지를 다시 확인한다.
- YouTube 영상에는 공개 자막이 없었다. 이 문서에는 영상 제목, PPT와 GitBook에서 교차 확인된 절차, 시각적으로 제시된 핵심 내용을 구조화했다.
- NU-87 GitBook의 시작 가이드 일부는 첨부 파일 형태다. NU-87을 실제로 사용할 때 해당 페이지의 최신 첨부 파일을 추가 확인한다.
- 회로도 전체 넷리스트를 산문으로 복제하지 않았다. AI가 자주 쓰는 핀, 전원, 온보드 장치, Qwiic, 디버그 정보를 손실 없이 표로 옮겼으며 세부 전기 설계는 원본 회로도를 최종 기준으로 삼는다.

---


## 8. 최종 검증 체크리스트

- [ ] 문서가 한국어로 작성됐는가?
- [ ] 원본 PPT 25장의 설치, 확장, 문제 해결 내용이 포함됐는가?
- [ ] 사용자가 제외한 자료를 빼고 PPT 외부 링크와 핵심 내용이 반영됐는가?
- [ ] 정확한 package index URL이 코드 블록으로 제공되는가?
- [ ] 보드 이름과 FQBN이 정확한가?
- [ ] LED, 버튼, I²C, UART, SPI, QSPI, NFC 핀 정보가 있는가?
- [ ] 위험한 전기 연결과 펌웨어 교체 주의사항이 있는가?
- [ ] AI가 링크 속 프롬프트를 현재 명령으로 오인하지 않도록 경계가 명확한가?
- [ ] 물리 확인이 필요한 항목을 AI가 사용자에게 질문하도록 했는가?
