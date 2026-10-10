import time
import unittest

from squad.protocol import Msg
from squad.report.desk import SqDesk
from squad.report.situation import Situation
from squad.report.sqrpt import FMT, Geo, ReportCounter, rule_voice, snapshot, validate
from squad.report.utterance import parse


def scene():
    sit = Situation()
    sit.set_positions([(1, -8, 2, 45), (2, 8, -2, 45), (3, 0, -4, 45)])   # 거리 v1.0.4 장면(1/5)
    return sit


class Desk(unittest.TestCase):
    def setUp(self):
        self.sit = scene()
        self.desk = SqDesk(self.sit, Geo(36.3005, 127.4185, 45), counter=ReportCounter())
        t = 1_000_000.0
        self.desk.on_events(self.sit.on_report(1, Msg.CONTACT, {"azimuth": 45, "dist_band": 2, "count": 3}, t))
        self.desk.on_events(self.sit.on_report(2, Msg.CONTACT, {"azimuth": 28, "dist_band": 2, "count": 2}, t + 5))
        self.desk.on_events(self.sit.on_report(3, Msg.CASUALTY_SELF, {"heading": 45}, t + 10))
        self.t = t + 20

    def test_flash_report(self):
        d, rb = self.desk.draft("적이 좌측으로 우회 중, 고수하겠음, 의무후송 요청", self.t)
        self.assertEqual((d["fmt"], d["priority"], d["rpt"]["id"], d["gen"]["by"]), (FMT, "flash", "1-1-0001", "rule"))
        b = d["body"]
        self.assertEqual(b["enemy"][0]["location"]["basis"], "triangulated")
        self.assertEqual(b["enemy"][0]["activity"]["code"], "FLANK_LEFT")
        self.assertEqual([a["code"] for a in b["action"]], ["HOLD"])
        self.assertEqual(b["requests"][0]["detail"], {"urgent": 1})
        self.assertEqual(d["rpt"]["kinds"], ["SPOT", "SIT", "MEDEVAC"])
        self.assertTrue(d["text"].startswith("[섬광]"))
        self.assertIn("후송: 1)52S", d["text"])
        self.assertIn("3번 부상", rb)                         # 소대장 ID 1-4 → 분대장 쪽 병사 3번

    def test_delta_and_resend(self):
        d, _ = self.desk.draft("고수하겠음", self.t)
        sent = self.desk.send(d, self.t)
        self.assertNotIn("_lines", sent)
        self.assertEqual(self.desk.due_resends(self.t + 5), [])
        self.assertEqual(len(self.desk.due_resends(self.t + 11)), 1)      # 섬광 10초 무응답 → 1회
        self.assertEqual(self.desk.due_resends(self.t + 30), [])
        d2, _ = self.desk.draft("고수하겠음, 탄약 보급 요청", self.t + 40)
        self.assertIn("조치: 변동 없음", d2["text"])
        self.assertIn("조치", d2["body"]["delta"]["unchanged"])
        self.assertEqual(d2["priority"], "urgent")                     # 새 부상 없음 + 요청 있음

    def test_ack_stops_resend(self):
        d, _ = self.desk.draft("고수하겠음", self.t)
        self.desk.send(d, self.t)
        self.desk.on_ack(d["rpt"]["id"])
        self.assertEqual(self.desk.due_resends(self.t + 20), [])


class Validate(unittest.TestCase):
    def setUp(self):
        sit = scene()
        sit.on_report(1, Msg.CONTACT, {"azimuth": 45, "dist_band": 2, "count": 3}, 0)
        self.snap = snapshot(sit, Geo(36.3, 127.4, 45), 10)

    def v(self, **kw):
        base = {"activity": [], "action": [], "requests": [], "judgment": [], "leader_count": None, "summary": "적 3명."}
        return {**base, **kw}

    def test_rejects(self):
        voice = "철수하지 않고 고수, 적 5명"
        self.assertIsNone(validate(self.v(action=[{"text": "고수", "code": "HOLD"}]), self.snap, voice))
        self.assertIn("숫자", validate(self.v(summary="적 7명 접근."), self.snap, voice))
        self.assertIn("부정", validate(self.v(action=[{"text": "철수", "code": "WITHDRAW"}]), self.snap, voice))
        self.assertIn("코드", validate(self.v(action=[{"text": "춤", "code": "DANCE"}]), self.snap, voice))
        self.assertIn("적 수", validate(self.v(leader_count=9), self.snap, voice))

    def test_rule_voice_negation(self):
        v = rule_voice(parse("적이 진지 구축 중인 것 같음, 철수하지 않고 고수, 탄약 보급 필요"))
        self.assertEqual([a["code"] for a in v["action"]], ["HOLD"])
        self.assertEqual([r["code"] for r in v["requests"]], ["RESUPPLY"])


if __name__ == "__main__":
    unittest.main()
