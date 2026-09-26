"""行级锚定引擎。

给旧版、新版两个行序列，按 README 第二节的口径求「旧行号 → 新行号」
的最优保序匹配：

- 候选：精确（内容完全相同），或相似（min(len) >= 6 且
  lev * 10 <= 4 * max(len)，即相似度 >= 0.6 的闭区间）。
- 择优：精确数 E 最大 → 相似数 S 最大 → 行号差之和 T 最小 →
  按旧行号升序的新行号序列字典序最小（未配对视为无穷大）。
- 每个旧行最多配一个新行，每个新行最多被一个旧行配对，
  配对的旧行号与新行号同时严格递增。

全过程只用确定性数据结构，同一输入重复运行结果逐字节一致。
"""

from array import array
from bisect import bisect_left

from .levenshtein import lev

# 相似判定所需的最小行长度。
MIN_SIMILAR_LEN = 6

# 把 (E, S, -T) 三级目标压成一个整数：E 占两个 BASE 位，S 占一个，
# -T 占最低位。BASE 取得足够大，任何合法输入都不会溢出位。
_BASE = 1 << 62
_W_EXACT = _BASE * _BASE
_W_SIMILAR = _BASE


def split_lines(text):
    """按 \\n 切行；行尾换行不算行内容；空行占一个行号。"""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _similar_cutoff(la, lb):
    """相似候选的编辑距离上限：lev <= 4 * max(len) / 10（闭区间）。"""
    return (4 * (la if la >= lb else lb)) // 10


# 倒排表里超过这个长度的 bigram 视为高频，计数时跳过（完备性见下）。
_SKIP_LIMIT = 64

# 索引条数不超过这个值时用字典索引（更快），否则用排序数组（省内存）。
_DICT_INDEX_LIMIT = 4_000_000


def _shared_floor(length, skipped):
    """共享 bigram 数（多重集、位置对齐）的必要下界。

    lev(a, b) <= floor(0.4 * L)（L = max(la, lb)）时，每次编辑最多毁掉
    2 个 bigram，故两侧位置对齐的共享 bigram 至少 L - 1 - 2 * d 个；
    再减去旧行一侧被跳过（高频）的 bigram 实例数，仍然保持必要。
    """
    d = (4 * length) // 10
    return length - 1 - 2 * d - skipped


