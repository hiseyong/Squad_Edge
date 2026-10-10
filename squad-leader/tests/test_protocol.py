import math
import unittest

from squad import adpcm
from squad.protocol import (
    Cmd, Frame, FrameError, Msg, AZ_NONE, DST_ALL_SOLDIERS, RESERVED,
    adv_manufacturer_data, azimuth_to_clock, build_report, clock_to_azimuth, cmd_button, emcon_set,
    parse_cmd_button, parse_report, req_stats, rpt_ack, soldier_bit, voice_chunk_size,
)


def h(s: str) -> bytes:
    return bytes.fromhex(s)


class SpecVectors(unittest.TestCase):
    """명세 §11.1 hex와 바이트 단위 일치."""

    def test_take_cover_all(self):
        f = cmd_button(5, DST_ALL_SOLDIERS, Cmd.TAKE_COVER, azimuth=270, priority=1)
        self.assertEqual(f.encode(), h("01 10 05 00 1F 06 02 0E 01 FF 00 01"))

    def test_enemy_info_soldier1(self):
        f = cmd_button(6, soldier_bit(1), Cmd.ENEMY_INFO, azimuth=45, dist_band=2, extra=3)
        self.assertEqual(f.encode(), h("01 10 06 00 01 06 09 2D 00 02 03 00"))

    def test_req_stats(self):
        self.assertEqual(req_stats(7, soldier_bit(1)).encode(), h("01 1F 07 00 01 00"))

    def test_contact_report_decode(self):
        # v1.0.1 정정: 시계 2, 내 방위 0 → azimuth 60(0x3C)
        f = Frame.decode(h("01 01 07 01 80 07 3C 00 02 02 03 00 00"))
        self.assertEqual((f.msg_type, f.seq, f.src_id), (Msg.CONTACT, 7, 1))
        self.assertTrue(f.is_for(0))
        self.assertEqual(parse_report(f), {"azimuth": 60, "clock": 2, "dist_band": 2,
                                           "count": 3, "heading": 0})
        self.assertEqual(clock_to_azimuth(0, 2), 60)

    def test_contact_report_build(self):
        f = build_report(Msg.CONTACT, 7, 1, azimuth=60, clock=2, dist_band=2, count=3, heading=0)
        self.assertEqual(f.encode(), h("01 01 07 01 80 07 3C 00 02 02 03 00 00"))

    def test_reserved_messages(self):
        r = parse_report(Frame(Msg.RANGING, 1, 2, 0x80, bytes([2, 1, 0xC4, 10, 3, 0xBA, 8])))
        self.assertEqual(r["peers"], [{"peer_id": 1, "rssi_avg": -60, "samples": 10},
                                      {"peer_id": 3, "rssi_avg": -70, "samples": 8}])
        self.assertEqual(parse_report(Frame(Msg.LOG, 1, 2, 0x80, b"boot ok"))["text"], "boot ok")
        self.assertEqual(parse_report(Frame(Msg.BEACON, 1, 2, 0xFF, h("5A 00")))["heading"], 90)
        self.assertIn(Msg.RANGING, RESERVED)


class FrameRules(unittest.TestCase):
    def test_bad_ver(self):
        with self.assertRaises(FrameError):
            Frame.decode(h("02 05 00 01 80 00"))

    def test_len_mismatch(self):
        with self.assertRaises(FrameError):
            Frame.decode(h("01 05 00 01 80 01"))

    def test_report_size_mismatch(self):
        with self.assertRaises(FrameError):
            parse_report(Frame(Msg.CONTACT, 0, 1, 0x80, b"\x00"))

    def test_dst_mask(self):
        f = Frame(Msg.CMD_BUTTON, 0, 0, soldier_bit(3), b"")
        self.assertTrue(f.is_for(3))
        self.assertFalse(f.is_for(2))
        self.assertFalse(f.is_for(0))

    def test_cmd_roundtrip(self):
        f = cmd_button(1, 0x1F, Cmd.HALT)
        self.assertEqual(parse_cmd_button(Frame.decode(f.encode()))["azimuth"], AZ_NONE)

    def test_silent_adv_fits(self):
        # Flags(3) + MSD(len1 type1 company2 + frame) <= 31
        self.assertLessEqual(3 + 4 + len(cmd_button(0, 0x1F, Cmd.HALT).encode()), 31)

    def test_silent_adv_allowed_frames(self):
        # v1.0.2 §3.2: CMD_BUTTON(12바이트)과 EMCON_SET(7바이트)만 방송 가능
        self.assertEqual(len(adv_manufacturer_data(cmd_button(0, 0x1F, Cmd.HALT))), 12)
        self.assertEqual(adv_manufacturer_data(emcon_set(1, 0x1F, 2)), h("01 16 01 00 1F 01 02"))
        with self.assertRaises(FrameError):
            adv_manufacturer_data(rpt_ack(2, 1, 7))

    def test_chunk_size(self):
        self.assertEqual(voice_chunk_size(247), 235)
        self.assertEqual(voice_chunk_size(23), 11)


class Direction(unittest.TestCase):
    def test_clock_to_azimuth(self):
        self.assertEqual(clock_to_azimuth(0, 2), 60)
        self.assertEqual(clock_to_azimuth(90, 9), 0)
        self.assertEqual(clock_to_azimuth(0, 0), AZ_NONE)

    def test_azimuth_to_clock(self):
        self.assertEqual(azimuth_to_clock(270, 0), 9)
        self.assertEqual(azimuth_to_clock(0, 0), 12)
        self.assertEqual(azimuth_to_clock(355, 0), 12)
        self.assertEqual(azimuth_to_clock(AZ_NONE, 0), 0)

    def test_azimuth_to_clock_half_rounds_up(self):
        # v1.0.1: .5 경계는 올림 (round()의 짝수 반올림 금지)
        for az, want in [(15, 1), (45, 2), (75, 3), (14, 12), (344, 11), (345, 12), (165, 6), (195, 7)]:
            with self.subTest(az=az):
                self.assertEqual(azimuth_to_clock(az, 0), want)
        self.assertEqual(azimuth_to_clock(100, 85), 1)  # rel 15

    def test_roundtrip(self):
        for heading in range(0, 360, 17):
            for clock in range(1, 13):
                self.assertEqual(azimuth_to_clock(clock_to_azimuth(heading, clock), heading), clock)


class Adpcm(unittest.TestCase):
    def test_crc_check_value(self):
        self.assertEqual(adpcm.crc16_ccitt_false(b"123456789"), 0x29B1)

    def test_roundtrip_error_small(self):
        sig = [round(8000 * math.sin(2 * math.pi * 440 * i / 8000)) for i in range(8000)]
        dec = adpcm.decode(adpcm.encode(sig), len(sig))
        self.assertEqual(len(dec), len(sig))
        # 초기 수렴 구간 이후 오차가 작아야 한다
        self.assertLess(max(abs(a - b) for a, b in zip(sig[200:], dec[200:])), 800)

    def test_nibble_order(self):
        # 첫 샘플이 하위 니블
        self.assertEqual(adpcm.encode([1000, 0]) [0] & 0x0F, 0x07)

    def test_odd_length(self):
        self.assertEqual(len(adpcm.encode([0, 0, 0])), 2)


if __name__ == "__main__":
    unittest.main()
