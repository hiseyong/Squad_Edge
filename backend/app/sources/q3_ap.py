"""Arduino UNO Q SoftAP (분대장1) TCP 클라이언트.

보드가 Wi-Fi AP(기본 192.168.4.1)를 열고 TCP :9000 NDJSON 세션을 제공한다.
노트북은 해당 AP에 조인한 뒤 이 모듈이 보드로 connect 한다.

  환경변수
    COP_Q3=1                         활성
    COP_Q3_HOST=192.168.4.1          보드 AP IP
    COP_Q3_PORT=9000
    COP_Q3_RECONNECT_S=3

  상향: unit.relpos / report.new(draft-1) / ack … → store.ingest
         (1-1 unit.position·link.update 는 COP mock — 무시)
  하향: downlink 구독 → 보드로 NDJSON 송신 (order.new / haptic / …)
         연결 직후 활성 1분대 명령 재전송
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any

from .ingest_util import normalize_event, should_ingest_hw_event
from .router import NOLINK_ON_DISCONNECT, router_hub

log = logging.getLogger("cop.q3_ap")

LINK_NAME = "q3-ap"
SQUAD = "1"
_hello: dict[str, Any] = {}
_tx_count = 0
_tx_last: float | None = None


def _squad1_ids(pool: list[Any]) -> list[str]:
    """1분대 관련이면 분대장(1-1)만. 분대원 개인 ID는 승격."""
    for r in pool:
        rs = str(r)
        if rs in ("*", SQUAD) or rs.startswith(f"{SQUAD}-"):
            return [f"{SQUAD}-1"]
    return []


def _affects_squad1(msg: dict[str, Any]) -> bool:
    """1분대(SoftAP 보드)로 보낼 하향인지."""
    typ = msg.get("type")
    if typ == "mission.update":
        return True
    dst = str(msg.get("dst") or "")
    if dst == SQUAD or dst.startswith(f"{SQUAD}-"):
        return True
    data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
    pool = list(data.get("recipients") or []) or list(data.get("to") or [])
    if dst == "*":
        if not pool:
            return True
        return bool(_squad1_ids(pool))
    return False


def _replay_lines(store) -> list[str]:
    """연결 직후: recent 하향 + store에 남은 1분대 미ACK 명령 재송출 (text 포함)."""
    from ..downlink import downlink, order_new_data

    out: list[str] = []
    seen_order: set[str] = set()

    for msg in list(downlink.recent):
        if not isinstance(msg, dict) or not _affects_squad1(msg):
            continue
        typ = msg.get("type")
        if typ not in ("order.new", "order.cancel", "mission.update", "report.update"):
            continue  # haptic 재전송은 스킵 (주문만)
        if typ == "order.new":
            oid = (msg.get("data") or {}).get("id")
            if oid:
                seen_order.add(str(oid))
        out.append(json.dumps(msg, ensure_ascii=False))

    for o in store.orders.values():
        if o.status not in ("sent", "partial"):
            continue
        if o.id in seen_order:
            continue
        targets = _squad1_ids(list(o.recipients))
        if not targets:
            continue
        msg = {
            "v": 1, "type": "order.new", "src": "PL", "dst": "*",
            "seq": 0, "ts": time.time(), "prio": o.priority, "ack": True, "ttl": 3,
            "data": order_new_data(o, targets, replay=True),
        }
        out.append(json.dumps(msg, ensure_ascii=False))

    return out


def _tx_summary(msg: dict[str, Any]) -> str:
    """TX 로그용 한 줄 요약 (명령 텍스트 확인용)."""
    typ = msg.get("type") or "?"
    data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
    if typ == "order.new":
        text = str(data.get("text") or "")
        if len(text) > 80:
            text = text[:77] + "…"
        return f"order.new id={data.get('id')} code={data.get('code')} text={text!r}"
    if typ == "order.cancel":
        return f"order.cancel id={data.get('id')} code={data.get('code')} reason={data.get('reason')}"
    return str(typ)


async def start_q3_ap(store) -> asyncio.Task | None:
    """COP_Q3=1 이면 백그라운드 태스크 시작. 아니면 None."""
    if os.getenv("COP_Q3", "0").strip().lower() not in ("1", "true", "yes", "on"):
        return None
    host = os.getenv("COP_Q3_HOST", "192.168.4.1").strip()
    port = int(os.getenv("COP_Q3_PORT", "9000"))
    retry = float(os.getenv("COP_Q3_RECONNECT_S", "3"))
    task = asyncio.create_task(_run_forever(store, host, port, retry), name="q3-ap")
    log.info("Q3 AP client enabled → %s:%d (downlink Mac→Arduino)", host, port)
    return task


async def _run_forever(store, host: str, port: int, retry: float) -> None:
    while True:
        try:
            await _session(store, host, port)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("Q3 AP session ended: %s (%.0fs 후 재시도)", e, retry)
        finally:
            was = router_hub.detach_link(LINK_NAME)
            if was and not router_hub.connected:
                store.mark_units_nolink(NOLINK_ON_DISCONNECT, reason="Q3 AP 연결 없음")
                log.info("Q3 AP offline → mark nolink %s", list(NOLINK_ON_DISCONNECT))
        await asyncio.sleep(retry)


async def _session(store, host: str, port: int) -> None:
    global _tx_count, _tx_last
    from ..downlink import downlink

    # connect 전에 구독 — 핸드셰이크 중 발행된 명령을 큐에 모아 연결 직후 TX
    q = downlink.subscribe()
    reader = writer = None
    down_task: asyncio.Task | None = None
    try:
        log.info("connecting Q3 AP %s:%d …", host, port)
        reader, writer = await asyncio.open_connection(host, port)
        router_hub.attach_link(LINK_NAME)
        log.info("Q3 AP connected — downlink pump on (order text → SoftAP NDJSON)")

        async def send_line(line: str) -> None:
            global _tx_count, _tx_last
            if not line.endswith("\n"):
                line += "\n"
            writer.write(line.encode("utf-8"))
            await writer.drain()
            _tx_count += 1
            _tx_last = time.time()

        # 연결 직후: 미전달·미완료 1분대 하향 재전송 (명령 텍스트 포함)
        replay = _replay_lines(store)
        for line in replay:
            try:
                msg = json.loads(line)
                log.info("Q3 ↓ replay %s", _tx_summary(msg) if isinstance(msg, dict) else "?")
            except json.JSONDecodeError:
                pass
            await send_line(line)
        if replay:
            log.info("Q3 downlink replay %d msg(s)", len(replay))

        async def pump_down() -> None:
            try:
                while True:
                    line = await q.get()
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        await send_line(line)
                        continue
                    if isinstance(msg, dict) and not _affects_squad1(msg):
                        continue
                    log.info("Q3 ↓ %s", _tx_summary(msg) if isinstance(msg, dict) else "?")
                    await send_line(line)
            except (asyncio.CancelledError, ConnectionError, BrokenPipeError):
                raise
            except Exception:
                log.exception("Q3 downlink pump error")
                raise

        down_task = asyncio.create_task(pump_down())
        buf = ""
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                raise ConnectionError("eof")
            buf += chunk.decode("utf-8", "ignore")
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    log.warning("Q3 bad json: %s", line[:160])
                    continue
                _ingest_one(store, obj)
    finally:
        if down_task is not None:
            down_task.cancel()
        downlink.unsubscribe(q)
        if writer is not None:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass


def _ingest_one(store, obj: Any) -> None:
    global _hello
    items = obj if isinstance(obj, list) else [obj]
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "router.hello":
            _hello = dict(item.get("data") or {})
            _hello["_ts"] = time.time()
            log.info("Q3 hello: node=%s ble=%s format=%s",
                     _hello.get("node"), _hello.get("ble"), _hello.get("report_format"))
            router_hub.note_rx()
            continue
        try:
            ev = normalize_event(item)
            if ev is None or not should_ingest_hw_event(ev):
                continue
            if ev.get("type") == "ack":
                log.info("Q3 ↑ ack ref=%s from=%s",
                         (ev.get("data") or {}).get("ref"),
                         (ev.get("data") or {}).get("from"))
            router_hub.note_rx()
            store.ingest(ev)
        except Exception:
            log.exception("Q3 ingest error: %s", str(item)[:200])


def status() -> dict[str, Any]:
    return {
        "enabled": os.getenv("COP_Q3", "0").strip().lower() in ("1", "true", "yes", "on"),
        "host": os.getenv("COP_Q3_HOST", "192.168.4.1"),
        "port": int(os.getenv("COP_Q3_PORT", "9000")),
        "link": LINK_NAME in router_hub.links,
        "hello": _hello or None,
        "tx_count": _tx_count,
        "tx_last": _tx_last,
        "downlink": True,
    }
