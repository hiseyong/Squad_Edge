"""BLE 병사 ID(1~5) ↔ COP 유닛 ID(`1-2` …) 매핑.

프로토콜: 분대장 BLE id=0, 병사 1~5 (광고명 SQ1-S{n}).
COP: 분대장 `1-1`, 분대원 `1-2`… (`-1` = 분대장).
→ BLE soldier n  ≡  COP `{squad}-{n+1}`
"""
from __future__ import annotations


def ble_to_cop(squad: str, ble_id: int) -> str:
    if ble_id == 0:
        return f"{squad}-1"
    if 1 <= ble_id <= 5:
        return f"{squad}-{ble_id + 1}"
    raise ValueError(f"ble_id 범위 밖: {ble_id}")


def cop_to_ble(unit_id: str) -> int | None:
    """COP 유닛 → BLE id. 분대장이면 0, 분대원이면 1~5, 파싱 불가면 None."""
    try:
        _, num = unit_id.split("-", 1)
        n = int(num)
    except (ValueError, AttributeError):
        return None
    if n == 1:
        return 0
    if 2 <= n <= 6:
        return n - 1
    return None


def cop_members(squad: str, count: int = 3) -> list[str]:
    """시연용 분대원 COP ID 목록 (기본 1-2..1-4)."""
    return [f"{squad}-{i}" for i in range(2, 2 + count)]
