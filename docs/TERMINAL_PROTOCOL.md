# Squad Edge C2 — 단말 데이터 표준 (v0.2)

> 병사 · 분대장 · 소대장 단말이 **보내야 할 값**과 **받아야 할 값**을 JSON으로 표준화한 문서.
> 백엔드(`backend/app/state.py`)의 이벤트 핸들러와 필드명을 그대로 맞췄으므로, 이 형식으로 보내면 COP 대시보드에 바로 반영된다.
> 구현 상태 표기: ✅ 백엔드 구현됨 · 🟡 신규(핸들러 추가 필요)

---

## 1. 단말 구성과 통신 경로

| 직책 | 단말 | 주요 역할 |
|---|---|---|
| **병사** (소총수·기관총·의무·통신) | NU40-DK 태그 (+ 선택: 스마트폰/이어셋) | 비콘, 이웃 RSSI, 버튼 퀵보고, 진동 수신, (음성 보고) |
| **분대장** | NU40 + 스마트폰 또는 UNO Q, GPS | 분대 위치 산출(상대측위), 음성 보고 구조화, 분대 중계 |
| **소대장** | 노트북(COP 서버) + UNO Q 게이트웨이 + NU40 | 전체 상황 집계, 명령·경보 하달, AI 브리핑 |
| 무인센서 | 아두이노 + NU40/무선 모듈 | 감지 이벤트 |

```
 [병사 태그] ──BLE adv/Coded PHY──▶ [분대장 단말] ──BLE 메시──▶ [소대장 게이트웨이] ──Serial/UDP/HTTP──▶ [COP 서버]
      ▲                                  ▲                               │
      └──────────── 하향(명령·경보·ACK) ──┴───────────────────────────────┘
```

- **상향(Uplink)**: 병사 → 분대장 → 소대장. 위치·상태·보고.
- **하향(Downlink)**: 소대장 → 분대장 → 병사. 명령·경보·표적 공유·ACK·EMCON.
- 분대장 단말이 연결되지 않으면 병사 태그 메시지는 **인접 노드가 그대로 중계**(TTL 감소)한다.

---

## 2. 공통 규약

### 2.1 단위·좌표·시간

| 항목 | 규칙 |
|---|---|
| 좌표 | WGS84 십진 도(`lat`, `lon`), 소수점 6자리 |
| 상대 위치 | 기준 노드 대비 **동(`dx`) / 북(`dy`) [m]** (ENU) |
| 방위 | 진북 기준 0~359 [deg] |
| 거리·오차 | [m] |
| 시간 | Unix epoch [s] (실수). 무선 프레임에서는 미션 시작 기준 상대초(uint16) 허용 |
| 신호세기 | RSSI [dBm] (정수) |
| 배터리 | 0~100 [%] |
| 문자열 | UTF-8. 무선 전송 시 자유 텍스트는 가능한 한 생략(코드값 사용) |

### 2.2 노드 ID

| 문자열 ID (JSON) | 1바이트 ID (무선) | 대상 |
|---|---|---|
| `PL` | `0x00` | 소대장 |
| `HQ-R` / `HQ-M` | `0x01` / `0x02` | 통신병 / 의무병 |
| `{분대}-{번호}` 예: `1-1` | `0x{분대}{번호}` 예: `0x11` | 분대원 (`-1` = 분대장) |
| `S-{n}` | `0xE0 + n` | 무인센서 |
| `*` | `0xFF` | 브로드캐스트 |

### 2.3 표준 봉투 (Envelope)

모든 메시지는 아래 봉투로 감싼다. COP 서버 입력(`POST /api/ingest`, UDP, Serial)에는 **`type`, `data`, `bytes`만 필수**이며 나머지는 단말 간 전달용이다.

