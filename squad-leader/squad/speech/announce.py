"""수신 내용을 헤드셋 낭독 항목으로 바꾼다.

1) 병사 이진 보고(명세 v1.0.2 §5.1) → §10.3 문장 템플릿 → 미리 합성한 조각을 이어 붙여 즉시 재생
2) 상급 부대(소대장·중대·대대) 텍스트 메시지 → 그대로 읽기 (요약·핵심 추출은 중대 측 담당)

방향은 분대장 기준 시계 방향으로 바꿔 읽는다(명세 §1: "몇 시" 변환은 받는 쪽에서).
분대장 방위를 모르면 절대 방위("방위 이백칠십 도")로 읽는다.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Callable

from ..audio.arbiter import AudioArbiter, Item, Priority
from ..protocol import AZ_NONE, DIST_NONE, HEADING_NONE, RESERVED, Frame, FrameError, Msg, azimuth_to_clock, parse_report
from .tts import Synth
from .verbalize import native

DIST = {0: "근거리", 1: "중거리", 2: "원거리"}
COUNT = {0: "적 수 미상", 5: "적 다수"}
EMCON_NAME = {0: "침묵", 1: "최소", 2: "정상"}
VOICE_FAIL = {1: "음성 오류", 2: "음성 일부 누락", 3: "음성 수신 불가"}


def _count(n: int) -> str:
    return COUNT.get(n, f"적 {native(n)} 명")


def _direction(azimuth: int, leader_heading: int | None) -> str:
    if azimuth == AZ_NONE:
        return "방향 미상"
    if leader_heading is None or leader_heading == HEADING_NONE:
        return f"방위 {azimuth}도"
    return f"{azimuth_to_clock(azimuth, leader_heading)}시 방향"


def report_phrases(frame: Frame, leader_heading: int | None) -> tuple[list[str], Priority, int] | None:
    """병사 보고 프레임 → (문장 조각들, 우선순위, 반복 횟수). 읽지 않는 종류는 None."""
    if frame.msg_type in RESERVED:
        return None
    f = parse_report(frame)
    n = f"{frame.src_id}번"
    t = frame.msg_type
    if t == Msg.CONTACT:
        parts = [n, _count(f["count"]), _direction(f["azimuth"], leader_heading)]
        if f["dist_band"] != DIST_NONE:
            parts.append(DIST.get(f["dist_band"], "거리 미상"))
        return parts, Priority.REPORT, 1
    if t == Msg.SUSPICIOUS:
        return [n, "징후", _direction(f["azimuth"], leader_heading)], Priority.REPORT, 1
    if t == Msg.HAZARD:
        return [n, "폭발물 의심", _direction(f["azimuth"], leader_heading)], Priority.REPORT, 1
    if t == Msg.CASUALTY_FOUND:
        return [n, "부상자 발견", _direction(f["azimuth"], leader_heading)], Priority.REPORT, 1
    if t == Msg.OK_READY:
        return [n, "이상 없음"], Priority.REPORT, 1
    if t == Msg.WEAPON_AMMO:
        return [n, "탄약 화기 문제"], Priority.REPORT, 1
    if t == Msg.CASUALTY_SELF:
        return [f"{n} 부상"], Priority.URGENT, 2          # §10.3: 최우선, 반복 2회
    if t == Msg.ACK:
        return [n, "수신"], Priority.REPORT, 1
    if t == Msg.CANNOT_COMPLY:
        return [n, "수행 불가"], Priority.REPORT, 1
    if t == Msg.VOICE_RESULT and f["status"]:
        return [n, VOICE_FAIL.get(f["status"], "음성 오류")], Priority.REPORT, 1
    if t == Msg.EMCON_STATE:
        return [n, f"{EMCON_NAME.get(f['mode'], '모드')} 모드"], Priority.SYSTEM, 1
    return None


def phrase_bank() -> list[str]:
    """미리 합성할 조각 목록 (병사 보고 템플릿에 나오는 모든 조각)."""
    bank = [f"{i}번" for i in range(1, 6)] + [f"{i}번 부상" for i in range(1, 6)]
    bank += [_count(c) for c in range(0, 6)]
    bank += [f"{c}시 방향" for c in range(1, 13)] + ["방향 미상"]
    bank += list(DIST.values()) + ["징후", "폭발물 의심", "부상자 발견", "이상 없음", "탄약 화기 문제",
                                   "수신", "수행 불가", "미수신"] + list(VOICE_FAIL.values())
    bank += [f"{v} 모드" for v in EMCON_NAME.values()]
    return bank


# ---- 상급 부대 메시지 (초안: 분대장↔소대장 형식은 미확정) ----

SOURCE_NAME = {"platoon": "소대장", "company": "중대", "battalion": "대대",
               "소대장": "소대장", "중대": "중대", "대대": "대대"}
PREC = {"FLASH": Priority.URGENT, "IMMEDIATE": Priority.COMMAND,
        "PRIORITY": Priority.COMMAND, "ROUTINE": Priority.COMMAND}
PREC_WORD = {"FLASH": "긴급", "IMMEDIATE": "즉각"}


@dataclass
class UpperMessage:
    """초안 형식: {"v":1, "from":"platoon|company|battalion", "prec":"FLASH|IMMEDIATE|PRIORITY|ROUTINE",
    "id":"...", "text":"..."}  — 텍스트는 상급 부대가 이미 요약·정리해서 보낸다는 전제."""
    source: str
    text: str
    prec: str = "ROUTINE"
    id: str = ""

    @classmethod
    def from_json(cls, data: str | bytes) -> "UpperMessage":
        d = json.loads(data)
        return cls(source=d["from"], text=d["text"], prec=d.get("prec", "ROUTINE").upper(), id=str(d.get("id", "")))

    def spoken(self) -> str:
        who = SOURCE_NAME.get(self.source, self.source)
        head = f"{PREC_WORD[self.prec]}. " if self.prec in PREC_WORD else ""
        return f"{head}{who} 전달. {self.text.strip()}"

    @property
    def priority(self) -> Priority:
        return PREC.get(self.prec, Priority.COMMAND)


# ---- 낭독기 ----

@dataclass
class Announcer:
    """수신 → 낭독 항목 생성 → 출력 중재기에 제출. 같은 보고의 재전송(같은 seq)은 한 번만 읽는다."""
    synth: Synth
    arbiter: AudioArbiter
    leader_heading: Callable[[], int | None] = lambda: None
    dedupe_s: float = 60.0
    log: list[str] = field(default_factory=list)
    _seen: dict = field(default_factory=dict)

    def _dup(self, key) -> bool:
        now = time.monotonic()
        self._seen = {k: t for k, t in self._seen.items() if now - t < self.dedupe_s}
        if key in self._seen:
            return True
        self._seen[key] = now
        return False

    def on_soldier_frame(self, frame: Frame) -> Item | None:
        if self._dup(("s", frame.src_id, frame.seq, frame.msg_type)):
            return None
        try:
            r = report_phrases(frame, self.leader_heading())
        except FrameError as e:
            self.log.append(f"해석 실패 {frame.src_id}번 0x{frame.msg_type:02x}: {e}")
            return None
        if r is None:
            self.log.append(f"낭독 안 함: {frame.src_id}번 0x{frame.msg_type:02x}")
            return None
        parts, prio, repeat = r
        audio = self.synth.phrases(parts * repeat)
        item = Item(prio, ", ".join(parts * repeat), source=f"병사{frame.src_id}", audio=audio)
        self.arbiter.submit(item)
        return item

    def on_upper_message(self, msg: UpperMessage) -> Item | None:
        if msg.id and self._dup(("u", msg.source, msg.id)):
            return None
        text = msg.spoken()
        item = Item(msg.priority, text, source=SOURCE_NAME.get(msg.source, msg.source),
                    audio=lambda: self.synth.stream(text))
        self.arbiter.submit(item)
        return item

    def say(self, text: str, priority: Priority = Priority.SYSTEM) -> Item:
        """시스템 안내 (예: "전원 엄폐 송신", "3번 미수신")."""
        item = Item(priority, text, source="시스템", audio=lambda: self.synth.stream(text, cache=True))
        self.arbiter.submit(item)
        return item
