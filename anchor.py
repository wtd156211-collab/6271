"""行级锚定引擎：给同一文件的新旧两个版本，输出旧行号 -> 新行号的映射。

口径（与 README 第二节一致）：
- 行按 \\n 切分，行号 1 起，比较按码位，不做任何归一化；
- 候选：精确（a == b），或相似（min(len) >= 6 且 lev * 10 <= 4 * max(len)）；
- 匹配保序（旧行号、新行号同时严格递增），每个旧行最多配一个新行，反之亦然；
- 择优顺序：精确数 E 最大 -> 相似数 S 最大 -> 行号差之和 T 最小 ->
  按旧行号升序的新行号序列字典序最小；
- 未配对的旧行记 deleted。

只依赖标准库；不读时钟、不读随机数，同一输入输出逐字节一致。
"""

from bisect import bisect_left, bisect_right

__all__ = [
    "split_lines",
    "lev_within",
    "is_candidate",
    "exact_candidates",
    "similar_candidates",
    "compute_mapping",
    "format_tsv",
]

# 单一内容组（同一行内容在一侧的全部出现）允许展开的精确候选对数上限。
# 超过上限时按出现次序加窗裁剪（k 号出现只配次序相近的出现），
# 正常样例与构造输入远达不到该上限，仅为防止病态重复输入撑爆内存。
EXACT_GROUP_CAP = 200_000
EXACT_GROUP_WINDOW = 16

# 二元组倒排桶的大小上限；超过即视为高频二元组，不计入计数（用 U 修正阈值）。
BIGRAM_BUCKET_CAP = 100


def split_lines(text):
    """按 \\n 切行；行尾换行不算行内容；空文件得到 0 行。"""
    if text == "":
        return []
    lines = text.split("\n")
    if text.endswith("\n"):
        lines.pop()
    return lines


def lev_within(a, b, limit):
    """码位级编辑距离 lev(a, b) <= limit 时返回 True，否则 False。

    改、增、删各计 1。带剪枝的带状动态规划，只关心是否超过 limit。
    """
    la, lb = len(a), len(b)
    if la > lb:
        a, b = b, a
        la, lb = lb, la
    if lb - la > limit:
        return False
    inf = limit + 1
    prev = list(range(lb + 1))
    for j in range(limit + 1, lb + 1):
        prev[j] = inf
    for i in range(1, la + 1):
        cur = [inf] * (lb + 1)
        if i <= limit:
            cur[0] = i
        ca = a[i - 1]
        jlo = i - limit
        if jlo < 1:
            jlo = 1
        jhi = i + limit
        if jhi > lb:
            jhi = lb
        prow = prev
        for j in range(jlo, jhi + 1):
            v = prow[j - 1]
            if b[j - 1] != ca:
                v += 1
            x = prow[j] + 1
            if x < v:
                v = x
            x = cur[j - 1] + 1
            if x < v:
                v = x
            if v > limit:
                v = inf
            cur[j] = v
        prev = cur
    return prev[lb] <= limit


