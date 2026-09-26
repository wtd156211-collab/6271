"""lineanchor：行级锚定与映射。

读入同一份文件的两个版本，按行建立「旧行号 → 新行号」的映射，
锚不上的旧行标为 deleted。口径见 README 第二节。
"""

from .engine import (
    compute_mapping,
    find_candidates,
    mapping_to_tsv,
    pair_kinds,
    split_lines,
)
from .levenshtein import lev

__all__ = [
    "compute_mapping",
    "find_candidates",
    "lev",
    "mapping_to_tsv",
    "pair_kinds",
    "split_lines",
]
