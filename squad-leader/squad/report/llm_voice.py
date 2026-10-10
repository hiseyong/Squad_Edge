"""LLM 발화 칸 생성 (sq-rpt/0.1 §6): 분대장 보고 음성(STT 텍스트) + 사실 요약 → 활동·조치·요청·판단·요지.

LLM은 분류와 요지 문장만 한다. 좌표·인원·시각은 스냅샷 값을 assemble()이 그대로 쓴다.
출력은 JSON 스키마로 강제(코드는 enum, 길이 제한)하고, validate()를 통과하지 못하면 None → 규칙 대체.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass

from .grid import cardinal
from .sqrpt import ACTION_CODES, ACTIVITY_CODES, REQUEST_CODES, SUMMARY_MAX, _count_text, validate


def _item(codes: dict, text_max: int = 20) -> dict:
    return {"type": "object", "properties": {"text": {"type": "string", "maxLength": text_max},
                                             "code": {"type": "string", "enum": list(codes)}},
            "required": ["text", "code"], "additionalProperties": False}


SCHEMA = {
    "type": "object",
    "properties": {
        "activity": {"type": "array", "items": _item(ACTIVITY_CODES), "maxItems": 2},
        "action": {"type": "array", "items": _item(ACTION_CODES), "maxItems": 3},
        "requests": {"type": "array", "items": _item(REQUEST_CODES), "maxItems": 3},
        "judgment": {"type": "array", "items": {"type": "string", "maxLength": 40}, "maxItems": 2},
        "leader_count": {"type": ["integer", "null"]},
        "summary": {"type": "string", "maxLength": SUMMARY_MAX},
    },
    "required": ["activity", "action", "requests", "judgment", "leader_count", "summary"],
    "additionalProperties": False,
}

# 고정 지시문을 앞에 둔다 (llama.cpp 프롬프트 캐시로 매번 다시 읽지 않음). 지시는 사용자 메시지에 넣는다.
PROMPT = """분대장 무전 보고를 소대장 보고 칸으로 정리한다.
규칙:
- activity: 적의 행동. action: 우리 분대의 현재 조치. requests: 소대장에게 요청. judgment: 분대장의 추정·판단 문장.
- 발화에 없는 것은 넣지 않는다. 부정("하지 않음")은 그 조치가 아니다.
- leader_count: 분대장이 적 수를 말했을 때만 그 숫자, 아니면 null.
- summary: 소대장용 요지 한 문장. [사실]과 발화에 있는 숫자만 쓴다. 적 수·방향·거리, 아군 부상, 조치, 요청 순서.
각 칸의 text는 짧은 한국어 명사구.

[사실]
{facts}

[발화] {voice}"""


def facts_text(snap: dict) -> str:
    """스냅샷 → 짧은 한국어 사실 줄 (JSON 전체보다 토큰이 훨씬 적다)."""
    lines = []
    for i, e in enumerate(snap["enemy"], 1):
        s = f"적{i}: {_count_text(e['size']['count'])}"
        if e["location"]:
            s += f", {cardinal(e['location']['bearing'])} {round(e['location']['dist'], -1):.0f}m"
        if e["activity"]["trend"]:
            s += f", 보고 추세 {e['activity']['trend']}"
        lines.append(s)
    f = snap["friendly"]
    s = f"아군: 가용 {f['available']}/{f['total']}"
    if f["casualties"]:
        s += ", 부상 " + ", ".join(c["id"] for c in f["casualties"])
    if f["ammo_issue"]:
        s += ", 탄약 문제 " + ", ".join(f["ammo_issue"])
    if f["lost"]:
        s += ", 두절 " + ", ".join(f["lost"])
    lines.append(s)
    for h in snap["hazards"]:
        lines.append(f"위험: {h['kind']} ({h['by']} 보고)")
    return "\n".join(lines) or "특이사항 없음"


@dataclass
class LlmResult:
    fields: dict | None          # 검증 통과한 발화 칸 (assemble에 넘김), 실패면 None
    reason: str | None           # 실패 이유
    ms: float
    raw: str


def generate(llm, voice_text: str, snap: dict, timeout_s: float = 60.0, max_tokens: int = 220) -> LlmResult:
    t = time.perf_counter()
    try:
        g = llm.chat("", PROMPT.format(facts=facts_text(snap), voice=voice_text), max_tokens=max_tokens,
                     schema=SCHEMA, timeout=timeout_s)
    except Exception as e:  # noqa: BLE001 (시간 초과·서버 오류 → 규칙 대체)
        return LlmResult(None, f"LLM 호출 실패: {e}", (time.perf_counter() - t) * 1000, "")
    ms = (time.perf_counter() - t) * 1000
    try:
        out = json.loads(g.text)
    except json.JSONDecodeError:
        return LlmResult(None, "JSON 아님(출력 잘림)", ms, g.text)
    v = {"activity": out["activity"], "action": out["action"],
         "requests": [{**r, "detail": {}} for r in out["requests"]],
         "judgment": [{"text": j} for j in out["judgment"]],
         "leader_count": out["leader_count"], "summary": out["summary"].strip()}
    why = validate(v, snap, voice_text)
    return LlmResult(None if why else v, why, ms, g.text)
