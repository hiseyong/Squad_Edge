"""데모용 시나리오 / realtime 하이브리드 시뮬레이터.

- scenario: 전 소대 mock + 스크립트 이벤트
- realtime:
    · 위치만 mock: 1-1 GPS + HQ·2·3 (연결 시). 1-2~1-4는 Arduino relpos
    · 메시 링크 = 위치 기반 COP 합성
    · 보고·부상·접적·두절연출·RECHECK 보완 등 기타 이벤트 = 시뮬 생성 금지
    · 1분대 상향 이벤트 = Arduino만

실제 하드웨어가 보낼 이벤트와 **같은 형식**으로 store.ingest()를 호출한다.
"""
from __future__ import annotations

import asyncio
import logging
import math
import random
import time
from typing import Iterable

from .. import geo
from ..downlink import downlink
from ..state import Store

log = logging.getLogger("cop.sim")

# realtime: 분대원만 HW. 1-1 GPS는 COP mock — Arduino 연결 중에만.
# 단절 시 1분대 전원(1-1 포함) 두절.
LIVE_SQUADS_DEFAULT = frozenset({"1"})
MOCK_GPS_UNITS = frozenset({"1-1"})
HW_GPS_UNITS = frozenset()  # 비움 — 분대장 GPS는 mock
HW_RELPOS_UNITS = frozenset({"1-2", "1-3", "1-4"})
NOLINK_ON_DISCONNECT = MOCK_GPS_UNITS | HW_RELPOS_UNITS
HW_SQUAD_UNITS = NOLINK_ON_DISCONNECT
LIVE_UNIT_IDS = HW_RELPOS_UNITS  # 하위 호환: HW 위치 노드 = 분대원

# realtime에서 시뮬이 넣어도 되는 타입 (위치·링크·명령 ACK만)
_REALTIME_MOCK_OK = frozenset({
    "unit.position", "unit.relpos", "unit.upsert", "link.update", "mission.update", "ack",
})

# 정찰 경로 (대략 북동쪽으로 700m)
ROUTE = [
    (36.3005, 127.4185), (36.3028, 127.4200), (36.3046, 127.4228),
    (36.3062, 127.4246), (36.3080, 127.4262),
]
OBJECTIVE = (36.3095, 127.4290)
PHASE_LINES = [
    {"name": "PL 알파", "coords": [(36.3020, 127.4170), (36.3010, 127.4235)]},
    {"name": "PL 브라보", "coords": [(36.3060, 127.4210), (36.3040, 127.4275)]},
]
# 소대 대형 (소대장 기준 body-frame: x=우측, y=전방) [m]
PLATOON = {"HQ": (0, 0), "1": (-35, 35), "2": (35, 35), "3": (0, -35)}
SQUAD_WEDGE = [(0, 0), (-9, -8), (9, -8), (-18, -16)]
HQ_SLOTS = {"PL": (0, 0), "HQ-R": (-6, -5), "HQ-M": (6, -5)}

ROSTER = [
    dict(id="PL", callsign="소대장", role="pl", squad="HQ"),
    dict(id="HQ-R", callsign="통신병", role="radio", squad="HQ"),
    dict(id="HQ-M", callsign="의무병", role="medic", squad="HQ"),
]
for sq in ("1", "2", "3"):
    ROSTER.append(dict(id=f"{sq}-1", callsign=f"{sq}분대장", role="sl", squad=sq))
    for k, role in ((2, "rifleman"), (3, "gunner"), (4, "rifleman")):
        ROSTER.append(dict(id=f"{sq}-{k}", callsign=f"{sq}-{k}", role=role, squad=sq))


def rssi_at(d: float) -> float:
    return -59 - 10 * 2.2 * math.log10(max(d, 0.5)) + random.gauss(0, 3)


