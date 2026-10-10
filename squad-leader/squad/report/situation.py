"""상황 집계기: 병사 보고(이진 프로토콜) + 분대 위치 → 적 표적 목록 + 아군 상태. 전부 규칙 기반.

좌표계: 분대장 위치가 원점, x = 동쪽 m, y = 북쪽 m (명세 POS_TABLE과 같음, 단위만 m).

적 표적 융합
- 같은 적을 여러 병사가 보고하면 한 표적으로 묶는다 (안 묶으면 "적 3명"이 세 번 들어와 9명이 된다).
  묶는 기준: 최근 FUSE_WINDOW_S 안에 갱신된 표적 중, 새 보고의 방위선이 표적 추정 위치를 RAY_GATE_M 안으로
  지나가거나 보고 추정점이 POINT_GATE_M 안이면 같은 표적.
- 위치: 서로 다른 병사 2명 이상이 MIN_CROSS_DEG 이상 다른 방위로 보고하면 방위선 교차점(최소제곱)으로 추정.
  아니면 보고자 위치 + 방위 + 거리 대표값(근 50 / 중 100 / 원 200m)의 평균.
- 규모: 보고 중 최댓값 (5 = 5명 이상, 0 = 미상).
- 추세: 같은 병사의 연속 보고에서 거리 구간이 줄면 접근, 늘면 이탈, 방위가 크게 바뀌면 측방 이동.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..protocol import AZ_NONE, Msg

# 병사 거리 구간 대표값: 병사 프로토콜 v1.0.4 이후(시연용 10·20·40m, 구간 경계 15·30m, 없음 20m).
# 오차·묶음 기준도 이전 값(50·100·200m 기준)에서 같은 비율(1/5)로 줄였다.
DIST_REP = {0: 10.0, 1: 20.0, 2: 40.0}
DIST_ERR = {0: 6.0, 1: 10.0, 2: 30.0}         # 거리 구간만으로 추정할 때 오차 (원거리는 "30m 이상")
DIST_ERR_UNKNOWN = 20.0
DIST_UNKNOWN = 20.0
FUSE_WINDOW_S = 300.0        # 도보 이동하는 적을 같은 표적으로 볼 시간
RAY_GATE_M = 20.0
POINT_GATE_M = 30.0
MIN_CROSS_DEG = 15.0
ACTIVE_S = 600.0              # 10분 넘게 갱신 없는 표적은 보고에서 뺀다
SOLDIERS = (1, 2, 3, 4, 5)


def _dir(az: float) -> tuple[float, float]:
    r = math.radians(az)
    return math.sin(r), math.cos(r)


def bearing(x: float, y: float) -> float:
    return math.degrees(math.atan2(x, y)) % 360


def _angle_diff(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


@dataclass
class Sighting:
    ts: float
    sid: int
    origin: tuple[float, float]
    az: float | None
    band: int
    count: int

    def point(self) -> tuple[float, float] | None:
        if self.az is None:
            return None
        d = DIST_REP.get(self.band, DIST_UNKNOWN)
        dx, dy = _dir(self.az)
        return self.origin[0] + d * dx, self.origin[1] + d * dy


def intersect(rays: list[tuple[tuple[float, float], float]]) -> tuple[float, float] | None:
    """방위선들의 최소제곱 교차점. 모든 보고자 앞쪽(t > 0)에 있어야 유효."""
    a11 = a12 = a22 = b1 = b2 = 0.0
    for (px, py), az in rays:
        dx, dy = _dir(az)
        # 수직 투영 행렬 I - d dᵀ
        m11, m12, m22 = 1 - dx * dx, -dx * dy, 1 - dy * dy
        a11 += m11; a12 += m12; a22 += m22
        b1 += m11 * px + m12 * py
        b2 += m12 * px + m22 * py
    det = a11 * a22 - a12 * a12
    if abs(det) < 1e-6:
        return None
    x, y = (a22 * b1 - a12 * b2) / det, (a11 * b2 - a12 * b1) / det
    for (px, py), az in rays:
        dx, dy = _dir(az)
        if (x - px) * dx + (y - py) * dy <= 0:
            return None
    return x, y


def ray_distance(p: tuple[float, float], origin: tuple[float, float], az: float) -> float:
    """점 p에서 origin발 방위선(반직선)까지 거리."""
    dx, dy = _dir(az)
    vx, vy = p[0] - origin[0], p[1] - origin[1]
    t = vx * dx + vy * dy
    if t <= 0:
        return math.hypot(vx, vy)
    return abs(vx * dy - vy * dx)


@dataclass
class EnemyTrack:
    tid: int
    sightings: list[Sighting] = field(default_factory=list)
    pos: tuple[float, float] | None = None
    err_m: float = 0.0
    basis: str = ""                 # "교차 추정(병사 2명)" | "단독 보고" | "방향 미상"

    @property
    def first_t(self) -> float:
        return self.sightings[0].ts

    @property
    def last_t(self) -> float:
        return self.sightings[-1].ts

    @property
    def count(self) -> int:
        """5 = 5명 이상, 0 = 미상."""
        return max(s.count for s in self.sightings)

    @property
    def reporters(self) -> list[int]:
        return sorted({s.sid for s in self.sightings})

    def estimate(self) -> None:
        recent = [s for s in self.sightings if self.last_t - s.ts <= FUSE_WINDOW_S and s.az is not None]
        latest: dict[int, Sighting] = {}
        for s in recent:                                    # 병사마다 가장 최근 방위선 하나
            latest[s.sid] = s
        rays = [(s.origin, s.az) for s in latest.values()]
        spread = max((_angle_diff(a[1], b[1]) for a in rays for b in rays), default=0.0)
        if len(rays) >= 2 and spread >= MIN_CROSS_DEG and (p := intersect(rays)) is not None:
            res = [ray_distance(p, o, az) for o, az in rays]
            self.pos = p
            self.err_m = max(25.0, 2 * math.sqrt(sum(r * r for r in res) / len(res)))
            self.basis = f"교차 추정(병사 {len(rays)}명)"
            return
        pts = [(s.point(), s.band) for s in latest.values() if s.point() is not None]
        if not pts:
            self.pos, self.err_m, self.basis = None, 0.0, "방향 미상"
            return
        self.pos = (sum(p[0] for p, _ in pts) / len(pts), sum(p[1] for p, _ in pts) / len(pts))
        self.err_m = max(DIST_ERR.get(b, DIST_ERR_UNKNOWN) for _, b in pts)
        self.basis = "단독 보고" if len(latest) == 1 else f"병사 {len(latest)}명 보고(같은 방향)"

    def trend(self) -> str | None:
        """같은 병사의 연속 보고로 판정. 근거가 없으면 None."""
        by_sid: dict[int, list[Sighting]] = {}
        for s in self.sightings:
            by_sid.setdefault(s.sid, []).append(s)
        moved = None
        for ss in by_sid.values():
            a, b = ss[0], ss[-1]
            if a is b or b.ts - a.ts < 15:
                continue
            if a.band in DIST_REP and b.band in DIST_REP and b.band != a.band:
                return "접근" if b.band < a.band else "이탈"
            if a.az is not None and b.az is not None and _angle_diff(a.az, b.az) >= 20:
                moved = "측방 이동"
        return moved


@dataclass
class SoldierState:
    sid: int
    pos: tuple[float, float] | None = None      # 분대장 기준 동·북 m
    heading: int | None = None
    last_rx: float | None = None
    casualty_t: float | None = None
    ammo_t: float | None = None
    ok_t: float | None = None
    link_lost_t: float | None = None            # BLE 연결이 끊긴 시각 (명세 v1은 생존 신호가 없어 무보고 ≠ 두절)
    silent: bool = False                        # EMCON 0 (침묵): 연결 없음이 정상


@dataclass
class Point:
    """위치가 있는 단건 보고 (폭발물 의심, 아군 부상자 발견, 의심 징후)."""
    ts: float
    sid: int
    kind: str
    pos: tuple[float, float] | None
    err_m: float


class Situation:
    def __init__(self):
        self.soldiers = {i: SoldierState(i) for i in SOLDIERS}
        self.tracks: list[EnemyTrack] = []
        self.points: list[Point] = []
        self._next_tid = 1

    # ---- 입력 ----

    def set_positions(self, entries: list[tuple[int, float, float, int | None]]) -> None:
        """[(병사 id, 동 m, 북 m, 방위)] — 시연은 POS_TABLE 프리셋, 실전은 RSSI/UWB + GPS 추정 결과."""
        for sid, x, y, hd in entries:
            if sid in self.soldiers:
                self.soldiers[sid].pos = (x, y)
                self.soldiers[sid].heading = hd

    def on_report(self, sid: int, msg_type: int, f: dict, ts: float) -> list[str]:
        """병사 보고 하나 반영. 보고 계기가 되는 사건 이름들을 돌려준다 (new_contact, casualty, ...)."""
        st = self.soldiers.get(sid)
        if st is None:
            return []
        st.last_rx = ts
        origin = st.pos or (0.0, 0.0)
        az = None if f.get("azimuth", AZ_NONE) == AZ_NONE else float(f["azimuth"])
        events: list[str] = []
        if msg_type == Msg.CONTACT:
            s = Sighting(ts, sid, origin, az, f.get("dist_band", 0xFF), f.get("count", 0))
            tr = self._associate(s)
            if tr is None:
                tr = EnemyTrack(self._next_tid)
                self._next_tid += 1
                self.tracks.append(tr)
                events.append("new_contact")
            else:
                before = (tr.count, self._range(tr))
                events += self._big_change(tr, s, before)
            tr.sightings.append(s)
            tr.estimate()
        elif msg_type == Msg.CASUALTY_SELF:
            if st.casualty_t is None:
                events.append("casualty")
            st.casualty_t = ts
        elif msg_type == Msg.WEAPON_AMMO:
            if st.ammo_t is None or (st.ok_t and st.ok_t > st.ammo_t):
                events.append("ammo")
            st.ammo_t = ts
        elif msg_type == Msg.OK_READY:
            st.ok_t = ts
        elif msg_type in (Msg.HAZARD, Msg.CASUALTY_FOUND, Msg.SUSPICIOUS):
            band = f.get("dist_band", 0 if msg_type == Msg.HAZARD else 0xFF)
            pos = Sighting(ts, sid, origin, az, band, 0).point()
            kind = {Msg.HAZARD: "폭발물 의심", Msg.CASUALTY_FOUND: "아군 부상자", Msg.SUSPICIOUS: "의심 징후"}[msg_type]
            self.points.append(Point(ts, sid, kind, pos, DIST_ERR.get(band, DIST_ERR_UNKNOWN)))
            events.append({Msg.HAZARD: "hazard", Msg.CASUALTY_FOUND: "casualty", Msg.SUSPICIOUS: "suspicious"}[msg_type])
        return events

    def set_link(self, sid: int, connected: bool, ts: float, silent: bool = False) -> list[str]:
        """BLE 계층이 알려주는 연결 상태. 침묵 모드 전환으로 끊긴 것은 두절이 아니다."""
        st = self.soldiers.get(sid)
        if st is None:
            return []
        st.silent = silent
        was_lost = st.link_lost_t is not None
        st.link_lost_t = None if connected or silent else (st.link_lost_t or ts)
        return ["link_lost"] if st.link_lost_t is not None and not was_lost else []

    def heard(self, sid: int, ts: float) -> None:
        """보고 외 프레임(ACK, HEARTBEAT 등)도 생존 신호로 친다."""
        if sid in self.soldiers:
            self.soldiers[sid].last_rx = ts

    # ---- 융합 ----

    def _associate(self, s: Sighting) -> EnemyTrack | None:
        best, best_d = None, float("inf")
        for tr in self.tracks:
            if s.ts - tr.last_t > FUSE_WINDOW_S:
                continue
            if s.az is None or tr.pos is None:
                d = 0.0 if s.az is None else float("inf")    # 방향 없는 보고는 가장 최근 표적에 붙인다
            else:
                ray, pt = ray_distance(tr.pos, s.origin, s.az), math.dist(tr.pos, s.point())
                d = min(ray if ray <= RAY_GATE_M else float("inf"), pt if pt <= POINT_GATE_M else float("inf"))
            if d < best_d:
                best, best_d = tr, d
        return best

    @staticmethod
    def _range(tr: EnemyTrack) -> float | None:
        return math.hypot(*tr.pos) if tr.pos else None

    def _big_change(self, tr: EnemyTrack, s: Sighting, before) -> list[str]:
        """규모 2배 이상, 또는 거리 절반 이하 → 새 보고 계기."""
        count0, range0 = before
        ev = []
        if count0 and s.count >= 2 * count0:
            ev.append("contact_grew")
        p = s.point()
        if range0 and p and math.hypot(*p) <= range0 / 2:
            ev.append("contact_closer")
        return ev

    # ---- 조회 ----

    def active_tracks(self, now: float) -> list[EnemyTrack]:
        return sorted((t for t in self.tracks if now - t.last_t <= ACTIVE_S), key=lambda t: -t.last_t)

    def friendly(self, now: float) -> dict:
        cas = [s.sid for s in self.soldiers.values() if s.casualty_t is not None]
        ammo = [s.sid for s in self.soldiers.values()
                if s.ammo_t is not None and not (s.ok_t and s.ok_t > s.ammo_t) and now - s.ammo_t <= 900]
        lost = [s.sid for s in self.soldiers.values() if s.link_lost_t is not None and s.sid not in cas]
        silent = [s.sid for s in self.soldiers.values() if s.silent]
        return {"total": len(self.soldiers), "available": len(self.soldiers) - len(set(cas) | set(lost)),
                "casualties": cas, "ammo_issue": ammo, "lost": lost, "silent": silent}
