"""병사 링크 상태기계 오프라인 시험 (가짜 Transport, BLE 없음). 레퍼런스 test_mock_leader_offline과 같은 방식."""
import asyncio
import unittest

from squad.soldier import codec as fc
from squad.soldier.leader import SquadLeader
from squad.soldier.seq import LeaderSeq


class FakeLink:
    def __init__(self, ids=(1, 2)):
        self.up = set(ids)
        self.sent: list[tuple[int, bytes, bool]] = []

    def mtu(self, sid):
        return 247

    def connected(self, sid):
        return sid in self.up

    def connected_ids(self):
        return sorted(self.up)

    async def write(self, sid, raw, response=True):
        if sid not in self.up:
            return False
        self.sent.append((sid, bytes(raw), response))
        return True


def report(t, seq, src, **f):
    return fc.encode(dict(type=t, seq=seq, src=src, dst=0x80, **f))


CONTACT = dict(azimuth=60, clock=2, dist_band=2, count=3, heading=0)


class Leader(unittest.TestCase):
    def setUp(self):
        self.now = [100.0]
        self.link = FakeLink()
        self.events = []
        self.ld = SquadLeader(self.link, seq=LeaderSeq(0), on_event=self.events.append, clock=lambda: self.now[0])

    def run_async(self, coro):
        async def go():
            r = await coro
            await asyncio.sleep(0)          # 만든 RPT_ACK 태스크가 돌게
            await asyncio.sleep(0)
            return r
        return asyncio.run(go())

    def test_rpt_ack_immediate_and_retransmit(self):
        raw = report(fc.CONTACT, 7, 1, **CONTACT)

        async def go():
            self.ld.on_frame(1, raw)
            self.ld.on_frame(1, raw)                    # 병사 재전송(같은 seq·같은 바이트) → 다시 RPT_ACK
            await asyncio.sleep(0.01)
        asyncio.run(go())
        acks = [fc.decode(r) for _, r, _ in self.link.sent if r[1] == fc.RPT_ACK]
        self.assertEqual([(a["ref_seq"], a["dst"]) for a in acks], [(7, 0x01), (7, 0x01)])
        self.assertEqual(len({a["seq"] for a in acks}), 2)               # RPT_ACK마다 새 seq
        frames = [e for e in self.events if e["kind"] == "frame"]
        self.assertEqual([e["retransmit"] for e in frames], [False, True])
        self.assertEqual(fc.to_hex(self.link.sent[0][1])[:8], "01 17 00")   # 첫 송신 = RPT_ACK(중계보다 먼저)

    def test_pending_acks_until_connected(self):
        self.link.up = set()

        async def go():
            self.ld.on_frame(2, report(fc.OK_READY, 3, 2))   # 구독 직후·연결 완료 전에 온 보고
            await asyncio.sleep(0.01)
            self.assertEqual(self.link.sent, [])
            self.link.up = {2}
            self.ld.on_connect(2, 247)
            await asyncio.sleep(0.01)
        asyncio.run(go())
        self.assertEqual([fc.decode(r)["ref_seq"] for _, r, _ in self.link.sent], [3])

    def test_reboot_same_seq_new_report(self):
        async def go():
            self.ld.on_frame(1, report(fc.OK_READY, 0, 1))
            self.ld.on_disconnect(1)
            self.ld.on_connect(1, 247)                     # 새 연결 → 기록 초기화
            self.ld.on_frame(1, report(fc.OK_READY, 0, 1))  # 재부팅 뒤 같은 seq 0
            await asyncio.sleep(0.01)
        asyncio.run(go())
        self.assertEqual([e["retransmit"] for e in self.events if e["kind"] == "frame"], [False, False])

    def test_no_ack_for_stats_ranging_log(self):
        async def go():
            self.ld.on_frame(1, report(fc.RANGING, 9, 1, peers=[dict(peer_id=0, rssi_avg=-66, samples=15)]))
            self.ld.on_frame(1, report(fc.LOG, 10, 1, text="hi"))
            self.ld.on_frame(1, report(fc.STATS, 11, 1, tx_frames=[0, 1, 2], tx_bytes=[0, 10, 20]))
            await asyncio.sleep(0.01)
        asyncio.run(go())
        self.assertEqual(self.link.sent, [])

    def test_cmd_ack_and_resend_same_bytes(self):
        async def go():
            pc = await self.ld.send_cmd(fc.CMD_CODES["TAKE_COVER"], 270, fc.NO_DIST, 0, 1, "all")
            self.assertEqual(fc.to_hex(pc.raw), "01 10 00 00 1F 06 02 0E 01 FF 00 01")   # 전원 = 1F
            self.ld.on_frame(1, report(fc.ACK, 5, 1, ref_type=fc.REF_BUTTON, ref_id=pc.seq))
            await asyncio.sleep(0.01)
            self.now[0] += 15.1
            await self.ld.check_cmds()                      # S2 무응답 → 같은 바이트로 S2에만 1회
            self.now[0] += 15.1
            await self.ld.check_cmds()                      # 그래도 없음 → 미수신
            return pc
        pc = asyncio.run(go())
        cmd_writes = [(s, r) for s, r, _ in self.link.sent if r[1] == fc.CMD_BUTTON]
        self.assertEqual(cmd_writes, [(1, pc.raw), (2, pc.raw), (2, pc.raw)])
        self.assertEqual(pc.status, {1: "수신", 2: None})
        self.assertIn({"kind": "cmd_unacked", "seq": pc.seq, "code": 2, "sids": [2]}, self.events)

    def test_targets_mask(self):
        async def go():
            return await self.ld.send_cmd(fc.CMD_CODES["ENEMY_INFO"], 60, 2, 3, 0, "2")
        pc = asyncio.run(go())
        self.assertEqual(fc.to_hex(pc.raw), "01 10 00 00 02 06 09 3C 00 02 03 00")     # 안내문 §5 예
        self.assertEqual([s for s, _, _ in self.link.sent], [2])


