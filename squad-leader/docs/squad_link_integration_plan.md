# 분대-병사 링크 통합 계획 (S0 결과, 병사 팀 답변 반영판)

- 작성: 2026-10-10. 개정: 2026-10-11, 병사 팀 안내문 반영.
- 작업 지시: `docs/LEADER_TASK.md`
- 레퍼런스(읽기 전용): `<REF_PATH>` = `~/work/soldier-node_ref_v1.1`
  - 수정하지 않았다. `docs/HANDOFF_MANIFEST.txt`의 sha256 103개가 모두 일치한다.
- 기준과 우선순위
  1. **구성·역할 분담**: 병사 팀 안내문 `docs/soldier_team_reply_2026-10-11.md`(확정판, 결정 D1~D7)
  2. **바이트·타이밍·규칙**: `<REF_PATH>/docs/squad_ble_protocol_v1.md` v1.1과 `golden_vectors.json`
  3. 둘이 충돌하면 멈추고 병사 팀에 알린다.
  - LEADER_TASK의 일부 항목(S4 분대장 비콘 송출·분대장 줄 RSSI, S5 침묵 방송 경로)은 안내문 D1~D4로 **대체**됐다(§2).
- 상태: S0 완료 → **S1 완료(2026-10-11)**: `squad/soldier/`(codec·adpcm·geo·localize·dedup·seq·voice·config) + `tests/test_soldier_golden.py` 22개(골든 전 항목 + 경계 규칙 + 레퍼런스 교차 확인) 통과, 기존 93개 포함 115개 통과. C1·C2·C6 적용. → **S2 완료(2026-10-11)**: `squad/soldier/ble.py`·`leader.py`·`txlog.py`·`describe.py`, `tools/soldier_cli.py`. 레퍼런스 mock_leader와 같은 조작에서 분대장 송신 프레임 바이트 동일, S1·S2 동시 연결, 끊김 감지·자동 재연결, 재연결 뒤 notify 중복 버그 수정. → **S3 완료(2026-10-11)**: h1~4·8·9·11·12 통과, 5(음성) 실기 생략, 6·7 일부. → **키패드 하달 앞당겨 구현(2026-10-11)**: `mcu/keypad/keypad.ino`(MCU, arduino-router 알림), `squad/input/keypad.py`(판정·명령 조립), `tools/soldier_cli.py --keypad`. 실기: 키 배선 D2~D9 확인, `2 → 9 길게 → #` = 전원 9시 엄폐, `D D 9 9 9 9 2길게 D길게×3 #` = S2 적 3명 2시 원거리(`01 10 xx 00 02 06 09 3C 00 02 03 00`) 병사 재생 확인. PTT 키(A·B·C)는 S5에서 STT·보고·교범에 연결. → **S4 완료(2026-10-11)**: h10·11·13~16 통과, 적 보고 → 분대장 기준 위치(target_estimate). → **S5-1 완료(2026-10-11)**: `tools/leader_app.py`(통합 실행기, AP 192.168.4.1:9000), 적 발견 자동 보고(병사 CONTACT·분대장 키패드 적 위치 → 분대장 기준 위치 → `contact_event`, 소대장 노트북 표시 확인), 분대원 위치 중계, 병사 보고 → 헤드셋 문장(가이드 e)·전투 로그·상황 정리. 보고 모델(사용자 정정): A 키 PTT = 정형화된 보고서(양식), 전투 종료 뒤 발화 = 전투 데이터 보고. 남은 것: S5-2 헤드셋 TTS·PTT STT, S5-3 전투 데이터 보고.

---

## 1. S0에서 한 일

### 1.1 읽은 것
- 문서
  - `REFERENCE_README.md`
  - 프로토콜 v1.1: 전체, §0.1과 부록 B 포함
  - 가이드 a~i
  - `golden_vectors.json`: 프레임 50, 광고 5, CRC 3, ADPCM, 시계 변환 14+7, peer_to_me 5, pathloss 12, rssi_median, localize 3
  - 침묵·공유 메모 2개
- 도구: `frame_codec.py`, `adpcm.py`, `mock_leader.py`(전체), `squad_localize.py`, `fit_pathloss.py`, `gen_clips.py`
- 펌웨어: `LeaderBeacon.ino`
- `<REF_PATH>/CLAUDE.md`는 참고만 하고 따르지 않았다.

