"""근거 기반 답변 조립 (결정론적). 원문 문장만 쓰고, 출처를 붙이고, 근거가 약하면 보류한다.

답변 구성
  1. 핵심: 가장 맞는 문단에서 질문과 맞는 단위들 (원문 순서 유지)
     - 절차 단계가 하나라도 맞으면 그 절차 전체를 순서대로
     - 판단 규칙은 조건과 함께
  2. 반드시 함께: 그 문단의 금지·예외 문장 + 그 문단에 적용되는 경고·주의·위험 상자 (조건·경고 누락 방지)
  3. 출처: TC 3-21.75 문단 번호, 교범 쪽, PDF 쪽
판정
  - 보류: 최고 점수 낮음, 또는 질문 내용어가 거의 안 맞음
  - 되묻기: 1·2위가 비슷한데 서로 다른 제목
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .schema import Kind, Paragraph, Unit, UType
from .search import RE_REASON, RE_WHY, Hit, ManualIndex, tokens

MIN_SCORE = 6.0
MIN_COVERAGE = 0.5
AMBIGUOUS_RATIO = 0.92
MUST_INCLUDE = {UType.PROHIBITION, UType.EXCEPTION, UType.WARNING, UType.CAUTION}


@dataclass
class Answer:
    status: str                              # "answer" | "abstain" | "clarify"
    query: str
    main: Paragraph | None = None
    lines: list[tuple[str, str]] = field(default_factory=list)      # (유형 표지, 원문)
    cautions: list[tuple[str, str]] = field(default_factory=list)   # (표지, 원문)
    citations: list[str] = field(default_factory=list)
    options: list[str] = field(default_factory=list)                # 되묻기·보류 시 후보
    score: float = 0.0
    coverage: float = 0.0
    brief: list[tuple[str, str]] = field(default_factory=list)      # 간결 답변 (낭독용 핵심 1~2개)
    brief_caution: tuple[str, str] | None = None                    # 낭독할 경고 1건

    def render(self) -> str:
        if self.status == "abstain":
            s = "교범에서 근거를 찾지 못했습니다. 답변을 보류합니다."
            return s + ("\n관련 있을 수 있는 항목: " + ", ".join(self.options) if self.options else "")
        if self.status == "clarify":
            return "어느 내용을 찾으시나요?\n" + "\n".join(f"  {i + 1}. {o}" for i, o in enumerate(self.options))
        out = [f"[{' > '.join(self._path())}]"]
        out += [f"- {t}" if not tag else f"- ({tag}) {t}" for tag, t in self.lines]
        if self.cautions:
            out.append("※ 함께 지켜야 할 사항")
            out += [f"- [{tag}] {t}" for tag, t in self.cautions]
        out.append("근거: " + "; ".join(self.citations))
        return "\n".join(out)

    def spoken(self) -> str:
        """헤드셋 낭독용 간결 답변: 핵심 1~2개 + 가장 관련된 경고 1건 + 근거 문단."""
        if self.status != "answer":
            return self.render().split("\n")[0]
        lines = self.brief or self.lines[:2]
        parts = [_speakable(t) for _, t in lines]
        if self.brief_caution:
            tag, t = self.brief_caution
            parts.append(f"{tag}. {_speakable(t)}")
            more = len(self.cautions) - 1
            if more > 0:
                parts.append(f"주의사항 {more}건 더 있음.")
        parts.append(f"근거, {self.main.id}.")
        return " ".join(parts)

    def render_brief(self) -> str:
        if self.status != "answer":
            return self.render()
        out = [f"- {t}" for _, t in (self.brief or self.lines[:2])]
        if self.brief_caution:
            out.append(f"※ [{self.brief_caution[0]}] {self.brief_caution[1]}"
                       + (f" (외 {len(self.cautions) - 1}건)" if len(self.cautions) > 1 else ""))
        out.append("근거: " + self.citations[0])
        return "\n".join(out)

    def _path(self) -> list[str]:
        p = self.main
        return [x for x in (p.chapter, p.section, *p.headings) if x]


def _speakable(t: str) -> str:
    """낭독 시 괄호 참조·목록 번호 제거: '(그림 3-34의 1)', '1. '"""
    t = re.sub(r"\((그림|표)\s?\d+-\d+[^)]*\)", "", t)
    t = re.sub(r"^\d+\.\s*", "", t)
    return re.sub(r"\s+", " ", t).strip()


def _overlap(q_tokens: set[str], text: str) -> int:
    return len(q_tokens & set(tokens(text)))


def _brief(a: Answer, index: ManualIndex, top: Hit, query: str, reranker=None) -> None:
    """간결 답변 선택: 질문 의도 가중된 단위 점수(+재순위 확률) 1위 + 비슷한 2위, 절차면 단계 전체."""
    scored = [(u, s) for u, s in top.units if u.type != UType.REFERENCE]
    if reranker is not None and scored:
        mx = max(s for _, s in scored) or 1.0
        probs = reranker.scores(query, [u.text for u, _ in scored])
        scored = [(u, 0.5 * s / mx + 0.5 * float(p)) for (u, s), p in zip(scored, probs)]
    scored = sorted(((u, s) for u, s in scored if s > 0), key=lambda x: -x[1])
    if not scored:
        a.brief = a.lines[:2]
    else:
        first, s1 = scored[0]
        if first.type == UType.PROCEDURE:
            steps = sorted((u for u in index.units_of[top.para.id] if u.type == UType.PROCEDURE),
                           key=lambda u: int(u.id.split("#")[1]))
            a.brief = [(f"절차 {u.order}", u.text) for u in steps]
        else:
            ratio = 0.8 if reranker is not None else 0.6
            pick = [first] + [u for u, s in scored[1:3] if s >= ratio * s1 and u.type != UType.PROCEDURE][:1]
            # 이유 질문인데 까닭 문장이 없으면, 질문과 조금이라도 맞는 까닭 문장 하나를 덧붙인다
            if RE_WHY.search(query) and not any(RE_REASON.search(u.text) for u in pick):
                why = next((u for u, _ in scored if RE_REASON.search(u.text) and u not in pick), None)
                if why is not None:
                    pick.append(why)
            pick.sort(key=lambda u: int(u.id.split("#")[1]))
            a.brief = [(TAG.get(u.type, ""), u.text) for u in pick]
            # "…은 다음과 같다." 로 끝나면 답은 뒤따르는 목록에 있다 → 목록 항목을 이어 읽는다
            for i, (tag, t) in enumerate(a.brief):
                if RE_LIST_LEAD.search(t):
                    a.brief[i] = (tag, t + " " + _list_after(index, pick[i]))
                    break
    if a.cautions:
        q = set(tokens(query))
        best = max(a.cautions, key=lambda c: (_overlap(q, c[1]), c[0] == "위험"))
        if best[1] not in {t for _, t in a.brief}:
            a.brief_caution = best


RE_LIST_LEAD = re.compile(r"(다음과 같다|다음이 있다|다음과 같이 한다|있는지 살핀다|다음을 지킨다)[.:]?$")
LIST_SPEAK_MAX = 6


def _list_after(index: ManualIndex, lead: Unit) -> str:
    """목록 머리 문장 뒤의 짧은 항목들을 '가, 나, 다 등' 으로 (낭독이 길어지지 않게 최대 LIST_SPEAK_MAX개)."""
    units = index.units_of[lead.para_id]
    k = next(i for i, u in enumerate(units) if u.id == lead.id)
    items = []
    for u in units[k + 1:]:
        if len(u.text) > 60 or RE_LIST_LEAD.search(u.text):
            break
        items.append(re.sub(r"[.。]$", "", _speakable(u.text)))
    more = len(items) > LIST_SPEAK_MAX
    return ", ".join(items[:LIST_SPEAK_MAX]) + (" 등." if more else ".") if items else ""


def _cite(p: Paragraph) -> str:
    return f"{p.source.doc} {p.id if p.kind == Kind.PARA else p.id + (' ' + p.label if p.label else '')} " \
           f"(교범 {p.source.page_label}쪽, PDF {p.source.pdf_page}쪽)"


TAG = {UType.PROCEDURE: "절차", UType.DECISION_RULE: "조건", UType.PROHIBITION: "금지", UType.EXCEPTION: "예외",
       UType.DEFINITION: "정의", UType.WARNING: "경고", UType.CAUTION: "주의"}
BOX_TAG = {"danger": "위험", "warning": "경고", "caution": "주의"}


RE_COMPARE = re.compile(r"(차이|다른\s?점|비교|구별|vs|뭐가\s?(다른|다르|달라)|어떻게\s?(다른|다르|달라)|각각)")


def compare_answer(index: ManualIndex, query: str) -> Answer | None:
    """'A와 B 차이' → A, B 각각의 정의 단위를 나란히. 둘 다 정의가 있을 때만."""
    words = [w for w in re.findall(r"[가-힣]+", query) if not RE_COMPARE.search(w)]
    terms = []
    for w in words:
        for suf in ("와", "과", "랑", "이랑", "하고", "의", "는", "은", "가", "이"):
            if w.endswith(suf) and len(w) > len(suf):
                w = w[: -len(suf)]
                break
        if w not in terms and len(w) >= 2:
            terms.append(w)
    defs = []
    for t in terms[:3]:
        u = next((u for u in index.all_units if u.type == UType.DEFINITION
                  and re.match(rf"^{re.escape(t)}(이)?(란|은|는)\s", u.text)), None)
        if u is None:   # 정의 문장이 없으면 그 이름의 절·제목 첫 문장(도입문)을 정의로 쓴다
            p = next((p for p in sorted(index.by_id.values(), key=lambda p: p.order)
                      if p.kind in (Kind.INTRO, Kind.PARA)
                      and (re.search(rf"제\d+절 {re.escape(t)}$", p.section) or (p.headings and p.headings[-1] == t))), None)
            u = index.units_of[p.id][0] if p and index.units_of[p.id] else None
        if u is not None:
            defs.append((t, u))
    if len(defs) < 2:
        return None
    a = Answer("answer", query, main=index.by_id[defs[0][1].para_id], score=99, coverage=1.0)
    for t, u in defs:
        a.lines.append((f"정의: {t}", u.text))
        p = index.by_id[u.para_id]
        nxt = [x for x in index.units_of[p.id] if int(x.id.split("#")[1]) == int(u.id.split("#")[1]) + 1]
        if nxt and nxt[0].type in (UType.FACT, UType.PROHIBITION):      # 정의 바로 뒤 보충 문장
            a.lines.append(("", nxt[0].text))
        a.citations.append(_cite(p))
    a.brief = [(t, x) for t, x in a.lines if t.startswith("정의")]
    return a


def _rerank_hits(hits: list[Hit], query: str, reranker) -> list[Hit]:
    """상위 문단 재순위: BM25(최고점 대비) 50% + 교차 인코더 확률 50%."""
    cands = [h for h in hits if h.para.kind != Kind.BOX]
    if len(cands) < 2:
        return hits
    texts = [" ".join(h.para.headings + [h.para.label]) + " " + h.para.text[:300] for h in cands]
    probs = reranker.scores(query, texts)
    mx = max(h.score for h in cands)
    order = sorted(zip(cands, probs), key=lambda x: -(0.5 * x[0].score / mx + 0.5 * float(x[1])))
    return [h for h, _ in order] + [h for h in hits if h.para.kind == Kind.BOX]


def answer(index: ManualIndex, query: str, reranker=None) -> Answer:
    if RE_COMPARE.search(query) and (cmp := compare_answer(index, query)):
        return cmp
    hits = index.search(query, k=5)
    if not hits:
        return Answer("abstain", query)
    gate = hits[0]                      # 보류 판정은 BM25 1위 기준 그대로 (재순위가 근거 없는 답을 만들지 않게)
    if reranker is not None and gate.score >= MIN_SCORE and gate.coverage >= MIN_COVERAGE:
        hits = _rerank_hits(hits, query, reranker)
    top = hits[0]
    # 상자·참고가 1위면 그 상자가 적용되는 본문 문단을 주 답으로 (상자는 주의사항으로 붙는다)
    if top.para.kind in (Kind.BOX, Kind.NOTE):
        targets = [pid for pid, srcs in index.applies.items() if top.para.id in srcs]
        if targets:
            tgt = index.by_id[sorted(targets, key=lambda x: index.by_id[x].order)[0]]
            found = next((h for h in hits if h.para.id == tgt.id), None)
            if found is None:   # 대상 문단이 상위에 없으면 그 문단 기준으로 다시 채점
                found = next((h for h in index.search(query, k=len(index.paras)) if h.para.id == tgt.id), None)
            if found is not None:
                top = Hit(tgt, max(found.score, top.score), max(found.coverage, top.coverage), found.units)
    opts = [_option(h) for h in hits[:3]]
    if gate.score < MIN_SCORE or gate.coverage < MIN_COVERAGE:
        return Answer("abstain", query, options=opts if top.score >= MIN_SCORE / 2 else [],
                      score=top.score, coverage=top.coverage)
    second = None if reranker is not None else next(
        (h for h in hits if h.para.id != top.para.id and h.para.kind != Kind.BOX), None)
    # 되묻기 (재순위를 쓰면 재순위가 대신 판단): 점수가 비슷하고, 질문어 일치율도 같고, 다른 장 또는 다른 큰 제목일 때만
    if (second and second.score >= AMBIGUOUS_RATIO * top.score and second.coverage >= top.coverage
            and (second.para.chapter != top.para.chapter or second.para.section != top.para.section)
            and second.para.id not in index.applies.get(top.para.id, [])
            and top.para.id not in index.applies.get(second.para.id, [])):
        return Answer("clarify", query, options=[_option(top), _option(second)], score=top.score,
                      coverage=top.coverage)

    a = Answer("answer", query, main=top.para, score=top.score, coverage=top.coverage)
    units = index.units_of[top.para.id]
    scored = dict((u.id, s) for u, s in top.units)
    best = max(scored.values(), default=0)
    chosen: list[Unit] = []
    if top.para.kind in (Kind.TABLE, Kind.FIGURE) or len(units) <= 4 or best == 0:
        chosen = list(units)                       # 짧은 문단·표는 통째로
    else:
        cut = 0.35 * best
        chosen = [u for u in units if scored.get(u.id, 0) >= cut]
        if any(u.type == UType.PROCEDURE for u in chosen):          # 절차는 전체 단계를 순서대로
            chosen += [u for u in units if u.type == UType.PROCEDURE and u not in chosen]
        # 정의·첫 문장은 맥락으로 유지
        if units[0] not in chosen and units[0].type in (UType.DEFINITION, UType.FACT):
            chosen.insert(0, units[0])
    chosen.sort(key=lambda u: int(u.id.split("#")[1]))
    for u in chosen:
        tag = TAG.get(u.type, "")
        if u.type == UType.PROCEDURE:
            tag = f"절차 {u.order}"
        a.lines.append((tag, u.text))
    # 반드시 함께: 같은 문단의 금지·예외·경고 중 빠진 것 + 적용 상자
    for u in units:
        if u.type in MUST_INCLUDE and u not in chosen:
            a.cautions.append((TAG[u.type], u.text))
    for box_id in index.applies.get(top.para.id, []):
        box = index.by_id[box_id]
        tag = BOX_TAG.get({"위험": "danger", "경고": "warning", "주의": "caution"}.get(box.label, ""), "참고")
        for line in box.text.split("\n"):
            if line.strip():
                a.cautions.append((tag if box.kind == Kind.BOX else "참고", line.strip()))
    a.citations = [_cite(top.para)] + [_cite(index.by_id[b]) for b in index.applies.get(top.para.id, [])]
    _brief(a, index, top, query, reranker)
    return a


def _option(h: Hit) -> str:
    p = h.para
    title = " > ".join([x for x in (*p.headings[-2:],) if x]) or p.section or p.chapter
    return f"{title} ({p.id})"
