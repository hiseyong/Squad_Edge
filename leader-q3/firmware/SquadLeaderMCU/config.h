#pragma once
// 분대장1 (1-1) — Arduino UNO Q MCU 설정
// Wi-Fi SoftAP · BLE Central · 측위는 Linux(MPU) host/bridge_server.py + host/ble/ 가 담당한다.

#ifndef NODE_ID
#define NODE_ID "1-1"
#endif

#ifndef SQUAD_ID
#define SQUAD_ID "1"
#endif

// 데모 GPS 원점 (시나리오 ROUTE 근처). 실 GPS 붙이면 Bridge telemetry 로 교체.
#ifndef DEMO_LAT
#define DEMO_LAT 36.300500
#endif
#ifndef DEMO_LON
#define DEMO_LON 127.418500
#endif

// Bridge RPC 이름 (host/bridge_server.py 와 동일해야 함)
#define RPC_TELEMETRY "telemetry_json"
#define RPC_ORDER     "order_notify"
#define RPC_PING      "ping"
