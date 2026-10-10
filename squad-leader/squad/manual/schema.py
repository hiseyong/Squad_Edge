"""교범 지식 모델: 원본 문단 → 지식 단위 → 지식 관계의 3계층.

- Paragraph: 교범의 한 요소(번호 문단, 도입문, 경고 상자, 표, 그림 설명, 참고). 원문 그대로 + 출처.
- Unit: 문단에서 뽑은 개별 규칙·사실·절차 단계 등. 원문 문장 그대로(재서술하지 않음) + 유형·조건.
- Relation: 문단↔단위, 단위↔단위, 문단↔문단 연결(포함, 예외, 다음 단계, 적용 경고, 참조).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path


class Kind(str, Enum):        # 문단 종류
    PARA = "para"             # 번호 문단 (3-40.)
    INTRO = "intro"           # 장·절 도입문 (번호 없음)
    BOX = "box"               # 경고·주의·위험 상자
    NOTE = "note"             # 참고:
    TABLE = "table"
    FIGURE = "figure"


class UType(str, Enum):       # 지식 유형
    DEFINITION = "DEFINITION"
    FACT = "FACT"
    CONDITION = "CONDITION"
    PROCEDURE = "PROCEDURE"           # 절차 단계 (order 있음)
    DECISION_RULE = "DECISION_RULE"   # "~하면 ~한다"
    WARNING = "WARNING"
    PROHIBITION = "PROHIBITION"
    CAUTION = "CAUTION"
    EXCEPTION = "EXCEPTION"
    REFERENCE = "REFERENCE"


class RType(str, Enum):
    CONTAINS = "CONTAINS"             # 문단 → 단위
    NEXT_STEP = "NEXT_STEP"           # 절차 단계 → 다음 단계
    EXCEPTION_OF = "EXCEPTION_OF"     # 예외 단위 → 대상 단위
    APPLIES_TO = "APPLIES_TO"         # 경고 상자 → 관련 문단
    REFERS_TO = "REFERS_TO"           # 문단 → 그림·표·장·문단
    CONTINUES = "CONTINUES"           # 쪽을 넘어 이어지는 문단 조각


@dataclass
class Source:
    doc: str                  # "TC 3-21.75"
    page_label: str           # 교범 쪽번호 "3-21"
    pdf_page: int             # PDF 쪽 (1부터)


@dataclass
class Paragraph:
    id: str                   # "3-40", "3-40.box1", "5.intro", "fig3-34"
    kind: Kind
    chapter: str              # "제3장 전투 부상자 처치 및 예방의학"
    section: str              # "제1절 엄폐" (없으면 "")
    headings: list[str]       # 장 아래 제목 경로 ["지혈대", "임시 지혈대"]
    text: str                 # 원문 (줄바꿈 = 목록 항목 경계)
    source: Source
    label: str = ""           # 상자 종류(경고/주의/위험), 표·그림 제목
    order: int = 0            # 문서 내 순서


@dataclass
class Unit:
    id: str                   # "3-40#2"
    para_id: str
    type: UType
    text: str                 # 원문 문장 그대로
    condition: str = ""       # DECISION_RULE/CONDITION: 조건 부분
    action: str = ""          # 조건 뒤 행동 부분
    order: int = 0            # PROCEDURE 단계 번호, 그 외 문단 내 순번
    severity: str = ""        # 상자 유래: danger / warning / caution
    refs: list[str] = field(default_factory=list)


@dataclass
class Relation:
    src: str
    type: RType
    dst: str
    note: str = ""


def _enc(o):
    if isinstance(o, Enum):
        return o.value
    raise TypeError(o)


def save_jsonl(path: Path, rows) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(asdict(r), ensure_ascii=False, default=_enc) + "\n")


def load_kb(dirpath: Path) -> tuple[list[Paragraph], list[Unit], list[Relation]]:
    def rows(name):
        with open(dirpath / name, encoding="utf-8") as f:
            return [json.loads(l) for l in f if l.strip()]
    paras = []
    for d in rows("paragraphs.jsonl"):
        d["kind"] = Kind(d["kind"])
        d["source"] = Source(**d["source"])
        paras.append(Paragraph(**d))
    units = []
    for d in rows("units.jsonl"):
        d["type"] = UType(d["type"])
        units.append(Unit(**d))
    rels = []
    for d in rows("relations.jsonl"):
        d["type"] = RType(d["type"])
        rels.append(Relation(**d))
    return paras, units, rels