class S3(unittest.TestCase):
    def setUp(self):
        self.link = FakeLink((1, 2, 3))
        self.events = []
        self.ld = SquadLeader(self.link, seq=LeaderSeq(0), on_event=self.events.append, allowed=(1, 2, 3))

    def sent(self, t):
        return [(s, fc.decode(r)) for s, r, _ in self.link.sent if r[1] == t]

    def test_relay_orig_seq_pos_unknown_and_no_retransmit(self):
        raw = report(fc.CONTACT, 7, 2, azimuth=0xFFFF, clock=0, dist_band=0xFF, count=3, heading=0)

        async def go():
            self.ld.on_frame(2, raw)
            self.ld.on_frame(2, raw)                         # 재전송 → 다시 중계하지 않음
            await asyncio.sleep(0.01)
        asyncio.run(go())
        peers = self.sent(fc.PEER_REPORT)
        self.assertEqual(len({m["seq"] for _, m in peers}), 1)           # 중계 1번(같은 프레임을 S1·S3에)
        sid, m = peers[0]
        self.assertEqual((m["dst"], m["reporter_id"], m["rx"], m["ry"], m["orig_seq"]), (0x05, 2, -32768, -32768, 7))
        self.assertEqual(m["orig"]["count"], 3)
        self.assertEqual(sorted(s for s, r, _ in self.link.sent if r[1] == fc.PEER_REPORT), [1, 3])

    def test_relay_uses_pos_table(self):
        async def go():
            await self.ld.send_pos_preset("line")
            self.ld.on_frame(2, report(fc.CONTACT, 9, 2, azimuth=0xFFFF, clock=0, dist_band=0xFF, count=3, heading=0))
            await asyncio.sleep(0.01)
        asyncio.run(go())
        pt = self.sent(fc.POS_TABLE)[0][1]
        self.assertEqual([(e["id"], e["x"], e["y"]) for e in pt["entries"]],
                         [(0, 0, 0), (1, -100, 0), (2, 100, 0), (3, -200, 0), (4, 200, 0), (5, -300, 0)])
        m = self.sent(fc.PEER_REPORT)[0][1]
        self.assertEqual((m["rx"], m["ry"]), (100, 0))             # S2 = 횡대 (10m, 0)

    def test_log_not_acked_not_relayed(self):
        async def go():
            self.ld.on_frame(1, report(fc.LOG, 4, 1, text="boot id=1"))
            await asyncio.sleep(0.01)
        asyncio.run(go())
        self.assertEqual(self.link.sent, [])
        self.assertEqual([e for e in self.events if e["kind"] == "frame"], [])

    def test_emcon_silent_blocks(self):
        async def go():
            await self.ld.send_emcon(0, "1")
            self.link.up.discard(1)                          # 병사가 끊고 침묵
            self.ld.on_disconnect(1)
            return await self.ld.send_cmd(fc.CMD_CODES["HALT"], spec="1")
        pc = asyncio.run(go())
        self.assertIsNone(pc)
        self.assertEqual(fc.to_hex(self.link.sent[0][1]), "01 16 00 00 01 01 00")
        self.assertIn({"kind": "silent_blocked", "sids": [1]}, self.events)

        async def back():
            self.link.up.add(1)
            self.ld.on_connect(1, 247)                       # 보드 A 버튼4 길게 / 병사 직접 해제 → 재연결
            self.ld.on_frame(1, report(fc.EMCON_STATE, 0, 1, mode=2))
            await asyncio.sleep(0.01)
        asyncio.run(back())
        self.assertEqual(self.ld.soldiers[1].emcon, 2)

    def test_voice_frames_and_retry_once(self):
        pcm = [((i * 37) % 2000) - 1000 for i in range(4000)]   # 0.5초 → ADPCM 2000B → 청크 9개

        async def go():
            pv = await self.ld.send_voice(pcm, 1, "1")
            await asyncio.sleep(0.5)
            first = len(self.link.sent)
            self.ld.on_frame(1, report(fc.VOICE_RESULT, 3, 1, voice_id=pv.clip.voice_id, status=1))   # CRC 오류
            await asyncio.sleep(0.5)
            self.ld.on_frame(1, report(fc.VOICE_RESULT, 4, 1, voice_id=pv.clip.voice_id, status=1))   # 또 실패 → 더 안 보냄
            await asyncio.sleep(0.3)
            return pv, first
        pv, first = asyncio.run(go())
        voice = [(s, r, resp) for s, r, resp in self.link.sent if r[1] in (fc.VOICE_BEGIN, fc.VOICE_CHUNK, fc.VOICE_END)]
        self.assertEqual(len(voice), 2 * (1 + 9 + 1))                    # 1회 재전송까지
        self.assertEqual([resp for _, _, resp in voice[:11]], [True] + [False] * 9 + [True])
        b1, b2 = fc.decode(voice[0][1]), fc.decode(voice[11][1])
        self.assertEqual((b1["voice_id"], b2["voice_id"], b1["priority"]), (pv.clip.voice_id, pv.clip.voice_id, 1))
        self.assertNotEqual(b1["seq"], b2["seq"])                       # 재전송은 같은 voice_id, 새 프레임 seq
        self.assertEqual(pv.retried, {1})


