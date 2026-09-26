import json
import os
import random
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lineanchor import (
    compute_mapping,
    find_candidates,
    lev,
    mapping_to_tsv,
    pair_kinds,
    split_lines,
)
from lineanchor.report import render_html

ROOT = os.path.join(os.path.dirname(__file__), "..")
PAIRS = os.path.join(ROOT, "samples", "pairs")
EXPECTED = os.path.join(ROOT, "samples", "expected")
CASES = [
    "01-insert", "02-delete", "03-move", "04-edit",
    "05-dup", "06-rewrite", "07-mixed", "08-scale",
]

_INF = float("inf")


def _naive_lev(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[-1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _is_candidate(a, b):
    """候选的独立判定：精确，或 min(len)>=6 且 lev*10 <= 4*max(len)。"""
    if a == b:
        return True
    la, lb = len(a), len(b)
    return min(la, lb) >= 6 and _naive_lev(a, b) * 10 <= 4 * max(la, lb)


def _brute_force(old_lines, new_lines):
    """枚举全部合法保序匹配，按 README 2.3 的四级顺序取最优。

    第四级：按旧行号升序的新行号序列取字典序最小，deleted 视为无穷大。
    """
    n, m = len(old_lines), len(new_lines)
    cand = [
        [_is_candidate(old_lines[i], new_lines[j]) for j in range(m)]
        for i in range(n)
    ]
    mapping = [None] * n
    best = []

    def rec(i, last_j, exact, similar, tdiff):
        if i == n:
            seq = tuple(j if j is not None else _INF for j in mapping)
            key = (-exact, -similar, tdiff, seq)
            if not best or key < best[0]:
                best[:] = [key, list(mapping)]
            return
        rec(i + 1, last_j, exact, similar, tdiff)
        for j in range(last_j + 1, m):
            if cand[i][j]:
                mapping[i] = j
                rec(
                    i + 1, j,
                    exact + (old_lines[i] == new_lines[j]),
                    similar + (old_lines[i] != new_lines[j]),
                    tdiff + abs(j - i),
                )
                mapping[i] = None

    rec(0, -1, 0, 0, 0)
    return [j + 1 if j is not None else None for j in best[1]]


def _random_lines(rng, count):
    pool = [
        "",
        "M-01 巡检台账的封面页，版本号与册号都要填",
        "M-02 采集口径按日切分，跨日按自然日归属",
        "slot=A17x9",
        "slot=B18y4",
        "slot=C24k6",
        "分册线",
        "x",
        "台账",
    ]
    lines = []
    for _ in range(count):
        base = rng.choice(pool)
        if base and rng.random() < 0.3:
            pos = rng.randrange(len(base))
            ch = rng.choice("ab台9x")
            base = base[:pos] + ch + base[pos + 1:]
        lines.append(base)
    return lines


def _random_pair(rng, n, m):
    """从同一底稿演化出两个版本，覆盖增删改移与重复。"""
    old = _random_lines(rng, n)
    new = list(old)
    for _ in range(rng.randrange(0, 4)):
        if not new:
            break
        op = rng.random()
        pos = rng.randrange(len(new))
        if op < 0.35:
            new.insert(pos, rng.choice(_random_lines(rng, 2) + [new[pos]]))
        elif op < 0.7:
            new.pop(pos)
        else:
            new[pos] = _random_lines(rng, 1)[0]
    new = (new + _random_lines(rng, max(0, m - len(new))))[:m]
    return old, new


class TestLev(unittest.TestCase):
    def test_against_naive(self):
        rng = random.Random(20260927)
        for alphabet, maxlen, count in [
            ("ab", 12, 4000),
            ("abc台账口径 slot=A17x9，。", 30, 1500),
            ("abcdef台x9", 80, 200),
        ]:
            for _ in range(count):
                a = "".join(rng.choice(alphabet) for _ in range(rng.randrange(maxlen)))
                b = "".join(rng.choice(alphabet) for _ in range(rng.randrange(maxlen)))
                self.assertEqual(lev(a, b), _naive_lev(a, b), (a, b))

    def test_basic(self):
        self.assertEqual(lev("", ""), 0)
        self.assertEqual(lev("", "abc"), 3)
        self.assertEqual(lev("kitten", "sitting"), 3)
        self.assertEqual(lev("slot=A17x9", "slot=B18y4"), 4)


class TestSplitLines(unittest.TestCase):
    def test_cases(self):
        self.assertEqual(split_lines(""), [])
        self.assertEqual(split_lines("\n"), [""])
        self.assertEqual(split_lines("a\n"), ["a"])
        self.assertEqual(split_lines("a\nb\n"), ["a", "b"])
        self.assertEqual(split_lines("a\n\nb\n"), ["a", "", "b"])
        self.assertEqual(split_lines("a\nb"), ["a", "b"])


class TestSamples(unittest.TestCase):
    def test_all_cases_byte_identical(self):
        for name in CASES:
            with self.subTest(case=name):
                with open(os.path.join(PAIRS, name, "old.txt"), encoding="utf-8") as fh:
                    old = split_lines(fh.read())
                with open(os.path.join(PAIRS, name, "new.txt"), encoding="utf-8") as fh:
                    new = split_lines(fh.read())
                mapping, _ = compute_mapping(old, new)
                got = mapping_to_tsv(mapping)
                with open(os.path.join(EXPECTED, name + ".tsv"), encoding="utf-8") as fh:
                    want = fh.read()
                self.assertEqual(got, want)
                self.assertTrue(want.endswith("\n"))

    def test_determinism(self):
        for name in CASES:
            with self.subTest(case=name):
                with open(os.path.join(PAIRS, name, "old.txt"), encoding="utf-8") as fh:
                    old = split_lines(fh.read())
                with open(os.path.join(PAIRS, name, "new.txt"), encoding="utf-8") as fh:
                    new = split_lines(fh.read())
                first = mapping_to_tsv(compute_mapping(old, new)[0])
                second = mapping_to_tsv(compute_mapping(old, new)[0])
                self.assertEqual(first, second)


class TestBruteForce(unittest.TestCase):
    def test_random_small(self):
        rng = random.Random(4471)
        for trial in range(300):
            n = rng.randrange(0, 8)
            m = rng.randrange(0, 8)
            old, new = _random_pair(rng, n, m)
            with self.subTest(trial=trial, old=old, new=new):
                got, _ = compute_mapping(old, new)
                want = _brute_force(old, new)
                self.assertEqual(got, want)

    def test_exhaustive_tiny_alphabet(self):
        rng = random.Random(9)
        alphabet = ["", "aa", "ab", "台账"]
        for trial in range(200):
            old = [rng.choice(alphabet) for _ in range(rng.randrange(0, 7))]
            new = [rng.choice(alphabet) for _ in range(rng.randrange(0, 7))]
            with self.subTest(trial=trial):
                self.assertEqual(
                    compute_mapping(old, new)[0], _brute_force(old, new)
                )


class TestMappingProperties(unittest.TestCase):
    def _check(self, old, new, mapping):
        self.assertEqual(len(mapping), len(old))
        seen = []
        for i, j in enumerate(mapping):
            if j is None:
                continue
            self.assertTrue(1 <= j <= len(new))
            self.assertTrue(
                _is_candidate(old[i], new[j - 1]),
                "锚定对不是候选: (%d, %d)" % (i + 1, j),
            )
            seen.append(j)
        self.assertEqual(len(seen), len(set(seen)), "新行号重复")
        self.assertEqual(seen, sorted(seen), "新行号未严格递增")

    def test_samples(self):
        for name in CASES:
            with self.subTest(case=name):
                with open(os.path.join(PAIRS, name, "old.txt"), encoding="utf-8") as fh:
                    old = split_lines(fh.read())
                with open(os.path.join(PAIRS, name, "new.txt"), encoding="utf-8") as fh:
                    new = split_lines(fh.read())
                mapping, _ = compute_mapping(old, new)
                self._check(old, new, mapping)

    def test_random(self):
        rng = random.Random(80)
        for _ in range(100):
            old, new = _random_pair(rng, rng.randrange(0, 15), rng.randrange(0, 15))
            mapping, _ = compute_mapping(old, new)
            self._check(old, new, mapping)


class TestCandidates(unittest.TestCase):
    def test_threshold_boundary(self):
        # 相似度恰好 0.6：lev=4, max len=10, 4*10 <= 4*10，闭区间算候选。
        cand = find_candidates(["slot=A17x9"], ["slot=B18y4"])
        self.assertEqual(cand[1], [(1, False)])

    def test_threshold_just_outside(self):
        # lev=5, max len=10：5*10 > 4*10，不是候选。
        cand = find_candidates(["slot=A17x9"], ["slot=C24k6"])
        self.assertEqual(cand[1], [])

    def test_min_length(self):
        # min(len) < 6 时不构成相似候选，即使只差一个字符。
        cand = find_candidates(["abcde"], ["abcdf"])
        self.assertEqual(cand[1], [])
        cand = find_candidates(["abcdef"], ["abcdex"])
        self.assertEqual(cand[1], [(1, False)])

    def test_exact_regardless_of_length(self):
        cand = find_candidates(["x", "ab"], ["ab", "x"])
        self.assertEqual(cand[1], [(2, True)])
        self.assertEqual(cand[2], [(1, True)])

    def test_exact_not_duplicated_as_similar(self):
        cand = find_candidates(["slot=A17x9"], ["slot=A17x9"])
        self.assertEqual(cand[1], [(1, True)])


class TestEdgeCases(unittest.TestCase):
    def test_both_empty(self):
        mapping, stats = compute_mapping([], [])
        self.assertEqual(mapping, [])
        self.assertEqual(mapping_to_tsv(mapping), "")

    def test_one_side_empty(self):
        mapping, _ = compute_mapping(["a", "b"], [])
        self.assertEqual(mapping, [None, None])
        mapping, _ = compute_mapping([], ["a"])
        self.assertEqual(mapping, [])

    def test_only_blank_lines(self):
        mapping, _ = compute_mapping(["", "", ""], ["", ""])
        self.assertEqual(mapping, [1, 2, None])

    def test_identical(self):
        lines = ["第%d行" % i for i in range(50)]
        mapping, stats = compute_mapping(lines, list(lines))
        self.assertEqual(mapping, list(range(1, 51)))
        self.assertEqual(stats["E"], 50)
        self.assertEqual(stats["T"], 0)

    def test_complete_rewrite(self):
        old = ["旧版内容%02d" % i for i in range(20)]
        new = ["全新文本%02d" % i for i in range(20)]
        mapping, _ = compute_mapping(old, new)
        self.assertEqual(mapping, [None] * 20)

    def test_carriage_return_is_a_normal_char(self):
        mapping, _ = compute_mapping(["abc\r"], ["abc"])
        self.assertEqual(mapping, [None])


class TestReport(unittest.TestCase):
    def test_html_report(self):
        with open(os.path.join(PAIRS, "07-mixed", "old.txt"), encoding="utf-8") as fh:
            old = split_lines(fh.read())
        with open(os.path.join(PAIRS, "07-mixed", "new.txt"), encoding="utf-8") as fh:
            new = split_lines(fh.read())
        mapping, stats = compute_mapping(old, new)
        kinds = pair_kinds(old, new, mapping)
        html = render_html(old, new, mapping, kinds, stats)

        self.assertIn('<script type="application/json" id="anchor-data">', html)
        self.assertNotIn("fetch(", html)
        self.assertNotIn("src=\"http", html)
        self.assertNotIn("href=\"http", html)

        payload = re.search(
            r'<script type="application/json" id="anchor-data">\s*(.*?)\s*</script>',
            html,
            re.S,
        ).group(1)
        data = json.loads(payload)
        self.assertEqual(data["stats"], {"E": 12, "S": 2, "T": 14, "deleted": 2})
        self.assertEqual(len(data["map"]), len(old))
        self.assertEqual(len(data["kind"]), len(old))
        self.assertEqual(data["old"], old)
        self.assertEqual(data["new"], new)

    def test_html_escapes_script_tag(self):
        old = ["</script><script>alert(1)</script>"]
        mapping, stats = compute_mapping(old, old)
        html = render_html(old, old, mapping,
                           pair_kinds(old, old, mapping), stats)
        self.assertNotIn("</script><script>alert", html)


if __name__ == "__main__":
    unittest.main()
