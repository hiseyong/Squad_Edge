"""병사 보고 재전송 판정 (가이드 f-4 권장 방식).

병사 seq는 부팅마다 0부터라 seq만 보면 재부팅 뒤 새 보고를 재전송으로 오인한다(mock_leader의 알려진 한계).
그래서 (병사, seq, **프레임 바이트 동일**, 60초 안)일 때만 재전송으로 보고, 연결이 새로 맺어지면 그 병사 기록을 비운다.
재전송이어도 RPT_ACK는 다시 보낸다(§5.2). 재전송은 다시 중계하지 않는다(§5.2 PEER_REPORT).
"""
from __future__ import annotations

from . import config


class ReportDedup:
    def __init__(self, window_s: float = config.REPORT_DEDUP_S):
        self.window_s = window_s
        self._seen: dict[int, dict[int, tuple[bytes, float]]] = {}

    def is_retransmit(self, sid: int, raw: bytes, now: float) -> bool:
        """처음 본 보고면 기록하고 False, 재전송이면 True."""
        raw = bytes(raw)
        seq = raw[2]
        per = self._seen.setdefault(sid, {})
        old = per.get(seq)
        if old is not None and old[0] == raw and now - old[1] <= self.window_s:
            return True
        per[seq] = (raw, now)
        for s in [s for s, (_, t) in per.items() if now - t > self.window_s]:
            del per[s]
        return False

    def reset(self, sid: int) -> None:
        """새 연결: 병사가 재부팅했을 수 있으니 기록을 비운다."""
        self._seen.pop(sid, None)