class S4(unittest.TestCase):
    def setUp(self):
        self.link = FakeLink((1, 2))
        self.events = []
        self.now = [100.0]
        self.ld = SquadLeader(self.link, seq=LeaderSeq(0), on_event=self.events.append, allowed=(1, 2),
                              clock=lambda: self.now[0])

    def ranging(self, sid, seq, peers):
        self.ld.on_frame(sid, report(fc.RANGING, seq, sid,
                                     peers=[dict(peer_id=p, rssi_avg=r, samples=15) for p, r in peers.items()]))

    def test_pos_auto_matches_localize_and_stale(self):
        from squad.soldier.localize import localize, measured_from_rssi
        self.ranging(1, 1, {0: -68, 2: -72})
        self.ranging(2, 1, {0: -70, 1: -71})
        pos = asyncio.run(self.ld.pos_auto())
        want, _ = localize([0, 1, 2], measured_from_rssi({1: {0: -68, 2: -72}, 2: {0: -70, 1: -71}}, -65.5, 1.6),
                           "wedge", clocks={1: 10, 2: 2})
        for i in want:
            self.assertAlmostEqual(pos[i][0], want[i][0], places=9)
            self.assertAlmostEqual(pos[i][1], want[i][1], places=9)
        pt = [fc.decode(r) for _, r, _ in self.link.sent if r[1] == fc.POS_TABLE][0]
        self.assertEqual([e["id"] for e in pt["entries"]], [0, 1, 2])
        self.assertTrue(pos[1][0] < 0 < pos[2][0])                 # S1 왼쪽(10시), S2 오른쪽(2시)
        self.now[0] += 31                                           # 30초 지난 RANGING은 안 씀
        self.assertEqual(self.ld.rssi_rows(), {})

    def test_target_estimate_relative_to_leader(self):
        async def go():
            await self.ld.send_pos({1: (-10.0, 0.0), 2: (10.0, 0.0)})
            self.ld.on_frame(2, report(fc.CONTACT, 5, 2, azimuth=0, clock=12, dist_band=0, count=3, heading=0))
            self.ld.on_frame(1, report(fc.HAZARD, 6, 1, azimuth=0xFFFF, clock=0, heading=0))
            await asyncio.sleep(0.01)
        asyncio.run(go())
        t = [e["target"] for e in self.events if e["kind"] == "frame" and "target" in e]
        self.assertEqual((t[0]["x"], t[0]["y"], t[0]["bearing"], t[0]["clock"], t[0]["basis"]), (10.0, 10.0, 45, 2, "pos_table"))
        self.assertAlmostEqual(t[0]["dist"], 14.1, places=1)
        self.assertEqual((t[1]["x"], t[1]["y"], t[1]["clock"], t[1]["basis"]), (-10.0, 0.0, 9, "toward_reporter"))

    def test_target_without_pos_table(self):
        from squad.soldier.geo import target_estimate
        t = target_estimate(None, 90, 2)
        self.assertEqual((t["x"], t["y"], t["clock"], t["basis"]), (40.0, 0.0, 3, "leader_origin"))

    def test_pos_table_resent_on_reconnect(self):
        async def go():
            await self.ld.send_pos_preset("line")
            n = len(self.link.sent)
            self.ld.on_connect(1, 247)
            await asyncio.sleep(0.01)
            return self.link.sent[n:]
        new = asyncio.run(go())
        self.assertEqual([(s, r[1], r[4]) for s, r, _ in new], [(1, fc.POS_TABLE, 0x01)])

    def test_pos_dist(self):
        pos = asyncio.run(self.ld.pos_dist(3, 4, 5, {1: 9, 2: 12}))
        self.assertAlmostEqual(pos[1][0], -3.0, places=3)
        self.assertAlmostEqual(pos[2][1], 4.0, places=3)


