#!/usr/bin/env bash
# 분대장 보드 AP 끄기.   sudo tools/ap_stop.sh [복귀할 Wi-Fi 연결 이름]
# 동시 운용(uap0)이면 AP만 내리고 회장 Wi-Fi는 그대로. 전용 모드(--exclusive)였으면 원래 Wi-Fi로 복귀.
set -uo pipefail
CONN="${Q3_AP_CONN:-squadedge-ap}"
VIF="${Q3_AP_IFACE:-uap0}"
BACK="${1:-D4D_Hacker_03}"
IW=$(command -v iw || echo /usr/sbin/iw)
[[ "$(id -u)" -eq 0 ]] || { echo "root 필요: sudo $0" >&2; exit 1; }
nmcli connection down "$CONN" 2>/dev/null
nmcli connection delete "$CONN" >/dev/null 2>&1
if $IW dev "$VIF" info >/dev/null 2>&1; then
  $IW dev "$VIF" del && echo "[ap] $VIF 제거"
fi
nmcli -t -f NAME connection show --active | grep -qx "$BACK" || nmcli connection up "$BACK"
echo "[ap] AP 끔"
