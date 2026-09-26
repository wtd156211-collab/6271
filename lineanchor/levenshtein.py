"""码位级编辑距离（Levenshtein）。

改、增、删各计 1，按 Python str 的码位比较，不做任何归一化。
实现采用 Myers 位并行算法：把较短的串编成位向量，扫描另一个串时
整列 DP 用整数的位运算一次推进。纯标准库、确定性，长串也快。
"""


def lev(a, b):
    """返回 a 与 b 的码位级编辑距离。"""
    if a == b:
        return 0
    # 较短的串当模式（位数少），较长的串当文本。
    if len(a) > len(b):
        a, b = b, a
    m = len(a)
    if m == 0:
        return len(b)

    masks = {}
    for i, ch in enumerate(a):
        masks[ch] = masks.get(ch, 0) | (1 << i)

    full = (1 << m) - 1
    top = 1 << (m - 1)
    vp = full
    vn = 0
    score = m
    get = masks.get
    for ch in b:
        x = get(ch, 0) | vn
        d0 = (((x & vp) + vp) ^ vp) | x
        hn = vp & d0
        hp = vn | (~(vp | d0) & full)
        # 低位要补 1：边界行 D[0][j] 的水平增量恒为 +1。
        xs = ((hp << 1) | 1) & full
        vn = xs & d0
        vp = ((hn << 1) & full) | (~(xs | d0) & full)
        if hp & top:
            score += 1
        if hn & top:
            score -= 1
    return score
