"""[보드에서 실행] STT 비교용 녹음 세트: 화면에 뜬 문장을 읽고 Enter로 시작/정지.

    .venv/bin/python tools/record_set.py              # 기본 문장 12개
    .venv/bin/python tools/record_set.py --from 5     # 5번 문장부터 다시

결과: recordings/stt_set/NN.wav (전처리 후 16kHz) + refs.tsv (파일<TAB>원문)
원본 음성은 개발용이다. 실운용에서는 저장하지 않거나 암호화 + 소각 대상.
"""
import argparse
import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import soundfile as sf  # noqa: E402

from squad.audio.pipeline import preprocess  # noqa: E402
from squad.audio.stream import MicStreamServer  # noqa: E402

OUT = ROOT / "recordings" / "stt_set"
SENTENCES = [
    "2시 방향 300미터 적 3명 발견",
    "1분대는 현 위치에서 경계하라",
    "엄폐하고 사격 개시",
    "부상자 1명 발생, 의무병 요청",
    "11시 방향 폭발물 의심 물체 확인",
    "탄약 부족, 보급 요청",
    "격자 3 2 9 9 6 6으로 이동하라",
    "16시 30분까지 사격 통제 유지",
    "적 차량 2대 북쪽으로 이동 중",
    "2번 병사 응답 없음, 위치 확인 바람",
    "지혈대는 언제 풀어도 돼?",
    "쇼크 환자한테 물 줘도 돼?",
]


async def line(prompt: str) -> str:
    return await asyncio.get_running_loop().run_in_executor(None, input, prompt)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", type=int, default=1)
    args = ap.parse_args()

    srv = MicStreamServer()
    task = asyncio.create_task(srv.serve())
    print("맥 송신기 연결 대기 중... (맥: adb forward tcp:7100 tcp:7100 → python3 mac_mic_sender.py)")
    await srv.connected.wait()
    await asyncio.sleep(0.5)
    print(f"연결됨: {srv.info.device}\n")

    OUT.mkdir(parents=True, exist_ok=True)
    refs = OUT / "refs.tsv"
    done = {}
    if refs.exists():
        done = dict(l.rstrip("\n").split("\t", 1) for l in refs.open(encoding="utf-8") if "\t" in l)

    for i, text in enumerate(SENTENCES, 1):
        if i < args.start:
            continue
        name = f"{i:02d}.wav"
        while True:
            print(f"[{i}/{len(SENTENCES)}]  {text}")
            await line("  Enter = 녹음 시작 ")
            srv.ptt_down(preroll_s=0.3)
            t0 = time.monotonic()
            stop = asyncio.ensure_future(line("  ● 녹음 중... 다 말하면 Enter "))
            while not stop.done():
                bar = "#" * int(max(0, srv.level_dbfs + 60) / 2)
                print(f"\r  {srv.level_dbfs:6.1f} dBFS |{bar:<30}|  ", end="", flush=True)
                await asyncio.sleep(0.1)
            x, sr = srv.ptt_up()
            res = preprocess(x, sr)
            print(f"\r  {time.monotonic() - t0:.1f}초, 음성 비율 {res.speech_ratio:.0%}, "
                  f"레벨 {res.level_out_dbfs:.0f} dBFS" + " " * 20)
            if res.speech_ratio < 0.1:
                print("  ! 목소리가 거의 안 잡혔습니다. 다시 녹음합니다.")
                continue
            again = await line("  Enter = 다음 / r + Enter = 다시 ")
            if again.strip().lower() != "r":
                break
        sf.write(OUT / name, res.audio, res.sr)
        done[name] = text
        refs.write_text("".join(f"{k}\t{v}\n" for k, v in sorted(done.items())), encoding="utf-8")
        print(f"  저장 → recordings/stt_set/{name}\n")

    print(f"끝. {len(done)}개 저장: {OUT.relative_to(ROOT)}")
    task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
