"""AI 상황 브리핑 / 자연어 질의응답.

구조
  1) build_facts()   : COP 상태 → 사실 목록. 방향(시계)·거리 같은 기하 계산은 여기서 미리 끝내서
                       소형 LLM이 계산을 틀리지 않도록 한다 (LLM은 '요약·표현'만 담당).
  2) recommendations(): 규칙 기반 '조치 건의' 후보
  3) LLM 사용 가능 → 사실 목록 + 지시문으로 스트리밍 생성
     불가        → 규칙 기반 답변 (의도 분류 + 템플릿). 항상 동작 보장.
"""
from __future__ import annotations

import re
import time
from typing import Any, AsyncIterator

from . import geo
from .llm import llm
from .state import ORDER_KO, Store

SYS_BRIEF = """너는 대한민국 육군 소대 전술 C2 체계의 상황 브리핑 보조 AI다.
반드시 아래 [사실]에 있는 정보만 사용하라. 없는 정보를 만들지 마라. 숫자·시계방향·거리는 그대로 옮겨라.

용어(반드시 구분):
- 측위대기: 해당 병사 위치만 아직 없음. SoftAP/라우터가 연결되어 있으면 분대 링크는 정상이다.
- 통신두절: SoftAP/라우터 단절, 또는 장시간 무응답으로 링크가 끊긴 상태.
- 측위대기·구 경보를 소대 전체 통신두절로 확대 해석하지 마라.
- REALTIME에서 1분대 보고(접적·부상 등)는 단말 수신분만 사실이다. 없으면 "1분대 상향 보고 없음"으로 기술.

출력 형식(그대로 지켜라):
■ 적 상황: 1~3문장
■ 아군 상황: 1~3문장
■ 조치 건의: 번호 목록 1~3개 (가장 시급한 것부터)
군대식 간결체(~함, ~임), 전체 350자 이내. 머리말·맺음말 금지."""

SYS_QA = """너는 소대 전술 C2 체계의 질의응답 보조 AI다. [사실]에 있는 정보만 근거로 답하라.
용어: 측위대기≠통신두절. SoftAP 연결 중이면 분대장 링크는 정상.
1~3문장, 군대식 간결체. 방향은 시계, 거리는 m. 답이 없으면 "해당 정보 없음"."""


# ====================================================================== 사실 구성
def _ago(ts: float) -> str:
    s = int(time.time() - ts)
    return f"{s}초 전" if s < 60 else f"{s // 60}분 전"


def _rel(frm, lat: float, lon: float) -> str:
    """기준 유닛(frm) 진행방향 기준 'N시 Dm'."""
    d = geo.distance(frm.lat, frm.lon, lat, lon)
    rel = geo.bearing(frm.lat, frm.lon, lat, lon) - frm.heading
    return f"{geo.clock_dir(rel)}시 {d:.0f}m"


def _pl(s: Store):
    pl = s.units.get("PL") or next((u for u in s.units.values() if u.role == "pl"), None)
    return pl if pl and pl.lat is not None else None


def _name(s: Store, uid: str | None) -> str:
    if not uid:
        return "미상"
    return s.units[uid].callsign if uid in s.units else uid


def _router_up() -> bool:
    try:
        from .sources.router import router_hub
        return router_hub.connected
    except Exception:
        return False


def _mode(s: Store) -> str:
    return getattr(s, "demo_mode", None) or "scenario"


STATUS_KO = {"ok": "정상", "wia": "부상", "kia": "전사", "nolink": "통신두절"}
SQUAD_KO = {"HQ": "소대본부", "1": "1분대", "2": "2분대", "3": "3분대"}


def unit_status_label(u, *, mode: str, router_up: bool) -> str:
    """브리핑용 통일 용어."""
    if u.status == "wia":
        return "부상"
    if u.status == "kia":
        return "전사"
    if u.status == "ok" and u.lat is not None:
        return "정상"
    if mode == "realtime" and u.squad == "1":
        if not router_up:
            return "통신두절"
        # SoftAP 연결 중 — 좌표 없으면 측위대기 (링크 자체는 살아 있을 수 있음)
        if u.lat is None or u.status == "nolink":
            return "측위대기"
        return "정상"
    if u.status == "nolink" or u.lat is None:
        return "통신두절"
    return STATUS_KO.get(u.status, u.status)


