#!/usr/bin/env bash
# [맥, Apple Silicon] 보고 칸 추출 LoRA 미세조정 → 병합 → GGUF(f16) 변환.
#   준비: 보드에서 data/finetune/{train,valid}.jsonl 을 맥으로 가져온다 (README 참고)
#   실행: bash mac_train.sh [HF 모델] [반복 수]
#     예) bash mac_train.sh Qwen/Qwen2.5-1.5B-Instruct 300
#   결과: out/<이름>-f16.gguf → 보드로 보내서 Q4_0 변환
set -euo pipefail
MODEL="${1:-Qwen/Qwen2.5-1.5B-Instruct}"
ITERS="${2:-300}"
NAME="sq-nlu-$(basename "$MODEL" | tr 'A-Z' 'a-z')"
DATA="${DATA:-./finetune}"          # train.jsonl, valid.jsonl 이 있는 폴더
WORK="${WORK:-./work}"
mkdir -p "$WORK" out

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -U "mlx-lm" huggingface_hub   # 변환 도구는 이 venv에 설치하지 않는다 (transformers 버전 충돌)

echo "== LoRA 학습: $MODEL, $ITERS 반복"
# --mask-prompt: 답(JSON)에만 손실을 준다. 데이터가 수백 개라 층 16개, 학습률 1e-4로 시작
mlx_lm.lora --model "$MODEL" --train --data "$DATA" \
  --iters "$ITERS" --batch-size 8 --num-layers 16 --learning-rate 1e-4 --mask-prompt \
  --steps-per-eval 100 --save-every 200 --adapter-path "$WORK/adapters-$NAME"

echo "== 검증 세트 손실"
mlx_lm.lora --model "$MODEL" --adapter-path "$WORK/adapters-$NAME" --data "$DATA" --test || true

echo "== 병합 (LoRA → 전체 가중치)"
mlx_lm.fuse --model "$MODEL" --adapter-path "$WORK/adapters-$NAME" --save-path "$WORK/fused-$NAME" --dequantize

echo "== 맛보기"
mlx_lm.generate --model "$WORK/fused-$NAME" --max-tokens 60 \
  --prompt "$(printf '분대장 무전 보고를 칸으로 나눠라.\n보고: 놈들 옆구리로 붙는다 자리 지킨다 다친 사람 데려가 줘')"

echo "== GGUF 변환 (변환 전용 venv)"
bash "$(dirname "$0")/mac_convert.sh" "$MODEL"
