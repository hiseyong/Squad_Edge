"""UDP JSON 입력 (같은 LAN/핫스팟의 게이트웨이·음성 AI 모듈용).

    echo '{"type":"sensor.trigger","data":{"id":"S-1"}}' | nc -u -w0 127.0.0.1 5005

환경변수: COP_UDP_PORT=5005 (0이면 비활성)
"""
from __future__ import annotations

import asyncio
import json
import logging

log = logging.getLogger("cop.udp")


class _Proto(asyncio.DatagramProtocol):
    def __init__(self, store) -> None:
        self.store = store

    def datagram_received(self, data: bytes, addr) -> None:
        for line in data.decode("utf-8", "ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                self.store.ingest(json.loads(line))
            except Exception as e:
                log.warning("bad udp packet from %s: %s", addr, e)


async def start_udp(store, port: int) -> bool:
    """UDP ingest 바인드. 포트 점유 시 False 반환(앱은 계속 기동)."""
    loop = asyncio.get_running_loop()
    try:
        await loop.create_datagram_endpoint(lambda: _Proto(store), local_addr=("0.0.0.0", port))
    except OSError as e:
        log.warning("UDP :%d bind 실패 (%s) — COP_UDP_PORT=0 으로 끄거나 기존 프로세스 종료 후 재시도", port, e)
        return False
    log.info("UDP ingest listening on :%d", port)
    return True
