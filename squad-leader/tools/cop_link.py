"""[보드] 소대장 노트북(COP) 링크 실행: AP(192.168.4.1) TCP :9000 대기.

    sudo tools/ap_start.sh                                   # 먼저 AP 켜기
    .venv/bin/python tools/cop_link.py                       # 위치 1초 상향 + 하향 명령 수신
    .venv/bin/python tools/cop_link.py --scenario            # + 병사 보고·양식 보고 시연 시나리오 상향
    .venv/bin/python tools/cop_link.py --host 127.0.0.1      # AP 없이 보드 안에서 시험
    .venv/bin/python tools/cop_link.py --llm none            # LLM 끄고 규칙만
LLM: 기본 = 미세조정 0.5B (models/llm/sq-nlu-qwen2.5-0.5b-instruct-q4_0.gguf). 규칙본 먼저 송신 →
     LLM 칸 추출이 검증 통과하고 규칙본과 다르면 정정본(rev+1) 송신.
보고 형식: docs/squad_platoon_report_protocol_v0.1.md (sq-rpt/0.1)

노트북: Wi-Fi 'SquadEdge-1-1' 연결 → COP_MODE=realtime COP_Q3=1 COP_Q3_HOST=192.168.4.1 ./run.sh
       (또는 시험용:  nc 192.168.4.1 9000)
BLE 병사 연결은 아직 이 실행기에 붙지 않았다: 하향 명령은 병사용 프레임(hex)으로 만들어 로그로만 남긴다.
분대장 GPS도 MCU 연동 전이라 시연용 가정 좌표(팀 COP 데모 원점과 같음).
"""
import argparse
import asyncio
import logging
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LLM = ROOT / "models" / "llm" / "sq-nlu-qwen2.5-0.5b-instruct-q4_0.gguf"
sys.path.insert(0, str(ROOT))

from squad.link.motion import SquadMotion  # noqa: E402
from squad.link.cop import AP_IP, PORT, CopServer, Telemetry, report_event  # noqa: E402
from squad.protocol import Msg  # noqa: E402
from squad.report.desk import SqDesk  # noqa: E402
from squad.report.log import CombatLog  # noqa: E402
from squad.report.sqrpt import Geo, ReportCounter  # noqa: E402
from squad.report.situation import Situation  # noqa: E402

DEMO_LAT, DEMO_LON = 36.3005, 127.4185          # 팀 COP 데모 원점
HEADING = 45
MEMBERS = (1, 2, 3)                     # 시연 분대원(병사 1~3번) → 소대장 화면 1-2, 1-3, 1-4 (분대장이 위치를 중계)

log = logging.getLogger("cop_link")


ENEMY_AT = (24.0, 32.0)                 # 시연 적 위치: 시작 지점 기준 동·북 m (고정, 약 40m = 병사 "원거리")


def bearing_to_enemy(sit: Situation, motion, sid: int) -> int:
    """지금 병사 위치에서 고정된 적까지 방위 (방위 센서 오차 ±3도 흉내)."""
    import random
    sx, sy = sit.soldiers[sid].pos or (0.0, 0.0)
    ex, ey = ENEMY_AT[0] - motion.x, ENEMY_AT[1] - motion.y      # 분대장 기준 적 위치
    return round(math.degrees(math.atan2(ex - sx, ey - sy)) + random.gauss(0, 3)) % 360


async def scenario(srv: CopServer, sit: Situation, desk: SqDesk, log_db: CombatLog, motion):
    """시연: 병사 1·2번 같은 적 보고 → 3번 본인 부상 → 분대장 보고 음성 → 규격 보고 송신 (+LLM 정정본).
    병사 보고는 분대장 상황 정리·전투 로그에만 들어가고, 소대장에게는 분대장 정형 보고 안에서만 간다(분리 원칙)."""
    while not srv.clients:
        await asyncio.sleep(0.5)
    await asyncio.sleep(3)

    async def report(sid, mt, **f):
        ts = time.time()
        log_db.add("report", sid, {"type": int(mt), **f}, ts=ts)
        if desk.on_events(sit.on_report(sid, mt, f, ts)):
            log.info("헤드셋: 보고 준비됨")
        log.info("병사 %d %s → 분대장 상황 정리·전투 로그 (소대장에 자동 전달 안 함)", sid, Msg(mt).name)

    hd = lambda: int(motion.heading())
    await report(1, Msg.CONTACT, azimuth=bearing_to_enemy(sit, motion, 1), clock=0, dist_band=2, count=3, heading=hd())
    await asyncio.sleep(4)
    await report(2, Msg.CONTACT, azimuth=bearing_to_enemy(sit, motion, 2), clock=0, dist_band=2, count=2, heading=hd())
    await asyncio.sleep(4)
    await report(3, Msg.CASUALTY_SELF, heading=hd())
    await asyncio.sleep(3)
    await leader_report(srv, desk, "적이 좌측으로 우회 중, 고수하겠음, 의무후송 요청")


