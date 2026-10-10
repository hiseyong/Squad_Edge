# Squad Edge C2 · COP 대시보드

Deploy for Defense 2026: 소부대 오프라인 전술 C2와 음성 AI를 합친 프로젝트의 **소대장용 공통상황도(COP) 대시보드**입니다.

## 빠른 실행

```bash
cd ~/Documents/competition/2026D4D
./run.sh                     # 개발 모드: 0.0.0.0:5173 + :8000 (핫리로드)
./run.sh prod                # 데모 모드: 빌드 후 0.0.0.0:8000 하나로 서빙
COP_MODE=realtime ./run.sh   # 1분대=단말 HW · HQ·2·3 mock (router_mock 또는 실단말 필요)
COP_MODE=realtime ./run.sh           # SoftAP 연동 기본(COP_Q3=1 → 192.168.4.1:9000)
COP_MODE=realtime COP_Q3=0 ./run.sh  # SoftAP 끄고 router_mock/WS만
COP_SIM=0 ./run.sh                   # 시뮬레이터 끄고 실제 하드웨어 입력만
```
# 노트북 Wi-Fi를 보드 AP(SquadEdge-1-1)에 연결한 뒤 realtime 실행. `nc 192.168.4.1 9000` 과 동일 스트림.

처음 실행할 때 `backend/.venv` 생성과 `npm install`을 자동으로 합니다. Python 3.10 이상과 Node 18 이상이 필요합니다.
프론트·백엔드 모두 `0.0.0.0`에 바인딩합니다. 같은 AP에서는 `http://<노트북IP>:5173`(개발) 또는 `:8000`(데모·라우터 WS)으로 접속하세요.

## 구조

```
NU40 태그/앵커 ─BLE─▶ UNO Q 게이트웨이 ─Serial(NDJSON)/UDP─┐
분대장1 UNO Q SoftAP ─TCP NDJSON(192.168.4.1:9000)──────────┤
음성 AI 모듈 (STT→LLM→JSON) ──────────── HTTP POST ─────────┤
                                                            ▼
                         backend (FastAPI)  app/state.py: Store
                           ├ 이벤트 핸들러 → COP 상태 갱신
                           ├ 경보 규칙 (통신두절·대형이탈·부상·접적)
                           ├ 브리핑 (규칙 기반 / 로컬 LLM)
                           └ WebSocket /ws  ── snapshot + patch ──▶ frontend (React)
```

| 경로 | 내용 |
|---|---|
| `backend/app/models.py` | 데이터 모델 (Unit, Target, Report, Sensor, Link, Alert …) |
| `backend/app/state.py` | 상태 저장소, **이벤트 핸들러**, 경보 규칙, 브로드캐스트 |
| `backend/app/briefing.py` | 상황 브리핑 및 자연어 질의 (LLM 선택) |
| `backend/app/sources/` | 입력 소스: `simulator.py`, `router.py`, `q3_ap.py`, `serial_source.py`, `udp_source.py` |
| `leader-q3/` | **분대장1** UNO Q SoftAP + BLE(NU40 측위·명령) + TCP 브리지 |
| `frontend/src/store.ts` | Zustand 전역 상태 (서버 patch 적용) |
| `frontend/src/components/` | `MapView`, `Roster`, `FormationView`, `ReportFeed`, `AlertPanel`, `BriefingPanel`, `TopBar` |
| `frontend/src/lib/ranks.ts` | 국군 육군 계급장 기호 (아군 지도/로스터) |
| `frontend/src/lib/symbols.ts` | 지도 아이콘 (아군 계급장 · 표적 2525 부호) |
| `tools/send_event.py` | 팀원용 이벤트 송신 예제 |

**스택**은 다음과 같습니다.

- 백엔드: FastAPI + WebSocket. Python이라 BLE/시리얼/AI 코드와 같은 언어로 붙일 수 있습니다.
- 프론트엔드: React + TypeScript + Vite, react-leaflet, Zustand, Tailwind, milsymbol, mgrs.