### 1.2 레퍼런스 자체 시험 (UNO Q)

원본을 바꾸지 않도록 scratchpad 사본에서 `sh tools/run_selftests.sh`를 돌렸다. 원본에서 돌리면 `tests/host/build`와 `__pycache__`가 생긴다.

| 항목 | 결과 |
|---|---|
| frame_codec, adpcm, test_vectors(부록 A: 4000B, CRC 0x0166) | 통과 |
| squad_localize, fit_pathloss, earpiece 자체 시험 | 통과 |
| gen_golden --check, test_golden(50 frames, 5 adv, 148 checks) | 통과 |
| test_mock_leader_offline | 시스템 python3에 bleak가 없어 건너뜀. 저장소 venv(bleak 3.0.2)로 돌려 **통과** |
| C 호스트 테스트 12종 | 전부 통과 |
| 최종 | **ALL SELFTESTS PASSED** |

### 1.3 이 저장소 조사

| 항목 | 현황 |
|---|---|
| 언어·런타임 | Python 3.13.5 `.venv`(bleak 3.0.2, numpy, scipy, sherpa-onnx…), `third_party/llama.cpp` |
| 진입점 | 통합 앱 프로세스는 없다. 기능별 도구로 나뉘어 있다: `tools/cop_link.py`(asyncio, 소대장 TCP·보고 시나리오·NLU), `mic_test.py`(STT), `ask_manual.py`(교범), `tts_demo.py` |
| 구조 | `squad/protocol.py`(v1.0.2), `adpcm.py`, `audio/`, `speech/`(stt·tts·announce), `report/`, `link/`(cop·motion), `manual/`, `text/` |
| 루프·스레드 | - 소대장 링크: asyncio<br>- STT: 큐 스레드<br>- TTS·LLM: 블로킹(`asyncio.to_thread`)<br>- 오디오: `AudioArbiter` + Player 스레드 |
| 설정·테스트·로깅 | argparse·모듈 상수, `python -m unittest discover -s tests`(93개), `logging`, CombatLog(sqlite) |
| STT 흐름 | 에어팟 → 맥 → `adb forward tcp:7100` → 보드 → DSP → Zipformer → 띄어쓰기·교정·정규화 → 텍스트 → 도구별 소비(`SqDesk.draft`, `ManualIndex`) |
| TTS 출력 | sherpa-onnx VITS → **16 kHz 모노 float32** → `AudioArbiter` → `RemotePlayer`(같은 adb 연결로 맥에 s16le) |
| 소대장 통신 | - AP `uap0` 192.168.4.1(2.4 GHz) + TCP :9000 NDJSON(`link/cop.py`)<br>- 섬광·긴급 보고는 ACK 10초 대기 후 1회 재송<br>- **노트북이 끊겼을 때 저장 후 재송하는 큐는 없다** |
| 기존 병사 프로토콜 코드 | - `protocol.py`(v1.0.2): 골든 프레임 50개 왕복은 일치, 시계 변환 1건 불일치(heading `FFFF`)<br>- `orig_seq`·`0x8000`·RANGING 해석 없음<br>- 거리 50·100·200 m가 남아 있다(`link/cop.py:DIST_M`, `report/situation.py:DIST_REP` 등) |

### 1.4 UNO Q 환경 (명령 출력으로 확인)

| 항목 | 결과 |
|---|---|
| OS·커널·Python | Debian 13, Linux 6.16.7 aarch64, Python 3.13.5 |
| BlueZ / 컨트롤러 | bluetoothd 5.82(`-E` 없음), hci0 = **Qualcomm WCN3988**(UART), BT 5.1, central+peripheral |
| 일반 사용자 BLE 스캔 | 가능(bleak 3.0.2). 10초에 장치 **424대**(현장 혼잡). 그때는 `SQ1-S*`가 없었다 |
| 메모리·CPU | 가용 1.8 GB(llama 0.5B 435 MB 상주), 스왑 0.6 GB 사용. 4코어 A53, load 1.4 |
| 무선 칩 공유 | **Wi-Fi(ath10k, WCN3990 계열)와 BT가 같은 칩**. AP는 2.4 GHz ch6 → 공존 위험 |
| MCU(키패드용) | `arduino-router.service` 실행 중(`/run/arduino-router.sock` rw), `arduino-cli` + `arduino:zephyr` 0.51.0. Python `msgpack` 없음 |

