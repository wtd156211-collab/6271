"""自包含 HTML 核对报告。

数据内联在 <script type="application/json" id="anchor-data"> 里，
页面只渲染、不重算：行号、连线、状态、汇总数字全部取自内联数据。
不 fetch、不引用任何外部资源，双击即开。
"""

import json

_KIND_LABEL = {"exact": "精确", "similar": "相似", "deleted": "已删除"}

_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>行级锚定核对报告</title>
<style>
  :root {
    --row-h: 22px;
    --exact: #2e9e5b;
    --similar: #e09f00;
    --deleted: #9aa0a6;
    --line-num: #8a8f98;
    --border: #e2e4e8;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 16px 20px 32px;
    font: 13px/1.5 -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    color: #1f2329; background: #fafbfc;
  }
  h1 { font-size: 17px; margin: 0 0 10px; }
  #summary { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 12px; }
  .chip {
    padding: 3px 12px; border-radius: 12px; background: #fff;
    border: 1px solid var(--border); font-variant-numeric: tabular-nums;
  }
  .chip b { margin-left: 6px; }
  .chip.exact b { color: var(--exact); }
  .chip.similar b { color: var(--similar); }
  .chip.deleted b { color: var(--deleted); }
  #legend { margin: 0 0 14px; color: #5f6368; font-size: 12px; }
  .sw { display: inline-block; width: 10px; height: 10px; border-radius: 2px;
        margin: 0 4px 0 12px; vertical-align: -1px; }
  #board { display: flex; align-items: flex-start; gap: 0; }
  .pane { flex: 0 0 auto; width: 42%; }
  .pane h2 {
    margin: 0 0 6px; font-size: 13px; color: #5f6368; font-weight: 600;
    position: sticky; top: 0; background: #fafbfc; padding: 2px 0;
  }
  .row {
    display: flex; height: var(--row-h); line-height: var(--row-h);
    white-space: pre; overflow: hidden; text-overflow: ellipsis;
    font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
    font-size: 12px; border-bottom: 1px solid #f0f1f3; padding-right: 8px;
  }
  .ln {
    flex: 0 0 4.5em; text-align: right; padding-right: 8px;
    color: var(--line-num); font-variant-numeric: tabular-nums;
    border-right: 1px solid var(--border); margin-right: 8px;
  }
  .row.exact .txt { color: #1f2329; }
  .row.similar .txt { color: #8a6500; }
  .row.deleted .txt, .row.deleted .ln { color: var(--deleted); }
  .row.deleted .txt { text-decoration: line-through; }
  .row.unmatched .txt, .row.unmatched .ln { color: var(--deleted); }
  .row.hot { background: #fff3c4; }
  #mid { flex: 1 1 auto; min-width: 120px; }
  #mid svg { display: block; width: 100%; }
  line.exact { stroke: var(--exact); stroke-width: 1.2; opacity: .75; }
  line.similar { stroke: var(--similar); stroke-width: 1.2; opacity: .85; }
  line.hot { stroke-width: 2.5; opacity: 1; }
</style>
</head>
<body>
<h1>行级锚定核对报告</h1>
<div id="summary"></div>
<p id="legend">状态：
  <span class="sw" style="background:var(--exact)"></span>精确
  <span class="sw" style="background:var(--similar)"></span>相似
  <span class="sw" style="background:var(--deleted)"></span>已删除 / 未锚定
  —— 连线由引擎输出的映射生成，灰色行没有对应。
</p>
<div id="board">
  <div class="pane" id="pane-old"><h2>旧版</h2><div id="col-old"></div></div>
  <div id="mid"><svg id="links" aria-hidden="true"></svg></div>
  <div class="pane" id="pane-new"><h2>新版</h2><div id="col-new"></div></div>
</div>
<script type="application/json" id="anchor-data">
__DATA__
</script>
<script>
(function () {
  "use strict";
  var data = JSON.parse(document.getElementById("anchor-data").textContent);
  var oldLines = data.old, newLines = data["new"];
  var map = data.map, kinds = data.kind, stats = data.stats;
  var n = oldLines.length, m = newLines.length;
  var ROW_H = 22;

  var summary = document.getElementById("summary");
  [["exact", "精确配对 E", stats.E],
   ["similar", "相似配对 S", stats.S],
   ["deleted", "已删除", stats.deleted],
   ["", "行号差之和 T", stats.T],
   ["", "旧版行数", n],
   ["", "新版行数", m]].forEach(function (item) {
    var chip = document.createElement("span");
    chip.className = "chip" + (item[0] ? " " + item[0] : "");
    chip.textContent = item[1];
    var b = document.createElement("b");
    b.textContent = String(item[2]);
    chip.appendChild(b);
    summary.appendChild(chip);
  });

  function buildColumn(host, lines, kindOf) {
    var frag = document.createDocumentFragment();
    for (var idx = 0; idx < lines.length; idx++) {
      var row = document.createElement("div");
      row.className = "row " + kindOf(idx);
      row.id = host.id + "-" + (idx + 1);
      var ln = document.createElement("span");
      ln.className = "ln";
      ln.textContent = String(idx + 1);
      var txt = document.createElement("span");
      txt.className = "txt";
      txt.textContent = lines[idx];
      row.appendChild(ln);
      row.appendChild(txt);
      frag.appendChild(row);
    }
    host.appendChild(frag);
  }

  var matchedNew = {};
  for (var i = 0; i < n; i++) if (map[i] > 0) matchedNew[map[i]] = true;

  buildColumn(document.getElementById("col-old"), oldLines,
    function (idx) { return kinds[idx]; });
  buildColumn(document.getElementById("col-new"), newLines,
    function (idx) { return matchedNew[idx + 1] ? "exact" : "unmatched"; });

  var height = Math.max(n, m) * ROW_H;
  var svg = document.getElementById("links");
  svg.setAttribute("height", String(height));
  var NS = "http://www.w3.org/2000/svg";
  var wires = [];
  for (var oi = 0; oi < n; oi++) {
    var nj = map[oi];
    if (nj <= 0) continue;
    var wire = document.createElementNS(NS, "line");
    wire.setAttribute("x1", "0");
    wire.setAttribute("y1", String(oi * ROW_H + ROW_H / 2));
    wire.setAttribute("x2", "100%");
    wire.setAttribute("y2", String((nj - 1) * ROW_H + ROW_H / 2));
    wire.setAttribute("class", kinds[oi]);
    wire.dataset.old = String(oi + 1);
    svg.appendChild(wire);
    wires.push(wire);
  }

  function hot(oldNo, on) {
    wires.forEach(function (w) {
      if (w.dataset.old === String(oldNo)) w.classList.toggle("hot", on);
    });
    var mapJ = map[oldNo - 1];
    [["col-old-", oldNo], ["col-new-", mapJ]].forEach(function (p) {
      if (p[1] > 0) {
        var el = document.getElementById(p[0] + p[1]);
        if (el) el.classList.toggle("hot", on);
      }
    });
  }
  document.getElementById("col-old").addEventListener("mouseover", function (ev) {
    var row = ev.target.closest ? ev.target.closest(".row") : null;
    if (row) hot(row.id.split("-").pop(), true);
  });
  document.getElementById("col-old").addEventListener("mouseout", function (ev) {
    var row = ev.target.closest ? ev.target.closest(".row") : null;
    if (row) hot(row.id.split("-").pop(), false);
  });
})();
</script>
</body>
</html>
"""


def _escape_for_script(text):
    # JSON 嵌进 <script>：转义 < 防止 </script> 提前闭合，顺带处理 & 和 >。
    return text.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")


def render_html(old_lines, new_lines, mapping, kinds, stats):
    """把映射结果渲染成一页自包含 HTML。所有数字直接取自入参，不重算。"""
    data = {
        "old": list(old_lines),
        "new": list(new_lines),
        "map": [j if j is not None else 0 for j in mapping],
        "kind": list(kinds),
        "stats": {
            "E": stats["E"],
            "S": stats["S"],
            "T": stats["T"],
            "deleted": stats["deleted"],
        },
    }
    payload = _escape_for_script(json.dumps(data, ensure_ascii=False))
    return _PAGE.replace("__DATA__", payload)
