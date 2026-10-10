"""[보드] TTS 낭독 시연: 병사 이진 보고 + 상급 부대 텍스트를 헤드셋으로 읽어준다.

    .venv/bin/python tools/tts_demo.py --wav      # 맥 없이: recordings/tts_*.wav 로 저장
    .venv/bin/python tools/tts_demo.py            # 맥 송신기 연결 후 에어팟으로 재생

처음 실행 때 보고 문장 조각을 미리 합성해 models/tts/cache 에 저장한다(이후엔 즉시).
"""
import argparse
import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import soundfile as sf  # noqa: E402

from squad.audio.arbiter import AudioArbiter  # noqa: E402
from squad.audio.output import RecordingPlayer, RemotePlayer  # noqa: E402
from squad.audio.stream import MicStreamServer  # noqa: E402
from squad.protocol import Msg, build_report  # noqa: E402
from squad.speech.announce import Announcer, UpperMessage, phrase_bank  # noqa: E402
from squad.speech.tts import OUT_SR, Synth  # noqa: E402

LEADER_HEADING = 0  # 분대장 방위 (센서 연동 전 고정값)

SCENARIO = [
    ("병사", build_report(Msg.CONTACT, 1, 3, azimuth=60, clock=2, dist_band=2, count=3, heading=0)),
    ("병사", build_report(Msg.HAZARD, 1, 1, azimuth=330, clock=11, heading=0)),
    ("상급", UpperMessage("platoon", "1분대는 현 위치에서 2시 방향 경계. 적 3명 접근 중, 1630Z까지 사격 통제 유지.",
                          prec="IMMEDIATE", id="p1")),
    ("병사", build_report(Msg.CASUALTY_SELF, 2, 2, heading=0)),
    ("상급", UpperMessage("company", "보급 차량 격자 329966에 17시 도착 예정.", id="c1")),
    ("병사", build_report(Msg.ACK, 3, 4, ref_type=0x10, ref_id=5)),
]


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wav", action="store_true")
    args = ap.parse_args()

    synth = Synth()
    t = time.perf_counter()
    n = synth.warm(phrase_bank())
    print(f"보고 조각 {len(phrase_bank())}개 준비 (새로 합성 {n}개, {time.perf_counter() - t:.1f}s)")

    srv = None
    if args.wav:
        player = RecordingPlayer(realtime=False)
    else:
        srv = MicStreamServer()
        asyncio.create_task(srv.serve())
        print("맥 송신기 연결 대기 중...")
        await srv.connected.wait()
        player = RemotePlayer(srv)
    arb = AudioArbiter(player)
    player.bind(arb)
    ann = Announcer(synth, arb, leader_heading=lambda: LEADER_HEADING)

    for kind, msg in SCENARIO:
        t = time.perf_counter()
        item = ann.on_soldier_frame(msg) if kind == "병사" else ann.on_upper_message(msg)
        print(f"[{kind}] {item.priority.name:7s} {item.text}  (준비 {1000 * (time.perf_counter() - t):.0f}ms)")
        await asyncio.sleep(0.3 if args.wav else 1.5)

    while arb.current or arb.pending():
        await asyncio.sleep(0.2)
    print("재생 순서:", *arb.log, sep="\n  ")
    if args.wav:
        out = ROOT / "recordings"
        out.mkdir(exist_ok=True)
        for i, (text, audio) in enumerate(player.played):
            sf.write(out / f"tts_{i}.wav", audio, OUT_SR)
            print(f"  tts_{i}.wav  {len(audio) / OUT_SR:.1f}s  {text}")


if __name__ == "__main__":
    asyncio.run(main())