---

## 2. 확정된 구성 (병사 팀 안내문 D1~D7)

```
동료 맥북 ══ USB-C(상시) ══ UNO Q ── BLE 연결(Central) ── 병사 SQ1-S1, SQ1-S2 …
보드 A(배터리, 분대장 몸에 부착) ── 비연결형 광고만 ──▶ 병사들   (UNO Q와 연결 없음)
```

| # | 결정 | 이 앱에 미치는 영향 |
|---|---|---|
| D1 | 보드 A는 UNO Q와 완전히 독립(배터리, USB 없음) | 시리얼·`BCN`·`OK tx/DONE`·`lbeacon`·`bcmd/bemcon` 구현 **안 함** |
| D2 | UNO Q는 **BLE Central만** 한다. 광고·비콘 스캔·sudo 없음 | §0.1 **8번(침묵 방송)과 분대장 비콘 송출 제외**. BlueZ 광고 검증 단계 삭제 |
| D3 | 침묵 중 명령·해제는 **보드 A 버튼**(1 정지, 2 엄폐 9시, 3 사격 중지, 4 짧게 집결 / **4 길게 EMCON_SET 2 해제**) | 앱은 침묵 중 송신하지 않는다. 분대장에게 "침묵 중, 보드 A 버튼 사용"을 알린다 |
| D4 | 위치 계산은 **병사 RANGING만** 쓴다(peer 0 = 분대장 거리). 분대장 줄 없음 | `measured_from_rssi`에 병사 줄만 넣는다 |
| D5 | 분대장 방위는 **0(북) 고정** | 시계 ↔ 방위 변환에 heading 0. COP 이동 모의 heading과 분리. POS_TABLE heading = 0 |
| D6 | 입력 방식은 자유, 결과는 CMD_BUTTON 6필드 규칙 | 키패드 초안(§9) 진행. RALLY의 azimuth는 항상 `FFFF` |
| D7 | P1m −65.5, n 1.6, 반올림은 **0에서 먼 쪽**, 거리 10·20·40 m | 설정 상수로 명시(기본 인자에 기대지 않음). `round()` 대신 직접 구현 |

---

## 3. 매핑 표 A: 프로토콜 §0.1 체크리스트

`S/` = `squad/soldier/` (신규)

| # | 기능 | 넣을 곳 | 레퍼런스 | 단계 |
|---|---|---|---|---|
| 1 | 프레임 인코드/디코드·검증 | `S/codec.py:encode/decode/encode_payload/decode_payload`(frame_codec 1:1 포팅, 필드 이름 동일) | `frame_codec.py` | S1 |
| 2 | `SQ1-S1`~`S5` 스캔·다중 연결·Notify·MTU·재연결(침묵 중에도 계속) | `S/ble.py:BleLink`. 연결 실패(`InProgress`)면 스캔 정지 → 연결 → 재개 | `mock_leader.py:Leader.scan_forever/connect/on_disconnect` | S2 |
| 3 | 보고 → 즉시 RPT_ACK(재전송에도 다시), 재전송 표시 | `S/leader.py:on_frame/send_rpt_ack` + `S/dedup.py`(병사·seq·**바이트 동일**·60초, 새 연결 때 초기화) | `Leader.on_notify/send_rpt_ack`, 가이드 f-4 | S1·S3 |
| 4 | 보고 → 사람이 읽는 문장(TTS) | `S/phrases.py`(가이드 e) → 기존 `Announcer`·`AudioArbiter` | 가이드 e, `describe` | S5 |
| 5 | CMD_BUTTON + 대상별 ACK/수행 불가, 15초 → 같은 바이트 1회 → "미수신" | `S/leader.py:send_cmd/on_cmd_ack/watch_cmds` | `Leader.send_cmd/on_cmd_ack/watch_cmds` | S3 |
| 6 | 음성 BEGIN/CHUNK/END(청크 간격 15 ms), VOICE_RESULT≠0이면 1회 재전송, **침묵 중 금지** | `S/voice.py:prepare_8k`(load_wav_8k 전처리, TTS 배열 입력) + `S/adpcm.py` + `S/leader.py:send_voice` | `load_wav_8k`, `stream_voice`, `on_voice_result`, `adpcm.py` | S1·S3 |
| 7 | EMCON_SET(연결) | `S/leader.py:send_emcon` | `Leader.send_emcon` | S3 |
| 8 | ~~침묵 방송~~ | **보드 A 버튼이 맡는다(D2·D3).** 앱은 구현하지 않는다 | — | — |
| 9 | POS_TABLE(id 0 포함, heading 0) | `S/leader.py:send_pos` + `S/localize.py` | `Leader.send_pos`, `squad_localize.py` | S1·S4 |
| 10 | PEER_REPORT 중계(orig_seq, 0x8000, 재전송은 중계 안 함, 보고자 제외) | `S/leader.py:on_peer_report` | `Leader.on_peer_report` | S3 |
| 11 | REQ_STATS/STATS | `S/leader.py:req_stats` | `handle("stats")` | S3 |
| 12 | 분대장 비콘·병사 비콘 RSSI | **보드 A가 비콘을 낸다. UNO Q는 재지 않는다(D4).** 병사 RANGING의 peer 0만 쓴다 | — | — |
| 13 | RANGING → 거리 → MDS → 정렬 → POS_TABLE | `S/leader.py:pos_auto` + `S/localize.py`(병사 줄만, 30초 만료, `DEFAULT_CLOCKS {1:10, 2:2}`) | `Leader.rssi_rows/send_pos("auto")`, `localize` | S1·S4 |
| 14 | LOG·HEARTBEAT·직접 방송 무시 | LOG는 별도 로그 파일에 기록만 한다 | — | S3 |

