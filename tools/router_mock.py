#!/usr/bin/env python3
"""Realtime 시연용 — 1분대 라우터 WebSocket mock.

분대원(1-2~1-4) relpos 만 올린다. 1-1 GPS·메시 링크는 COP가 mock한다.

  # COP를 realtime 모드로 둔 뒤
  python3 tools/router_mock.py
  python3 tools/router_mock.py --host 192.168.0.10 --period 1
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import random
import time

try:
    import websockets
except ImportError:
    raise SystemExit("pip install websockets  (또는 backend/.venv/bin/pip install websockets)")


MEMBERS = [
    ("1-2", (-9.0, -8.0)),
    ("1-3", (9.0, -8.0)),
    ("1-4", (-18.0, -16.0)),
]


async def run(url: str, period: float) -> None:
    t0 = time.time()
    print(f"connecting {url}  period={period}s  relpos={[u for u, _ in MEMBERS]}  (1-1 GPS=COP mock)")
    async with websockets.connect(url) as ws:
        hello = await asyncio.wait_for(ws.recv(), timeout=5)
        print("←", hello[:200])
        while True:
            elapsed = time.time() - t0
            hdg = (45 + math.sin(elapsed / 20) * 10) % 360
            wobble = math.sin(elapsed / 8) * 1.5
            for uid, (dx, dy) in MEMBERS:
                await ws.send(json.dumps({
                    "type": "unit.relpos",
                    "bytes": 14,
                    "data": {
                        "id": uid, "ref": "1-1",
                        "dx": dx + wobble + random.gauss(0, 0.6),
                        "dy": dy + random.gauss(0, 0.6),
                        "err": random.uniform(3.5, 6.0),
                        "heading": hdg,
                        "battery": max(40, 92 - elapsed / 60),
                    },
                }))

            try:
                while True:
                    msg = await asyncio.wait_for(ws.recv(), timeout=0.01)
                    print("↓ downlink", msg[:120])
                    try:
                        obj = json.loads(msg)
                    except json.JSONDecodeError:
                        continue
                    if obj.get("type") == "order.new":
                        for rid in obj.get("data", {}).get("recipients", []):
                            if rid.startswith("1-") and rid != "1-1":
                                await ws.send(json.dumps({
                                    "type": "ack",
                                    "data": {"ref": obj["data"]["id"], "from": rid},
                                }))
                    elif obj.get("type") == "report.update":
                        await ws.send(json.dumps({
                            "type": "ack",
                            "data": {"ref": obj.get("data", {}).get("id"), "from": obj.get("dst", "1-2")},
                        }))
            except asyncio.TimeoutError:
                pass

            await asyncio.sleep(period)


def main() -> None:
    p = argparse.ArgumentParser(description="1분대원 relpos 라우터 mock (1-1 GPS는 COP)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--period", type=float, default=1.0, help="업데이트 주기 [s]")
    args = p.parse_args()
    url = f"ws://{args.host}:{args.port}/ws/router"
    asyncio.run(run(url, args.period))


if __name__ == "__main__":
    main()