## 대시보드 기능

- **지도 COP**에 표시되는 것
  - 아군: 국군 육군 계급장(중위·하사·병장·상병·일병), 진행방향, 상태 색상(부상 / 두절 깜빡임)
  - 적·미확인 표적: 미확인은 점선 프레임과 오차원으로 표시하고, 5분에 걸쳐 흐려지게 해서 정보의 신선도를 보여줍니다
  - 메시 링크: RSSI 색상
  - 이동 궤적, BLE 측위 오차원, 경로·통제선·목표
  - 미터 격자: 오프라인에서도 거리감을 줍니다
  - 커서 위치의 MGRS 좌표
  - 소대장 추적 모드
- **부대 현황**: 분대별 인원·상태·측위 방식(GPS/BLE)·배터리를 보여주고, 클릭하면 상세 정보와 지도 이동이 됩니다.
- **대형 뷰**: BLE 상대측위 결과를 진행방향이 위로 오는 방사형 뷰로 보여줍니다. 60m 이상 벗어난 인원은 이탈로 강조합니다.
- **보고 피드**
  - SALUTE / SPOT / 접적 / MEDEVAC(9-line) / SITREP 카드
  - STT 원문, 구조화된 필드, 누락 항목, AI 신뢰도 표시
  - 신뢰도가 0.7 미만인 보고는 승인/기각 버튼이 붙습니다 (Human-in-the-loop)
- **경보**: 부상, 의무후송, 접적, 통신 두절/복구, 대형 이탈, 보고 누락 항목. 개별 확인과 일괄 확인을 지원합니다.
- **AI 브리핑**: 버튼 또는 자연어 질의로 실행합니다.
- **EMCON 모드**: 켜면 위치/링크 보고 주기가 1초에서 5초로 늘어납니다. TX 바이트와, 같은 보고를 음성으로 보냈을 때의 송신량 비교를 함께 표시합니다.
- **시나리오**: ↻ 버튼으로 처음부터 재생합니다. 재생 순서는 SALUTE → 저신뢰 SPOT → 접적 → 부상 → MEDEVAC → 통신 두절 → 대형 이탈 → SITREP입니다.

## 이벤트 프로토콜 (팀원 연동용)

모든 입력은 같은 봉투 형식을 씁니다. `bytes`는 실제 무선 프레임 크기를 알 때만 넣으면 됩니다.

```json
{"type": "<이벤트>", "data": { ... }, "bytes": 14}
```

| type | data | 보내는 쪽 |
|---|---|---|
| `unit.upsert` | `{id, callsign, role, squad}` | 초기 등록 |
| `unit.position` | `{id, lat, lon, heading?, err?, source?, battery?, rssi?}` | GPS 보유 노드 |
| `unit.relpos` | `{id, ref, dx, dy, err?}` (ref 기준 동/북 m) | **BLE 상대측위 (MDS 결과)** |
| `unit.status` | `{id, status: ok\|wia\|kia\|nolink}` | 태그 버튼 / 음성 |
| `link.update` | `{a, b, rssi}` | 노드 간 RSSI |
| `sensor.upsert` / `sensor.trigger` | `{id, kind, lat, lon}` / `{id, conf?}` | 아두이노 센서 |
| `report.new` | `{type, sender, raw_text, summary, fields, missing, conf, priority}` | **음성 AI** |
| `target.upsert` / `target.remove` | `{id?, affiliation, kind, lat, lon, ...}` | 수동 / 융합 |
| `alert.new` | `{level, kind, msg, unit_id?}` | 임의 |

- **SALUTE 위치**는 절대좌표 `{"lat","lon"}`나 보고자 기준 상대좌표 `{"bearing","dist","err"}` 둘 다 받습니다. 상대좌표면 서버가 절대좌표로 바꿔 표적을 자동 생성합니다.

