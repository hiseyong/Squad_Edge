# 분대장 → 소대장 규격 보고 프로토콜 v0.1 (초안)

> 대상 독자: 소대장 노트북(Squad Edge COP) 담당, 분대장 단말(Arduino UNO Q) 담당, 각자의 코딩 AI.
> 상태: **초안**. 분대장 측이 제안하고 소대장 측이 검토한다. 바꿀 점은 §12 질문 목록에 답하거나 이 문서를 고쳐서 공유한다.
> 전송 계층은 이미 동작 중인 COP 링크(leader-q3 `bridge_server.py` 규격)를 그대로 쓴다. 이 문서는 그 위에 **보고(report) 메시지**를 정의한다.

---

## 0. 요약

| 항목 | 결정 |
|---|---|
| 링크 | 분대장 보드 Wi-Fi AP `SquadEdge-1-1` (보드 `192.168.4.1`) → TCP `:9000`, 한 줄에 JSON 하나 (NDJSON, UTF-8) |
| 보고 메시지 | 기존 `report.new` 확장 (기존 필드 `type/sender/priority/conf/summary/fields/missing` 유지 + `fmt`, `rpt`, `text`, `body`, `gen`) |
| 보고 내용 | **규격 텍스트**(사람이 읽는 고정 양식) + **구조화 본문**(COP 지도·LLM 브리핑용 JSON) 두 가지를 함께 보낸다 |
| 생성 방식 | 분대장 보고 음성(STT) + 현재 전투 데이터 → **규격 본문 생성 (규칙, 선택적으로 LLM 정정본)** → 검증 → 분대장 복창·확인 → 송신. LLM 현황은 §6.4 |
| 사실 값의 출처 | 좌표·인원수·시각·거리는 **전투 데이터에서만**. LLM은 음성 내용을 칸에 분류하고 요지 문장만 쓴다 (§6) |
| 소대장 응답 | `report.ack` (수신 확인), `report.query` (상세·재송 요청) |
| 우선순위 | `flash` 섬광 > `urgent` 긴급 > `priority` 우선 > `routine` 보통 |
| ID | 분대장 `1-1`, BLE 병사 n → `1-(n+1)` (기존 COP 규칙) |

---

## 1. 전송 계층 (기존, 변경 없음)

- 분대장 보드가 AP를 열고 `192.168.4.1:9000`에서 대기, 노트북이 접속한다. 접속 직후 보드가 `router.hello`를 보낸다.
- 한 줄 = JSON 객체 하나, 끝은 `\n`. 모르는 `type`은 무시한다(앞으로의 확장 대비).
- 공통 봉투:

```json
{"v": 1, "type": "report.new", "src": "1-1", "dst": "PL", "bytes": 412, "data": { ... }}
```

| 필드 | 설명 |
|---|---|
| `v` | 봉투 버전 `1` |
| `type` | 메시지 종류 |
| `src` / `dst` | 보낸 쪽 / 받는 쪽 (`PL` = 소대장) |
| `bytes` | 실제 무선(전술망)으로 보낸다면 예상 크기. COP 표시용, 선택 |
| `data` | 메시지별 내용 |

이미 쓰고 있는 메시지(변경 없음): `router.hello`, `unit.position`, `unit.relpos`, `unit.status`, `alert.new`, `link.update`, `ack`, 병사 단건 `report.new`(`data.type = "CONTACT"`), 하향 `order.new`, `mission.update`, `report.update`, `haptic`.

`router.hello.data`에 `"report_format": "sq-rpt/0.1"`이 있으면 분대장 단말이 이 문서의 보고를 보낸다는 뜻이다.

---

## 2. 보고가 만들어지는 흐름 (분대장 단말 내부, 참고용)

