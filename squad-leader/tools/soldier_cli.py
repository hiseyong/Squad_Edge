#!/usr/bin/env python3
"""[보드] 병사 링크 시험 CLI — 레퍼런스 mock_leader와 같은 명령 문법(같은 조작으로 송수신 hex 비교, LEADER_TASK S2·S3).

    .venv/bin/python tools/soldier_cli.py --only S1 --log-csv data/soldier_link/s1.csv --seq-start 0
    명령: list | status | cmd <name|code> [az] [dist] [extra] [prio] [targets] | voice <wav> [prio] [targets]
          | emcon <0|1|2> [targets] | pos <wedge|line|column> [targets]
          | pos auto [id:시계 ...] [targets] | pos dist <분대장-S1> <분대장-S2> <S1-S2> [id:시계 ...] | autopos on|off
          | peer <reporter> <az|-> <dist> <count> [targets] | hpeer <reporter> <az|-> [targets] (폭발물 의심)
          | dist | relay on|off | stats <id|all> | raw <id|all> <hex> | ack on|off | mark <m>|- | quit
    침묵 방송(bcmd/bemcon)·비콘(lbeacon)은 없다: 보드 A 버튼이 맡는다(병사 팀 안내문 D1~D3).
    병사 LOG(0x7F)는 화면에 내지 않고 --log7f 파일로만(기본 data/soldier_link/log7f.txt).
    --keypad: 4×4 키패드(MCU, arduino-router)로 명령 하달. 안내 문장은 "🔊"로 출력(헤드셋 연결은 S5).
병사 팀 mock_leader는 꺼 둔다(병사는 분대장 하나하고만 연결된다).
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from squad.soldier import codec as fc  # noqa: E402
from squad.soldier.ble import BleLink  # noqa: E402
from squad.soldier.leader import CMD_NAMES, DIST_ARGS, SquadLeader, parse_cmd_code  # noqa: E402
from squad.soldier.seq import LeaderSeq  # noqa: E402
from squad.soldier.txlog import TxLog  # noqa: E402
from squad.soldier.voice import load_wav_8k  # noqa: E402

log = logging.getLogger("soldier_cli")


def parse_only(spec: str | None) -> set[int]:
    if not spec:
        return set(range(1, 6))
    return {int(p.strip().upper().lstrip("S")) for p in spec.split(",")}


async def handle(ld: SquadLeader, link: BleLink, line: str, stop: asyncio.Event) -> None:
    parts = line.split()
    if not parts:
        return
    cmd, args = parts[0].lower(), parts[1:]
    if cmd in ("quit", "exit", "q"):
        stop.set()
    elif cmd == "list":
        for p in link.peers.values():
            st = f"연결됨 MTU={p.mtu}" if p.connected else ("연결 중" if p.connecting else "찾는 중")
            log.info("  S%d: %s (연결 %d회)", p.sid, st, p.connects)
    elif cmd == "cmd":
        if not args or len(args) > 6:
            raise ValueError("사용: cmd <name|code> [az] [dist] [extra] [prio] [targets]  ('-' = 기본값)")
        code = parse_cmd_code(args[0])
        az_s, dist_s, extra_s, prio_s, tgt_s = (args[1:] + ["-"] * 5)[:5]
        az = fc.NO_AZIMUTH if az_s in ("-", "none") else int(az_s)
        if dist_s.lower() not in DIST_ARGS:
            raise ValueError("dist는 near|mid|far|0|1|2|-")
        prio = 0 if prio_s == "-" else int(prio_s)
        if prio not in (0, 1):
            raise ValueError("prio는 0 또는 1")
        await ld.send_cmd(code, az, DIST_ARGS[dist_s.lower()], 0 if extra_s == "-" else int(extra_s), prio,
                          "all" if tgt_s == "-" else tgt_s)
    elif cmd == "status":
        for ln in ld.status_lines():
            log.info("  %s", ln)
    elif cmd == "voice":
        if not args or len(args) > 3:
            raise ValueError("사용: voice <wav> [prio] [targets]")
        try:
            pcm = load_wav_8k(Path(args[0]).expanduser())
        except (OSError, ValueError, StopIteration) as e:
            raise ValueError(f"WAV 읽기 실패: {e}") from None
        await ld.send_voice(pcm, 0 if len(args) < 2 or args[1] == "-" else int(args[1]),
                            "all" if len(args) < 3 or args[2] == "-" else args[2])
    elif cmd == "emcon":
        if not args or len(args) > 2 or args[0] not in ("0", "1", "2"):
            raise ValueError("사용: emcon <0|1|2> [targets]  (연결 write. 침묵 해제는 보드 A 버튼4 길게 또는 병사 직접)")
        await ld.send_emcon(int(args[0]), args[1] if len(args) == 2 else "all")
    elif cmd == "pos":
        if not args:
            raise ValueError("사용: pos <wedge|line|column|auto|dist> …")
        name, rest = args[0], args[1:]
        clocks = {int(t.split(":")[0].upper().lstrip("S")): int(t.split(":")[1]) for t in rest if ":" in t}
        others = [t for t in rest if ":" not in t]
        if name in ("wedge", "line", "column"):
            await ld.send_pos_preset(name, others[0] if others else "all")
        elif name == "auto":
            await ld.pos_auto({**ld.clocks, **clocks}, others[0] if others else "all")
        elif name == "dist":
            if len(others) < 3:
                raise ValueError("사용: pos dist <분대장-S1> <분대장-S2> <S1-S2> [id:시계 ...]")
            await ld.pos_dist(*(float(x) for x in others[:3]), {**ld.clocks, **clocks})
        else:
            raise ValueError("pos <wedge|line|column|auto|dist>")
    elif cmd == "autopos":
        if len(args) != 1 or args[0] not in ("on", "off"):
            raise ValueError("사용: autopos on|off  (30초마다 다시 계산, 3m 넘게 바뀌면 POS_TABLE)")
        ld.auto_pos = args[0] == "on"
        log.info("자동 위치 갱신 %s", "켬" if ld.auto_pos else "끔")
    elif cmd == "dist":
        for ln in ld.dist_lines():
            log.info("  %s", ln)
    elif cmd == "hpeer":
        if len(args) not in (2, 3):
            raise ValueError("사용: hpeer <reporter> <az|-> [targets]")
        az = fc.NO_AZIMUTH if args[1] in ("-", "none") else int(args[1])
        await ld.send_peer_type(fc.HAZARD, int(args[0].upper().lstrip("S")), az, fc.NO_DIST, 0,
                                args[2] if len(args) == 3 else "all")
    elif cmd == "peer":
        if len(args) not in (4, 5):
            raise ValueError("사용: peer <reporter> <az|-> <dist near|mid|far|-> <count 0~5> [targets]")
        az = fc.NO_AZIMUTH if args[1] in ("-", "none") else int(args[1])
        await ld.send_peer(int(args[0].upper().lstrip("S")), az, DIST_ARGS[args[2].lower()], int(args[3]),
                           args[4] if len(args) == 5 else "all")
    elif cmd == "relay":
        if len(args) != 1 or args[0] not in ("on", "off"):
            raise ValueError("사용: relay on|off")
        ld.relay = args[0] == "on"
        log.info("PEER_REPORT 자동 중계 %s", "켬" if ld.relay else "끔")
    elif cmd == "stats":
        if len(args) != 1:
            raise ValueError("사용: stats <id|all>")
        await ld.req_stats(args[0])
    elif cmd == "raw":
        if len(args) < 2:
            raise ValueError("사용: raw <id|all> <hex>")
        await ld.write(ld.targets(args[0]), fc.from_hex("".join(args[1:])))
    elif cmd == "ack":
        if len(args) != 1 or args[0] not in ("on", "off"):
            raise ValueError("사용: ack on|off")
        ld.auto_ack = args[0] == "on"
        log.info("RPT_ACK 자동 응답 %s", "켬" if ld.auto_ack else "끔")
    elif cmd == "mark":
        ld.txlog.mark(args[0] if args else "-")
        log.info("표시: %s", args[0] if args else "-")
    elif cmd == "help":
        log.info(__doc__)
    else:
        raise ValueError(f"알 수 없는 명령 '{cmd}'")


def start_keypad(ld: SquadLeader, stop: asyncio.Event) -> list:
    from squad.input.keypad import CommandPad, KeyTimer, RouterKeys

    def say(text):
        log.info("🔊 %s", text)

    def send(d):
        async def go():
            pc = await ld.send_cmd(d["cmd_code"], d["azimuth"], d["dist_band"], d["extra"], d["priority"], d["target"])
            if pc is None:
                say("송신 대상 없음")
        asyncio.get_running_loop().create_task(go())

    pad = CommandPad(say, send, on_ptt=lambda k, down: log.info("[PTT %s %s] (S5에서 STT 연결)", k, "눌림" if down else "뗌"),
                     on_replay=lambda: say("다시 들을 안내 없음"), targets=ld.allowed)
    kt = KeyTimer(pad.on_key)
    keys = RouterKeys(lambda key, down, t: kt.feed(key, down, t))

    async def ticker():
        import time as _t
        while not stop.is_set():
            kt.tick(_t.monotonic())
            await asyncio.sleep(0.05)

    async def stopper():
        await stop.wait()
        keys.stop.set()

    return [asyncio.create_task(keys.run()), asyncio.create_task(ticker()), asyncio.create_task(stopper())]


async def main() -> None:
    ap = argparse.ArgumentParser(description="병사 링크 시험 CLI (mock_leader 문법)")
    ap.add_argument("--only", help="연결할 병사, 예: S1 또는 S1,S2")
    ap.add_argument("--log-csv", help="송수신 CSV (mock_leader 형식)")
    ap.add_argument("--seq-start", type=int, help="시험용 seq 시작값(운용은 무작위)")
    ap.add_argument("--pathloss", help="경로손실 'P1m,n' (기본 -65.5,1.6; tools/fit_pathloss 결과)")
    ap.add_argument("--clocks", help="분대장이 본 병사 방향, 예: 1:10,2:2 (기본)")
    ap.add_argument("--autopos", action="store_true", help="30초마다 위치 다시 계산·송신")
    ap.add_argument("--keypad", action="store_true", help="4×4 키패드로 명령 하달(mcu/keypad 스케치 필요)")
    ap.add_argument("--log7f", default=str(ROOT / "data" / "soldier_link" / "log7f.txt"), help="병사 LOG(0x7F) 파일")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S", stream=sys.stdout)
    Path(a.log7f).parent.mkdir(parents=True, exist_ok=True)
    l7 = logging.getLogger("soldier.log7f")
    l7.propagate = False
    h = logging.FileHandler(a.log7f, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))
    l7.addHandler(h)

    allowed = parse_only(a.only)
    stop = asyncio.Event()
    holder: dict = {}
    def on_event(e):
        if e["kind"] in ("cmd_unacked", "silent_blocked", "voice_result", "emcon_set"):
            log.info("  [알림] %s", {k: v for k, v in e.items() if k not in ("raw", "msg")})

    link = BleLink(allowed, on_frame=lambda s, r: holder["ld"].on_frame(s, r),
                   on_connect=lambda s, m: holder["ld"].on_connect(s, m),
                   on_disconnect=lambda s: holder["ld"].on_disconnect(s),
                   on_tx=lambda s, r: holder["ld"].on_tx(s, r))
    ld = holder["ld"] = SquadLeader(link, seq=LeaderSeq(a.seq_start), txlog=TxLog(a.log_csv), allowed=tuple(sorted(allowed)),
                                    on_event=on_event)
    if a.pathloss:
        ld.pathloss = tuple(float(x) for x in a.pathloss.split(","))
    if a.clocks:
        ld.clocks = {int(k): int(v) for k, v in (t.split(":") for t in a.clocks.split(","))}
    ld.auto_pos = a.autopos
    log.info("SQ1-S{%s} 찾는 중 … seq 시작 %d%s", ",".join(map(str, sorted(allowed))), ld.seq.value,
             "" if a.seq_start is not None else "(무작위)")

    loop = asyncio.get_running_loop()
    lines: asyncio.Queue = asyncio.Queue()

    def reader():
        for raw in sys.stdin:
            loop.call_soon_threadsafe(lines.put_nowait, raw)
        loop.call_soon_threadsafe(lines.put_nowait, None)

    threading.Thread(target=reader, daemon=True).start()
    tasks = [asyncio.create_task(link.run()), asyncio.create_task(ld.watch(stop))]
    tasks.append(asyncio.create_task(ld.auto_pos_loop(stop)))
    if a.keypad:
        tasks += start_keypad(ld, stop)

    async def cli():
        while not stop.is_set():
            line = await lines.get()
            if line is None:
                stop.set()
                break
            try:
                await handle(ld, link, line.strip(), stop)
            except ValueError as e:
                log.info("오류: %s", e)

    await cli()
    link.stop.set()
    for t in tasks[2:]:                    # 자동 위치·키패드 작업은 대기 중일 수 있어 취소
        t.cancel()
    for t in tasks:
        try:
            await t
        except asyncio.CancelledError:
            pass
    ld.txlog.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