def squad_lines(s: Store, *, mode: str, router_up: bool) -> list[str]:
    out = []
    groups: dict[str, list] = {}
    for u in s.units.values():
        groups.setdefault(u.squad, []).append(u)
    for sq in sorted(groups, key=lambda k: (k != "HQ", k)):
        us = groups[sq]
        labels = [(u, unit_status_label(u, mode=mode, router_up=router_up)) for u in us]
        ok = sum(1 for _, lab in labels if lab == "정상")
        bad = [f"{u.callsign} {lab}" for u, lab in labels if lab != "정상"]
        line = f"{SQUAD_KO.get(sq, sq + '분대')} {len(us)}명 중 정상 {ok}"
        if bad:
            line += f" ({', '.join(bad)})"
        if mode == "realtime" and sq == "1":
            line += " [링크:" + ("연결" if router_up else "단절") + "]"
        out.append(line)
    return out


# realtime 브리핑: 이보다 오래된 표적·보고는 제외 (재연결 잔여·스퓨리우스)
_REALTIME_FRESH_SEC = 180.0


def target_lines(s: Store) -> list[str]:
    pl = _pl(s)
    out = []
    mode = _mode(s)
    now = time.time()
    tg = [t for t in s.targets.values() if t.status != "rejected"]
    if mode == "realtime":
        tg = [t for t in tg if now - t.last_seen <= _REALTIME_FRESH_SEC]
    for i, t in enumerate(sorted(tg, key=lambda t: -t.last_seen), 1):
        aff = {"hostile": "적", "unknown": "미확인", "neutral": "중립"}[t.affiliation]
        label = t.label or t.kind
        desc = f"T{i} {aff} " + (label if label.startswith(aff) else label)
        desc = desc.replace(f"{aff} {aff}", aff)
        desc += f" {t.count}명" if t.count and t.kind != "vehicle" else ""
        if t.kind == "vehicle" and t.count:
            desc += f" {t.count}대"
        if t.activity:
            desc += f", {t.activity}"
        if pl:
            desc += f", 소대장 기준 {_rel(pl, t.lat, t.lon)}"
            near = min((u for u in s.units.values() if u.lat is not None and u.status != "kia" and u.id != pl.id),
                       key=lambda u: geo.distance(u.lat, u.lon, t.lat, t.lon), default=None)
            if near:
                desc += f", 최근접 아군 {near.callsign} {geo.distance(near.lat, near.lon, t.lat, t.lon):.0f}m"
        desc += f", {'확인됨' if t.status == 'confirmed' else '미확인(승인 대기)'}"
        desc += f", {_ago(t.last_seen)} ({_name(s, t.reported_by) + ' 보고' if t.reported_by else '출처 미상'})"
        out.append(desc)
    return out


def report_lines(s: Store, n: int = 6) -> list[str]:
    st = {"pending": "승인 대기", "confirmed": "승인", "rejected": "기각"}
    reps = list(s.reports.values())
    if _mode(s) == "realtime":
        cutoff = time.time() - _REALTIME_FRESH_SEC
        reps = [r for r in reps if r.ts >= cutoff]
    return [f"{r.type} {_name(s, r.sender)}: {r.summary} [{st[r.status]}, {_ago(r.ts)}]"
            + (f" 누락={', '.join(r.missing)}" if r.missing else "")
            for r in sorted(reps, key=lambda r: -r.ts)[:n]]


def order_lines(s: Store, n: int = 4) -> list[str]:
    out = []
    for o in sorted(s.orders.values(), key=lambda o: -o.ts)[:n]:
        miss = [_name(s, r) for r in o.recipients if r not in o.acks]
        st = {"sent": "송신", "partial": "일부수신", "acked": "전원수신", "cancelled": "취소",
              "expired": "미수신 만료", "superseded": "대체됨"}.get(o.status, o.status)
        out.append(f"[{ORDER_KO.get(o.code, o.code)}] {o.text} — {st} {len(o.acks)}/{len(o.recipients)}"
                   + (f", 미수신: {', '.join(miss)}" if miss and o.status != "cancelled" else "")
                   + f" ({_ago(o.ts)})")
    return out


