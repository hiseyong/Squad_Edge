#!/usr/bin/env bash
# [맥] 병합된 미세조정 모델 → GGUF(f16). 학습용 venv(.venv, transformers 5.x)와 분리된 변환 전용 venv를 쓴다.
#   bash mac_convert.sh Qwen/Qwen2.5-0.5B-Instruct
# 토크나이저는 원본 저장소 파일로 덮어쓴다 (LoRA는 토크나이저를 바꾸지 않음. mlx-lm이 저장한 transformers 5.x 형식을
# 변환 도구의 transformers 4.x가 못 읽는 문제 회피).
set -euo pipefail
MODEL="${1:-Qwen/Qwen2.5-0.5B-Instruct}"
NAME="sq-nlu-$(basename "$MODEL" | tr 'A-Z' 'a-z')"
WORK="${WORK:-./work}"
FUSED="$WORK/fused-$NAME"
[[ -d "$FUSED" ]] || { echo "병합 모델 없음: $FUSED (mac_train.sh 먼저)" >&2; exit 1; }
mkdir -p out

if [[ ! -d "$WORK/llama.cpp" ]]; then
  git clone --depth 1 https://github.com/ggml-org/llama.cpp "$WORK/llama.cpp"
fi
if [[ ! -d .venv-conv ]]; then
  python3 -m venv .venv-conv
  .venv-conv/bin/pip install -q -r "$WORK/llama.cpp/requirements/requirements-convert_hf_to_gguf.txt"
fi

echo "== 원본 토크나이저 복사: $MODEL"
TOK=$(.venv-conv/bin/python -c "
from huggingface_hub import snapshot_download
print(snapshot_download('$MODEL', allow_patterns=['tokenizer*', 'vocab.json', 'merges.txt', 'special_tokens_map.json']))")
cp "$TOK"/tokenizer* "$TOK"/vocab.json "$TOK"/merges.txt "$FUSED"/ 2>/dev/null || true
[[ -f "$TOK/special_tokens_map.json" ]] && cp "$TOK/special_tokens_map.json" "$FUSED"/

echo "== GGUF 변환"
.venv-conv/bin/python "$WORK/llama.cpp/convert_hf_to_gguf.py" "$FUSED" --outtype f16 --outfile "out/$NAME-f16.gguf"
ls -lh "out/$NAME-f16.gguf"
echo "다음: adb push out/$NAME-f16.gguf /home/arduino/squad-leader/models/llm/"
