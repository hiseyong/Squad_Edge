"""분대장 보고 발화 → 보고 칸 (NLU). 규칙과 LLM(미세조정)이 같은 출력 형식을 쓴다.

출력 (짧은 키 JSON, 약 30토큰):
  {"a": [활동 코드], "c": [조치 코드], "r": [요청 코드], "n": 적 수|null,
   "w": [부상 병사 번호], "wc": 번호 없는 부상자 수|null, "j": [판단 문장]}
코드표는 sq-rpt/0.1 §5.2 (sqrpt.py). 요지 문장은 LLM이 쓰지 않는다: 이 칸 + 사실 스냅샷으로 규칙이 만든다.
"""
from __future__ import annotations

import json
import re

from .sqrpt import ACTION_CODES, ACTIVITY_CODES, REQUEST_CODES, rule_voice
from .utterance import parse

KEYS = ("a", "c", "r", "n", "w", "wc", "j")

# 미세조정 모델 입력 (학습·추론 동일). 짧게: 프롬프트 캐시 없이도 입력 처리가 몇 초
PROMPT = "분대장 무전 보고를 칸으로 나눠라.\n보고: {text}"

# 기본(미세조정 전) 모델용: 같은 형식 + 코드표 + 예시. 고정 부분이 길어 프롬프트 캐시가 필요하다
FEWSHOT = (
    "분대장 무전 보고를 칸으로 나눠 JSON 한 줄로 답한다.\n"
    "a 적 활동: " + " ".join(ACTIVITY_CODES) + "\n"
    "c 우리 조치: " + " ".join(ACTION_CODES) + "\n"
    "r 요청: " + " ".join(REQUEST_CODES) + "\n"
    "n 분대장이 말한 적 수(없으면 null), w 부상 병사 번호, wc 번호 없는 부상자 수, j 분대장 추정 문장.\n"
    "부정된 것(하지 않음)은 넣지 않는다.\n"
    "보고: 놈들 왼쪽으로 돌아 들어온다 여기서 버틴다 다친 애 빼 줘\n"
    '{"a":["FLANK_LEFT"],"c":["HOLD"],"r":["MEDEVAC"],"n":null,"w":[],"wc":null,"j":[]}\n'
    "보고: 적 5명 접근 중 철수하지 않고 고수 탄약 보내줘\n"
    '{"a":["APPROACH"],"c":["HOLD"],"r":["RESUPPLY"],"n":5,"w":[],"wc":null,"j":[]}\n'
    "보고: 2번 부상 매복인 것 같다 지침 바람\n"
    '{"a":["AMBUSH"],"c":[],"r":["GUIDANCE"],"n":null,"w":[2],"wc":null,"j":["매복인 것 같다"]}\n'
    "보고: {text}\n")

SCHEMA = {
    "type": "object",
    "properties": {
        "a": {"type": "array", "items": {"type": "string", "enum": [c for c in ACTIVITY_CODES if c != "UNKNOWN"]},
              "maxItems": 3},
        "c": {"type": "array", "items": {"type": "string", "enum": list(ACTION_CODES)}, "maxItems": 3},
        "r": {"type": "array", "items": {"type": "string", "enum": list(REQUEST_CODES)}, "maxItems": 3},
        "n": {"type": ["integer", "null"]},
        "w": {"type": "array", "items": {"type": "integer", "minimum": 1, "maximum": 5}, "maxItems": 5},
        "wc": {"type": ["integer", "null"]},
        "j": {"type": "array", "items": {"type": "string", "maxLength": 40}, "maxItems": 2},
    },
    "required": list(KEYS), "additionalProperties": False,
}


def dumps(o: dict) -> str:
    return json.dumps({k: o.get(k) if k in ("n", "wc") else list(o.get(k) or []) for k in KEYS},
                      ensure_ascii=False, separators=(",", ":"))


def rule_nlu(text: str) -> dict:
    """규칙 추출기 → 같은 형식 (비교·대체용)."""
    u = parse(text)
    v = rule_voice(u)
    dedup = lambda xs: list(dict.fromkeys(xs))
    return {"a": dedup(x["code"] for x in v["activity"] if x["code"] != "UNKNOWN"),
            "c": dedup(x["code"] for x in v["action"]), "r": dedup(x["code"] for x in v["requests"]),
            "n": u.enemy_count, "w": list(u.casualty_ids), "wc": u.casualty_n, "j": list(u.judgment)}


def label_from_dataset(row: dict) -> dict:
    """변형 발화 데이터셋 한 줄 → 같은 형식 정답."""
    return {"a": row.get("activity") or [], "c": row.get("action") or [], "r": row.get("requests") or [],
            "n": row.get("leader_count"), "w": row.get("casualties") or [], "wc": row.get("casualty_count"),
            "j": row.get("judgment") or []}


def to_voice_fields(o: dict) -> dict:
    """NLU 결과 → sqrpt.assemble()의 발화 칸."""
    acts = [{"text": ACTIVITY_CODES[c], "code": c} for c in o.get("a", []) if c in ACTIVITY_CODES]
    return {"activity": acts,
            "action": [{"text": ACTION_CODES[c], "code": c} for c in o.get("c", []) if c in ACTION_CODES],
            "requests": [{"text": REQUEST_CODES[c], "code": c, "detail": {}} for c in o.get("r", []) if c in REQUEST_CODES],
            "judgment": [{"text": j} for j in o.get("j", [])], "leader_count": o.get("n"),
            "casualty_ids": o.get("w", []), "summary": None}


def parse_output(text: str) -> dict | None:
    """모델 출력에서 첫 JSON 객체를 꺼내 형식 검사. 실패면 None."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        o = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(o, dict):
        return None
    out = {k: o.get(k) for k in KEYS}
    for k, codes in (("a", ACTIVITY_CODES), ("c", ACTION_CODES), ("r", REQUEST_CODES)):
        out[k] = [c for c in (out[k] or []) if c in codes and c != "UNKNOWN"]
    out["w"] = [int(x) for x in (out["w"] or []) if str(x).isdigit() and 1 <= int(x) <= 5]
    out["j"] = [str(x) for x in (out["j"] or [])][:2]
    for k in ("n", "wc"):
        out[k] = out[k] if isinstance(out[k], int) else None
    return out


def llm_nlu(llm, text: str, timeout: float = 30.0) -> tuple[dict | None, float, str | None]:
    """미세조정 모델로 칸 추출 → (결과|None, ms, 실패 이유)."""
    import time
    t0 = time.monotonic()
    try:
        g = llm.chat("", PROMPT.format(text=text), max_tokens=80, timeout=timeout)
    except Exception as e:                      # 시간 초과·서버 중단
        return None, (time.monotonic() - t0) * 1000, f"llm:{type(e).__name__}"
    o = parse_output(g.text)
    return o, (time.monotonic() - t0) * 1000, None if o is not None else "parse"


def merge(o: dict, rule: dict) -> dict:
    """LLM 결과 + 규칙 결과 (코드는 합집합, 값은 LLM 우선)."""
    u = lambda k: list(dict.fromkeys((o.get(k) or []) + (rule.get(k) or [])))
    return {"a": u("a"), "c": u("c"), "r": u("r"), "w": u("w"),
            "n": o.get("n") if o.get("n") is not None else rule.get("n"),
            "wc": o.get("wc") if o.get("wc") is not None else rule.get("wc"),
            "j": o.get("j") or rule.get("j") or []}
