"""오프라인 STT. 기본 = 스트리밍 Zipformer(ZipformerStt), 예비 = whisper.cpp(WhisperStt).

ZipformerStt (한국어 KsponSpeech 학습 174M, int8, sherpa-onnx)
- PTT 누르는 동안 실시간 디코딩 → 뗀 뒤 대기 약 0.5~0.9초 (whisper base는 약 4초: 인코더가 말이 끝난 뒤 한 번에 돈다)
- 실녹음 6문장: 글자 오류율 whisper 23% → Zipformer 약 10~15%
- 전처리(임펄스·총성 억제 → 고역통과 → 잡음 제거 → AGC)를 PTT 중 실시간으로 건다 (StreamPreprocessor,
  0.5초 블록 + 앞 1.5초 맥락). 조용한 실내 녹음 6개에서는 원음이 약간 나았지만, 총성·차량 잡음 현장을 위해 유지한다.
  끄려면 ZipformerStt(preprocess=False).
- 군 용어 핫워드(빔서치 문맥 가중): "일본대→일분대", "의식→의심", "청약→탄약"이 고쳐졌다
- 출력은 띄어쓰기·숫자가 없다 ("두시방향삼백미터") → 띄어쓰기 복원 → 용어 교정 → 숫자 정규화
- 모델 로딩 약 35초 → 부팅 때 한 번 만들어 상주 (RAM 약 200MB)

WhisperStt — 보드(Cortex-A53 4코어, dotprod 없음) 실측으로 정한 설정:
- 모델 base-q5_1 (60MB). small은 3~4배 느려 PTT 응답에 부적합.
- 탐욕 디코딩(-bs 1 -bo 1): 빔서치는 재시도와 겹치면 수백 번 디코딩해 10초 이상 걸린다.
- audio_ctx를 발화 길이에 맞추되 하한 500(10초): whisper는 기본으로 30초 창 전체를 인코딩한다.
  너무 줄이면(2초 발화에 ~150) 환각·재시도 루프로 오히려 28초 이상 걸렸다.
- 짧은 도메인 프롬프트: 긴 용어집 프롬프트는 매 디코딩마다 비용이 들고 효과 차이가 작았다.
- 온도 재시도(fallback)는 유지: 끄면 반복 루프에 빠지는 경우가 있었다. 반복은 후처리로도 자른다.
"""
from __future__ import annotations

import queue
import re
import subprocess
import threading
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf

from ..audio.fmt import to_16k_mono
from ..audio.pipeline import StreamPreprocessor
from ..text.lexicon import all_terms, correct
from ..text.normalize import normalize
from ..text.spacing import default_segmenter

ROOT = Path(__file__).resolve().parents[2]
WHISPER_CLI = ROOT / "third_party" / "whisper.cpp" / "build" / "bin" / "whisper-cli"
MODEL = ROOT / "models" / "whisper" / "ggml-base-q5_1.bin"
PROMPT = "분대 무전. 2시 방향 300m 적 3명 발견. 엄폐, 사격 개시, 원거리, 근거리."
SR = 16000
ZIP_DIR = ROOT / "models" / "zipformer-ko"
ZIP_CHUNK = "32"          # 16=320ms(오류율 +0.4%p), 32=640ms, 64=1.28s (공개 수치 KsponSpeech CER 8.3/7.8/7.5%)
HOTWORD_SCORE = 1.5
TMP = Path("/dev/shm") if Path("/dev/shm").is_dir() else Path(tempfile.gettempdir())


@dataclass
class SttResult:
    raw: str                      # whisper 출력 그대로
    text: str                     # 정규화 + 용어 교정 후
    corrections: list = field(default_factory=list)
    elapsed_s: float = 0.0
    audio_s: float = 0.0


def trim_repeats(text: str) -> str:
    """'A. A. A. A.' 같은 반복 루프를 첫 번째만 남긴다."""
    parts = [p.strip() for p in re.split(r"(?<=[.,!?])\s+", text) if p.strip()]
    out: list[str] = []
    for p in parts:
        if out and p == out[-1]:
            continue
        if p in out[-3:]:
            break
        out.append(p)
    return " ".join(out)


class WhisperStt:
    def __init__(self, model: Path = MODEL, cli: Path = WHISPER_CLI, threads: int = 4,
                 prompt: str | None = PROMPT, language: str = "ko"):
        self.model, self.cli, self.threads, self.prompt, self.language = model, cli, threads, prompt, language
        if not cli.exists():
            raise FileNotFoundError(f"whisper-cli 없음: {cli}")
        if not model.exists():
            raise FileNotFoundError(f"모델 없음: {model}")

    def _args(self, wav: Path, audio_s: float) -> list[str]:
        ac = min(1500, max(500, int((audio_s + 1.0) * 50) + 32))   # 인코더 프레임 = 20ms, 여유 1초
        args = [str(self.cli), "-m", str(self.model), "-f", str(wav), "-l", self.language,
                "-t", str(self.threads), "-nt", "-np", "-fa", "-ac", str(ac), "-bs", "1", "-bo", "1"]
        if self.prompt:
            args += ["--prompt", self.prompt]
        return args

    def transcribe(self, audio: np.ndarray, sr: int = SR) -> SttResult:
        """16kHz 모노 float32 (전처리 파이프라인 출력)를 받는다."""
        if sr != SR:
            raise ValueError("16kHz 입력만 받는다 (squad.audio.pipeline.preprocess 사용)")
        audio_s = len(audio) / SR
        t0 = time.perf_counter()
        with tempfile.NamedTemporaryFile(suffix=".wav", dir=TMP) as f:
            sf.write(f.name, audio, SR, subtype="PCM_16")
            p = subprocess.run(self._args(Path(f.name), audio_s), capture_output=True, text=True, timeout=120)
        if p.returncode != 0:
            raise RuntimeError(f"whisper-cli 실패: {p.stderr[-300:]}")
        raw = trim_repeats(" ".join(p.stdout.split()))
        fixed, changes = correct(raw)
        return SttResult(raw=raw, text=normalize(fixed), corrections=changes,
                         elapsed_s=time.perf_counter() - t0, audio_s=audio_s)


