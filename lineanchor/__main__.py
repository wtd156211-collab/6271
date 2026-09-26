"""命令行入口：

    python3 -m lineanchor OLD NEW [-o MAPPING.tsv] [--html REPORT.html]

OLD 是改版前的版本，NEW 是改版后的版本。
不加 -o 时把映射 TSV 写到标准输出。
"""

import argparse
import sys

from .engine import compute_mapping, mapping_to_tsv, pair_kinds, split_lines
from .report import render_html


def _read_lines(path):
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return split_lines(fh.read())


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="lineanchor",
        description="行级锚定：输出旧版每一行在新版中的行号，或标为 deleted。",
    )
    parser.add_argument("old", help="改版前的文件")
    parser.add_argument("new", help="改版后的文件")
    parser.add_argument("-o", "--output", help="映射结果 TSV（缺省写到标准输出）")
    parser.add_argument("--html", help="同时生成自包含的 HTML 核对报告")
    args = parser.parse_args(argv)

    old_lines = _read_lines(args.old)
    new_lines = _read_lines(args.new)

    mapping, stats = compute_mapping(old_lines, new_lines)
    tsv = mapping_to_tsv(mapping)

    if args.output:
        with open(args.output, "w", encoding="utf-8", newline="") as fh:
            fh.write(tsv)
    else:
        sys.stdout.write(tsv)

    if args.html:
        kinds = pair_kinds(old_lines, new_lines, mapping)
        html = render_html(old_lines, new_lines, mapping, kinds, stats)
        with open(args.html, "w", encoding="utf-8", newline="") as fh:
            fh.write(html)

    return 0


if __name__ == "__main__":
    sys.exit(main())
