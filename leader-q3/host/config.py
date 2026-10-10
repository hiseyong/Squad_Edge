"""분대장1 SoftAP + BLE + TCP 브리지 설정 (Arduino UNO Q Linux / 로컬 mock 공용)."""
from __future__ import annotations

import os

# 역할
NODE_ID = os.getenv("Q3_NODE_ID", "1-1")
SQUAD_ID = os.getenv("Q3_SQUAD_ID", "1")
MEMBERS = ("1-2", "1-3", "1-4")

# SoftAP
AP_SSID = os.getenv("Q3_AP_SSID", "SquadEdge-1-1")
AP_PASS = os.getenv("Q3_AP_PASS", "squadedge1")  # WPA2, 8자 이상
AP_IFACE = os.getenv("Q3_AP_IFACE", "wlan0")
AP_IP = os.getenv("Q3_AP_IP", "192.168.4.1")
AP_CIDR = os.getenv("Q3_AP_CIDR", "24")

# COP ↔ 보드 TCP (보드가 listen, 노트북이 join 후 connect)
LISTEN_HOST = os.getenv("Q3_LISTEN_HOST", "0.0.0.0")
LISTEN_PORT = int(os.getenv("Q3_LISTEN_PORT", "9000"))

# 상향 주기
PERIOD_S = float(os.getenv("Q3_PERIOD_S", "1.0"))

# 데모 GPS 원점
DEMO_LAT = float(os.getenv("Q3_DEMO_LAT", "36.3005"))
DEMO_LON = float(os.getenv("Q3_DEMO_LON", "127.4185"))

# Bridge MCU RPC (없으면 내장 데모 포즈)
USE_BRIDGE = os.getenv("Q3_USE_BRIDGE", "1") == "1"
RPC_TELEMETRY = "telemetry_json"
RPC_ORDER = "order_notify"
RPC_PING = "ping"

# BLE Central (NU40-DK)
BLE_ENABLE = os.getenv("Q3_BLE", "1") == "1"
BLE_ONLY = os.getenv("Q3_BLE_ONLY", "1,2,3")  # SQ1-S1.. 기본 3명 시연
BLE_FORMATION = os.getenv("Q3_FORMATION", "wedge")  # wedge|line|column
BLE_LOCALIZE_S = float(os.getenv("Q3_LOCALIZE_S", "10"))
BLE_PATHLOSS_P1M = float(os.getenv("Q3_PATHLOSS_P1M", "-59"))
BLE_PATHLOSS_N = float(os.getenv("Q3_PATHLOSS_N", "2.0"))
BLE_RELAY = os.getenv("Q3_BLE_RELAY", "1") == "1"

# LeaderBeacon(보드 A) USB — 분대장 줄 RSSI (선택)
BEACON_PORT = os.getenv("Q3_BEACON_PORT", "")  # 예: /dev/ttyACM0
BEACON_BAUD = int(os.getenv("Q3_BEACON_BAUD", "115200"))


def parse_ble_only(s: str | None = None) -> set[int]:
    raw = s if s is not None else BLE_ONLY
    out: set[int] = set()
    for tok in raw.replace(" ", "").split(","):
        if not tok:
            continue
        tok = tok.upper().lstrip("S")
        out.add(int(tok))
    return out or {1, 2, 3}
