#!/usr/bin/env python3
"""이어폰 단말(맥) — 병사 단말이 USB 시리얼로 보낸 재생 이벤트를 맥 스피커로 재생한다.

병사 펌웨어 AUDIO_SINK=USB_EARPIECE일 때 사용. BLE 프로토콜과 무관한 로컬 링크(형식: firmware/.../core/earpiece_frame.h).
- PLAY(문장 조각, 예 "c9 cover") → 한국어 문장("9시 엄폐")으로 바꿔 macOS `say`로 읽음
- VOICE_BEGIN/DATA/END(병사가 CRC 검증한 ADPCM) → tools/adpcm.py로 디코딩 → WAV → `afplay`
- --log: 병사의 디버그 LOG 사본(USB)도 출력 — 침묵 모드(BLE 연결 없음)에서 병사 상태를 볼 수 있다.
- 우선순위: 긴급(2) > 일반 명령(1) > 로컬 피드백(0). 더 높은 우선순위가 오면 지금 재생을 끊는다. 겹치지 않게 큐로 순서대로.

외부 의존성 없음(표준 라이브러리 + 같은 폴더의 adpcm.py, frame_codec.py).

사용
    python3 tools/earpiece.py                    # /dev/cu.usbmodem*가 하나면 자동 선택
    python3 tools/earpiece.py --port /dev/cu.usbmodem1101 --id 1 --voice Yuna
    python3 tools/earpiece.py --self-test
"""

import argparse
import glob
import heapq
import itertools
import os
import select
import subprocess
import sys
import tempfile
import termios
import threading
import time
import tty
import wave

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adpcm  # noqa: E402
import frame_codec as fc  # noqa: E402

SYNC = b"\xA5\x5A"
EP_HELLO, EP_PLAY, EP_VOICE_BEGIN, EP_VOICE_DATA, EP_VOICE_END, EP_VOICE_STOP, EP_LOG = 1, 2, 3, 4, 5, 6, 7
PRIO_NAMES = {0: "피드백", 1: "일반", 2: "긴급"}
ERR_SOUND = "/System/Library/Sounds/Basso.aiff"

# 조각 ID → 한국어 (CLAUDE.md §6.5 조각 표와 같은 ID)
KO = {
    "n1": "1명", "n2": "2명", "n3": "3명", "n4": "4명", "many": "다수", "unknown": "미상",
    **{f"c{i}": f"{i}시" for i in range(1, 13)},
    "near": "근거리", "mid": "중거리", "far": "원거리",
    "halt": "정지", "cover": "엄폐", "advance": "전진", "withdraw": "후퇴", "rally": "집결",
    "open_fire": "사격 개시", "cease_fire": "사격 중지", "observe": "경계", "report_status": "상태 보고",
    "silence": "무선 침묵", "hold": "현 위치 고수", "cancel": "취소",
    "enemy": "적", "suspicious": "징후", "hazard": "폭발물 의심", "casualty": "부상자", "friendly": "아군",
    "sent": "송신", "received": "수신", "mode_silent": "침묵", "mode_min": "최소", "mode_normal": "정상",
    "calib_start": "보정 시작", "calib_done": "보정 완료",
}
# 버튼1을 누를 때마다의 피드백은 "1", "2"처럼 숫자만(프로토콜 §9.2)
KO_FEEDBACK = {"n1": "1", "n2": "2", "n3": "3", "n4": "4", "many": "다수"}


def ts():
    return time.strftime("%H:%M:%S")


def log(msg):
    print(f"{ts()} {msg}", flush=True)


def clips_to_korean(text, feedback=False):
    out = []
    for c in text.split():
        if c == "err":
            continue
        out.append((KO_FEEDBACK.get(c) if feedback else None) or KO.get(c, c))
    return " ".join(out)


def encode_frame(ftype, payload):
    body = bytes([ftype, len(payload) & 0xFF, len(payload) >> 8]) + bytes(payload)
    crc = fc.crc16_ccitt_false(body)
    return SYNC + body + bytes([crc & 0xFF, crc >> 8])


class Parser:
    """바이트 스트림 → (type, payload). 동기 바이트·CRC로 경계를 찾고, 깨진 부분은 건너뛴다."""

    def __init__(self):
        self.buf = bytearray()
        self.bad = 0

    def feed(self, data):
        self.buf += data
        out = []
        while True:
            i = self.buf.find(SYNC)
            if i < 0:
                del self.buf[:-1]
                break
            if i:
                del self.buf[:i]
            if len(self.buf) < 5:
                break
            n = self.buf[3] | (self.buf[4] << 8)
            if n > 240:
                del self.buf[:1]
                self.bad += 1
                continue
            if len(self.buf) < 7 + n:
                break
            frame = bytes(self.buf[:7 + n])
            crc = frame[5 + n] | (frame[6 + n] << 8)
            if fc.crc16_ccitt_false(frame[2:5 + n]) != crc:
                del self.buf[:1]
                self.bad += 1
                continue
            out.append((frame[2], frame[5:5 + n]))
            del self.buf[:7 + n]
        return out