## 4. 매핑 표 B: 가이드 b항

| mock_leader 명령 | 이 앱에서 | 입력 | 단계 |
|---|---|---|---|
| (자동) 스캔·연결, `pending_acks` | `S/ble.py`(연결 완료 전에 온 보고의 RPT_ACK는 모았다가 송신) | 자동 | S2 |
| (자동) 보고 → RPT_ACK | `S/leader.py:on_frame` | 자동 | S3 |
| `relay on/off` | `SquadLeader.relay`(기본 on) | 시험 CLI | S3 |
| `cmd …` | `send_cmd(code, clock, band, extra, prio, targets)` | 키패드·STT 명령어·소대장 `order.new` | S3·S5 |
| `voice …` | `send_voice(pcm16k, prio, targets)` | STT 자유 문장 → TTS → 음성 하달 | S3·S5 |
| `emcon …` | `send_emcon(mode, targets)`(연결 write) | 키패드·음성 | S3 |
| `bcmd`/`bemcon`/`lbeacon`/`--beacon-port`/`BCN` | **해당 없음**(D1·D2) | — | — |
| `pos wedge/line/column` | `send_pos(preset)` | 키패드·CLI | S4 |
| `pos auto [id:시계]` | `send_pos("auto", clocks)` | 키패드·CLI | S4 |
| `pos dist …` | `send_pos("dist", …)`(예비) | CLI | S4 |
| `peer …` | `send_peer(…)`(시험용, 가짜 orig_seq 128~) | CLI | S3 |
| `map` / `dist` | 텍스트 로그 + COP `unit.relpos`(기존 Telemetry) | CLI | S4 |
| `mark` | 보정 기록 행(fit_pathloss 호환 CSV) | CLI | S4 |
| `stats` / `raw` / `ack on/off` | `req_stats` / `write_raw` / `auto_ack` | CLI | S2·S3 |
| `--log-csv` | `S/txlog.py`: mock_leader와 같은 CSV 열 + JSONL, 항상 켬 | — | S2 |

- 시험 CLI(`tools/leader_app.py --cli`)는 mock_leader 명령어 문법을 따른다. 시험 재현용이다.
- **`--seq-start N`**: 시험 때만 seq 시작값을 지정한다. 운용은 무작위다(P1 답).

---

## 5. 새 모듈 구조

