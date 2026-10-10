"""분대 위치 복원: RANGING RSSI → 쌍별 거리 → 고전 MDS → 분대장 원점·방향 정렬 → POS_TABLE.

포팅 원본: ~/work/soldier-node_ref_v1.1/tools/squad_localize.py (계산 로직 그대로, 표준 라이브러리만)
원본과 다른 점(병사 팀 안내문 2026-10-11)
- 경로손실 기본값 = config(−65.5 dBm, n 1.6). 원본 rssi_to_m/measured_from_rssi 기본 인자(−59, 2.0)는 옛 값(P3).
- POS_TABLE 0.1m 변환은 0에서 먼 쪽 반올림(P2). 원본 round()(짝수 쪽)는 따르지 않는다.
- 입력은 병사 RANGING 줄만(D4). 분대장 줄(rows[0])은 없어도 된다.
좌표: 분대장 원점, x 동쪽, y 북쪽, m.
"""
import math

from . import config
from .geo import m_to_dm, rssi_to_m

SPACING_M = config.FORMATION_SPACING_M
DEFAULT_CLOCKS = config.DEFAULT_CLOCKS


def clock_to_deg(clock):
    """시계(1~12, 분대장 총구 = 북쪽 기준) → 방위(도)."""
    return (int(clock) % 12) * 30


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


def align_to_clocks(points, ids, clocks, prior=None, anchor=0):
    """분대장(anchor)을 원점으로 옮기고, clocks {id: 시계}의 방향에 가장 잘 맞는 회전(+반사)으로 돌린다.
    목표 벡터 = 그 방향의 단위 벡터 × 실측 거리(먼 병사의 방향일수록 무게가 큼). 방향이 하나뿐이라 반사가
    안 정해지면 prior(프리셋)로 고른다."""
    k0 = ids.index(anchor)
    ax, ay = points[k0]
    P = [(x - ax, y - ay) for x, y in points]
    use = [k for k, i in enumerate(ids) if i in clocks and i != anchor]
    if not use:
        return None
    Q = {}
    for k in use:
        r = math.hypot(*P[k])
        a = math.radians(clock_to_deg(clocks[ids[k]]))
        Q[k] = (r * math.sin(a), r * math.cos(a))
    cands = []
    for flip in (False, True):
        Pf = [(-x, y) if flip else (x, y) for x, y in P]
        sxy = sum(Pf[k][0] * Q[k][1] - Pf[k][1] * Q[k][0] for k in use)
        sdot = sum(Pf[k][0] * Q[k][0] + Pf[k][1] * Q[k][1] for k in use)
        th = math.atan2(sxy, sdot)
        c, s = math.cos(th), math.sin(th)
        R = [(c * x - s * y, s * x + c * y) for x, y in Pf]
        err = sum(dist(R[k], Q[k]) ** 2 for k in use)
        perr = sum(dist(R[k], prior[ids[k]]) ** 2 for k in range(len(ids))) if prior else 0.0
        cands.append((round(err, 6), perr, R, flip, math.degrees(th)))
    cands.sort(key=lambda c: (c[0], c[1]))
    err, _, R, flip, rot = cands[0]
    return {i: R[k] for k, i in enumerate(ids)}, {"flip": flip, "rot_deg": rot, "align": "clocks",
                                                 "clock_err_m": math.sqrt(err / len(use))}


def stress(pos, ids, D):
    """복원 좌표의 거리와 입력 거리의 RMS 차이(m)."""
    e, m = 0.0, 0
    for a in range(len(ids)):
        for b in range(a + 1, len(ids)):
            e += (dist(pos[ids[a]], pos[ids[b]]) - D[a][b]) ** 2
            m += 1
    return math.sqrt(e / m) if m else 0.0


def localize(ids, measured, formation="wedge", spacing=SPACING_M, clocks=None):
    """ids: 위치를 구할 ID 목록(0 포함 권장). measured: {(i, j): m}.
    clocks: 분대장이 본 병사 방향 {id: 시계 1~12}(기본 DEFAULT_CLOCKS, {}이면 프리셋에 맞춤).
    반환 (positions {id: (x, y)}, info). 실측 쌍이 하나도 없으면 프리셋 그대로."""
    ids = sorted(set(ids) | {0})
    clocks = DEFAULT_CLOCKS if clocks is None else clocks
    prior = preset_positions(formation, spacing)
    D, src = build_matrix(ids, measured, prior)
    n_meas = sum(1 for a in range(len(ids)) for b in range(a + 1, len(ids)) if src[a][b] != "prior")
    n_pairs = len(ids) * (len(ids) - 1) // 2
    info = {"pairs": n_pairs, "measured": n_meas, "formation": formation, "src": src, "D": D, "ids": ids,
            "clocks": {i: c for i, c in clocks.items() if i in ids}}
    if n_meas == 0:
        info.update(method="preset", stress=0.0, align="preset")
        return {i: prior[i] for i in ids}, info
    pts = classical_mds(D)
    got = align_to_clocks(pts, ids, clocks, prior) if clocks else None
    if got is None:
        pos, al = align_to_prior(pts, ids, prior)
        al["align"] = "preset"
    else:
        pos, al = got
    info.update(method="mds", stress=stress(pos, ids, D), **al)
    return pos, info


def measured_from_distances(d01, d02, d12):
    """분대장–S1, 분대장–S2, S1–S2 거리(m)를 직접 넣을 때(시연 예비·검증용)."""
    return {(0, 1): d01, (1, 0): d01, (0, 2): d02, (2, 0): d02, (1, 2): d12, (2, 1): d12}


def measured_from_rssi(rows, p1m=config.PATHLOSS_P1M_DBM, n=config.PATHLOSS_N):
    """rows: {i: {j: rssi_median}} (i가 j의 비콘을 잼. 이번 구성은 병사 줄만, peer 0 = 분대장) → {(i, j): m}."""
    return {(i, j): rssi_to_m(r, p1m, n) for i, peers in rows.items() for j, r in peers.items() if i != j}


def to_pos_table(pos, headings=None):
    """POS_TABLE entries(codec 형식): 0.1m 정수(0에서 먼 쪽 반올림), heading(없으면 0)."""
    headings = headings or {}
    return [dict(id=i, x=m_to_dm(pos[i][0]), y=m_to_dm(pos[i][1]), heading=headings.get(i, 0)) for i in sorted(pos)]
