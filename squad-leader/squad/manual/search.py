"""교범 검색: 결정론적 BM25 (단어 어간 + 한글 2글자 조각) + 동의어 확장 + 질문 의도별 지식 유형 가중.

신경망·LLM 없이 수 ms. 띄어쓰기 오류(PDF 줄바꿈)와 STT 오인식에 덜 민감하도록 2글자 조각을 함께 쓴다.
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass

from .schema import Kind, Paragraph, RType, Relation, Unit, UType

# 조사·어미 (긴 것부터 제거)
_SUFFIXES = sorted("""은 는 이 가 을 를 에 의 로 으로 와 과 도 만 에서 에게 까지 부터 처럼 보다 이나 나 이란 란
거나 지만 어서 아서 면서 도록 려면 으려면 어야 아야 어도 아도 고 며
랑 이랑 한테 에게서 에도 에는 에나 엔 들 는데 은데 인데 는지 은지 인지 나서 하게 되 된 될 되어 되는""".split() + """
이다 다 한다 된다 하는 하고 하면 할 해 했다 하나 인가 인지 야 요 뭐야 뭐지 있나 있어 없나 되나 돼 되는지 하는지
해야 하나요 인가요 어떻게 하지 거야 건가 해줘 해줘야""".split(), key=len, reverse=True)
# 조사가 둘 겹친 말("출혈에나", "위협으로부터")에서 한 번 더 떼는 조사 (명사 끝 글자와 헷갈리지 않는 것만)
_PARTICLES2 = sorted("에 에서 에게 한테 으로 는 은 을 를 의 랑 이랑".split(), key=len, reverse=True)
# 조사처럼 보이는 글자로 끝나지만 통째로 한 낱말인 부사 ("바로" ≠ "바" + "로")
_NO_STRIP = set("바로 서로 새로 따로 주로 별로 대로 처음 다시 함께 같이".split())
_STOP = set("다음 같다 수 있다 있는 것 거 등 및 또는 그 이 저 때 경우 위해 대한 그리고 하는 한다 된다 해야 어떻게 무엇 뭐 뭐야 "
            "알려줘 말해줘 설명해줘 뭔가 뭐지 언제 왜 어디 얼마나 몇 하나 해도 돼 되나 좀 법 요령 방법 차이 기준 "
            "어디에 뭘로 뭐가 할때 때는 "
            # 구어 질문의 군말·질문 틀 (교범 문장에는 거의 안 나와 일치율만 깎는다)
            "뭘 꾹 잠깐 각각 정확히 이유 어떤 해 있어 있으면 하면 되 안 나 있 이제 그냥 혹시 마땅한 아무 것들 맞아 "
            "제대로 무조건 해줘 나서".split())
# 질문에 흔한 활용형 → 교범 쪽 어간 (형태소 분석기 대신 최소 사전)
CONJ = {"풀어": "풀", "올려": "올리", "감아": "감", "감은": "감", "감고": "감", "줘": "주", "써": "쓰", "발라": "바르",
        "바르는": "바르", "재는": "측정", "재": "측정", "만들어": "만들", "막아": "막", "보여": "보이", "볼": "보",
        "숨어": "은폐", "피해": "피", "써도": "쓰", "줘도": "주", "올려도": "올리", "풀어도": "풀"}

SYNONYMS = {
    "토니켓": "지혈대", "지혈띠": "지혈대", "cat": "C-A-T", "캣": "C-A-T",
    "묶는": "감는", "묶어": "감아", "매는": "감는", "푸는": "풀", "풀어도": "풀",
    "총소리": "총성", "총성": "섬광 음향", "사격소리": "섬광 음향",
    "ied": "급조폭발물", "사제폭탄": "급조폭발물", "폭탄": "폭발물", "uxo": "불발탄", "불발": "불발탄",
    "자동차폭탄": "차량 폭탄", "차폭탄": "차량 폭탄",
    "메디백": "의무후송", "medevac": "의무후송", "후송요청": "의무후송 요청",
    "무전": "무선", "무전기": "무선", "교신": "무선", "절차어": "절차용어", "프로워드": "절차용어",
    "살루트": "SALUTE", "salute": "SALUTE", "적정보고": "SALUTE 보고", "적보고": "SALUTE 보고",
    "위장크림": "위장 크림", "페이스페인트": "위장 크림", "얼굴": "피부 위장 크림",
    "엄폐물": "엄폐", "은폐물": "은폐", "숨는": "은폐", "숨기": "은폐",
    "거리재는": "거리 측정", "거리측정": "거리 측정",
    "밤": "야간", "밤에": "야간", "어두울": "야간", "총구": "섬광", "섬광": "섬광 음향법",
    "야간투시경": "야간투시장비", "nvg": "야간투시경", "열상": "열영상 TWS",
    "포로": "적 포로", "opsec": "작전보안", "보안": "작전보안",
    "충격": "쇼크", "기절": "쇼크", "출혈": "출혈 지혈", "환자": "부상자", "다친": "부상자",
    "어디": "위치", "어디에": "위치", "누가": "지휘자", "정해": "정한다",
    # 팀원 실제 질문에서 나온 구어 표현 (2026-10-10)
    "누르": "압박 눌러", "눌러": "압박", "같이": "함께", "짧": "간결", "판단": "징후 증상", "증상": "징후",
    "곳": "자리", "가야": "떠야", "떠나": "떠야",
}

INTENTS = [  # (패턴, 가중할 유형들)
    (re.compile(r"(어떻게|방법|절차|순서|하는\s?법|요령|단계)"), {UType.PROCEDURE: 1.6, UType.DECISION_RULE: 1.2}),
    (re.compile(r"(뭐|무엇|란\b|이란|정의|의미|뜻|차이)"), {UType.DEFINITION: 2.0}),
    (re.compile(r"(해도|되나|돼\?|괜찮|금지|안\s?되|하면\s?안|말아야)"),
     {UType.PROHIBITION: 1.8, UType.WARNING: 1.5, UType.CAUTION: 1.5, UType.DECISION_RULE: 1.3}),
    (re.compile(r"(언제|경우|때\b|상황)"), {UType.DECISION_RULE: 1.5, UType.CONDITION: 1.5}),
    (re.compile(r"(주의|경고|위험)"), {UType.WARNING: 1.6, UType.CAUTION: 1.6, UType.PROHIBITION: 1.3}),
]


def _drop_final_n(syl: str) -> str:
    """받침 ㄴ 제거: '린' → '리', '준' → '주' (올린다 → 올리, 준다 → 주)."""
    code = ord(syl) - 0xAC00
    if 0 <= code < 11172 and code % 28 == 4:
        return chr(ord(syl) - 4)
    return syl


# 이유 질문 → 까닭을 말하는 문장(…므로, …때문, …위험이 있다, …수 있다) 우선
RE_WHY = re.compile(r"(왜|이유|까닭|어째서)")
RE_REASON = re.compile(r"(므로|때문|위험이|수 있다|수 있고|키운다|막기 위해|않도록)")
RE_QUANTITY = re.compile(r"(얼마|몇|걸려|걸리|거리는|시간은|길이|폭|무게|미터|분\b|초\b)")


_PAST_VOWEL = {6: 20, 14: 13, 9: 8, 10: 11}      # ㅕ→ㅣ(조였→조이), ㅝ→ㅜ(멈췄→멈추), ㅘ→ㅗ, ㅙ→ㅚ(됐→되)


def _unpast(word: str) -> str:
    """과거형 받침 ㅆ에서 자르고 어간으로: 감았는데 → 감, 멈췄어 → 멈추, 조였는지 → 조이, 했다 → 하."""
    for i, c in enumerate(word):
        code = ord(c) - 0xAC00
        if not (0 <= code < 11172) or code % 28 != 20 or len(word) < 2:
            continue
        cho, jung = code // 588, code % 588 // 28
        if cho == 11 and jung == 20:                     # 있: 과거형이 아니라 '있다'
            continue
        if cho == 11 and jung in (0, 4):                 # 았·었: 통째로 어미
            if i == 0:
                continue
            return word[:i]
        if cho == 18 and jung == 1:                      # 했 → 하
            jung = 0
        jung = _PAST_VOWEL.get(jung, jung)
        return word[:i] + chr(0xAC00 + cho * 588 + jung * 28)
    return word


def _strip(word: str) -> str:
    if word in _NO_STRIP:
        return word
    w = _unpast(word)
    if w != word:
        s = _strip1(w) if len(w) >= 3 else w            # 절단됐는데 → 절단되 → 절단
    else:
        s = _strip1(word)
        if s != word and len(s) >= 3:
            s = next((s[: -len(suf)] for suf in _PARTICLES2 if len(s) - len(suf) >= 2 and s.endswith(suf)), s)
    # 명사+하다 동사는 명사만 (사용해·사용하·사용 → 사용, 확인해 → 확인)
    if len(s) >= 3 and s[-1] in "하해":
        s = s[:-1]
    return s


def _strip1(word: str) -> str:
    # 동사 종결 'ㄴ다/는다': 감는다 → 감, 올린다 → 올리, 한다 → 하
    if len(word) >= 3 and word.endswith("는다"):
        return word[:-2]
    if len(word) >= 2 and word.endswith("다") and _drop_final_n(word[-2]) != word[-2]:
        return word[:-2] + _drop_final_n(word[-2])
    for suf in _SUFFIXES:
        if len(word) > len(suf) and word.endswith(suf):     # 한 글자 어간 허용 (폭은 → 폭)
            return word[: -len(suf)]
    return word


def tokens(text: str) -> list[str]:
    text = text.lower()
    words = re.findall(r"\d+(?:\.\d+)?|[a-z][a-z\-]*|[가-힣]+", text)   # "400m" → "400", "m"
    out = []
    for w in words:
        if w in _STOP:
            continue
        w = CONJ.get(w, w)
        s = _strip(w)
        s = CONJ.get(s, s)
        if s in _STOP or len(s) < 1:
            continue
        out.append("w:" + s)
        if len(s) == 1 and s != w:
            out.append("o:" + w)      # 한 글자로 줄었으면 원형도 약하게 (사이 → 사 같은 오절단 대비)
        if re.match(r"[가-힣]", s) and len(s) >= 2:
            out += ["b:" + s[i:i + 2] for i in range(len(s) - 1)]
    return out


def expand(query: str) -> str:
    """단어 단위 동의어 확장 (부분 문자열 금지: '사거리'가 '거리'로 확장되면 안 됨)."""
    words = re.findall(r"[a-z0-9\-]+|[가-힣]+", query.lower())
    joined = "".join(words)
    extra = []
    for k, v in SYNONYMS.items():
        if any(w == k or _strip(w) == k for w in words) or (len(k) >= 4 and k in joined):
            extra.append(v)
    return query + " " + " ".join(extra) if extra else query


def intent_boosts(query: str) -> dict[UType, float]:
    boosts: dict[UType, float] = {}
    for rx, b in INTENTS:
        if rx.search(query):
            for t, w in b.items():
                boosts[t] = max(boosts.get(t, 1.0), w)
    return boosts


def word_syns(words: list[str]) -> list[list[str]]:
    """질문어마다 동의어 어간 목록 (질문당 한 번만 계산해 coverage에 넘긴다)."""
    return [[t for t in tokens(expand(w)) if t.startswith("w:")] for w in words]


def coverage(words: list[str], doc: set[str], syns: list[list[str]] | None = None) -> float:
    """질문 내용어 중 문단에 나온 비율. 단어가 통째로 없어도 2글자 조각이 절반 이상 맞으면 반만 인정.
    질문 끝의 서술어(예: '돼야 해', '정해')는 활용형이 제각각이라 가중치 절반."""
    if not words:
        return 0.0
    got = 0.0
    weights = [1.0] * len(words)
    if len(words) >= 3:
        weights[-1] = 0.5
    total = sum(weights)
    syns = syns if syns is not None else word_syns(words)
    for w, wt, syn in zip(words, weights, syns):
        if "w:" + w in doc or any(t in doc for t in syn):
            got += wt
        else:
            bg = [w[i:i + 2] for i in range(len(w) - 1)] if len(w) >= 2 else []
            if bg and sum(("b:" + b) in doc for b in bg) / len(bg) >= 0.5:
                got += 0.5 * wt
    return got / total


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.4, b: float = 0.6):
        self.k1, self.b = k1, b
        self.tf = [Counter(d) for d in docs]
        self.len = [len(d) for d in docs]
        self.avg = sum(self.len) / max(1, len(docs))
        df = Counter(t for d in self.tf for t in d)
        n = len(docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def score(self, q: list[str], i: int) -> float:
        tf, L = self.tf[i], self.len[i]
        s = 0.0
        for t in q:
            if t in tf:
                f = tf[t]
                w = 1.0 if t.startswith("w:") else 0.45      # b: 2글자 조각, o: 원형
                s += w * self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * L / self.avg))
        return s


@dataclass
class Hit:
    para: Paragraph
    score: float
    coverage: float                      # 질문 내용어 중 문단(제목 포함)에 나온 비율
    units: list[tuple[Unit, float]]      # 문단 안 단위 점수


class ManualIndex:
    def __init__(self, paras: list[Paragraph], units: list[Unit], rels: list[Relation],
                 questions: dict[str, list[str]] | None = None):
        # questions: 문단별 예상 질문 (LLM 사전 생성, 선택). 검색 문서에만 더하고 답변 문장으로는 쓰지 않는다
        self.questions = questions or {}
        # 글자 없는 그림·표(원문이 이미지)는 검색 대상에서 뺀다 (제목만 맞고 내용이 없음)
        self.paras = [p for p in paras if not (p.kind in (Kind.FIGURE, Kind.TABLE) and not p.text)]
        self.by_id = {p.id: p for p in paras}
        self.all_units = units
        self.units_of: dict[str, list[Unit]] = defaultdict(list)
        for u in units:
            self.units_of[u.para_id].append(u)
        self.rels = rels
        self.applies: dict[str, list[str]] = defaultdict(list)     # 문단 → 적용 경고 상자·참고
        for r in rels:
            if r.type == RType.APPLIES_TO:
                self.applies[r.dst].append(r.src)
        self.docs = [self._doc_tokens(p) for p in self.paras]
        self.bm = BM25(self.docs)
        self.unit_bm = {p.id: BM25([tokens(u.text) for u in self.units_of[p.id]] or [[]]) for p in self.paras}

    def _doc_tokens(self, p: Paragraph) -> list[str]:
        head = " ".join(p.headings) + " " + p.label
        return (tokens(p.text) + tokens(head) * 2 + tokens(p.section)
                + tokens(" ".join(self.questions.get(p.id, []))))

    def search(self, query: str, k: int = 5) -> list[Hit]:
        q = tokens(expand(query))
        content_words = [t[2:] for t in tokens(query) if t.startswith("w:")]
        boosts = intent_boosts(query)
        quantity = bool(RE_QUANTITY.search(query))      # 수량 질문 → 숫자가 든 문장 우선
        why = bool(RE_WHY.search(query))
        syns = word_syns(content_words)
        hits = []
        for i, p in enumerate(self.paras):
            s = self.bm.score(q, i)
            if s <= 0:
                continue
            us = self.units_of[p.id]
            ubm = self.unit_bm[p.id]
            uscores = [(u, ubm.score(q, j) * boosts.get(u.type, 1.0)
                        * (1.5 if quantity and re.search(r"\d", u.text) else 1.0)
                        * (1.5 if why and RE_REASON.search(u.text) else 1.0)) for j, u in enumerate(us)]
            # 질문 의도에 맞는 유형의 단위가 잘 맞으면 문단 점수를 올린다
            best_u = max((sc for _, sc in uscores), default=0.0)
            if boosts and any(boosts.get(u.type, 1) > 1 and sc > 0 for u, sc in uscores):
                s *= 1.15
            s += 0.6 * best_u            # 질문에 딱 맞는 한 문장(표의 한 행 등)이 있으면 크게 반영
            if p.kind == Kind.BOX:
                s *= 0.9                 # 상자는 단독 답보다 관련 문단에 붙여 보여준다
            doc = set(self.docs[i])
            cov = coverage(content_words, doc, syns)
            hits.append(Hit(p, s, cov, uscores))
        hits.sort(key=lambda h: -h.score)
        return hits[:k]
