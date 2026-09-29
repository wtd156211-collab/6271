"""把锚定结果渲染成一页自包含 HTML：数据内联、不 fetch、不引外部资源。

页面只渲染、不重算：所有行号、状态与汇总数字都取自引擎输出，
引擎结果整体内联在 <script type="application/json" id="anchor-data"> 里。
"""

import json

__all__ = ["render_html"]

_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>行级锚定报告</title>
<style>
  body { font: 13px/1.45 -apple-system, "Segoe UI", "PingFang SC", sans-serif;
         margin: 0; color: #24292f; }
  header { position: sticky; top: 0; z-index: 2; padding: 10px 16px;
           background: #1f2933; color: #e6e6e6; }
  header h1 { font-size: 15px; margin: 0 0 4px; }
  header .stat { display: inline-block; margin-right: 18px; }
  header .num { color: #7bf1a8; font-weight: 600; }
  .legend { color: #9aa4b0; margin-left: 8px; }
  .sw { display: inline-block; width: 10px; height: 10px; border-radius: 2px;
        margin: 0 4px 0 10px; vertical-align: -1px; }
  #view { display: flex; align-items: flex-start; }
  .col { flex: 1 1 0; min-width: 0; }
  .colhead { position: sticky; top: 57px; z-index: 1; background: #f0f2f5;
             color: #57606a; font-weight: 600; padding: 4px 8px; }
  .row { display: flex; height: 22px; line-height: 22px; white-space: nowrap; }
  .ln { flex: 0 0 64px; text-align: right; padding-right: 8px;
        color: #8b949e; font-family: ui-monospace, Menlo, Consolas, monospace; }
  .tx { font-family: ui-monospace, Menlo, Consolas, monospace;
        overflow: hidden; text-overflow: ellipsis; padding-right: 8px; }
  .row.del { background: #f0f0f0; color: #a8a8a8; }
  .row.del .tx { text-decoration: line-through; }
  .row.free .tx { color: #b6bec7; }
  #links { flex: 0 0 160px; display: block; }
</style>
</head>
<body>
<header>
  <h1>行级锚定报告</h1>
  <span id="summary"></span>
  <span class="legend"><span class="sw" style="background:#2e7d32"></span>精确
  <span class="sw" style="background:#e65100"></span>相似
  <span class="sw" style="background:#c0c0c0"></span>已删除 / 未锚定</span>
</header>
<div id="view">
  <div class="col"><div class="colhead">旧版</div><div id="old-col"></div></div>
  <svg id="links" width="160"></svg>
  <div class="col"><div class="colhead">新版</div><div id="new-col"></div></div>
</div>
<script type="application/json" id="anchor-data">
__ANCHOR_DATA__
</script>
<script>
(function () {
  "use strict";
  var data = JSON.parse(document.getElementById("anchor-data").textContent);
  var ROW = 22, W = 160;
  var s = data.summary;
  document.getElementById("summary").innerHTML =
    '<span class="stat">旧版 <span class="num">' + s.oldCount + '</span> 行</span>' +
    '<span class="stat">新版 <span class="num">' + s.newCount + '</span> 行</span>' +
    '<span class="stat">精确配对 E = <span class="num">' + s.E + '</span></span>' +
    '<span class="stat">相似配对 S = <span class="num">' + s.S + '</span></span>' +
    '<span class="stat">已删除 <span class="num">' + s.deleted + '</span> 行</span>' +
    '<span class="stat">行号差之和 T = <span class="num">' + s.T + '</span></span>';

  function makeRow(lineNo, text, cls) {
    var row = document.createElement("div");
    row.className = "row" + (cls ? " " + cls : "");
    var ln = document.createElement("span");
    ln.className = "ln";
    ln.textContent = lineNo;
    var tx = document.createElement("span");
    tx.className = "tx";
    tx.textContent = text;
    tx.title = text;
    row.appendChild(ln);
    row.appendChild(tx);
    return row;
  }

  var mappedOld = {}, mappedNew = {}, kindOf = {};
  data.pairs.forEach(function (p) {
    mappedOld[p[0]] = p[1];
    mappedNew[p[1]] = p[0];
    kindOf[p[0] + "," + p[1]] = p[2];
  });

  var oldCol = document.getElementById("old-col");
  data.old.forEach(function (text, idx) {
    var no = idx + 1;
    oldCol.appendChild(makeRow(no, text, mappedOld[no] ? "" : "del"));
  });
  var newCol = document.getElementById("new-col");
  data.new.forEach(function (text, idx) {
    var no = idx + 1;
    newCol.appendChild(makeRow(no, text, mappedNew[no] ? "" : "free"));
  });

  var rows = Math.max(data.old.length, data.new.length);
  var svg = document.getElementById("links");
  svg.setAttribute("height", rows * ROW);
  svg.setAttribute("viewBox", "0 0 " + W + " " + rows * ROW);
  var NS = "http://www.w3.org/2000/svg";
  data.pairs.forEach(function (p) {
    var y1 = (p[0] - 1) * ROW + ROW / 2;
    var y2 = (p[1] - 1) * ROW + ROW / 2;
    var path = document.createElementNS(NS, "path");
    path.setAttribute("d", "M0," + y1 + " C" + W / 2 + "," + y1 + " " +
      W / 2 + "," + y2 + " " + W + "," + y2);
    path.setAttribute("fill", "none");
    path.setAttribute("stroke", p[2] === "exact" ? "#2e7d32" : "#e65100");
    path.setAttribute("stroke-width", p[2] === "exact" ? "1.2" : "2");
    path.setAttribute("stroke-opacity", "0.55");
    svg.appendChild(path);
  });
})();
</script>
</body>
</html>
"""


def render_html(old, new, mapping, pairs, stats):
    """old/new 为行列表，mapping 为引擎输出，pairs 为 (旧, 新, 是否精确) 列表，
    stats 为 (E, S, T)。返回自包含 HTML 字符串。"""
    e, s, t = stats
    data = {
        "old": list(old),
        "new": list(new),
        "pairs": [[i, j, "exact" if exact else "similar"] for i, j, exact in pairs],
        "summary": {
            "E": e,
            "S": s,
            "T": t,
            "deleted": sum(1 for j in mapping if j is None),
            "oldCount": len(old),
            "newCount": len(new),
        },
    }
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    # 防止行内容里的 "</script>" 提前闭合脚本块
    payload = payload.replace("<", "\\u003c")
    return _PAGE.replace("__ANCHOR_DATA__", payload)
