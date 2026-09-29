"""命令行入口：行级锚定。

用法：
    python3 main.py OLD.txt NEW.txt [-o MAPPING.tsv] [--html REPORT.html]

不带 -o 时把映射 TSV 写到标准输出。映射口径见 README 第二节。
"""

import argparse
import sys

from anchor import compute_mapping, format_tsv, split_lines
from report import render_html


def read_lines(path):
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return split_lines(fh.read())


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="line-anchor",
        description="给同一文件的新旧两个版本建立旧行号 -> 新行号的映射。",
    )
    parser.add_argument("old", help="改版前的文件")
    parser.add_argument("new", help="改版后的文件")
    parser.add_argument("-o", "--output", help="映射 TSV 输出路径（默认标准输出）")
    parser.add_argument("--html", help="同时生成自包含 HTML 报告的路径")
    args = parser.parse_args(argv)

    old = read_lines(args.old)
    new = read_lines(args.new)
    mapping, pairs, stats = compute_mapping(old, new)

    tsv = format_tsv(mapping)
    if args.output:
        with open(args.output, "w", encoding="utf-8", newline="") as fh:
            fh.write(tsv)
    else:
        sys.stdout.write(tsv)

    if args.html:
        with open(args.html, "w", encoding="utf-8", newline="") as fh:
            fh.write(render_html(old, new, mapping, pairs, stats))

    e, s, t = stats
    deleted = sum(1 for j in mapping if j is None)
    print(
        "E=%d S=%d deleted=%d T=%d" % (e, s, deleted, t),
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