```
squad/soldier/            # 신규. 포팅 파일 머리에 "포팅 원본: <REF_PATH>/tools/…" 표기
  codec.py      frame_codec 포팅(+ 광고 AD 파싱은 시험용으로만)         S1
  adpcm.py      adpcm 포팅 + CRC-16/CCITT-FALSE                          S1
  geo.py        시계↔방위(§7.1), 거리 구간, peer_to_me, 경로손실, RSSI 중앙값, 0에서 먼 쪽 반올림   S1
  localize.py   squad_localize 포팅(병사 줄만, 상수 −65.5/1.6 명시)      S1
  dedup.py      보고 중복 판정                                           S1
  seq.py        분대장 seq(무작위 시작, --seq-start 시험 옵션)           S1
  voice.py      PCM → 8 kHz 전처리 → ADPCM 프레임                        S1
  config.py     PATHLOSS, DEFAULT_CLOCKS, 시간 상수(15 s·60 s·30 s·15 ms), 분대장 heading 0   S1
  ble.py        bleak Central(스캔·연결·MTU·notify·재연결·병사별 쓰기 직렬화)   S2
  txlog.py      송수신 CSV·JSONL                                         S2
  leader.py     분대장 상태기계(Transport 추상화): ACK·명령·음성·EMCON·중계·위치·통계   S3·S4
  phrases.py    보고 → 문장(가이드 e), 미수신·침묵·음성 실패 알림        S5
squad/input/keypad.py     MCU 키 이벤트(arduino-router) → 동작           S5
mcu/keypad/keypad.ino     4×4 스캔 → Bridge 알림
tools/leader_app.py       통합 실행기(+ --cli, --seq-start)
tests/test_soldier_golden.py   골든 벡터 전 항목 (S1 통과 기준)
tests/test_soldier_leader.py   가짜 Transport로 상태기계 (mock_leader_offline 방식)
```

- 시간 의존 로직은 `now`를 주입해 시험한다.
- `leader.py`는 BLE를 모르고 `Transport.write(sid, raw, response)`만 쓴다. 그래서 오프라인 시험과 실기에서 같은 코드가 돈다.

## 6. 기존 코드 변경 (승인 필요, 병사 팀 의견 반영)

| # | 파일 | 변경 | 병사 팀 의견 | 시점 |
|---|---|---|---|---|
| C1 | `link/cop.py` `DIST_M`, `report/situation.py` `DIST_REP`·`DIST_UNKNOWN`·게이트 | 50·100·200 → **10·20·40 m**, 없음 → **20 m**, 구간 경계 15/30, 게이트 비례 조정 | **필수** | S1 |
| C2 | `squad/protocol.py` | 시계 변환을 §7.1 규칙대로 수정(heading `FFFF` → 0으로 간주). 이후 사용처를 `squad/soldier/`로 옮기고 protocol.py는 얇은 호환층으로 둔다 | **필수** | S1(수정)·S5(이전) |
| C3 | `speech/announce.py` | 가이드 e 문장 규칙(CASUALTY_FOUND 거리, "N번 쪽/기준") | v1.1과 충돌 여부로 판단 → 따름 | S5 |
| C4 | `link/cop.py`(소대장 링크) | **분리(사용자 지시 2026-10-11)**: 소대장 링크에서 병사 통신 관련을 걷어낸다 — `squad.protocol` import, `order_to_frames`·`ORDER_TO_CMD`(소대장 지시 → 병사 명령), `mission.update` emcon → 병사 EMCON_SET, `soldier_report_events`(병사 보고 → 소대장 자동 전달), `DIST_M`, `ble_live`. **분대원 위치(`unit.relpos`)는 계속 보낸다**: 병사와 소대장은 직접 연결되지 않고, 분대장이 받아 정리한 위치(분대장 기준 동·북 m — 실기에서는 RANGING → 위치 복원 결과)를 분대장 앱이 `Telemetry.members`로 넘기면 소대장 링크가 중계한다. 소대장 지시·임무 변경은 분대장에게 알리기만 한다(분대장이 판단해 병사에게 하달) | 사용자 지시 | S2 전 |
| C5 | `report/*`, `tools/cop_link.py` | 병사 보고는 **분대장 상황 정리(Situation)와 전투 로그에만** 들어간다. 소대장에게는 분대장이 정형 보고서(sq-rpt/0.1)를 보낼 때만 그 안에 반영된다(적 표적 융합·아군 현황). 지금 구조(`SqDesk`가 `Situation`을 읽어 보고서 작성)를 유지하고, 병사 보고 입력원만 실제 링크로 바꾼다. 시연 시나리오의 병사 보고 자동 전달은 뺀다 | 사용자 지시 | S2 전(전달 제거)·S5(입력원) |
| C5b | 전투 로그(`report/log.py` CombatLog) | 병사 보고를 원 프레임 hex·해석·수신 시각·병사 번호로 저장 | 사용자 지시 | S3 |
| C6 | `docs/squad_ble_protocol_v1.0.2.md` | 맨 위에 "대체됨 → v1.1" 표시만 | 〃 | S1 |
| C7 | `requirements.txt` | bleak 3.0.2 고정 명시, msgpack 추가(키패드 승인 시) | bleak 3.0.2 진행 | S2·S5 |

