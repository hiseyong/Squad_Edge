"""녹음 세트로 STT 비교: whisper base vs 스트리밍 Zipformer — 글자 오류율(CER)과 PTT 뗀 뒤 대기 시간.

    .venv/bin/python tools/stt_compare.py [폴더]      # 기본 recordings/stt_set (NN.wav + refs.tsv)

wav는 아무 샘플레이트·채널이나 된다 (16kHz 모노로 변환 후 전처리 파이프라인 통과).
CER은 띄어쓰기·문장부호를 빼고, 숫자는 양쪽 다 정규화(한글 수사 → 숫자)한 뒤 글자 단위로 잰다.
"""
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import sherpa_onnx  # noqa: E402
import soundfile as sf  # noqa: E402

from squad.audio.fmt import to_16k_mono  # noqa: E402
from squad.audio.pipeline import preprocess  # noqa: E402
from squad.speech.stt import WhisperStt, ZipformerStt  # noqa: E402
from squad.text.normalize import normalize  # noqa: E402

ZIP = ROOT / "models" / "zipformer-ko"


def canon(t: str) -> str:
    return re.sub(r"[^가-힣a-zA-Z0-9]", "", normalize(t))


def cer(ref: str, hyp: str) -> float:
    r, h = canon(ref), canon(hyp)
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
    return d[len(h)] / max(1, len(r))


def zipformer(chunk: str = "32", threads: int = 4):
    return sherpa_onnx.OnlineRecognizer.from_transducer(
        tokens=str(ZIP / "tokens.txt"), encoder=str(ZIP / f"encoder-chunk-{chunk}.int8.onnx"),
        decoder=str(ZIP / f"decoder-chunk-{chunk}.int8.onnx"), joiner=str(ZIP / f"joiner-chunk-{chunk}.int8.onnx"),
        num_threads=threads, sample_rate=16000, feature_dim=80, decoding_method="greedy_search")


def zip_run(rec, x: np.ndarray) -> tuple[str, float]:
    """말하는 동안 100ms씩 넣었다고 보고, 발화 끝 이후 처리 시간만 대기로 잰다."""
    s = rec.create_stream()
    step = 1600
    for k in range(0, len(x), step):
        s.accept_waveform(16000, x[k:k + step])
        while rec.is_ready(s):
            rec.decode_stream(s)
    t = time.perf_counter()
    s.accept_waveform(16000, np.zeros(12800, np.float32))
    s.input_finished()
    while rec.is_ready(s):
        rec.decode_stream(s)
    return rec.get_result(s), time.perf_counter() - t


def main():
    d = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "recordings" / "stt_set"
    refs = [l.rstrip("\n").split("\t", 1) for l in (d / "refs.tsv").open(encoding="utf-8") if "\t" in l]
    refs = [(f, t) for f, t in refs if (d / f).exists()]
    if not refs:
        sys.exit(f"{d} 에 refs.tsv와 일치하는 wav가 없습니다")
    print(f"{len(refs)}개 파일. Zipformer 로딩 중 (최초 30초 정도)...")
    zs, ws = ZipformerStt(), WhisperStt()
    tot = {"w": [0.0, 0.0], "z": [0.0, 0.0]}      # [CER 합, 대기 합]
    for f, ref in refs:
        x, sr = sf.read(d / f, dtype="float32", always_2d=True)
        audio = preprocess(x, sr).audio               # whisper: 전처리 후
        w = ws.transcribe(audio)
        raw16 = to_16k_mono(x, sr)                    # Zipformer: 원음 (전처리하면 나빠짐)
        s = zs.session()
        for k in range(0, len(raw16), 1600):
            s.feed(raw16[k:k + 1600])
            time.sleep(0.1)                           # 말하는 속도로 → 뗀 뒤 대기만 잰다
        z = s.finish()
        cw, cz = cer(ref, w.text), cer(ref, z.text)
        tot["w"][0] += cw; tot["w"][1] += w.elapsed_s
        tot["z"][0] += cz; tot["z"][1] += z.elapsed_s
        print(f"\n{f} ({len(raw16) / 16000:.1f}s) 원문: {ref}")
        print(f"  whisper  CER {cw:5.0%}  대기 {w.elapsed_s:4.1f}s | {w.text}")
        print(f"  zipformer CER {cz:5.0%}  대기 {z.elapsed_s:4.1f}s | {z.text}")
    n = len(refs)
    print(f"\n평균  whisper  CER {tot['w'][0] / n:.0%}, 대기 {tot['w'][1] / n:.1f}s"
          f"\n      zipformer CER {tot['z'][0] / n:.0%}, 대기 {tot['z'][1] / n:.1f}s")


if __name__ == "__main__":
    main()
