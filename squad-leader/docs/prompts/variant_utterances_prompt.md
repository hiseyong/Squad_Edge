# 변형 발화 생성 프롬프트 (분대장 보고 → 규격 보고 칸 학습·평가용)

아래 "프롬프트" 블록 전체를 ChatGPT/Claude 등에 붙여 넣는다. 한 번에 100개씩, 3번 요청해서 300개를 만든다.
(두 번째부터는 "이어서 101~200번, 앞과 겹치지 않게"처럼 요청)
결과는 `utterances.jsonl` 하나로 합쳐서 전달 → `data/utterances/` 에 넣는다.

---

## 프롬프트

```
너는 한국군 분대 무전 교신 데이터를 만드는 전문가다. 분대장이 무전기 PTT를 누르고 소대장에게 상황을 보고하는 "말"을 만들고, 각 말에 정답 라벨을 붙인다. 이 데이터는 음성 인식 결과를 보고 칸으로 분류하는 소형 모델의 학습·평가에 쓴다.

## 상황
- 화자: 보병 분대장 (1분대). 분대원은 1~5번 병사.
- 청자: 소대장. 분대장은 급박한 상황에서 짧게, 구어체로 말한다.
- 입력은 음성 인식 결과다. 문장부호가 없거나 어순이 뒤섞이거나, 말이 끊기거나, "어", "그", "음" 같은 군말이 섞일 수 있다.

## 만들 것: 100개 (id 1~100)
다양성 규칙 (반드시 지킬 것)
1. 말투: 정식 무전체("여기는 1분대, 적 3명 접근 중, 이상") 30%, 급박한 구어체("야 왼쪽으로 돌아온다 버텨") 40%, 반말·은어·군대 속어 섞인 말 30%.
2. 길이: 대부분 5~40글자, 10%는 40~80글자의 긴 보고, 10%는 2~5글자 단답("엄폐 중", "후송 요청").
3. 숫자: 한글 수사("세 명", "삼백 미터", "두 시 방향")와 아라비아 숫자("3명", "300m")를 섞는다.
4. 한 발화에 칸이 0~4개. 아무 칸에도 안 들어가는 발화(잡담, 무전 확인 "감도 어떤가")도 10% 넣는다.
5. 어려운 경우를 반드시 포함 (각 5개 이상):
   - 부정: "철수하지 않고 고수", "사격하지 마라", "후송 필요 없음" → 부정된 것은 라벨에 넣지 않는다
   - 시제: "아까는 엄폐했는데 지금 전진 중" → 현재·예정만 라벨
   - 적과 아군 구분: "적이 사격 중" (적 활동) vs "사격 개시함" (아군 조치)
   - 같은 뜻 다른 말: "돌아 들어온다/옆구리로 붙는다/측면으로 기동" = 우회, "버틴다/자리 지킨다/여기서 막는다" = 고수, "다친 사람 빼 줘/부상자 데려가 줘" = 의무후송
   - 판단·추정: "매복인 것 같다", "본대가 뒤에 있는 듯" → judgment
   - 음성 인식 오류 흉내 5개: "엄페", "사격 게시", "탄냑" 같은 오탈자
6. 같은 문장 반복·단어만 바꾼 복제 금지. 아래 예시를 그대로 베끼지 말 것.

## 라벨 (코드는 아래 표의 값만 사용)
- activity: 적의 행동 (여러 개 가능, 없으면 [])
  APPROACH 접근 | FLANK_LEFT 좌측 우회 | FLANK_RIGHT 우측 우회 | FIRING 사격 중 | AMBUSH 매복 | DIG_IN 진지 구축 | WITHDRAW 이탈·도주 | HALTED 고착·정지 | MOVING 이동(방향 불명확) | OBSERVING 관측·정찰
- action: 우리 분대의 현재 또는 곧 할 조치 (여러 개 가능, 없으면 [])
  HOLD 고수 | TAKE_COVER 엄폐 | OBSERVE 경계 | ENGAGED 교전·응사 중 | OPEN_FIRE 사격 개시 | FIRE_CONTROL 사격 통제 | CEASE_FIRE 사격 중지 | WITHDRAW 철수·후퇴 | MOVE 이동·전진 | WAIT 대기 | SELF_EVAC 자체 후송
- requests: 소대장에게 요청하는 것 (여러 개 가능, 없으면 [])
  MEDEVAC 의무후송 | FIRE_SUPPORT 화력 지원(박격포·포병 포함) | REINFORCE 증원 | RESUPPLY 재보급(탄약 등) | GUIDANCE 지침·명령 요청 | ILLUM 조명 지원
- leader_count: 분대장이 적 수를 말했으면 그 숫자(정수), "다수/여러 명"이면 5, 말하지 않았으면 null
- casualties: 분대장이 말한 아군 부상자 병사 번호 목록 (예: "2번 부상" → [2]). 번호 없이 "부상자 1명"이면 [] 로 두고 casualty_count에 1
- casualty_count: 번호 없이 말한 부상자 수, 없으면 null
- judgment: 분대장의 추정·판단 부분을 발화에서 그대로 잘라낸 문자열 목록 (없으면 [])
- direction: 분대장이 말한 적 방향 "N시" 또는 "좌측/우측/정면/후방/북쪽..." (없으면 null)
- distance_m: 분대장이 말한 적 거리(미터 정수, 없으면 null)
- hard: 위 5번의 어려운 경우에 해당하면 그 종류 ("negation", "tense", "enemy_vs_own", "paraphrase", "judgment", "stt_error"), 아니면 null

## 출력 형식
JSON Lines. 한 줄에 객체 하나, 설명·머리말·코드블록 없이 100줄만 출력한다.
{"id":1,"text":"...","activity":[],"action":[],"requests":[],"leader_count":null,"casualties":[],"casualty_count":null,"judgment":[],"direction":null,"distance_m":null,"hard":null}

## 예시 (형식 참고용, 베끼지 말 것)
{"id":0,"text":"여기는 1분대 적 세 명 두 시 방향 삼백 접근 중 이상","activity":["APPROACH"],"action":[],"requests":[],"leader_count":3,"casualties":[],"casualty_count":null,"judgment":[],"direction":"2시","distance_m":300,"hard":null}
{"id":0,"text":"놈들 왼쪽으로 돌아 들어온다 여기서 버틴다 다친 애 빼 줘","activity":["FLANK_LEFT"],"action":["HOLD"],"requests":["MEDEVAC"],"leader_count":null,"casualties":[],"casualty_count":null,"judgment":[],"direction":"좌측","distance_m":null,"hard":"paraphrase"}
{"id":0,"text":"철수 안 하고 고수한다 탄약 좀 보내줘","activity":[],"action":["HOLD"],"requests":["RESUPPLY"],"leader_count":null,"casualties":[],"casualty_count":null,"judgment":[],"direction":null,"distance_m":null,"hard":"negation"}

## 마지막 확인
출력 전에 각 줄을 스스로 점검한다: 부정된 조치를 라벨에 넣지 않았는가, 적 활동과 아군 조치를 바꿔 넣지 않았는가, 코드가 표에 있는 값인가, JSON이 한 줄로 올바른가.
```

---

## 받은 뒤 처리 (분대장 측)

1. JSON 형식·코드 값 자동 검사, 라벨 일부를 사람이 표본 검토 (생성 모델 라벨도 틀릴 수 있다).
2. 무작위로 학습 240 / 평가 60 분할. 평가 세트는 학습·규칙 수정에 쓰지 않는다.
3. 음성 인식 흉내 변환을 추가로 적용한 사본도 만든다 (띄어쓰기 제거 → 우리 띄어쓰기 복원기, 숫자 정규화) — 실제 파이프라인 입력과 같게.
4. 사실 스냅샷(적 표적·아군 상태)은 우리 쪽에서 무작위로 만들어 붙여 요지 문장 학습에 쓴다.