def is_candidate(a, b):
    """按口径判断旧行 a 与新行 b 是否构成候选（精确或相似）。"""
    if a == b:
        return True
    la, lb = len(a), len(b)
    mx = la if la > lb else lb
    mn = la if la < lb else lb
    if mn < 6:
        return False
    return lev_within(a, b, (4 * mx) // 10)


def exact_candidates(old, new):
    """精确候选：内容相同的所有 (旧行号, 新行号) 对。"""
    new_groups = {}
    for j, line in enumerate(new, 1):
        slot = new_groups.get(line)
        if slot is None:
            new_groups[line] = [j]
        else:
            slot.append(j)
    old_groups = {}
    for i, line in enumerate(old, 1):
        if line in new_groups:
            slot = old_groups.get(line)
            if slot is None:
                old_groups[line] = [i]
            else:
                slot.append(i)
    pairs = []
    for line, js in new_groups.items():
        o = old_groups.get(line)
        if o is None:
            continue
        p, q = len(o), len(js)
        if p * q <= EXACT_GROUP_CAP:
            for i in o:
                for j in js:
                    pairs.append((i, j))
        else:
            # 安全阀：病态重复时按出现次序加窗，k 号旧出现只配次序相近的新出现。
            w = (p - q) if p > q else (q - p)
            w += EXACT_GROUP_WINDOW
            for r, i in enumerate(o):
                lo = r - w
                if lo < 0:
                    lo = 0
                hi = r + w + 1
                if hi > q:
                    hi = q
                for s in range(lo, hi):
                    pairs.append((i, js[s]))
    return pairs


def _bigrams_packed(line, id_bits, line_no, out):
    """把一行全部码位二元组打包成整数追加到 out：(bigram << id_bits) | line_no。"""
    prev = ord(line[0])
    shift = id_bits
    for k in range(1, len(line)):
        cur = ord(line[k])
        out.append((((prev << 21) | cur) << shift) | line_no)
        prev = cur


def similar_candidates(old, new):
    """相似候选：min(len) >= 6 且 lev * 10 <= 4 * max(len) 且内容不同的行对。

    用二元组倒排索引做不漏候选的过滤：
    - 若 lev(a, b) <= d，则 a 的二元组多重集与 b 的交集大小 >= (len(a)-1) - 2d
      （每次编辑至多毁掉 a 的 2 个二元组），故必共享至少一个二元组；
    - 高频二元组（桶大于 BIGRAM_BUCKET_CAP）不展开，改用 U 修正计数阈值，
      保证过滤条件仍是候选的必要条件。
    """
    m = len(new)
    if m == 0 or len(old) == 0:
        return []
    id_bits = max(1, m.bit_length())
    mask = (1 << id_bits) - 1

    packed = []
    for j in range(1, m + 1):
        line = new[j - 1]
        if len(line) >= 6:
            _bigrams_packed(line, id_bits, j, packed)
    packed.sort()

    count = [0] * (m + 1)
    # 新行按长度排序，供兜底枚举按长度带取行
    by_len = sorted((len(line), j) for j, line in enumerate(new, 1))
    lengths = [x[0] for x in by_len]
    hi_cache = {}

    def len_hi(la):
        # Lb > la 时长度相容（Lb - la <= (4*Lb)//10）的最大 Lb
        hi = hi_cache.get(la)
        if hi is None:
            hi = la
            while hi + 1 - la <= (4 * (hi + 1)) // 10:
                hi += 1
            hi_cache[la] = hi
        return hi

    pairs = []
    for i in range(1, len(old) + 1):
        a = old[i - 1]
        la = len(a)
        if la < 6:
            continue
        touched = []
        u = 0  # a 的二元组中出现于高频桶的个数
        prev_cp = ord(a[0])
        for k in range(1, la):
            cur_cp = ord(a[k])
            bg = (prev_cp << 21) | cur_cp
            prev_cp = cur_cp
            key = bg << id_bits
            lo = bisect_left(packed, key)
            hi = bisect_left(packed, key + (1 << id_bits), lo)
            if hi - lo > BIGRAM_BUCKET_CAP:
                u += 1
                continue
            for t in range(lo, hi):
                jid = packed[t] & mask
                if count[jid] == 0:
                    touched.append(jid)
                count[jid] += 1
        la1 = la - 1
        need = la1 - u  # 候选必要条件：count >= need - 2*dmax
        for jid in touched:
            b = new[jid - 1]
            lb = len(b)
            mx = la if la > lb else lb
            dmax = (4 * mx) // 10
            mn = la if la < lb else lb
            if mx - mn <= dmax and count[jid] >= need - 2 * dmax and b != a:
                if lev_within(a, b, dmax):
                    pairs.append((i, jid))
        # 兜底：共享二元组计数为 0 的新行（未被触碰）在 need - 2*dmax <= 0
        # 时同样满足必要条件，必须逐一用编辑距离判定，否则会漏候选。
        # 按长度带枚举：Lb <= la 时条件是 need <= 2*((4*la)//10)；
        # Lb > la 时条件是 2*((4*Lb)//10) >= need，且 Lb 不超过 len_hi(la)。
        dmax_self = (4 * la) // 10
        ranges = []
        if need <= 2 * dmax_self:
            lo_len = la - dmax_self
            if lo_len < 6:
                lo_len = 6
            ranges.append((lo_len, la))
        if need <= 0:
            lo2 = la + 1
        else:
            # 最小的 L 使 2*((4*L)//10) >= need
            lo2 = (5 * need) // 4
            while 2 * ((4 * lo2) // 10) < need:
                lo2 += 1
            if lo2 < la + 1:
                lo2 = la + 1
        hi2 = len_hi(la)
        if lo2 <= hi2:
            ranges.append((lo2, hi2))
        for lo_len, hi_len in ranges:
            s = bisect_left(lengths, lo_len)
            e = bisect_left(lengths, hi_len + 1)
            for t in range(s, e):
                jid = by_len[t][1]
                if count[jid] != 0:
                    continue
                b = new[jid - 1]
                if b == a:
                    continue
                lb = lengths[t]
                mx = la if la > lb else lb
                if lev_within(a, b, (4 * mx) // 10):
                    pairs.append((i, jid))
        for jid in touched:
            count[jid] = 0
    return pairs


def compute_mapping(old, new):
    """计算映射。返回 (mapping, pairs, stats)：

    - mapping：长度为 len(old) 的列表，mapping[i-1] 是旧行 i 对应的新行号或 None；
    - pairs：[(旧行号, 新行号, 是否精确), ...]，按旧行号升序；
    - stats：(E, S, T)，精确配对数、相似配对数、行号差之和。
    """
    n, m = len(old), len(new)
    cands = [(i, j, True) for i, j in exact_candidates(old, new)]
    cands.extend((i, j, False) for i, j in similar_candidates(old, new))
    cands.sort()

    # 带权保序匹配：g(c) = 以 c 开头的最优链的 (E, S, -T)。
    # 按旧行号降序处理，用树状数组维护「行号更大、列号更大」的最优值。
    tree = [None] * (m + 2)

    def query(j):
        # 列号 > j 的最大值：反向坐标下前缀 [1, m-j] 的最大值
        x = m - j
        best = None
        while x > 0:
            v = tree[x]
            if v is not None and (best is None or v > best):
                best = v
            x -= x & -x
        return best

    def update(j, val):
        x = m + 1 - j
        while x <= m:
            v = tree[x]
            if v is None or val > v:
                tree[x] = val
            x += x & -x

    gvals = {}
    optimum = (0, 0, 0)
    pos = len(cands)
    while pos > 0:
        # 取同一旧行号的一段（cands 已按 (i, j) 排序）
        row_i = cands[pos - 1][0]
        start = pos - 1
        while start > 0 and cands[start - 1][0] == row_i:
            start -= 1
        pending = []
        for k in range(start, pos):
            _, j, exact = cands[k]
            best = query(j)
            if exact:
                cost = (1, 0, -abs(j - row_i))
            else:
                cost = (0, 1, -abs(j - row_i))
            if best is None:
                g = cost
            else:
                g = (cost[0] + best[0], cost[1] + best[1], cost[2] + best[2])
            gvals[(row_i, j)] = g
            if g > optimum:
                optimum = g
            pending.append((j, g))
        for j, g in pending:
            update(j, g)
        pos = start

    # 每列（新行号）：g 值 -> 该列取到该 g 值的旧行号升序列表
    colmap = {}
    for i, j, _exact in cands:
        g = gvals[(i, j)]
        col = colmap.get(j)
        if col is None:
            col = colmap[j] = {}
        lst = col.get(g)
        if lst is None:
            col[g] = [i]
        else:
            lst.append(i)

    # 贪心还原字典序最小的最优解：每一步取能延续出最优解的最小新行号，
    # 并列时取最小旧行号。
    mapping = [None] * n
    pairs = []
    value = (0, 0, 0)
    i_cur = 0
    j_cur = 0
    while True:
        target = (optimum[0] - value[0], optimum[1] - value[1], optimum[2] - value[2])
        found = None
        j = j_cur + 1
        while j <= m:
            col = colmap.get(j)
            if col is not None:
                lst = col.get(target)
                if lst is not None:
                    k = bisect_right(lst, i_cur)
                    if k < len(lst):
                        found = (lst[k], j)
                        break
            j += 1
        if found is None:
            break
        i, j = found
        if old[i - 1] == new[j - 1]:
            cost = (1, 0, -abs(j - i))
            exact = True
        else:
            cost = (0, 1, -abs(j - i))
            exact = False
        value = (value[0] + cost[0], value[1] + cost[1], value[2] + cost[2])
        mapping[i - 1] = j
        pairs.append((i, j, exact))
        i_cur, j_cur = i, j

    stats = (value[0], value[1], -value[2])
    return mapping, pairs, stats


def format_tsv(mapping):
    """映射 -> TSV 文本：每行 `<旧行号>\\t<新行号|deleted>`，末尾有换行。"""
    out = []
    for i, j in enumerate(mapping, 1):
        if j is None:
            out.append("%d\tdeleted" % i)
        else:
            out.append("%d\t%d" % (i, j))
    if not out:
        return ""
    return "\n".join(out) + "\n"