```json
{
  "v": 1,
  "type": "unit.position",
  "src": "1-1",
  "dst": "PL",
  "seq": 1832,
  "ts": 1791612116.34,
  "prio": "routine",
  "ttl": 3,
  "ack": false,
  "bytes": 18,
  "data": { }
}
```

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `v` | int | ○ | 프로토콜 버전 (현재 1) |
| `type` | string | ● | 메시지 종류 (§4 카탈로그) |
| `src` | string | ○ | 송신 노드 ID |
| `dst` | string | ○ | 수신 노드 ID 또는 `*` |
| `seq` | int | ○ | 송신 노드별 일련번호 (0~65535 순환), 중복 제거·ACK용 |
| `ts` | float | ○ | 생성 시각 |
| `prio` | enum | ○ | `routine` / `priority` / `urgent` (§2.4) |
| `ttl` | int | ○ | 남은 중계 홉 수 (기본 3) |
| `ack` | bool | ○ | 수신 확인 요구 여부 |
| `bytes` | int | ○ | 실제 무선 프레임 크기 (송신량 통계용) |
| `data` | object | ● | 메시지 본문 |

● = COP 서버 필수, ○ = 단말 간 필수(서버는 무시해도 됨)

### 2.4 우선순위 · ACK · EMCON

| prio | 예시 | ACK | 재전송 | EMCON 중 |
|---|---|---|---|---|
| `urgent` | 접적, 부상, MEDEVAC, SOS | 필수 | 1s→2s→4s, 최대 5회 | **송신 허용** |
| `priority` | SALUTE, 명령, 표적 공유 | 필수 | 2s→4s, 최대 3회 | 송신 허용(묶음 전송) |
| `routine` | 위치, 링크, 비콘, SITREP | 없음 | 없음 | **주기 연장 또는 중지** |

EMCON 시 주기 (평시 → EMCON):

| 메시지 | 평시 | EMCON |
|---|---|---|
| `beacon` | 1 s | 10 s (또는 수신 전용) |
| `nbr.rssi` | 2 s | 중지 |
| `unit.position` / `unit.relpos` | 1 s | 5~10 s |
| `link.update` | 2 s | 중지 |

---

## 3. 직책별 송수신 매트릭스

### 3.1 병사 단말 (NU40 태그)

| 방향 | type | 주기/조건 | prio | 상태 |
|---|---|---|---|---|
| **TX** | `beacon` | 1 s | routine | 🟡 |
| **TX** | `nbr.rssi` | 2 s | routine | 🟡 |
| **TX** | `quick` | 버튼 입력 시 | urgent/priority | 🟡 |
| **TX** | `unit.status` | 상태 변경 시 | urgent | ✅ |
| TX (선택) | `imu.step` | 걸음 검출 시 (PDR) | routine | 🟡 |
| TX (선택, 폰 보유 시) | `voice.raw` → 분대장에서 `report.new`로 변환 | 발화 시 | priority | 🟡 |
| **RX** | `haptic` | 경보·명령·보고결과 수신 시 | — | ✅ (하향 송출) |
| **RX** | `ack` | 내 urgent/priority 송신 후 | — | 🟡 (게이트웨이) |
| **RX** | `mission.update` (`emcon`만) | 변경 시 | — | ✅ |
| RX (선택) | `order.new` (요약 코드) | 하달 시 | — | ✅ |

### 3.2 분대장 단말

| 방향 | type | 주기/조건 | prio | 상태 |
|---|---|---|---|---|
| **TX** | `unit.position` (자신, GPS) | 1 s | routine | ✅ |
| **TX** | `unit.relpos` (분대원, 상대측위 결과) | 1 s | routine | ✅ |
| **TX** | `link.update` | 2 s | routine | ✅ |
| **TX** | `report.new` (SALUTE/SPOT/CONTACT/MEDEVAC/SITREP) | 음성 보고 구조화 시 | 보고별 | ✅ |
| **TX** | `unit.status` (분대원 대신 보고 포함) | 변경 시 | urgent | ✅ |
| **TX** | `squad.summary` | 30 s 또는 변경 시 | routine | 🟡 |
| **TX** | `ack` | 하향 명령·보고결과 수신 시 | — | ✅ |
| **TX** | `report.amend` | 재확인 요청에 대한 보완 보고 | priority | ✅ |
| 중계 | 병사의 `beacon`/`quick`/`unit.status` | 수신 즉시 | 원본 유지 | — |
| **RX** | `order.new` / `order.cancel` | 하달·취소 시 | — | ✅ |
| **RX** | `target.upsert` / `target.remove` (공유 표적) | 변경 시 | — | ✅ |
| **RX** | `report.update` (승인/기각 결과, ACK 요구) | 소대장 결심 시 | — | ✅ |
| **RX** | `alert.new` | 발생 시 | — | ✅ |
| **RX** | `mission.update` (EMCON, 통제선) | 변경 시 | — | ✅ |
| **RX** | `ack` | 내 보고 후 | — | 🟡 (게이트웨이) |

