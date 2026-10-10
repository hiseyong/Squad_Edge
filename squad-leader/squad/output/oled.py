"""분대장 OLED(SSD1306 128×64, MCU I2C) — 소대장 명령 표시.

화면은 여기서 나눔고딕으로 그려(한글) 1비트 → 페이지(8줄 = 128바이트) 8개로 바꿔 MCU에 보낸다.
MCU 스케치: mcu/leader_io/leader_io.ino (arduino-router RPC "oled_page", "oled_clear", "oled_ok").
바뀐 페이지만 보낸다(RPC 한 번 256B 제한, I2C 시간 절약).

배치
  맨 위 막대(반전, 14px): [긴급] FRAGO   21:05   (취소되면 [취소])
  아래 4줄(12px): 명령 문장 자동 줄바꿈. 4줄을 넘으면 SCROLL_S마다 한 줄씩 올려 끝까지 보여 주고 처음으로.
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger("oled")

ROOT = Path(__file__).resolve().parents[2]
FONT = ROOT / "manuals" / "fonts" / "NanumGothic-Bold.ttf"
W, H = 128, 64
HEAD_H = 14
LINE_H = 12
BODY_LINES = (H - HEAD_H) // LINE_H          # 4
SCROLL_S = 2.0
PRIO_KO = {"flash": "섬광", "urgent": "긴급", "priority": "우선", "routine": "일반"}


def _font(size: int):
    return ImageFont.truetype(str(FONT), size)


def wrap(text: str, font, width: int = W - 2) -> list[str]:
    """픽셀 폭 기준 줄바꿈(한글은 글자 단위, 공백 우선)."""
    lines, cur = [], ""
    for ch in text.replace("\n", " "):
        trial = cur + ch
        if font.getlength(trial) <= width:
            cur = trial
            continue
        cut = cur.rfind(" ")
        if cut > len(cur) // 2:                      # 단어 경계에서 끊기
            lines.append(cur[:cut])
            cur = cur[cut + 1:] + ch
        else:
            lines.append(cur)
            cur = ch.lstrip()
    if cur.strip():
        lines.append(cur)
    return lines


def render(head: str, right: str, lines: list[str], offset: int = 0) -> Image.Image:
    img = Image.new("1", (W, H), 0)
    d = ImageDraw.Draw(img)
    hf, bf = _font(12), _font(11)
    d.rectangle((0, 0, W - 1, HEAD_H - 1), fill=1)
    d.text((2, 0), head, font=hf, fill=0)
    d.text((W - 2 - hf.getlength(right), 0), right, font=hf, fill=0)
    for i, ln in enumerate(lines[offset:offset + BODY_LINES]):
        d.text((1, HEAD_H + 1 + i * LINE_H), ln, font=bf, fill=1)
    if len(lines) > BODY_LINES:                      # 스크롤 위치 막대
        n = len(lines) - BODY_LINES + 1
        bar = max(4, (H - HEAD_H) // n)
        y = HEAD_H + (H - HEAD_H - bar) * offset // max(1, n - 1)
        d.line((W - 1, y, W - 1, y + bar), fill=1)
    return img


def to_pages(img: Image.Image) -> list[bytes]:
    """SSD1306 페이지 형식: 페이지 p(0~7)의 열 x 바이트 = 세로 8픽셀(bit0 = 위)."""
    px = img.load()
    pages = []
    for p in range(8):
        col = bytearray(W)
        for x in range(W):
            b = 0
            for bit in range(8):
                if px[x, p * 8 + bit]:
                    b |= 1 << bit
            col[x] = b
        pages.append(bytes(col))
    return pages


class RouterRPC:
    """arduino-router에 msgpack-RPC 호출(MCU가 provide한 함수)."""

    def __init__(self, sock: str = "/run/arduino-router.sock"):
        self.sock = sock
        self._r = self._w = None
        self._id = 100
        self._lock = asyncio.Lock()

    async def call(self, method: str, *params, timeout: float = 2.0):
        import msgpack
        async with self._lock:
            if self._w is None:
                self._r, self._w = await asyncio.open_unix_connection(self.sock)
                self._up = msgpack.Unpacker(raw=False)
            self._id = (self._id + 1) & 0x7FFFFFFF
            mid = self._id
            self._w.write(msgpack.packb([0, mid, method, list(params)], use_bin_type=True))
            await self._w.drain()
            t_end = time.monotonic() + timeout
            while True:
                for m in self._up:
                    if m[0] == 1 and m[1] == mid:
                        if m[2] is not None:
                            raise RuntimeError(f"{method}: {m[2]}")
                        return m[3]
                left = t_end - time.monotonic()
                if left <= 0:
                    raise asyncio.TimeoutError(method)
                data = await asyncio.wait_for(self._r.read(4096), left)
                if not data:
                    self._w = None
                    raise ConnectionError("router closed")
                self._up.feed(data)

    def reset(self):
        if self._w is not None:
            self._w.close()
        self._w = None


class OledDisplay:
    """명령 표시 상태 + 스크롤 루프. show_order / cancel_order / message는 어느 스레드에서 불러도 된다(루프에서 반영)."""

    def __init__(self, rpc: RouterRPC | None = None):
        self.rpc = rpc or RouterRPC()
        self.head, self.right, self.lines = "", "", []
        self.offset = 0
        self.order_id = None
        self._sent: list[bytes | None] = [None] * 8
        self._dirty = asyncio.Event()
        self.ok = False

    def _set(self, head: str, right: str, text: str) -> None:
        self.head, self.right = head, right
        self.lines = wrap(text, _font(11))
        self.offset = 0
        self._dirty.set()

    def show_order(self, order: dict) -> None:
        prio = PRIO_KO.get(order.get("priority") or order.get("prio") or "", "")
        self.order_id = order.get("id")
        hm = time.strftime("%H:%M", time.localtime(order.get("ts") or time.time()))
        self._set(f"[{prio}] {order.get('code', '')}" if prio else str(order.get("code", "")), hm,
                  order.get("text") or order.get("code") or "")

    def cancel_order(self, order: dict) -> None:
        if order.get("id") and order.get("id") != self.order_id:
            return
        self._set(f"[취소] {order.get('code', '')}", time.strftime("%H:%M"), "취소됨: " + (order.get("text") or ""))

    def message(self, head: str, text: str) -> None:
        self._set(head, time.strftime("%H:%M"), text)

    async def _push(self) -> None:
        pages = to_pages(render(self.head, self.right, self.lines, self.offset))
        for p, data in enumerate(pages):
            if data != self._sent[p]:
                await self.rpc.call("oled_page", p, data)
                self._sent[p] = data

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                addr = await self.rpc.call("oled_ok")
                self.ok = bool(addr)
                log.info("OLED %s", f"연결 0x{addr:02X}" if addr else "없음(MCU가 I2C에서 못 찾음)")
                if not self.ok:
                    await asyncio.sleep(10)
                    continue
                self._sent = [None] * 8
                self.message("분대장 단말", "소대장 명령 대기 중")
                last = 0.0
                while not stop.is_set():
                    try:
                        await asyncio.wait_for(self._dirty.wait(), 0.2)
                    except asyncio.TimeoutError:
                        pass
                    now = time.monotonic()
                    if self._dirty.is_set():
                        self._dirty.clear()
                        last = now
                        await self._push()
                    elif len(self.lines) > BODY_LINES and now - last >= SCROLL_S:
                        last = now
                        self.offset = (self.offset + 1) % (len(self.lines) - BODY_LINES + 1)
                        await self._push()
            except (OSError, ConnectionError, asyncio.TimeoutError, RuntimeError) as e:
                log.warning("OLED 통신 실패(%s) → 5초 뒤 다시", e)
                self.rpc.reset()
                await asyncio.sleep(5)