```
① 계기
   - 분대장이 보고 버튼(PTT) 누르고 말함            예) "적이 좌측으로 우회 중, 고수하겠음, 의무후송 요청"
   - 또는 사건 발생 → 초안 자동 생성 후 분대장에게 "보고 준비됨" 알림
     (최초 적 접촉, 아군 부상, 병사 연결 두절, 적 규모 2배·거리 절반, 10분 무보고)
② 음성 인식 (기존 STT): 스트리밍 Zipformer + 전처리 + 띄어쓰기 복원·군 용어 교정·숫자 정규화
③ 전투 데이터 스냅샷: 적 표적(병사 보고 융합·교차 추정), 아군 위치·상태, 위험 지점, 전투 로그
④ LLM 생성: 입력 = ②의 텍스트 + ③의 스냅샷(JSON) → 출력 = §5 본문 JSON (문법 강제, §6)
⑤ 검증: §6.3 규칙. 실패하면 규칙 기반 생성기로 같은 본문을 만들고 gen.by = "rule"
⑥ 복창: 요지 + 핵심을 분대장 헤드셋으로 읽고 "송신할까요?" → 분대장 버튼 [송신 / 수정 / 취소]
   빈칸이 있으면 되묻는다 (예: "현재 조치?", "의무후송 요청?")
⑦ 송신: report.new. 같은 보고를 고치면 같은 rpt.id, rev + 1
```

소대장 측은 ④⑤를 구현할 필요가 없다. 받은 보고의 `gen`으로 누가 만들었는지만 알 수 있으면 된다.

---

## 3. `report.new` 확장 형식

```json
{
  "v": 1, "type": "report.new", "src": "1-1", "dst": "PL", "bytes": 412,
  "data": {
    "type": "SITREP",
    "sender": "1-1",
    "priority": "flash",
    "conf": 0.8,
    "summary": "적 3명 북동 250m 좌측 우회 중. 아군 1명 부상. 고수. 의무후송 요청.",
    "fields": { "location": {...}, "size": 3, "activity": "좌측 우회 중" },
    "missing": [],

    "fmt": "sq-rpt/0.1",
    "rpt": {"id": "1-1-0007", "rev": 0, "ts": 1791634834.1, "dtg": "101432", "kinds": ["SPOT", "SIT", "MEDEVAC"]},
    "text": "<§4 규격 텍스트>",
    "body": { "<§5 구조화 본문>" },
    "gen": {"by": "llm", "model": "gemma-3-1b-it-Q4_0", "ms": 9800, "checks": "pass", "fallback_reason": null},
    "voice": {"text": "적이 좌측으로 우회 중, 고수하겠음, 의무후송 요청", "stt": "zipformer-ko-174m", "conf": null}
  }
}
```

| 필드 | 형 | 설명 |
|---|---|---|
| `type` | 문자열 | 대표 보고 종류: `SPOTREP`(적정 중심) / `SITREP`(상황) / `MEDEVAC` / `ACE`. 기존 COP 분류용 |
| `sender` | 문자열 | 분대장 ID |
| `priority` | 문자열 | `flash` / `urgent` / `priority` / `routine` (§8) |
| `conf` | 0~1 | 보고 전체 신뢰도. 분대장이 확인 후 송신하면 0.8 이상. 자동 송신(§8.3)은 0.5 |
| `summary` | 문자열 | 요지 한 줄 (= `body.summary`). 80자 이내 |
| `fields` | 객체 | 기존 COP 호환용 요약 (주 표적의 `location`/`size`/`activity`) |
| `missing` | 문자열 배열 | 분대장이 채우지 않은 칸 (예: `["action"]`) |
| `fmt` | 문자열 | `"sq-rpt/0.1"`. 이 값이 있으면 아래 필드가 있다 |
| `rpt.id` | 문자열 | 보고 번호 `{분대장ID}-{4자리 순번}`. 분대장 단말 재부팅 후에도 이어진다 |
| `rpt.rev` | 정수 | 정정 횟수. 0 = 최초. 같은 `id`의 큰 `rev`가 이전 것을 대체한다 |
| `rpt.ts` / `rpt.dtg` | 수 / 문자열 | 작성 시각: 유닉스 초 / 군 일시그룹 `DDHHMM`(현지 시각) |
| `rpt.kinds` | 배열 | 이 보고에 들어 있는 양식: `SPOT`(SALUTE) `SIT` `ACE` `MEDEVAC` |
| `text` | 문자열 | §4 규격 텍스트. 사람이 그대로 읽는다 |
| `body` | 객체 | §5 구조화 본문 |
| `gen` | 객체 | 누가 만들었나: `by` = `llm` / `rule`, `checks` = `pass` / `fail`, 실패 시 `fallback_reason` |
| `voice` | 객체 | 분대장 원 발화(STT 결과). 감사·확인용, 선택 |

