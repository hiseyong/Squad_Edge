# 분대장(UNO Q) 담당용: 분대 위치표·보고 공유 메모 (단계 R + 9)

> 병사 단말 쪽에서 정리. 기준은 프로토콜 `docs/squad_ble_protocol_v1.md` v1.0.3. 아래 **(v1.1 예정)** 표시는 아직 문서에 없는 확장이다.
> 병사 펌웨어는 구현·컴파일만 끝났고 **장비 시험 전**이다. 리눅스(BlueZ) 쪽은 병사 팀이 검증하지 않았다.

## 분대장이 할 일 (요약)
1. **POS_TABLE(0x15) 송신**: 연결 직후, 대형이 바뀔 때, 위치를 다시 계산했을 때 병사 전원에게.
2. **PEER_REPORT(0x14) 중계**: 병사의 CONTACT/SUSPICIOUS/HAZARD/CASUALTY_FOUND를 받으면 **다른 연결된 병사들**에게.
3. **분대장 비콘 방송 (v1.1 예정)**: BEACON(0x20, src 0)을 500ms 간격으로 계속 광고(위치 복원 기준점).
4. **병사 비콘 RSSI 측정 (v1.1 예정)**: 병사 BEACON(0x20, src 1~5)을 수동 스캔해 병사별 RSSI 중앙값 → 거리 행렬의 분대장 줄.
5. **위치 복원**: 병사 RANGING(0x0E) + 4의 분대장 줄 → `tools/squad_localize.py` → POS_TABLE.

## 1. POS_TABLE (0x15, 연결 RX Write)
- payload: `n(1) + n×[id(1) x(int16) y(int16) heading(uint16)]`, 좌표 = **분대장 원점**, x 동쪽, y 북쪽, 단위 0.1m.
- **분대장 자신(id 0, (0,0))도 넣는다.** 병사는 RALLY(집결) 방향을 "내 위치 → id 0" 방위로 계산한다(없으면 원점).
- 프리셋(진행 방향 = 북쪽, 간격 10m) — `squad_localize.preset_positions()`와 같다:

| 대형 | S1 | S2 | S3 | S4 | S5 |
|---|---|---|---|---|---|
| wedge(쐐기, 분대장 꼭짓점) | (−7.1, −7.1) | (7.1, −7.1) | (−14.1, −14.1) | (14.1, −14.1) | (−21.2, −21.2) |
| line(횡대) | (−10, 0) | (10, 0) | (−20, 0) | (20, 0) | (−30, 0) |
| column(종대) | (0, 10) | (0, −10) | (0, 20) | (0, −20) | (0, −30) |

- 예(횡대, 분대장+S1+S2): `01 15 <seq> 00 03 16 03 00 00 00 00 00 00 00 01 9C FF 00 00 00 00 02 64 00 00 00 00 00`

## 2. PEER_REPORT 중계 (0x14, 연결 RX Write With Response)
- 대상 보고: CONTACT(0x01), SUSPICIOUS(0x02), HAZARD(0x03), CASUALTY_FOUND(0x04). **재전송(같은 병사·같은 seq)은 다시 중계하지 않는다.**
- payload: `reporter_id(1) rx(int16) ry(int16) orig_type(1) + 원 보고 payload 그대로`. rx/ry = POS_TABLE의 보고자 위치(0.1m).
  - 위치표를 아직 안 보냈으면 rx = ry = `0x8000`(−32768, **v1.1 예정: "위치 모름"**) → 병사는 자기 POS_TABLE에서 찾거나, 없으면 보고자 기준 방향으로 재생.
- dst_mask = 받는 병사들 비트(보고자 제외). 예: S2의 "적 3, 방위 0, 근거리"를 S1에게
  `01 14 <seq> 00 01 0D 02 64 00 00 00 01 00 00 0C 00 03 00 00`
- 병사는 표적 T = 보고자 위치 + d·(sin az, cos az)(d: 근 50m·중 100m·원 200m·없음 100m)를 자기 위치·방위로 바꿔 "적 3, 1시, 근거리"로 재생한다(프로토콜 §9.3).
- 병사는 같은 보고를 **10초 안에 두 번 재생하지 않는다**(아래 4의 직접 방송과 겹쳐도 한 번). 판정 = (보고자, 원 보고 type, 원 payload CRC).

