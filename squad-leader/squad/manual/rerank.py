"""교차 인코더 재순위 (mmarco-mMiniLMv2-L12-H384, ARM int8 ONNX, 119MB, Apache-2.0).

보드 실측: 질문-문장 1쌍 약 80ms (4스레드). 검색 상위 문단 몇 개와 문단 안 문장 몇 개만 다시 매긴다.
학습 데이터(mMARCO)에 한국어가 없어 다국어 전이에 의존하므로, BM25 점수와 섞어서 쓴다.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = ROOT / "models" / "rerank"


class Reranker:
    def __init__(self, model_dir: Path = MODEL_DIR, threads: int = 4, max_len: int = 192):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        self.tok = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self.tok.enable_truncation(max_len)
        self.tok.enable_padding()
        so = ort.SessionOptions()
        so.intra_op_num_threads = threads
        self.sess = ort.InferenceSession(str(model_dir / "model_qint8_arm64.onnx"), so,
                                         providers=["CPUExecutionProvider"])
        self._names = {i.name for i in self.sess.get_inputs()}

    def scores(self, query: str, texts: list[str]) -> np.ndarray:
        """관련도 확률(0~1)."""
        if not texts:
            return np.zeros(0)
        enc = self.tok.encode_batch([(query, t) for t in texts])
        feed = {"input_ids": np.array([e.ids for e in enc], dtype=np.int64),
                "attention_mask": np.array([e.attention_mask for e in enc], dtype=np.int64)}
        if "token_type_ids" in self._names:
            feed["token_type_ids"] = np.array([e.type_ids for e in enc], dtype=np.int64)
        logits = self.sess.run(None, feed)[0][:, 0]
        return 1 / (1 + np.exp(-logits))
