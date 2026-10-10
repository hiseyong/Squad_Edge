"""분대장 보드 ↔ 소대장 노트북(Squad Edge COP) 링크: 보드 SoftAP + TCP NDJSON 서버.

규격은 팀 COP와 맞춘다 (leader-q3/host/bridge_server.py 기준, 2026-10-10 수령):
  - 보드가 Wi-Fi AP(기본 SSID SquadEdge-1-1, 192.168.4.1)를 열고 TCP :9000 에서 대기, 노트북이 접속한다.
  - 한 줄에 JSON 하나(NDJSON). 접속하면 router.hello, 이후 period_s마다 unit.position(분대장) + unit.relpos(분대원).
  - 상향: report.new(분대장 정형 보고 sq-rpt/0.1, 적 발견 자동 보고 CONTACT) / ack
  - 하향: order.new, mission.update, report.ack/query/update — 분대장에게 알리기만 한다.
  - ID: 분대장 = "{squad}-1", 분대원 n번 = "{squad}-{n+1}"

분리 원칙(2026-10-11 사용자 지시): 이 모듈은 분대장 ↔ 병사 프로토콜·통신을 모른다(import하지 않는다).
  - 소대장 지시를 병사에게 자동으로 넘기지 않는다(분대장이 듣고 판단해 하달).
  - 병사와 소대장은 직접 연결되지 않는다. 분대원 위치는 분대장이 받아 정리한 값(분대장 기준 동·북 m)을
    분대장 앱이 Telemetry.members로 넘겨 주면 이 링크가 주기적으로 중계한다.
  - 병사 보고는 소대장에게 자동으로 보내지 않는다. 분대장이 정형 보고서를 보낼 때만 그 안에 반영된다(squad/report).
    예외(2026-10-11 사용자 지시): 적 발견은 분대장 앱이 분대장 기준 위치로 바꿔 즉시 자동 보고한다(contact_event).
    보내는 쪽은 언제나 분대장(sender = "{squad}-1"), 발견자는 observer로만 적는다.

보안: 기본으로 AP 주소에만 바인드한다 (회장 Wi-Fi 등 다른 망에 노출하지 않음). v1에는 인증이 없다.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from dataclasses import dataclass
from typing import Any, Callable


log = logging.getLogger(__name__)

AP_IP = "192.168.4.1"
PORT = 9000

def member_uid(squad: str, n: int) -> str:
    """분대원 n번(1~5) → 소대장 쪽 ID "{squad}-{n+1}" (분대장이 "{squad}-1")."""
    return f"{squad}-{n + 1}"


def ev(typ: str, data: dict, src: str | None = None, nbytes: int | None = None) -> dict:
    e: dict[str, Any] = {"v": 1, "type": typ}
    if src:
        e.update(src=src, dst="PL")
    if nbytes is not None:
        e["bytes"] = nbytes                 # 무선 구간 예상 크기 (COP 표시용)
    e["data"] = data
    return e


def contact_event(squad: str, observer: str, loc: dict, count: int | None, ts: float, kind: str = "infantry",
                  seq: int | None = None) -> dict:
    """적 발견 자동 보고(초안, 팀 COP reports.py의 CONTACT 모양에 맞춤).
    loc: 분대장 기준 {"bearing", "dist", "err", "dx", "dy", "mgrs"?, "basis"} — 위치는 sender(분대장)에서 본 값."""
    me = f"{squad}-1"
    size = None if not count else count
    who = "분대장" if observer == me else observer
    clock = ((int(loc["bearing"]) + 15) // 30) % 12 or 12
    summary = f"적 {'다수' if size == 5 else f'{size}명' if size else '규모 미상'} 분대장 기준 {clock}시 {round(loc['dist'])}m (발견 {who})"
    return ev("report.new", {
        "type": "CONTACT", "sender": me, "observer": observer, "priority": "urgent", "conf": 0.8 if observer != me else 0.9,
        "summary": summary, "ts": round(ts, 1), "seq": seq,
        "fields": {"kind": kind, "activity": "접적", "size": size,
                   "location": {"bearing": int(loc["bearing"]), "dist": round(loc["dist"]), "err": round(loc["err"]),
                                "ref": me, "dx": round(loc.get("dx", 0.0), 1), "dy": round(loc.get("dy", 0.0), 1),
                                "mgrs": loc.get("mgrs"), "basis": loc.get("basis")}},
        "missing": []}, src=me, nbytes=48)


def battle_event(squad: str, b: dict) -> dict:
    """전투 데이터 보고(전투 종료 뒤, 초안 sq-battle/0.1): 요약·회의록 텍스트 + 전체 기록 압축본."""
    me = f"{squad}-1"
    return ev("report.new", {"type": "BATTLE_DATA", "sender": me, "priority": "routine", "conf": 1.0,
                             "summary": b["summary"], "text": b["text"], "fmt": b["fmt"], "battle_id": b["battle_id"],
                             "result": b["result"], "payload": b["payload"], "missing": []},
              src=me, nbytes=b["payload"]["bytes"] + len(b["text"].encode()))


def report_event(squad: str, data: dict) -> dict:
    """sq-rpt/0.1 보고 data(desk.send 결과) → report.new 봉투."""
    return ev("report.new", data, src=f"{squad}-1", nbytes=len(data.get("text", "").encode()))


def sitrep_event(squad: str, report) -> dict:
    """squad.report.compose.Report(양식화된 상황 보고) → report.new. 형식은 초안(draft-1)."""
    d = {k: v for k, v in report.data.items() if k != "_full"}
    prio = {"FLASH": "flash", "IMMEDIATE": "urgent", "PRIORITY": "priority"}.get(report.prec, "routine")
    enemy = d.get("enemy") or []
    loc = None
    if enemy and enemy[0].get("rel_m"):
        x, y = enemy[0]["rel_m"]
        loc = {"bearing": round(math.degrees(math.atan2(x, y)) % 360), "dist": round(math.hypot(x, y)),
               "err": enemy[0].get("err_m"), "mgrs": enemy[0].get("mgrs"), "ref": f"{squad}-1"}
    return ev("report.new", {
        "type": d.get("type", "SITREP"), "sender": f"{squad}-1", "priority": prio, "conf": 1.0,
        "summary": report.summary, "text": report.text(),
        "fields": {"location": loc, "size": enemy[0]["count"] if enemy else None,
                   "activity": ", ".join(enemy[0]["activity"]) if enemy else None,
                   "friendly": d.get("friendly"), "action": d.get("action"), "requests": d.get("requests"),
                   "judgment": d.get("judgment"), "enemy": enemy, "points": d.get("points")},
        "missing": report.prompts, "format": d.get("v")}, src=f"{squad}-1", nbytes=len(report.text().encode()))


@dataclass
class Telemetry:
    """분대장 위치 + 분대원 상대 위치(분대장 원점, 동·북 m). 분대원 위치는 분대장 앱이 채워 넘긴다."""
    lat: float
    lon: float
    heading: float = 0.0
    err: float = 3.0
    battery: int = 90
    source: str = "gps"
    members: dict | None = None   # 분대원 번호 → (dx, dy, heading[, err]). 위치를 모르는 분대원은 넣지 않는다


def telemetry_events(squad: str, t: Telemetry) -> list[dict]:
    me = f"{squad}-1"
    out = [ev("unit.position", {"id": me, "lat": t.lat, "lon": t.lon, "heading": t.heading, "err": t.err,
                                "source": t.source, "battery": t.battery}, src=me, nbytes=18)]
    for n, m in sorted((t.members or {}).items()):
        dx, dy, hd = m[:3]
        err = m[3] if len(m) > 3 else 5.0
        out.append(ev("unit.relpos", {"id": member_uid(squad, n), "ref": me, "dx": dx, "dy": dy, "err": err,
                                      "heading": hd, "battery": t.battery}, src=me, nbytes=14))
    return out


class CopServer:
    """노트북(COP) 접속을 받아 상향 이벤트를 방송하고 하향 명령을 처리한다.

    telemetry(): 주기 상향에 쓸 Telemetry를 돌려주는 함수
    on_order(order): 소대장 지시 → 분대장 헤드셋 알림 (병사에게 넘기지 않는다)
    on_mission(data): 임무 변경(EMCON 등) → 분대장 헤드셋 알림
    on_order_cancel(data): 소대장 지시 취소 → 분대장 헤드셋·OLED
    members: 소대장 화면에 위치를 띄울 분대원 번호(hello의 hw_relpos)
    """

    def __init__(self, squad: str = "1", host: str = AP_IP, port: int = PORT, period_s: float = 1.0,
                 telemetry: Callable[[], Telemetry] | None = None,
                 on_order: Callable[[dict], None] | None = None,
                 on_mission: Callable[[dict], None] | None = None,
                 on_order_cancel: Callable[[dict], None] | None = None,
                 members: tuple[int, ...] = (1, 2, 3),
                 on_report_ack: Callable[[dict], None] | None = None,
                 on_report_query: Callable[[dict], list[dict]] | None = None):
        self.squad, self.host, self.port, self.period = squad, host, port, period_s
        self.telemetry, self.on_order, self.on_mission, self.members = telemetry, on_order, on_mission, members
        self.on_order_cancel = on_order_cancel
        self.on_report_ack, self.on_report_query = on_report_ack, on_report_query
        self.clients: set[asyncio.StreamWriter] = set()
        self.rx_log: list[dict] = []
        self.server: asyncio.base_events.Server | None = None

    @property
    def node(self) -> str:
        return f"{self.squad}-1"

    async def start(self) -> None:
        self.server = await asyncio.start_server(self._handle, self.host, self.port)
        log.info("COP 링크 대기 %s:%d", self.host, self.port)

    async def close(self) -> None:
        for w in list(self.clients):
            w.close()
        if self.server:
            self.server.close()
            try:                                    # 노트북이 연결을 안 끊으면 영원히 기다리므로 시간 제한
                await asyncio.wait_for(self.server.wait_closed(), 2.0)
            except asyncio.TimeoutError:
                pass

    async def send(self, events: list[dict]) -> int:
        """모든 접속 노트북에 방송. 보낸 노트북 수."""
        if not events or not self.clients:
            return 0
        payload = "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events).encode()
        n = 0
        for w in list(self.clients):
            try:
                w.write(payload)
                await w.drain()
                n += 1
            except (ConnectionError, OSError):
                self.clients.discard(w)
        return n

    def hello(self) -> dict:
        return ev("router.hello", {"role": "squad_leader", "node": self.node, "squad": self.squad,
                                   "hw_gps": [self.node], "hw_relpos": [member_uid(self.squad, n) for n in self.members],
                                   "period_s": self.period, "ap_ip": self.host, "transport": "tcp-ndjson",
                                   "report_format": "sq-rpt/0.1"}, src=self.node)

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        log.info("COP 접속 %s", peer)
        self.clients.add(writer)
        try:
            writer.write((json.dumps(self.hello(), ensure_ascii=False) + "\n").encode())
            await writer.drain()
            tx = asyncio.create_task(self._telemetry_loop(writer))
            try:
                while raw := await reader.readline():
                    line = raw.decode("utf-8", "ignore").strip()
                    if not line.startswith("{"):
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        log.warning("잘못된 JSON: %s", line[:120])
                        continue
                    replies = self.downlink(obj)
                    if replies:
                        writer.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in replies).encode())
                        await writer.drain()
            finally:
                tx.cancel()
        except (ConnectionError, OSError) as e:
            log.info("COP 연결 끊김 %s: %s", peer, e)
        finally:
            self.clients.discard(writer)
            writer.close()
            log.info("COP 종료 %s", peer)

    async def _telemetry_loop(self, writer: asyncio.StreamWriter) -> None:
        while self.telemetry is not None:
            evs = telemetry_events(self.squad, self.telemetry())
            writer.write("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in evs).encode())
            await writer.drain()
            await asyncio.sleep(self.period)

    def downlink(self, obj: dict) -> list[dict]:
        """하향 하나 처리 → 노트북에 돌려줄 응답들."""
        typ, data = obj.get("type"), obj.get("data") or {}
        self.rx_log.append({"ts": time.time(), **obj})
        log.info("↓ %s %s", typ, json.dumps(data, ensure_ascii=False)[:160])
        if typ == "order.new":                      # 분대장에게 알리기만 한다(병사 하달은 분대장 판단)
            if self.on_order:                       # 봉투의 ts·prio도 함께(재연결 재생이면 data.replay = true)
                self.on_order({**data, "ts": obj.get("ts"), "prio": obj.get("prio")})
            return [ev("ack", {"ref": data.get("id"), "from": self.node, "ok": True})]
        if typ == "order.cancel":
            if self.on_order_cancel:
                self.on_order_cancel(data)
            return []
        if typ == "mission.update":
            if self.on_mission:
                self.on_mission(data)
            return [ev("ack", {"ref": data.get("id"), "from": self.node, "ok": True})]
        if typ == "report.ack":                      # sq-rpt/0.1 §7
            if self.on_report_ack:
                self.on_report_ack(data)
            return []
        if typ == "report.query":
            return self.on_report_query(data) if self.on_report_query else []
        if typ == "report.update":
            return [ev("ack", {"ref": data.get("id"), "from": obj.get("dst") or self.node, "ok": True})]
        return []
