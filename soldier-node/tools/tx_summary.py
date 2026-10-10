#!/usr/bin/env python3
"""mock_leader --log-csv 파일로 송신량을 요약·비교한다(단계 7, EMCON 모드 비교).

    python3 tools/tx_summary.py run_mode2.csv run_mode1.csv

병사 → 분대장(rx) 기준으로 병사별: 프레임 수, 바이트(헤더 포함), 종류별 수, "송신 묶음" 수(1초 넘게 끊기면 새 묶음).
디버그 LOG(0x7F)는 따로 센다(프로토콜 밖, 병사 STATS에도 제외). 분대장 → 병사(tx)는 합계만.
주의: BLE 링크 계층의 빈 패킷·연결 유지 패킷은 CSV에 없다(앱 프레임만). 송신 출력(dBm) 차이도 여기서는 보이지 않는다.
"""

import csv
import sys
from collections import Counter, defaultdict

GAP_S = 1.0


def summarize(path):
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    per = defaultdict(lambda: dict(frames=0, bytes=0, types=Counter(), times=[], log_frames=0, log_bytes=0))
    tx = dict(frames=0, bytes=0)
    for r in rows:
        n = int(r["len"])
        if r["dir"] == "rx":
            d = per[r["soldier"]]
            if r["type"] == "0x7F":
                d["log_frames"] += 1
                d["log_bytes"] += n
                continue
            d["frames"] += 1
            d["bytes"] += n
            d["types"][r["name"]] += 1
            d["times"].append(float(r["t_s"]))
        elif r["dir"] in ("tx", "tx_adv"):
            tx["frames"] += 1
            tx["bytes"] += n
    for d in per.values():
        t = sorted(d["times"])
        d["bursts"] = sum(1 for i, x in enumerate(t) if i == 0 or x - t[i - 1] > GAP_S)
        d["span"] = (t[-1] - t[0]) if t else 0.0
    return per, tx


def main(paths):
    for path in paths:
        per, tx = summarize(path)
        print(f"== {path}")
        for sid in sorted(per):
            d = per[sid]
            types = ", ".join(f"{k} {v}" for k, v in sorted(d["types"].items()))
            print(f"  S{sid} → 분대장: {d['frames']}프레임 / {d['bytes']}B, 송신 묶음 {d['bursts']}회, 기간 {d['span']:.0f}s"
                  f"  | 디버그 LOG {d['log_frames']}프레임 / {d['log_bytes']}B")
            print(f"      종류: {types}")
        print(f"  분대장 → 병사: {tx['frames']}프레임 / {tx['bytes']}B")
    if len(paths) == 2:
        a, _ = summarize(paths[0])
        b, _ = summarize(paths[1])
        print("== 비교(병사 → 분대장, LOG 제외)")
        for sid in sorted(set(a) | set(b)):
            x, y = a.get(sid), b.get(sid)
            if x and y:
                print(f"  S{sid}: 프레임 {x['frames']} → {y['frames']}, 바이트 {x['bytes']} → {y['bytes']}, "
                      f"송신 묶음 {x['bursts']} → {y['bursts']}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1:])
