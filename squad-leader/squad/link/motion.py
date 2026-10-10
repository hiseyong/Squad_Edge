"""시연용 분대 이동 모델 (GPS·BLE 측위 연동 전): 분대장 위치·방위와 분대원 상대 위치를 그럴듯하게 움직인다.

- 분대장: 정면 방향으로 0.8m/s 이동 MOVE_S초 → HALT_S초 정지 반복. 방위는 천천히 흔들림, GPS 잡음 ±1.5m.
- 분대원: 대형(분대장 기준 오른쪽·앞 m)을 정면 방향에 맞춰 회전해 따라간다.
  각자 1차 자기회귀 랜덤워크(최대 ±4m) + 느린 흔들림, 개인 방위 ±15도, 측위 오차 3.5~6m.
실제 GPS(MCU)·BLE 측위가 붙으면 이 모델 대신 측정값을 쓴다.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

R_EARTH = 6_371_000.0
# 쐐기 대형: 분대장 기준 (오른쪽 m, 앞 m)
WEDGE = {1: (-12.0, -1.0), 2: (12.0, -1.0), 3: (-24.0, -12.0), 4: (24.0, -12.0), 5: (0.0, -18.0)}


@dataclass
class SquadMotion:
    lat0: float
    lon0: float
    heading0: float = 45.0
    speed: float = 0.8
    move_s: float = 60.0
    halt_s: float = 20.0
    members: tuple[int, ...] = (1, 2, 3)
    seed: int | None = None
    x: float = 0.0            # 분대장 이동량 (원점 대비 동·북 m)
    y: float = 0.0
    t: float = 0.0
    _walk: dict = field(default_factory=dict)
    _phase: dict = field(default_factory=dict)

    def __post_init__(self):
        self.rng = random.Random(self.seed)
        for sid in self.members:
            self._walk[sid] = [0.0, 0.0]
            self._phase[sid] = self.rng.uniform(0, 2 * math.pi)

    def heading(self) -> float:
        return (self.heading0 + 12 * math.sin(self.t / 40) + 4 * math.sin(self.t / 9)) % 360

    def moving(self) -> bool:
        return self.t % (self.move_s + self.halt_s) < self.move_s

    def step(self, dt: float) -> None:
        self.t += dt
        if self.moving():
            h = math.radians(self.heading())
            self.x += self.speed * dt * math.sin(h)
            self.y += self.speed * dt * math.cos(h)
        for sid, w in self._walk.items():          # 랜덤워크: 평균으로 되돌아오는 힘 + 잡음
            for k in (0, 1):
                w[k] = max(-4.0, min(4.0, 0.97 * w[k] + self.rng.gauss(0, 0.35 if self.moving() else 0.12)))

    def leader(self) -> tuple[float, float, float, float]:
        """(위도, 경도, 방위, 위치 오차 m) — GPS 잡음 포함."""
        nx, ny = self.rng.gauss(0, 0.8), self.rng.gauss(0, 0.8)
        lat = self.lat0 + math.degrees((self.y + ny) / R_EARTH)
        lon = self.lon0 + math.degrees((self.x + nx) / (R_EARTH * math.cos(math.radians(self.lat0))))
        return lat, lon, round(self.heading(), 1), round(self.rng.uniform(2.0, 4.5), 1)

    def member_offsets(self) -> dict[int, tuple[float, float, float, float]]:
        """병사 id → (동 m, 북 m, 방위, 오차 m), 분대장 기준."""
        h = math.radians(self.heading())
        out = {}
        for sid in self.members:
            right, fwd = WEDGE[sid]
            ex = right * math.cos(h) + fwd * math.sin(h)            # 정면 방향으로 대형 회전
            ny = -right * math.sin(h) + fwd * math.cos(h)
            sway = 1.2 * math.sin(self.t / 7 + self._phase[sid])
            w = self._walk[sid]
            hd = (self.heading() + self.rng.gauss(0, 8) + 10 * math.sin(self.t / 11 + self._phase[sid])) % 360
            out[sid] = (round(ex + w[0] + sway * math.cos(h), 1), round(ny + w[1] - sway * math.sin(h), 1),
                        round(hd), round(self.rng.uniform(3.5, 6.0), 1))
        return out
