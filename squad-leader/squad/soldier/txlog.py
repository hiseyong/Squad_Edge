"""병사 링크 송수신 기록 — mock_leader `--log-csv`와 같은 CSV 열(S2 비교, tools/tx_summary.py·fit_pathloss.py 호환).

포팅 원본: ~/work/soldier-node_ref_v1.1/tools/mock_leader.py (Leader.open_csv/record, handle("mark"))
열: time, t_s, dir(rx|tx|mark), soldier, type, name, seq, src, dst, len, hex
"""
from __future__ import annotations

import csv
import datetime
import time
from pathlib import Path

from . import codec as fc

COLUMNS = ["time", "t_s", "dir", "soldier", "type", "name", "seq", "src", "dst", "len", "hex"]


class TxLog:
    def __init__(self, path: str | Path | None):
        self.t0 = time.monotonic()
        self._f = self._w = None
        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            self._f = open(path, "w", newline="", encoding="utf-8")
            self._w = csv.writer(self._f)
            self._w.writerow(COLUMNS)

    def record(self, direction: str, sid, raw: bytes) -> None:
        if self._w is None:
            return
        raw = bytes(raw)
        t = raw[1] if len(raw) > 1 else -1
        self._w.writerow([datetime.datetime.now().isoformat(timespec="milliseconds"), f"{time.monotonic() - self.t0:.3f}",
                          direction, sid, f"0x{t:02X}" if t >= 0 else "", fc.MSG_NAMES.get(t, "?"),
                          raw[2] if len(raw) > 2 else "", raw[3] if len(raw) > 3 else "",
                          f"0x{raw[4]:02X}" if len(raw) > 4 else "", len(raw), raw.hex()])
        self._f.flush()

    def mark(self, value: str) -> None:
        """거리 보정 구간 표시(fit_pathloss.py가 읽음). value = 실제 거리 m 또는 '-'."""
        if self._w is None:
            return
        self._w.writerow([datetime.datetime.now().isoformat(timespec="milliseconds"), f"{time.monotonic() - self.t0:.3f}",
                          "mark", "", "", value, "", "", "", 0, ""])
        self._f.flush()

    def close(self) -> None:
        if self._f:
            self._f.close()