## 3. 분대장 비콘 방송 + 병사 비콘 RSSI 측정 (v1.1 예정)
- 비콘 형식(병사와 같음): Legacy **비연결형** 광고, Flags + Manufacturer Data `0xFFFF` + 프레임 `[01 20 seq 00 FF 02 heading_lo heading_hi]`
  - AD 데이터 예(heading 없음 0xFFFF): `02 01 06 0B FF FF FF 01 20 <seq> 00 FF 02 FF FF`
  - 간격 **500ms**, 계속(시간 제한 없음). 분대장이 침묵(EMCON 0)일 때는 끄는 것을 권장(분대장도 방출 통제).
  - 병사는 RANGING에 **peer_id 0**으로 분대장 비콘 RSSI(최근 15개 중앙값)를 넣는다.
- 병사 비콘 수신: 수동 스캔, Manufacturer Data `0xFFFF` + `01 20 xx <src 1~5> FF 02 …`의 RSSI → 병사별 **최근 15개 이동 중앙값**, 30초 못 들으면 버림. 이것이 거리 행렬의 분대장 줄(0 → i).
- UNO Q 한 무선으로 "병사 5대 Central 연결 + 비연결형 광고 + 스캔"이 동시에 되는지는 컨트롤러에 따라 다르다. 안 되면 **보드 A(LeaderBeacon)를 USB로 붙여 맡긴다**:
  - `beacon on|off` 한 줄 → 분대장 위치 비콘 켜기/끄기(기본 켜짐). 명령 방송(3초) 중에는 비콘을 잠시 멈췄다가 재개.
  - 보드 A가 병사 비콘을 들을 때마다 USB로 `BCN <src> <rssi> <heading>` 한 줄 → 이 값으로 분대장 줄을 만든다(중앙값은 분대장 쪽에서).
  - 이 경우 "분대장 위치" = 보드 A 위치(분대장 몸에 붙일 것).

## 4. 위치 복원 (`tools/squad_localize.py`, 표준 라이브러리만)
```python
import squad_localize as sl
rows = {1: {0: -79, 2: -87},      # 병사 1의 RANGING: 분대장 -79, S2 -87
        2: {0: -80, 1: -85},
        0: {1: -78, 2: -81}}      # 분대장 줄(직접 측정)
meas = sl.measured_from_rssi(rows, p1m=-59, n=2.0)       # 경로손실 보정값은 병사 팀이 측정해 전달
pos, info = sl.localize([0, 1, 2], meas, formation="line")  # 실측 없는 쌍은 대형 거리로 채움
entries = sl.to_pos_table(pos)    # POS_TABLE entries (0.1m)
```
- 절차: N×N 거리 행렬(양방향 평균, 한쪽만 있으면 그 값, 없으면 대형 값) → 고전 MDS(야코비 고유값 분해) → 분대장을 원점으로 옮기고 대형에 가장 잘 맞게 회전(+반사).
- **거리만으로는 북쪽을 알 수 없다** → "현재 대형의 진행 방향 = 북쪽"으로 맞춘다. GPS·방위 센서가 붙으면 `align_to_prior()`만 바꾸면 된다.
- RSSI 거리 오차가 크므로(실내 ±50% 이상 흔함) 위치표는 "참고용 배치"로 쓰고, 시연은 프리셋 대형이 기본.
- 시험: `python3 tools/squad_localize.py --self-test`, `--demo`.

## 5. 병사 쪽 신규 송신 — 분대장은 받아도 되고 무시해도 됨
| msg_type | 이름 | 경로 | 내용 | 분대장 처리 |
|---|---|---|---|---|
| 0x0E | RANGING (v1.1 예정) | NUS Notify, 10초마다(EMCON 1/2) | `n + n×[peer_id, rssi_avg(int8), samples]`, peer 0 = 분대장 비콘 | 위치 복원에 사용(4). RPT_ACK 대상 아님 |
| 0x20 | BEACON (v1.1 예정) | 광고, EMCON 2 + 분대장 연결 중, 500ms | heading(2) | RSSI 측정(3) |
| 0x14 | PEER_REPORT **병사 직접 방송** (v1.1 예정) | 광고 100ms × 3초, EMCON 2에서 보고할 때 | src = reporter_id(1~5), dst 0x1F, rx/ry = 보고자가 아는 자기 위치(모르면 0x8000) | 무시 가능(같은 보고가 NUS로도 옴). 분대장 없이 병사끼리 공유하는 대안 경로 |
| 0x7F | LOG | NUS Notify | 디버그 ASCII | 무시 |