### 3.3 소대장 단말 (COP)

| 방향 | type | 조건 | 상태 |
|---|---|---|---|
| **TX** | `order.new` (FRAGO, 정지·전진·집결 등) | 명령 시 | ✅ |
| **TX** | `order.cancel` | 명령 취소 시 | ✅ |
| **TX** | `target.upsert` / `target.remove` | 표적 확정·해제 시 | ✅ |
| **TX** | `report.update` + `haptic` | 보고 승인/기각 시 | ✅ |
| **TX** | `order.new`(code=`RECHECK`) | 보고 재확인 요청 시 | ✅ |
| **TX** | `alert.new` / `haptic` | 경보 하달 시 | ✅ |
| **TX** | `mission.update` | EMCON·통제선·목표 변경 시 | ✅ |
| **TX** | `ack` | 상향 urgent/priority 수신 시 | 🟡 (게이트웨이) |
| TX | `unit.position` (자신) | 1 s | ✅ |
| **RX** | 위 3.1, 3.2의 모든 TX + 무인센서 | — | — |

### 3.4 무인센서

| 방향 | type | 조건 | 상태 |
|---|---|---|---|
| TX | `sensor.upsert` | 부팅 시 1회 + 60 s 하트비트 | ✅ |
| TX | `sensor.trigger` | 감지 시 | ✅ |

---

## 4. 메시지 카탈로그 (`data` 스키마)

> 아래 예시는 `data` 본문 기준. 실제 전송 시 §2.3 봉투로 감싼다.

### 4.1 `beacon` 🟡 — 병사 생존·상태 비콘

```json
{ "id": "1-2", "status": "ok", "battery": 87, "heading": 32, "flags": ["moving"] }
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `id` | string | 노드 ID |
| `status` | enum | `ok` · `wia` · `kia` |
| `battery` | int | % |
| `heading` | int? | 지자기 센서 방위 (없으면 생략) |
| `flags` | string[] | `moving` · `stationary` · `sos` · `low_batt` |

> 서버 처리 권장: `last_seen` 갱신 + 배터리/상태 반영 (`unit.status`와 동일 경로).

### 4.2 `nbr.rssi` 🟡 — 이웃 노드 RSSI (상대측위 원자료)

```json
{
  "id": "1-2",
  "nbrs": [
    { "id": "1-1", "rssi": -63, "n": 5 },
    { "id": "1-3", "rssi": -71, "n": 4 },
    { "id": "PL",  "rssi": -84, "n": 2 }
  ],
  "win_ms": 2000
}
```

| 필드 | 설명 |
|---|---|
| `nbrs[].rssi` | 윈도 동안 채널 37/38/39 RSSI **중앙값** |
| `nbrs[].n` | 수신 패킷 수 (신뢰도) |
| `win_ms` | 집계 윈도 |

> 분대장 단말(또는 COP 서버)이 이 값을 모아 거리행렬 → SMACOF → `unit.relpos` 를 생성한다.
> 같은 데이터로 `link.update`도 만들 수 있다.

### 4.3 `quick` 🟡 — 버튼 퀵보고

```json
{ "id": "1-3", "code": "CONTACT", "dir": 2 }
```

| code | 의미 | prio | 서버 동작 권장 |
|---|---|---|---|
| `CONTACT` | 접적 | urgent | `report.new`(CONTACT) 생성, 경보 |
| `WIA_SELF` | 본인 부상 | urgent | `unit.status`=wia |
| `MAN_DOWN` | 인접 전우 쓰러짐 | urgent | 경보 + 위치 표시 |
| `NEED_MEDIC` | 의무병 요청 | urgent | 의무병 단말로 `haptic` |
| `AMMO_LOW` | 탄약 부족 | priority | `squad.summary` 반영 |
| `OK` | 이상 없음 / 도착 | routine | ACK만 |
| `SOS` | 긴급 구조 | urgent | 최상위 경보 |

| 필드 | 설명 |
|---|---|
| `dir` | (선택) 시계방향 1~12, 버튼 조합 또는 태그 방위로 입력 |

### 4.4 `unit.upsert` ✅ — 노드 등록 (부팅 시 1회)

```json
{ "id": "1-2", "callsign": "1-2", "role": "rifleman", "squad": "1" }
```

`role`: `pl` · `sl` · `rifleman` · `gunner` · `medic` · `radio`
`squad`: `HQ` · `1` · `2` · `3`

### 4.5 `unit.position` ✅ — 절대 위치 (GPS 보유 노드)

```json
{ "id": "1-1", "lat": 36.302812, "lon": 127.420035, "heading": 27, "err": 3.0,
  "source": "gps", "battery": 91, "rssi": -66 }
