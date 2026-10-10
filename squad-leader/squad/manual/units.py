"""원본 문단 → 지식 단위(Unit) + 지식 관계(Relation). 전부 규칙 기반, 원문 문장을 바꾸지 않는다.

문장 분리: "다." "다?" 등 종결 + 목록 항목(•, --, 1.) 경계.
유형 판별 우선순위 (먼저 맞는 것):
  상자 유래(위험/경고/주의) → 절차 단계(번호 목록) → 예외(다만/그러나…) → 정의(~란 …이다)
  → 금지(…않는다/안 된다, 조건 없는 것) → 판단 규칙(~하면/경우/때 … 한다) → 참조(…참조한다/다룬다) → 사실
"""
from __future__ import annotations

import re

from .schema import Kind, Paragraph, Relation, RType, Unit, UType

RE_SENT_END = re.compile(r"(?<=[다요음함됨]\.)\s+|(?<=\)\.)\s+|(?<=[?!])\s+")
RE_ITEM = re.compile(r"^(•|--|\d+\.)\s*")
RE_EXCEPTION = re.compile(r"^(다만|단,|그러나|하지만|그렇지만|그래도|예외)")
RE_DEFINITION = re.compile(r"^(.{1,40}?)(이)?란\s.+(이다|말한다|것이다|과정이다|장치다|띠다)\.?$|"
                           r"^(.{1,40}?)(은|는)\s.+(을|를)\s?(말한다|뜻한다|의미한다)\.?$")
# "~않게 한다"(미끄러지지 않게 한다 = 방지)는 금지가 아니라 제외
RE_PROHIBIT = re.compile(r"(지 않는다|안 된다|말아야 한다|금지|쓰지 않는다|주지 않는다|"
                         r"두지 않는다|감지 않는다|하지 않는다|피한다|해서는 안)[.)]*$")
# "면": 지면·정면·표면 같은 명사 제외
RE_COND = re.compile(r"(으면|하면|이면|라면|없으면|있으면|않으면|아니면|(?<![지측정표후전단화장방국이])면\s|"
                     r"경우(에는|엔)?|때(는|에는)?\s|동안|전에|후에|뒤에)")
# 상태·지각 동사의 부정은 서술이지 금지가 아니다 ("빨강은 거의 보이지 않는다")
RE_STATIVE = re.compile(r"(보이|들리|알|맞|같|크|작|많|적|쉽|어렵|느껴지|나타나|생기|되)지 않는다")
RE_PROHIBIT_ANY = re.compile(r"(절대|결코|금지|하지 마|지 말고|지 말 것)")
RE_REF_SENT = re.compile(r"(참조한다|다룬다|참고한다)[.)]*$")
RE_REFS = [(re.compile(r"그림\s?(\d+-\d+)"), "그림{}"), (re.compile(r"표\s?(\d+-\d+)"), "표{}"),
           (re.compile(r"제(\d+)장"), "제{}장"), (re.compile(r"(?<![\d.-])(\d{1,2}-\d{1,2})(?=\s?쪽)"), "쪽{}")]
SEVERITY = {"위험": "danger", "경고": "warning", "주의": "caution"}


def split_sentences(text: str) -> list[tuple[str, str]]:
    """(문장, 목록 표지) 목록. 목록 표지: "", "•", "--", "1." 등."""
    out = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        m = RE_ITEM.match(line)
        mark = m.group(1) if m else ""
        body = line[m.end():] if m else line
        parts = [p.strip() for p in RE_SENT_END.split(body) if p.strip()]
        for i, p in enumerate(parts):
            out.append((p, mark if i == 0 else ""))
    return out


def refs_of(text: str) -> list[str]:
    found = []
    for rx, fmt in RE_REFS:
        for m in rx.finditer(text):
            r = fmt.format(m.group(1))
            if r not in found:
                found.append(r)
    return found


def _split_condition(s: str) -> tuple[str, str]:
    """'A하면 B한다' → ('A하면', 'B한다'). 첫 조건 표지 기준."""
    m = RE_COND.search(s)
    if not m:
        return "", ""
    cut = m.end()
    return s[:cut].strip(" ,"), s[cut:].strip(" ,")


