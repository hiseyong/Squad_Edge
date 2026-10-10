"""병사 링크 코어 ↔ 레퍼런스 골든 벡터(바이트·값 단위 동일성). S1 통과 기준.

골든 벡터: ~/work/soldier-node_ref_v1.1/docs/golden_vectors.json (환경변수 SOLDIER_REF로 레퍼런스 경로 변경 가능)
레퍼런스 폴더가 없으면 건너뛴다(앱 자체는 레퍼런스 없이 동작). 레퍼런스는 읽기만 한다.
"""
import json
import math
import os
import random
import sys
import unittest
from pathlib import Path

from squad.soldier import codec as fc
from squad.soldier import config, geo, localize
from squad.soldier.adpcm import crc16, decode, encode
from squad.soldier.dedup import ReportDedup
from squad.soldier.seq import LeaderSeq
from squad.soldier.voice import VoiceClip, chunk_size, load_wav_8k, voice_frames

REF = Path(os.environ.get("SOLDIER_REF", Path.home() / "work" / "soldier-node_ref_v1.1"))
GOLDEN = REF / "docs" / "golden_vectors.json"
G = json.loads(GOLDEN.read_text(encoding="utf-8")) if GOLDEN.exists() else None
HEXFIELDS = ("data", "orig_payload")


def hb(s):
    return bytes.fromhex(s.replace(" ", ""))


def golden_fields(f):
    return {k: hb(v) if k in HEXFIELDS else v for k, v in f.items()}


@unittest.skipIf(G is None, f"골든 벡터 없음: {GOLDEN}")
class Golden(unittest.TestCase):
    def test_version_and_bands(self):
        self.assertEqual(G["protocol_version"], "1.1")
        d = G["dist_band_m"]
        self.assertEqual({0: d["0"], 1: d["1"], 2: d["2"]}, config.DIST_REP_M)
        self.assertEqual(d["none(0xFF)"], config.DIST_NONE_M)
        self.assertEqual(tuple(d["edges_m"]), config.BAND_EDGES_M)

    def test_frames(self):
        self.assertEqual(len(G["frames"]), 50)
        for f in G["frames"]:
            with self.subTest(f["name"]):
                raw = hb(f["frame_hex"])
                want = golden_fields(f["fields"])
                self.assertEqual(fc.encode(want), raw)                       # fields → hex
                got = fc.decode(raw)                                          # hex → fields
                self.assertEqual({k: got[k] for k in want}, want)
                if f["type_name"] == "PEER_REPORT" and "orig_seq" not in want:
                    self.assertIsNone(got["orig_seq"])                        # v1.0 형식(끝 바이트 없음)
                self.assertEqual(fc.to_hex(raw[:6]), f["header_hex"])
                self.assertEqual(len(raw), f["frame_len"])

    def test_advertising(self):
        self.assertEqual(len(G["advertising"]), 5)
        for a in G["advertising"]:
            with self.subTest(a["name"]):
                frame, ad = hb(a["frame_hex"]), hb(a["ad_data_hex"])
                self.assertEqual(fc.adv_data(frame), ad)
                self.assertEqual(len(ad), a["ad_len"])
                self.assertEqual(fc.parse_adv(ad), frame)
                if "fields" in a:
                    want = golden_fields(a["fields"])
                    got = fc.decode(frame)
                    self.assertEqual({k: got[k] for k in want}, want)

    def test_crc16(self):
        for c in G["crc16_ccitt_false"]:
            self.assertEqual(crc16(hb(c["input_hex"])), int(c["crc16"], 16))

    def test_adpcm_small(self):
        c = G["adpcm"]["small"]
        data, (p, i) = encode(c["input_samples"], c["predictor"], c["step_index"])
        self.assertEqual(data, hb(c["encoded_hex"]))
        self.assertEqual((p, i), (c["end_state"]["predictor"], c["end_state"]["step_index"]))
        dec, _ = decode(data, len(c["input_samples"]), c["predictor"], c["step_index"])
        self.assertEqual(dec, c["decoded_samples"])

    def test_adpcm_sine(self):
        c = G["adpcm"]["sine_440"]
        sine = [geo.round_half_away(8000 * math.sin(2 * math.pi * 440 * i / 8000)) for i in range(8000)]
        data, _ = encode(sine, 0, 0)
        self.assertEqual(len(data), c["len"])
        self.assertEqual(data[:16], hb(c["first16_hex"]))
        self.assertEqual(crc16(data), int(c["crc16"], 16))
        dec, _ = decode(data[:16], 32, 0, 0)
        self.assertEqual(dec, c["decode_first16_to_32_samples"])

    def test_clock_from_azimuth(self):
        for c in G["clock_from_azimuth"]["cases"]:
            self.assertEqual(geo.clock_from_azimuth(c["azimuth"], c["my_heading"]), c["clock"], c)

    def test_azimuth_from_clock(self):
        for c in G["azimuth_from_clock"]["cases"]:
            self.assertEqual(geo.azimuth_from_clock(c["clock"], c["my_heading"]), c["azimuth"], c)

    def test_peer_to_me(self):
        for c in G["peer_to_me"]["cases"]:
            with self.subTest(c["label"]):
                rep = (c["reporter_dm"][0] / 10, c["reporter_dm"][1] / 10)
                me = (c["me_dm"][0] / 10, c["me_dm"][1] / 10)
                clock, band, b, r = geo.peer_to_me(rep, c["azimuth"], c["dist_band"], me, c["my_heading"])
                self.assertEqual((clock, band, b, round(r, 2)), (c["clock"], c["my_dist_band"], c["bearing"], c["range_m"]))

    def test_pathloss(self):
        for c in G["pathloss"]["cases"]:
            self.assertAlmostEqual(geo.rssi_to_m(c["rssi"], c["p1m"], c["n"]), c["distance_m"], delta=6e-5)
        self.assertEqual((config.PATHLOSS_P1M_DBM, config.PATHLOSS_N), (-65.5, 1.6))
        self.assertAlmostEqual(geo.rssi_to_m(-68), 1.433, delta=6e-4)          # 기본값 = 현장 보정값

    def test_rssi_median(self):
        for c in G["rssi_median"]["cases"]:
            self.assertEqual(geo.rssi_median(c["rssi"]), c["median"], c)

    def test_localize(self):
        for c in G["localize"]["cases"]:
            with self.subTest(c["label"]):
                meas = {tuple(int(x) for x in k.split("-")): v for k, v in c["measured_m"].items()}
                clocks = {int(k): v for k, v in c["clocks"].items()}
                pos, info = localize.localize(c["ids"], meas, c["formation_for_missing_pairs"], clocks=clocks)
                for k, (x, y) in c["positions_m"].items():
                    self.assertAlmostEqual(pos[int(k)][0], x, delta=6e-4)
                    self.assertAlmostEqual(pos[int(k)][1], y, delta=6e-4)
                entries = localize.to_pos_table(pos)
                self.assertEqual(entries, c["pos_table_entries"])
                raw = fc.encode(dict(type=fc.POS_TABLE, seq=0, src=0, dst=0x1F, entries=entries))
                self.assertEqual(fc.to_hex(raw), c["pos_table_frame_hex"])


