"""분대장 ↔ 병사(분대원) BLE 링크.

기준: 병사 팀 레퍼런스 v1.1 (`~/work/soldier-node_ref_v1.1/docs/squad_ble_protocol_v1.md`, golden_vectors.json)
      + 병사 팀 안내문 `docs/soldier_team_reply_2026-10-11.md`.
이 패키지는 소대장 링크(`squad/link/`)와 서로 import하지 않는다(독립). 두 링크는 앱 계층에서만 잇는다.
레퍼런스는 런타임에 import하지 않는다(레퍼런스 폴더가 없어도 동작해야 함).
"""
