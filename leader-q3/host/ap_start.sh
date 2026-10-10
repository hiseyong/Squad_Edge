#!/usr/bin/env bash
# Arduino UNO Q (Linux) SoftAP 기동 — 분대장1
#   sudo ./ap_start.sh
#   sudo Q3_AP_SSID=SquadEdge-1-1 Q3_AP_PASS=squadedge1 ./ap_start.sh
set -euo pipefail

SSID="${Q3_AP_SSID:-SquadEdge-1-1}"
PASS="${Q3_AP_PASS:-squadedge1}"
IFACE="${Q3_AP_IFACE:-wlan0}"
IP="${Q3_AP_IP:-192.168.4.1}"
CIDR="${Q3_AP_CIDR:-24}"
CONN_NAME="${Q3_AP_CONN:-squadedge-ap}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "root 필요: sudo $0" >&2
  exit 1
fi

echo "[ap] iface=$IFACE ssid=$SSID ip=$IP/$CIDR"

if command -v nmcli >/dev/null 2>&1; then
  # NetworkManager hotspot (배포판에 따라 IP 가 10.42.0.1 일 수 있음 → 아래에서 고정 시도)
  nmcli connection delete "$CONN_NAME" 2>/dev/null || true
  nmcli device wifi hotspot ifname "$IFACE" con-name "$CONN_NAME" ssid "$SSID" password "$PASS" || {
    echo "[ap] nmcli hotspot 실패 — hostapd 경로를 쓰거나 Wi-Fi 인터페이스를 확인하세요" >&2
    exit 1
  }
  # 가능하면 AP IPv4 를 192.168.4.1 로 맞춤
  nmcli connection modify "$CONN_NAME" \
    ipv4.method shared \
    ipv4.addresses "${IP}/${CIDR}" 2>/dev/null || true
  nmcli connection up "$CONN_NAME" 2>/dev/null || true
  echo "[ap] NetworkManager hotspot OK"
  nmcli -f GENERAL.STATE,IP4.ADDRESS device show "$IFACE" 2>/dev/null || true
  echo "[ap] COP 노트북을 SSID=$SSID 에 연결한 뒤  python3 bridge_server.py"
  exit 0
fi

echo "[ap] nmcli 없음. hostapd/dnsmasq 수동 구성이 필요합니다." >&2
exit 1
