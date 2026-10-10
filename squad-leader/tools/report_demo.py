"""[보드] 분대장 → 소대장 양식화된 보고 시연 (BLE·마이크 없이 시나리오로).

    .venv/bin/python tools/report_demo.py            # 텍스트 보고 + 복창 + JSON
    .venv/bin/python tools/report_demo.py --speak    # 복창을 TTS로 합성해 recordings/report_readback.wav

시나리오: 병사 1·3번이 같은 적을 서로 다른 방위로 보고 → 교차 추정 → 2번 본인 부상
        → 분대장 보고 버튼 + "적이 좌측으로 우회 중, 고수하겠음, 의무후송 요청" → 복창 → 송신
        → 2분 뒤 3번이 거리 근거리로 다시 보고(접근) → 변동분만 담은 두 번째 보고
분대장 위치는 GPS 연동 전이라 시연용 가정 좌표.
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from squad.protocol import Msg  # noqa: E402
from squad.report.compose import Composer, ReportDesk  # noqa: E402
from squad.report.grid import latlon_to_utm  # noqa: E402
from squad.report.log import CombatLog  # noqa: E402
from squad.report.situation import Situation  # noqa: E402
from squad.report.utterance import parse  # noqa: E402

LEADER_LATLON = (37.9012, 127.0605)     # 시연용 가정 위치
LEADER_HEADING = 45                     # 분대 정면 북동
FORMATION = [(1, -40, 10, 45), (2, -20, 0, 45), (3, 40, -10, 45), (4, 20, -5, 45), (5, 0, -20, 45)]  # 횡대, m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--speak", action="store_true")
    args = ap.parse_args()

    t0 = time.time()
    log = CombatLog()
    sit = Situation()
    sit.set_positions(FORMATION)
    desk = ReportDesk(Composer(sit, latlon_to_utm(*LEADER_LATLON), LEADER_HEADING), log)

    def report(sid, mt, ts, **f):
        log.add("report", sid, {"type": int(mt), **f}, ts=ts)
        ev = sit.on_report(sid, mt, f, ts)
        d = desk.on_events(ev, ts)
        print(f"  +{ts - t0:4.0f}s  {sid}번 {Msg(mt).name} {f}  → 사건 {ev}" + (f"  ▶ 초안 [{d.prec}]" if d else ""))
        return d

    print("== 병사 보고 ==")
    # 적 실제 위치 (150, 200)m → 1번(-40,10)에서 방위 45도, 3번(40,-10)에서 28도
    report(1, Msg.CONTACT, t0 + 5, azimuth=45, clock=12, dist_band=2, count=3, heading=45)
    report(3, Msg.CONTACT, t0 + 20, azimuth=28, clock=11, dist_band=2, count=2, heading=45)
    report(2, Msg.CASUALTY_SELF, t0 + 40, heading=45)

    said = "적이 좌측으로 우회 중, 고수하겠음, 의무후송 요청"
    print(f"\n== 분대장 보고 버튼 + 발화: \"{said}\" ==")
    r = desk.with_voice(parse(said), t0 + 50)
    print(r.text())
    print(f"\n복창: {r.readback}")
    if r.prompts:
        print(f"되묻기: {r.prompts}")
    sent = desk.confirm()
    print("\n구조화 데이터(소대장 노트북용 초안):")
    print(json.dumps({k: v for k, v in sent.data.items() if k != "_full"}, ensure_ascii=False, indent=1)[:1500])

    print("\n== 2분 뒤: 3번이 근거리로 다시 보고 ==")
    sit.set_link(5, False, t0 + 160)
    desk.on_events(["link_lost"], t0 + 160)
    report(3, Msg.CONTACT, t0 + 170, azimuth=25, clock=11, dist_band=0, count=3, heading=45)
    r2 = desk.with_voice(parse("적 접근 중, 사격 개시하겠음"), t0 + 180)
    print(r2.text())
    print(f"\n복창: {r2.readback}")
    desk.confirm()
    print(f"\n송신 기록 {len(log.since(kind='sent'))}건, 전체 로그 {len(log.since())}건")

    if args.speak:
        import soundfile as sf
        from squad.speech.tts import OUT_SR, Synth
        from squad.speech.verbalize import verbalize
        print(f"읽기 변환: {verbalize(r.readback)}")
        audio = Synth()(verbalize(r.readback))
        out = ROOT / "recordings" / "report_readback.wav"
        sf.write(out, audio, OUT_SR)
        print(f"복창 음성 → {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
