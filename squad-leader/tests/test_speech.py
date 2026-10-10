import asyncio
import json
import struct
import time
import unittest

import numpy as np

from squad.audio.arbiter import AudioArbiter, Item, Priority
from squad.audio.output import RecordingPlayer, RemotePlayer
from squad.audio.stream import MicStreamServer
from squad.protocol import AZ_NONE, DIST_NONE, Frame, Msg, build_report
from squad.speech.announce import Announcer, UpperMessage, phrase_bank, report_phrases
from squad.speech.tts import OUT_SR, Synth
from squad.speech.verbalize import native, sino, split_sentences, verbalize


def fake_backend(text):
    # 글자 수에 비례하는 길이의 신호 (22.05kHz로 내보내 리샘플까지 거치게)
    n = int(22050 * 0.05 * max(1, len(text)))
    return np.full(n, 0.1, np.float32), 22050


def make_synth(tmp=None):
    return Synth(backend=fake_backend, cache_dir=tmp)


class Verbalize(unittest.TestCase):
    def test_numbers(self):
        self.assertEqual([sino(x) for x in (0, 10, 11, 350, 1630, 10000, 12000)],
                         ["영", "십", "십일", "삼백오십", "천육백삼십", "만", "만이천"])
        self.assertEqual([native(x) for x in (1, 3, 4, 12, 20, 21)], ["한", "세", "네", "열두", "스무", "스물한"])

    def test_sentences(self):
        for src, want in [
            ("3번, 적 3명, 2시 방향 300m", "삼 번, 적 세 명, 두 시 방향 삼백 미터"),
            ("16시 30분 집결", "십육 시 삼십 분 집결"),
            ("1630Z 도착 예정", "십육 시 삼십 분 표준시 도착 예정"),
            ("12시 방향 1.5km", "열두 시 방향 일 점 오 킬로미터"),
            ("방위 270도", "방위 이백칠십 도"),
            ("격자 329966으로 이동", "격자 삼 둘 아홉 아홉 여섯 여섯으로 이동"),
            ("AB 1234 5678", "알파 브라보 하나 둘 삼 넷 오 여섯 칠 팔"),
            ("2분대는 11시 방향 경계", "이 분대는 열한 시 방향 경계"),
            ("적 10명, 차량 2대", "적 열 명, 차량 두 대"),
            ("1630Z까지 유지", "십육 시 삼십 분 표준시까지 유지"),      # 한글 조사가 바로 붙는 경우
            ("300m에서 정지", "삼백 미터에서 정지"),
            ("EOD를 요청", "이오디를 요청"),
        ]:
            with self.subTest(src=src):
                self.assertEqual(verbalize(src), want)

    def test_split(self):
        self.assertEqual(split_sentences("가. 나다! 라"), ["가.", "나다!", "라"])


class Reports(unittest.TestCase):
    def contact(self, az, count=3, dist=2):
        return build_report(Msg.CONTACT, 7, 3, azimuth=az, clock=2, dist_band=dist, count=count, heading=0)

    def test_contact_leader_relative(self):
        # 적 방위 60, 분대장 방위 0 → 2시 / 분대장이 90을 보면 → 11시
        self.assertEqual(report_phrases(self.contact(60), 0)[0], ["3번", "적 세 명", "2시 방향", "원거리"])
        self.assertEqual(report_phrases(self.contact(60), 90)[0][2], "11시 방향")

    def test_contact_variants(self):
        self.assertEqual(report_phrases(self.contact(AZ_NONE, count=0, dist=DIST_NONE), 0)[0],
                         ["3번", "적 수 미상", "방향 미상"])
        self.assertEqual(report_phrases(self.contact(60, count=5), None)[0][1:3], ["적 다수", "방위 60도"])

    def test_other_templates(self):
        cases = [
            (build_report(Msg.HAZARD, 1, 2, azimuth=0, clock=12, heading=0), ["2번", "폭발물 의심", "12시 방향"]),
            (build_report(Msg.OK_READY, 1, 4), ["4번", "이상 없음"]),
            (build_report(Msg.WEAPON_AMMO, 1, 4), ["4번", "탄약 화기 문제"]),
            (build_report(Msg.ACK, 1, 5, ref_type=0x10, ref_id=3), ["5번", "수신"]),
            (build_report(Msg.CANNOT_COMPLY, 1, 5, ref_type=0x10, ref_id=3), ["5번", "수행 불가"]),
        ]
        for f, want in cases:
            with self.subTest(t=f.msg_type):
                self.assertEqual(report_phrases(f, 0)[0], want)

    def test_casualty_self_urgent_twice(self):
        parts, prio, rep = report_phrases(build_report(Msg.CASUALTY_SELF, 1, 2, heading=0), 0)
        self.assertEqual((parts, prio, rep), (["2번 부상"], Priority.URGENT, 2))

    def test_silent_types(self):
        self.assertIsNone(report_phrases(build_report(Msg.VOICE_RESULT, 1, 2, voice_id=1, status=0), 0))
        self.assertIsNone(report_phrases(Frame(Msg.LOG, 1, 2, 0x80, b"x"), 0))

    def test_bank_covers_templates(self):
        bank = set(phrase_bank())
        for c in range(1, 13):
            parts = report_phrases(self.contact((c % 12) * 30), 0)[0]
            self.assertTrue(set(parts) <= bank, parts)


