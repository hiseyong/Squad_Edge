"""UNO Q / NU40 게이트웨이 시리얼 입력.

게이트웨이는 한 줄에 하나씩 JSON 이벤트(NDJSON)를 출력하면 된다.
하향 메시지(order.new / haptic / report.update …)는 같은 포트로 NDJSON 한 줄씩 들어간다.
    {"type":"unit.relpos","data":{"id":"1-2","ref":"1-1","dx":4.1,"dy":-7.9,"err":5},"bytes":14}
    {"type":"link.update","data":{"a":"1-1","b":"1-2","rssi":-67}}

환경변수: COP_SERIAL=/dev/tty.usbmodemXXXX  COP_BAUD=115200
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading

log = logging.getLogger("cop.serial")


def start_serial(store, port: str, baud: int = 115200) -> None:
    try:
        import serial  # pyserial
    except ImportError:
        log.error("pyserial 미설치: pip install pyserial")
        return
    loop = asyncio.get_running_loop()
    holder: dict = {"ser": None}

    # 하향 메시지(명령·진동·보고 결과)를 같은 시리얼 포트로 NDJSON 출력
    from ..downlink import downlink

    def write(line: str) -> None:
        ser = holder["ser"]
        if ser is not None and ser.is_open:
            ser.write(line.encode("utf-8"))

    downlink.add_writer(write)

    def worker():
        while True:
            try:
                with serial.Serial(port, baud, timeout=1) as ser:
                    log.info("serial connected %s @%d", port, baud)
                    holder["ser"] = ser
                    while True:
                        line = ser.readline().decode("utf-8", "ignore").strip()
                        if not line.startswith("{"):
                            continue
                        try:
                            ev = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        loop.call_soon_threadsafe(store.ingest, ev)
            except Exception as e:  # 포트 분리 등 → 재시도
                holder["ser"] = None
                log.warning("serial error: %s (3초 후 재시도)", e)
                import time
                time.sleep(3)

    threading.Thread(target=worker, daemon=True, name="serial").start()
