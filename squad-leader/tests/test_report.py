import math
import unittest

from squad.protocol import Msg
from squad.report.compose import NO_CHANGE, Composer, ReportDesk
from squad.report.grid import cardinal, latlon_to_mgrs, latlon_to_utm
from squad.report.situation import Situation, intersect
from squad.report.utterance import parse

ORIGIN = latlon_to_utm(37.9012, 127.0605)


def contact(sit, sid, az, band, count, ts):
    return sit.on_report(sid, Msg.CONTACT, {"azimuth": az, "clock": 0, "dist_band": band, "count": count,
                                            "heading": 0}, ts)


class Grid(unittest.TestCase):
    def test_mgrs_matches_pyproj(self):
        # 기대값의 UTM 동·북은 pyproj(WGS84)로 교차 검증한 값
        self.assertEqual(latlon_to_mgrs(37.5665, 126.9780), "52S CG 2142 5964")
        self.assertEqual(latlon_to_mgrs(38.8895, -77.0353, 10), "18S UJ 23478 06483")
        self.assertEqual(latlon_to_mgrs(-33.8568, 151.2153, 10), "56H LH 34900 52288")

    def test_offset_and_cardinal(self):
        self.assertEqual(ORIGIN.offset(100, 0).easting - ORIGIN.easting, 100)
        self.assertEqual([cardinal(a) for a in (0, 44, 46, 180, 337, 338)], ["북", "북동", "북동", "남", "북서", "북"])


class Fusion(unittest.TestCase):
    def setUp(self):
        self.sit = Situation()
        # 병사 거리 구간 v1.0.4(10·20·40m)에 맞춰 이전 장면(원거리 200m)을 1/5로 줄인 배치
        self.sit.set_positions([(1, -8, 2, 0), (2, -4, 0, 0), (3, 8, -2, 0), (4, 4, -1, 0), (5, 0, -4, 0)])

    def test_intersect(self):
        az1 = math.degrees(math.atan2(190, 190))
        az3 = math.degrees(math.atan2(110, 210))
        x, y = intersect([((-40, 10), az1), ((40, -10), az3)])
        self.assertAlmostEqual(x, 150, places=3)
        self.assertAlmostEqual(y, 200, places=3)
        self.assertIsNone(intersect([((0, 0), 0), ((10, 0), 180)]))      # 등 돌린 방위선은 무효

    def test_same_enemy_two_soldiers(self):
        self.assertEqual(contact(self.sit, 1, 45, 2, 3, 0), ["new_contact"])
        self.assertEqual(contact(self.sit, 3, 28, 2, 2, 20), [])          # 같은 적 → 새 보고 계기 아님
        tr = self.sit.tracks
        self.assertEqual((len(tr), tr[0].count, tr[0].reporters), (1, 3, [1, 3]))   # 3+2=5가 아니라 최댓값 3
        self.assertTrue(tr[0].basis.startswith("교차 추정"))
        self.assertLess(math.dist(tr[0].pos, (30, 40)), 2)

    def test_different_enemies(self):
        contact(self.sit, 1, 45, 2, 3, 0)
        self.assertEqual(contact(self.sit, 5, 225, 0, 1, 10), ["new_contact"])   # 반대 방향
        self.assertEqual(len(self.sit.tracks), 2)

    def test_trend_closer(self):
        contact(self.sit, 3, 28, 2, 2, 0)
        contact(self.sit, 3, 28, 0, 2, 60)
        self.assertEqual(self.sit.tracks[0].trend(), "접근")

    def test_friendly(self):
        self.sit.on_report(2, Msg.CASUALTY_SELF, {"heading": 0}, 0)
        self.sit.on_report(4, Msg.WEAPON_AMMO, {}, 0)
        self.assertEqual(self.sit.set_link(5, False, 0), ["link_lost"])
        self.sit.set_link(1, False, 0, silent=True)                      # 침묵 모드는 두절 아님
        f = self.sit.friendly(10)
        self.assertEqual((f["available"], f["casualties"], f["ammo_issue"], f["lost"], f["silent"]),
                         (3, [2], [4], [5], [1]))
        self.sit.on_report(4, Msg.OK_READY, {}, 20)
        self.assertEqual(self.sit.friendly(30)["ammo_issue"], [])


class Utter(unittest.TestCase):
    def test_parse(self):
        u = parse("적이 좌측으로 우회 중, 고수하겠음, 의무후송 요청")
        self.assertEqual((u.activity, u.action, u.requests), (["좌측 우회 중"], ["고수"], ["의무후송"]))
        u = parse("적 5명 2시 방향 300m 접근 중, 엄폐 후 경계 중, 박격포 지원 요청")
        self.assertEqual((u.enemy_count, u.enemy_clock, u.enemy_dist_m, u.requests),
                         (5, 2, 300, ["화력 지원(박격포)"]))
        self.assertEqual(parse("2번 부상, 의무후송 요청").casualty_ids, [2])
        self.assertEqual(parse("적이 진지 구축 중인 것 같음").judgment, ["적이 진지 구축 중인 것 같음"])


class Compose(unittest.TestCase):
    def setUp(self):
        self.sit = Situation()
        self.sit.set_positions([(1, -8, 2, 45), (3, 8, -2, 45)])
        self.desk = ReportDesk(Composer(self.sit, ORIGIN, leader_heading=45))

    def test_flash_and_readback(self):
        d = self.desk.on_events(contact(self.sit, 1, 45, 2, 3, 0), 0)
        self.assertEqual(d.prec, "FLASH")
        r = self.desk.with_voice(parse("고수하겠음"), 5)
        self.assertIn("적 3명", r.summary)
        self.assertTrue(r.readback.startswith("섬광. 적 3명, 12시 방향"))
        self.assertTrue(r.readback.endswith("송신할까요?"))
        self.assertIn("52S", r.sections["적"])

    def test_prompts(self):
        self.desk.on_events(self.sit.on_report(1, Msg.CASUALTY_SELF, {"heading": 0}, 0), 0)
        r = self.desk.with_voice(parse(""), 1)
        self.assertEqual(r.prompts, ["현재 조치?", "의무후송 요청?"])

    def test_delta_after_sent(self):
        self.desk.on_events(contact(self.sit, 1, 45, 2, 3, 0), 0)
        self.desk.with_voice(parse("고수하겠음"), 5)
        self.desk.confirm()
        r = self.desk.with_voice(parse("고수하겠음, 탄약 보급 요청"), 30)
        self.assertEqual(r.sections["조치"], NO_CHANGE)
        self.assertEqual(r.sections["요청"], "재보급(탄약)")
        self.assertIn("고수", r.summary)                 # 요지는 항상 전체


if __name__ == "__main__":
    unittest.main()