def classify(sent: str, mark: str, para: Paragraph) -> tuple[UType, str, str, str]:
    """→ (유형, 조건, 행동, 심각도)"""
    if para.kind == Kind.BOX:
        sev = SEVERITY.get(para.label, "warning")
        return (UType.CAUTION if sev == "caution" else UType.WARNING), "", "", sev
    if mark and re.match(r"\d+\.", mark):
        return UType.PROCEDURE, "", "", ""
    if RE_EXCEPTION.match(sent):
        return UType.EXCEPTION, "", "", ""
    core = re.sub(r"\([^()]*\)(?=\.?$)", "", sent).strip()   # 끝의 "(그림 5-6)" 제거 후 판별
    if RE_DEFINITION.match(core):
        return UType.DEFINITION, "", "", ""
    cond, act = _split_condition(sent)
    descriptive = RE_STATIVE.search(sent) and not RE_PROHIBIT_ANY.search(sent)
    if (RE_PROHIBIT.search(sent) or RE_PROHIBIT_ANY.search(sent)) and not descriptive:
        # 조건이 붙은 금지는 판단 규칙으로 (조건을 잃지 않게)
        return (UType.DECISION_RULE, cond, act, "") if cond else (UType.PROHIBITION, "", "", "")
    if cond and len(act) > 3:
        return UType.DECISION_RULE, cond, act, ""
    if RE_REF_SENT.search(sent):
        return UType.REFERENCE, "", "", ""
    return UType.FACT, "", "", ""


def build_units(paras: list[Paragraph]) -> tuple[list[Unit], list[Relation]]:
    units: list[Unit] = []
    rels: list[Relation] = []
    by_order = sorted(paras, key=lambda p: p.order)
    numbered = [p for p in by_order if p.kind == Kind.PARA]

    for p in by_order:
        if p.kind == Kind.FIGURE and not p.text:
            sents = [(p.label, "")]
        elif p.kind in (Kind.TABLE, Kind.FIGURE):
            sents = [(p.label, "")] + [(l.strip(), "") for l in p.text.split("\n") if l.strip()]
        else:
            sents = split_sentences(p.text)
        prev: Unit | None = None
        step_prev: Unit | None = None
        step_no = 0
        in_step = False
        for i, (s, mark) in enumerate(sents):
            if mark:
                in_step = bool(re.match(r"\d+\.", mark))
            if p.kind in (Kind.TABLE, Kind.FIGURE):
                t, cond, act, sev = UType.REFERENCE if i == 0 else UType.FACT, "", "", ""
            elif in_step and not mark and p.kind != Kind.BOX:
                # 번호 항목 안의 둘째 문장부터: 같은 단계에 속한다 (단계 번호 유지)
                t, cond, act, sev = UType.PROCEDURE, *_split_condition(s), ""
                u = Unit(id=f"{p.id}#{i + 1}", para_id=p.id, type=t, text=s, condition=cond, action=act,
                         order=step_no, refs=refs_of(s))
                units.append(u)
                rels.append(Relation(p.id, RType.CONTAINS, u.id))
                for r in u.refs:
                    rels.append(Relation(p.id, RType.REFERS_TO, r, note=u.id))
                prev = u
                continue
            else:
                t, cond, act, sev = classify(s, mark, p)
            order = i + 1
            if t == UType.PROCEDURE:
                step_no = int(re.match(r"(\d+)", mark).group(1)) if mark else step_no + 1
                order = step_no
            u = Unit(id=f"{p.id}#{i + 1}", para_id=p.id, type=t, text=s, condition=cond, action=act,
                     order=order, severity=sev, refs=refs_of(s))
            units.append(u)
            rels.append(Relation(p.id, RType.CONTAINS, u.id))
            if t == UType.PROCEDURE:
                if step_prev is not None:
                    rels.append(Relation(step_prev.id, RType.NEXT_STEP, u.id))
                step_prev = u
            if t == UType.EXCEPTION and prev is not None:
                rels.append(Relation(u.id, RType.EXCEPTION_OF, prev.id))
            for r in u.refs:
                rels.append(Relation(p.id, RType.REFERS_TO, r, note=u.id))
            prev = u

        # 경고 상자·참고는 앞뒤 번호 문단에 적용 (교범은 상자를 관련 문단 바로 앞이나 뒤에 둔다)
        if p.kind in (Kind.BOX, Kind.NOTE):
            before = [q for q in numbered if q.order < p.order]
            after = [q for q in numbered if q.order > p.order]
            same_head = lambda q: q.headings[:1] == p.headings[:1] and q.chapter == p.chapter
            if before and same_head(before[-1]):
                rels.append(Relation(p.id, RType.APPLIES_TO, before[-1].id, note="앞 문단"))
            if after and same_head(after[0]) and p.kind == Kind.BOX:
                rels.append(Relation(p.id, RType.APPLIES_TO, after[0].id, note="뒤 문단"))
    return units, rels