def _find_similar_pairs(old_lines, new_lines, new_lens):
    """用二元组（bigram）倒排索引找相似候选对。

    完备性：min(la, lb) >= 6 且 lev(a, b) <= floor(0.4 * max(la, lb)) 时，
    两侧位置对齐的共享 bigram 数至少为 _shared_floor(max(la, lb), 0) >= 1，
    且每个幸存 bigram 的位置偏移不超过编辑距离本身。因此按
    「共享 bigram + 位置偏移 + 共享数下界」过滤不会漏掉任何相似候选。
    高频 bigram（倒排表超长）跳过计数、按 _shared_floor 的 skipped 项
    修正下界；若某旧行修正后下界不足 1，则该行退化为不跳过，保证完备。

    索引两种实现，对外都是「key -> (新行号序列, 长度)」：条数少时用
    字典（快），条数多时用排序数组 + 二分（每条 8 字节，省内存）；
    位置偏移在验证时用 str.find 做窗口检查（C 速度）。
    """
    total = sum(
        len(line) - 1 for line in new_lines if len(line) >= MIN_SIMILAR_LEN
    )
    if total <= _DICT_INDEX_LIMIT:
        index = {}
        for j, line in enumerate(new_lines, 1):
            if len(line) < MIN_SIMILAR_LEN:
                continue
            for p in range(len(line) - 1):
                key = (ord(line[p]) << 21) | ord(line[p + 1])
                bucket = index.get(key)
                if bucket is None:
                    index[key] = [j]
                else:
                    bucket.append(j)

        def postings(key):
            bucket = index.get(key)
            if bucket is None:
                return (), 0
            return bucket, len(bucket)
    else:
        # 紧凑路径：(bigram键 << j位数) | 新行号 排序后二分。
        jbits = max(1, len(new_lines).bit_length())
        if 42 + jbits > 62:
            raise ValueError("新行数超出索引可打包的范围")
        shift = jbits
        jmask = (1 << shift) - 1
        entries = array("Q")
        put = entries.append
        for j, line in enumerate(new_lines, 1):
            if len(line) < MIN_SIMILAR_LEN:
                continue
            for p in range(len(line) - 1):
                key = (ord(line[p]) << 21) | ord(line[p + 1])
                put((key << shift) | j)
        entries = array("Q", sorted(entries))

        def postings(key):
            lo = bisect_left(entries, key << shift)
            hi = bisect_left(entries, (key + 1) << shift)
            return _ArrayPostings(entries, lo, hi, jmask), hi - lo

    pairs = []  # (i, j)，均为 1 起行号
    for i, a in enumerate(old_lines, 1):
        la = len(a)
        if la < MIN_SIMILAR_LEN:
            continue
        grams = [None] * (la - 1)
        skipped = 0
        for p in range(la - 1):
            key = (ord(a[p]) << 21) | ord(a[p + 1])
            bucket, count = postings(key)
            grams[p] = (bucket, count)
            if count > _SKIP_LIMIT:
                skipped += 1
        # 修正后下界对一切兼容长度都必须 >= 1，否则该行不能跳过。
        if _shared_floor(la, skipped) < 1:
            skipped = 0
        hits = {}
        for p in range(la - 1):
            bucket, count = grams[p]
            if count == 0:
                continue
            if skipped and count > _SKIP_LIMIT:
                continue
            gram = a[p:p + 2]
            for j in bucket:
                lb = new_lens[j]
                d = _similar_cutoff(la, lb)
                lendiff = la - lb if la >= lb else lb - la
                if lendiff > d:
                    continue
                # 幸存 bigram 的位置偏移不超过编辑距离：在 b 的
                # [p-d, p+d] 窗口内必须能找到这个 bigram。
                start = p - d
                if start < 0:
                    start = 0
                if new_lines[j - 1].find(gram, start, p + d + 2) < 0:
                    continue
                hits[j] = hits.get(j, 0) + 1
        for j, count in hits.items():
            length = la if la >= new_lens[j] else new_lens[j]
            if count < _shared_floor(length, skipped):
                continue
            b = new_lines[j - 1]
            if b == a:
                continue  # 内容相同属于精确候选，不重复记
            if lev(a, b) <= _similar_cutoff(la, new_lens[j]):
                pairs.append((i, j))
    return pairs


class _ArrayPostings:
    """排序数组索引里的一个倒排段。"""

    __slots__ = ("entries", "lo", "hi", "jmask")

    def __init__(self, entries, lo, hi, jmask):
        self.entries = entries
        self.lo = lo
        self.hi = hi
        self.jmask = jmask

    def __iter__(self):
        entries = self.entries
        jmask = self.jmask
        for t in range(self.lo, self.hi):
            yield entries[t] & jmask


def find_candidates(old_lines, new_lines):
    """返回每个旧行的候选列表：cand[i] = [(新行号, 是否精确), ...]，按新行号升序。"""
    n = len(old_lines)
    new_lens = [0] + [len(line) for line in new_lines]  # 1 起

    cand = [[] for _ in range(n + 1)]
    # 精确候选：按内容分组，组内两侧行号两两组合。
    by_content = {}
    for j, line in enumerate(new_lines, 1):
        bucket = by_content.get(line)
        if bucket is None:
            by_content[line] = [j]
        else:
            bucket.append(j)
    for i, line in enumerate(old_lines, 1):
        bucket = by_content.get(line)
        if bucket:
            cand[i] = [(j, True) for j in bucket]

    # 相似候选：倒排索引 + 编辑距离验证。
    for i, j in _find_similar_pairs(old_lines, new_lines, new_lens):
        cand[i].append((j, False))

    for i in range(1, n + 1):
        if len(cand[i]) > 1:
            cand[i].sort()
    return cand


