#!/usr/bin/env python3
"""분대 위치 복원(분대장 측 로직) — RANGING(0x0E) RSSI → 쌍별 거리 → MDS → 분대장 원점·북쪽 정렬 → POS_TABLE.

분대장 팀원이 UNO Q(리눅스 Python)로 그대로 옮길 수 있게 **표준 라이브러리만** 쓴다(numpy 없음).

입력
- 병사 줄: 병사 i의 RANGING에서 peer j의 RSSI 중앙값(peer 0 = 분대장 비콘).
- 분대장 줄(ID 0): 분대장이 직접 잰 병사 비콘(0x20) RSSI 중앙값.
- 경로손실 모델 d = 10^((P1m − RSSI) / (10·n)) [m] (tools/fit_pathloss.py로 보정).

절차
1) N×N 거리 행렬(ID 0 = 분대장 + 병사들). i→j, j→i 둘 다 있으면 양방향 평균, 하나만 있으면 그 값.
2) 실측이 없는 쌍은 프리셋 대형(wedge/line/column, 간격 10m)의 거리로 채운다.
3) 고전 MDS(이중 중심화 → 고유값 분해, 2차원) — 야코비 고유값 분해(N ≤ 8이라 충분).
4) MDS 결과는 회전·반사·평행이동이 정해지지 않는다(거리만으로는 북쪽을 알 수 없음) →
   분대장(ID 0)을 원점으로 옮기고, 프리셋 대형에 가장 잘 맞는 회전(+필요하면 반사)으로 돌린다(앵커 고정 프로크루스테스).
   즉 "대형의 진행 방향 = 북쪽"이라는 가정으로 방위를 정한다. GPS/나침반이 붙으면 이 단계만 바꾸면 된다.
5) POS_TABLE 항목(0.1m 정수, heading).

좌표: 분대장 원점, x 동쪽, y 북쪽, 단위 m(POS_TABLE은 0.1m).

사용
    python3 tools/squad_localize.py --self-test
    python3 tools/squad_localize.py --demo
"""

import math
import random

SPACING_M = 10.0
IDS_ALL = (0, 1, 2, 3, 4, 5)  # 0 = 분대장


# ---------- 프리셋 대형 (진행 방향 = 북쪽 +y, 분대장 원점) ----------
def preset_positions(name, spacing=SPACING_M):
    """{id: (x, y)} m. 0 = 분대장(원점). 병사 1~5."""
    s = spacing
    d = s / math.sqrt(2.0)
    if name == "line":  # 횡대: 분대장 좌우로 번갈아
        p = {1: (-s, 0.0), 2: (s, 0.0), 3: (-2 * s, 0.0), 4: (2 * s, 0.0), 5: (-3 * s, 0.0)}
    elif name == "column":  # 종대: 분대장 앞뒤로
        p = {1: (0.0, s), 2: (0.0, -s), 3: (0.0, 2 * s), 4: (0.0, -2 * s), 5: (0.0, -3 * s)}
    elif name == "wedge":  # 쐐기: 분대장이 꼭짓점, 좌우 뒤쪽 45°로
        p = {1: (-d, -d), 2: (d, -d), 3: (-2 * d, -2 * d), 4: (2 * d, -2 * d), 5: (-3 * d, -3 * d)}
    else:
        raise ValueError(f"대형 '{name}' 모름 (wedge|line|column)")
    p[0] = (0.0, 0.0)
    return p


PRESETS = ("wedge", "line", "column")


def rssi_to_m(rssi, p1m=-59.0, n=2.0):
    return 10 ** ((p1m - rssi) / (10.0 * n))


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


