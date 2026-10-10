"""전투 데이터 보고(전투 종료 뒤) 오프라인 시험."""
import unittest

from squad.input.keypad import CommandPad
from squad.report.battle import build, unpack
from squad.report.log import CombatLog
from squad.report.situation import Situation
from squad.report.sqrpt import Geo


class Battle(unittest.TestCase):
    def test_build_minutes_and_payload(self):
        db = CombatLog()
        db.add("soldier", 1, {"desc": "CONTACT seq=7 src=1 dst=0x80 | 적 3, 방위 60°, 2시, 원거리, heading 0", "retx": False,
                              "target": {"clock": 2, "dist": 31.6}}, ts=100.0)
        db.add("soldier", 1, {"desc": "CONTACT seq=7 src=1 dst=0x80 | 적 3", "retx": True}, ts=103.0)   # 재전송은 빼고
        db.add("contact_up", 0, {"summary": "적 3명 분대장 기준 2시 32m (발견 1-2)"}, ts=100.1)
        db.add("voice", 0, {"ptt": "report", "text": "적 3명 좌측 우회 중"}, ts=110.0)
        db.add("cmd", 0, {"from": "keypad", "text": "엄폐, 9시, 전원", "target": "all"}, ts=120.0)
        db.add("cmd", 0, {"from": "PL", "order": {"code": "HALT"}}, ts=130.0)
        db.add("leader_pos", 0, {"mgrs": "52S CF 5800 1843"}, ts=140.0)
        sit = Situation()
        sit.set_positions([(1, -10, 0, 0)])
        b = build(db.since(0), sit, Geo(36.3005, 127.4185, 0), "1", "1분대", 90.0, 150.0, "1-1-B1")
        doc = unpack(b["payload"])
        self.assertEqual(doc["fmt"], "sq-battle/0.1")
        self.assertEqual(len(doc["events"]), 7)
        m = doc["minutes"]
        self.assertEqual(len(m), 5)                                     # 재전송·위치 기록은 회의록에서 뺀다
        self.assertIn("[1-2→1-1] CONTACT 적 3, 방위 60°, 2시, 원거리, heading 0 ⇒ 분대장 기준 2시 32m", m[0])
        self.assertIn("[소대장→1-1] 지시 HALT", m[-1])
        self.assertEqual(doc["result"]["soldier_reports"], 1)
        self.assertEqual(doc["leader_track"][0]["mgrs"], "52S CF 5800 1843")
        self.assertLess(b["payload"]["bytes"], b["payload"]["raw_bytes"])
        self.assertTrue(b["text"].startswith("[전투 데이터] 1분대 1-1-B1"))

    def test_keypad_d_long_is_battle_end_only_without_command(self):
        ends, said = [], []
        pad = CommandPad(said.append, lambda d: None, on_battle_end=lambda: ends.append(1))
        pad.on_key("long", "D")
        self.assertEqual(ends, [1])
        pad.on_key("short", "9")
        pad.on_key("long", "D")                                         # 적 위치 입력 중 = 거리 순환
        self.assertEqual((ends, said[-1]), ([1], "근거리"))


if __name__ == "__main__":
    unittest.main()
