"""[맥에서 실행] 에어팟 마이크 → 보드로 PCM 스트림 송신 + 보드가 보낸 음성(TTS)을 에어팟으로 재생.

준비 (맥):
    pip3 install sounddevice numpy
    adb forward tcp:7100 tcp:7100
실행:
    python3 mac_mic_sender.py --list          # 입력 장치 목록
    python3 mac_mic_sender.py                 # 이름에 'AirPods'가 있는 장치 자동 선택
    python3 mac_mic_sender.py --device 3      # 번호로 지정

장치의 기본 샘플레이트 그대로 보내고(맥 쪽 변환 없음), 보드가 16kHz 모노로 맞춘다.
보드 → 맥 방향(같은 연결): b"A"+uint32 sr+uint32 nbytes+PCM(s16le 모노) = 재생, b"S" = 즉시 중단.
연결이 끊기면 2초마다 재접속한다.
"""
import argparse
import json
import queue
import socket
import struct
import sys
import threading
import time

import sounddevice as sd


def pick_device(name_hint: str):
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0 and name_hint.lower() in d["name"].lower():
            return i
    return None


class Playback:
    """보드가 보낸 PCM을 이어서 재생. 16kHz 모노 고정(보드가 맞춰서 보냄)."""

    def __init__(self, device, sr=16000):
        self.buf = bytearray()
        self.lock = threading.Lock()
        self.stream = sd.RawOutputStream(device=device, samplerate=sr, channels=1, dtype="int16",
                                         blocksize=int(sr * 0.02), callback=self._cb)
        self.stream.start()

    def _cb(self, outdata, frames, t, status):
        n = frames * 2
        with self.lock:
            chunk = bytes(self.buf[:n])
            del self.buf[:n]
        outdata[:len(chunk)] = chunk
        outdata[len(chunk):] = b"\x00" * (n - len(chunk))

    def add(self, pcm: bytes):
        with self.lock:
            self.buf += pcm

    def clear(self):
        with self.lock:
            self.buf.clear()


def recv_exact(s, n):
    data = b""
    while len(data) < n:
        part = s.recv(n - len(data))
        if not part:
            raise ConnectionError("closed")
        data += part
    return data


def reader(s, playback):
    try:
        while True:
            kind = recv_exact(s, 1)
            if kind == b"A":
                sr, n = struct.unpack("<II", recv_exact(s, 8))
                playback.add(recv_exact(s, n))
            elif kind == b"S":
                playback.clear()
    except (ConnectionError, OSError):
        pass


def pick_output(name_hint: str):
    for i, d in enumerate(sd.query_devices()):
        if d["max_output_channels"] > 0 and name_hint.lower() in d["name"].lower():
            return i
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--device", type=int)
    ap.add_argument("--name", default="AirPods")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7100)
    args = ap.parse_args()

    if args.list:
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0:
                print(f"{i:3d}  {d['name']}  ({d['max_input_channels']}ch, {d['default_samplerate']:.0f}Hz)")
        return

    dev = args.device if args.device is not None else pick_device(args.name)
    if dev is None:
        sys.exit(f"'{args.name}' 입력 장치를 못 찾음. --list 로 확인 후 --device 지정")
    info = sd.query_devices(dev)
    sr = int(info["default_samplerate"])
    ch = 1
    print(f"입력: [{dev}] {info['name']} {sr}Hz")

    out_dev = pick_output(args.name)
    print(f"출력: {sd.query_devices(out_dev)['name'] if out_dev is not None else '기본 출력 장치'}")
    playback = Playback(out_dev)

    q: queue.Queue[bytes] = queue.Queue(maxsize=200)

    def cb(indata, frames, t, status):
        if status:
            print(status, file=sys.stderr)
        try:
            q.put_nowait(bytes(indata))
        except queue.Full:
            pass  # 보드 연결이 막혔을 때 맥 메모리가 쌓이지 않게 버림

    header = json.dumps({"v": 1, "sr": sr, "ch": ch, "fmt": "s16le", "device": info["name"]}) + "\n"
    with sd.RawInputStream(device=dev, samplerate=sr, channels=ch, dtype="int16",
                           blocksize=int(sr * 0.02), callback=cb):
        while True:
            try:
                with socket.create_connection((args.host, args.port), timeout=3) as s:
                    s.settimeout(None)
                    s.sendall(header.encode())
                    print("보드 연결됨. Ctrl+C로 종료")
                    threading.Thread(target=reader, args=(s, playback), daemon=True).start()
                    while not q.empty():
                        q.get_nowait()
                    while True:
                        s.sendall(q.get())
            except KeyboardInterrupt:
                return
            except OSError as e:
                print(f"연결 실패/끊김 ({e}). adb forward tcp:{args.port} tcp:{args.port} 확인. 2초 후 재시도")
                time.sleep(2)


if __name__ == "__main__":
    main()