- 기존 시험 93개는 매 단계 계속 통과해야 한다.
- STT·TTS 엔진과 `audio/*`는 바꾸지 않는다.

## 7. 이벤트 루프 통합

- 프로세스 하나, asyncio 루프 하나(`tools/leader_app.py`): bleak, COP 서버, 키패드 RPC 소켓.
- 블로킹 작업(STT 스레드, TTS·LLM은 `to_thread`, 오디오 Player 스레드)에서 루프로 넘길 때는 `call_soon_threadsafe`를 쓴다.
- RPT_ACK는 notify 콜백에서 즉시 쓰기 태스크로 보낸다(병사 긴급 재전송 3초보다 먼저).
- 병사별 GATT 쓰기는 직렬화한다. 음성 청크 사이에 RPT_ACK·명령을 끼워 넣는다.
- 타이머 태스크(0.5초 주기): 명령 15초, RANGING 30초 만료, 재연결 감시.
- 시작할 때 `free -m`을 로그로 남긴다.

## 8. BLE 구현

- BlueZ + bleak 3.0.2(Q1 답)
  - 이름 필터 `^SQ1-S[1-5]$` + NUS UUID, 콜백 초기 필터(현장 400대 이상)
  - 연결 직후 `_acquire_mtu()` → **MTU를 로그로 출력**(23이면 3.0.2용 확보 방법을 찾고, 안 되면 1.1.1 검토)
  - TX notify 구독, `len ≤ MTU−3`
  - 제어·명령은 With Response, 음성 청크는 Without Response
- 연결된 병사가 다 차면 스캔을 멈춘다. 침묵 중에도 재연결 스캔은 계속한다.
- 광고 송출·비콘 스캔은 하지 않는다(D2·D4).
- 위험: Wi-Fi AP와 같은 칩이다 → S2에서 AP를 켠 상태로 연결 유지 시간과 끊김 원인(0x08)을 기록한다.

## 9. 키패드(4×4, 8핀) 설계 초안 v2 — 병사 팀 "그대로 진행 가능", 구현은 S5

배치(일반 4×4 멤브레인):
```
 1  2  3  A
 4  5  6  B
 7  8  9  C
 *  0  #  D
```

| 키 | 짧게 | 길게(≥1.0 s) / 누르고 있기 |
|---|---|---|
| A | — | **보고 PTT**: 누르는 동안 말함 → 보고 초안 → 복창 → `#` 송신 / `*` 취소 |
| B | — | **교범 질문 PTT**: 누르는 동안 질문 → 답변 재생 |
| C | — | **병사 음성 하달 PTT**: 누르는 동안 말함 → 정해진 명령어면 CMD_BUTTON, 아니면 음성 하달 → 복창 → `#` 송신 |
| D | 대상 순환: 전원 → 1번 → … → 5번 → 전원 | 거리 순환: 없음 → 근 → 중 → 원 |
| 1~9, 0 | 명령 선택(아래 표). 적 위치(9)에서 9를 다시 누르면 적 수 순환(미상→1→…→4→다수) | 방향 "N시"(10·11·12시는 1 길게 → 이어서 0·1·2 짧게) |
| * | 입력 취소. 입력 중이 아니면 CANCEL 명령 선택 | REPORT_STATUS(상태 보고 요청) 선택 |
| # | **송신 확정**. 대기 중이면 마지막 안내 다시 듣기 | SILENCE(무선 침묵) 선택 |

명령 → CMD_BUTTON(병사 팀 안내문 §5, 분대장 방위 0 고정: azimuth = (시계 × 30) mod 360)

