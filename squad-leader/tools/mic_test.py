"""[보드에서 실행] 맥 송신기 연결 대기 → 레벨 미터 → N초 녹음 → 전처리 → WAV 저장.

    .venv/bin/python tools/mic_test.py --seconds 5
    .venv/bin/python tools/mic_test.py --seconds 5 --enroll    # 화자 등록용 녹음 3회
    .venv/bin/python tools/mic_test.py --seconds 4 --verify    # 등록된 화자와 비교
    .venv/bin/python tools/mic_test.py --seconds 5 --stt       # 녹음하면서 실시간 STT(Zipformer) → 정규화
    .venv/bin/python tools/mic_test.py --seconds 5 --whisper   # 예비 STT(whisper)로 비교

결과: recordings/<시각>_raw.wav (원본, 16k 변환 전 원 샘플레이트), _proc.wav (전처리 후)
원본 음성은 개발용이다. 실운용에서는 저장하지 않거나 암호화 + 소각 대상.
"""
import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import soundfile as sf  # noqa: E402

from squad.audio.pipeline import preprocess  # noqa: E402
from squad.audio.speaker import SpeakerVerifier  # noqa: E402
from squad.audio.stream import MicStreamServer  # noqa: E402

PROFILE = ROOT / "recordings" / "speaker_profile.npz"


async def record(srv: MicStreamServer, seconds: float, sink=None):
    print(f"  {seconds:.0f}초 녹음 시작 — 말하세요")
    srv.ptt_down(preroll_s=0, sink=sink)
    t_end = time.monotonic() + seconds
    while time.monotonic() < t_end:
        bar = "#" * int(max(0, srv.level_dbfs + 60) / 2)
        print(f"\r  {srv.level_dbfs:6.1f} dBFS |{bar:<30}|", end="", flush=True)
        await asyncio.sleep(0.1)
    print()
    return srv.ptt_up()


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=5)
    ap.add_argument("--enroll", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--stt", action="store_true")
    ap.add_argument("--whisper", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    stt = None
    if args.stt:                                  # 모델은 연결 전에 읽는다(읽는 동안 마이크 수신이 멈춰 소리가 밀리지 않게)
        from squad.speech.stt import ZipformerStt
        print("Zipformer 로딩 중 (약 35초, 실운용에서는 부팅 때 한 번)...")
        stt = await asyncio.to_thread(ZipformerStt)
    srv = MicStreamServer()
    task = asyncio.create_task(srv.serve())
    print("맥 송신기 연결 대기 중... (맥: adb forward tcp:7100 tcp:7100 → python3 mac_mic_sender.py)")
    await srv.connected.wait()
    await asyncio.sleep(0.5)

    out_dir = ROOT / "recordings"
    out_dir.mkdir(exist_ok=True)

    if args.enroll:
        utts = []
        for k in range(3):
            input(f"[등록 {k + 1}/3] Enter 누르고 평소처럼 문장을 말하세요 ")
            x, sr = await record(srv, args.seconds)
            utts.append(preprocess(x, sr).audio)
        model = ROOT / "models" / "wespeaker_en_voxceleb_resnet34.onnx"
        v = SpeakerVerifier.neural(str(model)) if model.exists() else SpeakerVerifier()
        v.enroll(utts)
        v.save(str(PROFILE))
        print(f"등록 완료 → {PROFILE.relative_to(ROOT)} (개발용 평문 저장, 실운용 시 암호화 필요)")
        task.cancel()
        return

    session = None
    if args.stt:
        session = stt.session()
    x, sr = await record(srv, args.seconds, sink=session.feed if session else None)
    if session:
        r = session.finish()
        print(f"STT (PTT 뗀 뒤 {r.elapsed_s:.2f}s): {r.raw}")
        print(f"정규화: {r.text}" + (f"  교정 {r.corrections}" if r.corrections else ""))
    res = preprocess(x, sr)
    stamp = time.strftime("%H%M%S")
    sf.write(out_dir / f"{stamp}_raw.wav", x, sr)
    sf.write(out_dir / f"{stamp}_proc.wav", res.audio, res.sr)
    print(f"입력 {srv.info.device} {sr}Hz → 16kHz, {len(x) / sr:.1f}s, 처리 {res.elapsed_ms:.0f}ms")
    print(f"레벨 {res.level_in_dbfs:.1f} → {res.level_out_dbfs:.1f} dBFS, 음성 비율 {res.speech_ratio:.0%}")
    for e in res.impulses:
        print(f"  임펄스 {e.start_s:.3f}~{e.end_s:.3f}s 피크 {e.peak_dbfs:.1f}dBFS → -{e.reduction_db:.0f}dB")
    print(f"저장: recordings/{stamp}_raw.wav, recordings/{stamp}_proc.wav")

    if args.whisper:
        from squad.speech.stt import WhisperStt
        r = WhisperStt().transcribe(res.audio)
        print(f"STT ({r.elapsed_s:.1f}s): {r.raw}")
        print(f"정규화: {r.text}" + (f"  교정 {r.corrections}" if r.corrections else ""))
    if args.verify:
        v = SpeakerVerifier.from_profile(str(PROFILE), str(ROOT / "models" / "wespeaker_en_voxceleb_resnet34.onnx"))
        r = v.verify(res.audio)
        print(f"화자 인증: {'통과' if r.accepted else '거부'} (점수 {r.score:.3f}, 임계 {r.threshold})")
    task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
