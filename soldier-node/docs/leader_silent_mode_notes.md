# 분대장(UNO Q) 담당용: 침묵 모드(EMCON 0) 방송 메모

> 병사 단말 쪽에서 정리. 기준은 프로토콜 `docs/squad_ble_protocol_v1.md` §2, §3.2 (v1.0.1).
> 리눅스(BlueZ) 방법은 병사 팀에서 **직접 검증하지 않았다** — 실제 UNO Q에서 확인 필요.

## 1. 병사가 기대하는 광고 (공통)
- **보내기 전에** 연결 모드에서 각 병사에 `EMCON_SET(0)`(0x16) 또는 CMD_BUTTON `SILENCE`(0x0B)를 보내고 연결을 끊는다(§10-6). 병사는 받으면 스스로 연결을 끊고 수동 스캔으로 간다.
- Legacy 광고, **연결·스캔 불가(ADV_NONCONN_IND)**, 간격 **100ms**, **3초** 동안 같은 프레임 반복 후 정지.
- AD 데이터(31B 안): `02 01 06` (Flags) + Manufacturer Specific Data `LL FF FF FF <프레임>`
  - `LL` = 1(타입) + 2(Company ID) + 프레임 길이. CMD_BUTTON(12B)이면 `0F`, EMCON_SET(7B)이면 `0A`.
  - 예(전원 엄폐 270, seq 05): `02 01 06 0F FF FF FF 01 10 05 00 1F 06 02 0E 01 FF 00 01`
- 병사가 받는 프레임: ver 01, **src 00**, `CMD_BUTTON`(0x10) 또는 `EMCON_SET`(0x16)만. 음성은 침묵 모드에서 보내지 않는다.
- 새 명령마다 seq를 바꾼다. 병사 중복 판정 = 같은 (src, seq) + 같은 내용 + 60초 안(병사 측 v1.0.2 제안). 3초 반복은 병사가 한 번만 재생한다.
- 침묵 모드 병사는 **송신하지 않는다**(ACK·보고는 병사 큐에 쌓였다가 모드 1/2로 돌아오면 나감). 분대장은 ACK를 기다리지 않는다.
- 병사를 연결 모드로 되돌리기: 같은 방식으로 `EMCON_SET(1 또는 2)`를 광고 → 병사가 광고를 다시 시작 → 분대장이 재연결.

## 2. 리눅스(BlueZ)에서 직접 광고할 때 필요한 것
- 루트 권한(또는 CAP_NET_ADMIN). 광고 중에는 다른 광고 인스턴스와 겹치지 않게.
- **간격 100ms 설정이 핵심.** 커널 기본 광고 간격은 약 1.28초라 3초에 2~3번밖에 안 나간다.
  - debugfs: `echo 160 > /sys/kernel/debug/bluetooth/hci0/adv_min_interval`, `adv_max_interval`도 160 (단위 0.625ms → 100ms)
- 방법 A — `btmgmt`(간단): Flags는 커널이 관리하므로 데이터에는 MSD만 넣고 `-g`(general discoverable)로 Flags를 붙인다. 연결 불가가 기본(`-c` 넣지 않음), `-t 3`으로 3초 후 자동 제거.
  - 예: `sudo btmgmt add-adv -g -t 3 -d 0FFFFFFF011005001F06020E01FF0001 1` ← 데이터 hex는 위 예의 MSD 부분(공백 없이). 옵션 이름은 BlueZ 버전에 따라 다를 수 있음(`btmgmt add-adv --help`로 확인).
- 방법 B — D-Bus `org.bluez.LEAdvertisingManager1`: `Type = "broadcast"`, `ManufacturerData = {0xFFFF: <프레임>}`, `Timeout = 3`(또는 `Duration`). 간격(`MinInterval/MaxInterval`)은 BlueZ 버전에 따라 실험 기능(`bluetoothd -E`)이 필요할 수 있음.
- 방법 C — HCI 명령(`hcitool cmd 0x08 0x0006/0x0008/0x000A`: 광고 파라미터·데이터·켜기/끄기). 가장 세밀하지만 hcitool은 사용 중단 예정.
- 확인: 폰 nRF Connect 스캐너에서 Manufacturer Data `0xFFFF`와 간격(약 100ms)이 보이는지.

## 3. 대안: 병사 팀의 "분대장 비콘" 보드(보드 A)에 맡기기
- 보드 A(NU-40 DK)에 `firmware/diag/LeaderBeacon` 펌웨어. UNO Q(또는 맥)에 **USB로 연결**하면 시리얼 장치가 생긴다(리눅스 `/dev/ttyACM0` 등, 맥 `/dev/cu.usbmodem…`).
- 프레임 hex 한 줄을 쓰면 보드가 위 1의 규칙대로 **100ms × 3초 방송**한다. seq와 내용은 분대장이 정한다.
  ```bash
  stty -F /dev/ttyACM0 115200 raw -echo      # 1200bps로 열지 말 것(보드가 부트로더로 들어감)
  cat /dev/ttyACM0 &                          # 응답 보기
  printf '01 10 05 00 1F 06 02 0E 01 FF 00 01\n' > /dev/ttyACM0
  ```
  응답: `OK tx type=10 seq=05 dst=1F len=12 3s` → 3초 뒤 `DONE seq=05`. 형식 오류면 `ERR …`(`help`로 사용법).
- 받아들이는 프레임: ver 01, src 00, CMD_BUTTON(len 6) 또는 EMCON_SET(len 1). 방송 중에 새 줄을 보내면 이전 방송을 멈추고 새로 시작.
- Python 예: `f = open('/dev/ttyACM0', 'r+b', buffering=0); f.write(b'01 10 05 00 1F 06 02 0E 01 FF 00 01\n')`
- 보드 A의 버튼 1~4는 고정 명령(정지·엄폐 270·사격 중지·집결, 전원 대상)으로도 방송한다.
