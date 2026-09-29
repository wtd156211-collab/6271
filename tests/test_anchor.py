"""行级锚定引擎的验收与单元测试（unittest）。

运行：python3 -m unittest discover -s tests -v
"""

import pathlib
import time
import unittest

from anchor import (
    compute_mapping,
    format_tsv,
    is_candidate,
    lev_within,
    split_lines,
)
from report import render_html

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAIRS = ROOT / "samples" / "pairs"
EXPECTED = ROOT / "samples" / "expected"


def read_lines(path):
    return split_lines(path.read_text(encoding="utf-8"))


def case_names():
    return sorted(p.name for p in PAIRS.iterdir() if p.is_dir())


class TestSamples(unittest.TestCase):
    """八组样例：映射与期望文件逐字节一致。"""

    def run_case(self, name):
        old = read_lines(PAIRS / name / "old.txt")
        new = read_lines(PAIRS / name / "new.txt")
        mapping, pairs, stats = compute_mapping(old, new)
        return old, new, mapping, pairs, stats

    def test_all_samples_byte_exact(self):
        for name in case_names():
            with self.subTest(case=name):
                _, _, mapping, _, _ = self.run_case(name)
                want = (EXPECTED / (name + ".tsv")).read_text(encoding="utf-8")
                self.assertEqual(format_tsv(mapping), want)

    def test_determinism(self):
        for name in case_names():
            with self.subTest(case=name):
                first = format_tsv(self.run_case(name)[2])
                second = format_tsv(self.run_case(name)[2])
                self.assertEqual(first, second)

    def test_mapping_validity(self):
        """每个锚定的新行号都是候选，且两两不同、随旧行号严格递增。"""
        for name in case_names():
            with self.subTest(case=name):
                old, new, mapping, pairs, stats = self.run_case(name)
                used = set()
                prev = 0
                for i, j in enumerate(mapping, 1):
                    if j is None:
                        continue
                    self.assertTrue(is_candidate(old[i - 1], new[j - 1]),
                                    "(%d, %d) 不是候选" % (i, j))
                    self.assertNotIn(j, used)
                    self.assertGreater(j, prev)
                    used.add(j)
                    prev = j
                # pairs 与 mapping 一致，stats 与 pairs 一致
                self.assertEqual([(i, j) for i, j, _ in pairs],
                                 [(i, j) for i, j in enumerate(mapping, 1)
                                  if j is not None])
                e, s, t = stats
                self.assertEqual(e, sum(1 for _, _, x in pairs if x))
                self.assertEqual(s, sum(1 for _, _, x in pairs if not x))
                self.assertEqual(t, sum(abs(j - i) for i, j, _ in pairs))


class TestLevWithin(unittest.TestCase):
    def test_basic(self):
        self.assertTrue(lev_within("abc", "abc", 0))
        self.assertFalse(lev_within("abc", "abd", 0))
        self.assertTrue(lev_within("abc", "abd", 1))
        self.assertTrue(lev_within("abc", "abcd", 1))
        self.assertTrue(lev_within("abcd", "abc", 1))
        self.assertFalse(lev_within("abc", "xyz", 2))
        self.assertTrue(lev_within("abc", "xyz", 3))

    def test_threshold_boundary(self):
        # 07-mixed 的边界对：10 码位改 4 处，相似度恰好 0.6
        self.assertTrue(lev_within("slot=A17x9", "slot=B18y4", 4))
        self.assertFalse(lev_within("slot=A17x9", "slot=B18y4", 3))
        self.assertFalse(lev_within("slot=C24k6", "slot=D35m7", 4))

    def test_length_prune(self):
        self.assertFalse(lev_within("a" * 6, "b" * 6 + "c" * 10, 3))