---

## 4. 규격 텍스트 (`data.text`)

사람이 읽는 고정 양식. **줄 순서와 머리말은 고정**, 해당 없는 줄은 생략한다. 줄 구분 `\n`, 한 줄 120자 이내.

```
[섬광] 101432 1분대→소대장 적정·상황보고 #0007
요지: 적 3명 북동 250m 좌측 우회 중. 아군 1명 부상. 고수. 의무후송 요청.
적1: 규모 보병 3명(병사2 보고) / 활동 좌측 우회 중 / 위치 52S CF 5815 1863 ±25m 교차추정 / 관측 1429~1432 / 장비 미상
위험: 폭발물 의심 52S CF 5803 1851 (3번 보고, 1431)
아군: 위치 52S CF 5800 1843 정면 북동 / 가용 4/5 / 부상 3번 / 탄약 이상없음 / 두절 없음
조치: 고수
요청: 의무후송(긴급 1명)
판단: 적이 좌측으로 우회하려는 것으로 보임
후송: 1)52S CF 5800 1843 2)- 3)긴급1 4)없음 5)보행불가1 6)적 있음 7)- 8)아군 9)-
```

| 줄 | 머리말 | 내용 규칙 |
|---|---|---|
| 1 | `[우선순위]` | `[섬광]` `[긴급]` `[우선]` `[보통]` + `DTG` + `분대→소대장` + 보고 이름 + `#보고번호`. 정정이면 끝에 `정정1` |
| 2 | `요지:` | 항상 있음. 무엇이 / 어디서 / 무엇이 필요한가 |
| 3~ | `적n:` | 적 표적마다 한 줄, 최근 갱신 순 최대 3개. SALUTE 순서: 규모 / 활동 / 위치(±오차, 근거) / 관측 시각 / 장비 |
| | `위험:` | 폭발물 의심, 아군 부상자 발견 지점 |
| | `아군:` | 분대장 위치, 정면 / 가용 인원 / 부상자 / 탄약·화기 / 연락 두절·무선 침묵 |
| | `조치:` | 현재 조치 (분대장 발화). 없으면 `미보고` |
| | `요청:` | 소대장에게 요청하는 것. 없으면 `없음` |
| | `판단:` | 분대장의 판단·추정 (선택) |
| | `후송:` | 9개 항목 의무후송 요청 초안 (부상자 + 의무후송 요청이 있을 때만). 모르는 항목은 `-` |

- 직전에 송신한 보고와 같은 줄은 내용을 `변동 없음`으로 바꾼다 (요지는 항상 전체). 전체 내용은 `body`에 늘 들어 있다.
- 좌표는 군사 격자(MGRS) **100km 구역 포함 8자리** (10m 단위). 근거: TC 3-21.75 표 9-1.
- 방향은 절대 방위(8방위 또는 도). "몇 시 방향"은 분대장 기준이라 소대장에게는 쓰지 않는다.

---

## 5. 구조화 본문 (`data.body`)