# ---------- 거리 행렬 ----------
def build_matrix(ids, measured, prior):
    """measured: {(i, j): 거리 m} (방향 있음, i가 j를 잼). 반환 (D, src) — src[i][j] = 'meas'|'one'|'prior'."""
    n = len(ids)
    D = [[0.0] * n for _ in range(n)]
    src = [[""] * n for _ in range(n)]
    for a in range(n):
        for b in range(a + 1, n):
            i, j = ids[a], ids[b]
            v = [measured[k] for k in ((i, j), (j, i)) if k in measured and measured[k] > 0]
            if len(v) == 2:
                d, s = (v[0] + v[1]) / 2.0, "meas"   # 양방향 평균
            elif len(v) == 1:
                d, s = v[0], "one"                    # 한쪽만 들림
            else:
                d, s = dist(prior[i], prior[j]), "prior"
            D[a][b] = D[b][a] = d
            src[a][b] = src[b][a] = s
    return D, src


# ---------- 고전 MDS ----------
def jacobi_eigen(A, iters=100):
    """대칭 행렬 고유값 분해(야코비). 반환 (값 목록, 벡터 목록[각 벡터는 길이 n])."""
    n = len(A)
    a = [row[:] for row in A]
    v = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    for _ in range(iters):
        off = sum(a[i][j] ** 2 for i in range(n) for j in range(n) if i != j)
        if off < 1e-18:
            break
        for p in range(n):
            for q in range(p + 1, n):
                if abs(a[p][q]) < 1e-15:
                    continue
                th = (a[q][q] - a[p][p]) / (2 * a[p][q])
                t = (1.0 if th >= 0 else -1.0) / (abs(th) + math.sqrt(th * th + 1))
                c = 1 / math.sqrt(t * t + 1)
                s = t * c
                for k in range(n):  # 열 회전
                    akp, akq = a[k][p], a[k][q]
                    a[k][p], a[k][q] = c * akp - s * akq, s * akp + c * akq
                for k in range(n):  # 행 회전
                    apk, aqk = a[p][k], a[q][k]
                    a[p][k], a[q][k] = c * apk - s * aqk, s * apk + c * aqk
                for k in range(n):
                    vkp, vkq = v[k][p], v[k][q]
                    v[k][p], v[k][q] = c * vkp - s * vkq, s * vkp + c * vkq
    vals = [a[i][i] for i in range(n)]
    vecs = [[v[k][i] for k in range(n)] for i in range(n)]
    return vals, vecs


def classical_mds(D):
    """거리 행렬 → 2차원 좌표 목록 [(x, y)]."""
    n = len(D)
    sq = [[D[i][j] ** 2 for j in range(n)] for i in range(n)]
    rmean = [sum(r) / n for r in sq]
    tmean = sum(rmean) / n
    B = [[-0.5 * (sq[i][j] - rmean[i] - rmean[j] + tmean) for j in range(n)] for i in range(n)]
    vals, vecs = jacobi_eigen(B)
    order = sorted(range(n), key=lambda k: -vals[k])[:2]
    cols = [[x * math.sqrt(max(vals[k], 0.0)) for x in vecs[k]] for k in order]
    return [(cols[0][i], cols[1][i]) for i in range(n)]


# ---------- 정렬(분대장 원점, 프리셋에 맞춘 회전/반사) ----------
def align_to_prior(points, ids, prior, anchor=0):
    """points[k] ↔ ids[k]. anchor(분대장)를 원점으로, 프리셋에 최소제곱으로 맞는 회전(+반사 후보)."""
    k0 = ids.index(anchor)
    ax, ay = points[k0]
    P = [(x - ax, y - ay) for x, y in points]
    Q = [prior[i] for i in ids]
    best = None
    for flip in (False, True):
        Pf = [(-x, y) if flip else (x, y) for x, y in P]
        sxy = sum(px * qy - py * qx for (px, py), (qx, qy) in zip(Pf, Q))
        sdot = sum(px * qx + py * qy for (px, py), (qx, qy) in zip(Pf, Q))
        th = math.atan2(sxy, sdot)
        c, s = math.cos(th), math.sin(th)
        R = [(c * x - s * y, s * x + c * y) for x, y in Pf]
        err = sum(dist(r, q) ** 2 for r, q in zip(R, Q))
        if best is None or err < best[0]:
            best = (err, R, flip, math.degrees(th))
    _, R, flip, rot = best
    return {i: R[k] for k, i in enumerate(ids)}, {"flip": flip, "rot_deg": rot}


