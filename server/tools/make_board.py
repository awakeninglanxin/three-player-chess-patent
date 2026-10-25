# -*- coding: utf-8 -*-
"""从 DXF 生成权威棋盘数据（points/lines/labels）+ SVG 可视化。"""
import collections
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "..", "..", "docs")
pts = [tuple(p) for p in json.load(open(os.path.join(DOCS, "_dxf_data.json"),
                                        encoding="utf-8"))["points"]]
lines = [[tuple(p) for p in L] for L in json.load(open(os.path.join(DOCS, "_dxf_lines.json"),
                                                       encoding="utf-8"))]

LAYER_LINES = {1: [22, 12, 11, 10, 9], 3: [36, 26, 25, 24, 23], 2: [50, 40, 39, 38, 37]}
RIGHT = {1: (1.0, 0.0), 3: (-0.5, math.sqrt(3) / 2), 2: (-0.5, -math.sqrt(3) / 2)}
ARMY_CN = {1: "魏", 2: "蜀", 3: "吴"}
COLOR = {1: "#2b6cb0", 2: "#c53030", 3: "#2f855a"}


def key(p):
    return (round(p[0], 2), round(p[1], 2))


# 编号
grid = {}          # (army,row,col) -> (x,y)
pos2id = {}        # key -> (army,row,col)
for army, ids in LAYER_LINES.items():
    rx, ry = RIGHT[army]
    for row, lid in enumerate(ids, start=1):
        L = lines[lid]
        pr = sorted(L, key=lambda p: -(p[0] * rx + p[1] * ry))
        for col, p in enumerate(pr, start=1):
            grid[(army, row, col)] = p
            pos2id[key(p)] = (army, row, col)

print(f"编号点数: {len(grid)}")

# 邻接（用 key 匹配）
k2rc = {key(p): rc for rc, p in grid.items()}
adj = collections.defaultdict(set)
for L in lines:
    for i in range(len(L) - 1):
        a, b = key(L[i]), key(L[i + 1])
        if a != b and a in k2rc and b in k2rc:
            adj[k2rc[a]].add(k2rc[b])
            adj[k2rc[b]].add(k2rc[a])

# 每点度数
deg = {rc: len(v) for rc, v in adj.items()}

# ---------- 线段表（用于渲染/车炮走法） ----------
seg_list = []
for L in lines:
    chain = [k2rc[key(p)] for p in L if key(p) in k2rc]
    seg_list.append(chain)

# ---------- 保存 board_data.json ----------
data = {
    "unit": "DXF 单位；六边形外接圆半径 104.0439，边长 104.0439，边心距 90.1046",
    "points": {f"{a}-{r}-{c}": {"x": round(p[0], 4), "y": round(p[1], 4),
                                "deg": deg.get((a, r, c), 0)}
               for (a, r, c), p in sorted(grid.items())},
    "lines": [["%d-%d-%d" % rc for rc in chain] for chain in seg_list if len(chain) > 1],
    "adj": {f"{a}-{r}-{c}": ["%d-%d-%d" % t for t in sorted(v)]
            for (a, r, c), v in sorted(adj.items())},
}
out = os.path.join(DOCS, "_board_data.json")
json.dump(data, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"已保存 {out}：{len(data['points'])} 点，{len(data['lines'])} 线")

# ---------- SVG 可视化 ----------
SC = 3.1
W2 = 118


def sx(x):
    return (x + W2) * SC


def sy(y):
    return (W2 - y) * SC


sv = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{2 * W2 * SC:.0f}" '
      f'height="{2 * W2 * SC:.0f}" viewBox="0 0 {2 * W2 * SC:.0f} {2 * W2 * SC:.0f}">',
      f'<rect width="100%" height="100%" fill="#fbf8f1"/>']

# 六边形
hexv = [(104.0439, 0), (52.0219, 90.1046), (-52.0219, 90.1046),
        (-104.0439, 0), (-52.0219, -90.1046), (52.0219, -90.1046)]
sv.append('<polygon points="' +
          " ".join(f"{sx(x):.1f},{sy(y):.1f}" for x, y in hexv) +
          '" fill="#fffdf8" stroke="#b9a06a" stroke-width="2.5"/>')

# 线
for chain in seg_list:
    if len(chain) < 2:
        continue
    d = " ".join(
        f"{'M' if i == 0 else 'L'}{sx(grid[rc][0]):.1f},{sy(grid[rc][1]):.1f}"
        for i, rc in enumerate(chain))
    sv.append(f'<path d="{d}" fill="none" stroke="#6b6255" stroke-width="1.3" opacity="0.75"/>')

# 点
for (a, r, c), p in grid.items():
    col = COLOR[a]
    rad = 5.2 if deg.get((a, r, c), 0) >= 4 else 4.2
    sv.append(f'<circle cx="{sx(p[0]):.1f}" cy="{sy(p[1]):.1f}" r="{rad}" '
              f'fill="#fff" stroke="{col}" stroke-width="2"/>')

# 编号（只标三方底线 + 最内层，避免太乱）
for (a, r, c), p in grid.items():
    if r in (1, 5):
        sv.append(f'<text x="{sx(p[0]):.1f}" y="{sy(p[1]) - 8:.1f}" font-size="11" '
                  f'fill="{col}" text-anchor="middle" font-family="monospace">{r}{c}</text>')

# 中心三角区
tri = [(0, -16.934), (14.666, 8.467), (-14.666, 8.467)]
sv.append('<polygon points="' +
          " ".join(f"{sx(x):.1f},{sy(y):.1f}" for x, y in tri) +
          '" fill="#dbeafe" stroke="#3b82f6" stroke-width="2" opacity="0.85"/>')
sv.append(f'<text x="{sx(0):.1f}" y="{sy(0) + 5:.1f}" font-size="13" fill="#1d4ed8" '
          'text-anchor="middle" font-weight="bold">中心三角区</text>')

sv.append("</svg>")
out_svg = os.path.join(DOCS, "专利版棋盘_DXF重建.svg")
open(out_svg, "w", encoding="utf-8").write("\n".join(sv))
print(f"已生成 {out_svg}")

# 统计
print("\n=== 每方度数分布 ===")
for a in (1, 2, 3):
    dd = collections.Counter(deg.get((a, r, c), 0) for r in range(1, 6) for c in range(1, 10))
    print(f"  {ARMY_CN[a]}: {dict(sorted(dd.items()))}")