```json
{
  "summary": "적 3명 북동 250m 좌측 우회 중. 아군 1명 부상. 고수. 의무후송 요청.",
  "enemy": [{
    "tid": 1,
    "size": {"count": 3, "count_text": "3명", "kind": "infantry", "src": "fused", "reporters": ["1-2", "1-4"],
             "leader_count": null},
    "activity": {"text": "좌측 우회 중", "code": "FLANK_LEFT", "src": "voice", "trend": null},
    "location": {"mgrs": "52S CF 5815 1863", "lat": 36.3023, "lon": 127.42017, "err_m": 25,
                 "basis": "triangulated", "rel": {"ref": "1-1", "dx": 150, "dy": 200}},
    "time": {"first": 1791634789, "last": 1791634804},
    "equipment": {"text": "미상", "src": null}
  }],
  "hazards": [{"kind": "UXO_SUSPECT", "mgrs": "52S CF 5803 1851", "by": "1-4", "ts": 1791634830}],
  "friendly": {
    "mgrs": "52S CF 5800 1843", "lat": 36.3005, "lon": 127.4185, "heading": 45,
    "total": 5, "available": 4,
    "casualties": [{"id": "1-4", "kind": "self", "ts": 1791634830, "urgency": "urgent"}],
    "ammo_issue": [], "lost": [], "silent": []
  },
  "action":   [{"text": "고수", "code": "HOLD", "src": "voice"}],
  "requests": [{"text": "의무후송", "code": "MEDEVAC", "detail": {"urgent": 1}, "src": "voice"}],
  "judgment": [{"text": "적이 좌측으로 우회하려는 것으로 보임", "src": "voice"}],
  "medevac9": {"1": "52S CF 5800 1843", "2": null, "3": {"urgent": 1}, "4": "none", "5": {"litter": 1},
               "6": "enemy_possible", "7": null, "8": "friendly", "9": null},
  "delta": {"since": "1-1-0006", "unchanged": ["friendly"]}
}
```

### 5.1 값의 출처 `src` (모든 항목에 붙는다)

| 값 | 뜻 | 소대장 화면 권장 |
|---|---|---|
| `sensor` | 병사 단말 보고·GPS 등 기계 값 그대로 | 기본 표시 |
| `fused` | 여러 병사 보고를 융합한 값 (같은 적 묶기, 교차 추정) | 근거(`reporters`, `basis`) 함께 표시 |
| `voice` | 분대장 발화에서 뽑은 값 | "분대장 판단" 표시 |
| `llm` | LLM이 만든 문장 (`summary` 등) | 원 발화(`data.voice`)와 대조 가능하게 |

분대장 발화와 병사 보고가 다르면 둘 다 남긴다: `size.count`(병사 융합)와 `size.leader_count`(분대장 판단).

### 5.2 코드표

| 칸 | 코드 |
|---|---|
| `activity.code` | `APPROACH` 접근 · `FLANK_LEFT`/`FLANK_RIGHT` 좌·우측 우회 · `FIRING` 사격 중 · `AMBUSH` 매복 · `DIG_IN` 진지 구축 · `WITHDRAW` 이탈 · `HALTED` 고착 · `MOVING` 이동 · `OBSERVING` 관측 · `UNKNOWN` |
| `action.code` | `HOLD` 고수 · `TAKE_COVER` 엄폐 · `OBSERVE` 경계 · `ENGAGED` 교전 중 · `OPEN_FIRE` 사격 개시 · `FIRE_CONTROL` 사격 통제 · `CEASE_FIRE` 사격 중지 · `WITHDRAW` 철수 · `MOVE` 이동 예정 · `WAIT` 대기 · `SELF_EVAC` 자체 후송 |
| `requests.code` | `MEDEVAC` 의무후송 · `FIRE_SUPPORT` 화력 지원(`detail.asset`: `mortar`/`artillery`) · `REINFORCE` 증원 · `RESUPPLY` 재보급(`detail.class`: `ammo`) · `GUIDANCE` 지침 · `ILLUM` 조명 |
| `hazards.kind` | `UXO_SUSPECT` 폭발물 의심 · `CASUALTY_FOUND` 아군 부상자 발견 · `SUSPICIOUS` 의심 징후 |
| `location.basis` | `triangulated` 교차 추정 · `single` 단독 보고 · `same_bearing` 같은 방향 복수 보고 · `voice` 분대장 발화 · `none` |
| `size.count` | 0 = 미상, 1~4, 5 = 5명 이상 (병사 단말 규격과 같음) |