def stress(pos, ids, D):
    """복원 좌표의 거리와 입력 거리의 RMS 차이(m)."""
    e, m = 0.0, 0
    for a in range(len(ids)):
        for b in range(a + 1, len(ids)):
            e += (dist(pos[ids[a]], pos[ids[b]]) - D[a][b]) ** 2
            m += 1
    return math.sqrt(e / m) if m else 0.0


def localize(ids, measured, formation="wedge", spacing=SPACING_M):
    """ids: 위치를 구할 ID 목록(0 포함 권장). measured: {(i, j): m}.
    반환 (positions {id: (x, y)}, info). 실측 쌍이 하나도 없으면 프리셋 그대로."""
    ids = sorted(set(ids) | {0})
    prior = preset_positions(formation, spacing)
    D, src = build_matrix(ids, measured, prior)
    n_meas = sum(1 for a in range(len(ids)) for b in range(a + 1, len(ids)) if src[a][b] != "prior")
    n_pairs = len(ids) * (len(ids) - 1) // 2
    info = {"pairs": n_pairs, "measured": n_meas, "formation": formation, "src": src, "D": D, "ids": ids}
    if n_meas == 0:
        info.update(method="preset", stress=0.0)
        return {i: prior[i] for i in ids}, info
    pts = classical_mds(D)
    pos, al = align_to_prior(pts, ids, prior)
    info.update(method="mds", stress=stress(pos, ids, D), **al)
    return pos, info


def measured_from_rssi(rows, p1m=-59.0, n=2.0):
    """rows: {i: {j: rssi_median}} (i가 j의 비콘을 잼, 0 = 분대장 줄) → {(i, j): m}."""
    return {(i, j): rssi_to_m(r, p1m, n) for i, peers in rows.items() for j, r in peers.items() if i != j}


def to_pos_table(pos, headings=None):
    """POS_TABLE entries(frame_codec 형식): 0.1m 정수, heading(없으면 0)."""
    headings = headings or {}
    out = []
    for i in sorted(pos):
        x, y = pos[i]
        out.append(dict(id=i, x=max(-32768, min(32767, int(round(x * 10)))),
                        y=max(-32768, min(32767, int(round(y * 10)))), heading=headings.get(i, 0)))
    return out


# ---------- 표적 변환(병사 펌웨어 core/geo와 같은 규칙, 지도 표시·시나리오 계산용) ----------
DIST_REP_M = {0: 50.0, 1: 100.0, 2: 200.0}  # 없음(0xFF) = 100m


def clock_from(az, heading=0):
    rel = (az - heading) % 360
    c = (rel + 15) // 30   # 프로토콜 §5.1: .5 올림
    return 12 if c == 0 else int(c)


def target_pos(rep, az, dist_band):
    d = DIST_REP_M.get(dist_band, 100.0)
    a = math.radians(az)
    return (rep[0] + d * math.sin(a), rep[1] + d * math.cos(a))


def bearing_range(p, t):
    dx, dy = t[0] - p[0], t[1] - p[1]
    return int(round(math.degrees(math.atan2(dx, dy)))) % 360, math.hypot(dx, dy)


def band_of(r):
    return 0 if r < 75 else (1 if r < 150 else 2)


def peer_to_me(rep, az, dist_band, me, my_heading=0):
    """→ (clock, band, bearing, range_m)."""
    t = target_pos(rep, az, dist_band)
    b, r = bearing_range(me, t)
    return clock_from(b, my_heading), band_of(r), b, r


