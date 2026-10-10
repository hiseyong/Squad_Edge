"""COP 상태 저장소 + 이벤트 처리 + 경보 규칙 + 웹소켓 브로드캐스트.

새 이벤트 타입을 추가하려면 `@handler("타입")` 함수 하나만 추가하면 된다.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Iterable

from . import geo
from .downlink import audit, downlink, order_cancel_data, order_new_data
from .models import (Alert, Event, Link, Mission, Order, Report, Sensor, Stats,
                     Target, Unit, now)

log = logging.getLogger("cop.state")

# 무선 프레임 크기 추정치 [byte] (CBOR 압축 가정). 실제 값이 오면 그것을 사용.
EST_BYTES = {
    "unit.position": 18, "unit.relpos": 14, "unit.status": 6, "unit.upsert": 24,
    "link.update": 6, "sensor.trigger": 10, "report.new": 72, "target.upsert": 32,
    "ack": 8,
}
# 하향 진동 패턴 (docs/TERMINAL_PROTOCOL.md §4.13)
ORDER_HAPTIC = {
    "HALT": "LONG_1", "MOVE": "SHORT_2", "RALLY": "SHORT_3", "TAKE_COVER": "LONG_3",
    "WEAPONS_HOLD": "SHORT_LONG", "WEAPONS_FREE": "SHORT_LONG", "RECHECK": "SHORT_SHORT_LONG",
    "FRAGO": "SHORT_2",
}
ORDER_KO = {
    "HALT": "정지", "MOVE": "이동", "RALLY": "집결", "TAKE_COVER": "엄폐", "WEAPONS_HOLD": "사격중지",
    "WEAPONS_FREE": "사격자유", "RECHECK": "재확인 요청", "FRAGO": "단편명령",
}
DECISION_HAPTIC = {"confirmed": "SHORT_1", "rejected": "SHORT_LONG"}
ORDER_RETX_SEC = 8.0       # 미수신 대상에게 재전송 간격
ORDER_MAX_TX = 4           # 최초 1 + 재전송 3
# 재명령 시 무효화할 이전 명령 코드 집합
SUPERSEDE_OF: dict[str, frozenset[str]] = {
    "WEAPONS_HOLD": frozenset({"WEAPONS_HOLD", "WEAPONS_FREE"}),
    "WEAPONS_FREE": frozenset({"WEAPONS_HOLD", "WEAPONS_FREE"}),
    "RALLY": frozenset({"RALLY", "HALT", "MOVE"}),       # 새 집결 → 이전 집결·정지·이동 무효
    "HALT": frozenset({"HALT", "MOVE", "RALLY"}),
    "MOVE": frozenset({"HALT", "MOVE", "RALLY"}),
    "TAKE_COVER": frozenset({"TAKE_COVER"}),
}
# 음성으로 같은 정보를 보냈다고 가정할 때 (8 kbps 코덱, 메시지당 평균 발화 시간 s)
VOICE_SEC = {"report.new": 12, "unit.status": 3, "sensor.trigger": 4, "unit.position": 0}
VOICE_BPS = 8000 / 8

STALE_SEC = 15.0           # 이 시간 이상 소식 없으면 통신 두절
FORMATION_MAX_M = 60.0     # 분대장과 이 거리 이상 떨어지면 대형 이탈
TRAIL_LEN = 40

COLLECTIONS = ("units", "targets", "reports", "sensors", "links", "alerts", "orders")

_handlers: dict[str, Callable[["Store", dict[str, Any]], None]] = {}


def handler(event_type: str):
    def deco(fn):
        _handlers[event_type] = fn
        return fn
    return deco


class Store:
    def __init__(self) -> None:
        self.mission = Mission()
        self.stats = Stats()
        self.units: dict[str, Unit] = {}
        self.targets: dict[str, Target] = {}
        self.reports: dict[str, Report] = {}
        self.sensors: dict[str, Sensor] = {}
        self.links: dict[str, Link] = {}
        self.alerts: dict[str, Alert] = {}
        self.orders: dict[str, Order] = {}
        self._prev_status: dict[str, str] = {}    # 두절 직전 상태 (복구 시 되돌림)
        self._subs: set[asyncio.Queue] = set()
        self._alert_keys: dict[str, float] = {}   # 중복 경보 억제
        self.demo_mode: str = "scenario"  # scenario | realtime — 브리핑 용어용

    # ------------------------------------------------------------------ pub/sub
    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=2000)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    def _emit(self, msg: dict[str, Any]) -> None:
        data = json.dumps(msg, ensure_ascii=False)
        for q in list(self._subs):
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                pass

    def put(self, coll: str, item) -> None:
        getattr(self, coll)[item.id] = item
        self._emit({"t": "patch", "c": coll, "op": "upsert", "v": item.model_dump()})

    def remove(self, coll: str, item_id: str) -> None:
        if getattr(self, coll).pop(item_id, None) is not None:
            self._emit({"t": "patch", "c": coll, "op": "remove", "id": item_id})

    def emit_meta(self) -> None:
        self._emit({"t": "mission", "v": self.mission.model_dump()})
        self._emit({"t": "stats", "v": self.stats.model_dump()})

    def snapshot(self) -> dict[str, Any]:
        snap: dict[str, Any] = {c: [v.model_dump() for v in getattr(self, c).values()]
                                for c in COLLECTIONS}
        snap["mission"] = self.mission.model_dump()
        snap["stats"] = self.stats.model_dump()
        snap["server_time"] = now()
        return snap

    def reset(self) -> None:
        mission, subs, mode = self.mission, self._subs, self.demo_mode
        self.__init__()
        self.mission, self._subs, self.demo_mode = mission, subs, mode
        self._emit({"t": "snapshot", "v": self.snapshot()})

    # ------------------------------------------------------------------ ingest
    def ingest(self, ev: Event | dict[str, Any]) -> None:
        try:
            if isinstance(ev, dict):
                ev = Event(**ev)
            fn = _handlers.get(ev.type)
            if fn is None:
                log.warning("unknown event type %s", ev.type)
                return
            fn(self, ev.data)
            b = ev.bytes if ev.bytes is not None else EST_BYTES.get(ev.type, 0)
            if b:
                self.stats.tx_bytes += b
                self.stats.tx_msgs += 1
                self.stats.tx_by_type[ev.type] = self.stats.tx_by_type.get(ev.type, 0) + b
                if ev.type in VOICE_SEC and VOICE_SEC[ev.type] > 0:
                    self.stats.voice_equiv_bytes += int(VOICE_SEC[ev.type] * VOICE_BPS)
                    self.stats.voiceable_bytes += b
        except Exception:
            log.exception("ingest failed type=%s", getattr(ev, "type", None) if not isinstance(ev, dict) else ev.get("type"))

    # ------------------------------------------------------------------ alerts
    def alert(self, level: str, kind: str, msg: str, unit_id: str | None = None,
              key: str | None = None, cooldown: float = 30.0) -> None:
        key = key or f"{kind}:{unit_id}"
        t = now()
        if t - self._alert_keys.get(key, 0) < cooldown:
            return
        self._alert_keys[key] = t
        self.put("alerts", Alert(level=level, kind=kind, msg=msg, unit_id=unit_id))

    def mark_units_nolink(self, ids: Iterable[str], *, reason: str = "연결 끊김") -> None:
        """라우터 단절·측위 대기 — 좌표 제거. 용어: 대기=측위대기, 그 외=통신두절."""
        waiting = any(k in reason for k in ("대기", "신호 대기"))
        kind = "fix_wait" if waiting else "link_lost"
        label = "측위 대기" if waiting else "통신 두절"
        for uid in ids:
            u = self.units.get(uid)
            if not u or u.status == "kia":
                continue
            already = u.status == "nolink" and u.lat is None
            if not already:
                if u.status != "nolink":
                    self._prev_status[uid] = u.status
                u.status = "nolink"
                u.lat, u.lon = None, None
                self.put("units", u)
            # 이미 nolink여도 단절↔측위대기 전환 시 경보 갱신
            if already and waiting:
                continue  # 측위대기 유지 — 중복 경보 생략
            if already and not waiting:
                # SoftAP 단절: 구 fix_wait 경보 확인 후 link_lost 발행
                for a in self.alerts.values():
                    if not a.ack and a.kind == "fix_wait" and a.unit_id == uid:
                        a.ack = True
                        self.put("alerts", a)
            self.alert("warn", kind, f"{u.callsign} {label} ({reason})", u.id, cooldown=5)

    def clear_squad1_link_alerts(self) -> None:
        """SoftAP/라우터 재연결 시 구 두절·측위대기·무좌표 대형이탈 경보 자동 확인."""
        drop_kinds = {"link_lost", "fix_wait"}
        for aid, a in list(self.alerts.items()):
            if a.ack:
                continue
            uid = a.unit_id
            sq1 = not uid or str(uid).startswith("1-")
            if a.kind in drop_kinds and sq1:
                a.ack = True
                self.put("alerts", a)
                continue
            if a.kind == "formation" and sq1:
                u = self.units.get(uid or "")
                if u and u.lat is None:
                    a.ack = True
                    self.put("alerts", a)

    def periodic_checks(self) -> None:
        """1초마다 호출: 통신 두절·측위대기 / 대형 이탈 / 센서 상태 복귀."""
        t = now()
        router_up = False
        if self.demo_mode == "realtime":
            try:
                from .sources.router import router_hub
                router_up = router_hub.connected
            except Exception:
                pass
        for u in self.units.values():
            if u.status in ("ok", "wia") and t - u.last_seen > STALE_SEC:
                self._prev_status[u.id] = u.status
                u.status = "nolink"
                self.put("units", u)
                # SoftAP 연결 중 1분대 무응답 = 측위대기 (링크 단절과 구분)
                if self.demo_mode == "realtime" and router_up and str(u.squad) == "1":
                    self.alert(
                        "warn", "fix_wait",
                        f"{u.callsign} 측위 대기 ({int(t - u.last_seen)}초)",
                        u.id,
                    )
                else:
                    self.alert(
                        "warn", "link_lost",
                        f"{u.callsign} 통신 두절 ({int(t - u.last_seen)}초)",
                        u.id,
                    )
        # 대형 이탈: 분대원 ↔ 분대장 거리
        leaders = {u.squad: u for u in self.units.values() if u.role in ("sl", "pl")}
        for u in self.units.values():
            sl = leaders.get(u.squad)
            if not sl or sl.id == u.id or u.lat is None or sl.lat is None or u.status == "nolink":
                continue
            d = geo.distance(sl.lat, sl.lon, u.lat, u.lon)
            if d > FORMATION_MAX_M:
                rel = geo.bearing(sl.lat, sl.lon, u.lat, u.lon) - sl.heading
                self.alert("warn", "formation", f"{u.callsign} 대형 이탈 — {sl.callsign} 기준 "
                           f"{geo.clock_dir(rel)}시 {d:.0f}m", u.id, cooldown=45)
        for s in self.sensors.values():
            if s.status == "triggered" and s.last_trigger and t - s.last_trigger > 20:
                s.status = "idle"
                self.put("sensors", s)
        # 링크 만료
        for lid in [k for k, l in self.links.items() if t - l.ts > 10]:
            self.remove("links", lid)
        # 명령 미수신자 재전송 / 만료
        for o in list(self.orders.values()):
            if o.status not in ("sent", "partial"):
                continue
            missing = [r for r in o.recipients if r not in o.acks]
            if not missing:
                continue
            if t - o.last_tx >= ORDER_RETX_SEC:
                if o.tx_count >= ORDER_MAX_TX:
                    o.status = "expired"
                    self.put("orders", o)
                    names = ", ".join(self.units[m].callsign if m in self.units else m for m in missing)
                    self.alert("warn", "order_unacked", f"명령 [{ORDER_KO[o.code]}] 미수신: {names}",
                               key=f"ordexp:{o.id}", cooldown=1)
                else:
                    o.tx_count += 1
                    o.last_tx = t
                    self._transmit_order(o, only=missing)
                    self.put("orders", o)

    # ================================================================ 지휘 결심 (COP → 하향)
    def decide_report(self, rid: str, action: str, by: str = "PL", note: str = "",
                      edits: dict[str, Any] | None = None) -> Report | None:
        """보고 승인/기각/재확인요청/되돌리기.
        action: confirm | reject | recheck | reopen
        edits : {summary?, priority?, fields?: {...}}  — 승인 전 AI 추출 오류 수정
        """
        r = self.reports.get(rid)
        if not r:
            return None
        edits = edits or {}
        if edits:
            if "summary" in edits:
                r.summary = edits["summary"]
            if "priority" in edits:
                r.priority = edits["priority"]
            if isinstance(edits.get("fields"), dict):
                r.fields = {**r.fields, **edits["fields"]}
                r.missing = [m for m in r.missing if r.fields.get(m) in (None, "")]
        t = now()
        entry = {"ts": t, "action": action, "by": by, "note": note}
        if edits:
            entry["edits"] = edits
        r.history.append(entry)

        if action in ("confirm", "reject"):
            r.status = "confirmed" if action == "confirm" else "rejected"
            r.decided_by, r.decided_at, r.decision_note = by, t, note
            r.sender_acked = False
            tgt = self.targets.get(r.target_id) if r.target_id else None
            if tgt is None and action == "confirm":
                tgt = _make_target(self, r)
            if tgt is not None:
                tgt.status = r.status
                f = r.fields
                if edits.get("fields"):
                    tgt.kind = f.get("kind", tgt.kind)
                    tgt.count = f.get("size", tgt.count)
                    tgt.activity = f.get("activity", tgt.activity)
                    tgt.label = f.get("unit", tgt.label) or tgt.label
                    loc = f.get("location")
                    if isinstance(loc, dict) and "lat" in loc:
                        tgt.lat, tgt.lon = loc["lat"], loc["lon"]
                if action == "confirm":
                    tgt.affiliation = "hostile" if tgt.affiliation == "unknown" and r.type != "FREE" else tgt.affiliation
                tgt.last_seen = t
                self.put("targets", tgt)
            # 결과를 보고자 단말로 하향 (ACK 요구) + 진동
            downlink.send("report.update", r.sender,
                          {"id": r.id, "status": r.status, "note": note, "edits": edits},
                          prio="priority", ack=True)
            downlink.send("haptic", r.sender, {"pattern": DECISION_HAPTIC[r.status], "reason": "report", "ref": r.id})
            self.alert("info", "decision",
                       f"{r.type} 보고 {'승인' if action == 'confirm' else '기각'} — {r.summary}"
                       + (f" ({note})" if note else ""), r.sender, key=f"dec:{r.id}:{action}", cooldown=1)
        elif action == "recheck":
            r.status = "pending"
            r.recheck_count += 1
            question = note or (f"누락 항목 확인: {', '.join(r.missing)}" if r.missing else "보고 내용 재확인 바람")
            self.issue_order("RECHECK", [r.sender], text=f"[{r.type}] {r.summary} — {question}",
                             by=by, ref_report=r.id, priority="priority")
        elif action == "reopen":
            r.status = "pending"
            r.decided_by = r.decided_at = None
            r.decision_note = ""
            tgt = self.targets.get(r.target_id) if r.target_id else None
            if tgt:
                tgt.status = "pending"
                self.put("targets", tgt)
        self.put("reports", r)
        audit("report." + action, report=r.id, type=r.type, sender=r.sender, by=by, note=note, edits=edits,
              summary=r.summary)
        return r

    def _squad_leader_id(self, squad: str) -> str | None:
        for u in self.units.values():
            if u.squad == squad and u.role == "sl" and u.status != "kia":
                return u.id
        return None

    def _expand(self, to: list[str]) -> list[str]:
        """하달 수신자 = 분대장만. 분대원 개인·전 분대원 전개는 하지 않음."""
        out: list[str] = []

        def add(uid: str | None) -> None:
            if not uid or uid in out:
                return
            u = self.units.get(uid)
            if u and u.status != "kia":
                out.append(uid)

        for x in to:
            if x == "*":
                for u in self.units.values():
                    if u.role == "sl":
                        add(u.id)
                # HQ는 분대장 없음 → 통신병만
                for u in self.units.values():
                    if u.squad == "HQ" and u.role == "radio":
                        add(u.id)
            elif x in self.units:
                u = self.units[x]
                if u.role == "pl":
                    continue
                if u.role == "sl":
                    add(u.id)
                elif u.squad == "HQ":
                    add(u.id)  # HQ 개별 선택 시 해당 인원
                else:
                    add(self._squad_leader_id(u.squad))  # 분대원 → 분대장으로 승격
            elif x == "HQ":
                for u in self.units.values():
                    if u.squad == "HQ" and u.role == "radio":
                        add(u.id)
            else:  # 분대 번호 "1"|"2"|"3"
                add(self._squad_leader_id(x))
        return out

    def _transmit_order(self, o: Order, only: list[str] | None = None) -> None:
        """하향 허브로 order.new(+text) 송출 → SoftAP(q3_ap)·라우터 WS (분대장만)."""
        targets = only or o.recipients
        downlink.send(
            "order.new", "*", order_new_data(o, targets),
            prio=o.priority, ack=True,
        )
        # 햅틱도 분대장 단말만 (분대원 BLE 개별 전송 없음)
        for rid in targets:
            downlink.send("haptic", rid, {"pattern": ORDER_HAPTIC.get(o.code, "SHORT_2"), "reason": "order", "ref": o.id})

    def _active_order(self, o: Order) -> bool:
        return o.status in ("sent", "partial", "acked", "expired")

    def _supersede_prior(self, code: str, by: str = "PL") -> list[Order]:
        """재명령 시 이전 활성 명령을 superseded 처리하고 단말에 철회 통지."""
        group = SUPERSEDE_OF.get(code)
        if not group:
            return []
        killed: list[Order] = []
        for o in list(self.orders.values()):
            if o.code not in group or not self._active_order(o):
                continue
            o.status = "superseded"
            downlink.send(
                "order.cancel", "*",
                order_cancel_data(o, reason="superseded", by_code=code),
                prio="priority", ack=False,
            )
            self.put("orders", o)
            audit("order.superseded", order=o.id, code=o.code, by=by, by_code=code)
            killed.append(o)
        if killed:
            names = ", ".join(ORDER_KO.get(x.code, x.code) for x in killed)
            self.alert(
                "info", "order",
                f"이전 명령 무효화 [{names}] ← 재명령 {ORDER_KO.get(code, code)}",
                key=f"ordsup:{code}:{now():.0f}", cooldown=1,
            )
        return killed

    def issue_order(self, code: str, to: list[str], text: str = "", params: dict | None = None,
                    by: str = "PL", priority: str = "priority", ref_report: str | None = None) -> Order:
        # 사격자유/중지·집결 등 재명령 시 이전 동일 그룹 명령 무효화
        self._supersede_prior(code, by=by)
        o = Order(code=code, to=to, text=text or ORDER_KO.get(code, code), params=params or {},
                  issuer=by, priority=priority, ref_report=ref_report)
        o.recipients = self._expand(to)
        self.put("orders", o)
        self._transmit_order(o)
        dest = "전 소대" if "*" in to else ", ".join(
            (f"{x}분대" if x.isdigit() else ("본부" if x == "HQ" else self.units[x].callsign if x in self.units else x))
            for x in to)
        if code != "RECHECK":
            self.alert("info", "order", f"명령 하달 [{ORDER_KO.get(code, code)}] → {dest}: {o.text}",
                       key=f"ord:{o.id}", cooldown=1)
        audit("order.new", order=o.id, code=code, to=to, recipients=o.recipients, text=o.text,
              params=o.params, by=by)
        return o

    def cancel_order(self, oid: str, by: str = "PL") -> Order | None:
        """명령 취소/철회. 집결·사격통제 등은 수신 완료(acked) 후에도 철회 가능."""
        o = self.orders.get(oid)
        if not o or o.status in ("cancelled", "superseded"):
            return o
        if o.status not in ("sent", "partial", "acked", "expired"):
            return o
        o.status = "cancelled"
        downlink.send(
            "order.cancel", "*",
            order_cancel_data(o, reason="cancelled"),
            prio="priority", ack=False,
        )
        self.put("orders", o)
        self.alert("info", "order", f"명령 철회 [{ORDER_KO.get(o.code, o.code)}]: {o.text}",
                   key=f"ordc:{o.id}", cooldown=1)
        audit("order.cancel", order=o.id, by=by, code=o.code)
        return o


# ====================================================================== handlers
def _touch(s: Store, uid: str) -> Unit | None:
    u = s.units.get(uid)
    if u is None:
        return None
    u.last_seen = now()
    if u.status == "nolink":
        u.status = s._prev_status.pop(u.id, "ok")
        s.alert("info", "link_restored", f"{u.callsign} 통신 복구", u.id, cooldown=5)
        # 저장 후 전달: 두절 중 못 받은 명령을 복구 즉시 재전송
        for o in s.orders.values():
            if o.status in ("sent", "partial", "expired") and uid in o.recipients and uid not in o.acks:
                if o.status == "expired":
                    o.status = "partial" if o.acks else "sent"
                o.last_tx = now()
                s._transmit_order(o, only=[uid])
                s.put("orders", o)
    return u


def _set_pos(u: Unit, lat: float, lon: float) -> None:
    if u.lat is not None and geo.distance(u.lat, u.lon, lat, lon) > 2.0:
        u.trail.append((u.lat, u.lon))
        u.trail = u.trail[-TRAIL_LEN:]
    u.lat, u.lon = lat, lon


@handler("unit.upsert")
def _unit_upsert(s: Store, d: dict) -> None:
    u = s.units.get(d["id"])
    u = u.model_copy(update=d) if u else Unit(**d)
    u.last_seen = now()
    s.put("units", u)


@handler("unit.position")
def _unit_position(s: Store, d: dict) -> None:
    """절대 좌표(GPS 등). {id, lat, lon, heading?, err?, source?, battery?, rssi?}"""
    u = _touch(s, d["id"])
    if not u:
        return
    _set_pos(u, d["lat"], d["lon"])
    u.heading = d.get("heading", u.heading)
    u.pos_err = d.get("err", u.pos_err)
    src = d.get("source", "gps")
    u.pos_source = src if src in ("gps", "ble-rel", "manual", "dr", "demo") else "gps"
    u.battery = d.get("battery", u.battery)
    u.rssi = d.get("rssi", u.rssi)
    s.put("units", u)


@handler("unit.relpos")
def _unit_relpos(s: Store, d: dict) -> None:
    """BLE 상대측위 결과. {id, ref, dx(동,m), dy(북,m), err?} → ref 유닛 기준 절대 좌표로 변환."""
    ref = s.units.get(d["ref"])
    # 분대장(ref) GPS가 없으면 절대좌표 불가 — 두절 복구도 하지 않음
    if not ref or ref.lat is None or ref.status == "nolink":
        return
    u = _touch(s, d["id"])
    if not u:
        return
    lat, lon = geo.offset(ref.lat, ref.lon, d["dx"], d["dy"])
    _set_pos(u, lat, lon)
    u.heading = d.get("heading", u.heading)
    u.pos_err = d.get("err", 5.0)
    u.pos_source = "ble-rel"
    u.battery = d.get("battery", u.battery)
    s.put("units", u)


@handler("unit.status")
def _unit_status(s: Store, d: dict) -> None:
    u = _touch(s, d["id"])
    if not u:
        return
    prev, u.status = u.status, d["status"]
    s.put("units", u)
    if d["status"] == "wia" and prev != "wia":
        s.alert("crit", "casualty", f"{u.callsign} 부상 (WIA)", u.id, cooldown=5)
    elif d["status"] == "kia" and prev != "kia":
        s.alert("crit", "casualty", f"{u.callsign} 전사 (KIA)", u.id, cooldown=5)


@handler("link.update")
def _link_update(s: Store, d: dict) -> None:
    a, b = sorted((d["a"], d["b"]))
    s.put("links", Link(id=f"{a}|{b}", a=a, b=b, rssi=d["rssi"]))


@handler("sensor.upsert")
def _sensor_upsert(s: Store, d: dict) -> None:
    sen = s.sensors.get(d["id"])
    sen = sen.model_copy(update=d) if sen else Sensor(**d)
    sen.last_seen = now()
    s.put("sensors", sen)


@handler("sensor.trigger")
def _sensor_trigger(s: Store, d: dict) -> None:
    """무인 센서 감지. {id, kind?, conf?} → 센서 위치에 미확인 표적 생성."""
    sen = s.sensors.get(d["id"])
    if not sen:
        return
    sen.status, sen.last_trigger, sen.last_seen = "triggered", now(), now()
    s.put("sensors", sen)
    # 같은 센서의 최근 미확인 표적이 있으면 갱신
    for t in s.targets.values():
        if t.source == "sensor" and t.reported_by == sen.id and now() - t.last_seen < 60:
            t.last_seen = now()
            s.put("targets", t)
            break
    else:
        s.put("targets", Target(affiliation="unknown", kind="movement", label=f"{sen.id} 감지",
                                lat=sen.lat, lon=sen.lon, err_m=25, conf=d.get("conf", 0.4),
                                reported_by=sen.id, source="sensor", activity="미확인 움직임"))
    s.alert("warn", "sensor", f"무인센서 {sen.id}({sen.kind}) 움직임 감지", key=f"sensor:{sen.id}")


@handler("target.upsert")
def _target_upsert(s: Store, d: dict) -> None:
    t = s.targets.get(d.get("id", ""))
    t = t.model_copy(update=d) if t else Target(**d)
    t.last_seen = now()
    s.put("targets", t)


@handler("target.remove")
def _target_remove(s: Store, d: dict) -> None:
    s.remove("targets", d["id"])


def _ref_unit(s: Store, r: Report, loc: dict) -> Unit | None:
    """location.ref 또는 보고자 유닛."""
    rid = loc.get("ref") or r.sender
    return s.units.get(rid) if rid else None


def _unit_with_fix(s: Store, r: Report, loc: dict | None = None) -> Unit | None:
    """지도 표적용 — 보고자 → 같은 분대 유효좌표 순으로 기준점."""
    loc = loc if isinstance(loc, dict) else {}
    ref = _ref_unit(s, r, loc)
    if ref and ref.lat is not None and ref.lon is not None:
        return ref
    sender = s.units.get(r.sender) if r.sender else None
    if sender and sender.lat is not None and sender.lon is not None:
        return sender
    sq = sender.squad if sender else (r.sender.split("-")[0] if r.sender and "-" in r.sender else None)
    if not sq:
        return None
    for u in s.units.values():
        if u.squad == sq and u.lat is not None and u.lon is not None and u.status != "nolink":
            return u
    return None


def _resolve_report_ll(s: Store, r: Report, loc: dict) -> tuple[float, float, float] | None:
    """location → (lat, lon, err_m). CONTACT는 좌표 없어도 보고자 위치에 표시."""
    ref = _unit_with_fix(s, r, loc)
    if "lat" in loc and loc["lat"] is not None and loc.get("lon") is not None:
        return float(loc["lat"]), float(loc["lon"]), float(loc.get("err") or 40)
    if ref and ref.lat is not None and ref.lon is not None:
        if "bearing" in loc and loc["bearing"] is not None:
            lat, lon = geo.polar(ref.lat, ref.lon, float(loc["bearing"]), float(loc.get("dist") or 100))
            loc["lat"], loc["lon"] = lat, lon
            return lat, lon, float(loc.get("err") or 40)
        if "clock" in loc and loc["clock"] is not None:
            try:
                clock = int(loc["clock"])
            except (TypeError, ValueError):
                clock = 0
            if 1 <= clock <= 12:
                bearing = (ref.heading + (clock - 12) * 30) % 360
                lat, lon = geo.polar(ref.lat, ref.lon, bearing, float(loc.get("dist") or 100))
                loc["lat"], loc["lon"] = lat, lon
                loc.setdefault("bearing", bearing)
                return lat, lon, float(loc.get("err") or 40)
        if r.type == "CONTACT":
            # 방위 없는 접적 → 보고자(분대) 위치에 큰 오차원
            return ref.lat, ref.lon, float(loc.get("err") or 100)
    return None


def _make_target(s: Store, r: Report) -> Target | None:
    """보고의 location(절대 또는 보고자/ref 기준 상대)으로 표적 생성."""
    loc = r.fields.get("location")
    if loc is None:
        loc = {}
    target_types = ("SALUTE", "SPOT", "CONTACT", "SPOTREP+SITREP")
    if r.type not in target_types:
        return None
    if not isinstance(loc, dict):
        if r.type == "SPOTREP+SITREP":
            return _make_targets_from_enemy(s, r)
        if r.type != "CONTACT":
            return None
        loc = {}
    r.fields["location"] = loc

    resolved = _resolve_report_ll(s, r, loc)
    if resolved is None:
        return _make_targets_from_enemy(s, r) if r.type == "SPOTREP+SITREP" else None
    lat, lon, err_m = resolved

    kind = "contact" if r.type == "CONTACT" else r.fields.get("kind", "infantry")
    activity = r.fields.get("activity", "") or ("접적" if r.type == "CONTACT" else "")
    count = r.fields.get("size")
    # draft-1: enemy[0] 보강
    enemies = r.fields.get("enemy")
    if isinstance(enemies, list) and enemies and isinstance(enemies[0], dict):
        e0 = enemies[0]
        count = count or e0.get("count")
        ea = e0.get("activity")
        if not activity and isinstance(ea, list) and ea:
            activity = str(ea[0])
        elif not activity and isinstance(ea, str):
            activity = ea
        if e0.get("err_m") is not None:
            err_m = float(e0["err_m"])
            loc.setdefault("err", err_m)
    if r.type == "CONTACT":
        label = r.fields.get("unit") or f"접적 · {r.sender}"
    else:
        label = r.fields.get("unit", "") or (r.summary[:24] if r.summary else "적")
    tgt = Target(affiliation="hostile", kind=kind,
                 label=label,
                 lat=lat, lon=lon, count=count,
                 activity=activity if isinstance(activity, str) else str(activity),
                 err_m=err_m, conf=r.conf, reported_by=r.sender,
                 source="voice", status="confirmed" if r.status == "confirmed" else "pending")
    r.target_id = tgt.id
    s.put("targets", tgt)
    if r.type == "SPOTREP+SITREP":
        _make_targets_from_enemy(s, r, skip_first=True)
    return tgt


def _make_targets_from_enemy(s: Store, r: Report, *, skip_first: bool = False) -> Target | None:
    """draft-1 fields.enemy[] → 추가 표적. 첫 표적 id를 반환(있으면)."""
    enemies = r.fields.get("enemy")
    if not isinstance(enemies, list):
        return None
    loc = r.fields.get("location") if isinstance(r.fields.get("location"), dict) else {}
    ref = _ref_unit(s, r, loc)
    first: Target | None = None
    for i, e in enumerate(enemies):
        if not isinstance(e, dict):
            continue
        if skip_first and i == 0:
            continue
        lat = lon = None
        if e.get("lat") is not None:
            lat, lon = e["lat"], e.get("lon")
        elif loc.get("lat") is not None and i == 0:
            lat, lon = loc["lat"], loc["lon"]
        elif loc.get("bearing") is not None and ref and ref.lat is not None and i == 0:
            lat, lon = geo.polar(ref.lat, ref.lon, loc["bearing"], loc.get("dist", 100))
        if lat is None:
            continue
        act = e.get("activity")
        if isinstance(act, list):
            act = ", ".join(str(a) for a in act) if act else ""
        tgt = Target(
            affiliation="hostile", kind="infantry",
            label=f"적 {e.get('count', '?')}명" if e.get("count") else (r.summary[:16] or "적"),
            lat=lat, lon=lon, count=e.get("count"),
            activity=str(act or ""),
            err_m=float(e.get("err_m") or loc.get("err") or 40),
            conf=r.conf, reported_by=r.sender, source="voice",
            status="confirmed" if r.status == "confirmed" else "pending",
        )
        if first is None:
            first = tgt
            if not r.target_id:
                r.target_id = tgt.id
        s.put("targets", tgt)
    return first


def _apply_friendly_casualties(s: Store, r: Report) -> None:
    """draft-1 friendly.casualties: 병사 번호(1~5) → COP 유닛 부상."""
    fr = r.fields.get("friendly")
    if not isinstance(fr, dict):
        return
    cas = fr.get("casualties") or []
    squad = (r.sender.split("-")[0] if r.sender and "-" in r.sender else "1")
    for n in cas:
        try:
            ble = int(n)
        except (TypeError, ValueError):
            continue
        # BLE 병사 n → COP {squad}-{n+1}
        uid = f"{squad}-{ble + 1}"
        u = s.units.get(uid)
        if u and u.status not in ("wia", "kia"):
            prev, u.status = u.status, "wia"
            s.put("units", u)
            if prev != "wia":
                s.alert("crit", "casualty", f"{u.callsign} 부상 (보고)", u.id, cooldown=5)


@handler("report.new")
def _report_new(s: Store, d: dict) -> None:
    """음성 AI / 분대장 draft-1 구조화 보고.
    SALUTE fields 예: {size, activity, location:{lat,lon}|{bearing,dist}, unit, time, equipment}
    location이 상대(bearing/dist)면 ref 또는 보고자 기준 절대 좌표 변환 후 표적 생성.
    """
    from .sources.ingest_util import normalize_report_data
    r = Report(**normalize_report_data(d))
    sender = s.units.get(r.sender)
    if sender:
        _touch(s, sender.id)
    if r.conf < 0.7 and r.type in ("SALUTE", "SPOT"):
        r.status = "pending"
    _make_target(s, r)
    if r.type == "SPOTREP+SITREP":
        _apply_friendly_casualties(s, r)
    s.put("reports", r)
    who = sender.callsign if sender else r.sender
    if r.type == "MEDEVAC":
        s.alert("crit", "medevac", f"{who} 의무후송 요청 — {r.summary}", r.sender, cooldown=5)
    elif r.type in ("CONTACT", "SALUTE", "SPOTREP+SITREP") and r.priority != "routine":
        s.alert("crit" if r.priority == "urgent" else "warn", "contact", f"{who}: {r.summary}",
                r.sender, key=f"rep:{r.id}")
        reqs = r.fields.get("requests") if isinstance(r.fields.get("requests"), list) else []
        if any("의무" in str(x) or "MEDEVAC" in str(x).upper() for x in reqs):
            s.alert("crit", "medevac", f"{who} 의무후송 요청", r.sender, key=f"med:{r.id}", cooldown=5)
    if r.missing:
        s.alert("info", "missing", f"{r.type} 보고 누락 항목: {', '.join(r.missing)}", key=f"miss:{r.id}")


@handler("report.update")
def _report_update(s: Store, d: dict) -> None:
    """호환용: {id, status: confirmed|rejected|pending, note?, by?}"""
    action = {"confirmed": "confirm", "rejected": "reject", "pending": "reopen"}.get(d.get("status", ""))
    if action:
        s.decide_report(d["id"], action, by=d.get("by", "PL"), note=d.get("note", ""), edits=d.get("edits"))


@handler("report.decision")
def _report_decision(s: Store, d: dict) -> None:
    """{id, action: confirm|reject|recheck|reopen, by?, note?, edits?} — 음성 명령으로도 호출 가능"""
    s.decide_report(d["id"], d["action"], by=d.get("by", "PL"), note=d.get("note", ""), edits=d.get("edits"))


@handler("report.amend")
def _report_amend(s: Store, d: dict) -> None:
    """보고자의 보완 보고 (재확인 요청에 대한 응답). {id, fields?, summary?, conf?, raw_text?, from?}"""
    r = s.reports.get(d["id"])
    if not r:
        return
    if isinstance(d.get("fields"), dict):
        r.fields = {**r.fields, **d["fields"]}
        r.missing = [m for m in r.missing if r.fields.get(m) in (None, "")]
    for k in ("summary", "conf", "raw_text"):
        if k in d:
            setattr(r, k, d[k])
    r.history.append({"ts": now(), "action": "amend", "by": d.get("from", r.sender),
                      "note": d.get("raw_text", ""), "edits": {"fields": d.get("fields", {})}})
    tgt = s.targets.get(r.target_id) if r.target_id else None
    if tgt:
        tgt.conf = r.conf
        tgt.activity = r.fields.get("activity", tgt.activity)
        tgt.label = r.fields.get("unit", tgt.label) or tgt.label
        tgt.last_seen = now()
        s.put("targets", tgt)
    for o in s.orders.values():  # 연계된 재확인 명령은 응답으로 수신 확인 처리
        if o.ref_report == r.id and r.sender not in o.acks:
            o.acks[r.sender] = now()
            o.status = "acked"
            s.put("orders", o)
    s.put("reports", r)
    s.alert("info", "amend", f"{_name_of(s, r.sender)} 보완 보고 수신 — {r.summary}", r.sender,
            key=f"amend:{r.id}:{len(r.history)}", cooldown=1)


def _name_of(s: Store, uid: str) -> str:
    return s.units[uid].callsign if uid in s.units else uid


@handler("order.new")
def _order_new(s: Store, d: dict) -> None:
    """{code, to[], text?, params?, priority?, by?} — 소대장 음성 명령 모듈 등에서 입력"""
    s.issue_order(d["code"], d.get("to", ["*"]), text=d.get("text", ""), params=d.get("params"),
                  by=d.get("by", "PL"), priority=d.get("priority", "priority"))


@handler("ack")
def _ack(s: Store, d: dict) -> None:
    """단말 수신확인. {ref: 명령ID|보고ID, from: 노드ID, ok?: bool}"""
    src = d.get("from") or d.get("src")
    if src:
        _touch(s, src)
    ref = d.get("ref", "")
    if ref in s.orders:
        o = s.orders[ref]
        if src and src not in o.acks:
            o.acks[src] = now()
            if o.status in ("sent", "partial", "expired"):
                o.status = "acked" if all(r in o.acks for r in o.recipients) else "partial"
            s.put("orders", o)
    elif ref in s.reports:
        r = s.reports[ref]
        r.sender_acked = True
        s.put("reports", r)


@handler("alert.new")
def _alert_new(s: Store, d: dict) -> None:
    s.put("alerts", Alert(**d))


@handler("mission.update")
def _mission_update(s: Store, d: dict) -> None:
    s.mission = s.mission.model_copy(update=d)
    s.emit_meta()


store = Store()