```

| 필드 | 필수 | 설명 |
|---|---|---|
| `id`, `lat`, `lon` | ● | |
| `heading` | | 진행방향 |
| `err` | | 위치 오차 반경 [m] |
| `source` | | `gps` · `manual` · `dr`(추측항법) |
| `battery`, `rssi` | | 게이트웨이 기준 RSSI |

### 4.6 `unit.relpos` ✅ — 상대 위치 (BLE 상대측위 결과)

```json
{ "id": "1-2", "ref": "1-1", "dx": -8.4, "dy": -7.1, "err": 4.8, "heading": 27, "battery": 85 }
```

| 필드 | 필수 | 설명 |
|---|---|---|
| `ref` | ● | 기준 노드 (보통 분대장). 서버가 `ref`의 절대좌표로 변환 |
| `dx`, `dy` | ● | 기준 대비 동/북 [m] |
| `err` | | 추정 오차 [m] (SMACOF 잔차 기반) |

### 4.7 `unit.status` ✅

```json
{ "id": "1-3", "status": "wia" }
```
`status`: `ok` · `wia` · `kia` (`nolink`는 서버가 판정, 단말이 보내지 않음)

### 4.8 `link.update` ✅

```json
{ "a": "1-1", "b": "1-2", "rssi": -67 }
```

### 4.9 `report.new` ✅ — 구조화 보고 (음성 AI 출력)

**공통 필드**

| 필드 | 필수 | 설명 |
|---|---|---|
| `type` | ● | `SALUTE` · `SPOT` · `CONTACT` · `MEDEVAC` · `SITREP` · `FREE` |
| `sender` | ● | 보고자 노드 ID |
| `priority` | | `routine` · `priority` · `urgent` |
| `raw_text` | | STT 원문 (무선 전송 시 생략 가능, 분대장 단말 로컬 보관) |
| `summary` | | AI 한 줄 요약 (≤ 40자 권장) |
| `fields` | ● | 양식별 필드 (아래) |
| `missing` | | 필수 항목 중 비어 있는 것 |
| `conf` | | AI 추출 신뢰도 0~1. **0.7 미만이면 COP에서 승인 대기** |

**위치(`location`) 표기 — 둘 중 하나**

```json
{ "lat": 36.30412, "lon": 127.42291, "err": 30 }
{ "bearing": 87, "dist": 150, "err": 30 }
```
상대 표기(`bearing` 진북 방위, `dist` m)는 보고자 위치 기준으로 서버가 절대좌표로 바꿔 표적을 만든다.

**SALUTE**

```json
{
  "type": "SALUTE", "sender": "1-1", "priority": "priority", "conf": 0.88,
  "raw_text": "1분대장 보고. 적 보병 3명, 2시 방향 약 150미터, 능선 따라 남쪽으로 이동 중. 소총 휴대.",
  "summary": "적 보병 3명 · 1분대 2시 150m · 능선 따라 남하",
  "fields": {
    "size": 3,
    "activity": "능선 따라 남하",
    "location": { "bearing": 87, "dist": 150, "err": 30 },
    "unit": "적 보병 분조",
    "time": "현재",
    "equipment": "소총",
    "kind": "infantry"
  },
  "missing": []
}
```
`kind`: `infantry` · `vehicle` · `sniper` · `movement` (지도 부호 결정)

**SPOT** — SALUTE 축약판 (`size`, `activity`, `location`, `kind`)

**CONTACT** (접적)

```json
{
  "type": "CONTACT", "sender": "1-1", "priority": "urgent", "conf": 0.93,
  "summary": "1분대 접적 — 1시 방향 소화기 사격",
  "fields": { "kind": "infantry", "activity": "소화기 사격",
              "location": { "bearing": 62, "dist": 120, "err": 25 } }
}
```

**MEDEVAC** (9-line)

```json
{
  "type": "MEDEVAC", "sender": "1-1", "priority": "urgent", "conf": 0.9,
  "summary": "긴급 환자 1 (1-3 대퇴부 총상) · 들것 1",
  "fields": {
    "1. 위치": "52S CF 58246 18616",
    "2. 호출부호": "메시 C2",
    "3. 환자/우선순위": "긴급 1",
    "4. 특수장비": "없음",
    "5. 환자 유형": "들것 1",
    "6. 착륙지대 보안": "적 활동 가능 — 무장호송 필요",
    "7. 착륙지대 표시": null,
    "8. 환자 국적": "아군 1",
    "9. 지형/장애물": "능선 남사면"
  },
  "missing": ["7. 착륙지대 표시"]
}
```
값이 `null`인 항목은 `missing`에 넣는다. 그러면 음성 AI가 보고자에게 그 항목을 되묻는다.

**SITREP**

```json
{
  "type": "SITREP", "sender": "PL",
  "summary": "PL 알파 통과 · WIA 1 후송 대기 · 탄약 양호",
  "fields": { "position": "PL 알파 북측", "casualties": "WIA 1", "ammo": "양호", "intent": "목표 지역으로 전진" }
}
```

### 4.10 `report.update` ✅ — 보고 승인/기각 결과 (소대장 → 보고자, ACK 요구)

```json
{ "id": "R-3fa21c", "status": "confirmed", "note": "2분대 관측 일치", "edits": { "fields": { "size": 2 } } }
```
보고자 단말은 `ack {ref: "R-3fa21c", from: "2-3"}`로 응답한다. 함께 `haptic`이 간다(승인 `SHORT_1`, 기각 `SHORT_LONG`).

### 4.10a `report.decision` ✅ — 승인 워크플로 입력 (COP UI·음성 명령 → 서버)

```json
{ "id": "R-3fa21c", "action": "confirm", "note": "2분대 관측 일치", "edits": { "fields": { "size": 2 } }, "by": "PL" }
```
| action | 동작 |
|---|---|
| `confirm` | 승인. `edits`가 있으면 AI 추출값을 수정한 뒤 승인하고 표적도 갱신. 결과를 보고자에게 하향 |
| `reject` | 기각(오보 처리 포함). 표적은 지도에서 숨김. `note` = 사유 |
| `recheck` | 보고자에게 재확인 명령(`order.new`, code=`RECHECK`)을 하달. 보고는 승인 대기 유지 |
| `reopen` | 결심 취소 → 승인 대기로 되돌림 |

모든 결심은 `history[]`와 `backend/data/audit.jsonl`(사후검토용)에 기록된다.

### 4.10b `report.amend` ✅ — 보완 보고 (보고자 → 소대장, 재확인 요청에 대한 응답)

```json
{ "id": "R-3fa21c", "from": "2-3", "fields": { "activity": "정차, 엔진 가동 중" }, "conf": 0.82,
  "summary": "적 경계 차량 1대 · 2분대 1시 220m · 정차", "raw_text": "재확인 결과 적 차량 맞음." }
