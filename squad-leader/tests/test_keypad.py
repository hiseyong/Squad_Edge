"""키패드 판정·명령 조립 오프라인 시험 (MCU·BLE 없음)."""
import unittest

from squad.input.keypad import CommandPad, KeyTimer
from squad.soldier import codec as fc


class Timer(unittest.TestCase):
    def test_short_long_ptt(self):
        got = []
        kt = KeyTimer(lambda k, key: got.append((k, key)))
        kt.feed("2", True, 0.0)
        kt.feed("2", False, 0.2)
        kt.feed("9", True, 1.0)
        kt.tick(1.5)
        kt.tick(2.1)                           # 1초 넘는 순간 한 번
        kt.tick(2.5)
        kt.feed("9", False, 3.0)               # 뗄 때는 아무것도 안 냄
        kt.feed("A", True, 4.0)
        kt.feed("A", False, 6.0)
        self.assertEqual(got, [("short", "2"), ("long", "9"), ("ptt_down", "A"), ("ptt_up", "A")])


class Pad(unittest.TestCase):
    def setUp(self):
        self.now = [0.0]
        self.said, self.sent, self.ptt, self.replays = [], [], [], []
        self.pad = CommandPad(self.said.append, self.sent.append, on_ptt=lambda k, d: self.ptt.append((k, d)),
                              on_replay=lambda: self.replays.append(1), targets=(1, 2), clock_fn=lambda: self.now[0])

    def keys(self, *seq):
        for k in seq:
            kind, key = ("long", k[0]) if k.endswith("L") and len(k) == 2 else ("short", k)
            self.pad.on_key(kind, key)
            self.now[0] += 0.3

    def frame(self, d, seq=5):
        dst = fc.DST_ALL_SOLDIERS if d["target"] == "all" else fc.dst_mask([int(d["target"])])
        return fc.to_hex(fc.encode(dict(type=fc.CMD_BUTTON, seq=seq, src=0, dst=dst, cmd_code=d["cmd_code"],
                                        azimuth=d["azimuth"], dist_band=d["dist_band"], extra=d["extra"],
                                        priority=d["priority"])))

    def test_cover_9_all(self):
        self.keys("2", "9L", "#")
        self.assertEqual(self.frame(self.sent[0]), "01 10 05 00 1F 06 02 0E 01 FF 00 01")   # 안내문 §5 예
        self.assertEqual(self.said[-1], "엄폐, 9시, 전원, 송신")

    def test_enemy_info_s2(self):
        self.keys("D", "D", "9", "9", "9", "9", "2L", "DL", "DL", "DL", "#")
        self.assertEqual(self.frame(self.sent[0]), "01 10 05 00 02 06 09 3C 00 02 03 00")   # 안내문 §5 예
        self.assertEqual(self.said[-1], "적 위치, 적 3명, 2시, 원거리, 2번, 송신")

    def test_digit_after_enemy_info_is_new_command(self):
        self.keys("9", "2")                       # 적 위치 다음 2 = 엄폐(적 수가 아님)
        self.assertEqual(self.said, ["적 위치", "엄폐"])
        self.keys("9", "9", "9", "9", "9", "9", "9")   # 미상→1→2→3→4→다수→미상
        self.assertEqual(self.said[-6:], ["적 1명", "적 2명", "적 3명", "적 4명", "적 다수", "적 수 미상"])

    def test_required_direction(self):
        self.keys("8", "#")
        self.assertEqual((self.sent, self.said[-1]), ([], "경계, 방향 필요"))

    def test_tens_clock(self):
        self.keys("4", "1L", "1", "#")
        self.assertEqual((self.sent[0]["azimuth"], self.said[-1]), (330, "후퇴, 11시, 전원, 송신"))
        self.now[0] += 5
        self.keys("4", "1L")
        self.now[0] += 2                       # 1.5초 지나면 1시로 확정, 이후 1 = 새 명령(정지)
        self.keys("1")
        self.assertEqual(self.said[-1], "정지")

    def test_rally_never_direction_and_specials(self):
        self.keys("5", "3L", "#", "*L", "#", "#L", "#")
        self.assertEqual([(d["cmd_code"], d["azimuth"], d["priority"]) for d in self.sent],
                         [(0x05, 0xFFFF, 0), (0x0A, 0xFFFF, 0), (0x0B, 0xFFFF, 1)])

    def test_cancel_and_replay_and_ptt(self):
        self.keys("6", "*", "#")
        self.assertEqual((self.sent, self.said[1], self.replays), ([], "입력 취소", [1]))
        self.pad.on_key("ptt_down", "C")
        self.pad.on_key("ptt_up", "C")
        self.assertEqual(self.ptt, [("voice_cmd", True), ("voice_cmd", False)])

    def test_target_cycle(self):
        self.keys("D", "D", "D")
        self.assertEqual(self.said, ["1번", "2번", "전원"])


if __name__ == "__main__":
    unittest.main()