class Rules(unittest.TestCase):
    """골든 벡터에 없는 경계(병사 팀 안내문 P1·P2·f-4)."""

    def test_round_half_away(self):
        self.assertEqual([geo.round_half_away(v) for v in (2.5, -2.5, 0.5, -0.5, 1.49, -1.51)], [3, -3, 1, -1, 1, -2])
        self.assertEqual(geo.m_to_dm(0.25), 3)          # round()라면 2
        self.assertEqual(geo.m_to_dm(-0.25), -3)
        self.assertEqual(geo.m_to_dm(-9999), -32767)    # −32768(위치 모름)과 겹치지 않게

    def test_bearing_half(self):
        # atan2가 정확히 x.5°가 되는 경우는 드물다 → 반올림 함수만 확인하고, 방위 계산이 그 함수를 쓰는지 본다
        b, _ = geo.bearing_range((0, 0), (math.sin(math.radians(22.5)), math.cos(math.radians(22.5))))
        self.assertEqual(b, 23)                           # round(22.5) = 22(짝수 쪽)였을 값

    def test_clock_edges(self):
        self.assertEqual([geo.clock_from_azimuth(a) for a in (0, 14, 15, 344, 345, 359)], [12, 12, 1, 11, 12, 12])
        self.assertEqual(geo.clock_from_azimuth(0xFFFF), 0)
        self.assertEqual(geo.clock_from_azimuth(90, 0xFFFF), 3)   # heading 없음 → 0으로 간주
        self.assertEqual([geo.azimuth_from_clock(c) for c in (12, 9, 2)], [0, 270, 60])   # 분대장 heading 0 고정

    def test_seq(self):
        s = LeaderSeq(254)
        self.assertEqual([s.next() for _ in range(3)], [254, 255, 0])
        self.assertTrue(0 <= LeaderSeq().value <= 255)

    def test_dedup(self):
        d = ReportDedup()
        a = hb("01 05 07 01 80 00")                     # S1 OK_READY seq 7
        self.assertFalse(d.is_retransmit(1, a, 0))
        self.assertTrue(d.is_retransmit(1, a, 3))        # 같은 seq·같은 바이트 → 재전송
        self.assertFalse(d.is_retransmit(2, a, 3))       # 다른 병사
        b = hb("01 06 07 01 80 00")                     # 같은 seq 다른 내용(병사 재부팅) → 새 보고
        self.assertFalse(d.is_retransmit(1, b, 4))
        self.assertFalse(d.is_retransmit(1, b, 70))      # 60초 지남
        d.reset(1)
        self.assertFalse(d.is_retransmit(1, b, 71))      # 새 연결 → 기록 비움

    def test_voice_frames(self):
        clip = VoiceClip.from_pcm8k(9, [0, 1000, 2000, 4000, 8000] * 200, priority=1)
        seq = LeaderSeq(10)
        frames = voice_frames(clip, 247, 0x03, seq.next)
        self.assertEqual(chunk_size(247), 235)
        self.assertEqual([r for _, r in frames], [True] + [False] * 3 + [True])   # 500B → 235+235+30
        begin, end = fc.decode(frames[0][0]), fc.decode(frames[-1][0])
        self.assertEqual((begin["total_samples"], begin["total_chunks"], begin["priority"], begin["seq"]), (1000, 3, 1, 10))
        self.assertEqual(end["crc16"], crc16(clip.data))
        self.assertEqual(b"".join(fc.decode(f)["data"] for f, _ in frames[1:-1]), clip.data)
        self.assertTrue(all(len(f) <= 244 for f, _ in frames))
        self.assertEqual(chunk_size(23), 11)             # MTU 확보 실패 시