단위: 거리 m, 각도 도(진북 기준 시계방향), 시각 유닉스 초. 모르는 값은 `null` (빈 문자열 금지).

---

## 6. LLM 생성 규칙 (분대장 단말 내부, 소대장 측 참고)

### 6.1 입력

```json
{"voice": "<STT 결과 텍스트>",
 "snapshot": {"now": ..., "enemy": [...], "friendly": {...}, "hazards": [...], "last_sent": "<직전 보고 body 또는 null>"}}
```

`snapshot`은 §5 형식에서 `summary`·`action`·`requests`·`judgment`를 뺀 것 (= 규칙·융합으로 이미 계산된 사실).

### 6.2 LLM이 하는 일과 하지 않는 일

| LLM이 한다 | LLM이 하지 않는다 |
|---|---|
| 발화를 `activity` / `action` / `requests` / `judgment`로 분류하고 코드 선택 | 좌표, 인원수, 거리, 시각, 부상자 ID 만들기 (스냅샷에서 복사만) |
| 분대장이 말한 수치를 `leader_count` 등 `voice` 칸에 옮기기 | 스냅샷에 없는 적·아군 추가 |
| `summary` 한 줄 쓰기 | 우선순위 정하기 (§8 규칙으로 결정) |
| 빈칸 목록(`missing`) 판단 | 송신 결정 (항상 분대장 확인) |

- 출력은 **문법 강제**(llama.cpp GBNF / JSON 스키마)로 §5 형식만 나오게 한다. 자유 문장 출력 없음.
- 대화 기록을 쓰지 않는다 (보고마다 독립). 고정 지시문은 캐시해서 재사용한다.

### 6.3 검증 (하나라도 실패하면 `gen.by = "rule"`로 대체)

1. `summary`와 모든 `text`에 나오는 숫자가 스냅샷 또는 발화에 있는 숫자다 (지어낸 수치 차단).
2. 발화에 부정·금지 표현이 있는데 해당 칸에서 빠지지 않았다 ("고수하지 않음" → `HOLD` 금지).
3. 코드는 §5.2 표에 있는 값이다.
4. 좌표·인원·부상자 칸이 스냅샷과 같다.
5. `summary` 80자 이내, 생성 시간 제한(기본 15초) 안.

### 6.4 왜 이렇게 나누는가 (실측 근거, 2026-10-10 분대장 보드)

- 보드(Cortex-A53 4코어)에서 1B급 모델은 입력 6~20 토큰/초, 출력 4~12 토큰/초. 답 하나에 8~30초.
- 교범 답변 다듬기 실험에서 근거에 없는 숫자를 지어낸 사례가 있었다 ("지혈대 1~2주 사용"). → 사실 값은 LLM에게 맡기지 않는다.
- 그래서 **보고는 항상 규칙 기반 본문을 먼저 송신(`gen.by="rule"`)하고, LLM 본문이 검증을 통과하면 같은 `rpt.id`의 `rev+1`로 보낸다.**
- 이 문서의 발화 칸 생성(§6.2)을 보드에서 실측한 결과 (2026-10-10, 발화 "적이 좌측으로 우회 중, 고수하겠음, 의무후송 요청"):

  | 모델 | 시간 | 결과 |
  |---|---|---|
  | Gemma 3 1B Q4_0 | 73초 | 활동=매복, 조치=자체 후송 (오분류) |
  | Qwen2.5 0.5B Q4_0 | 33초 | 활동=매복, 조치=자체 후송, 요청=증원 (오분류) |
  | 규칙 추출 | 0.03초 | 좌측 우회 / 고수 / 의무후송 (정답) |

  코드가 표 안의 값이라 형식 검증은 통과하지만 뜻이 틀린다. → 미세조정으로 해결: **현재 기본값은 미세조정 Qwen2.5-0.5B(`sq-nlu-qwen2.5-0.5b-instruct-q4_0`) 켬**. 규칙본(rev 0)을 먼저 보내고, LLM이 발화를 칸(코드)으로 나눈 결과가 검증을 통과하고 규칙본과 다를 때만 정정본(rev+1, `gen.by="llm"`)을 보낸다. 요지 문장은 LLM이 쓰지 않고 규칙이 만든다. 평가(음성 인식 흉내 59문장): 규칙 F1 0.49·정답 31% / 0.5B F1 0.76·정답 68%·중앙 3.6초 / 1.5B F1 0.84·정답 73%·10.8초(느려서 제외). `--llm none`이면 규칙만. 소대장 측은 `gen.by` 값과 상관없이 같은 형식을 받는다.

