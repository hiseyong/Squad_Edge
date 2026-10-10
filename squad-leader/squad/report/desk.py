"""보고 처리기 (sq-rpt/0.1 §2, §7, §8): 초안 → 복창 → 송신 → 소대장 확인 대기·재송신, LLM 정정본.

  draft(voice, now)  분대장 발화(+사건) → 규칙 기반 data (gen.by = "rule"), 복창 문장
  send(data)         송신 기록, 확인 대기 등록 (flash/urgent는 ACK_WAIT_S 뒤 1회 재송신)
  refine(data)       LLM 발화 칸으로 같은 보고의 rev+1 (검증 실패면 None)
  on_ack / on_query  소대장 응답 처리
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from .sqrpt import FMT, Geo, ReportCounter, assemble, priority, readback, rule_voice, snapshot, wire
from .situation import Situation
from .utterance import parse

ACK_WAIT_S = 10.0
RESEND_PRIO = {"flash", "urgent"}


@dataclass
class Pending:
    data: dict
    sent_at: float
    resent: bool = False


@dataclass
class SqDesk:
    sit: Situation
    geo: Geo
    squad: str = "1"
    unit: str = "1분대"
    counter: ReportCounter = field(default_factory=ReportCounter)
    log: object | None = None                 # CombatLog
    llm: object | None = None                 # LocalLLM (없으면 규칙만)
    events: list[str] = field(default_factory=list)
    last_sent: dict | None = None
    pending: dict[str, Pending] = field(default_factory=dict)   # rpt.id → 확인 대기
    acked: set = field(default_factory=set)

    def on_events(self, events: list[str]) -> bool:
        """보고 계기면 True (헤드셋에 "보고 준비됨")."""
        from .compose import TRIGGERS
        hit = [e for e in events if e in TRIGGERS]
        self.events += hit
        return bool(hit)

    def draft(self, voice_text: str | None, now: float | None = None, nlu: dict | None = None,
              nlu_gen: dict | None = None) -> tuple[dict, str]:
        """nlu: 미세조정 LLM이 채운 칸(squad.report.nlu 형식). 검증을 통과하면 그 칸으로, 아니면 규칙 추출로 채운다."""
        now = time.time() if now is None else now
        snap = snapshot(self.sit, self.geo, now, self.squad)
        gen = {"by": "rule", "model": None, "ms": 0, "checks": "pass", "fallback_reason": None}
        v = None
        u = parse(voice_text or "")

        def with_voice_enemy(snap, vv):
            if not snap["enemy"] and (vv["activity"] or vv.get("leader_count")):
                return {**snap, "enemy": [voice_enemy(self.geo, u, vv, now, self.squad, voice_text or "")]}
            return snap
        if nlu is not None:
            from .nlu import to_voice_fields
            from .sqrpt import rule_summary, validate
            cand = to_voice_fields(nlu)
            snap_c = with_voice_enemy(snap, cand)
            cand["summary"] = rule_summary(snap_c, cand)
            reason = validate(cand, snap_c, voice_text or "")
            if reason is None:
                v, snap = cand, snap_c
                gen = {"by": "llm", "checks": "pass", "fallback_reason": None, **(nlu_gen or {})}
            else:
                gen["fallback_reason"] = f"llm:{reason}"
        elif nlu_gen and nlu_gen.get("fallback_reason"):
            gen["fallback_reason"] = nlu_gen["fallback_reason"]
        if v is None:
            v = rule_voice(u)
            snap = with_voice_enemy(snap, v)
        prec = priority(self.events, snap, v, (self.last_sent or {}).get("body"))
        rid = f"{self.squad}-1-{self.counter.next():04d}"
        data = assemble(snap, v, prec=prec, rpt_id=rid, rev=0, unit=self.unit, gen=gen,
                        voice_text=voice_text, last=self.last_sent, squad=self.squad)
        data["_snap"], data["_voice"] = snap, voice_text
        return data, readback(data, self.geo.heading)

    def send(self, data: dict, now: float | None = None) -> dict:
        """송신할 report.new data (봉투 없이). 기록하고 확인 대기에 올린다."""
        now = time.time() if now is None else now
        self.last_sent, self.events = data, []
        if data["priority"] in RESEND_PRIO:
            self.pending[data["rpt"]["id"]] = Pending(data, now)
        if self.log is not None:
            self.log.add("sent", 0, {"rpt": data["rpt"], "priority": data["priority"], "gen": data["gen"],
                                     "text": data["text"]}, ts=now)
        return wire_data(data)

    def refine(self, data: dict, timeout_s: float = 60.0) -> dict | None:
        """LLM 발화 칸으로 같은 보고 rev+1. 실패하면 None (규칙본이 그대로 유효)."""
        if self.llm is None or not data.get("_voice"):
            return None
        from .nlu import llm_nlu, rule_nlu, to_voice_fields
        from .sqrpt import rule_summary, validate
        o, ms, reason = llm_nlu(self.llm, data["_voice"], timeout=timeout_s)
        fields = to_voice_fields(o) if o is not None else None
        if fields is not None:
            fields["summary"] = rule_summary(data["_snap"], fields)
            reason = validate(fields, data["_snap"], data["_voice"])
            if reason is None and o == rule_nlu(data["_voice"]):
                reason = "same"                 # 규칙본과 같으면 정정본을 보내지 않는다
        if self.log is not None:
            self.log.add("note", 0, {"llm": data["rpt"]["id"], "ok": reason is None, "reason": reason,
                                     "ms": round(ms)})
        if reason is not None:
            return None
        new = assemble(data["_snap"], fields, prec=data["priority"], rpt_id=data["rpt"]["id"],
                       rev=data["rpt"]["rev"] + 1, unit=self.unit,
                       gen={"by": "llm", "model": getattr(self.llm, "name", None), "ms": round(ms),
                            "checks": "pass", "fallback_reason": None},
                       voice_text=data["_voice"], last=None, squad=self.squad)
        new["_snap"], new["_voice"] = data["_snap"], data["_voice"]
        return new

    def due_resends(self, now: float | None = None) -> list[dict]:
        """확인이 없는 섬광·긴급 보고 (1회만)."""
        now = time.time() if now is None else now
        out = []
        for rid, p in self.pending.items():
            if not p.resent and rid not in self.acked and now - p.sent_at >= ACK_WAIT_S:
                p.resent = True
                out.append(wire_data(p.data))
        return out

    def on_ack(self, ref: str, rev: int | None = None) -> None:
        self.acked.add(ref)
        self.pending.pop(ref, None)

    def on_query(self, ref: str) -> dict | None:
        """재송·상세 요청 → 그 보고의 최신본 (없으면 None)."""
        d = self.last_sent if self.last_sent and self.last_sent["rpt"]["id"] == ref else None
        if d is None and ref in self.pending:
            d = self.pending[ref].data
        return wire_data(d) if d else None


def voice_enemy(geo: Geo, u, v: dict, now: float, squad: str, text: str = "") -> dict:
    """병사 보고로 잡힌 표적이 없을 때 분대장이 말로 알린 적(수·활동·방향·거리) → 보고서 적 항목(snapshot 형식).
    방향·거리는 규칙 파서 값, 없으면 발화에서 "N시"·"Nm"를 직접 찾는다(STT가 문장부호 없이 이어 붙여도)."""
    import math
    import re
    from .sqrpt import _count_text
    n = v.get("leader_count") or u.enemy_count or 0
    clock, dist_m = u.enemy_clock, u.enemy_dist_m
    if not clock and (m := re.search(r"(1[0-2]|[1-9])\s*시", text)):
        clock = int(m.group(1))
    if not dist_m and (m := re.search(r"(\d+)\s*(km|m|미터)", text)):
        dist_m = int(m.group(1)) * (1000 if m.group(2) == "km" else 1)
    loc = None
    if clock:
        brg = (geo.heading + clock * 30) % 360
        if dist_m:
            x, y = dist_m * math.sin(math.radians(brg)), dist_m * math.cos(math.radians(brg))
            lat, lon = geo.latlon(x, y)
            loc = {"mgrs": geo.mgrs(x, y), "lat": lat, "lon": lon, "err_m": max(10, round(dist_m * 0.2)),
                   "basis": "분대장 육안", "rel": {"ref": f"{squad}-1", "dx": round(x), "dy": round(y)},
                   "bearing": brg, "dist": dist_m}
    act = v["activity"][0] if v["activity"] else {"text": None, "code": "UNKNOWN"}
    return {"tid": "V", "size": {"count": n, "count_text": _count_text(n), "kind": "infantry", "src": "voice",
                                 "reporters": [f"{squad}-1"], "leader_count": v.get("leader_count")},
            "activity": {"text": act["text"], "code": act["code"], "src": "voice", "trend": None},
            "location": loc, "time": {"first": round(now), "last": round(now)}, "equipment": {"text": "미상", "src": None}}


def wire_data(data: dict) -> dict:
    return {k: v for k, v in wire(data).items()}


__all__ = ["SqDesk", "FMT", "Geo", "ReportCounter"]