## 시나리오 / REALTIME 모드

| 모드 | 동작 |
|---|---|
| **시나리오** | 전 소대 mock + 스크립트 이벤트 (기본) |
| **REALTIME** | **1-1 GPS=COP mock**, **1-2~1-4=단말 relpos**, **HQ·2·3 mock**, 메시 링크=COP 합성. 분대원 미수신 시 두절. 시나리오 연출 없음 |

- TopBar에서 `시나리오` / `REALTIME` 전환, 또는 `POST /api/mode {"mode":"realtime"}`
- 분대장 단말기(라우터): `ws://<노트북>:8000/ws/router` — 분대원 `unit.relpos` 상향 + 하향 명령
- **분대장1 SoftAP+BLE**: 보드 AP 조인 후 `COP_Q3=1` — NU40 측위(`POS_TABLE`)·명령은 `leader-q3/host/ble/` (`soldier-node` 프로토콜)
- 이상적 relpos 주기: **1초** (분대장 GPS·붉은 메시 링크는 COP mock)
- HW mock 테스트: `python3 tools/router_mock.py` (relpos만) 또는 `leader-q3/host/bridge_server.py --demo`

입력 경로:

- HTTP: `POST /api/ingest` (단일 이벤트 또는 배열)
- **Router WS**: `ws://…/ws/router` (realtime 1분대)
- **Q3 SoftAP TCP**: `COP_Q3=1` → 보드 `192.168.4.1:9000` NDJSON
- UDP: `:5005` (한 줄에 JSON 하나)
- 시리얼: `COP_SERIAL=/dev/tty.usbmodemXXXX ./run.sh` (게이트웨이가 NDJSON 출력)

```bash
python3 tools/send_event.py salute
python3 tools/send_event.py sensor S-2
python3 tools/router_mock.py          # realtime 1분대 mock
# 분대장1 SoftAP (보드에서 ap_start + bridge_server 후)
COP_MODE=realtime COP_Q3=1 COP_Q3_HOST=192.168.4.1 ./run.sh
```

## 확장 가이드

- **새 이벤트**: `state.py`에 `@handler("my.event")` 함수를 하나 추가하면 됩니다.
- **새 경보 규칙**: `Store.periodic_checks()`에 추가합니다.
- **새 패널**: `frontend/src/components/`에 컴포넌트를 만들고 `useCop((s) => s.xxx)`로 구독한 뒤 `App.tsx`에 배치합니다.
- **새 데이터 컬렉션**: `models.py`와 `types.ts`에 모델을 추가하고, `state.COLLECTIONS`와 `store.ts`의 `emptyCollections`에 이름을 넣습니다.
- **로컬 LLM 브리핑**: Ollama 기준 예시입니다.
  ```bash
  ollama pull exaone3.5:2.4b
  COP_LLM_URL=http://localhost:11434/v1 COP_LLM_MODEL=exaone3.5:2.4b ./run.sh
  ```
- **지도 배경**: SoftAP(인터넷 없음) 대비 **오프라인 타일이 기본**입니다. 온라인 레이어는 우상단에서 전환.
- **오프라인 타일 준비** (인터넷 되는 PC에서 한 번, SoftAP 접속 전에):
  ```bash
  python3 tools/fetch_offline_tiles.py          # Esri 위성 z14–19 → tiles/ (OSM.org 미사용)
  ```
  타일이 있으면 대시보드가 자동으로 「오프라인 (시연 AOI)」를 켭니다. Vite·백엔드 모두 `/tiles/{z}/{x}/{y}.png`로 서빙합니다.
- CARTO 베이스맵은 API 키가 필요합니다. `frontend/.env.local`에 `VITE_CARTO_KEY=…` (선택).
- 타일이 없어도 미터 격자는 항상 표시됩니다.

## 주요 API

