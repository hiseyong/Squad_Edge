import unittest

from squad.text.lexicon import correct, stt_prompt, to_jamo
from squad.text.normalize import normalize
from squad.text.spacing import default_segmenter


class Normalize(unittest.TestCase):
    CASES = [
        ("적 세 명 삼백 미터", "적 3명 300m"),
        ("삼백미터 전방", "300m 전방"),
        ("300 미터", "300m"),
        ("3 킬로 전방", "3km 전방"),
        ("일 킬로미터", "1km"),
        ("이천오백 미터", "2500m"),
        ("두 시 방향 적 다섯 명", "2시 방향 적 5명"),
        ("열두 시 방향 오백 미터 적 한 명", "12시 방향 500m 적 1명"),
        ("열네 시 삼십 분", "14시 30분"),
        ("스물세 시", "23시"),
        ("방위 이백칠십 도", "방위 270도"),
        ("그리드 알파 브라보 일 이 삼 사 오 육 칠 팔", "그리드 AB 12345678"),
        ("킬로 리마 이 공", "KL 20"),
        ("이 번 병사 엄폐", "2번 병사 엄폐"),
        ("적 이 명", "적 2명"),
        ("사 분대", "4분대"),
        ("삼십 분 후 집결", "30분 후 집결"),
        ("일분대", "1분대"),
        ("오분 후", "5분 후"),
        ("삼분간 사격", "3분간 사격"),
    ]
    # 숫자로 바꾸면 안 되는 일반 단어
    KEEP = ["사격 개시", "이동 준비", "오른쪽 구역으로 이동", "이번 작전", "한번 더 확인",
            "십자로", "천천히 전진", "이 사람", "일반 보고", "삼거리 통과", "구역 확보",
            "구분", "구분해야 한다"]

    def test_cases(self):
        for src, want in self.CASES:
            with self.subTest(src=src):
                self.assertEqual(normalize(src), want)

    def test_keep(self):
        for src in self.KEEP:
            with self.subTest(src=src):
                self.assertEqual(normalize(src), src)


class Lexicon(unittest.TestCase):
    def test_misheard(self):
        self.assertEqual(correct("전원 엄페 사격 게시")[0], "전원 엄폐 사격 개시")

    def test_fuzzy(self):
        for src, want in [("저격슈 발견", "저격수 발견"), ("박겨포 사격", "박격포 사격"),
                          ("현 위치 고슈", "현 위치 고수"), ("이동 완뇨", "이동 완료"),
                          ("장갑자 두 대", "장갑차 두 대")]:
            with self.subTest(src=src):
                self.assertEqual(correct(src)[0], want)

    def test_no_overcorrect(self):
        for src in ["전지 교체", "오늘 날씨", "적 발견", "상태 보고하라", "기관총 사수"]:
            with self.subTest(src=src):
                self.assertEqual(correct(src), (src, []))

    def test_prompt(self):
        p = stt_prompt()
        self.assertIn("엄폐", p)
        self.assertLessEqual(len(p), 200)

    def test_jamo(self):
        self.assertEqual(to_jamo("엄폐"), "ㅇㅓㅁㅍㅖ")


if __name__ == "__main__":
    unittest.main()


class Spacing(unittest.TestCase):
    """스트리밍 STT의 붙은 출력 → 띄어쓰기 복원 → 정규화."""
    CASES = [
        ("두시방향삼백미터적세명발견", "2시 방향 300m 적 3명 발견"),
        ("열한시방향폭발물의심물체확인", "11시 방향 폭발물 의심 물체 확인"),
        ("부상자한명발생의무병요청", "부상자 1명 발생 의무병 요청"),
        ("십육시삼십분까지사격통제유지", "16시 30분까지 사격 통제 유지"),
        ("격자삼이구구육육으로이동하라", "격자 329966 으로 이동하라"),
        ("쇼크환자한테물줘도돼", "쇼크 환자한테 물 줘도돼"),
        ("구분해야한다", "구분 해야한다"),
    ]

    def test_cases(self):
        sg = default_segmenter()
        for src, want in self.CASES:
            with self.subTest(src=src):
                self.assertEqual(normalize(sg.segment(src)), want)

    def test_spaced_text_kept(self):
        sg = default_segmenter()
        self.assertEqual(sg.segment("지혈대를 감는다"), "지혈대를 감는다")
