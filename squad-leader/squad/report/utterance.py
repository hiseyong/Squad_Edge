"""분대장 발화(STT → 정규화 후) → 보고 칸. 규칙 기반.

분대장에게는 판단과 요청만 말하게 하고 사실 정보(규모·좌표·시각·인원 상태)는 상황 집계기가 채운다.
분대장이 사실을 말하면(예: "적 5명") 자동 값보다 우선하되, 보고서에 둘 다 남긴다.

예) "적이 좌측으로 우회 중, 고수하겠음, 의무후송 요청"
  → activity ["좌측 우회 중"], action ["고수"], requests ["의무후송"]
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# (패턴, 표기) — 적 활동. 앞에 붙은 방향어(좌측·우측·북쪽…)는 함께 남긴다
ACTIVITY = [
    (r"우회", "우회 중"), (r"접근|다가오|다가옴", "접근 중"), (r"사격\s?(중|하고)|쏘고|총격", "사격 중"),
    (r"매복", "매복"), (r"진지\s?(구축|를 파)|참호", "진지 구축 중"), (r"(철수|후퇴|이탈|도주)\s?(중|하고)", "이탈 중"),
    (r"정지|멈춤|고착", "고착"), (r"이동\s?중", "이동 중"), (r"관측|정찰\s?중", "관측 중"),
]
# 아군 조치 (분대장이 "~하겠음/하겠다/중" 으로 말하는 것)
ACTION = [
    (r"고수", "고수"), (r"엄폐", "엄폐"), (r"경계", "경계"), (r"교전|응사", "교전 중"),
    (r"사격\s?개시", "사격 개시"), (r"사격\s?통제", "사격 통제"), (r"사격\s?중지", "사격 중지"),
    (r"(철수|후퇴)\s?(하겠|할\s?예정|예정|중)", "철수"), (r"(이동|전진)\s?(하겠|할\s?예정|예정)", "이동 예정"),
    (r"대기", "대기"), (r"후송\s?(중|하겠)", "자체 후송 중"),
]
# 요청 (…요청 / …필요 / …바람 앞의 명사)
REQUEST = [
    (r"의무\s?후송|메디백|후송", "의무후송"), (r"박격포", "화력 지원(박격포)"), (r"포병|포격", "화력 지원(포병)"),
    (r"화력|사격\s?지원", "화력 지원"), (r"증원|병력", "증원"), (r"탄약|재보급|보급", "재보급(탄약)"),
    (r"지침|지시|명령", "지침"), (r"조명", "조명 지원"),
]
RE_REQUEST_TAIL = re.compile(r"(요청|필요|바람|부탁|지원\s?바|보내\s?줘|달라)")
RE_JUDGE = re.compile(r"(것\s?같|추정|예상|의도|보임|판단|가능성)")
RE_DIR_WORD = re.compile(r"(좌측|우측|정면|후방|북쪽|남쪽|동쪽|서쪽|북동|북서|남동|남서|좌|우)\s?(으로|쪽으로|에서)?")
RE_ENEMY_COUNT = re.compile(r"적\s?(?:병력\s?)?(?:약\s?)?(\d+)\s?명")
RE_COUNT = re.compile(r"(\d+)\s?명")
RE_CLOCK = re.compile(r"(\d{1,2})\s?시\s?방향")
RE_DIST = re.compile(r"(\d+)\s?(m|km)\b")
RE_CASUALTY = re.compile(r"(\d)\s?번\s?(?:병사\s?)?(부상|전사|사망|쓰러)")
RE_CASUALTY_N = re.compile(r"부상자?\s?(\d+)\s?명")


@dataclass
class Utterance:
    raw: str = ""
    enemy_count: int | None = None
    enemy_clock: int | None = None         # 분대장 기준 시계 방향
    enemy_dist_m: int | None = None
    activity: list[str] = field(default_factory=list)
    action: list[str] = field(default_factory=list)
    requests: list[str] = field(default_factory=list)
    casualty_ids: list[int] = field(default_factory=list)
    casualty_n: int | None = None
    judgment: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.activity or self.action or self.requests or self.casualty_ids or self.casualty_n
                    or self.enemy_count or self.judgment)


def _clauses(text: str) -> list[str]:
    return [c.strip() for c in re.split(r"[,.;]|\s(?:그리고|하고)\s", text) if c.strip()]


def _first(table, text: str) -> list[str]:
    out = []
    for pat, label in table:
        if re.search(pat, text) and label not in out:
            out.append(label)
    return out


def parse(text: str) -> Utterance:
    u = Utterance(raw=text)
    for c in _clauses(text):
        is_request = bool(RE_REQUEST_TAIL.search(c))
        if is_request:
            for r in _first(REQUEST, c):
                if r not in u.requests and not (r == "화력 지원" and any(x.startswith("화력 지원(") for x in u.requests)):
                    u.requests.append(r)
            continue
        if RE_JUDGE.search(c):
            u.judgment.append(c)
        enemy_clause = "적" in c or not re.search(r"하겠|할\s?예정|예정", c)
        # "적"이 없는 절은 우리 조치로도 본다 ("철수하지 않고 고수")
        own = (re.search(r"하겠|할\s?예정|예정|실시|유지|중\b", c) or "적" not in c) and not c.startswith("적")
        neg = re.compile(r"(하지\s?않|안\s?하|말고|하지\s?말)")
        if own or not enemy_clause:
            for pat, a in ACTION:
                m = re.search(pat, c)
                # 부정된 조치는 빼기 ("철수하지 않고")
                if m and not neg.match(c[m.end():m.end() + 6].lstrip()) and a not in u.action:
                    u.action.append(a)
        if enemy_clause and (c.startswith("적") or "적" in c or not own):
            for act in _first(ACTIVITY, c):
                if act in ("고착",) and own:
                    continue
                d = RE_DIR_WORD.search(c)
                label = f"{d.group(1)} {act}" if d and act in ("우회 중", "이동 중", "이탈 중", "접근 중") else act
                if label not in u.activity:
                    u.activity.append(label)
        if (m := RE_ENEMY_COUNT.search(c)) or ("적" in c and (m := RE_COUNT.search(c))):
            u.enemy_count = int(m.group(1))
        if (m := RE_CLOCK.search(c)) and "적" in c:
            u.enemy_clock = int(m.group(1))
        if (m := RE_DIST.search(c)) and "적" in c:
            u.enemy_dist_m = int(m.group(1)) * (1000 if m.group(2) == "km" else 1)
        for m in RE_CASUALTY.finditer(c):
            if int(m.group(1)) not in u.casualty_ids:
                u.casualty_ids.append(int(m.group(1)))
        if m := RE_CASUALTY_N.search(c):
            u.casualty_n = int(m.group(1))
    # "적이 접근 중" 같은 적 활동이 조치로도 잡히지 않게: 사격 개시/통제는 조치, 사격 중은 적 활동
    return u
