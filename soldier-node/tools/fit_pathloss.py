#!/usr/bin/env python3
"""경로손실 보정(단계 R): mock_leader --log-csv 기록의 RANGING(0x0E)으로 P1m, n을 맞춘다.

모델: RSSI = P1m − 10·n·log10(d)   ⇔   d = 10^((P1m − RSSI) / (10·n))

시험: 병사 보드 두 대를 1m, 3m, 5m, 10m에 두고 각 30초 이상. mock_leader에서 거리를 바꿀 때마다 `mark <m>`.
      (RANGING은 10초마다 → 30초면 보드당 3개, 두 보드가 서로를 재므로 거리당 약 6개)

    python3 tools/fit_pathloss.py ranging.csv [더.csv ...] [--out pathloss.png] [--min-samples 5]
    python3 tools/fit_pathloss.py --self-test

출력: P1m, n, R², 거리별 RSSI 평균과 추정 거리·오차, 그래프(RSSI–거리, 실제–추정 거리).
그래프: matplotlib가 있으면 PNG, 없으면 같은 내용을 SVG로(의존성 없음). 맞추기 자체는 표준 라이브러리만 사용.
"""

import argparse
import csv
import math
import os
import random
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import frame_codec as fc  # noqa: E402


def load_points(paths, min_samples):
    """CSV → [(실제 거리 m, RSSI 중앙값, 보고 병사, 피어)]"""
    pts = []
    for path in paths:
        dist = None
        for r in csv.DictReader(open(path, encoding="utf-8")):
            if r["dir"] == "mark":
                v = r["name"].strip()
                dist = None if v in ("-", "") else float(v)
                continue
            if dist is None or r["dir"] != "rx" or r["type"] != "0x0E":
                continue
            try:
                m = fc.decode(bytes.fromhex(r["hex"]))
            except (fc.FrameError, ValueError):
                continue
            for p in m["peers"]:
                if p["samples"] >= min_samples:
                    pts.append((dist, p["rssi_avg"], m["src"], p["peer_id"]))
    return pts


def fit(pts):
    """최소제곱: y = a + b·x, x = log10(d), y = RSSI → P1m = a, n = −b/10."""
    xs = [math.log10(d) for d, *_ in pts]
    ys = [float(r) for _, r, *_ in pts]
    k = len(xs)
    mx, my = sum(xs) / k, sum(ys) / k
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        raise ValueError("거리가 하나뿐이라 기울기를 구할 수 없음(거리 2개 이상 필요)")
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    a = my - b * mx
    ss_tot = sum((y - my) ** 2 for y in ys)
    ss_res = sum((y - (a + b * x)) ** 2 for x, y in zip(xs, ys))
    r2 = 1 - ss_res / ss_tot if ss_tot else 1.0
    return a, -b / 10, r2


def est(rssi, p1m, n):
    return 10 ** ((p1m - rssi) / (10 * n))


def summary(pts, p1m, n):
    by = defaultdict(list)
    for d, r, *_ in pts:
        by[d].append(r)
    rows = []
    for d in sorted(by):
        rs = by[d]
        mean = sum(rs) / len(rs)
        e = est(mean, p1m, n)
        rows.append((d, len(rs), mean, min(rs), max(rs), e, (e - d) / d * 100))
    return rows


def plot_png(pts, p1m, n, rows, out):
    import matplotlib  # noqa: PLC0415 - 선택 의존성
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # noqa: PLC0415

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.5))
    ds = [d for d, *_ in pts]
    ax1.scatter(ds, [r for _, r, *_ in pts], s=18, alpha=0.6, label="RANGING 중앙값")
    lo, hi = min(ds) * 0.8, max(ds) * 1.2
    xs = [lo * (hi / lo) ** (i / 100) for i in range(101)]
    ax1.plot(xs, [p1m - 10 * n * math.log10(x) for x in xs], "r-", label=f"맞춤 P1m={p1m:.1f}, n={n:.2f}")
    ax1.set_xscale("log")
    ax1.set_xlabel("실제 거리 (m)")
    ax1.set_ylabel("RSSI (dBm)")
    ax1.set_title("RSSI – 거리")
    ax1.grid(True, which="both", alpha=0.3)
    ax1.legend()
    ax2.scatter([d for d, *_ in pts], [est(r, p1m, n) for _, r, *_ in pts], s=18, alpha=0.4, label="개별 추정")
    ax2.plot([r[0] for r in rows], [r[5] for r in rows], "ko-", label="거리별 평균 RSSI로 추정")
    m = max(max(ds), max(r[5] for r in rows)) * 1.15
    ax2.plot([0, m], [0, m], "g--", label="y = x")
    ax2.set_xlim(0, m)
    ax2.set_ylim(0, m)
    ax2.set_xlabel("실제 거리 (m)")
    ax2.set_ylabel("추정 거리 (m)")
    ax2.set_title("실제 vs 추정")
    ax2.grid(True, alpha=0.3)
    ax2.legend()
    for font in ("AppleGothic", "Apple SD Gothic Neo", "NanumGothic"):
        try:
            plt.rcParams["font.family"] = font
            break
        except Exception:  # noqa: BLE001
            pass
    plt.rcParams["axes.unicode_minus"] = False
    fig.tight_layout()
    fig.savefig(out, dpi=130)


