"""RANGING/비콘 RSSI → MDS → POS_TABLE 항목 (soldier-node squad_localize 기반)."""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import Any

_LIB = Path(__file__).resolve().parents[1] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

import squad_localize as sl  # noqa: E402

log = logging.getLogger("q3.localize")

RANGING_STALE_S = 30.0
RSSI_WINDOW = 15
MIN_LEADER_SAMPLES = 3


def _median(vals: list[int]) -> int:
    s = sorted(vals)
    n = len(s)
    if n == 0:
        return 0
    return s[n // 2] if n % 2 else int((s[n // 2 - 1] + s[n // 2]) / 2)


class LocalizeEngine:
    """병사 RANGING + (선택) 분대장 줄 비콘 RSSI → 위치 복원."""

    def __init__(
        self,
        *,
        formation: str = "wedge",
        p1m: float = -59.0,
        n: float = 2.0,
    ) -> None:
        self.formation = formation
        self.p1m = p1m
        self.path_n = n
        # ranging[sid] = {peer_id: (rssi, samples, mono_ts)}
        self.ranging: dict[int, dict[int, tuple[int, int, float]]] = {}
        # leader_rssi[sid] = [(mono_ts, rssi), ...]  보드 A BCN 또는 자체 스캔
        self.leader_rssi: dict[int, list[tuple[float, int]]] = {}
        self.headings: dict[int, int] = {}
        self.pos: dict[int, tuple[float, float]] = {}  # m, ENU, 분대장 원점
        self.last_info: dict[str, Any] = {}

    def note_ranging(self, sid: int, peers: list[dict[str, Any]]) -> None:
        now = time.monotonic()
        self.ranging[sid] = {
            int(p["peer_id"]): (int(p["rssi_avg"]), int(p["samples"]), now) for p in peers
        }

    def note_heading(self, sid: int, heading: int) -> None:
        if heading != 0xFFFF:
            self.headings[sid] = int(heading) % 360

    def note_leader_beacon(self, src: int, rssi: int, heading: int | None = None) -> None:
        """보드 A(LeaderBeacon) `BCN <src> <rssi> <heading>` 또는 자체 스캔."""
        if not 1 <= src <= 5:
            return
        now = time.monotonic()
        v = self.leader_rssi.setdefault(src, [])
        if v and now - v[-1][0] > RANGING_STALE_S:
            v.clear()
        v.append((now, int(rssi)))
        del v[:-RSSI_WINDOW]
        if heading is not None and heading != 0xFFFF:
            self.headings[src] = int(heading) % 360

    def leader_row(self) -> dict[int, int]:
        now = time.monotonic()
        row: dict[int, int] = {}
        for sid, v in self.leader_rssi.items():
            if v and now - v[-1][0] <= RANGING_STALE_S and len(v) >= MIN_LEADER_SAMPLES:
                row[sid] = _median([r for _, r in v])
        return row

    def rssi_rows(self) -> dict[int, dict[int, int]]:
        now = time.monotonic()
        rows: dict[int, dict[int, int]] = {}
        for sid, peers in self.ranging.items():
            r = {p: v[0] for p, v in peers.items() if now - v[2] <= RANGING_STALE_S}
            if r:
                rows[sid] = r
        lr = self.leader_row()
        if lr:
            rows[0] = lr
        return rows

    def compute(
        self,
        *,
        connected: set[int] | None = None,
        mode: str = "auto",
    ) -> tuple[dict[int, tuple[float, float]], list[dict[str, Any]]]:
        """mode=auto|wedge|line|column. 반환 (pos_m, POS_TABLE entries)."""
        connected = connected or set()
        if mode in ("wedge", "line", "column"):
            self.formation = mode
            pos = sl.preset_positions(mode)
            info = {"method": "preset", "formation": mode, "measured": 0, "pairs": 0}
        else:
            rows = self.rssi_rows()
            ids = sorted(
                {0}
                | set(connected)
                | set(rows)
                | {j for r in rows.values() for j in r if j <= 5}
            )
            meas = sl.measured_from_rssi(rows, self.p1m, self.path_n)
            pos, info = sl.localize(ids, meas, self.formation)
            log.info(
                "localize %s measured %s/%s stress=%.1f",
                info.get("method"),
                info.get("measured"),
                info.get("pairs"),
                info.get("stress", 0.0),
            )
        self.pos = dict(pos)
        self.last_info = info
        entries = sl.to_pos_table(pos, self.headings)
        return pos, entries

    def members_relpos_m(self, ble_ids: list[int] | None = None) -> list[dict[str, Any]]:
        """COP unit.relpos 용: [{ble_id, dx, dy, err, heading}]."""
        if not self.pos:
            self.compute(mode=self.formation)
        out = []
        ids = ble_ids if ble_ids is not None else [i for i in sorted(self.pos) if i != 0]
        stress = float(self.last_info.get("stress") or 5.0)
        err = max(3.5, min(12.0, stress + 3.0))
        for i in ids:
            if i not in self.pos:
                continue
            x, y = self.pos[i]
            out.append({
                "ble_id": i,
                "dx": x,
                "dy": y,
                "err": err,
                "heading": self.headings.get(i, self.headings.get(0, 0)),
            })
        return out

    def reporter_xy_dm(self, ble_id: int) -> tuple[int, int]:
        """PEER_REPORT 용 0.1m 좌표. 없으면 POS_UNKNOWN."""
        if ble_id not in self.pos:
            return -32768, -32768  # frame_codec.POS_UNKNOWN
        x, y = self.pos[ble_id]
        return (
            max(-32768, min(32767, int(round(x * 10)))),
            max(-32768, min(32767, int(round(y * 10)))),
        )
