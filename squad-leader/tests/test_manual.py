import unittest
from pathlib import Path

from squad.manual.answer import answer
from squad.manual.parse import Spacer, join_lines, parse
from squad.manual.schema import Kind, RType, UType
from squad.manual.search import ManualIndex, _strip, expand, tokens
from squad.manual.units import build_units, classify, split_sentences

PDF = Path(__file__).resolve().parent.parent / "manuals" / "TC3-21.75_발췌번역_비공식.pdf"


@unittest.skipUnless(PDF.exists(), "번역본 PDF 없음")
class Pipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.paras = parse(PDF)
        cls.units, cls.rels = build_units(cls.paras)
        cls.by_id = {p.id: p for p in cls.paras}
        cls.index = ManualIndex(cls.paras, cls.units, cls.rels)

    def test_structure(self):
        nums = [p.id for p in self.paras if p.kind == Kind.PARA]
        self.assertEqual(len(nums), 89)
        for pid in ("3-39", "3-57", "5-1", "5-19", "9-38", "11-5", "15-34"):
            self.assertIn(pid, nums)
        p = self.by_id["3-45"]
        self.assertEqual((p.chapter, p.headings[-1], p.source.page_label), ("제3장 전투 부상자 처치 및 예방의학", "감는 방법", "3-24"))
        self.assertEqual(self.by_id["15-26"].headings, ["종류"])

    def test_boxes_attached(self):
        applies = {(r.src, r.dst) for r in self.rels if r.type == RType.APPLIES_TO}
        self.assertIn(("3-54.box1", "3-54"), applies)
        self.assertEqual(self.by_id["3-39.box1"].label, "위험")

    def test_procedure_steps_ordered(self):
        steps = [u for u in self.units if u.type == UType.PROCEDURE and u.para_id.startswith("3.전투용")]
        self.assertEqual(sorted({u.order for u in steps}), list(range(1, 8)))

    def test_answers(self):
        a = answer(self.index, "쇼크 환자한테 물 줘도 돼?")
        self.assertEqual((a.status, a.main.id), ("answer", "3-57"))
        a = answer(self.index, "쇼크 환자 다리 올려도 돼?")
        self.assertEqual(a.main.id, "3-54")
        self.assertTrue(any("다리를 올리지 않는다" in t for _, t in a.cautions))   # 적용 경고 상자 포함
        self.assertIn("3-27쪽", a.citations[0])

    def test_compare(self):
        a = answer(self.index, "엄폐와 은폐 차이가 뭐야")
        self.assertEqual([t for t, _ in a.lines if t.startswith("정의")], ["정의: 엄폐", "정의: 은폐"])

    def test_list_read_aloud(self):
        a = answer(self.index, "부상자가 쇼크 상태인지 뭘 보고 판단할 수 있어?")
        self.assertEqual(a.main.id, "3-52")
        self.assertIn("약하고 빠른 맥박", a.spoken())       # "다음 징후…" 뒤 목록까지 읽는다

    def test_abstain_out_of_scope(self):
        for q in ("K2 소총 분해 결합 순서", "박격포 최대 사거리는?", "휴가 신청은 어떻게 해?"):
            with self.subTest(q=q):
                self.assertEqual(answer(self.index, q).status, "abstain")


class Rules(unittest.TestCase):
    def test_join_lines(self):
        self.assertEqual(join_lines(["쓰지 않는", "다. 그렇지", "만 일단"]), "쓰지 않는다. 그렇지만 일단")
        self.assertEqual(join_lines(["가 있다.", "• 하나", "• 둘"]), "가 있다.\n• 하나\n• 둘")

    def test_spacer(self):
        # 줄 안쪽 띄어쓰기에서 배운 통계로 줄바꿈 지점을 판정 (줄 첫·끝 어절은 학습에서 제외되므로 앞뒤에 덧말)
        sp = Spacer(["가 엄폐물을 찾는다 나", "가 엄폐물이 있다 나", "가 쇼크가 왔다 나", "가 하거나 했거나 나",
                     "가 대한 저항 대한 의지 대한 사항 나"] * 3)   # 조각은 3번 이상 나와야 근거로 쓴다
        self.assertEqual(join_lines(["쇼크가 왔", "거나 호흡이"], sp), "쇼크가 왔거나 호흡이")
        self.assertEqual(join_lines(["부상자를 엄", "폐물 뒤로"], sp), "부상자를 엄폐물 뒤로")
        self.assertEqual(join_lines(["적에 대한", "저항이 있다"], sp), "적에 대한 저항이 있다")

    def test_split_sentences(self):
        self.assertEqual([s for s, _ in split_sentences("모든 것이다(그림 5-6). 보호하지 못한다.")],
                         ["모든 것이다(그림 5-6).", "보호하지 못한다."])

    def test_stem(self):
        self.assertEqual([_strip(w) for w in ("올린다", "감는다", "지혈대를", "풀거나")], ["올리", "감", "지혈대", "풀"])
        self.assertIn("w:400", tokens("400m에서"))
        # 구어 질문: 과거형, 겹친 조사, 구어 조사, 하다 동사, 부사 보호
        cases = {"감았는데": "감", "멈췄어": "멈추", "조였는지": "조이", "절단됐는데": "절단", "있었다": "있",
                 "출혈에나": "출혈", "위협으로부터": "위협", "부상자한테": "부상자", "엄폐랑": "엄폐",
                 "사용해도": "사용", "사용한다": "사용", "바로": "바로"}
        self.assertEqual({w: _strip(w) for w in cases}, cases)

    def test_synonym_word_level(self):
        self.assertNotIn("거리 측정", expand("박격포 사거리"))   # 부분 문자열로 확장하지 않음
        self.assertIn("지혈대", expand("토니켓 감는 법"))

    def test_classify(self):
        from squad.manual.schema import Paragraph, Source
        p = Paragraph("x", Kind.PARA, "", "", [], "", Source("d", "1-1", 1))
        self.assertEqual(classify("상처 바로 위에는 절대 감지 않는다.", "", p)[0], UType.PROHIBITION)
        t, cond, act, _ = classify("팔다리가 완전히 절단되었으면 절단면에 붕대를 감는다.", "", p)
        self.assertEqual((t, cond), (UType.DECISION_RULE, "팔다리가 완전히 절단되었으면"))
        self.assertEqual(classify("다만 재료가 막대에 감긴 상태로 유지한다.", "", p)[0], UType.EXCEPTION)
        self.assertEqual(classify("미끄러지지 않게 한다.", "", p)[0], UType.FACT)


if __name__ == "__main__":
    unittest.main()
