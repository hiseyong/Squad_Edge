#!/usr/bin/env python3
"""시연 AOI 베이스맵 타일을 미리 받아 SoftAP 오프라인에서도 지도를 띄운다.

  ※ OpenStreetMap 공식 tile.openstreetmap.org 는 사용하지 않음
     (자원봉사자 서버 사용정책 → 앱/대량 요청 시 403).

  기본 소스: Esri World Imagery (시연 AOI 고해상도)

  python3 tools/fetch_offline_tiles.py
  python3 tools/fetch_offline_tiles.py --zmin 15 --zmax 19
  python3 tools/fetch_offline_tiles.py --source street

저장: <repo>/tiles/{z}/{x}/{y}.jpg  (Leaflet XYZ, Esri imagery)
사용: 대시보드 「오프라인 위성 (시연 AOI)」
"""
from __future__ import annotations

import argparse
import math
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tiles"

# simulator ROUTE / SoftAP demo 원점 주변 (+여유)
DEFAULT_BBOX = (36.2980, 127.4150, 36.3120, 127.4320)  # S, W, N, E
UA = "SquadEdgeCOP/1.0 (offline demo cache; local competition; no redistribution)"

# Esri ArcGIS Online — URL은 {z}/{y}/{x} (Leaflet 저장은 z/x/y.png)
SOURCES = {
    "dark": (
        "https://server.arcgisonline.com/ArcGIS/rest/services/"
        "Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}"
    ),
    "imagery": (
        "https://server.arcgisonline.com/ArcGIS/rest/services/"
        "World_Imagery/MapServer/tile/{z}/{y}/{x}"
    ),
    "street": (
        "https://server.arcgisonline.com/ArcGIS/rest/services/"
        "World_Street_Map/MapServer/tile/{z}/{y}/{x}"
    ),
}


def deg2num(lat: float, lon: float, z: int) -> tuple[int, int]:
    lat_r = math.radians(lat)
    n = 2.0**z
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(lat_r)) / math.pi) / 2.0 * n)
    return x, y


def tiles_for_bbox(s: float, w: float, n: float, e: float, z: int) -> list[tuple[int, int, int]]:
    x0, y1 = deg2num(s, w, z)  # south-west → larger y
    x1, y0 = deg2num(n, e, z)  # north-east → smaller y
    xs = range(min(x0, x1), max(x0, x1) + 1)
    ys = range(min(y0, y1), max(y0, y1) + 1)
    return [(z, x, y) for x in xs for y in ys]


def fetch_one(url_tmpl: str, z: int, x: int, y: int, dest: Path, pause: float) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 100:
        return False
    url = url_tmpl.format(z=z, x=x, y=y)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://localhost/"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
        # Esri imagery = JPEG; dark/street may be PNG
        ok = (len(data) > 100 and (
            data[:8] == b"\x89PNG\r\n\x1a\n" or data[:2] == b"\xff\xd8"
        ))
        if not ok:
            print(f"  skip bad {z}/{x}/{y}", file=sys.stderr)
            return False
        dest.write_bytes(data)
        time.sleep(pause)
        return True
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code} {z}/{x}/{y}", file=sys.stderr)
        time.sleep(pause * 2)
        return False
    except Exception as e:
        print(f"  err {z}/{x}/{y}: {e}", file=sys.stderr)
        time.sleep(pause * 2)
        return False


def main() -> None:
    p = argparse.ArgumentParser(description="Offline basemap tiles for COP SoftAP (not OSM.org)")
    p.add_argument("--out", type=Path, default=OUT)
    p.add_argument("--zmin", type=int, default=14)
    p.add_argument("--zmax", type=int, default=19)
    p.add_argument("--pause", type=float, default=0.06, help="요청 간격(초)")
    p.add_argument("--source", choices=sorted(SOURCES), default="imagery")
    p.add_argument("--force", action="store_true", help="기존 타일 덮어쓰기")
    p.add_argument("--bbox", type=float, nargs=4, metavar=("S", "W", "N", "E"), default=None)
    args = p.parse_args()
    s, w, n, e = args.bbox or DEFAULT_BBOX
    url_tmpl = SOURCES[args.source]
    jobs: list[tuple[int, int, int]] = []
    for z in range(args.zmin, args.zmax + 1):
        jobs.extend(tiles_for_bbox(s, w, n, e, z))
    print(f"source={args.source}  AOI={s},{w},{n},{e}  z={args.zmin}..{args.zmax}  tiles={len(jobs)}  → {args.out}")
    got = skip = 0
    for i, (z, x, y) in enumerate(jobs, 1):
        dest = args.out / str(z) / str(x) / f"{y}.jpg"
        # 예전 .png 캐시 정리
        legacy = dest.with_suffix(".png")
        if args.force and dest.exists():
            dest.unlink()
        if args.force and legacy.exists():
            legacy.unlink()
        if dest.exists() and dest.stat().st_size > 100:
            skip += 1
        elif fetch_one(url_tmpl, z, x, y, dest, args.pause):
            got += 1
        if i % 50 == 0 or i == len(jobs):
            print(f"  [{i}/{len(jobs)}] new={got} cached={skip}")
    print(f"done new={got} cached={skip} under {args.out}")
    (args.out / ".offline_ready").write_text(
        f"source={args.source} z={args.zmin}-{args.zmax} bbox={s},{w},{n},{e} tiles≈{len(jobs)}\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