class TestSplitLines(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(split_lines(""), [])

    def test_trailing_newline(self):
        self.assertEqual(split_lines("a\nb\n"), ["a", "b"])
        self.assertEqual(split_lines("\n"), [""])
        self.assertEqual(split_lines("a\n\n"), ["a", ""])

    def test_cr_is_plain_char(self):
        self.assertEqual(split_lines("a\rb\n"), ["a\rb"])


class TestEdgeCases(unittest.TestCase):
    def test_both_empty(self):
        mapping, pairs, stats = compute_mapping([], [])
        self.assertEqual(mapping, [])
        self.assertEqual(pairs, [])
        self.assertEqual(stats, (0, 0, 0))
        self.assertEqual(format_tsv(mapping), "")

    def test_one_side_empty(self):
        mapping, _, _ = compute_mapping(["x", "y"], [])
        self.assertEqual(mapping, [None, None])
        mapping, _, _ = compute_mapping([], ["x"])
        self.assertEqual(mapping, [])

    def test_only_blank_lines(self):
        mapping, _, _ = compute_mapping(["", "", ""], ["", ""])
        self.assertEqual(mapping, [1, 2, None])

    def test_identical(self):
        lines = ["第 %d 行" % i for i in range(1, 101)]
        mapping, _, stats = compute_mapping(lines, list(lines))
        self.assertEqual(mapping, list(range(1, 101)))
        self.assertEqual(stats, (100, 0, 0))

    def test_full_rewrite(self):
        old = ["甲" * 20 + str(i) for i in range(50)]
        new = ["乙" * 20 + str(i) for i in range(50)]
        mapping, _, _ = compute_mapping(old, new)
        self.assertEqual(mapping, [None] * 50)

    def test_high_freq_bigram_still_candidates(self):
        # 共享二元组全部落在高频桶时也不得漏候选：
        # 每行只差首字符，彼此都是相似候选，应逐行锚定
        old = ["旧%06d" % i for i in range(50)]
        new = ["新%06d" % i for i in range(50)]
        mapping, _, stats = compute_mapping(old, new)
        self.assertEqual(mapping, list(range(1, 51)))
        self.assertEqual(stats, (0, 50, 0))

    def test_short_line_length_gap(self):
        # 短行对长行：计数阈值 <= 0 时也要兜底判定
        old = ["abcdef"]
        new = ["XaXbXcXdef"]
        self.assertTrue(is_candidate(old[0], new[0]))
        mapping, _, _ = compute_mapping(old, new)
        self.assertEqual(mapping, [1])

    def test_duplicate_order(self):
        # 重复行按先后依次配对，多出来的一侧记 deleted
        old = ["头"] + ["块"] * 3 + ["尾"]
        new = ["头"] + ["块"] * 2 + ["尾"]
        mapping, _, _ = compute_mapping(old, new)
        self.assertEqual(mapping, [1, 2, 3, None, 4])

    def test_move_not_followed(self):
        # 整段搬家：保序的一侧留下，搬走的一侧记 deleted
        old = ["A", "B", "C", "D", "E"]
        new = ["A", "D", "E", "B", "C"]
        mapping, _, _ = compute_mapping(old, new)
        self.assertEqual(mapping[0], 1)
        self.assertEqual(mapping[3], 2)
        self.assertEqual(mapping[4], 3)
        self.assertIsNone(mapping[1])
        self.assertIsNone(mapping[2])


class TestScalePerformance(unittest.TestCase):
    def test_scale_budget(self):
        old = read_lines(PAIRS / "08-scale" / "old.txt")
        new = read_lines(PAIRS / "08-scale" / "new.txt")
        start = time.time()
        mapping, _, _ = compute_mapping(old, new)
        elapsed = time.time() - start
        want = (EXPECTED / "08-scale.tsv").read_text(encoding="utf-8")
        self.assertEqual(format_tsv(mapping), want)
        self.assertLessEqual(elapsed, 30, "08-scale 用时 %.1fs 超预算" % elapsed)


class TestReport(unittest.TestCase):
    def test_report_self_contained(self):
        old = read_lines(PAIRS / "07-mixed" / "old.txt")
        new = read_lines(PAIRS / "07-mixed" / "new.txt")
        mapping, pairs, stats = compute_mapping(old, new)
        html = render_html(old, new, mapping, pairs, stats)
        self.assertIn('<script type="application/json" id="anchor-data">', html)
        self.assertNotIn("fetch(", html)
        self.assertNotIn("http://", html.replace("http://www.w3.org/2000/svg", ""))
        self.assertNotIn("https://", html)
        self.assertNotIn("src=", html)
        self.assertNotIn("href=", html)
        # 汇总数字来自引擎输出
        self.assertIn('"E":%d' % stats[0], html)
        self.assertIn('"S":%d' % stats[1], html)
        self.assertIn('"T":%d' % stats[2], html)
        # 行内容原样内联（含可能被误认为标签的文本也已转义）
        self.assertIn("slot=A17x9", html)

    def test_report_escapes_script_tag(self):
        old = ["</script><script>alert(1)</script>"]
        mapping, pairs, stats = compute_mapping(old, old)
        html = render_html(old, old, mapping, pairs, stats)
        self.assertNotIn("</script><script>alert", html)


if __name__ == "__main__":
    unittest.main()