---

## 7. 소대장 → 분대장 응답

| type | data | 뜻 |
|---|---|---|
| `report.ack` | `{"ref": "1-1-0007", "rev": 0, "by": "PL"}` | 수신 확인. 분대장 헤드셋에 "소대장 수신" |
| `report.query` | `{"ref": "1-1-0007", "ask": "detail" \| "resend" \| "field", "field": "enemy[0].location"}` | 상세·재송·특정 칸 확인 요청. 분대장 헤드셋에 읽어 준다 |

- 기존 `report.update`(→ `ack`)도 계속 받는다.
- 분대장 단말은 `flash`/`urgent` 보고에 10초 안에 `report.ack`가 없으면 같은 `rpt.id`·`rev`로 1회 재송신한다.

---

## 8. 송신 규칙

### 8.1 우선순위 (규칙으로 결정, LLM 관여 없음)

| priority | 조건 |
|---|---|
| `flash` 섬광 | 최초 적 접촉, 아군 새 부상 |
| `urgent` 긴급 | 폭발물 의심, 적 규모 2배·거리 절반, 탄약·화기 문제, 병사 연락 두절, 분대장 요청이 있음 |
| `priority` 우선 | 활성 적 표적이 있음 |
| `routine` 보통 | 정기 상황보고 (10분 무보고), 특이사항 없음 |

### 8.2 변동분

`body.delta.unchanged`에 직전 송신 보고와 같은 항목을 적고, `text`의 해당 줄은 `변동 없음`. `body`에는 항상 전체 값이 있다 (소대장이 중간 보고를 놓쳐도 복원 가능).

### 8.3 확인 없는 송신

기본은 **항상 분대장 확인 후 송신**. 섬광 초안을 분대장이 30초 안에 처리하지 않으면 "자동 송신할까요?"를 한 번 더 묻고, 그래도 응답이 없으면 `conf = 0.5`, `missing`에 `"leader_confirm"`을 넣어 송신한다. (팀 결정 필요: §12-3)

### 8.4 크기

`text` 약 300~600바이트, 전체 메시지 약 1.5~3KB. 지금 링크(Wi-Fi)에는 문제없음. 실제 전술망을 가정할 때는 `text`만 보내는 축약 모드를 둘 수 있다 (`bytes`에 `text` 크기 표기).

---

## 9. 전체 예시 (NDJSON 한 줄씩)

