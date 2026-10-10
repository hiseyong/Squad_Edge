"""Squad Edge C2 — COP 서버.

    uvicorn app.main:app --host 0.0.0.0 --reload --port 8000

환경변수
    COP_MODE=scenario|realtime  동작 모드 (기본 scenario)
    COP_SIM=1                   시뮬레이터 자동 시작 (기본 1; 0이면 수동)
    COP_SERIAL=/dev/...         게이트웨이 시리얼 포트 (NDJSON)
    COP_UDP_PORT=5005           UDP JSON 입력 포트 (0=off)
    COP_Q3=1                    분대장1 Arduino UNO Q SoftAP TCP 클라이언트
    COP_Q3_HOST=192.168.4.1     보드 AP IP (노트북이 해당 AP에 조인 필요)
    COP_Q3_PORT=9000
    COP_LLM_URL=...             로컬 LLM (기본 http://localhost:11434 Ollama 자동 탐지, off=비활성)
    COP_LLM_MODEL=...           사용할 모델 (기본: 설치된 모델 중 자동 선택)

모드
    scenario  전 소대 mock + 스크립트 시나리오
    realtime  1-1 GPS=COP mock · 1-2~1-4=단말 relpos · HQ·2·3=mock
              분대원 미수신 시 두절 / 메시 링크는 COP 합성
              분대장: ws://<host>:8000/ws/router  또는  SoftAP TCP (COP_Q3=1)
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import json
from typing import Any, Literal

from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import briefing
from .downlink import downlink
from .llm import llm
from .models import Event
from .sources.q3_ap import start_q3_ap, status as q3_status
from .sources.router import handle_router_ws, router_hub
from .sources.serial_source import start_serial
from .sources.simulator import Simulator
from .sources.udp_source import start_udp
from .state import store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("cop")

sim = Simulator(store)
DemoMode = Literal["scenario", "realtime"]
_mode: DemoMode = "scenario"  # lifespan에서 초기화


def _apply_mode(mode: DemoMode, *, restart: bool = True) -> dict[str, Any]:
    """시나리오 ↔ realtime 전환. realtime: 1-1 mock GPS, 1-2~1-4 HW relpos, HQ·2·3 mock."""
    global _mode
    _mode = mode
    store.demo_mode = mode
    if mode == "realtime":
        sim.configure("realtime", live_squads={"1"})
    else:
        sim.configure("scenario")
    if restart:
        if sim.running:
            sim.restart()
        elif os.getenv("COP_SIM", "1") == "1":
            sim.start()
    store.demo_mode = mode  # reset() 후에도 유지
    log.info("demo mode → %s (sim.running=%s live=%s)", mode, sim.running, sorted(sim.live_squads))
    return mode_status()


def mode_status() -> dict[str, Any]:
    rs = router_hub.status()
    return {
        "mode": _mode,
        "sim_running": sim.running,
        "live_squads": sorted(sim.live_squads),
        "mock_squads": ["HQ", "2", "3"] if _mode == "realtime"
        else ["HQ", "1", "2", "3"] if sim.running else [],
        "mock_gps": list(rs.get("mock_gps", [])) if _mode == "realtime" else [],
        "hw_gps": list(rs.get("hw_gps", [])) if _mode == "realtime" else [],
        "hw_relpos": list(rs.get("hw_relpos", [])) if _mode == "realtime" else [],
        "router": rs,
        "q3_ap": q3_status(),
        "period_s": 1.0,
        "note": (
            "위치 mock만(1-1+HQ/2/3) · 1-2~1-4=Arduino relpos · 보고·부상 등 이벤트 mock 없음"
            if _mode == "realtime"
            else "전 소대 시나리오 mock"
        ),
    }


async def _checker():
    """시뮬레이터가 꺼져 있어도 경보 규칙/메타 갱신은 계속 돈다."""
    while True:
        await asyncio.sleep(1)
        if not sim.running:
            store.periodic_checks()
            store.emit_meta()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _mode
    boot = os.getenv("COP_MODE", "scenario").strip().lower()
    if boot not in ("scenario", "realtime"):
        boot = "scenario"
    _apply_mode(boot, restart=False)  # type: ignore[arg-type]
    if os.getenv("COP_SIM", "1") == "1":
        sim.start()
    if port := os.getenv("COP_SERIAL"):
        start_serial(store, port, int(os.getenv("COP_BAUD", "115200")))
    udp = int(os.getenv("COP_UDP_PORT", "5005"))
    if udp:
        ok = await start_udp(store, udp)
        if not ok:
            log.warning("UDP ingest 비활성 (포트 %d 사용 중). SoftAP/WS/시리얼은 정상", udp)
    q3_task = await start_q3_ap(store)
    task = asyncio.create_task(_checker())

    async def _boot_llm() -> None:
        st = await llm.refresh(force=True)
        if st.get("available"):
            await llm.warmup()

    asyncio.create_task(_boot_llm())
    yield
    task.cancel()
    if q3_task:
        q3_task.cancel()
    sim.stop()


app = FastAPI(title="Squad Edge C2 COP", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ------------------------------------------------------------------ realtime
@app.websocket("/ws")
async def ws(ws: WebSocket):
    await ws.accept()
    q = store.subscribe()
    try:
        await ws.send_json({"t": "snapshot", "v": store.snapshot()})
        while True:
            await ws.send_text(await q.get())
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        store.unsubscribe(q)


# ------------------------------------------------------------------ REST
@app.get("/api/state")
async def get_state():
    return store.snapshot()


@app.post("/api/ingest")
async def ingest(ev: Event | list[Event]):
    """게이트웨이·음성 AI 모듈의 표준 입력. 단일 이벤트 또는 배열.
    (store는 이벤트 루프 단일 스레드에서만 다루므로 엔드포인트는 모두 async)"""
    for e in ev if isinstance(ev, list) else [ev]:
        store.ingest(e)
    return {"ok": True}


class ReportAction(BaseModel):
    status: str  # confirmed | rejected  (호환용)


@app.post("/api/reports/{rid}")
async def report_action(rid: str, body: ReportAction):
    store.ingest({"type": "report.update", "data": {"id": rid, "status": body.status}})
    return {"ok": True}


class Decision(BaseModel):
    action: str                          # confirm | reject | recheck | reopen
    note: str = ""
    edits: dict[str, Any] | None = None  # {summary?, priority?, fields?}
    by: str = "PL"


@app.post("/api/reports/{rid}/decision")
async def report_decision(rid: str, body: Decision):
    if body.action not in ("confirm", "reject", "recheck", "reopen"):
        raise HTTPException(400, "invalid action")
    r = store.decide_report(rid, body.action, by=body.by, note=body.note, edits=body.edits)
    if r is None:
        raise HTTPException(404, "report not found")
    return r.model_dump()


# ------------------------------------------------------------------ 명령 하달
class OrderBody(BaseModel):
    code: str
    to: list[str] = ["*"]
    text: str = ""
    params: dict[str, Any] = {}
    priority: str = "priority"
    by: str = "PL"


@app.post("/api/orders")
async def create_order(body: OrderBody):
    from .state import ORDER_KO
    if body.code not in ORDER_KO:
        raise HTTPException(400, f"unknown code {body.code}")
    o = store.issue_order(body.code, body.to, text=body.text, params=body.params,
                          by=body.by, priority=body.priority)
    if not o.recipients:
        raise HTTPException(400, "수신 대상 없음")
    return o.model_dump()


@app.post("/api/orders/{oid}/cancel")
async def cancel_order(oid: str):
    o = store.cancel_order(oid)
    if o is None:
        raise HTTPException(404, "order not found")
    return o.model_dump()


@app.post("/api/orders/{oid}/resend")
async def resend_order(oid: str):
    o = store.orders.get(oid)
    if o is None:
        raise HTTPException(404, "order not found")
    missing = [r for r in o.recipients if r not in o.acks]
    if missing:
        o.status, o.tx_count, o.last_tx = "partial" if o.acks else "sent", 1, __import__("time").time()
        store._transmit_order(o, only=missing)
        store.put("orders", o)
    return o.model_dump()


@app.get("/api/downlink")
async def recent_downlink():
    return list(downlink.recent)


@app.websocket("/ws/downlink")
async def ws_downlink(ws: WebSocket):
    """UNO Q 게이트웨이 구독용: 하향 메시지를 NDJSON 텍스트 프레임으로 받는다."""
    await ws.accept()
    q = downlink.subscribe()
    try:
        while True:
            await ws.send_text(await q.get())
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        downlink.unsubscribe(q)


@app.websocket("/ws/router")
async def ws_router(ws: WebSocket):
    """Realtime 시연: 분대장 단말기(라우터) 양방향 소켓.
    상향=위치/보고 ingest, 하향=명령·진동. 이상적 주기 1초."""
    await handle_router_ws(ws, store)


@app.post("/api/alerts/{aid}/ack")
async def ack_alert(aid: str):
    a = store.alerts.get(aid)
    if a:
        a.ack = True
        store.put("alerts", a)
    return {"ok": True}


@app.post("/api/alerts/ack_all")
async def ack_all():
    for a in list(store.alerts.values()):
        if not a.ack:
            a.ack = True
            store.put("alerts", a)
    return {"ok": True}


class EmconBody(BaseModel):
    on: bool


@app.post("/api/emcon")
async def set_emcon(body: EmconBody):
    store.ingest({"type": "mission.update", "data": {"emcon": body.on}})
    store.alert("info", "emcon", f"EMCON {'발령 — 송신 최소화' if body.on else '해제'}", key=f"emcon:{body.on}", cooldown=1)
    return {"ok": True}


class SimBody(BaseModel):
    action: str  # start | stop | restart


@app.post("/api/sim")
async def sim_ctl(body: SimBody):
    {"start": sim.start, "stop": sim.stop, "restart": sim.restart}[body.action]()
    return {"running": sim.running, **mode_status()}


@app.get("/api/sim")
async def sim_status():
    return {"running": sim.running, **mode_status()}


class ModeBody(BaseModel):
    mode: DemoMode  # scenario | realtime


@app.get("/api/mode")
async def get_mode():
    return mode_status()


@app.post("/api/mode")
async def set_mode(body: ModeBody):
    """scenario ↔ realtime 전환. realtime은 시뮬을 재시작해 HQ·2·3만 mock으로 돌린다."""
    if body.mode not in ("scenario", "realtime"):
        raise HTTPException(400, "mode must be scenario|realtime")
    return _apply_mode(body.mode, restart=True)


class BriefBody(BaseModel):
    question: str | None = None
    use_llm: bool = True


@app.post("/api/briefing")
async def get_briefing(body: BriefBody):
    return await briefing.brief(store, body.question, body.use_llm)


@app.post("/api/briefing/stream")
async def stream_briefing(body: BriefBody):
    """Server-Sent Events: data: {type: meta|token|done|error, ...}"""
    async def gen():
        async for ev in briefing.stream(store, body.question, body.use_llm):
            yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/llm/status")
async def llm_status(refresh: bool = False):
    return await llm.refresh(force=refresh)


class ModelBody(BaseModel):
    model: str


@app.post("/api/llm/model")
async def llm_model(body: ModelBody):
    llm.set_model(body.model)
    return llm.status()


# ------------------------------------------------------------------ static (빌드된 프론트엔드)
DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
TILES = Path(__file__).resolve().parents[2] / "tiles"
if TILES.exists():  # 오프라인 지도 타일: tiles/{z}/{x}/{y}.png
    app.mount("/tiles", StaticFiles(directory=TILES), name="tiles")
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = DIST / path
        return FileResponse(f if f.is_file() else DIST / "index.html")
