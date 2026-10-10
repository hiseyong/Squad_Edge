#!/usr/bin/env bash
# 분대장 보드 Wi-Fi AP 켜기 (소대장 노트북 COP 연결용). 팀 COP 기본값과 같은 SSID·주소.
#   sudo tools/ap_start.sh               # 기본: 회장 Wi-Fi(wlan0)는 유지하고 가상 인터페이스 uap0로 AP 동시 운용
#   sudo tools/ap_start.sh --exclusive   # wlan0 자체를 AP로 전환 (회장 Wi-Fi·인터넷 끊김)
#   sudo Q3_AP_PASS=다른비번 tools/ap_start.sh
# 동시 운용 (ath10k 조합: AP 1개면 #channels <= 2): AP 채널은 기본 2.4GHz 6번.
#   wlan0와 같은 5GHz 채널은 회장 공유기가 80MHz 폭이라 실패했다 ("Failed to start AP functionality").
#   채널 바꾸기: sudo Q3_AP_CHANNEL=1 tools/ap_start.sh   (wlan0와 같은 채널: Q3_AP_CHANNEL=same)
# 되돌리기: sudo tools/ap_stop.sh
set -euo pipefail
SSID="${Q3_AP_SSID:-SquadEdge-1-1}"
PASS="${Q3_AP_PASS:-squadedge1}"
IP="${Q3_AP_IP:-192.168.4.1}"
CONN="${Q3_AP_CONN:-squadedge-ap}"
STA="${Q3_STA_IFACE:-wlan0}"
VIF="${Q3_AP_IFACE:-uap0}"
IW=$(command -v iw || echo /usr/sbin/iw)
[[ "$(id -u)" -eq 0 ]] || { echo "root 필요: sudo $0" >&2; exit 1; }
[[ ${#PASS} -ge 8 ]] || { echo "비밀번호는 8자 이상 (WPA2)" >&2; exit 1; }

nmcli connection delete "$CONN" >/dev/null 2>&1 || true

if [[ "${1:-}" == "--exclusive" ]]; then
  IFACE="$STA"; BAND=bg; CH_ARGS=()
else
  # 기본: wlan0가 2.4GHz에 붙어 있으면 같은 채널(칩이 채널을 오가지 않아 AP가 안정), 아니면 6번.
  #   (2026-10-11 실측: wlan0가 5GHz 157번 80MHz로 로밍하자 2.4GHz AP 송신이 거의 막혔다 → wlan0를 2.4GHz 11번
  #    공유기로 고정하고 AP도 11번. nmcli connection modify D4D_Hacker_03 802-11-wireless.bssid …)
  CH="${Q3_AP_CHANNEL:-auto}"
  if [[ "$CH" == "same" || "$CH" == "auto" ]]; then
    STA_CH=$($IW dev "$STA" info 2>/dev/null | awk '/channel/{print $2; exit}')
    if [[ "$CH" == "same" || ( -n "$STA_CH" && "$STA_CH" -le 14 ) ]]; then CH="${STA_CH:-6}"; else CH=6; fi
  fi
  BAND=$([[ "$CH" -gt 14 ]] && echo a || echo bg)
  CH_ARGS=(802-11-wireless.channel "$CH")
  IFACE="$VIF"
  if ! $IW dev "$VIF" info >/dev/null 2>&1; then
    $IW dev "$STA" interface add "$VIF" type __ap
    # wlan0와 다른 MAC (로컬 관리 비트 세움)
    MAC=$(cat /sys/class/net/"$STA"/address)
    NEW=$(printf '%02x' $(( 0x${MAC:0:2} | 0x02 )))${MAC:2:-2}$(printf '%02x' $(( (0x${MAC: -2} + 1) & 0xff )))
    ip link set "$VIF" address "$NEW"
  fi
  sleep 1
  echo "[ap] 회장 Wi-Fi 유지, $VIF 로 AP (채널 $CH, 대역 $BAND)"
fi

nmcli connection add type wifi ifname "$IFACE" con-name "$CONN" autoconnect no ssid "$SSID" \
  802-11-wireless.mode ap 802-11-wireless.band "$BAND" "${CH_ARGS[@]}" \
  wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$PASS" wifi-sec.proto rsn wifi-sec.pairwise ccmp wifi-sec.group ccmp \
  ipv4.method shared ipv4.addresses "$IP/24" ipv6.method disabled >/dev/null
nmcli connection up "$CONN"
echo "[ap] SSID=$SSID  보드 주소=$IP  인터페이스=$IFACE"
nmcli -t -f DEVICE,STATE,CONNECTION device | grep -E "^($STA|$VIF):" || true
echo "[ap] 다음: 보드에서  .venv/bin/python tools/cop_link.py   /  노트북은 Wi-Fi '$SSID' 연결 후 COP_Q3_HOST=$IP"
