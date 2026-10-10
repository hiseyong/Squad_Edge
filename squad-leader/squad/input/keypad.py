"""분대장 4×4 키패드 입력 (계획서 §9 v2).

MCU(mcu/keypad/keypad.ino)가 arduino-router로 보내는 키 눌림/뗌 → 짧게·길게·누르고 있기 판정 → 동작.
  - RouterKeys: /run/arduino-router.sock에 "keypad"를 등록하고 (key, down) 알림을 받는다(msgpack-RPC).
  - KeyTimer: 시각만으로 짧게/길게/PTT를 판정한다(시험 가능하게 BLE·소켓 없음).
  - CommandPad: 명령 입력 상태기계 → CMD_BUTTON 필드 + 복창 문장. 병사 링크를 모른다(결과 dict만 낸다).

키 배치                     짧게                                     길게(≥1.0 s) / 누르고 있기
  A  보고 PTT               —                                        누르는 동안 말함(ptt)
  B  교범 질문 PTT          —                                        누르는 동안 질문(ptt)
  C  병사 음성 하달 PTT     —                                        누르는 동안 말함(ptt)
  D                         대상 순환 전원→1번…→전원                거리 순환 없음→근→중→원 / (입력 없을 때) 전투 종료
  0~9                       명령 선택(적 위치에서 9 다시 = 적 수 순환) 방향 N시(1 길게 뒤 0·1·2 짧게 = 10·11·12시)
  *                         입력 취소 / (입력 없음) 취소 명령       상태 보고 요청 명령
  #                         송신 확정 / (입력 없음) 마지막 안내     무선 침묵 명령
  확인 대기(A 보고 복창, C 음성 하달 복창) 중이면  # 짧게 = 송신, * 짧게 = 취소
방위는 분대장 방위 0 고정(병사 팀 안내문 D5): azimuth = (시계 × 30) mod 360. 집결은 항상 방향 없음.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Callable

log = logging.getLogger("input.keypad")

ROUTER_SOCK = "/run/arduino-router.sock"
LONG_S = 1.0           # 길게 판정(병사 단말과 같은 기준)
TENS_WINDOW_S = 1.5    # "1" 길게 뒤 0·1·2를 기다리는 시간(10·11·12시)
PTT_KEYS = {"A": "report", "B": "manual", "C": "voice_cmd"}

# 명령 코드(병사 프로토콜 §6). 키 → (cmd_code, 이름, 방향 규칙, 거리 허용, 우선순위)
#   방향 규칙: "none" 없음, "opt" 선택, "req" 필수, "never" 항상 없음(집결)
CMDS = {
    "1": (0x01, "정지", "none", False, 1),
    "2": (0x02, "엄폐", "opt", False, 1),
    "3": (0x03, "전진", "opt", False, 0),
    "4": (0x04, "후퇴", "opt", False, 1),
    "5": (0x05, "집결", "never", False, 0),
    "6": (0x06, "사격 개시", "req", True, 1),
    "7": (0x07, "사격 중지", "none", False, 1),
    "8": (0x08, "경계", "req", False, 0),
    "9": (0x09, "적 위치", "req", True, 0),
    "0": (0x0C, "고수", "none", False, 0),
    "*": (0x0F, "취소", "none", False, 0),
    "*L": (0x0A, "상태 보고", "none", False, 0),
    "#L": (0x0B, "무선 침묵", "none", False, 1),
}
NO_AZIMUTH, NO_DIST = 0xFFFF, 0xFF
DIST_TEXT = {0: "근거리", 1: "중거리", 2: "원거리"}
DIST_CYCLE = [NO_DIST, 0, 1, 2]


def count_text(n: int) -> str:
    return {0: "적 수 미상", 5: "적 다수"}.get(n, f"적 {n}명")


# ---------------- 키 판정 ----------------
@dataclass
class KeyTimer:
    """(key, down, t) → on_key(kind, key). kind: short | long | ptt_down | ptt_up.
    길게는 누르고 있는 동안 1초가 되는 순간 낸다(뗄 때가 아니라) → 분대장이 바로 확인음을 들을 수 있다."""
    on_key: Callable[[str, str], None]
    long_s: float = LONG_S
    _down: dict = field(default_factory=dict)          # key → (t, long_sent)

    def feed(self, key: str, down: bool, t: float) -> None:
        if key in PTT_KEYS:
            self.on_key("ptt_down" if down else "ptt_up", key)
            return
        if down:
            self._down[key] = [t, False]
            return
        st = self._down.pop(key, None)
        if st is not None and not st[1]:
            self.on_key("long" if t - st[0] >= self.long_s else "short", key)

    def tick(self, t: float) -> None:
        """주기 호출: 누르고 있는 키가 1초를 넘으면 그때 '길게'."""
        for key, st in self._down.items():
            if not st[1] and t - st[0] >= self.long_s:
                st[1] = True
                self.on_key("long", key)


# ---------------- 명령 입력 ----------------
@dataclass
class CommandPad:
    """키 판정 → 명령 조립. say(text): 헤드셋 안내, send(cmd: dict): CMD_BUTTON 필드로 하달 요청.
    send 인자: {"cmd_code", "azimuth", "dist_band", "extra", "priority", "target", "text"}."""
    say: Callable[[str], None]
    send: Callable[[dict], None]
    on_ptt: Callable[[str, bool], None] = lambda kind, down: None
    on_replay: Callable[[], None] = lambda: None
    # 확인 대기(보고서 복창·음성 하달 복창 등)가 있으면 #/* 짧게는 그쪽으로: 송신 / 취소
    pending: Callable[[], bool] = lambda: False
    on_confirm: Callable[[], None] = lambda: None
    on_cancel: Callable[[], None] = lambda: None
    on_battle_end: Callable[[], None] = lambda: None   # 명령 입력이 없을 때 D 길게 = 전투 종료(전투 데이터 보고)
    targets: tuple[int, ...] = (1, 2, 3, 4, 5)
    clock_fn: Callable[[], float] = time.monotonic
    target: str = "all"
    cmd: str | None = None             # CMDS 키
    clock: int = 0
    dist: int = NO_DIST
    count: int = 0
    tens_until: float = 0.0

    # 상태
    def reset(self) -> None:
        self.cmd, self.clock, self.dist, self.count, self.tens_until = None, 0, NO_DIST, 0, 0.0

    def target_text(self) -> str:
        return "전원" if self.target == "all" else f"{self.target}번"

    def summary(self) -> str:
        code, name, rule, dist_ok, _ = CMDS[self.cmd]
        parts = [name]
        if self.cmd == "9":
            parts.append(count_text(self.count))
        if self.clock and rule != "never":
            parts.append(f"{self.clock}시")
        if dist_ok and self.dist != NO_DIST:
            parts.append(DIST_TEXT[self.dist])
        parts.append(self.target_text())
        return ", ".join(parts)

    # 키
    def on_key(self, kind: str, key: str) -> None:
        if kind in ("ptt_down", "ptt_up"):
            self.on_ptt(PTT_KEYS[key], kind == "ptt_down")
            return
        now = self.clock_fn()
        if key.isdigit():
            self._digit(kind, int(key), now)
        elif key == "D":
            self._d(kind)
        elif key == "*":
            self._star(kind)
        elif key == "#":
            self._hash(kind)

    def _digit(self, kind: str, d: int, now: float) -> None:
        if kind == "long":                                  # 방향
            if self.cmd is None:
                self.say("명령 먼저")
                return
            self.clock = 12 if d == 0 else d
            self.tens_until = now + TENS_WINDOW_S if d == 1 else 0.0
            self.say(f"{self.clock}시")
            return
        if self.tens_until and now <= self.tens_until and d in (0, 1, 2):   # 1 길게 → 0·1·2 = 10·11·12시
            self.clock, self.tens_until = 10 + d, 0.0
            self.say(f"{self.clock}시")
            return
        self.tens_until = 0.0
        if self.cmd == "9" and d == 9:                      # 적 위치에서 9 다시 → 적 수 순환 미상→1→…→다수
            self.count = (self.count + 1) % 6
            self.say(count_text(self.count))
            return
        self.reset()
        self.cmd = str(d)
        self.say(CMDS[self.cmd][1])

    def _d(self, kind: str) -> None:
        if kind == "short":
            order = ["all"] + [str(i) for i in self.targets]
            self.target = order[(order.index(self.target) + 1) % len(order)] if self.target in order else "all"
            self.say(self.target_text())
            return
        if self.cmd is None:
            self.on_battle_end()
            return
        if not CMDS[self.cmd][3]:
            self.say("거리 없음")
            return
        self.dist = DIST_CYCLE[(DIST_CYCLE.index(self.dist) + 1) % len(DIST_CYCLE)]
        self.say(DIST_TEXT.get(self.dist, "거리 없음"))

    def _star(self, kind: str) -> None:
        if kind == "short" and self.cmd is None and self.pending():
            self.on_cancel()
            return
        if kind == "long":
            self.reset()
            self.cmd = "*L"
            self.say(CMDS["*L"][1])
            return
        if self.cmd is not None:
            self.reset()
            self.say("입력 취소")
            return
        self.cmd = "*"
        self.say(CMDS["*"][1])

    def _hash(self, kind: str) -> None:
        if kind == "short" and self.cmd is None and self.pending():
            self.on_confirm()
            return
        if kind == "long":
            self.reset()
            self.cmd = "#L"
            self.say(CMDS["#L"][1])
            return
        if self.cmd is None:
            self.on_replay()
            return
        code, name, rule, dist_ok, prio = CMDS[self.cmd]
        if rule == "req" and not self.clock:
            self.say(f"{name}, 방향 필요")
            return
        az = NO_AZIMUTH if rule in ("none", "never") or not self.clock else (self.clock * 30) % 360
        text = self.summary()
        self.send({"cmd_code": code, "azimuth": az, "dist_band": self.dist if dist_ok else NO_DIST,
                   "extra": self.count if self.cmd == "9" else 0, "priority": prio, "target": self.target,
                   "text": text})
        self.say(f"{text}, 송신")
        self.reset()


# ---------------- arduino-router 연결 ----------------
class RouterKeys:
    """MCU 알림 "keypad"(key, down) 수신. 끊기면 2초 뒤 다시 등록."""

    def __init__(self, on_raw: Callable[[str, bool, float], None], sock: str = ROUTER_SOCK):
        self.on_raw, self.sock = on_raw, sock
        self.stop = asyncio.Event()
        self.connected = False

    async def run(self) -> None:
        import msgpack
        while not self.stop.is_set():
            try:
                reader, writer = await asyncio.open_unix_connection(self.sock)
                writer.write(msgpack.packb([0, 1, "$/register", ["keypad"]]))
                await writer.drain()
                up = msgpack.Unpacker(raw=False)
                while not self.stop.is_set():
                    data = await reader.read(4096)
                    if not data:
                        break
                    up.feed(data)
                    for m in up:
                        if m[0] == 1 and m[1] == 1:
                            self.connected = m[2] is None
                            log.info("키패드 등록 %s", "됨" if self.connected else f"실패 {m[2]}")
                        elif m[0] == 2 and m[1] == "keypad":
                            key, down = m[2][0], bool(m[2][1])
                            self.on_raw(key, down, time.monotonic())
                        elif m[0] == 0:                       # 요청 형태로 오면 빈 응답
                            writer.write(msgpack.packb([1, m[1], None, None]))
                writer.close()
            except OSError as e:
                log.warning("arduino-router 연결 실패: %s", e)
            self.connected = False
            await asyncio.sleep(2.0)