```
필드를 병합하고 `missing`을 다시 계산한다. 연계된 RECHECK 명령은 자동으로 수신 확인 처리된다.

### 4.11 `target.upsert` / `target.remove` ✅ — 표적 공유

```json
{ "id": "T-91ab02", "affiliation": "hostile", "kind": "infantry", "label": "적 보병 분조",
  "lat": 36.30412, "lon": 127.42291, "count": 3, "activity": "남하",
  "err_m": 30, "conf": 0.88, "status": "confirmed" }
```
```json
{ "id": "T-91ab02" }
```
하향 전송 시 분대장 단말에는 `id, affiliation, kind, lat, lon, count, status`만 보내도 된다.

### 4.12 `order.new` ✅ — 명령 하달 (소대장 → 분대장/병사)

```json
{
  "id": "O-0007",
  "to": ["1", "2"],
  "code": "HALT",
  "text": "1, 2분대 정지. 현 위치 엄호.",
  "params": { "until": null, "grid": null },
  "ack_required": true
}
```

| code | 의미 | 병사 태그 진동(`haptic`) |
|---|---|---|
| `HALT` | 정지 | `LONG_1` |
| `MOVE` | 전진/이동 (`params.grid` 목표) | `SHORT_2` |
| `RALLY` | 집결 (`params.grid`) | `SHORT_3` |
| `TAKE_COVER` | 엄폐 | `LONG_3` |
| `WEAPONS_HOLD` / `WEAPONS_FREE` | 사격 통제 | `SHORT_1` + `LONG_1` |
| `FRAGO` | 자유 텍스트 단편명령 | `SHORT_2` |

| `RECHECK` | 보고 재확인 요청 (`ref_report` 포함) | `SHORT_SHORT_LONG` |

`to`: 분대 번호 배열(`"1"`, `"HQ"`), 노드 ID 배열, 또는 `["*"]`. 서버가 실제 수신 노드 목록 `recipients`로 펼쳐서 하향 페이로드에 넣는다.

**수신 확인과 재전송**
- 수신 노드마다 `ack {ref: 명령ID, from}`를 받아 `acks`에 기록한다. 상태는 `sent` → `partial` → `acked` 순으로 바뀐다.
- 미수신 노드에게만 8초 간격으로 재전송한다(최대 4회). 그래도 안 되면 `expired` 처리하고 경보를 띄운다.
- 두절됐던 노드가 복구되면 못 받은 명령을 즉시 재전송한다(저장 후 전달).
- `order.cancel {id, recipients}`: 취소를 하향한다.

### 4.13 `haptic` ✅ — 병사 태그 진동 명령 (하향)

```json
{ "dst": "1-2", "pattern": "SHORT_2", "reason": "formation", "ref": "O-0007" }
```

| pattern | 진동 | 기본 용도 |
|---|---|---|
| `SHORT_1` | ● | ACK / 확인 |
| `SHORT_2` | ●● | 대형 이탈 — 복귀 |
| `SHORT_3` | ●●● | 집결 |
| `LONG_1` | ━ | 정지 |
| `LONG_3` | ━━━ | 접적 경보 / 엄폐 |
| `SHORT_LONG` | ●━ | 보고 기각 / 사격 통제 변경 |
| `SHORT_SHORT_LONG` | ●●━ | 보고 재확인 요청 |

### 4.14 `alert.new` ✅

```json
{ "level": "warn", "kind": "formation", "msg": "2-3 대형 이탈 — 2분대장 기준 3시 62m", "unit_id": "2-3" }
```
`level`: `info` · `warn` · `crit`

### 4.15 `mission.update` ✅

```json
{ "emcon": true }
```
```json
{ "name": "OP NIGHTOWL · 소대 정찰", "objective": [36.3095, 127.4290],
  "route": [[36.3005, 127.4185], [36.3028, 127.4200]],
  "phase_lines": [{ "name": "PL 알파", "coords": [[36.3020, 127.4170], [36.3010, 127.4235]] }] }