def plot_svg(pts, p1m, n, rows, out):
    """matplotlib 없이: 같은 두 그래프를 SVG로."""
    W, H, PAD = 520, 360, 50

    def panel(ox, title, xlab, ylab, xr, yr, series, xlog=False):
        def X(v):
            if xlog:
                return ox + PAD + (math.log10(v) - math.log10(xr[0])) / (math.log10(xr[1]) - math.log10(xr[0])) * (W - 2 * PAD)
            return ox + PAD + (v - xr[0]) / (xr[1] - xr[0]) * (W - 2 * PAD)

        def Y(v):
            return H - PAD - (v - yr[0]) / (yr[1] - yr[0]) * (H - 2 * PAD)

        g = [f'<text x="{ox + W / 2}" y="22" text-anchor="middle" font-size="15">{title}</text>',
             f'<rect x="{ox + PAD}" y="{PAD}" width="{W - 2 * PAD}" height="{H - 2 * PAD}" fill="none" stroke="#888"/>',
             f'<text x="{ox + W / 2}" y="{H - 12}" text-anchor="middle" font-size="12">{xlab}</text>',
             f'<text x="{ox + 14}" y="{H / 2}" font-size="12" transform="rotate(-90 {ox + 14} {H / 2})" text-anchor="middle">{ylab}</text>']
        for i in range(5):
            yv = yr[0] + (yr[1] - yr[0]) * i / 4
            g.append(f'<text x="{ox + PAD - 4}" y="{Y(yv) + 4}" text-anchor="end" font-size="10">{yv:.0f}</text>')
        step = max(1, math.ceil((xr[1] - xr[0]) / 5))
        ticks = [1, 2, 3, 5, 10, 20] if xlog else list(range(int(xr[0]), int(xr[1]) + 1, step))
        for t in ticks:
            if xr[0] <= t <= xr[1]:
                g.append(f'<text x="{X(t)}" y="{H - PAD + 14}" text-anchor="middle" font-size="10">{t:g}</text>')
        for kind, color, data in series:
            if kind == "pts":
                g += [f'<circle cx="{X(x):.1f}" cy="{Y(y):.1f}" r="3" fill="{color}" fill-opacity="0.6"/>' for x, y in data]
            else:
                d = " ".join(f"{X(x):.1f},{Y(y):.1f}" for x, y in data)
                g.append(f'<polyline points="{d}" fill="none" stroke="{color}" stroke-width="2"/>')
        return g

    ds = [d for d, *_ in pts]
    rs = [r for _, r, *_ in pts]
    lo, hi = min(ds) * 0.8, max(ds) * 1.2
    xs = [lo * (hi / lo) ** (i / 60) for i in range(61)]
    fitline = [(x, p1m - 10 * n * math.log10(x)) for x in xs]
    yr = (min(rs + [y for _, y in fitline]) - 3, max(rs + [y for _, y in fitline]) + 3)
    m = max(max(ds), max(r[5] for r in rows)) * 1.15
    g = panel(0, f"RSSI–거리 (P1m={p1m:.1f}, n={n:.2f})", "실제 거리 (m, 로그)", "RSSI (dBm)", (lo, hi), yr,
              [("pts", "#1f77b4", list(zip(ds, rs))), ("line", "#d62728", fitline)], xlog=True)
    g += panel(W, "실제 vs 추정 거리", "실제 거리 (m)", "추정 거리 (m)", (0, m), (0, m),
               [("pts", "#1f77b4", [(d, est(r, p1m, n)) for d, r, *_ in pts]),
                ("line", "#2ca02c", [(0, 0), (m, m)]),
                ("line", "#000000", [(r[0], r[5]) for r in rows])])
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{2 * W}" height="{H}" font-family="sans-serif">' + \
          '<rect width="100%" height="100%" fill="white"/>' + "".join(g) + "</svg>"
    open(out, "w", encoding="utf-8").write(svg)