class Player(threading.Thread):
    """재생 큐. (우선순위 높은 것 먼저, 같으면 들어온 순서). 더 높은 우선순위가 오면 지금 것을 끊는다."""

    def __init__(self, voice, rate):
        super().__init__(daemon=True)
        self.voice, self.rate = voice, rate
        self.q, self.cv, self.counter = [], threading.Condition(), itertools.count()
        self.proc, self.cur_prio = None, -1

    def put(self, prio, kind, data, label):
        with self.cv:
            heapq.heappush(self.q, (-prio, next(self.counter), kind, data, label))
            if self.proc is not None and prio > self.cur_prio:
                log(f"  ⏹ {PRIO_NAMES[prio]} 재생이 와서 지금 재생({PRIO_NAMES.get(self.cur_prio)})을 끊음")
                self.proc.kill()
            self.cv.notify()

    def run(self):
        while True:
            with self.cv:
                while not self.q:
                    self.cv.wait()
                negp, _, kind, data, label = heapq.heappop(self.q)
                if kind == "say":
                    cmd = ["say", "-v", self.voice] + (["-r", str(self.rate)] if self.rate else []) + [data]
                else:  # "wav"(임시 파일, 재생 후 삭제) / "sound"(시스템 소리)
                    cmd = ["afplay", data]
                self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.cur_prio = -negp
            log(f"  ▶ 재생: {label}")
            self.proc.wait()
            with self.cv:
                self.proc, self.cur_prio = None, -1
            if kind == "wav":
                try:
                    os.unlink(data)
                except OSError:
                    pass


