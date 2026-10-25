# -*- coding: utf-8 -*-
"""生成专利版棋盘校对图（SVG）：
  六边形 + 三方网格 + 九宫高亮 + 三角区 + 三条地带 + A-O/1-9 全部编号

【编号口径（2026-09-24 校正，两处曾写错）】
  ① 行字母：魏 = A-E、**吴 = K-O**、**蜀 = F-J**。
     曾写成 `{2:"FGHIJ", 3:"KLMNO"}` —— 把蜀/吴的字母**整条对调**了。
     依据（看棋盘原图上印的字母，不作几何推导）：
       蜀的名字在右上扇区，其字母线 F G H I J 贴**右下侧边**；
       吴的名字在左上扇区，其字母线 K L M N O 贴**顶边**。
     老师 2026-09-24 原话：「这 svg 的吴国（左侧）与右侧蜀国的英文字母
     应该要调换一下才正确，和原版图的吴国、蜀国的字母不一样。」
  ② 列数字：**图中数字 = 10 − 引擎列**。
     曾写成 `{c}`（数字 = 引擎列），会把整个数字线**左右镜像**。
     依据：棋盘原图上魏底边的「1」贴最左端、字母 E 紧邻这个「1」；
     而引擎里魏 row1 的**列 9 在最左**（列 1 最右，x=+52.02）。
     故左端 = 列9 = 数字1。老师另给出的「A6→F5 = 33.93、A6→K5 = 47.47」
     只有把 A6 当 `1-5-4` 才成立，是同一口径的旁证。

  ⚠️ 与 `web/board.js` 的 `coordLabel()` 必须保持**同一口径**
  （那里已于同日修好，两处一致后网页与校对图才能互相对照）。
"""
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
DOCS = os.path.join(ROOT, "docs")
# 数据源：引擎权威坐标表（旧路径 docs/_board_data.json 已不存在）
DATA = os.path.join(ROOT, "server", "data", "board_135.json")
data = json.load(open(DATA, encoding="utf-8"))
P = {k: (v["x"], v["y"]) for k, v in data["points"].items()}
LN = data["lines"]

#   行字母：r=5(最内) -> 索引0，r=1(底线) -> 索引4
LETTER = {1: "ABCDE", 2: "KLMNO", 3: "FGHIJ"}


def code(k):
    """3 位编号 -> 专利版字母编号
       A=魏最内(row5) ... E=魏底线(row1)；F-J 蜀(右下侧边)；K-O 吴(顶边)。
       图中数字 = 10 − 引擎列（引擎列 1 = 该方最右端，故图中「1」= 该方最左端）。"""
    a, r, c = map(int, k.split("-"))
    return f"{LETTER[a][5 - r]}{10 - c}"      # r=5 -> 索引0 -> A/K/F


SC, PAD = 3.6, 10


def sx(x):
    return (x + 118) * SC + PAD


def sy(y):
    return (118 - y) * SC + PAD


W = int(236 * SC + 2 * PAD)
sv = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{W}" viewBox="0 0 {W} {W}">',
      '<rect width="100%" height="100%" fill="#fdfbf6"/>']

hexv = [(104.0439, 0), (52.0219, 90.1046), (-52.0219, 90.1046),
        (-104.0439, 0), (-52.0219, -90.1046), (52.0219, -90.1046)]

# 三条地带（半透明填充）
bands = [
    ("赤壁", ["1-5-5", "1-5-9", "2-5-1", "2-5-5"], "#fde68a"),
    ("荆州", ["2-5-5", "2-5-9", "3-5-1", "3-5-5"], "#fca5a5"),
    ("祁山", ["3-5-5", "3-5-9", "1-5-1", "1-5-5"], "#bbf7d0"),
]
for name, keys, col in bands:
    pts = " ".join(f"{sx(P[k][0]):.1f},{sy(P[k][1]):.1f}" for k in keys)
    sv.append(f'<polygon points="{pts}" fill="{col}" opacity="0.42" stroke="{col}" stroke-width="1"/>')
    cx = sum(P[k][0] for k in keys) / 4
    cy = sum(P[k][1] for k in keys) / 4
    sv.append(f'<text x="{sx(cx):.1f}" y="{sy(cy):.1f}" font-size="15" fill="#7c5a12" '
              f'text-anchor="middle" opacity="0.6" font-weight="bold">{name}</text>')

# 六边形
sv.append('<polygon points="' + " ".join(f"{sx(x):.1f},{sy(y):.1f}" for x, y in hexv) +
          '" fill="none" stroke="#a8874a" stroke-width="3"/>')

# 九宫区域（行1-3 × 列4-6）高亮
GONG = {1: "#dbeafe", 2: "#fee2e2", 3: "#dcfce7"}
for a in (1, 2, 3):
    ks = [f"{a}-{r}-{c}" for r in (1, 2, 3) for c in (4, 5, 6)]
    ring = [f"{a}-1-4", f"{a}-1-6", f"{a}-3-6", f"{a}-3-4"]
    pts = " ".join(f"{sx(P[k][0]):.1f},{sy(P[k][1]):.1f}" for k in ring)
    sv.append(f'<polygon points="{pts}" fill="{GONG[a]}" stroke="#94a3b8" '
              f'stroke-width="1.2" stroke-dasharray="4 3" opacity="0.85"/>')

# 网格线
for chain in LN:
    if len(chain) < 2:
        continue
    d = " ".join(f"{'M' if i == 0 else 'L'}{sx(P[k][0]):.1f},{sy(P[k][1]):.1f}" for i, k in enumerate(chain))
    sv.append(f'<path d="{d}" fill="none" stroke="#59503f" stroke-width="1.4" opacity="0.8"/>')

# 中心三角区
tri = ["1-5-5", "3-5-5", "2-5-5"]
pts = " ".join(f"{sx(P[k][0]):.1f},{sy(P[k][1]):.1f}" for k in tri)
sv.append(f'<polygon points="{pts}" fill="#c7d2fe" stroke="#4338ca" stroke-width="2.4" opacity="0.9"/>')
sv.append(f'<text x="{sx(0):.1f}" y="{sy(-2):.1f}" font-size="14" fill="#312e81" '
          'text-anchor="middle" font-weight="bold">中心三角区</text>')

# 点（三方着色）
COL = {1: "#1d4ed8", 2: "#b91c1c", 3: "#15803d"}
for k, (x, y) in P.items():
    a = int(k.split("-")[0])
    sv.append(f'<circle cx="{sx(x):.1f}" cy="{sy(y):.1f}" r="6.0" fill="#fff" '
              f'stroke="{COL[a]}" stroke-width="2.2"/>')

# 编号（全部 135 个，小字）
for k, (x, y) in P.items():
    a = int(k.split("-")[0])
    sv.append(f'<text x="{sx(x):.1f}" y="{sy(y) - 9:.1f}" font-size="10.5" fill="{COL[a]}" '
              f'text-anchor="middle" font-family="monospace">{code(k)}</text>')

sv.append("</svg>")
out = os.path.join(DOCS, "专利版棋盘_DXF校对.svg")
open(out, "w", encoding="utf-8").write("\n".join(sv))
print(f"已生成 {out}")
print("示例编号：", [(k, code(k)) for k in ("1-5-1", "1-5-4", "1-5-5", "2-5-5", "3-5-5", "1-1-5")])