class _FenwickMax:
    """树状数组，维护前缀最大值。"""

    __slots__ = ("n", "t")

    def __init__(self, n):
        self.n = n
        self.t = [0] * (n + 1)

    def update(self, i, v):
        t = self.t
        n = self.n
        while i <= n:
            if v > t[i]:
                t[i] = v
            i += i & -i

    def query(self, i):
        r = 0
        t = self.t
        while i > 0:
            if t[i] > r:
                r = t[i]
            i -= i & -i
        return r


def compute_mapping(old_lines, new_lines):
    """求最优保序匹配。

    返回 (mapping, stats)：
    - mapping：长度等于旧行数的列表，mapping[i-1] 是新行号（1 起）或 None（deleted）；
    - stats：{'E', 'S', 'T', 'deleted'}。
    """
    n = len(old_lines)
    m = len(new_lines)
    cand = find_candidates(old_lines, new_lines)

    # 摊平候选对，按旧行号分组、组内按新行号升序。
    pair_j = []       # 新行号
    pair_w = []       # 权重（标量化后的 (E, S, -T)）
    pair_exact = []   # 是否精确
    lines_pairs = []  # 每个旧行的 pair 下标区间
    for i in range(1, n + 1):
        idxs = []
        for j, is_exact in cand[i]:
            pair_j.append(j)
            pair_w.append((_W_EXACT if is_exact else _W_SIMILAR) - abs(j - i))
            pair_exact.append(is_exact)
            idxs.append(len(pair_j) - 1)
        lines_pairs.append(idxs)

    # 反向 DP：g[p] = 以 p 开头的最优链值。树状数组按新行号取后缀最大。
    bit = _FenwickMax(m)
    g = [0] * len(pair_j)
    for i in range(n, 0, -1):
        idxs = lines_pairs[i - 1]
        if not idxs:
            continue
        pending = []
        for p in idxs:
            x = m + 1 - pair_j[p]          # j' > j  <=>  x' < x
            best_after = bit.query(x - 1)  # 旧行号更大、新行号更大的最优链
            gv = pair_w[p] + best_after
            g[p] = gv
            pending.append((x, gv))
        for x, gv in pending:
            bit.update(x, gv)

    optimum = bit.query(m)

    # 贪心还原：按旧行号升序，能配则配（字典序上 配对 < deleted），
    # 同一旧行取可行的新行号最小者。pair 可行当且仅当 g[p] == 当前剩余最优值。
    mapping = [None] * n
    remaining = optimum
    last_j = 0
    stats = {"E": 0, "S": 0, "T": 0, "deleted": 0}
    for i in range(1, n + 1):
        if remaining == 0:
            break
        for p in lines_pairs[i - 1]:
            j = pair_j[p]
            if j <= last_j:
                continue
            if g[p] == remaining:
                mapping[i - 1] = j
                remaining -= pair_w[p]
                last_j = j
                if pair_exact[p]:
                    stats["E"] += 1
                else:
                    stats["S"] += 1
                stats["T"] += abs(j - i)
                break
    stats["deleted"] = n - stats["E"] - stats["S"]
    return mapping, stats


def mapping_to_tsv(mapping):
    """映射写成 TSV：`<旧行号>\\t<新行号>` 或 `<旧行号>\\tdeleted`，末尾有换行。"""
    out = []
    for i, j in enumerate(mapping, 1):
        out.append("%d\t%s\n" % (i, j if j is not None else "deleted"))
    return "".join(out)


def pair_kinds(old_lines, new_lines, mapping):
    """每个旧行的锚定状态：'exact' / 'similar' / 'deleted'。"""
    kinds = []
    for i, j in enumerate(mapping, 1):
        if j is None:
            kinds.append("deleted")
        elif old_lines[i - 1] == new_lines[j - 1]:
            kinds.append("exact")
        else:
            kinds.append("similar")
    return kinds