def _brief_alerts(s: Store, *, mode: str, router_up: bool) -> list[str]:
    """브리핑용 경보. 연결 중이면 구 두절·측위대기 경보는 제외."""
    out = []
    now = time.time()
    for a in sorted(s.alerts.values(), key=lambda a: -a.ts):
        if a.ack or a.level == "info":
            continue
        if mode == "realtime" and now - a.ts > _REALTIME_FRESH_SEC:
            continue
        if mode == "realtime" and router_up and a.kind in ("link_lost", "fix_wait"):
            continue  # SoftAP 연결됨 — 구 링크 경보로 전체 두절 오판 방지
        if mode == "realtime" and not router_up and a.kind == "fix_wait":
            continue  # 단절 중 잔여 측위대기 경보 — 통신두절로만 기술
        if mode == "realtime" and a.kind == "formation":
            # 좌표 없는(측위대기) 병사의 대형이탈은 잔여 경보 — 제외
            u = s.units.get(a.unit_id or "")
            if u and (u.lat is None or unit_status_label(u, mode=mode, router_up=router_up) == "측위대기"):
                continue
        if mode == "realtime" and a.kind in ("contact", "report") and router_up:
            # 접적 경보는 최근 표적/보고로만 기술 (중복·잔여 억제)
            continue
        if mode == "realtime" and a.kind == "fix_wait":
            msg = a.msg.replace("통신 두절", "측위 대기")
            out.append(msg)
        else:
            out.append(a.msg)
        if len(out) >= 5:
            break
    return out


def recommendations(s: Store) -> list[str]:
    rec: list[str] = []
    t = time.time()
    pl = _pl(s)
    mode = _mode(s)
    router_up = _router_up()
    for r in sorted(s.reports.values(), key=lambda r: -r.ts):
        if r.type == "MEDEVAC" and r.status != "rejected" and r.missing:
            rec.append(f"MEDEVAC 누락 항목({', '.join(r.missing)}) 확인 후 후송 요청 완성")
            break
    wia = [u.callsign for u in s.units.values() if u.status == "wia"]
    if wia:
        rec.append(f"부상자({', '.join(wia)}) 응급처치 및 후송 준비 — 의무병 투입")
    for u in s.units.values():
        lab = unit_status_label(u, mode=mode, router_up=router_up)
        if lab == "통신두절":
            where = f" 최종위치(소대장 기준 {_rel(pl, u.lat, u.lon)})" if pl and u.lat is not None else ""
            rec.append(f"{u.callsign} 통신두절 {int(t - u.last_seen)}초 —{where} 확인 조치")
        elif lab == "측위대기":
            rec.append(f"{u.callsign} 측위대기 — 분대원 relpos/분대장 GPS 수신 확인")
    pend = [r for r in s.reports.values() if r.status == "pending"]
    if pend:
        rec.append(f"승인 대기 보고 {len(pend)}건 판단 필요 ({', '.join(r.type for r in pend[:3])})")
    for o in s.orders.values():
        if o.status in ("partial", "expired"):
            miss = [_name(s, r) for r in o.recipients if r not in o.acks]
            if miss:
                rec.append(f"명령 [{ORDER_KO.get(o.code, o.code)}] 미수신자({', '.join(miss)}) 재하달 또는 전령 확인")
    if pl:
        fresh = time.time() - _REALTIME_FRESH_SEC if mode == "realtime" else 0.0
        close = [
            t_ for t_ in s.targets.values()
            if t_.affiliation == "hostile" and t_.status == "confirmed"
            and t_.last_seen >= fresh
            and geo.distance(pl.lat, pl.lon, t_.lat, t_.lon) < 150
        ]
        if close:
            rec.append(f"150m 이내 확인된 적 {len(close)}건 — 엄폐 및 사격 통제 명령 검토")
    # 중복·과다 억제
    seen: set[str] = set()
    uniq: list[str] = []
    for r in rec:
        if r in seen:
            continue
        seen.add(r)
        uniq.append(r)
    return uniq[:5]


