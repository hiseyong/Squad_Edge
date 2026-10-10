# 분대장1 SoftAP + BLE 측위 (Arduino UNO Q)

Squad Edge COP ↔ 분대장1 HW. 보드가 **Wi-Fi AP**로 COP와 붙고, **BLE Central**로 분대원 NU40-DK(`SQ1-S1`~`S5`)와 측위·명령을 주고받는다.

프로토콜 기준: `soldier-node/docs/squad_ble_protocol_v1.md` (+ `leader_squad_sharing_notes.md`).

```
[NU40-DK ×N] ──BLE NUS──▶ [UNO Q Linux: bridge_server]
     ▲  POS_TABLE / CMD_BUTTON / PEER_REPORT
     │
     └─ RANGING / CONTACT… ──▶ LocalizeEngine(MDS) ──▶ unit.relpos
                                      │
                               SoftAP TCP :9000
                                      │
                               노트북 COP (COP_Q3=1)
```

> UNO Q Wi-Fi·BLE 스택은 **Linux(MPU)** 가 담당. MCU 스케치는 Bridge로 GPS/알림을 넘긴다.

## ID 매핑

| BLE | 광고명 | COP |
|---|---|---|
| 0 (분대장) | — | `1-1` |
| 1 | `SQ1-S1` | `1-2` |
| 2 | `SQ1-S2` | `1-3` |
| 3 | `SQ1-S3` | `1-4` |

## 측위 파이프라인

1. 병사 `RANGING(0x0E)` RSSI 행 + (선택) LeaderBeacon `BCN` 분대장 줄  
2. `lib/squad_localize.py` — 경로손실 → 거리행렬 → 고전 MDS → 대형 정렬  
3. `POS_TABLE(0x15)` 를 연결 병사에게 Write  
4. 같은 좌표를 COP `unit.relpos`(ref=`1-1`)로 1초 상향  

시연 기본은 프리셋 대형(`wedge|line|column`). RSSI가 쌓이면 `--formation` 기준 `auto` 복원(주기 `Q3_LOCALIZE_S`, 기본 10s).

## 명령 전달 (Mac → Arduino)

```
COP issue_order → downlink hub → q3_ap TCP → bridge_server._on_downlink
  ├─ SoftAP NDJSON `order.new` (data.recipients = 분대장만, 예: ["1-1"])
  ├─ MCU Bridge RPC `order_notify("CODE|text")` → LED + Serial
  └─ 분대장 ACK → COP `ack` (from=1-1)
     ※ 분대원 BLE CMD_BUTTON 개별 전송 없음
```

SoftAP wire (한 줄 NDJSON, UTF-8):

```json
{"v":1,"type":"order.new","src":"PL","dst":"*","seq":12,"ts":1791612116.3,"prio":"priority","ack":true,"ttl":3,"data":{"id":"O-0007","code":"HALT","text":"1분대 정지. 현 위치 엄호.","to":["1"],"recipients":["1-1"],"params":{},"ref_report":null,"ack_required":true,"priority":"priority"}}
```

연결 직후 COP가 미ACK 1분대 명령을 재전송한다. `--no-ble` 이면 MCU 알림 + synthetic ack.

병사 CONTACT 등 → `PEER_REPORT` 중계 + COP `report.new` / `alert.new`.

## 디렉터리

| 경로 | 역할 |
|---|---|
| `firmware/SquadLeaderMCU/` | MCU Bridge (`telemetry_json`, `order_notify`) |
| `host/bridge_server.py` | SoftAP TCP + BLE 통합 진입점 |
| `host/ble/central.py` | Bleak Central (연결·Notify·Write) |
| `host/ble/localize.py` | RANGING 버퍼 + MDS + POS_TABLE |
| `host/ble/downlink_map.py` | COP → CMD_BUTTON |
| `host/ble/reports.py` | 병사 보고 → COP 이벤트 |
| `host/lib/frame_codec.py` | 프로토콜 프레임 (soldier-node vendored) |
| `host/lib/squad_localize.py` | MDS 측위 (soldier-node vendored) |
| `host/ap_start.sh` | SoftAP |

보드 A(비콘)는 `soldier-node/firmware/diag/LeaderBeacon` — USB로 `BCN <src> <rssi> <heading>` → `--beacon-port`.

## 보드에서

```bash
cd leader-q3/host
python3 -m pip install -r requirements.txt
sudo ./ap_start.sh
python3 bridge_server.py --formation wedge --ble-only 1,2,3
# LeaderBeacon 연결 시
python3 bridge_server.py --beacon-port /dev/ttyACM0
```

## 노트북(COP)

```bash
# Wi-Fi SquadEdge-1-1 조인 후
COP_MODE=realtime COP_Q3=1 COP_Q3_HOST=192.168.4.1 ./run.sh
```

로컬만 (BLE 없이 데모 좌표):

```bash
python3 bridge_server.py --demo --no-ble --host 127.0.0.1
COP_MODE=realtime COP_Q3=1 COP_Q3_HOST=127.0.0.1 ./run.sh
```

측위 단위 시험:

```bash
python3 lib/squad_localize.py --self-test
python3 -c "from ble.localize import LocalizeEngine; e=LocalizeEngine(); e.note_ranging(1,[{'peer_id':0,'rssi_avg':-79,'samples':10}]); print(e.compute(mode='auto'))"
```

## 환경변수

| 변수 | 기본 | 설명 |
|---|---|---|
| `Q3_BLE` | `1` | BLE Central |
| `Q3_BLE_ONLY` | `1,2,3` | 연결할 병사 |
| `Q3_FORMATION` | `wedge` | 프리셋/정렬 대형 |
| `Q3_LOCALIZE_S` | `10` | auto POS_TABLE 주기 |
| `Q3_PATHLOSS_P1M` / `N` | `-59` / `2.0` | RSSI 거리 모델 |
| `Q3_BEACON_PORT` | (빈값) | LeaderBeacon USB |
| `Q3_AP_SSID` / `PASS` / `IP` | SquadEdge-1-1 / … / 192.168.4.1 | SoftAP |
