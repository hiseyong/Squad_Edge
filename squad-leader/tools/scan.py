"""주변 BLE 기기 스캔. SQ1-S* 병사 단말과 NUS 광고를 표시한다."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bleak import BleakScanner  # noqa: E402
from squad.protocol import NUS_SERVICE  # noqa: E402


async def main(seconds: float = 8.0):
    found = await BleakScanner.discover(timeout=seconds, return_adv=True)
    rows = sorted(found.values(), key=lambda da: -da[1].rssi)
    for dev, adv in rows:
        name = adv.local_name or dev.name or ""
        tag = " <== 병사" if name.startswith("SQ1-S") else ""
        nus = " [NUS]" if NUS_SERVICE in adv.service_uuids else ""
        print(f"{dev.address}  {adv.rssi:4d} dBm  {name}{nus}{tag}")
    print(f"총 {len(rows)}대")


if __name__ == "__main__":
    asyncio.run(main(float(sys.argv[1]) if len(sys.argv) > 1 else 8.0))
