#!/usr/bin/env python3
"""온디바이스 브리핑 지연 측정 (발표 자료용 수치).

대시보드 백엔드(:8000)가 실행 중이어야 한다. 실제 COP 상태로 브리핑·질의를 N회 호출해
첫 토큰 시간(TTFT)과 전체 시간을 측정한다.

    python3 scripts/bench_llm.py            # 5회
    python3 scripts/bench_llm.py -n 10
"""
import argparse, json, statistics, time, urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("-n", type=int, default=5)
ap.add_argument("--url", default="http://localhost:8000")
a = ap.parse_args()

st = json.loads(urllib.request.urlopen(a.url + "/api/llm/status?refresh=true").read())
print(f"LLM: {'연결' if st['available'] else '미연결'} · 모델 {st.get('model')} · {st.get('error') or ''}")

QUESTIONS = [None, "가장 가까운 적은?", "부상자 현황", "3분대 상태는?", "명령 수신 현황은?"]
rows = []
for i in range(a.n):
    q = QUESTIONS[i % len(QUESTIONS)]
    req = urllib.request.Request(a.url + "/api/briefing/stream", data=json.dumps({"question": q}).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.time(); ttft = None; engine = "?"; text = ""
    with urllib.request.urlopen(req, timeout=300) as r:
        for raw in r:
            line = raw.decode().strip()
            if not line.startswith("data:"):
                continue
            ev = json.loads(line[5:])
            if ev["type"] == "meta":
                engine = ev["engine"]
            elif ev["type"] == "token" and ttft is None:
                ttft = time.time() - t0
            elif ev["type"] == "done":
                text = ev["text"]
    total = time.time() - t0
    rows.append((ttft or total, total))
    print(f"[{i+1}] {q or '브리핑'} · {engine} · TTFT {ttft or 0:.2f}s · 총 {total:.2f}s · {len(text)}자")

tt = [r[0] for r in rows]; to = [r[1] for r in rows]
print(f"\n중앙값 TTFT {statistics.median(tt):.2f}s · 중앙값 총 {statistics.median(to):.2f}s (n={len(rows)})")