class Simulator:
    def __init__(self, store: Store) -> None:
        self.s = store
        self.task: asyncio.Task | None = None
        self.running = False
        self.offline: set[str] = set()
        self.halted = False
        # scenario | realtime — realtime이면 1-2~1-4만 HW relpos, 1-1 GPS는 mock
        self.mode: str = "scenario"
        self.live_squads: frozenset[str] = frozenset()
        downlink.add_listener(self._on_downlink)

    def configure(self, mode: str = "scenario", live_squads: Iterable[str] | None = None) -> None:
        self.mode = mode
        if mode == "realtime":
            self.live_squads = frozenset(live_squads) if live_squads is not None else LIVE_SQUADS_DEFAULT
        else:
            self.live_squads = frozenset()

    @staticmethod
    def _is_squad1_id(unit_id: str) -> bool:
        uid = str(unit_id or "")
        return uid == "1" or uid.startswith("1-")

    def _is_hw_unit(self, unit_id: str) -> bool:
        """realtime에서 위치가 단말/라우터에서만 오는 노드 (분대원 relpos)."""
        return self.mode == "realtime" and "1" in self.live_squads and unit_id in HW_RELPOS_UNITS

    def _is_hw_relpos(self, unit_id: str) -> bool:
        """realtime에서 라우터가 보내는 분대원 상대좌표 노드."""
        return self._is_hw_unit(unit_id)

    def _is_live(self, unit_id: str) -> bool:
        """realtime 1분대 전원 — ACK·보고·부상 mock 금지, Arduino만."""
        return self.mode == "realtime" and "1" in self.live_squads and self._is_squad1_id(unit_id)

    def _router_up(self) -> bool:
        """SoftAP/라우터 연결 여부. 끊기면 1-1 mock GPS도 중단."""
        if self.mode != "realtime" or "1" not in self.live_squads:
            return True
        from .router import router_hub
        return router_hub.connected

    def _mock_ingest(self, ev: dict) -> None:
        """시뮬이 넣는 이벤트. realtime에서는 위치·링크·ack 만 허용."""
        if self.mode == "realtime":
            typ = ev.get("type")
            if typ not in _REALTIME_MOCK_OK:
                log.info("realtime: block mock event type=%s (position-only mode)", typ)
                return
        self.s.ingest(ev)

    def _purge_scenario_traffic(self) -> None:
        """realtime 진입 시 시나리오 보고·표적·경보 제거 (위치 mock만 유지)."""
        s = self.s
        n_r, n_t, n_a = len(s.reports), len(s.targets), len(s.alerts)
        for rid in list(s.reports):
            s.remove("reports", rid)
        for tid in list(s.targets):
            s.remove("targets", tid)
        for aid in list(s.alerts):
            s.remove("alerts", aid)
        for uid, u in list(s.units.items()):
            if self._is_squad1_id(uid):
                continue  # 1분대는 곧 nolink 처리
            if u.status != "ok":
                u.status = "ok"
                s.put("units", u)
        if n_r or n_t or n_a:
            log.info("realtime: purged scenario traffic reports=%d targets=%d alerts=%d", n_r, n_t, n_a)

    # -------------------------------------------------------------- 가상 단말: 하향 메시지 응답
    def _later(self, delay: float, ev: dict) -> None:
        loop = asyncio.get_running_loop()
        loop.call_later(delay, lambda: self.running and self._mock_ingest(ev))

    def _on_downlink(self, msg: dict) -> None:
        """realtime: 위치 이동(집결)만 반영. 보고 보완 mock 없음. HQ·2·3은 명령 ACK만."""
        if not self.running:
            return
        t, d = msg["type"], msg["data"]
        if t == "order.new":
            for rid in d.get("recipients", []):
                if self._is_live(rid):
                    continue  # 1분대 — Arduino/bridge ACK
                if self.mode == "realtime" and d.get("code") == "RECHECK":
                    continue  # realtime: RECHECK 보완보고 mock 금지
                u = self.s.units.get(rid)
                if rid in self.offline or (u and u.status == "kia"):
                    continue
                if d["code"] == "RECHECK":
                    self._recheck_reply(d, rid)
                    continue
                self._later(random.uniform(0.6, 3.5), {"type": "ack", "data": {"ref": d["id"], "from": rid}})
            code = d.get("code")
            params = d.get("params") or {}
            if code in ("HALT", "TAKE_COVER"):
                self.halted = True
                if code == "HALT":
                    self._clear_rally("halt")
            elif code in ("MOVE", "RALLY"):
                self.halted = False
                lat, lon = params.get("lat"), params.get("lon")
                if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
                    self.rally_target = (float(lat), float(lon))
                    self.rally_order_id = d.get("id")
                    log.info("mock → %s 목표 %.5f,%.5f", code, lat, lon)
            elif code in ("WEAPONS_HOLD", "WEAPONS_FREE"):
                pass
        elif t == "order.cancel":
            oid = d.get("id")
            o = self.s.orders.get(oid) if oid else None
            if oid and (
                oid == self.rally_order_id
                or (self.rally_target and o and o.code in ("MOVE", "RALLY"))
            ):
                self._clear_rally(f"cancel {oid}")
        elif t == "report.update" and self.mode != "realtime":
            if msg["dst"] not in self.offline and not self._is_live(msg["dst"]):
                self._later(random.uniform(0.8, 2.0), {"type": "ack", "data": {"ref": d["id"], "from": msg["dst"]}})

    def _recheck_reply(self, d: dict, rid: str) -> None:
        if self.mode == "realtime":
            return
        o = self.s.orders.get(d["id"])
        r = self.s.reports.get(o.ref_report) if o and o.ref_report else None
        if not r:
            return
        if r.type == "MEDEVAC":
            amend = dict(fields={"7. 착륙지대 표시": "녹색 연막"},
                         raw_text="착륙지대 표시는 녹색 연막. 이상.")
        elif r.type in ("SPOT", "SALUTE"):
            amend = dict(fields={"activity": "정차, 엔진 가동 중", "unit": "적 경계 차량(추정)"}, conf=0.82,
                         summary=r.summary.replace("차량 추정", "적 경계 차량") if "차량" in r.summary else r.summary,
                         raw_text="재확인 결과 적 차량 맞음. 정차 상태로 엔진 가동 중.")
        else:
            amend = dict(raw_text="재확인 결과 이상 없음.", conf=min(1.0, r.conf + 0.1))
        self._later(random.uniform(5, 8), {"type": "report.amend", "data": {"id": r.id, "from": rid, **amend}})
    # -------------------------------------------------------------- lifecycle
    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self.task = asyncio.create_task(self._run())

    def stop(self) -> None:
        self.running = False
        if self.task:
            self.task.cancel()
            self.task = None

    def restart(self) -> None:
        self.stop()
        self.s.reset()
        self.start()

    # -------------------------------------------------------------- setup
    def _setup(self) -> None:
        s = self.s
        s.ingest({"type": "mission.update", "data": {
            "origin": ROUTE[0], "objective": OBJECTIVE, "route": ROUTE, "phase_lines": PHASE_LINES,
            "name": "Realtime HW 시연" if self.mode == "realtime" else "정찰 시나리오"}})
        for r in ROSTER:
            s.ingest({"type": "unit.upsert", "data": dict(r, battery=random.uniform(70, 100))})
        self.t0 = time.time()
        self.dist = 0.0
        self.offline = set()
        self.halted = False
        self.frozen: dict[str, tuple[float, float]] = {}
        self.drift: dict[str, float] = {}
        self.fired: set[str] = set()
        self.rally_target: tuple[float, float] | None = None
        self.rally_order_id: str | None = None
        self._rejoin_route = False
        self.plat_lat, self.plat_lon, self.plat_hdg = (*ROUTE[0], 0.0)
        if self.mode == "realtime":
            log.info(
                "realtime: position mock only (1-1+HQ/2/3) · 1-2~1-4 Arduino relpos · "
                "no scripted events for any squad"
            )
            self._purge_scenario_traffic()
            if "1" in self.live_squads:
                self.s.mark_units_nolink(NOLINK_ON_DISCONNECT, reason="단말 신호 대기")

    # -------------------------------------------------------------- geometry
    def _route_point(self, dist: float) -> tuple[float, float, float]:
        """경로 상 dist[m] 지점의 (lat, lon, heading). 끝나면 왕복."""
        segs = []
        for a, b in zip(ROUTE, ROUTE[1:]):
            segs.append((a, b, geo.distance(*a, *b)))
        total = sum(L for *_, L in segs)
        dist = dist % (2 * total)
        pts = ROUTE if dist <= total else ROUTE[::-1]
        dist = dist if dist <= total else dist - total
        for a, b in zip(pts, pts[1:]):
            L = geo.distance(*a, *b)
            if dist <= L:
                f = dist / L
                lat = a[0] + (b[0] - a[0]) * f
                lon = a[1] + (b[1] - a[1]) * f
                return lat, lon, geo.bearing(*a, *b)
            dist -= L
        return (*pts[-1], 0.0)

    def _nearest_route_dist(self, lat: float, lon: float) -> float:
        """현재 좌표에 가장 가까운 정찰 경로상 누적 거리 [m] (왕복 구간 제외 편도)."""
        best_d, best_err = 0.0, float("inf")
        acc = 0.0
        for a, b in zip(ROUTE, ROUTE[1:]):
            seg_len = geo.distance(*a, *b)
            if seg_len < 1e-3:
                continue
            e, n = geo.enu(a[0], a[1], lat, lon)
            be, bn = geo.enu(a[0], a[1], b[0], b[1])
            t = max(0.0, min(1.0, (e * be + n * bn) / (be * be + bn * bn)))
            err = math.hypot(e - be * t, n - bn * t)
            if err < best_err:
                best_err = err
                best_d = acc + t * seg_len
            acc += seg_len
        return best_d

    def _clear_rally(self, reason: str = "") -> None:
        """집결/이동 종료 — 현 plat 유지, 경로 진행도만 최근접점으로 맞춤 (순간이동 금지)."""
        if self.rally_target is not None or self.rally_order_id is not None:
            self.dist = self._nearest_route_dist(self.plat_lat, self.plat_lon)
            self._rejoin_route = True
            log.info(
                "mock 집결/이동 종료 → 현위치(%.5f,%.5f)에서 경로 재개 dist=%.0fm (%s)",
                self.plat_lat, self.plat_lon, self.dist, reason,
            )
        self.rally_target = None
        self.rally_order_id = None

    def _step_toward(self, tlat: float, tlon: float, speed: float) -> tuple[float, float, float]:
        """현 plat에서 목표로 speed[m] 만큼 이동. (새 lat, lon, heading)."""
        dist_m = geo.distance(self.plat_lat, self.plat_lon, tlat, tlon)
        if dist_m < 1e-3:
            return tlat, tlon, self.plat_hdg
        hdg = geo.bearing(self.plat_lat, self.plat_lon, tlat, tlon)
        step = min(speed, dist_m)
        rad = math.radians(hdg)
        plat, plon = geo.offset(
            self.plat_lat, self.plat_lon,
            step * math.sin(rad), step * math.cos(rad),
        )
        return plat, plon, hdg

    @staticmethod
    def _body(lat, lon, hdg, x, y):
        h = math.radians(hdg)
        east = x * math.cos(h) + y * math.sin(h)
        north = -x * math.sin(h) + y * math.cos(h)
        return geo.offset(lat, lon, east, north)

    # -------------------------------------------------------------- main loop
    async def _run(self) -> None:
        self._setup()
        tick = 0
        try:
            while self.running:
                self._step(tick)
                self.s.periodic_checks()
                self.s.emit_meta()
                tick += 1
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception("simulator crashed")

    def _step(self, tick: int) -> None:
        s = self.s
        t = time.time() - self.t0
        emcon = s.mission.emcon
        pos_every = 5 if emcon else 1
        link_every = 6 if emcon else 2

        # 위치: 집결/이동 목표가 있으면 그쪽으로, 아니면 정찰 경로
        # 중요: plat 좌표를 _route_point 결과로 직접 대입하지 않음 (철회 시 순간이동 방지)
        if self.rally_target and not self.halted:
            tlat, tlon = self.rally_target
            dist_m = geo.distance(self.plat_lat, self.plat_lon, tlat, tlon)
            if dist_m < 10:
                plat, plon, hdg = self.plat_lat, self.plat_lon, self.plat_hdg
            else:
                plat, plon, hdg = self._step_toward(tlat, tlon, 2.8)
            self.plat_lat, self.plat_lon, self.plat_hdg = plat, plon, hdg
        elif self.halted:
            plat, plon, hdg = self.plat_lat, self.plat_lon, self.plat_hdg
        else:
            if self._rejoin_route:
                tlat, tlon, _ = self._route_point(self.dist)
            else:
                tlat, tlon, _ = self._route_point(self.dist + 1.4)
            plat, plon, hdg = self._step_toward(tlat, tlon, 1.4)
            gap = geo.distance(plat, plon, tlat, tlon)
            if self._rejoin_route:
                if gap < 2.5:
                    self._rejoin_route = False
                    self.dist += 1.4
            else:
                if gap < 3.0:
                    self.dist += 1.4
            self.plat_lat, self.plat_lon, self.plat_hdg = plat, plon, hdg
        hdg_n = hdg + random.gauss(0, 2)

        positions: dict[str, tuple[float, float]] = {}
        router_up = self._router_up()
        # realtime: 1-2~1-4 mock 제외. 1-1 GPS는 Arduino 연결 중에만 mock
        mock_roster = [r for r in ROSTER if not self._is_hw_unit(r["id"])]
        if not router_up:
            mock_roster = [r for r in mock_roster if r["id"] not in MOCK_GPS_UNITS]
        for r in mock_roster:
            uid, sq = r["id"], r["squad"]
            if sq == "HQ":
                x, y = HQ_SLOTS[uid]
            else:
                px, py = PLATOON[sq]
                k = int(uid.split("-")[1]) - 1
                wx, wy = SQUAD_WEDGE[k]
                x, y = px + wx, py + wy
            if self.mode != "realtime" and uid in self.drift:  # 대형 이탈 = scenario만
                x += -self.drift[uid] if x < 0 else self.drift[uid]
            lat, lon = self._body(plat, plon, hdg, x + random.gauss(0, 1.2), y + random.gauss(0, 1.2))
            if self.mode != "realtime" and uid in self.frozen:
                lat, lon = self.frozen[uid]
            positions[uid] = (lat, lon)

        # --- 위치 보고: mock 노드 (1-1은 라우터 연결 시만). 분대원은 HW relpos
        if tick % pos_every == 0:
            for r in mock_roster:
                uid = r["id"]
                if self.mode != "realtime" and uid in self.offline:
                    continue
                lat, lon = positions[uid]
                u = s.units.get(uid)
                bat = max(5.0, (u.battery if u else 100) - random.uniform(0, 0.03))
                if r["role"] in ("pl", "sl", "radio", "medic"):
                    self._mock_ingest({"type": "unit.position", "data": dict(
                        id=uid, lat=lat, lon=lon, heading=hdg_n, err=3.0, source="gps", battery=bat,
                        rssi=rssi_at(geo.distance(*positions["PL"], lat, lon)))})
                else:
                    ref = f"{r['squad']}-1"
                    rlat, rlon = positions[ref]
                    e, n = geo.enu(rlat, rlon, lat, lon)
                    err = random.uniform(3.5, 7.0)
                    self._mock_ingest({"type": "unit.relpos", "data": dict(
                        id=uid, ref=ref, dx=e + random.gauss(0, err / 2), dy=n + random.gauss(0, err / 2),
                        err=err, heading=hdg_n, battery=bat)})

        # --- 메시 링크 (위치 파생). Arduino 연결 시 1분대원 합류
        if tick % link_every == 0:
            ids = [r["id"] for r in mock_roster]
            if self.mode != "realtime":
                ids = [i for i in ids if i not in self.offline]
            if router_up:
                for uid in HW_RELPOS_UNITS:
                    u = s.units.get(uid)
                    if u and u.lat is not None and u.status != "nolink":
                        positions[uid] = (u.lat, u.lon)
                        if uid not in ids:
                            ids.append(uid)
            for i, a in enumerate(ids):
                for b in ids[i + 1:]:
                    if a not in positions or b not in positions:
                        continue
                    d = geo.distance(*positions[a], *positions[b])
                    if d < 55 and random.random() < 0.8:
                        self._mock_ingest({"type": "link.update", "data": dict(a=a, b=b, rssi=rssi_at(d))})

        # realtime: 시나리오 연출 없음
        if self.mode != "realtime":
            self._script(t, positions, hdg)

    # -------------------------------------------------------------- scripted events
    def _once(self, key: str, cond: bool) -> bool:
        if cond and key not in self.fired:
            self.fired.add(key)
            return True
        return False

    def _script(self, t: float, pos: dict, hdg: float) -> None:
        """시나리오 모드 전용 연출. realtime에서는 호출하지 않음.
        1분대 보고·부상은 scenario에서만 mock — realtime은 Arduino 전용.
        """
        if self.mode == "realtime":
            return

        if self._once("salute", t > 20):
            self._mock_ingest({"type": "report.new", "data": dict(
                type="SALUTE", sender="1-1", priority="priority", conf=0.88,
                raw_text="1분대장 보고. 적 보병 3명, 2시 방향 약 150미터, 능선 따라 남쪽으로 이동 중. 소총 휴대.",
                summary="적 보병 3명 · 1분대 2시 150m · 능선 따라 남하",
                fields=dict(size=3, activity="능선 따라 남하", unit="적 보병 분조", time="현재",
                            equipment="소총", kind="infantry",
                            location=dict(bearing=(hdg + 60) % 360, dist=150, err=30)))})
        if self._once("spot", t > 35):
            self._mock_ingest({"type": "report.new", "data": dict(
                type="SPOT", sender="2-3", conf=0.55,
                raw_text="어... 저기 1시 방향에 차량 같은 게 한 대... 정차해 있는 것 같습니다.",
                summary="차량 추정 1대 · 2분대 1시 220m · 정차",
                fields=dict(size=1, activity="정차", kind="vehicle", unit="미상 차량",
                            location=dict(bearing=(hdg + 25) % 360, dist=220, err=60)))})
        if self._once("contact", t > 48):
            self._mock_ingest({"type": "report.new", "data": dict(
                type="CONTACT", sender="1-1", priority="urgent", conf=0.93,
                raw_text="접적! 접적! 1시 방향 사격 받음! 1-3 부상!",
                summary="1분대 접적 — 1시 방향 소화기 사격",
                fields=dict(kind="contact", activity="접적 · 소화기 사격", unit="접적 · 1-1",
                            location=dict(bearing=(hdg + 35) % 360, dist=120, err=25)))})
        if self._once("wia", t > 50):
            if "1-3" in pos:
                self.frozen["1-3"] = pos["1-3"]
            self._mock_ingest({"type": "unit.status", "data": {"id": "1-3", "status": "wia"}})
        if self._once("medevac", t > 56):
            self._mock_ingest({"type": "report.new", "data": dict(
                type="MEDEVAC", sender="1-1", priority="urgent", conf=0.9,
                raw_text="의무후송 요청. 1-3 대퇴부 총상, 긴급 환자 1명, 들것 필요. 적 활동 있음.",
                summary="긴급 환자 1 (1-3 대퇴부 총상) · 들것 1",
                fields={"1. 위치": "1분대 현위치", "2. 호출부호": "메시 C2",
                        "3. 환자/우선순위": "긴급 1", "4. 특수장비": "없음",
                        "5. 환자 유형": "들것 1", "6. 착륙지대 보안": "적 활동 가능 — 무장호송 필요",
                        "7. 착륙지대 표시": None, "8. 환자 국적": "아군 1",
                        "9. 지형/장애물": "능선 남사면"},
                missing=["7. 착륙지대 표시"])})
        if self._once("linkloss", t > 65):
            self.offline.add("3-4")
        if t > 80 and t < 105:
            self.drift["2-3"] = min(55.0, (t - 80) * 3)
        elif "2-3" in self.drift and t >= 105:
            self.drift["2-3"] = max(0.0, self.drift["2-3"] - 4)
            if self.drift["2-3"] == 0:
                del self.drift["2-3"]
        if self._once("linkback", t > 95):
            self.offline.discard("3-4")
        if self._once("sitrep", t > 110):
            self._mock_ingest({"type": "report.new", "data": dict(
                type="SITREP", sender="PL", conf=1.0,
                raw_text="소대 상황보고. PL 알파 통과. 부상 1 후송 대기. 탄약 양호. 계속 전진.",
                summary="PL 알파 통과 · WIA 1 후송 대기 · 탄약 양호 · 전진 계속",
                fields=dict(position="PL 알파 북측", casualties="WIA 1", ammo="양호", intent="목표 지역으로 전진"))})