class Earpiece:
    def __init__(self, player, want_id):
        self.player = player
        self.want_id = want_id
        self.parser = Parser()
        self.voices = {}
        self.hello_id = None
        self.show_log = False

    def handle(self, ftype, p):
        if ftype == EP_HELLO:
            if p[0] != self.hello_id:
                self.hello_id = p[0]
                warn = "" if self.want_id in (None, p[0]) else f"  ⚠ --id {self.want_id}와 다름"
                log(f"[S{p[0]}] 이어폰 링크 연결(버전 {p[1]}){warn}")
        elif ftype == EP_PLAY:
            prio, kind, text = p[0], p[1], p[2:].decode("ascii", "replace")
            feedback = kind == 1
            log(f"[S{self.hello_id}] PLAY({'로컬 피드백' if feedback else PRIO_NAMES.get(prio, prio)}): {text}")
            if "err" in text.split():
                self.player.put(prio, "sound", ERR_SOUND, "오류음")
            ko = clips_to_korean(text, feedback)
            if ko:
                self.player.put(prio, "say", ko, f"\"{ko}\"")
        elif ftype == EP_VOICE_BEGIN:
            vid, prio = p[0], p[1]
            pred = int.from_bytes(p[2:4], "little", signed=True)
            idx = p[4]
            nsamples = int.from_bytes(p[5:9], "little")
            nbytes = int.from_bytes(p[9:13], "little")
            self.voices[vid] = dict(prio=prio, pred=pred, idx=idx, nsamples=nsamples, buf=bytearray(nbytes), got=0,
                                    t0=time.monotonic())
            log(f"[S{self.hello_id}] 음성 {vid} 시작: {nsamples}샘플({nsamples / 8000:.1f}초), {nbytes}B, {PRIO_NAMES.get(prio)}")
        elif ftype == EP_VOICE_DATA:
            v = self.voices.get(p[0])
            if v is None:
                return
            off = int.from_bytes(p[1:5], "little")
            data = p[5:]
            if off + len(data) <= len(v["buf"]):
                v["buf"][off:off + len(data)] = data
                v["got"] += len(data)
        elif ftype == EP_VOICE_END:
            vid = p[0]
            v = self.voices.pop(vid, None)
            if v is None:
                return
            crc = int.from_bytes(p[1:3], "little")
            mine = fc.crc16_ccitt_false(bytes(v["buf"]))
            ms = (time.monotonic() - v["t0"]) * 1000
            if v["got"] != len(v["buf"]) or mine != crc:
                log(f"[S{self.hello_id}] 음성 {vid} 버림: 받은 {v['got']}/{len(v['buf'])}B, CRC {mine:04X} vs {crc:04X}")
                return
            samples, _ = adpcm.decode(bytes(v["buf"]), v["nsamples"], v["pred"], v["idx"])
            fd, path = tempfile.mkstemp(suffix=".wav", prefix=f"ear_v{vid}_")
            os.close(fd)
            with wave.open(path, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(8000)
                w.writeframes(b"".join(int(s).to_bytes(2, "little", signed=True) for s in samples))
            log(f"[S{self.hello_id}] 음성 {vid} 수신 완료(USB {ms:.0f}ms, CRC {crc:04X} 일치) → 재생")
            self.player.put(v["prio"], "wav", path, f"음성 {vid}")
        elif ftype == EP_LOG:
            if self.show_log:
                log(f"[S{self.hello_id}] LOG: {p.decode('ascii', 'replace')}")
        elif ftype == EP_VOICE_STOP:
            if self.voices.pop(p[0], None) is not None:
                log(f"[S{self.hello_id}] 음성 {p[0]} 전송 중단")


def pick_port(arg):
    if arg:
        return arg
    ports = sorted(glob.glob("/dev/cu.usbmodem*"))
    if len(ports) == 1:
        return ports[0]
    if not ports:
        return None
    raise SystemExit(f"USB 포트가 여러 개입니다. --port로 고르세요: {', '.join(ports)}")


def bootloader_mounted():
    """보드가 부트로더(NRF52BOOT)면 같은 이름의 포트를 열지 않는다 — 업로드(nrfutil)와 포트를 다투지 않게."""
    return bool(glob.glob("/Volumes/NRF52BOOT*"))


def open_port(path):
    fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    tty.setraw(fd)
    attrs = termios.tcgetattr(fd)
    attrs[4] = attrs[5] = termios.B115200  # CDC라 속도는 의미 없지만 명시
    termios.tcsetattr(fd, termios.TCSANOW, attrs)
    return fd


def run(args):
    player = Player(args.voice, args.rate)
    player.start()
    ear = Earpiece(player, args.id)
    ear.show_log = args.log
    log(f"이어폰 단말 시작(음성 {args.voice}). Ctrl+C로 종료")
    waiting_logged = False
    while True:
        if bootloader_mounted():
            if not waiting_logged:
                log("보드가 부트로더 상태(NRF52BOOT) → 업로드가 끝날 때까지 포트를 열지 않고 기다림")
                waiting_logged = True
            time.sleep(1.0)
            continue
        path = pick_port(args.port)
        if path is None or not os.path.exists(path):
            if not waiting_logged:
                log("USB 포트를 기다리는 중 …(보드를 USB로 연결)")
                waiting_logged = True
            time.sleep(1.0)
            continue
        try:
            fd = open_port(path)
        except OSError as e:
            log(f"{path} 열기 실패: {e}")
            time.sleep(1.0)
            continue
        log(f"{path} 열림(DTR 켜짐 → 병사가 송신 시작)")
        waiting_logged = False
        try:
            while True:
                r, _, _ = select.select([fd], [], [], 1.0)
                if not r:
                    continue
                data = os.read(fd, 4096)
                if not data:
                    raise OSError("포트 닫힘")
                for ftype, p in ear.parser.feed(data):
                    ear.handle(ftype, p)
        except OSError as e:
            log(f"{path} 연결 끊김({e}) → 다시 기다림")
            ear.hello_id = None
            try:
                os.close(fd)
            except OSError:
                pass
            time.sleep(1.0)


def self_test():
    # C 호스트 테스트(test_earpiece.cpp)와 같은 기준 벡터
    f = encode_frame(EP_PLAY, bytes([2, 0]) + b"c9 cover")
    assert fc.to_hex(f) == "A5 5A 02 0A 00 02 00 63 39 20 63 6F 76 65 72 16 D9", fc.to_hex(f)
    # 쓰레기 + 깨진 프레임 + 정상 프레임을 쪼개서 넣어도 정상 프레임만 나온다
    bad = bytearray(f)
    bad[8] ^= 0xFF
    stream = b"\x00\xA5\x13" + bytes(bad) + f + encode_frame(EP_HELLO, bytes([1, 1]))
    pz, got = Parser(), []
    for i in range(0, len(stream), 3):
        got += pz.feed(stream[i:i + 3])
    assert got == [(EP_PLAY, bytes([2, 0]) + b"c9 cover"), (EP_HELLO, bytes([1, 1]))], got
    assert clips_to_korean("c9 cover") == "9시 엄폐"
    assert clips_to_korean("enemy n3 c2 far") == "적 3명 2시 원거리"
    assert clips_to_korean("n2", feedback=True) == "2"
    assert clips_to_korean("enemy sent", feedback=True) == "적 송신"
    print("earpiece self-test OK")


def main():
    ap = argparse.ArgumentParser(description="이어폰 단말(맥): 병사 단말 USB 재생 이벤트 → 맥 스피커")
    ap.add_argument("--port", help="/dev/cu.usbmodem… (생략하면 하나뿐일 때 자동)")
    ap.add_argument("--id", type=int, help="기대하는 병사 ID(HELLO와 다르면 경고)")
    ap.add_argument("--voice", default="Yuna", help="macOS say 한국어 음성(기본 Yuna). 목록: say -v '?' | grep ko_KR")
    ap.add_argument("--rate", type=int, default=0, help="say 말하기 속도(단어/분, 0 = 기본)")
    ap.add_argument("--log", action="store_true", help="병사 디버그 LOG 사본도 출력(침묵 모드에서 BLE 없이 상태 확인)")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        self_test()
        return
    try:
        run(args)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