| | |
|---|---|
| `GET /api/state` | 전체 스냅샷 |
| `WS /ws` | `snapshot` → `patch{c, op, v}` / `mission` / `stats` |
| `POST /api/reports/{id}` | `{status: confirmed\|rejected}` |
| `POST /api/alerts/{id}/ack`, `/api/alerts/ack_all` | 경보 확인 |
| `POST /api/emcon` | `{on: bool}` |
| `POST /api/sim` | `{action: start\|stop\|restart}` |
| `GET/POST /api/mode` | `scenario` \| `realtime` (1분대 HW · HQ·2·3 mock) |
| `WS /ws/router` | 분대장 단말기 라우터 (상향 relpos + 하향 명령) |
| `POST /api/briefing` | `{question?}` → `{text, engine}` |


## v0.2 추가 기능

### 보고 승인 워크플로
- 보고 카드에서 **승인 / 수정·승인 / 재확인 / 기각**을 할 수 있습니다. 결심이 끝난 보고는 **오보 처리**, **누락 재요청**, **되돌리기**가 가능합니다.
- **수정·승인**은 AI가 잘못 뽑은 규모·활동·유형·MEDEVAC 항목을 고친 뒤 승인합니다. 수정한 값은 지도 표적에도 반영됩니다.
- **재확인**을 누르면 보고자에게 `RECHECK` 명령이 내려갑니다. 보고자가 보완 보고(`report.amend`)를 보내면 신뢰도·필드·누락 항목이 갱신됩니다.
- 결심 결과는 보고자 단말로 내려가고(`report.update` + 진동), 단말 ACK가 오면 카드에 "단말 수신 ✓"가 표시됩니다.
- 모든 결심은 카드의 이력과 `backend/data/audit.jsonl`(사후검토용)에 남습니다.

### 명령 하달 (지도 하단 패널)
- 수신 대상(전 소대·본부·분대·선택 인원) → 명령(정지·이동·집결·엄폐·사격중지·사격자유·단편명령) → 지점(이동·집결은 지도 클릭) → 내용 순으로 입력하고 **하달**합니다.
- 수신 노드별 ACK를 집계해 진행바와 미수신자 목록으로 보여줍니다.
- 미수신자에게는 8초 간격으로 최대 4회 자동 재전송하고, 그래도 안 되면 만료 경보를 띄웁니다. 수동 재하달과 취소도 가능합니다.
- 두절됐던 노드가 복구되면 못 받은 명령을 즉시 재전송합니다(저장 후 전달).
- 하향(Mac→Arduino): SoftAP `COP_Q3=1` 시 `order.new` 등이 보드 `bridge_server`로 전달됩니다 (MCU LED + BLE 명령). 최근 내역은 `GET /api/downlink`.

### AI 브리핑 (로컬 LLM)
- 백엔드가 `http://localhost:11434`(Ollama)를 자동으로 찾습니다. 연결되면 토큰 단위로 스트리밍하고, 연결이 없으면 규칙 기반 엔진으로 자동 전환합니다. 규칙 기반도 의도 분류형 질의응답을 지원합니다.
- 방향·거리 같은 기하 계산은 서버가 미리 끝내서 [사실] 목록으로 넘기고, LLM은 요약과 표현만 맡습니다. 그래서 소형 모델도 수치를 틀리지 않습니다. 패널의 "근거 보기"로 이 목록을 확인할 수 있습니다.
- 지원 기능: 모델 선택, LLM 켜기/끄기, 자동 주기 브리핑(1·3·5분), 음성 질의(브라우저 STT), 이전 답변 보기.

```bash
# Mac에서 로컬 LLM 준비 (최초 1회)
brew install ollama        # 또는 https://ollama.com 에서 앱 설치
ollama serve &             # 앱을 설치했다면 생략
ollama pull exaone3.5:2.4b # 한국어 소형 모델 (약 1.6GB). 여유가 있으면 exaone3.5:7.8b
./run.sh                   # 자동 탐지됨. 다른 서버는 COP_LLM_URL=http://host:port[/v1]
```