```

### 4.16 `squad.summary` 🟡 — 분대 요약 (분대장 → 소대장)

```json
{
  "squad": "1", "sl": "1-1",
  "strength": { "total": 4, "ok": 3, "wia": 1, "kia": 0, "nolink": 0 },
  "ammo": "green", "water": "amber", "equipment": "green",
  "note": "1-3 후송 대기"
}
```
`ammo`·`water`·`equipment`: `green` · `amber` · `red` · `black` (LACE 보고 개념)

### 4.17 `ack` ✅

```json
{ "ref": "O-7d967a", "from": "2-3", "ok": true }
```
`ref`는 명령 ID 또는 보고 ID다. 무선 계층의 ACK(`ref_src`, `ref_seq`)는 게이트웨이가 처리하고, 서버에는 위 형식으로 전달한다.

### 4.18 `sensor.upsert` / `sensor.trigger` ✅

```json
{ "id": "S-2", "kind": "acoustic", "lat": 36.30520, "lon": 127.42550, "battery": 76 }
```
```json
{ "id": "S-2", "conf": 0.45 }
```
`kind`: `pir` · `acoustic` · `ultrasonic` · `seismic`

---

## 5. 무선 프레임 압축 형식 (NU40 ↔ NU40)

BLE 레거시 광고 패킷은 31 B 제한이 있으므로, 고빈도 메시지는 **바이너리 고정 형식**으로 보낸다.
게이트웨이(UNO Q)가 이를 §4 JSON으로 풀어서 COP에 넣는다.

### 5.1 공통 헤더 (Manufacturer Specific Data, 5 B)

| 오프셋 | 크기 | 필드 | 값 |
|---|---|---|---|
| 0 | 2 | Company ID | `0xFFFF` (테스트용) |
| 2 | 1 | ver(4b) · msg(4b) | ver=1, msg 코드 아래 표 |
| 3 | 1 | src | 노드 1B ID (§2.2) |
| 4 | 1 | seq | 0~255 순환 |

| msg 코드 | type |
|---|---|
| `0x1` | `beacon` |
| `0x2` | `nbr.rssi` |
| `0x3` | `quick` |
| `0x4` | `unit.status` |
| `0x5` | `unit.relpos` |
| `0x6` | `unit.position` |
| `0x8` | `haptic` (하향) |
| `0x9` | `ack` |
| `0xA` | `mission.update` (emcon 1bit) |
| `0xF` | 확장(Extended ADV / GATT, CBOR 본문) |

### 5.2 `beacon` 본문 (4 B → 총 9 B)

| 오프셋 | 크기 | 필드 |
|---|---|---|
| 5 | 1 | status(2b: 0 ok,1 wia,2 kia) · flags(6b: moving, sos, low_batt …) |
| 6 | 1 | battery (0~100) |
| 7 | 2 | heading × 10 (uint16, 0xFFFF = 없음) |

### 5.3 `nbr.rssi` 본문 (1 + 2n B)

| 오프셋 | 크기 | 필드 |
|---|---|---|
| 5 | 1 | 이웃 수 n (최대 12) |
| 6 + 2k | 1 | 이웃 ID |
| 7 + 2k | 1 | RSSI (int8, dBm) |

### 5.4 `quick` 본문 (2 B)

| 오프셋 | 크기 | 필드 |
|---|---|---|
| 5 | 1 | code (`0x01` CONTACT, `0x02` WIA_SELF, `0x03` MAN_DOWN, `0x04` NEED_MEDIC, `0x05` AMMO_LOW, `0x06` OK, `0x07` SOS) |
| 6 | 1 | dir (0=없음, 1~12) |

### 5.5 `unit.relpos` 본문 (7 B → 총 12 B)

| 오프셋 | 크기 | 필드 |
|---|---|---|
| 5 | 1 | 대상 ID |
| 6 | 1 | ref ID |
| 7 | 2 | dx × 10 (int16, 0.1 m) |
| 9 | 2 | dy × 10 (int16) |
| 11 | 1 | err × 2 (uint8, 0.5 m) |

### 5.6 `unit.position` 본문 (11 B)

| 오프셋 | 크기 | 필드 |
|---|---|---|
| 5 | 4 | lat × 1e7 (int32) |
| 9 | 4 | lon × 1e7 (int32) |
| 13 | 2 | heading × 10 (uint16) |
| 15 | 1 | err (uint8, m) |

### 5.7 `report.new` 등 긴 메시지

- 확장 광고(Extended ADV, 최대 255 B) 또는 GATT로 **CBOR** 인코딩 전송
- `raw_text`는 무선으로 보내지 않고 보고자 단말에 보관 (요청 시 별도 전송)
- 목표: SALUTE ≤ 80 B, MEDEVAC ≤ 120 B

---

## 6. 게이트웨이 → COP 서버 입력

| 경로 | 형식 | 예 |
|---|---|---|
| **Router WS** (realtime) | `ws://<COP>:8000/ws/router` 양방향 | 분대장 단말기: 상향 NDJSON + 하향 명령 (주기 1 s) |
| **Q3 SoftAP TCP** (분대장1) | 보드 AP `192.168.4.1:9000` NDJSON 양방향 | 노트북이 AP 조인 후 `COP_Q3=1` (`squad-leader/`) |
| Serial (UNO Q → 노트북) | NDJSON, 115200 bps | `{"type":"unit.relpos","data":{...},"bytes":12}\n` |
| UDP | 포트 5005, 한 줄에 JSON 하나 | `nc -u 192.168.4.1 5005` |
| HTTP | `POST /api/ingest`, 단일 또는 배열 | `curl -d @ev.json` |