async def leader_report(srv: CopServer, desk: SqDesk, voice: str):
    """분대장 보고 버튼 + 발화(STT 결과) → 규칙본 송신 → (LLM 있으면) 정정본."""
    data, rb = desk.draft(voice)
    log.info("분대장 발화: %s\n%s\n복창: %s", voice, data["text"], rb)
    # 실제 단말: 복창 후 분대장 [송신] 버튼. 시연에서는 바로 송신
    n = await srv.send([report_event(srv.squad, desk.send(data))])
    log.info("규격 보고 %s [%s] gen=rule → COP %d대", data["rpt"]["id"], data["priority"], n)
    if desk.llm is not None:
        new = await asyncio.to_thread(desk.refine, data)
        if new is None:
            log.info("LLM 정정본 없음 (검증 실패 또는 시간 초과) → 규칙본 유지")
        else:
            n = await srv.send([report_event(srv.squad, desk.send(new))])
            log.info("LLM 정정본 %s rev%d → COP %d대: %s", new["rpt"]["id"], new["rpt"]["rev"], n, new["summary"])


async def resend_loop(srv: CopServer, desk: SqDesk):
    while True:
        await asyncio.sleep(2)
        for d in desk.due_resends():
            n = await srv.send([report_event(srv.squad, d)])
            log.info("소대장 확인 없음 → %s 재송신 (%d대)", d["rpt"]["id"], n)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=AP_IP)
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--period", type=float, default=1.0)
    ap.add_argument("--squad", default="1")
    ap.add_argument("--scenario", action="store_true")
    ap.add_argument("--llm", default=str(DEFAULT_LLM), help="NLU 모델 gguf (정정본). 'none'이면 규칙만")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")

    sit = Situation()
    motion = SquadMotion(DEMO_LAT, DEMO_LON, HEADING, members=MEMBERS)
    sit.set_positions([(i, x, y, int(hd)) for i, (x, y, hd, _) in motion.member_offsets().items()])
    log_db = CombatLog()
    llm = None
    if a.llm and a.llm.lower() != "none":
        from squad.manual.llm import LocalLLM
        log.info("LLM 기동 중: %s", a.llm)
        llm = LocalLLM(Path(a.llm))
        llm.name = Path(a.llm).stem
    desk = SqDesk(sit, Geo(DEMO_LAT, DEMO_LON, HEADING), a.squad, f"{a.squad}분대",
                  ReportCounter(ROOT / "data" / "report_seq.txt"), log_db, llm)
    last = [time.time()]

    def telemetry() -> Telemetry:
        """1초마다: 이동 모델 진행 → 상향 위치 + 상황 집계기·보고 좌표 원점 갱신."""
        now = time.time()
        motion.step(now - last[0])
        last[0] = now
        lat, lon, hd, err = motion.leader()
        mem = motion.member_offsets()
        sit.set_positions([(i, x, y, int(h)) for i, (x, y, h, _) in mem.items()])
        desk.geo = Geo(lat, lon, int(hd))
        # 분대원 위치: 분대장이 받아 정리한 값을 소대장에게 중계(실기에서는 병사 RANGING → 위치 복원 결과, S4)
        return Telemetry(lat, lon, heading=hd, err=err, source="demo",
                         battery=max(40, 95 - int((motion.t) / 120)), members=mem)

    def on_order(order):
        # 분대장 헤드셋 알림 대상(병사에게 넘기지 않는다. 하달은 분대장이 판단)
        log.info("소대장 지시 %s %s (분대장에게 알림)", order.get("code"), order.get("params") or "")
        log_db.add("cmd", 0, {"from": "PL", "order": order})

    def on_mission(data):
        log.info("소대장 임무 변경 %s (분대장에게 알림)", data)
        log_db.add("note", 0, {"from": "PL", "mission": data})

    def on_ack(d):
        desk.on_ack(d.get("ref"), d.get("rev"))
        log.info("소대장 수신 확인 %s rev%s", d.get("ref"), d.get("rev"))

    def on_query(d):
        r = desk.on_query(d.get("ref"))
        log.info("소대장 요청 %s %s → %s", d.get("ask"), d.get("ref"), "재송" if r else "해당 보고 없음")
        return [report_event(a.squad, r)] if r else []

    srv = CopServer(a.squad, a.host, a.port, a.period, telemetry=telemetry, on_order=on_order, on_mission=on_mission,
                    on_report_ack=on_ack, on_report_query=on_query, members=MEMBERS)
    try:
        await srv.start()
    except OSError as e:
        sys.exit(f"{a.host}:{a.port} 대기 실패 ({e}). AP를 켰는지 확인: sudo tools/ap_start.sh  "
                 f"(보드 안 시험은 --host 127.0.0.1)")
    log.info("노트북: Wi-Fi 연결 후 %s:%d 접속 대기 중", a.host, a.port)
    asyncio.create_task(resend_loop(srv, desk))
    if a.scenario:
        asyncio.create_task(scenario(srv, sit, desk, log_db, motion))
    await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