if __name__ == "__main__":
    unittest.main()


class Phrases(unittest.TestCase):
    def test_guide_e(self):
        from squad.soldier.phrases import report_sentence
        m = fc.decode(fc.from_hex("01 01 07 01 80 07 3C 00 02 02 03 00 00"))
        self.assertEqual(report_sentence(m), ("1번, 적 3명, 2시, 원거리", "urgent", 1))
        self.assertEqual(report_sentence(fc.decode(report(fc.CASUALTY_SELF, 1, 2, heading=0)))[0::2], ("2번 부상", 2))
        self.assertEqual(report_sentence(fc.decode(report(fc.HAZARD, 1, 2, azimuth=0xFFFF, clock=0, heading=0)))[0],
                         "2번, 폭발물 의심")


class LivePos(unittest.TestCase):
    def test_line_default_then_measured_with_smoothing(self):
        link = FakeLink((1, 2))
        events = []
        ld = SquadLeader(link, seq=LeaderSeq(0), on_event=events.append, allowed=(1, 2), clock=lambda: 100.0)
        ld.clocks = {1: 9, 2: 3}

        async def go():
            await ld.send_pos_preset("line")                 # 기본: S1 (-10,0), S2 (10,0)
            for sid, peers in ((1, {0: -76, 2: -82}), (2, {0: -76, 1: -82})):   # 실측 ≈ 분대장 4.5m, 서로 8.1m
                ld.on_frame(sid, report(fc.RANGING, 1, sid, peers=[dict(peer_id=p, rssi_avg=r, samples=15)
                                                                    for p, r in peers.items()]))
            return ld.update_live()
        live, info = asyncio.run(go())
        self.assertEqual(info["measured"], 3)
        self.assertLess(live[1][0], 0)                       # S1 왼쪽, S2 오른쪽(횡대 방향 유지)
        self.assertGreater(live[2][0], 0)
        # 평활 0.5: 프리셋 (-10,0)과 실측 (≈-4,0)의 중간쯤
        self.assertTrue(-8.5 < live[1][0] < -5.5, live)
        self.assertEqual([e["kind"] for e in events if e["kind"].startswith("pos")], ["pos_table", "pos_live"])

    def test_missing_pair_does_not_flip(self):
        link = FakeLink((1, 2))
        now = [100.0]
        ld = SquadLeader(link, seq=LeaderSeq(0), allowed=(1, 2), clock=lambda: now[0])
        ld.clocks, ld.pos_smooth = {1: 9, 2: 3}, 1.0

        def rng(sid, peers):
            ld.on_frame(sid, report(fc.RANGING, 1, sid, peers=[dict(peer_id=p, rssi_avg=r, samples=15) for p, r in peers.items()]))

        async def go():
            await ld.send_pos_preset("line")
            rng(1, {0: -60, 2: -66})
            rng(2, {0: -62, 1: -66})
            first = ld.update_live()[0]
            now[0] += 40                                   # 이전 RANGING 만료
            rng(1, {0: -60})                               # S1–S2 쌍이 빠진 회차
            rng(2, {0: -62})
            return first, ld.update_live()
        first, second = asyncio.run(go())
        self.assertGreater(first[2][0], 0)
        self.assertIsNotNone(second)
        self.assertGreater(second[0][2][0], 0)            # S2는 여전히 오른쪽