**분대장1 SoftAP + BLE 경로** (`squad-leader/`):
- 보드 SoftAP(`SquadEdge-1-1`) + TCP `:9000` — `squad/link/cop.py`, 진입점 `tools/leader_app.py` / `tools/cop_link.py`
- BLE Central → NU40(`SQ1-S*`) — `squad/soldier/` (`soldier-node` 프로토콜과 동일)
- 상향: `unit.relpos`, `report.new`(양식·`BATTLE_DATA` 등). `unit.position`·`link.update`는 COP mock이 담당해 HW분은 무시
- 하향: COP `order.new` → **분대장만** (`recipients`=`1-1`). 분대원 BLE 자동 하달 없음(분대장이 필요 시 키패드/음성으로 중계)
- COP: `COP_MODE=realtime ./run.sh` (기본 `COP_Q3=1`, `192.168.4.1:9000`)

**Realtime 시연 모드** (`COP_MODE=realtime` 또는 TopBar `REALTIME`):
- **Mock GPS**: 1분대장(`1-1`) — SoftAP 연결 중에만 COP가 위치·메시 합성
- **HW**: 1분대원(`1-2`~`1-4`) — `unit.relpos`(ref=`1-1`)
- **용어**: SoftAP 단절=1분대 **통신두절** · 연결 중 무좌표=**측위대기**
- **Mock 위치**: HQ·2·3분대 (시나리오 이벤트 mock 없음)
- 로컬 시연: `python3 tools/router_mock.py` (분대원 relpos만)

