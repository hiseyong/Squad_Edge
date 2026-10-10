"""전투 로그: 병사 보고·분대장 명령·수신 확인·분대장 발화·송신한 보고를 시각 순서로 저장 (SQLite).

보고서는 이 로그에서 다시 만들 수 있어야 한다 (재부팅·사후 검토). 기본은 메모리 DB.
개발용 평문 저장이다. 실운용에서는 파일을 암호화하고 소각(crypto-erase) 대상에 넣는다.
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass


@dataclass
class Event:
    ts: float
    kind: str        # "report" | "cmd" | "ack" | "voice" | "sent" | "pos" | "note"
    src: int         # 0 = 분대장, 1~5 = 병사
    data: dict


class CombatLog:
    def __init__(self, path: str = ":memory:"):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS events (ts REAL, kind TEXT, src INTEGER, data TEXT)")
        self.db.execute("CREATE INDEX IF NOT EXISTS events_ts ON events(ts)")

    def add(self, kind: str, src: int, data: dict, ts: float | None = None) -> Event:
        e = Event(time.time() if ts is None else ts, kind, src, data)
        self.db.execute("INSERT INTO events VALUES (?, ?, ?, ?)",
                        (e.ts, e.kind, e.src, json.dumps(e.data, ensure_ascii=False)))
        self.db.commit()
        return e

    def since(self, ts: float = 0.0, kind: str | None = None) -> list[Event]:
        q, args = "SELECT ts, kind, src, data FROM events WHERE ts >= ?", [ts]
        if kind:
            q += " AND kind = ?"
            args.append(kind)
        return [Event(t, k, s, json.loads(d)) for t, k, s, d in self.db.execute(q + " ORDER BY ts", args)]