def report(pts, out):
    if len(pts) < 2:
        raise SystemExit("RANGING 점이 부족함('mark <m>' 뒤에 받은 RANGING이 있는지 확인)")
    p1m, n, r2 = fit(pts)
    rows = summary(pts, p1m, n)
    print(f"점 {len(pts)}개, 거리 {len(rows)}개")
    print(f"맞춤 결과: P1m = {p1m:.1f} dBm, n = {n:.2f}, R² = {r2:.3f}")
    print(f"  → mock_leader --pathloss {p1m:.1f},{n:.2f}")
    print("  실제(m)  점수  RSSI 평균(최소~최대)   추정(m)   오차")
    for d, k, mean, mn, mx, e, err in rows:
        print(f"  {d:6.1f}  {k:4d}  {mean:7.1f} ({mn}~{mx})    {e:6.2f}   {err:+5.0f}%")
    try:
        plot_png(pts, p1m, n, rows, out)
        print(f"그래프: {out}")
    except ImportError:
        svg = os.path.splitext(out)[0] + ".svg"
        plot_svg(pts, p1m, n, rows, svg)
        print(f"그래프: {svg} (matplotlib 없음 → SVG. PNG는 'python3 -m pip install matplotlib' 후)")
    return p1m, n, r2


def self_test():
    random.seed(1)
    true_p1m, true_n = -61.0, 2.3
    pts = []
    for d in (1, 3, 5, 10):
        for _ in range(8):
            rssi = true_p1m - 10 * true_n * math.log10(d) + random.gauss(0, 1.5)
            pts.append((d, int(round(rssi)), 1, 2))
    p1m, n, r2 = fit(pts)
    assert abs(p1m - true_p1m) < 1.5 and abs(n - true_n) < 0.25 and r2 > 0.9, (p1m, n, r2)
    assert abs(est(-61 - 23, -61, 2.3) - 10.0) < 1e-6
    # CSV 경로: mark + RANGING 프레임
    import tempfile
    path = tempfile.mktemp(suffix=".csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["time", "t_s", "dir", "soldier", "type", "name", "seq", "src", "dst", "len", "hex"])
        for d in (1, 3, 5, 10):
            w.writerow(["", "", "mark", "", "", str(d), "", "", "", 0, ""])
            for k in range(3):
                rssi = int(round(true_p1m - 10 * true_n * math.log10(d)))
                raw = fc.encode(dict(type=fc.RANGING, seq=k, src=1, dst=0x80, peers=[dict(peer_id=2, rssi_avg=rssi, samples=15)]))
                w.writerow(["", "", "rx", 1, "0x0E", "RANGING", k, 1, "0x80", len(raw), raw.hex()])
        w.writerow(["", "", "mark", "", "", "-", "", "", "", 0, ""])
        raw = fc.encode(dict(type=fc.RANGING, seq=9, src=1, dst=0x80, peers=[dict(peer_id=2, rssi_avg=-40, samples=15)]))
        w.writerow(["", "", "rx", 1, "0x0E", "RANGING", 9, 1, "0x80", len(raw), raw.hex()])  # 구간 밖 → 무시
    got = load_points([path], 5)
    os.unlink(path)
    assert len(got) == 12 and {d for d, *_ in got} == {1, 3, 5, 10}, got
    p1m, n, _ = fit(got)
    assert abs(p1m - true_p1m) < 1 and abs(n - true_n) < 0.1, (p1m, n)
    out = tempfile.mktemp(suffix=".svg")
    plot_svg(pts, p1m, n, summary(pts, p1m, n), out)
    assert os.path.getsize(out) > 1000
    os.unlink(out)
    print(f"fit_pathloss self-test OK (합성 데이터 P1m {true_p1m}, n {true_n} → {p1m:.1f}, {n:.2f})")


def main():
    ap = argparse.ArgumentParser(description="RANGING CSV → 경로손실 보정(P1m, n) + 그래프")
    ap.add_argument("csv", nargs="*")
    ap.add_argument("--out", default="pathloss.png")
    ap.add_argument("--min-samples", type=int, default=5, help="중앙값에 쓴 표본이 이보다 적은 RANGING 항목은 버림")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        self_test()
        return
    if not args.csv:
        ap.error("CSV 파일을 주세요(또는 --self-test)")
    report(load_points(args.csv, args.min_samples), args.out)


if __name__ == "__main__":
    main()
