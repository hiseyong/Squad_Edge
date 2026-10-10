"""보고서 조립: 상황 집계 + 분대장 발화 → 양식화된 보고 (텍스트 + 구조화 데이터 + 복창 문장).

항목과 순서는 소대장이 보고를 받고 던지는 질문 순서를 따른다.
  1 요지(얼마나 급한가, 뭘 해줘야 하나)  2 적(SALUTE: 규모·활동·위치·시간·장비, + 추세)
  3 아군(위치·가용 인원·부상·탄약·연결)  4 조치  5 요청  6 판단
근거: TC 3-21.75 9-7(결정적 정보는 즉시, SALUTE가 1단계 보고), 9-11·표 9-1(SALUTE, 위치는 100km 구역 포함 8자리 격자),
      11-3(9개 항목 의무후송 요청). 탄약·사상자·장비(ACE/LACE)는 미군 관행(비공식 자료로만 확인).

분대장↔소대장 형식은 팀 간 미확정 → 이 모듈의 텍스트·JSON은 초안이다 ("v": "draft-1").
불확실성은 숨기지 않는다: 위치마다 ±오차와 근거(교차 추정/단독 보고), 오래된 관측은 "n분 전 관측",
분대장 판단과 병사 보고가 다르면 둘 다 적는다.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

from ..protocol import azimuth_to_clock
from .grid import Utm, cardinal, utm_to_mgrs
from .situation import EnemyTrack, Situation, bearing
from .utterance import Utterance

PREC_KO = {"FLASH": "섬광", "IMMEDIATE": "긴급", "PRIORITY": "우선", "ROUTINE": "보통"}
STALE_S = 120.0
NO_CHANGE = "변동 없음"


def _count_text(n: int) -> str:
    return "미상" if n == 0 else "5명 이상" if n >= 5 else f"{n}명"


def _ago(now: float, ts: float) -> str:
    m = int((now - ts) // 60)
    return "방금" if m < 1 else f"{m}분 전"


@dataclass
class Report:
    prec: str
    ts: float
    unit: str
    summary: str
    sections: dict[str, str]                 # 항목 이름 → 한 줄 (변동 없으면 NO_CHANGE)
    data: dict                               # 구조화 데이터 (소대장 노트북 COP·LLM 브리핑용)
    readback: str                            # 분대장 헤드셋 복창
    prompts: list[str] = field(default_factory=list)   # 분대장에게 되물을 것

    def text(self) -> str:
        hhmm = time.strftime("%H:%M", time.localtime(self.ts))
        lines = [f"[{PREC_KO[self.prec]}] {hhmm} {self.unit} → 소대장  {self.data['type_ko']}", f"요지: {self.summary}"]
        lines += [f"{k}: {v}" for k, v in self.sections.items() if v]
        return "\n".join(lines)


class Composer:
    def __init__(self, sit: Situation, origin: Utm, leader_heading: int = 0, unit: str = "1분대"):
        self.sit, self.origin, self.heading, self.unit = sit, origin, leader_heading, unit

    def grid(self, x: float, y: float) -> str:
        return utm_to_mgrs(self.origin.offset(x, y))

    def _rel(self, x: float, y: float) -> str:
        return f"분대 {cardinal(bearing(x, y))} {round(math.hypot(x, y), -1):.0f}m"

    def _enemy(self, tr: EnemyTrack, u: Utterance, now: float, primary: bool) -> tuple[str, dict]:
        cnt = _count_text(tr.count)
        conf = f"병사 {len(tr.reporters)}명 보고"
        if not primary:                       # 분대장 발화(규모·활동)는 주 표적에만 적용
            u = Utterance()
        if u.enemy_count and u.enemy_count != tr.count:
            size = f"보병 {u.enemy_count}명(분대장 판단), 병사 확인 {cnt}"
        else:
            size = f"보병 {cnt}({conf})"
        acts = list(u.activity)
        trend = tr.trend()
        if trend and not any(trend[:2] in a for a in acts):
            acts.append(f"{trend}(보고 추세)")
        act = ", ".join(acts) or "미상"
        if tr.pos:
            loc = f"{self.grid(*tr.pos)} ±{tr.err_m:.0f}m, {tr.basis} ({self._rel(*tr.pos)})"
        else:
            loc = "위치 미상(방향 없는 보고)"
        t = f"최초 {time.strftime('%H:%M', time.localtime(tr.first_t))}, 최근 {_ago(now, tr.last_t)} 관측"
        line = f"규모 {size} / 활동 {act} / 위치 {loc} / {t} / 장비 미상"
        data = {"count": tr.count, "count_leader": u.enemy_count, "reporters": tr.reporters, "activity": acts,
                "mgrs": self.grid(*tr.pos) if tr.pos else None, "err_m": round(tr.err_m), "basis": tr.basis,
                "rel_m": [round(tr.pos[0]), round(tr.pos[1])] if tr.pos else None,
                "first_seen": tr.first_t, "last_seen": tr.last_t, "trend": trend}
        return line, data

    def compose(self, u: Utterance | None = None, now: float | None = None, events: list[str] = (),
                last: Report | None = None) -> Report:
        u = u or Utterance()
        now = time.time() if now is None else now
        tracks = self.sit.active_tracks(now)
        fr = self.sit.friendly(now)
        cas = sorted(set(fr["casualties"]) | set(u.casualty_ids))
        sections: dict[str, str] = {}
        data: dict = {"v": "draft-1", "unit": self.unit, "time": now}

        # 적
        enemies = [self._enemy(tr, u, now, i == 0) for i, tr in enumerate(tracks[:3])]
        if enemies:
            sections["적"] = "\n      ".join(e[0] for e in enemies)
        elif u.enemy_count or u.activity:
            sections["적"] = f"규모 {_count_text(u.enemy_count or 0)}(분대장 판단) / 활동 {', '.join(u.activity) or '미상'}"
        data["enemy"] = [e[1] for e in enemies]
        pts = [p for p in self.sit.points if now - p.ts <= 900 and p.kind != "의심 징후"]
        if pts:
            sections["위험"] = " / ".join(
                f"{p.kind} {self.grid(*p.pos) if p.pos else '위치 미상'}({p.sid}번 보고, {_ago(now, p.ts)})" for p in pts)
        data["points"] = [{"kind": p.kind, "mgrs": self.grid(*p.pos) if p.pos else None, "by": p.sid, "ts": p.ts}
                          for p in pts]

        # 아군
        parts = [f"위치 {self.grid(0, 0)}, 정면 {cardinal(self.heading)}", f"가용 {fr['available']}/{fr['total']}"]
        if cas:
            parts.append("부상 " + ", ".join(f"{i}번" for i in cas))
        elif u.casualty_n:
            parts.append(f"부상 {u.casualty_n}명")
        parts.append("탄약·화기 문제 " + ", ".join(f"{i}번" for i in fr["ammo_issue"]) if fr["ammo_issue"]
                     else "탄약·화기 이상 없음")
        if fr["lost"]:
            parts.append("연락 두절 " + ", ".join(f"{i}번" for i in fr["lost"]))
        if fr["silent"]:
            parts.append("무선 침묵 " + ", ".join(f"{i}번" for i in fr["silent"]))
        sections["아군"] = " / ".join(parts)
        data["friendly"] = {**fr, "casualties": cas, "mgrs": self.grid(0, 0), "heading": self.heading}

        sections["조치"] = ", ".join(u.action) or "미보고"
        sections["요청"] = ", ".join(u.requests) or "없음"
        if u.judgment:
            sections["판단"] = " / ".join(u.judgment)
        data.update(action=u.action, requests=u.requests, judgment=u.judgment)

        # 우선순위 (명세 v1의 긴급 보고 기준과 같은 결)
        if "new_contact" in events or "casualty" in events or (cas and not (last and last.data["friendly"]["casualties"])):
            prec = "FLASH"
        elif {"hazard", "contact_grew", "contact_closer", "ammo", "link_lost"} & set(events) or u.requests:
            prec = "IMMEDIATE"
        elif tracks:
            prec = "PRIORITY"
        else:
            prec = "ROUTINE"
        kind = "적정·상황보고" if (enemies or "적" in sections) else "상황보고"
        data.update(prec=prec, type="SPOTREP+SITREP" if enemies else "SITREP", type_ko=kind)

        summary = self._summary(tracks, u, cas, fr)
        readback = self._readback(prec, tracks, u, cas, fr)
        prompts = []
        if (tracks or cas) and not u.action:
            prompts.append("현재 조치?")
        if cas and "의무후송" not in u.requests:
            prompts.append("의무후송 요청?")

        # 직전 송신 보고와 같은 항목은 "변동 없음" (송신량·전파 방출 줄이기). 요지는 항상 보낸다
        if last:
            for k, v in list(sections.items()):
                if last.sections.get(k) == v or (last.sections.get(k) == NO_CHANGE and last.data.get("_full", {}).get(k) == v):
                    sections[k] = NO_CHANGE
        data["_full"] = {k: v for k, v in sections.items()}
        return Report(prec, now, self.unit, summary, sections, data, readback, prompts)

    def _summary(self, tracks, u: Utterance, cas, fr) -> str:
        bits = []
        if tracks:
            tr = tracks[0]
            n = u.enemy_count or tr.count
            where = self._rel(*tr.pos).replace("분대 ", "") if tr.pos else ""
            act = (u.activity or [f"{tr.trend()}" if tr.trend() else ""])[0]
            bits.append(" ".join(x for x in (f"적 {_count_text(n)}", where, act) if x))
        if cas:
            bits.append(f"아군 {len(cas)}명 부상")
        if fr["lost"]:
            bits.append(f"{len(fr['lost'])}명 연락 두절")
        if u.action:
            bits.append(u.action[0])
        if u.requests:
            bits.append(", ".join(u.requests) + " 요청")
        return ". ".join(bits) + "." if bits else "특이사항 없음."

    def _readback(self, prec, tracks, u: Utterance, cas, fr) -> str:
        """헤드셋 복창: 방향은 분대장 기준 시계 방향 (격자 좌표는 읽지 않는다)."""
        out = [PREC_KO[prec]]
        if tracks:
            tr = tracks[0]
            n = u.enemy_count or tr.count
            s = f"적 {_count_text(n)}"
            if tr.pos:
                s += f", {azimuth_to_clock(round(bearing(*tr.pos)), self.heading)}시 방향 {round(math.hypot(*tr.pos), -1):.0f}미터"
            if u.activity:
                s += f", {u.activity[0]}"
            out.append(s)
        if cas:
            out.append(", ".join(f"{i}번" for i in cas) + " 부상")
        if u.action:
            out.append(", ".join(u.action))
        if u.requests:
            out.append(", ".join(u.requests) + " 요청")
        return ". ".join(out) + ". 송신할까요?"


# 보고 계기 (구상 C안: 사건 → 초안 자동 생성 → 분대장 확인 후 송신)
TRIGGERS = {
    "new_contact": "FLASH", "casualty": "FLASH", "link_lost": "IMMEDIATE",
    "contact_grew": "IMMEDIATE", "contact_closer": "IMMEDIATE", "hazard": "IMMEDIATE", "ammo": "IMMEDIATE",
}
PERIODIC_S = 600.0


class ReportDesk:
    """사건이 오면 초안을 만들고, 분대장이 확인하면 송신 기록을 남긴다."""

    def __init__(self, composer: Composer, log=None):
        self.c, self.log = composer, log
        self.draft: Report | None = None
        self.last_sent: Report | None = None
        self._events: list[str] = []

    def on_events(self, events: list[str], now: float) -> Report | None:
        """보고 계기면 새 초안을 돌려준다 (분대장 헤드셋에 "적정 보고 준비됨" 알림용)."""
        hit = [e for e in events if e in TRIGGERS]
        if not hit:
            return None
        self._events += hit
        self.draft = self.c.compose(now=now, events=self._events, last=self.last_sent)
        return self.draft

    def tick(self, now: float) -> Report | None:
        """정기 보고: 마지막 송신 후 PERIODIC_S 지나면 초안."""
        if self.draft is None and (self.last_sent is None or now - self.last_sent.ts >= PERIODIC_S):
            self.draft = self.c.compose(now=now, last=self.last_sent)
            return self.draft
        return None

    def with_voice(self, u: Utterance, now: float) -> Report:
        """보고 버튼 + 분대장 발화 → 초안에 판단·요청을 합친다 (초안이 없으면 새로)."""
        self.draft = self.c.compose(u, now=now, events=self._events, last=self.last_sent)
        return self.draft

    def confirm(self) -> Report | None:
        """분대장이 복창을 듣고 '송신' 버튼 → 송신 기록. 실제 전송은 소대장 링크 담당(미확정)."""
        r, self.draft = self.draft, None
        if r is not None:
            self.last_sent, self._events = r, []
            if self.log is not None:
                self.log.add("sent", 0, {"prec": r.prec, "text": r.text(), "data": {k: v for k, v in r.data.items()
                                                                                     if k != "_full"}}, ts=r.ts)
        return r

    def cancel(self) -> None:
        self.draft = None
