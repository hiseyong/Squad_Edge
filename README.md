# Squad Edge C2 · COP 대시보드

Deploy for Defense 2026: 소부대 오프라인 전술 C2와 음성 AI를 합친 프로젝트의 **소대장용 공통상황도(COP) 대시보드**입니다.

## 빠른 실행

```bash
cd ~/Documents/competition/2026D4D
./run.sh                     # 개발 모드: 0.0.0.0:5173 + :8000 (핫리로드)
./run.sh prod                # 데모 모드: 빌드 후 0.0.0.0:8000 하나로 서빙
./run-mockup.sh              # UI만 시연 (백엔드 없음) → :5174/index.mockup.html
COP_MODE=realtime ./run.sh   # SoftAP 연동 기본(COP_Q3=1 → 192.168.4.1:9000)
COP_MODE=realtime COP_Q3=0 ./run.sh  # SoftAP 끄고 router_mock/WS만
COP_SIM=0 ./run.sh                   # 시뮬레이터 끄고 실제 하드웨어 입력만
```

**UI Mockup** (`./run-mockup.sh`): 서버 없이 COP 화면만. Cloudflare Pages 배포:

| CF Pages 설정 | 값 |
|---|---|
| Root directory | `frontend` |
| Build command | `npm run build:mockup` |
| Build output | `dist-mockup` |
| Node | `20` |

로컬 빌드: `./run-mockup.sh build` · CLI: `./run-mockup.sh deploy` (`wrangler login` 후)

노트북 Wi-Fi를 분대장 보드 AP(`SquadEdge-1-1`)에 연결한 뒤 realtime을 실행합니다. `nc 192.168.4.1 9000`과 동일 NDJSON 스트림입니다.

처음 실행 시 `backend/.venv` 생성과 `npm install`을 자동으로 합니다. Python 3.10+, Node 18+ 필요.
프론트·백엔드 모두 `0.0.0.0` 바인딩 — 같은 AP에서는 `http://<노트북IP>:5173`(개발) 또는 `:8000`(데모)으로 접속합니다.

## 저장소 구조

```
2026D4D/
├── run.sh                 # COP 개발/데모 실행
├── run-mockup.sh          # UI-only mockup (백엔드 없음)
├── README.md
├── docs/
│   └── TERMINAL_PROTOCOL.md   # 단말↔COP NDJSON 프로토콜
├── backend/               # FastAPI COP 서버
│   ├── requirements.txt
│   ├── data/              # audit.jsonl 등
│   └── app/
│       ├── main.py        # HTTP / WS / 모드·명령·브리핑 API
│       ├── models.py      # Unit, Target, Report, Order, …
│       ├── state.py       # Store · 이벤트 핸들러 · 경보 · 명령 하달
│       ├── downlink.py    # 하향 허브 (SoftAP / router WS)
│       ├── briefing.py    # 상황 브리핑 (규칙 / 로컬 LLM)
│       ├── llm.py · geo.py
│       └── sources/
│           ├── simulator.py    # 시나리오 / realtime mock
│           ├── q3_ap.py        # 분대장 SoftAP TCP 클라이언트
│           ├── router.py       # /ws/router
│           ├── ingest_util.py  # 이벤트·보고 정규화 (BATTLE_DATA zlib 등)
│           ├── udp_source.py   # :5005
│           └── serial_source.py
├── frontend/              # React COP UI (Vite)
│   ├── index.mockup.html · vite.config.mockup.ts
│   └── src/
│       ├── App.tsx · main.tsx · main.mockup.tsx · api.ts · store.ts · types.ts
│       ├── mockup/        # UI 데모 시드·엔진·로컬 API
│       ├── components/    # MapView, Roster, FormationView, ReportFeed,
│       │                  # AlertPanel, BriefingPanel, OrderPanel, TopBar
│       └── lib/           # geo, ranks, symbols, unitDisplay, format
├── squad-leader/          # 분대장1 UNO Q 앱 (SoftAP + BLE + STT/TTS)
│   ├── squad/
│   │   ├── link/          # cop.py SoftAP TCP :9000 · motion
│   │   ├── soldier/       # BLE 병사 링크 · 측위 · 프로토콜
│   │   ├── report/        # sq-rpt · BATTLE_DATA · 상황 정리
│   │   ├── speech/ · audio/ · input/ · output/ · manual/ · text/
│   │   └── protocol.py
│   ├── mcu/               # leader_io · keypad 펌웨어
│   ├── tools/             # leader_app.py · cop_link.py · ap_start/stop.sh …
│   ├── docs/              # BLE·보고 프로토콜 · 연동 계획
│   ├── manuals/ · tests/ · deploy/ · data/
│   └── requirements.txt
├── soldier-node/          # 분대원 NU-40 DK 펌웨어·프로토콜 레퍼런스
│   ├── firmware/SoldierNode/ · diag/
│   ├── tools/             # frame_codec · mock_leader · localize …
│   ├── docs/              # squad_ble_protocol_v1 등
│   └── tests/
├── tools/                 # COP 호스트 유틸
│   ├── send_event.py · router_mock.py · fetch_offline_tiles.py
├── scripts/               # setup_ollama.sh · bench_llm.py
└── tiles/                 # 오프라인 지도 타일 (fetch_offline_tiles로 생성)
```