def build_facts(s: Store) -> str:
    units = list(s.units.values())
    mode = _mode(s)
    router_up = _router_up()
    labels = {u.id: unit_status_label(u, mode=mode, router_up=router_up) for u in units}
    cnt = {
        "정상": sum(1 for lab in labels.values() if lab == "정상"),
        "부상": sum(1 for lab in labels.values() if lab == "부상"),
        "전사": sum(1 for lab in labels.values() if lab == "전사"),
        "측위대기": sum(1 for lab in labels.values() if lab == "측위대기"),
        "통신두절": sum(1 for lab in labels.values() if lab == "통신두절"),
    }
    pl = _pl(s)
    lines = [
        f"[시각] {time.strftime('%H:%M:%S')}  [작전] {s.mission.name}  "
        f"[EMCON] {'발령' if s.mission.emcon else '해제'}"
    ]
    if mode == "realtime":
        link = "분대장1 SoftAP/라우터 연결됨 — 분대 링크 정상" if router_up else "분대장1 SoftAP/라우터 미연결"
        lines.append(f"[운용모드] REALTIME · {link}")
        lines.append(
            "[용어] 측위대기=위치 프레임 미수신(링크와 별개). "
            "통신두절=SoftAP 단절 또는 장기 무응답. 둘을 혼동하지 말 것."
        )
    else:
        lines.append("[운용모드] 시나리오")
    if pl:
        lines.append(f"[소대장] 진행방향 {pl.heading:.0f}°")
    lines.append(
        f"[아군] 총 {len(units)}명: 정상 {cnt['정상']}, 부상 {cnt['부상']}, 전사 {cnt['전사']}"
        + (f", 측위대기 {cnt['측위대기']}" if cnt["측위대기"] else "")
        + (f", 통신두절 {cnt['통신두절']}" if cnt["통신두절"] else "")
    )
    lines += ["  - " + x for x in squad_lines(s, mode=mode, router_up=router_up)]
    tl = target_lines(s)
    lines.append(f"[표적] {len(tl)}건" if tl else "[표적] 없음")
    lines += ["  - " + x for x in tl[:8]]
    rl = report_lines(s)
    if rl:
        lines.append("[최근 보고]")
        lines += ["  - " + x for x in rl]
    elif mode == "realtime":
        lines.append("[최근 보고] 1분대 상향 보고 없음 (단말 수신분만 표시)")
    ol = order_lines(s)
    if ol:
        lines.append("[하달 명령]")
        lines += ["  - " + x for x in ol]
    al = _brief_alerts(s, mode=mode, router_up=router_up)
    if al:
        lines.append("[미확인 경보]")
        lines += ["  - " + x for x in al]
    rec = recommendations(s)
    if rec:
        lines.append("[조치 건의 후보]")
        lines += ["  - " + x for x in rec]
    return "\n".join(lines)


# ====================================================================== 규칙 기반 (LLM 없이)
def rule_brief(s: Store) -> str:
    if not s.units:
        return "■ 적 상황: 해당 정보 없음\n■ 아군 상황: 병력 정보 없음\n■ 조치 건의: 1. 상황 파악 후 보고"
    mode = _mode(s)
    router_up = _router_up()
    facts_hint = []
    tl = target_lines(s)
    enemy = "없음." if not tl else "; ".join(tl[:2]) + "."
    labels = [(u, unit_status_label(u, mode=mode, router_up=router_up)) for u in s.units.values()]
    bad = [f"{u.callsign} {lab}" for u, lab in labels if lab != "정상"]
    link = ""
    if mode == "realtime":
        link = " 분대장1 링크 " + ("정상." if router_up else "단절.")
    friendly = f"병력 {len(labels)}명." + link
    if bad:
        friendly += " " + ", ".join(bad[:6]) + "."
    else:
        friendly += " 특이사항 없음."
    rec = recommendations(s)
    rec_txt = "\n".join(f"{i}. {r}" for i, r in enumerate(rec[:3], 1)) if rec else "1. 현 태세 유지 및 지속 감시"
    _ = facts_hint
    return f"■ 적 상황: {enemy}\n■ 아군 상황: {friendly}\n■ 조치 건의:\n{rec_txt}"