게이트웨이는 다음을 처리한다.

1. 바이너리 프레임을 §4 JSON으로 변환하고, `bytes`에 실제 프레임 크기를 기입한다.
2. `(src, seq)` 기준으로 중복을 제거한다 (메시 중계 때문에 같은 패킷이 여러 번 들어온다).
3. 1B 노드 ID를 문자열 ID로 변환한다 (`0x12` → `"1-2"`).
4. 하향 메시지는 다음 중 하나로 받아 무선 프레임으로 다시 인코딩한다.
   - **WebSocket** `ws://<COP>:8000/ws/downlink`: 메시지마다 §2.3 봉투 JSON 한 개
   - **Serial**: `COP_SERIAL`로 연결된 같은 포트에 NDJSON 한 줄씩
   - 최근 200건 확인: `GET /api/downlink`

   하향 type은 `order.new`, `order.cancel`, `haptic`, `report.update`이다.

---

## 7. 백엔드 반영 체크리스트 (🟡 항목)

| type | 서버 처리 | 위치 |
|---|---|---|
| `beacon` | `_touch()` + battery/status/heading 갱신 | `state.py` `@handler("beacon")` |
| `nbr.rssi` | 거리행렬 버퍼 갱신 → 주기적 SMACOF → `unit.relpos` 생성, `link.update` 생성 | 새 모듈 `localization.py` |
| `quick` | code별로 `report.new` / `unit.status` / `alert` 생성 | `state.py` |
| `squad.summary` | 새 컬렉션 `squads` 추가, Roster에 표시 | `models.py`, `types.ts` |
| ~~`order.new`~~ | ✅ v0.2 구현 (명령 패널, ACK 집계, 재전송, 저장 후 전달) | `state.py`, `OrderPanel.tsx` |
| ~~`haptic`~~ | ✅ v0.2 구현 (`downlink.py` → WS/Serial) | `downlink.py` |
| ~~`ack`~~ | ✅ v0.2 구현 | `state.py` |