@unittest.skipIf(not (REF / "tools").exists(), "레퍼런스 도구 없음")
class CrossCheck(unittest.TestCase):
    """같은 입력 → 레퍼런스 Python과 같은 출력(시험에서만 레퍼런스를 읽기 전용으로 import)."""

    @classmethod
    def setUpClass(cls):
        sys.dont_write_bytecode = True                   # 레퍼런스 폴더에 __pycache__를 만들지 않는다
        sys.path.insert(0, str(REF / "tools"))
        import adpcm as ref_adpcm
        import frame_codec as ref_fc
        import squad_localize as ref_sl
        cls.ref_fc, cls.ref_adpcm, cls.ref_sl = ref_fc, ref_adpcm, ref_sl

    @classmethod
    def tearDownClass(cls):
        sys.path.remove(str(REF / "tools"))

    def test_codec_random_roundtrip(self):
        rnd = random.Random(7)
        n = 0
        for f in G["frames"] if G else []:
            raw = bytearray(hb(f["frame_hex"]))
            for _ in range(20):                          # 같은 타입, 무작위 seq·payload 바이트
                raw[2] = rnd.randrange(256)
                for i in range(6, len(raw)):
                    raw[i] = rnd.randrange(256)
                for codec in (fc, self.ref_fc):
                    try:
                        codec.decode(bytes(raw))
                    except codec.FrameError:
                        pass
                try:
                    ref = self.ref_fc.decode(bytes(raw))
                except self.ref_fc.FrameError:
                    self.assertRaises(fc.FrameError, fc.decode, bytes(raw))
                    continue
                ours = fc.decode(bytes(raw))
                self.assertEqual(ours, ref)
                if ours["type"] != fc.LOG:                   # LOG는 비ASCII를 '?'로 바꿔 표시만 한다(재인코딩 대상 아님)
                    self.assertEqual(fc.encode(ours), bytes(raw))
                n += 1
        self.assertGreater(n, 500)

    def test_adpcm_same(self):
        rnd = random.Random(3)
        x = [rnd.randrange(-32768, 32768) for _ in range(3001)]
        self.assertEqual(encode(x, 0, 0), self.ref_adpcm.encode(x, 0, 0))

    def test_localize_same(self):
        rnd = random.Random(5)
        for _ in range(30):
            ids = [0, 1, 2, 3][:rnd.choice((3, 4))]
            meas = {(i, j): rnd.uniform(1, 20) for i in ids for j in ids if i != j and rnd.random() < 0.8}
            for clocks in (None, {}):
                a = localize.localize(ids, meas, "wedge", clocks=clocks)[0]
                b = self.ref_sl.localize(ids, meas, "wedge", clocks=clocks)[0]
                for k in a:
                    self.assertAlmostEqual(a[k][0], b[k][0], places=9)
                    self.assertAlmostEqual(a[k][1], b[k][1], places=9)

    def test_voice_prep_same_as_load_wav_8k(self):
        wavs = sorted((REF / "assets" / "test_voice").glob("*.wav"))
        self.assertTrue(wavs)
        import importlib.util
        spec = importlib.util.spec_from_file_location("ref_mock_leader", REF / "tools" / "mock_leader.py")
        ml = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ml)                      # bleak 필요(venv에 있음). 모듈 수준 코드만 실행
        for w in wavs:
            with self.subTest(w.name):
                self.assertEqual(load_wav_8k(w), ml.load_wav_8k(str(w)))


if __name__ == "__main__":
    unittest.main()