### 데이터 흐름

```
병사 NU-40 ─BLE─▶ 분대장 UNO Q (squad-leader)
                      │ SoftAP TCP NDJSON 192.168.4.1:9000
                      ▼
              backend q3_ap / router  ──▶  state.Store
                      │                      ├ 경보 · 표적 · 보고
                      │                      ├ 명령 하달 (분대장만)
                      │                      └ 브리핑
                      ▼
              WebSocket /ws  ──▶  frontend (React COP)
```

| 경로 | 역할 |
|---|---|
| `backend/app/` | COP 서버·상태·API |
| `squad-leader/` | 분대장 보드: SoftAP·BLE·음성·보고 (`tools/leader_app.py`, `tools/cop_link.py`) |
| `soldier-node/` | 분대원 노드 펌웨어·BLE 프로토콜 레퍼런스 |
| `docs/TERMINAL_PROTOCOL.md` | 봉투·메시지 타입 규격 |
| `tiles/` | SoftAP 오프라인용 위성 타일 |

**스택:** FastAPI + WebSocket · React/TS/Vite · react-leaflet · Zustand · Tailwind · milsymbol · mgrs

## 대시보드 기능

- **지도 COP**: 아군 계급장·진행방향·상태색, 적/미확인 표적(신선도 페이드), 메시 링크(RSSI), 궤적·BLE 오차원·경로/통제선, MGRS, 소대장 Follow
- **부대 현황 / 대형 뷰**: 분대별 상태·측위(GPS/BLE)·배터리 · BLE 상대측위 방사형 대형
- **보고 피드**: SALUTE / SPOT / 접적 / MEDEVAC / SITREP / 적정·상황 / **전투데이터(`BATTLE_DATA`, zlib+base64 펼침)** · 승인 워크플로
- **명령 하달** (`OrderPanel`): 전 소대·분대 대상 선택 → SoftAP로 **분대장에게만** 송신 (`recipients` = SL). 분대원 BLE 개별 전송 없음
- **경보**: 부상·후송·접적·통신두절/측위대기·대형이탈 등
- **AI 브리핑**: 로컬 Ollama 또는 규칙 기반 · realtime 용어(측위대기 ≠ 통신두절)
- **EMCON / 시나리오·REALTIME 전환** (TopBar)

## 시나리오 / REALTIME

| 모드 | 동작 |
|---|---|
| **시나리오** | 전 소대 mock + 스크립트 이벤트 (기본) |
| **REALTIME** | 1-1 GPS=COP mock(연결 시), 1-2~1-4=단말 relpos, HQ·2·3 mock. SoftAP 단절=1분대 통신두절, 연결 중 무좌표=측위대기 |

