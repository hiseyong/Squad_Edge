import asyncio
import json
import unittest

from squad.link import cop
from squad.link.cop import CopServer, Telemetry, telemetry_events


class Separation(unittest.TestCase):
    """소대장 링크는 병사 프로토콜·통신을 모른다(2026-10-11 분리 원칙)."""

    def test_no_soldier_coupling(self):
        src = open(cop.__file__, encoding="utf-8").read()
        for word in ("squad.protocol", "..protocol", "squad.soldier", "..soldier", "dist_band", "cmd_code"):
            self.assertNotIn(word, src)
        for name in ("order_to_frames", "soldier_report_events", "ble_to_cop", "DIST_M"):
            self.assertFalse(hasattr(cop, name), name)

    def test_telemetry_members_relayed_by_leader(self):
        evs = telemetry_events("1", Telemetry(36.3, 127.4, members={1: (-9, -8, 45), 3: (5, -7, 45, 4.0)}))
        self.assertEqual([e["type"] for e in evs], ["unit.position", "unit.relpos", "unit.relpos"])
        self.assertEqual([(e["src"], e["data"]["id"], e["data"]["ref"]) for e in evs[1:]],
                         [("1-1", "1-2", "1-1"), ("1-1", "1-4", "1-1")])      # 분대장(1-1)이 보내는 분대원 위치
        self.assertEqual(telemetry_events("1", Telemetry(36.3, 127.4))[0]["type"], "unit.position")


class Server(unittest.TestCase):
    def test_tcp_roundtrip(self):
        async def run():
            orders, missions = [], []
            srv = CopServer("1", "127.0.0.1", 0, 0.05, telemetry=lambda: Telemetry(36.3, 127.4),
                            on_order=orders.append, on_mission=missions.append)
            await srv.start()
            port = srv.server.sockets[0].getsockname()[1]
            r, w = await asyncio.open_connection("127.0.0.1", port)
            hello = json.loads(await r.readline())
            for m in ({"type": "order.new", "data": {"id": "o1", "code": "HALT", "recipients": ["1-2"]}},
                      {"type": "mission.update", "data": {"id": "m1", "emcon": True}}):
                w.write((json.dumps(m) + "\n").encode())
            await w.drain()
            got = []
            while len([e for e in got if e["type"] == "ack"]) < 2:
                got.append(json.loads(await asyncio.wait_for(r.readline(), 3)))
            w.close()
            await srv.close()
            return hello, got, orders, missions

        hello, got, orders, missions = asyncio.run(run())
        self.assertEqual(hello["type"], "router.hello")
        self.assertEqual(hello["data"]["hw_relpos"], ["1-2", "1-3", "1-4"])
        self.assertEqual({e["type"] for e in got} - {"ack"}, {"unit.position"})
        acks = [e["data"] for e in got if e["type"] == "ack"]
        self.assertEqual([(a["ref"], a["from"], a["ok"]) for a in acks], [("o1", "1-1", True), ("m1", "1-1", True)])
        self.assertEqual(([o["id"] for o in orders], [m["id"] for m in missions]), (["o1"], ["m1"]))   # 분대장 알림만


if __name__ == "__main__":
    unittest.main()


class Motion(unittest.TestCase):
    def test_moves_and_stays_in_formation(self):
        import math
        from squad.link.motion import SquadMotion
        m = SquadMotion(36.3, 127.4, 45, seed=1)
        a = m.member_offsets()
        for _ in range(30):
            m.step(1.0)
        b = m.member_offsets()
        self.assertGreater(math.hypot(m.x, m.y), 15)                 # 30초 이동 (0.8m/s)
        self.assertNotEqual(a[1][:2], b[1][:2])                      # 분대원 위치가 변한다
        for sid, (x, y, _, err) in b.items():
            self.assertLess(math.hypot(x, y), 35)                    # 대형에서 크게 벗어나지 않음
            self.assertTrue(3.5 <= err <= 6.0)
        for _ in range(35):                                          # 65초: 정지 구간 (60~80초)
            m.step(1.0)
        x0 = m.x
        m.step(1.0)
        self.assertEqual(m.x, x0)


class Contact(unittest.TestCase):
    def test_contact_event_from_leader(self):
        from squad.link.cop import contact_event
        e = contact_event("1", "1-2", {"bearing": 51, "dist": 31.6, "err": 20, "dx": 24.6, "dy": 20.0,
                                       "mgrs": "52S CF 1 2", "basis": "pos_table"}, 3, 10.0, seq=7)
        d = e["data"]
        self.assertEqual((e["src"], d["type"], d["sender"], d["observer"], d["priority"]), ("1-1", "CONTACT", "1-1", "1-2", "urgent"))
        self.assertEqual(d["fields"]["location"]["bearing"], 51)
        self.assertEqual(d["summary"], "적 3명 분대장 기준 2시 32m (발견 1-2)")
