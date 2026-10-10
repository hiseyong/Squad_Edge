#!/usr/bin/env python3
"""팀원용 이벤트 송신 예제 (표준 라이브러리만 사용).

    python3 tools/send_event.py salute       # 음성 AI → SALUTE 보고 예시
    python3 tools/send_event.py relpos       # BLE 상대측위 결과 예시
    python3 tools/send_event.py sensor S-1   # 무인센서 감지
    python3 tools/send_event.py udp          # UDP로 보내기 예시

HTTP: POST http://<소대장 노트북>:8000/api/ingest
UDP : <소대장 노트북>:5005 (한 줄당 JSON 하나)
"""
import json
import socket
import sys
import urllib.request

HOST = "localhost"

EXAMPLES = {
    "salute": {"type": "report.new", "data": {
        "type": "SALUTE", "sender": "2-1", "priority": "priority", "conf": 0.82,
        "raw_text": "2분대장 보고, 적 2명 11시 방향 100미터 수풀 속 관측 중",
        "summary": "적 2명 · 2분대 11시 100m · 관측 중",
        "fields": {"size": 2, "activity": "관측", "unit": "적 관측조", "time": "현재", "equipment": "쌍안경",
                   "kind": "infantry", "location": {"bearing": 330, "dist": 100, "err": 25}}}},
    "relpos": {"type": "unit.relpos", "data": {"id": "1-2", "ref": "1-1", "dx": -6.2, "dy": -9.8, "err": 4.5}, "bytes": 14},
    "status": {"type": "unit.status", "data": {"id": "3-2", "status": "wia"}},
    "link": {"type": "link.update", "data": {"a": "1-1", "b": "1-2", "rssi": -68}},
}


def post(ev):
    req = urllib.request.Request(f"http://{HOST}:8000/api/ingest", data=json.dumps(ev).encode(),
                                 headers={"Content-Type": "application/json"})
    print(urllib.request.urlopen(req).read().decode())


if __name__ == "__main__":
    kind = sys.argv[1] if len(sys.argv) > 1 else "salute"
    if kind == "sensor":
        post({"type": "sensor.trigger", "data": {"id": sys.argv[2] if len(sys.argv) > 2 else "S-1"}})
    elif kind == "udp":
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(
            json.dumps(EXAMPLES["status"]).encode(), (HOST, 5005))
        print("sent via UDP")
    else:
        post(EXAMPLES[kind])
