# 보고 칸 추출 미세조정 (분대장 발화 → 활동·조치·요청 코드)

목적: 구어체·은어·부정·음성 인식 오류가 섞인 분대장 보고에서 규칙 추출기보다 정확한 소형 LLM을 보드에서 돌린다.
LLM 출력은 짧은 JSON(`squad/report/nlu.py`)뿐이고 요지 문장은 규칙이 만든다 (숫자 지어내기 차단).

## 1. 데이터 (보드)

```bash
# 변형 발화(docs/prompts/variant_utterances_prompt.md 로 생성)를 data/utterances/utterances.jsonl 에 둔다
.venv/bin/python tools/finetune/prepare_data.py data/utterances/utterances.jsonl
# → data/finetune/train.jsonl valid.jsonl test.jsonl report.txt
.venv/bin/python tools/finetune/eval_nlu.py            # 규칙 기준점
```

## 2. 학습 (맥, Apple Silicon)

```bash
mkdir -p ~/sq-ft && cd ~/sq-ft
adb pull /home/arduino/squad-leader/data/finetune ./finetune
adb pull /home/arduino/squad-leader/tools/finetune/mac_train.sh .
bash mac_train.sh Qwen/Qwen2.5-1.5B-Instruct 300      # 32GB 기준 수십 분
# 3B: bash mac_train.sh Qwen/Qwen2.5-3B-Instruct 300
adb push out/sq-nlu-qwen2.5-1.5b-instruct-f16.gguf /home/arduino/squad-leader/models/llm/
```

## 3. 보드에서 변환·평가

```bash
cd ~/squad-leader/models/llm
../../third_party/llama.cpp/build/bin/llama-quantize sq-nlu-qwen2.5-1.5b-instruct-f16.gguf sq-nlu-qwen2.5-1.5b-instruct-q4_0.gguf Q4_0
rm sq-nlu-qwen2.5-1.5b-instruct-f16.gguf
cd ~/squad-leader
.venv/bin/python tools/finetune/eval_nlu.py --model models/llm/sq-nlu-qwen2.5-1.5b-instruct-q4_0.gguf --mode ft
```

평가 세트(eval.jsonl)는 학습·규칙 수정에 쓰지 않는다. 점수가 규칙보다 높고 응답 시간이 허용 범위면
`squad/report/desk.py`의 LLM 경로를 미세조정 모델로 켠다.
