"""병사 링크 설정 상수. 현장에서 바꿀 값은 여기서만 바꾼다.

출처: 프로토콜 v1.1 부록 C, `tools/mock_leader.py`, 병사 팀 안내문(2026-10-11) D5·D7.
"""
from __future__ import annotations

# 경로손실 모델 d = 10^((P1m − RSSI) / (10·n)) — 2026-10-11 현장 잠정 보정(nRF 대 nRF). 레퍼런스 함수 기본 인자(−59/2.0)는 옛 값이라 쓰지 않는다.
PATHLOSS_P1M_DBM = -65.5
PATHLOSS_N = 1.6

# 거리 구간 대표값(v1.0.4 시연용), 내 기준 구간 경계, 거리 없음일 때 계산값
DIST_REP_M = {0: 10.0, 1: 20.0, 2: 40.0}
DIST_NONE_M = 20.0
BAND_EDGES_M = (15.0, 30.0)

# 분대장 방위: 0(북쪽) 고정(D5). 병사도 heading 0 고정.
LEADER_HEADING = 0

# 위치 정렬: 분대장이 본 병사 방향(시계, 분대장 총구 = 북쪽). S1 왼쪽 앞 10시, S2 오른쪽 앞 2시
DEFAULT_CLOCKS = {1: 10, 2: 2}
FORMATION_SPACING_M = 10.0

# 시간 (초)
CMD_ACK_TIMEOUT_S = 15.0      # 버튼 명령 ACK 대기 → 같은 바이트로 1회 재전송 → 미수신
REPORT_DEDUP_S = 60.0         # 병사 보고 재전송 판정 창(병사·seq·바이트 동일)
RANGING_STALE_S = 30.0        # 이보다 오래된 RANGING은 위치 계산에 쓰지 않음
VOICE_CHUNK_GAP_S = 0.015     # 음성 청크 사이 간격
VOICE_MAX_S = 10.0            # 음성 최대 길이(40,000B)

RSSI_WINDOW = 15              # RSSI 이동 중앙값 창(펌웨어와 같게)