```json
{"v":1,"type":"report.new","src":"1-2","dst":"PL","bytes":40,"data":{"type":"CONTACT","sender":"1-2","priority":"urgent","conf":0.9,"summary":"1-2 접적","fields":{"kind":"infantry","activity":"접적","location":{"bearing":41,"dist":200,"err":30},"size":3},"missing":[]}}
{"v":1,"type":"alert.new","data":{"level":"crit","kind":"wia","msg":"1-4 본인 부상","unit_id":"1-4"}}
{"v":1,"type":"report.new","src":"1-1","dst":"PL","bytes":438,"data":{"type":"SITREP","sender":"1-1","priority":"flash","conf":0.8,"summary":"적 3명 북동 250m 좌측 우회 중. 아군 1명 부상. 고수. 의무후송 요청.","fields":{"location":{"bearing":37,"dist":250,"err":25,"mgrs":"52S CF 5815 1863","ref":"1-1"},"size":3,"activity":"좌측 우회 중"},"missing":[],"fmt":"sq-rpt/0.1","rpt":{"id":"1-1-0007","rev":0,"ts":1791634834.1,"dtg":"101432","kinds":["SPOT","SIT","MEDEVAC"]},"text":"[섬광] 101432 1분대→소대장 적정·상황보고 #0007\n요지: ...","body":{"summary":"...","enemy":[...],"friendly":{...},"action":[{"text":"고수","code":"HOLD","src":"voice"}],"requests":[{"text":"의무후송","code":"MEDEVAC","detail":{"urgent":1},"src":"voice"}]},"gen":{"by":"rule","model":null,"ms":35,"checks":"pass","fallback_reason":null},"voice":{"text":"적이 좌측으로 우회 중, 고수하겠음, 의무후송 요청","stt":"zipformer-ko-174m","conf":null}}}
{"v":1,"type":"report.new","src":"1-1","dst":"PL","bytes":452,"data":{"...같은 보고, LLM 요지...":"","rpt":{"id":"1-1-0007","rev":1,"...":""},"gen":{"by":"llm","model":"gemma-3-1b-it-Q4_0","ms":9800,"checks":"pass"}}}
{"v":1,"type":"report.ack","src":"PL","dst":"1-1","data":{"ref":"1-1-0007","rev":1,"by":"PL"}}
```

---

## 10. 소대장 측 구현 체크리스트

1. `report.new`에서 `data.fmt == "sq-rpt/0.1"`이면 `text`를 보고 창에 고정폭으로 표시, `body`로 지도 갱신.
2. `rpt.id`가 같고 `rev`가 크면 이전 보고를 대체 (목록에 "정정" 표시).
3. `body.enemy[].location`을 지도에 표시: `err_m` 반경 원 + `basis`에 따라 실선(교차 추정)/점선(단독).
4. `src == "voice"` 또는 `gen.by == "llm"` 값은 "분대장 판단/요약"으로 구분 표시.
5. 수신 즉시 `report.ack` 송신.
6. 모르는 필드·코드는 무시 (앞으로 추가될 수 있음).

---

## 11. 분대장 측 구현 현황 (2026-10-10)

| 부분 | 상태 |
|---|---|
| AP + TCP 링크, `router.hello` / 위치 / 병사 단건 보고 / 경고 | 동작 (`squad/link/cop.py`, `tools/cop_link.py`) |
| STT (스트리밍 Zipformer + 전처리 + 후처리) | 동작 (`squad/speech/stt.py`) |
| 전투 데이터 집계 (적 융합·교차 추정·추세, 아군 상태, 전투 로그) | 동작 (`squad/report/situation.py`, `log.py`) |
| 규칙 기반 보고 생성 (`gen.by = "rule"`), 이 문서 형식 | 동작 (`squad/report/sqrpt.py`, `desk.py`) |
| LLM 생성 (`gen.by = "llm"`) + 검증, 정정본 rev+1 | 구현됨, **기본 켬** (미세조정 0.5B, §6.4) |
| `report.ack` / `report.query`, 섬광·긴급 10초 무응답 1회 재송신 | 동작 |
| 보고 번호 재부팅 후 이어짐 | 동작 (`data/report_seq.txt`) |

---

## 12. 소대장 측에 묻는 것

1. **텍스트와 본문을 함께 받는 것**에 동의하는가? (권장: 함께. 텍스트는 사람용, 본문은 지도·브리핑용)
2. 소대장 노트북 LLM 브리핑이 쓰기 좋은 `body` 칸이 더 있는가? (예: 적 의도 추정 코드, 분대 임무 진행률)
3. 분대장 확인 없이 자동 송신하는 경우(§8.3)를 허용하는가?
4. 좌표는 MGRS 문자열 + 위경도를 둘 다 보내는데, 하나만 필요한가?
5. 같은 보고의 정정(`rev`)을 화면에서 어떻게 보여줄 것인가?
6. `report.ack`를 사람(소대장)이 누를 때 보내는가, 노트북이 수신 즉시 자동으로 보내는가? (분대장 헤드셋 문구가 달라진다)