def rule_answer(s: Store, q: str) -> str:
    ql = q.lower()
    mode = _mode(s)
    router_up = _router_up()
    if any(k in ql for k in ("대기", "승인", "확인필요", "미확인보고")):
        pend = [r for r in s.reports.values() if r.status == "pending"]
        return (f"승인 대기 {len(pend)}건: " + "; ".join(f"{r.type} {_name(s, r.sender)} — {r.summary}" for r in pend)
                if pend else "승인 대기 보고 없음.")
    if any(k in ql for k in ("명령", "하달", "ack", "수신확인")):
        ol = order_lines(s)
        return "하달 명령: " + " / ".join(ol) if ol else "하달된 명령 없음."
    if any(k in ql for k in ("두절", "통신", "링크", "측위")):
        labs = [(u, unit_status_label(u, mode=mode, router_up=router_up)) for u in s.units.values()]
        nl = [f"{u.callsign}(통신두절)" for u, lab in labs if lab == "통신두절"]
        wait = [f"{u.callsign}(측위대기)" for u, lab in labs if lab == "측위대기"]
        parts = []
        if mode == "realtime":
            parts.append("분대장1 SoftAP " + ("연결" if router_up else "미연결"))
        if nl:
            parts.append("통신두절 " + ", ".join(nl))
        if wait:
            parts.append("측위대기 " + ", ".join(wait))
        return ". ".join(parts) + "." if parts else "전원 통신·측위 양호."
    if "적" in q:
        tl = [x for x in target_lines(s) if x.split(" ")[1] in ("적", "미확인")]
        return "; ".join(tl[:3]) + "." if tl else "확인된 적 없음."
    if any(k in q for k in ("건의", "조치", "해야", "우선")):
        rec = recommendations(s)
        return " ".join(f"{i}. {r}." for i, r in enumerate(rec, 1)) if rec else "특이 조치 사항 없음."
    return rule_brief(s)


# ====================================================================== 진입점
def _messages(s: Store, question: str | None) -> list[dict]:
    facts = build_facts(s)
    if question:
        return [{"role": "system", "content": SYS_QA},
                {"role": "user", "content": f"[사실]\n{facts}\n\n[질문] {question}"}]
    return [{"role": "system", "content": SYS_BRIEF},
            {"role": "user", "content": f"[사실]\n{facts}\n\n위 사실로 소대장 상황 브리핑을 작성하라."}]


async def stream(s: Store, question: str | None = None, use_llm: bool = True) -> AsyncIterator[dict[str, Any]]:
    """이벤트 스트림: meta → token* → done. LLM 실패 시 규칙 기반으로 자동 폴백."""
    question = (question or "").strip() or None
    st = await llm.refresh()
    if use_llm and st["available"]:
        yield {"type": "meta", "engine": f"llm:{llm.model}", "facts": build_facts(s)}
        buf = ""
        t0 = time.time()
        try:
            async for tok in llm.stream(_messages(s, question)):
                buf += tok
                yield {"type": "token", "text": tok}
            yield {"type": "done", "text": buf.strip(), "latency": round(time.time() - t0, 2)}
            return
        except Exception as e:
            yield {"type": "error", "message": f"LLM 오류: {e} — 규칙 기반으로 전환"}
    text = rule_answer(s, question) if question else rule_brief(s)
    yield {"type": "meta", "engine": "rule", "facts": build_facts(s),
           "reason": None if not use_llm else (st.get("error") or "LLM 비활성")}
    for chunk in re.split(r"(?<=[.\n])", text):
        if chunk:
            yield {"type": "token", "text": chunk}
    yield {"type": "done", "text": text, "latency": 0}


async def brief(s: Store, question: str | None = None, use_llm: bool = True) -> dict:
    out = {"text": "", "engine": "rule"}
    async for ev in stream(s, question, use_llm):
        if ev["type"] == "meta":
            out["engine"] = ev["engine"]
        elif ev["type"] == "done":
            out["text"] = ev["text"]
    return out