| 키 | 명령 | cmd_code | 방향 | 거리 | extra | priority |
|---|---|---|---|---|---|---|
| 1 | 정지 HALT | 0x01 | 없음(FFFF) | FF | 0 | 1 긴급 |
| 2 | 엄폐 TAKE_COVER | 0x02 | 선택 | FF | 0 | 1 긴급 |
| 3 | 전진 ADVANCE | 0x03 | 선택 | FF | 0 | 0 |
| 4 | 후퇴 WITHDRAW | 0x04 | 선택 | FF | 0 | 1 긴급 |
| 5 | 집결 RALLY | 0x05 | 항상 FFFF(병사가 계산) | FF | 0 | 0 |
| 6 | 사격 개시 OPEN_FIRE | 0x06 | **필수** | 선택 | 0 | 1 긴급 |
| 7 | 사격 중지 CEASE_FIRE | 0x07 | 없음 | FF | 0 | 1 긴급 |
| 8 | 경계 OBSERVE | 0x08 | **필수** | FF | 0 | 0 |
| 9 | 적 위치 ENEMY_INFO | 0x09 | **필수** | 선택 | 적 수 0 미상·1~4·5 다수 | 0 |
| 0 | 고수 HOLD | 0x0C | 없음 | FF | 0 | 0 |
| * 짧게 | 취소 CANCEL | 0x0F | 없음 | FF | 0 | 0 |
| * 길게 | 상태 보고 REPORT_STATUS | 0x0A | 없음 | FF | 0 | 0 |
| # 길게 | 무선 침묵 SILENCE | 0x0B | 없음 | FF | 0 | 1 긴급 |

- 흐름: 명령 키 → (방향) → (거리) → (적 수) → `#` → 복창 "엄폐, 9시, 전원, 송신".
- 필수 방향이 없으면 "방향 필요"를 알리고 보내지 않는다. 침묵(EMCON 0) 중에는 송신하지 않고 "침묵 중, 보드 A 버튼"을 알린다.
- priority는 초안(병사 재생에서 긴급은 진행 중 재생을 끊음). 보드 A 버튼과 같은 정지·엄폐 긴급을 따랐다.

배선(확인 필요): 키패드 8핀(왼쪽부터 R1~R4, C1~C4가 일반적) → UNO Q 디지털 D2~D9.
- R1~R4 → D2~D5(스캔 출력), C1~C4 → D6~D9(입력, 내부 풀업). 외부 저항·전원 불필요(수동 스위치 행렬).
- D0·D1(UART, GPS 예정), D10~D13(SPI)은 비운다. MCU 3.3V 로직이지만 키패드는 전압을 내지 않으므로 무관.
- 핀 순서는 제품마다 다를 수 있어, 첫 연결 때 MCU 시험 스케치로 키 이름을 확인한다.

## 10. S5 연동 설계

1. **병사 보고 → 분대장**: 가이드 e 문장(heading 0 기준 시계) → 기존 Announcer/Arbiter(조각 캐시). CASUALTY_SELF는 최우선으로 2회.
2. **병사 보고 → 전투 로그·상황 정리**: 전투 로그 저장(C5b) + `Situation`(적 표적·아군 현황). 소대장에게는 분대장이 정형 보고서를 보낼 때만 반영된다(C5).
3. **분대장 음성 → 병사**: 키 C PTT → STT → 명령어 사전("정지", "9시 엄폐", "사격 중지", "집결", "고수", "경계 2시", "적 3명 2시 원거리", "무선 침묵", "N번/전원").
   - 사전에 맞으면 CMD_BUTTON을 보낸다.
   - 아니면 TTS 16 kHz → `prepare_8k` → ADPCM 음성 하달을 보낸다.
4. **EMCON 경로**
   - 연결 중이면 연결로 송신한다.
   - **침묵 중이면 앱은 송신하지 않는다.** 음성·명령 요청에는 "침묵 중: 보드 A 버튼 1 정지 / 2 엄폐 9시 / 3 사격 중지 / 4 집결 / 4 길게 해제"를 알린다.
5. ~~소대장 지시 → 병사~~: 삭제(분리 원칙). 소대장 지시는 소대장 링크 쪽에서 분대장 헤드셋으로 읽어 주기만 한다.
6. **미확인**: 15초 → 1회 재전송 → "N번 미수신"(헤드셋, 전투 로그).
7. **EMCON 전환**
   - 진입: 키 C 길게 또는 음성 "무선 침묵" → 연결 write EMCON_SET 0 / SILENCE → 병사 연결이 끊긴다(정상).
   - 해제: 보드 A 버튼4 길게, 또는 병사 직접 → 앱 자동 재연결 → EMCON_STATE + 큐에 쌓인 보고·ACK 수신.