# ---------- 시험 ----------
def _self_test():
    rnd = random.Random(1)
    ok = True
    # 1) MDS가 정확한 거리에서 위치를 복원(회전·반사 포함)
    for name in PRESETS:
        truth = preset_positions(name)
        ids = [0, 1, 2, 3, 4, 5]
        # 실제 배치를 프리셋에서 조금 비틀고 측정 = 정확한 거리(양방향)
        real = {i: (x + rnd.uniform(-2, 2), y + rnd.uniform(-2, 2)) for i, (x, y) in truth.items()}
        real[0] = (0.0, 0.0)
        meas = {(i, j): dist(real[i], real[j]) for i in ids for j in ids if i != j}
        pos, info = localize(ids, meas, name)
        err = max(dist(pos[i], real[i]) for i in ids)
        print(f"  {name}: 정확한 거리 → stress {info['stress']:.3f}m, 최대 위치 오차 {err:.2f}m"
              f"(방위는 프리셋에 맞춘 것이라 실제와 약간 다름), 반사 {info['flip']}")
        ok &= info["stress"] < 0.01 and err < 2.0
    # 2) 비대칭(양방향 평균)·잡음
    truth = preset_positions("line")
    ids = [0, 1, 2]
    meas = {}
    for i in ids:
        for j in ids:
            if i != j:
                meas[(i, j)] = dist(truth[i], truth[j]) * (1.2 if i < j else 0.8)  # 평균하면 정확
    D, src = build_matrix(ids, meas, truth)
    ok &= abs(D[1][2] - 20.0) < 1e-9 and src[1][2] == "meas"
    print(f"  비대칭 평균: D(1,2)={D[1][2]:.2f}m (기대 20.00)")
    # 3) 실측이 일부만 → 나머지는 프리셋으로 채움
    pos, info = localize([0, 1, 2], {(1, 2): 30.0, (2, 1): 30.0}, "line")
    ok &= info["measured"] == 1 and info["src"][0][1] == "prior"
    print(f"  부분 실측: 실측 {info['measured']}/{info['pairs']}쌍, S1-S2 {dist(pos[1], pos[2]):.1f}m, "
          f"S1 ({pos[1][0]:.1f},{pos[1][1]:.1f}) S2 ({pos[2][0]:.1f},{pos[2][1]:.1f})")
    # 4) 실측 없음 → 프리셋 그대로
    pos, info = localize([0, 1, 2], {}, "column")
    ok &= info["method"] == "preset" and pos[1] == (0.0, 10.0)
    # 5) RSSI → 거리 → POS_TABLE
    rows = {1: {0: -79, 2: -85}, 2: {0: -79, 1: -85}, 0: {1: -79, 2: -79}}  # P1m -59, n 2 → 10m, ~20m
    pos, info = localize([0, 1, 2], measured_from_rssi(rows), "line")
    tab = to_pos_table(pos)
    print(f"  RSSI 예: {[(e['id'], e['x'], e['y']) for e in tab]} (0.1m), stress {info['stress']:.2f}m")
    ok &= abs(dist(pos[0], pos[1]) - 10.0) < 1.5 and abs(dist(pos[1], pos[2]) - rssi_to_m(-85)) < 1.5
    # 6) 시계 규칙
    ok &= clock_from(15) == 1 and clock_from(345) == 12 and clock_from(0) == 12 and clock_from(45) == 2
    print("self-test", "OK" if ok else "FAIL")
    return ok


def _demo():
    truth = {0: (0.0, 0.0), 1: (-8.0, -6.0), 2: (9.0, -5.0)}
    rows = {}
    for i in truth:
        rows[i] = {}
        for j in truth:
            if i != j:
                d = dist(truth[i], truth[j])
                rows[i][j] = round(-59 - 20 * math.log10(d) + random.uniform(-2, 2))
    print("RSSI 행(i가 j를 잼):", rows)
    pos, info = localize(list(truth), measured_from_rssi(rows), "wedge")
    for i in sorted(pos):
        print(f"  ID {i}: 추정 ({pos[i][0]:6.1f}, {pos[i][1]:6.1f}) m   실제 ({truth[i][0]:6.1f}, {truth[i][1]:6.1f})")
    print(f"  stress {info['stress']:.2f}m, 실측 {info['measured']}/{info['pairs']}쌍")
    print("  POS_TABLE:", to_pos_table(pos))


if __name__ == "__main__":
    import sys
    if "--self-test" in sys.argv:
        sys.exit(0 if _self_test() else 1)
    elif "--demo" in sys.argv:
        _demo()
    else:
        print(__doc__)
