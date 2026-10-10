#!/usr/bin/env python3
"""[보드] 분대장 통합 실행기 (LEADER_TASK S5) — 병사 BLE 링크 + 소대장 AP 링크 + 키패드 + 상황 정리 + 전투 로그.

    .venv/bin/python tools/leader_app.py                     # AP(192.168.4.1:9000) + 병사 S1~S5 + 키패드
    .venv/bin/python tools/leader_app.py --host 127.0.0.1    # AP 없이 보드 안에서 시험
    표준입력으로 시험 명령(tools/soldier_cli.py와 같은 문법)도 받는다: cmd, pos, emcon, stats, status …

두 링크는 서로를 모른다(squad/link ↔ squad/soldier). 이 파일(앱 계층)만 둘을 잇는다:
  병사 보고 → 분대장 헤드셋 문장 + 전투 로그 + 상황 정리(Situation) — 소대장에게는 분대장 보고서 안에서만
  분대장 보고: A 키 PTT → 정형화된 보고서(양식, sq-rpt), 전투 종료 뒤 발화 → 전투 데이터 보고(S5-3)
  예외: 적 발견(병사 CONTACT, 분대장 키패드 '적 위치') → 분대장 기준 위치로 바꿔 소대장에게 즉시 자동 보고
  분대원 위치(위치표) → 상황 정리 + 소대장 화면(unit.relpos, 분대장이 중계)
  소대장 지시·임무 변경 → 분대장 헤드셋 알림만(병사에게 자동 하달하지 않음)
헤드셋(S5-2): 맥 mac_mic_sender.py(마이크 + 재생) ↔ adb forward tcp:7100. 키 A·B·C는 누르는 동안 말하기(PTT).
  A = 정형화된 보고서(발화 → 양식 → 복창 → # 송신 / * 취소)   B = 교범 질문 → 답변 낭독
  C = 병사 하달(명령어면 버튼 명령, 아니면 TTS 음성 하달 → 복창 → # 송신 / * 취소)
안내 문장은 헤드셋 재생과 함께 "🔊"로 로그에도 남긴다(--no-audio면 로그만).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from squad.link.cop import AP_IP, PORT, CopServer, Telemetry, battle_event, contact_event, member_uid, report_event  # noqa: E402
from squad.report.desk import SqDesk  # noqa: E402
from squad.report.log import CombatLog  # noqa: E402
from squad.report.situation import Situation  # noqa: E402
from squad.report.sqrpt import Geo, ReportCounter  # noqa: E402
from squad.soldier import codec as fc  # noqa: E402
from squad.soldier.ble import BleLink  # noqa: E402
from squad.soldier.describe import describe  # noqa: E402
from squad.soldier.geo import target_estimate  # noqa: E402
from squad.soldier.leader import REPORT_TYPES, SquadLeader  # noqa: E402
from squad.soldier.phrases import report_sentence, unacked_sentence  # noqa: E402
from squad.soldier.seq import LeaderSeq  # noqa: E402
from squad.soldier.txlog import TxLog  # noqa: E402

log = logging.getLogger("leader_app")

DEMO_LAT, DEMO_LON = 36.3005, 127.4185      # GPS가 붙기 전 분대장 원점(팀 COP 데모 원점)
LEADER_HEADING = 0                           # 병사 팀 안내문 D5: 분대장 방위 0 고정
WARM_PHRASES = ["정지", "엄폐", "전진", "후퇴", "집결", "사격 개시", "사격 중지", "경계", "적 위치", "고수", "취소",
                "상태 보고", "무선 침묵", "전원", "1번", "2번", "3번", "근거리", "중거리", "원거리", "거리 없음",
                *[f"{i}시" for i in range(1, 13)], "입력 취소", "보고 송신", "인식 못 함, 다시", "마이크 미연결",
                "침묵 중, 보드 A 버튼 사용", "보고 준비됨"]
FORMATION_CLOCKS = {"line": {1: 9, 2: 3, 3: 9, 4: 3, 5: 9},          # 실측 위치를 돌려 맞출 방향(분대장 총구 = 북)
                    "wedge": {1: 8, 2: 4, 3: 8, 4: 4, 5: 8},
                    "column": {1: 12, 2: 6, 3: 12, 4: 6, 5: 6}}


class LeaderApp:
    def __init__(self, a):
        self.a = a
        self.squad = a.squad
        self.me = f"{a.squad}-1"
        data = ROOT / "data" / "leader_app"
        data.mkdir(parents=True, exist_ok=True)
        self.log_db = CombatLog(str(data / "combat_log.sqlite"))
        self.sit = Situation()
        self.geo = Geo(a.lat, a.lon, LEADER_HEADING)
        self.desk = SqDesk(self.sit, self.geo, a.squad, f"{a.squad}분대", ReportCounter(ROOT / "data" / "report_seq.txt"),
                           self.log_db, None)
        allowed = {int(p.strip().upper().lstrip("S")) for p in a.only.split(",")} if a.only else set(range(1, 6))
        self.link = BleLink(allowed, on_frame=lambda s, r: self.ld.on_frame(s, r),
                            on_connect=lambda s, m: self.ld.on_connect(s, m),
                            on_disconnect=lambda s: self.ld.on_disconnect(s),
                            on_tx=lambda s, r: self.ld.on_tx(s, r))
        self.ld = SquadLeader(self.link, seq=LeaderSeq(a.seq_start), txlog=TxLog(data / "soldier_link.csv"),
                              allowed=tuple(sorted(allowed)), on_event=self.on_soldier_event)
        # 위치: 기본 대형(횡대) 위치표로 시작 → 10초마다 병사 RANGING 실측으로 다시 계산(모양 = 실측 거리,
        # 방향 = 대형 기준: 홀수 번 왼쪽 9시, 짝수 번 오른쪽 3시). 소대장 화면은 매번, 병사 위치표는 3m 넘게 바뀔 때만.
        self.ld.formation = a.formation
        self.ld.clocks = FORMATION_CLOCKS[a.formation]
        self.ld.auto_pos = a.autopos
        self.orders_seen: set = set()
        self.oled = None
        if a.oled:
            from squad.output.oled import OledDisplay
            self.oled = OledDisplay()
        self.srv = CopServer(a.squad, a.host, a.port, 1.0, telemetry=self.telemetry, on_order=self.on_order,
                             on_mission=self.on_mission, on_order_cancel=self.on_order_cancel, on_report_ack=self.on_report_ack,
                             on_report_query=self.on_report_query, members=tuple(sorted(allowed)))
        self.stop = asyncio.Event()
        self.last_said = None
        self.headset = None
        if a.audio:
            from squad.speech.headset import Headset
            self.headset = Headset()
        self.manual = None
        self.llm = None                 # 정형화된 보고서 전용 미세조정 NLU(--llm none이면 규칙만)
        self.pending = None            # 확인 대기: ("report", data) | ("cmd", dict) | ("voice", text) | ("battle", None)
        self.battle_file = data / "battle_start.txt"   # 이번 전투 시작 시각(전투 종료 보고 뒤 새로)
        try:
            self.battle_t0 = float(self.battle_file.read_text())
        except (OSError, ValueError):
            self.battle_t0 = time.time()
            self.battle_file.write_text(str(self.battle_t0))
        self.outbox: list = []         # 소대장 미연결 때 쌓아 두는 상향(전투 데이터)
        self.pending_t = 0.0

    # ---- 헤드셋 (S5-2에서 TTS) ----
    def say(self, text: str, urgency: str = "report", repeat: int = 1, long: bool = False) -> None:
        self.last_said = text
        log.info("🔊%s %s%s", {"urgent": "!", "system": "·"}.get(urgency, ""), text, f" (×{repeat})" if repeat > 1 else "")
        if self.headset is not None:
            if long:
                self.headset.say_long(text, urgency)
            else:
                self.headset.say(text, urgency, repeat)

    # ---- PTT (A 보고, B 교범, C 병사 하달) ----
    def on_ptt(self, kind: str, down: bool) -> None:
        if self.headset is None:
            log.info("[PTT %s %s] 헤드셋 없음(--no-audio)", kind, "눌림" if down else "뗌")
            return
        if down:
            if not self.headset.ptt_down():
                self.say("마이크 미연결" if not self.headset.mic.connected.is_set() else "음성 인식 준비 중", "system")
            return
        asyncio.get_running_loop().create_task(self._after_ptt(kind))

    async def _after_ptt(self, kind: str) -> None:
        r = await self.headset.ptt_up()
        if r is None:
            self.say("인식 못 함, 다시", "system")
            return
        text = r.text
        self.log_db.add("voice", 0, {"ptt": kind, "text": text, "raw": r.raw, "stt_s": round(r.elapsed_s, 2)})
        if kind == "report":                     # 정형화된 보고서: STT → 미세조정 LLM 빈칸 채우기 → 양식
            nlu, gen = None, {"fallback_reason": "llm:off"}
            if self.llm is not None:
                from squad.report.nlu import llm_nlu
                self.say("보고서 작성 중", "system")
                nlu, ms, reason = await asyncio.to_thread(llm_nlu, self.llm, text, 30.0)
                gen = {"model": self.llm.name, "ms": round(ms)} if nlu else {"fallback_reason": f"llm:{reason}"}
                log.info("LLM 칸 %s (%.1f초)%s", nlu, ms / 1000, "" if nlu else f" 실패 {reason}")
            data, rb = await asyncio.to_thread(self.desk.draft, text, None, nlu, gen)
            log.info("정형 보고서 초안 gen=%s\n%s", data["gen"], data["text"])
            self.set_pending(("report", data))
            self.say(rb, "system", long=True)
        elif kind == "manual":
            if self.manual is None:
                self.say("교범 준비 중", "system")
                return
            from squad.manual.answer import answer
            a = await asyncio.to_thread(answer, self.manual, text)
            self.log_db.add("note", 0, {"manual_q": text, "status": a.status})
            self.say(a.spoken(), "system", long=True)
        elif kind == "voice_cmd":
            from squad.soldier.voicecmd import parse
            c = parse(text, self.ld.allowed)
            if c and c["missing"]:
                self.say(f"{c['text'].split(',')[0]}, 방향 필요", "system")
            elif c:
                self.set_pending(("cmd", c))
                self.say(f"{c['text']}, 송신할까요", "system")
            else:
                self.set_pending(("voice", text))
                self.say(f"음성 하달, {text}, 송신할까요", "system", long=True)

    def set_pending(self, p) -> None:
        self.pending, self.pending_t = p, time.monotonic()

    def has_pending(self) -> bool:
        if self.pending and time.monotonic() - self.pending_t > 120:
            self.pending = None                 # 2분 지나면 자동 취소
        return self.pending is not None

    def on_confirm(self) -> None:
        kind, obj = self.pending
        self.pending = None
        if kind == "report":
            d = self.desk.send(obj)
            self.send_up([report_event(self.squad, d)])
            self.say("보고 송신", "system")
        elif kind == "cmd":
            self.keypad_send(obj)
            self.say(f"{obj['text']}, 송신", "system")
        elif kind == "voice":
            asyncio.get_running_loop().create_task(self._send_voice(obj))
        elif kind == "battle":
            asyncio.get_running_loop().create_task(self._send_battle())

    def on_battle_end(self) -> None:
        n = len(self.log_db.since(self.battle_t0))
        self.set_pending(("battle", None))
        self.say(f"전투 종료, 기록 {n}건, 전투 데이터 송신할까요", "system")

    async def _send_battle(self) -> None:
        from squad.report.battle import build
        now = time.time()
        events = self.log_db.since(self.battle_t0)
        bid = f"{self.squad}-1-B{time.strftime('%d%H%M', time.localtime(now))}"
        b = await asyncio.to_thread(build, events, self.sit, self.geo, self.squad, f"{self.squad}분대",
                                    self.battle_t0, now, bid, dict(self.ld.live_pos or self.ld.pos))
        e = battle_event(self.squad, b)
        (ROOT / "data" / "leader_app" / f"battle_{bid}.json").write_text(json.dumps(e, ensure_ascii=False))
        self.log_db.add("battle_sent", 0, {"battle_id": bid, "summary": b["summary"], "bytes": b["payload"]["bytes"]})
        log.info("전투 데이터 %s: 기록 %d건, 원본 %dB → 압축 %dB\n%s", bid, len(events), b["payload"]["raw_bytes"],
                 b["payload"]["bytes"], b["text"])
        self.battle_t0 = now                      # 새 전투 구간
        self.battle_file.write_text(str(now))
        if self.srv.clients:
            await self._send_up([e])
            self.say(f"전투 데이터 송신, {b['payload']['bytes'] // 1024 + 1}킬로바이트", "system")
        else:
            self.outbox.append(e)
            self.say("소대장 미연결, 전투 데이터 저장, 연결되면 송신", "system")

    async def _send_voice(self, text: str) -> None:
        from squad.soldier.voice import from_float, prepare_8k
        from squad.speech.verbalize import verbalize
        x = await asyncio.to_thread(self.headset.synth, verbalize(text))
        pcm = prepare_8k(from_float(x), 16000)
        pv = await self.ld.send_voice(pcm, 0, "all")
        self.log_db.add("cmd", 0, {"from": "voice", "text": text, "voice_id": pv.clip.voice_id if pv else None})
        self.say("음성 하달 송신" if pv else "음성 하달 대상 없음", "system")

    def on_cancel(self) -> None:
        self.pending = None
        self.say("취소", "system")

    # ---- 소대장 링크 ----
    def telemetry(self) -> Telemetry:
        src = self.ld.live_pos or self.ld.pos
        err = 3.0 if self.ld.pos_info and self.ld.pos_info.get("measured") else 5.0
        members = {sid: (round(x, 1), round(y, 1), 0, err) for sid, (x, y) in src.items()
                   if sid != 0 and sid in self.ld.allowed}
        return Telemetry(self.geo.lat, self.geo.lon, heading=LEADER_HEADING, err=5.0, source="fixed", members=members)

    def on_order(self, order: dict) -> None:
        oid = order.get("id")
        first = oid not in self.orders_seen
        self.orders_seen.add(oid)
        if self.oled is not None:
            self.oled.show_order(order)
        if not first:                                # 재전송·재연결 재생: 화면만 갱신, 다시 읽지 않음
            log.info("소대장 지시 %s 다시 받음(replay=%s) → 화면만", oid, order.get("replay"))
            return
        self.log_db.add("cmd", 0, {"from": "PL", "order": order})
        text = order.get("text") or (order.get("params") or {}).get("text", "")
        urgent = (order.get("priority") or order.get("prio")) in ("urgent", "flash")
        self.say(f"소대장 지시, {text or order.get('code', '')}", "urgent" if urgent else "command", long=True)

    def on_order_cancel(self, order: dict) -> None:
        self.log_db.add("cmd", 0, {"from": "PL", "cancel": order})
        if self.oled is not None:
            self.oled.cancel_order(order)
        self.say(f"소대장 지시 취소, {order.get('text') or order.get('code', '')}", "command", long=True)

    def on_mission(self, data: dict) -> None:
        self.log_db.add("note", 0, {"from": "PL", "mission": data})
        self.say("소대장 임무 변경" + (", 무선 침묵 지시" if data.get("emcon") else ""), "urgent")

    def on_report_ack(self, d: dict) -> None:
        self.desk.on_ack(d.get("ref"), d.get("rev"))

    def on_report_query(self, d: dict) -> list:
        r = self.desk.on_query(d.get("ref"))
        return [report_event(self.squad, r)] if r else []

    def send_up(self, events: list) -> None:
        asyncio.get_running_loop().create_task(self._send_up(events))

    async def _send_up(self, events: list) -> None:
        n = await self.srv.send(events)
        for e in events:
            log.info("↑ 소대장 %s %s → %d대", e["type"], e["data"].get("summary", ""), n)

    # ---- 적 발견 자동 보고 ----
    def auto_contact(self, observer: str, target: dict, count: int, ts: float, seq: int | None = None) -> None:
        loc = {"bearing": target["bearing"], "dist": target["dist"], "err": target["err"], "dx": target["x"],
               "dy": target["y"], "mgrs": self.geo.mgrs(target["x"], target["y"]), "basis": target["basis"]}
        e = contact_event(self.squad, observer, loc, count, ts, seq=seq)
        self.log_db.add("contact_up", 0, e["data"], ts=ts)
        self.send_up([e])

    # ---- 병사 링크 이벤트 ----
    def on_soldier_event(self, e: dict) -> None:
        k = e["kind"]
        if k == "frame":
            m, sid = e["msg"], e["sid"]
            if m["type"] not in REPORT_TYPES:
                return
            self.log_db.add("soldier", sid, {"hex": fc.to_hex(e["raw"]), "desc": describe(m), "retx": e["retransmit"],
                                             **({"target": e["target"]} if "target" in e else {})}, ts=e["ts"])
            if e["retransmit"]:
                return
            s = report_sentence(m)
            if s:
                self.say(*s)
            if self.desk.on_events(self.sit.on_report(sid, m["type"], m, e["ts"])):
                self.say("보고 준비됨", "system")
            if m["type"] == fc.CONTACT:
                self.auto_contact(member_uid(self.squad, sid), e["target"], m["count"], e["ts"], m["seq"])
        elif k in ("pos_table", "pos_live"):
            self.sit.set_positions([(i, x, y, LEADER_HEADING) for i, (x, y) in e["pos"].items() if i != 0])
            if k == "pos_table":
                self.log_db.add("pos", 0, {"pos": {str(i): [round(v, 1) for v in p] for i, p in e["pos"].items()}})
        elif k == "link" and e["up"] and not self.ld.pos:      # 첫 연결: 기본 대형 위치표부터
            asyncio.get_running_loop().create_task(self.ld.send_pos_preset(self.a.formation))
            self.sit.set_link(e["sid"], True, time.time())
        elif k == "cmd_unacked":
            self.say(unacked_sentence(e["sids"]), "urgent")
            self.log_db.add("note", 0, {"unacked": e})
        elif k == "silent_blocked":
            self.say("침묵 중, 보드 A 버튼 사용", "system")
        elif k == "link":
            self.sit.set_link(e["sid"], e["up"], time.time())

    # ---- 키패드 ----
    def keypad_send(self, d: dict) -> None:
        async def go():
            pc = await self.ld.send_cmd(d["cmd_code"], d["azimuth"], d["dist_band"], d["extra"], d["priority"], d["target"])
            self.log_db.add("cmd", 0, {"from": "keypad", **d, "seq": pc.seq if pc else None})
            if pc is None:
                self.say("송신 대상 없음", "system")
        asyncio.get_running_loop().create_task(go())
        if d["cmd_code"] == fc.CMD_CODES["ENEMY_INFO"] and d["azimuth"] != fc.NO_AZIMUTH:   # 분대장 본인 적 발견
            t = target_estimate(None, d["azimuth"], d["dist_band"])
            t["basis"] = "leader"
            self.auto_contact(self.me, t, d["extra"], time.time())

    def start_keypad(self) -> list:
        from squad.input.keypad import CommandPad, KeyTimer, RouterKeys
        pad = CommandPad(lambda t: self.say(t, "system"), self.keypad_send, on_ptt=self.on_ptt,
                         on_replay=lambda: self.say(self.last_said or "다시 들을 안내 없음", "system"),
                         targets=self.ld.allowed, pending=self.has_pending, on_confirm=self.on_confirm,
                         on_cancel=self.on_cancel, on_battle_end=self.on_battle_end)
        kt = KeyTimer(pad.on_key)
        keys = RouterKeys(lambda key, down, t: kt.feed(key, down, t))

        async def ticker():
            while not self.stop.is_set():
                kt.tick(time.monotonic())
                await asyncio.sleep(0.05)
        return [asyncio.create_task(keys.run()), asyncio.create_task(ticker())]

    # ---- 실행 ----
    async def run(self) -> None:
        try:
            await self.srv.start()
        except OSError as e:
            sys.exit(f"{self.a.host}:{self.a.port} 대기 실패 ({e}). AP를 켰는지 확인(sudo tools/ap_start.sh) 또는 --host 127.0.0.1")
        log.info("분대장 앱 시작: 소대장 링크 %s:%d, 병사 %s, 키패드 %s", self.a.host, self.a.port,
                 ",".join(f"S{i}" for i in self.ld.allowed), "켬" if self.a.keypad else "끔")
        # 병사 링크·소대장 링크·키패드는 바로 시작하고, 무거운 모델(STT 약 33초, 보고서 LLM 약 8초)은 뒤에서 읽는다.
        # 그 사이 A·B·C를 누르면 "음성 인식 준비 중"(보고서는 LLM 준비 전이면 규칙으로 채움).
        tasks = [asyncio.create_task(self.link.run()), asyncio.create_task(self.ld.watch(self.stop)),
                 asyncio.create_task(self.ld.auto_pos_loop(self.stop)), asyncio.create_task(self.resend_loop())]
        if self.a.keypad:
            tasks += self.start_keypad()
        if self.oled is not None:
            tasks.append(asyncio.create_task(self.oled.run(self.stop)))
        asyncio.get_running_loop().create_task(self._load_models())
        await self.cli()
        self.link.stop.set()
        for t in tasks[1:]:
            t.cancel()
        try:                                         # 병사 연결 정상 해제(최대 10초)
            await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 10.0)
        except asyncio.TimeoutError:
            log.warning("종료 정리 시간 초과 → 그대로 종료")
        await self.srv.close()
        self.ld.txlog.close()
        if self.llm is not None:
            self.llm.close()

    async def _load_models(self) -> None:
        if self.headset is not None:
            await self.headset.start()                       # 마이크 수신은 즉시, STT는 읽는 동안 기다림
            asyncio.get_running_loop().run_in_executor(None, self.headset.warm, WARM_PHRASES)
        await self._load_manual()
        if self.a.llm.lower() != "none":
            await self._load_llm()
        self.say("분대장 단말 준비 완료", "system")

    async def _load_manual(self) -> None:
        def load():
            from squad.manual.schema import load_kb
            from squad.manual.search import ManualIndex
            return ManualIndex(*load_kb(ROOT / "data" / "manual_kb"))
        t = time.monotonic()
        self.manual = await asyncio.to_thread(load)
        log.info("교범 색인 준비 %.0f초", time.monotonic() - t)

    async def _load_llm(self) -> None:
        def load():
            from squad.manual.llm import LocalLLM
            llm = LocalLLM(Path(self.a.llm))
            llm.name = Path(self.a.llm).stem
            llm.chat("", "안녕", 4)                    # 서버 기동·예열
            return llm
        t = time.monotonic()
        try:
            self.llm = await asyncio.to_thread(load)
            log.info("보고서 LLM 준비 %.0f초: %s", time.monotonic() - t, self.llm.name)
        except Exception as e:  # noqa: BLE001 - LLM 없으면 규칙으로 채운다
            log.warning("보고서 LLM 기동 실패(%r) → 규칙 추출로 채움", e)

    async def resend_loop(self) -> None:
        last_pos = 0.0
        while not self.stop.is_set():
            await asyncio.sleep(2)
            if self.outbox and self.srv.clients:          # 통신 확보 → 쌓인 전투 데이터 송신
                out, self.outbox = self.outbox, []
                await self._send_up(out)
                self.say("저장된 전투 데이터 송신", "system")
            if time.time() - last_pos >= 30:              # 분대장 이동 경로(GPS 붙기 전에는 고정 원점)
                last_pos = time.time()
                self.log_db.add("leader_pos", 0, {"lat": self.geo.lat, "lon": self.geo.lon, "mgrs": self.geo.mgrs(0, 0)})
            for d in self.desk.due_resends():
                await self.srv.send([report_event(self.squad, d)])

    async def cli(self) -> None:
        from soldier_cli import handle
        loop = asyncio.get_running_loop()
        lines: asyncio.Queue = asyncio.Queue()

        def reader():
            for raw in sys.stdin:
                loop.call_soon_threadsafe(lines.put_nowait, raw)
            loop.call_soon_threadsafe(lines.put_nowait, None)
        threading.Thread(target=reader, daemon=True).start()
        while not self.stop.is_set():
            line = await lines.get()
            if line is None:
                if self.a.stdin_eof_quit:
                    break
                await self.stop.wait()
                break
            try:
                await handle(self.ld, self.link, line.strip(), self.stop)
            except ValueError as e:
                log.info("오류: %s", e)
        self.stop.set()


async def main() -> None:
    ap = argparse.ArgumentParser(description="분대장 통합 실행기")
    ap.add_argument("--host", default=AP_IP)
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--squad", default="1")
    ap.add_argument("--only", help="연결할 병사, 예: S1,S2 (기본 S1~S5)")
    ap.add_argument("--lat", type=float, default=DEMO_LAT)
    ap.add_argument("--lon", type=float, default=DEMO_LON)
    ap.add_argument("--no-keypad", dest="keypad", action="store_false")
    ap.add_argument("--formation", default="line", choices=("line", "wedge", "column"), help="기본 대형(기본 횡대)")
    ap.add_argument("--no-autopos", dest="autopos", action="store_false", help="실측 위치 자동 갱신 끄기(대형 고정)")
    ap.add_argument("--seq-start", type=int)
    ap.add_argument("--llm", default=str(ROOT / "models" / "llm" / "sq-nlu-qwen2.5-0.5b-instruct-q4_0.gguf"),
                    help="정형화된 보고서 빈칸 채우기 미세조정 모델 gguf. 'none'이면 규칙만")
    ap.add_argument("--no-oled", dest="oled", action="store_false", help="OLED(MCU I2C) 표시 끄기")
    ap.add_argument("--no-audio", dest="audio", action="store_false", help="헤드셋(맥 마이크·TTS) 없이 로그만")
    ap.add_argument("--stdin-eof-quit", action="store_true", help="표준입력이 끝나면 종료(기본: 계속 실행)")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S", stream=sys.stdout)
    l7 = logging.getLogger("soldier.log7f")
    l7.propagate = False
    (ROOT / "data" / "leader_app").mkdir(parents=True, exist_ok=True)
    l7.addHandler(logging.FileHandler(ROOT / "data" / "leader_app" / "log7f.txt", encoding="utf-8"))
    app = LeaderApp(a)
    import signal
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):        # systemd stop·재시작: 병사 연결을 정상으로 끊고 내려간다
        loop.add_signal_handler(sig, app.stop.set)
    await app.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