- TopBar 또는 `POST /api/mode {"mode":"realtime"}`
- **분대장 SoftAP**: 보드에서 AP + COP 링크 후 노트북 조인
  ```bash
  # 보드(UNO Q) — squad-leader
  sudo tools/ap_start.sh
  .venv/bin/python tools/leader_app.py          # SoftAP + BLE + 키패드 (권장)
  # 또는 링크만: .venv/bin/python tools/cop_link.py

  # 노트북
  COP_MODE=realtime ./run.sh                    # COP_Q3=1 기본
  ```
- Router WS 대안: `ws://<노트북>:8000/ws/router` · mock: `python3 tools/router_mock.py`

## 이벤트 프로토콜 (요약)

봉투: `{"type":"<이벤트>","data":{…},"bytes":…}` — 상세는 [`docs/TERMINAL_PROTOCOL.md`](docs/TERMINAL_PROTOCOL.md).

| type | 용도 |
|---|---|
| `unit.position` / `unit.relpos` | GPS / BLE 상대측위 |
| `unit.status` · `link.update` | 상태 · 메시 |
| `report.new` | 구조화 보고 · `BATTLE_DATA`(payload `zlib+base64+json`) |
| `order.new` / `order.cancel` | 하달(분대장) · 철회 |
| `ack` | 명령/보고 수신 확인 |
| `target.*` · `alert.new` · `sensor.*` | 표적·경보·센서 |

**명령 SoftAP 예 (분대장만):**
```json
{"v":1,"type":"order.new","src":"PL","dst":"*","data":{"id":"O-…","code":"HALT","text":"1분대 정지","to":["1"],"recipients":["1-1"],…}}
```

입력 경로: `POST /api/ingest` · `/ws/router` · SoftAP TCP(`COP_Q3`) · UDP `:5005` · 시리얼(`COP_SERIAL=…`)

```bash
python3 tools/send_event.py salute
python3 tools/router_mock.py
python3 tools/fetch_offline_tiles.py   # Esri 위성 → tiles/
```

## 주요 API

| | |
|---|---|
| `GET /api/state` · `WS /ws` | 스냅샷 / patch |
| `POST /api/ingest` | 이벤트 주입 |
| `POST /api/orders` · `…/cancel` · `…/resend` | 명령 하달 |
| `GET /api/downlink` · `WS /ws/downlink` | 하향 큐·스트림 |
| `WS /ws/router` | 분대장 라우터 |
| `POST /api/reports/{id}/decision` | 승인·기각·재확인 |
| `POST /api/alerts/…` · `/api/emcon` · `/api/sim` | 경보·EMCON·시뮬 |
| `GET/POST /api/mode` | `scenario` \| `realtime` |
| `POST /api/briefing` · `/api/briefing/stream` · `/api/llm/…` | 브리핑·LLM |

## 확장 가이드

- **새 이벤트**: `backend/app/state.py`에 `@handler("…")`
- **새 패널**: `frontend/src/components/` + `App.tsx`
- **분대장 보드**: `squad-leader/squad/` · 진입점 `tools/leader_app.py`
- **병사 프로토콜**: `soldier-node/docs/` · `squad-leader/docs/squad_ble_protocol_v1.0.2.md`
- **로컬 LLM 브리핑**
  ```bash
  ollama pull exaone3.5:7.8b   # 또는 2.4b
  COP_LLM_URL=http://localhost:11434 COP_LLM_MODEL=exaone3.5:7.8b ./run.sh
  ```
- **오프라인 타일**: SoftAP 전 `python3 tools/fetch_offline_tiles.py` → `/tiles/{z}/{x}/{y}.png`

## 보고·명령 (요약)

- **승인 워크플로**: 승인 / 수정·승인 / 재확인(`RECHECK`) / 기각 · `backend/data/audit.jsonl`
- **전투데이터**: SoftAP `report.new` type=`BATTLE_DATA` → 서버가 zlib payload 펼침 → Reports 탭에서 적·아군·무전회의록·전문 표시
- **명령 하달**: 대상은 UI상 분대 단위이나 SoftAP 전송·ACK는 **분대장(SL)만**. 분대원 개인 BLE 하달 없음 (`GET /api/downlink`로 확인)
