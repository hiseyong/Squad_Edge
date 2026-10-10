import asyncio
import json
import unittest

import numpy as np

from squad.audio import dsp
from squad.audio.arbiter import AudioArbiter, Item, Priority
from squad.audio.fmt import dbfs, pcm_to_float, to_16k_mono, to_mono
from squad.audio.pipeline import preprocess
from squad.audio.speaker import SpeakerVerifier
from squad.audio.stream import MicStreamServer
from tests.synth import SR, gunshot, noise, snr_db, speech_like


class Format(unittest.TestCase):
    def test_rates_to_16k(self):
        for sr in (8000, 16000, 24000, 44100, 48000):
            with self.subTest(sr=sr):
                self.assertEqual(len(to_16k_mono(np.zeros(sr, np.float32), sr)), 16000)

    def test_one_dead_channel(self):
        x = np.stack([np.full(100, 0.5, np.float32), np.zeros(100, np.float32)], 1)
        self.assertTrue(np.allclose(to_mono(x), 0.5))

    def test_pcm_s16(self):
        raw = np.array([16384, -16384], "<i2").tobytes()
        self.assertTrue(np.allclose(pcm_to_float(raw, "s16le", 1)[:, 0], [0.5, -0.5]))


class Dsp(unittest.TestCase):
    def test_denoise_improves_snr(self):
        s = speech_like(4)
        x = s + noise(4, 0.02)
        y = dsp.spectral_denoise(dsp.highpass(x, SR), SR, speech_mask=dsp.vad_samples(x, SR))
        self.assertGreater(snr_db(dsp.highpass(s, SR), y), snr_db(s, x) + 4)

    def test_gunshot_suppressed(self):
        s = speech_like(4)
        g = gunshot()
        for at in (1.5, 2.08):
            x = s.copy()
            pos = int(at * SR)
            x[pos:pos + len(g)] += g
            y, ev = dsp.suppress_impulses(x, SR)
            seg = slice(pos, pos + len(g))
            self.assertEqual(len(ev), 1)
            self.assertLess(dbfs(y[seg]), dbfs(x[seg]) - 6)

    def test_no_false_impulse_on_speech(self):
        for lvl in (0.02, 0.1, 0.33):
            for seed in range(3):
                x = speech_like(4, level=lvl, seed=seed, f0=100 + 40 * seed) + noise(4, 0.003)
                self.assertEqual(dsp.suppress_impulses(x, SR)[1], [])

    def test_agc_levels_converge(self):
        outs = []
        for lvl in (0.005, 0.1, 0.5):
            r = preprocess(speech_like(4, level=lvl) + noise(4, 0.002), SR)
            outs.append(dbfs(r.audio[dsp.vad_samples(r.audio, SR)]))
            self.assertLess(np.abs(r.audio).max(), 0.9)
        self.assertLess(max(outs) - min(outs), 4.0)  # 입력 40dB 차이 → 출력 4dB 이내

    def test_pipeline_24k_stereo(self):
        x = np.stack([speech_like(3, sr=24000), np.zeros(72000, np.float32)], 1)
        r = preprocess(x, 24000)
        self.assertEqual((r.sr, len(r.audio)), (16000, 48000))


class FakePlayer:
    def __init__(self):
        self.playing = None
        self.stops = 0

    def play(self, item):
        self.playing = item

    def stop(self):
        self.stops += 1
        self.playing = None


def finish(a, p):
    p.playing = None
    a.on_finished()


class Arbiter(unittest.TestCase):
    def setUp(self):
        self.p = FakePlayer()
        self.a = AudioArbiter(self.p)

    def test_radio_interrupts_system(self):
        self.a.submit(Item(Priority.SYSTEM, "교범 답변"))
        self.a.submit(Item(Priority.COMMAND, "소대장 명령"))
        self.assertEqual(self.p.playing.text, "소대장 명령")
        finish(self.a, self.p)
        self.assertEqual(self.p.playing.text, "교범 답변")  # 끊긴 답변 이어서
        self.assertTrue(self.p.playing.interrupted)

    def test_same_level_queues(self):
        self.a.submit(Item(Priority.REPORT, "1번 보고"))
        self.a.submit(Item(Priority.REPORT, "2번 보고"))
        self.assertEqual(self.p.playing.text, "1번 보고")
        finish(self.a, self.p)
        self.assertEqual(self.p.playing.text, "2번 보고")

    def test_ptt_barge_in(self):
        self.a.submit(Item(Priority.REPORT, "보고"))
        self.a.ptt_down()
        self.assertIsNone(self.p.playing)
        self.a.submit(Item(Priority.COMMAND, "명령"))
        self.assertIsNone(self.p.playing)          # PTT 중엔 대기
        self.a.submit(Item(Priority.URGENT, "3번 부상"))
        self.assertEqual(self.p.playing.text, "3번 부상")  # 긴급은 재생
        finish(self.a, self.p)
        self.assertIsNone(self.p.playing)
        self.a.ptt_up()
        self.assertEqual(self.p.playing.text, "명령")
        finish(self.a, self.p)
        self.assertEqual(self.p.playing.text, "보고")


class Speaker(unittest.TestCase):
    def test_same_vs_other(self):
        def voice(f0, seed, formant_shift=1.0):
            # 화자 차이 = 기본주파수 + 성도 길이(리샘플로 포먼트 이동)
            x = speech_like(4, f0=f0, seed=seed, sr=int(SR * formant_shift))
            return to_16k_mono(x + noise(4, 0.002, seed=seed + 9, sr=int(SR * formant_shift)),
                               int(SR * formant_shift))
        v = SpeakerVerifier()
        v.enroll([voice(110, s) for s in range(3)])
        same = [v.score(voice(110 + d, 10 + d)) for d in (-5, 0, 5)]
        other = [v.score(voice(f, 20 + i, sh)) for i, (f, sh) in enumerate([(210, 1.2), (160, 1.1), (90, 0.85)])]
        self.assertGreater(min(same), v.threshold)
        self.assertLess(max(other), v.threshold)


class Stream(unittest.TestCase):
    def test_tcp_ptt_capture(self):
        async def run():
            srv = MicStreamServer(port=0)
            server = await asyncio.start_server(srv._handle, "127.0.0.1", 0)
            port = server.sockets[0].getsockname()[1]
            _, w = await asyncio.open_connection("127.0.0.1", port)
            w.write((json.dumps({"v": 1, "sr": 24000, "ch": 2, "fmt": "s16le"}) + "\n").encode())
            await srv.connected.wait()
            got = []
            srv.ptt_down(preroll_s=0, sink=lambda x, sr: got.append((len(x), sr)))
            pcm = np.zeros((24000, 2), "<i2")
            pcm[:, 0] = 1000
            w.write(pcm.tobytes())
            await w.drain()
            await asyncio.sleep(0.2)
            x, sr = srv.ptt_up()
            w.close()
            server.close()
            return x, sr, got

        x, sr, got = asyncio.run(run())
        self.assertEqual((sr, len(x)), (24000, 24000))
        self.assertEqual(sum(n for n, _ in got), 24000)       # 스트리밍 STT로 실시간 전달된 양 = PTT 구간
        self.assertAlmostEqual(float(x.mean()), 1000 / 32768, places=4)


if __name__ == "__main__":
    unittest.main()