8. **데모 시나리오**: LEADER_TASK S5 순서에서 "침묵 중 방송 명령"을 보드 A 버튼으로 바꾼다.

## 11. 위험 요소

| 위험 | 대응 |
|---|---|
| WCN 한 칩에 Wi-Fi AP(2.4 GHz) + STA + BLE 다중 연결 | 광고·스캔을 없애 부하를 줄였다(D2·D4). S2에서 AP를 켠 상태로 끊김 빈도를 기록하고, 필요하면 AP 채널·대역 조정을 검토한다 |
| bleak 3.0.2 MTU | 첫 연결 때 MTU 출력. 23이면 대응한다 |
| 현장 혼잡(10초 424대) | 이름 필터·콜백 초기 필터, 다 연결되면 스캔 정지 |
| 메모리(LLM·STT·TTS 동시) | BLE는 경량. LLM은 `--llm none`으로 끌 수 있다 |
| 업로드 전 병사 펌웨어(거리 v1.0.4 미반영 등) | 수락 시험 최종 판정은 업로드 뒤. 그 전에는 왕복 위주 |
| 보드 A가 원점 | 분대장 몸(UNO Q 옆)에 부착 |

## 12. 프로토콜 이슈와 질문 — 현재 상태

### 12.1 병사 팀 답변 완료
- **P1 seq**: 운용은 무작위 시작. 비교는 seq 바이트를 빼거나 `--seq-start N`(권장) → **`--seq-start` 구현**.
- **P2 반올림**: 0에서 먼 쪽이 기준. 레퍼런스 `round()`는 레퍼런스 결함 → **따라 하지 않고 직접 구현**.
  - 골든 벡터에는 .5 경우가 없다. 우리 시험에는 .5 경계 사례를 추가한다.
- **P3 경로손실**: −65.5/1.6을 설정 상수로 명시. 레퍼런스 기본 인자 −59/2.0은 옛 값.
- **P4 DTR**: 해당 없음.
- **P5 분대장 방위**: 0 고정.
- 질문 1(bleak 3.0.2)·2(보드 A 독립)·4(heading 0)·6(보드 켜짐)·7(sq-rpt/0.1 유지)·8(sudo 불필요): 답변 완료.

### 12.2 남은 것 — 사람(분대장 담당) 승인

- **A1** 기존 코드 변경: C1·C2·C3·C5·C6·C7 승인(2026-10-11). C4는 "소대장 링크와 병사 링크 완전 독립" 원칙으로 바꿔 승인.
- **A2** 키패드
  - 실제 배선 핀(행·열 → MCU 핀)
  - `msgpack` 설치 승인(`.venv/bin/pip install msgpack`)
  - S5 전까지만 정하면 된다.
- **A3** S1 시작 승인

## 13. 단계별 통과 기준 확인 방법

- **S1**: `tests/test_soldier_golden.py`가 golden_vectors.json 전 항목(frames 50, advertising 5 파싱, crc16 3, adpcm, 시계 14+7, peer_to_me 5, pathloss 12, rssi_median, localize 3)을 바이트·값 단위로 통과해야 한다. .5 반올림 경계 사례를 추가하고, 기존 시험 93개도 통과해야 한다.
- **S2**
  - mock_leader 원본을 UNO Q에서 돌려 정답 CSV를 만든다. 병사 팀 mock_leader는 꺼 둔다.
  - 이 앱(`--seq-start` 같은 값)으로 같은 조작을 해서 hex가 같은지 본다. 연결·MTU·보고·RPT_ACK·명령·ACK를 확인한다.
- **S3**
  - 가이드 h항 1~5, 8, 9, 12를 재현한다.
  - 6·7은 보드 A 버튼 방식으로 바꿔서 한다. 업로드 전에는 병사가 직접 해제한다.
- **S4**: 같은 입력으로 `squad_localize.py`(P2·P3 차이는 제외)와 출력이 같아야 한다. h항 10·11·13~15를 재현하고, 16은 실측 배치다.
- **S5**: 데모 시나리오를 1회 완주한다(침묵 명령은 보드 A).