class Upper(unittest.TestCase):
    def test_parse_and_spoken(self):
        m = UpperMessage.from_json(json.dumps({"v": 1, "from": "platoon", "prec": "flash", "id": "7",
                                               "text": "전원 현 위치 고수."}))
        self.assertEqual(m.priority, Priority.URGENT)
        self.assertEqual(m.spoken(), "긴급. 소대장 전달. 전원 현 위치 고수.")
        self.assertEqual(UpperMessage("company", "보급 1630Z").spoken(), "중대 전달. 보급 1630Z")


class AnnouncerFlow(unittest.TestCase):
    def setUp(self):
        self.player = RecordingPlayer()
        self.arb = AudioArbiter(self.player)
        self.player.bind(self.arb)
        self.ann = Announcer(make_synth(), self.arb, leader_heading=lambda: 0)

    def wait(self, n):
        t = time.monotonic() + 2
        while len(self.player.played) < n and time.monotonic() < t:
            time.sleep(0.01)

    def test_report_read_once_despite_retransmit(self):
        f = build_report(Msg.CONTACT, 9, 1, azimuth=60, clock=2, dist_band=0, count=2, heading=0)
        self.assertIsNotNone(self.ann.on_soldier_frame(f))
        self.assertIsNone(self.ann.on_soldier_frame(f))   # 같은 seq 재전송
        self.wait(1)
        self.assertEqual(self.player.played[0][0], "1번, 적 두 명, 2시 방향, 근거리")
        self.assertGreater(len(self.player.played[0][1]), OUT_SR * 0.3)

    def test_upper_message_streamed(self):
        self.ann.on_upper_message(UpperMessage("battalion", "첫 문장. 둘째 문장.", id="a"))
        self.ann.on_upper_message(UpperMessage("battalion", "첫 문장. 둘째 문장.", id="a"))
        self.wait(1)
        time.sleep(0.05)
        self.assertEqual(len(self.player.played), 1)
        self.assertTrue(self.player.played[0][0].startswith("대대 전달."))


class RemoteOutput(unittest.TestCase):
    def test_audio_frames_reach_mac(self):
        async def run():
            srv = MicStreamServer(port=0)
            server = await asyncio.start_server(srv._handle, "127.0.0.1", 0)
            port = server.sockets[0].getsockname()[1]
            r, w = await asyncio.open_connection("127.0.0.1", port)
            w.write((json.dumps({"v": 1, "sr": 16000, "ch": 1, "fmt": "s16le"}) + "\n").encode())
            await srv.connected.wait()
            player = RemotePlayer(srv, log=lambda m: None)
            arb = AudioArbiter(player)
            player.bind(arb)
            arb.submit(Item(Priority.COMMAND, "t", audio=np.full(1600, 0.5, np.float32)))
            kind = await asyncio.wait_for(r.readexactly(1), 2)
            sr, n = struct.unpack("<II", await r.readexactly(8))
            pcm = np.frombuffer(await r.readexactly(n), "<i2")
            arb.ptt_down()                                 # 재생 중 PTT → 중단 신호
            stop = await asyncio.wait_for(r.readexactly(1), 2)
            w.close()
            server.close()
            return kind, sr, pcm, stop

        kind, sr, pcm, stop = asyncio.run(run())
        self.assertEqual((kind, sr, len(pcm), stop), (b"A", 16000, 1600, b"S"))
        self.assertAlmostEqual(pcm[0] / 32767, 0.5, places=3)


if __name__ == "__main__":
    unittest.main()