def postprocess(raw: str) -> tuple[str, list]:
    """붙어 나온 STT 출력 → 띄어쓰기 복원 → 군 용어 교정 → 숫자·단위 정규화."""
    spaced = default_segmenter().segment(raw)
    fixed, changes = correct(spaced)
    return normalize(fixed), changes


_FLUSH = np.zeros(0, np.float32)                 # 표지 객체 (is 로 비교)
_TAIL = np.zeros(int(0.8 * SR), np.float32)


class ZipformerSession:
    """PTT 한 번 = 세션 하나. feed()는 마이크 수신 스레드에서 바로 불러도 된다 (디코딩은 전용 스레드)."""

    def __init__(self, stt: "ZipformerStt"):
        self.stt = stt
        self.pre = StreamPreprocessor() if stt.preprocess else None
        self.stream = stt.rec.create_stream(stt.hotwords) if stt.hotwords else stt.rec.create_stream()
        self.q: queue.Queue = queue.Queue()
        self.audio_s = 0.0
        self.t0 = time.perf_counter()
        self.worker = threading.Thread(target=self._run, daemon=True)
        self.worker.start()

    def feed(self, x: np.ndarray, sr: int = SR) -> None:
        """모노 float32 아무 샘플레이트 (16kHz로 맞춰서 넣는다)."""
        x = to_16k_mono(np.asarray(x, np.float32), sr) if sr != SR else np.asarray(x, np.float32)
        self.audio_s += len(x) / SR
        self.q.put(x)

    def _run(self) -> None:
        rec, s = self.stt.rec, self.stream
        while (x := self.q.get()) is not None:
            if x is _FLUSH:
                x = self.pre.flush() if self.pre is not None else x
            elif x is not _TAIL and self.pre is not None:   # 전처리도 디코딩 스레드에서 (마이크 수신을 막지 않게)
                x = self.pre.feed(x)
            if len(x):
                s.accept_waveform(SR, x)
            while rec.is_ready(s):
                rec.decode_stream(s)

    def partial(self) -> str:
        return self.stt.rec.get_result(self.stream)

    def finish(self) -> SttResult:
        """PTT 뗌: 꼬리 무음으로 마지막 청크를 마무리하고 결과를 낸다."""
        t = time.perf_counter()
        self.q.put(_FLUSH)                                   # 전처리에 남은 블록 내보내기
        self.q.put(_TAIL)                                    # 꼬리 무음 (전처리 없이 그대로)
        self.q.put(None)
        self.worker.join()
        self.stream.input_finished()
        rec = self.stt.rec
        while rec.is_ready(self.stream):
            rec.decode_stream(self.stream)
        raw = rec.get_result(self.stream).strip()
        text, changes = postprocess(raw)
        return SttResult(raw=raw, text=text, corrections=changes,
                         elapsed_s=time.perf_counter() - t, audio_s=self.audio_s)


class ZipformerStt:
    """상주형 스트리밍 STT. 만들 때 한 번 로딩(약 35초), 이후 PTT마다 session()."""

    def __init__(self, model_dir: Path = ZIP_DIR, chunk: str = ZIP_CHUNK, threads: int = 4,
                 hotword_score: float = HOTWORD_SCORE, use_hotwords: bool = True, preprocess: bool = True):
        import sherpa_onnx
        self.preprocess = preprocess
        f = lambda part: str(model_dir / f"{part}-chunk-{chunk}.int8.onnx")
        if not Path(f("encoder")).exists():
            raise FileNotFoundError(f"Zipformer 모델 없음: {model_dir}")
        kw = dict(decoding_method="greedy_search")
        self.hotwords = ""
        if use_hotwords:
            words = sorted({t.replace(" ", "") for t in all_terms()} | EXTRA_HOTWORDS)
            # cjkchar 단위: 한 글자씩 띄워서 준다 ("탄 약"). 파일 대신 스트림별 문자열로 넘긴다
            self.hotwords = "/".join(" ".join(w) for w in words)
            kw = dict(decoding_method="modified_beam_search", max_active_paths=4,
                      hotwords_score=hotword_score, modeling_unit="cjkchar")
        self.rec = sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=str(model_dir / "tokens.txt"), encoder=f("encoder"), decoder=f("decoder"), joiner=f("joiner"),
            num_threads=threads, sample_rate=SR, feature_dim=80, **kw)
        default_segmenter()          # 띄어쓰기 사전도 미리 (첫 발화 지연 방지)

    def session(self) -> ZipformerSession:
        return ZipformerSession(self)

    def transcribe(self, audio: np.ndarray, sr: int = SR) -> SttResult:
        """녹음 파일용 (스트리밍과 같은 경로)."""
        s = self.session()
        for k in range(0, len(audio), 1600):
            s.feed(audio[k:k + 1600], sr)
        return s.finish()


# 군 용어 외에 무전에 자주 나오는 말 (실녹음에서 틀린 것 위주)
EXTRA_HOTWORDS = {"일분대", "이분대", "삼분대", "부상자", "탄약", "보급", "의무병", "폭발물", "의심", "발생", "요청"}
